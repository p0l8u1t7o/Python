"""SQLite 儲存層。

選型理由：本工具是單機離線分析工具，批次數以百計、量測點以萬計，SQLite
綽綽有餘且零維運。不要為了「未來可能需要」就在單機情境直接上 PostgreSQL。
若日後要跨機集中，SQLite 檔可以被 DuckDB 直接查，遷移成本很低。

設定：
  journal_mode=WAL     讀寫不互相阻塞（UI 查詢時背景可寫入）
  synchronous=NORMAL   在有 UPS 的辦公環境是合理取捨
  foreign_keys=ON      SQLite 預設關閉，必須每個連線都開

schema 變更一律走 ``_MIGRATIONS`` 版本化腳本，不手改線上資料庫。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator

from ..logging_setup import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1

_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS batch (
            batch_id         TEXT PRIMARY KEY,
            run_date         TEXT NOT NULL DEFAULT '',
            ingot_len_mm     REAL NOT NULL,
            zone_len_mm      REAL NOT NULL,
            speed_mm_hr      REAL NOT NULL,
            temp_c           REAL NOT NULL,
            n_passes         INTEGER NOT NULL,
            atmosphere       TEXT NOT NULL DEFAULT 'Ar',
            head_crop_frac   REAL NOT NULL DEFAULT 0.0,
            feed_purity_note TEXT NOT NULL DEFAULT '',
            analysis_method  TEXT NOT NULL DEFAULT 'GDMS',
            operator         TEXT NOT NULL DEFAULT '',
            notes            TEXT NOT NULL DEFAULT '',
            created_ms       INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS measurement (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id    TEXT NOT NULL REFERENCES batch(batch_id) ON DELETE CASCADE,
            element     TEXT NOT NULL,
            x_norm      REAL NOT NULL,
            value_ppm   REAL NOT NULL,
            lod_ppm     REAL NOT NULL DEFAULT 0.0,
            censored    INTEGER NOT NULL DEFAULT 0,
            pass_index  INTEGER,
            sample_id   TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS element_spec (
            batch_id    TEXT NOT NULL REFERENCES batch(batch_id) ON DELETE CASCADE,
            element     TEXT NOT NULL,
            c0_ppm      REAL NOT NULL,
            spec_ppm    REAL,
            c0_measured INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (batch_id, element)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_meas_batch    ON measurement(batch_id)",
        "CREATE INDEX IF NOT EXISTS ix_meas_be       ON measurement(batch_id, element)",
        "CREATE INDEX IF NOT EXISTS ix_batch_date    ON batch(run_date)",
        "CREATE INDEX IF NOT EXISTS ix_batch_speed   ON batch(speed_mm_hr)",
    ],
}


class Database:
    """執行緒安全的 SQLite 包裝。

    FastAPI 的同步端點跑在 threadpool，每條執行緒各自持有連線
    （sqlite3 的連線物件不可跨執行緒共用）。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        with self._init_lock:
            self.migrate()

    # ── 連線管理 ────────────────────────────────────────────────
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── schema ─────────────────────────────────────────────────
    def user_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        cur = self.user_version()
        if cur > SCHEMA_VERSION:
            raise RuntimeError(
                f"資料庫 schema 版本 {cur} 高於本程式支援的 {SCHEMA_VERSION}；"
                "請更新程式，不要用舊版開啟新資料庫。"
            )
        for version in range(cur + 1, SCHEMA_VERSION + 1):
            log.info("套用 schema migration v%d", version)
            with self.conn:
                for stmt in _MIGRATIONS[version]:
                    self.conn.execute(stmt)
                self.conn.execute(f"PRAGMA user_version={version}")

    # ── 便利方法 ────────────────────────────────────────────────
    def execute(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def executemany(self, sql: str, rows: Iterable[tuple]) -> None:
        """批次寫入。逐筆開 transaction 會讓匯入變成瓶頸。"""
        with self.conn:
            self.conn.executemany(sql, rows)

    def transaction(self):
        return self.conn


_DB: Database | None = None
_DB_LOCK = threading.Lock()


def get_db(path: Path | None = None) -> Database:
    """取得行程層級的單例 Database。測試可傳入不同路徑重建。"""
    global _DB
    with _DB_LOCK:
        if _DB is None or (path is not None and Path(path) != _DB.path):
            from ..config import SETTINGS
            _DB = Database(path or SETTINGS.db_path)
        return _DB


def reset_db_singleton() -> None:
    """僅供測試使用。"""
    global _DB
    with _DB_LOCK:
        if _DB is not None:
            _DB.close()
        _DB = None
