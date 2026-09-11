"""YOLO 工具（ultralytics 原生推論）：物件偵測、實例分割、影像分類、姿態（關鍵點）、旋轉框（OBB）。

- 模型來源二選一：「模型資產」（教導頁訓練出的 .pt／.onnx，或自己上傳的 .pt）優先；沒選時用「底模名稱」
  （官方 yolo11n.pt、yolo11n-seg.pt… 第一次使用自動下載到 ASSET_DIR/dl/weights，或本機 .pt 路徑）。
- 推論走 torch（GPU 有就用；auto／cuda／cpu 可指定），前處理／NMS 由 ultralytics 處理，與訓練一致；
  模型在行程內快取（apps/vision/dl/yolo_runtime.py），同一模型的推論序列化。
- 座標一律回映到該節點輸入影像的全圖座標（ROI 用 crop／to_full）；overlays 只是顯示層。
- 未安裝 ultralytics／torch：執行時回 ToolError（平台照常啟動、工具照常列在目錄）。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.messages import Msg
from apps.vision.tools.roi import crop, region_overlay

ROI_SHAPES = ["rect", "rotated_rect"]
GREEN = "#22c55e"
#: COCO 17 關鍵點的骨架連線（姿態模型輸出 17 點時畫）。
COCO_SKELETON = [(15, 13), (13, 11), (16, 14), (14, 12), (11, 12), (5, 11), (6, 12), (5, 6), (5, 7), (6, 8), (7, 9), (8, 10), (1, 2), (0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 6)]
IMGSZ_OPTIONS = [{"value": 320, "label": "320"}, {"value": 480, "label": "480"}, {"value": 640, "label": "640 (recommended)"}, {"value": 960, "label": "960"}, {"value": 1280, "label": "1280"}]
DEVICE_OPTIONS = [{"value": "auto", "label": "Automatic (use the GPU when there is one)"}, {"value": "cuda", "label": "GPU (CUDA)"}, {"value": "cpu", "label": "CPU"}]
PRECISION_OPTIONS = [{"value": "full", "label": "Full precision"}, {"value": "auto", "label": "Automatic"}, {"value": "half", "label": "Half precision"}]
BACKEND_OPTIONS = [{"value": "eager", "label": "Standard"}, {"value": "torchscript", "label": "Compiled"}]
TRACKER_OPTIONS = [{"value": "none", "label": "None"}, {"value": "bytetrack", "label": "ByteTrack"}, {"value": "botsort", "label": "BoT-SORT"}]


#: 官方底模檔名的後綴（技術名稱只留在這裡與 dl/yolo.py；產品表面只有「大小」）。
STOCK_SUFFIX = {"detect": "", "segment": "-seg", "classify": "-cls", "pose": "-pose", "obb": "-obb"}
SIZE_OPTIONS = [
    {"value": "n", "label": "Nano (fastest, default)"}, {"value": "s", "label": "Small"}, {"value": "m", "label": "Medium"},
    {"value": "l", "label": "Large"}, {"value": "x", "label": "Extra large (most accurate, slowest)"},
]


def stock_model(task: str, size: str = "n") -> str:
    """任務＋大小 → 官方底模檔名（不存在的大小退回 nano）。"""
    size = str(size or "n").strip().lower()
    if size not in "nsmlx" or len(size) != 1:
        size = "n"
    return f"yolo11{size}{STOCK_SUFFIX.get(task, '')}.pt"


def _common_params(task: str, imgsz: int = 640) -> list[Param]:
    return [
        Param("model", "Model asset", kind="asset", accept="model", required=False, help_text="A model trained on the teaching page (.pt or .onnx) or one you uploaded; blank falls back to the stock model below."),
        Param("model_size", "Stock model size", kind="select", default="n", options=SIZE_OPTIONS, help_text="Used only when no model asset is chosen; larger is more accurate but slower. The stock model downloads on first use."),
        Param("model_name", "Model file (advanced)", kind="text", default="", group="Advanced", help_text="A local .pt path that overrides the stock model; leave blank normally."),
        Param("imgsz", "Inference size", kind="select", default=imgsz, options=IMGSZ_OPTIONS if task != "classify" else [{"value": 224, "label": "224 (recommended)"}, {"value": 320, "label": "320"}], help_text="Most accurate when it matches training."),
        Param("device", "Device", kind="select", default="auto", options=DEVICE_OPTIONS, group="Advanced"),
        Param("half", "Half precision (FP16)", kind="boolean", default=False, group="Advanced", help_text="GPU only: faster and lighter on memory."),
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Leave blank for the whole image."),
    ]


def _detect_params() -> list[Param]:
    return [
        Param("conf", "Confidence threshold", kind="range", default=0.25, minimum=0, maximum=1, step=0.01, teach=True),
        Param("iou", "NMS IoU", kind="range", default=0.45, minimum=0, maximum=1, step=0.01, group="Advanced"),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=1000, group="Advanced"),
        Param("filter_labels", "Keep classes only", kind="text", default="", help_text="Comma separated; blank keeps everything."),
        Param("min_count", "Min passing count", kind="number", default=1, minimum=0, group="Verdict"),
        Param("max_count_ok", "Max passing count", kind="number", default=0, minimum=0, group="Verdict", help_text="0 means no limit."),
    ]


class _YoloTool(Tool):
    category = "dl"
    icon = "ScanFace"
    heavy = True
    task = ""
    #: 允許載入的模型任務（例如偵測工具也能吃分割／姿態模型的框）。
    accepted_tasks: tuple[str, ...] = ()

    def _model(self, ctx: ToolContext):
        from apps.vision.dl import yolo_runtime

        asset_id = ctx.param("model")
        try:
            if asset_id:
                path = ctx.asset_path(str(asset_id))
                if not path:
                    raise ToolError(Msg.of("ai_tool.model_missing", "Model asset {asset_id} not found", asset_id=asset_id))
                model = yolo_runtime.load(path, task=self.task)
            else:
                name = str(ctx.param("model_name") or "").strip() or stock_model(self.task, str(ctx.param("model_size") or "n"))
                model = yolo_runtime.load(name, task=self.task)
        except yolo_runtime.ModelUnavailable as exc:
            raise ToolError(str(exc)) from None
        task = yolo_runtime.task_of(model)
        if task and task not in (self.accepted_tasks or (self.task,)):
            raise ToolError(Msg.of("ai_tool.task_mismatch", "The model does {task} but this tool needs {needed}; use the matching AI tool", task=task, needed=self.task))
        return model

    def _predict(self, ctx: ToolContext, model: Any, image: np.ndarray, **extra: Any):
        from apps.vision.dl import yolo_runtime

        device, note = yolo_runtime.pick_device(ctx.param("device", "auto"))
        kw: dict[str, Any] = {"imgsz": ctx.integer("imgsz", 640), "device": device, **extra}
        precision = str(ctx.param("precision", "") or "").lower()
        use_half = bool(ctx.flag("half") or precision == "half" or (precision == "auto" and device.startswith("cuda")))
        if use_half and device.startswith("cuda"):
            kw["half"] = True  # 只在要求時傳（ultralytics 8.4 對 half=False 也會印棄用警告）
        try:
            result = yolo_runtime.predict(model, image, **kw)
        except yolo_runtime.ModelUnavailable as exc:
            raise ToolError(str(exc)) from None
        return result, device, note

    def _track(self, ctx: ToolContext, model: Any, image: np.ndarray, tracker: str, **extra: Any):
        from apps.vision.dl import yolo_runtime

        device, note = yolo_runtime.pick_device(ctx.param("device", "auto"))
        kw: dict[str, Any] = {"imgsz": ctx.integer("imgsz", 640), "device": device, **extra}
        precision = str(ctx.param("precision", "") or "").lower()
        use_half = bool(ctx.flag("half") or precision == "half" or (precision == "auto" and device.startswith("cuda")))
        if use_half and device.startswith("cuda"):
            kw["half"] = True
        state_key = None
        if not ctx.sandboxed():
            state_key = f"{ctx.flow_id}:{ctx.node.get('id', '')}:{tracker}"
        try:
            result = yolo_runtime.track(model, image, state_key=state_key, tracker=tracker, **kw)
        except yolo_runtime.ModelUnavailable as exc:
            raise ToolError(str(exc)) from None
        return result, device, note

    @staticmethod
    def _allowed(ctx: ToolContext) -> set[str]:
        return {s.strip() for s in str(ctx.param("filter_labels", "") or "").split(",") if s.strip()}

    @staticmethod
    def _crop(ctx: ToolContext, image: np.ndarray, *, upright: bool):
        region = ctx.roi()
        c = crop(image, region, upright=upright) if upright else crop(image, region)
        if c.image.size == 0:
            raise ToolError(Msg.of("ai_tool.bad_region", "The region falls outside the image"))
        return region, c, np.ascontiguousarray(c.image)

    @staticmethod
    def _verdict(ctx: ToolContext, count: int) -> tuple[str, str]:
        lo, hi = ctx.integer("min_count", 1), ctx.integer("max_count_ok", 0)
        ok = count >= lo and (hi <= 0 or count <= hi)
        return ("found" if count else "not_found"), ("ok" if ok else "ng")


def _boxes(result: Any, names: dict[int, str], allowed: set[str], c, region) -> list[dict[str, Any]]:
    """Results.boxes → 全圖座標的框列表（含 cx, cy），依 filter_labels 過濾。"""
    out: list[dict[str, Any]] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return out
    xyxy = boxes.xyxy.cpu().numpy()
    conf = boxes.conf.cpu().numpy()
    cls = boxes.cls.cpu().numpy().astype(int)
    for i in range(len(xyxy)):
        name = names.get(int(cls[i]), str(int(cls[i])))
        if allowed and name not in allowed:
            continue
        x0, y0, x1, y1 = (float(v) for v in xyxy[i])
        fx, fy = c.to_full(x0, y0)
        cx, cy = c.to_full((x0 + x1) / 2, (y0 + y1) / 2)
        out.append({"x": round(fx, 1), "y": round(fy, 1), "w": round(x1 - x0, 1), "h": round(y1 - y0, 1), "cx": round(cx, 1), "cy": round(cy, 1),
                    "label": name, "index": int(cls[i]), "score": round(float(conf[i]), 4), "_i": i})
    out.sort(key=lambda d: -d["score"])
    return out


def _rect_overlay(d: dict[str, Any], angle: float, label: str | None = None) -> dict[str, Any]:
    return {"kind": "rect", "x": d["cx"] - d["w"] / 2, "y": d["cy"] - d["h"] / 2, "w": d["w"], "h": d["h"], "angle": angle, "color": GREEN, "width": 2,
            "label": label if label is not None else f"{d['label']} {d['score']:.2f}"}


def _region_angle(region: dict[str, Any] | None) -> float:
    return float(region.get("angle", 0)) if region and region.get("shape") == "rotated_rect" else 0.0


def _track_ids(result: Any, n: int) -> list[int | None]:
    boxes = getattr(result, "boxes", None)
    raw = getattr(boxes, "id", None)
    if raw is not None:
        arr = raw.cpu().numpy()
        return [int(v) for v in arr[:n]]
    data = getattr(boxes, "data", None)
    if data is not None:
        arr = data.cpu().numpy()
        is_track = bool(getattr(boxes, "is_track", arr.shape[1] == 7))
        if is_track and arr.shape[1] >= 7:
            return [int(v) for v in arr[:n, -3]]
    return [None for _ in range(n)]


def _largest_component(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """取出二值 mask 內最大連通塊；回傳該塊 mask 與原 mask 面積。"""
    m = (mask > 0).astype(np.uint8)
    total = int(m.sum())
    if not total:
        return m, 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return m, total
    areas = stats[1:, cv2.CC_STAT_AREA]
    label = int(np.argmax(areas) + 1)
    return (labels == label).astype(np.uint8), total


def _polygon_centroid(mask: np.ndarray, c, *, max_points: int) -> tuple[list[list[float]], list[float] | None, int]:
    """由最大連通塊建立簡化 polygon 與全圖質心。"""
    largest, mask_area = _largest_component(mask)
    if not mask_area:
        return [], None, 0
    moments = cv2.moments(largest, binaryImage=True)
    if moments["m00"] > 0:
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
    else:
        ys, xs = np.nonzero(largest)
        cx = float(xs.mean()) if len(xs) else 0.0
        cy = float(ys.mean()) if len(ys) else 0.0
    fx, fy = c.to_full(cx, cy)
    contours, _ = cv2.findContours(largest * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [], [round(float(fx), 2), round(float(fy), 2)], mask_area
    cnt = max(contours, key=cv2.contourArea)
    eps = 0.01 * cv2.arcLength(cnt, True)
    poly = cv2.approxPolyDP(cnt, eps, True).reshape(-1, 2).astype(np.float32)
    if len(poly) > max_points:
        poly = poly[np.linspace(0, len(poly) - 1, max_points).astype(np.int64)]
    points = [[round(float(c.to_full(float(x), float(y))[0]), 1), round(float(c.to_full(float(x), float(y))[1]), 1)] for x, y in poly]
    return points, [round(float(fx), 2), round(float(fy), 2)], mask_area


class YoloDetectTool(_YoloTool):
    key = "ai_detect"
    label = "Object detection (AI)"
    description = "Finds objects with a neural network — a stock model or one trained on the teaching page — returning boxes, classes and scores. A GPU is used automatically when present."
    task = "detect"
    accepted_tasks = ("detect", "segment", "pose", "obb")
    params = _common_params("detect") + _detect_params()
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("detections", "Detections", "matches"), Port("count", "Count", "number"),
               Port("matches", "Matches (with cx, cy)", "matches"), Port("labels", "Class list", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.dl import yolo_runtime

        image = ctx.require_image()
        model = self._model(ctx)
        region, c, sub = self._crop(ctx, image, upright=True)
        result, device, note = self._predict(ctx, model, sub, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_det=ctx.integer("max_count", 100))
        dets = _boxes(result, yolo_runtime.names_of(model), self._allowed(ctx), c, region) if result is not None else []
        for d in dets:
            d.pop("_i", None)
        angle = _region_angle(region)
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        overlays += [_rect_overlay(d, angle) for d in dets]
        count = len(dets)
        branch, status = self._verdict(ctx, count)
        return Result(outputs={"detections": dets, "count": count, "matches": dets, "labels": [d["label"] for d in dets]}, overlays=overlays,
                      branch=branch, status=status, message=(Msg.of("ai_detect.objects_note", "{count} objects ({device}, {note})", count=count, device=device, note=note) if note
                               else Msg.of("ai_detect.objects", "{count} objects ({device})", count=count, device=device)))


class YoloSegmentTool(_YoloTool):
    key = "ai_segment"
    label = "Instance segmentation (AI)"
    description = "Uses an instance-segmentation network (a stock model or one trained on the teaching page) to find each object's contour, class and area, and outputs a union mask and contours for later measurement."
    task = "segment"
    icon = "Brain"
    params = _common_params("segment") + _detect_params() + [
        Param("min_area", "Min area", kind="number", default=0, minimum=0, unit="px²", group="Verdict", help_text="Instances smaller than this are skipped."),
        Param("max_polygon_points", "Max polygon points", kind="number", default=12, minimum=3, maximum=200, group="Advanced"),
        Param("precision", "Precision", kind="select", default="full", options=PRECISION_OPTIONS, group="Advanced"),
        Param("backend", "Runtime backend", kind="select", default="eager", options=BACKEND_OPTIONS, group="Advanced"),
        Param("tracker", "Tracker", kind="select", default="none", options=TRACKER_OPTIONS, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("count", "Count", "number"), Port("matches", "Instances", "matches"),
               Port("mask", "Union mask", "image"), Port("contours", "Contour", "contours"), Port("labels", "Class list", "list"), Port("centroids", "Centroids", "points")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.dl import yolo_runtime

        image = ctx.require_image()
        model = self._model(ctx)
        region, c, sub = self._crop(ctx, image, upright=False)

        ts_requested = str(ctx.param("backend", "eager") or "eager") == "torchscript"
        ts_installed = yolo_runtime.install_torchscript(model, sub) if ts_requested else False
        tracker = str(ctx.param("tracker", "none") or "none").lower()
        if tracker in ("bytetrack", "botsort"):
            result, device, note = self._track(ctx, model, sub, tracker, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_det=ctx.integer("max_count", 100))
        else:
            result, device, note = self._predict(ctx, model, sub, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_det=ctx.integer("max_count", 100))
        if ts_requested and not ts_installed:
            yolo_runtime.install_torchscript(model, sub)
        names, allowed = yolo_runtime.names_of(model), self._allowed(ctx)
        full_h, full_w = image.shape[:2]
        sh, sw = sub.shape[:2]
        union = np.zeros((full_h, full_w), dtype=np.uint8)
        matches: list[dict[str, Any]] = []
        centroids: list[list[float]] = []
        contour_list: list[list[list[int]]] = []
        overlays: list[dict[str, Any]] = []
        min_area = ctx.integer("min_area", 0)
        max_points = max(3, ctx.integer("max_polygon_points", 12))
        masks = getattr(result, "masks", None) if result is not None else None
        boxes = getattr(result, "boxes", None) if result is not None else None
        if boxes is not None and len(boxes):
            data = masks.data.cpu().numpy() if masks is not None else None  # (n, mh, mw)，可能與 sub 尺寸不同
            conf = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            xyxy = boxes.xyxy.cpu().numpy()
            track_ids = _track_ids(result, len(xyxy))
            n_items = len(data) if data is not None else len(xyxy)
            for i in range(n_items):
                name = names.get(int(cls[i]), str(int(cls[i])))
                if allowed and name not in allowed:
                    continue
                x0, y0, x1, y1 = (float(v) for v in xyxy[i])
                cx, cy = c.to_full((x0 + x1) / 2, (y0 + y1) / 2)
                polygon: list[list[float]] = []
                centroid = [round(float(cx), 2), round(float(cy), 2)]
                mask_area = 0
                area = 0
                polys: list[list[list[int]]] = []
                if data is not None:
                    m = data[i]
                    if m.shape != (sh, sw):
                        m = cv2.resize(m.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST)
                    m = (m > 0).astype(np.uint8)
                    area = int(m.sum())
                    polygon, found_centroid, mask_area = _polygon_centroid(m, c, max_points=max_points)
                    if found_centroid is not None:
                        centroid = found_centroid
                    contours, _ = cv2.findContours(m * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    polys = [(cnt.reshape(-1, 2) + [c.x0, c.y0]).tolist() for cnt in contours if len(cnt) >= 3]
                else:
                    area = int(max(0.0, x1 - x0) * max(0.0, y1 - y0))
                if not area or area < min_area:
                    continue
                if data is not None:
                    union[c.y0 : c.y0 + sh, c.x0 : c.x0 + sw] |= m * 255
                    contour_list += polys
                item = {"label": name, "index": int(cls[i]), "score": round(float(conf[i]), 4), "x": round(x0 + c.x0, 1), "y": round(y0 + c.y0, 1),
                        "w": round(x1 - x0, 1), "h": round(y1 - y0, 1), "cx": round((x0 + x1) / 2 + c.x0, 1), "cy": round((y0 + y1) / 2 + c.y0, 1), "area": area,
                        "polygon": polygon, "centroid": centroid, "mask_area": mask_area}
                if track_ids[i] is not None:
                    item["track_id"] = track_ids[i]
                matches.append(item)
                centroids.append(centroid)
                if polys:
                    overlays.append({"kind": "contours", "contours": polys, "color": GREEN, "width": 1, "label": f"{name} {float(conf[i]):.2f}"})
        if region:
            overlays.append(region_overlay(region, label="roi"))
        count = len(matches)
        branch, status = self._verdict(ctx, count)
        return Result(outputs={"count": count, "matches": matches, "mask": union, "contours": [np.array(p).reshape(-1, 1, 2) for p in contour_list], "labels": [m["label"] for m in matches], "centroids": centroids},
                      overlays=overlays, branch=branch, status=status, message=(Msg.of("ai_segment.instances_note", "{count} instances ({device}, {note})", count=count, device=device, note=note) if note
                               else Msg.of("ai_segment.instances", "{count} instances ({device})", count=count, device=device)))


class YoloClassifyTool(_YoloTool):
    key = "ai_classify"
    label = "Classification (AI)"
    description = "Classifies the region with a classification network (a stock model or one trained on the teaching page); it passes when the top class scores above the threshold and is in the passing list."
    task = "classify"
    icon = "Brain"
    params = _common_params("classify", imgsz=224) + [
        Param("threshold", "Score threshold", kind="range", default=0.5, minimum=0, maximum=1, step=0.01, teach=True),
        Param("top_k", "Top-K", kind="number", default=3, minimum=1, maximum=50),
        Param("pass_labels", "Passing classes", kind="text", default="", help_text="Comma separated; when set, the top class must be in this list to pass."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("pass", "Pass", "ok"), flow_out("fail", "Fail", "critical"), Port("label", "Class", "string"), Port("score", "Score", "number"), Port("index", "Index", "number"), Port("top", "Top-K", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.dl import yolo_runtime

        image = ctx.require_image()
        model = self._model(ctx)
        region, c, sub = self._crop(ctx, image, upright=True)
        result, device, note = self._predict(ctx, model, sub)
        names = yolo_runtime.names_of(model)
        probs = getattr(result, "probs", None) if result is not None else None
        if probs is None:
            raise ToolError(Msg.of("ai_classify.no_probs", "The model has no classification output (is it a classifier?)"))
        k = ctx.integer("top_k", 3)
        idx = [int(i) for i in probs.top5[:k]]
        scores = [round(float(v), 4) for v in probs.top5conf[:k]]
        top = [{"label": names.get(i, str(i)), "index": i, "score": s} for i, s in zip(idx, scores, strict=False)]
        best = top[0] if top else {"label": "", "index": -1, "score": 0.0}
        allowed = {s.strip() for s in str(ctx.param("pass_labels", "") or "").split(",") if s.strip()}
        ok = best["score"] >= ctx.number("threshold", 0.5) and (not allowed or best["label"] in allowed)
        ax, ay = c.to_full(0, 0)
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        overlays.append({"kind": "text", "x": float(ax) + 4, "y": float(ay) + 18, "text": f"{best['label']} {best['score']:.2f}", "color": GREEN if ok else "#ef4444"})
        return Result(outputs={"label": best["label"], "score": best["score"], "index": best["index"], "top": top}, overlays=overlays,
                      branch="pass" if ok else "fail", status="ok" if ok else "ng", message=(Msg.of("ai_classify.result_note", "{label} {score:.2f} ({device}, {note})", label=best['label'], score=best['score'], device=device, note=note) if note
                               else Msg.of("ai_classify.result", "{label} {score:.2f} ({device})", label=best['label'], score=best['score'], device=device)))


class YoloPoseTool(_YoloTool):
    key = "ai_pose"
    label = "Pose keypoints (AI)"
    description = "Finds objects with a pose network and returns each object's keypoint coordinates and confidence (the 17 COCO body points or your own), for position and pose checks."
    task = "pose"
    icon = "PersonStanding"
    params = _common_params("pose") + _detect_params() + [
        Param("kpt_conf", "Keypoint confidence", kind="range", default=0.3, minimum=0, maximum=1, step=0.05, help_text="Keypoints below the threshold are not drawn but are still output, each with its confidence."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("count", "Count", "number"), Port("matches", "Boxes", "matches"),
               Port("keypoints", "Keypoints", "list"), Port("labels", "Class list", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.dl import yolo_runtime

        image = ctx.require_image()
        model = self._model(ctx)
        region, c, sub = self._crop(ctx, image, upright=True)
        result, device, note = self._predict(ctx, model, sub, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_det=ctx.integer("max_count", 100))
        dets = _boxes(result, yolo_runtime.names_of(model), self._allowed(ctx), c, region) if result is not None else []
        kpts = getattr(result, "keypoints", None) if result is not None else None
        xy = kpts.xy.cpu().numpy() if kpts is not None and kpts.xy is not None else None
        kc = kpts.conf.cpu().numpy() if kpts is not None and getattr(kpts, "conf", None) is not None else None
        thr = ctx.number("kpt_conf", 0.3)
        angle = _region_angle(region)
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        keypoints: list[dict[str, Any]] = []
        for d in dets:
            i = d.pop("_i")
            pts: list[list[float]] = []
            if xy is not None and i < len(xy):
                for j in range(len(xy[i])):
                    px, py = c.to_full(float(xy[i][j][0]), float(xy[i][j][1]))
                    conf_j = float(kc[i][j]) if kc is not None else 1.0
                    pts.append([round(px, 1), round(py, 1), round(conf_j, 3)])
            keypoints.append({"label": d["label"], "score": d["score"], "points": pts})
            overlays.append(_rect_overlay(d, angle))
            visible = [(p[0], p[1]) for p in pts if p[2] >= thr and (p[0] or p[1])]
            if visible:
                overlays.append({"kind": "points", "points": [[x, y] for x, y in visible], "color": "#f59e0b", "width": 3})
            if len(pts) == 17:
                for a, b in COCO_SKELETON:
                    if pts[a][2] >= thr and pts[b][2] >= thr and (pts[a][0] or pts[a][1]) and (pts[b][0] or pts[b][1]):
                        overlays.append({"kind": "line", "x1": pts[a][0], "y1": pts[a][1], "x2": pts[b][0], "y2": pts[b][1], "color": "#f59e0b", "width": 1})
        count = len(dets)
        branch, status = self._verdict(ctx, count)
        return Result(outputs={"count": count, "matches": dets, "keypoints": keypoints, "labels": [d["label"] for d in dets]}, overlays=overlays,
                      branch=branch, status=status, message=(Msg.of("ai_pose.objects_note", "{count} objects ({device}, {note})", count=count, device=device, note=note) if note
                               else Msg.of("ai_pose.objects", "{count} objects ({device})", count=count, device=device)))


class YoloObbTool(_YoloTool):
    key = "ai_obb"
    label = "Oriented boxes (AI)"
    description = "Finds objects with an oriented-box network and returns oriented boxes (centre, size, angle) and their four corners — the right choice for parts that sit at an angle."
    task = "obb"
    icon = "RotateCw"
    params = _common_params("obb") + _detect_params()
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("count", "Count", "number"), Port("matches", "Oriented boxes (cx, cy, w, h, angle)", "matches"),
               Port("contours", "Corner contours", "contours"), Port("labels", "Class list", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.dl import yolo_runtime

        image = ctx.require_image()
        model = self._model(ctx)
        region, c, sub = self._crop(ctx, image, upright=True)
        result, device, note = self._predict(ctx, model, sub, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_det=ctx.integer("max_count", 100))
        names, allowed = yolo_runtime.names_of(model), self._allowed(ctx)
        obb = getattr(result, "obb", None) if result is not None else None
        matches: list[dict[str, Any]] = []
        polys: list[list[list[float]]] = []
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if obb is not None and len(obb):
            corners = obb.xyxyxyxy.cpu().numpy()  # (n, 4, 2)
            xywhr = obb.xywhr.cpu().numpy()  # (n, 5) 角度為弧度
            conf = obb.conf.cpu().numpy()
            cls = obb.cls.cpu().numpy().astype(int)
            base_angle = _region_angle(region)
            for i in range(len(corners)):
                name = names.get(int(cls[i]), str(int(cls[i])))
                if allowed and name not in allowed:
                    continue
                quad = [list(c.to_full(float(x), float(y))) for x, y in corners[i]]
                cx, cy = c.to_full(float(xywhr[i][0]), float(xywhr[i][1]))
                matches.append({"label": name, "index": int(cls[i]), "score": round(float(conf[i]), 4), "cx": round(cx, 1), "cy": round(cy, 1),
                                "w": round(float(xywhr[i][2]), 1), "h": round(float(xywhr[i][3]), 1), "angle": round(float(np.degrees(xywhr[i][4])) + base_angle, 2),
                                "points": [[round(x, 1), round(y, 1)] for x, y in quad]})
                polys.append(quad)
                overlays.append({"kind": "polygon", "points": [[round(x, 1), round(y, 1)] for x, y in quad], "color": GREEN, "width": 2, "label": f"{name} {float(conf[i]):.2f}"})
            order = sorted(range(len(matches)), key=lambda k: -matches[k]["score"])
            matches, polys = [matches[k] for k in order], [polys[k] for k in order]
        count = len(matches)
        branch, status = self._verdict(ctx, count)
        return Result(outputs={"count": count, "matches": matches, "contours": [np.array(p, dtype=np.float32).reshape(-1, 1, 2) for p in polys], "labels": [m["label"] for m in matches]},
                      overlays=overlays, branch=branch, status=status, message=(Msg.of("ai_obb.objects_note", "{count} objects ({device}, {note})", count=count, device=device, note=note) if note
                               else Msg.of("ai_obb.objects", "{count} objects ({device})", count=count, device=device)))


TOOLS = [YoloDetectTool(), YoloSegmentTool(), YoloClassifyTool(), YoloPoseTool(), YoloObbTool()]
