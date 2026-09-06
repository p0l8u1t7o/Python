"""anomaly Trainer：只教良品的無監督異常檢測（apps/vision/dl/anomaly.py 的 PatchCore 風格記憶庫）。

樣本語意（label_mode=classes）：沒有標記的樣本與標為第一個類別的樣本都算「良品」進記憶庫；
標成其他類別的樣本不進庫，訓練結束時拿來算分數對照（有的話回報 AUROC），也是 suggest() 幫使用者找出混進良品的不良品的依據。
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from apps.vision.dl import anomaly
from apps.vision.dl.base import ProgressFn, SampleRef, Suggestion, Trainer, TrainError, TrainResult
from apps.vision.tools.base import Param


def _good_samples(samples: list[SampleRef], classes: list[str]) -> tuple[list[SampleRef], list[SampleRef]]:
    good_label = classes[0] if classes else ""
    good = [s for s in samples if s.label in ("", good_label) and s.split != "test"]
    other = [s for s in samples if s.label not in ("", good_label)]
    return good, other


def _augmented(image: np.ndarray, jitter: float) -> list[np.ndarray]:
    import cv2

    out = [cv2.flip(image, 1)]
    if jitter > 0:
        f = image.astype(np.float32)
        out.append(np.clip(f * (1.0 + jitter), 0, 255).astype(np.uint8))
        out.append(np.clip(f * (1.0 - jitter), 0, 255).astype(np.uint8))
    return out


def _auroc(pos: np.ndarray, neg: np.ndarray) -> float | None:
    if len(pos) == 0 or len(neg) == 0:
        return None
    # Mann–Whitney U：分數高＝異常
    ranks = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    r_pos = ranks[: len(pos)].sum()
    u = r_pos - len(pos) * (len(pos) + 1) / 2.0
    return round(float(u / (len(pos) * len(neg))), 4)


class AnomalyTrainer(Trainer):
    kind = "anomaly"
    label = "Anomaly detection (good parts only)"
    description = (
        "Learns what good looks like from good pictures alone — no defect samples, no labels — and flags anything it has not seen. "
        "A pre-trained backbone turns each picture into patch features, a memory bank keeps a compact subset, and at run time the "
        "distance of every patch to its nearest good patch is the anomaly score. Training is feature extraction plus bank building: seconds to a minute on CPU."
    )
    label_mode = "classes"
    tool_key = "dl_anomaly"
    devices = ("cpu", "cuda")
    min_per_class = 1
    params = [
        Param("backbone", "Backbone", kind="select", default="resnet18", options=[{"value": "resnet18", "label": "ResNet18 layer2+3 (ImageNet)"}]),
        Param("input_size", "Input size", kind="select", default=320, options=[{"value": 224, "label": "224 (fastest)"}, {"value": 320, "label": "320 (recommended)"}, {"value": 448, "label": "448 (finer defects)"}]),
        Param("coreset_ratio", "Memory bank ratio", kind="range", default=0.1, minimum=0.01, maximum=1.0, step=0.01,
              help_text="Fraction of good patches kept after greedy coreset sub-sampling. 0.1 keeps accuracy and makes run time short."),
        Param("threshold_sigma", "Threshold sigma", kind="number", default=3.0, minimum=0.5, maximum=10, step=0.5,
              help_text="The automatic threshold is mean + sigma × standard deviation of the good pictures' own scores."),
        Param("augment", "Augment (flip and brightness)", kind="boolean", default=False, group="Augment", help_text="Adds a flipped and two brightness-shifted copies of every good picture to the bank."),
        Param("augment_brightness", "Brightness jitter", kind="range", default=0.15, minimum=0.0, maximum=0.5, step=0.05, group="Augment"),
        Param("blur_sigma", "Score map smoothing", kind="number", default=4, minimum=0, maximum=32, group="Advanced", unit="px"),
        Param("projection_dims", "Feature projection", kind="select", default=128, options=[{"value": 0, "label": "None (384 dims, slowest)"}, {"value": 128, "label": "128 dims (recommended)"}, {"value": 64, "label": "64 dims (fastest)"}], group="Advanced",
              help_text="A fixed random projection of the 384-dim features. 128 keeps the ranking of distances and makes run time about three times shorter."),
    ]

    def _backbone(self, params: dict[str, Any]) -> tuple[str, bytes]:
        name = str(params.get("backbone") or "resnet18")
        # backbone_path 不是表單參數：測試與 bench 用來指到假 backbone，不碰 ASSET_DIR
        path = str(params.get("backbone_path") or anomaly.backbone_path(name))
        if not os.path.isfile(path):
            raise TrainError("The anomaly backbone is not installed (ASSET_DIR/dl/weights/resnet18_l2l3.onnx): run manage.py anomaly_backbone --export on a machine with torch and torchvision, or install the deep-learning pack")
        with open(path, "rb") as fh:
            return path, fh.read()

    def train(self, samples: list[SampleRef], classes: list[str], params: dict[str, Any], device: str, progress: ProgressFn) -> TrainResult:
        size = int(params.get("input_size") or 320)
        ratio = float(params.get("coreset_ratio") if params.get("coreset_ratio") is not None else 0.1)
        k_sigma = float(params.get("threshold_sigma") if params.get("threshold_sigma") is not None else 3.0)
        blur = float(params.get("blur_sigma") if params.get("blur_sigma") is not None else 4.0)
        good, other = _good_samples(samples, classes)
        if len(good) < 3:
            raise TrainError(f"At least 3 good pictures are needed ({len(good)} found); 20 to 50 is typical. Unlabelled samples and samples labelled '{classes[0] if classes else 'good'}' count as good")
        bpath, bbytes = self._backbone(params)
        progress(0.02, "Loading the backbone", None)
        sess = anomaly.session_for(bpath, path=bpath, device="cuda" if device == "cuda" else "cpu")
        feats: list[np.ndarray] = []      # 每張良品（含增強）的 patch 特徵
        owner: list[int] = []             # 每組特徵屬於第幾張原圖（leave-one-out 用）
        hw: tuple[int, int] = (0, 0)
        n_aug = 0
        proj: np.ndarray | None = None
        proj_dims = int(params.get("projection_dims") if params.get("projection_dims") is not None else 128)
        jitter = float(params.get("augment_brightness") if params.get("augment_brightness") is not None else 0.15)
        for i, s in enumerate(good):
            progress(0.03 + 0.45 * i / len(good), f"Extracting features {i + 1}/{len(good)}", None)
            image = s.load()
            if image is None:
                continue
            f, hw = anomaly.extract(sess, image, size)
            if proj is None:
                proj = anomaly.projection(f.shape[1], proj_dims)
            feats.append(anomaly.project(f, proj))
            owner.append(i)
            if bool(params.get("augment")):
                for aug in _augmented(image, jitter):
                    feats.append(anomaly.project(anomaly.extract(sess, aug, size)[0], proj))
                    owner.append(i)
                    n_aug += 1
        if len(set(owner)) < 3:
            raise TrainError("Fewer than 3 good pictures could be read")
        all_f = np.concatenate(feats)
        all_owner = np.concatenate([np.full(len(f), o, dtype=np.int32) for f, o in zip(feats, owner)])
        progress(0.5, f"Building the memory bank from {len(all_f)} patches", None)
        idx = anomaly.coreset(all_f, ratio, seed=7, progress=lambda fr: progress(0.5 + 0.3 * fr, "Building the memory bank", None))
        bank = np.ascontiguousarray(all_f[idx])
        bank_sq = np.einsum("ij,ij->i", bank, bank).astype(np.float32)
        bank_owner = all_owner[idx]
        progress(0.82, "Scoring the good pictures for the threshold (leave-one-out)", None)
        # 門檻：每張良品對「不含自己 patch」的記憶庫打分（自己的 patch 在庫裡會讓分數偏低，新良品就會被誤判）
        image_scores = []
        seen: set[int] = set()
        for f, o in zip(feats, owner):
            if o in seen:
                continue  # 增強版本不算進門檻統計
            seen.add(o)
            d = anomaly.nn_distance(f, bank, bank_sq, exclude=(bank_owner == o))
            image_scores.append(float(anomaly.score_map(d, hw, (size, size), blur).max()))
        img = np.array(image_scores, dtype=np.float64)
        # mean + k·σ，且至少高過最高的良品分數 5%：分數分布右偏，30 張時 3σ 仍可能低於個別良品
        threshold = float(max(img.mean() + k_sigma * img.std(), img.max() * 1.05)) if len(img) > 1 else float(img.max() * 1.5)
        metrics: dict[str, Any] = {
            "samples": int(len(good)), "augmented": int(n_aug), "patches": int(len(all_f)), "bank": int(len(bank)), "feature_dim": int(bank.shape[1]),
            "input_size": size, "feature_hw": [int(hw[0]), int(hw[1])],
            "good_score_mean": round(float(img.mean()), 4), "good_score_std": round(float(img.std()), 4), "good_score_max": round(float(img.max()), 4),
            "threshold": round(threshold, 4),
        }
        model_meta = {"kind": "anomaly", "version": anomaly.VERSION, "backbone": str(params.get("backbone") or "resnet18"), "input_size": size, "blur_sigma": blur,
                      "feature_hw": [int(hw[0]), int(hw[1])], "threshold": round(threshold, 4), "projection_dims": int(bank.shape[1]),
                      "good_score_mean": metrics["good_score_mean"], "good_score_std": metrics["good_score_std"], "samples": int(len(good))}
        model = {"bank": bank, "bank_sq": bank_sq, "meta": model_meta, "proj": proj}
        if other:
            progress(0.93, f"Scoring {len(other)} samples labelled as not good", None)
            neg = []
            for s in other[:50]:
                image = s.load()
                if image is not None:
                    neg.append(anomaly.infer(model, sess, image, (size, size))[1])
            if neg:
                metrics["other_score_mean"] = round(float(np.mean(neg)), 4)
                metrics["other_flagged"] = int(sum(v > threshold for v in neg))
                metrics["other_samples"] = int(len(neg))
                metrics["auroc"] = _auroc(np.array(neg), img)
        progress(0.97, "Packing the model", metrics)
        packed = anomaly.pack(bank, bbytes, model_meta, proj)
        tool_params = {"threshold": 0, "min_area": 30, "device": "auto"}
        return TrainResult(onnx_bytes=bbytes, metrics=metrics, tool_key="dl_anomaly", tool_params=tool_params,
                           weights_bytes=packed, weights_ext=".npz", weights_tool_key="dl_anomaly", weights_tool_params=tool_params)

    def suggest(self, labeled: list[SampleRef], unlabeled: list[SampleRef], classes: list[str], params: dict[str, Any]) -> list[Suggestion]:
        """自動標記＝資料清洗：對未標記樣本回報異常分數，高於門檻的建議標成第二個類別（沒有第二個類別就留空），讓使用者確認
        哪些其實是混進良品集的不良品。"""
        good, _ = _good_samples(labeled + unlabeled, classes)
        if len(good) < 3:
            raise TrainError("At least 3 good pictures are needed before scores can be suggested")
        size = int(params.get("input_size") or 320)
        ratio = min(1.0, float(params.get("coreset_ratio") or 0.1))
        bpath, _ = self._backbone(params)
        sess = anomaly.session_for(bpath, path=bpath, device="auto")
        feats = []
        proj = None
        for s in good[:60]:
            image = s.load()
            if image is not None:
                f = anomaly.extract(sess, image, size)[0]
                if proj is None:
                    proj = anomaly.projection(f.shape[1], int(params.get("projection_dims") if params.get("projection_dims") is not None else 128))
                feats.append(anomaly.project(f, proj))
        all_f = np.concatenate(feats)
        owner = np.concatenate([np.full(len(f), i, dtype=np.int32) for i, f in enumerate(feats)])
        idx = anomaly.coreset(all_f, ratio, seed=7)
        bank = np.ascontiguousarray(all_f[idx])
        bank_sq = np.einsum("ij,ij->i", bank, bank).astype(np.float32)
        bank_owner = owner[idx]
        blur = float(params.get("blur_sigma") or 4.0)
        model = {"bank": bank, "bank_sq": bank_sq, "meta": {"input_size": size, "blur_sigma": blur}, "proj": proj}
        hw = (int(np.sqrt(len(feats[0]))), int(np.sqrt(len(feats[0]))))
        scores = [float(anomaly.score_map(anomaly.nn_distance(f, bank, bank_sq, exclude=(bank_owner == i)), hw, (size, size), blur).max()) for i, f in enumerate(feats)]
        arr = np.array(scores)
        k_sigma = float(params.get("threshold_sigma") or 3.0)
        threshold = float(arr.mean() + k_sigma * arr.std()) if len(arr) else 0.0
        out: list[Suggestion] = []
        bad_label = classes[1] if len(classes) > 1 else ""
        good_label = classes[0] if classes else ""
        for s in unlabeled:
            image = s.load()
            if image is None:
                continue
            score = anomaly.infer(model, sess, image, (size, size))[1]
            out.append(Suggestion(sample_id=s.id, label=bad_label if score > threshold else good_label, score=round(float(score), 4)))
        return out


TRAINERS = [AnomalyTrainer]
