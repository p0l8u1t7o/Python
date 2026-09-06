"""無監督異常檢測（PatchCore 風格，只教良品）：預訓練 backbone 的中層特徵 → 良品 patch 特徵記憶庫 → 最近鄰距離＝異常分數。

「只餵 30 張良品，就能抓沒看過的缺陷」：訓練即「抽特徵＋建庫」，不需反向傳播，CPU 上數十秒。

- backbone：ResNet18 的 layer2（1/8，128ch）＋ layer3（1/16，256ch）特徵，匯成 ONNX 隨平台附帶到
  ASSET_DIR/dl/weights/resnet18_l2l3.onnx（`manage.py anomaly_backbone --export` 用 torchvision 產生；執行期**不下載**）。
  layer3 上採樣到 layer2 大小後串接 → 384 維，再 3×3 平均（PatchCore 的鄰域聚合）。
- 記憶庫：所有良品 patch 特徵 → coreset greedy（k-center）子抽樣到 coreset_ratio（預設 10%）；選點時用隨機投影到 128 維算距離。
- 推論：查詢 patch 到記憶庫的最近鄰歐氏距離 → 分數圖 → 上採樣到 ROI 尺寸＋高斯平滑；門檻＝訓練集分數的 mean + k·σ。
- 模型資產（npz，kind=model）：bank、bank_sq、backbone ONNX bytes（自包含，工具不必再找第二個檔）、meta JSON。
  載入走模組層快取（mtime＋size），ORT session 依 (路徑, 裝置) 快取並加鎖。
"""

from __future__ import annotations

import io
import json
import os
import threading
from collections import OrderedDict
from typing import Any, Callable

import cv2
import numpy as np
from django.conf import settings

VERSION = 1
BACKBONES = {"resnet18": "resnet18_l2l3"}
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
PROJECTION_DIMS = 128
_BOX3 = np.full((3, 3), 1.0 / 9.0, dtype=np.float32)


class AnomalyError(ValueError):
    """可預期的錯誤（訊息給使用者）。"""


# ---------------------------------------------------------------------------
# backbone
# ---------------------------------------------------------------------------
def weights_dir() -> str:
    return os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")


def backbone_path(name: str = "resnet18") -> str:
    return os.path.join(weights_dir(), f"{BACKBONES.get(name, name)}.onnx")


def backbone_available(name: str = "resnet18") -> bool:
    return os.path.isfile(backbone_path(name))


def export_backbone(path: str | None = None, name: str = "resnet18", opset: int = 17) -> str:
    """用 torchvision 的 ImageNet 預訓練 ResNet18 匯出 layer2／layer3 特徵 ONNX（開發／打包時執行，需要 torch＋torchvision）。"""
    try:
        import torch
        import torchvision
    except ImportError as exc:
        raise AnomalyError("Exporting the backbone needs torch and torchvision (scripts/setup_dl.ps1)") from exc
    if name != "resnet18":
        raise AnomalyError(f"Unknown backbone {name!r}")
    weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
    net = torchvision.models.resnet18(weights=weights).eval()

    class Features(torch.nn.Module):
        def __init__(self, m: Any) -> None:
            super().__init__()
            self.stem = torch.nn.Sequential(m.conv1, m.bn1, m.relu, m.maxpool, m.layer1)
            self.layer2 = m.layer2
            self.layer3 = m.layer3

        def forward(self, x: Any) -> tuple[Any, Any]:
            f1 = self.stem(x)
            f2 = self.layer2(f1)
            f3 = self.layer3(f2)
            return f2, f3

    path = path or backbone_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dummy = torch.zeros(1, 3, 320, 320)
    with torch.no_grad():
        torch.onnx.export(Features(net), dummy, path, input_names=["x"], output_names=["f2", "f3"], opset_version=opset,
                          dynamic_axes={"x": {0: "n", 2: "h", 3: "w"}, "f2": {0: "n", 2: "h2", 3: "w2"}, "f3": {0: "n", 2: "h3", 3: "w3"}}, dynamo=False)
    return path


# ---------------------------------------------------------------------------
# session 與特徵
# ---------------------------------------------------------------------------
_SESSIONS: "OrderedDict[tuple[str, str], Any]" = OrderedDict()
_SESSION_LOCK = threading.Lock()


def _providers(device: str) -> list[str]:
    from apps.vision.dl.devices import available_providers, preferred_providers

    if device == "cpu":
        return ["CPUExecutionProvider"]
    if device == "cuda":
        avail = available_providers()
        return (["CUDAExecutionProvider"] if "CUDAExecutionProvider" in avail else []) + ["CPUExecutionProvider"]
    return preferred_providers()


def session_for(key: str, model_bytes: bytes | None = None, path: str | None = None, device: str = "auto") -> Any:
    """ORT session（依 (key, device) 快取；key 是資產路徑或 backbone 路徑）。給 bytes 就從記憶體載入。"""
    try:
        import onnxruntime as ort
    except ImportError:
        raise AnomalyError("onnxruntime is not installed, so anomaly detection cannot run") from None
    cache_key = (key, device)
    with _SESSION_LOCK:
        sess = _SESSIONS.get(cache_key)
        if sess is not None:
            _SESSIONS.move_to_end(cache_key)
            return sess
    providers = _providers(device)
    if any(p != "CPUExecutionProvider" for p in providers):
        from apps.vision.tools.builtin.dl import preload_gpu_dlls

        preload_gpu_dlls()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    try:
        sess = ort.InferenceSession(model_bytes if model_bytes is not None else path, opts, providers=providers)
    except Exception as exc:  # noqa: BLE001
        raise AnomalyError(f"Could not load the backbone: {str(exc)[:200]}") from None
    with _SESSION_LOCK:
        _SESSIONS[cache_key] = sess
        while len(_SESSIONS) > 6:
            _SESSIONS.popitem(last=False)
    return sess


def clear_sessions() -> None:
    with _SESSION_LOCK:
        _SESSIONS.clear()


def preprocess(image: np.ndarray, size: int) -> np.ndarray:
    """BGR／灰階 u8 → (1,3,size,size) float32，ImageNet 正規化。"""
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.dtype != np.uint8:
        from apps.vision.tools import imgfmt

        image = imgfmt.normalize_u8(image)
    resized = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA if max(image.shape[:2]) > size else cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])


def extract(sess: Any, image: np.ndarray, size: int) -> tuple[np.ndarray, tuple[int, int]]:
    """影像 → patch 特徵 (h·w, D) 與特徵圖大小 (h, w)：layer3 上採樣到 layer2 大小、串接、3×3 平均。"""
    x = preprocess(image, size)
    name = sess.get_inputs()[0].name
    outs = sess.run(None, {name: x})
    f2 = outs[0][0]
    f3 = outs[1][0] if len(outs) > 1 else None
    h, w = f2.shape[1], f2.shape[2]
    parts = [f2.transpose(1, 2, 0)]
    if f3 is not None:
        f3_hwc = f3.transpose(1, 2, 0)
        if f3_hwc.shape[:2] != (h, w):
            # cv2.resize 最多 512 通道：分塊上採樣
            chunks = [cv2.resize(np.ascontiguousarray(f3_hwc[:, :, i : i + 512]), (w, h), interpolation=cv2.INTER_LINEAR) for i in range(0, f3_hwc.shape[2], 512)]
            chunks = [c[:, :, None] if c.ndim == 2 else c for c in chunks]
            f3_hwc = np.concatenate(chunks, axis=2)
        parts.append(f3_hwc)
    feat = np.concatenate(parts, axis=2).astype(np.float32)
    # 鄰域聚合（3×3 平均）：filter2D 對多通道比 blur 快 2.5 倍；分塊避開 512 通道上限
    agg = np.concatenate([cv2.filter2D(np.ascontiguousarray(feat[:, :, i : i + 512]), -1, _BOX3, borderType=cv2.BORDER_REPLICATE).reshape(h, w, -1) for i in range(0, feat.shape[2], 512)], axis=2)
    return np.ascontiguousarray(agg.reshape(h * w, -1)), (h, w)


# ---------------------------------------------------------------------------
# 記憶庫
# ---------------------------------------------------------------------------
def coreset(feats: np.ndarray, ratio: float, seed: int = 0, progress: Callable[[float], None] | None = None) -> np.ndarray:
    """greedy k-center 子抽樣：每次挑「離已選集合最遠」的點；距離在隨機投影（128 維）空間算。回傳被選的索引。"""
    n, d = feats.shape
    k = max(1, min(n, int(round(n * float(ratio)))))
    if k >= n:
        return np.arange(n)
    rng = np.random.default_rng(seed)
    if d > PROJECTION_DIMS:
        proj = rng.standard_normal((d, PROJECTION_DIMS)).astype(np.float32) / np.sqrt(PROJECTION_DIMS)
        z = feats @ proj
    else:
        z = feats
    z_sq = np.einsum("ij,ij->i", z, z)
    chosen = np.empty(k, dtype=np.int64)
    first = int(rng.integers(0, n))
    chosen[0] = first
    min_d = z_sq + z_sq[first] - 2.0 * (z @ z[first])
    report_every = max(1, k // 20)
    for i in range(1, k):
        nxt = int(np.argmax(min_d))
        chosen[i] = nxt
        d_new = z_sq + z_sq[nxt] - 2.0 * (z @ z[nxt])
        np.minimum(min_d, d_new, out=min_d)
        min_d[nxt] = -1.0
        if progress is not None and i % report_every == 0:
            progress(i / k)
    return np.sort(chosen)


def projection(dim: int, out_dim: int, seed: int = 11) -> np.ndarray | None:
    """固定的隨機投影（Johnson–Lindenstrauss）：384 維 → out_dim 維，距離近似保留、kNN 快 3 倍；存進模型，訓練與推論同一份。"""
    if out_dim <= 0 or out_dim >= dim:
        return None
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((dim, out_dim)) / np.sqrt(out_dim)).astype(np.float32)


def project(feats: np.ndarray, proj: np.ndarray | None) -> np.ndarray:
    return feats if proj is None else np.ascontiguousarray(feats @ proj)


def nn_distance(query: np.ndarray, bank: np.ndarray, bank_sq: np.ndarray, chunk: int = 4096, exclude: np.ndarray | None = None) -> np.ndarray:
    """每個查詢 patch 到記憶庫最近鄰的歐氏距離（分塊矩陣運算）。exclude（bool (K,)）為 True 的記憶庫列不算（leave-one-out 用）。"""
    q_sq = np.einsum("ij,ij->i", query, query)
    out = np.empty(len(query), dtype=np.float32)
    for s in range(0, len(query), chunk):
        e = min(len(query), s + chunk)
        # |q|² + |m|² − 2 q·m：先在矩陣乘積上就地做 ×(−2) 與 +|m|²、取 min，最後才加 |q|²（少配置兩個 (Q, K) 暫存，快 2.5 倍）
        d = query[s:e] @ bank.T
        d *= -2.0
        d += bank_sq
        if exclude is not None and exclude.any():
            d[:, exclude] = np.inf
        out[s:e] = d.min(axis=1)
    out += q_sq
    np.maximum(out, 0.0, out=out)
    return np.sqrt(out, out=out)


def score_map(dists: np.ndarray, hw: tuple[int, int], out_hw: tuple[int, int], sigma: float = 4.0) -> np.ndarray:
    """patch 距離 → 上採樣到輸出尺寸的異常分數圖（float32），高斯平滑。"""
    h, w = hw
    small = dists.reshape(h, w).astype(np.float32)
    big = cv2.resize(small, (out_hw[1], out_hw[0]), interpolation=cv2.INTER_LINEAR)
    if sigma > 0:
        k = int(sigma * 4) | 1
        big = cv2.GaussianBlur(big, (k, k), sigma)
    return big


# ---------------------------------------------------------------------------
# 資產
# ---------------------------------------------------------------------------
def pack(bank: np.ndarray, backbone_bytes: bytes, meta: dict[str, Any], proj: np.ndarray | None = None) -> bytes:
    buf = io.BytesIO()
    arrays: dict[str, Any] = {"bank": bank.astype(np.float32), "bank_sq": np.einsum("ij,ij->i", bank, bank).astype(np.float32),
                              "backbone": np.frombuffer(backbone_bytes, dtype=np.uint8), "meta": json.dumps(meta)}
    if proj is not None:
        arrays["proj"] = proj.astype(np.float32)
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


_CACHE: "OrderedDict[str, tuple[float, int, dict[str, Any]]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def load(path: str) -> dict[str, Any]:
    """載入模型資產（模組層快取，mtime＋size 判失效）。"""
    try:
        st = os.stat(path)
    except OSError as exc:
        raise AnomalyError(f"Could not read the anomaly model: {exc}") from None
    with _CACHE_LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            _CACHE.move_to_end(path)
            return hit[2]
    try:
        with np.load(path, allow_pickle=False) as z:
            if "bank" not in z or "meta" not in z:
                raise AnomalyError("This file is not an anomaly model (no memory bank)")
            model = {"bank": np.ascontiguousarray(z["bank"], dtype=np.float32), "bank_sq": np.ascontiguousarray(z["bank_sq"], dtype=np.float32),
                     "backbone": z["backbone"].tobytes() if "backbone" in z else b"", "meta": json.loads(str(z["meta"])),
                     "proj": np.ascontiguousarray(z["proj"], dtype=np.float32) if "proj" in z else None}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise AnomalyError(f"Could not read the anomaly model: {exc}") from None
    with _CACHE_LOCK:
        _CACHE[path] = (st.st_mtime, st.st_size, model)
        _CACHE.move_to_end(path)
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)
    return model


def invalidate() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def backbone_session(model: dict[str, Any], path: str, device: str = "auto") -> Any:
    """模型自帶的 backbone → session（快取鍵＝資產路徑）；沒自帶就用平台附帶的 backbone 檔。"""
    if model.get("backbone"):
        return session_for(path, model_bytes=model["backbone"], device=device)
    bp = backbone_path(str(model["meta"].get("backbone", "resnet18")))
    if not os.path.isfile(bp):
        raise AnomalyError("The anomaly backbone is not installed (ASSET_DIR/dl/weights); run manage.py anomaly_backbone --export or install the deep-learning pack")
    return session_for(bp, path=bp, device=device)


def infer(model: dict[str, Any], sess: Any, image: np.ndarray, out_hw: tuple[int, int] | None = None) -> tuple[np.ndarray, float]:
    """影像 → (分數圖 float32 (H, W), 最大分數)。out_hw 預設＝影像尺寸。"""
    size = int(model["meta"].get("input_size", 320))
    feats, hw = extract(sess, image, size)
    dists = nn_distance(project(feats, model.get("proj")), model["bank"], model["bank_sq"])
    smap = score_map(dists, hw, out_hw or image.shape[:2], float(model["meta"].get("blur_sigma", 4.0)))
    return smap, float(smap.max())
