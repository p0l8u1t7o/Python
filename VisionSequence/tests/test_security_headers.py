"""LAN 安全標頭：API 與靜態回應都帶 nosniff／Referrer-Policy／X-Frame-Options；不強制 HTTPS。"""

from __future__ import annotations

from django.conf import settings
from django.test import TestCase


class SecurityHeaderTests(TestCase):
    def test_api_and_docs_carry_the_headers(self):
        for path in ("/healthz", "/docs/index.html"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r["X-Content-Type-Options"], "nosniff", path)
            self.assertEqual(r["Referrer-Policy"], "same-origin", path)
            self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN", path)
            self.assertNotIn("Strict-Transport-Security", r, path)

    def test_no_forced_https(self):
        self.assertFalse(settings.SECURE_SSL_REDIRECT)
        self.assertEqual(self.client.get("/healthz").status_code, 200)  # 不會被 301 到 https

    def test_middleware_order(self):
        mw = settings.MIDDLEWARE
        self.assertEqual(mw[0], "django.middleware.security.SecurityMiddleware")
        self.assertLess(mw.index("whitenoise.middleware.WhiteNoiseMiddleware"), mw.index("corsheaders.middleware.CorsMiddleware"))
        self.assertIn("django.middleware.clickjacking.XFrameOptionsMiddleware", mw)
