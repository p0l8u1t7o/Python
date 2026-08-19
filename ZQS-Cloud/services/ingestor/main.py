"""MQTT ingestion service.

Responsibilities, in order:

1. subscribe to every uplink topic (optionally as an EMQX shared subscription
   so replicas share the load);
2. decode and schema-validate each payload, rejecting bad traffic at the edge;
3. resolve the device against a cached registry so unknown hardware cannot
   flood the pipeline;
4. hand the normalised envelope to the message bus and return.

Step 4 is the whole point: the ingestor never writes to the database, so a slow
or locked database cannot stall MQTT consumption.
"""

from __future__ import annotations

import queue
import signal
import threading
import time
from collections import defaultdict
from typing import Any

from django.conf import settings

from apps.core.logging import get_logger
from apps.core.timeutils import now
from apps.devices.registry import get_registry
from services.bus import streams
from services.bus.base import BusError, MessageBus
from services.bus.factory import build_bus
from services.ingestor import protocol
from services.mqtt import topics
from services.mqtt.client import MqttClient

logger = get_logger("ingestor")

ENVELOPE_VERSION = 1

#: Bounded so a bus outage causes visible backpressure rather than an OOM kill.
INBOUND_QUEUE_SIZE = 50_000

#: MQTT kind -> bus stream.
_STREAM_FOR_KIND = {
    topics.TELEMETRY: streams.TELEMETRY,
    topics.STATUS: streams.STATUS,
    topics.EVENT: streams.EVENT,
    topics.ALARM: streams.ALARM,
    topics.CONTROL_ACK: streams.COMMAND_ACK,
}


class Stats:
    """Counters flushed to the log once a minute."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = defaultdict(int)

    def incr(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[key] += amount

    def snapshot_and_reset(self) -> dict[str, int]:
        with self._lock:
            snapshot = dict(self._counts)
            self._counts.clear()
        return snapshot


class Ingestor:
    def __init__(self, bus: MessageBus | None = None, *, forwarders: int = 2) -> None:
        self.bus = bus or build_bus()
        self.registry = get_registry()
        self.stats = Stats()
        self.inbound: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(
            maxsize=INBOUND_QUEUE_SIZE
        )
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        self._forwarder_count = max(1, forwarders)
        self._mqtt: MqttClient | None = None
        self._last_drop_log = 0.0

    # ---- MQTT callback ---------------------------------------------------
    def on_message(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        received_at = now()
        parsed = topics.parse(topic)
        if parsed is None:
            self.stats.incr("dropped.unknown_topic")
            return

        self.stats.incr(f"received.{parsed.kind}")

        try:
            document = protocol.decode(payload)
            validated = protocol.validate(parsed.kind, document)
            data = self._normalize(parsed.kind, validated, received_at)
        except protocol.ProtocolError as exc:
            self.stats.incr(f"rejected.{exc.reason}")
            logger.warning(
                "rejected payload",
                extra={
                    "topic": topic,
                    "device_id": parsed.device_id,
                    "reason": exc.reason,
                    "error": str(exc)[:300],
                },
            )
            return

        ref = self.registry.get(parsed.device_id)
        if ref is None and not settings.INGEST["AUTO_PROVISION"]:
            self.stats.incr("dropped.unknown_device")
            self._log_unknown_device(parsed.device_id)
            return
        if ref is not None and not ref.is_enabled:
            self.stats.incr("dropped.device_disabled")
            return

        envelope = {
            "v": ENVELOPE_VERSION,
            "kind": parsed.kind,
            "topic": topic,
            "device_id": parsed.device_id,
            "device_pk": str(ref.pk) if ref else None,
            "organization_id": str(ref.organization_id) if ref else None,
            "recording_policy_id": (
                str(ref.recording_policy_id)
                if ref and ref.recording_policy_id
                else None
            ),
            "received_at": received_at.isoformat(),
            "retained": retain,
            "qos": qos,
            "data": data,
        }

        stream = streams.qualified(_STREAM_FOR_KIND[parsed.kind])
        try:
            self.inbound.put_nowait((stream, envelope))
        except queue.Full:
            # Telemetry is the only lossy-tolerable kind; everything else is
            # rare enough that blocking briefly is preferable to losing it.
            self.stats.incr("dropped.queue_full")
            self._log_backpressure()

    def _normalize(self, kind: str, validated, received_at) -> dict[str, Any]:
        if kind == topics.TELEMETRY:
            return {
                "seq": validated.seq,
                "meta": validated.meta,
                "readings": protocol.normalize_readings(
                    validated, received_at=received_at
                ),
            }

        document = validated.model_dump(mode="json")
        document["ts"] = protocol.resolve_timestamp(
            getattr(validated, "ts", None), received_at=received_at
        ).isoformat()
        return document

    # ---- forwarder threads ----------------------------------------------
    def _forward_loop(self) -> None:
        batch_max = 500
        while not self._stopping.is_set():
            try:
                first = self.inbound.get(timeout=0.5)
            except queue.Empty:
                continue

            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            grouped[first[0]].append(first[1])
            collected = 1
            while collected < batch_max:
                try:
                    stream, envelope = self.inbound.get_nowait()
                except queue.Empty:
                    break
                grouped[stream].append(envelope)
                collected += 1

            for stream, envelopes in grouped.items():
                self._publish_with_retry(stream, envelopes)
                self.stats.incr("published", len(envelopes))
            for _ in range(collected):
                self.inbound.task_done()

    def _publish_with_retry(self, stream: str, envelopes: list[dict[str, Any]]) -> None:
        delay = 0.5
        for attempt in range(1, 6):
            try:
                self.bus.publish_many(stream, envelopes)
                return
            except BusError as exc:
                self.stats.incr("bus.publish_error")
                logger.error(
                    "bus publish failed, retrying",
                    extra={"stream": stream, "attempt": attempt, "error": str(exc)},
                )
                if self._stopping.wait(delay):
                    break
                delay = min(delay * 2, 10.0)
        self.stats.incr("dropped.bus_unavailable", len(envelopes))
        logger.error(
            "giving up on batch after retries",
            extra={"stream": stream, "count": len(envelopes)},
        )

    # ---- reporting -------------------------------------------------------
    def _stats_loop(self) -> None:
        while not self._stopping.wait(60.0):
            snapshot = self.stats.snapshot_and_reset()
            if snapshot:
                logger.info(
                    "ingest stats",
                    extra={
                        **snapshot,
                        "queue_depth": self.inbound.qsize(),
                        "devices_known": self.registry.size,
                    },
                )

    def _log_unknown_device(self, device_id: str) -> None:
        elapsed = time.monotonic() - self._last_drop_log
        if elapsed > 30:
            self._last_drop_log = time.monotonic()
            logger.warning(
                "message from unregistered device dropped",
                extra={"device_id": device_id, "hint": "register it or set INGEST_AUTO_PROVISION=1"},
            )

    def _log_backpressure(self) -> None:
        elapsed = time.monotonic() - self._last_drop_log
        if elapsed > 10:
            self._last_drop_log = time.monotonic()
            logger.error(
                "inbound queue full; dropping messages",
                extra={"queue_size": INBOUND_QUEUE_SIZE},
            )

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.bus.connect()
        self.registry.refresh(force=True)

        for index in range(self._forwarder_count):
            thread = threading.Thread(
                target=self._forward_loop, name=f"forwarder-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

        stats_thread = threading.Thread(target=self._stats_loop, name="stats", daemon=True)
        stats_thread.start()
        self._threads.append(stats_thread)

        subscriptions = topics.uplink_subscriptions()
        self._mqtt = MqttClient(
            client_suffix="ingestor",
            subscriptions=subscriptions,
            on_message_callback=self.on_message,
            # Shared subscriptions are load-balanced by the broker, so a
            # persistent per-client session would only duplicate state.
            clean_session=settings.MQTT["USE_SHARED_SUBSCRIPTION"],
        )
        logger.info(
            "ingestor starting",
            extra={
                "broker": f"{settings.MQTT['HOST']}:{settings.MQTT['PORT']}",
                "subscriptions": [f for f, _ in subscriptions],
                "bus": settings.BUS_BACKEND,
                "devices_known": self.registry.size,
            },
        )
        self._mqtt.loop_forever()

    def stop(self, *_args) -> None:
        if self._stopping.is_set():
            return
        logger.info("ingestor shutting down")
        self._stopping.set()
        if self._mqtt is not None:
            self._mqtt.disconnect()

        # Give forwarders a moment to drain what is already queued.
        deadline = time.monotonic() + 5.0
        while not self.inbound.empty() and time.monotonic() < deadline:
            time.sleep(0.1)

        for thread in self._threads:
            thread.join(timeout=2.0)
        self.bus.close()
        logger.info("ingestor stopped", extra={"undrained": self.inbound.qsize()})


def run() -> None:
    ingestor = Ingestor()
    signal.signal(signal.SIGINT, ingestor.stop)
    signal.signal(signal.SIGTERM, ingestor.stop)
    try:
        ingestor.start()
    finally:
        ingestor.stop()
