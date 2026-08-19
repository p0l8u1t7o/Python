"""Device-facing domain services: downlink commands and credentials."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import ROLE_RANK
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, PermissionDenied, ServiceUnavailable
from apps.core.errors import ValidationError
from apps.core.logging import get_logger
from apps.devices.models import (
    TERMINAL_COMMAND_STATUSES,
    Command,
    CommandStatus,
    Device,
    DeviceCredential,
)
from services.mqtt import topics
from services.mqtt.publisher import PublishError, publish_json

logger = get_logger("devices.services")


# --------------------------------------------------------------------------
# Parameter validation
# --------------------------------------------------------------------------
def validate_params(schema: dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any]:
    """Validate command parameters against the blueprint's mini JSON-Schema.

    A deliberately small subset - ``type``, ``required``, ``properties``,
    ``enum``, ``minimum``, ``maximum`` - which covers every command shape a
    device blueprint needs without pulling in a schema library.
    """
    if not schema:
        return params
    if schema.get("type") not in (None, "object"):
        raise ValidationError("Command schema must describe an object", code="bad_schema")

    properties: dict[str, Any] = schema.get("properties") or {}
    required: list[str] = schema.get("required") or []

    missing = [name for name in required if name not in params]
    if missing:
        raise ValidationError(
            f"Missing required parameter(s): {', '.join(missing)}",
            code="missing_parameter",
            details={"missing": missing},
        )

    unexpected = [name for name in params if name not in properties] if properties else []
    if unexpected:
        raise ValidationError(
            f"Unknown parameter(s): {', '.join(unexpected)}",
            code="unknown_parameter",
            details={"unknown": unexpected, "allowed": sorted(properties)},
        )

    cleaned: dict[str, Any] = {}
    for name, value in params.items():
        cleaned[name] = _validate_value(name, value, properties.get(name) or {})
    return cleaned


def _validate_value(name: str, value: Any, spec: dict[str, Any]) -> Any:
    expected = spec.get("type")

    if expected == "boolean":
        if not isinstance(value, bool):
            raise ValidationError(f"'{name}' must be a boolean", code="bad_parameter_type")
        return value

    if expected in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"'{name}' must be a number", code="bad_parameter_type")
        if expected == "integer" and int(value) != value:
            raise ValidationError(f"'{name}' must be an integer", code="bad_parameter_type")
        minimum, maximum = spec.get("minimum"), spec.get("maximum")
        if minimum is not None and value < minimum:
            raise ValidationError(
                f"'{name}' must be >= {minimum}", code="parameter_out_of_range"
            )
        if maximum is not None and value > maximum:
            raise ValidationError(
                f"'{name}' must be <= {maximum}", code="parameter_out_of_range"
            )
        return int(value) if expected == "integer" else float(value)

    if expected == "string":
        if not isinstance(value, str):
            raise ValidationError(f"'{name}' must be a string", code="bad_parameter_type")
        choices = spec.get("enum")
        if choices and value not in choices:
            raise ValidationError(
                f"'{name}' must be one of: {', '.join(map(str, choices))}",
                code="parameter_not_allowed",
                details={"allowed": choices},
            )
        return value

    choices = spec.get("enum")
    if choices and value not in choices:
        raise ValidationError(
            f"'{name}' must be one of: {', '.join(map(str, choices))}",
            code="parameter_not_allowed",
            details={"allowed": choices},
        )
    return value


# --------------------------------------------------------------------------
# Command dispatch
# --------------------------------------------------------------------------
def dispatch_command(
    ctx,
    device: Device,
    *,
    name: str,
    params: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
    idempotency_key: str = "",
) -> Command:
    """Validate, persist and publish a downlink command.

    The row is written *before* the publish so a broker failure leaves an
    auditable record rather than a silent drop, and the ACK handler always has
    something to attach to when the device answers.
    """
    params = dict(params or {})

    if not device.is_enabled:
        raise Conflict("Device is disabled", code="device_disabled")

    spec = device.device_type.command_spec(name) if device.device_type_id else None
    if device.device_type_id and spec is None:
        available = [
            item.get("name")
            for item in (device.device_type.command_definitions or [])
            if isinstance(item, dict)
        ]
        raise ValidationError(
            f"'{name}' is not a command of blueprint '{device.device_type.name}'",
            code="unknown_command",
            details={"available": available},
        )

    if spec:
        required_role = spec.get("min_role")
        if required_role and ROLE_RANK.get(required_role):
            ctx.require(required_role)
        params = validate_params(spec.get("params"), params)

    if idempotency_key:
        existing = Command.objects.filter(
            organization=ctx.organization, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return existing

    timeout = timeout_seconds or settings.COMMAND_DEFAULT_TIMEOUT_SECONDS
    expires_at = timezone.now() + dt.timedelta(seconds=timeout)

    try:
        with transaction.atomic():
            command = Command.objects.create(
                organization=ctx.organization,
                device=device,
                name=name,
                params=params,
                status=CommandStatus.PENDING,
                issued_by=ctx.user,
                issued_by_label=ctx.principal_label[:200],
                expires_at=expires_at,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Concurrent submission with the same idempotency key.
        existing = Command.objects.filter(
            organization=ctx.organization, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return existing
        raise

    payload = {
        "command_id": str(command.id),
        "name": name,
        "params": params,
        "issued_at": int(command.created_at.timestamp() * 1000),
        "expires_at": int(expires_at.timestamp() * 1000),
        "reply_to": topics.device_topic(device.device_id, topics.CONTROL_ACK),
    }

    try:
        publish_json(topics.control_topic(device.device_id), payload)
    except PublishError as exc:
        command.status = CommandStatus.FAILED
        command.error = f"MQTT publish failed: {exc}"[:500]
        command.completed_at = timezone.now()
        command.save(update_fields=["status", "error", "completed_at", "updated_at"])
        record(
            AuditAction.DEVICE_COMMAND_SENT,
            ctx=ctx,
            target=device,
            status="failure",
            payload={"command": name, "params": params},
            message=str(exc)[:500],
        )
        raise ServiceUnavailable(
            "Command could not be delivered to the broker", code="broker_unavailable"
        ) from exc

    command.status = CommandStatus.SENT
    command.sent_at = timezone.now()
    command.save(update_fields=["status", "sent_at", "updated_at"])

    record(
        AuditAction.DEVICE_COMMAND_SENT,
        ctx=ctx,
        target=device,
        payload={"command": name, "params": params, "command_id": str(command.id)},
    )
    logger.info(
        "command dispatched",
        extra={"device_id": device.device_id, "command": name, "id": str(command.id)},
    )
    return command


def cancel_command(ctx, command_id: uuid.UUID) -> Command:
    command = Command.objects.filter(
        organization=ctx.organization, pk=command_id
    ).select_related("device").first()
    if command is None:
        raise NotFound("Command not found")
    if command.status in TERMINAL_COMMAND_STATUSES:
        raise Conflict(
            f"Command is already {command.status}", code="command_terminal"
        )

    command.status = CommandStatus.CANCELLED
    command.completed_at = timezone.now()
    command.error = "Cancelled by operator"
    command.save(update_fields=["status", "completed_at", "error", "updated_at"])
    record(
        AuditAction.DEVICE_COMMAND_CANCELLED,
        ctx=ctx,
        target=command.device,
        payload={"command_id": str(command.id), "command": command.name},
    )
    return command


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------
def rotate_credential(ctx, device: Device) -> tuple[DeviceCredential, str]:
    """Issue new MQTT credentials. The password is returned only once."""
    ctx.require("admin")
    credential, password = DeviceCredential.issue(device)
    record(AuditAction.DEVICE_CREDENTIAL_ROTATED, ctx=ctx, target=device)
    logger.info("device credential rotated", extra={"device_id": device.device_id})
    return credential, password


def authenticate_device(username: str, password: str, client_id: str = "") -> Device | None:
    """Backing check for the EMQX authentication webhook."""
    credential = (
        DeviceCredential.objects.select_related("device")
        .filter(mqtt_username=username, is_active=True)
        .first()
    )
    if credential is None or not credential.verify(password):
        return None
    if credential.allowed_client_id and client_id != credential.allowed_client_id:
        raise PermissionDenied("Client id does not match the pinned value")

    device = credential.device
    if not device.is_enabled or device.deleted_at is not None:
        return None

    now = timezone.now()
    if credential.last_auth_at is None or (now - credential.last_auth_at).total_seconds() > 60:
        DeviceCredential.objects.filter(pk=credential.pk).update(last_auth_at=now)
    return device
