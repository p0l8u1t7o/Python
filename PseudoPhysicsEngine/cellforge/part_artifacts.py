"""Standalone render and preview artifacts for one parametric module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import cadquery as cq
import numpy as np
import trimesh
from PIL import Image, ImageDraw

from cellforge.build.glb import _assembly_meshes, export_glb
from cellforge.build.modules import BuiltModule
from cellforge.part_check import (
    _built,
    _default_params,
    _definition,
    _load_file,
    discover_part_files,
)
from cellforge.schema import ModuleDef
from cellforge.schema.models import ModuleInstance

RENDER_WIDTH_PX = 1600
RENDER_HEIGHT_PX = 1200
PANEL_PADDING_PX = 64
PANEL_LABEL_OFFSET_PX = 20
BACKGROUND_COLOR = (11, 17, 24)
PANEL_COLOR = (18, 27, 37)
PANEL_BORDER_COLOR = (74, 91, 108)
LABEL_COLOR = (226, 234, 241)


class PartArtifactError(RuntimeError):
    pass


@dataclass(slots=True)
class LoadedPart:
    module: ModuleType
    definition: ModuleDef
    assembly: cq.Assembly
    params: dict[str, Any]
    source: Path


def load_part_artifact(project_dir: Path, module_id: str) -> LoadedPart:
    path = discover_part_files(project_dir).get(Path(module_id).stem)
    if path is None:
        raise PartArtifactError(f"找不到模組：{module_id}")
    return load_part_source(path)


def load_part_source(source: Path, supplied_params: dict[str, Any] | None = None) -> LoadedPart:
    source = source.resolve()
    try:
        module = _load_file(source)
        static = _definition(module, {})
        params = {**_default_params(static), **(supplied_params or {})}
        definition = _definition(module, params)
        assembly = _built(module, params)
    except Exception as error:  # noqa: BLE001 - module boundary becomes a localized CLI error
        raise PartArtifactError(f"模組 {source.stem} 以指定參數建置失敗：{error}") from error
    return LoadedPart(module, definition, assembly, params, source)


def resolve_part_output(output: Path, module_id: str, extension: str) -> Path:
    extension = extension.removeprefix(".").lower()
    if str(output).lower() == extension:
        return Path.cwd() / f"{module_id}.{extension}"
    if output.suffix.lower() != f".{extension}":
        raise PartArtifactError(f"輸出檔副檔名必須是 .{extension}：{output}")
    return output


def preview_part(project_dir: Path, module_id: str, output: Path) -> Path:
    loaded = load_part_artifact(project_dir, module_id)
    return preview_loaded_part(loaded, output)


def preview_loaded_part(loaded: LoadedPart, output: Path) -> Path:
    chain_factory = getattr(loaded.module, "chain_from_params", None)
    chain = chain_factory(loaded.params) if callable(chain_factory) else None
    instance = ModuleInstance(id=loaded.definition.id, part=str(loaded.source))
    built = BuiltModule(
        instance=instance,
        definition=loaded.definition,
        assembly=loaded.assembly,
        source=str(loaded.source),
        chain=chain,
    )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        export_glb([built], output)
    except Exception as error:  # noqa: BLE001 - exporter errors become a localized CLI error
        raise PartArtifactError(
            f"模組 {loaded.definition.id} 的 GLB 預覽產生失敗：{error}"
        ) from error
    return output


def render_part(project_dir: Path, module_id: str, output: Path) -> Path:
    loaded = load_part_artifact(project_dir, module_id)
    return render_loaded_part(loaded, output)


def render_loaded_part(loaded: LoadedPart, output: Path) -> Path:
    meshes = _assembly_meshes(loaded.assembly)
    if not meshes:
        raise PartArtifactError(f"模組 {loaded.definition.id} 沒有可渲染的 visual 幾何")
    canvas = Image.new("RGB", (RENDER_WIDTH_PX, RENDER_HEIGHT_PX), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)
    views = (
        ("FRONT", np.asarray((0.0, -1.0, 0.0)), np.asarray((0.0, 0.0, 1.0))),
        ("SIDE", np.asarray((1.0, 0.0, 0.0)), np.asarray((0.0, 0.0, 1.0))),
        ("TOP", np.asarray((0.0, 0.0, 1.0)), np.asarray((0.0, 1.0, 0.0))),
        ("ISO", np.asarray((1.0, -1.0, 0.75)), np.asarray((0.0, 0.0, 1.0))),
    )
    panel_width = RENDER_WIDTH_PX // 2
    panel_height = RENDER_HEIGHT_PX // 2
    for index, (label, view_direction, up_hint) in enumerate(views):
        left = (index % 2) * panel_width
        top = (index // 2) * panel_height
        bounds = (left, top, left + panel_width - 1, top + panel_height - 1)
        draw.rectangle(bounds, fill=PANEL_COLOR, outline=PANEL_BORDER_COLOR, width=2)
        _draw_view(draw, meshes, bounds, view_direction, up_hint)
        draw.text(
            (left + PANEL_LABEL_OFFSET_PX, top + PANEL_LABEL_OFFSET_PX),
            label,
            fill=LABEL_COLOR,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")
    return output


def _draw_view(
    draw: ImageDraw.ImageDraw,
    meshes: list[tuple[str, trimesh.Trimesh]],
    bounds: tuple[int, int, int, int],
    view_direction: np.ndarray,
    up_hint: np.ndarray,
) -> None:
    view = view_direction / np.linalg.norm(view_direction)
    right = np.cross(view, up_hint)
    right /= np.linalg.norm(right)
    up = np.cross(right, view)
    up /= np.linalg.norm(up)
    all_vertices = np.vstack([mesh.vertices for _name, mesh in meshes])
    center = (all_vertices.min(axis=0) + all_vertices.max(axis=0)) / 2.0
    projected_all = _project(all_vertices - center, right, up, view)
    low = projected_all[:, :2].min(axis=0)
    high = projected_all[:, :2].max(axis=0)
    span = np.maximum(high - low, 1e-9)
    left, top, right_edge, bottom = bounds
    available = np.asarray(
        (
            right_edge - left - PANEL_PADDING_PX * 2,
            bottom - top - PANEL_PADDING_PX * 2,
        ),
        dtype=float,
    )
    scale = float(np.min(available / span))
    panel_center = np.asarray(((left + right_edge) / 2, (top + bottom) / 2), dtype=float)
    faces: list[tuple[float, list[tuple[float, float]], tuple[int, int, int]]] = []
    light = view + np.asarray((-0.35, -0.25, 0.8))
    light /= np.linalg.norm(light)
    for _name, mesh in meshes:
        vertices = np.asarray(mesh.vertices, dtype=float)
        centered = vertices - center
        projected = _project(centered, right, up, view)
        colors = np.asarray(mesh.visual.vertex_colors)[:, :3]
        for face in np.asarray(mesh.faces, dtype=int):
            triangle = centered[face]
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            length = float(np.linalg.norm(normal))
            if length <= 1e-12:
                continue
            normal /= length
            if float(np.dot(normal, view)) <= 0:
                continue
            coordinates = projected[face]
            points = [
                (
                    float(panel_center[0] + point[0] * scale),
                    float(panel_center[1] - point[1] * scale),
                )
                for point in coordinates
            ]
            brightness = 0.48 + 0.52 * max(0.0, float(np.dot(normal, light)))
            base = colors[face].mean(axis=0)
            color = tuple(int(np.clip(channel * brightness, 0, 255)) for channel in base)
            faces.append((float(coordinates[:, 2].mean()), points, color))
    for _depth, points, color in sorted(faces, key=lambda item: item[0]):
        draw.polygon(points, fill=color)


def _project(
    vertices: np.ndarray,
    right: np.ndarray,
    up: np.ndarray,
    view: np.ndarray,
) -> np.ndarray:
    return np.column_stack((vertices @ right, vertices @ up, vertices @ view))
