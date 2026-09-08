"""量測工具共用的物理量換算；不修改像素結果或輸入影像。"""

from __future__ import annotations

from typing import Any

from apps.vision import calib
from apps.vision.tools.base import Param, ToolContext, ToolError


CALIBRATION_PARAM = Param(
    "calibration", "Calibration", kind="asset", accept="calibration", required=False, group="Advanced",
    help_text="Optional. Adds *_world outputs and unit, preferring robot mapping over world mapping. "
              "Lengths use the local area-equivalent pixel scale; angles are in degrees.",
)


def read_mapping(ctx: ToolContext, key: str = "calibration") -> tuple[dict, dict]:
    """讀取資產並優先使用機構映射，錯誤統一成工具錯誤。"""
    try:
        payload = calib.from_asset(ctx.param(key), ctx.asset_path)
    except calib.CalibError as exc:
        raise ToolError(str(exc)) from None
    for name in ("robot", "world"):
        mapping = payload.get(name) or {}
        if mapping.get("matrix") is not None:
            return payload, mapping
    raise ToolError("The calibration has no world or robot mapping")


def world_outputs(
    ctx: ToolContext, *, key: str = "calibration",
    points: dict[tuple[str, str], tuple[float, float]] | None = None,
    lengths: dict[str, tuple[float, tuple[float, float]]] | None = None,
    angles: dict[str, tuple[float, tuple[float, float]]] | None = None,
) -> dict[str, Any]:
    """點用原始埠鍵配對，例如 {("cx", "cy"): (x, y)}，各自追加 _world。

    長度與角度用 {原始埠鍵: (值, 量測位置)}；未選標定完全不讀資產。
    """
    if not ctx.param(key):
        return {}
    payload, mapping = read_mapping(ctx, key)
    matrix = mapping["matrix"]
    outputs: dict[str, Any] = {"unit": payload["unit"]}
    for (x_key, y_key), point in (points or {}).items():
        x, y = calib.apply(matrix, [point])[0]
        outputs[f"{x_key}_world"], outputs[f"{y_key}_world"] = float(x), float(y)
    for name, (length, at) in (lengths or {}).items():
        outputs[f"{name}_world"] = float(length) * calib.scale_at(matrix, at)
    for name, (angle, at) in (angles or {}).items():
        outputs[f"{name}_world"] = calib.angle_to_world(matrix, angle, at)
    return outputs
