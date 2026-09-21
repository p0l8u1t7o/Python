"""Manifest-backed catalogue for library and project-local parametric modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cellforge.part_check import _default_params, _definition, _load_file
from cellforge.yamlio import load_yaml

MANIFEST_FIELDS = {
    "id",
    "file",
    "tier",
    "category",
    "summary",
    "basis",
    "params",
    "frames",
    "axes",
    "status",
    "from_project",
}
CATEGORIES = {
    "frame",
    "conveying",
    "handling",
    "fixturing",
    "vision",
    "safety",
    "electrical",
    "material_handling",
}
TIERS = {"P", "V"}
STATUSES = {"draft", "production"}


def derive_module_fields(path: Path, file_name: str) -> dict[str, Any]:
    """Load a module and derive every structural manifest field from its ModuleDef."""
    module = _load_file(path)
    initial = _definition(module, {})
    definition = _definition(module, _default_params(initial))
    return {
        "id": definition.id,
        "file": file_name,
        "basis": definition.meta.basis,
        "params": list(definition.params_schema.get("properties", {})),
        "frames": list(definition.frames),
        "axes": [axis.id for axis in definition.axes],
    }


def load_library_catalog(root: Path | None = None) -> list[dict[str, Any]]:
    """Load the checked-in manifest and reject any drift from current ModuleDefs."""
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    library_dir = root / "library"
    payload = load_yaml(library_dir / "manifest.yaml")
    rows = payload.get("modules", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("library/manifest.yaml 的 modules 必須是清單")

    actual_files = {
        path.resolve() for path in library_dir.glob("*.py") if path.name != "__init__.py"
    }
    entries: list[dict[str, Any]] = []
    resolved_files: set[Path] = set()
    ids: list[str] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("library/manifest.yaml 的每筆模組必須是物件")
        missing = sorted(MANIFEST_FIELDS - set(raw))
        if missing:
            raise ValueError(f"library manifest 缺少欄位：{', '.join(missing)}")
        entry = dict(raw)
        path = (root / str(entry["file"])).resolve()
        if root not in path.parents or path not in actual_files:
            raise ValueError(f"library manifest 指向不存在的模組檔：{entry['file']}")
        if entry["category"] not in CATEGORIES:
            raise ValueError(f"模組 {entry['id']} 的 category 不在規格列舉內")
        if entry["tier"] not in TIERS or entry["status"] not in STATUSES:
            raise ValueError(f"模組 {entry['id']} 的 tier 或 status 無效")
        derived = derive_module_fields(path, str(entry["file"]))
        drift = [name for name, value in derived.items() if entry.get(name) != value]
        if drift:
            raise ValueError(
                f"模組 {entry['id']} 的 manifest 與 ModuleDef 不一致：{', '.join(drift)}"
            )
        entry["source"] = "library"
        entries.append(entry)
        resolved_files.add(path)
        ids.append(str(entry["id"]))

    duplicates = sorted({module_id for module_id in ids if ids.count(module_id) > 1})
    if duplicates:
        raise ValueError(f"library manifest 模組 id 重複：{', '.join(duplicates)}")
    missing_files = sorted(path.name for path in actual_files - resolved_files)
    if missing_files:
        raise ValueError(f"library manifest 未收錄模組：{', '.join(missing_files)}")
    return entries


def load_project_catalog(project_dir: Path) -> list[dict[str, Any]]:
    """Derive project-local entries directly from parts/*.py ModuleDefs."""
    parts_dir = project_dir.resolve() / "parts"
    if not parts_dir.is_dir():
        return []
    entries = []
    for path in sorted(parts_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        file_name = path.relative_to(project_dir.resolve()).as_posix()
        structural = derive_module_fields(path, file_name)
        module = _load_file(path)
        summary = (module.__doc__ or "本案自建參數化模組").strip().splitlines()[0]
        entries.append(
            {
                **structural,
                "tier": "P",
                "category": "project",
                "summary": summary,
                "status": "draft",
                "from_project": project_dir.resolve().name,
                "source": "project",
            }
        )
    return entries


def list_available_parts(
    project_dir: Path,
    *,
    include_library: bool = True,
    include_project: bool = True,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if include_library:
        entries.extend(load_library_catalog())
    if include_project:
        entries.extend(load_project_catalog(project_dir))
    return entries
