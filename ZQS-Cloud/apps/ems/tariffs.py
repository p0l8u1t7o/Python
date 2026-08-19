"""Time-of-use tariff resolution.

A tariff is a list of periods; the first period matching an instant wins, and
the tariff's defaults apply when nothing matches. Matching happens in the
tariff's own timezone, because rate boundaries are defined in local time.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass

from apps.core.logging import get_logger

logger = get_logger("ems.tariffs")


@dataclass(frozen=True, slots=True)
class Price:
    period_name: str
    import_price: float
    export_price: float
    currency: str = "TWD"


def _parse_clock(value: str) -> dt.time | None:
    """Parse ``HH:MM``. ``24:00`` means end-of-day and maps to ``00:00``.

    That mapping is what makes the default ``end`` work: a period ending at
    24:00 reads as ``end <= start``, which :func:`_matches` already treats as a
    window running to midnight.
    """
    try:
        hour_text, _, minute_text = value.partition(":")
        hour, minute = int(hour_text), int(minute_text or 0)
    except (ValueError, TypeError, AttributeError):
        return None
    if hour == 24 and minute == 0:
        return dt.time(0, 0)
    try:
        return dt.time(hour, minute)
    except ValueError:
        return None


def _matches(period: dict, local: dt.datetime) -> bool:
    months = period.get("months")
    if months and local.month not in months:
        return False

    weekdays = period.get("weekdays")
    if weekdays is not None and local.weekday() not in weekdays:
        return False

    start = _parse_clock(period.get("start", "00:00"))
    end = _parse_clock(period.get("end", "24:00"))
    if start is None or end is None:
        return False

    clock = local.time()
    if end <= start:
        # Window crosses midnight, e.g. 22:00-06:00.
        return clock >= start or clock < end
    return start <= clock < end


def resolve_price(tariff, moment: dt.datetime) -> Price:
    """Price applicable at ``moment`` (any timezone; converted internally)."""
    if tariff is None:
        return Price(period_name="", import_price=0.0, export_price=0.0)

    try:
        zone = zoneinfo.ZoneInfo(tariff.timezone_name or "UTC")
    except Exception:  # noqa: BLE001 - a bad tariff timezone must not break billing
        logger.warning(
            "tariff has an invalid timezone, falling back to UTC",
            extra={"tariff": tariff.name, "timezone": tariff.timezone_name},
        )
        zone = dt.timezone.utc

    local = moment.astimezone(zone)
    for period in tariff.periods or []:
        if not isinstance(period, dict):
            continue
        if _matches(period, local):
            return Price(
                period_name=period.get("name", ""),
                import_price=float(
                    period.get("import_price", tariff.default_import_price)
                ),
                export_price=float(
                    period.get("export_price", tariff.default_export_price)
                ),
                currency=tariff.currency,
            )

    return Price(
        period_name="default",
        import_price=float(tariff.default_import_price),
        export_price=float(tariff.default_export_price),
        currency=tariff.currency,
    )


def validate_periods(periods: list) -> list[str]:
    """Return human-readable problems with a tariff period list."""
    problems: list[str] = []
    for index, period in enumerate(periods or []):
        if not isinstance(period, dict):
            problems.append(f"periods[{index}] must be an object")
            continue
        if _parse_clock(period.get("start", "00:00")) is None:
            problems.append(f"periods[{index}].start must be HH:MM")
        if _parse_clock(period.get("end", "24:00")) is None:
            problems.append(f"periods[{index}].end must be HH:MM")
        months = period.get("months")
        if months is not None and (
            not isinstance(months, list) or any(m not in range(1, 13) for m in months)
        ):
            problems.append(f"periods[{index}].months must be integers 1-12")
        weekdays = period.get("weekdays")
        if weekdays is not None and (
            not isinstance(weekdays, list) or any(d not in range(0, 7) for d in weekdays)
        ):
            problems.append(f"periods[{index}].weekdays must be integers 0-6 (Mon=0)")
    return problems
