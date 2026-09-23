"""
標註與訓練資料匯出 (規劃書 PLAN-002 第 6 節)

- 標註以「影像＋檢測模組」為單位；每次儲存新增一筆 (保留歷程)，最新一筆為目前標註，不覆寫模組原始結果
- 空洞檢測的標註內容：
    balls：標註當下採用的焊點 [[x, y, r], …] (取自基準分析紀錄)
    voids：空洞輪廓 [[[x, y], …], …] (影像座標)；焊點內沒有輪廓 = 標註者確認無空洞
- 人工複判說明「判定是否正確」，標註說明「空洞正確位置」，兩者分開記錄
- 訓練資料匯出：單一 ZIP，內含焊點裁切 (16-bit 正規化吸收量，與模型前處理相同)、遮罩 PNG、dataset.json
"""
import io
import json
import os
import time
import zipfile

import cv2
import numpy as np

from ..core.calibration import prepare
from ..core.io import load_image
from ..inspections.void.model_seg import NORMALIZATION, ball_crop, mask_crop
from ..store.db import now

DATASET_FORMAT = "xrv-void-dataset/1"
VALIDATION_FORMAT = "xrv-validation-set/1"
CROP_SIZE, CROP_SCALE, CROP_RANGE = 64, 1.4, (-0.5, 1.5)
MAX_SHAPES, MAX_POINTS = 2000, 500
SUPPORTED_MODULES = ("void",)


class AnnotationError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _run(db, run_id):
    r = db.one("SELECT r.id, r.image_id, r.result_path, i.sha256, i.file_name, i.archive_path, i.original_path, "
               "i.archive_purged_at, i.width, i.height, i.sample_no, l.lot_no FROM runs r JOIN images i ON i.id = r.image_id "
               "LEFT JOIN lots l ON l.id = i.lot_id WHERE r.id = ?", (run_id,))
    if r is None:
        raise AnnotationError("run_not_found", run_id)
    return r


def _result(r):
    try:
        with open(r["result_path"], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        raise AnnotationError("result_unavailable", r["id"])


def base_from_result(result, module_id):
    """由分析結果建立標註初稿：採用的焊點與模組找到的空洞"""
    m = next((m for m in result["modules"] if m["module_id"] == module_id), None)
    if m is None:
        raise AnnotationError("module_not_in_run", module_id)
    balls = [[f["geometry"]["ball"]["x"], f["geometry"]["ball"]["y"], f["geometry"]["ball"]["r"]]
             for f in m["findings"] if f["category"] == "ball" and f["used"]]
    voids = [f["geometry"]["void"]["points"] for f in m["findings"] if f["category"] == "void"]
    return dict(balls=balls, voids=voids)


def get(db, run_id, module_id="void"):
    """回傳 dict(current, history_count, base)：current 為最新標註 (可能為 None)，base 為模組結果初稿"""
    if module_id not in SUPPORTED_MODULES:
        raise AnnotationError("annotation_not_supported", module_id)
    r = _run(db, run_id)
    rows = db.all("SELECT * FROM annotations WHERE image_id = ? AND module_id = ? ORDER BY id DESC",
                  (r["image_id"], module_id))
    cur = None
    if rows:
        cur = dict(rows[0])
        cur["data"] = json.loads(cur.pop("data_json"))
    return dict(current=cur, history_count=len(rows), base=base_from_result(_result(r), module_id))


def _clean(data):
    try:
        balls = [[float(b[0]), float(b[1]), float(b[2])] for b in data.get("balls", [])]
        voids = []
        for poly in data.get("voids", []):
            pts = [[float(p[0]), float(p[1])] for p in poly]
            if not 3 <= len(pts) <= MAX_POINTS:
                raise ValueError("points")
            voids.append(pts)
    except (TypeError, ValueError, IndexError, KeyError):
        raise AnnotationError("invalid_annotation")
    if len(balls) > MAX_SHAPES or len(voids) > MAX_SHAPES or any(b[2] <= 0 for b in balls):
        raise AnnotationError("invalid_annotation")
    return dict(balls=balls, voids=voids)


def save(db, run_id, module_id, data, actor, note=""):
    if module_id not in SUPPORTED_MODULES:
        raise AnnotationError("annotation_not_supported", module_id)
    r = _run(db, run_id)
    clean = _clean(data)
    pk = db.insert("annotations", run_id=run_id, image_id=r["image_id"], module_id=module_id,
                   data_json=json.dumps(clean), note=note or "", actor=actor, created_at=now())
    db.audit(actor, "annotation.save", "image", r["image_id"], run_id=run_id, module_id=module_id,
             balls=len(clean["balls"]), voids=len(clean["voids"]))
    return get(db, run_id, module_id)


# ---------------------------------------------------------------------------
# 訓練資料匯出
# ---------------------------------------------------------------------------
def _encode_crop(c):
    lo, hi = CROP_RANGE
    v = np.clip((c - lo) / (hi - lo), 0, 1) * 65535
    ok, buf = cv2.imencode(".png", v.round().astype(np.uint16))
    return buf.tobytes()


def export_dataset(settings, db, run_ids, actor, deidentify=False, module_id="void", include_images=False):
    """
    回傳 (檔名, ZIP bytes, 統計)。只匯出有標註的影像；影像檔已清除者略過。
    include_images：另附原始影像 (images/) 與整張影像的標註 (annotations.json)，作為模組驗證資料集 (validate-module)
    """
    from .diagnostics import _Deid
    deid = _Deid(deidentify)
    buf = io.BytesIO()
    items, skipped, images, full = [], [], set(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for run_id in run_ids:
            r = _run(db, run_id)
            if r["image_id"] in images:
                continue
            row = db.one("SELECT * FROM annotations WHERE image_id = ? AND module_id = ? ORDER BY id DESC LIMIT 1",
                         (r["image_id"], module_id))
            if row is None:
                skipped.append(dict(run_id=run_id, reason="not_annotated"))
                continue
            path = r["archive_path"] if r["archive_path"] and os.path.isfile(r["archive_path"]) else r["original_path"]
            if not path or not os.path.isfile(path):
                skipped.append(dict(run_id=run_id, reason="image_unavailable"))
                continue
            images.add(r["image_id"])
            data = json.loads(row["data_json"])
            if include_images:
                arc = "images/" + (deid.file(r["file_name"]) or os.path.basename(path))
                z.write(path, arc)
                full.append(dict(file=arc, sha256=r["sha256"], lot=deid.code("lot", r["lot_no"], "LOT"),
                                 balls=data["balls"], voids=data["voids"], annotator=deid.code("user", row["actor"], "U"),
                                 annotated_at=row["created_at"]))
            A = prepare(load_image(path)).absorption
            H, W = A.shape
            vmask = np.zeros((H, W), np.uint8)
            for poly in data["voids"]:
                cv2.fillPoly(vmask, [np.array(poly, np.float64).round().astype(np.int32).reshape(-1, 1, 2)], 1)
            job = db.one("SELECT acquisition_json FROM jobs WHERE image_id = ? ORDER BY id DESC LIMIT 1", (r["image_id"],))
            acq = (json.loads(job["acquisition_json"]) if job else {}).get("params", {})
            for x, y, rad in data["balls"]:
                disc = np.zeros((H, W), np.uint8)
                cv2.circle(disc, (int(round(x * 8)), int(round(y * 8))), int(round(rad * 8)), 1, -1, shift=3)
                c, win = ball_crop(A, x, y, rad, CROP_SIZE, CROP_SCALE)
                m = mask_crop(vmask & disc, win, CROP_SIZE)
                k = len(items) + 1
                z.writestr(f"crops/{k:06d}.png", _encode_crop(c))
                ok, mb = cv2.imencode(".png", (m * 255).astype(np.uint8))
                z.writestr(f"masks/{k:06d}.png", mb.tobytes())
                items.append(dict(
                    crop=f"crops/{k:06d}.png", mask=f"masks/{k:06d}.png",
                    void_pct=float(100.0 * (vmask & disc).sum() / max(np.pi * rad * rad, 1)),
                    source=dict(image_sha256=r["sha256"], file=deid.file(r["file_name"]),
                                lot=deid.code("lot", r["lot_no"], "LOT"), sample=deid.code("sample", r["sample_no"], "S"),
                                run_id=run_id, ball=[x, y, rad], image_size=[W, H]),
                    acquisition=acq, annotator=deid.code("user", row["actor"], "U"), annotated_at=row["created_at"]))
        meta = dict(format=DATASET_FORMAT, created_at=now(), module_id=module_id, deidentified=bool(deidentify),
                    crop_encoding=dict(size=CROP_SIZE, crop_scale=CROP_SCALE, normalization=NORMALIZATION,
                                       dtype="uint16", range=list(CROP_RANGE)),
                    items=items, skipped=skipped)
        z.writestr("dataset.json", json.dumps(meta, ensure_ascii=False, indent=1))
        if include_images:
            z.writestr("annotations.json", json.dumps(dict(format=VALIDATION_FORMAT, module_id=module_id, created_at=now(),
                                                           images=full), ensure_ascii=False, indent=1))
    if not items:
        raise AnnotationError("no_annotated_images")
    name = f"dataset_{module_id}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    db.audit(actor, "annotation.export", "dataset", name, runs=list(run_ids), crops=len(items), images=len(images),
             deidentify=bool(deidentify), include_images=bool(include_images))
    return name, buf.getvalue(), dict(crops=len(items), images=len(images), skipped=len(skipped))
