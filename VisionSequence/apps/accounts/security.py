"""身分：整合方（API 金鑰）或使用者（Bearer 權杖）。

Principal 附在 request.auth。規則：
- X-API-Key（或 ?api_key=）等於 VISION_API_KEY → integrator（機器身分，可執行、可上鎖／解鎖，看得到所有流程）。
- Authorization: Bearer <token>（或 ?token=）→ 使用者，角色來自 UserPref.role。
- 兩者皆無 → 401。系統尚未建立任何使用者時（第一次啟動）放行為 bootstrap 管理員，讓 /auth/setup 能建帳號。

三個工廠角色（`accounts.models.ROLES`）：

===========  ========================================================================
admin        帳號、系統設定、角色權限；永遠全開，不可被勾掉。
engineer     預設：建立與修改流程、來源、資產、深度學習、批次、Golden、外部整合。
operator     預設：執行、啟停連續模式、換線、只能改標了 ``teach=True`` 的參數
             （`teach_only_change` 在伺服器端把關）。
===========  ========================================================================

**engineer 與 operator 能用哪些功能由管理員勾選**（`accounts.permissions`，出廠值就是上表），
所以判斷要用 `p.can("<feature>")`／`require_feature(request, "<feature>")`，不要再看角色名稱。

流程的修改權**看角色不看擁有者**：工廠的心智模型是「這條線的檢測程式」，不是「某人的流程」，
工程師離職也不該讓流程變成沒人能改的孤兒。`Flow.owner` 退化成「建立者」，只用於顯示。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpRequest
from ninja.security import HttpBearer

from apps.accounts import permissions
from apps.accounts.models import DEFAULT_ROLE, ROLES, AuthToken, EngineLock
from apps.core.errors import APIError


@dataclass
class Principal:
    kind: str  # integrator | user | bootstrap
    user: User | None = None
    token: str = ""
    #: 這個角色能用的功能，第一次問的時候才查（見 can()）。
    _features: frozenset[str] | None = None

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
        """能改流程圖——現在是「有 flows.edit 這個功能」而不是「角色叫 engineer」。"""
        return self.can("flows.edit")

    def can(self, feature: str) -> bool:
        """這個身分能不能用某個功能（`permissions.FEATURES` 的鍵）。管理員與整合方全開。

        一個請求可能問好幾次，所以查到的集合記在這個 Principal 上（`request.auth` 一個請求一個）。
        """
        if self.is_admin:
            return True
        if self._features is None:
            self._features = permissions.allowed(self.role)
        return feature in self._features

    @property
    def name(self) -> str:
        if self.kind == "user" and self.user:
            return self.user.username
        return self.kind

    def can_edit_flow(self, flow=None) -> bool:  # noqa: ARG002 — flow 保留給日後的產線分組
        return self.can("flows.edit")

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
            f"The engine is locked by {lock.holder or "an integrator"}, so editing is possible but running is not" + (f": {lock.reason}" if lock.reason else ""),
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
        raise APIError("Not signed in", code="unauthenticated", status_code=401)
    return p


def require_admin(request: HttpRequest) -> Principal:
    p = principal(request)
    if not p.is_admin:
        raise APIError("Administrator role required", code="permission_denied", status_code=403)
    return p


def require_feature(request: HttpRequest, feature: str) -> Principal:
    """這個身分要有某個功能才過（管理員永遠過）。功能鍵見 `accounts.permissions.FEATURES`。"""
    p = principal(request)
    if not p.can(feature):
        raise APIError(f"Your role is not allowed to use '{feature}'", code="permission_denied", status_code=403,
                       details={"feature": feature, "role": p.role})
    return p
