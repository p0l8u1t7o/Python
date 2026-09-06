"""OCR／OCV 核心：離線的文字偵測（DB）＋辨識（CTC）＋現場字型教導（切分＋小型分類器）。

離線部署是前提：模型是 ASSET_DIR/ocr/ 下隨平台附帶的本地檔，**執行期絕不下載**。
預設模型（PaddleOCR PP-OCRv4，經 RapidOCR 打包成 ONNX；Apache-2.0，可商用轉散布）：
  ch_PP-OCRv4_det_infer.onnx   文字偵測（DB）：輸入 (1,3,H,W) 的 (x/255 − 0.5)/0.5，H、W 為 32 的倍數；輸出 sigmoid 機率圖 (1,1,H,W)
  ch_PP-OCRv4_rec_infer.onnx   文字辨識（CTC）：輸入 (N,3,48,W) 同樣正規化；輸出 (N,T,6625)＝blank＋6623 字（字典嵌在模型 metadata "character"）＋空白
  ch_ppocr_mobile_v2.0_cls_infer.onnx  方向分類（0／180°，選用）
安裝：`manage.py ocr_models --install <rapidocr wheel 或資料夾>`；模型來源與授權記在 ASSET_DIR/ocr/MODELS.json。

字型教導（點陣噴印、DPM 打標）：使用者框一行字給正確字串 → 切分（固定間距／投影法／連通域）→ 字元切片存成樣本 →
訓練小型分類器（沿用 dl/onnx_io.build_mlp 的 numpy MLP）→ npz 模型資產；ocr_read 的 model 選到 .npz 就走「切分＋逐字分類」。

session 與字典在模組層快取並加鎖（mtime＋size 判失效）。
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np
from django.conf import settings

DET_MODEL = "ch_PP-OCRv4_det_infer.onnx"
REC_MODEL = "ch_PP-OCRv4_rec_infer.onnx"
CLS_MODEL = "ch_ppocr_mobile_v2.0_cls_infer.onnx"
MODEL_FILES = (DET_MODEL, REC_MODEL, CLS_MODEL)
REC_HEIGHT = 48
REC_MAX_WIDTH = 1280
DIGITS = "0123456789"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOWER = "abcdefghijklmnopqrstuvwxyz"
ALNUM = DIGITS + UPPER + LOWER
PUNCT = "-./:+_#*()&"
CHARSETS = {"alnum": ALNUM + PUNCT, "digits": DIGITS + "-./:", "upper": DIGITS + UPPER + PUNCT, "any": ""}


class OcrError(ValueError):
    """可預期的錯誤（訊息給使用者看）。"""


def models_dir() -> str:
    return os.path.join(str(settings.VISION["ASSET_DIR"]), "ocr")


def model_path(name: str) -> str:
    return os.path.join(models_dir(), name)


def models_available() -> bool:
    return os.path.isfile(model_path(REC_MODEL))


def install_models(source: str) -> list[str]:
    """從 rapidocr 的 wheel（zip）或資料夾把三個 ONNX 複製到 ASSET_DIR/ocr，並寫 MODELS.json（來源、授權、正規化）。"""
    import shutil
    import zipfile

    dest = models_dir()
    os.makedirs(dest, exist_ok=True)
    copied: list[str] = []
    if os.path.isfile(source) and source.lower().endswith((".whl", ".zip")):
        with zipfile.ZipFile(source) as z:
            for info in z.infolist():
                base = os.path.basename(info.filename)
                if base in MODEL_FILES:
                    with z.open(info) as src, open(os.path.join(dest, base), "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    copied.append(base)
    elif os.path.isdir(source):
        for base in MODEL_FILES:
            src = os.path.join(source, base)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(dest, base))
                copied.append(base)
    else:
        raise OcrError(f"{source} is neither a wheel/zip nor a folder")
    if REC_MODEL not in copied:
        raise OcrError(f"{REC_MODEL} was not found in {source}")
    with open(os.path.join(dest, "MODELS.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "source": "PaddleOCR PP-OCRv4 (ONNX export packaged by RapidOCR, https://github.com/RapidAI/RapidOCR)",
            "license": "Apache-2.0 (models and package); commercial redistribution permitted",
            "files": copied,
            "det": {"file": DET_MODEL, "input": "(1,3,H,W) H,W multiples of 32, (x/255-0.5)/0.5 RGB", "output": "sigmoid probability map"},
            "rec": {"file": REC_MODEL, "input": "(N,3,48,W) (x/255-0.5)/0.5 RGB", "output": "(N,T,6625) CTC: blank + 6623 characters from model metadata 'character' + space"},
            "cls": {"file": CLS_MODEL, "input": "(N,3,48,192)", "labels": ["0", "180"]},
        }, fh, indent=2, ensure_ascii=False)
    invalidate()
    return copied


# ---------------------------------------------------------------------------
# session 快取
# ---------------------------------------------------------------------------
_SESSIONS: "OrderedDict[str, tuple[float, int, Any]]" = OrderedDict()
_LOCK = threading.Lock()
_CHARS: dict[str, list[str]] = {}


def invalidate() -> None:
    with _LOCK:
        _SESSIONS.clear()
        _CHARS.clear()


def session(path: str) -> Any:
    """ORT session（mtime＋size 判失效；providers 依設定頁）。"""
    try:
        import onnxruntime as ort
    except ImportError:
        raise OcrError("onnxruntime is not installed, so OCR cannot run") from None
    try:
        st = os.stat(path)
    except OSError:
        raise OcrError(f"OCR model missing: {path}. Install the models with manage.py ocr_models --install (nothing is downloaded at run time)") from None
    with _LOCK:
        hit = _SESSIONS.get(path)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            _SESSIONS.move_to_end(path)
            return hit[2]
    from apps.vision.dl.devices import preferred_providers
    from apps.vision.tools.builtin.dl import preload_gpu_dlls

    providers = preferred_providers()
    if any(p != "CPUExecutionProvider" for p in providers):
        preload_gpu_dlls()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    try:
        sess = ort.InferenceSession(path, opts, providers=providers)
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"Could not load the OCR model: {str(exc)[:200]}") from None
    with _LOCK:
        _SESSIONS[path] = (st.st_mtime, st.st_size, sess)
        while len(_SESSIONS) > 8:
            _SESSIONS.popitem(last=False)
    return sess


def characters(path: str) -> list[str]:
    """CTC 類別表：[blank] + 模型 metadata 的字典 + [space]。"""
    with _LOCK:
        cached = _CHARS.get(path)
    if cached is not None:
        return cached
    sess = session(path)
    meta = sess.get_modelmeta().custom_metadata_map or {}
    raw = meta.get("character", "")
    chars = raw.splitlines() if "\n" in raw else raw.split()
    table = ["<blank>"] + [c for c in chars] + [" "]
    with _LOCK:
        _CHARS[path] = table
    return table


# ---------------------------------------------------------------------------
# 前處理與辨識
# ---------------------------------------------------------------------------
def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.dtype != np.uint8:
        from apps.vision.tools import imgfmt

        return imgfmt.normalize_u8(image)
    return image


def enhance(gray: np.ndarray) -> np.ndarray:
    """auto 前處理：對比拉伸（2～98 百分位）＋輕度去噪。"""
    lo, hi = np.percentile(gray, (2, 98))
    if hi - lo < 10:
        return gray
    stretched = cv2.convertScaleAbs(gray, alpha=255.0 / (hi - lo), beta=-lo * 255.0 / (hi - lo))
    return cv2.medianBlur(stretched, 3) if min(gray.shape[:2]) >= 12 else stretched


def rec_input(line: np.ndarray, polarity: str = "dark_on_light") -> tuple[np.ndarray, float]:
    """一行影像 → (1,3,48,W) float32；回 (張量, 每個像素對應原圖的比例)。亮字暗底時反相（模型以暗字亮底訓練）。"""
    gray = line if line.ndim == 2 else cv2.cvtColor(line, cv2.COLOR_BGR2GRAY)
    if polarity == "light_on_dark":
        gray = 255 - gray
    h, w = gray.shape[:2]
    scale = REC_HEIGHT / max(1, h)
    new_w = int(max(16, min(REC_MAX_WIDTH, math.ceil(w * scale))))
    resized = cv2.resize(gray, (new_w, REC_HEIGHT), interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    # 補到 8 的倍數（PP-OCR 的下採樣率）
    pad_w = int(math.ceil(new_w / 8) * 8)
    canvas = np.full((REC_HEIGHT, pad_w), 255, np.uint8)
    canvas[:, :new_w] = resized
    x = (canvas.astype(np.float32) / 255.0 - 0.5) / 0.5
    return np.ascontiguousarray(np.repeat(x[None, None], 3, axis=1)), w / new_w


def charset_mask(table: list[str], allowed: str) -> np.ndarray | None:
    """允許字元集 → 類別遮罩（True＝允許）；空字串＝全部允許。blank 永遠允許。"""
    if not allowed:
        return None
    keep = set(allowed)
    mask = np.zeros(len(table), dtype=bool)
    mask[0] = True
    for i, ch in enumerate(table):
        if ch in keep:
            mask[i] = True
    return mask


def ctc_decode(probs: np.ndarray, table: list[str], mask: np.ndarray | None, px_per_step: float, offset_x: float = 0.0) -> tuple[str, list[dict[str, Any]]]:
    """(T, C) 機率 → 字串＋逐字 {ch, conf, box}（box 由時間步範圍換算成 x 範圍）。貪婪解碼、合併重複、去 blank。"""
    if mask is not None:
        probs = np.where(mask[None, :], probs, 0.0)
    idx = probs.argmax(axis=1)
    conf = probs[np.arange(len(idx)), idx]
    chars: list[dict[str, Any]] = []
    prev = -1
    for t, (k, c) in enumerate(zip(idx.tolist(), conf.tolist())):
        if k != 0 and k != prev:
            chars.append({"ch": table[k] if k < len(table) else "?", "conf": float(c), "t0": t, "t1": t})
        elif k != 0 and k == prev and chars:
            chars[-1]["t1"] = t
            chars[-1]["conf"] = max(chars[-1]["conf"], float(c))
        prev = k
    out = []
    for c in chars:
        x0 = offset_x + c["t0"] * px_per_step
        x1 = offset_x + (c["t1"] + 1) * px_per_step
        out.append({"ch": c["ch"], "conf": round(c["conf"], 4), "x0": round(x0, 1), "x1": round(x1, 1)})
    return "".join(c["ch"] for c in out), out


def recognise_line(line: np.ndarray, *, allowed: str = "", polarity: str = "dark_on_light", preprocess: str = "auto") -> tuple[str, list[dict[str, Any]]]:
    """單行辨識：回 (text, chars[{ch, conf, x0, x1}])；x 為該行影像的座標。"""
    gray = line if line.ndim == 2 else cv2.cvtColor(line, cv2.COLOR_BGR2GRAY)
    if preprocess == "auto":
        gray = enhance(gray)
    x, ratio = rec_input(gray, polarity)
    sess = session(model_path(REC_MODEL))
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    table = characters(model_path(REC_MODEL))
    px_per_step = x.shape[3] / max(1, out.shape[0]) * ratio
    return ctc_decode(out, table, charset_mask(table, allowed), px_per_step)


# ---------------------------------------------------------------------------
# 偵測（DB）
# ---------------------------------------------------------------------------
def detect_lines(image: np.ndarray, *, thresh: float = 0.3, box_thresh: float = 0.5, unclip: float = 1.6, limit: int = 736, max_boxes: int = 100) -> list[dict[str, Any]]:
    """DB 文字偵測：回每個文字區 {box: [[x,y]×4], score}（原圖座標，四點依左上起順時針）。"""
    bgr = _to_bgr(image)
    h, w = bgr.shape[:2]
    scale = 1.0
    if min(h, w) < limit:
        scale = limit / min(h, w)
    if max(h, w) * scale > 2000:
        scale = 2000 / max(h, w)
    nh, nw = max(32, int(round(h * scale / 32)) * 32), max(32, int(round(w * scale / 32)) * 32)
    resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = (cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - 0.5) / 0.5
    x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
    sess = session(model_path(DET_MODEL))
    prob = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    binary = (prob > thresh).astype(np.uint8)
    binary = cv2.dilate(binary, np.ones((2, 2), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    sx, sy = w / nw, h / nh
    boxes: list[dict[str, Any]] = []
    for cnt in contours[: max_boxes * 4]:
        if len(cnt) < 4:
            continue
        rect = cv2.minAreaRect(cnt)
        if min(rect[1]) < 3:
            continue
        # 分數＝輪廓內機率平均
        mask = np.zeros(prob.shape, np.uint8)
        cv2.drawContours(mask, [cnt], -1, 1, -1)
        score = float(prob[mask > 0].mean()) if mask.any() else 0.0
        if score < box_thresh:
            continue
        # unclip：依面積／周長比例外擴（Vatti 的近似：等比放大矩形）
        area = float(cv2.contourArea(cnt))
        length = float(cv2.arcLength(cnt, True))
        dist = area * unclip / max(1.0, length)
        (cx, cy), (rw, rh), ang = rect
        rect = ((cx, cy), (rw + 2 * dist, rh + 2 * dist), ang)
        pts = cv2.boxPoints(rect)
        pts[:, 0] *= sx
        pts[:, 1] *= sy
        boxes.append({"box": _order_points(pts).round(1).tolist(), "score": round(score, 4)})
    boxes.sort(key=lambda b: (min(p[1] for p in b["box"]), min(p[0] for p in b["box"])))
    return boxes[:max_boxes]


def _order_points(pts: np.ndarray) -> np.ndarray:
    """四點依左上、右上、右下、左下排序。"""
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    tl, br = pts[np.argmin(s)], pts[np.argmax(s)]
    tr, bl = pts[np.argmax(d)], pts[np.argmin(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def crop_box(image: np.ndarray, box: list[list[float]]) -> tuple[np.ndarray, np.ndarray]:
    """四點框 → 擺正的行影像；回 (crop, 2×3 反向仿射：行影像座標 → 原圖)。"""
    pts = np.asarray(box, dtype=np.float32)
    w = int(max(np.linalg.norm(pts[1] - pts[0]), np.linalg.norm(pts[2] - pts[3])))
    h = int(max(np.linalg.norm(pts[3] - pts[0]), np.linalg.norm(pts[2] - pts[1])))
    w, h = max(4, w), max(4, h)
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(pts, dst)
    out = cv2.warpPerspective(image, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if h > w * 1.5:  # 直排文字：轉正
        out = cv2.rotate(out, cv2.ROTATE_90_COUNTERCLOCKWISE)
    inv = np.linalg.inv(m)
    return out, inv


# ---------------------------------------------------------------------------
# 字型教導（切分＋逐字分類）
# ---------------------------------------------------------------------------
FONT_SIZE = 24
SEG_MODES = ("projection", "components", "fixed")


def binarise_text(gray: np.ndarray, polarity: str = "dark_on_light") -> np.ndarray:
    """文字前景遮罩（Otsu；亮字暗底反相）。"""
    flag = cv2.THRESH_BINARY_INV if polarity == "dark_on_light" else cv2.THRESH_BINARY
    _, mask = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
    return mask


def segment_chars(gray: np.ndarray, mode: str = "projection", count: int = 0, polarity: str = "dark_on_light", min_gap: int = 1, min_width: int = 3) -> list[tuple[int, int, int, int]]:
    """一行影像 → 字元框 [(x0, y0, x1, y1)]，由左到右。

    projection：垂直投影找空白欄位切開；components：連通域外框（相鄰重疊的合併）；fixed：已知字數 count 等分。
    """
    mask = binarise_text(gray, polarity)
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return []
    top, bottom = int(ys.min()), int(ys.max()) + 1
    left, right = int(xs.min()), int(xs.max()) + 1
    boxes: list[tuple[int, int, int, int]] = []
    if mode == "fixed" and count > 0:
        pitch = (right - left) / count
        for i in range(count):
            x0 = int(round(left + i * pitch))
            x1 = int(round(left + (i + 1) * pitch))
            boxes.append((x0, top, max(x0 + 1, x1), bottom))
        return boxes
    if mode == "components":
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        rects = [(int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 0] + stats[i, 2]), int(stats[i, 1] + stats[i, 3])) for i in range(1, n) if stats[i, 4] >= 3]
        rects.sort(key=lambda r: r[0])
        merged: list[list[int]] = []
        for r in rects:
            if merged and r[0] <= merged[-1][2] - 1:  # 水平重疊（i 的點與桿、破損筆畫）→ 合併
                m = merged[-1]
                m[0], m[1], m[2], m[3] = min(m[0], r[0]), min(m[1], r[1]), max(m[2], r[2]), max(m[3], r[3])
            else:
                merged.append(list(r))
        boxes = [(m[0], m[1], m[2], m[3]) for m in merged if m[2] - m[0] >= min_width]
        return boxes
    # projection
    col = (mask > 0).sum(axis=0)
    ink = col > 0
    x = 0
    runs: list[tuple[int, int]] = []
    while x < w:
        if ink[x]:
            x0 = x
            while x < w and ink[x]:
                x += 1
            runs.append((x0, x))
        else:
            x += 1
    # 合併間隙小於 min_gap 的相鄰段（同一字的斷筆）
    joined: list[list[int]] = []
    for r in runs:
        if joined and r[0] - joined[-1][1] < min_gap:
            joined[-1][1] = r[1]
        else:
            joined.append(list(r))
    for x0, x1 in joined:
        if x1 - x0 < min_width:
            continue
        sub = mask[:, x0:x1]
        rows = np.nonzero(sub.sum(axis=1))[0]
        boxes.append((x0, int(rows.min()), x1, int(rows.max()) + 1))
    return boxes


def char_tile(gray: np.ndarray, box: tuple[int, int, int, int], size: int = FONT_SIZE, polarity: str = "dark_on_light") -> np.ndarray:
    """字元切片 → size×size 灰階（暗字亮底，等比縮放置中，白邊）。"""
    x0, y0, x1, y1 = box
    piece = gray[max(0, y0) : y1, max(0, x0) : x1]
    if polarity == "light_on_dark":
        piece = 255 - piece
    if piece.size == 0:
        return np.full((size, size), 255, np.uint8)
    h, w = piece.shape[:2]
    scale = (size - 4) / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    resized = cv2.resize(piece, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    tile = np.full((size, size), 255, np.uint8)
    oy, ox = (size - nh) // 2, (size - nw) // 2
    tile[oy : oy + nh, ox : ox + nw] = resized
    return tile


def tile_features(tile: np.ndarray) -> np.ndarray:
    """分類器特徵：正規化到 [0,1] 的反相像素（筆畫＝1）攤平。"""
    return (1.0 - tile.astype(np.float32) / 255.0).reshape(-1)


def train_font(tiles: list[np.ndarray], labels: list[str], *, hidden: int = 64, epochs: int = 400, lr: float = 0.05, seed: int = 7, augment: bool = True) -> dict[str, Any]:
    """字元分類器（numpy MLP，與 mlp_classify 同一套訓練迴圈）→ 模型 dict {w1, b1, w2, b2, classes, size, metrics}。"""
    from apps.vision.dl.builtin import _train_softmax_mlp

    classes = sorted(set(labels))
    if len(classes) < 2:
        raise OcrError("At least two different characters are needed to teach a font")
    y = np.array([classes.index(c) for c in labels], dtype=np.int64)
    feats = [tile_features(t) for t in tiles]
    if augment:
        rng = np.random.default_rng(seed)
        for t, lab in list(zip(tiles, labels)):
            for _ in range(2):
                dx, dy = int(rng.integers(-2, 3)), int(rng.integers(-2, 3))
                m = np.array([[1, 0, dx], [0, 1, dy]], np.float32)
                shifted = cv2.warpAffine(t, m, (t.shape[1], t.shape[0]), borderValue=255)
                ang = float(rng.uniform(-6, 6))
                rot = cv2.warpAffine(shifted, cv2.getRotationMatrix2D((t.shape[1] / 2, t.shape[0] / 2), ang, 1.0), (t.shape[1], t.shape[0]), borderValue=255)
                feats.append(tile_features(rot))
                y = np.append(y, classes.index(lab))
    x = np.stack(feats).astype(np.float32)
    counts = np.bincount(y, minlength=len(classes))
    if counts.min() < 2:
        raise OcrError("Every character needs at least two samples; short: " + ", ".join(classes[i] for i in np.nonzero(counts < 2)[0]))
    # 驗證集：每類抽 1／5
    rng = np.random.default_rng(seed)
    val = np.zeros(len(y), dtype=bool)
    for ci in range(len(classes)):
        idx = np.flatnonzero(y == ci)
        rng.shuffle(idx)
        val[idx[: max(1, len(idx) // 5)]] = True
    if val.all() or (~val).sum() < len(classes):
        val[:] = False
    w1, b1, w2, b2, metrics = _train_softmax_mlp(x[~val], y[~val], x[val], y[val], hidden=hidden, classes=len(classes), epochs=epochs, lr=lr, seed=seed, progress=lambda *a: None)
    return {"w1": w1.astype(np.float32), "b1": b1.astype(np.float32), "w2": w2.astype(np.float32), "b2": b2.astype(np.float32),
            "classes": classes, "size": FONT_SIZE, "metrics": {**metrics, "samples": int(len(labels)), "augmented": int(len(y) - len(labels)), "classes": len(classes)}}


def pack_font(model: dict[str, Any]) -> bytes:
    import io

    buf = io.BytesIO()
    np.savez_compressed(buf, w1=model["w1"], b1=model["b1"], w2=model["w2"], b2=model["b2"], classes=np.array(model["classes"], dtype="<U8"), size=np.int32(model["size"]),
                        meta=json.dumps({"kind": "ocr_font", "version": 1, "metrics": model.get("metrics", {})}))
    return buf.getvalue()


_FONTS: "OrderedDict[str, tuple[float, int, dict[str, Any]]]" = OrderedDict()


def load_font(path: str) -> dict[str, Any]:
    try:
        st = os.stat(path)
    except OSError as exc:
        raise OcrError(f"Could not read the font model: {exc}") from None
    with _LOCK:
        hit = _FONTS.get(path)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
    try:
        with np.load(path, allow_pickle=False) as z:
            if "w1" not in z or "classes" not in z:
                raise OcrError("This file is not a taught font model")
            model = {"w1": z["w1"], "b1": z["b1"], "w2": z["w2"], "b2": z["b2"], "classes": [str(c) for c in z["classes"]], "size": int(z["size"]),
                     "meta": json.loads(str(z["meta"])) if "meta" in z else {}}
    except (OSError, ValueError, KeyError) as exc:
        raise OcrError(f"Could not read the font model: {exc}") from None
    with _LOCK:
        _FONTS[path] = (st.st_mtime, st.st_size, model)
        while len(_FONTS) > 8:
            _FONTS.popitem(last=False)
    return model


def classify_tiles(model: dict[str, Any], tiles: list[np.ndarray], allowed: str = "") -> list[tuple[str, float]]:
    """逐字分類：回 [(字元, 信心)]。allowed 非空時只在允許的類別裡取最大。"""
    if not tiles:
        return []
    x = np.stack([tile_features(t) for t in tiles]).astype(np.float32)
    h = np.maximum(x @ model["w1"] + model["b1"], 0.0)
    logits = h @ model["w2"] + model["b2"]
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    if allowed:
        keep = np.array([c in allowed for c in model["classes"]], dtype=bool)
        if keep.any():
            p = np.where(keep[None, :], p, 0.0)
    idx = p.argmax(axis=1)
    return [(model["classes"][int(i)], float(p[k, i])) for k, i in enumerate(idx)]


def read_with_font(gray: np.ndarray, model: dict[str, Any], *, mode: str = "projection", count: int = 0, polarity: str = "dark_on_light", allowed: str = "") -> tuple[str, list[dict[str, Any]]]:
    """切分＋逐字分類：回 (text, chars[{ch, conf, x0, x1, y0, y1}])。"""
    boxes = segment_chars(gray, mode, count, polarity)
    tiles = [char_tile(gray, b, model["size"], polarity) for b in boxes]
    preds = classify_tiles(model, tiles, allowed)
    chars = [{"ch": ch, "conf": round(conf, 4), "x0": float(b[0]), "x1": float(b[2]), "y0": float(b[1]), "y1": float(b[3])} for (ch, conf), b in zip(preds, boxes)]
    return "".join(c["ch"] for c in chars), chars


# ---------------------------------------------------------------------------
# OCV：萬用字元比對
# ---------------------------------------------------------------------------
def compare(actual: str, expected: str, mode: str = "exact") -> tuple[bool, int]:
    """回 (match, fail_index)：第一個不符的字元位置，−1＝全符。`?`＝任一字、`#`＝任一數字（exact／contains）；regex 走 re.fullmatch。"""
    import re

    def char_ok(a: str, e: str) -> bool:
        return e == "?" or (e == "#" and a.isdigit()) or a == e

    if mode == "regex":
        try:
            ok = re.fullmatch(expected, actual) is not None
        except re.error as exc:
            raise OcrError(f"Invalid regular expression: {exc}") from None
        if ok:
            return True, -1
        # 找第一個讓前綴無法匹配的位置（近似）
        for i in range(len(actual) + 1):
            if re.fullmatch(expected, actual[:i]) is None and not any(re.fullmatch(expected, actual[:i] + t) for t in ("",)):
                pass
        return False, 0 if not actual else min(len(actual), len(expected))
    if mode == "contains":
        n = len(expected)
        if n == 0:
            return True, -1
        best_fail = 0
        for start in range(0, max(1, len(actual) - n + 1)):
            window = actual[start : start + n]
            if len(window) < n:
                break
            bad = next((i for i in range(n) if not char_ok(window[i], expected[i])), -1)
            if bad < 0:
                return True, -1
            best_fail = max(best_fail, start + bad)
        return False, best_fail
    # exact
    for i in range(max(len(actual), len(expected))):
        if i >= len(actual) or i >= len(expected) or not char_ok(actual[i], expected[i]):
            return False, i
    return True, -1
