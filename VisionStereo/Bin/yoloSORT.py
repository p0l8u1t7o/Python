import mmap
import numpy as np
import cv2 as cv
import json
from ultralytics import YOLO
from collections import deque


# ==================================================
# Global
# ==================================================

_g_reader = None
_g_model = None


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

        self.view = np.frombuffer(self.mm, dtype=np.uint8, count=num_elements)

    def read_frame(self):

        data = self.view

        frame = cv.imdecode(data, cv.IMREAD_COLOR)

        return frame

    def close(self):
        del self.view
        self.mm.close()


# ==================================================
# Initialize
# ==================================================

def initialize(tag_name, num_elements):

    global _g_reader, _g_model

    if _g_reader is None:
        _g_reader = MMapReader(tag_name, num_elements)

    if _g_model is None:
        _g_model = YOLO("yolov8n.pt")  # 載入模型（只做一次）




# ==================================================
# SORT (ultra simplified version)
# ==================================================



class Track:
    def __init__(self, bbox, track_id):
        self.bbox = bbox
        self.id = track_id
        self.hits = 1

tracks = []
next_id = 0

def iou(boxA, boxB):
    x1 = max(boxA[0], boxB[0])
    y1 = max(boxA[1], boxB[1])
    x2 = min(boxA[2], boxB[2])
    y2 = min(boxA[3], boxB[3])

    inter = max(0, x2-x1) * max(0, y2-y1)

    areaA = (boxA[2]-boxA[0])*(boxA[3]-boxA[1])
    areaB = (boxB[2]-boxB[0])*(boxB[3]-boxB[1])

    return inter / (areaA + areaB - inter + 1e-6)


def sort_update(detections, iou_thres=0.3):
    global tracks, next_id

    updated_tracks = []

    for det in detections:
        best_iou = 0
        best_track = None

        for t in tracks:
            score = iou(det, t.bbox)
            if score > best_iou:
                best_iou = score
                best_track = t

        if best_iou > iou_thres:
            best_track.bbox = det
            best_track.hits += 1
            updated_tracks.append(best_track)
        else:
            updated_tracks.append(Track(det, next_id))
            next_id += 1

    tracks = updated_tracks
    return tracks



# ==================================================
# EXECUTE
# ==================================================

def execute():

    global _g_reader, _g_model

    frame = _g_reader.read_frame()

    results = _g_model(frame, conf=0.5, verbose=False)
    r = results[0]

    detections = []

    if r.boxes is None:
        return json.dumps([])

    for box in r.boxes:

        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        conf = float(box.conf[0])

        detections.append([x1, y1, x2, y2])

    # =========================
    # SORT tracking
    # =========================
    tracked = sort_update(detections)

    output = []

    for t in tracked:

        x1, y1, x2, y2 = t.bbox

        output.append({
            "id": t.id,
            "bbox": [x1, y1, x2, y2],
            "hits": t.hits
        })

    return json.dumps(output, separators=(',', ':'))


# ==================================================
# Cleanup
# ==================================================

def cleanup():

    global _g_reader

    if _g_reader is not None:
        _g_reader.close()
        _g_reader = None