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
from cellforge.yamlio import load_yaml


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
    interference = [
        item
        for item in checks_before["items"]
        if item["type"] == "interference"
        and item["severity"] == "red"
        and any(name.startswith("robot_1") for name in item["objects"])
        and any(name.startswith("workpiece") for name in item["objects"])
    ]
    assert interference
    worst = min(interference, key=lambda item: item["min_dist_mm"])
    process_before = load_yaml(project / "process.yaml")
    approach_before = next(step for step in process_before["steps"] if step["id"] == "S3.approach")
    offset_before = float(approach_before["target"]["offset"]["xyz"][2])

    change_dir = project / "changes"
    change_dir.mkdir(exist_ok=True)
    (change_dir / "CR-001.md").write_text("# CR-001\n- 狀態：open\n", encoding="utf-8")
    retract_mm = 20.0
    applied = apply_local_change(
        project,
        "CR-001",
        f"法蘭退 {retract_mm:g} mm",
        "robot_1.tool",
        float(worst["t"]),
    )
    checks_after = json.loads((project / ".cellforge" / "v2" / "checks.json").read_text("utf-8"))
    targeted_red_after = [
        item
        for item in checks_after["items"]
        if item["type"] == "interference"
        and item["severity"] == "red"
        and any(name.startswith("robot_1") for name in item["objects"])
        and any(name.startswith("workpiece") for name in item["objects"])
    ]
    process_after = load_yaml(project / "process.yaml")
    approach_after = next(step for step in process_after["steps"] if step["id"] == "S3.approach")
    assert before["version"] == 1
    assert applied["build"]["version"] == 2
    assert not targeted_red_after
    assert float(approach_after["target"]["offset"]["xyz"][2]) == (offset_before + retract_mm)
    assert diff_versions(project, "v1", "v2")["count"] > 0
    cr = (change_dir / "CR-001.md").read_text("utf-8")
    assert all(field in cr for field in ("代理解讀", "影響", "差異", "結果", "狀態：applied"))


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
    html = next(
        (Path(exported["directory"]) / name) for name in exported["files"] if name.endswith(".html")
    ).read_text("utf-8")
    assert "window.CELLFORGE_DATA=" in html
    assert "cellforgeOfflineReady" in html
    assert "getContext('2d')" not in html
