from datetime import date
from pathlib import Path

from PIL import Image

from cellforge import derived
from cellforge.build.pipeline import build_project
from cellforge.exports import _review_snapshots
from cellforge.project import create_project
from cellforge.versioning import VersionContext


def _fake_snapshot(project: Path, name: str) -> Path:
    path = project / "build" / name
    Image.new("RGB", (64, 36), "#224466").save(path)
    return path


def test_build_snapshot_is_registered_to_mirrored_version_without_touching_snapshot(
    tmp_path: Path,
):
    project = create_project(
        tmp_path / "snapshots",
        {"name": "截圖登記案", "created": date.today().isoformat()},
        seed_example="getac_qc",
    )
    build_project(project, "L0")
    v1 = project / ".cellforge" / "v1"
    before = sorted(path.relative_to(v1).as_posix() for path in v1.rglob("*"))
    entry = derived.record_build_snapshot(
        project, _fake_snapshot(project, "snapshot_t0_iso.png"), {"camera": "iso"}
    )
    assert entry is not None and entry["version"] == "v1"
    assert sorted(path.relative_to(v1).as_posix() for path in v1.rglob("*")) == before
    v1_images = _review_snapshots(VersionContext.open(project, "v1"), None)
    assert [path.name for path in v1_images] == ["snapshot_t0_iso.png"]

    build_project(project, "L0")
    later = derived.record_build_snapshot(
        project, _fake_snapshot(project, "snapshot_station_s3.png"), {"camera": "S3"}
    )
    assert later is not None and later["version"] == "v2"
    # v2 的截圖不會出現在 v1 的交付內容。
    assert _review_snapshots(VersionContext.open(project, "v1"), None) == v1_images

    # build/ 被改得與發布版本不符時，不登記到任何版本。
    (project / "build" / "scene.glb").write_bytes(b"not the published scene")
    assert (
        derived.record_build_snapshot(
            project, _fake_snapshot(project, "snapshot_t0_top.png"), {"camera": "top"}
        )
        is None
    )


def test_delivery_prefers_snapshots_nearest_worst_check_times(tmp_path: Path):
    build = tmp_path / "build"
    version = tmp_path / ".cellforge" / "v1"
    build.mkdir()
    version.mkdir(parents=True)
    early = version / "snapshot_t9_iso.png"
    late = version / "snapshot_t28_S4.png"
    unrelated = version / "snapshot_t50_iso.png"
    # 工作區 build/ 可能屬於其他版本；即使時間更接近 red 檢查也不得被選用。
    stray = build / "snapshot_t10_iso.png"
    for path in (early, late, unrelated, stray):
        path.write_bytes(b"png")
    checks = {
        "items": [
            {"severity": "red", "t": 10.0, "min_dist_mm": -2.0},
            {"severity": "yellow", "t": 30.0, "value": 9.0, "limit": 10.0},
        ]
    }
    assert _review_snapshots(VersionContext.open(tmp_path, "v1"), checks) == [early, late]
