"""
空洞檢測的深度學習路徑 (規劃書 PLAN-002 第 5 節)

焊點位置與半徑沿用規則式的擬合結果；模型只負責每顆焊點的空洞分割。
前處理 (訓練腳本共用本檔，確保訓練與產品一致)：
  - 以焊點為中心裁切 2 x crop_scale x R 的正方形視窗，縮放到 size x size
  - 依焊點自身正規化：背景 = 1.15～1.35 R 環帶的中位數，頂部 = 0.5 R 內的 90 百分位
    → (A - 背景) / (頂部 - 背景)，限制在 [-0.5, 1.5]；不受曝光與功率影響
模型輸出每個像素的空洞機率 (size x size)。
"""
import math

import cv2
import numpy as np

NORMALIZATION = "ball_relative_v1"


def ball_crop(A, x, y, R, size=64, crop_scale=1.4):
    """回傳 (正規化裁切 float32 size x size, 視窗 (x0, y0, x1, y1))；視窗超出影像時以邊緣值補齊"""
    H, W = A.shape
    h = int(math.ceil(crop_scale * R))
    cx, cy = int(round(x)), int(round(y))
    x0, y0, x1, y1 = cx - h, cy - h, cx + h + 1, cy + h + 1
    pad = max(0, -x0, -y0, x1 - W, y1 - H)
    src = cv2.copyMakeBorder(A, pad, pad, pad, pad, cv2.BORDER_REPLICATE) if pad else A
    win = src[y0 + pad:y1 + pad, x0 + pad:x1 + pad].astype(np.float32)
    crop = cv2.resize(win, (size, size), interpolation=cv2.INTER_AREA)
    yy, xx = np.mgrid[0:size, 0:size]
    s = (x1 - x0) / size                                   # 原始像素 / 裁切像素
    d = np.hypot((xx + 0.5) * s + x0 - x, (yy + 0.5) * s + y0 - y) / R
    ring = crop[(d > 1.15) & (d < 1.35)]
    core = crop[d < 0.5]
    bg = float(np.median(ring)) if ring.size else float(np.percentile(crop, 5))
    top = float(np.percentile(core, 90)) if core.size else float(crop.max())
    norm = (crop - bg) / max(top - bg, 1e-6)
    return np.clip(norm, -0.5, 1.5).astype(np.float32), (x0, y0, x1, y1)


def mask_crop(mask, window, size=64):
    """訓練用：把影像座標的遮罩 (0/1) 以相同視窗裁切縮放"""
    x0, y0, x1, y1 = window
    H, W = mask.shape
    pad = max(0, -x0, -y0, x1 - W, y1 - H)
    src = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0) if pad else mask
    win = src[y0 + pad:y1 + pad, x0 + pad:x1 + pad].astype(np.float32)
    return (cv2.resize(win, (size, size), interpolation=cv2.INTER_AREA) >= 0.5).astype(np.float32)


def segment(A, balls, model, gpu, cfg):
    """
    balls：[dict(x, y, r)]；model：dict(path, meta)。
    回傳每顆焊點的 (空洞清單, 空洞總面積)；空洞格式與規則式相同 (contour, area_px2, depth, cx, cy, perimeter_px)
    """
    from ...core import inference
    meta = model["meta"]
    inp = meta.get("input") or {}
    size, crop_scale = int(inp.get("size", 64)), float(inp.get("crop_scale", 1.4))
    thr = float((meta.get("output") or {}).get("threshold", 0.5))
    if inp.get("normalization", NORMALIZATION) != NORMALIZATION:
        raise inference.InferenceError("model_input_unsupported", inp.get("normalization"))
    crops, wins = [], []
    for b in balls:
        c, w = ball_crop(A, b["x"], b["y"], b["r"], size, crop_scale)
        crops.append(c)
        wins.append(w)
    if not crops:
        return []
    out = []
    probs = []
    for i in range(0, len(crops), 64):
        batch = np.stack(crops[i:i + 64])[:, None]
        probs.append(inference.run(model["path"], batch, gpu))
    prob = np.concatenate(probs)[:, 0]
    H, W = A.shape
    for b, (x0, y0, x1, y1), p in zip(balls, wins, prob):
        n = x1 - x0
        full = cv2.resize(p.astype(np.float32), (n, n), interpolation=cv2.INTER_LINEAR)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        zone = np.hypot(xx - b["x"], yy - b["y"]) < (1 - cfg["rim"]) * b["r"]
        m = ((full >= thr) & zone).astype(np.uint8)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(m)
        cv2.drawContours(filled, cs, -1, 1, -1)
        filled &= zone.astype(np.uint8)
        min_area = max(cfg["min_area_px"], math.pi * (cfg["min_diam_ratio"] * b["r"]) ** 2)
        k, lab, stats, cent = cv2.connectedComponentsWithStats(filled, connectivity=8)
        voids, total = [], 0.0
        for j in range(1, k):
            area = float(stats[j, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            reg = (lab == j).astype(np.uint8)
            cc, _ = cv2.findContours(reg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            c = max(cc, key=cv2.contourArea)
            pts = c[:, 0, :] + [x0, y0]
            voids.append(dict(contour=pts.astype(float).tolist(), area_px2=area, rim=False,
                              depth=float(full[reg > 0].max()), perimeter_px=cv2.arcLength(c, True),
                              cx=float(cent[j][0]) + x0, cy=float(cent[j][1]) + y0, source="model"))
            total += area
        out.append((voids, total))
    return out
