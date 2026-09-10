"""Golden Set：建立（上傳／從批次快取）、影像端點、期望值比對、回歸報告、基準、CLI、權限。"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.golden import regress
from apps.golden.models import GoldenBaseline, GoldenCase
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from tests._helpers import temp_dir

TMP = temp_dir()
VISION_TEST = {**settings.VISION, "ASSET_DIR": Path(TMP)}


def png(value: int, w: int = 64, h: int = 48, name: str = "img.png"):
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), value, np.uint8))
    assert ok
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


@override_settings(VISION=VISION_TEST)
class GoldenTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        self.flow = Flow.objects.create(name="gate", graph=gate_graph(self.source.id))
        self.url = f"/api/vision/flows/{self.flow.id}/golden"

    def upload(self, values, expect_status="any", **form):
        files = [png(v, name=f"v{v}.png") for v in values]
        r = self.client.post(self.url, data={"images": files, "expect_status": expect_status, **form})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["items"]

    # -- 建立 / 列表 / 影像 / 修改 / 刪除 -----------------------------------
    def test_upload_list_image_patch_delete(self):
        items = self.upload([200, 20], expect_status="ok", note="n")
        self.assertEqual(len(items), 2)
        case = GoldenCase.objects.get(pk=items[0]["id"])
        self.assertTrue(Path(case.image_path).is_file())
        self.assertTrue(str(case.image_path).startswith(str(Path(TMP) / "golden" / str(self.flow.id))))
        self.assertEqual(case.expect_status, "ok")
        self.assertEqual(case.note, "n")

        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 2)
        self.assertTrue(r.json()["can_manage"])
        self.assertIsNone(r.json()["baseline_version"])

        r = self.client.get(items[0]["image_url"] + "?max=32&fmt=png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_UNCHANGED)
        self.assertEqual(max(img.shape[:2]), 32)

        r = self.client.patch(f"{self.url}/{case.id}", data=json.dumps({"expect_status": "ng", "expect_outputs": {"mean": {"value": 10, "tol": 5}}, "name": "renamed"}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["expect_status"], "ng")
        self.assertEqual(r.json()["name"], "renamed")
        self.assertEqual(self.client.patch(f"{self.url}/{case.id}", data=json.dumps({"expect_status": "maybe"}), content_type="application/json").status_code, 422)

        r = self.client.delete(f"{self.url}/{case.id}")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Path(case.image_path).exists())
        self.assertEqual(GoldenCase.objects.count(), 1)
        self.assertEqual(self.client.get(f"{self.url}/{case.id}/image").status_code, 404)

    def test_from_batch_uses_image_cache(self):
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/batch", data={"images": [png(200, name="a.png"), png(20, name="b.png")]})
        self.assertEqual(r.status_code, 200, r.content)
        refs = [it["image_ref"] for it in r.json()["items"]]
        self.assertTrue(all(refs))
        body = {"from_batch": [
            {"image_ref": refs[0], "name": "a", "expect_status": "ok"},
            {"image_ref": refs[1], "name": "b", "expect_status": "ng", "expect_outputs": {"mean": {"value": 0, "tol": 30}}},
        ]}
        r = self.client.post(self.url, data=json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual([c["name"] for c in r.json()["items"]], ["a", "b"])
        self.assertEqual(GoldenCase.objects.get(name="b").expect_outputs["mean"]["tol"], 30)
        # 快取沒有的 ref → 404
        r = self.client.post(self.url, data=json.dumps({"from_batch": [{"image_ref": "nope:src:image"}]}), content_type="application/json")
        self.assertEqual(r.status_code, 404)

    # -- 比對規則 ----------------------------------------------------------
    def test_output_matching_rules(self):
        self.assertTrue(regress.output_matches({"value": 5, "tol": 0.5}, 5.4))
        self.assertFalse(regress.output_matches({"value": 5, "tol": 0.5}, 5.6))
        self.assertTrue(regress.output_matches(5, 5.0))
        self.assertFalse(regress.output_matches(5, "5"))
        self.assertTrue(regress.output_matches("A", "A"))
        self.assertTrue(regress.output_matches({"value": "A"}, "A"))
        self.assertFalse(regress.output_matches(True, 1))
        case = GoldenCase(expect_status="any", expect_outputs={"n": 3, "m": {"value": 1, "tol": 1}})
        self.assertEqual(regress.evaluate(case, "failed", {"n": 3, "m": 1.5}), (True, []))
        ok, reasons = regress.evaluate(case, "ok", {"n": 4})
        self.assertFalse(ok)
        self.assertEqual(len(reasons), 2)

    # -- 回歸 --------------------------------------------------------------
    def test_regress_report_baseline_and_regressed(self):
        bright = self.upload([220, 200], expect_status="ok")
        dark = self.upload([10], expect_status="ng")
        wrong = self.upload([15], expect_status="ok")  # 故意標錯：暗圖期望 ok → mismatch
        GoldenCase.objects.filter(pk=bright[0]["id"]).update(expect_outputs={"mean": {"value": 220, "tol": 5}})

        r = self.client.post(f"/api/vision/flows/{self.flow.id}/regress", data=json.dumps({"save_baseline": True}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["match"], 3)
        self.assertEqual(body["mismatch"], 1)
        self.assertEqual(body["confusion"], {"tp": 1, "fp": 1, "tn": 2, "fn": 0})
        self.assertEqual(body["regressed"], [])
        self.assertTrue(body["baseline_saved"])
        self.assertEqual(body["baseline_version"], self.flow.version)
        self.assertEqual(GoldenBaseline.objects.count(), 1)
        rows = {c["case_id"]: c for c in body["cases"]}
        self.assertFalse(rows[wrong[0]["id"]]["match"])
        self.assertIsNotNone(rows[wrong[0]["id"]]["image_ref"])  # mismatch 才有 preview 影像
        self.assertEqual(rows[wrong[0]["id"]]["node"], "rng")
        self.assertIsNone(rows[bright[0]["id"]]["image_ref"])
        self.assertIsNone(rows[bright[0]["id"]]["changed_since_baseline"])
        self.assertTrue(all(c["duration_ms"] >= 0 for c in body["cases"]))
        # 非 preview：regress run 會進統計，影像不留在快取
        self.assertGreaterEqual(runner.runtime(self.flow.id).stats.runs, 4)

        r = self.client.get(f"{self.url}/baseline")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["baseline"]["case_count"], 4)
        self.assertIn(str(dark[0]["id"]), r.json()["baseline"]["results"])

        # 把門檻拉高：亮圖全部變 ng → 2 個 regressed（bright），wrong 那張 improved？否：它期望 ok 仍不符
        graph = gate_graph(self.source.id, low=250)
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/regress", data=json.dumps({"graph": graph, "fail_under": 0.9}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["baseline_version"], self.flow.version)
        self.assertTrue(body["graph_override"])
        self.assertFalse(body["passed"])
        regressed = {x["case_id"]: x for x in body["regressed"]}
        self.assertEqual(set(regressed), {bright[0]["id"], bright[1]["id"]})
        self.assertEqual(regressed[bright[0]["id"]]["was"], "ok")
        self.assertEqual(regressed[bright[0]["id"]]["now"], "ng")
        self.assertEqual(regressed[bright[0]["id"]]["node"], "rng")
        self.assertEqual(body["improved"], [])
        rows = {c["case_id"]: c for c in body["cases"]}
        self.assertTrue(rows[bright[0]["id"]]["changed_since_baseline"])
        self.assertFalse(rows[dark[0]["id"]]["changed_since_baseline"])
        self.assertEqual(GoldenBaseline.objects.count(), 1)  # 沒 save_baseline

        # 用壞掉的圖存基準，再用正確的圖跑 → 亮圖 improved；標錯那張仍 mismatch 但不算 regressed
        regress.run_regression(self.flow, graph=graph, save_baseline=True)
        self.assertEqual(GoldenBaseline.objects.count(), 2)
        body = regress.run_regression(self.flow)
        self.assertEqual({x["case_id"] for x in body["improved"]}, {bright[0]["id"], bright[1]["id"]})
        self.assertEqual(body["regressed"], [])
        self.assertEqual(body["mismatch"], 1)
        # 修正標錯的那張 → 全部 match
        GoldenCase.objects.filter(pk=wrong[0]["id"]).update(expect_status="ng")
        self.assertEqual(regress.run_regression(self.flow)["mismatch"], 0)

    def test_regress_missing_image_file_is_failed_case(self):
        item = self.upload([200], expect_status="ok")[0]
        Path(GoldenCase.objects.get(pk=item["id"]).image_path).unlink()
        body = regress.run_regression(self.flow)
        row = body["cases"][0]
        self.assertEqual(row["status"], "failed")
        self.assertFalse(row["match"])
        self.assertIsNone(row["image_ref"])

    def test_regress_cli_exit_codes(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command("regress", str(self.flow.id), stdout=out)
        self.assertEqual(cm.exception.code, 3)  # 沒有 case

        self.upload([220], expect_status="ok")
        self.upload([10], expect_status="ok")  # 錯標 → rate 0.5
        out = io.StringIO()
        call_command("regress", str(self.flow.id), "--fail-under", "0.5", "--save-baseline", stdout=out)
        self.assertIn("PASS", out.getvalue())
        self.assertEqual(GoldenBaseline.objects.count(), 1)

        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command("regress", self.flow.name, "--json", stdout=out)
        self.assertEqual(cm.exception.code, 1)
        data = json.loads(out.getvalue())
        self.assertEqual(data["mismatch"], 1)
        self.assertEqual(data["baseline_version"], self.flow.version)

    # -- 權限 --------------------------------------------------------------
    def test_permissions(self):
        owner = User.objects.create_user("owner", password="x")
        other = User.objects.create_user("other", password="x")
        self.flow.owner = owner
        self.flow.save()
        t_owner = AuthToken.issue(owner)
        t_other = AuthToken.issue(other)
        h_owner = {"HTTP_AUTHORIZATION": f"Bearer {t_owner}"}
        h_other = {"HTTP_AUTHORIZATION": f"Bearer {t_other}"}
        # 未登入
        self.assertEqual(self.client.get(self.url).status_code, 401)
        # 流程屬於產線：另一位工程師看得到，也能加案例（角色模型，不看擁有者）
        self.assertEqual(self.client.get(self.url, **h_other).status_code, 200)
        self.assertEqual(self.client.post(self.url, data={"images": [png(200)]}, **h_other).status_code, 201)
        # 擁有者可以
        r = self.client.post(self.url, data={"images": [png(200)], "expect_status": "ok"}, **h_owner)
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["items"][0]["id"]
        self.assertEqual(self.client.get(f"{self.url}/{cid}/image").status_code, 401)
        self.assertEqual(self.client.get(f"{self.url}/{cid}/image?token={t_owner}").status_code, 200)
        self.assertEqual(self.client.get(f"{self.url}/{cid}/image?token={t_other}").status_code, 200)
        # 沒有建立者的流程（owner=None）照樣是工程師的責任範圍
        self.flow.owner = None
        self.flow.save()
        self.assertEqual(self.client.get(self.url, **h_other).json()["can_manage"], True)
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/regress", data=json.dumps({}), content_type="application/json", **h_other)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.client.delete(f"{self.url}/{cid}", **h_other).status_code, 204)
        # 操作員不能碰 Golden（回歸與基準是工程師的事）
        op = User.objects.create_user("goldenop", password="x")
        UserPref.objects.create(user=op, role="operator")
        h_op = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(op)}"}
        self.assertEqual(self.client.get(self.url, **h_op).json()["can_manage"], False)
        self.assertEqual(self.client.post(self.url, data={"images": [png(200)]}, **h_op).status_code, 403)
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow.id}/regress", data=json.dumps({}), content_type="application/json", **h_op).status_code, 403)
