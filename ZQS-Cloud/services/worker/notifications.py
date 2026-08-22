"""Alert notification delivery.

The rule engine only writes ``NotificationDelivery`` rows; sending happens here.
Persisting the intent first means a crash between "alert fired" and "operator
notified" is recoverable, and retries are bounded and visible.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

import orjson
from django.utils import timezone

from apps.alerts.models import (
    SEVERITY_RANK,
    AlertEvent,
    AlertEventType,
    ChannelType,
    DeliveryPhase,
    DeliveryStatus,
    NotificationDelivery,
)
from apps.core.logging import get_logger

logger = get_logger("worker.notifications")

MAX_ATTEMPTS = 5
BATCH_SIZE = 50
REQUEST_TIMEOUT = 10.0


#: Device-event levels, ordered. Kept here beside the queueing logic that
#: compares them; the model stores the labels.
EVENT_LEVEL_RANK = {
    "debug": 0, "info": 1, "notice": 2, "warning": 3, "error": 4, "critical": 5,
}


def queue_alert_notifications(alert, channel_ids, *, phase: str = DeliveryPhase.RAISED) -> int:
    """Queue one delivery per subscribed channel for an alert, raised or
    resolved. The severity gate is the alert's own severity in both phases:
    whoever was told it fired is told it cleared, nobody else."""
    from apps.alerts.models import NotificationChannel

    if not channel_ids:
        return 0
    channels = NotificationChannel.objects.filter(
        id__in=channel_ids, is_enabled=True, notify_alerts=True
    )
    deliveries = [
        NotificationDelivery(alert=alert, channel=channel, phase=phase,
                             status=DeliveryStatus.PENDING)
        for channel in channels
        if SEVERITY_RANK.get(alert.severity, 0) >= SEVERITY_RANK.get(channel.min_severity, 0)
    ]
    if deliveries:
        NotificationDelivery.objects.bulk_create(deliveries)
    return len(deliveries)


def queue_event_notifications(events) -> int:
    """Queue deliveries for device events on channels subscribed to them.

    Called right after the ingest pipeline persists a batch of events. Same
    persist-first contract as alerts: the intent is written before any network
    is touched, so a crash between "event stored" and "operator notified" is
    recoverable.
    """
    from apps.alerts.models import NotificationChannel

    events = [e for e in events if e.pk is not None]
    if not events:
        return 0

    org_ids = {event.organization_id for event in events}
    channels = list(
        NotificationChannel.objects.filter(
            organization_id__in=org_ids, is_enabled=True, notify_events=True
        )
    )
    if not channels:
        return 0

    deliveries = []
    for event in events:
        payload = event.payload or {}
        # A cleared alarm is logged at "info" (clearing is not an error), but
        # it must reach the same channels the raise reached, so the gate uses
        # the level the alarm was raised at.
        gate_level = payload.get("alarm_level") if payload.get("alarm_state") == "cleared" else event.level
        rank = EVENT_LEVEL_RANK.get(gate_level or event.level, 0)
        for channel in channels:
            if channel.organization_id != event.organization_id:
                continue
            if rank < EVENT_LEVEL_RANK.get(channel.min_event_level, 4):
                continue
            deliveries.append(
                NotificationDelivery(
                    event=event, channel=channel, status=DeliveryStatus.PENDING,
                    phase=(
                        DeliveryPhase.RESOLVED
                        if payload.get("alarm_state") == "cleared"
                        else DeliveryPhase.RAISED
                    ),
                )
            )
    if deliveries:
        NotificationDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)
    return len(deliveries)


def _event_payload(delivery: NotificationDelivery) -> dict[str, Any]:
    event = delivery.event
    device = event.device
    return {
        "kind": "event",
        "phase": delivery.phase,
        "alarm_state": (event.payload or {}).get("alarm_state"),
        "event_id": event.pk,
        "organization_id": str(event.organization_id),
        "timezone": getattr(event.organization, "default_timezone", "") or "UTC",
        # A cleared alarm is logged at info; the message still names the
        # severity it was raised at, so "what cleared" is unambiguous.
        "severity": (event.payload or {}).get("alarm_level") or event.level,
        "title": f"[{device.name or device.device_id}] {event.code or event.level}",
        "message": event.message,
        "code": event.code,
        "ts": event.ts.isoformat(),
        "payload": event.payload,
        "device": {
            "id": str(device.id),
            "device_id": device.device_id,
            "name": device.name,
            "site": device.site.name if device.site_id else None,
        },
    }


def build_payload(delivery: NotificationDelivery) -> dict[str, Any]:
    if delivery.event_id is not None:
        return _event_payload(delivery)
    alert = delivery.alert
    device = alert.device
    return {
        "kind": "alert",
        "phase": delivery.phase,
        "alert_id": str(alert.id),
        "timezone": getattr(alert.organization, "default_timezone", "") or "UTC",
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "resolve_note": alert.resolve_note,
        "organization_id": str(alert.organization_id),
        "severity": alert.severity,
        "status": alert.status,
        "source": alert.source,
        "title": alert.title,
        "message": alert.message,
        "metric": alert.metric_key,
        "code": alert.code,
        "value": alert.trigger_value,
        "threshold": alert.threshold,
        "started_at": alert.started_at.isoformat(),
        "occurrence_count": alert.occurrence_count,
        "device": {
            "id": str(device.id),
            "device_id": device.device_id,
            "name": device.name,
            "site": device.site.name if device.site_id else None,
        }
        if device is not None
        else None,
    }


def _send_webhook(config: dict[str, Any], payload: dict[str, Any]) -> None:
    url = config.get("url")
    if not url:
        raise ValueError("webhook channel has no 'url' configured")
    if not url.startswith(("http://", "https://")):
        raise ValueError("webhook url must be http(s)")

    body = orjson.dumps(payload)
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "ZQS-Cloud/1.0")
    for key, value in (config.get("headers") or {}).items():
        request.add_header(str(key), str(value))

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        if response.status >= 300:
            raise ValueError(f"webhook returned HTTP {response.status}")


def _send_mqtt(config: dict[str, Any], payload: dict[str, Any]) -> None:
    from services.mqtt.publisher import publish_json

    topic = config.get("topic")
    if not topic:
        raise ValueError("mqtt channel has no 'topic' configured")
    publish_json(topic, payload, qos=config.get("qos", 1), retain=bool(config.get("retain")))


#: First line of every message. Bilingual on purpose: the channel has no
#: notion of the recipient's language, and "發生 / 解除" is the one word the
#: recipient has to be able to tell apart at a glance.
PHASE_HEADLINE = {
    DeliveryPhase.RAISED: "🔴 發生 RAISED",
    DeliveryPhase.RESOLVED: "🟢 解除 RESOLVED",
}


def _phase_of(payload: dict[str, Any]) -> str:
    phase = payload.get("phase")
    if phase in (DeliveryPhase.RAISED, DeliveryPhase.RESOLVED):
        return phase
    if payload.get("alarm_state") == "cleared" or payload.get("status") == "resolved":
        return DeliveryPhase.RESOLVED
    return DeliveryPhase.RAISED


def _duration_text(start: str | None, end: str | None) -> str:
    if not start or not end:
        return ""
    try:
        import datetime as dt

        seconds = (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return ""
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{int(seconds // 60)} min"
    return f"{seconds / 3600:.1f} h"


def _local_time(iso: str | None, zone_name: str | None) -> str:
    """An ISO timestamp as the recipient's wall clock, e.g. ``2026-08-22 19:55``."""
    if not iso:
        return ""
    try:
        import datetime as dt
        import zoneinfo

        moment = dt.datetime.fromisoformat(str(iso))
        zone = zoneinfo.ZoneInfo(zone_name or "UTC")
        return moment.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001 - never let formatting block a notification
        return str(iso)


def _notification_text(payload: dict[str, Any]) -> str:
    """One short human message, shared by email and LINE.

    The first line says whether this is the alarm firing or clearing; the
    severity and title follow. Two messages about the same alarm must never
    read the same.
    """
    device = payload.get("device") or {}
    phase = _phase_of(payload)
    lines = [
        "🔔 測試 TEST" if payload.get("kind") == "test" else PHASE_HEADLINE[phase],
        f"[{str(payload.get('severity', '')).upper()}] {payload.get('title', '')}",
    ]
    if payload.get("message") and payload["message"] != payload.get("title"):
        lines.append(str(payload["message"]))
    place = " / ".join(
        str(part) for part in (device.get("site"), device.get("name")) if part
    )
    if place:
        lines.append(place)
    if phase == DeliveryPhase.RESOLVED:
        when = payload.get("resolved_at") or payload.get("ts")
        lasted = _duration_text(payload.get("started_at"), payload.get("resolved_at"))
        if when:
            lines.append(f"解除時間 {_local_time(when, payload.get('timezone'))}" + (f"（持續 {lasted}）" if lasted else ""))
        if payload.get("resolve_note"):
            lines.append(str(payload["resolve_note"]))
    else:
        when = payload.get("started_at") or payload.get("ts")
        if when:
            lines.append(f"發生時間 {_local_time(when, payload.get('timezone'))}")
    return "\n".join(lines)


def _smtp_connection(config: dict[str, Any]):
    """The SMTP connection for one channel.

    Per-channel SMTP settings win; the server-wide ``EMAIL_*`` settings are
    the fallback. With neither configured this **refuses** rather than
    falling through to Django's console backend: that backend reports
    success while printing the mail to a log nobody is reading, which is
    how an email channel sat at "sent" for weeks without delivering once.
    """
    from django.conf import settings
    from django.core.mail import get_connection

    host = (config.get("smtp_host") or "").strip()
    if host:
        port = int(config.get("smtp_port") or 587)
        use_ssl = bool(config.get("smtp_use_ssl"))
        use_tls = bool(config.get("smtp_use_tls", not use_ssl)) and not use_ssl
        return get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host,
            port=port,
            username=(config.get("smtp_username") or "") or None,
            password=(config.get("smtp_password") or "") or None,
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout=REQUEST_TIMEOUT,
        )
    if settings.EMAIL_HOST:
        return get_connection(timeout=REQUEST_TIMEOUT)
    raise ValueError(
        "No SMTP server configured: set the channel's SMTP settings, or "
        "EMAIL_HOST in the server environment"
    )


def _send_email(config: dict[str, Any], payload: dict[str, Any]) -> None:
    from django.conf import settings
    from django.core.mail import EmailMessage

    recipients = config.get("recipients") or []
    if not recipients:
        raise ValueError("email channel has no recipients configured")
    if payload.get("kind") == "test":
        phase_tag = "測試"
    else:
        phase_tag = "解除" if _phase_of(payload) == DeliveryPhase.RESOLVED else "發生"
    subject = f"[{phase_tag}][{payload['severity'].upper()}] {payload['title']}"
    sender = (
        config.get("from_email")
        or config.get("smtp_username")
        or settings.DEFAULT_FROM_EMAIL
    )
    where = (
        f"{config.get('smtp_host')}:{config.get('smtp_port') or 587}"
        if config.get("smtp_host")
        else f"{settings.EMAIL_HOST}:{settings.EMAIL_PORT}"
    )
    try:
        with _smtp_connection(config) as connection:
            EmailMessage(
                subject, _notification_text(payload), sender, list(recipients),
                connection=connection,
            ).send(fail_silently=False)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - smtplib and sockets raise their own hierarchies
        # Name the server: "connection refused" alone sends people checking
        # the recipient address instead of the host and port.
        raise ValueError(f"SMTP {where}: {exc}") from exc


def _send_line(config: dict[str, Any], payload: dict[str, Any]) -> None:
    """Push to a LINE chat through the Messaging API (a LINE bot).

    LINE Notify was retired in 2025; a bot with a channel access token pushing
    to a user/group ID is the supported way in.
    """
    token = config.get("channel_access_token")
    to = config.get("to")
    if not token or not to:
        raise ValueError("line channel needs 'channel_access_token' and 'to'")

    body = orjson.dumps(
        {"to": to, "messages": [{"type": "text",
                                 "text": _notification_text(payload)[:4900]}]}
    )
    request = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push", data=body, method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            if response.status >= 300:
                raise ValueError(f"LINE API returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        # LINE answers with a JSON body that says what was wrong; "HTTP 401"
        # on its own sent people looking at the network instead of the token.
        detail = ""
        try:
            body = orjson.loads(exc.read() or b"{}")
            detail = str(body.get("message") or "")
            for item in body.get("details") or []:
                if item.get("message"):
                    detail += f"; {item.get('property', '')}: {item['message']}"
        except Exception:  # noqa: BLE001 - the body is best-effort
            pass
        hint = {
            401: "the channel access token is invalid or expired (Messaging API "
                 "channel > Messaging API > channel access token)",
            400: "check 'to': it must be a user ID (U...), group ID (C...) or "
                 "room ID (R...) from the Messaging API, not a display name",
            403: "the bot is not allowed to push to this recipient (the user "
                 "must add the bot as a friend, or the bot must be in the group)",
            429: "LINE rate limit reached",
        }.get(exc.code, "")
        message = f"LINE API HTTP {exc.code}"
        if detail:
            message += f": {detail}"
        if hint:
            message += f" - {hint}"
        raise ValueError(message) from exc


_SENDERS = {
    ChannelType.WEBHOOK: _send_webhook,
    ChannelType.MQTT: _send_mqtt,
    ChannelType.EMAIL: _send_email,
    ChannelType.LINE: _send_line,
}


def test_payload(organization_name: str, channel_name: str) -> dict[str, Any]:
    """What a test send looks like on the other end: clearly a test, with
    enough context to tell which channel of which tenant it came from."""
    now = timezone.now()
    return {
        "kind": "test",
        "severity": "info",
        "title": f"ZQS Cloud test notification ({channel_name})",
        "message": (
            f"This is a test from {organization_name}. If you can read this, "
            f"the channel '{channel_name}' is configured correctly."
        ),
        "device": None,
        "ts": now.isoformat(),
    }


def send_test(channel_type: str, config: dict[str, Any], payload: dict[str, Any]) -> None:
    """Send one message synchronously; raises ``ValueError`` with a readable
    reason on failure. Used by the settings page's test button."""
    sender = _SENDERS.get(channel_type)
    if sender is None:
        raise ValueError(f"unsupported channel type {channel_type}")
    try:
        sender(config or {}, payload)
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc


def dispatch_pending(limit: int = BATCH_SIZE) -> tuple[int, int]:
    """Send queued notifications. Returns ``(sent, failed)``."""
    pending = (
        NotificationDelivery.objects.filter(status=DeliveryStatus.PENDING)
        .select_related(
            "alert", "alert__device", "alert__device__site", "alert__organization",
            "event", "event__device", "event__device__site", "event__organization", "channel",
        )
        .order_by("created_at")[:limit]
    )

    sent = failed = 0
    for delivery in pending:
        channel = delivery.channel
        delivery.attempts += 1

        if not channel.is_enabled:
            delivery.status = DeliveryStatus.SKIPPED
            delivery.last_error = "channel disabled"
            delivery.save(update_fields=["status", "attempts", "last_error", "updated_at"])
            continue

        sender = _SENDERS.get(channel.channel_type)
        if sender is None:
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error = f"unsupported channel type {channel.channel_type}"
            delivery.save(update_fields=["status", "attempts", "last_error", "updated_at"])
            failed += 1
            continue

        try:
            sender(channel.config or {}, build_payload(delivery))
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            failed += 1
            delivery.last_error = str(exc)[:500]
            # Keep retrying until the attempt budget is spent, then give up.
            delivery.status = (
                DeliveryStatus.FAILED
                if delivery.attempts >= MAX_ATTEMPTS
                else DeliveryStatus.PENDING
            )
            delivery.save(update_fields=["status", "attempts", "last_error", "updated_at"])
            logger.warning(
                "notification delivery failed",
                extra={
                    "channel": channel.name,
                    "attempt": delivery.attempts,
                    "error": delivery.last_error,
                },
            )
            continue

        sent += 1
        delivery.status = DeliveryStatus.SENT
        delivery.delivered_at = timezone.now()
        delivery.last_error = ""
        delivery.save(
            update_fields=["status", "attempts", "delivered_at", "last_error", "updated_at"]
        )
        # The audit line on the alert only exists for alert deliveries; a
        # device event has no alert to attach it to.
        if delivery.alert_id is not None:
            AlertEvent.objects.create(
                alert=delivery.alert,
                event_type=AlertEventType.NOTIFIED,
                actor_label=f"channel:{channel.name}",
                message=f"Notified via {channel.channel_type} ({delivery.phase})",
            )

    return sent, failed
