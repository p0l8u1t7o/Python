"""Edge node lifecycle: provisioning, credentials, and rebirth requests.

An edge node is the thing that actually holds an MQTT session, so this is where
credentials live and where the host's two outbound control paths start.

Kept out of ``services.py`` because that module is about devices - what they
are allowed to do, what happens when one is replaced - while this is about
connections.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.audit.models import AuditAction
from apps.core.errors import PermissionDenied
from apps.core.logging import get_logger
from apps.devices.models import Device, EdgeNode, EdgeNodeCredential
from services.mqtt.publisher import PublishError, publish_bytes
from services.sparkplug import payload as sp
from services.sparkplug import topics

logger = get_logger("devices.edge_nodes")

#: How long to wait before asking the same node for another rebirth. A node
#: that is genuinely confused will produce a burst of bad sequence numbers, and
#: answering each one with its own request turns a hiccup into a storm.
REBIRTH_COOLDOWN = dt.timedelta(seconds=30)


@transaction.atomic
def implicit_node_for(
    *, organization, node_id: str, site=None, name: str = ""
) -> EdgeNode:
    """The node that carries a single directly-connected device.

    Created on demand so registering such a device stays a one-step operation
    for the operator, even though the model underneath now has two levels.
    """
    node, created = EdgeNode.objects.get_or_create(
        group_id=organization.slug,
        node_id=node_id,
        deleted_at__isnull=True,
        defaults={
            "organization": organization,
            "site": site,
            "name": name or node_id,
            "is_implicit": True,
        },
    )
    if created:
        logger.info(
            "implicit edge node created",
            extra={"node_id": node_id, "group_id": organization.slug},
        )
    return node


def issue_credential(node: EdgeNode) -> tuple[EdgeNodeCredential, str]:
    """Create or rotate the node's credential, returning the plaintext once."""
    return EdgeNodeCredential.issue(node)


def rotate_credential(ctx, node: EdgeNode) -> tuple[EdgeNodeCredential, str]:
    ctx.require("admin")
    credential, password = EdgeNodeCredential.issue(node)
    record(AuditAction.DEVICE_CREDENTIAL_ROTATED, ctx=ctx, target=node)
    logger.info("edge node credential rotated", extra={"node_id": node.node_id})
    return credential, password


def authenticate_edge_node(
    username: str, password: str, client_id: str = ""
) -> EdgeNode | None:
    """Backing check for the EMQX authentication webhook."""
    credential = (
        EdgeNodeCredential.objects.select_related("edge_node")
        .filter(mqtt_username=username, is_active=True)
        .first()
    )
    if credential is None or not credential.verify(password):
        return None
    if credential.allowed_client_id and client_id != credential.allowed_client_id:
        raise PermissionDenied("Client id does not match the pinned value")

    node = credential.edge_node
    if not node.is_enabled or node.deleted_at is not None:
        return None

    now = timezone.now()
    if (
        credential.last_auth_at is None
        or (now - credential.last_auth_at).total_seconds() > 60
    ):
        EdgeNodeCredential.objects.filter(pk=credential.pk).update(last_auth_at=now)
    return node


# ------------------------------------------------------------- rebirth ----
def _rebirth_payload(metric_name: str) -> bytes:
    message = sp.new_payload(timestamp=timezone.now())
    sp.add_metric(message, metric_name, True)
    return sp.encode(message)


def request_rebirth(node: EdgeNode, device: Device | None = None, *, reason: str = "") -> bool:
    """Ask a node, or one device on it, to re-announce all of its metrics.

    This is the specification's recovery path, and the only one there is. When
    a sequence gap says messages were lost, the alias table may no longer match
    what the publisher believes it published - so every later reading could be
    filed under the wrong metric. Guessing is not an option; asking is.

    Returns ``False`` when a request was suppressed by the cooldown.
    """
    now = timezone.now()
    if node.rebirth_requested_at and now - node.rebirth_requested_at < REBIRTH_COOLDOWN:
        return False

    if device is not None:
        topic = topics.device_command(node.group_id, node.node_id, device.device_id)
        message_type = topics.MessageType.DCMD
        body = _rebirth_payload(sp.DEVICE_REBIRTH_METRIC)
    else:
        topic = topics.node_command(node.group_id, node.node_id)
        message_type = topics.MessageType.NCMD
        body = _rebirth_payload(sp.NODE_REBIRTH_METRIC)

    qos, retain = topics.publish_options(message_type)
    try:
        publish_bytes(topic, body, qos=qos, retain=retain)
    except PublishError as exc:
        logger.warning(
            "rebirth request could not be published",
            extra={"node_id": node.node_id, "error": str(exc)[:200]},
        )
        return False

    EdgeNode.objects.filter(pk=node.pk).update(rebirth_requested_at=now)
    node.rebirth_requested_at = now
    logger.info(
        "rebirth requested",
        extra={
            "node_id": node.node_id,
            "device_id": device.device_id if device else "",
            "reason": reason,
        },
    )
    return True
