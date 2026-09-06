"""條碼品質分級工具（barcode_grade，WP-09）：ISO 15415／15416／AIM DPM 的分項與總評，min_grade 判定。演算法在 apps/vision/grading.py。"""

from __future__ import annotations

from typing import Any

import numpy as np

from apps.vision import grading
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.preprocess import to_gray
from apps.vision.tools.roi import crop, region_overlay

STANDARD_OPTIONS = [
    {"value": "iso15415", "label": "ISO/IEC 15415 (2D: Data Matrix, QR)"},
    {"value": "iso15416", "label": "ISO/IEC 15416 (1D: EAN, UPC, Code 128, Code 39)"},
    {"value": "aim_dpm", "label": "AIM DPM (ISO/IEC TR 29158, direct part marks)"},
]
GRADE_OPTIONS = [{"value": g, "label": f"{g} ({v:.1f})"} for g, v in (("A", 4.0), ("B", 3.0), ("C", 2.0), ("D", 1.0), ("F", 0.0))]


class BarcodeGradeTool(Tool):
    key = "barcode_grade"
    label = "Barcode quality grade"
    description = (
        "Grades a 2D or 1D symbol the way a verifier does — ISO/IEC 15415 for Data Matrix and QR, ISO/IEC 15416 for linear codes, "
        "AIM DPM for direct part marks — reporting every parameter (contrast, modulation, fixed pattern damage, axial and grid "
        "non-uniformity, unused error correction, defects, decodability) with its own grade, the overall grade A to F, and whether it "
        "meets the minimum grade. Uses 8-bit grey levels as reflectance, so the numbers match a verifier's magnitude rather than certify it."
    )
    category = "detect"
    icon = "ScanBarcode"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect"], teach=True, help_text="The symbol and its quiet zone; leave blank for the whole image."),
        Param("standard", "Standard", kind="select", default="iso15415", options=STANDARD_OPTIONS, help_text="Linear symbols always grade under 15416; DPM uses cell contrast and cell modulation instead of the 15415 contrast and modulation."),
        Param("symbology", "Symbology", kind="select", default="auto", options=grading.SYMBOLOGY_OPTIONS),
        Param("aperture", "Aperture", kind="number", default=0, minimum=0, unit="px", help_text="Synthetic aperture diameter; 0 = 80% of the module size (50% for DPM)."),
        Param("min_grade", "Minimum grade", kind="select", default="C", options=GRADE_OPTIONS, teach=True, help_text="The overall grade must be this or better to pass."),
        Param("dpm_filter", "DPM pre-filter", kind="select", default="none", options=[{"value": "none", "label": "None"}, {"value": "median", "label": "Median 3×3"}],
              visible_when={"param": "standard", "in": ["aim_dpm"]}, group="Advanced", help_text="AIM DPM allows image processing before measurement."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("pass", "Pass", "ok"), flow_out("fail", "Fail", "critical"),
        Port("grade", "Grade", "string"), Port("grade_value", "Grade value", "number"), Port("params", "Parameters", "list"),
        Port("text", "Content", "string"), Port("symbology", "Symbology", "string"), Port("decoded", "Decoded", "bool"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region, upright=True)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        sub = np.ascontiguousarray(c.image)
        standard = str(ctx.param("standard", "iso15415"))
        try:
            out = grading.grade(sub, standard, str(ctx.param("symbology", "auto")), ctx.number("aperture", 0), str(ctx.param("dpm_filter", "none")))
        except grading.GradingError as exc:
            raise ToolError(str(exc)) from None
        min_grade = str(ctx.param("min_grade", "C")).upper()
        need = grading.LETTER_VALUE.get(min_grade, 2)
        # 1D 的總評是平均分數（3.5 以上才 A）；門檻以字母比：總評字母 ≥ min_grade
        got = grading.LETTER_VALUE[out["grade"]]
        ok = got >= need and out["text"] != ""
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if out.get("corners") is not None:
            pts = c.points_to_full(np.asarray(out["corners"], dtype=np.float64)).round(1).tolist()
            overlays.append({"kind": "polygon", "points": pts, "color": "#22c55e" if ok else "#ef4444", "width": 2, "label": f"{out['grade']} ({out['grade_value']:.1f}) {out['text'][:24]}"})
        worst = [p for p in out["params"] if p["grade"] == grading.LETTER_VALUE[out["grade"]] and p["key"] != "decode"] if out["text"] else []
        message = (f"{out['symbology']} grade {out['grade']} ({out['grade_value']:.1f}), minimum {min_grade}" + (f" — limited by {', '.join(p['label'].lower() for p in worst[:3])}" if worst and not ok else "")
                   if out["text"] else "No symbol decoded — grade F")
        return Result(
            outputs={"grade": out["grade"], "grade_value": out["grade_value"], "params": out["params"], "text": out["text"], "symbology": out["symbology"], "decoded": bool(out["text"])},
            overlays=overlays, branch="pass" if ok else "fail", status="ok" if ok else "ng", message=message, detail=out["detail"],
        )


TOOLS = [BarcodeGradeTool()]
