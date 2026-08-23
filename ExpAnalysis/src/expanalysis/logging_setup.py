"""日誌設定。

規則：
  DEBUG   單點擬合細節（預設關閉，呼叫端需以 isEnabledFor 保護）
  INFO    狀態轉換（服務啟動、批次匯入、模型重擬合）
  WARNING 可恢復異常（LLM 退回模板模式、單批擬合不收斂）
  ERROR   需人介入（資料庫寫入失敗、schema 版本不符）

輸出同時到 stderr 與輪替檔案，避免長時間執行把磁碟塞爆。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(stream)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_dir / "expanalysis.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
            root.addHandler(fh)
        except OSError as exc:  # 檔案系統唯讀等狀況：降級為只輸出 stderr
            root.warning("無法建立日誌檔案（%s），僅輸出至 stderr", exc)

    # uvicorn 自帶的 handler 會造成重複輸出
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).propagate = True
        logging.getLogger(name).handlers.clear()

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
