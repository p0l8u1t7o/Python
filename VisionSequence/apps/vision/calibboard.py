"""可列印標定板產生器。

這個模組只處理幾何與 PNG 編碼，不碰 HTTP 或權限，讓端點與測試都能共用同一套真值。
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from PIL import Image

Pattern = Literal["chessboard", "acircles"]

DPI_MIN = 72
DPI_MAX = 1200
SIZE_MIN = 3
SIZE_MAX = 40
SPACING_MIN_MM = 1.0
SPACING_MAX_MM = 500.0


@dataclass(frozen=True)
class BoardSpec:
    pattern: Pattern
    rows: int
    cols: int
    spacing_mm: float
    dpi: int

    @property
    def pitch_px(self) -> float:
        return self.spacing_mm / 25.4 * self.dpi


def validate_spec(pattern: str, rows: int, cols: int, spacing: float, dpi: int) -> BoardSpec:
    """驗證標定板參數並回傳正規化規格。"""
    if pattern not in ("chessboard", "acircles"):
        raise ValueError("pattern must be chessboard or acircles")
    if rows < SIZE_MIN or cols < SIZE_MIN:
        raise ValueError("rows and cols must be at least 3")
    if rows > SIZE_MAX or cols > SIZE_MAX:
        raise ValueError(f"rows and cols must be at most {SIZE_MAX}")
    if not math.isfinite(spacing) or spacing < SPACING_MIN_MM or spacing > SPACING_MAX_MM:
        raise ValueError(f"spacing must be between {SPACING_MIN_MM:g} and {SPACING_MAX_MM:g} mm")
    if dpi < DPI_MIN or dpi > DPI_MAX:
        raise ValueError(f"dpi must be between {DPI_MIN} and {DPI_MAX}")
    return BoardSpec(pattern=pattern, rows=rows, cols=cols, spacing_mm=float(spacing), dpi=int(dpi))


def _put_text(img: np.ndarray, text: str, org: tuple[int, int], scale: float = 0.85, thickness: int = 2) -> None:
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (40, 40, 40), thickness, cv2.LINE_AA)


def _scale_bar_mm(width: int, margin: int, pitch_px: float, dpi: int) -> tuple[float, int]:
    for mm in (100.0, 50.0, 25.0, 10.0):
        px = int(round(mm / 25.4 * dpi))
        if px <= width - 2 * margin:
            return mm, px
    return 5.0, int(round(5.0 / 25.4 * dpi))


def _footer(img: np.ndarray, spec: BoardSpec, board_bottom: int, margin: int) -> None:
    """把規格與比例尺印在標定圖下方，避開可偵測的幾何區。"""
    h, w = img.shape[:2]
    y = min(h - 120, board_bottom + max(54, margin // 2))
    pitch = spec.pitch_px
    label = "Chessboard" if spec.pattern == "chessboard" else "Asymmetric circles"
    _put_text(img, f"{label} - rows {spec.rows}, cols {spec.cols}, spacing {spec.spacing_mm:g} mm, {spec.dpi} DPI", (margin, y))
    _put_text(img, "Print at 100% / actual size. Measure the scale bar after printing.", (margin, y + 42), 0.72, 2)
    bar_mm, bar_px = _scale_bar_mm(w, margin, pitch, spec.dpi)
    x0, y0 = margin, y + 90
    x1 = min(w - margin, x0 + bar_px)
    cv2.line(img, (x0, y0), (x1, y0), (20, 20, 20), 6, cv2.LINE_AA)
    cv2.line(img, (x0, y0 - 16), (x0, y0 + 16), (20, 20, 20), 4, cv2.LINE_AA)
    cv2.line(img, (x1, y0 - 16), (x1, y0 + 16), (20, 20, 20), 4, cv2.LINE_AA)
    _put_text(img, f"{bar_mm:g} mm scale", (x0, y0 + 44), 0.72, 2)


def render_board(spec: BoardSpec) -> np.ndarray:
    """依規格產生 BGR 標定板影像。

    chessboard 的 rows/cols 是內角點數；acircles 的 rows/cols 是圓心數。兩者的相鄰真值間距都由
    ``spacing_mm / 25.4 * dpi`` 決定。
    """
    pitch = spec.pitch_px
    margin = int(max(90, round(pitch * 0.8)))
    footer_h = int(max(210, round(pitch * 0.9)))
    if spec.pattern == "chessboard":
        board_w = int(round((spec.cols + 1) * pitch))
        board_h = int(round((spec.rows + 1) * pitch))
        w, h = board_w + margin * 2, board_h + margin * 2 + footer_h
        img = np.full((h, w, 3), 255, np.uint8)
        for r in range(spec.rows + 1):
            for c in range(spec.cols + 1):
                color = 0 if (r + c) % 2 == 0 else 255
                x0 = int(round(margin + c * pitch))
                y0 = int(round(margin + r * pitch))
                x1 = int(round(margin + (c + 1) * pitch))
                y1 = int(round(margin + (r + 1) * pitch))
                cv2.rectangle(img, (x0, y0), (x1, y1), (color, color, color), -1)
        _footer(img, spec, margin + board_h, margin)
        return img

    radius = int(max(7, round(pitch * 0.13)))
    board_w = int(round(((spec.cols - 1) * 2 + 1) * pitch + radius * 2))
    board_h = int(round((spec.rows - 1) * pitch + radius * 2))
    w, h = board_w + margin * 2, board_h + margin * 2 + footer_h
    img = np.full((h, w, 3), 255, np.uint8)
    x_origin = margin + radius
    y_origin = margin + radius
    for r in range(spec.rows):
        for c in range(spec.cols):
            x = int(round(x_origin + (2 * c + (r % 2)) * pitch))
            y = int(round(y_origin + r * pitch))
            cv2.circle(img, (x, y), radius, (0, 0, 0), -1, cv2.LINE_AA)
    _footer(img, spec, int(round(y_origin + (spec.rows - 1) * pitch + radius)), margin)
    return img


def png_bytes(spec: BoardSpec) -> bytes:
    """輸出含 DPI metadata 的 PNG bytes。"""
    img = render_board(spec)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    out = io.BytesIO()
    Image.fromarray(rgb).save(out, format="PNG", dpi=(spec.dpi, spec.dpi))
    return out.getvalue()
