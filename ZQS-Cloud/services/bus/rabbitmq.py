"""RabbitMQ (AMQP 0-9-1) backend.

Use this when RabbitMQ is already part of the estate. Semantics are mapped onto
the same contract as the Redis backend:

* one durable direct exchange, one durable queue per logical stream;
* ``BusMessage.id`` carries the AMQP delivery tag;
* redelivery count is tracked in the ``x-attempt`` header, and a message that
  exhausts its retries is routed to the dead-letter queue.

Requires ``pip install -r requirements-optional.txt``.
"""

from __future__ import annotations

import threading
from typing import Any, Sequence

import orjson

from apps.core.logging import get_logger
from services.bus.base import BusError, BusMessage, MessageBus

logger = get_logger("bus.rabbitmq")

try:  # optional dependency
    import pika
    from pika.exceptions import AMQPError
except ImportError:  # pragma: no cover - exercised only without pika installed
    pika = None
    AMQPError = Exception


class RabbitMQBus(MessageBus):
    EXCHANGE = "zqs.ingest"
    DEAD_LETTER_EXCHANGE = "zqs.ingest.dlx"

    def __init__(self, url: str, *, prefetch: int = 500) -> None:
        if pika is None:
            raise BusError(
                "BUS_BACKEND=rabbitmq requires pika: "
                "pip install -r requirements-optional.txt"
            )
        self.url = url
        self.prefetch = prefetch
        self._connection = None
        self._channel = None
        self._declared: set[str] = set()
        # pika channels are not thread-safe; serialise access.
        self._lock = threading.RLock()

    # ---- lifecycle -------------------------------------------------------
    def connect(self) -> None:
        if self._connection is not None and self._connection.is_open:
            return
        try:
            params = pika.URLParameters(self.url)
            params.heartbeat = 30
            params.blocked_connection_timeout = 60
            self._connection = pika.BlockingConnection(params)
            self._channel = self._connection.channel()
            self._channel.basic_qos(prefetch_count=self.prefetch)
            self._channel.exchange_declare(
                exchange=self.EXCHANGE, exchange_type="direct", durable=True
            )
            self._channel.exchange_declare(
                exchange=self.DEAD_LETTER_EXCHANGE, exchange_type="direct", durable=True
            )
        except AMQPError as exc:
            raise BusError(f"Cannot reach RabbitMQ: {exc}") from exc
        logger.info("connected to rabbitmq bus")

    def close(self) -> None:
        with self._lock:
            if self._connection is not None and self._connection.is_open:
                self._connection.close()
            self._connection = None
            self._channel = None
            self._declared.clear()

    def _ensure_channel(self):
        if self._channel is None or self._channel.is_closed:
            self.connect()
        return self._channel

    def _declare(self, stream: str) -> None:
        if stream in self._declared:
            return
        channel = self._ensure_channel()
        dlq = f"{stream}.dead"
        channel.queue_declare(queue=dlq, durable=True)
        channel.queue_bind(queue=dlq, exchange=self.DEAD_LETTER_EXCHANGE, routing_key=stream)
        channel.queue_declare(
            queue=stream,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": stream,
            },
        )
        channel.queue_bind(queue=stream, exchange=self.EXCHANGE, routing_key=stream)
        self._declared.add(stream)

    # ---- producer --------------------------------------------------------
    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        with self._lock:
            channel = self._ensure_channel()
            self._declare(stream)
            try:
                channel.basic_publish(
                    exchange=self.EXCHANGE,
                    routing_key=stream,
                    body=orjson.dumps(payload),
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=2,  # persist to disk
                    ),
                )
            except AMQPError as exc:
                raise BusError(f"publish to {stream} failed: {exc}") from exc
        return ""  # AMQP assigns no publisher-visible id

    # ---- consumer --------------------------------------------------------
    def ensure_group(self, streams: Sequence[str], group: str) -> None:
        # Queues are the group; ``group`` is unused but kept for interface parity.
        with self._lock:
            for stream in streams:
                self._declare(stream)

    def consume(
        self,
        streams: Sequence[str],
        *,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[BusMessage]:
        """Drain up to ``count`` messages with basic_get.

        Polling rather than basic_consume keeps the batching model identical to
        the Redis backend, at the cost of one round trip per message.
        """
        messages: list[BusMessage] = []
        with self._lock:
            channel = self._ensure_channel()
            for stream in streams:
                self._declare(stream)
                while len(messages) < count:
                    method, properties, body = channel.basic_get(queue=stream, auto_ack=False)
                    if method is None:
                        break
                    try:
                        payload = orjson.loads(body)
                    except orjson.JSONDecodeError:
                        channel.basic_nack(method.delivery_tag, requeue=False)
                        logger.error("undecodable amqp message", extra={"stream": stream})
                        continue
                    attempt = 1
                    if properties and properties.headers:
                        attempt = int(properties.headers.get("x-attempt", 1))
                    if method.redelivered:
                        attempt = max(attempt, 2)
                    messages.append(
                        BusMessage(
                            id=str(method.delivery_tag),
                            stream=stream,
                            payload=payload,
                            attempt=attempt,
                        )
                    )
            if not messages:
                # Yield to heartbeats instead of hot-looping on an empty queue.
                self._connection.sleep(block_ms / 1000.0)
        return messages

    def ack(self, stream: str, group: str, message_ids: Sequence[str]) -> None:
        with self._lock:
            channel = self._ensure_channel()
            for tag in message_ids:
                try:
                    channel.basic_ack(delivery_tag=int(tag))
                except (AMQPError, ValueError) as exc:
                    logger.error("ack failed", extra={"tag": tag, "error": str(exc)})

    def nack(self, stream: str, group: str, message_ids: Sequence[str]) -> None:
        with self._lock:
            channel = self._ensure_channel()
            for tag in message_ids:
                try:
                    channel.basic_nack(delivery_tag=int(tag), requeue=True)
                except (AMQPError, ValueError) as exc:
                    logger.error("nack failed", extra={"tag": tag, "error": str(exc)})

    def dead_letter(self, stream: str, message: BusMessage, reason: str) -> None:
        with self._lock:
            channel = self._ensure_channel()
            try:
                # requeue=False routes through the queue's dead-letter exchange.
                channel.basic_nack(delivery_tag=int(message.id), requeue=False)
            except (AMQPError, ValueError) as exc:
                logger.error("dead-letter failed", extra={"error": str(exc)})
        logger.warning(
            "dead-lettered message", extra={"stream": stream, "reason": reason}
        )

    def health(self) -> dict[str, Any]:
        ok = self._connection is not None and self._connection.is_open
        return {"backend": "rabbitmq", "ok": ok}
