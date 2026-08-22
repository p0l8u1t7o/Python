"""Behind-the-meter energy management endpoints."""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo

from django.db import IntegrityError
from django.db.models import Count, Q
from ninja import Query, Router

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.alerts.models import Alert, AlertStatus
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.schemas import OkResponse, Page, PageParams, TimeRangeParams, paginate
from apps.core.timeutils import now
from apps.devices.models import ConnectionStatus, Device, Site, descendant_site_ids
from apps.ems import rollup
from apps.ems.demand import demand_benefit
from apps.ems.plans import effective_plan_map
from apps.ems import schemas as s
from apps.ems.models import (
    AssetRole,
    DemandResponseEvent,
    DeviceOperatingSession,
    DispatchStrategy,
    DispatchWindow,
    EnergyAsset,
    EnergyInterval,
    EnergyIntervalCost,
    SessionKind,
    StoragePlan,
    Tariff,
)
from apps.ems.tariffs import validate_periods
from apps.telemetry.models import LatestSample

router = Router(tags=["ems"])

#: A power snapshot older than this is shown as stale rather than as "now".
FLOW_STALE_SECONDS = 300


# --------------------------------------------------------------------------
# Energy assets
# --------------------------------------------------------------------------
@router.get("/assets", response=list[s.EnergyAssetOut])
def list_assets(request, site_id: uuid.UUID | None = None):
    ctx: AuthContext = request.auth
    queryset = ctx.scope_queryset(
        EnergyAsset.objects.filter(organization=ctx.organization).select_related("device")
    )
    if site_id is not None:
        queryset = queryset.filter(site_id=site_id)
    return list(queryset.order_by("site_id", "role"))


@router.post("/assets", response={201: s.EnergyAssetOut}, auth=role_required(Role.ADMIN))
def create_asset(request, payload: s.EnergyAssetIn):
    """Bind a device and its metric keys to an energy role at a site."""
    ctx: AuthContext = request.auth
    site = _get_site(ctx, payload.site_id)
    device = _get_device(ctx, payload.device_id)
    _validate_asset_metrics(payload)

    data = payload.dict(exclude={"site_id", "device_id"})
    try:
        asset = EnergyAsset.objects.create(
            organization=ctx.organization, site=site, device=device, **data
        )
    except IntegrityError as exc:
        raise Conflict(
            "This device already has that role at this site", code="asset_exists"
        ) from exc
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=asset, payload=data)
    return 201, asset


@router.put("/assets/{asset_id}", response=s.EnergyAssetOut, auth=role_required(Role.ADMIN))
def update_asset(request, asset_id: uuid.UUID, payload: s.EnergyAssetIn):
    ctx: AuthContext = request.auth
    asset = EnergyAsset.objects.filter(
        organization=ctx.organization, pk=asset_id
    ).select_related("device").first()
    if asset is None:
        raise NotFound("Energy asset not found")

    _validate_asset_metrics(payload)
    asset.site = _get_site(ctx, payload.site_id)
    asset.device = _get_device(ctx, payload.device_id)
    for field, value in payload.dict(exclude={"site_id", "device_id"}).items():
        setattr(asset, field, value)
    asset.save()
    return asset


@router.delete("/assets/{asset_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_asset(request, asset_id: uuid.UUID):
    ctx: AuthContext = request.auth
    deleted, _ = EnergyAsset.objects.filter(
        organization=ctx.organization, pk=asset_id
    ).delete()
    if not deleted:
        raise NotFound("Energy asset not found")
    return {"ok": True, "message": "asset_deleted"}


# --------------------------------------------------------------------------
# Storage plan
# --------------------------------------------------------------------------
@router.get("/plans", response=list[s.StoragePlanOut])
def list_plans(request):
    """Every storage strategy profile of this tenant, with its bound sites."""
    ctx: AuthContext = request.auth
    plans = (
        StoragePlan.objects.filter(organization=ctx.organization)
        .select_related("tariff")
        .prefetch_related("sites")
        .order_by("name")
    )
    return [_plan_out(plan) for plan in plans]


@router.post("/plans", response={201: s.StoragePlanOut}, auth=role_required(Role.ADMIN))
def create_plan(request, payload: s.StoragePlanIn):
    ctx: AuthContext = request.auth
    tariff, workflow = _resolve_plan_relations(ctx, payload)
    if StoragePlan.objects.filter(
        organization=ctx.organization, name=payload.name
    ).exists():
        raise Conflict(
            f"A plan called '{payload.name}' already exists", code="plan_name_taken"
        )
    data = payload.dict(exclude={"tariff_id", "workflow_id"})
    plan = StoragePlan.objects.create(
        organization=ctx.organization,
        tariff=tariff,
        workflow=workflow,
        updated_by=ctx.user,
        **data,
    )
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=plan,
           payload={"plan": plan.name, "action": "created"})
    return 201, _plan_out(plan)


@router.get("/plans/{plan_id}", response=s.StoragePlanOut)
def get_plan_by_id(request, plan_id: uuid.UUID):
    ctx: AuthContext = request.auth
    plan = _get_plan(ctx, plan_id)
    return _plan_out(plan)


@router.put("/plans/{plan_id}", response=s.StoragePlanOut, auth=role_required(Role.ADMIN))
def update_plan(request, plan_id: uuid.UUID, payload: s.StoragePlanIn):
    ctx: AuthContext = request.auth
    plan = _get_plan(ctx, plan_id)
    tariff, workflow = _resolve_plan_relations(ctx, payload)
    if (
        StoragePlan.objects.filter(organization=ctx.organization, name=payload.name)
        .exclude(pk=plan.pk)
        .exists()
    ):
        raise Conflict(
            f"A plan called '{payload.name}' already exists", code="plan_name_taken"
        )
    for field, value in payload.dict(exclude={"tariff_id", "workflow_id"}).items():
        setattr(plan, field, value)
    plan.tariff = tariff
    plan.workflow = workflow
    plan.updated_by = ctx.user
    plan.save()
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=plan,
           payload={"plan": plan.name, "action": "updated"})
    return _plan_out(plan)


@router.delete("/plans/{plan_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_plan(request, plan_id: uuid.UUID):
    """Delete a profile. Bound sites are unbound (SET_NULL), not deleted -
    they simply stop being dispatched until they pick another plan."""
    ctx: AuthContext = request.auth
    plan = _get_plan(ctx, plan_id)
    unbound = plan.sites.count()
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=plan,
           payload={"plan": plan.name, "action": "deleted", "unbound_sites": unbound})
    plan.delete()
    return {"ok": True, "message": "plan_deleted"}


@router.get("/sites/{site_id}/plan", response=s.StoragePlanOut)
def get_plan(request, site_id: uuid.UUID):
    """The plan effectively driving this site - inherited from an ancestor
    when the site has no binding of its own. ``inherited_from`` names the
    ancestor so the console can say where the behaviour comes from."""
    from apps.ems.plans import effective_plan

    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    plan, source = effective_plan(site)
    if plan is None:
        raise NotFound("This site has no storage plan yet", code="plan_not_configured")
    payload = _plan_out(plan)
    payload["inherited_from"] = source.name if source is not None and source.pk != site.pk else None
    return payload


@router.put("/sites/{site_id}/plan", response=OkResponse, auth=role_required(Role.ADMIN))
def bind_plan(request, site_id: uuid.UUID, payload: s.StoragePlanBindIn):
    """Bind a site to a plan profile, or unbind it with ``plan_id: null``.

    Plans are named templates shared across sites; the parameters live on the
    plan and are edited on the plans page, not per site.
    """
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)

    plan = None
    if payload.plan_id is not None:
        plan = _get_plan(ctx, payload.plan_id)

    site.storage_plan = plan
    site.save(update_fields=["storage_plan", "updated_at"])
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=site,
           payload={"site": site.name,
                    "plan": plan.name if plan else None,
                    "action": "bound" if plan else "unbound"})
    return {"ok": True, "message": "plan_bound" if plan else "plan_unbound"}


def _get_plan(ctx: AuthContext, plan_id: uuid.UUID) -> StoragePlan:
    plan = (
        StoragePlan.objects.filter(organization=ctx.organization, pk=plan_id)
        .select_related("tariff")
        .first()
    )
    if plan is None:
        raise NotFound("Storage plan not found")
    return plan


def _resolve_plan_relations(ctx: AuthContext, payload: s.StoragePlanIn):
    """Validate the tariff/workflow the payload names, plus the SOC ranges."""
    _validate_plan(payload)

    tariff = None
    if payload.tariff_id is not None:
        tariff = Tariff.objects.filter(
            organization=ctx.organization, pk=payload.tariff_id
        ).first()
        if tariff is None:
            raise NotFound("Tariff not found")

    workflow = None
    if payload.workflow_id is not None:
        from apps.workflows.models import Workflow

        workflow = Workflow.objects.filter(
            organization=ctx.organization,
            pk=payload.workflow_id,
            deleted_at__isnull=True,
        ).first()
        if workflow is None:
            raise NotFound("Workflow not found")

    # A workflow strategy with nothing to run would silently do nothing, which
    # looks exactly like a working plan on a settings page.
    if payload.strategy == DispatchStrategy.WORKFLOW and workflow is None:
        raise ValidationError(
            "Select a workflow, or choose a different strategy",
            code="workflow_required",
        )
    return tariff, workflow


# --------------------------------------------------------------------------
# Demand response
# --------------------------------------------------------------------------
def _dr_out(event: DemandResponseEvent, moment=None) -> dict:
    moment = moment or now()
    return {
        "id": event.id,
        "site_id": event.site_id,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "target_power_kw": event.target_power_kw,
        "cancelled_at": event.cancelled_at,
        "note": event.note,
        "source": event.source,
        "created_at": event.created_at,
        "is_active": event.is_live(moment),
    }


@router.get("/sites/{site_id}/demand-response", response=list[s.DemandResponseOut])
def list_dr_events(request, site_id: uuid.UUID):
    """Recent DR events for a site, newest first."""
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    moment = now()
    events = DemandResponseEvent.objects.filter(site=site).order_by("-starts_at")[:20]
    return [_dr_out(event, moment) for event in events]


@router.post(
    "/sites/{site_id}/demand-response",
    response={201: s.DemandResponseOut},
    auth=role_required(Role.OPERATOR),
)
def trigger_dr_event(request, site_id: uuid.UUID, payload: s.DemandResponseIn):
    """Commit the site's battery to a discharge, starting now (or later).

    While the event is live it outranks the strategy, the scheduled windows
    and even a workflow takeover - DR is a commitment to the grid operator.
    The plan envelope and health constraints still clamp it: a commitment
    beyond the hardware is still a lie.
    """
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)

    starts_at = payload.starts_at or now()
    ends_at = starts_at + dt.timedelta(minutes=payload.duration_minutes)

    overlapping = DemandResponseEvent.objects.filter(
        site=site,
        cancelled_at__isnull=True,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exists()
    if overlapping:
        raise Conflict(
            "A demand-response event already covers part of this window",
            code="dr_overlap",
        )

    event = DemandResponseEvent.objects.create(
        organization=ctx.organization,
        site=site,
        starts_at=starts_at,
        ends_at=ends_at,
        target_power_kw=payload.target_power_kw,
        note=payload.note,
        source="api" if request.headers.get("X-Api-Key") else "manual",
        created_by=ctx.user,
    )
    record(AuditAction.EMS_DISPATCH, ctx=ctx, target=event,
           payload={"site": site.name, "target_power_kw": payload.target_power_kw,
                    "duration_minutes": payload.duration_minutes,
                    "action": "dr_triggered"})
    return 201, _dr_out(event)


@router.post(
    "/demand-response/{event_id}/cancel",
    response=s.DemandResponseOut,
    auth=role_required(Role.OPERATOR),
)
def cancel_dr_event(request, event_id: uuid.UUID):
    ctx: AuthContext = request.auth
    event = DemandResponseEvent.objects.filter(
        pk=event_id, organization=ctx.organization
    ).select_related("site").first()
    if event is None:
        raise NotFound("Demand-response event not found")
    if event.cancelled_at is None and event.ends_at > now():
        event.cancelled_at = now()
        event.save(update_fields=["cancelled_at", "updated_at"])
        record(AuditAction.EMS_DISPATCH, ctx=ctx, target=event,
               payload={"site": event.site.name, "action": "dr_cancelled"})
    return _dr_out(event)


# --------------------------------------------------------------------------
# Tariffs
# --------------------------------------------------------------------------
@router.get("/tariffs/presets", response=list[s.TariffPresetOut])
def tariff_presets(request):
    """Bundled Taipower TOU rate tables.

    Posted tariffs, not an API: Taipower has no public real-time price feed,
    so the console ships the current posted tables and lets the operator
    apply, then adjust them. Each preset names its tariff year.
    """
    from apps.ems.taipower import presets

    return presets()


@router.get("/tariffs", response=list[s.TariffOut])
def list_tariffs(request):
    ctx: AuthContext = request.auth
    return list(Tariff.objects.filter(organization=ctx.organization).order_by("name"))


@router.post("/tariffs", response={201: s.TariffOut}, auth=role_required(Role.ADMIN))
def create_tariff(request, payload: s.TariffIn):
    ctx: AuthContext = request.auth
    _validate_tariff(payload, ctx.organization)
    try:
        tariff = Tariff.objects.create(organization=ctx.organization, **payload.dict())
    except IntegrityError as exc:
        raise Conflict(
            f"A tariff named '{payload.name}' already exists", code="name_taken"
        ) from exc
    return 201, tariff


@router.put("/tariffs/{tariff_id}", response=s.TariffOut, auth=role_required(Role.ADMIN))
def update_tariff(request, tariff_id: uuid.UUID, payload: s.TariffIn):
    ctx: AuthContext = request.auth
    tariff = Tariff.objects.filter(organization=ctx.organization, pk=tariff_id).first()
    if tariff is None:
        raise NotFound("Tariff not found")
    _validate_tariff(payload, ctx.organization)
    for field, value in payload.dict().items():
        setattr(tariff, field, value)
    tariff.save()
    return tariff


@router.delete("/tariffs/{tariff_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_tariff(request, tariff_id: uuid.UUID):
    ctx: AuthContext = request.auth
    tariff = Tariff.objects.filter(organization=ctx.organization, pk=tariff_id).first()
    if tariff is None:
        raise NotFound("Tariff not found")
    in_use = StoragePlan.objects.filter(tariff=tariff).count()
    if in_use:
        raise Conflict(
            f"{in_use} site plan(s) still reference this tariff", code="tariff_in_use"
        )
    tariff.delete()
    return {"ok": True, "message": "tariff_deleted"}


# --------------------------------------------------------------------------
# Live overview and reporting
# --------------------------------------------------------------------------
@router.get("/sites/{site_id}/overview", response=s.SiteOverviewOut)
def site_overview(request, site_id: uuid.UUID):
    """Current power flows plus today's energy totals for one site."""
    ctx: AuthContext = request.auth
    from apps.ems.plans import effective_plan

    site = _get_site(ctx, site_id)
    plan = effective_plan(site)[0]

    flow = _current_flow(site)
    day_start, day_end = _local_day_bounds(site)
    today = _totals(site, day_start, day_end, plan)

    device_stats = Device.objects.filter(site=site, deleted_at__isnull=True).aggregate(
        total=Count("id"),
        online=Count("id", filter=Q(status=ConnectionStatus.ONLINE)),
    )
    open_alerts = (
        Device.objects.filter(site=site, deleted_at__isnull=True)
        .aggregate(
            count=Count("alerts", filter=~Q(alerts__status=AlertStatus.RESOLVED))
        )
        .get("count")
        or 0
    )

    return {
        "site_id": site.id,
        "site_name": site.name,
        "strategy": plan.strategy if plan else None,
        "contract_capacity_kw": plan.contract_capacity_kw if plan else None,
        "usable_capacity_kwh": plan.usable_capacity_kwh if plan else None,
        "flow": flow,
        "today": today,
        "device_count": device_stats["total"] or 0,
        "online_count": device_stats["online"] or 0,
        "open_alert_count": open_alerts,
    }


@router.get("/live", response=s.FleetLiveOut)
def fleet_live(request, include_inactive: bool = False):
    """Current power at every site the caller can see, plus today's totals.

    The overview needs a row per site *and* a headline figure. Calling
    ``/sites/{id}/overview`` once per site would be N round trips and N x 3
    queries; this walks each table once.

    Power sums across sites, and this endpoint does sum it - two plants each
    drawing 100 kW really are drawing 200 kW right now. Peak demand does
    *not* work that way, which is why there is deliberately no peak figure
    here; ``/ems/sites/{id}/summary`` carries that, with its ``peak_basis``
    caveat attached.
    """
    ctx: AuthContext = request.auth

    sites = ctx.scope_queryset(
        Site.objects.filter(
            organization=ctx.organization, deleted_at__isnull=True
        ).order_by("name"),
        field="id",
    )
    if not include_inactive:
        sites = sites.filter(is_active=True)
    sites = list(sites)
    if not sites:
        return {"totals": {"is_stale": True}, "sites": []}

    site_ids = [site.pk for site in sites]
    depths = _depth_map(ctx)

    device_rows = {
        row["site_id"]: row
        for row in Device.objects.filter(
            organization=ctx.organization, site_id__in=site_ids, deleted_at__isnull=True
        )
        .values("site_id")
        .annotate(
            total=Count("id"),
            online=Count("id", filter=Q(status=ConnectionStatus.ONLINE)),
        )
    }
    alert_rows = {
        row["device__site_id"]: row["count"]
        for row in Alert.objects.filter(
            organization=ctx.organization, device__site_id__in=site_ids
        )
        .exclude(status=AlertStatus.RESOLVED)
        .values("device__site_id")
        .annotate(count=Count("id"))
    }
    reporting = ctx.organization.reporting_currency
    currencies = rollup.currency_by_site(site_ids, default=reporting)

    rows: list[dict] = []
    totals = {"grid_kw": 0.0, "pv_kw": 0.0, "load_kw": 0.0, "battery_kw": 0.0}
    contributions = dict.fromkeys(totals, 0)
    newest = None
    reporting = 0
    # Sites that could report at all. A parent that only groups its children
    # has nothing to be stale about and must not drag the count down.
    equipped = 0
    soc_weighted = soc_weight = 0.0
    day_cost = day_savings = day_load = day_pv = 0.0

    for site in sites:
        flow = _current_flow(site)
        day_start, day_end = _local_day_bounds(site)
        today = rollup.energy_totals(
            [site.pk], day_start, day_end, default_currency=reporting
        )

        devices = device_rows.get(site.pk, {})
        stale = bool(flow.get("is_stale", True))
        if (devices.get("total", 0) or 0) > 0:
            equipped += 1
        if not stale:
            reporting += 1
            for key in totals:
                value = flow.get(key)
                if value is not None:
                    totals[key] += value
                    contributions[key] += 1
            if flow.get("as_of") is not None:
                newest = (
                    flow["as_of"] if newest is None else max(newest, flow["as_of"])
                )
            soc = flow.get("battery_soc_percent")
            if soc is not None:
                # Weighted by usable capacity: a 1 MWh pack at 20% and a 10 kWh
                # pack at 100% do not average to 60% in any useful sense.
                weight = _battery_capacity_kwh(site) or 1.0
                soc_weighted += soc * weight
                soc_weight += weight

        savings = today.get("estimated_savings")
        day_cost += today.get("energy_cost") or 0.0
        day_savings += savings or 0.0
        day_load += today.get("load_kwh") or 0.0
        day_pv += today.get("pv_kwh") or 0.0

        rows.append(
            {
                "site_id": site.pk,
                "site_name": site.name,
                "parent_id": site.parent_id,
                "depth": depths.get(site.pk, 0),
                "flow": flow,
                "device_count": devices.get("total", 0) or 0,
                "online_count": devices.get("online", 0) or 0,
                "open_alert_count": alert_rows.get(site.pk, 0),
                "today_load_kwh": today.get("load_kwh") or 0.0,
                "today_energy_cost": today.get("energy_cost") or 0.0,
                "today_estimated_savings": savings,
                "currency": currencies.get(site.pk, ""),
                "is_stale": stale,
            }
        )

    distinct = {code for code in currencies.values() if code}
    return {
        "as_of": newest,
        "totals": {
            **{
                key: (round(value, 3) if contributions[key] else None)
                for key, value in totals.items()
            },
            "battery_soc_percent": (
                round(soc_weighted / soc_weight, 1) if soc_weight else None
            ),
            "as_of": newest,
            "is_stale": reporting == 0,
        },
        "battery_soc_percent": (
            round(soc_weighted / soc_weight, 1) if soc_weight else None
        ),
        "site_count": equipped,
        "reporting_site_count": reporting,
        "currency": distinct.pop() if len(distinct) == 1 else "",
        "mixed_currency": len(distinct) > 1,
        "today_energy_cost": round(day_cost, 2),
        "today_estimated_savings": round(day_savings, 2),
        "today_load_kwh": round(day_load, 3),
        "today_pv_kwh": round(day_pv, 3),
        "sites": rows,
    }


@router.get("/sites/{site_id}/investment", response=s.SiteInvestmentOut)
def site_investment(request, site_id: uuid.UUID, window: Query[TimeRangeParams]):
    """What the equipment at this site cost, and its share of the window.

    Reported next to the energy cost rather than mixed into it. Capital is not
    a cost of moving energy: folding an amortised purchase price into the
    interval costs would make "what did this interval cost" mean two things at
    once, and it would double count against the battery cycle charge, which is
    already that purchase price expressed per kWh of throughput.
    """
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)

    devices = list(
        Device.objects.filter(
            organization=ctx.organization, site=site, deleted_at__isnull=True
        ).select_related("device_type")
    )

    rows = []
    total_capital = total_annual = 0.0
    missing = 0
    currencies: set[str] = set()

    for device in devices:
        annual = device.annual_cost
        if device.capital_cost is None and annual is None:
            missing += 1
            continue
        if device.cost_currency:
            currencies.add(device.cost_currency)
        total_capital += device.capital_cost or 0.0
        total_annual += annual or 0.0
        rows.append(
            {
                "device_id": device.pk,
                "device_name": device.name,
                "device_external_id": device.device_id,
                "category": (
                    device.device_type.category if device.device_type_id else ""
                ),
                "capital_cost": device.capital_cost,
                "annual_cost": None if annual is None else round(annual, 2),
                "commissioned_on": device.commissioned_on,
                "expected_life_years": device.expected_life_years,
            }
        )

    years = (end - start).total_seconds() / (365.25 * 24 * 3600)
    if not currencies:
        # Nothing said otherwise, so fall back to what the site bills in.
        currencies = {
            code
            for code in [
                rollup.currency_for(
                    [site.pk], default=ctx.organization.reporting_currency
                )
            ]
            if code
        }

    return {
        "site_id": site.pk,
        "start": start,
        "end": end,
        "currency": currencies.pop() if len(currencies) == 1 else "",
        "total_capital_cost": round(total_capital, 2),
        "total_annual_cost": round(total_annual, 2),
        "window_amortised_cost": round(total_annual * years, 2),
        "devices_without_cost": missing,
        "devices": rows,
    }


@router.get("/cost-overview", response=s.CostOverviewOut)
def cost_overview(request, window: Query[TimeRangeParams], include_inactive: bool = False):
    """Cost and estimated savings for every site, in one request.

    The dashboard needs a row per site; asking the per-site summary endpoint
    once per site would be one query per site plus one round trip per site.
    This walks the interval table once, grouped.

    Sites with no intervals in the window are still returned, at zero, so the
    chart's category axis stays stable while data trickles in rather than
    having bars appear and disappear between refreshes.
    """
    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=24 * 3600)

    sites = ctx.scope_queryset(
        Site.objects.filter(
            organization=ctx.organization, deleted_at__isnull=True
        ).order_by("name"),
        field="id",
    )
    if not include_inactive:
        sites = sites.filter(is_active=True)
    sites = list(sites)
    if not sites:
        return {"start": start, "end": end, "sites": []}

    site_ids = [site.pk for site in sites]
    costs = rollup.cost_by_site(site_ids, start, end)
    demand = rollup.demand_by_site(site_ids, start, end)
    plans = effective_plan_map(ctx.organization)
    currencies = rollup.currency_by_site(
        site_ids, default=ctx.organization.reporting_currency
    )
    depths = _depth_map(ctx)
    device_counts = {
        row["site_id"]: row["count"]
        for row in Device.objects.filter(
            organization=ctx.organization, site_id__in=site_ids, deleted_at__isnull=True
        )
        .values("site_id")
        .annotate(count=Count("id"))
    }

    rows = []
    for site in sites:
        figures = costs.get(site.pk, {})
        plan = (plans.get(site.pk) or (None, None))[0]
        benefit = demand_benefit(
            peak_demand_kw=demand.get(site.pk, {}).get("peak_demand_kw"),
            baseline_peak_kw=demand.get(site.pk, {}).get("baseline_peak_kw"),
            contract_capacity_kw=plan.contract_capacity_kw if plan else None,
            demand_charge_per_kw=(
                plan.tariff.demand_charge_per_kw if plan and plan.tariff else None
            ),
        )
        rows.append(
            {
                **benefit.as_dict(),
                "site_id": site.pk,
                "site_name": site.name,
                "parent_id": site.parent_id,
                "depth": depths.get(site.pk, 0),
                "energy_cost": figures.get("energy_cost", 0.0),
                "export_revenue": figures.get("export_revenue", 0.0),
                "estimated_savings": figures.get("estimated_savings", 0.0),
                "grid_import_kwh": figures.get("grid_import_kwh", 0.0),
                "load_kwh": figures.get("load_kwh", 0.0),
                "device_count": device_counts.get(site.pk, 0),
                "currency": currencies.get(site.pk, ""),
            }
        )

    distinct = {row["currency"] for row in rows if row["currency"]}
    return {
        "start": start,
        "end": end,
        "currency": distinct.pop() if len(distinct) == 1 else "",
        "mixed_currency": len(distinct) > 1,
        "total_energy_cost": round(sum(row["energy_cost"] for row in rows), 2),
        "total_export_revenue": round(sum(row["export_revenue"] for row in rows), 2),
        "total_estimated_savings": round(
            sum(row["estimated_savings"] for row in rows), 2
        ),
        "total_demand_savings": round(sum(row["demand_savings"] for row in rows), 2),
        "sites": rows,
    }


@router.get("/sites/{site_id}/intervals", response=list[s.EnergyIntervalOut])
def site_intervals(
    request, site_id: uuid.UUID, window: Query[TimeRangeParams], limit: int = 5000
):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    start, end = window.normalized(default_window_seconds=24 * 3600)
    return list(
        EnergyInterval.objects.filter(
            site=site, interval_start__gte=start, interval_start__lt=end
        ).order_by("interval_start")[: min(limit, 20000)]
    )


@router.get("/sites/{site_id}/summary", response=s.EnergyTotalsOut)
def site_summary(
    request,
    site_id: uuid.UUID,
    window: Query[TimeRangeParams],
    include_descendants: bool = False,
):
    """Energy, cost and self-consumption totals over an arbitrary window.

    With ``include_descendants`` the whole subtree is rolled up. Read
    ``peak_basis`` before quoting the peak: across several sites it is a
    coincident estimate, not a meter reading.
    """
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)

    if include_descendants:
        site_ids = descendant_site_ids([site.pk], organization=ctx.organization)
        if len(site_ids) > 1:
            return _totals_for_sites(
                site_ids, start, end, ctx.organization.reporting_currency
            )

    from apps.ems.plans import effective_plan

    plan = effective_plan(site)[0]
    return _totals(site, start, end, plan)


@router.post("/sites/{site_id}/rebuild-intervals", response=OkResponse, auth=role_required(Role.ADMIN))
def rebuild_intervals(request, site_id: uuid.UUID, window: Query[TimeRangeParams]):
    """Recompute intervals, e.g. after fixing an asset's metric binding."""
    from apps.ems.aggregator import SiteAggregator

    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    start, end = window.normalized(default_window_seconds=24 * 3600)
    if (end - start).total_seconds() > 90 * 24 * 3600:
        raise ValidationError(
            "Rebuild window is limited to 90 days per request", code="window_too_large"
        )
    count = SiteAggregator(site).run(start, end)
    return {"ok": True, "message": f"rebuilt_{count}_intervals"}


# --------------------------------------------------------------------------
# Operating sessions
# --------------------------------------------------------------------------
@router.get("/sessions", response=Page[s.OperatingSessionOut])
def list_sessions(
    request,
    params: Query[PageParams],
    window: Query[TimeRangeParams],
    site_id: uuid.UUID | None = None,
    device_pk: uuid.UUID | None = None,
    kind: str | None = None,
    open_only: bool = False,
):
    """Charge / discharge / running sessions, newest first.

    The window filters on ``started_at``, so a session that began before the
    window and is still running is *not* returned by a narrow window. That is
    deliberate - "sessions that started today" is the question this answers;
    use ``open_only`` for "what is running right now", which ignores the
    window entirely.
    """
    ctx: AuthContext = request.auth
    queryset = ctx.scope_queryset(
        DeviceOperatingSession.objects.filter(
            organization=ctx.organization
        ).select_related("device"),
        field="device__site_id",
    )

    if site_id is not None:
        _get_site(ctx, site_id)
        queryset = queryset.filter(
            device__site_id__in=descendant_site_ids(
                [site_id], organization=ctx.organization
            )
        )
    if device_pk is not None:
        queryset = queryset.filter(device_id=device_pk)
    if kind:
        queryset = queryset.filter(kind=kind)

    if open_only:
        queryset = queryset.filter(ended_at__isnull=True)
    elif window.start or window.end:
        start, end = window.normalized(default_window_seconds=30 * 24 * 3600)
        queryset = queryset.filter(started_at__gte=start, started_at__lt=end)

    return paginate(queryset.order_by("-started_at"), params)


@router.get("/sessions/summary", response=list[s.SessionSummaryOut])
def session_summary(
    request,
    window: Query[TimeRangeParams],
    site_id: uuid.UUID | None = None,
    device_pk: uuid.UUID | None = None,
):
    """Counts, durations and energy per session kind.

    Open sessions contribute their count but not their duration: a session
    that has not ended has no length yet, and pretending it does would drag
    every average towards whatever moment the report was run.
    """
    from django.db.models import Avg, Max, Sum

    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)

    queryset = ctx.scope_queryset(
        DeviceOperatingSession.objects.filter(
            organization=ctx.organization, started_at__gte=start, started_at__lt=end
        ),
        field="device__site_id",
    )
    if site_id is not None:
        _get_site(ctx, site_id)
        queryset = queryset.filter(
            device__site_id__in=descendant_site_ids(
                [site_id], organization=ctx.organization
            )
        )
    if device_pk is not None:
        queryset = queryset.filter(device_id=device_pk)

    rows = []
    for kind in SessionKind.values:
        subset = queryset.filter(kind=kind)
        closed = subset.filter(ended_at__isnull=False)
        totals = subset.aggregate(
            count=Count("id"), energy=Sum("energy_kwh"), peak=Max("peak_kw")
        )
        durations = closed.aggregate(total=Sum("duration_s"), average=Avg("duration_s"))
        rows.append(
            {
                "kind": kind,
                "count": totals["count"] or 0,
                "total_energy_kwh": round(totals["energy"] or 0.0, 3),
                "total_duration_s": int(durations["total"] or 0),
                "avg_duration_s": (
                    round(durations["average"], 1) if durations["average"] else None
                ),
                "max_peak_kw": totals["peak"],
                "last_started_at": subset.order_by("-started_at")
                .values_list("started_at", flat=True)
                .first(),
                "open_count": subset.filter(ended_at__isnull=True).count(),
            }
        )
    return rows


@router.post(
    "/sessions/rebuild", response=OkResponse, auth=role_required(Role.ADMIN)
)
def rebuild_sessions(
    request, window: Query[TimeRangeParams], device_pk: uuid.UUID | None = None
):
    """Recompute sessions over a window - the manual counterpart of the job.

    Mirrors ``POST /ems/sites/{id}/rebuild-intervals``: same shape, same reason
    to exist. Repair a gap after fixing a metric binding, without waiting for
    the schedule to reach that far back.
    """
    from apps.ems.sessions import rebuild_organization

    ctx: AuthContext = request.auth
    start, end = window.normalized(default_window_seconds=24 * 3600)
    if (end - start).total_seconds() > 90 * 24 * 3600:
        raise ValidationError(
            "Rebuild window is limited to 90 days per request", code="window_too_large"
        )
    if device_pk is not None:
        _get_device(ctx, device_pk)

    result = rebuild_organization(
        ctx.organization, since=start, until=end, device_id=device_pk
    )
    return {
        "ok": True,
        "message": f"rebuilt_{result.written}_sessions",
    }


# --------------------------------------------------------------------------
# Cost breakdown
# --------------------------------------------------------------------------
@router.get("/cost-models", response=list[s.CostModelOut])
def list_cost_models(request):
    """Registered cost models, and which asset roles default to them.

    Exposed so the console can offer the real list rather than a hard-coded
    copy that drifts the first time somebody registers a new one.
    """
    from apps.ems import costs

    defaults: dict[str, list[str]] = {}
    for role, key in costs.ROLE_DEFAULTS.items():
        defaults.setdefault(key, []).append(role)
    return [
        {"key": key, "default_for": sorted(defaults.get(key, []))}
        for key in costs.available()
    ]


@router.get("/sites/{site_id}/cost-breakdown", response=s.CostBreakdownOut)
def site_cost_breakdown(request, site_id: uuid.UUID, window: Query[TimeRangeParams]):
    """What each source cost this site over the window.

    The totals on the site summary keep their old meaning - grid only. This is
    the layer underneath, and it is the only place that knows a generator
    burns fuel or that a battery cycle wears the pack.
    """
    from django.db.models import Sum

    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)

    rows = (
        EnergyIntervalCost.objects.filter(
            interval__site=site,
            interval__interval_start__gte=start,
            interval__interval_start__lt=end,
        )
        .values("source", "cost_model", "currency")
        .annotate(energy=Sum("energy_kwh"), amount=Sum("amount"))
        .order_by("source")
    )

    # The worst basis in a group decides the group's: one estimated interval
    # makes the total an estimate, and reporting it as measured would overstate
    # how much the number can be leaned on.
    rank = {"unknown": 0, "estimated": 1, "measured": 2}
    bases: dict[tuple[str, str], str] = {}
    for source, model, basis in EnergyIntervalCost.objects.filter(
        interval__site=site,
        interval__interval_start__gte=start,
        interval__interval_start__lt=end,
    ).values_list("source", "cost_model", "basis"):
        key = (source, model)
        current = bases.get(key)
        if current is None or rank.get(basis, 0) < rank.get(current, 0):
            bases[key] = basis

    currencies = {row["currency"] for row in rows if row["currency"]}
    output = [
        {
            "source": row["source"],
            "cost_model": row["cost_model"],
            "energy_kwh": round(row["energy"] or 0.0, 3),
            "amount": round(row["amount"] or 0.0, 2),
            "unit_cost": (
                round((row["amount"] or 0.0) / row["energy"], 4)
                if row["energy"]
                else None
            ),
            "basis": bases.get((row["source"], row["cost_model"]), "estimated"),
        }
        for row in rows
    ]

    return {
        "site_id": site.pk,
        "start": start,
        "end": end,
        "currency": (
            currencies.pop()
            if len(currencies) == 1
            else ("" if currencies else ctx.organization.reporting_currency)
        ),
        "total_amount": round(sum(row["amount"] for row in output), 2),
        "rows": output,
        "unknown_savings_intervals": EnergyInterval.objects.filter(
            site=site,
            interval_start__gte=start,
            interval_start__lt=end,
            estimated_savings__isnull=True,
        ).count(),
    }


# --------------------------------------------------------------------------
# Dispatch windows
# --------------------------------------------------------------------------
@router.get("/dispatch-windows", response=list[s.DispatchWindowOut])
def list_dispatch_windows(request, site_id: uuid.UUID | None = None):
    ctx: AuthContext = request.auth
    queryset = ctx.scope_queryset(
        DispatchWindow.objects.filter(organization=ctx.organization)
    )
    if site_id is not None:
        queryset = queryset.filter(site_id=site_id)
    return list(queryset.order_by("starts_at"))


@router.post("/dispatch-windows", response={201: s.DispatchWindowOut}, auth=role_required(Role.OPERATOR))
def create_dispatch_window(request, payload: s.DispatchWindowIn):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, payload.site_id)
    if payload.ends_at <= payload.starts_at:
        raise ValidationError("ends_at must be after starts_at", code="invalid_range")

    window = DispatchWindow.objects.create(
        organization=ctx.organization,
        site=site,
        created_by=ctx.user,
        **payload.dict(exclude={"site_id"}),
    )
    record(AuditAction.EMS_DISPATCH, ctx=ctx, target=window, payload=payload.dict())
    return 201, window


@router.get("/dispatch-windows/preview", response=list[s.DispatchDecisionOut])
def preview_dispatch(request):
    """What the dispatch engine would send right now, without sending it.

    The point of this endpoint is that an operator can answer "why is the
    battery idle?" before trusting the automation - the engine's own reasoning,
    including any clamp the storage plan applied, rather than an inference from
    the command log.
    """
    from apps.ems import dispatch as dispatch_engine

    ctx: AuthContext = request.auth
    site_ids = list(
        ctx.scope_queryset(
            Site.objects.filter(
                organization=ctx.organization,
                storage_plan__is_enabled=True,
                deleted_at__isnull=True,
            ),
            field="pk",
        ).values_list("pk", flat=True)
    )
    names = dict(
        Site.objects.filter(pk__in=site_ids).values_list("pk", "name")
    )

    output = []
    for site_id in site_ids:
        decision = dispatch_engine.decide(site_id)
        output.append(
            {
                "site_id": site_id,
                "site_name": names.get(site_id, ""),
                "device_id": decision.device.pk if decision.device else None,
                "device_external_id": (
                    decision.device.device_id if decision.device else ""
                ),
                "power_w": decision.power_w,
                "window_id": decision.window.pk if decision.window else None,
                "reason": decision.reason,
                "clamped_from_w": decision.clamped_from_w,
                "skipped": decision.skipped,
            }
        )
    return output


@router.post(
    "/dispatch-windows/run",
    response=list[s.DispatchDecisionOut],
    auth=role_required(Role.OPERATOR),
)
def run_dispatch_now(request, dry_run: bool = False):
    """Run the dispatch engine immediately instead of waiting for the cycle.

    Idempotent in the way that matters: the engine only issues a command when
    the target has actually moved, so pressing this twice sends one setpoint,
    not two.
    """
    from apps.ems import dispatch as dispatch_engine

    ctx: AuthContext = request.auth
    decisions = dispatch_engine.run_organization(ctx.organization, dry_run=dry_run)
    names = dict(
        Site.objects.filter(
            pk__in=[decision.site_id for decision in decisions]
        ).values_list("pk", "name")
    )
    record(
        AuditAction.EMS_DISPATCH,
        ctx=ctx,
        payload={"manual": True, "dry_run": dry_run, "sites": len(decisions)},
    )
    return [
        {
            "site_id": decision.site_id,
            "site_name": names.get(decision.site_id, ""),
            "device_id": decision.device.pk if decision.device else None,
            "device_external_id": (
                decision.device.device_id if decision.device else ""
            ),
            "power_w": decision.power_w,
            "window_id": decision.window.pk if decision.window else None,
            "reason": decision.reason,
            "clamped_from_w": decision.clamped_from_w,
            "skipped": decision.skipped,
        }
        for decision in decisions
    ]


@router.delete("/dispatch-windows/{window_id}", response=OkResponse, auth=role_required(Role.OPERATOR))
def delete_dispatch_window(request, window_id: uuid.UUID):
    ctx: AuthContext = request.auth
    deleted, _ = DispatchWindow.objects.filter(
        organization=ctx.organization, pk=window_id
    ).delete()
    if not deleted:
        raise NotFound("Dispatch window not found")
    return {"ok": True, "message": "window_deleted"}


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


def _depth_map(ctx: AuthContext) -> dict:
    """Depth of every site in the tenant, from one pass over (pk, parent_id).

    Walking ``site.ancestors()`` per row is a query per level per site; the
    tree is small enough to resolve in memory instead. The visited set is
    there because a cycle reaching the database must not hang the request.
    """
    rows = list(
        Site.objects.filter(
            organization=ctx.organization, deleted_at__isnull=True
        ).values_list("pk", "parent_id")
    )
    parent_of = dict(rows)

    depths: dict = {}
    for pk, _parent in rows:
        depth, node, seen = 0, parent_of.get(pk), {pk}
        while node is not None and node not in seen and depth <= 32:
            depth += 1
            seen.add(node)
            node = parent_of.get(node)
        depths[pk] = depth
    return depths


def _get_device(ctx: AuthContext, device_pk: uuid.UUID) -> Device:
    device = Device.objects.for_organization(ctx.organization).filter(pk=device_pk).first()
    if device is None:
        raise NotFound("Device not found")
    if not ctx.allows_site(device.site_id):
        raise NotFound("Device not found")
    return device


def _current_flow(site: Site) -> dict:
    """Assemble the instantaneous power balance from the latest-value table."""
    assets = list(
        EnergyAsset.objects.filter(site=site, is_active=True).select_related("device")
    )
    if not assets:
        return {"is_stale": True}

    wanted: set[tuple[uuid.UUID, str]] = set()
    for asset in assets:
        for metric in (asset.power_metric, asset.soc_metric, asset.soh_metric):
            if metric:
                wanted.add((asset.device_id, metric))
    if not wanted:
        return {"is_stale": True}

    rows = LatestSample.objects.filter(
        device_id__in={device for device, _ in wanted}
    ).values_list("device_id", "metric_key", "value", "ts")
    lookup = {(device, metric): (value, ts) for device, metric, value, ts in rows}

    totals: dict[str, float] = {}
    newest: dt.datetime | None = None
    soc_values: list[float] = []
    soh_values: list[float] = []

    for asset in assets:
        if asset.power_metric:
            entry = lookup.get((asset.device_id, asset.power_metric))
            if entry and entry[0] is not None:
                value = asset.normalize_power(entry[0])
                totals[asset.role] = totals.get(asset.role, 0.0) + value
                newest = entry[1] if newest is None else max(newest, entry[1])
        if asset.soc_metric:
            entry = lookup.get((asset.device_id, asset.soc_metric))
            if entry and entry[0] is not None:
                soc_values.append(entry[0])
        if asset.soh_metric:
            entry = lookup.get((asset.device_id, asset.soh_metric))
            if entry and entry[0] is not None:
                soh_values.append(entry[0])

    grid = totals.get(AssetRole.GRID_METER)
    pv = totals.get(AssetRole.PV)
    battery = totals.get(AssetRole.BATTERY)
    load = totals.get(AssetRole.LOAD_METER)
    if load is None and grid is not None:
        # Node balance: load = grid + pv + battery discharge.
        load = grid + (pv or 0.0) + (battery or 0.0)

    is_stale = newest is None or (now() - newest).total_seconds() > FLOW_STALE_SECONDS
    return {
        "grid_kw": _round(grid),
        "pv_kw": _round(pv),
        "load_kw": _round(load),
        "battery_kw": _round(battery),
        "battery_soc_percent": _round(
            sum(soc_values) / len(soc_values) if soc_values else None
        ),
        "battery_soh_percent": _round(
            sum(soh_values) / len(soh_values) if soh_values else None
        ),
        "as_of": newest,
        "is_stale": is_stale,
    }


def _battery_capacity_kwh(site: Site) -> float | None:
    """Usable battery capacity at a site, for weighting an average SOC.

    Prefers the assets' nameplate over the storage plan: the plan is a
    site-level setting an operator typed, the asset ratings describe the packs
    that are actually there.
    """
    rated = [
        value
        for value in EnergyAsset.objects.filter(
            site=site, role=AssetRole.BATTERY, is_active=True
        ).values_list("rated_energy_kwh", flat=True)
        if value
    ]
    if rated:
        return sum(rated)
    from apps.ems.plans import effective_plan

    plan = effective_plan(site)[0]
    return plan.usable_capacity_kwh if plan else None


def _totals(site: Site, start: dt.datetime, end: dt.datetime, plan) -> dict:
    """Per-site totals. Thin wrapper over the shared multi-site roll-up."""
    totals = rollup.energy_totals(
        [site.pk], start, end, default_currency=site.organization.reporting_currency
    )
    if plan is not None and plan.tariff_id:
        totals["currency"] = plan.tariff.currency
    return totals


def _totals_for_sites(
    site_ids, start: dt.datetime, end: dt.datetime, default_currency: str = ""
) -> dict:
    return rollup.energy_totals(
        site_ids, start, end, default_currency=default_currency
    )


def _local_day_bounds(site: Site) -> tuple[dt.datetime, dt.datetime]:
    """Midnight-to-midnight in the site's own timezone."""
    try:
        zone = zoneinfo.ZoneInfo(site.timezone_name or "UTC")
    except Exception:  # noqa: BLE001 - a misconfigured site should still render
        zone = dt.timezone.utc
    local_now = now().astimezone(zone)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(dt.timezone.utc), local_now.astimezone(dt.timezone.utc)


def _plan_out(plan: StoragePlan) -> dict:
    return {
        "id": plan.id,
        "name": plan.name,
        "sites": [
            {"id": site.id, "name": site.name}
            for site in plan.sites.filter(deleted_at__isnull=True).order_by("name")
        ],
        "strategy": plan.strategy,
        "is_enabled": plan.is_enabled,
        "contract_capacity_kw": plan.contract_capacity_kw,
        "peak_shaving_target_kw": plan.peak_shaving_target_kw,
        "export_limit_kw": plan.export_limit_kw,
        "usable_capacity_kwh": plan.usable_capacity_kwh,
        "max_charge_kw": plan.max_charge_kw,
        "max_discharge_kw": plan.max_discharge_kw,
        "min_soc_percent": plan.min_soc_percent,
        "max_soc_percent": plan.max_soc_percent,
        "backup_reserve_percent": plan.backup_reserve_percent,
        "round_trip_efficiency": plan.round_trip_efficiency,
        "tariff_id": plan.tariff_id,
        "workflow_id": plan.workflow_id,
        "savings_baseline": plan.savings_baseline,
        "enforce_limits": plan.enforce_limits,
        "notes": plan.notes,
        "dispatchable_capacity_kwh": plan.dispatchable_capacity_kwh,
        "updated_at": plan.updated_at,
    }


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _validate_asset_metrics(payload: s.EnergyAssetIn) -> None:
    if payload.role in (AssetRole.GRID_METER, AssetRole.PV, AssetRole.BATTERY):
        if not payload.power_metric:
            raise ValidationError(
                f"Role '{payload.role}' requires a power_metric binding",
                code="missing_power_metric",
            )
    if payload.role == AssetRole.BATTERY and not payload.soc_metric:
        raise ValidationError(
            "Battery assets require a soc_metric binding", code="missing_soc_metric"
        )
    if payload.power_scale == 0:
        raise ValidationError("power_scale must not be zero", code="invalid_scale")
    if payload.cost_model:
        from apps.ems import costs

        if payload.cost_model not in costs.available():
            raise ValidationError(
                f"Unknown cost model '{payload.cost_model}'", code="unknown_cost_model",
                details={"available": costs.available()},
            )
    if (
        payload.session_enter_kw is not None
        and payload.session_exit_kw is not None
        and payload.session_exit_kw > payload.session_enter_kw
    ):
        raise ValidationError(
            "session_exit_kw must not exceed session_enter_kw", code="invalid_session_band"
        )


def _validate_plan(payload: s.StoragePlanIn) -> None:
    if payload.min_soc_percent >= payload.max_soc_percent:
        raise ValidationError(
            "min_soc_percent must be lower than max_soc_percent", code="invalid_soc_range"
        )
    if payload.backup_reserve_percent < payload.min_soc_percent:
        raise ValidationError(
            "backup_reserve_percent cannot be below min_soc_percent",
            code="invalid_reserve",
        )
    if payload.backup_reserve_percent > payload.max_soc_percent:
        raise ValidationError(
            "backup_reserve_percent cannot exceed max_soc_percent",
            code="invalid_reserve",
        )


def _validate_tariff(payload: s.TariffIn, organization=None) -> None:
    if organization is not None:
        reporting = (organization.reporting_currency or "").upper()
        given = (payload.currency or "").upper()
        if reporting and given and given != reporting:
            # Refused here rather than reconciled at report time. The design
            # note in device-classification.md §3.12 is explicit about why:
            # discovering a mixed-currency total when the monthly report is
            # already on somebody's desk is far worse than being stopped now.
            raise ValidationError(
                f"This organization reports in {reporting}; a tariff in "
                f"{given} cannot be added to its totals",
                code="currency_mismatch",
                details={"reporting_currency": reporting, "tariff_currency": given},
            )

    try:
        zoneinfo.ZoneInfo(payload.timezone_name)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            f"Unknown timezone: {payload.timezone_name}", code="invalid_timezone"
        ) from exc
    problems = validate_periods(payload.periods)
    if problems:
        raise ValidationError(
            "Tariff periods are invalid", code="invalid_periods", details=problems
        )
