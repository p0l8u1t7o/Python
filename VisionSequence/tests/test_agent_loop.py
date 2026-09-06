"""代理迴圈測試（不打外網）：腳本化的假供應商回傳工具呼叫，驗證動作層、迴圈狀態機、預算、提問續跑、背景工作端點與供應商格式轉換。"""

from __future__ import annotations

import json
import time
from unittest import mock

import cv2
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase

from apps.vision.agent import actions, loop, providers, service
from apps.vision.graph import validate_graph


def part_image(holes: int = 5) -> np.ndarray:
    img = np.full((480, 640, 3), 200, np.uint8)
    for i in range(holes):
        cv2.circle(img, (100 + i * 110, 240), 30, (40, 40, 40), -1)
    return img


LLM = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user", mode="agentic")


def call(name: str, args: dict | None = None, cid: str = "") -> providers.ToolCall:
    return providers.ToolCall(cid or f"{name}-{time.time_ns()}", name, args or {})


def reply(*calls: providers.ToolCall, text: str = "") -> providers.ToolReply:
    return providers.ToolReply(text, list(calls))


def scripted(*replies: providers.ToolReply):
    """每次呼叫依序回一個 ToolReply；腳本用完就 finish。"""
    queue = list(replies)

    def fake(settings, system, history, tools, *, timeout=None):
        assert isinstance(system, str) and tools and history
        if queue:
            return queue.pop(0)
        return reply(call("finish", {"rationale": "腳本結束"}))

    return fake


def _upload(client, image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    assert ok
    res = client.post("/api/vision/agent/image", {"image": SimpleUploadedFile("img.png", buf.tobytes(), content_type="image/png")})
    assert res.status_code == 201, res.content
    return res.json()["ref"]


def _wait(client, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/vision/agent/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job 沒有在時限內結束")


class ActionTests(TestCase):
    def test_draft_trial_patch_and_guards(self):
        state = service.build_state("generate", [part_image(5), part_image(4)], [], "應該有 5 個孔", labels=["ok", "ng"])
        out = actions.dispatch(state, "get_state", {})
        self.assertEqual(out["image_count"], 2)
        self.assertEqual(out["expected"], [{"image": 1, "expected": "ok"}, {"image": 2, "expected": "ng"}])
        out = actions.dispatch(state, "draft_from_rules", {})
        self.assertIn("graph", out)
        self.assertIsNotNone(state.graph)
        out = actions.dispatch(state, "run_trial", {})
        self.assertEqual(out["summary"]["matches"], 2)
        self.assertEqual(state.trials, 1)
        out = actions.dispatch(state, "patch_graph", {"ops": [{"op": "set_param", "node": "blob", "key": "min_area", "value": "20000"}]})
        self.assertTrue(out["ok"])
        self.assertEqual(next(n for n in state.graph["nodes"] if n["id"] == "blob")["params"]["min_area"], 20000)
        out = actions.dispatch(state, "run_trial", {"images": [1]})
        self.assertEqual(out["summary"]["matches"], 0)
        # 守門：不得加深度學習工具、不得刪 image_source、未知節點
        out = actions.dispatch(state, "patch_graph", {"ops": [{"op": "add_node", "node": "dl", "type": "dl_classify"}]})
        self.assertIn("error", out)
        out = actions.dispatch(state, "patch_graph", {"ops": [{"op": "remove_node", "node": "src"}]})
        self.assertIn("error", out)
        out = actions.dispatch(state, "inspect_node", {"node": "nope"})
        self.assertIn("error", out)
        out = actions.dispatch(state, "inspect_node", {"node": "blob", "image": 1})
        self.assertEqual(out["node"], "blob")
        out = actions.dispatch(state, "auto_tune", {"max_evals": 30})
        self.assertTrue(out["improved"])
        out = actions.dispatch(state, "get_tool_skill", {"key": "blob"})
        self.assertIn("blob", out["markdown"])
        out = actions.dispatch(state, "finish", {"rationale": "完成"})
        self.assertTrue(state.finished)
        self.assertEqual([s["kind"] for s in state.steps][:3], ["tool", "tool", "tool"])
        self.assertTrue(any(s["kind"] == "error" for s in state.steps))

    def test_add_node_edge_and_template(self):
        state = service.build_state("generate", [part_image(5)], [], "應該有 5 個孔")
        actions.dispatch(state, "draft_from_rules", {})
        out = actions.dispatch(state, "patch_graph", {"ops": [
            {"op": "add_node", "node": "close", "type": "morphology", "label": "閉運算", "params": {"op": "close", "ksize": "5"}},
            {"op": "remove_edge", "source": "open", "target": "blob"},
            {"op": "add_edge", "source": "open", "target": "close"},
            {"op": "add_edge", "source": "close", "target": "blob"},
            {"op": "set_label", "node": "blob", "label": "孔"},
        ]})
        self.assertTrue(out["ok"], out)
        validate_graph(state.graph)
        self.assertEqual(next(n for n in state.graph["nodes"] if n["id"] == "close")["params"]["ksize"], 5)
        # 裁範本圖：不帶 target 只回描述子，帶 target 就加一個固定影像節點接到那個工具的圖片輸入埠
        out = actions.dispatch(state, "crop_template", {"image": 1, "region": {"shape": "rect", "x": 60, "y": 200, "w": 80, "h": 80}, "name": "t"})
        self.assertIn("picture", out)
        state.graph["nodes"].append({"id": "tm", "type": "template_match", "label": "找範本", "x": 6, "y": 0, "params": {"threshold": 0.7}})
        out = actions.dispatch(state, "crop_template", {"image": 1, "region": {"shape": "rect", "x": 60, "y": 200, "w": 80, "h": 80}, "name": "t", "target": "tm"})
        self.assertEqual(out.get("picture_node"), "pic_tm", out)
        pic = next(n for n in state.graph["nodes"] if n["id"] == "pic_tm")
        self.assertEqual(pic["params"]["role"], "reference")
        self.assertTrue(any(e["source"] == "pic_tm" and e["target"] == "tm" and e["target_handle"] == "template_image" for e in state.graph["edges"]))
        self.assertIn("error", actions.dispatch(state, "crop_template", {"image": 1, "region": {"shape": "rect", "x": 0, "y": 0, "w": 10, "h": 10}, "target": "nope"}))
        out = actions.dispatch(state, "replace_graph", {"graph": {"nodes": [{"id": "s", "type": "image_source", "params": {"mode": "auto"}}, {"id": "w", "type": "write_modbus", "params": {}}], "edges": []}})
        self.assertIn("error", out)


class LoopTests(TestCase):
    def setUp(self):
        self.state = service.build_state("generate", [part_image(5), part_image(4)], [], "應該有 5 個孔", labels=["ok", "ng"])

    def test_scripted_loop_reaches_done(self):
        script = scripted(reply(call("get_state")), reply(call("draft_from_rules"), text="先起草"), reply(call("run_trial")), reply(call("finish", {"rationale": "規則草稿已命中"})))
        with mock.patch.object(providers, "complete_tools", side_effect=script):
            history: list[dict] = []
            res = loop.run_loop(LLM, self.state, history, loop.Budget())
        self.assertEqual(res.status, "done")
        self.assertEqual(res.rationale, "規則草稿已命中")
        self.assertEqual(res.turns, 4)
        validate_graph(res.graph)
        self.assertEqual(history[0]["role"], "user")
        self.assertTrue(any(p.get("type") == "image" for p in history[0]["content"]))
        self.assertEqual([t["role"] for t in history[1:5]], ["assistant", "tool", "assistant", "tool"])
        self.assertIn("assistant", [s["kind"] for s in self.state.steps])
        self.assertEqual(self.state.steps[-1]["kind"], "done")

    def test_needs_input_then_resume(self):
        script = scripted(reply(call("ask_user", {"questions": [{"id": "count", "text": "期望幾個？", "kind": "number"}]})))
        history: list[dict] = []
        with mock.patch.object(providers, "complete_tools", side_effect=script):
            res = loop.run_loop(LLM, self.state, history, loop.Budget())
        self.assertEqual(res.status, "needs_input")
        self.assertEqual(res.questions[0]["id"], "count")
        self.assertEqual(history[-1]["role"], "tool")  # 提問也有 tool 回覆，供應商才不會抱怨
        history.append(loop.answer_turn([{"id": "count", "answer": "5"}]))
        self.state.questions = None
        script = scripted(reply(call("draft_from_rules")), reply(call("finish", {"rationale": "ok"})))
        with mock.patch.object(providers, "complete_tools", side_effect=script):
            res = loop.run_loop(LLM, self.state, history, loop.Budget(), turns_used=res.turns)
        self.assertEqual(res.status, "done")
        self.assertEqual(res.turns, 3)

    def test_budget_stops_with_current_graph(self):
        def endless(settings, system, history, tools, *, timeout=None):
            if len(history) == 1:
                return reply(call("draft_from_rules"))
            return reply(call("run_trial"))

        with mock.patch.object(providers, "complete_tools", side_effect=endless):
            res = loop.run_loop(LLM, self.state, [], loop.Budget(max_turns=6, max_trials=2))
        self.assertEqual(res.status, "budget")
        self.assertIsNotNone(res.graph)
        self.assertEqual(self.state.trials, 2)
        self.assertEqual(self.state.steps[-1]["kind"], "budget")

    def test_text_only_reply_finishes_when_graph_exists(self):
        script = scripted(reply(call("draft_from_rules")), reply(text="流程已可用，說明如上"))
        with mock.patch.object(providers, "complete_tools", side_effect=script):
            res = loop.run_loop(LLM, self.state, [], loop.Budget())
        self.assertEqual((res.status, res.rationale), ("done", "流程已可用，說明如上"))

    def test_text_only_without_graph_is_nudged_then_error(self):
        script = scripted(reply(text="嗯"), reply(text="還是嗯"))
        with mock.patch.object(providers, "complete_tools", side_effect=script):
            res = loop.run_loop(LLM, self.state, [], loop.Budget())
        self.assertEqual(res.status, "error")


class ProviderFormatTests(TestCase):
    HISTORY = [
        {"role": "user", "content": [{"type": "image", "data": "AAAA"}, {"type": "text", "text": "需求"}]},
        {"role": "assistant", "content": "先看狀態", "tool_calls": [{"id": "c1", "name": "get_state", "args": {}}, {"id": "c2", "name": "get_tool_skill", "args": {"key": "blob"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_state", "content": "{\"image_count\": 1}"},
        {"role": "tool", "tool_call_id": "c2", "name": "get_tool_skill", "content": "{\"markdown\": \"# blob\"}"},
    ]

    def test_claude_messages_merge_tool_results(self):
        msgs = providers.claude_messages(self.HISTORY)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual([b["type"] for b in msgs[1]["content"]], ["text", "tool_use", "tool_use"])
        self.assertEqual([b["tool_use_id"] for b in msgs[2]["content"]], ["c1", "c2"])
        out = providers.parse_claude_reply([{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "x", "name": "run_trial", "input": {"images": [1]}}])
        self.assertEqual((out.text, out.calls[0].name, out.calls[0].args), ("hi", "run_trial", {"images": [1]}))

    def test_openai_messages_and_parse(self):
        msgs = providers.openai_messages("sys", self.HISTORY)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[2]["tool_calls"][1]["function"]["arguments"], "{\"key\": \"blob\"}")
        self.assertEqual([m["role"] for m in msgs[3:]], ["tool", "tool"])
        out = providers.parse_openai_reply({"content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "finish", "arguments": "{\"rationale\": \"done\"}"}}]})
        self.assertEqual((out.text, out.calls[0].args), ("", {"rationale": "done"}))

    def test_gemini_contents_and_parse(self):
        contents = providers.gemini_contents(self.HISTORY)
        self.assertEqual([c["role"] for c in contents], ["user", "model", "user"])
        self.assertEqual(len(contents[2]["parts"]), 2)
        self.assertEqual(contents[2]["parts"][0]["functionResponse"]["response"], {"image_count": 1})
        out = providers.parse_gemini_reply({"content": {"parts": [{"text": "ok"}, {"functionCall": {"name": "run_trial", "args": {}}}]}})
        self.assertEqual((out.text, out.calls[0].name), ("ok", "run_trial"))
        schema = providers._gemini_schema({"type": "object", "properties": {}, "required": []})
        self.assertIn("properties", schema)
        # Gemini 3：functionCall 帶 thoughtSignature，下一回合要原樣回傳
        out = providers.parse_gemini_reply({"content": {"parts": [{"functionCall": {"name": "get_state", "args": {}}, "thoughtSignature": "sig-1"}]}})
        self.assertEqual(out.raw[0]["thoughtSignature"], "sig-1")
        history = [{"role": "user", "content": [{"type": "text", "text": "x"}]},
                   {"role": "assistant", "content": "", "tool_calls": [{"id": "get_state_0", "name": "get_state", "args": {}}], "raw": out.raw},
                   {"role": "tool", "tool_call_id": "get_state_0", "name": "get_state", "content": "{}"}]
        contents = providers.gemini_contents(history)
        self.assertEqual(contents[1]["parts"][0]["thoughtSignature"], "sig-1")


class JobApiTests(TransactionTestCase):
    def test_job_roundtrip_agentic(self):
        ref = _upload(self.client, part_image(5))
        script = scripted(reply(call("get_state")), reply(call("draft_from_rules")), reply(call("run_trial")), reply(call("finish", {"rationale": "代理完成"})))
        with mock.patch.object(providers, "complete_tools", side_effect=script), mock.patch.object(providers, "resolve", return_value=LLM):
            res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "generate", "images": [ref], "prompt": "應該有 5 個孔", "labels": ["ok"]}), content_type="application/json")
            self.assertEqual(res.status_code, 202, res.content)
            job_id = res.json()["id"]
            body = _wait(self.client, job_id)
        self.assertEqual(body["status"], "done", body.get("error"))
        self.assertEqual(body["result"]["rationale"], "代理完成")
        self.assertTrue(body["result"]["agentic"])
        self.assertEqual(body["result"]["report"]["status"], "ok")
        validate_graph(body["result"]["graph"])
        self.assertGreaterEqual(len(body["steps"]), 4)
        listed = self.client.get("/api/vision/agent/jobs").json()["items"]
        self.assertIn(job_id, [j["id"] for j in listed])
        # step_from 只回新步驟
        tail = self.client.get(f"/api/vision/agent/jobs/{job_id}?step_from={len(body['steps'])}").json()
        self.assertEqual(tail["steps"], [])

    def test_job_offline_falls_back_to_rules(self):
        ref = _upload(self.client, part_image(5))
        res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "generate", "images": [ref], "prompt": "應該有 5 個孔"}), content_type="application/json")
        self.assertEqual(res.status_code, 202, res.content)
        body = _wait(self.client, res.json()["id"])
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["result"]["provider"], "rules")
        self.assertTrue(body["fallback_reason"])
        self.assertTrue(body["result"]["warnings"][0].startswith("沒有可用的 LLM"))

    def test_job_needs_input_answer_and_cancel(self):
        ref = _upload(self.client, part_image(5))
        script = scripted(reply(call("ask_user", {"questions": [{"id": "count", "text": "期望幾個？", "kind": "number"}]})), reply(call("draft_from_rules")), reply(call("finish", {"rationale": "ok"})))
        with mock.patch.object(providers, "complete_tools", side_effect=script), mock.patch.object(providers, "resolve", return_value=LLM):
            res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "generate", "images": [ref], "prompt": "看一下"}), content_type="application/json")
            job_id = res.json()["id"]
            body = _wait(self.client, job_id)
            self.assertEqual(body["status"], "needs_input")
            self.assertEqual(body["questions"][0]["id"], "count")
            res = self.client.post(f"/api/vision/agent/jobs/{job_id}/answer", data=json.dumps({"answers": [{"id": "count", "answer": "5"}]}), content_type="application/json")
            self.assertEqual(res.status_code, 200, res.content)
            body = _wait(self.client, job_id)
        self.assertEqual(body["status"], "done")
        self.assertTrue(any(s["kind"] == "answer" for s in body["steps"]))
        # 等待回答中的工作可以取消
        script = scripted(reply(call("ask_user", {"questions": [{"id": "q", "text": "？"}]})))
        with mock.patch.object(providers, "complete_tools", side_effect=script), mock.patch.object(providers, "resolve", return_value=LLM):
            res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "generate", "images": [ref], "prompt": "看一下"}), content_type="application/json")
            job_id = res.json()["id"]
            _wait(self.client, job_id)
        self.assertTrue(self.client.post(f"/api/vision/agent/jobs/{job_id}/cancel").json()["cancelled"])
        self.assertEqual(self.client.get(f"/api/vision/agent/jobs/{job_id}").json()["status"], "cancelled")
        res = self.client.post(f"/api/vision/agent/jobs/{job_id}/answer", data=json.dumps({"answers": []}), content_type="application/json")
        self.assertEqual(res.status_code, 409)

    def test_edit_and_tune_jobs(self):
        ref = _upload(self.client, part_image(5))
        base = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False)["graph"]
        script = scripted(reply(call("patch_graph", {"ops": [{"op": "set_param", "node": "blob", "key": "min_area", "value": "40"}]})), reply(call("finish", {"rationale": "已改"})))
        with mock.patch.object(providers, "complete_tools", side_effect=script), mock.patch.object(providers, "resolve", return_value=LLM):
            res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "edit", "graph": base, "instruction": "把 blob 最小面積改成 40", "images": [ref]}), content_type="application/json")
            self.assertEqual(res.status_code, 202, res.content)
            body = _wait(self.client, res.json()["id"])
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["result"]["changes"], ["blob.min_area = 40"])
        self.assertEqual(body["result"]["report"]["status"], "ok")
        script = scripted(reply(call("run_trial")), reply(call("finish", {"rationale": "維持"})))
        with mock.patch.object(providers, "complete_tools", side_effect=script), mock.patch.object(providers, "resolve", return_value=LLM):
            res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "tune", "graph": base, "instruction": "看一下這批", "runs": [{"name": "a", "image_ref": ref, "status": "ok", "expected": "ok"}]}), content_type="application/json")
            self.assertEqual(res.status_code, 202, res.content)
            body = _wait(self.client, res.json()["id"])
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["result"]["after"]["ok"], 1)
        res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "edit", "graph": base, "instruction": ""}), content_type="application/json")
        self.assertEqual(res.status_code, 422)

    def test_settings_mode(self):
        r = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret123", "display_name": "管理員"}), content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['token']}"}
        r = self.client.patch("/api/vision/agent/settings", data=json.dumps({"provider": "openai", "api_key": "sk-testtest12", "mode": "agentic"}), content_type="application/json", **auth)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["mode"], "agentic")
        self.assertEqual(self.client.get("/api/vision/agent/info", **auth).json()["mode"], "agentic")
        r = self.client.patch("/api/vision/agent/settings", data=json.dumps({"provider": "openai", "mode": "bogus"}), content_type="application/json", **auth)
        self.assertEqual(r.status_code, 422)
        self.assertIn("agentic", [it["key"] for it in self.client.get("/api/vision/agent/skills", **auth).json()["items"]])
        self.assertIn("代理工作方式", self.client.get("/api/vision/agent/skills/agentic", **auth).json()["markdown"])
