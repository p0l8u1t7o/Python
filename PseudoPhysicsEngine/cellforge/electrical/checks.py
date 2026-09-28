"""電控連接檢查：以端子、電位網與器件內部導通建立連通圖後逐項判定。

每項檢查帶 status（pass／fail／not_evaluated）與嚴重度；資料不足（例如額定電流未填）時為
not_evaluated，不以預設值推定容量合格。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .panel import layout_panel
from .resolve import ResolvedElectrical

SIGNAL_GROUPS = {
    "ac_power": "ac_power",
    "dc_power": "dc_power",
    "ground": "ground",
    "digital_in": "digital",
    "digital_out": "digital",
    "relay_contact": "digital",
    "safety": "safety",
    "analog_in": "analog",
    "analog_out": "analog",
    "ethernet": "network",
    "gige": "network",
    "fieldbus": "fieldbus",
    "serial": "serial",
    "vendor": "vendor",
}
POWER = {"ac_power", "dc_power", "ground"}


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, node: str) -> str:
        self.parent.setdefault(node, node)
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, first: str, second: str) -> None:
        self.parent[self.find(first)] = self.find(second)


def _node(endpoint) -> str:
    if endpoint.net is not None:
        return f"net:{endpoint.net}"
    return f"{endpoint.device}:{endpoint.terminal}"


def _item(index: int, severity: str, status: str, detail: str, objects: list[str], **extra):
    return {
        "id": f"CHK-ELEC-{index:03d}",
        "type": "electrical",
        "severity": severity,
        "status": status,
        "objects": objects,
        "detail": detail,
        "source": "electrical.yaml 連通圖（端子、電位網、器件內部導通）",
        **extra,
    }


def electrical_checks(
    resolved: ResolvedElectrical,
    *,
    required_modules: list[tuple[str, str, str | None]] | None = None,
    costing: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return check items.

    ``required_modules`` lists (module id, reason, required device kind or None) for equipment
    that must be tied to an electrical device through ``module_ref``.
    """

    graph = _Union()
    wired: set[str] = set()
    for connection in resolved.connections:
        first, second = _node(connection.from_), _node(connection.to)
        graph.union(first, second)
        wired.update((first, second))
    for device in resolved.devices.values():
        for left, right in device.bridges:
            graph.union(f"{device.id}:{left}", f"{device.id}:{right}")
    nets = {net.id: net for net in resolved.source.nets}
    components: dict[str, list[tuple[str, Any, Any]]] = defaultdict(list)
    for device in resolved.devices.values():
        for terminal in device.terminals:
            node = f"{device.id}:{terminal.id}"
            components[graph.find(node)].append((node, device, terminal))
    net_roots = {net_id: graph.find(f"net:{net_id}") for net_id in nets}

    items: list[dict[str, Any]] = []

    def add(severity: str, status: str, detail: str, objects: list[str], **extra) -> None:
        items.append(_item(len(items) + 1, severity, status, detail, objects, **extra))

    # 1. 缺接線：必要端子沒有任何連接
    for device in resolved.devices.values():
        for terminal in device.terminals:
            node = f"{device.id}:{terminal.id}"
            # 必要端子本身要有接線；器件內部導通（斷路器出線端有接）不能代替進線端
            if terminal.required and node not in wired:
                add(
                    "red",
                    "fail",
                    f"缺接線：{device.id}.{terminal.id}"
                    f"（{terminal.label or terminal.signal}）沒有連接",
                    [device.id],
                    suggestion="補上接線或移除不需要的必要端子宣告",
                    code="MISSING_WIRE",
                )

    # 2. 供電：受電端子必須連到同電壓域「且本身有電」的供電來源。
    #    電源器件的輸出只有在它自己的受電端子都有電時才算有電（例如 PS1 的 AC 輸入斷線，
    #    24 V 輸出也失電），以不動點迭代求出。同一連通群組、同一電壓合併為一項。
    def matches(source, sink) -> bool:
        return source.signal == sink.signal and (
            sink.voltage is None or source.voltage == sink.voltage
        )

    def power_sinks(device):
        return [
            terminal
            for terminal in device.terminals
            if terminal.signal in POWER and terminal.direction == "sink"
        ]

    live: set[str] = set()
    changed = True
    while changed:
        changed = False
        for device in resolved.devices.values():
            if device.id in live:
                continue
            if all(
                any(
                    other.id in live
                    and other_terminal.direction == "source"
                    and matches(other_terminal, terminal)
                    for _n, other, other_terminal in components[
                        graph.find(f"{device.id}:{terminal.id}")
                    ]
                    if other.id != device.id
                )
                for terminal in power_sinks(device)
            ):
                live.add(device.id)
                changed = True
    for root, members in components.items():
        if not any(node in wired for node, _d, _t in members) and not any(
            net_root == root for net_root in net_roots.values()
        ):
            continue  # 完全沒接線的端子已由缺接線報告
        sources = [
            (device, terminal)
            for _node_name, device, terminal in members
            if terminal.direction == "source" and terminal.signal in POWER
        ]
        failing: dict[tuple[str, str | None, str], list[str]] = defaultdict(list)
        dead_upstream: dict[tuple[str, str | None, str], set[str]] = defaultdict(set)
        for _node_name, device, terminal in members:
            if terminal.signal not in POWER or terminal.direction != "sink":
                continue
            candidates = [
                (other, source)
                for other, source in sources
                if other.id != device.id and matches(source, terminal)
            ]
            if any(other.id in live for other, _source in candidates):
                continue
            kind = "dead" if candidates else ("wrong" if sources else "open")
            key = (terminal.signal, terminal.voltage, kind)
            failing[key].append(f"{device.id}.{terminal.id}")
            dead_upstream[key].update(other.id for other, _source in candidates)
        on_nets = sorted(net_id for net_id, net_root in net_roots.items() if net_root == root)
        where = f"（電位網 {'、'.join(on_nets)}）" if on_nets else ""
        for (signal, voltage, kind), sinks in failing.items():
            devices = sorted({name.split(".")[0] for name in sinks})
            need = voltage or signal
            if kind == "wrong":
                found = "、".join(
                    f"{device.id}.{terminal.id}（{terminal.voltage}）"
                    for device, terminal in sources
                )
                add(
                    "red",
                    "fail",
                    f"電壓域錯誤{where}：{'、'.join(sinks)} 需要 {need}，連到的供電是 {found}",
                    [*devices, *sorted({device.id for device, _t in sources})],
                    suggestion="改接正確電壓域的電源",
                    code="WRONG_VOLTAGE",
                    terminals=sinks,
                )
            elif kind == "dead":
                upstream = sorted(dead_upstream[(signal, voltage, kind)])
                add(
                    "red",
                    "fail",
                    f"斷路{where}：上游 {'、'.join(upstream)} 本身未受電，{len(sinks)} 個受電端子"
                    f"（{need}）失電：{'、'.join(sinks)}",
                    [*devices, *upstream],
                    suggestion="檢查上游電源器件的供電連接",
                    code="OPEN_CIRCUIT",
                    terminals=sinks,
                )
            else:
                add(
                    "red",
                    "fail",
                    f"斷路{where}：{len(sinks)} 個受電端子（{need}）追不到任何供電來源："
                    f"{'、'.join(sinks)}",
                    devices,
                    suggestion="檢查供電連接、保護器件與端子排是否接通",
                    code="OPEN_CIRCUIT",
                    terminals=sinks,
                )
    # 3. 電位網電壓：端子電壓必須與所接電位網相同
    for net_id, net in nets.items():
        if net.voltage is None:
            continue
        for _node_name, device, terminal in components.get(net_roots[net_id], []):
            if terminal.voltage and terminal.voltage != net.voltage and terminal.signal in POWER:
                add(
                    "red",
                    "fail",
                    f"電壓不符：{device.id}.{terminal.id} 為 {terminal.voltage}，"
                    f"接到 {net_id}（{net.voltage}）",
                    [device.id, net_id],
                )
    # 4. 訊號相容：同一連通群組只能有一類訊號
    for root, members in components.items():
        groups = defaultdict(list)
        for _node_name, device, terminal in members:
            groups[SIGNAL_GROUPS[terminal.signal]].append(f"{device.id}.{terminal.id}")
        for net_id, net_root in net_roots.items():
            if net_root == root:
                groups[SIGNAL_GROUPS[nets[net_id].signal]].append(f"net {net_id}")
        if len(groups) > 1:
            detail = "；".join(
                f"{group}：{'、'.join(sorted(names))}" for group, names in groups.items()
            )
            add(
                "red",
                "fail",
                f"訊號型別不相容：{detail}",
                sorted({name.split(".")[0] for names in groups.values() for name in names}),
            )
    # 5. I/O 與點位池的配置問題
    for issue in resolved.issues:
        if issue["code"] in {"DUPLICATE_ADDRESS", "POOL_EXHAUSTED"}:
            title = "重複 I/O 位址" if issue["code"] == "DUPLICATE_ADDRESS" else "點位不足"
            add("red", "fail", f"{title}：{issue['message']}", [], code=issue["code"])
    # 6. 製程使用的設備必須連到電控器件
    covered = defaultdict(list)
    for device in resolved.devices.values():
        if device.module_ref:
            covered[device.module_ref].append(device)
    for module, reason, kind in required_modules or []:
        devices = [
            device for device in covered.get(module, []) if kind is None or device.kind == kind
        ]
        if not devices:
            need = f"需要 kind={kind} 的器件" if kind else "需要 module_ref 指向它的器件"
            add(
                "red",
                "fail",
                f"模組 {module} 未連到電控器件（{reason}；{need}）",
                [module],
                suggestion="在 electrical.yaml 為此模組建立器件或設備樣板",
            )
    # 7. 供電容量：額定值齊全才評估
    for device in resolved.devices.values():
        sources = [
            terminal
            for terminal in device.terminals
            if terminal.direction == "source"
            and terminal.signal == "dc_power"
            and terminal.voltage not in (None, "0V")
        ]
        if device.kind != "psu" or not sources:
            continue
        loads = {
            other.id: other
            for terminal in sources
            for _node_name, other, other_terminal in components[
                graph.find(f"{device.id}:{terminal.id}")
            ]
            if other.id != device.id and other_terminal.direction == "sink"
        }
        missing = sorted(name for name, load in loads.items() if load.ratings.current_a is None)
        rating = device.ratings.output_current_a
        if rating is None or missing:
            parts = []
            if rating is None:
                parts.append(f"{device.id} 未填輸出額定電流")
            if missing:
                parts.append(f"負載未填電流：{'、'.join(missing)}")
            add(
                "yellow",
                "not_evaluated",
                f"供電容量未評估：{'；'.join(parts)}",
                [device.id, *missing],
                suggestion="依設備手冊補上額定值後重建；未評估不代表容量足夠",
            )
            continue
        total = sum(load.ratings.current_a or 0.0 for load in loads.values())
        add(
            "red" if total > rating else "green",
            "fail" if total > rating else "pass",
            f"{device.id} 負載 {total:.2f} A／額定 {rating:.2f} A",
            [device.id, *sorted(loads)],
            value=total,
            limit=rating,
            unit="A",
        )
    # 8. 安全回路：只呈現規劃
    for circuit in resolved.source.safety:
        add(
            "yellow",
            "not_evaluated",
            f"安全回路 {circuit.name}：{circuit.note}",
            [circuit.controller, *circuit.devices],
            suggestion="依風險評估完成安全架構設計與驗證",
        )
    # 9. 與採購 BOM 的數量對照：器件數量加總必須等於採購數量；組套內含（None）只核對存在
    if costing is not None:
        purchased = {line["item"]: line for line in costing.get("purchase_lines", [])}
        counts: dict[str, list] = defaultdict(list)
        for device in resolved.devices.values():
            if device.catalog_ref:
                counts[device.catalog_ref].append(device)
        for item, devices in sorted(counts.items()):
            names = [device.id for device in devices]
            line = purchased.get(item)
            if line is None:
                add(
                    "yellow",
                    "fail",
                    f"器件 {'、'.join(names)} 的採購項 {item} 不在採購明細",
                    names,
                    suggestion="在 costing.yaml 補上對應的設備對應或 BOM 列",
                )
                continue
            counted = [device for device in devices if device.catalog_quantity is not None]
            if not counted:
                continue
            quantity = sum(device.catalog_quantity for device in counted)
            if abs(float(line["quantity"]) - quantity) > 1e-9:
                add(
                    "yellow",
                    "fail",
                    f"採購項 {item}（{line['name']}）採購數量 {line['quantity']}，"
                    f"電控器件合計 {quantity:g}：{'、'.join(device.id for device in counted)}",
                    names,
                    suggestion="電控器件與成本設備對應應同步增減",
                )
    # 10. 盤面：寬度與上下間距由排版幾何算出；缺尺寸或未排入的器件未評估
    layout = layout_panel(resolved)
    if layout is not None:
        for detail, objects in layout.problems:
            add("red", "fail", detail, objects, suggestion="調整軌道、器件順序或盤面尺寸")
        if layout.unsized or layout.unplaced:
            parts = []
            if layout.unsized:
                parts.append(f"缺外形尺寸：{'、'.join(layout.unsized)}")
            if layout.unplaced:
                parts.append(f"未指定軌道：{'、'.join(layout.unplaced)}")
            add(
                "yellow",
                "not_evaluated",
                f"盤面排版未完整評估（{'；'.join(parts)}）",
                [*layout.unsized, *layout.unplaced],
            )
        elif not layout.problems:
            add("green", "pass", f"盤內 {len(layout.placements)} 個器件排入盤面，無溢出或重疊", [])
    if not any(item["severity"] == "red" for item in items):
        add("green", "pass", "電控連通圖無缺接線、斷路、電壓域或訊號型別錯誤", [])
    return items
