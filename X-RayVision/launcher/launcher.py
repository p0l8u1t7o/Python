"""
啟動器 (Windows 服務主程式)：啟動並監看目前版本的平台服務，執行進版與退版 (規劃書第 12 節)

只使用 Python 標準函式庫，與產品版本分開安裝，進版時不會被替換。

安裝目錄 (XRAYVISION_HOME)：
  launcher/launcher.py、launcher/launcher.json   本程式與設定
  versions/<版本>/                               各版本 (python/ 執行環境、app/ 程式與前端)
  current.json                                  {"version": "目前版本"}
資料目錄 (launcher.json 的 data_dir)：
  updates/requests/*.json    平台服務寫入的進版／退版請求
  updates/status.json        目前進度 (平台重新啟動後可讀取結果)
  updates/history.json       版本歷史
  snapshots/<時間>__<來源版本>__<目標版本>/   升版前快照 (資料庫、設定、授權、校正設定檔)
  rollback_archives/         退版時匯出的升版後紀錄

進版：停止服務 → 建立快照 → 切換版本 → 啟動 → 自我檢查 → 成功則完成；失敗則還原快照並切回原版本。
退版：停止服務 → 匯出快照之後的紀錄 → 還原快照 → 切換版本 → 啟動 → 自我檢查。

用法：
  python launcher.py run                 以前景方式執行 (由 Windows 服務呼叫)
  python launcher.py status              顯示目前版本與已安裝版本
"""
import json
import logging
import logging.handlers
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request

HOME = os.path.abspath(os.environ.get("XRAYVISION_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(HOME, "launcher", "launcher.json")

DEFAULT_CONFIG = dict(
    data_dir=r"C:\ProgramData\X-RayVision",
    port=8600,
    command=["{version_dir}\\python\\python.exe", "-m", "xrayvision", "serve", "--data", "{data_dir}",
             "--port", "{port}"],
    pythonpath="{version_dir}\\app",
    keep_versions=3,
    health_timeout_s=240,
    stop_timeout_s=30,
)

# 快照包含的資料目錄內項目 (影像封存與結果檔為只新增的檔案，不需快照)
SNAPSHOT_ITEMS = ("settings.json", "license", "calibration")

# 退版時匯出的資料表：(資料表, 時間欄位)；module_results 與 reviews 依所屬分析紀錄一併匯出
ARCHIVE_TABLES = (("recipes", "created_at"), ("lots", "created_at"), ("images", "imported_at"),
                  ("jobs", "created_at"), ("runs", "created_at"), ("audit_log", "ts"),
                  ("diagnostic_exports", "created_at"))

log = logging.getLogger("launcher")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _has_console():
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except (AttributeError, OSError):
        return False


def version_key(v):
    return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))


class Launcher:
    def __init__(self, home=HOME, cfg=None):
        self.home = home
        self.cfg = cfg or load_config()
        self.data = self.cfg["data_dir"]
        self.proc = None
        self.stopping = threading.Event()
        self.updates = os.path.join(self.data, "updates")
        os.makedirs(os.path.join(self.updates, "requests"), exist_ok=True)

    # ---- 版本 ----
    @property
    def current(self):
        return (read_json(os.path.join(self.home, "current.json"), {}) or {}).get("version")

    def set_current(self, version):
        write_json(os.path.join(self.home, "current.json"), dict(version=version, switched_at=now()))

    def version_dir(self, v):
        return os.path.join(self.home, "versions", v)

    def installed(self):
        root = os.path.join(self.home, "versions")
        if not os.path.isdir(root):
            return []
        return sorted((d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "version.json"))),
                      key=version_key)

    # ---- 服務程序 ----
    def _fmt(self, s, v):
        return s.format(version_dir=self.version_dir(v), data_dir=self.data, port=self.cfg["port"], home=self.home)

    def start_app(self):
        v = self.current
        if not v:
            raise RuntimeError("no current version")
        cmd = [self._fmt(c, v) for c in self.cfg["command"]]
        env = dict(os.environ, XRAYVISION_HOME=self.home, XRAYVISION_DATA=self.data, PYTHONUTF8="1")
        env["PYTHONPATH"] = self._fmt(self.cfg["pythonpath"], v)
        # 沿用本程式的主控台 (服務包裝程式提供隱藏主控台)，停止時才能送出 CTRL_BREAK 正常關閉；沒有主控台時才不開視窗
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if os.name == "nt" and not _has_console():
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("starting %s: %s", v, " ".join(cmd))
        self.proc = subprocess.Popen(cmd, env=env, cwd=self.version_dir(v), creationflags=flags)

    def stop_app(self):
        """先要求正常關閉 (服務會停止佇列與子行程)；逾時則結束整個行程樹"""
        p, self.proc = self.proc, None
        if p is None or p.poll() is not None:
            return
        log.info("stopping app pid %s", p.pid)
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                p.terminate()
            p.wait(self.cfg["stop_timeout_s"])
        except (subprocess.TimeoutExpired, OSError, ValueError):
            log.warning("graceful stop timed out; killing process tree %s", p.pid)
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                p.kill()
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                pass

    def health(self, expect_version, timeout=None):
        """自我檢查：服務回應、版本正確、內建標準影像分析結果與預期一致"""
        deadline = time.time() + (timeout or self.cfg["health_timeout_s"])
        url = f"http://127.0.0.1:{self.cfg['port']}/api/health?selftest=1"
        last = "no response"
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False, f"process exited ({self.proc.returncode})"
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    h = json.loads(r.read().decode("utf-8"))
                if h.get("version") != expect_version:
                    return False, f"version {h.get('version')} != {expect_version}"
                if h.get("selftest") != "pass":
                    return False, f"selftest {h.get('selftest')}: {h.get('selftest_detail', '')}"
                return True, "ok"
            except Exception as e:                                # noqa: BLE001  服務尚未就緒
                last = repr(e)
                time.sleep(1.0)
        return False, f"timeout: {last}"

    # ---- 快照 ----
    def snapshot(self, from_v, to_v):
        d = os.path.join(self.data, "snapshots", f"{time.strftime('%Y%m%d_%H%M%S')}__{from_v}__{to_v}")
        os.makedirs(d, exist_ok=True)
        db = os.path.join(self.data, "xrayvision.db")
        if os.path.isfile(db):
            src = sqlite3.connect(db)
            dst = sqlite3.connect(os.path.join(d, "xrayvision.db"))
            with dst:
                src.backup(dst)                                   # 線上備份，確保一致性
            src.close()
            dst.close()
        for item in SNAPSHOT_ITEMS:
            p = os.path.join(self.data, item)
            if os.path.isdir(p):
                shutil.copytree(p, os.path.join(d, item))
            elif os.path.isfile(p):
                shutil.copy2(p, os.path.join(d, item))
        write_json(os.path.join(d, "snapshot.json"), dict(created_at=now(), from_version=from_v, to_version=to_v))
        return d

    def snapshots(self):
        root = os.path.join(self.data, "snapshots")
        out = []
        if os.path.isdir(root):
            for n in sorted(os.listdir(root)):
                meta = read_json(os.path.join(root, n, "snapshot.json"))
                if meta:
                    out.append(dict(meta, path=os.path.join(root, n)))
        return out

    @staticmethod
    def _retry(fn, *args, attempts=20, delay=0.5):
        """Windows 上檔案剛被釋放時可能短暫仍被鎖定：重試幾次"""
        for i in range(attempts):
            try:
                return fn(*args)
            except PermissionError:
                if i == attempts - 1:
                    raise
                time.sleep(delay)

    def restore(self, snap_dir):
        db = os.path.join(self.data, "xrayvision.db")
        for suffix in ("-wal", "-shm"):
            if os.path.isfile(db + suffix):
                self._retry(os.remove, db + suffix)
        self._retry(shutil.copy2, os.path.join(snap_dir, "xrayvision.db"), db)
        for item in SNAPSHOT_ITEMS:
            src, dst = os.path.join(snap_dir, item), os.path.join(self.data, item)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            elif os.path.isfile(dst):
                os.remove(dst)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

    def export_since(self, since, label):
        """退版前：把快照時間之後新增的紀錄匯出為封存檔 (日後升版可再匯入)"""
        db = os.path.join(self.data, "xrayvision.db")
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        out = dict(format="xrv-rollback-archive/1", created_at=now(), since=since, from_version=label, tables={})
        for table, col in ARCHIVE_TABLES:
            try:
                out["tables"][table] = [dict(r) for r in con.execute(f"SELECT * FROM {table} WHERE {col} >= ?", (since,))]
            except sqlite3.OperationalError:
                out["tables"][table] = []
        run_ids = [r["id"] for r in out["tables"]["runs"]]
        for table in ("module_results", "reviews"):
            q = ",".join("?" * len(run_ids))
            out["tables"][table] = [dict(r) for r in con.execute(
                f"SELECT * FROM {table} WHERE run_id IN ({q})", run_ids)] if run_ids else []
        con.close()
        path = os.path.join(self.data, "rollback_archives", f"{time.strftime('%Y%m%d_%H%M%S')}_from-{label}.json")
        write_json(path, out)
        return path, {k: len(v) for k, v in out["tables"].items()}

    def audit(self, action, **detail):
        """直接寫入稽核紀錄 (服務停止期間)"""
        try:
            con = sqlite3.connect(os.path.join(self.data, "xrayvision.db"))
            with con:
                con.execute("INSERT INTO audit_log (ts, actor, action, target_type, target_id, detail_json) "
                            "VALUES (?, ?, ?, 'system', '', ?)",
                            (now(), detail.pop("actor", "launcher"), action, json.dumps(detail, ensure_ascii=False)))
            con.close()
        except sqlite3.Error as e:
            log.warning("audit failed: %s", e)

    # ---- 狀態與歷史 ----
    def status(self, **st):
        write_json(os.path.join(self.updates, "status.json"), dict(st, updated_at=now()))

    def history(self, **event):
        p = os.path.join(self.updates, "history.json")
        h = read_json(p, []) or []
        h.append(dict(event, at=now()))
        write_json(p, h[-200:])

    # ---- 進版 ----
    def apply_update(self, req):
        target, actor = req["version"], req.get("requested_by", "")
        cur = self.current
        if not os.path.isfile(os.path.join(self.version_dir(target), "version.json")):
            self.status(state="failed", action="update", version=target, reason="version_not_staged")
            return False
        self.status(state="running", action="update", version=target, from_version=cur, step="stopping")
        self.stop_app()
        self.status(state="running", action="update", version=target, from_version=cur, step="snapshot")
        snap = self.snapshot(cur, target)
        self.set_current(target)
        self.status(state="running", action="update", version=target, from_version=cur, step="health_check")
        self.start_app()
        ok, reason = self.health(target)
        if ok:
            self.history(action="update", from_version=cur, to_version=target, result="success", actor=actor,
                         snapshot=os.path.basename(snap))
            self.status(state="success", action="update", version=target, from_version=cur)
            self.prune()
            return True
        # 失敗：自動退回
        log.error("update to %s failed: %s", target, reason)
        self.stop_app()
        self.restore(snap)
        self.set_current(cur)
        self.start_app()
        ok2, reason2 = self.health(cur)
        self.audit("system.update_failed", actor=actor, target=target, reason=reason, restored=ok2)
        self.history(action="update", from_version=cur, to_version=target, result="failed_rolled_back",
                     reason=reason, actor=actor, restored_ok=ok2, restore_reason=reason2)
        self.status(state="failed", action="update", version=target, from_version=cur, reason=reason,
                    restored=ok2)
        return False

    # ---- 退版 ----
    def rollback(self, req):
        target, actor = req["version"], req.get("requested_by", "")
        cur = self.current
        snaps = [s for s in self.snapshots() if s["from_version"] == target and s["to_version"] == cur]
        if not snaps or not os.path.isdir(self.version_dir(target)):
            self.status(state="failed", action="rollback", version=target, reason="snapshot_not_found")
            return False
        snap = snaps[-1]
        self.status(state="running", action="rollback", version=target, from_version=cur, step="stopping")
        self.stop_app()
        self.status(state="running", action="rollback", version=target, from_version=cur, step="archive")
        archive, counts = self.export_since(snap["created_at"], cur)
        self.restore(snap["path"])
        self.set_current(target)
        self.audit("system.rollback", actor=actor, from_version=cur, to_version=target,
                   archive=os.path.basename(archive), archived=counts)
        self.status(state="running", action="rollback", version=target, from_version=cur, step="health_check")
        self.start_app()
        ok, reason = self.health(target)
        self.history(action="rollback", from_version=cur, to_version=target, result="success" if ok else "failed",
                     reason=reason, actor=actor, archive=os.path.basename(archive), archived=counts)
        self.status(state="success" if ok else "failed", action="rollback", version=target, from_version=cur,
                    reason=reason, archive=os.path.basename(archive))
        return ok

    def prune(self):
        """保留最近 keep_versions 個版本 (含目前版本)；刪除其餘版本與其快照"""
        keep = self.cfg["keep_versions"]
        vers = self.installed()
        cur = self.current
        old = [v for v in vers if v != cur][: max(0, len(vers) - keep)]
        for v in old:
            shutil.rmtree(self.version_dir(v), ignore_errors=True)
            for s in self.snapshots():
                if s["from_version"] == v:
                    shutil.rmtree(s["path"], ignore_errors=True)
            log.info("pruned version %s", v)

    # ---- 主迴圈 ----
    def handle_requests(self):
        d = os.path.join(self.updates, "requests")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            p = os.path.join(d, name)
            req = read_json(p)
            os.remove(p)
            if not req:
                continue
            log.info("request %s", req)
            try:
                if req.get("action") == "update":
                    self.apply_update(req)
                elif req.get("action") == "rollback":
                    self.rollback(req)
            except Exception as e:                                # noqa: BLE001
                log.exception("request failed")
                self.status(state="failed", action=req.get("action"), version=req.get("version"), reason=repr(e))
                if self.proc is None:
                    self.start_app()

    def run(self):
        crashes = []
        self.start_app()
        while not self.stopping.is_set():
            self.handle_requests()
            if self.proc is not None and self.proc.poll() is not None:
                crashes = [t for t in crashes if time.time() - t < 600] + [time.time()]
                delay = min(60, 2 ** len(crashes))
                log.error("app exited with %s; restarting in %ss", self.proc.returncode, delay)
                self.stopping.wait(delay)
                if not self.stopping.is_set():
                    self.start_app()
            self.stopping.wait(1.0)
        self.stop_app()


def setup_logging(data_dir):
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
    h = logging.handlers.RotatingFileHandler(os.path.join(data_dir, "logs", "launcher.log"), maxBytes=5 << 20,
                                             backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def main(argv=None):
    argv = argv or sys.argv[1:]
    cfg = load_config()
    lz = Launcher(HOME, cfg)
    if argv[:1] == ["status"]:
        print(json.dumps(dict(current=lz.current, installed=lz.installed(), home=HOME, data_dir=cfg["data_dir"]),
                         indent=1))
        return 0
    setup_logging(cfg["data_dir"])

    def _stop(*_):
        lz.stopping.set()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _stop)
    log.info("launcher started: home=%s data=%s", HOME, cfg["data_dir"])
    lz.run()
    log.info("launcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
