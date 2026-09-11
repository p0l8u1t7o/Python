"""SSE 連線上限：超過 VISION_SSE_MAX_STREAMS 回 503＋Retry-After，串流結束或回應關閉都會把名額還回去。"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from apps.vision import stream


class StreamLimitTests(TestCase):
    def test_limit_and_release(self):
        # 其他測試用 test client 開過串流但沒讀完也沒 close（真伺服器會在斷線時 close 而歸還名額），
        # 名額計數會殘留；這裡從 0 起算，測的是「限額、迭代結束歸還、未迭代就 close 也歸還」本身
        with mock.patch.object(stream, "_active", 0), override_settings(VISION={**settings.VISION, "SSE_MAX_STREAMS": 1}):
            with mock.patch.object(stream, "_active", 1):
                r = self.client.get("/api/vision/events?max_seconds=0.2")
                self.assertEqual(r.status_code, 503)
                self.assertEqual(r["Retry-After"], "5")
                self.assertEqual(r.json()["error"]["code"], "too_many_streams")
            r = self.client.get("/api/vision/events?max_seconds=0.2")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(stream.active_streams(), 1)  # 還在串流中
            body = b"".join(r.streaming_content)
            self.assertIn(b"event: hello", body)
            self.assertIn(b"event: bye", body)
            self.assertEqual(stream.active_streams(), 0)  # generator 結束就還
            # 沒開始迭代就關閉回應：名額也要還
            r = self.client.get("/api/vision/events?max_seconds=0.2")
            self.assertEqual(stream.active_streams(), 1)
            r.close()
            self.assertEqual(stream.active_streams(), 0)

    def test_trimmed_run_keeps_node_shape(self):
        # outputs=0 的訂閱者拿到的 run 要瘦身（沒有 outputs／overlays／detail），但每個鍵都在且標 nodes_trimmed，
        # 否則瘦身版經全域串流進了前端快取，編輯器一開 `outputs[...]` 就炸（Temp/Issue 流程工具編輯出錯）。
        node = {"status": "ok", "duration_ms": 1.5, "message": "m", "message_code": "blob.found", "message_args": {"n": "2"},
                "branch": None, "overlay_on": "image",
                "outputs": {"image": {"ref": "r:1:image", "width": 4, "height": 3}}, "overlays": [{"kind": "point"}],
                "detail": {"_input_ref": "x"}, "logs": [{"level": "info", "message": "hi"}]}
        event = {"type": "run_finished", "flow_id": 7, "run": {"id": "r", "nodes": {"n": node}, "outputs": {}}}
        import orjson

        def data_of(frames: list[bytes]) -> dict:
            body = b"".join(frames)
            line = next(ln for ln in body.split(b"\n") if ln.startswith(b"data: "))
            return orjson.loads(line[6:])

        lean = data_of(list(stream._Session(0, 7, False, 1.0).frames([event])))["run"]
        self.assertTrue(lean["nodes_trimmed"])
        self.assertEqual(set(lean["nodes"]["n"]), set(stream.NODE_REPORT_DEFAULTS))
        self.assertEqual(lean["nodes"]["n"]["outputs"], {})
        self.assertEqual(lean["nodes"]["n"]["overlays"], [])
        self.assertEqual(lean["nodes"]["n"]["overlay_on"], "image")
        self.assertEqual(lean["nodes"]["n"]["duration_ms"], 1.5)
        # 訊息代碼與參數很小，瘦身版也要帶著，中文介面的即時畫面才翻得出來
        self.assertEqual(lean["nodes"]["n"]["message_code"], "blob.found")
        self.assertEqual(lean["nodes"]["n"]["message_args"], {"n": "2"})
        full = data_of(list(stream._Session(0, 7, True, 1.0).frames([event])))["run"]
        self.assertNotIn("nodes_trimmed", full)
        self.assertEqual(full["nodes"]["n"]["outputs"]["image"]["ref"], "r:1:image")

    def test_pool_size_follows_setting(self):
        with mock.patch.object(stream, "_pool", None), override_settings(VISION={**settings.VISION, "SSE_MAX_STREAMS": 3}):
            pool = stream._executor()
            self.assertEqual(pool._max_workers, 3)
            pool.shutdown(wait=False)
        stream._pool = None
