"""Detect charge / discharge / running sessions from power samples.

Recomputed from stored data on a schedule rather than tracked live in the
ingest worker. The reasons are the same three that made the energy aggregator
work this way, and they are not stylistic:

* messages arrive **out of order**, and a state machine fed out of order
  produces sessions that never happened;
* messages arrive **late**, and a live machine has already moved past them;
* a worker **restarts**, and whatever state it held is gone.

Recomputation has none of those problems because it starts from the data every
time. The cost is latency - "last discharged" is at most one scheduler cycle
stale - and that is a number nobody needs to the second.

Idempotency is what makes the rebuild safe to re-run, and it needs care at the
left edge of the window: a session that started before the window must not be
sliced in two. :func:`rebuild_window` therefore extends its own start back to
the beginning of any session still open there.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q

from apps.core.logging import get_logger
from apps.core.timeutils import now
from apps.devices.models import Device
from apps.ems.models import (
    AssetRole,
    DeviceOperatingSession,
    EnergyAsset,
    SessionEndReason,
    SessionKind,
)
from apps.telemetry.models import TelemetrySample

logger = get_logger("ems.sessions")

SECONDS_PER_HOUR = 3600.0

#: Enter threshold when the asset does not set one: 2% of the nameplate.
DEFAULT_ENTER_FRACTION = 0.02
#: ...but never below this, or noise on a large asset becomes a session.
MINIMUM_ENTER_KW = 0.5
#: Exit threshold as a fraction of enter. Below 1 by definition - the gap is
#: the hysteresis, and without it a load hovering at the threshold produces
#: thousands of one-sample sessions.
DEFAULT_EXIT_RATIO = 0.5

#: A load is "running" above this fraction of its rating. Standby draw is
#: typically 1-3%, so 5% separates standby from work.
LOAD_RUNNING_FRACTION = 0.05

#: Roles whose sessions are charge/discharge rather than running.
_BIDIRECTIONAL_ROLES = {AssetRole.BATTERY}


@dataclass(slots=True)
class Thresholds:
    enter_kw: float
    exit_kw: float
    min_duration_s: int
    gap_s: int


@dataclass(slots=True)
class _Open:
    """A session being accumulated."""

    kind: str
    started_at: dt.datetime
    last_ts: dt.datetime
    energy_kwh: float = 0.0
    peak_kw: float = 0.0
    weighted_kw: float = 0.0
    seconds: float = 0.0
    start_soc: float | None = None
    last_soc: float | None = None
    samples: int = 0


@dataclass(slots=True)
class RebuildResult:
    device_count: int = 0
    written: int = 0
    deleted: int = 0
    skipped: list[str] = field(default_factory=list)


def thresholds_for(asset: EnergyAsset) -> Thresholds:
    """Resolve this asset's session thresholds, filling in what it omits.

    Defaults are derived from the nameplate because an absolute default cannot
    suit both a 5 kW rooftop and a 2 MW battery. Where there is no nameplate
    either, :data:`MINIMUM_ENTER_KW` is the floor.
    """
    rating = asset.rated_power_kw or 0.0
    fraction = (
        LOAD_RUNNING_FRACTION
        if asset.role not in _BIDIRECTIONAL_ROLES
        else DEFAULT_ENTER_FRACTION
    )
    enter = asset.session_enter_kw
    if enter is None:
        enter = max(rating * fraction, MINIMUM_ENTER_KW)

    exit_kw = asset.session_exit_kw
    if exit_kw is None:
        exit_kw = enter * DEFAULT_EXIT_RATIO
    # Hysteresis only exists while exit < enter. An asset configured the other
    # way round would flap, so the relationship is enforced rather than trusted.
    exit_kw = min(exit_kw, enter * DEFAULT_EXIT_RATIO)

    return Thresholds(
        enter_kw=float(enter),
        exit_kw=float(exit_kw),
        min_duration_s=int(asset.session_min_duration_s or 0),
        gap_s=int(asset.session_gap_s or 300),
    )


def _kind_for(asset: EnergyAsset, power_kw: float) -> str | None:
    """Which session a normalised power reading belongs to, if any.

    Sign follows the platform convention, which the asset's ``power_scale``
    and ``invert_sign`` have already applied: positive is power *out of* the
    equipment, negative is power into it.
    """
    if asset.role in _BIDIRECTIONAL_ROLES:
        return SessionKind.DISCHARGE if power_kw > 0 else SessionKind.CHARGE
    return SessionKind.RUNNING


def detect(
    asset: EnergyAsset,
    points: list[tuple[dt.datetime, float]],
    thresholds: Thresholds,
    *,
    soc_points: list[tuple[dt.datetime, float]] | None = None,
    window_end: dt.datetime | None = None,
) -> list[DeviceOperatingSession]:
    """Turn a normalised kW series into sessions.

    ``points`` must be sorted and already scaled to kW with the asset's sign
    convention applied. Energy is accumulated with the same zero-order hold the
    rest of the platform uses: each sample holds until the next one.

    Three rules do the work:

    * **hysteresis** - a session opens above ``enter_kw`` and closes below
      ``exit_kw``, so a reading that oscillates around one number does not
      open and close repeatedly;
    * **minimum duration** - anything shorter is dropped, so a motor's inrush
      does not become a one-second discharge;
    * **gap** - no samples for ``gap_s`` closes the session *at the last
      sample*, never extrapolated past it. What the equipment did while it was
      silent is not known, and inventing it would be worse than stopping.
    """
    sessions: list[DeviceOperatingSession] = []
    open_session: _Open | None = None
    soc_lookup = _soc_interpolator(soc_points or [])

    def close(reason: str, ended_at: dt.datetime) -> None:
        nonlocal open_session
        if open_session is None:
            return
        duration = (ended_at - open_session.started_at).total_seconds()
        if duration >= thresholds.min_duration_s and open_session.samples > 0:
            sessions.append(
                _materialise(asset, open_session, ended_at, duration, reason)
            )
        open_session = None

    for index, (ts, power_kw) in enumerate(points):
        magnitude = abs(power_kw)
        kind = _kind_for(asset, power_kw)
        next_ts = points[index + 1][0] if index + 1 < len(points) else None

        if open_session is not None:
            gap = (ts - open_session.last_ts).total_seconds()
            if gap > thresholds.gap_s:
                close(SessionEndReason.OFFLINE, open_session.last_ts)
            elif kind != open_session.kind:
                # A battery that swings from charge to discharge ends one
                # session and starts another at the same instant; they are
                # different activities, not one long one.
                close(SessionEndReason.THRESHOLD, ts)
            elif magnitude < thresholds.exit_kw:
                close(SessionEndReason.THRESHOLD, ts)

        if open_session is None:
            if magnitude >= thresholds.enter_kw:
                open_session = _Open(
                    kind=kind,
                    started_at=ts,
                    last_ts=ts,
                    start_soc=soc_lookup(ts),
                )
            else:
                continue

        # Hold this reading until the next sample, or to the end of the series.
        span_end = next_ts or ts
        duration = max((span_end - ts).total_seconds(), 0.0)
        if duration > thresholds.gap_s:
            duration = 0.0  # the hold does not survive a data gap

        open_session.samples += 1
        open_session.last_ts = ts
        open_session.energy_kwh += magnitude * duration / SECONDS_PER_HOUR
        open_session.weighted_kw += magnitude * duration
        open_session.seconds += duration
        open_session.peak_kw = max(open_session.peak_kw, magnitude)
        open_session.last_soc = soc_lookup(ts) or open_session.last_soc

    if open_session is not None:
        # Still active at the end of the data. If the last sample is older than
        # the gap the equipment has simply stopped reporting; otherwise the
        # session is genuinely still running and stays open.
        edge = window_end or open_session.last_ts
        if (edge - open_session.last_ts).total_seconds() > thresholds.gap_s:
            close(SessionEndReason.OFFLINE, open_session.last_ts)
        else:
            duration = (open_session.last_ts - open_session.started_at).total_seconds()
            if duration >= thresholds.min_duration_s and open_session.samples > 0:
                sessions.append(
                    _materialise(asset, open_session, None, duration, "")
                )

    return sessions


def _materialise(
    asset: EnergyAsset,
    state: _Open,
    ended_at: dt.datetime | None,
    duration: float,
    reason: str,
) -> DeviceOperatingSession:
    return DeviceOperatingSession(
        organization_id=asset.organization_id,
        device_id=asset.device_id,
        asset=asset,
        kind=state.kind,
        started_at=state.started_at,
        ended_at=ended_at,
        duration_s=int(duration) if ended_at is not None else None,
        energy_kwh=round(state.energy_kwh, 6),
        peak_kw=round(state.peak_kw, 4) or None,
        avg_kw=(
            round(state.weighted_kw / state.seconds, 4) if state.seconds > 0 else None
        ),
        start_soc_percent=state.start_soc,
        end_soc_percent=state.last_soc,
        end_reason=reason,
    )


def _soc_interpolator(points: list[tuple[dt.datetime, float]]):
    """Last SOC reading at or before a moment; ``None`` before the first."""
    if not points:
        return lambda _ts: None

    ordered = sorted(points)

    def lookup(ts: dt.datetime) -> float | None:
        found = None
        for sample_ts, value in ordered:
            if sample_ts > ts:
                break
            found = value
        return found

    return lookup


# --------------------------------------------------------------------------
# Rebuild
# --------------------------------------------------------------------------
def rebuild_asset(
    asset: EnergyAsset, start: dt.datetime, end: dt.datetime
) -> tuple[int, int]:
    """Recompute one asset's sessions in ``[start, end)``. Returns (written, deleted).

    The effective window starts at whichever is earlier: the requested start,
    or the start of a session that was still open there. Without that, a
    battery discharging across the window boundary would be recorded twice -
    once as the tail of the old session and once as a new one beginning at an
    arbitrary clock time.
    """
    if not asset.power_metric:
        return 0, 0

    effective_start = start
    straddling = (
        DeviceOperatingSession.objects.filter(
            device_id=asset.device_id, started_at__lt=start
        )
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start))
        .order_by("started_at")
        .first()
    )
    if straddling is not None:
        effective_start = straddling.started_at

    rows = list(
        TelemetrySample.objects.filter(
            device_id=asset.device_id,
            metric_key=asset.power_metric,
            ts__gte=effective_start,
            ts__lt=end,
            value__isnull=False,
        )
        .order_by("ts")
        .values_list("ts", "value")
    )
    points = [(ts, asset.normalize_power(value)) for ts, value in rows]

    soc_points: list[tuple[dt.datetime, float]] = []
    if asset.soc_metric:
        soc_points = list(
            TelemetrySample.objects.filter(
                device_id=asset.device_id,
                metric_key=asset.soc_metric,
                ts__gte=effective_start,
                ts__lt=end,
                value__isnull=False,
            )
            .order_by("ts")
            .values_list("ts", "value")
        )

    sessions = detect(
        asset, points, thresholds_for(asset), soc_points=soc_points, window_end=end
    )

    with transaction.atomic():
        deleted, _ = DeviceOperatingSession.objects.filter(
            device_id=asset.device_id,
            started_at__gte=effective_start,
            started_at__lt=end,
        ).delete()
        if sessions:
            DeviceOperatingSession.objects.bulk_create(sessions, batch_size=500)
        _refresh_device_cache(asset.device_id)

    return len(sessions), deleted


def _refresh_device_cache(device_id) -> None:
    """Recompute the three ``last_*_at`` fields from the session table.

    Recomputed rather than incremented: the rebuild may have *removed* the
    session that was previously the most recent one, and an increment-only
    cache would keep pointing at something that no longer exists.
    """
    latest: dict[str, dt.datetime | None] = {}
    for kind, field_name in (
        (SessionKind.CHARGE, "last_charge_at"),
        (SessionKind.DISCHARGE, "last_discharge_at"),
        (SessionKind.RUNNING, "last_running_at"),
    ):
        latest[field_name] = (
            DeviceOperatingSession.objects.filter(device_id=device_id, kind=kind)
            .order_by("-started_at")
            .values_list("started_at", flat=True)
            .first()
        )
    Device.objects.filter(pk=device_id).update(**latest)


def rebuild_organization(
    organization,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    device_id=None,
) -> RebuildResult:
    """Rebuild sessions for every tracked asset of a tenant. Safe to re-run.

    Mirrors ``aggregate_energy``: the same overlapping lookback, so late data
    corrects the window it belongs to, and one mental model for both jobs.
    """
    until = until or now()
    since = since or (until - dt.timedelta(hours=2))
    result = RebuildResult()

    assets = EnergyAsset.objects.filter(
        organization=organization, is_active=True, session_tracking_enabled=True
    ).select_related("device")
    if device_id is not None:
        assets = assets.filter(device_id=device_id)

    for asset in assets:
        if not asset.power_metric:
            result.skipped.append(f"{asset.device_id}: no power metric bound")
            continue
        written, deleted = rebuild_asset(asset, since, until)
        result.device_count += 1
        result.written += written
        result.deleted += deleted

    logger.info(
        "operating sessions rebuilt",
        extra={
            "organization": organization.slug,
            "assets": result.device_count,
            "sessions": result.written,
        },
    )
    return result
