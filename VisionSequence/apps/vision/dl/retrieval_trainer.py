from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from apps.vision.dl import anomaly, retrieval
from apps.vision.dl.base import Param, ProgressFn, SampleRef, Suggestion, TrainError, Trainer, TrainResult


def _as_int(params: dict[str, Any], name: str, default: int) -> int:
    try:
        return int(params.get(name, default))
    except (TypeError, ValueError):
        return default


def _as_bool(params: dict[str, Any], name: str, default: bool = False) -> bool:
    value = params.get(name, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _image(sample: Any) -> np.ndarray:
    img = sample.load()
    if img is None:
        raise TrainError(f"Sample image is not available: {sample.id}")
    return img


def _rotate(image: np.ndarray, degrees: float) -> np.ndarray:
    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        return image.copy()
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), degrees, 1.0)
    border = cv2.BORDER_REFLECT_101
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=border)


def _variants(image: np.ndarray, enabled: bool, angle: int) -> list[tuple[str, np.ndarray]]:
    items = [("orig", image)]
    if not enabled:
        return items
    items.append(("flip", cv2.flip(image, 1)))
    if angle > 0:
        items.append((f"rot_p{angle}", _rotate(image, float(angle))))
        items.append((f"rot_n{angle}", _rotate(image, float(-angle))))
    return items


class RetrievalTrainer(Trainer):
    kind = "retrieval"
    label = "Image reference library"
    description = "Builds a reference library that can grow by adding labeled images."
    label_mode = "classes"
    tool_key = "dl_retrieval"
    devices = ("cpu", "cuda")
    min_per_class = 1
    params = (
        Param(
            "input_size",
            "Input size",
            kind="select",
            default=224,
            options=[
                {"label": "224 px", "value": 224},
                {"label": "320 px", "value": 320},
                {"label": "448 px", "value": 448},
            ],
            help_text="Square size used when adding references.",
        ),
        Param(
            "topk",
            "Vote count",
            kind="number",
            default=3,
            minimum=1,
            maximum=25,
            step=1,
            help_text="Number of nearest references used for the final label.",
        ),
        Param(
            "augment",
            "Store light variants",
            kind="boolean",
            default=False,
            help_text="Adds mirrored and slightly tilted references for each labeled image.",
        ),
        Param(
            "augment_angle",
            "Tilt angle",
            kind="number",
            default=3,
            minimum=0,
            maximum=15,
            step=1,
            visible_when={"param": "augment", "equals": True},
            help_text="Small angle used when light variants are stored.",
        ),
        Param(
            "projection_dims",
            "Compact library",
            kind="select",
            default=retrieval.DEFAULT_PROJECTION_DIMS,
            options=[
                {"label": "Off", "value": 0},
                {"label": "Small", "value": 64},
                {"label": "Standard", "value": retrieval.DEFAULT_PROJECTION_DIMS},
            ],
            group="Advanced",
            help_text="Keeps each reference compact while preserving similarity.",
        ),
        Param(
            "backbone_path",
            "Reference matcher file",
            kind="text",
            default="",
            group="Advanced",
            help_text="Internal file override for tests.",
            visible_when={"param": "device", "in": []},
        ),
    )

    def _backbone(self, params: dict[str, Any]) -> tuple[Path, bytes]:
        custom = str(params.get("backbone_path") or "").strip()
        path = Path(custom) if custom else Path(anomaly.backbone_path("resnet18"))
        if not path.exists():
            raise TrainError(f"Reference matcher is not available: {path}")
        return path, path.read_bytes()

    def _build(
        self,
        samples: list[SampleRef],
        classes: list[str],
        params: dict[str, Any],
        *,
        collect_thumbs: bool,
    ) -> tuple[np.ndarray, np.ndarray, list[str], list[bytes], list[str], np.ndarray | None, bytes, dict[str, Any]]:
        if not classes:
            raise TrainError("At least one class is required")
        labeled = [s for s in samples if getattr(s, "label", "") in classes and s.split != "test"]
        if not labeled:
            raise TrainError("At least one labeled image is required")
        size = _as_int(params, "input_size", 224)
        topk = max(1, _as_int(params, "topk", 3))
        augment = _as_bool(params, "augment")
        angle = max(0, min(15, _as_int(params, "augment_angle", 3)))
        proj_dims = max(0, _as_int(params, "projection_dims", retrieval.DEFAULT_PROJECTION_DIMS))
        _path, backbone_bytes = self._backbone(params)
        session = anomaly.session_for(
            f"retrieval-train:{hashlib.sha256(backbone_bytes).hexdigest()}",
            model_bytes=backbone_bytes,
            device=str(params.get("device") or "auto"),
        )
        vectors: list[np.ndarray] = []
        labels: list[int] = []
        thumb_ids: list[str] = []
        thumbs: list[bytes] = []
        source_ids: list[str] = []
        proj: np.ndarray | None = None
        for sample in labeled:
            label = str(sample.label)
            label_index = int(classes.index(label))
            image = _image(sample)
            for suffix, variant in _variants(image, augment, angle):
                feats, _shape = anomaly.extract(session, variant, size)
                if proj is None and proj_dims > 0 and feats.shape[1] > proj_dims:
                    proj = anomaly.projection(feats.shape[1], proj_dims, retrieval.DEFAULT_PROJECTION_SEED)
                vectors.append(retrieval.vector_from_features(feats, proj))
                labels.append(label_index)
                source = f"{sample.id}:{suffix}"
                source_ids.append(source)
                thumb_ids.append(retrieval.thumb_id(variant, label, source))
                thumbs.append(retrieval.make_thumb(variant) if collect_thumbs else b"")
        if not vectors:
            raise TrainError("No labeled images could be added")
        matrix = np.vstack(vectors).astype(np.float32, copy=False)
        label_arr = np.asarray(labels, dtype=np.int32)
        meta = {
            "version": retrieval.VERSION,
            "input_size": size,
            "topk": topk,
            "pooling": "mean+max",
            "projection_seed": retrieval.DEFAULT_PROJECTION_SEED if proj is not None else None,
            "projection_dims": int(proj.shape[1]) if proj is not None else 0,
            "backbone_sha256": hashlib.sha256(backbone_bytes).hexdigest(),
            "augmented": bool(augment),
        }
        return matrix, label_arr, thumb_ids, thumbs, source_ids, proj, backbone_bytes, meta

    def train(
        self,
        samples: list[SampleRef],
        classes: list[str],
        params: dict[str, Any],
        device: str,
        progress: ProgressFn,
    ) -> TrainResult:
        classes = [str(c) for c in (classes or [])]
        progress(0.02, "Loading references", None)
        matrix, labels, thumb_ids, thumbs, source_ids, proj, backbone_bytes, meta = self._build(
            samples,
            classes,
            {**params, "device": device},
            collect_thumbs=True,
        )
        progress(0.78, "Checking the library", None)
        topk = int(meta["topk"])
        counts = {name: int(np.count_nonzero(labels == i)) for i, name in enumerate(classes)}
        loo = retrieval.leave_one_out(matrix, labels, classes, topk)
        metrics = {
            "library_size": int(len(matrix)),
            "classes": int(len(classes)),
            "per_class": counts,
            "leave_one_out_accuracy": float(loo),
            "samples": int(len(samples)),
            "augmented": bool(meta["augmented"]),
            "topk": topk,
        }
        progress(0.92, "Packing the library", metrics)
        packed = retrieval.pack(
            matrix,
            labels,
            classes,
            thumb_ids,
            thumbs,
            backbone_bytes,
            meta,
            proj,
            source_ids=source_ids,
        )
        return TrainResult(
            onnx_bytes=backbone_bytes,
            metrics=metrics,
            tool_key="dl_retrieval",
            tool_params={"topk": topk, "min_similarity": 0.0, "device": "auto"},
            weights_bytes=packed,
            weights_ext=".npz",
            weights_tool_key="dl_retrieval",
            weights_tool_params={"topk": topk, "min_similarity": 0.0, "device": "auto"},
        )

    def suggest(
        self,
        labeled: list[SampleRef],
        unlabeled: list[SampleRef],
        classes: list[str],
        params: dict[str, Any],
    ) -> list[Suggestion]:
        classes = [str(c) for c in (classes or [])]
        labeled = [s for s in labeled if getattr(s, "label", "") in classes]
        pending = [s for s in unlabeled if not getattr(s, "label", "")]
        if not labeled or not pending:
            return []
        matrix, labels, thumb_ids, thumbs, source_ids, proj, backbone_bytes, meta = self._build(
            labeled,
            classes,
            params,
            collect_thumbs=False,
        )
        model = {
            "vectors": matrix,
            "labels": labels,
            "classes": classes,
            "thumb_ids": thumb_ids,
            "source_ids": source_ids,
            "thumbs": thumbs,
            "backbone": backbone_bytes,
            "meta": meta,
            "proj": proj,
        }
        session = anomaly.session_for(
            f"retrieval-suggest:{hashlib.sha256(backbone_bytes).hexdigest()}",
            model_bytes=backbone_bytes,
            device=str(params.get("device") or "auto"),
        )
        suggestions: list[Suggestion] = []
        topk = int(meta["topk"])
        for sample in pending:
            result = retrieval.query(model, session, _image(sample), topk)
            if result["label"]:
                suggestions.append(Suggestion(sample_id=str(sample.id), label=str(result["label"]), score=float(result["similarity"])))
        suggestions.sort(key=lambda item: item.score)
        return suggestions


TRAINERS = [RetrievalTrainer]
