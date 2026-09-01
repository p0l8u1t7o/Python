"""內建 trainer：MLP 影像分類（numpy 訓練、手刻 ONNX 匯出）。

前處理與 dl_classify 工具的預設完全一致（RGB、ImageNet mean/std、resize 到 input_size），
所以匯出的模型放進「DL 分類」工具、labels 貼上類別清單就能用，其餘參數用預設值。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from apps.vision.dl.base import ProgressFn, SampleRef, Suggestion, TrainCancelled, Trainer, TrainError, TrainResult
from apps.vision.dl.onnx_io import build_mlp
from apps.vision.tools.base import Param

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _features(image: np.ndarray, size: int) -> np.ndarray:
    """與 dl_classify 的 preprocess 等價（rgb、/255、ImageNet mean/std）→ 攤平向量。"""
    import cv2

    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    image = cv2.resize(image, (size, size), interpolation=cv2.INTER_LINEAR)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    x = image.astype(np.float32) / 255.0
    x = (x - _MEAN) / _STD
    return np.ascontiguousarray(x.transpose(2, 0, 1)).reshape(-1)


def _load_features(samples: list[SampleRef], size: int) -> tuple[np.ndarray, list[SampleRef]]:
    feats, kept = [], []
    for s in samples:
        image = s.load()
        if image is None:
            continue
        feats.append(_features(image, size))
        kept.append(s)
    if not feats:
        return np.zeros((0, 3 * size * size), dtype=np.float32), []
    return np.stack(feats), kept


class MlpClassifierTrainer(Trainer):
    kind = "mlp_classify"
    label = "影像分類（MLP）"
    description = "把整張（或裁切後的）樣本影像分到你定義的類別；輕量全連接網路，CPU 幾秒內可完成教導，匯出後用「DL 分類」工具推論。"
    label_mode = "classes"
    tool_key = "dl_classify"
    devices = ("cpu",)
    min_per_class = 2
    params = [
        Param("input_size", "輸入尺寸", kind="select", default=64, options=[{"value": 32, "label": "32×32（最快）"}, {"value": 64, "label": "64×64（建議）"}, {"value": 96, "label": "96×96"}, {"value": 128, "label": "128×128（細節多）"}]),
        Param("hidden", "隱藏層寬度", kind="number", default=64, minimum=8, maximum=512, group="進階"),
        Param("epochs", "訓練回合", kind="number", default=300, minimum=10, maximum=5000, group="進階"),
        Param("learning_rate", "學習率", kind="number", default=0.05, minimum=0.0001, maximum=1, step=0.001, group="進階"),
        Param("val_split", "驗證比例", kind="number", default=0.2, minimum=0, maximum=0.5, step=0.05, group="進階", help_text="0 = 全部拿去訓練（樣本很少時）。"),
    ]

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        size = int(params.get("input_size") or 64)
        hidden = int(params.get("hidden") or 64)
        epochs = int(params.get("epochs") or 300)
        lr = float(params.get("learning_rate") or 0.05)
        val_split = float(params.get("val_split") if params.get("val_split") is not None else 0.2)

        labeled = [s for s in samples if s.label in classes]
        counts = {c: sum(1 for s in labeled if s.label == c) for c in classes}
        lacking = [f"{c}×{n}" for c, n in counts.items() if n < self.min_per_class]
        if len(classes) < 2:
            raise TrainError("至少要定義 2 個類別")
        if lacking:
            raise TrainError(f"每類至少 {self.min_per_class} 張已標記樣本，不足：{', '.join(lacking)}")

        progress(0.02, "讀取樣本與抽取特徵", None)
        x, kept = _load_features(labeled, size)
        if not len(kept):
            raise TrainError("樣本影像讀取失敗")
        y = np.array([classes.index(s.label) for s in kept], dtype=np.int64)

        # 分層切驗證集（每類至少留 1 張在訓練集）
        rng = np.random.default_rng(7)
        val_idx: list[int] = []
        if val_split > 0:
            for ci in range(len(classes)):
                idx = np.flatnonzero(y == ci)
                rng.shuffle(idx)
                take = min(len(idx) - 1, max(0, int(round(len(idx) * val_split))))
                val_idx += list(idx[:take])
        val_mask = np.zeros(len(y), dtype=bool)
        val_mask[val_idx] = True
        xt, yt, xv, yv = x[~val_mask], y[~val_mask], x[val_mask], y[val_mask]

        d, c = x.shape[1], len(classes)
        w1 = rng.normal(0, np.sqrt(2.0 / d), (d, hidden)).astype(np.float32)
        b1 = np.zeros(hidden, dtype=np.float32)
        w2 = rng.normal(0, np.sqrt(2.0 / hidden), (hidden, c)).astype(np.float32)
        b2 = np.zeros(c, dtype=np.float32)

        def forward(xb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            h = np.maximum(xb @ w1 + b1, 0)
            logits = h @ w2 + b2
            return h, logits

        def accuracy(xb: np.ndarray, yb: np.ndarray) -> float:
            if not len(yb):
                return 0.0
            return float((forward(xb)[1].argmax(axis=1) == yb).mean())

        n = len(yt)
        metrics: dict[str, Any] = {}
        for epoch in range(epochs):
            h, logits = forward(xt)
            logits -= logits.max(axis=1, keepdims=True)
            e = np.exp(logits)
            probs = e / e.sum(axis=1, keepdims=True)
            loss = float(-np.log(np.clip(probs[np.arange(n), yt], 1e-9, 1)).mean())
            grad = probs
            grad[np.arange(n), yt] -= 1
            grad /= n
            gw2 = h.T @ grad
            gb2 = grad.sum(axis=0)
            gh = grad @ w2.T
            gh[h <= 0] = 0
            gw1 = xt.T @ gh
            gb1 = gh.sum(axis=0)
            w1 -= lr * gw1
            b1 -= lr * gb1
            w2 -= lr * gw2
            b2 -= lr * gb2
            if epoch % 20 == 0 or epoch == epochs - 1:
                metrics = {
                    "epoch": epoch + 1, "epochs": epochs, "loss": round(loss, 4),
                    "train_accuracy": round(accuracy(xt, yt), 4),
                    "val_accuracy": round(accuracy(xv, yv), 4) if len(yv) else None,
                    "samples": int(len(y)), "val_samples": int(len(yv)), "classes": counts,
                }
                progress(0.05 + 0.9 * (epoch + 1) / epochs, f"訓練中（{epoch + 1}/{epochs}）", metrics)

        progress(0.97, "匯出 ONNX", metrics)
        onnx = build_mlp(w1, b1, w2, b2, channels=3, size=size)
        return TrainResult(
            onnx_bytes=onnx,
            metrics=metrics,
            tool_key=self.tool_key,
            tool_params={
                "labels": "\n".join(classes), "input_size": size,
                "mean": "0.485,0.456,0.406", "std": "0.229,0.224,0.225",
                "color_order": "rgb", "apply_softmax": True,
            },
        )

    def suggest(self, labeled: list[SampleRef], unlabeled: list[SampleRef], classes: list[str], params: dict[str, Any]) -> list[Suggestion]:
        """自動標記：以已標記樣本的特徵做 cosine kNN（k=3），快、且一張標對就開始有用。"""
        size = int(params.get("input_size") or 64)
        pool = [s for s in labeled if s.label in classes]
        if not pool:
            raise TrainError("先標記幾張樣本，才能自動標記其餘的")
        if not unlabeled:
            return []
        xl, kl = _load_features(pool, size)
        xu, ku = _load_features(unlabeled, size)
        if not len(kl) or not len(ku):
            return []
        xl = xl / (np.linalg.norm(xl, axis=1, keepdims=True) + 1e-9)
        xu = xu / (np.linalg.norm(xu, axis=1, keepdims=True) + 1e-9)
        sim = xu @ xl.T  # [U, L]
        k = min(3, sim.shape[1])
        out: list[Suggestion] = []
        for i, s in enumerate(ku):
            top = np.argsort(-sim[i])[:k]
            votes: dict[str, float] = {}
            for j in top:
                votes[kl[j].label] = votes.get(kl[j].label, 0.0) + float(max(sim[i, j], 0.0))
            best = max(votes, key=lambda kk: votes[kk])
            total = sum(votes.values()) or 1.0
            out.append(Suggestion(sample_id=s.id, label=best, score=round(votes[best] / total, 4)))
        return out


TRAINERS: list[type[Trainer]] = [MlpClassifierTrainer]

# 讓 lint 知道 TrainCancelled 是框架的一部分（jobs.py 透過 progress 擲出）。
__all__ = ["MlpClassifierTrainer", "TRAINERS", "TrainCancelled"]
