"""AI 助手的唯讀查詢（agent/lookup.py）與帶查詢的問答（help._answer_with_lookups）、回覆動作（ACTIONS 行→actions[]）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import UserPref
from apps.accounts.security import Principal
from apps.comm.models import Connection
from apps.vision import engine
from apps.vision.agent import help as help_mod
from apps.vision.agent import lookup, providers
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from tests._helpers import temp_dir
from tests.fakes import register_memory_kind

TMP = temp_dir()
LLM = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user")
GRAPH = {"nodes": [{"id": "src", "type": "image_source", "params": {}}, {"id": "blob", "type": "blob", "params": {"min_area": 10}}], "edges": [{"source": "src", "source_handle": "image", "target": "blob", "target_handle": "image"}]}


def _reply(text: str = "", calls: list[tuple[str, str, dict]] | None = None) -> providers.ToolReply:
    return providers.ToolReply(text=text, calls=[providers.ToolCall(id=i, name=n, args=a) for i, n, a in (calls or [])])


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class LookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        register_memory_kind()
        cls.admin = User.objects.create_user("boss", password="x", is_staff=True)
        cls.op = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=cls.op, role="operator")
        cls.flow = Flow.objects.create(name="檢測 A", graph=GRAPH, owner=cls.admin)
        ImageSource.objects.create(name="cam", kind="folder", config={"path": "d:/img", "password": "no"})
        Connection.objects.create(name="plc", kind="memory_sim", config={"host": "1.2.3.4", "token": "hidden"})
        rt = runner.runtime(cls.flow.id)
        rt.recent.append(engine.RunReport(id="run-1", flow_id=cls.flow.id, flow_version=1, trigger="ui", status="ng", started_at=1.0, duration_ms=12.5, outputs={"count": 3, "ratio": 0.12345}))

    def setUp(self):
        self.admin_p = Principal(kind="user", user=self.admin)
        self.op_p = Principal(kind="user", user=self.op)

    def test_specs_and_unknown(self):
        names = [s["name"] for s in lookup.specs()]
        self.assertIn("list_flows", names)
        self.assertIn("search_notes", names)
        self.assertTrue(all(set(s) == {"name", "description", "input_schema"} for s in lookup.specs()))
        out = lookup.dispatch(self.admin_p, "nope", {})
        self.assertIn("No lookup", out["error"])
        self.assertIn("list_flows", out["available"])

    def test_search_notes_only_confirmed(self):
        from apps.vision import notes

        draft = notes.create(self.admin_p, {"title": "Draft lighting", "body": "Unreviewed", "flow": self.flow.pk})
        self.assertEqual(lookup.dispatch(self.op_p, "search_notes", {"flow_id": self.flow.pk})["items"], [])
        reviewer = User.objects.create_user("reviewer", is_staff=True)
        notes.transition(Principal(kind="user", user=reviewer), draft.pk, "confirm")
        self.assertEqual(lookup.dispatch(self.op_p, "search_notes", {"flow_id": self.flow.pk})["items"][0]["id"], draft.pk)
        self.assertIn("error", lookup.dispatch(None, "search_notes", {}))

    def test_flows_and_runs(self):
        out = lookup.dispatch(self.admin_p, "list_flows", {"query": "檢測"})
        self.assertEqual(out["count"], 1)
        item = out["items"][0]
        self.assertEqual(item["name"], "檢測 A")
        self.assertEqual(item["nodes"], 2)
        self.assertEqual(item["last_run"]["status"], "ng")
        self.assertEqual(lookup.dispatch(self.admin_p, "list_flows", {"query": "zzz"})["count"], 0)
        detail = lookup.dispatch(self.admin_p, "get_flow", {"flow_id": self.flow.id})
        self.assertEqual([n["type"] for n in detail["nodes"]], ["image_source", "blob"])
        self.assertEqual(detail["nodes"][1]["params"], {"min_area": 10})
        self.assertEqual(detail["recent_runs"][0]["run_id"], "run-1")
        self.assertIn("No flow", lookup.dispatch(self.admin_p, "get_flow", {"flow_id": 999})["error"])
        run = lookup.dispatch(self.admin_p, "get_run", {"run_id": "run-1"})
        self.assertEqual(run["status"], "ng")
        self.assertEqual(run["outputs"], {"count": 3, "ratio": 0.1235})
        self.assertEqual(run["duration_ms"], 12)
        self.assertIn("No run", lookup.dispatch(self.admin_p, "get_run", {"run_id": "missing"})["error"])
        self.assertIn("required", lookup.dispatch(self.admin_p, "get_run", {})["error"])

    def test_sources_connections_hide_secrets(self):
        src = lookup.dispatch(self.admin_p, "list_sources", {})["items"][0]
        self.assertEqual(src["name"], "cam")
        self.assertNotIn("password", src["config"])
        self.assertEqual(src["config"]["path"], "d:/img")
        conn = lookup.dispatch(self.admin_p, "list_connections", {})["items"][0]
        self.assertEqual(conn["name"], "plc")
        self.assertNotIn("token", conn["config"])
        self.assertIn("status", conn)

    def test_permission_gating(self):
        # 操作員預設沒有 connections／sources／integration；有的查詢照回
        denied = lookup.dispatch(self.op_p, "list_connections", {})
        self.assertIn("Not permitted", denied["error"])
        self.assertIn("connections", denied["error"])
        self.assertIn("Not permitted", lookup.dispatch(self.op_p, "list_sources", {})["error"])
        self.assertIn("Not permitted", lookup.dispatch(self.op_p, "list_plugins", {})["error"])
        self.assertEqual(lookup.dispatch(self.op_p, "get_run", {"run_id": "run-1"})["status"], "ng")  # flows.run 操作員有
        mine = lookup.dispatch(self.op_p, "my_permissions", {})
        self.assertEqual(mine["role"], "operator")
        self.assertIn("flows.run", mine["allowed"])
        self.assertNotIn("connections", mine["allowed"])
        self.assertIn("operator", mine["matrix"])
        self.assertEqual(lookup.dispatch(None, "list_sources", {})["error"][:13], "Not permitted")
        self.assertEqual(lookup.dispatch(None, "engine_status", {})["lock"]["locked"], False)

    def test_status_docs_tool_plugins(self):
        st = lookup.dispatch(self.admin_p, "engine_status", {})
        self.assertIn("version", st)
        self.assertIn("workers", st)
        docs = lookup.dispatch(self.admin_p, "search_docs", {"query": "Golden Set 回歸"})
        self.assertTrue(docs["items"])
        self.assertIn("required", lookup.dispatch(self.admin_p, "search_docs", {})["error"])
        tool = lookup.dispatch(self.admin_p, "get_tool", {"key": "blob"})
        self.assertIn("min_area", tool["skill"])
        self.assertIn("No tool", lookup.dispatch(self.admin_p, "get_tool", {"key": "nope"})["error"])
        # 以一句話找工具：關鍵詞表沒列的說法也靠工具技能段的檢索找得到
        found = lookup.dispatch(self.admin_p, "search_tools", {"query": "兩台相機各拍一半拼成一張"})
        self.assertIn("stitch_images", [it["key"] for it in found["items"]])
        self.assertIn("required", lookup.dispatch(self.admin_p, "search_tools", {})["error"])
        # 範本目錄：可用關鍵字過濾，每筆帶用到的工具
        gallery = lookup.dispatch(self.admin_p, "list_templates", {})
        self.assertGreaterEqual(gallery["total"], 30)
        conveyor = lookup.dispatch(self.admin_p, "list_templates", {"query": "conveyor"})
        self.assertTrue(conveyor["items"] and all("conveyor" in f"{it['key']} {it['name']}".lower() for it in conveyor["items"]))
        self.assertIn("track_objects", conveyor["items"][0]["tools"])
        self.assertIn("items", lookup.dispatch(self.admin_p, "list_plugins", {}))
        self.assertIn("items", lookup.dispatch(self.admin_p, "capture_clients", {}))

    def test_handler_exception_becomes_error(self):
        with mock.patch.object(lookup, "h_engine_status", side_effect=RuntimeError("boom")):
            with mock.patch.dict(lookup.LOOKUP_MAP, {"engine_status": lookup.Lookup("engine_status", "", {}, lookup.h_engine_status)}):
                out = lookup.dispatch(self.admin_p, "engine_status", {})
        self.assertEqual(out["error"], "RuntimeError: boom")


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class HelpLookupLoopTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        register_memory_kind()
        cls.admin = User.objects.create_user("boss2", password="x", is_staff=True)
        cls.op = User.objects.create_user("op2", password="x")
        UserPref.objects.create(user=cls.op, role="operator")
        Connection.objects.create(name="plc", kind="memory_sim", config={})

    def test_loop_calls_lookup_then_answers_with_actions(self):
        replies = [_reply(calls=[("c1", "list_connections", {})]),
                   _reply('連線「plc」沒有開啟。\nACTIONS: [{"kind":"navigate","to":"/integration/modbus-server","tab":"connections","label":"前往從站連線"},{"kind":"navigate","to":"/nope","label":"x"},{"kind":"navigate","to":"/integration/tcp","tab":"zzz","label":"TCP"}]')]
        with mock.patch.object(providers, "complete_tools", side_effect=replies) as done, mock.patch.object(providers, "complete") as plain:
            out = help_mod.answer("為什麼 PLC 連不上？", LLM, context={"kind": "page", "route": "/integration/modbus-server"}, principal=Principal(kind="user", user=self.admin))
        plain.assert_not_called()
        self.assertEqual(out["answer"], "連線「plc」沒有開啟。")
        self.assertEqual(out["lookups"], [{"name": "list_connections", "args": {}}])
        self.assertEqual(out["actions"], [{"kind": "navigate", "to": "/integration/modbus-server", "tab": "connections", "label": "前往從站連線"},
                                          {"kind": "navigate", "to": "/integration/tcp", "label": "TCP"}])
        # 第二回合的歷史帶著工具結果（含連線名稱）
        history = done.call_args_list[1].args[2]
        self.assertEqual(history[1]["tool_calls"][0]["name"], "list_connections")
        self.assertEqual(history[2]["role"], "tool")
        self.assertIn("plc", history[2]["content"])
        self.assertIn("# Interface map", done.call_args_list[0].args[1])

    def test_denied_lookup_is_reported_to_model(self):
        replies = [_reply(calls=[("c1", "list_connections", {})]), _reply("您的角色看不到連線。")]
        with mock.patch.object(providers, "complete_tools", side_effect=replies) as done:
            out = help_mod.answer("連線狀態？", LLM, context={"kind": "page"}, principal=Principal(kind="user", user=self.op))
        self.assertEqual(out["answer"], "您的角色看不到連線。")
        self.assertIn("Not permitted", out["lookups"][0]["error"])
        self.assertIn("Not permitted", json.loads(done.call_args_list[1].args[2][2]["content"])["error"])

    def test_budget_and_fallbacks(self):
        # 模型一直查不回答：預算用完後退回單次 complete，但查過什麼仍回給前端
        always = _reply(calls=[("c", "engine_status", {})])
        with mock.patch.object(providers, "complete_tools", return_value=always) as done, mock.patch.object(providers, "complete", return_value="以查到的資料回答"):
            out = help_mod.answer("狀態？", LLM, context={"kind": "page"}, principal=Principal(kind="user", user=self.admin))
        self.assertEqual(done.call_count, help_mod.MAX_LOOKUP_TURNS + 1)
        self.assertEqual(out["answer"], "以查到的資料回答")
        self.assertEqual(len(out["lookups"]), help_mod.MAX_LOOKUP_TURNS)
        nudges = [h for h in done.call_args_list[-1].args[2] if h.get("role") == "user" and "budget" in json.dumps(h)]
        self.assertTrue(nudges)
        # 模型回空白 → 退回單次 complete
        with mock.patch.object(providers, "complete_tools", return_value=_reply("")), mock.patch.object(providers, "complete", return_value="純文件回答"):
            out = help_mod.answer("狀態？", LLM, context={"kind": "page"}, principal=Principal(kind="user", user=self.admin))
        self.assertEqual(out["answer"], "純文件回答")
        # 工具呼叫炸掉 → 退回單次 complete 並帶警告
        with mock.patch.object(providers, "complete_tools", side_effect=RuntimeError("tools down")), mock.patch.object(providers, "complete", return_value="純文件回答"):
            out = help_mod.answer("狀態？", LLM, context={"kind": "page"}, principal=Principal(kind="user", user=self.admin))
        self.assertEqual(out["answer"], "純文件回答")
        self.assertTrue(any("Live lookups failed" in w for w in out["warnings"]), out["warnings"])
        self.assertEqual(out["lookups"], [])
        # 關掉即時查詢 → 直接單次
        with mock.patch.object(providers, "_cfg", return_value="0"), mock.patch.object(providers, "complete_tools") as tools, mock.patch.object(providers, "complete", return_value="ok"):
            out = help_mod.answer("狀態？", LLM, context={"kind": "page"}, principal=Principal(kind="user", user=self.admin))
        tools.assert_not_called()
        self.assertEqual(out["answer"], "ok")
        # 沒有 principal（沒登入）就不給工具
        with mock.patch.object(providers, "complete_tools") as tools, mock.patch.object(providers, "complete", return_value="ok"):
            help_mod.answer("狀態？", LLM, context={"kind": "page"})
        tools.assert_not_called()

    def test_parse_and_validate_actions(self):
        text, raw = help_mod.parse_actions("回答\nACTIONS: not json")
        self.assertEqual((text, raw), ("回答\nACTIONS: not json", []))
        text, raw = help_mod.parse_actions("回答\n\nACTIONS: [{\"kind\":\"focus_node\",\"node\":\"blob\",\"label\":\"看 blob\"},{\"kind\":\"open_tool\",\"node\":\"nope\"},{\"kind\":\"navigate\",\"to\":\"/flows/7?x=1\",\"label\":\"編輯器\"},\"junk\"]")
        self.assertEqual(text, "回答")
        ctx = {"kind": "flow_editor", "flow_id": 7, "graph": GRAPH}
        out = help_mod.validate_actions(raw, ctx)
        self.assertEqual(out, [{"kind": "focus_node", "node": "blob", "flow_id": 7, "label": "看 blob"}, {"kind": "navigate", "to": "/flows/7", "label": "編輯器"}])
        # 沒有流程脈絡就不給節點動作；最多 3 個
        self.assertEqual(help_mod.validate_actions(raw, {"kind": "page"}), [{"kind": "navigate", "to": "/flows/7", "label": "編輯器"}])
        many = [{"kind": "navigate", "to": "/sources"}] * 5
        self.assertEqual(len(help_mod.validate_actions(many, {})), 3)
        self.assertEqual(help_mod.validate_actions(many, {})[0]["label"], "Source library")

    def test_llm_without_actions_line_still_gets_rule_navigate(self):
        # 實測 Gemini 常略過選填的 ACTIONS 行：問「在哪裡」時規則補一個「前往」
        with mock.patch.object(providers, "complete_tools", return_value=_reply("到「Modbus 從站」頁面的「連線」分頁。")):
            out = help_mod.answer("Modbus 從站在哪個頁面設定？", LLM, context={"kind": "page", "lang": "zh-Hant"}, principal=Principal(kind="user", user=self.admin))
        self.assertEqual(out["provider"], "openai")
        self.assertEqual(out["actions"], [{"kind": "navigate", "to": "/integration/modbus-server", "label": "Modbus 從站"}])
        with mock.patch.object(providers, "complete_tools", return_value=_reply("用新增流程。")):
            out = help_mod.answer("如何建立流程？", LLM, context={"kind": "page"}, principal=Principal(kind="user", user=self.admin))
        self.assertEqual(out["actions"], [])

    def test_where_question_ignores_unrelated_recent_error(self):
        # 剛剛有 423，但問的是「在哪裡」：錯誤字不併進檢索、仍給「前往」
        ctx = {"kind": "flow_editor", "route": "/flows/3", "flow_id": 3, "lang": "en",
               "activity": [{"ago_s": 5, "kind": "error", "text": "POST /vision/flows/3/preview -> 423 engine_locked", "detail": "The engine is locked by audit_admin"}]}
        self.assertEqual(help_mod._error_terms(ctx, "Where do I set up the Modbus server?"), "")
        self.assertIn("423", help_mod._error_terms(ctx, "Why did the preview fail?"))
        self.assertIn("423", help_mod._error_terms(ctx))  # 沒給問題＝舊行為（一律併）
        out = help_mod.answer("Where do I set up the Modbus server?", providers.AgentSettings(provider="offline"), context=ctx)
        self.assertEqual(out["actions"], [{"kind": "navigate", "to": "/integration/modbus-server", "label": "Modbus server"}])
        self.assertFalse(out["answer"].startswith("Most recent error"))
        with mock.patch.object(providers, "complete_tools", return_value=_reply("Go to External integration.")):
            out = help_mod.answer("Modbus 從站在哪個頁面設定？", LLM, context={**ctx, "lang": "zh-Hant"}, principal=Principal(kind="user", user=self.admin))
        self.assertEqual(out["actions"][0]["to"], "/integration/modbus-server")

    def test_rule_actions_offline(self):
        out = help_mod.answer("Modbus 從站在哪個頁面設定？", providers.AgentSettings(provider="offline"), context={"kind": "page", "lang": "zh-Hant"})
        self.assertEqual(out["provider"], "rules")
        self.assertEqual(out["actions"], [{"kind": "navigate", "to": "/integration/modbus-server", "label": "Modbus 從站"}])
        out = help_mod.answer("如何建立影像來源？", providers.AgentSettings(provider="offline"), context={"kind": "page", "lang": "zh-Hant"})
        self.assertEqual(out["actions"], [])
        self.assertEqual(out["lookups"], [])

    def test_chat_endpoint_returns_actions_and_lookups(self):
        r = self.client.post("/api/auth/login", data=json.dumps({"username": "boss2", "password": "x"}), content_type="application/json")
        token = r.json()["token"]
        replies = [_reply(calls=[("c1", "engine_status", {})]), _reply("沒有鎖定。\nACTIONS: [{\"kind\":\"navigate\",\"to\":\"/settings\",\"label\":\"設定\"}]")]
        with mock.patch.object(providers, "resolve", return_value=LLM), mock.patch.object(providers, "available", return_value=True), mock.patch.object(providers, "complete_tools", side_effect=replies):
            r = self.client.post("/api/vision/agent/chat", data=json.dumps({"message": "引擎鎖定了嗎？", "context": {"kind": "page", "route": "/settings"}}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["answer"], "沒有鎖定。")
        self.assertEqual(body["lookups"][0]["name"], "engine_status")
        self.assertEqual(body["actions"][0]["to"], "/settings")
