from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Field, FilterSchema, Schema

from apps.devices.models import (
    CommandStatus,
    ConnectionStatus,
    DeviceCategory,
    EventLevel,
    SiteKind,
)


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------
class SiteIn(Schema):
    name: str = Field(max_length=200)
    code: str = Field(max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    #: Parent in the site tree; null makes this a top-level site.
    parent_id: uuid.UUID | None = None
    kind: SiteKind = SiteKind.SITE
    description: str = ""
    address: str = Field(default="", max_length=400)
    city: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=2)
    postal_code: str = Field(default="", max_length=32)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    #: Blank takes ``SITE_DEFAULT_TIMEZONE`` (see ``create_site``).
    timezone_name: str = ""
    contact_name: str = Field(default="", max_length=120)
    contact_phone: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list)


class SiteUpdateIn(Schema):
    name: str | None = Field(default=None, max_length=200)
    #: Send ``null`` explicitly to detach a site and make it top-level; the
    #: endpoint distinguishes "field omitted" from "field set to null".
    parent_id: uuid.UUID | None = None
    kind: SiteKind | None = None
    description: str | None = None
    address: str | None = Field(default=None, max_length=400)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=2)
    postal_code: str | None = Field(default=None, max_length=32)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone_name: str | None = Field(default=None, max_length=64)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=40)
    tags: list[str] | None = None
    is_active: bool | None = None


class SiteOut(Schema):
    id: uuid.UUID
    name: str
    code: str
    parent_id: uuid.UUID | None = None
    kind: SiteKind = SiteKind.SITE
    #: 0 for a top-level site, 1 for its children, and so on.
    depth: int = 0
    child_count: int = 0
    description: str
    address: str
    city: str
    region: str
    country: str
    postal_code: str
    latitude: float | None
    longitude: float | None
    timezone_name: str
    contact_name: str
    contact_phone: str
    tags: list[str]
    is_active: bool
    created_at: dt.datetime


class SiteSummaryOut(SiteOut):
    #: Devices assigned to this site itself.
    device_count: int = 0
    online_count: int = 0
    open_alert_count: int = 0
    #: The same counts including every descendant site. Identical to the plain
    #: counts unless the request asked for ``include_descendants``, so an older
    #: client that ignores these fields keeps seeing what it always saw.
    total_device_count: int = 0
    total_online_count: int = 0
    total_open_alert_count: int = 0


class SiteDeviceRollupOut(Schema):
    total: int = 0
    online: int = 0
    offline: int = 0
    unknown: int = 0
    disabled: int = 0
    #: Enabled devices that have not reported inside the offline grace window.
    stale: int = 0


class SiteAlertRollupOut(Schema):
    open: int = 0
    critical: int = 0
    major: int = 0
    acknowledged: int = 0


class SiteRollupOut(Schema):
    """Everything one node of the site tree adds up to."""

    site_id: uuid.UUID
    site_name: str
    kind: SiteKind = SiteKind.SITE
    depth: int = 0
    include_descendants: bool = False
    #: Sites folded into these figures, this one first.
    site_ids: list[uuid.UUID] = Field(default_factory=list)
    site_count: int = 1
    child_count: int = 0
    devices: SiteDeviceRollupOut
    alerts: SiteAlertRollupOut
    #: Null when no site in the subtree has energy intervals in the window.
    energy: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Blueprints
# --------------------------------------------------------------------------
class DeviceTypeIn(Schema):
    key: str = Field(max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(max_length=200)
    category: DeviceCategory = DeviceCategory.OTHER
    manufacturer: str = Field(default="", max_length=120)
    model_name: str = Field(default="", max_length=120)
    description: str = ""
    #: {"zh-hant": {"name": "...", "description": "..."}}
    translations: dict[str, Any] = Field(default_factory=dict)
    icon: str = Field(default="", max_length=64)
    command_definitions: list[dict[str, Any]] = Field(default_factory=list)
    default_metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceTypeOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    #: ``name`` and ``description`` in the caller's language, falling back to
    #: the stored English. The raw fields stay, so an editor round-trips.
    label: str = ""
    description_text: str = ""
    category: DeviceCategory
    manufacturer: str
    model_name: str
    description: str
    translations: dict[str, Any] = Field(default_factory=dict)
    icon: str
    command_definitions: list[dict[str, Any]]
    #: Null for the built-in blueprints shared by every tenant.
    organization_id: uuid.UUID | None = None
    created_at: dt.datetime


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------
class DeviceCostIn(Schema):
    """What this unit cost to buy and to keep. All optional.

    On the device rather than the blueprint because it is a commercial fact
    about *this purchase* - the same model bought under two contracts cost
    different amounts.
    """

    capital_cost: float | None = Field(default=None, ge=0)
    #: Empty, not null: the column is a blank-able CharField, and a null would
    #: fail at the database rather than at validation.
    cost_currency: str = Field(default="", max_length=8)
    commissioned_on: dt.date | None = None
    expected_life_years: float | None = Field(default=None, gt=0, le=100)
    annual_maintenance_cost: float | None = Field(default=None, ge=0)


class DeviceIn(DeviceCostIn):
    device_id: str = Field(
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
        description=(
            "Sparkplug device_id - the fifth topic level. Unique within its "
            "edge node, not globally."
        ),
    )
    name: str = Field(max_length=200)
    #: The gateway this device reports through. Omit when the device speaks
    #: MQTT itself, and an edge node carrying just this device is created for
    #: it - registering stays one call either way.
    edge_node_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    device_type_id: uuid.UUID | None = None
    recording_policy_id: uuid.UUID | None = None
    #: Unique within the organisation when given; blank is allowed and is not
    #: compared, because a serial is often unknown at commissioning.
    serial_number: str = Field(default="", max_length=120)
    description: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: str = Field(default="", max_length=400)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class DeviceUpdateIn(DeviceCostIn):
    name: str | None = Field(default=None, max_length=200)
    site_id: uuid.UUID | None = None
    device_type_id: uuid.UUID | None = None
    recording_policy_id: uuid.UUID | None = None
    serial_number: str | None = Field(default=None, max_length=120)
    description: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=400)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    is_enabled: bool | None = None


class DeviceCapabilitiesOut(Schema):
    """Effective capabilities - blueprint defaults with device overrides.

    These are what the command gate consults. A device's own declaration never
    appears here; see ``GET /devices/{id}/declaration`` for that.
    """

    can_charge: bool = True
    can_discharge: bool = True
    can_export: bool = True
    is_dispatchable: bool = True


class DeviceOut(Schema):
    id: uuid.UUID
    device_id: str
    name: str
    description: str
    serial_number: str
    status: ConnectionStatus
    status_changed_at: dt.datetime | None
    last_seen_at: dt.datetime | None
    last_telemetry_at: dt.datetime | None
    firmware_version: str
    hardware_version: str
    ip_address: str | None
    rssi: int | None
    latitude: float | None
    longitude: float | None
    address: str
    location_source: str
    tags: list[str]
    metadata: dict[str, Any]
    is_enabled: bool
    created_at: dt.datetime

    site_id: uuid.UUID | None = None
    site_name: str | None = None
    device_type_id: uuid.UUID | None = None
    device_type_name: str | None = None
    device_category: str = ""
    recording_policy_id: uuid.UUID | None = None

    # ---- Sparkplug address ----------------------------------------------
    edge_node_id: uuid.UUID | None = None
    edge_node_name: str = ""
    #: True when the node exists only to carry this device, which is what the
    #: console uses to decide whether the gateway is worth showing at all.
    edge_node_is_implicit: bool = True
    #: ``group_id/edge_node_id/device_id`` - the address on the broker.
    sparkplug_address: str = ""

    @staticmethod
    def resolve_edge_node_name(obj) -> str:
        return obj.edge_node.name if obj.edge_node_id else ""

    @staticmethod
    def resolve_edge_node_is_implicit(obj) -> bool:
        return bool(obj.edge_node.is_implicit) if obj.edge_node_id else True

    @staticmethod
    def resolve_sparkplug_address(obj) -> str:
        return obj.sparkplug_address if obj.edge_node_id else ""

    # ---- Investment ------------------------------------------------------
    capital_cost: float | None = None
    cost_currency: str = ""
    commissioned_on: dt.date | None = None
    expected_life_years: float | None = None
    annual_maintenance_cost: float | None = None
    #: Capital amortised straight-line plus yearly upkeep. Null when nothing
    #: was recorded - deliberately not zero, which would read as "free".
    annual_cost: float | None = None

    #: What the platform accepted, not what the device claims.
    capabilities: DeviceCapabilitiesOut = Field(default_factory=DeviceCapabilitiesOut)
    capability_source: str = "blueprint"
    #: pending | active | suspended | retired | rejected
    commissioning_state: str = "active"
    retired_at: dt.datetime | None = None
    replaced_by_id: uuid.UUID | None = None
    #: The device is declaring a different category than it is registered as,
    #: so dispatch commands are frozen until a replacement is registered.
    identity_mismatch: bool = False

    @staticmethod
    def resolve_identity_mismatch(obj) -> bool:
        declaration = getattr(obj, "declaration", None)
        return bool(declaration and declaration.identity_mismatch)
    #: True when there is no blueprint, so no capability check is possible.
    capabilities_unchecked: bool = False

    @staticmethod
    def resolve_capabilities(obj) -> dict:
        return obj.effective_capabilities()

    @staticmethod
    def resolve_capabilities_unchecked(obj) -> bool:
        return obj.device_type_id is None

    @staticmethod
    def resolve_device_category(obj) -> str:
        return obj.device_type.category if obj.device_type_id else ""

    @staticmethod
    def resolve_site_name(obj) -> str | None:
        return obj.site.name if obj.site_id else None

    @staticmethod
    def resolve_device_type_name(obj) -> str | None:
        return obj.device_type.name if obj.device_type_id else None


class MetricValueOut(Schema):
    metric_key: str
    label: str = ""
    unit: str = ""
    value: float | None = None
    value_text: str | None = None
    ts: dt.datetime
    quality: int = 0


class DeviceDetailOut(DeviceOut):
    latest: list[MetricValueOut] = Field(default_factory=list)
    open_alert_count: int = 0
    available_commands: list[dict[str, Any]] = Field(default_factory=list)


class DeviceEnergyOut(Schema):
    """Energy moved by one device over a window, and how it was arrived at.

    ``kwh`` is ``null`` when the figure cannot be determined - a counter that
    went backwards with no declared wrap point, or a metric with no samples.
    That is deliberately not zero: a monthly report that quietly loses a
    segment is worse than one that says it does not know.
    """

    device_id: uuid.UUID
    metric_key: str = ""
    #: ``counter`` (differenced, exact) | ``integrated`` (approximate) |
    #: ``unknown``.
    basis: str = "unknown"
    kwh: float | None = None
    unit: str = "kWh"
    #: Fraction of the window covered by samples (0..1). Always 1 for a
    #: counter. Below ~0.8 an integrated figure should be shown as incomplete.
    coverage: float = 0.0
    samples: int = 0
    #: The counter stepped backwards inside this window.
    counter_reset: bool = False
    avg_kw: float | None = None
    peak_kw: float | None = None
    start: dt.datetime
    end: dt.datetime
    #: Other metric keys that could have answered, best first.
    available_metrics: list[str] = Field(default_factory=list)


class DeviceMapPointOut(Schema):
    """Compact marker payload for the map view."""

    id: uuid.UUID
    device_id: str
    name: str
    status: ConnectionStatus
    latitude: float
    longitude: float
    address: str = ""
    #: "device" when the coordinates came from the hardware, "site" otherwise.
    source: str = "device"
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    category: str = ""
    open_alert_count: int = 0
    highest_severity: str | None = None


class DeviceFilters(FilterSchema):
    q: str | None = Field(default=None, q=["name__icontains", "device_id__icontains"])
    status: ConnectionStatus | None = None
    site_id: uuid.UUID | None = None
    device_type_id: uuid.UUID | None = None
    edge_node_id: uuid.UUID | None = None
    is_enabled: bool | None = None


class DeviceDeclarationOut(Schema):
    """A device's own claims about itself. Informational only.

    Nothing here is consulted when deciding whether a command may run; see
    ``capability_source`` on the device for what was actually accepted.
    """

    device_id: uuid.UUID
    schema_version: int
    state: str
    received_at: dt.datetime
    reviewed_at: dt.datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    has_differences: bool = False


class DeclarationReviewIn(Schema):
    accept: bool
    note: str = Field(default="", max_length=500)


class LifecycleIn(Schema):
    state: str = Field(
        description="pending | active | suspended | retired | rejected"
    )
    reason: str = Field(default="", max_length=500)


class DeviceReplaceIn(Schema):
    """Register a successor for a device being taken out of service.

    ``device_id`` must be new: it is the MQTT topic segment, it is unique
    platform-wide, and a retired device keeps its own so its history stays
    attributable to it.
    """

    device_id: str = Field(
        max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$"
    )
    name: str = Field(default="", max_length=200)
    device_type_id: uuid.UUID | None = None
    serial_number: str = Field(default="", max_length=120)
    reason: str = Field(default="", max_length=500)
    issue_credential: bool = True


class DeviceReplacementOut(Schema):
    retired: DeviceOut
    replacement: DeviceOut
    moved_asset_count: int = 0
    moved_alert_rule_count: int = 0
    #: Present only when credentials were issued; the password is shown once.
    credential: "DeviceCredentialOut | None" = None


class DeviceCredentialOut(Schema):
    mqtt_username: str
    #: Present only in the response that created or rotated the credential.
    mqtt_password: str | None = None
    allowed_client_id: str = ""
    is_active: bool
    rotated_at: dt.datetime | None = None
    last_auth_at: dt.datetime | None = None


class DeviceCreatedOut(Schema):
    device: DeviceOut
    credential: DeviceCredentialOut | None = None


# --------------------------------------------------------------------------
# Edge nodes
# --------------------------------------------------------------------------
class EdgeNodeIn(Schema):
    node_id: str = Field(
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
        description="Sparkplug edge_node_id - the fourth topic level.",
    )
    name: str = Field(default="", max_length=200)
    description: str = ""
    site_id: uuid.UUID | None = None
    is_enabled: bool = True


class EdgeNodeUpdateIn(Schema):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    site_id: uuid.UUID | None = None
    is_enabled: bool | None = None


class EdgeNodeOut(Schema):
    id: uuid.UUID
    node_id: str
    group_id: str
    name: str
    description: str
    is_implicit: bool
    is_enabled: bool
    status: ConnectionStatus
    status_changed_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None
    birth_at: dt.datetime | None = None
    #: Birth/death sequence of the session currently believed to be live.
    bd_seq: int | None = None
    #: Last accepted payload sequence number, 0-255.
    last_seq: int | None = None
    rebirth_requested_at: dt.datetime | None = None
    firmware_version: str = ""
    hardware_version: str = ""
    ip_address: str | None = None
    rssi: int | None = None
    #: What the current NBIRTH declared, metric by metric. Informational.
    birth_metrics: list[dict] = []
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    device_count: int = 0
    created_at: dt.datetime

    @staticmethod
    def resolve_site_name(obj) -> str | None:
        return obj.site.name if obj.site_id else None

    @staticmethod
    def resolve_device_count(obj) -> int:
        cached = getattr(obj, "device_count_annotated", None)
        if cached is not None:
            return cached
        return obj.devices.filter(deleted_at__isnull=True).count()


class EdgeNodeCreatedOut(Schema):
    edge_node: EdgeNodeOut
    credential: DeviceCredentialOut | None = None


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
class CommandIn(Schema):
    name: str = Field(max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    #: Repeating a submission with the same key returns the original command.
    idempotency_key: str = Field(default="", max_length=80)


class CommandOut(Schema):
    id: uuid.UUID
    device_id: uuid.UUID
    device_external_id: str = ""
    name: str
    params: dict[str, Any]
    status: CommandStatus
    issued_by_label: str
    created_at: dt.datetime
    sent_at: dt.datetime | None
    acked_at: dt.datetime | None
    completed_at: dt.datetime | None
    expires_at: dt.datetime
    response: dict[str, Any]
    error: str

    @staticmethod
    def resolve_device_external_id(obj) -> str:
        return obj.device.device_id if obj.device_id else ""


# --------------------------------------------------------------------------
# Device-reported logs
# --------------------------------------------------------------------------
class DeviceEventOut(Schema):
    id: int
    device_id: uuid.UUID
    device_external_id: str = ""
    device_name: str = ""
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    ts: dt.datetime
    level: EventLevel
    code: str
    message: str
    payload: dict[str, Any]
    received_at: dt.datetime

    @staticmethod
    def resolve_device_external_id(obj) -> str:
        return obj.device.device_id

    @staticmethod
    def resolve_device_name(obj) -> str:
        return obj.device.name

    @staticmethod
    def resolve_site_id(obj):
        return obj.device.site_id

    @staticmethod
    def resolve_site_name(obj) -> str | None:
        return obj.device.site.name if obj.device.site_id else None


class EventFilters(FilterSchema):
    """Filters for the fleet-wide event log."""

    device_id: uuid.UUID | None = Field(default=None, q="device_id")
    site_id: uuid.UUID | None = Field(default=None, q="device__site_id")
    level: EventLevel | None = Field(default=None, q="level")
    code: str | None = Field(default=None, q="code__iexact")
    #: Free text over the message and the code, which is how an operator
    #: actually searches: they remember a phrase, not an enum.
    search: str | None = Field(
        default=None, q=["message__icontains", "code__icontains"]
    )


class EventCodeOut(Schema):
    """One distinct code, for the filter dropdown."""

    code: str
    count: int


class DeviceStatusEventOut(Schema):
    id: int
    device_id: uuid.UUID
    status: ConnectionStatus
    previous_status: str
    reason: str
    ts: dt.datetime
    payload: dict[str, Any]


class GeocodeResultOut(Schema):
    latitude: float
    longitude: float
    display_name: str
    city: str = ""
    country: str = ""
    #: Blank when the coordinates fall outside any land timezone, which the
    #: console reads as "leave the current selection alone".
    timezone_name: str = ""


class GeocodeOut(Schema):
    #: False when the deployment has geocoding switched off, so the console can
    #: say "type the coordinates in" instead of showing an empty result list
    #: that looks like a failed search.
    available: bool = True
    results: list[GeocodeResultOut] = Field(default_factory=list)
