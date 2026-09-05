"""前端 build 的供應：whitenoise 掛在 /（index no-cache、/assets 一年 immutable、預壓縮檔自動選用），深連結由 _spa 回 index.html。"""

from __future__ import annotations

import gzip
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from whitenoise.middleware import WhiteNoiseMiddleware


class WhiteNoiseRootTests(SimpleTestCase):
    def setUp(self):
        self.dist = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dist, True)
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
        js = self.dist / "assets" / "index-abc12345.js"
        js.write_text("console.log(1)" * 100, encoding="utf-8")
        (self.dist / "assets" / "index-abc12345.js.gz").write_bytes(gzip.compress(js.read_bytes()))
        self.factory = RequestFactory()

    def _middleware(self):
        return WhiteNoiseMiddleware(lambda request: HttpResponse("fallback", status=404))

    def test_root_index_assets_and_compression(self):
        with override_settings(WHITENOISE_ROOT=str(self.dist), WHITENOISE_AUTOREFRESH=False, WHITENOISE_USE_FINDERS=False, STATIC_ROOT=None,
                               WHITENOISE_INDEX_FILE=settings.WHITENOISE_INDEX_FILE, WHITENOISE_IMMUTABLE_FILE_TEST=settings.WHITENOISE_IMMUTABLE_FILE_TEST,
                               WHITENOISE_ADD_HEADERS_FUNCTION=settings.WHITENOISE_ADD_HEADERS_FUNCTION):
            mw = self._middleware()
            r = mw(self.factory.get("/"))
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/html", r["Content-Type"])
            self.assertEqual(r["Cache-Control"], "no-cache")
            r = mw(self.factory.get("/assets/index-abc12345.js"))
            self.assertEqual(r.status_code, 200)
            self.assertIn("immutable", r["Cache-Control"])
            self.assertIn("max-age=315360000", r["Cache-Control"])
            self.assertNotIn("Content-Encoding", r)
            r = mw(self.factory.get("/assets/index-abc12345.js", HTTP_ACCEPT_ENCODING="gzip"))
            self.assertEqual(r["Content-Encoding"], "gzip")
            r = mw(self.factory.get("/assets/index-abc12345.js.map"))
            self.assertEqual(r.status_code, 404)  # 不存在的檔案交給下一層
            r = mw(self.factory.get("/flows/3"))
            self.assertEqual(r.status_code, 404)  # 深連結不是檔案：交給 urls 的 _spa


class SpaFallbackTests(TestCase):
    def test_deep_link_and_missing_asset_return_index(self):
        dist = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dist, True)
        (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
        with override_settings(FRONTEND_DIST=dist):
            for path in ("/flows/3", "/integration/modbus-server", "/assets/gone-deadbeef.js.map"):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200, path)
                self.assertEqual(r["Cache-Control"], "no-cache")
                self.assertEqual(b"".join(r.streaming_content), b"<html>spa</html>")
        with override_settings(FRONTEND_DIST=dist / "nope"):
            self.assertEqual(self.client.get("/flows/3").status_code, 404)
