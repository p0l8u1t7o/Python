"""組裝版本化的 electrical.json：展開後的器件、接線、I/O 表、模組對照與連接檢查。"""

from __future__ import annotations

from typing import Any

from cellforge.schema.electrical import Electrical
from cellforge.schema.models import Cell, Process

from .checks import electrical_checks
from .resolve import ResolvedElectrical, resolve_electrical

PASSIVE_ACTIONS = {"wait", "emit"}


def required_modules(scene, process: Process) -> list[tuple[str, str, str | None]]:
    """Equipment that must be tied to electrical devices: robots, cameras and process actors."""

    required: dict[tuple[str, str | None], str] = {}

    def need(module: str, reason: str, kind: str | None = None) -> None:
        required.setdefault((module, kind), reason)

    for name, module in scene.modules.items():
        if module.chain is not None:
            need(name, "手臂")
            try:
                tool = scene.tool_definition(name)
            except ValueError:
                tool = None
            if tool is not None and tool.cameras:
                need(name, "手臂工具相機", "camera")
        if module.definition.cameras:
            need(name, "相機模組", "camera")
    for step in process.steps:
        owner = step.actor.partition(".")[0]
        if owner in scene.modules and step.action not in PASSIVE_ACTIONS:
            need(owner, f"製程動作 {step.action}（{step.id}）")
    return [
        (module, reason, kind)
        for (module, kind), reason in sorted(
            required.items(), key=lambda entry: (entry[0][0], entry[0][1] or "")
        )
    ]


def _device_row(resolved: ResolvedElectrical, device_id: str) -> dict[str, Any]:
    device = resolved.devices[device_id]
    return {
        **device.model_dump(mode="json", by_alias=True),
        "generated_by": resolved.generated.get(device_id),
    }


def electrical_report(
    electrical: Electrical,
    cell: Cell,
    *,
    scene=None,
    process: Process | None = None,
    costing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = resolve_electrical(electrical, cell)
    required = required_modules(scene, process) if scene is not None and process else []
    checks = electrical_checks(resolved, required_modules=required, costing=costing)
    modules: dict[str, list[str]] = {}
    for device in resolved.devices.values():
        if device.module_ref:
            modules.setdefault(device.module_ref, []).append(device.id)
    return {
        "title": electrical.title,
        "nets": [net.model_dump(mode="json") for net in electrical.nets],
        "devices": [_device_row(resolved, device_id) for device_id in resolved.devices],
        "connections": [
            connection.model_dump(mode="json", by_alias=True, exclude_none=True)
            for connection in resolved.connections
        ],
        "io": [
            {
                "id": item.point.id,
                "signal": item.point.signal,
                "function": item.point.function,
                "channel_device": item.channel_device,
                "address": item.address,
                "pool": item.point.pool,
                "allocated": item.point.address is None,
                "field": (
                    item.point.field.model_dump(mode="json", exclude_none=True)
                    if item.point.field
                    else None
                ),
                "wire": item.point.wire,
                "generated_by": item.generated_by,
                "note": item.point.note,
            }
            for item in resolved.io
        ],
        "pools": {
            pool_id: {
                "device": pool.device,
                "signal": pool.signal,
                "capacity": len(pool.terminals),
                "allocated": resolved.pool_usage.get(pool_id, []),
            }
            for pool_id, pool in resolved.pools.items()
        },
        "safety": [circuit.model_dump(mode="json") for circuit in electrical.safety],
        "panel": electrical.panel.model_dump(mode="json") if electrical.panel else None,
        "drawing": electrical.drawing.model_dump(mode="json"),
        "notes": list(electrical.notes),
        "modules": modules,
        "required_modules": [
            {"module": module, "reason": reason, "kind": kind} for module, reason, kind in required
        ],
        "issues": resolved.issues,
        "reference_errors": resolved.reference_errors,
        "checks": checks,
        "summary": {
            color: sum(item["severity"] == color for item in checks)
            for color in ("red", "yellow", "green")
        },
    }
