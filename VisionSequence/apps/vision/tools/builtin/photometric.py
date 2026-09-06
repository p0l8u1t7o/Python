"""光度立體（photometric_stereo）：四方向打光合成表面法向，抓刻印字、凹凸缺陷、拋光面刮痕——單張影像上「看不見」的東西。

Lambertian 模型 I_k = ρ · (N · L_k)：每個像素對 N 盞燈解最小平方。
- 光源方向矩陣 L（N×3）由方位角（畫面 +x 起、順時針為正，與平台角度慣例一致）與仰角算出，是常數；**偽逆預先算好並快取**，
  每幀只做 (3×N)·(N×HW) 矩陣乘（向量化是效能的全部關鍵，逐像素 lstsq 是災難）。
- 陰影：4 盞燈時每個像素丟掉最暗的一張、用剩下 3 張解。**不用四組子集偽逆逐像素挑**（fancy indexing 一張 1280×960 要 50 ms），
  而是留一法（leave-one-out）更新式：g_d = g_full − c_d · r_d，c_d＝(LᵀL)⁻¹l_d／(1−h_d) 是每盞燈一個常數 3 向量，
  r_d＝I_d − l_dᵀg_full 是那盞燈的殘差；I_d 就是四張的逐像素最小值，l_d／c_d 由最暗索引查 4 格小表。
- **整條管線按列分塊**（約 40K 像素一塊，全部留在快取內）：整張 1280×960 的 numpy 逐元素運算是記憶體頻寬綁死的（每趟 1.5 ms、
  管線 20 幾趟），分塊後 no-drop 8 ms、drop 21 ms（整張分別 25／75 ms）。
- curvature ＝ 法向場的散度 ∂Nx/∂x + ∂Ny/∂y（Sobel），對刻印字最有效；albedo ＝ |ρN| 反射率圖（把打光影響拿掉的「純材質」圖）。
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError

OUTPUT_OPTIONS = [
    {"value": "curvature", "label": "Curvature (signed shape map: bumps bright, dents dark)"},
    {"value": "curvature_abs", "label": "Shape strength (absolute curvature, for thresholding)"},
    {"value": "normal_x", "label": "Normal X (left-right slope)"},
    {"value": "normal_y", "label": "Normal Y (up-down slope)"},
    {"value": "albedo", "label": "Albedo (reflectance without the lighting)"},
    {"value": "all", "label": "All (image = curvature)"},
]
MAP_KEYS = ("curvature", "curvature_abs", "albedo", "normal_x", "normal_y")
TILE_PIXELS = 40_000

_SOLVERS: dict[tuple, dict[str, Any]] = {}
_LOCK = threading.Lock()


def light_directions(azimuths: list[float], elevation: float) -> np.ndarray:
    """(N, 3) 單位光向量：方位角在影像平面（x 右、y 下、順時針為正），仰角離平面往相機。"""
    e = math.radians(float(elevation))
    out = []
    for a in azimuths:
        t = math.radians(float(a))
        out.append([math.cos(e) * math.cos(t), math.cos(e) * math.sin(t), math.sin(e)])
    return np.asarray(out, dtype=np.float32)


def _solvers(azimuths: tuple[float, ...], elevation: float) -> dict[str, Any]:
    """全燈偽逆＋留一法常數（每盞燈的 c_d 與 l_d，放成 256 格查表給 u8 索引用），快取。"""
    key = (azimuths, round(float(elevation), 4))
    with _LOCK:
        hit = _SOLVERS.get(key)
        if hit is not None:
            return hit
    L = light_directions(list(azimuths), elevation)
    if np.linalg.matrix_rank(L) < 3:
        raise ToolError("The light directions are degenerate (at least three lights from different sides are needed)")
    L64 = L.astype(np.float64)
    full = np.linalg.pinv(L64).astype(np.float32)  # (3, N)
    ltl_inv = np.linalg.inv(L64.T @ L64)
    n = len(azimuths)
    loo_ok = n >= 4
    coef = np.zeros((n, 3), dtype=np.float64)
    for d in range(n):
        h = float(L64[d] @ ltl_inv @ L64[d])  # 槓桿值
        if h >= 1.0 - 1e-6 or np.linalg.matrix_rank(np.delete(L64, d, axis=0)) < 3:
            loo_ok = False
            break
        coef[d] = ltl_inv @ L64[d] / (1.0 - h)
    table_c = np.zeros((3, 256), dtype=np.float32)
    table_l = np.zeros((3, 256), dtype=np.float32)
    if loo_ok:
        table_c[:, :n] = coef.T
        table_l[:, :n] = L64.T
    out = {"L": L, "full": full, "loo": loo_ok, "table_c": table_c, "table_l": table_l}
    with _LOCK:
        if len(_SOLVERS) > 16:
            _SOLVERS.clear()
        _SOLVERS[key] = out
    return out


def _gray(im: np.ndarray, k: int, h: int, w: int) -> np.ndarray:
    g = im if im.ndim == 2 else cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    if g.shape[:2] != (h, w):
        raise ToolError(f"Light image {k + 1} is {g.shape[1]}×{g.shape[0]} but image 1 is {w}×{h}; all lighting pictures must be the same size")
    if g.dtype != np.uint8:
        g = cv2.normalize(g.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return np.ascontiguousarray(g)


def solve(images: list[np.ndarray], azimuths: list[float], elevation: float, drop_darkest: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """N 張灰階 → (法向 (3, H, W) float32 單位向量 [nx, ny, nz], albedo (H, W) float32 ＝ |ρ|)。"""
    n = len(images)
    h, w = images[0].shape[:2]
    grays = [_gray(im, k, h, w) for k, im in enumerate(images)]
    s = _solvers(tuple(float(a) for a in azimuths[:n]), elevation)
    full = s["full"]
    drop = bool(drop_darkest and n >= 4 and s["loo"])
    hw = h * w
    normals = np.empty((3, hw), dtype=np.float32)
    albedo = np.empty(hw, dtype=np.float32)
    rows = max(1, TILE_PIXELS // w)
    stack = np.empty((n, rows * w), dtype=np.float32)
    if drop:
        # 最暗的那盞燈：u8 上做（cv2 多執行緒、每趟 0.3 ms），索引 0..n-1
        m = grays[0]
        for k in range(1, n):
            m = cv2.min(m, grays[k])
        idx = np.zeros((h, w), dtype=np.uint8)
        for k in range(1, n):
            idx = cv2.max(idx, cv2.min(cv2.compare(grays[k], m, cv2.CMP_EQ), float(k)))
        mflat = m.reshape(-1)
        iflat = idx.reshape(-1)
        tc, tl = s["table_c"], s["table_l"]
    for r0 in range(0, h, rows):
        r1 = min(r0 + rows, h)
        a, b = r0 * w, r1 * w
        st = stack[:, : b - a]
        for k in range(n):
            st[k] = grays[k][r0:r1].reshape(-1)
        g = full @ st  # (3, t)：ρ·N
        if drop:
            ii = iflat[a:b]
            pred = np.take(tl[0], ii) * g[0]
            pred += np.take(tl[1], ii) * g[1]
            pred += np.take(tl[2], ii) * g[2]
            resid = mflat[a:b].astype(np.float32)
            resid -= pred
            for k in range(3):
                g[k] -= np.take(tc[k], ii) * resid
        rho = np.sqrt(np.einsum("ij,ij->j", g, g))
        inv = np.reciprocal(np.maximum(rho, 1e-6))
        for k in range(3):
            np.multiply(g[k], inv, out=normals[k, a:b])
        albedo[a:b] = rho
    return normals.reshape(3, h, w), albedo.reshape(h, w)


def curvature_of(normals: np.ndarray) -> np.ndarray:
    """散度 ∂Nx/∂x + ∂Ny/∂y（Sobel，1/8 縮放）：凸起處為正、凹陷為負。normals 為 (3, H, W)。"""
    dx = cv2.Sobel(normals[0], cv2.CV_32F, 1, 0, ksize=3, scale=1.0 / 8.0)
    dy = cv2.Sobel(normals[1], cv2.CV_32F, 0, 1, ksize=3, scale=1.0 / 8.0)
    return cv2.add(dx, dy)


def _percentile(arr: np.ndarray, q) -> Any:
    """顯示用正規化的百分位：抽樣 1/32（整張 np.percentile 要 10 ms 以上）。"""
    flat = arr.reshape(-1)
    return np.percentile(flat[::32] if flat.size > 65536 else flat, q)


def to_u8(arr: np.ndarray, kind: str) -> np.ndarray:
    """正規化到 u8：法向分量 (−1..1) → 0..255；albedo／shape strength 以 99.5／98 百分位為白；curvature 以 2～98 百分位對稱拉伸、0 在 128。"""
    if kind in ("normal_x", "normal_y"):
        return cv2.convertScaleAbs(arr, alpha=127.5, beta=127.5)
    if kind == "albedo":
        hi = float(_percentile(arr, 99.5))
        return cv2.convertScaleAbs(arr, alpha=255.0 / max(hi, 1e-6))
    if kind == "curvature_abs":
        hi = float(_percentile(arr, 98))
        return cv2.convertScaleAbs(arr, alpha=255.0 / max(hi, 1e-6))
    lo, hi = _percentile(arr, (2, 98))
    span = max(abs(float(lo)), abs(float(hi)), 1e-6)
    return cv2.convertScaleAbs(arr, alpha=127.0 / span, beta=128.0)


class PhotometricStereoTool(Tool):
    key = "photometric_stereo"
    label = "Photometric stereo"
    description = (
        "Combines three or four pictures of the same part, each lit from a different side, into the surface shape: embossed and "
        "engraved characters, dents, bumps and scratches on polished surfaces stand out in the curvature map even when they are "
        "invisible in any single picture. The albedo output is the material without the lighting."
    )
    category = "preprocess"
    icon = "Lightbulb"
    heavy = True
    params = [
        Param("light_azimuth", "Light azimuths", kind="json", default=[0, 90, 180, 270],
              help_text="One angle per light, in degrees around the picture (0 = from the right, 90 = from below, clockwise). Four lights at 90° apart is the usual rig."),
        Param("light_elevation", "Light elevation", kind="number", default=30, minimum=5, maximum=85, unit="°", help_text="Angle of the lights above the surface; the same for all lights."),
        Param("output", "Image output", kind="select", default="curvature", options=OUTPUT_OPTIONS),
        Param("normalize", "Normalise to 8-bit", kind="boolean", default=True, help_text="Off keeps float32 maps (curvature and normals signed)."),
        Param("drop_darkest", "Drop the darkest light per pixel", kind="boolean", default=True, group="Advanced",
              help_text="With four lights, solve each pixel from the three brighter pictures so shadows in deep grooves do not tilt the normal."),
    ]
    inputs = [
        Port("image", "Light 1", "image"), Port("image_1", "Light 2", "image", required=False),
        Port("image_2", "Light 3", "image", required=False), Port("image_3", "Light 4", "image", required=False),
    ]
    outputs = [
        Port("image", "Image", "image"), Port("curvature", "Curvature", "image"), Port("curvature_abs", "Shape strength", "image"),
        Port("albedo", "Albedo", "image"), Port("normal_x", "Normal X", "image"), Port("normal_y", "Normal Y", "image"),
        Port("lights", "Lights used", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        images = [ctx.image("image")]
        for key in ("image_1", "image_2", "image_3"):
            im = ctx.image(key)
            if im is not None:
                images.append(im)
        if images[0] is None:
            raise ToolError("Input port 'image' has no image")
        if len(images) < 3:
            raise ToolError("At least three lighting pictures are needed (four is the usual rig)")
        raw = ctx.param("light_azimuth", [0, 90, 180, 270])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raise ToolError("Light azimuths must be a JSON list of angles") from None
        try:
            azimuths = [float(a) for a in raw]
        except (TypeError, ValueError):
            raise ToolError("Light azimuths must be a list of numbers") from None
        if len(azimuths) < len(images):
            raise ToolError(f"{len(images)} pictures but only {len(azimuths)} light azimuths")
        elevation = ctx.number("light_elevation", 30)
        normals, albedo = solve(images, azimuths, elevation, ctx.flag("drop_darkest", True))
        curv = curvature_of(normals)
        norm = ctx.flag("normalize", True)
        raw_maps = {"curvature": curv, "curvature_abs": cv2.absdiff(curv, 0.0), "albedo": albedo, "normal_x": normals[0], "normal_y": normals[1]}
        maps = {k: (to_u8(v, k) if norm else np.ascontiguousarray(v)) for k, v in raw_maps.items()}
        which = str(ctx.param("output", "curvature"))
        main = maps.get(which, maps["curvature"])
        return Result(outputs={"image": main, "lights": len(images), **maps},
                      message=f"{len(images)} lights, elevation {elevation:g}°, output {which}")


TOOLS = [PhotometricStereoTool()]
