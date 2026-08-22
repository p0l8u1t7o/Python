"""Metric catalogue, recording policies and time-series queries."""

from __future__ import annotations

import datetime as dt
import math
import uuid

from django.db import IntegrityError, transaction
from ninja import Query, Router

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.schemas import OkResponse, TimeRangeParams
from apps.devices.models import Device, DeviceType, descendant_site_ids
from apps.telemetry import repository, schemas as s
from apps.telemetry.catalog import get_catalog
from apps.telemetry.models import (
    LatestSample,
    Metric,
    RecordingPolicy,
    RecordingRule,
)
from apps.telemetry.policy import PolicyResolver

metrics_router = Router(tags=["metrics"])
policies_router = Router(tags=["recording-policies"])
series_router = Router(tags=["telemetry"])

#: Bucket widths the auto-downsampler may choose, coarsest last.
_BUCKET_LADDER = (1, 5, 10, 30, 60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400)

_policy_resolver = PolicyResolver()


# --------------------------------------------------------------------------
# Metric catalogue
# --------------------------------------------------------------------------
@metrics_router.get("", response=list[s.MetricOut])
def list_metrics(request, category: str | None = None):
    """Built-in metrics merged with the tenant's own definitions."""
    ctx: AuthContext = request.auth
    language = ctx.user.language if ctx.user else "en"

    custom = {
        metric.key: metric
        for metric in Metric.objects.filter(
            organization=ctx.organization, is_active=True
        )
    }
    builtin = {
        metric.key: metric
        for metric in Metric.objects.filter(organization__isnull=True, is_active=True)
    }

    output: list[dict] = []
    for key in sorted(set(builtin) | set(custom)):
        metric = custom.get(key) or builtin[key]
        if category and metric.category != category:
            continue
        output.append(
            {
                "id": metric.id,
                "key": metric.key,
                "display_name": metric.display_name,
                "label": metric.label(language),
                "translations": metric.translations or {},
                "description": metric.description,
                "unit": metric.unit,
                "value_type": metric.value_type,
                "kind": metric.kind,
                "aggregation": metric.aggregation,
                "decimals": metric.decimals,
                "min_value": metric.min_value,
                "max_value": metric.max_value,
                "state_map": metric.state_map or {},
                "category": metric.category,
                "is_builtin": key not in custom,
            }
        )
    return output


@metrics_router.post("", response={201: s.MetricOut}, auth=role_required(Role.ADMIN))
def create_metric(request, payload: s.MetricIn):
    """Define a tenant metric. Reusing a built-in key overrides it locally."""
    ctx: AuthContext = request.auth
    _check_metric_bounds(payload.min_value, payload.max_value)
    try:
        metric = Metric.objects.create(organization=ctx.organization, **payload.dict())
    except IntegrityError as exc:
        raise Conflict(
            f"Metric '{payload.key}' is already defined", code="metric_exists"
        ) from exc
    get_catalog().invalidate()
    record(AuditAction.METRIC_UPDATED, ctx=ctx, target=metric, payload=payload.dict())
    return 201, _metric_out(metric, ctx)


@metrics_router.patch("/{metric_id}", response=s.MetricOut, auth=role_required(Role.ADMIN))
def update_metric(request, metric_id: uuid.UUID, payload: s.MetricIn):
    ctx: AuthContext = request.auth
    metric = Metric.objects.filter(organization=ctx.organization, pk=metric_id).first()
    if metric is None:
        if Metric.objects.filter(pk=metric_id, organization__isnull=True).exists():
            raise Conflict(
                "Built-in metrics cannot be edited; create a tenant metric with "
                "the same key to override it",
                code="builtin_readonly",
            )
        raise NotFound("Metric not found")

    _check_metric_bounds(payload.min_value, payload.max_value)
    for field, value in payload.dict().items():
        setattr(metric, field, value)
    metric.save()
    get_catalog().invalidate()
    record(AuditAction.METRIC_UPDATED, ctx=ctx, target=metric, payload=payload.dict())
    return _metric_out(metric, ctx)


@metrics_router.delete("/{metric_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_metric(request, metric_id: uuid.UUID):
    """Deactivates the definition; stored samples are untouched."""
    ctx: AuthContext = request.auth
    metric = Metric.objects.filter(organization=ctx.organization, pk=metric_id).first()
    if metric is None:
        raise NotFound("Metric not found")
    metric.is_active = False
    metric.save(update_fields=["is_active", "updated_at"])
    get_catalog().invalidate()
    return {"ok": True, "message": "metric_deactivated"}


# --------------------------------------------------------------------------
# Recording policies
# --------------------------------------------------------------------------
@policies_router.get("", response=list[s.RecordingPolicyOut])
def list_policies(request):
    ctx: AuthContext = request.auth
    policies = (
        RecordingPolicy.objects.filter(organization=ctx.organization)
        .prefetch_related("rules", "devices")
        .order_by("name")
    )
    return [_policy_out(policy) for policy in policies]


@policies_router.post("", response={201: s.RecordingPolicyOut}, auth=role_required(Role.ADMIN))
def create_policy(request, payload: s.RecordingPolicyIn):
    """Create a policy plus its per-metric rules in one call."""
    ctx: AuthContext = request.auth
    device_type = _resolve_blueprint(ctx, payload.device_type_id)

    with transaction.atomic():
        if payload.is_default:
            RecordingPolicy.objects.filter(
                organization=ctx.organization, is_default=True
            ).update(is_default=False)
        try:
            policy = RecordingPolicy.objects.create(
                organization=ctx.organization,
                name=payload.name,
                description=payload.description,
                is_default=payload.is_default,
                device_type=device_type,
                record_unlisted_metrics=payload.record_unlisted_metrics,
                default_retention_days=payload.default_retention_days,
                default_min_interval_seconds=payload.default_min_interval_seconds,
                default_max_interval_seconds=payload.default_max_interval_seconds,
            )
        except IntegrityError as exc:
            raise Conflict(
                f"A policy named '{payload.name}' already exists", code="name_taken"
            ) from exc
        _replace_rules(policy, payload.rules)

    _policy_resolver.invalidate()
    record(AuditAction.POLICY_UPDATED, ctx=ctx, target=policy, payload=payload.dict())
    return 201, _policy_out(policy)


@policies_router.get("/{policy_id}", response=s.RecordingPolicyOut)
def get_policy(request, policy_id: uuid.UUID):
    return _policy_out(_get_policy(request.auth, policy_id))


@policies_router.put("/{policy_id}", response=s.RecordingPolicyOut, auth=role_required(Role.ADMIN))
def update_policy(request, policy_id: uuid.UUID, payload: s.RecordingPolicyIn):
    """Full replacement, rules included - this is what the editor UI submits."""
    ctx: AuthContext = request.auth
    policy = _get_policy(ctx, policy_id)
    device_type = _resolve_blueprint(ctx, payload.device_type_id)

    with transaction.atomic():
        if payload.is_default and not policy.is_default:
            RecordingPolicy.objects.filter(
                organization=ctx.organization, is_default=True
            ).exclude(pk=policy.pk).update(is_default=False)

        policy.name = payload.name
        policy.description = payload.description
        policy.is_default = payload.is_default
        policy.device_type = device_type
        policy.record_unlisted_metrics = payload.record_unlisted_metrics
        policy.default_retention_days = payload.default_retention_days
        policy.default_min_interval_seconds = payload.default_min_interval_seconds
        policy.default_max_interval_seconds = payload.default_max_interval_seconds
        try:
            policy.save()
        except IntegrityError as exc:
            raise Conflict(
                f"A policy named '{payload.name}' already exists", code="name_taken"
            ) from exc
        _replace_rules(policy, payload.rules)

    _policy_resolver.invalidate()
    record(AuditAction.POLICY_UPDATED, ctx=ctx, target=policy, payload=payload.dict())
    return _policy_out(policy)


@policies_router.delete("/{policy_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_policy(request, policy_id: uuid.UUID):
    ctx: AuthContext = request.auth
    policy = _get_policy(ctx, policy_id)
    if policy.is_default:
        raise Conflict(
            "The default policy cannot be deleted; promote another one first",
            code="policy_is_default",
        )
    Device.objects.filter(recording_policy=policy).update(recording_policy=None)
    policy.delete()
    _policy_resolver.invalidate()
    return {"ok": True, "message": "policy_deleted"}


# --------------------------------------------------------------------------
# Series queries
# --------------------------------------------------------------------------
@series_router.post("/series", response=s.SeriesResponse)
def query_series(request, payload: s.SeriesQuery):
    """Fetch one or more series, downsampling automatically when needed.

    POST rather than GET because a dashboard commonly asks for dozens of
    device/metric pairs, which does not fit comfortably in a query string.
    """
    ctx: AuthContext = request.auth
    devices = _resolve_query_devices(ctx, payload)
    stitch = _replacement_windows(ctx, devices) if payload.follow_replacements else {}
    if stitch:
        devices = {**devices, **{pk: label for pk, (_, label, _, _) in stitch.items()}}
    start, end = TimeRangeParams(start=payload.start, end=payload.end).normalized()

    interval = payload.interval_seconds or _auto_interval(start, end, payload.max_points)
    downsampled = interval > 0

    catalog = get_catalog().for_organization(ctx.organization.id)
    language = ctx.user.language if ctx.user else "en"
    device_ids = list(devices)

    grouped: dict[tuple[uuid.UUID, str], list[dict]] = {}
    if downsampled:
        rows = repository.aggregate_series(
            device_ids=device_ids,
            metric_keys=payload.metrics,
            start=start,
            end=end,
            interval_seconds=interval,
        )
        for row in rows:
            key = _stitch_key(stitch, row["device_id"], row["bucket_start"])
            if key is None:
                continue
            grouped.setdefault((key, row["metric_key"]), []).append(
                {
                    "ts": row["bucket_start"],
                    "value": row["avg_value"],
                    "min": row["min_value"],
                    "max": row["max_value"],
                    "count": row["sample_count"],
                }
            )
    else:
        rows = repository.fetch_series(
            device_ids=device_ids,
            metric_keys=payload.metrics,
            start=start,
            end=end,
            limit=payload.max_points * len(payload.metrics) * len(device_ids),
        )
        for row in rows:
            key = _stitch_key(stitch, row["device_id"], row["ts"])
            if key is None:
                continue
            grouped.setdefault((key, row["metric_key"]), []).append(
                {"ts": row["ts"], "value": row["value"]}
            )

    series = []
    for (device_pk, metric_key), points in grouped.items():
        definition = catalog.get(metric_key)
        series.append(
            {
                "device_id": device_pk,
                "device_external_id": devices.get(device_pk, ""),
                "device_ids": [
                    pk for pk, entry in stitch.items() if entry[0] == device_pk
                ]
                or [device_pk],
                "metric_key": metric_key,
                "label": definition.label(language) if definition else metric_key,
                "unit": definition.unit if definition else "",
                "aggregation": (definition.aggregation if definition else "avg")
                if downsampled
                else "raw",
                "interval_seconds": interval,
                "points": points,
            }
        )
    series.sort(key=lambda item: (str(item["device_id"]), item["metric_key"]))

    return {
        "start": start,
        "end": end,
        "interval_seconds": interval,
        "downsampled": downsampled,
        "series": series,
    }


@series_router.get("/latest", response=list[s.LatestOut])
def latest_values(request, device_ids: Query[list[uuid.UUID]] = None):
    """Current value of every recorded metric, for dashboards and tiles."""
    ctx: AuthContext = request.auth
    devices = _authorized_devices(ctx, device_ids) if device_ids else _all_devices(ctx)
    if not devices:
        return []

    catalog = get_catalog().for_organization(ctx.organization.id)
    language = ctx.user.language if ctx.user else "en"

    rows = LatestSample.objects.filter(device_id__in=list(devices)).order_by(
        "device_id", "metric_key"
    )
    output = []
    for row in rows:
        definition = catalog.get(row.metric_key)
        output.append(
            {
                "device_id": row.device_id,
                "device_external_id": devices.get(row.device_id, ""),
                "metric_key": row.metric_key,
                "label": definition.label(language) if definition else row.metric_key,
                "unit": definition.unit if definition else "",
                "value": row.value,
                "value_text": row.value_text,
                "ts": row.ts,
                "quality": row.quality,
            }
        )
    return output


@series_router.get("/devices/{device_pk}/metrics", response=list[str])
def device_metrics(request, device_pk: uuid.UUID):
    """Metric keys this device has actually reported."""
    ctx: AuthContext = request.auth
    _authorized_devices(ctx, [device_pk])
    return sorted(
        LatestSample.objects.filter(device_id=device_pk)
        .values_list("metric_key", flat=True)
        .distinct()
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _auto_interval(start: dt.datetime, end: dt.datetime, max_points: int) -> int:
    """Finest ladder bucket whose result still fits inside ``max_points``.

    Buckets are aligned to epoch multiples, not to ``start``, so a window can
    straddle one extra partial bucket at each edge. The ``+ 1`` budgets for
    that, which makes ``max_points`` a real ceiling rather than a hint.

    Returns 0 when raw samples already fit, so short windows stay unaggregated.
    """
    span = max((end - start).total_seconds(), 1.0)
    if span <= max_points:
        return 0
    for candidate in _BUCKET_LADDER:
        if math.ceil(span / candidate) + 1 <= max_points:
            return candidate
    return _BUCKET_LADDER[-1]


#: Ceiling on how many devices one series request may chart. Matches the
#: max_length on ``device_ids``: expanding a site must not become a way to ask
#: for the whole fleet at once.
MAX_SERIES_DEVICES = 50


def _replacement_windows(ctx: AuthContext, devices: dict) -> dict:
    """Map every device in a replacement chain to its own slice of time.

    Returns ``{device_pk: (head_pk, external_id, valid_from, valid_until)}``.

    Hardware routinely keeps reporting after it has been retired - left powered
    on a bench, or simply not yet unplugged - so a naive stitch would have two
    devices covering the same minutes. Adding those overlaps inflates energy
    and, worse, manufactures a peak that never occurred. Each device therefore
    contributes only between its predecessor's retirement and its own.
    """
    from apps.devices.models import chain_segments

    windows: dict = {}
    roots = (
        Device.objects.for_organization(ctx.organization)
        .filter(pk__in=list(devices))
        .select_related("replaced_by")
    )
    for device in roots:
        head = device.pk
        for node, valid_from, valid_until in chain_segments(device):
            windows[node.pk] = (head, node.device_id, valid_from, valid_until)
    return windows


def _stitch_key(stitch: dict, device_pk, ts):
    """Which logical series a row belongs to, or ``None`` if it is out of window."""
    if not stitch:
        return device_pk
    entry = stitch.get(device_pk)
    if entry is None:
        return device_pk
    head, _label, valid_from, valid_until = entry
    if valid_from is not None and ts < valid_from:
        return None
    if valid_until is not None and ts >= valid_until:
        return None
    return head


def _resolve_query_devices(ctx: AuthContext, payload: s.SeriesQuery) -> dict:
    """Turn ``device_ids`` and/or ``site_ids`` into the devices to chart.

    Expanding on the server saves the console a round trip - it can chart a
    group without first fetching that group's device list - and keeps the
    tenant check in one place, since the expansion only ever looks inside the
    caller's own organisation.
    """
    devices = _authorized_devices(ctx, payload.device_ids) if payload.device_ids else {}

    if payload.site_ids:
        site_ids = list(payload.site_ids)
        if payload.include_descendants:
            site_ids = descendant_site_ids(site_ids, organization=ctx.organization)
        rows = (
            Device.objects.for_organization(ctx.organization)
            .filter(site_id__in=site_ids)
            .order_by("name")
            .values_list("pk", "device_id")
        )
        for pk, external_id in rows:
            devices.setdefault(pk, external_id)

    if not devices:
        raise ValidationError(
            "Select at least one device, or a site that contains devices",
            code="no_devices_selected",
            details={
                "device_ids": [str(pk) for pk in payload.device_ids],
                "site_ids": [str(pk) for pk in payload.site_ids],
            },
        )
    if len(devices) > MAX_SERIES_DEVICES:
        raise ValidationError(
            f"That selection covers {len(devices)} devices; the limit is "
            f"{MAX_SERIES_DEVICES}. Narrow the site or pick devices explicitly.",
            code="too_many_devices",
            details={"device_count": len(devices), "limit": MAX_SERIES_DEVICES},
        )
    return devices


def _authorized_devices(
    ctx: AuthContext, device_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Map pk -> external device_id, rejecting anything the caller cannot see.

    Site scope is applied here, not only on the device list, because a series
    query names device ids directly: without this a scoped user could read the
    telemetry of any device in the tenant simply by knowing its id.
    """
    rows = dict(
        ctx.scope_queryset(
            Device.objects.for_organization(ctx.organization).filter(
                pk__in=device_ids
            )
        ).values_list("pk", "device_id")
    )
    missing = [str(pk) for pk in device_ids if pk not in rows]
    if missing:
        raise NotFound(
            "Unknown device(s) in this organization",
            code="device_not_found",
            details={"device_ids": missing},
        )
    return rows


def _all_devices(ctx: AuthContext) -> dict[uuid.UUID, str]:
    return dict(
        ctx.scope_queryset(
            Device.objects.for_organization(ctx.organization)
        ).values_list("pk", "device_id")
    )


def _metric_out(metric: Metric, ctx: AuthContext) -> dict:
    language = ctx.user.language if ctx.user else "en"
    return {
        "id": metric.id,
        "key": metric.key,
        "display_name": metric.display_name,
        "label": metric.label(language),
        "translations": metric.translations or {},
        "description": metric.description,
        "unit": metric.unit,
        "value_type": metric.value_type,
        "kind": metric.kind,
        "aggregation": metric.aggregation,
        "decimals": metric.decimals,
        "min_value": metric.min_value,
        "max_value": metric.max_value,
        "state_map": metric.state_map or {},
        "category": metric.category,
        "is_builtin": metric.organization_id is None,
    }


def _policy_out(policy: RecordingPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "description": policy.description,
        "is_default": policy.is_default,
        "device_type_id": policy.device_type_id,
        "record_unlisted_metrics": policy.record_unlisted_metrics,
        "default_retention_days": policy.default_retention_days,
        "default_min_interval_seconds": policy.default_min_interval_seconds,
        "default_max_interval_seconds": policy.default_max_interval_seconds,
        "rules": list(policy.rules.all()),
        "device_count": policy.devices.count(),
        "created_at": policy.created_at,
    }


def _get_policy(ctx: AuthContext, policy_id: uuid.UUID) -> RecordingPolicy:
    policy = (
        RecordingPolicy.objects.filter(organization=ctx.organization, pk=policy_id)
        .prefetch_related("rules")
        .first()
    )
    if policy is None:
        raise NotFound("Recording policy not found")
    return policy


def _replace_rules(policy: RecordingPolicy, rules: list[s.RecordingRuleIn]) -> None:
    seen: set[str] = set()
    for rule in rules:
        if rule.metric_key in seen:
            raise ValidationError(
                f"Duplicate rule for metric '{rule.metric_key}'", code="duplicate_rule"
            )
        seen.add(rule.metric_key)
        if (
            rule.max_interval_seconds
            and rule.min_interval_seconds
            and rule.max_interval_seconds < rule.min_interval_seconds
        ):
            raise ValidationError(
                f"'{rule.metric_key}': max_interval_seconds must be >= "
                "min_interval_seconds",
                code="invalid_interval",
            )

    policy.rules.all().delete()
    RecordingRule.objects.bulk_create(
        [RecordingRule(policy=policy, **rule.dict()) for rule in rules]
    )


def _resolve_blueprint(ctx: AuthContext, blueprint_id: uuid.UUID | None):
    if blueprint_id is None:
        return None
    from django.db.models import Q

    blueprint = DeviceType.objects.filter(
        Q(organization=ctx.organization) | Q(organization__isnull=True), pk=blueprint_id
    ).first()
    if blueprint is None:
        raise NotFound("Blueprint not found")
    return blueprint


def _check_metric_bounds(minimum: float | None, maximum: float | None) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValidationError(
            "min_value must be less than or equal to max_value", code="invalid_bounds"
        )
