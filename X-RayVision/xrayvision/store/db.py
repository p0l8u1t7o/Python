"""
SQLite 資料庫：結構版本管理與存取

設計重點：
  - 結構變更只以「新增」方式進行 (新增資料表、欄位)，每次變更一個版本號，記錄於 schema_version。
    退版採還原升版前快照 (規劃書第 12.5 節)，因此不需要反向遷移。
  - 已發布 (released) 的配方版本不可修改內容；稽核紀錄不可修改或刪除 (以觸發器強制)。
  - 大型資料 (逐物件量測) 存於結果 JSON 檔，資料庫只存摘要與索引。
"""
import json
import sqlite3
import threading
import time

MIGRATIONS = [
    # 1：初始結構
    """
    CREATE TABLE recipes (
        id INTEGER PRIMARY KEY,
        recipe_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        name_json TEXT NOT NULL,
        body_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'released', 'retired')),
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        released_at TEXT,
        released_by TEXT,
        UNIQUE (recipe_id, version)
    );
    CREATE TRIGGER recipes_released_immutable BEFORE UPDATE OF body_json, name_json, recipe_id, version ON recipes
    WHEN OLD.status != 'draft'
    BEGIN SELECT RAISE(ABORT, 'released recipe is immutable'); END;
    CREATE TRIGGER recipes_released_no_delete BEFORE DELETE ON recipes
    WHEN OLD.status != 'draft'
    BEGIN SELECT RAISE(ABORT, 'released recipe cannot be deleted'); END;

    CREATE TABLE lots (
        id INTEGER PRIMARY KEY,
        lot_no TEXT NOT NULL,
        recipe_pk INTEGER REFERENCES recipes(id),
        operator TEXT NOT NULL DEFAULT '',
        acquisition_json TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT 'manual',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX lots_no ON lots(lot_no);

    CREATE TABLE images (
        id INTEGER PRIMARY KEY,
        sha256 TEXT NOT NULL UNIQUE,
        original_path TEXT NOT NULL,
        archive_path TEXT,
        file_name TEXT NOT NULL,
        kind TEXT,
        width INTEGER,
        height INTEGER,
        size_bytes INTEGER,
        lot_id INTEGER REFERENCES lots(id),
        sample_no TEXT NOT NULL DEFAULT '',
        imported_at TEXT NOT NULL
    );
    CREATE INDEX images_lot ON images(lot_id);

    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY,
        image_id INTEGER NOT NULL REFERENCES images(id),
        recipe_pk INTEGER NOT NULL REFERENCES recipes(id),
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
        priority INTEGER NOT NULL DEFAULT 0,
        acquisition_json TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT 'manual',
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX jobs_status ON jobs(status, priority DESC, id);

    CREATE TABLE runs (
        id INTEGER PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id),
        image_id INTEGER NOT NULL REFERENCES images(id),
        recipe_pk INTEGER NOT NULL REFERENCES recipes(id),
        software_version TEXT NOT NULL,
        result_path TEXT NOT NULL,
        quality_level TEXT NOT NULL,
        reference_only INTEGER NOT NULL,
        auto_judgment TEXT NOT NULL,
        final_judgment TEXT NOT NULL,
        summary_json TEXT NOT NULL DEFAULT '{}',
        elapsed_s REAL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX runs_image ON runs(image_id);
    CREATE INDEX runs_created ON runs(created_at);
    CREATE INDEX runs_judgment ON runs(final_judgment);

    CREATE TABLE module_results (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id),
        module_id TEXT NOT NULL,
        module_version TEXT NOT NULL,
        status TEXT NOT NULL,
        judgment TEXT NOT NULL,
        reasons_json TEXT NOT NULL DEFAULT '[]',
        summary_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX module_results_run ON module_results(run_id);

    CREATE TABLE reviews (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id),
        judgment TEXT NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        reviewer TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX reviews_run ON reviews(run_id);

    CREATE TABLE watch_folders (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        recipe_id TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        recursive INTEGER NOT NULL DEFAULT 1,
        name_rule TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_scan_at TEXT
    );
    CREATE TABLE watch_seen (
        folder_id INTEGER NOT NULL REFERENCES watch_folders(id),
        rel_path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        mtime REAL NOT NULL,
        state TEXT NOT NULL,
        seen_at TEXT NOT NULL,
        PRIMARY KEY (folder_id, rel_path)
    );

    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL DEFAULT '',
        target_id TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

    CREATE TABLE diagnostic_exports (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        actor TEXT NOT NULL,
        file_name TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        run_ids_json TEXT NOT NULL,
        options_json TEXT NOT NULL
    );
    """,
    # 2：帳號、工作階段、系統設定、影像封存清除標記
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('operator', 'engineer', 'admin')),
        password_hash TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        last_login_at TEXT
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
    ALTER TABLE images ADD COLUMN archive_purged_at TEXT;
    """,
    # 3：檢測模組驗證狀態 (只新增；最新一筆為目前狀態)。微凸塊對位 1.1 已有回歸基準與重複性驗證，直接標示已驗證
    """
    CREATE TABLE module_validations (
        id INTEGER PRIMARY KEY,
        module_id TEXT NOT NULL,
        series TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('validated', 'revoked')),
        note TEXT NOT NULL DEFAULT '',
        report_name TEXT NOT NULL DEFAULT '',
        actor TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX module_validations_key ON module_validations (module_id, series, id);
    INSERT INTO module_validations (module_id, series, status, note, actor, created_at)
        VALUES ('bump_alignment', '1.1', 'validated', 'modval.baseline',
                'system', strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'));
    """,
    # 4：深度學習模型 (第 5c 階段)
    """
    CREATE TABLE models (
        id INTEGER PRIMARY KEY,
        model_id TEXT NOT NULL,
        version TEXT NOT NULL,
        module_id TEXT NOT NULL,
        task TEXT NOT NULL DEFAULT '',
        sha256 TEXT NOT NULL,
        meta_json TEXT NOT NULL,
        file_path TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active', 'retired')),
        imported_by TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        UNIQUE (model_id, version)
    );
    """,
    # 5：標註 (第 5d 階段)；只新增，最新一筆為目前標註
    """
    CREATE TABLE annotations (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id),
        image_id INTEGER NOT NULL REFERENCES images(id),
        module_id TEXT NOT NULL,
        data_json TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        actor TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX annotations_key ON annotations (image_id, module_id, id);
    CREATE TRIGGER annotations_no_update BEFORE UPDATE ON annotations
    BEGIN SELECT RAISE(ABORT, 'annotations are append-only'); END;
    """,
    # 6：目前結果 (同一影像最新一筆紀錄) 的查詢索引 (PLAN-003)
    """
    CREATE INDEX runs_image_latest ON runs (image_id, id);
    """,
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Database:
    """執行緒安全的 SQLite 存取 (每個執行緒一條連線)"""

    def __init__(self, path):
        self.path = path
        self._local = threading.local()
        self.migrate()

    @property
    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA busy_timeout = 30000")
            self._local.conn = c
        return c

    def close(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    def migrate(self):
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
        cur = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        for v, sql in enumerate(MIGRATIONS, 1):
            if v <= cur:
                continue
            c.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _split_sql(sql):
                    c.execute(stmt)
                c.execute("INSERT INTO schema_version VALUES (?, ?)", (v, now()))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    @property
    def schema_version(self):
        return self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    # ---- 基本操作 ----
    def execute(self, sql, args=()):
        return self.conn.execute(sql, args)

    def one(self, sql, args=()):
        r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def all(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def insert(self, table, **cols):
        keys = ", ".join(cols)
        qs = ", ".join("?" for _ in cols)
        return self.conn.execute(f"INSERT INTO {table} ({keys}) VALUES ({qs})", tuple(cols.values())).lastrowid

    def transaction(self):
        return _Tx(self.conn)

    # ---- 稽核 ----
    def audit(self, actor, action, target_type="", target_id="", **detail):
        self.insert("audit_log", ts=now(), actor=actor or "system", action=action, target_type=target_type,
                    target_id=str(target_id), detail_json=json.dumps(detail, ensure_ascii=False, default=str))


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, et, ev, tb):
        self.conn.execute("ROLLBACK" if et else "COMMIT")
        return False


def _split_sql(script):
    """依分號切開，但保留 CREATE TRIGGER ... BEGIN ... END; 區塊完整"""
    out, buf, in_trigger = [], [], False
    for line in script.splitlines():
        s = line.strip()
        if not s:
            continue
        buf.append(line)
        if s.upper().startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if s.upper().endswith("END;"):
                out.append("\n".join(buf))
                buf, in_trigger = [], False
        elif s.endswith(";"):
            out.append("\n".join(buf))
            buf = []
    if buf:
        out.append("\n".join(buf))
    return out
