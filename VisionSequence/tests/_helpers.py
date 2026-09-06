"""測試共用：直接建 ToolContext 跑工具、合成影像、手刻最小 ONNX 模型。"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import cv2
import numpy as np

from apps.vision.tools import base, register_builtins
from apps.vision.tools.base import Result, ToolContext

register_builtins()


def run_tool(key: str, image: np.ndarray | None = None, params: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None,
             assets: dict[str, str] | None = None, context: dict[str, Any] | None = None) -> Result:
    tool = base.get(key)
    ins: dict[str, Any] = {}
    if image is not None:
        ins["image"] = image
    ins.update(inputs or {})
    ctx = ToolContext(
        run_id="test", flow_id=1, node={"id": key, "type": key, "params": params or {}}, inputs=ins,
        context=context if context is not None else {}, moment=0.0, log=lambda *a, **k: None,
        asset_path=lambda aid: (assets or {}).get(str(aid)), grab=lambda sid: None, preview=True,
        depth=getattr(tool, "accepts", ("u8",)),
    )
    return tool.execute(ctx)


def temp_dir() -> str:
    return tempfile.mkdtemp(prefix="vs-test-")


def save_png(image: np.ndarray, folder: str, name: str) -> str:
    path = os.path.join(folder, name)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    buf.tofile(path)
    return path


def blank(h: int = 240, w: int = 320, value: int = 30) -> np.ndarray:
    return np.full((h, w), value, dtype=np.uint8)


def circle_image(cx: int = 160, cy: int = 120, r: int = 50, bg: int = 30, fg: int = 220) -> np.ndarray:
    img = blank(value=bg)
    cv2.circle(img, (cx, cy), r, fg, -1)
    return img


def rect_image(x: int = 100, y: int = 80, w: int = 120, h: int = 60, bg: int = 30, fg: int = 220) -> np.ndarray:
    img = blank(value=bg)
    cv2.rectangle(img, (x, y), (x + w - 1, y + h - 1), fg, -1)
    return img


# ---------------------------------------------------------------------------
# 手刻 protobuf（不依賴 onnx 套件）：足夠寫出 Identity / GlobalAveragePool 這種小模型
# ---------------------------------------------------------------------------
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field_varint(num: int, value: int) -> bytes:
    return _varint((num << 3) | 0) + _varint(value)


def _field_bytes(num: int, payload: bytes) -> bytes:
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _field_str(num: int, s: str) -> bytes:
    return _field_bytes(num, s.encode())


def _value_info(name: str, dims: list[int]) -> bytes:
    shape = b"".join(_field_bytes(1, _field_varint(1, d)) for d in dims)  # TensorShapeProto.dim[].dim_value
    tensor_type = _field_varint(1, 1) + _field_bytes(2, shape)  # elem_type=FLOAT, shape
    type_proto = _field_bytes(1, tensor_type)
    return _field_str(1, name) + _field_bytes(2, type_proto)


def _node(op: str, inputs: list[str], outputs: list[str]) -> bytes:
    return b"".join(_field_str(1, i) for i in inputs) + b"".join(_field_str(2, o) for o in outputs) + _field_str(3, op.lower()) + _field_str(4, op)


def write_onnx(path: str, nodes: list[tuple[str, list[str], list[str]]], inputs: list[tuple[str, list[int]]], outputs: list[tuple[str, list[int]]]) -> str:
    graph = b"".join(_field_bytes(1, _node(*n)) for n in nodes) + _field_str(2, "g")
    graph += b"".join(_field_bytes(11, _value_info(*i)) for i in inputs)
    graph += b"".join(_field_bytes(12, _value_info(*o)) for o in outputs)
    opset = _field_str(1, "") + _field_varint(2, 13)
    model = _field_varint(1, 8) + _field_bytes(7, graph) + _field_bytes(8, opset)
    with open(path, "wb") as f:
        f.write(model)
    return path


def fake_backbone(path: str, size: int = 320) -> str:
    """不帶權重的異常檢測「backbone」：AveragePool 8×8 → f2 (1,3,s/8,s/8)、AveragePool 16×16 → f3 (1,3,s/16,s/16)。
    特徵＝局部平均色；刮痕（暗線）會讓局部平均掉下去，足夠驗證整條鏈（測試與 bench 用，不需 torch）。"""
    from apps.vision.dl.onnx_io import build_model

    model = build_model(
        nodes=[("AveragePool", ["x"], ["f2"], {"kernel_shape": [8, 8], "strides": [8, 8]}), ("AveragePool", ["x"], ["f3"], {"kernel_shape": [16, 16], "strides": [16, 16]})],
        inputs=[("x", [1, 3, size, size])], outputs=[("f2", [1, 3, size // 8, size // 8]), ("f3", [1, 3, size // 16, size // 16])],
    )
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(model)
    return path


def gap_classifier_onnx(folder: str, size: int = 8) -> str:
    """x[1,3,s,s] → GlobalAveragePool → Flatten → y[1,3]：類別 = 平均值最高的通道。"""
    return write_onnx(os.path.join(folder, "gap.onnx"),
                      [("GlobalAveragePool", ["x"], ["p"]), ("Flatten", ["p"], ["y"])],
                      [("x", [1, 3, size, size])], [("y", [1, 3])])


def identity_onnx(folder: str, size: int = 8) -> str:
    """x[1,3,s,s] → Identity → y[1,3,s,s]：當分割模型用（3 類，argmax 為最大通道）。"""
    return write_onnx(os.path.join(folder, "id.onnx"), [("Identity", ["x"], ["y"])], [("x", [1, 3, size, size])], [("y", [1, 3, size, size])])


def yolo_seg_onnx(folder: str, size: int = 64) -> str:
    """固定輸出的 YOLO-seg 風格模型（dl_instance 的接線測試：letterbox／NMS／mask 合成／座標回映）。

    det[1,9,16]（4 box + 1 類 + 4 mask 係數；只有第 0 個候選過信心門檻，框在 letterbox 中央 40%）
    ＋ protos[1,4,8,8] 全 1（sigmoid(係數和 20)≈1 → mask 蓋滿框內）。輸入影像內容不影響輸出。
    """
    from apps.vision.dl.onnx_io import build_model

    n = 16
    det = np.zeros((1, 9, n), dtype=np.float32)
    det[0, :, 0] = [size / 2, size / 2, size * 0.4, size * 0.4, 0.9, 5, 5, 5, 5]
    protos = np.ones((1, 4, 8, 8), dtype=np.float32)
    model = build_model(
        nodes=[("Identity", ["det0"], ["det"]), ("Identity", ["protos0"], ["protos"]), ("Identity", ["x"], ["unused"])],
        inputs=[("x", [1, 3, size, size])],
        outputs=[("det", [1, 9, n]), ("protos", [1, 4, 8, 8])],
        initializers={"det0": det, "protos0": protos},
    )
    path = os.path.join(folder, "seg.onnx")
    with open(path, "wb") as f:
        f.write(model)
    return path
