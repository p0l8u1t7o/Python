"""手刻 ONNX protobuf（不依賴 onnx 套件）：支援帶權重（initializer）的小模型。

與 tests/_helpers.py 的手刻版同源，多了 initializer（TensorProto raw_data）。
夠用來輸出 Flatten → MatMul → Add → Relu → MatMul → Add 這類全連接網路；
運算子都不需要 attribute（Flatten 預設 axis=1 正好把 NCHW 壓成 [N, C*H*W]）。
"""

from __future__ import annotations

import numpy as np


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
    # TensorShapeProto.dim[]：>0 用 dim_value（field 1）；<=0 表示動態，用 dim_param（field 2）。
    shape = b"".join(_field_bytes(1, _field_varint(1, d) if d > 0 else _field_str(2, f"d{i}")) for i, d in enumerate(dims))
    tensor_type = _field_varint(1, 1) + _field_bytes(2, shape)  # elem_type=FLOAT
    return _field_str(1, name) + _field_bytes(2, _field_bytes(1, tensor_type))


def _attr_ints(name: str, values: list[int]) -> bytes:
    """AttributeProto：name=1、ints=8（repeated）、type=20（INTS=7）。"""
    return _field_str(1, name) + b"".join(_field_varint(8, v) for v in values) + _field_varint(20, 7)


def _node(op: str, inputs: list[str], outputs: list[str], attrs: dict[str, list[int]] | None = None) -> bytes:
    name = f"{op.lower()}_{outputs[0]}"  # 節點名稱必須唯一
    out = b"".join(_field_str(1, i) for i in inputs) + b"".join(_field_str(2, o) for o in outputs) + _field_str(3, name) + _field_str(4, op)
    for key, values in (attrs or {}).items():
        out += _field_bytes(5, _attr_ints(key, values))
    return out


def _initializer(name: str, array: np.ndarray) -> bytes:
    """TensorProto：dims=1、data_type=2（FLOAT=1）、name=8、raw_data=9（float32 LE）。"""
    data = np.ascontiguousarray(array, dtype=np.float32)
    out = b"".join(_field_varint(1, int(d)) for d in data.shape)
    out += _field_varint(2, 1)
    out += _field_str(8, name)
    out += _field_bytes(9, data.tobytes())
    return out


def build_model(
    nodes: list[tuple],
    inputs: list[tuple[str, list[int]]],
    outputs: list[tuple[str, list[int]]],
    initializers: dict[str, np.ndarray] | None = None,
) -> bytes:
    """組出 ONNX ModelProto bytes（ir_version=8、opset 13）。"""
    graph = b"".join(_field_bytes(1, _node(*n)) for n in nodes) + _field_str(2, "g")
    for name, array in (initializers or {}).items():
        graph += _field_bytes(5, _initializer(name, array))
    graph += b"".join(_field_bytes(11, _value_info(*i)) for i in inputs)
    graph += b"".join(_field_bytes(12, _value_info(*o)) for o in outputs)
    opset = _field_str(1, "") + _field_varint(2, 13)
    return _field_varint(1, 8) + _field_bytes(7, graph) + _field_bytes(8, opset)


def build_mlp(w1: np.ndarray, b1: np.ndarray, w2: np.ndarray, b2: np.ndarray, *, channels: int, size: int) -> bytes:
    """x[1,C,S,S] → Flatten → xW1+b1 → Relu → hW2+b2 → y[1,classes]。權重形狀：w1[D,H]、w2[H,C_out]。"""
    d = channels * size * size
    if w1.shape[0] != d:
        raise ValueError(f"w1 第一維應為 {d}，得到 {w1.shape}")
    return build_model(
        nodes=[
            ("Flatten", ["x"], ["flat"]),
            ("MatMul", ["flat", "w1"], ["m1"]),
            ("Add", ["m1", "b1"], ["a1"]),
            ("Relu", ["a1"], ["h"]),
            ("MatMul", ["h", "w2"], ["m2"]),
            ("Add", ["m2", "b2"], ["y"]),
        ],
        inputs=[("x", [1, channels, size, size])],
        outputs=[("y", [1, int(w2.shape[1])])],
        initializers={"w1": w1, "b1": b1.reshape(1, -1), "w2": w2, "b2": b2.reshape(1, -1)},
    )


def build_patch_segmenter(k1: np.ndarray, c1: np.ndarray, k2: np.ndarray, c2: np.ndarray, *, channels: int, kernel: int) -> bytes:
    """全卷積 patch 分類器：x[1,C,H,W] → Conv(k×k, pad=same) → Relu → Conv(1×1) → y[1,classes,H,W]。

    k1[hidden, C, k, k]、c1[hidden]、k2[classes, hidden, 1, 1]、c2[classes]。
    輸入 H/W 用 0 表示動態（onnxruntime 接受任意尺寸）。
    """
    pad = kernel // 2
    return build_model(
        nodes=[
            ("Conv", ["x", "k1", "c1"], ["a1"], {"kernel_shape": [kernel, kernel], "pads": [pad, pad, pad, pad], "strides": [1, 1]}),
            ("Relu", ["a1"], ["h"]),
            ("Conv", ["h", "k2", "c2"], ["y"], {"kernel_shape": [1, 1], "pads": [0, 0, 0, 0], "strides": [1, 1]}),
        ],
        inputs=[("x", [1, channels, 0, 0])],
        outputs=[("y", [1, int(k2.shape[0]), 0, 0])],
        initializers={"k1": k1, "c1": c1, "k2": k2, "c2": c2},
    )
