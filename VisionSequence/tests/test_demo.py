"""示範樣板煙霧測試：seed_demo 建齊來源／資產／2 個示範流程，範例樣板都在範本畫廊，
且每個 builtin 範本掛上對應的樣本來源後實跑一輪不出錯。

runner 會把工作丟進執行緒池（跨執行緒寫 DB），所以用 TransactionTestCase。
樣本圖與資產寫進暫存 ASSET_DIR／SAMPLE_DIR，不碰真正的 data/。
"""

from __future__ import annotations

import re
import shutil
import tempfile
import os

from django.conf import settings
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.vision.api_more import SOURCE_PLACEHOLDER, instantiate
from apps.vision import demo, fixed_images
from apps.vision.demo import BUILTIN_TEMPLATES, TEMPLATE_SAMPLE_SOURCES, TEMPLATES_NEED_BACKBONE, TEMPLATES_NEED_DL, TEMPLATES_NEED_MODEL, seed_demo
from apps.vision.graph import validate_graph
from apps.vision.models import Asset, Flow, ImageSource, ResourceGroup


def _vision_with_tmp_asset_dir(tmp: str) -> dict:
    cfg = dict(settings.VISION)
    cfg["ASSET_DIR"] = tmp
    cfg["SAMPLE_DIR"] = f"{tmp}/samples"
    # 不啟動背景持久化執行緒：它會在 teardown 時還握著 SQLite 檔（WinError 32）。
    cfg["PERSIST_RUNS"] = False
    return cfg


def _stock_yolo_weights_available() -> bool:
    """Return True only when stock weights are already present; never download in tests."""
    from apps.vision.tools.builtin.yolo import stock_model

    folder = os.path.join(str(settings.VISION["ASSET_DIR"]), "dl", "weights")
    tasks = ("detect", "segment", "classify", "obb", "pose")
    return all(os.path.isfile(os.path.join(folder, stock_model(task, "n"))) for task in tasks)


class DemoSeedTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-demo-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_every_template_over_all_sample_pictures(self) -> None:
        """深度測試：每個範本對它的每張樣本圖各跑一次（engine.execute 直跑），不得有 error 節點，OK/NG 序列要符合樣本的設計
        （多數是「第 4 張刻意 NG」；排除區四張都 OK；DL 範本 3 好 2 壞）。
        這條會抓到「找不到東西時 raise 而不是回 ng」與「blob 找不到把整次 run 判 NG」這類單張測試看不出的毛病。"""
        import importlib.util
        import os

        import numpy as np

        from apps.vision import engine
        from apps.vision.graph import compile_graph
        from apps.vision.runner import runner

        expected = {
            "queue_handoff": "ok ok ok ng",
            "character_count": "ok ok ok ng", "seal_width": "ok ok ok ng",
            "point_fitting": "ok ok ok ng", "polar_edge_check": "ok ok ok ng", "absence_check": "ok ok ok ng",
            "register_count": "ok ok ok ng",
            "register_classes": "ok ok ok ng",
            "register_segment": "ok ok ok ng",
            "hole_count": "ok ok ok ng", "exposure": "ok ok ok ng",
            "circle_gauge": "ok ok ok ng", "edge_angle": "ok ok ok ng", "golden_compare": "ok ok ok ng", "stat_compare": "ok ok ok ng",
            "fft_defect": "ok ok ok ng", "surface_scratch": "ok ok ok ng", "geometry_count": "ok ok ok ng", "gear_teeth": "ok ok ok ng", "contour_defect": "ok ok ok ng",
            "list_postprocess": "ok ok ok ng", "array_placement": "ok ok ok ng", "boxes_cleanup": "ok ok ok ng", "script_measure": "ok ok ok ng",
            "circular_defect": "ok ok ok ng", "edge_defect_demo": "ok ok ok ng", "form_tolerance": "ok ok ok ng", "emboss_defect": "ok ok ok ng", "barcode_grade": "ok ok ok ng",
            "exclusion_zone": "ok ok ok ok", "shading": "ok ok ok ng", "color_presence": "ok ok ok ng", "color_verify": "ok ok ok ng",
            "label_map_count": "ok ok ok ng", "color_sample_classify": "ok ok ok ng",
            "plate_corners": "ok ok ok ng", "parallel_edges": "ok ok ok ng", "hole_matrix": "ok ok ok ng", "edge_trend_peaks": "ok ok ok ng",
            "outline_defect": "ok ok ok ng", "path_edge_search": "ok ok ok ng", "focus_gate": "ok ok ok ng", "temporal_frames": "ng ok ok ng",
            "roi_process_paste": "ok ok ok ng", "manual_undistort_world": "ok ok ok ng", "camera_mapping": "ok ok ok ng",
            "pick_offset": "ok ok ok ng", "fixture_rerun": "ok ok ok ng", "stitch_two_views": "ok ok ok ng",
            "barcode_read": "ok ok ok ng", "code_message_rules": "ok ok ok ng", "date_code": "ok ok ok ng", "label_read": "ok ok ok ng", "shape_locate": "ok ok ok ng",
            "locate_measure": "ok ok ok ng", "cup_measure": "ok ok ok ng", "dl_classify_demo": "ok ok ok ok ng ng", "anomaly_demo": "ok ok ok ng ng",
            "dl_segment_demo": "ok ok ok ng ng", "variable_switch": "ok ok ok ng", "tile_for_each": "ok ok ok ok", "io_sequence": "ok ok ok ng",
            "outputs_bundle": "ok ok ok ng",
            "ai_classify_demo": "ng ng ng ng", "ai_obb_demo": "ng ng ng ng", "ai_pose_demo": "ng ng ng ng",
            "dl_retrieval_demo": "ok ok ok ng", "multi_light_surface": "ok ok ok ng", "guided_code_read": "ok ok ok ng",
        }
        with override_settings(VISION=_vision_with_tmp_asset_dir(self.tmp)):
            seed_demo()
            run_dl = os.environ.get("VISION_TEST_DL") == "1" and importlib.util.find_spec("ultralytics") is not None and _stock_yolo_weights_available()
            from apps.vision.dl import anomaly as _anomaly

            backbone_ok = _anomaly.backbone_available()
            problems: list[str] = []
            for key, name, _desc, _cat, builder in BUILTIN_TEMPLATES:
                if key in TEMPLATES_NEED_MODEL:
                    samples = demo.template_samples(key)
                    self.assertTrue(samples, f"{name} has no samples")
                    compile_graph(validate_graph(instantiate(builder(SOURCE_PLACEHOLDER), source_id=None, samples=samples)))
                    continue
                if (key in TEMPLATES_NEED_DL and not run_dl) or (key in TEMPLATES_NEED_BACKBONE and not backbone_ok):
                    continue
                samples = demo.template_samples(key)
                self.assertTrue(samples, f"{name} 沒有樣本圖")
                compiled = compile_graph(validate_graph(instantiate(builder(SOURCE_PLACEHOLDER), source_id=None, samples=samples)))
                runner._prefetch(compiled)
                statuses = []
                for d in samples:
                    img = fixed_images.load(d["id"])
                    self.assertIsNotNone(img, (name, d))
                    rep = engine.execute(compiled, flow_id=0, flow_version=1, trigger="test", grab=runner._grab, asset_path=runner._asset_path, preview=False, input_image=np.ascontiguousarray(img), run_id=f"seq{key}{d['id']}"[:32])
                    errors = {nid: nr.message for nid, nr in rep.nodes.items() if nr.status == "error"}
                    if errors:
                        problems.append(f"{name} / {d['name']}: error nodes {errors}")
                    statuses.append(rep.status)
                seq = " ".join(statuses)
                if key in expected and seq != expected[key]:
                    problems.append(f"{name}: statuses {seq!r}, expected {expected[key]!r}")
            self.assertFalse(problems, "\n".join(problems))

    def test_seed_builds_and_every_template_runs(self) -> None:
        with override_settings(VISION=_vision_with_tmp_asset_dir(self.tmp)):
            seed_demo()
            seed_demo()  # idempotent：重跑不炸、不重複建資源

            self.assertTrue(ResourceGroup.objects.filter(kind="source", name="Examples").exists())
            # 樣本圖與參考圖都是固定影像（跟著範本走）：來源庫只剩合成來源、資產庫沒有範例影像
            self.assertEqual(ImageSource.objects.filter(group="Examples").count(), 1)
            self.assertEqual(Asset.objects.filter(group="Examples", kind="image").count(), 0)
            self.assertGreaterEqual(len(fixed_images.list_ids()), 60)
            self.assertTrue(all(demo._demo_ref(n) for n in demo.REF_SPECS))
            self.assertEqual(Asset.objects.filter(group="Examples", kind="file").count(), 2)
            # DL 範本用的兩個示範模型（seed 以內建 CPU trainer 訓練）
            model_names = sorted(Asset.objects.filter(group="Examples", kind="model").values_list("name", flat=True))
            expected_models = ["Example: classifier (good / missing hole)", "Example: segmenter (scratch)", "Example: taught font (digits)"]
            from apps.vision.dl import anomaly as _anomaly

            if _anomaly.backbone_available():
                expected_models.append("Example: retrieval library (three part types)")
            self.assertEqual([n for n in model_names if "anomaly" not in n], sorted(expected_models))
            self.assertEqual(len(BUILTIN_TEMPLATES), 76)
            import importlib.util
            import os

            run_dl = os.environ.get("VISION_TEST_DL") == "1" and importlib.util.find_spec("ultralytics") is not None and _stock_yolo_weights_available()

            backbone_ok = _anomaly.backbone_available()
            # 範例樣板不佔流程清單：seed 只建 2 個示範流程
            self.assertEqual(Flow.objects.count(), 2)

            from apps.vision.runner import runner

            # 每個內建範本都有樣本圖：畫廊預設把取像節點換成帶圖的固定影像，載入就能試執行（沒有「請先選來源」）
            self.assertEqual(set(demo.TEMPLATE_SAMPLE_SETS), {key for key, *_ in BUILTIN_TEMPLATES})
            self.assertEqual(set(TEMPLATE_SAMPLE_SOURCES), set(demo.TEMPLATE_SAMPLE_SETS))
            covered = {n["type"] for *_, builder in BUILTIN_TEMPLATES for n in builder(SOURCE_PLACEHOLDER)["nodes"]}
            from apps.vision.tools import base

            builtin = {t.key for t in base.all_types()}
            self.assertFalse(builtin - covered, f"Missing template tools: {sorted(builtin - covered)}")
            for key, name, _desc, _cat, builder in BUILTIN_TEMPLATES:
                samples = demo.template_samples(key)
                self.assertTrue(samples, name)
                graph = instantiate(builder(SOURCE_PLACEHOLDER), source_id=None, samples=samples)
                src = next(n for n in graph["nodes"] if n["id"] == "src")
                self.assertEqual(src["type"], "fixed_image", name)
                self.assertEqual(len(src["params"]["images"]), len(samples), name)
                self.assertFalse([n for n in graph["nodes"] if n["type"] == "image_source"], name)
                if key in TEMPLATES_NEED_MODEL:
                    validate_graph(graph)
                    continue
                if key in TEMPLATES_NEED_DL and not run_dl:
                    validate_graph(graph)  # 沒有 DL 依賴（或未設 VISION_TEST_DL=1）只驗 graph，實跑見 tests/test_dl_live.py
                    continue
                if key in TEMPLATES_NEED_BACKBONE and not backbone_ok:
                    validate_graph(graph)  # 沒有異常檢測 backbone：只驗 graph（有 backbone 的機器會實跑，seed 會訓練示範模型）
                    continue
                flow = Flow.objects.create(name=f"tpl-{key}", graph=validate_graph(graph))
                try:
                    report = runner.run_sync(flow, timeout=60)
                    self.assertIn(report.status, ("ok", "ng"), f"{name} status={report.status} error={report.error}")
                    errors = {nid: nr.message for nid, nr in report.nodes.items() if nr.status == "error"}
                    self.assertFalse(errors, f"{name} 有 error 節點: {errors}")
                finally:
                    flow.delete()


class SimplifiedTemplateTests(SimpleTestCase):
    """新增範本以平台入口驗證接線、缺項與缺陷座標。"""

    def execute_sample(self, key, image, change=None):
        from apps.vision import engine
        from apps.vision.graph import compile_graph

        graph = next(builder(SOURCE_PLACEHOLDER) for name, *_, builder in BUILTIN_TEMPLATES if name == key)
        if change:
            change(graph)
        report = engine.execute(compile_graph(validate_graph(graph)), flow_id=0, flow_version=1, trigger="test", grab=lambda _: image,
                                asset_path=lambda _: None, input_image=image, preview=True)
        self.assertFalse({nid: n.message for nid, n in report.nodes.items() if n.status == "error"})
        return report

    def test_fitting_summary_rejects_a_skipped_required_measurement(self):
        from apps.vision.demo_images import fitted_boundaries

        images = fitted_boundaries()
        good = self.execute_sample("point_fitting", images[0])
        self.assertEqual(good.status, "ok")
        self.assertEqual(good.nodes["summary"].outputs, {"received": 3, "passed": 3, "missing": 0})
        self.assertAlmostEqual(good.nodes["circle"].outputs["diameter"], 200, delta=2)
        self.assertAlmostEqual(good.nodes["ellipse"].outputs["major"], 280, delta=2)
        missing = self.execute_sample("point_fitting", images[3])
        self.assertEqual(missing.nodes["tol_line"].status, "skipped")
        self.assertEqual(missing.nodes["summary"].outputs["missing"], 1)
        self.assertEqual(missing.status, "ng")
        # 良品只停用一項公差，其他工具都正常；NG 必須來自彙總本身。
        skipped = self.execute_sample("point_fitting", images[0], lambda g: next(n for n in g["nodes"] if n["id"] == "tol_line").update(enabled=False))
        self.assertEqual([nid for nid, n in skipped.nodes.items() if n.status == "ng"], ["summary"])
        self.assertEqual(skipped.status, "ng")

    def test_polar_restores_only_the_chip(self):
        import math

        from apps.vision.demo_images import polar_rim_chips

        for index, image in enumerate(polar_rim_chips()):
            with self.subTest(index=index):
                report = self.execute_sample("polar_edge_check", image)
                points = report.nodes["restore"].outputs["points"]
                self.assertEqual(report.status, "ng" if index == 3 else "ok")
                self.assertEqual(len(points), 1 if index == 3 else 0)
                for x, y in points:
                    self.assertAlmostEqual(math.degrees(math.atan2(y - 350, x - 500)), 40, delta=3)
                    self.assertGreater(math.hypot(x - 500, y - 350), 235)
                    self.assertLess(math.hypot(x - 500, y - 350), 255)

    def test_absence_samples_reject_only_foreign_objects_inside_the_region(self):
        from apps.vision.demo_images import clear_exclusion_zone

        reports = [self.execute_sample("absence_check", image) for image in clear_exclusion_zone()]
        self.assertEqual([r.status for r in reports], ["ok", "ok", "ok", "ng"])

    def test_exported_result_image_waits_for_the_verdict(self):
        from unittest.mock import patch

        from apps.vision.demo_images import output_bundle_parts
        from apps.vision.images import store

        with patch.object(demo, "_demo_flow_id", return_value=1):
            for index, image in enumerate(output_bundle_parts()):
                with self.subTest(index=index):
                    report = self.execute_sample("outputs_bundle", image)
                    self.assertEqual(report.status, "ng" if index == 3 else "ok")
                    result = store.get(report.nodes["draw"].outputs["image"]["ref"])
                    self.assertIsNotNone(result)
                    self.assertEqual(result[5, 5].tolist(), [0, 0, 230] if index == 3 else [0, 200, 0])


class TemplateCategoryLabelTests(SimpleTestCase):
    """範本畫廊的分類名稱由前端 `templates.categories` 翻譯：後端多一種分類（automation）而字典沒補，中文介面就會直接顯示英文 key。"""

    def test_every_builtin_category_has_a_label(self):
        from pathlib import Path

        en = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n" / "locales" / "en.ts").read_text(encoding="utf-8")
        m = re.search(r"^\s*categories: \{([^}]*)\}", en, re.M)
        self.assertIsNotNone(m, "templates.categories not found in en.ts")
        labelled = set(re.findall(r"(\w+):", m.group(1)))
        used = {row[3] for row in BUILTIN_TEMPLATES}
        self.assertFalse(used - labelled, f"template categories without a label: {sorted(used - labelled)}")
