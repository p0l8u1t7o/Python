"""Runner：流程執行的生命週期、並行上限、結果快取、事件推播、背景持久化。

- 每個 Flow 一個 FlowRuntime：編譯快取（依 version）、一次只跑一個 run 的鎖、
  最近一次結果、統計（次數、平均／最大耗時、OK/NG 數）。
- 全域 ThreadPoolExecutor(max_workers=VISION_MAX_WORKERS)：同時忙碌的流程數上限，
  可用 .env 擴充。同一流程的 run 排隊上限 MAX_QUEUE_PER_FLOW，超過拒絕（429）。
- 結果以事件推給 SSE 訂閱者（threading.Condition，行程內真推播，不查 DB）。
- FlowRun 列由背景執行緒批次寫入（VISION_PERSIST_RUNS=1），不擋執行緒池。
- 連續模式：每個流程一條 loop 執行緒，間隔 continuous_interval_ms。

只允許一個 API 行程（引擎狀態在行程內）；水平擴展要換成獨立引擎服務。
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from django.conf import settings
from django.db import IntegrityError, close_old_connections
from django.db.models import F, Value
from django.db.models.functions import Greatest

from apps.core.errors import Conflict, NotFound, RateLimited
from apps.vision import archive, engine
from apps.vision import reporting, spc, variables
from apps.vision.graph import CompiledGraph, compile_graph, restrict_to, validate_graph
from apps.vision.images import store
from apps.vision.models import Asset, Flow, FlowRecipe, FlowRun, FlowRunHourly, ImageSource, MeasurementLog
from apps.vision.sources import grab_by_id, open_source

log = logging.getLogger(__name__)


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


# ---------------------------------------------------------------------------
# 事件匯流排（行程內）
# ---------------------------------------------------------------------------
class EventBus:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._seq = 0
        self._buffer: list[tuple[int, dict]] = []
        self._keep = 500

    def publish(self, event: dict) -> None:
        with self._cond:
            self._seq += 1
            self._buffer.append((self._seq, event))
            if len(self._buffer) > self._keep:
                self._buffer = self._buffer[-self._keep :]
            self._cond.notify_all()

    def wait(self, since: int, timeout: float) -> tuple[int, list[dict]]:
        with self._cond:
            if self._seq <= since:
                self._cond.wait(timeout)
            items = [(s, e) for s, e in self._buffer if s > since]
            return (items[-1][0] if items else since), [e for _, e in items]

    @property
    def seq(self) -> int:
        return self._seq


bus = EventBus()


# ---------------------------------------------------------------------------
# 持久化（背景）
# ---------------------------------------------------------------------------
class _Persister(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="vision-persist", daemon=True)
        self.q: queue.Queue[engine.RunReport | None] = queue.Queue(maxsize=5000)
        self._launched = False
        self._prune_counter = 0

    def ensure(self) -> None:
        if not self._launched:
            self._launched = True
            self.start()

    def submit(self, report: engine.RunReport) -> None:
        if not _cfg("PERSIST_RUNS", True):
            return
        self.ensure()
        try:
            self.q.put_nowait(report)
        except queue.Full:
            log.warning("run 持久化佇列已滿，丟棄 %s", report.id)

    def run(self) -> None:
        while True:
            try:
                report = self.q.get(timeout=2.0)
            except queue.Empty:
                # 沒有 run 也要把流程變數寫回（PLC 用 SET 改了料號，兩秒內落地），順便看看該不該做資料保留整理
                try:
                    variables.store.flush()
                    self._housekeeping()
                finally:
                    close_old_connections()
                continue
            if report is None:
                return
            batch = [report]
            while len(batch) < 100:
                try:
                    nxt = self.q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    return
                batch.append(nxt)
            try:
                self._write(batch)
                variables.store.flush()
            except Exception:  # noqa: BLE001
                log.exception("寫入 FlowRun 失敗")
            finally:
                close_old_connections()

    @staticmethod
    def _housekeeping() -> None:
        """閒置時的資料保留整理：retention 自己判斷時間到了沒、引擎忙不忙（每批 500 列就讓出）。"""
        if not _cfg("RETENTION_SWEEP", True):
            return
        try:
            from apps.vision import retention

            if retention.background_enabled():
                retention.maybe_sweep()
        except Exception:  # noqa: BLE001 - 維護不能拖垮持久化
            log.exception("資料保留整理失敗")

    @staticmethod
    def _rollup(rows: list[FlowRun]) -> None:
        """把這一批累加進每小時彙總（永久保留；明細清掉後趨勢還在）。"""
        buckets: dict[tuple[int, Any, str, str], dict[str, float]] = {}
        for row in rows:
            hour = row.started_at.replace(minute=0, second=0, microsecond=0)
            key = (row.flow_id, hour, row.station_id, row.recipe)
            b = buckets.setdefault(key, {"ok": 0, "ng": 0, "failed": 0, "total_ms": 0.0, "max_ms": 0.0})
            b[row.status if row.status in ("ok", "ng") else "failed"] += 1
            b["total_ms"] += row.duration_ms
            b["max_ms"] = max(b["max_ms"], row.duration_ms)
        for (flow_id, hour, station, recipe), b in buckets.items():
            try:
                updated = FlowRunHourly.objects.filter(flow_id=flow_id, hour=hour, station_id=station, recipe=recipe).update(
                    ok=F("ok") + int(b["ok"]), ng=F("ng") + int(b["ng"]), failed=F("failed") + int(b["failed"]),
                    total_ms=F("total_ms") + b["total_ms"], max_ms=Greatest(F("max_ms"), Value(b["max_ms"])),
                )
                if not updated:
                    FlowRunHourly.objects.create(
                        flow_id=flow_id, hour=hour, station_id=station, recipe=recipe,
                        ok=int(b["ok"]), ng=int(b["ng"]), failed=int(b["failed"]), total_ms=b["total_ms"], max_ms=b["max_ms"],
                    )
            except IntegrityError:  # 同時兩批寫同一個小時：重試一次 update 就好
                FlowRunHourly.objects.filter(flow_id=flow_id, hour=hour, station_id=station, recipe=recipe).update(
                    ok=F("ok") + int(b["ok"]), ng=F("ng") + int(b["ng"]), failed=F("failed") + int(b["failed"]),
                    total_ms=F("total_ms") + b["total_ms"], max_ms=Greatest(F("max_ms"), Value(b["max_ms"])),
                )

    @staticmethod
    def _log_measurements(batch: list[engine.RunReport], rows: list[FlowRun]) -> int:
        """具名數值輸出 → MeasurementLog（WP-14）；與明細同一批寫、bool 與非數值略過。回寫入筆數。"""
        if not _cfg("MEASUREMENT_LOG", True):
            return 0
        logs: list[MeasurementLog] = []
        for r, row in zip(batch, rows):
            for name, value in (r.outputs or {}).items():
                if spc.is_number(value):
                    logs.append(MeasurementLog(flow_id=r.flow_id, run_id=row.id, name=str(name)[:80], value=float(value), ts=row.started_at, station_id=row.station_id))
        if logs:
            try:
                MeasurementLog.objects.bulk_create(logs, batch_size=500, ignore_conflicts=True)
            except IntegrityError:  # 流程剛被刪：這批量測值跟著丟
                return 0
        return len(logs)

    def _write(self, batch: list[engine.RunReport]) -> None:
        rows = [
            FlowRun(
                id=uuid.UUID(r.id) if len(r.id) == 32 else uuid.uuid4(),
                flow_id=r.flow_id,
                flow_version=r.flow_version,
                status=r.status,
                trigger=r.trigger,
                station_id=r.station_id or str(_cfg("STATION_ID", "ST01")),
                recipe=r.recipe,
                duration_ms=r.duration_ms,
                nodes={nid: {"status": n.status, "duration_ms": round(n.duration_ms, 2), "message": n.message[:200]} for nid, n in r.nodes.items()},
                outputs=_json_safe(r.outputs),
                images=archive.save(r, getattr(r, "archive_images", None) or {}),
                error=r.error[:2000],
                started_at=datetime.fromtimestamp(r.started_at, tz=timezone.utc),
                finished_at=datetime.fromtimestamp(r.finished_at, tz=timezone.utc),
            )
            for r in batch
        ]
        try:
            FlowRun.objects.bulk_create(rows, ignore_conflicts=True)
        except IntegrityError:
            # 流程在 run 結束前被刪：逐筆寫，跳過已無主的列。
            for row in rows:
                try:
                    row.save()
                except IntegrityError:
                    pass
        self._rollup(rows)
        self._log_measurements(batch, rows)
        self._prune_counter += len(rows)
        if self._prune_counter >= 500:
            self._prune_counter = 0
            from apps.vision import retention as _retention

            keep_cfg = _retention.effective()
            mdays = int(keep_cfg["measurement_days"])
            if mdays > 0:
                MeasurementLog.objects.filter(ts__lt=datetime.now(timezone.utc) - timedelta(days=mdays)).delete()
            days = int(keep_cfg["run_days"])
            if days > 0:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                for run_id, images in FlowRun.objects.filter(started_at__lt=cutoff).values_list("id", "images")[:5000]:
                    archive.drop_run(run_id.hex, images)
                FlowRun.objects.filter(started_at__lt=cutoff).delete()
            keep = int(_cfg("KEEP_RUN_ROWS", 2000))
            for flow_id in {r.flow_id for r in batch}:
                doomed = list(FlowRun.objects.filter(flow_id=flow_id).order_by("-started_at").values_list("id", "images")[keep : keep + 1000])
                if doomed:
                    for run_id, images in doomed:
                        archive.drop_run(run_id.hex, images)
                    FlowRun.objects.filter(id__in=[d[0] for d in doomed]).delete()
            archive.purge()  # 順便照天數與容量上限清封存


def _json_safe(value: Any) -> Any:
    """NaN／inf 轉 None：SQLite 的 JSON_VALID 會拒絕 NaN，一個算不出來的量測值不能讓整筆 run 記錄消失。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


persister = _Persister()


# 變數一髒就確保持久化執行緒活著（它每 2 秒會 flush 一次）
variables.store.on_dirty = persister.ensure
# ---------------------------------------------------------------------------
# 每流程的執行期狀態
# ---------------------------------------------------------------------------
@dataclass
class FlowStats:
    runs: int = 0
    ok: int = 0
    ng: int = 0
    failed: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0
    last_status: str = ""
    last_run_id: str = ""
    last_finished_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs, "ok": self.ok, "ng": self.ng, "failed": self.failed,
            "avg_ms": round(self.total_ms / self.runs, 2) if self.runs else 0.0,
            "max_ms": round(self.max_ms, 2), "last_ms": round(self.last_ms, 2),
            "last_status": self.last_status, "last_run_id": self.last_run_id,
            "last_finished_at": self.last_finished_at,
        }


@dataclass
class FlowRuntime:
    flow_id: int
    compiled: CompiledGraph | None = None
    compiled_version: int = -1
    #: (version, recipe_id, recipe_updated_at) → 編譯結果
    compiled_by_recipe: dict = field(default_factory=dict)
    #: 這個 gate 是「容量號誌」：容量放在 concurrency 這個記憶體欄位，
    #: 由 submit()（呼叫者執行緒，本來就會碰 DB）從 Flow.concurrency 更新。
    #: **執行緒池裡等待的 run 一律只讀記憶體**——熱路徑不碰資料庫是這個引擎的硬規則，
    #: 早期版本在 wait 迴圈裡每 50 ms 查一次 Flow，一條排隊的 run 一秒就打 20 次 SQLite。
    #: 調大並行度時，下一次 submit 就會把新容量帶進來；調小時不硬砍已在跑的 run。
    #: concurrency=1 時條件就是 running < 1，行為等同原本整段 with lock。
    gate: threading.Condition = field(default_factory=lambda: threading.Condition(threading.Lock()))
    #: 目前允許的同時 run 數（submit 在呼叫者執行緒更新，gate 只讀它）
    concurrency: int = 1
    queued: int = 0
    running: int = 0
    stats: FlowStats = field(default_factory=FlowStats)
    #: 最近的 run 報告（新在後），上限 KEEP_RUN_IMAGES。
    recent: list[engine.RunReport] = field(default_factory=list)
    continuous: "ContinuousLoop | None" = None
    #: 已受理但還沒有結果的 run：run_id → "queued" | "running"（非同步觸發的外部系統靠它查進度）
    pending: dict[str, str] = field(default_factory=dict)

    def report(self, run_id: str) -> engine.RunReport | None:
        for r in reversed(self.recent):
            if r.id == run_id:
                return r
        return None


class Runner:
    def __init__(self) -> None:
        self._runtimes: dict[int, FlowRuntime] = {}
        self._lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None
        self._active = 0
        self._active_lock = threading.Lock()
        self._workers_busy = 0
        self._workers_lock = threading.Lock()
        self._asset_paths: dict[str, str] = {}

    # -- 池 ---------------------------------------------------------------
    @property
    def max_workers(self) -> int:
        return max(1, int(_cfg("MAX_WORKERS", 10)))

    def pool(self) -> ThreadPoolExecutor:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="vision-run")
        return self._pool

    def runtime(self, flow_id: int) -> FlowRuntime:
        with self._lock:
            rt = self._runtimes.get(flow_id)
            if rt is None:
                rt = self._runtimes[flow_id] = FlowRuntime(flow_id=flow_id)
            return rt

    def clear_recent(self, flow_id: int) -> None:
        """清除該流程在記憶體內的執行紀錄與統計（影像快取一併釋放）。"""
        rt = self.runtime(flow_id)
        with self._lock:
            recent, rt.recent = rt.recent, []
            rt.stats = FlowStats()
            rt.pending.clear()
        for r in recent:
            store.drop_run(r.id)
        bus.publish({"type": "cleared", "flow_id": flow_id, "stats": rt.stats.to_dict()})

    def forget(self, flow_id: int) -> None:
        self.stop_continuous(flow_id)
        with self._lock:
            rt = self._runtimes.pop(flow_id, None)
        if rt:
            for r in rt.recent:
                store.drop_run(r.id)
        variables.store.forget(flow_id)
        reporting.forget(flow_id)

    @property
    def max_queue_per_flow(self) -> int:
        """同一流程可同時等待的觸發數（每個流程一次只跑一個 run，超過此數的觸發立刻回 429）。"""
        return max(1, int(_cfg("MAX_QUEUE_PER_FLOW", 16)))

    def capacity(self) -> dict[str, Any]:
        with self._lock:
            busy = [
                {"flow_id": fid, "running": rt.running, "queued": rt.queued, "continuous": bool(rt.continuous and rt.continuous.is_alive())}
                for fid, rt in self._runtimes.items()
                if rt.running or rt.queued or (rt.continuous and rt.continuous.is_alive())
            ]
        with self._active_lock:
            active = self._active
        with self._workers_lock:
            workers_busy = self._workers_busy
        return {"max_workers": self.max_workers, "max_queue_per_flow": self.max_queue_per_flow, "active": active,
                "workers_busy": workers_busy, "flows": busy, "images": store.stats()}

    def sync_wait_available(self) -> tuple[bool, dict[str, Any]]:
        """同步觸發前的死結檢查。

        呼叫中的 run 已佔住一條 ThreadPoolExecutor worker；若所有 worker 都在跑或等流程 gate，
        子流程即使 submit 進去也沒有執行緒可跑，父流程再 result() 等它就會互等。這裡同時看
        runner.capacity() 與 pool 的待辦佇列：只在有空 worker 且沒有已排在 executor 裡的工作時才允許同步等。
        """
        data = self.capacity()
        queued = 0
        if self._pool is not None:
            try:
                queued = int(self._pool._work_queue.qsize())  # noqa: SLF001 - ThreadPoolExecutor 沒有公開待辦深度。
            except Exception:  # noqa: BLE001
                queued = 1
        ok = int(data["workers_busy"]) < int(data["max_workers"]) and queued == 0
        return ok, {**data, "executor_queued": queued}

    def pending_status(self, run_id: str) -> tuple[int, str] | None:
        """已受理但還沒有結果的 run → (flow_id, "queued"|"running")。"""
        with self._lock:
            for fid, rt in self._runtimes.items():
                state = rt.pending.get(run_id)
                if state:
                    return fid, state
        return None

    # -- 編譯 ---------------------------------------------------------------
    def compiled_for(self, flow: Flow, *, graph_override: dict | None = None, recipe: "FlowRecipe | None" = None) -> CompiledGraph:
        if graph_override is not None:
            graph = apply_recipe(graph_override, recipe) if recipe else graph_override
            compiled = compile_graph(validate_graph(graph))
            self._prefetch(compiled)
            return compiled
        rt = self.runtime(flow.id)
        # 結果回送規則在呼叫者執行緒讀進記憶體（引擎執行緒的熱路徑不碰資料庫）
        reporting.set_rules(flow.id, flow.comm, flow.name)
        # 流程自己的 updated_at 也進鍵：同一個 id、同一個版本但內容不同（測試裡序號重用、還原舊版）不會拿到舊的編譯結果
        key = (flow.version, flow.updated_at.isoformat() if flow.updated_at else "", recipe.id if recipe else 0, recipe.updated_at.isoformat() if recipe else "")
        cached = rt.compiled_by_recipe.get(key)
        if cached is not None:
            return cached
        graph = apply_recipe(flow.graph, recipe) if recipe else flow.graph
        compiled = compile_graph(validate_graph(graph))
        self._prefetch(compiled)
        # 版本變了就清掉舊版本的所有配方編譯。
        rt.compiled_by_recipe = {k: v for k, v in rt.compiled_by_recipe.items() if k[0] == flow.version}
        rt.compiled_by_recipe[key] = compiled
        rt.compiled = compiled if not recipe else rt.compiled
        rt.compiled_version = flow.version
        return compiled

    #: 其他子系統（例如 Modbus 連線）在呼叫者執行緒預先開好資源的掛勾：fn(compiled) -> None。
    prefetch_hooks: list = []

    def _prefetch(self, compiled: CompiledGraph) -> None:
        """在呼叫者執行緒把影像來源打開、資產路徑查好：執行緒池內的熱路徑不碰資料庫。"""
        for hook in list(self.prefetch_hooks):
            try:
                hook(compiled)
            except Exception:  # noqa: BLE001
                log.warning("prefetch hook %r 失敗", hook, exc_info=True)
        source_ids: set[int] = set()
        asset_ids: set[str] = set()
        for cn in compiled.nodes.values():
            params = cn.node.get("params") or {}
            for p in cn.tool.params:
                value = params.get(p.key)
                if value in (None, ""):
                    continue
                if p.kind == "source":
                    try:
                        source_ids.add(int(value))
                    except (TypeError, ValueError):
                        pass
                elif p.kind == "asset":
                    asset_ids.add(str(value))
        for source in ImageSource.objects.filter(pk__in=source_ids):
            try:
                open_source(source)
            except Exception:  # noqa: BLE001 — 開不起來的來源在執行時會回報，不在這裡擋
                log.warning("影像來源 %s 預先開啟失敗", source.name, exc_info=True)
        if asset_ids:
            with self._lock:
                for asset in Asset.objects.filter(pk__in=asset_ids):
                    self._asset_paths[str(asset.id)] = asset.path

    # -- 執行 ---------------------------------------------------------------
    def submit(
        self,
        flow: Flow,
        *,
        trigger: str = "manual",
        input_image: np.ndarray | None = None,
        context: dict[str, Any] | None = None,
        preview: bool = False,
        graph_override: dict | None = None,
        until_node: str | None = None,
        recipe: "FlowRecipe | str | int | None" = None,
    ) -> Future:
        if not flow.is_enabled and not preview:
            raise Conflict("The flow is disabled", code="flow_disabled")
        recipe_obj = resolve_recipe(flow, recipe)
        compiled = self.compiled_for(flow, graph_override=graph_override, recipe=recipe_obj)
        # 流程變數在呼叫者執行緒載入（引擎執行緒不碰 DB）
        variables.store.ensure_loaded(flow.id)
        variables.store.ensure_loaded(None)
        if until_node:
            compiled = restrict_to(compiled, until_node)
        rt = self.runtime(flow.id)
        # 並行度在這裡（呼叫者執行緒）讀進記憶體，執行緒池的 gate 才不用碰 DB
        rt.concurrency = max(1, int(getattr(flow, "concurrency", 1) or 1))
        limit = self.max_queue_per_flow
        run_id = uuid.uuid4().hex
        with self._lock:
            if rt.queued >= limit:
                raise RateLimited(f"Flow '{flow.name}' already has {rt.queued}/{limit} triggers waiting; try again shortly", code="flow_queue_full")
            rt.queued += 1
            rt.pending[run_id] = "queued"
        bus.publish({"type": "run_queued", "flow_id": flow.id, "run_id": run_id, "trigger": trigger})
        # 封存策略在呼叫者執行緒解析（熱路徑不碰 DB），跟著這次 run 走。
        future = self.pool().submit(self._execute, flow, compiled, rt, run_id, trigger, input_image, context, preview,
                                    recipe_obj.name if recipe_obj else "", archive.policy_for(flow))
        future.run_id = run_id  # 非同步觸發（TCP TRIGGER、POST run?wait=0）要把 run_id 回給外部系統
        return future

    def run_sync(self, flow: Flow, *, timeout: float | None = None, **kw: Any) -> engine.RunReport:
        future = self.submit(flow, **kw)
        return future.result(timeout=timeout or float(_cfg("RUN_TIMEOUT_S", 30)) + 5)

    def _flow_concurrency(self, rt: FlowRuntime, flow: Flow) -> int:
        """目前的並行度。**只讀記憶體**——submit() 已在呼叫者執行緒把 Flow.concurrency 帶進來。"""
        current = rt.concurrency or getattr(flow, "concurrency", 1) or 1
        return max(1, int(current))

    def _acquire_flow_slot(self, rt: FlowRuntime, flow: Flow) -> None:
        with rt.gate:
            while rt.running >= self._flow_concurrency(rt, flow):
                rt.gate.wait(0.05)
            rt.running += 1
            rt.gate.notify_all()

    @staticmethod
    def _release_flow_slot(rt: FlowRuntime) -> None:
        with rt.gate:
            rt.running = max(0, rt.running - 1)
            rt.gate.notify_all()

    def _execute(
        self,
        flow: Flow,
        compiled: CompiledGraph,
        rt: FlowRuntime,
        run_id: str,
        trigger: str,
        input_image: np.ndarray | None,
        context: dict[str, Any] | None,
        preview: bool,
        recipe_name: str = "",
        archive_policy: dict[str, Any] | None = None,
    ) -> engine.RunReport:
        with self._workers_lock:
            self._workers_busy += 1
        try:
            self._acquire_flow_slot(rt, flow)
            # 排隊數在「真的取得流程許可」時才扣：等 gate 的 run 也算在排隊上限內，
            # 否則執行緒池有空位時上限永遠不會生效。
            with self._lock:
                rt.queued -= 1
                if run_id in rt.pending:
                    rt.pending[run_id] = "running"
            with self._active_lock:
                self._active += 1
            bus.publish({"type": "run_started", "flow_id": flow.id, "run_id": run_id})
            try:
                if input_image is None and context and context.get("_input_image_ref"):
                    input_image = store.get(str(context.get("_input_image_ref") or ""))
                deadline = time.perf_counter() + float(_cfg("RUN_TIMEOUT_S", 30))
                report = engine.execute(
                    compiled,
                    flow_id=flow.id,
                    flow_version=flow.version,
                    trigger=trigger,
                    grab=self._grab,
                    asset_path=self._asset_path,
                    preview=preview,
                    initial_context=context,
                    input_image=input_image,
                    run_id=run_id,
                    deadline=deadline,
                    flow_timeout_s=getattr(flow, "timeout_s", 0),
                    stop_on_ng=bool(getattr(flow, "stop_on_ng", False)),
                )
            except Exception as exc:  # noqa: BLE001 — 引擎本身的 bug，不該發生
                log.exception("引擎失敗 flow=%s", flow.id)
                report = engine.RunReport(id=run_id, flow_id=flow.id, flow_version=flow.version, trigger=trigger, status="failed", error=f"engine: {exc!r}", started_at=time.time(), finished_at=time.time())
            finally:
                with self._active_lock:
                    self._active -= 1
                self._release_flow_slot(rt)
                close_old_connections()
        finally:
            with self._workers_lock:
                self._workers_busy = max(0, self._workers_busy - 1)
        report.station_id = str(_cfg("STATION_ID", "ST01"))
        report.recipe = recipe_name
        report.archive_policy = archive_policy
        if not flow.commissioned and not preview:
            report.warnings.append("On-site teaching is not finished (not yet confirmed on the teach page)")
        with self._lock:
            rt.pending.pop(run_id, None)  # 結果已在 recent，查詢改走 report()
        self._record(rt, report)
        return report

    def _record(self, rt: FlowRuntime, report: engine.RunReport) -> None:
        s = rt.stats
        s.runs += 1
        s.total_ms += report.duration_ms
        s.max_ms = max(s.max_ms, report.duration_ms)
        s.last_ms = report.duration_ms
        s.last_status = report.status
        s.last_run_id = report.id
        s.last_finished_at = report.finished_at
        if report.status == "ok":
            s.ok += 1
        elif report.status == "ng":
            s.ng += 1
        else:
            s.failed += 1
        keep = int(_cfg("KEEP_RUN_IMAGES", 8))
        with self._lock:
            rt.recent.append(report)
            while len(rt.recent) > keep:
                old = rt.recent.pop(0)
                store.drop_run(old.id)
        if report.trigger != "preview":
            # 封存的影像在這裡只取參照（不複製、不編碼）；編碼與寫檔在持久化執行緒做。
            policy = getattr(report, "archive_policy", None)
            if policy and archive.wanted(policy, report.status, s.runs):
                report.archive_images = archive.capture(report, store, queue_depth=persister.q.qsize())
            persister.submit(report)
        bus.publish({"type": "run_finished", "flow_id": rt.flow_id, "run": report.to_dict(include_node_outputs=True), "stats": s.to_dict()})
        if report.trigger != "preview" and report.flow_id > 0:
            # 逐片回送：跑完就在這條執行緒送出去（不經佇列也不經匯流排，才不會漏掉任何一片）
            reporting.deliver(report)

    # -- 接縫 ---------------------------------------------------------------
    @staticmethod
    def _grab(source_id: str) -> np.ndarray | None:
        return grab_by_id(source_id)

    def _asset_path(self, asset_id: str) -> str | None:
        cached = self._asset_paths.get(str(asset_id))
        if cached:
            return cached
        try:
            asset = Asset.objects.filter(pk=asset_id).first()
        except Exception:  # noqa: BLE001
            return None
        if asset:
            self._asset_paths[str(asset.id)] = asset.path
            return asset.path
        return None

    def forget_asset(self, asset_id: str) -> None:
        self._asset_paths.pop(str(asset_id), None)

    # -- 連續模式 -----------------------------------------------------------
    def start_continuous(self, flow: Flow) -> None:
        rt = self.runtime(flow.id)
        if rt.continuous and rt.continuous.is_alive():
            return
        if not flow.is_enabled:
            raise Conflict("The flow is disabled", code="flow_disabled")
        self.compiled_for(flow)
        rt.continuous = ContinuousLoop(self, flow)
        rt.continuous.start()
        bus.publish({"type": "continuous", "flow_id": flow.id, "running": True})

    def stop_continuous(self, flow_id: int) -> None:
        rt = self.runtime(flow_id)
        loop = rt.continuous
        if loop and loop.is_alive():
            loop.stop()
            loop.join(timeout=float(_cfg("RUN_TIMEOUT_S", 30)) + 1)
        rt.continuous = None
        bus.publish({"type": "continuous", "flow_id": flow_id, "running": False})

    def is_continuous(self, flow_id: int) -> bool:
        rt = self._runtimes.get(flow_id)
        return bool(rt and rt.continuous and rt.continuous.is_alive())

    def shutdown(self) -> None:
        for fid in list(self._runtimes):
            self.stop_continuous(fid)
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)


class ContinuousLoop(threading.Thread):
    """連續模式：Flow 物件在啟動時帶入，之後每 REFRESH_S 秒才回資料庫確認一次
    （停用／改圖），迴圈本身不碰資料庫。"""

    REFRESH_S = 2.0

    def __init__(self, runner: Runner, flow: Flow) -> None:
        super().__init__(name=f"vision-loop-{flow.id}", daemon=True)
        self.runner = runner
        self.flow = flow
        self.flow_id = flow.id
        self.interval = max(0, int(flow.continuous_interval_ms)) / 1000.0
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        last_refresh = time.monotonic()
        while not self._halt.is_set():
            t0 = time.perf_counter()
            try:
                if time.monotonic() - last_refresh > self.REFRESH_S:
                    last_refresh = time.monotonic()
                    fresh = Flow.objects.filter(pk=self.flow_id).first()
                    close_old_connections()
                    if fresh is None or not fresh.is_enabled:
                        break
                    self.flow = fresh
                    self.interval = max(0, int(fresh.continuous_interval_ms)) / 1000.0
                self.runner.run_sync(self.flow, trigger="continuous")
            except RateLimited:
                time.sleep(0.05)
            except Exception:  # noqa: BLE001
                log.exception("連續模式 flow=%s 例外", self.flow_id)
                time.sleep(0.5)
            remain = self.interval - (time.perf_counter() - t0)
            if remain > 0:
                self._halt.wait(remain)
        with self.runner._lock:
            rt = self.runner._runtimes.get(self.flow_id)
        if rt and rt.continuous is self:
            rt.continuous = None
        bus.publish({"type": "continuous", "flow_id": self.flow_id, "running": False})


runner = Runner()


def apply_recipe(graph: dict, recipe: "FlowRecipe | None") -> dict:
    """把配方的參數覆寫疊到圖上（不動原圖）。overrides = {node_id: {param: value}}。"""
    if not recipe or not recipe.param_overrides:
        return graph
    import copy

    out = copy.deepcopy(graph)
    overrides = recipe.param_overrides or {}
    for node in out.get("nodes", []):
        patch = overrides.get(str(node.get("id")))
        if isinstance(patch, dict):
            node["params"] = {**(node.get("params") or {}), **patch}
    return out


def resolve_recipe(flow: Flow, recipe: "FlowRecipe | str | int | None") -> "FlowRecipe | None":
    """recipe 可為物件、id、名稱；None 時用預設配方（若有）。查無 → NotFound。"""
    if isinstance(recipe, FlowRecipe):
        return recipe
    if recipe in (None, ""):
        return FlowRecipe.objects.filter(flow=flow, is_default=True).first()
    qs = FlowRecipe.objects.filter(flow=flow)
    row = qs.filter(pk=int(recipe)).first() if str(recipe).isdigit() else qs.filter(name=str(recipe)).first()
    if row is None:
        raise NotFound(f"Recipe '{recipe}' not found", code="recipe_not_found")
    return row


def get_flow(flow_id: int) -> Flow:
    flow = Flow.objects.filter(pk=flow_id).first()
    if flow is None:
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    return flow


__all__ = ["runner", "bus", "persister", "get_flow", "Runner", "FlowRuntime"]
