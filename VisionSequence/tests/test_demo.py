"""示範樣板煙霧測試：seed_demo 建齊來源／資產／2 個示範流程，範例樣板都在範本畫廊，
且每個 builtin 範本掛上對應的樣本來源後實跑一輪不出錯。

runner 會把工作丟進執行緒池（跨執行緒寫 DB），所以用 TransactionTestCase。
樣本圖與資產寫進暫存 ASSET_DIR／SAMPLE_DIR，不碰真正的 data/。
"""

from __future__ import annotations

import shutil
import tempfile

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.vision.api_more import SOURCE_PLACEHOLDER, instantiate
from apps.vision.demo import BUILTIN_TEMPLATES, TEMPLATE_SAMPLE_SOURCES, seed_demo
from apps.vision.graph import validate_graph
from apps.vision.models import Asset, Flow, ImageSource, ResourceGroup


def _vision_with_tmp_asset_dir(tmp: str) -> dict:
    cfg = dict(settings.VISION)
    cfg["ASSET_DIR"] = tmp
    cfg["SAMPLE_DIR"] = f"{tmp}/samples"
    # 不啟動背景持久化執行緒：它會在 teardown 時還握著 SQLite 檔（WinError 32）。
    cfg["PERSIST_RUNS"] = False
    return cfg


class DemoSeedTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-demo-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_seed_builds_and_every_template_runs(self) -> None:
        with override_settings(VISION=_vision_with_tmp_asset_dir(self.tmp)):
            seed_demo()
            seed_demo()  # idempotent：重跑不炸、不重複建資源

            self.assertTrue(ResourceGroup.objects.filter(kind="source", name="範例").exists())
            self.assertGreaterEqual(ImageSource.objects.filter(group="範例").count(), 11)
            self.assertEqual(Asset.objects.filter(group="範例", kind="image").count(), 3)
            # 範例樣板不佔流程清單：seed 只建 2 個示範流程
            self.assertEqual(Flow.objects.count(), 2)

            from apps.vision.runner import runner

            for key, name, _desc, _cat, builder in BUILTIN_TEMPLATES:
                src = ImageSource.objects.get(name=TEMPLATE_SAMPLE_SOURCES[key])
                graph = instantiate(builder(SOURCE_PLACEHOLDER), source_id=src.id)
                flow = Flow.objects.create(name=f"tpl-{key}", graph=validate_graph(graph))
                try:
                    report = runner.run_sync(flow, timeout=60)
                    self.assertIn(report.status, ("ok", "ng"), f"{name} status={report.status} error={report.error}")
                    errors = {nid: nr.message for nid, nr in report.nodes.items() if nr.status == "error"}
                    self.assertFalse(errors, f"{name} 有 error 節點: {errors}")
                finally:
                    flow.delete()
