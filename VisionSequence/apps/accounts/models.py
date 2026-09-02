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


class UserPref(models.Model):
    """每個使用者的介面偏好（主題風格等）；OneToOne 掛在 auth.User 上，不動內建資料表。

    ui 是小型 JSON（目前只有 theme）；前端登入後套用、切換時 PATCH /auth/prefs 回寫。
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="pref")
    ui = models.JSONField(default=dict, blank=True)
    #: AI 助手供應商設定 {provider, model, api_key}；金鑰只在伺服器，API 只回尾碼提示，不進 /auth/me。
    agent = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


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
        row = cls.objects.select_related("user").filter(token_hash=hash_token(raw), expires_at__gt=timezone.now()).first()
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

    def to_dict(self) -> dict:
        return {
            "locked": self.locked,
            "holder": self.holder,
            "reason": self.reason,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
