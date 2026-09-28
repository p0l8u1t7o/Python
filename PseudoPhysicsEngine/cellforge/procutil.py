"""有期限、可取消的子程序執行；取消、逾時或結束時連同所有後代程序一起收掉。

Claude Code 會再啟動 bash、``cell build`` 等子程序。只結束最上層程序時，Windows 上的後代會
繼續執行，取消後仍可能發布版本；後代持有輸出管線時，asyncio 的 ``Process.wait()`` 也會一直等到
它們結束。因此 Windows 以 Job Object（KILL_ON_JOB_CLOSE）、POSIX 以獨立 process group 綁住
整個程序家族，並以 returncode 判斷主程序結束，不依賴管線關閉。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

LineSink = Callable[[str], None]
STREAM_LINE_LIMIT = 16 * 1024 * 1024
# 主程序結束後，最多再等這麼久讀完管線中剩餘的輸出。
PIPE_DRAIN_S = 5.0


class ProcessTimeoutError(TimeoutError):
    pass


async def run_streaming(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout_s: float,
    on_stdout: LineSink,
    on_stderr: LineSink,
) -> int:
    """Run ``argv`` streaming decoded lines; return the exit code or raise on timeout."""

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # stream-json 單一事件可能超過 asyncio 預設的 64 KiB 行長上限。
        limit=STREAM_LINE_LIMIT,
        **_spawn_options(),
    )
    family = ProcessFamily(process)

    async def pump(stream: asyncio.StreamReader | None, sink: LineSink) -> None:
        assert stream is not None
        while line := await stream.readline():
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                sink(text)

    readers = [
        asyncio.create_task(pump(process.stdout, on_stdout)),
        asyncio.create_task(pump(process.stderr, on_stderr)),
    ]
    try:
        if not await _wait_exit(process, max(timeout_s, 0.001)):
            await family.terminate()
            raise ProcessTimeoutError(f"子程序超過 {timeout_s:.0f} 秒，已連同後代程序一併終止")
        await asyncio.wait(readers, timeout=PIPE_DRAIN_S)
    except asyncio.CancelledError:
        await family.terminate()
        raise
    finally:
        for reader in readers:
            if not reader.done():
                reader.cancel()
        # 主程序之後仍殘留的後代（例如背景執行的指令）不得比這次工作活得更久。
        family.close()
    assert process.returncode is not None
    return process.returncode


class ProcessFamily:
    """A spawned process together with every descendant it starts."""

    def __init__(self, process: asyncio.subprocess.Process):
        self.process = process
        self._job = _WindowsJob.attach(process.pid) if os.name == "nt" else None

    async def terminate(self, grace_s: float = 5.0) -> None:
        if os.name == "nt":
            if self._job is not None:
                self._job.terminate()
            else:
                await _taskkill_tree(self.process.pid)
            if not await _wait_exit(self.process, grace_s):
                _kill_quietly(self.process)
                await _wait_exit(self.process, grace_s)
            return
        self._signal_group(signal.SIGTERM)
        if not await _wait_exit(self.process, grace_s):
            self._signal_group(signal.SIGKILL)
            _kill_quietly(self.process)
            await _wait_exit(self.process, grace_s)

    def close(self) -> None:
        if self._job is not None:
            self._job.close()
            self._job = None
        elif os.name != "nt":
            self._signal_group(signal.SIGKILL)

    def _signal_group(self, signum: int) -> None:
        try:
            os.killpg(self.process.pid, signum)
        except (ProcessLookupError, PermissionError):
            pass


async def _wait_exit(process: asyncio.subprocess.Process, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while process.returncode is None:
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


def _kill_quietly(process: asyncio.subprocess.Process) -> None:
    try:
        process.kill()
    except ProcessLookupError:
        pass


async def _taskkill_tree(pid: int) -> None:
    killer = await asyncio.create_subprocess_exec(
        "taskkill",
        "/PID",
        str(pid),
        "/T",
        "/F",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await killer.wait()


def _spawn_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # 明確宣告簽章，避免 64 位元 HANDLE 被 ctypes 預設的 int 截斷。
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _WindowsJob:
        """Job Object：關閉或終止時，裡面所有程序（含已失去父程序的後代）一起結束。"""

        def __init__(self, handle: int):
            self.handle = handle

        @classmethod
        def attach(cls, pid: int) -> _WindowsJob | None:
            handle = _kernel32.CreateJobObjectW(None, None)
            if not handle:
                return None
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            assigned = bool(process) and bool(
                _kernel32.SetInformationJobObject(
                    handle,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                )
            )
            assigned = assigned and bool(_kernel32.AssignProcessToJobObject(handle, process))
            if process:
                _kernel32.CloseHandle(process)
            if not assigned:
                # 無法建立 job 時退回 taskkill /T（只涵蓋仍在父子鏈上的程序）。
                _kernel32.CloseHandle(handle)
                return None
            return cls(handle)

        def terminate(self) -> None:
            _kernel32.TerminateJobObject(self.handle, 1)

        def close(self) -> None:
            _kernel32.CloseHandle(self.handle)

else:

    class _WindowsJob:  # pragma: no cover - 非 Windows 平台不使用
        @classmethod
        def attach(cls, pid: int) -> None:
            return None
