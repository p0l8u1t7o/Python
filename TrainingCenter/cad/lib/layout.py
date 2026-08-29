"""組裝版面工具：場景座標（公尺、Y 向上，與前端 three.js 相同）→ CAD 座標（mm、Z 向上），
以及可動節點（關節／氣缸桿／輸送載具／風扇）的基準點嵌入。

前端 GltfScene 依節點名稱與基準點做互動與動畫：
- 節點名稱 = seed 的 mesh_name（點選／高亮）
- 子節點 `_pivot`、`_axis`（1 mm 小球，前端隱藏）= 旋轉／平移的樞軸與軸向
- 子節點 `_anim_<kind>`：rev（往復擺動）、spin（連續旋轉）、rod（往復直線）、carrier（循環直線）、blink
"""
from __future__ import annotations

from typing import Iterable

from build123d import Compound, Location, Pos, Rot, Shape, Sphere
from cadgen import srgb
from cadgen.assembly import AssemblyHelper, label_shape

M = 1000.0  # m → mm


def scene(x: float, y: float, z: float) -> tuple[float, float, float]:
    """three.js (x, y, z) Y-up 公尺 → build123d (x, -z, y) Z-up mm。"""
    return (x * M, -z * M, y * M)


def place(shape: Shape, pos_m: tuple[float, float, float], yaw_deg: float = 0.0, rot: tuple[float, float, float] | None = None) -> Shape:
    """把以「底面中心為原點、+Z 向上」建的零件放到場景座標（pos_m 為底面中心，公尺，Y-up）。
    yaw_deg：繞垂直軸（場景 Y = CAD Z）旋轉；rot：額外的 CAD (rx, ry, rz) 度。"""
    cad = scene(*pos_m)
    r = rot or (0.0, 0.0, 0.0)
    return shape.moved(Location(cad, (r[0], r[1], r[2] + yaw_deg)))


def datum(pos_m: tuple[float, float, float], name: str) -> Shape:
    s = Sphere(0.5).moved(Location(scene(*pos_m)))
    s.color = srgb("#ff00ff", 0.0)
    return label_shape(s, name)


def anim_datums(kind: str, pivot_m: tuple[float, float, float], axis_dir: tuple[float, float, float]) -> list[Shape]:
    """回傳 [_anim_<kind>, _pivot, _axis] 三個基準小球；axis 為場景座標方向向量（Y-up）。"""
    ax = (pivot_m[0] + axis_dir[0] * 0.1, pivot_m[1] + axis_dir[1] * 0.1, pivot_m[2] + axis_dir[2] * 0.1)
    return [datum(pivot_m, f"_anim_{kind}"), datum(pivot_m, "_pivot"), datum(ax, "_axis")]


def module(asm: AssemblyHelper, name: str, children: Iterable[Shape]) -> Compound:
    return asm.add_module(name, list(children))


def part(asm: AssemblyHelper, name: str, shape: Shape) -> Shape:
    return asm.add(shape, name)


def moving_module(asm: AssemblyHelper, name: str, kind: str, pivot_m, axis_dir, children: Iterable[Shape], color=None) -> Compound:
    """帶動畫基準點的模組。"""
    kids = list(children) + anim_datums(kind, pivot_m, axis_dir)
    m = asm.add_module(name, kids)
    if color is not None:
        m.color = color
    return m


def sub_compound(name: str, children: Iterable[Shape]) -> Compound:
    """不經 asm 直接建子組（用於巢狀關節）。"""
    c = Compound(children=list(children))
    c.label = name
    return c


def sub_moving(name: str, kind: str, pivot_m, axis_dir, children: Iterable[Shape]) -> Compound:
    return sub_compound(name, list(children) + anim_datums(kind, pivot_m, axis_dir))


__all__ = ["M", "scene", "place", "datum", "anim_datums", "module", "part", "moving_module", "sub_compound", "sub_moving", "Pos", "Rot", "Location"]
