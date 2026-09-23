"""第 4 階段：軟體授權 (離線啟用、機器綁定、期限與寬限、模組授權、時間竄改、停用)"""
import json
import os
import time

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from conftest import synth_raw16
from xrayvision.config import Settings
from xrayvision.service import license as L
from xrayvision.service.api import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.path.join(ROOT, "tools", "keys", "license_private_DEV.pem")
pytestmark = pytest.mark.skipif(not os.path.isfile(KEY), reason="development license key not available")

HW = {"machine_guid": "guid-1", "bios_uuid": "uuid-1", "baseboard_serial": "bb-1", "cpu_id": "cpu-1"}


def vendor_key():
    return serialization.load_pem_private_key(open(KEY, "rb").read(), password=None)


def mgr(tmp_path, hw=HW, db=None):
    return L.LicenseManager(str(tmp_path / "data"), db, collector=lambda: dict(hw))


def test_request_issue_import_valid(tmp_path):
    m = mgr(tmp_path)
    assert m.status()["state"] == L.MISSING and not m.status()["analysis_allowed"]
    req = m.request()
    assert "guid-1" not in json.dumps(req)                                # 只含雜湊值，不含原始序號
    lic = L.issue(req, vendor_key(), "ACME Corp", days=365, grace_days=7, modules=["bump_alignment"])
    st = m.import_license(lic)
    assert st["state"] == L.VALID and st["analysis_allowed"] and st["customer"] == "ACME Corp"
    assert 363 <= st["days_left"] <= 365 and not st["warn"]
    assert m.module_allowed("bump_alignment") and not m.module_allowed("void")


def test_tampered_or_foreign_license_rejected(tmp_path):
    m = mgr(tmp_path)
    lic = L.issue(m.request(), vendor_key(), "ACME", days=30)
    bad = json.loads(json.dumps(lic))
    bad["payload"]["expires"] = "2099-01-01T00:00:00"                     # 竄改到期日
    with pytest.raises(L.LicenseError) as e:
        m.import_license(bad)
    assert e.value.code == "license_invalid"
    other = mgr(tmp_path / "other")                                      # 另一套安裝 (相同硬體也不行)
    with pytest.raises(L.LicenseError) as e:
        other.import_license(lic)
    assert e.value.code == "license_machine_mismatch"


def test_hardware_change_tolerance(tmp_path):
    m = mgr(tmp_path)
    lic = L.issue(m.request(), vendor_key(), "ACME", days=30)
    m.import_license(lic)
    one = dict(HW, cpu_id="cpu-NEW")                                     # 換一項：仍有效
    assert mgr(tmp_path, one).status()["state"] == L.VALID
    two = dict(HW, cpu_id="cpu-NEW", baseboard_serial="bb-NEW")          # 換兩項：視為不同電腦
    assert mgr(tmp_path, two).status()["state"] == L.MACHINE_MISMATCH


def test_expiry_warning_and_grace(tmp_path):
    m = mgr(tmp_path)
    req = m.request()
    past = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 40 * 86400))
    m.import_license(L.issue(req, vendor_key(), "ACME", days=50, starts=past))           # 剩約 10 天
    st = m.status()
    assert st["state"] == L.VALID and st["warn"] and 9 <= st["days_left"] <= 10
    m.import_license(L.issue(req, vendor_key(), "ACME", days=38, grace_days=7, starts=past))  # 過期 2 天，寬限 7 天
    st = m.status()
    assert st["state"] == L.GRACE and st["analysis_allowed"]
    m.import_license(L.issue(req, vendor_key(), "ACME", days=30, grace_days=3, starts=past))  # 過期 10 天
    st = m.status()
    assert st["state"] == L.EXPIRED and not st["analysis_allowed"]
    future = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 5 * 86400))
    m.import_license(L.issue(req, vendor_key(), "ACME", days=30, starts=future))
    assert m.status()["state"] == L.NOT_STARTED


def test_deactivation_proof(tmp_path):
    m = mgr(tmp_path)
    req = m.request()
    m.import_license(L.issue(req, vendor_key(), "ACME", days=30))
    proof = m.deactivate()
    assert m.status()["state"] == L.DEACTIVATED and not m.status()["analysis_allowed"]
    assert L.verify_deactivation(proof, req)
    proof["payload"]["license_id"] = "FORGED"
    assert not L.verify_deactivation(proof, req)


def test_api_enforcement_and_clock_tamper(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"))
    app = create_app(settings, workers=1, watch=False, hardware_collector=lambda: dict(HW))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "admin", "password": "Adm1nPass"})
        assert c.get("/api/auth/state").json()["license"]["state"] == "missing"
        b = json.load(open(os.path.join(ROOT, "recipes", "bump_alignment_default.json"), encoding="utf-8"))
        pk = c.post("/api/recipes", json={"body": b}).json()["id"]
        # 未啟用授權：不可發布 (模組未授權)、不可匯入
        r = c.post(f"/api/recipes/{pk}/release")
        assert r.status_code == 403 and r.json()["error"] == "module_not_licensed"
        p = synth_raw16(str(tmp_path / "a.tiff"), size=(300, 300))
        r = c.post("/api/imports/path", json={"paths": [p], "recipe_pk": pk})
        assert r.status_code == 403 and r.json()["error"] == "license_missing"
        # 下載申請檔 → 原廠簽發 → 匯入
        req = c.get("/api/license/request").json()
        lic = L.issue(req, vendor_key(), "ACME", days=365, modules=["*"])
        r = c.post("/api/license/import", files={"file": ("lic.xrvlic", json.dumps(lic).encode(), "application/json")})
        assert r.status_code == 200 and r.json()["state"] == "valid"
        assert c.post(f"/api/recipes/{pk}/release").status_code == 200
        out = c.post("/api/imports/path", json={"paths": [p], "recipe_pk": pk}).json()
        assert "job_id" in out[0]
        assert app.state.platform.queue.wait_idle(120)
        assert c.get("/api/runs").json()["total"] == 1
        # 資料庫中有未來時間的紀錄 (系統時間被調回去) → 暫停分析
        db = app.state.platform.db
        db.audit("x", "test.future", "", "", note="simulated")
        future = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 3 * 86400))
        db.execute("UPDATE runs SET created_at = ?", (future,))
        st = c.get("/api/license").json()
        assert st["state"] == "clock_tampered" and not st["analysis_allowed"]
        # 稽核紀錄
        actions = {a["action"] for a in c.get("/api/audit").json()}
        assert {"license.request", "license.import"} <= actions
