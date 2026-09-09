"""ROI 影像特徵量測：規則引擎靠它自動調參，LLM 供應器把它當文字摘要。

支援多張影像：每個 ROI 帶 `image`（影像索引，預設 0），在自己那張圖上量。
所有量測輸出純 Python 純量，可直接 JSON 化。不修改輸入影像。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from apps.vision.tools.roi import bounding_rect, crop


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def _dominant_hsv(bgr: np.ndarray) -> dict[str, Any]:
    """ROI 主色：HSV 各通道中位數＋十六進位色碼（近似）。"""
    if bgr.ndim != 3:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h = float(np.median(hsv[:, :, 0]))
    s = float(np.median(hsv[:, :, 1]))
    v = float(np.median(hsv[:, :, 2]))
    b, g, r = (float(np.median(bgr[:, :, c])) for c in range(3))
    return {"h": round(h, 1), "s": round(s, 1), "v": round(v, 1), "hex": f"#{int(r):02x}{int(g):02x}{int(b):02x}"}


def _blob_probe(gray: np.ndarray, otsu: float) -> dict[str, Any]:
    """在 Otsu 門檻下數一數暗／亮粒子（面積 > 全圖 0.05%），供計數意圖調參。"""
    area_floor = max(9, int(gray.size * 0.0005))
    out: dict[str, Any] = {}
    for label, invert in (("dark", True), ("bright", False)):
        _, mask = cv2.threshold(gray, otsu, 255, cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        areas = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= area_floor]
        areas.sort()
        out[label] = {
            "count": len(areas),
            "median_area": int(areas[len(areas) // 2]) if areas else 0,
            "min_area": int(areas[0]) if areas else 0,
        }
    return out


PROBE_MAX_SIDE = 480  # 霍夫試探先縮到這個邊長：只需要「有沒有圓」，不需要像素級半徑


def _circle_probe(gray: np.ndarray, edge_ratio: float = 0.0) -> dict[str, Any]:
    """霍夫試探：ROI 裡有沒有明顯的圓（給「找圓 vs 找 blob」的判斷加權）。

    整張 1280×960 的規律紋理面直接跑霍夫要十幾秒且結果無意義，所以：邊緣密度過高直接略過，其餘先縮圖再試探。
    """
    if edge_ratio > 0.15:
        return {"found": False, "count": 0, "radius": 0.0, "skipped": True}
    h, w = gray.shape[:2]
    scale = min(1.0, PROBE_MAX_SIDE / float(max(h, w)))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else gray
    sh, sw = small.shape[:2]
    r_max = max(10, min(sh, sw) // 2)
    blurred = cv2.medianBlur(small, 5)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1.5, minDist=max(20, r_max // 2),
                               param1=120, param2=30, minRadius=max(4, r_max // 8), maxRadius=r_max)
    if circles is None:
        return {"found": False, "count": 0, "radius": 0.0}
    circles = circles[0]
    return {"found": True, "count": int(len(circles)), "radius": round(float(np.median(circles[:, 2])) / scale, 1)}


def _outliers(gray: np.ndarray) -> dict[str, float]:
    """偏離背景的像素佔比（暗／亮各一）：原圖用穩健 σ、低通後再算一次取大者，讓紋理面上的刮痕也算得出來。"""
    g = gray.astype(np.float32)
    med = float(np.median(g))
    mad = float(np.median(np.abs(g - med))) * 1.4826
    smooth = cv2.GaussianBlur(gray, (0, 0), 6).astype(np.float32)
    smed = float(np.median(smooth))
    smad = float(np.median(np.abs(smooth - smed))) * 1.4826
    k_raw, k_smooth = max(30.0, 3 * mad), max(12.0, 3 * smad)
    dark = max(float((g < med - k_raw).mean()), float((smooth < smed - k_smooth).mean()))
    bright = max(float((g > med + k_raw).mean()), float((smooth > smed + k_smooth).mean()))
    return {"dark": round(dark, 5), "bright": round(bright, 5)}


def _sharpness(gray: np.ndarray) -> float:
    """清晰度：呼叫 sharpness 工具同一支評分（laplacian、normalize），生成的門檻才與工具輸出同一個尺度。"""
    try:
        from apps.vision.tools.builtin.measure import _sharpness_score

        return round(float(_sharpness_score(gray, None, "laplacian", True)), 4)
    except Exception:  # noqa: BLE001 - 區域太小等情況：沒有分數就不給門檻
        return 0.0


def analyze_region(image: np.ndarray, region: dict[str, Any] | None) -> dict[str, Any]:
    """單一 ROI 的特徵包。region=None 表示整張影像。"""
    piece = crop(image, region, upright=True).image if region else image
    if piece.size == 0:
        return {"empty": True}
    gray = _to_gray(piece)
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 150)
    edge_ratio = float((edges > 0).mean())
    dark_ratio = float((gray < otsu).mean())
    median = float(np.median(gray))
    mad = float(np.median(np.abs(gray.astype(np.float32) - median))) * 1.4826  # 穩健 σ：不受缺陷本身拉高
    h_, w_ = gray.shape[:2]
    mean_all = max(1.0, float(gray.mean()))
    gradient = (abs(float(gray[: h_ // 2].mean()) - float(gray[h_ // 2:].mean())) + abs(float(gray[:, : w_ // 2].mean()) - float(gray[:, w_ // 2:].mean()))) / 2 / mean_all
    color_std = float(np.mean([piece[:, :, c].std() for c in range(3)])) if piece.ndim == 3 else float(gray.std())
    smooth = cv2.GaussianBlur(gray, (0, 0), 6)  # 低通後的穩健 σ：規律紋理被平均掉，只剩大尺度起伏（紋理面缺陷門檻用）
    smooth_mad = float(np.median(np.abs(smooth.astype(np.float32) - float(np.median(smooth))))) * 1.4826
    info: dict[str, Any] = {
        "w": int(piece.shape[1]), "h": int(piece.shape[0]), "area": int(piece.shape[0] * piece.shape[1]),
        "mean": round(float(gray.mean()), 1), "std": round(float(gray.std()), 1),
        "mad": round(mad, 1), "smooth_mad": round(smooth_mad, 1), "gradient": round(gradient, 3), "color_std": round(color_std, 1),
        "otsu": round(float(otsu), 1),
        "sharpness": _sharpness(gray),
        "dark_ratio": round(dark_ratio, 3),
        "edge_ratio": round(edge_ratio, 4),
        "dominant": _dominant_hsv(piece),
        "blobs": _blob_probe(gray, otsu),
        "circle": _circle_probe(gray, edge_ratio),
        "outliers": _outliers(gray),
    }
    if region:
        x, y, w, h = bounding_rect(region, int(image.shape[1]), int(image.shape[0]))
        info["bounds"] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        info["shape"] = str(region.get("shape", ""))
    return info


def _image_outliers(image: np.ndarray, regions: list[dict[str, Any]]) -> dict[str, float]:
    """每張影像各算一次離群比例（套第一個 ROI，沒有就整張）：缺陷只出現在部分影像，跨影像取最大值才看得到極性。"""
    region = regions[0].get("region") if regions else None
    piece = crop(image, region, upright=True).image if region else image
    if piece.size == 0:
        return {"dark": 0.0, "bright": 0.0}
    return _outliers(_to_gray(piece))


def analyze(images: list[np.ndarray], regions: list[dict[str, Any]]) -> dict[str, Any]:
    """多張影像＋各 ROI 的特徵摘要。regions[i] 可帶 image（影像索引，預設 0）。"""
    first = images[0]
    rows = []
    for r in regions:
        idx = int(r.get("image", 0) or 0)
        img = images[idx] if 0 <= idx < len(images) else first
        row = analyze_region(img, r.get("region"))
        row["image"] = idx
        row["hint"] = str(r.get("hint") or "")
        rows.append(row)
    return {
        "width": int(first.shape[1]),
        "height": int(first.shape[0]),
        "channels": int(first.shape[2]) if first.ndim == 3 else 1,
        "image_count": len(images),
        "images": [{"index": i, "width": int(im.shape[1]), "height": int(im.shape[0]), "outliers": _image_outliers(im, regions)} for i, im in enumerate(images)],
        "full": analyze_region(first, None),
        "regions": rows,
    }


def summarize_for_llm(analysis: dict[str, Any]) -> str:
    """把特徵包壓成給 LLM 的短文字（省 token、避免傳原始陣列）。"""
    lines = [f"共 {analysis.get('image_count', 1)} 張影像；影像 1 為 {analysis['width']}x{analysis['height']} px，{analysis['channels']} 通道。"]
    for i, r in enumerate(analysis.get("regions", []), start=1):
        if r.get("empty"):
            lines.append(f"ROI{i:02d}: 空區域")
            continue
        b = r.get("bounds", {})
        dom = r.get("dominant", {})
        hint = f"，使用者提示「{r['hint']}」" if r.get("hint") else ""
        lines.append(
            f"ROI{i:02d}（影像 {r.get('image', 0) + 1}，{r.get('shape', '?')} @ {b.get('x')},{b.get('y')} {b.get('w')}x{b.get('h')}{hint}）："
            f"平均灰階 {r['mean']}±{r['std']}（穩健 σ {r.get('mad', 0)}，背景不均 {r.get('gradient', 0)}），Otsu {r['otsu']}，暗部佔比 {r['dark_ratio']}，"
            f"邊緣密度 {r['edge_ratio']}，主色 {dom.get('hex')}（H{dom.get('h')} S{dom.get('s')} V{dom.get('v')}），"
            f"暗粒子 {r['blobs']['dark']['count']} 顆（中位面積 {r['blobs']['dark']['median_area']}px²）、"
            f"亮粒子 {r['blobs']['bright']['count']} 顆；"
            f"圓形試探：{'有' if r['circle']['found'] else '無'}（{r['circle']['count']} 個，r≈{r['circle']['radius']}px）"
        )
    return "\n".join(lines)
