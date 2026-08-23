"""Turn scheduled :class:`~apps.ems.models.DispatchWindow` rows into commands.

Until now a dispatch window was a plan nobody executed. This is the executor.

Three properties matter more than cleverness here, because the thing being
automated moves megawatts:

* **One command per change, not one per cycle.** The engine works out what
  each site's battery *should* be doing right now, compares that with what it
  last told it, and stays silent when they agree. A scheduler that re-sends
  the same setpoint every cycle fills the command log, and every one of those
  is a real MQTT publish to real hardware.
* **The plan's envelope is a gate, not a suggestion.** Every setpoint goes
  through the same :func:`clamp_to_plan` the manual API path uses, so an
  operator and the scheduler cannot end up with different limits.
* **Overlaps resolve deterministically.** Higher ``priority`` wins; equal
  priority is broken by the later start, so an operator overriding today's
  schedule with a one-off window does not have to guess.

Everything runs through :func:`apps.devices.services.dispatch_command`, which
means the capability checks, the lifecycle gates and the audit trail are the
same ones a human gets. There is no privileged back door.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from apps.accounts.models import Role
from apps.accounts.security import AuthContext
from apps.core.errors import APIError
from apps.core.logging import get_logger
from apps.core.timeutils import now
from apps.devices.models import Command, CommandStatus, Device, LifecycleState
from apps.devices.services import dispatch_command
from apps.ems.models import (
    AssetRole,
    DispatchMode,
    DispatchStrategy,
    DispatchWindow,
    EnergyAsset,
    StoragePlan,
)
from apps.telemetry.models import LatestSample

logger = get_logger("ems.dispatch")

#: Command used to drive a battery. Negative watts charge, positive discharge -
#: the same convention ``_required_capabilities`` already reads.
SETPOINT_COMMAND = "set_power_setpoint"

#: Don't re-issue a setpoint that differs from the last one by less than this.
#: Without a deadband, a target derived from a live measurement would produce a
#: new command on every cycle forever.
SETPOINT_DEADBAND_W = 500.0

#: How long to look back for the command this engine last issued.
RECENT_COMMAND_HOURS = 6


@dataclass(slots=True)
class Decision:
    """What one site's battery should be doing, and why."""

    site_id: object
    device: Device | None
    #: Watts. Negative charges, positive discharges, zero idles.
    power_w: float | None
    window: DispatchWindow | None
    reason: str
    #: Set when the requested figure was reduced to fit the plan.
    clamped_from_w: float | None = None
    skipped: str = ""


# --------------------------------------------------------------------------
# Plan enforcement
# --------------------------------------------------------------------------
def clamp_to_plan(
    plan: StoragePlan | None, power_w: float, *, soc_percent: float | None = None
) -> tuple[float, str]:
    """Reduce ``power_w`` to what the storage plan permits.

    Returns the permitted figure and a short reason when it changed. Clamping
    rather than refusing is the right response *for the scheduler*: a plan
    saying "never above 200 kW" and a window saying "500 kW" is not a
    contradiction to abort on, it is an instruction to run at 200. The manual
    API path refuses instead - see :func:`assert_within_plan` - because there a
    human typed a number and silently doing something else would be worse.

    SOC limits are applied only when a live reading is available. Guessing at
    an unknown SOC would either block legitimate dispatch or permit a deep
    discharge, and neither is acceptable, so an unknown SOC leaves the power
    limits to do the work and says so.
    """
    if plan is None or not plan.enforce_limits:
        return power_w, ""

    reasons: list[str] = []

    if power_w < 0 and plan.max_charge_kw is not None:
        limit = -abs(plan.max_charge_kw) * 1000.0
        if power_w < limit:
            power_w = limit
            reasons.append("max_charge_kw")
    if power_w > 0 and plan.max_discharge_kw is not None:
        limit = abs(plan.max_discharge_kw) * 1000.0
        if power_w > limit:
            power_w = limit
            reasons.append("max_discharge_kw")

    if soc_percent is not None:
        floor = max(plan.min_soc_percent, plan.backup_reserve_percent)
        if power_w > 0 and soc_percent <= floor:
            power_w = 0.0
            reasons.append("backup_reserve_percent")
        if power_w < 0 and soc_percent >= plan.max_soc_percent:
            power_w = 0.0
            reasons.append("max_soc_percent")

    # ``export_limit_kw == 0`` is deliberately not clamped here. Discharging
    # still serves the site's own load, and a setpoint alone does not say how
    # much of it will reach the meter - only the PCS can hold that boundary.
    # Clamping discharge to zero would stop legitimate self-consumption.
    return power_w, "+".join(reasons)


def assert_within_plan(device: Device, name: str, params: dict) -> None:
    """Refuse a manual command that would break the site's storage plan.

    Called from :func:`apps.devices.services.dispatch_command`, so it applies
    to the console, to API keys and to the dispatch engine alike - the plan
    stops being a settings page that documents an intention and becomes the
    thing that actually holds.

    Refuses rather than clamps: a person typed a number, and quietly executing
    a different one is how an operator ends up believing the site is doing
    something it is not.
    """
    from apps.core.errors import ValidationError

    if name != SETPOINT_COMMAND or device.site_id is None:
        return

    plan = plan_for_site(device.site_id)
    if plan is None or not plan.enforce_limits or not plan.is_enabled:
        return

    power = params.get("power_w")
    if not isinstance(power, (int, float)) or isinstance(power, bool):
        return

    soc = _battery_soc(device.site_id)
    permitted, reason = clamp_to_plan(plan, float(power), soc_percent=soc)
    if abs(permitted - float(power)) <= 1e-6:
        return

    raise ValidationError(
        f"{power:.0f} W exceeds the storage plan for this site; "
        f"the limit here is {permitted:.0f} W",
        code="storage_plan_limit",
        details={
            "requested_w": float(power),
            "permitted_w": permitted,
            "limit": reason,
            "soc_percent": soc,
            "plan_id": str(plan.pk),
        },
    )


def _battery_soc(site_id) -> float | None:
    """Mean SOC across the site's battery assets, or ``None`` if unknown."""
    assets = list(
        EnergyAsset.objects.filter(
            site_id=site_id, role=AssetRole.BATTERY, is_active=True
        ).exclude(soc_metric="")
    )
    if not assets:
        return None

    values = [
        value
        for value in LatestSample.objects.filter(
            device_id__in=[asset.device_id for asset in assets],
            metric_key__in=[asset.soc_metric for asset in assets],
        ).values_list("value", flat=True)
        if value is not None
    ]
    return sum(values) / len(values) if values else None


# --------------------------------------------------------------------------
# Window selection
# --------------------------------------------------------------------------
def active_window(
    windows: list[DispatchWindow], moment: dt.datetime
) -> DispatchWindow | None:
    """The window in force at ``moment``.

    Higher ``priority`` wins. Equal priority is broken by the later start, so
    a one-off override entered today beats the daily schedule it overlaps
    without anyone having to bump a number.
    """
    candidates = [
        window
        for window in windows
        if window.is_enabled and window.starts_at <= moment < window.ends_at
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda window: (window.priority, window.starts_at))


def target_power_w(
    window: DispatchWindow, plan: StoragePlan | None
) -> float | None:
    """Setpoint the window asks for, in watts, before the plan is applied.

    ``None`` means "this window does not name a power", which is the case for
    ``auto``: following a strategy is not something this engine decides, so it
    steps aside rather than inventing a number.
    """
    if window.mode == DispatchMode.IDLE:
        return 0.0
    if window.mode == DispatchMode.AUTO:
        return None

    kilowatts = window.target_power_kw
    if kilowatts is None:
        # No figure given, so use the whole envelope in the requested
        # direction. A window that says "charge" and nothing else means
        # "charge as hard as you are allowed to".
        if window.mode == DispatchMode.CHARGE:
            kilowatts = plan.max_charge_kw if plan else None
        else:
            kilowatts = plan.max_discharge_kw if plan else None
    if kilowatts is None:
        return None

    magnitude = abs(float(kilowatts)) * 1000.0
    return -magnitude if window.mode == DispatchMode.CHARGE else magnitude


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
def plan_for_site(site_id) -> StoragePlan | None:
    """The plan *effectively* driving a site.

    Its own binding, else the nearest ancestor's - a plan bound to a parent
    covers the children unless a child binds its own. See
    :mod:`apps.ems.plans`.
    """
    from apps.devices.models import Site
    from apps.ems.plans import effective_plan

    site = (
        Site.objects.filter(pk=site_id)
        .select_related("storage_plan__tariff", "parent")
        .first()
    )
    if site is None:
        return None
    plan, _source = effective_plan(site)
    return plan


def battery_device(site_id) -> Device | None:
    """The dispatchable battery at a site.

    One asset, one device: a site with several packs needs a controller that
    presents them as one, and modelling that here would mean deciding how to
    split a setpoint - a question with no general answer.
    """
    asset = (
        EnergyAsset.objects.filter(
            site_id=site_id, role=AssetRole.BATTERY, is_active=True
        )
        .select_related("device", "device__device_type")
        .order_by("created_at")
        .first()
    )
    if asset is None:
        return None
    device = asset.device
    if device.deleted_at is not None:
        return None
    if device.commissioning_state != LifecycleState.ACTIVE:
        return None
    return device


def decide(site_id, moment: dt.datetime | None = None) -> Decision:
    """What this site's battery should be doing right now.

    Authority, from highest: a live demand-response event (a commitment made
    to the grid), then a scheduled window naming a power (the operator's
    explicit override), then the plan's strategy. Whatever wins is clamped by
    the plan envelope and the battery health constraints - one gate for every
    source, so nothing can out-rank the hardware limits.
    """
    from apps.ems.strategy import (
        apply_health_constraints,
        live_dr_event,
        strategy_power_w,
    )

    moment = moment or now()
    plan = plan_for_site(site_id)
    device = battery_device(site_id)

    if device is None:
        return Decision(
            site_id=site_id,
            device=None,
            power_w=None,
            window=None,
            reason="no dispatchable battery",
            skipped="no_device",
        )
    if plan is not None and not plan.is_enabled:
        return Decision(
            site_id=site_id,
            device=device,
            power_w=None,
            window=None,
            reason="plan disabled",
            skipped="plan_disabled",
        )

    windows = list(DispatchWindow.objects.filter(site_id=site_id))
    window = active_window(windows, moment)

    requested: float | None = None
    source = ""

    event = live_dr_event(site_id, moment)
    if event is not None:
        requested = abs(event.target_power_kw) * 1000.0
        source = f"demand response {event.target_power_kw:g} kW"
        window = None
    elif window is not None and (value := target_power_w(window, plan)) is not None:
        requested = value
        source = f"window {window.mode}"
    elif plan is not None:
        strategy = strategy_power_w(plan, site_id, moment)
        if strategy.power_w is None:
            return Decision(
                site_id=site_id,
                device=device,
                power_w=None,
                window=window,
                reason=f"{plan.strategy}: {strategy.reason}",
                skipped="no_setpoint",
            )
        requested = strategy.power_w
        source = f"{plan.strategy}: {strategy.reason}"

    if requested is None:
        return Decision(
            site_id=site_id,
            device=device,
            power_w=None,
            window=window,
            reason="nothing to do",
            skipped="no_window",
        )

    soc = _battery_soc(site_id)
    permitted, reason = clamp_to_plan(plan, requested, soc_percent=soc)
    if plan is not None:
        permitted, health = apply_health_constraints(plan, site_id, permitted, moment)
        if health:
            reason = f"{reason}+{health}" if reason else health
    return Decision(
        site_id=site_id,
        device=device,
        power_w=permitted,
        window=window,
        reason=source + (f" clamped by {reason}" if reason else ""),
        clamped_from_w=requested if abs(permitted - requested) > 1e-6 else None,
    )


def last_engine_setpoint(device: Device, moment: dt.datetime) -> float | None:
    """The setpoint this engine last sent to ``device``, if it was recent.

    Recognised by the idempotency key prefix, so a manual command an operator
    sent in between does not look like the engine's own work and the next
    cycle re-asserts the schedule.
    """
    command = (
        Command.objects.filter(
            device=device,
            name=SETPOINT_COMMAND,
            idempotency_key__startswith="dispatch:",
            created_at__gte=moment - dt.timedelta(hours=RECENT_COMMAND_HOURS),
        )
        .exclude(status__in=[CommandStatus.FAILED, CommandStatus.REJECTED])
        .order_by("-created_at")
        .first()
    )
    if command is None:
        return None
    value = command.params.get("power_w")
    return float(value) if isinstance(value, (int, float)) else None


def ensure_workflow_running(plan, *, dry_run: bool = False) -> str:
    """Keep this site's workflow going, and say what happened.

    Started rather than stepped: the workflow engine has its own loop with its
    own tick, because a control graph needs seconds of resolution and the
    dispatch scheduler runs on minutes. All this does is notice that the site's
    workflow is not running and start it.

    Idempotent by design. An already-running workflow is left alone, so calling
    this every scheduler cycle does not pile up runs - which also means a run
    that finishes is restarted on the next cycle, and a workflow drawn as a
    loop simply keeps going.
    """
    from apps.workflows.models import ACTIVE_STATUSES, TriggerSource
    from apps.workflows.runner import ConcurrencyLimit, start_run

    workflow = plan.workflow
    if workflow is None:
        # The API refuses to save this combination, so reaching here means the
        # workflow was deleted afterwards. Reported rather than papered over:
        # a plan that quietly does nothing looks identical to a working one.
        return "no_workflow"
    if not workflow.is_enabled or workflow.deleted_at is not None:
        return "workflow_disabled"

    if workflow.runs.filter(status__in=ACTIVE_STATUSES).exists():
        return "already_running"
    if dry_run:
        return "dry_run"

    try:
        start_run(workflow, trigger=TriggerSource.STORAGE_PLAN)
    except ConcurrencyLimit:
        return "at_capacity"
    except APIError as exc:
        return getattr(exc, "code", "") or "refused"
    return "started"


def run_site(ctx: AuthContext, site_id, *, moment=None, dry_run: bool = False) -> Decision:
    """Evaluate one site and issue a command if the target has moved."""
    moment = moment or now()

    # A workflow-driven site does not get a computed setpoint. Handing it one
    # as well would mean two things commanding the same battery, and the
    # operator chose the graph. A live demand-response event still outranks
    # the workflow - it is a commitment to the grid, and `decide` handles it.
    from apps.ems.strategy import live_dr_event

    plan = plan_for_site(site_id)
    if (
        plan is not None
        and plan.is_enabled
        and plan.strategy == DispatchStrategy.WORKFLOW
        and live_dr_event(site_id, moment) is None
    ):
        outcome = ensure_workflow_running(plan, dry_run=dry_run)
        return Decision(
            site_id=site_id,
            device=battery_device(site_id),
            power_w=None,
            window=None,
            reason=f"workflow: {outcome}",
            skipped=outcome,
        )

    decision = decide(site_id, moment)
    if decision.device is None or decision.power_w is None:
        return decision

    previous = last_engine_setpoint(decision.device, moment)
    if previous is not None and abs(previous - decision.power_w) < SETPOINT_DEADBAND_W:
        decision.skipped = "unchanged"
        return decision

    if dry_run:
        decision.skipped = "dry_run"
        return decision

    # The key makes a retried cycle - a crash between publish and commit, a
    # second scheduler started by mistake - collapse onto one command rather
    # than two setpoints racing to the same hardware.
    key = f"dispatch:{site_id}:{int(decision.power_w)}:{moment:%Y%m%d%H%M}"
    try:
        dispatch_command(
            ctx,
            decision.device,
            name=SETPOINT_COMMAND,
            params={"power_w": decision.power_w},
            idempotency_key=key[:80],
        )
    except APIError as exc:
        # A refused command is information, not a crash: the run continues to
        # the other sites and the reason is recorded against this one.
        decision.skipped = getattr(exc, "code", "") or "refused"
        logger.warning(
            "dispatch refused",
            extra={
                "site": str(site_id),
                "device_id": decision.device.device_id,
                "reason": decision.skipped,
            },
        )
    return decision


def run_organization(
    organization, *, moment=None, dry_run: bool = False, strategy: str | None = None
) -> list[Decision]:
    """Evaluate every site of a tenant that has a storage plan.

    ``strategy`` 只評估該策略的場域：W2 需量窗口控制需要比 5 分鐘快得多的
    節奏（窗口只有 15 分鐘），排程器用它在完整週期之間多跑幾次 demand_cap。

    The engine acts as the organisation itself rather than as a person, at
    admin rank - it must be able to command, and every command it sends is
    labelled with the API-key-less service principal in the audit log.
    """
    from apps.devices.models import Site

    ctx = AuthContext(organization=organization, role=Role.ADMIN, service_label="dispatch-engine")
    moment = moment or now()

    from apps.ems.plans import effective_plan_map

    active_ids = set(
        Site.objects.filter(
            organization=organization, deleted_at__isnull=True, is_active=True
        ).values_list("pk", flat=True)
    )
    effective = effective_plan_map(organization)
    site_ids = [
        site_id
        for site_id, (plan, _source) in effective.items()
        if site_id in active_ids and plan.is_enabled
        and (strategy is None or plan.strategy == strategy)
    ]

    return [
        run_site(ctx, site_id, moment=moment, dry_run=dry_run)
        for site_id in site_ids
    ]
