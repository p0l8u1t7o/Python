"""使用者設定的檔案輸出佇列與保留清理。"""

from __future__ import annotations

import atexit
import csv
import logging
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.vision import archive

log = logging.getLogger(__name__)

QUEUE_LIMIT = max(1, int(getattr(settings, "VISION", {}).get("FILE_OUTPUT_QUEUE", 1000) or 1000))

_queue: queue.Queue[Any] = queue.Queue(maxsize=QUEUE_LIMIT)
#: 行程結束前最多等多久把佇列寫完（秒）。
EXIT_FLUSH_S = 5.0
_started = False
_lock = threading.Lock()
_dropped = 0
_written = 0
_drop_warned = False


@dataclass(frozen=True)
class TextJob:
    path: Path
    fmt: str
    row: list[str]
    header: list[str]
    write_header: bool
    rotate_bytes: int
    rotate_rows: int
    encoding: str


@dataclass(frozen=True)
class ImageJob:
    path: Path
    image: np.ndarray
    fmt: str
    quality: int


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


def root() -> Path:
    """回傳檔案輸出的專用根目錄。"""
    custom = str(_cfg("FILE_OUTPUT_DIR", "") or "")
    return Path(custom) if custom else Path(settings.DATA_DIR) / "file_outputs"


def resolve_dir(path: str) -> Path:
    """把使用者路徑限制在檔案輸出根目錄下。"""
    raw = str(path or "").strip().replace("\\", "/")
    win = PureWindowsPath(raw)
    if win.drive or win.root or Path(raw).is_absolute():
        raise ValueError("Output path must be relative to DATA_DIR/file_outputs")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("Output path must not contain '..'")
    return root().joinpath(*parts).resolve()


def safe_filename(name: str, fallback: str = "output") -> str:
    """沿用封存模組的檔名字元規則，保留一個可用檔名。"""
    stem = archive._safe(str(name or ""))  # noqa: SLF001 - 共用封存既有純函式規則
    return stem or fallback


def daily_dir(base: Path, when: float | None = None) -> Path:
    """沿用封存的 yyyyMMdd 按日目錄格式。"""
    return base / time.strftime("%Y%m%d", time.localtime(when or time.time()))


def text_path(base_dir: Path | str, filename: str, fmt: str, *, daily_folder: bool, when: float | None = None) -> Path:
    base_dir = Path(base_dir)
    folder = daily_dir(base_dir, when) if daily_folder else base_dir
    ext = "csv" if str(fmt).lower() == "csv" else "txt"
    return folder / f"{safe_filename(filename)}.{ext}"


def image_path(base_dir: Path | str, filename: str, fmt: str, *, daily_folder: bool, when: float | None = None) -> Path:
    base_dir = Path(base_dir)
    folder = daily_dir(base_dir, when) if daily_folder else base_dir
    ext = "jpg" if str(fmt).lower() in ("jpg", "jpeg") else str(fmt).lower()
    return folder / f"{safe_filename(filename, 'image')}.{ext}"


def submit(job: TextJob | ImageJob) -> bool:
    """把檔案寫入工作放入有界佇列；滿載時丟棄。"""
    global _drop_warned, _dropped
    ensure()
    try:
        _queue.put_nowait(job)
        return True
    except queue.Full:
        with _lock:
            _dropped += 1
            if not _drop_warned:
                _drop_warned = True
                log.warning("檔案輸出佇列已滿，後續檔案輸出將丟棄直到佇列恢復")
        return False


def ensure() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_worker, name="vision-fileout", daemon=True).start()
        # 行程結束前把還沒寫完的排空：品保靠這些 CSV，服務重啟不該吃掉最後幾列。
        # worker 是 daemon，atexit 在直譯器收掉 daemon 執行緒之前執行，還來得及寫完。
        atexit.register(_drain_on_exit)


def _drain_on_exit() -> None:
    depth = queue_depth()
    if not depth:
        return
    if flush(EXIT_FLUSH_S):
        log.info("結束前寫完 %d 筆檔案輸出", depth)
    else:
        log.warning("結束前仍有 %d 筆檔案輸出未寫入", queue_depth())


def _worker() -> None:
    while True:
        job = _queue.get()
        try:
            if isinstance(job, TextJob):
                _write_text(job)
            elif isinstance(job, ImageJob):
                _write_image(job)
        except Exception:  # noqa: BLE001 - 背景輸出失敗只記錄，產線執行不回滾
            log.exception("檔案輸出寫入失敗")
        finally:
            _queue.task_done()


def _rotated(path: Path, rotate_bytes: int, rotate_rows: int, *, csv_header: bool) -> Path:
    if rotate_bytes <= 0 and rotate_rows <= 0:
        return path
    candidate = path
    for index in range(1, 10000):
        if not candidate.exists() or not _over_limit(candidate, rotate_bytes, rotate_rows, csv_header=csv_header):
            return candidate
        candidate = path.with_name(f"{path.stem}_{index + 1:03d}{path.suffix}")
    return candidate


def _over_limit(path: Path, rotate_bytes: int, rotate_rows: int, *, csv_header: bool) -> bool:
    try:
        if rotate_bytes > 0 and path.stat().st_size >= rotate_bytes:
            return True
        if rotate_rows > 0:
            rows = _line_count(path)
            if csv_header and rows:
                rows -= 1
            return rows >= rotate_rows
    except OSError:
        return False
    return False


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _write_text(job: TextJob) -> None:
    global _written
    path = _rotated(job.path, job.rotate_bytes, job.rotate_rows, csv_header=(job.fmt == "csv" and job.write_header))
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding=job.encoding, newline="") as fh:
        if job.fmt == "csv":
            writer = csv.writer(fh)
            if job.write_header and new_file:
                writer.writerow(job.header)
            writer.writerow(job.row)
        else:
            fh.write("\t".join(job.row) + "\n")
    with _lock:
        _written += 1


def _write_image(job: ImageJob) -> None:
    global _written
    job.path.parent.mkdir(parents=True, exist_ok=True)
    ext = ".jpg" if job.fmt in ("jpg", "jpeg") else f".{job.fmt}"
    params = [int(cv2.IMWRITE_JPEG_QUALITY), int(job.quality)] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, job.image, params)
    if not ok:
        log.warning("影像輸出編碼失敗：%s", job.path)
        return
    buf.tofile(str(job.path))
    with _lock:
        _written += 1


def flush(timeout: float = 5.0) -> bool:
    """等待目前佇列清空（測試與行程結束前用）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _queue.unfinished_tasks == 0:
            return True
        time.sleep(0.01)
    return _queue.unfinished_tasks == 0


def queue_depth() -> int:
    return _queue.qsize()


def stats() -> dict[str, Any]:
    files = _files()
    with _lock:
        dropped = _dropped
        written = _written
    return {"files": len(files), "bytes": sum(f[1] for f in files), "written": written, "dropped": dropped, "dir": str(root()), "queued": queue_depth()}


def _files() -> list[tuple[float, int, Path]]:
    base = root()
    out: list[tuple[float, int, Path]] = []
    if not base.exists():
        return out
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        out.append((st.st_mtime, st.st_size, path))
    return out


def purge(*, days: int | None = None, max_bytes: int | None = None) -> dict[str, int]:
    """依天數與總容量清理檔案輸出。"""
    days = int(_cfg("FILE_OUTPUT_DAYS", 90) if days is None else days)
    max_bytes = int((float(_cfg("FILE_OUTPUT_MAX_GB", 20)) * (1 << 30)) if max_bytes is None else max_bytes)
    files = sorted(_files())
    removed = freed = 0
    cutoff = time.time() - days * 86400 if days > 0 else 0.0
    keep: list[tuple[float, int, Path]] = []
    for mtime, size, path in files:
        if cutoff and mtime < cutoff:
            try:
                path.unlink()
                removed += 1
                freed += size
                continue
            except OSError:
                pass
        keep.append((mtime, size, path))
    total = sum(item[1] for item in keep)
    for _mtime, size, path in keep:
        if max_bytes <= 0 or total <= max_bytes:
            break
        try:
            path.unlink()
            removed += 1
            freed += size
            total -= size
        except OSError:
            pass
    _prune_empty_dirs()
    return {"removed": removed, "freed": freed}


def _prune_empty_dirs() -> None:
    base = root()
    if not base.exists():
        return
    for path in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass


def clear() -> None:
    """測試用：清空檔案輸出根目錄與計數。"""
    global _dropped, _written, _drop_warned
    shutil.rmtree(root(), ignore_errors=True)
    with _lock:
        _dropped = 0
        _written = 0
        _drop_warned = False
