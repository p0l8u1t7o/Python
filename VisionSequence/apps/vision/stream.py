"""SSE：行程內事件匯流排 → 瀏覽器。

引擎與 API 在同一行程，所以這裡是真推播（Condition 喚醒），不查資料庫。
每條串流 55 秒自行關閉、client 帶 ?since= 重連補齊漏掉的事件。

注意：在 ASGI（uvicorn）下 Django 對 StreamingHttpResponse 的**同步** generator 會
`sync_to_async(list)` 整段收完才送出，等於沒有串流（瀏覽器 55 秒後才收到全部、期間顯示離線）。
所以 ASGI 請求用 async generator，`bus.wait` 丟到執行緒等待；WSGI／測試 client 走同步版本。
"""

from __future__ import annotations

import asyncio
import time
from typing import Iterator

import orjson
from django.http import HttpResponse, StreamingHttpResponse

from apps.vision.runner import bus, runner

MAX_STREAM_SECONDS = 55
HEARTBEAT_SECONDS = 15
WAIT_SECONDS = 1.0


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
                run = dict(payload["run"])
                run["nodes"] = {k: {kk: vv for kk, vv in v.items() if kk in ("status", "duration_ms", "message", "branch")} for k, v in run["nodes"].items()}
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
    yield from s.head()
    while s.alive():
        s.since, events = bus.wait(s.since, s.wait_timeout())
        yield from s.frames(events)
    yield s.tail()


async def _generate_async(s: _Session):
    for chunk in s.head():
        yield chunk
    while s.alive():
        s.since, events = await asyncio.to_thread(bus.wait, s.since, s.wait_timeout())
        for chunk in s.frames(events):
            yield chunk
    yield s.tail()


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

    session = _Session(since, flow_id, include_outputs, max_seconds)
    # ASGIRequest 有 scope；WSGI（runserver、測試 client）沒有。
    is_asgi = hasattr(request, "scope")
    response = StreamingHttpResponse(_generate_async(session) if is_asgi else _generate_sync(session), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def flow_stream(request, flow_id: int):
    return _stream(request, flow_id=int(flow_id))


def events_stream(request):
    return _stream(request, flow_id=None)
