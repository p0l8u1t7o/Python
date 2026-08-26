"""MQTT ingestion service - the Sparkplug primary host application.

Responsibilities, in order:

1. announce itself on ``spBv1.0/STATE/{host_id}`` and register the matching
   offline message as its will, so edge nodes can tell whether anyone is
   listening;
2. subscribe to every uplink message type (optionally as an EMQX shared
   subscription so replicas share the load);
3. decode each protobuf payload, rejecting bad traffic at the edge;
4. resolve the Sparkplug address against a cached registry so unknown hardware
   cannot flood the pipeline;
5. hand the envelope to the message bus and return.

Step 5 is the whole point: the ingestor never writes to the database, so a slow
or locked database cannot stall MQTT consumption. That constraint is also why
metric *classification* is not done here - an alias-only metric cannot be read
without the birth table, and the birth table is in the database.
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
import orjson

from services.ingestor import protocol
from services.mqtt.client import MqttClient
from services import diagnostics as diag
from services.sparkplug import topics
from services.sparkplug.topics import MessageType

logger = get_logger("ingestor")

ENVELOPE_VERSION = 2

#: Bounded so a bus outage causes visible backpressure rather than an OOM kill.
INBOUND_QUEUE_SIZE = 50_000

#: Message types this host consumes. Everything goes to one stream so the
#: ``seq`` counter still means something by the time the worker looks at it.
_ACCEPTED_TYPES = frozenset(
    {
        MessageType.NBIRTH,
        MessageType.NDEATH,
        MessageType.DBIRTH,
        MessageType.DDEATH,
        MessageType.NDATA,
        MessageType.DDATA,
    }
)


def _state_payload(online: bool) -> bytes:
    """The host STATE document.

    The one place in the Sparkplug namespace that is JSON rather than protobuf,
    which looks like an inconsistency and is not: STATE is meant to be readable
    by anything watching the broker, including tools that have never heard of
    the protobuf schema.
    """
    return orjson.dumps({"online": online, "timestamp": int(now().timestamp() * 1000)})


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


#: 拒收原因 → 設備商該看哪裡。
_REJECT_HINTS = {
    "bad_timestamp": "Payload.timestamp 要是 UTC epoch 毫秒，且在過去 7 天～未來 5 分鐘內；檢查設備時鐘與單位（秒 vs 毫秒）",
    "decode_error": "不是合法的 Sparkplug B protobuf：確認用 sparkplug_b.proto 編碼、不是 JSON；對照文件附錄 H 的位元組",
    "invalid_payload": "protobuf 解得開但內容不合規範：檢查 datatype 與 value 欄位是否對應",
}


def _describe(data: dict) -> str:
    metrics = data.get("metrics") or []
    names = [m.get("name") or f"alias {m.get('alias')}" for m in metrics[:6]]
    more = f" …共 {len(metrics)} 個" if len(metrics) > 6 else ""
    parts = [f"seq={data.get('seq')}" if data.get("seq") is not None else "無 seq"]
    if data.get("bd_seq") is not None:
        parts.append(f"bdSeq={data.get('bd_seq')}")
    if names:
        parts.append("metrics: " + ", ".join(str(n) for n in names) + more)
    return "；".join(parts)


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
        if parsed is None or parsed.message_type not in _ACCEPTED_TYPES:
            self.stats.incr("dropped.unknown_topic")
            diag.trace(
                diag.STAGE_INGEST, diag.OUTCOME_DROPPED, topic=topic, reason="unknown_topic",
                message="topic 不在 spBv1.0/{group}/{NBIRTH|NDEATH|DBIRTH|DDEATH|DDATA|NDATA}/{node}[/{device}] 的形狀，或訊息型別不是上行",
                raw=payload, size=len(payload),
            )
            return

        self.stats.incr(f"received.{parsed.message_type}")

        try:
            data = protocol.decode_uplink(parsed, payload, received_at)
        except protocol.ProtocolError as exc:
            self.stats.incr(f"rejected.{exc.reason}")
            logger.warning(
                "rejected payload",
                extra={
                    "topic": topic,
                    "edge_node_id": parsed.edge_node_id,
                    "reason": exc.reason,
                    "error": str(exc)[:300],
                },
            )
            diag.trace(
                diag.STAGE_INGEST, diag.OUTCOME_REJECTED, group_id=parsed.group_id,
                edge_node_id=parsed.edge_node_id, device_id=parsed.device_id or "", topic=topic,
                kind=str(parsed.message_type), reason=exc.reason, message=str(exc)[:300],
                detail={"hint": _REJECT_HINTS.get(exc.reason, "")}, raw=payload, size=len(payload),
            )
            return

        node = self.registry.get_node(parsed.group_id, parsed.edge_node_id)
        if node is None:
            # Auto-provisioning needs a database write, so it is the worker's
            # job. The envelope goes through carrying only the address, and the
            # worker either creates the rows or drops it.
            if not settings.INGEST["AUTO_PROVISION"]:
                self.stats.incr("dropped.unknown_node")
                self._log_unknown_device(f"{parsed.group_id}/{parsed.edge_node_id}")
                diag.trace(
                    diag.STAGE_INGEST, diag.OUTCOME_DROPPED, group_id=parsed.group_id,
                    edge_node_id=parsed.edge_node_id, device_id=parsed.device_id or "", topic=topic,
                    kind=str(parsed.message_type), reason="unknown_node",
                    message=f"平台沒有 group_id={parsed.group_id}、node_id={parsed.edge_node_id} 的閘道器；"
                            "請確認 topic 的 group 是租戶代碼、node id 與整合頁登記的一致（大小寫也要相同）",
                    raw=payload, size=len(payload),
                )
                return
        elif not node.is_enabled:
            self.stats.incr("dropped.node_disabled")
            diag.trace(
                diag.STAGE_INGEST, diag.OUTCOME_DROPPED, organization_id=node.organization_id,
                group_id=parsed.group_id, edge_node_id=parsed.edge_node_id, topic=topic,
                kind=str(parsed.message_type), reason="node_disabled", message="這個閘道器在平台上被停用",
                size=len(payload),
            )
            return

        ref = None
        if parsed.device_id and node is not None:
            ref = self.registry.get_device(node.pk, parsed.device_id)
            if ref is not None and not ref.is_enabled:
                self.stats.incr("dropped.device_disabled")
                return

        envelope = {
            "v": ENVELOPE_VERSION,
            "kind": str(parsed.message_type),
            "topic": topic,
            "group_id": parsed.group_id,
            "edge_node_id": parsed.edge_node_id,
            "device_id": parsed.device_id,
            "edge_node_pk": str(node.pk) if node else None,
            "device_pk": str(ref.pk) if ref else None,
            "organization_id": str(node.organization_id) if node else None,
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

        diag.trace(
            diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=node.organization_id if node else None,
            group_id=parsed.group_id, edge_node_id=parsed.edge_node_id, device_id=parsed.device_id or "",
            topic=topic, kind=str(parsed.message_type), reason="accepted",
            message=_describe(data),
            detail={"seq": data.get("seq"), "metrics": len(data.get("metrics") or []),
                    "dropped_metrics": data.get("dropped_metrics", 0), "qos": qos, "retain": retain},
            raw=payload, size=len(payload),
        )

        stream = streams.qualified(streams.INGEST)
        try:
            self.inbound.put_nowait((stream, envelope))
        except queue.Full:
            self.stats.incr("dropped.queue_full")
            self._log_backpressure()

    # ---- host state ------------------------------------------------------
    def announce_online(self) -> None:
        """Publish the host birth. Runs on every CONNACK, reconnects included."""
        if self._mqtt is None:
            return
        qos, retain = topics.publish_options(MessageType.STATE)
        topic = topics.state_topic()
        if self._mqtt.publish(topic, _state_payload(True), qos=qos, retain=retain):
            logger.info("host state announced", extra={"topic": topic})
        else:
            logger.error("host state could not be published", extra={"topic": topic})

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

    def _log_unknown_device(self, address: str) -> None:
        elapsed = time.monotonic() - self._last_drop_log
        if elapsed > 30:
            self._last_drop_log = time.monotonic()
            logger.warning(
                "message from unregistered edge node dropped",
                extra={
                    "address": address,
                    "hint": "register it or set INGEST_AUTO_PROVISION=1",
                },
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
            on_connect_callback=self.announce_online,
            # Shared subscriptions are load-balanced by the broker, so a
            # persistent per-client session would only duplicate state.
            clean_session=settings.MQTT["USE_SHARED_SUBSCRIPTION"],
        )
        # Registered before connecting, because a will set afterwards is a will
        # the broker never received - and then a host that dies stays "online"
        # on a retained topic forever.
        state_qos, state_retain = topics.publish_options(MessageType.STATE)
        self._mqtt.set_last_will(
            topics.state_topic(),
            _state_payload(False),
            qos=state_qos,
            retain=state_retain,
        )
        logger.info(
            "ingestor starting",
            extra={
                "broker": f"{settings.MQTT['HOST']}:{settings.MQTT['PORT']}",
                "host_id": topics.host_id(),
                "subscriptions": [f for f, _ in subscriptions],
                "bus": settings.BUS_BACKEND,
                "nodes_known": self.registry.node_count,
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
            # A clean DISCONNECT makes the broker discard the will, so the
            # offline STATE has to be published here or nothing ever retracts
            # the online one.
            qos, retain = topics.publish_options(MessageType.STATE)
            try:
                self._mqtt.publish(
                    topics.state_topic(), _state_payload(False), qos=qos, retain=retain
                )
            except Exception:  # noqa: BLE001 - shutdown must not raise
                logger.warning("could not publish offline host state")
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
