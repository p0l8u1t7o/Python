"""Traceable vendor asset acquisition and engineering stubs."""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
from datetime import date
from pathlib import Path

from cellforge.kinematics.stub import stub_dimensions, write_stub_urdf
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
    limits = write_stub_urdf(
        urdf,
        name=vendor_id,
        reach_mm=reach_mm,
        payload_kg=payload_kg,
    )
    dims = stub_dimensions(reach_mm, payload_kg)
    entry = {
        "id": vendor_id,
        "kind": "robot",
        "files": {"urdf": urdf.relative_to(project).as_posix()},
        "source_url": source_url,
        "downloaded": date.today().isoformat(),
        "sha256": {"urdf": limits.pop("sha256")},
        "units_in_file": "mm",
        "up_axis": "z",
        "approximated": True,
        "frames": {
            "base": {"xyz": [0, 0, 0], "rpy_deg": [0, 0, 0]},
            "flange": {
                "link": "link6",
                "xyz": [dims.l6_mm, 0, 0],
                "rpy_deg": [0, 90, 0],
            },
        },
        "limits": limits,
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


def add_vendor_urdf(
    project: Path,
    vendor_id: str,
    urdf: str,
    extra_sources: list[str],
    *,
    kind: str = "robot",
    flange: dict | None = None,
    limits: dict | None = None,
    part_no: str | None = None,
    source_url: str | None = None,
) -> dict:
    """Register a vendor URDF with its meshes; every file gets its own SHA-256.

    URDF 依規範為公尺與弧度；網格引用必須能在同一個廠商資料夾內解析，否則拒絕登記。
    """

    import xml.etree.ElementTree as ET

    from cellforge.vendor_model import _resolve_mesh, verify_vendor_files

    vendor_dir = project / "vendor" / vendor_id
    vendor_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for key, source in [("urdf", urdf), *((None, item) for item in extra_sources)]:
        target = _fetch(source, vendor_dir)
        name = key or f"file:{target.name}"
        files[name] = target.relative_to(project).as_posix()
        hashes[name] = _sha256(target)
    urdf_path = project / files["urdf"]
    missing = []
    for mesh in ET.parse(urdf_path).getroot().iter("mesh"):
        try:
            _resolve_mesh(str(mesh.get("filename", "")), urdf_path, project)
        except ValueError:
            missing.append(str(mesh.get("filename")))
    if missing:
        raise ValueError("URDF 引用的網格未一併提供：" + "、".join(sorted(set(missing))))
    frames: dict = {"base": {"xyz": [0, 0, 0], "rpy_deg": [0, 0, 0]}}
    if flange:
        frames["flange"] = flange
    entry = {
        "id": vendor_id,
        "kind": kind,
        "files": files,
        "source_url": source_url or urdf,
        "downloaded": date.today().isoformat(),
        "sha256": hashes,
        "units_in_file": "m",
        "up_axis": "z",
        "approximated": False,
        "frames": frames,
        "limits": limits or {},
    }
    if part_no:
        entry["part_no"] = part_no
    verify_vendor_files(project, entry)
    return _upsert(project, entry)


def _fetch(source: str, directory: Path) -> Path:
    name = Path(source.split("?", 1)[0]).name
    if not name:
        raise ValueError(f"無法由來源推得檔名：{source}")
    target = directory / name
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=60) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
    else:
        shutil.copy2(Path(source), target)
    return target


def _upsert(project: Path, entry: dict) -> dict:
    manifest_path = project / "vendor" / "manifest.yaml"
    manifest = load_yaml(manifest_path) or {"vendors": []}
    manifest["vendors"] = [
        item for item in manifest.get("vendors", []) if item.get("id") != entry["id"]
    ]
    manifest["vendors"].append(entry)
    dump_yaml(manifest_path, manifest)
    return entry
