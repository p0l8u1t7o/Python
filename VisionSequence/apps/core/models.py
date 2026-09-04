"""Audit trail: who changed what, when.

Nothing in the platform used to answer "yesterday the yield was fine, today it is 80% — did somebody
touch a threshold?". Twenty-two models and not one of them recorded a change. Regulated customers
(IATF 16949, medical) rule a system out on that alone, and even an ordinary 8D needs it.

Rows are written by explicit calls from the endpoints that mutate something (`apps.core.audit`),
not by middleware magic: the point is to record **meaningful actions**, not HTTP traffic.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    #: user | integrator | bootstrap — an API key has no user row but is still an actor.
    actor_kind = models.CharField(max_length=16, default="user")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    #: Kept as text so the trail survives the account being deleted.
    actor_name = models.CharField(max_length=150, blank=True, default="")
    #: Dotted verb: flow.update, recipe.activate, user.role, lock.acquire…
    action = models.CharField(max_length=40, db_index=True)
    target_type = models.CharField(max_length=24, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    #: Name at the time of the change; the object may be renamed or deleted later.
    target_name = models.CharField(max_length=160, blank=True, default="")
    #: One readable line — "threshold 60 → 46, +1 step".
    summary = models.CharField(max_length=400, blank=True, default="")
    #: Structured detail (parameter diff, before/after fields). Clipped before storing.
    detail = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id", "-at"]),
            models.Index(fields=["actor", "-at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"
