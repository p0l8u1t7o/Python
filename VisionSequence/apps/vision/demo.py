"""示範流程（程式化產生，經 validate_graph 後寫入）。

節點用 _node / _edge helper 建，座標以 300×170 網格排，讓畫布一開就整齊。
範例樣板放在「範本畫廊」（BUILTIN_TEMPLATES → GET /vision/templates 的 builtin 項），
seed_demo 只建 2 個示範流程＋每個樣板一組合成樣本圖（apps/vision/demo_images.py，
folder 來源、群組「範例」）＋範本／良品資產（從樣本圖自動裁切）。座標與公差都對齊
合成圖的標稱值，範本掛上對應的「範例：⋯」來源就能執行。深度學習（dl_*）、save_image
與 write_modbus 需要模型／連線，不入樣板，見各流程便利貼說明。
"""

from __future__ import annotations

import logging

from typing import Any

import numpy as np

from apps.vision.graph import validate_graph
from apps.vision.models import Asset, Flow, ImageSource, ResourceGroup
from apps.vision.tools import base as tools

log = logging.getLogger(__name__)

GX, GY = 300, 170


def _node(nid: str, ntype: str, col: int, row: int, title: str = "", **params: Any) -> dict[str, Any]:
    return {
        "id": nid,
        "type": ntype,
        "label": title,
        "enabled": True,
        "params": params,
        "position": {"x": 40 + col * GX, "y": 40 + row * GY},
    }


def _edge(source: str, target: str, sh: str = "", th: str = "") -> dict[str, Any]:
    return {"id": f"e-{source}-{sh}-{target}-{th}", "source": source, "target": target, "source_handle": sh, "target_handle": th}


def _note(nid: str, col: int, row: int, label: str, text: str) -> dict[str, Any]:
    return {"id": nid, "type": "note", "label": label, "description": text, "position": {"x": 40 + col * GX, "y": 40 + row * GY}, "width": 320, "height": 120}


def hole_count_flow(source_id: Any) -> dict[str, Any]:
    """零件孔數檢測：灰階 → 二值化（暗孔）→ blob → 孔數 = 5 → OK。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("blur", "blur", 2, 0, "Denoise", method="median", ksize=5),
        _node("thr", "threshold", 3, 0, "Find dark holes", method="fixed", threshold=60, invert=True),
        _node("open", "morphology", 4, 0, "Open to remove specks", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "Hole blobs", min_area=300, max_area=60000, min_circularity=0.6, sort_by="area"),
        _node("cmp", "if_number", 6, 0, "5 holes?", operator="eq", threshold=5),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG: wrong hole count", verdict="ng", label="hole_count"),
        _node("out", "output", 6, 1, "Output hole count", name="hole_count"),
        _node("draw", "draw_result", 6, 2, "Result image"),
        _note("n1", 0, 1, "About", "Each synthetic image is shifted and rotated at random, and about 30% are missing a hole or carry a scratch.\nAnything other than 5 holes takes the NG branch."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "blur"), _edge("blur", "thr"), _edge("thr", "open"), _edge("open", "blob"),
        _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
        _edge("src", "draw", "image", "image"),
    ]
    if tools.has("blob"):
        return {"nodes": nodes, "edges": edges}
    # blob 尚未提供時退化為像素計數示範。
    nodes = [n for n in nodes if n["id"] not in ("blob", "open")]
    nodes.append(_node("cnt", "pixel_count" if tools.has("pixel_count") else "threshold", 4, 0, "Count"))
    return {"nodes": nodes, "edges": [e for e in edges if e["source"] not in ("blob", "open", "thr") and e["target"] not in ("blob", "open")] + [_edge("thr", "cnt")]}


def brightness_gate_flow(source_id: Any) -> dict[str, Any]:
    """曝光檢查：平均亮度落在範圍內才 OK（純前處理＋邏輯，無 detect 依賴）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("small", "resize", 2, 0, "Downscale for speed", scale=0.25),
        _node("thr", "threshold", 3, 0, "Otsu", method="otsu"),
        _node("rng", "in_range", 4, 0, "Threshold in range?", low=40, high=200),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG: exposure out of range", verdict="ng", label="exposure"),
        _node("out", "output", 4, 1, "Output Otsu threshold", name="otsu"),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "small"), _edge("small", "thr"),
        _edge("thr", "rng", "threshold_used", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("thr", "out", "threshold_used", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def locate_measure_flow(source_id: Any, template_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """定位＋卡尺：範本比對 → 定位補正 → ROI 跟隨 → 卡尺量帶高 → 公差。

    對齊合成圖「定位量測」：十字標記標稱 (260, 220)，中央亮帶高 160px（NG 張 200px）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("tm", "template_match", 2, 0, "Find locator template", threshold=0.6, max_matches=1),
        _node("ref", "fixed_image", 0, 3, "Locator template picture", images=[template_ref] if template_ref else [], mode="fixed", index=1, role="reference"),
        _node("align", "shape_align", 3, 0, "Locate correction", ref_x=260, ref_y=220, ref_angle=0),
        _node("fix", "fixture_roi", 4, 0, "ROI follow", roi={"shape": "rotated_rect", "cx": 690, "cy": 480, "w": 300, "h": 60, "angle": 90}),
        _node("cal", "caliper", 5, 0, "Caliper band height", polarity="any", edge_pair="widest"),
        _node("rng", "in_range", 6, 0, "Band height tolerance", low=140, high=180),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG: width out of tolerance", verdict="ng", label="width"),
        _node("out", "output", 6, 1, "Output width", name="width_px"),
        _node("nf", "judge", 3, 1, "NG: template not found", verdict="ng", label="not_found"),
        _note("n1", 0, 1, "How to use it", "The template is the cross marker at the top left of the sample image, carried by the Fixed image step wired into the locator's template input.\nWhen the part moves, the ROI follows the locate result, so the caliper always measures on the bright band.\nFor your own part: draw a new template, take the reference position in one click, and redraw the ROI."),
    ]
    edges = [
        _edge("ref", "tm", "image", "template_image"),
        _edge("src", "gray"), _edge("gray", "tm"),
        _edge("tm", "align", "matches", "matches"),
        _edge("tm", "nf", "not_found", "_flow"),
        _edge("gray", "fix", "image", "image"), _edge("align", "fix", "transform", "transform"),
        _edge("gray", "cal", "image", "image"), _edge("fix", "cal", "region", "roi"),
        _edge("cal", "rng", "width", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("cal", "out", "width", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def cup_measure_flow(source_id: Any, template_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """深抽杯件量測：定位 → ROI 跟隨 ×3 → 外徑／內徑找圓 + 壁厚 → 同心度 → 公差判定 ×3 → 具名輸出 → 判定。

    教導步驟（現場調機時照順序做，數值參數都已標 teach，可在參數卡頁一次調完）：
    1. 「找定位範本」：從目前影像框選杯口特徵建立範本；調分數門檻（threshold）。
    2. 試跑一次，把「定位補正」的 ref_x/ref_y/ref_angle 設成目前匹配位置（前端一鍵帶入）。
    3. 三個「ROI 跟隨」：外徑環畫在杯口外緣附近、內徑環畫在內緣附近、壁厚用「線段」ROI 橫切杯壁。
    4. 找圓／壁厚的 edge_threshold、polarity 依實際對比調到邊緣點穩定。
    5. 三個「公差判定」填圖面標稱值與上下偏差（單位 px；若要 mm，在前面接「像素校正」）、圖面出處。
    6. 「同心度」的 max_deviation 依圖面同心度公差 /2 填入（同心度 = 2×圓心偏移）。
    """
    od_roi = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 300, "r_outer": 380}
    id_roi = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 220, "r_outer": 300}
    wall_roi = {"shape": "line", "x1": 870, "y1": 480, "x2": 1015, "y2": 480}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("tm", "template_match", 2, 0, "Find locator template", threshold=0.6, max_matches=1, angle_range=10, angle_step=2),
        _node("ref", "fixed_image", 0, 3, "Locator template picture", images=[template_ref] if template_ref else [], mode="fixed", index=1, role="reference"),
        _node("align", "shape_align", 3, 0, "Locate correction", ref_x=200, ref_y=170, ref_angle=0),
        _node("nf", "judge", 3, 1, "NG: template not found", verdict="ng", label="not_found"),
        _node("fix_od", "fixture_roi", 4, 0, "Outer ROI follow", roi=od_roi),
        _node("fix_id", "fixture_roi", 4, 1, "Inner ROI follow", roi=id_roi),
        _node("fix_wall", "fixture_roi", 4, 2, "Wall ROI follow", roi=wall_roi),
        _node("od", "find_circle", 5, 0, "Outer circle", polarity="any", edge_threshold=20, num_rays=72, edge_select="last"),
        _node("idc", "find_circle", 5, 1, "Inner circle", polarity="any", edge_threshold=20, num_rays=72, edge_select="first"),
        _node("wall", "wall_thickness", 5, 2, "Wall thickness", polarity="any", edge_threshold=20, num_calipers=10, band=40),
        _node("od_d", "formula", 6, 0, "Outer = 2r", expression="a*2"),
        _node("id_d", "formula", 6, 1, "Inner = 2r", expression="a*2"),
        _node("conc", "concentricity", 6, 3, "Concentricity", max_deviation=5),
        _node("tol_od", "tolerance_judge", 7, 0, "Outer tolerance", nominal=700, upper_tol=5, lower_tol=-5, unit="px", spec_source="Drawing: outer dia", name="od"),
        _node("tol_id", "tolerance_judge", 7, 1, "Inner tolerance", nominal=520, upper_tol=5, lower_tol=-5, unit="px", spec_source="Drawing: inner dia", name="id"),
        _node("tol_wall", "tolerance_judge", 7, 2, "Wall tolerance", nominal=90, upper_tol=5, lower_tol=-5, unit="px", spec_source="Drawing: wall thickness", name="wall"),
        _node("out_od", "output", 8, 0, "Output outer diameter", name="od_px"),
        _node("out_id", "output", 8, 1, "Output inner diameter", name="id_px"),
        _node("out_wall", "output", 8, 2, "Output wall thickness", name="wall_px"),
        _node("all_ok", "bool_logic", 8, 3, "All in spec?", mode="and"),
        _node("judge", "judge", 9, 3, "OK / NG", verdict="by_input", label="cup"),
        _node("draw", "draw_result", 9, 0, "Result image"),
        _note("n1", 0, 1, "Teaching steps", "1. Locator template: draw a box around a feature of the cup rim.\n2. Preview once, then set the locate correction's reference position to the current match.\n3. Three ROIs follow it: the outer annulus, the inner annulus, and a line across the wall.\n4. Fill each tolerance judge with the nominal, the deviations and where on the drawing it comes from; concentricity takes max_deviation."),
    ]
    edges = [
        _edge("ref", "tm", "image", "template_image"),
        _edge("src", "gray"), _edge("gray", "tm"),
        _edge("tm", "align", "matches", "matches"), _edge("tm", "nf", "not_found", "_flow"),
        _edge("gray", "fix_od", "image", "image"), _edge("align", "fix_od", "transform", "transform"),
        _edge("gray", "fix_id", "image", "image"), _edge("align", "fix_id", "transform", "transform"),
        _edge("gray", "fix_wall", "image", "image"), _edge("align", "fix_wall", "transform", "transform"),
        _edge("gray", "od", "image", "image"), _edge("fix_od", "od", "region", "roi"),
        _edge("gray", "idc", "image", "image"), _edge("fix_id", "idc", "region", "roi"),
        _edge("gray", "wall", "image", "image"), _edge("fix_wall", "wall", "region", "roi"),
        _edge("od", "od_d", "r", "a"), _edge("idc", "id_d", "r", "a"),
        _edge("od", "conc", "cx", "ax"), _edge("od", "conc", "cy", "ay"), _edge("od", "conc", "r", "ar"),
        _edge("idc", "conc", "cx", "bx"), _edge("idc", "conc", "cy", "by"), _edge("idc", "conc", "r", "br"),
        _edge("od_d", "tol_od", "value", "value"), _edge("id_d", "tol_id", "value", "value"), _edge("wall", "tol_wall", "thickness", "value"),
        _edge("od_d", "out_od", "value", "value"), _edge("id_d", "out_id", "value", "value"), _edge("wall", "out_wall", "thickness", "value"),
        _edge("tol_od", "all_ok", "in_spec", "values"), _edge("tol_id", "all_ok", "in_spec", "values"),
        _edge("tol_wall", "all_ok", "in_spec", "values"), _edge("conc", "all_ok", "in_spec", "values"),
        _edge("all_ok", "judge", "result", "value"),
        _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def color_presence_flow(source_id: Any) -> dict[str, Any]:
    """顏色／有無：HSV 範圍遮罩 → 像素計數 → 門檻。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("mask", "color_range", 1, 0, "Red mask", h_low=0, h_high=12, s_low=80, s_high=255, v_low=60, v_high=255),
        _node("cnt", "pixel_count", 2, 0, "Count", min_count=50000),
        _node("cmp", "if_number", 3, 0, "Enough pixels?", operator="ge", threshold=50000),
        _node("ok", "judge", 4, 0, "OK: present", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: missing", verdict="ng", label="missing"),
        _node("out", "output", 3, 1, "Output pixel count", name="pixels"),
    ]
    edges = [
        _edge("src", "mask"), _edge("mask", "cnt"),
        _edge("cnt", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("cnt", "out", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def barcode_flow(source_id: Any) -> dict[str, Any]:
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("bc", "barcode", 2, 0, "Read code"),
        _node("cmp", "if_number", 3, 0, "Anything read?", operator="ge", threshold=1),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: nothing read", verdict="ng", label="no_code"),
        _node("out", "output", 3, 1, "Output content", name="code"),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "bc"),
        _edge("bc", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("bc", "out", "first", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def guided_code_read_flow(source_id: Any) -> dict[str, Any]:
    """先以偵測框帶動 ROI, 再裁切放大後讀碼。"""
    code_roi = {"shape": "rect", "x": 900, "y": 240, "w": 160, "h": 160}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("det", "ai_detect", 1, 0, "Find code area", model_size="n", conf=0.25, min_count=1, max_count=5, imgsz=640),
        _node("align", "shape_align", 2, 0, "Use box position", ref_x=978, ref_y=318, ref_angle=0, use_angle=False),
        _node("roi", "fixture_roi", 3, 0, "ROI follows box", roi=code_roi),
        _node("crop", "crop", 4, 0, "Crop code area"),
        _node("zoom", "resize", 5, 0, "Enlarge crop", scale=3.0),
        _node("bc", "barcode", 6, 0, "Read code", types="qr"),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG: nothing read", verdict="ng", label="no_code"),
        _node("out", "output", 7, 2, "Output content", name="code"),
        _node("draw", "draw_result", 6, 2, "Result image"),
        _note("n1", 0, 1, "About", "Use this when the code is small, moves around, or sits on a busy background.\nThe stock detector setting is only here to demonstrate the wiring. For production, train a detector for the code location and select that model asset."),
    ]
    edges = [
        _edge("src", "det"),
        _edge("det", "align", "matches", "matches"),
        _edge("align", "roi", "transform", "transform"),
        _edge("src", "crop", "image", "image"),
        _edge("roi", "crop", "region", "roi"),
        _edge("crop", "zoom", "image", "image"),
        _edge("zoom", "bc", "image", "image"),
        _edge("bc", "ok", "found", "_flow"),
        _edge("bc", "ng", "not_found", "_flow"),
        _edge("bc", "out", "first", "value"),
        _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def circle_gauge_flow(source_id: Any) -> dict[str, Any]:
    """圓孔尺寸量測：找圓 → 直徑 → 像素校正成 mm → 公差判定；扇形 ROI 弧擬合看真圓度。

    對齊合成圖「圓孔量測」：孔半徑標稱 175px（NG 張 190px）；0.05 mm/px → ⌀17.5mm ±0.4。"""
    roi = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 110, "r_outer": 260}
    arc_roi = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 110, "r_outer": 260, "a0": 200, "a1": 340}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("fc", "find_circle", 2, 0, "Find hole", roi=roi, polarity="any", edge_threshold=20, num_rays=72),
        _node("dia", "formula", 3, 0, "Diameter = 2r", expression="a*2"),
        _node("cal", "calibration", 4, 0, "Pixel calibration", mode="pixel_size", pixel_size_mm=0.05),
        _node("tol", "tolerance_judge", 5, 0, "Diameter tolerance", nominal=17.5, upper_tol=0.4, lower_tol=-0.4, unit="mm", spec_source="Drawing: dia 17.5 +/- 0.4", name="diameter"),
        _node("jd", "judge", 6, 0, "OK / NG", verdict="by_input", label="diameter"),
        _node("out", "output", 5, 1, "Output diameter mm", name="diameter_mm"),
        _node("arc", "fit_arc", 2, 1, "Upper arc fit", roi=arc_roi, polarity="any", edge_threshold=20),
        _node("ell", "fit_ellipse", 2, 2, "Ellipse fit for roundness", roi=roi, polarity="any", edge_threshold=20),
        _node("out_r", "output", 3, 2, "Output roundness", name="roundness"),
        _node("nf", "judge", 3, 1, "NG: hole not found", verdict="ng", label="not_found"),
        _node("draw", "draw_result", 6, 1, "Result image"),
        _note("n1", 0, 1, "About", "The circle find's annulus covers the hole edge; the arc fit shows a sector ROI taking only the upper half.\nThe tolerance judge works in millimetres: pixel calibration turns a 350 px diameter at 0.05 mm/px into 17.5 mm."),
    ]
    edges = [
        _edge("src", "gray"),
        _edge("gray", "fc", "image", "image"),
        _edge("fc", "dia", "r", "a"), _edge("fc", "nf", "not_found", "_flow"),
        _edge("dia", "cal", "value", "value"),
        _edge("cal", "tol", "mm", "value"),
        _edge("tol", "jd", "in_spec", "value"),
        _edge("cal", "out", "mm", "value"),
        _edge("gray", "arc", "image", "image"),
        _edge("gray", "ell", "image", "image"),
        _edge("ell", "out_r", "roundness", "value"),
        _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def edge_angle_flow(source_id: Any) -> dict[str, Any]:
    """邊線夾角：兩條找線 → 夾角 → 公差；交點座標輸出；斜切角用倒角量測。

    對齊合成圖「邊線夾角」：L 形工件兩邊標稱 90°（NG 張 84°）、底邊右端 45° 斜切角。"""
    roi_base = {"shape": "rect", "x": 460, "y": 500, "w": 460, "h": 120}
    roi_arm = {"shape": "rect", "x": 200, "y": 280, "w": 200, "h": 340}
    roi_cham = {"shape": "rect", "x": 940, "y": 540, "w": 160, "h": 200}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("l1", "find_line", 2, 0, "Bottom edge", roi=roi_base, polarity="any", edge_threshold=20),
        _node("l2", "find_line", 2, 1, "Side edge", roi=roi_arm, polarity="any", edge_threshold=20),
        _node("ang", "angle", 3, 0, "Angle", range="0_90"),
        _node("rng", "in_range", 4, 0, "89°～91°？", low=89, high=91),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG: angle out of tolerance", verdict="ng", label="angle"),
        _node("geo", "geometry", 3, 1, "Line intersection", mode="intersect"),
        _node("out_a", "output", 4, 1, "Output angle", name="angle_deg"),
        _node("out_x", "output", 4, 2, "Output intersection X", name="corner_x"),
        _node("cham", "chamfer_angle", 2, 2, "Chamfer angle", roi=roi_cham, polarity="any", edge_threshold=20),
        _node("out_c", "output", 3, 2, "Output chamfer angle", name="chamfer_deg"),
        _note("n1", 0, 1, "About", "Each line find boxes one edge, and the angle tool takes both lines directly.\nThe chamfer measurement boxes the bevel at the bottom right (nominally 45 degrees). A line that is not found takes the not_found branch."),
        _node("nf", "judge", 3, 2, "NG: edge not found", verdict="ng", label="no_edge"),
    ]
    edges = [
        _edge("src", "gray"),
        _edge("gray", "l1", "image", "image"), _edge("gray", "l2", "image", "image"),
        _edge("l1", "ang", "line", "a"), _edge("l2", "ang", "line", "b"),
        _edge("l1", "geo", "line", "a"), _edge("l2", "geo", "line", "b"),
        _edge("l1", "nf", "not_found", "_flow"), _edge("l2", "nf", "not_found", "_flow"),
        _edge("ang", "rng", "angle_deg", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("ang", "out_a", "angle_deg", "value"),
        _edge("geo", "out_x", "x", "value"),
        _edge("gray", "cham", "image", "image"),
        _edge("cham", "out_c", "angle_deg", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def golden_compare_flow(source_id: Any, template_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """印刷良品比對：與良品範本做差異比對，任何多印／髒污／缺損都算缺陷。

    對齊合成圖「印刷良品比對」：第 1 張＝良品（seed 已存成資產），NG 張多一塊污漬。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("diff", "defect_diff", 1, 0, "Golden compare", align="phase", threshold=45, min_area=200),
        _node("ref", "fixed_image", 0, 3, "Golden sample picture", images=[template_ref] if template_ref else [], mode="fixed", index=1, role="reference"),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: appearance defect", verdict="ng", label="defect"),
        _node("out_n", "output", 2, 2, "Output defect count", name="defect_count"),
        _node("out_a", "output", 3, 2, "Output defect area", name="defect_area"),
        _node("draw", "draw_result", 3, 0, "Result image"),
        _note("n1", 0, 1, "About", "The golden sample is the first sample image, carried by the Fixed image step wired into the golden-compare tool's picture input.\nDisplacement is corrected automatically by phase alignment; the difference threshold and the minimum area set the sensitivity."),
    ]
    edges = [
        _edge("ref", "diff", "image", "template_image"),
        _edge("src", "diff"),
        _edge("diff", "ok", "ok", "_flow"), _edge("diff", "ng", "defect", "_flow"),
        _edge("diff", "out_n", "count", "value"), _edge("diff", "out_a", "total_area", "value"),
        _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def fft_defect_flow(source_id: Any) -> dict[str, Any]:
    """織紋瑕疵（頻域）：低通濾波把週期性織紋濾掉 → 剩下的暗痕就是刮痕 → blob 判定。

    對齊合成圖「織紋瑕疵」：NG 張有一道斜向刮痕；正常織紋在頻域是高頻，會被低通吃掉。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("fft", "fft_filter", 2, 0, "Frequency low pass", mode="lowpass", cutoff=0.08),
        _node("thr", "threshold", 3, 0, "Find dark marks", method="fixed", threshold=95, invert=True),
        _node("mor", "morphology", 4, 0, "Open to remove specks", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "Scratch blobs", threshold_method="fixed", threshold=128, polarity="bright", min_area=800, min_count=0),
        _node("cmp", "if_number", 6, 0, "No scratches?", operator="eq", threshold=0),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG: surface scratch", verdict="ng", label="scratch"),
        _node("mask", "apply_mask", 5, 2, "Defect area only", fill=0),
        _node("out", "output", 6, 1, "Output scratch count", name="scratch_count"),
        _node("draw", "draw_result", 7, 2, "Result image"),
        _note("n1", 0, 1, "About", 'Frequency filtering is the strongest tool against a textured background: a regular weave is a fixed frequency, a low pass cuts it out,\nand the large dark mark left behind is the defect. "Defect area only" shows how a mask is applied.'),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "fft"),
        _edge("fft", "thr", "image", "image"),
        _edge("thr", "mor"), _edge("mor", "blob"),
        _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("gray", "mask", "image", "image"), _edge("blob", "mask", "mask", "mask"),
        _edge("blob", "out", "count", "value"),
        _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def preprocess_lab_flow(source_id: Any) -> dict[str, Any]:
    """前處理與量測教學：位深→查找表→濾波→翻轉的影像鏈，搭配剖面／統計／直方圖／邊緣密度。

    對齊合成圖「前處理教學圖」：水平漸層＋灰階階梯＋一條暗溝（線剖面的谷值量得到）。"""
    groove = {"shape": "line", "x1": 640, "y1": 520, "x2": 640, "y2": 720}
    center = {"shape": "rect", "x": 440, "y": 360, "w": 400, "h": 200}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("cd", "convert_depth", 1, 0, "Convert to 8-bit", to="u8"),
        _node("lut", "lut", 2, 0, "Gamma correction", mode="gamma", gamma=0.8),
        _node("fil", "filter", 3, 0, "Sharpen", method="sharpen", strength=1.0),
        _node("flip", "rotate_flip", 4, 0, "Flip horizontally", flip="horizontal"),
        _node("prof", "line_profile", 2, 1, "Groove profile", roi=groove),
        _node("out_g", "output", 3, 1, "Output groove grey level", name="groove_min"),
        _node("inten", "intensity", 2, 2, "Centre statistics", roi=center),
        _node("out_m", "output", 3, 2, "Output mean brightness", name="center_mean"),
        _node("hist", "histogram", 2, 3, "Histogram"),
        _node("out_o", "output", 3, 3, "Output Otsu threshold", name="otsu"),
        _node("diff", "arithmetic", 5, 0, "Before and after difference", op="absdiff"),
        _node("din", "intensity", 6, 0, "Mean difference"),
        _node("out_d", "output", 7, 0, "Output processing difference", name="diff_mean"),
        _node("gray", "grayscale", 1, 2, "Grayscale"),
        _node("crop", "crop", 1, 3, "Crop centre", roi=center),
        _node("cc", "color_convert", 2, 4, "Saturation plane", mode="hsv_s"),
        _node("ed", "edge_density", 5, 1, "Edge density gate", max_ratio=0.2),
        _node("ok", "judge", 6, 1, "OK", verdict="ok"),
        _node("ng", "judge", 6, 2, "NG: image abnormal", verdict="ng", label="edge_density"),
        _node("dark", "dark_ratio", 5, 3, "Dark ratio", threshold=60, max_ratio=0.2),
        _node("out_k", "output", 6, 3, "Output dark ratio", name="dark_ratio"),
        _note("n1", 0, 1, "About", "The top row is an image chain: bit depth, gamma, sharpen, flip, with the arithmetic tool quantifying the change.\nThe bottom row is a tour of the measurement tools: a line profile across the groove, region statistics, a histogram, edge density and the dark ratio."),
    ]
    edges = [
        _edge("src", "cd"), _edge("cd", "lut", "image", "image"), _edge("lut", "fil"), _edge("fil", "flip"),
        _edge("cd", "prof", "image", "image"), _edge("prof", "out_g", "min", "value"),
        _edge("cd", "inten", "image", "image"), _edge("inten", "out_m", "mean", "value"),
        _edge("cd", "hist", "image", "image"), _edge("hist", "out_o", "otsu", "value"),
        _edge("cd", "diff", "image", "a"), _edge("flip", "diff", "image", "b"),
        _edge("diff", "din", "image", "image"), _edge("din", "out_d", "mean", "value"),
        _edge("src", "gray"), _edge("gray", "crop", "image", "image"),
        _edge("src", "cc", "image", "image"),
        _edge("gray", "ed", "image", "image"),
        _edge("ed", "ok", "ok", "_flow"), _edge("ed", "ng", "ng", "_flow"),
        _edge("crop", "dark", "image", "image"), _edge("dark", "out_k", "ratio", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def geometry_count_flow(source_id: Any) -> dict[str, Any]:
    """多圓幾何：霍夫找圓計數 → 判定；霍夫找線清單計數；兩孔找圓 → 圓心距量測。

    對齊合成圖「多圓幾何」：5 個圓孔＋2 條斜線（NG 張少一個圓）。"""
    roi_a = {"shape": "circle", "cx": 300, "cy": 300, "r": 110}
    roi_b = {"shape": "circle", "cx": 980, "cy": 320, "r": 120}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("hc", "hough_circles", 2, 0, "Hough circles", min_radius=50, max_radius=110, min_dist=120, param2=20),
        _node("cmp", "if_number", 3, 0, "5 holes?", operator="eq", threshold=5),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: wrong hole count", verdict="ng", label="hole_count"),
        _node("out_n", "output", 3, 1, "Output hole count", name="circle_count"),
        _node("hl", "hough_lines", 2, 1, "Hough lines", threshold=80, min_length=300, max_gap=20),
        _node("cl", "count_list", 3, 2, "Line count"),
        _node("out_l", "output", 4, 2, "Output line count", name="line_count"),
        _node("fa", "find_circle", 2, 3, "Top-left hole", roi=roi_a, polarity="any", edge_threshold=20),
        _node("fb", "find_circle", 2, 4, "Top-right hole", roi=roi_b, polarity="any", edge_threshold=20),
        _node("dist", "distance", 3, 3, "Centre distance"),
        _node("out_d", "output", 4, 3, "Output centre distance", name="pitch_px"),
        _note("n1", 0, 1, "About", "Hough is for grabbing many circles at once; the radial circle find is for measuring one circle precisely.\nThe distance tool takes both circle centres directly and gives the hole spacing."),
    ]
    edges = [
        _edge("src", "gray"),
        _edge("gray", "hc", "image", "image"),
        _edge("hc", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("hc", "out_n", "count", "value"),
        _edge("gray", "hl", "image", "image"),
        _edge("hl", "cl", "lines", "items"),
        _edge("cl", "out_l", "count", "value"),
        _edge("gray", "fa", "image", "image"), _edge("gray", "fb", "image", "image"),
        _edge("fa", "dist", "cx", "ax"), _edge("fa", "dist", "cy", "ay"),
        _edge("fb", "dist", "cx", "bx"), _edge("fb", "dist", "cy", "by"),
        _edge("dist", "out_d", "distance", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def surface_scratch_flow(source_id: str) -> dict:
    """表面缺陷濾波：拉絲金屬面上的細刮傷。

    與「織紋瑕疵」是一對：那邊的背景是規則的（低通就濾掉），這邊是隨機的拉絲紋理，
    頻域那一招無效，只能靠「沿著缺陷方向平均、跨著缺陷方向微分」把細長的東西挑出來。
    """
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("filt", "surface_filter", 2, 0, "Surface defect filter", polarity="dark", width=3, length=31, directions=8, gain=14),
        _node("thr", "threshold", 3, 0, "Keep the strong answers", method="fixed", threshold=150),
        _node("blob", "blob", 4, 0, "Scratch blobs", threshold_method="none", polarity="bright", min_area=250, min_count=0),
        _node("cmp", "if_number", 5, 0, "No scratches?", operator="eq", threshold=0),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: surface scratch", verdict="ng", label="scratch"),
        _node("out", "output", 5, 1, "Output scratch count", name="scratch_count"),
        _node("peak", "output", 5, 2, "Output the strongest answer", name="peak"),
        _node("draw", "draw_result", 6, 2, "Result image"),
        _note("n1", 0, 1, "About", "A brushed surface has no repeating pattern, so a frequency filter cannot separate it from a scratch (compare the fabric template).\nThis filter averages along the mark and differentiates across it at eight angles, so a long thin mark stands out and the grain does not.\nTurn the gain up until the mark is clear and the surface stays dark, then set the threshold."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "filt"),
        _edge("filt", "thr", "image", "image"),
        _edge("thr", "blob"),
        _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
        _edge("filt", "peak", "max_response", "value"),
        _edge("gray", "draw", "image", "image"),
        _edge("blob", "draw", "_overlays", "overlays"),
    ]
    return {"nodes": nodes, "edges": edges}


def edge_defect_flow(source_id: str) -> dict:
    """邊緣缺陷：一顆工具沿圓周佈卡尺、找缺陷、分類（與「圓周崩邊」是同一組樣本的兩種做法）。

    圓周崩邊那條是「圓形卡尺 → 半徑序列 → 序列缺陷」三顆工具接起來；這裡是一顆工具做完，
    而且每個缺陷都帶外框、長度與種類（偏移／斷裂／階差）。
    """
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("circle", "find_circle", 2, 0, "Find the rim", roi={"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 250, "r_outer": 340},
              polarity="light_to_dark", edge_threshold=25, num_rays=72),
        _node("edge", "edge_defect", 3, 0, "Edge defects", calipers=180, search=40, edge_threshold=25,
              polarity="light_to_dark", threshold=3.0, min_width=2, fracture_run=2, max_defects=0),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: chipped rim", verdict="ng", label="chip"),
        _node("out", "output", 4, 2, "Output how many", name="defect_count"),
        _node("size", "output", 4, 3, "Output the longest", name="defect_size"),
        _node("draw", "draw_result", 5, 2, "Result image"),
        _note("n1", 0, 1, "About", "The rim is found first, so the ideal edge is the circle this part actually has, not where it was taught.\nEvery caliper that finds no edge at all is a break; a run that sits too far in or out is a nick or a burr.\nCompare with the chipped-rim template, which builds the same check out of three separate steps."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "circle"),
        _edge("gray", "edge", "image", "image"),
        _edge("circle", "edge", "circle", "circle"),
        _edge("edge", "ok", "ok", "_flow"), _edge("edge", "ng", "defect", "_flow"),
        _edge("edge", "out", "count", "value"),
        _edge("edge", "size", "max_size", "value"),
        _edge("gray", "draw", "image", "image"),
        _edge("edge", "draw", "_overlays", "overlays"),
    ]
    return {"nodes": nodes, "edges": edges}


def gear_teeth_flow(source_id: Any) -> dict[str, Any]:
    """圓周齒數：極座標展開齒圈 → 二值化 → blob 數齒 → 12 齒判定；齒的位置用 polar_restore 標回原圖。

    對齊合成圖「齒輪齒數」：齒根 r=260、齒頂 r=320，展開 r 270～330 的環帶，每齒在展開圖上是一塊亮矩形；起始角 18° 落在齒隙（接縫不切齒）。"""
    ring = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 270, "r_outer": 330}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("polar", "polar_unwrap", 2, 0, "Unwrap the tooth ring", roi=ring, angle_step="auto", direction="cw", start_angle=18),
        _node("thr", "threshold", 3, 0, "Bright teeth", method="fixed", threshold=100),
        _node("blob", "blob", 4, 0, "Tooth blobs", threshold_method="none", min_area=400, sort_by="x"),
        _node("cmp", "if_number", 5, 0, "12 teeth?", operator="eq", threshold=12),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: tooth missing", verdict="ng", label="tooth_count"),
        _node("out", "output", 5, 1, "Output tooth count", name="tooth_count"),
        _node("restore", "polar_restore", 5, 2, "Teeth on the original"),
        _note("n1", 0, 1, "About", "The ring between the root and tip radius is flattened into a strip, so every tooth becomes a bright block and the gaps become dark columns.\nBlob counts the blocks; Polar restore puts their centres back on the original picture. The fourth image is missing a tooth."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "polar", "image", "image"), _edge("polar", "thr", "image", "image"), _edge("thr", "blob", "image", "image"),
        _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
        _edge("src", "restore", "image", "image"), _edge("polar", "restore", "mapping", "mapping"),
        _edge("blob", "restore", "centers", "points"), _edge("blob", "restore", "contours", "contours"),
    ]
    return {"nodes": nodes, "edges": edges}


def contour_defect_flow(source_id: Any, template_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """輪廓崩邊檢測：contour_find（外輪廓）→ contour_filter（最大一條＝工件）→ contour_geometry（凸缺陷）→ 缺陷數＝0 → OK；
    另用 contour_match 與範例外形資產比 Hu 矩距離（換料／變形守門）。對齊合成圖「沖壓件」：第 4 張上緣崩邊（缺陷深約 40 px）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("find", "contour_find", 2, 0, "Outer contours", threshold_method="otsu", polarity="bright", mode="external", min_area=20000),
        _node("keep", "contour_filter", 3, 0, "Keep the part", min_area=100000, sort_by="area", max_count=1),
        _node("geo", "contour_geometry", 4, 0, "Geometry and chips", defect_depth=12),
        _node("cmp", "if_number", 5, 0, "No chips?", operator="eq", threshold=0),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: chipped edge", verdict="ng", label="chipped_edge"),
        _node("out_d", "output", 5, 1, "Output chip count", name="chip_count"),
        _node("out_a", "output", 5, 2, "Output area", name="part_area_px"),
        _node("match", "contour_match", 4, 2, "Outline vs. sample", max_distance=0.05),
        _node("ref", "fixed_image", 0, 3, "Sample outline picture", images=[template_ref] if template_ref else [], mode="fixed", index=1, role="reference"),
        _node("out_m", "output", 5, 3, "Output shape distance", name="shape_distance"),
        _note("n1", 0, 1, "About", "Contour find traces the outline, the filter keeps only the largest one (the part), and contour geometry reports its convexity defects — a bite out of the edge deeper than 12 px is a chip.\nContour match compares the silhouette with the sample outline by Hu moments: a wrong or badly deformed part scores a large distance."),
    ]
    edges = [
        _edge("ref", "match", "image", "template_image"),
        _edge("src", "gray"), _edge("gray", "find", "image", "image"),
        _edge("find", "keep", "contours", "contours"), _edge("keep", "geo", "contours", "contours"), _edge("gray", "geo", "image", "image"),
        _edge("geo", "cmp", "first_defects", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("geo", "out_d", "first_defects", "value"), _edge("geo", "out_a", "first_area", "value"),
        _edge("keep", "match", "contours", "contours"), _edge("gray", "match", "image", "image"),
        _edge("match", "out_m", "distance", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def exclusion_zone_flow(source_id: Any) -> dict[str, Any]:
    """排除區：板面量測區挖掉中央孔（孔徑會變）與角落料號區 → intensity 平均只算板面 → in_range 判定曝光／髒污。

    對齊合成圖「圓孔尺寸量測」（亮板 190 灰階、中央暗孔 r 174～190）：不挖孔時平均約 150 且隨孔徑跳動，挖掉後穩定在 190 上下。"""
    plate = {"shape": "rect", "x": 180, "y": 140, "w": 920, "h": 680}
    hole = {"shape": "circle", "cx": 640, "cy": 480, "r": 215}
    corner = {"shape": "rect", "x": 900, "y": 700, "w": 200, "h": 120}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("hole", "region_from_shape", 1, 1, "Hole (exclude)", roi=hole),
        _node("corner", "region_from_shape", 1, 2, "Label area (exclude)", roi=corner),
        _node("combine", "region_combine", 2, 1, "Plate minus holes", base=plate, mode="subtract"),
        _node("stats", "intensity", 3, 0, "Plate brightness"),
        _node("rng", "in_range", 4, 0, "Plate 170 to 215?", low=170, high=215),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG: plate too dark or bright", verdict="ng", label="plate_brightness"),
        _node("out", "output", 4, 1, "Output plate mean", name="plate_mean"),
        _node("blob", "blob", 3, 2, "Dark marks on the plate", threshold_method="fixed", threshold=120, polarity="dark", min_area=200, min_count=0),
        _node("out_b", "output", 4, 2, "Output mark count", name="mark_count"),
        _note("n1", 0, 1, "About", "Two Region steps draw the exclusion zones; Region combine cuts them out of the plate rectangle and feeds the result into the region input of the statistics and blob steps.\nThe hole changes size from picture to picture, yet the plate mean stays put because the hole pixels are never counted."),
    ]
    edges = [
        _edge("src", "gray"),
        _edge("hole", "combine", "region", "regions"), _edge("corner", "combine", "region", "regions"), _edge("gray", "combine", "image", "image"),
        _edge("gray", "stats", "image", "image"), _edge("combine", "stats", "region", "roi"),
        _edge("stats", "rng", "mean", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("stats", "out", "mean", "value"),
        _edge("gray", "blob", "image", "image"), _edge("combine", "blob", "region", "roi"),
        _edge("blob", "out_b", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def shading_flow(source_id: Any, flat_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """平場校正：白板參考影像除掉漸暈 → 固定門檻找暗污點 → blob 計數 → 6 顆＝OK。

    對齊合成圖「打光不均」：角落亮度只剩 45%，不校正時固定門檻在角落整片誤判；校正後每張 6 顆（第 4 張多一大塊 → 7，NG）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("flat", "shading_correct", 2, 0, "Flat-field correction", mode="flat_field", target_level=200),
        _node("ref", "fixed_image", 0, 3, "White reference picture", images=[flat_ref] if flat_ref else [], mode="fixed", index=1, role="reference"),
        _node("thr", "threshold", 3, 0, "Dark spots", method="fixed", threshold=120, invert=True),
        _node("blob", "blob", 4, 0, "Spot blobs", threshold_method="none", min_area=400, max_area=20000),
        _node("cmp", "if_number", 5, 0, "6 spots?", operator="eq", threshold=6),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: extra mark", verdict="ng", label="spot_count"),
        _node("out", "output", 5, 1, "Output spot count", name="spot_count"),
        _node("raw_thr", "threshold", 3, 2, "Same threshold, no correction", method="fixed", threshold=120, invert=True),
        _node("raw_blob", "blob", 4, 2, "Spots without correction", threshold_method="none", min_area=400),
        _node("out_raw", "output", 5, 2, "Output uncorrected count", name="spot_count_uncorrected"),
        _note("n1", 0, 1, "About", "The lighting falls to 45% in the corners. The white-reference asset was taken under the same light, so dividing by it flattens the field and one fixed threshold works everywhere.\nThe lower branch runs the same threshold on the uncorrected image: the dark corners swallow the spots and the count is wrong."),
    ]
    edges = [
        _edge("ref", "flat", "image", "flat_image"),
        _edge("src", "gray"), _edge("gray", "flat", "image", "image"), _edge("flat", "thr", "image", "image"), _edge("thr", "blob", "image", "image"),
        _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
        _edge("gray", "raw_thr", "image", "image"), _edge("raw_thr", "raw_blob", "image", "image"), _edge("raw_blob", "out_raw", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def stat_compare_flow(source_id: Any, model_asset: str = "") -> dict[str, Any]:
    """統計良品比對：defect_stat（30 張良品建的 mean／std 範本）→ 缺陷數 → OK/NG；旁邊放 defect_diff 對照同一張。

    對齊合成圖「印刷良品比對」（第 4 張多一塊污漬）：σ 門檻 4 不必為了打光波動放鬆。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("stat", "defect_stat", 2, 0, "Statistical compare", model=model_asset, sigma=4, min_area=30),
        _node("cmp", "if_number", 3, 0, "No defects?", operator="eq", threshold=0),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: print defect", verdict="ng", label="print_defect"),
        _node("out", "output", 3, 1, "Output defect count", name="defect_count"),
        _node("out_s", "output", 3, 2, "Output max deviation", name="max_sigma"),
        _note("n1", 0, 1, "About", "The statistical template was built by seeding from 30 good prints with brightness jitter and small shifts, so every pixel knows its own normal spread.\nA defect is anything more than 4 standard deviations from normal; the fourth image carries a smudge."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "stat", "image", "image"),
        _edge("stat", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("stat", "out", "count", "value"), _edge("stat", "out_s", "max_sigma", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def shape_match_flow(source_id: Any, model_asset: str = "") -> dict[str, Any]:
    """形狀比對定位：shape_match（任意角度、變暗、雜物都找得到）→ found/not_found → shape_align → fixture_roi 讓量測 ROI 跟著件走。

    對齊合成圖「形狀比對」：第 1 張正放（seed 用它建模）、第 2 張轉 37° 變暗、第 3 張轉 −120° 加雜物、第 4 張是別的零件（NG）。"""
    ref = {"shape": "rect", "x": 640 - 110, "y": 480 - 80, "w": 220, "h": 160}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("shape", "shape_match", 2, 0, "Find the bracket", model=model_asset, min_score=0.6, max_matches=1),
        _node("ok", "judge", 3, 0, "OK: found", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG: not this part", verdict="ng", label="part_not_found"),
        _node("out_x", "output", 3, 2, "Output X", name="part_x"),
        _node("out_y", "output", 4, 2, "Output Y", name="part_y"),
        _node("out_a", "output", 3, 3, "Output angle", name="part_angle"),
        _node("out_s", "output", 4, 3, "Output score", name="shape_score"),
        _node("align", "shape_align", 4, 0, "Locate offset", ref_x=640 + 0, ref_y=480 + 0, ref_angle=0),
        _node("follow", "fixture_roi", 5, 0, "Part box follows", roi=ref),
        _node("stats", "intensity", 6, 0, "Part brightness"),
        _note("n1", 0, 1, "About", "Shape match scores the direction of edges, not grey values: the second picture is darker and turned 37°, the third is turned −120° among clutter, and both are found with a high score.\nThe fourth picture holds a different part, so nothing scores above 0.6 and the flow takes the NG branch. The model asset is built by seeding from the first picture."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "shape", "image", "image"),
        _edge("shape", "ok", "found", "_flow"), _edge("shape", "ng", "not_found", "_flow"),
        _edge("shape", "out_x", "best_x", "value"), _edge("shape", "out_y", "best_y", "value"),
        _edge("shape", "out_a", "best_angle", "value"), _edge("shape", "out_s", "best_score", "value"),
        _edge("shape", "align", "matches", "matches"), _edge("shape", "align", "found", "_flow"), _edge("align", "follow", "transform", "transform"),
        _edge("gray", "stats", "image", "image"), _edge("follow", "stats", "region", "roi"),
    ]
    return {"nodes": nodes, "edges": edges}


def circular_defect_flow(source_id: Any) -> dict[str, Any]:
    """圓形工件崩邊：circular_caliper 沿圓周 180 把卡尺量半徑 → profile_defect 對擬合圓看凹陷／打空 → 缺陷數＝0 → OK；另輸出徑向跳動。

    對齊合成圖「圓盤崩邊」：第 4 張右下緣 24°×7 px 缺口（NG）。"""
    ring = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 250, "r_outer": 350}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("cal", "circular_caliper", 2, 0, "Radius at 180 angles", roi=ring, caliper_count=180, polarity="light_to_dark", edge_select="first", edge_threshold=20),
        _node("pd", "profile_defect", 3, 0, "Chips on the rim", baseline="fit_circle", threshold=3, min_width=2, direction="inward"),
        _node("cmp", "if_number", 4, 0, "No chips?", operator="eq", threshold=0),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG: chipped rim", verdict="ng", label="rim_chip"),
        _node("out_n", "output", 4, 1, "Output chip count", name="chip_count"),
        _node("out_r", "output", 3, 2, "Output run-out", name="runout_px"),
        _node("out_m", "output", 4, 2, "Output mean radius", name="radius_px"),
        _note("n1", 0, 1, "About", "The circular caliper measures the radius at every 2°; the run-out (max minus min) is the out-of-round. Profile defects fits a circle to those points and marks every stretch that sinks 3 px below it — or where a caliper found no edge at all, which is what a large chip looks like.\nThe defect is drawn as a red arc on the rim of the original picture."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "cal", "image", "image"),
        _edge("cal", "pd", "radii", "values"), _edge("cal", "pd", "all_points", "points"), _edge("gray", "pd", "image", "image"),
        _edge("pd", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("pd", "out_n", "count", "value"), _edge("cal", "out_r", "runout", "value"), _edge("cal", "out_m", "mean_r", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def emboss_defect_flow(source_id: Any) -> dict[str, Any]:
    """刻印字／凹凸缺陷：四個象限各裁成一張打光影像 → photometric_stereo（shape strength）→ 凹坑區 pixel_count ≤ 40 → OK。

    對齊合成圖「浮凸板（四燈）」：第 4 張右上角區多一個凹坑（NG）；反射率斑駁讓單張二值化抓不到任何形狀。"""
    q = [{"shape": "rect", "x": 0, "y": 0, "w": 640, "h": 480}, {"shape": "rect", "x": 640, "y": 0, "w": 640, "h": 480},
         {"shape": "rect", "x": 0, "y": 480, "w": 640, "h": 480}, {"shape": "rect", "x": 640, "y": 480, "w": 640, "h": 480}]
    from apps.vision import demo_images as _di

    zone = dict(_di.EMBOSS_DENT_ZONE)
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("q1", "crop", 1, 0, "Light 1 (right)", roi=q[0]),
        _node("q2", "crop", 1, 1, "Light 2 (below)", roi=q[1]),
        _node("q3", "crop", 1, 2, "Light 3 (left)", roi=q[2]),
        _node("q4", "crop", 1, 3, "Light 4 (above)", roi=q[3]),
        _node("ps", "photometric_stereo", 2, 0, "Surface shape", light_azimuth=[0, 90, 180, 270], light_elevation=30, output="curvature_abs"),
        _node("px", "pixel_count", 3, 0, "Shape pixels in the check zone", roi=zone, threshold=90, min_count=0, max_count=40),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: surface dent", verdict="ng", label="dent"),
        _node("out_n", "output", 4, 2, "Output shape pixels", name="dent_pixels"),
        _note("n1", 2, 2, "About", "The same plate is photographed four times, each time lit from a different side; the sample picture tiles those four views 2×2 and the Crop steps split them again. Photometric stereo solves the surface normal at every pixel and its shape-strength map shows where the surface bends — the embossed characters and any dent — while ignoring the mottled reflectance that defeats a threshold on any single picture.\nThe pixel-count step counts shape pixels inside the check zone above the characters; more than 40 of them means a dent, and that is NG. (A blob count would call an empty zone \u2018not found\u2019 and mark the run NG, so a pixel count is the right tool when nothing is the good answer.)"),
    ]
    edges = [
        _edge("src", "q1"), _edge("src", "q2"), _edge("src", "q3"), _edge("src", "q4"),
        _edge("q1", "ps", "image", "image"), _edge("q2", "ps", "image", "image_1"), _edge("q3", "ps", "image", "image_2"), _edge("q4", "ps", "image", "image_3"),
        _edge("ps", "px", "image", "image"),
        _edge("px", "ok", "ok", "_flow"), _edge("px", "ng", "ng", "_flow"),
        _edge("px", "out_n", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def form_tolerance_flow(source_id: Any) -> dict[str, Any]:
    """真圓度（形位公差）：circular_caliper 沿圓周 180 把卡尺取邊緣點 → gdt_measure(roundness, MZC) → 公差 5 px 內 → OK。

    對齊合成圖「圓盤崩邊」：第 4 張右下緣 7 px 深的缺口讓最小區域帶寬超過公差（NG）。"""
    ring = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 250, "r_outer": 350}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("cal", "circular_caliper", 2, 0, "Edge points at 180 angles", roi=ring, caliper_count=180, polarity="light_to_dark", edge_select="first", edge_threshold=20),
        _node("gdt", "gdt_measure", 3, 0, "Roundness (minimum zone)", mode="roundness", tolerance=5, unit="px"),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: out of round", verdict="ng", label="roundness"),
        _node("out_d", "output", 4, 2, "Output roundness", name="roundness_px"),
        _note("n1", 0, 1, "About", "Roundness the way a drawing states it (ISO 1101): the narrowest ring between two concentric circles that holds every edge point — the minimum-zone circle, not a least-squares residual. The detail of the tolerance step also reports the least-squares value and the two extreme points, so a disputed part can be argued from the numbers.\nThe same step measures straightness, flatness, parallelism, perpendicularity and angularity; switch the unit to millimetres and connect the calibration scale to report in mm."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "cal", "image", "image"),
        _edge("cal", "gdt", "points", "points"), _edge("gray", "gdt", "image", "image"),
        _edge("gdt", "ok", "pass", "_flow"), _edge("gdt", "ng", "fail", "_flow"),
        _edge("gdt", "out_d", "deviation", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def barcode_grade_flow(source_id: Any) -> dict[str, Any]:
    """條碼品質分級：barcode_grade（ISO 15415，最低 C）→ pass／fail；輸出總評字母、分數與內容。

    對齊合成圖「條碼分級」：1 乾淨 A、2 對比偏低 B、3 模糊雜訊 C、4 髒污與靜區污漬（NG）。"""
    from apps.vision import demo_images as _di

    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("grade", "barcode_grade", 1, 0, "Grade the Data Matrix", roi=dict(_di.BARCODE_GRADE_ROI), standard="iso15415", symbology="datamatrix", min_grade="C"),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: print quality", verdict="ng", label="barcode_grade"),
        _node("out_g", "output", 2, 2, "Output grade", name="grade"),
        _node("out_v", "output", 2, 3, "Output grade value", name="grade_value"),
        _node("out_t", "output", 3, 2, "Output content", name="content"),
        _note("n1", 0, 1, "About", "The grade step measures the symbol the way a verifier does (ISO/IEC 15415): symbol contrast, modulation, fixed pattern damage, axial and grid non-uniformity and unused error correction, each graded A to F, and the overall grade is the lowest of them. The parameters output lists every value with its grade, so a C can be traced to the cause — low contrast, a dirty quiet zone, damaged modules.\nSwitch the standard to ISO/IEC 15416 for linear codes or AIM DPM for marks on metal; switch the minimum grade to what the customer's specification demands."),
    ]
    edges = [
        _edge("src", "grade"),
        _edge("grade", "ok", "pass", "_flow"), _edge("grade", "ng", "fail", "_flow"),
        _edge("grade", "out_g", "grade", "value"), _edge("grade", "out_v", "grade_value", "value"), _edge("grade", "out_t", "text", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def color_verify_flow(source_id: Any) -> dict[str, Any]:
    """顏色比對：指定區域的平均色與目標色比距離 → 判定；顏色統計輸出色碼。

    對齊合成圖「顏色檢驗」：左側色塊標稱紅色（NG 張偏橘）。"""
    left = {"shape": "rect", "x": 150, "y": 330, "w": 240, "h": 300}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("chk", "color_check", 1, 0, "Red compare", roi=left, color="#d22828", space="rgb", tolerance=60),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: colour mismatch", verdict="ng", label="color"),
        _node("stat", "color_stats", 1, 1, "Colour statistics", roi=left),
        _node("out_h", "output", 2, 2, "Output hex code", name="hex"),
        _node("out_d", "output", 3, 1, "Output colour distance", name="color_distance"),
        _note("n1", 0, 1, "About", "Colour comparison measures the distance between the mean colour and a target, which suits verifying a material or a cap colour.\nColour statistics send the RGB and HSV means and a hex code out for the host system to record."),
    ]
    edges = [
        _edge("src", "chk"),
        _edge("chk", "ok", "match", "_flow"), _edge("chk", "ng", "mismatch", "_flow"),
        _edge("src", "stat", "image", "image"),
        _edge("stat", "out_h", "hex", "value"),
        _edge("chk", "out_d", "distance", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def label_flow(source_id: Any) -> dict[str, Any]:
    """條碼標籤：透視校正把斜貼標籤拉正 → 讀碼 → 判定；序號區文字有無檢查。

    對齊合成圖「條碼標籤」：標籤四角固定（透視校正的四點），NG 張沒印碼。"""
    quad = {"shape": "polygon", "points": [[330, 240], [940, 300], [900, 720], [290, 660]]}
    sn_roi = {"shape": "rect", "x": 140, "y": 370, "w": 300, "h": 45}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("warp", "warp_perspective", 1, 0, "Straighten label", roi=quad, width=560, height=420),
        _node("gray", "grayscale", 2, 0, "Grayscale"),
        _node("bc", "barcode", 3, 0, "Read code"),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: code not read", verdict="ng", label="no_code"),
        _node("out", "output", 4, 2, "Output content", name="code"),
        _node("txt", "text_presence", 3, 2, "Serial area printed?", roi=sn_roi, polarity="dark"),
        _node("ng2", "judge", 4, 3, "NG: serial not printed", verdict="ng", label="no_sn"),
        _note("n1", 0, 1, "About", "A crooked label still reads: four-point perspective correction straightens it first.\nText presence is decided by stroke density, and a missing serial number is an immediate NG."),
    ]
    edges = [
        _edge("src", "warp"),
        _edge("warp", "gray", "image", "image"),
        _edge("gray", "bc"),
        _edge("bc", "ok", "found", "_flow"), _edge("bc", "ng", "not_found", "_flow"),
        _edge("bc", "out", "first", "value"),
        _edge("gray", "txt", "image", "image"),
        _edge("txt", "ng2", "absent", "_flow"),
    ]
    return {"nodes": nodes, "edges": edges}


def yolo_count_flow(source_id: Any) -> dict[str, Any]:
    """YOLO 物件計數（官方底模）：ai_detect 只留 stop sign → 數量 = 2 → OK；不用訓練，第一次執行自動下載 yolo11n.pt。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("det", "ai_detect", 1, 0, "Find signs (AI)", model_size="n", conf=0.4, filter_labels="stop sign", min_count=1, imgsz=640),
        _node("cmp", "if_number", 2, 0, "2 signs?", operator="eq", threshold=2),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG: wrong count", verdict="ng", label="sign_count"),
        _node("out", "output", 2, 1, "Output count", name="sign_count"),
        _node("draw", "draw_result", 2, 2, "Result image"),
        _note("n1", 0, 1, "About", "The stock model recognises stop signs directly, with no training; the first run downloads about 5 MB of weights.\nFor your own objects: train an object detection (AI) project on the Deep learning page and select the result as the model asset."),
    ]
    edges = [
        _edge("src", "det"), _edge("det", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("det", "out", "count", "value"), _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def yolo_area_flow(source_id: Any) -> dict[str, Any]:
    """YOLO 實例分割（官方底模）：ai_segment 的聯合遮罩 → 像素計數（面積）→ 門檻判定；輸出標誌面積。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("seg", "ai_segment", 1, 0, "Segment signs (AI)", model_size="n", conf=0.4, filter_labels="stop sign", min_count=1, imgsz=640),
        _node("area", "pixel_count", 2, 0, "Sign area", threshold=128, min_count=15000, max_count=45000),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG: area out of range", verdict="ng", label="sign_area"),
        _node("out", "output", 2, 1, "Output area", name="sign_area"),
        _node("draw", "draw_result", 2, 2, "Result image"),
        _note("n1", 0, 1, "About", "A segmentation model returns each instance's outline and a union mask; the mask into a pixel count is the total area (or into blob to measure them one by one).\nThe fourth image has one sign and the fifth has three, so the area falls outside the threshold and goes NG."),
    ]
    edges = [
        _edge("src", "seg"), _edge("seg", "area", "mask", "image"),
        _edge("area", "ok", "ok", "_flow"), _edge("area", "ng", "ng", "_flow"),
        _edge("area", "out", "count", "value"), _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def conveyor_pick_flow(source_id: Any) -> dict[str, Any]:
    """輸送帶取料：實例分割 → 邊界排除 → 平台追蹤確認 → 每個新確認物件輸出一行位置。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("seg", "ai_segment", 1, 0, "Segment parts (AI)", model_size="n", conf=0.25, min_count=0, imgsz=640, tracker="none"),
        _node("edge", "edge_filter", 2, 0, "Inside frame", margin_top=50, margin_bottom=50, margin_left=0, margin_right=0),
        _node("trk", "track_objects", 3, 0, "Confirm tracks", state_name="conveyor_pick", confirm_frames=2, motion="linear", max_distance=80, max_missing=1),
        _node("fmt", "format_text", 4, 0, "Robot line", template="{judge}", name="robot_line",
              each_template="{index},{centroid[0]:.2f},{centroid[1]:.2f},0.00", join="\\n"),
        _node("tcp", "write_modbus", 5, 0, "Send to robot", connection="robot", mapping=[{"src": "robot_line", "address": "text", "dtype": "string"}], on_error="warn"),
        _node("draw", "draw_result", 4, 1, "Result image"),
        _note("n1", 0, 1, "About", "Objects touching the top or bottom margin are ignored until they are fully inside the camera view.\nOnly the frame where a track first becomes confirmed is formatted for the robot connection; later frames of the same object are not sent again."),
    ]
    edges = [
        _edge("src", "seg"),
        _edge("seg", "edge", "matches", "matches"), _edge("src", "edge", "image", "image"),
        _edge("edge", "trk", "matches", "matches"),
        _edge("trk", "fmt", "new_confirmed", "items"),
        _edge("fmt", "tcp", "text", "values"),
        _edge("src", "draw", "image", "image"),
        _edge("seg", "draw", "_overlays", "overlays"), _edge("edge", "draw", "_overlays", "overlays"), _edge("trk", "draw", "_overlays", "overlays"),
    ]
    return {"nodes": nodes, "edges": edges}


def conveyor_pick_bytetrack_flow(source_id: Any) -> dict[str, Any]:
    """輸送帶取料（ByteTrack）：分割工具自帶 ByteTrack 給每個物件穩定的 track_id → 邊界排除 →
    track_objects 以 tracker 的 id 為準做確認（algorithm=bytetrack）→ 每個新確認物件輸出一行。
    與 conveyor_pick 的差別只在追蹤的來源：這裡由分割模型內建的 tracker 配對，平台只負責確認與去重。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("seg", "ai_segment", 1, 0, "Segment and track (AI)", model_size="n", conf=0.25, min_count=0, imgsz=640, tracker="bytetrack"),
        _node("edge", "edge_filter", 2, 0, "Inside frame", margin_top=50, margin_bottom=50, margin_left=0, margin_right=0),
        _node("trk", "track_objects", 3, 0, "Confirm by tracker ID", state_name="conveyor_pick_bytetrack", algorithm="bytetrack", confirm_frames=2,
              motion="linear", max_distance=80, max_missing=1),
        _node("fmt", "format_text", 4, 0, "Robot line", template="{judge}", name="robot_line",
              each_template="{index},{centroid[0]:.2f},{centroid[1]:.2f},0.00", join="\\n"),
        _node("tcp", "write_modbus", 5, 0, "Send to robot", connection="robot", mapping=[{"src": "robot_line", "address": "text", "dtype": "string"}], on_error="warn"),
        _node("draw", "draw_result", 4, 1, "Result image"),
        _note("n1", 0, 1, "About", "The segmentation tool runs the ByteTrack tracker itself, so every object keeps one tracker ID across frames.\n"
              "track_objects only confirms an ID after it has been seen for the configured number of frames fully inside the margins, "
              "then formats that first confirmed frame for the robot connection."),
    ]
    edges = [
        _edge("src", "seg"),
        _edge("seg", "edge", "matches", "matches"), _edge("src", "edge", "image", "image"),
        _edge("edge", "trk", "matches", "matches"),
        _edge("trk", "fmt", "new_confirmed", "items"),
        _edge("fmt", "tcp", "text", "values"),
        _edge("src", "draw", "image", "image"),
        _edge("seg", "draw", "_overlays", "overlays"), _edge("edge", "draw", "_overlays", "overlays"), _edge("trk", "draw", "_overlays", "overlays"),
    ]
    return {"nodes": nodes, "edges": edges}


def conveyor_pick_stereo_flow(source_id: Any, calibration: str = "") -> dict[str, Any]:
    """輸送帶雙視野取料：分割左圖，追蹤確認後只對新確認物件計算雙視野高度。
    calibration 是 seed 建的示範立體標定（與合成樣本同一組焦距／基線／帶面距離）；沒 seed 就留空給使用者選。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Sample left image", source_id=source_id),
        _node("pair", "stereo_grab", 0, 0, "Stereo grab", left=source_id, right=source_id, max_dt_ms=20),
        _node("seg", "ai_segment", 1, 0, "Segment parts (AI)", model_size="n", conf=0.25, min_count=0, imgsz=640, tracker="none"),
        _node("edge", "edge_filter", 2, 0, "Inside frame", margin_top=50, margin_bottom=50, margin_left=0, margin_right=0),
        _node("trk", "track_objects", 3, 0, "Confirm tracks", state_name="conveyor_pick_stereo", confirm_frames=2, motion="linear", max_distance=80, max_missing=1),
        _node("z", "stereo_depth", 4, 0, "Measure Z", calibration=calibration, num_disparities=128, block_size=5, scale=0.5, min_valid_ratio=0.25),
        _node("fmt", "format_text", 5, 0, "Robot line", template="{judge}", name="robot_line",
              each_template="{index},{centroid[0]:.2f},{centroid[1]:.2f},{z:.2f}", join="\\n"),
        _node("tcp", "write_modbus", 6, 0, "Send to robot", connection="robot", mapping=[{"src": "robot_line", "address": "text", "dtype": "string"}], on_error="warn"),
        _node("draw", "draw_result", 5, 1, "Result image"),
        _note("n1", 0, 1, "About", "The right camera is only used for disparity. Tracking supplies the first-confirmed items and their pixel velocity, so stereo depth only runs on items that will be sent to the robot."),
    ]
    edges = [
        _edge("src", "pair", "image", "image"),
        _edge("pair", "seg", "image", "image"),
        _edge("seg", "edge", "matches", "matches"), _edge("pair", "edge", "image", "image"),
        _edge("edge", "trk", "matches", "matches"),
        _edge("pair", "z", "image", "image"), _edge("pair", "z", "image_right", "image_right"), _edge("pair", "z", "dt_ms", "dt_ms"),
        _edge("trk", "z", "new_confirmed", "matches"),
        _edge("z", "fmt", "matches", "items"),
        _edge("fmt", "tcp", "text", "values"),
        _edge("pair", "draw", "image", "image"),
        _edge("seg", "draw", "_overlays", "overlays"), _edge("edge", "draw", "_overlays", "overlays"), _edge("trk", "draw", "_overlays", "overlays"),
        _edge("z", "draw", "_overlays", "overlays"),
    ]
    return {"nodes": nodes, "edges": edges}


def dl_classify_flow(source_id: Any, model: tuple[str, dict[str, Any]] = ("", {})) -> dict[str, Any]:
    """DL 分類（教導模型）：seed 用內建 MLP 分類器訓練「良品／缺孔」示範模型，dl_classify 判 pass／fail。"""
    asset_id, tool_params = model
    params = {**tool_params, "model": asset_id, "threshold": 0.5, "pass_labels": "ok", "top_k": 2}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("cls", "dl_classify", 1, 0, "Classify: good?", **params),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: missing hole", verdict="ng", label="missing_hole"),
        _node("out", "output", 2, 2, "Output score", name="ok_score"),
        _node("draw", "draw_result", 1, 2, "Result image"),
        _note("n1", 0, 1, "About", "The model \"Example: classifier (good / missing hole)\" is trained by seed_demo on 30 synthetic samples (the built-in MLP, seconds on CPU).\nThat MLP sees the whole downscaled image, which suits classes that differ in overall appearance; for small defects in random positions use semantic segmentation or instance segmentation. For your own part: create a classification project on the Deep learning page, label a few images, press train, and swap this node's model asset for the result."),
    ]
    edges = [
        _edge("src", "cls"), _edge("cls", "ok", "pass", "_flow"), _edge("cls", "ng", "fail", "_flow"),
        _edge("cls", "out", "score", "value"), _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def dl_segment_flow(source_id: Any, model: tuple[str, dict[str, Any]] = ("", {})) -> dict[str, Any]:
    """DL 語意分割（教導模型）：seed 用 patch_segment 訓練「刮痕」示範模型，dl_segment 的刮痕面積超過門檻走 NG。"""
    asset_id, tool_params = model
    params = {**tool_params, "model": asset_id, "target_class": 1, "min_area": 0, "max_area": 300}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("seg", "dl_segment", 1, 0, "Segment: scratch", **params),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: scratch area too large", verdict="ng", label="scratch_area"),
        _node("out", "output", 2, 2, "Output area", name="scratch_area"),
        _node("draw", "draw_result", 1, 2, "Result image"),
        _note("n1", 0, 1, "About", 'The model "Example: segmenter (scratch)" is trained by seed_demo on 10 polygon-labelled synthetic samples: a fully convolutional ONNX running on CPU.\nThe mask output can feed blob to measure each scratch; for your own defects, train a semantic segmentation project on the Deep learning page.'),
    ]
    edges = [
        _edge("src", "seg"), _edge("seg", "ok", "ok", "_flow"), _edge("seg", "ng", "ng", "_flow"),
        _edge("seg", "out", "area", "value"), _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def anomaly_flow(source_id: Any, model: tuple[str, dict[str, Any]] = ("", {})) -> dict[str, Any]:
    """只教良品的異常檢測：dl_anomaly（seed 用 20 張乾淨鋁板建的記憶庫）→ 異常區數 → OK/NG；分數圖給現場調門檻看。"""
    asset_id, params = model
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("anom", "dl_anomaly", 1, 0, "Anomaly (good parts only)", model=asset_id, threshold=params.get("threshold", 0), min_area=params.get("min_area", 30)),
        _node("cmp", "if_number", 2, 0, "No anomaly?", operator="eq", threshold=0),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG: anomaly", verdict="ng", label="anomaly"),
        _node("out_s", "output", 2, 1, "Output max score", name="anomaly_score"),
        _node("out_n", "output", 2, 2, "Output region count", name="anomaly_count"),
        _note("n1", 0, 1, "About", "The model was built from good pictures only — no defect was ever shown to it. Every patch is scored by its distance to the nearest good patch in the memory bank; the threshold comes from the good pictures' own scores.\nOpen the score map output to see where the anomaly is; raise the threshold on the tool if good parts are flagged."),
    ]
    edges = [
        _edge("src", "anom", "image", "image"),
        _edge("anom", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("anom", "out_s", "score", "value"), _edge("anom", "out_n", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def date_code_flow(source_id: Any, font_asset: str = "") -> dict[str, Any]:
    """日期碼讀取與驗證：ocr_read（seed 教的數字字型）→ ocv_verify（預期 ########、逐字信心）→ pass/fail；輸出讀到的字串。

    對齊合成圖「日期碼標籤」：第 4 張有一字被污點蓋住 → 讀錯或信心不足 → NG，紅框標出是第幾個字。"""
    roi = {"shape": "rect", "x": 360, "y": 410, "w": 560, "h": 150}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("ocr", "ocr_read", 2, 0, "Read the date code", roi=roi, model=font_asset, charset="digits", min_confidence=0.6, segmentation="projection"),
        _node("ocv", "ocv_verify", 3, 0, "Eight digits?", expected="########", min_char_confidence=0.6),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG: date code unreadable", verdict="ng", label="date_code"),
        _node("out", "output", 3, 1, "Output date code", name="date_code"),
        _node("out_c", "output", 3, 2, "Output confidence", name="ocr_confidence"),
        _note("n1", 0, 1, "About", "The font was taught by seeding from 24 rendered lines of digits, so the read runs entirely offline: characters are segmented by the gaps between them and classified one by one.\nText verify checks the pattern (eight digits) and the confidence of every character; the fourth picture has a smudge over one digit and takes the NG branch with that digit boxed in red."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "ocr", "image", "image"),
        _edge("ocr", "ocv", "text", "text"), _edge("ocr", "ocv", "items", "items"), _edge("gray", "ocv", "image", "image"),
        _edge("ocv", "ok", "pass", "_flow"), _edge("ocv", "ng", "fail", "_flow"),
        _edge("ocr", "out", "text", "value"), _edge("ocr", "out_c", "confidence", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def register_count_flow(source_id: Any) -> dict[str, Any]:
    """三個註冊零件才合格；直接由樣本圖裁切參考，不建立訓練資產。"""
    reference = _demo_ref("registered square part")
    return {"nodes": [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("detect", "register_detect", 1, 0, "Count registered parts", registrations=[reference] if reference else [], mode="count", min_count=3, max_count_ok=3, min_similarity=0.9),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: wrong part count", verdict="ng", label="part_count"),
    ], "edges": [
        _edge("src", "detect", "image", "image"),
        _edge("detect", "ok", "ok", "_flow"), _edge("detect", "ng", "ng", "_flow"),
    ]}


SCRIPT_MEASURE_CODE = '''def run(ctx):
    items = ctx.inputs.get("a") or []
    if not isinstance(items, list) or not items:
        return {"value": 0, "result": False, "status": "ng", "branch": "fail", "message": "No measured part"}
    largest = max(items, key=lambda b: float(b.get("area", 0)))
    box = largest.get("bbox") or [0, 0, largest.get("w", 0), largest.get("h", 0)]
    w = float(box[2] or 0)
    h = float(box[3] or 0)
    aspect = max(w, h) / max(1.0, min(w, h))
    fill = float(largest.get("area", 0)) / max(1.0, w * h)
    ok = 1.2 <= aspect <= 2.2 and fill >= 0.65
    return {
        "value": aspect,
        "result": ok,
        "status": "ok" if ok else "ng",
        "branch": "pass" if ok else "fail",
        "data": {"aspect": round(aspect, 3), "fill": round(fill, 3)},
        "message": f"aspect={aspect:.2f}, fill={fill:.2f}",
    }
'''


def _demo_flow_id(name: str = "Demo: hole count") -> int:
    """查詢 seed 建立的示範流程 id；若尚未 seed，保留正整數讓範本仍可載入。"""
    try:
        row = Flow.objects.filter(name=name).only("id").first()
        return int(row.id) if row is not None else 1
    except Exception:  # noqa: BLE001 - 匯入文件或尚未初始化 DB 時，範本仍需可序列化。
        return 1


def list_postprocess_flow(source_id: Any) -> dict[str, Any]:
    """散裝零件後處理範例：用清單過濾、排序、挑選、分級與點集合併整理 blob 結果。"""
    left_roi = {"shape": "rect", "x": 0, "y": 0, "w": 280, "h": 400}
    right_roi = {"shape": "rect", "x": 280, "y": 0, "w": 280, "h": 400}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("thr", "threshold", 2, 0, "Bright parts mask", method="fixed", threshold=120),
        _node("blob", "blob", 3, 0, "All part blobs", min_area=250, max_area=30000, sort_by="area"),
        _node("left", "blob", 3, 1, "Left side centres", roi=left_roi, min_area=250, max_area=30000, sort_by="x"),
        _node("right", "blob", 3, 2, "Right side centres", roi=right_roi, min_area=250, max_area=30000, sort_by="x"),
        _node("pts", "points_merge", 4, 2, "Merged centres", unique=True),
        _node("flt", "list_filter", 4, 0, "Reject dust and oversize", field="area", op="between", value="1000", value2="9000"),
        _node("sort", "list_sort", 5, 0, "Scan order", by="xy"),
        _node("pick", "list_pick", 6, 0, "Largest kept part", by="max", field="area"),
        _node("class", "list_classify", 6, 1, "Area class", field="area", classes="small:0,2500\nstandard:2500,6000\nlarge:6000,9000"),
        _node("cmp", "if_number", 7, 0, "6 valid parts?", operator="eq", threshold=6),
        _node("ok", "judge", 8, 0, "OK", verdict="ok"),
        _node("ng", "judge", 8, 1, "NG: count or size", verdict="ng", label="list_postprocess"),
        _node("out", "output", 7, 1, "Output valid count", name="valid_parts"),
        _note("n1", 0, 1, "About", "The fourth picture has one missing part and one oversize part. The size filter drops the oversize blob, so the valid count falls below six."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "thr"), _edge("thr", "blob"), _edge("thr", "left"), _edge("thr", "right"),
        _edge("left", "pts", "centers", "a"), _edge("right", "pts", "centers", "b"), _edge("src", "pts", "image", "image"),
        _edge("blob", "flt", "blobs", "matches"), _edge("src", "flt", "image", "image"),
        _edge("flt", "sort", "matches", "matches"), _edge("sort", "pick", "matches", "matches"), _edge("sort", "class", "matches", "matches"),
        _edge("flt", "cmp", "count", "value"), _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("flt", "out", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def boxes_cleanup_flow(source_id: Any, marker_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """重疊定位結果清理範例：合併 template match 結果、過濾尺寸，並檢查是否壓到禁區。"""
    zone_roi = {"shape": "rect", "x": 325, "y": 92, "w": 120, "h": 148}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("ref", "fixed_image", 0, 3, "Marker template", images=[marker_ref] if marker_ref else [], mode="fixed", index=1, role="reference"),
        _node("tm", "template_match", 2, 0, "Find markers", threshold=0.62, max_matches=8, sort_by="score"),
        _node("merge", "boxes_merge", 3, 0, "Merge duplicates", mode="center_distance", threshold=18, same_label_only=False),
        _node("flt", "boxes_filter", 4, 0, "Marker size and score", min_width=34, max_width=64, min_height=28, max_height=54, min_score=0.55),
        _node("zone", "blob", 3, 1, "No-go zone box", roi=zone_roi, polarity="bright", threshold_method="fixed", threshold=70, min_area=10000, max_count=1),
        _node("ov", "boxes_overlap", 5, 0, "No marker in no-go zone", metric="a_area", min_overlap=0.18, mode="none"),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: marker in zone", verdict="ng", label="box_zone"),
        _note("n1", 0, 1, "About", "The grey no-go zone is measured as one box. The marker boxes are compared against it after merge and size filtering."),
    ]
    edges = [
        _edge("src", "gray"), _edge("ref", "tm", "image", "template_image"), _edge("gray", "tm"),
        _edge("tm", "merge", "matches", "matches"), _edge("merge", "flt", "matches", "matches"),
        _edge("gray", "zone", "image", "image"),
        _edge("flt", "ov", "matches", "matches"), _edge("zone", "ov", "blobs", "matches_b"), _edge("src", "ov", "image", "image"),
        _edge("ov", "ok", "ok", "_flow"), _edge("ov", "ng", "ng", "_flow"),
    ]
    return {"nodes": nodes, "edges": edges}


def array_placement_flow(source_id: Any) -> dict[str, Any]:
    """規則陣列放置範例：3x4 元件先抓 blob，再由陣列校正補出缺格位置並判定。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("thr", "threshold", 2, 0, "Component mask", method="fixed", threshold=130),
        _node("blob", "blob", 3, 0, "Component blobs", min_area=900, max_area=4000, sort_by="xy", max_count=20),
        _node("arr", "array_correct", 4, 0, "3 x 4 grid", rows=3, cols=4, tolerance=0.4),
        _node("miss", "count_list", 5, 0, "Missing count"),
        _node("cmp", "if_number", 6, 0, "No missing site?", operator="eq", threshold=0),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG: missing site", verdict="ng", label="array_missing"),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "thr"), _edge("thr", "blob"),
        _edge("blob", "arr", "blobs", "matches"), _edge("src", "arr", "image", "image"),
        _edge("arr", "miss", "missing", "items"), _edge("miss", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
    ]
    return {"nodes": nodes, "edges": edges}


def label_map_count_flow(source_id: Any) -> dict[str, Any]:
    """多色分割計數範例：紅、綠、藍區塊轉成 label map 後用 blob_label 統計。"""
    segments = "red:170,10,80,255,80,255\ngreen:45,85,60,255,60,255\nblue:95,130,60,255,60,255"
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("seg", "color_segment", 1, 0, "Segment red green blue", segments=segments, space="hsv", min_area=1000, smooth=3),
        _node("lbl", "blob_label", 2, 0, "Count coloured blobs", classes="1:red\n2:green\n3:blue", min_area=2000, min_count=3, max_count_ok=3),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG: missing colour", verdict="ng", label="colour_count"),
        _node("out", "output", 2, 1, "Output class count", name="colour_blob_count"),
    ]
    edges = [
        _edge("src", "seg"), _edge("seg", "lbl", "labels", "labels"),
        _edge("lbl", "ok", "ok", "_flow"), _edge("lbl", "ng", "ng", "_flow"),
        _edge("lbl", "out", "count", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def color_sample_classify_flow(source_id: Any, samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """固定色票分類範例：把 ROI 的顏色直方圖和三張固定樣本色票比對。"""
    roi = {"shape": "rect", "x": 124, "y": 74, "w": 172, "h": 132}
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("cls", "color_classify", 1, 0, "Classify colour sample", samples=samples or [], roi=roi, space="hsv", bins=32, min_similarity=0.5),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: unknown colour", verdict="ng", label="colour_sample"),
        _node("out", "output", 2, 2, "Output colour label", name="colour_label"),
    ]
    edges = [
        _edge("src", "cls"), _edge("cls", "ok", "ok", "_flow"), _edge("cls", "ng", "ng", "_flow"),
        _edge("cls", "out", "label", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def variable_switch_flow(source_id: Any) -> dict[str, Any]:
    """變數配方切換範例：sandbox 下變數寫入覆蓋層，不會污染實際站台狀態。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("recipe", "variable_get", 1, 0, "Read recipe variable", name="recipe", scope="flow", default="bright"),
        _node("sw", "switch", 2, 0, "Route recipe", cases="bright\ndim", match="exact"),
        _node("bthr", "threshold", 3, 0, "Bright recipe threshold", method="fixed", threshold=170),
        _node("bblob", "blob", 4, 0, "Bright parts", min_area=1200, max_area=6000, min_count=1),
        _node("dthr", "threshold", 3, 1, "Dim recipe threshold", method="fixed", threshold=90),
        _node("dblob", "blob", 4, 1, "Dim parts", min_area=1200, max_area=6000, min_count=1),
        _node("set_b", "variable_set", 5, 0, "Add bright count", name="inspected_count", scope="flow", mode="add"),
        _node("set_d", "variable_set", 5, 1, "Add dim count", name="inspected_count", scope="flow", mode="add"),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: branch failed", verdict="ng", label="recipe_branch"),
        _note("n1", 0, 1, "Sandbox variables", "Sample runs use the variable overlay: variable_set reports the new value for this run but does not keep it in the station store."),
    ]
    edges = [
        _edge("recipe", "sw", "text", "value"),
        _edge("sw", "bthr", "case_1", "_flow"), _edge("sw", "dthr", "case_2", "_flow"),
        _edge("src", "bthr", "image", "image"), _edge("src", "dthr", "image", "image"),
        _edge("bthr", "bblob"), _edge("dthr", "dblob"),
        _edge("bblob", "set_b", "count", "value"), _edge("dblob", "set_d", "count", "value"),
        _edge("bblob", "ok", "found", "_flow"), _edge("dblob", "ok", "found", "_flow"),
        _edge("bblob", "ng", "not_found", "_flow"), _edge("dblob", "ng", "not_found", "_flow"),
    ]
    return {"nodes": nodes, "edges": edges}


def tile_for_each_flow(source_id: Any) -> dict[str, Any]:
    """切片巡檢範例：把影像切成 2x2，逐格呼叫 seed 示範流程，並放一個直接 call_flow 節點。"""
    target = _demo_flow_id()
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("tile", "tile", 1, 0, "2 x 2 tiles", rows=2, cols=2, overlap=0),
        _node("each", "for_each", 2, 0, "Inspect each tile", target_flow_id=target, source="regions", pass_outputs=False, max_items=4),
        _node("call", "call_flow", 2, 1, "Direct call example", target_flow_id=target, prefix="demo_", pass_outputs=False, pass_image=True),
        _node("judge", "judge", 3, 0, "All tiles OK?", verdict="by_input"),
        _note("n1", 0, 1, "Sandbox behaviour", "In sample mode call_flow and for_each return Would call messages, so the wiring is visible without requiring another real production flow."),
    ]
    edges = [
        _edge("src", "tile", "image", "image"),
        _edge("tile", "each", "regions", "regions"), _edge("src", "each", "image", "image"),
        _edge("src", "call", "image", "image"),
        _edge("each", "judge", "all_ok", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def script_measure_flow(source_id: Any) -> dict[str, Any]:
    """自訂 Python 量測範例：blob 後用固定腳本計算最大零件長寬比與填滿率。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("thr", "threshold", 2, 0, "Part mask", method="fixed", threshold=130),
        _node("blob", "blob", 3, 0, "Measured part", min_area=2000, max_area=40000, sort_by="area"),
        _node("script", "python_script", 4, 0, "Aspect script", code=SCRIPT_MEASURE_CODE, max_ms=1000),
        _node("rng", "in_range", 5, 0, "Aspect in range", low=1.2, high=2.2),
        _node("ok", "judge", 6, 0, "OK", verdict="ok"),
        _node("ng", "judge", 6, 1, "NG: custom score", verdict="ng", label="script_measure"),
        _node("out", "output", 5, 1, "Output aspect", name="aspect_ratio"),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "thr"), _edge("thr", "blob"),
        _edge("blob", "script", "blobs", "a"), _edge("src", "script", "image", "image"),
        _edge("script", "rng", "value", "value"),
        _edge("rng", "ok", "inside", "_flow"), _edge("rng", "ng", "outside", "_flow"),
        _edge("script", "out", "value", "value"),
    ]
    return {"nodes": nodes, "edges": edges}


def code_message_rules_flow(source_id: Any) -> dict[str, Any]:
    """條碼訊息規則範例：解碼後拆批號與料號，並用正規表示式驗證批號。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("code", "barcode", 1, 0, "Read QR message", types="qr"),
        _node("parse", "parse_message", 2, 0, "Split lot and part", mode="delimiter", separator="|", fields="lot\npart", publish=True),
        _node("match", "string_match", 3, 0, "Lot format B######", list="^B[0-9]{6}$", match="regex", case_sensitive=True),
        _node("fmt", "format_text", 4, 0, "Reply text", template="lot={a}, text={b}", name="message_reply"),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG: bad lot", verdict="ng", label="message_rule"),
    ]
    edges = [
        _edge("src", "code"), _edge("code", "parse", "first", "text"),
        _edge("parse", "match", "first", "text"),
        _edge("parse", "fmt", "first", "a"), _edge("match", "fmt", "text", "b"),
        _edge("match", "ok", "found", "_flow"), _edge("match", "ng", "not_found", "_flow"),
    ]
    return {"nodes": nodes, "edges": edges}


def io_sequence_flow(source_id: Any) -> dict[str, Any]:
    """設備 I/O 順序範例：相機設定、燈源、影像判定、輸出點、相機線與 Modbus 讀取都可降級。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("camset", "camera_set", 0, 1, "Apply camera settings", source=source_id, values="exposure_us=5000", user_set="none", required=False),
        _node("light", "set_light", 1, 1, "Set ring light", connection="ring-light", channel=1, value=180, required=False),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("thr", "threshold", 2, 0, "Bright signal dots", method="fixed", threshold=140),
        _node("blob", "blob", 3, 0, "Signal dot count", min_area=1200, max_area=4000),
        _node("cmp", "if_number", 4, 0, "3 dots?", operator="eq", threshold=3),
        _node("judge", "judge", 5, 0, "OK / NG", verdict="by_input"),
        _node("io", "io_output", 6, 0, "Reject output", connection="station-io", address="coil:0", on_when="ng", pulse_ms=50, required=False),
        _node("camio", "camera_io", 6, 1, "Camera reject line", source=source_id, line="Line1", on_when="ng", pulse_ms=50, required=False),
        _node("mb", "read_modbus", 6, 2, "Read recipe register", connection="station-plc", mapping=[{"name": "recipe", "address": "holding:0"}], publish=False, on_error="warn"),
        _note("n1", 0, 2, "Degraded I/O", "When these connections are absent, the steps log warnings and continue: camera settings, light, station output, camera output and Modbus read."),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "thr"), _edge("thr", "blob"), _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "judge", "result", "value"),
        _edge("judge", "io", "verdict", "status"), _edge("judge", "camio", "verdict", "status"),
    ]
    return {"nodes": nodes, "edges": edges}


def outputs_bundle_flow(source_id: Any) -> dict[str, Any]:
    """輸出打包範例：把檢測結果格式化、寫 log、保存影像、送圖並觸發下一條流程。"""
    target = _demo_flow_id()
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("thr", "threshold", 2, 0, "Part mask", method="fixed", threshold=130),
        _node("blob", "blob", 3, 0, "Part blobs", min_area=1200, max_area=5000),
        _node("cmp", "if_number", 4, 0, "3 parts?", operator="eq", threshold=3),
        _node("judge", "judge", 5, 0, "OK / NG", verdict="by_input"),
        _node("fmt", "format_text", 6, 0, "Bundle line", template="{a},{b}", name="bundle_text"),
        _node("log", "write_log", 7, 0, "CSV log", path="examples", format="csv", fields="bundle_text\njudge\nrun_id", filename="outputs_bundle_{date}", daily_folder=False),
        _node("save", "save_image", 7, 1, "Save rejects", folder="", format="png", condition="ng", split_by_judge=True, filename="{run_id:.8}"),
        _node("send", "send_image", 7, 2, "Send result image", connection="image-host", encoding="png", include_values=True, on_error="warn"),
        _node("trig", "trigger_flow", 7, 3, "Trigger audit flow", target_flow_id=target, mode="async", pass_outputs=True, pass_image=False),
    ]
    edges = [
        _edge("src", "gray"), _edge("gray", "thr"), _edge("thr", "blob"), _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "judge", "result", "value"),
        _edge("judge", "fmt", "verdict", "a"), _edge("blob", "fmt", "count", "b"),
        _edge("fmt", "log", "text", "a"),
        _edge("src", "save", "image", "image"), _edge("judge", "save", "verdict", "param:prefix"),
        _edge("src", "send", "image", "image"), _edge("judge", "send", "verdict", "param:name"),
    ]
    return {"nodes": nodes, "edges": edges}


def _demo_model(name: str) -> tuple[str, dict[str, Any]]:
    """seed 訓練的示範模型資產：(asset id, 建議的工具參數)；還沒 seed 就回空（範本照樣能載入）。"""
    row = Asset.objects.filter(name=name, kind="model").only("id", "meta").first()
    if not row:
        return "", {}
    return str(row.id), dict((row.meta or {}).get("tool_params") or {})


#: 示範立體標定資產名稱：合成樣本 demo_images.conveyor_stereo_sequence() 用的 f=1200、基線 60 mm、480×360、帶面 800 mm
STEREO_CALIB_NAME = "Example: stereo calibration (conveyor)"


def _demo_asset(name: str, kind: str = "image") -> str:
    """seed 建立的範例資產 id；還沒 seed 就回空字串（範本照樣能載入，資產欄留給使用者填）。"""
    row = Asset.objects.filter(name=name, kind=kind).only("id").first()
    return str(row.id) if row else ""


#: 範本的參考圖（以前是 5 個影像資產）：名稱 → (樣本集 key, 裁切區域, 產生器名)；由 _demo_ref 現算並存進固定影像庫（內容雜湊，重跑不重複）。
REF_SPECS: dict[str, tuple[str, dict[str, Any] | None, str]] = {
    "registered square part": ("registered_parts", {"shape": "rect", "x": 64, "y": 48, "w": 96, "h": 96}, ""),
    "cleanup marker template": ("cleanup_boxes", {"shape": "rect", "x": 66, "y": 70, "w": 52, "h": 44}, ""),
    "cross locator template": ("marker_plate", {"shape": "rect", "x": 200, "y": 160, "w": 120, "h": 120}, ""),
    "cup locator template": ("cup", {"shape": "rect", "x": 150, "y": 120, "w": 100, "h": 100}, ""),
    "print golden template": ("golden_print", None, ""),
    "stamped part outline": ("stamped_part", None, ""),
    "white reference (uneven lighting)": ("vignette", None, "vignette_flat"),
}
_FIXED_CACHE: dict[str, Any] = {}


def _cached_present(value: Any) -> bool:
    """快取的描述子指到的檔案都還在才算數（資產目錄換了、或孤兒清理刪掉了就重生）。"""
    from apps.vision import fixed_images

    descs = value if isinstance(value, list) else [value]
    return all(isinstance(d, dict) and fixed_images.exists(str(d.get("id") or "")) for d in descs)


def _demo_ref(name: str) -> dict[str, Any] | None:
    """範本參考圖的固定影像描述子（從樣本圖第 1 張裁一塊，或用產生器的圖）；算不出來回 None（範本照樣能載入，圖留給使用者上傳）。"""
    key = f"ref:{name}"
    if key in _FIXED_CACHE and _cached_present(_FIXED_CACHE[key]):
        return _FIXED_CACHE[key]
    spec = REF_SPECS.get(name)
    if spec is None:
        return None
    try:
        import os

        import cv2
        import numpy as np

        from apps.vision import demo_images, fixed_images
        from apps.vision.tools.roi import crop as roi_crop

        set_key, region, maker = spec
        if maker:
            image = getattr(demo_images, maker)()
        else:
            folder = demo_images.write_set(set_key)
            first = sorted(n for n in os.listdir(folder) if n.endswith(".png"))[0]
            image = cv2.imdecode(np.fromfile(os.path.join(folder, first), dtype=np.uint8), cv2.IMREAD_COLOR)
        piece = roi_crop(image, region, upright=True).image if region else image
        desc = fixed_images.store(np.ascontiguousarray(piece), f"Example {name}.png")
    except Exception:  # noqa: BLE001 - 範本目錄不能因為樣本圖產不出來而炸
        log.warning("範本參考圖 %s 產生失敗", name, exc_info=True)
        return None
    _FIXED_CACHE[key] = desc
    return desc


def _color_sample_refs() -> list[dict[str, Any]]:
    """建立 color_classify 範本使用的三張固定色票。"""
    key = "refs:colour_samples"
    if key in _FIXED_CACHE and _cached_present(_FIXED_CACHE[key]):
        return [dict(d) for d in _FIXED_CACHE[key]]
    try:
        from apps.vision import fixed_images

        specs = [("red sample", (45, 45, 218)), ("green sample", (62, 178, 62)), ("blue sample", (210, 92, 45))]
        out = []
        for name, colour in specs:
            image = np.full((96, 96, 3), colour, dtype=np.uint8)
            out.append(fixed_images.store(np.ascontiguousarray(image), f"Example {name}.png"))
    except Exception:  # noqa: BLE001 - 色票只是範例參考圖，失敗時範本仍可載入。
        log.warning("建立範例色票失敗", exc_info=True)
        return []
    _FIXED_CACHE[key] = out
    return [dict(d) for d in out]


def template_samples(key: str) -> list[dict[str, Any]]:
    """內建範本的樣本圖（固定影像描述子清單，依檔名排序；第 4 張多半刻意 NG）；沒有樣本集的範本回空清單。"""
    set_key = TEMPLATE_SAMPLE_SETS.get(key)
    return sample_pictures(set_key) if set_key else []


def sample_pictures(set_key: str) -> list[dict[str, Any]]:
    """一個合成樣本集（demo_images.SAMPLE_SETS 的鍵）的固定影像描述子；產不出來回空清單。"""
    cache_key = f"set:{set_key}"
    if cache_key in _FIXED_CACHE and _cached_present(_FIXED_CACHE[cache_key]):
        return [dict(d) for d in _FIXED_CACHE[cache_key]]
    try:
        import os

        from apps.vision import demo_images, fixed_images

        folder = demo_images.write_set(set_key)
        out = []
        for f in sorted(n for n in os.listdir(folder) if n.endswith(".png")):
            with open(os.path.join(folder, f), "rb") as fh:
                out.append(fixed_images.store_bytes(fh.read(), f"{demo_images.SAMPLE_SETS[set_key][0]} {f}"))
    except Exception:  # noqa: BLE001
        log.warning("範本樣本圖 %s 產生失敗", set_key, exc_info=True)
        return []
    _FIXED_CACHE[cache_key] = out
    return [dict(d) for d in out]


def builtin_fixed_ids() -> set[str]:
    """內建範本會用到的所有固定影像 id（樣本集＋參考圖），purge 清孤兒時要保留。"""
    out: set[str] = set()
    for key in TEMPLATE_SAMPLE_SETS:
        out |= {d["id"] for d in template_samples(key)}
    for name in REF_SPECS:
        d = _demo_ref(name)
        if d:
            out.add(d["id"])
    out |= {d["id"] for d in _color_sample_refs()}
    return out


#: 範本畫廊的內建範本目錄：(key, 名稱, 說明, 分類, builder)。
#: builder 在 request 時才呼叫（範例資產 id 由 _demo_asset 現查，seed 過就開箱即用）。
BUILTIN_TEMPLATES: tuple[tuple[str, str, str, str, Any], ...] = (
    ("register_count", "Count parts by registration", "Register one cropped part and accept exactly three matches, without training. Requires the deep learning pack.", "count", register_count_flow),
    ("hole_count", "Hole count", "Grayscale, denoise, threshold, morphology, blob count, number check, OK/NG — with a named output and a result image", "count", hole_count_flow),
    ("exposure", "Exposure check", "Downscale, Otsu threshold, range check, OK/NG", "quality", brightness_gate_flow),
    ("circle_gauge", "Circle gauge", "Find circle, diameter, pixel calibration to mm, tolerance judge — plus a sector ROI arc fit and ellipse roundness", "measure", circle_gauge_flow),
    ("edge_angle", "Edge angle", "Two line finds into an angle tolerance, the intersection point, and a 45 degree chamfer measurement", "measure", edge_angle_flow),
    ("golden_compare", "Print compare", "Difference against a golden sample to catch overprinting, smudges and gaps; the golden picture comes with the template as a fixed image", "quality",
     lambda sid: golden_compare_flow(sid, _demo_ref("print golden template"))),
    ("stat_compare", "Statistical print compare", "Per-pixel mean and spread from 30 good prints; anything beyond 4 standard deviations is a defect, so light and texture variation no longer force a loose threshold", "quality",
     lambda sid: stat_compare_flow(sid, _demo_asset("Example: statistical template (print)", "file"))),
    ("fft_defect", "Fabric defect", "A frequency-domain low pass removes the periodic weave and what is left is the scratch; a mask pulls out the defect area", "quality", fft_defect_flow),
    ("surface_scratch", "Surface scratch (filter)", "A brushed surface has no repeating pattern for a frequency filter to remove; the surface defect filter averages along the mark and differentiates across it instead", "quality", surface_scratch_flow),
    ("preprocess_lab", "Pre-processing and measurement lab", "An image chain of bit depth, look-up table, filtering and flipping, plus a tour of line profile, statistics, histogram and edge density", "tutorial", preprocess_lab_flow),
    ("list_postprocess", "Blob results sorted and picked", "Blob results filtered by area, sorted in scan order, picked by maximum area, classified by size and merged as point sets", "count", list_postprocess_flow),
    ("array_placement", "Component array with a missing site", "Blob centres corrected into a 3 x 4 grid so the missing site can be reported and judged", "count", array_placement_flow),
    ("geometry_count", "Circles and lines", "Hough circles counted, Hough lines counted as a list, and two circle finds giving a centre distance", "count", geometry_count_flow),
    ("gear_teeth", "Gear tooth count (polar unwrap)", "Polar unwrap flattens the tooth ring into a strip, threshold and blob count the teeth, and Polar restore marks each tooth on the original picture", "count", gear_teeth_flow),
    ("contour_defect", "Chipped edge (contour geometry)", "Contour find, filter to the part, contour geometry counting convexity defects deeper than 12 px, OK/NG — plus a Hu-moment contour match against the sample outline", "quality",
     lambda sid: contour_defect_flow(sid, _demo_ref("stamped part outline"))),
    ("edge_defect_demo", "Chipped rim (edge defects)", "One step lays 180 calipers round the rim the part actually has, finds every stretch that strays and says what kind of fault it is, with a box round each", "measure", edge_defect_flow),
    ("circular_defect", "Chipped rim (circular caliper)", "A ring of 180 radial calipers gives the radius at every angle and the run-out; Profile defects fits a circle and marks every dip or empty caliper as a chip, drawn as a red arc on the rim", "measure", circular_defect_flow),
    ("form_tolerance", "Roundness (form tolerance)", "180 radial calipers give the edge points; Form and position tolerance fits the minimum-zone circle (ISO 1101) and passes the disc when the ring between the two concentric circles is within 5 px — the chipped rim fails", "measure", form_tolerance_flow),
    ("emboss_defect", "Embossed characters and dents (photometric stereo)", "Four crops split a 2×2 picture of the plate under four lights; Photometric stereo turns them into a shape-strength map on which a pixel count in the check zone finds the dent that no single picture shows", "quality", emboss_defect_flow),
    ("barcode_grade", "Barcode quality grade (ISO 15415)", "Grades the Data Matrix on the label like a verifier — contrast, modulation, fixed pattern damage, axial and grid non-uniformity, unused error correction — and passes it at C or better; the dirty symbol fails", "detect", barcode_grade_flow),
    ("exclusion_zone", "Exclusion zones (combined region)", "Two drawn regions cut out of the plate rectangle by Region combine, feeding the statistics and blob steps through their region inputs — the hole pixels never count", "measure", exclusion_zone_flow),
    ("shading", "Flat-field correction (uneven lighting)", "Divide by a white-reference asset so one fixed threshold finds the dark spots in the corners too; a side branch shows the same threshold failing on the uncorrected picture", "quality",
     lambda sid: shading_flow(sid, _demo_ref("white reference (uneven lighting)"))),
    ("boxes_cleanup", "Overlapping matches merged and kept out of a zone", "Template matches are merged, filtered by box size and score, then checked against a no-go-zone box for overlap", "quality",
     lambda sid: boxes_cleanup_flow(sid, _demo_ref("cleanup marker template"))),
    ("script_measure", "Custom Python measurement", "Blob measurements feed an approved Python script that calculates aspect ratio and a fill score before judging the range", "quality", script_measure_flow),
    ("color_presence", "Colour presence", "A colour range mask into a pixel count, judged against a threshold", "detect", color_presence_flow),
    ("color_verify", "Colour verification", "The region's mean colour against a target by distance, with colour statistics reporting a hex code", "detect", color_verify_flow),
    ("label_map_count", "Multi-colour segmentation to counts", "Three HSV colour ranges become a label map, then label-map blobs count the red, green and blue regions", "detect", label_map_count_flow),
    ("color_sample_classify", "Classify by sample colours", "The part colour is compared with fixed red, green and blue sample images and rejected when no sample is close enough", "detect",
     lambda sid: color_sample_classify_flow(sid, _color_sample_refs())),
    ("barcode_read", "Barcode / QR read", "Read the code, check whether anything was read, output it", "identify", barcode_flow),
    ("code_message_rules", "Decode, parse and match", "Read a QR payload, split lot and part fields, match the lot with a regular expression and format a reply", "identify", code_message_rules_flow),
    ("guided_code_read", "Locate then read code", "Find the likely code area, move a crop ROI to it, enlarge that crop, then decode. The stock detector size only demonstrates the wiring; train a detector for your own code location before production use.", "identify", guided_code_read_flow),
    ("date_code", "Date code read and verify (taught font)", "Text read with a font taught by seeding — segmentation plus per-character classification, fully offline — into Text verify against an eight-digit pattern with per-character confidence; a smudged digit is boxed in red", "identify",
     lambda sid: date_code_flow(sid, _demo_asset("Example: taught font (digits)", "model"))),
    ("label_read", "Barcode label with perspective correction", "Four-point perspective correction straightens the tilted label before reading it, plus a text-presence check on the serial area", "identify", label_flow),
    ("shape_locate", "Shape match locate (any angle, any light)", "Edge-direction shape matching finds the part turned, darkened or among clutter, feeds Locate offset and ROI follow, and rejects a different part", "measure",
     lambda sid: shape_match_flow(sid, _demo_asset("Example: shape model (bracket)", "file"))),
    ("locate_measure", "Locate and gauge", "Template match, locate correction, ROI follow, caliper width, tolerance judge", "measure",
     lambda sid: locate_measure_flow(sid, _demo_ref("cross locator template"))),
    ("cup_measure", "Deep-drawn cup gauge", "Template match, locate correction, three ROIs following, outer and inner circle finds plus wall thickness, concentricity, three tolerance judges, named outputs, OK/NG", "measure",
     lambda sid: cup_measure_flow(sid, _demo_ref("cup locator template"))),
    ("ai_count", "AI object count (stock model)", "ai_detect finds stop signs with the COCO stock model and judges the count. No training needed and the GPU is used automatically (deep-learning dependencies required)", "count", yolo_count_flow),
    ("ai_area", "AI instance segmentation: sign area", "ai_segment's union mask into a pixel count and an area threshold, showing segmentation feeding a measurement (deep-learning dependencies required)", "detect", yolo_area_flow),
    ("conveyor_pick", "Conveyor pick (single camera)", "Instance segmentation into edge filtering, stable platform tracking, first-confirmed item formatting and a degraded robot text output (deep-learning dependencies required)", "automation", conveyor_pick_flow),
    ("conveyor_pick_bytetrack", "Conveyor pick (ByteTrack)", "Instance segmentation with the built-in ByteTrack tracker, edge filtering, confirmation by tracker ID, first-confirmed item formatting and a degraded robot text output (deep-learning dependencies required)", "automation", conveyor_pick_bytetrack_flow),
    ("conveyor_pick_stereo", "Conveyor pick (stereo Z)", "Stereo grab, instance segmentation, edge filtering, tracking, stereo depth on first-confirmed items and robot text output (deep-learning dependencies required)", "automation",
     lambda sid: conveyor_pick_stereo_flow(sid, _demo_asset(STEREO_CALIB_NAME, "calibration"))),
    ("variable_switch", "Recipe switch by variable", "Read a recipe variable, switch between two threshold branches and store a running inspected count through the sandbox variable overlay", "automation", variable_switch_flow),
    ("tile_for_each", "Tile the image and inspect each tile", "Split the image into a 2 x 2 grid, run a child flow for each tile in sandbox mode, and show a direct flow call", "automation", tile_for_each_flow),
    ("io_sequence", "Light, camera IO and device signals", "Apply camera settings, set a light, inspect the image, pulse station and camera outputs, and read Modbus with degraded missing connections", "automation", io_sequence_flow),
    ("outputs_bundle", "Log, save, send and trigger", "Format the result, write a CSV log, save reject images, send a result image and trigger an audit flow; sandbox mode reports Would actions", "automation", outputs_bundle_flow),
    ("dl_classify_demo", "Classification: good / missing hole (taught model)", "The built-in MLP classifier trained by seeding, into dl_classify pass/fail — how a taught model gets into a flow", "quality",
     lambda sid: dl_classify_flow(sid, _demo_model("Example: classifier (good / missing hole)"))),
    ("anomaly_demo", "Anomaly detection: good parts only (taught model)", "The anomaly model built by seeding from 20 clean plates scores every patch against the good memory bank; scratches it has never seen come out as anomalies (needs the anomaly backbone)", "quality",
     lambda sid: anomaly_flow(sid, _demo_model("Example: anomaly (scratch plate)"))),
    ("dl_segment_demo", "Semantic segmentation: scratch area (taught model)", "The patch_segment model trained by seeding, into a dl_segment scratch-area threshold and OK/NG", "quality",
     lambda sid: dl_segment_flow(sid, _demo_model("Example: segmenter (scratch)"))),
)

#: builtin 範本 key → 對應的樣本集名稱（`Example: <demo_images.SAMPLE_SETS 的標籤>`）。
#: **每個內建範本都要有一組**：範本畫廊預設把取像節點換成帶著這些圖的固定影像，載入即可試執行。
TEMPLATE_SAMPLE_SOURCES: dict[str, str] = {
    "register_count": "Example: registered parts",
    "hole_count": "Example: plate holes",
    "exposure": "Example: exposure",
    "circle_gauge": "Example: circle gauge",
    "edge_angle": "Example: edge angle",
    "golden_compare": "Example: print compare",
    "fft_defect": "Example: fabric defect",
    "surface_scratch": "Example: brushed surface",
    "stat_compare": "Example: print compare",
    "preprocess_lab": "Example: preprocessing lab",
    "list_postprocess": "Example: list postprocess parts",
    "array_placement": "Example: component array",
    "geometry_count": "Example: circles and lines",
    "gear_teeth": "Example: gear teeth",
    "contour_defect": "Example: stamped part",
    "exclusion_zone": "Example: circle gauge",
    "circular_defect": "Example: chipped disc",
    "edge_defect_demo": "Example: chipped disc",
    "form_tolerance": "Example: chipped disc",
    "emboss_defect": "Example: embossed plate (four lights)",
    "barcode_grade": "Example: barcode grading",
    "shading": "Example: uneven lighting",
    "boxes_cleanup": "Example: box cleanup",
    "script_measure": "Example: script rectangles",
    "color_presence": "Example: colour blocks",
    "color_verify": "Example: colour blocks",
    "label_map_count": "Example: label map colours",
    "color_sample_classify": "Example: sample colour cards",
    "barcode_read": "Example: barcode label",
    "code_message_rules": "Example: coded messages",
    "guided_code_read": "Example: small code in clutter",
    "label_read": "Example: barcode label",
    "date_code": "Example: date code label",
    "locate_measure": "Example: locate and gauge",
    "shape_locate": "Example: shape match",
    "cup_measure": "Example: cup gauge",
    "ai_count": "Example: stop sign",
    "ai_area": "Example: stop sign",
    "conveyor_pick": "Example: conveyor sequence",
    "conveyor_pick_bytetrack": "Example: conveyor sequence",
    "conveyor_pick_stereo": "Example: conveyor stereo sequence",
    "variable_switch": "Example: variable recipe parts",
    "tile_for_each": "Example: tiled panels",
    "io_sequence": "Example: io signal parts",
    "outputs_bundle": "Example: output bundle parts",
    "dl_classify_demo": "Example: classification teaching",
    "dl_segment_demo": "Example: segmentation teaching",
    "anomaly_demo": "Example: segmentation teaching",
}

def _sample_sets() -> dict[str, str]:
    """範本 key → 樣本集 key（demo_images.SAMPLE_SETS）；每個內建範本都要有一組（test_demo 鎖住）。"""
    from apps.vision import demo_images

    labels = {f"Example: {label}": set_key for set_key, (label, _fn) in demo_images.SAMPLE_SETS.items()}
    return {key: labels[name] for key, name in TEMPLATE_SAMPLE_SOURCES.items() if name in labels}


TEMPLATE_SAMPLE_SETS: dict[str, str] = _sample_sets()
#: 需要 DL 依賴（ultralytics／torch）才能執行的範本 key；測試與文件用。
TEMPLATES_NEED_DL = ("ai_count", "ai_area", "guided_code_read", "conveyor_pick", "conveyor_pick_bytetrack", "conveyor_pick_stereo")
#: 需要平台附帶的異常檢測 backbone（ASSET_DIR/dl/weights/resnet18_l2l3.onnx）才能執行的範本 key。
TEMPLATES_NEED_BACKBONE = ("anomaly_demo", "register_count")


def _seed_demo_models(created: list[str]) -> None:
    """用內建 CPU trainer 訓練兩個示範模型資產（分類：良品／缺孔、分割：刮痕），給 DL 範本開箱即用；已存在就沿用。"""
    import os
    import shutil
    import tempfile
    import uuid as _uuid

    import cv2
    from django.conf import settings

    from apps.vision import demo_images
    from apps.vision.dl import base as dl_base
    from apps.vision.dl.base import SampleRef

    dl_base.register_builtins()
    specs = [
        ("Example: classifier (good / missing hole)", "mlp_classify", demo_images.dl_parts_labeled, ["ok", "ng"], {"input_size": 64, "epochs": 300, "val_split": 0.2, "augment": True}),
        ("Example: segmenter (scratch)", "patch_segment", demo_images.dl_scratch_labeled, ["scratch"], {"input_size": 128, "epochs": 200, "samples_per_image": 2000}),
    ]
    from apps.vision.dl import anomaly as _anomaly

    if _anomaly.backbone_available():
        # 只教良品的異常檢測：需要平台附帶的 backbone（開發機 manage.py anomaly_backbone --export；現場由 DL 加購包附帶）
        specs.append(("Example: anomaly (scratch plate)", "anomaly", demo_images.dl_clean_plates, ["good"], {"input_size": 320, "coreset_ratio": 0.1}))
    for name, kind, maker, classes, params in specs:
        if Asset.objects.filter(name=name, kind="model").exists():
            continue
        tmp = tempfile.mkdtemp(prefix="vs-demo-dl-")
        try:
            refs: list[SampleRef] = []
            for i, (image, label) in enumerate(maker()):
                path = os.path.join(tmp, f"s{i:02d}.png")
                ok, buf = cv2.imencode(".png", image)
                buf.tofile(path)
                if isinstance(label, list):
                    refs.append(SampleRef(id=f"s{i}", label="", path=path, shapes=label))
                else:
                    refs.append(SampleRef(id=f"s{i}", label=str(label), path=path))
            result = dl_base.get_trainer(kind).train(refs, classes, params, "cpu", lambda f, s, m: None)
            if result.weights_bytes and result.weights_tool_key:
                # 主產物是原生權重（異常檢測的記憶庫 npz）：與 jobs._train 同樣存成 model 資產
                weights_id = _uuid.uuid4()
                wpath = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{weights_id.hex}{result.weights_ext}")
                with open(wpath, "wb") as fh:
                    fh.write(result.weights_bytes)
                Asset.objects.create(
                    id=weights_id, name=name, kind="model", group="Examples", path=wpath, size=len(result.weights_bytes),
                    meta={"trainer": kind, "project": "Examples", "tool_key": result.weights_tool_key, "tool_params": result.weights_tool_params, "metrics": result.metrics, "format": result.weights_ext.lstrip(".")},
                )
                created.append(f"模型資產 {name}（新建，{kind}）")
                continue
            asset_id = _uuid.uuid4()
            path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.onnx")
            with open(path, "wb") as f:
                f.write(result.onnx_bytes)
            Asset.objects.create(
                id=asset_id, name=name, kind="model", group="Examples", path=path, size=len(result.onnx_bytes),
                meta={"trainer": kind, "project": "Examples", "tool_key": result.tool_key, "tool_params": result.tool_params, "metrics": result.metrics, "format": "onnx"},
            )
            created.append(f"模型資產 {name}（新建，{kind}）")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

#: 舊版 seed 建過、現改由範本畫廊提供的流程名稱（seed 時清掉，避免流程清單被塞滿）。
#: 舊版 seed 建過的範例流程名稱（改由範本畫廊提供後要清掉）。舊安裝是中文名，必須原樣保留才刪得掉。
_GALLERY_FLOW_NAMES = (
    "範例：圓孔尺寸量測", "範例：邊線夾角", "範例：印刷良品比對", "範例：織紋瑕疵檢測",
    "範例：前處理與量測教學", "範例：多圓幾何計數", "範例：顏色有無檢測", "範例：顏色比對",
    "範例：條碼標籤讀取", "範例：定位量測", "範例：杯件量測",
)


#: 舊安裝（中文示範資料）→ 現在的英文名稱；seed 前先改名，避免同一份資料出現兩筆。
_LEGACY_RENAMES: dict[str, str] = {
    "示範：合成零件": "Demo: synthetic parts",
    "範例：圓孔量測": "Example: circle gauge",
    "範例：邊線夾角": "Example: edge angle",
    "範例：印刷良品比對": "Example: print compare",
    "範例：織紋瑕疵": "Example: fabric defect",
    "範例：前處理教學圖": "Example: preprocessing lab",
    "範例：多圓幾何": "Example: circles and lines",
    "範例：顏色檢驗": "Example: colour blocks",
    "範例：條碼標籤": "Example: barcode label",
    "範例：杯件量測": "Example: cup gauge",
    "範例：定位量測": "Example: locate and gauge",
    "範例：停止標誌": "Example: stop sign",
    "範例：分類教導": "Example: classification teaching",
    "範例：分割教導": "Example: segmentation teaching",
    "範例：定位十字範本": "Example: cross locator template",
    "範例：杯件定位範本": "Example: cup locator template",
    "範例：印刷良品範本": "Example: print golden template",
    "範例：分類模型（良品／缺孔）": "Example: classifier (good / missing hole)",
    "範例：分割模型（刮痕）": "Example: segmenter (scratch)",
    "示範：零件孔數檢測": "Demo: hole count",
    "示範：曝光檢查": "Demo: exposure check",
}


def _drop_legacy_examples(created: list[str]) -> None:
    """舊版 seed 建的範例資料夾來源（每個樣本集一個）與 5 個參考影像資產：沒有任何流程引用的就刪掉，讓來源庫與資產庫只剩使用者自己的東西。"""
    import json as _json

    graphs = " ".join(_json.dumps(g) for g in Flow.objects.values_list("graph", flat=True))
    from apps.vision import demo_images

    names = [f"Example: {label}" for label, _fn in demo_images.SAMPLE_SETS.values()]
    for src in ImageSource.objects.filter(kind="folder", group="Examples", name__in=names):
        if f'"source_id": {src.id}' in graphs or f'"source_id": "{src.id}"' in graphs:
            continue
        src.delete()
        created.append(f"移除舊範例來源 {src.name}")
    for asset in Asset.objects.filter(kind="image", group="Examples", name__in=[f"Example: {n}" for n in REF_SPECS]):
        if str(asset.id) in graphs:
            continue
        try:
            import os

            if asset.path and os.path.isfile(asset.path):
                os.remove(asset.path)
        except OSError:
            pass
        asset.delete()
        created.append(f"移除舊範例資產 {asset.name}")


def _rename_legacy(created: list[str]) -> None:
    """把舊安裝的中文示範資料改成英文名（同名已存在就不動，交給後續 get_or_create）。"""
    for model, kinds in ((ImageSource, None), (Asset, ("image", "model")), (Flow, None)):
        qs = model.objects.filter(name__in=_LEGACY_RENAMES)
        if kinds is not None:
            qs = qs.filter(kind__in=kinds)
        for row in qs:
            new_name = _LEGACY_RENAMES[row.name]
            if model.objects.filter(name=new_name).exists():
                continue
            old_name = row.name
            row.name = new_name
            row.save(update_fields=["name"])
            created.append(f"更名 {old_name} → {new_name}")
    ResourceGroup.objects.filter(name="範例").update(name="Examples")
    for model in (ImageSource, Asset):
        model.objects.filter(group="範例").update(group="Examples")


def seed_demo() -> list[str]:
    from apps.vision import demo_images

    created: list[str] = []
    _rename_legacy(created)
    for kind in ("source", "asset"):
        ResourceGroup.objects.get_or_create(kind=kind, name="Examples")
    from apps.vision import scripts as _scripts

    _scripts.approve(SCRIPT_MEASURE_CODE)

    source, made = ImageSource.objects.get_or_create(
        name="Demo: synthetic parts",
        defaults={"kind": "synthetic", "group": "Examples", "config": {"width": 1280, "height": 960, "pattern": "parts", "seed": 7, "defect_rate": 0.3}},
    )
    if not made and not source.group:
        source.group = "Examples"
        source.save(update_fields=["group"])
    created.append(f"影像來源 {source.name}（{'新建' if made else '既有'}）")

    # 樣本圖與參考圖是固定影像（跟著範本走），不再佔影像來源庫與資產庫
    n_samples = sum(len(template_samples(key)) for key in TEMPLATE_SAMPLE_SETS)
    n_refs = sum(1 for name in REF_SPECS if _demo_ref(name))
    created.append(f"固定影像：樣本圖 {n_samples} 張、參考圖 {n_refs} 張")
    _drop_legacy_examples(created)
    if not Asset.objects.filter(name=STEREO_CALIB_NAME, kind="calibration").exists():
        import os
        import uuid as _uuid

        from django.conf import settings

        from apps.vision import calib

        # 與 demo_images.conveyor_stereo_sequence() 同一組參數：右相機在 +x 方向 60 mm，帶面 800 mm 當 Z=0
        f, baseline, size = 1200.0, 60.0, (480, 360)
        m = [[f, 0.0, size[0] / 2], [0.0, f, size[1] / 2], [0.0, 0.0, 1.0]]
        payload = calib.validate({
            "unit": "mm", "image_size": list(size), "note": "Synthetic stereo pair used by the conveyor pick (stereo Z) template samples",
            "stereo": {"M1": m, "D1": [0.0] * 5, "M2": m, "D2": [0.0] * 5, "R": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                       "T": [-baseline, 0.0, 0.0], "image_size": list(size), "baseline_mm": baseline,
                       "z_ref": {"d0_mm": 800.0, "Z0_mm": 0.0, "scale": 1.0}},
        })
        calib_id = _uuid.uuid4()
        calib_path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{calib_id.hex}.json")
        calib.save(calib_path, payload)
        Asset.objects.create(
            id=calib_id, name=STEREO_CALIB_NAME, kind="calibration", group="Examples", path=calib_path, size=os.path.getsize(calib_path),
            meta={"summary": calib.summary(payload), "quality": calib.quality(payload), "unit": payload["unit"], "image_size": payload["image_size"],
                  "has_lens": False, "has_world": False, "has_robot": False, "has_mapping": False},
        )
        created.append(f"資產 {STEREO_CALIB_NAME}（新建）")
    if not Asset.objects.filter(name="Example: shape model (bracket)", kind="file").exists():
        import os
        import uuid as _uuid

        import cv2
        from django.conf import settings

        from apps.vision import shapemodel
        from apps.vision.api_shapemodel import build_model

        first = cv2.cvtColor(demo_images.shape_parts()[0], cv2.COLOR_BGR2GRAY)
        model, meta = build_model(first, {"shape": "rect", "x": 640 - 125, "y": 480 - 95, "w": 250, "h": 190}, None, {"min_contrast": 10})
        shape_id = _uuid.uuid4()
        shape_path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{shape_id.hex}.npz")
        size = shapemodel.save(shape_path, model)
        Asset.objects.create(id=shape_id, name="Example: shape model (bracket)", kind="file", group="Examples", path=shape_path, size=size, meta=meta)
        created.append("資產 Example: shape model (bracket)（新建）")
    if not Asset.objects.filter(name="Example: taught font (digits)", kind="model").exists():
        # OCR 字型教導：PIL 內建字型的數字行 → 切分 → 訓練 → 模型資產（ocr_read 的 model）；完全離線，不需要通用 OCR 模型
        import os
        import uuid as _uuid

        from django.conf import settings

        from apps.vision import ocr as _ocr

        tiles, labels = [], []
        rng = np.random.default_rng(78)
        for _ in range(24):
            code = "".join(rng.choice(list("0123456789"), 8))
            line = demo_images._render_code(code, w=400, h=80, size=36)
            boxes = _ocr.segment_chars(line, "projection")
            if len(boxes) == len(code):
                for b, ch in zip(boxes, code):
                    tiles.append(_ocr.char_tile(line, b))
                    labels.append(ch)
        font_model = _ocr.train_font(tiles, labels, epochs=300)
        font_bytes = _ocr.pack_font(font_model)
        font_id = _uuid.uuid4()
        font_path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{font_id.hex}.npz")
        with open(font_path, "wb") as fh:
            fh.write(font_bytes)
        Asset.objects.create(id=font_id, name="Example: taught font (digits)", kind="model", group="Examples", path=font_path, size=len(font_bytes),
                             meta={"trainer": "ocr_font", "font": "example-digits", "tool_key": "ocr_read", "tool_params": {"charset": "digits"}, "classes": font_model["classes"], "metrics": font_model["metrics"], "format": "npz", "ocr_font": True})
        created.append("模型資產 Example: taught font (digits)（新建，ocr_font）")
    if not Asset.objects.filter(name="Example: statistical template (print)", kind="file").exists():
        import os
        import uuid as _uuid

        from django.conf import settings

        from apps.vision import stattpl

        payload, meta = stattpl.build(demo_images.golden_print_variants(30), None, "phase")
        stat_id = _uuid.uuid4()
        stat_path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{stat_id.hex}.npz")
        size = stattpl.save(stat_path, payload)
        Asset.objects.create(id=stat_id, name="Example: statistical template (print)", kind="file", group="Examples", path=stat_path, size=size, meta=meta)
        created.append("資產 Example: statistical template (print)（新建）")
    _seed_demo_models(created)

    # 範例樣板放在「範本畫廊」（BUILTIN_TEMPLATES），不佔流程清單；清掉舊版 seed 建過的流程。
    stale = Flow.objects.filter(name__in=_GALLERY_FLOW_NAMES)
    removed = stale.count()
    if removed:
        stale.delete()
        created.append(f"移除 {removed} 個舊版範例流程（改由範本畫廊提供）")

    specs: list[tuple[str, str, Any, Any]] = [
        ("Demo: hole count", "Grayscale, threshold, blob count, judge — showing branching and named outputs", hole_count_flow, source),
        ("Demo: exposure check", "Uses an Otsu threshold to tell whether the exposure is normal", brightness_gate_flow, source),
    ]
    for name, desc, builder, src in specs:
        graph = validate_graph(builder(src.id))
        flow, made_flow = Flow.objects.get_or_create(name=name, defaults={"description": desc, "graph": graph})
        if not made_flow:
            flow.graph = graph
            flow.description = desc
            flow.version += 1
            flow.save()
        created.append(f"流程 {flow.name}（{'新建' if made_flow else '已更新'}，id={flow.id}）")
    return created
