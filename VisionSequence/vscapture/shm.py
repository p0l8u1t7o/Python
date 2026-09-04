"""共享記憶體環（擷取端寫入端）：同機時把像素直接寫進槽，FRAME(slot) 當事件；伺服端 SLOT_FREE 後才可重用。

規則：只寫 FREE 的槽；K ≥ 3 時允許覆寫「最舊、seq 落後 ≥ 2K 且被持有超過 1 秒」的孤兒槽（伺服端顯然沒回收）；
release 只在 seq 相符時生效（舊 ring 的遲到 ack 忽略）。
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from multiprocessing import shared_memory
from typing import Any

import numpy as np

from vscapture import protocol as P


class ShmRing:
    def __init__(self, name: str, slots: int, slot_bytes: int, canary: int, shm: shared_memory.SharedMemory) -> None:
        self.name, self.slots, self.slot_bytes, self.canary, self.shm = name, slots, slot_bytes, canary, shm
        self._lock = threading.Condition()
        self._owner_seq: dict[int, int] = {}  # slot → seq（伺服端持有中）
        self._owner_time: dict[int, float] = {}
        self._next = 0
        self.dropped = 0
        self.overwritten = 0
        self._closed = False

    @classmethod
    def create(cls, client_name: str, cid: str, slots: int, slot_bytes: int) -> ShmRing:
        slots = max(2, int(slots))
        slot_bytes = P.align_slot_bytes(slot_bytes)
        name = f"vs_cap_{client_name}_{os.getpid()}_{cid}_{secrets.token_hex(2)}"[:60]
        canary = secrets.randbits(63)
        shm = shared_memory.SharedMemory(name=name, create=True, size=P.segment_size(slots, slot_bytes))
        shm.buf[: P.SEG_HEADER_BYTES] = P.pack_seg_header(canary, slots, slot_bytes)
        return cls(shm.name, slots, slot_bytes, canary, shm)

    def offer(self) -> dict[str, Any]:
        return {"name": self.name, "slots": self.slots, "slot_bytes": self.slot_bytes, "canary": self.canary}

    def _pick_locked(self, seq: int) -> int | None:
        for i in range(self.slots):
            cand = (self._next + i) % self.slots
            if cand not in self._owner_seq:
                self._next = (cand + 1) % self.slots
                return cand
        if self.slots >= 3:
            oldest = min(self._owner_seq, key=self._owner_seq.get)
            if seq - self._owner_seq[oldest] >= 2 * self.slots and time.perf_counter() - self._owner_time.get(oldest, 0.0) >= 1.0:
                self.overwritten += 1
                self._next = (oldest + 1) % self.slots
                return oldest
        return None

    def try_write(self, seq: int, image: np.ndarray) -> int | None:
        """把影像寫進一個可用槽並標記為伺服端持有；沒有槽回 None。"""
        with self._lock:
            if self._closed:
                return None
            slot = self._pick_locked(seq)
            if slot is None:
                self.dropped += 1
                return None
            self._owner_seq[slot] = seq
            self._owner_time[slot] = time.perf_counter()
        self._copy(slot, image)
        return slot

    def wait_write(self, seq: int, image: np.ndarray, timeout: float) -> int | None:
        with self._lock:
            if not self._lock.wait_for(lambda: self._closed or len(self._owner_seq) < self.slots, timeout):
                return None
            if self._closed:
                return None
            slot = self._pick_locked(seq)
            if slot is None:
                return None
            self._owner_seq[slot] = seq
            self._owner_time[slot] = time.perf_counter()
        self._copy(slot, image)
        return slot

    def _copy(self, slot: int, image: np.ndarray) -> None:
        n = image.nbytes
        if n > self.slot_bytes:
            raise ValueError("影像超過共享記憶體槽大小")
        off = P.slot_offset(slot, self.slot_bytes)
        view = np.ndarray(image.shape, image.dtype, buffer=self.shm.buf, offset=off)
        np.copyto(view, image)
        del view

    def release(self, slot: int, seq: int) -> bool:
        with self._lock:
            if self._owner_seq.get(slot) != seq:
                return False
            del self._owner_seq[slot]
            self._owner_time.pop(slot, None)
            self._lock.notify_all()
            return True

    def release_all(self) -> None:
        with self._lock:
            self._owner_seq.clear()
            self._lock.notify_all()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"name": self.name, "slots": self.slots, "in_use": len(self._owner_seq), "dropped": self.dropped, "overwritten": self.overwritten}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._lock.notify_all()
        try:
            self.shm.close()
        except (BufferError, OSError):
            pass
        try:
            self.shm.unlink()
        except (FileNotFoundError, OSError):
            pass
