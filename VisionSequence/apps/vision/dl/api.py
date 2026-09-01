"""深度學習教導 API（掛在 /api/vision/dl/*）。

權限：讀取／標記／訓練 = 任何登入者（整合方金鑰亦可）；訓練另過 can_execute()（鎖定時 423）；
裝置設定 PATCH = 管理員。樣本影像檔比照資產檔端點（auth=None + authenticate）。
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Router, UploadedFile

from apps.accounts.security import authenticate, principal, require_admin
from apps.core.errors import NotFound, ValidationError
from apps.vision.dl import base as dl_base, devices, jobs
from apps.vision.dl.base import SampleRef, TrainError
from apps.vision.images import encode_image
from apps.vision.models import DlProject, DlSample
from apps.vision.sources import grab_by_id

router = Router(tags=["dl"])


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("JSON 格式錯誤", code="bad_json") from None
    if not isinstance(data, dict):
        raise ValidationError("需要 JSON 物件", code="bad_json")
    return data


def _project(project_id: int) -> DlProject:
    project = DlProject.objects.filter(pk=project_id).first()
    if project is None:
        raise NotFound("教導專案不存在", code="dl_project_not_found")
    return project


def _sample_dir(project: DlProject) -> str:
    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", str(project.id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _counts(project: DlProject) -> dict[str, Any]:
    rows = project.samples.values_list("label", flat=True)
    labels = list(rows)
    per_class = {c: labels.count(c) for c in (project.classes or [])}
    return {"total": len(labels), "unlabeled": labels.count(""), "per_class": per_class}


def _project_out(project: DlProject, *, counts: bool = True) -> dict[str, Any]:
    out = {
        "id": project.id, "name": project.name, "description": project.description,
        "trainer_kind": project.trainer_kind, "classes": list(project.classes or []),
        "params": dict(project.params or {}), "last_asset_id": project.last_asset_id,
        "last_metrics": dict(project.last_metrics or {}),
        "created_at": project.created_at, "updated_at": project.updated_at,
    }
    if counts:
        out["counts"] = _counts(project)
    return out


def _sample_out(sample: DlSample) -> dict[str, Any]:
    return {
        "id": str(sample.id), "label": sample.label, "labeled_by": sample.labeled_by,
        "score": sample.score, "width": sample.width, "height": sample.height, "created_at": sample.created_at,
    }


def _save_sample(project: DlProject, image: np.ndarray, label: str = "") -> DlSample:
    sample_id = uuid.uuid4()
    path = os.path.join(_sample_dir(project), f"{sample_id.hex}.png")
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValidationError("影像編碼失敗", code="encode_failed")
    buf.tofile(path)
    return DlSample.objects.create(
        id=sample_id, project=project, label=label, labeled_by="human" if label else "",
        path=path, width=int(image.shape[1]), height=int(image.shape[0]),
    )


# ---------------------------------------------------------------------------
# 目錄與裝置
# ---------------------------------------------------------------------------
@router.get("/dl/trainers")
def list_trainers(request: HttpRequest):
    return {"items": dl_base.catalogue()}


@router.get("/dl/devices")
def device_info(request: HttpRequest):
    return devices.info()


@router.patch("/dl/settings")
def patch_settings(request: HttpRequest):
    require_admin(request)
    body = _body(request)
    providers = body.get("providers")
    if providers is not None and not (isinstance(providers, list) and all(isinstance(p, str) for p in providers)):
        raise ValidationError("providers 必須是字串清單", code="bad_providers")
    device = body.get("train_device")
    return devices.save_settings(providers, str(device) if device is not None else None)


# ---------------------------------------------------------------------------
# 專案
# ---------------------------------------------------------------------------
@router.get("/dl/projects")
def list_projects(request: HttpRequest):
    return {"items": [_project_out(p) for p in DlProject.objects.all()]}


@router.post("/dl/projects", response={201: dict})
def create_project(request: HttpRequest):
    body = _body(request)
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValidationError("需要名稱", code="bad_name")
    kind = str(body.get("trainer_kind") or "")
    dl_base.get_trainer(kind)  # 驗證存在
    classes = [str(c).strip() for c in (body.get("classes") or []) if str(c).strip()]
    if DlProject.objects.filter(name=name).exists():
        raise ValidationError(f"名稱「{name}」已存在", code="duplicate_name")
    project = DlProject.objects.create(name=name, description=str(body.get("description") or ""), trainer_kind=kind, classes=classes, params=dict(body.get("params") or {}))
    return 201, _project_out(project)


@router.get("/dl/projects/{project_id}")
def get_project(request: HttpRequest, project_id: int):
    return _project_out(_project(project_id))


@router.patch("/dl/projects/{project_id}")
def patch_project(request: HttpRequest, project_id: int):
    project = _project(project_id)
    body = _body(request)
    if "name" in body:
        name = str(body["name"] or "").strip()
        if not name:
            raise ValidationError("需要名稱", code="bad_name")
        if DlProject.objects.exclude(pk=project.id).filter(name=name).exists():
            raise ValidationError(f"名稱「{name}」已存在", code="duplicate_name")
        project.name = name
    if "description" in body:
        project.description = str(body["description"] or "")
    if "classes" in body:
        classes = [str(c).strip() for c in (body["classes"] or []) if str(c).strip()]
        removed = set(project.classes or []) - set(classes)
        project.classes = classes
        if removed:  # 被移除類別的樣本改回未標記
            project.samples.filter(label__in=list(removed)).update(label="", labeled_by="", score=0)
    if "params" in body and isinstance(body["params"], dict):
        project.params = body["params"]
    project.save()
    return _project_out(project)


@router.delete("/dl/projects/{project_id}", response={204: None})
def delete_project(request: HttpRequest, project_id: int):
    project = _project(project_id)
    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", str(project.id))
    project.delete()
    shutil.rmtree(folder, ignore_errors=True)
    return 204, None


# ---------------------------------------------------------------------------
# 樣本：上傳、從來源收集、標記
# ---------------------------------------------------------------------------
@router.get("/dl/projects/{project_id}/samples")
def list_samples(request: HttpRequest, project_id: int, label: str = "__all__"):
    project = _project(project_id)
    qs = project.samples.all()
    if label != "__all__":
        qs = qs.filter(label=label)
    return {"items": [_sample_out(s) for s in qs]}


@router.post("/dl/projects/{project_id}/samples", response={201: dict})
def upload_samples(request: HttpRequest, project_id: int, files: list[UploadedFile] = File(...), label: str = Form("")):
    project = _project(project_id)
    if label and label not in (project.classes or []):
        raise ValidationError(f"'{label}' 不在類別清單內", code="bad_label")
    created, skipped = [], 0
    for file in files:
        image = cv2.imdecode(np.frombuffer(file.read(), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            skipped += 1
            continue
        created.append(_sample_out(_save_sample(project, image, label)))
    return 201, {"items": created, "skipped": skipped}


@router.post("/dl/projects/{project_id}/samples/from-source", response={201: dict})
def samples_from_source(request: HttpRequest, project_id: int):
    """從影像來源連抓 N 張進樣本集（現場快速收集）。"""
    project = _project(project_id)
    body = _body(request)
    source_id = body.get("source_id")
    count = max(1, min(50, int(body.get("count") or 1)))
    label = str(body.get("label") or "")
    if label and label not in (project.classes or []):
        raise ValidationError(f"'{label}' 不在類別清單內", code="bad_label")
    created = []
    for _ in range(count):
        image = grab_by_id(source_id)
        if image is None:
            break
        created.append(_sample_out(_save_sample(project, image, label)))
    if not created:
        raise ValidationError("來源沒有取到任何影像", code="grab_failed")
    return 201, {"items": created}


@router.get("/dl/samples/{sample_id}/file", auth=None)
def sample_file(request: HttpRequest, sample_id: uuid.UUID, max: int = 0):
    if authenticate(request) is None:
        return HttpResponse(status=401)
    sample = DlSample.objects.filter(pk=sample_id).first()
    if sample is None or not os.path.isfile(sample.path):
        raise NotFound("樣本不存在", code="dl_sample_not_found")
    image = cv2.imdecode(np.fromfile(sample.path, dtype=np.uint8), cv2.IMREAD_COLOR)
    return HttpResponse(encode_image(image, max_side=max or None, fmt="jpg"), content_type="image/jpeg")


@router.patch("/dl/samples/{sample_id}")
def patch_sample(request: HttpRequest, sample_id: uuid.UUID):
    sample = DlSample.objects.filter(pk=sample_id).select_related("project").first()
    if sample is None:
        raise NotFound("樣本不存在", code="dl_sample_not_found")
    body = _body(request)
    if "label" in body:
        label = str(body["label"] or "")
        if label and label not in (sample.project.classes or []):
            raise ValidationError(f"'{label}' 不在類別清單內", code="bad_label")
        sample.label = label
        sample.labeled_by = "human" if label else ""
        sample.score = 0
        sample.save(update_fields=["label", "labeled_by", "score"])
    return _sample_out(sample)


@router.delete("/dl/samples/{sample_id}", response={204: None})
def delete_sample(request: HttpRequest, sample_id: uuid.UUID):
    sample = DlSample.objects.filter(pk=sample_id).first()
    if sample is None:
        raise NotFound("樣本不存在", code="dl_sample_not_found")
    try:
        os.remove(sample.path)
    except OSError:
        pass
    sample.delete()
    return 204, None


@router.post("/dl/projects/{project_id}/labels")
def bulk_label(request: HttpRequest, project_id: int):
    """批次標記：{"items": [{"id", "label", "by"?}]}；接受自動標記建議時 by="auto"。"""
    project = _project(project_id)
    body = _body(request)
    items = body.get("items")
    if not isinstance(items, list):
        raise ValidationError("需要 items 清單", code="bad_items")
    classes = set(project.classes or [])
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        if label and label not in classes:
            continue
        by = "auto" if str(item.get("by") or "") == "auto" else "human"
        rows = project.samples.filter(pk=item.get("id"))
        updated += rows.update(label=label, labeled_by=by if label else "", score=float(item.get("score") or 0))
    return {"updated": updated, "counts": _counts(project)}


# ---------------------------------------------------------------------------
# 自動標記與訓練
# ---------------------------------------------------------------------------
@router.post("/dl/projects/{project_id}/auto-label")
def auto_label(request: HttpRequest, project_id: int):
    """回傳未標記樣本的建議（不落地；前端確認後用 /labels 批次寫入）。"""
    project = _project(project_id)
    trainer = dl_base.get_trainer(project.trainer_kind)
    rows = list(project.samples.all())
    labeled = [SampleRef(id=str(r.id), label=r.label, path=r.path) for r in rows if r.label and r.labeled_by == "human"]
    unlabeled = [SampleRef(id=str(r.id), label="", path=r.path) for r in rows if not r.label or r.labeled_by == "auto"]
    params = {**dict(project.params or {}), **(_body(request).get("params") or {})}
    try:
        suggestions = trainer.suggest(labeled, unlabeled, list(project.classes or []), params)
    except TrainError as exc:
        raise ValidationError(str(exc), code="auto_label_failed") from None
    return {"items": [{"id": s.sample_id, "label": s.label, "score": s.score} for s in suggestions]}


@router.post("/dl/projects/{project_id}/train", response={202: dict})
def start_training(request: HttpRequest, project_id: int):
    principal(request).can_execute()
    project = _project(project_id)
    body = _body(request)
    params = {**dict(project.params or {}), **(body.get("params") or {})}
    if isinstance(body.get("params"), dict):  # 記住這次的超參數
        project.params = params
        project.save(update_fields=["params", "updated_at"])
    device = str(body.get("device") or devices.train_device())
    return 202, jobs.start(project, params, device, str(body.get("asset_name") or ""))


@router.get("/dl/train/status")
def train_status(request: HttpRequest):
    return {"job": jobs.status()}


@router.post("/dl/train/cancel")
def train_cancel(request: HttpRequest):
    return {"cancelled": jobs.cancel()}
