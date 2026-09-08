"""快速註冊流程層：自動框選、套用保守預設並啟動既有教導工作。"""

from __future__ import annotations

from typing import Any

from apps.core.errors import ValidationError
from apps.vision.dl import devices, jobs, yolo_runtime
from apps.vision.dl.base import SampleRef, TrainError, get_trainer
from apps.vision.dl.shapes import shapes_to_yolo, yolo_to_shapes

# 少於 2 張時無法穩定切出 train/val；快速註冊寧可早點阻擋，而不是啟動後才失敗。
QUICK_MIN_SAMPLES = 2
# 全圖提案只取少量候選，避免樣本少時把背景雜訊也拿去教導，現場確認成本較低。
QUICK_MAX_MASKS = 8
# 每次最多處理 200 張，和既有全圖自動標記端點相同，避免單次請求長時間占用。
QUICK_MAX_SAMPLES = 200
# 分數代表「自動產生、待確認」；不拿它當準確度，只讓介面能辨識來源。
QUICK_LABEL_SCORE = 0.5
# 快速註冊面向少量現場樣本：小底模、短排程、低批量、關閉會大幅改變影像的增強。
# 這組設定優先讓使用者很快得到第一版結果；要追求精度可查看回傳 params 後走一般訓練重跑。
QUICK_PRESET: dict[str, Any] = {
    "model": "n",
    "epochs": 20,
    "batch": 4,
    "patience": 8,
    "lr0": 0.001,
    "val_ratio": 0.2,
    "workers": 0,
    "suggest_conf": 0.4,
    "degrees": 0,
    "fliplr": 0.0,
    "mosaic": 0.0,
}


def proposals_to_boxes(proposals: list[dict[str, Any]], classes: list[str]) -> list[dict[str, Any]]:
    """沿用既有 detect 匯出分支，將 polygon 提案轉為外接 bbox。"""
    if not classes:
        return []
    labelled = [{**shape, "label": str(shape.get("label") or classes[0])} for shape in proposals]
    boxes = [shape for shape in yolo_to_shapes(shapes_to_yolo(labelled, classes, task="detect"), classes) if shape.get("kind") == "bbox"]
    for shape in boxes:
        shape["points"] = [[round(float(x), 6), round(float(y), 6)] for x, y in shape.get("points", [])]
    return boxes


def quick_params(samples) -> dict[str, Any]:
    """依樣本影像大小補上影像尺寸；其餘值由 QUICK_PRESET 固定。"""
    longest = max((max(int(s.width or 0), int(s.height or 0)) for s in samples), default=0)
    imgsz = 320 if longest <= 480 else 480 if longest <= 960 else 640
    return {**QUICK_PRESET, "imgsz": imgsz}


def quick_register(project, *, device: str = "", asset_name: str = "") -> dict[str, Any]:
    """執行快速註冊三步驟，並回傳工作 id、標記數、略過數與實際參數。"""
    trainer = get_trainer(project.trainer_kind)
    if trainer.kind != "ai_detect":
        raise ValidationError("Quick register is only available for box teaching projects", code="quick_register_not_supported")
    classes = [str(c) for c in (project.classes or []) if str(c)]
    if not classes:
        raise ValidationError("Add at least one class before quick register", code="no_classes")
    rows = list(project.samples.all())
    if len(rows) < QUICK_MIN_SAMPLES:
        raise ValidationError(f"Quick register needs at least {QUICK_MIN_SAMPLES} samples", code="not_enough_samples",
                              details={"min_samples": QUICK_MIN_SAMPLES, "samples": len(rows)})

    from apps.vision.dl import sam

    pending = [sample for sample in rows if not sample.shapes]
    skipped = max(0, len(pending) - QUICK_MAX_SAMPLES)
    labeled = 0
    sam_device = yolo_runtime.pick_device("auto")[0]
    try:
        for sample in pending[:QUICK_MAX_SAMPLES]:
            image = SampleRef(id=str(sample.id), label=sample.label, path=sample.path).load()
            if image is None:
                skipped += 1
                continue
            boxes = proposals_to_boxes(sam.suggest_everything(image, model_name="", device=sam_device, max_masks=QUICK_MAX_MASKS), classes)
            if not boxes:
                skipped += 1
                continue
            sample.shapes = boxes
            sample.labeled_by = "auto"
            sample.score = QUICK_LABEL_SCORE
            sample.save(update_fields=["shapes", "labeled_by", "score"])
            labeled += 1
    except TrainError as exc:
        raise ValidationError(str(exc), code="quick_register_label_failed") from None

    labelled_count = sum(1 for sample in project.samples.all() if sample.shapes)
    if labelled_count < QUICK_MIN_SAMPLES:
        raise ValidationError(f"Quick register needs at least {QUICK_MIN_SAMPLES} boxed samples", code="not_enough_labeled_samples",
                              details={"min_samples": QUICK_MIN_SAMPLES, "labeled_samples": labelled_count})
    params = quick_params(rows)
    job = jobs.start(project, params, device or devices.train_device(), asset_name)
    return {"job_id": job["id"], "labeled": labeled, "skipped": skipped, "params": params}
