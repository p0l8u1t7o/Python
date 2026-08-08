import copy
import gc
import json
import mmap
import os
import time
import traceback

import cv2 as cv
import numpy as np
import torch
import yaml

# ultralytics 於 import 期會做 DNS 探測（判斷是否連得上網）並在載入模型時
# 檢查 PyPI 是否有新版。產線電腦多半沒有對外網路，這兩件事會卡在逾時上。
# 必須在 import ultralytics 之前設定才有效。
os.environ.setdefault("YOLO_OFFLINE", "1")

from ultralytics import YOLO  # noqa: E402

# ==================================================
# 設定
# ==================================================

# ── 模型 ──────────────────────────────────────────
# MODEL_PATH 必須與 YAML_PATH 為同一次訓練的產物，否則 class id 體系不同，
MODEL_PATH = r"D:\Working Space\Python\VisionStereo\weights\best.pt"

# 類別名稱來源。.pt 內嵌 names，可留空字串 ""；
# .onnx / .engine 不帶 names，必須指定 yaml。
YAML_PATH = r"D:\TrainingImage\ATD\dataset\data.yaml"

TRACKER_CFG = "bytetrack.yaml"

# 推論輸入尺寸（長邊）。前處理會先把影像等比縮到此尺寸再送入模型。
IMGSZ = 640

# 單幀最大偵測數，避免異常畫面造成 NMS 與後處理爆量。
MAX_DET = 100

# 降採樣是否使用 INTER_AREA（盒狀平均，抗鋸齒）。
# 若小物件因鋸齒而漏檢，再開啟並用 PROFILE 確認 prep 階段的實際成本。
RESIZE_ANTIALIAS = False

# ── 過濾條件 ──────────────────────────────────────
CONF_THRES = 0.2          # 需 ≥ bytetrack.yaml 的 new_track_thresh，否則低信心
                          # 偵測無法建立軌跡，track() 會回空
MIN_AREA = 500            # 原始影像座標下的 bbox 面積下限（pixel）

# bbox 任一邊距影像邊緣「小於等於」此值即排除。
#   640×480   → 10~20
#   1920×1080 → 20~50
# 除錯時先設 0，確認不是這條把結果濾光。
EDGE_MARGIN = 50

# 只保留指定 class id；None = 全部保留。
ALLOWED_CLASSES = None

# polygon 最大頂點數，超過則等距抽樣
MAX_POLY_POINTS = 12

# 長時間運行後 Kalman Filter 數值可能退化，每 N 幀重置 tracker 狀態
TRACKER_RESET_INTERVAL = 3000

# Python 的循環偵測每幀會掃過大量短命物件（Results / tensor / dict），實測停用
# 可省約 0.5 ms。但完全不回收會讓循環參照無限累積，因此改為每 N 幀手動收一次，
# 把成本集中在單一幀而不是攤在每一幀。
GC_COLLECT_INTERVAL = 600

# ── 診斷 ──────────────────────────────────────────
# LabVIEW Python Node 不顯示 stdout，訊息一律寫檔。產線運行時兩者都設 False。
DEBUG = False             # 分階段過濾數量
PROFILE = False           # 各階段耗時滾動平均
DBG_LOG = r"D:\Working Space\Python\VisionStereo\execute_debug.log"


DBG_STAT_INTERVAL = 60    # 影像統計每 N 幀算一次
DBG_STAT_STRIDE = 8       # 統計取樣間隔（只在 1/64 的像素上計算）
PROFILE_INTERVAL = 100    # 每 N 幀輸出一次 profile

# ==================================================
# 模組狀態
# ==================================================

_g_reader = None
_g_prep = None
_g_model = None
_g_names = None
_g_device = None
_g_half = False
_g_frame_count = 0
_g_allowed_np = None
_g_track_kw = None

_dbg_fh = None
_prof_acc = {}
_prof_n = 0


# ==================================================
# 診斷工具
# ==================================================

def _dbg_open():
    """常駐 log file handle。每次寫入都 open/close 在 Windows 上成本很高。"""
    global _dbg_fh
    if _dbg_fh is None:
        try:
            _dbg_fh = open(DBG_LOG, "a", encoding="utf-8", buffering=1)
        except Exception:
            _dbg_fh = False          # False = 開檔失敗，不再重試
    return _dbg_fh


def _dbg(msg):
    if not (DEBUG or PROFILE):
        return
    fh = _dbg_open()
    if fh:
        try:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass


def _log_error(msg):
    """錯誤訊息無視 DEBUG 設定一律寫檔，這是唯一能看到 traceback 的管道。"""
    fh = _dbg_open()
    if fh:
        try:
            fh.write(f"{time.strftime('%H:%M:%S')} [ERROR] {msg}\n")
            fh.flush()
        except Exception:
            pass


def _prof(stage, dt):
    if PROFILE:
        _prof_acc[stage] = _prof_acc.get(stage, 0.0) + dt


def _prof_dump():
    parts = [f"{k}={v * 1000.0 / _prof_n:.2f}ms"
             for k, v in sorted(_prof_acc.items(), key=lambda kv: -kv[1])]
    _dbg(f"[profile n={_prof_n}] " + "  ".join(parts))


def _prof_tick():
    """一幀結束，必要時輸出平均耗時（ms）並重新計數。"""
    global _prof_n
    if not PROFILE:
        return
    _prof_n += 1
    if _prof_n >= PROFILE_INTERVAL:
        _prof_dump()
        _prof_acc.clear()
        _prof_n = 0


# ==================================================
# MMap Reader
# ==================================================
# fmt（IMAQ 影像型別代碼）-> (dtype, bytes_per_pixel, channels)
# bytes_per_pixel 為單一像素「所有 channel 加總」的位元組數，
# 用來換算每一列（row）在記憶體中的實際跨距（stride）。
FORMATS = {
    0: (np.uint8,   1, 1),   # Grayscale (U8)
    1: (np.int16,   2, 1),   # Grayscale (I16)
    2: (np.float32, 4, 1),   # Grayscale (SGL)
    4: (np.uint8,   4, 4),   # RGB (U32)，記憶體順序 BGRA
    5: (np.uint8,   4, 4),   # HSL (U32)
    6: (np.uint16,  8, 4),   # RGB (U64)，每個 channel 16-bit
    7: (np.uint16,  2, 1),   # Grayscale (U16)
}


class MMapReader:
    """讀取 LabVIEW 寫入的具名共享記憶體。

    line_width 為 IMAQ GetImageInfo 的 Line Width（單位像素，含 padding）。
    size 為映射總長度，0 表示只有單張影像。
    """

    def __init__(self, tag_name, width, height, line_width, fmt, size=0):
        if fmt not in FORMATS:
            raise ValueError(f"不支援的影像型別代碼 fmt={fmt}，"
                             f"可用值：{sorted(FORMATS.keys())}")

        self.dtype, bpp, self.ch = FORMATS[fmt]
        self.w, self.h = width, height
        self.row = (line_width or width) * bpp   # 每列實際 byte 數（含 padding）
        self.valid = width * bpp                 # 每列有效影像資料的 byte 數
        self.frame_bytes = self.row * height     # 單張影像總 byte 數

        # 以唯讀模式開啟 LabVIEW 已建立好的具名記憶體對映
        self.mm = mmap.mmap(-1, size or self.frame_bytes,
                            tagname=tag_name, access=mmap.ACCESS_READ)
        self.buf = np.frombuffer(self.mm, dtype=np.uint8)
        self.buf[::4096].sum()          # prefault，把 page fault 成本移到開場

        # 有無 padding 決定能否走 zero-copy 的快路徑
        self.no_padding = (self.row == self.valid)

    def read_frame(self, offset=0, copy=False):
        """回傳一張影像的 numpy array。

        預設為 zero-copy view，與共享記憶體共用同一塊資料——
        下一次 LabVIEW 寫入會直接改變內容，因此必須在本幀內用完。
        """
        raw = self.buf[offset:offset + self.frame_bytes].reshape(self.h, self.row)
        blk = raw[:, :self.valid]

        # 非 uint8 型別若因裁掉 padding 而不連續，view() 轉型前必須先複製
        if copy or (self.dtype != np.uint8 and not self.no_padding):
            blk = np.ascontiguousarray(blk)

        arr = blk if self.dtype == np.uint8 else blk.view(self.dtype)
        return arr.reshape(self.h, self.w, self.ch) if self.ch > 1 \
            else arr.reshape(self.h, self.w)

    def close(self):
        self.buf = None
        if self.mm is not None:
            self.mm.close()
        self.mm = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ==================================================
# FramePrep
# ==================================================

class FramePrep:
    """把 IMAQ 影像正規化成 YOLO 需要的 (h', w', 3) uint8 BGR。

    處理順序刻意設計為「先縮放、再轉位元深度、最後轉通道」：

        2048x1536 灰階先轉 BGR 再讓模型縮放
            → 需寫入 2048x1536x3 ≈ 9 MB
        先縮到 640x480 再轉 BGR
            → 需寫入 640x480x3 ≈ 0.9 MB

    兩者送進模型的內容等價，但後者省下約一個數量級的記憶體頻寬。
    所有輸出緩衝區於建構時一次配置完成，每幀重複使用。

    縮放倍率記錄於 inv_scale_*，供後處理把座標還原回原始影像尺度。
    """

    # RESIZE_ANTIALIAS 開啟且縮小超過兩倍時才用 INTER_AREA。
    # 它能抑制高倍降採樣的鋸齒，但成本是 INTER_LINEAR 的十餘倍。
    _AREA_THRESHOLD = 0.5

    def __init__(self, height, width, channels, dtype, imgsz=IMGSZ):
        self.src_h, self.src_w = height, width
        self.src_ch = channels
        self.src_dtype = np.dtype(dtype)

        # 等比縮放，不放大
        scale = min(1.0, float(imgsz) / max(height, width))
        self.dst_w = max(1, int(round(width * scale)))
        self.dst_h = max(1, int(round(height * scale)))
        self.need_resize = (self.dst_w != width or self.dst_h != height)

        # 用實際整數尺寸回推倍率，避免 round 造成的累積誤差
        self.scale_x = self.dst_w / width
        self.scale_y = self.dst_h / height
        self.inv_scale_x = width / self.dst_w
        self.inv_scale_y = height / self.dst_h

        self.interp = (cv.INTER_AREA
                       if (RESIZE_ANTIALIAS and scale < self._AREA_THRESHOLD)
                       else cv.INTER_LINEAR)

        # 16/32-bit 來源用固定倍率轉 8-bit。動態 min/max 需要整張影像的完整
        # 走訪，成本過高，而且會讓每幀的亮度基準浮動、影響推論穩定性。
        if self.src_dtype == np.uint16:
            self.depth_alpha = 1.0 / 256.0      # 16-bit → 8-bit
        elif self.src_dtype == np.int16:
            self.depth_alpha = 1.0 / 128.0      # 取正半段
        elif self.src_dtype == np.float32:
            self.depth_alpha = 255.0            # 假設來源已正規化到 0~1
        else:
            self.depth_alpha = None

        # ── 預配置緩衝區 ──────────────────────────
        rs_shape = ((self.dst_h, self.dst_w, channels) if channels > 1
                    else (self.dst_h, self.dst_w))
        self._buf_resized = np.empty(rs_shape, dtype=self.src_dtype)
        self._buf_u8 = np.empty(rs_shape, dtype=np.uint8)
        self._buf_bgr = np.empty((self.dst_h, self.dst_w, 3), dtype=np.uint8)

    def __call__(self, raw):
        """回傳 (dst_h, dst_w, 3) uint8 BGR。輸出緩衝區重複使用。"""
        img = raw

        # 1) 縮放：在來源原始通道數與位元深度下進行，搬移的資料量最小
        if self.need_resize:
            img = cv.resize(img, (self.dst_w, self.dst_h),
                            dst=self._buf_resized, interpolation=self.interp)

        # 2) 位元深度 → uint8
        if self.depth_alpha is not None:
            img = cv.convertScaleAbs(img, dst=self._buf_u8,
                                     alpha=self.depth_alpha)

        # 3) 通道 → BGR
        if img.ndim == 2:
            return cv.cvtColor(img, cv.COLOR_GRAY2BGR, dst=self._buf_bgr)

        ch = img.shape[2]
        if ch == 4:                                  # IMAQ U32 為 BGRA 排列
            return cv.cvtColor(img, cv.COLOR_BGRA2BGR, dst=self._buf_bgr)
        if ch == 1:
            return cv.cvtColor(img[:, :, 0], cv.COLOR_GRAY2BGR,
                               dst=self._buf_bgr)
        if ch == 3:
            return img if img.flags["C_CONTIGUOUS"] else np.ascontiguousarray(img)

        raise ValueError(f"無法處理的影像通道數：{img.shape}")


# ==================================================
# 類別名稱
# ==================================================

def _normalize_names(raw):
    """list / dict 形式的 names 統一成 {int: str}。"""
    if isinstance(raw, dict):
        return {int(k): v for k, v in raw.items()}
    return {i: n for i, n in enumerate(raw)}


def _load_names_from_yaml(yaml_path):
    """支援 list 格式（names: [a, b]）與 dict 格式（names: {0: a, 1: b}）。"""
    if not yaml_path or not os.path.exists(yaml_path):
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _normalize_names(data.get("names", {}))


# ==================================================
# 幾何工具
# ==================================================

def _border_hit_mask(polys, width, height, margin_x, margin_y):
    """向量化判斷每個 polygon 的外接框是否碰到影像邊界。

    polys 為 list[ndarray(N,2)]，座標系需與 width / height / margin 一致。
    回傳 bool ndarray，True = 碰到邊界（應排除）。
    """
    n = len(polys)
    if n == 0:
        return np.zeros(0, dtype=bool)

    counts = np.fromiter((len(p) for p in polys), dtype=np.int64, count=n)
    empty = (counts == 0)
    result = empty.copy()

    idx = np.flatnonzero(~empty)
    if idx.size == 0:
        return result

    # 全部頂點串成單一陣列，用 reduceat 一次算出所有 polygon 的 min/max
    all_pts = np.concatenate([polys[i] for i in idx], axis=0)
    seg = np.zeros(idx.size, dtype=np.int64)
    if idx.size > 1:
        np.cumsum(counts[idx][:-1], out=seg[1:])

    min_xy = np.minimum.reduceat(all_pts, seg)
    max_xy = np.maximum.reduceat(all_pts, seg)

    result[idx] = (
        (min_xy[:, 0] < margin_x) |
        (min_xy[:, 1] < margin_y) |
        (max_xy[:, 0] > width - 1 - margin_x) |
        (max_xy[:, 1] > height - 1 - margin_y)
    )
    return result


def _poly_and_centroid(pts, sx, sy, max_points=MAX_POLY_POINTS):
    """簡化 polygon 並計算質心，同時把座標還原到原始影像尺度。

    pts 來自 r.masks.xy[i]，為推論影像（縮放後）的座標。
    先在小尺度上做 approxPolyDP（頂點少、運算量低），最後才乘上還原倍率。
    """
    if pts is None or len(pts) < 3:
        return [], None

    cnt = np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2)

    M = cv.moments(cnt)
    if M["m00"] > 0:
        cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
    else:
        bx, by, bw, bh = cv.boundingRect(cnt)
        cx, cy = bx + bw * 0.5, by + bh * 0.5
    centroid = [int(round(cx * sx)), int(round(cy * sy))]

    eps = 0.01 * cv.arcLength(cnt, True)
    poly = cv.approxPolyDP(cnt, eps, True).reshape(-1, 2).astype(np.float32)

    if len(poly) > max_points:
        poly = poly[np.linspace(0, len(poly) - 1, max_points).astype(np.int64)]

    poly[:, 0] *= sx
    poly[:, 1] *= sy
    return np.rint(poly).astype(np.int32).tolist(), centroid


# ==================================================
# Tracker
# ==================================================

def _reset_trackers():
    """清空 ByteTrack 內部狀態（Kalman Filter、track id 池）。

    不使用 predictor = None：那會讓下次 track() 重新 register_tracker()，
    而註冊是透過 add_callback 完成的，重複註冊會使 callback list 持續累積，
    每幀執行多份 tracker 更新，時間一長效能穩定劣化。
    """
    trackers = getattr(getattr(_g_model, "predictor", None), "trackers", None)
    if not trackers:
        return
    for t in trackers:
        if hasattr(t, "reset"):
            t.reset()
        else:                                    # 舊版 ultralytics 沒有 reset()
            for attr in ("tracked_stracks", "lost_stracks", "removed_stracks"):
                if hasattr(t, attr):
                    setattr(t, attr, [])
            if hasattr(t, "frame_id"):
                t.frame_id = 0


# ==================================================
# Initialize
# ==================================================

def _precision_kwargs(half):
    """回傳這個 ultralytics 版本用來指定推論精度的參數。

    新版把 half 併入 quantize（內部就是 half=True → quantize=16），舊參數雖然
    仍可用，但每次呼叫都會噴一次 deprecation warning。這裡直接給等價的新參數，
    舊版偵測不到 quantize 時退回 half。
    """
    try:
        from ultralytics.cfg import DEFAULT_CFG_DICT
        if "quantize" in DEFAULT_CFG_DICT:
            return {"quantize": 16 if half else None}
    except Exception:
        pass
    return {"half": half}


class _FlatForward(torch.nn.Module):
    """把模型輸出攤平成兩個 tensor。

    原始輸出是 [(preds, protos), {...}]，最後那個 dict 讓 tracer 無法推導型別。
    """

    def __init__(self, module):
        super().__init__()
        self.module = module

    def forward(self, x):
        y = self.module(x)
        return y[0][0], y[0][1]              # preds, protos


def _install_torchscript(dummy):
    """把前向改成由 TorchScript 執行。

    模型每幀要在 Python 裡逐一走過三百多個 nn.Module，這層直譯器成本佔了前向
    約三成（實測 9.28 ms → 6.63 ms）。trace 之後 kernel 與順序完全相同，只是改
    由 C++ 依序送出，輸出為 bit-identical。

    只覆寫 backend.forward，不動 predictor.model.model 本身——ultralytics 有多處
    要從那個物件取 names / end2end / Detect 層（ReID pre-hook），換掉會踩雷。

    任何一步失敗或數值對不上就保持原本的 eager 路徑，不影響可用性。
    """
    pred = getattr(_g_model, "predictor", None)
    backend = getattr(getattr(pred, "model", None), "backend", None)
    module = getattr(backend, "model", None)
    if not isinstance(module, torch.nn.Module):
        _dbg("torchscript: 找不到可 trace 的模型，維持 eager")
        return

    sample = pred.preprocess([dummy])
    in_shape = tuple(sample.shape)
    best = best_name = None

    with torch.inference_mode():
        ref = _FlatForward(module).eval()(sample)

        # 必須對「副本」做 trace。trace 出來的圖與原模組共用參數張量，而 freeze
        # 與 optimize_for_inference 會就地折疊權重——直接 trace 會把原本的 eager
        # 模型一起改掉，而且改完 eager 與 traced 仍然彼此一致，光比對兩者看不出來。
        try:
            flat = _FlatForward(copy.deepcopy(module)).eval()
            frozen = torch.jit.freeze(
                torch.jit.trace(flat, (sample,), check_trace=False).eval())
        except Exception:
            _log_error("torchscript trace 失敗，維持 eager 路徑\n"
                       + traceback.format_exc())
            return

        # 逐個候選版本驗證：必須與 eager 完全相同（不是相近）才採用。
        # optimize_for_inference 會再做一次圖層融合，有可能改變數值，所以獨立驗證。
        for name, mod in (("optimize_for_inference",
                           _try(lambda: torch.jit.optimize_for_inference(frozen))),
                          ("freeze", frozen)):
            if mod is None:
                continue
            try:
                for _ in range(10):
                    got = mod(sample)
            except Exception:
                continue
            if all(torch.equal(a, b) for a, b in zip(ref, got)):
                best, best_name = mod, name
                break
            _dbg(f"torchscript: {name} 數值與 eager 不一致，試下一個")

        # 再確認原模組本身沒被折疊動到，否則連退回 eager 都是錯的
        intact = all(torch.equal(a, b) for a, b in
                     zip(ref, _FlatForward(module).eval()(sample)))

    if not intact:
        _log_error("torchscript: 原模型權重已被更動，這是嚴重問題，請回報")
        return
    if best is None:
        _log_error("torchscript 所有版本皆與 eager 不一致，維持 eager 路徑")
        return

    def _forward(im, augment=False, visualize=False, embed=None, **kwargs):
        # trace 綁定輸入形狀，且不包含 augment / visualize / embed 分支；
        # 只要有任何一項不符就退回原模組，行為與未優化前相同。
        if (augment or visualize or embed is not None or kwargs
                or tuple(im.shape) != in_shape):
            return module(im, augment=augment, visualize=visualize,
                          embed=embed, **kwargs)
        # 第二個元素原本是 yolo26 雙頭的特徵 dict，只有啟用 ReID 的 tracker
        # （botsort / tracktrack / deepocsort）才會讀取，bytetrack 不會。
        return [tuple(best(im)), {}]

    backend.forward = _forward
    _dbg(f"torchscript ready: {best_name} input={in_shape}")


def _try(fn):
    """執行 fn，失敗回 None。用於「有更好就用、沒有就算了」的可選優化。"""
    try:
        return fn()
    except Exception:
        return None


def initialize(tag_name, width, height, line_width, fmt):
    """開啟共享記憶體、載入模型、完成 warmup。LabVIEW 端呼叫一次即可。"""
    global _g_reader, _g_prep, _g_model, _g_names
    global _g_device, _g_half, _g_allowed_np, _g_frame_count, _g_track_kw

    try:
        if _g_reader is None:
            _g_reader = MMapReader(tag_name, width, height, line_width, fmt)
            _g_prep = FramePrep(height, width, _g_reader.ch,
                                _g_reader.dtype, IMGSZ)
            _dbg(f"reader ready: {width}x{height} fmt={fmt} "
                 f"line_width={line_width} → infer {_g_prep.dst_w}x{_g_prep.dst_h}")

        if _g_model is not None:
            return

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"找不到模型檔：{MODEL_PATH}")

        _g_device = "cuda:0" if torch.cuda.is_available() else "cpu"
        _g_half = (_g_device != "cpu")

        if _g_device != "cpu":
            # cudnn.benchmark 會對「每一種 input shape」窮舉 kernel 組合，實測在
            # 本機單一 shape 就要約 18 秒；而 ultralytics 內部 warmup 用方形
            # imgsz（640x640）、實際推論走 letterbox 後的 640x480，等於要付兩次，
            # initialize() 因此卡住約 37 秒。
            # 本流程是 CPU dispatch bound（GPU 使用率僅約 25%），換 kernel 對穩態
            # 幾乎沒有影響，關掉純賺初始化時間。
            torch.backends.cudnn.benchmark = False

        # 指定 task 可略過從權重反推任務種類的步驟
        _g_model = YOLO(MODEL_PATH, task="segment")
        _g_model.to(_g_device)

        # 類別名稱：優先採用 yaml（確保與訓練時一致），否則用模型內嵌的
        model_names = _normalize_names(_g_model.names)
        yaml_names = _load_names_from_yaml(YAML_PATH)
        _g_names = yaml_names or model_names

        # 類別數不一致代表模型與 yaml 不是同一次訓練的產物，
        # 這是「偵測結果全空」最常見的隱形原因，必須明確告警
        if yaml_names and len(yaml_names) != len(model_names):
            _log_error(f"類別數不一致：yaml={len(yaml_names)} "
                       f"vs model={len(model_names)}。"
                       f"請確認 MODEL_PATH 與 YAML_PATH 為同一次訓練產物。")

        if ALLOWED_CLASSES is not None:
            _g_allowed_np = np.asarray(ALLOWED_CLASSES, dtype=np.int32)

        # 每幀不變的推論參數只組一次。ultralytics 每次 track() 都會把 kwargs
        # 併進設定再做一次完整驗證，重複配置字典沒有意義。
        _g_track_kw = dict(
            persist=True,
            imgsz=IMGSZ,
            tracker=TRACKER_CFG,
            conf=CONF_THRES,
            classes=ALLOWED_CLASSES,     # 下推到 NMS，提早丟棄不需要的類別
            max_det=MAX_DET,
            device=_g_device,
            verbose=False,
            save=False,
            show=False,
            **_precision_kwargs(_g_half),
        )

        # warmup 使用實際推論尺寸與實際推論參數，讓權重載入、cuDNN 演算法選擇與
        # TensorRT 的 JIT 編譯在開場完成，避免前幾幀出現數百 ms 的尖峰
        dummy = np.zeros((_g_prep.dst_h, _g_prep.dst_w, 3), dtype=np.uint8)
        for _ in range(5):
            _g_model.track(dummy, **_g_track_kw)

        # 必須在 predictor 建好（第一次 track 之後）才能取到已融合的模型
        _install_torchscript(dummy)
        for _ in range(3):
            _g_model.track(dummy, **_g_track_kw)

        gc.disable()

        _reset_trackers()
        _g_frame_count = 0
        _dbg(f"model ready: {MODEL_PATH} device={_g_device} "
             f"half={_g_half} classes={len(_g_names)}")

    except Exception:
        _log_error("initialize 失敗\n" + traceback.format_exc())
        raise


# ==================================================
# Execute
# ==================================================

def execute():
    """讀取一張影像、推論、過濾，回傳 JSON array 字串。

    無結果時回傳 "[]"。發生例外時寫入完整 traceback 後 re-raise，
    讓 LabVIEW 收到真正的錯誤，而不是被誤判成「沒有偵測到物件」。
    """
    global _g_frame_count

    try:
        if _g_model is None or _g_reader is None:
            raise RuntimeError("模組尚未初始化，請先呼叫 initialize()")

        t_all = time.perf_counter()
        _g_frame_count += 1

        if _g_frame_count % TRACKER_RESET_INTERVAL == 0:
            _reset_trackers()
            _dbg(f"tracker reset at frame {_g_frame_count}")

        # 自動回收已在 initialize() 停用，這裡定期補一次，避免循環參照累積
        if _g_frame_count % GC_COLLECT_INTERVAL == 0:
            gc.collect()

        # ── 讀取 + 前處理 ───────────────────────────
        t = time.perf_counter()
        raw = _g_reader.read_frame()
        frame = _g_prep(raw)
        _prof("prep", time.perf_counter() - t)

        # 影像統計只在取樣格子上、且每 N 幀算一次。全解析度的 mean/std 會把
        # uint8 升格成 float64 做兩次完整走訪，每幀執行足以吃掉整個 frame budget。
        if DEBUG and _g_frame_count % DBG_STAT_INTERVAL == 1:
            sub = raw[::DBG_STAT_STRIDE, ::DBG_STAT_STRIDE].astype(np.float32)
            std = float(sub.std())
            _dbg(f"[{_g_frame_count}] raw={raw.shape} {raw.dtype} "
                 f"mean={float(sub.mean()):.2f} std={std:.2f}")
            if std < 1e-3:
                _dbg("  !! 影像近乎全平坦，共享記憶體可能沒有實際資料")

        # ── 推論 + 追蹤 ─────────────────────────────
        t = time.perf_counter()
        r = _g_model.track(frame, **_g_track_kw)[0]
        _prof("track", time.perf_counter() - t)

        n_raw = 0 if r.boxes is None else len(r.boxes)
        if DEBUG:
            _dbg(f"  track boxes={n_raw}")
        if n_raw == 0:
            _prof_tick()
            return "[]"

        # ── Tensor → CPU（一次搬移）────────────────
        # boxes.xyxy / conf / cls / id 都只是 boxes.data 的欄位切片，逐一取用
        # 等於對同一塊 GPU 記憶體搬四次、同步四次。先整塊搬回再切欄位，
        # 取到的數值與原本完全相同。欄位位置沿用 Boxes 的定義：
        #   [x1, y1, x2, y2, (track_id), conf, cls]
        t = time.perf_counter()
        boxes = r.boxes
        det = boxes.data.cpu().numpy()                   # 推論尺度，float32
        xyxy = det[:, :4]
        confs = det[:, -2]
        clss = det[:, -1].astype(np.int32)
        is_track = getattr(boxes, "is_track", det.shape[1] == 7)
        ids = (det[:, -3].astype(np.int32) if is_track
               else np.full(n_raw, -1, dtype=np.int32))
        _prof("gpu2cpu", time.perf_counter() - t)

        # ── 過濾：全程在推論尺度進行，門檻換算成同一座標系 ──
        sx, sy = _g_prep.inv_scale_x, _g_prep.inv_scale_y
        dst_w, dst_h = _g_prep.dst_w, _g_prep.dst_h

        # 面積門檻由原始尺度換算，避免對整批 box 做座標還原
        areas_small = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
        valid = (confs >= CONF_THRES) & (areas_small >= MIN_AREA / (sx * sy))

        if _g_allowed_np is not None:
            valid &= np.isin(clss, _g_allowed_np)

        if DEBUG:
            _dbg(f"  after conf/area/class: {int(valid.sum())}")
        if not valid.any():
            _prof_tick()
            return "[]"

        # ── 邊界排除 ────────────────────────────────
        t = time.perf_counter()
        # masks.xy 是 lazy property，第一次存取才抽取輪廓，之後有快取；
        # 這裡是唯一的觸發點。
        masks_xy = r.masks.xy if r.masks is not None else None
        margin_x = EDGE_MARGIN * _g_prep.scale_x
        margin_y = EDGE_MARGIN * _g_prep.scale_y

        if masks_xy is not None:
            vi = np.flatnonzero(valid)
            hit = _border_hit_mask([masks_xy[i] for i in vi],
                                   dst_w, dst_h, margin_x, margin_y)
            valid[vi[hit]] = False
        else:
            valid &= ~(
                (xyxy[:, 0] <= margin_x) |
                (xyxy[:, 1] <= margin_y) |
                (xyxy[:, 2] >= dst_w - 1 - margin_x) |
                (xyxy[:, 3] >= dst_h - 1 - margin_y)
            )
        _prof("edge", time.perf_counter() - t)

        if DEBUG:
            _dbg(f"  after edge filter (margin={EDGE_MARGIN}): {int(valid.sum())}")
        if not valid.any():
            _prof_tick()
            return "[]"

        keep = np.flatnonzero(valid)

        # ── 座標還原：只對留下來的物件做 ────────────
        box_out = xyxy[keep].copy()
        box_out[:, 0::2] *= sx
        box_out[:, 1::2] *= sy
        box_out = np.rint(box_out).astype(np.int32)
        area_out = ((box_out[:, 2] - box_out[:, 0]).astype(np.int64) *
                    (box_out[:, 3] - box_out[:, 1]).astype(np.int64))

        # ── polygon + centroid ─────────────────────
        # 使用 r.masks.xy（輪廓座標）而非 masks.data：後者是 letterbox 後的
        # 模型輸入尺度且含灰邊 padding，直接 resize 會造成系統性座標偏移，
        # 而且要多付一次 mask tensor 的 GPU→CPU 傳輸。
        t = time.perf_counter()
        polys = centroids = None
        if masks_xy is not None:
            polys, centroids = [], []
            for i in keep:
                p, c = _poly_and_centroid(masks_xy[i], sx, sy)
                polys.append(p)
                centroids.append(c)
        _prof("polygon", time.perf_counter() - t)

        # ── 組裝輸出 ────────────────────────────────
        # 迴圈內逐格取 numpy 純量再轉 Python 型別，每個欄位都要走一次 numpy
        # 的純量包裝；整批 tolist() 一次轉完，結果相同但少掉大量中間物件。
        t = time.perf_counter()
        names = _g_names
        id_l = ids[keep].tolist()
        conf_l = confs[keep].tolist()
        cls_l = clss[keep].tolist()
        bbox_l = box_out.tolist()
        area_l = area_out.tolist()

        out = []
        for k in range(len(keep)):
            cls_k = cls_l[k]
            item = {
                "id": id_l[k],
                "bbox": bbox_l[k],
                "conf": round(conf_l[k], 4),
                "cls": cls_k,
                "name": names.get(cls_k, "obj"),
                "area": area_l[k],
            }
            if polys is not None:
                item["polygon"] = polys[k]
                item["centroid"] = centroids[k]
            out.append(item)

        # 緊湊分隔符可減少跨 LabVIEW 邊界傳遞的字串長度
        payload = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
        _prof("json", time.perf_counter() - t)

        if DEBUG:
            _dbg(f"  output={len(out)}")

        _prof("TOTAL", time.perf_counter() - t_all)
        _prof_tick()
        return payload

    except Exception:
        _log_error(f"execute 失敗 (frame {_g_frame_count})\n"
                   + traceback.format_exc())
        raise


# ==================================================
# Get Class Names
# ==================================================

def get_class_names(pt_path=""):
    """回傳類別列表 JSON。pt_path 留空則取用已載入的模型。"""
    try:
        if pt_path:
            tmp = YOLO(pt_path)
            raw_names = tmp.names
            del tmp
        elif _g_model is None:
            return json.dumps({"count": 0, "names": [],
                               "error": "model not initialized"},
                              ensure_ascii=False)
        else:
            raw_names = _g_model.names

        nd = _normalize_names(raw_names)
        names_list = [{"id": k, "name": nd[k]} for k in sorted(nd)]
        return json.dumps({"count": len(names_list), "names": names_list},
                          ensure_ascii=False)

    except Exception as e:
        _log_error("get_class_names 失敗\n" + traceback.format_exc())
        return json.dumps({"count": 0, "names": [], "error": str(e)},
                          ensure_ascii=False)


# ==================================================
# Diagnose
# ==================================================

def diagnose(image_path=""):
    """不經共享記憶體，直接用磁碟影像測試推論路徑。

    用來區分「資料傳遞問題」與「模型／前處理問題」：
    這裡有結果而 execute() 沒有，問題就在 LabVIEW 寫入端。
    image_path 留空則改用當前共享記憶體內容。
    """
    try:
        if _g_model is None:
            return json.dumps({"error": "model not initialized"},
                              ensure_ascii=False)

        if image_path:
            img = cv.imread(image_path, cv.IMREAD_COLOR)
            if img is None:
                return json.dumps({"error": f"cannot read {image_path}"},
                                  ensure_ascii=False)
        elif _g_reader is not None:
            img = _g_prep(_g_reader.read_frame()).copy()
        else:
            return json.dumps({"error": "no image source"}, ensure_ascii=False)

        rp = _g_model.predict(img, imgsz=IMGSZ, conf=CONF_THRES,
                              device=_g_device, half=_g_half, verbose=False)[0]
        rt = _g_model.track(img, persist=False, imgsz=IMGSZ,
                            tracker=TRACKER_CFG, conf=CONF_THRES,
                            device=_g_device, half=_g_half, verbose=False)[0]

        n_pred = 0 if rp.boxes is None else len(rp.boxes)
        n_track = 0 if rt.boxes is None else len(rt.boxes)

        info = {
            "image": list(img.shape),
            "model": MODEL_PATH,
            "device": _g_device,
            "half": _g_half,
            "predict_boxes": n_pred,
            "track_boxes": n_track,
            "has_masks": rp.masks is not None,
            "conf_min": round(float(rp.boxes.conf.min()), 4) if n_pred else None,
            "conf_max": round(float(rp.boxes.conf.max()), 4) if n_pred else None,
        }
        if n_pred and not n_track:
            info["hint"] = ("predict 有結果但 track 為空 → bytetrack.yaml 的 "
                            "new_track_thresh / track_high_thresh 高於 CONF_THRES")

        _dbg(f"diagnose: {info}")
        return json.dumps(info, ensure_ascii=False)

    except Exception as e:
        _log_error("diagnose 失敗\n" + traceback.format_exc())
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================================================
# Cleanup
# ==================================================

def cleanup():
    """釋放共享記憶體與 log handle。LabVIEW 端結束前呼叫。"""
    global _g_reader, _g_prep, _dbg_fh

    # 停用自動回收是整個行程的設定，不是本模組私有的，離開前要還原
    gc.enable()

    if _g_reader is not None:
        _g_reader.close()
        _g_reader = None
    _g_prep = None

    if PROFILE and _prof_n:
        _prof_dump()
    _dbg("cleanup done")

    if _dbg_fh:
        try:
            _dbg_fh.close()
        except Exception:
            pass
    _dbg_fh = None