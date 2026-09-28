"""案子回收區：刪除只是移出專案根目錄，可還原；只有清除回收區項目才真正刪檔。"""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from cellforge.project import resolve_project, unique_project_dir
from cellforge.yamlio import load_yaml

TRASH_META = ".cellforge_trash.json"


class TrashError(RuntimeError):
    """回收區操作失敗；訊息為繁體中文，直接顯示給使用者。"""


def default_trash_root(projects_root: Path) -> Path:
    return projects_root.resolve().parent / "trash"


def move_to_trash(projects_root: Path, trash_root: Path, project_id: str) -> dict[str, Any]:
    try:
        project = resolve_project(projects_root, project_id)
    except FileNotFoundError as error:
        raise TrashError(f"找不到案子：{project_id}") from error
    data = _project_data(project)
    deleted = datetime.now().astimezone()
    trash_root.mkdir(parents=True, exist_ok=True)
    trash_id = f"{project.name}__{deleted.strftime('%Y%m%dT%H%M%S')}"
    target = trash_root / trash_id
    suffix = 2
    while target.exists():
        target = trash_root / f"{trash_id}_{suffix}"
        suffix += 1
    meta = {
        "trash_id": target.name,
        "original_id": project.name,
        "name": data.get("name", project.name),
        "customer": data.get("customer", ""),
        "product": data.get("product", ""),
        "deleted_at": deleted.isoformat(),
        "versions": _version_count(project),
    }
    meta_path = project / TRASH_META
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    try:
        # 同一磁碟上是原子改名；檔案被占用（例如另一程序開著）時整體失敗，不會只搬一半。
        os.replace(project, target)
    except OSError as error:
        meta_path.unlink(missing_ok=True)
        raise TrashError(
            f"無法移動案子 {project_id} 到回收區（檔案可能被占用）：{error}"
        ) from error
    return meta


def list_trash(trash_root: Path) -> list[dict[str, Any]]:
    if not trash_root.is_dir():
        return []
    items = []
    for entry in trash_root.iterdir():
        meta_path = entry / TRASH_META
        if not entry.is_dir() or not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        meta["trash_id"] = entry.name
        items.append(meta)
    return sorted(items, key=lambda item: str(item.get("deleted_at", "")), reverse=True)


def restore_from_trash(projects_root: Path, trash_root: Path, trash_id: str) -> dict[str, Any]:
    entry = _trash_entry(trash_root, trash_id)
    meta = json.loads((entry / TRASH_META).read_text("utf-8"))
    original = str(meta.get("original_id") or entry.name)
    target = projects_root / original
    if target.exists():
        # 原名已被新案子使用：以新 id 還原，不覆蓋任何現有案子。
        target = unique_project_dir(projects_root, original)
    try:
        os.replace(entry, target)
    except OSError as error:
        raise TrashError(f"無法還原 {trash_id}（檔案可能被占用）：{error}") from error
    (target / TRASH_META).unlink(missing_ok=True)
    return {
        "id": target.name,
        "name": meta.get("name", target.name),
        "renamed": target.name != original,
    }


def purge_trash(trash_root: Path, trash_id: str) -> None:
    entry = _trash_entry(trash_root, trash_id)
    try:
        shutil.rmtree(entry, onexc=_clear_readonly)
    except OSError as error:
        raise TrashError(f"無法永久刪除 {trash_id}（檔案可能被占用）：{error}") from error


def _trash_entry(trash_root: Path, trash_id: str) -> Path:
    root = trash_root.resolve()
    entry = (root / trash_id).resolve()
    if entry.parent != root or not (entry / TRASH_META).is_file():
        raise TrashError(f"回收區沒有這個項目：{trash_id}")
    return entry


def _project_data(project: Path) -> dict[str, Any]:
    try:
        return dict(load_yaml(project / "project.yaml") or {})
    except (OSError, ValueError):
        return {}


def _version_count(project: Path) -> int:
    versions = project / ".cellforge"
    if not versions.is_dir():
        return 0
    return sum(
        1
        for item in versions.iterdir()
        if item.is_dir() and item.name[1:].isdigit() and item.name[0] == "v"
    )


def _clear_readonly(function, path, _error) -> None:
    # git 物件在 Windows 上是唯讀檔，rmtree 需要先解除唯讀再重試。
    os.chmod(path, stat.S_IWRITE)
    function(path)
