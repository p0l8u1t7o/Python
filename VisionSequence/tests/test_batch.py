"""批次測試：影像集建立（上傳／來源）、背景執行與進度、期望標記與命中、洞察門檻建議、比較、單張預覽、
自動調參模式、存成配方／Golden Set、淘汰、刪除、權限、伺服器重啟殘留。背景執行緒會寫 DB → TransactionTestCase。"""

from __future__ import annotations

import io
import json
import os
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.golden.models import GoldenCase
from apps.vision.batch import insights, jobs, store
from apps.vision.models import BatchRun, BatchSet, Flow, FlowRecipe, ImageSource
from apps.vision.runner import runner
from tests._helpers import temp_dir

TMP = temp_dir()
VISION_TEST = {**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False, "KEEP_BATCH_SETS": 10, "KEEP_BATCH_RUNS": 20, "BATCH_MAX_IMAGES": 200}


def png(value: int, w: int = 64, h: int = 48, name: str = "img.png"):
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), value, np.uint8))
    assert ok
    f = io.BytesIO(buf.tobytes())
    f.name = name
    return f


def part_png(holes: int, name: str):
    img = np.full((240, 320, 3), 200, np.uint8)
    for i in range(holes):
        cv2.circle(img, (50 + i * 55, 120), 15, (40, 40, 40), -1)
    ok, buf = cv2.imencode(".png", img)
    f = io.BytesIO(buf.tobytes())
    f.name = name
    return f


def gate_graph(source_id: int, low: int = 100) -> dict:
    """灰階平均 >= low → ok，否則 ng；同時輸出 mean。"""
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "g", "type": "grayscale", "params": {}},
            {"id": "t", "type": "intensity", "params": {}},
            {"id": "rng", "type": "in_range", "params": {"low": low, "high": 255}},
            {"id": "ok", "type": "judge", "params": {"verdict": "ok"}},
            {"id": "ng", "type": "judge", "params": {"verdict": "ng", "label": "dark"}},
            {"id": "o", "type": "output", "params": {"name": "mean"}},
        ],
        "edges": [
            {"source": "src", "target": "g"}, {"source": "g", "target": "t"},
            {"source": "t", "source_handle": "mean", "target": "rng", "target_handle": "value"},
            {"source": "rng", "source_handle": "inside", "target": "ok", "target_handle": "_flow"},
            {"source": "rng", "source_handle": "outside", "target": "ng", "target_handle": "_flow"},
            {"source": "t", "source_handle": "mean", "target": "o", "target_handle": "value"},
        ],
    }


def count_graph(source_id: int, min_area: int = 5000) -> dict:
    """暗孔計數：blob 最小面積故意調壞時抓不到孔。"""
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "g", "type": "grayscale", "params": {}},
            {"id": "thr", "type": "threshold", "params": {"method": "otsu", "invert": True}},
            {"id": "blob", "type": "blob", "params": {"min_area": min_area, "min_count": 0}},
            {"id": "cmp", "type": "if_number", "params": {"operator": "ge", "threshold": 1}},
            {"id": "ok", "type": "judge", "params": {"verdict": "ok"}},
            {"id": "ng", "type": "judge", "params": {"verdict": "ng", "label": "count"}},
            {"id": "o", "type": "output", "params": {"name": "count"}},
        ],
        "edges": [
            {"source": "src", "target": "g"}, {"source": "g", "target": "thr"}, {"source": "thr", "target": "blob"},
            {"source": "blob", "source_handle": "count", "target": "cmp", "target_handle": "value"},
            {"source": "cmp", "source_handle": "true", "target": "ok", "target_handle": "_flow"},
            {"source": "cmp", "source_handle": "false", "target": "ng", "target_handle": "_flow"},
            {"source": "blob", "source_handle": "count", "target": "o", "target_handle": "value"},
        ],
    }


@override_settings(VISION=VISION_TEST)
class BatchApiTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        self.flow = Flow.objects.create(name="gate", graph=gate_graph(self.source.id))

    def _json(self, method: str, path: str, body=None, **kw):
        fn = getattr(self.client, method)
        return fn(path, data=json.dumps(body) if body is not None else None, content_type="application/json", **kw)

    def _set(self, files, name="s1", flow=None):
        r = self.client.post("/api/vision/batch/sets", data={"images": files, "flow_id": (flow or self.flow).id, "name": name})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _run(self, set_id: int, **body) -> dict:
        r = self._json("post", f"/api/vision/batch/sets/{set_id}/runs", body)
        self.assertEqual(r.status_code, 202, r.content)
        run_id = r.json()["id"]
        self.assertTrue(jobs.wait(run_id, 120))
        out = self._json("get", f"/api/vision/batch/runs/{run_id}").json()
        self.assertNotIn(out["status"], ("queued", "running"), out)
        return out

    # -- 影像集 → 執行 → 標記 → 洞察 → 重跑 → 比較 → 預覽 ---------------------------------
    def test_upload_run_labels_insights_compare_preview(self):
        s = self._set([png(200, name="bright.png"), png(20, name="dark.png"), png(150, name="mid.png")])
        self.assertEqual(s["image_count"], 3)
        self.assertEqual([im["name"] for im in s["images"]], ["bright.png", "dark.png", "mid.png"])
        self.assertTrue(os.path.isdir(store.batch_dir(s["id"])))
        run = self._run(s["id"], label="第一次")
        self.assertEqual(run["status"], "done")
        self.assertEqual([it["status"] for it in run["items"]], ["ok", "ng", "ok"])
        self.assertEqual(run["summary"]["total"], 3)
        self.assertEqual(run["summary"]["labeled"], 0)
        self.assertIn("mean", run["items"][0]["outputs"])
        self.assertIn("t", run["items"][0]["nodes"])
        self.assertEqual(run["progress"], {"done": 3, "total": 3, "stage": ""})
        self.assertIn("graph", run)
        # 期望標記：mid 應該是 NG（門檻 100 太低）
        r = self._json("patch", f"/api/vision/batch/sets/{s['id']}", {"labels": [{"index": 0, "expected": "ok"}, {"index": 1, "expected": "ng"}, {"index": 2, "expected": "ng", "note": "偏暗"}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["labeled"], {"ok": 1, "ng": 2})
        run = self._json("get", f"/api/vision/batch/runs/{run['id']}").json()
        self.assertEqual((run["summary"]["labeled"], run["summary"]["match"]), (3, 2))
        self.assertEqual([it["match"] for it in run["items"]], [True, True, False])
        # 洞察：in_range 的 low 建議落在 150～200 之間，命中率 2/3 → 3/3
        ins = self._json("get", f"/api/vision/batch/runs/{run['id']}/insights").json()
        self.assertTrue(ins["ready"])
        self.assertEqual((ins["labeled"], ins["match"]), (3, 2))
        self.assertEqual(ins["confusion"], {"tp": 1, "fp": 0, "tn": 1, "fn": 1})
        judge = next(j for j in ins["judges"] if j["node"] == "rng")
        self.assertEqual(judge["value_from"], {"node": "t", "port": "mean", "label": "t"})
        self.assertTrue(judge["separable"])
        self.assertTrue(150 < judge["suggestion"]["low"] < 200, judge)
        self.assertEqual(judge["acc_suggested"], 1.0)
        self.assertEqual(ins["suggestions"][0]["node"], "rng")
        self.assertTrue(any("Consider changing" in line for line in ins["text"]))
        self.assertEqual(ins["mismatches"][0]["index"], 2)
        # 套用建議重跑（parent＝第一次）
        graph2 = insights.apply_suggestions(run["graph"], ins["suggestions"])
        run2 = self._run(s["id"], graph=graph2, parent_run_id=run["id"], label="套用建議")
        self.assertEqual(run2["summary"]["match"], 3)
        self.assertEqual(run2["parent_id"], run["id"])
        ins2 = self._json("get", f"/api/vision/batch/runs/{run2['id']}/insights").json()
        self.assertEqual(ins2["vs_parent"]["improved"], [2])
        self.assertEqual(ins2["vs_parent"]["regressed"], [])
        self.assertEqual(ins2["vs_parent"]["param_diff"]["rows"][0]["key"], "low")
        # 比較
        cmp = self._json("get", f"/api/vision/batch/runs/{run['id']}/compare?other={run2['id']}").json()
        self.assertEqual(cmp["summary"]["changed"], 1)
        self.assertEqual(cmp["summary"]["improved"], 1)
        self.assertTrue(cmp["rows"][2]["changed"])
        self.assertEqual(cmp["param_diff"]["rows"][0]["node"], "rng")
        # 單張預覽（取標記）
        r = self._json("post", f"/api/vision/batch/runs/{run2['id']}/rows/0/preview", {})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "ok")
        self.assertIn("t", r.json()["nodes"])
        # 清單與影像端點
        listed = self._json("get", f"/api/vision/batch/sets?flow_id={self.flow.id}").json()
        self.assertEqual(listed["items"][0]["latest_run"]["id"], run2["id"])
        self.assertEqual(listed["max_images"], 200)
        runs = self._json("get", f"/api/vision/batch/sets/{s['id']}/runs").json()
        self.assertEqual([x["id"] for x in runs["items"]], [run2["id"], run["id"]])
        self.assertNotIn("items", runs["items"][0])
        r = self.client.get(f"/api/vision/batch/sets/{s['id']}/images/0?max=32")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get(f"/api/vision/batch/sets/{s['id']}/images/9").status_code, 404)

    # -- 同一組影像測不同流程 --------------------------------------------------------
    def test_run_with_another_flow(self):
        """影像集是測試資料：清單跨流程可見，執行可指定 flow_id，逐張結果依該流程的圖。"""
        other = Flow.objects.create(name="gate-high", graph=gate_graph(self.source.id, low=250))  # 門檻拉高 → 全部 ng
        s = self._set([png(200, name="bright.png"), png(20, name="dark.png")])
        # 不帶 flow_id 的清單看得到（跨流程）；帶 flow_id 只看該流程建立的
        allsets = self._json("get", "/api/vision/batch/sets").json()
        self.assertIn(s["id"], [x["id"] for x in allsets["items"]])
        self.assertEqual(next(x for x in allsets["items"] if x["id"] == s["id"])["flow_name"], self.flow.name)
        only_other = self._json("get", f"/api/vision/batch/sets?flow_id={other.id}").json()
        self.assertEqual([x["id"] for x in only_other["items"]], [])
        # 預設用影像集的流程：亮的 ok、暗的 ng
        base = self._run(s["id"])
        self.assertEqual([it["status"] for it in base["items"]], ["ok", "ng"])
        self.assertEqual((base["flow_id"], base["set_flow_id"]), (self.flow.id, self.flow.id))
        # 指定另一個流程：門檻 250 → 兩張都 ng；影像集歸屬不變
        cross = self._run(s["id"], flow_id=other.id, label="換流程")
        self.assertEqual([it["status"] for it in cross["items"]], ["ng", "ng"])
        self.assertEqual((cross["flow_id"], cross["flow_name"], cross["set_flow_id"]), (other.id, other.name, self.flow.id))
        self.assertEqual(BatchSet.objects.get(pk=s["id"]).flow_id, self.flow.id)
        # 兩次執行都掛在同一個影像集，可以互相比較
        runs = self._json("get", f"/api/vision/batch/sets/{s['id']}/runs").json()
        self.assertEqual({r["id"] for r in runs["items"]}, {base["id"], cross["id"]})
        # 沒帶 graph 的接續：換流程時用該流程的現圖，不沿用上一次（別的流程）的參數
        again = self._run(s["id"], flow_id=other.id, parent_run_id=base["id"])
        self.assertEqual([it["status"] for it in again["items"]], ["ng", "ng"])
        self.assertEqual(again["graph"]["nodes"][3]["params"]["low"], 250)
        # 單張預覽與存為配方都用這次執行的流程
        r = self._json("post", f"/api/vision/batch/runs/{cross['id']}/rows/0/preview", {})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "ng")
        r = self._json("post", f"/api/vision/batch/runs/{cross['id']}/to-recipe", {"name": "n/a"})
        self.assertEqual(r.status_code, 422, r.content)  # 與該流程現圖相同 → 沒有差異可存
        tuned = self._run(s["id"], flow_id=other.id, graph=gate_graph(self.source.id, low=10))
        r = self._json("post", f"/api/vision/batch/runs/{tuned['id']}/to-recipe", {"name": "低門檻"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(FlowRecipe.objects.get(name="低門檻").flow_id, other.id)
        # 看不見的流程不能拿來測
        r = self._json("post", f"/api/vision/batch/sets/{s['id']}/runs", {"flow_id": 999999})
        self.assertEqual(r.status_code, 404, r.content)

    def test_from_source_prune_and_limits(self):
        r = self._json("post", "/api/vision/batch/sets/from-source", {"flow_id": self.flow.id, "source_id": self.source.id, "count": 2})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["image_count"], 2)
        self.assertTrue(r.json()["source"].startswith("source:"))
        first_dir = store.batch_dir(r.json()["id"])
        with override_settings(VISION={**VISION_TEST, "KEEP_BATCH_SETS": 2}):
            self._set([png(10)], name="s2")
            self._set([png(10)], name="s3")
        self.assertEqual(BatchSet.objects.filter(flow=self.flow).count(), 2)
        self.assertFalse(os.path.isdir(first_dir))
        with override_settings(VISION={**VISION_TEST, "BATCH_MAX_IMAGES": 2}):
            r = self.client.post("/api/vision/batch/sets", data={"images": [png(1), png(2), png(3)], "flow_id": self.flow.id})
            self.assertEqual(r.status_code, 422)
        s = self._set([png(10)], name="s4")
        self.assertEqual(self._json("post", f"/api/vision/batch/sets/{s['id']}/runs", {"mode": "bogus"}).status_code, 422)
        self.assertEqual(self._json("post", f"/api/vision/batch/sets/{s['id']}/runs", {"mode": "autotune"}).status_code, 422)
        self.assertEqual(self._json("post", "/api/vision/batch/sets/from-source", {"flow_id": self.flow.id, "source_id": 9999}).status_code, 404)

    def test_cancel_delete_and_stale_running(self):
        s = self._set([png(200 - i * 3, name=f"i{i}.png") for i in range(40)], name="many")
        r = self._json("post", f"/api/vision/batch/sets/{s['id']}/runs", {})
        self.assertEqual(r.status_code, 202, r.content)
        run_id = r.json()["id"]
        self._json("post", f"/api/vision/batch/runs/{run_id}/cancel")
        self.assertTrue(jobs.wait(run_id, 60))
        run = self._json("get", f"/api/vision/batch/runs/{run_id}").json()
        self.assertIn(run["status"], ("cancelled", "done"))
        self.assertEqual(self.client.delete(f"/api/vision/batch/runs/{run_id}").status_code, 204)
        folder = store.batch_dir(s["id"])
        self.assertEqual(self.client.delete(f"/api/vision/batch/sets/{s['id']}").status_code, 204)
        self.assertFalse(os.path.isdir(folder))
        self.assertEqual(self._json("get", f"/api/vision/batch/sets/{s['id']}").status_code, 404)
        # 伺服器重啟殘留的 running → failed
        s2 = self._set([png(10)], name="stale")
        stale = BatchRun.objects.create(batch_set_id=s2["id"], flow_version=1, graph=self.flow.graph, status="running", progress_total=1)
        out = self._json("get", f"/api/vision/batch/runs/{stale.id}").json()
        self.assertEqual(out["status"], "failed")
        self.assertIn("restarted", out["error"])

    def test_autotune_mode_to_recipe_and_to_golden(self):
        flow = Flow.objects.create(name="count", graph=count_graph(self.source.id, min_area=5000))
        s = self._set([part_png(5, "five.png"), part_png(3, "three.png"), png(200, 320, 240, "blank.png")], name="holes", flow=flow)
        self._json("patch", f"/api/vision/batch/sets/{s['id']}", {"labels": [{"index": 0, "expected": "ok"}, {"index": 1, "expected": "ok"}, {"index": 2, "expected": "ng"}]})
        run = self._run(s["id"])
        self.assertEqual([it["status"] for it in run["items"]], ["ng", "ng", "ng"])
        self.assertEqual(run["summary"]["match"], 1)
        tuned = self._run(s["id"], mode="autotune", parent_run_id=run["id"], max_evals=40, deadline_s=60)
        self.assertEqual(tuned["origin"], "autotune")
        self.assertTrue(tuned["meta"]["autotune"]["improved"], tuned["meta"])
        self.assertEqual(tuned["summary"]["match"], 3)
        self.assertLess(next(n for n in tuned["graph"]["nodes"] if n["id"] == "blob")["params"]["min_area"], 5000)
        # 存成配方（與流程現圖的差異）
        r = self._json("post", f"/api/vision/batch/runs/{tuned['id']}/to-recipe", {"name": "tuned"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn("min_area", r.json()["param_overrides"]["blob"])
        self.assertEqual(self._json("post", f"/api/vision/batch/runs/{tuned['id']}/to-recipe", {"name": "tuned"}).status_code, 409)
        self.assertEqual(self._json("post", f"/api/vision/batch/runs/{run['id']}/to-recipe", {"name": "same"}).status_code, 422)
        self.assertEqual(FlowRecipe.objects.filter(flow=flow).count(), 1)
        # 存入 Golden Set（用期望標記）
        r = self._json("post", f"/api/vision/batch/sets/{s['id']}/to-golden", {"expect_from": "label"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["created"], 3)
        cases = list(GoldenCase.objects.filter(flow=flow).order_by("id"))
        self.assertEqual([c.expect_status for c in cases], ["ok", "ok", "ng"])
        self.assertTrue(all(os.path.exists(c.image_path) for c in cases))
        r = self._json("post", f"/api/vision/batch/sets/{s['id']}/to-golden", {"expect_from": "status", "run_id": tuned["id"], "indexes": [2]})
        self.assertEqual(r.json()["created"], 1)
        # 移除一張影像後重算
        r = self._json("patch", f"/api/vision/batch/sets/{s['id']}", {"remove": [2]})
        self.assertEqual(r.json()["image_count"], 2)
        self.assertEqual(self._json("get", f"/api/vision/batch/runs/{tuned['id']}").json()["summary"]["labeled"], 2)

    def test_permissions(self):
        token = self._json("post", "/api/auth/setup", {"username": "admin", "password": "secret123"}).json()["token"]
        admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        r = self._json("post", "/api/vision/flows", {"name": "mine", "graph": gate_graph(self.source.id)}, **admin_auth)
        self.assertEqual(r.status_code, 201, r.content)
        flow_id = r.json()["id"]
        r = self.client.post("/api/vision/batch/sets", data={"images": [png(10)], "flow_id": flow_id}, **admin_auth)
        self.assertEqual(r.status_code, 201, r.content)
        set_id = r.json()["id"]
        worker = User.objects.create_user("worker", password="x")
        worker_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(worker)}"}
        # 流程與影像集屬於產線，工程師都看得到
        self.assertEqual(self.client.get(f"/api/vision/batch/sets?flow_id={flow_id}", **worker_auth).status_code, 200)
        self.assertEqual(self.client.get(f"/api/vision/batch/sets/{set_id}", **worker_auth).status_code, 200)
        # 操作員不能做批次測試（那是工程師調參數的工具）
        op = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=op, role="operator")
        op_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(op)}"}
        self.assertEqual(self.client.post("/api/vision/batch/sets", data={"images": [png(10)], "flow_id": flow_id}, **op_auth).status_code, 403)
        self.assertEqual(self.client.get(f"/api/vision/batch/sets/{set_id}", **admin_auth).status_code, 200)
        self.assertEqual(self.client.get(f"/api/vision/batch/sets?flow_id={flow_id}").status_code, 401)
        self.assertEqual(self.client.get(f"/api/vision/batch/sets/{set_id}/images/0?max=16&token={token}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/vision/batch/sets/{set_id}/images/0?max=16").status_code, 401)


class StoreUnitTests(TransactionTestCase):
    def test_graph_param_diff_and_overrides(self):
        a = gate_graph(1, low=100)
        b = json.loads(json.dumps(a))
        next(n for n in b["nodes"] if n["id"] == "rng")["params"]["low"] = 160
        b["nodes"].append({"id": "extra", "type": "grayscale", "params": {}})
        diff = store.graph_param_diff(a, b)
        self.assertEqual(diff["rows"], [{"node": "rng", "label": "rng", "type": "in_range", "key": "low", "from": 100, "to": 160}])
        self.assertEqual(diff["added"], ["extra"])
        self.assertEqual(store.to_overrides(diff), {"rng": {"low": 160}})

    def test_summarize_and_row_match(self):
        images = [{"index": 0, "expected": "ok"}, {"index": 1, "expected": "ng", "expect_outputs": {"mean": {"value": 20, "tol": 5}}}, {"index": 2, "expected": ""}]
        items = [{"index": 0, "status": "ok", "duration_ms": 2, "outputs": {"mean": 200}}, {"index": 1, "status": "ng", "duration_ms": 4, "outputs": {"mean": 21}}, {"index": 2, "status": "failed", "duration_ms": 1, "outputs": {}}]
        summary = store.summarize(items, images, 9.5)
        self.assertEqual((summary["labeled"], summary["match"], summary["failed"], summary["wall_ms"]), (2, 2, 1, 9.5))
        self.assertEqual(summary["confusion"], {"tp": 1, "fp": 0, "tn": 1, "fn": 0})
        self.assertEqual(store.row_match(items[2], images[2]), (None, []))
        self.assertTrue(time.time() > 0)


@override_settings(VISION=VISION_TEST)
class BatchAgentTests(TransactionTestCase):
    """AI 助手接持久化批次：資料諮詢、請 AI 調整／自動調參落成新執行。"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        self.flow = Flow.objects.create(name="gate", graph=gate_graph(self.source.id))

    def _json(self, method: str, path: str, body=None, **kw):
        fn = getattr(self.client, method)
        return fn(path, data=json.dumps(body) if body is not None else None, content_type="application/json", **kw)

    def _gate_run(self):
        r = self.client.post("/api/vision/batch/sets", data={"images": [png(200, name="bright.png"), png(20, name="dark.png"), png(150, name="mid.png")], "flow_id": self.flow.id})
        s = BatchSet.objects.get(pk=r.json()["id"])
        self._json("patch", f"/api/vision/batch/sets/{s.id}", {"labels": [{"index": 0, "expected": "ok"}, {"index": 1, "expected": "ng"}, {"index": 2, "expected": "ng"}]})
        s.refresh_from_db()
        rows, wall = jobs.execute_rows(self.flow, self.flow.graph, s.images)
        run = store.save_completed_run(s, self.flow.graph, rows, origin="manual", wall_ms=wall)
        return s, run

    def test_consult_offline_and_llm_suggestions(self):
        s, run = self._gate_run()
        r = self._json("post", "/api/vision/agent/consult", {"batch_run_id": run.id, "question": "哪個門檻該調？"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["provider"], "rules")
        self.assertIn("Consider changing", body["answer"])
        self.assertEqual(body["insights"]["labeled"], 3)
        self.assertEqual(body["suggestions"][0]["node"], "rng")
        self.assertEqual(body["suggestions"][0]["key"], "low")
        # LLM：回答尾端的 SUGGESTIONS 會被驗證（不存在的節點丟掉並記 warnings）
        from unittest import mock

        from apps.vision.agent import providers

        llm_settings = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user")
        reply = "第 3 張偏暗但門檻太低。\nSUGGESTIONS: {\"suggestions\":[{\"node\":\"rng\",\"key\":\"low\",\"value\":170,\"reason\":\"介於兩群之間\"},{\"node\":\"nope\",\"key\":\"low\",\"value\":1}]}"
        with mock.patch.object(providers, "resolve", return_value=llm_settings), mock.patch.object(providers, "complete", return_value=reply) as done:
            r = self._json("post", "/api/vision/agent/consult", {"batch_run_id": run.id, "question": "為什麼第 3 張 NG？"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["provider"], "openai")
        self.assertEqual(body["answer"], "第 3 張偏暗但門檻太低。")
        self.assertEqual(body["suggestions"], [{"node": "rng", "label": "rng", "key": "low", "value": 170, "reason": "介於兩群之間"}])
        self.assertTrue(any("nope" in w for w in body["warnings"]))
        self.assertIn("Per-image data", done.call_args.args[3])
        self.assertEqual(self._json("post", "/api/vision/agent/consult", {"batch_run_id": run.id, "question": " "}).status_code, 422)
        self.assertEqual(self._json("post", "/api/vision/agent/consult", {"batch_run_id": 9999, "question": "x"}).status_code, 404)

    def test_tune_and_autotune_with_batch_run_id(self):
        s, run = self._gate_run()
        # 規則式回饋映射：in_range 不在映射表 → 沒改動；用 set 節點參數指令
        r = self._json("post", "/api/vision/agent/tune", {"batch_run_id": run.id, "instruction": "把 rng 的 low 改成 170"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["applied"])
        self.assertEqual(body["after"], {"ok": 1, "ng": 2, "failed": 0})
        self.assertIsNotNone(body["batch_run_id"])
        new = BatchRun.objects.get(pk=body["batch_run_id"])
        self.assertEqual((new.origin, new.parent_id, new.status), ("ai_tune", run.id, "done"))
        self.assertEqual(new.summary["match"], 3)
        self.assertEqual(len(new.items), 3)
        self.assertIn("t", new.items[0]["nodes"])
        self.assertEqual(new.meta["changes"][0], "rng：low → 170")
        # 自動調參端點（in_range 是規格不搜，所以維持原參數但仍會回應）
        r = self._json("post", "/api/vision/agent/autotune", {"batch_run_id": run.id, "max_evals": 10})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["applied"])
        self.assertEqual(r.json()["provider"], "autotune")
        self.assertEqual(BatchRun.objects.filter(batch_set=s).count(), 3)
        # 沒有 graph 也沒有 batch_run_id → 422
        self.assertEqual(self._json("post", "/api/vision/agent/tune", {"instruction": "x"}).status_code, 422)

    def test_agent_job_tune_persists_batch_run(self):
        from unittest import mock

        from apps.vision.agent import providers

        s, run = self._gate_run()
        llm_settings = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user", mode="agentic")
        replies = [providers.ToolReply("", [providers.ToolCall("c1", "patch_graph", {"ops": [{"op": "set_param", "node": "rng", "key": "low", "value": "170"}]})]),
                   providers.ToolReply("", [providers.ToolCall("c2", "finish", {"rationale": "門檻拉到兩群中間"})])]

        def fake(settings, system, history, tools, *, timeout=None):
            return replies.pop(0) if replies else providers.ToolReply("", [providers.ToolCall("f", "finish", {"rationale": "done"})])

        with mock.patch.object(providers, "complete_tools", side_effect=fake), mock.patch.object(providers, "resolve", return_value=llm_settings):
            r = self._json("post", "/api/vision/agent/jobs", {"task": "tune", "batch_run_id": run.id, "instruction": "依這批資料調門檻"})
            self.assertEqual(r.status_code, 202, r.content)
            job_id = r.json()["id"]
            deadline = time.time() + 60
            while time.time() < deadline:
                body = self._json("get", f"/api/vision/agent/jobs/{job_id}").json()
                if body["status"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(body["status"], "done", body.get("error"))
        self.assertEqual(body["result"]["after"], {"ok": 1, "ng": 2, "failed": 0})
        new_id = body["result"]["batch_run_id"]
        self.assertIsNotNone(new_id)
        new = BatchRun.objects.get(pk=new_id)
        self.assertEqual((new.origin, new.parent_id, new.summary["match"]), ("ai_tune", run.id, 3))
        self.assertIn("rng.low = 170", new.meta["changes"][0])
