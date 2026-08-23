"""Turning a storage plan's strategy into a setpoint, right now.

Until this module, a plan's ``strategy`` was mostly a label: the dispatch
engine executed scheduled windows and the workflow hand-off, and the built-in
policies were documentation. This is where each policy becomes arithmetic.

Every function here answers the same question - "what should the battery be
doing at this instant, in watts?" - from live readings, and returns ``None``
plus a reason when it cannot answer honestly (no readings, no tariff, stale
data). Guessing is the one thing none of them do: a control decision made
from a reading that stopped updating is how a battery ends up fighting
yesterday's load curve.

The order of authority, applied in :mod:`apps.ems.dispatch`:

1. A live demand-response event - a commitment to the grid outranks policy.
2. A scheduled window naming a power - the operator's explicit override.
3. The strategy below.
4. The plan envelope and the health constraints, clamping whatever won.

Cadence honesty: these run on the scheduler cycle (minutes). That is fine for
15-minute demand management and TOU boundaries; it is not a milliseconds PCS
loop and does not pretend to be.
"""

from __future__ import annotations

import datetime as dt
import json
import zoneinfo
from dataclasses import dataclass

from apps.core.logging import get_logger
from apps.ems.forecast import HOURS_PER_INTERVAL
from apps.ems.models import DemandResponseEvent, DispatchStrategy, StoragePlan
from apps.ems.replay import REPLAY
from apps.ems.tariffs import resolve_price

logger = get_logger("ems.strategy")

#: Ignore imbalances smaller than this; chasing noise wears the battery.
DEADBAND_KW = 0.2

_PRICE_RANGE_CACHE: dict = {}

#: Fraction of contract capacity used as the demand ceiling when the plan
#: does not name one. The gap is working room: the engine samples on the
#: scheduler cadence, and a ceiling equal to the contract leaves no margin
#: for load moving between samples.
DEFAULT_DEMAND_MARGIN = 0.95


@dataclass(slots=True)
class StrategyDecision:
    #: Watts; negative charges, positive discharges. ``None`` = no opinion.
    power_w: float | None
    reason: str


def _flow(site) -> dict:
    replay = REPLAY.get()
    if replay is not None:
        return replay.flow()
    # Local import: api.py imports the dispatch engine, which imports this
    # module - a top-level import here would close the circle.
    from apps.ems.api import _current_flow

    return _current_flow(site)


def _native_demand_kw(flow: dict) -> float | None:
    """Grid demand as it would be with the battery idle.

    The meter reading already contains whatever the battery is doing, so
    deciding from it directly chases the battery's own tail: a 120 kW charge
    lifts the meter 120 kW, the next cycle sees an excursion and orders a
    discharge, the cycle after sees headroom and orders the charge back.
    Subtracting the battery's flow (positive = discharge, which *lowers* the
    meter) gives the figure the decision actually has to manage.
    """
    grid_kw = flow.get("grid_kw")
    if grid_kw is None:
        return None
    return grid_kw + (flow.get("battery_kw") or 0.0)


# --------------------------------------------------------------------------
# Tariff helpers
# --------------------------------------------------------------------------
def _tariff_zone(tariff) -> dt.tzinfo:
    try:
        return zoneinfo.ZoneInfo(tariff.timezone_name or "UTC")
    except Exception:  # noqa: BLE001 - a bad timezone must not break dispatch
        return dt.timezone.utc


def todays_price_range(tariff, moment: dt.datetime) -> tuple[float, float]:
    """(cheapest, dearest) import price over the tariff's local day.

    Sampled every 15 minutes rather than solved symbolically: the tariff is a
    first-match-wins period list and 96 lookups are cheap, while reasoning
    about period overlap in closed form is exactly the kind of cleverness that
    breaks on a midnight-crossing window.
    """
    zone = _tariff_zone(tariff)
    local = moment.astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    # 每天 96 次 resolve_price 在回測裡會被呼叫上萬次；以 (方案, 日, 價格表) 為
    # 鍵快取。價格表本身進鍵，編輯方案後舊快取自然失效。
    key = (tariff.pk, start.date(), json.dumps(tariff.periods, sort_keys=True, default=str),
           tariff.default_import_price)
    cached = _PRICE_RANGE_CACHE.get(key)
    if cached is not None:
        return cached
    prices = [
        resolve_price(tariff, start + dt.timedelta(minutes=15 * step)).import_price
        for step in range(96)
    ]
    result = (min(prices), max(prices))
    if len(_PRICE_RANGE_CACHE) > 4096:
        _PRICE_RANGE_CACHE.clear()
    _PRICE_RANGE_CACHE[key] = result
    return result



def _window_decision(
    plan: StoragePlan, site, moment: dt.datetime, ceiling_kw: float, demand_kw: float
) -> tuple[StrategyDecision | None, str]:
    """需量窗口積分決策；``(None, note)`` 表示這一輪改走瞬時邏輯，note 說明原因。

    退回瞬時邏輯的情況只有兩種，且都寫進 reason 讓稽核看得到：窗口遙測
    涵蓋 < 0.8、或上一輪沒有可沿用的設定點而窗口剛開（沒東西可積分）。
    放電以外的情形（有餘裕）也交回原本的回充邏輯，那段沒有改。
    """
    from apps.ems import demand_window, forecast

    site_id = getattr(site, "id", site)  # 呼叫端可能傳 Site 也可能傳 UUID
    replay = REPLAY.get()
    if replay is not None:
        if replay.window_state is None:
            return None, "replay without window state"
        state = replay.window_state(moment)
        if state is None:
            return None, "replay without window state"
        memory = replay.memory
    else:
        state = demand_window.window_state(site_id, moment)
        memory = demand_window._last_decision
    previous_kw, same_window = demand_window.previous_for(site_id, state.window_start, memory=memory)
    if not state.is_trustworthy or state.elapsed_h <= 0:
        if state.elapsed_h <= 0 or state.reason == "no telemetry in window":
            # 窗口剛開：沿用上一個窗口的設定點，避免邊界瞬間歸零再重建。
            if previous_kw is not None and previous_kw > DEADBAND_KW:
                demand_window.remember(site_id, state.window_start, previous_kw, memory=memory)
                return StrategyDecision(previous_kw * 1000.0, f"window boundary: holding {previous_kw:.1f} kW"), ""
            return None, "window just opened, nothing to integrate"
        logger.info("demand_cap window fallback site=%s reason=%s", site_id, state.reason)
        return None, state.reason

    if replay is not None:
        margin_kw, margin_reason = (replay.margin_kw or 0.0), "replay"
    else:
        margin_kw, margin_reason = demand_window.safety_margin_kw(site_id)
    target_kw = ceiling_kw - margin_kw

    # 剩餘時間的功率：W1 已記錄的預測 > 目前瞬時值。讀 LoadForecast 表而不是
    # 現算——現算要掃 4 週區間，每 20 秒一次會把資料庫拖垮。
    predicted_kw = demand_kw
    if replay is not None:
        if replay.forecast_kw is not None:
            predicted = replay.forecast_kw(moment)
            if predicted is not None:
                predicted_kw = predicted
    else:
        recorded = forecast.recorded_native_kw(site_id, state.window_start)
        if recorded is not None:
            predicted_kw = recorded
    predicted_kw = max(predicted_kw, demand_kw)  # 實際已高於預測就信實際

    need_kw = demand_window.required_discharge_kw(
        state, target_kw, predicted_kw, moment, previous_kw=previous_kw if same_window else None
    )
    if need_kw is None:
        # 剩餘不足 60 秒且本窗口沒有前值：不重算，維持靜止。
        return StrategyDecision(0.0, "window tail: holding"), ""
    if need_kw > DEADBAND_KW:
        demand_window.remember(site_id, state.window_start, need_kw, memory=memory)
        projected_kw = (state.accumulated_kwh + state.remaining_h * max(predicted_kw, 0.0)) / HOURS_PER_INTERVAL
        return StrategyDecision(
            need_kw * 1000.0,
            f"window projection {projected_kw:.1f} kW over target {target_kw:.1f} kW"
            f" (margin {margin_reason}); discharge {need_kw:.1f} kW",
        ), ""
    demand_window.remember(site_id, state.window_start, 0.0, memory=memory)
    return None, ""

def demand_ceiling_kw(plan: StoragePlan) -> float | None:
    """Ceiling fallback chain: the explicit demand target, the older
    peak-shaving target (same idea, earlier name), then a margin under the
    contract capacity. ``None`` when the plan names nothing."""
    ceiling_kw = plan.demand_cap_target_kw
    if ceiling_kw is None:
        ceiling_kw = plan.peak_shaving_target_kw
    if ceiling_kw is None and plan.contract_capacity_kw:
        ceiling_kw = plan.contract_capacity_kw * DEFAULT_DEMAND_MARGIN
    return ceiling_kw or None


def battery_cycle_cost_per_kwh(site) -> float:
    """每 kWh 放電的循環成本：電池資產的 ``cycle_cost_per_kwh``，否則
    購置成本 ÷ 保固總吞吐量，都沒有就是 0（與 costs/battery.py 同一套規則）。"""
    from apps.ems.models import AssetRole, EnergyAsset

    replay = REPLAY.get()
    if replay is not None and replay.cycle_cost_per_kwh is not None:
        return replay.cycle_cost_per_kwh
    asset = (
        EnergyAsset.objects.filter(site_id=getattr(site, "id", site), role=AssetRole.BATTERY, is_active=True)
        .select_related("device").first()
    )
    if asset is None:
        return 0.0
    params = asset.cost_parameters or {}
    if params.get("cycle_cost_per_kwh") is not None:
        return float(params["cycle_cost_per_kwh"])
    throughput = params.get("warranted_throughput_kwh")
    capital = getattr(asset.device, "capital_cost", None)
    if throughput and capital:
        return float(capital) / float(throughput)
    return 0.0


# --------------------------------------------------------------------------
# The policies
# --------------------------------------------------------------------------
def demand_cap(plan: StoragePlan, site, moment: dt.datetime) -> StrategyDecision:
    """Hold grid import under the demand ceiling; recharge when it is safe.

    The recharge path is the subtle half. Charging *raises* grid demand, so it
    is allowed only up to the headroom below the ceiling - a battery that
    tripped the demand charge while refilling to prevent the demand charge
    would be a bad joke - and, when the plan says so, only during the tariff's
    cheapest period of the day.
    """
    ceiling_kw = demand_ceiling_kw(plan)
    if not ceiling_kw:
        return StrategyDecision(None, "no demand ceiling configured")

    flow = _flow(site)
    demand_kw = _native_demand_kw(flow)
    if demand_kw is None or flow.get("is_stale"):
        return StrategyDecision(None, "no fresh grid reading")

    # W2：先用窗口積分判斷，遙測涵蓋不足才退回瞬時比較。理由見
    # demand_window 模組開頭——台電算的是 15 分鐘平均，不是瞬時值。
    window, fallback_note = _window_decision(plan, site, moment, ceiling_kw, demand_kw)
    if window is not None:
        return window
    # 退回瞬時邏輯的原因要留在 reason 裡，稽核時才看得出那一輪為什麼沒積分。
    suffix = f" [window fallback: {fallback_note}]" if fallback_note else ""

    over_kw = demand_kw - ceiling_kw
    if over_kw > DEADBAND_KW:
        return StrategyDecision(
            over_kw * 1000.0, f"demand {demand_kw:.1f} kW over ceiling {ceiling_kw:.1f} kW{suffix}"
        )

    headroom_kw = ceiling_kw - demand_kw
    if plan.offpeak_recharge and headroom_kw > DEADBAND_KW:
        tariff = plan.tariff
        if tariff is not None:
            cheapest, _dearest = todays_price_range(tariff, moment)
            current = resolve_price(tariff, moment).import_price
            if current <= cheapest + 1e-9:
                charge_kw = headroom_kw
                if plan.max_charge_kw is not None:
                    charge_kw = min(charge_kw, plan.max_charge_kw)
                return StrategyDecision(
                    -charge_kw * 1000.0,
                    f"off-peak recharge within {headroom_kw:.1f} kW headroom",
                )

    return StrategyDecision(0.0, f"demand {demand_kw:.1f} kW under ceiling{suffix}")


def tou_arbitrage(plan: StoragePlan, site, moment: dt.datetime) -> StrategyDecision:
    """Charge through the day's trough, discharge through its peak.

    Acts only when the day's spread clears ``min_price_spread`` - shuffling
    energy through a ~90% round trip inside a flat price curve just pays for
    battery wear. Discharge is capped at the site's own load when export is
    disabled, because arbitrage revenue assumes the energy displaces bought
    energy; power pushed into a meter that pays nothing is a loss dressed as
    activity.
    """
    tariff = plan.tariff
    if tariff is None:
        return StrategyDecision(None, "no tariff on the plan")

    cheapest, dearest = todays_price_range(tariff, moment)
    if dearest - cheapest < (plan.min_price_spread or 0.0):
        return StrategyDecision(0.0, f"price spread {dearest - cheapest:.2f} below minimum")

    current = resolve_price(tariff, moment).import_price
    flow = _flow(site)

    if current >= dearest - 1e-9:
        discharge_kw = plan.max_discharge_kw or 0.0
        if plan.export_limit_kw == 0:
            load_kw = flow.get("load_kw")
            if load_kw is None or flow.get("is_stale"):
                return StrategyDecision(None, "export disabled and no fresh load reading")
            discharge_kw = min(discharge_kw, max(load_kw, 0.0))
        if discharge_kw <= DEADBAND_KW:
            return StrategyDecision(0.0, "peak period but nothing worth discharging")
        return StrategyDecision(discharge_kw * 1000.0, f"peak price {current:.2f}")

    if current <= cheapest + 1e-9:
        charge_kw = plan.max_charge_kw or 0.0
        # Never buy cheap energy at the cost of a demand-charge excursion -
        # and keep a margin under the contract, because a night-time charge
        # that lands exactly on the contract becomes the month's billed peak.
        if plan.contract_capacity_kw:
            demand_kw = _native_demand_kw(flow)
            if demand_kw is not None and not flow.get("is_stale"):
                ceiling_kw = plan.contract_capacity_kw * DEFAULT_DEMAND_MARGIN
                charge_kw = min(charge_kw, max(ceiling_kw - demand_kw, 0.0))
        if charge_kw <= DEADBAND_KW:
            return StrategyDecision(0.0, "trough price but no charging headroom")
        return StrategyDecision(-charge_kw * 1000.0, f"trough price {current:.2f}")

    return StrategyDecision(0.0, f"mid-range price {current:.2f}")


def self_consumption(plan: StoragePlan, site, moment: dt.datetime) -> StrategyDecision:
    """Soak up PV surplus, cover the deficit - swap feed-in for self-use."""
    flow = _flow(site)
    pv_kw = flow.get("pv_kw")
    load_kw = flow.get("load_kw")
    if pv_kw is None or load_kw is None or flow.get("is_stale"):
        return StrategyDecision(None, "no fresh PV/load readings")

    surplus_kw = pv_kw - load_kw
    if surplus_kw > DEADBAND_KW:
        charge_kw = surplus_kw
        if plan.max_charge_kw is not None:
            charge_kw = min(charge_kw, plan.max_charge_kw)
        return StrategyDecision(-charge_kw * 1000.0, f"PV surplus {surplus_kw:.1f} kW")
    if surplus_kw < -DEADBAND_KW:
        discharge_kw = -surplus_kw
        if plan.max_discharge_kw is not None:
            discharge_kw = min(discharge_kw, plan.max_discharge_kw)
        return StrategyDecision(discharge_kw * 1000.0, f"load deficit {-surplus_kw:.1f} kW")
    return StrategyDecision(0.0, "balanced")


def backup_only(plan: StoragePlan, site, moment: dt.datetime) -> StrategyDecision:
    """Keep the reserve topped up; otherwise leave the battery alone."""
    from apps.ems.dispatch import _battery_soc

    soc = _battery_soc(site.pk if hasattr(site, "pk") else site)
    if soc is None:
        return StrategyDecision(None, "no SOC reading")
    target = max(plan.backup_reserve_percent, plan.min_soc_percent)
    if soc < target:
        charge_kw = plan.max_charge_kw or 0.0
        if plan.contract_capacity_kw:
            flow = _flow(site)
            demand_kw = flow.get("grid_kw")
            if demand_kw is not None and not flow.get("is_stale"):
                charge_kw = min(charge_kw, max(plan.contract_capacity_kw - demand_kw, 0.0))
        if charge_kw <= DEADBAND_KW:
            return StrategyDecision(0.0, "reserve low but no charging headroom")
        return StrategyDecision(-charge_kw * 1000.0, f"SOC {soc:.0f}% below reserve {target:.0f}%")
    return StrategyDecision(0.0, "reserve held")


_POLICIES = {
    DispatchStrategy.DEMAND_CAP: demand_cap,
    DispatchStrategy.PEAK_SHAVING: demand_cap,  # same arithmetic, older name
    DispatchStrategy.TOU_ARBITRAGE: tou_arbitrage,
    DispatchStrategy.SELF_CONSUMPTION: self_consumption,
    DispatchStrategy.BACKUP_ONLY: backup_only,
}


def single_strategy_power_w(plan: StoragePlan, site, moment: dt.datetime, strategy: str) -> StrategyDecision:
    """One named strategy, evaluated now. Manual and workflow have no opinion."""
    policy = _POLICIES.get(strategy)
    if policy is None:
        return StrategyDecision(None, f"strategy {strategy} computes no setpoint")
    return policy(plan, site, moment)


def strategy_power_w(plan: StoragePlan, site, moment: dt.datetime) -> StrategyDecision:
    """The plan's strategy (or stacked strategies, W5), evaluated now.

    單一策略走原本的路徑，一個位元都不變——相容性測試釘住。兩個以上才交給
    仲裁器。
    """
    active = plan.active_strategies
    if len(active) <= 1:
        return single_strategy_power_w(plan, site, moment, plan.strategy)
    from apps.ems.arbitration import arbitrate, propose

    return arbitrate(propose(plan, site, moment), plan)


# --------------------------------------------------------------------------
# Demand response
# --------------------------------------------------------------------------
def live_dr_event(site_id, moment: dt.datetime) -> DemandResponseEvent | None:
    return (
        DemandResponseEvent.objects.filter(
            site_id=site_id,
            cancelled_at__isnull=True,
            starts_at__lte=moment,
            ends_at__gt=moment,
        )
        .order_by("-starts_at")
        .first()
    )


# --------------------------------------------------------------------------
# Health constraints
# --------------------------------------------------------------------------
def cycles_used_today(plan: StoragePlan, site_id, moment: dt.datetime) -> float | None:
    """Full-cycle-equivalents discharged since local midnight.

    Read from the energy intervals the aggregator already writes, so the
    number survives restarts and counts *all* discharge, not just what this
    engine commanded.
    """
    if not plan.usable_capacity_kwh:
        return None
    from apps.ems.models import EnergyInterval

    zone = _tariff_zone(plan.tariff) if plan.tariff else dt.timezone.utc
    local = moment.astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)

    discharged = (
        EnergyInterval.objects.filter(
            site_id=site_id, interval_start__gte=midnight.astimezone(dt.timezone.utc)
        ).values_list("battery_discharge_kwh", flat=True)
    )
    total = sum(value for value in discharged if value)
    return total / plan.usable_capacity_kwh


def battery_temperature(plan: StoragePlan, site_id) -> float | None:
    if not plan.temperature_metric:
        return None
    from apps.ems.dispatch import battery_device
    from apps.telemetry.models import LatestSample

    device = battery_device(site_id)
    if device is None:
        return None
    row = (
        LatestSample.objects.filter(device=device, metric_key=plan.temperature_metric)
        .values_list("value", flat=True)
        .first()
    )
    return float(row) if row is not None else None


def apply_health_constraints(
    plan: StoragePlan, site_id, power_w: float, moment: dt.datetime
) -> tuple[float, str]:
    """The battery-preservation gate every strategy's output passes through.

    Ordered from most to least absolute: an over-temperature battery is not
    driven in either direction; a battery that has spent its daily cycle
    budget still charges (charging ends the day's *discharge* budget no
    faster) but stops discharging for economics.
    """
    if power_w == 0:
        return power_w, ""

    if plan.temperature_max_c is not None:
        temperature = battery_temperature(plan, site_id)
        if temperature is not None and temperature > plan.temperature_max_c:
            return 0.0, f"temperature {temperature:.1f}C over limit"

    if power_w > 0 and plan.max_cycles_per_day:
        cycles = cycles_used_today(plan, site_id, moment)
        if cycles is not None and cycles >= plan.max_cycles_per_day:
            return 0.0, f"daily cycle budget spent ({cycles:.2f})"

    return power_w, ""
