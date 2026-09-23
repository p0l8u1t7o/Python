"""
原廠端工具 (不隨產品發布)：授權管理

  python tools/license_admin/license_admin.py keygen --out <資料夾>
      產生授權簽章金鑰組 (Ed25519)。私鑰須存放於離線環境並備份；公鑰替換 xrayvision/keys/license_public.pem。

  python tools/license_admin/license_admin.py inspect <申請檔.xrvreq>
      驗證申請檔的安裝金鑰簽章，顯示機器碼、安裝識別碼與產品版本。

  python tools/license_admin/license_admin.py issue <申請檔.xrvreq> --customer "客戶名稱" --days 365
        [--grace 7] [--modules bump_alignment,void | *] [--starts 2026-10-01] --key <私鑰.pem> [--out 授權檔.xrvlic]
      簽發授權檔，並附加一筆紀錄到 issued.jsonl (同資料夾)。續約時以同一份申請檔再簽發即可。

  python tools/license_admin/license_admin.py verify-deactivation <停用證明.xrvdeact> <原申請檔.xrvreq>
      以原申請檔中的安裝公鑰驗證停用證明 (授權移轉)。
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from xrayvision.service import license as L  # noqa: E402

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "issued.jsonl")


def cmd_keygen(a):
    os.makedirs(a.out, exist_ok=True)
    k = Ed25519PrivateKey.generate()
    priv = os.path.join(a.out, "license_private.pem")
    pub = os.path.join(a.out, "license_public.pem")
    if os.path.exists(priv):
        print(f"refusing to overwrite {priv}", file=sys.stderr)
        return 2
    open(priv, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    open(pub, "wb").write(k.public_key().public_bytes(serialization.Encoding.PEM,
                                                      serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"private key: {priv}\npublic key:  {pub}")
    return 0


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def cmd_inspect(a):
    req = _load(a.request)
    p = req["payload"]
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(L.unb64(p["install_public_key"])).verify(
            L.unb64(req["signature"]), L.canonical(p))
        ok = True
    except Exception:                                             # noqa: BLE001
        ok = False
    print(f"signature:       {'OK' if ok else 'INVALID'}")
    for k in ("product", "product_version", "install_id", "machine_code", "created_at"):
        print(f"{k + ':':<17}{p.get(k)}")
    print(f"machine items:   {', '.join(sorted(p.get('machine', {})))}")
    return 0 if ok else 1


def cmd_issue(a):
    req = _load(a.request)
    key = serialization.load_pem_private_key(open(a.key, "rb").read(), password=None)
    modules = ["*"] if a.modules.strip() == "*" else [m.strip() for m in a.modules.split(",") if m.strip()]
    starts = f"{a.starts}T00:00:00" if a.starts else None
    lic = L.issue(req, key, a.customer, days=a.days, grace_days=a.grace, modules=modules, starts=starts)
    p = lic["payload"]
    out = a.out or f"license_{p['license_id']}_{req['payload']['machine_code']}.xrvlic"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(lic, f, ensure_ascii=False, indent=1)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(issued_at=time.strftime("%Y-%m-%dT%H:%M:%S"), license_id=p["license_id"],
                                customer=p["customer"], install_id=p["install_id"],
                                machine_code=req["payload"]["machine_code"], starts=p["starts"],
                                expires=p["expires"], grace_days=p["grace_days"], modules=p["modules"]),
                           ensure_ascii=False) + "\n")
    print(f"license {p['license_id']} for {p['customer']}: {p['starts']} ~ {p['expires']} "
          f"(grace {p['grace_days']} days), modules {p['modules']}\n→ {out}")
    return 0


def cmd_verify_deactivation(a):
    ok = L.verify_deactivation(_load(a.proof), _load(a.request))
    p = _load(a.proof)["payload"]
    print(f"deactivation proof: {'VALID' if ok else 'INVALID'}  license {p.get('license_id')}  at {p.get('deactivated_at')}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="license administration (vendor only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("keygen")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_keygen)
    p = sub.add_parser("inspect")
    p.add_argument("request")
    p.set_defaults(func=cmd_inspect)
    p = sub.add_parser("issue")
    p.add_argument("request")
    p.add_argument("--customer", required=True)
    p.add_argument("--days", type=int, required=True)
    p.add_argument("--grace", type=int, default=0)
    p.add_argument("--modules", default="*")
    p.add_argument("--starts", default="")
    p.add_argument("--key", required=True)
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_issue)
    p = sub.add_parser("verify-deactivation")
    p.add_argument("proof")
    p.add_argument("request")
    p.set_defaults(func=cmd_verify_deactivation)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
