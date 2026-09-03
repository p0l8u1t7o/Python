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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("blur", "blur", 2, 0, "去雜訊", method="median", ksize=5),
        _node("thr", "threshold", 3, 0, "找暗孔", method="fixed", threshold=60, invert=True),
        _node("open", "morphology", 4, 0, "開運算去雜點", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "孔 blob", min_area=300, max_area=60000, min_circularity=0.6, sort_by="area"),
        _node("cmp", "if_number", 6, 0, "孔數 = 5？", operator="eq", threshold=5),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG：孔數不對", verdict="ng", label="hole_count"),
        _node("out", "output", 6, 1, "輸出孔數", name="hole_count"),
        _node("draw", "draw_result", 6, 2, "結果影像"),
        _note("n1", 0, 1, "說明", "合成影像每張隨機位移／旋轉，約 30% 會少一個孔或有刮痕。\n孔數不等於 5 走 NG 分支。"),
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
    nodes.append(_node("cnt", "pixel_count" if tools.has("pixel_count") else "threshold", 4, 0, "計數"))
    return {"nodes": nodes, "edges": [e for e in edges if e["source"] not in ("blob", "open", "thr") and e["target"] not in ("blob", "open")] + [_edge("thr", "cnt")]}


def brightness_gate_flow(source_id: Any) -> dict[str, Any]:
    """曝光檢查：平均亮度落在範圍內才 OK（純前處理＋邏輯，無 detect 依賴）。"""
    nodes = [
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("small", "resize", 2, 0, "縮小加速", scale=0.25),
        _node("thr", "threshold", 3, 0, "Otsu", method="otsu"),
        _node("rng", "in_range", 4, 0, "門檻合理？", low=40, high=200),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG：曝光異常", verdict="ng", label="exposure"),
        _node("out", "output", 4, 1, "輸出 Otsu 門檻", name="otsu"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("tm", "template_match", 2, 0, "找定位範本", threshold=0.6, max_matches=1, template=template_asset),
        _node("align", "shape_align", 3, 0, "定位補正", ref_x=260, ref_y=220, ref_angle=0),
        _node("fix", "fixture_roi", 4, 0, "ROI 跟隨", roi={"shape": "rotated_rect", "cx": 690, "cy": 480, "w": 300, "h": 60, "angle": 90}),
        _node("cal", "caliper", 5, 0, "卡尺量帶高", polarity="any", edge_pair="widest"),
        _node("rng", "in_range", 6, 0, "帶高公差", low=140, high=180),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG：寬度超差", verdict="ng", label="width"),
        _node("out", "output", 6, 1, "輸出寬度", name="width_px"),
        _node("nf", "judge", 3, 1, "NG：找不到範本", verdict="ng", label="not_found"),
        _note("n1", 0, 1, "使用方式", "範本＝樣本圖左上的十字標記（seed 已自動建立）。\n工件位移時 ROI 跟著定位結果移動，卡尺永遠量在亮帶上。\n換自己的工件：範本重新框選、參考位置一鍵帶入、ROI 重畫即可。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("tm", "template_match", 2, 0, "找定位範本", threshold=0.6, max_matches=1, angle_range=10, angle_step=2, template=template_asset),
        _node("align", "shape_align", 3, 0, "定位補正", ref_x=200, ref_y=170, ref_angle=0),
        _node("nf", "judge", 3, 1, "NG：找不到範本", verdict="ng", label="not_found"),
        _node("fix_od", "fixture_roi", 4, 0, "外徑 ROI 跟隨", roi=od_roi),
        _node("fix_id", "fixture_roi", 4, 1, "內徑 ROI 跟隨", roi=id_roi),
        _node("fix_wall", "fixture_roi", 4, 2, "壁厚 ROI 跟隨", roi=wall_roi),
        _node("od", "find_circle", 5, 0, "外徑找圓", polarity="any", edge_threshold=20, num_rays=72, edge_select="last"),
        _node("idc", "find_circle", 5, 1, "內徑找圓", polarity="any", edge_threshold=20, num_rays=72, edge_select="first"),
        _node("wall", "wall_thickness", 5, 2, "壁厚", polarity="any", edge_threshold=20, num_calipers=10, band=40),
        _node("od_d", "formula", 6, 0, "外徑 = 2r", expression="a*2"),
        _node("id_d", "formula", 6, 1, "內徑 = 2r", expression="a*2"),
        _node("conc", "concentricity", 6, 3, "同心度", max_deviation=5),
        _node("tol_od", "tolerance_judge", 7, 0, "外徑公差", nominal=700, upper_tol=5, lower_tol=-5, unit="px", spec_source="圖面 ⌀外徑", name="od"),
        _node("tol_id", "tolerance_judge", 7, 1, "內徑公差", nominal=520, upper_tol=5, lower_tol=-5, unit="px", spec_source="圖面 ⌀內徑", name="id"),
        _node("tol_wall", "tolerance_judge", 7, 2, "壁厚公差", nominal=90, upper_tol=5, lower_tol=-5, unit="px", spec_source="圖面 壁厚", name="wall"),
        _node("out_od", "output", 8, 0, "輸出外徑", name="od_px"),
        _node("out_id", "output", 8, 1, "輸出內徑", name="id_px"),
        _node("out_wall", "output", 8, 2, "輸出壁厚", name="wall_px"),
        _node("all_ok", "bool_logic", 8, 3, "全部合格？", mode="and"),
        _node("judge", "judge", 9, 3, "OK / NG", verdict="by_input", label="cup"),
        _node("draw", "draw_result", 9, 0, "結果影像"),
        _note("n1", 0, 1, "教導步驟", "1. 找定位範本：框選杯口特徵建範本。\n2. 試跑後把定位補正的參考位置設成目前匹配。\n3. 三個 ROI 跟隨：外徑環、內徑環、壁厚線段（橫切杯壁）。\n4. 公差判定填圖面標稱值／上下偏差／出處；同心度填 max_deviation。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("mask", "color_range", 1, 0, "紅色遮罩", h_low=0, h_high=12, s_low=80, s_high=255, v_low=60, v_high=255),
        _node("cnt", "pixel_count", 2, 0, "計數", min_count=50000),
        _node("cmp", "if_number", 3, 0, "夠多嗎？", operator="ge", threshold=50000),
        _node("ok", "judge", 4, 0, "OK：有料", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：缺料", verdict="ng", label="missing"),
        _node("out", "output", 3, 1, "輸出像素數", name="pixels"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("bc", "barcode", 2, 0, "讀碼"),
        _node("cmp", "if_number", 3, 0, "讀到？", operator="ge", threshold=1),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：讀不到", verdict="ng", label="no_code"),
        _node("out", "output", 3, 1, "輸出內容", name="code"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("fc", "find_circle", 2, 0, "找孔", roi=roi, polarity="any", edge_threshold=20, num_rays=72),
        _node("dia", "formula", 3, 0, "直徑 = 2r", expression="a*2"),
        _node("cal", "calibration", 4, 0, "像素校正", mode="pixel_size", pixel_size_mm=0.05),
        _node("tol", "tolerance_judge", 5, 0, "直徑公差", nominal=17.5, upper_tol=0.4, lower_tol=-0.4, unit="mm", spec_source="圖面 ⌀17.5±0.4", name="diameter"),
        _node("jd", "judge", 6, 0, "OK / NG", verdict="by_input", label="diameter"),
        _node("out", "output", 5, 1, "輸出直徑 mm", name="diameter_mm"),
        _node("arc", "fit_arc", 2, 1, "上弧擬合", roi=arc_roi, polarity="any", edge_threshold=20),
        _node("ell", "fit_ellipse", 2, 2, "橢圓擬合看圓度", roi=roi, polarity="any", edge_threshold=20),
        _node("out_r", "output", 3, 2, "輸出圓度", name="roundness"),
        _node("nf", "judge", 3, 1, "NG：找不到孔", verdict="ng", label="not_found"),
        _node("draw", "draw_result", 6, 1, "結果影像"),
        _note("n1", 0, 1, "說明", "找圓的環形 ROI 蓋住孔緣；弧擬合示範「扇形」ROI（只取上半弧）。\n公差判定收 mm 值：像素校正把 350px 直徑 × 0.05 mm/px 換算成 17.5mm。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("l1", "find_line", 2, 0, "底邊", roi=roi_base, polarity="any", edge_threshold=20),
        _node("l2", "find_line", 2, 1, "側邊", roi=roi_arm, polarity="any", edge_threshold=20),
        _node("ang", "angle", 3, 0, "夾角", range="0_90"),
        _node("rng", "in_range", 4, 0, "89°～91°？", low=89, high=91),
        _node("ok", "judge", 5, 0, "OK", verdict="ok"),
        _node("ng", "judge", 5, 1, "NG：角度超差", verdict="ng", label="angle"),
        _node("geo", "geometry", 3, 1, "兩線交點", mode="intersect"),
        _node("out_a", "output", 4, 1, "輸出夾角", name="angle_deg"),
        _node("out_x", "output", 4, 2, "輸出交點 X", name="corner_x"),
        _node("cham", "chamfer_angle", 2, 2, "斜切角", roi=roi_cham, polarity="any", edge_threshold=20),
        _node("out_c", "output", 3, 2, "輸出斜切角", name="chamfer_deg"),
        _note("n1", 0, 1, "說明", "兩個找線各自框住一條邊，夾角工具直接吃兩條線。\n倒角量測框住右下斜切角（標稱 45°）。找不到線會走 not_found 分支。"),
        _node("nf", "judge", 3, 2, "NG：找不到邊", verdict="ng", label="no_edge"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("diff", "defect_diff", 1, 0, "良品比對", template=template_asset, align="phase", threshold=45, min_area=200),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：外觀缺陷", verdict="ng", label="defect"),
        _node("out_n", "output", 2, 2, "輸出缺陷數", name="defect_count"),
        _node("out_a", "output", 3, 2, "輸出缺陷面積", name="defect_area"),
        _node("draw", "draw_result", 3, 0, "結果影像"),
        _note("n1", 0, 1, "說明", "良品範本＝樣本圖第 1 張（seed 自動建立資產）。\n位移由相位對齊自動補正；差異門檻與最小面積決定靈敏度。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("fft", "fft_filter", 2, 0, "頻域低通", mode="lowpass", cutoff=0.08),
        _node("thr", "threshold", 3, 0, "抓暗痕", method="fixed", threshold=95, invert=True),
        _node("mor", "morphology", 4, 0, "開運算去雜點", op="open", ksize=5),
        _node("blob", "blob", 5, 0, "刮痕 blob", threshold_method="fixed", threshold=128, polarity="bright", min_area=800, min_count=0),
        _node("cmp", "if_number", 6, 0, "沒有刮痕？", operator="eq", threshold=0),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG：表面刮痕", verdict="ng", label="scratch"),
        _node("mask", "apply_mask", 5, 2, "只留缺陷區", fill=0),
        _node("out", "output", 6, 1, "輸出刮痕數", name="scratch_count"),
        _node("draw", "draw_result", 7, 2, "結果影像"),
        _note("n1", 0, 1, "說明", "頻域濾波是紋理背景檢測的王牌：規律紋理＝固定頻率，低通一刀切掉，\n殘下來的大尺度暗痕就是缺陷。「只留缺陷區」示範遮罩套用。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("cd", "convert_depth", 1, 0, "位深轉 8bit", to="u8"),
        _node("lut", "lut", 2, 0, "Gamma 校正", mode="gamma", gamma=0.8),
        _node("fil", "filter", 3, 0, "銳化", method="sharpen", strength=1.0),
        _node("flip", "rotate_flip", 4, 0, "水平翻轉", flip="horizontal"),
        _node("prof", "line_profile", 2, 1, "暗溝剖面", roi=groove),
        _node("out_g", "output", 3, 1, "輸出溝底灰階", name="groove_min"),
        _node("inten", "intensity", 2, 2, "中央區統計", roi=center),
        _node("out_m", "output", 3, 2, "輸出平均亮度", name="center_mean"),
        _node("hist", "histogram", 2, 3, "直方圖"),
        _node("out_o", "output", 3, 3, "輸出 Otsu 門檻", name="otsu"),
        _node("diff", "arithmetic", 5, 0, "前後差異", op="absdiff"),
        _node("din", "intensity", 6, 0, "差異均值"),
        _node("out_d", "output", 7, 0, "輸出處理差異", name="diff_mean"),
        _node("gray", "grayscale", 1, 2, "灰階"),
        _node("crop", "crop", 1, 3, "裁切中央", roi=center),
        _node("cc", "color_convert", 2, 4, "取飽和度面", mode="hsv_s"),
        _node("ed", "edge_density", 5, 1, "邊緣密度守門", max_ratio=0.2),
        _node("ok", "judge", 6, 1, "OK", verdict="ok"),
        _node("ng", "judge", 6, 2, "NG：畫面異常", verdict="ng", label="edge_density"),
        _node("dark", "dark_ratio", 5, 3, "暗部比例", threshold=60, max_ratio=0.2),
        _node("out_k", "output", 6, 3, "輸出暗部比例", name="dark_ratio"),
        _note("n1", 0, 1, "說明", "上排是影像處理鏈：位深→Gamma→銳化→翻轉，差異工具量化處理前後變化。\n下排是量測工具課：線剖面量暗溝、區域統計、直方圖、邊緣密度、暗部比例。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("hc", "hough_circles", 2, 0, "霍夫找圓", min_radius=50, max_radius=110, min_dist=120, param2=20),
        _node("cmp", "if_number", 3, 0, "孔數 = 5？", operator="eq", threshold=5),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：孔數不對", verdict="ng", label="hole_count"),
        _node("out_n", "output", 3, 1, "輸出孔數", name="circle_count"),
        _node("hl", "hough_lines", 2, 1, "霍夫找線", threshold=80, min_length=300, max_gap=20),
        _node("cl", "count_list", 3, 2, "線段計數"),
        _node("out_l", "output", 4, 2, "輸出線段數", name="line_count"),
        _node("fa", "find_circle", 2, 3, "左上孔", roi=roi_a, polarity="any", edge_threshold=20),
        _node("fb", "find_circle", 2, 4, "右上孔", roi=roi_b, polarity="any", edge_threshold=20),
        _node("dist", "distance", 3, 3, "兩孔圓心距"),
        _node("out_d", "output", 4, 3, "輸出圓心距", name="pitch_px"),
        _note("n1", 0, 1, "說明", "霍夫找圓適合「一次抓很多圓」，找圓（射線式）適合「精量測單一圓」。\n距離工具直接吃兩個找圓的圓心座標，量孔距。"),
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


def color_verify_flow(source_id: Any) -> dict[str, Any]:
    """顏色比對：指定區域的平均色與目標色比距離 → 判定；顏色統計輸出色碼。

    對齊合成圖「顏色檢驗」：左側色塊標稱紅色（NG 張偏橘）。"""
    left = {"shape": "rect", "x": 150, "y": 330, "w": 240, "h": 300}
    nodes = [
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("chk", "color_check", 1, 0, "紅色比對", roi=left, color="#d22828", space="rgb", tolerance=60),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：顏色不符", verdict="ng", label="color"),
        _node("stat", "color_stats", 1, 1, "顏色統計", roi=left),
        _node("out_h", "output", 2, 2, "輸出色碼", name="hex"),
        _node("out_d", "output", 3, 1, "輸出色差", name="color_distance"),
        _note("n1", 0, 1, "說明", "顏色比對量「平均色與目標色的距離」，適合驗料／驗蓋色。\n顏色統計把 RGB／HSV 平均與色碼丟出去，供上位機記錄。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("warp", "warp_perspective", 1, 0, "標籤拉正", roi=quad, width=560, height=420),
        _node("gray", "grayscale", 2, 0, "灰階"),
        _node("bc", "barcode", 3, 0, "讀碼"),
        _node("ok", "judge", 4, 0, "OK", verdict="ok"),
        _node("ng", "judge", 4, 1, "NG：讀不到碼", verdict="ng", label="no_code"),
        _node("out", "output", 4, 2, "輸出內容", name="code"),
        _node("txt", "text_presence", 3, 2, "序號區有字？", roi=sn_roi, polarity="dark"),
        _node("ng2", "judge", 4, 3, "NG：序號沒印", verdict="ng", label="no_sn"),
        _note("n1", 0, 1, "說明", "標籤斜貼也能讀：先用四點透視校正拉正再讀碼。\n文字有無用筆畫密度判斷，沒印序號直接 NG。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("det", "yolo_detect", 1, 0, "YOLO 找標誌", model_name="yolo11n.pt", conf=0.4, filter_labels="stop sign", min_count=1, imgsz=640),
        _node("cmp", "if_number", 2, 0, "標誌 = 2？", operator="eq", threshold=2),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG：數量不對", verdict="ng", label="sign_count"),
        _node("out", "output", 2, 1, "輸出數量", name="sign_count"),
        _node("draw", "draw_result", 2, 2, "結果影像"),
        _note("n1", 0, 1, "說明", "官方 COCO 底模（yolo11n.pt）直接辨識停止標誌，不需訓練；第一次執行會下載約 5MB 權重。\n要辨識自己的物件：到「深度學習」用「物件偵測（YOLO）」訓練，再把「模型資產」選成訓練產物。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("seg", "yolo_segment", 1, 0, "YOLO 分割標誌", model_name="yolo11n-seg.pt", conf=0.4, filter_labels="stop sign", min_count=1, imgsz=640),
        _node("area", "pixel_count", 2, 0, "標誌面積", threshold=128, min_count=15000, max_count=45000),
        _node("ok", "judge", 3, 0, "OK", verdict="ok"),
        _node("ng", "judge", 3, 1, "NG：面積異常", verdict="ng", label="sign_area"),
        _node("out", "output", 2, 1, "輸出面積", name="sign_area"),
        _node("draw", "draw_result", 2, 2, "結果影像"),
        _note("n1", 0, 1, "說明", "分割模型輸出每個實例的輪廓與聯合遮罩；遮罩接像素計數就是總面積（也可接 blob 逐個量測）。\n第 4 張只有 1 個標誌、第 5 張有 3 個，面積落在門檻外走 NG。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("cls", "dl_classify", 1, 0, "DL 分類：良品？", **params),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：缺孔", verdict="ng", label="missing_hole"),
        _node("out", "output", 2, 2, "輸出分數", name="ok_score"),
        _node("draw", "draw_result", 1, 2, "結果影像"),
        _note("n1", 0, 1, "說明", "模型「範例：分類模型（良品／缺孔）」由 seed_demo 用 30 張合成樣本訓練（內建 MLP，CPU 數秒）。\n內建 MLP 看的是整張縮圖，適合整體外觀不同的類別；位置隨機的細小瑕疵請用語意分割或 YOLO。自己的零件：到「深度學習」建分類專案、標記幾張、按訓練，再把此節點的模型資產換成產物。"),
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
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("seg", "dl_segment", 1, 0, "DL 分割：刮痕", **params),
        _node("ok", "judge", 2, 0, "OK", verdict="ok"),
        _node("ng", "judge", 2, 1, "NG：刮痕面積過大", verdict="ng", label="scratch_area"),
        _node("out", "output", 2, 2, "輸出面積", name="scratch_area"),
        _node("draw", "draw_result", 1, 2, "結果影像"),
        _note("n1", 0, 1, "說明", "模型「範例：分割模型（刮痕）」由 seed_demo 用 10 張合成樣本（polygon 標記）訓練，全卷積 ONNX、CPU 推論。\n遮罩輸出可再接 blob 逐條量刮痕長度；換成自己的瑕疵請到「深度學習」用「語意分割」專案訓練。"),
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
    ("hole_count", "零件孔數檢測", "灰階→去雜訊→二值化→形態學→Blob 計數→數值判斷→OK/NG；含具名輸出與結果影像", "count", hole_count_flow),
    ("exposure", "曝光檢查", "縮圖→Otsu 門檻→範圍判斷→OK/NG", "quality", brightness_gate_flow),
    ("circle_gauge", "圓孔尺寸量測", "找圓→直徑→像素校正成 mm→公差判定；扇形 ROI 弧擬合與橢圓圓度", "measure", circle_gauge_flow),
    ("edge_angle", "邊線夾角", "兩條找線→夾角公差；兩線交點座標與 45° 斜切角量測", "measure", edge_angle_flow),
    ("golden_compare", "印刷良品比對", "與良品範本差異比對，抓多印／髒污／缺損；範本資產可由 seed 樣本自動建立", "quality",
     lambda sid: golden_compare_flow(sid, _demo_asset("範例：印刷良品範本"))),
    ("fft_defect", "織紋瑕疵檢測", "頻域低通濾掉週期織紋，殘留暗痕＝刮痕；含遮罩套用取缺陷區", "quality", fft_defect_flow),
    ("preprocess_lab", "前處理與量測教學", "位深／查找表／濾波／翻轉影像鏈＋線剖面／統計／直方圖／邊緣密度等量測工具課", "tutorial", preprocess_lab_flow),
    ("geometry_count", "多圓幾何計數", "霍夫找圓計數、霍夫找線清單計數、兩孔找圓→圓心距", "count", geometry_count_flow),
    ("color_presence", "顏色／有無檢測", "色彩範圍遮罩→像素計數→門檻判定", "detect", color_presence_flow),
    ("color_verify", "顏色比對", "區域平均色與目標色比距離→判定；顏色統計輸出色碼", "detect", color_verify_flow),
    ("barcode_read", "條碼／QR 讀取", "讀碼→是否讀到→具名輸出", "identify", barcode_flow),
    ("label_read", "條碼標籤讀取（透視校正）", "四點透視校正把斜貼標籤拉正→讀碼；序號區文字有無檢查", "identify", label_flow),
    ("locate_measure", "定位＋卡尺量測", "範本比對→定位補正→ROI 跟隨→卡尺寬度→公差判定", "measure",
     lambda sid: locate_measure_flow(sid, _demo_asset("範例：定位十字範本"))),
    ("cup_measure", "深抽杯件量測", "範本比對→定位補正→ROI 跟隨×3→外徑／內徑找圓＋壁厚→同心度→公差判定×3→具名輸出→OK/NG", "measure",
     lambda sid: cup_measure_flow(sid, _demo_asset("範例：杯件定位範本"))),
    ("yolo_count", "YOLO 物件計數（官方底模）", "yolo_detect 用 COCO 底模找停止標誌→數量判定；不需訓練、GPU 自動使用（需安裝 DL 依賴）", "count", yolo_count_flow),
    ("yolo_area", "YOLO 實例分割：標誌面積", "yolo_segment 聯合遮罩→像素計數→面積門檻；示範分割輸出接後續量測（需安裝 DL 依賴）", "detect", yolo_area_flow),
    ("dl_classify_demo", "DL 分類：良品／缺孔（教導模型）", "seed 訓練的內建 MLP 分類模型→dl_classify pass/fail；示範教導產物如何進流程", "quality",
     lambda sid: dl_classify_flow(sid, _demo_model("範例：分類模型（良品／缺孔）"))),
    ("dl_segment_demo", "DL 語意分割：刮痕面積（教導模型）", "seed 訓練的 patch_segment 模型→dl_segment 刮痕面積門檻→OK/NG", "quality",
     lambda sid: dl_segment_flow(sid, _demo_model("範例：分割模型（刮痕）"))),
)

#: builtin 範本 key → 對應的範例樣本來源名稱（測試與文件用；hole_count／exposure 用合成來源）。
TEMPLATE_SAMPLE_SOURCES: dict[str, str] = {
    "hole_count": "示範：合成零件",
    "exposure": "示範：合成零件",
    "circle_gauge": "範例：圓孔量測",
    "edge_angle": "範例：邊線夾角",
    "golden_compare": "範例：印刷良品比對",
    "fft_defect": "範例：織紋瑕疵",
    "preprocess_lab": "範例：前處理教學圖",
    "geometry_count": "範例：多圓幾何",
    "color_presence": "範例：顏色檢驗",
    "color_verify": "範例：顏色檢驗",
    "barcode_read": "範例：條碼標籤",
    "label_read": "範例：條碼標籤",
    "locate_measure": "範例：定位量測",
    "cup_measure": "範例：杯件量測",
    "yolo_count": "範例：停止標誌",
    "yolo_area": "範例：停止標誌",
    "dl_classify_demo": "範例：分類教導",
    "dl_segment_demo": "範例：分割教導",
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
        ("範例：分類模型（良品／缺孔）", "mlp_classify", demo_images.dl_parts_labeled, ["ok", "ng"], {"input_size": 64, "epochs": 300, "val_split": 0.2, "augment": True}),
        ("範例：分割模型（刮痕）", "patch_segment", demo_images.dl_scratch_labeled, ["scratch"], {"input_size": 128, "epochs": 200, "samples_per_image": 2000}),
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
                id=asset_id, name=name, kind="model", group="範例", path=path, size=len(result.onnx_bytes),
                meta={"trainer": kind, "project": "範例", "tool_key": result.tool_key, "tool_params": result.tool_params, "metrics": result.metrics, "format": "onnx"},
            )
            created.append(f"模型資產 {name}（新建，{kind}）")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

#: 舊版 seed 建過、現改由範本畫廊提供的流程名稱（seed 時清掉，避免流程清單被塞滿）。
_GALLERY_FLOW_NAMES = (
    "範例：圓孔尺寸量測", "範例：邊線夾角", "範例：印刷良品比對", "範例：織紋瑕疵檢測",
    "範例：前處理與量測教學", "範例：多圓幾何計數", "範例：顏色有無檢測", "範例：顏色比對",
    "範例：條碼標籤讀取", "範例：定位量測", "範例：杯件量測",
)


def seed_demo() -> list[str]:
    from apps.vision import demo_images

    created: list[str] = []
    for kind in ("source", "asset"):
        ResourceGroup.objects.get_or_create(kind=kind, name="範例")

    source, made = ImageSource.objects.get_or_create(
        name="示範：合成零件",
        defaults={"kind": "synthetic", "group": "範例", "config": {"width": 1280, "height": 960, "pattern": "parts", "seed": 7, "defect_rate": 0.3}},
    )
    if not made and not source.group:
        source.group = "範例"
        source.save(update_fields=["group"])
    created.append(f"影像來源 {source.name}（{'新建' if made else '既有'}）")

    def folder_source(key: str) -> ImageSource:
        folder = demo_images.write_set(key)
        label = demo_images.SAMPLE_SETS[key][0]
        src, made_src = ImageSource.objects.get_or_create(
            name=f"範例：{label}",
            defaults={"kind": "folder", "group": "範例", "config": {"path": folder, "loop": True, "sort": "name"}},
        )
        created.append(f"影像來源 {src.name}（{'新建' if made_src else '既有'}）")
        return src

    def sample_asset(name: str, key: str, region: dict[str, Any] | None) -> str:
        """從樣本圖第 1 張裁一塊存成資產（既有同名資產直接沿用），回傳 asset id。"""
        existing = Asset.objects.filter(name=name, kind="image").first()
        if existing:
            return str(existing.id)
        import os
        import uuid as _uuid

        import cv2
        import numpy as np
        from django.conf import settings

        from apps.vision.tools.roi import crop as roi_crop

        folder = demo_images.write_set(key)
        first = sorted(n for n in os.listdir(folder) if n.endswith(".png"))[0]
        image = cv2.imdecode(np.fromfile(os.path.join(folder, first), dtype=np.uint8), cv2.IMREAD_COLOR)
        piece = roi_crop(image, region, upright=True).image if region else image
        asset_id = _uuid.uuid4()
        path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.png")
        ok, buf = cv2.imencode(".png", piece)
        buf.tofile(path)
        asset = Asset.objects.create(
            id=asset_id, name=name, kind="image", group="範例", path=path, size=int(buf.size),
            meta={"width": int(piece.shape[1]), "height": int(piece.shape[0]), "channels": 3},
        )
        created.append(f"資產 {asset.name}（新建）")
        return str(asset.id)

    # 每個範本畫廊樣板一組樣本來源；範例資產從樣本圖自動裁切（builtin 範本 instantiate 時現查）。
    for key in demo_images.SAMPLE_SETS:
        folder_source(key)
    sample_asset("範例：定位十字範本", "marker_plate", {"shape": "rect", "x": 200, "y": 160, "w": 120, "h": 120})
    sample_asset("範例：杯件定位範本", "cup", {"shape": "rect", "x": 150, "y": 120, "w": 100, "h": 100})
    sample_asset("範例：印刷良品範本", "golden_print", None)
    _seed_demo_models(created)

    # 範例樣板放在「範本畫廊」（BUILTIN_TEMPLATES），不佔流程清單；清掉舊版 seed 建過的流程。
    stale = Flow.objects.filter(name__in=_GALLERY_FLOW_NAMES)
    removed = stale.count()
    if removed:
        stale.delete()
        created.append(f"移除 {removed} 個舊版範例流程（改由範本畫廊提供）")

    specs: list[tuple[str, str, Any, Any]] = [
        ("示範：零件孔數檢測", "灰階→二值化→blob 計數→判定；示範分支與具名輸出", hole_count_flow, source),
        ("示範：曝光檢查", "以 Otsu 門檻判斷曝光是否正常", brightness_gate_flow, source),
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
