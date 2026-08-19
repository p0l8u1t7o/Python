"""Uniform API error taxonomy.

Every failure the API returns carries a stable machine-readable ``code`` so the
React client can map it to a translated message instead of showing English
server text.
"""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return {"error": payload}


class ValidationError(APIError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(APIError):
    status_code = 401
    code = "unauthenticated"


class PermissionDenied(APIError):
    status_code = 403
    code = "permission_denied"


class NotFound(APIError):
    status_code = 404
    code = "not_found"


class Conflict(APIError):
    status_code = 409
    code = "conflict"


class RateLimited(APIError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(APIError):
    status_code = 503
    code = "service_unavailable"
