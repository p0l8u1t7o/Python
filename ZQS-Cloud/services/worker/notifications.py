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
    AlertEvent,
    AlertEventType,
    ChannelType,
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
        rank = EVENT_LEVEL_RANK.get(event.level, 0)
        for channel in channels:
            if channel.organization_id != event.organization_id:
                continue
            if rank < EVENT_LEVEL_RANK.get(channel.min_event_level, 4):
                continue
            deliveries.append(
                NotificationDelivery(event=event, channel=channel,
                                     status=DeliveryStatus.PENDING)
            )
    if deliveries:
        NotificationDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)
    return len(deliveries)


def _event_payload(delivery: NotificationDelivery) -> dict[str, Any]:
    event = delivery.event
    device = event.device
    return {
        "kind": "event",
        "event_id": event.pk,
        "organization_id": str(event.organization_id),
        "severity": event.level,
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
        "alert_id": str(alert.id),
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


def _notification_text(payload: dict[str, Any]) -> str:
    """One short human message, shared by email and LINE."""
    device = payload.get("device") or {}
    lines = [f"[{str(payload.get('severity', '')).upper()}] {payload.get('title', '')}"]
    if payload.get("message") and payload["message"] != payload.get("title"):
        lines.append(str(payload["message"]))
    place = " / ".join(
        str(part) for part in (device.get("site"), device.get("name")) if part
    )
    if place:
        lines.append(place)
    when = payload.get("started_at") or payload.get("ts")
    if when:
        lines.append(str(when))
    return "\n".join(lines)


def _send_email(config: dict[str, Any], payload: dict[str, Any]) -> None:
    from django.core.mail import send_mail

    recipients = config.get("recipients") or []
    if not recipients:
        raise ValueError("email channel has no recipients configured")
    subject = f"[{payload['severity'].upper()}] {payload['title']}"
    send_mail(
        subject, _notification_text(payload),
        config.get("from_email") or None, list(recipients),
    )


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

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        if response.status >= 300:
            raise ValueError(f"LINE API returned HTTP {response.status}")


_SENDERS = {
    ChannelType.WEBHOOK: _send_webhook,
    ChannelType.MQTT: _send_mqtt,
    ChannelType.EMAIL: _send_email,
    ChannelType.LINE: _send_line,
}


def dispatch_pending(limit: int = BATCH_SIZE) -> tuple[int, int]:
    """Send queued notifications. Returns ``(sent, failed)``."""
    pending = (
        NotificationDelivery.objects.filter(status=DeliveryStatus.PENDING)
        .select_related(
            "alert", "alert__device", "alert__device__site",
            "event", "event__device", "event__device__site", "channel",
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
                message=f"Notified via {channel.channel_type}",
            )

    return sent, failed
