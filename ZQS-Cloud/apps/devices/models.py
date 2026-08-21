"""Sites, device blueprints, devices, credentials, events and commands."""

from __future__ import annotations

import datetime as dt
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError as DjangoValidationError
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
    LOAD = "load", _("Electrical load")
    GENERATOR = "generator", _("Backup generator")
    EV_CHARGER = "ev_charger", _("EV charger")
    CONTROLLER = "controller", _("EMS controller")
    SENSOR = "sensor", _("Sensor")
    GATEWAY = "gateway", _("Gateway")
    OTHER = "other", _("Other")


#: Capability defaults per category, applied to built-in blueprints by
#: ``manage.py bootstrap``. Order: can_charge, can_discharge, can_export,
#: is_dispatchable.
#:
#: A load is *not* metering-only even though all four are false for a passive
#: one: "can it be commanded" and "what is it" are different axes. Use
#: :func:`is_metering_only` for the second question.
CATEGORY_CAPABILITIES: dict[str, tuple[bool, bool, bool, bool]] = {
    DeviceCategory.BATTERY: (True, True, True, True),
    DeviceCategory.PCS: (True, True, True, True),
    DeviceCategory.PV_INVERTER: (False, True, True, True),
    DeviceCategory.GENERATOR: (False, True, False, True),
    DeviceCategory.EV_CHARGER: (True, False, False, True),
    DeviceCategory.METER: (False, False, False, False),
    DeviceCategory.SENSOR: (False, False, False, False),
    DeviceCategory.LOAD: (False, False, False, False),
    DeviceCategory.CONTROLLER: (False, False, False, True),
    DeviceCategory.GATEWAY: (False, False, False, True),
    DeviceCategory.OTHER: (False, False, False, True),
}

#: The four capability flags, in the order used throughout.
CAPABILITY_FIELDS = ("can_charge", "can_discharge", "can_export", "is_dispatchable")


def is_metering_only(category: str) -> bool:
    """Whether a category exists purely to report readings.

    Decided by category, never by the capability flags. A passive light circuit
    has all four flags false and is still a *load*, not a meter - the flags
    answer "can it be commanded", not "what is it".
    """
    return category in {DeviceCategory.METER, DeviceCategory.SENSOR}


class CapabilitySource(models.TextChoices):
    """Where a device's effective capabilities came from.

    Mirrors ``Device.location_source``: what the device claimed and what the
    platform accepted are different things, and the difference is recorded.
    """

    BLUEPRINT = "blueprint", _("Inherited from the blueprint")
    MANUAL = "manual", _("Set by an operator")
    DEVICE = "device", _("Accepted from the device's declaration")


class LifecycleState(models.TextChoices):
    """Where a device is in its working life.

    Operating policy: **a device's category never changes.** When the hardware
    is genuinely replaced by something different, a *new* device is registered
    and the old one is retired - the old row is never edited into the new
    thing. That keeps every historical figure attributable to the equipment
    that actually produced it.

    ``is_enabled`` stays as the ingest switch it always was, but it is no
    longer set by hand: :func:`apps.devices.services.set_lifecycle` keeps the
    two in step so there is one decision, not two.
    """

    PENDING = "pending", _("Pending commissioning")
    ACTIVE = "active", _("Active")
    SUSPENDED = "suspended", _("Suspended")
    RETIRED = "retired", _("Retired")
    REJECTED = "rejected", _("Rejected")


#: States in which the ingest pipeline still accepts the device's data.
#: A pending device must keep reporting - an operator needs to see what it
#: actually sends before deciding what it is.
INGESTING_STATES = frozenset({LifecycleState.PENDING, LifecycleState.ACTIVE})

#: States that accept dispatch commands.
COMMANDABLE_STATES = frozenset({LifecycleState.ACTIVE})


class ConnectionStatus(models.TextChoices):
    ONLINE = "online", _("Online")
    OFFLINE = "offline", _("Offline")
    UNKNOWN = "unknown", _("Unknown")


class SiteKind(models.TextChoices):
    """What a node in the site tree represents. Presentation only.

    Nothing in the aggregation logic branches on this - a plant and a
    production line roll up identically. It exists so the console can pick an
    icon and so an operator can tell "Taoyuan plant" from "Line 3" at a glance.
    """

    SITE = "site", _("Site / plant")
    AREA = "area", _("Area / workshop")
    LINE = "line", _("Production line")
    GROUP = "group", _("Logical group")


#: How deep the tree may go, counting the root as depth 0. The limit is what
#: lets descendant lookups run as a bounded number of plain queries instead of
#: a recursive CTE, which SQLite and PostgreSQL spell differently.
MAX_SITE_DEPTH = 5


class Site(UUIDPrimaryKeyModel, TimeStampedModel, SoftDeleteModel):
    """A location grouping devices - the unit shown on the map.

    Sites nest: ``Taoyuan plant -> Workshop 1 -> Line 3``. The tree is only a
    grouping device; every energy object (assets, storage plan, intervals)
    still hangs off one specific site, so a parent's figures are always the sum
    of its subtree rather than a separate measurement.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="sites"
    )
    #: PROTECT, not CASCADE: deleting a plant must never silently take its
    #: workshops - and their devices' history - with it. The API refuses the
    #: delete while children exist.
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    kind = models.CharField(
        max_length=16, choices=SiteKind.choices, default=SiteKind.SITE
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
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["organization", "parent"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    # ---- Tree ------------------------------------------------------------
    def ancestors(self) -> list["Site"]:
        """Root-first chain above this site.

        Walks with a visited set rather than trusting the data: a cycle that
        somehow reached the database - a restored dump, a manual UPDATE - must
        not turn every page that renders a breadcrumb into an infinite loop.
        """
        chain: list[Site] = []
        seen = {self.pk}
        node = self.parent
        while node is not None and node.pk not in seen:
            chain.append(node)
            seen.add(node.pk)
            node = node.parent
        chain.reverse()
        return chain

    @property
    def depth(self) -> int:
        """Levels above this site.

        Computing it walks the parent chain one query at a time, which is fine
        for a single site but not for a page of them - so a caller that has
        already loaded the tree can fill ``_depth_cache`` and skip the walk.
        """
        cached = getattr(self, "_depth_cache", None)
        return cached if cached is not None else len(self.ancestors())

    def validate_parent(self, parent: "Site | None") -> None:
        """Reject a parent that would create a cycle or exceed the depth cap.

        Raises :class:`django.core.exceptions.ValidationError`; the API layer
        turns that into its own error type.
        """
        if parent is None:
            return
        if self.pk is not None and parent.pk == self.pk:
            raise DjangoValidationError(
                "A site cannot be its own parent.", code="parent_self"
            )
        if parent.organization_id != self.organization_id:
            raise DjangoValidationError(
                "Parent site belongs to another organization.",
                code="parent_foreign_org",
            )
        if parent.deleted_at is not None:
            raise DjangoValidationError(
                "Parent site has been deleted.", code="parent_deleted"
            )

        chain = [parent, *reversed(parent.ancestors())]
        if self.pk is not None and any(node.pk == self.pk for node in chain):
            raise DjangoValidationError(
                "That would create a cycle in the site tree.",
                code="parent_cycle",
            )

        # Depth of the parent, plus this node, plus whatever already hangs off
        # it - moving a subtree must not push its leaves past the cap.
        new_depth = len(parent.ancestors()) + 1
        if new_depth + self._subtree_height() > MAX_SITE_DEPTH:
            raise DjangoValidationError(
                f"Site nesting is limited to {MAX_SITE_DEPTH + 1} levels.",
                code="parent_too_deep",
            )

    def _subtree_height(self) -> int:
        """0 for a leaf, 1 if it has children, and so on."""
        if self.pk is None:
            return 0
        height = 0
        frontier = [self.pk]
        while frontier and height < MAX_SITE_DEPTH + 1:
            frontier = list(
                Site.objects.filter(
                    parent_id__in=frontier, deleted_at__isnull=True
                ).values_list("pk", flat=True)
            )
            if frontier:
                height += 1
        return height


def descendant_site_ids(
    site_ids, *, organization=None, include_self: bool = True
) -> list:
    """Expand site ids to include everything below them in the tree.

    Breadth-first, one query per level, capped by :data:`MAX_SITE_DEPTH` - so
    the worst case is a handful of small queries and a cycle in the data cannot
    hang the request. Soft-deleted sites are excluded.
    """
    roots = [pk for pk in site_ids if pk is not None]
    if not roots:
        return []

    collected: list = list(roots) if include_self else []
    seen = set(roots)
    frontier = roots

    for _level in range(MAX_SITE_DEPTH + 1):
        queryset = Site.objects.filter(
            parent_id__in=frontier, deleted_at__isnull=True
        )
        if organization is not None:
            queryset = queryset.filter(organization=organization)
        children = [pk for pk in queryset.values_list("pk", flat=True) if pk not in seen]
        if not children:
            break
        collected.extend(children)
        seen.update(children)
        frontier = children

    return collected


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

    # ---- Capability defaults for this model ------------------------------
    #: What the *model* can do. Individual units may differ - a PCS commissioned
    #: without a charging contactor, a battery bank kept backup-only by
    #: contract - so ``Device`` carries nullable overrides.
    can_charge = models.BooleanField(default=False)
    can_discharge = models.BooleanField(default=False)
    can_export = models.BooleanField(
        default=False, help_text="May push power back towards the grid."
    )
    is_dispatchable = models.BooleanField(
        default=True, help_text="Accepts control commands at all. False for meters."
    )

    #: [{"name": "set_power_limit", "label": {...}, "params": {json-schema},
    #:   "min_role": "operator", "confirm": true, "kind": "dispatch"}, ...]
    #:
    #: ``kind`` marks energy-dispatch commands. ``is_dispatchable=False`` blocks
    #: those but still allows housekeeping like ``set_report_interval``, which a
    #: meter legitimately accepts.
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

    # ---- Capabilities ----------------------------------------------------
    #: Null means "inherit the blueprint". Set only by an operator, or by an
    #: operator *accepting* a device declaration - never by the device itself.
    #: Everything that decides whether a command may run reads these, and only
    #: these; see :func:`effective_capabilities`.
    can_charge = models.BooleanField(null=True, blank=True)
    can_discharge = models.BooleanField(null=True, blank=True)
    can_export = models.BooleanField(null=True, blank=True)
    is_dispatchable = models.BooleanField(null=True, blank=True)
    capability_source = models.CharField(
        max_length=16,
        choices=CapabilitySource.choices,
        default=CapabilitySource.BLUEPRINT,
    )

    #: Lifecycle state. Auto-provisioned devices land in ``pending``: telemetry
    #: is accepted so an operator can see what the thing actually reports, but
    #: dispatch commands are refused until someone confirms it. Deliberately
    #: not ``is_enabled``, which would drop the telemetry and leave nothing to
    #: judge by.
    #:
    #: Retirement never soft-deletes. A retired device stays visible in the API
    #: and its history stays readable; it simply cannot connect or be commanded.
    commissioning_state = models.CharField(
        max_length=16,
        choices=LifecycleState.choices,
        default=LifecycleState.ACTIVE,
        db_index=True,
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    #: The device that took over this one's job. Set when a replacement is
    #: registered; SET_NULL so removing the successor never erases the
    #: predecessor's history.
    replaced_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
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

    # ---- Capabilities ----------------------------------------------------
    def effective_capabilities(self) -> dict[str, bool]:
        """The capabilities control decisions are allowed to consult.

        Resolution order: the device's own override, else the blueprint, else
        permissive. A device with no blueprint has nothing to check against, so
        it stays permissive rather than silently becoming uncontrollable - but
        the console shows "no blueprint, capabilities unchecked" so the gap is
        visible instead of surprising.

        This never reads :class:`DeviceDeclaration`. What a device claims about
        itself is a hint for an operator, not an input to a safety check.
        """
        blueprint = self.device_type
        resolved: dict[str, bool] = {}
        for field in CAPABILITY_FIELDS:
            own = getattr(self, field)
            if own is not None:
                resolved[field] = own
            elif blueprint is not None:
                resolved[field] = getattr(blueprint, field)
            else:
                resolved[field] = True
        return resolved

    @property
    def is_metering_only(self) -> bool:
        return bool(
            self.device_type_id and is_metering_only(self.device_type.category)
        )

    # ---- Lifecycle -------------------------------------------------------
    @property
    def is_retired(self) -> bool:
        return self.commissioning_state == LifecycleState.RETIRED

    def replacement_chain(self) -> list["Device"]:
        """This device and every one that succeeded it, oldest first.

        Walks with a visited set: a cycle that reached the database must not
        turn a report into an infinite loop.
        """
        chain: list[Device] = [self]
        seen = {self.pk}
        node = self.replaced_by
        while node is not None and node.pk not in seen:
            chain.append(node)
            seen.add(node.pk)
            node = node.replaced_by
        return chain

    def replacement_root(self) -> "Device":
        """The oldest device in this replacement chain."""
        node, seen = self, {self.pk}
        while True:
            predecessor = node.supersedes.first()
            if predecessor is None or predecessor.pk in seen:
                return node
            seen.add(predecessor.pk)
            node = predecessor


def chain_segments(device: Device) -> list[tuple[Device, "dt.datetime | None", "dt.datetime | None"]]:
    """Split a replacement chain into non-overlapping time windows.

    Returns ``(device, valid_from, valid_until)`` oldest first, where
    ``valid_until`` is the device's ``retired_at`` and ``valid_from`` is the
    predecessor's. Both ends may be ``None``, meaning unbounded.

    The windows exist to stop a stitched report double counting. Hardware often
    keeps reporting after it is retired - left powered on the bench, or simply
    slow to be unplugged - so the two devices' samples overlap in wall-clock
    time even though only one was the site's equipment at any given moment.
    Adding those overlaps would inflate energy and, worse, invent a peak that
    never happened.
    """
    segments: list[tuple[Device, dt.datetime | None, dt.datetime | None]] = []
    previous_end: dt.datetime | None = None
    for node in device.replacement_chain():
        segments.append((node, previous_end, node.retired_at))
        previous_end = node.retired_at
    return segments

    def topic(self, suffix: str) -> str:
        root = settings.MQTT["TOPIC_ROOT"].rstrip("/")
        return f"{root}/{self.device_id}/{suffix.lstrip('/')}"


class DeclarationState(models.TextChoices):
    """How a device's own account of itself compares with the register.

    Under the "a device's category never changes" policy a declaration is no
    longer a change proposal waiting to be approved - the answer to "this unit
    says it is something else now" is to register a replacement, not to edit
    the existing row. So the states describe agreement, not approval.
    """

    MATCHED = "matched", _("Matches the register")
    MISMATCHED = "mismatched", _("Differs from the register")
    ACKNOWLEDGED = "acknowledged", _("Difference acknowledged")


#: Highest ``attributes.schema_version`` the server understands.
DECLARATION_SCHEMA_VERSION = 1


class DeviceDeclaration(TimeStampedModel):
    """What a device says about itself. Untrusted, by construction.

    Kept in its own table rather than as ``declared_*`` columns on
    :class:`Device` for one reason above the others: it makes the trust
    boundary impossible to cross by accident. Whatever decides whether a
    command may run is handed a ``Device``, and a ``Device`` simply has no
    field carrying a device's own claims. Parallel columns would differ by one
    underscore, which is not a difference a code review reliably catches.

    A device with valid credentials can therefore claim anything it likes. The
    worst it achieves is a misleading hint next to a review button.
    """

    device = models.OneToOneField(
        Device, on_delete=models.CASCADE, related_name="declaration"
    )
    #: The ``attributes`` object exactly as received.
    payload = models.JSONField(default=dict, blank=True)
    schema_version = models.PositiveSmallIntegerField(default=0)
    received_at = models.DateTimeField()
    state = models.CharField(
        max_length=16,
        choices=DeclarationState.choices,
        default=DeclarationState.MATCHED,
    )
    #: {"can_charge": {"declared": true, "effective": false}, ...}
    diff_summary = models.JSONField(default=dict, blank=True)
    #: The declared category differs from the registered blueprint's. Treated
    #: far more seriously than a capability difference: it means the equipment
    #: on the wire is probably not the equipment on file, so dispatch commands
    #: are frozen until a replacement is registered. Acknowledging the
    #: difference silences the banner; it does **not** lift the freeze.
    identity_mismatch = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devices_declaration"
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["state", "-received_at"])]

    def __str__(self) -> str:
        return f"{self.device_id} declaration [{self.state}]"

    @property
    def has_differences(self) -> bool:
        return bool(self.diff_summary)

    @property
    def freezes_commands(self) -> bool:
        return self.identity_mismatch


#: Declared fields that map onto an effective capability, and the payload path
#: they arrive under.
DECLARED_CAPABILITY_PATH = "capabilities"
DECLARED_RATING_PATH = "ratings"


def declaration_diff(device: Device, attributes: dict) -> dict:
    """Where a declaration disagrees with what the platform currently holds.

    Only fields that influence a control or costing decision are compared.
    Descriptive ones - firmware, IP, signal strength - are already updated
    automatically and are not worth an operator's attention.
    """
    diff: dict[str, dict] = {}
    effective = device.effective_capabilities()

    declared_capabilities = attributes.get(DECLARED_CAPABILITY_PATH) or {}
    for field in CAPABILITY_FIELDS:
        if field not in declared_capabilities:
            continue
        claimed = bool(declared_capabilities[field])
        if claimed != effective[field]:
            diff[field] = {"declared": claimed, "effective": effective[field]}

    category = attributes.get("category")
    if category and device.device_type_id and category != device.device_type.category:
        diff["category"] = {
            "declared": category,
            "effective": device.device_type.category,
        }

    return diff


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
