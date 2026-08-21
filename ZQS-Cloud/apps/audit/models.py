"""Append-only audit trail for operator actions."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization, User


class AuditAction(models.TextChoices):
    """Stable action keys - the UI translates them, so never reword in place."""

    LOGIN = "auth.login", _("Sign in")
    LOGIN_FAILED = "auth.login_failed", _("Failed sign in")
    LOGOUT = "auth.logout", _("Sign out")
    PASSWORD_CHANGED = "auth.password_changed", _("Password changed")

    USER_CREATED = "user.created", _("User created")
    USER_UPDATED = "user.updated", _("User updated")
    MEMBER_INVITED = "member.invited", _("Member added")
    MEMBER_ROLE_CHANGED = "member.role_changed", _("Member role changed")
    MEMBER_REMOVED = "member.removed", _("Member removed")

    APIKEY_CREATED = "apikey.created", _("API key created")
    APIKEY_REVOKED = "apikey.revoked", _("API key revoked")

    ORG_CREATED = "organization.created", _("Organization created")
    ORG_UPDATED = "organization.updated", _("Organization updated")

    SITE_CREATED = "site.created", _("Site created")
    SITE_UPDATED = "site.updated", _("Site updated")
    SITE_DELETED = "site.deleted", _("Site deleted")

    DEVICE_CREATED = "device.created", _("Device registered")
    DEVICE_UPDATED = "device.updated", _("Device updated")
    DEVICE_DELETED = "device.deleted", _("Device removed")
    DEVICE_CREDENTIAL_ROTATED = "device.credential_rotated", _("Device credential rotated")
    DEVICE_COMMAND_SENT = "device.command_sent", _("Command sent to device")
    DEVICE_COMMAND_CANCELLED = "device.command_cancelled", _("Command cancelled")
    # Receiving a declaration is the device's doing and is logged as a
    # DeviceEvent; accepting or rejecting one is an operator's decision, which
    # is what this trail is for.
    DEVICE_DECLARATION_ACCEPTED = (
        "device.declaration_accepted",
        _("Device declaration accepted"),
    )
    DEVICE_DECLARATION_REJECTED = (
        "device.declaration_rejected",
        _("Device declaration rejected"),
    )
    DEVICE_SUSPENDED = "device.suspended", _("Device suspended")
    DEVICE_RETIRED = "device.retired", _("Device retired")
    DEVICE_RESTORED = "device.restored", _("Device returned to service")
    DEVICE_REJECTED = "device.rejected", _("Device rejected")
    DEVICE_REPLACED = "device.replaced", _("Device replaced")

    POLICY_UPDATED = "telemetry.policy_updated", _("Recording policy updated")
    METRIC_UPDATED = "telemetry.metric_updated", _("Metric definition updated")

    ALERT_RULE_CREATED = "alert.rule_created", _("Alert rule created")
    ALERT_RULE_UPDATED = "alert.rule_updated", _("Alert rule updated")
    ALERT_RULE_DELETED = "alert.rule_deleted", _("Alert rule deleted")
    ALERT_ACKNOWLEDGED = "alert.acknowledged", _("Alert acknowledged")
    ALERT_RESOLVED = "alert.resolved", _("Alert resolved")

    EMS_PLAN_UPDATED = "ems.plan_updated", _("Energy plan updated")
    EMS_DISPATCH = "ems.dispatch", _("Battery dispatch issued")


class AuditStatus(models.TextChoices):
    SUCCESS = "success", _("Success")
    FAILURE = "failure", _("Failure")


class AuditLog(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="audit_logs",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    # Kept denormalised so the entry survives the actor being deleted.
    actor_label = models.CharField(max_length=200, blank=True)

    action = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=AuditStatus.choices, default=AuditStatus.SUCCESS
    )

    target_type = models.CharField(max_length=40, blank=True, db_index=True)
    target_id = models.CharField(max_length=64, blank=True, db_index=True)
    target_label = models.CharField(max_length=200, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    # Sanitised request/diff payload; secrets are stripped before writing.
    payload = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["organization", "action", "-created_at"]),
            models.Index(fields=["target_type", "target_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action} {self.target_label}"
