"""定位工具：範本比對、定位補正、ROI 跟隨、找圓、找直線、Hough。

座標慣例：所有輸出與 overlays 都是「該節點輸入影像」的全圖座標。
ROI 先裁切再運算，結果用 Crop.to_full / points_to_full 換回全圖。
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.roi import Crop, crop, extent, region_center, region_overlay, transform_region


def to_gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


#: 解碼後的資產影像快取：(path, gray) → (mtime, size, image)。每次 run 重新 imdecode 一張
#: 1280×960 的 PNG 要 5 ms，比大多數工具本身還慢；以檔案 mtime/size 判斷失效。
_ASSET_CACHE: "OrderedDict[tuple[str, bool], tuple[float, int, np.ndarray]]" = OrderedDict()
_ASSET_CACHE_MAX = 32
_ASSET_LOCK = threading.Lock()


def reference_image(ctx: ToolContext, port: str, key: str, *, gray: bool = True) -> np.ndarray:
    """參考影像：影像輸入埠（例如固定影像工具接進來）優先，沒接才讀 `key` 資產。回傳的陣列不可原地修改。"""
    img = ctx.inputs.get(port)
    if isinstance(img, np.ndarray) and img.size:
        if gray and img.ndim == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return np.ascontiguousarray(img)
    if not ctx.param(key):
        raise ToolError(f"Connect a picture to '{port}' or choose an asset for '{key}'")
    return read_asset_image(ctx, key, gray=gray)


def read_asset_image(ctx: ToolContext, key: str, *, gray: bool = True) -> np.ndarray:
    """讀取資產影像（支援非 ASCII 路徑）。缺資產 → ToolError。

    回傳的陣列是快取共用的，呼叫端不可原地修改。
    """
    asset_id = ctx.param(key)
    if not asset_id:
        raise ToolError(f"No asset is set for '{key}'")
    path = ctx.asset_path(str(asset_id))
    if not path:
        raise ToolError(f"Asset {asset_id} not found")
    try:
        st = os.stat(path)
    except OSError as exc:
        raise ToolError(f"Could not read the asset: {exc}") from None
    cache_key = (path, gray)
    with _ASSET_LOCK:
        hit = _ASSET_CACHE.get(cache_key)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            _ASSET_CACHE.move_to_end(cache_key)
            return hit[2]
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ToolError(f"Could not read the asset: {exc}") from None
    image = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ToolError(f"Asset {asset_id} is not a decodable image")
    with _ASSET_LOCK:
        _ASSET_CACHE[cache_key] = (st.st_mtime, st.st_size, image)
        _ASSET_CACHE.move_to_end(cache_key)
        while len(_ASSET_CACHE) > _ASSET_CACHE_MAX:
            _ASSET_CACHE.popitem(last=False)
    return image


def clear_asset_cache() -> None:
    with _ASSET_LOCK:
        _ASSET_CACHE.clear()


POLARITY_OPTIONS = [
    {"value": "any", "label": "Any"},
    {"value": "dark_to_light", "label": "Dark to light"},
    {"value": "light_to_dark", "label": "Light to dark"},
]


def smooth_profile(profile: np.ndarray, smoothing: int) -> np.ndarray:
    profile = np.asarray(profile, dtype=np.float32)
    k = int(smoothing)
    if k <= 1 or len(profile) < 3:
        return profile
    if k % 2 == 0:
        k += 1
    k = min(k, len(profile) if len(profile) % 2 else len(profile) - 1)
    return cv2.GaussianBlur(profile.reshape(1, -1), (k, 1), 0).reshape(-1)


def find_edges_rows(profiles: np.ndarray, polarity: str = "any", threshold: float = 20.0, smoothing: int = 3) -> list[list[tuple[float, float]]]:
    """對多條剖面（R×L）一次找邊緣；每列回傳 [(次像素位置, 帶號梯度強度)]，依位置排序。

    與逐列呼叫 find_edges_1d 結果完全相同（平滑、梯度、非極大抑制、拋物線次像素
    都是逐列獨立的運算），但整批向量化處理，找圓 180 條掃描線只要一次呼叫。
    """
    p = np.asarray(profiles, dtype=np.float32)
    if p.ndim == 1:
        p = p.reshape(1, -1)
    rows, length = p.shape
    if length < 3 or rows == 0:
        return [[] for _ in range(rows)]
    k = int(smoothing)
    if k > 1:
        if k % 2 == 0:
            k += 1
        k = min(k, length if length % 2 else length - 1)
        p = cv2.GaussianBlur(p, (k, 1), 0)
    grad = np.gradient(p, axis=1)
    if polarity == "dark_to_light":
        score = grad
    elif polarity == "light_to_dark":
        score = -grad
    else:
        score = np.abs(grad)
    # 局部極大值（非極大抑制）：左鄰為 -inf、右鄰為 -inf 代表邊界
    mask = np.empty(score.shape, dtype=bool)
    mask[:, 0] = score[:, 0] > score[:, 1]
    mask[:, -1] = score[:, -1] >= score[:, -2]
    mask[:, 1:-1] = (score[:, 1:-1] >= score[:, :-2]) & (score[:, 1:-1] > score[:, 2:])
    mask &= score >= threshold
    ri, ci = np.nonzero(mask)
    pos = ci.astype(np.float64)
    inner = (ci > 0) & (ci < length - 1)
    if inner.any():
        r_in, c_in = ri[inner], ci[inner]
        a = score[r_in, c_in - 1]
        b = score[r_in, c_in]
        c = score[r_in, c_in + 1]
        denom = a - 2 * b + c
        safe = np.abs(denom) > 1e-9
        off = np.zeros(len(denom), dtype=np.float32)
        np.divide(0.5 * (a - c), denom, out=off, where=safe)
        off = np.clip(off, -0.5, 0.5)
        off[~safe] = 0.0
        pos[inner] += off.astype(np.float64)
    strength = grad[ri, ci].astype(np.float64)
    out: list[list[tuple[float, float]]] = [[] for _ in range(rows)]
    for r, x, g in zip(ri.tolist(), pos.tolist(), strength.tolist()):
        out[r].append((x, g))
    return out


def find_edges_1d(profile: np.ndarray, polarity: str = "any", threshold: float = 20.0, smoothing: int = 3) -> list[tuple[float, float]]:
    """在一維灰階剖面找邊緣：回傳 [(次像素位置, 帶號梯度強度)]，依位置排序。

    梯度為正代表沿掃描方向由暗到亮。
    """
    # 單條剖面用純量版本：峰值通常只有幾個，逐點處理比向量化版本少 0.1 ms 的 numpy 固定開銷。
    p = smooth_profile(profile, smoothing)
    if len(p) < 3:
        return []
    grad = np.gradient(p)
    if polarity == "dark_to_light":
        score = grad
    elif polarity == "light_to_dark":
        score = -grad
    else:
        score = np.abs(grad)
    # 局部極大值（非極大抑制）
    left = np.r_[-np.inf, score[:-1]]
    right = np.r_[score[1:], -np.inf]
    peaks = np.where((score >= left) & (score > right) & (score >= threshold))[0]
    edges: list[tuple[float, float]] = []
    for i in peaks:
        pos = float(i)
        if 0 < i < len(score) - 1:
            a, b, c = score[i - 1], score[i], score[i + 1]
            denom = a - 2 * b + c
            if abs(denom) > 1e-9:
                pos += float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
        edges.append((pos, float(grad[i])))
    return edges


def pick_edge(edges: list[tuple[float, float]], direction: str) -> tuple[float, float] | None:
    if not edges:
        return None
    if direction == "last":
        return edges[-1]
    if direction == "strongest":
        return max(edges, key=lambda e: abs(e[1]))
    return edges[0]


def sector_thetas(num_rays: int, a0: float | None = None, a1: float | None = None) -> np.ndarray:
    """徑向掃描線的角度（弧度）：整圈等距不含終點；扇形 a0→a1（度，畫面順時針為正）時 num_rays 條全落在扇形內、含兩端。"""
    if a0 is None or a1 is None:
        return np.linspace(0, 2 * math.pi, num_rays, endpoint=False, dtype=np.float32)
    start, end = float(a0), float(a1)
    if end <= start:
        end += 360.0
    return np.radians(np.linspace(start, end, num_rays, endpoint=True)).astype(np.float32)


def radial_edge_points(image: np.ndarray, cx: float, cy: float, r_in: float, r_out: float, num_rays: int,
                       polarity: str, threshold: float, select: str, smoothing: int, *,
                       mask: np.ndarray | None = None, mask_offset: tuple[int, int] = (0, 0),
                       a0: float | None = None, a1: float | None = None) -> list[list[float]]:
    """由 (cx, cy) 向外發射 num_rays 條徑向掃描線（可限扇形 a0→a1），每條取一個邊緣點（全圖座標）。

    cv2.remap 一次取樣所有剖面 → find_edges_rows 向量化找邊；mask 給定時只保留落在遮罩內的點（polygon ROI 用）。
    """
    n_samples = int(math.ceil(r_out - r_in)) + 1
    radii = np.linspace(r_in, r_out, n_samples, dtype=np.float32)
    thetas = sector_thetas(num_rays, a0, a1)
    map_x = (cx + np.cos(thetas)[:, None] * radii[None, :]).astype(np.float32)
    map_y = (cy + np.sin(thetas)[:, None] * radii[None, :]).astype(np.float32)
    profiles = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    pts: list[list[float]] = []
    for i, edges in enumerate(find_edges_rows(profiles, polarity, threshold, smoothing)):
        e = pick_edge(edges, select)
        if e is None:
            continue
        rr = r_in + e[0] * (r_out - r_in) / max(1, n_samples - 1)
        x, y = cx + math.cos(thetas[i]) * rr, cy + math.sin(thetas[i]) * rr
        if mask is not None:
            mx, my = int(round(x)) - mask_offset[0], int(round(y)) - mask_offset[1]
            if not (0 <= my < mask.shape[0] and 0 <= mx < mask.shape[1]) or mask[my, mx] == 0:
                continue
        pts.append([x, y])
    return pts


def fit_circle_points(pts: np.ndarray, use_ransac: bool, tol: float) -> tuple[tuple[float, float, float] | None, np.ndarray]:
    """依設定擬合圓：RANSAC（剔除離群後幾何精修）或直接幾何最小平方。回傳 (圓或 None, 內點遮罩)。"""
    arr = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    inliers = np.ones(len(arr), dtype=bool)
    if len(arr) < 3:
        return None, inliers
    if use_ransac:
        fitted = fit_circle_ransac(arr, tol=tol)
        if fitted is not None:
            return fitted[0], fitted[1]
    return fit_circle_lsq(arr), inliers


# ---------------------------------------------------------------------------
# 圓擬合
# ---------------------------------------------------------------------------
def fit_circle_kasa(pts: np.ndarray) -> tuple[float, float, float] | None:
    """代數最小平方（Kåsa）擬合圓：快，但部分圓弧有系統性偏差（60° 弧＋0.5px 噪點半徑約少 1px，30° 弧可差十幾 px）。"""
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 3:
        return None
    x, y = pts[:, 0], pts[:, 1]
    a = np.column_stack([x, y, np.ones_like(x)])
    b = -(x**2 + y**2)
    try:
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = -sol[0] / 2, -sol[1] / 2
    r2 = cx**2 + cy**2 - sol[2]
    if not np.isfinite(r2) or r2 <= 0:
        return None
    return float(cx), float(cy), float(math.sqrt(r2))


def _fit_circle_taubin(pts: np.ndarray) -> tuple[float, float, float] | None:
    """Taubin 代數擬合（Chernov 的 SVD 版）：對部分圓弧幾乎無偏，當幾何擬合的起始值。"""
    x0, y0 = float(pts[:, 0].mean()), float(pts[:, 1].mean())
    x, y = pts[:, 0] - x0, pts[:, 1] - y0
    z = x * x + y * y
    zm = float(z.mean())
    if zm <= 1e-12:
        return None
    zs = 2.0 * math.sqrt(zm)
    m = np.column_stack([(z - zm) / zs, x, y])
    try:
        _, _, vt = np.linalg.svd(m, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    a = vt[-1].copy()
    a[0] /= zs
    a4 = -zm * a[0]
    if abs(a[0]) < 1e-12:
        return None
    cx = -a[1] / a[0] / 2 + x0
    cy = -a[2] / a[0] / 2 + y0
    r2 = a[1] * a[1] + a[2] * a[2] - 4 * a[0] * a4
    if not np.isfinite(r2) or r2 <= 0:
        return None
    return float(cx), float(cy), float(math.sqrt(r2) / abs(a[0]) / 2)


def fit_circle_lsq(pts: np.ndarray, iterations: int = 30) -> tuple[float, float, float] | None:
    """幾何最小平方圓擬合：Taubin 起始 → Gauss–Newton 最小化各點到圓的徑向距離。

    部分圓弧（R 角、杯口圓角）也無偏；整圈時與 Kåsa 幾乎相同。回傳 (cx, cy, r)。
    """
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 3:
        return None
    init = _fit_circle_taubin(pts) or fit_circle_kasa(pts)
    if init is None:
        return None
    cx, cy, r = init
    x, y = pts[:, 0], pts[:, 1]
    ones = np.ones(len(pts))
    for _ in range(int(iterations)):
        dx, dy = x - cx, y - cy
        d = np.maximum(np.hypot(dx, dy), 1e-9)
        resid = d - r
        jac = np.column_stack([-dx / d, -dy / d, -ones])
        try:
            step, *_ = np.linalg.lstsq(jac, -resid, rcond=None)
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(step)):
            break
        cx, cy, r = cx + float(step[0]), cy + float(step[1]), r + float(step[2])
        if r <= 0:
            return init
        if float(np.abs(step).max()) < 1e-7:
            break
    return float(cx), float(cy), float(r)


def fit_circle_ransac(pts: np.ndarray, tol: float = 2.0, iterations: int = 200, seed: int = 0) -> tuple[tuple[float, float, float], np.ndarray] | None:
    """RANSAC 擬合圓：所有取樣一次向量化（三點圓閉式解 + 距離矩陣），不逐次 lstsq。"""
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n < 3:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(iterations), 3))
    idx = idx[(idx[:, 0] != idx[:, 1]) & (idx[:, 1] != idx[:, 2]) & (idx[:, 0] != idx[:, 2])]
    if len(idx) == 0:
        return None
    p = pts[idx]  # (m, 3, 2)
    x1, y1 = p[:, 0, 0], p[:, 0, 1]
    x2, y2 = p[:, 1, 0], p[:, 1, 1]
    x3, y3 = p[:, 2, 0], p[:, 2, 1]
    a, b = 2 * (x2 - x1), 2 * (y2 - y1)
    c = x2 * x2 + y2 * y2 - x1 * x1 - y1 * y1
    d, e = 2 * (x3 - x1), 2 * (y3 - y1)
    f = x3 * x3 + y3 * y3 - x1 * x1 - y1 * y1
    det = a * e - b * d
    good = np.abs(det) > 1e-9
    det = np.where(good, det, 1.0)
    cx = (c * e - b * f) / det
    cy = (a * f - c * d) / det
    r = np.hypot(x1 - cx, y1 - cy)
    dist = np.abs(np.hypot(pts[None, :, 0] - cx[:, None], pts[None, :, 1] - cy[:, None]) - r[:, None])
    inl = dist <= tol
    counts = inl.sum(axis=1)
    counts[~good] = -1
    best_i = int(counts.argmax())
    if counts[best_i] < 3:
        return None
    best_inliers = inl[best_i]
    best = (float(cx[best_i]), float(cy[best_i]), float(r[best_i]))
    refit = fit_circle_lsq(pts[best_inliers]) or best
    dd = np.abs(np.hypot(pts[:, 0] - refit[0], pts[:, 1] - refit[1]) - refit[2])
    return refit, dd <= tol


def fit_line_ransac(pts: np.ndarray, tol: float = 2.0, iterations: int = 200, seed: int = 0) -> tuple[tuple[float, float, float, float], np.ndarray] | None:
    """回傳 ((vx, vy, x0, y0), inlier_mask)。取樣與距離計算一次向量化。"""
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(iterations), 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    if len(idx) == 0:
        return None
    p0 = pts[idx[:, 0]]
    d = pts[idx[:, 1]] - p0
    norm = np.hypot(d[:, 0], d[:, 1])
    good = norm >= 1e-9
    norm = np.where(good, norm, 1.0)
    nx, ny = -d[:, 1] / norm, d[:, 0] / norm
    dist = np.abs((pts[None, :, 0] - p0[:, 0:1]) * nx[:, None] + (pts[None, :, 1] - p0[:, 1:2]) * ny[:, None])
    inl = dist <= tol
    counts = inl.sum(axis=1)
    counts[~good] = -1
    best_i = int(counts.argmax())
    if counts[best_i] < 2:
        return None
    best_inliers = inl[best_i]
    vx, vy, x0, y0 = cv2.fitLine(pts[best_inliers].astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).reshape(-1)
    return (float(vx), float(vy), float(x0), float(y0)), best_inliers


# ---------------------------------------------------------------------------
# 範本比對
# ---------------------------------------------------------------------------
def _rotate_template(tpl: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray | None]:
    """旋轉範本（外框放大以免裁掉角），回傳 (旋轉後影像, 遮罩)；angle=0 不做事。

    角度慣例與 ROI／找直線相同：影像座標 y 向下，正值＝畫面順時針（cv2.getRotationMatrix2D 的正值是逆時針，所以取負）。
    這樣 shape_align 的 dθ 才能直接餵給 fixture_roi（transform_region）。
    """
    if abs(angle) < 1e-6:
        return tpl, None
    h, w = tpl.shape[:2]
    rad = math.radians(angle)
    cos, sin = abs(math.cos(rad)), abs(math.sin(rad))
    nw = int(math.ceil(w * cos + h * sin))
    nh = int(math.ceil(w * sin + h * cos))
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    rotated = cv2.warpAffine(tpl, m, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), m, (nw, nh), flags=cv2.INTER_NEAREST, borderValue=0)
    return rotated, mask


def _inscribed_half(angle: float, w: int, h: int) -> tuple[int, int] | None:
    """w×h 的範本旋轉 angle 度後，仍完全落在有效像素內的置中軸對齊矩形半尺寸 (a, b)。

    金字塔粗找用「所有角度共用的置中裁切」取代帶遮罩的 matchTemplate（帶遮罩慢 4 倍）：
    每個角度都比同一塊中央區域，分數才能互相比較；細找仍用完整範本＋遮罩算精確分數。
    太小（邊 < 8）回 None，粗找改走遮罩。
    """
    th = math.radians(abs(angle))
    cos, sin = math.cos(th), math.sin(th)
    hw, hh = w / 2, h / 2
    s = min(hw / (hw * cos + hh * sin), hh / (hw * sin + hh * cos))
    a, b = int(hw * s), int(hh * s)
    if a < 4 or b < 4:
        return None
    return a, b


def _center_crop(image: np.ndarray, a: int, b: int) -> tuple[np.ndarray, int, int]:
    """取 image 中央 2a×2b 的區塊，回傳 (crop, x0, y0)。"""
    nh, nw = image.shape[:2]
    x0 = max(0, int(round(nw / 2 - a)))
    y0 = max(0, int(round(nh / 2 - b)))
    return image[y0 : min(nh, y0 + 2 * b), x0 : min(nw, x0 + 2 * a)], x0, y0


def _match(image: np.ndarray, tpl: np.ndarray, mask: np.ndarray | None) -> np.ndarray | None:
    th, tw = tpl.shape[:2]
    if image.shape[0] < th or image.shape[1] < tw:
        return None
    if mask is not None:
        result = cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
    else:
        result = cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED)
    result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
    return result


def _peaks(result: np.ndarray, threshold: float, max_n: int, tw: int, th: int) -> list[tuple[int, int, float]]:
    """從相關圖抓局部最大值（以範本半尺寸做非極大抑制）。"""
    res = result.copy()
    out: list[tuple[int, int, float]] = []
    rx, ry = max(1, tw // 2), max(1, th // 2)
    while len(out) < max_n:
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < threshold:
            break
        x, y = int(loc[0]), int(loc[1])
        out.append((x, y, float(score)))
        res[max(0, y - ry) : y + ry + 1, max(0, x - rx) : x + rx + 1] = -1.0
    return out


def _subpixel_peak(res: np.ndarray, x: int, y: int) -> tuple[float, float]:
    """相關圖峰值的 3×3 拋物線次像素內插（峰值在邊界時原樣回傳）。"""
    h, w = res.shape[:2]
    fx, fy = float(x), float(y)
    if 0 < x < w - 1:
        lo, c, hi = float(res[y, x - 1]), float(res[y, x]), float(res[y, x + 1])
        d = lo - 2 * c + hi
        if d < -1e-12:
            fx += max(-0.5, min(0.5, 0.5 * (lo - hi) / d))
    if 0 < y < h - 1:
        lo, c, hi = float(res[y - 1, x]), float(res[y, x]), float(res[y + 1, x])
        d = lo - 2 * c + hi
        if d < -1e-12:
            fy += max(-0.5, min(0.5, 0.5 * (lo - hi) / d))
    return fx, fy


def _window_match(search: np.ndarray, rt: np.ndarray, rm: np.ndarray | None, cx: float, cy: float, pad: int = 3) -> tuple[float, float, float] | None:
    """以中心 (cx, cy) 為準在小視窗內比對旋轉範本，回傳 (次像素中心 x, y, 分數)。"""
    rh, rw = rt.shape[:2]
    left, top = int(round(cx - rw / 2)), int(round(cy - rh / 2))
    x0, y0 = max(0, left - pad), max(0, top - pad)
    x1, y1 = min(search.shape[1], left + rw + pad), min(search.shape[0], top + rh + pad)
    res = _match(search[y0:y1, x0:x1], rt, rm)
    if res is None:
        return None
    _, score, _, loc = cv2.minMaxLoc(res)
    px, py = _subpixel_peak(res, int(loc[0]), int(loc[1]))
    return x0 + px + rw / 2, y0 + py + rh / 2, float(score)


def _refine_match(search: np.ndarray, tpl: np.ndarray, cx: float, cy: float, angle: float, score: float, step: float) -> tuple[float, float, float, float]:
    """次像素精修：角度以 (angle−step, angle, angle+step) 三個分數做拋物線內插，再於精修角度下重新比對並做 3×3 位置內插。"""
    best_angle = angle
    if step > 0:
        scores = []
        for a in (angle - step, angle, angle + step):
            rt, rm = _rotate_template(tpl, a)
            hit = _window_match(search, rt, rm, cx, cy)
            scores.append(hit[2] if hit is not None else -1.0)
        lo, mid, hi = scores
        d = lo - 2 * mid + hi
        if d < -1e-9 and mid >= max(lo, hi):
            best_angle = angle + step * max(-0.5, min(0.5, 0.5 * (lo - hi) / d))
    rt, rm = _rotate_template(tpl, best_angle)
    hit = _window_match(search, rt, rm, cx, cy)
    if hit is None:
        return cx, cy, score, angle
    return hit[0], hit[1], hit[2], best_angle


class TemplateMatchTool(Tool):
    key = "template_match"
    label = "Template match"
    description = "Finds a template by normalised cross-correlation, in the whole image or a search region, with optional rotation search, pyramid speed-up and sub-pixel refinement. Angles are positive clockwise on screen, as everywhere else in the platform."
    category = "locate"
    icon = "ScanSearch"
    params = [
        Param("template", "Template image", kind="asset", accept="image", required=False, help_text="Not needed when a picture is connected to the template picture input. The uploaded template image (matched in grayscale)."),
        Param("roi", "Search region", kind="roi", shapes=["rect", "rotated_rect"], help_text="Leave blank to search the whole image."),
        Param("threshold", "Score threshold", kind="range", default=0.7, minimum=0, maximum=1, step=0.01, help_text="NCC score 0–1; below this is not a match.", teach=True),
        Param("max_matches", "Max matches", kind="number", default=1, minimum=1, maximum=500),
        Param("angle_range", "Rotation range ±", kind="number", default=0, minimum=0, maximum=180, unit="°", help_text="0 disables the rotation search.", group="Rotation", teach=True),
        Param("angle_step", "Angle step", kind="number", default=5, minimum=0.5, maximum=45, unit="°", group="Rotation"),
        Param("pyramid", "Pyramid speed-up", kind="boolean", default=True, help_text="Search a quarter-size image first, then refine around the candidates. Turns itself off for very small templates.", group="Advanced"),
        Param("subpixel", "Sub-pixel refine", kind="boolean", default=True, help_text="Position comes from a 3×3 parabolic interpolation of the correlation map; with a rotation search the angle is interpolated from neighbouring scores, beating the angle step.", group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Search region (dynamic)", "region", required=False), Port("template_image", "Template picture", "image", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("matches", "Matches", "matches"), Port("count", "Count", "number"),
        Port("best_x", "Best X", "number"), Port("best_y", "Best Y", "number"),
        Port("best_score", "Best score", "number"), Port("best_angle", "Best angle", "number"),
    ]
    heavy = True

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        tpl = reference_image(ctx, "template_image", "template")
        region = ctx.roi()
        c = crop(image, region, upright=True)
        search = np.ascontiguousarray(c.image)
        if search.size == 0:
            raise ToolError("The search region falls outside the image")
        th, tw = tpl.shape[:2]
        if search.shape[0] < th or search.shape[1] < tw:
            raise ToolError(f"The search region {search.shape[1]}×{search.shape[0]} is smaller than the template {tw}×{th}")

        threshold = float(np.clip(ctx.number("threshold", 0.7), 0, 1))
        max_n = max(1, ctx.integer("max_matches", 1))
        angle_range = abs(ctx.number("angle_range", 0))
        angle_step = max(0.5, ctx.number("angle_step", 5))
        if angle_range > 0:
            angles = [float(a) for a in np.arange(-angle_range, angle_range + 1e-6, angle_step)]
            if 0.0 not in angles:
                angles.append(0.0)
        else:
            angles = [0.0]

        scale = 4
        use_pyramid = ctx.flag("pyramid", True) and min(th, tw) >= 32 and min(search.shape[:2]) >= scale * 8
        candidates: list[tuple[int, int, float, float, int, int]] = []  # x, y, score, angle, w, h（搜尋圖座標）
        if use_pyramid:
            small = cv2.resize(search, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
            tpl_small = cv2.resize(tpl, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
            coarse: list[tuple[int, int, float, float, int, int]] = []  # x, y, score, angle, rw, rh（縮圖座標）
            common = _inscribed_half(max(abs(a) for a in angles), tpl_small.shape[1], tpl_small.shape[0]) if len(angles) > 1 else None
            for angle in angles:
                rt, rm = _rotate_template(tpl_small, angle)
                ox = oy = 0
                if common is not None:
                    rt_c, ox, oy = _center_crop(rt, *common)
                    res = _match(small, rt_c, None)
                else:
                    res = _match(small, rt, rm)
                if res is None:
                    continue
                for x, y, s in _peaks(res, max(0.0, threshold - 0.15), max_n * 3, rt.shape[1], rt.shape[0]):
                    coarse.append((x - ox, y - oy, s, angle, rt.shape[1], rt.shape[0]))
            coarse.sort(key=lambda t: -t[2])
            # 剪枝：同一位置（中心距離 < 縮圖範本半尺寸）最多細找分數最高的 3 個角度，
            # 總數上限 max_n*4；避免 5 個角度在同一目標上各細找一次。
            selected: list[tuple[int, int, float, float, int, int]] = []
            locs: list[list[float]] = []  # cx, cy, count
            min_d_small = max(2.0, min(tpl_small.shape[:2]) / 2)
            for cand in coarse:
                ccx, ccy = cand[0] + cand[4] / 2, cand[1] + cand[5] / 2
                slot = next((loc for loc in locs if math.hypot(ccx - loc[0], ccy - loc[1]) < min_d_small), None)
                if slot is None:
                    locs.append([ccx, ccy, 1])
                elif slot[2] >= 3:
                    continue
                else:
                    slot[2] += 1
                selected.append(cand)
                if len(selected) >= max_n * 4:
                    break
            for x, y, _, angle, _, _ in selected:
                rt, rm = _rotate_template(tpl, angle)
                rh, rw = rt.shape[:2]
                pad = scale * 2
                x0, y0 = max(0, x * scale - pad), max(0, y * scale - pad)
                x1, y1 = min(search.shape[1], x * scale + rw + pad), min(search.shape[0], y * scale + rh + pad)
                window = search[y0:y1, x0:x1]
                res = _match(window, rt, rm)
                if res is None:
                    continue
                _, s, _, loc = cv2.minMaxLoc(res)
                if s >= threshold:
                    candidates.append((x0 + int(loc[0]), y0 + int(loc[1]), float(s), angle, rw, rh))
        else:
            for angle in angles:
                rt, rm = _rotate_template(tpl, angle)
                res = _match(search, rt, rm)
                if res is None:
                    continue
                for x, y, s in _peaks(res, threshold, max_n, rt.shape[1], rt.shape[0]):
                    candidates.append((x, y, s, angle, rt.shape[1], rt.shape[0]))

        # 跨角度的非極大抑制：中心距離小於範本半尺寸者視為同一目標
        candidates.sort(key=lambda t: -t[2])
        kept: list[tuple[int, int, float, float, int, int]] = []
        min_d = max(2.0, min(tw, th) / 2)
        for cand in candidates:
            cx, cy = cand[0] + cand[4] / 2, cand[1] + cand[5] / 2
            if all(math.hypot(cx - (k[0] + k[4] / 2), cy - (k[1] + k[5] / 2)) >= min_d for k in kept):
                kept.append(cand)
            if len(kept) >= max_n:
                break

        matches: list[dict[str, Any]] = []
        overlays: list[dict[str, Any]] = []
        if region is not None:
            overlays.append(region_overlay(region, label="search"))
        refine_step = angle_step if len(angles) > 1 else 0.0
        do_subpixel = ctx.flag("subpixel", True)
        for x, y, s, angle, rw, rh in kept:
            sx, sy = x + rw / 2, y + rh / 2
            if do_subpixel:
                sx, sy, s, angle = _refine_match(search, tpl, sx, sy, angle, s, refine_step)
            cx, cy = c.to_full(sx, sy)
            fx, fy = cx - tw / 2, cy - th / 2
            total_angle = angle + (float(region.get("angle", 0)) if region and region.get("shape") == "rotated_rect" else 0.0)
            matches.append({
                "x": round(fx, 2), "y": round(fy, 2), "w": tw, "h": th,
                "cx": round(cx, 2), "cy": round(cy, 2), "score": round(s, 4), "angle": round(total_angle, 2),
            })
            overlays.append({"kind": "rect", "x": cx - tw / 2, "y": cy - th / 2, "w": tw, "h": th, "angle": total_angle, "color": "#22c55e", "width": 2, "label": f"{s:.2f}"})
            overlays.append({"kind": "point", "x": cx, "y": cy, "color": "#22c55e"})
        best = matches[0] if matches else None
        return Result(
            outputs={
                "matches": matches, "count": len(matches),
                "best_x": best["cx"] if best else float("nan"), "best_y": best["cy"] if best else float("nan"),
                "best_score": best["score"] if best else 0.0, "best_angle": best["angle"] if best else 0.0,
            },
            overlays=overlays,
            branch="found" if matches else "not_found",
            status="ok" if matches else "ng",
            message=f"{len(matches)} matches" + (f", best {best['score']:.3f} @ ({best['cx']:.1f}, {best['cy']:.1f})" if best else ""),
        )


# ---------------------------------------------------------------------------
# 定位補正 / ROI 跟隨
# ---------------------------------------------------------------------------
def _current_pose(ctx: ToolContext) -> tuple[float, float, float]:
    matches = ctx.inputs.get("matches")
    if isinstance(matches, list) and matches:
        m = matches[0]
        if isinstance(m, dict):
            x = m.get("cx", m.get("x"))
            y = m.get("cy", m.get("y"))
            if x is not None and y is not None:
                return float(x), float(y), float(m.get("angle", 0) or 0)
    a, b, cc = ctx.inputs.get("a"), ctx.inputs.get("b"), ctx.inputs.get("c")
    if a is None or b is None:
        if "matches" in ctx.inputs or "a" in ctx.inputs or "b" in ctx.inputs:
            return math.nan, math.nan, 0.0  # 上游有接、只是這次沒找到：讓工具回 ng，不是 raise
        raise ToolError("No current position: wire matches, or a/b as X/Y")
    try:
        return float(a), float(b), float(cc or 0)
    except (TypeError, ValueError):
        raise ToolError("a, b and c must be numbers") from None


class ShapeAlignTool(Tool):
    key = "shape_align"
    label = "Locate offset"
    description = "Compares the current locate result with the reference position from teaching and produces the translation and rotation (dx, dy, dθ) that ROI follow needs."
    category = "locate"
    icon = "Move"
    params = [
        Param("ref_x", "Reference X", kind="number", required=True, default=0, help_text="The best match centre X at teach time (the editor can fill in the current value)."),
        Param("ref_y", "Reference Y", kind="number", required=True, default=0),
        Param("ref_angle", "Reference angle", kind="number", default=0, unit="°"),
        Param("use_angle", "Apply rotation", kind="boolean", default=True, help_text="Off pins dθ to 0 and corrects translation only."),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("a", "Current X", "number", required=False), Port("b", "Current Y", "number", required=False), Port("c", "Current angle", "number", required=False),
    ]
    outputs = [
        Port("dx", "dx", "number"), Port("dy", "dy", "number"), Port("dtheta", "dθ", "number"),
        Port("transform", "Transform", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        x, y, angle = _current_pose(ctx)
        if not all(np.isfinite([x, y])):
            # 找不到東西回 ng、不 raise（工具規則）：下游 ROI 跟隨拿到 None 會把區域留在原地
            return Result(outputs={"dx": None, "dy": None, "dtheta": None, "transform": None}, status="ng",
                          message="No current position: the locate step found nothing")
        rx, ry, ra = ctx.number("ref_x"), ctx.number("ref_y"), ctx.number("ref_angle")
        dx, dy = x - rx, y - ry
        dtheta = (angle - ra) if ctx.flag("use_angle", True) else 0.0
        dtheta = (dtheta + 180) % 360 - 180
        transform = {"dx": dx, "dy": dy, "dtheta": dtheta, "pivot": [rx, ry], "current": [x, y, angle]}
        overlays = [
            {"kind": "point", "x": rx, "y": ry, "color": "#38bdf8", "label": "ref"},
            {"kind": "point", "x": x, "y": y, "color": "#22c55e", "label": "now"},
            {"kind": "line", "x1": rx, "y1": ry, "x2": x, "y2": y, "color": "#f59e0b", "width": 2},
        ]
        return Result(outputs={"dx": dx, "dy": dy, "dtheta": dtheta, "transform": transform}, overlays=overlays,
                      message=f"dx={dx:.2f} dy={dy:.2f} dθ={dtheta:.2f}°")


class FixtureRoiTool(Tool):
    key = "fixture_roi"
    label = "ROI follow"
    description = "Moves a drawn ROI by the dx, dy and dθ from the locate step and feeds the resulting dynamic region into a downstream tool's region input."
    category = "locate"
    icon = "Locate"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["rect", "rotated_rect", "circle", "annulus", "polygon", "line"]),
    ]
    inputs = [Port("image", "Image", "image", required=False), Port("transform", "Transform", "any")]
    outputs = [Port("region", "Region", "region")]

    def execute(self, ctx: ToolContext) -> Result:
        region = ctx.params.get("roi")
        if not isinstance(region, dict) or not region.get("shape"):
            raise ToolError("No region is set")
        t = ctx.inputs.get("transform")
        if t is None and "transform" in ctx.inputs:
            # 定位補正這次沒找到（回 None）：區域留在原地、標 ng，下游量測照跑但整次 run 是 NG
            return Result(outputs={"region": region}, overlays=[region_overlay(region, color="#ef4444", label="not moved")], status="ng",
                          message="No transform (the locate step found nothing); region left in place")
        if not isinstance(t, dict):
            raise ToolError("The transform input must come from a locate-offset step")
        try:
            dx, dy, dtheta = float(t.get("dx", 0)), float(t.get("dy", 0)), float(t.get("dtheta", 0))
        except (TypeError, ValueError):
            raise ToolError("The transform values are not numbers") from None
        pivot = t.get("pivot")
        pivot_t = (float(pivot[0]), float(pivot[1])) if isinstance(pivot, (list, tuple)) and len(pivot) == 2 else region_center(region)
        moved = transform_region(region, dx, dy, dtheta, pivot=pivot_t)
        overlays = [region_overlay(region, color="#94a3b8", label="Original ROI")]
        moved_ov = region_overlay(moved, color="#22c55e", label="Following")
        moved_ov["dash"] = False
        moved_ov["width"] = 2
        overlays.append(moved_ov)
        return Result(outputs={"region": moved}, overlays=overlays, message=f"dx={dx:.1f} dy={dy:.1f} dθ={dtheta:.1f}°")


class ImageFixtureTool(Tool):
    key = "image_fixture"
    label = "Image follow"
    description = (
        "Turns the picture back to the pose the flow was taught on, using the offset from a locate step. Everything downstream "
        "then sees the part in the same place every time, which is the easy way to reuse a flow that was set up on one sample: "
        "no region needs to follow, and a taught template still matches."
    )
    category = "locate"
    icon = "Frame"
    params = [
        Param("border", "Fill the edges with", kind="select", default="black", options=[
            {"value": "black", "label": "Black"},
            {"value": "white", "label": "White"},
            {"value": "replicate", "label": "The nearest pixel"},
        ], help_text="Turning the picture leaves empty corners; this is what goes in them."),
        Param("smooth", "Smooth the pixels", kind="boolean", default=True,
              help_text="On: interpolate, which looks right and measures better. Off: nearest pixel, which keeps labels and masks crisp."),
    ]
    inputs = [Port("image", "Image", "image"), Port("transform", "Transform", "any")]
    outputs = [
        Port("image", "Image", "image"),
        Port("dx", "dx", "number"), Port("dy", "dy", "number"), Port("dtheta", "d angle", "number"),
    ]
    accepts = ("u8", "u16", "f32")

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        t = ctx.inputs.get("transform")
        if t is None:
            # 定位這次沒找到：影像原樣傳下去、標 ng（下游照跑，整次 run 是 NG）
            return Result(outputs={"image": image, "dx": 0.0, "dy": 0.0, "dtheta": 0.0}, status="ng",
                          message="No transform (the locate step found nothing); picture left as it is")
        if not isinstance(t, dict):
            raise ToolError("The transform input must come from a locate-offset step")
        try:
            dx, dy = float(t.get("dx", 0) or 0), float(t.get("dy", 0) or 0)
            dtheta = float(t.get("dtheta", 0) or 0)
        except (TypeError, ValueError):
            raise ToolError("The transform values are not numbers") from None
        pivot = t.get("pivot")
        at = (float(pivot[0]), float(pivot[1])) if isinstance(pivot, (list, tuple)) and len(pivot) == 2 else (image.shape[1] / 2, image.shape[0] / 2)
        matrix = inverse_matrix(dx, dy, dtheta, at)
        border, value = _BORDERS.get(str(ctx.param("border", "black")), (cv2.BORDER_CONSTANT, 0))
        if str(ctx.param("border", "black")) == "white":
            value = 255 if image.dtype == np.uint8 else float(np.iinfo(image.dtype).max if image.dtype.kind in "ui" else 1.0)
        flags = cv2.INTER_LINEAR if ctx.flag("smooth", True) else cv2.INTER_NEAREST
        out = cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]), flags=flags, borderMode=border, borderValue=value)
        return Result(
            outputs={"image": out, "dx": dx, "dy": dy, "dtheta": dtheta},
            message=f"back by dx={dx:.1f} dy={dy:.1f} dθ={dtheta:.1f}°",
        )


#: image_fixture 的邊界填法。
_BORDERS = {"black": (cv2.BORDER_CONSTANT, 0), "white": (cv2.BORDER_CONSTANT, 255), "replicate": (cv2.BORDER_REPLICATE, 0)}


def inverse_matrix(dx: float, dy: float, dtheta: float, pivot: tuple[float, float]) -> np.ndarray:
    """把「工件從教導姿態移動了多少」反過來，得到 warpAffine 用的 2x3 矩陣。

    正向（`roi.transform_region` 的做法）是：先繞 pivot 轉 dtheta（畫面順時針為正，所以
    `getRotationMatrix2D` 傳 −dtheta），再平移 (dx, dy)。這裡回的是它的反矩陣，
    warpAffine 套上去就把影像轉回教導時的位置。
    """
    forward = np.eye(3, dtype=np.float64)
    forward[:2] = cv2.getRotationMatrix2D(pivot, -float(dtheta), 1.0)
    move = np.eye(3, dtype=np.float64)
    move[0, 2], move[1, 2] = float(dx), float(dy)
    return np.linalg.inv(move @ forward)[:2].astype(np.float32)


# ---------------------------------------------------------------------------
# 找圓
# ---------------------------------------------------------------------------
class FindCircleTool(Tool):
    key = "find_circle"
    label = "Find circles"
    description = "Fires radial scan lines out from the ROI centre to find edge points, then fits a circle by least squares or RANSAC."
    category = "locate"
    icon = "Circle"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["circle", "annulus", "rect"], help_text="Circle or ring: scan outwards to the outer radius (a ring may set start and end angles to scan only that sector). Rectangle: scan to the inscribed radius."),
        Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, help_text="How the grey level changes along the scan line, inside out."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, help_text="A grey gradient below this is not an edge.", teach=True),
        Param("num_rays", "Scan lines", kind="number", default=36, minimum=6, maximum=720),
        Param("edge_select", "Which edge", kind="select", default="strongest", options=[{"value": "strongest", "label": "Strongest"}, {"value": "first", "label": "First (innermost)"}, {"value": "last", "label": "Last (outermost)"}]),
        Param("ransac", "RANSAC outlier rejection", kind="boolean", default=True),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=2, minimum=0.5, maximum=50, unit="px", group="Advanced"),
        Param("refine", "Rescan refine", kind="boolean", default=True, group="Advanced", help_text="When the ROI centre is off the circle, rescan from the fitted centre so the scan lines meet the edge square on."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"), Port("r", "Radius", "number"),
        Port("points", "Edge points", "points"), Port("score", "Score", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        shape = region.get("shape")
        cx, cy = region_center(region)
        a0 = a1 = None
        if shape == "circle":
            r_in, r_out = 0.0, float(region["r"])
        elif shape == "annulus":
            r_in, r_out = float(region["r_inner"]), float(region["r_outer"])
            a0, a1 = region.get("a0"), region.get("a1")
        elif shape == "rect":
            r_in, r_out = 0.0, min(float(region["w"]), float(region["h"])) / 2
        elif shape == "composite":
            # 組合區域：從遮罩重心往外掃到外框的內切半徑
            x0, y0, x1, y1 = extent(region)
            r_in, r_out = 0.0, min(x1 - x0, y1 - y0) / 2
        else:
            raise ToolError(f"Find circle does not support a {shape} region")
        if r_out - r_in < 3:
            raise ToolError("The region radius is too small")
        num_rays = max(6, ctx.integer("num_rays", 36))
        polarity = ctx.param("polarity", "any")
        thr = ctx.number("edge_threshold", 20)
        sel = ctx.param("edge_select", "strongest")
        smoothing = ctx.integer("smoothing", 3)
        use_ransac, tol = ctx.flag("ransac", True), ctx.number("ransac_tol", 2)

        def scan(ox: float, oy: float) -> np.ndarray:
            return np.asarray(radial_edge_points(image, ox, oy, r_in, r_out, num_rays, polarity, thr, sel, smoothing, a0=a0, a1=a1), dtype=np.float64).reshape(-1, 2)

        arr = scan(cx, cy)
        overlays = [region_overlay(region, label="roi")]
        nan = float("nan")
        if len(arr) < 3:
            return Result(outputs={"cx": nan, "cy": nan, "r": nan, "points": arr.round(2).tolist(), "score": 0.0},
                          overlays=overlays, branch="not_found", status="ng", message=f"Too few edge points ({len(arr)})")
        circle, inliers = fit_circle_points(arr, use_ransac, tol)
        # 重掃精修：ROI 中心偏離圓心時掃描線斜切邊緣；改從擬合圓心再掃一次，掃描線與邊緣垂直。
        if circle is not None and ctx.flag("refine", True) and math.hypot(circle[0] - cx, circle[1] - cy) > 0.5:
            arr2 = scan(circle[0], circle[1])
            if len(arr2) >= 3:
                circle2, inliers2 = fit_circle_points(arr2, use_ransac, tol)
                if circle2 is not None and int(inliers2.sum()) >= int(inliers.sum()):
                    arr, circle, inliers = arr2, circle2, inliers2
        if circle is None:
            return Result(outputs={"cx": nan, "cy": nan, "r": nan, "points": arr.round(2).tolist(), "score": 0.0},
                          overlays=overlays, branch="not_found", status="ng", message="Fit failed")
        fcx, fcy, fr = circle
        resid = np.abs(np.hypot(arr[:, 0] - fcx, arr[:, 1] - fcy) - fr)
        score = float(inliers.sum() / num_rays)
        overlays += [
            {"kind": "points", "points": arr[inliers].round(2).tolist(), "color": "#22c55e"},
            {"kind": "points", "points": arr[~inliers].round(2).tolist(), "color": "#ef4444"},
            {"kind": "circle", "cx": fcx, "cy": fcy, "r": fr, "color": "#22c55e", "width": 2, "label": f"r={fr:.1f}"},
            {"kind": "line", "x1": fcx - 6, "y1": fcy, "x2": fcx + 6, "y2": fcy, "color": "#22c55e"},
            {"kind": "line", "x1": fcx, "y1": fcy - 6, "x2": fcx, "y2": fcy + 6, "color": "#22c55e"},
        ]
        return Result(
            outputs={"cx": fcx, "cy": fcy, "r": fr, "points": arr.round(2).tolist(), "score": score},
            overlays=overlays, branch="found",
            message=f"Centre ({fcx:.1f}, {fcy:.1f}) r={fr:.1f}, {int(inliers.sum())}/{num_rays} points, residual {float(resid[inliers].mean()):.2f}px",
            detail={"rms": float(np.sqrt((resid[inliers] ** 2).mean()))},
        )


# ---------------------------------------------------------------------------
# 找直線
# ---------------------------------------------------------------------------
def _as_rotated_rect(region: dict[str, Any]) -> dict[str, Any]:
    if region.get("shape") == "rect":
        return {"shape": "rotated_rect", "cx": region["x"] + region["w"] / 2, "cy": region["y"] + region["h"] / 2, "w": region["w"], "h": region["h"], "angle": 0.0}
    if region.get("shape") == "rotated_rect":
        return region
    if region.get("shape") == "composite":
        # 組合區域：矩形類工具用它的外框（挖除項不擴大外框）
        x0, y0, x1, y1 = extent(region)
        if x1 - x0 < 1 or y1 - y0 < 1:
            raise ToolError("The combined region is empty")
        return {"shape": "rotated_rect", "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "w": x1 - x0, "h": y1 - y0, "angle": 0.0}
    raise ToolError(f"This tool needs a rectangle or rotated rectangle, got {region.get('shape')}")


def pick_pair(edges: list[tuple[float, float]], mode: str, pair_polarity: str, expected: float) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """依模式挑一對邊緣。pair_polarity 限制兩個邊緣的梯度符號（亮條＝先正後負、暗條＝先負後正）；
    expected > 0 時改挑寬度最接近期望值的一對（同寬時取較強者）。"""
    if pair_polarity == "any":
        cands = [(a, b) for i, a in enumerate(edges) for b in edges[i + 1 :]]
    else:
        first_pos = pair_polarity == "bright"
        cands = [(a, b) for i, a in enumerate(edges) for b in edges[i + 1 :] if (a[1] > 0) == first_pos and (b[1] > 0) != first_pos]
    if not cands:
        return None
    if expected > 0:
        return min(cands, key=lambda p: (abs((p[1][0] - p[0][0]) - expected), -(abs(p[0][1]) + abs(p[1][1]))))
    if pair_polarity == "any":
        if mode == "narrowest":
            return min(zip(edges[:-1], edges[1:]), key=lambda p: p[1][0] - p[0][0])
        if mode == "strongest":
            top = sorted(edges, key=lambda e: -abs(e[1]))[:2]
            return tuple(sorted(top, key=lambda e: e[0]))  # type: ignore[return-value]
        return edges[0], edges[-1]
    if mode == "narrowest":
        return min(cands, key=lambda p: p[1][0] - p[0][0])
    if mode == "strongest":
        return max(cands, key=lambda p: abs(p[0][1]) + abs(p[1][1]))
    if mode == "widest":
        return max(cands, key=lambda p: p[1][0] - p[0][0])
    first = cands[0][0]
    return first, max((b for a, b in cands if a is first), key=lambda e: e[0])


def caliper_points(crop_img: np.ndarray, num: int, polarity: str, threshold: float, direction: str, smoothing: int) -> tuple[list[tuple[float, float, float]], bool]:
    """在擺正的 crop 內，沿長邊等距放 num 條卡尺（垂直於長邊），每條回傳 (x, y, 強度)。

    回傳 (points, horizontal)：horizontal=True 表示長邊為水平、卡尺沿 y 掃描。
    """
    h, w = crop_img.shape[:2]
    horizontal = w >= h
    length = w if horizontal else h
    num = max(2, min(num, length))
    band = max(1, length // num)
    centers = np.linspace(band / 2, length - band / 2, num)
    # 每條卡尺的剖面 = 帶內像素沿長邊平均；用長邊方向的累積和一次算完所有帶（整數和在 float64 精確）。
    csum = np.cumsum(crop_img, axis=1 if horizontal else 0, dtype=np.float64)
    a_idx = np.array([int(max(0, c - band / 2)) for c in centers])
    b_idx = np.array([int(min(length, c + band / 2 + 1)) for c in centers])
    if horizontal:
        hi = csum[:, b_idx - 1]                       # (h, num)
        lo = np.where(a_idx > 0, csum[:, np.maximum(a_idx - 1, 0)], 0.0)
        profiles = ((hi - lo) / (b_idx - a_idx)[None, :]).T  # (num, h)
    else:
        hi = csum[b_idx - 1, :]
        lo = np.where((a_idx > 0)[:, None], csum[np.maximum(a_idx - 1, 0), :], 0.0)
        profiles = (hi - lo) / (b_idx - a_idx)[:, None]   # (num, w)
    pts: list[tuple[float, float, float]] = []
    for cpos, edges in zip(centers, find_edges_rows(profiles, polarity, threshold, smoothing)):
        e = pick_edge(edges, direction)
        if e is None:
            continue
        if horizontal:
            pts.append((float(cpos), e[0], e[1]))
        else:
            pts.append((e[0], float(cpos), e[1]))
    return pts, horizontal


# ---------------------------------------------------------------------------
# 通用卡尺序列：沿一條幾何等距佈卡尺
# ---------------------------------------------------------------------------
@dataclass
class CaliperHit:
    """一把卡尺的結果（全圖座標）。

    `found=False` 表示這把打空——**打空本身就是缺陷訊號**（大缺口會讓卡尺完全找不到邊），
    所以不要把它濾掉，座標與強度留 NaN 讓下游決定。
    `offset` 是邊緣相對卡尺中線的位移（沿掃描方向為正），量偏移與階差用它比座標好用。
    邊緣對模式才有 `x2/y2/strength2/width`（width 是兩邊之間的距離，px）。
    """

    index: int
    #: 卡尺沿幾何的位置：直線是離起點的弧長（px），圓弧是角度（度，畫面順時針為正）
    position: float
    #: 卡尺中心（全圖座標）
    cx: float
    cy: float
    found: bool = False
    x: float = float("nan")
    y: float = float("nan")
    strength: float = float("nan")
    offset: float = float("nan")
    x2: float = float("nan")
    y2: float = float("nan")
    strength2: float = float("nan")
    width: float = float("nan")


def line_geometry(x1: float, y1: float, x2: float, y2: float, count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """沿線段等距佈 count 把卡尺：回 (中心點 (N,2), 掃描方向 (N,2), 切向 (N,2), 位置 (N,))。

    **掃描方向＝線方向順時針轉 90°**（(dx,dy) → (−dy,dx)，影像 y 向下，與平台「角度正值＝畫面順時針」同一慣例）：
    沿 +x 的線往 +y（畫面下方）掃，沿 +y 的線往 −x 掃。要往反方向掃就把線的起訖點對調。
    位置回傳離起點的弧長（px）。"""
    p1 = np.array([float(x1), float(y1)])
    p2 = np.array([float(x2), float(y2)])
    length = float(np.hypot(*(p2 - p1)))
    if length < 1e-6:
        raise ToolError("The line is too short to place calipers on")
    n = max(1, int(count))
    t = np.linspace(0.0, 1.0, n) if n > 1 else np.array([0.5])
    centers = p1[None, :] + t[:, None] * (p2 - p1)[None, :]
    along = (p2 - p1) / length
    normal = np.array([-along[1], along[0]])
    return centers, np.tile(normal, (n, 1)), np.tile(along, (n, 1)), t * length


def arc_geometry(cx: float, cy: float, radius: float, count: int, a0: float | None = None, a1: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """沿圓（或扇形 a0→a1，度、畫面順時針為正）等距佈 count 把卡尺：掃描方向＝徑向（向外為正），
    切向＝圓周方向。位置回傳角度（度）。"""
    thetas = sector_thetas(max(1, int(count)), a0, a1).astype(np.float64)
    cos_t, sin_t = np.cos(thetas), np.sin(thetas)
    radial = np.stack([cos_t, sin_t], axis=1)
    tangent = np.stack([-sin_t, cos_t], axis=1)
    centers = np.array([float(cx), float(cy)])[None, :] + radial * float(radius)
    return centers, radial, tangent, np.degrees(thetas)


def caliper_series(
    image: np.ndarray,
    centers: np.ndarray,
    scan: np.ndarray,
    tangent: np.ndarray,
    positions: np.ndarray,
    *,
    search: float,
    height: float = 1.0,
    polarity: str = "any",
    threshold: float = 20.0,
    smoothing: int = 3,
    mode: str = "single",
    select: str = "strongest",
    pair_mode: str = "first_last",
    pair_polarity: str = "any",
    expected_width: float = 0.0,
) -> list[CaliperHit]:
    """沿一條幾何佈好的卡尺一次全掃：每把在掃描方向取 `search` px 的剖面（切向平均 `height` px 降噪），
    找一個邊（mode="single"）或一對邊（mode="pair"），回全圖座標。

    幾何由 `centers`／`scan`／`tangent`／`positions` 四個陣列描述（用 `line_geometry`／`arc_geometry` 產生，
    折線與任意路徑自己組也可以），所以直線、圓弧、路徑共用同一條程式路徑。取樣是一次 `cv2.remap`
    ((N×height) × samples)、找邊是一次 `find_edges_rows`——180 把卡尺也只有兩次呼叫。

    找不到邊的卡尺**照樣回傳**（`found=False`），因為打空是缺陷判斷的訊號之一。
    """
    img = to_gray(image)
    n = len(centers)
    if n == 0:
        return []
    span = max(2.0, float(search))
    samples = int(math.ceil(span)) + 1
    offsets = np.linspace(-span / 2.0, span / 2.0, samples)
    rows = max(1, int(round(float(height))))
    tang = (np.arange(rows, dtype=np.float64) - (rows - 1) / 2.0)
    # (N, rows, samples) 的取樣格：中心 + 掃描方向×位移 + 切向×降噪位移
    cx = centers[:, 0][:, None, None] + scan[:, 0][:, None, None] * offsets[None, None, :] + tangent[:, 0][:, None, None] * tang[None, :, None]
    cy = centers[:, 1][:, None, None] + scan[:, 1][:, None, None] * offsets[None, None, :] + tangent[:, 1][:, None, None] * tang[None, :, None]
    sampled = cv2.remap(img, cx.astype(np.float32).reshape(-1, samples), cy.astype(np.float32).reshape(-1, samples),
                        cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    profiles = sampled.reshape(n, rows, samples).astype(np.float32).mean(axis=1)
    step = span / max(1, samples - 1)

    def at(i: int, pos: float) -> tuple[float, float, float]:
        """剖面上的次像素位置 → (x, y, 相對中線的位移)。"""
        off = -span / 2.0 + pos * step
        return float(centers[i, 0] + scan[i, 0] * off), float(centers[i, 1] + scan[i, 1] * off), float(off)

    out: list[CaliperHit] = []
    for i, edges in enumerate(find_edges_rows(profiles, polarity, threshold, smoothing)):
        hit = CaliperHit(index=i, position=float(positions[i]), cx=float(centers[i, 0]), cy=float(centers[i, 1]))
        if mode == "pair":
            pair = pick_pair(edges, pair_mode, pair_polarity, float(expected_width))
            if pair is not None:
                (p0, s0), (p1, s1) = pair
                x0, y0, o0 = at(i, p0)
                x1, y1, o1 = at(i, p1)
                hit.found = True
                hit.x, hit.y, hit.strength, hit.offset = x0, y0, float(s0), o0
                hit.x2, hit.y2, hit.strength2 = x1, y1, float(s1)
                hit.width = abs(o1 - o0)
        else:
            e = pick_edge(edges, select)
            if e is not None:
                x0, y0, o0 = at(i, e[0])
                hit.found = True
                hit.x, hit.y, hit.strength, hit.offset = x0, y0, float(e[1]), o0
        out.append(hit)
    return out


def hit_points(hits: list[CaliperHit], *, second: bool = False) -> list[list[float]]:
    """找到邊的那些卡尺的點（全圖座標）；`second=True` 取邊緣對的第二個邊。"""
    if second:
        return [[h.x2, h.y2] for h in hits if h.found]
    return [[h.x, h.y] for h in hits if h.found]


def hit_series(hits: list[CaliperHit], field: str = "offset") -> list[float | None]:
    """把一串卡尺結果變成一維序列（給 tools/defects.py 的分段用）；打空的位置是 None。"""
    return [float(getattr(h, field)) if h.found else None for h in hits]


class FindLineTool(Tool):
    key = "find_line"
    label = "Find lines"
    description = "Places caliper scan lines across the long side of a rectangle to find edge points, then fits a line, optionally with RANSAC."
    category = "locate"
    icon = "Slash"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["rotated_rect", "rect"], help_text="The long side is the line direction; calipers scan across the short side."),
        Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, help_text="How the grey level changes across the short side (top to bottom / left to right)."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("num_calipers", "Calipers", kind="number", default=20, minimum=2, maximum=500),
        Param("direction", "Which edge", kind="select", default="strongest", options=[{"value": "first", "label": "First"}, {"value": "last", "label": "Last"}, {"value": "strongest", "label": "Strongest"}]),
        Param("ransac", "RANSAC outlier rejection", kind="boolean", default=True),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=2, minimum=0.5, maximum=50, unit="px", group="Advanced"),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("x1", "X1", "number"), Port("y1", "Y1", "number"), Port("x2", "X2", "number"), Port("y2", "Y2", "number"),
        Port("angle", "Angle", "number"), Port("rho", "ρ", "number"), Port("theta", "θ", "number"),
        Port("line", "Line", "any"), Port("points", "Edge points", "points"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("The region is too small or falls outside the image")
        pts_local, horizontal = caliper_points(
            c.image, ctx.integer("num_calipers", 20), ctx.param("polarity", "any"),
            ctx.number("edge_threshold", 20), ctx.param("direction", "strongest"), ctx.integer("smoothing", 3),
        )
        overlays = [region_overlay(region, label="roi")]
        nan_out = {k: float("nan") for k in ("x1", "y1", "x2", "y2", "angle", "rho", "theta")}
        if len(pts_local) < 2:
            return Result(outputs={**nan_out, "line": None, "points": []}, overlays=overlays, branch="not_found", status="ng", message=f"Too few edge points ({len(pts_local)})")
        full = c.points_to_full(np.asarray([(p[0], p[1]) for p in pts_local]))
        inliers = np.ones(len(full), dtype=bool)
        if ctx.flag("ransac", True) and len(full) >= 3:
            fitted = fit_line_ransac(full, tol=ctx.number("ransac_tol", 2))
            if fitted is not None:
                (vx, vy, x0, y0), inliers = fitted
            else:
                vx, vy, x0, y0 = cv2.fitLine(full.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).reshape(-1)
        else:
            vx, vy, x0, y0 = cv2.fitLine(full.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).reshape(-1)
        vx, vy, x0, y0 = float(vx), float(vy), float(x0), float(y0)
        # 端點：把 ROI 長邊兩端投影到直線上
        half = (rr["w"] if horizontal else rr["h"]) / 2
        ang = math.radians(float(rr.get("angle", 0)))
        ux, uy = (math.cos(ang), math.sin(ang)) if horizontal else (-math.sin(ang), math.cos(ang))
        ends = []
        for s in (-half, half):
            px, py = rr["cx"] + ux * s, rr["cy"] + uy * s
            t = (px - x0) * vx + (py - y0) * vy
            ends.append((x0 + vx * t, y0 + vy * t))
        (x1, y1), (x2, y2) = ends
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        # 法線式 ρ = x cosθ + y sinθ
        nx, ny = -vy, vx
        rho = x0 * nx + y0 * ny
        theta = math.degrees(math.atan2(ny, nx))
        if rho < 0:
            rho, theta = -rho, theta + 180
        theta = (theta + 180) % 360 - 180
        line = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "angle": angle}
        dist = np.abs((full[:, 0] - x0) * nx + (full[:, 1] - y0) * ny)
        overlays += [
            {"kind": "points", "points": full[inliers].round(2).tolist(), "color": "#22c55e"},
            {"kind": "points", "points": full[~inliers].round(2).tolist(), "color": "#ef4444"},
            {"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": "#22c55e", "width": 2, "label": f"{angle:.2f}°"},
        ]
        return Result(
            outputs={"x1": x1, "y1": y1, "x2": x2, "y2": y2, "angle": angle, "rho": rho, "theta": theta, "line": line, "points": full.round(2).tolist()},
            overlays=overlays, branch="found",
            message=f"Angle {angle:.2f}°, {int(inliers.sum())}/{len(full)} points, residual {float(dist[inliers].mean()):.2f}px",
        )


# ---------------------------------------------------------------------------
# Hough
# ---------------------------------------------------------------------------
class HoughCirclesTool(Tool):
    key = "hough_circles"
    label = "Hough circles"
    description = "Finds several circles in the region with the Hough gradient method."
    category = "locate"
    icon = "CircleDot"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect"], help_text="Leave blank for the whole image."),
        Param("min_radius", "Min radius", kind="number", default=10, minimum=1, unit="px"),
        Param("max_radius", "Max radius", kind="number", default=100, minimum=1, unit="px"),
        Param("min_dist", "Min centre spacing", kind="number", default=20, minimum=1, unit="px"),
        Param("param1", "Canny high", kind="number", default=100, minimum=1, maximum=500, group="Advanced"),
        Param("param2", "Accumulator threshold", kind="number", default=30, minimum=1, maximum=300, group="Advanced", help_text="Lower finds more, false positives included."),
        Param("blur", "Pre-median kernel", kind="number", default=5, minimum=0, maximum=31, group="Advanced"),
        Param("max_count", "Max results", kind="number", default=50, minimum=1, maximum=1000),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("circles", "Circle", "list"), Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        sub = np.ascontiguousarray(c.image)
        k = ctx.integer("blur", 5)
        if k >= 3:
            sub = cv2.medianBlur(sub, k | 1)
        min_r, max_r = ctx.integer("min_radius", 10), ctx.integer("max_radius", 100)
        found = cv2.HoughCircles(sub, cv2.HOUGH_GRADIENT, 1, max(1, ctx.number("min_dist", 20)),
                                 param1=max(1, ctx.number("param1", 100)), param2=max(1, ctx.number("param2", 30)),
                                 minRadius=min(min_r, max_r), maxRadius=max(min_r, max_r))
        circles: list[dict[str, float]] = []
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if found is not None:
            for x, y, r in found[0][: ctx.integer("max_count", 50)]:
                fx, fy = c.to_full(float(x), float(y))
                circles.append({"cx": round(fx, 2), "cy": round(fy, 2), "r": round(float(r), 2)})
                overlays.append({"kind": "circle", "cx": fx, "cy": fy, "r": float(r), "color": "#22c55e", "width": 2})
        return Result(outputs={"circles": circles, "count": len(circles)}, overlays=overlays,
                      branch="found" if circles else "not_found", status="ok" if circles else "ng", message=f"{len(circles)} circles")


class HoughLinesTool(Tool):
    key = "hough_lines"
    label = "Hough segments"
    description = "Canny edges followed by the probabilistic Hough transform to find line segments."
    category = "locate"
    icon = "Spline"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect"], help_text="Leave blank for the whole image."),
        Param("canny_low", "Canny low", kind="number", default=50, minimum=0, maximum=500),
        Param("canny_high", "Canny high", kind="number", default=150, minimum=0, maximum=500),
        Param("threshold", "Accumulator threshold", kind="number", default=80, minimum=1, maximum=1000),
        Param("min_length", "Min segment length", kind="number", default=30, minimum=1, unit="px"),
        Param("max_gap", "Max gap", kind="number", default=10, minimum=0, unit="px"),
        Param("max_count", "Max results", kind="number", default=50, minimum=1, maximum=1000),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("lines", "Segments", "list"), Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        edges = cv2.Canny(np.ascontiguousarray(c.image), ctx.number("canny_low", 50), ctx.number("canny_high", 150))
        if c.mask is not None:
            edges = cv2.bitwise_and(edges, c.mask)
        found = cv2.HoughLinesP(edges, 1, np.pi / 180, max(1, ctx.integer("threshold", 80)),
                                minLineLength=ctx.number("min_length", 30), maxLineGap=ctx.number("max_gap", 10))
        lines: list[dict[str, float]] = []
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if found is not None:
            segs = found.reshape(-1, 4).astype(np.float64)
            lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
            for i in np.argsort(-lengths)[: ctx.integer("max_count", 50)]:
                x1, y1 = c.to_full(segs[i, 0], segs[i, 1])
                x2, y2 = c.to_full(segs[i, 2], segs[i, 3])
                ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
                lines.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "length": round(float(lengths[i]), 2), "angle": round(ang, 2)})
                overlays.append({"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": "#22c55e", "width": 2})
        return Result(outputs={"lines": lines, "count": len(lines)}, overlays=overlays,
                      branch="found" if lines else "not_found", status="ok" if lines else "ng", message=f"{len(lines)} segments")


__all__ = ["Crop", "to_gray", "read_asset_image", "clear_asset_cache", "find_edges_1d", "find_edges_rows", "pick_edge", "caliper_points", "sector_thetas", "radial_edge_points", "fit_circle_kasa", "fit_circle_lsq", "fit_circle_ransac", "fit_circle_points", "fit_line_ransac", "POLARITY_OPTIONS"]

TOOLS = [
    TemplateMatchTool(), ShapeAlignTool(), FixtureRoiTool(), ImageFixtureTool(),
    FindCircleTool(), FindLineTool(), HoughCirclesTool(), HoughLinesTool(),
]
