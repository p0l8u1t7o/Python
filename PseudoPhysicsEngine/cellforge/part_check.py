"""Standalone quality checks for parametric CadQuery modules."""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import cadquery as cq
from jsonschema import Draft202012Validator, SchemaError

from cellforge.build.glb import _collision_mesh, _shape_mesh
from cellforge.schema import ModuleDef

Severity = Literal["fail", "warn", "info"]

BASIS_MIN_LENGTH = 10
BASIS_TEMPLATE_TEXT = "TODO：填寫尺寸依據"
FRAME_BOUNDS_TOLERANCE_MM = 5.0
FRAME_SURFACE_WARNING_MM = 20.0
PARAM_BOUNDS_COVERAGE = 0.8
MOUNT_SECONDARY_VOLUME_RATIO = 0.2
MOUNT_SECONDARY_PART_MINIMUM = 2
MOUNT_FEATURE_FACE_LIMIT = 6
COLOR_COVERAGE_MINIMUM = 0.8
# D-021 records the nine-module calibration behind these acceptance thresholds.
COLLISION_WARN_RATIO = 3.0
COLLISION_FAIL_RATIO = 6.0
TRIANGLE_WARN_COUNT = 50_000
TRIANGLE_FAIL_COUNT = 150_000
AXIS_SPEED_LIMITS = {
    "prismatic": (1.0, 2000.0, "mm/s"),
    "revolute": (1.0, 720.0, "deg/s"),
}
GENERIC_PART_NAME = re.compile(r"^(solid|part|object|shape|compound)_?\d*$", re.IGNORECASE)


@dataclass(slots=True)
class PartCheckItem:
    index: str
    severity: Severity
    code: str
    message: str
    values: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PartCheckResult:
    module_id: str
    passed: bool
    items: list[PartCheckItem]
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "passed": self.passed,
            "items": [item.as_dict() for item in self.items],
            "source": self.source,
        }


@dataclass(slots=True)
class _Part:
    name: str
    shape: cq.Shape
    color: cq.Color | None
    link: str


def _shape(value: Any) -> cq.Shape | None:
    if isinstance(value, cq.Workplane):
        candidate = value.val()
        return candidate if isinstance(candidate, cq.Shape) else None
    return value if isinstance(value, cq.Shape) else None


def _parts(assembly: cq.Assembly) -> list[_Part]:
    output: list[_Part] = []
    for key, child in assembly.objects.items():
        if key == assembly.name or child.obj is None:
            continue
        shape = _shape(child.obj)
        if shape is None:
            continue
        name = str(child.name or key).rsplit("/", 1)[-1]
        metadata = child.metadata or {}
        output.append(
            _Part(
                name=name,
                shape=shape.located(child.loc),
                color=child.color,
                link=str(metadata.get("link") or name),
            )
        )
    return output


def _default_params(definition: ModuleDef) -> dict[str, Any]:
    properties = definition.params_schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {
        name: schema["default"]
        for name, schema in properties.items()
        if isinstance(schema, dict) and "default" in schema
    }


def _definition(module: ModuleType, params: dict[str, Any]) -> ModuleDef:
    static = getattr(module, "MODULE", None)
    if not isinstance(static, ModuleDef):
        raise ValueError("模組必須匯出 ModuleDef 型別的 MODULE")
    factory = getattr(module, "module_definition", None)
    dynamic = factory(dict(params)) if callable(factory) else static
    if not isinstance(dynamic, ModuleDef):
        raise ValueError("module_definition() 必須回傳 ModuleDef")
    return dynamic


def _built(module: ModuleType, params: dict[str, Any]) -> cq.Assembly:
    builder = getattr(module, "build", None)
    if not callable(builder):
        raise ValueError("模組必須匯出 build(params)")
    assembly = builder(dict(params))
    if not isinstance(assembly, cq.Assembly):
        raise ValueError("build() 必須回傳 cq.Assembly")
    return assembly


def _item(
    index: str,
    severity: Severity,
    code: str,
    message: str,
    **values: Any,
) -> PartCheckItem:
    return PartCheckItem(index, severity, code, message, values)


def _check_basis(definition: ModuleDef) -> list[PartCheckItem]:
    basis = definition.meta.basis.strip()
    if len(basis) >= BASIS_MIN_LENGTH and basis != BASIS_TEMPLATE_TEXT:
        return []
    return [
        _item(
            "6.1",
            "fail",
            "basis_missing",
            f"模組 {definition.id} 未填寫尺寸依據（meta.basis）。"
            "請說明尺寸來自型錄、實測、工程圖或工程推估。",
            length=len(basis),
            minimum_length=BASIS_MIN_LENGTH,
        )
    ]


def _check_mounting_interface(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    volumes = sorted(
        (
            (
                part.name,
                float(part.shape.BoundingBox().xlen)
                * float(part.shape.BoundingBox().ylen)
                * float(part.shape.BoundingBox().zlen),
            )
            for part in parts
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    largest = volumes[0][1] if volumes else 0.0
    secondary = [
        name
        for name, volume in volumes[1:]
        if largest > 0 and volume < largest * MOUNT_SECONDARY_VOLUME_RATIO
    ]
    face_counts = {part.name: len(part.shape.Faces()) for part in parts}
    featured = [name for name, count in face_counts.items() if count > MOUNT_FEATURE_FACE_LIMIT]
    if len(secondary) >= MOUNT_SECONDARY_PART_MINIMUM or featured:
        return []
    return [
        _item(
            "6.2",
            "warn",
            "mounting_interface_missing",
            f"模組 {definition.id} 看起來是單純箱體（次要子零件 {len(secondary)} 個、"
            "無孔槽特徵）。請補上安裝介面——底板與螺孔位、鋁擠 T 槽、法蘭面或支撐腳。",
            secondary_part_count=len(secondary),
            secondary_parts=secondary,
            secondary_volume_ratio=MOUNT_SECONDARY_VOLUME_RATIO,
            minimum_secondary_parts=MOUNT_SECONDARY_PART_MINIMUM,
            face_counts=face_counts,
            feature_face_limit=MOUNT_FEATURE_FACE_LIMIT,
        )
    ]


def _check_names(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    names = [part.name.strip() for part in parts]
    invalid = sorted(
        name for name in names if len(name) < 2 or GENERIC_PART_NAME.fullmatch(name) is not None
    )
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if names and not invalid and not duplicates:
        return []
    details = []
    if not names:
        details.append("沒有可辨識的子零件")
    if invalid:
        details.append(f"無意義名稱：{', '.join(invalid)}")
    if duplicates:
        details.append(f"重複名稱：{', '.join(duplicates)}")
    return [
        _item(
            "6.3",
            "fail",
            "part_names_invalid",
            f"模組 {definition.id} 的具名子零件不合格（{'；'.join(details)}）。"
            "請使用能表達功能或方位的唯一名稱。",
            names=names,
            invalid=invalid,
            duplicates=duplicates,
        )
    ]


def _bounds(parts: list[_Part]) -> tuple[float, float, float, float, float, float] | None:
    if not parts:
        return None
    boxes = [part.shape.BoundingBox() for part in parts]
    return (
        min(box.xmin for box in boxes),
        max(box.xmax for box in boxes),
        min(box.ymin for box in boxes),
        max(box.ymax for box in boxes),
        min(box.zmin for box in boxes),
        max(box.zmax for box in boxes),
    )


def _check_frames(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    failures: list[str] = []
    warnings: list[str] = []
    values: dict[str, Any] = {}
    if "mount" not in definition.frames:
        failures.append("缺少 mount frame")
    valid_links = {"base", *(part.name for part in parts), *(part.link for part in parts)}
    bounds = _bounds(parts)
    distances: dict[str, float] = {}
    outside: list[str] = []
    bad_links: list[str] = []
    for name, frame in definition.frames.items():
        if frame.link and frame.link not in valid_links:
            bad_links.append(f"{name}→{frame.link}")
        if bounds is None:
            continue
        x, y, z = frame.xyz
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        if not (
            xmin - FRAME_BOUNDS_TOLERANCE_MM <= x <= xmax + FRAME_BOUNDS_TOLERANCE_MM
            and ymin - FRAME_BOUNDS_TOLERANCE_MM <= y <= ymax + FRAME_BOUNDS_TOLERANCE_MM
            and zmin - FRAME_BOUNDS_TOLERANCE_MM <= z <= zmax + FRAME_BOUNDS_TOLERANCE_MM
        ):
            outside.append(name)
            continue
        point = cq.Vertex.makeVertex(x, y, z)
        distance = min(part.shape.distance(point) for part in parts)
        distances[name] = float(distance)
        if distance > FRAME_SURFACE_WARNING_MM and not frame.free_space:
            warnings.append(f"{name} 距最近實體表面 {distance:.1f} mm")
    if bad_links:
        failures.append(f"frame 指向不存在的子零件：{', '.join(bad_links)}")
    if outside:
        failures.append(f"frame 位於整體包圍盒外：{', '.join(outside)}")
    values.update(
        bounds_mm=list(bounds) if bounds is not None else None,
        surface_distance_mm=distances,
        bounds_tolerance_mm=FRAME_BOUNDS_TOLERANCE_MM,
        surface_warning_mm=FRAME_SURFACE_WARNING_MM,
    )
    items: list[PartCheckItem] = []
    if failures:
        items.append(
            _item(
                "6.4",
                "fail",
                "frames_invalid",
                f"模組 {definition.id} 的 frames 不合格（{'；'.join(failures)}）。",
                **values,
            )
        )
    elif warnings:
        items.append(
            _item(
                "6.4",
                "warn",
                "frames_far_from_surface",
                f"模組 {definition.id} 的 frame 可能離開機構表面"
                f"（{'；'.join(warnings)}）。光學中心或抓取點可保留此警告供目視確認。",
                **values,
            )
        )
    return items


def _check_axes(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    problems: list[str] = []
    link_parts: dict[str, int] = {}
    for part in parts:
        link_parts[part.link] = link_parts.get(part.link, 0) + 1
        link_parts[part.name] = link_parts.get(part.name, 0) + 1
    available = {"base", *link_parts}
    for axis in definition.axes:
        limits = axis.range_deg if axis.type == "revolute" else axis.range_mm
        if limits is None or math.isclose(float(limits[0]), float(limits[1])):
            problems.append(f"{axis.id} 的 range 不得為零")
        speed = axis.max_speed_dps if axis.type == "revolute" else axis.max_speed_mm_s
        low, high, unit = AXIS_SPEED_LIMITS[axis.type]
        if speed is None or not low <= speed <= high:
            problems.append(f"{axis.id} 的 max_speed 必須在 {low:g}～{high:g} {unit}")
        if sum(float(value) ** 2 for value in axis.axis) <= 1e-24:
            problems.append(f"{axis.id} 的 axis 不得為零向量")
        child = axis.child or axis.id
        if axis.parent not in available:
            problems.append(f"{axis.id} 的 parent {axis.parent} 不存在")
        if child not in available:
            problems.append(f"{axis.id} 的 child {child} 沒有對應子零件")
        elif link_parts.get(child, 0) == 0:
            problems.append(f"{axis.id} 的 child {child} 沒有幾何")
    if not problems:
        return []
    return [
        _item(
            "6.5",
            "fail",
            "axes_invalid",
            f"模組 {definition.id} 的 axes 不合格（{'；'.join(problems)}）。",
            problems=problems,
        )
    ]


def _check_collision(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    try:
        visual_volume, collision_volume, ratio = _collision_measurement(definition, parts)
    except Exception as error:  # noqa: BLE001 - geometry errors must become a finding
        return [
            _item(
                "6.6",
                "fail",
                "collision_generation_failed",
                f"模組 {definition.id} 無法產生碰撞幾何：{error}",
                collision_mode=definition.collision,
                error=str(error),
            )
        ]
    if ratio <= COLLISION_WARN_RATIO:
        return []
    severity: Severity = "fail" if ratio > COLLISION_FAIL_RATIO else "warn"
    return [
        _item(
            "6.6",
            severity,
            "collision_inflation",
            f"模組 {definition.id} 的碰撞體體積是實體的 {ratio:.2f} 倍，"
            "可能整包住鏤空區，會讓干涉檢查誤報。請對各桿件分別產生碰撞體。",
            collision_mode=definition.collision,
            visual_volume_mm3=visual_volume,
            collision_volume_mm3=collision_volume,
            inflation_ratio=ratio,
            warning_threshold=COLLISION_WARN_RATIO,
            failure_threshold=COLLISION_FAIL_RATIO,
        )
    ]


def _collision_measurement(definition: ModuleDef, parts: list[_Part]) -> tuple[float, float, float]:
    if not parts:
        raise ValueError("沒有可建立碰撞體的 visual 實體")
    visual_volume = sum(abs(float(part.shape.Volume())) for part in parts)
    if not math.isfinite(visual_volume) or visual_volume <= 0:
        raise ValueError("visual 實體總體積必須大於零")
    collision_volume = 0.0
    for part in parts:
        visual = _shape_mesh(part.shape)
        if not len(visual.vertices) or not len(visual.faces):
            raise ValueError(f"子零件 {part.name} 無法三角化")
        collision = _collision_mesh(visual, definition.collision)
        volume = abs(float(collision.volume))
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError(f"子零件 {part.name} 的碰撞體體積無效")
        collision_volume += volume
    return visual_volume, collision_volume, collision_volume / visual_volume


def _check_colors(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    colored = [part.name for part in parts if part.color is not None]
    coverage = len(colored) / len(parts) if parts else 0.0
    if coverage >= COLOR_COVERAGE_MINIMUM:
        return []
    return [
        _item(
            "6.7",
            "warn",
            "colors_incomplete",
            f"模組 {definition.id} 只有 {len(colored)}/{len(parts)} 個子零件明確指定 cq.Color"
            f"（{coverage:.0%}），低於 {COLOR_COVERAGE_MINIMUM:.0%}。請依工程慣例補齊配色。",
            colored_part_count=len(colored),
            total_part_count=len(parts),
            coverage=coverage,
            required=COLOR_COVERAGE_MINIMUM,
        )
    ]


def _numeric_bounds(schema: dict[str, Any]) -> tuple[Any, Any] | None:
    if schema.get("type") not in {"number", "integer"}:
        return None
    lower = schema.get("minimum", schema.get("exclusiveMinimum"))
    upper = schema.get("maximum", schema.get("exclusiveMaximum"))
    if lower is None or upper is None:
        return None
    if "exclusiveMinimum" in schema:
        lower = (
            int(lower) + 1 if schema.get("type") == "integer" else math.nextafter(lower, math.inf)
        )
    if "exclusiveMaximum" in schema:
        upper = (
            int(upper) - 1 if schema.get("type") == "integer" else math.nextafter(upper, -math.inf)
        )
    return lower, upper


def _numeric_parameter(schema: dict[str, Any]) -> bool:
    if schema.get("type") in {"number", "integer"}:
        return True
    if schema.get("type") == "array":
        item = schema.get("items")
        return isinstance(item, dict) and item.get("type") in {"number", "integer"}
    return False


def _parameter_extremes(schema: dict[str, Any], default: Any) -> tuple[Any, Any] | None:
    direct = _numeric_bounds(schema)
    if direct is not None:
        return direct
    if schema.get("type") != "array" or not isinstance(default, (list, tuple)):
        return None
    item = schema.get("items")
    if not isinstance(item, dict):
        return None
    bounds = _numeric_bounds(item)
    if bounds is None:
        return None
    return [bounds[0]] * len(default), [bounds[1]] * len(default)


def _check_params(
    module: ModuleType, definition: ModuleDef, defaults: dict[str, Any]
) -> list[PartCheckItem]:
    schema = definition.params_schema or {"type": "object"}
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [
            _item(
                "6.8",
                "fail",
                "params_schema_invalid",
                f"模組 {definition.id} 的 params_schema 不是有效的 JSON Schema：{error.message}",
                schema_path=list(error.schema_path),
            )
        ]

    failures: list[str] = []
    properties = schema.get("properties", {})
    numeric: list[str] = []
    bounded: list[str] = []
    if isinstance(properties, dict):
        for name, parameter_schema in properties.items():
            if not isinstance(parameter_schema, dict) or not _numeric_parameter(parameter_schema):
                continue
            numeric.append(name)
            extremes = _parameter_extremes(parameter_schema, defaults.get(name))
            if extremes is None:
                continue
            bounded.append(name)
            for end, value in zip(("minimum", "maximum"), extremes, strict=True):
                params = {**defaults, name: value}
                try:
                    _built(module, params)
                except Exception as error:  # noqa: BLE001 - module boundary must become a finding
                    failures.append(f"{name} 的 {end} 建置失敗：{error}")
    if failures:
        return [
            _item(
                "6.8",
                "fail",
                "parameter_extreme_build_failed",
                f"模組 {definition.id} 的極端參數無法建置（{'；'.join(failures)}）。",
                numeric_parameters=numeric,
                bounded_parameters=bounded,
            )
        ]
    coverage = len(bounded) / len(numeric) if numeric else 1.0
    if coverage < PARAM_BOUNDS_COVERAGE:
        return [
            _item(
                "6.8",
                "warn",
                "parameter_bounds_incomplete",
                f"模組 {definition.id} 的數值參數上下限覆蓋率為 {coverage:.0%}，"
                f"低於 {PARAM_BOUNDS_COVERAGE:.0%}。",
                numeric_parameters=numeric,
                bounded_parameters=bounded,
                coverage=coverage,
                required=PARAM_BOUNDS_COVERAGE,
            )
        ]
    return []


def _check_triangles(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    try:
        total, contributions = _triangle_measurement(parts)
    except Exception as error:  # noqa: BLE001 - tessellation errors must become a finding
        return [
            _item(
                "6.9",
                "fail",
                "tessellation_failed",
                f"模組 {definition.id} 無法計算三角形數：{error}",
                error=str(error),
            )
        ]
    if total <= TRIANGLE_WARN_COUNT:
        return []
    severity: Severity = "fail" if total > TRIANGLE_FAIL_COUNT else "warn"
    leaders = contributions[:3]
    leader_text = "、".join(f"{name} {count:,}" for name, count in leaders)
    return [
        _item(
            "6.9",
            severity,
            "triangle_budget_exceeded",
            f"模組 {definition.id} 的 visual 網格共有 {total:,} 個三角形；"
            f"最高的三個子零件為 {leader_text}。",
            triangle_count=total,
            top_sub_parts=[{"name": name, "triangle_count": count} for name, count in leaders],
            warning_threshold=TRIANGLE_WARN_COUNT,
            failure_threshold=TRIANGLE_FAIL_COUNT,
        )
    ]


def _triangle_measurement(parts: list[_Part]) -> tuple[int, list[tuple[str, int]]]:
    contributions = [(part.name, len(_shape_mesh(part.shape).faces)) for part in parts]
    contributions.sort(key=lambda item: (-item[1], item[0]))
    return sum(count for _name, count in contributions), contributions


def _check_lowest_z(definition: ModuleDef, parts: list[_Part]) -> list[PartCheckItem]:
    bounds = _bounds(parts)
    lowest = bounds[4] if bounds is not None else None
    text = "沒有可計算的實體" if lowest is None else f"包圍盒最低點 z={lowest:.1f} mm"
    return [
        _item(
            "6.10",
            "info",
            "lowest_z",
            f"模組 {definition.id} {text}；是否落地由 cell validate 依 mount 宣告判定。",
            lowest_z_mm=lowest,
        )
    ]


def check_module(
    module: ModuleType,
    source: str = "",
    *,
    params: dict[str, Any] | None = None,
) -> PartCheckResult:
    """Build one module with effective parameters and evaluate all quality items."""

    module_id = getattr(getattr(module, "MODULE", None), "id", Path(source).stem or "unknown")
    try:
        static = _definition(module, {})
        defaults = _default_params(static)
        effective = {**defaults, **(params or {})}
        definition = _definition(module, effective)
        assembly = _built(module, effective)
        parts = _parts(assembly)
    except Exception as error:  # noqa: BLE001 - imported module errors are user-facing findings
        item = _item(
            "6.8",
            "fail",
            "default_build_failed",
            f"模組 {module_id} 以預設參數建置失敗：{error}",
            error=str(error),
        )
        return PartCheckResult(module_id, False, [item], source)

    # A declared placeholder is intentionally a simple envelope, so item 6.2's
    # mounting-detail proxy is not meaningful. Items 6.1 and 6.3–6.10 remain
    # unchanged: placeholders still need provenance, valid structure and safe geometry.
    mounting_items = (
        [] if definition.meta.placeholder else _check_mounting_interface(definition, parts)
    )
    items = [
        *_check_basis(definition),
        *mounting_items,
        *_check_names(definition, parts),
        *_check_frames(definition, parts),
        *_check_axes(definition, parts),
        *_check_collision(definition, parts),
        *_check_colors(definition, parts),
        *_check_params(module, definition, effective),
        *_check_triangles(definition, parts),
        *_check_lowest_z(definition, parts),
    ]
    return PartCheckResult(
        definition.id,
        not any(item.severity == "fail" for item in items),
        items,
        source,
    )


def _load_file(path: Path) -> ModuleType:
    module_name = f"_cellforge_part_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"無法載入模組檔：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_part_files(project_dir: Path) -> dict[str, Path]:
    """Return library parts overlaid by project-local parts with the same file stem."""

    library_dir = Path(__file__).resolve().parents[1] / "library"
    files = {
        path.stem: path for path in sorted(library_dir.glob("*.py")) if path.name != "__init__.py"
    }
    project_parts = project_dir / "parts"
    if project_parts.is_dir():
        files.update(
            {
                path.stem: path
                for path in sorted(project_parts.glob("*.py"))
                if path.name != "__init__.py"
            }
        )
    return files


def _project_params_for_source(project_dir: Path, source: Path) -> dict[str, Any] | None:
    parts_dir = (project_dir / "parts").resolve()
    source = source.resolve()
    if source.parent != parts_dir:
        return None
    cell_path = project_dir / "cell.yaml"
    if not cell_path.is_file():
        return None
    from cellforge.yamlio import load_yaml

    payload = load_yaml(cell_path) or {}
    for machine in payload.get("machines", []):
        for instance in machine.get("modules", []):
            part = instance.get("part")
            if part and Path(str(part)).stem == source.stem:
                return dict(instance.get("params") or {})
    return None


def check_parts(
    project_dir: Path,
    module_id: str | None = None,
    *,
    cache_root: Path | None = None,
) -> list[PartCheckResult]:
    from cellforge.module_cache import cached_check

    files = discover_part_files(project_dir)
    if module_id is not None:
        path = files.get(Path(module_id).stem)
        if path is None:
            raise ValueError(f"找不到模組：{module_id}")
        selected = [path]
    else:
        selected = list(files.values())
    return [
        cached_check(
            path,
            _project_params_for_source(project_dir, path),
            cache_root=cache_root,
        ).result
        for path in selected
    ]


def check_project_parts(
    project_dir: Path, *, cache_root: Path | None = None
) -> list[PartCheckResult]:
    from cellforge.module_cache import cached_check

    parts_dir = project_dir / "parts"
    if not parts_dir.is_dir():
        return []
    paths = [path for path in sorted(parts_dir.glob("*.py")) if path.name != "__init__.py"]
    return [
        cached_check(
            path,
            _project_params_for_source(project_dir, path),
            cache_root=cache_root,
        ).result
        for path in paths
    ]
