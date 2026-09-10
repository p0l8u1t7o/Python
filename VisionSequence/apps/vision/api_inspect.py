"""檢測任務清單的無狀態 API。"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema

from apps.accounts.security import principal, require_feature
from apps.core.errors import APIError, ValidationError
from apps.vision import inspect
from apps.vision.tasks import all as all_definitions

router = Router(tags=["inspect"])


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
