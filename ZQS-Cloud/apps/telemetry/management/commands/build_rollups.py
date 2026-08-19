"""Materialise telemetry rollups so long-range charts skip the sample table."""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Organization
from apps.devices.models import Device
from apps.telemetry.models import LatestSample
from apps.telemetry.repository import build_rollups


class Command(BaseCommand):
    help = "Aggregate raw samples into fixed-width rollup buckets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval", type=int, default=900, help="Bucket width in seconds."
        )
        parser.add_argument(
            "--hours", type=float, default=25.0, help="How far back to rebuild."
        )
        parser.add_argument("--organization", default="")

    def handle(self, *args, **options):
        end = timezone.now()
        start = end - dt.timedelta(hours=options["hours"])
        interval = options["interval"]

        organizations = Organization.objects.filter(is_active=True)
        if options["organization"]:
            organizations = organizations.filter(slug=options["organization"])

        total = 0
        for organization in organizations:
            device_ids = list(
                Device.objects.filter(
                    organization=organization, deleted_at__isnull=True
                ).values_list("id", flat=True)
            )
            if not device_ids:
                continue
            metric_keys = list(
                LatestSample.objects.filter(device_id__in=device_ids)
                .values_list("metric_key", flat=True)
                .distinct()
            )
            if not metric_keys:
                continue

            written = build_rollups(
                organization_id=organization.id,
                device_ids=device_ids,
                metric_keys=metric_keys,
                start=start,
                end=end,
                interval_seconds=interval,
            )
            total += written
            self.stdout.write(f"{organization.slug}: {written} bucket(s)")

        self.stdout.write(
            self.style.SUCCESS(f"wrote {total} rollup bucket(s) at {interval}s")
        )
