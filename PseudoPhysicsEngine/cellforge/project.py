"""Project creation and filesystem safety helpers."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from cellforge.versioning import initialize_git
from cellforge.yamlio import dump_yaml


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def project_template() -> Path:
    template = source_root() / "templates" / "project"
    if template.is_dir():
        return template
    return Path(__file__).resolve().parent / "_templates" / "project"


def safe_slug(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    return slug or "project"


def unique_project_dir(root: Path, name: str) -> Path:
    base = safe_slug(name)
    candidate = root / base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base}_{suffix}"
        suffix += 1
    return candidate


def create_project(directory: Path, project_data: dict, *, seed_example: str | None = None) -> Path:
    shutil.copytree(project_template(), directory)
    if seed_example:
        example = source_root() / "examples" / seed_example / "handwritten"
        if not example.is_dir():
            raise ValueError(f"找不到步驟 1 示意案例：{seed_example}")
        for relative in ("workpiece.yaml", "cell.yaml", "process.yaml", "animation/sequence.py"):
            source = example / relative
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # 範例的推估假設與待確認問題：推估值必須帶著對應假設進入新案子。
        for relative in (
            "analysis/assumptions.yaml",
            "analysis/questions.yaml",
            "costing.yaml",
            "electrical.yaml",
        ):
            if (example / relative).is_file():
                shutil.copy2(example / relative, directory / relative)
        # 案例專屬的零件與工具模組（例如 SSD 案的接頭、連板與壓墊工具）
        if (example / "parts").is_dir():
            shutil.copytree(
                example / "parts",
                directory / "parts",
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
    dump_yaml(directory / "project.yaml", project_data)
    initialize_git(directory)
    return directory


def resolve_project(root: Path, project_id: str) -> Path:
    root = root.resolve()
    project = (root / project_id).resolve()
    if project.parent != root or not project.is_dir():
        raise FileNotFoundError(project_id)
    return project


def resolve_inside(project: Path, relative: str) -> Path:
    project = project.resolve()
    path = (project / relative).resolve()
    if project not in path.parents:
        raise ValueError("路徑超出案子目錄")
    return path
