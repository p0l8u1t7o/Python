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
from apps.vision.tools.roi import crop, region_overlay

ROI_SHAPES = ["rect", "rotated_rect"]
GREEN = "#22c55e"
#: COCO 17 關鍵點的骨架連線（姿態模型輸出 17 點時畫）。
COCO_SKELETON = [(15, 13), (13, 11), (16, 14), (14, 12), (11, 12), (5, 11), (6, 12), (5, 6), (5, 7), (6, 8), (7, 9), (8, 10), (1, 2), (0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 6)]
IMGSZ_OPTIONS = [{"value": 320, "label": "320"}, {"value": 480, "label": "480"}, {"value": 640, "label": "640 (recommended)"}, {"value": 960, "label": "960"}, {"value": 1280, "label": "1280"}]
DEVICE_OPTIONS = [{"value": "auto", "label": "Automatic (use the GPU when there is one)"}, {"value": "cuda", "label": "GPU (CUDA)"}, {"value": "cpu", "label": "CPU"}]


def _common_params(task: str, default_weights: str, imgsz: int = 640) -> list[Param]:
    return [
        Param("model", "Model asset", kind="asset", accept="model", required=False, help_text="A model trained on the teaching page (.pt or .onnx) or one you uploaded; blank falls back to the base model below."),
        Param("model_name", "Base model", kind="text", default=default_weights, help_text="An official model name (downloaded on first use) or a local .pt path; used only when no model asset is chosen."),
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
                    raise ToolError(f"Model asset {asset_id} not found")
                model = yolo_runtime.load(path, task=self.task)
            else:
                name = str(ctx.param("model_name") or "").strip()
                if not name:
                    raise ToolError("No model is set: choose a model asset or name a base model")
                model = yolo_runtime.load(name, task=self.task)
        except yolo_runtime.ModelUnavailable as exc:
            raise ToolError(str(exc)) from None
        task = yolo_runtime.task_of(model)
        if task and task not in (self.accepted_tasks or (self.task,)):
            raise ToolError(f"The model does {task} but this tool needs {self.task}; use the matching YOLO tool")
        return model

    def _predict(self, ctx: ToolContext, model: Any, image: np.ndarray, **extra: Any):
        from apps.vision.dl import yolo_runtime

        device, note = yolo_runtime.pick_device(ctx.param("device", "auto"))
        kw: dict[str, Any] = {"imgsz": ctx.integer("imgsz", 640), "device": device, **extra}
        if ctx.flag("half") and device.startswith("cuda"):
            kw["half"] = True  # 只在要求時傳（ultralytics 8.4 對 half=False 也會印棄用警告）
        try:
            result = yolo_runtime.predict(model, image, **kw)
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
            raise ToolError("The region falls outside the image")
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


class YoloDetectTool(_YoloTool):
    key = "yolo_detect"
    label = "YOLO object detection"
    description = "Finds objects with an ultralytics YOLO model — an official base model or a .pt trained on the teaching page — returning boxes, classes and scores. A GPU is used automatically when present."
    task = "detect"
    accepted_tasks = ("detect", "segment", "pose", "obb")
    params = _common_params("detect", "yolo11n.pt") + _detect_params()
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
                      branch=branch, status=status, message=f"{count} objects ({device}{', ' + note if note else ''})")


class YoloSegmentTool(_YoloTool):
    key = "yolo_segment"
    label = "YOLO instance segmentation"
    description = "Uses an ultralytics YOLO-seg model to find each object's contour, class and area, and outputs a union mask and contours for later measurement."
    task = "segment"
    icon = "Brain"
    params = _common_params("segment", "yolo11n-seg.pt") + _detect_params() + [Param("min_area", "Min area", kind="number", default=0, minimum=0, unit="px²", group="Verdict", help_text="Instances smaller than this are skipped.")]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"), Port("count", "Count", "number"), Port("matches", "Instances", "matches"),
               Port("mask", "Union mask", "image"), Port("contours", "Contour", "contours"), Port("labels", "Class list", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.dl import yolo_runtime

        image = ctx.require_image()
        model = self._model(ctx)
        region, c, sub = self._crop(ctx, image, upright=False)
        result, device, note = self._predict(ctx, model, sub, conf=ctx.number("conf", 0.25), iou=ctx.number("iou", 0.45), max_det=ctx.integer("max_count", 100))
        names, allowed = yolo_runtime.names_of(model), self._allowed(ctx)
        full_h, full_w = image.shape[:2]
        sh, sw = sub.shape[:2]
        union = np.zeros((full_h, full_w), dtype=np.uint8)
        matches: list[dict[str, Any]] = []
        contour_list: list[list[list[int]]] = []
        overlays: list[dict[str, Any]] = []
        min_area = ctx.integer("min_area", 0)
        masks = getattr(result, "masks", None) if result is not None else None
        if masks is not None and result.boxes is not None and len(result.boxes):
            data = masks.data.cpu().numpy()  # (n, mh, mw)，可能與 sub 尺寸不同
            conf = result.boxes.conf.cpu().numpy()
            cls = result.boxes.cls.cpu().numpy().astype(int)
            xyxy = result.boxes.xyxy.cpu().numpy()
            for i in range(len(data)):
                name = names.get(int(cls[i]), str(int(cls[i])))
                if allowed and name not in allowed:
                    continue
                m = data[i]
                if m.shape != (sh, sw):
                    m = cv2.resize(m.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST)
                m = (m > 0).astype(np.uint8)
                area = int(m.sum())
                if not area or area < min_area:
                    continue
                union[c.y0 : c.y0 + sh, c.x0 : c.x0 + sw] |= m * 255
                contours, _ = cv2.findContours(m * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                polys = [(cnt.reshape(-1, 2) + [c.x0, c.y0]).tolist() for cnt in contours if len(cnt) >= 3]
                contour_list += polys
                x0, y0, x1, y1 = (float(v) for v in xyxy[i])
                matches.append({"label": name, "index": int(cls[i]), "score": round(float(conf[i]), 4), "x": round(x0 + c.x0, 1), "y": round(y0 + c.y0, 1),
                                "w": round(x1 - x0, 1), "h": round(y1 - y0, 1), "cx": round((x0 + x1) / 2 + c.x0, 1), "cy": round((y0 + y1) / 2 + c.y0, 1), "area": area})
                if polys:
                    overlays.append({"kind": "contours", "contours": polys, "color": GREEN, "width": 1, "label": f"{name} {float(conf[i]):.2f}"})
        if region:
            overlays.append(region_overlay(region, label="roi"))
        count = len(matches)
        branch, status = self._verdict(ctx, count)
        return Result(outputs={"count": count, "matches": matches, "mask": union, "contours": [np.array(p).reshape(-1, 1, 2) for p in contour_list], "labels": [m["label"] for m in matches]},
                      overlays=overlays, branch=branch, status=status, message=f"{count} instances ({device}{', ' + note if note else ''})")


class YoloClassifyTool(_YoloTool):
    key = "yolo_classify"
    label = "YOLO classification"
    description = "Classifies the region with an ultralytics YOLO-cls model; it passes when the top class scores above the threshold and is in the passing list."
    task = "classify"
    icon = "Brain"
    params = _common_params("classify", "yolo11n-cls.pt", imgsz=224) + [
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
            raise ToolError("The model has no classification output (is it a classifier?)")
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
                      branch="pass" if ok else "fail", status="ok" if ok else "ng", message=f"{best['label']} {best['score']:.2f}（{device}{'，' + note if note else ''}）")


class YoloPoseTool(_YoloTool):
    key = "yolo_pose"
    label = "YOLO pose (keypoints)"
    description = "Finds objects with an ultralytics YOLO-pose model and returns each object's keypoint coordinates and confidence (the 17 COCO body points or your own), for position and pose checks."
    task = "pose"
    icon = "PersonStanding"
    params = _common_params("pose", "yolo11n-pose.pt") + _detect_params() + [
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
                      branch=branch, status=status, message=f"{count} objects ({device}{', ' + note if note else ''})")


class YoloObbTool(_YoloTool):
    key = "yolo_obb"
    label = "YOLO oriented boxes (OBB)"
    description = "Finds objects with an ultralytics YOLO-obb model and returns oriented boxes (centre, size, angle) and their four corners — the right choice for parts that sit at an angle."
    task = "obb"
    icon = "RotateCw"
    params = _common_params("obb", "yolo11n-obb.pt") + _detect_params()
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
                      overlays=overlays, branch=branch, status=status, message=f"{count} objects ({device}{', ' + note if note else ''})")


TOOLS = [YoloDetectTool(), YoloSegmentTool(), YoloClassifyTool(), YoloPoseTool(), YoloObbTool()]
