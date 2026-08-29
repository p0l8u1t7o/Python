"""ROI 幾何：把畫布上畫的區域套到影像上，並把座標換回全圖。

region dict 形狀：
  {"shape": "rect", "x", "y", "w", "h"}
  {"shape": "rotated_rect", "cx", "cy", "w", "h", "angle"}   angle 為度，順時針
  {"shape": "circle", "cx", "cy", "r"}
  {"shape": "annulus", "cx", "cy", "r_inner", "r_outer"}
  {"shape": "polygon", "points": [[x, y], ...]}
  {"shape": "line", "x1", "y1", "x2", "y2"}
所有工具都用這裡的 helper，座標慣例只在一處。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class Crop:
    """裁切結果：crop 是子影像（可能帶遮罩），offset 是它在全圖的左上角。"""

    image: np.ndarray
    x0: int
    y0: int
    mask: np.ndarray | None = None
    #: 旋轉矩形時：把 crop 座標轉回全圖的 2x3 仿射矩陣。
    inverse: np.ndarray | None = None

    def to_full(self, x: float, y: float) -> tuple[float, float]:
        if self.inverse is not None:
            px = self.inverse @ np.array([x, y, 1.0])
            return float(px[0]), float(px[1])
        return float(x + self.x0), float(y + self.y0)

    def points_to_full(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if self.inverse is not None:
            ones = np.ones((len(pts), 1))
            return (np.hstack([pts, ones]) @ self.inverse.T)
        return pts + np.array([self.x0, self.y0], dtype=np.float64)


def bounding_rect(region: dict[str, Any], w: int, h: int) -> tuple[int, int, int, int]:
    """region 的軸對齊外框（已夾在影像內）：x, y, w, h。"""
    shape = region.get("shape")
    if shape == "rect":
        x, y, rw, rh = region["x"], region["y"], region["w"], region["h"]
    elif shape == "rotated_rect":
        box = cv2.boxPoints(((float(region["cx"]), float(region["cy"])), (float(region["w"]), float(region["h"])), float(region.get("angle", 0))))
        x, y, rw, rh = cv2.boundingRect(box.astype(np.float32))
    elif shape == "circle":
        r = float(region["r"])
        x, y, rw, rh = region["cx"] - r, region["cy"] - r, 2 * r, 2 * r
    elif shape == "annulus":
        r = float(region["r_outer"])
        x, y, rw, rh = region["cx"] - r, region["cy"] - r, 2 * r, 2 * r
    elif shape == "polygon":
        pts = np.asarray(region["points"], dtype=np.float32)
        x, y, rw, rh = cv2.boundingRect(pts)
    elif shape == "line":
        xs = [region["x1"], region["x2"]]
        ys = [region["y1"], region["y2"]]
        x, y, rw, rh = min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    else:
        raise ValueError(f"未知的 ROI 形狀 {shape!r}")
    x0 = max(0, int(np.floor(x)))
    y0 = max(0, int(np.floor(y)))
    x1 = min(w, int(np.ceil(x + rw)))
    y1 = min(h, int(np.ceil(y + rh)))
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def mask_for(region: dict[str, Any], w: int, h: int, *, offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    """0/255 遮罩。預設全圖大小；給 offset=(x0, y0) 時只畫 w×h 的子視窗（座標平移 -x0, -y0），
    crop() 用它避免每次為了一個小 ROI 配置整張影像大小的遮罩。"""
    mask = np.zeros((h, w), dtype=np.uint8)
    ox, oy = offset
    shape = region.get("shape")
    if shape == "rect":
        x, y, rw, rh = bounding_rect(region, w + ox, h + oy)
        x, y = x - ox, y - oy
        mask[max(0, y) : y + rh, max(0, x) : x + rw] = 255
    elif shape == "rotated_rect":
        box = cv2.boxPoints(((float(region["cx"]) - ox, float(region["cy"]) - oy), (float(region["w"]), float(region["h"])), float(region.get("angle", 0))))
        cv2.fillPoly(mask, [np.round(box).astype(np.int32)], 255)
    elif shape == "circle":
        cv2.circle(mask, (int(round(region["cx"])) - ox, int(round(region["cy"])) - oy), int(round(region["r"])), 255, -1)
    elif shape == "annulus":
        c = (int(round(region["cx"])) - ox, int(round(region["cy"])) - oy)
        cv2.circle(mask, c, int(round(region["r_outer"])), 255, -1)
        cv2.circle(mask, c, int(round(region["r_inner"])), 0, -1)
    elif shape == "polygon":
        cv2.fillPoly(mask, [np.round(np.asarray(region["points"]) - np.array([ox, oy])).astype(np.int32)], 255)
    elif shape == "line":
        cv2.line(mask, (int(region["x1"]) - ox, int(region["y1"]) - oy), (int(region["x2"]) - ox, int(region["y2"]) - oy), 255, 1)
    return mask


def crop(image: np.ndarray, region: dict[str, Any] | None, *, upright: bool = False) -> Crop:
    """裁出 ROI。

    upright=True 且 ROI 為 rotated_rect 時，會把區域旋轉擺正（量測類工具需要）；
    其餘形狀裁外框並附遮罩（非矩形區域外的像素在 mask 為 0）。
    """
    h, w = image.shape[:2]
    if region is None:
        return Crop(image=image, x0=0, y0=0)
    shape = region.get("shape")
    if shape == "rotated_rect" and upright:
        cx, cy = float(region["cx"]), float(region["cy"])
        rw, rh = max(1, int(round(region["w"]))), max(1, int(round(region["h"])))
        angle = float(region.get("angle", 0))
        m = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        m[0, 2] += rw / 2 - cx
        m[1, 2] += rh / 2 - cy
        out = cv2.warpAffine(image, m, (rw, rh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        inverse = cv2.invertAffineTransform(m)
        return Crop(image=out, x0=0, y0=0, inverse=inverse)
    x, y, rw, rh = bounding_rect(region, w, h)
    if rw == 0 or rh == 0:
        return Crop(image=image[0:0, 0:0], x0=x, y0=y)
    sub = image[y : y + rh, x : x + rw]
    mask = None
    if shape not in ("rect",):
        mask = mask_for(region, rw, rh, offset=(x, y))
    return Crop(image=sub, x0=x, y0=y, mask=mask)


def region_overlay(region: dict[str, Any], color: str = "#38bdf8", label: str = "") -> dict[str, Any]:
    """把 ROI 畫成 overlay（前端用），方便工具顯示它實際看的範圍。"""
    shape = region.get("shape")
    base: dict[str, Any] = {"color": color, "width": 1, "dash": True}
    if label:
        base["label"] = label
    if shape == "rect":
        return {"kind": "rect", "x": region["x"], "y": region["y"], "w": region["w"], "h": region["h"], **base}
    if shape == "rotated_rect":
        return {"kind": "rect", "x": region["cx"] - region["w"] / 2, "y": region["cy"] - region["h"] / 2, "w": region["w"], "h": region["h"], "angle": region.get("angle", 0), **base}
    if shape == "circle":
        return {"kind": "circle", "cx": region["cx"], "cy": region["cy"], "r": region["r"], **base}
    if shape == "annulus":
        return {"kind": "annulus", "cx": region["cx"], "cy": region["cy"], "r_inner": region["r_inner"], "r_outer": region["r_outer"], **base}
    if shape == "polygon":
        return {"kind": "polygon", "points": region["points"], **base}
    if shape == "line":
        return {"kind": "line", "x1": region["x1"], "y1": region["y1"], "x2": region["x2"], "y2": region["y2"], **base}
    return {"kind": "text", "x": 0, "y": 0, "text": f"unknown roi {shape}", **base}


def region_center(region: dict[str, Any]) -> tuple[float, float]:
    shape = region.get("shape")
    if shape == "rect":
        return region["x"] + region["w"] / 2, region["y"] + region["h"] / 2
    if shape in ("rotated_rect", "circle", "annulus"):
        return float(region["cx"]), float(region["cy"])
    if shape == "polygon":
        pts = np.asarray(region["points"], dtype=np.float64)
        return float(pts[:, 0].mean()), float(pts[:, 1].mean())
    if shape == "line":
        return (region["x1"] + region["x2"]) / 2, (region["y1"] + region["y2"]) / 2
    return 0.0, 0.0


def transform_region(region: dict[str, Any], dx: float, dy: float, dtheta: float = 0.0, pivot: tuple[float, float] | None = None) -> dict[str, Any]:
    """依定位結果平移／旋轉 ROI（定位後的跟隨 ROI）。dtheta 為度。"""
    out = dict(region)
    shape = region.get("shape")
    if dtheta and pivot is not None:
        m = cv2.getRotationMatrix2D(pivot, -dtheta, 1.0)

        def rot(x: float, y: float) -> tuple[float, float]:
            p = m @ np.array([x, y, 1.0])
            return float(p[0]), float(p[1])
    else:
        def rot(x: float, y: float) -> tuple[float, float]:
            return x, y

    if shape == "rect":
        cx, cy = rot(region["x"] + region["w"] / 2, region["y"] + region["h"] / 2)
        if dtheta:
            out = {"shape": "rotated_rect", "cx": cx + dx, "cy": cy + dy, "w": region["w"], "h": region["h"], "angle": dtheta}
        else:
            out["x"] = region["x"] + dx
            out["y"] = region["y"] + dy
    elif shape in ("rotated_rect", "circle", "annulus"):
        cx, cy = rot(region["cx"], region["cy"])
        out["cx"], out["cy"] = cx + dx, cy + dy
        if shape == "rotated_rect":
            out["angle"] = float(region.get("angle", 0)) + dtheta
    elif shape == "polygon":
        out["points"] = [[px + dx, py + dy] for px, py in (rot(*p) for p in region["points"])]
    elif shape == "line":
        x1, y1 = rot(region["x1"], region["y1"])
        x2, y2 = rot(region["x2"], region["y2"])
        out.update({"x1": x1 + dx, "y1": y1 + dy, "x2": x2 + dx, "y2": y2 + dy})
    return out
