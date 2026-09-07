"""訓練工作：單一訓練槽的背景執行緒（訓練吃 CPU/GPU，不占用檢測執行緒池）。

- 一次只跑一個訓練（第二個進來回 409），前端輪詢 status()。
- 執行緒自己開 DB 連線：讀樣本 → 訓練（progress 進記憶體）→ 模型檔寫進 `ASSET_DIR/dl/pending/<job>/`
  → close_old_connections()（自己執行緒結束才呼叫）。
- **訓練完不會自動進資產庫**：產物先擱在 pending 資料夾，使用者在畫面上命名後按儲存才 `save()` 建 Asset
  並回寫專案的 last_asset_id / last_metrics；不要的按 `discard()` 整個刪掉。試了三種超參數只留最好的那個，
  資產庫就不會被半成品塞滿。
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
class PendingModel:
    """訓練完成、還沒存進資產庫的產物：檔案在 `dir` 底下，`save()` 時才搬進 ASSET_DIR 建 Asset。"""

    dir: str
    onnx_path: str
    tool_key: str
    tool_params: dict[str, Any] = field(default_factory=dict)
    #: 原生權重（YOLO 的 best.pt、異常檢測的 npz）：有的話它才是主產物，ONNX 另存一個
    weights_path: str = ""
    weights_ext: str = ""
    weights_tool_key: str = ""
    weights_tool_params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    project_name: str = ""


@dataclass
class TrainJob:
    id: str
    project_id: int
    project_name: str
    trainer_kind: str
    device: str
    status: str = "running"  # running | done | failed | cancelled
    progress: float = 0.0
    stage: str = "Preparing"
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    #: 存進資產庫之後才有（沒存就是空的）
    asset_id: str = ""
    #: 建議的名稱；儲存時可改
    asset_name: str = ""
    #: 訓練好但還沒決定要不要留的產物
    pending: PendingModel | None = None
    #: 使用者按了放棄
    discarded: bool = False
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
            "pending": self.pending is not None, "saved": bool(self.asset_id), "discarded": self.discarded,
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
        _clear_pending(_job)  # 上一次訓練沒存也沒放棄的產物：開始新的就丟掉（不然 pending 會越積越多）
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
        job.status, job.stage = "cancelled", "Cancelled"
    except TrainError as exc:
        job.status, job.error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 — 訓練失敗不影響平台
        log.exception("訓練失敗")
        job.status, job.error = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        job.finished_at = time.time()
        close_old_connections()  # 自己執行緒結束，關掉自己的連線


def pending_root() -> str:
    return os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "pending")


def _clear_pending(job: TrainJob | None) -> None:
    """丟掉一個工作還沒處理的產物檔（沒有就當沒事）。"""
    import shutil

    if job is None or job.pending is None:
        return
    shutil.rmtree(job.pending.dir, ignore_errors=True)
    job.pending = None


def _train(job: TrainJob, project_id: int, params: dict[str, Any]) -> None:
    from apps.vision.models import DlProject

    trainer = get_trainer(job.trainer_kind)
    project = DlProject.objects.get(pk=project_id)
    rows = list(project.samples.all())
    samples = [SampleRef(id=str(r.id), label=r.label, path=r.path, shapes=list(r.shapes or []), split=r.split) for r in rows]
    classes = [str(c) for c in (project.classes or [])]

    progress = TrainProgress(job)
    result = trainer.train(samples, classes, params, job.device, progress)

    # 產物先落在 pending 資料夾：使用者命名並確認後才進資產庫（save），不要就整個刪掉（discard）
    folder = os.path.join(pending_root(), job.id)
    os.makedirs(folder, exist_ok=True)
    onnx_path = os.path.join(folder, "model.onnx")
    with open(onnx_path, "wb") as f:
        f.write(result.onnx_bytes)
    pending = PendingModel(dir=folder, onnx_path=onnx_path, tool_key=result.tool_key, tool_params=dict(result.tool_params),
                           metrics=dict(result.metrics), project_name=project.name)
    if result.weights_bytes and result.weights_tool_key:
        pending.weights_ext = result.weights_ext
        pending.weights_path = os.path.join(folder, f"weights{result.weights_ext}")
        pending.weights_tool_key = result.weights_tool_key
        pending.weights_tool_params = dict(result.weights_tool_params)
        with open(pending.weights_path, "wb") as f:
            f.write(result.weights_bytes)

    job.pending = pending
    job.metrics = dict(result.metrics)
    job.tool_key = pending.weights_tool_key or pending.tool_key
    job.tool_params = pending.weights_tool_params or pending.tool_params
    job.progress, job.stage, job.status = 1.0, "Finished", "done"


def save(name: str = "", job: TrainJob | None = None) -> dict[str, Any]:
    """把剛訓練好的模型存進資產庫（原生權重是主產物，ONNX 另存一個），並回寫專案的最後模型。
    `job` 只有測試會傳；平台上永遠是目前那個訓練工作。"""
    from apps.vision.models import Asset, DlProject

    if job is None:
        with _lock:
            job = _job
    if job is None or job.status != "done" or job.pending is None:
        raise Conflict("No trained model is waiting to be saved", code="no_pending_model")
    p = job.pending
    asset_name = (name or job.asset_name).strip() or f"{p.project_name}-model"
    has_weights = bool(p.weights_path)
    asset_dir = str(settings.VISION["ASSET_DIR"])

    onnx_id = uuid.uuid4()
    onnx_dest = os.path.join(asset_dir, f"{onnx_id.hex}.onnx")
    os.replace(p.onnx_path, onnx_dest)  # 同一個 ASSET_DIR 底下，換名字就好
    Asset.objects.create(
        id=onnx_id, name=f"{asset_name} (ONNX)" if has_weights else asset_name, kind="model", path=onnx_dest, size=os.path.getsize(onnx_dest),
        meta={"trainer": job.trainer_kind, "project": p.project_name, "tool_key": p.tool_key, "tool_params": p.tool_params, "metrics": p.metrics, "format": "onnx"},
    )
    primary_id, tool_key, tool_params = onnx_id, p.tool_key, p.tool_params
    if has_weights:
        weights_id = uuid.uuid4()
        dest = os.path.join(asset_dir, f"{weights_id.hex}{p.weights_ext}")
        os.replace(p.weights_path, dest)
        Asset.objects.create(
            id=weights_id, name=asset_name, kind="model", path=dest, size=os.path.getsize(dest),
            meta={"trainer": job.trainer_kind, "project": p.project_name, "tool_key": p.weights_tool_key, "tool_params": p.weights_tool_params,
                  "metrics": p.metrics, "format": p.weights_ext.lstrip("."), "onnx_asset_id": onnx_id.hex},
        )
        primary_id, tool_key, tool_params = weights_id, p.weights_tool_key, p.weights_tool_params

    metrics = {**p.metrics, "onnx_asset_id": onnx_id.hex}
    DlProject.objects.filter(pk=job.project_id).update(last_asset_id=primary_id.hex, last_metrics=metrics)
    job.metrics, job.asset_id, job.asset_name = metrics, primary_id.hex, asset_name
    job.tool_key, job.tool_params = tool_key, tool_params
    _clear_pending(job)
    log.info("訓練產物存入資產庫：%s（%s）", asset_name, tool_key)
    return job.to_dict()


def discard(job: TrainJob | None = None) -> bool:
    """不要這個模型：把 pending 的檔案刪掉（資產庫本來就還沒有東西）。"""
    if job is None:
        with _lock:
            job = _job
    if job is None or job.pending is None:
        return False
    _clear_pending(job)
    job.discarded = True
    return True
