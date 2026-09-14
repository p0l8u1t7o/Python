"""Traceable vendor asset acquisition and engineering stubs."""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
from datetime import date
from pathlib import Path

from cellforge.yamlio import dump_yaml, load_yaml


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stub_robot(
    project: Path,
    vendor_id: str,
    *,
    reach_mm: float = 905,
    payload_kg: float = 7,
    source_url: str = "engineering://approximation",
) -> dict:
    vendor_dir = project / "vendor" / vendor_id
    vendor_dir.mkdir(parents=True, exist_ok=True)
    urdf = vendor_dir / f"{vendor_id}.urdf"
    joints = "\n".join(
        (
            f'  <joint name="j{i}" type="revolute">'
            f'<parent link="link{i - 1}"/><child link="link{i}"/>'
            '<axis xyz="0 0 1"/>'
            '<limit lower="-3.141593" upper="3.141593" '
            'effort="100" velocity="2.0"/></joint>\n'
            f'  <link name="link{i}"/>'
        )
        for i in range(1, 7)
    )
    urdf.write_text(
        f'<?xml version="1.0"?>\n<robot name="{vendor_id}">\n'
        f'  <link name="link0"/>\n{joints}\n</robot>\n',
        encoding="utf-8",
    )
    entry = {
        "id": vendor_id,
        "kind": "robot",
        "files": {"urdf": urdf.relative_to(project).as_posix()},
        "source_url": source_url,
        "downloaded": date.today().isoformat(),
        "sha256": {"urdf": _sha256(urdf)},
        "units_in_file": "mm",
        "up_axis": "z",
        "approximated": True,
        "frames": {"base": {"xyz": [0, 0, 0]}, "flange": {"xyz": [reach_mm, 0, 360]}},
        "limits": {
            "reach_mm": reach_mm,
            "payload_kg": payload_kg,
            "joints_deg": [[-180, 180] for _ in range(6)],
        },
    }
    return _upsert(project, entry)


def add_vendor_file(
    project: Path,
    vendor_id: str,
    kind: str,
    source: str,
    *,
    units: str = "mm",
    up_axis: str = "z",
) -> dict:
    vendor_dir = project / "vendor" / vendor_id
    vendor_dir.mkdir(parents=True, exist_ok=True)
    name = Path(source).name or f"{vendor_id}.bin"
    target = vendor_dir / name
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=60) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
    else:
        shutil.copy2(Path(source), target)
    entry = {
        "id": vendor_id,
        "kind": kind,
        "files": {
            target.suffix.lstrip(".").lower() or "file": target.relative_to(project).as_posix()
        },
        "source_url": source,
        "downloaded": date.today().isoformat(),
        "sha256": _sha256(target),
        "units_in_file": units,
        "up_axis": up_axis,
        "approximated": False,
        "frames": {"base": {"xyz": [0, 0, 0]}},
        "limits": {},
    }
    return _upsert(project, entry)


def _upsert(project: Path, entry: dict) -> dict:
    manifest_path = project / "vendor" / "manifest.yaml"
    manifest = load_yaml(manifest_path) or {"vendors": []}
    manifest["vendors"] = [
        item for item in manifest.get("vendors", []) if item.get("id") != entry["id"]
    ]
    manifest["vendors"].append(entry)
    dump_yaml(manifest_path, manifest)
    return entry
