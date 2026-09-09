"""手眼標定通訊訊號佇列。"""

from __future__ import annotations

from django.test import TestCase

from apps.vision import calib_signals


class CalibrationSignalsTests(TestCase):
    def setUp(self):
        calib_signals.clear()
        self.addCleanup(calib_signals.clear)

    def test_push_since_latest_and_clear(self):
        a = calib_signals.push("start", source="Start")
        b = calib_signals.push("point", x="10.5", y=20, r="90", source="Calibration(10.5,20,90)")
        self.assertGreater(b["seq"], a["seq"])
        self.assertEqual(calib_signals.since(a["seq"]), [b])
        self.assertEqual(calib_signals.latest()["source"], "Calibration(10.5,20,90)")
        seq = calib_signals.current_seq()
        calib_signals.clear()
        self.assertEqual(calib_signals.since(0), [])
        self.assertEqual(calib_signals.current_seq(), seq)

    def test_queue_keeps_the_latest_64_items(self):
        for i in range(70):
            calib_signals.push("point", x=i, y=i + 1)
        items = calib_signals.since(0)
        self.assertEqual(len(items), 64)
        self.assertEqual(items[0]["x"], 6.0)
        self.assertEqual(items[-1]["x"], 69.0)

    def test_rejects_unknown_kind(self):
        with self.assertRaisesMessage(ValueError, "Unknown calibration signal"):
            calib_signals.push("bad")

    def test_api_reads_and_clears_the_queue(self):
        first = calib_signals.push("point", x=1, y=2)
        calib_signals.push("end")
        r = self.client.get(f"/api/vision/calibration/robot/signals?since={first['seq']}")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual([item["kind"] for item in body["items"]], ["end"])
        self.assertEqual(body["last_seq"], body["items"][-1]["seq"])
        r = self.client.delete("/api/vision/calibration/robot/signals")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.client.get("/api/vision/calibration/robot/signals").json()["items"], [])
