"""Ingestor and worker in one process, sharing the in-memory bus.

Normally these are separate services precisely so they can be scaled and
restarted independently, and so a slow database cannot stall MQTT consumption.
That separation is the right shape for a deployment, and it is why the bus
exists at all.

It is the wrong shape for a laptop. Two processes cannot share
``BUS_BACKEND=memory`` - it is an in-process queue - so the split forces Redis
on anybody who only wants to watch telemetry arrive. This command removes that
requirement by putting both loops in one process, where the singleton bus from
``services.bus.factory.get_bus()`` connects them.

Use it for development. Run ``run_ingestor`` and ``run_worker`` separately,
against a real broker, for anything else.
"""

from __future__ import annotations

import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.logging import get_logger

logger = get_logger("core.pipeline")


class Command(BaseCommand):
    help = "Run the MQTT ingestor and the queue worker together (development)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-name",
            default="worker-1",
            help="Consumer name recorded on the bus.",
        )

    def handle(self, *args, **options):
        from services.bus.factory import get_bus
        from services.ingestor.main import Ingestor
        from services.worker.main import Worker

        if settings.BUS_BACKEND not in {"memory", "inmemory", "local"}:
            # Not refused: running both halves against Redis is harmless, just
            # pointless. Saying so beats silently doing something the operator
            # did not intend.
            self.stdout.write(
                self.style.WARNING(
                    f"BUS_BACKEND is '{settings.BUS_BACKEND}', so these two would "
                    "run just as well as separate services. This command exists "
                    "for the in-memory bus, which cannot cross a process boundary."
                )
            )

        # One bus, injected into both. Left to themselves each constructs its
        # own via build_bus(), which is right for separate processes talking to
        # Redis and silently wrong here: two InMemoryBus objects are two
        # unconnected queues, so the ingestor would fill one while the worker
        # drained the other and nothing would reach the database.
        bus = get_bus()
        ingestor = Ingestor(bus)
        worker = Worker(bus, name=options["worker_name"])
        stopping = threading.Event()

        def shutdown(*_args) -> None:
            if stopping.is_set():
                return
            stopping.set()
            self.stdout.write("stopping…")
            # Both stop() calls are idempotent and non-blocking; the threads
            # notice on their next loop.
            for service in (ingestor, worker):
                try:
                    service.stop()
                except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                    logger.warning("stop failed", extra={"error": repr(exc)})

        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, shutdown)
                except (ValueError, OSError):
                    pass  # not the main thread, or unsupported here

        threads = [
            threading.Thread(target=self._guard, args=("worker", worker, shutdown), daemon=True),
            threading.Thread(target=self._guard, args=("ingestor", ingestor, shutdown), daemon=True),
        ]
        # Worker first: it creates the consumer group, so starting it after the
        # ingestor would drop whatever arrived in between.
        for thread in threads:
            thread.start()

        self.stdout.write(
            self.style.SUCCESS("ingestor + worker running (in-process bus)")
        )
        try:
            while not stopping.is_set():
                stopping.wait(0.5)
        except KeyboardInterrupt:
            shutdown()

        for thread in threads:
            thread.join(timeout=10)
        self.stdout.write(self.style.SUCCESS("pipeline stopped"))

    def _guard(self, label: str, service, shutdown) -> None:
        """Run one service, and take the other down with it if it dies.

        A half-dead pipeline is the worst outcome: the ingestor would keep
        acknowledging MQTT messages onto a queue nobody drains, and the console
        would show a healthy broker and no data.
        """
        try:
            service.start()
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            self.stderr.write(f"{label} failed: {exc!r}")
            logger.exception("%s failed", label)
        finally:
            shutdown()
