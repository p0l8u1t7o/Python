"""帳號：沿用 django.contrib.auth 的 User（is_staff = 管理員），外加不透明的存取權杖。

權杖是隨機 48 字元字串，資料庫只存 SHA-256；瀏覽器放 localStorage、每次請求帶
Authorization: Bearer。<img>／EventSource 帶不了 header，所以也接受 ?token=。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


#: 工廠角色。admin＝系統與帳號；engineer＝建流程、訓練模型、調任何參數；
#: operator＝現場作業（執行、換線、只能動標了 teach 的參數）。
ROLES = ("admin", "engineer", "operator")
DEFAULT_ROLE = "engineer"


class UserPref(models.Model):
    """每個使用者的介面偏好（主題風格等）與角色；OneToOne 掛在 auth.User 上，不動內建資料表。

    ui 是小型 JSON（目前只有 theme）；前端登入後套用、切換時 PATCH /auth/prefs 回寫。
    role 放在這裡而不是另開一張表：權限判定每個請求都要用，跟著 token 的 select_related 一起撈。
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="pref")
    #: admin 與 User.is_staff 保持同步（Django admin 與既有工具還在看 is_staff）。
    role = models.CharField(max_length=16, default=DEFAULT_ROLE, choices=[(r, r) for r in ROLES])
    ui = models.JSONField(default=dict, blank=True)
    #: AI 助手供應商設定 {provider, model, api_key}；金鑰只在伺服器，API 只回尾碼提示，不進 /auth/me。
    agent = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class RolePermission(models.Model):
    """一個角色能用哪些功能（`accounts.permissions.FEATURES` 的鍵）。

    沒有這一列的角色用出廠值（`permissions.defaults`），所以升級後的行為與升級前一樣；
    管理員永遠全開，不會有列。
    """

    role = models.CharField(max_length=16, unique=True)
    features = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.role}: {len(self.features or [])}"


class AuthToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True, default="")

    @classmethod
    def issue(cls, user: User, *, user_agent: str = "") -> str:
        raw = secrets.token_urlsafe(36)
        ttl = int(getattr(settings, "AUTH_TOKEN_TTL_HOURS", 24 * 14))
        cls.objects.create(user=user, token_hash=hash_token(raw), expires_at=timezone.now() + timedelta(hours=ttl), user_agent=user_agent[:200])
        return raw

    @classmethod
    def resolve(cls, raw: str) -> User | None:
        if not raw:
            return None
        row = cls.objects.select_related("user", "user__pref").filter(token_hash=hash_token(raw), expires_at__gt=timezone.now()).first()
        if row is None or not row.user.is_active:
            return None
        # 最後使用時間每 5 分鐘更新一次就好，不要每個請求都寫。
        now = timezone.now()
        if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 300:
            cls.objects.filter(pk=row.pk).update(last_used_at=now)
        return row.user

    @classmethod
    def revoke(cls, raw: str) -> None:
        cls.objects.filter(token_hash=hash_token(raw)).delete()


class EngineLock(models.Model):
    """引擎執行鎖（單一列 id=1）。

    整合方（API 金鑰）或管理員鎖定後，其他使用者只能編輯流程、不能執行（試跑／執行一次／連續）；
    整合方自己的 API / TCP 觸發不受影響。expires_at 可選：整合方忘了解鎖時自動釋放。
    """

    locked = models.BooleanField(default=False)
    holder = models.CharField(max_length=120, blank=True, default="")  # "integrator" 或使用者名稱
    reason = models.CharField(max_length=300, blank=True, default="")
    locked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def current(cls) -> "EngineLock":
        row, _ = cls.objects.get_or_create(pk=1)
        if row.locked and row.expires_at and row.expires_at <= timezone.now():
            row.locked, row.holder, row.reason, row.locked_at, row.expires_at = False, "", "", None, None
            row.save()
        return row

    def acquire(self, holder: str, reason: str = "", ttl_s: int | None = None) -> "EngineLock":
        """上鎖並停掉所有連續執行（硬體要留給鎖的持有者）；HTTP 與 TCP 共用同一條路。"""
        from apps.vision.runner import bus, runner

        self.locked = True
        self.holder = holder
        self.reason = (reason or "")[:300]
        self.locked_at = timezone.now()
        self.expires_at = timezone.now() + timedelta(seconds=int(ttl_s)) if ttl_s else None
        self.save()
        for fid in list(runner._runtimes):  # noqa: SLF001
            if runner.is_continuous(fid):
                runner.stop_continuous(fid)
        bus.publish({"type": "lock", "lock": self.to_dict()})
        return self

    def release(self) -> "EngineLock":
        from apps.vision.runner import bus

        self.locked, self.holder, self.reason, self.locked_at, self.expires_at = False, "", "", None, None
        self.save()
        bus.publish({"type": "lock", "lock": self.to_dict()})
        return self

    def to_dict(self) -> dict:
        return {
            "locked": self.locked,
            "holder": self.holder,
            "reason": self.reason,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
