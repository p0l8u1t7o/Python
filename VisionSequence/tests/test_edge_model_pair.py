"""任意輪廓雙邊寬度與斷裂的幾何真值回歸。"""

import math
from typing import Any

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.demo import seal_width_flow
from apps.vision.demo_images import seal_path, seal_scene
from apps.vision.graph import validate_graph
from apps.vision.tools import defects
from apps.vision.tools.base import TRANSFORM_IN, Result, ToolContext
from apps.vision.tools.builtin.edge_defect import (
    EdgeDefectTool, _COLORS, _model_payload, _reference_model, defect_rect,
)
from apps.vision.tools.builtin.locate import CaliperHit, caliper_series, find_edges_rows, pick_edge, pick_pair, polyline_geometry, to_gray
from apps.vision.tools.roi import apply_transform, region_overlay
from tests._helpers import run_tool


class EdgeModelPairTests(SimpleTestCase):
    def test_caliper_batches_equal_one_sampling_pass_on_odd_sizes(self):
        import itertools
        from dataclasses import asdict
        from unittest.mock import patch

        native_remap = cv2.remap

        def unlimited_remap(image, map_x, map_y, interpolation, **kwargs):
            # 只模擬底層列數上限放大：座標先整批建立，原函式仍一次平均、一次找邊。
            # remap 各像素獨立；在原生可接受的尺寸另驗此模擬逐像素相同。
            return np.concatenate([native_remap(image, map_x[i:i + 16000], map_y[i:i + 16000], interpolation, **kwargs)
                                   for i in range(0, len(map_x), 16000)], axis=0)

        variants = [("single", select, "first_last", polarity) for select in ("first", "last", "strongest")
                    for polarity in ("any", "dark_to_light", "light_to_dark")]
        variants += [("pair", "strongest", pair_mode, polarity) for pair_mode in ("first_last", "widest", "narrowest", "strongest", "expected")
                     for polarity in ("any", "bright", "dark")]
        checked = 0
        for (width, height), dtype, count in itertools.product([(333, 97), (1001, 701)], (np.uint8, np.uint16, np.float32), (100, 400)):
            x, y = np.meshgrid(np.arange(width), np.arange(height))
            image = np.where(np.abs(y - height / 2 - 4 * np.sin(x / 30)) < 7, 210, 25).astype(dtype)
            image[:, width // 2:width // 2 + 9] = 25
            geometry = polyline_geometry([[20, height / 2], [width - 20, height / 2]], False, count=count)
            for mode, select, pair_mode, polarity in variants:
                params = {"search": 26, "height": 99, "mode": mode, "select": select, "pair_mode": pair_mode,
                          "polarity": polarity if mode == "single" else "any", "pair_polarity": polarity if mode == "pair" else "any",
                          "expected_width": 14 if pair_mode == "expected" else 0, "smoothing": 1 if count == 100 else 3, "threshold": 2}
                actual = caliper_series(image, *geometry, **params)
                with patch("apps.vision.tools.builtin.locate.cv2.remap", side_effect=unlimited_remap):
                    expected = _legacy_caliper_series(image, *geometry, **params)
                for a, b in zip(actual, expected):
                    np.testing.assert_equal(list(asdict(a).values()), list(asdict(b).values()))
                self.assertEqual(len(actual), len(expected))
                checked += 1
            # 連續原生呼叫與模擬上限呼叫也要逐像素一致，避免用不同內插當參考。
            mx, my = np.meshgrid(np.linspace(0, width - 1, 31, dtype=np.float32), np.linspace(0, height - 1, 17000, dtype=np.float32))
            np.testing.assert_array_equal(native_remap(image, mx, my, cv2.INTER_LINEAR), unlimited_remap(image, mx, my, cv2.INTER_LINEAR))
        print(f"Caliper equivalence: {checked} variants on 333x97 and 1001x701; all fields identical")

    def test_single_mode_matches_frozen_reference_on_odd_sizes(self):
        import itertools

        from apps.vision.tools import base
        from apps.vision.tools.roi import mask_for

        tool = base.get("edge_model_defect")
        for width, height in [(333, 97), (1001, 701)]:
            points = [[30, 25], [width - 30, 25], [width - 30, height - 25], [30, height - 25]]
            image = mask_for({"shape": "polygon", "points": points}, width, height)
            image[20:32, width // 2:width // 2 + 15] = 0
            for dtype, closed, polarity, select, direction in itertools.product(
                (np.uint8, np.uint16, np.float32), (False, True), ("any", "dark_to_light", "light_to_dark"),
                ("strongest", "first", "last"), ("both", "inward", "outward"),
            ):
                params = {"model": {"points": points, "closed": closed}, "calipers": 80, "search": 24,
                          "polarity": polarity, "edge_select": select, "direction": direction, "step_threshold": 2}
                inputs = {"image": image.astype(dtype) * (257 if dtype == np.uint16 else 1)}
                def context():
                    return ToolContext(run_id="test", flow_id=1, node={"id": "edge", "type": tool.key, "params": params},
                                       inputs=inputs, context={}, moment=0, log=lambda *a, **k: None,
                                       asset_path=lambda _: None, grab=lambda _: None, preview=True, depth=tool.accepts)
                old, new = _LegacySingle().execute(context()), tool.execute(context())
                np.testing.assert_array_equal(old.outputs.pop("image"), new.outputs.pop("image"))
                self.assertEqual(old.outputs, new.outputs)
                self.assertEqual((old.status, old.branch, old.message, old.overlays, old.detail),
                                 (new.status, new.branch, new.message, new.overlays, new.detail))

    def params(self, **extra):
        return {"mode": "pair", "pair_polarity": "bright", "model": {"version": 1, "image_size": [1001, 701],
                "points": seal_path().tolist(), "closed": False}, "calipers": 1200, "search": 24,
                "caliper_width": 1, "smoothing": 1, "threshold": 3, "width_min": 9, "width_max": 15, **extra}

    def test_s_curve_width_fracture_and_transformed_truth(self):
        points = seal_path()
        arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        truth = {"width": arc[[360, 540]], "fracture": arc[[880, 1020]]}
        for angle, dx, dy in [(0, 0, 0), (12, 25, -18), (-12, -25, 18)]:
            with self.subTest(angle=angle):
                image = seal_scene(True, angle, dx, dy)
                before = image.copy()
                transform = {"dx": dx, "dy": dy, "dtheta": angle, "pivot": [500, 350]}
                result = run_tool("edge_model_defect", image, self.params(), inputs={"_transform": transform})
                self.assertEqual(result.status, "ng")
                self.assertEqual([d["type"] for d in result.outputs["defects"]], ["width", "fracture"])
                for defect in result.outputs["defects"]:
                    # 缺陷起訖的弧長座標是位置真值；彎曲段的最小矩形中心不必落在曲線上。
                    actual = [defect["position"], defect["position"] + defect["length"]]
                    error = np.max(np.abs(truth[defect["type"]] - actual))
                    self.assertLess(error, 1.5, f"Boundary position error {error:.4f}px")
                np.testing.assert_array_equal(image, before)

    def test_clean_width_median_absolute_limits_and_polarities(self):
        for polarity in ("bright", "dark", "any"):
            image = seal_scene()
            if polarity == "dark":
                image = 255 - image
            good = run_tool("edge_model_defect", image, self.params(pair_polarity=polarity))
            self.assertEqual(good.status, "ok")
            self.assertLess(abs(np.median(good.outputs["deviations"])), 0.01)
            narrow = run_tool("edge_model_defect", image, self.params(pair_polarity=polarity, width_min=15, threshold=0))
            wide = run_tool("edge_model_defect", image, self.params(pair_polarity=polarity, width_max=10, threshold=0))
            for result in (narrow, wide):
                self.assertEqual(result.status, "ng")
                self.assertTrue(all(d["type"] == "width" for d in result.outputs["defects"]))

    def test_pair_step_and_missing_edge(self):
        result = run_tool("edge_model_defect", seal_scene(True), self.params(threshold=0, width_min=0, width_max=0, step_threshold=2, min_width=1))
        self.assertIn("step", [d["type"] for d in result.outputs["defects"]])
        missing = run_tool("edge_model_defect", np.zeros((701, 1001), np.uint8), self.params())
        self.assertEqual((missing.status, missing.branch), ("ng", "defect"))
        self.assertEqual(missing.outputs["defects"][0]["type"], "fracture")

    def test_graph_pair_model_and_fixture(self):
        graph = seal_width_flow("{SOURCE}")
        graph["nodes"].append({"id": "align", "type": "shape_align", "params": {}})
        graph["edges"].append({"id": "pose", "source": "align", "source_handle": "transform", "target": "seal", "target_handle": "_transform"})
        self.assertEqual(len(validate_graph(graph)["edges"]), 2)

    def test_large_caliper_width_matches_independent_safe_batches(self):
        from unittest.mock import patch

        image = seal_scene(True)
        params = self.params(caliper_width=99)
        actual = run_tool("edge_model_defect", image, params)

        def safe_batches(image, centers, scan, tangent, positions, **kwargs):
            hits = []
            for start in range(0, len(centers), 200):
                end = start + 200
                part = caliper_series(image, centers[start:end], scan[start:end], tangent[start:end], positions[start:end], **kwargs)
                for hit in part:
                    hit.index += start
                hits.extend(part)
            return hits

        with patch("apps.vision.tools.builtin.edge_defect.caliper_series", side_effect=safe_batches):
            expected = run_tool("edge_model_defect", image, params)
        np.testing.assert_array_equal(actual.outputs.pop("image"), expected.outputs.pop("image"))
        self.assertEqual(actual.outputs, expected.outputs)
        self.assertEqual(actual.overlays, expected.overlays)
        self.assertEqual(actual.message, expected.message)


# 派工前的單邊純計算副本；未來修改演算法時仍須逐值比對。
class _LegacySingle:
    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        teach_roi = ctx.roi()
        model = _model_payload(ctx.param("model"), image.shape)
        auto_taught = False
        if model is None:
            model, auto_taught = _reference_model(ctx, teach_roi)
        if model is None:
            return Result(
                outputs={"count": 0, "defects": [], "max_deviation": 0.0, "points": [], "deviations": [], "missing": [], "image": image},
                overlays=[],
                branch="defect", status="ng",
                message="No contour model is set, and no reference picture could teach one",
            )
        points = model["points"]
        closed = bool(model.get("closed", True))
        region = {"shape": "polygon" if closed else "polyline", "points": points}
        if TRANSFORM_IN in ctx.inputs:
            transform = ctx.inputs.get(TRANSFORM_IN)
            if transform is None:
                ctx.fixture_missing = True
            else:
                region = apply_transform(region, transform)
        moved_points = region.get("points") or []
        count = max(4, ctx.integer("calipers", 160))
        centers, scan, tangent, positions = polyline_geometry(moved_points, closed, count=count)
        wrap = closed
        if len(centers) == 0:
            return Result(
                outputs={"count": 0, "defects": [], "max_deviation": 0.0, "points": [], "deviations": [], "missing": [], "image": image},
                overlays=[region_overlay(region, label="model")],
                branch="defect", status="ng", message="The contour model is too short to sample",
            )
        hits = caliper_series(
            image, centers, scan, tangent, positions,
            search=ctx.number("search", 24), height=ctx.number("caliper_width", 3),
            polarity=str(ctx.param("polarity", "light_to_dark")), threshold=ctx.number("edge_threshold", 20),
            smoothing=ctx.integer("smoothing", 3), mode="single",
            select=str(ctx.param("edge_select", "strongest")),
        )
        series = np.array([h.offset for h in hits], dtype=np.float64)
        found = np.array([h.found for h in hits], dtype=bool)
        series[~found] = np.nan
        baseline = np.zeros(len(series), dtype=np.float64)
        deviation = series - baseline
        flags, kinds = EdgeDefectTool._flags(ctx, deviation, found, series, False, wrap)
        runs = EdgeDefectTool._runs(ctx, flags, kinds, wrap)
        items = self._describe_model(runs, hits, deviation, positions, wrap)
        limit = ctx.integer("max_defects", 0)
        bad = len(items) > limit if limit else bool(items)
        hit_points_out = [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found]
        missing = [int(i) for i in np.nonzero(~found)[0]]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="model")]
        overlays.append({"kind": "points", "points": hit_points_out, "color": "#22c55e"})
        for item in items:
            rect = item.get("rect")
            if rect:
                overlays.append({
                    "kind": "rect", "x": rect["cx"] - rect["w"] / 2, "y": rect["cy"] - rect["h"] / 2,
                    "w": rect["w"], "h": rect["h"], "angle": rect["angle"],
                    "color": _COLORS.get(item["type"], "#ef4444"), "width": 2, "label": item["type"],
                })
        worst = max((abs(i["max_deviation"] or 0.0) for i in items), default=0.0)
        note = "auto-taught contour, " if auto_taught else ""
        return Result(
            outputs={
                "count": len(items), "defects": items, "max_deviation": round(float(worst), 4),
                "points": hit_points_out,
                "deviations": [None if not np.isfinite(v) else round(float(v), 4) for v in deviation],
                "missing": missing, "image": image,
            },
            overlays=overlays, branch="defect" if bad else "ok", status="ng" if bad else "ok",
            message=(f"{note}{len(items)} faults, worst {worst:.2f}px"
                     if items else f"{note}clean ({int(found.sum())}/{len(hits)} calipers found the edge)"),
            detail={"model": {"image_size": model.get("image_size"), "closed": closed, "points": len(points)}, "auto_taught": auto_taught},
        )

    @staticmethod
    def _describe_model(runs: list[tuple[int, int, str]], hits: list[CaliperHit], deviation: np.ndarray,
                        positions: np.ndarray, wrap: bool) -> list[dict[str, Any]]:
        """任意輪廓缺陷段描述；沿邊長度用模型弧長座標，不用端點直線距離。"""
        n = len(hits)
        total = float(positions[-1] + (positions[1] - positions[0])) if wrap and len(positions) > 1 else float(positions[-1] if len(positions) else 0.0)
        items: list[dict[str, Any]] = []
        for start, end, kind in runs:
            indices = defects.seg_indices((start, end), n)
            pts: list[list[float]] = []
            for i in indices:
                h = hits[i]
                pts.append([h.x, h.y] if h.found else [h.cx, h.cy])
            values = np.array([deviation[i] for i in indices], dtype=np.float64)
            finite = values[np.isfinite(values)]
            peak = float(finite[np.argmax(np.abs(finite))]) if len(finite) else float("nan")
            if end >= start:
                length = float(positions[end] - positions[start])
            else:
                length = float(total - positions[start] + positions[end])
            if len(indices) > 1 and len(positions) > 1:
                length += float(np.median(np.diff(positions[: min(len(positions), max(2, len(positions)))])))
            rect = defect_rect(np.asarray(pts, dtype=np.float64))
            area = float(rect["w"] * rect["h"]) if rect else 0.0
            items.append({
                "type": kind, "start": int(start), "end": int(end), "count": len(indices),
                "length": round(max(0.0, length), 3), "area": round(area, 3),
                "max_deviation": round(peak, 4) if np.isfinite(peak) else None,
                "peak": round(peak, 4) if np.isfinite(peak) else None,
                "direction": ("outward" if peak > 0 else "inward") if np.isfinite(peak) else "missing",
                "position": round(float(positions[start]), 3),
                "rect": rect,
            })
        return items



def _legacy_caliper_series(
    image: np.ndarray,
    centers: np.ndarray,
    scan: np.ndarray,
    tangent: np.ndarray,
    positions: np.ndarray,
    *,
    search: float,
    height: float = 1.0,
    polarity: str = "any",
    threshold: float = 20.0,
    smoothing: int = 3,
    mode: str = "single",
    select: str = "strongest",
    pair_mode: str = "first_last",
    pair_polarity: str = "any",
    expected_width: float = 0.0,
) -> list[CaliperHit]:
    """沿一條幾何佈好的卡尺一次全掃：每把在掃描方向取 `search` px 的剖面（切向平均 `height` px 降噪），
    找一個邊（mode="single"）或一對邊（mode="pair"），回全圖座標。

    幾何由 `centers`／`scan`／`tangent`／`positions` 四個陣列描述（用 `line_geometry`／`arc_geometry` 產生，
    折線與任意路徑自己組也可以），所以直線、圓弧、路徑共用同一條程式路徑。取樣是一次 `cv2.remap`
    ((N×height) × samples)、找邊是一次 `find_edges_rows`——180 把卡尺也只有兩次呼叫。

    找不到邊的卡尺**照樣回傳**（`found=False`），因為打空是缺陷判斷的訊號之一。
    """
    img = to_gray(image)
    n = len(centers)
    if n == 0:
        return []
    span = max(2.0, float(search))
    samples = int(math.ceil(span)) + 1
    offsets = np.linspace(-span / 2.0, span / 2.0, samples)
    rows = max(1, int(round(float(height))))
    tang = (np.arange(rows, dtype=np.float64) - (rows - 1) / 2.0)
    # (N, rows, samples) 的取樣格：中心 + 掃描方向×位移 + 切向×降噪位移
    cx = centers[:, 0][:, None, None] + scan[:, 0][:, None, None] * offsets[None, None, :] + tangent[:, 0][:, None, None] * tang[None, :, None]
    cy = centers[:, 1][:, None, None] + scan[:, 1][:, None, None] * offsets[None, None, :] + tangent[:, 1][:, None, None] * tang[None, :, None]
    sampled = cv2.remap(img, cx.astype(np.float32).reshape(-1, samples), cy.astype(np.float32).reshape(-1, samples),
                        cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    profiles = sampled.reshape(n, rows, samples).astype(np.float32).mean(axis=1)
    step = span / max(1, samples - 1)

    def at(i: int, pos: float) -> tuple[float, float, float]:
        """剖面上的次像素位置 → (x, y, 相對中線的位移)。"""
        off = -span / 2.0 + pos * step
        return float(centers[i, 0] + scan[i, 0] * off), float(centers[i, 1] + scan[i, 1] * off), float(off)

    out: list[CaliperHit] = []
    for i, edges in enumerate(find_edges_rows(profiles, polarity, threshold, smoothing)):
        hit = CaliperHit(index=i, position=float(positions[i]), cx=float(centers[i, 0]), cy=float(centers[i, 1]))
        if mode == "pair":
            pair = pick_pair(edges, pair_mode, pair_polarity, float(expected_width))
            if pair is not None:
                (p0, s0), (p1, s1) = pair
                x0, y0, o0 = at(i, p0)
                x1, y1, o1 = at(i, p1)
                hit.found = True
                hit.x, hit.y, hit.strength, hit.offset = x0, y0, float(s0), o0
                hit.x2, hit.y2, hit.strength2 = x1, y1, float(s1)
                hit.width = abs(o1 - o0)
        else:
            e = pick_edge(edges, select)
            if e is not None:
                x0, y0, o0 = at(i, e[0])
                hit.found = True
                hit.x, hit.y, hit.strength, hit.offset = x0, y0, float(e[1]), o0
        out.append(hit)
    return out

