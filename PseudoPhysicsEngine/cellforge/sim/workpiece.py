"""Workpiece geometry, face frames, and articulated hinged covers."""

from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq
import numpy as np
from scipy.spatial.transform import Rotation

from cellforge.schema import Frame, ModuleAxis, ModuleDef
from cellforge.schema.models import Cover, Process, Sku, Workpiece


@dataclass(slots=True)
class BuiltWorkpiece:
    sku: Sku
    assembly: cq.Assembly
    definition: ModuleDef
    warnings: list[str] = field(default_factory=list)


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


def build_workpiece(workpiece: Workpiece, process: Process | None = None) -> BuiltWorkpiece:
    sku = _choose_sku(workpiece, process)
    assembly = cq.Assembly(name="workpiece")
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
        id="workpiece",
        frames=frames,
        axes=axes,
        collision="box",
        payload_kg=sku.mass_kg,
    )
    return BuiltWorkpiece(sku, assembly, definition, warnings)
