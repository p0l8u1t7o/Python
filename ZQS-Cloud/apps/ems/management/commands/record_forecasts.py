"""為每個有能源資產的場域做一次未來 24 小時預測並記錄下來。

排程器每輪呼叫，但同一場域一小時內只記一次——誤差統計要的是「每個區間
最近一次預測」，每分鐘記一筆只會把表撐大，對準確度沒有幫助。
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.devices.models import Site
from apps.ems import forecast
from apps.ems.models import EnergyAsset, LoadForecast

MIN_GAP = dt.timedelta(minutes=55)


class Command(BaseCommand):
    help = "Record a 24 h load / PV forecast per site (at most once an hour)."

    def add_arguments(self, parser):
        parser.add_argument("--horizon-hours", type=int, default=24)
        parser.add_argument("--force", action="store_true", help="Ignore the one-per-hour gate.")

    def handle(self, *args, **options):
        now = timezone.now()
        site_ids = set(EnergyAsset.objects.filter(is_active=True).values_list("site_id", flat=True))
        recorded = 0
        for site in Site.objects.filter(pk__in=site_ids, deleted_at__isnull=True):
            last = (
                LoadForecast.objects.filter(site=site).order_by("-made_at")
                .values_list("made_at", flat=True).first()
            )
            if last is not None and now - last < MIN_GAP and not options["force"]:
                continue
            points = forecast.forecast_site(site.pk, now, options["horizon_hours"])
            known = sum(1 for p in points if p.confidence == "estimated")
            recorded += 1
            self.stdout.write(f"{site.code}: {known}/{len(points)} point(s) estimated")
        self.stdout.write(self.style.SUCCESS(f"recorded forecasts for {recorded} site(s)"))
