"""意圖 → graph 合成器（規則引擎的產出端）。

每種意圖一個合成器：掛使用者的 ROI、用 analysis 特徵自動調參，輸出
(graph, rationale)。graph 是標準格式（呼叫端再過 validate_graph）；
image_source 不綁來源（mode=auto：試跑吃上傳影像，存成流程後在編輯器選來源）。
"""

from __future__ import annotations

from typing import Any

from apps.vision.agent.intents import Intent
from apps.vision.demo import _edge, _node, _note


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


def synth_count(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    info = _roi_info(analysis)
    roi = _region_of(regions)
    dark = info.get("blobs", {}).get("dark", {})
    bright = info.get("blobs", {}).get("bright", {})
    invert = dark.get("count", 0) >= bright.get("count", 0)
    probe = dark if invert else bright
    min_area = max(30, int(probe.get("median_area", 0) * 0.3)) if probe.get("count") else max(30, int(info.get("w", 100) * info.get("h", 100) * 0.001))
    nodes, edges = _src_gray("由 AI 助手生成：計數流程。粒子抓不對時調「二值化」門檻與 blob 最小面積。")
    nodes += [
        _node("blur", "blur", 2, 0, "去雜訊", method="median", ksize=5),
        _node("thr", "threshold", 3, 0, "二值化", method="otsu", invert=invert),
        _node("open", "morphology", 4, 0, "開運算去雜點", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "粒子計數", roi=roi, min_area=min_area, min_count=0, sort_by="area"),
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
    why = f"抓{'暗' if invert else '亮'}粒子（ROI 內{'暗' if invert else '亮'}粒子較多），最小面積 {min_area}px²"
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
    col = 3
    if intent.nominal is not None:
        tol = intent.tol if intent.tol is not None else round(intent.nominal * 0.05, 3)
        nodes += [
            _node("tol", "tolerance_judge", col, 0, "寬度公差", nominal=intent.nominal, upper_tol=tol, lower_tol=-tol, unit=intent.unit, name="width"),
            _node("jd", "judge", col + 1, 0, "OK / NG", verdict="by_input", label="width"),
        ]
        edges += [_edge("cal", "tol", "width", "value"), _edge("tol", "jd", "in_spec", "value")]
    nodes.append(_node("out", "output", col, 1, "輸出寬度", name="width_px"))
    edges.append(_edge("cal", "out", "width", "value"))
    return _finish(nodes, edges), "卡尺在 ROI 內找最寬的邊緣對量距離"


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


def synth_defect(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    mean = float(info.get("mean", 128))
    std = float(info.get("std", 20))
    dark_more = info.get("blobs", {}).get("dark", {}).get("count", 0) >= info.get("blobs", {}).get("bright", {}).get("count", 0)
    offset = max(30.0, 3 * std)
    thr = max(5.0, mean - offset) if dark_more else min(250.0, mean + offset)
    nodes, edges = _src_gray("由 AI 助手生成：表面缺陷。門檻＝ROI 平均灰階往" + ("暗" if dark_more else "亮") + "偏 3σ；誤抓就把門檻再往外調、最小面積調大。")
    nodes += [
        _node("blur", "blur", 2, 0, "去雜訊", method="gaussian", ksize=5),
        _node("thr", "threshold", 3, 0, "抓異常", method="fixed", threshold=int(thr), invert=dark_more),
        _node("open", "morphology", 4, 0, "開運算", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "缺陷 blob", roi=roi, threshold_method="fixed", threshold=128, polarity="bright", min_area=200, min_count=0),
        _node("cmp", "if_number", 6, 0, "沒有缺陷？", operator="eq", threshold=0),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG：表面缺陷", verdict="ng", label="defect"),
        _node("out", "output", 6, 1, "輸出缺陷數", name="defect_count"),
    ]
    edges += [
        _edge("gray", "blur"), _edge("blur", "thr"), _edge("thr", "open"), _edge("open", "blob"),
        _edge("blob", "cmp", "count", "value"), _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
    ]
    why = f"以固定門檻 {int(thr)} 抓{'暗' if dark_more else '亮'}異常（ROI 平均 {mean:.0f}±{std:.0f}）；有良品範本時建議改用「良品比對」工具更穩"
    return _finish(nodes, edges), why


def synth_color_match(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    color = intent.color_hex or _roi_info(analysis).get("dominant", {}).get("hex", "#808080")
    nodes = [
        _node("src", "image_source", 0, 0, "取像", mode="auto"),
        _node("chk", "color_check", 1, 0, "顏色比對", roi=roi, color=color, space="rgb", tolerance=60),
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
    return _finish(nodes, edges, col=3), f"ROI 平均色與目標色 {color} 比距離"


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
    nodes, edges = _src_gray("由 AI 助手生成：有無檢測。ROI 內抓得到粒子＝有料。")
    nodes += [
        _node("blob", "blob", 2, 0, "找料件", roi=roi, min_area=100, min_count=1),
        _node("ok", "judge", 3, 0, "OK：有料", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG：缺料", verdict="ng", label="missing"),
        _node("out", "output", 3, 2, "輸出數量", name="count"),
    ]
    edges += [
        _edge("gray", "blob", "image", "image"),
        _edge("blob", "ok", "found", "_flow"), _edge("blob", "ng", "not_found", "_flow"),
        _edge("blob", "out", "count", "value"),
    ]
    return _finish(nodes, edges, col=4), "ROI 內以 Otsu 門檻找粒子，有→OK、無→NG"


def synth_brightness(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    info = _roi_info(analysis)
    mean = float(info.get("mean", 128))
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


def synth_barcode(intent: Intent, regions: list, analysis: dict) -> tuple[dict, str]:
    roi = _region_of(regions)
    nodes, edges = _src_gray("由 AI 助手生成：讀碼。標籤斜貼讀不到時，前面加「透視校正」工具拉正。")
    nodes += [
        _node("bc", "barcode", 2, 0, "讀碼", roi=roi),
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
}


def synthesize(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any]) -> tuple[dict[str, Any], str]:
    graph, why = SYNTHESIZERS[intent.kind](intent, regions, analysis)
    rationale = "；".join([*intent.notes, why])
    return graph, rationale
