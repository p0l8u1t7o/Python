"""Helpers for writing audit entries without cluttering the API handlers."""

from __future__ import annotations

from typing import Any

from apps.audit.models import AuditLog, AuditStatus
from apps.core.logging import get_logger
from apps.core.middleware import get_request_context

logger = get_logger("audit")

#: Keys whose values must never reach the audit table.
_SENSITIVE_KEYS = {
    "password",
    "new_password",
    "current_password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "hashed_secret",
    "private_key",
    "mqtt_password",
}
_REDACTED = "***"


def sanitize(payload: Any, *, _depth: int = 0) -> Any:
    if _depth > 6:
        return "<truncated>"
    if isinstance(payload, dict):
        return {
            key: (
                _REDACTED
                if key.lower() in _SENSITIVE_KEYS
                else sanitize(value, _depth=_depth + 1)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [sanitize(item, _depth=_depth + 1) for item in payload[:100]]
    if isinstance(payload, (str, int, float, bool)) or payload is None:
        return payload
    return str(payload)


def record(
    action: str,
    *,
    ctx=None,
    organization=None,
    actor=None,
    target=None,
    target_type: str = "",
    target_id: str = "",
    target_label: str = "",
    status: str = AuditStatus.SUCCESS,
    payload: Any = None,
    message: str = "",
) -> AuditLog:
    """Write one audit row.

    ``ctx`` is an :class:`~apps.accounts.security.AuthContext`; when supplied it
    fills in organisation and actor. ``target`` may be any model instance - its
    class name and pk are recorded.
    """
    request_context = get_request_context()

    if ctx is not None:
        organization = organization or ctx.organization
        actor = actor or ctx.user
        if not target_label and ctx.is_service:
            message = message or f"via API key {ctx.api_key.name}"

    if target is not None:
        target_type = target_type or target.__class__.__name__.lower()
        target_id = target_id or str(getattr(target, "pk", ""))
        target_label = target_label or str(target)[:200]

    actor_label = ""
    if actor is not None:
        actor_label = getattr(actor, "email", "") or str(actor)
    elif ctx is not None:
        actor_label = ctx.principal_label

    entry = AuditLog.objects.create(
        organization=organization,
        actor=actor,
        actor_label=actor_label[:200],
        action=action,
        status=status,
        target_type=target_type[:40],
        target_id=target_id[:64],
        target_label=target_label[:200],
        ip_address=request_context.get("ip") or None,
        user_agent=(request_context.get("user_agent") or "")[:256],
        request_id=(request_context.get("request_id") or "")[:64],
        payload=sanitize(payload) if payload is not None else {},
        message=message[:500],
    )
    logger.info(
        "audit %s", action, extra={"action": action, "target": target_label, "status": status}
    )
    return entry


def record_failure(action: str, message: str, **kwargs) -> AuditLog:
    return record(action, status=AuditStatus.FAILURE, message=message, **kwargs)
