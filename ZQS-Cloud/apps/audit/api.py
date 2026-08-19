"""Read-only access to the operator audit trail."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Query, Router, Schema

from apps.accounts.security import AuthContext
from apps.audit.models import AuditAction, AuditLog, AuditStatus
from apps.core.schemas import Page, PageParams, TimeRangeParams, paginate

router = Router(tags=["audit"])


class AuditLogOut(Schema):
    id: int
    action: str
    action_label: str = ""
    status: AuditStatus
    actor_id: uuid.UUID | None = None
    actor_label: str
    target_type: str
    target_id: str
    target_label: str
    ip_address: str | None
    request_id: str
    payload: dict[str, Any]
    message: str
    created_at: dt.datetime

    @staticmethod
    def resolve_action_label(obj) -> str:
        try:
            # str() forces Django's lazy translation proxy to a real string;
            # pydantic rejects the proxy object itself.
            return str(AuditAction(obj.action).label)
        except ValueError:
            return obj.action


class AuditActionOut(Schema):
    value: str
    label: str


@router.get("", response=Page[AuditLogOut])
def list_audit_logs(
    request,
    params: Query[PageParams],
    window: Query[TimeRangeParams],
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
):
    """Operator actions, newest first. Defaults to the last 30 days."""
    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)

    queryset = AuditLog.objects.filter(
        organization=ctx.organization, created_at__gte=start, created_at__lt=end
    )
    if action:
        queryset = queryset.filter(action=action)
    if actor_id:
        queryset = queryset.filter(actor_id=actor_id)
    if target_type:
        queryset = queryset.filter(target_type=target_type)
    if target_id:
        queryset = queryset.filter(target_id=str(target_id))
    if status:
        queryset = queryset.filter(status=status)

    return paginate(queryset.order_by("-created_at"), params)


@router.get("/actions", response=list[AuditActionOut])
def list_audit_actions(request):
    """Action vocabulary, so the console can render a translated filter list."""
    return [{"value": choice.value, "label": str(choice.label)} for choice in AuditAction]


@router.get("/devices/{device_pk}", response=Page[AuditLogOut])
def device_audit_trail(
    request, device_pk: uuid.UUID, params: Query[PageParams], window: Query[TimeRangeParams]
):
    """Everything operators did to one device - the "operation record" view."""
    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)
    queryset = AuditLog.objects.filter(
        organization=ctx.organization,
        target_type="device",
        target_id=str(device_pk),
        created_at__gte=start,
        created_at__lt=end,
    ).order_by("-created_at")
    return paginate(queryset, params)
