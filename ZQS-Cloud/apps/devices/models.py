"""Sites, device blueprints, devices, credentials, events and commands."""

from __future__ import annotations

import datetime as dt
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization, User
from apps.core.models import SoftDeleteModel, TimeStampedModel, UUIDPrimaryKeyModel

#: ``device_id`` becomes an MQTT topic segment, so keep it wildcard-free.
DEVICE_ID_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
    message=_(
        "Device ID must be 3-64 characters of letters, digits, '.', '_' or '-' "
        "and must not contain MQTT wildcards."
    ),
)


class DeviceCategory(models.TextChoices):
    BATTERY = "battery", _("Battery / BESS")
    PCS = "pcs", _("Power conversion system")
    PV_INVERTER = "pv_inverter", _("PV inverter")
    METER = "meter", _("Energy meter")
    EV_CHARGER = "ev_charger", _("EV charger")
    CONTROLLER = "controller", _("EMS controller")
    SENSOR = "sensor", _("Sensor")
    GATEWAY = "gateway", _("Gateway")
    OTHER = "other", _("Other")


class ConnectionStatus(models.TextChoices):
    ONLINE = "online", _("Online")
    OFFLINE = "offline", _("Offline")
    UNKNOWN = "unknown", _("Unknown")


class Site(UUIDPrimaryKeyModel, TimeStampedModel, SoftDeleteModel):
    """A physical location grouping devices - the unit shown on the map."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="sites"
    )
    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=64)
    description = models.TextField(blank=True)

    address = models.CharField(max_length=400, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2")
    postal_code = models.CharField(max_length=32, blank=True)
    latitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )

    timezone_name = models.CharField(max_length=64, default="UTC")
    contact_name = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    tags = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "devices_site"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"], name="uniq_site_org_code"
            )
        ]
        indexes = [models.Index(fields=["organization", "is_active"])]

    def __str__(self) -> str:
        return self.name

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class DeviceType(UUIDPrimaryKeyModel, TimeStampedModel):
    """Blueprint shared by devices of the same model.

    Mirrors Enapter's "blueprint" idea: the metric catalogue and the command
    catalogue live here, so adding a device model is configuration, not code.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="device_types",
        null=True,
        blank=True,
        help_text="Null means a built-in blueprint shared by all tenants.",
    )
    key = models.SlugField(max_length=80)
    name = models.CharField(max_length=200)
    category = models.CharField(
        max_length=20, choices=DeviceCategory.choices, default=DeviceCategory.OTHER
    )
    manufacturer = models.CharField(max_length=120, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=64, blank=True)

    #: [{"name": "set_power_limit", "label": {...}, "params": {json-schema},
    #:   "min_role": "operator", "confirm": true}, ...]
    command_definitions = models.JSONField(default=list, blank=True)
    #: Free-form defaults applied to new devices of this type.
    default_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "devices_device_type"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"],
                name="uniq_device_type_org_key",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(organization__isnull=True),
                name="uniq_device_type_global_key",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def command_spec(self, name: str) -> dict | None:
        for spec in self.command_definitions or []:
            if isinstance(spec, dict) and spec.get("name") == name:
                return spec
        return None


class DeviceQuerySet(models.QuerySet):
    def for_organization(self, organization) -> "DeviceQuerySet":
        return self.filter(organization=organization, deleted_at__isnull=True)

    def online(self) -> "DeviceQuerySet":
        return self.filter(status=ConnectionStatus.ONLINE)

    def stale(self, grace_seconds: int | None = None) -> "DeviceQuerySet":
        """Devices marked online but silent for longer than the grace window."""
        grace = grace_seconds or settings.DEVICE_OFFLINE_GRACE_SECONDS
        cutoff = timezone.now() - dt.timedelta(seconds=grace)
        return self.filter(status=ConnectionStatus.ONLINE).filter(
            models.Q(last_seen_at__lt=cutoff) | models.Q(last_seen_at__isnull=True)
        )


class Device(UUIDPrimaryKeyModel, TimeStampedModel, SoftDeleteModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="devices"
    )
    site = models.ForeignKey(
        Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="devices"
    )
    device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="devices",
    )

    #: Identifier the device uses on MQTT. Globally unique, not per-tenant: the
    #: topic ``energy/devices/{device_id}/...`` carries no organisation segment,
    #: so the id alone has to resolve the owner. Use a serial number or MAC.
    device_id = models.CharField(
        max_length=64, unique=True, db_index=True, validators=[DEVICE_ID_VALIDATOR]
    )
    #: Human-friendly registered name shown in the console.
    name = models.CharField(max_length=200)
    serial_number = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)

    firmware_version = models.CharField(max_length=64, blank=True)
    hardware_version = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=16, choices=ConnectionStatus.choices, default=ConnectionStatus.UNKNOWN
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    #: Last time *any* uplink arrived (telemetry, status, event).
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_telemetry_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    rssi = models.IntegerField(null=True, blank=True)

    # Location reported by the device; falls back to the site when absent.
    latitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    address = models.CharField(max_length=400, blank=True)
    location_source = models.CharField(
        max_length=16,
        blank=True,
        help_text="device | manual | site",
    )
    location_updated_at = models.DateTimeField(null=True, blank=True)

    #: Which metrics get persisted, and how often. Null falls back to the
    #: blueprint's policy, then to the organisation default.
    recording_policy = models.ForeignKey(
        "telemetry.RecordingPolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="devices",
    )

    tags = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_enabled = models.BooleanField(
        default=True, help_text="Disabled devices are ignored by the ingest pipeline."
    )

    objects = DeviceQuerySet.as_manager()

    class Meta:
        db_table = "devices_device"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "site"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.device_id})"

    @property
    def effective_location(self) -> tuple[float, float, str] | None:
        """Device-reported position wins; otherwise fall back to the site."""
        if self.latitude is not None and self.longitude is not None:
            return self.latitude, self.longitude, self.address
        if self.site and self.site.has_location:
            return self.site.latitude, self.site.longitude, self.site.address
        return None

    @property
    def is_stale(self) -> bool:
        if self.last_seen_at is None:
            return True
        age = (timezone.now() - self.last_seen_at).total_seconds()
        return age > settings.DEVICE_OFFLINE_GRACE_SECONDS

    def topic(self, suffix: str) -> str:
        root = settings.MQTT["TOPIC_ROOT"].rstrip("/")
        return f"{root}/{self.device_id}/{suffix.lstrip('/')}"


class DeviceCredential(TimeStampedModel):
    """MQTT credentials served to EMQX through the auth webhook."""

    device = models.OneToOneField(
        Device, on_delete=models.CASCADE, related_name="credential"
    )
    mqtt_username = models.CharField(max_length=128, unique=True, db_index=True)
    hashed_password = models.CharField(max_length=256)
    #: Optional pinning: EMQX rejects the connection if the client id differs.
    allowed_client_id = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    last_auth_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devices_credential"

    def __str__(self) -> str:
        return self.mqtt_username

    @classmethod
    def issue(cls, device: Device) -> tuple["DeviceCredential", str]:
        """Create or rotate the credential, returning the plaintext password."""
        password = secrets.token_urlsafe(24)
        credential, _created = cls.objects.update_or_create(
            device=device,
            defaults={
                "mqtt_username": f"dev-{device.organization.slug}-{device.device_id}"[:128],
                "hashed_password": make_password(password),
                "is_active": True,
                "rotated_at": timezone.now(),
            },
        )
        return credential, password

    def verify(self, password: str) -> bool:
        return self.is_active and check_password(password, self.hashed_password)


class DeviceStatusEvent(models.Model):
    """Connection state transitions, including MQTT last-will messages."""

    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="status_events"
    )
    status = models.CharField(max_length=16, choices=ConnectionStatus.choices)
    previous_status = models.CharField(max_length=16, blank=True)
    reason = models.CharField(max_length=64, blank=True, help_text="lwt | report | timeout")
    ts = models.DateTimeField(db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "devices_status_event"
        ordering = ["-ts"]
        indexes = [models.Index(fields=["device", "-ts"])]

    def __str__(self) -> str:
        return f"{self.device_id} -> {self.status} @ {self.ts:%Y-%m-%d %H:%M:%S}"


class EventLevel(models.TextChoices):
    DEBUG = "debug", _("Debug")
    INFO = "info", _("Info")
    NOTICE = "notice", _("Notice")
    WARNING = "warning", _("Warning")
    ERROR = "error", _("Error")
    CRITICAL = "critical", _("Critical")


class DeviceEvent(models.Model):
    """Operation / diagnostic records reported by the device itself.

    Distinct from :class:`~apps.audit.models.AuditLog` (what operators did) and
    from :class:`~apps.alerts.models.Alert` (what the rule engine concluded).
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="device_events"
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="events")
    ts = models.DateTimeField(db_index=True)
    level = models.CharField(
        max_length=16, choices=EventLevel.choices, default=EventLevel.INFO
    )
    #: Vendor error/event code, e.g. "E0231" - kept verbatim for the manual.
    code = models.CharField(max_length=64, blank=True, db_index=True)
    message = models.CharField(max_length=500, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "devices_event"
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["organization", "-ts"]),
            models.Index(fields=["device", "-ts"]),
            models.Index(fields=["device", "level", "-ts"]),
        ]

    def __str__(self) -> str:
        return f"[{self.level}] {self.code} {self.message[:40]}"


class CommandStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SENT = "sent", _("Sent")
    ACCEPTED = "accepted", _("Accepted by device")
    SUCCEEDED = "succeeded", _("Succeeded")
    REJECTED = "rejected", _("Rejected by device")
    FAILED = "failed", _("Failed")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


#: States from which no further transition is expected.
TERMINAL_COMMAND_STATUSES = frozenset(
    {
        CommandStatus.SUCCEEDED,
        CommandStatus.REJECTED,
        CommandStatus.FAILED,
        CommandStatus.EXPIRED,
        CommandStatus.CANCELLED,
    }
)


class Command(UUIDPrimaryKeyModel, TimeStampedModel):
    """A downlink control request and its lifecycle."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="commands"
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="commands")
    name = models.CharField(max_length=80, db_index=True)
    params = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=16, choices=CommandStatus.choices, default=CommandStatus.PENDING
    )
    issued_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="commands"
    )
    issued_by_label = models.CharField(max_length=200, blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    response = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True)
    #: Client-supplied key making retried submissions idempotent.
    idempotency_key = models.CharField(max_length=80, blank=True)

    class Meta:
        db_table = "devices_command"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["device", "-created_at"]),
            models.Index(fields=["status", "expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_command_idempotency",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} -> {self.device_id} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_COMMAND_STATUSES

    @property
    def is_expired(self) -> bool:
        return not self.is_terminal and self.expires_at <= timezone.now()
