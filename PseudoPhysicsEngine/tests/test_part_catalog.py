from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import cadquery as cq
from typer.testing import CliRunner

from cellforge.cli import app
from cellforge.part_catalog import derive_module_fields, load_library_catalog
from cellforge.part_check import BASIS_TEMPLATE_TEXT, _definition, _load_file, check_module
from cellforge.schema import Frame, ModuleDef, ModuleMeta
from cellforge.yamlio import dump_yaml, load_yaml
from library import box

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_every_library_module_has_a_resolvable_synchronized_manifest_entry():
    entries = load_library_catalog(ROOT)
    manifest_files = {entry["file"] for entry in entries}
    library_files = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "library").glob("*.py")
        if path.name != "__init__.py"
    }
    assert manifest_files == library_files
    for entry in entries:
        path = ROOT / entry["file"]
        assert path.is_file()
        derived = derive_module_fields(path, entry["file"])
        assert entry["frames"] == derived["frames"]
        assert entry["axes"] == derived["axes"]


def test_part_list_selects_library_and_project_entries(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "local_bracket.py").write_text(
        '''"""本案相機支架。"""
from cellforge.schema import Frame, ModuleDef, ModuleMeta
MODULE = ModuleDef(
    id="local_bracket",
    params_schema={"type": "object", "properties": {"height_mm": {"type": "number"}}},
    frames={"mount": Frame(), "camera": Frame()},
    meta=ModuleMeta(basis="依本案相機安裝高度與現場支撐需求作工程推估"),
)
''',
        encoding="utf-8",
    )
    library_result = runner.invoke(app, ["part", "list", "--library", "--json"])
    assert library_result.exit_code == 0, library_result.output
    library_ids = {entry["id"] for entry in json.loads(library_result.stdout)["modules"]}
    assert library_ids == {entry["id"] for entry in load_library_catalog(ROOT)}

    project_result = runner.invoke(
        app,
        ["part", "list", "--project", "--project-dir", str(tmp_path), "--json"],
    )
    assert project_result.exit_code == 0, project_result.output
    project_entries = json.loads(project_result.stdout)["modules"]
    assert {entry["id"] for entry in project_entries} == {"local_bracket"}
    assert project_entries[0]["params"] == ["height_mm"]
    assert project_entries[0]["frames"] == ["mount", "camera"]

    text_result = runner.invoke(app, ["part", "list", "--library"])
    assert text_result.exit_code == 0, text_result.output
    assert "類別：" in text_result.stdout
    assert "參數：" in text_result.stdout


def test_part_new_skeleton_is_rejected_until_basis_is_replaced(tmp_path):
    result = runner.invoke(
        app,
        [
            "part",
            "new",
            "local_mechanism",
            "--category",
            "handling",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    source = tmp_path / "parts" / "local_mechanism.py"
    module = _load_file(source)
    definition = _definition(module, {})
    checked = check_module(module, source=source)
    assert definition.meta.basis == BASIS_TEMPLATE_TEXT
    assert {(item.index, item.severity) for item in checked.items if item.index == "6.1"} == {
        ("6.1", "fail")
    }


def test_part_new_from_library_copies_an_editable_module(tmp_path):
    source_module = _load_file(ROOT / "library" / "extrusion_frame.py")
    source_definition = _definition(source_module, {})
    result = runner.invoke(
        app,
        [
            "part",
            "new",
            "local_frame",
            "--category",
            "frame",
            "--from",
            source_definition.id,
            "--project",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    copied = _load_file(tmp_path / "parts" / "local_frame.py")
    copied_definition = _definition(copied, {})
    assert copied_definition.id == "local_frame"
    assert copied_definition.params_schema == source_definition.params_schema
    assert copied_definition.frames == source_definition.frames
    assert copied_definition.axes == source_definition.axes
    assert copied.CATEGORY == "frame"
    assert callable(copied.build)
    assert callable(copied.module_definition)


def test_validate_warns_for_box_placeholder_without_failing(tmp_path):
    project = tmp_path / "placeholder-project"
    initialized = runner.invoke(app, ["init", str(project), "--json"])
    assert initialized.exit_code == 0, initialized.output
    cell_path = project / "cell.yaml"
    cell_data = load_yaml(cell_path)
    duplicate = deepcopy(cell_data["machines"][0]["modules"][0])
    duplicate["id"] = "second_placeholder"
    cell_data["machines"][0]["modules"].append(duplicate)
    dump_yaml(cell_path, cell_data)
    validated = runner.invoke(app, ["validate", "--project", str(project), "--json"])
    assert validated.exit_code == 0, validated.output
    payload = json.loads(validated.stdout)
    assert payload["status"] == "ok"
    placeholder_instances = [
        module
        for machine in cell_data["machines"]
        for module in machine["modules"]
        if Path(module["part"]).stem == "box"
    ]
    assert len(payload["warnings"]) == len(placeholder_instances)
    assert all("仍為佔位幾何" in warning for warning in payload["warnings"])


def _single_box_module(module_id: str, *, placeholder: bool, valid_structure: bool) -> ModuleType:
    module = ModuleType(module_id)
    module.MODULE = ModuleDef(
        id=module_id,
        params_schema={"type": "object"},
        frames={"mount": Frame()} if valid_structure else {},
        meta=ModuleMeta(
            basis="依佔位判定因果測試所需的通用外形包絡建立" if valid_structure else "",
            placeholder=placeholder,
        ),
    )

    def build(_params: dict) -> cq.Assembly:
        assembly = cq.Assembly(name=module_id)
        assembly.add(
            cq.Workplane("XY").box(100, 100, 100),
            name="envelope",
            color=cq.Color(0.5, 0.5, 0.5),
        )
        return assembly

    module.build = build
    return module


def test_placeholder_relaxation_only_skips_mounting_interface_proxy():
    actual_box = check_module(box)
    ordinary = check_module(
        _single_box_module("ordinary_envelope", placeholder=False, valid_structure=True)
    )
    invalid_placeholder = check_module(
        _single_box_module("invalid_placeholder", placeholder=True, valid_structure=False)
    )
    assert not [item for item in actual_box.items if item.index == "6.2"]
    assert {(item.index, item.severity) for item in ordinary.items if item.index == "6.2"} == {
        ("6.2", "warn")
    }
    invalid_failures = {item.index for item in invalid_placeholder.items if item.severity == "fail"}
    assert {"6.1", "6.4"} <= invalid_failures
