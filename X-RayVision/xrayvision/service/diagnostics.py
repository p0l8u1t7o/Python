"""
問題回報包 (規劃書第 13 節)

客戶對分析結果有疑慮時，將選定的分析紀錄連同原始影像、配方、版本、日誌打包成單一檔案，交給原廠重現。

檔案格式：
  - 未加密：ZIP (副檔名 .xrvdiag)
  - 加密：  "XRVENC1" + RSA-OAEP 加密的 AES-256 金鑰 + 分塊 AES-256-GCM 密文 (副檔名 .xrvdiag.enc)
  - 超過指定大小時分割為 .001、.002 …，重現工具依序合併
  - 全程串流寫入磁碟，不將整包載入記憶體
ZIP 內容：
  manifest.json      產品與軟體版本、匯出時間與人員、選項、系統資訊、每個檔案的 SHA-256
  description.txt    問題描述
  runs.json          分析紀錄 (影像、配方版本、判定、人工複判)
  results/run<id>.json   完整分析結果
  recipes/recipe<pk>.json 使用的配方版本
  images/<sha256>.*  原始影像 (可選)
  logs/*             對應時段的應用程式日誌
"""
import glob
import hashlib
import io
import json
import os
import platform
import re
import struct
import sys
import time
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .. import PRODUCT_NAME, __version__
from ..core import plugin
from ..store.db import now

MAGIC = b"XRVENC1\n"
CHUNK = 16 << 20
PUBLIC_KEY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keys", "diagnostics_public.pem")


class DiagnosticsError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def system_info():
    info = dict(platform=platform.platform(), machine=platform.machine(), processor=platform.processor(),
                cpu_count=os.cpu_count(), python=sys.version.split()[0])
    try:
        import cv2
        import numpy
        info.update(opencv=cv2.__version__, numpy=numpy.__version__)
    except ImportError:
        pass
    return info


class _Deid:
    """去識別化：以代號取代批號、樣品編號、檔名、人員、路徑"""

    def __init__(self, enabled):
        self.enabled = enabled
        self.maps = {}

    def code(self, kind, value, prefix):
        if not self.enabled or value in (None, ""):
            return value
        m = self.maps.setdefault(kind, {})
        if value not in m:
            m[value] = f"{prefix}{len(m) + 1:03d}"
        return m[value]

    def file(self, name):
        if not self.enabled or not name:
            return name
        return self.code("file", name, "IMG") + os.path.splitext(name)[1]


def _scrub_result(res, deid, file_code):
    if not deid.enabled:
        return res
    res = json.loads(json.dumps(res))
    res["image"]["path"] = file_code
    res["image"]["name"] = file_code
    acq = res.get("acquisition") or {}
    if acq.get("file"):
        acq["file"] = "sidecar"
    res.get("recipe", {})["name"] = {}
    return res


def _file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def export(settings, db, run_ids, actor, description="", include_images=True, deidentify=False, encrypt=False,
           split_mb=2048):
    """產生問題回報包；回傳 dict(files=[路徑…], sha256, size, name)"""
    run_ids = sorted({int(r) for r in run_ids})
    if not run_ids:
        raise DiagnosticsError("no_runs_selected")
    q = ",".join("?" * len(run_ids))
    runs = db.all(f"SELECT r.*, i.sha256, i.file_name, i.archive_path, i.original_path, i.sample_no, i.kind, "
                  f"l.lot_no, l.operator FROM runs r JOIN images i ON i.id = r.image_id "
                  f"LEFT JOIN lots l ON l.id = i.lot_id WHERE r.id IN ({q}) ORDER BY r.id", run_ids)
    if len(runs) != len(run_ids):
        raise DiagnosticsError("run_not_found")
    os.makedirs(settings.exports_dir, exist_ok=True)
    name = f"diag_{time.strftime('%Y%m%d_%H%M%S')}.xrvdiag"
    zpath = os.path.join(settings.exports_dir, name + ".tmp")
    deid = _Deid(deidentify)
    digests, run_rows, recipes, images_done = {}, [], {}, set()
    t_min = min(r["created_at"] for r in runs)
    t_max = max(r["created_at"] for r in runs)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        def put(arc, data):
            digests[arc] = hashlib.sha256(data).hexdigest()
            z.writestr(arc, data)

        for r in runs:
            fname = deid.file(r["file_name"])
            reviews = db.all("SELECT judgment, comment, reviewer, created_at FROM reviews WHERE run_id = ? "
                             "ORDER BY id", (r["id"],))
            for rv in reviews:
                rv["reviewer"] = deid.code("person", rv["reviewer"], "P")
            with open(r["result_path"], encoding="utf-8") as f:
                res = json.load(f)
            put(f"results/run{r['id']}.json",
                json.dumps(_scrub_result(res, deid, fname), ensure_ascii=False, indent=1).encode("utf-8"))
            recipes[r["recipe_pk"]] = db.one("SELECT recipe_id, version, status, body_json, released_at FROM recipes "
                                             "WHERE id = ?", (r["recipe_pk"],))
            img_entry = None
            if include_images:
                src = r["archive_path"] if r["archive_path"] and os.path.isfile(r["archive_path"]) else r["original_path"]
                if os.path.isfile(src):
                    img_entry = f"images/{r['sha256']}{os.path.splitext(src)[1].lower()}"
                    if img_entry not in images_done:
                        digests[img_entry] = _file_sha(src)
                        z.write(src, img_entry, compress_type=zipfile.ZIP_STORED)
                        images_done.add(img_entry)
            run_rows.append(dict(run_id=r["id"], created_at=r["created_at"], software_version=r["software_version"],
                                 recipe_pk=r["recipe_pk"], image_sha256=r["sha256"], image_file=fname,
                                 image_entry=img_entry, kind=r["kind"],
                                 lot_no=deid.code("lot", r["lot_no"], "LOT"),
                                 sample_no=deid.code("sample", r["sample_no"], "S"),
                                 operator=deid.code("person", r["operator"], "P"),
                                 quality_level=r["quality_level"], auto_judgment=r["auto_judgment"],
                                 final_judgment=r["final_judgment"], reviews=reviews,
                                 result_entry=f"results/run{r['id']}.json"))
        for pk, rc in recipes.items():
            body = json.loads(rc.pop("body_json"))
            if deidentify:
                body["name"] = {}
            put(f"recipes/recipe{pk}.json", json.dumps(dict(rc, body=body), ensure_ascii=False, indent=1).encode("utf-8"))
        put("runs.json", json.dumps(run_rows, ensure_ascii=False, indent=1).encode("utf-8"))
        put("description.txt", (description or "").encode("utf-8"))
        for arc, data in _logs(settings, t_min, t_max).items():
            put(arc, data)
        manifest = dict(format="xrvdiag/1", product=PRODUCT_NAME, software_version=__version__,
                        modules={k: v.version for k, v in plugin.available().items()},
                        created_at=now(), created_by=deid.code("person", actor, "P"),
                        options=dict(include_images=include_images, deidentify=deidentify, encrypt=encrypt),
                        run_ids=run_ids, system=system_info(), files=digests)
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    src = zpath
    if encrypt:
        name += ".enc"
        src = zpath + ".enc"
        encrypt_file(zpath, src)
        os.remove(zpath)
    sha, size = _file_sha(src), os.path.getsize(src)
    out = _split_file(src, os.path.join(settings.exports_dir, name), int(split_mb) << 20)
    options = dict(include_images=include_images, deidentify=deidentify, encrypt=encrypt)
    db.insert("diagnostic_exports", created_at=now(), actor=actor, file_name=name, sha256=sha,
              run_ids_json=json.dumps(run_ids), options_json=json.dumps(options))
    db.audit(actor, "diagnostics.export", "diagnostic_export", name, run_ids=run_ids, sha256=sha, **options)
    return dict(files=out, sha256=sha, size=size, name=name)


def _logs(settings, t_min, t_max):
    """對應時段 (前後各一天) 內有修改的日誌檔；每個檔最多取尾端 20 MB"""
    out = {}
    if not os.path.isdir(settings.logs_dir):
        return out
    lo = time.mktime(time.strptime(t_min, "%Y-%m-%dT%H:%M:%S")) - 86400
    hi = time.mktime(time.strptime(t_max, "%Y-%m-%dT%H:%M:%S")) + 86400
    for f in sorted(os.listdir(settings.logs_dir)):
        p = os.path.join(settings.logs_dir, f)
        if os.path.isfile(p) and os.path.getmtime(p) >= lo and os.path.getctime(p) <= hi:
            with open(p, "rb") as fh:
                data = fh.read()
            out[f"logs/{f}"] = data[-(20 << 20):]
    return out


def _split_file(src, dst, part_size):
    """不超過分割大小時更名為 dst；否則分割為 dst.001、dst.002 …"""
    if part_size <= 0 or os.path.getsize(src) <= part_size:
        os.replace(src, dst)
        return [dst]
    out = []
    with open(src, "rb") as f:
        for i, data in enumerate(iter(lambda: f.read(part_size), b""), 1):
            p = f"{dst}.{i:03d}"
            with open(p, "wb") as o:
                o.write(data)
            out.append(p)
    os.remove(src)
    return out


# ---------------------------------------------------------------------------
# 加密 / 解密
# ---------------------------------------------------------------------------
def _rsa_oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def encrypt_file(src, dst, public_key_path=PUBLIC_KEY):
    """分塊 AES-256-GCM (每塊獨立 nonce，並以序號做附加驗證資料)，金鑰以 RSA-OAEP 加密"""
    with open(public_key_path, "rb") as f:
        pub = serialization.load_pem_public_key(f.read())
    key = AESGCM.generate_key(bit_length=256)
    aes = AESGCM(key)
    base = os.urandom(8)
    ek = pub.encrypt(key, _rsa_oaep())
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(MAGIC + struct.pack(">H", len(ek)) + ek + base + struct.pack(">Q", os.path.getsize(src)))
        for i, chunk in enumerate(iter(lambda: fi.read(CHUNK), b"")):
            fo.write(aes.encrypt(base + struct.pack(">I", i), chunk, struct.pack(">I", i)))


def decrypt_bytes(blob, private_key_pem):
    if not blob.startswith(MAGIC):
        raise DiagnosticsError("not_encrypted_package")
    p = len(MAGIC)
    (n,) = struct.unpack(">H", blob[p:p + 2])
    p += 2
    ek = blob[p:p + n]
    p += n
    base = blob[p:p + 8]
    p += 8
    (total,) = struct.unpack(">Q", blob[p:p + 8])
    p += 8
    priv = serialization.load_pem_private_key(private_key_pem, password=None)
    aes = AESGCM(priv.decrypt(ek, _rsa_oaep()))
    out, i = [], 0
    while p < len(blob):
        size = min(CHUNK, total - i * CHUNK) + 16
        out.append(aes.decrypt(base + struct.pack(">I", i), blob[p:p + size], struct.pack(">I", i)))
        p += size
        i += 1
    data = b"".join(out)
    if len(data) != total:
        raise DiagnosticsError("corrupted_package")
    return data


def read_package(path, private_key_pem=None):
    """
    讀取問題回報包 (原廠端)：合併分割檔、解密 (需要時)、驗證 manifest 雜湊值。
    回傳 (zipfile.ZipFile, manifest)
    """
    blob = b"".join(open(p, "rb").read() for p in _parts(path))
    if blob.startswith(MAGIC):
        if private_key_pem is None:
            raise DiagnosticsError("private_key_required")
        blob = decrypt_bytes(blob, private_key_pem)
    z = zipfile.ZipFile(io.BytesIO(blob))
    manifest = json.loads(z.read("manifest.json"))
    bad = [k for k, h in manifest["files"].items() if hashlib.sha256(z.read(k)).hexdigest() != h]
    if bad:
        raise DiagnosticsError("hash_mismatch", ",".join(bad))
    return z, manifest


def _parts(path):
    if os.path.isfile(path):
        return [path]
    base = re.sub(r"\.\d{3}$", "", path)
    parts = sorted(glob.glob(glob.escape(base) + ".[0-9][0-9][0-9]"))
    if not parts:
        raise DiagnosticsError("package_not_found", path)
    return parts
