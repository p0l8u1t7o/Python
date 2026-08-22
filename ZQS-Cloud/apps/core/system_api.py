"""Platform health, capability discovery and i18n metadata."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.conf import settings
from django.db import connection

from services.sparkplug import topics as sp_topics
from ninja import Router, Schema

from apps.accounts.models import Theme
from apps.accounts.security import AuthContext
from apps.core.logging import get_logger
from apps.core.timeutils import now
from apps.devices.models import ConnectionStatus, Device

router = Router(tags=["system"])
logger = get_logger("core.system")

_STARTED_AT = now()


class ComponentHealth(Schema):
    """One dependency's state.

    ``ok`` answers "is this a problem?", which is not the same as "is it
    connected". A dependency this deployment deliberately does not use is not
    a problem, and reporting it as one trains people to ignore the health
    card - see ``state``.
    """

    name: str
    ok: bool
    detail: str = ""
    #: ``ok`` | ``error`` | ``disabled``
    state: str = "ok"
    #: False when the deployment is configured without this dependency, so it
    #: does not count towards the overall verdict.
    required: bool = True


class HealthOut(Schema):
    status: str
    version: str
    uptime_seconds: int
    server_time: dt.datetime
    components: list[ComponentHealth]


class LanguageOut(Schema):
    code: str
    name: str


class CapabilitiesOut(Schema):
    """Everything the SPA needs to configure itself on first load."""

    languages: list[LanguageOut]
    default_language: str
    themes: list[str]
    sparkplug_namespace: str = ""
    sparkplug_host_id: str = ""
    #: False when this deployment runs without a broker - the console uses it
    #: to explain why live values are not moving, instead of showing an alarm.
    mqtt_enabled: bool = True
    bus_backend: str
    database_engine: str
    device_offline_grace_seconds: int
    command_default_timeout_seconds: int
    max_page_size: int


class FleetStatsOut(Schema):
    total_devices: int
    online: int
    offline: int
    unknown: int
    disabled: int
    sites: int
    open_alerts: int


@router.get("/health", response=HealthOut, auth=None)
def health(request):
    """Readiness probe: reports each dependency instead of a bare 200/500."""
    components: list[dict[str, Any]] = []

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        components.append(
            {"name": "database", "ok": True, "state": "ok", "detail": connection.vendor}
        )
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        components.append(
            {"name": "database", "ok": False, "state": "error", "detail": str(exc)[:200]}
        )

    try:
        from services.bus.factory import get_bus

        status = get_bus().health()
        healthy_bus = bool(status.get("ok"))
        components.append(
            {
                "name": "message_bus",
                "ok": healthy_bus,
                "state": "ok" if healthy_bus else "error",
                "detail": str(status.get("error", status.get("backend", ""))),
            }
        )
    except Exception as exc:  # noqa: BLE001
        components.append(
            {
                "name": "message_bus",
                "ok": False,
                "state": "error",
                "detail": str(exc)[:200],
            }
        )

    endpoint = f"{settings.MQTT['HOST']}:{settings.MQTT['PORT']}"
    if not settings.MQTT.get("ENABLED", True):
        # Not an incident: this deployment was configured without a broker.
        # Connecting anyway just to report the failure would also cost a
        # ten-second timeout on every health poll.
        components.append(
            {
                "name": "mqtt",
                "ok": True,
                "state": "disabled",
                "required": False,
                "detail": "MQTT_ENABLED=0",
            }
        )
    else:
        try:
            from services.mqtt.publisher import get_publisher

            client = get_publisher()
            connected = client.is_connected
            components.append(
                {
                    "name": "mqtt",
                    "ok": connected,
                    "state": "ok" if connected else "error",
                    "detail": endpoint,
                }
            )
        except Exception as exc:  # noqa: BLE001
            components.append(
                {
                    "name": "mqtt",
                    "ok": False,
                    "state": "error",
                    "detail": str(exc)[:200],
                }
            )

    healthy = all(
        component["ok"] for component in components if component.get("required", True)
    )
    return {
        "status": "ok" if healthy else "degraded",
        "version": getattr(settings, "APP_VERSION", "1.0.0"),
        "uptime_seconds": int((now() - _STARTED_AT).total_seconds()),
        "server_time": now(),
        "components": components,
    }


@router.get("/capabilities", response=CapabilitiesOut, auth=None)
def capabilities(request):
    return {
        "languages": [{"code": code, "name": name} for code, name in settings.LANGUAGES],
        "default_language": settings.LANGUAGE_CODE,
        "themes": list(Theme.values),
        "sparkplug_namespace": sp_topics.NAMESPACE,
        "sparkplug_host_id": settings.SPARKPLUG["HOST_ID"],
        "mqtt_enabled": bool(settings.MQTT.get("ENABLED", True)),
        "bus_backend": settings.BUS_BACKEND,
        "database_engine": connection.vendor,
        "device_offline_grace_seconds": settings.DEVICE_OFFLINE_GRACE_SECONDS,
        "command_default_timeout_seconds": settings.COMMAND_DEFAULT_TIMEOUT_SECONDS,
        "max_page_size": settings.NINJA_PAGINATION_MAX_LIMIT,
    }


@router.get("/timezones", response=list[str], auth=None)
def timezones(request):
    """IANA zone names this server can actually resolve.

    Read from ``zoneinfo`` rather than shipped as a constant, because the list
    that matters is the one the *server* will accept - a console offering a
    zone this Python cannot load would let an operator pick a value that then
    fails validation on save.

    Filtered to ``Area/Location`` names: the flat aliases (``EST``, ``UTC+8``,
    ``posix/...``) are legacy and would triple the length of a dropdown for no
    benefit. ``UTC`` is kept because it is a real answer.
    """
    import zoneinfo

    names = sorted(
        name
        for name in zoneinfo.available_timezones()
        if "/" in name and not name.startswith(("posix/", "right/", "SystemV/"))
    )
    return ["UTC", *names]


@router.get("/fleet", response=FleetStatsOut)
def fleet_stats(request):
    """Headline counts for the console's landing page."""
    from django.db.models import Count, Q

    from apps.alerts.models import Alert, AlertStatus
    from apps.devices.models import Site

    ctx: AuthContext = request.auth
    stats = ctx.scope_queryset(
        Device.objects.filter(organization=ctx.organization, deleted_at__isnull=True)
    ).aggregate(
        total=Count("id"),
        online=Count("id", filter=Q(status=ConnectionStatus.ONLINE)),
        offline=Count("id", filter=Q(status=ConnectionStatus.OFFLINE)),
        unknown=Count("id", filter=Q(status=ConnectionStatus.UNKNOWN)),
        disabled=Count("id", filter=Q(is_enabled=False)),
    )
    return {
        "total_devices": stats["total"] or 0,
        "online": stats["online"] or 0,
        "offline": stats["offline"] or 0,
        "unknown": stats["unknown"] or 0,
        "disabled": stats["disabled"] or 0,
        "sites": ctx.scope_queryset(
            Site.objects.filter(
                organization=ctx.organization, deleted_at__isnull=True
            ),
            field="id",
        ).count(),
        "open_alerts": ctx.scope_queryset(
            Alert.objects.filter(organization=ctx.organization).exclude(
                status=AlertStatus.RESOLVED
            ),
            field="device__site_id",
        ).count(),
    }
