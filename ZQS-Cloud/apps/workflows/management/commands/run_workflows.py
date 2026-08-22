"""Drive workflow runs: advance every one that is due, then wait.

A separate process from ``run_scheduler`` and deliberately so. The scheduler's
jobs are minutes apart and each one is a heavy sweep; this ticks every couple
of seconds because the interval *is* the resolution of every timer an operator
draws. Putting a two-second loop inside a sixty-second scheduler would either
make timers useless or make the sweeps run far too often.

Idle cost is one indexed query per tick.
"""

from __future__ import annotations

import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.core.logging import get_logger
from apps.workflows.runner import sweep_orphans, tick

logger = get_logger("workflows.command")


class Command(BaseCommand):
    help = "Advance running workflows. Long-lived; one instance."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=0.0,
            help="Seconds between ticks. 0 uses WORKFLOW_TICK_SECONDS.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Advance whatever is due and exit. For tests and cron.",
        )

    def handle(self, *args, **options):
        interval = options["interval"] or float(settings.WORKFLOWS["TICK_SECONDS"])

        if options["once"]:
            reports = tick()
            self.stdout.write(f"advanced {len(reports)} run(s)")
            return

        stopping = {"value": False}

        def stop(*_args):
            stopping["value"] = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        self.stdout.write(
            self.style.SUCCESS(f"workflow engine running, tick {interval}s")
        )
        last_sweep = 0.0
        while not stopping["value"]:
            try:
                # Long-lived process: recycle connections the server closed.
                close_old_connections()
                reports = tick()
                if reports:
                    finished = sum(1 for r in reports if r.finished)
                    logger.info(
                        "workflow tick",
                        extra={"advanced": len(reports), "finished": finished},
                    )
                if time.monotonic() - last_sweep > 300:
                    last_sweep = time.monotonic()
                    stranded = sweep_orphans()
                    if stranded:
                        logger.warning(
                            "released stranded workflow runs",
                            extra={"count": stranded},
                        )
            except Exception:  # noqa: BLE001 - the loop must outlive one bad tick
                logger.exception("workflow tick failed")
            time.sleep(interval)

        self.stdout.write("workflow engine stopped")
