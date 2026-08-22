"""Cached lookup from a Sparkplug address to the rows the ingest path needs.

Both the ingestor and the worker resolve every inbound message to an edge node
and, for device-level messages, to a device. Hitting the database per message
would cap throughput at database round-trip speed, so the mapping is cached
in-process with a short TTL - stale by at most ``WORKER["REGISTRY_CACHE_TTL_S"]``
seconds, which is acceptable for a registry that changes only when an operator
adds hardware.

The keys mirror the topic exactly: ``(group_id, edge_node_id)`` for a node and
``(node_pk, device_id)`` for a device. Resolving by anything else would mean the
lookup and the ACL could disagree about which row a topic refers to.
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
class EdgeNodeRef:
    pk: uuid.UUID
    node_id: str
    group_id: str
    organization_id: uuid.UUID
    site_id: uuid.UUID | None
    is_enabled: bool


@dataclass(frozen=True, slots=True)
class DeviceRef:
    """Everything the ingest path needs, without loading the full model."""

    pk: uuid.UUID
    device_id: str
    edge_node_id: uuid.UUID
    organization_id: uuid.UUID
    site_id: uuid.UUID | None
    device_type_id: uuid.UUID | None
    recording_policy_id: uuid.UUID | None
    is_enabled: bool


class DeviceRegistry:
    """Thread-safe TTL cache over the edge node and device tables."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl = ttl_seconds or settings.WORKER["REGISTRY_CACHE_TTL_S"]
        self._nodes: dict[tuple[str, str], EdgeNodeRef] = {}
        self._devices: dict[tuple[uuid.UUID, str], DeviceRef] = {}
        self._loaded_at = 0.0
        self._lock = threading.RLock()
        #: Addresses seen on the wire with no registry entry, for reporting.
        self._unknown: dict[str, int] = {}

    # ---- loading ---------------------------------------------------------
    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and (time.monotonic() - self._loaded_at) < self.ttl:
                return
            self._load()

    def _load(self) -> None:
        from apps.devices.models import Device, EdgeNode

        self._nodes = {
            (row[2], row[1]): EdgeNodeRef(
                pk=row[0],
                node_id=row[1],
                group_id=row[2],
                organization_id=row[3],
                site_id=row[4],
                is_enabled=row[5],
            )
            for row in EdgeNode.objects.filter(deleted_at__isnull=True).values_list(
                "id", "node_id", "group_id", "organization_id", "site_id", "is_enabled"
            )
        }
        self._devices = {
            (row[2], row[1]): DeviceRef(
                pk=row[0],
                device_id=row[1],
                edge_node_id=row[2],
                organization_id=row[3],
                site_id=row[4],
                device_type_id=row[5],
                recording_policy_id=row[6],
                is_enabled=row[7],
            )
            for row in Device.objects.filter(deleted_at__isnull=True).values_list(
                "id",
                "device_id",
                "edge_node_id",
                "organization_id",
                "site_id",
                "device_type_id",
                "recording_policy_id",
                "is_enabled",
            )
        }
        self._loaded_at = time.monotonic()
        logger.debug(
            "device registry loaded",
            extra={"nodes": len(self._nodes), "devices": len(self._devices)},
        )

    # ---- lookup ----------------------------------------------------------
    def get_node(self, group_id: str, node_id: str) -> EdgeNodeRef | None:
        key = (group_id, node_id)
        self.refresh()
        with self._lock:
            ref = self._nodes.get(key)
        if ref is None:
            # A node registered seconds ago would otherwise be rejected until
            # the TTL elapses, so force one reload before giving up.
            self.refresh(force=True)
            with self._lock:
                ref = self._nodes.get(key)
                if ref is None:
                    address = f"{group_id}/{node_id}"
                    self._unknown[address] = self._unknown.get(address, 0) + 1
        return ref

    def get_device(self, edge_node_pk: uuid.UUID, device_id: str) -> DeviceRef | None:
        key = (edge_node_pk, device_id)
        self.refresh()
        with self._lock:
            ref = self._devices.get(key)
        if ref is None:
            self.refresh(force=True)
            with self._lock:
                ref = self._devices.get(key)
                if ref is None:
                    self._unknown[device_id] = self._unknown.get(device_id, 0) + 1
        return ref

    def devices_of(self, edge_node_pk: uuid.UUID) -> list[DeviceRef]:
        """Every device on one node - what an NDEATH has to take offline."""
        self.refresh()
        with self._lock:
            return [
                ref for ref in self._devices.values() if ref.edge_node_id == edge_node_pk
            ]

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._devices)

    @property
    def node_count(self) -> int:
        with self._lock:
            return len(self._nodes)

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
