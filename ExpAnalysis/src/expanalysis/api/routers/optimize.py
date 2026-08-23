"""模擬與最佳化端點。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...logging_setup import get_logger
from ...ml.bayesopt import doe_comparison, suggest_next_batches
from ...service import get_service
from ..schemas import DOERequest, OptimizeRequest, SimulateRequest, SuggestRequest

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["optimize"])


@router.post("/simulate")
def simulate(req: SimulateRequest):
    try:
        return get_service().simulate(
            req.speed_mm_hr, req.temp_c, req.n_passes,
            zone_len_frac=req.zone_len_frac, c0_ppm=req.c0_ppm,
            use_ai=req.use_ai, head_crop_frac=req.head_crop_frac,
            threshold_ppm=req.threshold_ppm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/optimize/grid")
def optimize_grid(req: OptimizeRequest):
    sp = (req.speed_min, req.speed_max) if req.speed_min and req.speed_max else None
    tp = (req.temp_min, req.temp_max) if req.temp_min is not None and req.temp_max is not None else None
    if sp and sp[0] >= sp[1]:
        raise HTTPException(status_code=400, detail="speed_min 必須小於 speed_max")
    if tp and tp[0] >= tp[1]:
        raise HTTPException(status_code=400, detail="temp_min 必須小於 temp_max")
    try:
        return get_service().optimize(
            speed_range=sp, temp_range=tp,
            pass_choices=tuple(req.pass_choices) if req.pass_choices else None,
            throughput_weight=req.throughput_weight,
            zone_len_frac=req.zone_len_frac)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/optimize/suggest")
def suggest(req: SuggestRequest):
    svc = get_service()
    details = svc.repo.all_details()
    if not details:
        raise HTTPException(status_code=400, detail="資料庫沒有批次資料")
    sp = (req.speed_min or max(0.3, min(d.batch.speed_mm_hr for d in details) * 0.6),
          req.speed_max or max(d.batch.speed_mm_hr for d in details) * 1.3)
    tp = (req.temp_min if req.temp_min is not None else min(d.batch.temp_c for d in details) - 5,
          req.temp_max if req.temp_max is not None else max(d.batch.temp_c for d in details) + 5)
    pc = tuple(req.pass_choices or sorted({d.batch.n_passes for d in details})) or (8,)
    return suggest_next_batches(svc.bo_observations(), sp, tp, pc,
                                n_suggest=req.n_suggest)


@router.post("/optimize/doe-comparison")
def doe(req: DOERequest):
    """全因子 DOE vs 貝氏最佳化的省批次試算。"""
    svc = get_service()
    details = svc.repo.all_details()
    if not details:
        raise HTTPException(status_code=400, detail="資料庫沒有批次資料")
    sp = (max(0.3, min(d.batch.speed_mm_hr for d in details) * 0.6),
          max(d.batch.speed_mm_hr for d in details) * 1.3)
    tp = (min(d.batch.temp_c for d in details) - 5,
          max(d.batch.temp_c for d in details) + 5)
    pc = tuple(req.pass_choices or sorted({d.batch.n_passes for d in details})[:3]) or (8,)
    try:
        res = doe_comparison(svc.make_oracle(), speed_range=sp, temp_range=tp,
                             pass_choices=pc,
                             factorial_speeds=req.factorial_speeds,
                             factorial_temps=req.factorial_temps,
                             bo_budget=req.bo_budget, seed_n=req.seed_n,
                             cost_per_batch=req.cost_per_batch)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=f"DOE 對比失敗：{exc}") from exc
    return res.to_dict()
