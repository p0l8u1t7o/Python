"""深度學習工具：ONNX 分類、物件偵測（YOLOv5/v8 風格輸出）、語意分割。

onnxruntime 為可選相依；未安裝時工具在執行時拋 ToolError，平台照常啟動。
Session 依模型路徑快取在模組層（thread-safe）。
"""

from __future__ import annotations

import threading
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.roi import crop, region_overlay

try:  # pragma: no cover - 相依存在與否由環境決定
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None

_SESSIONS: dict[str, Any] = {}
_LOCK = threading.Lock()
_PRELOADED = False

ROI_SHAPES = ["rect", "rotated_rect"]


def preload_gpu_dlls() -> None:
    """onnxruntime-gpu 在 Windows 要自己找 CUDA 12／cuDNN 9 的 DLL：torch cu12x wheel 自帶（torch\\lib），
    先 import torch 讓 DLL 進到行程，再 preload_dlls()（ORT ≥ 1.21 會去 nvidia-* pip 套件與 torch 目錄找）。
    沒做這步 CUDA session 會靜默退回 CPU（provider 列表看起來有 CUDA，實際 session 只剩 CPU）。"""
    global _PRELOADED
    if _PRELOADED:
        return
    _PRELOADED = True
    try:
        import torch  # noqa: F401, PLC0415
    except Exception:  # noqa: BLE001
        pass
    try:
        if ort is not None and hasattr(ort, "preload_dlls"):
            ort.preload_dlls()
    except Exception:  # noqa: BLE001
        pass


def get_session(path: str) -> Any:
    if ort is None:
        raise ToolError("onnxruntime is not installed, so deep-learning tools cannot run")
    with _LOCK:
        sess = _SESSIONS.get(path)
        if sess is None:
            try:
                from apps.vision.dl.devices import preferred_providers

                providers = preferred_providers()
                if any(p != "CPUExecutionProvider" for p in providers):
                    preload_gpu_dlls()
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                # providers 依設定頁選擇（純記憶體查詢；變更設定會 clear_sessions 重建）。
                sess = ort.InferenceSession(path, opts, providers=providers)
            except Exception as exc:  # noqa: BLE001
                raise ToolError(f"Could not load the model: {str(exc)[:200]}") from None
            _SESSIONS[path] = sess
        return sess


def clear_sessions() -> None:
    with _LOCK:
        _SESSIONS.clear()


def _model_path(ctx: ToolContext) -> str:
    asset_id = ctx.param("model")
    if not asset_id:
        raise ToolError("No model is set")
    path = ctx.asset_path(str(asset_id))
    if not path:
        raise ToolError(f"Model asset {asset_id} not found")
    return path


def _labels(ctx: ToolContext) -> list[str]:
    raw = str(ctx.param("labels", "") or "")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _triplet(value: Any, default: tuple[float, float, float]) -> np.ndarray:
    if value in (None, ""):
        return np.array(default, dtype=np.float32)
    try:
        parts = [float(v) for v in str(value).replace(";", ",").split(",") if v.strip()]
    except ValueError:
        raise ToolError(f"Malformed mean/std: {value!r}") from None
    if len(parts) == 1:
        parts = parts * 3
    if len(parts) != 3:
        raise ToolError(f"mean/std needs three numbers: {value!r}")
    return np.array(parts, dtype=np.float32)


def _input_hw(sess: Any, fallback: int) -> tuple[int, int]:
    """模型輸入固定尺寸則用模型的，否則用參數。"""
    shape = sess.get_inputs()[0].shape
    h, w = fallback, fallback
    if len(shape) == 4:
        if isinstance(shape[2], int) and shape[2] > 0:
            h = shape[2]
        if isinstance(shape[3], int) and shape[3] > 0:
            w = shape[3]
    return h, w


def preprocess(image: np.ndarray, size: tuple[int, int], mean: np.ndarray, std: np.ndarray, color_order: str, *, letterbox: bool = False, scale_255: bool = True) -> tuple[np.ndarray, dict[str, float]]:
    """影像 → NCHW float32。回傳 (tensor, {scale, pad_x, pad_y}) 供偵測框換回原座標。"""
    h, w = size
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    ih, iw = image.shape[:2]
    if letterbox:
        scale = min(w / iw, h / ih)
        nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((h, w, 3), 114, dtype=np.uint8)
        px, py = (w - nw) // 2, (h - nh) // 2
        canvas[py : py + nh, px : px + nw] = resized
        image = canvas
        info = {"scale": scale, "pad_x": float(px), "pad_y": float(py)}
    else:
        image = cv2.resize(image, (w, h), interpolation=cv2.INTER_LINEAR)
        info = {"scale_x": w / iw, "scale_y": h / ih, "pad_x": 0.0, "pad_y": 0.0}
    if color_order == "rgb":
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    x = image.astype(np.float32)
    if scale_255:
        x /= 255.0
    x = (x - mean) / std
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None]), info


def softmax(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float64) - v.max()
    e = np.exp(v)
    return e / e.sum()


def _run(sess: Any, tensor: np.ndarray) -> list[np.ndarray]:
    name = sess.get_inputs()[0].name
    try:
        return sess.run(None, {name: tensor})
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Inference failed: {str(exc)[:200]}") from None


def _common_params(size_default: int) -> list[Param]:
    return [
        Param("model", "ONNX model", kind="asset", accept="model", required=True),
        Param("labels", "Class names", kind="multiline", default="", help_text="One class per line, in the model's output order; blank falls back to indices."),
        Param("input_size", "Input size", kind="number", default=size_default, minimum=8, maximum=4096, help_text="A model with a fixed input size wins over this setting."),
        Param("mean", "Mean", kind="text", default="0.485,0.456,0.406", group="Pre-processing", help_text="In 0–1 units; YOLO models normally want 0."),
        Param("std", "Std", kind="text", default="0.229,0.224,0.225", group="Pre-processing", help_text="YOLO models normally want 1."),
        Param("color_order", "Channel order", kind="select", default="rgb", options=[{"value": "rgb", "label": "RGB"}, {"value": "bgr", "label": "BGR"}], group="Pre-processing"),
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Leave blank for the whole image."),
    ]


class DlClassifyTool(Tool):
    key = "dl_classify"
    label = "DL classification"
    description = "Classifies the region with an ONNX model; it passes when the top class scores above the threshold."
    category = "dl"
    icon = "Brain"
    heavy = True
    params = _common_params(224) + [
        Param("top_k", "Top-K", kind="number", default=3, minimum=1, maximum=50),
        Param("threshold", "Score threshold", kind="range", default=0.5, minimum=0, maximum=1, step=0.01, teach=True),
        Param("pass_labels", "Passing classes", kind="text", default="", help_text="Comma separated; when set, the top class must be in this list to pass."),
        Param("apply_softmax", "Apply softmax to the output", kind="boolean", default=True, group="Pre-processing", help_text="Turn off when the model already outputs probabilities."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("pass", "Pass", "ok"), flow_out("fail", "Fail", "critical"), Port("label", "Class", "string"), Port("score", "Score", "number"), Port("index", "Index", "number"), Port("top", "Top-K", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        sess = get_session(_model_path(ctx))
        region = ctx.roi()
        c = crop(image, region, upright=True)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        size = _input_hw(sess, ctx.integer("input_size", 224))
        tensor, _ = preprocess(np.ascontiguousarray(c.image), size, _triplet(ctx.param("mean"), (0.485, 0.456, 0.406)), _triplet(ctx.param("std"), (0.229, 0.224, 0.225)), ctx.param("color_order", "rgb"))
        out = np.asarray(_run(sess, tensor)[0], dtype=np.float32).reshape(-1)
        probs = softmax(out) if ctx.flag("apply_softmax", True) else out.astype(np.float64)
        labels = _labels(ctx)
        names = [labels[i] if i < len(labels) else str(i) for i in range(len(probs))]
        order = np.argsort(-probs)[: ctx.integer("top_k", 3)]
        top = [{"label": names[i], "index": int(i), "score": round(float(probs[i]), 4)} for i in order]
        best = top[0]
        allowed = [s.strip() for s in str(ctx.param("pass_labels", "") or "").split(",") if s.strip()]
        ok = best["score"] >= ctx.number("threshold", 0.5) and (not allowed or best["label"] in allowed)
        overlays = [region_overlay(region, color="#22c55e" if ok else "#ef4444", label=f"{best['label']} {best['score']:.2f}")] if region else [
            {"kind": "text", "x": 8, "y": 24, "text": f"{best['label']} {best['score']:.2f}", "color": "#22c55e" if ok else "#ef4444"},
        ]
        return Result(outputs={"label": best["label"], "score": best["score"], "index": best["index"], "top": top}, overlays=overlays,
                      branch="pass" if ok else "fail", status="ok" if ok else "ng", message=f"{best['label']} {best['score']:.3f}")


def parse_yolo(out: np.ndarray, num_labels: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把 YOLOv5（[1,N,5+nc]）或 YOLOv8（[1,4+nc,N]）輸出轉成 (boxes_xywh_center, scores, class_ids)。"""
    arr = np.asarray(out, dtype=np.float32)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        raise ToolError(f"Unsupported detection output shape {list(np.asarray(out).shape)}")
    # 判斷方向：通道數（4+nc 或 5+nc）通常遠小於候選框數
    if arr.shape[0] < arr.shape[1] and arr.shape[0] < 512:
        arr = arr.T
    cols = arr.shape[1]
    if cols < 5:
        raise ToolError(f"The detection output has too few columns: {cols}")
    if num_labels > 0 and cols == num_labels + 4:
        has_obj = False  # v8：x,y,w,h,cls...
    else:
        has_obj = True  # v5：x,y,w,h,obj,cls...（cols==5 時只有 obj）
    boxes = arr[:, :4]
    if has_obj:
        obj = arr[:, 4:5]
        cls = arr[:, 5:]
        if cls.shape[1] == 0:
            scores, ids = obj.reshape(-1), np.zeros(len(arr), dtype=np.int64)
        else:
            ids = cls.argmax(axis=1)
            scores = (obj.reshape(-1) * cls[np.arange(len(arr)), ids])
    else:
        cls = arr[:, 4:]
        ids = cls.argmax(axis=1)
        scores = cls[np.arange(len(arr)), ids]
    return boxes, scores.astype(np.float32), ids.astype(np.int64)


class DlDetectTool(Tool):
    key = "dl_detect"
    label = "DL object detection"
    description = "Finds objects with an ONNX detection model (YOLOv5 or v8 style output), including letterbox pre-processing and NMS."
    category = "dl"
    icon = "ScanFace"
    heavy = True
    params = [p if p.key not in ("mean", "std") else Param(p.key, p.label, kind="text", default="0" if p.key == "mean" else "1", group="Pre-processing", help_text=p.help_text) for p in _common_params(640)] + [
        Param("conf", "Confidence threshold", kind="range", default=0.25, minimum=0, maximum=1, step=0.01, teach=True),
        Param("iou", "NMS IoU", kind="range", default=0.45, minimum=0, maximum=1, step=0.01),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=1000),
        Param("filter_labels", "Keep classes only", kind="text", default="", help_text="Comma separated; blank keeps everything."),
        Param("min_count", "Min passing count", kind="number", default=1, minimum=0, group="Verdict"),
        Param("normalized", "Output coordinates are 0–1", kind="boolean", default=False, group="Pre-processing", help_text="Turn on when the model outputs normalised boxes."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("detections", "Detections", "matches"), Port("count", "Count", "number"), Port("matches", "Matches (with cx, cy)", "matches"), Port("labels", "Class list", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        sess = get_session(_model_path(ctx))
        region = ctx.roi()
        c = crop(image, region, upright=True)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        sub = np.ascontiguousarray(c.image)
        size = _input_hw(sess, ctx.integer("input_size", 640))
        tensor, info = preprocess(sub, size, _triplet(ctx.param("mean"), (0, 0, 0)), _triplet(ctx.param("std"), (1, 1, 1)), ctx.param("color_order", "rgb"), letterbox=True)
        labels = _labels(ctx)
        boxes, scores, ids = parse_yolo(_run(sess, tensor)[0], len(labels))
        conf = ctx.number("conf", 0.25)
        keep = scores >= conf
        boxes, scores, ids = boxes[keep], scores[keep], ids[keep]
        if ctx.flag("normalized"):
            boxes = boxes * np.array([size[1], size[0], size[1], size[0]], dtype=np.float32)
        detections: list[dict[str, Any]] = []
        if len(boxes):
            # 中心 xywh → 左上 xywh（letterbox 座標）→ 原 crop 座標
            xy = (boxes[:, :2] - boxes[:, 2:] / 2 - np.array([info["pad_x"], info["pad_y"]], dtype=np.float32)) / info["scale"]
            wh = boxes[:, 2:] / info["scale"]
            rects = np.hstack([xy, wh])
            idx = cv2.dnn.NMSBoxes(rects.tolist(), scores.tolist(), conf, ctx.number("iou", 0.45))
            idx = np.asarray(idx).reshape(-1) if idx is not None and len(idx) else np.array([], dtype=int)
            allowed = [s.strip() for s in str(ctx.param("filter_labels", "") or "").split(",") if s.strip()]
            sh, sw = sub.shape[:2]
            for i in idx:
                x, y, w, h = (float(v) for v in rects[i])
                x0, y0 = max(0.0, x), max(0.0, y)
                x1, y1 = min(float(sw), x + w), min(float(sh), y + h)
                if x1 <= x0 or y1 <= y0:
                    continue
                name = labels[ids[i]] if ids[i] < len(labels) else str(int(ids[i]))
                if allowed and name not in allowed:
                    continue
                fx, fy = c.to_full(x0, y0)
                cx, cy = c.to_full((x0 + x1) / 2, (y0 + y1) / 2)
                detections.append({"x": round(fx, 1), "y": round(fy, 1), "w": round(x1 - x0, 1), "h": round(y1 - y0, 1), "cx": round(cx, 1), "cy": round(cy, 1),
                                   "label": name, "index": int(ids[i]), "score": round(float(scores[i]), 4)})
            detections.sort(key=lambda d: -d["score"])
            detections = detections[: ctx.integer("max_count", 100)]
        angle = float(region.get("angle", 0)) if region and region.get("shape") == "rotated_rect" else 0.0
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        for d in detections:
            overlays.append({"kind": "rect", "x": d["cx"] - d["w"] / 2, "y": d["cy"] - d["h"] / 2, "w": d["w"], "h": d["h"], "angle": angle, "color": "#22c55e", "width": 2, "label": f"{d['label']} {d['score']:.2f}"})
        count = len(detections)
        ok = count >= ctx.integer("min_count", 1)
        return Result(outputs={"detections": detections, "count": count, "matches": detections, "labels": [d["label"] for d in detections]}, overlays=overlays,
                      branch="found" if count else "not_found", status="ok" if ok else "ng", message=f"{count} objects")


class DlSegmentTool(Tool):
    key = "dl_segment"
    label = "DL semantic segmentation"
    description = "Runs an ONNX segmentation model to label every pixel (argmax) and returns the class mask and the area of each class."
    category = "dl"
    icon = "Layers"
    heavy = True
    params = _common_params(512) + [
        Param("target_class", "Target class index", kind="number", default=1, minimum=0, help_text="The mask output is a 0/255 mask of this class; class_map holds every class index."),
        Param("min_area", "Min passing area", kind="number", default=0, minimum=0, unit="px²", group="Verdict"),
        Param("max_area", "Max passing area", kind="number", default=0, minimum=0, unit="px²", group="Verdict", help_text="0 means no limit."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("ok", "Pass", "ok"), flow_out("ng", "Fail", "critical"), Port("mask", "Target mask", "image"), Port("class_map", "Class map", "image"), Port("area", "Target area", "number"), Port("classes", "Area per class", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        sess = get_session(_model_path(ctx))
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        sub = np.ascontiguousarray(c.image)
        size = _input_hw(sess, ctx.integer("input_size", 512))
        tensor, _ = preprocess(sub, size, _triplet(ctx.param("mean"), (0.485, 0.456, 0.406)), _triplet(ctx.param("std"), (0.229, 0.224, 0.225)), ctx.param("color_order", "rgb"))
        out = np.asarray(_run(sess, tensor)[0])
        if out.ndim == 4:
            out = out[0]
        if out.ndim == 3:
            if out.shape[0] <= 256 and out.shape[0] < out.shape[-1]:
                cls = out.argmax(axis=0) if out.shape[0] > 1 else (out[0] > 0.5)
            else:
                cls = out.argmax(axis=-1)
        elif out.ndim == 2:
            cls = out
        else:
            raise ToolError(f"Unsupported segmentation output shape {list(out.shape)}")
        cls = np.asarray(cls).astype(np.uint8)
        cls = cv2.resize(cls, (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_NEAREST)
        if c.mask is not None:
            cls[c.mask == 0] = 0
        target = ctx.integer("target_class", 1)
        mask_sub = ((cls == target).astype(np.uint8) * 255)
        h, w = image.shape[:2]
        full_mask = np.zeros((h, w), dtype=np.uint8)
        full_cls = np.zeros((h, w), dtype=np.uint8)
        full_mask[c.y0 : c.y0 + mask_sub.shape[0], c.x0 : c.x0 + mask_sub.shape[1]] = mask_sub
        full_cls[c.y0 : c.y0 + cls.shape[0], c.x0 : c.x0 + cls.shape[1]] = cls
        labels = _labels(ctx)
        counts = np.bincount(cls.reshape(-1), minlength=max(len(labels), target + 1))
        classes = [{"index": i, "label": labels[i] if i < len(labels) else str(i), "area": int(n)} for i, n in enumerate(counts) if n > 0]
        area = int(counts[target]) if target < len(counts) else 0
        lo, hi = ctx.number("min_area", 0), ctx.number("max_area", 0)
        ok = area >= lo and (hi <= 0 or area <= hi)
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if area:
            contours, _ = cv2.findContours(full_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            overlays.append({"kind": "contours", "contours": [cnt.reshape(-1, 2).tolist() for cnt in contours], "color": "#22c55e" if ok else "#ef4444", "width": 1, "label": f"area={area}"})
        return Result(outputs={"mask": full_mask, "class_map": full_cls, "area": area, "classes": classes}, overlays=overlays,
                      branch="ok" if ok else "ng", status="ok" if ok else "ng", message=f"Target class area {area}px²")


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def parse_yolo_seg(det: np.ndarray, protos: np.ndarray, *, conf: float, iou: float, max_count: int, size: tuple[int, int]) -> list[dict[str, Any]]:
    """YOLOv8-seg 輸出 → 實例清單（letterbox 空間座標）。

    det: [1, 4+nc+nm, N] 或 [1, N, 4+nc+nm]；protos: [1, nm, mh, mw]。
    回傳 [{box(xyxy), score, class_id, mask(HxW bool, letterbox 空間)}]。
    """
    d = np.asarray(det, dtype=np.float32)
    if d.ndim == 3:
        d = d[0]
    p = np.asarray(protos, dtype=np.float32)
    if p.ndim == 4:
        p = p[0]
    nm = p.shape[0]
    # 通道維（4+nc+nm）遠小於候選框數 → 轉成 [N, ch]
    if d.shape[0] < d.shape[1]:
        d = d.T
    ch = d.shape[1]
    nc = ch - 4 - nm
    if nc < 1:
        raise ToolError(f"Not a YOLO-seg output ({ch} columns, {nm} protos)")
    boxes_cxcywh = d[:, :4]
    cls_scores = d[:, 4 : 4 + nc]
    coefs = d[:, 4 + nc :]
    scores = cls_scores.max(axis=1)
    keep = scores >= conf
    if not keep.any():
        return []
    boxes_cxcywh, cls_scores, coefs, scores = boxes_cxcywh[keep], cls_scores[keep], coefs[keep], scores[keep]
    ids = cls_scores.argmax(axis=1)
    xywh = np.stack([boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2, boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2, boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]], axis=1)
    picked = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), conf, iou)
    picked = np.asarray(picked).reshape(-1)[:max_count]
    if not len(picked):
        return []
    h, w = size
    mh, mw = p.shape[1], p.shape[2]
    proto_flat = p.reshape(nm, -1)
    out: list[dict[str, Any]] = []
    for i in picked:
        mask_small = _sigmoid(coefs[i] @ proto_flat).reshape(mh, mw)
        mask = cv2.resize(mask_small, (w, h), interpolation=cv2.INTER_LINEAR) > 0.5
        x0, y0, bw, bh = xywh[i]
        x1, y1 = x0 + bw, y0 + bh
        box_mask = np.zeros((h, w), dtype=bool)
        xa, ya = max(0, int(x0)), max(0, int(y0))
        xb, yb = min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1)))
        if xb > xa and yb > ya:
            box_mask[ya:yb, xa:xb] = True
        mask &= box_mask
        out.append({"box": (float(x0), float(y0), float(x1), float(y1)), "score": float(scores[i]), "class_id": int(ids[i]), "mask": mask})
    return out


class DlInstanceTool(Tool):
    key = "dl_instance"
    label = "DL instance segmentation"
    description = "Finds each object's contour and class with a YOLO-seg style ONNX model, including letterbox pre-processing, NMS and mask assembly. You can train one on the platform's deep-learning page."
    category = "dl"
    icon = "Shapes"
    heavy = True
    params = [p if p.key not in ("mean", "std") else Param(p.key, p.label, kind="text", default="0" if p.key == "mean" else "1", group="Pre-processing", help_text=p.help_text) for p in _common_params(640)] + [
        Param("conf", "Confidence threshold", kind="range", default=0.25, minimum=0, maximum=1, step=0.01, teach=True),
        Param("iou", "NMS IoU", kind="range", default=0.45, minimum=0, maximum=1, step=0.01),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=1000),
        Param("filter_labels", "Keep classes only", kind="text", default="", help_text="Comma separated; blank keeps everything."),
        Param("min_count", "Min passing count", kind="number", default=1, minimum=0, group="Verdict"),
        Param("max_count_ok", "Max passing count", kind="number", default=0, minimum=0, group="Verdict", help_text="0 means no limit."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("count", "Count", "number"), Port("matches", "Instances", "matches"), Port("mask", "Union mask", "image"), Port("contours", "Contour", "contours")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        sess = get_session(_model_path(ctx))
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        sub = np.ascontiguousarray(c.image)
        size = _input_hw(sess, ctx.integer("input_size", 640))
        tensor, info = preprocess(sub, size, _triplet(ctx.param("mean"), (0.0, 0.0, 0.0)), _triplet(ctx.param("std"), (1.0, 1.0, 1.0)), ctx.param("color_order", "rgb"), letterbox=True)
        outputs = _run(sess, tensor)
        protos = next((o for o in outputs if np.asarray(o).ndim == 4), None)
        det = next((o for o in outputs if np.asarray(o) is not protos), None)
        if protos is None or det is None:
            raise ToolError("The model output has no protos (is it a YOLO-seg model?)")
        instances = parse_yolo_seg(det, protos, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_count=ctx.integer("max_count", 100), size=size)

        labels = _labels(ctx)
        allowed = {s.strip() for s in str(ctx.param("filter_labels", "") or "").split(",") if s.strip()}
        scale, pad_x, pad_y = info.get("scale", 1.0), info["pad_x"], info["pad_y"]
        sh, sw = sub.shape[:2]
        full_h, full_w = image.shape[:2]
        union = np.zeros((full_h, full_w), dtype=np.uint8)
        matches, contour_list, overlays = [], [], []
        for inst in instances:
            name = labels[inst["class_id"]] if inst["class_id"] < len(labels) else str(inst["class_id"])
            if allowed and name not in allowed:
                continue
            # letterbox 空間 → 子圖 → 全圖
            mask_lb = inst["mask"]
            x_lo, y_lo = int(round(pad_x)), int(round(pad_y))
            mask_sub_lb = mask_lb[y_lo : y_lo + max(1, int(round(sh * scale))), x_lo : x_lo + max(1, int(round(sw * scale)))]
            mask_sub = cv2.resize(mask_sub_lb.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST)
            area = int(mask_sub.sum())
            if not area:
                continue
            union[c.y0 : c.y0 + sh, c.x0 : c.x0 + sw] |= mask_sub * 255
            contours, _ = cv2.findContours(mask_sub * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            polys = [(cnt.reshape(-1, 2) + [c.x0, c.y0]).tolist() for cnt in contours if len(cnt) >= 3]
            contour_list += polys
            x0, y0, x1, y1 = inst["box"]
            bx0, by0 = (x0 - pad_x) / scale + c.x0, (y0 - pad_y) / scale + c.y0
            bx1, by1 = (x1 - pad_x) / scale + c.x0, (y1 - pad_y) / scale + c.y0
            matches.append({"label": name, "score": round(inst["score"], 4), "x": round(bx0, 1), "y": round(by0, 1), "w": round(bx1 - bx0, 1), "h": round(by1 - by0, 1), "area": area})
            if polys:
                overlays.append({"kind": "contours", "contours": polys, "color": "#22c55e", "width": 1, "label": f"{name} {inst['score']:.2f}"})
        if region:
            overlays.append(region_overlay(region, label="roi"))
        count = len(matches)
        lo, hi = ctx.integer("min_count", 1), ctx.integer("max_count_ok", 0)
        ok = count >= lo and (hi <= 0 or count <= hi)
        return Result(outputs={"count": count, "matches": matches, "mask": union, "contours": [np.array(p).reshape(-1, 1, 2) for p in contour_list]},
                      overlays=overlays, branch="found" if count else "not_found", status="ok" if ok else "ng", message=f"{count} instances")


TOOLS = [DlClassifyTool(), DlDetectTool(), DlSegmentTool(), DlInstanceTool()]
