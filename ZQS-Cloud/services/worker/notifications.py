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


def build_payload(delivery: NotificationDelivery) -> dict[str, Any]:
    alert = delivery.alert
    device = alert.device
    return {
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


def _send_email(config: dict[str, Any], payload: dict[str, Any]) -> None:
    from django.core.mail import send_mail

    recipients = config.get("recipients") or []
    if not recipients:
        raise ValueError("email channel has no recipients configured")
    subject = f"[{payload['severity'].upper()}] {payload['title']}"
    body = payload["message"] or payload["title"]
    send_mail(subject, body, config.get("from_email") or None, list(recipients))


_SENDERS = {
    ChannelType.WEBHOOK: _send_webhook,
    ChannelType.MQTT: _send_mqtt,
    ChannelType.EMAIL: _send_email,
}


def dispatch_pending(limit: int = BATCH_SIZE) -> tuple[int, int]:
    """Send queued notifications. Returns ``(sent, failed)``."""
    pending = (
        NotificationDelivery.objects.filter(status=DeliveryStatus.PENDING)
        .select_related("alert", "alert__device", "alert__device__site", "channel")
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
        AlertEvent.objects.create(
            alert=delivery.alert,
            event_type=AlertEventType.NOTIFIED,
            actor_label=f"channel:{channel.name}",
            message=f"Notified via {channel.channel_type}",
        )

    return sent, failed
