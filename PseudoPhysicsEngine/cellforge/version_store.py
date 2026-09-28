"""不可變版本快照：凍結來源、保留版本號、在 staging 建置，驗證產物後原子發布。

流程：
1. 在發布鎖內保留下一個版本號（每個保留各自持有一個作業系統鎖，程序崩潰即自動失效）。
2. 把工作區來源依 ``SOURCE_INCLUDE`` 凍結到 ``.cellforge/_staging/vN-*/source``；
   輸入證據與大檔以 SHA-256 內容定址存到 ``.cellforge/objects``，版本內為硬連結或複本。
3. 建置只讀凍結來源、只寫 staging；實際載入的庫模組另存於 staging 的 ``library/``。
4. 驗證產物（schema、STEP 名稱、GLB 回讀、雜湊）與庫模組未在建置期間變動後，
   寫入 manifest，再以單一 rename 發布成 ``.cellforge/vN``。
任何一步失敗都只留下被清除的 staging，不會出現可被當成成功版本的半成品。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any

from cellforge.filelock import HeldLock, file_lock
from cellforge.schema import SCHEMAS, VersionManifest
from cellforge.versioning import (
    MANIFEST_NAME,
    VERSION_DIR_PATTERN,
    GitCommitError,
    git,
    git_lock,
    path_matches,
    version_dirs,
)
from cellforge.yamlio import load_yaml

STAGING_DIR = "_staging"
RESERVED_DIR = "_reserved"
OBJECTS_DIR = "objects"
PUBLISH_LOCK = ".publish.lock"
MIRROR_MARKER = ".cellforge_version.json"
OBJECT_THRESHOLD_BYTES = 1024 * 1024

# 凍結範圍：涵蓋內的案內檔案全部進快照；涵蓋內卻不存在，代表建置當時沒有這個檔。
SOURCE_INCLUDE = (
    "project.yaml",
    "workpiece.yaml",
    "cell.yaml",
    "process.yaml",
    "costing.yaml",
    "electrical.yaml",
    "drawing_templates/**",
    "inputs/**",
    "analysis/*.yaml",
    "analysis/*.md",
    "analysis/*.json",
    "analysis/*.txt",
    "analysis/extracted/**/*.md",
    "analysis/extracted/**/*.json",
    "analysis/extracted/**/*.txt",
    "animation/**",
    "parts/**",
    "vendor/**",
    "presentation/theme.json",
    "presentation/camera.json",
    "presentation/easing.json",
    "viewer/theme/**",
    "drawing_templates/**",
)
SOURCE_EXCLUDE = ("**/__pycache__/**", "**/*.pyc", "**/.gitkeep", "**/.DS_Store", "**/Thumbs.db")
# 輸入證據一律內容定址共用，避免每個版本各存一份照片與 PDF；證據清單本身照常複製。
OBJECT_PATTERNS = ("inputs/**",)
OBJECT_EXCLUDE = ("inputs/manifest.yaml",)
ENGINE_PACKAGES = (
    "cadquery",
    "cadquery-ocp",
    "numpy",
    "scipy",
    "python-fcl",
    "trimesh",
    "pygltflib",
    "pydantic",
    "ruamel.yaml",
)
STORE_GITIGNORE = f"{STAGING_DIR}/\n{RESERVED_DIR}/\n*.lock\n"
BUILD_JOB_ENV = "CELLFORGE_JOB_ID"
BUILD_ORIGIN_ENV = "CELLFORGE_BUILD_ORIGIN"


class VersionPublishError(RuntimeError):
    pass


@dataclass
class StagedBuild:
    project: Path
    number: int
    directory: Path
    started: datetime
    sources: list[dict[str, Any]] = field(default_factory=list)
    library: list[dict[str, Any]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"v{self.number}"

    @property
    def source_dir(self) -> Path:
        return self.directory / "source"

    @property
    def output_dir(self) -> Path:
        return self.directory

    def module_file_sha256(self, module_file: str) -> str:
        """Hash of the frozen copy a module was actually loaded from."""
        relative = module_file.replace("\\", "/").strip("/")
        base = self.directory if relative.startswith("library/") else self.source_dir
        return _sha256_file(base / relative)


def store_dir(project: Path) -> Path:
    return project / ".cellforge"


def ensure_store(project: Path) -> Path:
    store = store_dir(project)
    store.mkdir(parents=True, exist_ok=True)
    ignore = store / ".gitignore"
    if not ignore.is_file() or ignore.read_text("utf-8") != STORE_GITIGNORE:
        ignore.write_text(STORE_GITIGNORE, encoding="utf-8")
    return store


@contextmanager
def stage_build(project: Path, library_root: Path) -> Iterator[StagedBuild]:
    """Reserve a version number and freeze all inputs; always clean staging on exit."""

    project = project.resolve()
    store = ensure_store(project)
    reservation, number = reserve_version(project)
    directory = store / STAGING_DIR / f"v{number}-{uuid.uuid4().hex[:8]}"
    try:
        directory.mkdir(parents=True)
        stage = StagedBuild(project, number, directory, datetime.now().astimezone())
        stage.sources = freeze_sources(project, stage.source_dir, store)
        stage.library = freeze_library(stage.source_dir, library_root, directory)
        yield stage
    finally:
        if directory.exists():
            remove_tree(directory)
        reservation.release(remove=True)


def reserve_version(project: Path) -> tuple[HeldLock, int]:
    store = ensure_store(project)
    reserved = store / RESERVED_DIR
    with file_lock(store / PUBLISH_LOCK):
        active: set[int] = set()
        for lock_path in sorted(reserved.glob("v*.lock")):
            match = VERSION_DIR_PATTERN.fullmatch(lock_path.stem)
            if not match:
                continue
            probe = HeldLock(lock_path)
            if probe.try_acquire():
                # 沒有程序持有這個保留：原本的建置已崩潰，版本號可以回收。
                probe.release(remove=True)
                continue
            active.add(int(match.group(1)))
        _remove_orphan_staging(store, active)
        published = {int(path.name[1:]) for path in version_dirs(project)}
        number = max(published | active, default=0) + 1
        lock = HeldLock(reserved / f"v{number}.lock")
        if not lock.try_acquire():
            raise VersionPublishError(f"無法保留版本號 v{number}；請稍後重試")
    return lock, number


def _remove_orphan_staging(store: Path, active: set[int]) -> None:
    staging = store / STAGING_DIR
    if not staging.is_dir():
        return
    for directory in staging.iterdir():
        number = directory.name.partition("-")[0]
        match = VERSION_DIR_PATTERN.fullmatch(number)
        if directory.is_dir() and (not match or int(match.group(1)) not in active):
            remove_tree(directory)


def freeze_sources(project: Path, destination: Path, store: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for relative, path in iter_source_files(project):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        as_object = path.stat().st_size >= OBJECT_THRESHOLD_BYTES or (
            relative not in OBJECT_EXCLUDE
            and any(path_matches(relative, pattern) for pattern in OBJECT_PATTERNS)
        )
        if as_object:
            digest, size = _store_object(store, path)
            _link_or_copy(_object_path(store, digest), target)
        else:
            digest, size = _copy_hashing(path, target)
        entries.append(
            {
                "path": relative,
                "sha256": digest,
                "size": size,
                "stored": "object" if as_object else "copy",
            }
        )
    return entries


def iter_source_files(project: Path) -> Iterator[tuple[str, Path]]:
    roots = sorted({pattern.split("/", 1)[0] for pattern in SOURCE_INCLUDE})
    seen: set[str] = set()
    for root in roots:
        candidate = project / root
        if candidate.is_file():
            files: Iterable[Path] = [candidate]
        elif candidate.is_dir():
            files = sorted(path for path in candidate.rglob("*") if path.is_file())
        else:
            continue
        for path in files:
            relative = path.relative_to(project).as_posix()
            if relative in seen or not source_included(relative):
                continue
            seen.add(relative)
            yield relative, path


def source_included(relative: str) -> bool:
    return any(path_matches(relative, pattern) for pattern in SOURCE_INCLUDE) and not any(
        path_matches(relative, pattern) for pattern in SOURCE_EXCLUDE
    )


def freeze_library(source_dir: Path, library_root: Path, destination: Path) -> list[dict[str, Any]]:
    """Copy every library file the frozen cell and parts import, and record its hash."""

    entries = []
    for relative in used_library_files(source_dir, library_root):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        digest, size = _copy_hashing(library_root.parent / relative, target)
        entries.append({"path": relative, "sha256": digest, "size": size, "stored": "copy"})
    return entries


def used_library_files(source_dir: Path, library_root: Path) -> list[str]:
    try:
        cell = load_yaml(source_dir / "cell.yaml") or {}
    except (OSError, ValueError):
        cell = {}
    try:
        vendor_manifest = load_yaml(source_dir / "vendor" / "manifest.yaml") or {}
    except (OSError, ValueError):
        vendor_manifest = {}
    vendors = {
        item.get("id"): item
        for item in vendor_manifest.get("vendors", []) or []
        if isinstance(item, dict)
    }
    pending: list[Path] = []
    try:
        product = load_yaml(source_dir / "workpiece.yaml") or {}
    except (OSError, ValueError):
        product = {}
    # 多零件產品的零件模組同樣要凍結。
    for part in product.get("parts", []) or []:
        pending.extend(
            path
            for reference in _part_references(part)
            if (path := _part_path(reference, source_dir, library_root)) is not None
        )
    for machine in cell.get("machines", []) or []:
        for module in machine.get("modules", []) or []:
            item = vendors.get(module.get("vendor")) if module.get("vendor") else None
            # 原廠 URDF／STEP 模組不依賴 robot_stub；只有近似條目（或讀不到條目時保守地）才凍結它。
            if module.get("vendor") and (item is None or item.get("approximated", False)):
                pending.append(library_root / "robot_stub.py")
            pending.extend(
                path
                for part in _part_references(module)
                if (path := _part_path(part, source_dir, library_root)) is not None
            )
    used: set[Path] = set()
    visited: set[Path] = set()
    while pending:
        path = pending.pop().resolve()
        if path in visited or not path.is_file():
            continue
        visited.add(path)
        if library_root.resolve() in path.parents:
            used.add(path)
        pending.extend(_library_imports(path, library_root))
    if used:
        init = library_root / "__init__.py"
        if init.is_file():
            used.add(init.resolve())
    base = library_root.resolve().parent
    return sorted(path.relative_to(base).as_posix() for path in used)


def _part_references(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        part = value.get("part")
        if isinstance(part, str):
            yield part
        for key, item in value.items():
            if key != "part":
                yield from _part_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _part_references(item)


def _part_path(part: str, source_dir: Path, library_root: Path) -> Path | None:
    relative = part.replace("\\", "/").strip("/")
    if relative.startswith("library/"):
        return library_root.parent / relative
    candidate = source_dir / relative
    return candidate if candidate.is_file() else None


def _library_imports(path: Path, library_root: Path) -> list[Path]:
    try:
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    found = []
    for name in names:
        parts = name.split(".")
        if parts[0] != "library" or len(parts) < 2:
            continue
        for end in range(len(parts), 1, -1):
            stem = library_root.joinpath(*parts[1:end])
            candidate = next(
                (
                    item
                    for item in (stem.with_suffix(".py"), stem / "__init__.py")
                    if item.is_file()
                ),
                None,
            )
            if candidate is not None:
                found.append(candidate)
                break
    return found


def verify_library_unchanged(stage: StagedBuild, library_root: Path) -> None:
    for entry in stage.library:
        live = library_root.parent / entry["path"]
        if not live.is_file() or _sha256_file(live) != entry["sha256"]:
            raise VersionPublishError(
                f"建置期間共用模組庫 {entry['path']} 被修改，產物可能混用新舊程式碼；"
                "版本不發布，請重新建置。"
            )


def verify_outputs(
    directory: Path, level: str, number: int, expected_nodes: list[str]
) -> list[dict[str, Any]]:
    """Read every artifact back before publishing; any doubt means no version."""

    from pygltflib import GLTF2

    from cellforge.schema import Checks, Timeline

    required = ["scene.step", "scene.glb", "timeline.json", "step_validation.json"]
    required.append("render_brief.md")
    if level == "L1":
        required.append("checks.json")
    for name in required:
        path = directory / name
        if not path.is_file() or path.stat().st_size == 0:
            raise VersionPublishError(f"建置產物缺少或為空：{name}；版本不發布")
    Timeline.model_validate_json((directory / "timeline.json").read_text("utf-8"))
    step = json.loads((directory / "step_validation.json").read_text("utf-8"))
    if not (step.get("name_match") and step.get("count_match")):
        raise VersionPublishError("STEP 回讀名稱或數量不符；版本不發布")
    if level == "L1":
        checks = Checks.model_validate_json((directory / "checks.json").read_text("utf-8"))
        if checks.version != number:
            raise VersionPublishError(
                f"checks.json 版本號 {checks.version} 與發布版本 v{number} 不符；版本不發布"
            )
    costing = directory / "costing.json"
    if costing.is_file():
        data = json.loads(costing.read_text("utf-8"))
        if data.get("version") != number or "totals" not in data:
            raise VersionPublishError("costing.json 版本號或內容不符；版本不發布")
    electrical = directory / "electrical.json"
    if electrical.is_file():
        data = json.loads(electrical.read_text("utf-8"))
        if data.get("version") != number or "devices" not in data:
            raise VersionPublishError("electrical.json 版本號或內容不符；版本不發布")
    gltf = GLTF2().load(str(directory / "scene.glb"))
    scene = gltf.scenes[gltf.scene or 0] if gltf.scenes else None
    roots = {gltf.nodes[index].name for index in (scene.nodes if scene else [])}
    missing = sorted(set(expected_nodes) - roots)
    if missing:
        raise VersionPublishError(f"GLB 回讀缺少節點：{', '.join(missing)}；版本不發布")
    artifacts = []
    for path in sorted(item for item in directory.iterdir() if item.is_file()):
        if path.name == MANIFEST_NAME:
            continue
        artifacts.append(
            {
                "path": path.name,
                "sha256": _sha256_file(path),
                "size": path.stat().st_size,
                "stored": "copy",
            }
        )
    return artifacts


def write_manifest(stage: StagedBuild, manifest: dict[str, Any]) -> dict[str, Any]:
    validated = VersionManifest.model_validate(manifest).model_dump(mode="json")
    temporary = stage.directory / f".{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, stage.directory / MANIFEST_NAME)
    return validated


def publish(stage: StagedBuild) -> tuple[Path, list[str]]:
    """Atomically turn the staging directory into ``.cellforge/vN`` and refresh ``build/``."""

    store = store_dir(stage.project)
    target = store / stage.name
    warnings: list[str] = []
    with file_lock(store / PUBLISH_LOCK):
        if target.exists():
            raise VersionPublishError(f"版本 {stage.name} 已存在；拒絕覆寫已發布版本")
        _rename_with_retry(stage.directory, target)
        try:
            mirror_build(stage.project, target)
        except OSError as error:
            # 版本本身已完整發布；build/ 只是工作區鏡像，更新失敗不可回報成建置失敗。
            warnings.append(f"版本 {stage.name} 已發布，但 build/ 鏡像更新失敗：{error}")
    return target, warnings


def mirror_build(project: Path, version_dir: Path, *, force: bool = False) -> bool:
    """Make ``build/`` mirror exactly one version; older versions never overwrite newer ones."""

    build = project / "build"
    build.mkdir(parents=True, exist_ok=True)
    marker = build / MIRROR_MARKER
    number = int(version_dir.name[1:])
    if marker.is_file() and not force:
        try:
            current = int(json.loads(marker.read_text("utf-8")).get("number", 0))
        except (ValueError, json.JSONDecodeError):
            current = 0
        if current > number:
            return False
    manifest_path = version_dir / MANIFEST_NAME
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text("utf-8"))
        names = [item["path"] for item in manifest.get("artifacts", [])]
        manifest_sha256 = _sha256_file(manifest_path)
    else:
        names = [
            path.name
            for path in version_dir.iterdir()
            if path.is_file() and path.name not in {"astra_result.json", MANIFEST_NAME}
        ]
        manifest_sha256 = None
    # 移除上一個版本殘留的頂層檔（例如舊截圖），避免被誤認為屬於這個版本。
    for existing in build.iterdir():
        if existing.is_file() and existing.name not in names and existing.name != MIRROR_MARKER:
            existing.unlink()
    for name in names:
        shutil.copy2(version_dir / name, build / name)
    marker.write_text(
        json.dumps(
            {
                "version": version_dir.name,
                "number": number,
                "manifest_sha256": manifest_sha256,
                "mirrored": datetime.now().astimezone().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return True


def commit_version(project: Path, name: str) -> str | None:
    """Commit the published version; failure is reported, the published version stays valid."""

    if not (project / ".git").is_dir():
        return None
    paths = [
        path
        for path in (".cellforge", "project.yaml", "workpiece.yaml", "cell.yaml", "process.yaml")
        if (project / path).exists()
    ]
    if (project / "animation").is_dir():
        paths.append("animation")
    try:
        with git_lock(project):
            git(project, "add", "--", *paths)
            git(project, "commit", "--allow-empty", "-m", f"build {name}")
    except GitCommitError as error:
        return f"版本 {name} 已發布，但案子 git 提交失敗：{error}"
    return None


def engine_info(platform_root: Path) -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for name in ENGINE_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    try:
        package_version: str | None = metadata.version("cellforge")
    except metadata.PackageNotFoundError:
        package_version = None
    commit, dirty = _git_state(platform_root)
    return {
        "package_version": package_version,
        "git_commit": commit,
        "git_dirty": dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
    }


def _git_state(root: Path) -> tuple[str | None, bool | None]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
        )
        if head.returncode != 0:
            return None, None
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return head.stdout.strip() or None, dirty


@lru_cache(maxsize=1)
def schema_fingerprint() -> str:
    schemas = {name: model.model_json_schema() for name, model in sorted(SCHEMAS.items())}
    payload = json.dumps(schemas, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_policy() -> dict[str, Any]:
    return {
        "include": list(SOURCE_INCLUDE),
        "exclude": list(SOURCE_EXCLUDE),
        "object_threshold_bytes": OBJECT_THRESHOLD_BYTES,
    }


def expanded_params(params_schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    properties = params_schema.get("properties", {})
    defaults = (
        {
            name: schema["default"]
            for name, schema in properties.items()
            if isinstance(schema, dict) and "default" in schema
        }
        if isinstance(properties, dict)
        else {}
    )
    return {**defaults, **params}


def remove_tree(path: Path) -> None:
    def clear_readonly(function: Any, target: str, _error: BaseException) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onexc=clear_readonly)


def _object_path(store: Path, digest: str) -> Path:
    return store / OBJECTS_DIR / "sha256" / digest[:2] / digest


def _store_object(store: Path, source: Path) -> tuple[str, int]:
    incoming = store / OBJECTS_DIR / f".incoming-{uuid.uuid4().hex}"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    try:
        digest, size = _copy_hashing(source, incoming)
        target = _object_path(store, digest)
        if target.is_file():
            incoming.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(incoming, target)
    finally:
        incoming.unlink(missing_ok=True)
    return digest, size


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _copy_hashing(source: Path, target: Path) -> tuple[str, int]:
    """Copy while hashing the bytes actually written, so the record always matches the copy."""

    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, target.open("wb") as writer:
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
            writer.write(chunk)
            size += len(chunk)
    shutil.copystat(source, target)
    return digest.hexdigest(), size


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rename_with_retry(source: Path, target: Path, attempts: int = 20) -> None:
    for attempt in range(attempts):
        try:
            os.rename(source, target)
            return
        except PermissionError:
            # Windows 防毒或索引服務可能短暫鎖住剛寫完的檔案。
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))
