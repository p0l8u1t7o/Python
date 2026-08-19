"""Bus construction from Django settings."""

from __future__ import annotations

import threading

from django.conf import settings

from services.bus.base import BusError, MessageBus

_shared: MessageBus | None = None
_lock = threading.Lock()


def build_bus(backend: str | None = None) -> MessageBus:
    """Create a *new*, unconnected bus for the configured backend."""
    backend = (backend or settings.BUS_BACKEND).lower()

    if backend == "redis":
        from services.bus.redis_streams import RedisStreamBus

        return RedisStreamBus(
            settings.BUS["REDIS_URL"],
            max_stream_length=settings.BUS["MAX_STREAM_LENGTH"],
        )

    if backend in {"rabbitmq", "amqp"}:
        from services.bus.rabbitmq import RabbitMQBus

        return RabbitMQBus(settings.BUS["AMQP_URL"])

    if backend in {"memory", "inmemory", "local"}:
        from services.bus.memory import InMemoryBus

        return InMemoryBus()

    raise BusError(
        f"Unknown BUS_BACKEND '{backend}'. Expected one of: redis, rabbitmq, memory."
    )


def get_bus() -> MessageBus:
    """Process-wide connected bus.

    The in-memory backend depends on this being a singleton - producer and
    consumer must share the same object to see each other's messages.
    """
    global _shared
    if _shared is None:
        with _lock:
            if _shared is None:
                bus = build_bus()
                bus.connect()
                _shared = bus
    return _shared


def reset_bus() -> None:
    """Drop the shared instance; used by tests and by graceful shutdown."""
    global _shared
    with _lock:
        if _shared is not None:
            try:
                _shared.close()
            finally:
                _shared = None
