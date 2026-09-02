"""影像位深支援（NI Vision 對照：Grayscale U8/I16/SGL、RGB U32/U64）。

平台內部以 numpy dtype 表示：
- "u8"  = uint8（預設；灰階 HxW 或 BGR HxWx3）
- "u16" = uint16（16-bit 灰階或每通道 16-bit 的 RGB U64）
- "f32" = float32（SGL 浮點灰階；例如 FFT／校正中間結果）
（NI 的 I16 讀入時轉 u16 偏移或 f32；HSL U32 是編碼方式，平台以 color_convert 取 H/S/L 通道處理。）

工具透過 `Tool.accepts` 宣告可以吃的位深；ToolContext.image() 是**中央接縫**——
不在宣告內的位深會自動正規化成 u8（產生新陣列，不動輸入），所以任何工具丟什麼影像都不會炸。
顯示端 images.encode_image 本來就會把非 u8 正規化後編碼。
"""

from __future__ import annotations

import numpy as np

#: 位深代號（封閉集合；Tool.accepts 用）。
DEPTHS = ("u8", "u16", "f32")


def depth_of(image: np.ndarray) -> str:
    if image.dtype == np.uint8:
        return "u8"
    if image.dtype == np.uint16:
        return "u16"
    return "f32"  # float32/float64／其他一律當浮點


def normalize_u8(image: np.ndarray) -> np.ndarray:
    """非 u8 → u8（新陣列）。u16 固定右移 8（保持線性、可預期）；浮點 min-max 展開。"""
    if image.dtype == np.uint8:
        return image
    if image.dtype == np.uint16:
        return (image >> 8).astype(np.uint8)
    x = image.astype(np.float32)
    lo, hi = float(np.nanmin(x)), float(np.nanmax(x))
    scale = 255.0 / (hi - lo) if hi > lo else 1.0
    return np.clip((x - lo) * scale, 0, 255).astype(np.uint8)


def coerce(image: np.ndarray, accepts: tuple[str, ...]) -> np.ndarray:
    """依工具宣告的位深轉換：宣告內原樣通過，否則正規化成 u8。"""
    if depth_of(image) in accepts:
        return image
    return normalize_u8(image)


def strip_alpha(image: np.ndarray) -> np.ndarray:
    """BGRA → BGR（讀檔 IMREAD_UNCHANGED 會保留 alpha，平台不用）。"""
    if image.ndim == 3 and image.shape[2] == 4:
        return np.ascontiguousarray(image[:, :, :3])
    return image
