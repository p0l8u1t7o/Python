"""Abstract model bases reused across the domain apps."""

from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPrimaryKeyModel(models.Model):
    """UUID PKs keep device/organisation identifiers safe to expose publicly."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> "SoftDeleteQuerySet":
        return self.filter(deleted_at__isnull=False)


class SoftDeleteModel(models.Model):
    """Retains rows referenced by historical telemetry instead of hard deleting."""

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, *, save: bool = True) -> None:
        from django.utils import timezone

        self.deleted_at = timezone.now()
        if save:
            self.save(update_fields=["deleted_at"])

    def restore(self, *, save: bool = True) -> None:
        self.deleted_at = None
        if save:
            self.save(update_fields=["deleted_at"])
