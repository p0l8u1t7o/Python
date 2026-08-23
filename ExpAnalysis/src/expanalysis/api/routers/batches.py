"""批次資料端點：查詢、匯入、合成資料、刪除。"""

from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from ...data.importer import import_dataframe, template_csv
from ...data.synthetic import SyntheticConfig, seed_database
from ...logging_setup import get_logger
from ...service import get_service
from ..schemas import SeedRequest

log = get_logger(__name__)
router = APIRouter(prefix="/api/batches", tags=["batches"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("")
def list_batches():
    svc = get_service()
    return [{**b.to_dict(), "yield_frac": svc.batch_yield(b.batch_id)}
            for b in svc.repo.list_batches()]


@router.get("/template.csv", response_class=PlainTextResponse)
def download_template():
    """下載匯入用的 CSV 範本。加 BOM 讓 Excel 正確辨識 UTF-8。"""
    return PlainTextResponse(
        "﻿" + template_csv(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="expanalysis_template.csv"'})


@router.get("/{batch_id}")
def get_batch(batch_id: str):
    payload = get_service().batch_payload(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"找不到批次 {batch_id}")
    return payload


@router.delete("/{batch_id}")
def delete_batch(batch_id: str):
    svc = get_service()
    if not svc.repo.delete_batch(batch_id):
        raise HTTPException(status_code=404, detail=f"找不到批次 {batch_id}")
    svc.invalidate()
    return {"deleted": batch_id}


@router.post("/import")
async def import_batches(request: Request, file: UploadFile = File(...),
                         dry_run: bool = False):
    """匯入 CSV / Excel。dry_run=true 只稽核不寫入。"""
    # 先看標頭再讀內容：否則超大檔案已經整個進記憶體才回 413，防護等於沒有
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES * 1.1:
        raise HTTPException(status_code=413,
                            detail=f"檔案超過上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"檔案超過上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    name = (file.filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw))
        else:
            try:
                df = pd.read_csv(io.BytesIO(raw))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw), encoding="big5")
    except (ValueError, pd.errors.ParserError) as exc:
        raise HTTPException(status_code=400, detail=f"檔案無法解析：{exc}") from exc

    svc = get_service()
    report = import_dataframe(df, None if dry_run else svc.repo)
    if not dry_run and report.ok:
        svc.invalidate()
    return report.to_dict()


@router.post("/seed-demo")
def seed_demo(req: SeedRequest):
    """產生合成資料集。所有畫面都會標示為合成資料。"""
    svc = get_service()
    cfg = SyntheticConfig(
        n_batches=req.n_batches, seed=req.seed, rel_noise=req.rel_noise,
        n_sample_points=req.n_sample_points, inject_anomalies=req.inject_anomalies,
    )
    truth = seed_database(svc.repo, cfg, clear=req.clear_existing)
    svc.invalidate()
    log.info("已產生 %d 批合成資料", req.n_batches)
    return {"n_batches": req.n_batches,
            "injected_anomalies": truth["injected_anomalies"],
            "element_truth": truth["element_truth"],
            "disclaimer": truth["disclaimer"]}


@router.delete("")
def clear_all():
    svc = get_service()
    svc.repo.clear_all()
    svc.invalidate()
    return {"cleared": True}
