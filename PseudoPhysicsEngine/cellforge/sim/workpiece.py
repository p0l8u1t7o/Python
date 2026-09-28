"""Workpiece and part geometry, face frames, articulated hinged covers, and part state axes.

單一工件案例只有一個 id 為 ``workpiece`` 的零件；多零件產品（``workpiece.yaml`` 的 ``parts``）
每個零件各自有外形、frame、狀態軸、質量與初始位置，持有關係由模擬引擎追蹤。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq
import numpy as np
from scipy.spatial.transform import Rotation

from cellforge.schema import Frame, ModuleAxis, ModuleDef
from cellforge.schema.models import Cover, PartInstance, PartPlacement, Process, Sku, Workpiece

PRIMARY_PART = "workpiece"


@dataclass(slots=True)
class BuiltWorkpiece:
    """One product part instance (the legacy single workpiece is id ``workpiece``)."""

    sku: Sku | None
    assembly: cq.Assembly | None
    definition: ModuleDef
    warnings: list[str] = field(default_factory=list)
    id: str = PRIMARY_PART
    mass_kg: float = 0.0
    initial: PartPlacement | None = None
    state: dict[str, float] = field(default_factory=dict)
    # 零件模組路徑（SKU 方塊零件為空字串）與外形高度（翻面旋轉中心用）。
    part_file: str = ""
    height_mm: float = 0.0
    trust: str | None = None
    # 零件模組的參數（例如壓合後的回彈角），供狀態模型使用。
    params: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FaceBasis:
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    n: np.ndarray
    width: float
    height: float

    @property
    def rotation(self) -> np.ndarray:
        return np.column_stack((self.u, self.v, self.n))


def _face_basis(sku: Sku, face: str) -> FaceBasis:
    x, y, z = sku.size.x, sku.size.y, sku.size.z
    data = {
        "front": ((-x / 2, -y / 2, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0), x, z),
        "rear": ((x / 2, y / 2, 0), (-1, 0, 0), (0, 0, 1), (0, 1, 0), x, z),
        "left": ((-x / 2, y / 2, 0), (0, -1, 0), (0, 0, 1), (-1, 0, 0), y, z),
        "right": ((x / 2, -y / 2, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0), y, z),
        "top": ((-x / 2, -y / 2, z), (1, 0, 0), (0, 1, 0), (0, 0, 1), x, y),
        "bottom": ((-x / 2, y / 2, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1), x, y),
    }
    origin, u, v, n, width, height = data[face]
    return FaceBasis(
        np.asarray(origin, dtype=float),
        np.asarray(u, dtype=float),
        np.asarray(v, dtype=float),
        np.asarray(n, dtype=float),
        width,
        height,
    )


def _frame(position: np.ndarray, rotation: np.ndarray) -> Frame:
    rpy = Rotation.from_matrix(rotation).as_euler("xyz", degrees=True)
    return Frame(
        xyz=tuple(float(value) for value in position),
        rpy_deg=tuple(float(value) for value in rpy),
    )


def _fit_rect(
    cover_id: str,
    u: float,
    v: float,
    width: float,
    height: float,
    face: FaceBasis,
    warnings: list[str],
) -> tuple[float, float, float, float]:
    fitted_width = min(max(width, 0.1), face.width)
    fitted_height = min(max(height, 0.1), face.height)
    fitted_u = min(max(u, 0.0), face.width - fitted_width)
    fitted_v = min(max(v, 0.0), face.height - fitted_height)
    fitted = (fitted_u, fitted_v, fitted_width, fitted_height)
    original = (u, v, width, height)
    if not np.allclose(fitted, original):
        warnings.append(f"護蓋 {cover_id} 的 rect 超出工件表面，已夾回有效範圍")
    return fitted


def _cover_data(
    cover: Cover, sku: Sku, warnings: list[str]
) -> tuple[FaceBasis, np.ndarray, np.ndarray, np.ndarray, float, float, np.ndarray]:
    face = _face_basis(sku, cover.face)
    u, v, width, height = _fit_rect(
        cover.id,
        cover.rect.u,
        cover.rect.v,
        cover.rect.w,
        cover.rect.h,
        face,
        warnings,
    )
    edge = str(cover.hinge.get("edge", "bottom"))
    if edge == "bottom":
        direction, pivot_uv, free_uv = face.v, (u + width / 2, v), (u + width / 2, v + height)
    elif edge == "top":
        direction, pivot_uv, free_uv = -face.v, (u + width / 2, v + height), (u + width / 2, v)
    elif edge == "left":
        direction, pivot_uv, free_uv = face.u, (u, v + height / 2), (u + width, v + height / 2)
    elif edge == "right":
        direction, pivot_uv, free_uv = -face.u, (u + width, v + height / 2), (u, v + height / 2)
    else:
        raise ValueError(f"護蓋 {cover.id} 的 hinge.edge 不支援：{edge}")
    center = face.origin + face.u * (u + width / 2) + face.v * (v + height / 2) + face.n
    pivot = face.origin + face.u * pivot_uv[0] + face.v * pivot_uv[1] + face.n * 2.0
    free = face.origin + face.u * free_uv[0] + face.v * free_uv[1] + face.n * 2.0
    axis = np.cross(direction, face.n)
    axis /= np.linalg.norm(axis)
    return face, center, pivot, free, width, height, axis


def _choose_sku(workpiece: Workpiece, process: Process | None) -> Sku:
    requested = process.workpiece_sku if process else None
    if requested:
        for sku in workpiece.skus:
            if sku.id == requested:
                return sku
        raise ValueError(f"process.yaml 指定不存在的 workpiece_sku：{requested}")
    if not workpiece.skus:
        raise ValueError("workpiece.yaml 至少需要一個 SKU")
    return workpiece.skus[0]


def build_workpiece(
    workpiece: Workpiece, process: Process | None = None, *, build_geometry: bool = True
) -> BuiltWorkpiece:
    """Legacy single workpiece: the process-selected SKU as part ``workpiece``."""

    sku = _choose_sku(workpiece, process)
    built = _sku_part(sku, PRIMARY_PART, build_geometry=build_geometry)
    if process is not None and process.initial_workpiece_frame:
        built.initial = PartPlacement(frame=process.initial_workpiece_frame)
    return built


def build_parts(
    workpiece: Workpiece, process: Process | None = None, *, build_geometry: bool = True
) -> list[BuiltWorkpiece]:
    """All part instances of the product; without ``parts`` this is the legacy workpiece."""

    if not workpiece.parts:
        return [build_workpiece(workpiece, process, build_geometry=build_geometry)]
    skus = {sku.id: sku for sku in workpiece.skus}
    built = []
    for part in workpiece.parts:
        if part.sku is not None:
            item = _sku_part(skus[part.sku], part.id, build_geometry=build_geometry)
            item.mass_kg = float(part.mass_kg if part.mass_kg is not None else item.mass_kg)
        else:
            item = _module_part(part, build_geometry=build_geometry)
        item.initial = part.initial
        item.state = dict(part.state)
        item.trust = part.trust or item.trust
        unknown = sorted(set(part.state) - {axis.id for axis in item.definition.axes})
        if unknown:
            raise ValueError(f"零件 {part.id} 的 state 引用不存在的狀態軸：{', '.join(unknown)}")
        built.append(item)
    return built


def _module_part(part: PartInstance, *, build_geometry: bool) -> BuiltWorkpiece:
    from cellforge.build.modules import load_part, validate_params

    assert part.part is not None
    module = load_part(part.part)
    definition = getattr(module, "MODULE", None)
    builder = getattr(module, "build", None)
    if not isinstance(definition, ModuleDef) or not callable(builder):
        raise ValueError(f"零件 {part.id} 的模組 {part.part} 必須匯出 MODULE 與 build(params)")
    params = dict(part.params)
    validate_params(definition, params)
    dynamic = getattr(module, "module_definition", lambda _params: definition)(params)
    assembly = None
    height = 0.0
    if build_geometry:
        assembly = builder(dict(params))
        if not isinstance(assembly, cq.Assembly):
            raise ValueError(f"零件 {part.id} 的 {part.part}.build() 必須回傳 cq.Assembly")
        assembly.name = part.id
        bounds = assembly.toCompound().BoundingBox()
        height = float(bounds.zmax - bounds.zmin)
    warnings = []
    mass = part.mass_kg
    if mass is None:
        mass = 0.0
        warnings.append(f"零件 {part.id} 沒有 mass_kg，負載檢查以 0 kg 計；請補上質量")
    return BuiltWorkpiece(
        sku=None,
        assembly=assembly,
        definition=dynamic.model_copy(update={"id": part.id}),
        warnings=warnings,
        id=part.id,
        mass_kg=float(mass),
        part_file=part.part.replace("\\", "/"),
        height_mm=height,
        params=params,
    )


def _sku_part(sku: Sku, part_id: str, *, build_geometry: bool) -> BuiltWorkpiece:
    assembly = cq.Assembly(name=part_id) if build_geometry else None
    if assembly is not None:
        assembly.add(
            cq.Workplane("XY")
            .box(sku.size.x, sku.size.y, sku.size.z)
            .translate((0, 0, sku.size.z / 2)),
            name="body",
            color=cq.Color(0.16, 0.18, 0.2),
        )
    warnings: list[str] = []
    frames: dict[str, Frame] = {"workpiece": Frame()}
    axes: list[ModuleAxis] = []
    for face_name in ("front", "rear", "left", "right", "top", "bottom"):
        face = _face_basis(sku, face_name)
        center = face.origin + face.u * face.width / 2 + face.v * face.height / 2
        frames[face_name] = _frame(center, face.rotation)
    for cover in sku.covers:
        face, center, pivot, free, width, height, axis = _cover_data(cover, sku, warnings)
        rpy = Rotation.from_matrix(face.rotation).as_euler("xyz", degrees=True)
        if assembly is not None:
            plate = cq.Workplane("XY").box(width, height, 2.0)
            assembly.add(
                plate,
                name=cover.id,
                color=cq.Color(0.35, 0.38, 0.42),
                loc=cq.Location(tuple(center), tuple(float(value) for value in rpy)),
            )
        axis_local = face.rotation.T @ axis
        open_angle = float(cover.hinge.get("open_angle_deg", 110.0))
        axes.append(
            ModuleAxis(
                id=cover.id,
                type="revolute",
                parent="base",
                child=cover.id,
                origin={"xyz": tuple(pivot), "rpy_deg": tuple(rpy)},
                axis=tuple(float(value) for value in axis_local),
                range_deg=(0.0, open_angle),
            )
        )
        frames[cover.id] = _frame(center, face.rotation)
        frames[f"{cover.id}.hinge"] = _frame(pivot, face.rotation)
        frames[f"{cover.id}.edge"] = _frame(free, face.rotation)
    for region in sku.inspect_regions:
        face_name = str(region.get("face", "top"))
        face = _face_basis(sku, face_name)
        rect = region.get("rect", {})
        u, v, width, height = _fit_rect(
            str(region.get("id", "inspect_region")),
            float(rect.get("u", 0)),
            float(rect.get("v", 0)),
            float(rect.get("w", face.width)),
            float(rect.get("h", face.height)),
            face,
            warnings,
        )
        center = face.origin + face.u * (u + width / 2) + face.v * (v + height / 2)
        frames[str(region["id"])] = _frame(center, face.rotation)
    definition = ModuleDef(
        id=part_id,
        frames=frames,
        axes=axes,
        collision="box",
        payload_kg=sku.mass_kg,
    )
    return BuiltWorkpiece(
        sku,
        assembly,
        definition,
        warnings,
        id=part_id,
        mass_kg=float(sku.mass_kg),
        height_mm=float(sku.size.z),
        trust=sku.size.trust,
    )
