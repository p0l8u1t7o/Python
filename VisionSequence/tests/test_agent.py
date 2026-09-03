"""AI 助手測試：意圖解析、流程合成（validate 過）、多影像端到端試跑、編輯指令、批次調參、API 表面、每人供應商設定。

LLM 供應器不打外網：只驗設定解析與「沒金鑰＝離線」。
"""

from __future__ import annotations

import io
import json

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase

from apps.vision.agent import analysis, intents, providers, service, synth
from apps.vision.graph import validate_graph
from apps.vision.models import Asset


def part_image(holes: int = 5) -> np.ndarray:
    """亮板＋N 個暗孔的合成件。"""
    img = np.full((480, 640, 3), 200, np.uint8)
    for i in range(holes):
        cv2.circle(img, (100 + i * 110, 240), 30, (40, 40, 40), -1)
    return img


def red_block_image() -> np.ndarray:
    img = np.full((480, 640, 3), 220, np.uint8)
    cv2.rectangle(img, (200, 150), (440, 330), (40, 40, 200), -1)
    return img


def print_image(stain: bool) -> np.ndarray:
    img = np.full((480, 640, 3), 225, np.uint8)
    cv2.rectangle(img, (120, 100), (520, 380), (60, 70, 80), 4)
    cv2.circle(img, (220, 240), 60, (50, 60, 200), -1)
    if stain:
        cv2.circle(img, (420, 300), 25, (30, 30, 30), -1)
    return img


class IntentTests(TestCase):
    def _parse(self, prompt: str, image: np.ndarray, region: dict | None = None):
        regions = [{"region": region, "image": 0}] if region else []
        feats = analysis.analyze([image], regions)
        return intents.parse(prompt, regions, feats)

    def test_keyword_intents(self):
        img = part_image()
        cases = [
            ("這個區域應該有 5 個孔", "count", 5),
            ("检查有没有 3 个孔", "count", 3),
            ("量這個孔的直徑", "diameter", None),
            ("量測寬度 160±10", "width", None),
            ("兩條邊的夾角要 90 度", "angle", None),
            ("表面有沒有刮痕", "defect", None),
            ("讀取條碼", "barcode", None),
            ("亮度是否正常", "brightness", None),
        ]
        for prompt, kind, count in cases:
            intent = self._parse(prompt, img)
            self.assertEqual(intent.kind, kind, prompt)
            if count is not None:
                self.assertEqual(intent.expected_count, count, prompt)

    def test_tolerance_and_mm(self):
        intent = self._parse("直徑 17.5 ±0.4mm，0.05mm=1px", part_image())
        self.assertEqual(intent.kind, "diameter")
        self.assertEqual(intent.nominal, 17.5)
        self.assertEqual(intent.tol, 0.4)
        self.assertEqual(intent.unit, "mm")
        self.assertAlmostEqual(intent.mm_per_px or 0, 0.05)

    def test_color_match_uses_roi_color(self):
        region = {"shape": "rect", "x": 220, "y": 170, "w": 200, "h": 140}
        intent = self._parse("這一塊的顏色對不對", red_block_image(), region)
        self.assertEqual(intent.kind, "color_match")
        self.assertTrue(intent.color_hex.startswith("#"))

    def test_golden_roles_from_prompt_and_hints(self):
        regions = [{"region": {"shape": "rect", "x": 100, "y": 80, "w": 440, "h": 320}, "image": 0, "hint": ""},
                   {"region": {"shape": "rect", "x": 100, "y": 80, "w": 440, "h": 320}, "image": 1, "hint": ""}]
        feats = analysis.analyze([print_image(False), print_image(True)], regions)
        intent = intents.parse("ROI01 的位置是好品，ROI02 的位置是壞品", regions, feats)
        self.assertEqual(intent.kind, "golden")
        self.assertEqual((intent.good_roi, intent.bad_roi), (0, 1))
        regions[0]["hint"], regions[1]["hint"] = "壞品", "良品"
        intent = intents.parse("比對這兩塊", regions, feats)
        self.assertEqual((intent.good_roi, intent.bad_roi), (1, 0))

    def test_vague_prompt_falls_back(self):
        intent = self._parse("看一下這個", np.full((200, 200, 3), 128, np.uint8))
        self.assertIn(intent.kind, ("generic", "count", "diameter"))


class SynthTests(TestCase):
    def test_all_synthesizers_validate(self):
        img = part_image()
        region = {"shape": "rect", "x": 50, "y": 100, "w": 540, "h": 280}
        regions = [{"region": region, "image": 0}, {"region": {"shape": "rect", "x": 60, "y": 60, "w": 120, "h": 300}, "image": 0}]
        feats = analysis.analyze([img], regions)
        for kind in intents.INTENT_KINDS:
            intent = intents.Intent(kind=kind, expected_count=5, nominal=100, tol=5, good_roi=0, bad_roi=1)
            graph, rationale = synth.synthesize(intent, regions, feats)
            validate_graph(graph)  # 不合法會 raise
            self.assertTrue(rationale)


class ServiceTests(TestCase):
    def test_generate_count_end_to_end(self):
        result = service.generate([part_image(5)], [], "應該有 5 個孔")
        self.assertEqual(result["provider"], "rules")
        self.assertEqual(result["intent"], "count")
        self.assertEqual(result["report"]["status"], "ok", result["report"].get("error"))
        self.assertEqual(result["report"]["outputs"].get("count"), 5)
        result_ng = service.generate([part_image(4)], [], "應該有 5 個孔")
        self.assertEqual(result_ng["report"]["status"], "ng")

    def test_generate_multi_image_reports(self):
        result = service.generate([part_image(5), part_image(4)], [], "應該有 5 個孔")
        self.assertEqual([r["status"] for r in result["reports"]], ["ok", "ng"])
        self.assertEqual(result["main_image"], 0)

    def test_generate_golden_from_two_images(self):
        roi = {"shape": "rect", "x": 100, "y": 80, "w": 440, "h": 320}
        regions = [{"region": roi, "image": 0, "hint": "好品"}, {"region": roi, "image": 1, "hint": "壞品"}]
        result = service.generate([print_image(False), print_image(True)], regions, "ROI01 是好品，ROI02 是壞品，找出差異")
        self.assertEqual(result["intent"], "golden")
        self.assertEqual(result["main_image"], 1)  # 壞品那張當主影像
        self.assertEqual([r["status"] for r in result["reports"]], ["ok", "ng"])
        self.assertEqual(Asset.objects.filter(group="AI 助手").count(), 1)

    def test_generate_color_presence(self):
        region = {"shape": "rect", "x": 220, "y": 170, "w": 200, "h": 140}
        result = service.generate([red_block_image()], [{"region": region, "image": 0}], "檢查紅色膠塞有沒有")
        self.assertIn(result["intent"], ("color_presence", "presence"))
        self.assertEqual(result["report"]["status"], "ok", result["report"].get("error"))

    def test_refine_rules_adjusts_params(self):
        img = part_image(5)
        result = service.generate([img], [], "應該有 5 個孔")
        refined = service.refine([img], [], "應該有 5 個孔", result["graph"], "改成 4 個")
        thr = next(n for n in refined["graph"]["nodes"] if n["type"] == "if_number")
        self.assertEqual(thr["params"]["threshold"], 4)
        self.assertEqual(refined["report"]["status"], "ng")

    def test_refine_looser(self):
        img = part_image(5)
        result = service.generate([img], [], "應該有 5 個孔")
        before = next(n for n in result["graph"]["nodes"] if n["type"] == "blob")["params"]["min_area"]
        refined = service.refine([img], [], "應該有 5 個孔", result["graph"], "太敏感了，誤判很多")
        after = next(n for n in refined["graph"]["nodes"] if n["type"] == "blob")["params"]["min_area"]
        self.assertGreater(after, before)

    def test_edit_rules(self):
        img = part_image(5)
        graph = service.generate([img], [], "應該有 5 個孔")["graph"]
        out = service.edit(graph, "把 二值化 的 threshold 改成 80", img)
        self.assertTrue(out["applied"], out["rationale"])
        thr = next(n for n in out["graph"]["nodes"] if n["type"] == "threshold")
        self.assertEqual(thr["params"]["threshold"], 80)
        out = service.edit(graph, "停用 去雜訊", None)
        blur = next(n for n in out["graph"]["nodes"] if n["type"] == "blur")
        self.assertFalse(blur["enabled"])
        out = service.edit(graph, "刪除 結果影像", None)
        self.assertFalse(any(n["type"] == "draw_result" for n in out["graph"]["nodes"]))
        out = service.edit(graph, "幫我泡杯咖啡", None)
        self.assertFalse(out["applied"])

    def test_tune_reruns_batch(self):
        imgs = {"a": part_image(5), "b": part_image(4)}
        graph = service.generate([imgs["a"]], [], "應該有 5 個孔")["graph"]
        runs = [{"name": "a", "image_ref": "a", "status": "ok", "outputs": {"count": 5}},
                {"name": "b", "image_ref": "b", "status": "ng", "outputs": {"count": 4}}]
        out = service.tune(graph, "改成 4 個", runs, imgs)
        self.assertTrue(out["applied"])
        self.assertEqual(out["before"], {"ok": 1, "ng": 1, "failed": 0})
        self.assertEqual(out["after"], {"ok": 1, "ng": 1, "failed": 0})
        self.assertEqual([it["after"] for it in out["items"]], ["ng", "ok"])


class SkillsTests(TestCase):
    def test_every_tool_has_a_skill_and_core_ones_are_curated(self):
        from apps.vision.agent import skills
        from apps.vision.tools import base as tools

        items = skills.list_skills()
        keys = {it["key"] for it in items}
        self.assertTrue({"platform", "design", "note"} <= keys)
        for t in tools.all_types():
            self.assertIn(t.key, keys)
            text = skills.skill_text(t.key)
            self.assertIn("## 參數", text)
            self.assertIn("## 輸出埠", text)
        curated = {it["key"] for it in items if it["curated"]}
        self.assertTrue({"find_circle", "caliper", "blob", "defect_diff", "judge", "output", "template_match"} <= curated)
        self.assertGreaterEqual(len(curated), 40)

    def test_select_tools_by_keywords_roi_intent_and_graph(self):
        from apps.vision.agent import skills

        picked = skills.select_tools("量孔的直徑 17.5±0.4mm")
        self.assertIn("find_circle", picked)
        self.assertIn("tolerance_judge", picked)
        self.assertIn("judge", picked)  # 核心永遠在
        picked = skills.select_tools("", [{"region": {"shape": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1}}])
        self.assertIn("wall_thickness", picked)
        picked = skills.select_tools("", intent_kind="golden")
        self.assertIn("defect_diff", picked)
        graph = {"nodes": [{"id": "a", "type": "fft_filter"}]}
        self.assertIn("fft_filter", skills.select_tools("", graph=graph))

    def test_system_prompt_is_stable_and_carries_platform_rules(self):
        from apps.vision.agent import llm, skills

        s1, s2 = llm.system_prompt(), llm.system_prompt()
        self.assertEqual(s1, s2)
        self.assertIn("平台規則", s1)
        self.assertIn("收尾規則", s1)
        self.assertIn("# 工具目錄", s1)
        self.assertNotIn("dl_classify", skills.brief_catalogue())  # 不生成的工具不進目錄
        focus = skills.focus_text(["find_circle"])
        self.assertIn("annulus", focus)

    def test_skills_api(self):
        r = self.client.get("/api/vision/agent/skills")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.json()["items"]), 50)
        r = self.client.get("/api/vision/agent/skills/find_circle")
        self.assertEqual(r.status_code, 200)
        self.assertIn("找圓", r.json()["markdown"])
        self.assertEqual(self.client.get("/api/vision/agent/skills/nope").status_code, 404)


class ImageStorePinnedTests(TestCase):
    def test_pinned_scratch_survives_run_rotation(self):
        from apps.vision.images import ImageStore

        s = ImageStore()
        img = np.zeros((4, 4), np.uint8)
        s.put("scratch1:upload:image", img, flow_id=7, run_id="scratch1", pinned=True)
        for i in range(12):  # 超過 KEEP_RUN_IMAGES（8）次試跑
            s.put(f"run{i}:n:image", img, flow_id=7, run_id=f"run{i}")
        self.assertIsNotNone(s.get("scratch1:upload:image"))
        self.assertIsNone(s.get("run0:n:image"))  # 一般 run 照舊輪替

    def test_settings_test_endpoint(self):
        r = self.client.post("/api/vision/agent/settings/test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])  # 伺服器預設離線
        from apps.vision.agent import providers

        out = providers.test_connection(providers.AgentSettings(provider="claude", api_key="", source="user"))
        self.assertFalse(out["ok"])
        self.assertIn("金鑰", out["reason"])
        # 供應商錯誤翻譯（不打外網）
        self.assertIn("金鑰無效", providers._explain(RuntimeError("HTTP 400: API key not valid. Please pass a valid API key.")))
        self.assertIn("模型", providers._explain(RuntimeError("HTTP 404: model 'nope' does not exist")))
        self.assertIn("gemini-3.6-flash", providers._explain(RuntimeError('HTTP 404: {"error": {"message": "This model models/gemini-2.0-flash is no longer available. Please update your code to use models/gemini-3.6-flash"}}')))
        self.assertIn("過載", providers._explain(RuntimeError("HTTP 503: This model is currently experiencing high demand")))
        self.assertIn("anthropic", providers._explain(ImportError("No module named 'anthropic'")))
        # 列模型：離線回空、缺金鑰回原因（不打外網）
        self.assertEqual(providers.list_models(providers.AgentSettings())["models"], [])
        out = providers.list_models(providers.AgentSettings(provider="openai", api_key="", source="user"))
        self.assertFalse(out["ok"])
        self.assertEqual(self.client.post("/api/vision/agent/settings/models").json()["ok"], True)


class ClarifyTests(TestCase):
    """詢問機制：資訊不足先問、答了就 ready、答案併進提示詞影響生成。"""

    def test_vague_prompt_asks_for_goal_then_ready(self):
        img = part_image(5)
        out = service.clarify([img], [], "看一下這個")
        self.assertFalse(out["ready"])
        self.assertEqual(out["questions"][0]["id"], "goal")
        self.assertEqual(out["questions"][0]["kind"], "choice")
        out2 = service.clarify([img], [], "看一下這個", answers=[{"id": "goal", "answer": "count"}, {"id": "count", "answer": "5"}, {"id": "roi_scope", "answer": "whole"}])
        self.assertTrue(out2["ready"], out2)
        self.assertEqual(out2["intent"], "count")

    def test_count_without_number_asks_optional_and_is_ready(self):
        out = service.clarify([part_image(5)], [], "數一數有幾個孔")
        ids = [q["id"] for q in out["questions"]]
        self.assertIn("count", ids)
        self.assertTrue(all(q["optional"] for q in out["questions"] if q["id"] == "count"))
        self.assertIn("roi_scope", ids)  # 沒圈 ROI → 問範圍（必答）
        self.assertFalse(out["ready"])

    def test_diameter_needs_roi_and_mm_scale(self):
        img = np.full((300, 300, 3), 200, np.uint8)  # 沒有圓 → 一定要 ROI
        out = service.clarify([img], [], "量直徑 10±0.2mm")
        ids = [q["id"] for q in out["questions"]]
        self.assertIn("roi", ids)
        self.assertIn("mm_per_px", ids)
        self.assertFalse(out["ready"])

    def test_angle_needs_two_rois(self):
        roi = {"shape": "rect", "x": 10, "y": 10, "w": 100, "h": 50}
        out = service.clarify([part_image()], [{"region": roi, "image": 0}], "兩邊夾角 90±1")
        self.assertEqual(out["questions"][0]["id"], "roi")

    def test_answers_flow_into_generation(self):
        img = part_image(5)
        answers = [{"id": "goal", "answer": "count"}, {"id": "count", "answer": "4"}, {"id": "polarity", "answer": "dark"}, {"id": "roi_scope", "answer": "whole"}]
        result = service.generate([img], [], "看一下這個", answers=answers)
        self.assertEqual(result["intent"], "count")
        self.assertEqual(result["report"]["status"], "ng")  # 5 顆 vs 期望 4
        thr = next(n for n in result["graph"]["nodes"] if n["type"] == "threshold")
        self.assertTrue(thr["params"]["invert"])  # 極性回答生效
        self.assertEqual(result["warnings"], [])

    def test_generate_without_answers_reports_warnings(self):
        result = service.generate([part_image(5)], [], "數一數有幾個孔")
        self.assertTrue(any("期望的數量" in w for w in result["warnings"]))

    def test_clarify_api(self):
        ok, buf = cv2.imencode(".png", part_image(5))
        f = io.BytesIO(buf.tobytes())
        f.name = "p.png"
        ref = self.client.post("/api/vision/agent/image", data={"image": f}).json()["ref"]
        r = self.client.post("/api/vision/agent/clarify", data=json.dumps({"images": [ref], "prompt": "看一下"}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["ready"])
        r = self.client.post("/api/vision/agent/generate", data=json.dumps({"images": [ref], "prompt": "看一下", "answers": [{"id": "goal", "answer": "count"}]}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["intent"], "count")


class Phase0Tests(TestCase):
    """Phase 0：缺陷修正、常數特徵化、供應商相容端點、兩層工具挑選。"""

    def test_golden_reachable_without_tagged_roi(self):
        roi = {"shape": "rect", "x": 100, "y": 80, "w": 440, "h": 320}
        out = service.clarify([print_image(False)], [{"region": roi, "image": 0}], "用良品比對找差異")
        self.assertEqual(out["intent"], "golden")
        self.assertEqual(out["questions"][0]["id"], "roi")

    def test_barcode_and_brightness_ask(self):
        out = service.clarify([part_image(5)], [], "讀取條碼")
        self.assertEqual([q["id"] for q in out["questions"]], ["expected"])
        self.assertTrue(out["questions"][0]["optional"])
        out = service.clarify([part_image(5)], [], "亮度是否正常")
        self.assertEqual([q["id"] for q in out["questions"]], ["range"])
        out = service.clarify([part_image(5)], [], "亮度是否正常 80~180")
        self.assertTrue(out["ready"])
        result = service.generate([part_image(5)], [], "亮度是否正常 80~180")
        rng = next(n for n in result["graph"]["nodes"] if n["type"] == "in_range")
        self.assertEqual((rng["params"]["low"], rng["params"]["high"]), (80, 180))
        result = service.generate([part_image(5)], [], "讀取條碼", answers=[{"id": "expected", "answer": "ABC123"}])
        bc = next(n for n in result["graph"]["nodes"] if n["type"] == "barcode")
        self.assertEqual(bc["params"]["expected"], "ABC123")

    def test_width_uses_calibration_when_mm_given(self):
        roi = {"shape": "rect", "x": 50, "y": 200, "w": 540, "h": 80}
        feats = analysis.analyze([part_image(5)], [{"region": roi, "image": 0}])
        intent = intents.parse("量寬度 8±0.5mm，0.05mm=1px", [{"region": roi, "image": 0}], feats)
        graph, _ = synth.synthesize(intent, [{"region": roi, "image": 0}], feats)
        types = [n["type"] for n in graph["nodes"]]
        self.assertIn("calibration", types)
        self.assertEqual(next(n for n in graph["nodes"] if n["type"] == "output")["params"]["name"], "width_mm")
        self.assertEqual(next(n for n in graph["nodes"] if n["type"] == "tolerance_judge")["params"]["unit"], "mm")

    def test_analysis_robust_features(self):
        feats = analysis.analyze([part_image(5)], [{"region": {"shape": "rect", "x": 0, "y": 0, "w": 640, "h": 480}, "image": 0}])
        r = feats["regions"][0]
        for key in ("mad", "area", "gradient", "color_std"):
            self.assertIn(key, r)
        self.assertEqual(r["area"], 640 * 480)

    def test_defect_uses_fft_on_textured_surface(self):
        from apps.vision import demo_images

        img = demo_images.textile()[3]
        result = service.generate([img], [], "表面有沒有刮痕")
        types = [n["type"] for n in result["graph"]["nodes"]]
        self.assertIn("fft_filter", types)
        self.assertEqual(result["report"]["status"], "ng")

    def test_select_tools_keeps_intent_tools_with_big_graph(self):
        from apps.vision.agent import skills

        graph = {"nodes": [{"id": f"n{i}", "type": t} for i, t in enumerate(["blur", "lut", "filter", "fft_filter", "crop", "resize", "color_convert", "color_range", "apply_mask", "arithmetic", "warp_perspective", "rotate_flip", "hough_lines", "line_profile", "histogram", "edge_density", "text_presence", "barcode"])]}
        picked = skills.select_tools("量直徑", intent_kind="diameter", graph=graph)
        self.assertIn("find_circle", picked)
        self.assertIn("tolerance_judge", picked)
        self.assertLessEqual(len(picked), 24)

    def test_openai_compatible_and_reasoning_models(self):
        body = providers.openai_body("o4-mini", [{"role": "user", "content": "x"}], json_mode=True)
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        body = providers.openai_body("gpt-4o", [{"role": "user", "content": "x"}])
        self.assertIn("max_tokens", body)
        self.assertNotIn("response_format", body)
        s = providers.AgentSettings(provider="openai_compatible", base_url="http://127.0.0.1:11434/v1", model="llama3.2-vision", source="user")
        self.assertTrue(s.uses_llm)
        self.assertTrue(providers.available(s))
        self.assertEqual(providers.missing_reason(providers.AgentSettings(provider="openai_compatible", source="user")), "未填 base URL（例如 http://127.0.0.1:11434/v1）")
        self.assertEqual(providers.compat_url("http://h/v1/", "chat/completions"), "http://h/v1/chat/completions")
        self.assertIn("120", providers._explain(RuntimeError("timed out"), 120.0))


class ProviderSettingsTests(TestCase):
    def test_server_default_is_offline_without_key(self):
        s = providers.server_settings()
        self.assertEqual(s.provider, "offline")
        self.assertFalse(providers.available(s))

    def test_user_settings_override_server(self):
        user = User.objects.create_user("u1", password="pw")
        self.assertEqual(providers.resolve(user).provider, "offline")
        from apps.accounts.models import UserPref

        UserPref.objects.create(user=user, agent={"provider": "openai", "model": "gpt-4o", "api_key": "sk-test-12345678"})
        s = providers.resolve(user)
        self.assertEqual((s.provider, s.source), ("openai", "user"))
        self.assertTrue(s.uses_llm)
        pub = s.public()
        self.assertEqual(pub["key_hint"], "…5678")
        self.assertNotIn("api_key", pub)


class AgentApiTests(TestCase):
    def _upload(self, img=None):
        ok, buf = cv2.imencode(".png", part_image(5) if img is None else img)
        f = io.BytesIO(buf.tobytes())
        f.name = "part.png"
        r = self.client.post("/api/vision/agent/image", data={"image": f})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["ref"]

    def _json(self, path, body):
        return self.client.post(path, data=json.dumps(body), content_type="application/json")

    def test_info(self):
        r = self.client.get("/api/vision/agent/info")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["llm"])
        self.assertEqual([p["value"] for p in r.json()["providers"]], list(providers.PROVIDERS))

    def test_generate_and_refine_roundtrip(self):
        ref = self._upload()
        r = self._json("/api/vision/agent/generate", {"images": [ref], "prompt": "應該有 5 個孔"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["report"]["status"], "ok")
        self.assertEqual(len(body["reports"]), 1)
        r = self._json("/api/vision/agent/refine", {"images": [ref], "prompt": "應該有 5 個孔", "graph": body["graph"], "feedback": "改成 6 個"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["report"]["status"], "ng")

    def test_legacy_single_ref_still_works(self):
        ref = self._upload()
        r = self._json("/api/vision/agent/generate", {"ref": ref, "prompt": "應該有 5 個孔"})
        self.assertEqual(r.status_code, 200, r.content)

    def test_edit_and_tune_endpoints(self):
        ref = self._upload()
        graph = self._json("/api/vision/agent/generate", {"images": [ref], "prompt": "應該有 5 個孔"}).json()["graph"]
        r = self._json("/api/vision/agent/edit", {"graph": graph, "instruction": "把 二值化 的 threshold 改成 90", "image_ref": ref})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["applied"])
        self.assertIsNotNone(r.json()["report"])
        ref_ng = self._upload(part_image(4))
        runs = [{"name": "a", "image_ref": ref, "status": "ok", "outputs": {"count": 5}}, {"name": "b", "image_ref": ref_ng, "status": "ng", "outputs": {"count": 4}}]
        r = self._json("/api/vision/agent/tune", {"graph": graph, "instruction": "改成 4 個", "runs": runs})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["after"], {"ok": 1, "ng": 1, "failed": 0})

    def test_generate_missing_image(self):
        r = self._json("/api/vision/agent/generate", {"images": ["agentnope:upload:image"], "prompt": "x"})
        self.assertEqual(r.status_code, 404)

    def test_settings_roundtrip_per_user(self):
        # 沒有任何使用者 → bootstrap 放行 setup，拿 token 後以該使用者身分操作
        token = self._json("/api/auth/setup", {"username": "admin", "password": "secret1"}).json()["token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        r = self.client.get("/api/vision/agent/settings", **auth)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["configured"])
        r = self.client.patch("/api/vision/agent/settings", data=json.dumps({"provider": "gemini", "api_key": "AIza-abcdefgh"}), content_type="application/json", **auth)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["provider"], "gemini")
        self.assertTrue(body["has_key"])
        self.assertEqual(body["key_hint"], "…efgh")
        self.assertNotIn("api_key", body)
        # info 反映使用者自己的設定；/auth/me 的 prefs 不含金鑰
        self.assertEqual(self.client.get("/api/vision/agent/info", **auth).json()["provider"], "gemini")
        self.assertNotIn("api_key", json.dumps(self.client.get("/api/auth/me", **auth).json()))
        r = self.client.patch("/api/vision/agent/settings", data=json.dumps({"provider": "gemini", "clear_key": True}), content_type="application/json", **auth)
        self.assertFalse(r.json()["has_key"])
