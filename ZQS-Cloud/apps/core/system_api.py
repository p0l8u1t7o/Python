"""Platform health, capability discovery and i18n metadata."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.conf import settings
from django.db import connection
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
    name: str
    ok: bool
    detail: str = ""


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
    mqtt_topic_root: str
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
        components.append({"name": "database", "ok": True, "detail": connection.vendor})
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        components.append({"name": "database", "ok": False, "detail": str(exc)[:200]})

    try:
        from services.bus.factory import get_bus

        status = get_bus().health()
        components.append(
            {
                "name": "message_bus",
                "ok": bool(status.get("ok")),
                "detail": str(status.get("error", status.get("backend", ""))),
            }
        )
    except Exception as exc:  # noqa: BLE001
        components.append({"name": "message_bus", "ok": False, "detail": str(exc)[:200]})

    try:
        from services.mqtt.publisher import get_publisher

        client = get_publisher()
        components.append(
            {
                "name": "mqtt",
                "ok": client.is_connected,
                "detail": f"{settings.MQTT['HOST']}:{settings.MQTT['PORT']}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        components.append({"name": "mqtt", "ok": False, "detail": str(exc)[:200]})

    healthy = all(component["ok"] for component in components)
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
        "mqtt_topic_root": settings.MQTT["TOPIC_ROOT"],
        "bus_backend": settings.BUS_BACKEND,
        "database_engine": connection.vendor,
        "device_offline_grace_seconds": settings.DEVICE_OFFLINE_GRACE_SECONDS,
        "command_default_timeout_seconds": settings.COMMAND_DEFAULT_TIMEOUT_SECONDS,
        "max_page_size": settings.NINJA_PAGINATION_MAX_LIMIT,
    }


@router.get("/fleet", response=FleetStatsOut)
def fleet_stats(request):
    """Headline counts for the console's landing page."""
    from django.db.models import Count, Q

    from apps.alerts.models import Alert, AlertStatus
    from apps.devices.models import Site

    ctx: AuthContext = request.auth
    stats = Device.objects.filter(
        organization=ctx.organization, deleted_at__isnull=True
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
        "sites": Site.objects.filter(
            organization=ctx.organization, deleted_at__isnull=True
        ).count(),
        "open_alerts": Alert.objects.filter(organization=ctx.organization)
        .exclude(status=AlertStatus.RESOLVED)
        .count(),
    }
