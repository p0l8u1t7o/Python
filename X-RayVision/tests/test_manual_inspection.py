"""PLAN-004：檢測區域「視為一個陣列」、手動檢測工作區、本影像自訂檢測區域"""
import io
import json
import zipfile

import cv2
import pytest

from test_iteration import _upload
from test_service import _released, _wait, client, recipe_body  # noqa: F401  (client 為 fixture)

from conftest import synth_absorption, synth_raw16, to_intensity
from xrayvision.core import regions as R
from xrayvision.core.pipeline import Recipe, analyze_image


# ---------------------------------------------------------------------------
# A　區域格式與「視為一個陣列」
# ---------------------------------------------------------------------------
def test_region_label_and_as_array_format():
    n = R.normalize(dict(reference=dict(width=100, height=100),
                         include=[dict(type="rect", x0=0, y0=0, x1=50, y1=50, label=" A ", as_array=True),
                                  dict(type="rect", x0=50, y0=0, x1=100, y1=50, as_array=False, label="")]))
    assert n["include"][0] == dict(type="rect", x0=0.0, y0=0.0, x1=50.0, y1=50.0, label="A", as_array=True)
    assert n["include"][1] == dict(type="rect", x0=50.0, y0=0.0, x1=100.0, y1=50.0)          # 未設定時維持舊格式
    for bad in (dict(exclude=[dict(type="rect", x0=0, y0=0, x1=5, y1=5, as_array=True)]),     # 排除區域不可勾選
                dict(include=[dict(type="rect", x0=0, y0=0, x1=5, y1=5, label="x" * 33)]),
                dict(include=[dict(type="rect", x0=0, y0=0, x1=5, y1=5, as_array="yes")])):
        with pytest.raises(R.RegionError):
            R.normalize(dict(reference=dict(width=10, height=10), **bad))
    # 重疊時屬於較後面的區域
    g = R.build_groups(R.normalize(dict(reference=dict(width=100, height=100), include=[
        dict(type="rect", x0=0, y0=0, x1=60, y1=100, as_array=True),
        dict(type="rect", x0=40, y0=0, x1=100, y1=100, as_array=True)])), (100, 100))
    assert R.group_at(g, 10, 50) == 1 and R.group_at(g, 50, 50) == 2 and R.group_at(g, 90, 50) == 2
    assert R.build_groups(None, (10, 10)) is None and R.group_at(None, 1, 1) == 0


def test_as_array_splits_adjacent_arrays(tmp_path):
    """左右兩半偏移方向相反、間距相同：自動分群併成一個陣列；以兩個區域強制拆開後各自估計"""
    A = synth_absorption(shift=(1.0, 0.0))
    A[:, 495:] = synth_absorption(shift=(-1.0, 0.0))[:, 495:]
    p = str(tmp_path / "two.tiff")
    cv2.imwrite(p, to_intensity(A))
    body = dict(recipe_id="b", version=1, name={}, modules=[dict(module_id="bump_alignment", params={})])
    auto, _ = analyze_image(p, Recipe.from_dict(body))
    assert len(auto.modules[0].groups) == 1 and auto.modules[0].groups[0].source == "auto"
    reg = dict(reference=dict(width=900, height=900), include=[
        dict(type="rect", x0=0, y0=0, x1=495, y1=900, as_array=True, label="L"),
        dict(type="rect", x0=495, y0=0, x1=900, y1=900, as_array=True, label="R")])
    res, _ = analyze_image(p, Recipe.from_dict(dict(body, regions=reg)))
    gs = res.modules[0].groups
    assert [(g.source, g.label) for g in gs] == [("region", "L"), ("region", "R")]
    assert gs[0].estimate["dx"] > 0.2 and gs[1].estimate["dx"] < -0.2
    assert sum(g.size for g in gs) == auto.modules[0].groups[0].size
    # 區域內可用位點不足：陣列沒有估計並標示原因
    tiny = dict(reference=dict(width=900, height=900), include=[
        dict(type="rect", x0=0, y0=0, x1=900, y1=900),
        dict(type="rect", x0=60, y0=60, x1=130, y1=130, as_array=True)])
    res, _ = analyze_image(p, Recipe.from_dict(dict(body, regions=tiny)))
    forced = [g for g in res.modules[0].groups if g.source == "region"]
    assert len(forced) == 1 and forced[0].estimate is None
    assert f"region_array_insufficient_sites:group{forced[0].id}" in res.modules[0].reasons


def test_regions_without_as_array_unchanged(tmp_path):
    p = synth_raw16(str(tmp_path / "b.tiff"), shift=(0.5, 0.0))
    body = dict(recipe_id="b", version=1, name={}, modules=[dict(module_id="bump_alignment", params={})])
    reg = dict(reference=dict(width=900, height=900), include=[dict(type="rect", x0=0, y0=0, x1=900, y1=450)])
    a, _ = analyze_image(p, Recipe.from_dict(dict(body, regions=reg)))
    reg["include"][0]["label"] = "top"
    b, _ = analyze_image(p, Recipe.from_dict(dict(body, regions=reg)))
    assert a.modules[0].summary["die_shift"] == b.modules[0].summary["die_shift"]
    assert all(g.source == "auto" for g in b.modules[0].groups)


# ---------------------------------------------------------------------------
# B　手動檢測工作區
# ---------------------------------------------------------------------------
def _ws_upload(client, tmp_path, names, sidecar=None):
    files = []
    for i, n in enumerate(names):
        p = synth_raw16(str(tmp_path / n), shift=(0.4 + 0.2 * i, 0.0), seed=i + 3)
        files.append(("files", (n, open(p, "rb"), "image/tiff")))
    if sidecar:
        files.append(("files", (sidecar[0], io.BytesIO(sidecar[1].encode()), "application/json")))
    r = client.post("/api/workspace/images", files=files)
    for _, (_, fh, _) in files:
        fh.close()
    assert r.status_code == 200, r.text
    return r.json()


def test_workspace_upload_analyze_switch_and_no_records(client, tmp_path):
    before = client.get("/api/stats").json()
    up = _ws_upload(client, tmp_path, ["m1.tiff", "m2.tiff"], sidecar=("m1.json", json.dumps({"kv": 90})))
    assert len(up["added"]) == 2 and up["errors"] == []
    tpl = client.get("/api/recipe-template/bump_alignment").json()
    assert client.put("/api/workspace/params", json={"body": tpl}).status_code == 200
    ws = client.get("/api/workspace").json()
    a, b = ws["images"]
    assert a["acquisition"]["params"].get("tube_voltage_kv") == 90 and a["result"] is None

    r = client.post(f"/api/workspace/images/{a['id']}/analyze", json={})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["manual"] is True and res["recipe"]["recipe_id"] == "manual"
    # 改參數：結果過期；分析時一併送出參數
    tpl["modules"][0]["judgment"] = {"die_shift_max_px": 0.01}
    ws = client.get("/api/workspace").json()
    assert ws["images"][0]["result"]["stale"] is False
    r = client.post(f"/api/workspace/images/{b['id']}/analyze", json={"body": tpl})
    assert r.status_code == 200 and r.json()["result"]["judgment"] == "fail"
    ws = client.get("/api/workspace").json()
    assert ws["images"][0]["result"]["stale"] is True and ws["images"][1]["result"]["stale"] is False

    # 分析全部：只分析過期的影像
    r = client.post("/api/workspace/analyze-all", json={})
    assert r.json()["total"] == 1
    for _ in range(300):
        st = client.get("/api/workspace").json()
        if st["batch"] and not st["batch"]["running"]:
            break
        import time
        time.sleep(0.1)
    assert st["batch"]["done"] == 1 and st["batch"]["failed"] == 0
    assert all(i["result"] and not i["result"]["stale"] for i in st["images"])
    assert client.get(f"/api/workspace/images/{a['id']}/result").json()["judgment"] == "fail"
    assert client.get(f"/api/workspace/images/{a['id']}/image", params={"max_size": 512}).status_code == 200

    # 不寫入正式紀錄
    assert client.get("/api/runs").json()["total"] == 0
    assert client.get("/api/stats").json() == before

    # 匯出
    r = client.get("/api/workspace/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README.txt", "params.json", "summary.csv", "results/m1.json", "overlays/m1.jpg"} <= names

    # 移除與清空
    assert client.delete(f"/api/workspace/images/{b['id']}").status_code == 200
    assert len(client.get("/api/workspace").json()["images"]) == 1
    assert client.delete("/api/workspace").status_code == 200
    assert client.get("/api/workspace").json()["images"] == []
    acts = [x["action"] for x in client.get("/api/audit").json()]
    assert {"workspace.add_images", "workspace.analyze", "workspace.analyze_all", "workspace.export",
            "workspace.clear"} <= set(acts)


def test_workspace_same_result_as_formal_analysis(client, tmp_path):
    rel = _released(client)
    _upload(client, tmp_path, rel, ["f.tiff"])
    run = client.get("/api/runs").json()["items"][0]
    r = client.post("/api/workspace/images/from-runs", json={"run_ids": [run["id"], run["id"]]})
    assert r.json()["added"] and r.json()["skipped"] == 1                    # 同一影像不重複加入
    src = client.post("/api/workspace/params/from-recipe", json={"recipe_pk": rel["id"]}).json()
    assert src["source"]["recipe_id"] == rel["recipe_id"]
    it = client.get("/api/workspace").json()["images"][0]
    res = client.post(f"/api/workspace/images/{it['id']}/analyze", json={}).json()["result"]
    formal = client.get(f"/api/runs/{run['id']}").json()["result"]
    assert res["judgment"] == formal["judgment"]
    assert res["modules"][0]["summary"]["die_shift"] == formal["modules"][0]["summary"]["die_shift"]

    # 另存：來源配方的下一版草稿；已有草稿時需確認覆寫
    body = client.get("/api/workspace").json()["params"]
    body["modules"][0]["params"]["pad_level"] = 0.3
    client.put("/api/workspace/params", json={"body": body})
    d = client.post("/api/workspace/save-recipe", json={"mode": "revise"})
    assert d.status_code == 200 and d.json()["version"] == 2 and d.json()["status"] == "draft"
    assert d.json()["body"]["modules"][0]["params"]["pad_level"] == 0.3
    r = client.post("/api/workspace/save-recipe", json={"mode": "revise"})
    assert r.status_code == 409 and r.json()["error"] == "draft_exists"
    r = client.post("/api/workspace/save-recipe", json={"mode": "revise", "overwrite_draft": True})
    assert r.status_code == 200 and r.json()["id"] == d.json()["id"]
    r = client.post("/api/workspace/save-recipe", json={"mode": "new", "recipe_id": rel["recipe_id"]})
    assert r.status_code == 409 and r.json()["error"] == "recipe_id_exists"
    r = client.post("/api/workspace/save-recipe", json={"mode": "new", "recipe_id": "from-manual", "name": {"zh-TW": "手動"}})
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["note"] == "manual"


def test_workspace_limits_and_permissions(client, tmp_path, monkeypatch):
    from xrayvision.service import workspace
    monkeypatch.setattr(workspace, "MAX_IMAGES", 1)
    up = _ws_upload(client, tmp_path, ["x1.tiff", "x2.tiff"])
    assert len(up["added"]) == 1 and up["errors"] == [{"file": "x2.tiff", "error": "workspace_full"}]
    r = client.post("/api/workspace/images", files=[("files", ("a.png.txt", io.BytesIO(b"x"), "text/plain"))])
    assert r.status_code == 200 and r.json()["added"] == []
    # 操作員不可使用
    client.post("/api/users", json={"username": "op", "role": "operator", "password": "Passw0rd!"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "op", "password": "Passw0rd!"})
    assert client.get("/api/workspace").status_code == 403
    assert client.post("/api/runs/1/regions", json={"regions": None}).status_code == 403


def test_workspace_purge_stale(tmp_path):
    from xrayvision.config import Settings
    from xrayvision.service import workspace
    s = Settings(data_dir=str(tmp_path / "d"))
    w = workspace.Workspace(s, "eng")
    w.set_params({"modules": []})
    d = w.load()
    d["updated_at"] = "2000-01-01T00:00:00"
    with open(w.manifest_path, "w", encoding="utf-8") as f:
        json.dump(d, f)
    workspace.Workspace(s, "other").set_params({"modules": []})
    assert workspace.purge_stale(s, 7) == 1
    assert w.load()["params"] is None and workspace.Workspace(s, "other").load()["params"] == {"modules": []}


# ---------------------------------------------------------------------------
# D　本影像自訂檢測區域
# ---------------------------------------------------------------------------
def test_image_regions_override_and_carry_over(client, tmp_path):
    rel = _released(client, limit_px=5.0)
    _upload(client, tmp_path, rel, ["g.tiff", "h.tiff"])
    runs = client.get("/api/runs").json()["items"]
    run = next(x for x in runs if x["file_name"].endswith("g.tiff"))
    full = client.get(f"/api/runs/{run['id']}").json()["result"]
    assert full["regions_source"] == "recipe"
    reg = dict(reference=dict(width=900, height=900), include=[dict(type="rect", x0=0, y0=0, x1=900, y1=450, label="top")])

    t = client.post(f"/api/runs/{run['id']}/regions/trial", json={"regions": reg})
    assert t.status_code == 200 and t.json()["result"]["regions_source"] == "image"
    assert client.get("/api/runs").json()["total"] == 2                        # 試跑不產生紀錄
    bad = client.post(f"/api/runs/{run['id']}/regions", json={"regions": {"include": reg["include"]}})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_regions"

    assert client.post(f"/api/runs/{run['id']}/regions", json={"regions": reg}).status_code == 200
    _wait(client)
    cur = next(x for x in client.get("/api/runs").json()["items"] if x["file_name"].endswith("g.tiff"))
    assert cur["id"] != run["id"]
    res = client.get(f"/api/runs/{cur['id']}").json()["result"]
    assert res["regions_source"] == "image" and res["recipe"]["regions"]["include"][0]["label"] == "top"
    assert res["modules"][0]["summary"]["sites_measured"] < full["modules"][0]["summary"]["sites_measured"]
    assert "run.regions_override" in [a["action"] for a in client.get("/api/audit").json()]

    # 發布新版本並重新分析：預設沿用自訂區域；範圍計數
    d = client.post(f"/api/recipes/{rel['id']}/revise").json()
    assert client.get(f"/api/recipes/{d['id']}/reanalysis-scope").json()["image_regions"] == 1
    client.post(f"/api/recipes/{d['id']}/release", json={"reanalyze": "all_previous"})
    _wait(client)
    items = client.get("/api/runs").json()["items"]
    src = {x["file_name"][-6:]: client.get(f"/api/runs/{x['id']}").json()["result"]["regions_source"] for x in items}
    assert src == {"g.tiff": "image", "h.tiff": "recipe"}
    # 批次重新分析改用配方區域
    g = next(x for x in items if x["file_name"].endswith("g.tiff"))
    client.post("/api/runs/reanalyze", json={"run_ids": [g["id"]], "keep_image_regions": False})
    _wait(client)
    g2 = next(x for x in client.get("/api/runs").json()["items"] if x["file_name"].endswith("g.tiff"))
    assert client.get(f"/api/runs/{g2['id']}").json()["result"]["regions_source"] == "recipe"
    # 改回配方區域 (regions = None)
    client.post(f"/api/runs/{g2['id']}/regions", json={"regions": reg})
    _wait(client)
    g3 = next(x for x in client.get("/api/runs").json()["items"] if x["file_name"].endswith("g.tiff"))
    client.post(f"/api/runs/{g3['id']}/regions", json={"regions": None})
    _wait(client)
    g4 = next(x for x in client.get("/api/runs").json()["items"] if x["file_name"].endswith("g.tiff"))
    assert client.get(f"/api/runs/{g4['id']}").json()["result"]["regions_source"] == "recipe"


def test_blob_cache_same_result(tmp_path):
    """互動分析的尺度空間快取：同一影像換參數重新分析，結果與重新計算完全相同"""
    from xrayvision.inspections.bump_alignment import algorithm as alg
    from xrayvision.service.jobs import _preloaded
    p = synth_raw16(str(tmp_path / "c.tiff"), shift=(0.6, 0.0))
    body = dict(recipe_id="b", version=1, name={}, modules=[dict(module_id="bump_alignment", params={})])
    rec = Recipe.from_dict(body)
    pre = _preloaded(p, rec, None)
    a, _ = analyze_image(p, rec, preloaded=pre)
    assert alg._BLOB_CACHE and alg._BLOB_CACHE[0][0]() is pre[1].absorption
    body["modules"][0]["params"] = {"pad_level": 0.3}
    rec2 = Recipe.from_dict(body)
    cached, _ = analyze_image(p, rec2, preloaded=_preloaded(p, rec2, None))
    alg._BLOB_CACHE.clear()
    fresh, _ = analyze_image(p, rec2)
    assert cached.modules[0].summary == fresh.modules[0].summary
    assert a.modules[0].summary != cached.modules[0].summary or a.modules[0].summary["die_shift"] is not None


def test_warm_image_fills_caches(tmp_path):
    """背景預先準備：載入影像與尺度空間偵測存入快取，之後的分析沿用且結果相同"""
    from xrayvision.inspections.bump_alignment import algorithm as alg
    from xrayvision.service import jobs
    p = synth_raw16(str(tmp_path / "w.tiff"), shift=(0.4, 0.0))
    body = dict(recipe_id="b", version=1, name={}, modules=[dict(module_id="bump_alignment", params={})])
    jobs._IMAGE_CACHE.clear()
    alg._BLOB_CACHE.clear()
    out = jobs.warm_image(dict(image_path=p, recipe=body, calibration_root=None))
    assert out["ok"] and len(jobs._IMAGE_CACHE) == 1 and len(alg._BLOB_CACHE) == 1
    rec = Recipe.from_dict(body)
    pre = jobs._preloaded(p, rec, None)
    assert alg._BLOB_CACHE[0][0]() is pre[1].absorption
    warm, _ = analyze_image(p, rec, preloaded=pre)
    alg._BLOB_CACHE.clear()
    fresh, _ = analyze_image(p, rec)
    assert warm.modules[0].summary == fresh.modules[0].summary
    assert not jobs.warm_image(dict(image_path=str(tmp_path / "none.tiff"), recipe=body, calibration_root=None))["ok"]


def test_workspace_prefetch_and_license_blocked(client, tmp_path):
    up = _ws_upload(client, tmp_path, ["p1.tiff", "p2.tiff"])
    tpl = client.get("/api/recipe-template/bump_alignment").json()
    client.put("/api/workspace/params", json={"body": tpl})
    r = client.post("/api/workspace/prefetch", json={"ids": up["added"] + [999]})
    assert r.status_code == 200 and r.json()["queued"] == 2
    it = up["added"][0]
    assert client.post(f"/api/workspace/images/{it}/analyze", json={}).status_code == 200
    # 授權不可分析：手動檢測、試跑、自訂區域的分析都拒絕；檢視結果與匯出仍可用
    plat = client.platform
    plat.enforce_license = True
    plat._lic_cache = (0.0, None)
    assert not plat.analysis_allowed()
    for path, body in ((f"/api/workspace/images/{it}/analyze", {}), ("/api/workspace/analyze-all", {}),
                       ("/api/recipes/trial", {"body": tpl, "run_id": 1}), ("/api/runs/1/regions/trial", {"regions": None})):
        r = client.post(path, json=body)
        assert r.status_code == 403 and r.json()["error"].startswith("license_"), (path, r.text)
    assert client.post("/api/workspace/prefetch", json={"ids": up["added"]}).json()["queued"] == 0
    assert client.get("/api/workspace").json()["analysis_allowed"] is False
    assert client.get(f"/api/workspace/images/{it}/result").status_code == 200
    assert client.get("/api/workspace/export").status_code == 200
