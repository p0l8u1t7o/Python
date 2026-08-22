"""Run the periodic maintenance jobs in one long-lived process.

docker-compose wraps the same jobs in ``sh -c "while true; ...; sleep 300; done"``.
That has no Windows equivalent and, more importantly, gives a supervisor
nothing to signal: killing the shell can leave a management command mid-write.
This command is the single process form - one PID to start, one to stop, and a
signal handler that finishes the cycle in flight before exiting.

Run exactly one instance.
"""

from __future__ import annotations

import signal
import threading
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core.logging import get_logger

logger = get_logger("scheduler")


class Command(BaseCommand):
    help = "Periodically aggregate energy intervals, build rollups and prune samples."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=300.0,
            help="Seconds between cycles (default 300).",
        )
        parser.add_argument(
            "--hours",
            type=float,
            default=2.0,
            help="Energy aggregation lookback, in hours (default 2).",
        )
        parser.add_argument(
            "--rollup-interval",
            type=int,
            default=900,
            help="Rollup bucket width in seconds (default 900).",
        )
        parser.add_argument(
            "--rollup-hours",
            type=float,
            default=25.0,
            help="How far back to rebuild rollups (default 25).",
        )
        parser.add_argument(
            "--prune-every",
            type=int,
            default=288,
            help=(
                "Run prune_telemetry every N cycles; 0 disables it. The default "
                "is once a day at the default interval."
            ),
        )
        parser.add_argument(
            "--session-hours",
            type=float,
            default=2.0,
            help=(
                "Operating-session rebuild lookback, in hours (default 2). "
                "Overlapping on purpose, like the energy aggregation."
            ),
        )
        parser.add_argument(
            "--no-dispatch",
            action="store_true",
            help=(
                "Do not execute dispatch windows. The engine sends real "
                "commands to real hardware, so there is an off switch."
            ),
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single cycle and exit. Useful from Task Scheduler or cron.",
        )

    def handle(self, *args, **options):
        stopping = threading.Event()

        def _request_stop(signum, _frame):
            self.stdout.write(f"signal {signum} received, finishing this cycle")
            stopping.set()

        # SIGBREAK is what CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT delivers
        # on Windows; SIGTERM is what Docker and POSIX supervisors send.
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, _request_stop)
                except (ValueError, OSError):
                    pass  # not the main thread, or unsupported on this platform

        interval = max(float(options["interval"]), 1.0)
        prune_every = max(int(options["prune_every"]), 0)
        cycle = 0

        while True:
            cycle += 1
            started = time.monotonic()

            self._run_job(
                "aggregate_energy",
                hours=options["hours"],
            )
            self._run_job(
                "build_rollups",
                interval=options["rollup_interval"],
                hours=options["rollup_hours"],
            )
            # After the rollups: sessions read the same samples, and running
            # them in this order means a freshly closed session is visible in
            # the same cycle the energy behind it was aggregated.
            self._run_job("rebuild_sessions", hours=options["session_hours"])
            if not options["no_dispatch"]:
                # Last, and deliberately so: the dispatch engine reads the
                # live SOC to decide whether the plan permits a discharge, and
                # everything above has just refreshed what it reads.
                self._run_job("run_dispatch")
            if prune_every and cycle % prune_every == 0:
                self._run_job("prune_telemetry")

            if options["once"] or stopping.is_set():
                break

            # Interruptible idle. Waited in one-second slices rather than one
            # long wait: on Windows a signal arriving while the main thread
            # sits on a lock is not handled until that wait returns, which
            # would delay shutdown by up to a full interval.
            remaining = interval - (time.monotonic() - started)
            while remaining > 0 and not stopping.is_set():
                stopping.wait(min(1.0, remaining))
                remaining -= 1.0
            if stopping.is_set():
                break

        self.stdout.write(self.style.SUCCESS(f"scheduler stopped after {cycle} cycle(s)"))

    def _run_job(self, name: str, **kwargs) -> None:
        """One job failing must not take the loop down with it."""
        try:
            call_command(name, **kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            self.stderr.write(f"{name} failed: {exc!r}")
            logger.exception("scheduler job failed", extra={"job": name})
