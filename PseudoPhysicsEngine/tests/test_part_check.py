from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import ModuleType

import cadquery as cq
from PIL import Image
from pygltflib import GLTF2
from typer.testing import CliRunner

from cellforge.build.glb import _shape_mesh
from cellforge.cli import app
from cellforge.part_check import TRIANGLE_FAIL_COUNT, TRIANGLE_WARN_COUNT, check_module
from cellforge.schema import Frame, ModuleAxis, ModuleDef, ModuleMeta

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "getac_qc" / "handwritten"


def _module(
    *,
    basis: str = "依設備工程圖與標準安裝尺寸建模",
    part_name: str = "mounting_plate",
    frames: dict[str, Frame] | None = None,
    axes: list[ModuleAxis] | None = None,
    fail_at_upper_bound: bool = False,
) -> ModuleType:
    module = ModuleType("test_part")
    parameter_schema = {
        "type": "number",
        "minimum": 20,
        "maximum": 200,
        "default": 100,
    }
    schema = {"type": "object", "properties": {"width_mm": parameter_schema}}
    module.MODULE = ModuleDef(
        id="test_part",
        params_schema=schema,
        frames=frames
        or {
            "mount": Frame(xyz=(0, 0, 0)),
            "top": Frame(xyz=(0, 0, 100)),
        },
        axes=axes or [],
        meta=ModuleMeta(basis=basis),
    )

    def build(params: dict) -> cq.Assembly:
        width = params.get("width_mm", parameter_schema["default"])
        if fail_at_upper_bound and width == parameter_schema["maximum"]:
            raise ValueError("上限不可建置")
        assembly = cq.Assembly(name="test_part")
        assembly.add(
            cq.Workplane("XY").box(width, 100, 100).translate((0, 0, 50)),
            name=part_name,
            color=cq.Color(0.5, 0.5, 0.5),
        )
        for name, x in (("foot_left", -40), ("foot_right", 40)):
            assembly.add(
                cq.Workplane("XY").box(10, 10, 10).translate((x, 0, 5)),
                name=name,
                color=cq.Color(0.2, 0.2, 0.2),
            )
        return assembly

    module.build = build
    return module


def _findings(module: ModuleType, severity: str) -> set[str]:
    return {item.index for item in check_module(module).items if item.severity == severity}


def _geometry_module(
    module_id: str,
    shapes: list[tuple[str, cq.Shape]],
    mount_xyz: tuple[float, float, float] = (0, 0, 0),
    with_interface: bool = True,
) -> ModuleType:
    module = ModuleType(module_id)
    module.MODULE = ModuleDef(
        id=module_id,
        params_schema={"type": "object"},
        frames={"mount": Frame(xyz=mount_xyz)},
        collision="box",
        meta=ModuleMeta(basis="依幾何品質檢查的因果測試需求建模"),
    )

    def build(_params: dict) -> cq.Assembly:
        assembly = cq.Assembly(name=module_id)
        for name, shape in shapes:
            assembly.add(shape, name=name, color=cq.Color(0.5, 0.5, 0.5))
        if with_interface:
            for name, x in (("interface_pad_left", -1), ("interface_pad_right", 1)):
                assembly.add(
                    cq.Workplane("XY").box(1, 1, 1).translate((x, 0, 0)),
                    name=name,
                    color=cq.Color(0.2, 0.2, 0.2),
                )
        return assembly

    module.build = build
    return module


def _color_module(module_id: str, colored: list[bool]) -> ModuleType:
    module = ModuleType(module_id)
    module.MODULE = ModuleDef(
        id=module_id,
        params_schema={"type": "object"},
        frames={"mount": Frame()},
        meta=ModuleMeta(basis="依安裝介面與工程配色因果測試需求建模"),
    )

    def build(_params: dict) -> cq.Assembly:
        assembly = cq.Assembly(name=module_id)
        shapes = [
            ("mounting_plate", cq.Workplane("XY").box(100, 100, 10).translate((0, 0, 15))),
            *[
                (
                    f"support_foot_{index}",
                    cq.Workplane("XY").box(10, 10, 10).translate((x, y, 5)),
                )
                for index, (x, y) in enumerate(((-40, -40), (-40, 40), (40, -40), (40, 40)))
            ],
        ]
        for is_colored, (name, shape) in zip(colored, shapes, strict=True):
            assembly.add(
                shape,
                name=name,
                color=cq.Color(0.5, 0.5, 0.5) if is_colored else None,
            )
        return assembly

    module.build = build
    return module


def test_structural_checks_are_causal():
    compliant = _module()
    assert not _findings(compliant, "fail")
    assert not _findings(compliant, "warn")

    assert _findings(_module(basis=""), "fail") == {"6.1"}
    assert _findings(_module(part_name="solid1"), "fail") == {"6.3"}
    assert _findings(_module(frames={"top": Frame(xyz=(0, 0, 100))}), "fail") == {"6.4"}
    invalid_axis = ModuleAxis(
        id="slide",
        type="prismatic",
        child="moving",
        range_mm=(0, 0),
        max_speed_mm_s=100,
    )
    assert _findings(_module(axes=[invalid_axis]), "fail") == {"6.5"}
    assert _findings(_module(fail_at_upper_bound=True), "fail") == {"6.8"}


def test_lowest_z_is_geometry_derived_information():
    result = check_module(_module())
    items = [item for item in result.items if item.index == "6.10"]
    assert len(items) == 1
    assert items[0].severity == "info"
    assert items[0].values["lowest_z_mm"] is not None


def test_mounting_interface_warning_is_caused_by_single_box_geometry():
    single_box = _geometry_module(
        "single_box",
        [("enclosure", cq.Workplane("XY").box(100, 100, 100).val())],
        with_interface=False,
    )
    warning = check_module(single_box)
    compliant = check_module(_module())
    assert {(item.index, item.severity) for item in warning.items if item.severity != "info"} == {
        ("6.2", "warn")
    }
    assert not [item for item in compliant.items if item.index == "6.2"]


def test_color_warning_is_caused_by_missing_explicit_colors():
    mostly_uncolored = check_module(
        _color_module("mostly_uncolored", [True, False, False, False, False])
    )
    fully_colored = check_module(_color_module("fully_colored", [True] * 5))
    assert {
        (item.index, item.severity) for item in mostly_uncolored.items if item.severity != "info"
    } == {("6.7", "warn")}
    assert not [item for item in fully_colored.items if item.index == "6.7"]


def test_collision_inflation_severity_is_caused_by_over_enclosure():
    compliant = _module()
    assert not [item for item in check_module(compliant).items if item.index == "6.6"]

    radius = 10.0
    direction = cq.Vector(1, 1, 0)
    warning_rod = cq.Solid.makeCylinder(radius, radius * 5, cq.Vector(), direction)
    failure_rod = cq.Solid.makeCylinder(radius, radius * 15, cq.Vector(), direction)
    warning = check_module(_geometry_module("warning_rod", [("diagonal_rod", warning_rod)]))
    failure = check_module(_geometry_module("failure_rod", [("diagonal_rod", failure_rod)]))
    assert {(item.index, item.severity) for item in warning.items if item.severity != "info"} == {
        ("6.6", "warn")
    }
    assert {(item.index, item.severity) for item in failure.items if item.severity != "info"} == {
        ("6.6", "fail")
    }


def test_triangle_budget_severity_is_caused_by_dense_geometry():
    compliant = _module()
    assert not [item for item in check_module(compliant).items if item.index == "6.9"]

    sample = cq.Solid.makeTorus(50, 10)
    triangles_per_ring = len(_shape_mesh(sample).faces)

    def rings_for(limit: int) -> list[tuple[str, cq.Shape]]:
        count = limit // triangles_per_ring + 1
        return [
            (f"dense_ring_{index}", sample.moved(cq.Location((index * 125, 0, 0))))
            for index in range(count)
        ]

    ring_surface = (60.0, 0.0, 0.0)
    warning = check_module(
        _geometry_module("warning_mesh", rings_for(TRIANGLE_WARN_COUNT), ring_surface)
    )
    failure = check_module(
        _geometry_module("failure_mesh", rings_for(TRIANGLE_FAIL_COUNT), ring_surface)
    )
    assert {(item.index, item.severity) for item in warning.items if item.severity != "info"} == {
        ("6.9", "warn")
    }
    assert {(item.index, item.severity) for item in failure.items if item.severity != "info"} == {
        ("6.9", "fail")
    }
    dense_finding = next(item for item in failure.items if item.index == "6.9")
    assert len(dense_finding.values["top_sub_parts"]) == 3


def test_part_check_json_for_placeholder_module():
    result = runner.invoke(app, ["part", "check", "box", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["module_id"] == "box"
    assert payload["passed"] is True
    assert {"index", "severity", "code", "message", "values"} <= set(payload["items"][0])


def test_part_render_writes_png(tmp_path):
    output = tmp_path / "box.png"
    result = runner.invoke(
        app,
        ["part", "render", "box", "--project", str(ROOT), "--out", str(output)],
    )
    assert result.exit_code == 0, result.output
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.width > 0 and image.height > 0


def test_part_preview_preserves_joint_hierarchy(tmp_path):
    output = tmp_path / "lift-rack.glb"
    result = runner.invoke(
        app,
        ["part", "preview", "lift_rack", "--project", str(ROOT), "--out", str(output)],
    )
    assert result.exit_code == 0, result.output
    gltf = GLTF2().load_binary(str(output))
    nodes = gltf.nodes or []
    module = next(node for node in nodes if node.name == "lift_rack")
    joint = next(node for node in nodes if node.name == "lift_rack.lift")
    collision = next(node for node in nodes if node.name == "collision")
    assert module.extras["joints"] == ["lift"]
    assert joint.extras["joint"]["type"] == "prismatic"
    assert collision.extras["hidden"] is True


def test_validate_rejects_a_failing_project_part(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project)
    parts = project / "parts"
    parts.mkdir(exist_ok=True)
    (parts / "unqualified.py").write_text(
        """import cadquery as cq
from cellforge.schema import Frame, ModuleDef
MODULE = ModuleDef(id='unqualified', params_schema={'type': 'object'}, frames={'mount': Frame()})
def build(params):
    result = cq.Assembly(name='unqualified')
    result.add(cq.Workplane('XY').box(10, 10, 10), name='body')
    return result
""",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--project", str(project), "--json"])
    assert result.exit_code == 2
    assert "案內 parts 品質檢查失敗" in result.stdout
