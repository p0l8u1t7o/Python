"""Parametric articulated six-axis engineering robot."""

from __future__ import annotations

import importlib
from typing import Any

import cadquery as cq

from cellforge.kinematics import Chain, make_stub_chain, stub_dimensions
from cellforge.schema import Frame, ModuleAxis, ModuleDef, ModuleMeta

ROBOT_STUB_BASIS = "依 DENSO VS-087 等級六軸機器人型錄的九百零五毫米臂展與七公斤負載作參數化近似"

ARM_RED = cq.Color(0.78, 0.08, 0.08)
CASTING_RED = cq.Color(0.62, 0.05, 0.05)
METAL_GREY = cq.Color(0.72, 0.74, 0.77)
JOINT_DARK = cq.Color(0.12, 0.14, 0.16)


def _x_cylinder(radius: float, length: float, start: tuple[float, float, float]) -> cq.Solid:
    """Create an X-aligned solid using global coordinates, independent of a workplane frame."""

    return cq.Solid.makeCylinder(radius, length, cq.Vector(*start), cq.Vector(1, 0, 0))


def _z_cylinder(radius: float, height: float, start_z: float = 0.0) -> cq.Solid:
    return cq.Solid.makeCylinder(radius, height, cq.Vector(0, 0, start_z), cq.Vector(0, 0, 1))


def _y_cylinder(radius: float, length: float, start: tuple[float, float, float]) -> cq.Solid:
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*start), cq.Vector(0, 1, 0))


def _tapered_z(start_z: float, length: float, lower_radius: float, upper_radius: float) -> cq.Shape:
    return (
        cq.Workplane("XY", origin=(0, 0, start_z))
        .circle(lower_radius)
        .workplane(offset=length)
        .circle(upper_radius)
        .loft()
        .val()
    )


def _tapered_x(
    start_x: float,
    z: float,
    length: float,
    start_radius: float,
    end_radius: float,
) -> cq.Shape:
    return (
        cq.Workplane("YZ", origin=(start_x, 0, z))
        .circle(start_radius)
        .workplane(offset=length)
        .circle(end_radius)
        .loft()
        .val()
    )


def _iso_flange(flange_x: float, radius: float, thickness: float) -> cq.Shape:
    """Simplified ISO 9409 face: pilot outline plus a four-hole bolt circle."""

    disk = _x_cylinder(radius, thickness, (flange_x - thickness, 0, 0))
    bolt_circle = radius * 0.62
    hole_radius = radius * 0.075
    cutter_start = flange_x - thickness * 1.5
    cutter_length = thickness * 2.0
    for y, z in (
        (bolt_circle, 0.0),
        (-bolt_circle, 0.0),
        (0.0, bolt_circle),
        (0.0, -bolt_circle),
    ):
        disk = disk.cut(_x_cylinder(hole_radius, cutter_length, (cutter_start, y, z)))
    pilot = _x_cylinder(radius * 0.32, thickness * 0.18, (flange_x, 0, 0))
    return cq.Compound.makeCompound([disk, pilot])


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
            "mount": Frame(link="link0"),
            "base": Frame(link="link0"),
            "flange": Frame(
                xyz=tuple(float(v) for v in flange[:3, 3]), rpy_deg=(0, 90, 0), link="link6"
            ),
            "tool": Frame(
                xyz=tuple(float(v) for v in rest["tool"][:3, 3]),
                rpy_deg=(0, 90, 0),
                link="tool",
            ),
        },
        axes=axes,
        collision="hull",
        payload_kg=float(params.get("payload_kg", 7)),
        tool_mass_kg=tool_mass,
        meta=ModuleMeta(basis=ROBOT_STUB_BASIS),
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
    scale = reach / 905.0
    base_radius = 145.0 * scale
    base_height = min(dims.d1_mm * 0.24, 110.0 * scale)
    shoulder_radius = 82.0 * scale
    upper_start_radius = 70.0 * scale
    upper_end_radius = 54.0 * scale
    forearm_start_radius = 58.0 * scale
    forearm_end_radius = 42.0 * scale

    base_casting = cq.Compound.makeCompound(
        [
            _z_cylinder(base_radius, base_height * 0.45),
            _tapered_z(
                base_height * 0.45,
                base_height * 0.55,
                base_radius * 0.82,
                shoulder_radius,
            ),
        ]
    )
    result.add(base_casting, name="link0", color=METAL_GREY)

    shoulder_column = _tapered_z(
        0.0,
        dims.d1_mm,
        shoulder_radius,
        shoulder_radius * 0.88,
    )
    shoulder_housing = _y_cylinder(
        shoulder_radius,
        shoulder_radius * 1.45,
        (0, -shoulder_radius * 0.725, dims.d1_mm),
    )
    result.add(
        cq.Compound.makeCompound([shoulder_column, shoulder_housing]),
        name="link1",
        color=CASTING_RED,
    )

    upper_arm = _tapered_z(dims.d1_mm, dims.l2_mm, upper_start_radius, upper_end_radius)
    elbow_cap = _y_cylinder(
        upper_end_radius * 1.08,
        upper_end_radius * 1.45,
        (0, -upper_end_radius * 0.725, dims.d1_mm + dims.l2_mm),
    )
    result.add(
        cq.Compound.makeCompound([upper_arm, elbow_cap]),
        name="link2",
        color=ARM_RED,
    )

    elbow_z = dims.d1_mm + dims.l2_mm
    half_forearm = dims.l3_mm / 2
    result.add(
        _tapered_x(0, elbow_z, half_forearm, forearm_start_radius, forearm_end_radius),
        name="link3",
        color=METAL_GREY,
    )
    result.add(
        _tapered_x(
            half_forearm,
            elbow_z,
            half_forearm,
            forearm_end_radius,
            forearm_end_radius * 0.78,
        ),
        name="link4",
        color=METAL_GREY,
    )
    wrist_x = dims.l3_mm
    wrist_z = elbow_z
    wrist_radius = max(forearm_end_radius * 0.86, 28.0 * scale)
    result.add(
        _x_cylinder(wrist_radius, wrist_radius * 1.35, (wrist_x - wrist_radius * 0.68, 0, wrist_z)),
        name="link5",
        color=ARM_RED,
    )
    flange_radius = max(wrist_radius * 0.82, 24.0 * scale)
    flange_thickness = max(dims.l6_mm * 0.18, 10.0 * scale)
    flange_x = wrist_x + dims.l6_mm
    wrist_neck = _tapered_x(
        wrist_x,
        wrist_z,
        dims.l6_mm - flange_thickness,
        wrist_radius * 0.72,
        flange_radius * 0.72,
    )
    flange = _iso_flange(flange_x, flange_radius, flange_thickness).translate((0, 0, wrist_z))
    result.add(
        cq.Compound.makeCompound([wrist_neck, flange]),
        name="link6",
        color=JOINT_DARK,
    )
    tcp_x = wrist_x + dims.l6_mm + dims.tool_length_mm
    if custom_tool is None:
        tool_shape = _x_cylinder(
            dims.tool_radius_mm,
            dims.tool_length_mm,
            (wrist_x + dims.l6_mm, 0, wrist_z),
        )
        result.add(tool_shape, name="tool", color=JOINT_DARK)
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
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "reach_mm": {"type": "number", "minimum": 600, "maximum": 1300, "default": 905},
            "payload_kg": {"type": "number", "minimum": 3, "maximum": 20, "default": 7},
            "name": {"type": "string"},
            "tool": {"type": "object"},
        },
    },
    frames={"mount": Frame(), "base": Frame(), "flange": Frame(), "tool": Frame()},
    axes=[ModuleAxis(id=f"j{i}", type="revolute", range_deg=(-180, 180)) for i in range(1, 7)],
    collision="hull",
    payload_kg=7,
    meta=ModuleMeta(basis=ROBOT_STUB_BASIS),
)
