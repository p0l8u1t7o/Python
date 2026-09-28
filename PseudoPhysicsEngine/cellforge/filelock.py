"""跨程序檔案鎖：由作業系統持有，程序結束（含崩潰）時自動釋放。"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class LockTimeoutError(TimeoutError):
    pass


class HeldLock:
    """一個鎖檔的持有權；同一程序內的不同 HeldLock 也互斥。"""

    def __init__(self, path: Path):
        self.path = path
        self._handle: BinaryIO | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def try_acquire(self) -> bool:
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if _lock(handle):
            self._handle = handle
            return True
        handle.close()
        return False

    def acquire(self, timeout_s: float, poll_s: float = 0.05) -> None:
        deadline = time.monotonic() + timeout_s
        while not self.try_acquire():
            if time.monotonic() >= deadline:
                raise LockTimeoutError(f"等待鎖定逾時（{timeout_s:g} 秒）：{self.path}")
            time.sleep(poll_s)

    def release(self, *, remove: bool = False) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None
        if remove:
            self.path.unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path, timeout_s: float = 120.0) -> Iterator[None]:
    lock = HeldLock(path)
    lock.acquire(timeout_s)
    try:
        yield
    finally:
        lock.release()


if os.name == "nt":
    import msvcrt

    def _lock(handle: BinaryIO) -> bool:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle: BinaryIO) -> bool:
        # flock 以開啟的檔案描述為單位，同一程序另開的 handle 也會互斥。
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
