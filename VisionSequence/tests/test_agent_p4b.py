"""PRODUCT-DIRECTION v2 P4b：助手產出封裝成複合工具、助手 ↔ 影像視窗互動協定（roi／crop／preview）、離線時明確退化到工具箱。"""

from __future__ import annotations

import json
import time
from unittest import mock

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import AuthToken
from apps.core.errors import ValidationError
from apps.vision import composites, engine
from apps.vision.agent import actions, help as help_mod, loop, providers, service
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import CompositeTool, Flow
from apps.vision.tools import register_builtins
from tests.test_agent_loop import LLM, _upload, _wait, call, part_image, reply, scripted


def run(graph: dict, image: np.ndarray) -> engine.RunReport:
    compiled = compile_graph(validate_graph(json.loads(json.dumps(graph))))
    return engine.execute(compiled, flow_id=1, flow_version=1, trigger="test", grab=lambda _sid: None, asset_path=lambda _aid: None, preview=True, input_image=image)


def count_graph() -> dict:
    return {"nodes": [{"id": "src", "type": "image_source", "params": {"mode": "input"}, "position": {"x": 0, "y": 0}},
                      {"id": "gray", "type": "grayscale", "params": {}, "position": {"x": 200, "y": 0}},
                      {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": 100, "invert": True}, "position": {"x": 400, "y": 0}},
                      {"id": "blob", "type": "blob", "params": {"min_area": 50}, "position": {"x": 600, "y": 0}, "interface": {"outputs": [{"key": "count", "alias": "holes"}]}},
                      {"id": "rng", "type": "in_range", "params": {"low": 5, "high": 5, "on_false": "reject"}, "position": {"x": 800, "y": 0}}],
            "edges": [{"source": "src", "source_handle": "image", "target": "gray", "target_handle": "image"},
                      {"source": "gray", "source_handle": "image", "target": "thr", "target_handle": "image"},
                      {"source": "thr", "source_handle": "image", "target": "blob", "target_handle": "image"},
                      {"source": "blob", "source_handle": "count", "target": "rng", "target_handle": "value"}]}


class EncapsulateTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def setUp(self):
        composites.invalidate()
        self.admin = User.objects.create_user("p4b-admin", is_staff=True)

    def test_encapsulate_matches_the_frontend_rules_and_runs_the_same(self):
        graph = count_graph()
        before = run(graph, part_image(5))
        enc = composites.encapsulate(graph, ["gray", "thr", "blob"], "count_holes", "Count holes", expose_params=True)
        self.assertEqual([p["key"] for p in enc["interface"]["inputs"]], ["gray:image"])
        self.assertEqual([p["key"] for p in enc["interface"]["outputs"]], ["blob:count"])
        params = {p["key"]: p for p in enc["interface"]["params"]}
        self.assertIn("thr:threshold", params)
        self.assertTrue(params["thr:threshold"]["teach"])
        self.assertIn("blob:roi", params)
        self.assertNotIn("thr:block", params, "parameters hidden by the current threshold method stay internal")
        self.assertEqual(enc["instance"]["type"], "composite:count_holes")
        self.assertEqual(enc["instance"]["interface"], {"outputs": [{"key": "blob:count", "alias": "holes"}]})
        self.assertTrue(all("interface" not in n or not any("alias" in o for o in n["interface"].get("outputs", [])) for n in enc["tool_graph"]["nodes"]))
        self.assertEqual({(e["source"], e["source_handle"], e["target"], e["target_handle"]) for e in enc["graph"]["edges"]},
                         {("src", "image", "count_holes", "gray:image"), ("count_holes", "blob:count", "rng", "value")})
        composites.create(self.admin, {"key": "count_holes", "label": "Count holes", "graph": enc["tool_graph"], "interface": enc["interface"]})
        after = run(enc["graph"], part_image(5))
        self.assertEqual((before.status, after.status), ("ok", "ok"))
        self.assertEqual(before.outputs["holes"], after.outputs["holes"])
        self.assertEqual(after.nodes["count_holes"].outputs["blob:count"], 5)
        with self.assertRaises(ValidationError):
            composites.encapsulate(graph, ["nope"], "x", "X")

    def test_save_tool_endpoint_creates_the_tool_and_a_flow_using_it(self):
        user = User.objects.create_superuser("p4b-super", "", "password")
        auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(user)}"}
        body = {"graph": count_graph(), "key": "ai_count", "label": "AI count", "description": "Count the holes", "flow_name": "AI count flow"}
        res = self.client.post("/api/vision/agent/save-tool", data=json.dumps(body), content_type="application/json", **auth)
        self.assertEqual(res.status_code, 201, res.content)
        out = res.json()
        row = CompositeTool.objects.get(key="ai_count")
        self.assertFalse(row.builtin)
        self.assertEqual(out["tool"]["id"], row.id)
        flow = Flow.objects.get(pk=out["flow_id"])
        self.assertEqual(flow.kind, "flow")
        types = {n["id"]: n["type"] for n in flow.graph["nodes"]}
        self.assertEqual(types, {"src": "image_source", "ai_count": "composite:ai_count"})
        self.assertEqual(out["instance"], "ai_count")
        composites.invalidate()
        report = run(flow.graph, part_image(5))
        self.assertEqual(report.status, "ok", report.to_dict())
        self.assertEqual(report.outputs["holes"], 5)
        # 同名工具再存一次 → 409；只有取像的流程 → 422
        again = self.client.post("/api/vision/agent/save-tool", data=json.dumps({**body, "flow_name": "Another"}), content_type="application/json", **auth)
        self.assertEqual(again.status_code, 409)
        empty = self.client.post("/api/vision/agent/save-tool", data=json.dumps({**body, "key": "k2", "graph": {"nodes": [count_graph()["nodes"][0]], "edges": []}}), content_type="application/json", **auth)
        self.assertEqual(empty.status_code, 422)
        # 操作員沒有 tools.edit
        worker = User.objects.create_user("p4b-worker", password="x")
        from apps.accounts.models import UserPref

        UserPref.objects.update_or_create(user=worker, defaults={"role": "operator"})
        denied = self.client.post("/api/vision/agent/save-tool", data=json.dumps({**body, "key": "k3"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {AuthToken.issue(worker)}")
        self.assertEqual(denied.status_code, 403)


class ViewerProtocolTests(TestCase):
    def setUp(self):
        self.state = service.build_state("generate", [part_image(5)], [], "應該有 5 個孔", labels=["ok"])
        self.state.principal = mock.Mock(can=mock.Mock(return_value=True), can_execute=mock.Mock(return_value=True))

    def test_ask_user_accepts_viewer_kinds_with_their_targets(self):
        res = actions.h_ask_user(self.state, {"questions": [
            {"id": "mark", "text": "Draw the locator mark", "kind": "crop", "target": "tm", "image": 1},
            {"id": "area", "text": "Draw the search area", "kind": "roi", "node": "blob", "param": "roi", "shapes": ["rect", "circle", "bogus"]},
            {"id": "look", "text": "Check the threshold output", "kind": "preview", "node": "thr", "port": "image"},
        ]})
        self.assertTrue(res["waiting_for_user"])
        q = {item["id"]: item for item in self.state.questions}
        self.assertEqual((q["mark"]["kind"], q["mark"]["target"], q["mark"]["shapes"], q["mark"]["image"]), ("crop", "tm", ["rect"], 1))
        self.assertEqual((q["area"]["node"], q["area"]["param"], q["area"]["shapes"]), ("blob", "roi", ["rect", "circle"]))
        self.assertEqual((q["look"]["node"], q["look"]["port"]), ("thr", "image"))

    def test_platform_applies_crop_and_roi_answers_before_the_model_continues(self):
        actions.dispatch(self.state, "draft_from_rules", {})
        graph = self.state.graph
        graph["nodes"].append({"id": "tm", "type": "template_match", "params": {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 640, "h": 480}}, "position": {"x": 900, "y": 0}})
        graph["edges"].append({"source": graph["nodes"][0]["id"], "source_handle": "image", "target": "tm", "target_handle": "image"})
        self.state.graph = validate_graph(graph)
        blob = next(n["id"] for n in self.state.graph["nodes"] if n["type"] == "blob")
        questions = [{"id": "mark", "kind": "crop", "text": "Locator mark", "target": "tm", "port": "template_image", "image": 1},
                     {"id": "area", "kind": "roi", "text": "Search area", "node": blob, "param": "roi"},
                     {"id": "look", "kind": "preview", "text": "Preview", "node": blob},
                     {"id": "count", "kind": "number", "text": "How many?"}]
        answers = [{"id": "mark", "value": json.dumps({"shape": "rect", "x": 70, "y": 210, "w": 60, "h": 60})},
                   {"id": "area", "value": {"shape": "circle", "cx": 320, "cy": 240, "r": 200}},
                   {"id": "look", "value": "shown"},
                   {"id": "count", "value": "5"}]
        notes = actions.apply_viewer_answers(self.state, questions, answers)
        self.assertEqual(len(notes), 3)
        self.assertIn("crop applied", notes[0])
        pic = next(n for n in self.state.graph["nodes"] if n["id"] == "pic_tm")
        self.assertEqual(pic["params"]["role"], "reference")
        self.assertTrue(any(e["source"] == "pic_tm" and e["target"] == "tm" and e["target_handle"] == "template_image" for e in self.state.graph["edges"]))
        self.assertEqual(next(n for n in self.state.graph["nodes"] if n["id"] == blob)["params"]["roi"], {"shape": "circle", "cx": 320, "cy": 240, "r": 200})
        self.assertEqual(answers[0]["value"]["shape"], "rect", "the model sees the region as a dict")
        self.assertIn("viewed the preview", notes[2])
        turn = loop.answer_turn(answers, notes)
        self.assertIn("平台已依回答處理", turn["content"][0]["text"])
        # 沒畫區域＝不套用、不炸
        self.assertEqual(actions.apply_viewer_answers(self.state, questions[:1], [{"id": "mark", "value": ""}]), ["mark: no region was drawn"])


class ViewerProtocolJobTests(TransactionTestCase):
    def test_job_crop_question_is_answered_from_the_viewer_and_applied(self):
        ref = _upload(self.client, part_image(5))
        seen: list[str] = []
        roles: list[list[str]] = []
        script = scripted(reply(call("draft_from_rules")), reply(call("ask_user", {"questions": [{"id": "mark", "text": "Draw the mark", "kind": "crop", "target": "tm", "image": 1}]})),
                          reply(call("run_trial")), reply(call("finish", {"rationale": "done"})))

        def fake(settings, system, history, tools, *, timeout=None):
            roles.append([h["role"] for h in history])
            last = history[-1]
            if last["role"] == "user" and isinstance(last.get("content"), list) and last["content"] and last["content"][0].get("type") == "text":
                seen.append(str(last["content"][0]["text"]))
            return script(settings, system, history, tools, timeout=timeout)

        with mock.patch.object(providers, "complete_tools", side_effect=fake), mock.patch.object(providers, "resolve", return_value=LLM):
            res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "generate", "images": [ref], "prompt": "應該有 5 個孔"}), content_type="application/json")
            job_id = res.json()["id"]
            body = _wait(self.client, job_id)
            self.assertEqual(body["status"], "needs_input")
            self.assertEqual((body["questions"][0]["kind"], body["questions"][0]["target"], body["questions"][0]["shapes"]), ("crop", "tm", ["rect"]))
            # 目標節點不存在：平台回報而不是炸掉
            res = self.client.post(f"/api/vision/agent/jobs/{job_id}/answer", data=json.dumps({"answers": [{"id": "mark", "value": json.dumps({"shape": "rect", "x": 70, "y": 210, "w": 60, "h": 60})}]}), content_type="application/json")
            self.assertEqual(res.status_code, 200, res.content)
            body = _wait(self.client, job_id)
        self.assertEqual(body["status"], "done", (body.get("error"), roles, body["steps"]))
        answered = [text for text in seen if "使用者回答" in text]
        self.assertTrue(answered and "平台已依回答處理" in answered[0] and "crop applied" in answered[0], seen)
        self.assertTrue(any(s["kind"] == "answer" for s in body["steps"]))


class OfflineDegradeTests(TestCase):
    def _chat(self, body: dict):
        return self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json")

    def test_offline_build_requests_point_to_the_inspection_tools(self):
        graph = {"nodes": [{"id": "src", "type": "image_source", "params": {"mode": "input"}}], "edges": []}
        r = self._chat({"message": "add count 5", "context": {"kind": "inspect", "route": "/flows/1/inspect", "flow_id": 1, "graph": graph, "lang": "zh-Hant"}})
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        self.assertEqual(out["kind"], "tasklist")
        self.assertEqual(out["actions"], [{"kind": "open_toolbox", "category": "inspection", "label": "開啟檢測任務工具"}])
        self.assertTrue(any("離線規則模式" in w for w in out["warnings"]))
        r = self._chat({"message": "Please build an inspection that checks the label is present", "context": {"kind": "page", "route": "/flows", "lang": "en"}})
        out = r.json()
        self.assertEqual(out["kind"], "help")
        self.assertEqual(out["actions"][0], {"kind": "open_toolbox", "category": "inspection", "label": "Open the Inspection tasks tools"})
        self.assertTrue(any("offline rule mode" in w for w in out["warnings"]))
        # 一般問句不加
        r = self._chat({"message": "Where is the batch page?", "context": {"kind": "page", "route": "/flows", "lang": "en"}})
        self.assertFalse(any(a["kind"] == "open_toolbox" for a in r.json()["actions"]))

    def test_validate_actions_keeps_open_toolbox_and_llm_settings_skip_the_degrade(self):
        self.assertEqual(help_mod.validate_actions([{"kind": "open_toolbox", "category": "inspection", "label": ""}], {"lang": "zh-Hans"}), [{"kind": "open_toolbox", "category": "inspection", "label": "打开检测任务工具"}])
        self.assertTrue(help_mod.wants_build("幫我建立一條檢測流程"))
        self.assertFalse(help_mod.wants_build("批次測試頁在哪裡"))
        self.assertFalse(service.has_llm(providers.AgentSettings()))
        self.assertTrue(service.has_llm(LLM))


def _png(image: np.ndarray) -> SimpleUploadedFile:
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return SimpleUploadedFile("img.png", buf.tobytes(), content_type="image/png")


_ = (time, _png, cv2, SimpleUploadedFile)
