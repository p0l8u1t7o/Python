"""DEV-010（一）：電控連接圖、I/O 自動配置與連接檢查。

每個反例只改一處（刪一條供電線、改一個 I/O 位址、接錯電壓域、引用不存在的端子、加一台相機），
斷言對應檢查由通過變成失敗或同步變更；期望的受影響端子集合由範例資料推導，不寫死數量。
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from cellforge.costing import compute_costing
from cellforge.electrical import electrical_checks, resolve_electrical
from cellforge.electrical.panel import layout_panel
from cellforge.schema.costing import Costing
from cellforge.schema.electrical import Electrical, Endpoint, IoPoint
from cellforge.schema.models import Cell
from cellforge.validation import ProjectValidationError, validate_project
from cellforge.yamlio import dump_yaml, load_yaml

SOURCE = Path(__file__).resolve().parents[1] / "examples" / "ssd_press" / "handwritten"
ELECTRICAL = load_yaml(SOURCE / "electrical.yaml")
CELL = load_yaml(SOURCE / "cell.yaml")
COSTING = load_yaml(SOURCE / "costing.yaml")
CAMERA_PART = "parts/global_camera.py"


def _resolve(data=None, cell=None):
    return resolve_electrical(
        Electrical.model_validate(data or ELECTRICAL), Cell.model_validate(cell or CELL)
    )


def _checks(data=None, cell=None, **options):
    resolved = _resolve(data, cell)
    assert resolved.reference_errors == []
    return electrical_checks(resolved, **options)


def _red(items, code=None):
    return [
        item
        for item in items
        if item["severity"] == "red" and (code is None or item.get("code") == code)
    ]


def _device(data, device_id):
    return next(device for device in data["devices"] if device["id"] == device_id)


def _net_sinks(data, net_id, signal):
    """Sink terminals wired straight to a net, read from the source data."""
    sinks = set()
    for connection in data["connections"]:
        ends = (connection["from"], connection["to"])
        if {"net": net_id} not in ends:
            continue
        end = next(item for item in ends if "device" in item)
        terminal = next(
            item
            for item in _device(data, end["device"])["terminals"]
            if item["id"] == end["terminal"]
        )
        if terminal["signal"] == signal and terminal["direction"] == "sink":
            sinks.add(f"{end['device']}.{end['terminal']}")
    return sinks


def _without(data, predicate):
    changed = copy.deepcopy(data)
    removed = [item for item in changed["connections"] if predicate(item)]
    assert len(removed) == 1
    changed["connections"].remove(removed[0])
    return changed


def _add_cameras(cell, count):
    changed = copy.deepcopy(cell)
    modules = changed["machines"][0]["modules"]
    template = next(module for module in modules if module.get("part") == CAMERA_PART)
    added = []
    for index in range(count):
        module = copy.deepcopy(template)
        module["id"] = f"extra_camera_{index + 1}"
        module["pose"]["xyz"][0] += 150.0 * (index + 1)
        modules.append(module)
        added.append(module["id"])
    return changed, added


def test_ssd_example_resolves_without_reference_errors_or_red_checks():
    resolved = _resolve()
    assert resolved.reference_errors == [] and resolved.issues == []
    items = electrical_checks(resolved)
    assert _red(items) == []
    # 額定值缺少時容量檢查為未評估（黃），安全回路只呈現規劃，不會是 pass
    capacity = [item for item in items if item["status"] == "not_evaluated"]
    assert any("PS1" in item["objects"] for item in capacity)
    safety_ids = {circuit["id"] for circuit in ELECTRICAL["safety"]}
    safety = [item for item in items if "安全回路" in item["detail"]]
    assert len(safety) == len(safety_ids)
    assert all(item["status"] == "not_evaluated" for item in safety)


def test_deleting_the_24v_feed_is_a_missing_wire_and_opens_every_24v_load():
    data = _without(
        data=ELECTRICAL, predicate=lambda item: item["from"] == {"device": "PS1", "terminal": "V+"}
    )
    items = _checks(data)
    missing = _red(items, "MISSING_WIRE")
    assert any("PS1" in item["objects"] for item in missing)
    opened = _red(items, "OPEN_CIRCUIT")
    expected = _net_sinks(ELECTRICAL, "P24A", "dc_power")
    assert expected and {name for item in opened for name in item["terminals"]} >= expected
    # 原本通過
    assert _red(_checks(), "OPEN_CIRCUIT") == [] and _red(_checks(), "MISSING_WIRE") == []


def test_breaking_the_ac_branch_also_kills_the_power_supply_outputs():
    """QS1→QF1 斷線：QF1 缺接線，PS1 的 AC 輸入失電，24 V 負載連帶失電。"""
    data = _without(
        ELECTRICAL,
        lambda item: (
            item["from"] == {"device": "QS1", "terminal": "L2"}
            and item["to"] == {"device": "QF1", "terminal": "1"}
        ),
    )
    items = _checks(data)
    assert any("QF1" in item["objects"] for item in _red(items, "MISSING_WIRE"))
    opened = _red(items, "OPEN_CIRCUIT")
    terminals = {name for item in opened for name in item["terminals"]}
    assert "PS1.L" in terminals
    assert _net_sinks(ELECTRICAL, "P24A", "dc_power") <= terminals
    assert any("PS1" in item["objects"] and "未受電" in item["detail"] for item in opened)
    # 動力支路（QF2）不受控制支路斷線影響
    assert "RC1.L" not in terminals


def test_duplicate_manual_address_is_red_and_pools_skip_manual_addresses():
    assert _red(_checks(), "DUPLICATE_ADDRESS") == []
    data = copy.deepcopy(ELECTRICAL)
    manual = [point for point in data["io"] if point.get("address")]
    manual[-1]["address"] = manual[0]["address"]
    duplicate = _red(_checks(data), "DUPLICATE_ADDRESS")
    assert duplicate and manual[0]["address"] in duplicate[0]["detail"]

    resolved = _resolve()
    addresses = [(item.channel_device, item.address) for item in resolved.io]
    assert len(addresses) == len(set(addresses))
    manual_addresses = {
        (point["channel_device"], point["address"])
        for point in ELECTRICAL["io"]
        if point.get("address")
    }
    allocated = [item for item in resolved.io if item.point.address is None]
    assert allocated and all(
        (item.channel_device, item.address) not in manual_addresses for item in allocated
    )
    # 手動佔用一個原本會被自動配置的點位，自動配置改用下一個空點位而不重複
    first = allocated[0]
    data = copy.deepcopy(ELECTRICAL)
    data["io"].append(
        {
            "id": "DI-MANUAL",
            "signal": first.point.signal,
            "function": "手動指定",
            "channel_device": first.channel_device,
            "address": first.address,
        }
    )
    moved = _resolve(data)
    again = next(item for item in moved.io if item.point.id == first.point.id)
    assert again.address != first.address
    assert _red(electrical_checks(moved), "DUPLICATE_ADDRESS") == []


def test_wrong_voltage_domain_is_detected():
    data = copy.deepcopy(ELECTRICAL)
    feed = next(
        item for item in data["connections"] if item["from"] == {"device": "LC1", "terminal": "24V"}
    )
    feed["to"] = {"net": "N24A"}
    items = _checks(data)
    wrong = _red(items, "WRONG_VOLTAGE")
    assert wrong and "LC1.24V" in wrong[0]["terminals"]
    assert any("電壓不符" in item["detail"] and "LC1" in item["objects"] for item in _red(items))


def test_incompatible_signal_types_on_one_wire_are_red():
    data = copy.deepcopy(ELECTRICAL)
    data["connections"].append(
        {
            "id": "BAD-01",
            "from": {"device": "SW1", "terminal": "P8"},
            "to": {"device": "XDI", "terminal": "16"},
        }
    )
    red = [item for item in _red(_checks(data)) if "訊號型別不相容" in item["detail"]]
    assert red and {"SW1", "XDI"} <= set(red[0]["objects"])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda data: data["connections"][0]["to"].update(terminal="L9"), "不存在的端子"),
        (
            lambda data: data["connections"].append(
                {"id": "X-1", "from": {"net": "P48"}, "to": {"device": "PLC1", "terminal": "24V"}}
            ),
            "不存在的電位網",
        ),
        (
            lambda data: data["connections"].append(
                {"id": "X-2", "from": {"device": "PLC9", "terminal": "24V"}, "to": {"net": "P24A"}}
            ),
            "不存在的器件",
        ),
        (lambda data: data["io"][0].update(address="DI99"), "位址不是"),
        (lambda data: data["io"][-1].update(pool="IO9-DO"), "不存在的點位池"),
        (lambda data: data["devices"][0].update(module_ref="robot_9"), "module_ref"),
        (lambda data: data["devices"][1]["panel"].update(rail="R9"), "盤面軌道不存在"),
    ],
)
def test_undefined_references_fail_project_validation(tmp_path, change, message):
    project = tmp_path / "ssd"
    shutil.copytree(
        SOURCE, project, ignore=shutil.ignore_patterns("__pycache__", ".cellforge", "build")
    )
    data = copy.deepcopy(ELECTRICAL)
    change(data)
    dump_yaml(project / "electrical.yaml", data)
    with pytest.raises(ProjectValidationError, match=message):
        validate_project(project)


def test_endpoint_and_io_point_forms_are_validated():
    with pytest.raises(ValueError, match="其中一種"):
        Endpoint(device="PLC1")
    with pytest.raises(ValueError, match="其中一種"):
        Endpoint(net="P24A", pool="XDI")
    with pytest.raises(ValueError, match="address 或 pool"):
        IoPoint(id="A", signal="digital_in", function="x")
    with pytest.raises(ValueError, match="channel_device"):
        IoPoint(id="A", signal="digital_in", function="x", address="DI00")
    # YAML 未加引號的數字端子名稱視為字串
    assert Endpoint(device="QF1", terminal=1).terminal == "1"


def test_adding_a_camera_module_adds_device_port_trigger_and_matching_bom_quantity():
    cell, added = _add_cameras(CELL, 1)
    before, after = _resolve(), _resolve(cell=cell)
    camera = added[0]
    new_devices = set(after.devices) - set(before.devices)
    assert len(new_devices) == 1
    device = after.devices[new_devices.pop()]
    assert device.module_ref == camera and device.kind == "camera"
    # 新相機分到一個之前沒被用的影像埠與觸發點位
    ports = lambda resolved: {  # noqa: E731
        (connection.to.device, connection.to.terminal)
        for connection in resolved.connections
        if connection.from_.device
        in {d.id for d in resolved.devices.values() if d.kind == "camera"}
        and connection.to.device is not None
    }
    assert len(ports(after)) == len(ports(before)) + 1
    triggers = [
        item for item in after.io if item.generated_by and item.generated_by.endswith(camera)
    ]
    assert len(triggers) == 1
    assert (triggers[0].channel_device, triggers[0].address) not in {
        (item.channel_device, item.address) for item in before.io
    }
    # 成本依同一份 cell.yaml 增加一台相機，電控器件數與採購數量一致
    costing = Costing.model_validate(COSTING)
    cost_before = compute_costing(costing, Cell.model_validate(CELL), as_of=costing.as_of)
    cost_after = compute_costing(costing, Cell.model_validate(cell), as_of=costing.as_of)
    catalog = device.catalog_ref

    def quantity(result):
        return float(
            next(line for line in result["purchase_lines"] if line["item"] == catalog)["quantity"]
        )

    assert quantity(cost_after) == quantity(cost_before) + 1
    bom = [
        item for item in electrical_checks(after, costing=cost_after) if "採購" in item["detail"]
    ]
    assert bom == []
    # 成本沒有同步（沿用舊的採購數量）時提示不一致
    stale = [
        item for item in electrical_checks(after, costing=cost_before) if "採購" in item["detail"]
    ]
    assert stale and stale[0]["severity"] == "yellow" and catalog in stale[0]["detail"]


def test_camera_ports_run_out_when_more_cameras_than_pool_capacity():
    pool = next(item for item in ELECTRICAL["pools"] if item["id"] == "IPC1-GIGE")
    used = len(
        [
            item
            for item in _resolve().connections
            if (item.to.device, item.to.terminal)
            in {(pool["device"], name) for name in pool["terminals"]}
        ]
    )
    free = len(pool["terminals"]) - used
    fits, _ = _add_cameras(CELL, free)
    assert _red(_checks(cell=fits), "POOL_EXHAUSTED") == []
    over, _ = _add_cameras(CELL, free + 1)
    assert _red(_checks(cell=over), "POOL_EXHAUSTED")


def test_module_coverage_requires_a_device_for_each_process_module():
    required = [
        ("conveyor_1", "製程動作 transfer", None),
        ("robot_1", "手臂工具相機", "camera"),
    ]
    assert _red(_checks(required_modules=required)) == []
    data = copy.deepcopy(ELECTRICAL)
    for device in data["devices"]:
        if device.get("module_ref") == "conveyor_1":
            device["module_ref"] = None
    red = _red(_checks(data, required_modules=required))
    assert [item["objects"] for item in red] == [["conveyor_1"]]
    data = copy.deepcopy(ELECTRICAL)
    _device(data, "CAM01")["kind"] = "other"
    red = _red(_checks(data, required_modules=required))
    assert [item["objects"] for item in red] == [["robot_1"]]


def test_power_budget_is_evaluated_only_with_ratings_and_detects_overload():
    data = copy.deepcopy(ELECTRICAL)
    resolved = _resolve(data)
    capacity = next(item for item in electrical_checks(resolved) if "供電容量" in item["detail"])
    loads = [name for name in capacity["objects"] if name != "PS1"]
    rating = 10.0
    _device(data, "PS1")["ratings"] = {"output_current_a": rating}
    for name in loads:
        _device(data, name)["ratings"] = {"current_a": rating / len(loads) / 2}
    ok = next(item for item in _checks(data) if item.get("unit") == "A")
    assert ok["status"] == "pass" and ok["value"] <= ok["limit"]
    _device(data, loads[0])["ratings"] = {"current_a": rating}
    over = next(item for item in _checks(data) if item.get("unit") == "A")
    assert over["severity"] == "red" and over["value"] > over["limit"]


def test_panel_layout_overflow_and_rail_overlap_are_red():
    resolved = _resolve()
    layout = layout_panel(resolved)
    assert layout.problems == [] and layout.placements
    widest = max(layout.bands, key=lambda band: band.used_mm if band.kind != "duct" else 0)
    data = copy.deepcopy(ELECTRICAL)
    data["panel"]["width_mm"] = widest.used_mm + 2 * data["panel"]["margin_mm"] - 1
    assert any("盤面空間不足" in item["detail"] for item in _red(_checks(data)))
    data = copy.deepcopy(ELECTRICAL)
    rails = data["panel"]["rails"]
    rails[1]["y_mm"] = rails[2]["y_mm"]
    assert any("上下間距" in item["detail"] for item in _red(_checks(data)))


def test_hand_traced_di01_sensor_loop():
    """人工追線：PS1 V+ → P24A → B01 BN；B01 BK → XDI:02 → IO1 DI01；B01 BU → N24A → PS1 V-。

    期望路徑依 TestCode I/O 表（DI01、XDI:02、W-DI01）手寫，與平台程式無共用。
    """
    resolved = _resolve()
    edges = {}
    for connection in resolved.connections:
        ends = []
        for end in (connection.from_, connection.to):
            ends.append(f"net:{end.net}" if end.net else f"{end.device}:{end.terminal}")
        edges.setdefault(ends[0], []).append((ends[1], connection))
        edges.setdefault(ends[1], []).append((ends[0], connection))

    def hop(a, b):
        return [connection for other, connection in edges.get(a, []) if other == b]

    assert hop("PS1:V+", "net:P24A") and hop("B01:BN", "net:P24A")
    assert hop("B01:BU", "net:N24A") and hop("PS1:V-", "net:N24A")
    panel_wire = hop("IO1:DI01", "XDI:02")
    field_wire = hop("XDI:02", "B01:BK")
    assert panel_wire and field_wire
    assert panel_wire[0].wire_numbers == ["W-DI01"] == field_wire[0].wire_numbers
    point = next(item for item in resolved.io if item.point.id == "DI01")
    assert point.point.function == "載盤進站到位" and point.address == "DI01"


def test_build_writes_versioned_electrical_json_and_merges_l1_checks(tmp_path):
    from cellforge.build.pipeline import build_project

    project = tmp_path / "ssd"
    shutil.copytree(
        SOURCE, project, ignore=shutil.ignore_patterns("__pycache__", ".cellforge", "build")
    )
    report = build_project(project, "L0")
    version = project / ".cellforge" / report["version_id"]
    data = json.loads((version / "electrical.json").read_text("utf-8"))
    assert data["version"] == report["version"]
    assert report["electrical"]["red"] == 0
    required = {(item["module"], item["kind"]) for item in data["required_modules"]}
    assert ("robot_1", "camera") in required and ("global_camera", "camera") in required
    assert set(data["modules"]) >= {module for module, _kind in required}
    manifest = json.loads((version / "manifest.json").read_text("utf-8"))
    assert "electrical.yaml" in json.dumps(manifest["sources"], ensure_ascii=False)
