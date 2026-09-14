import json
from datetime import date
from pathlib import Path

from PIL import Image

from cellforge.agents.astra import build_hash, refresh_theme_local
from cellforge.build.pipeline import build_project
from cellforge.changes import apply_local_change
from cellforge.diffing import diff_versions
from cellforge.exports import export_project
from cellforge.project import create_project


def make_project(root: Path) -> Path:
    return create_project(
        root / "acceptance",
        {
            "name": "Step 3-6 acceptance",
            "customer": "Getac",
            "product": "V110",
            "description": "Automated rugged notebook QC cell",
            "constraints": {
                "robot_brand": "DENSO",
                "takt_target_s": 45,
                "footprint_mm": [8000, 4000],
                "stations_max": 6,
                "safety_notes": "force limited",
                "free_text": "",
            },
            "created": date.today().isoformat(),
        },
        seed_example="getac_qc",
    )


def test_l1_interference_change_and_diff(tmp_path: Path):
    project = make_project(tmp_path)
    before = build_project(project, "L1")
    checks_before = json.loads((project / ".cellforge" / "v1" / "checks.json").read_text("utf-8"))
    interference = next(item for item in checks_before["items"] if item["type"] == "interference")
    assert interference["severity"] == "red"
    assert interference["value"] == -3.2

    change_dir = project / "changes"
    change_dir.mkdir(exist_ok=True)
    (change_dir / "CR-001.md").write_text("# CR-001\n- status: open\n", encoding="utf-8")
    applied = apply_local_change(project, "CR-001", "法蘭退 20 mm")
    checks_after = json.loads((project / ".cellforge" / "v2" / "checks.json").read_text("utf-8"))
    resolved = next(item for item in checks_after["items"] if item["type"] == "interference")
    assert before["version"] == 1
    assert applied["build"]["version"] == 2
    assert resolved["severity"] == "green"
    assert resolved["value"] == 16.8
    assert diff_versions(project, "v1", "v2")["count"] > 0


def test_astra_hash_protection_and_non_office_exports(tmp_path: Path):
    project = make_project(tmp_path)
    build_project(project, "L1")
    before = build_hash(project)
    result = refresh_theme_local(project, "請 Astra 美化")
    assert result["build_unchanged"] is True
    assert build_hash(project) == before
    assert (project / result["video"]).is_file()
    with Image.open(project / "presentation" / "placeholder.png") as placeholder:
        assert placeholder.size == (1280, 720)

    exported = export_project(project, ["step", "dxf", "bom", "report", "html", "video"])
    assert len(exported["files"]) == 6
    for name in exported["files"]:
        assert (Path(exported["directory"]) / name).stat().st_size > 0
