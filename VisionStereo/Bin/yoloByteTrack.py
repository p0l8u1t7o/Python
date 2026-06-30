import mmap
import numpy as np
import cv2 as cv
from ultralytics import YOLO
import json
import torch

# ==================================================
# Global
# ==================================================

_g_reader = None
_g_model = None
_g_names = None
_g_device = None
_g_half = False

TRACKER_CFG = "bytetrack.yaml"

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

        frame = cv.imdecode(
            self.view,
            cv.IMREAD_COLOR
        )

        return frame

    def close(self):

        if hasattr(self, "view"):
            del self.view

        import gc
        gc.collect()

        if self.mm:
            self.mm.close()
            self.mm = None


# ==================================================
# Filtering Rules
# ==================================================

CONF_THRES = 0.2

MIN_AREA = 500

# None = All Classes
ALLOWED_CLASSES = None

# 預先轉成 numpy array 供 isin 使用
_ALLOWED_CLASSES_NP = None


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

        _g_model = YOLO(r"D:\Working Space\Python\VisionStereo\weights\yolov8s.pt")
        _g_model.to(_g_device)
        _g_names = _g_model.names

        # 預處理 allowed classes
        if ALLOWED_CLASSES is not None:
            _ALLOWED_CLASSES_NP = np.array(ALLOWED_CLASSES, dtype=np.int32)

        # -----------------------------
        # Warmup（多跑幾次讓 CUDA kernel 穩定）
        # -----------------------------
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)

        for _ in range(3):
            _g_model.track(
                dummy,
                persist=True,
                imgsz=640,
                tracker=TRACKER_CFG,
                device=_g_device,
                half=_g_half,
                verbose=False,
                save=False,
                show=False,
                vid_stride=4    # 如果效能吃緊，可以調整為 2 進行跳幀追踪

            )


# ==================================================
# Execute
# ==================================================

def execute():

    global _g_reader, _g_model, _g_names, _g_device, _g_half

    frame = _g_reader.read_frame()

    if frame is None:
        return "[]"

    # ==================================================
    # YOLO + ByteTrack
    # ==================================================

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
        vid_stride=4    # 如果效能吃緊，可以調整為 2 進行跳幀追踪
    )

    boxes = results[0].boxes

    if boxes is None or len(boxes) == 0:
        return "[]"

    # ==================================================
    # Tensor -> Numpy（一次轉換，共用 .cpu() stream）
    # ==================================================

    # 用 torch 向量化計算 area，避免多次 .cpu() 往返
    xyxy_t = boxes.xyxy          # shape (N,4), float32, on device
    conf_t = boxes.conf          # shape (N,)
    cls_t  = boxes.cls           # shape (N,)
    id_t   = boxes.id            # shape (N,) or None

    # 在 GPU 上先算 area 再 filter（減少搬回 CPU 的資料量）
    if _g_device != "cpu":
        areas_t = (xyxy_t[:, 2] - xyxy_t[:, 0]) * (xyxy_t[:, 3] - xyxy_t[:, 1])
        mask_t  = (conf_t >= CONF_THRES) & (areas_t >= MIN_AREA)

        if _ALLOWED_CLASSES_NP is not None:
            # isin 在 GPU 上用 torch 做
            allowed_t = torch.tensor(
                _ALLOWED_CLASSES_NP,
                device=_g_device,
                dtype=cls_t.dtype
            )
            mask_t &= torch.isin(cls_t, allowed_t)

        if not mask_t.any():
            return "[]"

        # 只把過濾後的資料搬回 CPU
        xyxy  = xyxy_t[mask_t].cpu().numpy().astype(np.int32)
        confs = conf_t[mask_t].cpu().numpy()
        clss  = cls_t[mask_t].cpu().numpy().astype(np.int32)
        ids   = id_t[mask_t].cpu().numpy().astype(np.int32) if id_t is not None else np.full(len(xyxy), -1, dtype=np.int32)
        areas = areas_t[mask_t].cpu().numpy().astype(np.int32)

    else:
        xyxy  = xyxy_t.numpy().astype(np.int32)
        confs = conf_t.numpy()
        clss  = cls_t.numpy().astype(np.int32)
        ids   = id_t.numpy().astype(np.int32) if id_t is not None else np.full(len(xyxy), -1, dtype=np.int32)
        areas = ((xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1]))

        mask  = (confs >= CONF_THRES) & (areas >= MIN_AREA)
        if _ALLOWED_CLASSES_NP is not None:
            mask &= np.isin(clss, _ALLOWED_CLASSES_NP)

        if not np.any(mask):
            return "[]"

        xyxy  = xyxy[mask]
        confs = confs[mask]
        clss  = clss[mask]
        ids   = ids[mask]
        areas = areas[mask].astype(np.int32)

    # ==================================================
    # JSON Output（直接用 list comprehension，避免逐次 append）
    # ==================================================

    names = _g_names   # local ref，避免每次 global lookup

    output = [
        {
            "id":   int(ids[i]),
            "bbox": xyxy[i].tolist(),
            "conf": round(float(confs[i]), 4),   # 限制小數位數，縮短 JSON 長度
            "cls":  int(clss[i]),
            "name": names.get(int(clss[i]), "obj"),
            "area": int(areas[i])
        }
        for i in range(len(ids))
    ]

    return json.dumps(output)   # 去掉空白，縮短輸出


# ==================================================
# Cleanup
# ==================================================

def cleanup():

    global _g_reader

    if _g_reader is not None:
        _g_reader.close()
        _g_reader = None