"""
手動檢測工作區 (規劃書 PLAN-004 第 4 節)

- 每位使用者一個工作區：<資料目錄>/workspace/<帳號代碼>/
    workspace.json          影像清單、參數組 (與配方內容同格式)、帶入來源、各影像最近一次結果摘要
    images/<編號>_<檔名>     上傳的影像與同名拍攝參數檔 (從檢測紀錄加入者只記錄原始路徑，不複製)
    results/<編號>.json      最近一次分析結果；results/<編號>.overlay.jpg 疊圖 (匯出用)
- 不寫入 images／jobs／runs 資料表：總覽、紀錄、CSV 不會出現手動檢測結果。
- 上限：每人 50 張、上傳影像合計 2 GB；超過保留天數 (系統設定，預設 7 天) 未使用的工作區由維護工作清除。
"""
import copy
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid

from ..core import acquisition
from ..core.io import IMAGE_EXTENSIONS, ImageFormatError, load_image
from ..store.db import now

MAX_IMAGES = 50
MAX_BYTES = 2 * 1024 ** 3
MAX_PARAMS_BYTES = 1 << 20
SIDECAR_EXTENSIONS = (".json", ".txt", ".ini")
MANUAL_RECIPE_ID = "manual"

_locks, _locks_guard = {}, threading.Lock()


class WorkspaceError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def root_dir(settings):
    return os.path.join(settings.data_dir, "workspace")


def user_dir(settings, username):
    """帳號可能含檔名不允許的字元：以安全字元加雜湊當目錄名稱"""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", username)[:40]
    return os.path.join(root_dir(settings), f"{safe}-{hashlib.sha1(username.encode('utf-8')).hexdigest()[:8]}")


def params_hash(body):
    """參數組雜湊 (不含名稱等不影響分析的欄位)；結果以此判斷是否過期"""
    b = {k: v for k, v in (body or {}).items() if k not in ("recipe_id", "version", "name")}
    return hashlib.sha256(json.dumps(b, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def analysis_body(body):
    """分析用的配方內容：補上代碼與版本 (手動檢測不屬於任何配方)"""
    b = copy.deepcopy(body or {})
    b["recipe_id"] = MANUAL_RECIPE_ID
    b["version"] = 1
    b.setdefault("name", {})
    return b


class Workspace:
    def __init__(self, settings, username):
        self.settings = settings
        self.username = username
        self.dir = user_dir(settings, username)
        with _locks_guard:
            self.lock = _locks.setdefault(self.dir, threading.RLock())

    # ---- 讀寫 ----
    @property
    def manifest_path(self):
        return os.path.join(self.dir, "workspace.json")

    def load(self):
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return dict(params=None, source=None, images=[], next_id=1, updated_at=now())

    def save(self, data):
        os.makedirs(self.dir, exist_ok=True)
        data["updated_at"] = now()
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.manifest_path)

    def touch(self):
        """記錄使用時間 (保留天數由最後使用時間起算)"""
        with self.lock:
            if os.path.isfile(self.manifest_path):
                self.save(self.load())

    def view(self):
        """前端用：影像清單 (含結果摘要與是否過期)、參數組、來源、用量"""
        with self.lock:
            d = self.load()
        h = params_hash(d["params"]) if d["params"] else None
        images = []
        for it in d["images"]:
            r = it.get("result")
            images.append(dict({k: v for k, v in it.items() if k not in ("path", "result")},
                               available=os.path.isfile(it["path"]),
                               result=dict(r, stale=r.get("hash") != h) if r else None))
        return dict(params=d["params"], source=d["source"], images=images, params_hash=h,
                    usage=dict(images=len(d["images"]), bytes=self.upload_bytes(d), max_images=MAX_IMAGES,
                               max_bytes=MAX_BYTES),
                    updated_at=d["updated_at"])

    def upload_bytes(self, d=None):
        d = d or self.load()
        return sum(it.get("size_bytes", 0) for it in d["images"] if it["source"] == "upload")

    def item(self, item_id, d=None):
        d = d or self.load()
        for it in d["images"]:
            if it["id"] == item_id:
                return it
        raise WorkspaceError("workspace_image_not_found", item_id)

    # ---- 影像 ----
    def _check_room(self, d, add_bytes=0):
        if len(d["images"]) >= MAX_IMAGES:
            raise WorkspaceError("workspace_full", MAX_IMAGES)
        if self.upload_bytes(d) + add_bytes > MAX_BYTES:
            raise WorkspaceError("workspace_too_large", MAX_BYTES)

    def add_upload(self, name, fileobj, sidecars=None):
        """上傳影像 (fileobj 為可讀取的檔案物件)；sidecars：{檔名: bytes} 同名拍攝參數檔"""
        name = os.path.basename(name or "upload")
        if not name.lower().endswith(IMAGE_EXTENSIONS):
            raise WorkspaceError("unsupported_format", name)
        with self.lock:
            d = self.load()
            self._check_room(d)
            item_id = d["next_id"]
            img_dir = os.path.join(self.dir, "images")
            os.makedirs(img_dir, exist_ok=True)
            stem = f"{item_id}_{uuid.uuid4().hex[:6]}"
            dst = os.path.join(img_dir, f"{stem}_{name}")
            with open(dst, "wb") as fo:
                shutil.copyfileobj(fileobj, fo)
            size = os.path.getsize(dst)
            try:
                self._check_room(d, size)
                img = load_image(dst)
            except (WorkspaceError, ImageFormatError) as e:
                os.remove(dst)
                raise WorkspaceError(e.code, name)
            # 同名拍攝參數檔：與影像放在同一資料夾、同樣的主檔名，由 acquisition.collect 讀取
            base = os.path.splitext(dst)[0]
            for sname, data in (sidecars or {}).items():
                ext = os.path.splitext(sname)[1].lower()
                if ext in SIDECAR_EXTENSIONS and os.path.splitext(os.path.basename(sname))[0] == os.path.splitext(name)[0]:
                    with open(base + ext, "wb") as fo:
                        fo.write(data)
            acq = acquisition.collect(dst, None)
            it = dict(id=item_id, name=name, source="upload", path=dst, image_id=None, run_id=None,
                      kind=img.kind, width=img.shape[1], height=img.shape[0], size_bytes=size, acquisition=acq,
                      added_at=now(), result=None)
            d["images"].append(it)
            d["next_id"] = item_id + 1
            self.save(d)
            return it

    def add_from_run(self, db, run_id, path_of):
        """從檢測紀錄加入 (只參照原影像)；同一影像已在工作區時略過並回傳 None"""
        r = db.one("SELECT r.image_id, j.acquisition_json FROM runs r JOIN jobs j ON j.id = r.job_id WHERE r.id = ?",
                   (run_id,))
        if r is None:
            raise WorkspaceError("run_not_found", run_id)
        img = db.one("SELECT * FROM images WHERE id = ?", (r["image_id"],))
        path = path_of(img)
        if path is None:
            raise WorkspaceError("image_unavailable", img["file_name"])
        with self.lock:
            d = self.load()
            if any(it.get("image_id") == img["id"] for it in d["images"]):
                return None
            self._check_room(d)
            it = dict(id=d["next_id"], name=img["file_name"], source="run", path=path, image_id=img["id"],
                      run_id=run_id, kind=img["kind"], width=img["width"], height=img["height"],
                      size_bytes=img["size_bytes"], acquisition=json.loads(r["acquisition_json"] or "{}"),
                      added_at=now(), result=None)
            d["images"].append(it)
            d["next_id"] += 1
            self.save(d)
            return it

    def remove(self, item_id):
        with self.lock:
            d = self.load()
            it = self.item(item_id, d)
            d["images"] = [x for x in d["images"] if x["id"] != item_id]
            self.save(d)
        self._delete_files(it)

    def _delete_files(self, it):
        paths = [os.path.join(self.dir, "results", f"{it['id']}.json"),
                 os.path.join(self.dir, "results", f"{it['id']}.overlay.jpg")]
        if it["source"] == "upload":
            base = os.path.splitext(it["path"])[0]
            paths += [it["path"]] + [base + ext for ext in SIDECAR_EXTENSIONS]
        for p in paths:
            if os.path.abspath(p).startswith(os.path.abspath(self.dir) + os.sep) and os.path.isfile(p):
                os.remove(p)

    def clear(self):
        with self.lock:
            if os.path.isdir(self.dir):
                shutil.rmtree(self.dir, ignore_errors=True)

    # ---- 參數組 ----
    def set_params(self, body, source=None, keep_source=True):
        raw = json.dumps(body, ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_PARAMS_BYTES or not isinstance(body, dict):
            raise WorkspaceError("invalid_recipe", "params")
        with self.lock:
            d = self.load()
            d["params"] = body
            if source is not None or not keep_source:
                d["source"] = source
            self.save(d)
            return d

    # ---- 結果 ----
    def result_path(self, item_id):
        return os.path.join(self.dir, "results", f"{item_id}.json")

    def overlay_path(self, item_id):
        return os.path.join(self.dir, "results", f"{item_id}.overlay.jpg")

    def record_result(self, item_id, h, result):
        os.makedirs(os.path.join(self.dir, "results"), exist_ok=True)
        with open(self.result_path(item_id), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        with self.lock:
            d = self.load()
            it = self.item(item_id, d)
            it["result"] = dict(hash=h, judgment=result["judgment"], quality=result["quality"]["level"],
                                summary=_summary(result), elapsed_s=result["elapsed_s"], analyzed_at=now())
            self.save(d)
            return it["result"]

    def get_result(self, item_id):
        try:
            with open(self.result_path(item_id), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None


def _summary(result):
    """清單與結果總表用的精簡摘要 (與 runs.summary_json 相同格式)"""
    from .jobs import summarize
    return summarize(result)


def purge_stale(settings, days):
    """清除超過保留天數未使用的工作區；回傳清除數量"""
    root = root_dir(settings)
    if not days or not os.path.isdir(root):
        return 0
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
    n = 0
    for name in os.listdir(root):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        try:
            with open(os.path.join(d, "workspace.json"), encoding="utf-8") as f:
                updated = json.load(f).get("updated_at", "")
        except (OSError, ValueError):
            updated = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(d)))
        if updated < cutoff:
            with _locks_guard:
                lock = _locks.setdefault(d, threading.RLock())
            with lock:
                shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def disk_usage_bytes(settings):
    """所有工作區占用的空間 (儲存空間頁)"""
    total = 0
    for base, _dirs, files in os.walk(root_dir(settings)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total
