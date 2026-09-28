"""版本衍生 artifact（截圖、影片）登記：屬於哪個版本、由哪些來源與設定產生、檔案是否仍可取得。

衍生 artifact 在版本發布後才產生，因此不寫進不可變的 ``.cellforge/vN``：
登記檔在 ``.cellforge/derived/vN.json``，截圖存 ``.cellforge/derived/vN/snapshots/``，
影片存在不進版控的 ``TEMP/videos/vN/``。讀取時逐一核對檔案存在與雜湊，
暫存被清掉的影片只會顯示「可重新產生」，絕不拿其他版本的檔案頂替。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from cellforge.filelock import file_lock
from cellforge.version_store import MIRROR_MARKER
from cellforge.versioning import MANIFEST_NAME, VersionError, normalize_version

DerivedKind = Literal["snapshot", "video"]
DERIVED_DIR = "derived"
TEMP_DIR = "TEMP"


class DerivedArtifactError(RuntimeError):
    pass


class DerivedArtifactMissingError(VersionError):
    """該版本沒有可用的衍生檔；訊息說明是從未產生還是已被清除。"""


@dataclass(frozen=True)
class DerivedArtifact:
    entry: dict[str, Any]
    path: Path
    available: bool
    reason: str | None

    @property
    def kind(self) -> str:
        return str(self.entry["kind"])

    @property
    def name(self) -> str:
        return self.path.name


def registry_path(project: Path, version: str) -> Path:
    return project / ".cellforge" / DERIVED_DIR / f"{normalize_version(version)}.json"


def snapshot_dir(project: Path, version: str) -> Path:
    return project / ".cellforge" / DERIVED_DIR / normalize_version(version) / "snapshots"


def video_dir(project: Path, version: str) -> Path:
    temp = project / TEMP_DIR
    temp.mkdir(parents=True, exist_ok=True)
    ignore = temp / ".gitignore"
    if not ignore.is_file():
        # TEMP 內的影片與影格一律不進案子 git（開發書 P5）。
        ignore.write_text("*\n", encoding="utf-8")
    return temp / "videos" / normalize_version(version)


def register(
    project: Path,
    version: str,
    kind: DerivedKind,
    path: Path,
    *,
    producer: str,
    sources: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    version = normalize_version(version)
    if not (project / ".cellforge" / version).is_dir():
        raise DerivedArtifactError(f"找不到版本 {version}，無法登記衍生檔")
    entry = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "version": version,
        "path": path.resolve().relative_to(project.resolve()).as_posix(),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "created": datetime.now().astimezone().isoformat(),
        "producer": producer,
        "sources": sources,
        "settings": settings,
    }
    registry = registry_path(project, version)
    registry.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(registry.with_suffix(".lock")):
        entries = _read(registry)
        entries.append(entry)
        temporary = registry.with_name(f".{registry.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps({"version": version, "artifacts": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, registry)
    return entry


def artifacts(
    project: Path, version: str, kind: DerivedKind | None = None
) -> list[DerivedArtifact]:
    """Registered artifacts of one version, newest first, each checked for existence and hash."""

    found = []
    for entry in reversed(_read(registry_path(project, version))):
        if kind is not None and entry.get("kind") != kind:
            continue
        path = (project / entry["path"]).resolve()
        if project.resolve() not in path.parents:
            continue
        if not path.is_file():
            reason: str | None = f"已登記的 {entry['path']} 已不存在，可重新產生"
        elif sha256_file(path) != entry.get("sha256"):
            reason = f"{entry['path']} 與登記雜湊不符，可能被覆寫，請重新產生"
        else:
            reason = None
        found.append(DerivedArtifact(entry, path, reason is None, reason))
    return found


def latest_available(project: Path, version: str, kind: DerivedKind) -> DerivedArtifact | None:
    return next((item for item in artifacts(project, version, kind) if item.available), None)


def missing_reason(project: Path, version: str, kind: DerivedKind) -> str:
    label = {"video": "影片", "snapshot": "截圖"}[kind]
    stale = [item.reason for item in artifacts(project, version, kind) if not item.available]
    if stale:
        return f"{normalize_version(version)} 沒有可用{label}：{stale[0]}"
    return f"{normalize_version(version)} 尚未產生{label}；請先為此版本產生後再匯出"


def mirrored_version(project: Path) -> str | None:
    """Version currently mirrored in ``build/``, confirmed by comparing the scene hash."""

    build = project / "build"
    marker = build / MIRROR_MARKER
    scene = build / "scene.glb"
    if not marker.is_file() or not scene.is_file():
        return None
    try:
        version = normalize_version(json.loads(marker.read_text("utf-8"))["version"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
    manifest_path = project / ".cellforge" / version / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text("utf-8"))
    recorded = {item["path"]: item["sha256"] for item in manifest.get("artifacts", [])}
    if recorded.get("scene.glb") != sha256_file(scene):
        return None
    return version


def record_build_snapshot(project: Path, image: Path, settings: dict[str, Any]) -> dict | None:
    """Copy a screenshot taken from ``build/`` into the mirrored version's derived snapshots."""

    version = mirrored_version(project)
    if version is None:
        return None
    target_dir = snapshot_dir(project, version)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / image.name
    if image.resolve() != target.resolve():
        shutil.copy2(image, target)
    build = project / "build"
    sources = [
        {"path": f".cellforge/{version}/{name}", "sha256": sha256_file(build / name)}
        for name in ("scene.glb", "timeline.json")
        if (build / name).is_file()
    ]
    return register(
        project,
        version,
        "snapshot",
        target,
        producer="cellforge.snapshot",
        sources=sources,
        settings=settings,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read(registry: Path) -> list[dict[str, Any]]:
    if not registry.is_file():
        return []
    try:
        payload = json.loads(registry.read_text("utf-8"))
    except json.JSONDecodeError as error:
        raise DerivedArtifactError(f"衍生檔登記損毀：{registry}") from error
    return list(payload.get("artifacts", []))
