"""Content-addressed cache for module checks, renders and GLB previews."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cellforge.part_check import (
    PartCheckItem,
    PartCheckResult,
    _default_params,
    _definition,
    _load_file,
    check_module,
)

CACHE_ROOT_ENV = "CELLFORGE_MODULE_CACHE_ROOT"
CACHE_METADATA_FILE = "metadata.json"
CACHE_CHECK_FILE = "check.json"
CACHE_RENDER_FILE = "render.png"
CACHE_PREVIEW_FILE = "preview.glb"

ArtifactKind = Literal["check", "render", "preview"]

_locks_guard = threading.Lock()
_entry_locks: dict[str, threading.Lock] = {}


@dataclass(slots=True)
class CachedCheck:
    result: PartCheckResult
    key: str
    entry: Path
    params: dict[str, Any]
    hit: bool


@dataclass(slots=True)
class CachedFile:
    path: Path
    key: str
    entry: Path
    params: dict[str, Any]
    hit: bool


def default_module_cache_root() -> Path:
    configured = os.environ.get(CACHE_ROOT_ENV)
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[1] / ".cellforge-runtime" / "module-cache"


def effective_params(source: Path, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    module = _load_file(source)
    static = _definition(module, {})
    return {**_default_params(static), **(supplied or {})}


def module_cache_key(source: Path, params: dict[str, Any]) -> tuple[str, str, str]:
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    params_json = json.dumps(
        params,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256()
    digest.update(source_sha256.encode("ascii"))
    digest.update(b"\0")
    digest.update(params_json.encode("utf-8"))
    return digest.hexdigest(), source_sha256, params_json


def cache_entry(
    source: Path,
    params: dict[str, Any],
    cache_root: Path | None = None,
) -> tuple[str, Path, str, str]:
    key, source_sha256, params_json = module_cache_key(source, params)
    root = (cache_root or default_module_cache_root()).resolve()
    return key, root / key, source_sha256, params_json


def _entry_lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _entry_locks.setdefault(key, threading.Lock())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_metadata(
    entry: Path,
    *,
    key: str,
    source: Path,
    source_sha256: str,
    params: dict[str, Any],
) -> None:
    artifacts = sorted(
        path.name
        for path in entry.iterdir()
        if path.is_file() and path.name != CACHE_METADATA_FILE and not path.name.endswith(".tmp")
    )
    _write_json(
        entry / CACHE_METADATA_FILE,
        {
            "key": key,
            "source": str(source.resolve()),
            "source_sha256": source_sha256,
            "params": params,
            "artifacts": artifacts,
        },
    )


def _result_from_json(payload: dict[str, Any]) -> PartCheckResult:
    items = [PartCheckItem(**item) for item in payload.get("items", [])]
    return PartCheckResult(
        module_id=str(payload["module_id"]),
        passed=bool(payload["passed"]),
        items=items,
        source=str(payload.get("source", "")),
    )


def cached_check(
    source: Path,
    supplied_params: dict[str, Any] | None = None,
    *,
    cache_root: Path | None = None,
    force: bool = False,
) -> CachedCheck:
    source = source.resolve()
    params = effective_params(source, supplied_params)
    key, entry, source_sha256, _params_json = cache_entry(source, params, cache_root)
    target = entry / CACHE_CHECK_FILE
    with _entry_lock(key):
        if target.is_file() and not force:
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
                result = _result_from_json(payload)
                result.source = str(source)
                return CachedCheck(result, key, entry, params, True)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        module = _load_file(source)
        result = check_module(module, str(source), params=params)
        _write_json(target, result.as_dict())
        _write_metadata(
            entry,
            key=key,
            source=source,
            source_sha256=source_sha256,
            params=params,
        )
        return CachedCheck(result, key, entry, params, False)


def _cached_file(
    kind: Literal["render", "preview"],
    source: Path,
    supplied_params: dict[str, Any] | None,
    *,
    cache_root: Path | None,
    force: bool,
) -> CachedFile:
    from cellforge.part_artifacts import load_part_source, preview_loaded_part, render_loaded_part

    source = source.resolve()
    params = effective_params(source, supplied_params)
    key, entry, source_sha256, _params_json = cache_entry(source, params, cache_root)
    filename = CACHE_RENDER_FILE if kind == "render" else CACHE_PREVIEW_FILE
    target = entry / filename
    with _entry_lock(key):
        if target.is_file() and not force:
            return CachedFile(target, key, entry, params, True)
        loaded = load_part_source(source, params)
        if kind == "render":
            render_loaded_part(loaded, target)
        else:
            preview_loaded_part(loaded, target)
        _write_metadata(
            entry,
            key=key,
            source=source,
            source_sha256=source_sha256,
            params=params,
        )
        return CachedFile(target, key, entry, params, False)


def cached_render(
    source: Path,
    supplied_params: dict[str, Any] | None = None,
    *,
    cache_root: Path | None = None,
    force: bool = False,
) -> CachedFile:
    return _cached_file("render", source, supplied_params, cache_root=cache_root, force=force)


def cached_preview(
    source: Path,
    supplied_params: dict[str, Any] | None = None,
    *,
    cache_root: Path | None = None,
    force: bool = False,
) -> CachedFile:
    return _cached_file("preview", source, supplied_params, cache_root=cache_root, force=force)


def cached_check_status(
    source: Path,
    supplied_params: dict[str, Any] | None = None,
    *,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    params = effective_params(source.resolve(), supplied_params)
    key, entry, _source_sha256, _params_json = cache_entry(source.resolve(), params, cache_root)
    target = entry / CACHE_CHECK_FILE
    if not target.is_file():
        return {"status": "not_checked", "cache_key": key}
    try:
        result = _result_from_json(json.loads(target.read_text(encoding="utf-8")))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "not_checked", "cache_key": key}
    counts = {
        severity: sum(item.severity == severity for item in result.items)
        for severity in ("fail", "warn", "info")
    }
    return {
        "status": "passed" if result.passed else "failed",
        "passed": result.passed,
        "counts": counts,
        "cache_key": key,
    }
