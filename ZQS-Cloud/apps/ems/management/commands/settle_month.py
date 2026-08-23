"""月結算。冪等；封存的月份跳過，除非 --force。

    manage.py settle_month                    # 每個場域的當月與上個月（排程器每天跑）
    manage.py settle_month --month 2026-07    # 指定月份
    manage.py settle_month --month 2026-07 --force   # 重算已封存的月份（要有理由）
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.devices.models import Site
from apps.ems.settlement import finalize_if_due, months_to_settle, parse_month, settle


class Command(BaseCommand):
    help = "Settle a billing month per site: peak demand, demand charge, penalty, totals, snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="", help="YYYY-MM; blank = current and previous month.")
        parser.add_argument("--site", default="", help="Site UUID; blank = every active site.")
        parser.add_argument("--organization", default="", help="Organization slug; blank = all.")
        parser.add_argument("--force", action="store_true", help="Recompute finalized months too.")
        parser.add_argument("--no-finalize", action="store_true", help="Never stamp finalized_at.")

    def handle(self, *args, **options):
        sites = Site.objects.filter(deleted_at__isnull=True, is_active=True).select_related("organization")
        if options["organization"]:
            sites = sites.filter(organization__slug=options["organization"])
        if options["site"]:
            try:
                sites = sites.filter(pk=uuid.UUID(options["site"]))
            except ValueError as exc:
                raise CommandError("--site must be a UUID") from exc
        explicit = parse_month(options["month"]) if options["month"] else None

        settled = finalized = 0
        for site in sites:
            months = [explicit] if explicit else months_to_settle(site)
            for month in months:
                row = settle(site, month, force=options["force"])
                settled += 1
                if not options["no_finalize"] and finalize_if_due(row):
                    finalized += 1
                self.stdout.write(
                    f"{site.name} {month:%Y-%m}: total={row.total:,.0f} peak={row.peak_demand_kw or 0:.1f} kW "
                    f"savings={'-' if row.savings is None else f'{row.savings:,.0f}'} basis={row.basis}"
                    f"{' [finalized]' if row.finalized_at else ''}"
                )
        self.stdout.write(self.style.SUCCESS(f"settled {settled} site-month(s), finalized {finalized}"))
