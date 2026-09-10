"""旋轉工具預設路徑：保留修正前入口，奇數尺寸與全部選項逐值比對。"""

import math
import time
import cv2
from typing import Any
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from apps.vision import fixed_images
from apps.vision.tools.builtin.locate import (
    TemplateMatchTool, ToolContext, ToolError, Result, to_gray, crop, region_overlay,
    _templates, _search_template, _sorted_matches,
)
from tests._helpers import run_tool

def old_template_execute(self, ctx: ToolContext) -> Result:
    image = to_gray(ctx.require_image())
    templates = _templates(ctx)
    region = ctx.roi()
    c = crop(image, region, upright=True)
    search = np.ascontiguousarray(c.image)
    if search.size == 0:
        raise ToolError("The search region falls outside the image")

    threshold = float(np.clip(ctx.number("threshold", 0.7), 0, 1))
    max_n = max(1, ctx.integer("max_matches", 1))
    angle_range = abs(ctx.number("angle_range", 0))
    angle_step = max(0.5, ctx.number("angle_step", 5))
    if angle_range > 0:
        angles = [float(a) for a in np.arange(-angle_range, angle_range + 1e-6, angle_step)]
        if 0.0 not in angles:
            angles.append(0.0)
    else:
        angles = [0.0]
    deadline = (time.perf_counter() + ctx.number("timeout_ms", 0) / 1000.0) if ctx.number("timeout_ms", 0) > 0 else None

    pad = 0
    if ctx.flag("allow_clipped"):
        # 工件跨在搜尋範圍邊上：把邊界往外複製半個範本，比對照樣做得下去（分數會低一些）
        pad = max(t.shape[0] for _, t in templates) // 2
        search = cv2.copyMakeBorder(search, pad, pad, pad, pad, cv2.BORDER_REPLICATE)

    found: list[tuple[float, dict[str, Any]]] = []
    timed_out = False
    for label, tpl in templates:
        if deadline is not None and time.perf_counter() >= deadline:
            timed_out = True
            break
        th, tw = tpl.shape[:2]
        if search.shape[0] < th or search.shape[1] < tw:
            if len(templates) == 1:
                raise ToolError(f"The search region {search.shape[1]}×{search.shape[0]} is smaller than the template {tw}×{th}")
            continue
        for x, y, score, angle, rw, rh in _search_template(
            search, tpl, threshold=threshold, max_n=max_n, angles=angles,
            pyramid=ctx.flag("pyramid", True), subpixel=ctx.flag("subpixel", True), angle_step=angle_step,
            deadline=deadline,
        ):
            cx, cy = c.to_full(x - pad, y - pad)
            total_angle = angle + (float(region.get("angle", 0)) if region and region.get("shape") == "rotated_rect" else 0.0)
            found.append((score, {
                "x": round(cx - tw / 2, 2), "y": round(cy - th / 2, 2), "w": tw, "h": th,
                "cx": round(cx, 2), "cy": round(cy, 2), "score": round(score, 4), "angle": round(total_angle, 2),
                "label": label,
            }))

    # 跨模板的非極大抑制：中心靠得太近的視為同一個目標，留分數高的那一個
    found.sort(key=lambda t: -t[0])
    kept: list[dict[str, Any]] = []
    for _, m in found:
        span = max(2.0, min(m["w"], m["h"]) / 2)
        if all(math.hypot(m["cx"] - k["cx"], m["cy"] - k["cy"]) >= span for k in kept):
            kept.append(m)
        if len(kept) >= max_n:
            break
    matches = _sorted_matches(kept, str(ctx.param("sort_by", "score")))

    overlays: list[dict[str, Any]] = []
    if region is not None:
        overlays.append(region_overlay(region, label="search"))
    for i, m in enumerate(matches):
        tag = f"{m['score']:.2f}" + (f" {m['label']}" if m["label"] else "")
        overlays.append({"kind": "rect", "x": m["cx"] - m["w"] / 2, "y": m["cy"] - m["h"] / 2, "w": m["w"], "h": m["h"],
                         "angle": m["angle"], "color": "#22c55e", "width": 2, "label": f"{i + 1}: {tag}" if len(matches) > 1 else tag})
        overlays.append({"kind": "point", "x": m["cx"], "y": m["cy"], "color": "#22c55e"})
    best = max(matches, key=lambda m: m["score"]) if matches else None
    counts = [{"label": label, "count": sum(1 for m in matches if m["label"] == label)} for label, _ in templates] if len(templates) > 1 else []
    note = ", gave up on time" if timed_out else ""
    detected = bool(matches)
    valid = not ctx.fixture_missing
    expected = str(ctx.param("expected", "any"))
    status = "ok" if matches else "ng"
    if expected in ("present", "absent"):
        status = "ok" if valid and detected == (expected == "present") else "ng"
    return Result(
        outputs={
            "matches": matches, "count": len(matches),
            "best_x": best["cx"] if best else float("nan"), "best_y": best["cy"] if best else float("nan"),
            "best_score": best["score"] if best else 0.0, "best_angle": best["angle"] if best else 0.0,
            "best_label": (best["label"] if best else ""),
            "counts": counts, "detected": detected, "valid": valid,
        },
        overlays=overlays,
        branch="found" if matches else "not_found",
        status=status,
        message=f"{len(matches)} matches" + (f", best {best['score']:.3f} @ ({best['cx']:.1f}, {best['cy']:.1f})" if best else "") + note,
    )

class TemplateDefaultEquivalenceTests(SimpleTestCase):
    def test_odd_sizes_all_depths_rotation_sort_pyramid_and_clipping(self):
        count = 0
        template = np.full((35, 43), 40, np.uint8)
        template[7:28, 8:15] = 210
        template[20:28, 8:32] = 160
        desc = fixed_images.store(template, "Second mark")
        for h, w in ((197, 333), (237, 401)):
            image = np.full((h, w), 40, np.uint8)
            image[70:105, 110:153] = template
            for dtype in (np.uint8, np.uint16, np.float32):
                converted = image.astype(dtype) * (200 if dtype == np.uint16 else 1)
                for pyramid in (True, False):
                    for angle in (0, 20):
                        for sort in ("score", "x", "y", "xy", "angle"):
                            for clipped in (False, True):
                                params = {"pyramid": pyramid, "angle_range": angle, "sort_by": sort, "allow_clipped": clipped,
                                          "scale_x": 1 if clipped else 1.05, "scale_y": 1, "templates": [desc] if clipped else [],
                                          "roi": {"shape": "rect", "x": 3, "y": 5, "w": w - 8, "h": h - 12}}
                                with patch.object(TemplateMatchTool, "execute", old_template_execute):
                                    old = run_tool("template_match", converted, params, {"template_image": template})
                                new = run_tool("template_match", converted, params, {"template_image": template})
                                self.assertEqual((new.status, new.branch, new.message, new.overlays), (old.status, old.branch, old.message, old.overlays))
                                np.testing.assert_equal(new.outputs, old.outputs)
                                count += 1
        print(f"template default equivalence: {count} cases, 0 differences")
