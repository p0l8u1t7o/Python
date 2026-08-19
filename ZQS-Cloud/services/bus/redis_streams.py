"""Redis Streams backend.

Chosen as the default because it gives consumer groups, explicit acks and a
pending-entries list (so a crashed worker's in-flight messages are recoverable)
without introducing a second broker alongside EMQX.

The payload travels as a single ``data`` field holding compact JSON; Redis
stream fields are flat strings, and one blob keeps nested envelopes intact.
"""

from __future__ import annotations

from typing import Any, Sequence

import orjson
import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from apps.core.logging import get_logger
from services.bus.base import BusError, BusMessage, MessageBus

logger = get_logger("bus.redis")

_PAYLOAD_FIELD = "data"
_ATTEMPT_FIELD = "attempt"


class RedisStreamBus(MessageBus):
    def __init__(
        self,
        url: str,
        *,
        max_stream_length: int = 1_000_000,
        socket_timeout: float = 30.0,
    ) -> None:
        self.url = url
        self.max_stream_length = max_stream_length
        self.socket_timeout = socket_timeout
        self._client: redis.Redis | None = None

    # ---- lifecycle -------------------------------------------------------
    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise BusError("Redis bus is not connected; call connect() first")
        return self._client

    def connect(self) -> None:
        if self._client is not None:
            return
        self._client = redis.Redis.from_url(
            self.url,
            decode_responses=True,
            socket_timeout=self.socket_timeout,
            socket_connect_timeout=5.0,
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        try:
            self._client.ping()
        except RedisConnectionError as exc:
            self._client = None
            raise BusError(f"Cannot reach Redis at {self.url}: {exc}") from exc
        logger.info("connected to redis stream bus", extra={"url": _redact(self.url)})

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- producer --------------------------------------------------------
    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        try:
            return self.client.xadd(
                stream,
                {_PAYLOAD_FIELD: orjson.dumps(payload).decode()},
                maxlen=self.max_stream_length,
                approximate=True,
            )
        except redis.RedisError as exc:
            raise BusError(f"publish to {stream} failed: {exc}") from exc

    def publish_many(self, stream: str, payloads) -> list[str]:
        pipe = self.client.pipeline(transaction=False)
        count = 0
        for payload in payloads:
            pipe.xadd(
                stream,
                {_PAYLOAD_FIELD: orjson.dumps(payload).decode()},
                maxlen=self.max_stream_length,
                approximate=True,
            )
            count += 1
        if count == 0:
            return []
        try:
            return list(pipe.execute())
        except redis.RedisError as exc:
            raise BusError(f"batch publish to {stream} failed: {exc}") from exc

    # ---- consumer --------------------------------------------------------
    def ensure_group(self, streams: Sequence[str], group: str) -> None:
        for stream in streams:
            try:
                # mkstream so the group can be created before any producer runs.
                self.client.xgroup_create(stream, group, id="0", mkstream=True)
                logger.info("created consumer group", extra={"stream": stream, "group": group})
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise BusError(f"cannot create group {group} on {stream}: {exc}") from exc

    def consume(
        self,
        streams: Sequence[str],
        *,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[BusMessage]:
        # '>' means "messages never delivered to any consumer in this group".
        request = {stream: ">" for stream in streams}
        try:
            response = self.client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams=request,
                count=count,
                block=block_ms,
            )
        except ResponseError as exc:
            if "NOGROUP" in str(exc):
                self.ensure_group(streams, group)
                return []
            raise BusError(f"consume failed: {exc}") from exc
        except redis.RedisError as exc:
            raise BusError(f"consume failed: {exc}") from exc

        return _decode_response(response)

    def ack(self, stream: str, group: str, message_ids: Sequence[str]) -> None:
        if not message_ids:
            return
        try:
            self.client.xack(stream, group, *message_ids)
            # Acked entries are still in the stream; XDEL frees memory now that
            # only one consumer group reads these streams.
            self.client.xdel(stream, *message_ids)
        except redis.RedisError as exc:
            raise BusError(f"ack on {stream} failed: {exc}") from exc

    def reclaim(
        self,
        streams: Sequence[str],
        *,
        group: str,
        consumer: str,
        min_idle_ms: int,
        count: int = 100,
    ) -> list[BusMessage]:
        """Adopt entries left pending by a worker that died mid-batch."""
        reclaimed: list[BusMessage] = []
        for stream in streams:
            try:
                _cursor, entries, _deleted = self.client.xautoclaim(
                    name=stream,
                    groupname=group,
                    consumername=consumer,
                    min_idle_time=min_idle_ms,
                    count=count,
                )
            except ResponseError as exc:
                if "NOGROUP" in str(exc):
                    continue
                raise BusError(f"reclaim on {stream} failed: {exc}") from exc
            except redis.RedisError as exc:
                raise BusError(f"reclaim on {stream} failed: {exc}") from exc

            for message_id, fields in entries or []:
                message = _decode_entry(stream, message_id, fields)
                if message is not None:
                    # Reclaimed implies at least a second attempt.
                    message.attempt = max(message.attempt, 2)
                    reclaimed.append(message)
        if reclaimed:
            logger.warning("reclaimed stale messages", extra={"count": len(reclaimed)})
        return reclaimed

    def dead_letter(self, stream: str, message: BusMessage, reason: str) -> None:
        from services.bus import streams as stream_names

        target = stream_names.qualified(stream_names.DEAD_LETTER)
        try:
            self.client.xadd(
                target,
                {
                    _PAYLOAD_FIELD: orjson.dumps(
                        {
                            "origin_stream": stream,
                            "origin_id": message.id,
                            "reason": reason,
                            "attempt": message.attempt,
                            "payload": message.payload,
                        }
                    ).decode()
                },
                maxlen=self.max_stream_length,
                approximate=True,
            )
        except redis.RedisError as exc:  # never let DLQ failure kill the worker
            logger.error("dead-letter write failed: %s", exc)

    def health(self) -> dict[str, Any]:
        try:
            self.client.ping()
            return {"backend": "redis", "ok": True}
        except Exception as exc:  # noqa: BLE001 - health probe reports anything
            return {"backend": "redis", "ok": False, "error": str(exc)}

    def pending_summary(self, streams: Sequence[str], group: str) -> dict[str, int]:
        """Backlog depth per stream, for the /api/system/health endpoint."""
        summary: dict[str, int] = {}
        for stream in streams:
            try:
                info = self.client.xpending(stream, group)
                summary[stream] = int(info.get("pending", 0)) if info else 0
            except redis.RedisError:
                summary[stream] = -1
        return summary


def _decode_response(response) -> list[BusMessage]:
    messages: list[BusMessage] = []
    for stream, entries in response or []:
        for message_id, fields in entries:
            message = _decode_entry(stream, message_id, fields)
            if message is not None:
                messages.append(message)
    return messages


def _decode_entry(stream: str, message_id: str, fields: dict) -> BusMessage | None:
    raw = fields.get(_PAYLOAD_FIELD)
    if raw is None:
        logger.warning("stream entry without payload", extra={"stream": stream})
        return None
    try:
        payload = orjson.loads(raw)
    except orjson.JSONDecodeError:
        logger.error("undecodable stream entry", extra={"stream": stream, "id": message_id})
        return None
    attempt = int(fields.get(_ATTEMPT_FIELD, 1) or 1)
    return BusMessage(id=message_id, stream=stream, payload=payload, attempt=attempt)


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    return f"{scheme}://***@{rest.split('@', 1)[1]}"
