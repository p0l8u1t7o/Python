"""Message bus abstraction.

The MQTT ingestor must never block on a database write, so it hands validated
envelopes to a bus and returns immediately. Which bus is a deployment choice:
Redis Streams by default, RabbitMQ when one is already in the estate, or an
in-process queue for development and tests.

Implementations only have to provide at-least-once delivery with explicit
acknowledgement; consumers are written to be idempotent.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


class BusError(RuntimeError):
    """Transport failure. Callers decide whether to retry or shed load."""


@dataclass(slots=True)
class BusMessage:
    #: Broker-assigned identifier used to acknowledge the message.
    id: str
    stream: str
    payload: dict[str, Any]
    #: 1 on first delivery; higher when the message was reclaimed after a crash.
    attempt: int = 1
    raw: Any = field(default=None, repr=False)


class MessageBus(abc.ABC):
    """Minimal producer/consumer contract shared by every backend."""

    @abc.abstractmethod
    def connect(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        """Append one message and return its broker id."""

    def publish_many(self, stream: str, payloads: Iterable[dict[str, Any]]) -> list[str]:
        """Default implementation; backends may override with a pipeline."""
        return [self.publish(stream, payload) for payload in payloads]

    @abc.abstractmethod
    def ensure_group(self, streams: Sequence[str], group: str) -> None:
        """Create the consumer group if the backend needs one."""

    @abc.abstractmethod
    def consume(
        self,
        streams: Sequence[str],
        *,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[BusMessage]:
        """Fetch up to ``count`` messages, blocking at most ``block_ms``."""

    @abc.abstractmethod
    def ack(self, stream: str, group: str, message_ids: Sequence[str]) -> None: ...

    def nack(  # noqa: B027 - optional hook, the no-op default is correct
        self, stream: str, group: str, message_ids: Sequence[str]
    ) -> None:
        """Return messages for redelivery.

        Deliberately concrete rather than abstract: with Redis Streams an
        un-acked message already stays in the pending list and is picked up by
        :meth:`reclaim`, so doing nothing is the correct behaviour there.
        """

    def reclaim(
        self,
        streams: Sequence[str],
        *,
        group: str,
        consumer: str,
        min_idle_ms: int,
        count: int = 100,
    ) -> list[BusMessage]:
        """Take over messages abandoned by a dead consumer. Optional."""
        return []

    @abc.abstractmethod
    def dead_letter(self, stream: str, message: BusMessage, reason: str) -> None:
        """Park a message that failed too many times, for later inspection."""

    def health(self) -> dict[str, Any]:
        return {"backend": self.__class__.__name__, "ok": True}

    def __enter__(self) -> "MessageBus":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
