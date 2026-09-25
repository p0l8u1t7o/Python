"""
影像匯入與分析工作佇列

- 匯入：檢查影像可讀、計算雜湊值、複製封存 (可設定)、讀取拍攝參數 (於原始檔位置尋找參數檔)、建立工作。
- 佇列：工作存於資料庫；服務重啟時把「執行中」的工作放回佇列，不會遺失。
- 執行：分析在子行程中以較低優先權執行 (與設備控制軟體共用電腦)；單張失敗不影響其他工作。
- 重新分析：同一張影像可多次分析，最新一筆紀錄為「目前結果」，較早的紀錄保留為歷程 (PLAN-003)。
- 試跑：以未發布的配方內容分析一張影像，結果不寫入紀錄 (TrialRunner)。
"""
import json
import logging
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from ..core import acquisition, runtime, serialize
from ..core.calibration import CalibrationError
from ..core.io import ImageFormatError, load_image
from ..core.pipeline import analyze_image
from . import maintenance, modules
from . import models as model_store
from ..store import archive
from ..store.db import now
from .recipes import RecipeStore, RecipeStoreError

log = logging.getLogger("xrayvision.jobs")
MAX_ATTEMPTS = 2


class ImportFailed(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


# ---------------------------------------------------------------------------
# 匯入
# ---------------------------------------------------------------------------
def find_or_create_lot(db, lot_no, recipe_pk, operator="", source="manual", acquisition_params=None):
    lot_no = (lot_no or "").strip()
    if not lot_no:
        return None
    r = db.one("SELECT id FROM lots WHERE lot_no = ? AND recipe_pk = ?", (lot_no, recipe_pk))
    if r:
        return r["id"]
    return db.insert("lots", lot_no=lot_no, recipe_pk=recipe_pk, operator=operator, source=source,
                     acquisition_json=json.dumps(acquisition_params or {}, ensure_ascii=False), created_at=now())


def import_image(settings, db, path, recipe_pk, actor, lot_no="", sample_no="", acquisition_manual=None,
                 source="manual", priority=0):
    """匯入一張影像並建立分析工作；回傳 dict(image_id, job_id)"""
    recipe = RecipeStore(db).get(recipe_pk)
    if recipe is None:
        raise ImportFailed("recipe_not_found", recipe_pk)
    if recipe["status"] != "released":
        raise ImportFailed("recipe_not_released", f"{recipe['recipe_id']} v{recipe['version']}")
    try:
        img = load_image(path)                    # 確認可讀取並判定種類
    except ImageFormatError as e:
        raise ImportFailed(e.code, path)
    sha = img.sha256
    acq = acquisition.collect(path, acquisition_manual)
    row = db.one("SELECT * FROM images WHERE sha256 = ?", (sha,))
    arch = None
    if settings.archive_originals:
        arch, _ = archive.store(settings.archive_dir, path, sha)
    lot_id = find_or_create_lot(db, lot_no, recipe_pk, actor, source, acq["params"])
    if row is None:
        image_id = db.insert("images", sha256=sha, original_path=os.path.abspath(path), archive_path=arch,
                             file_name=os.path.basename(path), kind=img.kind, width=img.shape[1], height=img.shape[0],
                             size_bytes=os.path.getsize(path), lot_id=lot_id, sample_no=sample_no or "",
                             imported_at=now())
    else:
        image_id = row["id"]
        if arch and not row["archive_path"]:
            db.execute("UPDATE images SET archive_path = ? WHERE id = ?", (arch, image_id))
    job_id = db.insert("jobs", image_id=image_id, recipe_pk=recipe_pk, status="queued", priority=priority,
                       acquisition_json=json.dumps(acq, ensure_ascii=False), source=source, created_at=now())
    db.audit(actor, "image.import", "image", image_id, job_id=job_id, source=source, file=os.path.basename(path),
             sha256=sha, recipe_id=recipe["recipe_id"], recipe_version=recipe["version"])
    return dict(image_id=image_id, job_id=job_id)


# ---------------------------------------------------------------------------
# 子行程工作
# ---------------------------------------------------------------------------
def _init_worker():
    runtime.apply_limits(low_priority=True, cv_threads=1)


def run_analysis(payload):
    """子行程：分析並寫出結果 JSON；回傳 dict(ok, result | error)"""
    from ..core.pipeline import Recipe
    try:
        recipe = Recipe.from_dict(payload["recipe"])
        res, _ = analyze_image(payload["image_path"], recipe, calibration_root=payload["calibration_root"],
                               acquisition_record=payload["acquisition"], validated=payload.get("validated"),
                               models=payload.get("models"), gpu=payload.get("gpu", False))
        data = serialize.to_jsonable(res)
        if payload.get("result_path"):                            # 試跑不寫出結果檔
            os.makedirs(os.path.dirname(payload["result_path"]), exist_ok=True)
            serialize.dump(res, payload["result_path"])
        return dict(ok=True, result=data)
    except (ImageFormatError, CalibrationError) as e:
        return dict(ok=False, error=e.code)
    except Exception as e:                                        # noqa: BLE001
        return dict(ok=False, error="analysis_exception", detail=repr(e))


def image_path(img):
    """分析用的影像檔：優先使用封存檔，其次原始位置；都不存在時回傳 None"""
    for p in (img["archive_path"], img["original_path"]):
        if p and os.path.isfile(p):
            return p
    return None


def build_payload(settings, db, img, recipe_dict, acquisition_record, result_path):
    """分析子行程的輸入 (佇列工作與試跑共用)"""
    return dict(image_path=image_path(img) or img["original_path"], recipe=recipe_dict,
                calibration_root=settings.calibration_dir, acquisition=acquisition_record,
                validated=modules.validated_set(db), models=model_store.resolve(db, recipe_dict),
                gpu=bool(maintenance.get_settings(db)["gpu_inference"]), result_path=result_path)


def queue_reanalysis(db, items, actor, source="reanalyze"):
    """
    建立重新分析工作。items：[(image_id, recipe_pk)]；同一影像只建立一個工作。
    沿用該影像最近一次工作的拍攝參數。回傳 dict(job_ids, skipped=[檔名])，影像檔已不存在者略過。
    """
    job_ids, skipped, seen = [], [], set()
    for image_id, recipe_pk in items:
        if image_id in seen:
            continue
        seen.add(image_id)
        img = db.one("SELECT * FROM images WHERE id = ?", (image_id,))
        if img is None:
            continue
        if image_path(img) is None:
            skipped.append(img["file_name"])
            continue
        last = db.one("SELECT acquisition_json FROM jobs WHERE image_id = ? ORDER BY id DESC LIMIT 1", (image_id,))
        job_ids.append(db.insert("jobs", image_id=image_id, recipe_pk=recipe_pk, status="queued", priority=1,
                                 acquisition_json=last["acquisition_json"] if last else "{}", source=source,
                                 created_at=now()))
    return dict(job_ids=job_ids, skipped=skipped)


def summarize(result):
    """寫入 runs.summary_json 的精簡摘要 (清單畫面與趨勢用)"""
    out = dict(quality=result["quality"]["level"], judgment_reasons=result["judgment_reasons"], modules={})
    for m in result["modules"]:
        s = m["summary"] or {}
        keep = {k: v for k, v in s.items() if not isinstance(v, (list,)) and k != "traceback"}
        out["modules"][m["module_id"]] = dict(status=m["status"], judgment=m["judgment"], summary=keep)
    return out


# ---------------------------------------------------------------------------
# 佇列
# ---------------------------------------------------------------------------
class JobQueue:
    def __init__(self, settings, db_factory, workers=None, can_run=None, module_allowed=None):
        self.settings = settings
        self.can_run = can_run or (lambda: True)                 # 授權無效時暫停取件 (工作留在佇列)
        self.module_allowed = module_allowed or (lambda m: True)
        self.db_factory = db_factory          # 每個執行緒自己的 Database 由 factory 取得 (Database 本身執行緒安全)
        self.workers = workers or settings.workers or runtime.default_workers()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._pool = None
        self._inflight = {}
        self._lock = threading.Lock()

    @property
    def db(self):
        return self.db_factory()

    def recover(self):
        n = self.db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'").rowcount
        if n:
            log.info("recovered %d running jobs", n)
        return n

    def start(self):
        self.recover()
        self._pool = ProcessPoolExecutor(self.workers, initializer=_init_worker)
        self._thread = threading.Thread(target=self._loop, name="job-dispatcher", daemon=True)
        self._thread.start()

    def stop(self, wait=True):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        if self._pool:
            self._pool.shutdown(wait=wait, cancel_futures=True)

    def notify(self):
        self._wake.set()

    def _claim(self):
        db = self.db
        with db.transaction() as c:
            r = c.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY priority DESC, id LIMIT 1").fetchone()
            if r is None:
                return None
            c.execute("UPDATE jobs SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = ?",
                      (now(), r["id"]))
        return r["id"]

    def _payload(self, job_id):
        db = self.db
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        img = db.one("SELECT * FROM images WHERE id = ?", (job["image_id"],))
        store = RecipeStore(db)
        row = store.get(job["recipe_pk"])
        recipe = store.to_recipe(row)
        for m in recipe.modules:
            if m.enabled and not self.module_allowed(m.module_id):
                raise RecipeStoreError("module_not_licensed", m.module_id)
        day = time.strftime("%Y%m%d")
        return build_payload(self.settings, db, img, recipe.to_dict(), json.loads(job["acquisition_json"]),
                             os.path.join(self.settings.results_dir, day, f"job{job_id}.json"))

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                free = self.workers - len(self._inflight)
            if not self.can_run():
                free = 0
            started = 0
            for _ in range(max(free, 0)):
                job_id = self._claim()
                if job_id is None:
                    break
                try:
                    payload = self._payload(job_id)
                except (RecipeStoreError, OSError, KeyError) as e:
                    self._finish_failed(job_id, getattr(e, "code", "job_prepare_failed"), str(e), retry=False)
                    continue
                fut = self._pool.submit(run_analysis, payload)
                with self._lock:
                    self._inflight[job_id] = fut
                fut.add_done_callback(lambda f, j=job_id, p=payload: self._done(j, p, f))
                started += 1
            self._wake.wait(timeout=1.0 if not started else 0.2)
            self._wake.clear()

    def _done(self, job_id, payload, fut):
        with self._lock:
            self._inflight.pop(job_id, None)
        try:
            out = fut.result()
        except Exception as e:                                    # noqa: BLE001  子行程異常終止
            out = dict(ok=False, error="worker_crashed", detail=repr(e))
        try:
            if out["ok"]:
                self._record(job_id, payload, out["result"])
            else:
                self._finish_failed(job_id, out["error"], out.get("detail", ""))
        except Exception:                                         # noqa: BLE001
            log.exception("recording job %s failed", job_id)
            self._finish_failed(job_id, "record_failed", "", retry=False)
        self._wake.set()

    def _finish_failed(self, job_id, code, detail="", retry=True):
        db = self.db
        job = db.one("SELECT attempts FROM jobs WHERE id = ?", (job_id,))
        if retry and code in ("worker_crashed", "analysis_exception") and job and job["attempts"] < MAX_ATTEMPTS:
            db.execute("UPDATE jobs SET status = 'queued', error = ? WHERE id = ?", (code, job_id))
            return
        db.execute("UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                   (f"{code}{': ' + detail if detail else ''}"[:2000], now(), job_id))
        log.warning("job %s failed: %s %s", job_id, code, detail)

    def _record(self, job_id, payload, result):
        db = self.db
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        with db.transaction() as c:
            cur = c.execute(
                "INSERT INTO runs (job_id, image_id, recipe_pk, software_version, result_path, quality_level, "
                "reference_only, auto_judgment, final_judgment, summary_json, elapsed_s, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, job["image_id"], job["recipe_pk"], result["software_version"], payload["result_path"],
                 result["quality"]["level"], int(result["reference_only"]), result["judgment"], result["judgment"],
                 json.dumps(summarize(result), ensure_ascii=False), result["elapsed_s"], now()))
            run_id = cur.lastrowid
            for m in result["modules"]:
                c.execute("INSERT INTO module_results (run_id, module_id, module_version, status, judgment, "
                          "reasons_json, summary_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (run_id, m["module_id"], m["module_version"], m["status"], m["judgment"],
                           json.dumps(m["reasons"] + m["judgment_reasons"]),
                           json.dumps({k: v for k, v in (m["summary"] or {}).items() if k != "traceback"},
                                      ensure_ascii=False)))
            c.execute("UPDATE jobs SET status = 'done', finished_at = ?, error = '' WHERE id = ?", (now(), job_id))
        return run_id

    # ---- 管理 ----
    def cancel(self, job_id, actor):
        n = self.db.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status = 'queued'",
                            (now(), job_id)).rowcount
        if n:
            self.db.audit(actor, "job.cancel", "job", job_id)
        return bool(n)

    def cancel_queued(self, actor, source=None):
        """取消所有排隊中的工作 (可限定來源，例如重新分析)；回傳取消數量"""
        where, args = ("AND source = ?", [source]) if source else ("", [])
        n = self.db.execute(f"UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE status = 'queued' {where}",
                            (now(), *args)).rowcount
        if n:
            self.db.audit(actor, "job.cancel_all", "job", "", source=source or "", count=n)
        return n

    def retry(self, job_id, actor):
        n = self.db.execute("UPDATE jobs SET status = 'queued', attempts = 0, error = '' WHERE id = ? "
                            "AND status IN ('failed', 'cancelled')", (job_id,)).rowcount
        if n:
            self.db.audit(actor, "job.retry", "job", job_id)
            self.notify()
        return bool(n)

    def wait_idle(self, timeout=120):
        """測試與批次用：等待佇列清空"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = self.db.one("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued', 'running')")
            with self._lock:
                busy = len(self._inflight)
            if r["n"] == 0 and busy == 0:
                return True
            time.sleep(0.2)
        return False


# ---------------------------------------------------------------------------
# 試跑 (配方編輯器)：同步分析一張影像，不寫入紀錄；同時只允許一個
# ---------------------------------------------------------------------------
class TrialBusy(Exception):
    pass


class TrialRunner:
    def __init__(self, timeout_s=180):
        self.timeout_s = timeout_s
        self._pool = None
        self._busy = threading.Lock()

    def run(self, payload):
        """回傳 run_analysis 的輸出；已有試跑進行中時拋出 TrialBusy，逾時回傳 error=trial_timeout"""
        if not self._busy.acquire(blocking=False):
            raise TrialBusy()
        try:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(1, initializer=_init_worker)
            fut = self._pool.submit(run_analysis, payload)
            try:
                return fut.result(timeout=self.timeout_s)
            except FutureTimeout:
                self._kill()
                return dict(ok=False, error="trial_timeout")
            except Exception as e:                                # noqa: BLE001  子行程異常終止
                self._kill()
                return dict(ok=False, error="worker_crashed", detail=repr(e))
        finally:
            self._busy.release()

    def _kill(self):
        """中止卡住的試跑子行程並丟棄行程池 (下次試跑重新建立)"""
        pool, self._pool = self._pool, None
        if pool is None:
            return
        for p in list(getattr(pool, "_processes", {}).values()):
            try:
                p.terminate()
            except Exception:                                     # noqa: BLE001
                pass
        pool.shutdown(wait=False, cancel_futures=True)

    def stop(self):
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
