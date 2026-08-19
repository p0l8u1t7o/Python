"""Request-scoped context: request id, client IP, resolved language."""

from __future__ import annotations

import contextvars
import uuid
from typing import Any

# The default is None rather than {} so no caller can mutate a dict shared by
# every context that never set one; get_request_context() hands back a fresh
# empty mapping instead.
_request_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "zqs_request_context", default=None
)

REQUEST_ID_HEADER = "HTTP_X_REQUEST_ID"


def get_request_context() -> dict[str, Any]:
    return _request_context.get() or {}


def set_request_context(**values: Any) -> None:
    merged = dict(_request_context.get() or {})
    merged.update(values)
    _request_context.set(merged)


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        # Left-most entry is the original client when the proxy chain is trusted.
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.request_id = request_id
        token = _request_context.set(
            {
                "request_id": request_id,
                "ip": client_ip(request),
                "path": request.path,
                "method": request.method,
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:256],
            }
        )
        try:
            response = self.get_response(request)
        finally:
            _request_context.reset(token)
        response["X-Request-ID"] = request_id
        return response
