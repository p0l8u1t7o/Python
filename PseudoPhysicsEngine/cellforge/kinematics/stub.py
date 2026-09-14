"""Parametric six-axis engineering robot chain and URDF writer."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from .chain import Chain, Joint

DEFAULT_JOINT_LIMITS_DEG = (
    (-170.0, 170.0),
    (-135.0, 135.0),
    (-136.0, 153.0),
    (-270.0, 270.0),
    (-120.0, 120.0),
    (-360.0, 360.0),
)
DEFAULT_MAX_SPEED_DPS = (250.0, 187.0, 250.0, 260.0, 326.0, 400.0)


@dataclass(frozen=True, slots=True)
class StubDimensions:
    reach_mm: float
    payload_kg: float
    d1_mm: float
    l2_mm: float
    l3_mm: float
    l6_mm: float
    tool_length_mm: float
    tool_radius_mm: float
    tool_mass_kg: float


def stub_dimensions(
    reach_mm: float = 905.0,
    payload_kg: float = 7.0,
    *,
    tool_length_mm: float = 150.0,
    tool_radius_mm: float = 30.0,
    tool_mass_kg: float = 1.2,
) -> StubDimensions:
    if reach_mm <= 0 or payload_kg <= 0:
        raise ValueError("手臂 reach 與 payload 必須大於零")
    return StubDimensions(
        reach_mm=float(reach_mm),
        payload_kg=float(payload_kg),
        d1_mm=0.43 * reach_mm,
        l2_mm=0.50 * reach_mm,
        l3_mm=0.50 * reach_mm,
        l6_mm=0.10 * reach_mm,
        tool_length_mm=float(tool_length_mm),
        tool_radius_mm=float(tool_radius_mm),
        tool_mass_kg=float(tool_mass_kg),
    )


def make_stub_chain(
    reach_mm: float = 905.0,
    payload_kg: float = 7.0,
    *,
    tool_length_mm: float = 150.0,
    tool_radius_mm: float = 30.0,
    tool_mass_kg: float = 1.2,
    name: str = "robot_stub",
) -> Chain:
    dims = stub_dimensions(
        reach_mm,
        payload_kg,
        tool_length_mm=tool_length_mm,
        tool_radius_mm=tool_radius_mm,
        tool_mass_kg=tool_mass_kg,
    )
    origins = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, dims.d1_mm),
        (0.0, 0.0, dims.l2_mm),
        (dims.l3_mm / 2.0, 0.0, 0.0),
        (dims.l3_mm / 2.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )
    axes = ((0, 0, 1), (0, 1, 0), (0, 1, 0), (1, 0, 0), (0, 1, 0), (1, 0, 0))
    joints = [
        Joint(
            id=f"j{index}",
            type="revolute",
            parent=f"link{index - 1}",
            child=f"link{index}",
            origin_xyz=origins[index - 1],
            axis=axes[index - 1],
            limit=DEFAULT_JOINT_LIMITS_DEG[index - 1],
            max_speed=DEFAULT_MAX_SPEED_DPS[index - 1],
        )
        for index in range(1, 7)
    ]
    joints.append(
        Joint(
            id="tool",
            type="fixed",
            parent="link6",
            child="tool",
            origin_xyz=(dims.l6_mm + dims.tool_length_mm, 0.0, 0.0),
            origin_rpy_deg=(0.0, 90.0, 0.0),
        )
    )
    return Chain(joints, base_link="link0", tip_link="tool", name=name)


def write_stub_urdf(
    path: Path,
    *,
    name: str,
    reach_mm: float = 905.0,
    payload_kg: float = 7.0,
    tool_length_mm: float = 150.0,
    tool_radius_mm: float = 30.0,
    tool_mass_kg: float = 1.2,
) -> dict[str, object]:
    """Write a dimensioned URDF (metres/radians) and return manifest limits."""

    dims = stub_dimensions(
        reach_mm,
        payload_kg,
        tool_length_mm=tool_length_mm,
        tool_radius_mm=tool_radius_mm,
        tool_mass_kg=tool_mass_kg,
    )
    chain = make_stub_chain(
        reach_mm,
        payload_kg,
        tool_length_mm=tool_length_mm,
        tool_radius_mm=tool_radius_mm,
        tool_mass_kg=tool_mass_kg,
        name=name,
    )
    links = "\n".join(f'  <link name="link{i}"/>' for i in range(7))
    joint_xml: list[str] = []
    for joint in chain.active_joints:
        xyz = " ".join(_format(value / 1000.0) for value in joint.origin_xyz)
        axis = " ".join(_format(value) for value in joint.axis)
        assert joint.limit is not None and joint.max_speed is not None
        joint_xml.append(
            f'  <joint name="{joint.id}" type="revolute">\n'
            f'    <parent link="{joint.parent}"/><child link="{joint.child}"/>\n'
            f'    <origin xyz="{xyz}" rpy="0 0 0"/><axis xyz="{axis}"/>\n'
            f'    <limit lower="{_format(math.radians(joint.limit[0]))}" '
            f'upper="{_format(math.radians(joint.limit[1]))}" effort="100" '
            f'velocity="{_format(math.radians(joint.max_speed))}"/>\n'
            "  </joint>"
        )
    tool_offset_m = (dims.l6_mm + dims.tool_length_mm) / 1000.0
    joint_xml.append(
        '  <link name="tool"/>\n'
        '  <joint name="tool" type="fixed">\n'
        '    <parent link="link6"/><child link="tool"/>\n'
        f'    <origin xyz="{_format(tool_offset_m)} 0 0" rpy="0 {_format(math.pi / 2)} 0"/>\n'
        "  </joint>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<?xml version="1.0"?>\n<robot name="{name}">\n{links}\n'
        + "\n".join(joint_xml)
        + "\n</robot>\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "sha256": digest,
        "joints_deg": [list(pair) for pair in DEFAULT_JOINT_LIMITS_DEG],
        "max_joint_speed_dps": list(DEFAULT_MAX_SPEED_DPS),
        "payload_kg": dims.payload_kg,
        "reach_mm": dims.reach_mm,
    }


def _format(value: float) -> str:
    return f"{value:.12g}"
