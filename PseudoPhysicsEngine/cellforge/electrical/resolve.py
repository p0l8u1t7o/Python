"""展開 electrical.yaml：設備樣板依模組實例產生器件、連接與 I/O，點位池依序配置端子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from cellforge.schema.electrical import (
    Connection,
    Device,
    Electrical,
    Endpoint,
    IoPoint,
    Pool,
)
from cellforge.schema.models import Cell


class ElectricalReferenceError(ValueError):
    """未定義的器件、端子、電位網或點位池；正式資料驗證時必須失敗。"""


@dataclass
class ResolvedIo:
    point: IoPoint
    channel_device: str
    address: str
    generated_by: str | None = None
    via: Endpoint | None = None


@dataclass
class ResolvedElectrical:
    source: Electrical
    devices: dict[str, Device]
    generated: dict[str, str]
    connections: list[Connection]
    io: list[ResolvedIo]
    pools: dict[str, Pool]
    pool_usage: dict[str, list[str]]
    issues: list[dict[str, str]] = field(default_factory=list)
    reference_errors: list[str] = field(default_factory=list)

    def terminal(self, device: str, terminal: str):
        item = self.devices.get(device)
        if item is None:
            return None
        return next((entry for entry in item.terminals if entry.id == terminal), None)


def _substitute(value: Any, module: str) -> Any:
    if isinstance(value, str):
        return value.replace("{module}", module)
    if isinstance(value, list):
        return [_substitute(item, module) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, module) for key, item in value.items()}
    return value


def _modules(cell: Cell):
    for machine in cell.machines:
        yield from machine.modules


def _tool_part(instance) -> str | None:
    tool = instance.params.get("tool")
    return str(tool.get("part")).replace("\\", "/") if isinstance(tool, dict) else None


def _matches(match, instance) -> bool:
    return all(
        (
            match.part is None or (instance.part or "").replace("\\", "/") == match.part,
            match.vendor is None or instance.vendor == match.vendor,
            match.module is None or instance.id == match.module,
            match.tool is None or _tool_part(instance) == match.tool.replace("\\", "/"),
        )
    )


def resolve_electrical(electrical: Electrical, cell: Cell) -> ResolvedElectrical:
    devices: dict[str, Device] = {device.id: device for device in electrical.devices}
    generated: dict[str, str] = {}
    connections = list(electrical.connections)
    io_points: list[tuple[IoPoint, str | None]] = [(point, None) for point in electrical.io]
    issues: list[dict[str, str]] = []
    errors: list[str] = []
    module_ids = {instance.id for instance in _modules(cell)}

    for template in electrical.equipment:
        if template.match.module and template.match.module not in module_ids:
            errors.append(f"電控設備樣板 {template.id} 引用不存在的模組：{template.match.module}")
        matched = [instance for instance in _modules(cell) if _matches(template.match, instance)]
        if not matched:
            issues.append(
                {
                    "severity": "warning",
                    "code": "NO_EQUIPMENT",
                    "message": f"電控設備樣板 {template.id} 沒有對到任何模組實例",
                }
            )
        for instance in matched:
            label = f"{template.id}:{instance.id}"
            try:
                for raw in template.devices:
                    device = Device.model_validate(_substitute(raw, instance.id))
                    if device.id in devices:
                        errors.append(f"設備樣板 {label} 產生的器件 id 與既有器件重複：{device.id}")
                        continue
                    devices[device.id] = device
                    generated[device.id] = label
                for raw in template.connections:
                    connections.append(Connection.model_validate(_substitute(raw, instance.id)))
                for raw in template.io:
                    io_points.append((IoPoint.model_validate(_substitute(raw, instance.id)), label))
            except ValidationError as error:
                errors.append(f"設備樣板 {label} 的內容格式錯誤：{error}")

    pools = {pool.id: pool for pool in electrical.pools}
    for pool in pools.values():
        if pool.device not in devices:
            errors.append(f"點位池 {pool.id} 引用不存在的器件：{pool.device}")
            continue
        known = {terminal.id for terminal in devices[pool.device].terminals}
        missing = [terminal for terminal in pool.terminals if terminal not in known]
        if missing:
            errors.append(
                f"點位池 {pool.id} 引用器件 {pool.device} 不存在的端子：{'、'.join(missing)}"
            )

    used: dict[tuple[str, str], str] = {}
    usage: dict[str, list[str]] = {pool_id: [] for pool_id in pools}

    def claim(device: str, terminal: str, owner: str) -> None:
        key = (device, terminal)
        if key in used:
            issues.append(
                {
                    "severity": "error",
                    "code": "DUPLICATE_ADDRESS",
                    "message": f"{device} 的 {terminal} 同時被 {used[key]} 與 {owner} 使用",
                }
            )
            return
        used[key] = owner

    # 手動指定的點位先佔用，自動配置才不會覆蓋
    resolved_io: list[ResolvedIo] = []
    for point, origin in io_points:
        if point.address is None:
            continue
        device = point.channel_device or (pools[point.pool].device if point.pool in pools else None)
        if device is None:
            errors.append(f"I/O {point.id} 引用不存在的點位池：{point.pool}")
            continue
        claim(device, point.address, f"I/O {point.id}")
        resolved_io.append(ResolvedIo(point, device, point.address, origin))
    for point, _origin in io_points:
        if point.via is not None and point.via.net is not None:
            errors.append(f"I/O {point.id} 的 via 必須是端子排端子或點位池，不可為電位網")
        elif point.via is not None and point.via.device and point.via.terminal:
            claim(point.via.device, point.via.terminal, f"I/O {point.id}")
    for connection in connections:
        for endpoint in (connection.from_, connection.to):
            if endpoint.device and endpoint.terminal:
                pool = next(
                    (
                        item
                        for item in pools.values()
                        if item.device == endpoint.device and endpoint.terminal in item.terminals
                    ),
                    None,
                )
                if pool is not None:
                    claim(endpoint.device, endpoint.terminal, f"連接 {connection.id}")

    def allocate(pool_id: str, owner: str) -> tuple[str, str] | None:
        pool = pools.get(pool_id)
        if pool is None:
            errors.append(f"{owner} 引用不存在的點位池：{pool_id}")
            return None
        for terminal in pool.terminals:
            if (pool.device, terminal) not in used:
                used[(pool.device, terminal)] = owner
                usage[pool_id].append(terminal)
                return pool.device, terminal
        issues.append(
            {
                "severity": "error",
                "code": "POOL_EXHAUSTED",
                "message": f"點位池 {pool_id} 已無可用端子，{owner} 無法配置",
            }
        )
        return None

    for point, origin in io_points:
        if point.address is not None:
            continue
        allocated = allocate(point.pool or "", f"I/O {point.id}")
        if allocated is not None:
            resolved_io.append(ResolvedIo(point, allocated[0], allocated[1], origin))
    for item in resolved_io:
        via = item.point.via
        if via is not None and via.pool is not None:
            allocated = allocate(via.pool, f"I/O {item.point.id} 端子排")
            item.via = Endpoint(device=allocated[0], terminal=allocated[1]) if allocated else None
        elif via is not None and via.net is None:
            item.via = via
    final_connections: list[Connection] = []
    for connection in connections:
        endpoints = []
        for endpoint in (connection.from_, connection.to):
            if endpoint.pool is not None:
                allocated = allocate(endpoint.pool, f"連接 {connection.id}")
                endpoint = (
                    Endpoint(device=allocated[0], terminal=allocated[1]) if allocated else endpoint
                )
            endpoints.append(endpoint)
        final_connections.append(
            connection.model_copy(update={"from_": endpoints[0], "to": endpoints[1]})
        )
    # I/O 本身就是接線：控制器通道 →（端子排）→ 現場器件端子
    for item in resolved_io:
        wires = [item.point.wire] if item.point.wire else []
        channel = {"device": item.channel_device, "terminal": item.address}
        field_end = item.point.field.model_dump(exclude_none=True) if item.point.field else None
        hops: list[tuple[str, dict[str, str], dict[str, str]]] = []
        if item.via is not None:
            via = item.via.model_dump(exclude_none=True)
            hops.append((f"IO:{item.point.id}", channel, via))
            if field_end is not None:
                hops.append((f"IO:{item.point.id}:field", via, field_end))
        elif field_end is not None:
            hops.append((f"IO:{item.point.id}", channel, field_end))
        for connection_id, start, end in hops:
            final_connections.append(
                Connection.model_validate(
                    {
                        "id": connection_id,
                        "from": start,
                        "to": end,
                        "wire_numbers": wires,
                        "note": item.point.function,
                    }
                )
            )

    resolved = ResolvedElectrical(
        source=electrical,
        devices=devices,
        generated=generated,
        connections=final_connections,
        io=resolved_io,
        pools=pools,
        pool_usage=usage,
        issues=issues,
        reference_errors=errors,
    )
    _check_references(resolved, module_ids)
    return resolved


def _check_references(resolved: ResolvedElectrical, module_ids: set[str]) -> None:
    nets = {net.id for net in resolved.source.nets}
    errors = resolved.reference_errors
    for connection in resolved.connections:
        for endpoint in (connection.from_, connection.to):
            if endpoint.net is not None:
                if endpoint.net not in nets:
                    errors.append(f"連接 {connection.id} 引用不存在的電位網：{endpoint.net}")
            elif endpoint.device is not None:
                if endpoint.device not in resolved.devices:
                    errors.append(f"連接 {connection.id} 引用不存在的器件：{endpoint.device}")
                elif resolved.terminal(endpoint.device, endpoint.terminal or "") is None:
                    errors.append(
                        f"連接 {connection.id} 引用器件 {endpoint.device} 不存在的端子："
                        f"{endpoint.terminal}"
                    )
    for item in resolved.io:
        if resolved.terminal(item.channel_device, item.address) is None:
            errors.append(
                f"I/O {item.point.id} 的位址不是 {item.channel_device} 的端子：{item.address}"
            )
    for device in resolved.devices.values():
        if device.module_ref and device.module_ref not in module_ids:
            errors.append(
                f"器件 {device.id} 的 module_ref 不是 cell.yaml 的模組：{device.module_ref}"
            )
        for left, right in device.bridges:
            for terminal in (left, right):
                if resolved.terminal(device.id, terminal) is None:
                    errors.append(f"器件 {device.id} 的內部導通引用不存在的端子：{terminal}")
    rails = {rail.id for rail in resolved.source.panel.rails} if resolved.source.panel else set()
    for device in resolved.devices.values():
        if device.panel is not None and device.panel.rail not in rails:
            errors.append(f"器件 {device.id} 的盤面軌道不存在：{device.panel.rail}")
    for circuit in resolved.source.safety:
        for device in [*circuit.devices, circuit.controller, *circuit.outputs]:
            if device not in resolved.devices:
                errors.append(f"安全回路 {circuit.id} 引用不存在的器件：{device}")


def require_valid(resolved: ResolvedElectrical) -> None:
    if resolved.reference_errors:
        raise ElectricalReferenceError("；".join(resolved.reference_errors))
