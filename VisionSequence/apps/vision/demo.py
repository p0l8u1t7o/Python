"""示範流程（程式化產生，經 validate_graph 後寫入）。

節點用 _node / _edge helper 建，座標以 300×170 網格排，讓畫布一開就整齊。
範例樣板放在「範本畫廊」（BUILTIN_TEMPLATES → GET /vision/templates 的 builtin 項），
seed_demo 只建 2 個示範流程＋每個樣板一組合成樣本圖（apps/vision/demo_images.py，
folder 來源、群組「範例」）＋範本／良品資產（從樣本圖自動裁切）。座標與公差都對齊
合成圖的標稱值，範本掛上對應的「範例：⋯」來源就能執行。深度學習（dl_*）、save_image
與 write_modbus 需要模型／連線，不入樣板，見各流程便利貼說明。
"""

from __future__ import annotations

from typing import Any

from apps.vision.graph import validate_graph
from apps.vision.models import Asset, Flow, ImageSource, ResourceGroup
from apps.vision.tools import base as tools

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


def locate_measure_flow(source_id: Any, template_asset: str = "") -> dict[str, Any]:
    """定位＋卡尺：範本比對 → 定位補正 → ROI 跟隨 → 卡尺量帶高 → 公差。

    對齊合成圖「定位量測」：十字標記標稱 (260, 220)，中央亮帶高 160px（NG 張 200px）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("tm", "template_match", 2, 0, "Find locator template", threshold=0.6, max_matches=1, template=template_asset),
        _node("align", "shape_align", 3, 0, "Locate correction", ref_x=260, ref_y=220, ref_angle=0),
        _node("fix", "fixture_roi", 4, 0, "ROI follow", roi={"shape": "rotated_rect", "cx": 690, "cy": 480, "w": 300, "h": 60, "angle": 90}),
        _node("cal", "caliper", 5, 0, "Caliper band height", polarity="any", edge_pair="widest"),
        _node("rng", "in_range", 6, 0, "Band height tolerance", low=140, high=180),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG: width out of tolerance", verdict="ng", label="width"),
        _node("out", "output", 6, 1, "Output width", name="width_px"),
        _node("nf", "judge", 3, 1, "NG: template not found", verdict="ng", label="not_found"),
        _note("n1", 0, 1, "How to use it", "The template is the cross marker at the top left of the sample image (created by seeding).\nWhen the part moves, the ROI follows the locate result, so the caliper always measures on the bright band.\nFor your own part: draw a new template, take the reference position in one click, and redraw the ROI."),
    ]
    edges = [
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


def cup_measure_flow(source_id: Any, template_asset: str = "") -> dict[str, Any]:
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
        _node("tm", "template_match", 2, 0, "Find locator template", threshold=0.6, max_matches=1, angle_range=10, angle_step=2, template=template_asset),
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


def golden_compare_flow(source_id: Any, template_asset: str = "") -> dict[str, Any]:
    """印刷良品比對：與良品範本做差異比對，任何多印／髒污／缺損都算缺陷。

    對齊合成圖「印刷良品比對」：第 1 張＝良品（seed 已存成資產），NG 張多一塊污漬。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("diff", "defect_diff", 1, 0, "Golden compare", template=template_asset, align="phase", threshold=45, min_area=200),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG: appearance defect", verdict="ng", label="defect"),
        _node("out_n", "output", 2, 2, "Output defect count", name="defect_count"),
        _node("out_a", "output", 3, 2, "Output defect area", name="defect_area"),
        _node("draw", "draw_result", 3, 0, "Result image"),
        _note("n1", 0, 1, "About", "The golden template is the first sample image (the asset is created by seeding).\nDisplacement is corrected automatically by phase alignment; the difference threshold and the minimum area set the sensitivity."),
    ]
    edges = [
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


def contour_defect_flow(source_id: Any, template_asset: str = "") -> dict[str, Any]:
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
        _node("match", "contour_match", 4, 2, "Outline vs. sample", template=template_asset, max_distance=0.05),
        _node("out_m", "output", 5, 3, "Output shape distance", name="shape_distance"),
        _note("n1", 0, 1, "About", "Contour find traces the outline, the filter keeps only the largest one (the part), and contour geometry reports its convexity defects — a bite out of the edge deeper than 12 px is a chip.\nContour match compares the silhouette with the sample outline by Hu moments: a wrong or badly deformed part scores a large distance."),
    ]
    edges = [
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


def shading_flow(source_id: Any, flat_asset: str = "") -> dict[str, Any]:
    """平場校正：白板參考影像除掉漸暈 → 固定門檻找暗污點 → blob 計數 → 6 顆＝OK。

    對齊合成圖「打光不均」：角落亮度只剩 45%，不校正時固定門檻在角落整片誤判；校正後每張 6 顆（第 4 張多一大塊 → 7，NG）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "Grayscale"),
        _node("flat", "shading_correct", 2, 0, "Flat-field correction", mode="flat_field", flat=flat_asset, target_level=200),
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
        _edge("src", "gray"), _edge("gray", "flat", "image", "image"), _edge("flat", "thr", "image", "image"), _edge("thr", "blob", "image", "image"),
        _edge("blob", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("blob", "out", "count", "value"),
        _edge("gray", "raw_thr", "image", "image"), _edge("raw_thr", "raw_blob", "image", "image"), _edge("raw_blob", "out_raw", "count", "value"),
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
    """YOLO 物件計數（官方底模）：yolo_detect 只留 stop sign → 數量 = 2 → OK；不用訓練，第一次執行自動下載 yolo11n.pt。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("det", "yolo_detect", 1, 0, "YOLO find signs", model_name="yolo11n.pt", conf=0.4, filter_labels="stop sign", min_count=1, imgsz=640),
        _node("cmp", "if_number", 2, 0, "2 signs?", operator="eq", threshold=2),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG: wrong count", verdict="ng", label="sign_count"),
        _node("out", "output", 2, 1, "Output count", name="sign_count"),
        _node("draw", "draw_result", 2, 2, "Result image"),
        _note("n1", 0, 1, "About", "The stock COCO model (yolo11n.pt) recognises stop signs directly, with no training; the first run downloads about 5 MB of weights.\nFor your own objects: train an object detection (YOLO) project on the Deep learning page and select the result as the model asset."),
    ]
    edges = [
        _edge("src", "det"), _edge("det", "cmp", "count", "value"),
        _edge("cmp", "ok", "true", "_flow"), _edge("cmp", "ng", "false", "_flow"),
        _edge("det", "out", "count", "value"), _edge("src", "draw", "image", "image"),
    ]
    return {"nodes": nodes, "edges": edges}


def yolo_area_flow(source_id: Any) -> dict[str, Any]:
    """YOLO 實例分割（官方底模）：yolo_segment 的聯合遮罩 → 像素計數（面積）→ 門檻判定；輸出標誌面積。"""
    nodes = [
        _node("src", "image_source", 0, 0, "Acquire", source_id=source_id),
        _node("seg", "yolo_segment", 1, 0, "YOLO segment signs", model_name="yolo11n-seg.pt", conf=0.4, filter_labels="stop sign", min_count=1, imgsz=640),
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
        _note("n1", 0, 1, "About", "The model \"Example: classifier (good / missing hole)\" is trained by seed_demo on 30 synthetic samples (the built-in MLP, seconds on CPU).\nThat MLP sees the whole downscaled image, which suits classes that differ in overall appearance; for small defects in random positions use semantic segmentation or YOLO. For your own part: create a classification project on the Deep learning page, label a few images, press train, and swap this node's model asset for the result."),
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


def _demo_model(name: str) -> tuple[str, dict[str, Any]]:
    """seed 訓練的示範模型資產：(asset id, 建議的工具參數)；還沒 seed 就回空（範本照樣能載入）。"""
    row = Asset.objects.filter(name=name, kind="model").only("id", "meta").first()
    if not row:
        return "", {}
    return str(row.id), dict((row.meta or {}).get("tool_params") or {})


def _demo_asset(name: str) -> str:
    """seed 建立的範例資產 id；還沒 seed 就回空字串（範本照樣能載入，資產欄留給使用者填）。"""
    row = Asset.objects.filter(name=name, kind="image").only("id").first()
    return str(row.id) if row else ""


#: 範本畫廊的內建範本目錄：(key, 名稱, 說明, 分類, builder)。
#: builder 在 request 時才呼叫（範例資產 id 由 _demo_asset 現查，seed 過就開箱即用）。
BUILTIN_TEMPLATES: tuple[tuple[str, str, str, str, Any], ...] = (
    ("hole_count", "Hole count", "Grayscale, denoise, threshold, morphology, blob count, number check, OK/NG — with a named output and a result image", "count", hole_count_flow),
    ("exposure", "Exposure check", "Downscale, Otsu threshold, range check, OK/NG", "quality", brightness_gate_flow),
    ("circle_gauge", "Circle gauge", "Find circle, diameter, pixel calibration to mm, tolerance judge — plus a sector ROI arc fit and ellipse roundness", "measure", circle_gauge_flow),
    ("edge_angle", "Edge angle", "Two line finds into an angle tolerance, the intersection point, and a 45 degree chamfer measurement", "measure", edge_angle_flow),
    ("golden_compare", "Print compare", "Difference against a golden template to catch overprinting, smudges and gaps; the template asset is created from the sample images", "quality",
     lambda sid: golden_compare_flow(sid, _demo_asset("Example: print golden template"))),
    ("fft_defect", "Fabric defect", "A frequency-domain low pass removes the periodic weave and what is left is the scratch; a mask pulls out the defect area", "quality", fft_defect_flow),
    ("preprocess_lab", "Pre-processing and measurement lab", "An image chain of bit depth, look-up table, filtering and flipping, plus a tour of line profile, statistics, histogram and edge density", "tutorial", preprocess_lab_flow),
    ("geometry_count", "Circles and lines", "Hough circles counted, Hough lines counted as a list, and two circle finds giving a centre distance", "count", geometry_count_flow),
    ("gear_teeth", "Gear tooth count (polar unwrap)", "Polar unwrap flattens the tooth ring into a strip, threshold and blob count the teeth, and Polar restore marks each tooth on the original picture", "count", gear_teeth_flow),
    ("contour_defect", "Chipped edge (contour geometry)", "Contour find, filter to the part, contour geometry counting convexity defects deeper than 12 px, OK/NG — plus a Hu-moment contour match against the sample outline", "quality",
     lambda sid: contour_defect_flow(sid, _demo_asset("Example: stamped part outline"))),
    ("exclusion_zone", "Exclusion zones (combined region)", "Two drawn regions cut out of the plate rectangle by Region combine, feeding the statistics and blob steps through their region inputs — the hole pixels never count", "measure", exclusion_zone_flow),
    ("shading", "Flat-field correction (uneven lighting)", "Divide by a white-reference asset so one fixed threshold finds the dark spots in the corners too; a side branch shows the same threshold failing on the uncorrected picture", "quality",
     lambda sid: shading_flow(sid, _demo_asset("Example: white reference (uneven lighting)"))),
    ("color_presence", "Colour presence", "A colour range mask into a pixel count, judged against a threshold", "detect", color_presence_flow),
    ("color_verify", "Colour verification", "The region's mean colour against a target by distance, with colour statistics reporting a hex code", "detect", color_verify_flow),
    ("barcode_read", "Barcode / QR read", "Read the code, check whether anything was read, output it", "identify", barcode_flow),
    ("label_read", "Barcode label with perspective correction", "Four-point perspective correction straightens the tilted label before reading it, plus a text-presence check on the serial area", "identify", label_flow),
    ("locate_measure", "Locate and gauge", "Template match, locate correction, ROI follow, caliper width, tolerance judge", "measure",
     lambda sid: locate_measure_flow(sid, _demo_asset("Example: cross locator template"))),
    ("cup_measure", "Deep-drawn cup gauge", "Template match, locate correction, three ROIs following, outer and inner circle finds plus wall thickness, concentricity, three tolerance judges, named outputs, OK/NG", "measure",
     lambda sid: cup_measure_flow(sid, _demo_asset("Example: cup locator template"))),
    ("yolo_count", "YOLO object count (stock model)", "yolo_detect finds stop signs with the COCO stock model and judges the count. No training needed and the GPU is used automatically (deep-learning dependencies required)", "count", yolo_count_flow),
    ("yolo_area", "YOLO instance segmentation: sign area", "yolo_segment's union mask into a pixel count and an area threshold, showing segmentation feeding a measurement (deep-learning dependencies required)", "detect", yolo_area_flow),
    ("dl_classify_demo", "Classification: good / missing hole (taught model)", "The built-in MLP classifier trained by seeding, into dl_classify pass/fail — how a taught model gets into a flow", "quality",
     lambda sid: dl_classify_flow(sid, _demo_model("Example: classifier (good / missing hole)"))),
    ("dl_segment_demo", "Semantic segmentation: scratch area (taught model)", "The patch_segment model trained by seeding, into a dl_segment scratch-area threshold and OK/NG", "quality",
     lambda sid: dl_segment_flow(sid, _demo_model("Example: segmenter (scratch)"))),
)

#: builtin 範本 key → 對應的範例樣本來源名稱（測試與文件用；hole_count／exposure 用合成來源）。
TEMPLATE_SAMPLE_SOURCES: dict[str, str] = {
    "hole_count": "Demo: synthetic parts",
    "exposure": "Demo: synthetic parts",
    "circle_gauge": "Example: circle gauge",
    "edge_angle": "Example: edge angle",
    "golden_compare": "Example: print compare",
    "fft_defect": "Example: fabric defect",
    "preprocess_lab": "Example: preprocessing lab",
    "geometry_count": "Example: circles and lines",
    "gear_teeth": "Example: gear teeth",
    "contour_defect": "Example: stamped part",
    "exclusion_zone": "Example: circle gauge",
    "shading": "Example: uneven lighting",
    "color_presence": "Example: colour blocks",
    "color_verify": "Example: colour blocks",
    "barcode_read": "Example: barcode label",
    "label_read": "Example: barcode label",
    "locate_measure": "Example: locate and gauge",
    "cup_measure": "Example: cup gauge",
    "yolo_count": "Example: stop sign",
    "yolo_area": "Example: stop sign",
    "dl_classify_demo": "Example: classification teaching",
    "dl_segment_demo": "Example: segmentation teaching",
}

#: 需要 DL 依賴（ultralytics／torch）才能執行的範本 key；測試與文件用。
TEMPLATES_NEED_DL = ("yolo_count", "yolo_area")


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
    specs = (
        ("Example: classifier (good / missing hole)", "mlp_classify", demo_images.dl_parts_labeled, ["ok", "ng"], {"input_size": 64, "epochs": 300, "val_split": 0.2, "augment": True}),
        ("Example: segmenter (scratch)", "patch_segment", demo_images.dl_scratch_labeled, ["scratch"], {"input_size": 128, "epochs": 200, "samples_per_image": 2000}),
    )
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

    source, made = ImageSource.objects.get_or_create(
        name="Demo: synthetic parts",
        defaults={"kind": "synthetic", "group": "Examples", "config": {"width": 1280, "height": 960, "pattern": "parts", "seed": 7, "defect_rate": 0.3}},
    )
    if not made and not source.group:
        source.group = "Examples"
        source.save(update_fields=["group"])
    created.append(f"影像來源 {source.name}（{'新建' if made else '既有'}）")

    def folder_source(key: str) -> ImageSource:
        folder = demo_images.write_set(key)
        label = demo_images.SAMPLE_SETS[key][0]
        src, made_src = ImageSource.objects.get_or_create(
            name=f"Example: {label}",
            defaults={"kind": "folder", "group": "Examples", "config": {"path": folder, "loop": True, "sort": "name"}},
        )
        created.append(f"影像來源 {src.name}（{'新建' if made_src else '既有'}）")
        return src

    def sample_asset(name: str, key: str, region: dict[str, Any] | None, image: Any = None) -> str:
        """從樣本圖第 1 張裁一塊存成資產（既有同名資產直接沿用），回傳 asset id；給 image 時直接存那張（參考影像）。"""
        existing = Asset.objects.filter(name=name, kind="image").first()
        if existing:
            return str(existing.id)
        import os
        import uuid as _uuid

        import cv2
        import numpy as np
        from django.conf import settings

        from apps.vision.tools.roi import crop as roi_crop

        if image is None:
            folder = demo_images.write_set(key)
            first = sorted(n for n in os.listdir(folder) if n.endswith(".png"))[0]
            image = cv2.imdecode(np.fromfile(os.path.join(folder, first), dtype=np.uint8), cv2.IMREAD_COLOR)
        piece = roi_crop(image, region, upright=True).image if region else image
        asset_id = _uuid.uuid4()
        path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.png")
        ok, buf = cv2.imencode(".png", piece)
        buf.tofile(path)
        asset = Asset.objects.create(
            id=asset_id, name=name, kind="image", group="Examples", path=path, size=int(buf.size),
            meta={"width": int(piece.shape[1]), "height": int(piece.shape[0]), "channels": 3},
        )
        created.append(f"資產 {asset.name}（新建）")
        return str(asset.id)

    # 每個範本畫廊樣板一組樣本來源；範例資產從樣本圖自動裁切（builtin 範本 instantiate 時現查）。
    for key in demo_images.SAMPLE_SETS:
        folder_source(key)
    sample_asset("Example: cross locator template", "marker_plate", {"shape": "rect", "x": 200, "y": 160, "w": 120, "h": 120})
    sample_asset("Example: cup locator template", "cup", {"shape": "rect", "x": 150, "y": 120, "w": 100, "h": 100})
    sample_asset("Example: print golden template", "golden_print", None)
    sample_asset("Example: stamped part outline", "stamped_part", None)
    sample_asset("Example: white reference (uneven lighting)", "vignette", None, image=demo_images.vignette_flat())
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
