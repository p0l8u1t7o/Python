"""
資料夾監看：設備輸出資料夾出現新影像時自動匯入並分析

- 以輪詢方式掃描 (相容網路磁碟與各種檔案系統)。
- 檔案須連續兩次掃描大小與修改時間不變、且可開啟讀取，才視為寫入完成；避免讀到寫入中的檔案。
- 只讀取原始檔，不移動、不刪除、不鎖定。
- 新增監看資料夾時，資料夾內既有的檔案預設略過 (import_existing=False)。
- 批號與樣品編號由命名規則 (正規表示式，具名群組 lot、sample) 從相對路徑解析；
  未設定規則時，批號為上一層資料夾名稱 (位於根目錄時為日期)，樣品編號為檔名。
"""
import logging
import os
import re
import threading
import time

from ..core.io import IMAGE_EXTENSIONS
from ..store.db import now
from ..service.jobs import ImportFailed, import_image
from ..service.recipes import RecipeStore

log = logging.getLogger("xrayvision.watcher")


class WatchError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def parse_name(rel_path, rule):
    rel = rel_path.replace("\\", "/")
    stem = os.path.splitext(os.path.basename(rel))[0]
    if rule:
        m = re.search(rule, rel)
        if m:
            g = m.groupdict()
            return g.get("lot") or "", g.get("sample") or stem
    parent = os.path.dirname(rel)
    return (os.path.basename(parent) if parent else time.strftime("%Y%m%d")), stem


def add_folder(db, path, recipe_id, actor, recursive=True, name_rule="", import_existing=False):
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise WatchError("folder_not_found", path)
    if RecipeStore(db).latest_released(recipe_id) is None:
        raise WatchError("recipe_not_released", recipe_id)
    if name_rule:
        try:
            re.compile(name_rule)
        except re.error as e:
            raise WatchError("invalid_name_rule", str(e))
    fid = db.insert("watch_folders", path=path, recipe_id=recipe_id, enabled=1, recursive=int(recursive),
                    name_rule=name_rule, created_at=now())
    if not import_existing:
        for rel, st in _scan(path, recursive):
            db.execute("INSERT OR REPLACE INTO watch_seen VALUES (?, ?, ?, ?, 'skipped', ?)",
                       (fid, rel, st.st_size, st.st_mtime, now()))
    db.audit(actor, "watch.add", "watch_folder", fid, path=path, recipe_id=recipe_id, name_rule=name_rule,
             import_existing=import_existing)
    return fid


def _scan(root, recursive):
    if recursive:
        walker = os.walk(root)
    else:
        walker = [(root, [], [f for f in os.listdir(root)])]
    for base, _, files in walker:
        for f in files:
            if not f.lower().endswith(IMAGE_EXTENSIONS) or f.endswith(".part"):
                continue
            p = os.path.join(base, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            yield os.path.relpath(p, root), st


def _readable(path):
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


def scan_folder(settings, db, folder, on_import=None):
    """掃描一個監看資料夾一次；回傳本次匯入的工作編號清單"""
    fid, root = folder["id"], folder["path"]
    if not os.path.isdir(root):
        return []
    seen = {r["rel_path"]: r for r in db.all("SELECT * FROM watch_seen WHERE folder_id = ?", (fid,))}
    recipe = RecipeStore(db).latest_released(folder["recipe_id"])
    jobs = []
    for rel, st in _scan(root, bool(folder["recursive"])):
        prev = seen.get(rel)
        if prev and prev["state"] in ("imported", "skipped", "failed") \
                and prev["size_bytes"] == st.st_size and prev["mtime"] == st.st_mtime:
            continue
        if prev is None or prev["state"] != "pending" or prev["size_bytes"] != st.st_size or prev["mtime"] != st.st_mtime:
            # 第一次看到或仍在變動：記為 pending，下次掃描確認穩定後才匯入
            db.execute("INSERT OR REPLACE INTO watch_seen VALUES (?, ?, ?, ?, 'pending', ?)",
                       (fid, rel, st.st_size, st.st_mtime, now()))
            continue
        path = os.path.join(root, rel)
        if recipe is None or not _readable(path):
            continue
        lot, sample = parse_name(rel, folder["name_rule"])
        try:
            r = import_image(settings, db, path, recipe["id"], "watcher", lot_no=lot, sample_no=sample, source="watch")
            state = "imported"
            jobs.append(r["job_id"])
        except ImportFailed as e:
            log.warning("watch import failed %s: %s", path, e)
            state = "failed"
        db.execute("INSERT OR REPLACE INTO watch_seen VALUES (?, ?, ?, ?, ?, ?)",
                   (fid, rel, st.st_size, st.st_mtime, state, now()))
    db.execute("UPDATE watch_folders SET last_scan_at = ? WHERE id = ?", (now(), fid))
    if jobs and on_import:
        on_import()
    return jobs


class FolderWatcher:
    def __init__(self, settings, db_factory, on_import=None, can_import=None):
        self.settings = settings
        self.db_factory = db_factory
        self.on_import = on_import
        self.can_import = can_import or (lambda: True)          # 授權無效時暫停匯入 (檔案維持等待中)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="folder-watcher", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def scan_all(self):
        if not self.can_import():
            return []
        db = self.db_factory()
        out = []
        for f in db.all("SELECT * FROM watch_folders WHERE enabled = 1"):
            try:
                out += scan_folder(self.settings, db, f, self.on_import)
            except Exception:                                     # noqa: BLE001  單一資料夾錯誤不影響其他資料夾
                log.exception("scan failed: %s", f["path"])
        return out

    def _loop(self):
        while not self._stop.is_set():
            self.scan_all()
            self._stop.wait(self.settings.watch_interval_s)
