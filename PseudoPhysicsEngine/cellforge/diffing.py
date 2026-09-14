"""Semantic comparison for immutable CellForge versions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cellforge.yamlio import load_yaml


def diff_versions(project: Path, before: str, after: str) -> dict[str, Any]:
    left = _version(project, before)
    right = _version(project, after)
    changes: list[dict[str, Any]] = []
    for relative in ("source/cell.yaml", "source/process.yaml", "checks.json", "timeline.json"):
        _walk(relative, _load(left / relative), _load(right / relative), changes)
    return {"from": left.name, "to": right.name, "changes": changes, "count": len(changes)}


def _version(project: Path, version: str) -> Path:
    normalized = version if version.startswith("v") else f"v{version}"
    path = project / ".cellforge" / normalized
    if not path.is_dir():
        raise FileNotFoundError(normalized)
    return path


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text("utf-8")) if path.suffix == ".json" else load_yaml(path)


def _walk(path: str, a: Any, b: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _walk(f"{path}.{key}", a.get(key), b.get(key), output)
    elif a != b:
        output.append({"path": path, "before": a, "after": b})
