"""檢測任務的說明文字（產品表面英文；中文由前端 catalogue 字典疊上去）。

第二輪體檢（PM-REVIEW-R2 A3／L-3）：八種任務裡六種的說明原本是同一句罐頭文案「Configure and run … using the
current image」，欄位也大多沒有說明，現場 AE 無從判斷該選哪一種。這裡集中放每種任務「什麼時候用它」與每個欄位的
一句說明；``register()`` 在登記時把空的補上（工具本身帶的 help_text 保留不動）。
"""
from __future__ import annotations

#: 每種任務「什麼時候用它」
KIND_HELP: dict[str, str] = {
    "check_presence": "Check that a part or feature is there - or not there - by matching a reference picture, finding a bright or dark object, or detecting printed text. Use it for missing screws, labels, caps and prints.",
    "count_objects": "Count the bright or dark objects in the region and check the count against a minimum and a maximum. Use it for pins, holes, pills and pieces in a tray.",
    "inspect_circular_surface": "Unwrap a ring (cup rim, bottle mouth, bearing race) into a strip and look for chips, gaps and burrs along its edge.",
    "inspect_edge_defect": "Follow a straight edge, an arc or a taught outline with calipers and report where the real edge deviates: nicks, burrs and gaps, and for seals the band width.",
    "measure_distance": "Measure the width between two edges, or the distance between two hole centres, and check it against a nominal value and tolerances.",
    "read_and_verify": "Read a barcode, a 2D code or printed text in the region and check it against the expected content.",
}

#: 依欄位鍵的通用說明（同一個鍵在各種任務裡意思相同時）
GENERIC_FIELD_HELP: dict[str, str] = {
    "roi": "Draw the region to inspect on the image; keep it tight around the feature so the background does not interfere.",
    "required": "Required tasks are included in the inspection summary; an unmet required task makes the run NG.",
    "locator": "Optional locate task; its position correction is applied to this task's region.",
    "result_name": "Name used in run outputs (letters, digits and underscore).",
    "threshold_method": "How pixels are split into object and background; Auto suits most lighting.",
    "min_area": "Objects smaller than this are ignored (pixels).",
    "max_area": "0 means no limit.",
    "nominal": "The target value from the drawing.",
    "upper_tol": "Signed; the upper limit is nominal + this.",
    "lower_tol": "Signed, normally negative; the lower limit is nominal + this.",
    "unit": "Pixels, or millimetres with a calibration.",
    "calibration": "Optional. Leave blank to measure in pixels.",
    "search": "How far either side of the ideal edge each caliper looks (px).",
    "max_defects": "0 = any fault is a reject.",
    "pair_polarity": "Whether the band between the two edges is brighter or darker than its surroundings.",
}

#: 依（任務, 欄位）的專屬說明（同一個鍵在不同任務裡意思不同時）
FIELD_HELP: dict[tuple[str, str], str] = {
    # 量直徑
    ("measure_diameter", "mode"): "Check the diameter against a specification, or the roundness of the edge.",
    ("measure_diameter", "edge"): "Measure the outer or the inner edge of the ring.",
    ("measure_diameter", "polarity"): "Which brightness transition counts as the edge, scanning outward from the centre.",
    ("measure_diameter", "num_rays"): "Number of scan lines around the circle; more lines give a steadier fit but take longer.",
    # 定位工件
    ("locate_part", "method"): "Template: match a cropped picture of the mark. Shape: an edge-based shape model. Register: a registered reference picture.",
    ("locate_part", "model"): "Shape model asset taught from the mark.",
    ("locate_part", "threshold"): "Minimum match score 0-1; below this the part counts as not located.",
    ("locate_part", "allow_rotation"): "Also search rotated positions; slower, but needed when the part can turn.",
    ("locate_part", "angle_range"): "Maximum rotation to search, in degrees either way.",
    ("locate_part", "ref_x"): "Taught X position of the mark; set by Teach pose after a trial run.",
    ("locate_part", "ref_y"): "Taught Y position of the mark; set by Teach pose after a trial run.",
    ("locate_part", "ref_angle"): "Taught angle of the mark; set by Teach pose after a trial run.",
    # 檢查有無
    ("check_presence", "method"): "Template: match a reference picture. Blob: look for a bright or dark object. Print: look for printed text.",
    ("check_presence", "expected"): "Present: the item must be found. Absent: finding it is NG.",
    ("check_presence", "template_images"): "Pictures of the item to look for, cropped from a good part.",
    ("check_presence", "blob_threshold"): "Grey level for the fixed method (0-255); ignored by Auto.",
    ("check_presence", "polarity"): "Whether the object is brighter or darker than the background.",
    ("check_presence", "print_polarity"): "Dark print on a light background, or light print on dark.",
    ("check_presence", "min_ratio"): "Minimum ink coverage of the region for print to count as present.",
    # 計數
    ("count_objects", "threshold"): "Grey level for the fixed method (0-255); ignored by Auto.",
    ("count_objects", "polarity"): "Whether the objects are brighter or darker than the background.",
    ("count_objects", "min_circularity"): "4πA/P², 1 for a perfect circle; raise it to exclude elongated shapes.",
    ("count_objects", "min_count"): "Fewer objects than this is NG.",
    ("count_objects", "max_count"): "More objects than this is NG.",
    # 圓周表面
    ("inspect_circular_surface", "roi"): "Draw an annulus that covers the ring edge; the inner and outer radii bound the search.",
    ("inspect_circular_surface", "polarity"): "Brightness transition of the ring edge along the scan.",
    ("inspect_circular_surface", "threshold"): "How far the edge may deviate from the ideal ring before it counts as a fault (px).",
    ("inspect_circular_surface", "unit"): "Degrees along the ring, or millimetres with a calibration.",
    ("inspect_circular_surface", "defect_direction"): "Inward = missing material (chips, gaps); outward = extra material (burrs).",
    ("inspect_circular_surface", "geometry"): "How each fault is reported for downstream steps: centre point, bounding box or start/end span.",
    # 邊緣缺陷
    ("inspect_edge_defect", "method"): "Simple: a straight or arc edge from the drawn region or a connected line/circle. Freeform: an outline taught from a good part.",
    ("inspect_edge_defect", "mode"): "Single: one edge. Pair: two parallel edges and the band between them (seals, glue bead).",
    ("inspect_edge_defect", "polarity"): "Which brightness transition counts as the edge, scanning across it.",
    ("inspect_edge_defect", "direction"): "Which side of the ideal edge counts as a fault.",
    ("inspect_edge_defect", "model"): "Outline taught from a good part; teach it from the current image.",
    # 量邊距
    ("measure_distance", "mode"): "Edge pair: the width between two edges inside one region. Hole centres: the distance between the centres of two holes found in regions A and B.",
    ("measure_distance", "roi_a"): "Circular or annular region around hole A.",
    ("measure_distance", "roi_b"): "Circular or annular region around hole B.",
    ("measure_distance", "polarity"): "Which brightness transition counts as an edge along the scan.",
    ("measure_distance", "edge_pair"): "Which pair of edges to measure when several are found in the region.",
    # 讀取與驗證
    ("read_and_verify", "mode"): "Code: read a barcode or 2D code. Text: read printed characters.",
    ("read_and_verify", "types"): "Restrict decoding to one code family for speed and fewer false reads.",
    ("read_and_verify", "expected"): "The text the read must match; blank means any successful read passes.",
    ("read_and_verify", "charset"): "Characters that may appear; restricting it improves accuracy.",
    ("read_and_verify", "polarity"): "Dark characters on a light background, or light on dark.",
    ("read_and_verify", "verify_mode"): "Exact: identical. Contains: the expected text appears inside the read. Regex: a regular expression.",
}

CANNED_PREFIX = "Configure and run "


def kind_help(kind: str, current: str) -> str:
    """罐頭文案換成真正的說明；已經有人寫過的不動。"""
    if current and not current.startswith(CANNED_PREFIX):
        return current
    return KIND_HELP.get(kind, current)


def field_help(kind: str, key: str, current: str) -> str:
    """欄位沒有說明時補一句；工具本身帶的說明保留。"""
    if current:
        return current
    return FIELD_HELP.get((kind, key)) or GENERIC_FIELD_HELP.get(key, "")
