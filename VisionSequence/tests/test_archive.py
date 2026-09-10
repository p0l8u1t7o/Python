"""影像封存：出貨預設不存，流程自己開；跑完的影像落地、取得回、會照保留期清掉。"""

from __future__ import annotations

import io
import shutil

import cv2
import numpy as np
from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings

from apps.vision import archive
from apps.vision.images import store
from apps.vision.models import Flow, FlowRun, ImageSource
from apps.vision.runner import persister, runner

VISION = settings.VISION


def png(value: int = 120, size: int = 32) -> io.BytesIO:
    img = np.full((size, size, 3), value, np.uint8)
    return io.BytesIO(cv2.imencode(".png", img)[1].tobytes())


def graph_for(source_id: int, *, ng: bool) -> dict:
    """一定會有影像輸出的最短流程；judge 決定 OK 還是 NG。"""
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "gray", "type": "grayscale", "params": {}},
            {"id": "j", "type": "judge", "params": {"verdict": "ng" if ng else "ok"}},
        ],
        "edges": [{"source": "src", "source_handle": "image", "target": "gray", "target_handle": "image"}],
    }


class ArchivePolicyTests(TestCase):
    """純函式：策略解析與「這次要不要存」。"""

    def test_default_is_off_so_disk_is_never_a_surprise(self):
        self.assertEqual(archive.default_policy()["mode"], "off")
        self.assertFalse(archive.wanted(archive.default_policy(), "ng"))

    @override_settings(VISION={**VISION, "ARCHIVE_DEFAULT": "ng"})
    def test_site_default_can_be_preset_for_a_whole_install(self):
        self.assertEqual(archive.default_policy()["mode"], "ng")
        flow = Flow(name="x")
        self.assertEqual(archive.policy_for(flow)["mode"], "ng")
        flow.archive_policy = {"mode": "off"}  # 流程自己的設定蓋過站點預設
        self.assertEqual(archive.policy_for(flow)["mode"], "off")

    def test_sanitize_ignores_junk_and_clamps(self):
        p = archive.sanitize({"mode": "ALL", "pictures": "all", "quality": 999, "sample": -5, "format": "gif", "nope": 1})
        self.assertEqual((p["mode"], p["pictures"], p["quality"], p["sample"], p["format"]), ("all", "all", 100, 0, "jpeg"))
        self.assertEqual(archive.sanitize({"mode": "wat"})["mode"], archive.default_policy()["mode"])
        self.assertEqual(archive.sanitize(None), archive.default_policy())

    def test_wanted_covers_ng_failed_and_sampling(self):
        ng = {**archive.default_policy(), "mode": "ng"}
        self.assertTrue(archive.wanted(ng, "ng"))
        self.assertTrue(archive.wanted(ng, "failed"))
        self.assertFalse(archive.wanted(ng, "ok"))
        sampled = {**ng, "sample": 10}
        self.assertTrue(archive.wanted(sampled, "ok", run_index=20))
        self.assertFalse(archive.wanted(sampled, "ok", run_index=21))
        every = {**ng, "mode": "all"}
        self.assertTrue(archive.wanted(every, "ok", run_index=7))

    def test_pick_refs_keeps_source_when_no_result_image_exists(self):
        class _Node:
            def __init__(self, outputs):
                self.outputs = outputs

        class _Report:
            id = "run1"
            nodes = {
                "a": _Node({"image": {"ref": "run1:a:image"}}),
                "b": _Node({"image": {"ref": "run1:b:image"}, "_image": {"ref": "run1:b:_image"}}),
                "c": _Node({"image": {"ref": "run1:c:image"}, "count": 5}),
            }

        self.assertEqual(archive.pick_refs(_Report(), {"pictures": "result"}), ["run1:a:image"])
        self.assertEqual(len(archive.pick_refs(_Report(), {"pictures": "all"})), 3)  # _image 直通埠不算

    def test_pick_refs_keeps_source_and_draw_result(self):
        class _Node:
            def __init__(self, outputs):
                self.outputs = outputs

        class _Report:
            id = "run1"
            nodes = {
                "src": _Node({"image": {"ref": "run1:src:image"}}),
                "b": _Node({"image": {"ref": "run1:b:image"}}),
                "draw": _Node({"image": {"ref": "run1:draw:image"}}),
            }

        self.assertEqual(archive.pick_refs(_Report(), {"pictures": "result"}), ["run1:src:image", "run1:draw:image"])


@override_settings(VISION={**VISION, "PERSIST_RUNS": True, "ARCHIVE_DIR": str(VISION["ASSET_DIR"].parent / "archive-test")})
class ArchiveRunTests(TransactionTestCase):
    """跑一次流程，影像要真的落地、而且取得回來。"""

    def setUp(self):
        archive.clear()
        self.addCleanup(archive.clear)
        self.addCleanup(lambda: shutil.rmtree(archive.root(), ignore_errors=True))
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48, "pattern": "parts"})
        self.addCleanup(runner.forget, 0)

    def _run(self, *, mode: str, ng: bool = True) -> FlowRun:
        flow = Flow.objects.create(name=f"arch-{mode}-{ng}", graph=graph_for(self.source.id, ng=ng), archive_policy={"mode": mode})
        self.addCleanup(runner.forget, flow.id)
        report = runner.run_sync(flow, trigger="api")
        persister.ensure()
        for _ in range(200):
            row = FlowRun.objects.filter(pk=report.id.replace("-", "")).first()
            if row is not None:
                return row
            import time

            time.sleep(0.02)
        raise AssertionError("FlowRun 沒有被寫進資料庫")

    def test_off_writes_nothing(self):
        row = self._run(mode="off")
        self.assertEqual(row.images, {})
        self.assertEqual(archive.stats()["files"], 0)

    def test_ng_run_is_archived_and_readable_after_the_cache_drops_it(self):
        row = self._run(mode="ng", ng=True)
        self.assertTrue(row.images, "NG 應該被封存")
        self.assertGreaterEqual(archive.stats()["files"], 1)
        ref = next(iter(row.images))
        # 模擬快取淘汰：記憶體沒了，封存還在
        store.drop_run(row.id.hex)
        self.assertIsNone(store.get(ref))
        img = archive.read(row.id.hex, ref)
        self.assertIsNotNone(img, "封存讀不回來就沒有意義")
        self.assertGreater(img.size, 0)

    def test_preview_reuses_an_archived_picture(self):
        """統計頁「在編輯器用這張影像重跑」：快取沒了也能拿封存的那張試執行；真的沒有就 404 image_gone。"""
        import json

        row = self._run(mode="ng", ng=True)
        ref = next(iter(row.images))
        store.drop_run(row.id.hex)
        self.assertIsNone(store.get(ref))
        flow = Flow.objects.get(pk=row.flow_id)
        body = {"graph": flow.graph, "reuse_image_ref": ref}
        r = self.client.post(f"/api/vision/flows/{flow.id}/preview", data=json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(r.json()["status"], ("ok", "ng"))
        r = self.client.post(f"/api/vision/flows/{flow.id}/preview", data=json.dumps({**body, "reuse_image_ref": "nope:src:image"}), content_type="application/json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "image_gone")

    def test_ok_run_is_not_archived_in_ng_mode(self):
        row = self._run(mode="ng", ng=False)
        self.assertEqual(row.images, {})

    def test_purge_by_age(self):
        """0 = 不限；設了天數就照天數清。"""
        import os
        import time

        row = self._run(mode="all", ng=False)
        self.assertTrue(row.images)
        self.assertEqual(archive.purge(days=0, max_bytes=0)["removed"], 0, "0＝不限，不該刪東西")
        old_time = time.time() - 100 * 86400
        for rel in row.images.values():
            os.utime(archive.root() / rel, (old_time, old_time))
        self.assertGreater(archive.purge(days=90, max_bytes=0)["removed"], 0)
        self.assertEqual(archive.stats()["files"], 0)

    def test_purge_by_size(self):
        row = self._run(mode="all", ng=False)
        before = archive.stats()
        self.assertGreater(before["files"], 0)
        result = archive.purge(days=0, max_bytes=1)
        self.assertEqual(result["removed"], before["files"])
        self.assertGreater(result["freed"], 0)
        self.assertEqual(archive.stats()["files"], 0)
        _ = row

    def test_drop_run_removes_the_files(self):
        row = self._run(mode="all", ng=True)
        self.assertTrue(row.images)
        archive.drop_run(row.id.hex, row.images)
        self.assertEqual(archive.stats()["files"], 0)
        archive.drop_run(row.id.hex, row.images)  # 冪等


@override_settings(VISION={**VISION, "ARCHIVE_DIR": str(VISION["ASSET_DIR"].parent / "archive-test2")})
class ArchiveApiTests(TestCase):
    """API：策略進得去、出得來；影像端點在快取沒有時回頭讀封存。"""

    def setUp(self):
        archive.clear()
        self.addCleanup(archive.clear)
        self.source = ImageSource.objects.create(name="syn2", kind="synthetic", config={"width": 32, "height": 32})

    def test_policy_round_trip(self):
        import json

        flow = Flow.objects.create(name="policy", graph=graph_for(self.source.id, ng=True))
        r = self.client.get(f"/api/vision/flows/{flow.id}")
        self.assertEqual(r.json()["archive_policy"]["mode"], "off")
        r = self.client.patch(f"/api/vision/flows/{flow.id}", data=json.dumps({"archive_policy": {"mode": "ng", "sample": 5}}),
                              content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["archive_policy"]["mode"], "ng")
        self.assertEqual(r.json()["archive_policy"]["sample"], 5)
        flow.refresh_from_db()
        self.assertEqual(flow.archive_policy["mode"], "ng")

    def test_image_endpoint_falls_back_to_the_archive(self):
        import uuid

        flow = Flow.objects.create(name="fallback", graph=graph_for(self.source.id, ng=True))
        run_id = uuid.uuid4()
        ref = f"{run_id.hex}:draw:image"

        class _Report:
            id = run_id.hex
            flow_id = flow.id
            started_at = 0.0
            archive_policy = {**archive.default_policy(), "mode": "all"}

        written = archive.save(_Report(), {ref: np.full((16, 16, 3), 200, np.uint8)})
        self.assertEqual(len(written), 1)
        FlowRun.objects.create(id=run_id, flow=flow, flow_version=1, status="ng", images=written,
                               started_at="2026-01-01T00:00:00Z", finished_at="2026-01-01T00:00:01Z")
        self.assertIsNone(store.get(ref))  # 記憶體裡本來就沒有
        r = self.client.get(f"/api/vision/images/{ref}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertGreater(len(r.content), 100)
        # 沒封存的 ref 仍是 404
        self.assertEqual(self.client.get(f"/api/vision/images/{run_id.hex}:nope:image").status_code, 404)
