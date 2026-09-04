"""擷取端記錄：主控台＋輪替檔案（%APPDATA%/VisionSequenceCapture/logs/），UI 可再掛一個 handler 顯示。"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from vscapture.config import app_dir

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_dir() -> Path:
    return app_dir() / "logs"


def setup_logging(level: str = "INFO", *, to_file: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    if sys.stderr is not None and not any(isinstance(h, logging.StreamHandler) and getattr(h, "_vsc", False) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(FORMAT))
        console._vsc = True  # type: ignore[attr-defined]
        root.addHandler(console)
    if to_file and not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        try:
            log_dir().mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(log_dir() / "capture.log", maxBytes=2 << 20, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter(FORMAT))
            root.addHandler(fh)
        except OSError:
            pass
