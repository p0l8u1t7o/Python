"""In-process bus for development and tests.

Lets ``manage.py runserver`` plus ``manage.py run_ingestor`` work with no Redis
or RabbitMQ running. Not durable - a restart drops the backlog - so it is never
appropriate in production.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import defaultdict, deque
from typing import Any, Sequence

from apps.core.logging import get_logger
from services.bus.base import BusMessage, MessageBus

logger = get_logger("bus.memory")


class InMemoryBus(MessageBus):
    def __init__(self, *, max_stream_length: int = 100_000) -> None:
        self._queues: dict[str, deque[BusMessage]] = defaultdict(
            lambda: deque(maxlen=max_stream_length)
        )
        self._pending: dict[str, BusMessage] = {}
        self._dead: deque[dict[str, Any]] = deque(maxlen=1000)
        self._counter = itertools.count(1)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)

    def connect(self) -> None:
        logger.warning(
            "using the in-memory bus: messages are lost on restart, dev only"
        )

    def close(self) -> None:
        with self._lock:
            self._queues.clear()
            self._pending.clear()

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        message_id = f"{int(time.time() * 1000)}-{next(self._counter)}"
        with self._not_empty:
            self._queues[stream].append(
                BusMessage(id=message_id, stream=stream, payload=payload)
            )
            self._not_empty.notify()
        return message_id

    def ensure_group(self, streams: Sequence[str], group: str) -> None:
        with self._lock:
            for stream in streams:
                self._queues.setdefault(stream, deque())

    def consume(
        self,
        streams: Sequence[str],
        *,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[BusMessage]:
        deadline = time.monotonic() + block_ms / 1000.0
        collected: list[BusMessage] = []
        with self._not_empty:
            while True:
                for stream in streams:
                    queue = self._queues.get(stream)
                    while queue and len(collected) < count:
                        message = queue.popleft()
                        self._pending[message.id] = message
                        collected.append(message)
                if collected:
                    return collected
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._not_empty.wait(timeout=remaining)

    def ack(self, stream: str, group: str, message_ids: Sequence[str]) -> None:
        with self._lock:
            for message_id in message_ids:
                self._pending.pop(message_id, None)

    def nack(self, stream: str, group: str, message_ids: Sequence[str]) -> None:
        with self._not_empty:
            for message_id in message_ids:
                message = self._pending.pop(message_id, None)
                if message is not None:
                    message.attempt += 1
                    self._queues[message.stream].append(message)
            self._not_empty.notify()

    def dead_letter(self, stream: str, message: BusMessage, reason: str) -> None:
        with self._lock:
            self._pending.pop(message.id, None)
            self._dead.append(
                {"stream": stream, "reason": reason, "payload": message.payload}
            )
        logger.warning("dead-lettered message", extra={"stream": stream, "reason": reason})

    def depth(self) -> dict[str, int]:
        with self._lock:
            return {stream: len(queue) for stream, queue in self._queues.items()}
