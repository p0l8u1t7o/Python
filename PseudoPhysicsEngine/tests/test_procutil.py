"""取消與逾時必須連同子程序一起結束，否則被取消的建置仍可能在背景發布版本。"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from cellforge.procutil import ProcessTimeoutError, run_streaming

PARENT = """
import os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
child = subprocess.Popen([sys.executable, "-c",
    "import os, sys, time; from pathlib import Path; "
    "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(120)",
    str(root / "child.pid")])
(root / "parent.pid").write_text(str(os.getpid()))
print("ready", flush=True)
time.sleep(120)
"""


# venv 的 python.exe 是啟動器，會把真正的直譯器放進 Job Object，殺掉啟動器就連帶結束整個 job，
# 會讓「只殺父程序」也看似成功。直接用基底直譯器，才測得到真正的孤兒程序。
PYTHON = getattr(sys, "_base_executable", None) or sys.executable


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pids: list[int], timeout_s: float = 15) -> list[int]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _alive(pid)]
        if not alive:
            return []
        time.sleep(0.1)
    return [pid for pid in pids if _alive(pid)]


def _pids(root: Path) -> list[int]:
    return [int((root / name).read_text()) for name in ("parent.pid", "child.pid")]


async def _wait_for_pids(root: Path) -> None:
    for _ in range(600):
        if (root / "parent.pid").is_file() and (root / "child.pid").is_file():
            if (root / "child.pid").read_text():
                return
        await asyncio.sleep(0.05)
    raise AssertionError("測試子程序沒有啟動")


def _start(root: Path, timeout_s: float, lines: list[str]):
    script = root / "parent.py"
    script.write_text(PARENT, encoding="utf-8")
    return run_streaming(
        [PYTHON, str(script), str(root)],
        cwd=root,
        env=None,
        timeout_s=timeout_s,
        on_stdout=lines.append,
        on_stderr=lines.append,
    )


def test_cancel_terminates_the_whole_process_tree(tmp_path: Path):
    lines: list[str] = []

    async def scenario() -> None:
        task = asyncio.create_task(_start(tmp_path, 120, lines))
        await _wait_for_pids(tmp_path)
        assert all(_alive(pid) for pid in _pids(tmp_path))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert _wait_dead(_pids(tmp_path)) == []


def test_timeout_terminates_the_whole_process_tree(tmp_path: Path):
    lines: list[str] = []

    async def scenario() -> None:
        with pytest.raises(ProcessTimeoutError, match="子程序"):
            await _start(tmp_path, 8, lines)

    asyncio.run(scenario())
    assert "ready" in lines
    assert _wait_dead(_pids(tmp_path)) == []


# 父程序印出 ready 後立刻結束，留下仍在睡 120 秒、持有輸出管線的子程序。
ABANDONING_PARENT = PARENT.replace("time.sleep(120)\n", "", 1)


def test_descendants_left_behind_by_a_finished_process_are_terminated(tmp_path: Path):
    """主程序結束但背景後代還在（持有輸出管線）時，不可卡住，也不可讓後代繼續執行。"""
    lines: list[str] = []
    script = tmp_path / "parent.py"
    script.write_text(ABANDONING_PARENT, encoding="utf-8")
    assert "time.sleep(120)" in ABANDONING_PARENT  # 子程序仍會睡 120 秒

    async def scenario() -> int:
        return await run_streaming(
            [PYTHON, str(script), str(tmp_path)],
            cwd=tmp_path,
            env=None,
            timeout_s=60,
            on_stdout=lines.append,
            on_stderr=lines.append,
        )

    started = time.monotonic()
    assert asyncio.run(scenario()) == 0
    assert time.monotonic() - started < 40
    assert "ready" in lines
    assert _wait_dead(_pids(tmp_path)) == []


def test_exit_code_and_lines_are_returned(tmp_path: Path):
    lines: list[str] = []

    async def scenario() -> int:
        return await run_streaming(
            [
                sys.executable,
                "-c",
                "import sys; print('第一行'); print('錯誤', file=sys.stderr); sys.exit(3)",
            ],
            cwd=tmp_path,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout_s=60,
            on_stdout=lines.append,
            on_stderr=lines.append,
        )

    assert asyncio.run(scenario()) == 3
    assert sorted(lines) == sorted(["第一行", "錯誤"])
