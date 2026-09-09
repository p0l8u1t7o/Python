"""從影片建立深度學習樣本。

背景工作重用平台工具 `ai_segment`、`edge_filter`、`track_objects`；追蹤狀態透過 ToolContext 的
variables overlay 保存，flow_id=0 不會污染任何產線流程變數。
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.core.errors import Conflict, NotFound, ValidationError
from apps.vision.models import Asset, DlProject, DlSample
from apps.vision.tools.base import ToolContext, ToolError
from apps.vision.tools.builtin.lists import EdgeFilterTool
from apps.vision.tools.builtin.track import TrackObjectsTool
from apps.vision.tools.builtin.yolo import YoloSegmentTool

log = logging.getLogger(__name__)

_LOG_KEEP = 300
_lock = threading.Lock()
_job: VideoExtractJob | None = None


@dataclass
class VideoExtractJob:
    id: str
    project_id: int
    video_path: str
    params: dict[str, Any]
    status: str = "running"
    progress: float = 0.0
    frame: int = 0
    total_frames: int = 0
    saved: int = 0
    duplicates: int = 0
    per_class: dict[str, int] = field(default_factory=dict)
    recent: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel: bool = False
    logs: list[str] = field(default_factory=list)
    log_base: int = 0

    def add_log(self, message: str) -> None:
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        overflow = len(self.logs) - _LOG_KEEP
        if overflow > 0:
            del self.logs[:overflow]
            self.log_base += overflow

    def to_dict(self, log_from: int | None = None) -> dict[str, Any]:
        if log_from is None:
            logs, log_from_out = list(self.logs), self.log_base
        else:
            offset = max(0, log_from - self.log_base)
            logs, log_from_out = self.logs[offset:], max(log_from, self.log_base)
        return {
            "id": self.id, "project_id": self.project_id, "video_path": self.video_path, "params": dict(self.params),
            "status": self.status, "progress": round(self.progress, 3), "frame": self.frame, "total_frames": self.total_frames,
            "saved": self.saved, "duplicates": self.duplicates, "per_class": dict(self.per_class), "recent": list(self.recent),
            "error": self.error, "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "logs": logs, "log_from": log_from_out, "log_next": self.log_base + len(self.logs),
        }


class _ContextFactory:
    def __init__(self, params: dict[str, Any]) -> None:
        self.params = params
        self.context: dict[str, Any] = {"_sandbox": True, "_variables_overlay": {}}

    def ctx(self, node_id: str, tool_params: dict[str, Any], inputs: dict[str, Any]) -> ToolContext:
        return ToolContext(
            run_id="video-extract", flow_id=0, node={"id": node_id, "params": tool_params}, inputs=inputs,
            context=self.context, moment=time.time(), log=lambda *_a, **_kw: None,
            asset_path=_asset_path, grab=lambda _source_id: None, preview=True,
        )


def _asset_path(asset_id: str) -> str | None:
    asset = Asset.objects.filter(pk=asset_id).first()
    return asset.path if asset is not None else None


def _pixels_sha256(image: np.ndarray) -> str:
    digest = hashlib.sha256(str(image.shape).encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def _existing_shas(project: DlProject) -> set[str]:
    return {h for h in project.samples.values_list("sha256", flat=True) if h}


def _sample_dir(project: DlProject) -> str:
    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", str(project.id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _save_sample(project: DlProject, image: np.ndarray, shapes: list[dict[str, Any]], split: str, sha: str) -> DlSample:
    sample_id = uuid.uuid4()
    path = os.path.join(_sample_dir(project), f"{sample_id.hex}.png")
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValidationError("Could not encode the image", code="encode_failed")
    buf.tofile(path)
    return DlSample.objects.create(
        id=sample_id, project=project, label="", labeled_by="auto" if shapes else "",
        path=path, width=int(image.shape[1]), height=int(image.shape[0]),
        sha256=sha, shapes=shapes, split=split,
    )


def _int(params: dict[str, Any], key: str, default: int, lo: int = 1, hi: int = 100000) -> int:
    try:
        return max(lo, min(hi, int(params.get(key, default))))
    except (TypeError, ValueError):
        return default


def _float(params: dict[str, Any], key: str, default: float, lo: float = 0.0) -> float:
    try:
        return max(lo, float(params.get(key, default)))
    except (TypeError, ValueError):
        return default


def _normalize_shapes(matches: list[dict[str, Any]], width: int, height: int) -> tuple[list[dict[str, Any]], list[str]]:
    shapes: list[dict[str, Any]] = []
    labels: list[str] = []
    for match in matches:
        label = str(match.get("label") or match.get("index") or "object")
        points = match.get("polygon") if isinstance(match.get("polygon"), list) else []
        if not points:
            x0 = float(match.get("x", 0))
            y0 = float(match.get("y", 0))
            x1 = x0 + float(match.get("w", 0))
            y1 = y0 + float(match.get("h", 0))
            points = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        norm = []
        for pt in points:
            try:
                x, y = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                continue
            norm.append([min(1.0, max(0.0, x / max(1, width))), min(1.0, max(0.0, y / max(1, height)))])
        if len(norm) >= 3:
            shapes.append({"label": label, "kind": "polygon", "points": norm})
            labels.append(label)
    return shapes, labels


def _merge_classes(project: DlProject, labels: list[str]) -> None:
    classes = list(project.classes or [])
    changed = False
    for label in labels:
        if label and label not in classes:
            classes.append(label)
            changed = True
    if changed:
        project.classes = classes
        project.save(update_fields=["classes", "updated_at"])


def ai_segment(image: np.ndarray, params: dict[str, Any], factory: _ContextFactory) -> list[dict[str, Any]]:
    """平台分割工具入口；測試可 mock 此函式，不需要 GPU 底模。"""
    result = YoloSegmentTool().execute(factory.ctx("ai_segment", params, {"image": image}))
    return list(result.outputs.get("matches") or [])


def _edge_filter(image: np.ndarray, matches: list[dict[str, Any]], params: dict[str, Any], factory: _ContextFactory) -> list[dict[str, Any]]:
    result = EdgeFilterTool().execute(factory.ctx("edge_filter", params, {"image": image, "matches": matches}))
    return list(result.outputs.get("matches") or [])


def _track(image: np.ndarray, matches: list[dict[str, Any]], params: dict[str, Any], factory: _ContextFactory) -> dict[str, Any]:
    result = TrackObjectsTool().execute(factory.ctx("track_objects", params, {"image": image, "matches": matches}))
    return dict(result.outputs)


def start(project_id: int, video_path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """開始影片抽樣；已有抽樣工作在跑回 409。"""
    global _job
    project = DlProject.objects.filter(pk=project_id).first()
    if project is None:
        raise NotFound("Teaching project not found", code="dl_project_not_found")
    path = Path(video_path)
    if not path.is_file():
        raise NotFound("Video not found", code="video_not_found")
    with _lock:
        if _job and _job.status == "running":
            raise Conflict("Video extraction is already running", code="video_extract_busy")
        job = VideoExtractJob(uuid.uuid4().hex[:12], project_id, str(path), dict(params or {}))
        _job = job
    thread = threading.Thread(target=_run, args=(job,), name=f"dl-video-{job.id}", daemon=True)
    thread.start()
    return job.to_dict()


def status(log_from: int | None = None) -> dict[str, Any] | None:
    with _lock:
        return _job.to_dict(log_from) if _job else None


def stop() -> bool:
    with _lock:
        if _job and _job.status == "running":
            _job.cancel = True
            return True
        return False


def _run(job: VideoExtractJob) -> None:
    from django.db import close_old_connections

    try:
        _extract(job)
        if job.status == "running":
            job.status = "done"
            job.progress = 1.0
    except _Cancelled:
        job.status = "cancelled"
        job.add_log("Cancelled")
    except (ToolError, ValidationError, OSError) as exc:
        job.status = "failed"
        job.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("影片抽樣失敗")
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        job.finished_at = time.time()
        close_old_connections()


class _Cancelled(Exception):
    pass


def _extract(job: VideoExtractJob) -> None:
    project = DlProject.objects.get(pk=job.project_id)
    params = dict(project.params or {})
    params.update(job.params)
    max_per_track = _int(params, "max_per_track", _int(params, "n", 3), 1, 100)
    interval = _int(params, "frame_interval", _int(params, "k", 5), 1, 100000)
    stride = _int(params, "stride", 1, 1, 100000)
    split = str(params.get("split") or "")
    if split not in ("", "train", "val", "test"):
        raise ValidationError("split must be train, val, test or empty", code="bad_split")
    seg_params = {
        "model": params.get("model") or project.last_asset_id or "",
        "model_size": params.get("model_size") or "n",
        "model_name": params.get("model_name") or "",
        "imgsz": params.get("imgsz") or 640,
        "conf": _float(params, "conf", 0.25),
        "iou": _float(params, "iou", 0.45),
        "min_area": _int(params, "min_area", 0, 0),
        "max_count": _int(params, "max_count", 100, 1),
        "tracker": "none",
    }
    edge_params = {
        "margin_top": _float(params, "margin_top", 50),
        "margin_bottom": _float(params, "margin_bottom", 50),
        "margin_left": _float(params, "margin_left", 0),
        "margin_right": _float(params, "margin_right", 0),
    }
    track_params = {
        "state_name": "video_extract_tracks",
        "algorithm": params.get("algorithm") or "platform",
        "max_distance": _float(params, "max_distance", 25),
        "max_missing": _int(params, "max_missing", 2, 0),
        "confirm_frames": _int(params, "confirm_frames", 2, 1),
        "motion": params.get("motion") or "linear",
    }
    cap = cv2.VideoCapture(job.video_path)
    if not cap.isOpened():
        raise ValidationError("Could not open the video", code="bad_video")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        job.total_frames = total
        seen = _existing_shas(project)
        factory = _ContextFactory(params)
        per_track: dict[int, dict[str, int]] = {}
        per_class = Counter()
        frame_no = 0
        while True:
            if job.cancel:
                raise _Cancelled()
            ok, image = cap.read()
            if not ok:
                break
            frame_no += 1
            job.frame = frame_no
            if total:
                job.progress = min(0.999, frame_no / total)
            if (frame_no - 1) % stride:
                continue
            matches = ai_segment(image, seg_params, factory)
            kept = _edge_filter(image, matches, edge_params, factory)
            tracks = _track(image, kept, track_params, factory)
            confirmed = list(tracks.get("confirmed") or [])
            due = []
            for item in confirmed:
                tid = int(item.get("id") or 0)
                state = per_track.setdefault(tid, {"saved": 0, "last": -interval})
                if state["saved"] < max_per_track and frame_no - state["last"] >= interval:
                    due.append(tid)
            if not due:
                continue
            sha = _pixels_sha256(image)
            if sha in seen:
                job.duplicates += 1
                for tid in due:
                    per_track[tid]["saved"] += 1
                    per_track[tid]["last"] = frame_no
                continue
            shapes, labels = _normalize_shapes(kept, image.shape[1], image.shape[0])
            _merge_classes(project, labels)
            sample = _save_sample(project, image, shapes, split, sha)
            seen.add(sha)
            for tid in due:
                per_track[tid]["saved"] += 1
                per_track[tid]["last"] = frame_no
            per_class.update(labels)
            job.saved += 1
            job.per_class = dict(per_class)
            job.recent = ([{"id": str(sample.id), "frame": frame_no, "shapes": len(shapes)}] + job.recent)[:8]
            job.add_log(f"Saved frame {frame_no}: {len(shapes)} shapes")
    finally:
        cap.release()
