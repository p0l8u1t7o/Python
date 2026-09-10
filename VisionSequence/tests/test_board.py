"""看板：設定的清洗、看板資料的組成（影像挑選、公差判定、今日良率、變數）、PATCH 權限與 API。"""

from __future__ import annotations

import json

from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.vision import board, variables
from apps.vision.models import Flow, FlowRunHourly, ImageSource
from apps.vision.runner import runner


class SanitizeTests(TestCase):
    def test_keeps_only_valid_fields_and_clamps(self):
        raw = {
            "title": "x" * 200, "image": "node_a", "overlays": 0, "show_counts": "yes", "junk": 1,
            "values": ["width", {"key": "height", "label": "H", "unit": "mm", "decimals": 9, "low": "9.8", "high": "bad"}, {"nope": 1}, 7],
            "variables": ["parts", "", 12],
        }
        out = board.sanitize(raw)
        self.assertEqual(len(out["title"]), 80)
        self.assertEqual(out["image"], "node_a")
        self.assertFalse(out["overlays"])
        self.assertTrue(out["show_counts"])
        self.assertNotIn("junk", out)
        self.assertEqual(out["values"][0], {"key": "width"})
        self.assertEqual(out["values"][1], {"key": "height", "label": "H", "unit": "mm", "decimals": 6, "low": 9.8})
        self.assertEqual(len(out["values"]), 2)
        self.assertEqual(out["variables"], ["parts", "12"])
        self.assertEqual(board.sanitize("nope"), {})
        self.assertEqual(board.sanitize({}), {})
        self.assertEqual(board.effective({})["show_verdict"], True)


class BuildTests(TestCase):
    def setUp(self):
        self.flow = Flow.objects.create(name="b", graph={"nodes": [], "edges": []})

    def run_dict(self):
        return {
            "id": "r1", "status": "ng", "started_at": 1.0, "duration_ms": 12.5, "trigger": "api", "recipe": "",
            "outputs": {"judge": "NG", "width": 10.25, "height": 4.0, "text": "OK,10.25", "judge_label": "gap"},
            "nodes": {
                "src": {"status": "ok", "outputs": {"image": {"ref": "r1:src:image", "width": 64, "height": 48}}, "overlays": []},
                "blur": {"status": "ok", "outputs": {"image": {"ref": "r1:blur:image", "width": 64, "height": 48}}, "overlays": [{"kind": "point", "x": 1, "y": 2}]},
                "j": {"status": "ng", "outputs": {"verdict": "NG"}, "overlays": []},
            },
        }

    def test_default_board_lists_every_named_output_and_source_image(self):
        out = board.build(self.flow, self.run_dict())
        self.assertEqual([v["key"] for v in out["values"]], ["width", "height", "text"])
        self.flow.graph = {"nodes": [{"id": "src", "type": "image_source"}, {"id": "blur", "type": "blur"}], "edges": []}
        out = board.build(self.flow, self.run_dict())
        self.assertEqual(out["run"]["image"]["ref"], "r1:src:image")
        self.assertEqual(out["run"]["verdict"], "NG")
        self.assertEqual(out["run"]["label"], "gap")
        self.assertEqual(len(out["run"]["overlays"]), 1)
        self.assertEqual(out["flow"]["title"], "b")
        self.assertIsNotNone(out["counts"])

    def test_default_board_prefers_draw_result_when_present(self):
        run = self.run_dict()
        run["nodes"]["draw"] = {
            "status": "ok",
            "outputs": {"image": {"ref": "r1:draw:image", "width": 64, "height": 48}},
            "overlays": [],
        }
        self.flow.graph = {"nodes": [{"id": "src", "type": "image_source"}, {"id": "draw", "type": "draw_result"}], "edges": []}
        out = board.build(self.flow, run)
        self.assertEqual(out["run"]["image"]["ref"], "r1:draw:image")

    def test_acquisition_types_work_with_arbitrary_ids_and_precedence(self):
        run = self.run_dict()
        run["nodes"] = {"n3": run["nodes"]["src"], "draw": run["nodes"]["blur"]}
        for kind in board.ACQUIRE_TYPES:
            with self.subTest(kind=kind):
                self.flow.graph = {"nodes": [{"id": "n3", "type": kind}, {"id": "draw", "type": "threshold"}], "edges": []}
                self.assertEqual(board.build(self.flow, run)["run"]["image"]["ref"], "r1:src:image")
        run["nodes"]["n7"] = {"outputs": {"image": {"ref": "r1:n7:image", "width": 64, "height": 48}}}
        self.flow.graph["nodes"].append({"id": "n7", "type": "draw_result"})
        self.assertEqual(board.build(self.flow, run)["run"]["image"]["ref"], "r1:n7:image")
        self.flow.board = {"image": "draw"}
        self.assertEqual(board.build(self.flow, run)["run"]["image"]["ref"], "r1:blur:image")

    def test_configured_board_picks_image_formats_and_judges_tolerance(self):
        self.flow.board = {"title": "Line 1", "image": "src", "overlays": False, "show_counts": False,
                           "values": [{"key": "width", "label": "Width", "unit": "mm", "decimals": 1, "low": 9.8, "high": 10.2},
                                      {"key": "height", "low": 5}, {"key": "missing"}]}
        out = board.build(self.flow, self.run_dict(), variables={"parts": 3, "lot": "A"}, stats={"runs": 1})
        self.assertEqual(out["flow"]["title"], "Line 1")
        self.assertEqual(out["run"]["image"]["ref"], "r1:src:image")
        self.assertEqual(out["run"]["overlays"], [])
        self.assertIsNone(out["counts"])
        width, height, missing = out["values"]
        self.assertEqual((width["label"], width["unit"], width["text"], width["ok"]), ("Width", "mm", "10.2", False))  # 10.25 > 10.2
        self.assertEqual((height["text"], height["ok"]), ("4", False))  # 沒有小數位設定：整數就整數
        self.assertEqual((missing["present"], missing["ok"], missing["text"]), (False, None, ""))
        self.assertEqual(out["variables"], {"parts": 3, "lot": "A"})  # 沒指定就全部
        self.flow.board["variables"] = ["lot", "nope"]
        self.assertEqual(board.build(self.flow, self.run_dict(), variables={"parts": 3, "lot": "A"})["variables"], {"lot": "A", "nope": None})

    def test_without_a_run(self):
        out = board.build(self.flow, None)
        self.assertIsNone(out["run"])
        self.assertEqual(out["values"], [])
        self.assertEqual(out["counts"]["total"], 0)

    def test_today_counts_from_the_hourly_rollup(self):
        now = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        FlowRunHourly.objects.create(flow=self.flow, hour=now, ok=8, ng=2, failed=0)
        FlowRunHourly.objects.create(flow=self.flow, hour=now - timezone.timedelta(days=2), ok=100, ng=0, failed=0)  # 昨天以前不算
        counts = board.today_counts(self.flow.id)
        self.assertEqual((counts["total"], counts["ok"], counts["ng"], counts["yield"]), (10, 8, 2, 80.0))


class ApiTests(TestCase):
    def setUp(self):
        self.flow = Flow.objects.create(name="api", graph={"nodes": [], "edges": []})
        runner.forget(self.flow.id)  # 流程 id 會被別的測試重用，先清掉它們留下的 run

    def test_patch_and_read_back(self):
        body = {"board": {"title": "L1", "values": [{"key": "width", "low": 1, "high": 2}], "junk": 1}}
        r = self.client.patch(f"/api/vision/flows/{self.flow.id}", data=json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["board"], {"title": "L1", "values": [{"key": "width", "low": 1.0, "high": 2.0}]})
        r = self.client.get(f"/api/vision/flows/{self.flow.id}/board")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["flow"]["title"], "L1")
        self.assertIsNone(r.json()["run"])
        self.assertEqual(r.json()["values"][0]["key"], "width")
        self.assertEqual(self.client.get("/api/vision/flows/999/board").status_code, 404)

    def test_operator_cannot_change_the_board(self):
        r = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}), content_type="application/json")
        admin = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['token']}"}
        self.client.post("/api/users", data=json.dumps({"username": "op", "password": "pass123", "role": "operator"}), content_type="application/json", **admin)
        token = self.client.post("/api/auth/login", data=json.dumps({"username": "op", "password": "pass123"}), content_type="application/json").json()["token"]
        op = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        r = self.client.patch(f"/api/vision/flows/{self.flow.id}", data=json.dumps({"board": {"title": "x"}}), content_type="application/json", **op)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(f"/api/vision/flows/{self.flow.id}/board", **op).status_code, 200)


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class LiveTests(TransactionTestCase):
    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)
        source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 32, "height": 24})
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": source.id}},
                {"id": "i", "type": "intensity", "params": {}},
                {"id": "o", "type": "output", "params": {"name": "mean"}},
                {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
            ],
            "edges": [{"source": "src", "target": "i"}, {"source": "i", "source_handle": "mean", "target": "o", "target_handle": "value"}],
        }
        self.flow = Flow.objects.create(name="live", graph=graph, board={"values": [{"key": "mean", "decimals": 0, "low": 0}]})
        runner.forget(self.flow.id)  # TransactionTestCase 會重用流程 id：先清掉別的測試留下的執行狀態與統計
        self.addCleanup(runner.forget, self.flow.id)

    def test_board_reflects_the_latest_run_and_variables(self):
        variables.store.set(self.flow.id, "lot", "A17")
        runner.run_sync(self.flow, trigger="api")
        r = self.client.get(f"/api/vision/flows/{self.flow.id}/board")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["run"]["verdict"], "OK")
        self.assertIsNotNone(body["run"]["image"])
        self.assertEqual(body["values"][0]["key"], "mean")
        self.assertTrue(body["values"][0]["ok"], body)
        self.assertEqual(body["variables"]["lot"], "A17")
        self.assertEqual(body["stats"]["runs"], 1)
