"""批次執行的背景工作：每張影像用 engine.execute 直跑（不走 runner 佇列／統計／SSE／持久化），
影像進獨立快取桶並在每張跑完立即釋放；進度定期寫回 DB，可取消；autotune 模式先座標下降再全量重跑。"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from django.conf import settings as dj_settings

from apps.core.errors import Conflict
from apps.vision import engine
from apps.vision.batch import store
from apps.vision.images import store as image_store
from apps.vision.models import BatchRun, BatchSet, Flow
from apps.vision.runner import runner

log = logging.getLogger("vision.batch")

#: 自動調參搜尋用的標記影像上限（未命中優先），避免 200 張 × 60 次評估。
AUTOTUNE_SAMPLE = 40


@dataclass
class BatchJob:
    run_id: int
    set_id: int
    mode: str = "run"  # run | autotune
    status: str = "running"
    done: int = 0
    total: int = 0
    stage: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    cancel_flag: bool = False
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    thread: threading.Thread | None = None
    autotune: dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_jobs: dict[int, BatchJob] = {}


def _cfg(key: str, default: Any) -> Any:
    return dj_settings.VISION.get(key, default)


def running_count() -> int:
    with _lock:
        return sum(1 for j in _jobs.values() if j.status == "running")


def progress(run_id: int) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(run_id)
        if job is None:
            return None
        return {"done": job.done, "total": job.total, "stage": job.stage, "status": job.status, "mode": job.mode}


def live_items(run_id: int) -> list[dict[str, Any]] | None:
    with _lock:
        job = _jobs.get(run_id)
        return list(job.items) if job else None


def cancel(run_id: int) -> bool:
    with _lock:
        job = _jobs.get(run_id)
        if job is None or job.status != "running":
            return False
        job.cancel_flag = True
        return True


def wait(run_id: int, timeout: float = 120.0) -> bool:
    """測試用：等背景執行緒結束。"""
    with _lock:
        job = _jobs.get(run_id)
    if job is None or job.thread is None:
        return True
    job.thread.join(timeout)
    return not job.thread.is_alive()


def _prune_locked() -> None:
    finished = sorted((j for j in _jobs.values() if j.status != "running"), key=lambda j: j.finished_at)
    for j in finished[:-20] if len(finished) > 20 else []:
        _jobs.pop(j.run_id, None)


def start(run: BatchRun, *, mode: str = "run", autotune: dict[str, Any] | None = None) -> dict[str, Any]:
    with _lock:
        _prune_locked()
        if sum(1 for j in _jobs.values() if j.status == "running") >= int(_cfg("BATCH_MAX_RUNNING", 2)):
            raise Conflict("Too many batch runs at once; try again shortly", code="batch_busy")
        if any(j.status == "running" and j.set_id == run.batch_set_id for j in _jobs.values()):
            raise Conflict("This image set already has a run in progress", code="set_busy")
        job = BatchJob(run_id=run.id, set_id=run.batch_set_id, mode=mode, total=int(run.progress_total or 0), autotune=dict(autotune or {}))
        _jobs[run.id] = job
    BatchRun.objects.filter(pk=run.id).update(status="running")
    job.thread = threading.Thread(target=_run, args=(job,), name=f"batch-{run.id}", daemon=True)
    job.thread.start()
    return progress(run.id) or {}


def execute_rows(flow: Flow, graph: dict[str, Any], images: list[dict[str, Any]], *, on_row: Callable[[dict[str, Any]], None] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> tuple[list[dict[str, Any]], float]:
    """把 graph 在影像集每張影像上跑一遍（同步；背景工作與測試共用）。回 (rows, wall_ms)。"""
    compiled = runner.compiled_for(flow, graph_override=graph)
    timeout_s = float(_cfg("RUN_TIMEOUT_S", 30))
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for item in images:
        if cancelled():
            break
        index = int(item.get("index", len(rows)))
        img = store.load_image(item)
        if img is None:
            row = store.failed_row(index, "The image file could not be read")
        else:
            report = engine.execute(
                compiled, flow_id=store.BATCH_FLOW_ID, flow_version=flow.version, trigger="batch",
                grab=runner._grab, asset_path=runner._asset_path, preview=False, input_image=img,
                run_id=f"batch{uuid.uuid4().hex[:12]}", deadline=time.perf_counter() + timeout_s,
            )
            image_store.drop_run(report.id)
            row = store.compact_row(index, report)
        rows.append(row)
        if on_row is not None:
            on_row(row)
    return rows, (time.perf_counter() - t0) * 1000


def _autotune_graph(job: BatchJob, run: BatchRun, batch_set: BatchSet, images: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """自動調參模式：用影像集的期望標記做座標下降（未命中優先抽樣），回 (新 graph, meta)。"""
    from apps.vision.agent import autotune, service

    parent_status: dict[int, str] = {}
    if run.parent_id:
        parent = BatchRun.objects.filter(pk=run.parent_id).only("items").first()
        if parent is not None:
            parent_status = {int(it.get("index", -1)): str(it.get("status", "")) for it in parent.items or []}
    labeled_imgs = [im for im in images if im.get("expected") in ("ok", "ng")]
    labeled_imgs.sort(key=lambda im: 0 if parent_status.get(int(im["index"])) not in ("", None, im["expected"]) else 1)
    labeled = []
    for im in labeled_imgs[:AUTOTUNE_SAMPLE]:
        img = store.load_image(im)
        if img is not None:
            labeled.append(autotune.Labeled(img, str(im["expected"]), im.get("expect_outputs") or {}, str(im.get("name", ""))))
    if not labeled:
        return run.graph, {"autotune": {"improved": False, "reason": "There is no readable labelled image"}}
    job.stage = f"Auto-tuning: {len(labeled)} labelled images, at most {int(job.autotune.get('max_evals', 40))} evaluations"
    res = autotune.coordinate_search(
        run.graph, labeled, max_evals=int(job.autotune.get("max_evals", 40)), deadline_s=float(job.autotune.get("deadline_s", 60.0)),
        trial=lambda g, im: service.trial_run(g, im, keep_images=False),
    )
    meta = {"autotune": {k: res[k] for k in ("before", "after", "changes", "change_text", "evals", "elapsed_ms", "improved", "budget_hit")}, "sampled": len(labeled)}
    job.stage = ""
    return res["graph"], meta


def _run(job: BatchJob) -> None:
    from django.db import close_old_connections
    from django.utils import timezone

    try:
        run = BatchRun.objects.select_related("batch_set__flow", "flow").get(pk=job.run_id)
        batch_set = run.batch_set
        flow = store.run_flow(run)  # 跨流程測試：用這次指定的流程
        images = list(batch_set.images or [])
        job.total = len(images)
        graph, meta = (run.graph, None)
        if job.mode == "autotune":
            graph, meta = _autotune_graph(job, run, batch_set, images)
            BatchRun.objects.filter(pk=run.id).update(graph=graph, meta=meta or {})
        last_flush = time.perf_counter()

        def on_row(row: dict[str, Any]) -> None:
            nonlocal last_flush
            job.items.append(row)
            job.done += 1
            if job.done % 10 == 0 or (time.perf_counter() - last_flush) > 2.0:
                BatchRun.objects.filter(pk=run.id).update(progress_done=job.done, items=list(job.items))
                last_flush = time.perf_counter()

        rows, wall = execute_rows(flow, graph, images, on_row=on_row, cancelled=lambda: job.cancel_flag)
        status = "cancelled" if (job.cancel_flag and len(rows) < len(images)) else "done"
        run = BatchRun.objects.select_related("batch_set__flow", "flow").get(pk=job.run_id)
        store.finalize_run(run, rows, wall_ms=wall, status=status, graph=graph, meta=meta)
        job.status = status
    except Exception as exc:  # noqa: BLE001 - 批次失敗不影響平台
        log.exception("批次執行失敗")
        job.status = "failed"
        try:
            BatchRun.objects.filter(pk=job.run_id).update(status="failed", error=f"{exc.__class__.__name__}: {str(exc)[:300]}", finished_at=timezone.now(), items=list(job.items), progress_done=job.done)
        except Exception:  # noqa: BLE001
            log.warning("批次失敗狀態寫回失敗", exc_info=True)
    finally:
        job.finished_at = time.time()
        close_old_connections()
