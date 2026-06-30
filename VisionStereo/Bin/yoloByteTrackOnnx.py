import mmap
import numpy as np
import cv2 as cv
from ultralytics import YOLO
import json

# ==================================================
# Global
# ==================================================
_g_reader = None
_g_model = None
_g_names = None

TRACKER_CFG = "bytetrack.yaml"
CONF_THRES = 0.2
MIN_AREA = 500
ALLOWED_CLASSES = None
_ALLOWED_CLASSES_NP = None


# ==================================================
# MMap Reader（微優化）
# ==================================================
class MMapReader:
    def __init__(self, tag_name, num_elements):
        self.mm = mmap.mmap(
            -1,
            num_elements,
            tagname=tag_name,
            access=mmap.ACCESS_READ
        )
        # ⚡ 避免 view 重建
        self.buf = memoryview(self.mm)

    def read_frame(self):
        # ⚡ 直接 decode memoryview（少一次 numpy wrap）
        arr = np.frombuffer(self.buf, dtype=np.uint8)
        return cv.imdecode(arr, cv.IMREAD_COLOR)

    def close(self):
        if self.mm:
            self.mm.close()
            self.mm = None


# ==================================================
# Initialize
# ==================================================
def initialize(tag_name, num_elements):
    global _g_reader, _g_model, _g_names, _ALLOWED_CLASSES_NP

    if _g_reader is None:
        _g_reader = MMapReader(tag_name, num_elements)

    if _g_model is None:
        _g_model = YOLO(r"D:\Working Space\Python\VisionStereo\weights\best.onnx")
        _g_names = _g_model.names

        if ALLOWED_CLASSES is not None:
            _ALLOWED_CLASSES_NP = np.array(ALLOWED_CLASSES, dtype=np.int32)

        # ⚡ warmup（減少 track overhead）
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        _g_model.track(dummy, persist=True, tracker=TRACKER_CFG, verbose=False)

    return True


# ==================================================
# Execute (optimized core)
# ==================================================
def execute():
    frame = _g_reader.read_frame()

    if frame is None:
        return "[]"

    results = _g_model.track(
        frame,
        persist=True,
        tracker=TRACKER_CFG,
        conf=CONF_THRES,
        verbose=False
    )

    if not results or results[0].boxes is None:
        return "[]"

    boxes = results[0].boxes

    if len(boxes) == 0:
        return "[]"

    # ==================================================
    # 🔥 ONE SHOT tensor → numpy (critical speedup)
    # ==================================================
    data = boxes.data.cpu().numpy()

    # columns: [x1,y1,x2,y2,conf,cls,track_id?]
    xyxy = data[:, 0:4].astype(np.int32)
    confs = data[:, 4]
    clss = data[:, 5].astype(np.int32)

    ids = (
        boxes.id.cpu().numpy().astype(np.int32)
        if boxes.id is not None
        else np.full(len(xyxy), -1, dtype=np.int32)
    )

    # ==================================================
    # Vectorized filtering
    # ==================================================
    areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])

    mask = (confs >= CONF_THRES) & (areas >= MIN_AREA)

    if _ALLOWED_CLASSES_NP is not None:
        mask &= np.isin(clss, _ALLOWED_CLASSES_NP)

    if not np.any(mask):
        return "[]"

    xyxy = xyxy[mask]
    confs = confs[mask]
    clss = clss[mask]
    ids = ids[mask]
    areas = areas[mask]

    # ==================================================
    # 🔥 FAST JSON (no loop dict append)
    # ==================================================
    names = _g_names

    output = [
        {
            "id": int(i),
            "bbox": b.tolist(),
            "conf": round(float(c), 4),
            "cls": int(cl),
            "name": names.get(int(cl), "obj"),
            "area": int(a)
        }
        for i, b, c, cl, a in zip(ids, xyxy, confs, clss, areas)
    ]

    return json.dumps(output)


# ==================================================
# Cleanup
# ==================================================
def cleanup():
    global _g_reader, _g_model

    if _g_reader:
        _g_reader.close()
        _g_reader = None

    _g_model = None

    return True