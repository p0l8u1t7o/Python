"""第 2 階段：資料庫、配方版本、工作佇列、判定、資料夾監看、API、問題回報包"""
import json
import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from conftest import synth_raw16
from xrayvision.config import Settings
from xrayvision.service import diagnostics
from xrayvision.service.api import create_app
from xrayvision.service.recipes import compatible

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def recipe_body(limit_px=5.0):
    with open(os.path.join(ROOT, "recipes", "bump_alignment_default.json"), encoding="utf-8") as f:
        b = json.load(f)
    b["recipe_id"] = "flipchip-a"
    b["modules"][0]["judgment"] = {"die_shift_max_px": limit_px}
    return b


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"))
    app = create_app(settings, workers=1, watch=False, enforce_license=False)
    with TestClient(app) as c:
        c.settings = settings
        c.platform = app.state.platform
        r = c.post("/api/auth/setup", json={"username": "tester", "display_name": "Tester", "password": "Passw0rd!"})
        assert r.status_code == 200, r.text
        yield c


def _released(client, limit_px=5.0):
    r = client.post("/api/recipes", json={"body": recipe_body(limit_px)})
    assert r.status_code == 200, r.text
    pk = r.json()["id"]
    r = client.post(f"/api/recipes/{pk}/release")
    assert r.status_code == 200 and r.json()["status"] == "released"
    return r.json()


def _wait(client):
    assert client.platform.queue.wait_idle(180)


def test_recipe_versioning_and_immutability(client):
    rel = _released(client)
    assert rel["body"]["modules"][0]["module_version"]                  # 發布時鎖定模組版本
    # 已發布版本不可修改
    r = client.put(f"/api/recipes/{rel['id']}", json={"body": recipe_body(1.0)})
    assert r.status_code == 409 and r.json()["error"] == "recipe_not_draft"
    with pytest.raises(sqlite3.IntegrityError):
        client.platform.db.execute("UPDATE recipes SET body_json = '{}' WHERE id = ?", (rel["id"],))
    # 新版本號自動遞增
    r = client.post("/api/recipes", json={"body": recipe_body(2.0)})
    assert r.json()["version"] == 2 and r.json()["status"] == "draft"
    # 不合法的配方參數
    bad = recipe_body()
    bad["modules"][0]["params"] = {"bump_level": 9}
    r = client.post("/api/recipes", json={"body": bad})
    assert r.status_code == 400 and r.json()["error"] == "invalid_param"
    lst = client.get("/api/recipes").json()
    assert lst[0]["latest_released"] == 1 and len(lst[0]["versions"]) == 2


def test_module_version_compatibility():
    assert compatible("1.1.0", "1.1.7")
    assert not compatible("1.0.0", "1.1.0")


def test_upload_analyze_judge_review_and_audit(client, tmp_path):
    rel = _released(client, limit_px=5.0)
    p = synth_raw16(str(tmp_path / "u1.tiff"), shift=(0.5, 0.0))
    with open(p, "rb") as f:
        r = client.post("/api/imports", files=[("files", ("u1.tiff", f, "image/tiff"))],
                        data={"recipe_pk": str(rel["id"]), "lot_no": "LOT-1", "acquisition": "kv=90,power_w=4"})
    assert r.status_code == 200 and "job_id" in r.json()[0], r.text
    _wait(client)
    runs = client.get("/api/runs").json()
    assert runs["total"] == 1
    run = runs["items"][0]
    assert run["final_judgment"] == "pass" and run["lot_no"] == "LOT-1" and run["recipe_version"] == 1
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["result"]["acquisition"]["params"]["tube_voltage_kv"] == 90.0
    assert detail["result"]["modules"][0]["judgment"] == "pass"
    img = client.get(f"/api/runs/{run['id']}/image?max_size=512")
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    # 人工複判
    r = client.post(f"/api/runs/{run['id']}/review", json={"judgment": "fail", "comment": "manual check"})
    assert r.status_code == 200
    run2 = client.get(f"/api/runs/{run['id']}").json()
    assert run2["run"]["final_judgment"] == "fail" and run2["run"]["auto_judgment"] == "pass"
    assert run2["reviews"][0]["reviewer"] == "tester"
    assert client.post(f"/api/runs/{run['id']}/review", json={"judgment": "maybe"}).status_code == 400
    # 稽核紀錄
    actions = [a["action"] for a in client.get("/api/audit").json()]
    for a in ("recipe.create_draft", "recipe.release", "image.import", "run.review"):
        assert a in actions
    with pytest.raises(sqlite3.IntegrityError):
        client.platform.db.execute("DELETE FROM audit_log")
    # 統計
    st = client.get("/api/stats?days=1").json()
    assert {t["judgment"]: t["n"] for t in st["totals"]} == {"fail": 1}


def test_draft_recipe_cannot_be_used(client, tmp_path):
    r = client.post("/api/recipes", json={"body": recipe_body()})
    p = synth_raw16(str(tmp_path / "d.tiff"), size=(300, 300))
    out = client.post("/api/imports/path", json={"paths": [p], "recipe_pk": r.json()["id"]}).json()
    assert out[0]["error"] == "recipe_not_released"


def test_watch_folder_imports_stable_new_files(client, tmp_path):
    rel = _released(client)
    watch = tmp_path / "equipment_out"
    (watch / "LOT-A").mkdir(parents=True)
    synth_raw16(str(watch / "LOT-A" / "old.tiff"), size=(300, 300))       # 既有檔案：預設略過
    r = client.post("/api/watch-folders", json={"path": str(watch), "recipe_id": rel["recipe_id"]})
    assert r.status_code == 200, r.text
    from xrayvision.ingest.watcher import FolderWatcher
    w = FolderWatcher(client.settings, lambda: client.platform.db, on_import=client.platform.queue.notify)
    synth_raw16(str(watch / "LOT-A" / "s01.tiff"))
    assert w.scan_all() == []                  # 第一次看到：等待檔案穩定
    jobs = w.scan_all()                        # 第二次：大小與時間未變 → 匯入
    assert len(jobs) == 1
    assert w.scan_all() == []                  # 不重複匯入
    _wait(client)
    runs = client.get("/api/runs").json()["items"]
    assert [(x["lot_no"], x["sample_no"], x["file_name"]) for x in runs] == [("LOT-A", "s01", "s01.tiff")]
    counts = client.get("/api/watch-folders").json()[0]["counts"]
    assert counts == {"imported": 1, "skipped": 1}
    # 原始檔未被移動或修改
    assert os.path.isfile(watch / "LOT-A" / "s01.tiff")


def test_crash_recovery_requeues_running_jobs(client, tmp_path):
    rel = _released(client)
    db = client.platform.db
    p = synth_raw16(str(tmp_path / "c.tiff"), size=(300, 300))
    client.platform.queue.stop()                                       # 停止佇列，模擬當機前的狀態
    out = client.post("/api/imports/path", json={"paths": [p], "recipe_pk": rel["id"]}).json()
    db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (out[0]["job_id"],))
    assert client.platform.queue.recover() == 1
    assert db.one("SELECT status FROM jobs WHERE id = ?", (out[0]["job_id"],))["status"] == "queued"


def test_diagnostic_package_roundtrip(client, tmp_path):
    rel = _released(client)
    paths = [synth_raw16(str(tmp_path / f"g{i}.tiff"), size=(450, 450), seed=i) for i in range(2)]
    client.post("/api/imports/path", json={"paths": paths, "recipe_pk": rel["id"], "lot_no": "SECRET-LOT"})
    _wait(client)
    ids = [r["id"] for r in client.get("/api/runs").json()["items"]]
    # 未加密、去識別化
    r = client.post("/api/diagnostics", json={"run_ids": ids, "description": "suspected miss", "deidentify": True})
    assert r.status_code == 200, r.text
    pkg = os.path.join(client.settings.exports_dir, r.json()["name"])
    z, man = diagnostics.read_package(pkg)
    runs = json.loads(z.read("runs.json"))
    assert {x["lot_no"] for x in runs} == {"LOT001"} and all(x["image_file"].startswith("IMG") for x in runs)
    assert "SECRET-LOT" not in json.dumps(runs) and z.read("description.txt") == b"suspected miss"
    assert len([n for n in z.namelist() if n.startswith("images/")]) == 2
    # 加密 + 分割
    r = client.post("/api/diagnostics", json={"run_ids": ids, "encrypt": True, "split_mb": 10})
    info = r.json()
    assert info["name"].endswith(".enc")
    first = os.path.join(client.settings.exports_dir, info["parts"][0])
    with pytest.raises(diagnostics.DiagnosticsError):
        diagnostics.read_package(first)                                 # 沒有私鑰無法開啟
    key = os.path.join(ROOT, "tools", "keys", "diagnostics_private_DEV.pem")
    if not os.path.isfile(key):
        pytest.skip("development private key not available")
    z, man = diagnostics.read_package(first, open(key, "rb").read())
    assert man["options"]["encrypt"] and len(man["run_ids"]) == 2
    # 原廠端重現：相同版本應得到相同結果
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools", "diag_replay"))
    from replay import replay
    rows = replay(first, key, str(tmp_path / "replay"))
    assert [x["status"] for x in rows] == ["same", "same"]
    assert client.get(f"/api/diagnostics/files/{info['parts'][0]}").status_code == 200
    assert client.get("/api/diagnostics/files/..%2Fxrayvision.db").status_code in (400, 404)


def test_runs_csv_export(client, tmp_path):
    rel = _released(client)
    p = synth_raw16(str(tmp_path / "csv.tiff"), size=(450, 450))
    client.post("/api/imports/path", json={"paths": [p], "recipe_pk": rel["id"], "lot_no": "L9"})
    _wait(client)
    r = client.get("/api/runs/export.csv?locale=zh-TW")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("id,created_at,lot_no") and len(lines) == 2 and ",L9," in lines[1]
    assert "合格" in lines[1]


def test_system_modules_i18n(client):
    s = client.get("/api/system").json()
    assert s["modules"]["bump_alignment"] and s["schema_version"] >= 2
    mods = client.get("/api/modules").json()
    assert mods[0]["judgment_params"][0]["key"] == "die_shift_max_um"
    assert mods[0]["overlay_styles"]["bump"]["color"] == "#ff0000"            # BGR (0,0,255) → 紅色
    assert mods[0]["summary_vector"] == "die_shift"
    assert client.get("/api/i18n/zh-TW").json()["status.ok"] == "完成"
    assert client.get("/api/i18n/xx").status_code == 404
