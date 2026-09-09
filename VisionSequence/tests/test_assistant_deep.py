"""全域 AI 助手深度測試：意圖分流語料準確率、說明檢索命中率基準、邊界輸入與索引重建／多執行緒、權限與引擎鎖定、代理模式經 /agent/jobs 走完。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings

from apps.accounts.models import AuthToken
from apps.vision.agent import api as agent_api
from apps.vision.agent import help as help_mod
from apps.vision.agent import providers
from apps.vision.batch import jobs, store
from apps.vision.graph import validate_graph
from apps.vision.models import BatchRun, BatchSet, Flow, ImageSource
from tests._helpers import temp_dir

TMP = temp_dir()
LLM = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user")
AGENTIC = providers.AgentSettings(provider="openai", model="gpt-4o", api_key="sk-test", source="user", mode="agentic")
GRAPH = {"nodes": [{"id": "src", "type": "image_source", "params": {"source_id": 1}}, {"id": "blob", "type": "blob", "params": {"min_area": 10}}], "edges": [{"source": "src", "target": "blob"}]}


def gate_graph(source_id: int, low: int = 100) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}}, {"id": "g", "type": "grayscale", "params": {}},
            {"id": "t", "type": "intensity", "params": {}}, {"id": "rng", "type": "in_range", "params": {"low": low, "high": 255}},
            {"id": "ok", "type": "judge", "params": {"verdict": "ok"}}, {"id": "ng", "type": "judge", "params": {"verdict": "ng"}},
        ],
        "edges": [
            {"source": "src", "target": "g"}, {"source": "g", "target": "t"}, {"source": "t", "source_handle": "mean", "target": "rng", "target_handle": "value"},
            {"source": "rng", "source_handle": "inside", "target": "ok", "target_handle": "_flow"}, {"source": "rng", "source_handle": "outside", "target": "ng", "target_handle": "_flow"},
        ],
    }


def make_run(owner=None):
    """三張灰階影像（亮／暗／中）＋期望 ok／ng／ng 的已完成批次執行。"""
    source = ImageSource.objects.create(name=f"syn-{time.time_ns()}", kind="synthetic", config={"width": 64, "height": 48})
    flow = Flow.objects.create(name="gate", graph=gate_graph(source.id), owner=owner)
    bset = BatchSet.objects.create(flow=flow, name="s")
    store.save_images(bset, [("bright", np.full((48, 64, 3), 200, np.uint8)), ("dark", np.full((48, 64, 3), 20, np.uint8)), ("mid", np.full((48, 64, 3), 150, np.uint8))])
    bset.images[0]["expected"], bset.images[1]["expected"], bset.images[2]["expected"] = "ok", "ng", "ng"
    bset.save(update_fields=["images"])
    rows, wall = jobs.execute_rows(flow, flow.graph, bset.images)
    return flow, bset, store.save_completed_run(bset, flow.graph, rows, origin="manual", wall_ms=wall)


EDITOR = agent_api.ChatContext(kind="flow_editor", flow_id=1, graph=GRAPH)
TOOL = agent_api.ChatContext(kind="tool", flow_id=1, node_type="blob", graph=GRAPH)
BATCH = agent_api.ChatContext(kind="batch", flow_id=1, batch_run_id=1)
PAGE = agent_api.ChatContext(kind="page", route="/sources")

#: (訊息, 脈絡, 期望意圖)
INTENT_CORPUS = [
    ("把 二值化 的 threshold 改成 80", EDITOR, "edit"), ("停用去雜訊", EDITOR, "edit"), ("刪除結果影像", EDITOR, "edit"), ("在找圓後面加公差判定 ±0.5", EDITOR, "edit"),
    ("門檻放寬一點", EDITOR, "edit"), ("誤判太多了", EDITOR, "edit"), ("期望數量改為 4", EDITOR, "edit"), ("Set blob min_area to 40", EDITOR, "edit"), ("把顏色比對換成顏色範圍", EDITOR, "edit"),
    ("新增一個判定步驟", TOOL, "edit"), ("min_area 調到 60", TOOL, "edit"),
    ("如何在畫布上連接兩個步驟？", EDITOR, "help"), ("blob 的 min_area 是做什麼的", EDITOR, "help"), ("此工具可以接到哪些工具", TOOL, "help"), ("為什麼試執行沒有影像", EDITOR, "help"),
    ("How do I add an ROI?", EDITOR, "help"), ("停用去雜訊會有什麼影響？", EDITOR, "help"), ("此工具的參數各代表什麼？", TOOL, "help"), ("參數該如何調整才不會誤判？", TOOL, "help"),
    ("為什麼第 3 張 NG？", BATCH, "consult"), ("哪個門檻該調？", BATCH, "consult"), ("與上一次相比改善了什麼？", BATCH, "consult"), ("未命中的影像有哪些", BATCH, "consult"),
    ("這次執行的結果如何", BATCH, "consult"), ("耗時最久的節點是哪個", BATCH, "consult"), ("为什么第 3 张 NG？", BATCH, "consult"), ("Why is image 3 NG?", BATCH, "consult"),
    ("把 in_range 的 low 改成 170", BATCH, "tune"), ("NG 的那幾張其實是好品，誤判偏多", BATCH, "tune"), ("自動調參", BATCH, "tune"), ("放寬門檻", BATCH, "tune"),
    ("把阈值改成 80", BATCH, "tune"), ("increase the threshold", BATCH, "tune"),
    ("如何匯出 CSV？", BATCH, "help"), ("批次測試與 Golden Set 有何不同", BATCH, "help"), ("如何把結果存入 Golden Set？", BATCH, "help"),
    ("把門檻改成 80", PAGE, "help"), ("如何從資料夾建立影像來源？", PAGE, "help"), ("誤判太多", PAGE, "help"), ("Golden Set 是什麼", PAGE, "help"),
]

#: (問題, 可接受的頁面集合；"tool" 代表工具技能段)
SEARCH_BENCH = [
    ("如何從資料夾建立影像來源？", {"guide/user-guide", "plugins.html", "automation.html"}),
    ("相機接在另一台電腦要怎麼取像", {"capture-client.html", "guide/user-guide", "automation.html"}),
    ("批次測試與 Golden Set 有何不同", {"guide/batch", "guide/golden", "guide/user-guide"}),
    ("如何用 PLC 觸發執行並取回結果", {"automation.html", "guide/user-guide", "modbus.html"}),
    ("Modbus 寫暫存器", {"modbus.html"}),
    ("如何安裝外掛工具", {"plugins.html"}),
    ("YOLO 訓練需要安裝什麼", {"guide/dl"}),
    ("配方是什麼", {"guide/user-guide", "architecture.html", "guide/glossary", "contract.html", "workflow-design.html"}),
    ("引擎鎖定時為什麼回 423", {"automation.html", "contract.html", "guide/user-guide", "architecture.html", "guide/glossary"}),
    ("範本畫廊怎麼用", {"guide/samples", "guide/user-guide"}),
    ("卡尺量測寬度", {"tool", "guide/vision-capabilities", "workflow-design.html", "guide/samples"}),
    ("blob 最小面積", {"tool", "guide/vision-capabilities"}),
    ("template_match 金字塔", {"tool", "performance.html", "guide/vision-capabilities"}),
    ("SSE 事件串流", {"automation.html", "contract.html", "architecture.html", "guide/user-guide"}),  # 指南的 Quick reference 列出 SSE 端點
    ("代理模式是什麼", {"guide/agent", "guide/user-guide"}),
    ("自動調參怎麼跑", {"guide/agent", "guide/batch", "guide/golden", "guide/user-guide"}),
    ("執行緒池與效能", {"performance.html", "architecture.html"}),
    ("How do I export a dataset for YOLO", {"guide/dl"}),
    ("ROI 形狀有哪些", {"guide/vision-capabilities", "guide/user-guide", "contract.html", "guide/glossary"}),
    ("整合方 API 金鑰", {"automation.html", "contract.html", "guide/user-guide", "architecture.html", "guide/glossary"}),
    ("上傳暫存影像", {"guide/user-guide", "architecture.html", "guide/glossary", "performance.html", "guide/agent"}),
    ("Golden Set 回歸進 CI", {"guide/golden"}),
    ("SAM 智慧選取", {"guide/dl"}),
    ("使用者可見文案的用詞規範", {"guide/glossary"}),
    ("影像集最多幾張", {"guide/batch", "guide/user-guide"}),
    # 介面地圖（ui_map.json）：問「在哪裡」要能對到頁面
    ("Modbus 從站要在哪個頁面設定", {"ui", "modbus.html"}),
    ("外掛頁面在哪裡", {"ui", "plugins.html"}),
    ("角色權限在哪裡設定", {"ui", "guide/user-guide", "automation.html", "guide/glossary"}),
    ("Where do I add a new connection", {"ui", "modbus.html", "automation.html", "guide/user-guide"}),
]


class PatchGraphRobustnessTests(TestCase):
    """代理迴圈的 patch_graph：模型常用別名（param／name）或把 set_params 寫成 set_param；缺 key／value 要報錯而不是寫進空參數。"""

    def test_set_param_aliases_and_errors(self):
        from apps.vision.agent import actions

        g, done = actions.apply_ops(GRAPH, [{"op": "set_param", "node": "blob", "param": "min_area", "value": "600"}])
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "blob")["params"]["min_area"], 600)
        self.assertEqual(done, ["blob.min_area = 600"])
        g, done = actions.apply_ops(GRAPH, [{"op": "set_param", "node": "blob", "params": {"min_area": 50, "max_area": 900}}])
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "blob")["params"], {"min_area": 50, "max_area": 900})
        self.assertEqual(done, ["blob 參數 ['max_area', 'min_area']"])
        with self.assertRaises(ValueError):
            actions.apply_ops(GRAPH, [{"op": "set_param", "node": "blob", "value": 1}])
        with self.assertRaises(ValueError):
            actions.apply_ops(GRAPH, [{"op": "set_param", "node": "blob", "key": "min_area"}])
        # 原圖不被就地修改
        self.assertEqual(GRAPH["nodes"][1]["params"], {"min_area": 10})
        self.assertNotIn("", GRAPH["nodes"][1]["params"])


class IntentCorpusTests(TestCase):
    def test_corpus_accuracy(self):
        misses = [(m, c.kind, want, got) for m, c, want in INTENT_CORPUS if (got := agent_api.chat_intent(m, c, "auto")) != want]
        acc = 1 - len(misses) / len(INTENT_CORPUS)
        print(f"\n意圖分流語料 {len(INTENT_CORPUS)} 句：準確率 {acc:.0%}" + (f"，未中：{misses}" if misses else ""))
        self.assertGreaterEqual(acc, 0.95, misses)

    def test_forced_mode_wins(self):
        for mode in ("help", "edit", "consult", "tune"):
            self.assertEqual(agent_api.chat_intent("隨便一句", BATCH, mode), mode)
        self.assertEqual(agent_api.chat_intent("把門檻改成 80", agent_api.ChatContext(kind="flow_editor"), "auto"), "help")  # 沒 graph 不能改
        self.assertEqual(agent_api.chat_intent("為什麼第 3 張 NG？", agent_api.ChatContext(kind="batch"), "auto"), "help")  # 沒選執行不能諮詢


class HelpSearchBenchTests(TestCase):
    def test_hit_rates(self):
        hit1 = hit3 = 0
        misses = []
        for q, pages in SEARCH_BENCH:
            hits = help_mod.search(q, k=3)
            keys = [("tool" if s.kind == "tool" else s.page) for s, _ in hits]
            if keys and keys[0] in pages:
                hit1 += 1
            if any(k in pages for k in keys):
                hit3 += 1
            else:
                misses.append((q, keys))
        n = len(SEARCH_BENCH)
        print(f"\n說明檢索基準 {n} 題：hit@1 {hit1 / n:.0%}、hit@3 {hit3 / n:.0%}" + (f"，未中：{misses}" if misses else ""))
        self.assertGreaterEqual(hit3 / n, 0.85, misses)
        self.assertGreaterEqual(hit1 / n, 0.6)

    def test_performance(self):
        t0 = time.perf_counter()
        idx = help_mod.build_index(force=True)
        build_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        for q, _ in SEARCH_BENCH * 2:
            help_mod.search(q)
        per_ms = (time.perf_counter() - t0) * 1000 / (len(SEARCH_BENCH) * 2)
        print(f"\n索引 {len(idx.sections)} 段建立 {build_ms:.0f} ms、每次檢索 {per_ms:.1f} ms")
        self.assertLess(build_ms, 5000)
        self.assertLess(per_ms, 80)


class HelpRobustnessTests(TestCase):
    def _chat(self, body: dict, **extra):
        return self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json", **extra)

    def test_degenerate_queries(self):
        self.assertEqual(help_mod.search(""), [])
        self.assertEqual(help_mod.search("？！…、。"), [])
        self.assertEqual(help_mod.tokenize(""), [])
        self.assertEqual(help_mod.answer("！！！", providers.AgentSettings())["provider"], "rules")
        r = self._chat({"message": "如何建立流程？" * 800, "context": {"kind": "weird-kind"}})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r.json()["kind"], "help")
        r = self._chat({"message": "<script>alert(1)</script> 如何建立流程", "history": [{"role": 5, "text": None}, {"role": "assistant"}, {"text": 123}]})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertTrue(r.json()["answer"])
        # 非物件的 history 項目由 schema 擋下（422），不會進到服務層
        self.assertEqual(self._chat({"message": "如何建立流程", "history": ["junk"]}).status_code, 422)
        self.assertEqual(self._chat({"message": "如何建立流程", "context": {"batch_run_id": "abc"}}).status_code, 422)
        self.assertEqual(self.client.get("/api/vision/agent/help/search?q=批次&k=0").status_code, 200)
        self.assertLessEqual(len(self.client.get("/api/vision/agent/help/search?q=批次&k=100").json()["items"]), 20)
        self.assertEqual(self.client.get("/api/vision/agent/help/search?q=").json()["items"], [])

    def test_llm_junk_history_and_empty_reply(self):
        with mock.patch.object(providers, "complete", return_value="有答案") as done:
            out = help_mod.answer("如何建立流程？", LLM, history=[{"role": 5, "text": None}, "junk", {"role": "user", "text": "前一句"}])
        self.assertEqual(out["provider"], "openai")
        self.assertIn("前一句", done.call_args.args[3])
        self.assertNotIn("junk", done.call_args.args[3])
        with mock.patch.object(providers, "complete", return_value="   "):
            out = help_mod.answer("如何建立流程？", LLM)
        self.assertEqual(out["provider"], "rules")
        self.assertIn("From the platform documentation:", out["answer"])
        self.assertTrue(any("returned nothing" in w for w in out["warnings"]), out["warnings"])

    def test_index_rebuilds_when_docs_change(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "a.html").write_text('<article><h1>甲</h1><h2 id="x">影像集建立</h2><p>' + "影像集是一組批量測試用的影像。" * 5 + "</p></article>", encoding="utf-8")
            with mock.patch.object(help_mod, "DOCS_DIR", tmp), mock.patch.object(help_mod, "UI_MAP_PATH", tmp / "none.json"):
                first = help_mod.build_index(force=True)
                docs = [s for s in first.sections if s.kind == "doc"]
                self.assertEqual([s.page for s in docs], ["a.html"])
                self.assertEqual(docs[0].url, "/docs/a.html#x")
                self.assertIs(help_mod.build_index(), first)  # 沒變不重建
                (tmp / "b.html").write_text('<article><h1>乙</h1><h2 id="y">Golden 回歸</h2><p>' + "Golden Set 是回歸基準。" * 5 + "</p></article>", encoding="utf-8")
                later = time.time() + 10
                os.utime(tmp / "b.html", (later, later))
                second = help_mod.build_index()
                self.assertIsNot(second, first)
                self.assertEqual(sorted(s.page for s in second.sections if s.kind == "doc"), ["a.html", "b.html"])
                self.assertEqual(help_mod.search("Golden 回歸")[0][0].page, "b.html")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            help_mod.build_index(force=True)

    def test_concurrent_build_and_search(self):
        errors: list[BaseException] = []

        def work(i: int):
            try:
                if i % 3 == 0:
                    help_mod.build_index(force=True)
                assert help_mod.search("批次測試 影像集")
                assert help_mod.answer("如何建立影像集？", providers.AgentSettings())["sources"]
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work, range(24)))
        self.assertEqual(errors, [])
        self.assertGreater(help_mod.index_stats()["sections"], 80)


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False, "API_KEY": "integrator-key"})
class ChatSecurityTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def _chat(self, body: dict, **extra):
        return self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json", **extra)

    def test_auth_visibility_and_lock(self):
        token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret123"}), content_type="application/json").json()["token"]
        admin = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        worker = User.objects.create_user("worker", password="x")
        worker_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(worker)}"}
        flow, bset, run = make_run(owner=User.objects.get(username="admin"))
        batch_ctx = {"kind": "batch", "flow_id": flow.id, "batch_run_id": run.id}
        # 有使用者後未登入 401；整合方金鑰可用
        self.assertEqual(self._chat({"message": "如何建立流程？"}).status_code, 401)
        self.assertEqual(self._chat({"message": "如何建立流程？"}, HTTP_X_API_KEY="integrator-key").status_code, 200)
        # 批次執行屬於產線，工程師都諮詢得到；不存在的仍是 404
        self.assertEqual(self._chat({"message": "為什麼第 3 張 NG？", "context": batch_ctx}, **worker_auth).status_code, 200)
        self.assertEqual(self._chat({"message": "為什麼第 3 張 NG？", "context": batch_ctx}, **admin).json()["kind"], "consult")
        self.assertEqual(self._chat({"message": "為什麼第 3 張 NG？", "context": {**batch_ctx, "batch_run_id": 999999}}, **admin).status_code, 404)
        # 引擎鎖定：問答照常，修改／諮詢／調整 423
        r = self.client.post("/api/vision/lock", data=json.dumps({"reason": "量產中", "ttl_s": 600}), content_type="application/json", HTTP_X_API_KEY="integrator-key")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._chat({"message": "如何建立流程？"}, **admin).status_code, 200)
        self.assertEqual(self._chat({"message": "把 blob 的 min_area 改成 40", "context": {"kind": "flow_editor", "graph": GRAPH}}, **admin).status_code, 423)
        self.assertEqual(self._chat({"message": "為什麼第 3 張 NG？", "context": batch_ctx}, **admin).status_code, 423)
        self.assertEqual(self._chat({"message": "把 rng 的 low 改成 170", "context": batch_ctx}, **admin).status_code, 423)
        self.assertEqual(self._chat({"message": "為什麼第 3 張 NG？", "context": batch_ctx}, HTTP_X_API_KEY="integrator-key").status_code, 200)
        self.assertEqual(self.client.delete("/api/vision/lock", HTTP_X_API_KEY="integrator-key").status_code, 200)
        self.assertEqual(self._chat({"message": "把 rng 的 low 改成 170", "context": batch_ctx}, **admin).json()["kind"], "tune")

    def test_edit_with_broken_graph_is_a_clean_error(self):
        broken = {"nodes": [{"id": "x", "type": "no_such_tool", "params": {}}], "edges": []}
        r = self._chat({"message": "把 x 的 a 改成 1", "context": {"kind": "flow_editor", "graph": broken}})
        self.assertIn(r.status_code, (200, 400, 422), r.content[:200])
        if r.status_code == 200:
            self.assertFalse(r.json()["result"]["applied"])


@override_settings(VISION={**settings.VISION, "ASSET_DIR": Path(TMP), "PERSIST_RUNS": False})
class ChatAgenticJobTests(TransactionTestCase):
    """代理模式：chat 回旗標 → 前端改走 /agent/jobs（task=edit／tune）→ 背景迴圈完成 → 產物有效／落成新批次執行。"""

    def _chat(self, body: dict):
        return self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json")

    def _wait(self, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = self.client.get(f"/api/vision/agent/jobs/{job_id}").json()
            if body["status"] != "running":
                return body
            time.sleep(0.1)
        raise AssertionError("job timeout")

    @staticmethod
    def _script(*names: str):
        queue = [providers.ToolReply("", [providers.ToolCall(f"{n}-{i}", n, {})]) for i, n in enumerate(names)]

        def fake(settings, system, history, tools, *, timeout=None):
            if queue:
                return queue.pop(0)
            return providers.ToolReply("", [providers.ToolCall("fin", "finish", {"rationale": "代理完成"})])

        return fake

    def test_edit_and_tune_through_jobs(self):
        flow, bset, run = make_run()
        with mock.patch.object(providers, "resolve", return_value=AGENTIC):
            r = self._chat({"message": "把 rng 的 low 改成 170", "context": {"kind": "flow_editor", "flow_id": flow.id, "graph": flow.graph}})
            self.assertEqual((r.json()["kind"], r.json()["agentic"]), ("edit", True))
            with mock.patch.object(providers, "complete_tools", side_effect=self._script("get_state")):
                res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "edit", "graph": flow.graph, "instruction": "把 rng 的 low 改成 170"}), content_type="application/json")
                self.assertEqual(res.status_code, 202, res.content)
                body = self._wait(res.json()["id"])
            self.assertEqual(body["status"], "done", body.get("error"))
            validate_graph(body["result"]["graph"])
            self.assertEqual(body["result"]["rationale"], "代理完成")
            # tune：帶 batch_run_id，完成後落成新的一次執行
            r = self._chat({"message": "把 rng 的 low 改成 170", "context": {"kind": "batch", "flow_id": flow.id, "batch_run_id": run.id}})
            self.assertEqual((r.json()["kind"], r.json()["agentic"]), ("tune", True))
            before = BatchRun.objects.count()
            with mock.patch.object(providers, "complete_tools", side_effect=self._script("get_state", "run_trial")):
                res = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "tune", "batch_run_id": run.id, "instruction": "把 rng 的 low 改成 170"}), content_type="application/json")
                self.assertEqual(res.status_code, 202, res.content)
                body = self._wait(res.json()["id"])
            self.assertEqual(body["status"], "done", body.get("error"))
            self.assertEqual(BatchRun.objects.count(), before + 1)
            new = BatchRun.objects.order_by("-id").first()
            self.assertEqual((new.parent_id, new.status, len(new.items)), (run.id, "done", 3))
        # 主執行緒之外的工作都結束了
        self.assertFalse([t for t in threading.enumerate() if t.name.startswith("agent-job") and t.is_alive()])
