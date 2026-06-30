import mmap
import numpy as np
import cv2 as cv
from ultralytics import YOLO
import json
import yaml
import os
import torch

# ==================================================
# Global
# ==================================================

_g_reader  = None
_g_model   = None
_g_names   = None
_g_device  = None
_g_half    = False
_g_is_engine   = False
_g_frame_count = 0

TRACKER_CFG = "bytetrack.yaml"

# ==================================================
# 設定
# ==================================================

MODEL_PATH = r"D:\Working Space\Python\VisionStereo\weights\best.pt"

# yaml 路徑：用於讀取正確的類別名稱
# .pt 模型本身已內嵌 names，此設定可留空字串 ""
# .onnx 模型不帶 names，必須填寫 yaml 路徑
YAML_PATH  = r"D:\TrainingImage\CITD\dataset\data.yaml"

# ==================================================
# MMap Reader
# ==================================================

class MMapReader:

    def __init__(self, tag_name, num_elements):

        self.mm = mmap.mmap(
            -1,
            num_elements,
            tagname=tag_name,
            access=mmap.ACCESS_READ
        )

        self.view = np.frombuffer(
            self.mm,
            dtype=np.uint8,
            count=num_elements
        )

    def read_frame(self):
        return cv.imdecode(self.view, cv.IMREAD_COLOR)

    def close(self):
        if hasattr(self, "view"):
            del self.view

        import gc
        gc.collect()

        if self.mm:
            self.mm.close()
            self.mm = None


# ==================================================
# Filtering
# ==================================================

CONF_THRES  = 0.2
MIN_AREA    = 500

# ── 邊界排除距離設定 ────────────────────────────────
# polygon 任意頂點距影像邊緣「小於等於」此值（pixel）即排除。
#
# 說明：
#   EDGE_MARGIN = 0   → 只排除頂點剛好在邊界上（= 0 pixel 間距）
#   EDGE_MARGIN = 2   → 頂點距邊界 2 pixel 以內排除
#   EDGE_MARGIN = 30  → 頂點距邊界 30 pixel 以內排除（物件在影像邊緣附近即排除）
#
# 建議依影像解析度調整：
#   640×480  →  10~20 pixel
#   1920×1080 →  20~50 pixel
EDGE_MARGIN = 50   # ← 修改此數值即可

# ── Tracker 週期性重置 ────────────────────────────
# 長時間運行後 Kalman Filter 數值累積可能退化，
# 每 N 幀強制重置 tracker 狀態
TRACKER_RESET_INTERVAL = 3000
 

ALLOWED_CLASSES     = None
_ALLOWED_CLASSES_NP = None


# ==================================================
# 從 yaml 讀取類別名稱
#   支援兩種 yaml 格式：
#     List 格式：names: [cat, dog]  或  names:\n  - cat
#     Dict 格式：names:\n  0: cat\n  1: dog
# ==================================================

def _load_names_from_yaml(yaml_path: str) -> dict:
    if not yaml_path or not os.path.exists(yaml_path):
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    names = data.get("names", {})
    if isinstance(names, list):
        return {i: n for i, n in enumerate(names)}
    return {int(k): v for k, v in names.items()}


# ==================================================
# _polygon_border_mask（vectorized，零 Python loop）
#
#   masks_xy : list[ndarray(N,2) float32]  ← r.masks.xy 子集
#              已是原始影像座標，無需 resize
#   回傳 bool ndarray，True = 碰到邊界（排除）
# ==================================================

def _polygon_border_mask(masks_xy, img_h, img_w, margin=EDGE_MARGIN):
    n = len(masks_xy)
    if n == 0:
        return np.zeros(0, dtype=bool)

    counts = np.array([len(m) for m in masks_xy], dtype=np.int64)
    empty  = (counts == 0)
    result = empty.copy()

    nonempty_idx = np.where(~empty)[0]
    if len(nonempty_idx) == 0:
        return result

    all_pts   = np.concatenate([masks_xy[i] for i in nonempty_idx], axis=0)
    ne_counts = counts[nonempty_idx]
    seg_idx   = np.concatenate([[0], np.cumsum(ne_counts[:-1])]).astype(np.int64)

    min_xy = np.minimum.reduceat(all_pts, seg_idx)
    max_xy = np.maximum.reduceat(all_pts, seg_idx)

    m = margin
    touches = (
        (min_xy[:, 0] < m)             |
        (min_xy[:, 1] < m)             |
        (max_xy[:, 0] > img_w - 1 - m) |
        (max_xy[:, 1] > img_h - 1 - m)
    )

    result[nonempty_idx] = touches
    return result


# ==================================================
# mask_to_polygon_and_centroid
# ==================================================

def mask_to_polygon_and_centroid(mask_data, img_h, img_w, max_points=12):

    if mask_data.shape[0] != img_h or mask_data.shape[1] != img_w:
        mask_resized = cv.resize(
            mask_data,
            (img_w, img_h),
            interpolation=cv.INTER_LINEAR
        )
    else:
        mask_resized = mask_data

    binary = (mask_resized > 0.5).astype(np.uint8)

    contours, _ = cv.findContours(
        binary,
        cv.RETR_EXTERNAL,
        cv.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return [], None

    cnt = max(contours, key=cv.contourArea)

    M = cv.moments(cnt)
    if M["m00"] > 0:
        cx = int(round(M["m10"] / M["m00"]))
        cy = int(round(M["m01"] / M["m00"]))
        centroid = [cx, cy]
    else:
        bx, by, bw, bh = cv.boundingRect(cnt)
        centroid = [bx + bw // 2, by + bh // 2]

    epsilon = 0.01 * cv.arcLength(cnt, True)
    approx  = cv.approxPolyDP(cnt, epsilon, True)
    poly    = approx.reshape(-1, 2)

    if len(poly) > max_points:
        idx  = np.linspace(0, len(poly) - 1, max_points).astype(int)
        poly = poly[idx]

    return poly.tolist(), centroid


# ==================================================
# Initialize
# ==================================================

def initialize(tag_name, num_elements):

    global _g_reader, _g_model, _g_names, _g_device, _g_half
    global _ALLOWED_CLASSES_NP

    if _g_reader is None:
        _g_reader = MMapReader(tag_name, num_elements)

    if _g_model is None:

        _g_device = "cuda:0" if torch.cuda.is_available() else "cpu"
        _g_half   = (_g_device != "cpu")

        _g_model = YOLO(MODEL_PATH)
        _g_model.to(_g_device)

        # ── 類別名稱讀取順序 ──────────────────────────
        # 1. 優先從 YAML_PATH 讀取（確保名稱與訓練時一致）
        # 2. yaml 不存在或未設定時，fallback 到模型內嵌的 names
        yaml_names = _load_names_from_yaml(YAML_PATH)
        _g_names   = yaml_names if yaml_names else _g_model.names

        if ALLOWED_CLASSES is not None:
            _ALLOWED_CLASSES_NP = np.array(ALLOWED_CLASSES, dtype=np.int32)

        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        for _ in range(3):
            _g_model.track(
                dummy,
                persist=True,
                imgsz=640,
                tracker=TRACKER_CFG,
                device=_g_device,
                half=_g_half,
                verbose=False
            )


# ==================================================
# Execute
# ==================================================

def execute():

    global _g_frame_count
 
    # ── 週期性重置 tracker（防止 Kalman Filter 長時間退化）──
    _g_frame_count += 1
    if _g_frame_count % TRACKER_RESET_INTERVAL == 0:
        _g_model.predictor = None

    frame = _g_reader.read_frame()
    if frame is None:
        return "[]"

    img_h, img_w = frame.shape[:2]

    results = _g_model.track(
        frame,
        persist=True,
        tracker=TRACKER_CFG,
        conf=CONF_THRES,
        device=_g_device,
        half=_g_half,
        verbose=False,
        save=False,
        show=False,
        vid_stride=4
    )

    r = results[0]
    if r.boxes is None or len(r.boxes) == 0:
        return "[]"

    # --------------------------------------------------
    # Tensor → CPU numpy（一次傳輸）
    # --------------------------------------------------

    xyxy  = r.boxes.xyxy.cpu().numpy().astype(np.int32)
    confs = r.boxes.conf.cpu().numpy()
    clss  = r.boxes.cls.cpu().numpy().astype(np.int32)
    ids   = (
        r.boxes.id.cpu().numpy().astype(np.int32)
        if r.boxes.id is not None
        else np.full(len(xyxy), -1, dtype=np.int32)
    )

    areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])

    # --------------------------------------------------
    # Step 1：conf + area + class（vectorized）
    # --------------------------------------------------

    valid = (confs >= CONF_THRES) & (areas >= MIN_AREA)

    if _ALLOWED_CLASSES_NP is not None:
        valid &= np.isin(clss, _ALLOWED_CLASSES_NP)

    if not np.any(valid):
        return "[]"

    # --------------------------------------------------
    # Step 2：polygon 碰到影像邊界 → 濾除
    # --------------------------------------------------

    if r.masks is not None and r.masks.xy is not None:
        valid_idx  = np.where(valid)[0]
        sub_masks  = [r.masks.xy[i] for i in valid_idx]
        border_hit = _polygon_border_mask(sub_masks, img_h, img_w)
        valid[valid_idx[border_hit]] = False
    else:
        m = EDGE_MARGIN
        valid &= ~(
            (xyxy[:, 0] <= m)              |
            (xyxy[:, 1] <= m)              |
            (xyxy[:, 2] >= img_w - 1 - m)  |
            (xyxy[:, 3] >= img_h - 1 - m)
        )

    if not np.any(valid):
        return "[]"

    xyxy  = xyxy[valid]
    confs = confs[valid]
    clss  = clss[valid]
    ids   = ids[valid]
    areas = areas[valid]

    # --------------------------------------------------
    # Segmentation mask → polygon + centroid
    # --------------------------------------------------

    polygons  = None
    centroids = None

    if r.masks is not None:
        masks_np  = r.masks.data.cpu().numpy()[valid]
        polygons  = []
        centroids = []

        for mask in masks_np:
            poly, centroid = mask_to_polygon_and_centroid(mask, img_h, img_w)
            polygons.append(poly)
            centroids.append(centroid)

    # --------------------------------------------------
    # 組裝 JSON 輸出
    # --------------------------------------------------

    names = _g_names

    if polygons is not None:
        output = [
            {
                "id":       int(ids[i]),
                "bbox":     xyxy[i].tolist(),
                "conf":     round(float(confs[i]), 4),
                "cls":      int(clss[i]),
                "name":     names.get(int(clss[i]), "obj"),
                "area":     int(areas[i]),
                "polygon":  polygons[i],
                "centroid": centroids[i],
            }
            for i in range(len(ids))
        ]
    else:
        output = [
            {
                "id":   int(ids[i]),
                "bbox": xyxy[i].tolist(),
                "conf": round(float(confs[i]), 4),
                "cls":  int(clss[i]),
                "name": names.get(int(clss[i]), "obj"),
                "area": int(areas[i]),
            }
            for i in range(len(ids))
        ]

    return json.dumps(output, ensure_ascii=False)


# ==================================================
# Get Class Names
#   從已載入的模型或指定的 .pt 檔取得類別名稱列表
#
#   用法：
#     # 取得目前已載入模型的類別名稱
#     get_class_names()
#
#     # 指定 .pt 路徑（不影響已載入的 _g_model）
#     get_class_names(r"D:\weights\other.pt")
#
#   回傳 JSON 字串：
#     {"count": 3, "names": {"0": "car", "1": "truck", "2": "person"}}
#   失敗時回傳：
#     {"count": 0, "names": {}, "error": "..."}
# ==================================================

def get_class_names(pt_path: str = "") -> str:
    """
    取得 .pt 模型內嵌的類別名稱。

    Args:
        pt_path: .pt 檔路徑。
                 留空 "" → 使用目前已載入的 _g_model。
                 指定路徑 → 臨時載入該模型讀取 names，不影響 _g_model。

    Returns:
        JSON 字串，格式：
        {"count": N, "names": {"0": "class_a", "1": "class_b", ...}}
    """
    try:
        if pt_path:
            # 臨時載入指定模型，只讀 names，立即釋放
            tmp = YOLO(pt_path)
            raw_names = tmp.names
            del tmp
        else:
            # 使用已載入的全域模型
            if _g_model is None:
                return json.dumps(
                    {"count": 0, "names": {}, "error": "model not initialized"},
                    ensure_ascii=False
                )
            raw_names = _g_model.names

        # raw_names 可能是 dict {0: "car", ...} 或 list ["car", ...]
        if isinstance(raw_names, dict):
            names = {str(k): v for k, v in sorted(raw_names.items())}
        else:
            names = {str(i): n for i, n in enumerate(raw_names)}

        return json.dumps(
            {"count": len(names), "names": names},
            ensure_ascii=False
        )

    except Exception as e:
        return json.dumps(
            {"count": 0, "names": {}, "error": str(e)},
            ensure_ascii=False
        )


# ==================================================
# Cleanup
# ==================================================

def cleanup():

    global _g_reader

    if _g_reader is not None:
        _g_reader.close()
        _g_reader = None