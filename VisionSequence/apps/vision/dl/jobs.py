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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "project_id": self.project_id, "project_name": self.project_name,
            "trainer_kind": self.trainer_kind, "device": self.device, "status": self.status,
            "progress": round(self.progress, 3), "stage": self.stage, "metrics": self.metrics,
            "error": self.error, "asset_id": self.asset_id, "asset_name": self.asset_name,
            "tool_key": self.tool_key, "tool_params": self.tool_params,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_s": round((self.finished_at or time.time()) - self.started_at, 1),
        }


_lock = threading.Lock()
_job: TrainJob | None = None  # 最近一個（含執行中）


def status() -> dict[str, Any] | None:
    with _lock:
        return _job.to_dict() if _job else None


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
            raise Conflict(f"已有訓練在進行中（{_job.project_name}）", code="training_busy")
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
    samples = [SampleRef(id=str(r.id), label=r.label, path=r.path) for r in rows]
    classes = [str(c) for c in (project.classes or [])]

    def progress(fraction: float, stage: str, metrics: dict[str, Any] | None) -> None:
        if job.cancel:
            raise TrainCancelled()
        job.progress, job.stage = float(fraction), str(stage)
        if metrics:
            job.metrics = metrics

    result = trainer.train(samples, classes, params, job.device, progress)

    asset_id = uuid.uuid4()
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.onnx")
    with open(path, "wb") as f:
        f.write(result.onnx_bytes)
    Asset.objects.create(
        id=asset_id, name=job.asset_name, kind="model", path=path, size=len(result.onnx_bytes),
        meta={"trainer": job.trainer_kind, "project": project.name, "tool_key": result.tool_key, "tool_params": result.tool_params, "metrics": result.metrics},
    )
    project.last_asset_id = asset_id.hex
    project.last_metrics = result.metrics
    project.save(update_fields=["last_asset_id", "last_metrics", "updated_at"])

    job.metrics = result.metrics
    job.asset_id = asset_id.hex
    job.tool_key = result.tool_key
    job.tool_params = result.tool_params
    job.progress, job.stage, job.status = 1.0, "完成", "done"
