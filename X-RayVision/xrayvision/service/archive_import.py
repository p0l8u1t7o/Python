"""
退版封存檔匯入 (規劃書第 12.5 節)

退版時，啟動器把升版後新增的紀錄匯出為封存檔 (資料目錄 rollback_archives/)。
日後再次升級到該版本或更新的版本時，由管理員於網頁匯入，將紀錄合併回資料庫：
  - 配方依 (配方代碼, 版本) 對應，不存在才新增
  - 批次依 (批號, 配方) 對應；影像依雜湊值對應 (原始影像檔不刪除，封存路徑沿用)
  - 工作、分析紀錄、模組結果、複判重新編號後新增
  - 稽核紀錄照原時間與人員新增，並於內容註記來源封存檔
  - 同一個封存檔只能匯入一次；欄位以目前資料庫結構為準 (新版本新增的欄位使用預設值)
"""
import json
import os

from ..store.db import now


class ArchiveError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def archives_dir(settings):
    return os.path.join(settings.data_dir, "rollback_archives")


def imported_names(db):
    r = db.one("SELECT value_json FROM settings WHERE key = 'imported_archives'")
    return json.loads(r["value_json"]) if r else []


def list_archives(settings, db):
    d = archives_dir(settings)
    done = set(imported_names(db))
    out = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d), reverse=True):
            if n.endswith(".json"):
                try:
                    with open(os.path.join(d, n), encoding="utf-8") as f:
                        a = json.load(f)
                    counts = {k: len(v) for k, v in a.get("tables", {}).items()}
                except (OSError, ValueError):
                    counts = {}
                    a = {}
                out.append(dict(name=n, created_at=a.get("created_at"), from_version=a.get("from_version"),
                                counts=counts, imported=n in done))
    return out


def _columns(con, table):
    return [r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]


def _insert(con, table, row, cols):
    keys = [k for k in row if k in cols and k != "id"]
    cur = con.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                      [row[k] for k in keys])
    return cur.lastrowid


def import_archive(settings, db, name, actor):
    if os.path.basename(name) != name or not name.endswith(".json"):
        raise ArchiveError("invalid_file_name", name)
    if name in imported_names(db):
        raise ArchiveError("archive_already_imported", name)
    path = os.path.join(archives_dir(settings), name)
    try:
        with open(path, encoding="utf-8") as f:
            a = json.load(f)
    except (OSError, ValueError):
        raise ArchiveError("archive_unreadable", name)
    if a.get("format") != "xrv-rollback-archive/1":
        raise ArchiveError("archive_unreadable", name)
    t = a["tables"]
    counts = {}
    with db.transaction() as con:
        cols = {tb: _columns(con, tb) for tb in ("recipes", "lots", "images", "jobs", "runs", "module_results",
                                                 "reviews", "audit_log", "diagnostic_exports")}
        rmap, lmap, imap, jmap, runmap = {}, {}, {}, {}, {}
        for r in t.get("recipes", []):
            ex = con.execute("SELECT id FROM recipes WHERE recipe_id = ? AND version = ?",
                             (r["recipe_id"], r["version"])).fetchone()
            rmap[r["id"]] = ex["id"] if ex else _insert(con, "recipes", r, cols["recipes"])
        def recipe_pk(old):
            if old in rmap:
                return rmap[old]
            ex = con.execute("SELECT id FROM recipes WHERE id = ?", (old,)).fetchone()
            if ex is None:
                raise ArchiveError("archive_recipe_missing", old)
            return old
        for r in t.get("lots", []):
            rp = recipe_pk(r["recipe_pk"]) if r.get("recipe_pk") else None
            ex = con.execute("SELECT id FROM lots WHERE lot_no = ? AND recipe_pk IS ?", (r["lot_no"], rp)).fetchone()
            lmap[r["id"]] = ex["id"] if ex else _insert(con, "lots", dict(r, recipe_pk=rp), cols["lots"])
        for r in t.get("images", []):
            ex = con.execute("SELECT id FROM images WHERE sha256 = ?", (r["sha256"],)).fetchone()
            lot = lmap.get(r.get("lot_id"), r.get("lot_id"))
            imap[r["id"]] = ex["id"] if ex else _insert(con, "images", dict(r, lot_id=lot), cols["images"])
        def image_id(old):
            if old in imap:
                return imap[old]
            if con.execute("SELECT id FROM images WHERE id = ?", (old,)).fetchone() is None:
                raise ArchiveError("archive_image_missing", old)
            return old
        for r in t.get("jobs", []):
            jmap[r["id"]] = _insert(con, "jobs", dict(r, image_id=image_id(r["image_id"]),
                                                      recipe_pk=recipe_pk(r["recipe_pk"])), cols["jobs"])
        for r in t.get("runs", []):
            runmap[r["id"]] = _insert(con, "runs", dict(r, job_id=jmap.get(r["job_id"], r["job_id"]),
                                                        image_id=image_id(r["image_id"]),
                                                        recipe_pk=recipe_pk(r["recipe_pk"])), cols["runs"])
        for tb in ("module_results", "reviews"):
            for r in t.get(tb, []):
                if r["run_id"] in runmap:
                    _insert(con, tb, dict(r, run_id=runmap[r["run_id"]]), cols[tb])
        for r in t.get("audit_log", []):
            detail = json.loads(r.get("detail_json") or "{}")
            detail["restored_from"] = name
            _insert(con, "audit_log", dict(r, detail_json=json.dumps(detail, ensure_ascii=False)), cols["audit_log"])
        for r in t.get("diagnostic_exports", []):
            _insert(con, "diagnostic_exports", r, cols["diagnostic_exports"])
        counts = {k: len(v) for k, v in t.items()}
        done = imported_names(db) + [name]
        con.execute("INSERT INTO settings (key, value_json, updated_at, updated_by) VALUES ('imported_archives', ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at, "
                    "updated_by = excluded.updated_by", (json.dumps(done), now(), actor))
    db.audit(actor, "system.archive_import", "rollback_archive", name, counts=counts)
    return counts
