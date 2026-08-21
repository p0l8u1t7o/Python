"""Device-facing domain services: downlink commands and credentials."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.accounts.models import ROLE_RANK
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, PermissionDenied, ServiceUnavailable
from apps.core.errors import ValidationError
from apps.core.logging import get_logger
from apps.devices.models import (
    INGESTING_STATES,
    TERMINAL_COMMAND_STATUSES,
    Command,
    CommandStatus,
    Device,
    DeviceCredential,
    DeviceDeclaration,
    DeviceType,
    LifecycleState,
)
from apps.devices.registry import get_registry
from services.mqtt import topics
from services.mqtt.publisher import PublishError, publish_json

logger = get_logger("devices.services")


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------
#: Which audit entry each destination state produces.
_LIFECYCLE_AUDIT = {
    LifecycleState.ACTIVE: AuditAction.DEVICE_RESTORED,
    LifecycleState.SUSPENDED: AuditAction.DEVICE_SUSPENDED,
    LifecycleState.RETIRED: AuditAction.DEVICE_RETIRED,
    LifecycleState.REJECTED: AuditAction.DEVICE_REJECTED,
}


def assert_free_of_energy_bindings(device: Device) -> None:
    """Refuse to stop a device the site's energy balance still depends on.

    An asset left bound to a device that no longer reports does not raise an
    error anywhere - the integral simply comes back empty and the site's
    figures quietly shrink. If that asset is the grid meter, the whole site
    reads as importing nothing. Catching it here is the only place the mistake
    is still visible.
    """
    from apps.ems.models import EnergyAsset

    bindings = list(
        EnergyAsset.objects.filter(device=device, is_active=True).values(
            "id", "role", "site__name"
        )
    )
    if bindings:
        raise Conflict(
            f"{len(bindings)} energy asset binding(s) still point at this device",
            code="device_in_energy_model",
            details={
                "assets": [
                    {
                        "asset_id": str(row["id"]),
                        "role": row["role"],
                        "site": row["site__name"],
                    }
                    for row in bindings
                ]
            },
        )


def set_lifecycle(
    ctx,
    device: Device,
    state: str,
    *,
    reason: str = "",
    skip_binding_check: bool = False,
) -> Device:
    """Move a device between lifecycle states, keeping ``is_enabled`` in step.

    ``is_enabled`` remains what the ingest path reads - it is on the hot path
    in the ingestor, the worker and the EMQX auth webhook, and none of that
    changes. What changes is that nobody sets it by hand any more: one decision
    here drives both fields, so "suspended" and "retired" can never disagree
    with "is this device allowed to connect".

    ``skip_binding_check`` is for the replacement flow, which moves the asset
    bindings to the successor inside the same transaction before retiring the
    predecessor.
    """
    if state not in LifecycleState.values:
        raise ValidationError(f"Unknown lifecycle state '{state}'", code="unknown_state")

    previous = device.commissioning_state
    if previous == state:
        return device

    if state in {LifecycleState.RETIRED, LifecycleState.SUSPENDED} and not skip_binding_check:
        assert_free_of_energy_bindings(device)

    if previous == LifecycleState.RETIRED and state == LifecycleState.ACTIVE:
        _assert_restorable(device)

    updates = ["commissioning_state", "is_enabled", "updated_at"]
    device.commissioning_state = state
    device.is_enabled = state in INGESTING_STATES

    if state == LifecycleState.RETIRED:
        device.retired_at = device.retired_at or timezone.now()
        updates.append("retired_at")
    elif state == LifecycleState.ACTIVE and previous == LifecycleState.RETIRED:
        # Coming back into service: it is current equipment again, so it has
        # no successor and no retirement date.
        device.retired_at = None
        device.replaced_by = None
        updates += ["retired_at", "replaced_by"]

    device.save(update_fields=updates)
    DeviceCredential.objects.filter(device=device).update(
        is_active=state in INGESTING_STATES
    )
    get_registry().invalidate()

    record(
        _LIFECYCLE_AUDIT.get(state, AuditAction.DEVICE_UPDATED),
        ctx=ctx,
        target=device,
        payload={"from": previous, "to": state, "reason": reason},
    )
    return device


def _assert_restorable(device: Device) -> None:
    """A retired device may only come back if its successor has stepped aside.

    Two devices claiming to be the same piece of equipment at the same time
    would make every stitched report ambiguous, so the successor has to be
    retired or suspended first. The device id itself is never the obstacle:
    ``device_id`` is unique platform-wide and a retired device never gives its
    own back, so restoring one can never collide.
    """
    successor = device.replaced_by
    if successor is None:
        return
    if successor.commissioning_state in INGESTING_STATES:
        raise Conflict(
            f"'{successor.name}' replaced this device and is still in service; "
            "retire or suspend it first",
            code="successor_still_active",
            details={
                "successor_id": str(successor.pk),
                "successor_device_id": successor.device_id,
            },
        )


@transaction.atomic
def replace_device(
    ctx,
    old: Device,
    *,
    device_id: str,
    name: str,
    device_type_id=None,
    serial_number: str = "",
    reason: str = "",
    issue_credential: bool = True,
) -> dict:
    """Register a successor, move everything to it, and retire the old one.

    Why the new device needs a new ``device_id``: it is the MQTT topic segment
    and is unique platform-wide, and a retired device keeps its own - history
    has to stay attributable to the equipment that produced it. So the field
    work includes writing a new id into the replacement's configuration.

    What moves, and why each matters:

    * **Energy asset bindings.** The one that cannot be skipped. A binding left
      on a silent device makes the site's balance quietly incomplete.
    * **Device-scoped alert rules.** Otherwise the new hardware is unmonitored
      while the rule still watches a device that will never report again.
    * **Recording policy.** Copied, so the successor stores the same series at
      the same resolution instead of falling back to the tenant default.
    """
    from apps.alerts.models import AlertRule
    from apps.ems.models import EnergyAsset

    if Device.objects.filter(device_id=device_id).exists():
        raise Conflict(
            f"Device id '{device_id}' is already in use",
            code="device_id_taken",
            details={"device_id": device_id},
        )
    if old.commissioning_state == LifecycleState.RETIRED:
        raise Conflict(
            "This device has already been retired", code="device_already_retired"
        )

    blueprint = old.device_type
    if device_type_id is not None:
        blueprint = DeviceType.objects.filter(
            models.Q(organization=ctx.organization) | models.Q(organization__isnull=True),
            pk=device_type_id,
        ).first()
        if blueprint is None:
            raise NotFound("Blueprint not found")

    new = Device.objects.create(
        organization=old.organization,
        site=old.site,
        device_type=blueprint,
        recording_policy=old.recording_policy,
        device_id=device_id,
        name=name or old.name,
        serial_number=serial_number,
        description=f"Replaces {old.device_id}",
        latitude=old.latitude,
        longitude=old.longitude,
        address=old.address,
        location_source=old.location_source,
        tags=list(old.tags or []),
        commissioning_state=LifecycleState.ACTIVE,
    )

    moved_assets = list(
        EnergyAsset.objects.filter(device=old).values_list("id", flat=True)
    )
    EnergyAsset.objects.filter(device=old).update(device=new)

    moved_rules = list(
        AlertRule.objects.filter(devices=old).values_list("id", flat=True)
    )
    for rule in AlertRule.objects.filter(devices=old):
        rule.devices.add(new)
        rule.devices.remove(old)

    old.replaced_by = new
    old.save(update_fields=["replaced_by", "updated_at"])
    # Bindings have already moved, so the usual guard would fire on an empty
    # set anyway; skipping it keeps the intent explicit.
    set_lifecycle(
        ctx,
        old,
        LifecycleState.RETIRED,
        reason=reason or f"replaced by {new.device_id}",
        skip_binding_check=True,
    )

    credential = password = None
    if issue_credential:
        credential, password = DeviceCredential.issue(new)

    get_registry().invalidate()
    record(
        AuditAction.DEVICE_REPLACED,
        ctx=ctx,
        target=new,
        payload={
            "replaces": old.device_id,
            "moved_assets": len(moved_assets),
            "moved_alert_rules": len(moved_rules),
            "reason": reason,
        },
    )

    return {
        "retired": old,
        "replacement": new,
        "moved_asset_count": len(moved_assets),
        "moved_alert_rule_count": len(moved_rules),
        "credential": (
            {
                "mqtt_username": credential.mqtt_username,
                "mqtt_password": password,
                "allowed_client_id": credential.allowed_client_id,
                "is_active": credential.is_active,
                "rotated_at": credential.rotated_at,
                "last_auth_at": credential.last_auth_at,
            }
            if credential
            else None
        ),
    }


# --------------------------------------------------------------------------
# Capability enforcement
# --------------------------------------------------------------------------
#: Which capability each dispatch command needs, and how to read its params.
#:
#: Naming a command is not enough: ``set_power_setpoint`` with a negative
#: ``power_w`` is a charge instruction, and the blueprint's schema happily
#: allows the whole ±5 MW range. The intent has to be read out of the values.
_CHARGE_MODES = {"charge"}
_DISCHARGE_MODES = {"discharge"}


def _required_capabilities(name: str, params: dict[str, Any]) -> set[str]:
    """Capabilities a command needs, derived from its name *and* its values."""
    needed: set[str] = set()

    if name == "set_power_setpoint":
        power = params.get("power_w")
        if isinstance(power, (int, float)):
            if power < 0:
                needed.add("can_charge")
            elif power > 0:
                needed.add("can_discharge")
    elif name == "set_mode":
        mode = str(params.get("mode", "")).lower()
        if mode in _CHARGE_MODES:
            needed.add("can_charge")
        elif mode in _DISCHARGE_MODES:
            needed.add("can_discharge")
        elif mode == "auto":
            # Auto may do either, so it needs both.
            needed.update({"can_charge", "can_discharge"})
    elif name == "set_export_limit":
        limit = params.get("limit_w")
        if isinstance(limit, (int, float)) and limit > 0:
            needed.add("can_export")

    return needed


def _check_dispatch_state(device: Device) -> None:
    """Lifecycle and identity gates that apply to energy-dispatch commands.

    Housekeeping commands - changing a reporting interval, syncing a clock -
    move no power and stay available, which is why only dispatch reaches here.
    """
    state = device.commissioning_state
    if state == LifecycleState.PENDING:
        raise Conflict(
            "This device is awaiting commissioning; confirm it before sending "
            "dispatch commands",
            code="device_unconfirmed",
            details={"device_id": str(device.id)},
        )
    if state == LifecycleState.RETIRED:
        raise Conflict(
            "This device has been retired",
            code="device_retired",
            details={
                "device_id": str(device.id),
                "replaced_by": str(device.replaced_by_id) if device.replaced_by_id else None,
            },
        )
    if state == LifecycleState.SUSPENDED:
        raise Conflict(
            "This device is suspended",
            code="device_suspended",
            details={"device_id": str(device.id)},
        )
    if state == LifecycleState.REJECTED:
        raise Conflict(
            "This device was rejected during commissioning",
            code="device_rejected",
            details={"device_id": str(device.id)},
        )

    declaration = (
        DeviceDeclaration.objects.filter(device=device)
        .only("identity_mismatch")
        .first()
    )
    if declaration is not None and declaration.identity_mismatch:
        # The equipment on the wire is declaring itself to be something other
        # than what is registered - most likely it was swapped without
        # registering a replacement. Until that is resolved we do not know what
        # we would be commanding, so we do not command it.
        raise Conflict(
            "This device is declaring a different category than the one it is "
            "registered as; register the replacement before commanding it",
            code="device_identity_mismatch",
            details={"device_id": str(device.id)},
        )


def check_capabilities(device: Device, name: str, params: dict[str, Any]) -> None:
    """Refuse commands the hardware cannot - or must not - carry out.

    Reads :meth:`Device.effective_capabilities` and nothing else. It must never
    consult a device's own declaration: a compromised unit claiming
    ``can_charge`` would otherwise talk its way past the check it exists to
    enforce. There is a test pinning exactly that.
    """
    spec = device.device_type.command_spec(name) if device.device_type_id else None
    is_dispatch = (spec or {}).get("kind", "dispatch") == "dispatch"

    if is_dispatch:
        _check_dispatch_state(device)

    capabilities = device.effective_capabilities()

    if is_dispatch and not capabilities["is_dispatchable"]:
        raise ValidationError(
            f"'{device.name}' does not accept dispatch commands",
            code="asset_not_dispatchable",
            details={"device_id": str(device.id), "command": name},
        )

    for capability in sorted(_required_capabilities(name, params)):
        if capabilities.get(capability):
            continue
        code = (
            "export_not_permitted"
            if capability == "can_export"
            else "capability_not_supported"
        )
        raise ValidationError(
            f"'{device.name}' cannot perform '{name}': {capability} is not available",
            code=code,
            details={
                "capability": capability,
                "command": name,
                "device_id": str(device.id),
            },
        )


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
        # Lifecycle first: "retired" and "suspended" are far more useful to an
        # operator than a bare "disabled".
        _check_dispatch_state(device)
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

    # After the schema, so the capability check reads validated values.
    check_capabilities(device, name, params)

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
