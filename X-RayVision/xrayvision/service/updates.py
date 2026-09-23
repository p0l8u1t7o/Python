"""
軟體更新與退版 (規劃書第 12 節) — 平台服務端

- 更新檔 (.xrvupd) 為 ZIP：manifest.json、manifest.sig (原廠 Ed25519 簽章)、payload/ (app/ 與選用的 python/)。
  manifest 記錄每個檔案的 SHA-256，驗證簽章後逐一比對，未經簽章或遭竄改的檔案無法安裝。
- 平台服務只負責「驗證並展開到新版本目錄」與「寫入請求」；停止服務、快照、切換、自我檢查、
  失敗退回由獨立的啟動器 (launcher/launcher.py) 執行，因為服務無法替換正在執行的自身。
- 開發環境 (未經啟動器執行，沒有 XRAYVISION_HOME) 不支援進版。
"""
import hashlib
import json
import os
import shutil
import time
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from .. import __version__
from ..store.db import now

PUBLIC_KEY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keys", "update_public.pem")
FORMAT = "xrv-update/1"


class UpdateError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def version_key(v):
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).split("."))


def home():
    return os.environ.get("XRAYVISION_HOME")


def _read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# 更新檔驗證與展開
# ---------------------------------------------------------------------------
def verify_package(path, public_key_path=PUBLIC_KEY):
    """驗證簽章與每個檔案的雜湊值；回傳 manifest"""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise UpdateError("update_package_invalid")
    with z:
        try:
            raw = z.read("manifest.json")
            sig = z.read("manifest.sig")
        except KeyError:
            raise UpdateError("update_package_invalid")
        pub = serialization.load_pem_public_key(open(public_key_path, "rb").read())
        try:
            pub.verify(sig, raw)
        except InvalidSignature:
            raise UpdateError("update_signature_invalid")
        m = json.loads(raw)
        if m.get("format") != FORMAT or m.get("product") != "xrayvision":
            raise UpdateError("update_package_invalid")
        names = set(z.namelist())
        for rel, digest in m["files"].items():
            arc = "payload/" + rel
            if arc not in names:
                raise UpdateError("update_file_missing", rel)
            h = hashlib.sha256()
            with z.open(arc) as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            if h.hexdigest() != digest:
                raise UpdateError("update_hash_mismatch", rel)
    return m


def check_compatible(m, current, license_ok):
    if not license_ok:
        raise UpdateError("update_license_required")
    if version_key(m["version"]) <= version_key(current):
        raise UpdateError("update_not_newer", f"{m['version']} <= {current}")
    if m.get("min_from_version") and version_key(current) < version_key(m["min_from_version"]):
        raise UpdateError("update_from_version_unsupported", f"{current} < {m['min_from_version']}")


def stage(path, install_home, current, license_ok, public_key_path=PUBLIC_KEY):
    """驗證並展開到 versions/<版本>/；未包含執行環境時沿用目前版本的 python/。回傳 manifest"""
    m = verify_package(path, public_key_path)
    check_compatible(m, current, license_ok)
    vdir = os.path.join(install_home, "versions", m["version"])
    tmp = vdir + ".staging"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with zipfile.ZipFile(path) as z:
        for rel in m["files"]:
            dst = os.path.join(tmp, *rel.split("/"))
            if not os.path.abspath(dst).startswith(os.path.abspath(tmp) + os.sep):
                raise UpdateError("update_package_invalid", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open("payload/" + rel) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
    if not m.get("runtime_included"):
        cur_py = os.path.join(install_home, "versions", current, "python")
        if os.path.isdir(cur_py):
            shutil.copytree(cur_py, os.path.join(tmp, "python"))
    _write_json(os.path.join(tmp, "version.json"), dict(version=m["version"], released_at=m.get("released_at"),
                                                        notes=m.get("notes", {}), staged_at=now()))
    if os.path.isdir(vdir):
        shutil.rmtree(vdir)
    os.replace(tmp, vdir)
    return m


# ---------------------------------------------------------------------------
# 請求與狀態 (與啟動器之間以檔案溝通)
# ---------------------------------------------------------------------------
def _updates_dir(data_dir):
    return os.path.join(data_dir, "updates")


def request(data_dir, action, version, actor):
    p = os.path.join(_updates_dir(data_dir), "requests", f"{time.strftime('%Y%m%d_%H%M%S')}_{action}.json")
    _write_json(p, dict(action=action, version=version, requested_by=actor, requested_at=now()))
    return p


def overview(data_dir, install_home):
    """目前版本、已安裝版本、可退回的版本、最近狀態與歷史"""
    cur = __version__
    installed, rollback_to = [], []
    if install_home:
        cur = (_read_json(os.path.join(install_home, "current.json"), {}) or {}).get("version", cur)
        root = os.path.join(install_home, "versions")
        if os.path.isdir(root):
            for v in sorted(os.listdir(root), key=version_key):
                meta = _read_json(os.path.join(root, v, "version.json"))
                if meta:
                    installed.append(meta)
        snaps = os.path.join(data_dir, "snapshots")
        if os.path.isdir(snaps):
            for n in sorted(os.listdir(snaps)):
                s = _read_json(os.path.join(snaps, n, "snapshot.json"))
                if s and s.get("to_version") == cur and any(i["version"] == s["from_version"] for i in installed):
                    rollback_to.append(dict(version=s["from_version"], snapshot_at=s["created_at"]))
    upd = _updates_dir(data_dir)
    return dict(current=cur, running=__version__, supported=bool(install_home), installed=installed,
                rollback_to=rollback_to, status=_read_json(os.path.join(upd, "status.json")),
                history=list(reversed(_read_json(os.path.join(upd, "history.json"), []) or []))[:50],
                pending=sorted(os.listdir(os.path.join(upd, "requests"))) if os.path.isdir(os.path.join(upd, "requests")) else [])
