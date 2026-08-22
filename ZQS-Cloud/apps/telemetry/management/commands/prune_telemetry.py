"""Apply retention policy to the sample table.

Run daily (cron / Task Scheduler). Deletion is chunked per series so a large
purge never holds a long write lock - which matters on SQLite, where a single
long transaction blocks the ingest worker.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.devices.models import Device
from apps.telemetry.models import LatestSample
from apps.telemetry.policy import PolicyResolver
from apps.telemetry.repository import prune_samples


class Command(BaseCommand):
    help = "Delete telemetry samples older than each metric's retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting anything.",
        )
        parser.add_argument(
            "--organization",
            default="",
            help="Limit to one organization slug.",
        )
        parser.add_argument("--chunk", type=int, default=5000)

    def handle(self, *args, **options):
        resolver = PolicyResolver(ttl_seconds=0)
        resolver.refresh(force=True)

        devices = Device.objects.filter(deleted_at__isnull=True).select_related(
            "device_type"
        )
        if options["organization"]:
            devices = devices.filter(organization__slug=options["organization"])

        now = timezone.now()
        total_deleted = 0
        inspected = 0

        for device in devices:
            ref = _ref_for(device)
            policy = resolver.for_device(ref)

            metric_keys = list(
                LatestSample.objects.filter(device=device).values_list(
                    "metric_key", flat=True
                )
            )
            for metric_key in metric_keys:
                rule = policy.rule_for(metric_key)
                retention = (
                    rule.retention_days
                    if rule is not None and rule.retention_days is not None
                    else policy.default_retention_days
                )
                inspected += 1
                if not retention:
                    continue  # 0 or None means keep forever

                cutoff = now - dt.timedelta(days=retention)
                if options["dry_run"]:
                    from apps.telemetry.models import TelemetrySample

                    count = TelemetrySample.objects.filter(
                        device=device, metric_key=metric_key, ts__lt=cutoff
                    ).count()
                    if count:
                        self.stdout.write(
                            f"would delete {count:>8} rows  "
                            f"{device.device_id}/{metric_key} older than {cutoff:%Y-%m-%d}"
                        )
                        total_deleted += count
                    continue

                deleted = prune_samples(
                    device_id=device.id,
                    metric_key=metric_key,
                    older_than=cutoff,
                    chunk=options["chunk"],
                )
                total_deleted += deleted
                if deleted:
                    self.stdout.write(
                        f"deleted {deleted:>8} rows  {device.device_id}/{metric_key}"
                    )

        verb = "would delete" if options["dry_run"] else "deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {total_deleted} sample(s) across {inspected} series"
            )
        )


def _ref_for(device):
    from apps.devices.registry import DeviceRef

    return DeviceRef(
        pk=device.id,
        device_id=device.device_id,
        edge_node_id=device.edge_node_id,
        organization_id=device.organization_id,
        site_id=device.site_id,
        device_type_id=device.device_type_id,
        recording_policy_id=device.recording_policy_id,
        is_enabled=device.is_enabled,
    )
