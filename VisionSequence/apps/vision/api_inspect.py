"""檢測任務清單與最近試執行摘要 API。"""

from __future__ import annotations

import datetime as dt
import json
import math
import struct
from typing import Any, Literal

from django.db import transaction
from django.http import HttpRequest
from ninja import Router, Schema
from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator

from apps.accounts.security import principal, require_feature
from apps.core import audit
from apps.core.errors import APIError, NotFound, ValidationError
from apps.vision import inspect
from apps.vision.models import InspectionTrial
from apps.vision.tasks import all as all_definitions

router = Router(tags=["inspect"])


def inspection_graph_hash(graph: dict) -> str:
    """與前端共用 v2 正規化：UTF-16 鍵序、ASCII 字串、精確 binary64 數值。"""
    def canonical(value):
        if isinstance(value, dict):
            return "{" + ",".join(json.dumps(key, ensure_ascii=True) + ":" + canonical(value[key])
                                  for key in sorted(value, key=lambda key: key.encode("utf-16-be", errors="surrogatepass"))) + "}"
        if isinstance(value, list):
            return "[" + ",".join(canonical(item) for item in value) + "]"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if not math.isfinite(number):
                raise ValidationError("Graph numbers must be finite", code="bad_trial")
            return "n:" + struct.pack(">d", number if number else 0.0).hex()
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    try:
        return "v2:" + canonical(graph)
    except (OverflowError, RecursionError) as exc:
        raise ValidationError("Invalid trial graph", code="bad_trial") from exc


class TrialReadingIn(Schema):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    status: Literal["pass", "fail", "not_found", "locate_failed", "error", "skipped"]
    value: StrictInt | StrictFloat | StrictStr | None = None
    unit: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=4000)
    valid: StrictBool
    detected: StrictBool | None = None
    node_id: str = Field(default="", max_length=200)

    @field_validator("value")
    @classmethod
    def scalar_value(cls, value):
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError("Reading numbers must be finite")
        if isinstance(value, str) and len(value) > 4000:
            raise ValueError("Reading text is too long")
        return value


class LastTrialIn(Schema):
    model_config = ConfigDict(extra="forbid")
    graph: dict[str, Any]
    readings: list[TrialReadingIn] = Field(max_length=1000)
    status: Literal["ok", "ng", "failed"]
    judge: str = Field(default="", max_length=200)
    executed_at: dt.datetime

    @field_validator("executed_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("Execution time must include a timezone")
        return value.astimezone(dt.UTC)


def _trial_flow(request, flow_id):
    # 沿用正式流程可見性，避免將建立者誤當成唯一讀取者。
    from apps.vision.api import _visible_flows
    flow = _visible_flows(request).filter(pk=flow_id).first()
    if flow is None:
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    return flow


def _trial_out(row):
    return {"hash": row.graph_hash, "readings": row.readings, "status": row.status, "judge": row.judge,
            "executed_at": row.executed_at.isoformat(), "executed_by": row.executed_by}


@router.get("/inspect/{flow_id}/last-trial")
def last_trial(request: HttpRequest, flow_id: int):
    require_feature(request, "flows.run")
    flow = _trial_flow(request, flow_id)
    row = InspectionTrial.objects.filter(flow=flow).first()
    return {"trial": _trial_out(row) if row else None}


@router.put("/inspect/{flow_id}/last-trial")
def save_last_trial(request: HttpRequest, flow_id: int, payload: LastTrialIn):
    """由頁面在顯示結果後另送請求；試執行及引擎熱路徑不等待資料庫。"""
    actor = require_feature(request, "flows.run")
    actor.can_execute()
    flow = _trial_flow(request, flow_id)
    graph_hash = inspection_graph_hash(payload.graph)
    readings = [reading.model_dump() for reading in payload.readings]
    if len(graph_hash) > 2_000_000 or len(json.dumps(readings, ensure_ascii=True)) > 256_000:
        raise ValidationError("Trial summary is too large", code="bad_trial")
    if len({reading["task_id"] for reading in readings}) != len(readings):
        raise ValidationError("Trial task IDs must be unique", code="bad_trial")
    with transaction.atomic():
        # 鎖定父列，涵蓋首筆建立；較晚送達的舊試執行不可蓋掉新摘要。
        type(flow).objects.select_for_update().get(pk=flow.pk)
        row = InspectionTrial.objects.filter(flow=flow).first()
        if row and row.executed_at >= payload.executed_at:
            return {"saved": False}
        InspectionTrial.objects.update_or_create(flow=flow, defaults={
            "graph_hash": graph_hash, "readings": readings, "status": payload.status, "judge": payload.judge,
            "executed_at": payload.executed_at, "executed_by": actor.name,
        })
        audit.record(request, "inspect.last_trial", target_type="flow", target_id=str(flow.pk),
                     summary="Saved inspection trial readings", detail={"count": len(readings)})
    return {"saved": True}


class GraphIn(Schema):
    graph: dict[str, Any]


class TaskGraphIn(Schema):
    graph: dict[str, Any]
    task: dict[str, Any]
    ctx: dict[str, Any] = {}


class RemoveIn(Schema):
    graph: dict[str, Any]
    task_id: str


class EvidenceIn(Schema):
    graph: dict[str, Any]
    report: dict[str, Any]


class TeachPoseIn(Schema):
    graph: dict[str, Any]
    task_id: str
    report: dict[str, Any]


def _as_422(exc: APIError) -> ValidationError:
    return ValidationError(exc.message, code=exc.code, details=exc.details)


@router.get("/inspect/kinds")
def kinds(request: HttpRequest):
    principal(request)
    return {"items": [definition.as_dict() for definition in all_definitions()]}


@router.post("/inspect/read")
def read(request: HttpRequest, payload: GraphIn):
    principal(request)
    try:
        return inspect.read(payload.graph)
    except APIError as exc:
        raise _as_422(exc) from exc


@router.post("/inspect/build")
def build(request: HttpRequest, payload: TaskGraphIn):
    require_feature(request, "flows.edit")
    try:
        return {"graph": inspect.build(payload.graph, payload.task, payload.ctx)}
    except APIError as exc:
        raise _as_422(exc) from exc


@router.post("/inspect/update")
def update(request: HttpRequest, payload: TaskGraphIn):
    require_feature(request, "flows.edit")
    try:
        return {"graph": inspect.update(payload.graph, payload.task)}
    except APIError as exc:
        raise _as_422(exc) from exc


@router.post("/inspect/remove")
def remove(request: HttpRequest, payload: RemoveIn):
    require_feature(request, "flows.edit")
    try:
        return inspect.remove(payload.graph, payload.task_id)
    except APIError as exc:
        raise _as_422(exc) from exc


@router.post("/inspect/evidence")
def evidence(request: HttpRequest, payload: EvidenceIn):
    principal(request)
    try:
        return {"items": inspect.evidence(payload.graph, payload.report)}
    except APIError as exc:
        raise _as_422(exc) from exc


@router.post("/inspect/teach-pose")
def teach_pose(request: HttpRequest, payload: TeachPoseIn):
    require_feature(request, "flows.edit")
    try:
        return {"graph": inspect.teach_pose(payload.graph, payload.task_id, payload.report)}
    except APIError as exc:
        raise _as_422(exc) from exc
