from pathlib import Path

from cellforge.exports import _review_snapshots
from cellforge.snapshot import _copy_to_latest_version


def test_copy_to_latest_version_skips_copying_a_file_onto_itself(tmp_path: Path):
    version = tmp_path / ".cellforge" / "v2"
    version.mkdir(parents=True)
    snapshot = version / "snapshot_t0_top.png"
    snapshot.write_bytes(b"png-fixture")

    _copy_to_latest_version(tmp_path, snapshot)

    assert snapshot.read_bytes() == b"png-fixture"


def test_delivery_prefers_snapshots_nearest_worst_check_times(tmp_path: Path):
    build = tmp_path / "build"
    version = tmp_path / ".cellforge" / "v1"
    build.mkdir()
    version.mkdir(parents=True)
    early = build / "snapshot_t9_iso.png"
    late = build / "snapshot_t28_S4.png"
    unrelated = build / "snapshot_t50_iso.png"
    for path in (early, late, unrelated):
        path.write_bytes(b"png")
    checks = {
        "items": [
            {"severity": "red", "t": 10.0, "min_dist_mm": -2.0},
            {"severity": "yellow", "t": 30.0, "value": 9.0, "limit": 10.0},
        ]
    }
    assert _review_snapshots(tmp_path, version, checks) == [early, late]
