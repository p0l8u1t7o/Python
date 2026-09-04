"""身分：整合方（API 金鑰）或使用者（Bearer 權杖）。

Principal 附在 request.auth。規則：
- X-API-Key（或 ?api_key=）等於 VISION_API_KEY → integrator（機器身分，可執行、可上鎖／解鎖，看得到所有流程）。
- Authorization: Bearer <token>（或 ?token=）→ 使用者，角色來自 UserPref.role。
- 兩者皆無 → 401。系統尚未建立任何使用者時（第一次啟動）放行為 bootstrap 管理員，讓 /auth/setup 能建帳號。

三個工廠角色（`accounts.models.ROLES`）：

===========  ========================================================================
admin        帳號、系統設定、通訊連線；含 engineer 的一切。
engineer     建立與修改流程、訓練模型、批次測試、調任何參數；含 operator 的一切。
operator     現場作業：執行、啟停連續模式、換線（切換預設配方）、只能改標了
             ``teach=True`` 的參數（`teach_only_change` 在伺服器端把關）。
===========  ========================================================================

流程的修改權**看角色不看擁有者**：工廠的心智模型是「這條線的檢測程式」，不是「某人的流程」，
工程師離職也不該讓流程變成沒人能改的孤兒。`Flow.owner` 退化成「建立者」，只用於顯示。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpRequest
from ninja.security import HttpBearer

from apps.accounts.models import DEFAULT_ROLE, ROLES, AuthToken, EngineLock
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
    def role(self) -> str:
        """機器身分與第一次啟動視為 admin；使用者看 UserPref.role（沒有 pref 時退回 is_staff）。"""
        if self.kind in ("integrator", "bootstrap"):
            return "admin"
        if self.user is None:
            return "operator"
        if self.user.is_staff:
            return "admin"
        pref = getattr(self.user, "pref", None)
        role = getattr(pref, "role", "") or DEFAULT_ROLE
        return role if role in ROLES else DEFAULT_ROLE

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_engineer(self) -> bool:
        """能改流程圖、訓練模型、調任何參數。"""
        return self.role in ("admin", "engineer")

    @property
    def name(self) -> str:
        if self.kind == "user" and self.user:
            return self.user.username
        return self.kind

    def can_edit_flow(self, flow=None) -> bool:  # noqa: ARG002 — flow 保留給日後的產線分組
        return self.is_engineer

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


def bearer_token(request: HttpRequest) -> str:
    """`Authorization: Bearer <token>` 的權杖（沒有就空字串）。"""
    header = request.headers.get("Authorization") or ""
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def authenticate(request: HttpRequest, token: str | None = None) -> Principal | None:
    """任何進入點的身分判定。

    `?token=` 是給瀏覽器 EventSource／img 標籤用的（它們沒辦法帶標頭），但**標頭一樣要通**——
    非瀏覽器的整合方（Python／C#／Node）一律送 `Authorization: Bearer`，只認 query 參數的話
    事件串流與影像會莫名其妙 401。
    """
    if _api_key_ok(request):
        return Principal(kind="integrator")
    raw = token or bearer_token(request) or request.GET.get("token") or ""
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
        return authenticate(request, bearer_token(request) or None)

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
        raise APIError("Administrator role required", code="permission_denied", status_code=403)
    return p


def require_engineer(request: HttpRequest) -> Principal:
    """建立／修改流程、訓練模型、批次測試——操作員做不了的事。"""
    p = principal(request)
    if not p.is_engineer:
        raise APIError("Engineer role required to change this", code="permission_denied", status_code=403)
    return p
