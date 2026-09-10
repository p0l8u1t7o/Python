from __future__ import annotations

import hashlib
import io
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from apps.vision.dl import anomaly


VERSION = 1
DEFAULT_PROJECTION_DIMS = 128
DEFAULT_PROJECTION_SEED = 17
_LOAD_LOCK = threading.Lock()
_LOAD_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


class RetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class LibraryItem:
    vector: np.ndarray
    label_index: int
    thumb_id: str
    thumb: bytes
    source_id: str = ""


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-12 or not math.isfinite(norm):
        return np.zeros_like(arr, dtype=np.float32)
    return (arr / norm).astype(np.float32, copy=False)


def vector_from_features(feats: np.ndarray, proj: np.ndarray | None = None) -> np.ndarray:
    if feats.ndim != 2 or feats.shape[0] <= 0:
        raise RetrievalError("Reference features are empty")
    arr = np.asarray(feats, dtype=np.float32)
    if proj is not None:
        arr = anomaly.project(arr, proj)
    # 平均池化保留整體外觀；最大池化補上局部紋理差異。以 fake backbone
    # 的條紋合成資料量測，平均+最大能把不同紋理的相似度多拉開約 0.18。
    pooled = np.concatenate([arr.mean(axis=0), arr.max(axis=0)], axis=0)
    return _l2_normalize(pooled)


def image_vector(
    sess: Any,
    image: np.ndarray,
    size: int,
    proj: np.ndarray | None = None,
) -> np.ndarray:
    feats, _shape = anomaly.extract(sess, image, int(size))
    return vector_from_features(feats, proj)


def make_thumb(image: np.ndarray, max_side: int = 96) -> bytes:
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim != 3:
        raise RetrievalError("Reference image must be an image array")
    h, w = arr.shape[:2]
    if h <= 0 or w <= 0:
        raise RetrievalError("Reference image is empty")
    scale = min(float(max_side) / float(max(h, w)), 1.0)
    if scale < 1.0:
        arr = cv2.resize(arr, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise RetrievalError("Reference thumbnail could not be encoded")
    return enc.tobytes()


def thumb_id(image: np.ndarray, label: str, source_id: str = "") -> str:
    digest = hashlib.sha256()
    digest.update(str(label).encode("utf-8"))
    digest.update(str(source_id).encode("utf-8"))
    digest.update(np.ascontiguousarray(image).tobytes())
    return digest.hexdigest()[:16]


def _json_array(values: list[Any]) -> np.ndarray:
    return np.asarray(json.dumps(values, ensure_ascii=False), dtype=np.str_)


def _json_obj(value: dict[str, Any]) -> np.ndarray:
    return np.asarray(json.dumps(value, ensure_ascii=False, sort_keys=True), dtype=np.str_)


def pack(
    vectors: np.ndarray,
    labels: np.ndarray,
    classes: list[str],
    thumb_ids: list[str],
    thumbs: list[bytes],
    backbone_bytes: bytes,
    meta: dict[str, Any],
    proj: np.ndarray | None = None,
    source_ids: list[str] | None = None,
) -> bytes:
    vecs = np.asarray(vectors, dtype=np.float32)
    labs = np.asarray(labels, dtype=np.int32)
    if vecs.ndim != 2:
        raise RetrievalError("Reference vectors must be a matrix")
    if len(labs) != len(vecs):
        raise RetrievalError("Reference labels do not match vector count")
    if len(thumb_ids) != len(vecs) or len(thumbs) != len(vecs):
        raise RetrievalError("Reference thumbnails do not match vector count")
    src = list(source_ids or [""] * len(vecs))
    if len(src) != len(vecs):
        raise RetrievalError("Reference source ids do not match vector count")
    normalized = np.vstack([_l2_normalize(v) for v in vecs]).astype(np.float32, copy=False) if len(vecs) else vecs
    packed_meta = {
        "version": VERSION,
        "kind": "retrieval",
        "items": int(len(normalized)),
        **dict(meta),
    }
    payload: dict[str, Any] = {
        "vectors": normalized,
        "labels": labs,
        "classes": _json_array(list(classes)),
        "thumb_ids": _json_array(list(thumb_ids)),
        "source_ids": _json_array(src),
        "backbone": np.frombuffer(bytes(backbone_bytes), dtype=np.uint8),
        "meta": _json_obj(packed_meta),
    }
    if proj is not None:
        payload["proj"] = np.asarray(proj, dtype=np.float32)
    for i, data in enumerate(thumbs):
        payload[f"thumb_{i:06d}"] = np.frombuffer(bytes(data), dtype=np.uint8)
    bio = io.BytesIO()
    np.savez_compressed(bio, **payload)
    return bio.getvalue()


def _read_text(raw: np.ndarray, fallback: Any) -> Any:
    try:
        return json.loads(str(raw.item()))
    except Exception:
        return fallback


def loads(data: bytes, *, path: str = "") -> dict[str, Any]:
    try:
        npz = np.load(io.BytesIO(data), allow_pickle=False)
    except Exception as exc:  # pragma: no cover - numpy exception type varies
        raise RetrievalError(f"Reference library could not be opened: {exc}") from exc
    try:
        vectors = np.asarray(npz["vectors"], dtype=np.float32)
        labels = np.asarray(npz["labels"], dtype=np.int32)
        classes = list(_read_text(npz["classes"], []))
        thumb_ids = list(_read_text(npz["thumb_ids"], []))
        source_ids = list(_read_text(npz["source_ids"], [""] * len(labels)))
        meta = dict(_read_text(npz["meta"], {}))
        backbone = bytes(np.asarray(npz["backbone"], dtype=np.uint8).tobytes())
        proj = np.asarray(npz["proj"], dtype=np.float32) if "proj" in npz.files else None
        thumbs = [bytes(np.asarray(npz[f"thumb_{i:06d}"], dtype=np.uint8).tobytes()) for i in range(len(labels))]
    except KeyError as exc:
        raise RetrievalError(f"Reference library is missing {exc}") from exc
    finally:
        npz.close()
    if vectors.ndim != 2 or len(labels) != len(vectors):
        raise RetrievalError("Reference library has invalid vectors")
    if len(thumb_ids) != len(vectors) or len(thumbs) != len(vectors):
        raise RetrievalError("Reference library has invalid thumbnails")
    if len(source_ids) != len(vectors):
        source_ids = [""] * len(vectors)
    return {
        "vectors": np.vstack([_l2_normalize(v) for v in vectors]).astype(np.float32, copy=False)
        if len(vectors)
        else vectors,
        "labels": labels,
        "classes": classes,
        "thumb_ids": thumb_ids,
        "source_ids": source_ids,
        "thumbs": thumbs,
        "backbone": backbone,
        "meta": meta,
        "proj": proj,
        "_path": path,
    }


def load(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        stat = p.stat()
    except OSError as exc:
        raise RetrievalError(f"Reference library is not available: {p}") from exc
    key = str(p.resolve())
    marker = (int(stat.st_mtime_ns), int(stat.st_size))
    with _LOAD_LOCK:
        cached = _LOAD_CACHE.get(key)
        if cached and cached[0] == marker:
            return cached[1]
    model = loads(p.read_bytes(), path=key)
    with _LOAD_LOCK:
        _LOAD_CACHE[key] = (marker, model)
    return model


def invalidate(path: str | Path | None = None) -> None:
    with _LOAD_LOCK:
        if path is None:
            _LOAD_CACHE.clear()
            return
        try:
            key = str(Path(path).resolve())
        except OSError:
            key = str(path)
        _LOAD_CACHE.pop(key, None)


def backbone_session(
    model: dict[str, Any],
    path: str | Path,
    device: str = "auto",
    override_path: str | Path | None = None,
) -> Any:
    if override_path:
        p = Path(override_path)
        if not p.exists():
            raise RetrievalError(f"Reference model file is not available: {p}")
        return anomaly.session_for(str(p.resolve()), path=p, device=device)
    backbone = model.get("backbone") or b""
    if not backbone:
        raise RetrievalError("Reference library does not include its matcher")
    meta = model.get("meta") or {}
    digest = meta.get("backbone_sha256") or hashlib.sha256(backbone).hexdigest()
    return anomaly.session_for(f"retrieval:{digest}", model_bytes=backbone, device=device)


def _item_id(model: dict[str, Any], index: int) -> str:
    ids = model.get("thumb_ids") or []
    return str(ids[index]) if 0 <= index < len(ids) else str(index)


def _top_entries(
    model: dict[str, Any],
    order: np.ndarray,
    sims: np.ndarray,
) -> list[dict[str, Any]]:
    classes = model.get("classes") or []
    labels = np.asarray(model.get("labels"), dtype=np.int32)
    entries: list[dict[str, Any]] = []
    for idx in order:
        label_index = int(labels[int(idx)])
        label = str(classes[label_index]) if 0 <= label_index < len(classes) else ""
        entries.append(
            {
                "label": label,
                "similarity": float(np.clip(sims[int(idx)], -1.0, 1.0)),
                "index": int(idx),
                "id": _item_id(model, int(idx)),
            }
        )
    return entries


def classify_vector(
    model: dict[str, Any],
    vector: np.ndarray,
    topk: int = 3,
    *,
    exclude_index: int | None = None,
) -> dict[str, Any]:
    vectors = np.asarray(model.get("vectors"), dtype=np.float32)
    labels = np.asarray(model.get("labels"), dtype=np.int32)
    classes = list(model.get("classes") or [])
    if vectors.ndim != 2 or len(vectors) == 0:
        raise RetrievalError("Reference library is empty")
    vec = _l2_normalize(vector)
    sims = vectors @ vec
    if exclude_index is not None and 0 <= exclude_index < len(sims):
        sims = sims.copy()
        sims[exclude_index] = -np.inf
    valid = np.isfinite(sims)
    if not np.any(valid):
        return {"label": "", "similarity": 0.0, "confidence": 0.0, "topk": []}
    k = max(1, min(int(topk or 1), int(np.count_nonzero(valid))))
    order = np.argsort(-sims)[:k]
    top = _top_entries(model, order, sims)
    votes: dict[int, float] = {}
    best_seen: dict[int, float] = {}
    for idx in order:
        label_index = int(labels[int(idx)])
        sim = float(sims[int(idx)])
        votes[label_index] = votes.get(label_index, 0.0) + max(sim, 0.0)
        best_seen[label_index] = max(best_seen.get(label_index, -1.0), sim)
    if not votes:
        return {"label": "", "similarity": 0.0, "confidence": 0.0, "topk": top}
    winner = sorted(votes, key=lambda lab: (-votes[lab], -best_seen.get(lab, -1.0), lab))[0]
    total_vote = float(sum(votes.values()))
    confidence = float(votes[winner] / total_vote) if total_vote > 0 else 0.0
    label = str(classes[winner]) if 0 <= winner < len(classes) else ""
    similarity = max((row["similarity"] for row in top if row["label"] == label), default=0.0)
    return {
        "label": label,
        "similarity": float(np.clip(similarity, -1.0, 1.0)),
        "confidence": confidence,
        "topk": top,
    }


def query(model: dict[str, Any], sess: Any, image: np.ndarray, topk: int = 3) -> dict[str, Any]:
    size = int((model.get("meta") or {}).get("input_size") or 224)
    vec = image_vector(sess, image, size, model.get("proj"))
    return classify_vector(model, vec, topk)


def build_item(
    sess: Any,
    image: np.ndarray,
    label: str,
    classes: list[str],
    size: int,
    proj: np.ndarray | None,
    *,
    source_id: str = "",
) -> LibraryItem:
    if label not in classes:
        classes.append(label)
    index = int(classes.index(label))
    return LibraryItem(
        vector=image_vector(sess, image, size, proj),
        label_index=index,
        thumb_id=thumb_id(image, label, source_id),
        thumb=make_thumb(image),
        source_id=source_id,
    )


def _repack(model: dict[str, Any], vectors: np.ndarray, labels: np.ndarray, thumb_ids: list[str], thumbs: list[bytes], source_ids: list[str]) -> bytes:
    meta = dict(model.get("meta") or {})
    meta["items"] = int(len(vectors))
    return pack(
        vectors,
        labels,
        list(model.get("classes") or []),
        thumb_ids,
        thumbs,
        bytes(model.get("backbone") or b""),
        meta,
        model.get("proj"),
        source_ids=source_ids,
    )


def add(
    model: dict[str, Any],
    image: np.ndarray,
    label: str,
    sess: Any | None = None,
    *, source_id: str = "",
) -> bytes:
    name = str(label or "").strip()
    if not name:
        raise RetrievalError("Reference label is required")
    meta = model.get("meta") or {}
    size = int(meta.get("input_size") or 224)
    classes = list(model.get("classes") or [])
    runner = sess or backbone_session(model, model.get("_path") or "<embedded>", "auto")
    item = build_item(runner, image, name, classes, size, model.get("proj"), source_id=source_id)
    vectors = np.asarray(model.get("vectors"), dtype=np.float32)
    labels = np.asarray(model.get("labels"), dtype=np.int32)
    if vectors.size:
        vectors = np.vstack([vectors, item.vector]).astype(np.float32, copy=False)
    else:
        vectors = item.vector.reshape(1, -1)
    labels = np.concatenate([labels, np.asarray([item.label_index], dtype=np.int32)])
    model_copy = {**model, "classes": classes}
    return _repack(
        model_copy,
        vectors,
        labels,
        list(model.get("thumb_ids") or []) + [item.thumb_id],
        list(model.get("thumbs") or []) + [item.thumb],
        list(model.get("source_ids") or []) + [item.source_id],
    )


def remove(model: dict[str, Any], index: int) -> bytes:
    vectors = np.asarray(model.get("vectors"), dtype=np.float32)
    labels = np.asarray(model.get("labels"), dtype=np.int32)
    idx = int(index)
    if idx < 0 or idx >= len(vectors):
        raise RetrievalError("Reference item index is out of range")
    keep = np.ones(len(vectors), dtype=bool)
    keep[idx] = False
    return _repack(
        model,
        vectors[keep],
        labels[keep],
        [v for i, v in enumerate(model.get("thumb_ids") or []) if i != idx],
        [v for i, v in enumerate(model.get("thumbs") or []) if i != idx],
        [v for i, v in enumerate(model.get("source_ids") or []) if i != idx],
    )


def leave_one_out(
    vectors: np.ndarray,
    labels: np.ndarray,
    classes: list[str],
    topk: int = 3,
) -> float:
    vecs = np.asarray(vectors, dtype=np.float32)
    labs = np.asarray(labels, dtype=np.int32)
    if len(vecs) <= 1:
        return 0.0
    model = {
        "vectors": vecs,
        "labels": labs,
        "classes": classes,
        "thumb_ids": [str(i) for i in range(len(vecs))],
    }
    ok = 0
    total = 0
    for i, vec in enumerate(vecs):
        result = classify_vector(model, vec, topk, exclude_index=i)
        expected = str(classes[int(labs[i])]) if 0 <= int(labs[i]) < len(classes) else ""
        ok += int(result["label"] == expected)
        total += 1
    return float(ok / total) if total else 0.0

