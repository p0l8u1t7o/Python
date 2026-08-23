"""月結算：把一個場域一個當地月份的 EnergyInterval 結成一張對得上帳單的表。

三條規則：

* **能源費、逆送收入、節省都直接加總 EnergyInterval 的欄位**，不另算一套——
  那三個欄位是儀表板、``_totals()``、跨場域 rollup 的共同來源，結算表的數字
  必須與整月窗口的 ``/ems/cost-overview`` 一致（驗收條件）。
* **需量費與超約罰款在這裡才真正進帳**：取月內最高的 15 分鐘購電平均，
  乘方案電價的月費率；罰款沿用 :func:`apps.ems.demand.excess_charge`。
* **封存後不再變動**。``finalized_at`` 有值的月份 :func:`settle` 原樣回傳；
  快照在結算時抄下電價與參數，之後改電價影響不到它。

冪等：同一個月重跑，輸出相同（未封存的月份會用現行設定重算，這是刻意
的——進行中的月份就該反映最新設定）。
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass

from django.db.models import F, FloatField, Max, Sum
from django.db.models.expressions import ExpressionWrapper
from django.utils.timezone import now

from apps.ems.demand import excess_charge
from apps.ems.models import (
    EnergyAsset,
    EnergyInterval,
    MonthlySettlement,
    SavingsBaseline,
    SettlementBasis,
)
from apps.ems.plans import effective_plan

#: 次月幾號封存上個月。台電抄表在月初；5 號前的重算讓遲到的遙測補進來。
FINALIZE_DAY = 5
#: 區間涵蓋率低於此視為估計值，再低視為未知——與 EnergyInterval 同一套門檻。
ESTIMATED_COVERAGE = 0.8
UNKNOWN_COVERAGE = 0.5


def parse_month(text: str) -> dt.date:
    """``"2026-07"`` → ``date(2026, 7, 1)``。"""
    year, month = text.split("-", 1)
    return dt.date(int(year), int(month), 1)


def next_month(month: dt.date) -> dt.date:
    return (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def site_zone(site) -> dt.tzinfo:
    try:
        return zoneinfo.ZoneInfo(site.timezone_name or "UTC")
    except Exception:  # noqa: BLE001 - 錯的時區名不該讓結算掛掉
        return dt.timezone.utc


def month_bounds(site, month: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """當地月份的 UTC 區間 ``[start, end)``。"""
    zone = site_zone(site)
    start = dt.datetime(month.year, month.month, 1, tzinfo=zone)
    end_month = next_month(month)
    end = dt.datetime(end_month.year, end_month.month, 1, tzinfo=zone)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def _snapshot_tariff(plan) -> dict:
    if plan is None:
        return {}
    tariff = plan.tariff
    out = {
        "plan": {
            "id": str(plan.id), "name": plan.name, "strategy": plan.strategy,
            "contract_capacity_kw": plan.contract_capacity_kw,
            "savings_baseline": plan.savings_baseline,
            "round_trip_efficiency": plan.round_trip_efficiency,
        },
    }
    if tariff is not None:
        out["tariff"] = {
            "id": str(tariff.id), "name": tariff.name, "kind": tariff.kind,
            "currency": tariff.currency, "timezone_name": tariff.timezone_name,
            "demand_charge_per_kw": tariff.demand_charge_per_kw,
            "default_import_price": tariff.default_import_price,
            "default_export_price": tariff.default_export_price,
            "periods": tariff.periods,
        }
    return out


def _snapshot_cost_parameters(site) -> dict:
    return {
        str(asset.id): {
            "device": asset.device.device_id, "role": asset.role,
            "cost_model": asset.cost_model, "cost_parameters": asset.cost_parameters,
        }
        for asset in EnergyAsset.objects.filter(site=site, is_active=True).select_related("device")
        if asset.cost_parameters
    }


@dataclass(slots=True)
class _Figures:
    energy_charge: float
    export_revenue: float
    savings_energy: float | None  # 加總的 estimated_savings；任一區間 null → null
    peak_kw: float | None
    peak_at: dt.datetime | None
    baseline_peak_kw: float | None
    interval_count: int
    coverage: float
    basis: str


def _figures(site, start: dt.datetime, end: dt.datetime, *, baseline_kind: str) -> _Figures:
    qs = EnergyInterval.objects.filter(site=site, interval_start__gte=start, interval_start__lt=end)
    per_hour = 3600.0
    demand = ExpressionWrapper(F("grid_import_kwh") * per_hour / F("interval_seconds"), output_field=FloatField())
    # 基準線峰值跟 savings_baseline 一致：grid_only 是「全部買電」（負載本身），
    # no_storage 是「有 PV 沒電池」（負載 − PV）。
    if baseline_kind == SavingsBaseline.GRID_ONLY:
        baseline_expr = F("load_kwh") * per_hour / F("interval_seconds")
    else:
        baseline_expr = (F("load_kwh") - F("pv_kwh")) * per_hour / F("interval_seconds")
    baseline = ExpressionWrapper(baseline_expr, output_field=FloatField())
    sums = qs.aggregate(
        cost=Sum("energy_cost"), revenue=Sum("export_revenue"), savings=Sum("estimated_savings"),
        peak=Max(demand), baseline_peak=Max(baseline), seconds=Sum("interval_seconds"),
    )
    count = qs.count()
    if count == 0:
        return _Figures(0.0, 0.0, None, None, None, None, 0, 0.0, SettlementBasis.UNKNOWN)

    # 任一區間 savings 為 null（停電、無基準線）→ 整月 savings 為 null。
    # Sum 會略過 null，所以要另外數。
    null_savings = qs.filter(estimated_savings__isnull=True).exists()
    savings = None if null_savings else (sums["savings"] or 0.0)

    peak_at = None
    if sums["peak"] is not None:
        row = qs.annotate(demand_kw=demand).order_by("-demand_kw", "interval_start").values_list("interval_start", flat=True).first()
        peak_at = row

    # 涵蓋率：月內秒數 ÷ 月長度（考慮遙測涵蓋率）。
    total_seconds = (end - start).total_seconds()
    covered = qs.aggregate(c=Sum(F("interval_seconds") * F("coverage"), output_field=FloatField()))["c"] or 0.0
    coverage = min(covered / total_seconds, 1.0) if total_seconds > 0 else 0.0
    # basis 取月內最差：任何一個區間涵蓋率低就是估計；整月不到一半就是未知。
    min_cov = qs.order_by("coverage").values_list("coverage", flat=True).first() or 0.0
    if coverage < UNKNOWN_COVERAGE:
        basis = SettlementBasis.UNKNOWN
    elif min_cov < ESTIMATED_COVERAGE or coverage < 1.0 - 1e-6:
        basis = SettlementBasis.ESTIMATED
    else:
        basis = SettlementBasis.MEASURED
    return _Figures(
        sums["cost"] or 0.0, sums["revenue"] or 0.0, savings, sums["peak"], peak_at,
        sums["baseline_peak"], count, coverage, basis,
    )


def settle(site, month: dt.date, *, force: bool = False) -> MonthlySettlement:
    """結算 ``site`` 的 ``month``。已封存且未 ``force`` 時原樣回傳。"""
    existing = MonthlySettlement.objects.filter(site=site, billing_month=month).first()
    if existing is not None and existing.finalized_at is not None and not force:
        return existing

    start, end = month_bounds(site, month)
    plan, _source = effective_plan(site)
    tariff = plan.tariff if plan else None
    rate = float(tariff.demand_charge_per_kw) if tariff else 0.0
    contract = float(plan.contract_capacity_kw) if plan and plan.contract_capacity_kw else None
    currency = tariff.currency if tariff else site.organization.reporting_currency

    baseline_kind = plan.savings_baseline if plan else SavingsBaseline.NONE
    fig = _figures(site, start, end, baseline_kind=baseline_kind)
    peak = max(fig.peak_kw, 0.0) if fig.peak_kw is not None else None
    demand_charge = peak * rate if peak is not None else 0.0
    penalty = excess_charge(peak, contract or 0.0, rate) if peak is not None and contract else 0.0
    total = fig.energy_charge + demand_charge + penalty - fig.export_revenue

    baseline_total = None
    savings = None
    if baseline_kind != SavingsBaseline.NONE and fig.savings_energy is not None and fig.interval_count:
        baseline_energy = fig.energy_charge + fig.savings_energy
        baseline_peak = max(fig.baseline_peak_kw, 0.0) if fig.baseline_peak_kw is not None else peak
        baseline_demand = (baseline_peak or 0.0) * rate
        baseline_penalty = excess_charge(baseline_peak or 0.0, contract or 0.0, rate) if contract else 0.0
        baseline_total = baseline_energy + baseline_demand + baseline_penalty - fig.export_revenue
        savings = baseline_total - total

    fields = {
        "organization": site.organization,
        "period_start": start, "period_end": end, "currency": currency,
        "tariff_snapshot": _snapshot_tariff(plan),
        "cost_parameters_snapshot": _snapshot_cost_parameters(site),
        "peak_demand_kw": peak, "peak_occurred_at": fig.peak_at,
        "baseline_peak_kw": fig.baseline_peak_kw, "contract_capacity_kw": contract,
        "energy_charge": fig.energy_charge, "demand_charge": demand_charge,
        "excess_penalty": penalty, "export_revenue": fig.export_revenue, "total": total,
        "baseline_total": baseline_total, "savings": savings,
        "basis": fig.basis, "interval_count": fig.interval_count, "coverage": fig.coverage,
    }
    if existing is None:
        return MonthlySettlement.objects.create(site=site, billing_month=month, **fields)
    for key, value in fields.items():
        setattr(existing, key, value)
    existing.save()
    return existing


def finalize_if_due(settlement: MonthlySettlement, *, today: dt.date | None = None) -> bool:
    """上個月在次月 ``FINALIZE_DAY`` 號（場域當地日期）起封存。回傳是否剛封存。"""
    if settlement.finalized_at is not None:
        return False
    local_today = today or now().astimezone(site_zone(settlement.site)).date()
    due = next_month(settlement.billing_month).replace(day=FINALIZE_DAY)
    if local_today >= due:
        settlement.finalized_at = now()
        settlement.save(update_fields=["finalized_at", "updated_at"])
        return True
    return False


def months_to_settle(site, *, today: dt.date | None = None) -> list[dt.date]:
    """排程器每天要跑的：當月與上個月（場域當地）。"""
    local_today = today or now().astimezone(site_zone(site)).date()
    this_month = local_today.replace(day=1)
    previous = (this_month - dt.timedelta(days=1)).replace(day=1)
    return [previous, this_month]
