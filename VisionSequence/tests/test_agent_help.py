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
from apps.vision.agent import providers, service, situation
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
        self.assertIn(hits[0][0].page, ("guide/batch", "guide/user-guide"))
        self.assertTrue(any(s.page == "guide/batch" for s, _ in hits))
        self.assertTrue(hits[0][0].url.startswith(("/docs/", "/help/")))
        hits = help_mod.search("Golden Set 回歸 基準")
        self.assertIn(hits[0][0].page, ("guide/golden", "guide/user-guide"))
        hits = help_mod.search("blob 粒子 最小面積")
        self.assertTrue(any(s.kind == "tool" and "blob" in s.heading for s, _ in hits))
        self.assertEqual(help_mod.tokenize("Blob 分析 min_area"), ["blob", "min_area", "分析"])

    def test_offline_answer_and_snippet(self):
        out = help_mod.answer("如何把批次結果存入 Golden Set？", providers.AgentSettings())
        self.assertEqual(out["provider"], "rules")
        self.assertIn("From the platform documentation:", out["answer"])
        self.assertTrue(out["sources"])
        self.assertTrue(all(src["url"].startswith(("/docs/", "/help/")) or src["kind"] == "ui" for src in out["sources"]))
        self.assertLessEqual(len(help_mod.snippet(out and help_mod.search("Golden")[0][0], "Golden", 120)), 130)
        out = help_mod.answer("zzqqxx", providers.AgentSettings())
        self.assertIn("no section that directly matches", out["answer"])

    def test_context_adds_tool_skill_and_llm_prompt(self):
        with mock.patch.object(providers, "complete", return_value="結論：blob 的最小面積擋雜訊。\n參考：《AI 技能 › 工具：Blob 分析》") as done:
            out = help_mod.answer("這個參數是做什麼的？", LLM, context={"kind": "tool", "node_type": "blob", "flow_name": "示範"}, history=[{"role": "user", "text": "上一句"}])
        self.assertEqual(out["provider"], "openai")
        self.assertEqual(out["sources"][0]["kind"], "tool")
        prompt = done.call_args.args[3]
        self.assertIn("tool page", prompt)
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
        # 頁面快照、操作軌跡、語系與畫面摘要都收得下；有最近錯誤時離線回答先講錯誤，參考裡有目前頁面的介面地圖段
        r = self._chat({"message": "為什麼失敗？", "context": {"kind": "sources", "route": "/sources", "lang": "zh-Hant", "page": {"title": "Source library", "dialog": "New source"},
                                                          "activity": [{"ago_s": 4, "kind": "error", "text": "POST /vision/sources/test -> 422 no_frame", "detail": "Nothing is listening", "route": "/sources"}], "screen": "x"}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["answer"].startswith("最近一次錯誤（4 秒前）"))
        self.assertFalse(any(s["kind"] == "ui" and s["url"] == "/sources" for s in r.json()["sources"]))  # 目前頁的介面段不是檢索命中，不進參考
        # 問「在哪裡」：介面段進參考、離線規則給「前往」
        r = self._chat({"message": "Modbus 從站在哪個頁面設定？", "context": {"kind": "page", "route": "/", "lang": "zh-Hant"}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(any(s["kind"] == "ui" and s["url"] == "/integration/modbus-server" for s in r.json()["sources"]), r.json()["sources"])
        self.assertEqual(r.json()["actions"], [{"kind": "navigate", "to": "/integration/modbus-server", "label": "Modbus 從站"}])
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
        r = self.client.get("/docs/modbus.html")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/docs/nope.html").status_code, 404)
        # 使用者指南九頁已搬進前端（docs/guide 的 Markdown）：舊網址 301 到 /help/<page>
        r = self.client.get("/docs/batch.html")
        self.assertEqual((r.status_code, r["Location"]), (301, "/help/batch"))
        self.assertEqual(self.client.get("/docs/user-guide.html")["Location"], "/help/user-guide")
        # 使用者手冊的截圖（docs/img）同一條路提供（其他副檔名落到前端的 SPA 路由）
        self.assertEqual(self.client.get("/docs/img/shell.jpg").status_code, 200)
        self.assertEqual(self.client.get("/docs/img/shell.jpg")["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get("/docs/img/nope.jpg").status_code, 404)


class SituationTests(TestCase):
    """現況段落：頁面快照、操作軌跡、身分與鎖定；長度上限；離線回答帶最近錯誤；檢索用錯誤文字。"""

    def test_describe_and_limits(self):
        ctx = {"kind": "flow_editor", "route": "/flows/3", "flow_id": 3, "flow_name": "示範", "lang": "zh-Hant",
               "page": {"selected": {"id": "blob", "type": "blob"}, "dirty": True, "last_run": {"status": "failed", "error": "Image source is not set"}},
               "activity": [{"ago_s": 40, "kind": "nav", "text": "/flows/3"}, {"ago_s": 5, "kind": "error", "text": "POST /vision/flows/3/preview -> 422 no_source", "detail": "Image source is not set", "count": 2},
                            {"kind": "", "text": "ignored"}, "junk"]}
        text = situation.describe(ctx, principal=None, lock={"locked": True, "holder": "integrator", "reason": "maintenance"})
        self.assertIn("Page: flow editor (route /flows/3)", text)
        self.assertIn("Flow: 示範 (id 3)", text)
        self.assertIn("UI language: zh-Hant", text)
        self.assertIn('"selected": {"id": "blob"', text)
        self.assertIn("5s ago [error] POST /vision/flows/3/preview -> 422 no_source — Image source is not set (x2)", text)
        self.assertIn("Engine lock: locked by integrator (maintenance)", text)
        self.assertEqual(situation.describe({}), "")
        big = {"kind": "page", "page": {"rows": ["x" * 100] * 200}, "activity": [{"ago_s": 1, "kind": "nav", "text": "y" * 500}] * 100, "screen": "z" * 9000}
        text = situation.describe(big)
        self.assertLess(len(text), situation.MAX_PAGE_CHARS + situation.MAX_ACTIVITY_CHARS + situation.MAX_SCREEN_CHARS + 500)
        self.assertIn("truncated", text)
        errs = situation.recent_errors(situation.clean_activity(ctx["activity"]))
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["count"], 2)

    def test_principal_line_and_role_guard(self):
        from django.contrib.auth.models import User

        from apps.accounts.models import UserPref
        from apps.accounts.security import Principal

        u = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=u, role="operator")
        text = situation.describe({"kind": "page"}, principal=Principal(kind="user", user=u))
        self.assertIn("Caller: op, role operator, allowed features: ", text)
        self.assertIn("flows.run", text)
        self.assertNotIn("flows.edit", text)
        self.assertIn("Do not tell them to do something their role cannot", text)
        self.assertIn("integrator", situation.describe({}, principal=Principal(kind="integrator")))

    def test_offline_answer_mentions_recent_error_and_searches_it(self):
        ctx = {"kind": "sources", "route": "/sources", "lang": "zh-Hant", "activity": [{"ago_s": 3, "kind": "error", "text": "POST /vision/sources/test -> 422 no_frame", "detail": "Nothing is listening at 127.0.0.1:9001"}]}
        out = help_mod.answer("為什麼測試失敗？", providers.AgentSettings(provider="offline"), context=ctx)
        self.assertEqual(out["provider"], "rules")
        self.assertTrue(out["answer"].startswith("最近一次錯誤（3 秒前）：POST /vision/sources/test -> 422 no_frame — Nothing is listening"), out["answer"])
        self.assertIn("依平台文件：", out["answer"])
        # 介面語言決定規則文字：英文預設、簡中
        out = help_mod.answer("為什麼測試失敗？", providers.AgentSettings(provider="offline"), context={**ctx, "lang": "en"})
        self.assertTrue(out["answer"].startswith("Most recent error (3s ago): POST /vision/sources/test -> 422 no_frame — Nothing is listening"), out["answer"])
        self.assertIn("From the platform documentation:", out["answer"])
        out = help_mod.answer("為什麼測試失敗？", providers.AgentSettings(provider="offline"), context={**ctx, "lang": "zh-CN"})
        self.assertTrue(out["answer"].startswith("最近一次错误（3 秒前）"), out["answer"])
        self.assertTrue(out["sources"])
        # 沒有錯誤時不會多出那一行
        out = help_mod.answer("為什麼測試失敗？", providers.AgentSettings(provider="offline"), context={"kind": "sources"})
        self.assertFalse(out["answer"].startswith(("最近一次錯誤", "Most recent error")))

    def test_llm_prompt_carries_situation_and_ui_map(self):
        from django.contrib.auth.models import User

        from apps.accounts.security import Principal

        u = User.objects.create_user("eng", password="x", is_staff=True)
        ctx = {"kind": "tool", "route": "/flows/1/tools/blob", "node_type": "blob", "flow_name": "示範", "page": {"node": {"id": "blob", "params": {"min_area": 10}}},
               "activity": [{"ago_s": 2, "kind": "run", "text": "preview flow 1: ng"}]}
        with mock.patch.object(providers, "complete", return_value="回答") as done:
            out = help_mod.answer("min_area 要多少？", LLM, context=ctx, principal=Principal(kind="user", user=u), lock={"locked": False})
        self.assertEqual(out["answer"], "回答")
        system, prompt = done.call_args.args[1], done.call_args.args[3]
        self.assertIn("Current situation:", prompt)
        self.assertIn("Page: tool page (route /flows/1/tools/blob)", prompt)
        self.assertIn('"min_area": 10', prompt)
        self.assertIn("2s ago [run] preview flow 1: ng", prompt)
        self.assertIn("Caller: eng, role admin", prompt)
        self.assertTrue(prompt.rstrip().endswith("Answer language: English."), prompt[-120:])
        self.assertNotIn("Engine lock", prompt)
        self.assertIn("# Interface map", system)
        self.assertIn("Source library (/sources) [sources]", system)
        # 目前頁面的介面地圖段進提示詞（讓模型知道使用者在哪），但不列進參考清單（不是檢索命中的）
        self.assertIn("Route: /flows/:flowId/tools/:nodeId", prompt)
        self.assertFalse(any(s["kind"] == "ui" and s["url"] == "/flows/:flowId/tools/:nodeId" for s in out["sources"]), out["sources"])


class UiMapIndexTests(TestCase):
    """介面地圖進索引：中文問「在哪裡」對到頁面、url 是前端路由、路由樣板比對、地圖檔更新會重建。"""

    def test_ui_sections_searchable_in_three_languages(self):
        stats = help_mod.index_stats()
        self.assertGreaterEqual(stats["ui_pages"], 20)
        for q in ("Modbus 從站在哪個頁面", "Modbus 从站在哪个页面", "Where is the Modbus server page"):
            hits = help_mod.search(q, k=3)
            ui = [s for s, _ in hits if s.kind == "ui"]
            self.assertTrue(ui, (q, [s.title for s, _ in hits]))
            self.assertEqual(ui[0].url, "/integration/modbus-server", q)
            self.assertEqual(ui[0].title, "Interface › Modbus server")
        sec = next(s for s in help_mod.build_index().sections if s.kind == "ui" and s.anchor == "/users")
        self.assertIn("administrators only", sec.text)
        self.assertIn("Buttons: New user / 新增使用者", sec.text)

    def test_route_matching_and_brief(self):
        self.assertEqual(help_mod.ui_page_for("/flows/12/tools/blob")["id"], "tool")
        self.assertEqual(help_mod.ui_page_for("/flows/12")["id"], "flow_editor")
        self.assertEqual(help_mod.ui_page_for("/integration/plugins")["id"], "integration_plugins")
        self.assertIsNone(help_mod.ui_page_for("/nope/x"))
        brief = help_mod.ui_brief()
        self.assertIn("- Plugins (/integration/plugins) [integration]:", brief)
        self.assertIn("tabs: inventory (Loaded plugins), connections (Connections)", brief)
        self.assertIn("- Users (/users) [admin]:", brief)
        # 中文介面：名稱給「英文 / 中文」，模型才會用介面上的字
        zh = help_mod.ui_brief("zh-Hant")
        self.assertIn("- Plugins / 外掛 (/integration/plugins) [integration]:", zh)
        self.assertIn("connections (Connections / 連線)", zh)
        self.assertIn("buttons: Rescan / 重新掃描", zh)
        self.assertIn("names are English / interface language", zh)
        self.assertIn("- Users / 用户 (/users) [admin]:", help_mod.ui_brief("zh-CN"))

    def test_missing_map_degrades(self):
        with mock.patch.object(help_mod, "UI_MAP_PATH", Path(TMP) / "nope.json"):
            self.assertEqual(help_mod.load_ui_map()["pages"], [])
            self.assertEqual(help_mod._ui_sections(), [])
            self.assertIsNone(help_mod.ui_page_for("/sources"))
            self.assertIn("# Interface map", help_mod.ui_brief())


class GuideMarkdownIndexTests(TestCase):
    """使用者指南的 Markdown 正本（docs/guide/<lang>/*.md）進索引：錨點來自 `{#id}`、url 指向前端 /help、同語系優先。"""

    def test_parse_markdown_sections_anchors_and_chunks(self):
        md = "# Guide title\n\nIntro paragraph long enough to become its own section for the index.\n\n## First {#first}\n\nBody **bold** `code` [link](batch.md#x).\n\n### Sub heading\n\n" + ("row | value\n" * 400) + "\n## Second {#second}\n\nTail.\n"
        sections = help_mod._parse_markdown("guide/demo", md, "zh-Hant")
        self.assertEqual(sections[0].page_title, "Guide title")
        self.assertEqual(sections[0].heading, "")
        first = [s for s in sections if s.heading == "First"][0]
        self.assertEqual(first.anchor, "first")
        self.assertEqual(first.lang, "zh-Hant")
        self.assertIn("bold code link", first.text)
        self.assertEqual(first.url, "/help/demo#first")
        sub = [s for s in sections if s.heading.startswith("Sub heading")]
        self.assertEqual(sub[0].anchor, "sub-heading")
        self.assertGreater(len(sub), 1, "長章節要切成（續）片段，不能只截斷")
        self.assertTrue(sub[1].heading.endswith("（續）"))
        self.assertEqual([s.heading for s in sections][-1], "Second")

    def test_guide_pages_replace_their_html_and_prefer_language(self):
        idx = help_mod.build_index()
        pages = {s.page for s in idx.sections if s.kind == "doc"}
        self.assertIn("guide/user-guide", pages)
        self.assertNotIn("user-guide.html", pages, "有 md 正本的頁面不再索引同名 HTML")
        self.assertIn("modbus.html", pages, "工程文件仍是 HTML")
        hits = help_mod.search("batch test image set", k=3, lang="en")
        self.assertTrue(any(s.page == "guide/batch" for s, _ in hits))
        # 同語系優先：造一個只差語言的章節，zh-Hant 提問時 zh-Hant 版要排前面
        base = [s for s in idx.sections if s.page == "guide/batch" and s.heading][0]
        twin = help_mod.Section(base.page, base.page_title, base.heading, base.anchor, base.text, lang="zh-Hant")
        twin.tokens, twin.length = dict(base.tokens), base.length
        with mock.patch.object(help_mod, "_index", help_mod.Index(idx.sections + [twin], idx.df, idx.avg_len, idx.stamp)):
            with mock.patch.object(help_mod, "_stamp", return_value=idx.stamp):
                zh = help_mod.search(base.heading, k=10, lang="zh-Hant")
                order = [s.lang for s, _ in zh if s.page == base.page and s.heading == base.heading]
                self.assertEqual(order[:2], ["zh-Hant", "en"])
