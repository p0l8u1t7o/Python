#!/usr/bin/env python3
"""
print_qc.py — 字形無關的印刷品質檢測 (font-agnostic print defect inspection)

不比對「字該長什麼樣」，只量測印刷的物理特性，因此字型、字數、內容都可以變。

量測項目
--------
1. stroke_width_mean / stroke_width_cv  筆畫寬度與其變異係數  → 糊字、壓力不均、瘦字
2. gap_count / gap_severity             骨架斷點配對偵測      → 斷筆、缺墨
3. component_excess                     連通域數量異常        → 字被切斷、多印
4. speckle_count / speckle_area         孤立小墨點面積        → 噴濺、污漬、鬼影
5. edge_sharpness                       邊界梯度銳利度        → 暈染、離焦、重影
6. ink_coverage                         外接框內墨水覆蓋率    → 整體濃淡偏移
7. contrast                             前景/背景灰階分離度   → 淡墨、色帶耗盡

判定方式
--------
只用良品建立基準 (median + MAD)，對待測字元算 robust z-score，
任一指標超出門檻即判 NG，並回報是哪個指標、往哪個方向偏。

用法
----
    # 1) 用一批良品影像建立基準
    python print_qc.py fit  ./good_samples/  -o baseline.json

    # 2) 檢測
    python print_qc.py check ./test.png -b baseline.json -o result.png

    # 3) 不建基準，只看指標數值（調機用）
    python print_qc.py dump ./test.png

需求: opencv-python numpy scikit-image scipy
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass, asdict, field

import cv2
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

# ----------------------------------------------------------------------------
# 參數（依產線調整；單位為像素，除非另註）
# ----------------------------------------------------------------------------

CFG = {
    # --- 前處理 ---
    "invert": None,          # None=自動判斷深字淺底/淺字深底；True/False 可強制
    "denoise_h": 5,          # non-local means 強度，0 = 關閉
    "bin_block": 31,         # 自適應二值化視窗（必須為奇數，約 2~3 倍字高）
    "bin_C": 8,              # 自適應二值化偏移
    "noise_close": 3,        # 閉運算核大小，填掉 <此尺寸的二值化雜訊；
                             # 同時定義了「可偵測的最小缺陷尺寸」，勿設過大
    "ink_sigma": 4.0,        # 前景必須偏離背景 此倍數×背景雜訊 才算墨水
    "min_ink_delta": 12,     # 前景與背景的最小灰階差（絕對值），擋掉低對比雜訊
    "deskew": True,          # 是否用最小外接矩形自動校正整體傾斜

    # --- 切字 ---
    "min_char_area": 40,     # 小於此面積的連通域不視為字元（會被當 speckle）
    "min_char_h": 8,         # 字元最小高度
    "merge_overlap": 0.55,   # 水平重疊率超過此值才可能是同一字（處理「i」的點、偏旁）
    "merge_vsep": 0.20,      # 且垂直重疊率必須低於此值，否則是相鄰的兩個字

    # --- 缺陷偵測 ---
    "gap_max_ratio": 1.8,    # 斷點配對的最大距離 = 此值 × 筆畫寬度
    "gap_angle_tol": 40,     # 兩端切線與連線的最大夾角(度)；用來排除 S/3/C 的自然開口
    "speckle_ratio": 0.25,   # 面積小於 (筆畫寬^2 × 此值) 視為雜點
    "min_speckle_px": 6,     # 雜點面積絕對下限，低於此值視為感測器雜訊
    "edge_band": 2,          # 量測邊緣銳利度的環帶寬度

    # --- 判定 ---
    "z_thresh": 4.0,         # 連續型指標的 robust z-score 門檻（單一字元）
    "z_thresh_image": 4.0,   # 整行漂移的 z-score 門檻
    "count_quantile": 0.995, # 稀疏型指標取良品的此百分位當上限
    "min_mad": 1e-6,         # MAD 下限，避免除以 0
}

# --- 指標分類 -------------------------------------------------------------
# 連續型：良品也有自然分佈 → 用 robust z-score (median / MAD)
#         方向 +1 只管變大, -1 只管變小, 0 雙向都管
CONTINUOUS = {
    "stroke_ratio": 0,
    "stroke_width_cv": +1,
    "edge_sharpness": -1,
    "ink_coverage": 0,
    "ink_depth": 0,
}
# 整張影像層級的漂移指標：對全部字元取中位數再比對。
# 單一字元的筆畫粗細受字型/字面影響很大，MAD 寬、抓不到緩慢的墨量漂移；
# 對一整行取中位數後標準誤降到 1/√N，色帶耗盡、壓力偏移這類全域問題才看得出來。
IMAGE_LEVEL = ["stroke_ratio", "ink_depth", "edge_sharpness"]

# 稀疏型：良品幾乎恆為 0 → MAD 也是 0，z-score 會爆掉，改用「良品觀測上限」判定
COUNTING = ["gap_count", "component_excess", "speckle_count"]
# 輔助型：只用於描述嚴重程度，本身不觸發 NG（避免與 COUNTING 重複計數）
INFO = ["gap_severity", "speckle_area", "stroke_width_mean", "snr"]

METRIC_NAMES = list(CONTINUOUS) + COUNTING + INFO

DEFECT_HINT = {
    "stroke_ratio": "筆畫過粗/過細（墨量或壓力偏移）",
    "stroke_width_mean": "筆畫絕對寬度異常",
    "stroke_width_cv": "筆畫寬度不均（糊字、暈染）",
    "gap_count": "筆畫斷裂（缺墨、噴嘴阻塞）",
    "gap_severity": "斷裂缺口過大",
    "component_excess": "字元被切成多塊",
    "speckle_count": "孤立墨點（噴濺、污漬）",
    "speckle_area": "雜點面積過大",
    "edge_sharpness": "邊緣模糊（離焦、暈染、重影）",
    "ink_coverage": "覆蓋率異常（整體濃淡偏移）",
    "ink_depth": "墨色深度異常（淡墨、色帶耗盡、墨量過多）",
    "snr": "訊雜比不足",
}


# ----------------------------------------------------------------------------
# 前處理
# ----------------------------------------------------------------------------

def load_gray(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def binarize(gray: np.ndarray, cfg: dict) -> np.ndarray:
    """回傳前景=255 的二值圖（前景 = 墨水）。"""
    g = gray
    if cfg["denoise_h"] > 0:
        g = cv2.fastNlMeansDenoising(g, None, cfg["denoise_h"], 7, 21)

    blk = cfg["bin_block"] | 1  # 強制奇數
    binv = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, blk, cfg["bin_C"]
    )

    invert = cfg["invert"]
    if invert is None:
        # 墨水通常佔少數；若「反相後的前景」佔比 > 50%，代表原圖是淺字深底
        invert = (binv > 0).mean() > 0.5
    if invert:
        binv = 255 - binv

    # --- 墨水閘 -------------------------------------------------------------
    # 自適應二值化在平坦背景上會把感測器雜訊也當成前景（誤報的最大來源）。
    # 真正的墨水一定會明顯偏離背景灰階，所以加一道絕對條件：
    # 必須偏離背景 max(min_ink_delta, ink_sigma × 背景雜訊) 以上。
    bg = g[binv == 0].astype(np.float32)
    fg = g[binv > 0].astype(np.float32)
    if bg.size > 50 and fg.size > 10:
        bg_med = float(np.median(bg))
        bg_mad = 1.4826 * float(np.median(np.abs(bg - bg_med)))
        delta = max(float(cfg["min_ink_delta"]), cfg["ink_sigma"] * bg_mad)
        gate = (g < bg_med - delta) if float(np.median(fg)) < bg_med else (g > bg_med + delta)
        binv = cv2.bitwise_and(binv, (gate * 255).astype(np.uint8))

    # 去掉單像素雜訊，但不要動到細筆畫
    binv = cv2.morphologyEx(binv, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # 閉運算填掉抗鋸齒/雜訊造成的假斷點。核大小 = 系統能偵測的最小缺陷尺寸，
    # 設太大會把真的斷筆補起來，設太小則良品會一直誤報 —— 這是最關鍵的一個參數。
    nc = cfg["noise_close"]
    if nc >= 2:
        binv = cv2.morphologyEx(binv, cv2.MORPH_CLOSE, np.ones((nc, nc), np.uint8))
    return binv


def deskew(binary: np.ndarray, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    pts = cv2.findNonZero(binary)
    if pts is None or len(pts) < 20:
        return binary, gray, 0.0
    angle = cv2.minAreaRect(pts)[-1]
    if angle > 45:
        angle -= 90
    if abs(angle) < 0.2 or abs(angle) > 20:   # 幾乎沒斜、或量測不可信就不動
        return binary, gray, 0.0
    h, w = binary.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    b = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    g = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
    return b, g, float(angle)


# ----------------------------------------------------------------------------
# 切字
# ----------------------------------------------------------------------------

def segment_chars(binary: np.ndarray, cfg: dict) -> list[tuple[int, int, int, int]]:
    """回傳字元外接框 [(x, y, w, h), ...]，由左至右排序。"""
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < cfg["min_char_area"] or h < cfg["min_char_h"]:
            continue
        boxes.append([x, y, w, h])
    if not boxes:
        return []

    # 垂直堆疊的部件（i/j 的點、ä 的兩點）水平投影會高度重疊；
    # 相鄰的不同字元則幾乎不重疊 —— 用重疊率而非距離來判斷，才不會把整串字黏成一塊。
    def ov(a, b, i):   # i=0 水平, i=1 垂直
        s = min(a[i] + a[i + 2], b[i] + b[i + 2]) - max(a[i], b[i])
        return s / max(1, min(a[i + 2], b[i + 2]))

    boxes.sort(key=lambda b: b[0])
    changed = True
    while changed:
        changed = False
        out = []
        for b in boxes:
            # 同一字的兩個部件（i 的點與豎）水平重疊、垂直分離；
            # 相鄰的不同字元則是水平可能微重疊、但垂直幾乎完全重疊。
            # 兩個條件都要看，只看水平會把整串字黏成一塊。
            if out and ov(out[-1], b, 0) >= cfg["merge_overlap"] \
                   and ov(out[-1], b, 1) < cfg["merge_vsep"]:
                p = out[-1]
                x0, y0 = min(p[0], b[0]), min(p[1], b[1])
                x1, y1 = max(p[0] + p[2], b[0] + b[2]), max(p[1] + p[3], b[1] + b[3])
                out[-1] = [x0, y0, x1 - x0, y1 - y0]
                changed = True
            else:
                out.append(list(b))
        boxes = out
    return [tuple(int(v) for v in b) for b in boxes]


# ----------------------------------------------------------------------------
# 指標
# ----------------------------------------------------------------------------

def _stroke_width(mask: np.ndarray) -> tuple[float, float, np.ndarray]:
    """用距離轉換在骨架上取值：width = 2 × distance。回傳 (mean, cv, 骨架上的寬度圖)。"""
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    skel = skeletonize(mask > 0)
    vals = 2.0 * dist[skel]
    vals = vals[vals > 0]
    if vals.size < 3:
        return 0.0, 0.0, np.zeros_like(dist)
    mean = float(np.mean(vals))
    cv_ = float(np.std(vals) / mean) if mean > 0 else 0.0
    wmap = np.zeros_like(dist)
    wmap[skel] = 2.0 * dist[skel]
    return mean, cv_, wmap


def _skeleton_endpoints(skel: np.ndarray) -> np.ndarray:
    """骨架端點（8 鄰域只有 1 個鄰居的骨架像素）座標 (N, 2) as (y, x)。"""
    k = np.array([[1, 1, 1], [1, 10, 1], [1, 1, 1]], np.uint8)
    s = skel.astype(np.uint8)
    nb = cv2.filter2D(s, cv2.CV_16S, k, borderType=cv2.BORDER_CONSTANT)
    ep = (nb == 11)  # 自己(10) + 恰好一個鄰居(1)
    return np.column_stack(np.nonzero(ep))


def _endpoint_tangent(skel: np.ndarray, p: np.ndarray, steps: int) -> np.ndarray:
    """沿骨架從端點往內走 steps 步，回傳「由內指向端點」的單位切線向量。"""
    h, w = skel.shape
    prev, cur = None, tuple(int(v) for v in p)
    for _ in range(steps):
        nxt = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = cur[0] + dy, cur[1] + dx
                if 0 <= ny < h and 0 <= nx < w and skel[ny, nx] and (ny, nx) != prev:
                    nxt = (ny, nx)
                    break
            if nxt:
                break
        if nxt is None:
            break
        prev, cur = cur, nxt
    v = p.astype(np.float64) - np.array(cur, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else np.zeros(2)


def _gaps(mask: np.ndarray, sw: float, cfg: dict) -> tuple[int, float, list]:
    """
    字形無關的斷筆偵測。一個真正的斷裂有三個特徵，缺一不可：

      (a) 兩個骨架端點的距離 < gap_max_ratio × 筆畫寬
      (b) 兩點之間是背景（否則只是同一筆畫上的兩個端點）
      (c) 兩端的切線都「指向對方」——這是關鍵。S / 3 / C / G 的自然開口
          同樣滿足 (a)(b)，但它們的筆尾是繞開彼此的，切線不共線。
          少了這一條，圓弧字元會大量誤報。

    整套判斷只用到筆畫的幾何連續性，不需要知道這是哪個字、哪種字型。
    """
    if sw <= 0:
        return 0, 0.0, []
    skel = skeletonize(mask > 0)
    eps = _skeleton_endpoints(skel)
    if len(eps) < 2:
        return 0, 0.0, []

    max_d = cfg["gap_max_ratio"] * sw
    cos_tol = float(np.cos(np.deg2rad(cfg["gap_angle_tol"])))
    steps = max(3, int(round(1.5 * sw)))
    tangents = {i: _endpoint_tangent(skel, eps[i], steps) for i in range(len(eps))}

    used, gaps = set(), []
    for i in range(len(eps)):
        if i in used:
            continue
        for j in range(i + 1, len(eps)):
            if j in used:
                continue
            p, q = eps[i], eps[j]
            d = float(np.hypot(*(p - q)))
            if d < 1.5 or d > max_d:
                continue

            # (b) 連線必須是背景
            nsamp = max(int(d), 3)
            ys = np.linspace(p[0], q[0], nsamp).astype(int)
            xs = np.linspace(p[1], q[1], nsamp).astype(int)
            if (mask[ys, xs][1:-1] > 0).mean() > 0.25:
                continue

            # (c) 兩端切線都要指向對方
            u = (q - p).astype(np.float64)
            u /= max(np.linalg.norm(u), 1e-6)
            if float(tangents[i] @ u) < cos_tol or float(tangents[j] @ (-u)) < cos_tol:
                continue

            gaps.append((tuple(int(v) for v in p[::-1]),
                         tuple(int(v) for v in q[::-1]), d))
            used.add(i)
            used.add(j)
            break
    severity = float(max((g[2] for g in gaps), default=0.0) / sw) if gaps else 0.0
    return len(gaps), severity, gaps


def _speckles(stats, cents, main_i: int, keep: list[int],
              sw: float, cfg: dict) -> tuple[int, float, list]:
    """面積遠小於一個筆畫斷面的孤立連通域 → 噴濺點 / 污漬。"""
    if sw <= 0:
        return 0, 0.0, []
    thr = max(float(cfg["min_speckle_px"]), cfg["speckle_ratio"] * sw * sw)
    cnt, area, locs = 0, 0.0, []
    for i in keep:
        if i == main_i:
            continue
        a = float(stats[i, cv2.CC_STAT_AREA])
        if a < thr:
            cnt += 1
            area += a
            locs.append((int(cents[i][0]), int(cents[i][1])))
    return cnt, area, locs


def _edge_sharpness(roi_gray, roi_bin, valid: np.ndarray, cfg: dict) -> float:
    """邊界環帶上的平均梯度，除以前景/背景灰階差 → 與墨色深淺無關的銳利度。"""
    k = np.ones((3, 3), np.uint8)
    band = cv2.dilate(roi_bin, k, iterations=cfg["edge_band"]) ^ \
           cv2.erode(roi_bin, k, iterations=cfg["edge_band"])
    band = (band > 0) & valid
    if band.sum() < 10:
        return 0.0
    g = roi_gray.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    grad = float(cv2.magnitude(gx, gy)[band].mean())
    fg, bg = g[roi_bin > 0], g[(roi_bin == 0) & valid]
    depth = abs(float(fg.mean()) - float(bg.mean())) if fg.size and bg.size else 1.0
    return grad / max(depth, 1.0)


def _ink_depth(roi_gray, roi_bin, valid: np.ndarray) -> tuple[float, float]:
    """
    回傳 (ink_depth, snr)。

    ink_depth = |背景灰階 − 筆畫核心灰階|，單位是灰階級數。這是判定淡墨的主力：
    良品之間非常穩定，色帶耗盡或墨量不足時會直接掉下來。

    兩個曾經踩過的坑：
      * 分母不能用「前景+背景的合併變異數」。墨色變淡時前景變異數同步縮小，
        比值會變成尺度不變，整片淡墨完全量不出來。
      * 也不要拿背景標準差當分母當主指標 —— 那會把照明雜訊的波動灌進指標裡，
        MAD 被撐大，40% 的淡墨就淹沒在正常變異中。雜訊比另外用 snr 回報即可。
    """
    k = np.ones((3, 3), np.uint8)
    core = cv2.erode(roi_bin, k, iterations=1)        # 取筆畫核心，避開抗鋸齒邊緣
    far_bg = cv2.dilate(roi_bin, k, iterations=2)
    fg = roi_gray[core > 0] if core.sum() > 20 * 255 else roi_gray[roi_bin > 0]
    bg = roi_gray[(far_bg == 0) & valid]
    if fg.size < 5 or bg.size < 20:
        return 0.0, 0.0
    depth = abs(float(bg.mean()) - float(fg.mean()))
    return depth, depth / max(float(bg.std()), 1.0)


@dataclass
class CharResult:
    box: tuple
    metrics: dict = field(default_factory=dict)
    z: dict = field(default_factory=dict)
    ng: bool = False
    reasons: list = field(default_factory=list)
    gap_pts: list = field(default_factory=list)
    speckle_pts: list = field(default_factory=list)


def measure_char(gray: np.ndarray, binary: np.ndarray, box: tuple,
                 cfg: dict, others: list[tuple] = ()) -> CharResult:
    x, y, w, h = box
    pad = 4
    y0, y1 = max(0, y - pad), min(gray.shape[0], y + h + pad)
    x0, x1 = max(0, x - pad), min(gray.shape[1], x + w + pad)
    roi_g = gray[y0:y1, x0:x1]
    roi_b = binary[y0:y1, x0:x1].copy()

    n, lab, stats, cents = cv2.connectedComponentsWithStats(roi_b, 8)
    if n <= 1:
        return CharResult(box=box)
    main_i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))

    # ROI 有留 padding，會切到隔壁字元的邊。凡是重心落在「別的字元框」裡的
    # 連通域一律剔除，否則相鄰字會被誤判成本字的雜點或斷塊。
    keep = []
    alien = np.zeros(roi_b.shape, np.uint8)   # 屬於隔壁字元的像素
    for i in range(1, n):
        cx, cy = cents[i][0] + x0, cents[i][1] + y0
        if any(ox <= cx <= ox + ow and oy <= cy <= oy + oh for ox, oy, ow, oh in others):
            roi_b[lab == i] = 0
            alien[lab == i] = 255
            continue
        keep.append(i)
    # 隔壁字元的墨水若混進「背景」樣本，contrast 與 edge_sharpness 會整個失真，
    # 所以連同其周邊一併排除在統計之外。
    valid = cv2.dilate(alien, np.ones((3, 3), np.uint8), iterations=3) == 0
    if main_i not in keep:
        return CharResult(box=box)

    main = ((lab == main_i) * 255).astype(np.uint8)
    sw_mean, sw_cv, _ = _stroke_width(main)

    # 斷筆偵測用「主體 + 夠大的碎塊」的聯集：筆畫被完全切斷時字元會分裂成
    # 兩塊，只看主體就找不到那個缺口。
    thr_big = max(float(cfg["min_speckle_px"]), cfg["speckle_ratio"] * sw_mean ** 2)
    body = main.copy()
    for i in keep:
        if i != main_i and stats[i, cv2.CC_STAT_AREA] >= thr_big:
            body[lab == i] = 255
    gap_n, gap_sev, gap_list = _gaps(body, sw_mean, cfg)
    spk_n, spk_a, spk_pts = _speckles(stats, cents, main_i, keep, sw_mean, cfg)
    sharp = _edge_sharpness(roi_g, roi_b, valid, cfg)
    depth, snr = _ink_depth(roi_g, roi_b, valid)

    # 字元被切斷 → 除了主體外還有「夠大」的塊（不是雜點）
    big_extra = sum(1 for i in keep
                    if i != main_i and stats[i, cv2.CC_STAT_AREA] >= thr_big)

    m = {
        "stroke_ratio": sw_mean / max(h, 1),      # 相對字高的筆畫粗細，與字級無關
        "stroke_width_mean": sw_mean,             # 絕對值（僅供參考/調機）
        "stroke_width_cv": sw_cv,
        "gap_count": float(gap_n),
        "gap_severity": gap_sev,
        "component_excess": float(big_extra),
        "speckle_count": float(spk_n),
        "speckle_area": spk_a,
        "edge_sharpness": sharp,
        "ink_coverage": float((main > 0).sum()) / max(w * h, 1),
        "ink_depth": depth,
        "snr": snr,
    }
    return CharResult(
        box=box, metrics=m,
        gap_pts=[((g[0][0] + x0, g[0][1] + y0), (g[1][0] + x0, g[1][1] + y0)) for g in gap_list],
        speckle_pts=[(p[0] + x0, p[1] + y0) for p in spk_pts],
    )


# ----------------------------------------------------------------------------
# 基準 (只用良品)
# ----------------------------------------------------------------------------

class Baseline:
    """只用良品建立。連續型存 median/MAD，稀疏型存良品觀測上限。"""

    def __init__(self, med=None, mad=None, lim=None, n=0, cfg=None,
                 img_med=None, img_mad=None):
        self.med = med or {}
        self.mad = mad or {}
        self.lim = lim or {}
        self.img_med = img_med or {}
        self.img_mad = img_mad or {}
        self.n = n
        self.cfg = cfg or dict(CFG)

    @staticmethod
    def fit(samples: list[dict], cfg: dict) -> "Baseline":
        med, mad, lim = {}, {}, {}
        for k in CONTINUOUS:
            v = np.array([s[k] for s in samples], dtype=np.float64)
            m = float(np.median(v))
            # 1.4826 × MAD ≈ 常態分布下的標準差，但對離群值不敏感
            med[k] = m
            mad[k] = max(1.4826 * float(np.median(np.abs(v - m))), cfg["min_mad"])
        for k in COUNTING:
            v = np.array([s[k] for s in samples], dtype=np.float64)
            # 良品的 99.5 百分位當上限；良品全 0 時上限就是 0，出現任何一個就 NG
            lim[k] = float(np.quantile(v, cfg["count_quantile"]))
        for k in INFO:
            v = np.array([s[k] for s in samples], dtype=np.float64)
            med[k] = float(np.median(v))
            mad[k] = max(1.4826 * float(np.median(np.abs(v - med[k]))), cfg["min_mad"])
        return Baseline(med, mad, lim, len(samples), cfg)

    def fit_image_level(self, per_image: list[dict], cfg: dict):
        """per_image: 每張良品影像對全部字元取中位數後的指標。"""
        for k in IMAGE_LEVEL:
            v = np.array([p[k] for p in per_image], dtype=np.float64)
            m = float(np.median(v))
            self.img_med[k] = m
            self.img_mad[k] = max(1.4826 * float(np.median(np.abs(v - m))), cfg["min_mad"])
        return self

    def score_image(self, results: list["CharResult"]) -> list[str]:
        """整行漂移檢查，回傳警告訊息。"""
        ms = [r.metrics for r in results if r.metrics]
        if not ms or not self.img_med:
            return []
        out = []
        for k in IMAGE_LEVEL:
            v = float(np.median([m[k] for m in ms]))
            z = (v - self.img_med[k]) / self.img_mad[k]
            if abs(z) > self.cfg["z_thresh_image"]:
                out.append(f"整行漂移: {k} = {v:.4f} (z={z:+.1f}) → {DEFECT_HINT[k]}")
        return out

    def score(self, r: CharResult) -> CharResult:
        if not r.metrics:
            r.ng, r.reasons = True, ["無法量測（字元太小或分割失敗）"]
            return r

        for k, d in CONTINUOUS.items():
            z = (r.metrics[k] - self.med[k]) / self.mad[k]
            r.z[k] = float(z)
            hit = abs(z) > self.cfg["z_thresh"] if d == 0 else d * z > self.cfg["z_thresh"]
            if hit:
                r.ng = True
                r.reasons.append(f"{k} = {r.metrics[k]:.3f} (z={z:+.1f}) → {DEFECT_HINT[k]}")

        for k in COUNTING:
            v = r.metrics[k]
            if v > self.lim[k]:
                r.ng = True
                extra = ""
                if k == "gap_count" and r.metrics["gap_severity"] > 0:
                    extra = f"，最大缺口 {r.metrics['gap_severity']:.1f}× 筆畫寬"
                if k == "speckle_count" and r.metrics["speckle_area"] > 0:
                    extra = f"，總面積 {r.metrics['speckle_area']:.0f} px"
                r.reasons.append(
                    f"{k} = {v:.0f} (良品上限 {self.lim[k]:.0f}) → {DEFECT_HINT[k]}{extra}")
        return r

    def save(self, path: str):
        json.dump({"n": self.n, "median": self.med, "mad": self.mad,
                   "limit": self.lim, "img_median": self.img_med,
                   "img_mad": self.img_mad, "cfg": self.cfg},
                  open(path, "w"), indent=2, ensure_ascii=False)

    @staticmethod
    def load(path: str) -> "Baseline":
        d = json.load(open(path))
        return Baseline(d["median"], d["mad"], d["limit"], d["n"],
                        d.get("cfg", dict(CFG)),
                        d.get("img_median"), d.get("img_mad"))


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def inspect(path: str, cfg: dict, baseline: Baseline | None = None):
    gray = load_gray(path)
    binary = binarize(gray, cfg)
    if cfg["deskew"]:
        binary, gray, _ = deskew(binary, gray)
    boxes = segment_chars(binary, cfg)
    results = [measure_char(gray, binary, b, cfg,
                            others=[o for o in boxes if o != b])
               for b in boxes]
    if baseline is not None:
        results = [baseline.score(r) for r in results]
    return gray, binary, results


def annotate(gray: np.ndarray, results: list[CharResult]) -> np.ndarray:
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for r in results:
        x, y, w, h = r.box
        color = (0, 0, 220) if r.ng else (0, 170, 0)
        cv2.rectangle(vis, (x - 2, y - 2), (x + w + 2, y + h + 2), color, 1)
        for p, q in r.gap_pts:
            cv2.circle(vis, p, 4, (255, 0, 255), 1)
            cv2.circle(vis, q, 4, (255, 0, 255), 1)
            cv2.line(vis, p, q, (255, 0, 255), 1)
        for p in r.speckle_pts:
            cv2.circle(vis, p, 5, (0, 165, 255), 1)
    return vis


def cmd_fit(args):
    cfg = dict(CFG)
    files = sorted(sum([glob.glob(os.path.join(args.src, e))
                        for e in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif")], []))
    if not files:
        sys.exit(f"找不到影像: {args.src}")
    samples, per_image = [], []
    for f in files:
        _, _, res = inspect(f, cfg)
        ms = [r.metrics for r in res if r.metrics]
        if not ms:
            continue
        samples += ms
        per_image.append({k: float(np.median([m[k] for m in ms])) for k in IMAGE_LEVEL})
    if len(samples) < 10:
        print(f"警告: 只取到 {len(samples)} 個字元樣本，建議 >= 200 個再上線", file=sys.stderr)
    bl = Baseline.fit(samples, cfg).fit_image_level(per_image, cfg)
    bl.save(args.out)
    print(f"已用 {len(files)} 張影像 / {len(samples)} 個字元建立基準 → {args.out}")
    for k in CONTINUOUS:
        lo = bl.med[k] - cfg["z_thresh"] * bl.mad[k]
        hi = bl.med[k] + cfg["z_thresh"] * bl.mad[k]
        print(f"  {k:20s} median={bl.med[k]:8.3f}  mad={bl.mad[k]:7.3f}  "
              f"允收區間 [{lo:.3f}, {hi:.3f}]")
    for k in COUNTING:
        print(f"  {k:20s} 良品上限 = {bl.lim[k]:.0f}")


def cmd_check(args):
    bl = Baseline.load(args.baseline)
    gray, _, res = inspect(args.image, bl.cfg, bl)
    ng = [r for r in res if r.ng]
    drift = bl.score_image(res)
    print(f"{args.image}: {len(res)} 字元, NG {len(ng)} 個 "
          f"→ {'FAIL' if (ng or drift) else 'PASS'}")
    for d in drift:
        print(f"  ! {d}")
    for i, r in enumerate(res):
        if r.ng:
            print(f"  [#{i} @ {r.box}]")
            for s in r.reasons:
                print(f"      {s}")
    if args.out:
        cv2.imwrite(args.out, annotate(gray, res))
        print(f"標註影像 → {args.out}")
    return 1 if (ng or drift) else 0


def cmd_dump(args):
    cfg = dict(CFG)
    _, _, res = inspect(args.image, cfg)
    hdr = ["idx", "box"] + METRIC_NAMES
    print("\t".join(hdr))
    for i, r in enumerate(res):
        if not r.metrics:
            continue
        row = [str(i), str(r.box)] + [f"{r.metrics[k]:.4f}" for k in METRIC_NAMES]
        print("\t".join(row))


def main():
    p = argparse.ArgumentParser(description="字形無關的印刷品質檢測")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fit", help="用良品影像建立基準")
    f.add_argument("src")
    f.add_argument("-o", "--out", default="baseline.json")
    f.set_defaults(func=cmd_fit)

    c = sub.add_parser("check", help="檢測單張影像")
    c.add_argument("image")
    c.add_argument("-b", "--baseline", default="baseline.json")
    c.add_argument("-o", "--out", default=None, help="輸出標註影像路徑")
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("dump", help="只印出指標數值（調機用）")
    d.add_argument("image")
    d.set_defaults(func=cmd_dump)

    a = p.parse_args()
    sys.exit(a.func(a) or 0)


if __name__ == "__main__":
    main()
