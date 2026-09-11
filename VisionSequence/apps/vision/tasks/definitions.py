"""第一版檢測任務定義。"""

from __future__ import annotations

from functools import partial
from typing import Any

from apps.core.errors import ValidationError
from apps.vision.tasks.base import ALIAS_KEY, EdgeSpec, FieldSpec, PortRef, TaskDefinition, edge, register, task_fields, task_node
from apps.vision.tasks.kinds import locate_layout, read_fields

EDGE_OPTIONS = (
    {"value": "outer", "label": "Outer edge"},
    {"value": "inner", "label": "Inner edge"},
)
UNIT_OPTIONS = (
    {"value": "px", "label": "Pixels"},
    {"value": "mm", "label": "Millimetres"},
)
LOCATE_METHOD_OPTIONS = (
    {"value": "template", "label": "Template"},
    {"value": "shape", "label": "Shape model"},
    {"value": "register", "label": "Registered examples"},
)


def _edge_select(value: Any) -> str:
    # 實測與工具宣告一致：環形 ROI 從中心往外掃，first 是內緣，last 是外緣。
    return "first" if str(value or "outer") == "inner" else "last"


def _edge_name(params: dict[str, Any]) -> str:
    return "inner" if params.get("edge_select") == "first" else "outer"


def _publish(params: dict[str, Any], key: str, name: Any) -> None:
    """輸出埠 → 具名輸出名稱；task_node() 會把保留鍵 _alias 搬成 node.interface.outputs[].alias。"""
    text = str(name or "").strip()
    if text:
        params[ALIAS_KEY] = {key: text}
    else:
        params.pop(ALIAS_KEY, None)


def _measure_edges(definition: TaskDefinition, fields: dict[str, Any]) -> tuple[EdgeSpec, ...]:
    if str(fields.get("mode") or "check") == "roundness":
        edges = (EdgeSpec("find", "points", "tol", "points"),)
        if fields.get("unit") == "mm":
            edges += (EdgeSpec("find", "points", "scale", "points"), EdgeSpec("scale", "scale", "tol", "scale"))
        return edges
    port = "diameter_world" if fields.get("calibration") else "diameter"
    return (EdgeSpec("find", port, "tol", "value"),)


def _measure_build(definition: TaskDefinition, task: dict[str, Any], ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields = task_fields(task, definition)
    if fields.get("calibration"):
        fields["unit"] = "mm"
    if fields.get("unit") == "mm" and not fields.get("calibration"):
        raise ValidationError("Millimetre mode needs a calibration", code="missing_calibration")
    task_id = str(task.get("task_id") or task.get("id") or "diameter")
    required = bool(task.get("required", fields.get("required", True)))
    mode = str(fields.get("mode") or "check")
    find_params = definition.default_params("find")
    find_params.update({
        "roi": fields["roi"],
        "edge_select": _edge_select(fields.get("edge")),
        "polarity": fields.get("polarity") or "any",
        "calibration": fields.get("calibration") or "",
        "num_rays": int(fields.get("num_rays") or 72),
    })
    _publish(find_params, "diameter_world" if fields.get("calibration") else "diameter", fields.get("result_name"))
    tol_tool = "gdt_measure" if mode == "roundness" else "tolerance_judge"
    if mode == "roundness":
        # 保留直徑規格，切回直徑時仍可讀回原本的標稱值與名稱。
        tol_params = {"mode": "roundness", "tolerance": fields.get("upper_tol", 1), "unit": fields.get("unit") or "px",
                      "nominal": fields.get("nominal"), "lower_tol": fields.get("lower_tol"), "name": fields.get("result_name") or ""}
    else:
        tol_params = {
            "nominal": fields.get("nominal"),
            "upper_tol": fields.get("upper_tol"),
            "lower_tol": fields.get("lower_tol"),
            "unit": fields.get("unit") or "px",
            "name": fields.get("result_name") or "",
        }
    nodes = [
        task_node(task_id, "find", "find_circle", find_params, definition.kind, definition.version, required),
        task_node(task_id, "tol", tol_tool, tol_params, definition.kind, definition.version, required),
    ]
    if mode == "roundness" and fields.get("unit") == "mm":
        nodes.append(task_node(task_id, "scale", "calibration", {"mode": "asset", "calibration": fields["calibration"]}, definition.kind, definition.version, required))
    return nodes, [edge(f"{task_id}_{e.source_role}", e.source_port, f"{task_id}_{e.target_role}", e.target_port) for e in _measure_edges(definition, fields)]


register(TaskDefinition(
    kind="measure_diameter",
    version=1,
    label="Measure diameter",
    help_text="Find a circular edge and check the measured diameter or roundness against a specification.",
    roles={"find": "find_circle", "tol": "tolerance_judge"},
    internal_edges=(EdgeSpec("find", "diameter", "tol", "value"),),
    edges_hook=_measure_edges,
    fields={
        "mode": FieldSpec("mode", "Mode", "select", default="check", options=({"value": "check", "label": "Diameter"}, {"value": "roundness", "label": "Roundness"})),
        "roi": FieldSpec("roi", "Region", "roi", role="find", param="roi", required=True, shapes=("annulus", "circle", "rect"), help_text="Draw a circular or annular search region around the edge."),
        "edge": FieldSpec("edge", "Measured edge", "select", role="find", param="edge_select", default="outer", options=EDGE_OPTIONS, read=_edge_name, write=lambda p, v: p.__setitem__("edge_select", _edge_select(v))),
        "polarity": FieldSpec("polarity", "Edge polarity", "select", role="find", param="polarity", default="any", options=({"value": "any", "label": "Any"}, {"value": "dark_to_light", "label": "Dark to light"}, {"value": "light_to_dark", "label": "Light to dark"})),
        "calibration": FieldSpec("calibration", "Calibration", "asset", role="find", param="calibration", default="", accept="calibration", help_text="Optional. Leave blank to measure in pixels."),
        "nominal": FieldSpec("nominal", "Nominal", "number", role="tol", param="nominal", required=True, default=100, unit=""),
        "upper_tol": FieldSpec("upper_tol", "Upper tolerance", "number", role="tol", param="upper_tol", required=True, default=1),
        "lower_tol": FieldSpec("lower_tol", "Lower tolerance", "number", role="tol", param="lower_tol", required=True, default=-1),
        "unit": FieldSpec("unit", "Unit", "select", role="tol", param="unit", required=True, default="px", options=UNIT_OPTIONS),
        "result_name": FieldSpec("result_name", "Result name", "output_key", role="tol", param="name", default="diameter", help_text="Name used in run outputs."),
        "required": FieldSpec("required", "Required", "boolean", default=True, help_text="Required tasks are included in the inspection summary."),
        "locator": FieldSpec("locator", "Locator", "text", default="", help_text="Optional locate task id used for position correction."),
        "num_rays": FieldSpec("num_rays", "Scan lines", "number", role="find", param="num_rays", default=72, minimum=6, maximum=720),
    },
    public_inputs=(PortRef("find", "image"), PortRef("find", "roi"), PortRef("find", "_transform"), PortRef("find", "_flow")),
    public_outputs=(PortRef("find", "diameter"), PortRef("find", "diameter_world"), PortRef("tol", "in_spec"), PortRef("tol", "verdict")),
    pass_port=PortRef("tol", "in_spec"),
    build_hook=_measure_build,
))

register(TaskDefinition(
    kind="locate_part",
    version=1,
    label="Locate part",
    help_text="Find a taught template and publish a position correction transform for downstream tasks.",
    roles={"ref": "fixed_image", "find": "template_match", "align": "shape_align"},
    internal_edges=(EdgeSpec("ref", "image", "find", "template_image"), EdgeSpec("find", "matches", "align", "matches")),
    fields={
        "method": FieldSpec("method", "Method", "select", default="template", options=LOCATE_METHOD_OPTIONS),
        "roi": FieldSpec("roi", "Search region", "roi", role="find", param="roi", shapes=("rect", "rotated_rect"), help_text="Leave blank to search the whole image."),
        "template_images": FieldSpec("template_images", "Locator mark", "images", role="ref", param="images", required=True, default=[], help_text="A fixed reference picture cropped from the taught part.", visible_when={"method": ["template", "register"]}),
        "model": FieldSpec("model", "Shape model", "asset", role="find", param="model", required=True, default="", accept="file", visible_when={"method": "shape"}),
        "threshold": FieldSpec("threshold", "Score threshold", "range", role="find", param="threshold", default=0.7, minimum=0, maximum=1, step=0.01),
        "allow_rotation": FieldSpec("allow_rotation", "Allow rotation", "boolean", default=False),
        "angle_range": FieldSpec("angle_range", "Rotation range", "number", role="find", param="angle_range", default=0, minimum=0, maximum=180, unit="deg"),
        "ref_x": FieldSpec("ref_x", "Reference X", "number", role="align", param="ref_x", required=True, default=0, unit="px"),
        "ref_y": FieldSpec("ref_y", "Reference Y", "number", role="align", param="ref_y", required=True, default=0, unit="px"),
        "ref_angle": FieldSpec("ref_angle", "Reference angle", "number", role="align", param="ref_angle", default=0, unit="deg"),
        "required": FieldSpec("required", "Required", "boolean", default=True),
    },
    public_inputs=(PortRef("find", "image"),),
    public_outputs=(PortRef("align", "transform"), PortRef("find", "found"), PortRef("find", "detected")),
    pass_port=None,
    layout_hook=locate_layout,
    read_hook=partial(read_fields, "locate_part"),
))
