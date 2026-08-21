"""Per-device energy: integrate a power gauge, or difference a counter.

Two sources, two methods, and the choice matters:

* A **gauge** in kW is integrated. The method is a **zero-order hold** - each
  sample is assumed to hold until the next one - not a trapezoid. For a signal
  reported far more often than it changes the error is negligible; for a motor
  switching on and off it is systematic, and its direction depends on whether
  the step was up or down. :attr:`EnergyResult.coverage` is how much of the
  window was actually covered by samples, and is the honest quality signal.

* A **counter** in kWh is differenced. The device did the accumulating, so
  there is no sampling error at all. Whenever a counter is available it wins.

A counter that goes *backwards* is the interesting case. It means a meter was
swapped, an integer wrapped, or firmware reset - and those three call for
different corrections that cannot be told apart from the numbers alone. So
unless the metric declares ``counter_max``, the answer is ``None``: not zero,
which would quietly shrink a monthly total, and not a negative delta, which
would be worse.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

SECONDS_PER_HOUR = 3600.0

#: A counter may drift down by this much before it counts as a reset rather
#: than noise - float storage of a large kWh total loses the last digits.
COUNTER_NOISE_TOLERANCE = 1e-6

BASIS_COUNTER = "counter"
BASIS_INTEGRATED = "integrated"
BASIS_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EnergyResult:
    """Energy over a window, and how much to trust it."""

    #: ``None`` means "cannot be determined", never "zero".
    kwh: float | None
    basis: str
    #: Fraction of the window covered by samples (0..1). Always 1.0 for a
    #: counter difference, which spans the window by construction.
    coverage: float = 0.0
    samples: int = 0
    counter_reset: bool = False


def build_timeline(
    points: Sequence[tuple[dt.datetime, float]],
    start: dt.datetime,
    end: dt.datetime,
    *,
    seed: tuple[dt.datetime, float] | None = None,
) -> list[tuple[dt.datetime, float]]:
    """Clamp a sample series to ``[start, end)``, anchored at ``start``.

    ``seed`` is the last sample *before* the window. Supplying it is what lets a
    device that reports only on change still account for a full interval: its
    value held from before the window opened.

    Shared with the site-level aggregator so the fiddly part - deciding what
    the value was at ``start`` - has exactly one implementation.
    """
    timeline: list[tuple[dt.datetime, float]] = []
    if seed is not None:
        timeline.append((start, seed[1]))

    for ts, value in points:
        if ts < start:
            # A later pre-window sample than the seed supersedes it.
            if timeline and timeline[0][0] == start:
                timeline[0] = (start, value)
            else:
                timeline.insert(0, (start, value))
        elif ts < end:
            timeline.append((ts, value))
    return timeline


def integrate_kwh(
    points: Sequence[tuple[dt.datetime, float]],
    start: dt.datetime,
    end: dt.datetime,
    *,
    seed: tuple[dt.datetime, float] | None = None,
) -> EnergyResult:
    """Zero-order-hold integration of a kW series into kWh."""
    window_seconds = (end - start).total_seconds()
    if window_seconds <= 0:
        return EnergyResult(kwh=None, basis=BASIS_UNKNOWN)

    timeline = build_timeline(points, start, end, seed=seed)
    if not timeline:
        return EnergyResult(kwh=None, basis=BASIS_UNKNOWN)

    total = 0.0
    covered = 0.0
    for index, (ts, value) in enumerate(timeline):
        segment_end = timeline[index + 1][0] if index + 1 < len(timeline) else end
        duration = (segment_end - ts).total_seconds()
        if duration <= 0:
            continue
        covered += duration
        total += value * duration / SECONDS_PER_HOUR

    return EnergyResult(
        kwh=total,
        basis=BASIS_INTEGRATED,
        coverage=min(covered / window_seconds, 1.0),
        samples=len(timeline),
    )


def counter_delta(
    first: float | None,
    last: float | None,
    *,
    counter_max: float | None = None,
) -> EnergyResult:
    """Difference a cumulative counter, refusing to guess through a reset.

    ``counter_max`` is the value at which the counter wraps. Only when it is
    known can a backwards step be corrected; otherwise a swapped meter and an
    overflow look identical, and the result is ``None``.
    """
    if first is None or last is None:
        return EnergyResult(kwh=None, basis=BASIS_UNKNOWN)

    delta = last - first
    if delta >= 0:
        return EnergyResult(kwh=delta, basis=BASIS_COUNTER, coverage=1.0, samples=2)

    if -delta <= COUNTER_NOISE_TOLERANCE:
        # Float noise on a large total, not a real decrease.
        return EnergyResult(kwh=0.0, basis=BASIS_COUNTER, coverage=1.0, samples=2)

    if counter_max is not None and counter_max > 0:
        wrapped = (counter_max - first) + last
        if 0 <= wrapped <= counter_max:
            return EnergyResult(
                kwh=wrapped,
                basis=BASIS_COUNTER,
                coverage=1.0,
                samples=2,
                counter_reset=True,
            )

    # Meter swap, firmware reset or an unknown wrap point. Record that it
    # happened; do not invent a number for it.
    return EnergyResult(
        kwh=None, basis=BASIS_UNKNOWN, coverage=1.0, samples=2, counter_reset=True
    )
