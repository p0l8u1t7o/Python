"""API 請求／回應模型。

回應約定
--------
成功（2xx）直接回傳資料本身；失敗（4xx/5xx）一律回傳統一的錯誤外層：

    { "ok": false, "data": null,
      "error": {"code": "VALIDATION_ERROR", "message": "...", "detail": "..."} }

前端只需要在 HTTP 狀態碼 >= 400 時讀 error 欄位，其餘直接用 body。
所有錯誤（含未預期的例外）都會經過 app.py 的例外處理器轉成這個格式，
不會有裸的 traceback 流到前端。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str
    message: str
    detail: str = ""


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any = None
    error: ApiError | None = None


class SimulateRequest(BaseModel):
    speed_mm_hr: float = Field(..., gt=0, le=200, description="熔區移動速率 [mm/hr]")
    temp_c: float = Field(..., ge=100, le=900,
                          description="熔區溫度 [°C]。銦熔點 156.6 °C，"
                                      "低於 100 °C 一律視為單位或欄位錯誤")
    n_passes: int = Field(..., ge=1, le=60, description="純化次數")
    zone_len_frac: float | None = Field(None, gt=0, lt=1, description="熔區長度比 l/L")
    head_crop_frac: float = Field(0.03, ge=0, lt=0.5, description="頭端固定切除比例")
    threshold_ppm: float | None = Field(None, gt=0, description="6N 判定門檻（總雜質 ppm）")
    c0_ppm: dict[str, float] | None = Field(None, description="各元素進料濃度 [ppm]")
    use_ai: bool = Field(False, description="是否套用 L1 殘差修正（雙軌顯示）")


class OptimizeRequest(BaseModel):
    speed_min: float | None = Field(None, gt=0)
    speed_max: float | None = Field(None, gt=0)
    temp_min: float | None = None
    temp_max: float | None = None
    pass_choices: list[int] | None = Field(None, description="要掃描的純化次數")
    throughput_weight: float = Field(0.0, ge=0, le=1,
                                     description="產能權重；0 為純看得料率")
    zone_len_frac: float | None = Field(None, gt=0, lt=1)


class SuggestRequest(BaseModel):
    n_suggest: int = Field(3, ge=1, le=10)
    speed_min: float | None = Field(None, gt=0)
    speed_max: float | None = Field(None, gt=0)
    temp_min: float | None = None
    temp_max: float | None = None
    pass_choices: list[int] | None = None


class DOERequest(BaseModel):
    factorial_speeds: int = Field(4, ge=2, le=8)
    factorial_temps: int = Field(3, ge=2, le=8)
    pass_choices: list[int] | None = None
    bo_budget: int = Field(12, ge=4, le=60)
    seed_n: int = Field(5, ge=2, le=20)
    cost_per_batch: float = Field(100000.0, ge=0)


class SeedRequest(BaseModel):
    n_batches: int = Field(20, ge=4, le=200)
    seed: int = 20250114
    rel_noise: float = Field(0.12, ge=0.0, le=1.0)
    n_sample_points: int = Field(8, ge=3, le=40)
    inject_anomalies: bool = True
    clear_existing: bool = True


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)
    provider: str | None = Field(None, description="覆寫 provider：anthropic/openai/template")
