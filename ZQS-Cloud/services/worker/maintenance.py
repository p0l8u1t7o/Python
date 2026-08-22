"""Periodic housekeeping run by the worker.

These are the things nothing else will notice: a command whose device never
answered, and a device that stopped talking without sending a last will (power
cut, network drop - the broker's LWT only fires if the session ends cleanly
enough for the broker to notice).
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.utils import timezone

from apps.core.logging import get_logger
from apps.devices.models import (
    TERMINAL_COMMAND_STATUSES,
    Command,
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceStatusEvent,
)

logger = get_logger("worker.maintenance")


def expire_commands() -> int:
    """Close out commands whose deadline passed with no acknowledgement."""
    now = timezone.now()
    stale = Command.objects.filter(expires_at__lte=now).exclude(
        status__in=list(TERMINAL_COMMAND_STATUSES)
    )
    expired = list(stale.values_list("id", "device__device_id", "name"))
    if not expired:
        return 0

    stale.update(
        status=CommandStatus.EXPIRED,
        completed_at=now,
        error="Device did not acknowledge before the deadline",
    )
    for command_id, device_id, name in expired[:20]:
        logger.warning(
            "command expired",
            extra={"command_id": str(command_id), "device_id": device_id, "command": name},
        )
    return len(expired)


def mark_stale_devices_offline(grace_seconds: int | None = None) -> int:
    """Flip devices to offline when no uplink arrived within the grace window."""
    grace = grace_seconds or settings.DEVICE_OFFLINE_GRACE_SECONDS
    now = timezone.now()
    cutoff = now - dt.timedelta(seconds=grace)

    stale = Device.objects.filter(
        status=ConnectionStatus.ONLINE, deleted_at__isnull=True
    ).filter(last_seen_at__lt=cutoff)
    device_pks = list(stale.values_list("pk", flat=True))
    if not device_pks:
        return 0

    stale.update(status=ConnectionStatus.OFFLINE, status_changed_at=now)
    DeviceStatusEvent.objects.bulk_create(
        [
            DeviceStatusEvent(
                device_id=pk,
                status=ConnectionStatus.OFFLINE,
                previous_status=ConnectionStatus.ONLINE,
                reason="timeout",
                ts=now,
                payload={"grace_seconds": grace},
            )
            for pk in device_pks
        ]
    )
    logger.warning("devices marked offline by timeout", extra={"count": len(device_pks)})
    return len(device_pks)


def mark_stale_nodes_offline(grace_seconds: int | None = None) -> int:
    """Flip edge nodes to offline when nothing arrived on them in the grace
    window. An NDEATH can be lost (the will is discarded on a clean
    DISCONNECT, and a broker may drop a PUBLISH that a DISCONNECT follows
    too closely); without this sweep such a node reads "online" forever."""
    from apps.devices.models import EdgeNode

    grace = grace_seconds or settings.DEVICE_OFFLINE_GRACE_SECONDS
    now = timezone.now()
    cutoff = now - dt.timedelta(seconds=grace)
    stale = EdgeNode.objects.filter(
        status=ConnectionStatus.ONLINE, deleted_at__isnull=True, last_seen_at__lt=cutoff
    )
    count = stale.update(status=ConnectionStatus.OFFLINE, status_changed_at=now, last_seq=None)
    if count:
        logger.warning("edge nodes marked offline by timeout", extra={"count": count})
    return count


def run_maintenance_cycle() -> dict[str, int]:
    return {
        "commands_expired": expire_commands(),
        "devices_offline": mark_stale_devices_offline(),
        "nodes_offline": mark_stale_nodes_offline(),
    }
