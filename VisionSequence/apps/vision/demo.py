"""示範流程（程式化產生，經 validate_graph 後寫入）。

節點用 _node / _edge helper 建，座標以 300×170 網格排，讓畫布一開就整齊。
示範流程只用「一定存在」的內建工具（source / preprocess / logic / output 與 detect.blob）。
"""

from __future__ import annotations

from typing import Any

from apps.vision.graph import validate_graph
from apps.vision.models import Flow, ImageSource
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


def locate_measure_flow(source_id: Any) -> dict[str, Any]:
    """定位＋卡尺：範本比對（範本資產由使用者設定）→ 定位補正 → ROI 跟隨 → 卡尺寬度 → 公差。"""
    nodes = [
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("tm", "template_match", 2, 0, "找定位範本", threshold=0.6, max_matches=1),
        _node("align", "shape_align", 3, 0, "定位補正", ref_x=640, ref_y=480, ref_angle=0),
        _node("fix", "fixture_roi", 4, 0, "ROI 跟隨", roi={"shape": "rotated_rect", "cx": 640, "cy": 480, "w": 400, "h": 60, "angle": 0}),
        _node("cal", "caliper", 5, 0, "卡尺量寬", polarity="any", edge_pair="widest"),
        _node("rng", "in_range", 6, 0, "寬度公差", low=100, high=900),
        _node("ok", "judge", 7, 0, "OK", verdict="ok"),
        _node("ng", "judge", 7, 1, "NG：寬度超差", verdict="ng", label="width"),
        _node("out", "output", 6, 1, "輸出寬度", name="width_px"),
        _node("nf", "judge", 3, 1, "NG：找不到範本", verdict="ng", label="not_found"),
        _note("n1", 0, 1, "使用方式", "1. 在「找定位範本」工具頁按「從目前影像框選建立範本」。\n2. 試跑一次後把 shape_align 的參考位置設成目前匹配位置。\n3. 把 ROI 跟隨的區域畫在要量測的邊緣上。"),
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


def cup_measure_flow(source_id: Any) -> dict[str, Any]:
    """深抽杯件量測：定位 → ROI 跟隨 ×3 → 外徑／內徑找圓 + 壁厚 → 同心度 → 公差判定 ×3 → 具名輸出 → 判定。

    教導步驟（現場調機時照順序做，數值參數都已標 teach，可在參數卡頁一次調完）：
    1. 「找定位範本」：從目前影像框選杯口特徵建立範本；調分數門檻（threshold）。
    2. 試跑一次，把「定位補正」的 ref_x/ref_y/ref_angle 設成目前匹配位置（前端一鍵帶入）。
    3. 三個「ROI 跟隨」：外徑環畫在杯口外緣附近、內徑環畫在內緣附近、壁厚矩形橫跨杯壁剖面（長邊沿壁）。
    4. 找圓／壁厚的 edge_threshold、polarity 依實際對比調到邊緣點穩定。
    5. 三個「公差判定」填圖面標稱值與上下偏差（單位 px；若要 mm，在前面接「像素校正」）、圖面出處。
    6. 「同心度」的 max_deviation 依圖面同心度公差 /2 填入（同心度 = 2×圓心偏移）。
    """
    od_roi = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 300, "r_outer": 380}
    id_roi = {"shape": "annulus", "cx": 640, "cy": 480, "r_inner": 220, "r_outer": 300}
    wall_roi = {"shape": "rotated_rect", "cx": 960, "cy": 480, "w": 120, "h": 80, "angle": 90}
    nodes = [
        _node("src", "image_source", 0, 0, "取像", source_id=source_id),
        _node("gray", "grayscale", 1, 0, "灰階"),
        _node("tm", "template_match", 2, 0, "找定位範本", threshold=0.6, max_matches=1, angle_range=10, angle_step=2),
        _node("align", "shape_align", 3, 0, "定位補正", ref_x=640, ref_y=480, ref_angle=0),
        _node("nf", "judge", 3, 1, "NG：找不到範本", verdict="ng", label="not_found"),
        _node("fix_od", "fixture_roi", 4, 0, "外徑 ROI 跟隨", roi=od_roi),
        _node("fix_id", "fixture_roi", 4, 1, "內徑 ROI 跟隨", roi=id_roi),
        _node("fix_wall", "fixture_roi", 4, 2, "壁厚 ROI 跟隨", roi=wall_roi),
        _node("od", "find_circle", 5, 0, "外徑找圓", polarity="any", edge_threshold=20, num_rays=72, edge_select="last"),
        _node("idc", "find_circle", 5, 1, "內徑找圓", polarity="any", edge_threshold=20, num_rays=72, edge_select="first"),
        _node("wall", "wall_thickness", 5, 2, "壁厚", polarity="any", edge_threshold=20, num_calipers=10),
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
        _note("n1", 0, 1, "教導步驟", "1. 找定位範本：框選杯口特徵建範本。\n2. 試跑後把定位補正的參考位置設成目前匹配。\n3. 三個 ROI 跟隨：外徑環、內徑環、壁厚矩形（長邊沿壁）。\n4. 公差判定填圖面標稱值／上下偏差／出處；同心度填 max_deviation。"),
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
        _node("mask", "color_range", 1, 0, "目標色遮罩", h_low=0, h_high=179, s_low=0, s_high=60, v_low=150, v_high=255),
        _node("cnt", "pixel_count", 2, 0, "計數", min_count=1000),
        _node("cmp", "if_number", 3, 0, "夠多嗎？", operator="ge", threshold=1000),
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


def seed_demo() -> list[str]:
    created: list[str] = []
    source, made = ImageSource.objects.get_or_create(
        name="示範：合成零件",
        defaults={"kind": "synthetic", "config": {"width": 1280, "height": 960, "pattern": "parts", "seed": 7, "defect_rate": 0.3}},
    )
    created.append(f"影像來源 {source.name}（{'新建' if made else '既有'}）")
    for name, desc, builder in (
        ("示範：零件孔數檢測", "灰階→二值化→blob 計數→判定；示範分支與具名輸出", hole_count_flow),
        ("示範：曝光檢查", "以 Otsu 門檻判斷曝光是否正常", brightness_gate_flow),
    ):
        graph = validate_graph(builder(source.id))
        flow, made = Flow.objects.get_or_create(name=name, defaults={"description": desc, "graph": graph})
        if not made:
            flow.graph = graph
            flow.version += 1
            flow.save()
        created.append(f"流程 {flow.name}（{'新建' if made else '已更新'}，id={flow.id}）")
    return created
