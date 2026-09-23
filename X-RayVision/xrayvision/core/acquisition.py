"""
拍攝參數 (成像條件對策第五層)

來源 (依序)：
  1. 手動輸入 (批次建立時由操作員填寫，或命令列 --acq)
  2. 影像旁的參數檔：<影像名>.json，或 <影像名>.txt / .ini (每行 key=value 或 key: value)
     設備實際匯出格式尚待確認 (規劃書 Q1)，此處以通用格式與鍵名別名對應支援。
參數寫入分析結果；配方可設定允許範圍，超出時品質閘門提出警告。
"""
import json
import os
import re

# 標準鍵名 → 可接受的別名 (比對時忽略大小寫、空白、底線、單位括號)
ALIASES = {
    "tube_voltage_kv": ("kv", "voltage", "tubevoltage", "tubevoltagekv", "kvp"),
    "tube_current_ua": ("ua", "µa", "current", "tubecurrent", "tubecurrentua"),
    "tube_power_w": ("watt", "power", "tubepower", "tubepowerw", "powerw"),
    "exposure_ms": ("exposure", "exposurems", "exposuretime", "integrationtime"),
    "frames": ("frames", "frameaverage", "averaging", "integration", "avg", "framecount"),
    "tube_mode": ("mode", "tubemode", "focusmode"),
    "magnification": ("magnification", "geometricmagnification", "mag"),
    "view_angle_deg": ("viewangle", "tilt", "tiltangle", "obliqueangle", "angle"),
}
_LOOKUP = {a: k for k, al in ALIASES.items() for a in al}
_LOOKUP.update({k.replace("_", ""): k for k in ALIASES})


def _norm_key(k):
    k = re.sub(r"\(.*?\)|\[.*?\]", "", str(k)).strip().lower()
    return re.sub(r"[\s_\-]", "", k)


def normalize(raw):
    """將任意鍵名的參數字典轉為標準鍵名；無法辨識的鍵保留在 extra"""
    out, extra = {}, {}
    for k, v in raw.items():
        std = _LOOKUP.get(_norm_key(k))
        val = _num(v)
        if std:
            out[std] = val
        else:
            extra[str(k)] = val
    if extra:
        out["extra"] = extra
    return out


def _num(v):
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    m = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)\s*[a-zA-Zµ%]*", s)
    return float(m.group(1)) if m else s


def find_sidecar(image_path):
    stem = os.path.splitext(image_path)[0]
    for ext in (".json", ".txt", ".ini"):
        p = stem + ext
        if os.path.isfile(p):
            return p
    return None


def read_sidecar(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    raw = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", ";", "[")):
                continue
            m = re.match(r"([^=:]+)[=:](.*)", line)
            if m:
                raw[m.group(1).strip()] = m.group(2).strip()
    return raw


def collect(image_path, manual=None):
    """回傳 dict(source=manual|sidecar|none, file=參數檔路徑, params=標準化參數)"""
    if manual:
        return dict(source="manual", file=None, params=normalize(manual))
    p = find_sidecar(image_path)
    if p:
        try:
            return dict(source="sidecar", file=p, params=normalize(read_sidecar(p)))
        except (OSError, ValueError):
            return dict(source="sidecar_unreadable", file=p, params={})
    return dict(source="none", file=None, params={})


def parse_manual(text):
    """命令列格式 "kv=90,power_w=5,frames=8" → dict"""
    out = {}
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def limit_checks(params, limits):
    """配方允許範圍 {標準鍵: [下限, 上限]}；超出時為 warn。回傳 checks 清單"""
    checks = []
    for k, (lo, hi) in (limits or {}).items():
        v = params.get(k)
        if not isinstance(v, (int, float)):
            continue
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        checks.append(dict(metric=f"acquisition.{k}", value=v, level="pass" if ok else "warn",
                           rule=dict(metric=f"acquisition.{k}", warn_below=lo, warn_above=hi)))
    return checks
