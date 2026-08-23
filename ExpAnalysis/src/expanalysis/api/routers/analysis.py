"""分析端點：總覽、k_eff 表、參數映射、異常、驗證。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...logging_setup import get_logger
from ...service import get_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/overview")
def overview():
    return get_service().overview()


@router.get("/keff")
def keff_table(element: str | None = Query(None, description="以元素過濾")):
    rows = get_service().keff_table()
    return [r for r in rows if r["element"] == element] if element else rows


@router.get("/mapping")
def mapping():
    return get_service().mapping_payload()


@router.get("/anomalies")
def anomalies(severity: str | None = Query(None, pattern="^(high|medium|low)$")):
    rows = get_service().anomalies()
    return [r for r in rows if r["severity"] == severity] if severity else rows


@router.get("/validation")
def validation(use_ai: bool = True):
    return get_service().lobo(use_residual_ai=use_ai)


@router.get("/censoring-study")
def censoring_study():
    """設限處理方式的對照實驗：當成 0 / 當成 LOD / Tobit 的差異。"""
    from ...ml.validation import censoring_comparison
    svc = get_service()
    details = svc.repo.all_details()
    if not details:
        raise HTTPException(status_code=400, detail="資料庫沒有批次資料")
    return censoring_comparison(details)


@router.get("/pass-advice")
def pass_advice(n_passes_max: int = Query(25, ge=5, le=60)):
    """純化次數飽和分析：做到第幾次之後就白做了。"""
    from ...config import SETTINGS
    from ...physics.multipass import find_ultimate_pass
    import numpy as np

    svc = get_service()
    b = svc.bundle()
    if not b.elements:
        raise HTTPException(status_code=400, detail="尚未有可用的擬合結果")
    details = svc.repo.all_details()
    speed = float(np.median([d.batch.speed_mm_hr for d in details]))
    temp = float(np.median([d.batch.temp_c for d in details]))
    ks = np.array([float(b.mapping[el].predict(speed, temp, return_ci=False)[0])
                   for el in b.elements])
    c0 = np.array([b.c0_median[el] for el in b.elements])
    # 頭端切除比例取歷史批次的中位數，而不是寫死 0.03——否則這裡算出來的
    # 得料率會與「批次資料」「模擬」頁用的基準不一致，同一個系統出現兩套數字。
    crop = float(np.median([d.batch.head_crop_frac for d in details]))
    out = find_ultimate_pass(ks, b.zone_len_frac_median, c0=c0,
                             max_passes=n_passes_max,
                             threshold_ppm=SETTINGS.purity_threshold_ppm,
                             head_crop_frac=crop, elements=b.elements)
    out["conditions"] = {"speed_mm_hr": speed, "temp_c": temp,
                         "head_crop_frac": crop,
                         "zone_len_frac": b.zone_len_frac_median,
                         "k_eff": {el: round(float(k), 5)
                                   for el, k in zip(b.elements, ks)}}
    return out
