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


def _augmented(image: np.ndarray, jitter: float):
    """訓練用增強副本：水平翻轉＋亮度 ±jitter（convertScaleAbs 飽和裁切，驗證集不做）。"""
    import cv2

    yield cv2.flip(image, 1)
    if jitter > 0:
        yield cv2.convertScaleAbs(image, alpha=1.0 + jitter)
        yield cv2.convertScaleAbs(image, alpha=1.0 - jitter)


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
        Param("val_split", "驗證比例", kind="number", default=0.2, minimum=0, maximum=0.5, step=0.05, group="進階", help_text="0 = 全部拿去訓練（樣本很少時）。樣本有人工指定 val 分割時以指定為準。"),
        Param("augment", "啟用資料增強", kind="boolean", default=False, group="增強", help_text="訓練集加入水平翻轉與亮度擾動副本（驗證集不動）；樣本少時可提升泛化。"),
        Param("augment_brightness", "亮度擾動幅度", kind="range", default=0.2, minimum=0.0, maximum=0.5, step=0.05, group="增強"),
    ]

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        size = int(params.get("input_size") or 64)
        hidden = int(params.get("hidden") or 64)
        epochs = int(params.get("epochs") or 300)
        lr = float(params.get("learning_rate") or 0.05)
        val_split = float(params.get("val_split") if params.get("val_split") is not None else 0.2)

        # test 分割不進訓練（保留給訓練後的盲測）；val 有人工指定就照指定
        labeled = [s for s in samples if s.label in classes and s.split != "test"]
        n_test = sum(1 for s in samples if s.label in classes and s.split == "test")
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

        rng = np.random.default_rng(7)
        val_mask = np.array([s.split == "val" for s in kept], dtype=bool)
        if not val_mask.any():
            # 沒有人工指定：分層隨機切驗證集（每類至少留 1 張在訓練集）
            val_idx: list[int] = []
            if val_split > 0:
                for ci in range(len(classes)):
                    idx = np.flatnonzero(y == ci)
                    rng.shuffle(idx)
                    take = min(len(idx) - 1, max(0, int(round(len(idx) * val_split))))
                    val_idx += list(idx[:take])
            val_mask[val_idx] = True
        if val_mask.all():
            raise TrainError("所有樣本都被指定為驗證（val），沒有訓練樣本")
        xt, yt, xv, yv = x[~val_mask], y[~val_mask], x[val_mask], y[val_mask]

        # 資料增強：只加在訓練集（重載原圖做翻轉／亮度擾動，特徵接在後面）
        n_aug = 0
        if bool(params.get("augment")):
            jitter = float(params.get("augment_brightness") if params.get("augment_brightness") is not None else 0.2)
            progress(0.04, "產生增強樣本", None)
            aug_feats, aug_y = [], []
            for i in np.flatnonzero(~val_mask):
                image = kept[int(i)].load()
                if image is None:
                    continue
                for aug in _augmented(image, jitter):
                    aug_feats.append(_features(aug, size))
                    aug_y.append(y[int(i)])
            if aug_feats:
                xt = np.concatenate([xt, np.stack(aug_feats)])
                yt = np.concatenate([yt, np.array(aug_y, dtype=np.int64)])
                n_aug = len(aug_y)

        # 與 patch_segment 共用同一個訓練迴圈（含學習率保護：lr 太大把 ReLU 打死時自動砍 lr 重來）
        w1, b1, w2, b2, metrics = _train_softmax_mlp(xt, yt, xv, yv, hidden=hidden, classes=len(classes), epochs=epochs, lr=lr, seed=7, progress=progress)
        metrics = {**metrics, "samples": int(len(y)), "val_samples": int(len(yv)), "classes": counts}
        if metrics.get("val_accuracy") is None and not len(yv):
            metrics["val_accuracy"] = None

        if n_aug:
            metrics["augmented"] = n_aug
        if n_test:
            metrics["test_holdout"] = n_test
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


# ---------------------------------------------------------------------------
# 輕量語意分割：patch 分類器（numpy 訓練）→ 全卷積 ONNX → dl_segment 工具
# ---------------------------------------------------------------------------
def _seg_features(image: np.ndarray, size: int) -> np.ndarray:
    """與 dl_segment 的 preprocess 等價 → CHW float32（保留空間維度給 patch 取樣）。"""
    import cv2

    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    image = cv2.resize(image, (size, size), interpolation=cv2.INTER_LINEAR)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    x = image.astype(np.float32) / 255.0
    x = (x - _MEAN) / _STD
    return np.ascontiguousarray(x.transpose(2, 0, 1))


def _patches_at(chw: np.ndarray, ys: np.ndarray, xs: np.ndarray, k: int) -> np.ndarray:
    """在 (ys, xs) 位置取 k×k patch（zero padding，與 ONNX Conv pads 一致）→ [N, 3*k*k]。"""
    pad = k // 2
    padded = np.pad(chw, ((0, 0), (pad, pad), (pad, pad)))
    out = np.empty((len(ys), chw.shape[0] * k * k), dtype=np.float32)
    for i, (y, x) in enumerate(zip(ys, xs)):
        out[i] = padded[:, y : y + k, x : x + k].reshape(-1)
    return out


def _train_softmax_mlp(xt, yt, xv, yv, *, hidden, classes, epochs, lr, seed, progress, base_frac=0.05, span=0.9, stage="訓練中"):
    """單隱藏層 softmax MLP 的全批次梯度下降。回 (w1, b1, w2, b2, metrics)。"""
    rng = np.random.default_rng(seed)
    d = xt.shape[1]
    w1 = rng.normal(0, np.sqrt(2.0 / d), (d, hidden)).astype(np.float32)
    b1 = np.zeros(hidden, dtype=np.float32)
    w2 = rng.normal(0, np.sqrt(2.0 / hidden), (hidden, classes)).astype(np.float32)
    b2 = np.zeros(classes, dtype=np.float32)
    n = len(yt)
    metrics: dict[str, Any] = {}
    # 學習率保護：全批次 GD 在原始像素（維度上萬）上，lr 太大會第一步就把隱藏層打死（ReLU 全 0 → 輸出常數、loss 卡在 ln(k)）。
    # 訓練前 10% 若 loss 沒離開 ln(k)，就重新初始化並把 lr 砍成 1/4 重來（最多 3 次），trainer 預設值在各種資料上都能收斂。
    chance = float(np.log(max(2, classes)))
    probe_epoch = max(10, epochs // 10)
    restarts = 0

    def init():
        nonlocal w1, b1, w2, b2
        w1 = rng.normal(0, np.sqrt(2.0 / d), (d, hidden)).astype(np.float32)
        b1 = np.zeros(hidden, dtype=np.float32)
        w2 = rng.normal(0, np.sqrt(2.0 / hidden), (hidden, classes)).astype(np.float32)
        b2 = np.zeros(classes, dtype=np.float32)

    def acc(xb, yb):
        if not len(yb):
            return None
        h = np.maximum(xb @ w1 + b1, 0)
        return round(float(((h @ w2 + b2).argmax(axis=1) == yb).mean()), 4)

    epoch = 0
    while epoch < epochs:
        h = np.maximum(xt @ w1 + b1, 0)
        logits = h @ w2 + b2
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        probs = e / e.sum(axis=1, keepdims=True)
        loss = float(-np.log(np.clip(probs[np.arange(n), yt], 1e-9, 1)).mean())
        if epoch >= probe_epoch and epoch % 20 == 0 and restarts < 3 and loss > chance - 0.02 and (acc(xt, yt) or 0.0) <= 1.0 / classes + 0.05:
            # 隱藏層死掉（輸出常數、loss 停在 ln(k)、正確率＝隨機）：砍 lr 重來
            restarts += 1
            lr *= 0.25
            init()
            epoch = 0
            metrics["lr_restarts"] = restarts
            continue
        grad = probs
        grad[np.arange(n), yt] -= 1
        grad /= n
        gw2, gb2 = h.T @ grad, grad.sum(axis=0)
        gh = grad @ w2.T
        gh[h <= 0] = 0
        w1 -= lr * (xt.T @ gh)
        b1 -= lr * gh.sum(axis=0)
        w2 -= lr * gw2
        b2 -= lr * gb2
        epoch += 1
        if (epoch - 1) % 20 == 0 or epoch == epochs:
            metrics = {"epoch": epoch, "epochs": epochs, "loss": round(loss, 4),
                       "train_accuracy": acc(xt, yt), "val_accuracy": acc(xv, yv), "samples": int(n), **({"lr_restarts": restarts, "lr": lr} if restarts else {})}
            progress(base_frac + span * epoch / epochs, f"{stage}（{epoch}/{epochs}）", metrics)
    return w1, b1, w2, b2, metrics


class PatchSegmentTrainer(Trainer):
    kind = "patch_segment"
    label = "語意分割（輕量）"
    description = "用 polygon 標記教每像素分類（背景＋你的類別）；patch 特徵＋輕量網路，CPU 數秒完成，匯出全卷積 ONNX 給「DL 語意分割」工具。適合顏色／紋理類的區域與瑕疵。"
    label_mode = "shapes"
    tool_key = "dl_segment"
    devices = ("cpu",)
    min_per_class = 1
    params = [
        Param("input_size", "工作尺寸", kind="select", default=192, options=[{"value": 128, "label": "128（最快）"}, {"value": 192, "label": "192（建議）"}, {"value": 256, "label": "256（細節多）"}], help_text="訓練與建議的推論尺寸；模型是全卷積，推論可用其他尺寸。"),
        Param("kernel", "感受野", kind="select", default=7, options=[{"value": 5, "label": "5×5"}, {"value": 7, "label": "7×7"}, {"value": 9, "label": "9×9"}], group="進階"),
        Param("hidden", "隱藏層寬度", kind="number", default=32, minimum=8, maximum=256, group="進階"),
        Param("epochs", "訓練回合", kind="number", default=400, minimum=10, maximum=5000, group="進階"),
        Param("learning_rate", "學習率", kind="number", default=0.1, minimum=0.0001, maximum=1, step=0.001, group="進階"),
        Param("samples_per_image", "每張取樣像素數", kind="number", default=4000, minimum=500, maximum=20000, group="進階"),
        Param("augment", "啟用資料增強", kind="boolean", default=False, group="增強", help_text="每張樣本追加水平翻轉版本的取樣（標記同步翻轉）。"),
    ]

    def _dataset(self, samples, classes, params):
        from apps.vision.dl.shapes import rasterize

        size = int(params.get("input_size") or 192)
        k = int(params.get("kernel") or 7)
        per_image = int(params.get("samples_per_image") or 4000)
        augment = bool(params.get("augment"))
        rng = np.random.default_rng(7)
        xs_list, ys_list = [], []
        # test 分割不進訓練（保留給訓練後的盲測）
        labeled = [s for s in samples if s.shapes and s.split != "test"]

        def take_from(chw: np.ndarray, mask: np.ndarray) -> None:
            # 各類（含背景）平衡取樣
            per_class = max(1, per_image // (len(classes) + 1))
            pys, pxs = [], []
            for value in range(len(classes) + 1):
                cand = np.flatnonzero(mask.reshape(-1) == value)
                if not len(cand):
                    continue
                take = rng.choice(cand, size=min(per_class, len(cand)), replace=False)
                pys.append(take // size)
                pxs.append(take % size)
            if not pys:
                return
            yy, xx = np.concatenate(pys), np.concatenate(pxs)
            xs_list.append(_patches_at(chw, yy, xx, k))
            ys_list.append(mask[yy, xx].astype(np.int64))

        for s in labeled:
            image = s.load()
            if image is None:
                continue
            chw = _seg_features(image, size)
            mask = rasterize(s.shapes, classes, size, size)
            take_from(chw, mask)
            if augment:
                take_from(np.ascontiguousarray(chw[:, :, ::-1]), np.ascontiguousarray(mask[:, ::-1]))
        if not xs_list:
            raise TrainError("沒有任何帶 shapes 標記的樣本（先在標記編輯器畫出區域）")
        return np.concatenate(xs_list), np.concatenate(ys_list), size, k

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        if not classes:
            raise TrainError("至少要定義 1 個類別")
        hidden = int(params.get("hidden") or 32)
        epochs = int(params.get("epochs") or 400)
        lr = float(params.get("learning_rate") or 0.1)
        progress(0.02, "讀取樣本、rasterize 標記與取樣 patch", None)
        x, y, size, k = self._dataset(samples, classes, params)
        present = set(np.unique(y).tolist())
        missing = [c for i, c in enumerate(classes) if (i + 1) not in present]
        if missing:
            raise TrainError(f"這些類別沒有任何標記像素：{', '.join(missing)}")
        rng = np.random.default_rng(3)
        order = rng.permutation(len(y))
        n_val = max(1, len(y) // 5)
        vi, ti = order[:n_val], order[n_val:]
        w1, b1, w2, b2, metrics = _train_softmax_mlp(
            x[ti], y[ti], x[vi], y[vi], hidden=hidden, classes=len(classes) + 1,
            epochs=epochs, lr=lr, seed=11, progress=progress)
        metrics["pixel_metric"] = True
        progress(0.97, "匯出 ONNX（全卷積）", metrics)
        from apps.vision.dl.onnx_io import build_patch_segmenter

        k1 = np.ascontiguousarray(w1.T.reshape(hidden, 3, k, k))
        k2 = np.ascontiguousarray(w2.T.reshape(len(classes) + 1, hidden, 1, 1))
        onnx = build_patch_segmenter(k1, b1, k2, b2, channels=3, kernel=k)
        return TrainResult(
            onnx_bytes=onnx, metrics=metrics, tool_key=self.tool_key,
            tool_params={
                "labels": "\n".join(["background"] + list(classes)), "input_size": size,
                "mean": "0.485,0.456,0.406", "std": "0.229,0.224,0.225", "color_order": "rgb",
                "target_class": 1,
            },
        )

    def suggest(self, labeled: list[SampleRef], unlabeled: list[SampleRef], classes: list[str], params: dict[str, Any]) -> list[Suggestion]:
        """自動標記：用已標記樣本快速訓練一個小模型，對未標記樣本推論 → 輪廓 → polygon 建議。"""
        import cv2

        pool = [s for s in labeled if s.shapes]
        if not pool:
            raise TrainError("先用標記編輯器標幾張，才能自動標記其餘的")
        if not unlabeled:
            return []
        quick = {**params, "epochs": min(int(params.get("epochs") or 400), 150), "samples_per_image": 2000}
        x, y, size, k = self._dataset(pool, classes, quick)
        hidden = int(quick.get("hidden") or 32)
        w1, b1, w2, b2, _ = _train_softmax_mlp(
            x, y, x[:0], y[:0], hidden=hidden, classes=len(classes) + 1,
            epochs=int(quick["epochs"]), lr=float(quick.get("learning_rate") or 0.1), seed=11,
            progress=lambda *a: None)
        out: list[Suggestion] = []
        for s in unlabeled:
            image = s.load()
            if image is None:
                continue
            chw = _seg_features(image, size)
            ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
            feats = _patches_at(chw, ys.reshape(-1), xs.reshape(-1), k)
            h = np.maximum(feats @ w1 + b1, 0)
            logits = h @ w2 + b2
            cls_map = logits.argmax(axis=1).reshape(size, size).astype(np.uint8)
            probs = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs /= probs.sum(axis=1, keepdims=True)
            conf_map = probs.max(axis=1).reshape(size, size)
            shapes_out, scores = [], []
            for ci in range(1, len(classes) + 1):
                mask = ((cls_map == ci).astype(np.uint8)) * 255
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for cnt in contours:
                    if cv2.contourArea(cnt) < size * size * 0.001:
                        continue
                    approx = cv2.approxPolyDP(cnt, 0.01 * cv2.arcLength(cnt, True), True).reshape(-1, 2)
                    if len(approx) < 3:
                        continue
                    m = np.zeros((size, size), np.uint8)
                    cv2.fillPoly(m, [approx.astype(np.int32)], 1)
                    scores.append(float(conf_map[m > 0].mean()) if (m > 0).any() else 0.0)
                    shapes_out.append({"label": classes[ci - 1], "kind": "polygon",
                                       "points": [[float(px) / size, float(py) / size] for px, py in approx]})
            if shapes_out:
                out.append(Suggestion(sample_id=s.id, label="", score=round(float(np.mean(scores)), 4), shapes=shapes_out))
        return out


TRAINERS: list[type[Trainer]] = [MlpClassifierTrainer, PatchSegmentTrainer]

# 讓 lint 知道 TrainCancelled 是框架的一部分（jobs.py 透過 progress 擲出）。
__all__ = ["MlpClassifierTrainer", "PatchSegmentTrainer", "TRAINERS", "TrainCancelled"]
