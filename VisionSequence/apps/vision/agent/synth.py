"""意圖 → graph 合成器（規則引擎的產出端）。

每種意圖一個合成器：掛使用者的 ROI、用 analysis 特徵自動調參，輸出
(graph, rationale)。graph 是標準格式（呼叫端再過 validate_graph）；
image_source 不綁來源（mode=auto：試跑吃上傳影像，存成流程後在編輯器選來源）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable

from apps.vision.agent.intents import Intent
from apps.vision.demo import GY, _edge, _node, _note
from apps.vision.tools import base as tools

#: 良品比對用：把某張影像的 ROI 裁成範本資產，回 asset id。(image_index, region, name) -> id
#: 把某張影像的 ROI 裁成固定影像描述子（`Param(kind="images")` 的元素）；裁不出來回 None。
MakeAsset = Callable[[int, dict[str, Any], str], "dict[str, Any] | None"]


def _picture_node(node_id: str, picture: dict[str, Any] | None, col: int, row: int, label: str) -> list[dict[str, Any]]:
    """參考圖節點：role=reference 的固定影像（批次測試送進來的待測圖不會取代它）。"""
    if not picture:
        return []
    return [_node(node_id, "fixed_image", col, row, label, images=[picture], mode="fixed", index=1, role="reference")]


def _src_gray(prompt_note: str) -> tuple[list[dict], list[dict]]:
    nodes = [
        _node("src", "image_source", 0, 0, "取像", mode="auto"),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _note("hint", 0, 1, "AI 助手", prompt_note),
    ]
    return nodes, [_edge("src", "gray")]


def _finish(nodes: list[dict], edges: list[dict], *, draw: bool = True, col: int = 6) -> dict[str, Any]:
    if draw:
        nodes.append(_node("draw", "draw_result", col, 2, "結果影像"))
        edges.append(_edge("src", "draw", "image", "image"))
    return {"nodes": nodes, "edges": edges}


def _region_of(regions: list[dict[str, Any]], idx: int = 0) -> dict[str, Any] | None:
    if idx < len(regions):
        return regions[idx].get("region")
    return None


def _roi_info(analysis: dict[str, Any], idx: int = 0) -> dict[str, Any]:
    rows = analysis.get("regions") or []
    if idx < len(rows) and not rows[idx].get("empty"):
        return rows[idx]
    return analysis.get("full") or {}


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _blob_min_area(info: dict[str, Any], polarity_dark: bool | None = None, floor: int = 30) -> int:
    """粒子最小面積：有粒子試探就取中位面積的 30%，否則取 ROI 面積的千分之一。"""
    blobs = info.get("blobs", {})
    dark, bright = blobs.get("dark", {}), blobs.get("bright", {})
    if polarity_dark is None:
        polarity_dark = dark.get("count", 0) >= bright.get("count", 0)
    probe = dark if polarity_dark else bright
    if probe.get("count"):
        return max(floor, int(probe.get("median_area", 0) * 0.3))
    return max(floor, int(info.get("area", info.get("w", 100) * info.get("h", 100)) * 0.001))


def synth_count(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    info = _roi_info(analysis)
    roi = _region_of(regions)
    dark = info.get("blobs", {}).get("dark", {})
    bright = info.get("blobs", {}).get("bright", {})
    invert = dark.get("count", 0) >= bright.get("count", 0)
    if intent.polarity in ("dark", "bright"):
        invert = intent.polarity == "dark"
    probe = dark if invert else bright
    min_area = max(30, int(probe.get("median_area", 0) * 0.3)) if probe.get("count") else max(30, int(info.get("w", 100) * info.get("h", 100) * 0.001))
    nodes, edges = _src_gray("由 AI 助手生成：計數流程。粒子抓不對時調「二值化」門檻與 blob 最小面積。")
    nodes += [
        _node("blur", "blur", 2, 0, "去雜訊", method="median", ksize=5),
        _node("thr", "threshold", 3, 0, "二值化", method="otsu", invert=invert),
        _node("open", "morphology", 4, 0, "開運算去雜點", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "粒子計數", roi=roi, min_area=min_area, min_count=0, sort_by="area",
              **({"min_circularity": 0.5} if intent.round_target else {})),
    ]
    edges += [_edge("gray", "blur"), _edge("blur", "thr"), _edge("thr", "open"), _edge("open", "blob")]
    if intent.expected_count is not None:
        nodes += [
            _node("cmp", "if_number", 6, 0, f"數量 = {intent.expected_count}？", operator="eq", threshold=intent.expected_count),
            _node("ok", "judge", 7, 0, "OK", verdict="ok"),
            _node("ng", "judge", 7, 1, "NG：數量不對", verdict="ng", label="count"),
        ]
        edges += [_edge("blob", "cmp", "count", "value"), _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow")]
    nodes.append(_node("out", "output", 6, 1, "輸出數量", name="count"))
    edges.append(_edge("blob", "out", "count", "value"))
    why = f"抓{'暗' if invert else '亮'}粒子（ROI 內{'暗' if invert else '亮'}粒子較多），最小面積 {min_area}px²" + ("，圓形度 ≥ 0.5 排除線段" if intent.round_target else "")
    if intent.expected_count is not None:
        why += f"；期望 {intent.expected_count} 個，不符走 NG"
    return _finish(nodes, edges), why


def synth_diameter(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    if roi and roi.get("shape") == "circle":
        r = float(roi.get("r", 50))
        roi = {"shape": "annulus", "cx": roi["cx"], "cy": roi["cy"], "r_inner": max(3.0, r * 0.6), "r_outer": r * 1.4}
    elif roi is None and info.get("circle", {}).get("found"):
        b = info.get("bounds") or {"x": 0, "y": 0, "w": analysis["width"], "h": analysis["height"]}
        r = float(info["circle"]["radius"])
        cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        roi = {"shape": "annulus", "cx": cx, "cy": cy, "r_inner": max(3.0, r * 0.6), "r_outer": r * 1.4}
    nodes, edges = _src_gray("由 AI 助手生成：圓直徑量測。環形 ROI 要蓋住圓的邊緣。")
    nodes += [
        _node("fc", "find_circle", 2, 0, "找圓", roi=roi, polarity="any", edge_threshold=20, num_rays=72),
        _node("dia", "formula", 3, 0, "直徑 = 2r", expression="a*2"),
        _node("nf", "judge", 3, 1, "NG：找不到圓", verdict="ng", label="not_found"),
    ]
    edges += [_edge("gray", "fc", "image", "image"), _edge("fc", "dia", "r", "a"), _edge("fc", "nf", "not_found", "_flow")]
    value_src, value_port, col = "dia", "value", 4
    unit = "px"
    if intent.mm_per_px:
        nodes.append(_node("cal", "calibration", col, 0, "像素校正", mode="pixel_size", pixel_size_mm=intent.mm_per_px))
        edges.append(_edge("dia", "cal", "value", "value"))
        value_src, value_port, col, unit = "cal", "mm", col + 1, "mm"
    if intent.nominal is not None:
        tol = intent.tol if intent.tol is not None else round(intent.nominal * 0.02, 3)
        nodes += [
            _node("tol", "tolerance_judge", col, 0, "直徑公差", nominal=intent.nominal, upper_tol=tol, lower_tol=-tol, unit=unit, name="diameter"),
            _node("jd", "judge", col + 1, 0, "OK / NG", verdict="by_input", label="diameter"),
        ]
        edges += [_edge(value_src, "tol", value_port, "value"), _edge("tol", "jd", "in_spec", "value")]
    nodes.append(_node("out", "output", col, 1, "輸出直徑", name=f"diameter_{unit}"))
    edges.append(_edge(value_src, "out", value_port, "value"))
    why = "找圓量直徑"
    if intent.mm_per_px:
        why += f"，以 {intent.mm_per_px:.4f} mm/px 換算"
    if intent.nominal is not None:
        why += f"，公差 {intent.nominal}±{intent.tol if intent.tol is not None else round(intent.nominal * 0.02, 3)}{unit}"
    return _finish(nodes, edges), why


def synth_width(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    nodes, edges = _src_gray("由 AI 助手生成：卡尺量寬。ROI 長邊要橫跨要量的兩條邊緣。")
    nodes += [_node("cal", "caliper", 2, 0, "卡尺量寬", roi=roi, polarity="any", edge_pair="widest")]
    edges += [_edge("gray", "cal", "image", "image")]
    value_src, value_port, col, unit = "cal", "width", 3, "px"
    if intent.mm_per_px:
        nodes.append(_node("calib", "calibration", col, 0, "像素校正", mode="pixel_size", pixel_size_mm=intent.mm_per_px))
        edges.append(_edge("cal", "calib", "width", "value"))
        value_src, value_port, col, unit = "calib", "mm", col + 1, "mm"
    if intent.nominal is not None:
        tol = intent.tol if intent.tol is not None else round(intent.nominal * 0.05, 3)
        nodes += [
            _node("tol", "tolerance_judge", col, 0, "寬度公差", nominal=intent.nominal, upper_tol=tol, lower_tol=-tol, unit=unit, name="width"),
            _node("jd", "judge", col + 1, 0, "OK / NG", verdict="by_input", label="width"),
        ]
        edges += [_edge(value_src, "tol", value_port, "value"), _edge("tol", "jd", "in_spec", "value")]
    nodes.append(_node("out", "output", col, 1, "輸出寬度", name=f"width_{unit}"))
    edges.append(_edge(value_src, "out", value_port, "value"))
    why = "卡尺在 ROI 內找最寬的邊緣對量距離"
    if intent.mm_per_px:
        why += f"，以 {intent.mm_per_px:.4f} mm/px 換算"
    return _finish(nodes, edges), why


def synth_angle(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi_a = _region_of(regions, 0)
    roi_b = _region_of(regions, 1)
    nodes, edges = _src_gray("由 AI 助手生成：兩邊夾角。兩個 ROI 各框住一條直邊。" + ("" if roi_b else "\n目前只圈了一個 ROI，請再圈第二條邊後重新生成。"))
    nodes += [
        _node("l1", "find_line", 2, 0, "邊 1", roi=roi_a, polarity="any", edge_threshold=20),
        _node("l2", "find_line", 2, 1, "邊 2", roi=roi_b, polarity="any", edge_threshold=20),
        _node("ang", "angle", 3, 0, "夾角", range="0_90"),
        _node("out", "output", 4, 1, "輸出夾角", name="angle_deg"),
        _node("nf", "judge", 3, 2, "NG：找不到邊", verdict="ng", label="no_edge"),
    ]
    edges += [
        _edge("gray", "l1", "image", "image"), _edge("gray", "l2", "image", "image"),
        _edge("l1", "ang", "line", "a"), _edge("l2", "ang", "line", "b"),
        _edge("l1", "nf", "not_found", "_flow"), _edge("l2", "nf", "not_found", "_flow"),
        _edge("ang", "out", "angle_deg", "value"),
    ]
    if intent.nominal is not None:
        tol = intent.tol if intent.tol is not None else 1.0
        nodes += [
            _node("rng", "in_range", 4, 0, "角度公差", low=intent.nominal - tol, high=intent.nominal + tol),
            _node("ok", "judge", 5, 0, "OK", verdict="ok"),
            _node("ng", "judge", 5, 1, "NG：角度超差", verdict="ng", label="angle"),
        ]
        edges += [_edge("ang", "rng", "angle_deg", "value"), _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow")]
    return _finish(nodes, edges), "兩條找線量夾角" + ("（缺第二個 ROI，記得補圈）" if not roi_b else "")


def _defect_polarity_dark(intent: Intent, info: dict[str, Any], analysis: dict[str, Any]) -> bool:
    """缺陷極性：使用者說了算；否則看所有影像裡「偏離背景的像素」哪邊多（缺陷只在部分影像出現，所以跨影像取最大）；都沒證據才用粒子數。"""
    if intent.polarity in ("dark", "bright"):
        return intent.polarity == "dark"
    dark_ev = bright_ev = 0.0
    for row in analysis.get("images") or []:
        o = row.get("outliers") or {}
        dark_ev = max(dark_ev, float(o.get("dark", 0.0)))
        bright_ev = max(bright_ev, float(o.get("bright", 0.0)))
    if max(dark_ev, bright_ev) >= 1e-4 and dark_ev != bright_ev:
        return dark_ev > bright_ev
    blobs = info.get("blobs", {})
    return blobs.get("dark", {}).get("count", 0) >= blobs.get("bright", {}).get("count", 0)


def synth_defect(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    mean = float(info.get("mean", 128))
    textured = float(info.get("edge_ratio", 0)) > 0.08  # 規律紋理：先頻域低通把紋理濾掉再抓異常
    sigma = float(info.get("smooth_mad" if textured else "mad", info.get("std", 20)) or info.get("std", 20))  # 穩健 σ：缺陷本身不會把門檻推遠；紋理面用低通後的 σ
    dark_more = _defect_polarity_dark(intent, info, analysis)
    offset = max(30.0, 3 * sigma)
    thr = max(5.0, mean - offset) if dark_more else min(250.0, mean + offset)
    min_area = int(_clip(float(info.get("area", info.get("w", 100) * info.get("h", 100))) * 0.0005, 50, 2000))
    nodes, edges = _src_gray("由 AI 助手生成：表面缺陷。門檻＝ROI 平均灰階往" + ("暗" if dark_more else "亮") + "偏 3σ（穩健）；誤抓就把門檻再往外調、最小面積調大。" + ("\n偵測到規律紋理：先以頻域低通濾掉紋理。" if textured else ""))
    if textured:
        nodes.append(_node("fft", "fft_filter", 2, 0, "頻域低通去紋理", mode="lowpass", cutoff=0.08))
        edges.append(_edge("gray", "fft"))
        pre = "fft"
    else:
        nodes.append(_node("blur", "blur", 2, 0, "去雜訊", method="gaussian", ksize=5))
        edges.append(_edge("gray", "blur"))
        pre = "blur"
    nodes += [
        _node("thr", "threshold", 3, 0, "抓異常", method="fixed", threshold=int(thr), invert=dark_more),
        _node("open", "morphology", 4, 0, "開運算", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "缺陷 blob", roi=roi, threshold_method="fixed", threshold=128, polarity="bright", min_area=min_area, min_count=0),
        _node("cmp", "if_number", 6, 0, "沒有缺陷？", operator="eq", threshold=0),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG：表面缺陷", verdict="ng", label="defect"),
        _node("out", "output", 6, 1, "輸出缺陷數", name="defect_count"),
    ]
    edges += [
        _edge(pre, "thr"), _edge("thr", "open"), _edge("open", "blob"),
        _edge("blob", "cmp", "count", "value"), _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
    ]
    why = f"以固定門檻 {int(thr)} 抓{'暗' if dark_more else '亮'}異常（ROI 平均 {mean:.0f}、穩健 σ {sigma:.0f}，最小面積 {min_area}px²）" + ("，規律紋理先經頻域低通" if textured else "") + "；有良品範本時建議改用「良品比對」工具更穩"
    return _finish(nodes, edges), why


def synth_color_match(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    color = intent.color_hex or info.get("dominant", {}).get("hex", "#808080")
    tolerance = int(_clip(3 * float(info.get("color_std", 20) or 20), 25, 90))  # 區域內色彩越不均勻，容差越寬
    nodes = [
        _node("src", "image_source", 0, 0, "取像", mode="auto"),
        _node("chk", "color_check", 1, 0, "顏色比對", roi=roi, color=color, space="rgb", tolerance=tolerance),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：顏色不符", verdict="ng", label="color"),
        _node("stat", "color_stats", 1, 1, "顏色統計", roi=roi),
        _node("out", "output", 2, 2, "輸出色碼", name="hex"),
        _note("hint", 0, 1, "AI 助手", f"由 AI 助手生成：顏色比對。目標色 {color} 取自你圈的 ROI 主色，容差可在工具頁調整。"),
    ]
    edges = [
        _edge("src", "chk"),
        _edge("chk", "ok", "match", "_flow"), _edge("chk", "ng", "mismatch", "_flow"),
        _edge("src", "stat", "image", "image"), _edge("stat", "out", "hex", "value"),
    ]
    return _finish(nodes, edges, col=3), f"ROI 平均色與目標色 {color} 比距離（容差 {tolerance}，依區域色彩離散度）"


def synth_color_presence(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    info = _roi_info(analysis)
    dom = info.get("dominant", {"h": 0, "s": 128, "v": 128})
    h = float(dom.get("h", 0))
    b = info.get("bounds")
    area = int(b["w"] * b["h"]) if b else int(analysis["width"] * analysis["height"] * 0.05)
    min_count = max(500, area // 4)
    nodes = [
        _node("src", "image_source", 0, 0, "取像", mode="auto"),
        _node("mask", "color_range", 1, 0, "目標色遮罩",
              h_low=max(0, int(h - 12)), h_high=min(179, int(h + 12)),
              s_low=max(0, int(float(dom.get("s", 128)) * 0.4)), s_high=255,
              v_low=max(0, int(float(dom.get("v", 128)) * 0.4)), v_high=255),
        _node("cnt", "pixel_count", 2, 0, "計數", min_count=min_count),
        _node("cmp", "if_number", 3, 0, "夠多嗎？", operator="ge", threshold=min_count),
        _node("ok", "judge", 4, 0, "OK：有料", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：缺料", verdict="ng", label="missing"),
        _node("out", "output", 3, 1, "輸出像素數", name="pixels"),
        _note("hint", 0, 1, "AI 助手", "由 AI 助手生成：顏色有無。HSV 範圍取自 ROI 主色；光源變動大時放寬 S/V 下限。"),
    ]
    edges = [
        _edge("src", "mask"), _edge("mask", "cnt"),
        _edge("cnt", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("cnt", "out", "count", "value"),
    ]
    return _finish(nodes, edges, col=4), f"以 H≈{h:.0f} 的顏色範圍抓目標色，至少 {min_count}px 算有料"


def synth_presence(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    polarity_dark = intent.polarity == "dark" if intent.polarity else None
    min_area = _blob_min_area(info, polarity_dark)
    if polarity_dark is None:
        polarity_dark = info.get("blobs", {}).get("dark", {}).get("count", 0) >= info.get("blobs", {}).get("bright", {}).get("count", 0)
    nodes, edges = _src_gray("由 AI 助手生成：有無檢測。ROI 內抓得到粒子＝有料。")
    nodes += [
        _node("blob", "blob", 2, 0, "找料件", roi=roi, polarity="dark" if polarity_dark else "bright", min_area=min_area, min_count=1),
        _node("ok", "judge", 3, 0, "OK：有料", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG：缺料", verdict="ng", label="missing"),
        _node("out", "output", 3, 2, "輸出數量", name="count"),
    ]
    edges += [
        _edge("gray", "blob", "image", "image"),
        _edge("blob", "ok", "found", "_flow"), _edge("blob", "ng", "not_found", "_flow"),
        _edge("blob", "out", "count", "value"),
    ]
    return _finish(nodes, edges, col=4), f"ROI 內以 Otsu 門檻找{'暗' if polarity_dark else '亮'}粒子（最小面積 {min_area}px²），有→OK、無→NG"


def synth_brightness(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    mean = float(info.get("mean", 128))
    if intent.range_low is not None and intent.range_high is not None:
        low, high = int(min(intent.range_low, intent.range_high)), int(max(intent.range_low, intent.range_high))
    else:
        low, high = max(0, int(mean * 0.7)), min(255, int(mean * 1.3 + 10))
    nodes, edges = _src_gray("由 AI 助手生成：亮度守門。範圍以目前影像的平均亮度 ±30% 起跳。")
    nodes += [
        _node("inten", "intensity", 2, 0, "亮度統計", roi=roi),
        _node("rng", "in_range", 3, 0, "亮度範圍", low=low, high=high),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：曝光異常", verdict="ng", label="exposure"),
        _node("out", "output", 3, 1, "輸出平均亮度", name="mean"),
    ]
    edges += [
        _edge("gray", "inten", "image", "image"),
        _edge("inten", "rng", "mean", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("inten", "out", "mean", "value"),
    ]
    return _finish(nodes, edges, col=4), f"平均亮度 {mean:.0f}，範圍設 {low}~{high}"


def synth_focus(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    """對焦／清晰度守門：sharpness 分數低於「目前影像的一半」判 NG；雜訊會讓分數虛高，所以一併輸出 noise。"""
    roi = _region_of(regions)
    info = _roi_info(analysis)
    score = float(info.get("sharpness") or 0.0)
    low = round(score * 0.5, 4) if score > 0 else 0.0
    nodes, edges = _src_gray("由 AI 助手生成：對焦守門。門檻是目前這張（視為對焦良好）分數的一半；換鏡頭或光源後重新試執行再調。"
                             "雜訊會讓清晰度虛高，低光高增益時請一起看 noise。")
    nodes += [
        _node("sharp", "sharpness", 2, 0, "清晰度", roi=roi, method="laplacian", normalize=True, noise_estimate=True),
        _node("rng", "in_range", 3, 0, "清晰度門檻", low=low, high=1000000),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：失焦或模糊", verdict="ng", label="out_of_focus"),
        _node("out", "output", 3, 1, "輸出清晰度", name="sharpness"),
        _node("out2", "output", 3, 2, "輸出雜訊", name="noise"),
    ]
    edges += [
        _edge("gray", "sharp", "image", "image"),
        _edge("sharp", "rng", "score", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("sharp", "out", "score", "value"), _edge("sharp", "out2", "noise", "value"),
    ]
    return _finish(nodes, edges, col=4), f"目前清晰度 {score:.3f}，最低門檻設 {low:.3f}"


def synth_roundness(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    """真圓度：find_circle 的邊緣點 → gdt_measure 最小區域圓，環寬超過公差帶判 NG。"""
    roi = _region_of(regions)
    tol = float(intent.tol) if intent.tol else 2.0
    unit = "mm" if intent.unit == "mm" and intent.mm_per_px else "px"
    gdt_params: dict[str, Any] = {"mode": "roundness", "tolerance": tol, "unit": unit}
    if unit == "mm":
        gdt_params["mm_per_px"] = float(intent.mm_per_px)
    nodes, edges = _src_gray("由 AI 助手生成：真圓度。find_circle 沿 ROI 徑向找邊緣點，gdt_measure 以最小區域圓（兩個同心圓的最窄環）量圓度，"
                             f"公差帶 {tol:g} {unit}。孔太小或邊緣糊時把 ROI 貼緊孔緣。")
    nodes += [
        _node("circ", "find_circle", 2, 0, "找圓", roi=roi),
        _node("gdt", "gdt_measure", 3, 0, "真圓度", **gdt_params),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：真圓度超差", verdict="ng", label="roundness"),
        _node("out", "output", 3, 1, "輸出圓度偏差", name="roundness"),
    ]
    edges += [
        _edge("gray", "circ", "image", "image"),
        _edge("circ", "gdt", "points", "points"),
        _edge("gdt", "ok", "pass", "_flow"), _edge("gdt", "ng", "fail", "_flow"),
        _edge("gdt", "out", "deviation", "value"),
    ]
    return _finish(nodes, edges, col=4), f"真圓度公差帶 {tol:g} {unit}"


def synth_template(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    """套用內建範本：取像節點改成 auto（吃上傳影像），其餘照範本；找不到範本就退回資訊流程。"""
    from apps.vision import demo
    from apps.vision.api_more import SOURCE_PLACEHOLDER, instantiate

    entry = next((e for e in demo.BUILTIN_TEMPLATES if e[0] == intent.template_key), None)
    if entry is None:
        return synth_generic(intent, regions, analysis)
    key, name, desc, _category, builder = entry
    graph = instantiate(builder(SOURCE_PLACEHOLDER), source_id=None)
    for node in graph.get("nodes", []):
        if node.get("type") == "image_source":
            node.setdefault("params", {}).update({"source_id": "", "mode": "auto"})
    graph.setdefault("nodes", []).append(_note("ai_hint", 0, 3, "AI 助手", f"由 AI 助手套用範本「{name}」：{desc}\n請依實際影像調整各步驟的區域與門檻。"))
    return graph, f"套用範本「{name}」（{key}）：{desc}"


def synth_barcode(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    nodes, edges = _src_gray("由 AI 助手生成：讀碼。標籤斜貼讀不到時，前面加「透視校正」工具拉正。")
    nodes += [
        _node("bc", "barcode", 2, 0, "讀碼", roi=roi, **({"expected": intent.expected_text} if intent.expected_text else {})),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG：讀不到碼", verdict="ng", label="no_code"),
        _node("out", "output", 3, 2, "輸出內容", name="code"),
    ]
    edges += [
        _edge("gray", "bc", "image", "image"),
        _edge("bc", "ok", "found", "_flow"), _edge("bc", "ng", "not_found", "_flow"),
        _edge("bc", "out", "first", "value"),
    ]
    return _finish(nodes, edges, col=4), "ROI 內讀一維碼／QR"


def _annulus_for(region: dict[str, Any] | None) -> dict[str, Any] | None:
    """圓形 ROI → 蓋住圓緣的環（找圓要的形狀）；其他形狀原樣。"""
    if region and region.get("shape") == "circle":
        r = float(region.get("r", 50))
        return {"shape": "annulus", "cx": region["cx"], "cy": region["cy"], "r_inner": max(3.0, r * 0.6), "r_outer": r * 1.4}
    return region


def _expand_rect(b: dict[str, Any], factor: float, width: int, height: int) -> dict[str, Any]:
    """把 bounds 各邊外擴 factor 倍自身尺寸並夾在影像內（範本比對的搜尋區）。"""
    x0 = max(0, int(b["x"] - b["w"] * factor))
    y0 = max(0, int(b["y"] - b["h"] * factor))
    x1 = min(int(width), int(b["x"] + b["w"] * (1 + factor)))
    y1 = min(int(height), int(b["y"] + b["h"] * (1 + factor)))
    return {"shape": "rect", "x": x0, "y": y0, "w": max(1, x1 - x0), "h": max(1, y1 - y0)}


def _image_size(analysis: dict[str, Any], image_idx: int) -> tuple[int, int]:
    imgs = analysis.get("images") or []
    if 0 <= image_idx < len(imgs):
        return int(imgs[image_idx]["width"]), int(imgs[image_idx]["height"])
    return int(analysis["width"]), int(analysis["height"])


def synth_text(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    dark = intent.polarity != "bright" if intent.polarity else float(info.get("dark_ratio", 0.5)) < 0.5  # 暗部佔比低＝亮底暗字
    nodes, edges = _src_gray("由 AI 助手生成：印字有無（筆劃密度，不是 OCR）。字太細抓不到就把最小筆劃比例調低；整片污損會超過最大比例而判無。")
    nodes += [
        _node("txt", "text_presence", 2, 0, "印字有無", roi=roi, polarity="dark" if dark else "bright", min_ratio=0.02, max_ratio=0.7),
        _node("ok", "judge", 3, 0, "OK：有印字", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG：沒有印字", verdict="ng", label="no_text"),
        _node("out", "output", 3, 2, "輸出筆劃比例", name="ink_ratio"),
    ]
    edges += [
        _edge("gray", "txt", "image", "image"),
        _edge("txt", "ok", "present", "_flow"), _edge("txt", "ng", "absent", "_flow"),
        _edge("txt", "out", "ratio", "value"),
    ]
    return _finish(nodes, edges, col=4), f"ROI 內以自適應門檻抓{'暗' if dark else '亮'}筆劃，筆劃比例 2%～70% 算有印字"


def synth_distance(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi_a = _annulus_for(_region_of(regions, 0))
    roi_b = _annulus_for(_region_of(regions, 1))
    nodes, edges = _src_gray("由 AI 助手生成：兩孔中心距。兩個 ROI 各蓋住一個孔的邊緣。" + ("" if roi_b else "\n目前只圈了一個 ROI，請再圈第二個孔後重新生成。"))
    nodes += [
        _node("c1", "find_circle", 2, 0, "孔 1", roi=roi_a, polarity="any", edge_threshold=20, num_rays=72),
        _node("c2", "find_circle", 2, 1, "孔 2", roi=roi_b or roi_a, polarity="any", edge_threshold=20, num_rays=72),
        _node("dist", "distance", 3, 0, "中心距", mode="euclid"),
        _node("nf", "judge", 3, 2, "NG：找不到孔", verdict="ng", label="not_found"),
    ]
    edges += [
        _edge("gray", "c1", "image", "image"), _edge("gray", "c2", "image", "image"), _edge("gray", "dist", "image", "image"),
        _edge("c1", "dist", "cx", "ax"), _edge("c1", "dist", "cy", "ay"), _edge("c2", "dist", "cx", "bx"), _edge("c2", "dist", "cy", "by"),
        _edge("c1", "nf", "not_found", "_flow"), _edge("c2", "nf", "not_found", "_flow"),
    ]
    value_src, value_port, col, unit = "dist", "distance", 4, "px"
    if intent.mm_per_px:
        nodes.append(_node("cal", "calibration", col, 0, "像素校正", mode="pixel_size", pixel_size_mm=intent.mm_per_px))
        edges.append(_edge("dist", "cal", "distance", "value"))
        value_src, value_port, col, unit = "cal", "mm", col + 1, "mm"
    if intent.nominal is not None:
        tol = intent.tol if intent.tol is not None else round(intent.nominal * 0.02, 3)
        nodes += [
            _node("tol", "tolerance_judge", col, 0, "中心距公差", nominal=intent.nominal, upper_tol=tol, lower_tol=-tol, unit=unit, name="distance"),
            _node("jd", "judge", col + 1, 0, "OK / NG", verdict="by_input", label="distance"),
        ]
        edges += [_edge(value_src, "tol", value_port, "value"), _edge("tol", "jd", "in_spec", "value")]
    nodes.append(_node("out", "output", col, 1, "輸出中心距", name=f"distance_{unit}"))
    edges.append(_edge(value_src, "out", value_port, "value"))
    why = "兩個找圓的圓心量距離" + ("（缺第二個 ROI，記得補圈）" if not roi_b else "")
    if intent.mm_per_px:
        why += f"，以 {intent.mm_per_px:.4f} mm/px 換算"
    if intent.nominal is not None:
        why += f"，公差 {intent.nominal}±{intent.tol if intent.tol is not None else round(intent.nominal * 0.02, 3)}{unit}"
    return _finish(nodes, edges), why


def synth_template_presence(intent: Intent, regions: list, analysis: dict, make_asset: MakeAsset | None) -> tuple[dict, str]:
    idx = intent.template_roi if intent.template_roi is not None else 0
    tpl = regions[idx] if idx < len(regions) else None
    rows = analysis.get("regions") or []
    picture: dict[str, Any] | None = None
    search = None
    if tpl is not None:
        image_idx = int(tpl.get("image", 0) or 0)
        if make_asset is not None:
            picture = make_asset(image_idx, tpl["region"], "AI 助手：圖案範本")
        b = rows[idx].get("bounds") if idx < len(rows) and rows[idx].get("bounds") else None
        if b:
            w, h = _image_size(analysis, image_idx)
            search = _expand_rect(b, 1.0, w, h)
    nodes = [
        _node("src", "image_source", 0, 0, "取像", mode="auto"),
        _node("tm", "template_match", 1, 0, "找圖案", roi=search, threshold=0.7, max_matches=1, angle_range=0),
        *_picture_node("tpl", picture, 0, 3, "圖案範本圖"),
        _node("ok", "judge", 2, 0, "OK：有圖案", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：沒有圖案", verdict="ng", label="missing"),
        _node("out", "output", 2, 2, "輸出比對分數", name="match_score"),
        _note("hint", 0, 1, "AI 助手", "由 AI 助手生成：圖案有無。範本＝您圈的 ROI，已存成「圖案範本圖」固定影像節點接到比對工具的圖片輸入埠（跟著流程走，換台機器也能跑）；在 ROI 周圍一圈範圍內搜尋；分數門檻 0.7，會旋轉的工件再加 angle_range。"),
    ]
    edges = [
        _edge("src", "tm"),
        _edge("tm", "ok", "found", "_flow"), _edge("tm", "ng", "not_found", "_flow"),
        _edge("tm", "out", "best_score", "value"),
    ]
    if picture:
        edges.append(_edge("tpl", "tm", "image", "template_image"))
    why = "ROI 裁成範本圖（跟著流程走的固定影像），在其周圍搜尋，分數 ≥ 0.7 算有"
    if not picture:
        why += "（範本圖尚未建立：請圈選圖案 ROI 後重新生成，或在工具的圖片輸入埠接一個固定影像）"
    return _finish(nodes, edges, col=3), why


def synth_generic(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    nodes, edges = _src_gray("由 AI 助手生成：資訊流程。提示詞不夠明確，先量統計／直方圖／邊緣密度給你看；\n請補充要檢測什麼（例：應該有 5 個孔、量直徑 17.5±0.4mm、有沒有刮痕）再重新生成。")
    nodes += [
        _node("inten", "intensity", 2, 0, "區域統計", roi=roi),
        _node("hist", "histogram", 2, 1, "直方圖", roi=roi),
        _node("ed", "edge_density", 2, 2, "邊緣密度", roi=roi, max_ratio=0.5),
        _node("out_m", "output", 3, 0, "輸出平均", name="mean"),
        _node("out_o", "output", 3, 1, "輸出 Otsu", name="otsu"),
        _node("out_e", "output", 3, 2, "輸出邊緣比例", name="edge_ratio"),
    ]
    edges += [
        _edge("gray", "inten", "image", "image"), _edge("inten", "out_m", "mean", "value"),
        _edge("gray", "hist", "image", "image"), _edge("hist", "out_o", "otsu", "value"),
        _edge("gray", "ed", "image", "image"), _edge("ed", "out_e", "ratio", "value"),
    ]
    return _finish(nodes, edges, col=4), "提示詞不明確：先回報 ROI 的統計特徵，請補充檢測目標"


SYNTHESIZERS = {
    "count": synth_count,
    "diameter": synth_diameter,
    "width": synth_width,
    "angle": synth_angle,
    "defect": synth_defect,
    "color_match": synth_color_match,
    "color_presence": synth_color_presence,
    "presence": synth_presence,
    "brightness": synth_brightness,
    "barcode": synth_barcode,
    "generic": synth_generic,
    "text": synth_text,
    "distance": synth_distance,
    "focus": synth_focus,
    "roundness": synth_roundness,
    "template": synth_template,
}


def _same_size_rect(good_bounds: dict[str, Any], target_bounds: dict[str, Any]) -> dict[str, Any]:
    """良品比對的檢測框：位置取目標 ROI 的中心、尺寸取好品 ROI（範本必須與檢測區同尺寸）。"""
    w, h = int(good_bounds["w"]), int(good_bounds["h"])
    cx = target_bounds["x"] + target_bounds["w"] / 2
    cy = target_bounds["y"] + target_bounds["h"] / 2
    return {"shape": "rect", "x": int(round(cx - w / 2)), "y": int(round(cy - h / 2)), "w": w, "h": h}


def synth_golden(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any], make_asset: MakeAsset | None) -> tuple[dict, str]:
    rows = analysis.get("regions") or []
    good_idx = intent.good_roi if intent.good_roi is not None else 0
    good = regions[good_idx] if good_idx < len(regions) else None
    bad = regions[intent.bad_roi] if intent.bad_roi is not None and intent.bad_roi < len(regions) else None
    picture: dict[str, Any] | None = None
    if good is not None and make_asset is not None:
        picture = make_asset(int(good.get("image", 0) or 0), good["region"], "AI 助手：良品範本")
    good_bounds = rows[good_idx].get("bounds") if good_idx < len(rows) and rows[good_idx].get("bounds") else None
    if bad is not None and good_bounds and rows[intent.bad_roi].get("bounds"):
        roi = _same_size_rect(good_bounds, rows[intent.bad_roi]["bounds"])
    elif good_bounds:
        roi = {"shape": "rect", **good_bounds}
    else:
        roi = good["region"] if good else None
    ginfo = rows[good_idx] if good_idx < len(rows) and not rows[good_idx].get("empty") else (analysis.get("full") or {})
    threshold = int(_clip(3 * float(ginfo.get("mad", 13) or 13), 25, 80))
    min_area = int(_clip(float(ginfo.get("area", 100000)) * 0.001, 30, 500))
    nodes = [
        _node("src", "image_source", 0, 0, "取像", mode="auto"),
        _node("diff", "defect_diff", 1, 0, "良品比對", roi=roi, align="phase", threshold=threshold, min_area=min_area),
        *_picture_node("tpl", picture, 0, 3, "良品圖"),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：與良品有差異", verdict="ng", label="defect"),
        _node("out_n", "output", 2, 2, "輸出缺陷數", name="defect_count"),
        _node("out_a", "output", 3, 2, "輸出缺陷面積", name="defect_area"),
        _note("hint", 0, 1, "AI 助手", "由 AI 助手生成：良品比對。範本＝您圈的好品 ROI，已存成「良品圖」固定影像節點接到比對工具的圖片輸入埠（跟著流程走）；檢測框與範本同尺寸。\n位移由相位對齊補正；差異門檻與最小面積決定靈敏度。"),
    ]
    edges = [
        _edge("src", "diff"),
        _edge("diff", "ok", "ok", "_flow"), _edge("diff", "ng", "defect", "_flow"),
        _edge("diff", "out_n", "count", "value"), _edge("diff", "out_a", "total_area", "value"),
    ]
    if picture:
        edges.append(_edge("tpl", "diff", "image", "template_image"))
    why = f"好品 ROI 裁成良品圖（跟著流程走的固定影像），在檢測框內做差異比對（門檻 {threshold}、最小面積 {min_area}px²，依良品區域雜訊）"
    if not picture:
        why += "（良品圖尚未建立：請在「良品比對」工具頁上傳，或接一個固定影像到它的圖片輸入埠）"
    return _finish(nodes, edges, col=3), why


def _has_roi_input(tool_type: str) -> bool:
    return tools.has(tool_type) and any(p.key == "roi" for p in tools.get(tool_type).inputs)


def wrap_with_locate(graph: dict[str, Any], regions: list[dict[str, Any]], analysis: dict[str, Any], locator_idx: int,
                     make_asset: MakeAsset | None, *, threshold: float = 0.6) -> tuple[dict[str, Any], str]:
    """在任何流程前面包「範本比對 → 定位補正 → ROI 跟隨」三件套：定位 ROI 裁成範本、參考位置＝其中心，
    每個帶固定 ROI 的檢測節點各接一個 fixture_roi。沒有可跟隨的 ROI 就原樣回傳。"""
    rows = analysis.get("regions") or []
    if not (0 <= locator_idx < len(regions)) or locator_idx >= len(rows) or not rows[locator_idx].get("bounds"):
        return graph, ""
    loc = regions[locator_idx]
    b = rows[locator_idx]["bounds"]
    image_idx = int(loc.get("image", 0) or 0)
    width, height = _image_size(analysis, image_idx)
    picture = make_asset(image_idx, loc["region"], "AI 助手：定位範本") if make_asset is not None else None
    search = _expand_rect(b, 1.5, width, height)
    ref_x, ref_y = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    out = json.loads(json.dumps(graph))
    src_id = next((n["id"] for n in out["nodes"] if n.get("type") == "image_source"), None)
    if src_id is None:
        return graph, ""
    feed = next((n["id"] for n in out["nodes"] if n.get("type") == "grayscale"), src_id)
    new_nodes = [
        _node("loc_tm", "template_match", 1, 0, "找定位範本", roi=search, threshold=threshold, max_matches=1, angle_range=0),
        *_picture_node("loc_tpl", picture, 0, 3, "定位範本圖"),
        _node("loc_align", "shape_align", 2, 0, "定位補正", ref_x=round(ref_x, 1), ref_y=round(ref_y, 1), ref_angle=0, use_angle=False),
        _node("loc_nf", "judge", 3, 0, "NG：定位失敗", verdict="ng", label="locate_failed"),
    ]
    new_edges = [
        _edge(feed, "loc_tm", "image", "image"),
        _edge("loc_tm", "loc_align", "matches", "matches"),
        _edge("loc_tm", "loc_nf", "not_found", "_flow"),
    ]
    if picture:
        new_edges.append(_edge("loc_tpl", "loc_tm", "image", "template_image"))
    col, followed = 4, 0
    for n in out["nodes"]:
        roi = (n.get("params") or {}).get("roi")
        if n.get("type") in ("note", "image_source", "template_match") or not isinstance(roi, dict) or not roi.get("shape") or not _has_roi_input(n["type"]):
            continue
        fid = f"fix_{n['id']}"
        new_nodes.append(_node(fid, "fixture_roi", col, 0, f"ROI 跟隨：{n.get('label') or n['id']}", roi=roi))
        new_edges += [_edge(feed, fid, "image", "image"), _edge("loc_align", fid, "transform", "transform"), _edge(fid, n["id"], "region", "roi")]
        col += 1
        followed += 1
    if followed == 0:
        return graph, ""
    for n in out["nodes"]:  # 既有節點整體往下移一列，定位鏈放最上排
        pos = n.get("position") or {}
        pos["y"] = float(pos.get("y", 0)) + GY
        n["position"] = pos
    out["nodes"] = new_nodes + out["nodes"]
    out["edges"] = out["edges"] + new_edges
    why = f"定位補正：ROI{locator_idx + 1:02d} 裁成定位範本圖（參考位置 {ref_x:.0f},{ref_y:.0f}），{followed} 個 ROI 跟隨位移"
    if not picture:
        why += "（定位範本圖尚未建立）"
    return out, why


def _work_regions(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any]) -> tuple[Intent, list[dict[str, Any]], dict[str, Any]]:
    """去掉定位 ROI 後的工作 ROI（analysis.regions 同步過濾、intent 內的 ROI 索引同步重編）。"""
    if intent.locator_roi is None or not (0 <= intent.locator_roi < len(regions)):
        return intent, regions, analysis
    keep = [i for i in range(len(regions)) if i != intent.locator_roi]
    remap = {old: new for new, old in enumerate(keep)}
    rows = analysis.get("regions") or []
    a = dict(analysis)
    a["regions"] = [rows[i] for i in keep if i < len(rows)]
    fixed = replace(intent, good_roi=remap.get(intent.good_roi), bad_roi=remap.get(intent.bad_roi), template_roi=remap.get(intent.template_roi))
    return fixed, [regions[i] for i in keep], a


def _synth_one(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any], make_asset: MakeAsset | None) -> tuple[dict[str, Any], str]:
    if intent.kind == "golden":
        return synth_golden(intent, regions, analysis, make_asset)
    if intent.kind == "template_presence":
        return synth_template_presence(intent, regions, analysis, make_asset)
    return SYNTHESIZERS[intent.kind](intent, regions, analysis)


def synthesize(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any], *,
               make_asset: MakeAsset | None = None) -> tuple[dict[str, Any], str]:
    work_intent, work_regions, work_analysis = _work_regions(intent, regions, analysis)
    graph, why = _synth_one(work_intent, work_regions, work_analysis, make_asset)
    notes = list(intent.notes)
    if intent.locate and intent.locator_roi is not None:
        graph, loc_why = wrap_with_locate(graph, regions, analysis, intent.locator_roi, make_asset)
        if loc_why:
            notes.append(loc_why)
    rationale = "；".join([*notes, why])
    return graph, rationale


# ---------------------------------------------------------------------------
# 候選方案：主要方案＋參數變體（同一意圖 2～3 種取法），由 service 在影像上試跑後依標記排名
# ---------------------------------------------------------------------------
def _scale(key: str, factor: float, floor: float = 0.0, ceil: float | None = None) -> Callable[[dict[str, Any]], Any]:
    def fn(p: dict[str, Any]) -> Any:
        v = p.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        out = max(floor, v * factor)
        if ceil is not None:
            out = min(ceil, out)
        return type(v)(round(out, 4)) if isinstance(v, float) else int(round(out))
    return fn


def _shift_threshold(delta: float) -> Callable[[dict[str, Any]], Any]:
    """固定門檻往「遠離平均」（delta>0）或「靠近平均」（delta<0）移；依 invert 決定方向。"""
    def fn(p: dict[str, Any]) -> Any:
        v = p.get("threshold")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or p.get("method", "fixed") != "fixed":
            return None
        step = -delta if p.get("invert") else delta
        return int(_clip(v + step, 0, 255))
    return fn


def _flip_polarity(p: dict[str, Any]) -> Any:
    return "bright" if p.get("polarity", "dark") == "dark" else "dark"


#: 意圖 → [(key, 顯示名, [(工具型別, {參數: 值或 fn(params)})], 說明)]
VARIANTS: dict[str, list[tuple[str, str, list[tuple[str, dict[str, Any]]], str]]] = {
    "count": [
        ("adaptive", "自適應門檻", [("threshold", {"method": "adaptive_gaussian", "block": 51, "c": 5})], "背景不均時用區域門檻"),
        ("strict", "嚴格粒子", [("blob", {"min_area": _scale("min_area", 2.0, 10)}), ("morphology", {"ksize": 7})], "最小面積加倍、開運算加大"),
    ],
    "defect": [
        ("conservative", "保守", [("threshold", {"threshold": _shift_threshold(12)}), ("blob", {"min_area": _scale("min_area", 2.0, 20)})], "門檻外推、最小面積加倍"),
        ("sensitive", "靈敏", [("threshold", {"threshold": _shift_threshold(-8)}), ("blob", {"min_area": _scale("min_area", 0.5, 20)})], "門檻內縮、最小面積減半"),
    ],
    "presence": [
        ("loose", "寬鬆", [("blob", {"min_area": _scale("min_area", 0.5, 10)})], "最小面積減半"),
        ("strict", "嚴格", [("blob", {"min_area": _scale("min_area", 2.0, 10)})], "最小面積加倍"),
    ],
    "diameter": [("soft_edges", "低邊緣門檻", [("find_circle", {"edge_threshold": 10, "num_rays": 120})], "對比低時用較低邊緣門檻、更多射線")],
    "distance": [("soft_edges", "低邊緣門檻", [("find_circle", {"edge_threshold": 10, "num_rays": 120})], "對比低時用較低邊緣門檻、更多射線")],
    "width": [
        ("first_last", "首尾邊緣對", [("caliper", {"edge_pair": "first_last"})], "取掃描方向的第一與最後一條邊"),
        ("strongest", "最強邊緣對", [("caliper", {"edge_pair": "strongest"})], "取對比最強的兩條邊"),
    ],
    "golden": [
        ("conservative", "保守", [("defect_diff", {"threshold": _scale("threshold", 1.5, 1, 255), "min_area": _scale("min_area", 2.0, 10)})], "差異門檻與最小面積放大"),
        ("ecc", "ECC 對齊", [("defect_diff", {"align": "ecc"})], "位移較大時用 ECC 對齊"),
    ],
    "color_presence": [("wide", "寬鬆色域", [("color_range", {"h_low": _scale("h_low", 1.0, 0), "s_low": _scale("s_low", 0.7, 0), "v_low": _scale("v_low", 0.7, 0)})], "S/V 下限放寬")],
    "color_match": [("hsv", "HSV 空間", [("color_check", {"space": "hsv"})], "以色相為主比對，抗亮度變化")],
    "text": [("flip", "反向筆劃", [("text_presence", {"polarity": _flip_polarity})], "字比背景亮時用")],
    "template_presence": [("loose", "低分數門檻", [("template_match", {"threshold": 0.55, "angle_range": 10})], "分數門檻 0.55、允許 ±10° 旋轉")],
}


def _variant(base: dict[str, Any], key: str, label: str, patches: list[tuple[str, dict[str, Any]]], why: str) -> dict[str, Any] | None:
    graph = json.loads(json.dumps(base["graph"]))
    hit = False
    for n in graph.get("nodes", []):
        if str(n.get("id", "")).startswith(("loc_", "fix_")):
            continue
        for tool_type, changes in patches:
            if n.get("type") != tool_type:
                continue
            params = n.setdefault("params", {})
            for k, v in changes.items():
                new = v(params) if callable(v) else v
                if new is None or new == params.get(k):
                    continue
                params[k] = new
                hit = True
    if not hit:
        return None
    return {"key": key, "label": label, "graph": graph, "rationale": f"{base['rationale']}；候選方案「{label}」：{why}"}


def candidates(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any], *,
               make_asset: MakeAsset | None = None, priors: dict[tuple[str, str], Any] | None = None) -> list[dict[str, Any]]:
    """主要方案在前，之後是同一意圖的參數變體（最多 2 個）；每筆 {key, label, graph, rationale}。
    priors（相似成功案例的 teach 參數）有改到東西時，「沿用過去成功參數」版排第一、原主要方案第二，讓標記排名可以否決先驗。"""
    graph, rationale = synthesize(intent, regions, analysis, make_asset=make_asset)
    out = [{"key": "primary", "label": "主要方案", "graph": graph, "rationale": rationale}]
    if priors:
        from apps.vision.agent import memory

        prior_graph, changed = memory.apply_priors(graph, priors)
        if changed:
            out.insert(0, {"key": "prior", "label": "沿用過去成功參數", "graph": prior_graph, "rationale": rationale + "；沿用相似成功案例的參數：" + "、".join(changed)})
    for key, label, patches, why in VARIANTS.get(intent.kind, []):
        v = _variant(out[-1] if len(out) == 1 else out[1], key, label, patches, why)
        if v is not None:
            out.append(v)
    return out
