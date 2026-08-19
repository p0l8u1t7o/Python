"""Behind-the-meter energy management endpoints."""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo

from django.db import IntegrityError
from django.db.models import Count, Max, Q, Sum
from ninja import Query, Router

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.alerts.models import AlertStatus
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.schemas import OkResponse, TimeRangeParams
from apps.core.timeutils import now
from apps.devices.models import ConnectionStatus, Device, Site
from apps.ems import schemas as s
from apps.ems.models import (
    AssetRole,
    DispatchWindow,
    EnergyAsset,
    EnergyInterval,
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
    queryset = EnergyAsset.objects.filter(organization=ctx.organization).select_related(
        "device"
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
@router.get("/sites/{site_id}/plan", response=s.StoragePlanOut)
def get_plan(request, site_id: uuid.UUID):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    plan = StoragePlan.objects.filter(site=site).first()
    if plan is None:
        raise NotFound("This site has no storage plan yet", code="plan_not_configured")
    return _plan_out(plan)


@router.put("/sites/{site_id}/plan", response=s.StoragePlanOut, auth=role_required(Role.ADMIN))
def upsert_plan(request, site_id: uuid.UUID, payload: s.StoragePlanIn):
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    _validate_plan(payload)

    tariff = None
    if payload.tariff_id is not None:
        tariff = Tariff.objects.filter(
            organization=ctx.organization, pk=payload.tariff_id
        ).first()
        if tariff is None:
            raise NotFound("Tariff not found")

    data = payload.dict(exclude={"tariff_id"})
    plan, _created = StoragePlan.objects.update_or_create(
        site=site,
        defaults={
            "organization": ctx.organization,
            "tariff": tariff,
            "updated_by": ctx.user,
            **data,
        },
    )
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=plan, payload=data)
    return _plan_out(plan)


# --------------------------------------------------------------------------
# Tariffs
# --------------------------------------------------------------------------
@router.get("/tariffs", response=list[s.TariffOut])
def list_tariffs(request):
    ctx: AuthContext = request.auth
    return list(Tariff.objects.filter(organization=ctx.organization).order_by("name"))


@router.post("/tariffs", response={201: s.TariffOut}, auth=role_required(Role.ADMIN))
def create_tariff(request, payload: s.TariffIn):
    ctx: AuthContext = request.auth
    _validate_tariff(payload)
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
    _validate_tariff(payload)
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
    site = _get_site(ctx, site_id)
    plan = StoragePlan.objects.filter(site=site).select_related("tariff").first()

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
def site_summary(request, site_id: uuid.UUID, window: Query[TimeRangeParams]):
    """Energy, cost and self-consumption totals over an arbitrary window."""
    ctx: AuthContext = request.auth
    site = _get_site(ctx, site_id)
    start, end = window.normalized(default_window_seconds=30 * 24 * 3600)
    plan = StoragePlan.objects.filter(site=site).select_related("tariff").first()
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
# Dispatch windows
# --------------------------------------------------------------------------
@router.get("/dispatch-windows", response=list[s.DispatchWindowOut])
def list_dispatch_windows(request, site_id: uuid.UUID | None = None):
    ctx: AuthContext = request.auth
    queryset = DispatchWindow.objects.filter(organization=ctx.organization)
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
    return site


def _get_device(ctx: AuthContext, device_pk: uuid.UUID) -> Device:
    device = Device.objects.for_organization(ctx.organization).filter(pk=device_pk).first()
    if device is None:
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


def _totals(site: Site, start: dt.datetime, end: dt.datetime, plan) -> dict:
    aggregate = EnergyInterval.objects.filter(
        site=site, interval_start__gte=start, interval_start__lt=end
    ).aggregate(
        grid_import=Sum("grid_import_kwh"),
        grid_export=Sum("grid_export_kwh"),
        pv=Sum("pv_kwh"),
        load=Sum("load_kwh"),
        charge=Sum("battery_charge_kwh"),
        discharge=Sum("battery_discharge_kwh"),
        peak=Max("peak_import_kw"),
        cost=Sum("energy_cost"),
        revenue=Sum("export_revenue"),
        savings=Sum("estimated_savings"),
    )

    pv_kwh = aggregate["pv"] or 0.0
    load_kwh = aggregate["load"] or 0.0
    grid_import = aggregate["grid_import"] or 0.0
    grid_export = aggregate["grid_export"] or 0.0
    charge = aggregate["charge"] or 0.0
    discharge = aggregate["discharge"] or 0.0

    return {
        "start": start,
        "end": end,
        "grid_import_kwh": round(grid_import, 3),
        "grid_export_kwh": round(grid_export, 3),
        "pv_kwh": round(pv_kwh, 3),
        "load_kwh": round(load_kwh, 3),
        "battery_charge_kwh": round(charge, 3),
        "battery_discharge_kwh": round(discharge, 3),
        "peak_import_kw": aggregate["peak"],
        "energy_cost": round(aggregate["cost"] or 0.0, 2),
        "export_revenue": round(aggregate["revenue"] or 0.0, 2),
        "estimated_savings": round(aggregate["savings"] or 0.0, 2),
        "self_consumption_ratio": (
            round(max(0.0, min(1.0, (pv_kwh - grid_export) / pv_kwh)), 4)
            if pv_kwh > 0
            else None
        ),
        "self_sufficiency_ratio": (
            round(max(0.0, min(1.0, (load_kwh - grid_import) / load_kwh)), 4)
            if load_kwh > 0
            else None
        ),
        "round_trip_efficiency": round(discharge / charge, 4) if charge > 0 else None,
        "currency": plan.tariff.currency if plan and plan.tariff_id else "",
    }


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
        "site_id": plan.site_id,
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


def _validate_tariff(payload: s.TariffIn) -> None:
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
