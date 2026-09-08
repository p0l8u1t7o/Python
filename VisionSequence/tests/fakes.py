"""測試用的假物件。

`MemoryWriter`：只把寫入記在記憶體的通訊連線，給 write_modbus 工具、Runner 預先載入與連線 API
的測試用。以前產品裡有一個「模擬數位 I/O」連線種類做同樣的事，但它對使用者沒有實質功能，
所以拿掉了；測試需要的「假設備」放這裡就好。
"""

from __future__ import annotations

import time
from typing import Any

from apps.comm import writers
from apps.comm.writers import CommError, Writer

MEMORY_KIND = "memory_sim"


class MemoryWriter(Writer):
    """config.channels 有列時，寫到未宣告的通道算失敗（用來測降級）。"""

    kind = MEMORY_KIND
    label = "In-memory (tests)"
    fields = ["channels"]
    section = "plugins"
    texts = True  # 事件回報與心跳的測試要有個「送得出文字」的假設備

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        channels = config.get("channels") or []
        if isinstance(channels, int):
            channels = [f"DO{i}" for i in range(channels)]
        self.channels = [str(c) for c in channels]
        self.state: dict[str, Any] = {c: 0 for c in self.channels}
        self.history: list[dict[str, Any]] = []
        self.lines: list[str] = []

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.channels:
            unknown = [a for a in values if a not in self.channels]
            if unknown:
                raise CommError(f"Undeclared channels: {', '.join(unknown)}")
        self.state.update(values)
        self.history.append({"at": time.time(), "values": dict(values)})
        return {"written": len(values), "values": dict(values)}

    def _read(self, addresses: list[str]) -> dict[str, Any]:
        return {a: self.state.get(a) for a in addresses}

    def _send_text(self, text: str) -> dict[str, Any]:
        self.lines.append(text)
        return {"sent": len(text)}

    def info(self) -> dict[str, Any]:
        return {**super().info(), "channels": self.channels, "state": dict(self.state)}


def register_memory_kind() -> None:
    """讓 API 測試能用 kind="memory_sim" 建連線（已註冊就略過）。"""
    writers.register_kind(MemoryWriter)
