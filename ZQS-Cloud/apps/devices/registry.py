"""Cached device lookup by MQTT ``device_id``.

Both the ingestor and the worker resolve every inbound message to a device.
Hitting the database per message would cap throughput at database round-trip
speed, so the mapping is cached in-process with a short TTL - stale by at most
``WORKER["REGISTRY_CACHE_TTL_S"]`` seconds, which is acceptable for a registry
that changes only when an operator adds hardware.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from django.conf import settings

from apps.core.logging import get_logger

logger = get_logger("devices.registry")


@dataclass(frozen=True, slots=True)
class DeviceRef:
    """Everything the ingest path needs, without loading the full model."""

    pk: uuid.UUID
    device_id: str
    organization_id: uuid.UUID
    site_id: uuid.UUID | None
    device_type_id: uuid.UUID | None
    recording_policy_id: uuid.UUID | None
    is_enabled: bool


class DeviceRegistry:
    """Thread-safe TTL cache over the device table."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl = ttl_seconds or settings.WORKER["REGISTRY_CACHE_TTL_S"]
        self._by_device_id: dict[str, DeviceRef] = {}
        self._loaded_at = 0.0
        self._lock = threading.RLock()
        #: device_ids seen on the wire with no registry entry, for reporting.
        self._unknown: dict[str, int] = {}

    # ---- loading ---------------------------------------------------------
    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and (time.monotonic() - self._loaded_at) < self.ttl:
                return
            self._load()

    def _load(self) -> None:
        from apps.devices.models import Device

        rows = Device.objects.filter(deleted_at__isnull=True).values_list(
            "id",
            "device_id",
            "organization_id",
            "site_id",
            "device_type_id",
            "recording_policy_id",
            "is_enabled",
        )
        self._by_device_id = {
            row[1]: DeviceRef(
                pk=row[0],
                device_id=row[1],
                organization_id=row[2],
                site_id=row[3],
                device_type_id=row[4],
                recording_policy_id=row[5],
                is_enabled=row[6],
            )
            for row in rows
        }
        self._loaded_at = time.monotonic()
        logger.debug("device registry loaded", extra={"count": len(self._by_device_id)})

    # ---- lookup ----------------------------------------------------------
    def get(self, device_id: str) -> DeviceRef | None:
        self.refresh()
        with self._lock:
            ref = self._by_device_id.get(device_id)
        if ref is None:
            # A device registered seconds ago would otherwise be rejected until
            # the TTL elapses, so force one reload before giving up.
            self.refresh(force=True)
            with self._lock:
                ref = self._by_device_id.get(device_id)
                if ref is None:
                    self._unknown[device_id] = self._unknown.get(device_id, 0) + 1
        return ref

    def contains(self, device_id: str) -> bool:
        self.refresh()
        with self._lock:
            return device_id in self._by_device_id

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._by_device_id)

    def unknown_devices(self) -> dict[str, int]:
        with self._lock:
            return dict(self._unknown)


_registry: DeviceRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> DeviceRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = DeviceRegistry()
    return _registry
