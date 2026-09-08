"""資料保留與自動整理：過了保存時限的資料自動刪除，但**絕不影響正在跑的檢測**。

規則（與使用者談定）：
1. 保存時限存在資料庫（單列 `RetentionSettings`），前端「設定」頁可改；沒有列時用 `.env`／出廠值。預設 1 年。
2. **只在引擎空檔刪**：清理跑在既有的持久化執行緒（`runner.persister`）閒置那一段，
   每批最多 `BATCH` 列就讓出，發現有 run 在排隊／執行／連續模式就立刻停手，下次再繼續。
3. **夜間維護視窗**：整理備份與 SQLite 空間回收（VACUUM，會鎖住整個資料庫）只在設定的時段做，
   而且要引擎連續閒置 `IDLE_S` 秒；白天只做小批量刪除。
4. 備份：`data/backups/*.zip` 與還原前留下的資料庫副本，各保留最近 N 份。
5. 看得到：`GET /vision/retention` 回設定＋上次整理時間、刪了幾列、資料庫與封存大小，doctor 也有一條。

熱路徑（引擎執行緒）完全不碰這個模組；持久化執行緒讀的設定有記憶體快取，存檔時作廢。
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.core.models import AuditLog
from apps.vision import archive, fileout
from apps.vision.models import FlowRun, MeasurementLog, RetentionSettings

#: 一批刪幾列（刪完就讓出，避免長交易卡住寫入）
BATCH = 500
#: 兩次小整理至少隔多久
SWEEP_INTERVAL_S = 600.0
#: 深度整理（備份、VACUUM）前要求引擎閒置多久
IDLE_S = 60.0
#: 一天最多一次深度整理
DEEP_INTERVAL_S = 20 * 3600.0
#: 孤兒固定影像要放這麼久才刪（上傳完還沒存進流程的圖不能被掃掉）
ORPHAN_AGE_S = 7 * 86400.0

#: 可設定的欄位與型別（前端只送這些）
FIELDS: dict[str, type] = {
    "run_days": int, "audit_days": int, "measurement_days": int, "archive_days": int,
    "archive_max_gb": float, "file_output_days": int, "file_output_max_gb": float,
    "backup_keep": int, "window_hour": int, "vacuum": bool, "enabled": bool,
}
#: 天數欄位的上限（0＝永久保留）
MAX_DAYS = 3650

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
#: 只有 manage.py serve 會打開背景整理（測試與一次性 CLI 不該有執行緒在背後刪資料）
_background = False
_last_sweep = 0.0
_last_deep = 0.0
_idle_since = 0.0


def defaults() -> dict[str, Any]:
    """出廠值：資料類保存 1 年，封存影像沿用站點設定（另有容量上限），維護視窗 03:00。"""
    cfg = settings.VISION
    return {
        "run_days": int(cfg.get("KEEP_RUN_DAYS", 365) or 0),
        "audit_days": int(cfg.get("AUDIT_DAYS", 365) or 0),
        "measurement_days": int(cfg.get("MEASUREMENT_DAYS", 365) or 0),
        "archive_days": int(cfg.get("ARCHIVE_DAYS", 90) or 0),
        "archive_max_gb": float(cfg.get("ARCHIVE_MAX_GB", 20.0) or 0),
        "file_output_days": int(cfg.get("FILE_OUTPUT_DAYS", 90) or 0),
        "file_output_max_gb": float(cfg.get("FILE_OUTPUT_MAX_GB", 20.0) or 0),
        "backup_keep": int(cfg.get("KEEP_BACKUPS", 10) or 0),
        "window_hour": int(cfg.get("MAINTENANCE_HOUR", 3)),
        "vacuum": True,
        "enabled": True,
    }


def effective() -> dict[str, Any]:
    """目前生效的設定（資料庫有列就用它，否則出廠值）；記憶體快取，存檔時作廢。"""
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
    values = defaults()
    try:
        row = RetentionSettings.objects.filter(id=1).first()
    except Exception:  # noqa: BLE001 - 還沒 migrate 或資料庫忙：用出廠值，不能讓呼叫者炸掉
        row = None
    if row is not None:
        for key in FIELDS:
            values[key] = getattr(row, key)
    with _lock:
        _cache = dict(values)
    return dict(values)


def enable_background(on: bool = True) -> None:
    """serve 啟動時打開；沒打開的話持久化執行緒不會自己整理。"""
    global _background
    _background = bool(on)


def background_enabled() -> bool:
    return _background


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def save(changes: dict[str, Any]) -> dict[str, Any]:
    """寫入設定（只認 FIELDS 的鍵，值先正規化），回傳生效後的設定。"""
    clean: dict[str, Any] = {}
    for key, kind in FIELDS.items():
        if key not in changes or changes[key] is None:
            continue
        raw = changes[key]
        if kind is bool:
            clean[key] = bool(raw)
        elif kind is int:
            clean[key] = max(0, min(MAX_DAYS, int(raw)))
        else:
            clean[key] = max(0.0, float(raw))
    if "window_hour" in clean:
        clean["window_hour"] = max(0, min(23, int(clean["window_hour"])))
    if "backup_keep" in clean:
        clean["backup_keep"] = max(0, min(1000, int(clean["backup_keep"])))
    row, _ = RetentionSettings.objects.get_or_create(id=1, defaults=defaults())
    for key, value in clean.items():
        setattr(row, key, value)
    row.save()
    invalidate()
    return effective()


# ---------------------------------------------------------------------------
# 引擎忙不忙
# ---------------------------------------------------------------------------
def busy() -> bool:
    """有 run 在排隊、執行中或連續模式在跑就算忙（清理要讓路）。"""
    from apps.vision import runner as runner_mod

    try:
        for entry in runner_mod.runner.capacity().get("flows", []):
            if entry.get("running") or entry.get("queued") or entry.get("continuous"):
                return True
    except Exception:  # noqa: BLE001
        return True  # 問不出來就當忙，寧可不刪
    return bool(runner_mod.persister.q.qsize() or fileout.queue_depth())


def _note_idle() -> float:
    """引擎已經連續閒置幾秒；正在忙就回 -1（呼叫者據此完全跳過）。"""
    global _idle_since
    now = time.monotonic()
    if busy():
        _idle_since = 0.0
        return -1.0
    if not _idle_since:
        _idle_since = now
    return now - _idle_since


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------
def _cutoff(days: int) -> dt.datetime | None:
    return timezone.now() - dt.timedelta(days=int(days)) if days and days > 0 else None


def _sweep_runs(cutoff: dt.datetime, budget: int) -> int:
    """明細 FlowRun：一批 BATCH 列，順便刪掉它們的封存影像。"""
    removed = 0
    while removed < budget:
        doomed = list(FlowRun.objects.filter(started_at__lt=cutoff).values_list("id", "images")[:BATCH])
        if not doomed:
            break
        for run_id, images in doomed:
            archive.drop_run(run_id.hex, images)
        FlowRun.objects.filter(id__in=[d[0] for d in doomed]).delete()
        removed += len(doomed)
        if len(doomed) < BATCH or busy():
            break
    return removed


def _sweep_rows(model, field: str, cutoff: dt.datetime, budget: int) -> int:
    """一般資料列（量測值、操作紀錄）：主鍵分批刪，不做一次性大交易。"""
    removed = 0
    while removed < budget:
        ids = list(model.objects.filter(**{f"{field}__lt": cutoff}).values_list("pk", flat=True)[:BATCH])
        if not ids:
            break
        model.objects.filter(pk__in=ids).delete()
        removed += len(ids)
        if len(ids) < BATCH or busy():
            break
    return removed


def sweep(*, deep: bool = False, budget: int = 5000, force: bool = False) -> dict[str, Any]:
    """跑一次整理，回報刪了什麼。`deep`＝連備份與 VACUUM 一起做（維護視窗）。"""
    cfg = effective()
    result: dict[str, Any] = {
        "runs": 0, "measurements": 0, "audit": 0,
        "archive_files": 0, "archive_freed": 0,
        "file_output_files": 0, "file_output_freed": 0,
        "pictures": 0, "backups": 0, "vacuum": False,
    }
    if not cfg["enabled"] and not force:
        return result
    started = time.perf_counter()

    cutoff = _cutoff(cfg["run_days"])
    if cutoff and (force or not busy()):
        result["runs"] = _sweep_runs(cutoff, budget)
    cutoff = _cutoff(cfg["measurement_days"])
    if cutoff and (force or not busy()):
        result["measurements"] = _sweep_rows(MeasurementLog, "ts", cutoff, budget)
    cutoff = _cutoff(cfg["audit_days"])
    if cutoff and (force or not busy()):
        result["audit"] = _sweep_rows(AuditLog, "at", cutoff, budget)
    if force or not busy():
        purged = archive.purge(days=cfg["archive_days"] or 0, max_bytes=int(cfg["archive_max_gb"] * (1 << 30)))
        result["archive_files"] = int(purged.get("removed", 0))
        result["archive_freed"] = int(purged.get("freed", 0))
    if force or not busy():
        purged = fileout.purge(days=cfg["file_output_days"] or 0, max_bytes=int(cfg["file_output_max_gb"] * (1 << 30)))
        result["file_output_files"] = int(purged.get("removed", 0))
        result["file_output_freed"] = int(purged.get("freed", 0))
    if deep:
        result["pictures"] = purge_orphan_pictures()
        result["backups"] = purge_backups(cfg["backup_keep"])
        if cfg["vacuum"]:
            result["vacuum"] = vacuum()
    result["ms"] = round((time.perf_counter() - started) * 1000, 1)
    _record(result, deep=deep)
    return result


def _record(result: dict[str, Any], *, deep: bool) -> None:
    """把這次的結果記在設定列上（設定頁與 doctor 顯示「上次整理」）。"""
    fields = {"last_sweep_at": timezone.now(), "last_result": result}
    if deep:
        fields["last_deep_at"] = timezone.now()
    try:
        if not RetentionSettings.objects.filter(id=1).update(**fields):
            RetentionSettings.objects.create(id=1, **defaults(), **fields)
    except Exception:  # noqa: BLE001 - 記錄失敗不能影響清理本身
        return
    invalidate()


def maybe_sweep() -> dict[str, Any] | None:
    """持久化執行緒的閒置分支每兩秒呼叫一次：時間到了、引擎閒著才真的動手。"""
    global _last_sweep, _last_deep
    idle = _note_idle()
    if idle < 0:
        return None
    cfg = effective()
    if not cfg["enabled"]:
        return None
    now = time.monotonic()
    deep = False
    if idle >= IDLE_S and now - _last_deep >= DEEP_INTERVAL_S and _in_window(cfg["window_hour"]):
        deep = True
    elif now - _last_sweep < SWEEP_INTERVAL_S:
        return None
    _last_sweep = now
    if deep:
        _last_deep = now
    try:
        return sweep(deep=deep, budget=BATCH * (20 if deep else 2))
    except Exception:  # noqa: BLE001 - 維護出錯只記 log，產線照跑
        import logging

        logging.getLogger(__name__).exception("資料保留整理失敗")
        return None


def _in_window(hour: int) -> bool:
    """維護視窗＝當地時間 hour:00–hour:59。"""
    return timezone.localtime().hour == int(hour) % 24


# ---------------------------------------------------------------------------
# 備份與空間
# ---------------------------------------------------------------------------
def backup_files() -> list[tuple[str, os.stat_result]]:
    """`data/backups/*.zip` 與資料庫旁邊的 `*.before-restore-*` 副本（新到舊）。"""
    out: list[tuple[str, os.stat_result]] = []
    folder = os.path.join(str(settings.DATA_DIR), "backups")
    try:
        for name in os.listdir(folder):
            if name.lower().endswith(".zip"):
                path = os.path.join(folder, name)
                out.append((path, os.stat(path)))
    except OSError:
        pass
    db = str(settings.DATABASES["default"]["NAME"])
    db_dir = os.path.dirname(db) or "."
    base = os.path.basename(db)
    try:
        for name in os.listdir(db_dir):
            if name.startswith(base + ".before-restore"):
                path = os.path.join(db_dir, name)
                out.append((path, os.stat(path)))
    except OSError:
        pass
    return sorted(out, key=lambda item: item[1].st_mtime, reverse=True)


def purge_backups(keep: int) -> int:
    """兩種備份各自保留最近 keep 份（0＝全部保留）；回傳刪掉幾個檔案。"""
    if not keep or keep <= 0:
        return 0
    zips = [f for f in backup_files() if f[0].lower().endswith(".zip")]
    copies = [f for f in backup_files() if not f[0].lower().endswith(".zip")]
    removed = 0
    for group in (zips, copies):
        for path, _st in group[int(keep):]:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed


def purge_orphan_pictures(min_age_s: float = ORPHAN_AGE_S) -> int:
    """沒有任何流程／版本／範本引用的固定影像；只刪放超過 min_age_s 的（剛上傳還沒存檔的不能碰）。"""
    from apps.vision import fixed_images

    cutoff = time.time() - float(min_age_s)
    removed = 0
    for image_id in fixed_images.orphans():
        try:
            if os.path.getmtime(fixed_images.path_of(image_id)) > cutoff:
                continue
        except (OSError, fixed_images.FixedImageError):
            continue
        if fixed_images.remove(image_id):
            removed += 1
    return removed


def vacuum() -> bool:
    """SQLite 空間回收：只在 sqlite、引擎閒著時做（會鎖住整個資料庫幾秒）。"""
    if "sqlite" not in connection.vendor or busy():
        return False
    try:
        with connection.cursor() as cur:
            cur.execute("VACUUM")
        return True
    except Exception:  # noqa: BLE001
        return False


def db_bytes() -> int:
    path = str(settings.DATABASES["default"]["NAME"])
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(path + suffix)
        except OSError:
            pass
    return total


def _fixed_bytes() -> int:
    from apps.vision import fixed_images

    return fixed_images.total_bytes()


def _fixed_orphans() -> int:
    from apps.vision import fixed_images

    return len(fixed_images.orphans())


def status() -> dict[str, Any]:
    """設定頁與 doctor 用：設定＋上次整理＋目前用量。"""
    cfg = effective()
    row = RetentionSettings.objects.filter(id=1).first()
    files = backup_files()
    stats = archive.stats()
    out_stats = fileout.stats()
    return {
        "settings": cfg,
        "defaults": defaults(),
        "last_sweep_at": row.last_sweep_at.isoformat() if row and row.last_sweep_at else None,
        "last_deep_at": row.last_deep_at.isoformat() if row and row.last_deep_at else None,
        "last_result": (row.last_result if row else None) or {},
        "usage": {
            "db_bytes": db_bytes(),
            "archive_files": int(stats.get("files", 0)),
            "archive_bytes": int(stats.get("bytes", 0)),
            "file_output_files": int(out_stats.get("files", 0)),
            "file_output_bytes": int(out_stats.get("bytes", 0)),
            "backup_files": len(files),
            "backup_bytes": sum(st.st_size for _p, st in files),
            "picture_bytes": _fixed_bytes(),
            "picture_orphans": _fixed_orphans(),
            "runs": FlowRun.objects.count(),
            "audit": AuditLog.objects.count(),
            "measurements": MeasurementLog.objects.count(),
        },
        "busy": busy(),
    }
