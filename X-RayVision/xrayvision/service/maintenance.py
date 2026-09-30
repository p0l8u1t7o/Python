"""
資料保留與維護

- 預設不自動刪除檢測資料；磁碟剩餘空間低於門檻時警示。
- 手動檢測工作區 (暫存，非正式紀錄) 預設 7 天未使用即清除。
- 管理員可設定封存影像保留天數：超過天數的封存影像檔會被刪除，
  但分析紀錄、結果檔、複判與稽核紀錄全部保留 (影像檢視改用原始路徑，若原始檔也不存在則無法顯示)。
- 設定存於資料庫 settings 表，變更寫入稽核紀錄。
"""
import json
import logging
import os
import shutil
import threading
import time

from ..store.db import now

log = logging.getLogger("xrayvision.maintenance")

DEFAULTS = dict(
    retention_days=None,        # 封存影像保留天數；None = 不自動刪除
    disk_warn_gb=20.0,          # 剩餘空間低於此值警示 (GB)
    gpu_inference=False,        # 深度學習推論使用 GPU；預設關閉 (設備可能用 GPU 做 3D 重建)
    workspace_retention_days=7, # 手動檢測工作區未使用超過此天數即清除 (PLAN-004)；None = 不自動清除
)


def get_settings(db):
    out = dict(DEFAULTS)
    for r in db.all("SELECT key, value_json FROM settings"):
        if r["key"] in DEFAULTS:
            out[r["key"]] = json.loads(r["value_json"])
    return out


def put_settings(db, changes, actor):
    cur = get_settings(db)
    clean = {}
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise ValueError(k)
        if k in ("retention_days", "workspace_retention_days") and v is not None:
            v = int(v)
            if v < 1:
                raise ValueError(k)
        if k == "gpu_inference":
            if not isinstance(v, bool):
                raise ValueError(k)
        if k == "disk_warn_gb":
            v = float(v)
            if v < 0:
                raise ValueError(k)
        clean[k] = v
    for k, v in clean.items():
        db.execute("INSERT INTO settings (key, value_json, updated_at, updated_by) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at, "
                   "updated_by = excluded.updated_by", (k, json.dumps(v), now(), actor))
    if clean:
        db.audit(actor, "settings.update", "settings", "", before={k: cur[k] for k in clean}, after=clean)
    return get_settings(db)


def disk_status(settings, db):
    try:
        u = shutil.disk_usage(settings.data_dir)
    except OSError:
        return None
    warn_gb = get_settings(db)["disk_warn_gb"]
    free_gb = u.free / 1e9
    return dict(total_gb=round(u.total / 1e9, 1), free_gb=round(free_gb, 1), used_ratio=round(1 - u.free / u.total, 3),
                warn_gb=warn_gb, low=free_gb < warn_gb)


def purge_archive(settings, db, days, actor="system"):
    """刪除超過保留天數的封存影像檔；回傳刪除數量與釋放空間"""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
    rows = db.all("SELECT id, archive_path FROM images WHERE imported_at < ? AND archive_path IS NOT NULL "
                  "AND archive_purged_at IS NULL", (cutoff,))
    n, freed = 0, 0
    root = os.path.abspath(settings.archive_dir)
    for r in rows:
        p = os.path.abspath(r["archive_path"])
        if not p.startswith(root + os.sep):             # 只刪封存區內的檔案，絕不碰原始資料夾
            continue
        try:
            if os.path.isfile(p):
                freed += os.path.getsize(p)
                os.remove(p)
            db.execute("UPDATE images SET archive_purged_at = ? WHERE id = ?", (now(), r["id"]))
            n += 1
        except OSError as e:
            log.warning("purge failed %s: %s", p, e)
    if n:
        db.audit(actor, "maintenance.purge_archive", "images", "", count=n, freed_mb=round(freed / 1e6, 1),
                 retention_days=days)
    return dict(purged=n, freed_mb=round(freed / 1e6, 1))


def cleanup_sessions(db):
    return db.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),)).rowcount


class Maintenance:
    """每小時執行：清除過期工作階段；有設定保留天數時清除過期封存影像；磁碟空間不足時記錄警告"""

    def __init__(self, settings, db_factory, interval_s=3600):
        self.settings = settings
        self.db_factory = db_factory
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = None

    def run_once(self):
        db = self.db_factory()
        cleanup_sessions(db)
        s = get_settings(db)
        out = {}
        if s["retention_days"]:
            out = purge_archive(self.settings, db, s["retention_days"])
        if s["workspace_retention_days"]:
            from .workspace import purge_stale
            n = purge_stale(self.settings, s["workspace_retention_days"])
            if n:
                db.audit("system", "workspace.purge", "workspace", "", count=n, days=s["workspace_retention_days"])
                out["workspaces_purged"] = n
        d = disk_status(self.settings, db)
        if d and d["low"]:
            log.warning("low disk space: %.1f GB free", d["free_gb"])
        return out

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="maintenance", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        if self._stop.wait(30):                                   # 啟動後稍候，避免與開機時的其他工作搶資源
            return
        while True:
            try:
                self.run_once()
            except Exception:                                     # noqa: BLE001
                log.exception("maintenance failed")
            if self._stop.wait(self.interval_s):
                return
