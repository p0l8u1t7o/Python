"""ROI 影像特徵量測：規則引擎靠它自動調參，LLM 供應器把它當文字摘要。

所有量測都在「使用者圈的 ROI」內做（沒圈就整張圖），輸出純 Python 純量，
可直接 JSON 化。不修改輸入影像。
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


def _circle_probe(gray: np.ndarray) -> dict[str, Any]:
    """霍夫試探：ROI 裡有沒有明顯的圓（給「找圓 vs 找 blob」的判斷加權）。"""
    h, w = gray.shape[:2]
    r_max = max(10, min(h, w) // 2)
    blurred = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1.5, minDist=max(20, r_max // 2),
                               param1=120, param2=30, minRadius=max(5, r_max // 8), maxRadius=r_max)
    if circles is None:
        return {"found": False, "count": 0, "radius": 0.0}
    circles = circles[0]
    return {"found": True, "count": int(len(circles)), "radius": round(float(np.median(circles[:, 2])), 1)}


def analyze_region(image: np.ndarray, region: dict[str, Any] | None) -> dict[str, Any]:
    """單一 ROI 的特徵包。region=None 表示整張影像。"""
    piece = crop(image, region, upright=True).image if region else image
    if piece.size == 0:
        return {"empty": True}
    gray = _to_gray(piece)
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 150)
    dark_ratio = float((gray < otsu).mean())
    info: dict[str, Any] = {
        "w": int(piece.shape[1]), "h": int(piece.shape[0]),
        "mean": round(float(gray.mean()), 1), "std": round(float(gray.std()), 1),
        "otsu": round(float(otsu), 1),
        "dark_ratio": round(dark_ratio, 3),
        "edge_ratio": round(float((edges > 0).mean()), 4),
        "dominant": _dominant_hsv(piece),
        "blobs": _blob_probe(gray, otsu),
        "circle": _circle_probe(gray),
    }
    if region:
        x, y, w, h = bounding_rect(region, int(image.shape[1]), int(image.shape[0]))
        info["bounds"] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        info["shape"] = str(region.get("shape", ""))
    return info


def analyze(image: np.ndarray, regions: list[dict[str, Any]]) -> dict[str, Any]:
    """整張影像＋各 ROI 的特徵摘要。regions 可為空（整張圖當一個 ROI）。"""
    return {
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "channels": int(image.shape[2]) if image.ndim == 3 else 1,
        "full": analyze_region(image, None),
        "regions": [analyze_region(image, r.get("region")) for r in regions],
    }


def summarize_for_llm(analysis: dict[str, Any]) -> str:
    """把特徵包壓成給 LLM 的短文字（省 token、避免傳原始陣列）。"""
    lines = [f"影像 {analysis['width']}x{analysis['height']} px，{analysis['channels']} 通道。"]
    for i, r in enumerate(analysis.get("regions", []), start=1):
        if r.get("empty"):
            lines.append(f"ROI{i}: 空區域")
            continue
        b = r.get("bounds", {})
        dom = r.get("dominant", {})
        lines.append(
            f"ROI{i}（{r.get('shape', '?')} @ {b.get('x')},{b.get('y')} {b.get('w')}x{b.get('h')}）："
            f"平均灰階 {r['mean']}±{r['std']}，Otsu {r['otsu']}，暗部佔比 {r['dark_ratio']}，"
            f"邊緣密度 {r['edge_ratio']}，主色 {dom.get('hex')}（H{dom.get('h')} S{dom.get('s')} V{dom.get('v')}），"
            f"暗粒子 {r['blobs']['dark']['count']} 顆（中位面積 {r['blobs']['dark']['median_area']}px²）、"
            f"亮粒子 {r['blobs']['bright']['count']} 顆；"
            f"圓形試探：{'有' if r['circle']['found'] else '無'}（{r['circle']['count']} 個，r≈{r['circle']['radius']}px）"
        )
    return "\n".join(lines)
