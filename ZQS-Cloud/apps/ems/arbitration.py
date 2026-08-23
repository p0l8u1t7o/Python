"""策略疊加仲裁（W5）：硬約束定界，軟目標在界內依貨幣化價值排序。

台中廠 1 MW / 2 MWh 的電池離峰充飽、尖峰放電，本來就同時在削需量；
``demand_cap`` 的離峰回充挑最便宜時段，已經是半個套利。單選策略把這些價值
丟掉了。這裡不做最佳化求解器——先用優先序仲裁，等回測（W3）證明剩餘價值
可觀再談 MILP。

    硬約束（違反的成本遠高於任何收益）
      1. 需量上限        —— 超約罰款是費率的 2–3 倍
      2. 備援保留 SOC
      （3. 電池健康、4. 運轉包絡：由 decide() 的 clamp_to_plan / apply_health_constraints
        統一夾限，所有來源一視同仁，這裡不重做。）
    軟目標，依每小時貨幣價值排序
      5. 套利：價差 − 循環成本
      6. PV 自用：購電價 − 躉售價

仲裁輸出一個設定點：硬約束給出 ``[min_w, max_w]``（負 = 充電、正 = 放電），
最高價值的軟提案夾進這個區間；沒有軟提案就用硬約束自己的值。兩個硬約束
衝突（需量要放電、備援要充電）時需量上限贏——罰款比少一點備援更貴，
而且備援保留在 ``clamp_to_plan`` 還有一道 SOC 下限守著。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from apps.ems.models import DispatchStrategy, StoragePlan
from apps.ems.tariffs import resolve_price

#: 能疊加的策略：會算出設定點、而且有「值」可比的那些。
STACKABLE = frozenset({
    DispatchStrategy.DEMAND_CAP,
    DispatchStrategy.PEAK_SHAVING,
    DispatchStrategy.TOU_ARBITRAGE,
    DispatchStrategy.SELF_CONSUMPTION,
    DispatchStrategy.BACKUP_ONLY,
})
HARD = frozenset({DispatchStrategy.DEMAND_CAP, DispatchStrategy.PEAK_SHAVING, DispatchStrategy.BACKUP_ONLY})


@dataclass(slots=True)
class StrategyProposal:
    strategy: str
    #: Watts；負充電、正放電；None = 這個策略這一輪沒有意見。
    power_w: float | None
    reason: str
    is_hard: bool = False
    #: 軟目標：照這個設定點跑一小時值多少錢（已扣循環成本）。硬約束不填。
    value_per_hour: float = 0.0
    #: 硬約束給的界：至少放電多少（min_w）、最多充電多少（max_charge_w，負值）。
    min_w: float | None = None
    max_charge_w: float | None = None


def _price(plan: StoragePlan, moment: dt.datetime):
    tariff = plan.tariff
    return resolve_price(tariff, moment) if tariff is not None else None


def propose(plan: StoragePlan, site, moment: dt.datetime) -> list[StrategyProposal]:
    """每個啟用的策略各提一案。策略函式本身不改，這裡只是替它們標價。"""
    from apps.ems import strategy as policies

    proposals: list[StrategyProposal] = []
    cycle_cost = None  # 懶讀：沒有套利就不用查
    for key in plan.active_strategies:
        if key not in STACKABLE:
            continue
        decision = policies.single_strategy_power_w(plan, site, moment, key)
        power_w = decision.power_w
        proposal = StrategyProposal(key, power_w, decision.reason, is_hard=key in HARD)

        if key in (DispatchStrategy.DEMAND_CAP, DispatchStrategy.PEAK_SHAVING):
            # 放電需求是下界；餘裕（上限 − native）是充電上限，避免回充把需量充爆。
            if power_w is not None and power_w > 0:
                proposal.min_w = power_w
            headroom_kw = _demand_headroom_kw(plan, site)
            if headroom_kw is not None:
                proposal.max_charge_w = -max(headroom_kw, 0.0) * 1000.0
        elif key == DispatchStrategy.BACKUP_ONLY:
            # 低於備援水位時要求充電；arbitrate() 直接讀它的 power_w 當充電下限。
            pass
        elif key == DispatchStrategy.TOU_ARBITRAGE and power_w:
            price = _price(plan, moment)
            if price is not None:
                cheapest, dearest = policies.todays_price_range(plan.tariff, moment)
                if cycle_cost is None:
                    cycle_cost = policies.battery_cycle_cost_per_kwh(site)
                kw = abs(power_w) / 1000.0
                efficiency = float(plan.round_trip_efficiency or 1.0)
                if power_w > 0:
                    # 放出去的每 kWh 省下現價；它是用最便宜的價買進來的，要除效率。
                    margin = price.import_price - cheapest / efficiency - cycle_cost
                else:
                    # 充進來的每 kWh 之後以最高價放出；今天現價買、扣效率與循環成本。
                    margin = dearest * efficiency - price.import_price - cycle_cost
                proposal.value_per_hour = kw * margin
        elif key == DispatchStrategy.SELF_CONSUMPTION and power_w:
            price = _price(plan, moment)
            if price is not None:
                kw = abs(power_w) / 1000.0
                if cycle_cost is None:
                    cycle_cost = policies.battery_cycle_cost_per_kwh(site)
                # 把原本要躉售的 PV 存起來自用：每 kWh 值「購電價 − 躉售價」，放電時再扣循環。
                margin = price.import_price - (price.export_price or 0.0)
                if power_w > 0:
                    margin -= cycle_cost
                proposal.value_per_hour = kw * margin
        proposals.append(proposal)
    return proposals


def _demand_headroom_kw(plan: StoragePlan, site) -> float | None:
    from apps.ems import strategy as policies

    ceiling_kw = policies.demand_ceiling_kw(plan)
    if ceiling_kw is None:
        return None
    flow = policies._flow(site)
    demand_kw = policies._native_demand_kw(flow)
    if demand_kw is None or flow.get("is_stale"):
        return None
    return ceiling_kw - demand_kw


def arbitrate(proposals: list[StrategyProposal], plan: StoragePlan):
    """把提案解成一個設定點。回傳 StrategyDecision（與單策略同型別）。"""
    from apps.ems.strategy import StrategyDecision

    if not proposals:
        return StrategyDecision(None, "no stackable strategy produced a proposal")

    min_w: float | None = None  # 至少放電（正）或至少充電（負）
    max_charge_w: float | None = None  # 最多充到（負值，越接近 0 越嚴）
    notes: list[str] = []
    for p in proposals:
        if not p.is_hard:
            continue
        if p.strategy == DispatchStrategy.BACKUP_ONLY and p.power_w is not None and p.power_w < 0:
            # 備援要求充電：若需量已要求放電，需量贏（規則 1 > 2），只記下來。
            if min_w is not None and min_w > 0:
                notes.append(f"backup_only wants {p.power_w / 1000:.0f} kW charge but demand cap outranks")
            else:
                min_w = p.power_w if min_w is None else min(min_w, p.power_w)
                notes.append(f"backup_only: {p.reason}")
            continue
        if p.min_w is not None:
            min_w = p.min_w if min_w is None or min_w < 0 else max(min_w, p.min_w)
            notes.append(f"{p.strategy}: {p.reason}")
        if p.max_charge_w is not None:
            max_charge_w = p.max_charge_w if max_charge_w is None else max(max_charge_w, p.max_charge_w)

    # 備援要求的充電也得尊重需量餘裕：充太猛就是超約。
    if min_w is not None and min_w < 0 and max_charge_w is not None and min_w < max_charge_w:
        notes.append(f"charge limited to {-max_charge_w / 1000:.0f} kW demand headroom")
        min_w = max_charge_w

    soft = [p for p in proposals if not p.is_hard and p.power_w is not None and abs(p.power_w) > 0]
    soft.sort(key=lambda p: p.value_per_hour, reverse=True)

    chosen: float
    source: str
    if soft and soft[0].value_per_hour > 0:
        best = soft[0]
        chosen = best.power_w
        source = f"{best.strategy}: {best.reason} (≈{best.value_per_hour:.0f}/h)"
        # 夾進硬約束的界內。
        if min_w is not None and chosen < min_w:
            notes.append(f"{best.strategy} {chosen / 1000:.0f} kW raised to {min_w / 1000:.0f} kW by hard constraint")
            chosen = min_w
        if chosen < 0 and max_charge_w is not None and chosen < max_charge_w:
            notes.append(f"{best.strategy} charge {-chosen / 1000:.0f} kW capped at {-max_charge_w / 1000:.0f} kW demand headroom")
            chosen = max_charge_w
    else:
        # 沒有值得做的軟目標：執行硬約束自己的值（需量放電／回充、備援充電）。
        hard = [p for p in proposals if p.is_hard and p.power_w is not None]
        if min_w is not None:
            chosen = min_w
            source = notes[0] if notes else "hard constraint"
        elif hard:
            # demand_cap 的離峰回充等「非強制」的硬策略輸出；取第一個非零者。
            first = next((p for p in hard if p.power_w), hard[0])
            chosen = first.power_w
            source = f"{first.strategy}: {first.reason}"
            if chosen < 0 and max_charge_w is not None and chosen < max_charge_w:
                chosen = max_charge_w
        else:
            return StrategyDecision(None, "no strategy produced a setpoint")
        if soft:
            notes.append(f"{soft[0].strategy} not worth it (≈{soft[0].value_per_hour:.0f}/h)")

    reason = source + (f" [{'; '.join(n for n in notes if n != source)}]" if notes else "")
    return StrategyDecision(chosen, reason)
