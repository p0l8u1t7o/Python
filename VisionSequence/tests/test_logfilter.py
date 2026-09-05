"""access log 遮罩：URL 裡的 token／api_key 不進日誌；serve 的 uvicorn 日誌設定掛上濾器。"""

from __future__ import annotations

import logging

from django.test import SimpleTestCase

from apps.core.logfilter import RedactSecrets, redact


class RedactTests(SimpleTestCase):
    def test_redacts_query_secrets_only(self):
        self.assertEqual(redact("GET /api/vision/images/x?max=800&token=abc.def&api_key=k1 HTTP/1.1"), "GET /api/vision/images/x?max=800&token=***&api_key=*** HTTP/1.1")
        self.assertEqual(redact('POST /api/auth/login "password=hunter2"'), 'POST /api/auth/login "password=***"')
        self.assertEqual(redact("GET /api/vision/flows?limit=5"), "GET /api/vision/flows?limit=5")

    def test_filter_rewrites_msg_and_args(self):
        f = RedactSecrets()
        rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/1.1" %d', ("127.0.0.1:1", "GET", "/api/vision/events?token=abc", 200), None)
        self.assertTrue(f.filter(rec))
        self.assertIn("token=***", rec.getMessage())
        self.assertNotIn("abc", rec.getMessage())
        rec = logging.LogRecord("x", logging.INFO, "", 0, "plain token=zzz", None, None)
        f.filter(rec)
        self.assertEqual(rec.getMessage(), "plain token=***")

    def test_serve_log_config_has_the_filter(self):
        from apps.vision.management.commands.serve import _log_config

        cfg = _log_config()
        self.assertEqual(cfg["filters"]["redact"]["()"], "apps.core.logfilter.RedactSecrets")
        self.assertIn("redact", cfg["handlers"]["access"]["filters"])
