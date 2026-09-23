"""
第 4 階段：離線更新與退版 端到端測試 (真實啟動器 + 真實服務程序)

  - 安裝目錄 versions/0.1.0 啟動 → 網頁上傳 0.2.0 更新檔 → 啟動器進版、自我檢查通過
  - 升版後新增紀錄 → 退版回 0.1.0 → 升版後紀錄匯出封存檔、資料還原
  - 損壞的 0.3.0 (自我檢查不通過) → 自動退回 0.2.0
  - 竄改的更新檔 → 拒絕
"""
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "launcher"))
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))
KEYS = os.path.join(ROOT, "tools", "keys")
pytestmark = [pytest.mark.slow, pytest.mark.skipif(
    not (os.path.isfile(os.path.join(KEYS, "update_private_DEV.pem")) and os.path.isfile(os.path.join(KEYS, "license_private_DEV.pem"))),
    reason="development keys not available")]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_app(dst, version, break_selftest=False):
    """複製目前的程式成為指定版本的 app/ 目錄"""
    shutil.copytree(os.path.join(ROOT, "xrayvision"), os.path.join(dst, "xrayvision"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    init = os.path.join(dst, "xrayvision", "__init__.py")
    s = open(init, encoding="utf-8").read().replace('__version__ = "0.1.0"', f'__version__ = "{version}"')
    open(init, "w", encoding="utf-8").write(s)
    if break_selftest:
        p = os.path.join(dst, "xrayvision", "selftest", "expected.json")
        e = json.load(open(p))
        e["dx"] += 5.0
        json.dump(e, open(p, "w"))


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.cookie = ""

    def call(self, method, path, body=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", ctype)
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                sc = r.headers.get("Set-Cookie")
                if sc:
                    self.cookie = sc.split(";")[0]
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "null")

    def upload(self, path, url="/api/updates/upload"):
        boundary = "----xrvtest"
        data = open(path, "rb").read()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(path)}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        return self.call("POST", url, raw=body, ctype=f"multipart/form-data; boundary={boundary}")


def wait_version(c, version, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st, h = c.call("GET", "/api/health")
            if st == 200 and h["version"] == version:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def wait_status(data, action, timeout=300):
    p = os.path.join(data, "updates", "status.json")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s = json.load(open(p, encoding="utf-8"))
            if s.get("action") == action and s.get("state") in ("success", "failed"):
                return s
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise AssertionError("timeout waiting for launcher")


def test_update_and_rollback_end_to_end(tmp_path):
    import launcher as L
    from make_update import build_update
    from xrayvision.service import license as lic
    from cryptography.hazmat.primitives import serialization

    home, data, port = str(tmp_path / "home"), str(tmp_path / "data"), free_port()
    os.makedirs(os.path.join(home, "versions", "0.1.0", "app"))
    make_app(os.path.join(home, "versions", "0.1.0", "app"), "0.1.0")
    json.dump({"version": "0.1.0"}, open(os.path.join(home, "versions", "0.1.0", "version.json"), "w"))
    json.dump({"version": "0.1.0"}, open(os.path.join(home, "current.json"), "w"))
    cfg = dict(L.DEFAULT_CONFIG, data_dir=data, port=port, command=[sys.executable, "-m", "xrayvision", "serve",
               "--data", "{data_dir}", "--port", "{port}", "--workers", "1"], pythonpath="{version_dir}\\app",
               health_timeout_s=120)
    lz = L.Launcher(home, cfg)
    t = threading.Thread(target=lz.run, daemon=True)
    t.start()
    c = Client(port)
    try:
        assert wait_version(c, "0.1.0"), "0.1.0 did not start"
        st, _ = c.call("POST", "/api/auth/setup", {"username": "admin", "password": "Adm1nPass"})
        assert st == 200
        # 授權 (更新需要有效授權)
        st, req = c.call("GET", "/api/license/request")
        key = serialization.load_pem_private_key(open(os.path.join(KEYS, "license_private_DEV.pem"), "rb").read(), None)
        doc = lic.issue(req, key, "TEST", days=30)
        boundary = "----b"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"l.xrvlic\"\r\n\r\n").encode() + \
            json.dumps(doc).encode() + f"\r\n--{boundary}--\r\n".encode()
        st, r = c.call("POST", "/api/license/import", raw=body, ctype=f"multipart/form-data; boundary={boundary}")
        assert st == 200 and r["state"] == "valid", r

        # 竄改的更新檔 → 拒絕
        app2 = str(tmp_path / "app020")
        make_app(app2, "0.2.0")
        pkg = str(tmp_path / "u020.xrvupd")
        build_update(app2, "0.2.0", pkg, os.path.join(KEYS, "update_private_DEV.pem"), min_from="0.1.0")
        bad = str(tmp_path / "bad.xrvupd")
        with zipfile.ZipFile(pkg) as zi, zipfile.ZipFile(bad, "w") as zo:
            for n in zi.namelist():
                d = zi.read(n)
                if n == "payload/app/xrayvision/__init__.py":
                    d += b"\n# tampered\n"
                zo.writestr(n, d)
        st, r = c.upload(bad)
        assert st == 400 and r["error"] == "update_hash_mismatch", r

        # 進版 0.2.0
        st, r = c.upload(pkg)
        assert st == 200 and r["version"] == "0.2.0", r
        st, r = c.call("POST", "/api/updates/apply", {"version": "0.2.0"})
        assert st == 200, r
        s = wait_status(data, "update")
        assert s["state"] == "success", s
        assert wait_version(c, "0.2.0")
        c.cookie = ""
        c.call("POST", "/api/auth/login", {"username": "admin", "password": "Adm1nPass"})
        st, ov = c.call("GET", "/api/updates")
        assert ov["current"] == "0.2.0" and [r["version"] for r in ov["rollback_to"]] == ["0.1.0"]

        # 升版後新增紀錄 (配方草稿)
        b = json.load(open(os.path.join(ROOT, "recipes", "bump_alignment_default.json"), encoding="utf-8"))
        b["recipe_id"] = "after-upgrade"
        st, r = c.call("POST", "/api/recipes", {"body": b})
        assert st == 200

        # 損壞的 0.3.0：自我檢查失敗 → 自動退回 0.2.0
        app3 = str(tmp_path / "app030")
        make_app(app3, "0.3.0", break_selftest=True)
        pkg3 = str(tmp_path / "u030.xrvupd")
        build_update(app3, "0.3.0", pkg3, os.path.join(KEYS, "update_private_DEV.pem"))
        assert c.upload(pkg3)[0] == 200
        os.remove(os.path.join(data, "updates", "status.json"))
        c.call("POST", "/api/updates/apply", {"version": "0.3.0"})
        s = wait_status(data, "update")
        assert s["state"] == "failed" and s["restored"], s
        assert wait_version(c, "0.2.0")
        c.cookie = ""
        c.call("POST", "/api/auth/login", {"username": "admin", "password": "Adm1nPass"})
        st, recs = c.call("GET", "/api/recipes")
        assert any(r["recipe_id"] == "after-upgrade" for r in recs)           # 失敗退回不會遺失資料

        # 退版回 0.1.0
        os.remove(os.path.join(data, "updates", "status.json"))
        st, r = c.call("POST", "/api/updates/rollback", {"version": "0.1.0"})
        assert st == 200, r
        s = wait_status(data, "rollback")
        assert s["state"] == "success", s
        assert wait_version(c, "0.1.0")
        c.cookie = ""
        c.call("POST", "/api/auth/login", {"username": "admin", "password": "Adm1nPass"})
        st, recs = c.call("GET", "/api/recipes")
        assert not any(r["recipe_id"] == "after-upgrade" for r in recs)       # 還原為升版前快照
        st, arch = c.call("GET", "/api/rollback-archives")
        assert len(arch) == 1 and arch[0]["counts"]["recipes"] == 1 and not arch[0]["imported"]
        # 封存檔匯入：升版後的紀錄合併回來
        st, r = c.call("POST", f"/api/rollback-archives/{arch[0]['name']}/import")
        assert st == 200 and r["recipes"] == 1, r
        st, recs = c.call("GET", "/api/recipes")
        assert any(r["recipe_id"] == "after-upgrade" for r in recs)
        assert c.call("POST", f"/api/rollback-archives/{arch[0]['name']}/import")[1]["error"] == "archive_already_imported"
        hist = json.load(open(os.path.join(data, "updates", "history.json"), encoding="utf-8"))
        assert [h["result"] for h in hist] == ["success", "failed_rolled_back", "success"]
    finally:
        lz.stopping.set()
        t.join(timeout=60)
