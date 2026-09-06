"""形狀比對（geometric matching）：以邊緣梯度方向為特徵的範本建模與搜尋。

template_match（NCC）在光照變化、部分遮擋、雜亂背景下會失效；這裡的相似度是**梯度方向內積**：
    score(pose) = (1/n) Σ_i cos(θ_model,i − θ_search,T(p_i))        （use_polarity）
                = (1/n) Σ_i |cos(…)|                                （ignore_polarity，黑白反轉的件）
對線性／非線性光照免疫，對遮擋線性衰減（遮 30% 分數掉 0.3）。

模型（apps/vision/shapemodel.py, npz 資產 kind="file"）：金字塔各層的邊緣點（相對模型重心）與單位梯度方向。
搜尋：最上層窮舉（位置 × 角度 × 尺度，以「逐點平移切片累加」一次算出整張分數圖）→ 逐層在候選鄰域細化
（一批姿態向量化 gather，分塊累加做提早中止）→ 最底層拋物線次像素 → NMS。

座標慣例：角度正值＝畫面順時針（影像座標 y 向下，直接用 cos/sin 旋轉即符合）。
"""

from __future__ import annotations

import io
import json
import math
import os
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

VERSION = 1
MAX_LEVELS = 6
MIN_TOP_POINTS = 30


class ShapeModelError(ValueError):
    """建模／載入的可預期錯誤（訊息給使用者看）。"""


# ---------------------------------------------------------------------------
# 建模
# ---------------------------------------------------------------------------
def gradient_field(gray: np.ndarray, min_contrast: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sobel 梯度 → (ux, uy, mag)：ux／uy 為單位方向（mag < min_contrast 的位置為 0，不參與計分）。"""
    f = gray if gray.dtype == np.float32 else gray.astype(np.float32)
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3, scale=1.0 / 8.0)
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3, scale=1.0 / 8.0)
    mag = cv2.magnitude(gx, gy)
    safe = np.maximum(mag, np.float32(1e-6))
    ux = cv2.divide(gx, safe)
    uy = cv2.divide(gy, safe)
    weak = mag < np.float32(min_contrast)
    ux[weak] = 0.0
    uy[weak] = 0.0
    return ux, uy, mag


def _auto_thresholds(mag: np.ndarray) -> tuple[float, float]:
    """Otsu on gradient magnitude → (low, high)：high＝Otsu，low＝high/2（Canny 慣用比例）。"""
    m = np.clip(mag, 0, 255).astype(np.uint8)
    high, _ = cv2.threshold(m, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    high = max(8.0, float(high))
    return high / 2.0, high


def extract_edges(gray: np.ndarray, contrast_low: float | None, contrast_high: float | None, min_contrast: float, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """一層的邊緣點：Canny 細化的邊緣像素（雙門檻）＋該像素的單位梯度方向。回 (pts (N,2) float32, dirs (N,2) float32, (low, high))。"""
    ux, uy, mag = gradient_field(gray, 0.0)
    if contrast_low is None or contrast_high is None:
        low, high = _auto_thresholds(mag)
    else:
        low, high = float(contrast_low), float(contrast_high)
    # Canny 對 Sobel 幅值做非極大抑制與遲滯；門檻對應 3×3 Sobel 未縮放的幅值（×8）
    edges = cv2.Canny(gray if gray.dtype == np.uint8 else np.clip(gray, 0, 255).astype(np.uint8), low * 8.0, high * 8.0, L2gradient=True)
    keep = edges > 0
    if mask is not None:
        keep &= mask > 0
    keep &= mag >= np.float32(min_contrast)
    ys, xs = np.nonzero(keep)
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    dirs = np.stack([ux[ys, xs], uy[ys, xs]], axis=1).astype(np.float32)
    return pts, dirs, (low, high)


def _subsample(pts: np.ndarray, dirs: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    if len(pts) <= max_points:
        return pts, dirs
    idx = np.linspace(0, len(pts) - 1, max_points).round().astype(int)
    return pts[idx], dirs[idx]


def teach(template: np.ndarray, *, mask: np.ndarray | None = None, contrast_low: float | None = None, contrast_high: float | None = None,
          min_contrast: float = 10.0, pyramid_levels: int = 0, max_points: int = 1024, angle_start: float = -180.0, angle_extent: float = 360.0,
          scale_min: float = 1.0, scale_max: float = 1.0) -> dict[str, Any]:
    """範本影像（灰階，已裁 ROI）→ 模型 payload。

    每層：邊緣點座標相對「第 0 層邊緣點重心」（各層等比縮小）、單位方向；層數 auto＝到最上層邊緣點 < MIN_TOP_POINTS 為止，上限 6。
    mask 給定時（排除區）只取遮罩內的邊緣。
    """
    gray = template if template.ndim == 2 else cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        from apps.vision.tools import imgfmt

        gray = imgfmt.normalize_u8(gray)
    if min(gray.shape[:2]) < 8:
        raise ShapeModelError("The template is too small (at least 8×8 px)")
    h, w = gray.shape[:2]
    levels: list[dict[str, Any]] = []
    img = gray
    msk = mask
    thresholds: tuple[float, float] | None = None
    centroid: tuple[float, float] | None = None
    want = int(pyramid_levels) if pyramid_levels and pyramid_levels > 0 else MAX_LEVELS
    for level in range(min(MAX_LEVELS, want)):
        scale = 2.0**level
        lo = None if contrast_low is None else float(contrast_low) / scale
        hi = None if contrast_high is None else float(contrast_high) / scale
        pts, dirs, used = extract_edges(img, lo if level == 0 else (thresholds[0] / scale if thresholds and contrast_low is None else lo),
                                        hi if level == 0 else (thresholds[1] / scale if thresholds and contrast_high is None else hi),
                                        max(1.0, min_contrast / scale), msk)
        if level == 0:
            thresholds = used
            if len(pts) < MIN_TOP_POINTS:
                raise ShapeModelError(f"Only {len(pts)} edge points in the template; lower the contrast thresholds or use a template with clearer edges")
            centroid = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        if level > 0 and len(pts) < MIN_TOP_POINTS and not (pyramid_levels and pyramid_levels > 0):
            break
        if len(pts) < 4:
            break
        pts, dirs = _subsample(pts, dirs, max_points)
        rel = pts - np.array([centroid[0] / scale, centroid[1] / scale], dtype=np.float32)
        radius = float(np.hypot(rel[:, 0], rel[:, 1]).max()) if len(rel) else 1.0
        levels.append({"level": level, "scale": scale, "pts": rel.astype(np.float32), "dirs": dirs.astype(np.float32), "radius": max(1.0, radius), "count": int(len(rel))})
        if min(img.shape[:2]) < 16:
            break
        img = cv2.pyrDown(img)
        if msk is not None:
            msk = cv2.resize(msk, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    if not levels:
        raise ShapeModelError("No edges were found in the template")
    return {
        "version": VERSION, "width": int(w), "height": int(h), "centroid": [centroid[0], centroid[1]],
        "levels": levels, "contrast_low": float(thresholds[0]), "contrast_high": float(thresholds[1]), "min_contrast": float(min_contrast),
        "angle_start": float(angle_start), "angle_extent": float(angle_extent), "scale_min": float(scale_min), "scale_max": float(scale_max),
        "max_points": int(max_points),
    }


def describe(model: dict[str, Any]) -> dict[str, Any]:
    """資產 meta。"""
    return {
        "kind": "shape_model", "version": int(model.get("version", VERSION)), "width": int(model["width"]), "height": int(model["height"]),
        "centroid": [round(float(model["centroid"][0]), 2), round(float(model["centroid"][1]), 2)],
        "levels": len(model["levels"]), "points": [int(lv["count"]) for lv in model["levels"]], "radius": round(float(model["levels"][0]["radius"]), 1),
        "contrast_low": round(float(model["contrast_low"]), 2), "contrast_high": round(float(model["contrast_high"]), 2), "min_contrast": float(model["min_contrast"]),
        "angle_start": float(model["angle_start"]), "angle_extent": float(model["angle_extent"]), "scale_min": float(model["scale_min"]), "scale_max": float(model["scale_max"]),
    }


def save(path: str, model: dict[str, Any]) -> int:
    arrays: dict[str, Any] = {"meta": json.dumps({k: v for k, v in model.items() if k != "levels"} | {"level_info": [{"level": lv["level"], "scale": lv["scale"], "radius": lv["radius"], "count": lv["count"]} for lv in model["levels"]]})}
    for lv in model["levels"]:
        arrays[f"L{lv['level']}_pts"] = lv["pts"]
        arrays[f"L{lv['level']}_dirs"] = lv["dirs"]
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    data = buf.getvalue()
    with open(path, "wb") as fh:
        fh.write(data)
    invalidate(path)
    return len(data)


_CACHE: "OrderedDict[str, tuple[float, int, dict[str, Any]]]" = OrderedDict()
_CACHE_MAX = 16
_LOCK = threading.Lock()


def invalidate(path: str = "") -> None:
    with _LOCK:
        if path:
            _CACHE.pop(path, None)
        else:
            _CACHE.clear()


def load(path: str) -> dict[str, Any]:
    try:
        st = os.stat(path)
    except OSError as exc:
        raise ShapeModelError(f"Could not read the shape model: {exc}") from None
    with _LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            _CACHE.move_to_end(path)
            return hit[2]
    try:
        with np.load(path, allow_pickle=False) as z:
            if "meta" not in z or "L0_pts" not in z:
                raise ShapeModelError("This file is not a shape model")
            meta = json.loads(str(z["meta"]))
            levels = []
            for info in meta.pop("level_info", []):
                k = int(info["level"])
                levels.append({"level": k, "scale": float(info["scale"]), "radius": float(info["radius"]), "count": int(info["count"]),
                               "pts": np.ascontiguousarray(z[f"L{k}_pts"], dtype=np.float32), "dirs": np.ascontiguousarray(z[f"L{k}_dirs"], dtype=np.float32)})
            model = {**meta, "levels": levels}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ShapeModelError(f"Could not read the shape model: {exc}") from None
    with _LOCK:
        _CACHE[path] = (st.st_mtime, st.st_size, model)
        _CACHE.move_to_end(path)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return model


def from_asset(asset_id: Any, resolve: Any) -> dict[str, Any]:
    if not asset_id:
        raise ShapeModelError("No shape model is set")
    path = resolve(str(asset_id))
    if not path:
        raise ShapeModelError(f"Asset {asset_id} not found")
    return load(path)


# ---------------------------------------------------------------------------
# 搜尋
# ---------------------------------------------------------------------------
def angle_step_for(radius: float) -> float:
    """角度步進（度）＝atan(1 / 半徑)：外緣點剛好移動 1 px，更細是純浪費。"""
    return math.degrees(math.atan(1.0 / max(1.0, radius)))


def _angles(start: float, extent: float, step: float) -> np.ndarray:
    extent = min(360.0, max(step, extent))
    n = max(1, int(math.ceil(extent / step)))
    if extent >= 360.0 - 1e-9:
        return (start + np.arange(n) * (360.0 / n)).astype(np.float64)
    return (start + np.linspace(0, extent, n + 1)).astype(np.float64)


def _scales(smin: float, smax: float, radius: float) -> np.ndarray:
    if smax <= smin + 1e-9:
        return np.array([smin], dtype=np.float64)
    step = 1.0 / max(1.0, radius)  # 半徑上剛好差 1 px
    n = max(1, int(math.ceil((smax - smin) / step)))
    return np.linspace(smin, smax, n + 1)


def _transform(pts: np.ndarray, angle_deg: float, scale: float) -> np.ndarray:
    t = math.radians(angle_deg)
    c, s = math.cos(t) * scale, math.sin(t) * scale
    out = np.empty_like(pts)
    out[:, 0] = pts[:, 0] * c - pts[:, 1] * s
    out[:, 1] = pts[:, 0] * s + pts[:, 1] * c
    return out


def _rotate_dirs(dirs: np.ndarray, angle_deg: float) -> tuple[np.ndarray, np.ndarray]:
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    return dirs[:, 0] * c - dirs[:, 1] * s, dirs[:, 0] * s + dirs[:, 1] * c


def score_map(ux: np.ndarray, uy: np.ndarray, pts: np.ndarray, dirs: np.ndarray, angle: float, scale: float, polarity: bool) -> np.ndarray:
    """整張影像每個位置的分數（最上層窮舉用）：逐點平移切片累加。回 (H, W) float32，模型放不下的位置為 0。"""
    h, w = ux.shape
    rp = np.round(_transform(pts, angle, scale)).astype(np.int32)
    dx_, dy_ = _rotate_dirs(dirs, angle)
    acc = np.zeros((h, w), dtype=np.float32)
    n = len(rp)
    if n == 0:
        return acc
    if polarity:
        # 帶極性的分數是線性相關：把模型點放進稀疏核（同一格的點累加），兩次 filter2D 算完整張分數圖
        r = int(max(np.abs(rp).max(), 1))
        kx = np.zeros((2 * r + 1, 2 * r + 1), dtype=np.float32)
        ky = np.zeros_like(kx)
        np.add.at(kx, (rp[:, 1] + r, rp[:, 0] + r), dx_.astype(np.float32))
        np.add.at(ky, (rp[:, 1] + r, rp[:, 0] + r), dy_.astype(np.float32))
        acc = cv2.filter2D(ux, -1, kx, anchor=(r, r), borderType=cv2.BORDER_CONSTANT)
        acc += cv2.filter2D(uy, -1, ky, anchor=(r, r), borderType=cv2.BORDER_CONSTANT)
        acc /= np.float32(n)
        return acc
    x0, x1 = int(rp[:, 0].min()), int(rp[:, 0].max())
    y0, y1 = int(rp[:, 1].min()), int(rp[:, 1].max())
    # 有效的中心位置：cx ∈ [−x0, w−1−x1]、cy ∈ [−y0, h−1−y1]
    cx0, cx1 = -x0, w - 1 - x1
    cy0, cy1 = -y0, h - 1 - y1
    if cx1 < cx0 or cy1 < cy0:
        return acc
    cw, ch = cx1 - cx0 + 1, cy1 - cy0 + 1
    region = acc[cy0 : cy0 + ch, cx0 : cx0 + cw]
    tmp = np.empty((ch, cw), dtype=np.float32)
    for i in range(n):
        px, py = int(rp[i, 0]), int(rp[i, 1])
        sx = ux[cy0 + py : cy0 + py + ch, cx0 + px : cx0 + px + cw]
        sy = uy[cy0 + py : cy0 + py + ch, cx0 + px : cx0 + px + cw]
        np.multiply(sx, np.float32(dx_[i]), out=tmp)
        tmp += sy * np.float32(dy_[i])
        if not polarity:
            np.abs(tmp, out=tmp)
        region += tmp
    region /= np.float32(n)
    return acc


def score_poses(ux: np.ndarray, uy: np.ndarray, pts: np.ndarray, dirs: np.ndarray, poses: np.ndarray, polarity: bool,
                min_score: float, greediness: float, chunks: int = 4, origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """一批姿態 (K, 4)=[cx, cy, angle, scale] 的分數（在某一層）。分塊累加＋提早中止：每塊之後把上界過不了 min_score 的姿態剔除。

    ux／uy 可以是子視窗（origin＝視窗左上角在該層的座標），姿態座標仍是該層的全圖座標。
    """
    k = len(poses)
    if k == 0:
        return np.zeros(0, dtype=np.float32)
    h, w = ux.shape
    n = len(pts)
    ox, oy = origin
    scores = np.zeros(k, dtype=np.float32)
    alive = np.ones(k, dtype=bool)
    order = np.linspace(0, n, chunks + 1).round().astype(int)
    ang = np.radians(poses[:, 2])
    c = np.cos(ang) * poses[:, 3]
    s = np.sin(ang) * poses[:, 3]
    cd, sd = np.cos(ang), np.sin(ang)
    partial = np.zeros(k, dtype=np.float32)
    px = poses[:, 0] - ox
    py = poses[:, 1] - oy
    for ci in range(chunks):
        a, b = int(order[ci]), int(order[ci + 1])
        if b <= a:
            continue
        idx = np.nonzero(alive)[0]
        if len(idx) == 0:
            break
        P = pts[a:b]
        D = dirs[a:b]
        X = px[idx][:, None] + P[:, 0][None, :] * c[idx][:, None] - P[:, 1][None, :] * s[idx][:, None]
        Y = py[idx][:, None] + P[:, 0][None, :] * s[idx][:, None] + P[:, 1][None, :] * c[idx][:, None]
        xi = np.rint(X).astype(np.int32)
        yi = np.rint(Y).astype(np.int32)
        inside = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        np.clip(xi, 0, w - 1, out=xi)
        np.clip(yi, 0, h - 1, out=yi)
        gx = ux[yi, xi]
        gy = uy[yi, xi]
        mdx = D[:, 0][None, :] * cd[idx][:, None] - D[:, 1][None, :] * sd[idx][:, None]
        mdy = D[:, 0][None, :] * sd[idx][:, None] + D[:, 1][None, :] * cd[idx][:, None]
        dot = gx * mdx + gy * mdy
        if not polarity:
            np.abs(dot, out=dot)
        dot[~inside] = 0.0
        partial[idx] += dot.sum(axis=1).astype(np.float32)
        done = b
        if ci < chunks - 1 and min_score > 0:
            # 提早中止：安全界 (partial + 剩餘點數) / n < min_score；greediness 往「partial/j」的激進界靠
            safe_t = min_score * n - (n - done)
            greedy_t = min_score * done
            t = (1.0 - greediness) * safe_t + greediness * greedy_t
            alive[idx] = partial[idx] >= t
    scores[:] = partial / np.float32(n)
    scores[~alive] = np.minimum(scores[~alive], np.float32(min_score * 0.99))
    return scores


def _local_maxima(sm: np.ndarray, threshold: float, max_n: int) -> list[tuple[int, int, float]]:
    """分數圖的 3×3 局部極大（≥ threshold），依分數排序取前 max_n。"""
    if sm.size == 0:
        return []
    dil = cv2.dilate(sm, np.ones((3, 3), np.uint8))
    peaks = (sm >= dil) & (sm >= threshold) & (sm > 0)
    ys, xs = np.nonzero(peaks)
    if len(xs) == 0:
        return []
    vals = sm[ys, xs]
    order = np.argsort(-vals)[:max_n]
    return [(int(xs[i]), int(ys[i]), float(vals[i])) for i in order]


def _nms(matches: list[dict[str, Any]], model_w: float, model_h: float, max_overlap: float, max_n: int) -> list[dict[str, Any]]:
    """依分數排序，外框（軸對齊近似）IoU > max_overlap 的較差者剔除。"""
    kept: list[dict[str, Any]] = []
    for m in sorted(matches, key=lambda d: -d["score"]):
        bw, bh = model_w * m["scale"], model_h * m["scale"]
        t = math.radians(m["angle"])
        ew = abs(bw * math.cos(t)) + abs(bh * math.sin(t))
        eh = abs(bw * math.sin(t)) + abs(bh * math.cos(t))
        ax0, ay0, ax1, ay1 = m["cx"] - ew / 2, m["cy"] - eh / 2, m["cx"] + ew / 2, m["cy"] + eh / 2
        ok = True
        for k in kept:
            kw, kh = model_w * k["scale"], model_h * k["scale"]
            tk = math.radians(k["angle"])
            kew = abs(kw * math.cos(tk)) + abs(kh * math.sin(tk))
            keh = abs(kw * math.sin(tk)) + abs(kh * math.cos(tk))
            bx0, by0, bx1, by1 = k["cx"] - kew / 2, k["cy"] - keh / 2, k["cx"] + kew / 2, k["cy"] + keh / 2
            iw, ih = max(0.0, min(ax1, bx1) - max(ax0, bx0)), max(0.0, min(ay1, by1) - max(ay0, by0))
            inter = iw * ih
            union = ew * eh + kew * keh - inter
            if union > 0 and inter / union > max_overlap:
                ok = False
                break
        if ok:
            kept.append(m)
            if len(kept) >= max_n:
                break
    return kept


def _dedup(poses: np.ndarray, scores: np.ndarray, pos_tol: float, ang_tol: float, scale_tol: float) -> tuple[np.ndarray, np.ndarray]:
    """同一個目標會從好幾個最上層候選（相鄰角度／位置）收斂到同一姿態：每層細化後只留分數最高的那個，其餘丟掉。"""
    if len(poses) <= 1:
        return poses, scores
    order = np.argsort(-scores)
    kept: list[int] = []
    for i in order:
        dup = False
        for k in kept:
            da = abs(((poses[i, 2] - poses[k, 2]) + 180.0) % 360.0 - 180.0)
            if abs(poses[i, 0] - poses[k, 0]) <= pos_tol and abs(poses[i, 1] - poses[k, 1]) <= pos_tol and da <= ang_tol and abs(poses[i, 3] - poses[k, 3]) <= scale_tol + 1e-9:
                dup = True
                break
        if not dup:
            kept.append(int(i))
    idx = np.array(kept, dtype=int)
    return poses[idx], scores[idx]


def _parabola(sm1: float, s0: float, sp1: float) -> float:
    denom = sm1 - 2 * s0 + sp1
    if abs(denom) < 1e-9:
        return 0.0
    return float(np.clip(0.5 * (sm1 - sp1) / denom, -0.5, 0.5))


def find(search: np.ndarray, model: dict[str, Any], *, min_score: float = 0.7, max_matches: int = 1, angle_start: float | None = None,
         angle_extent: float | None = None, scale_min: float | None = None, scale_max: float | None = None, max_overlap: float = 0.5,
         greediness: float = 0.7, subpixel: bool = True, polarity: bool = True, min_contrast: float | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """在灰階 search 影像上找模型。回 (matches[{cx, cy, angle, scale, score}], info)；matches 座標為 search 影像座標。

    最上層窮舉（整張分數圖）→ 逐層爬山細化（±1 px × ±2 角度步進 × ±1 尺度步進的鄰域，最佳不在中心就再爬，最多 3 次）
    → 最底層拋物線次像素 → NMS。第 0／1 層的梯度場只在候選附近的子視窗計算（整張 1280×960 的 Sobel 要 10 ms）。
    """
    gray = search if search.ndim == 2 else cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
    a_start = float(model["angle_start"] if angle_start is None else angle_start)
    a_extent = float(model["angle_extent"] if angle_extent is None else angle_extent)
    s_min = float(model["scale_min"] if scale_min is None else scale_min)
    s_max = float(model["scale_max"] if scale_max is None else scale_max)
    if a_extent <= 0:
        raise ShapeModelError("angle_extent must be positive")
    if s_min <= 0 or s_max < s_min:
        raise ShapeModelError("scale_min must be positive and not larger than scale_max")
    contrast = float(model.get("min_contrast", 10.0) if min_contrast is None else min_contrast)
    levels = model["levels"]
    n_levels = len(levels)
    pyr = [gray]
    for _ in range(1, n_levels):
        if min(pyr[-1].shape[:2]) < 16:
            break
        pyr.append(cv2.pyrDown(pyr[-1]))
    n_levels = min(n_levels, len(pyr))
    top = n_levels - 1
    lv = levels[top]
    ux, uy, _ = gradient_field(pyr[top], max(1.0, contrast / (2.0**top)))
    step_top = angle_step_for(lv["radius"])
    angles = _angles(a_start, a_extent, step_top)
    scales = _scales(s_min, s_max, lv["radius"])
    coarse_threshold = min_score * 0.8
    max_cands = max(16, max_matches * 8)
    candidates: list[tuple[float, float, float, float, float]] = []
    info: dict[str, Any] = {"levels": n_levels, "top_angles": int(len(angles)), "top_scales": int(len(scales)), "top_size": [int(ux.shape[1]), int(ux.shape[0])]}
    for sc in scales:
        for ang in angles:
            sm = score_map(ux, uy, lv["pts"], lv["dirs"], float(ang), float(sc), polarity)
            for x, y, v in _local_maxima(sm, coarse_threshold, max_cands):
                candidates.append((float(x), float(y), float(ang), float(sc), v))
    candidates.sort(key=lambda t: -t[4])
    candidates = candidates[: max_cands * 4]
    info["top_candidates"] = len(candidates)
    if not candidates:
        return [], info
    poses = np.array([[c[0], c[1], c[2], c[3]] for c in candidates], dtype=np.float64)
    last_scores = np.array([c[4] for c in candidates], dtype=np.float32)
    scale_step = float(scales[1] - scales[0]) if len(scales) > 1 else 0.0
    poses, last_scores = _dedup(poses, last_scores, 1.5, 1.5 * step_top, scale_step)
    info["top_unique"] = int(len(poses))
    offs = np.array([(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)], dtype=np.float64)
    final_grid: np.ndarray | None = None
    final_scores: np.ndarray | None = None
    for level in range(top - 1, -1, -1):
        lv = levels[level]
        step = angle_step_for(lv["radius"])
        poses[:, 0] *= 2.0
        poses[:, 1] *= 2.0
        scale_step = scale_step / 2.0 if scale_step > 0 else 0.0
        dangs = np.array([-2 * step, -step, 0.0, step, 2 * step])
        dscales = np.array([-scale_step, 0.0, scale_step]) if scale_step > 0 else np.array([0.0])
        grid = np.array([(o[0], o[1], da, ds) for ds in dscales for da in dangs for o in offs], dtype=np.float64)
        centre_index = int(np.nonzero((grid == 0).all(axis=1))[0][0])
        thr = min_score * (0.85 if level > 0 else 0.95)
        # 梯度場：只算候選附近的子視窗（半徑 × 最大尺度 ＋ 邊界）
        reach = lv["radius"] * s_max + 4.0
        h_l, w_l = pyr[level].shape[:2]
        x0 = max(0, int(math.floor(poses[:, 0].min() - reach)) - 1)
        y0 = max(0, int(math.floor(poses[:, 1].min() - reach)) - 1)
        x1 = min(w_l, int(math.ceil(poses[:, 0].max() + reach)) + 2)
        y1 = min(h_l, int(math.ceil(poses[:, 1].max() + reach)) + 2)
        if x1 <= x0 or y1 <= y0:
            poses = poses[:0]
            break
        ux, uy, _ = gradient_field(np.ascontiguousarray(pyr[level][y0:y1, x0:x1]), max(1.0, contrast / (2.0**level)))
        # 子視窗邊緣一圈的 Sobel 不完整：多切 1 px，這一圈已在視窗外（上面 −1／+2 留的邊）
        origin = (x0, y0)
        sc = None
        active = np.ones(len(poses), dtype=bool)
        for _ in range(3):
            ai = np.nonzero(active)[0]
            allp = (poses[ai][:, None, :] + grid[None, :, :]).reshape(-1, 4)
            allp[:, 3] = np.clip(allp[:, 3], s_min, s_max)
            part = score_poses(ux, uy, lv["pts"], lv["dirs"], allp, polarity, thr, greediness, origin=origin).reshape(len(ai), len(grid))
            if sc is None:
                sc = part
            else:
                sc[ai] = part
            best = part.argmax(axis=1)
            last_scores[ai] = part[np.arange(len(ai)), best]
            poses[ai] = allp.reshape(len(ai), len(grid), 4)[np.arange(len(ai)), best]
            moved = best != centre_index
            active[ai] = moved
            if not moved.any():
                break
        keep = last_scores >= thr
        info.setdefault("per_level", []).append({"level": level, "poses": int(len(poses)), "kept": int(keep.sum()), "best": round(float(last_scores.max()), 3) if len(last_scores) else 0.0, "threshold": round(thr, 3)})
        poses, last_scores = poses[keep], last_scores[keep]
        if level == 0 and sc is not None:
            final_grid, final_scores = grid, sc[keep]
        if len(poses) == 0:
            break
        # 收斂到同一姿態的重複候選只留最好的（多個最上層角度／位置候選會爬到同一個目標）
        before = len(poses)
        poses, last_scores = _dedup(poses, last_scores, 1.5, 1.5 * step, scale_step)
        if final_grid is not None and level == 0 and len(poses) != before:
            # 去重後 final_scores 要跟著（依 _dedup 的排序重取）：簡單起見重算一次鄰域分數
            allp = (poses[:, None, :] + grid[None, :, :]).reshape(-1, 4)
            allp[:, 3] = np.clip(allp[:, 3], s_min, s_max)
            final_scores = score_poses(ux, uy, lv["pts"], lv["dirs"], allp, polarity, 0.0, 0.0, origin=origin).reshape(len(poses), len(grid))
        info["per_level"][-1]["unique"] = int(len(poses))
    info["refined"] = int(len(poses))
    matches: list[dict[str, Any]] = []
    for i in range(len(poses)):
        cx, cy, ang, scl = (float(v) for v in poses[i])
        s = float(last_scores[i])
        if subpixel and final_grid is not None and final_scores is not None and top > 0:
            g, sc_i = final_grid, final_scores[i]
            bi = int(np.argmax(sc_i))
            if (g[bi] == 0).all():
                def at(dx: float, dy: float, da: float) -> float | None:
                    m = (np.abs(g[:, 0] - dx) < 1e-9) & (np.abs(g[:, 1] - dy) < 1e-9) & (np.abs(g[:, 2] - da) < 1e-9) & (np.abs(g[:, 3]) < 1e-9)
                    j = np.nonzero(m)[0]
                    return float(sc_i[j[0]]) if len(j) else None
                step0 = angle_step_for(levels[0]["radius"])
                sxm, sxp = at(-1, 0, 0), at(1, 0, 0)
                sym, syp = at(0, -1, 0), at(0, 1, 0)
                sam, sap = at(0, 0, -step0), at(0, 0, step0)
                if sxm is not None and sxp is not None:
                    cx += _parabola(sxm, s, sxp)
                if sym is not None and syp is not None:
                    cy += _parabola(sym, s, syp)
                if sam is not None and sap is not None:
                    ang += _parabola(sam, s, sap) * step0
        matches.append({"cx": cx, "cy": cy, "angle": ((ang + 180.0) % 360.0) - 180.0, "scale": scl, "score": min(1.0, s)})
    matches = [m for m in matches if m["score"] >= min_score]
    matches = _nms(matches, float(model["width"]), float(model["height"]), max_overlap, max_matches)
    return matches, info


def model_outline(model: dict[str, Any], cx: float, cy: float, angle: float, scale: float, max_points: int = 400) -> list[list[float]]:
    """模型第 0 層邊緣點依姿態轉到影像座標（顯示用，最多 max_points 點）。"""
    pts = model["levels"][0]["pts"]
    if len(pts) > max_points:
        idx = np.linspace(0, len(pts) - 1, max_points).round().astype(int)
        pts = pts[idx]
    tp = _transform(pts, angle, scale)
    tp[:, 0] += cx
    tp[:, 1] += cy
    return tp.round(2).tolist()
