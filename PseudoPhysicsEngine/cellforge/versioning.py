"""Git and immutable build snapshot helpers."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SOURCE_FILES = (
    "project.yaml",
    "workpiece.yaml",
    "cell.yaml",
    "process.yaml",
    "vendor/manifest.yaml",
    "analysis/assumptions.yaml",
    "analysis/checklist_map.md",
)


def initialize_git(project_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=project_dir, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=CellForge",
            "-c",
            "user.email=cellforge@localhost",
            "commit",
            "-m",
            "Initialize CellForge project",
        ],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


def commit_changes(project_dir: Path, message: str, paths: list[str]) -> None:
    """Commit an API mutation without relying on the user's global git identity."""
    if not (project_dir / ".git").is_dir():
        return
    existing_paths = [path for path in paths if (project_dir / path).exists()]
    if not existing_paths:
        return
    subprocess.run(
        ["git", "add", "--", *existing_paths],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=project_dir,
        capture_output=True,
    )
    if staged.returncode == 0:
        return
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=CellForge",
            "-c",
            "user.email=cellforge@localhost",
            "commit",
            "-m",
            message,
        ],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


def snapshot_build(project_dir: Path, output_names: list[str]) -> int:
    versions_dir = project_dir / ".cellforge"
    versions_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        int(match.group(1))
        for path in versions_dir.iterdir()
        if (match := re.fullmatch(r"v(\d+)", path.name))
    ]
    version = max(existing, default=0) + 1
    target = versions_dir / f"v{version}"
    target.mkdir()
    for name in output_names:
        source = project_dir / "build" / name
        if source.is_file():
            shutil.copy2(source, target / name)
    source_dir = target / "source"
    for name in SOURCE_FILES:
        source = project_dir / name
        if source.is_file():
            destination = source_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    if (project_dir / ".git").is_dir():
        subprocess.run(
            [
                "git",
                "add",
                ".cellforge",
                "project.yaml",
                "workpiece.yaml",
                "cell.yaml",
                "process.yaml",
                "animation",
            ],
            cwd=project_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CellForge",
                "-c",
                "user.email=cellforge@localhost",
                "commit",
                "--allow-empty",
                "-m",
                f"build v{version}",
            ],
            cwd=project_dir,
            check=True,
            capture_output=True,
        )
    return version


def latest_version_dir(project_dir: Path) -> Path | None:
    versions = [
        path
        for path in (project_dir / ".cellforge").glob("v*")
        if path.is_dir() and path.name[1:].isdigit()
    ]
    return max(versions, key=lambda path: int(path.name[1:]), default=None)


def restore_build(project_dir: Path, version_dir: Path) -> None:
    """Restore generated build files after a presentation-agent policy violation."""
    build_dir = project_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    for source in version_dir.iterdir():
        if source.is_file() and source.name != "astra_result.json":
            shutil.copy2(source, build_dir / source.name)
