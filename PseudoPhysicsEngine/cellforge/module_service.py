"""Project-aware module discovery, detail views and library promotion."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cellforge.module_cache import cached_check, cached_check_status, effective_params
from cellforge.part_catalog import CATEGORIES, derive_module_fields, load_library_catalog
from cellforge.part_check import BASIS_TEMPLATE_TEXT, _definition, _load_file
from cellforge.project import source_root
from cellforge.yamlio import dump_yaml, load_yaml

PROMOTION_FALLBACK_CATEGORY = "handling"
PART_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _part_skeleton(module_id: str, category: str) -> str:
    return f'''"""本案自建的 {module_id} 參數化模組骨架。"""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

CATEGORY = {category!r}
BODY_COLOR = cq.Color(0.58, 0.64, 0.70)
MOUNT_COLOR = cq.Color(0.24, 0.27, 0.31)


def _dimensions(params: dict) -> tuple[float, float, float]:
    return (
        float(params.get("width_mm", 300)),
        float(params.get("depth_mm", 240)),
        float(params.get("height_mm", 200)),
    )


def build(params: dict) -> cq.Assembly:
    width, depth, height = _dimensions(params)
    plate_thickness = height * 0.08
    body_height = height - plate_thickness
    hole_spacing_x = width * 0.38
    hole_spacing_y = depth * 0.38
    hole_diameter = min(width, depth) * 0.04
    plate = (
        cq.Workplane("XY")
        .box(width, depth, plate_thickness)
        .faces(">Z")
        .workplane()
        .rect(hole_spacing_x * 2, hole_spacing_y * 2, forConstruction=True)
        .vertices()
        .hole(hole_diameter)
        .translate((0, 0, plate_thickness / 2))
    )
    body = (
        cq.Workplane("XY")
        .box(width * 0.72, depth * 0.72, body_height)
        .translate((0, 0, plate_thickness + body_height / 2))
    )
    assembly = cq.Assembly(name=params.get("name", {module_id!r}))
    assembly.add(plate, name="mounting_plate", color=MOUNT_COLOR)
    assembly.add(body, name="mechanism_body", color=BODY_COLOR)
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _width, _depth, height = _dimensions(params)
    return ModuleDef(
        id={module_id!r},
        params_schema=MODULE.params_schema,
        frames={{
            "mount": Frame(xyz=(0, 0, 0), link="mounting_plate"),
            "service": Frame(xyz=(0, 0, height), link="mechanism_body"),
        }},
        collision="box",
        meta=ModuleMeta(basis={BASIS_TEMPLATE_TEXT!r}),
    )


MODULE = ModuleDef(
    id={module_id!r},
    params_schema={{
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {{
            "width_mm": {{"type": "number", "minimum": 100, "maximum": 2000, "default": 300}},
            "depth_mm": {{"type": "number", "minimum": 100, "maximum": 2000, "default": 240}},
            "height_mm": {{"type": "number", "minimum": 80, "maximum": 3000, "default": 200}},
        }},
        "additionalProperties": False,
    }},
    frames={{
        "mount": Frame(xyz=(0, 0, 0), link="mounting_plate"),
        "service": Frame(xyz=(0, 0, 200), link="mechanism_body"),
    }},
    collision="box",
    meta=ModuleMeta(basis={BASIS_TEMPLATE_TEXT!r}),
)
'''


def create_part(
    project: Path,
    module_id: str,
    category: str,
    *,
    from_library: str | None = None,
    catalog_root: Path | None = None,
) -> dict[str, Any]:
    """Create a project-local module skeleton or editable copy of a library module."""
    project = project.resolve()
    catalog_root = (catalog_root or source_root()).resolve()
    if not PART_ID_PATTERN.fullmatch(module_id):
        raise ValueError("模組 id 必須以英文字母開頭，且只能包含英文字母、數字與底線")
    if category not in CATEGORIES:
        raise ValueError(f"模組 category 不在規格列舉內：{category}")
    parts_dir = project / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    target = parts_dir / f"{module_id}.py"
    if target.exists():
        raise ValueError(f"案內模組檔已存在：{target.name}")

    if from_library is None:
        content = _part_skeleton(module_id, category)
    else:
        entries = {entry["id"]: entry for entry in load_library_catalog(catalog_root)}
        entry = entries.get(from_library)
        if entry is None:
            raise ValueError(f"模組庫找不到可複製的模組：{from_library}")
        source = (catalog_root / str(entry["file"])).resolve()
        content = source.read_text(encoding="utf-8")
        literal = re.compile(rf"(?P<quote>['\"]){re.escape(from_library)}(?P=quote)")
        content, replacements = literal.subn(
            lambda match: f"{match.group('quote')}{module_id}{match.group('quote')}",
            content,
        )
        if replacements == 0:
            raise ValueError(f"庫模組 {from_library} 內找不到可改寫的模組 id")
        category_line = f"CATEGORY = {category!r}"
        if re.search(r"(?m)^CATEGORY\s*=.*$", content):
            content = re.sub(r"(?m)^CATEGORY\s*=.*$", category_line, content)
        else:
            content = f"{content.rstrip()}\n\n{category_line}\n"

    target.write_text(content, encoding="utf-8")
    return {
        "id": module_id,
        "category": category,
        "path": str(target),
        "from": from_library,
    }


@dataclass(slots=True)
class ModuleResource:
    id: str
    source: Path
    source_kind: str
    params: dict[str, Any]
    parameter_sets: list[dict[str, Any]]
    usages: list[dict[str, Any]]
    catalog: dict[str, Any] | None = None


def _station_usage(project: Path) -> dict[str, list[str]]:
    process_path = project / "process.yaml"
    if not process_path.is_file():
        return {}
    process = load_yaml(process_path) or {}
    result: dict[str, list[str]] = {}
    for station in process.get("stations", []):
        for instance_id in station.get("modules", []):
            result.setdefault(str(instance_id), []).append(str(station.get("id", "")))
    return result


def _source_for_part(project: Path, catalog_root: Path, part: str) -> Path:
    normalized = part.replace("\\", "/").lstrip("/")
    if normalized.startswith("library/"):
        candidate = (catalog_root / normalized).resolve()
        allowed = (catalog_root / "library").resolve()
    else:
        candidate = (project / normalized).resolve()
        allowed = project.resolve()
    if candidate != allowed and allowed not in candidate.parents:
        raise ValueError(f"模組路徑超出允許範圍：{part}")
    return candidate


def _usages(project: Path, catalog_root: Path) -> dict[Path, list[dict[str, Any]]]:
    cell_path = project / "cell.yaml"
    if not cell_path.is_file():
        return {}
    stations = _station_usage(project)
    cell = load_yaml(cell_path) or {}
    result: dict[Path, list[dict[str, Any]]] = {}
    for machine in cell.get("machines", []):
        for instance in machine.get("modules", []):
            part = instance.get("part")
            if not part:
                continue
            source = _source_for_part(project, catalog_root, str(part))
            usage = {
                "machine_id": str(machine.get("id", "")),
                "instance_id": str(instance.get("id", "")),
                "stations": stations.get(str(instance.get("id", "")), []),
                "part": str(part),
                "params": dict(instance.get("params") or {}),
                "trust": instance.get("trust") or (instance.get("pose") or {}).get("trust"),
            }
            result.setdefault(source, []).append(usage)
    return result


def _unique_parameter_sets(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def project_modules(project: Path, catalog_root: Path | None = None) -> list[ModuleResource]:
    project = project.resolve()
    catalog_root = (catalog_root or source_root()).resolve()
    usage_by_source = _usages(project, catalog_root)
    resources: list[ModuleResource] = []

    for path in sorted((project / "parts").glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = _load_file(path)
        definition = _definition(module, {})
        usages = usage_by_source.get(path.resolve(), [])
        supplied_sets = [dict(usage["params"]) for usage in usages] or [{}]
        parameter_sets = _unique_parameter_sets(
            [effective_params(path, supplied) for supplied in supplied_sets]
        )
        resources.append(
            ModuleResource(
                definition.id,
                path.resolve(),
                "project",
                parameter_sets[0],
                parameter_sets,
                usages,
            )
        )

    manifest = load_yaml(catalog_root / "library" / "manifest.yaml") or {}
    catalog = manifest.get("modules", [])
    if not isinstance(catalog, list):
        raise ValueError("library/manifest.yaml 的 modules 必須是清單")
    by_source = {(catalog_root / entry["file"]).resolve(): entry for entry in catalog}
    for path, usages in usage_by_source.items():
        entry = by_source.get(path.resolve())
        if entry is None:
            continue
        params = effective_params(path)
        resources.append(
            ModuleResource(
                str(entry["id"]),
                path.resolve(),
                "library",
                params,
                [params],
                usages,
                entry,
            )
        )

    resources.sort(key=lambda resource: (resource.source_kind, resource.id))
    ids = [resource.id for resource in resources]
    duplicates = sorted({module_id for module_id in ids if ids.count(module_id) > 1})
    if duplicates:
        raise ValueError(f"案內模組 id 與引用的庫模組重複：{', '.join(duplicates)}")
    return resources


def resolve_project_module(
    project: Path,
    module_id: str,
    catalog_root: Path | None = None,
) -> ModuleResource:
    catalog_root = (catalog_root or source_root()).resolve()
    for resource in project_modules(project, catalog_root):
        if resource.id == module_id or resource.source.stem == Path(module_id).stem:
            return resource

    # The project list intentionally contains only referenced library modules.  The
    # module browser still needs to open an unused manifest entry, so resolve it here
    # without changing that compact list response.
    manifest = load_yaml(catalog_root / "library" / "manifest.yaml") or {}
    usage_by_source = _usages(project.resolve(), catalog_root)
    for entry in manifest.get("modules", []):
        source = (catalog_root / str(entry.get("file", ""))).resolve()
        if str(entry.get("id")) != module_id and source.stem != Path(module_id).stem:
            continue
        params = effective_params(source)
        return ModuleResource(
            str(entry["id"]),
            source,
            "library",
            params,
            [params],
            usage_by_source.get(source, []),
            entry,
        )
    raise KeyError(f"找不到案內可用模組：{module_id}")


def module_summary(resource: ModuleResource, cache_root: Path) -> dict[str, Any]:
    module = _load_file(resource.source)
    definition = _definition(module, resource.params)
    return {
        "id": resource.id,
        "source": resource.source_kind,
        "file": str(resource.source),
        "category": (resource.catalog or {}).get("category", "project"),
        "summary": (resource.catalog or {}).get("summary", "本案自建參數化模組"),
        "placeholder": definition.meta.placeholder,
        "params": resource.params,
        "parameter_sets": resource.parameter_sets,
        "usages": resource.usages,
        "check": cached_check_status(
            resource.source,
            resource.params,
            cache_root=cache_root,
        ),
    }


def module_detail(resource: ModuleResource) -> dict[str, Any]:
    module = _load_file(resource.source)
    definition = _definition(module, resource.params)
    definition_json = definition.model_dump(mode="json")
    return {
        "id": definition.id,
        "source": resource.source_kind,
        "file": str(resource.source),
        "module_def": definition_json,
        "params": resource.params,
        "parameter_sets": resource.parameter_sets,
        "params_schema": definition.params_schema,
        "frames": {
            name: frame.model_dump(mode="json") for name, frame in definition.frames.items()
        },
        "axes": [axis.model_dump(mode="json") for axis in definition.axes],
        "meta": definition.meta.model_dump(mode="json"),
        "usages": resource.usages,
    }


def promotion_check(
    project: Path,
    module_id: str,
    *,
    cache_root: Path | None = None,
) -> tuple[Path, Any]:
    source = (project.resolve() / "parts" / f"{Path(module_id).stem}.py").resolve()
    if source.parent != (project.resolve() / "parts").resolve() or not source.is_file():
        raise ValueError(f"找不到案內模組：{module_id}")
    checked = cached_check(source, cache_root=cache_root)
    failures = [item for item in checked.result.items if item.severity == "fail"]
    if failures:
        indices = "、".join(item.index for item in failures)
        raise ValueError(f"模組 {module_id} 仍有失敗項目（{indices}），不可收進模組庫")
    return source, checked.result


def promote_part(
    project: Path,
    module_id: str,
    *,
    catalog_root: Path | None = None,
    cache_root: Path | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    project = project.resolve()
    catalog_root = (catalog_root or source_root()).resolve()
    source, _result = promotion_check(project, module_id, cache_root=cache_root)
    module = _load_file(source)
    definition = _definition(module, effective_params(source))
    selected_category = category or getattr(module, "CATEGORY", None)
    if selected_category is None:
        selected_category = getattr(definition.meta, "category", None)
    selected_category = str(selected_category or PROMOTION_FALLBACK_CATEGORY)
    if selected_category not in CATEGORIES:
        raise ValueError(f"模組 category 不在規格列舉內：{selected_category}")

    manifest_path = catalog_root / "library" / "manifest.yaml"
    manifest = load_yaml(manifest_path) or {"modules": []}
    entries = manifest.get("modules", [])
    if any(str(entry.get("id")) == definition.id for entry in entries):
        raise ValueError(f"模組庫已有同 id 模組：{definition.id}")
    target = (catalog_root / "library" / f"{definition.id}.py").resolve()
    if target.exists():
        raise ValueError(f"模組庫檔案已存在：{target.name}")

    structural = derive_module_fields(source, f"library/{target.name}")
    summary = (module.__doc__ or "本案自建參數化模組").strip().splitlines()[0]
    entry = {
        **structural,
        "tier": "P",
        "category": selected_category,
        "summary": summary,
        "status": "production",
        "from_project": project.name,
    }
    original_manifest = manifest_path.read_text(encoding="utf-8")
    cell_path = project / "cell.yaml"
    original_cell = cell_path.read_text(encoding="utf-8") if cell_path.is_file() else None
    cell = load_yaml(cell_path) if cell_path.is_file() else None
    cell_changed = False
    if isinstance(cell, dict):
        for machine in cell.get("machines", []):
            for instance in machine.get("modules", []):
                part = instance.get("part")
                if not part:
                    continue
                if _source_for_part(project, catalog_root, str(part)) == source:
                    instance["part"] = f"library/{target.name}"
                    cell_changed = True
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    entries.append(entry)
    manifest["modules"] = entries
    try:
        dump_yaml(manifest_path, manifest)
        if cell_changed:
            dump_yaml(cell_path, cell)
        source.unlink()
    except Exception:
        target.unlink(missing_ok=True)
        manifest_path.write_text(original_manifest, encoding="utf-8")
        if original_cell is not None:
            cell_path.write_text(original_cell, encoding="utf-8")
        raise
    return entry
