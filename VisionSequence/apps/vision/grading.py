"""條碼品質分級（WP-09）：ISO/IEC 15415（2D）、ISO/IEC 15416（1D）、AIM DPM（ISO/IEC TR 29158）。

規範實作、不是演算法創新：每個分項一個函式，附條文對照註解；門檻表集中在 THRESHOLDS，docs/vision-capabilities.html 的「Barcode quality grading」
一節逐項解釋給現場人員看。**不是認證用驗證器**——反射率用 8 位元灰階／255 代替校正過的絕對反射率、光學孔徑用圓盤濾波近似，
分項數值對得上市售驗證器的量級，等級不保證逐一相同。

解碼與符號結構靠 zxing-cpp（延後 import；`Result.extra` 給 UEC（未用錯誤更正）、Version（DataMatrix「12x12」、QR 版本）、QR 的 ECLevel），
座標由 `position` 四角（符號自身方向的 tl／tr／br／bl，像素含邊）。沒有 zxing-cpp 就 GradingError。

2D（15415）：decode、symbol_contrast、modulation（含錯誤更正容許：模組低於某級門檻視為壞碼字，重新算 UEC）、fixed_pattern_damage、
axial_nonuniformity、grid_nonuniformity、unused_error_correction；總評＝最低分。
DPM（29158）：與 15415 共用 decode／FPD／AN／GN／UEC，但對比改 cell_contrast（明暗格平均值之差／明格平均）、modulation 改 cell_modulation
（相對明暗格平均而非全域極值）、加 minimum_reflectance；允許前處理（中值）與較小孔徑。**與 15415 路徑分開走**，不混在一起。
1D（15416）：符號高度上取 10 條掃描線，每條算 decode、Rmin／Rmax、symbol_contrast、min_reflectance、edge_contrast、modulation、defects、decodability，
掃描線分數＝最低分，總評＝各掃描線分數平均（3.5 以上 A…）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

LETTERS = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}
LETTER_VALUE = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}

#: 分項門檻（≥ 或 ≤ 的方向見各函式）：(4 級, 3 級, 2 級, 1 級)
THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    "symbol_contrast": (0.70, 0.55, 0.40, 0.20),      # ISO 15415 7.3.2 / 15416：SC ≥
    "modulation_2d": (0.50, 0.40, 0.30, 0.20),        # ISO 15415 7.3.3：MOD ≥（每模組）
    "axial_nonuniformity": (0.06, 0.08, 0.10, 0.12),  # ISO 15415 7.3.5：AN ≤
    "grid_nonuniformity": (0.38, 0.50, 0.63, 0.75),   # ISO 15415 7.3.6：GN ≤（模組單位）
    "unused_error_correction": (0.62, 0.50, 0.37, 0.25),  # ISO 15415 7.3.7：UEC ≥
    "fixed_pattern_fraction": (0.0, 0.09, 0.13, 0.17),  # 固定圖形損傷比例 ≤（L 邊／時鐘軌／靜區／定時圖形）
    "cell_contrast": (0.30, 0.25, 0.20, 0.15),        # ISO 29158 DPM：CC ≥
    "cell_modulation": (0.50, 0.40, 0.30, 0.20),      # ISO 29158 DPM：CM ≥
    "modulation_1d": (0.70, 0.60, 0.50, 0.40),        # ISO 15416：MOD = ECmin / SC ≥
    "defects": (0.15, 0.20, 0.25, 0.30),              # ISO 15416：Defects = ERNmax / SC ≤
    "decodability": (0.62, 0.50, 0.37, 0.25),         # ISO 15416：V ≥
}
QUIET_ZONE = {"DataMatrix": 1, "QRCode": 4, "MicroQRCode": 2, "Aztec": 0}
LINEAR_FORMATS = {"EAN-13", "EAN-8", "UPC-A", "UPC-E", "Code 128", "Code 39", "Code 93", "Codabar", "ITF", "DataBar", "DataBar Expanded", "Code 32", "Code 39 Ext"}
#: 每種碼制的模組總數（1D 解碼度用；未列的碼制由元素寬度的 20 百分位估 X）
LINEAR_MODULES = {"EAN-13": 95, "UPC-A": 95, "EAN-8": 67, "UPC-E": 51}
#: DataMatrix ECC200（ISO 16022 Table 7）：(rows, cols) → (data codewords, EC codewords)
DM_CAPACITY = {
    (10, 10): (3, 5), (12, 12): (5, 7), (14, 14): (8, 10), (16, 16): (12, 12), (18, 18): (18, 14), (20, 20): (22, 18), (22, 22): (30, 20),
    (24, 24): (36, 24), (26, 26): (44, 28), (32, 32): (62, 36), (36, 36): (86, 42), (40, 40): (114, 48), (44, 44): (144, 56), (48, 48): (174, 68),
    (52, 52): (204, 84), (64, 64): (280, 112), (72, 72): (368, 144), (80, 80): (456, 192), (88, 88): (576, 224), (96, 96): (696, 272),
    (104, 104): (816, 336), (120, 120): (1050, 408), (132, 132): (1304, 496), (144, 144): (1558, 620),
    (8, 18): (5, 7), (8, 32): (10, 11), (12, 26): (16, 14), (12, 36): (22, 18), (16, 36): (32, 24), (16, 48): (49, 28),
}
#: QR 每版本總碼字數（ISO 18004 Table 9）
QR_TOTAL = [26, 44, 70, 100, 134, 172, 196, 242, 292, 346, 404, 466, 532, 581, 655, 733, 815, 901, 991, 1085, 1156, 1258, 1364, 1474, 1588, 1706, 1828, 1921,
            2051, 2185, 2323, 2465, 2611, 2761, 2876, 3034, 3196, 3362, 3532, 3706]
#: QR 1～10 版每級的 EC 碼字總數（ISO 18004 Table 9：每塊 EC 數 × 塊數）；11 版以上以典型比例估
QR_EC = {
    1: {"L": 7, "M": 10, "Q": 13, "H": 17}, 2: {"L": 10, "M": 16, "Q": 22, "H": 28}, 3: {"L": 15, "M": 26, "Q": 36, "H": 44},
    4: {"L": 20, "M": 36, "Q": 52, "H": 64}, 5: {"L": 26, "M": 48, "Q": 72, "H": 88}, 6: {"L": 36, "M": 64, "Q": 96, "H": 112},
    7: {"L": 40, "M": 72, "Q": 108, "H": 130}, 8: {"L": 48, "M": 88, "Q": 132, "H": 156}, 9: {"L": 60, "M": 110, "Q": 160, "H": 192},
    10: {"L": 72, "M": 130, "Q": 192, "H": 224},
}
QR_EC_RATIO = {"L": 0.20, "M": 0.38, "Q": 0.55, "H": 0.65}
#: QR 對位圖形中心座標（ISO 18004 Annex E），版本 2～40
QR_ALIGN = {
    2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50], 11: [6, 30, 54],
    12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66], 15: [6, 26, 48, 70], 16: [6, 26, 50, 74], 17: [6, 30, 54, 78], 18: [6, 30, 56, 82],
    19: [6, 30, 58, 86], 20: [6, 34, 62, 90], 21: [6, 28, 50, 72, 94], 22: [6, 26, 50, 74, 98], 23: [6, 30, 54, 78, 102], 24: [6, 28, 54, 80, 106],
    25: [6, 32, 58, 84, 110], 26: [6, 30, 58, 86, 114], 27: [6, 34, 62, 90, 118], 28: [6, 26, 50, 74, 98, 122], 29: [6, 30, 54, 78, 102, 126],
    30: [6, 26, 52, 78, 104, 130], 31: [6, 30, 56, 82, 108, 134], 32: [6, 34, 60, 86, 112, 138], 33: [6, 30, 58, 86, 114, 142],
    34: [6, 34, 62, 90, 118, 146], 35: [6, 30, 54, 78, 102, 126, 150], 36: [6, 24, 50, 76, 102, 128, 154], 37: [6, 28, 54, 80, 106, 132, 158],
    38: [6, 32, 58, 84, 110, 136, 162], 39: [6, 26, 54, 82, 110, 138, 166], 40: [6, 30, 58, 86, 114, 142, 170],
}
SYMBOLOGY_OPTIONS = [
    {"value": "auto", "label": "Any"}, {"value": "datamatrix", "label": "Data Matrix"}, {"value": "qr", "label": "QR Code"},
    {"value": "ean_upc", "label": "EAN / UPC"}, {"value": "code128", "label": "Code 128"}, {"value": "code39", "label": "Code 39"},
]


class GradingError(Exception):
    """分級做不下去（缺解碼器、沒有符號、碼制不支援分級）。"""


def zxing_available() -> bool:
    try:
        import zxingcpp  # noqa: F401
    except ImportError:
        return False
    return True


def _zx():
    try:
        import zxingcpp
    except ImportError:
        raise GradingError("Barcode grading needs the zxing-cpp package (pip install zxing-cpp)") from None
    return zxingcpp


def formats_for(symbology: str):
    zx = _zx()
    B = zx.BarcodeFormat
    return {
        "datamatrix": B.DataMatrix, "qr": B.QRCode | B.MicroQRCode, "ean_upc": B.EAN13 | B.EAN8 | B.UPCA | B.UPCE, "code128": B.Code128,
        "code39": B.Code39,
    }.get(symbology, B.DataMatrix | B.QRCode | B.MicroQRCode | B.Aztec | B.EAN13 | B.EAN8 | B.UPCA | B.UPCE | B.Code128 | B.Code39 | B.Code93 | B.ITF)


@dataclass
class Symbol:
    text: str
    fmt: str                      # zxing 名稱："Data Matrix"／"QR Code"／"EAN-13"…
    corners: np.ndarray           # (4, 2) tl, tr, br, bl（符號自身方向；像素含邊）
    linear: bool
    rows: int = 0
    cols: int = 0
    version: str = ""
    ec_level: str = ""
    uec: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return {"Data Matrix": "DataMatrix", "QR Code": "QRCode", "Micro QR Code": "MicroQRCode", "Aztec": "Aztec"}.get(self.fmt, self.fmt)


def decode(gray: np.ndarray, symbology: str = "auto", pure: bool = False) -> list[Symbol]:
    """zxing 解碼：回每個符號的內容、四角、模組數與 UEC。gray 是 u8 單通道。"""
    zx = _zx()
    out: list[Symbol] = []
    src = np.ascontiguousarray(gray)
    results = []
    for binarizer in (zx.Binarizer.LocalAverage, zx.Binarizer.GlobalHistogram, zx.Binarizer.FixedThreshold):
        results = zx.read_barcodes(src, formats=formats_for(symbology), try_rotate=True, try_downscale=True, try_invert=False, is_pure=pure, binarizer=binarizer)
        if any(r.valid for r in results):
            break
    for r in results:
        if not r.valid:
            continue
        p = r.position
        corners = np.array([[p.top_left.x, p.top_left.y], [p.top_right.x, p.top_right.y], [p.bottom_right.x, p.bottom_right.y], [p.bottom_left.x, p.bottom_left.y]], dtype=np.float64)
        extra = dict(r.extra or {})
        fmt = str(r.format)
        fmt = fmt.split(".")[-1] if fmt.startswith("BarcodeFormat.") else fmt
        sym = Symbol(text=str(r.text), fmt=fmt, corners=corners, linear=fmt in LINEAR_FORMATS, extra=extra, ec_level=str(r.ec_level or ""))
        version = str(extra.get("Version", ""))
        sym.version = version
        if "x" in version:
            a, b = version.lower().split("x")
            sym.rows, sym.cols = int(a), int(b)
        elif version.isdigit() and sym.kind == "QRCode":
            n = 4 * int(version) + 17
            sym.rows = sym.cols = n
        elif version.isdigit() and sym.kind == "MicroQRCode":
            n = 2 * int(version) + 9
            sym.rows = sym.cols = n
        if "UEC" in extra:
            try:
                sym.uec = float(extra["UEC"])
            except (TypeError, ValueError):
                sym.uec = None
        out.append(sym)
    return out


# ---------------------------------------------------------------- 共用：等級
def grade_ge(value: float, key: str) -> int:
    """值越大越好：≥ 門檻取級。"""
    t = THRESHOLDS[key]
    for g, th in zip((4, 3, 2, 1), t):
        if value >= th:
            return g
    return 0


def grade_le(value: float, key: str) -> int:
    """值越小越好：≤ 門檻取級。"""
    t = THRESHOLDS[key]
    for g, th in zip((4, 3, 2, 1), t):
        if value <= th:
            return g
    return 0


def _param(key: str, label: str, value: Any, grade: int, note: str = "") -> dict[str, Any]:
    out = {"key": key, "label": label, "value": value if value is None or isinstance(value, str) else round(float(value), 4), "grade": int(grade), "letter": LETTERS[int(grade)]}
    if note:
        out["note"] = note
    return out


def letter_of(value: float) -> str:
    """1D 的平均分數 → 字母（ISO 15416：3.5～4.0 A、2.5～3.4 B、1.5～2.4 C、0.5～1.4 D）。"""
    if value >= 3.5:
        return "A"
    if value >= 2.5:
        return "B"
    if value >= 1.5:
        return "C"
    if value >= 0.5:
        return "D"
    return "F"


def ec_codewords(sym: Symbol) -> int:
    """錯誤更正碼字數（調變的錯誤更正容許用）。查不到回 0（＝不給容許）。"""
    if sym.kind == "DataMatrix":
        return DM_CAPACITY.get((sym.rows, sym.cols), (0, 0))[1]
    if sym.kind == "QRCode" and sym.version.isdigit():
        v = int(sym.version)
        lvl = sym.ec_level or "M"
        if v in QR_EC:
            return QR_EC[v].get(lvl, QR_EC[v]["M"])
        if 1 <= v <= 40:
            return int(round(QR_TOTAL[v - 1] * QR_EC_RATIO.get(lvl, 0.38)))
    return 0


# ---------------------------------------------------------------- 2D：格點取樣
def disc_filter(gray: np.ndarray, diameter: float) -> np.ndarray:
    """光學孔徑：直徑 diameter px 的圓盤平均（ISO 15415 的合成孔徑），回 float32 0..1。"""
    f = gray.astype(np.float32) / 255.0
    d = int(round(diameter))
    if d >= 2:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d)).astype(np.float32)
        k /= k.sum()
        f = cv2.filter2D(f, -1, k, borderType=cv2.BORDER_REPLICATE)
    return f


@dataclass
class Grid:
    """模組座標 (u, v) → 影像座標的透視映射；u 沿欄（0..cols）、v 沿列（0..rows），像素中心在整數座標。"""

    H: np.ndarray
    rows: int
    cols: int
    pitch_x: float
    pitch_y: float

    def to_image(self, uv: np.ndarray) -> np.ndarray:
        pts = np.asarray(uv, dtype=np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.H).reshape(-1, 2)

    def sample(self, field: np.ndarray, uv: np.ndarray) -> np.ndarray:
        xy = self.to_image(uv).astype(np.float32)
        h, w = field.shape[:2]
        mx = np.clip(xy[:, 0], 0, w - 1).reshape(1, -1)
        my = np.clip(xy[:, 1], 0, h - 1).reshape(1, -1)
        return cv2.remap(field, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(-1)

    def centres(self, r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
        vv, uu = np.mgrid[r0:r1, c0:c1]
        return np.column_stack([uu.reshape(-1) + 0.5, vv.reshape(-1) + 0.5]).astype(np.float64)


def make_grid(sym: Symbol) -> Grid:
    """由 zxing 四角建格點：角點是含邊像素，往外推半個像素成為符號外緣。"""
    tl, tr, br, bl = sym.corners
    ex = tr - tl
    ey = bl - tl
    nx = np.linalg.norm(ex) or 1.0
    ny = np.linalg.norm(ey) or 1.0
    ex, ey = ex / nx, ey / ny
    dst = np.array([tl - 0.5 * ex - 0.5 * ey, tr + 0.5 * ex - 0.5 * ey, br + 0.5 * ex + 0.5 * ey, bl - 0.5 * ex + 0.5 * ey], dtype=np.float32)
    src = np.array([[0, 0], [sym.cols, 0], [sym.cols, sym.rows], [0, sym.rows]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src, dst)
    px = (np.linalg.norm(dst[1] - dst[0]) + np.linalg.norm(dst[2] - dst[3])) / 2 / max(1, sym.cols)
    py = (np.linalg.norm(dst[3] - dst[0]) + np.linalg.norm(dst[2] - dst[1])) / 2 / max(1, sym.rows)
    return Grid(H=H, rows=sym.rows, cols=sym.cols, pitch_x=float(px), pitch_y=float(py))


def _dark_side_modules(sym: Symbol, side: str) -> list[int]:
    """每一邊「外緣模組必為暗」的模組索引（沿該邊由 tl 或 tr 起算）：DM 的 L 邊全暗、時鐘軌偶數格暗（相位在 refine 裡兩種擇優）；QR 三個尋像圖形外緣各 7 格。"""
    r, c = sym.rows, sym.cols
    if sym.kind == "DataMatrix":
        if side == "left":
            return list(range(r))
        if side == "bottom":
            return list(range(c))
        if side == "top":
            return list(range(0, c, 2))
        return list(range(0, r, 2))
    if sym.kind == "QRCode":
        n = r
        if side in ("top", "left"):
            return list(range(7)) + list(range(n - 7, n))
        return list(range(7))  # right：右上尋像圖形；bottom：左下尋像圖形
    return []


def _edge_offset(prof: np.ndarray, ts: np.ndarray, gt: float) -> float | None:
    """由外往內第一個亮→暗越過 GT 的位置（模組單位；負＝在理想邊界外側）。"""
    above = prof > gt
    for k in range(1, len(prof)):
        if above[k - 1] and not above[k]:
            a, b = prof[k - 1], prof[k]
            return float(ts[k - 1] + (ts[k] - ts[k - 1]) * ((gt - a) / (b - a) if b != a else 0.5))
    return None


def refine_grid(sym: Symbol, grid: Grid, field: np.ndarray, gt: float, passes: int = 2) -> Grid:
    """參考格點精修（ISO 15415 的格點由符號自身的固定圖形決定）：對每一邊，在外緣必暗的模組中心取垂直於邊的剖面（外→內），
    找亮→暗越過 GT 的位置，最小平方擬合該邊的直線，四邊兩兩相交得新角點。zxing 的角點對 QR 是邊界、對 Data Matrix 是含邊像素，
    差一個像素會讓小模組的調變掉一級。精修偏離超過 1.5 模組視為失敗、保留原格點。"""
    r, c = grid.rows, grid.cols
    ts = np.linspace(-1.5, 1.5, 61)
    for _ in range(passes):
        lines: dict[str, tuple[float, float]] = {}
        for side in ("top", "right", "bottom", "left"):
            mods = _dark_side_modules(sym, side)
            if not mods:
                return grid
            phases = (0, 1) if sym.kind == "DataMatrix" and side in ("top", "right") else (0,)
            best: list[tuple[float, float]] = []
            for phase in phases:
                pts: list[tuple[float, float]] = []
                limit = c if side in ("top", "bottom") else r
                for m in mods:
                    m2 = m + phase
                    if m2 >= limit:
                        continue
                    along = m2 + 0.5
                    if side == "top":
                        uv = np.column_stack([np.full_like(ts, along), ts])
                    elif side == "bottom":
                        uv = np.column_stack([np.full_like(ts, along), r - ts])
                    elif side == "left":
                        uv = np.column_stack([ts, np.full_like(ts, along)])
                    else:
                        uv = np.column_stack([c - ts, np.full_like(ts, along)])
                    hit = _edge_offset(grid.sample(field, uv), ts, gt)
                    if hit is not None and abs(hit) < 0.75:
                        pts.append((along, hit))
                if len(pts) > len(best):
                    best = pts
            if len(best) < 2:
                return grid
            arr = np.array(best)
            A = np.column_stack([np.ones(len(arr)), arr[:, 0]])
            coef, *_ = np.linalg.lstsq(A, arr[:, 1], rcond=None)
            lines[side] = (float(coef[0]), float(coef[1]))

        def side_point(side: str, u: float) -> np.ndarray:
            a, b = lines[side]
            d = a + b * u
            if side == "top":
                return np.array([u, d])
            if side == "bottom":
                return np.array([u, r - d])
            if side == "left":
                return np.array([d, u])
            return np.array([c - d, u])

        def intersect(s1: str, s2: str) -> np.ndarray:
            p1, p2 = side_point(s1, 0.0), side_point(s1, 1.0)
            p3, p4 = side_point(s2, 0.0), side_point(s2, 1.0)
            d1, d2 = p2 - p1, p4 - p3
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) < 1e-9:
                return p1
            t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
            return p1 + d1 * t

        new_uv = np.array([intersect("top", "left"), intersect("top", "right"), intersect("bottom", "right"), intersect("bottom", "left")], dtype=np.float64)
        if np.abs(new_uv - np.array([[0, 0], [c, 0], [c, r], [0, r]])).max() > 1.5:
            return grid
        dst = grid.to_image(new_uv).astype(np.float32)
        src = np.array([[0, 0], [c, 0], [c, r], [0, r]], dtype=np.float32)
        H = cv2.getPerspectiveTransform(src, dst)
        px = (np.linalg.norm(dst[1] - dst[0]) + np.linalg.norm(dst[2] - dst[3])) / 2 / max(1, c)
        py = (np.linalg.norm(dst[3] - dst[0]) + np.linalg.norm(dst[2] - dst[1])) / 2 / max(1, r)
        grid = Grid(H=H, rows=r, cols=c, pitch_x=float(px), pitch_y=float(py))
    return grid


def sample_modules(grid: Grid, field: np.ndarray, quiet: int) -> tuple[np.ndarray, np.ndarray]:
    """符號模組反射率 (rows, cols) 與含靜區的擴大取樣 (rows+2q, cols+2q)。"""
    inner = grid.sample(field, grid.centres(0, grid.rows, 0, grid.cols)).reshape(grid.rows, grid.cols)
    if quiet > 0:
        outer = grid.sample(field, grid.centres(-quiet, grid.rows + quiet, -quiet, grid.cols + quiet)).reshape(grid.rows + 2 * quiet, grid.cols + 2 * quiet)
    else:
        outer = inner
    return inner, outer


# ---------------------------------------------------------------- 2D：分項
def symbol_contrast(outer: np.ndarray) -> tuple[float, float, float]:
    """ISO 15415 7.3.2：SC = Rmax − Rmin（含靜區的符號區域）。"""
    rmax = float(outer.max())
    rmin = float(outer.min())
    return rmax - rmin, rmax, rmin


def modulation_2d(inner: np.ndarray, gt: float, sc: float, uec: float | None, ec_total: int) -> tuple[int, float, dict[str, Any]]:
    """ISO 15415 7.3.3／7.3.4：MOD = 2·|R − GT| / SC（每模組）；等級與錯誤更正合併——
    對每一級 L，模組低於該級門檻者視為壞碼字（保守：一模組一碼字），UEC' = UEC − 2·bad/EC，該級的分數 = min(L, grade(UEC'))，取最高。"""
    if sc <= 1e-6:
        return 0, 0.0, {"min_mod": 0.0}
    mod = 2.0 * np.abs(inner - gt) / sc
    min_mod = float(mod.min())
    best = 0
    detail: dict[str, Any] = {"min_mod": round(min_mod, 4), "levels": {}}
    for level, thr in zip((4, 3, 2, 1), THRESHOLDS["modulation_2d"]):
        bad = int((mod < thr).sum())
        if bad == 0:
            g = level
        elif uec is not None and ec_total > 0:
            uec2 = max(0.0, uec - 2.0 * bad / ec_total)
            g = min(level, grade_ge(uec2, "unused_error_correction"))
        else:
            g = 0
        detail["levels"][str(level)] = {"below": bad, "grade": g}
        best = max(best, g)
    return best, min_mod, detail


def axial_nonuniformity(grid: Grid) -> float:
    """ISO 15415 7.3.5：AN = |Xavg − Yavg| / ((Xavg + Yavg) / 2)。"""
    return abs(grid.pitch_x - grid.pitch_y) / max(1e-6, (grid.pitch_x + grid.pitch_y) / 2)


def _transitions(profile: np.ndarray, gt: float, step: float) -> list[float]:
    """剖面越過 GT 的位置（線性內插，單位＝模組）。"""
    out = []
    above = profile > gt
    for k in range(1, len(profile)):
        if above[k] != above[k - 1]:
            a, b = profile[k - 1], profile[k]
            t = (gt - a) / (b - a) if b != a else 0.5
            out.append(((k - 1) + t) * step)
    return out


def grid_nonuniformity(grid: Grid, field: np.ndarray, gt: float, max_lines: int = 48) -> tuple[float, int]:
    """ISO 15415 7.3.6：沿每一列與每一欄的中心線取密集剖面（每模組 10 點），每個越過 GT 的轉換點與最近的理想格線之差，取最大（模組單位）。
    大符號最多取 max_lines 條均勻分佈的列／欄。"""
    worst = 0.0
    count = 0
    per = 10
    for axis, n_lines, length in ((0, grid.rows, grid.cols), (1, grid.cols, grid.rows)):
        idx = np.unique(np.linspace(0, n_lines - 1, min(n_lines, max_lines)).round().astype(int))
        n = int(length * per) + 1
        ts = np.linspace(0.0, float(length), n)
        for i in idx:
            c = i + 0.5
            uv = np.column_stack([ts, np.full(n, c)]) if axis == 0 else np.column_stack([np.full(n, c), ts])
            prof = grid.sample(field, uv)
            for pos in _transitions(prof, gt, float(length) / max(1, n - 1)):
                dev = abs(pos - round(pos))
                worst = max(worst, dev)
                count += 1
    return worst, count


def _fraction_grade(frac: float) -> int:
    return grade_le(frac, "fixed_pattern_fraction")


def _count_grade(n: int) -> int:
    return {0: 4, 1: 3, 2: 2, 3: 1}.get(int(n), 0)


def fixed_pattern_datamatrix(inner: np.ndarray, outer: np.ndarray, gt: float, quiet: int) -> tuple[int, dict[str, Any]]:
    """ISO 16022 Annex M（結構）：L 形定位邊（左欄、底列全暗）、時鐘軌（頂列、右欄明暗交替，角落固定）、靜區（全亮）。
    每段以損傷模組比例定級。（大符號的內部對位圖形未檢查。）"""
    dark = inner < gt
    rows, cols = dark.shape
    segs: dict[str, float] = {}
    segs["left_side"] = float((~dark[:, 0]).mean())
    segs["bottom_side"] = float((~dark[rows - 1, :]).mean())
    top = dark[0, :]
    right = dark[:, cols - 1]
    # 時鐘軌：頂列由左到右從暗開始交替（左上角暗）、右欄由上到下從亮開始…實際起相位依尺寸而異，取兩種相位中較好的
    exp_a = np.array([(k % 2 == 0) for k in range(cols)])
    top_bad = min(int((top != exp_a).sum()), int((top != ~exp_a).sum()))
    exp_b = np.array([(k % 2 == 0) for k in range(rows)])
    right_bad = min(int((right != exp_b).sum()), int((right != ~exp_b).sum()))
    segs["clock_track"] = (top_bad + right_bad) / float(cols + rows)
    if quiet > 0:
        q = outer < gt
        ring = np.ones_like(q, dtype=bool)
        ring[quiet:-quiet, quiet:-quiet] = False
        segs["quiet_zone"] = float(q[ring].mean())
    grades = {k: _fraction_grade(v) for k, v in segs.items()}
    return min(grades.values()), {"segments": {k: {"damage": round(v, 4), "grade": grades[k]} for k, v in segs.items()}}


def _format_bits(dark: np.ndarray) -> tuple[list[int], list[int]]:
    """QR 格式資訊的 15 位元兩份（ISO 18004 7.9）：左上一份、另一份分佈在右上與左下。"""
    n = dark.shape[0]
    a = []
    for i in range(0, 6):
        a.append(int(dark[8, i]))
    a.append(int(dark[8, 7]))
    a.append(int(dark[8, 8]))
    a.append(int(dark[7, 8]))
    for i in range(5, -1, -1):
        a.append(int(dark[i, 8]))
    b = []
    for i in range(n - 1, n - 8, -1):
        b.append(int(dark[i, 8]))
    for i in range(n - 8, n):
        b.append(int(dark[8, i]))
    return a, b


def _valid_formats() -> list[int]:
    out = []
    for data in range(32):
        v = data << 10
        g = 0x537
        for i in range(14, 9, -1):
            if v & (1 << i):
                v ^= g << (i - 10)
        out.append(((data << 10) | v) ^ 0x5412)
    return out


_FORMATS = _valid_formats()


def _bits_to_int(bits: list[int]) -> int:
    v = 0
    for b in bits:
        v = (v << 1) | (1 if b else 0)
    return v


def fixed_pattern_qr(inner: np.ndarray, outer: np.ndarray, gt: float, quiet: int, version: int) -> tuple[int, dict[str, Any]]:
    """ISO 18004 Annex（結構）：三個尋像圖形（7×7＋分隔一圈＝8×8 區）、定時圖形、對位圖形、格式資訊（BCH 位元錯誤）、靜區（4 模組）。"""
    dark = inner < gt
    n = dark.shape[0]
    segs: dict[str, Any] = {}
    finder = np.array([[1, 1, 1, 1, 1, 1, 1, 0], [1, 0, 0, 0, 0, 0, 1, 0], [1, 0, 1, 1, 1, 0, 1, 0], [1, 0, 1, 1, 1, 0, 1, 0], [1, 0, 1, 1, 1, 0, 1, 0],
                       [1, 0, 0, 0, 0, 0, 1, 0], [1, 1, 1, 1, 1, 1, 1, 0], [0, 0, 0, 0, 0, 0, 0, 0]], dtype=bool)
    grades: dict[str, int] = {}
    for name, block, ref in (("finder_tl", dark[0:8, 0:8], finder), ("finder_tr", dark[0:8, n - 8:n], finder[:, ::-1]), ("finder_bl", dark[n - 8:n, 0:8], finder[::-1, :])):
        bad = int((block != ref).sum())
        segs[name] = {"damaged_modules": bad}
        grades[name] = _count_grade(bad)
    timing_row = dark[6, 8:n - 8]
    timing_col = dark[8:n - 8, 6]
    exp = np.array([(k % 2 == 0) for k in range(len(timing_row))])
    t_bad = int((timing_row != exp).sum()) + int((timing_col != exp).sum())
    frac = t_bad / max(1, 2 * len(timing_row))
    segs["timing"] = {"damage": round(frac, 4)}
    grades["timing"] = _fraction_grade(frac)
    # 對位圖形（5×5：外暗、中亮、心暗）
    if version in QR_ALIGN:
        ap = np.array([[1, 1, 1, 1, 1], [1, 0, 0, 0, 1], [1, 0, 1, 0, 1], [1, 0, 0, 0, 1], [1, 1, 1, 1, 1]], dtype=bool)
        coords = QR_ALIGN[version]
        worst = 0
        cnt = 0
        for cy in coords:
            for cx in coords:
                if (cy == 6 and cx == 6) or (cy == 6 and cx == coords[-1]) or (cy == coords[-1] and cx == 6):
                    continue  # 與尋像圖形重疊的三個位置沒有對位圖形
                block = dark[cy - 2:cy + 3, cx - 2:cx + 3]
                if block.shape == (5, 5):
                    worst = max(worst, int((block != ap).sum()))
                    cnt += 1
        if cnt:
            segs["alignment"] = {"patterns": cnt, "worst_damaged_modules": worst}
            grades["alignment"] = _count_grade(worst)
    # 格式資訊：兩份各取與最近合法碼的漢明距離，取較好的一份
    fa, fb = _format_bits(dark)
    best = 15
    for bits in (fa, fb):
        v = _bits_to_int(bits)
        best = min(best, min(bin(v ^ f).count("1") for f in _FORMATS))
    segs["format_info"] = {"bit_errors": best}
    grades["format_info"] = _count_grade(best)
    if quiet > 0:
        q = outer < gt
        ring = np.ones_like(q, dtype=bool)
        ring[quiet:-quiet, quiet:-quiet] = False
        frac = float(q[ring].mean())
        segs["quiet_zone"] = {"damage": round(frac, 4)}
        grades["quiet_zone"] = _fraction_grade(frac)
    for k in segs:
        segs[k]["grade"] = grades[k]
    return min(grades.values()), {"segments": segs}


def grade_2d(gray: np.ndarray, sym: Symbol, standard: str = "iso15415", aperture: float = 0.0, dpm_filter: str = "none") -> dict[str, Any]:
    """一個 2D 符號的全部分項與總評。standard：iso15415 或 aim_dpm。"""
    if sym.rows < 8 or sym.cols < 8:
        raise GradingError(f"{sym.fmt} symbols cannot be graded (module grid unknown)")
    grid = make_grid(sym)
    pitch = (grid.pitch_x + grid.pitch_y) / 2
    dpm = standard == "aim_dpm"
    src = gray
    if dpm and dpm_filter == "median":
        src = cv2.medianBlur(gray, 3)
    ap = aperture if aperture > 0 else pitch * (0.5 if dpm else 0.8)
    field = disc_filter(src, ap)
    quiet = QUIET_ZONE.get(sym.kind, 1)
    inner, outer = sample_modules(grid, field, quiet)
    gt0 = (float(outer.max()) + float(outer.min())) / 2
    grid = refine_grid(sym, grid, field, gt0)
    pitch = (grid.pitch_x + grid.pitch_y) / 2
    inner, outer = sample_modules(grid, field, quiet)
    params: list[dict[str, Any]] = []
    detail: dict[str, Any] = {"standard": standard, "symbology": sym.fmt, "version": sym.version, "modules": [sym.rows, sym.cols], "pitch_px": round(pitch, 3), "aperture_px": round(ap, 2)}
    params.append(_param("decode", "Decode", "ok", 4))
    sc, rmax, rmin = symbol_contrast(outer)
    gt = (rmax + rmin) / 2
    detail.update({"rmax": round(rmax, 4), "rmin": round(rmin, 4), "global_threshold": round(gt, 4)})
    ec_total = ec_codewords(sym)
    if not dpm:
        params.append(_param("symbol_contrast", "Symbol contrast", sc, grade_ge(sc, "symbol_contrast")))
        g, min_mod, md = modulation_2d(inner, gt, sc, sym.uec, ec_total)
        params.append(_param("modulation", "Modulation", min_mod, g, note=f"{md['levels']['4']['below']} modules below the 0.50 threshold" if md.get("levels") else ""))
        detail["modulation"] = md
    else:
        # ISO/IEC TR 29158：明暗格由格點反射率的 Otsu 分界決定；CC = (ML − MD) / ML；CM 相對明暗格平均
        vals = inner.reshape(-1)
        thr = _otsu(vals)
        light = vals[vals >= thr]
        darkv = vals[vals < thr]
        ml = float(light.mean()) if light.size else rmax
        md_ = float(darkv.mean()) if darkv.size else rmin
        cc = (ml - md_) / max(1e-6, ml)
        params.append(_param("cell_contrast", "Cell contrast", cc, grade_ge(cc, "cell_contrast")))
        t = (ml + md_) / 2
        cm = np.where(inner >= t, (inner - t) / max(1e-6, ml - t), (t - inner) / max(1e-6, t - md_))
        g, min_cm, cmd = modulation_2d(inner, t, max(1e-6, ml - md_), sym.uec, ec_total)
        params.append(_param("cell_modulation", "Cell modulation", float(cm.min()), g))
        detail["cell_modulation"] = cmd
        # ISO 29158 最低反射率：Rmin 要 ≥ 5%·Rmax——這是曝光檢查（暗格不能被壓到全黑，否則影像沒有可量的動態範圍），不是對比檢查
        params.append(_param("minimum_reflectance", "Minimum reflectance", rmin / max(rmax, 1e-6), 4 if rmin >= 0.05 * rmax else 0, note="Rmin as a fraction of Rmax; below 5% the image is under-exposed for DPM"))
        detail["cell_means"] = {"light": round(ml, 4), "dark": round(md_, 4), "threshold": round(t, 4)}
    if sym.kind == "DataMatrix":
        fg, fd = fixed_pattern_datamatrix(inner, outer, gt, quiet)
    elif sym.kind in ("QRCode",):
        fg, fd = fixed_pattern_qr(inner, outer, gt, quiet, int(sym.version) if sym.version.isdigit() else 0)
    else:
        fg, fd = 4, {"segments": {}, "note": "fixed patterns not checked for this symbology"}
    params.append(_param("fixed_pattern_damage", "Fixed pattern damage", min(v.get("damage", v.get("damaged_modules", v.get("worst_damaged_modules", v.get("bit_errors", 0)))) if isinstance(v, dict) else v for v in fd["segments"].values()) if fd["segments"] else 0, fg))
    detail["fixed_pattern"] = fd
    an = axial_nonuniformity(grid)
    params.append(_param("axial_nonuniformity", "Axial non-uniformity", an, grade_le(an, "axial_nonuniformity")))
    detail["pitch"] = {"x": round(grid.pitch_x, 3), "y": round(grid.pitch_y, 3)}
    gn, n_edges = grid_nonuniformity(grid, field, gt)
    params.append(_param("grid_nonuniformity", "Grid non-uniformity", gn, grade_le(gn, "grid_nonuniformity"), note=f"{n_edges} edges checked"))
    if sym.uec is not None:
        params.append(_param("unused_error_correction", "Unused error correction", sym.uec, grade_ge(sym.uec, "unused_error_correction")))
    else:
        params.append(_param("unused_error_correction", "Unused error correction", None, 4, note="not reported by the decoder"))
    overall = min(p["grade"] for p in params)
    return {"grade": LETTERS[overall], "grade_value": float(overall), "params": params, "detail": detail, "text": sym.text, "symbology": sym.fmt, "corners": sym.corners}


def _otsu(vals: np.ndarray) -> float:
    v = np.clip(vals, 0, 1)
    hist, edges = np.histogram(v, bins=64, range=(0.0, 1.0))
    total = hist.sum()
    if total == 0:
        return 0.5
    best_t, best_var = 0.5, -1.0
    w0 = 0.0
    sum0 = 0.0
    centres = (edges[:-1] + edges[1:]) / 2
    total_mean = float((hist * centres).sum() / total)
    for i in range(len(hist)):
        w0 += hist[i]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        sum0 += hist[i] * centres[i]
        m0 = sum0 / w0
        m1 = (total_mean * total - sum0) / w1
        var = w0 * w1 * (m0 - m1) ** 2
        if var > best_var:
            best_var, best_t = var, float(edges[i + 1])
    return best_t


# ---------------------------------------------------------------- 1D：掃描反射率剖面
def _runs(dark: np.ndarray) -> list[tuple[int, int, bool]]:
    out = []
    start = 0
    for k in range(1, len(dark) + 1):
        if k == len(dark) or dark[k] != dark[start]:
            out.append((start, k, bool(dark[start])))
            start = k
    return out


def scan_profile_params(profile: np.ndarray, fmt: str, sample_step: float) -> dict[str, Any]:
    """ISO 15416 一條掃描線：Rmax／Rmin／SC／GT、元素、ECmin、MOD、Defects、Decodability。profile 是沿掃描線的反射率（含靜區），sample_step＝每樣本像素數。"""
    rmax = float(profile.max())
    rmin = float(profile.min())
    sc = rmax - rmin
    gt = (rmax + rmin) / 2
    out: dict[str, Any] = {"rmax": rmax, "rmin": rmin, "symbol_contrast": sc}
    if sc < 1e-6:
        out.update({"edge_contrast": 0.0, "modulation": 0.0, "defects": 1.0, "decodability": 0.0, "elements": 0})
        return out
    dark = profile < gt
    runs = _runs(dark)
    # 去掉兩端的靜區（亮）
    bars = [r for r in runs if r[2]]
    if not bars:
        out.update({"edge_contrast": 0.0, "modulation": 0.0, "defects": 1.0, "decodability": 0.0, "elements": 0})
        return out
    first = bars[0][0]
    last = bars[-1][1]
    elems = [r for r in runs if r[0] >= first and r[1] <= last]
    # 邊緣對比 ECmin：相鄰元素的 (space peak − bar valley)
    extremes = []
    for a, b, is_dark in elems:
        seg = profile[a:b]
        extremes.append(float(seg.min()) if is_dark else float(seg.max()))
    ec_min = min(abs(extremes[i + 1] - extremes[i]) for i in range(len(extremes) - 1)) if len(extremes) > 1 else sc
    out["edge_contrast"] = ec_min
    out["modulation"] = ec_min / sc
    # Defects（ISO 15416 6.4.6）：元素反射率不均勻 ERN ＝ 一個元素內「最高峰 − 最低谷」，但只有元素內部真的有反向極值時才算——
    # 空白裡的黑點是兩個峰之間的谷、條裡的空洞是兩個谷之間的峰；單峰／單谷的元素 ERN ＝ 0
    ern = 0.0
    for a, b, is_dark in elems:
        seg = profile[a:b]
        if len(seg) < 3:
            continue
        mid = seg[1:-1]
        left, right = seg[:-2], seg[2:]
        # 平底的谷／平頂的峰（孔徑濾波後常見）：一側用 ≤／≥ 取平台的最後一點
        if is_dark:
            peaks = mid[(mid >= left) & (mid > right)]  # 條內部的亮峰（空洞）
            if peaks.size:
                ern = max(ern, float(peaks.max() - seg.min()))
        else:
            valleys = mid[(mid <= left) & (mid < right)]  # 空白內部的暗谷（黑點）
            if valleys.size:
                ern = max(ern, float(seg.max() - valleys.min()))
    out["defects"] = ern / sc
    # Decodability：元素寬度對名目模組寬度的偏差（參考解碼的簡化：以元素寬度為準，V = 1 − 2·max|w/Z − round(w/Z)|）
    widths = np.array([(b - a) * sample_step for a, b, _ in elems], dtype=np.float64)
    total_modules = LINEAR_MODULES.get(fmt)
    if total_modules:
        z = float((last - first) * sample_step) / total_modules
    else:
        z = float(np.percentile(widths, 20)) if len(widths) else 1.0
    ratios = widths / max(z, 1e-6)
    dev = np.abs(ratios - np.maximum(1, np.round(ratios)))
    out["decodability"] = float(max(0.0, 1.0 - 2.0 * dev.max())) if len(dev) else 0.0
    out["module_px"] = z
    out["elements"] = len(elems)
    out["width_px"] = float((last - first) * sample_step)
    return out


def _scan_grades(p: dict[str, Any], decoded: bool) -> dict[str, int]:
    g = {
        "decode": 4 if decoded else 0,
        "symbol_contrast": grade_ge(p["symbol_contrast"], "symbol_contrast"),
        "min_reflectance": 4 if p["rmin"] <= 0.5 * p["rmax"] else 0,        # ISO 15416：Rmin ≤ 0.5·Rmax
        "edge_contrast": 4 if p["edge_contrast"] >= 0.15 else 0,             # ISO 15416：ECmin ≥ 0.15
        "modulation": grade_ge(p["modulation"], "modulation_1d"),
        "defects": grade_le(p["defects"], "defects"),
        "decodability": grade_ge(p["decodability"], "decodability"),
    }
    return g


def grade_1d(gray: np.ndarray, sym: Symbol, aperture: float = 0.0, scans: int = 10) -> dict[str, Any]:
    """ISO 15416：符號高度 10%～90% 取 scans 條掃描線，每條的分數＝最低分項，總評＝平均。每條掃描線用 zxing 重解一次（decode 分項）。"""
    zx = _zx()
    tl, tr, br, bl = sym.corners
    ex = tr - tl
    length = float(np.linalg.norm(ex))
    if length < 4:
        raise GradingError("The bar code is too small to grade")
    ex /= length
    ey = np.array([-ex[1], ex[0]])
    height = float(abs(np.dot(bl - tl, ey)))
    if height < 3:
        height = 3.0
    # 沿掃描線延伸兩側各 20% 長度當靜區
    margin = 0.2 * length
    step = 0.25  # 每 0.25 px 一個樣本
    n = int((length + 2 * margin) / step) + 1
    ts = np.linspace(-margin, length + margin, n)
    # 名目模組寬度估計（孔徑用）：EAN 類用模組總數，其餘先用 1D 元素最細者的近似（length / 100）
    modules = LINEAR_MODULES.get(sym.fmt)
    x_dim = length / modules if modules else max(1.0, length / 100.0)
    ap = aperture if aperture > 0 else 0.8 * x_dim
    field = disc_filter(gray, ap)
    h, w = gray.shape[:2]
    fmt_enum = None
    for name, member in ((("EAN-13",), zx.BarcodeFormat.EAN13), (("EAN-8",), zx.BarcodeFormat.EAN8), (("UPC-A",), zx.BarcodeFormat.UPCA), (("UPC-E",), zx.BarcodeFormat.UPCE),
                         (("Code 128",), zx.BarcodeFormat.Code128), (("Code 39", "Code 39 Ext", "Code 39 Std"), zx.BarcodeFormat.Code39), (("Code 93",), zx.BarcodeFormat.Code93), (("ITF",), zx.BarcodeFormat.ITF)):
        if sym.fmt in name:
            fmt_enum = member
    scan_rows = []
    params_all: list[dict[str, Any]] = []
    for k in range(scans):
        frac = 0.1 + 0.8 * k / max(1, scans - 1)
        origin = tl + (bl - tl) * frac
        pts = origin[None, :] + ts[:, None] * ex[None, :]
        mx = np.clip(pts[:, 0], 0, w - 1).astype(np.float32).reshape(1, -1)
        my = np.clip(pts[:, 1], 0, h - 1).astype(np.float32).reshape(1, -1)
        prof = cv2.remap(field, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(-1).astype(np.float64)
        p = scan_profile_params(prof, sym.fmt, step)
        # decode（ISO 15416 的參考解碼：剖面以全域門檻 GT 二值化、由元素寬度解碼）：把 GT 二值化後的剖面做成 5 列的條狀影像給 zxing 固定門檻解
        gt = (p["rmax"] + p["rmin"]) / 2
        binary = np.where(prof > gt, 255, 0).astype(np.uint8).reshape(1, -1)
        strip = np.repeat(binary, 5, axis=0)
        decoded = False
        try:
            res = zx.read_barcodes(np.ascontiguousarray(strip), formats=fmt_enum if fmt_enum is not None else zx.BarcodeFormat.AllLinear, try_rotate=False, try_downscale=False, try_invert=False, binarizer=zx.Binarizer.FixedThreshold)
            decoded = any(r.valid and r.text == sym.text for r in res)
        except Exception:  # noqa: BLE001 - 解碼器例外視為該掃描線解碼失敗
            decoded = False
        g = _scan_grades(p, decoded)
        scan_grade = min(g.values())
        scan_rows.append({"scan": k + 1, "grade": scan_grade, "decoded": decoded, **{key: round(float(v), 4) for key, v in p.items() if isinstance(v, (int, float))}, "grades": g})
        params_all.append({**p, "grades": g})
    mean_grade = float(np.mean([s["grade"] for s in scan_rows]))
    keys = ("decode", "symbol_contrast", "min_reflectance", "edge_contrast", "modulation", "defects", "decodability")
    labels = {"decode": "Decode", "symbol_contrast": "Symbol contrast", "min_reflectance": "Minimum reflectance", "edge_contrast": "Edge contrast", "modulation": "Modulation", "defects": "Defects", "decodability": "Decodability"}
    value_key = {"decode": None, "symbol_contrast": "symbol_contrast", "min_reflectance": "rmin", "edge_contrast": "edge_contrast", "modulation": "modulation", "defects": "defects", "decodability": "decodability"}
    params = []
    for key in keys:
        grades = [pa["grades"][key] for pa in params_all]
        vk = value_key[key]
        val = None if vk is None else float(np.mean([pa[vk] for pa in params_all]))
        params.append(_param(key, labels[key], "ok" if key == "decode" and all(grades) else val, int(round(float(np.mean(grades)))) if key != "decode" else (4 if all(grades) else 0),
                             note=f"{sum(1 for g in grades if g == 0)} of {len(grades)} scans failed" if key == "decode" and not all(grades) else f"scan average, worst {min(grades)}"))
    return {"grade": letter_of(mean_grade), "grade_value": round(mean_grade, 2), "params": params, "detail": {"standard": "iso15416", "symbology": sym.fmt, "scans": scan_rows, "x_dim_px": round(x_dim, 3), "aperture_px": round(ap, 2), "height_px": round(height, 1)},
            "text": sym.text, "symbology": sym.fmt, "corners": sym.corners}


# ---------------------------------------------------------------- 入口
def grade(gray: np.ndarray, standard: str = "iso15415", symbology: str = "auto", aperture: float = 0.0, dpm_filter: str = "none") -> dict[str, Any]:
    """整個流程：解碼 → 依碼制走 2D／1D 路徑。解不出來回 decode F（其餘分項不計）。"""
    symbols = decode(gray, symbology)
    if not symbols:
        return {"grade": "F", "grade_value": 0.0, "params": [_param("decode", "Decode", "failed", 0, note="no symbol decoded in the region")], "detail": {"standard": standard}, "text": "", "symbology": "", "corners": None}
    sym = symbols[0]
    if len(symbols) > 1:  # 取面積最大的
        sym = max(symbols, key=lambda s: abs(cv2.contourArea(s.corners.astype(np.float32))))
    used = standard
    if sym.linear:
        used = "iso15416"
        out = grade_1d(gray, sym, aperture)
    else:
        if standard == "iso15416":
            used = "iso15415"
        out = grade_2d(gray, sym, used, aperture, dpm_filter)
    out["detail"]["standard_used"] = used
    out["detail"]["standard_requested"] = standard
    return out
