"""能源管理報表：把一段時間裡「場域用了多少、花了多少、省了多少、警報怎麼發生」
整理成一份可讀的結果。

這裡只算數字與寫結論；畫面由前端負責，PDF／Word 由 :mod:`apps.ems.report_export`
負責。三者共用同一個 dict，所以匯出的內容和螢幕上看到的一定一樣。

結論（``insights``）是規則產生的：每一條都對應一個可以查證的數字，並說出「所以
呢」——自發自用率低就建議儲能移轉、警報集中在某個時段就點名那個時段。沒有數
字支撐的話就不寫，寧可少一條也不要硬湊。
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from collections import Counter, defaultdict
from typing import Any

from django.db.models import Count, Sum
from django.db.models.functions import TruncDay

from apps.alerts.models import Alert, AlertStatus, Severity
from apps.devices.models import Device, Site, descendant_site_ids
from apps.ems import rollup
from apps.ems.demand import demand_benefit
from apps.ems.models import EnergyInterval
from apps.ems.plans import effective_plan_map

SEVERITIES = [str(Severity.CRITICAL.value), str(Severity.MAJOR.value), str(Severity.WARNING.value), str(Severity.INFO.value)]
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _zone(name: str) -> dt.tzinfo:
    try:
        return zoneinfo.ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 - a misconfigured site should still report
        return dt.timezone.utc


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 1)


def tree_order(rows: list[dict], *, id_key: str = "site_id", parent_key: str = "parent_id") -> list[dict]:
    """Parents first, each followed by its subtree; adds ``depth`` to every row.

    Every per-site listing in the platform is drawn as a tree (console tables,
    PDF, Word), so the ordering lives in one place. Rows whose parent is not in
    the list are roots: a scoped report still shows what it has.
    """
    known = {row[id_key] for row in rows}
    children: dict = {}
    for row in rows:
        parent = row.get(parent_key)
        children.setdefault(parent if parent in known else None, []).append(row)
    out: list[dict] = []

    def walk(parent, depth: int) -> None:
        for row in children.get(parent, []):
            row["depth"] = depth
            out.append(row)
            walk(row[id_key], depth + 1)

    walk(None, 0)
    return out


# ---------------------------------------------------------------------------
# 能源
# ---------------------------------------------------------------------------
def _site_rows(organization, sites: list[Site], start, end) -> list[dict]:
    ids = [site.pk for site in sites]
    costs = rollup.cost_by_site(ids, start, end)
    demand = rollup.demand_by_site(ids, start, end)
    plans = effective_plan_map(organization)
    currencies = rollup.currency_by_site(ids, default=organization.reporting_currency)
    energy = {
        row["site_id"]: row
        for row in EnergyInterval.objects.filter(
            site_id__in=ids, interval_start__gte=start, interval_start__lt=end
        )
        .values("site_id")
        .annotate(
            grid_import=Sum("grid_import_kwh"),
            grid_export=Sum("grid_export_kwh"),
            pv=Sum("pv_kwh"),
            load=Sum("load_kwh"),
            charge=Sum("battery_charge_kwh"),
            discharge=Sum("battery_discharge_kwh"),
            intervals=Count("id"),
        )
    }
    device_counts = {
        row["site_id"]: row["n"]
        for row in Device.objects.filter(site_id__in=ids, deleted_at__isnull=True)
        .values("site_id")
        .annotate(n=Count("id"))
    }

    rows = []
    for site in sites:
        e = energy.get(site.pk, {})
        c = costs.get(site.pk, {})
        plan = (plans.get(site.pk) or (None, None))[0]
        benefit = demand_benefit(
            peak_demand_kw=demand.get(site.pk, {}).get("peak_demand_kw"),
            baseline_peak_kw=demand.get(site.pk, {}).get("baseline_peak_kw"),
            contract_capacity_kw=plan.contract_capacity_kw if plan else None,
            demand_charge_per_kw=(plan.tariff.demand_charge_per_kw if plan and plan.tariff else None),
        ).as_dict()
        pv = e.get("pv") or 0.0
        load = e.get("load") or 0.0
        grid_import = e.get("grid_import") or 0.0
        grid_export = e.get("grid_export") or 0.0
        charge = e.get("charge") or 0.0
        discharge = e.get("discharge") or 0.0
        rows.append(
            {
                "site_id": site.pk,
                "site_name": site.name,
                "parent_id": site.parent_id,
                "timezone_name": site.timezone_name,
                "device_count": device_counts.get(site.pk, 0),
                "interval_count": e.get("intervals", 0),
                "load_kwh": round(load, 1),
                "pv_kwh": round(pv, 1),
                "grid_import_kwh": round(grid_import, 1),
                "grid_export_kwh": round(grid_export, 1),
                "battery_charge_kwh": round(charge, 1),
                "battery_discharge_kwh": round(discharge, 1),
                "self_consumption_ratio": _pct(rollup._ratio(pv - grid_export, pv)),
                "self_sufficiency_ratio": _pct(rollup._ratio(load - grid_import, load)),
                "energy_cost": round(c.get("energy_cost", 0.0), 2),
                "export_revenue": round(c.get("export_revenue", 0.0), 2),
                "estimated_savings": round(c.get("estimated_savings", 0.0), 2),
                "currency": currencies.get(site.pk, ""),
                "peak_demand_kw": benefit.get("peak_demand_kw"),
                "baseline_peak_kw": benefit.get("baseline_peak_kw"),
                "contract_capacity_kw": benefit.get("contract_capacity_kw"),
                "demand_savings": round(benefit.get("demand_savings", 0.0) or 0.0, 2),
                "penalty_avoided": round(benefit.get("penalty_avoided", 0.0) or 0.0, 2),
                "over_contract": bool(
                    benefit.get("contract_capacity_kw")
                    and benefit.get("peak_demand_kw")
                    and benefit["peak_demand_kw"] > benefit["contract_capacity_kw"]
                ),
            }
        )
    return tree_order(rows)


def _daily_series(site_ids, start, end, zone: dt.tzinfo) -> list[dict]:
    """每日的用電／產電／購電／售電／電費，以報表時區切日。"""
    rows = (
        EnergyInterval.objects.filter(
            site_id__in=site_ids, interval_start__gte=start, interval_start__lt=end
        )
        .annotate(day=TruncDay("interval_start", tzinfo=zone))
        .values("day")
        .annotate(
            load=Sum("load_kwh"),
            pv=Sum("pv_kwh"),
            grid_import=Sum("grid_import_kwh"),
            grid_export=Sum("grid_export_kwh"),
            discharge=Sum("battery_discharge_kwh"),
            cost=Sum("energy_cost"),
            savings=Sum("estimated_savings"),
        )
        .order_by("day")
    )
    return [
        {
            "day": row["day"].astimezone(zone).date().isoformat(),
            "load_kwh": round(row["load"] or 0.0, 1),
            "pv_kwh": round(row["pv"] or 0.0, 1),
            "grid_import_kwh": round(row["grid_import"] or 0.0, 1),
            "grid_export_kwh": round(row["grid_export"] or 0.0, 1),
            "battery_discharge_kwh": round(row["discharge"] or 0.0, 1),
            "energy_cost": round(row["cost"] or 0.0, 2),
            "estimated_savings": round(row["savings"] or 0.0, 2),
        }
        for row in rows
    ]


def _hourly_load_profile(site_ids, start, end, zone: dt.tzinfo) -> list[dict]:
    """一天 24 小時的平均負載（kW），看尖峰落在哪裡。"""
    per_hour = 3600.0
    rows = (
        EnergyInterval.objects.filter(
            site_id__in=site_ids, interval_start__gte=start, interval_start__lt=end
        )
        .values("interval_start", "interval_seconds")
        .annotate(load=Sum("load_kwh"), grid_import=Sum("grid_import_kwh"))
    )
    load_by_hour: dict[int, list[float]] = defaultdict(list)
    import_by_hour: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        hour = row["interval_start"].astimezone(zone).hour
        seconds = row["interval_seconds"] or 900
        load_by_hour[hour].append((row["load"] or 0.0) * per_hour / seconds)
        import_by_hour[hour].append((row["grid_import"] or 0.0) * per_hour / seconds)
    return [
        {
            "hour": hour,
            "avg_load_kw": round(sum(load_by_hour[hour]) / len(load_by_hour[hour]), 1) if load_by_hour[hour] else 0.0,
            "avg_import_kw": round(sum(import_by_hour[hour]) / len(import_by_hour[hour]), 1) if import_by_hour[hour] else 0.0,
        }
        for hour in range(24)
    ]


# ---------------------------------------------------------------------------
# 警報
# ---------------------------------------------------------------------------
def _alert_stats(organization, site_ids, start, end, zone: dt.tzinfo, parent_of: dict | None = None) -> dict:
    """區間內「開始」的警報：數量、嚴重度、狀態、時段分佈、處理時間、常客。"""
    alerts = list(
        Alert.objects.filter(
            organization=organization,
            device__site_id__in=site_ids,
            started_at__gte=start,
            started_at__lt=end,
        )
        .select_related("device", "device__site")
        .values(
            "id", "severity", "status", "code", "title", "started_at", "resolved_at",
            "acknowledged_at", "occurrence_count", "device__name", "device__device_id",
            "device__site_id", "device__site__name",
        )
    )
    by_severity = Counter(a["severity"] for a in alerts)
    by_status = Counter(a["status"] for a in alerts)
    by_hour = [0] * 24
    by_weekday = [0] * 7
    resolve_minutes: list[float] = []
    ack_minutes: list[float] = []
    by_site: dict[Any, dict] = {}
    by_title: dict[str, dict] = {}
    by_device: dict[str, dict] = {}
    for a in alerts:
        local = a["started_at"].astimezone(zone)
        by_hour[local.hour] += 1
        by_weekday[local.weekday()] += 1
        if a["resolved_at"]:
            resolve_minutes.append((a["resolved_at"] - a["started_at"]).total_seconds() / 60)
        if a["acknowledged_at"]:
            ack_minutes.append((a["acknowledged_at"] - a["started_at"]).total_seconds() / 60)
        site_entry = by_site.setdefault(
            a["device__site_id"],
            {"site_id": a["device__site_id"], "site_name": a["device__site__name"] or "",
             "parent_id": (parent_of or {}).get(a["device__site_id"]), "total": 0,
             "critical": 0, "major": 0, "warning": 0, "info": 0, "open": 0},
        )
        site_entry["total"] += 1
        site_entry[a["severity"]] = site_entry.get(a["severity"], 0) + 1
        if a["status"] != AlertStatus.RESOLVED:
            site_entry["open"] += 1
        key = a["code"] or a["title"]
        title_entry = by_title.setdefault(key, {"code": a["code"], "title": a["title"], "count": 0, "occurrences": 0, "severity": a["severity"]})
        title_entry["count"] += 1
        title_entry["occurrences"] += a["occurrence_count"] or 1
        device_key = a["device__device_id"] or "?"
        device_entry = by_device.setdefault(device_key, {"device_id": device_key, "device_name": a["device__name"] or device_key, "site_name": a["device__site__name"] or "", "count": 0})
        device_entry["count"] += 1

    total = len(alerts)
    span_hours = max(1.0, (end - start).total_seconds() / 3600)
    hour_peak = max(range(24), key=lambda h: by_hour[h]) if total else None
    weekday_peak = max(range(7), key=lambda d: by_weekday[d]) if total else None

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        return round(ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2, 1)

    return {
        "total": total,
        "per_day": round(total / (span_hours / 24), 2),
        "by_severity": {level: by_severity.get(level, 0) for level in SEVERITIES},
        "by_status": {str(status): by_status.get(status, 0) for status in AlertStatus.values},
        "open": total - by_status.get(AlertStatus.RESOLVED, 0),
        "resolved": by_status.get(AlertStatus.RESOLVED, 0),
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "peak_hour": hour_peak,
        "peak_hour_share": round(by_hour[hour_peak] / total * 100, 1) if total else None,
        "peak_weekday": WEEKDAY_KEYS[weekday_peak] if weekday_peak is not None else None,
        "mean_minutes_to_resolve": round(sum(resolve_minutes) / len(resolve_minutes), 1) if resolve_minutes else None,
        "median_minutes_to_resolve": _median(resolve_minutes),
        "mean_minutes_to_acknowledge": round(sum(ack_minutes) / len(ack_minutes), 1) if ack_minutes else None,
        "by_site": tree_order(sorted(by_site.values(), key=lambda row: -row["total"])),
        "top_titles": sorted(by_title.values(), key=lambda row: -row["count"])[:8],
        "top_devices": sorted(by_device.values(), key=lambda row: -row["count"])[:8],
    }


# ---------------------------------------------------------------------------
# 結論
# ---------------------------------------------------------------------------
def _insights(totals: dict, sites: list[dict], alerts: dict, hourly: list[dict], currency: str) -> list[dict]:
    out: list[dict] = []

    def add(level: str, text: str) -> None:
        out.append({"level": level, "text": text})

    load = totals["load_kwh"]
    pv = totals["pv_kwh"]
    if load <= 0 and pv <= 0:
        add("info", "這段期間沒有任何能源區間資料：請確認設備有回報、記錄策略有開啟，或縮短區間。")
        return out

    def money(value: float) -> str:
        return f"{currency} {value:,.0f}" if currency else f"{value:,.0f}"

    add("info", f"期間總用電 {load:,.0f} kWh，其中購電 {totals['grid_import_kwh']:,.0f} kWh、自發電 {pv:,.0f} kWh；電費 {money(totals['energy_cost'])}。")

    ssr = totals.get("self_sufficiency_ratio")
    scr = totals.get("self_consumption_ratio")
    if pv > 0 and ssr is not None:
        if ssr >= 50:
            add("ok", f"自給率 {ssr:.0f}%：一半以上的用電來自自發電，購電依賴度低。")
        elif ssr >= 20:
            add("info", f"自給率 {ssr:.0f}%：自發電覆蓋約五分之一到一半的用電。")
        else:
            add("warning", f"自給率只有 {ssr:.0f}%：用電主要仍靠購電，若要降低電費，優先檢視尖峰時段的負載。")
    if pv > 0 and scr is not None and scr < 70:
        add("warning", f"自發自用率 {scr:.0f}%：有 {100 - scr:.0f}% 的自發電逆送回電網，售電價通常低於購電價；可考慮用儲能把這部分移到尖峰時段使用。")
    elif pv > 0 and scr is not None:
        add("ok", f"自發自用率 {scr:.0f}%：自發電幾乎都被自己用掉。")

    savings = totals["estimated_savings"]
    if savings > 0:
        add("ok", f"儲能調度相對基準線估計節省 {money(savings)}（電量面）；需量面另省 {money(totals['demand_savings'])}。")
    elif savings < 0:
        add("critical", f"儲能調度相對基準線反而多花 {money(-savings)}：請檢查儲能規劃的策略與電價時段是否對得上。")

    over = [row for row in sites if row["over_contract"]]
    if over:
        names = "、".join(row["site_name"] for row in over[:3])
        add("critical", f"{len(over)} 個場域最高需量超過契約容量（{names}）：超約部分依台電規定以 2～3 倍計費，建議調整削峰目標或提高契約容量。")
    else:
        near = [row for row in sites if row["contract_capacity_kw"] and row["peak_demand_kw"] and row["peak_demand_kw"] > 0.9 * row["contract_capacity_kw"]]
        if near:
            add("warning", f"{len(near)} 個場域最高需量已達契約容量 90% 以上（{'、'.join(r['site_name'] for r in near[:3])}），接近超約邊緣。")

    if hourly:
        peak = max(hourly, key=lambda row: row["avg_load_kw"])
        trough = min(hourly, key=lambda row: row["avg_load_kw"])
        if peak["avg_load_kw"] > 0:
            add("info", f"平均負載最高在 {peak['hour']:02d}:00（{peak['avg_load_kw']:,.0f} kW），最低在 {trough['hour']:02d}:00（{trough['avg_load_kw']:,.0f} kW）；儲能放電應集中在前者附近。")

    rte = totals.get("round_trip_efficiency")
    if rte is not None and rte < 80:
        add("warning", f"電池來回效率 {rte:.0f}%：低於常見的 85–90%，建議檢查電池健康度或充放電策略中的小電流充放。")

    total_alerts = alerts["total"]
    if total_alerts == 0:
        add("ok", "期間沒有任何警報。")
    else:
        crit = alerts["by_severity"].get("critical", 0)
        add("critical" if crit else "info", f"期間共 {total_alerts} 則警報（每日 {alerts['per_day']:.1f} 則），其中嚴重 {crit}、重大 {alerts['by_severity'].get('major', 0)}；尚有 {alerts['open']} 則未結案。")
        if alerts["peak_hour"] is not None and (alerts["peak_hour_share"] or 0) >= 20:
            add("warning", f"警報集中在 {alerts['peak_hour']:02d}:00 前後（佔 {alerts['peak_hour_share']:.0f}%），與該時段的負載或排程作業有關的可能性高。")
        if alerts["top_titles"]:
            top = alerts["top_titles"][0]
            if top["count"] >= max(3, total_alerts * 0.3):
                add("warning", f"「{top['title']}」重複發生 {top['count']} 次，是最常見的警報；反覆發生的同一問題通常值得從根因處理而不是逐次結案。")
        mttr = alerts["median_minutes_to_resolve"]
        if mttr is not None:
            if mttr > 240:
                add("warning", f"警報結案中位數 {mttr / 60:.1f} 小時，處理偏慢。")
            else:
                add("ok", f"警報結案中位數 {mttr:.0f} 分鐘。")
    return out


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def build_report(ctx, *, start: dt.datetime, end: dt.datetime, site_id=None, include_descendants: bool = True) -> dict:
    organization = ctx.organization
    sites_qs = ctx.scope_queryset(
        Site.objects.filter(organization=organization, deleted_at__isnull=True, is_active=True).order_by("name"),
        field="id",
    )
    scope_name = ""
    if site_id is not None:
        root = sites_qs.filter(pk=site_id).first()
        if root is None:
            from apps.core.errors import NotFound

            raise NotFound("Site not found")
        scope_name = root.name
        ids = descendant_site_ids([root.pk], organization=organization) if include_descendants else [root.pk]
        sites_qs = sites_qs.filter(pk__in=ids)
    sites = list(sites_qs)
    site_ids = [site.pk for site in sites]

    zone_name = sites[0].timezone_name if len({s.timezone_name for s in sites}) == 1 and sites else "Asia/Taipei"
    zone = _zone(zone_name)

    rows = _site_rows(organization, sites, start, end)
    totals = rollup.energy_totals(site_ids, start, end, default_currency=organization.reporting_currency) if site_ids else {
        "grid_import_kwh": 0.0, "grid_export_kwh": 0.0, "pv_kwh": 0.0, "load_kwh": 0.0,
        "battery_charge_kwh": 0.0, "battery_discharge_kwh": 0.0, "peak_import_kw": None, "peak_load_kw": None,
        "peak_basis": "measured", "energy_cost": 0.0, "export_revenue": 0.0, "estimated_savings": 0.0,
        "self_consumption_ratio": None, "self_sufficiency_ratio": None, "round_trip_efficiency": None, "currency": "",
    }
    totals = {
        **totals,
        "self_consumption_ratio": _pct(totals.get("self_consumption_ratio")),
        "self_sufficiency_ratio": _pct(totals.get("self_sufficiency_ratio")),
        "round_trip_efficiency": _pct(totals.get("round_trip_efficiency")),
        "demand_savings": round(sum(row["demand_savings"] for row in rows), 2),
        "penalty_avoided": round(sum(row["penalty_avoided"] for row in rows), 2),
        "net_cost": round(totals["energy_cost"] - totals["export_revenue"], 2),
    }
    currencies = {row["currency"] for row in rows if row["currency"]}
    currency = currencies.pop() if len(currencies) == 1 else ""
    daily = _daily_series(site_ids, start, end, zone) if site_ids else []
    hourly = _hourly_load_profile(site_ids, start, end, zone) if site_ids else []
    alerts = _alert_stats(organization, site_ids, start, end, zone, parent_of={s.pk: s.parent_id for s in sites})

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc),
        "organization_name": organization.name,
        "scope_name": scope_name,
        "start": start,
        "end": end,
        "timezone_name": zone_name,
        "currency": currency,
        "mixed_currency": len(currencies) > 1,
        "site_count": len(sites),
        "device_count": sum(row["device_count"] for row in rows),
        "totals": totals,
        "sites": rows,
        "daily": daily,
        "hourly_load": hourly,
        "alerts": alerts,
        "insights": _insights(totals, rows, alerts, hourly, currency),
    }

