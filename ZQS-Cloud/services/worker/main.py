"""Queue consumer: persists telemetry, evaluates rules, maintains device state.

Runs three loops in one process:

* the **consume loop** drains the bus in batches and dispatches each batch to a
  processor;
* the **maintenance loop** expires commands and marks silent devices offline;
* the **notification loop** delivers pending alert notifications.

Failure handling is deliberate. A batch that raises is retried once as a batch,
then re-processed one message at a time so a single poison payload is isolated
and dead-lettered instead of blocking the stream behind it.
"""

from __future__ import annotations

import signal
import threading
import time
from collections import defaultdict

from django.conf import settings
from django.db import close_old_connections

from apps.core.logging import get_logger
from services.bus import streams
from services.bus.base import BusError, BusMessage, MessageBus
from services.bus.factory import build_bus
from services.worker.maintenance import run_maintenance_cycle
from services.worker.notifications import dispatch_pending
from services.worker.processors import (
    CommandAckProcessor,
    EventProcessor,
    Shared,
    StatusProcessor,
    TelemetryProcessor,
)

logger = get_logger("worker")


class Worker:
    def __init__(self, bus: MessageBus | None = None, *, name: str = "worker-1") -> None:
        self.bus = bus or build_bus()
        self.name = name
        self.group = settings.BUS["CONSUMER_GROUP"]
        self.batch_size = settings.WORKER["BATCH_SIZE"]
        self.block_ms = settings.WORKER["BLOCK_MS"]
        self.max_retries = settings.WORKER["MAX_RETRIES"]

        self.shared = Shared()
        self.processors = {
            streams.TELEMETRY: TelemetryProcessor(self.shared),
            streams.STATUS: StatusProcessor(self.shared),
            streams.EVENT: EventProcessor(self.shared),
            streams.ALARM: EventProcessor(self.shared),
            streams.COMMAND_ACK: CommandAckProcessor(self.shared),
        }

        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        self._totals: dict[str, int] = defaultdict(int)
        self._last_reclaim = 0.0

    # ---- consume loop ----------------------------------------------------
    def _consume_loop(self) -> None:
        qualified = list(streams.all_qualified())
        self.bus.ensure_group(qualified, self.group)

        while not self._stopping.is_set():
            try:
                messages = self.bus.consume(
                    qualified,
                    group=self.group,
                    consumer=self.name,
                    count=self.batch_size,
                    block_ms=self.block_ms,
                )
                messages += self._maybe_reclaim(qualified)
            except BusError as exc:
                logger.error("bus consume failed, backing off", extra={"error": str(exc)})
                self._stopping.wait(2.0)
                continue

            if not messages:
                continue

            # Long-lived worker: recycle connections closed by the server.
            close_old_connections()
            self._dispatch(messages)

    def _maybe_reclaim(self, qualified: list[str]) -> list[BusMessage]:
        """Periodically adopt messages abandoned by a crashed worker."""
        if time.monotonic() - self._last_reclaim < 30:
            return []
        self._last_reclaim = time.monotonic()
        try:
            return self.bus.reclaim(
                qualified,
                group=self.group,
                consumer=self.name,
                min_idle_ms=settings.BUS["CLAIM_MIN_IDLE_MS"],
                count=self.batch_size,
            )
        except BusError as exc:
            logger.error("reclaim failed", extra={"error": str(exc)})
            return []

    def _dispatch(self, messages: list[BusMessage]) -> None:
        by_stream: dict[str, list[BusMessage]] = defaultdict(list)
        for message in messages:
            by_stream[message.stream].append(message)

        for stream, batch in by_stream.items():
            logical = streams.logical(stream)
            processor = self.processors.get(logical)
            if processor is None:
                logger.error("no processor for stream", extra={"stream": stream})
                self.bus.ack(stream, self.group, [m.id for m in batch])
                continue
            self._run_batch(processor, stream, logical, batch)

    def _run_batch(
        self, processor, stream: str, logical: str, batch: list[BusMessage]
    ) -> None:
        envelopes = [message.payload for message in batch]
        started = time.monotonic()
        try:
            stats = processor.process(envelopes)
        except Exception:  # noqa: BLE001 - isolate the failure, keep consuming
            logger.exception(
                "batch failed, retrying message by message",
                extra={"stream": stream, "size": len(batch)},
            )
            self._run_individually(processor, stream, logical, batch)
            return

        self.bus.ack(stream, self.group, [message.id for message in batch])
        elapsed_ms = (time.monotonic() - started) * 1000
        for key, value in (stats or {}).items():
            self._totals[f"{logical}.{key}"] += value
        self._totals[f"{logical}.batches"] += 1
        if elapsed_ms > 5000:
            logger.warning(
                "slow batch",
                extra={"stream": stream, "size": len(batch), "ms": round(elapsed_ms)},
            )

    def _run_individually(
        self, processor, stream: str, logical: str, batch: list[BusMessage]
    ) -> None:
        """Second pass: find the poison message rather than replaying the batch."""
        for message in batch:
            try:
                processor.process([message.payload])
            except Exception as exc:  # noqa: BLE001
                self._totals[f"{logical}.failed"] += 1
                if message.attempt >= self.max_retries:
                    self.bus.dead_letter(stream, message, reason=str(exc)[:300])
                    self.bus.ack(stream, self.group, [message.id])
                    logger.error(
                        "dead-lettered poison message",
                        extra={
                            "stream": stream,
                            "device_id": message.payload.get("device_id"),
                            "attempt": message.attempt,
                            "error": str(exc)[:300],
                        },
                    )
                else:
                    # Leave it un-acked so reclaim picks it up with a higher
                    # attempt count after the idle window.
                    self.bus.nack(stream, self.group, [message.id])
                continue
            self.bus.ack(stream, self.group, [message.id])
            self._totals[f"{logical}.recovered"] += 1

    # ---- background loops ------------------------------------------------
    def _maintenance_loop(self) -> None:
        interval = 30.0
        while not self._stopping.wait(interval):
            close_old_connections()
            try:
                summary = run_maintenance_cycle()
            except Exception:  # noqa: BLE001
                logger.exception("maintenance cycle failed")
                continue
            if any(summary.values()):
                logger.info("maintenance", extra=summary)

    def _notification_loop(self) -> None:
        while not self._stopping.wait(5.0):
            close_old_connections()
            try:
                sent, failed = dispatch_pending()
            except Exception:  # noqa: BLE001
                logger.exception("notification dispatch failed")
                continue
            if sent or failed:
                logger.info("notifications", extra={"sent": sent, "failed": failed})

    def _stats_loop(self) -> None:
        while not self._stopping.wait(60.0):
            if self._totals:
                snapshot = dict(self._totals)
                self._totals.clear()
                logger.info("worker stats", extra=snapshot)

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.bus.connect()
        logger.info(
            "worker starting",
            extra={
                "name": self.name,
                "bus": settings.BUS_BACKEND,
                "group": self.group,
                "batch_size": self.batch_size,
            },
        )

        for target, name in (
            (self._maintenance_loop, "maintenance"),
            (self._notification_loop, "notifications"),
            (self._stats_loop, "stats"),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

        self._consume_loop()

    def stop(self, *_args) -> None:
        if self._stopping.is_set():
            return
        logger.info("worker shutting down")
        self._stopping.set()
        for thread in self._threads:
            thread.join(timeout=3.0)
        self.bus.close()
        logger.info("worker stopped")


def run(name: str = "worker-1") -> None:
    worker = Worker(name=name)
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    try:
        worker.start()
    finally:
        worker.stop()
