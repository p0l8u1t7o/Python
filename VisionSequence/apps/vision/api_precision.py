"""精度研究的 API（WP-13）：POST /vision/flows/{id}/precision {mode, repeat, source_id?, tolerance?, reference?} → JSON 結果＋markdown。

同步執行（repeat ≤ 200；每次幾毫秒，再現性用實機相機時是取像時間 × N）。走 engine.execute 直跑（與批次測試同路），不計統計、不寫 FlowRun。
GR&R 需要多件影像，只在 manage.py precision 提供。
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest
from ninja import Router

from apps.accounts.security import principal, require_feature
from apps.core.errors import ValidationError
from apps.vision import precision
from apps.vision.api import _operable_flow

router = Router(tags=["precision"])
MAX_REPEAT = 200


def _numbers(value: Any, what: str) -> dict[str, float]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{what} must be an object of output name → number", code="bad_request")
    out: dict[str, float] = {}
    for k, v in value.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            raise ValidationError(f"{what}.{k} is not a number", code="bad_request") from None
    return out


@router.post("/flows/{flow_id}/precision")
def run_precision(request: HttpRequest, flow_id: int):
    require_feature(request, "flows.run")
    principal(request).can_execute()
    flow = _operable_flow(request, flow_id)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(body, dict):
        raise ValidationError("The body must be a JSON object", code="bad_json")
    mode = str(body.get("mode") or "repeatability")
    if mode not in ("repeatability", "reproducibility"):
        raise ValidationError("mode must be repeatability or reproducibility (GR&R runs from manage.py precision)", code="bad_mode")
    try:
        repeat = int(body.get("repeat") or 30)
    except (TypeError, ValueError):
        raise ValidationError("repeat must be an integer", code="bad_request") from None
    if not 2 <= repeat <= MAX_REPEAT:
        raise ValidationError(f"repeat must be between 2 and {MAX_REPEAT}", code="bad_request")
    source_id = body.get("source_id")
    try:
        source_id = int(source_id) if source_id not in (None, "") else None
    except (TypeError, ValueError):
        raise ValidationError("source_id must be an integer", code="bad_request") from None
    try:
        result = precision.study(flow, mode, repeat=repeat, source_id=source_id, tolerance=_numbers(body.get("tolerance"), "tolerance"), reference=_numbers(body.get("reference"), "reference"))
    except precision.PrecisionError as exc:
        raise ValidationError(str(exc), code="precision_failed") from None
    result["markdown"] = precision.markdown_report(result)
    return result
