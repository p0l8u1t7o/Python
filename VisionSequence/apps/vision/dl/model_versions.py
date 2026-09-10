"""模型版本、固定保留集與候選評估；資料庫操作只在 DL 工作與請求執行緒進行。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

import cv2
import numpy as np
from django.conf import settings
from django.db import transaction
from django.db.models import Max

from apps.core.errors import Conflict, NotFound
from apps.vision.dl.base import SampleRef, TrainError, get_trainer
from apps.vision.models import Asset, DlDatasetVersion, DlModelVersion, DlProject, Flow


def holdout_ids(project):
    """已凍結的保留樣本永遠不可重新加入訓練。"""
    return {sid for ids in project.model_versions.values_list("holdout_samples", flat=True) for sid in ids}


def prepare(project, params):
    """第一次建模前分層抽樣；已有 test 或凍結紀錄時不再抽換。"""
    with transaction.atomic():
        project = DlProject.objects.select_for_update().get(pk=project.pk)
        fixed = holdout_ids(project)
        fingerprints = set()
        # 尚未儲存的候選也已凍結，避免重新分割造成洩漏。
        for stats in project.versions.values_list("stats", flat=True):
            fixed.update(stats.get("holdout_samples", []))
            fingerprints.update(stats.get("holdout_sha256", []))
        if fixed:
            project.samples.filter(pk__in=fixed).update(split="test")
        if fingerprints:
            project.samples.filter(sha256__in=fingerprints).update(split="test")
        rows = list(project.samples.all())
        if not fixed and not any(r.split == "test" for r in rows):
            ratio = params.get("holdout_ratio", 0.2)
            if not isinstance(ratio, (int, float)) or not 0 < ratio <= 0.5:
                raise TrainError("Holdout ratio must be greater than 0 and at most 0.5")
            groups = {}
            for r in rows:
                if project.trainer_kind != "anomaly" and get_trainer(project.trainer_kind).label_mode == "classes" and r.label not in project.classes:
                    continue
                key = r.label if get_trainer(project.trainer_kind).label_mode == "classes" else "shapes"
                groups.setdefault(key, []).append(r)
            minimum = get_trainer(project.trainer_kind).min_per_class
            for group in groups.values():
                count = min(len(group) - minimum, max(1, round(len(group) * ratio)))
                for r in sorted(group, key=lambda x: str(x.id))[:max(0, count)]:
                    r.split = "test"
                    r.save(update_fields=["split"])
        return rows


def frozen_holdout_ids(project):
    ids = holdout_ids(project)
    for stats in project.versions.values_list("stats", flat=True):
        ids.update(stats.get("holdout_samples", []))
    return ids


def freeze(project, rows):
    """在訓練前保存原始 PNG、標記與分割，避免訓練期間編輯改寫版本證據。"""
    aid = uuid.uuid4()
    path = Path(settings.VISION["ASSET_DIR"]) / f"{aid.hex}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"classes": list(project.classes), "items": []}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            name = f"images/{row.id}.png"
            try:
                archive.write(row.path, name)
            except OSError as exc:
                raise TrainError(f"Sample {row.id} could not be read") from exc
            manifest["items"].append({"id": str(row.id), "file": name, "label": row.label,
                                      "shapes": deepcopy(row.shapes), "split": row.split,
                                      "labeled_by": row.labeled_by, "sha256": row.sha256})
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    stats = {"total": len(rows), "classes": list(project.classes),
             "split": dict(Counter(r.split for r in rows)),
             "holdout_samples": [str(r.id) for r in rows if r.split == "test"]}
    stats["holdout_sha256"] = [r.sha256 for r in rows if r.split == "test" and r.sha256]
    asset = Asset.objects.create(id=aid, name=f"{project.name} dataset", kind="dataset", path=str(path), size=path.stat().st_size)
    return DlDatasetVersion.objects.create(project=project, name=f"Model dataset {aid.hex[:8]}", asset_id=asset.id.hex, stats=stats)


def frozen_samples(dataset, folder):
    """只取自己寫入的 manifest 檔案；解壓路徑不接受外部檔名。"""
    asset = Asset.objects.get(pk=dataset.asset_id)
    out = []
    with zipfile.ZipFile(asset.path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for item in manifest["items"]:
            sid = str(uuid.UUID(item["id"]))
            path = Path(folder) / f"{sid}.png"
            path.write_bytes(archive.read(f"images/{sid}.png"))
            out.append(SampleRef(sid, item["label"], str(path), item["shapes"], item["split"]))
    return out, manifest["classes"]


def frozen_item(version_id, sample_id):
    """歷史影像與真值從版本 ZIP 取回，不依賴目前可刪除或重標的樣本。"""
    version = DlModelVersion.objects.filter(pk=version_id).select_related("dataset_version").first()
    if version is None or not version.dataset_version_id:
        raise NotFound("Model dataset not found", code="model_dataset_missing")
    asset = Asset.objects.filter(pk=version.dataset_version.asset_id).first()
    try:
        with zipfile.ZipFile(asset.path if asset else "") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            item = next((i for i in manifest["items"] if i["id"] == str(sample_id)), None)
            if item is None:
                raise NotFound("Sample is not in this model dataset", code="model_sample_missing")
            image = cv2.imdecode(np.frombuffer(archive.read(item["file"]), np.uint8), cv2.IMREAD_COLOR)
    except (OSError, zipfile.BadZipFile, KeyError):
        raise NotFound("Model dataset could not be read", code="model_dataset_missing") from None
    return image, item


def registration_asset(settings, name):
    """註冊圖片另存 ZIP，固定影像孤兒清理不會破壞可回復版本。"""
    from apps.vision import fixed_images

    aid = uuid.uuid4()
    path = Path(settings_root()) / f"{aid.hex}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        seen = set()
        for key in ("registrations", "negatives"):
            for descriptor in settings.get(key, []):
                sid = descriptor["id"]
                if sid in seen:
                    continue
                image = fixed_images.load(sid)
                if image is None:
                    raise TrainError(f"Registered picture {sid} is missing")
                archive.write(fixed_images.path_of(sid), f"{sid}.png")
                seen.add(sid)
    return Asset.objects.create(id=aid, name=name, kind="dataset", path=str(path), size=path.stat().st_size)


def settings_root():
    path = Path(settings.VISION["ASSET_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def restore_registration(version):
    from apps.vision import fixed_images

    asset = Asset.objects.filter(pk=version.asset_id).first()
    if asset is None:
        raise NotFound("Registration dataset is missing", code="model_dataset_missing")
    with zipfile.ZipFile(asset.path) as archive:
        for key in ("registrations", "negatives"):
            for descriptor in version.params["settings"].get(key, []):
                sid = descriptor["id"]
                # 只寫入當初驗證過的影像 id；不讓 ZIP 的路徑控制目的地。
                data = archive.read(f"{sid}.png")
                if hashlib.sha256(data).hexdigest()[:fixed_images.ID_LEN] != sid:
                    raise TrainError("A registered picture failed its integrity check")
                Path(fixed_images.path_of(sid)).write_bytes(data)


def infer(tool_key, path, params, image):
    """使用平台工具入口評估，參數與實際部署共用。"""
    from apps.vision.tools import base

    tool = base.get(tool_key)
    ctx = base.ToolContext(run_id="model-validation", flow_id=0,
                           node={"id": "model", "type": tool_key, "params": {**params, "model": "candidate"}},
                           inputs={"image": image}, context={}, moment=0, log=lambda *a, **kw: None,
                           asset_path=lambda aid: path if aid == "candidate" else None,
                           grab=lambda sid: None, preview=True, depth=getattr(tool, "accepts", ("u8",)))
    return tool.execute(ctx)


def evaluate(tool_key, path, params, samples, classes):
    """只在模型完全建立後評估保留集；誤判存真值與預測，不參與調參。"""
    from apps.vision.dl.shapes import rasterize

    failures, scores, ious = [], [], []
    total = errors = 0
    for sample in samples:
        if sample.split != "test":
            continue
        image = sample.load()
        if image is None:
            raise TrainError(f"Holdout sample {sample.id} could not be read")
        result = infer(tool_key, path, params, image)
        out = result.outputs
        total += 1
        if "label" in out:
            if sample.label not in classes:
                raise TrainError(f"Label holdout sample {sample.id} before evaluating the model")
            truth, prediction = sample.label, str(out["label"])
            correct = truth == prediction
        elif tool_key == "dl_anomaly":
            truth = sample.label not in ("", classes[0] if classes else "good")
            prediction = result.status == "ng"
            scores.append((float(out.get("score", 0)), truth))
            correct = truth == prediction
        else:
            truth = sample.shapes
            target = rasterize(truth, classes, *image.shape[:2])
            if "class_map" in out:
                predicted = np.asarray(out["class_map"])
                values = range(1, len(classes) + 1)
            elif "mask" in out:
                target = target > 0
                predicted = np.asarray(out["mask"]) > 0
                values = [1]
            else:
                prediction = out.get("matches", out.get("detections", []))
                shapes = [{"kind": "bbox", "label": m.get("label", ""),
                           "points": [[m.get("x", 0) / image.shape[1], m.get("y", 0) / image.shape[0]],
                                      [(m.get("x", 0) + m.get("w", 0)) / image.shape[1],
                                       (m.get("y", 0) + m.get("h", 0)) / image.shape[0]]]} for m in prediction]
                predicted = rasterize(shapes, classes, *image.shape[:2])
                values = range(1, len(classes) + 1)
            overlaps = []
            for value in values:
                a, b = target == value, predicted == value
                union = np.count_nonzero(a | b)
                if union:
                    overlaps.append(float(np.count_nonzero(a & b) / union))
            overlap = float(np.mean(overlaps)) if overlaps else 1.0
            ious.append(overlap)
            prediction = {"iou": overlap, "regions": []}
            for value in values:
                mask = (predicted == value).astype(np.uint8)
                contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours[:200]:
                    x, y, w, h = cv2.boundingRect(contour)
                    prediction["regions"].append({"label": classes[value - 1] if value <= len(classes) else "foreground",
                                                   "x": x, "y": y, "w": w, "h": h})
            correct = overlap >= 0.5
        if not correct:
            errors += 1
            if len(failures) < 200:
                failures.append({"sample_id": sample.id, "prediction": prediction, "truth": truth})
    metrics = {"holdout_count": total, "accuracy": (total - errors) / total if total else None, "error_count": errors}
    if total == 0:
        metrics["warning"] = "No holdout set. Accuracy was not measured."
    if ious:
        metrics["iou"] = float(np.mean(ious))
    if scores:
        pos = [s for s, label in scores if label]
        neg = [s for s, label in scores if not label]
        metrics["auroc"] = float(np.mean([float(a > b) + 0.5 * float(a == b) for a in pos for b in neg])) if pos and neg else None
    return metrics, failures


def record(project, asset_id, dataset, params, metrics, failures, *, created_by="", note=""):
    with transaction.atomic():
        DlProject.objects.select_for_update().get(pk=project.pk)
        versions = project.model_versions.all()
        parent = versions.first()
        return DlModelVersion.objects.create(project=project, number=(versions.aggregate(n=Max("number"))["n"] or 0) + 1,
                                             asset_id=asset_id, dataset_version=dataset, params=deepcopy(params),
                                             tune_samples=dataset.stats.get("tune_samples", []),
                                             holdout_samples=dataset.stats.get("holdout_samples", []), metrics=metrics,
                                             failures=failures[:200], parent=parent, created_by=created_by, note=note)


def same_asset(a, b):
    return str(a).replace("-", "") == str(b).replace("-", "")


def flows_using(asset_id):
    if not asset_id:
        return []
    return [{"flow_id": f.id, "name": f.name, "node_id": n["id"], "updated_at": f.updated_at.isoformat()}
            for f in Flow.objects.all() for n in (f.graph or {}).get("nodes", [])
            if same_asset((n.get("params") or {}).get("model", ""), asset_id)]


def output(version):
    return {"id": version.id, "number": version.number, "status": version.status, "asset_id": version.asset_id,
            "dataset_version": version.dataset_version_id, "params": version.params,
            "tune_samples": version.tune_samples, "holdout_samples": version.holdout_samples,
            "metrics": version.metrics, "failures": version.failures, "parent": version.parent.number if version.parent_id else None,
            "created_by": version.created_by, "created_at": version.created_at, "note": version.note,
            "flows": flows_using(version.asset_id), "flow_id": version.flow_id, "node_id": version.node_id}


def get(project, number):
    version = project.model_versions.filter(number=number).select_related("parent").first()
    if version is None:
        raise NotFound("Model version not found", code="model_version_not_found")
    return version


def activate(version, rollback=False):
    with transaction.atomic():
        if version.project_id:
            DlProject.objects.select_for_update().get(pk=version.project_id)
            scope = DlModelVersion.objects.filter(project_id=version.project_id)
        else:
            Flow.objects.select_for_update().get(pk=version.flow_id)
            scope = DlModelVersion.objects.filter(flow_id=version.flow_id, node_id=version.node_id)
        version = scope.get(pk=version.pk)
        if rollback:
            if version.status != "active" or not version.parent_id:
                raise Conflict("Only an active version with a parent can be rolled back", code="no_parent_version")
            target = scope.get(pk=version.parent_id)
        else:
            target = version
        if target.asset_id and not Asset.objects.filter(pk=target.asset_id).exists():
            raise NotFound("Model asset not found", code="model_asset_not_found")
        old_assets = set(scope.exclude(pk=target.pk).exclude(asset_id="").values_list("asset_id", flat=True))
        scope.filter(status="active").exclude(pk=target.pk).update(status="retired")
        target.status = "active"
        target.save(update_fields=["status"])
        return {"version": output(target), "flows_using_previous": [f for aid in old_assets for f in flows_using(aid)]}


def compare(a, b):
    left = {f["sample_id"]: f for f in a.failures}
    right = {f["sample_id"]: f for f in b.failures}
    return {"a": output(a), "b": output(b), "fixed": [left[k] for k in sorted(left.keys() - right.keys())],
            "new": [right[k] for k in sorted(right.keys() - left.keys())],
            "truncated": a.metrics.get("error_count", 0) > len(left) or b.metrics.get("error_count", 0) > len(right)}


def retrieval_edit(project, asset, data, created_by=""):
    """庫內容不變時不建版本；每次改動都另存資產，舊流程仍用舊資產。"""
    if hashlib.sha256(Path(asset.path).read_bytes()).digest() == hashlib.sha256(data).digest():
        return asset
    import tempfile

    rows = prepare(project, project.params)
    dataset = freeze(project, rows)
    aid = uuid.uuid4()
    path = Path(settings.VISION["ASSET_DIR"]) / f"{aid.hex}.npz"
    path.write_bytes(data)
    params = dict((asset.meta or {}).get("tool_params", {}))
    with tempfile.TemporaryDirectory(prefix="vs-model-eval-") as folder:
        samples, classes = frozen_samples(dataset, folder)
        metrics, failures = evaluate("dl_retrieval", str(path), params, samples, classes)
    new = Asset.objects.create(id=aid, name=asset.name, kind="model", path=str(path), size=len(data),
                               meta={**asset.meta, "metrics": metrics})
    from apps.vision.dl import retrieval

    model = retrieval.loads(data)
    sources = set(model.get("source_ids", []))
    dataset.stats["tune_samples"] = [str(r.id) for r in rows if r.split != "test" and (str(r.id) in sources or r.id.hex in sources)]
    dataset.save(update_fields=["stats"])
    record(project, aid.hex, dataset, project.params, metrics, failures, created_by=created_by)
    project.last_asset_id = aid.hex
    project.last_metrics = metrics
    project.save(update_fields=["last_asset_id", "last_metrics", "updated_at"])
    return new
