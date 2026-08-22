"""The node types that ship with the platform.

Each one is small on purpose. A node that does two things cannot be reasoned
about on a canvas, and the whole value of drawing a control flow is that you
can see what it does without reading it.
"""

from __future__ import annotations

import datetime as dt
import operator
from typing import Any


from apps.workflows.nodes.base import Handle, NodeContext, Param, Result, register

#: Comparison operators an IF node can use, in the order the console lists
#: them. Names match the alert engine's so an operator meets one vocabulary.
COMPARATORS: dict[str, Any] = {
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
    "eq": operator.eq,
    "ne": operator.ne,
}

_COMPARATOR_OPTIONS = [
    {"value": "gt", "label": ">"},
    {"value": "gte", "label": ">="},
    {"value": "lt", "label": "<"},
    {"value": "lte", "label": "<="},
    {"value": "eq", "label": "=="},
    {"value": "ne", "label": "!="},
]


def _latest_value(ctx: NodeContext, device_id: str, metric_key: str):
    """Most recent stored reading, or ``None`` if there is not one.

    ``None`` is returned rather than zero, and every caller treats it as "the
    condition cannot be evaluated". A missing reading that reads as zero would
    make ``power < 100`` true for a device that has stopped reporting, which is
    the opposite of what anyone wants from a safety interlock.
    """
    from apps.telemetry.models import LatestSample

    if not device_id or not metric_key:
        return None
    row = (
        LatestSample.objects.filter(
            organization_id=ctx.organization.id,
            device_id=device_id,
            metric_key=metric_key,
        )
        .values("value", "ts")
        .first()
    )
    if row is None or row["value"] is None:
        return None
    return row["value"], row["ts"]


def _poll_seconds() -> float:
    """How often a holding timer re-checks its condition."""
    from django.conf import settings

    return float(settings.WORKFLOWS["TICK_SECONDS"])


def _staleness_seconds(ctx: NodeContext) -> float:
    from django.conf import settings

    return float(settings.WORKFLOWS["MAX_READING_AGE_SECONDS"])


def _read_condition(ctx: NodeContext) -> tuple[bool | None, dict[str, Any]]:
    """Evaluate this node's comparison against the newest reading.

    Returns ``(None, detail)`` when it cannot be evaluated - no reading, or one
    too old to act on. Refusing to decide is the safe answer: an interlock that
    guesses is worse than one that stops.
    """
    device_id = ctx.param("device_id")
    metric_key = ctx.param("metric_key")
    comparator = ctx.param("operator", "gt")
    threshold = ctx.param("threshold")

    detail: dict[str, Any] = {
        "device_id": str(device_id or ""),
        "metric_key": metric_key or "",
        "operator": comparator,
        "threshold": threshold,
    }

    if threshold is None:
        detail["reason"] = "no_threshold"
        return None, detail

    reading = _latest_value(ctx, device_id, metric_key)
    if reading is None:
        detail["reason"] = "no_reading"
        return None, detail

    value, ts = reading
    detail["value"] = value
    detail["reading_ts"] = ts.isoformat()

    age = (ctx.moment - ts).total_seconds()
    detail["age_seconds"] = round(age, 1)
    limit = _staleness_seconds(ctx)
    if age > limit:
        detail["reason"] = "stale_reading"
        detail["max_age_seconds"] = limit
        return None, detail

    compare = COMPARATORS.get(comparator)
    if compare is None:
        detail["reason"] = "bad_operator"
        return None, detail

    try:
        outcome = bool(compare(float(value), float(threshold)))
    except (TypeError, ValueError):
        detail["reason"] = "not_numeric"
        return None, detail

    return outcome, detail


_CONDITION_PARAMS = [
    Param("device_id", "Device", kind="device", required=True),
    Param(
        "metric_key",
        "Metric",
        kind="metric",
        required=True,
        help_text="The measurement to compare. Its newest stored reading is used.",
    ),
    Param("operator", "Operator", kind="select", required=True, default="gt",
          options=_COMPARATOR_OPTIONS),
    Param("threshold", "Threshold", kind="number", required=True),
]

_CONDITION_HANDLES = [
    Handle("true", "True", tone="ok"),
    Handle("false", "False", tone="neutral"),
    Handle("unknown", "No reading", tone="warn"),
]


# --------------------------------------------------------------------------
# Flow control
# --------------------------------------------------------------------------
class StartNode:
    key = "start"
    label = "Start"
    description = (
        "Where a run begins. A graph may have several, and each one starts its "
        "own branch running in parallel."
    )
    category = "flow"
    icon = "Play"
    params: list[Param] = []
    handles = [Handle("out", "Next")]

    def execute(self, ctx: NodeContext) -> Result:
        return Result(branch="out", message="Started")


class EndNode:
    key = "end"
    label = "End"
    description = (
        "Ends this branch. The run finishes when its last branch reaches an "
        "end - or when nothing is left able to move."
    )
    category = "flow"
    icon = "Square"
    params: list[Param] = []
    handles: list[Handle] = []

    def execute(self, ctx: NodeContext) -> Result:
        return Result(stop=True, message="Branch ended")


class PassThroughNode:
    key = "node"
    label = "Waypoint"
    description = (
        "Does nothing. Exists to be a jump target and to keep a long graph "
        "readable - a line that bends where you want it to."
    )
    category = "flow"
    icon = "Circle"
    params: list[Param] = []
    handles = [Handle("out", "Next")]

    def execute(self, ctx: NodeContext) -> Result:
        return Result(branch="out", message="Passed through", level="debug")


class JumpNode:
    key = "jump"
    label = "Jump"
    description = (
        "Continues at another node instead of following an edge. Used to build "
        "loops, which is also why every run has a step limit."
    )
    category = "flow"
    icon = "CornerDownRight"
    params = [
        Param(
            "target",
            "Jump to",
            kind="node",
            required=True,
            help_text="The node to continue at.",
        )
    ]
    handles: list[Handle] = []

    def execute(self, ctx: NodeContext) -> Result:
        target = ctx.param("target")
        if not target:
            return Result(stop=True, message="No jump target set")
        # Yields to the next tick rather than continuing immediately.
        #
        # A jump backwards is a loop, and a loop executed at full speed is a
        # busy-wait: it burns the run's whole step budget in seconds, floods
        # the log and hammers the database, all to re-read a value that
        # changes every few seconds at most. Ticking is also the semantic the
        # operator wanted - "keep checking this" - and it matches how a PLC
        # scan behaves. A forward jump pays one tick of latency for the same
        # rule, which is a fair price for not having to reason about which
        # jumps are back-edges.
        return Result(
            goto=str(target),
            message=f"Jumping to {target}",
            level="debug",
            wait_until=ctx.moment + dt.timedelta(seconds=_poll_seconds()),
        )


# --------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------
class IfEndNode:
    key = "if_end"
    label = "IF-End"
    description = (
        "Compares a device reading against a threshold and takes one branch or "
        "the other. A reading that is missing or too old takes neither - it "
        "leaves by 'No reading', because guessing at an interlock is worse "
        "than stopping."
    )
    category = "condition"
    icon = "GitBranch"
    params = list(_CONDITION_PARAMS)
    handles = list(_CONDITION_HANDLES)

    def execute(self, ctx: NodeContext) -> Result:
        outcome, detail = _read_condition(ctx)
        if outcome is None:
            return Result(
                branch="unknown",
                message=f"Cannot evaluate ({detail.get('reason')})",
                detail=detail,
            )
        return Result(
            branch="true" if outcome else "false",
            message=f"{detail.get('value')} {detail['operator']} {detail['threshold']}"
            f" is {outcome}",
            detail=detail,
        )


class IfEndTimerNode:
    key = "if_end_timer"
    label = "IF-End Timer"
    description = (
        "Like IF-End, but the condition has to hold continuously for the given "
        "duration before the true branch is taken. The timer restarts the "
        "moment it stops holding, which is what filters out a momentary spike."
    )
    category = "condition"
    icon = "Timer"
    params = [
        *_CONDITION_PARAMS,
        Param(
            "hold_seconds",
            "Must hold for",
            kind="duration",
            required=True,
            default=30,
            unit="s",
            minimum=1,
            help_text="How long the condition must stay true without a break.",
        ),
    ]
    handles = list(_CONDITION_HANDLES)

    def execute(self, ctx: NodeContext) -> Result:
        outcome, detail = _read_condition(ctx)
        hold = float(ctx.param("hold_seconds", 30) or 30)
        detail["hold_seconds"] = hold

        if outcome is None:
            # An unevaluable reading is not the same as a false one, but it is
            # certainly not "still holding" - so the timer resets either way.
            return Result(
                branch="unknown",
                message=f"Cannot evaluate ({detail.get('reason')})",
                detail=detail,
                token_state={"held_since": None},
            )

        if not outcome:
            return Result(
                branch="false",
                message="Condition is false; timer reset",
                detail=detail,
                token_state={"held_since": None},
            )

        state = dict(ctx.token.state or {})
        held_since_raw = state.get("held_since")
        if not held_since_raw:
            held_since = ctx.moment
            held_since_raw = ctx.moment.isoformat()
        else:
            held_since = dt.datetime.fromisoformat(held_since_raw)

        elapsed = (ctx.moment - held_since).total_seconds()
        detail["held_since"] = held_since_raw
        detail["elapsed_seconds"] = round(elapsed, 1)

        if elapsed + 0.5 >= hold:
            return Result(
                branch="true",
                message=f"Held for {elapsed:.0f}s",
                detail=detail,
                token_state={"held_since": None},
            )

        # Re-sampled every tick rather than slept through, and the difference
        # is correctness rather than latency. Parking for the whole duration
        # and looking once at the end cannot tell "true the entire time" from
        # "dropped in the middle and came back" - it would fire on both. An
        # on-delay timer has to be evaluated repeatedly, the way a PLC scans it.
        return Result(
            branch="",
            message=f"Held {elapsed:.0f}s of {hold:g}s",
            detail=detail,
            wait_until=min(
                held_since + dt.timedelta(seconds=hold),
                ctx.moment + dt.timedelta(seconds=_poll_seconds()),
            ),
            token_state={"held_since": held_since_raw},
        )


class WaitNode:
    key = "wait"
    label = "Wait"
    description = (
        "Waits a fixed number of seconds, then continues. Costs nothing while "
        "waiting - the branch is parked, not spinning."
    )
    category = "flow"
    icon = "Hourglass"
    params = [
        Param(
            "seconds",
            "Wait for",
            kind="duration",
            required=True,
            default=10,
            unit="s",
            minimum=1,
            maximum=86400,
        )
    ]
    handles = [Handle("out", "Next")]

    def execute(self, ctx: NodeContext) -> Result:
        seconds = float(ctx.param("seconds", 10) or 10)
        state = dict(ctx.token.state or {})
        until_raw = state.get("_wait_until")

        if until_raw:
            until = dt.datetime.fromisoformat(until_raw)
            if ctx.moment >= until:
                # Cleared on the way out, or a loop back through this node
                # would sail straight past it.
                return Result(
                    branch="out",
                    message=f"Waited {seconds:g}s",
                    token_state={"_wait_until": None},
                )
            # Woken early - a step or a slow-motion delay - so park again for
            # the remainder rather than restarting the clock.
            return Result(branch="", level="debug", wait_until=until)

        until = ctx.moment + dt.timedelta(seconds=seconds)
        return Result(
            branch="",
            message=f"Waiting {seconds:g}s",
            wait_until=until,
            token_state={"_wait_until": until.isoformat()},
        )


class ConditionWaitNode:
    key = "condition_wait"
    label = "Condition Wait"
    description = (
        "Waits until a reading meets the condition, then continues - or gives "
        "up when the timeout passes. A reading that is missing counts as not "
        "met but the waiting continues; the timeout is what catches a device "
        "that never comes back."
    )
    category = "condition"
    icon = "Loader"
    params = [
        *_CONDITION_PARAMS,
        Param(
            "timeout_seconds",
            "Give up after",
            kind="duration",
            required=True,
            default=300,
            unit="s",
            minimum=1,
            maximum=86400,
            help_text="Without one, a device that never recovers holds the branch forever.",
        ),
    ]
    handles = [
        Handle("met", "Condition met", tone="ok"),
        Handle("timeout", "Timed out", tone="warn"),
    ]

    def execute(self, ctx: NodeContext) -> Result:
        timeout = float(ctx.param("timeout_seconds", 300) or 300)
        state = dict(ctx.token.state or {})
        since_raw = state.get("_cw_since")
        since = dt.datetime.fromisoformat(since_raw) if since_raw else ctx.moment

        outcome, detail = _read_condition(ctx)
        detail["timeout_seconds"] = timeout
        elapsed = (ctx.moment - since).total_seconds()
        detail["elapsed_seconds"] = round(elapsed, 1)

        if outcome is True:
            return Result(
                branch="met",
                message=f"Condition met after {elapsed:.0f}s",
                detail=detail,
                token_state={"_cw_since": None},
            )

        if elapsed >= timeout:
            return Result(
                branch="timeout",
                message=f"Gave up after {timeout:g}s",
                detail=detail,
                token_state={"_cw_since": None},
            )

        return Result(
            branch="",
            level="debug",
            message=f"Waiting for condition ({elapsed:.0f}s of {timeout:g}s)",
            detail=detail,
            wait_until=min(
                since + dt.timedelta(seconds=timeout),
                ctx.moment + dt.timedelta(seconds=_poll_seconds()),
            ),
            token_state={"_cw_since": since.isoformat()},
        )


#: What the day selector's values mean, as ISO weekday sets (Mon=1..Sun=7).
_DAY_SETS: dict[str, frozenset[int]] = {
    "everyday": frozenset(range(1, 8)),
    "weekdays": frozenset(range(1, 6)),
    "weekend": frozenset((6, 7)),
    "mon": frozenset((1,)),
    "tue": frozenset((2,)),
    "wed": frozenset((3,)),
    "thu": frozenset((4,)),
    "fri": frozenset((5,)),
    "sat": frozenset((6,)),
    "sun": frozenset((7,)),
}


def _parse_hhmm(raw) -> tuple[int, int] | None:
    try:
        text = str(raw or "").strip()
        hh, mm = text.split(":")
        hour, minute = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


class IfEndTimeNode:
    key = "if_end_time"
    label = "IF-End Time"
    description = (
        "A time-of-day window: inside it the true branch runs. Outside it the "
        "branch either waits for the window to open (the default) or takes "
        "the false branch immediately. Times are read in the site's timezone."
    )
    category = "condition"
    icon = "CalendarClock"
    params = [
        Param(
            "days",
            "Days",
            kind="select",
            required=True,
            default="everyday",
            options=[
                {"value": "everyday", "label": "Every day"},
                {"value": "weekdays", "label": "Mon-Fri"},
                {"value": "weekend", "label": "Sat-Sun"},
                {"value": "mon", "label": "Monday"},
                {"value": "tue", "label": "Tuesday"},
                {"value": "wed", "label": "Wednesday"},
                {"value": "thu", "label": "Thursday"},
                {"value": "fri", "label": "Friday"},
                {"value": "sat", "label": "Saturday"},
                {"value": "sun", "label": "Sunday"},
            ],
        ),
        Param("start_time", "From", kind="text", required=True, default="09:00",
              help_text="HH:MM, 24-hour."),
        Param("end_time", "Until", kind="text", required=True, default="18:00",
              help_text="HH:MM. Earlier than From means the window crosses midnight."),
        Param(
            "wait_for_window",
            "Wait for the window",
            kind="boolean",
            default=True,
            help_text="Off takes the false branch immediately when outside it.",
        ),
    ]
    handles = [
        Handle("true", "In window", tone="ok"),
        Handle("false", "Outside", tone="neutral"),
    ]

    def _zone(self, ctx: NodeContext):
        """The site's timezone, else the organisation's, else UTC.

        Local time is the only honest reading of "09:00 to 18:00" - a control
        window evaluated in UTC turns into the night shift twice a year.
        """
        import zoneinfo

        for name in (
            getattr(ctx.site, "timezone_name", "") if ctx.site else "",
            getattr(ctx.organization, "default_timezone", ""),
        ):
            if name:
                try:
                    return zoneinfo.ZoneInfo(name)
                except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                    continue
        return dt.UTC

    def execute(self, ctx: NodeContext) -> Result:
        days = _DAY_SETS.get(str(ctx.param("days", "everyday")), _DAY_SETS["everyday"])
        start = _parse_hhmm(ctx.param("start_time", "09:00"))
        end = _parse_hhmm(ctx.param("end_time", "18:00"))
        if start is None or end is None:
            return Result(
                branch="false",
                message="Invalid time; expected HH:MM",
                detail={"start_time": ctx.param("start_time"),
                        "end_time": ctx.param("end_time")},
            )

        zone = self._zone(ctx)
        local = ctx.moment.astimezone(zone)
        minutes = local.hour * 60 + local.minute
        start_m = start[0] * 60 + start[1]
        end_m = end[0] * 60 + end[1]
        detail = {
            "local_time": local.strftime("%a %H:%M"),
            "timezone": str(zone),
            "window": f"{start[0]:02d}:{start[1]:02d}-{end[0]:02d}:{end[1]:02d}",
        }

        if start_m <= end_m:
            in_window = local.isoweekday() in days and start_m <= minutes < end_m
        else:
            # Crosses midnight: the evening half belongs to the listed day,
            # the morning half to the day after it.
            in_window = (local.isoweekday() in days and minutes >= start_m) or (
                ((local.isoweekday() - 2) % 7 + 1) in days and minutes < end_m
            )

        if in_window:
            return Result(branch="true", message="Inside the window", detail=detail)

        if not ctx.param("wait_for_window", True):
            return Result(branch="false", message="Outside the window", detail=detail)

        # Wait for the next opening. Scanned day by day rather than computed
        # in closed form: fourteen iterations of arithmetic beat an
        # off-by-one across a month boundary.
        for offset in range(0, 8):
            day = (local + dt.timedelta(days=offset)).date()
            candidate = dt.datetime(
                day.year, day.month, day.day, start[0], start[1], tzinfo=zone
            )
            if candidate > local and candidate.isoweekday() in days:
                detail["opens_at"] = candidate.isoformat()
                return Result(
                    branch="",
                    message=f"Waiting for the window ({candidate:%a %H:%M})",
                    detail=detail,
                    wait_until=candidate.astimezone(dt.UTC),
                )
        return Result(branch="false", message="No opening found", detail=detail)


class ArrowNode:
    """Canvas decoration: a big arrow block, resizable, pointing where the
    author aims it. Exists because "point at the thing" is what annotations
    do, and a note alone cannot."""

    key = "arrow"
    label = "Arrow"
    description = (
        "A pointer arrow on the canvas. Decoration only: resize it, aim it, "
        "colour it - it never executes and cannot be connected."
    )
    category = "decoration"
    icon = "MoveUpRight"
    params = [
        Param(
            "direction",
            "Direction",
            kind="select",
            required=True,
            default="right",
            options=[
                {"value": "right", "label": "→"},
                {"value": "down-right", "label": "↘"},
                {"value": "down", "label": "↓"},
                {"value": "down-left", "label": "↙"},
                {"value": "left", "label": "←"},
                {"value": "up-left", "label": "↖"},
                {"value": "up", "label": "↑"},
                {"value": "up-right", "label": "↗"},
            ],
        )
    ]
    handles: list[Handle] = []

    def execute(self, ctx: NodeContext) -> Result:
        # Defensive: a token should never land here.
        return Result(stop=True, level="debug", message="")


class NoteNode:
    """Canvas decoration. Never executed; the engine and the entry scan both
    skip it, and the graph validator refuses edges into or out of one."""

    key = "note"
    label = "Note"
    description = (
        "A sticky note on the canvas. Not part of the flow: it cannot be "
        "connected and never executes."
    )
    category = "decoration"
    icon = "StickyNote"
    params: list[Param] = []
    handles: list[Handle] = []

    def execute(self, ctx: NodeContext) -> Result:
        # Defensive: a token should never land here.
        return Result(stop=True, level="debug", message="")


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def _dispatch(ctx: NodeContext, name: str, params: dict[str, Any]) -> Result:
    """Send one command, or say what would have been sent.

    Everything goes through :func:`apps.devices.services.dispatch_command`, so
    the capability checks, the plan envelope and the audit trail are the same
    ones a person gets. A workflow is not a privileged path.
    """
    from apps.accounts.models import Role
    from apps.accounts.security import AuthContext
    from apps.core.errors import APIError
    from apps.devices.models import Device
    from apps.devices.services import dispatch_command

    device_id = ctx.param("device_id")
    detail: dict[str, Any] = {"device_id": str(device_id or ""), "command": name,
                              "params": params}

    device = (
        Device.objects.filter(
            pk=device_id, organization=ctx.organization, deleted_at__isnull=True
        )
        .select_related("device_type", "edge_node")
        .first()
        if device_id
        else None
    )
    if device is None:
        return Result(branch="failed", message="Device not found", detail=detail)

    # A site-scoped workflow may only command equipment at that site. Without
    # this a workflow handed to one plant's operator could reach another's.
    if ctx.site is not None and device.site_id != ctx.site.id:
        detail["reason"] = "outside_workflow_site"
        return Result(
            branch="failed",
            message="Device is not at this workflow's site",
            detail=detail,
        )

    if ctx.dry_run:
        return Result(
            branch="sent",
            message=f"Would send {name}",
            detail={**detail, "dry_run": True},
        )

    auth = AuthContext(organization=ctx.organization, role=Role.ADMIN)
    try:
        command = dispatch_command(auth, device, name=name, params=params)
    except APIError as exc:
        detail["reason"] = getattr(exc, "code", "") or exc.__class__.__name__
        return Result(branch="failed", message=str(exc)[:300], detail=detail)

    detail["command_id"] = str(command.id)
    return Result(branch="sent", message=f"Sent {name}", detail=detail)


_ACTION_HANDLES = [
    Handle("sent", "Sent", tone="ok"),
    Handle("failed", "Failed", tone="critical"),
]


class SendActionNode:
    key = "send_action"
    label = "Send Action"
    description = (
        "Issues a command to a device - the same command an operator could "
        "press, through the same checks. Refused commands leave by 'Failed' "
        "rather than stopping the run."
    )
    category = "action"
    icon = "Send"
    params = [
        Param("device_id", "Device", kind="device", required=True),
        Param(
            "command",
            "Command",
            kind="command",
            required=True,
            help_text="Offered from the device blueprint's own command list.",
        ),
        Param(
            "params",
            "Parameters",
            kind="text",
            help_text="JSON object, for commands that take arguments.",
        ),
    ]
    handles = list(_ACTION_HANDLES)

    def execute(self, ctx: NodeContext) -> Result:
        import json

        name = ctx.param("command")
        if not name:
            return Result(branch="failed", message="No command selected")

        raw = ctx.param("params")
        params: dict[str, Any] = {}
        if raw:
            if isinstance(raw, dict):
                params = raw
            else:
                try:
                    parsed = json.loads(str(raw))
                    params = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return Result(
                        branch="failed",
                        message="Parameters are not valid JSON",
                        detail={"params": str(raw)[:200]},
                    )
        return _dispatch(ctx, str(name), params)


class SetDataNode:
    key = "set_data"
    label = "Set Data"
    description = (
        "Writes one numeric value to a device: a setpoint, a limit. The same "
        "thing Send Action does, with a form built for the common case of one "
        "named number."
    )
    category = "action"
    icon = "SlidersHorizontal"
    params = [
        Param("device_id", "Device", kind="device", required=True),
        Param("command", "Command", kind="command", required=True),
        Param(
            "param_name",
            "Parameter name",
            kind="text",
            required=True,
            help_text="For example limit_w, power_w, min_soc.",
        ),
        Param("value", "Value", kind="number", required=True),
    ]
    handles = list(_ACTION_HANDLES)

    def execute(self, ctx: NodeContext) -> Result:
        name = ctx.param("command")
        key = ctx.param("param_name")
        value = ctx.param("value")
        if not name or not key:
            return Result(branch="failed", message="Command and parameter are required")
        try:
            number = float(value)
        except (TypeError, ValueError):
            return Result(
                branch="failed",
                message="Value is not a number",
                detail={"value": value},
            )
        # Whole numbers go as ints: a command schema declaring an integer
        # bound rejects 400000.0 on some validators and accepts 400000.
        payload = int(number) if number.is_integer() else number
        return _dispatch(ctx, str(name), {str(key): payload})


class RunWorkflowNode:
    key = "run_workflow"
    label = "Run Workflow"
    description = (
        "Starts another workflow and carries on without waiting. Subject to "
        "the same concurrency limit as any other run, so a graph that starts "
        "workflows in a loop is throttled rather than allowed to multiply."
    )
    category = "flow"
    icon = "Workflow"
    params = [Param("workflow_id", "Workflow", kind="workflow", required=True)]
    handles = [
        Handle("started", "Started", tone="ok"),
        Handle("refused", "Refused", tone="warn"),
    ]

    def execute(self, ctx: NodeContext) -> Result:
        from apps.workflows.models import TriggerSource, Workflow
        from apps.workflows.runner import ConcurrencyLimit, start_run

        target_id = ctx.param("workflow_id")
        detail = {"workflow_id": str(target_id or "")}
        target = (
            Workflow.objects.filter(
                pk=target_id, organization=ctx.organization, deleted_at__isnull=True
            ).first()
            if target_id
            else None
        )
        if target is None:
            return Result(branch="refused", message="Workflow not found", detail=detail)

        if ctx.dry_run:
            return Result(
                branch="started",
                message=f"Would start {target.name}",
                detail={**detail, "dry_run": True},
            )

        try:
            child = start_run(
                target,
                trigger=TriggerSource.WORKFLOW,
                parent_run=ctx.run,
            )
        except ConcurrencyLimit as exc:
            return Result(branch="refused", message=str(exc), detail=detail)

        detail["run_id"] = str(child.id)
        return Result(branch="started", message=f"Started {target.name}", detail=detail)


def register_builtins() -> None:
    """Registered from ``AppConfig.ready`` so importing models is safe."""
    for node_type in (
        StartNode(),
        EndNode(),
        PassThroughNode(),
        JumpNode(),
        WaitNode(),
        IfEndNode(),
        IfEndTimerNode(),
        IfEndTimeNode(),
        ConditionWaitNode(),
        SendActionNode(),
        SetDataNode(),
        RunWorkflowNode(),
        NoteNode(),
        ArrowNode(),
    ):
        register(node_type)
