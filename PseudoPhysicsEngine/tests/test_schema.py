from pathlib import Path

from cellforge.schema import SCHEMAS
from cellforge.schema.export import export_json_schemas
from cellforge.validation import validate_project

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "getac_qc" / "handwritten"


def test_handwritten_project_validates():
    project, workpiece, cell, process = validate_project(EXAMPLE)
    assert project.name.startswith("Getac")
    assert workpiece.units == "mm"
    assert len(cell.machines[0].modules) == 7
    assert len(process.stations) == 5


def test_json_schema_export(tmp_path):
    outputs = export_json_schemas(tmp_path)
    assert {path.name for path in outputs} == {f"{name}.schema.json" for name in SCHEMAS}
    assert "version-manifest" in SCHEMAS
    assert all(path.is_file() for path in outputs)
    # docs/schema 必須與目前的 pydantic 模型同步。
    for path in outputs:
        committed = ROOT / "docs" / "schema" / path.name
        assert committed.read_text("utf-8") == path.read_text("utf-8"), path.name
