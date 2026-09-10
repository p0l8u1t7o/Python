"""WP-13 精度驗證：統計函式（手算對照）、確定性流程重複性 σ = 0、注入雜訊的再現性 σ 與注入值相符、GR&R ANOVA、報告 markdown、CLI 門檻、API。"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
from contextlib import redirect_stderr

import cv2
import numpy as np
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from apps.vision import precision
from apps.vision.models import Flow, ImageSource


def _flow_graph(source_id: int) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "label": "src", "enabled": True, "params": {"source_id": source_id}, "position": {"x": 0, "y": 0}},
            {"id": "gray", "type": "grayscale", "label": "gray", "enabled": True, "params": {}, "position": {"x": 200, "y": 0}},
            {"id": "stat", "type": "intensity", "label": "stat", "enabled": True, "params": {"roi": {"shape": "rect", "x": 10, "y": 10, "w": 100, "h": 80}}, "position": {"x": 400, "y": 0}},
            {"id": "out", "type": "output", "label": "out", "enabled": True, "params": {"name": "mean"}, "position": {"x": 600, "y": 0}},
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "gray", "source_handle": "image", "target_handle": "image"},
            {"id": "e2", "source": "gray", "target": "stat", "source_handle": "image", "target_handle": "image"},
            {"id": "e3", "source": "stat", "target": "out", "source_handle": "mean", "target_handle": "value"},
        ],
    }


class PrecisionMathTests(TestCase):
    def test_describe_and_capability(self):
        d = precision.describe([10.0, 10.2, 9.8, 10.1, 9.9])
        self.assertEqual(d["n"], 5)
        self.assertAlmostEqual(d["mean"], 10.0)
        self.assertAlmostEqual(d["std"], float(np.std([10.0, 10.2, 9.8, 10.1, 9.9], ddof=1)))
        self.assertAlmostEqual(d["range"], 0.4)
        self.assertEqual(precision.describe([])["n"], 0)
        self.assertEqual(precision.describe([3.0])["std"], 0.0)
        cap = precision.capability(0.05, 10.02, tolerance=1.0, reference=10.0)
        self.assertAlmostEqual(cap["cg"], 0.2 / (6 * 0.05))
        self.assertAlmostEqual(cap["bias"], 0.02)
        self.assertAlmostEqual(cap["cgk"], (0.1 - 0.02) / (3 * 0.05))
        self.assertEqual(precision.capability(0.05, 10, None, None), {})

    def test_numeric_outputs_skip_bools_and_strings(self):
        series, skipped = precision.numeric_outputs([{"a": 1, "b": True, "c": "x", "d": 2.5}, {"a": 2, "b": False, "c": "y", "d": 3.5}])
        self.assertEqual(series, {"a": [1.0, 2.0], "d": [2.5, 3.5]})
        self.assertEqual(skipped, ["b", "c"])

    def test_grr_anova_matches_hand_calculation(self):
        # 兩件 × 兩次：A = [10, 12]、B = [20, 22] → MS_part = 100、MS_e = 2 → EV √2、PV 7、TV √51、%GRR 19.80、ndc 6
        g = precision.grr_anova({"A": [10.0, 12.0], "B": [20.0, 22.0]}, tolerance=30.0)
        self.assertAlmostEqual(g["ms_part"], 100.0)
        self.assertAlmostEqual(g["ms_error"], 2.0)
        self.assertAlmostEqual(g["ev"], 2 ** 0.5)
        self.assertAlmostEqual(g["pv"], 7.0)
        self.assertAlmostEqual(g["tv"], 51 ** 0.5)
        self.assertAlmostEqual(g["pct_grr"], 100 * (2 ** 0.5) / (51 ** 0.5), places=4)
        self.assertEqual(g["ndc"], 6)
        self.assertEqual(g["verdict"], "acceptable")
        self.assertAlmostEqual(g["pct_grr_tolerance"], 100 * 6 * (2 ** 0.5) / 30)
        self.assertAlmostEqual(g["cg"], 0.2 * 30 / (6 * 2 ** 0.5))
        # 注入雜訊：10 件（均值間隔 1）× 5 次、σ_repeat = 0.05 → EV ≈ 0.05、%GRR < 10（優）
        rng = np.random.default_rng(1)
        parts = {f"p{i}": list(10 + i + rng.normal(0, 0.05, 5)) for i in range(10)}
        g = precision.grr_anova(parts)
        self.assertAlmostEqual(g["ev"], 0.05, delta=0.02)
        self.assertLess(g["pct_grr"], 10)
        self.assertEqual(g["verdict"], "excellent")
        self.assertGreaterEqual(g["ndc"], 5)
        with self.assertRaises(precision.PrecisionError):
            precision.grr_anova({"A": [1.0, 2.0]})
        with self.assertRaises(precision.PrecisionError):
            precision.grr_anova({"A": [1.0], "B": [2.0]})

    def test_check_limits(self):
        result = {"outputs": {"mean": {"stats": {"std": 0.5}}, "d": {"stats": {"std": 0.1}, "grr": {"pct_grr": 35.0}}}}
        self.assertEqual(precision.check_limits(result, {"*": 1.0}), [])
        self.assertEqual(len(precision.check_limits(result, {"*": 0.2})), 1)
        self.assertEqual(len(precision.check_limits(result, {"mean": 0.2, "d": 1.0})), 1)
        self.assertEqual(len(precision.check_limits(result, None, 30.0)), 1)


class PrecisionStudyTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-prec-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        img = np.full((200, 300), 90, np.uint8)
        cv2.rectangle(img, (20, 20), (90, 70), 200, -1)
        cv2.imwrite(os.path.join(self.tmp, "a.png"), img)
        self.folder = ImageSource.objects.create(name="prec folder", kind="folder", config={"path": self.tmp, "loop": True})
        self.synthetic = ImageSource.objects.create(name="prec synthetic", kind="synthetic", config={"width": 320, "height": 240, "pattern": "parts", "seed": 3, "defect_rate": 0.0})
        self.flow = Flow.objects.create(name="prec flow", graph=_flow_graph(self.folder.id))

    def test_repeatability_of_deterministic_flow_is_zero(self):
        result = precision.study(self.flow, "repeatability", repeat=5)
        self.assertEqual(result["runs"], 5)
        self.assertIn("mean", result["outputs"])
        self.assertEqual(result["outputs"]["mean"]["stats"]["std"], 0.0)
        self.assertEqual(result["outputs"]["mean"]["stats"]["range"], 0.0)
        self.assertEqual(result["skipped_outputs"], ["judge"])
        self.assertTrue(result["formulas"])
        md = precision.markdown_report(result)
        self.assertIn("# Repeatability study", md)
        self.assertIn("| σ (sample) | 0.0000 |", md)
        # 帶公差與真值：Cg 無限大（σ = 0）、bias 與 Cgk 存在
        result = precision.study(self.flow, "repeatability", repeat=3, tolerance={"mean": 2.0}, reference={"mean": 100.0})
        e = result["outputs"]["mean"]
        self.assertEqual(e["tolerance"], 2.0)
        self.assertEqual(e["pct_six_sigma_of_tolerance"], 0.0)
        self.assertTrue(np.isinf(e["cg"]))
        self.assertIn("Cgk", precision.markdown_report(result))

    def test_reproducibility_sees_injected_noise(self):
        # 合成來源每次取像都是新雜訊（σ 6 灰階）與隨機位移：ROI 內平均值的 σ 不為 0 且與直接量測相符
        flow = Flow.objects.create(name="prec noisy", graph=_flow_graph(self.synthetic.id))
        result = precision.study(flow, "reproducibility", repeat=12, source_id=self.synthetic.id)
        st = result["outputs"]["mean"]["stats"]
        self.assertGreater(st["std"], 0.0)
        # 直接對同一來源取像算 ROI 平均的 σ，量級應一致（同一分佈的兩組樣本，容許 3 倍）
        from apps.vision.sources import grab_by_id

        vals = []
        for _ in range(12):
            g = cv2.cvtColor(grab_by_id(self.synthetic.id), cv2.COLOR_BGR2GRAY)
            vals.append(float(g[10:90, 10:110].mean()))
        ref = float(np.std(vals, ddof=1))
        self.assertLess(st["std"], ref * 3 + 0.5)
        self.assertGreater(st["std"], ref / 3 - 0.5)
        self.assertEqual(result["mode"], "reproducibility")
        self.assertIn("# Reproducibility study", precision.markdown_report(result))

    def test_grr_study_from_part_images(self):
        rng = np.random.default_rng(7)
        parts: dict[str, list[np.ndarray]] = {}
        for k in range(4):
            imgs = []
            for _ in range(3):
                img = np.full((200, 300), 60 + 20 * k, np.uint8)
                imgs.append(np.clip(img.astype(np.int16) + rng.integers(-1, 2, img.shape), 0, 255).astype(np.uint8))
            parts[f"part{k}"] = imgs
        result = precision.study(self.flow, "grr", parts=parts, tolerance={"mean": 100.0})
        g = result["outputs"]["mean"]["grr"]
        self.assertEqual((g["parts"], g["trials"]), (4, 3))
        self.assertLess(g["pct_grr"], 10)  # 件間差 20 灰階、件內雜訊 < 1
        self.assertGreaterEqual(g["ndc"], 5)
        self.assertIn("pct_grr_tolerance", g)
        md = precision.markdown_report(result)
        self.assertIn("# Gauge R&R study", md)
        self.assertIn("%GR&R (of total variation)", md)
        self.assertIn("| part0 |", md)
        with self.assertRaises(precision.PrecisionError):
            precision.study(self.flow, "grr", parts={"only": parts["part0"]})
        with self.assertRaises(precision.PrecisionError):
            precision.study(self.flow, "nope")

    def test_command_writes_reports_and_enforces_limits(self):
        out_json = os.path.join(self.tmp, "r.json")
        out_md = os.path.join(self.tmp, "r.md")
        stdout = io.StringIO()
        with redirect_stderr(io.StringIO()):
            call_command("precision", str(self.flow.id), "--repeat", "3", "--output", out_json, "--markdown", out_md, "--max-sigma", "0.001", stdout=stdout)
        self.assertIn("PASS (limits met)", stdout.getvalue())
        with open(out_json, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["mode"], "repeatability")
        self.assertTrue(data["limits"]["passed"])
        with open(out_md, encoding="utf-8") as fh:
            self.assertIn("Repeatability study", fh.read())
        # --json 印 JSON；名稱找不到 → CommandError；GR&R 沒給零件 → CommandError；σ 門檻不合格 → CommandError
        stdout = io.StringIO()
        with redirect_stderr(io.StringIO()):
            call_command("precision", "prec flow", "--repeat", "2", "--json", stdout=stdout)
        self.assertEqual(json.loads(stdout.getvalue())["runs"], 2)
        with self.assertRaises(CommandError):
            call_command("precision", "no such flow", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("precision", str(self.flow.id), "--mode", "grr", stdout=io.StringIO())
        noisy = Flow.objects.create(name="prec noisy cli", graph=_flow_graph(self.synthetic.id))
        with self.assertRaisesMessage(CommandError, "precision limits not met"), redirect_stderr(io.StringIO()):
            call_command("precision", str(noisy.id), "--mode", "reproducibility", "--repeat", "4", "--max-sigma", "mean=0.0", stdout=io.StringIO())
        # 零件資料夾
        pdir = os.path.join(self.tmp, "parts")
        for k in range(2):
            os.makedirs(os.path.join(pdir, f"p{k}"))
            for t in range(2):
                cv2.imwrite(os.path.join(pdir, f"p{k}", f"{t}.png"), np.full((200, 300), 80 + 40 * k, np.uint8))
        stdout = io.StringIO()
        with redirect_stderr(io.StringIO()):
            call_command("precision", str(self.flow.id), "--mode", "grr", "--parts-dir", pdir, "--json", "--max-grr", "30", stdout=stdout)
        self.assertEqual(json.loads(stdout.getvalue())["outputs"]["mean"]["grr"]["parts"], 2)

    @override_settings(VISION={**__import__("django.conf").conf.settings.VISION, "PERSIST_RUNS": False})
    def test_api_endpoint(self):
        client = Client()
        r = client.post(f"/api/vision/flows/{self.flow.id}/precision", data=json.dumps({"mode": "repeatability", "repeat": 4}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["runs"], 4)
        self.assertEqual(body["outputs"]["mean"]["stats"]["std"], 0.0)
        self.assertIn("# Repeatability study", body["markdown"])
        r = client.post(f"/api/vision/flows/{self.flow.id}/precision", data=json.dumps({"mode": "grr"}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        r = client.post(f"/api/vision/flows/{self.flow.id}/precision", data=json.dumps({"repeat": 1}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        r = client.post(f"/api/vision/flows/{self.flow.id}/precision", data=json.dumps({"tolerance": {"mean": "x"}}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        r = client.post("/api/vision/flows/999999/precision", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 404)
