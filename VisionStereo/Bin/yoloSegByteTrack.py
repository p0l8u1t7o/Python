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
# fmt（IMAQ 影像型別代碼）-> (dtype, bytes_per_pixel, channels)
# bytes_per_pixel 為單一像素「所有 channel 加總」的位元組數，
# 用來換算每一列（row）在記憶體中的實際跨距（stride）。
FORMATS = {
    0: (np.uint8,   1, 1),   # Grayscale (U8)
    1: (np.int16,   2, 1),   # Grayscale (I16)
    2: (np.float32, 4, 1),   # Grayscale (SGL)
    4: (np.uint8,   4, 4),   # RGB (U32)，記憶體順序 BGRA
    5: (np.uint8,   4, 4),   # HSL (U32)
    6: (np.uint16,  8, 4),   # RGB (U64)，每個 channel 16-bit
    7: (np.uint16,  2, 1),   # Grayscale (U16)
}




class MMapReader:
    """讀取 LabVIEW 寫入的共享記憶體。

    line_width 為 IMAQ GetImageInfo 的 Line Width（單位像素，含 padding）。
    size 為映射總長度，0 表示只有單張影像。
    """

    def __init__(self, tag_name, width, height, line_width, fmt, size=0):
        """開啟指定 tag 的具名共享記憶體並準備好讀取用的中介資訊。

        參數：
            tag_name:   LabVIEW 端建立共享記憶體時使用的名稱。
            width:      影像實際寬度（像素）。
            height:     影像實際高度（像素）。
            line_width: IMAQ GetImageInfo 回傳的 Line Width（像素，含 padding）；
                        0 表示沒有 padding，等同 width。
            fmt:        影像型別代碼，對應 FORMATS 字典的 key。
            size:       整段共享記憶體的總長度（bytes）；0 表示只映射單張影像。
        """
        self.dtype, bpp, self.ch = FORMATS[fmt]
        self.w, self.h = width, height
        self.row = (line_width or width) * bpp   # 每一列在記憶體中的實際 byte 數（含 padding）
        self.valid = width * bpp                  # 每一列中真正有效影像資料的 byte 數
        self.frame_bytes = self.row * height       # 單張影像佔用的總 byte 數

        # 以唯讀模式開啟 LabVIEW 已建立好的具名記憶體對映；
        # size 為 0 時代表只有單張影像，用 frame_bytes 當作映射長度。
        self.mm = mmap.mmap(-1, size or self.frame_bytes,
                            tagname=tag_name, access=mmap.ACCESS_READ)
        self.buf = np.frombuffer(self.mm, dtype=np.uint8)
        self.buf[::4096].sum()          # prefault，把 page fault 成本移到開場

    def read_frame(self, offset=0, copy=False):
        """從共享記憶體讀出一張影像，回傳 numpy array。

        參數：
            offset: 該影像在共享記憶體中的起始 byte 位移（多張影像串接時使用）。
            copy:   True 時強制回傳獨立複製；False（預設）盡量回傳 zero-copy view，
                    共享同一塊記憶體，效能較好但資料可能隨下次寫入而改變。
        """
        # 依 row（含 padding）切成 (h, row) 的 2D view，再裁掉 padding 只留有效資料
        raw = self.buf[offset:offset + self.frame_bytes].reshape(self.h, self.row)
        blk = raw[:, :self.valid]

        # uint8 以外的型別若不是連續記憶體（因裁切 padding 而不連續），
        # view() 轉型前必須先複製成連續記憶體，否則會出錯或結果不正確。
        if copy or (self.dtype != np.uint8 and not blk.flags["C_CONTIGUOUS"]):
            blk = np.ascontiguousarray(blk)

        # uint8 直接使用（沒有型別轉換需求），其餘型別以 view 重新解讀底層 bytes
        arr = blk if self.dtype == np.uint8 else blk.view(self.dtype)
        return arr.reshape(self.h, self.w, self.ch) if self.ch > 1 \
            else arr.reshape(self.h, self.w)

    def close(self):
        """釋放 numpy view 與 mmap 物件。"""
        self.buf = None
        self.mm.close()
        self.mm = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


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

def initialize(tag_name, width, height ,line_width ,fmt):

    global _g_reader, _g_model, _g_names, _g_device, _g_half
    global _ALLOWED_CLASSES_NP

    if _g_reader is None:
        _g_reader = MMapReader(tag_name, width, height, line_width, fmt)

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

    xyxy  = r.boxes.xyxy.cpu().numpy().astype(np.int32)  # type: ignore[reportAttributeAccessIssue]
    confs = r.boxes.conf.cpu().numpy()  # type: ignore[reportAttributeAccessIssue]
    clss  = r.boxes.cls.cpu().numpy().astype(np.int32)  # type: ignore[reportAttributeAccessIssue]
    ids   = (
        r.boxes.id.cpu().numpy().astype(np.int32)  # type: ignore[reportAttributeAccessIssue]
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
        masks_np  = r.masks.data.cpu().numpy()[valid]  # type: ignore[reportAttributeAccessIssue]
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
# ==================================================

def get_class_names(pt_path: str = "") -> str:
    try:
        if pt_path:
            tmp = YOLO(pt_path)
            raw_names = tmp.names
            del tmp
        else:
            if _g_model is None:
                return json.dumps(
                    {"count": 0, "names": [], "error": "model not initialized"},
                    ensure_ascii=False
                )
            raw_names = _g_model.names

        # 統一轉成 {int: str} 再轉 list，確保順序正確
        if isinstance(raw_names, dict):
            name_dict = {int(k): v for k, v in raw_names.items()}
        else:
            name_dict = {i: n for i, n in enumerate(raw_names)}

        # 依 int key 排序後輸出為 list of {id, name}
        names_list = [
            {"id": k, "name": name_dict[k]}
            for k in sorted(name_dict.keys())
        ]

        return json.dumps(
            {"count": len(names_list), "names": names_list},
            ensure_ascii=False
        )

    except Exception as e:
        return json.dumps(
            {"count": 0, "names": [], "error": str(e)},
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