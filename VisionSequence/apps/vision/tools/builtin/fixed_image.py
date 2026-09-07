"""固定影像（fixed_image）：把上傳的圖片記在流程裡，每次執行直接送出——不用影像來源、不佔資產庫。

用途：沒有相機時用固定圖片跑流程、範本畫廊的樣本圖、範本比對／良品比對／平場的參考圖（接到那些工具的參考影像埠）。
多張時 `mode`＝cycle 每次執行輪到下一張（**試執行也算一次**：現場調參要按一次看一張，不是一直看同一張）、fixed 固定第 index 張。
游標只在真的有流程 id 時推進：批次測試（flow_id=-1）與 AI 試跑（flow_id=0）都自己餵圖，不該動到產線那條流程的位置。
`role`＝acquire 時批次測試／精度研究／API 送圖（context 的 `_input_image`）優先——與取像工具同一條規則，這樣「用這張重跑」對固定影像流程也成立；
`role`＝reference（範本圖、良品圖、白參考等接到其他工具參考埠的圖）永遠送自己的圖，否則批次測試會把待測圖同時餵給參考埠（比對自己＝永遠 OK）。
"""

from __future__ import annotations

import threading

import cv2

from apps.vision import fixed_images
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError

_cursor: dict[tuple[int, str], int] = {}
_lock = threading.Lock()


def reset_cursors() -> None:
    with _lock:
        _cursor.clear()


class FixedImageTool(Tool):
    key = "fixed_image"
    label = "Fixed image"
    description = (
        "Uses pictures uploaded into this step instead of a camera: one picture, or several taken in turn on each run. Keeps the pictures with the "
        "flow, so a flow built from a template or from an uploaded picture runs anywhere; also the way to hand a reference picture (template, golden "
        "sample, white reference) to the tool that needs it through its picture input."
    )
    category = "source"
    icon = "ImageUp"
    params = [
        Param("images", "Pictures", kind="images", required=True, help_text="Upload one or more pictures; they are stored with the flow."),
        Param("mode", "Which picture", kind="select", default="cycle", options=[
            {"value": "cycle", "label": "Each run takes the next picture, previews included"},
            {"value": "fixed", "label": "Always the picture at the index"},
        ]),
        Param("index", "Index", kind="number", default=1, minimum=1, visible_when={"param": "mode", "in": ["fixed"]}, help_text="1 = the first picture."),
        Param("role", "Role", kind="select", default="acquire", options=[
            {"value": "acquire", "label": "Picture to inspect (a pushed picture from the API, a batch test or a re-run takes its place)"},
            {"value": "reference", "label": "Reference for another tool (template, golden sample, white reference): never replaced"},
        ]),
        Param("convert", "Colour", kind="select", default="keep", options=[
            {"value": "keep", "label": "As uploaded"}, {"value": "gray", "label": "Grayscale"}, {"value": "bgr", "label": "Colour (3 channels)"},
        ]),
    ]
    inputs: list[Port] = []
    outputs = [Port("image", "Image", "image"), Port("index", "Picture index", "number"), Port("name", "Picture name", "string"), Port("count", "Picture count", "number"),
               Port("width", "Width", "number"), Port("height", "Height", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        images = ctx.param("images") or []
        descs = [d for d in images if isinstance(d, dict) and d.get("id")]
        candidate = ctx.context.get("_input_image") if str(ctx.param("role", "acquire")) != "reference" else None
        if candidate is not None:
            image, idx, name = candidate, 0, "input"
        else:
            if not descs:
                raise ToolError("No picture uploaded: add at least one picture to this step")
            n = len(descs)
            if str(ctx.param("mode", "cycle")) == "fixed":
                idx = min(max(1, ctx.integer("index", 1)), n) - 1
            else:
                key = (int(ctx.flow_id), str(ctx.node.get("id") or ""))
                with _lock:
                    idx = _cursor.get(key, 0) % n
                    if ctx.flow_id > 0:  # 試執行也推進；批次與 AI 試跑（flow_id ≤ 0）不動游標
                        _cursor[key] = (idx + 1) % n
            d = descs[idx]
            image = fixed_images.load(str(d["id"]))
            if image is None:
                raise ToolError(f"Picture {idx + 1} ({d.get('name') or d['id']}) is missing from the store; upload it again")
            name = str(d.get("name") or d["id"])
        convert = str(ctx.param("convert", "keep"))
        if convert == "gray" and image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif convert == "bgr" and image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        h, w = image.shape[:2]
        return Result(outputs={"image": image, "index": idx + 1, "name": name, "count": len(descs), "width": int(w), "height": int(h)},
                      message=f"picture {idx + 1} of {len(descs)}: {name}" if candidate is None else "input picture")


TOOLS = [FixedImageTool()]
