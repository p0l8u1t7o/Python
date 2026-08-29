"""六軸機械手臂（巢狀關節模組，供前端依 _pivot/_axis 基準點做動畫）。

節點結構（名稱 = seed mesh_name，prefix 例 "r1-"）：
  r1-base
  r1-j1 (rev, 繞垂直軸)
    └ r1-j2 (rev, 繞水平軸)
        └ r1-j3 (rev)
            └ r1-wrist (rev)
                └ r1-flange、r1-gripper / r1-tool
所有幾何以絕對場景座標烘入；樞軸由 anim_datums 給出。
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cylinder, Location, Pos, Rot, Sphere, fillet
from cadgen import srgb

from layout import M, anim_datums, scene, sub_compound, sub_moving
from parts import BOT, DARK, STEEL, TEAL, col, comp, gripper, vacuum_pads, electric_screwdriver, tool_flange, industrial_camera


def _capsule_link(length, r, color):
    body = col(Cylinder(r, length, align=BOT), color)
    ends = [col(Sphere(r).moved(Location((0, 0, z))), color) for z in (0, length)]
    return [body] + ends


def robot_arm(prefix: str, base_m, yaw_deg: float = 0.0, color="#E8E8E8", tool="gripper", pose=(0.0, -0.4, 0.9, -0.5)):
    """base_m：底座法蘭底面中心（場景座標，公尺，Y-up）。pose：(j1, j2, j3, j5) 靜態姿態（弧度）。
    回傳 (base_compound, j1_compound) 兩個頂層子組。"""
    L1 = 140.0   # 底座高
    H1 = 300.0   # J1 殼高（到 J2 軸）
    L2 = 550.0   # 下臂
    L3 = 500.0   # 上臂
    LW = 150.0   # 腕部
    bx, by, bz = scene(*base_m)  # CAD 座標 mm
    yaw = math.radians(yaw_deg)
    q1, q2, q3, q5 = pose

    def W(x, y, z):
        """手臂本地座標（X 前、Z 上，已含 yaw）→ CAD 絕對座標。"""
        cx = bx + x * math.cos(yaw) - y * math.sin(yaw)
        cy = by + x * math.sin(yaw) + y * math.cos(yaw)
        return (cx, cy, bz + z)

    def loc(x, y, z, rot=(0, 0, 0)):
        return Location(W(x, y, z), (rot[0], rot[1], rot[2] + yaw_deg))

    def to_scene(x, y, z):
        cx, cy, cz = W(x, y, z)
        return (cx / M, cz / M, -cy / M)

    # ---- 底座 ----
    base = [
        col(Cylinder(200, 30, align=BOT).moved(loc(0, 0, 0)), DARK),
        col(Cylinder(160, L1 - 30, align=BOT).moved(loc(0, 0, 30)), DARK),
    ] + [col(Cylinder(12, 12, align=BOT).moved(loc(185 * math.cos(a), 185 * math.sin(a), 30)), "#222") for a in (0.4, 0.4 + math.pi / 2, 0.4 + math.pi, 0.4 + 1.5 * math.pi)]
    base_c = sub_compound(f"{prefix}base", base)

    # ---- J1 ----
    j1_parts = [
        col(Cylinder(130, 220, align=BOT).moved(loc(0, 0, L1)), color),
        col(Box(200, 260, 160, align=BOT).moved(loc(0, 0, L1 + 200)), color),
    ]
    # J2 軸心（本地）
    p2 = (0.0, 0.0, L1 + H1)
    # 下臂方向：從 J2 起，繞 Y 軸擺 q2（0 = 垂直向上）
    d2 = (math.sin(q2), 0.0, math.cos(q2))
    p3 = (p2[0] + d2[0] * L2, 0.0, p2[2] + d2[2] * L2)
    # 上臂方向：q3 相對於下臂
    a3 = q2 + q3 - math.pi / 2  # 使 q3=90° 時上臂水平
    d3 = (math.cos(a3) if False else math.sin(q2 + q3), 0.0, math.cos(q2 + q3))
    p4 = (p3[0] + d3[0] * L3, 0.0, p3[2] + d3[2] * L3)
    d5 = (math.sin(q2 + q3 + q5), 0.0, math.cos(q2 + q3 + q5))
    p6 = (p4[0] + d5[0] * LW, 0.0, p4[2] + d5[2] * LW)

    def seg(p_from, direction, length, r, colr):
        """沿方向 direction（本地 XZ 平面單位向量）從 p_from 起的圓柱。"""
        ang = math.degrees(math.atan2(direction[0], direction[2]))  # 繞 Y 的傾角
        c = Cylinder(r, length, align=BOT).rotate(Axis.Y, ang)
        return col(c.moved(loc(*p_from)), colr)

    # ---- J2 模組（關節殼 + 下臂）----
    j2_parts = [
        col(Cylinder(120, 300).rotate(Axis.X, 90).moved(loc(*p2)), DARK),
        col(Cylinder(60, 340).rotate(Axis.X, 90).moved(loc(*p2)), "#888"),
        seg(p2, d2, L2, 85, color),
    ]
    # ---- J3 模組（肘 + 上臂 + 線纜）----
    j3_parts = [
        col(Cylinder(105, 260).rotate(Axis.X, 90).moved(loc(*p3)), DARK),
        col(Cylinder(50, 300).rotate(Axis.X, 90).moved(loc(*p3)), "#888"),
        seg(p3, d3, L3, 75, color),
        seg((p3[0], 60, p3[2] + 100), d3, L3 * 0.9, 20, "#222"),
    ]
    # ---- 腕部模組 ----
    wrist_parts = [
        seg(p4, d5, LW * 0.6, 75, DARK),
        seg((p4[0] + d5[0] * LW * 0.6, 0, p4[2] + d5[2] * LW * 0.6), d5, LW * 0.4, 62, color),
    ]
    # 法蘭與工具
    ang6 = math.degrees(math.atan2(d5[0], d5[2]))
    flange_loc = loc(*p6, rot=(0, ang6, 0))
    flange = tool_flange(f"{prefix}flange").moved(flange_loc)
    tool_loc = Location(W(p6[0] + d5[0] * 14, p6[1], p6[2] + d5[2] * 14), (0, ang6, yaw_deg))
    if tool == "gripper":
        tool_c = gripper(f"{prefix}gripper").moved(tool_loc)
    elif tool == "vacuum":
        tool_c = vacuum_pads(f"{prefix}gripper").rotate(Axis.X, 180).moved(Location(W(p6[0] + d5[0] * 60, p6[1], p6[2] + d5[2] * 60), (0, ang6, yaw_deg)))
    else:
        tool_c = comp(f"{prefix}tool", electric_screwdriver("screwdriver").moved(tool_loc), industrial_camera(f"{prefix}cam").moved(Location(W(p6[0] + d5[0] * 30, 60, p6[2] + d5[2] * 30), (0, ang6, yaw_deg))))
    tool_c.label = f"{prefix}gripper" if tool != "screwdriver" else f"{prefix}tool"

    # 軸向（場景座標）：J1 垂直 Y；J2/J3/J5 為本地 Y 軸 → 場景中 = 水平且垂直於手臂平面
    axis_v = (0.0, 1.0, 0.0)
    ax_local = to_scene(0, 1, 0)
    base_scene = to_scene(0, 0, 0)
    axis_h = (ax_local[0] - base_scene[0], ax_local[1] - base_scene[1], ax_local[2] - base_scene[2])

    wrist = sub_moving(f"{prefix}wrist", "rev", to_scene(*p4), axis_h, wrist_parts + [flange, tool_c])
    j3 = sub_moving(f"{prefix}j3", "rev", to_scene(*p3), axis_h, j3_parts + [wrist])
    j2 = sub_moving(f"{prefix}j2", "rev", to_scene(*p2), axis_h, j2_parts + [j3])
    j1 = sub_moving(f"{prefix}j1", "rev", to_scene(0, 0, L1), axis_v, j1_parts + [j2])
    return base_c, j1
