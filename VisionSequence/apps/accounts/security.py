"""身分：整合方（API 金鑰）或使用者（Bearer 權杖）。

Principal 附在 request.auth。規則：
- X-API-Key（或 ?api_key=）等於 VISION_API_KEY → integrator（機器身分，可執行、可上鎖／解鎖，看得到所有流程）。
- Authorization: Bearer <token>（或 ?token=）→ 使用者；is_staff 為管理員。
- 兩者皆無 → 401。系統尚未建立任何使用者時（第一次啟動）放行為 bootstrap 管理員，讓 /auth/setup 能建帳號。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpRequest
from ninja.security import HttpBearer

from apps.accounts.models import AuthToken, EngineLock
from apps.core.errors import APIError


@dataclass
class Principal:
    kind: str  # integrator | user | bootstrap
    user: User | None = None
    token: str = ""

    @property
    def is_integrator(self) -> bool:
        return self.kind == "integrator"

    @property
    def is_admin(self) -> bool:
        return self.kind in ("integrator", "bootstrap") or bool(self.user and self.user.is_staff)

    @property
    def name(self) -> str:
        if self.kind == "user" and self.user:
            return self.user.username
        return self.kind

    def can_edit_flow(self, flow) -> bool:
        return self.is_admin or (self.user is not None and flow.owner_id == self.user.id)

    def can_execute(self) -> None:
        """引擎鎖定時，只有整合方或鎖的持有者能執行。"""
        lock = EngineLock.current()
        if not lock.locked or self.is_integrator or (self.kind == "user" and self.user and lock.holder == self.user.username):
            return
        raise EngineLocked(lock)


class EngineLocked(APIError):
    status_code = 423
    code = "engine_locked"

    def __init__(self, lock: EngineLock) -> None:
        super().__init__(
            f"引擎已由 {lock.holder or '整合方'} 鎖定，目前只能編輯不能執行" + (f"：{lock.reason}" if lock.reason else ""),
            details=lock.to_dict(),
        )


def _api_key_ok(request: HttpRequest) -> bool:
    expected = settings.VISION.get("API_KEY") or ""
    if not expected:
        return False
    key = request.headers.get("X-API-Key") or request.GET.get("api_key")
    return key == expected


def authenticate(request: HttpRequest, token: str | None = None) -> Principal | None:
    if _api_key_ok(request):
        return Principal(kind="integrator")
    raw = token or request.GET.get("token") or ""
    if raw:
        user = AuthToken.resolve(raw)
        if user:
            return Principal(kind="user", user=user, token=raw)
        return None
    if not User.objects.exists():
        return Principal(kind="bootstrap")
    return None


class BearerOrApiKey(HttpBearer):
    def __call__(self, request: HttpRequest):
        header = request.headers.get("Authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        return authenticate(request, token)

    def authenticate(self, request: HttpRequest, token: str):  # pragma: no cover - __call__ 已涵蓋
        return authenticate(request, token)


auth = BearerOrApiKey()


def principal(request: HttpRequest) -> Principal:
    p = getattr(request, "auth", None)
    if not isinstance(p, Principal):
        raise APIError("未登入", code="unauthenticated", status_code=401)
    return p


def require_admin(request: HttpRequest) -> Principal:
    p = principal(request)
    if not p.is_admin:
        raise APIError("需要管理員權限", code="permission_denied", status_code=403)
    return p
