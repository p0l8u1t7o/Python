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

    def test_pool_size_follows_setting(self):
        with mock.patch.object(stream, "_pool", None), override_settings(VISION={**settings.VISION, "SSE_MAX_STREAMS": 3}):
            pool = stream._executor()
            self.assertEqual(pool._max_workers, 3)
            pool.shutdown(wait=False)
        stream._pool = None
