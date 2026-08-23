r"""Cross-check the platform's numbers against each other on a running stack.

Every figure a customer is shown is derived from the same interval table
more than one way; they must agree. This script pulls each view through the
public API and checks the arithmetic:

* cost overview totals = sum of the site rows;
* demand-charge benefit reproduces from peaks, contract and tariff rate;
* a site's summary over a window = sum of its intervals in that window;
* the fleet live "today" figures = sum of the per-site today figures;
* a site's live power flow balances (grid = load - pv - battery);
* each interval's cost and savings reproduce from its kWh and prices.

    .venv\Scripts\python.exe scripts\verify_calculations.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
EMAIL, PASSWORD = "admin@example.com", "ChangeMe-2026!"

failures: list[str] = []
checks = 0


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def close(label, a, b, tol=0.02, abs_tol=0.05):
    """Relative tolerance for the rounding the API applies on each row."""
    global checks
    checks += 1
    a = a or 0.0
    b = b or 0.0
    if abs(a - b) <= max(abs_tol, tol * max(abs(a), abs(b))):
        return True
    failures.append(f"{label}: {a} != {b}")
    return False


def excess(peak, contract, rate):
    if not contract or rate <= 0:
        return 0.0
    over = max(peak - contract, 0.0)
    band = contract * 0.10
    return min(over, band) * rate * 2 + max(over - band, 0.0) * rate * 3


def main() -> int:
    token = call("POST", "/api/auth/login", body={"email": EMAIL, "password": PASSWORD})["access_token"]
    end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    start = end - dt.timedelta(days=7)
    window = f"start={start.isoformat().replace('+00:00', 'Z')}&end={end.isoformat().replace('+00:00', 'Z')}"

    # ---- cost overview -----------------------------------------------------
    overview = call("GET", f"/api/ems/cost-overview?{window}", token)
    rows = overview["sites"]
    close("overview total_energy_cost", overview["total_energy_cost"], sum(r["energy_cost"] for r in rows))
    close("overview total_export_revenue", overview["total_export_revenue"], sum(r["export_revenue"] for r in rows))
    close("overview total_estimated_savings", overview["total_estimated_savings"], sum(r["estimated_savings"] for r in rows))
    close("overview total_demand_savings", overview["total_demand_savings"], sum(r["demand_savings"] for r in rows))

    tariffs = {t["id"]: t for t in call("GET", "/api/ems/tariffs", token)}
    sites = {s["id"]: s for s in call("GET", "/api/sites?limit=200", token)["items"]}

    for row in rows:
        sid = row["site_id"]
        label = row["site_name"]
        # Demand benefit reproduces from the effective plan's tariff.
        try:
            plan = call("GET", f"/api/ems/sites/{sid}/plan", token)
        except urllib.error.HTTPError:
            plan = None
        if plan and row["baseline_peak_kw"] is not None:
            tariff = tariffs.get(plan.get("tariff_id") or "")
            rate = (tariff or {}).get("demand_charge_per_kw") or 0.0
            contract = plan.get("contract_capacity_kw")
            close(f"{label} contract", row["contract_capacity_kw"] or 0, contract or 0)
            close(f"{label} rate", row["demand_charge_per_kw"], rate)
            if rate > 0:
                base = max(row["baseline_peak_kw"], 0.0)
                peak = max(row["peak_demand_kw"], 0.0)
                penalty = excess(base, contract, rate) - excess(peak, contract, rate)
                expected = (base - peak) * rate + penalty
                close(f"{label} demand_savings", row["demand_savings"], expected, tol=0.01, abs_tol=rate * 0.2)
                close(f"{label} penalty_avoided", row["penalty_avoided"], penalty, tol=0.01, abs_tol=rate * 0.2)
            else:
                close(f"{label} demand_savings (no rate)", row["demand_savings"], 0.0)

        # Summary over the window equals the sum of its intervals.
        summary = call("GET", f"/api/ems/sites/{sid}/summary?{window}&include_descendants=false", token)
        intervals = call("GET", f"/api/ems/sites/{sid}/intervals?{window}&limit=5000", token)
        if intervals:
            for key in ("grid_import_kwh", "grid_export_kwh", "pv_kwh", "load_kwh",
                        "battery_charge_kwh", "battery_discharge_kwh", "energy_cost",
                        "export_revenue"):
                close(f"{label} summary.{key}", summary.get(key), sum(i[key] or 0 for i in intervals))
            close(f"{label} summary.estimated_savings", summary.get("estimated_savings"),
                  sum(i["estimated_savings"] or 0 for i in intervals))
            pv = summary.get("pv_kwh") or 0
            load = summary.get("load_kwh") or 0
            if pv > 0 and summary.get("self_consumption_ratio") is not None:
                close(f"{label} self_consumption_ratio", summary["self_consumption_ratio"],
                      (pv - (summary.get("grid_export_kwh") or 0)) / pv, tol=0.005, abs_tol=0.002)
            if load > 0 and summary.get("self_sufficiency_ratio") is not None:
                close(f"{label} self_sufficiency_ratio", summary["self_sufficiency_ratio"],
                      (load - (summary.get("grid_import_kwh") or 0)) / load, tol=0.005, abs_tol=0.002)
            close(f"{label} summary.peak_import_kw", summary.get("peak_import_kw"),
                  max(i["peak_import_kw"] or 0 for i in intervals), tol=0.005)
            close(f"{label} overview.energy_cost vs summary", row["energy_cost"], summary.get("energy_cost"))
            close(f"{label} overview.grid_import vs summary", row["grid_import_kwh"], summary.get("grid_import_kwh"))
            # Peaks reproduce from the intervals.
            peak = max(i["grid_import_kwh"] * 3600 / i["interval_seconds"] for i in intervals)
            base = max((i["load_kwh"] - i["pv_kwh"]) * 3600 / i["interval_seconds"] for i in intervals)
            close(f"{label} peak_demand_kw", row["peak_demand_kw"], peak, tol=0.005)
            close(f"{label} baseline_peak_kw", row["baseline_peak_kw"], base, tol=0.005)
            # Each interval prices itself consistently.
            for i in intervals[:400]:
                close(f"{label} interval {i['interval_start']} energy_cost",
                      i["energy_cost"], i["grid_import_kwh"] * i["import_price"], tol=0.001, abs_tol=0.01)
                # export_price is not exposed; derive it from the row itself.
                export_price = (i["export_revenue"] / i["grid_export_kwh"]) if i["grid_export_kwh"] else 0.0
                if i["estimated_savings"] is not None and i.get("generator_kwh", 0) == 0:
                    baseline_net = i["load_kwh"] - i["pv_kwh"]
                    baseline_cost = max(baseline_net, 0) * i["import_price"] - max(-baseline_net, 0) * export_price
                    actual = i["energy_cost"] - i["export_revenue"]
                    close(f"{label} interval {i['interval_start']} savings",
                          i["estimated_savings"], baseline_cost - actual, tol=0.001, abs_tol=0.02)

        # Investment: totals are sums of the rows; the window share is pro rata.
        inv = call("GET", f"/api/ems/sites/{sid}/investment?{window}", token)
        close(f"{label} investment capital", inv["total_capital_cost"],
              sum(d["capital_cost"] or 0 for d in inv["devices"]))
        close(f"{label} investment annual", inv["total_annual_cost"],
              sum(d["annual_cost"] or 0 for d in inv["devices"]))
        years = (end - start).total_seconds() / (365.25 * 24 * 3600)
        close(f"{label} investment window share", inv["window_amortised_cost"], inv["total_annual_cost"] * years)
        for d in inv["devices"]:
            if d["capital_cost"] and d["expected_life_years"] and d["annual_cost"] is not None:
                # annual = capital / life + maintenance; maintenance is not exposed, so
                # the check is a lower bound.
                global checks
                checks += 1
                if d["annual_cost"] + 0.01 < d["capital_cost"] / d["expected_life_years"]:
                    failures.append(f"{label} {d['device_external_id']} annual_cost below straight-line")

        # Live flow balances.
        site_overview = call("GET", f"/api/ems/sites/{sid}/overview", token)
        flow = site_overview["flow"]
        if flow["grid_kw"] is not None and flow["load_kw"] is not None and not flow["is_stale"]:
            expected_grid = flow["load_kw"] - (flow["pv_kw"] or 0) - (flow["battery_kw"] or 0)
            close(f"{label} live flow balance", flow["grid_kw"], expected_grid, tol=0.03, abs_tol=5.0)

    # ---- fleet live today = sum of sites ---------------------------------
    live = call("GET", "/api/ems/live", token)
    close("live today_energy_cost", live["today_energy_cost"], sum(s["today_energy_cost"] or 0 for s in live["sites"]))
    close("live today_estimated_savings", live["today_estimated_savings"],
          sum((s["today_estimated_savings"] or 0) for s in live["sites"]))
    close("live today_load_kwh", live["today_load_kwh"], sum(s["today_load_kwh"] or 0 for s in live["sites"]))
    for key in ("grid_kw", "pv_kw", "load_kw", "battery_kw"):
        close(f"live totals.{key}", live["totals"][key],
              sum((s["flow"][key] or 0) for s in live["sites"] if not s["is_stale"]), abs_tol=1.0)
    close("live site_count", live["site_count"], sum(1 for s in live["sites"] if s["device_count"] > 0), tol=0, abs_tol=0)
    close("live reporting_site_count", live["reporting_site_count"], sum(1 for s in live["sites"] if not s["is_stale"]), tol=0, abs_tol=0)

    # ---- parent site summary = sum of its subtree ---------------------------
    for site in sites.values():
        if site["child_count"] > 0:
            whole = call("GET", f"/api/ems/sites/{site['id']}/summary?{window}&include_descendants=true", token)
            parts = [s for s in sites.values() if s["parent_id"] == site["id"]] + [site]
            total_cost = 0.0
            for part in parts:
                own = call("GET", f"/api/ems/sites/{part['id']}/summary?{window}&include_descendants=false", token)
                total_cost += own.get("energy_cost") or 0
            close(f"{site['name']} subtree energy_cost", whole.get("energy_cost"), total_cost)

    # ---- monthly settlements (W4) ------------------------------------------
    # The settlement must equal the cost-overview over the same local-month
    # window: same interval rows, same demand-charge arithmetic. A finalized
    # month is frozen, so only open months are compared against live figures.
    for site in sites.values():
        try:
            settlements = call("GET", f"/api/ems/sites/{site['id']}/settlements?months=3", token)
        except urllib.error.HTTPError:
            continue
        for row in settlements:
            if row["finalized_at"] or row["interval_count"] == 0:
                continue
            label = f"{site['name']} {row['billing_month'][:7]}"
            mwin = f"start={row['period_start'].replace('+00:00', 'Z')}&end={row['period_end'].replace('+00:00', 'Z')}"
            month_overview = call("GET", f"/api/ems/cost-overview?{mwin}&include_inactive=true", token)
            match = next((r for r in month_overview["sites"] if r["site_id"] == site["id"]), None)
            if match is None:
                continue
            close(f"{label} settlement.energy_charge", row["energy_charge"], match["energy_cost"])
            close(f"{label} settlement.export_revenue", row["export_revenue"], match["export_revenue"])
            if match["peak_demand_kw"] is not None:
                close(f"{label} settlement.peak_demand_kw", row["peak_demand_kw"], max(match["peak_demand_kw"], 0.0), tol=0.001)
            rate = row["tariff_snapshot"].get("tariff", {}).get("demand_charge_per_kw") or 0.0
            peak = row["peak_demand_kw"] or 0.0
            contract = row["contract_capacity_kw"] or 0.0
            close(f"{label} settlement.demand_charge", row["demand_charge"], peak * rate)
            close(f"{label} settlement.excess_penalty", row["excess_penalty"], excess(peak, contract, rate) if contract else 0.0)
            close(
                f"{label} settlement.total", row["total"],
                row["energy_charge"] + row["demand_charge"] + row["excess_penalty"] - row["export_revenue"],
            )
            if row["savings"] is not None:
                close(f"{label} settlement.savings", row["savings"], row["baseline_total"] - row["total"])

    print(f"{checks} checks, {len(failures)} failure(s)")
    for line in failures[:40]:
        print("  FAIL", line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
