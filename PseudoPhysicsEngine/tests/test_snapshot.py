from pathlib import Path

from cellforge.snapshot import _copy_to_latest_version


def test_copy_to_latest_version_skips_copying_a_file_onto_itself(tmp_path: Path):
    version = tmp_path / ".cellforge" / "v2"
    version.mkdir(parents=True)
    snapshot = version / "snapshot_t0_top.png"
    snapshot.write_bytes(b"png-fixture")

    _copy_to_latest_version(tmp_path, snapshot)

    assert snapshot.read_bytes() == b"png-fixture"
