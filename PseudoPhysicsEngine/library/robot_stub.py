"""Parametric articulated six-axis engineering robot."""

from __future__ import annotations

import importlib
from typing import Any

import cadquery as cq

from cellforge.kinematics import Chain, make_stub_chain, stub_dimensions
from cellforge.schema import Frame, ModuleAxis, ModuleDef


def _x_cylinder(radius: float, length: float, start: tuple[float, float, float]) -> cq.Solid:
    """Create an X-aligned solid using global coordinates, independent of a workplane frame."""

    return cq.Solid.makeCylinder(radius, length, cq.Vector(*start), cq.Vector(1, 0, 0))


def _z_cylinder(radius: float, height: float, start_z: float = 0.0) -> cq.Solid:
    return cq.Solid.makeCylinder(radius, height, cq.Vector(0, 0, start_z), cq.Vector(0, 0, 1))


def _tool_parameters(
    params: dict[str, Any], *, include_shape: bool = True
) -> tuple[float, float, float, cq.Shape | None]:
    tool = params.get("tool") or {}
    if not isinstance(tool, dict):
        raise ValueError("tool 必須是參數物件")
    if "part" not in tool:
        return (
            float(tool.get("length_mm", 150)),
            float(tool.get("radius_mm", 30)),
            float(tool.get("mass_kg", 1.2)),
            None,
        )
    module_name = str(tool["part"]).replace("\\", "/").removesuffix(".py").replace("/", ".")
    module = importlib.import_module(module_name)
    definition = module.MODULE
    tcp = definition.frames.get("tool_center_point", Frame(xyz=(0, 0, 150)))
    length = float(tcp.xyz[2])
    mass = float(tool.get("mass_kg", definition.payload_kg or 1.2))
    shape = None
    if include_shape:
        shape = module.build(dict(tool.get("params", {}))).toCompound()
    return length, float(tool.get("radius_mm", 30)), mass, shape


def chain_from_params(params: dict[str, Any]) -> Chain:
    length, radius, mass, _shape = _tool_parameters(params, include_shape=False)
    return make_stub_chain(
        float(params.get("reach_mm", 905)),
        float(params.get("payload_kg", 7)),
        tool_length_mm=length,
        tool_radius_mm=radius,
        tool_mass_kg=mass,
        name=str(params.get("name", "robot_stub")),
    )


def module_definition(params: dict[str, Any]) -> ModuleDef:
    chain = chain_from_params(params)
    _tool_length, _tool_radius, tool_mass, _shape = _tool_parameters(params, include_shape=False)
    axes = []
    for joint in chain.active_joints:
        assert joint.limit is not None
        axes.append(
            ModuleAxis(
                id=joint.id,
                type="revolute",
                parent=joint.parent,
                child=joint.child,
                origin={"xyz": joint.origin_xyz, "rpy_deg": joint.origin_rpy_deg},
                axis=joint.axis,
                range_deg=joint.limit,
                max_speed_dps=joint.max_speed,
            )
        )
    rest = chain.link_transforms([0.0] * 6)
    flange = rest["link6"].copy()
    dims = stub_dimensions(
        float(params.get("reach_mm", 905)),
        float(params.get("payload_kg", 7)),
        tool_length_mm=_tool_parameters(params, include_shape=False)[0],
    )
    flange[:3, 3] += flange[:3, 0] * dims.l6_mm
    return ModuleDef(
        id="robot_stub",
        params_schema=MODULE.params_schema,
        frames={
            "base": Frame(),
            "flange": Frame(xyz=tuple(float(v) for v in flange[:3, 3]), rpy_deg=(0, 90, 0)),
            "tool": Frame(xyz=tuple(float(v) for v in rest["tool"][:3, 3]), rpy_deg=(0, 90, 0)),
        },
        axes=axes,
        collision="hull",
        payload_kg=float(params.get("payload_kg", 7)),
        tool_mass_kg=tool_mass,
    )


def build(params: dict) -> cq.Assembly:
    reach = float(params.get("reach_mm", 905))
    payload = float(params.get("payload_kg", 7))
    tool_length, tool_radius, tool_mass, custom_tool = _tool_parameters(params)
    dims = stub_dimensions(
        reach,
        payload,
        tool_length_mm=tool_length,
        tool_radius_mm=tool_radius,
        tool_mass_kg=tool_mass,
    )
    result = cq.Assembly(name=params.get("name", "robot_stub"))
    red = cq.Color(0.76, 0.1, 0.1)
    silver = cq.Color(0.82, 0.82, 0.85)
    result.add(_z_cylinder(150, 100), name="link0", color=silver)
    result.add(_z_cylinder(90, dims.d1_mm), name="link1", color=red)
    result.add(
        cq.Workplane("XY").box(120, 120, dims.l2_mm).translate((0, 0, dims.d1_mm + dims.l2_mm / 2)),
        name="link2",
        color=red,
    )
    result.add(
        _x_cylinder(65, dims.l3_mm / 2, (0, 0, dims.d1_mm + dims.l2_mm)),
        name="link3",
        color=silver,
    )
    result.add(
        _x_cylinder(
            52,
            dims.l3_mm / 2 - 27.5,
            (dims.l3_mm / 2, 0, dims.d1_mm + dims.l2_mm),
        ),
        name="link4",
        color=silver,
    )
    wrist_x = dims.l3_mm
    wrist_z = dims.d1_mm + dims.l2_mm
    result.add(
        _x_cylinder(58, 55, (wrist_x - 27.5, 0, wrist_z)),
        name="link5",
        color=red,
    )
    result.add(
        _x_cylinder(48, dims.l6_mm, (wrist_x, 0, wrist_z)),
        name="link6",
        color=silver,
    )
    tcp_x = wrist_x + dims.l6_mm + dims.tool_length_mm
    if custom_tool is None:
        tool_shape = _x_cylinder(
            dims.tool_radius_mm,
            dims.tool_length_mm,
            (wrist_x + dims.l6_mm, 0, wrist_z),
        )
        result.add(tool_shape, name="tool", color=cq.Color(0.2, 0.25, 0.3))
    else:
        result.add(
            custom_tool,
            name="tool",
            color=cq.Color(0.18, 0.21, 0.24),
            loc=cq.Location((wrist_x + dims.l6_mm, 0, wrist_z), (0, 90, 0)),
        )
    result.metadata = {"tcp_xyz": (tcp_x, 0.0, wrist_z)}
    return result


MODULE = ModuleDef(
    id="robot_stub",
    params_schema={
        "type": "object",
        "properties": {
            "reach_mm": {"type": "number", "exclusiveMinimum": 0},
            "payload_kg": {"type": "number", "exclusiveMinimum": 0},
            "name": {"type": "string"},
            "tool": {"type": "object"},
        },
    },
    frames={"base": Frame(), "flange": Frame(), "tool": Frame()},
    axes=[ModuleAxis(id=f"j{i}", type="revolute", range_deg=(-180, 180)) for i in range(1, 7)],
    collision="hull",
    payload_kg=7,
)
