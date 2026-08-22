"""Sites, blueprints, devices, downlink commands and device logs."""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
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
from apps.core.timeutils import now
from apps.devices import edge_nodes
from apps.devices import geocoding
from apps.devices import schemas as s
from apps.devices import services
from apps.devices.models import (
    CAPABILITY_FIELDS,
    CapabilitySource,
    Command,
    LifecycleState,
    ConnectionStatus,
    DeclarationState,
    Device,
    EdgeNode,
    EdgeNodeCredential,
    DeviceDeclaration,
    DeviceEvent,
    DeviceStatusEvent,
    DeviceType,
    Site,
    declaration_diff,
    descendant_site_ids,
)
from apps.devices.registry import get_registry
from apps.telemetry.catalog import get_catalog

sites_router = Router(tags=["sites"])
blueprints_router = Router(tags=["blueprints"])
devices_router = Router(tags=["devices"])
edge_nodes_router = Router(tags=["edge-nodes"])
events_router = Router(tags=["events"])
commands_router = Router(tags=["commands"])


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------
@sites_router.get("", response=Page[s.SiteSummaryOut])
def list_sites(
    request,
    params: Query[PageParams],
    include_inactive: bool = False,
    include_descendants: bool = False,
    parent_id: uuid.UUID | None = None,
    top_level_only: bool = False,
):
    """List sites with their own counts, and optionally their subtree totals.

    ``include_descendants`` fills ``total_*``; the plain counts always stay the
    site's own devices, so a parent row can show both "12 here" and "340 in
    total" without a second request.
    """
    ctx: AuthContext = request.auth
    queryset = ctx.scope_queryset(
        Site.objects.filter(organization=ctx.organization, deleted_at__isnull=True),
        field="id",
    )
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if top_level_only:
        queryset = queryset.filter(parent__isnull=True)
    elif parent_id is not None:
        queryset = queryset.filter(parent_id=parent_id)

    queryset = _with_own_counts(queryset).order_by("name")
    page = paginate(queryset, params)
    _decorate_tree(ctx, page["items"], include_descendants=include_descendants)
    return page


@sites_router.post("", response={201: s.SiteOut}, auth=role_required(Role.ADMIN))
def create_site(request, payload: s.SiteIn):
    ctx: AuthContext = request.auth
    # A site-scoped admin may only add sites *inside* their scope. Without this
    # they could create a top-level site and then watch it disappear from their
    # own listing, which looks like the save silently failed.
    if ctx.is_site_scoped and payload.parent_id is None:
        raise ValidationError(
            "Your access is limited to specific sites, so a new site needs a "
            "parent inside that scope",
            code="parent_required_in_scope",
        )

    data = payload.dict(exclude={"parent_id"})
    site = Site(organization=ctx.organization, **data)
    _apply_parent(ctx, site, payload.parent_id)
    try:
        site.save()
    except IntegrityError as exc:
        raise Conflict(
            f"A site with code '{payload.code}' already exists", code="code_taken"
        ) from exc
    record(AuditAction.SITE_CREATED, ctx=ctx, target=site)
    _decorate_tree(ctx, [site])
    return 201, site


# --------------------------------------------------------------------------
# Geocoding
# --------------------------------------------------------------------------
@sites_router.get("/geocode", response=s.GeocodeOut)
def geocode_address(request, q: str, limit: int = 5):
    """Turn an address into candidate coordinates.

    Declared before ``/sites/{site_id}``: routes match in registration order,
    so a literal path placed after a parameterised one is never reached - the
    word "geocode" is simply parsed as a (failing) UUID.

    Deliberately never fails. ``available`` says whether lookup is possible at
    all in this deployment, and an empty ``results`` covers everything else -
    no match, no internet, rate limited. The console's fallback is the same in
    every one of those cases: let the operator type the numbers in.
    """
    ctx: AuthContext = request.auth
    return {
        "available": geocoding.is_enabled(),
        "results": [
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "display_name": place.display_name,
                "city": place.city,
                "country": place.country,
                "timezone_name": place.timezone_name,
            }
            for place in geocoding.search(
                q, limit=limit, language=getattr(ctx.user, "language", "") or ""
            )
        ],
    }


@sites_router.get("/{site_id}", response=s.SiteOut)
def get_site(request, site_id: uuid.UUID):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    _decorate_tree(ctx, [site])
    return site


@sites_router.get("/{site_id}/summary", response=s.SiteRollupOut)
def site_rollup(
    request,
    site_id: uuid.UUID,
    window: Query[TimeRangeParams],
    include_descendants: bool = True,
):
    """Devices, alerts and energy for one site - and, by default, its subtree.

    The energy block is produced by :mod:`apps.ems.rollup`, so its ``peak_*``
    figures are coincident peaks rather than a sum of per-site peaks, and its
    ratios are recomputed from summed totals rather than averaged.
    """
    from apps.ems import rollup as ems_rollup

    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    site_ids = (
        descendant_site_ids([site.pk], organization=ctx.organization)
        if include_descendants
        else [site.pk]
    )
    start, end = window.normalized(default_window_seconds=24 * 3600)

    devices = Device.objects.filter(
        organization=ctx.organization, site_id__in=site_ids, deleted_at__isnull=True
    )
    device_counts = devices.aggregate(
        total=Count("id"),
        online=Count("id", filter=Q(status=ConnectionStatus.ONLINE)),
        offline=Count("id", filter=Q(status=ConnectionStatus.OFFLINE)),
        unknown=Count("id", filter=Q(status=ConnectionStatus.UNKNOWN)),
        disabled=Count("id", filter=Q(is_enabled=False)),
    )
    alert_counts = Alert.objects.filter(
        organization=ctx.organization, device__site_id__in=site_ids
    ).aggregate(
        open=Count("id", filter=~Q(status=AlertStatus.RESOLVED)),
        critical=Count(
            "id", filter=Q(severity="critical") & ~Q(status=AlertStatus.RESOLVED)
        ),
        major=Count("id", filter=Q(severity="major") & ~Q(status=AlertStatus.RESOLVED)),
        acknowledged=Count("id", filter=Q(status=AlertStatus.ACKNOWLEDGED)),
    )

    energy = ems_rollup.energy_totals(
        site_ids, start, end, default_currency=ctx.organization.reporting_currency
    )
    # A subtree with no metered site at all should read as "nothing to show"
    # rather than as a confident row of zeroes.
    if not energy["site_count"] or _energy_is_empty(energy):
        energy = None

    return {
        "site_id": site.id,
        "site_name": site.name,
        "kind": site.kind,
        "depth": site.depth,
        "include_descendants": include_descendants,
        "site_ids": site_ids,
        "site_count": len(site_ids),
        "child_count": Site.objects.filter(
            parent_id=site.pk, deleted_at__isnull=True
        ).count(),
        "devices": {
            "total": device_counts["total"] or 0,
            "online": device_counts["online"] or 0,
            "offline": device_counts["offline"] or 0,
            "unknown": device_counts["unknown"] or 0,
            "disabled": device_counts["disabled"] or 0,
            "stale": devices.filter(is_enabled=True).stale().count(),
        },
        "alerts": {key: value or 0 for key, value in alert_counts.items()},
        "energy": energy,
    }


@sites_router.patch("/{site_id}", response=s.SiteOut, auth=role_required(Role.ADMIN))
def update_site(request, site_id: uuid.UUID, payload: s.SiteUpdateIn):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)

    # parent_id is handled separately: exclude_none would swallow an explicit
    # null, which is how a site gets detached and promoted to top level.
    provided = payload.dict(exclude_unset=True)
    reparented = "parent_id" in provided
    changes = payload.dict(exclude_unset=True, exclude_none=True)
    changes.pop("parent_id", None)

    for field, value in changes.items():
        setattr(site, field, value)
    if reparented:
        _apply_parent(ctx, site, provided["parent_id"])
        changes["parent_id"] = provided["parent_id"]

    if changes:
        update_fields = [
            "parent" if field == "parent_id" else field for field in changes
        ]
        site.save(update_fields=[*update_fields, "updated_at"])
        record(AuditAction.SITE_UPDATED, ctx=ctx, target=site, payload=changes)
    _decorate_tree(ctx, [site])
    return site


@sites_router.delete("/{site_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_site(request, site_id: uuid.UUID):
    """Soft delete - historical telemetry keeps referring to the site."""
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)

    # Children first: the FK is PROTECT, so deleting a parent out from under a
    # subtree would either fail at the database or orphan it. Say so plainly.
    children = Site.objects.filter(parent_id=site.pk, deleted_at__isnull=True).count()
    if children:
        raise Conflict(
            f"{children} child site(s) are still nested under this site",
            code="site_has_children",
            details={"child_count": children},
        )

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
    """Built-in blueprints plus this tenant's own.

    ``label`` and ``description_text`` come back in the caller's language.
    The blueprint catalogue is where somebody registering their first device
    finds out what a "PCS" is, so it should not be the one screen that stays
    English.
    """
    ctx: AuthContext = request.auth
    language = ctx.user.language if ctx.user else "en"
    return [
        _blueprint_out(blueprint, language)
        for blueprint in DeviceType.objects.filter(
            Q(organization=ctx.organization) | Q(organization__isnull=True)
        ).order_by("name")
    ]


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
    return 201, _blueprint_out(blueprint, ctx.user.language if ctx.user else "en")


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
    return _blueprint_out(blueprint, ctx.user.language if ctx.user else "en")


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
    request,
    filters: Query[s.DeviceFilters],
    params: Query[PageParams],
    include_descendants: bool = False,
    unassigned_only: bool = False,
):
    """List devices.

    ``include_descendants`` widens ``site_id`` to the whole subtree, so
    selecting a plant shows the devices of its workshops too.
    ``unassigned_only`` returns the devices with no site at all - the ones a
    tree view has nowhere to put.
    """
    ctx: AuthContext = request.auth
    queryset = ctx.scope_queryset(
        Device.objects.for_organization(ctx.organization)
        .select_related("site", "device_type")
        .order_by("name")
    )

    site_id = filters.site_id
    if include_descendants and site_id is not None:
        # Applied here rather than through FilterSchema, which maps one field
        # to one lookup and cannot turn site_id into site_id__in.
        filters = filters.model_copy(update={"site_id": None})
        queryset = queryset.filter(
            site_id__in=descendant_site_ids([site_id], organization=ctx.organization)
        )

    queryset = filters.filter(queryset)
    if unassigned_only:
        queryset = queryset.filter(site__isnull=True)
    return paginate(queryset, params)


@devices_router.get("/{device_pk}/declaration", response=s.DeviceDeclarationOut)
def get_declaration(request, device_pk: uuid.UUID):
    """What the device claims about itself, and where that differs from record."""
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    declaration = DeviceDeclaration.objects.filter(device=device).first()
    if declaration is None:
        raise NotFound("This device has not declared anything", code="no_declaration")
    return _declaration_out(declaration)


@devices_router.post(
    "/{device_pk}/declaration/review",
    response=s.DeviceDeclarationOut,
    auth=role_required(Role.ADMIN),
)
def review_declaration(request, device_pk: uuid.UUID, payload: s.DeclarationReviewIn):
    """Adopt a declaration during commissioning, or acknowledge a difference.

    Adoption is available **once**, while the device is still ``pending``. It
    is the only path by which a device's own claims reach the fields that gate
    commands. After commissioning a device's category never changes, so a later
    disagreement is not a change to approve - it is a sign the hardware was
    swapped, and the answer is to register a replacement.
    """
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    declaration = DeviceDeclaration.objects.filter(device=device).first()
    if declaration is None:
        raise NotFound("This device has not declared anything", code="no_declaration")

    if payload.accept:
        if device.commissioning_state != LifecycleState.PENDING:
            raise Conflict(
                "A declaration can only be adopted while the device is pending "
                "commissioning. Register a replacement device instead.",
                code="declaration_not_adoptable",
                details={"commissioning_state": device.commissioning_state},
            )

        claimed = declaration.payload.get("capabilities") or {}
        applied: dict[str, bool] = {}
        for field in CAPABILITY_FIELDS:
            if field in claimed:
                value = bool(claimed[field])
                setattr(device, field, value)
                applied[field] = value
        device.capability_source = CapabilitySource.DEVICE
        device.save(update_fields=[*applied, "capability_source", "updated_at"])
        services.set_lifecycle(
            ctx, device, LifecycleState.ACTIVE, reason="declaration adopted"
        )
        action = AuditAction.DEVICE_DECLARATION_ACCEPTED
        audit_payload = {"applied": applied, "note": payload.note}
        declaration.identity_mismatch = False
    else:
        # Acknowledging silences the banner. It deliberately does not clear
        # identity_mismatch: seeing a problem is not the same as fixing it, and
        # the command freeze exists because we do not know what the hardware is.
        action = AuditAction.DEVICE_DECLARATION_REJECTED
        audit_payload = {"note": payload.note}

    declaration.diff_summary = declaration_diff(device, declaration.payload)
    declaration.state = (
        DeclarationState.MATCHED
        if not declaration.diff_summary
        else DeclarationState.ACKNOWLEDGED
    )
    declaration.reviewed_by = ctx.user
    declaration.reviewed_at = now()
    declaration.save(
        update_fields=[
            "state",
            "identity_mismatch",
            "reviewed_by",
            "reviewed_at",
            "diff_summary",
            "updated_at",
        ]
    )
    record(action, ctx=ctx, target=device, payload=audit_payload)
    return _declaration_out(declaration)


@devices_router.post(
    "/{device_pk}/lifecycle", response=s.DeviceOut, auth=role_required(Role.ADMIN)
)
def change_lifecycle(request, device_pk: uuid.UUID, payload: s.LifecycleIn):
    """Suspend, retire, reject or return a device to service.

    Retirement never soft-deletes: the device stays in the API and its history
    stays readable, it simply cannot connect or be commanded. Returning a
    retired device to service is allowed - hardware does come back - but only
    once whatever replaced it has stepped aside.
    """
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    services.set_lifecycle(ctx, device, payload.state, reason=payload.reason)
    device.refresh_from_db()
    return device


@devices_router.post(
    "/{device_pk}/replace",
    response={201: s.DeviceReplacementOut},
    auth=role_required(Role.ADMIN),
)
def replace_device(request, device_pk: uuid.UUID, payload: s.DeviceReplaceIn):
    """Register a successor and hand everything over to it, atomically.

    A replacement is several steps that are only correct together: without the
    asset bindings moving, the site's energy balance silently loses whichever
    flow the old device measured. Doing it in one transaction means there is no
    window in which the site is half-migrated.
    """
    ctx: AuthContext = request.auth
    old = _get_device(ctx, device_pk)
    result = services.replace_device(
        ctx,
        old,
        device_id=payload.device_id,
        name=payload.name,
        device_type_id=payload.device_type_id,
        serial_number=payload.serial_number,
        reason=payload.reason,
        issue_credential=payload.issue_credential,
    )
    return 201, result


@devices_router.get("/map", response=list[s.DeviceMapPointOut])
def device_map(request, site_id: uuid.UUID | None = None):
    """Marker list for the map view.

    Devices without their own coordinates inherit the site's, so a fleet is
    visible on day one and becomes more precise as hardware reports GPS.
    """
    ctx: AuthContext = request.auth
    queryset = ctx.scope_queryset(
        Device.objects.for_organization(ctx.organization).select_related(
            "site", "device_type"
        )
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


def _credential_out(credential, password: str) -> dict:
    return {
        "mqtt_username": credential.mqtt_username,
        "mqtt_password": password,
        "allowed_client_id": credential.allowed_client_id,
        "is_active": credential.is_active,
        "rotated_at": credential.rotated_at,
        "last_auth_at": credential.last_auth_at,
    }


def _resolve_edge_node(ctx, node_id, device_id: str, site):
    """The node this device reports through.

    Omitting ``edge_node_id`` means "this device speaks MQTT itself", and an
    implicit node is created to hold its connection. Registering a device is
    still one call, even though the model underneath now has two levels.
    """
    if node_id:
        node = EdgeNode.objects.filter(
            pk=node_id, organization=ctx.organization, deleted_at__isnull=True
        ).first()
        if node is None:
            raise NotFound("Edge node not found")
        return node
    return edge_nodes.implicit_node_for(
        organization=ctx.organization, node_id=device_id, site=site
    )


@devices_router.post("", response={201: s.DeviceCreatedOut}, auth=role_required(Role.ADMIN))
def create_device(request, payload: s.DeviceIn, issue_credential: bool = True):
    """Register a device. MQTT credentials are returned once, if requested."""
    ctx: AuthContext = request.auth
    data = payload.dict()
    site = _resolve_site(ctx, data.pop("site_id", None))
    device_type = _resolve_blueprint(ctx, data.pop("device_type_id", None))
    policy = _resolve_policy(ctx, data.pop("recording_policy_id", None))
    node = _resolve_edge_node(ctx, data.pop("edge_node_id", None), payload.device_id, site)

    if data.get("latitude") is not None and data.get("longitude") is not None:
        data["location_source"] = "manual"

    _assert_serial_free(ctx, data.get("serial_number", ""))
    try:
        device = Device.objects.create(
            organization=ctx.organization,
            site=site,
            device_type=device_type,
            recording_policy=policy,
            edge_node=node,
            **data,
        )
    except IntegrityError as exc:
        # Two constraints can land here. Telling them apart matters: one means
        # "pick another id", the other means "this hardware is already
        # registered, go and find it".
        raise _registration_conflict(ctx, payload.device_id, data.get("serial_number", "")) from exc

    credential_out = None
    if issue_credential:
        # On a shared gateway the credential already exists and belongs to the
        # other devices too, so issuing here would silently invalidate theirs.
        if node.is_implicit or not hasattr(node, "credential"):
            credential, password = edge_nodes.issue_credential(node)
            credential_out = _credential_out(credential, password)

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

    # Attach the extras to the model instance rather than serialising to a
    # dict and handing that back. Ninja validates the returned value against
    # the response schema, and a dict re-entering the schema loses every
    # resolver-backed field - site_name, device_type_name, device_category and
    # capabilities all silently fall back to their defaults, because the
    # resolvers reach for ``obj.site`` / ``obj.effective_capabilities()`` and a
    # dict has neither.
    device.latest = latest
    device.open_alert_count = (
        Alert.objects.filter(device=device).exclude(status=AlertStatus.RESOLVED).count()
    )
    device.available_commands = (
        device.device_type.command_definitions if device.device_type_id else []
    )
    return device


@devices_router.patch("/{device_pk}", response=s.DeviceOut, auth=role_required(Role.ADMIN))
def update_device(request, device_pk: uuid.UUID, payload: s.DeviceUpdateIn):
    """Edit a device's registered details, including which site it belongs to.

    A device is registered to exactly one site - the FK enforces that - so
    "moving" one is a reassignment, not an addition. The audit entry records
    the site and blueprint by name on both sides: ``site_id`` alone tells a
    later reader nothing about what actually changed, and a site can be
    renamed or deleted between the change and the day someone reads the log.
    """
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    changes = payload.dict(exclude_unset=True)
    audit: dict = {}
    site_changed = False

    if "serial_number" in changes and changes["serial_number"] is not None:
        _assert_serial_free(ctx, changes["serial_number"], exclude_pk=device.pk)

    if "site_id" in changes:
        previous = device.site
        device.site = _resolve_site(ctx, changes.pop("site_id"))
        if (previous.pk if previous else None) != (
            device.site.pk if device.site else None
        ):
            site_changed = True
            audit["site"] = {
                "from": previous.name if previous else None,
                "to": device.site.name if device.site else None,
                "to_id": str(device.site.pk) if device.site else None,
            }
    if "device_type_id" in changes:
        previous_type = device.device_type
        device.device_type = _resolve_blueprint(ctx, changes.pop("device_type_id"))
        if (previous_type.pk if previous_type else None) != (
            device.device_type.pk if device.device_type else None
        ):
            audit["device_type"] = {
                "from": previous_type.name if previous_type else None,
                "to": device.device_type.name if device.device_type else None,
            }
    if "recording_policy_id" in changes:
        device.recording_policy = _resolve_policy(ctx, changes.pop("recording_policy_id"))
        audit["recording_policy_id"] = (
            str(device.recording_policy_id) if device.recording_policy_id else None
        )
    if changes.get("latitude") is not None and changes.get("longitude") is not None:
        # An operator-set position outranks whatever the device last reported.
        device.location_source = "manual"

    # Fields where an explicit null is a real instruction ("clear this"),
    # rather than the caller simply not mentioning it. Everything else keeps
    # its stored value when null arrives.
    nullable = {
        "description",
        "address",
        "serial_number",
        "capital_cost",
        "commissioned_on",
        "expected_life_years",
        "annual_maintenance_cost",
    }
    for field, value in changes.items():
        if value is None and field not in nullable:
            continue
        if field == "name":
            audit["name"] = {"from": device.name, "to": value}
        setattr(device, field, value)
        audit.setdefault(field, value)

    try:
        device.save()
    except IntegrityError as exc:
        raise _registration_conflict(
            ctx, device.device_id, device.serial_number
        ) from exc

    if site_changed:
        # The energy asset bindings say "at site S, this device supplies flow
        # R". Left behind, they make the old site's balance depend on
        # equipment that is no longer there while the new site reads as
        # unconfigured - two wrong numbers, no error anywhere.
        moved = services.move_energy_bindings(device, device.site)
        if moved:
            audit["energy_bindings"] = moved

    get_registry().invalidate()
    record(AuditAction.DEVICE_UPDATED, ctx=ctx, target=device, payload=audit)
    return device


@devices_router.delete("/{device_pk}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_device(request, device_pk: uuid.UUID):
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    device.soft_delete()
    EdgeNodeCredential.objects.filter(
        edge_node_id=device.edge_node_id, edge_node__is_implicit=True
    ).update(is_active=False)
    get_registry().invalidate()
    record(AuditAction.DEVICE_DELETED, ctx=ctx, target=device)
    return {"ok": True, "message": "device_deleted"}


@devices_router.post("/{device_pk}/credential", response=s.DeviceCredentialOut, auth=role_required(Role.ADMIN))
def rotate_device_credential(request, device_pk: uuid.UUID):
    """Rotate the credential of the node this device reports through.

    Refused on a shared gateway. The credential authenticates the connection,
    not the device, so rotating it here would cut off every other device on the
    same gateway - and the operator asking for one device would have no reason
    to expect that.
    """
    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    node = device.edge_node
    if not node.is_implicit:
        siblings = (
            Device.objects.filter(edge_node=node, deleted_at__isnull=True)
            .exclude(pk=device.pk)
            .count()
        )
        if siblings:
            raise Conflict(
                f"This device reports through edge node '{node.node_id}', which "
                f"carries {siblings} other device(s). Rotate the node's "
                f"credential instead.",
                code="shared_edge_node",
                details={"edge_node_id": str(node.pk), "sibling_count": siblings},
            )
    credential, password = edge_nodes.rotate_credential(ctx, node)
    return _credential_out(credential, password)


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


@devices_router.get("/{device_pk}/energy", response=s.DeviceEnergyOut)
def device_energy(
    request,
    device_pk: uuid.UUID,
    window: Query[TimeRangeParams],
    metric_key: str = "",
):
    """How much energy this one device consumed or produced in the window.

    Distinct from the site figures under ``/ems``: those are the site's energy
    *balance*, on a fixed 15-minute grid, and a single device is not a slice of
    them. This reads the device's own series.

    Method follows the metric, not the caller: a cumulative counter is
    differenced (exact), a power gauge is integrated (approximate, and
    ``coverage`` says how approximate). Leave ``metric_key`` empty to let the
    device's energy asset bindings choose.
    """
    from apps.telemetry import device_energy as energy_service

    ctx: AuthContext = request.auth
    device = _get_device(ctx, device_pk)
    start, end = window.normalized(default_window_seconds=24 * 3600)

    result = energy_service.device_energy(
        device, start=start, end=end, metric_key=metric_key
    )
    return {
        "device_id": device.pk,
        "metric_key": result.metric_key,
        "basis": result.basis,
        "kwh": result.kwh,
        "unit": result.unit,
        "coverage": result.coverage,
        "samples": result.samples,
        "counter_reset": result.counter_reset,
        "avg_kw": result.avg_kw,
        "peak_kw": result.peak_kw,
        "start": start,
        "end": end,
        "available_metrics": energy_service.candidate_metrics(device),
    }


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
    ctx.require_site(site.pk)
    return site


# --------------------------------------------------------------------------
# Site tree helpers
# --------------------------------------------------------------------------
def _with_own_counts(queryset):
    """Annotate each site with the counts for its own directly-assigned devices."""
    return queryset.annotate(
        device_count=Count(
            "devices", filter=Q(devices__deleted_at__isnull=True), distinct=True
        ),
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
    )


def _apply_parent(ctx: AuthContext, site: Site, parent_id: uuid.UUID | None) -> None:
    """Set ``site.parent``, refusing cycles and over-deep nesting.

    The model raises Django's ValidationError; translate it into the API's so
    the console gets the usual error envelope with a machine-readable code.
    """
    parent = _get_site(ctx, parent_id) if parent_id is not None else None
    try:
        site.validate_parent(parent)
    except DjangoValidationError as exc:
        raise ValidationError(
            "; ".join(exc.messages),
            code=getattr(exc, "code", None) or "invalid_parent",
            details={"parent_id": str(parent_id) if parent_id else None},
        ) from exc
    site.parent = parent


def _decorate_tree(ctx: AuthContext, sites, *, include_descendants: bool = False) -> None:
    """Attach depth, child_count and optional subtree totals to site instances.

    One pass over the organisation's site table rather than a query per row:
    tenants have tens of sites, not thousands, and the tree has to be walked in
    memory anyway to compute depth.
    """
    if not sites:
        return

    rows = list(
        Site.objects.filter(
            organization=ctx.organization, deleted_at__isnull=True
        ).values_list("pk", "parent_id")
    )
    parent_of = {pk: parent for pk, parent in rows}
    children_of: dict = {}
    for pk, parent in rows:
        children_of.setdefault(parent, []).append(pk)

    def depth_of(pk) -> int:
        depth, seen, node = 0, {pk}, parent_of.get(pk)
        while node is not None and node not in seen and depth <= 32:
            depth += 1
            seen.add(node)
            node = parent_of.get(node)
        return depth

    def subtree(pk) -> list:
        collected, frontier = [pk], [pk]
        while frontier:
            nxt = [
                child
                for node in frontier
                for child in children_of.get(node, [])
                if child not in collected
            ]
            collected.extend(nxt)
            frontier = nxt
        return collected

    totals: dict = {}
    if include_descendants:
        wanted = {pk for site in sites for pk in subtree(site.pk)}
        for row in _with_own_counts(
            Site.objects.filter(pk__in=wanted, deleted_at__isnull=True)
        ).values("pk", "device_count", "online_count", "open_alert_count"):
            totals[row["pk"]] = row

    for site in sites:
        site._depth_cache = depth_of(site.pk)
        site.child_count = len(children_of.get(site.pk, []))
        own_device = getattr(site, "device_count", 0) or 0
        own_online = getattr(site, "online_count", 0) or 0
        own_alerts = getattr(site, "open_alert_count", 0) or 0
        if include_descendants:
            members = [totals[pk] for pk in subtree(site.pk) if pk in totals]
            site.total_device_count = sum(row["device_count"] for row in members)
            site.total_online_count = sum(row["online_count"] for row in members)
            site.total_open_alert_count = sum(row["open_alert_count"] for row in members)
        else:
            site.total_device_count = own_device
            site.total_online_count = own_online
            site.total_open_alert_count = own_alerts


def _declaration_out(declaration: DeviceDeclaration) -> dict:
    return {
        "device_id": declaration.device_id,
        "schema_version": declaration.schema_version,
        "state": declaration.state,
        "received_at": declaration.received_at,
        "reviewed_at": declaration.reviewed_at,
        "payload": declaration.payload,
        "diff_summary": declaration.diff_summary,
        "has_differences": declaration.has_differences,
    }


def _energy_is_empty(totals: dict) -> bool:
    return not any(
        totals.get(key)
        for key in (
            "grid_import_kwh",
            "grid_export_kwh",
            "pv_kwh",
            "load_kwh",
            "battery_charge_kwh",
            "battery_discharge_kwh",
        )
    )


def _get_device(ctx: AuthContext, device_pk: uuid.UUID) -> Device:
    device = (
        Device.objects.for_organization(ctx.organization)
        .select_related("site", "device_type")
        .filter(pk=device_pk)
        .first()
    )
    if device is None:
        raise NotFound("Device not found")
    # 404 rather than 403 for an out-of-scope device: telling someone that a
    # device exists but is not theirs is itself information they do not have.
    if not ctx.allows_site(device.site_id):
        raise NotFound("Device not found")
    return device


def _assert_serial_free(
    ctx: AuthContext, serial_number: str, *, exclude_pk: uuid.UUID | None = None
) -> None:
    """Refuse a serial number another live device in this tenant already holds.

    Checked here as well as by the database constraint so the operator gets
    the *name* of the device that already has it. "Which one?" is the only
    question a duplicate-serial error provokes, and a bare 409 cannot answer
    it.

    Blank is never compared: serials are often unknown at commissioning, and
    demanding a placeholder would defeat the check far more thoroughly than
    allowing the blank does.
    """
    serial = (serial_number or "").strip()
    if not serial:
        return

    queryset = Device.objects.for_organization(ctx.organization).filter(
        serial_number=serial
    )
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    existing = queryset.only("id", "name", "device_id").first()
    if existing is None:
        return

    raise Conflict(
        f"Serial number '{serial}' is already registered to '{existing.name}'",
        code="serial_number_taken",
        details={
            "serial_number": serial,
            "device_id": str(existing.pk),
            "device_external_id": existing.device_id,
            "device_name": existing.name,
        },
    )


def _registration_conflict(ctx: AuthContext, device_id: str, serial_number: str):
    """Turn an IntegrityError on the device table into the right message.

    Two unique constraints reach the same handler; which one fired changes
    what the operator should do about it.
    """
    if serial_number:
        try:
            _assert_serial_free(ctx, serial_number)
        except Conflict as conflict:
            return conflict
    return Conflict(
        f"Device id '{device_id}' is already registered", code="device_id_taken"
    )


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


def _blueprint_out(blueprint: DeviceType, language: str) -> dict:
    return {
        "id": blueprint.id,
        "key": blueprint.key,
        "name": blueprint.name,
        "label": blueprint.label(language),
        "description_text": blueprint.describe(language),
        "category": blueprint.category,
        "manufacturer": blueprint.manufacturer,
        "model_name": blueprint.model_name,
        "description": blueprint.description,
        "translations": blueprint.translations or {},
        "icon": blueprint.icon,
        "command_definitions": blueprint.command_definitions,
        "organization_id": blueprint.organization_id,
        "created_at": blueprint.created_at,
    }


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


# --------------------------------------------------------------------------
# Edge nodes
# --------------------------------------------------------------------------
def _get_edge_node(ctx, node_pk: uuid.UUID) -> EdgeNode:
    node = EdgeNode.objects.filter(
        pk=node_pk, organization=ctx.organization, deleted_at__isnull=True
    ).first()
    if node is None:
        raise NotFound("Edge node not found")
    return node


@edge_nodes_router.get("", response=Page[s.EdgeNodeOut])
def list_edge_nodes(
    request,
    page: Query[PageParams],
    include_implicit: bool = False,
    site_id: uuid.UUID | None = None,
):
    """Gateways in this organisation.

    Implicit nodes are hidden by default. They exist to give a
    directly-connected device somewhere to hold its session, and listing them
    beside real gateways would double every device in the operator's view.
    """
    ctx: AuthContext = request.auth
    queryset = (
        EdgeNode.objects.for_organization(ctx.organization)
        .select_related("site")
        .annotate(
            device_count_annotated=Count(
                "devices", filter=Q(devices__deleted_at__isnull=True)
            )
        )
    )
    if not include_implicit:
        queryset = queryset.filter(is_implicit=False)
    if site_id:
        queryset = queryset.filter(site_id=site_id)
    return paginate(queryset.order_by("name"), page)


@edge_nodes_router.post(
    "", response={201: s.EdgeNodeCreatedOut}, auth=role_required(Role.ADMIN)
)
def create_edge_node(request, payload: s.EdgeNodeIn, issue_credential: bool = True):
    """Register a gateway. MQTT credentials are returned once, if requested."""
    ctx: AuthContext = request.auth
    site = _resolve_site(ctx, payload.site_id)
    if EdgeNode.objects.filter(
        group_id=ctx.organization.slug,
        node_id=payload.node_id,
        deleted_at__isnull=True,
    ).exists():
        raise Conflict(
            f"Edge node '{payload.node_id}' already exists in this organization",
            code="edge_node_exists",
        )

    node = EdgeNode.objects.create(
        organization=ctx.organization,
        site=site,
        node_id=payload.node_id,
        name=payload.name or payload.node_id,
        description=payload.description,
        is_enabled=payload.is_enabled,
        is_implicit=False,
    )

    credential_out = None
    if issue_credential:
        credential, password = edge_nodes.issue_credential(node)
        credential_out = _credential_out(credential, password)

    get_registry().invalidate()
    record(AuditAction.DEVICE_CREATED, ctx=ctx, target=node)
    return 201, {"edge_node": node, "credential": credential_out}


@edge_nodes_router.get("/{node_pk}", response=s.EdgeNodeOut)
def get_edge_node(request, node_pk: uuid.UUID):
    ctx: AuthContext = request.auth
    return _get_edge_node(ctx, node_pk)


@edge_nodes_router.patch(
    "/{node_pk}", response=s.EdgeNodeOut, auth=role_required(Role.ADMIN)
)
def update_edge_node(request, node_pk: uuid.UUID, payload: s.EdgeNodeUpdateIn):
    ctx: AuthContext = request.auth
    node = _get_edge_node(ctx, node_pk)
    data = payload.dict(exclude_unset=True)

    if "site_id" in data:
        node.site = _resolve_site(ctx, data.pop("site_id"))
    for field, value in data.items():
        setattr(node, field, value)
    node.save()

    if "is_enabled" in data:
        EdgeNodeCredential.objects.filter(edge_node=node).update(
            is_active=node.is_enabled
        )
    get_registry().invalidate()
    record(AuditAction.DEVICE_UPDATED, ctx=ctx, target=node)
    return node


@edge_nodes_router.delete(
    "/{node_pk}", response=OkResponse, auth=role_required(Role.ADMIN)
)
def delete_edge_node(request, node_pk: uuid.UUID):
    """Remove a gateway. Refused while devices still report through it.

    Deleting it anyway would cascade the devices away with it, taking their
    history and any energy asset bound to them - which is not what "remove this
    gateway" sounds like it does.
    """
    ctx: AuthContext = request.auth
    node = _get_edge_node(ctx, node_pk)
    attached = Device.objects.filter(edge_node=node, deleted_at__isnull=True).count()
    if attached:
        raise Conflict(
            f"Edge node '{node.node_id}' still carries {attached} device(s)",
            code="edge_node_in_use",
            details={"device_count": attached},
        )

    node.deleted_at = now()
    node.save(update_fields=["deleted_at", "updated_at"])
    EdgeNodeCredential.objects.filter(edge_node=node).update(is_active=False)
    get_registry().invalidate()
    record(AuditAction.DEVICE_DELETED, ctx=ctx, target=node)
    return {"ok": True, "message": "edge_node_deleted"}


@edge_nodes_router.post(
    "/{node_pk}/credential",
    response=s.DeviceCredentialOut,
    auth=role_required(Role.ADMIN),
)
def rotate_edge_node_credential(request, node_pk: uuid.UUID):
    ctx: AuthContext = request.auth
    node = _get_edge_node(ctx, node_pk)
    credential, password = edge_nodes.rotate_credential(ctx, node)
    return _credential_out(credential, password)


@edge_nodes_router.post(
    "/{node_pk}/rebirth", response=OkResponse, auth=role_required(Role.OPERATOR)
)
def request_edge_node_rebirth(request, node_pk: uuid.UUID):
    """Ask a node to re-announce every metric it offers.

    The operator-facing half of the recovery the worker performs automatically
    on a sequence gap. Useful after editing a device by hand, when the console
    and the node may disagree about what exists.
    """
    ctx: AuthContext = request.auth
    node = _get_edge_node(ctx, node_pk)
    sent = edge_nodes.request_rebirth(node, reason="operator")
    return {
        "ok": sent,
        "message": "rebirth_requested" if sent else "rebirth_recently_requested",
    }


# --------------------------------------------------------------------------
# Fleet-wide event log
# --------------------------------------------------------------------------
@events_router.get("", response=Page[s.DeviceEventOut])
def list_events(
    request,
    filters: Query[s.EventFilters],
    params: Query[PageParams],
    window: Query[TimeRangeParams],
    include_descendants: bool = False,
):
    """Every operation-log line the fleet reported, newest first.

    The per-device tab answers "what happened to this unit". This answers the
    question an operator actually starts with - "something odd happened around
    four o'clock, where?" - which needs the whole fleet in one place.
    """
    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=7 * 24 * 3600)

    queryset = DeviceEvent.objects.filter(
        organization=ctx.organization, ts__gte=start, ts__lt=end
    ).select_related("device", "device__site")
    # Site scope applies through the device, so a member restricted to one
    # plant cannot read another plant's events.
    queryset = queryset.filter(device__in=ctx.scope_queryset(
        Device.objects.for_organization(ctx.organization)
    ))

    if include_descendants and filters.site_id is not None:
        site_ids = descendant_site_ids([filters.site_id], organization=ctx.organization)
        filters = filters.model_copy(update={"site_id": None})
        queryset = queryset.filter(device__site_id__in=site_ids)

    queryset = filters.filter(queryset)
    return paginate(queryset.order_by("-ts", "-id"), params)


@events_router.get("/codes", response=list[s.EventCodeOut])
def list_event_codes(request, window: Query[TimeRangeParams]):
    """Distinct codes seen in the window, most frequent first.

    Populates the filter dropdown from what actually arrived rather than from a
    fixed list: the codes are the device vendor's, not this platform's, so any
    hard-coded list would be wrong for somebody.
    """
    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=7 * 24 * 3600)

    rows = (
        DeviceEvent.objects.filter(
            organization=ctx.organization, ts__gte=start, ts__lt=end
        )
        .filter(device__in=ctx.scope_queryset(
            Device.objects.for_organization(ctx.organization)
        ))
        .exclude(code="")
        .values("code")
        .annotate(count=Count("id"))
        .order_by("-count", "code")[:100]
    )
    return list(rows)
