"""全域 AI 助手：說明索引（docs 章節＋工具技能）檢索、離線／LLM 問答、/agent/chat 依脈絡分流（問答／修改流程／資料諮詢／依資料調整／代理旗標）、docs 靜態服務。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from django.conf import settings
from django.test import TestCase, override_settings

from apps.vision.agent import help as help_mod
from apps.vision.agent import providers, service
from apps.vision.batch import jobs, store
from apps.vision.models import BatchSet, Flow, ImageSource
from tests._helpers import temp_dir

TMP = temp_dir()
LLM = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user")


def part_image(holes: int = 5) -> np.ndarray:
    img = np.full((480, 640, 3), 200, np.uint8)
    for i in range(holes):
        cv2.circle(img, (100 + i * 110, 240), 30, (40, 40, 40), -1)
    return img


class HelpIndexTests(TestCase):
    def test_index_and_search(self):
        stats = help_mod.index_stats()
        self.assertGreater(stats["sections"], 80)
        self.assertGreaterEqual(stats["pages"], 15)
        self.assertGreaterEqual(stats["tools"], 60)
        hits = help_mod.search("批次測試 影像集 怎麼建立")
        self.assertTrue(hits)
        self.assertIn(hits[0][0].page, ("batch.html", "user-guide.html"))
        self.assertTrue(any(s.page == "batch.html" for s, _ in hits))
        self.assertTrue(hits[0][0].url.startswith("/docs/"))
        hits = help_mod.search("Golden Set 回歸 基準")
        self.assertIn(hits[0][0].page, ("golden.html", "user-guide.html"))
        hits = help_mod.search("blob 粒子 最小面積")
        self.assertTrue(any(s.kind == "tool" and "blob" in s.heading for s, _ in hits))
        self.assertEqual(help_mod.tokenize("Blob 分析 min_area"), ["blob", "min_area", "分析"])

    def test_offline_answer_and_snippet(self):
        out = help_mod.answer("如何把批次結果存入 Golden Set？", providers.AgentSettings())
        self.assertEqual(out["provider"], "rules")
        self.assertIn("依平台文件", out["answer"])
        self.assertTrue(out["sources"])
        self.assertTrue(all(src["url"].startswith("/docs/") for src in out["sources"]))
        self.assertLessEqual(len(help_mod.snippet(out and help_mod.search("Golden")[0][0], "Golden", 120)), 130)
        out = help_mod.answer("zzqqxx", providers.AgentSettings())
        self.assertIn("找不到", out["answer"])

    def test_context_adds_tool_skill_and_llm_prompt(self):
        with mock.patch.object(providers, "complete", return_value="結論：blob 的最小面積擋雜訊。\n參考：《AI 技能 › 工具：Blob 分析》") as done:
            out = help_mod.answer("這個參數是做什麼的？", LLM, context={"kind": "tool", "node_type": "blob", "flow_name": "示範"}, history=[{"role": "user", "text": "上一句"}])
        self.assertEqual(out["provider"], "openai")
        self.assertEqual(out["sources"][0]["kind"], "tool")
        prompt = done.call_args.args[3]
        self.assertIn("工具頁", prompt)
        self.assertIn("最近對話", prompt)
        self.assertIn("Blob", prompt)
        self.assertIn("問題：這個參數是做什麼的？", prompt)
        with mock.patch.object(providers, "complete", side_effect=RuntimeError("boom")):
            out = help_mod.answer("如何建立影像來源？", LLM)
        self.assertEqual(out["provider"], "rules")
        self.assertTrue(out["warnings"])


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class ChatApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def _chat(self, body: dict):
        return self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json")

    def test_help_and_validation(self):
        r = self._chat({"message": "如何建立影像來源？", "context": {"kind": "page", "route": "/sources"}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["kind"], "help")
        self.assertTrue(r.json()["sources"])
        self.assertEqual(self._chat({"message": "  "}).status_code, 422)
        r = self.client.get("/api/vision/agent/help/search?q=範本畫廊")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["items"])
        self.assertGreater(r.json()["sections"], 80)

    def test_edit_intent_in_editor(self):
        graph = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False, remember=False)["graph"]
        ctx = {"kind": "flow_editor", "flow_id": 1, "graph": graph}
        r = self._chat({"message": "把 blob 的 min_area 改成 40", "context": ctx})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["kind"], "edit")
        self.assertTrue(body["result"]["applied"])
        self.assertEqual(next(n for n in body["result"]["graph"]["nodes"] if n["id"] == "blob")["params"]["min_area"], 40)
        # 問句在編輯器仍走問答
        r = self._chat({"message": "blob 的 min_area 是做什麼的？", "context": {**ctx, "node_type": "blob"}})
        self.assertEqual(r.json()["kind"], "help")
        # 強制模式
        r = self._chat({"message": "停用去雜訊", "mode": "help", "context": ctx})
        self.assertEqual(r.json()["kind"], "help")
        self.assertEqual(self._chat({"message": "把 blob 的 min_area 改成 40", "mode": "edit", "context": {"kind": "flow_editor"}}).status_code, 422)
        # 代理模式回旗標
        agentic = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user", mode="agentic")
        with mock.patch.object(providers, "resolve", return_value=agentic):
            r = self._chat({"message": "把 blob 的 min_area 改成 40", "context": ctx})
        self.assertEqual((r.json()["kind"], r.json()["agentic"]), ("edit", True))

    def test_batch_consult_and_tune(self):
        source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        flow = Flow.objects.create(name="gate", graph={
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": source.id}}, {"id": "g", "type": "grayscale", "params": {}},
                {"id": "t", "type": "intensity", "params": {}}, {"id": "rng", "type": "in_range", "params": {"low": 100, "high": 255}},
                {"id": "ok", "type": "judge", "params": {"verdict": "ok"}}, {"id": "ng", "type": "judge", "params": {"verdict": "ng"}},
            ],
            "edges": [
                {"source": "src", "target": "g"}, {"source": "g", "target": "t"}, {"source": "t", "source_handle": "mean", "target": "rng", "target_handle": "value"},
                {"source": "rng", "source_handle": "inside", "target": "ok", "target_handle": "_flow"}, {"source": "rng", "source_handle": "outside", "target": "ng", "target_handle": "_flow"},
            ],
        })
        bset = BatchSet.objects.create(flow=flow, name="s")
        store.save_images(bset, [("bright", np.full((48, 64, 3), 200, np.uint8)), ("dark", np.full((48, 64, 3), 20, np.uint8)), ("mid", np.full((48, 64, 3), 150, np.uint8))])
        bset.images[0]["expected"], bset.images[1]["expected"], bset.images[2]["expected"] = "ok", "ng", "ng"
        bset.save(update_fields=["images"])
        rows, wall = jobs.execute_rows(flow, flow.graph, bset.images)
        run = store.save_completed_run(bset, flow.graph, rows, origin="manual", wall_ms=wall)
        ctx = {"kind": "batch", "flow_id": flow.id, "batch_run_id": run.id}
        r = self._chat({"message": "為什麼第 3 張 NG？", "context": ctx})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["kind"], "consult")
        self.assertEqual(r.json()["suggestions"][0]["node"], "rng")
        r = self._chat({"message": "把 rng 的 low 改成 170", "context": ctx})
        self.assertEqual(r.json()["kind"], "tune")
        self.assertIsNotNone(r.json()["batch_run_id"])
        r = self._chat({"message": "如何匯出 CSV？", "context": ctx})
        self.assertEqual(r.json()["kind"], "help")
        self.assertEqual(self._chat({"message": "為什麼第 3 張 NG？", "mode": "consult", "context": {"kind": "batch"}}).status_code, 422)

    def test_docs_served(self):
        r = self.client.get("/docs/batch.html")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/docs/nope.html").status_code, 404)
