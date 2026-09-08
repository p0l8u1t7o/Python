"""靜默暖機: 以直跑路徑預先載入流程與工具狀態.

暖機會先編譯流程, 再用 `engine.execute()` 直接執行一次, 不經 runner 佇列與
`Runner._record()`, 因此不會累計統計, 不會發 SSE, 不會寫 FlowRun. `flow_id`
固定使用負值, 讓變數工具進入 sandbox overlay, 不寫入真正的流程或站台變數.

真實 `image_source` 預設不取像. 若流程先前已由 runner 留下來源影像快取, 暖機會
把該影像當作 `_input_image` 重跑一次, 讓 `auto` 與 `input` 模式可暖機而不碰相機.
若來源節點強制 `source` 模式, 或尚無可用 recent image, 則只完成編譯並回報
`skipped`; 此作法避免伺服器啟動時對產線相機多觸發一次.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
import uuid
from typing import Any, Callable, Iterable

import numpy as np
from django.conf import settings
from django.db import close_old_connections

from apps.vision import engine
from apps.vision.images import store as image_store
from apps.vision.models import Flow
from apps.vision.runner import runner

log = logging.getLogger(__name__)

WARMUP_FLOW_ID = -2
WARMUP_TRIGGER = "warmup"
WARMUP_MODES = ("off", "commissioned", "all")

WarmupRow = dict[str, Any]
ProgressCallback = Callable[[WarmupRow], None]


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


def parse_flow_ids(value: str | Iterable[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    else:
        items = [str(part).strip() for part in value]
    out: list[int] = []
    for item in items:
        if not item:
            continue
        out.append(int(item))
    return out


def configured_flow_ids() -> list[int]:
    return parse_flow_ids(str(_cfg("WARMUP_FLOWS", "") or ""))


def flow_ids_for_mode(mode: str) -> list[int]:
    """依指定模式取回流程 id, 手動指令用此函式略過 WARMUP=off."""
    mode = (mode or "off").strip().lower()
    if mode not in WARMUP_MODES:
        mode = "off"
    if mode == "off":
        return []
    qs = Flow.objects.filter(is_enabled=True)
    if mode == "commissioned":
        qs = qs.filter(commissioned=True)
    return list(qs.order_by("id").values_list("id", flat=True))


def default_flow_ids() -> list[int]:
    limited = configured_flow_ids()
    if limited:
        return limited
    return flow_ids_for_mode(str(_cfg("WARMUP", "off") or "off"))


def warm_flows(
    flow_ids: Iterable[int] | str | None = None,
    *,
    timeout_s: float | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """暖機指定流程並回傳每條流程的結果.

    `flow_ids=None` 時依設定選擇流程: `VISION_WARMUP_FLOWS` 非空則使用該清單,
    否則依 `VISION_WARMUP` 的 `off`, `commissioned`, `all` 規則. 每條流程先
    `runner.compiled_for()` 編譯一次, 再視取像策略決定是否直跑.
    """
    started = time.perf_counter()
    timeout = float(timeout_s if timeout_s is not None else _cfg("WARMUP_TIMEOUT_S", 30))
    ids = parse_flow_ids(flow_ids) if flow_ids is not None else default_flow_ids()
    rows: list[WarmupRow] = []
    for flow_id in ids:
        try:
            flow = Flow.objects.filter(pk=int(flow_id)).first()
            if flow is None:
                row = _row(int(flow_id), "", "skipped", "Flow not found", 0.0)
            else:
                row = _warm_one(flow, timeout)
        except Exception as exc:  # noqa: BLE001 - 暖機不得讓呼叫端或伺服器啟動失敗
            log.exception("暖機流程 %s 失敗", flow_id)
            row = _row(int(flow_id), "", "failed", f"{exc.__class__.__name__}: {exc}", 0.0)
        rows.append(row)
        if on_progress is not None:
            try:
                on_progress(dict(row))
            except Exception:  # noqa: BLE001
                log.exception("暖機進度回呼失敗")
    summary = {status: sum(1 for row in rows if row["status"] == status) for status in ("warmed", "skipped", "failed")}
    return {"items": rows, "summary": summary, "duration_ms": round((time.perf_counter() - started) * 1000, 3)}


def start_background(*, port: int, timeout_s: float | None = None, health_timeout_s: float = 30.0) -> threading.Thread:
    """啟動背景暖機執行緒; 執行緒會先等本機 /healthz 可回應."""
    thread = threading.Thread(
        target=_background_worker,
        kwargs={"port": int(port), "timeout_s": timeout_s, "health_timeout_s": float(health_timeout_s)},
        name="vision-warmup",
        daemon=True,
    )
    thread.start()
    return thread


def _warm_one(flow: Flow, timeout_s: float) -> WarmupRow:
    t0 = time.perf_counter()
    run_id = f"warm{uuid.uuid4().hex[:12]}"
    compiled = runner.compiled_for(flow)
    source_nodes = _source_nodes(compiled)
    input_image: np.ndarray | None = None
    if source_nodes:
        forced = [node_id for node_id, mode in source_nodes if mode == "source"]
        if forced:
            return _row(flow.id, flow.name, "skipped", f"image_source {', '.join(forced)} is set to source mode", t0)
        input_image = _recent_source_image(flow.id, [node_id for node_id, _mode in source_nodes])
        if input_image is None:
            return _row(flow.id, flow.name, "skipped", "No recent source image is available; live capture is not triggered during warmup", t0)
    report = engine.execute(
        compiled,
        flow_id=WARMUP_FLOW_ID,
        flow_version=flow.version,
        trigger=WARMUP_TRIGGER,
        grab=_no_capture_grab,
        asset_path=runner._asset_path,  # noqa: SLF001 - 與批次直跑路徑使用同一個快取查詢
        preview=False,
        input_image=input_image,
        initial_context={"_sandbox": True},
        run_id=run_id,
        deadline=time.perf_counter() + timeout_s,
        flow_timeout_s=getattr(flow, "timeout_s", 0),
        stop_on_ng=bool(getattr(flow, "stop_on_ng", False)),
    )
    image_store.drop_run(report.id)
    if report.status == "failed":
        return _row(flow.id, flow.name, "failed", report.error or _first_error(report), t0)
    return _row(flow.id, flow.name, "warmed", f"engine status {report.status}", t0)


def _row(flow_id: int, name: str, status: str, reason: str, started: float) -> WarmupRow:
    duration = 0.0 if started <= 0 else (time.perf_counter() - started) * 1000
    return {"flow_id": int(flow_id), "name": name, "status": status, "reason": reason, "duration_ms": round(duration, 3)}


def _source_nodes(compiled) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for node_id, cn in compiled.nodes.items():
        if cn.type != "image_source" or cn.node.get("enabled") is False:
            continue
        params = cn.node.get("params") or {}
        out.append((node_id, str(params.get("mode") or "auto")))
    return out


def _recent_source_image(flow_id: int, node_ids: list[str]) -> np.ndarray | None:
    rt = runner.runtime(flow_id)
    with runner._lock:  # noqa: SLF001 - recent run cache has no public iterator
        recent = list(rt.recent)
    for report in reversed(recent):
        for node_id in node_ids:
            ref = ((report.nodes.get(node_id) or engine.NodeReport()).outputs.get("image") or {}).get("ref")
            if not ref:
                continue
            image = image_store.get(str(ref))
            if isinstance(image, np.ndarray):
                return np.ascontiguousarray(image.copy())
    return None


def _first_error(report: engine.RunReport) -> str:
    for node in report.nodes.values():
        if node.status == "error" and node.message:
            return node.message
    return "Engine reported failed"


def _no_capture_grab(source_id: str) -> np.ndarray | None:
    log.warning("暖機略過實際取像: source_id=%s", source_id)
    return None


def _background_worker(*, port: int, timeout_s: float | None, health_timeout_s: float) -> None:
    try:
        from apps.accounts.models import EngineLock

        if EngineLock.current().locked:
            log.info("引擎鎖定中, 略過啟動暖機")
            return
        if not _wait_healthz(port, health_timeout_s):
            log.warning("等待 /healthz 逾時, 略過啟動暖機")
            return
        if EngineLock.current().locked:
            log.info("引擎鎖定中, 略過啟動暖機")
            return

        def progress(row: WarmupRow) -> None:
            log.info(
                "暖機流程 %s (%s): %s, %.0f ms%s",
                row["flow_id"],
                row["name"] or "-",
                row["status"],
                row["duration_ms"],
                f", {row['reason']}" if row.get("reason") else "",
            )

        result = warm_flows(timeout_s=timeout_s, on_progress=progress)
        summary = result["summary"]
        log.info(
            "啟動暖機完成: warmed=%s, skipped=%s, failed=%s, total=%s, %.0f ms",
            summary.get("warmed", 0),
            summary.get("skipped", 0),
            summary.get("failed", 0),
            len(result["items"]),
            result["duration_ms"],
        )
    except Exception:  # noqa: BLE001 - 暖機不得中止伺服器
        log.exception("啟動暖機失敗")
    finally:
        close_old_connections()


def _wait_healthz(port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + max(0.1, timeout_s)
    url = f"http://127.0.0.1:{int(port)}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:  # noqa: S310 - 本機健康檢查
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(data, dict) and data.get("status") == "ok":
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False
