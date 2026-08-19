"""Rebuild behind-the-meter energy intervals.

Schedule every few minutes. The default two-hour lookback intentionally
overlaps previous runs: late-arriving telemetry then corrects the interval it
belongs to, and the upsert makes re-running harmless.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Organization
from apps.ems.aggregator import DEFAULT_INTERVAL_SECONDS, aggregate_organization


class Command(BaseCommand):
    help = "Compute site-level energy intervals from raw telemetry."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="", help="Limit to one slug.")
        parser.add_argument(
            "--hours", type=float, default=2.0, help="Lookback window in hours."
        )
        parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
        parser.add_argument(
            "--since",
            default="",
            help="ISO-8601 start; overrides --hours for a manual backfill.",
        )

    def handle(self, *args, **options):
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

        total = 0
        for organization in organizations:
            summary = aggregate_organization(
                organization,
                since=since,
                until=until,
                interval_seconds=options["interval"],
            )
            for site_code, count in summary.items():
                if count:
                    self.stdout.write(f"{organization.slug}/{site_code}: {count} interval(s)")
                total += count

        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {total} interval(s) from {since:%Y-%m-%d %H:%M} to "
                f"{until:%Y-%m-%d %H:%M} UTC"
            )
        )
