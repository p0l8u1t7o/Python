"""SSE：行程內事件匯流排 → 瀏覽器。

引擎與 API 在同一行程，所以這裡是真推播（Condition 喚醒），不查資料庫。
每條串流 55 秒自行關閉、client 帶 ?since= 重連補齊漏掉的事件。

注意：在 ASGI（uvicorn）下 Django 對 StreamingHttpResponse 的**同步** generator 會
`sync_to_async(list)` 整段收完才送出，等於沒有串流（瀏覽器 55 秒後才收到全部、期間顯示離線）。
所以 ASGI 請求用 async generator，`bus.wait` 丟到執行緒等待；WSGI／測試 client 走同步版本。

每條活著的串流都占一條等待執行緒：用專用的執行緒池（VISION_SSE_MAX_STREAMS，預設 64），不跟事件迴圈的預設池
（min(32, cpu+4)，4 核站台只有 8 條）搶；超過上限回 503＋Retry-After 讓瀏覽器稍後重試，而不是無聲排隊讓全站看起來離線。
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

import orjson
from django.conf import settings
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse

from apps.vision.engine import NODE_REPORT_DEFAULTS
from apps.vision.runner import bus, runner

MAX_STREAM_SECONDS = 55
HEARTBEAT_SECONDS = 15
WAIT_SECONDS = 1.0

_pool_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None
_active = 0


def max_streams() -> int:
    return max(1, int(settings.VISION.get("SSE_MAX_STREAMS") or 64))


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=max_streams(), thread_name_prefix="vs-sse")
        return _pool


def _acquire_slot() -> bool:
    global _active
    with _pool_lock:
        if _active >= max_streams():
            return False
        _active += 1
        return True


def _release_slot() -> None:
    global _active
    with _pool_lock:
        _active = max(0, _active - 1)


def active_streams() -> int:
    with _pool_lock:
        return _active


def _sse(event: str, data) -> bytes:
    return b"event: " + event.encode() + b"\ndata: " + orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY) + b"\n\n"


def _authorized(request) -> bool:
    from apps.accounts.security import authenticate

    return authenticate(request) is not None


class _Session:
    """一條串流的狀態與純函式片段，讓同步／非同步 generator 共用。"""

    def __init__(self, since: int, flow_id: int | None, include_outputs: bool, max_seconds: float) -> None:
        # 伺服器重啟後 seq 從 0 起算；客戶端帶著舊的 since 重連會永遠收不到事件，超過目前 seq 就夾回來
        self.since = min(since, bus.seq)
        self.flow_id = flow_id
        self.include_outputs = include_outputs
        self.deadline = time.monotonic() + max_seconds
        self.last_beat = time.monotonic()
        self._released = False

    def release(self) -> None:
        """把占的串流名額還回去（generator 結束、客戶端斷線、或回應根本沒開始迭代都會走到；只做一次）。"""
        if not self._released:
            self._released = True
            _release_slot()

    def head(self) -> Iterator[bytes]:
        yield b"retry: 1500\n\n"
        yield _sse("hello", {"seq": self.since, "flow_id": self.flow_id})
        if self.flow_id is not None:
            rt = runner.runtime(self.flow_id)
            yield _sse("stats", {"flow_id": self.flow_id, "stats": rt.stats.to_dict(), "continuous": runner.is_continuous(self.flow_id)})

    def alive(self) -> bool:
        return time.monotonic() < self.deadline

    def wait_timeout(self) -> float:
        return min(WAIT_SECONDS, max(0.01, self.deadline - time.monotonic()))

    def frames(self, events: list[dict]) -> Iterator[bytes]:
        for event in events:
            if self.flow_id is not None and "flow_id" in event and event.get("flow_id") != self.flow_id:
                continue
            payload = dict(event)
            if not self.include_outputs and "run" in payload:
                # 瘦身：丟掉輸出／標記／detail，但形狀維持完整（前端 NodeReport 的每個鍵都在），
                # 並標 nodes_trimmed 讓前端別拿它蓋掉同一個 run 的完整版。
                run = dict(payload["run"])
                run["nodes"] = {
                    k: {**NODE_REPORT_DEFAULTS, **{kk: vv for kk, vv in v.items() if kk in ("status", "duration_ms", "message", "message_code", "message_args", "branch", "overlay_on")}}
                    for k, v in run["nodes"].items()
                }
                run["nodes_trimmed"] = True
                payload["run"] = run
            payload["seq"] = self.since
            yield _sse(str(event.get("type", "event")), payload)
            self.last_beat = time.monotonic()
        if time.monotonic() - self.last_beat > HEARTBEAT_SECONDS:
            # 具名事件而不是 `: ping` 註解：EventSource 不會把註解交給 JS，前端要靠它做斷線看門狗
            # （經 Vite proxy 或某些反向代理時，後端死掉客戶端連線可能不會被關，只能靠沒心跳來判斷）。
            yield _sse("ping", {"seq": self.since})
            self.last_beat = time.monotonic()

    def tail(self) -> bytes:
        return _sse("bye", {"seq": self.since})


def _generate_sync(s: _Session):
    try:
        yield from s.head()
        while s.alive():
            s.since, events = bus.wait(s.since, s.wait_timeout())
            yield from s.frames(events)
        yield s.tail()
    finally:
        s.release()


async def _generate_async(s: _Session):
    loop = asyncio.get_running_loop()
    try:
        for chunk in s.head():
            yield chunk
        while s.alive():
            s.since, events = await loop.run_in_executor(_executor(), bus.wait, s.since, s.wait_timeout())
            for chunk in s.frames(events):
                yield chunk
        yield s.tail()
    finally:
        s.release()


def _stream(request, *, flow_id: int | None):
    if not _authorized(request):
        return HttpResponse(status=401)
    try:
        since = int(request.GET.get("since") or 0)
    except ValueError:
        since = 0
    # 沒帶 since 表示「從現在開始」，不要重播歷史。
    if not request.GET.get("since"):
        since = bus.seq
    include_outputs = request.GET.get("outputs", "1") != "0"
    try:
        max_seconds = min(MAX_STREAM_SECONDS, float(request.GET.get("max_seconds") or MAX_STREAM_SECONDS))
    except ValueError:
        max_seconds = MAX_STREAM_SECONDS

    if not _acquire_slot():
        response = JsonResponse({"error": {"code": "too_many_streams", "message": f"Too many live event streams on this station (limit {max_streams()}); try again shortly"}}, status=503)
        response["Retry-After"] = "5"
        return response
    session = _Session(since, flow_id, include_outputs, max_seconds)
    # ASGIRequest 有 scope；WSGI（runserver、測試 client）沒有。
    is_asgi = hasattr(request, "scope")
    response = StreamingHttpResponse(_generate_async(session) if is_asgi else _generate_sync(session), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    # 回應被關閉時（客戶端斷線、或還沒開始迭代就結束）也要還名額；generator 的 finally 再叫一次也沒關係
    response._resource_closers.append(session.release)  # noqa: SLF001
    return response


def flow_stream(request, flow_id: int):
    return _stream(request, flow_id=int(flow_id))


def events_stream(request):
    return _stream(request, flow_id=None)
