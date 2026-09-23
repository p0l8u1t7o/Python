"""
軟體授權 (規劃書第 11 節)

- 一台電腦一份授權：授權檔綁定機器碼；機器碼由多項硬體特徵的雜湊值組成，容許一項變更。
- 全程離線：產品產生「授權申請檔」→ 原廠以私鑰簽發「授權檔」→ 管理員於網頁匯入。
- 授權檔以 Ed25519 簽章，產品內只有公鑰，無法偽造或竄改。
- 訂閱制：到期後經過寬限天數 (授權檔指定) 即停止新的分析；檢視、報告、匯出與匯入續約授權仍可使用。
- 時間竄改防護：系統時間早於授權簽發時間，或早於資料庫中最新紀錄時間超過 24 小時，即暫停分析。
- 每套安裝首次啟動時產生安裝金鑰 (Ed25519)，用於申請檔與停用證明的簽章。
"""
import base64
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .. import __version__


PUBLIC_KEY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keys", "license_public.pem")
PRODUCT_CODE = "xrayvision"
FORMAT = "xrv-license/1"
CLOCK_TOLERANCE_S = 24 * 3600
WARN_DAYS = (30, 14, 7, 1)

# 授權狀態
VALID = "valid"                     # 有效
GRACE = "grace"                     # 已到期、寬限期內 (可分析，持續提醒)
EXPIRED = "expired"                 # 已到期且超過寬限期
MISSING = "missing"                 # 尚未啟用
INVALID = "invalid"                 # 簽章錯誤或格式不符
MACHINE_MISMATCH = "machine_mismatch"
NOT_STARTED = "not_started"
CLOCK_TAMPERED = "clock_tampered"
DEACTIVATED = "deactivated"
ANALYSIS_ALLOWED = (VALID, GRACE)


class LicenseError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


# ---------------------------------------------------------------------------
# 機器碼
# ---------------------------------------------------------------------------
def _ps(cmd):
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                             text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def collect_hardware():
    """原始硬體特徵 (不離開本機；只有雜湊值會寫入申請檔)"""
    comps = {}
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                comps["machine_guid"] = winreg.QueryValueEx(k, "MachineGuid")[0]
        except OSError:
            pass
        out = _ps("$c=Get-CimInstance Win32_ComputerSystemProduct; $b=Get-CimInstance Win32_BaseBoard; "
                  "$p=Get-CimInstance Win32_Processor | Select-Object -First 1; "
                  "Write-Output $c.UUID; Write-Output $b.SerialNumber; Write-Output $p.ProcessorId")
        vals = (out.splitlines() + ["", "", ""])[:3]
        for name, v in zip(("bios_uuid", "baseboard_serial", "cpu_id"), vals):
            comps[name] = v.strip()
    else:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.isfile(p):
                comps["machine_guid"] = open(p).read().strip()
                break
        comps["node"] = platform.node()
    # 空值或常見的預設值不列入 (部分主機板序號為 "To be filled by O.E.M.")
    bad = {"", "none", "default string", "to be filled by o.e.m.", "not applicable", "0", "ffffffff-ffff-ffff-ffff-ffffffffffff"}
    return {k: v for k, v in comps.items() if v and v.strip().lower() not in bad}


def fingerprint(raw):
    """硬體特徵 → 各項雜湊值 (加入產品代碼避免與其他軟體的機器碼相同)"""
    return {k: hashlib.sha256(f"{PRODUCT_CODE}:{k}:{v}".encode()).hexdigest()[:24] for k, v in sorted(raw.items())}


def machine_matches(licensed, current):
    """授權的機器碼與目前機器比對：可比對項目中最多允許一項不同，且至少兩項相同"""
    keys = set(licensed) & set(current)
    same = sum(licensed[k] == current[k] for k in keys)
    return same >= 2 and (len(set(licensed)) - same) <= 1


def machine_code(fp):
    """顯示用的機器碼 (各項雜湊值再雜湊，分段顯示)"""
    h = hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()[:20].upper()
    return "-".join(h[i:i + 5] for i in range(0, 20, 5))


# ---------------------------------------------------------------------------
# 簽章工具
# ---------------------------------------------------------------------------
def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def b64(b):
    return base64.b64encode(b).decode()


def unb64(s):
    return base64.b64decode(s)


def load_public(path_or_pem):
    pem = path_or_pem if isinstance(path_or_pem, bytes) else open(path_or_pem, "rb").read()
    return serialization.load_pem_public_key(pem)


def verify_signed(doc, public_key):
    try:
        public_key.verify(unb64(doc["signature"]), canonical(doc["payload"]))
        return True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 授權管理 (產品端)
# ---------------------------------------------------------------------------
class LicenseManager:
    def __init__(self, data_dir, db=None, collector=collect_hardware, public_key_path=PUBLIC_KEY):
        self.dir = os.path.join(data_dir, "license")
        os.makedirs(self.dir, exist_ok=True)
        self.db = db
        self.collector = collector
        self.public_key = load_public(public_key_path)
        self._fp = None
        self._install = None

    # ---- 安裝識別與金鑰 ----
    @property
    def install(self):
        if self._install is None:
            p = os.path.join(self.dir, "install.json")
            kp = os.path.join(self.dir, "install_key.pem")
            if not os.path.isfile(p) or not os.path.isfile(kp):
                key = Ed25519PrivateKey.generate()
                with open(kp, "wb") as f:
                    f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(dict(install_id=str(uuid.uuid4()), created_at=_now()), f)
            key = serialization.load_pem_private_key(open(kp, "rb").read(), password=None)
            info = json.load(open(p, encoding="utf-8"))
            self._install = dict(info, key=key, public_key=b64(key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)))
        return self._install

    @property
    def fp(self):
        if self._fp is None:
            self._fp = fingerprint(self.collector())
        return self._fp

    def _sign(self, payload):
        return dict(payload=payload, signature=b64(self.install["key"].sign(canonical(payload))))

    # ---- 申請檔 ----
    def request(self):
        payload = dict(format="xrv-license-request/1", product=PRODUCT_CODE, product_version=__version__,
                       install_id=self.install["install_id"], install_public_key=self.install["public_key"],
                       machine=self.fp, machine_code=machine_code(self.fp), created_at=_now())
        return self._sign(payload)

    # ---- 授權檔 ----
    @property
    def license_path(self):
        return os.path.join(self.dir, "license.json")

    def load(self):
        if not os.path.isfile(self.license_path):
            return None
        with open(self.license_path, encoding="utf-8") as f:
            return json.load(f)

    def check_document(self, doc):
        """檢查授權檔本身 (簽章、產品、機器、安裝識別)；回傳 (狀態, payload)"""
        if not isinstance(doc, dict) or not verify_signed(doc, self.public_key):
            return INVALID, None
        p = doc["payload"]
        if p.get("format") != FORMAT or p.get("product") != PRODUCT_CODE:
            return INVALID, p
        if p.get("install_id") != self.install["install_id"] or not machine_matches(p.get("machine", {}), self.fp):
            return MACHINE_MISMATCH, p
        return VALID, p

    def import_license(self, doc, actor="system"):
        """匯入授權檔 (續約時取代舊授權)；不合法時拋出 LicenseError"""
        state, p = self.check_document(doc)
        if state != VALID:
            raise LicenseError(f"license_{state}")
        if os.path.isfile(os.path.join(self.dir, "deactivated.json")):
            os.remove(os.path.join(self.dir, "deactivated.json"))
        with open(self.license_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        if self.db is not None:
            self.db.audit(actor, "license.import", "license", p["license_id"], customer=p.get("customer"),
                          expires=p.get("expires"), modules=p.get("modules"))
        return self.status()

    def deactivate(self, actor="system"):
        """停用授權並產生附安裝金鑰簽章的停用證明 (交給原廠辦理移轉)"""
        doc = self.load()
        if doc is None:
            raise LicenseError("license_missing")
        payload = dict(format="xrv-license-deactivation/1", product=PRODUCT_CODE,
                       license_id=doc["payload"]["license_id"], install_id=self.install["install_id"],
                       machine=self.fp, deactivated_at=_now())
        proof = self._sign(payload)
        with open(os.path.join(self.dir, "deactivated.json"), "w", encoding="utf-8") as f:
            json.dump(proof, f, ensure_ascii=False, indent=1)
        if self.db is not None:
            self.db.audit(actor, "license.deactivate", "license", payload["license_id"])
        return proof

    # ---- 狀態 ----
    def _latest_record_time(self):
        if self.db is None:
            return None
        r = self.db.one("SELECT MAX(t) AS t FROM (SELECT MAX(ts) AS t FROM audit_log "
                        "UNION ALL SELECT MAX(created_at) FROM runs)")
        return r["t"] if r else None

    def status(self):
        """回傳授權狀態 dict：state、analysis_allowed、到期資訊、可用模組、提醒"""
        base = dict(machine_code=machine_code(self.fp), install_id=self.install["install_id"])
        if os.path.isfile(os.path.join(self.dir, "deactivated.json")):
            return dict(base, state=DEACTIVATED, analysis_allowed=False)
        doc = self.load()
        if doc is None:
            return dict(base, state=MISSING, analysis_allowed=False)
        state, p = self.check_document(doc)
        info = dict(base, license_id=(p or {}).get("license_id"), customer=(p or {}).get("customer"),
                    starts=(p or {}).get("starts"), expires=(p or {}).get("expires"),
                    grace_days=(p or {}).get("grace_days", 0), modules=(p or {}).get("modules", []))
        if state != VALID:
            return dict(info, state=state, analysis_allowed=False)
        # 系統時間早於授權簽發時間、或早於資料庫最新紀錄時間超過容許值 → 疑似把時間調回去
        latest = self._latest_record_time()
        issued_ahead = _secs(p["issued_at"]) - time.time() > CLOCK_TOLERANCE_S
        records_ahead = bool(latest) and _secs(latest) - time.time() > CLOCK_TOLERANCE_S
        if issued_ahead or records_ahead:
            return dict(info, state=CLOCK_TAMPERED, analysis_allowed=False)
        if _now() < p["starts"]:
            return dict(info, state=NOT_STARTED, analysis_allowed=False)
        days_left = (_secs(p["expires"]) - time.time()) / 86400
        # 顯示用：未到期時無條件進位 (到期當天顯示 1 天)，已到期時為負的逾期天數
        info["days_left"] = math.ceil(days_left) if days_left >= 0 else -int((-days_left) // 1 + 1)
        if days_left >= 0:
            warn = next((d for d in WARN_DAYS if days_left <= d), None)
            return dict(info, state=VALID, analysis_allowed=True, warn=warn is not None)
        if -days_left <= p.get("grace_days", 0):
            return dict(info, state=GRACE, analysis_allowed=True, warn=True)
        return dict(info, state=EXPIRED, analysis_allowed=False, warn=True)

    def module_allowed(self, module_id):
        st = self.status()
        mods = st.get("modules") or []
        return "*" in mods or module_id in mods


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _secs(ts):
    return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


# ---------------------------------------------------------------------------
# 原廠端 (簽發)：tools/license_admin 使用；產品執行時不會呼叫
# ---------------------------------------------------------------------------
def issue(request_doc, private_key, customer, days, grace_days=0, modules=("*",), license_id=None, starts=None):
    """驗證申請檔的安裝金鑰簽章後簽發授權檔"""
    rp = request_doc["payload"]
    pub = Ed25519PublicKey.from_public_bytes(unb64(rp["install_public_key"]))
    try:
        pub.verify(unb64(request_doc["signature"]), canonical(rp))
    except (InvalidSignature, KeyError, ValueError):
        raise LicenseError("request_signature_invalid")
    if rp.get("product") != PRODUCT_CODE:
        raise LicenseError("request_wrong_product")
    t0 = time.time() if starts is None else _secs(starts)
    payload = dict(format=FORMAT, product=PRODUCT_CODE, license_id=license_id or str(uuid.uuid4())[:13].upper(),
                   customer=customer, install_id=rp["install_id"], machine=rp["machine"],
                   issued_at=_now(), starts=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
                   expires=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 + days * 86400)),
                   grace_days=int(grace_days), modules=list(modules))
    return dict(payload=payload, signature=b64(private_key.sign(canonical(payload))))


def verify_deactivation(proof, request_doc):
    """原廠端：以原申請檔中的安裝公鑰驗證停用證明"""
    pub = Ed25519PublicKey.from_public_bytes(unb64(request_doc["payload"]["install_public_key"]))
    try:
        pub.verify(unb64(proof["signature"]), canonical(proof["payload"]))
    except (InvalidSignature, KeyError, ValueError):
        return False
    return proof["payload"]["install_id"] == request_doc["payload"]["install_id"]
