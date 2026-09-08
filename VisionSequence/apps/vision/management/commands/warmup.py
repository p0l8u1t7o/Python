"""手動執行靜默暖機."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vision import warmup


class Command(BaseCommand):
    help = "Warm up enabled commissioned flows without creating run history."

    def add_arguments(self, parser):
        parser.add_argument("--flows", default="", help="Comma-separated flow ids to warm up")
        parser.add_argument("--all", action="store_true", dest="all_flows", help="Warm up all enabled flows, not only commissioned flows")
        parser.add_argument("--timeout", type=float, default=None, help="Per-flow timeout in seconds")

    def handle(self, *args, **options):
        try:
            if options["flows"]:
                flow_ids = warmup.parse_flow_ids(options["flows"])
            else:
                flow_ids = warmup.flow_ids_for_mode("all" if options["all_flows"] else "commissioned")
        except ValueError as exc:
            raise CommandError(f"--flows expects comma-separated integer ids: {exc}") from None
        timeout_s = options["timeout"]
        if timeout_s is None:
            timeout_s = float(settings.VISION.get("WARMUP_TIMEOUT_S", 30))
        result = warmup.warm_flows(flow_ids, timeout_s=timeout_s)
        rows = result["items"]
        self.stdout.write("Flow ID  Name                          Status    Duration ms  Reason")
        self.stdout.write("-------  ----------------------------  --------  -----------  ------")
        for row in rows:
            self.stdout.write(
                f"{row['flow_id']:>7}  {str(row['name'])[:28]:<28}  {row['status']:<8}  {row['duration_ms']:>11.1f}  {row['reason']}"
            )
        summary = result["summary"]
        self.stdout.write(
            self.style.SUCCESS(
                f"Warmup complete: warmed={summary.get('warmed', 0)}, skipped={summary.get('skipped', 0)}, "
                f"failed={summary.get('failed', 0)}, total={len(rows)}"
            )
        )
