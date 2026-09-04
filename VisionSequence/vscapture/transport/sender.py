"""送出佇列與傳送執行緒：控制訊息優先；GRAB 回覆依序；串流影格同通道只留最新（背壓＝丟舊）。"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from typing import Callable

log = logging.getLogger(__name__)


class SendQueue:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._control: deque[bytes] = deque()
        self._replies: deque[bytes] = deque()
        self._stream: dict[str, bytes] = {}
        self._stream_order: deque[str] = deque()
        self.closed = False

    def put_control(self, data: bytes) -> None:
        with self._cond:
            self._control.append(data)
            self._cond.notify()

    def put_reply(self, data: bytes) -> None:
        with self._cond:
            self._replies.append(data)
            self._cond.notify()

    def put_stream(self, cid: str, data: bytes) -> bool:
        """同通道只留最新一張；回 True 表示取代了尚未送出的舊影格。"""
        with self._cond:
            replaced = cid in self._stream
            self._stream[cid] = data
            if not replaced:
                self._stream_order.append(cid)
            self._cond.notify()
            return replaced

    def get(self, timeout: float) -> bytes | None:
        with self._cond:
            if not self._cond.wait_for(lambda: self.closed or self._control or self._replies or self._stream, timeout):
                return None
            if self.closed:
                return None
            if self._control:
                return self._control.popleft()
            if self._replies:
                return self._replies.popleft()
            cid = self._stream_order.popleft()
            return self._stream.pop(cid)

    def clear(self) -> None:
        with self._cond:
            self._control.clear()
            self.clear_frames()

    def clear_frames(self) -> None:
        """丟掉尚未送出的影格（共享記憶體重新協商時，舊槽索引不能再送）。"""
        with self._cond:
            self._replies.clear()
            self._stream.clear()
            self._stream_order.clear()

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()


class SenderThread(threading.Thread):
    """把佇列的資料 sendall 出去；閒置超過 heartbeat_s 送一次 PING（由 on_idle 產生）。"""

    def __init__(self, sock: socket.socket, queue: SendQueue, *, heartbeat_s: float, on_idle: Callable[[], bytes | None], on_error: Callable[[Exception], None]) -> None:
        super().__init__(name="vsc-send", daemon=True)
        self.sock = sock
        self.queue = queue
        self.heartbeat_s = max(0.5, float(heartbeat_s))
        self.on_idle = on_idle
        self.on_error = on_error
        self.bytes_sent = 0
        self.frames_sent = 0
        self._last_send = time.perf_counter()

    def run(self) -> None:
        try:
            while not self.queue.closed:
                data = self.queue.get(self.heartbeat_s)
                if data is None:
                    if self.queue.closed:
                        break
                    if time.perf_counter() - self._last_send >= self.heartbeat_s:
                        ping = self.on_idle()
                        if ping:
                            self.sock.sendall(ping)
                            self._last_send = time.perf_counter()
                    continue
                self.sock.sendall(data)
                self.bytes_sent += len(data)
                self._last_send = time.perf_counter()
        except (OSError, ValueError) as exc:
            if not self.queue.closed:
                self.on_error(exc)
