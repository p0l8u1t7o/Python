"""訓練工作：單一訓練槽的背景執行緒（訓練吃 CPU/GPU，不占用檢測執行緒池）。

- 一次只跑一個訓練（第二個進來回 409），前端輪詢 status()。
- 執行緒自己開 DB 連線：讀樣本 → 訓練（progress 進記憶體）→ 匯出 ONNX 存成 Asset →
  回寫專案的 last_asset_id / last_metrics → close_old_connections()（自己執行緒結束才呼叫）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from apps.core.errors import Conflict
from apps.vision.dl.base import SampleRef, TrainCancelled, TrainError, get_trainer

log = logging.getLogger(__name__)


@dataclass
class TrainJob:
    id: str
    project_id: int
    project_name: str
    trainer_kind: str
    device: str
    status: str = "running"  # running | done | failed | cancelled
    progress: float = 0.0
    stage: str = "準備中"
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    asset_id: str = ""
    asset_name: str = ""
    tool_key: str = ""
    tool_params: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel = False
    #: 每個 epoch 的指標（loss/mAP 曲線用）：[{"epoch": n, ...}]。
    history: list[dict[str, Any]] = field(default_factory=list)
    #: 訓練 log 環形緩衝（最近 _LOG_KEEP 行）＋已丟棄行數（換算全域行號）。
    logs: list[str] = field(default_factory=list)
    log_base: int = 0

    def add_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {message}")
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
            "id": self.id, "project_id": self.project_id, "project_name": self.project_name,
            "trainer_kind": self.trainer_kind, "device": self.device, "status": self.status,
            "progress": round(self.progress, 3), "stage": self.stage, "metrics": self.metrics,
            "error": self.error, "asset_id": self.asset_id, "asset_name": self.asset_name,
            "tool_key": self.tool_key, "tool_params": self.tool_params,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "history": list(self.history),
            "logs": logs, "log_from": log_from_out, "log_next": self.log_base + len(self.logs),
        }


_LOG_KEEP = 400

_lock = threading.Lock()
_job: TrainJob | None = None  # 最近一個（含執行中）


class TrainProgress:
    """交給 trainer 的進度物件：可呼叫（相容 ProgressFn），另有 log()／history()。"""

    def __init__(self, job: TrainJob) -> None:
        self._job = job

    def __call__(self, fraction: float, stage: str, metrics: dict[str, Any] | None) -> None:
        if self._job.cancel:
            raise TrainCancelled()
        self._job.progress, self._job.stage = float(fraction), str(stage)
        if metrics:
            self._job.metrics = metrics
            # 帶 epoch 的指標自動累積成曲線（trainer 不用自己呼叫 history()）
            epoch = metrics.get("epoch")
            if isinstance(epoch, int) and (not self._job.history or self._job.history[-1].get("epoch") != epoch):
                point = {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and k not in ("epochs", "samples", "val_samples")}
                if len(point) > 1:
                    self._job.history.append(point)

    def log(self, message: str) -> None:
        self._job.add_log(str(message))

    def history(self, point: dict[str, Any]) -> None:
        """一個 epoch 的指標點（loss/mAP 曲線）；同 epoch 已存在時合併更新。"""
        epoch = point.get("epoch")
        if self._job.history and self._job.history[-1].get("epoch") == epoch:
            self._job.history[-1].update(point)
        else:
            self._job.history.append(dict(point))


def status(log_from: int | None = None) -> dict[str, Any] | None:
    with _lock:
        return _job.to_dict(log_from) if _job else None


def cancel() -> bool:
    with _lock:
        if _job and _job.status == "running":
            _job.cancel = True
            return True
        return False


def start(project, params: dict[str, Any], device: str, asset_name: str) -> dict[str, Any]:
    """開始訓練；已有訓練在跑回 409。"""
    global _job
    trainer = get_trainer(project.trainer_kind)  # 先驗 kind
    if device not in trainer.devices:
        device = trainer.devices[0]
    with _lock:
        if _job and _job.status == "running":
            raise Conflict(f"Training is already running ({_job.project_name})", code="training_busy")
        job = TrainJob(
            id=uuid.uuid4().hex[:12], project_id=project.id, project_name=project.name,
            trainer_kind=project.trainer_kind, device=device,
            asset_name=asset_name or f"{project.name}-{time.strftime('%m%d-%H%M')}",
        )
        _job = job
    thread = threading.Thread(target=_run, args=(job, project.id, dict(params)), name=f"dl-train-{job.id}", daemon=True)
    thread.start()
    return job.to_dict()


def _run(job: TrainJob, project_id: int, params: dict[str, Any]) -> None:
    from django.db import close_old_connections

    try:
        _train(job, project_id, params)
    except TrainCancelled:
        job.status, job.stage = "cancelled", "已取消"
    except TrainError as exc:
        job.status, job.error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 — 訓練失敗不影響平台
        log.exception("訓練失敗")
        job.status, job.error = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        job.finished_at = time.time()
        close_old_connections()  # 自己執行緒結束，關掉自己的連線


def _train(job: TrainJob, project_id: int, params: dict[str, Any]) -> None:
    from apps.vision.models import Asset, DlProject

    trainer = get_trainer(job.trainer_kind)
    project = DlProject.objects.get(pk=project_id)
    rows = list(project.samples.all())
    samples = [SampleRef(id=str(r.id), label=r.label, path=r.path, shapes=list(r.shapes or []), split=r.split) for r in rows]
    classes = [str(c) for c in (project.classes or [])]

    progress = TrainProgress(job)
    result = trainer.train(samples, classes, params, job.device, progress)

    has_weights = bool(result.weights_bytes and result.weights_tool_key)
    onnx_id = uuid.uuid4()
    onnx_name = f"{job.asset_name}（ONNX）" if has_weights else job.asset_name
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{onnx_id.hex}.onnx")
    with open(path, "wb") as f:
        f.write(result.onnx_bytes)
    Asset.objects.create(
        id=onnx_id, name=onnx_name, kind="model", path=path, size=len(result.onnx_bytes),
        meta={"trainer": job.trainer_kind, "project": project.name, "tool_key": result.tool_key, "tool_params": result.tool_params, "metrics": result.metrics, "format": "onnx"},
    )
    primary_id, tool_key, tool_params = onnx_id, result.tool_key, result.tool_params
    if has_weights:
        # 原生權重（best.pt）另存一個資產，成為專案主產物：對應的 yolo_* 工具直接選它
        weights_id = uuid.uuid4()
        wpath = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{weights_id.hex}{result.weights_ext}")
        with open(wpath, "wb") as f:
            f.write(result.weights_bytes)
        Asset.objects.create(
            id=weights_id, name=job.asset_name, kind="model", path=wpath, size=len(result.weights_bytes),
            meta={"trainer": job.trainer_kind, "project": project.name, "tool_key": result.weights_tool_key, "tool_params": result.weights_tool_params,
                  "metrics": result.metrics, "format": result.weights_ext.lstrip("."), "onnx_asset_id": onnx_id.hex},
        )
        primary_id, tool_key, tool_params = weights_id, result.weights_tool_key, result.weights_tool_params
    result.metrics = {**result.metrics, "onnx_asset_id": onnx_id.hex}
    project.last_asset_id = primary_id.hex
    project.last_metrics = result.metrics
    project.save(update_fields=["last_asset_id", "last_metrics", "updated_at"])

    job.metrics = result.metrics
    job.asset_id = primary_id.hex
    job.tool_key = tool_key
    job.tool_params = tool_params
    job.progress, job.stage, job.status = 1.0, "完成", "done"
