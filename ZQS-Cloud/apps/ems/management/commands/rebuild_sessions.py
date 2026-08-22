"""Recompute device operating sessions from stored telemetry.

Deliberately shaped like ``aggregate_energy``: the same overlapping lookback,
the same "safe to re-run" contract, so operators have one mental model for both
jobs rather than two.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Organization
from apps.ems.sessions import rebuild_organization


class Command(BaseCommand):
    help = "Rebuild charge / discharge / running sessions from telemetry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=float,
            default=2.0,
            help=(
                "Lookback in hours (default 2). The overlap is intentional: "
                "late samples correct the window they belong to."
            ),
        )
        parser.add_argument("--organization", default="", help="Slug; blank means all.")
        parser.add_argument(
            "--device",
            default="",
            help="Restrict to one device_id. Use with --since to repair a gap.",
        )
        parser.add_argument(
            "--since",
            default="",
            help="ISO 8601 start instant, overriding --hours.",
        )

    def handle(self, *args, **options):
        from apps.devices.models import Device

        until = timezone.now()
        if options["since"]:
            since = dt.datetime.fromisoformat(options["since"])
            if since.tzinfo is None:
                since = since.replace(tzinfo=dt.timezone.utc)
        else:
            since = until - dt.timedelta(hours=options["hours"])

        organizations = Organization.objects.filter(is_active=True)
        if options["organization"]:
            organizations = organizations.filter(slug=options["organization"])

        device_pk = None
        if options["device"]:
            device = Device.objects.filter(device_id=options["device"]).first()
            if device is None:
                self.stderr.write(f"no device with id {options['device']!r}")
                return
            device_pk = device.pk

        total = 0
        for organization in organizations:
            result = rebuild_organization(
                organization, since=since, until=until, device_id=device_pk
            )
            total += result.written
            self.stdout.write(
                f"{organization.slug}: {result.written} session(s) across "
                f"{result.device_count} asset(s), {result.deleted} replaced"
            )
            for note in result.skipped:
                self.stdout.write(self.style.WARNING(f"  skipped {note}"))

        self.stdout.write(self.style.SUCCESS(f"wrote {total} session(s)"))
