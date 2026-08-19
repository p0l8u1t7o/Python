"""EMQX HTTP authentication and ACL webhooks.

Point EMQX at these endpoints so device credentials live in this database
instead of in the broker's config, and so a device disabled in the console
loses broker access immediately.

EMQX 5 configuration sketch::

    authentication = [{
      mechanism = password_based
      backend = http
      method = post
      url = "https://api.example.com/api/emqx/auth"
      headers { "X-EMQX-Token" = "<EMQX_WEBHOOK_TOKEN>" }
      body { username = "${username}", password = "${password}",
             clientid = "${clientid}", peerhost = "${peerhost}" }
    }]

    authorization.sources = [{
      type = http
      method = post
      url = "https://api.example.com/api/emqx/acl"
      headers { "X-EMQX-Token" = "<EMQX_WEBHOOK_TOKEN>" }
      body { username = "${username}", clientid = "${clientid}",
             topic = "${topic}", action = "${action}" }
    }]

Both endpoints are unauthenticated as far as the API's own JWT layer is
concerned; the shared token header is what proves the caller is the broker.
"""

from __future__ import annotations

import hmac

from django.conf import settings
from ninja import Router, Schema

from apps.core.errors import AuthenticationError
from apps.core.logging import get_logger
from apps.devices.models import Device
from apps.devices.services import authenticate_device
from services.mqtt import topics

logger = get_logger("devices.emqx")

router = Router(tags=["emqx"])

ALLOW = {"result": "allow", "is_superuser": False}
DENY = {"result": "deny"}

#: Topic suffixes a device may publish to.
_PUBLISHABLE = {topics.TELEMETRY, topics.STATUS, topics.EVENT, topics.ALARM, topics.CONTROL_ACK}
#: Topic suffixes a device may subscribe to.
_SUBSCRIBABLE = {topics.CONTROL}


class AuthIn(Schema):
    username: str = ""
    password: str = ""
    clientid: str = ""
    peerhost: str = ""


class AclIn(Schema):
    username: str = ""
    clientid: str = ""
    topic: str = ""
    action: str = ""


class WebhookOut(Schema):
    result: str
    is_superuser: bool = False


def _check_token(request) -> None:
    expected = settings.EMQX_WEBHOOK_TOKEN
    if not expected:
        raise AuthenticationError(
            "EMQX webhooks are disabled; set EMQX_WEBHOOK_TOKEN to enable them",
            code="emqx_webhook_disabled",
        )
    presented = request.headers.get("X-EMQX-Token", "")
    if not hmac.compare_digest(presented, expected):
        raise AuthenticationError("Invalid EMQX webhook token", code="emqx_token_invalid")


@router.post("/auth", response=WebhookOut, auth=None)
def emqx_auth(request, payload: AuthIn):
    """Password check for a connecting device."""
    _check_token(request)

    if not payload.username or not payload.password:
        return DENY

    try:
        device = authenticate_device(
            payload.username, payload.password, client_id=payload.clientid
        )
    except Exception:  # noqa: BLE001 - never leak internals to the broker
        logger.exception("device authentication error", extra={"username": payload.username})
        return DENY

    if device is None:
        logger.info(
            "device authentication denied",
            extra={"username": payload.username, "peerhost": payload.peerhost},
        )
        return DENY
    return ALLOW


@router.post("/acl", response=WebhookOut, auth=None)
def emqx_acl(request, payload: AclIn):
    """Confine each device to its own topic subtree."""
    _check_token(request)

    parsed_device_id = _device_id_from_topic(payload.topic)
    if parsed_device_id is None:
        return DENY

    owner = (
        Device.objects.filter(
            device_id=parsed_device_id, deleted_at__isnull=True, is_enabled=True
        )
        .values_list("credential__mqtt_username", flat=True)
        .first()
    )
    # The topic's device must be the one whose credential authenticated.
    if not owner or owner != payload.username:
        logger.info(
            "acl denied: topic does not belong to the caller",
            extra={"username": payload.username, "topic": payload.topic},
        )
        return DENY

    suffix = _suffix_from_topic(payload.topic)
    action = payload.action.lower()
    if action == "publish" and suffix in _PUBLISHABLE:
        return ALLOW
    if action == "subscribe" and suffix in _SUBSCRIBABLE:
        return ALLOW

    logger.info(
        "acl denied: action not permitted on topic",
        extra={"username": payload.username, "topic": payload.topic, "action": action},
    )
    return DENY


def _split_topic(topic: str) -> tuple[str, str] | None:
    root = topics.root()
    if not topic.startswith(root + "/"):
        return None
    parts = topic[len(root) + 1 :].split("/")
    if len(parts) < 2 or not parts[0]:
        return None
    return parts[0], "/".join(parts[1:])


def _device_id_from_topic(topic: str) -> str | None:
    split = _split_topic(topic)
    return split[0] if split else None


def _suffix_from_topic(topic: str) -> str:
    split = _split_topic(topic)
    return split[1] if split else ""
