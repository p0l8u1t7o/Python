"""擷取端自動更新：伺服端建置了新版就從擷取連線把安裝檔拉下來、驗證、解壓，再由新版接手覆寫並重啟。

流程：
1. 伺服端在 WELCOME 帶 `update`，之後每次心跳發現 manifest 版本變了就再推一次 UPDATE。
2. 擷取端 `download()` 以 UPDATE_PULL／UPDATE_DATA 逐塊拉（走已驗證的同一條連線，不必另開埠或再給金鑰），
   存到 `%APPDATA%/VisionSequenceCapture/updates/`，比對 sha256。
3. `stage()` 解壓到 `updates/staging-<版本>/`。
4. `apply()` 用**新版的**主控台執行檔接手：等舊行程結束 → 覆寫安裝資料夾 → 重新啟動。
   （更新程式必須跑在新版的資料夾裡，否則會覆寫到自己。）
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vscapture.config import app_dir

log = logging.getLogger(__name__)
STAGING_PREFIX = "staging-"


@dataclass(frozen=True)
class UpdateInfo:
    """伺服端手上的安裝檔資訊（`available` 表示比擷取端目前的版本新）。"""

    available: bool = False
    version: str = ""
    filename: str = ""
    size: int = 0
    sha256: str = ""
    built_at: str | None = None
    chunk: int = 1 << 20

    @classmethod
    def from_dict(cls, body: dict[str, Any] | None) -> UpdateInfo:
        d = body or {}
        return cls(
            available=bool(d.get("available")), version=str(d.get("version") or ""), filename=str(d.get("filename") or ""),
            size=int(d.get("size") or 0), sha256=str(d.get("sha256") or ""), built_at=d.get("built_at"), chunk=max(1 << 16, int(d.get("chunk") or 1 << 20)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "version": self.version, "filename": self.filename, "size": self.size, "sha256": self.sha256, "built_at": self.built_at}


def updates_dir() -> Path:
    return app_dir() / "updates"


def is_frozen() -> bool:
    """打包後的執行檔（PyInstaller）才能就地更新；原始碼執行只提示不動手。"""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """安裝資料夾（打包版＝執行檔所在；原始碼執行＝專案根目錄）。"""
    return Path(sys.executable).parent if is_frozen() else Path(__file__).resolve().parent.parent


def console_exe(folder: Path) -> Path:
    return folder / "VisionSequenceCapture-console.exe"


def gui_exe(folder: Path) -> Path:
    return folder / "VisionSequenceCapture.exe"


class UpdateError(RuntimeError):
    pass


def download(pull: Callable[[int, int], tuple[bytes, bool]], info: UpdateInfo, *, dest: Path | None = None,
             on_progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None) -> Path:
    """逐塊拉安裝檔並驗證 sha256；`pull(offset, length)` 回 (資料, 是否到檔尾)。回下載好的 zip 路徑。"""
    folder = dest or updates_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (info.filename or f"VisionSequenceCapture-{info.version}-win64.zip")
    part = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    offset = 0
    with part.open("wb") as fh:
        while True:
            if cancel is not None and cancel.is_set():
                raise UpdateError("已取消")
            chunk, eof = pull(offset, info.chunk)
            if not chunk and not eof:
                raise UpdateError("伺服端沒有回傳資料")
            fh.write(chunk)
            digest.update(chunk)
            offset += len(chunk)
            if on_progress is not None:
                on_progress(offset, info.size or offset)
            if eof:
                break
    if info.size and offset != info.size:
        part.unlink(missing_ok=True)
        raise UpdateError(f"下載長度不符（{offset}／{info.size}）")
    if info.sha256 and digest.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("下載內容的 SHA-256 不符，已丟棄")
    target.unlink(missing_ok=True)
    os.replace(part, target)
    log.info("已下載擷取端 %s（%d 位元組）", info.version, offset)
    return target


def stage(zip_path: Path, version: str, *, dest: Path | None = None) -> Path:
    """解壓到 updates/staging-<版本>/；回實際含執行檔的資料夾（zip 頂層是 VisionSequenceCapture-<版本>/）。"""
    folder = (dest or updates_dir()) / f"{STAGING_PREFIX}{version}"
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():  # 防 zip slip
            if name.startswith("/") or ".." in Path(name).parts:
                raise UpdateError(f"安裝檔內有可疑路徑：{name}")
        zf.extractall(folder)
    inner = [p for p in folder.iterdir() if p.is_dir()]
    root = inner[0] if len(inner) == 1 and not (folder / "VisionSequenceCapture.exe").exists() else folder
    if not gui_exe(root).is_file() and not console_exe(root).is_file():
        raise UpdateError("安裝檔內找不到執行檔")
    return root


def apply(staging: Path, target: Path | None = None, *, restart: bool = True, pid: int | None = None) -> None:
    """交棒給新版：用新版的主控台執行檔等舊行程結束、覆寫安裝資料夾、重新啟動。呼叫後應立即結束本行程。"""
    dest = target or install_dir()
    updater = console_exe(staging)
    if not updater.is_file():
        raise UpdateError("新版沒有主控台執行檔，無法自動更新")
    args = [str(updater), "--apply-update", str(dest), "--wait-pid", str(pid or os.getpid())]
    if restart:
        args.append("--restart")
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, cwd=str(staging), close_fds=True, creationflags=flags)
    log.info("已交給更新程式：%s → %s", staging, dest)


def run_updater(target: Path, wait_pid: int, *, restart: bool, timeout: float = 60.0) -> int:
    """更新程式本體（新版執行檔以 --apply-update 啟動）：等舊行程結束 → 覆寫 → 重啟。"""
    source = install_dir()
    if source.resolve() == target.resolve():
        print("更新來源與目標相同，取消")
        return 2
    _wait_pid(wait_pid, timeout)
    for attempt in range(30):  # 檔案可能還被佔用，重試到放開為止
        try:
            _copy_tree(source, target)
            break
        except (OSError, PermissionError) as exc:
            if attempt == 29:
                print(f"覆寫失敗：{exc}")
                return 1
            time.sleep(1.0)
    print(f"已更新 {target}")
    if restart:
        exe = gui_exe(target) if gui_exe(target).is_file() else console_exe(target)
        subprocess.Popen([str(exe)], cwd=str(target), close_fds=True)
    return 0


def _wait_pid(pid: int, timeout: float) -> None:
    if pid <= 0:
        return
    end = time.time() + timeout
    while time.time() < end:
        if not _alive(pid):
            time.sleep(0.5)  # 讓作業系統放開檔案把手
            return
        time.sleep(0.2)


def _alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return str(pid) in out


def _copy_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        dst = target / rel
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)


def cleanup(keep_version: str = "") -> None:
    """清掉舊的暫存與下載（更新完成後、或下次啟動時呼叫）。"""
    folder = updates_dir()
    if not folder.is_dir():
        return
    for item in folder.iterdir():
        if item.name == f"{STAGING_PREFIX}{keep_version}":
            continue
        try:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        except OSError:
            pass
