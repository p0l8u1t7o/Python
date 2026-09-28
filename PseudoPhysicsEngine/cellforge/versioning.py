"""Git and immutable build snapshot helpers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from cellforge.filelock import file_lock
from cellforge.yamlio import load_yaml

VERSION_DIR_PATTERN = re.compile(r"v(\d+)")
MANIFEST_NAME = "manifest.json"

# 舊版快照（無 manifest.json）在建置後嘗試複製的來源檔；只有這些路徑能判斷「建置時不存在」。
SOURCE_FILES = (
    "project.yaml",
    "workpiece.yaml",
    "cell.yaml",
    "process.yaml",
    "vendor/manifest.yaml",
    "analysis/assumptions.yaml",
    "analysis/checklist_map.md",
)


class GitCommitError(RuntimeError):
    """案子 git 操作失敗；訊息含 git 的 stderr，直接顯示給使用者。"""


def git(project_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git for a CellForge project with a fixed identity and a scoped safe.directory.

    案子可能由沙箱或其他帳號建立，git 會以 dubious ownership 拒絕；只對這個案子路徑放行。
    """
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={project_dir.resolve().as_posix()}",
            "-c",
            "user.name=CellForge",
            "-c",
            "user.email=cellforge@localhost",
            *args,
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-600:]
        raise GitCommitError(
            f"案子 git 指令失敗（git {' '.join(args[:2])}，退出碼 {completed.returncode}）："
            f"{detail or '沒有錯誤輸出'}"
        )
    return completed


def initialize_git(project_dir: Path) -> None:
    git(project_dir, "init")
    git(project_dir, "add", ".")
    git(project_dir, "commit", "-m", "Initialize CellForge project")


@contextmanager
def git_lock(project_dir: Path) -> Iterator[None]:
    """Serialize git index writes of one project across API jobs, CLI builds and agents."""
    with file_lock(project_dir / ".git" / "cellforge.lock"):
        yield


def commit_changes(project_dir: Path, message: str, paths: list[str]) -> None:
    """Commit an API mutation without relying on the user's global git identity."""
    if not (project_dir / ".git").is_dir():
        return
    existing_paths = [path for path in paths if (project_dir / path).exists()]
    if not existing_paths:
        return
    with git_lock(project_dir):
        git(project_dir, "add", "--", *existing_paths)
        if git(project_dir, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git(project_dir, "commit", "-m", message)


def try_commit_changes(project_dir: Path, message: str, paths: list[str]) -> str | None:
    """Commit after verified work; a git failure becomes a warning instead of a failure."""
    try:
        commit_changes(project_dir, message, paths)
    except GitCommitError as error:
        return f"工作已完成，但案子 git 提交失敗：{error}"
    return None


class VersionError(FileNotFoundError):
    """版本資料錯誤；訊息為繁體中文，直接顯示給使用者與代理。"""


class VersionNotFoundError(VersionError):
    pass


class VersionCorruptError(VersionError):
    pass


class VersionIncompleteError(VersionError):
    def __init__(self, version: str, missing: str, purpose: str):
        self.version = version
        self.missing = missing
        self.purpose = purpose
        super().__init__(
            f"版本資料不完整：{version} 未保存 {missing}，無法{purpose}；"
            "不會改讀工作區或其他版本的資料。"
        )


def normalize_version(version: str | int) -> str:
    text = str(version).strip()
    if text.isdigit():
        text = f"v{text}"
    if not VERSION_DIR_PATTERN.fullmatch(text):
        raise VersionNotFoundError(f"版本名稱格式錯誤：{version}（應為 v1、v2…）")
    return text


def version_dirs(project_dir: Path) -> list[Path]:
    """Published version directories in numeric order; staging and reservations never match."""
    root = project_dir / ".cellforge"
    if not root.is_dir():
        return []
    found = [
        (int(match.group(1)), path)
        for path in root.iterdir()
        if path.is_dir() and (match := VERSION_DIR_PATTERN.fullmatch(path.name))
    ]
    return [path for _number, path in sorted(found)]


def latest_version_dir(project_dir: Path) -> Path | None:
    directories = version_dirs(project_dir)
    return directories[-1] if directories else None


@dataclass
class VersionContext:
    """匯出器與其他讀取端取得指定版本資料的唯一入口，絕不回頭讀工作區。"""

    project: Path
    directory: Path
    manifest: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def open(cls, project: Path, version: str | None = None) -> VersionContext:
        if version is None:
            directory = latest_version_dir(project)
            if directory is None:
                raise VersionNotFoundError("尚無任何建置版本；請先執行 cell build")
        else:
            name = normalize_version(version)
            directory = project / ".cellforge" / name
            if not directory.is_dir():
                raise VersionNotFoundError(f"找不到版本 {name}")
        manifest_path = directory / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.is_file() else None
        context = cls(project, directory, manifest)
        if context.legacy:
            context.warnings.append(
                f"{context.name} 為舊版快照：沒有版本 manifest，來源是在建置完成後才從工作區複製，"
                "且未記錄雜湊，無法證明與產物一致。"
            )
        return context

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def number(self) -> int:
        return int(self.directory.name[1:])

    @property
    def legacy(self) -> bool:
        return self.manifest is None

    def covers(self, relative: str) -> bool:
        """Whether this version's freeze policy would have saved ``relative`` if it existed."""
        relative = relative.replace("\\", "/")
        if self.manifest is None:
            return relative in SOURCE_FILES
        policy = self.manifest.get("source_policy", {})
        return any(
            path_matches(relative, pattern) for pattern in policy.get("include", [])
        ) and not any(path_matches(relative, pattern) for pattern in policy.get("exclude", []))

    def artifact(self, name: str, purpose: str) -> Path:
        path = self.optional_artifact(name)
        if path is None:
            raise VersionIncompleteError(self.name, name, purpose)
        return path

    def optional_artifact(self, name: str) -> Path | None:
        path = self._inside(self.directory, name)
        if not path.is_file():
            return None
        if self.manifest is None:
            return path
        # 有 manifest 的版本只承認登記過的產物，並逐次核對雜湊。
        recorded = self._recorded("artifacts").get(name)
        return self._verified(path, recorded, name) if recorded else None

    def artifact_json(self, name: str, purpose: str) -> Any:
        return json.loads(self.artifact(name, purpose).read_text("utf-8"))

    def source(self, relative: str, purpose: str) -> Path:
        path = self._source_file(relative)
        if path is None:
            raise VersionIncompleteError(self.name, f"source/{relative}", purpose)
        return path

    def optional_source(self, relative: str, purpose: str) -> Path | None:
        """Return ``None`` only when the file provably did not exist at build time."""
        path = self._source_file(relative)
        if path is not None:
            return path
        if self.covers(relative):
            return None
        raise VersionIncompleteError(self.name, f"source/{relative}", purpose)

    def _source_file(self, relative: str) -> Path | None:
        relative = relative.replace("\\", "/")
        path = self._inside(self.directory / "source", relative)
        if not path.is_file():
            return None
        if self.manifest is None:
            return path
        recorded = self._recorded("sources").get(relative)
        return self._verified(path, recorded, f"source/{relative}") if recorded else None

    def _recorded(self, section: str) -> dict[str, str]:
        assert self.manifest is not None
        return {item["path"]: item["sha256"] for item in self.manifest.get(section, [])}

    def _verified(self, path: Path, recorded: str, label: str) -> Path:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != recorded:
            raise VersionCorruptError(
                f"版本檔案雜湊不符：{self.name}/{label} 與 manifest 記錄不同，快照可能遭修改；"
                "請改用其他版本或重新建置。"
            )
        return path

    def source_yaml(self, relative: str, purpose: str) -> Any:
        return load_yaml(self.source(relative, purpose))

    def optional_source_yaml(self, relative: str, purpose: str, default: Any = None) -> Any:
        path = self.optional_source(relative, purpose)
        if path is None:
            return default
        loaded = load_yaml(path)
        return default if loaded is None else loaded

    def _inside(self, root: Path, relative: str) -> Path:
        base = root.resolve()
        path = (root / relative).resolve()
        if base not in path.parents:
            raise VersionNotFoundError(f"版本路徑超出 {self.name}：{relative}")
        return path


def restore_build(project_dir: Path, version_dir: Path) -> None:
    """Restore generated build files after a presentation-agent policy violation."""
    from cellforge.version_store import mirror_build

    mirror_build(project_dir, version_dir, force=True)


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """``**/`` 跨任意層目錄、``*`` 與 ``?`` 不跨 ``/``；路徑一律用 POSIX 分隔。"""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts) + r"\Z")


def path_matches(relative: str, pattern: str) -> bool:
    return _glob_regex(pattern).match(relative.replace("\\", "/")) is not None
