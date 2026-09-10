"""清單提案：離線語料、供應商邊界、確認與核心來回。"""

import copy
import json
from unittest import mock

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from apps.vision import graphdiff, inspect
from apps.vision.agent import providers, tasklist
from tests.test_inspect import base_graph
from apps.accounts.models import AuthToken, UserPref


CORPUS = [
    ("量外徑 70±0.5 px", "measure_diameter", "upper_tol", .5, "confirmed"),
    ("量內徑 60±0.3 px", "measure_diameter", "edge", "inner", "confirmed"),
    ("直徑 70 +0.2/-0.1 px", "measure_diameter", "lower_tol", -.1, "confirmed"),
    ("直徑 69.5～70.5 px", "measure_diameter", "nominal", 70., "confirmed"),
    ("直徑下限 69.5 上限 70.5 px", "measure_diameter", "upper_tol", .5, "confirmed"),
    ("直徑 70±0.5", "measure_diameter", "unit", "px", "assumed"),
    ("直徑 70±0.5 mm", "measure_diameter", "unit", "mm", "missing"),
    ("量距離 5±0.2 px", "measure_distance", "nominal", 5., "confirmed"),
    ("間距 5 +0.2/-0.1 px", "measure_distance", "lower_tol", -.1, "confirmed"),
    ("孔距 30±1 px", "measure_distance", "mode", "hole_centres", "confirmed"),
    ("定位工件 20°", "locate_part", "angle_range", 20., "confirmed"),
    ("定位工件", "locate_part", "template_images", [], "missing"),
    ("數量 6", "count_objects", "min_count", 6., "confirmed"),
    ("數量至少 3 最多 8", "count_objects", "max_count", 8., "confirmed"),
    ("檢查有無", "check_presence", "method", "template", "assumed"),
    ("檢查缺件", "check_presence", "expected", "present", "confirmed"),
    ("檢查異物", "check_presence", "expected", "absent", "confirmed"),
    ("檢查圓周缺口", "inspect_circular_surface", "roi", None, "missing"),
    ("檢查毛邊", "inspect_edge_defect", "method", "simple", "assumed"),
    ("讀碼應為 ABC", "read_and_verify", "expected", "ABC", "confirmed"),
    ("讀取字元應為 XYZ", "read_and_verify", "mode", "text", "confirmed"),
    ("量真圓度", "measure_diameter", "mode", "roundness", "confirmed"),
    ("measure outer diameter 70±0.5 px", "measure_diameter", "upper_tol", .5, "confirmed"),
    ("measure inner diameter 60±0.3 px", "measure_diameter", "edge", "inner", "confirmed"),
    ("diameter 70 +0.2/-0.1 px", "measure_diameter", "lower_tol", -.1, "confirmed"),
    ("diameter 69.5 to 70.5 px", "measure_diameter", "nominal", 70., "confirmed"),
    ("diameter lower limit 69.5 upper limit 70.5 px", "measure_diameter", "upper_tol", .5, "confirmed"),
    ("diameter 70±0.5", "measure_diameter", "unit", "px", "assumed"),
    ("diameter 70±0.5 mm", "measure_diameter", "unit", "mm", "missing"),
    ("measure distance 5±0.2 px", "measure_distance", "nominal", 5., "confirmed"),
    ("spacing 5 +0.2/-0.1 px", "measure_distance", "lower_tol", -.1, "confirmed"),
    ("hole centres 30±1 px", "measure_distance", "mode", "hole_centres", "confirmed"),
    ("locate part 20°", "locate_part", "angle_range", 20., "confirmed"),
    ("locate part", "locate_part", "template_images", [], "missing"),
    ("count 6 objects", "count_objects", "min_count", 6., "confirmed"),
    ("count at least 3 at most 8", "count_objects", "max_count", 8., "confirmed"),
    ("check presence", "check_presence", "method", "template", "assumed"),
    ("check missing part", "check_presence", "expected", "present", "confirmed"),
    ("check foreign object", "check_presence", "expected", "absent", "confirmed"),
    ("check circular surface", "inspect_circular_surface", "roi", None, "missing"),
    ("check edge defect", "inspect_edge_defect", "method", "simple", "assumed"),
    ("read code expected ABC", "read_and_verify", "expected", "ABC", "confirmed"),
    ("OCR expected XYZ", "read_and_verify", "mode", "text", "confirmed"),
    ("measure roundness", "measure_diameter", "mode", "roundness", "confirmed"),
]


class TaskListTests(SimpleTestCase):
    def test_bilingual_corpus(self):
        for text, kind, key, value, status in CORPUS:
            with self.subTest(text=text):
                draft = tasklist.parse(text, graph=base_graph())[0]
                self.assertEqual(draft["kind"], kind)
                self.assertEqual(draft["fields"][key]["value"], value)
                self.assertEqual(draft["fields"][key]["status"], status)

    def test_multi_task_and_operations(self):
        self.assertEqual(len(tasklist.parse("外徑 70±0.5、內徑 60±0.3")), 2)
        graph = inspect.build(base_graph(), {"kind": "count_objects", "task_id": "one"})
        for text, op in (("改成第 1 項數量 4", "update"), ("change task 1 count to 4", "update"), ("刪掉第 1 項", "remove"), ("delete item 1", "remove")):
            draft = tasklist.parse(text, graph=graph)[0]
            self.assertEqual((draft["op"], draft["task_id"]), (op, "one"))
        for text in ("再跑一次", "run again"):
            self.assertEqual(tasklist.parse(text)[0]["op"], "run")

    def test_apply_confirmations_and_roundtrip(self):
        graph = base_graph()
        original = copy.deepcopy(graph)
        draft = tasklist.parse("量外徑 70±0.5 px", graph=graph)[0]
        self.assertEqual(tasklist.apply(graph, [draft], {})["graph"], graph)
        confirm = {draft["draft_id"]: {"confirmed": True, "fields": {"roi": {"value": {"shape": "circle", "cx": 100, "cy": 100, "r": 40}}}}}
        out = tasklist.apply(graph, [draft], confirm)
        self.assertEqual(len(out["applied"]), 1, out["skipped"])
        self.assertEqual(out["tasks"], inspect.read(out["graph"])["tasks"])
        self.assertEqual(graph, original)
        self.assertGreater(graphdiff.diff(graph, out["graph"])["count"], 0)
        target = out["tasks"][0]["task_id"]
        update = {"draft_id": "u", "kind": "measure_diameter", "op": "update", "task_id": target,
                  "fields": {"nominal": tasklist.cell(99), "upper_tol": tasklist.cell(.2, "confirmed", "user")}, "regions": []}
        changed = tasklist.apply(out["graph"], [update], {"u": {"confirmed": True}})
        self.assertEqual(changed["tasks"][0]["fields"]["nominal"], 70)
        self.assertEqual(changed["tasks"][0]["fields"]["upper_tol"], .2)
        changes = graphdiff.diff(out["graph"], changed["graph"])
        self.assertEqual(changes["count"], 1)
        self.assertEqual(changes["params"][0]["param"], "upper_tol")
        remove = {**update, "op": "remove", "fields": {}}
        removed = tasklist.apply(changed["graph"], [remove], {"u": {"confirmed": True}})
        self.assertEqual(removed["tasks"], [])

    def test_missing_and_ambiguous_source_never_apply(self):
        draft = tasklist.parse("diameter 70±0.5 mm", graph=base_graph())[0]
        out = tasklist.apply(base_graph(), [draft], {draft["draft_id"]: {"confirmed": True, "fields": {k: True for k in draft["fields"]}}})
        self.assertEqual(out["graph"], base_graph())
        self.assertTrue(out["skipped"])
        graph = base_graph()
        graph["nodes"].append({"id": "second", "type": "image_source", "params": {"mode": "input"}})
        draft = tasklist.parse("count 5", graph=graph)[0]
        out = tasklist.apply(graph, [draft], {draft["draft_id"]: {"confirmed": True}})
        self.assertEqual(out["graph"], graph)

    def test_llm_validation_fallback_and_provenance(self):
        settings = providers.AgentSettings(provider="openai", api_key="test")
        good = {"drafts": [{"op": "add", "kind": "measure_diameter", "fields": {"nominal": 70, "upper_tol": .9, "num_rays": 9000}}]}
        with mock.patch.object(providers, "complete", return_value=json.dumps(good)) as complete:
            out = tasklist.propose("diameter 70±0.5 px", "en", base_graph(), settings)
        fields = out["drafts"][0]["fields"]
        self.assertEqual(fields["nominal"]["status"], "confirmed")
        self.assertEqual(fields["nominal"]["source"], "llm")
        self.assertEqual(fields["upper_tol"]["status"], "confirmed")
        self.assertEqual(fields["upper_tol"]["value"], .5)
        self.assertEqual(fields["num_rays"]["status"], "missing")
        self.assertIn('"public_outputs"', complete.call_args.args[1])
        for reply in ("not json", '{"drafts":[{"kind":"invented"}]}'):
            with mock.patch.object(providers, "complete", return_value=reply):
                out = tasklist.propose("count 6", "en", base_graph(), settings)
            self.assertEqual(out["provider"], "offline")
            self.assertEqual(out["drafts"][0]["fields"]["min_count"]["value"], 6)
            self.assertTrue(out["warnings"])

    def test_regions_and_three_questions(self):
        image = np.zeros((97, 333), np.uint8)
        image[20:40, 230:250] = 255
        original = image.copy()
        out = tasklist.propose("count 1", "en", base_graph(), providers.AgentSettings(), image=image)
        region = out["drafts"][0]["regions"][0]
        self.assertEqual(region["status"], "assumed")
        self.assertEqual(region["region"]["x"], 230)
        np.testing.assert_array_equal(image, original)
        out = tasklist.propose("定位工件", "en", base_graph(), providers.AgentSettings())
        self.assertLessEqual(len(out["questions"]), 3)
        self.assertTrue(out["questions"])

    def test_provider_failure_and_field_type_validation(self):
        settings = providers.AgentSettings(provider="openai", api_key="test")
        with mock.patch.object(providers, "complete", side_effect=TimeoutError):
            out = tasklist.propose("count 6", "en", base_graph(), settings)
        self.assertEqual(out["provider"], "offline")
        self.assertTrue(out["warnings"])
        specs = {f["key"]: f for f in tasklist.catalogue()["measure_diameter"]["fields"]}
        for key, value in (("nominal", True), ("nominal", float("nan")), ("edge", "unknown"), ("num_rays", 1), ("roi", {"shape": "circle", "cx": 0, "cy": 0, "r": -1})):
            self.assertFalse(tasklist.valid(specs[key], value))

    def test_remove_keeps_graph_when_outputs_have_consumers(self):
        graph = inspect.build(base_graph(), {"kind": "count_objects", "task_id": "one"})
        graph["nodes"].append({"id": "consumer", "type": "formula", "params": {"expression": "a"}})
        graph["edges"].append({"source": "one_blob", "source_handle": "count", "target": "consumer", "target_handle": "a"})
        draft = tasklist.parse("delete item 1", graph=graph)[0]
        out = tasklist.apply(graph, [draft], {draft["draft_id"]: {"confirmed": True}})
        self.assertEqual(out["graph"], graph)
        self.assertTrue(out["skipped"])

    def test_reference_picture_is_not_an_acquisition_source(self):
        graph = base_graph()
        graph["nodes"].insert(0, {"id": "ref", "type": "fixed_image", "params": {"role": "reference", "images": []}})
        draft = tasklist.parse("count 5", graph=graph)[0]
        out = tasklist.apply(graph, [draft], {draft["draft_id"]: {"confirmed": True}})
        self.assertEqual(len(out["applied"]), 1, out["skipped"])
        self.assertTrue(any(e["source"] == "src" and e["target_handle"] == "image" for e in out["graph"]["edges"]))
        self.assertFalse(any(e["source"] == "ref" for e in out["graph"]["edges"]))


@override_settings(VISION={**settings.VISION, "API_KEY": "stage11-key"})
class TaskListApiTests(TestCase):
    def test_proposal_and_apply_under_lock_and_feature_gate(self):
        user = User.objects.create_superuser("stage11", "", "password")
        token = AuthToken.issue(user)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        payload = {"message": "add count 5", "graph": base_graph()}
        path = "/api/vision/agent/tasklist/propose"
        self.assertEqual(self.client.post(path, data=json.dumps(payload), content_type="application/json").status_code, 401)
        self.client.post("/api/vision/lock", data=json.dumps({"reason": "Production", "ttl_s": 600}), content_type="application/json", HTTP_X_API_KEY="stage11-key")
        with mock.patch("apps.vision.agent.api._settings_for", return_value=providers.AgentSettings()):
            reply = self.client.post(path, data=json.dumps(payload), content_type="application/json", **auth)
            self.assertEqual(reply.status_code, 200, reply.content)
            drafts = reply.json()["drafts"]
            chat = self.client.post("/api/vision/agent/chat", data=json.dumps({"message": payload["message"], "context": {"kind": "inspect", "graph": base_graph()}}), content_type="application/json", **auth)
            self.assertEqual(chat.json()["kind"], "tasklist")
        out = self.client.post("/api/vision/agent/tasklist/apply", data=json.dumps({"graph": base_graph(), "drafts": drafts, "confirmations": {drafts[0]["draft_id"]: {"confirmed": True}}}), content_type="application/json", **auth)
        self.assertEqual(out.status_code, 200, out.content)
        self.assertEqual(len(out.json()["applied"]), 1)
        from apps.vision.models import Flow

        self.assertEqual(Flow.objects.count(), 0)
        worker = User.objects.create_user("worker-stage11", password="password")
        UserPref.objects.update_or_create(user=worker, defaults={"role": "operator"})
        worker_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(worker)}"}
        denied = self.client.post(path, data=json.dumps(payload), content_type="application/json", **worker_auth)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.delete("/api/vision/lock", HTTP_X_API_KEY="stage11-key").status_code, 200)
