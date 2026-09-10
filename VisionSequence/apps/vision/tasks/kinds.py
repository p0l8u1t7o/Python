"""多方式檢測任務：所有方式都產生既有工具與真實接線。"""

from __future__ import annotations

from functools import partial
import math
from typing import Any

from apps.core.errors import ValidationError
from apps.vision.tasks.base import EdgeSpec as E
from apps.vision.tasks.base import FieldSpec, PortRef as P, TaskDefinition, TaskLayout, register
from apps.vision.tools import base as tools
from apps.vision.tools.builtin.polar import geometry_from_region, mapping_dict


def options(*values: str) -> tuple[dict[str, str], ...]:
    return tuple({"value": v, "label": v.replace("_", " ").capitalize()} for v in values)


def field(key: str, label: str, kind: str = "number", **kwargs: Any) -> FieldSpec:
    return FieldSpec(key, label, kind, **kwargs)


def tool_fields(tool: str, role: str, keys: str, *, when: dict | None = None, rename: dict | None = None) -> dict[str, FieldSpec]:
    result = {}
    for param in tools.get(tool).params:
        if param.key not in keys.split():
            continue
        key = (rename or {}).get(param.key, param.key)
        result[key] = FieldSpec(key, param.label, param.kind, role=role, param=param.key,
                                default=param.default, help_text=param.help_text, unit=param.unit,
                                options=tuple(param.options or ()), minimum=param.minimum, maximum=param.maximum,
                                step=param.step, shapes=tuple(param.shapes or ()), accept=param.accept,
                                visible_when=when)
    return result


def roi_field(key: str = "roi", role: str = "", shapes: tuple = ("rect", "rotated_rect"), **kwargs: Any) -> FieldSpec:
    return field(key, "Region" if key == "roi" else f"Region {key[-1].upper()}", "roi", role=role, param="roi", shapes=shapes, **kwargs)


COMMON = {
    "required": field("required", "Required", "boolean", default=True),
    "locator": field("locator", "Locator", "text", default=""),
}
MEASUREMENT = {
    **tool_fields("tolerance_judge", "tol", "nominal upper_tol lower_tol unit name", rename={"name": "result_name"}),
    "unit": field("unit", "Unit", "select", role="tol", param="unit", default="px", options=options("px", "mm")),
    "calibration": field("calibration", "Calibration", "asset", default="", accept="calibration"),
}


def inputs(*roles: str) -> tuple[P, ...]:
    return tuple(P(role, port) for role in roles for port in ("image", "roi", "_transform", "_flow"))


def values(fields: dict, keys: str, **rename: str) -> dict:
    return {rename.get(key, key): fields[key] for key in keys.split() if key in fields}


def publish(params: dict, port: str, name: Any) -> None:
    if str(name or "").strip():
        params["_publish"] = {port: str(name).strip()}


def choice(fields: dict, key: str, allowed: tuple[str, ...]) -> str:
    value = str(fields.get(key) or allowed[0])
    if value not in allowed:
        raise ValidationError(f"Unsupported {key} '{value}'", code="invalid_task_field")
    return value


def distance_layout(f: dict) -> TaskLayout:
    mode = choice(f, "mode", ("edge_pair", "hole_centres"))
    calibrated = bool(f.get("calibration"))
    tol = values(f, "nominal upper_tol lower_tol", result_name="name")
    tol.update(unit="mm" if calibrated else "px", name=f.get("result_name") or "")
    if mode == "edge_pair":
        params = values(f, "roi polarity pair_polarity edge_pair calibration")
        port = P("cal", "width_world" if calibrated else "width")
        steps = {"cal": ("caliper", params), "tol": ("tolerance_judge", tol)}
        edges = ()
        image_roles = ("cal",)
    else:
        port = P("dist", "distance_world" if calibrated else "distance")
        steps = {"find_a": ("find_circle", {"roi": f.get("roi_a"), "edge_select": "last"}),
                 "find_b": ("find_circle", {"roi": f.get("roi_b"), "edge_select": "last"}),
                 "dist": ("distance", {"mode": "centers", "calibration": f.get("calibration") or ""}),
                 "tol": ("tolerance_judge", tol)}
        edges = (E("find_a", "circle", "dist", "a"), E("find_b", "circle", "dist", "b"))
        image_roles = ("find_a", "find_b")
    publish(steps[port.role][1], port.port, f.get("result_name"))
    return TaskLayout(steps, (*edges, E(port.role, port.port, "tol", "value")), inputs(*image_roles),
                      (port, P("tol", "in_spec")), P("tol", "in_spec"), port, "tol", image_roles)


def count_layout(f: dict) -> TaskLayout:
    params = values(f, "roi polarity threshold_method threshold min_area max_area min_circularity")
    # 結果清單至少保留上限之外的一筆，避免截斷後把超量誤判合格。
    params.update(min_count=0, expected="any", max_count=max(5000, int(f.get("max_count", 10)) + 1))
    publish(params, "count", f.get("result_name"))
    return TaskLayout({"blob": ("blob", params), "range": ("in_range", {"low": f.get("min_count", 0), "high": f.get("max_count", 10), "on_false": "reject"})},
                      (E("blob", "count", "range", "value"),), inputs("blob"), (P("blob", "count"), P("range", "result")),
                      P("range", "result"), P("blob", "count"), "range", ("blob",))


def presence_layout(f: dict) -> TaskLayout:
    method = choice(f, "method", ("template", "blob", "print"))
    tool = {"template": "template_match", "blob": "blob", "print": "text_presence"}[method]
    params = values(f, "roi expected")
    if method == "template":
        params.update(values(f, "template_images threshold", template_images="templates"))
    elif method == "blob":
        params.update(values(f, "min_area max_area polarity threshold_method blob_threshold", blob_threshold="threshold"))
        params["min_count"] = 0
    else:
        params.update(values(f, "min_ratio max_ratio print_polarity", print_polarity="polarity"))
    return TaskLayout({"det": (tool, params)}, inputs=inputs("det"), outputs=(P("det", "detected"), P("det", "valid")),
                      pass_port=P("det", "valid"), value_port=P("det", "detected"), verdict_role="det", locator_roles=("det",),
                      summary_expression=f"a and b == {f.get('expected', 'present') == 'present'}", summary_inputs=(P("det", "valid"), P("det", "detected")))


def circular_layout(f: dict) -> TaskLayout:
    region = f.get("roi") or {"shape": "annulus", "cx": 0, "cy": 0, "r_inner": 10, "r_outer": 30}
    if region.get("shape") not in ("annulus", "circle"):
        region = {"shape": "annulus", "cx": 0, "cy": 0, "r_inner": 10, "r_outer": 30}
    cx, cy, ri, ro, a0, a1 = geometry_from_region(region)
    # 假設 #3～#5：0.5°／1 px 展開、逐欄卡尺、封閉分段；真引擎測接縫、扇形與位置修正。
    mapping = mapping_dict(cx, cy, ri, ro, a0=a0, a1=a1, start_angle=f.get("start_angle", 0), direction=f.get("direction", "cw"), step_deg=.5, radial_step=1)
    width = mapping["width"]
    closed = not mapping["sector"]
    minimum = float(f.get("min_length", 1))
    edge_params = values(f, "threshold max_defects")
    edge_params.update(roi={"shape": "rect", "x": 0, "y": (ro - ri) / 2 - 10, "w": width if closed else max(1, width - 1), "h": 20},
                       calipers=width, caliper_width=1, search=f.get("search", 35), edge_threshold=20,
                       polarity=f.get("polarity", "light_to_dark"), closed_sequence=closed,
                       filter_fractures=True, min_width=minimum / .5, direction=f.get("defect_direction", "both"), baseline="reference")
    publish(edge_params, "count", f.get("result_name"))
    steps = {"unwrap": ("polar_unwrap", {**values(f, "roi start_angle direction"), "angle_step": "0.5"}),
                       "defect": ("edge_defect", edge_params), "geom": ("defects_to_geometry", {"output": f.get("geometry", "centres")}),
                       "restore": ("polar_restore", {})}
    extra = ()
    if f.get("unit") == "mm":
        if not f.get("calibration"):
            raise ValidationError("Millimetre mode needs a calibration", code="missing_calibration")
        # 弧長定義在教導環域的中線半徑；標定倍率由執行時的既有工具讀取，不在翻譯器查資料庫。
        arc = (ri + ro) / 2 * math.radians(.5)
        steps.update(length=("formula", {"expression": str(minimum)}),
                     scale=("calibration", {"mode": "asset", "calibration": f["calibration"]}),
                     limit=("formula", {"expression": f"a / (b * {arc!r})"}))
        extra = (E("length", "value", "scale", "value"), E("length", "value", "limit", "a"),
                 E("scale", "scale", "limit", "b"), E("limit", "value", "defect", "param:min_width"))
    return TaskLayout(steps,
                      (*extra, E("unwrap", "image", "defect", "image"), E("defect", "defects", "geom", "defects"),
                       E("geom", "points", "restore", "points"), E("geom", "contours", "restore", "contours"), E("unwrap", "mapping", "restore", "mapping"),
                       E("defect", "ok", "restore", "_flow"), E("defect", "defect", "restore", "_flow")),
                      (*inputs("unwrap"), P("restore", "image")), (P("defect", "count"), P("restore", "points"), P("restore", "contours")),
                      value_port=P("defect", "count"), verdict_role="defect", locator_roles=("unwrap",),
                      summary_expression=f"a <= {int(f.get('max_defects', 0))}", summary_inputs=(P("defect", "count"),))


def defect_layout(f: dict) -> TaskLayout:
    method = choice(f, "method", ("simple", "freeform"))
    params = values(f, "roi mode threshold min_width max_defects direction width_min width_max polarity search pair_polarity")
    external = ()
    if method == "simple":
        tool = "edge_defect"
        params.update(values(f, "baseline"))
        reference = f.get("reference")
        if isinstance(reference, dict) and reference.get("node_id") and reference.get("port"):
            port = reference.get("type", "line")
            if port not in ("line", "circle"):
                raise ValidationError("Select a line or circle source", code="invalid_task_field")
            external = ({"source": reference["node_id"], "port": reference["port"], "role": "defect", "input": port},)
    else:
        tool = "edge_model_defect"
        params.update(values(f, "model"))
    return TaskLayout({"defect": (tool, params)}, inputs=(*inputs("defect"), P("defect", "line"), P("defect", "circle")) if method == "simple" else inputs("defect"),
                      outputs=(P("defect", "count"), P("defect", "defects")), value_port=P("defect", "count"), verdict_role="defect", locator_roles=("defect",),
                      summary_expression=f"a <= {int(f.get('max_defects', 0))}", summary_inputs=(P("defect", "count"),), external=external)


def read_layout(f: dict) -> TaskLayout:
    mode = choice(f, "mode", ("code", "text"))
    if mode == "code":
        params = values(f, "roi types expected")
        publish(params, "first", f.get("result_name"))
        expected = str(f.get("expected") or "")
        return TaskLayout({"read": ("barcode", params)}, inputs=inputs("read"), outputs=(P("read", "first"), P("read", "count")),
                          value_port=P("read", "first"), verdict_role="read", locator_roles=("read",),
                          summary_expression="a > 0" + (f" and b == {expected!r}" if expected else ""), summary_inputs=(P("read", "count"), P("read", "first")))
    params = values(f, "roi charset custom_charset polarity min_confidence pattern font_model", font_model="model")
    publish(params, "text", f.get("result_name"))
    return TaskLayout({"read": ("ocr_read", params), "verify": ("ocv_verify", {**values(f, "expected verify_mode", verify_mode="mode"), "expected_source": "param"})},
                      (E("read", "text", "verify", "text"), E("read", "items", "verify", "items")),
                      (*inputs("read"), P("verify", "image")), (P("read", "text"), P("verify", "match")),
                      P("verify", "match"), P("read", "text"), "verify", ("read",))


def locate_layout(f: dict) -> TaskLayout:
    method = choice(f, "method", ("template", "shape", "register"))
    rotation = bool(f.get("allow_rotation"))
    angle = float(f.get("angle_range") or 0) if rotation else 0
    steps = {"align": ("shape_align", {**values(f, "ref_x ref_y ref_angle"), "use_angle": rotation})}
    edges = (E("find", "matches", "align", "matches"),)
    params = {"roi": f.get("roi")}
    if method == "template":
        tool = "template_match"
        steps["ref"] = ("fixed_image", {"images": f.get("template_images") or [], "mode": "fixed", "index": 1, "role": "reference"})
        params.update(threshold=f.get("threshold", .7), angle_range=angle, expected="present", refine_rotation=rotation)
        edges = (E("ref", "image", "find", "template_image"), *edges)
    elif method == "shape":
        tool = "shape_match"
        # 既有搜尋器不接受零寬角度區間；停用旋轉時用最窄區間，補正仍明確停用角度。
        params.update(model=f.get("model") or "", model_source="asset", min_score=f.get("threshold", .7), angle_start=-angle, angle_extent=max(.1, 2 * angle))
    else:
        tool = "register_detect"
        params.update(registrations=f.get("template_images") or [], min_similarity=f.get("threshold", .7), angle_range=angle, mode="detect", expected="present", max_count=1)
    steps["find"] = (tool, params)
    return TaskLayout(steps, edges, (P("find", "image"),), (P("find", "found"), P("align", "transform")), value_port=P("align", "transform"), verdict_role="find",
                      summary_expression="a > 0", summary_inputs=(P("find", "count"),))


LAYOUTS = {"measure_distance": distance_layout, "count_objects": count_layout, "check_presence": presence_layout,
           "inspect_circular_surface": circular_layout, "inspect_edge_defect": defect_layout, "read_and_verify": read_layout, "locate_part": locate_layout}


def read_fields(kind: str, f: dict, nodes: dict, edges: list[dict]) -> None:
    """方式從實際工具與角色讀回，參數仍以節點為唯一事實來源。"""
    def params(role: str) -> dict:
        return (nodes.get(role) or {}).get("params") or {}

    if kind == "measure_distance":
        f["mode"] = "hole_centres" if "find_a" in nodes or "dist" in nodes else "edge_pair"
        f["calibration"] = params("dist" if f["mode"] == "hole_centres" else "cal").get("calibration", "")
    elif kind == "check_presence":
        f["method"] = {"template_match": "template", "blob": "blob", "text_presence": "print"}.get((nodes.get("det") or {}).get("type"), "template")
        p = params("det")
        if f["method"] == "template":
            f["template_images"] = p.get("templates", [])
        elif f["method"] == "blob":
            f["blob_threshold"] = p.get("threshold", 128)
        else:
            f["print_polarity"] = p.get("polarity", "dark")
    elif kind == "inspect_edge_defect":
        f["method"] = "freeform" if (nodes.get("defect") or {}).get("type") == "edge_model_defect" else "simple"
        f["reference"] = next(({"node_id": e["source"], "port": e["source_handle"], "type": e["target_handle"]} for e in edges
                               if e.get("target") == (nodes.get("defect") or {}).get("id") and e.get("target_handle") in ("line", "circle")), None)
    elif kind == "read_and_verify":
        f["mode"] = "text" if (nodes.get("read") or {}).get("type") == "ocr_read" else "code"
        f["expected"] = params("verify" if f["mode"] == "text" else "read").get("expected", "")
    elif kind == "locate_part":
        f["method"] = {"template_match": "template", "shape_match": "shape", "register_detect": "register"}.get((nodes.get("find") or {}).get("type"), "template")
        p = params("find")
        f["allow_rotation"] = bool(params("align").get("use_angle", False))
        f["threshold"] = p.get({"template": "threshold", "shape": "min_score", "register": "min_similarity"}[f["method"]], .7)
        f["angle_range"] = (p.get("angle_extent", 0) / 2 if f["allow_rotation"] else 0) if f["method"] == "shape" else p.get("angle_range", 0)
        if f["method"] == "register":
            f["template_images"] = p.get("registrations", [])
    elif kind == "inspect_circular_surface":
        f["unit"] = "mm" if "scale" in nodes else "deg"
        f["calibration"] = params("scale").get("calibration", "")
        f["min_length"] = float(params("length").get("expression", "1")) if "length" in nodes else float(params("defect").get("min_width", 2)) * .5
    layout = LAYOUTS[kind](f)
    if "result_name" in f and layout.value_port:
        ref = layout.value_port
        f["result_name"] = (params(ref.role).get("_publish") or {}).get(ref.port, f["result_name"])


def add(kind: str, label: str, fields: dict[str, FieldSpec]) -> None:
    defaults = {k: v.default for k, v in fields.items()}
    layout = LAYOUTS[kind](defaults)
    register(TaskDefinition(kind, 1, label, f"Configure and run {label.lower()} using the current image.",
                            roles={r: t for r, (t, _) in layout.steps.items()}, internal_edges=layout.edges,
                            fields={**fields, **COMMON}, public_inputs=layout.inputs, public_outputs=layout.outputs,
                            pass_port=layout.pass_port, layout_hook=LAYOUTS[kind], read_hook=partial(read_fields, kind)))


add("measure_distance", "Measure distance", {
    "mode": field("mode", "Mode", "select", default="edge_pair", options=options("edge_pair", "hole_centres")),
    "roi": roi_field(role="cal", required=True, visible_when={"mode": "edge_pair"}),
    "roi_a": roi_field("roi_a", "find_a", ("annulus", "circle", "rect"), required=True, visible_when={"mode": "hole_centres"}),
    "roi_b": roi_field("roi_b", "find_b", ("annulus", "circle", "rect"), required=True, visible_when={"mode": "hole_centres"}),
    **tool_fields("caliper", "cal", "polarity pair_polarity edge_pair", when={"mode": "edge_pair"}), **MEASUREMENT,
})
add("count_objects", "Count objects", {
    "roi": roi_field(role="blob"), **tool_fields("blob", "blob", "polarity threshold_method threshold min_area max_area min_circularity"),
    "min_count": field("min_count", "Minimum count", role="range", param="low", default=0, minimum=0),
    "max_count": field("max_count", "Maximum count", role="range", param="high", default=10, minimum=0),
    "result_name": field("result_name", "Result name", "output_key", default="count"),
})
add("check_presence", "Check presence", {
    "method": field("method", "Method", "select", default="template", options=options("template", "blob", "print")),
    "roi": roi_field(role="det"),
    "expected": field("expected", "Expected", "select", role="det", param="expected", default="present", options=options("present", "absent")),
    "template_images": field("template_images", "Reference pictures", "images", required=True, default=[], visible_when={"method": "template"}),
    **tool_fields("template_match", "det", "threshold", when={"method": "template"}),
    **tool_fields("blob", "det", "min_area max_area polarity threshold_method threshold", when={"method": "blob"}, rename={"threshold": "blob_threshold"}),
    **tool_fields("text_presence", "det", "min_ratio max_ratio polarity", when={"method": "print"}, rename={"polarity": "print_polarity"}),
})
add("inspect_circular_surface", "Inspect circular surface", {
    "roi": roi_field(role="unwrap", shapes=("annulus",), required=True),
    **tool_fields("polar_unwrap", "unwrap", "start_angle direction"),
    **tool_fields("edge_defect", "defect", "threshold max_defects polarity"),
    "threshold": field("threshold", "Defect threshold", role="defect", param="threshold", default=3, minimum=0, unit="px"),
    "min_length": field("min_length", "Minimum defect length", default=1, minimum=0, help_text="Applies to every fault, including gaps. Arc length uses the midpoint radius of the taught ring."),
    "unit": field("unit", "Length unit", "select", default="deg", options=options("deg", "mm")),
    "calibration": field("calibration", "Calibration", "asset", default="", accept="calibration"),
    "defect_direction": field("defect_direction", "Defect direction", "select", role="defect", param="direction", default="inward", options=options("both", "inward", "outward")),
    "result_name": field("result_name", "Result name", "output_key", default="defects"),
    "polarity": field("polarity", "Edge polarity", "select", role="defect", param="polarity", default="light_to_dark", options=options("any", "dark_to_light", "light_to_dark")),
    "search": field("search", "Search range", role="defect", param="search", default=35, minimum=2, maximum=2000, unit="px"),
    "geometry": field("geometry", "Defect geometry", "select", role="geom", param="output", default="centres", options=options("centres", "boxes", "spans")),
})
add("inspect_edge_defect", "Inspect edge defect", {
    "method": field("method", "Method", "select", default="simple", options=options("simple", "freeform")),
    "roi": roi_field(role="defect", shapes=("rect", "rotated_rect", "circle", "annulus")),
    "reference": field("reference", "Reference geometry", "json", source_type="geometry", visible_when={"method": "simple"}, help_text="Optional line or circle source. A connected source takes precedence over the drawn region."),
    **tool_fields("edge_defect", "defect", "mode threshold min_width direction max_defects width_min width_max polarity search pair_polarity"),
    **tool_fields("edge_defect", "defect", "baseline", when={"method": "simple"}),
    "model": field("model", "Taught outline", "json", role="defect", param="model", required=True, visible_when={"method": "freeform"}),
})
add("read_and_verify", "Read and verify", {
    "mode": field("mode", "Mode", "select", default="code", options=options("code", "text")),
    "roi": roi_field(role="read"), **tool_fields("barcode", "read", "types", when={"mode": "code"}),
    "expected": field("expected", "Expected text", "text", default=""),
    **tool_fields("ocr_read", "read", "charset custom_charset polarity min_confidence pattern model", when={"mode": "text"}, rename={"model": "font_model"}),
    **tool_fields("ocv_verify", "verify", "mode", when={"mode": "text"}, rename={"mode": "verify_mode"}),
    "result_name": field("result_name", "Result name", "output_key", default="text"),
})
