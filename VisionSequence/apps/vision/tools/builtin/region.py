"""區域工具：把 ROI 當資料在畫布上組合（多重 ROI 與排除區）。

量測區要挖掉孔位、字樣、反光帶、料號區是高頻需求。不動前端 ROI 編輯器（多形狀繪製會動到把手與命中判定），
改成**組合工具**：使用者放幾個 region_from_shape（各畫一個形狀）串進 region_combine，輸出 composite region
（`tools/roi.py` 檔頭的 {"shape": "composite", "ops": [...]}），下游任何走 crop()／mask_for() 的工具都直接吃。
"""

from __future__ import annotations

from typing import Any

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError
from apps.vision.tools.roi import composite, region_overlay, region_overlays

MODE_OPTIONS = [
    {"value": "subtract", "label": "Subtract (cut the regions out of the base)"},
    {"value": "union", "label": "Union (add the regions to the base)"},
    {"value": "intersect", "label": "Intersect (keep only where they overlap)"},
]


def _regions(value: Any) -> list[dict[str, Any]]:
    """multiple=True 的 region 埠：list；單一 dict 也接受；空的略過。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value] if value.get("shape") else []
    out = []
    for item in value:
        if isinstance(item, dict) and item.get("shape"):
            out.append(item)
        elif isinstance(item, list):
            out.extend(_regions(item))
    return out


class RegionFromShapeTool(Tool):
    key = "region_from_shape"
    label = "Region"
    description = (
        "Turns a drawn shape into a region output, so a second or third region can exist on the canvas — the exclusion zones "
        "and extra areas that Region combine puts together. It has no effect on the image."
    )
    category = "locate"
    icon = "Square"
    params = [Param("roi", "Shape", kind="roi", required=True, teach=True, help_text="Any shape: rectangle, rotated rectangle, circle, ellipse, annulus, polygon.")]
    inputs = [Port("image", "Image (for drawing)", "image", required=False)]
    outputs = [Port("region", "Region", "region")]

    def execute(self, ctx: ToolContext) -> Result:
        region = ctx.roi("roi")  # ctx.roi 會套上位置修正（接了 _transform 時形狀跟著工件走）
        if not isinstance(region, dict) or not region.get("shape"):
            raise ToolError("No shape is drawn")
        return Result(outputs={"region": dict(region)}, overlays=[region_overlay(region, label="region")], message=str(region.get("shape")))


class RegionCombineTool(Tool):
    key = "region_combine"
    label = "Region combine"
    description = (
        "Builds one region out of several: cut holes, labels or glare bands out of a measurement area (subtract), join separate "
        "areas into one (union), or keep only the overlap (intersect). The result goes into any tool's region input — blob, "
        "statistics, defect comparison and the rest all honour the combined mask."
    )
    category = "locate"
    icon = "Combine"
    params = [
        Param("base", "Base region", kind="roi", teach=True, help_text="The starting area. Leave it blank to use the first connected region instead."),
        Param("mode", "Mode", kind="select", default="subtract", options=MODE_OPTIONS),
    ]
    inputs = [
        Port("base", "Base region (dynamic)", "region", required=False),
        Port("regions", "Regions to combine", "region", required=False, multiple=True),
        Port("image", "Image (for drawing)", "image", required=False),
    ]
    outputs = [Port("region", "Region", "region"), Port("count", "Parts", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        base = ctx.roi("base")  # 輸入埠優先、其次畫布上畫的；ctx.roi 會套上位置修正
        others = _regions(ctx.inputs.get("regions"))
        if not (isinstance(base, dict) and base.get("shape")):
            if not others:
                raise ToolError("Draw a base region or connect at least one region")
            base, others = others[0], others[1:]
        mode = str(ctx.param("mode", "subtract"))
        if mode not in ("subtract", "union", "intersect"):
            mode = "subtract"
        region = composite(base, [(mode, r) for r in others])
        overlays = region_overlays(region)
        combined = region_overlay(region, color="#22c55e", label="combined")
        combined["dash"] = False
        combined["width"] = 2
        overlays.append(combined)
        return Result(outputs={"region": region, "count": len(others) + 1}, overlays=overlays,
                      message=f"{mode}: {len(others)} region(s) on the base")


TOOLS = [RegionFromShapeTool(), RegionCombineTool()]
