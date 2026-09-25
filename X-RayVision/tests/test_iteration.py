"""PLAN-003：目前結果、配方修改與差異、發布並重新分析、批次重新分析、試跑"""
import os

from test_service import _released, _wait, client, recipe_body  # noqa: F401  (client 為 fixture)

from conftest import synth_raw16


def _upload(client, tmp_path, rel, names, lot="LOT-A"):
    files = []
    for i, n in enumerate(names):
        p = synth_raw16(str(tmp_path / n), shift=(0.5 + 0.1 * i, 0.0), seed=sum(map(ord, n)))
        files.append(("files", (n, open(p, "rb"), "image/tiff")))
    r = client.post("/api/imports", files=files, data={"recipe_pk": str(rel["id"]), "lot_no": lot})
    for _, (_, fh, _) in files:
        fh.close()
    assert r.status_code == 200 and all("job_id" in x for x in r.json()), r.text
    _wait(client)


def test_revise_diff_release_reanalyze_and_current_results(client, tmp_path):
    rel = _released(client, limit_px=5.0)
    _upload(client, tmp_path, rel, ["a.tiff", "b.tiff"])
    runs = client.get("/api/runs").json()
    assert runs["total"] == 2 and all(r["superseded_by"] is None for r in runs["items"])
    first = runs["items"][-1]
    client.post(f"/api/runs/{first['id']}/review", json={"judgment": "fail", "comment": "manual"})

    # 修改：建立下一版草稿；重複按不產生第二份
    d1 = client.post(f"/api/recipes/{rel['id']}/revise").json()
    d2 = client.post(f"/api/recipes/{rel['id']}/revise").json()
    assert d1["id"] == d2["id"] and d1["version"] == 2 and d1["status"] == "draft" and d1["note"] == "from v1"
    body = d1["body"]
    body["modules"][0]["judgment"] = {"die_shift_max_px": 0.05}
    assert client.put(f"/api/recipes/{d1['id']}", json={"body": body}).status_code == 200
    diff = client.get(f"/api/recipes/{d1['id']}/diff").json()
    assert diff["base"]["version"] == 1
    assert [c["path"] for c in diff["changes"]] == ["modules.bump_alignment.judgment.die_shift_max_px"]
    assert diff["changes"][0]["old"] == 5.0 and diff["changes"][0]["new"] == 0.05

    # 重跑範圍與發布並重新分析
    scope = client.get(f"/api/recipes/{d1['id']}/reanalysis-scope").json()
    assert scope["total"] == 2 and scope["skipped"] == 0 and scope["lots"] == [{"lot_no": "LOT-A", "n": 2}]
    r = client.post(f"/api/recipes/{d1['id']}/release", json={"reanalyze": "all_previous"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "released" and r.json()["reanalysis"]["queued"] == 2
    _wait(client)

    # 目前結果只列新結果；取消篩選可看到被取代的舊紀錄
    cur = client.get("/api/runs").json()
    assert cur["total"] == 2 and {x["recipe_version"] for x in cur["items"]} == {2}
    assert all(x["final_judgment"] == "fail" for x in cur["items"])          # 規格收緊後不合格
    allr = client.get("/api/runs", params={"current_only": "false"}).json()
    assert allr["total"] == 4
    old = next(x for x in allr["items"] if x["id"] == first["id"])
    assert old["superseded_by"] is not None and old["final_judgment"] == "fail"
    # 新結果不沿用舊紀錄的人工複判；歷程可看到舊複判
    new = client.get(f"/api/runs/{old['superseded_by']}").json()
    assert new["reviews"] == [] and new["run"]["auto_judgment"] == new["run"]["final_judgment"]
    assert [h["recipe_version"] for h in new["history"]] == [2, 1]
    assert new["history"][1]["reviews"][0]["comment"] == "manual"
    # 總覽只計目前結果
    st = client.get("/api/stats?days=1").json()
    assert sum(t["n"] for t in st["totals"]) == 2
    # CSV 依目前結果
    csv_cur = client.get("/api/runs/export.csv").text.strip().splitlines()
    csv_all = client.get("/api/runs/export.csv", params={"current_only": "false"}).text.strip().splitlines()
    assert len(csv_cur) == 3 and len(csv_all) == 5
    acts = [a["action"] for a in client.get("/api/audit").json()]
    assert "recipe.release_reanalyze" in acts


def test_release_scope_lot_and_none(client, tmp_path):
    rel = _released(client)
    _upload(client, tmp_path, rel, ["a.tiff"], lot="L1")
    _upload(client, tmp_path, rel, ["b.tiff"], lot="L2")
    d = client.post(f"/api/recipes/{rel['id']}/revise").json()
    r = client.post(f"/api/recipes/{d['id']}/release", json={"reanalyze": "lot", "lot_no": "L2"})
    assert r.json()["reanalysis"]["queued"] == 1
    _wait(client)
    cur = {x["lot_no"]: x["recipe_version"] for x in client.get("/api/runs").json()["items"]}
    assert cur == {"L1": 1, "L2": 2}
    # 不重新分析：只發布
    d3 = client.post(f"/api/recipes/{d['id']}/revise").json()
    r = client.post(f"/api/recipes/{d3['id']}/release")
    assert r.status_code == 200 and "reanalysis" not in r.json()
    assert client.post(f"/api/recipes/{d3['id']}/release", json={"reanalyze": "bogus"}).status_code == 400


def test_batch_reanalyze_skips_missing_images_and_progress(client, tmp_path):
    rel = _released(client)
    _upload(client, tmp_path, rel, ["a.tiff", "b.tiff"])
    items = client.get("/api/runs").json()["items"]
    # 封存影像與原始檔都不存在時略過
    gone = client.platform.db.one("SELECT * FROM images WHERE id = ?", (items[0]["image_id"],))
    for p in (gone["archive_path"], gone["original_path"]):
        if p and os.path.isfile(p):
            os.remove(p)
    ids = [x["id"] for x in items] + [items[1]["id"]]                       # 重複勾選只建立一個工作
    r = client.post("/api/runs/reanalyze", json={"run_ids": ids}).json()
    assert r["queued"] == 1 and r["skipped"] == [items[0]["file_name"]] and r["no_recipe"] == []
    prog = client.get("/api/jobs/reanalysis").json()
    assert prog["active"] in (True, False)
    _wait(client)
    assert client.get("/api/jobs/reanalysis").json() == {"active": False}
    assert client.get("/api/runs", params={"current_only": "false"}).json()["total"] == 3


def test_trial_runs_unsaved_body_without_records(client, tmp_path):
    rel = _released(client, limit_px=5.0)
    _upload(client, tmp_path, rel, ["a.tiff"])
    run = client.get("/api/runs").json()["items"][0]
    n_runs = client.platform.db.one("SELECT COUNT(*) AS n FROM runs")["n"]
    body = recipe_body(0.05)                                                  # 未儲存的收緊規格
    r = client.post("/api/recipes/trial", json={"body": body, "run_id": run["id"]})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["judgment"] == "fail" and run["final_judgment"] == "pass"
    assert client.platform.db.one("SELECT COUNT(*) AS n FROM runs")["n"] == n_runs
    assert "recipe.trial" in [a["action"] for a in client.get("/api/audit").json()]
    bad = recipe_body()
    bad["modules"][0]["params"] = {"bump_level": 9}
    assert client.post("/api/recipes/trial", json={"body": bad, "run_id": run["id"]}).json()["error"] == "invalid_param"
    assert client.post("/api/recipes/trial", json={"body": body, "run_id": 9999}).status_code == 404
