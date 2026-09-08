"""內建工具與引擎的效能基準。

用法：
    .venv/Scripts/python.exe scripts/bench_tools.py            # 印到 stdout
    .venv/Scripts/python.exe scripts/bench_tools.py -o docs/bench-before.txt

對 1280×960 與 640×480 兩種合成影像（SyntheticGrabber，seed 固定），每個內建工具
用合理的參數跑 30 次（先暖機 3 次），輸出 median／p95 ms；另外量：
- 示範流程「零件孔數檢測」整體 run 與各節點的分佈；
- 引擎每節點固定開銷（總時間 − 各節點工具時間）；
- ImageStore.encode 的縮圖／原圖 JPEG 編碼時間。

需要範本／模型的工具用臨時裁切的範本（template_match、defect_diff）與
tests/_helpers.py 的手刻 ONNX。輸出格式只是表格，不影響任何測試。
"""

from __future__ import annotations

import argparse
import io
import math
import os
import platform
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from apps.vision import engine  # noqa: E402
from apps.vision.demo import hole_count_flow  # noqa: E402
from apps.vision.graph import compile_graph, validate_graph  # noqa: E402
from apps.vision.images import ImageStore, encode_image  # noqa: E402
from apps.vision.sources.grabbers import SyntheticGrabber  # noqa: E402
from apps.vision.tools import base, register_builtins  # noqa: E402
from apps.vision.tools.base import Result, ToolContext  # noqa: E402
from apps.vision.tools.builtin.script import TEMPLATE as SCRIPT_TEMPLATE  # noqa: E402
from tests._helpers import _field_bytes, _field_str, _field_varint, _value_info, fake_backbone, gap_classifier_onnx, identity_onnx, save_png, yolo_seg_onnx  # noqa: E402

register_builtins()

WARMUP = 3
RUNS = 30
#: 每個量測重複幾輪、取各輪 median／p95 的最小值（混合大小核的筆電上單輪雜訊可達 ±20%）。
REPEAT = 1


# ---------------------------------------------------------------------------
# 工具呼叫
# ---------------------------------------------------------------------------
def make_ctx(key: str, image: np.ndarray | None, params: dict[str, Any], inputs: dict[str, Any], assets: dict[str, str], context: dict[str, Any]) -> ToolContext:
    ins: dict[str, Any] = {}
    if image is not None:
        ins["image"] = image
    ins.update(inputs)
    from apps.vision.tools import base as _base

    return ToolContext(
        run_id="bench", flow_id=1, node={"id": key, "type": key, "params": params}, inputs=ins,
        context=context, moment=0.0, log=lambda *a, **k: None,
        asset_path=lambda aid: assets.get(str(aid)), grab=lambda sid: None, preview=False,
        depth=getattr(_base.get(key), "accepts", ("u8",)),
    )


def _timeit_once(fn: Callable[[], Any], runs: int, warmup: int) -> tuple[float, float, Any]:
    last = None
    for _ in range(warmup):
        last = fn()
    samples: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        last = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    med = statistics.median(samples)
    p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    return med, p95, last


def timeit(fn: Callable[[], Any], runs: int | None = None, warmup: int = WARMUP) -> tuple[float, float, Any]:
    """回傳 (median ms, p95 ms, 最後一次的回傳值)；REPEAT > 1 時取各輪的最小值。"""
    best_med = best_p95 = float("inf")
    last = None
    for _ in range(max(1, REPEAT)):
        med, p95, last = _timeit_once(fn, runs or RUNS, warmup)
        best_med, best_p95 = min(best_med, med), min(best_p95, p95)
    return best_med, best_p95, last


def pin_process() -> str:
    """Windows：把行程綁到前 8 個邏輯核心（混合架構的 P-core）並拉高優先權，減少量測雜訊。"""
    if os.name != "nt":
        return "pin: 只支援 Windows"
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    handle = k32.GetCurrentProcess()
    ncpu = os.cpu_count() or 1
    mask = (1 << min(8, ncpu)) - 1
    ok_aff = k32.SetProcessAffinityMask(handle, mask)
    ok_pri = k32.SetPriorityClass(handle, 0x00000080)  # HIGH_PRIORITY_CLASS
    return f"pin: affinity=0x{mask:x} ({'ok' if ok_aff else 'fail'}), priority=high ({'ok' if ok_pri else 'fail'})"


def yolo_like_onnx(folder: str, size: int = 8) -> str:
    """x[1,3,s,s] → Flatten(axis=3) → y[3s, s]：把每列像素當一個候選框（x,y,w,h + 4 類分數）。"""
    attr = _field_str(1, "axis") + _field_varint(3, 3) + _field_varint(20, 2)  # AttributeProto{name, i, type=INT}
    node = _field_str(1, "x") + _field_str(2, "y") + _field_str(3, "flatten") + _field_str(4, "Flatten") + _field_bytes(5, attr)
    graph = _field_bytes(1, node) + _field_str(2, "g")
    graph += _field_bytes(11, _value_info("x", [1, 3, size, size]))
    graph += _field_bytes(12, _value_info("y", [3 * size, size]))
    opset = _field_str(1, "") + _field_varint(2, 13)
    model = _field_varint(1, 8) + _field_bytes(7, graph) + _field_bytes(8, opset)
    path = os.path.join(folder, "yolo.onnx")
    with open(path, "wb") as f:
        f.write(model)
    return path


def save_calibration(folder: str, w: int, h: int) -> str:
    """一份典型的站台標定：桶形畸變＋帶旋轉的仿射世界座標（undistort／to_world 的 bench 用）。"""
    from apps.vision import calib

    f = 1.4 * max(w, h)
    ang = math.radians(12)
    k = 0.05
    payload = {
        "unit": "mm", "image_size": [w, h],
        "lens": {"camera_matrix": [[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], "dist_coeffs": [-0.22, 0.08, 0.0, 0.0, 0.0], "rms": 0.19, "views": 12},
        "world": {"kind": "affine", "matrix": [[k * math.cos(ang), -k * math.sin(ang), 12.0], [k * math.sin(ang), k * math.cos(ang), -8.0], [0, 0, 1]], "mm_per_px": k, "rms": 0.01, "max_error": 0.02},
    }
    path = os.path.join(folder, f"calib_{w}.json")
    calib.save(path, payload)
    return path


def save_mapping_calibration(folder: str, w: int, h: int) -> str:
    """建立一份只含相機映射的標定資產，避免影響既有世界座標 bench。"""
    from apps.vision import calib

    matrix = [[1.0, 0.0, 30.0], [0.0, 1.0, -20.0], [0.0, 0.0, 1.0]]
    pairs = [
        ([10.0, 20.0], [40.0, 0.0]),
        ([120.0, 20.0], [150.0, 0.0]),
        ([10.0, 100.0], [40.0, 80.0]),
        ([120.0, 100.0], [150.0, 80.0]),
    ]
    payload = {"unit": "px", "image_size": [w, h], "mapping": calib.solve_mapping(pairs, "affine", matrix=matrix, from_source="A", to_source="B")}
    path = os.path.join(folder, f"mapcal_{w}.json")
    calib.save(path, payload)
    return path


class Scene:
    """一張合成影像與它的幾何（板子中心、孔位），讓每個工具的 ROI 都落在有東西的地方。"""

    def __init__(self, w: int, h: int, folder: str) -> None:
        g = SyntheticGrabber({"width": w, "height": h, "pattern": "parts", "seed": 7, "defect_rate": 0.0})
        self.image = g.grab()
        assert self.image is not None
        meta = g.last_meta
        self.w, self.h = w, h
        self.cx, self.cy = w / 2 + meta["dx"], h / 2 + meta["dy"]
        self.angle = meta["angle"]
        self.m = min(w, h)
        self.gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        self.folder = folder
        r = int(self.m * 0.12)
        cx, cy = int(self.cx), int(self.cy)
        self.template = save_png(self.gray[cy - r : cy + r, cx - r : cx + r], folder, f"tpl_{w}.png")
        self.golden = save_png(self.gray, folder, f"golden_{w}.png")
        self.mask = cv2.threshold(self.gray, 60, 255, cv2.THRESH_BINARY_INV)[1]
        self.calibration = save_calibration(folder, w, h)
        self.mapping_calibration = save_mapping_calibration(folder, w, h)
        self.shape_template = save_png(self.mask[cy - r : cy + r, cx - r : cx + r], folder, f"shape_{w}.png")
        yy, xx = np.mgrid[0:h, 0:w]
        vignette = 1.0 - 0.45 * (((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / ((w / 2) ** 2 + (h / 2) ** 2))
        self.flat = save_png(np.clip(vignette * 235, 0, 255).astype(np.uint8), folder, f"flat_{w}.png")
        # 統計範本：以場景灰階為底做 8 張亮度／位移擾動的良品建模（板子區域）
        from apps.vision import stattpl as _stattpl

        rng = np.random.default_rng(3)
        good = []
        for i in range(8):
            m = np.array([[1, 0, rng.integers(-3, 4)], [0, 1, rng.integers(-3, 4)]], np.float32)
            shifted = cv2.warpAffine(self.gray, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
            good.append(np.clip(shifted.astype(np.int16) + int(rng.integers(-8, 9)), 0, 255).astype(np.uint8))
        payload, _ = _stattpl.build(good, self.rect(-0.25, -0.2, 0.5, 0.4), "phase")
        self.stat_model = os.path.join(folder, f"stat_{w}.npz")
        _stattpl.save(self.stat_model, payload)
        from apps.vision import shapemodel as _shapemodel

        self.shape_model = os.path.join(folder, f"shape_{w}.npz")
        _shapemodel.save(self.shape_model, _shapemodel.teach(self.gray[cy - r : cy + r, cx - r : cx + r]))
        # 異常檢測：假 backbone（pooling）＋ 4 張擾動良品建的小記憶庫（真 backbone 的數字見 docs/performance.html）
        from apps.vision.dl.anomaly_trainer import AnomalyTrainer
        from apps.vision.dl.base import SampleRef as _SampleRef

        fb = fake_backbone(os.path.join(folder, "fake_backbone.onnx"), size=224)
        goods = [_SampleRef(id=f"a{i}", label="", path=save_png(np.clip(self.image.astype(np.int16) + int(rng.integers(-6, 7)), 0, 255).astype(np.uint8), folder, f"anomaly_{w}_{i}.png")) for i in range(4)]
        res = AnomalyTrainer().train(goods, ["good"], {"input_size": 224, "coreset_ratio": 0.5, "projection_dims": 0, "backbone_path": fb}, "cpu", lambda f, s, m: None)
        self.anomaly_model = os.path.join(folder, f"anomaly_{w}.npz")
        with open(self.anomaly_model, "wb") as fh:
            fh.write(res.weights_bytes)
        from apps.vision.dl.retrieval_trainer import RetrievalTrainer

        ref_red = np.full((224, 224, 3), (0, 0, 255), np.uint8)
        ref_green = np.full((224, 224, 3), (0, 255, 0), np.uint8)
        ref_blue = np.full((224, 224, 3), (255, 0, 0), np.uint8)
        self.retrieval_probe = ref_red.copy()
        refs = [
            _SampleRef(id="r0", label="red", path=save_png(ref_red, folder, f"retrieval_red_{w}.png")),
            _SampleRef(id="g0", label="green", path=save_png(ref_green, folder, f"retrieval_green_{w}.png")),
            _SampleRef(id="b0", label="blue", path=save_png(ref_blue, folder, f"retrieval_blue_{w}.png")),
        ]
        res = RetrievalTrainer().train(refs, ["red", "green", "blue"], {"input_size": 224, "topk": 1, "projection_dims": 0, "backbone_path": fb}, "cpu", lambda f, s, m: None)
        self.retrieval_model = os.path.join(folder, f"retrieval_{w}.npz")
        with open(self.retrieval_model, "wb") as fh:
            fh.write(res.weights_bytes)
        # OCR：用 PIL 內建字型教一個數字字型模型（bench 的 ocr_read 走教導路；通用 PP-OCR 路只在有模型的機器上量）
        from apps.vision import ocr as _ocr
        from tests.test_ocr import digits as _digits, render as _render

        rng_t = np.random.default_rng(11)
        tiles, labels = [], []
        for _ in range(20):
            txt = _digits(rng_t, 8)
            line = _render(txt, size=36)
            boxes = _ocr.segment_chars(line, "projection")
            if len(boxes) == len(txt):
                for b, ch in zip(boxes, txt):
                    tiles.append(_ocr.char_tile(line, b))
                    labels.append(ch)
        self.font_model = os.path.join(folder, "font.npz")
        with open(self.font_model, "wb") as fh:
            fh.write(_ocr.pack_font(_ocr.train_font(tiles, labels, epochs=150)))
        self.ocr_line = np.full((h, w), 235, np.uint8)
        self.ocr_line[h // 2 - 40 : h // 2 + 40, w // 2 - 200 : w // 2 + 200] = _render("24091237", size=36)
        self.flat_bgr = save_png(cv2.cvtColor(np.clip(vignette * 235, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR), folder, f"flatc_{w}.png")
        # 光度立體：以板子遮罩當高度場（6 px 浮凸）渲染四個方向的打光影像
        from apps.vision.tools.builtin.photometric import light_directions

        height = cv2.GaussianBlur(self.mask.astype(np.float32) / 255.0, (0, 0), 3) * 6.0
        gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
        gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
        nrm = np.dstack([-gx, -gy, np.ones_like(gx)])
        nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
        lights = light_directions([0, 90, 180, 270], 30)
        self.lit = [np.clip(180.0 * np.clip(nrm @ lights[k], 0, None) + 8, 0, 255).astype(np.uint8) for k in range(4)]
        # 條碼分級：Data Matrix（模組 8 px）貼在場景中央偏上；沒有 zxing 就是棋盤（工具回 F，仍可量時間）
        from apps.vision.demo_images import _datamatrix_bitmap

        dm = np.kron(_datamatrix_bitmap("VS-000123"), np.ones((8, 8), np.uint8))
        self.dm_image = self.gray.copy()
        y0, x0 = int(self.cy) - dm.shape[0] // 2 - int(self.m * 0.3), int(self.cx) - dm.shape[1] // 2
        self.dm_image[y0:y0 + dm.shape[0], x0:x0 + dm.shape[1]] = dm
        self.dm_roi = {"shape": "rect", "x": x0 - 20, "y": y0 - 20, "w": dm.shape[1] + 40, "h": dm.shape[0] + 40}
        from apps.vision import fixed_images

        self.color_samples = [
            fixed_images.store(np.full((32, 32, 3), (0, 0, 255), np.uint8), "red"),
            fixed_images.store(np.full((32, 32, 3), (0, 255, 0), np.uint8), "green"),
            fixed_images.store(np.full((32, 32, 3), (255, 0, 0), np.uint8), "blue"),
        ]
        self.assets = {"tpl": self.template, "golden": self.golden, "gap": gap_classifier_onnx(folder), "idn": identity_onnx(folder), "yolo": yolo_like_onnx(folder), "seg": yolo_seg_onnx(folder), "cal": self.calibration, "mapcal": self.mapping_calibration, "shape": self.shape_template, "flat": self.flat, "flat_bgr": self.flat_bgr, "stat": self.stat_model, "shapemodel": self.shape_model, "anomaly": self.anomaly_model, "retrieval": self.retrieval_model, "font": self.font_model}

    def rect(self, fx: float, fy: float, fw: float, fh: float) -> dict[str, Any]:
        """以板子中心為原點、以影像比例給的矩形。"""
        return {"shape": "rect", "x": self.cx + fx * self.w, "y": self.cy + fy * self.h, "w": fw * self.w, "h": fh * self.h}


def cases(s: Scene) -> list[tuple[str, str, np.ndarray | None, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """(顯示名, 工具 key, image, params, inputs, context)。"""
    m = s.m
    plate = s.rect(-0.25, -0.2, 0.5, 0.4)
    center_circle = {"shape": "circle", "cx": s.cx, "cy": s.cy, "r": m * 0.12}
    hole_r = m * 0.035
    big = s.image
    gray = s.gray
    overlays = [
        [{"kind": "rect", "x": 10, "y": 10, "w": 100, "h": 50, "label": "a"}, {"kind": "circle", "cx": s.cx, "cy": s.cy, "r": 30, "label": "c"}],
        [{"kind": "contours", "contours": [[[x, 10] for x in range(0, 60, 5)] + [[x, 50] for x in range(60, 0, -5)]] * 5}],
        [{"kind": "points", "points": [[float(i), float(i)] for i in range(0, 200, 4)]}, {"kind": "text", "x": 20, "y": 80, "text": "hello"}],
    ]
    top_edge = {"shape": "rotated_rect", "cx": s.cx, "cy": s.cy - 0.2 * s.h, "w": 0.4 * s.w, "h": 40, "angle": s.angle}
    caliper_bars = np.full((90, 220), 40, np.uint8)
    caliper_bars[:, 45:55] = 100
    caliper_bars[:, 150:160] = 230
    caliper_bars = cv2.GaussianBlur(caliper_bars, (0, 0), 0.8)
    trend_edge = np.full((140, 220), 40, np.uint8)
    for x in range(trend_edge.shape[1]):
        trend_edge[70 + (3 if 90 <= x < 130 else 0) :, x] = 210
    trend_edge = cv2.GaussianBlur(trend_edge, (0, 0), 0.8)
    path_block = np.full((180, 240), 30, np.uint8)
    cv2.rectangle(path_block, (40, 40), (200, 140), 220, -1)
    path_block = cv2.GaussianBlur(path_block, (0, 0), 0.8)
    path_square = {"shape": "polygon", "points": [[35, 35], [205, 35], [205, 145], [35, 145]]}
    edge_model_square = {"version": 1, "image_size": [240, 180], "closed": True, "points": [[40, 40], [200, 40], [200, 140], [40, 140]]}
    blob_hyst = np.full((180, 240), 10, np.uint8)
    blob_hyst[45:125, 45:135] = 115
    blob_hyst[70:100, 75:105] = 230
    blob_hyst[55:115, 165:205] = 115
    yy_b, xx_b = np.mgrid[0:180, 0:240]
    blob_soft = np.clip(230 - np.hypot(xx_b - 120, yy_b - 90) * 3.0, 20, 230).astype(np.uint8)
    label_map = np.zeros((180, 240), np.uint8)
    label_map[35:95, 35:95] = 1
    label_map[45:85, 135:175] = 2
    label_map[105:145, 145:205] = 2
    color_blocks = np.zeros((180, 300, 3), dtype=np.uint8)
    color_blocks[30:130, 20:100] = (0, 0, 255)
    color_blocks[30:130, 110:190] = (0, 255, 0)
    color_blocks[30:130, 200:280] = (255, 0, 0)
    color_segments = "red:170,10,80,255,80,255\ngreen:45,85,80,255,80,255\nblue:110,130,80,255,80,255"
    merge_r = np.full((180, 300), 40, np.uint8)
    merge_g = np.full((180, 300), 120, np.uint8)
    merge_b = np.full((180, 300), 210, np.uint8)
    grid_matches = [
        {"cx": 20.0 + col * 30.0, "cy": 25.0 + row * 40.0, "w": 12.0, "h": 8.0, "score": 0.8, "angle": 0.0, "label": "dot"}
        for row in range(3)
        for col in range(4)
        if row * 4 + col not in (5, 10)
    ]
    merge_matches = [
        {"cx": 10.0, "cy": 10.0, "w": 10.0, "h": 10.0, "score": 0.2, "angle": 0.0, "label": "part"},
        {"cx": 12.0, "cy": 10.0, "w": 10.0, "h": 10.0, "score": 0.9, "angle": 0.0, "label": "part"},
        {"cx": 50.0, "cy": 50.0, "w": 10.0, "h": 10.0, "score": 0.4, "angle": 0.0, "label": "part"},
    ]
    # 極座標展開：1280×960 時 r 200～300（規格的效能預算案例）；640×480 等比縮小
    ring = {"shape": "annulus", "cx": s.cx, "cy": s.cy, "r_inner": m * 0.2083, "r_outer": m * 0.3125}
    from apps.vision.tools.builtin import polar as _polar

    ring_map = _polar.mapping_dict(ring["cx"], ring["cy"], ring["r_inner"], ring["r_outer"], a0=None, a1=None, start_angle=0, direction="ccw",
                                   step_deg=_polar.step_degrees("auto", ring["r_outer"]), radial_step=1)
    # contours 工具鏈的輸入：整張遮罩的外輪廓（雜訊粒子很多，接近產線最差情況）
    mask_contours = [c for c in cv2.findContours(s.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0] if len(c) >= 4]
    # 組合區域：板子矩形挖掉中央孔（多重 ROI／排除區）
    from apps.vision.tools import roi as _roi

    plate_minus_hole = _roi.composite(plate, [("subtract", center_circle)])
    return [
        # source / preprocess
        ("image_source", "image_source", None, {"mode": "input"}, {}, {"_input_image": big}),
        ("grayscale", "grayscale", big, {}, {}, {}),
        ("crop (rect)", "crop", big, {"roi": plate}, {}, {}),
        ("crop (rotated)", "crop", big, {"roi": {"shape": "rotated_rect", "cx": s.cx, "cy": s.cy, "w": 0.5 * s.w, "h": 0.4 * s.h, "angle": s.angle}}, {}, {}),
        ("blur gaussian 5", "blur", big, {"method": "gaussian", "ksize": 5}, {}, {}),
        ("blur median 5", "blur", gray, {"method": "median", "ksize": 5}, {}, {}),
        ("threshold otsu", "threshold", big, {"method": "otsu"}, {}, {}),
        ("threshold adaptive", "threshold", gray, {"method": "adaptive_gaussian", "block": 31}, {}, {}),
        ("threshold sauvola", "threshold", gray, {"method": "sauvola", "window": 31, "k": 0.2, "invert": True}, {}, {}),
        ("morphology open 5", "morphology", s.mask, {"op": "open", "ksize": 5}, {}, {}),
        ("resize 0.5", "resize", big, {"scale": 0.5}, {}, {}),
        ("color_convert hsv_s", "color_convert", big, {"mode": "hsv_s"}, {}, {}),
        ("color_range", "color_range", big, {"h_low": 0, "h_high": 179, "s_low": 0, "s_high": 60, "v_low": 100, "v_high": 255}, {}, {}),
        ("color_segment", "color_segment", color_blocks, {"segments": color_segments, "space": "hsv"}, {}, {}),
        ("color_classify", "color_classify", color_blocks, {"samples": s.color_samples, "space": "hsv", "bins": 16}, {}, {}),
        ("color_convert merge_rgb", "color_convert", None, {"mode": "merge_rgb"}, {"r": merge_r, "g": merge_g, "b": merge_b}, {}),
        ("lut clahe", "lut", big, {"mode": "clahe"}, {}, {}),
        ("lut normalize_ratio", "lut", gray, {"mode": "normalize_ratio", "low_percent": 1, "high_percent": 99}, {}, {}),
        ("arithmetic absdiff", "arithmetic", None, {"op": "absdiff"}, {"a": big, "b": big}, {}),
        ("apply_mask", "apply_mask", big, {"fill": 0}, {"mask": s.mask}, {}),
        ("filter canny", "filter", big, {"method": "canny"}, {}, {}),
        ("rotate_flip 15deg", "rotate_flip", big, {"angle": 15, "keep_size": True}, {}, {}),
        ("convert_depth u16", "convert_depth", big, {"to": "u16"}, {}, {}),
        ("lut gamma", "lut", big, {"mode": "power", "gamma": 0.6}, {}, {}),
        ("filter gradient", "filter", big, {"method": "gradient"}, {}, {}),
        ("surface_filter 8 dirs", "surface_filter", gray, {"width": 3, "length": 21, "directions": 8}, {}, {}),
        ("fft_filter lowpass", "fft_filter", gray, {"mode": "lowpass", "cutoff": 0.15}, {}, {}),
        ("warp_perspective", "warp_perspective", big, {"roi": {"shape": "polygon", "points": [[s.cx - m * 0.2, s.cy - m * 0.15], [s.cx + m * 0.22, s.cy - m * 0.12], [s.cx + m * 0.2, s.cy + m * 0.15], [s.cx - m * 0.18, s.cy + m * 0.16]]}}, {}, {}),
        ("undistort", "undistort", big, {"calibration": "cal"}, {}, {}),
        ("shading_correct flat (gray)", "shading_correct", gray, {"mode": "flat_field", "flat": "flat"}, {}, {}),
        ("shading_correct flat (bgr)", "shading_correct", big, {"mode": "flat_field", "flat": "flat_bgr"}, {}, {}),
        ("shading_correct estimate", "shading_correct", gray, {"mode": "estimate", "blur_sigma": 51}, {}, {}),
        ("polar_unwrap auto", "polar_unwrap", big, {"roi": ring}, {}, {}),
        ("polar_unwrap 0.5deg cubic", "polar_unwrap", big, {"roi": ring, "angle_step": "0.5", "interpolation": "cubic"}, {}, {}),
        ("polar_restore", "polar_restore", None, {}, {"mapping": ring_map, "points": [[10.0, 5.0], [400.0, 50.0]], "contours": [np.array([[[1, 1]], [[30, 1]], [[30, 20]]], dtype=np.int32)]}, {}),
        # locate
        ("template_match pyramid", "template_match", big, {"template": "tpl", "pyramid": True, "threshold": 0.6}, {}, {}),
        ("template_match no-pyr", "template_match", big, {"template": "tpl", "pyramid": False, "threshold": 0.6}, {}, {}),
        ("template_match rot ±10/5", "template_match", big, {"template": "tpl", "pyramid": True, "threshold": 0.6, "angle_range": 10, "angle_step": 5}, {}, {}),
        ("template_match roi+rot", "template_match", big, {"template": "tpl", "roi": plate, "pyramid": True, "threshold": 0.6, "angle_range": 10, "angle_step": 5}, {}, {}),
        ("template_match sort xy", "template_match", big, {"template": "tpl", "pyramid": True, "threshold": 0.6, "max_matches": 20, "sort_by": "xy"}, {}, {}),
        ("template_match clipped", "template_match", big, {"template": "tpl", "pyramid": True, "threshold": 0.6, "allow_clipped": True}, {}, {}),
        ("shape_match full angle", "shape_match", big, {"model": "shapemodel", "min_score": 0.6}, {}, {}),
        ("shape_match ±20°", "shape_match", big, {"model": "shapemodel", "min_score": 0.6, "angle_start": -20, "angle_extent": 40}, {}, {}),
        ("shape_match roi ±20°", "shape_match", big, {"model": "shapemodel", "min_score": 0.6, "roi": plate, "angle_start": -20, "angle_extent": 40}, {}, {}),
        ("shape_align", "shape_align", None, {"ref_x": s.cx, "ref_y": s.cy}, {"matches": [{"cx": s.cx + 3, "cy": s.cy - 2, "angle": 1.5}]}, {}),
        ("align_offset point", "align_offset", None, {"ref_x": s.cx, "ref_y": s.cy, "ref_angle": 0}, {"matches": [{"cx": s.cx + 3, "cy": s.cy - 2, "angle": 1.5}]}, {}),
        ("align_offset grab", "align_offset", None, {"mode": "grab", "ref_x": s.cx, "ref_y": s.cy, "grab_x": s.cx + 40, "grab_y": s.cy + 10}, {"matches": [{"cx": s.cx + 3, "cy": s.cy - 2, "angle": 1.5}]}, {}),
        ("align_offset set", "align_offset", None, {"mode": "point_set", "ref_points": [[10, 10], [90, 12], [50, 70]]}, {"points": [[13, 8], [93, 10], [53, 68]]}, {}),
        ("map_points", "map_points", None, {"calibration": "mapcal"}, {"points": [[10.0, 20.0], [30.0, 40.0]], "x": 5.0, "y": 6.0}, {}),
        ("fixture_roi", "fixture_roi", None, {"roi": plate}, {"transform": {"dx": 3, "dy": -2, "dtheta": 1.5, "pivot": [s.cx, s.cy]}}, {}),
        ("image_fixture", "image_fixture", gray, {}, {"transform": {"dx": 3, "dy": -2, "dtheta": 1.5, "pivot": [s.cx, s.cy]}}, {}),
        ("region_from_shape", "region_from_shape", None, {"roi": center_circle}, {}, {}),
        ("region_combine subtract", "region_combine", None, {"base": plate, "mode": "subtract"}, {"regions": [center_circle, s.rect(-0.2, -0.15, 0.05, 0.05)]}, {}),
        ("intensity (composite roi)", "intensity", big, {}, {"roi": plate_minus_hole}, {}),
        ("blob (composite roi)", "blob", gray, {"threshold_method": "fixed", "threshold": 60, "polarity": "dark", "min_area": 300}, {"roi": plate_minus_hole}, {}),
        ("find_circle 36", "find_circle", big, {"roi": center_circle, "num_rays": 36}, {}, {}),
        ("find_circle 180", "find_circle", big, {"roi": center_circle, "num_rays": 180}, {}, {}),
        ("find_line 20", "find_line", big, {"roi": top_edge, "num_calipers": 20}, {}, {}),
        ("find_line 100", "find_line", big, {"roi": top_edge, "num_calipers": 100}, {}, {}),
        ("find_rectangle 12/side", "find_rectangle", big, {"roi": s.rect(-0.3, -0.25, 0.6, 0.5), "calipers": 12}, {}, {}),
        ("find_parallel_lines 20", "find_parallel_lines", big, {"roi": s.rect(-0.3, -0.25, 0.6, 0.5), "calipers": 20}, {}, {}),
        ("find_lines_multi 4", "find_lines_multi", big, {"roi": plate, "max_lines": 4}, {}, {}),
        ("find_circles_matrix 3x3", "find_circles_matrix", big, {"roi": plate, "rows": 3, "cols": 3}, {}, {}),
        ("hough_circles", "hough_circles", big, {"roi": plate, "min_radius": int(hole_r * 0.7), "max_radius": int(m * 0.09), "min_dist": int(hole_r * 2)}, {}, {}),
        ("hough_lines", "hough_lines", big, {}, {}, {}),
        # measure
        ("caliper", "caliper", big, {"roi": {"shape": "rect", "x": s.cx - m * 0.12, "y": s.cy - 10, "w": m * 0.24, "h": 20}}, {}, {}),
        ("caliper multi weighted", "caliper", caliper_bars, {"roi": {"shape": "rect", "x": 0, "y": 20, "w": 200, "h": 40}, "pair_polarity": "bright",
                                                              "max_results": 3, "expected_position": 50, "position_weight": 5, "contrast_weight": 1, "edge_threshold": 5}, {}, {}),
        ("distance", "distance", None, {}, {"a": [1.0, 2.0], "b": [4.0, 6.0]}, {}),
        ("angle", "angle", None, {}, {"a": {"x1": 0, "y1": 0, "x2": 10, "y2": 0}, "b": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}}, {}),
        ("intensity (circle roi)", "intensity", big, {"roi": center_circle}, {}, {}),
        ("intensity (full)", "intensity", big, {}, {}, {}),
        ("calibration", "calibration", None, {"pixel_size_mm": 0.01}, {"value": 123.4}, {}),
        ("format_text", "format_text", None, {"template": "{judge},{a:.2f},{lot}", "ending": "crlf"}, {"a": 12.3456}, {"_judge": "ok", "lot": "A17"}),
        ("variable_set (add)", "variable_set", None, {"name": "bench_count", "mode": "add"}, {"value": 1}, {"_sandbox": True}),
        ("variable_get", "variable_get", None, {"name": "bench_count", "default": "0"}, {}, {"_sandbox": True}),
        ("calibration (asset)", "calibration", None, {"mode": "asset", "calibration": "cal"}, {"value": 123.4}, {}),
        ("coordinate", "coordinate", None, {"origin_x": s.cx, "origin_y": s.cy, "axis_angle": 90}, {}, {}),
        ("to_world (frame)", "to_world", None, {"calibration": "cal"},
         {"points": [[s.cx, s.cy + 40]], "frame": {"origin": [s.cx, s.cy], "angle": 90, "scale": 1.0}}, {}),
        ("to_world (inverse)", "to_world", None, {"calibration": "cal", "mode": "to_pixel"}, {"x": 12.0, "y": -8.0}, {}),
        ("distance (calibration)", "distance", None, {"calibration": "cal"}, {"a": [1.0, 2.0], "b": [4.0, 6.0]}, {}),
        ("to_world (points)", "to_world", None, {"calibration": "cal"}, {"points": [[s.cx, s.cy], [s.cx + 40, s.cy + 25]], "value": 100.0, "angle": 30.0}, {}),
        ("histogram (rect roi)", "histogram", big, {"roi": plate}, {}, {}),
        ("histogram (full)", "histogram", big, {}, {}, {}),
        ("sharpness laplacian", "sharpness", gray, {"method": "laplacian"}, {}, {}),
        ("sharpness gradient", "sharpness", gray, {"method": "gradient"}, {}, {}),
        ("sharpness autocorrelation", "sharpness", gray, {"method": "autocorrelation"}, {}, {}),
        ("circular_caliper 72", "circular_caliper", big, {"roi": {"shape": "annulus", "cx": s.cx, "cy": s.cy, "r_inner": m * 0.06, "r_outer": m * 0.18}, "caliper_count": 72}, {}, {}),
        ("circular_caliper 360", "circular_caliper", big, {"roi": {"shape": "annulus", "cx": s.cx, "cy": s.cy, "r_inner": m * 0.06, "r_outer": m * 0.18}, "caliper_count": 360}, {}, {}),
        ("edge_defect line 180", "edge_defect", gray, {"roi": top_edge, "calipers": 180, "search": 30}, {}, {}),
        ("edge_defect arc 180", "edge_defect", gray, {"roi": center_circle, "calipers": 180, "search": 30}, {}, {}),
        ("edge_model_defect 240", "edge_model_defect", path_block, {"model": edge_model_square, "calipers": 240, "search": 28, "threshold": 3, "polarity": "light_to_dark", "edge_threshold": 12}, {}, {}),
        ("edge_trend line 60", "edge_trend", trend_edge, {"calipers": 60, "search": 24, "caliper_width": 5, "polarity": "dark_to_light",
                                                           "edge_threshold": 10, "baseline": "reference", "max_deviation": 2},
         {"line": {"x1": 20, "y1": 69.5, "x2": 200, "y2": 69.5}}, {}),
        ("path_extract interval", "path_extract", None, {"roi": path_square, "spacing": 10}, {}, {}),
        ("path_extract edge_search", "path_extract", path_block, {"mode": "edge_search", "spacing": 10, "search": 12,
                                                                  "caliper_width": 3, "polarity": "dark_to_light", "edge_threshold": 15},
         {"points": [[45, 35], [195, 35]]}, {}),
        ("profile_defect (fit_circle 360)", "profile_defect", None, {"baseline": "fit_circle", "threshold": 3}, {"values": [float(m * 0.12 + (2.0 if 40 <= i < 46 else 0.0)) for i in range(360)], "points": [[s.cx + math.cos(math.radians(i)) * (m * 0.12 + (2.0 if 40 <= i < 46 else 0.0)), s.cy + math.sin(math.radians(i)) * (m * 0.12 + (2.0 if 40 <= i < 46 else 0.0))] for i in range(360)]}, {}),
        ("fit_arc (annulus 90)", "fit_arc", big, {"roi": {"shape": "annulus", "cx": s.cx, "cy": s.cy, "r_inner": m * 0.06, "r_outer": m * 0.18}, "num_rays": 90}, {}, {}),
        ("fit_ellipse (annulus 90)", "fit_ellipse", big, {"roi": {"shape": "annulus", "cx": s.cx, "cy": s.cy, "r_inner": m * 0.06, "r_outer": m * 0.18}, "num_rays": 90}, {}, {}),
        ("wall_thickness 10", "wall_thickness", big, {"roi": {"shape": "rect", "x": s.cx - m * 0.2, "y": s.cy - 20, "w": m * 0.4, "h": 40}, "num_calipers": 10}, {}, {}),
        ("concentricity", "concentricity", None, {"max_deviation": 5}, {"a": {"cx": s.cx, "cy": s.cy, "r": 50}, "bx": s.cx + 1, "by": s.cy - 2, "br": 20}, {}),
        ("chamfer_angle 40", "chamfer_angle", big, {"roi": top_edge, "num_calipers": 40}, {}, {}),
        ("tolerance_judge", "tolerance_judge", None, {"nominal": 12, "upper_tol": 0.05, "lower_tol": -0.05}, {"value": 12.02}, {"_outputs": {}}),
        ("contour_find (mask)", "contour_find", s.mask, {"threshold_method": "none", "min_area": 300}, {}, {}),
        ("barcode_grade (Data Matrix roi)", "barcode_grade", s.dm_image, {"roi": s.dm_roi, "symbology": "datamatrix"}, {}, {}),
        ("barcode_grade (Data Matrix full image)", "barcode_grade", s.dm_image, {"symbology": "datamatrix"}, {}, {}),
        ("barcode (Data Matrix, zxing)", "barcode", s.dm_image, {"roi": s.dm_roi, "types": "2d"}, {}, {}),
        ("photometric_stereo (4 lights, drop darkest)", "photometric_stereo", s.lit[0], {"output": "curvature"}, {"image_1": s.lit[1], "image_2": s.lit[2], "image_3": s.lit[3]}, {}),
        ("photometric_stereo (4 lights, plain)", "photometric_stereo", s.lit[0], {"output": "curvature", "drop_darkest": False}, {"image_1": s.lit[1], "image_2": s.lit[2], "image_3": s.lit[3]}, {}),
        ("gdt_measure straightness 2000", "gdt_measure", None, {"mode": "straightness", "tolerance": 20}, {"points": [[x, 5 * math.sin(x / 50)] for x in np.linspace(0, 1000, 2000)]}, {}),
        ("gdt_measure roundness 360 (MZC)", "gdt_measure", None, {"mode": "roundness", "tolerance": 5}, {"points": [[s.cx + (100 + 1.5 * math.cos(3 * math.radians(i))) * math.cos(math.radians(i)), s.cy + (100 + 1.5 * math.cos(3 * math.radians(i))) * math.sin(math.radians(i))] for i in range(360)]}, {}),
        ("gdt_measure perpendicularity", "gdt_measure", None, {"mode": "perpendicularity", "tolerance": 2}, {"a": {"x1": 50, "y1": 50, "x2": 52, "y2": 250}, "b": {"x1": 0, "y1": 0, "x2": 300, "y2": 0}}, {}),
        ("contour_find (gray otsu roi)", "contour_find", gray, {"roi": plate, "polarity": "dark"}, {}, {}),
        ("contour_filter", "contour_filter", None, {"min_area": 300, "min_convexity": 0.5}, {"contours": mask_contours}, {}),
        ("contour_geometry", "contour_geometry", None, {"defect_depth": 3}, {"contours": mask_contours}, {}),
        ("contour_match", "contour_match", None, {"template": "shape", "max_distance": 0.2}, {"contours": mask_contours}, {}),
        ("line_profile", "line_profile", big, {"roi": {"shape": "line", "x1": s.cx - m * 0.2, "y1": s.cy, "x2": s.cx + m * 0.2, "y2": s.cy}}, {}, {}),
        ("color_stats", "color_stats", big, {"roi": plate}, {}, {}),
        ("geometry intersect", "geometry", None, {"mode": "intersect"}, {"a": {"x1": 0, "y1": 0, "x2": 100, "y2": 100}, "b": {"x1": 0, "y1": 100, "x2": 100, "y2": 0}}, {}),
        ("geometry median", "geometry", None, {"mode": "median"}, {"a": {"x1": 0, "y1": 0, "x2": 100, "y2": 0}, "b": {"x1": 0, "y1": 20, "x2": 100, "y2": 20}}, {}),
        ("geometry circle_3pts", "geometry", None, {"mode": "circle_3pts"}, {"a": [0, 0], "b": [10, 0], "c": [5, 5]}, {}),
        ("geometry offset", "geometry", None, {"mode": "offset", "offset_x": 12, "offset_y": -5}, {"points": [[1.0, 2.0], [3.0, 4.0]]}, {}),
        ("distance circle-circle", "distance", None, {"mode": "nearest"}, {"a": {"cx": 0, "cy": 0, "r": 5}, "b": {"cx": 30, "cy": 0, "r": 5}}, {}),
        ("points_merge", "points_merge", None, {}, {"a": [[float(i), float(i)] for i in range(200)], "b": [5.0, 6.0]}, {}),
        ("blob separate", "blob", s.mask, {"threshold_method": "none", "min_area": 300, "separate": True}, {}, {}),
        # detect
        ("blob (gray, fixed)", "blob", gray, {"threshold_method": "fixed", "threshold": 60, "polarity": "dark", "min_area": 300}, {}, {}),
        ("blob (mask, none)", "blob", s.mask, {"threshold_method": "none", "min_area": 300}, {}, {}),
        ("blob (roi circle)", "blob", gray, {"roi": center_circle, "threshold_method": "fixed", "threshold": 60, "polarity": "dark", "min_area": 300}, {}, {}),
        ("blob hysteresis", "blob", blob_hyst, {"threshold_method": "hysteresis", "threshold": 200, "threshold_low": 100, "min_area": 300}, {}, {}),
        ("blob soft", "blob", blob_soft, {"threshold_method": "soft", "threshold": 150, "soft_width": 60, "min_area": 300}, {}, {}),
        ("blob_label", "blob_label", None, {"classes": "1:scratch\n2:dent", "min_area": 300}, {"labels": label_map}, {}),
        ("defect_stat phase (roi)", "defect_stat", big, {"model": "stat", "roi": plate, "sigma": 4}, {}, {}),
        ("defect_stat none (roi)", "defect_stat", big, {"model": "stat", "roi": plate, "sigma": 4, "align": "none"}, {}, {}),
        ("defect_diff phase", "defect_diff", big, {"template": "golden", "align": "phase"}, {}, {}),
        ("defect_diff none roi", "defect_diff", big, {"template": "golden", "align": "none", "roi": plate}, {}, {}),
        ("barcode", "barcode", big, {"roi": plate}, {}, {}),
        ("ocr_read taught font (400x80)", "ocr_read", s.ocr_line, {"model": "font", "roi": {"shape": "rect", "x": s.w / 2 - 200, "y": s.h / 2 - 40, "w": 400, "h": 80}, "charset": "digits"}, {}, {}),
        ("ocr_read pattern", "ocr_read", s.ocr_line, {"model": "font", "roi": {"shape": "rect", "x": s.w / 2 - 200, "y": s.h / 2 - 40, "w": 400, "h": 80}, "charset": "digits", "pattern": "NNNNNNNN"}, {}, {}),
        ("ocv_verify", "ocv_verify", None, {"expected": "########"}, {"text": "24091237", "items": [{"text": "24091237", "box": [[0, 0], [1, 0], [1, 1], [0, 1]], "confidence": 0.9, "chars": [{"ch": c, "conf": 0.9, "box": [[i, 0], [i + 1, 0], [i + 1, 1], [i, 1]]} for i, c in enumerate("24091237")]}]}, {}),
        ("text_presence", "text_presence", big, {"roi": s.rect(-0.1, 0.12, 0.2, 0.06)}, {}, {}),
        ("color_check", "color_check", big, {"roi": plate, "color": "#c8c8cd"}, {}, {}),
        ("edge_density", "edge_density", big, {"roi": plate}, {}, {}),
        ("pixel_count (full)", "pixel_count", s.mask, {}, {}, {}),
        ("pixel_count (circle)", "pixel_count", s.mask, {"roi": center_circle}, {}, {}),
        # dl
        ("dl_anomaly (fake backbone, roi)", "dl_anomaly", big, {"model": "anomaly", "roi": plate, "device": "cpu"}, {}, {}),
        ("dl_retrieval (fake backbone)", "dl_retrieval", s.retrieval_probe, {"model": "retrieval", "topk": 1, "device": "cpu"}, {}, {}),
        ("dl_classify", "dl_classify", big, {"model": "gap", "roi": plate}, {}, {}),
        ("dl_detect", "dl_detect", big, {"model": "yolo", "labels": "a\nb\nc\nd", "roi": plate, "conf": 0.1}, {}, {}),
        ("dl_segment", "dl_segment", big, {"model": "idn", "roi": plate}, {}, {}),
        ("dl_instance", "dl_instance", big, {"model": "seg", "labels": "obj", "conf": 0.5, "roi": plate}, {}, {}),
        # yolo（原生 ultralytics；只在 VISION_TEST_DL=1 時納入：需要 torch＋官方底模）
        *([("ai_detect", "ai_detect", big, {"model_name": "yolo11n.pt", "roi": plate, "conf": 0.1}, {}, {}),
           ("ai_segment", "ai_segment", big, {"model_name": "yolo11n-seg.pt", "roi": plate, "conf": 0.1}, {}, {}),
           ("ai_classify", "ai_classify", big, {"model_name": "yolo11n-cls.pt", "roi": plate}, {}, {}),
           ("ai_pose", "ai_pose", big, {"model_name": "yolo11n-pose.pt", "conf": 0.1}, {}, {}),
           ("ai_obb", "ai_obb", big, {"model_name": "yolo11n-obb.pt", "conf": 0.1}, {}, {})] if os.environ.get("VISION_TEST_DL") == "1" else []),
        # logic
        ("if_number", "if_number", None, {"operator": "eq", "threshold": 5}, {"value": 5}, {}),
        ("in_range", "in_range", None, {"low": 0, "high": 10}, {"value": 5}, {}),
        ("bool_logic", "bool_logic", None, {"mode": "and"}, {"values": [True, True, False]}, {}),
        ("formula", "formula", None, {"expression": "abs(a-b)/c*100"}, {"a": 3, "b": 1, "c": 4}, {}),
        ("parse_message", "parse_message", None, {"separator": "|", "fields": "lot\ndate\nslot:int\nw:float*0.01"}, {"text": "LOT12345|2026-09-08|7|1234"}, {}),
        ("switch", "switch", None, {"cases": "A17\nB22\nC30"}, {"value": "B22"}, {}),
        ("string_match", "string_match", None, {"list": "OK\nPASS", "match": "contains"}, {"text": "the PASS one"}, {}),
        ("python_script", "python_script", gray, {"code": SCRIPT_TEMPLATE}, {}, {"_script_admin": True}),
        ("boxes_merge", "boxes_merge", None, {"mode": "iou", "threshold": 0.5, "keep": "highest_score"}, {"matches": merge_matches}, {}),
        ("array_correct", "array_correct", None, {"rows": 3, "cols": 4, "tolerance": 2}, {"matches": grid_matches}, {}),
        ("count_list", "count_list", None, {}, {"items": list(range(100))}, {}),
        # output
        ("judge", "judge", None, {"verdict": "by_input"}, {"value": True}, {}),
        ("output", "output", None, {"name": "v"}, {"value": 1.23456}, {}),
        ("write_log csv", "write_log", None, {"path": "bench", "format": "csv", "fields": "judge\nv\nlot\n{a:.2f}", "filename": "{station}_{date}", "daily_folder": True}, {"a": 12.3456}, {"_judge": "OK", "_outputs": {"v": 1.23456}, "lot": "A17", "_sandbox": True}),
        ("trigger_flow", "trigger_flow", None, {"target_flow_id": 1, "mode": "async"}, {}, {"_sandbox": True}),
        ("write_modbus", "write_modbus", None, {"connection": "bench_sim", "mapping": [{"src": "judge", "address": "ok"}]}, {}, {"_judge": "OK"}),
        ("read_modbus", "read_modbus", None, {"connection": "bench_sim", "mapping": [{"name": "ok", "address": "ok"}]}, {}, {}),
        ("send_image (degraded)", "send_image", gray, {"connection": "bench_sim"}, {}, {"_judge": "OK"}),
        ("save_image png", "save_image", gray, {"folder": os.path.join(s.folder, "saved"), "format": "png", "split_by_judge": False}, {}, {"_sandbox": True}),
        ("draw_result", "draw_result", big, {}, {"overlays": overlays}, {"_judge": "ok"}),
    ]


def _bench_connection() -> None:
    """整合工具（write_modbus／read_modbus）需要一條連線；用只記在記憶體的假連線，不碰硬體。"""
    from apps.comm.writers import Writer, register_writer

    class _MemoryWriter(Writer):
        kind = "bench_memory"

        def __init__(self, config, **kw):
            super().__init__(config, **kw)
            self.state = {}

        def _write(self, values):
            self.state.update(values)
            return {"written": len(values)}

        def _read(self, addresses):
            return {a: self.state.get(a) for a in addresses}

    register_writer("bench_sim", _MemoryWriter({}, name="bench_sim"))


def bench_tools(s: Scene, out: io.StringIO) -> dict[str, tuple[float, float]]:
    _bench_connection()
    rows: dict[str, tuple[float, float]] = {}
    out.write(f"\n== 工具 @ {s.w}×{s.h}（median / p95 ms，{RUNS} 次，暖機 {WARMUP}）==\n")
    out.write(f"{'工具':<28}{'median':>10}{'p95':>10}   狀態 / 訊息\n")
    for name, key, image, params, inputs, context in cases(s):
        tool = base.get(key)

        def run() -> Result:
            return tool.execute(make_ctx(key, image, params, inputs, s.assets, dict(context)))

        try:
            med, p95, res = timeit(run)
            msg = f"{res.status} {res.message[:48]}"
        except Exception as exc:  # noqa: BLE001
            med, p95, msg = float("nan"), float("nan"), f"EXC {type(exc).__name__}: {str(exc)[:60]}"
        rows[name] = (med, p95)
        out.write(f"{name:<28}{med:>10.3f}{p95:>10.3f}   {msg}\n")
    return rows


def bench_engine(s: Scene, out: io.StringIO) -> None:
    graph = validate_graph(hole_count_flow(1))
    compiled = compile_graph(graph)
    img = s.image

    def run(preview: bool = False) -> engine.RunReport:
        return engine.execute(compiled, flow_id=1, flow_version=1, trigger="bench", grab=lambda sid: img, asset_path=lambda aid: None, preview=preview)

    for preview in (False, True):
        med, p95, rep = timeit(lambda: run(preview))
        out.write(f"\n== 引擎：示範流程「零件孔數檢測」@ {s.w}×{s.h} preview={preview}：median {med:.3f} ms / p95 {p95:.3f} ms（status={rep.status}）==\n")
        node_sum = 0.0
        for nid, r in rep.nodes.items():
            node_sum += r.duration_ms
            out.write(f"  {nid:<8}{r.status:<8}{r.duration_ms:>9.3f} ms  {r.message[:50]}\n")
        n = len(rep.nodes)
        out.write(f"  節點工具時間合計 {node_sum:.3f} ms；引擎固定開銷 {rep.duration_ms - node_sum:.3f} ms（{(rep.duration_ms - node_sum) / max(1, n) * 1000:.1f} µs/節點，{n} 節點）\n")


def bench_overhead(out: io.StringIO) -> None:
    """純引擎開銷：一串 formula 節點（工具本身幾乎不花時間）。"""
    n = 40
    nodes = [{"id": f"f{i}", "type": "formula", "enabled": True, "params": {"expression": "a+1" if i else "1"}, "position": {"x": 0, "y": 0}} for i in range(n)]
    edges = [{"id": f"e{i}", "source": f"f{i - 1}", "target": f"f{i}", "source_handle": "value", "target_handle": "a"} for i in range(1, n)]
    compiled = compile_graph(validate_graph({"nodes": nodes, "edges": edges}))
    med, p95, rep = timeit(lambda: engine.execute(compiled, flow_id=1, flow_version=1, trigger="bench", grab=lambda s: None, asset_path=lambda a: None))
    tool_ms = sum(r.duration_ms for r in rep.nodes.values())
    out.write(f"\n== 引擎固定開銷：{n} 個 formula 節點串接：整體 median {med:.3f} ms（{med / n * 1000:.1f} µs/節點；其中工具 {tool_ms / n * 1000:.1f} µs/節點）==\n")


def bench_encode(s: Scene, out: io.StringIO) -> None:
    st = ImageStore()
    st.put("r:n:image", s.image, flow_id=1, run_id="r")
    st.put("r:n:gray", s.gray, flow_id=1, run_id="r")
    out.write(f"\n== ImageStore.encode @ {s.w}×{s.h}（cold = 每次重新編碼；cached = store.encode 同 ref 同尺寸的快取命中）==\n")
    for ref, label in (("r:n:image", "BGR"), ("r:n:gray", "gray")):
        img = st.get(ref)
        for max_side in (None, 1600, 1024, 320):
            med, p95, data = timeit(lambda: encode_image(img, max_side=max_side))
            cmed, _, _ = timeit(lambda: st.encode(ref, max_side=max_side))
            out.write(f"  {label:<5} max_side={str(max_side):<5} jpeg85  cold {med:>8.3f} / {p95:>8.3f} ms   cached {cmed:>7.3f} ms  ({len(data) / 1024:.0f} KB)\n")
    med, p95, data = timeit(lambda: encode_image(st.get("r:n:image"), max_side=1024, fmt="png"))
    out.write(f"  BGR   max_side=1024  png     cold {med:>8.3f} / {p95:>8.3f} ms  ({len(data) / 1024:.0f} KB)\n")


def bench_registration(out: io.StringIO, folder: str) -> None:
    """兩張註冊圖、640×480 單尺度；假模型驗流程，有正式模型時另列實際 CPU 耗時。"""
    from django.conf import settings
    from django.test import override_settings

    from apps.vision import demo_images, fixed_images
    from apps.vision.dl import anomaly

    installed = anomaly.backbone_path()
    models = [("fake", fake_backbone(os.path.join(folder, "register_backbone.onnx"), 320))]
    if os.path.isfile(installed):
        models.append(("installed", installed))
    image = demo_images.registered_parts()[0]
    patch = image[48:144, 64:160]
    with override_settings(VISION={**settings.VISION, "ASSET_DIR": os.path.join(folder, "registration")}):
        refs = [fixed_images.store(patch, "Part"), fixed_images.store(np.clip(patch.astype(np.int16) - 5, 0, 255).astype(np.uint8), "Dim part")]
        out.write("\n== register_detect @ 640×480, 2 registrations, single scale, CPU ==\n")
        for label, path in models:
            for mode in ("detect", "count"):
                params = {"registrations": refs, "backbone_path": path, "device": "cpu", "mode": mode, "min_similarity": 0.9, "min_count": 3, "max_count_ok": 3}
                tool = base.get("register_detect")
                med, p95, result = timeit(lambda: tool.execute(make_ctx("register_detect", image, params, {}, {}, {})))
                assert result.status == "ok" and result.outputs["count"] == 3, result
                out.write(f"register_detect ({mode}, {label})  median {med:.3f} / p95 {p95:.3f} ms   {result.status} {result.message}\n")


def main() -> None:
    global RUNS, REPEAT
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--runs", type=int, default=RUNS)
    ap.add_argument("--repeat", type=int, default=REPEAT, help="每個量測重複幾輪取最小 median")
    ap.add_argument("--pin", action="store_true", help="綁 P-core＋高優先權（Windows）")
    args = ap.parse_args()
    RUNS = args.runs
    REPEAT = args.repeat
    pin_note = pin_process() if args.pin else "未綁核心"
    out = io.StringIO()
    out.write(f"VisionSequence 工具效能基準  {time.strftime('%Y-%m-%d %H:%M')}\n")
    out.write(f"Python {platform.python_version()}  OpenCV {cv2.__version__}  numpy {np.__version__}  cv2 threads={cv2.getNumThreads()}  {platform.processor()}\n")
    out.write(f"每工具 {RUNS} 次取 median／p95，重複 {REPEAT} 輪取最小值；{pin_note}\n")
    folder = tempfile.mkdtemp(prefix="vs-bench-")
    bench_registration(out, folder)
    scenes = [Scene(1280, 960, folder), Scene(640, 480, folder)]
    for s in scenes:
        bench_tools(s, out)
    for s in scenes:
        bench_engine(s, out)
    bench_overhead(out)
    for s in scenes:
        bench_encode(s, out)
    text = out.getvalue()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    if args.output:
        with open(os.path.join(ROOT, args.output) if not os.path.isabs(args.output) else args.output, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
