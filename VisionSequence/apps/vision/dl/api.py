"""深度學習教導 API（掛在 /api/vision/dl/*）。

權限：讀取／標記／訓練 = 任何登入者（整合方金鑰亦可）；訓練另過 can_execute()（鎖定時 423）；
裝置設定 PATCH = 管理員。樣本影像檔比照資產檔端點（auth=None + authenticate）。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from collections import Counter
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Router, UploadedFile

from apps.accounts.security import authenticate, principal, require_admin, require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision.dl import base as dl_base, devices, jobs, quick, retrieval, yolo_runtime
from apps.vision.dl.base import SampleRef, TrainError
from apps.vision.images import encode_image
from apps.vision.models import Asset, DlDatasetVersion, DlProject, DlSample
from apps.vision.sources import grab_by_id

router = Router(tags=["dl"])


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(data, dict):
        raise ValidationError("A JSON object is required", code="bad_json")
    return data


def _project(project_id: int) -> DlProject:
    project = DlProject.objects.filter(pk=project_id).first()
    if project is None:
        raise NotFound("Teaching project not found", code="dl_project_not_found")
    return project


def _sample_dir(project: DlProject) -> str:
    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", str(project.id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _label_mode(project: DlProject) -> str:
    try:
        return dl_base.get_trainer(project.trainer_kind).label_mode
    except Exception:  # noqa: BLE001 — 外掛 trainer 被移除時仍可瀏覽
        return "classes"


def _counts(project: DlProject) -> dict[str, Any]:
    classes = list(project.classes or [])
    if _label_mode(project) == "shapes":
        rows = list(project.samples.values_list("shapes", flat=True))
        per_class = {c: 0 for c in classes}
        labeled = 0
        for shp in rows:
            if shp:
                labeled += 1
                for shape in shp:
                    if shape.get("label") in per_class:
                        per_class[shape["label"]] += 1
        return {"total": len(rows), "unlabeled": len(rows) - labeled, "per_class": per_class}
    tally = Counter(project.samples.values_list("label", flat=True))
    total = sum(tally.values())
    return {"total": total, "unlabeled": tally.get("", 0), "per_class": {c: tally.get(c, 0) for c in classes}}


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
        "shapes": list(sample.shapes or []), "split": sample.split,
    }


def _retrieval_project(project: DlProject) -> None:
    if project.trainer_kind != "retrieval":
        raise ValidationError("This project does not use a reference library", code="bad_project_kind")


def _retrieval_asset(project: DlProject) -> Asset:
    _retrieval_project(project)
    if not project.last_asset_id:
        raise ValidationError("Build the reference library before editing it", code="missing_library")
    asset = Asset.objects.filter(pk=project.last_asset_id).first()
    if asset is None or asset.kind != "model":
        raise NotFound("Reference library asset not found", code="library_not_found")
    return asset


def _retrieval_metrics(model: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    labels = np.asarray(model.get("labels"), dtype=np.int32)
    classes = [str(c) for c in (model.get("classes") or [])]
    topk = int((model.get("meta") or {}).get("topk") or 3)
    counts = {name: int(np.count_nonzero(labels == i)) for i, name in enumerate(classes)}
    vectors = np.asarray(model.get("vectors"), dtype=np.float32)
    out = dict(previous or {})
    out.update(
        {
            "library_size": int(len(vectors)),
            "classes": int(len(classes)),
            "per_class": counts,
            "leave_one_out_accuracy": retrieval.leave_one_out(vectors, labels, classes, topk) if len(vectors) > 1 else 0.0,
            "topk": topk,
        }
    )
    return out


def _retrieval_out(project: DlProject) -> dict[str, Any]:
    _retrieval_project(project)
    if not project.last_asset_id:
        return {"asset_id": "", "total": 0, "classes": [], "items": [], "metrics": dict(project.last_metrics or {})}
    asset = _retrieval_asset(project)
    try:
        model = retrieval.load(asset.path)
    except retrieval.RetrievalError as exc:
        raise ValidationError(str(exc), code="bad_library") from None
    labels = np.asarray(model.get("labels"), dtype=np.int32)
    class_names = [str(c) for c in (model.get("classes") or [])]
    items: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in class_names}
    for idx, label_index in enumerate(labels):
        label = class_names[int(label_index)] if 0 <= int(label_index) < len(class_names) else ""
        thumb = model.get("thumbs", [])[idx] if idx < len(model.get("thumbs", [])) else b""
        row = {
            "index": int(idx),
            "id": str((model.get("thumb_ids") or [""])[idx]),
            "label": label,
            "thumb": f"data:image/jpeg;base64,{base64.b64encode(thumb).decode('ascii')}" if thumb else "",
        }
        items.append(row)
        groups.setdefault(label, []).append(row)
    return {
        "asset_id": str(asset.id),
        "total": int(len(items)),
        "classes": [{"label": name, "count": len(groups.get(name, [])), "items": groups.get(name, [])} for name in class_names],
        "items": items,
        "metrics": _retrieval_metrics(model, dict(project.last_metrics or {})),
    }


def _write_retrieval_model(project: DlProject, asset: Asset, data: bytes) -> dict[str, Any]:
    path = Path(asset.path)
    with path.open("wb") as fh:
        fh.write(data)
    retrieval.invalidate(path)
    asset.size = os.path.getsize(path)
    model = retrieval.loads(data, path=str(path.resolve()))
    metrics = _retrieval_metrics(model, dict(project.last_metrics or {}))
    asset.meta = {**dict(asset.meta or {}), "metrics": metrics}
    asset.save(update_fields=["size", "meta"])
    project.last_metrics = metrics
    project.save(update_fields=["last_metrics", "updated_at"])
    return _retrieval_out(project)


def _pixels_sha256(image: np.ndarray) -> str:
    """解碼後像素的 SHA256（含形狀，避免不同尺寸同 bytes 撞雜湊）；同專案內去重用。"""
    digest = hashlib.sha256(str(image.shape).encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def _existing_shas(project: DlProject) -> set[str]:
    """同專案已存在的像素雜湊，一次查回（之後純記憶體比對；空字串=舊資料，略過）。"""
    return {h for h in project.samples.values_list("sha256", flat=True) if h}


def _save_sample(project: DlProject, image: np.ndarray, label: str = "", sha: str = "") -> DlSample:
    sample_id = uuid.uuid4()
    path = os.path.join(_sample_dir(project), f"{sample_id.hex}.png")
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValidationError("Could not encode the image", code="encode_failed")
    buf.tofile(path)
    return DlSample.objects.create(
        id=sample_id, project=project, label=label, labeled_by="human" if label else "",
        path=path, width=int(image.shape[1]), height=int(image.shape[0]),
        sha256=sha or _pixels_sha256(image),
    )


#: ZIP 批次匯入接受的影像副檔名與單一 zip 的檔數上限（避免 zip 炸彈把行程吃滿）。
_ZIP_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
_ZIP_MAX_ENTRIES = 2000


def _iter_upload_images(file: UploadedFile):
    """一個上傳檔 → 逐張 (影像, 是否解碼失敗)。zip 檔內的影像逐一展開，其餘視為單張影像。"""
    name = (file.name or "").lower()
    data = file.read()
    if not name.endswith(".zip"):
        yield cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        return
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        yield None
        return
    count = 0
    for info in archive.infolist():
        if info.is_dir() or count >= _ZIP_MAX_ENTRIES:
            continue
        entry = info.filename
        base = os.path.basename(entry)
        if base.startswith(".") or "__MACOSX" in entry or not entry.lower().endswith(_ZIP_IMAGE_EXTS):
            continue
        count += 1
        yield cv2.imdecode(np.frombuffer(archive.read(info), dtype=np.uint8), cv2.IMREAD_COLOR)


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
        raise ValidationError("providers must be a list of strings", code="bad_providers")
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
    require_feature(request, "dl")
    body = _body(request)
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValidationError("A name is required", code="bad_name")
    kind = dl_base.get_trainer(str(body.get("trainer_kind") or "")).kind  # 驗證存在（舊名稱換成新的）
    classes = [str(c).strip() for c in (body.get("classes") or []) if str(c).strip()]
    if DlProject.objects.filter(name=name).exists():
        raise ValidationError(f'The name "{name}" is taken', code="duplicate_name")
    project = DlProject.objects.create(name=name, description=str(body.get("description") or ""), trainer_kind=kind, classes=classes, params=dict(body.get("params") or {}))
    return 201, _project_out(project)


@router.get("/dl/projects/{project_id}")
def get_project(request: HttpRequest, project_id: int):
    return _project_out(_project(project_id))


@router.patch("/dl/projects/{project_id}")
def patch_project(request: HttpRequest, project_id: int):
    require_feature(request, "dl")
    project = _project(project_id)
    body = _body(request)
    if "name" in body:
        name = str(body["name"] or "").strip()
        if not name:
            raise ValidationError("A name is required", code="bad_name")
        if DlProject.objects.exclude(pk=project.id).filter(name=name).exists():
            raise ValidationError(f'The name "{name}" is taken', code="duplicate_name")
        project.name = name
    if "description" in body:
        project.description = str(body["description"] or "")
    if "classes" in body:
        from django.db import transaction

        classes = list(dict.fromkeys(str(c).strip() for c in (body["classes"] or []) if str(c).strip()))  # 去重保序
        removed = set(project.classes or []) - set(classes)
        project.classes = classes
        with transaction.atomic():  # 清標記與寫入新類別要一起成立（清掉的標記不可復原）
            if removed:  # 被移除類別的標記一併清掉（label 與 shapes；殘留會讓之後的儲存被驗證拒絕）
                project.samples.filter(label__in=list(removed)).update(label="", labeled_by="", score=0)
                for sample in project.samples.all():
                    kept = [sh for sh in (sample.shapes or []) if sh.get("label") not in removed]
                    if len(kept) != len(sample.shapes or []):
                        sample.shapes = kept
                        if not kept:
                            sample.labeled_by = ""
                            sample.score = 0
                        sample.save(update_fields=["shapes", "labeled_by", "score"])
            project.save()
    if "params" in body and isinstance(body["params"], dict):
        project.params = body["params"]
    project.save()
    return _project_out(project)


@router.delete("/dl/projects/{project_id}", response={204: None})
def delete_project(request: HttpRequest, project_id: int):
    require_feature(request, "dl")
    project = _project(project_id)
    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", str(project.id))
    project.delete()
    shutil.rmtree(folder, ignore_errors=True)
    return 204, None


# ---------------------------------------------------------------------------
# 樣本：上傳、從來源收集、標記
# ---------------------------------------------------------------------------
@router.get("/dl/projects/{project_id}/samples")
def list_samples(request: HttpRequest, project_id: int, label: str = "__all__", split: str = "__all__"):
    project = _project(project_id)
    qs = project.samples.all()
    if label != "__all__":
        qs = qs.filter(label=label)
    if split != "__all__":
        qs = qs.filter(split=split)
    return {"items": [_sample_out(s) for s in qs]}


@router.post("/dl/projects/{project_id}/samples", response={201: dict})
def upload_samples(request: HttpRequest, project_id: int, files: list[UploadedFile] = File(...), label: str = Form("")):
    """上傳樣本影像（可混 zip 批次包）；解碼後以像素 SHA256 去重，重複的略過並回報 duplicates。"""
    require_feature(request, "dl")
    project = _project(project_id)
    if label and label not in (project.classes or []):
        raise ValidationError(f"'{label}' is not in the class list", code="bad_label")
    created, skipped, duplicates = [], 0, 0
    seen = _existing_shas(project)  # 既有＋同批內（zip 裡同圖兩份）都擋；一次查回不逐張打 DB
    for file in files:
        for image in _iter_upload_images(file):
            if image is None:
                skipped += 1
                continue
            sha = _pixels_sha256(image)
            if sha in seen:
                duplicates += 1
                continue
            seen.add(sha)
            created.append(_sample_out(_save_sample(project, image, label, sha=sha)))
    return 201, {"items": created, "skipped": skipped, "duplicates": duplicates}


@router.get("/dl/projects/{project_id}/retrieval-library")
def get_retrieval_library(request: HttpRequest, project_id: int):
    return _retrieval_out(_project(project_id))


@router.post("/dl/projects/{project_id}/retrieval-library/items", response={201: dict})
def add_retrieval_items(request: HttpRequest, project_id: int, files: list[UploadedFile] = File(...), label: str = Form("")):
    require_feature(request, "dl")
    principal(request).can_execute()
    project = _project(project_id)
    asset = _retrieval_asset(project)
    name = str(label or "").strip()
    if not name:
        raise ValidationError("A label is required", code="bad_label")
    classes = list(project.classes or [])
    if name not in classes:
        classes.append(name)
        project.classes = classes
        project.save(update_fields=["classes", "updated_at"])
    model = retrieval.load(asset.path)
    created, skipped, duplicates = 0, 0, 0
    seen = _existing_shas(project)
    data = b""
    for file in files:
        for image in _iter_upload_images(file):
            if image is None:
                skipped += 1
                continue
            sha = _pixels_sha256(image)
            if sha in seen:
                duplicates += 1
                continue
            seen.add(sha)
            _save_sample(project, image, name, sha=sha)
            data = retrieval.add(model, image, name)
            model = retrieval.loads(data, path=str(Path(asset.path).resolve()))
            created += 1
    if created == 0:
        return 201, {**_retrieval_out(project), "created": 0, "skipped": skipped, "duplicates": duplicates}
    out = _write_retrieval_model(project, asset, data)
    return 201, {**out, "created": created, "skipped": skipped, "duplicates": duplicates}


@router.delete("/dl/projects/{project_id}/retrieval-library/items/{index}")
def remove_retrieval_item(request: HttpRequest, project_id: int, index: int):
    require_feature(request, "dl")
    principal(request).can_execute()
    project = _project(project_id)
    asset = _retrieval_asset(project)
    try:
        data = retrieval.remove(retrieval.load(asset.path), int(index))
    except retrieval.RetrievalError as exc:
        raise ValidationError(str(exc), code="bad_library_item") from None
    return _write_retrieval_model(project, asset, data)


@router.post("/dl/projects/{project_id}/samples/from-source", response={201: dict})
def samples_from_source(request: HttpRequest, project_id: int):
    """從影像來源連抓 N 張進樣本集（現場快速收集）。"""
    require_feature(request, "dl")
    project = _project(project_id)
    body = _body(request)
    source_id = body.get("source_id")
    count = max(1, min(50, int(body.get("count") or 1)))
    label = str(body.get("label") or "")
    if label and label not in (project.classes or []):
        raise ValidationError(f"'{label}' is not in the class list", code="bad_label")
    created, duplicates = [], 0
    seen = _existing_shas(project)
    for _ in range(count):
        image = grab_by_id(source_id)
        if image is None:
            break
        sha = _pixels_sha256(image)
        if sha in seen:  # 靜態畫面連抓 N 張會是同一張，去重後只留一份
            duplicates += 1
            continue
        seen.add(sha)
        created.append(_sample_out(_save_sample(project, image, label, sha=sha)))
    if not created and not duplicates:
        raise ValidationError("The source produced no images", code="grab_failed")
    return 201, {"items": created, "duplicates": duplicates}


@router.get("/dl/samples/{sample_id}/file", auth=None)
def sample_file(request: HttpRequest, sample_id: uuid.UUID, max: int = 0):
    if authenticate(request) is None:
        return HttpResponse(status=401)
    sample = DlSample.objects.filter(pk=sample_id).first()
    if sample is None or not os.path.isfile(sample.path):
        raise NotFound("Sample not found", code="dl_sample_not_found")
    image = cv2.imdecode(np.fromfile(sample.path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise NotFound("The sample image is missing or damaged", code="dl_sample_not_found")
    response = HttpResponse(encode_image(image, max_side=max or None, fmt="jpeg"), content_type="image/jpeg")
    # 樣本影像不可變（同 id 內容不會改）：讓瀏覽器快取，儲存標記後縮圖牆不用整批重抓。
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    return response


@router.patch("/dl/samples/{sample_id}")
def patch_sample(request: HttpRequest, sample_id: uuid.UUID):
    require_feature(request, "dl")
    sample = DlSample.objects.filter(pk=sample_id).select_related("project").first()
    if sample is None:
        raise NotFound("Sample not found", code="dl_sample_not_found")
    body = _body(request)
    fields = []
    if "label" in body:
        label = str(body["label"] or "")
        if label and label not in (sample.project.classes or []):
            raise ValidationError(f"'{label}' is not in the class list", code="bad_label")
        sample.label = label
        sample.labeled_by = "human" if label else ""
        sample.score = 0
        fields += ["label", "labeled_by", "score"]
    if "shapes" in body:
        from apps.vision.dl.shapes import validate_shapes

        sample.shapes = validate_shapes(body["shapes"], list(sample.project.classes or []))
        sample.labeled_by = "human" if sample.shapes else ""
        sample.score = 0
        fields += ["shapes", "labeled_by", "score"]
    if "split" in body:
        split = str(body["split"] or "")
        if split not in ("", "train", "val", "test"):
            raise ValidationError("split must be train, val, test or empty", code="bad_split")
        sample.split = split
        fields += ["split"]
    if fields:
        sample.save(update_fields=sorted(set(fields)))
    return _sample_out(sample)


@router.delete("/dl/samples/{sample_id}", response={204: None})
def delete_sample(request: HttpRequest, sample_id: uuid.UUID):
    require_feature(request, "dl")
    sample = DlSample.objects.filter(pk=sample_id).first()
    if sample is None:
        raise NotFound("Sample not found", code="dl_sample_not_found")
    try:
        os.remove(sample.path)
    except OSError:
        pass
    sample.delete()
    return 204, None


@router.post("/dl/projects/{project_id}/labels")
def bulk_label(request: HttpRequest, project_id: int):
    """批次標記：{"items": [{"id", "label", "by"?}]}；接受自動標記建議時 by="auto"。"""
    require_feature(request, "dl")
    project = _project(project_id)
    body = _body(request)
    items = body.get("items")
    if not isinstance(items, list):
        raise ValidationError("An items list is required", code="bad_items")
    from apps.vision.dl.shapes import validate_shapes

    classes = set(project.classes or [])
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        by = "auto" if str(item.get("by") or "") == "auto" else "human"
        score = float(item.get("score") or 0)
        rows = project.samples.filter(pk=item.get("id"))
        if "shapes" in item:
            shapes = validate_shapes(item["shapes"], list(project.classes or []))
            updated += rows.update(shapes=shapes, labeled_by=by if shapes else "", score=score)
            continue
        label = str(item.get("label") or "")
        if label and label not in classes:
            continue
        updated += rows.update(label=label, labeled_by=by if label else "", score=score)
    return {"updated": updated, "counts": _counts(project)}


@router.post("/dl/projects/{project_id}/split")
def auto_split(request: HttpRequest, project_id: int):
    """自動分 train/val/test：{"val": 0.15, "test": 0.0, "seed"?}。

    classes 模式依類別分層（每類比例一致）；shapes 模式依「有無標記」分層。
    整批重新指派（含之前手動指定的）；個別樣本事後可用 PATCH /dl/samples/{id} 改。
    """
    require_feature(request, "dl")
    project = _project(project_id)
    body = _body(request)
    val = min(0.5, max(0.0, float(body.get("val") if body.get("val") is not None else 0.15)))
    test = min(0.5, max(0.0, float(body.get("test") or 0.0)))
    if val + test >= 1.0:
        raise ValidationError("val + test must be less than 1", code="bad_ratio")
    rows = list(project.samples.values_list("id", "label", "shapes"))
    if not rows:
        raise ValidationError("There are no samples to split", code="no_samples")
    rng = np.random.default_rng(int(body["seed"]) if body.get("seed") is not None else None)
    groups: dict[str, list] = {}
    for sid, label, shp in rows:
        key = label if _label_mode(project) == "classes" else ("labeled" if shp else "")
        groups.setdefault(key, []).append(sid)
    assign: dict[str, list] = {"train": [], "val": [], "test": []}
    for ids in groups.values():
        order = rng.permutation(len(ids))
        n_test = int(round(len(ids) * test))
        n_val = min(len(ids) - n_test, int(round(len(ids) * val)))
        for pos, i in enumerate(order):
            split = "test" if pos < n_test else "val" if pos < n_test + n_val else "train"
            assign[split].append(ids[int(i)])
    for split, ids in assign.items():
        project.samples.filter(pk__in=ids).update(split=split)
    return {"train": len(assign["train"]), "val": len(assign["val"]), "test": len(assign["test"])}


# ---------------------------------------------------------------------------
# YOLO 資料集匯出／匯入（與 VisionStereo 等工具互通；伺服器本機路徑）
# ---------------------------------------------------------------------------
@router.post("/dl/projects/{project_id}/dataset-export")
def dataset_export(request: HttpRequest, project_id: int):
    """{"dir": 目的資料夾, "val_ratio"?: 0.2} → 寫出 images/labels/{train,val} + data.yaml。"""
    require_feature(request, "dl")
    from apps.vision.dl.shapes import export_dataset

    project = _project(project_id)
    body = _body(request)
    out_dir = str(body.get("dir") or "").strip()
    if not out_dir:
        raise ValidationError("dir is required (the destination folder on the server)", code="bad_dir")
    rows = [(r.id.hex, r.path, list(r.shapes or [])) for r in project.samples.all()]
    return export_dataset(rows, list(project.classes or []), out_dir, val_ratio=float(body.get("val_ratio") or 0.2))


@router.post("/dl/projects/{project_id}/dataset-import")
def dataset_import(request: HttpRequest, project_id: int):
    """{"dir": YOLO 資料夾} → 把 images/labels 匯入成樣本（shapes）。類別依 data.yaml 對應，缺的自動補進專案。"""
    require_feature(request, "dl")
    from apps.vision.dl.shapes import iter_dataset, read_yaml_classes, yolo_to_shapes

    project = _project(project_id)
    body = _body(request)
    root = str(body.get("dir") or "").strip()
    if not root or not os.path.isdir(root):
        raise ValidationError("dir is required (an existing label folder on the server)", code="bad_dir")
    classes = read_yaml_classes(root) or list(project.classes or [])
    missing = [c for c in classes if c not in (project.classes or [])]
    if missing:
        project.classes = list(project.classes or []) + missing
        project.save(update_fields=["classes", "updated_at"])
    imported = skipped = duplicates = 0
    seen = _existing_shas(project)
    for image_path, label_text in iter_dataset(root):
        image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            skipped += 1
            continue
        sha = _pixels_sha256(image)
        if sha in seen:  # 重匯同一個資料夾不會長出兩份
            duplicates += 1
            continue
        seen.add(sha)
        sample = _save_sample(project, image, sha=sha)
        shapes = yolo_to_shapes(label_text, classes)
        if shapes:
            sample.shapes = shapes
            sample.labeled_by = "human"
            sample.save(update_fields=["shapes", "labeled_by"])
        imported += 1
    return {"imported": imported, "skipped": skipped, "duplicates": duplicates, "counts": _counts(project), "classes": list(project.classes or [])}


# ---------------------------------------------------------------------------
# 資料集版本：凍結目前樣本＋標記成 zip 存進資產庫（kind=dataset），之後可下載回溯
# ---------------------------------------------------------------------------
def _version_out(version: DlDatasetVersion) -> dict[str, Any]:
    return {
        "id": version.id, "name": version.name, "note": version.note,
        "stats": dict(version.stats or {}), "asset_id": version.asset_id, "created_at": version.created_at,
    }


def _freeze_zip(project: DlProject, work: str) -> None:
    """把專案目前的樣本寫進 work：shapes 模式 = YOLO 樹；classes 模式 = 類別資料夾＋manifest。"""
    rows = list(project.samples.all())
    if _label_mode(project) == "shapes":
        from apps.vision.dl.shapes import export_dataset

        export_dataset(((r.id.hex, r.path, list(r.shapes or []), r.split) for r in rows),
                       list(project.classes or []), work)
        return
    items = []
    for r in rows:
        folder = r.label or "_unlabeled"
        os.makedirs(os.path.join(work, folder), exist_ok=True)
        try:
            shutil.copyfile(r.path, os.path.join(work, folder, f"{r.id.hex}.png"))
        except OSError:
            continue
        items.append({"file": f"{folder}/{r.id.hex}.png", "label": r.label, "split": r.split})
    if not items:
        raise ValidationError("There are no samples to freeze", code="no_samples")
    with open(os.path.join(work, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"classes": list(project.classes or []), "items": items}, f, ensure_ascii=False, indent=1)


@router.get("/dl/projects/{project_id}/versions")
def list_versions(request: HttpRequest, project_id: int):
    project = _project(project_id)
    return {"items": [_version_out(v) for v in project.versions.all()]}


@router.post("/dl/projects/{project_id}/versions", response={201: dict})
def create_version(request: HttpRequest, project_id: int):
    """凍結資料集版本：{"name"?: 顯示名, "note"?: 備註}。"""
    require_feature(request, "dl")
    project = _project(project_id)
    body = _body(request)
    name = str(body.get("name") or "").strip() or f"v{project.versions.count() + 1}"
    splits = list(project.samples.values_list("split", flat=True))
    stats = {**_counts(project), "classes": list(project.classes or []),
             "split": {k: splits.count(k) for k in ("train", "val", "test")}}
    work = tempfile.mkdtemp(prefix="vs-dlver-")
    try:
        _freeze_zip(project, work)
        asset_id = uuid.uuid4()
        zip_path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, names in os.walk(work):
                for fname in names:
                    full = os.path.join(root, fname)
                    archive.write(full, os.path.relpath(full, work))
        Asset.objects.create(
            id=asset_id, name=f"{project.name}-{name}", kind="dataset", path=zip_path,
            size=os.path.getsize(zip_path), meta={"project": project.name, "version": name, "stats": stats},
        )
        version = DlDatasetVersion.objects.create(
            project=project, name=name, note=str(body.get("note") or ""), stats=stats, asset_id=asset_id.hex)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 201, _version_out(version)


@router.delete("/dl/versions/{version_id}", response={204: None})
def delete_version(request: HttpRequest, version_id: int):
    require_feature(request, "dl")
    version = DlDatasetVersion.objects.filter(pk=version_id).first()
    if version is None:
        raise NotFound("Dataset version not found", code="dl_version_not_found")
    asset = Asset.objects.filter(pk=version.asset_id).first() if version.asset_id else None
    if asset is not None:
        try:
            os.remove(asset.path)
        except OSError:
            pass
        asset.delete()
    version.delete()
    return 204, None


# ---------------------------------------------------------------------------
# SAM 點擊智慧標記（點一下物件 → polygon 建議；ultralytics 可選安裝）
# ---------------------------------------------------------------------------
@router.post("/dl/projects/{project_id}/sam-point")
def sam_point(request: HttpRequest, project_id: int):
    """{"sample_id", "points"?: [[x,y] 0~1], "labels"?: [1|0…], "boxes"?: [[x0,y0,x1,y1] 0~1], "model"?} → {"shapes": [...], "model"}。

    點（同一物件的正／負點）或框（每框一物件）至少給一種；label 由前端掛目前類別。
    第一次使用會自動下載 SAM 權重（預設 sam2.1_t.pt；VISION_SAM_MODEL 可改；回應會比較久）。
    """
    require_feature(request, "dl")
    from apps.vision.dl import sam

    project = _project(project_id)
    body = _body(request)
    sample = project.samples.filter(pk=body.get("sample_id")).first()
    if sample is None:
        raise NotFound("Sample not found", code="dl_sample_not_found")
    points = body.get("points") or []
    boxes = body.get("boxes") or []
    if not isinstance(points, list) or not isinstance(boxes, list) or not (points or boxes):
        raise ValidationError("points (normalised 0-1 coordinates) or boxes ([x0,y0,x1,y1] in 0-1) are required", code="bad_points")
    image = cv2.imdecode(np.fromfile(sample.path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise NotFound("The sample image is missing or damaged", code="dl_sample_not_found")
    device = yolo_runtime.pick_device("auto")[0]  # SAM 走 GPU 就用（訓練裝置設定是另一回事；CPU 全圖提案一張要 20 秒以上）
    try:
        shapes = sam.suggest_shapes(
            image, [[float(p[0]), float(p[1])] for p in points],
            [int(v) for v in body.get("labels") or []] or None,
            model_name=str(body.get("model") or ""), device=device,
            boxes_norm=[[float(v) for v in b[:4]] for b in boxes if isinstance(b, (list, tuple)) and len(b) >= 4])
    except (TrainError, ValueError) as exc:
        raise ValidationError(str(exc), code="sam_failed") from None
    return {"shapes": shapes, "model": os.path.basename(sam.loaded_model())}


# ---------------------------------------------------------------------------
# 自動標記與訓練
# ---------------------------------------------------------------------------
@router.post("/dl/projects/{project_id}/auto-label")
def auto_label(request: HttpRequest, project_id: int):
    """回傳未標記樣本的建議（不落地；前端確認後用 /labels 批次寫入）。

    body.method："model"（預設：trainer.suggest，用上次訓練的權重或官方底模）或 "sam"（shapes 專案：SAM2 全圖
    自動分割提案，掛第一個類別；每次最多 max_samples 張，回 remaining 讓前端可以續跑）。"""
    require_feature(request, "dl")
    project = _project(project_id)
    trainer = dl_base.get_trainer(project.trainer_kind)
    rows = list(project.samples.all())
    body = _body(request)
    if str(body.get("method") or "model") == "sam":
        if trainer.label_mode != "shapes":
            raise ValidationError("Whole-image SAM proposals only work on shape-labelled projects", code="sam_not_applicable")
        classes = [str(c) for c in (project.classes or [])]
        if not classes:
            raise ValidationError("Add at least one class under Edit classes first", code="no_classes")
        from apps.vision.dl import sam

        pending = [r for r in rows if not r.shapes or r.labeled_by == "auto"]
        limit = max(1, min(200, int(body.get("max_samples") or 20)))
        device = yolo_runtime.pick_device("auto")[0]  # SAM 走 GPU 就用（訓練裝置設定是另一回事；CPU 全圖提案一張要 20 秒以上）
        items = []
        try:
            for r in pending[:limit]:
                image = cv2.imdecode(np.fromfile(r.path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    continue
                shapes = sam.suggest_everything(image, model_name=str(body.get("model") or ""), device=device,
                                                max_masks=int(body.get("max_masks") or 30))
                if shapes:
                    items.append({"id": str(r.id), "label": "", "score": 0.5, "shapes": [{**sh, "label": classes[0]} for sh in shapes]})
        except TrainError as exc:
            raise ValidationError(str(exc), code="auto_label_failed") from None
        return {"items": items, "remaining": max(0, len(pending) - limit), "method": "sam", "model": os.path.basename(sam.loaded_model())}
    if trainer.label_mode == "shapes":
        labeled = [SampleRef(id=str(r.id), label=r.label, path=r.path, shapes=list(r.shapes or [])) for r in rows if r.shapes and r.labeled_by == "human"]
        unlabeled = [SampleRef(id=str(r.id), label="", path=r.path) for r in rows if not r.shapes or r.labeled_by == "auto"]
    else:
        labeled = [SampleRef(id=str(r.id), label=r.label, path=r.path) for r in rows if r.label and r.labeled_by == "human"]
        unlabeled = [SampleRef(id=str(r.id), label="", path=r.path) for r in rows if not r.label or r.labeled_by == "auto"]
    params = {**dict(project.params or {}), **(body.get("params") or {})}
    weights = (project.last_metrics or {}).get("weights_path")
    if weights and "weights" not in params:
        params["weights"] = weights  # yolo trainer 沿用上次訓練的 best.pt
    try:
        suggestions = trainer.suggest(labeled, unlabeled, list(project.classes or []), params)
    except TrainError as exc:
        raise ValidationError(str(exc), code="auto_label_failed") from None
    items = []
    for sg in suggestions:
        item = {"id": sg.sample_id, "label": sg.label, "score": sg.score}
        if sg.shapes is not None:
            item["shapes"] = sg.shapes
        items.append(item)
    return {"items": items}


@router.post("/dl/projects/{project_id}/train", response={202: dict})
def start_training(request: HttpRequest, project_id: int):
    require_feature(request, "dl")
    principal(request).can_execute()
    project = _project(project_id)
    body = _body(request)
    params = {**dict(project.params or {}), **(body.get("params") or {})}
    if isinstance(body.get("params"), dict):  # 記住這次的超參數
        project.params = params
        project.save(update_fields=["params", "updated_at"])
    device = str(body.get("device") or devices.train_device())
    return 202, jobs.start(project, params, device, str(body.get("asset_name") or ""))


@router.post("/dl/projects/{project_id}/quick-register", response={202: dict})
def quick_register(request: HttpRequest, project_id: int):
    require_feature(request, "dl")
    principal(request).can_execute()
    project = _project(project_id)
    body = _body(request)
    return 202, quick.quick_register(
        project,
        device=str(body.get("device") or ""),
        asset_name=str(body.get("asset_name") or ""),
    )


@router.get("/dl/train/status")
def train_status(request: HttpRequest, log_from: int = -1):
    return {"job": jobs.status(None if log_from < 0 else log_from)}


@router.post("/dl/train/cancel")
def train_cancel(request: HttpRequest):
    require_feature(request, "dl")
    return {"cancelled": jobs.cancel()}


@router.post("/dl/train/save")
def train_save(request: HttpRequest):
    """把剛訓練好的模型存進資產庫（訓練完不會自動存，先讓使用者看指標、命名）。"""
    require_feature(request, "dl")
    name = str(_body(request).get("name") or "")
    job = jobs.save(name)
    audit.record(request, "dl.model.save", target_type="asset", target_id=job["asset_id"], target_name=job["asset_name"],
                 summary=f"{job['project_name']} → {job['asset_name']}",
                 detail={"trainer": job["trainer_kind"], "tool": job["tool_key"], "metrics": job["metrics"]})
    return job


@router.post("/dl/train/discard")
def train_discard(request: HttpRequest):
    """不要這個模型：刪掉還沒進資產庫的產物檔。"""
    require_feature(request, "dl")
    return {"discarded": jobs.discard()}
