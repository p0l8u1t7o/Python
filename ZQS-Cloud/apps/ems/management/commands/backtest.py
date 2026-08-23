"""離線回測一個場域的儲能方案。只讀不寫。

    manage.py backtest --site "新竹園區 A 棟廠房" --days 30
    manage.py backtest --site <uuid> --plan "契約容量管理" --days 30 --compare
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now

from apps.devices.models import Site
from apps.ems.backtest import backtest_with_baseline, compare_strategies
from apps.ems.models import DispatchStrategy, StoragePlan
from apps.ems.plans import effective_plan


class Command(BaseCommand):
    help = "Replay a storage plan over historical load/PV and report what it would have cost."

    def add_arguments(self, parser):
        parser.add_argument("--site", required=True, help="Site name or UUID.")
        parser.add_argument("--plan", default="", help="Plan name or UUID; blank = the site's effective plan.")
        parser.add_argument("--days", type=int, default=30, help="Lookback in days (default 30).")
        parser.add_argument(
            "--strategy", default="",
            help="Override the plan's strategy; comma-separated keys stack them (W5), e.g. demand_cap,tou_arbitrage.",
        )
        parser.add_argument("--compare", action="store_true", help="Run every strategy and rank by total cost.")
        parser.add_argument("--soc", type=float, default=50.0, help="Initial SOC percent (default 50).")
        parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")

    def handle(self, *args, **options):
        site = self._site(options["site"])
        plan = self._plan(site, options["plan"])
        end = now().replace(second=0, microsecond=0)
        end -= dt.timedelta(minutes=end.minute % 15)
        start = end - dt.timedelta(days=max(int(options["days"]), 1))

        if options["compare"]:
            results = compare_strategies(site, plan, start, end)
            if options["json"]:
                self.stdout.write(json.dumps([r.summary() for r in results], ensure_ascii=False, indent=2))
                return
            self.stdout.write(f"site={site.name} plan={plan.name} range={start:%Y-%m-%d}..{end:%Y-%m-%d}")
            self.stdout.write(
                f"{'strategy':36} {'energy':>12} {'demand':>10} {'penalty':>10} {'cycle':>10} {'total':>12} "
                f"{'savings':>12} {'peak kW':>9} {'cycles':>7}"
            )
            for r in results:
                s = r.summary()
                self.stdout.write(
                    f"{s['strategy']:36} {s['energy_cost']:>12,.0f} {s['demand_charge']:>10,.0f} "
                    f"{s['penalty']:>10,.0f} {s['cycle_cost']:>10,.0f} {s['total']:>12,.0f} "
                    f"{(s['savings'] or 0):>12,.0f} {(s['peak_demand_kw'] or 0):>9,.1f} {s['equivalent_cycles']:>7.1f}"
                )
            self.stdout.write(f"baseline (no battery) total: {results[0].baseline_total:,.0f}")
            for note in results[0].notes:
                self.stdout.write(f"  note: {note}")
            return

        strategy = [k.strip() for k in options["strategy"].split(",") if k.strip()] or None
        for key in strategy or []:
            if key not in DispatchStrategy.values:
                raise CommandError(f"unknown strategy {key!r}; choose from {', '.join(DispatchStrategy.values)}")
        result = backtest_with_baseline(
            site, plan, start, end, strategy=strategy, initial_soc_percent=options["soc"], keep_intervals=False
        )
        if options["json"]:
            self.stdout.write(json.dumps(result.summary(), ensure_ascii=False, indent=2))
            return
        s = result.summary()
        self.stdout.write(f"site={site.name} plan={plan.name} strategy={s['strategy']} range={start:%Y-%m-%d}..{end:%Y-%m-%d}")
        for key in (
            "energy_cost", "demand_charge", "penalty", "cycle_cost", "stored_energy_adjustment",
            "total", "baseline_total", "savings",
        ):
            value = s[key]
            self.stdout.write(f"  {key:26} {'-' if value is None else f'{value:,.2f}':>14}")
        self.stdout.write(f"  {'peak_demand_kw':26} {s['peak_demand_kw']}")
        self.stdout.write(f"  {'cycles':26} {s['equivalent_cycles']}")
        self.stdout.write(f"  {'intervals':26} {s['intervals']}")
        for note in s["notes"]:
            self.stdout.write(f"  note: {note}")

    def _site(self, ref: str) -> Site:
        qs = Site.objects.filter(deleted_at__isnull=True)
        try:
            return qs.get(pk=uuid.UUID(ref))
        except (ValueError, Site.DoesNotExist):
            pass
        matches = list(qs.filter(name=ref)[:2])
        if not matches:
            raise CommandError(f"no site named {ref!r}")
        if len(matches) > 1:
            raise CommandError(f"site name {ref!r} is ambiguous; pass the UUID")
        return matches[0]

    def _plan(self, site: Site, ref: str) -> StoragePlan:
        if not ref:
            plan, _source = effective_plan(site)
            if plan is None:
                raise CommandError(f"site {site.name!r} has no effective storage plan; pass --plan")
            return plan
        qs = StoragePlan.objects.filter(organization=site.organization)
        try:
            return qs.get(pk=uuid.UUID(ref))
        except (ValueError, StoragePlan.DoesNotExist):
            pass
        try:
            return qs.get(name=ref)
        except StoragePlan.DoesNotExist as exc:
            raise CommandError(f"no plan named {ref!r} in {site.organization}") from exc
