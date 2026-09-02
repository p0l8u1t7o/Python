"""AI 助手測試：意圖解析、流程合成（validate 過）、在合成影像上端到端試跑、API 表面。

LLM 供應器不打外網：只驗 available() 在沒金鑰時為 False、generate 走規則引擎。
"""

from __future__ import annotations

import io
import json

import cv2
import numpy as np
from django.test import TestCase

from apps.vision.agent import analysis, intents, service, synth
from apps.vision.graph import validate_graph


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


class IntentTests(TestCase):
    def _parse(self, prompt: str, image: np.ndarray, region: dict | None = None):
        regions = [{"region": region}] if region else []
        feats = analysis.analyze(image, regions)
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

    def test_vague_prompt_falls_back(self):
        intent = self._parse("看一下這個", np.full((200, 200, 3), 128, np.uint8))
        self.assertIn(intent.kind, ("generic", "count", "diameter"))


class SynthTests(TestCase):
    def test_all_synthesizers_validate(self):
        img = part_image()
        region = {"shape": "rect", "x": 50, "y": 100, "w": 540, "h": 280}
        regions = [{"region": region}, {"region": {"shape": "rect", "x": 60, "y": 60, "w": 120, "h": 300}}]
        feats = analysis.analyze(img, regions)
        for kind in intents.INTENT_KINDS:
            intent = intents.Intent(kind=kind, expected_count=5, nominal=100, tol=5)
            graph, rationale = synth.SYNTHESIZERS[kind](intent, regions, feats)
            validate_graph(graph)  # 不合法會 raise
            self.assertTrue(rationale)


class ServiceTests(TestCase):
    def test_generate_count_end_to_end(self):
        img = part_image(5)
        result = service.generate(img, [], "應該有 5 個孔")
        self.assertEqual(result["provider"], "rules")
        self.assertEqual(result["intent"], "count")
        self.assertEqual(result["report"]["status"], "ok", result["report"].get("error"))
        self.assertEqual(result["report"]["outputs"].get("count"), 5)
        # 少一個孔 → NG
        result_ng = service.generate(part_image(4), [], "應該有 5 個孔")
        self.assertEqual(result_ng["report"]["status"], "ng")

    def test_generate_color_presence(self):
        region = {"shape": "rect", "x": 220, "y": 170, "w": 200, "h": 140}
        result = service.generate(red_block_image(), [{"region": region}], "檢查紅色膠塞有沒有")
        self.assertIn(result["intent"], ("color_presence", "presence"))
        self.assertEqual(result["report"]["status"], "ok", result["report"].get("error"))

    def test_refine_rules_adjusts_params(self):
        img = part_image(5)
        result = service.generate(img, [], "應該有 5 個孔")
        refined = service.refine(img, [], "應該有 5 個孔", result["graph"], "改成 4 個")
        thr = next(n for n in refined["graph"]["nodes"] if n["type"] == "if_number")
        self.assertEqual(thr["params"]["threshold"], 4)
        self.assertEqual(refined["report"]["status"], "ng")  # 5 顆 vs 期望 4 → NG

    def test_refine_looser(self):
        img = part_image(5)
        result = service.generate(img, [], "應該有 5 個孔")
        before = next(n for n in result["graph"]["nodes"] if n["type"] == "blob")["params"]["min_area"]
        refined = service.refine(img, [], "應該有 5 個孔", result["graph"], "太敏感了，誤判很多")
        after = next(n for n in refined["graph"]["nodes"] if n["type"] == "blob")["params"]["min_area"]
        self.assertGreater(after, before)

    def test_llm_unavailable_without_key(self):
        from apps.vision.agent import llm

        self.assertFalse(llm.available())


class AgentApiTests(TestCase):
    def _upload(self):
        ok, buf = cv2.imencode(".png", part_image(5))
        f = io.BytesIO(buf.tobytes())
        f.name = "part.png"
        r = self.client.post("/api/vision/agent/image", data={"image": f})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["ref"]

    def test_info(self):
        r = self.client.get("/api/vision/agent/info")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["llm"])

    def test_generate_and_refine_roundtrip(self):
        ref = self._upload()
        r = self.client.post("/api/vision/agent/generate",
                             data=json.dumps({"ref": ref, "prompt": "應該有 5 個孔"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["report"]["status"], "ok")
        self.assertTrue(any(n["type"] == "judge" for n in body["graph"]["nodes"]))
        r = self.client.post("/api/vision/agent/refine",
                             data=json.dumps({"ref": ref, "prompt": "應該有 5 個孔", "graph": body["graph"], "feedback": "改成 6 個"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["report"]["status"], "ng")

    def test_generate_missing_image(self):
        r = self.client.post("/api/vision/agent/generate",
                             data=json.dumps({"ref": "agentnope:upload:image", "prompt": "x"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)
