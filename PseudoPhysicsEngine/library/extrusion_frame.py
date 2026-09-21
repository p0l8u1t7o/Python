"""Parametric aluminium-extrusion equipment frame."""

from __future__ import annotations

from copy import deepcopy

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

ALUMINIUM = cq.Color(0.72, 0.74, 0.76)
BRACKET_GREY = cq.Color(0.35, 0.37, 0.40)
FOOT_BLACK = cq.Color(0.05, 0.06, 0.07)


def _profile(length: float, profile: float, axis: str) -> cq.Shape:
    """Make the prescribed square profile with four shallow grooves and a bore."""
    groove_width = profile * 0.28
    groove_depth = profile * 0.07
    cutter_length = length + profile
    solid = cq.Workplane("XY").box(profile, profile, length)
    solid = solid.cut(
        cq.Workplane("XY")
        .box(groove_width, groove_depth * 2, cutter_length)
        .translate((0, profile / 2, 0))
    )
    solid = solid.cut(
        cq.Workplane("XY")
        .box(groove_width, groove_depth * 2, cutter_length)
        .translate((0, -profile / 2, 0))
    )
    solid = solid.cut(
        cq.Workplane("XY")
        .box(groove_depth * 2, groove_width, cutter_length)
        .translate((profile / 2, 0, 0))
    )
    solid = solid.cut(
        cq.Workplane("XY")
        .box(groove_depth * 2, groove_width, cutter_length)
        .translate((-profile / 2, 0, 0))
    )
    solid = solid.cut(
        cq.Workplane("XY").circle(profile * 0.10).extrude(cutter_length / 2, both=True)
    )
    shape = solid.val()
    if axis == "x":
        return shape.rotate((0, 0, 0), (0, 1, 0), 90)
    if axis == "y":
        return shape.rotate((0, 0, 0), (1, 0, 0), 90)
    return shape


def _level_name(level: float) -> str:
    return f"{level:g}".replace("-", "n").replace(".", "p")


def _parameters(params: dict) -> tuple[float, float, float, float, int, list[float], bool]:
    size = params.get("size_mm", [1200, 800, 1800])
    length, width, height = (float(value) for value in size)
    profile = float(params.get("profile_mm", 40))
    posts = int(params.get("posts", 4))
    requested_levels = [float(value) for value in params.get("beam_levels_mm", [80, 1800])]
    levels = list(
        dict.fromkeys(
            min(max(level, profile / 2), height - profile / 2) for level in requested_levels
        )
    )
    return length, width, height, profile, posts, levels, bool(params.get("with_feet", True))


def build(params: dict) -> cq.Assembly:
    length, width, height, profile, post_count, levels, with_feet = _parameters(params)
    result = cq.Assembly(name=params.get("name", "extrusion_frame"))
    x_edge = (length - profile) / 2
    y_edge = (width - profile) / 2
    post_positions = {
        "fl": (-x_edge, -y_edge),
        "fr": (x_edge, -y_edge),
        "rl": (-x_edge, y_edge),
        "rr": (x_edge, y_edge),
    }
    if post_count == 6:
        post_positions.update({"ml": (-x_edge, 0.0), "mr": (x_edge, 0.0)})

    post_bottom = profile if with_feet else 0.0
    post_length = max(height - post_bottom, profile)
    for suffix, (x, y) in post_positions.items():
        result.add(
            _profile(post_length, profile, "z").translate((x, y, post_bottom + post_length / 2)),
            name=f"post_{suffix}",
            color=ALUMINIUM,
        )

    for level in levels:
        level_name = _level_name(level)
        for side, y in (("front", -y_edge), ("rear", y_edge)):
            result.add(
                _profile(length - 2 * profile, profile, "x").translate((0, y, level)),
                name=f"beam_{level_name}_{side}",
                color=ALUMINIUM,
            )
        for side, x in (("left", -x_edge), ("right", x_edge)):
            result.add(
                _profile(width - 2 * profile, profile, "y").translate((x, 0, level)),
                name=f"beam_{level_name}_{side}",
                color=ALUMINIUM,
            )
        bracket_size = profile * 0.45
        for suffix, (x, y) in post_positions.items():
            result.add(
                cq.Workplane("XY")
                .box(bracket_size, bracket_size, bracket_size)
                .translate((x, y, level)),
                name=f"bracket_{suffix}_{level_name}",
                color=BRACKET_GREY,
            )

    if with_feet:
        pad_size = profile * 1.5
        pad_height = profile * 0.22
        stem_size = profile * 0.35
        for suffix, (x, y) in post_positions.items():
            pad = (
                cq.Workplane("XY")
                .box(pad_size, pad_size, pad_height)
                .translate((x, y, pad_height / 2))
            )
            stem = (
                cq.Workplane("XY")
                .box(stem_size, stem_size, profile - pad_height)
                .translate((x, y, pad_height + (profile - pad_height) / 2))
            )
            result.add(
                cq.Compound.makeCompound([pad.val(), stem.val()]),
                name=f"foot_{suffix}",
                color=FOOT_BLACK,
            )
    return result


def module_definition(params: dict) -> ModuleDef:
    length, width, height, profile, _posts, levels, _with_feet = _parameters(params)
    params_schema = deepcopy(MODULE.params_schema)
    params_schema["properties"]["beam_levels_mm"]["items"]["maximum"] = height
    x_edge = (length - profile) / 2
    y_edge = (width - profile) / 2
    frames = {
        "mount": Frame(xyz=(0, 0, 0), free_space=True),
        "top_front": Frame(xyz=(0, -width / 2, height)),
        "top_rear": Frame(xyz=(0, width / 2, height)),
        "top_left": Frame(xyz=(-length / 2, 0, height)),
        "top_right": Frame(xyz=(length / 2, 0, height)),
        "inner_center": Frame(xyz=(0, 0, height / 2), free_space=True),
    }
    for level in levels:
        level_name = _level_name(level)
        frames.update(
            {
                f"rail_{level_name}_front": Frame(xyz=(0, -y_edge, level)),
                f"rail_{level_name}_rear": Frame(xyz=(0, y_edge, level)),
                f"rail_{level_name}_left": Frame(xyz=(-x_edge, 0, level)),
                f"rail_{level_name}_right": Frame(xyz=(x_edge, 0, level)),
            }
        )
    return ModuleDef(
        id="extrusion_frame",
        params_schema=params_schema,
        frames=frames,
        collision="box",
        meta=ModuleMeta(
            basis="依 40×40 鋁擠型材標準斷面與一般設備機架尺寸，斷面簡化為方廓加四面淺槽"
        ),
    )


MODULE = ModuleDef(
    id="extrusion_frame",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "size_mm": {
                "type": "array",
                "items": {"type": "number", "minimum": 200, "maximum": 6000},
                "minItems": 3,
                "maxItems": 3,
                "default": [1200, 800, 1800],
            },
            "profile_mm": {
                "type": "integer",
                "enum": [30, 40, 45, 60],
                "minimum": 30,
                "maximum": 60,
                "default": 40,
            },
            "posts": {
                "type": "integer",
                "enum": [4, 6],
                "minimum": 4,
                "maximum": 6,
                "default": 4,
            },
            "beam_levels_mm": {
                "type": "array",
                "items": {"type": "number", "minimum": 0, "maximum": 1800},
                "minItems": 1,
                "default": [80, 1800],
            },
            "with_feet": {"type": "boolean", "default": True},
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "inner_center": Frame(free_space=True)},
    collision="box",
    meta=ModuleMeta(basis="依 40×40 鋁擠型材標準斷面與一般設備機架尺寸，斷面簡化為方廓加四面淺槽"),
)
