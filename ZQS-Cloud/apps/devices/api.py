"""Sites, blueprints, devices, downlink commands and device logs."""

from __future__ import annotations

import uuid

from django.db import IntegrityError
from django.db.models import Count, Q
from ninja import Query, Router

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.alerts.models import SEVERITY_RANK, Alert, AlertStatus
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.schemas import OkResponse, Page, PageParams, TimeRangeParams, paginate
from apps.devices import schemas as s
from apps.devices import services
from apps.devices.models import (
    Command,
    ConnectionStatus,
    Device,
    DeviceCredential,
    DeviceEvent,
    DeviceStatusEvent,
    DeviceType,
    Site,
)
from apps.devices.registry import get_registry
from apps.telemetry.catalog import get_catalog

sites_router = Router(tags=["sites"])
blueprints_router = Router(tags=["blueprints"])
devices_router = Router(tags=["devices"])
commands_router = Router(tags=["commands"])


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------
@sites_router.get("", response=Page[s.SiteSummaryOut])
def list_sites(request, params: Query[PageParams], include_inactive: bool = False):
    ctx: AuthContext = request.auth
    queryset = Site.objects.filter(
        organization=ctx.organization, deleted_at__isnull=True
    )
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    queryset = queryset.annotate(
        device_count=Count("devices", filter=Q(devices__deleted_at__isnull=True), distinct=True),
        online_count=Count(
            "devices",
            filter=Q(
                devices__deleted_at__isnull=True,
                devices__status=ConnectionStatus.ONLINE,
            ),
            distinct=True,
        ),
        open_alert_count=Count(
            "devices__alerts",
            filter=~Q(devices__alerts__status=AlertStatus.RESOLVED),
            distinct=True,
        ),
    ).order_by("name")
    return paginate(queryset, params)


@sites_router.post("", response={201: s.SiteOut}, auth=role_required(Role.ADMIN))
def create_site(request, payload: s.SiteIn):
    ctx: AuthContext = request.auth
    try:
        site = Site.objects.create(organization=ctx.organization, **payload.dict())
    except IntegrityError as exc:
        raise Conflict(
            f"A site with code '{payload.code}' already exists", code="code_taken"
        ) from exc
    record(AuditAction.SITE_CREATED, ctx=ctx, target=site)
    return 201, site


@sites_router.get("/{site_id}", response=s.SiteOut)
def get_site(request, site_id: uuid.UUID):
    return _get_site(request.auth, site_id)


@sites_router.patch("/{site_id}", response=s.SiteOut, auth=role_required(Role.ADMIN))
def update_site(request, site_id: uuid.UUID, payload: s.SiteUpdateIn):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    changes = payload.dict(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(site, field, value)
    if changes:
        site.save(update_fields=[*changes, "updated_at"])
        record(AuditAction.SITE_UPDATED, ctx=ctx, target=site, payload=changes)
    return site


@sites_router.delete("/{site_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_site(request, site_id: uuid.UUID):
    """Soft delete - historical telemetry keeps referring to the site."""
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    attached = Device.objects.filter(site=site, deleted_at__isnull=True).count()
    if attached:
        raise Conflict(
            f"{attached} device(s) are still assigned to this site",
            code="site_in_use",
            details={"device_count": attached},
        )
    site.soft_delete()
    record(AuditAction.SITE_DELETED, ctx=ctx, target=site)
    return {"ok": True, "message": "site_deleted"}


# --------------------------------------------------------------------------
# Blueprints (device types)
# --------------------------------------------------------------------------
@blueprints_router.get("", response=list[s.DeviceTypeOut])
def list_blueprints(request):
    """Built-in blueprints plus this tenant's own."""
    ctx: AuthContext = request.auth
    return list(
        DeviceType.objects.filter(
            Q(organization=ctx.organization) | Q(organization__isnull=True)
        ).order_by("name")
    )


@blueprints_router.post("", response={201: s.DeviceTypeOut}, auth=role_required(Role.ADMIN))
def create_blueprint(request, payload: s.DeviceTypeIn):
    ctx: AuthContext = request.auth
    _validate_command_definitions(payload.command_definitions)
    try:
        blueprint = DeviceType.objects.create(
            organization=ctx.organization, **payload.dict()
        )
    except IntegrityError as exc:
        raise Conflict(
            f"A blueprint with key '{payload.key}' already exists", code="key_taken"
        ) from exc
    return 201, blueprint


@blueprints_router.patch("/{blueprint_id}", response=s.DeviceTypeOut, auth=role_required(Role.ADMIN))
def update_blueprint(request, blueprint_id: uuid.UUID, payload: s.DeviceTypeIn):
    ctx: AuthContext = request.auth
    blueprint = DeviceType.objects.filter(
        pk=blueprint_id, organization=ctx.organization
    ).first()
    if blueprint is None:
        # Built-ins are read-only; say so rather than a bare 404.
        if DeviceType.objects.filter(pk=blueprint_id, organization__isnull=True).exists():
            raise Conflict(
                "Built-in blueprints cannot be edited; copy it first",
                code="builtin_readonly",
            )
        raise NotFound("Blueprint not found")

    _validate_command_definitions(payload.command_definitions)
    for field, value in payload.dict().items():
        setattr(blueprint, field, value)
    blueprint.save()
    return blueprint


@blueprints_router.delete("/{blueprint_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_blueprint(request, blueprint_id: uuid.UUID):
    ctx: AuthContext = request.auth
    blueprint = DeviceType.objects.filter(
        pk=blueprint_id, organization=ctx.organization
    ).first()
    if blueprint is None:
        raise NotFound("Blueprint not found")
    in_use = Device.objects.filter(device_type=blueprint, deleted_at__isnull=True).count()
    if in_use:
        raise Conflict(
            f"{in_use} device(s) still use this blueprint",
            code="blueprint_in_use",
            details={"device_count": in_use},
        )
    blueprint.delete()
    return {"ok": True, "message": "blueprint_deleted"}


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------
@devices_router.get("", response=Page[s.DeviceOut])
def list_devices(
    request, filters: Query[s.DeviceFilters], params: Query[PageParams]
):
    ctx: AuthContext = request.auth
    queryset = (
        Device.objects.for_organization(ctx.organization)
        .select_related("site", "device_type")
        .order_by("name")
    )
    queryset = filters.filter(queryset)
    return paginate(queryset, params)


@devices_router.get("/map", response=list[s.DeviceMapPointOut])
def device_map(request, site_id: uuid.UUID | None = None):
    """Marker list for the map view.

    Devices without their own coordinates inherit the site's, so a fleet is
    visible on day one and becomes more precise as hardware reports GPS.
    """
    ctx: AuthContext = request.auth
    queryset = (
        Device.objects.for_organization(ctx.organization)
        .select_related("site", "device_type")
    )
    if site_id is not None:
        queryset = queryset.filter(site_id=site_id)

    alert_rows = (
        Alert.objects.filter(organization=ctx.organization)
        .exclude(status=AlertStatus.RESOLVED)
        .values_list("device_id", "severity")
    )
    counts: dict[uuid.UUID, int] = {}
    worst: dict[uuid.UUID, str] = {}
    for device_pk, severity in alert_rows:
        if device_pk is None:
            continue
        counts[device_pk] = counts.get(device_pk, 0) + 1
        current = worst.get(device_pk)
        if current is None or SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(current, 0):
            worst[device_pk] = severity

    points = []
    for device in queryset:
        location = device.effective_location
        if location is None:
            continue
        latitude, longitude, address = location
        own = device.latitude is not None and device.longitude is not None
        points.append(
            {
                "id": device.id,
                "device_id": device.device_id,
                "name": device.name,
                "status": device.status,
                "latitude": latitude,
                "longitude": longitude,
                "address": address or "",
                "source": device.location_source or ("device" if own else "site"),
                "site_id": device.site_id,
                "site_name": device.site.name if device.site_id else None,
                "category": device.device_type.category if device.device_type_id else "",
                "open_alert_count": counts.get(device.id, 0),
                "highest_severity": worst.get(device.id),
            }
        )
    return points


@devices_router.post("", response={201: s.DeviceCreatedOut}, auth=role_required(Role.ADMIN))
def create_device(request, payload: s.DeviceIn, issue_credential: bool = True):
    """Register a device. MQTT credentials are returned once, if requested."""
    ctx: AuthContext = request.auth
    data = payload.dict()
    site = _resolve_site(ctx, data.pop("site_id", None))
    device_type = _resolve_blueprint(ctx, data.pop("device_type_id", None))
    policy = _resolve_policy(ctx, data.pop("recording_policy_id", None))

    if data.get("latitude") is not None and data.get("longitude") is not None:
        data["location_source"] = "manual"

    try:
        device = Device.objects.create(
            organization=ctx.organization,
            site=site,
            device_type=device_type,
            recording_policy=policy,
            **data,
        )
    except IntegrityError as exc:
        raise Conflict(
            f"Device id '{payload.device_id}' is already registered",
            code="device_id_taken",
        ) from exc

    credential_out = None
    if issue_credential:
        credential, password = DeviceCredential.issue(device)
        credential_out = {
            "mqtt_username": credential.mqtt_username,
            "mqtt_password": password,
            "allowed_client_id": credential.allowed_client_id,
            "is_active": credential.is_active,
            "rotated_at": credential.rotated_at,
            "last_auth_at": credential.last_auth_at,
        }

    get_registry().invalidate()
    record(AuditAction.DEVICE_CREATED, ctx=ctx, target=device)
    return 201, {"device": device, "credential": credential_out}


@devices_router.get("/{device_pk}", response=s.DeviceDetailOut)
def get_device(request, device_pk: uuid.UUID):
    from apps.telemetry.models import LatestSample

    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    language = ctx.user.language if ctx.user else "en"
    catalog = get_catalog().for_organization(ctx.organization.id)

    latest = []
    for row in LatestSample.objects.filter(device=device).order_by("metric_key"):
        definition = catalog.get(row.metric_key)
        latest.append(
            {
                "metric_key": row.metric_key,
                "label": definition.label(language) if definition else row.metric_key,
                "unit": definition.unit if definition else "",
                "value": row.value,
                "value_text": row.value_text,
                "ts": row.ts,
                "quality": row.quality,
            }
        )

    payload = s.DeviceDetailOut.from_orm(device).dict()
    payload["latest"] = latest
    payload["open_alert_count"] = (
        Alert.objects.filter(device=device).exclude(status=AlertStatus.RESOLVED).count()
    )
    payload["available_commands"] = (
        device.device_type.command_definitions if device.device_type_id else []
    )
    return payload


@devices_router.patch("/{device_pk}", response=s.DeviceOut, auth=role_required(Role.ADMIN))
def update_device(request, device_pk: uuid.UUID, payload: s.DeviceUpdateIn):
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    changes = payload.dict(exclude_unset=True)

    if "site_id" in changes:
        device.site = _resolve_site(ctx, changes.pop("site_id"))
    if "device_type_id" in changes:
        device.device_type = _resolve_blueprint(ctx, changes.pop("device_type_id"))
    if "recording_policy_id" in changes:
        device.recording_policy = _resolve_policy(ctx, changes.pop("recording_policy_id"))
    if changes.get("latitude") is not None and changes.get("longitude") is not None:
        # An operator-set position outranks whatever the device last reported.
        device.location_source = "manual"

    for field, value in changes.items():
        if value is not None or field in {"description", "address", "serial_number"}:
            setattr(device, field, value)

    device.save()
    get_registry().invalidate()
    record(AuditAction.DEVICE_UPDATED, ctx=ctx, target=device, payload=changes)
    return device


@devices_router.delete("/{device_pk}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_device(request, device_pk: uuid.UUID):
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    device.soft_delete()
    DeviceCredential.objects.filter(device=device).update(is_active=False)
    get_registry().invalidate()
    record(AuditAction.DEVICE_DELETED, ctx=ctx, target=device)
    return {"ok": True, "message": "device_deleted"}


@devices_router.post("/{device_pk}/credential", response=s.DeviceCredentialOut, auth=role_required(Role.ADMIN))
def rotate_device_credential(request, device_pk: uuid.UUID):
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    credential, password = services.rotate_credential(ctx, device)
    return {
        "mqtt_username": credential.mqtt_username,
        "mqtt_password": password,
        "allowed_client_id": credential.allowed_client_id,
        "is_active": credential.is_active,
        "rotated_at": credential.rotated_at,
        "last_auth_at": credential.last_auth_at,
    }


# ---- Commands -------------------------------------------------------------
@devices_router.post("/{device_pk}/commands", response={202: s.CommandOut}, auth=role_required(Role.OPERATOR))
def send_command(request, device_pk: uuid.UUID, payload: s.CommandIn):
    """Queue a downlink command and publish it to the device's control topic."""
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    command = services.dispatch_command(
        ctx,
        device,
        name=payload.name,
        params=payload.params,
        timeout_seconds=payload.timeout_seconds,
        idempotency_key=payload.idempotency_key,
    )
    return 202, command


@devices_router.get("/{device_pk}/commands", response=Page[s.CommandOut])
def list_device_commands(request, device_pk: uuid.UUID, params: Query[PageParams]):
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    queryset = (
        Command.objects.filter(device=device)
        .select_related("device")
        .order_by("-created_at")
    )
    return paginate(queryset, params)


# ---- Device-reported logs -------------------------------------------------
@devices_router.get("/{device_pk}/events", response=Page[s.DeviceEventOut])
def list_device_events(
    request,
    device_pk: uuid.UUID,
    params: Query[PageParams],
    window: Query[TimeRangeParams],
    level: str | None = None,
    code: str | None = None,
):
    """Operation log entries the device reported."""
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    start, end = window.normalized(default_window_seconds=7 * 24 * 3600)

    queryset = (
        DeviceEvent.objects.filter(device=device, ts__gte=start, ts__lt=end)
        .select_related("device")
        .order_by("-ts")
    )
    if level:
        queryset = queryset.filter(level=level)
    if code:
        queryset = queryset.filter(code=code)
    return paginate(queryset, params)


@devices_router.get("/{device_pk}/status-history", response=Page[s.DeviceStatusEventOut])
def list_status_history(
    request, device_pk: uuid.UUID, params: Query[PageParams], window: Query[TimeRangeParams]
):
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    start, end = window.normalized(default_window_seconds=7 * 24 * 3600)
    queryset = DeviceStatusEvent.objects.filter(
        device=device, ts__gte=start, ts__lt=end
    ).order_by("-ts")
    return paginate(queryset, params)


# --------------------------------------------------------------------------
# Commands (organisation-wide)
# --------------------------------------------------------------------------
@commands_router.get("", response=Page[s.CommandOut])
def list_commands(
    request,
    params: Query[PageParams],
    status: str | None = None,
    device_pk: uuid.UUID | None = None,
):
    ctx: AuthContext = request.auth
    queryset = (
        Command.objects.filter(organization=ctx.organization)
        .select_related("device")
        .order_by("-created_at")
    )
    if status:
        queryset = queryset.filter(status=status)
    if device_pk:
        queryset = queryset.filter(device_id=device_pk)
    return paginate(queryset, params)


@commands_router.get("/{command_id}", response=s.CommandOut)
def get_command(request, command_id: uuid.UUID):
    ctx: AuthContext = request.auth
    command = (
        Command.objects.filter(organization=ctx.organization, pk=command_id)
        .select_related("device")
        .first()
    )
    if command is None:
        raise NotFound("Command not found")
    return command


@commands_router.post("/{command_id}/cancel", response=s.CommandOut, auth=role_required(Role.OPERATOR))
def cancel_command(request, command_id: uuid.UUID):
    return services.cancel_command(request.auth, command_id)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _get_site(ctx: AuthContext, site_id: uuid.UUID) -> Site:
    site = Site.objects.filter(
        organization=ctx.organization, pk=site_id, deleted_at__isnull=True
    ).first()
    if site is None:
        raise NotFound("Site not found")
    return site


def _get_device(ctx: AuthContext, device_pk: uuid.UUID) -> Device:
    device = (
        Device.objects.for_organization(ctx.organization)
        .select_related("site", "device_type")
        .filter(pk=device_pk)
        .first()
    )
    if device is None:
        raise NotFound("Device not found")
    return device


def _resolve_site(ctx: AuthContext, site_id: uuid.UUID | None) -> Site | None:
    return None if site_id is None else _get_site(ctx, site_id)


def _resolve_blueprint(ctx: AuthContext, blueprint_id: uuid.UUID | None):
    if blueprint_id is None:
        return None
    blueprint = DeviceType.objects.filter(
        Q(organization=ctx.organization) | Q(organization__isnull=True), pk=blueprint_id
    ).first()
    if blueprint is None:
        raise NotFound("Blueprint not found")
    return blueprint


def _resolve_policy(ctx: AuthContext, policy_id: uuid.UUID | None):
    if policy_id is None:
        return None
    from apps.telemetry.models import RecordingPolicy

    policy = RecordingPolicy.objects.filter(
        organization=ctx.organization, pk=policy_id
    ).first()
    if policy is None:
        raise NotFound("Recording policy not found")
    return policy


def _validate_command_definitions(definitions: list[dict]) -> None:
    seen: set[str] = set()
    for index, spec in enumerate(definitions or []):
        if not isinstance(spec, dict):
            raise ValidationError(
                f"command_definitions[{index}] must be an object", code="bad_command_spec"
            )
        name = spec.get("name")
        if not name or not isinstance(name, str):
            raise ValidationError(
                f"command_definitions[{index}] needs a 'name'", code="bad_command_spec"
            )
        if name in seen:
            raise ValidationError(
                f"Duplicate command name '{name}'", code="duplicate_command"
            )
        seen.add(name)
        params = spec.get("params")
        if params is not None and not isinstance(params, dict):
            raise ValidationError(
                f"command '{name}' has a non-object 'params' schema",
                code="bad_command_spec",
            )
