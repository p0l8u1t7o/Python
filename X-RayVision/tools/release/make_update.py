"""
原廠端工具 (不隨產品發布)：產生更新檔 (.xrvupd)

  python tools/release/make_update.py --app <版本目錄的 app/> --version 0.2.0 --key <update 私鑰.pem>
        [--runtime <python/ 執行環境目錄>] [--min-from 0.1.0] [--notes-zh "…"] [--notes-en "…"] --out <檔案>

更新檔內容：
  manifest.json   格式、產品、版本、可升級的最低版本、發布日期、版本說明、每個檔案的 SHA-256
  manifest.sig    manifest.json 的 Ed25519 簽章
  payload/app/…       程式與前端 (必要)
  payload/python/…    執行環境 (選用；未包含時沿用目前版本的執行環境)
"""
import argparse
import hashlib
import json
import os
import sys
import time
import zipfile

from cryptography.hazmat.primitives import serialization

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules"}


def _walk(root, prefix):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            p = os.path.join(base, f)
            rel = prefix + "/" + os.path.relpath(p, root).replace("\\", "/")
            yield p, rel


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_update(app_dir, version, out, key_path, runtime_dir=None, min_from=None, notes=None):
    key = serialization.load_pem_private_key(open(key_path, "rb").read(), password=None)
    entries = list(_walk(app_dir, "app"))
    if runtime_dir:
        entries += list(_walk(runtime_dir, "python"))
    manifest = dict(format="xrv-update/1", product="xrayvision", version=version, min_from_version=min_from,
                    released_at=time.strftime("%Y-%m-%dT%H:%M:%S"), notes=notes or {},
                    runtime_included=bool(runtime_dir), files={rel: _sha(p) for p, rel in entries})
    raw = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("manifest.json", raw)
        z.writestr("manifest.sig", key.sign(raw))
        for p, rel in entries:
            z.write(p, "payload/" + rel)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runtime", default=None)
    ap.add_argument("--min-from", default=None)
    ap.add_argument("--notes-zh", default="")
    ap.add_argument("--notes-en", default="")
    a = ap.parse_args()
    m = build_update(a.app, a.version, a.out, a.key, a.runtime, a.min_from, {"zh-TW": a.notes_zh, "en": a.notes_en})
    print(f"update {m['version']}: {len(m['files'])} files, runtime {'included' if m['runtime_included'] else 'reused'} → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
