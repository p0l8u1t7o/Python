"""離線回測：把一個儲能方案套在歷史負載上，算出它「會」花多少錢。

「客戶問『換成時間電價套利會省多少』，目前只能憑感覺回答。」回測用
EnergyInterval 裡的 **native 負載與 PV**（不含電池動作）重播場域，讓
同一份策略程式碼（經 :mod:`apps.ems.replay` 注入）逐分鐘決策，用簡化的
電池模型積分 SOC，再依電價方案算能源費、需量費、超約罰款與循環成本。

三個不變量：

* **不寫資料庫**。回測是分析工具，輸出只回傳給呼叫端。
* **策略程式碼不分叉**。回測證明的是 ``apps/ems/strategy.py`` 的行為，不是
  一份另寫的簡化版；需量窗口積分控制（W2）在這裡一樣生效。
* **成本公式同一套**。能源費用 ``resolve_price``，罰款用 ``demand.excess_charge``，
  循環成本讀電池資產的 ``cycle_cost_per_kwh``——與報表走相同函式，數字才對得上。

簡化之處要說清楚：15 分鐘區間內負載視為常數（歷史資料就這個解析度，階躍
負載看不到），電池模型只有功率上下限、SOC 上下限、往返效率；沒有溫度、沒有
健康約束的每日循環上限。這些是回測的「比報表樂觀」的方向，讀數字時要知道。
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass, field

from apps.ems.demand import excess_charge
from apps.ems.demand_window import WindowState
from apps.ems.dispatch import clamp_to_plan
from apps.ems.forecast import HOURS_PER_INTERVAL, INTERVAL
from apps.ems.models import AssetRole, DispatchStrategy, EnergyAsset, EnergyInterval, StoragePlan
from apps.ems.replay import ReplayContext, replaying
from apps.ems.strategy import strategy_power_w
from apps.ems.tariffs import resolve_price

#: 策略評估步長。正式路徑是 20–60 秒；回測用 1 分鐘，夠讓窗口積分邏輯
#: 在 15 分鐘內改變多次決策，又不至於讓一個月的回放跑太久。
STEP = dt.timedelta(minutes=1)


@dataclass(slots=True)
class BacktestInterval:
    starts_at: dt.datetime
    native_load_kw: float
    pv_kw: float
    battery_kw: float  # 正 = 放電（區間平均）
    grid_kw: float  # 正 = 購電（區間平均）
    soc_percent: float
    energy_cost: float
    reason: str


@dataclass(slots=True)
class BacktestResult:
    site_id: object
    strategy: str
    start: dt.datetime
    end: dt.datetime
    energy_cost: float
    demand_charge: float
    penalty: float
    cycle_cost: float
    #: 起訖 SOC 差額以期間平均購電價計價：放掉的初始電量不是免費的，
    #: 留在電池裡的電量也不是白花的。少了這項，「把電池放光」會看起來像省錢。
    stored_energy_adjustment: float
    total: float
    peak_demand_kw: float | None
    equivalent_cycles: float
    intervals: list[BacktestInterval] = field(default_factory=list)
    #: 「沒有電池」的對照組；比較欄位要同一段歷史算出來才有意義。
    baseline_total: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def savings(self) -> float | None:
        return None if self.baseline_total is None else self.baseline_total - self.total

    def summary(self) -> dict:
        return {
            "strategy": self.strategy,
            "energy_cost": round(self.energy_cost, 2),
            "demand_charge": round(self.demand_charge, 2),
            "penalty": round(self.penalty, 2),
            "cycle_cost": round(self.cycle_cost, 2),
            "stored_energy_adjustment": round(self.stored_energy_adjustment, 2),
            "total": round(self.total, 2),
            "baseline_total": None if self.baseline_total is None else round(self.baseline_total, 2),
            "savings": None if self.savings is None else round(self.savings, 2),
            "peak_demand_kw": None if self.peak_demand_kw is None else round(self.peak_demand_kw, 1),
            "equivalent_cycles": round(self.equivalent_cycles, 2),
            "intervals": len(self.intervals),
            "notes": list(self.notes),
        }


class _Battery:
    """夠用的電池：功率限制、SOC 限制、往返效率。沒有的東西見模組說明。"""

    def __init__(self, plan: StoragePlan, soc_percent: float):
        self.capacity_kwh = float(plan.usable_capacity_kwh or 0.0)
        self.soc = soc_percent
        self.min_soc = max(plan.min_soc_percent, plan.backup_reserve_percent)
        self.max_soc = plan.max_soc_percent
        # 往返效率拆成充放各一半（幾何平均），與 battery_cycle 成本模型一致。
        self.one_way = float(plan.round_trip_efficiency or 1.0) ** 0.5
        self.max_charge_kw = plan.max_charge_kw
        self.max_discharge_kw = plan.max_discharge_kw
        self.discharged_kwh = 0.0
        self.charged_kwh = 0.0

    def apply(self, setpoint_kw: float, hours: float) -> float:
        """套用設定點一段時間，回傳實際平均功率（受 SOC 與容量限制）。"""
        if self.capacity_kwh <= 0:
            return 0.0
        kw = setpoint_kw
        if kw > 0:
            if self.max_discharge_kw is not None:
                kw = min(kw, self.max_discharge_kw)
            available_kwh = max((self.soc - self.min_soc) / 100.0 * self.capacity_kwh, 0.0)
            deliverable_kwh = available_kwh * self.one_way
            kw = min(kw, deliverable_kwh / hours) if hours > 0 else 0.0
            drawn = kw * hours / self.one_way
            self.soc -= drawn / self.capacity_kwh * 100.0
            self.discharged_kwh += kw * hours
        elif kw < 0:
            if self.max_charge_kw is not None:
                kw = max(kw, -self.max_charge_kw)
            room_kwh = max((self.max_soc - self.soc) / 100.0 * self.capacity_kwh, 0.0)
            kw = max(kw, -(room_kwh / self.one_way) / hours) if hours > 0 else 0.0
            stored = -kw * hours * self.one_way
            self.soc += stored / self.capacity_kwh * 100.0
            self.charged_kwh += -kw * hours
        return kw


def _cycle_cost_per_kwh(site_id) -> float:
    asset = (
        EnergyAsset.objects.filter(site_id=site_id, role=AssetRole.BATTERY, is_active=True)
        .select_related("device").first()
    )
    if asset is None:
        return 0.0
    explicit = (asset.cost_parameters or {}).get("cycle_cost_per_kwh")
    if explicit is not None:
        return float(explicit)
    throughput = (asset.cost_parameters or {}).get("warranted_throughput_kwh")
    capital = getattr(asset.device, "capital_cost", None)
    if throughput and capital:
        return float(capital) / float(throughput)
    return 0.0


def _native_intervals(site_id, start: dt.datetime, end: dt.datetime) -> list[tuple[dt.datetime, float, float]]:
    """(starts_at, native_load_kw, pv_kw)。load_kwh 已是場域負載（不含電池）。"""
    rows = EnergyInterval.objects.filter(
        site_id=site_id, interval_start__gte=start, interval_start__lt=end,
    ).order_by("interval_start").values_list("interval_start", "load_kwh", "pv_kwh", "coverage")
    out = []
    for starts_at, load_kwh, pv_kwh, coverage in rows:
        if coverage is not None and coverage < 0.5:
            continue  # 殘缺區間不重播——用 0 重播會把一個斷線變成「省了一筆」
        out.append((starts_at, (load_kwh or 0.0) / HOURS_PER_INTERVAL, (pv_kwh or 0.0) / HOURS_PER_INTERVAL))
    return out


def _billing_months(start: dt.datetime, end: dt.datetime, zone) -> list[tuple[dt.datetime, dt.datetime]]:
    months = []
    cursor = start.astimezone(zone).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        nxt = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        months.append((cursor, min(nxt, end.astimezone(zone))))
        cursor = nxt
    return months


def run_backtest(
    site,
    plan: StoragePlan,
    start: dt.datetime,
    end: dt.datetime,
    *,
    strategy: str | list[str] | None = None,
    initial_soc_percent: float = 50.0,
    with_battery: bool = True,
    keep_intervals: bool = True,
) -> BacktestResult:
    """重播 ``[start, end)``。``with_battery=False`` 產生對照組。"""
    site_id = getattr(site, "id", site)
    # ``strategy`` 可以是單一鍵或疊加清單（W5）；清單第一個是主策略。
    if strategy is None:
        strategies = plan.active_strategies
    elif isinstance(strategy, str):
        strategies = [strategy]
    else:
        strategies = list(strategy)
    if strategies != plan.active_strategies:
        # 不動原方案：複製一份記憶體內的 plan 來改策略，資料庫不被碰。
        plan = StoragePlan(**{f.name: getattr(plan, f.name) for f in StoragePlan._meta.concrete_fields})
        plan.strategy = strategies[0]
        plan.strategies = strategies
    strategy = "+".join(strategies)
    tariff = plan.tariff
    zone = zoneinfo.ZoneInfo(tariff.timezone_name) if tariff else dt.timezone.utc
    notes: list[str] = []
    if tariff is None:
        notes.append("plan has no tariff: energy cost and demand charge are zero")

    native = _native_intervals(site_id, start, end)
    if not native:
        notes.append("no energy intervals in range")

    battery = _Battery(plan, initial_soc_percent) if with_battery else None
    cycle_cost_rate = _cycle_cost_per_kwh(site_id) if with_battery else 0.0
    if with_battery and cycle_cost_rate == 0.0:
        notes.append("battery cycle cost unknown (no cycle_cost_per_kwh): cycle_cost = 0")

    # 回放狀態，由 ReplayContext 的 closure 讀取。
    state = {"load": 0.0, "pv": 0.0, "battery": 0.0, "window_kwh": 0.0, "window_start": None}

    def flow() -> dict:
        grid = state["load"] - state["pv"] - state["battery"]
        return {
            "grid_kw": grid, "pv_kw": state["pv"], "load_kw": state["load"],
            "battery_kw": state["battery"], "is_stale": False,
        }

    def window_state(moment: dt.datetime) -> WindowState | None:
        ws = state["window_start"]
        if ws is None:
            return None
        elapsed_h = (moment - ws).total_seconds() / 3600.0
        return WindowState(
            window_start=ws, accumulated_kwh=state["window_kwh"], coverage=1.0,
            is_trustworthy=True, elapsed_h=elapsed_h, last_native_kw=state["load"] - state["pv"],
        )

    ctx = ReplayContext(
        flow=flow,
        soc=lambda: battery.soc if battery else None,
        window_state=window_state,
        # 回測用完美預測：區間內負載就是常數。這讓回測比實際樂觀，有註記。
        forecast_kw=lambda moment: state["load"] - state["pv"],
        margin_kw=0.0,
        cycle_cost_per_kwh=cycle_cost_rate,
    )
    notes.append("forecast inside replay is perfect (interval load is constant): results are optimistic")

    # 只有需量窗口控制在 15 分鐘內會改變決策；其他策略的輸入在區間內是常數，
    # 每區間評估一次就夠，少跑 15 倍。
    windowed = bool({DispatchStrategy.DEMAND_CAP, DispatchStrategy.PEAK_SHAVING} & set(strategies))
    step = STEP if windowed else INTERVAL
    step_h = step.total_seconds() / 3600.0

    intervals: list[BacktestInterval] = []
    energy_cost = 0.0
    import_price_sum = 0.0
    # 每個計費月的需量峰值（15 分鐘平均購電）。
    month_peaks: dict[dt.datetime, float] = {}
    months = _billing_months(start, end, zone)

    with replaying(ctx):
        for starts_at, load_kw, pv_kw in native:
            state["load"], state["pv"] = load_kw, pv_kw
            state["window_start"], state["window_kwh"] = starts_at, 0.0
            step_powers: list[float] = []
            moment = starts_at
            while moment < starts_at + INTERVAL:
                if battery is not None:
                    decision = strategy_power_w(plan, site_id, moment)
                    setpoint_kw = (decision.power_w or 0.0) / 1000.0
                    clamped_w, _why = clamp_to_plan(plan, setpoint_kw * 1000.0, soc_percent=battery.soc)
                    actual_kw = battery.apply(clamped_w / 1000.0, step_h)
                    reason = decision.reason
                else:
                    actual_kw, reason = 0.0, "no battery"
                state["battery"] = actual_kw
                step_powers.append(actual_kw)
                # 累積的是電表（含電池），與正式路徑的 window_state 一致。
                state["window_kwh"] += (load_kw - pv_kw - actual_kw) * step_h
                moment += step

            battery_avg = sum(step_powers) / len(step_powers)
            grid_avg = load_kw - pv_kw - battery_avg
            price = resolve_price(tariff, starts_at) if tariff else None
            import_kwh = max(grid_avg, 0.0) * HOURS_PER_INTERVAL
            export_kwh = max(-grid_avg, 0.0) * HOURS_PER_INTERVAL
            cost = 0.0
            if price is not None:
                cost = import_kwh * price.import_price - export_kwh * (price.export_price or 0.0)
                import_price_sum += price.import_price
            energy_cost += cost
            for month_start, month_end in months:
                if month_start <= starts_at.astimezone(zone) < month_end:
                    month_peaks[month_start] = max(month_peaks.get(month_start, 0.0), grid_avg)
            if keep_intervals:
                intervals.append(BacktestInterval(
                    starts_at, load_kw, pv_kw, battery_avg, grid_avg,
                    battery.soc if battery else 0.0, cost, reason,
                ))

    demand_rate = float(tariff.demand_charge_per_kw) if tariff else 0.0
    contract = float(plan.contract_capacity_kw or 0.0)
    demand_charge = 0.0
    penalty = 0.0
    for month_start, peak in month_peaks.items():
        billed = max(peak, 0.0)
        demand_charge += billed * demand_rate
        penalty += excess_charge(billed, contract, demand_rate)
    if months and demand_rate and len(months) == 1 and (end - start) < dt.timedelta(days=28):
        notes.append("range shorter than a billing month: demand charge is the period peak × rate, not pro-rated")

    cycle_cost = (battery.discharged_kwh if battery else 0.0) * cycle_cost_rate
    cycles = 0.0
    if battery and battery.capacity_kwh > 0:
        cycles = battery.discharged_kwh / battery.capacity_kwh
    peak = max(month_peaks.values()) if month_peaks else None
    stored_adjustment = 0.0
    if battery and battery.capacity_kwh > 0 and native:
        mean_price = import_price_sum / len(native)
        net_drawn_kwh = (initial_soc_percent - battery.soc) / 100.0 * battery.capacity_kwh
        stored_adjustment = net_drawn_kwh * mean_price
    total = energy_cost + demand_charge + penalty + cycle_cost + stored_adjustment
    return BacktestResult(
        site_id=site_id, strategy=strategy if with_battery else "no_battery",
        start=start, end=end,
        energy_cost=energy_cost, demand_charge=demand_charge, penalty=penalty,
        cycle_cost=cycle_cost, stored_energy_adjustment=stored_adjustment, total=total,
        peak_demand_kw=peak, equivalent_cycles=cycles,
        intervals=intervals, notes=notes,
    )


def backtest_with_baseline(site, plan: StoragePlan, start: dt.datetime, end: dt.datetime, **kwargs) -> BacktestResult:
    """策略結果＋「沒有電池」對照組，``savings`` 才有東西可填。"""
    baseline = run_backtest(site, plan, start, end, with_battery=False, keep_intervals=False)
    result = run_backtest(site, plan, start, end, **kwargs)
    result.baseline_total = baseline.total
    return result


def compare_strategies(
    site, plan: StoragePlan, start: dt.datetime, end: dt.datetime, strategies: list | None = None
) -> list[BacktestResult]:
    """同一段歷史跑多個策略（含 W5 疊加組合），回傳依 total 由低到高排序。"""
    strategies = strategies or [
        DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE,
        DispatchStrategy.SELF_CONSUMPTION, DispatchStrategy.BACKUP_ONLY,
        [DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE],
        [DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE, DispatchStrategy.SELF_CONSUMPTION],
    ]
    baseline = run_backtest(site, plan, start, end, with_battery=False, keep_intervals=False)
    results = []
    for strategy in strategies:
        result = run_backtest(site, plan, start, end, strategy=strategy, keep_intervals=False)
        result.baseline_total = baseline.total
        results.append(result)
    results.sort(key=lambda r: r.total)
    return results
