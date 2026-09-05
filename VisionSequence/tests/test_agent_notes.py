"""AI 助手長期記憶（agent/notes.py）與截圖：記住／忘記指令、事實與問答的上限、評分與相似回想、help.answer 帶記憶與截圖、/agent/memory 端點。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.security import Principal
from apps.vision.agent import api as agent_api
from apps.vision.agent import help as help_mod
from apps.vision.agent import notes, providers
from apps.vision.models import AssistantMemory
from tests._helpers import temp_dir

TMP = temp_dir()
LLM = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user")
OFFLINE = providers.AgentSettings(provider="offline")


def jpeg_b64() -> str:
    ok, buf = cv2.imencode(".jpg", np.full((8, 8, 3), 128, np.uint8))
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


class NotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = User.objects.create_user("mem", password="x")

    def test_parse_command(self):
        self.assertEqual(notes.parse_command("記住：產線 3 用流程 A"), ("remember", "產線 3 用流程 A"))
        self.assertEqual(notes.parse_command("remember: line 3 uses flow A"), ("remember", "line 3 uses flow A"))
        self.assertEqual(notes.parse_command("  忘记:  流程 A"), ("forget", "流程 A"))
        self.assertIsNone(notes.parse_command("記住什麼？"))
        self.assertIsNone(notes.parse_command(""))

    def test_facts_dedupe_cap_forget(self):
        a = notes.add_fact(self.u, "  產線 3   用流程「檢測 A」 ")
        self.assertEqual(a.text, "產線 3 用流程「檢測 A」")
        self.assertEqual(notes.add_fact(self.u, "產線 3 用流程「檢測 A」").id, a.id)
        with self.assertRaises(ValueError):
            notes.add_fact(self.u, "   ")
        with mock.patch.object(notes, "MAX_FACTS", 3):
            for i in range(4):
                notes.add_fact(self.u, f"事實 {i}")
            texts = [f.text for f in notes.facts(self.u)]
        self.assertEqual(len(texts), 3)
        self.assertNotIn("產線 3 用流程「檢測 A」", texts)  # 最舊的被淘汰
        self.assertEqual(notes.forget_facts(self.u, "事實 1"), 1)
        self.assertEqual(notes.forget_facts(self.u, "沒有的"), 0)
        self.assertEqual(notes.forget_facts(self.u, ""), 0)
        self.assertEqual(notes.facts(None), [])
        self.assertIn("- 事實 3", notes.facts_text(self.u))
        self.assertEqual(notes.facts_text(None), "")

    def test_qa_record_rate_recall(self):
        self.assertIsNone(notes.record_qa(None, "q", "a"))
        self.assertIsNone(notes.record_qa(self.u, "q", "   "))
        row = notes.record_qa(self.u, "如何建立影像來源？", "到來源庫按新增來源。", {"kind": "page", "route": "/sources", "lang": "zh-Hant", "page": {"big": 1}}, "rules")
        self.assertEqual(row.context, {"kind": "page", "route": "/sources", "lang": "zh-Hant", "provider": "rules"})
        # 沒評分不會被回想；評過好才會
        self.assertEqual(notes.recall(self.u, "如何建立影像來源"), [])
        self.assertEqual(notes.rate(self.u, row.id, 5).rating, 1)
        self.assertIsNone(notes.rate(self.u, 999, 1))
        hits = notes.recall(self.u, "如何建立影像來源")
        self.assertEqual(hits[0][0].id, row.id)
        self.assertGreaterEqual(hits[0][1], notes.DIRECT_MIN)
        self.assertEqual(AssistantMemory.objects.get(pk=row.id).hits, 1)
        self.assertIsNotNone(AssistantMemory.objects.get(pk=row.id).last_used_at)
        self.assertEqual(notes.recall(self.u, "YOLO 訓練要裝什麼"), [])
        self.assertIn("Q: 如何建立影像來源？", notes.examples_text(hits))
        self.assertEqual(notes.examples_text([]), "")
        # 上限：淘汰最舊且未評分的，評過的留著
        with mock.patch.object(notes, "MAX_QA", 2):
            notes.record_qa(self.u, "第二題", "答")
            notes.record_qa(self.u, "第三題", "答")
        texts = [r.text for r in notes.recent_qa(self.u)]
        self.assertEqual(len(texts), 2)
        self.assertIn("如何建立影像來源？", texts)
        self.assertNotIn("第二題", texts)
        self.assertTrue(notes.delete(self.u, row.id))
        self.assertFalse(notes.delete(self.u, row.id))

    def test_confirmation_languages(self):
        self.assertTrue(notes.confirmation("remember", "x", 0, "zh-Hant").startswith("已記住：x"))
        self.assertTrue(notes.confirmation("remember", "x", 0, "zh-Hans").startswith("已记住：x"))
        self.assertTrue(notes.confirmation("remember", "x", 0, "en").startswith("Remembered: x"))
        self.assertIn("已忘記 2 筆", notes.confirmation("forget", "x", 2, "zh-Hant"))
        self.assertIn("沒有含", notes.confirmation("forget", "x", 0, "zh-Hant"))
        self.assertIn("Forgot 1", notes.confirmation("forget", "x", 1, ""))


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class HelpMemoryAndScreenshotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = User.objects.create_user("mem2", password="x", is_staff=True)
        notes.add_fact(cls.u, "產線 3 用流程「檢測 A」")
        row = notes.record_qa(cls.u, "如何從資料夾建立影像來源？", "到來源庫，新增來源選資料夾。", {}, "openai")
        notes.rate(cls.u, row.id, 1)

    def test_llm_prompt_gets_facts_examples_and_screenshot(self):
        shot = jpeg_b64()
        with mock.patch.object(providers, "complete", return_value="回答") as done, mock.patch.object(providers, "_cfg", return_value="0"):
            out = help_mod.answer("如何從資料夾建立影像來源", LLM, context={"kind": "page"}, user=self.u, principal=Principal(kind="user", user=self.u), screenshot=shot)
        self.assertEqual(out["answer"], "回答")
        system, images, prompt = done.call_args.args[1], done.call_args.args[2], done.call_args.args[3]
        self.assertEqual(images, [shot])
        self.assertIn("Things the user asked you to remember:\n- 產線 3 用流程「檢測 A」", prompt)
        self.assertIn("A screenshot of the user's current screen is attached", prompt)
        self.assertIn("Previously helpful answers this user rated up", prompt)
        self.assertIn("A: 到來源庫，新增來源選資料夾。", prompt)
        self.assertIn("If a screenshot is attached", system)
        # 工具迴圈的第一則使用者訊息也帶圖
        reply = providers.ToolReply(text="ok", calls=[])
        with mock.patch.object(providers, "complete_tools", return_value=reply) as tools:
            help_mod.answer("狀態？", LLM, context={"kind": "page"}, user=self.u, principal=Principal(kind="user", user=self.u), screenshot=shot)
        first = tools.call_args.args[2][0]["content"]
        self.assertEqual(first[0], {"type": "image", "data": shot})
        self.assertEqual(first[1]["type"], "text")

    def test_offline_uses_rated_answer_when_nearly_same_question(self):
        out = help_mod.answer("如何從資料夾建立影像來源？", OFFLINE, context={"kind": "page"}, user=self.u, screenshot=jpeg_b64())
        self.assertEqual(out["provider"], "memory")
        self.assertEqual(out["answer"], "到來源庫，新增來源選資料夾。")
        self.assertTrue(out["sources"])
        self.assertTrue(any("cannot see screenshots" in w for w in out["warnings"]), out["warnings"])
        out = help_mod.answer("YOLO 訓練需要安裝什麼", OFFLINE, context={"kind": "page"}, user=self.u)
        self.assertEqual(out["provider"], "rules")
        self.assertEqual(out["warnings"], [])
        # 別的使用者看不到這些記憶
        other = User.objects.create_user("other", password="x")
        out = help_mod.answer("如何從資料夾建立影像來源？", OFFLINE, context={"kind": "page"}, user=other)
        self.assertEqual(out["provider"], "rules")


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False, "API_KEY": "integrator-key"})
class MemoryApiTests(TestCase):
    def setUp(self):
        User.objects.create_user("boss", password="x", is_staff=True)
        r = self.client.post("/api/auth/login", data=json.dumps({"username": "boss", "password": "x"}), content_type="application/json")
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['token']}"}

    def _chat(self, body: dict, **extra):
        return self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json", **(extra or self.auth))

    def test_remember_forget_and_qa_memory(self):
        r = self._chat({"message": "記住：產線 3 用流程「檢測 A」", "context": {"kind": "page", "lang": "zh-Hant"}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["provider"], "memory")
        self.assertTrue(r.json()["answer"].startswith("已記住：產線 3 用流程「檢測 A」"))
        self.assertEqual(r.json()["memory"]["kind"], "fact")
        self.assertEqual(self._chat({"message": "記住：   "}).status_code, 422)
        # 一般問答會留一筆並回 memory_id；評分；清單
        r = self._chat({"message": "如何建立影像來源？", "context": {"kind": "page", "route": "/sources"}})
        self.assertEqual(r.status_code, 200, r.content)
        mid = r.json()["memory_id"]
        self.assertTrue(mid)
        r = self.client.post(f"/api/vision/agent/memory/{mid}/rate", data=json.dumps({"rating": 1}), content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["rating"], 1)
        self.assertEqual(self.client.post("/api/vision/agent/memory/999/rate", data=json.dumps({"rating": 1}), content_type="application/json", **self.auth).status_code, 404)
        r = self.client.get("/api/vision/agent/memory", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([f["text"] for f in r.json()["facts"]], ["產線 3 用流程「檢測 A」"])
        self.assertEqual(r.json()["qa"][0]["rating"], 1)
        self.assertEqual(r.json()["limits"]["facts"], notes.MAX_FACTS)
        # 手動新增與刪除
        r = self.client.post("/api/vision/agent/memory", data=json.dumps({"text": "我負責 B 線"}), content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 201, r.content)
        fid = r.json()["id"]
        self.assertEqual(self.client.post("/api/vision/agent/memory", data=json.dumps({"text": " "}), content_type="application/json", **self.auth).status_code, 422)
        self.assertEqual(self.client.delete(f"/api/vision/agent/memory/{fid}", **self.auth).status_code, 204)
        self.assertEqual(self.client.delete(f"/api/vision/agent/memory/{fid}", **self.auth).status_code, 404)
        # 忘記
        r = self._chat({"message": "忘記：檢測 A", "context": {"kind": "page", "lang": "zh-Hant"}})
        self.assertIn("已忘記 1 筆", r.json()["answer"])
        self.assertEqual(self.client.get("/api/vision/agent/memory", **self.auth).json()["facts"], [])
        # 整合方（沒有使用者身分）：記住指令當一般問句、清單為空、新增 422
        r = self._chat({"message": "記住：x", "context": {"kind": "page"}}, HTTP_X_API_KEY="integrator-key")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotEqual(r.json()["provider"], "memory")
        self.assertNotIn("memory_id", r.json())
        self.assertEqual(self.client.get("/api/vision/agent/memory", HTTP_X_API_KEY="integrator-key").json()["facts"], [])
        self.assertEqual(self.client.post("/api/vision/agent/memory", data=json.dumps({"text": "x"}), content_type="application/json", HTTP_X_API_KEY="integrator-key").status_code, 422)

    def test_screenshot_validation(self):
        shot = jpeg_b64()
        with mock.patch.object(help_mod, "answer", return_value={"answer": "看到了", "provider": "openai", "sources": [], "warnings": [], "actions": [], "lookups": []}) as done:
            r = self._chat({"message": "這頁在顯示什麼？", "context": {"kind": "page", "screenshot": f"data:image/jpeg;base64,{shot}"}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(done.call_args.kwargs["screenshot"], shot)
        self.assertNotIn("screenshot", done.call_args.kwargs["context"])
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 16).decode()
        self.assertEqual(self._chat({"message": "x", "context": {"kind": "page", "screenshot": png}}).json()["error"]["code"], "screenshot_invalid")
        self.assertEqual(self._chat({"message": "x", "context": {"kind": "page", "screenshot": "data:image/jpeg"}}).json()["error"]["code"], "screenshot_invalid")
        self.assertEqual(self._chat({"message": "x", "context": {"kind": "page", "screenshot": "not base64!!"}}).json()["error"]["code"], "screenshot_invalid")
        with mock.patch.object(agent_api, "MAX_SCREENSHOT_B64", 10):
            self.assertEqual(self._chat({"message": "x", "context": {"kind": "page", "screenshot": shot}}).json()["error"]["code"], "screenshot_too_large")
