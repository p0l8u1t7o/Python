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
from apps.devices.edge_nodes import authenticate_edge_node
from apps.devices.models import EdgeNode
from services.sparkplug import topics

logger = get_logger("devices.emqx")

router = Router(tags=["emqx"])

ALLOW = {"result": "allow", "is_superuser": False}
DENY = {"result": "deny"}

#: What an edge node may publish, and what it may subscribe to. Sparkplug is
#: strict about the direction of each message type, and so is this: a node that
#: could publish NCMD could command its neighbours.
_PUBLISHABLE = frozenset(
    {
        topics.MessageType.NBIRTH,
        topics.MessageType.NDEATH,
        topics.MessageType.NDATA,
        topics.MessageType.DBIRTH,
        topics.MessageType.DDEATH,
        topics.MessageType.DDATA,
    }
)
_SUBSCRIBABLE = frozenset({topics.MessageType.NCMD, topics.MessageType.DCMD})

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
        node = authenticate_edge_node(
            payload.username, payload.password, client_id=payload.clientid
        )
    except Exception:  # noqa: BLE001 - never leak internals to the broker
        logger.exception(
            "edge node authentication error", extra={"username": payload.username}
        )
        return DENY

    if node is None:
        logger.info(
            "edge node authentication denied",
            extra={"username": payload.username, "peerhost": payload.peerhost},
        )
        return DENY
    return ALLOW


@router.post("/acl", response=WebhookOut, auth=None)
def emqx_acl(request, payload: AclIn):
    """Confine each edge node to its own Sparkplug address.

    Three things have to line up before a publish is allowed: the topic is
    inside the Sparkplug namespace, the ``(group_id, edge_node_id)`` in it
    belongs to the credential that authenticated, and the message type travels
    in the direction the specification says it does.

    The second check is the one that matters. Without it any valid credential
    could publish an NDEATH for a neighbouring node and take it off the air.
    """
    _check_token(request)

    action = payload.action.lower()
    parsed = (
        topics.parse_subscription(payload.topic)
        if action == "subscribe"
        else topics.parse(payload.topic)
    )
    if parsed is None:
        # STATE is the host's topic, not a node's, and nothing else in the
        # namespace is addressable by an edge node.
        return DENY

    owner = (
        EdgeNode.objects.filter(
            group_id=parsed.group_id,
            node_id=parsed.edge_node_id,
            deleted_at__isnull=True,
            is_enabled=True,
        )
        .values_list("credential__mqtt_username", flat=True)
        .first()
    )
    if not owner or owner != payload.username:
        logger.info(
            "acl denied: address does not belong to the caller",
            extra={"username": payload.username, "topic": payload.topic},
        )
        return DENY

    if action == "publish" and parsed.message_type in _PUBLISHABLE:
        return ALLOW
    if action == "subscribe" and parsed.message_type in _SUBSCRIBABLE:
        return ALLOW

    logger.info(
        "acl denied: message type not permitted in this direction",
        extra={
            "username": payload.username,
            "topic": payload.topic,
            "action": action,
        },
    )
    return DENY
