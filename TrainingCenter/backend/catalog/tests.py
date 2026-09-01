"""Google 圖片抓取的解析、驗證與存檔路徑測試（HTTP 全部 mock，不會真的連外）。"""

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from catalog import googleimages as gi
from catalog.models import Component, Equipment, Module

CREDS = {"GOOGLE_CSE_API_KEY": "test-key", "GOOGLE_CSE_ID": "test-cx"}


def png_bytes(w: int = 400, h: int = 300, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 120, 200)).save(buf, fmt)
    return buf.getvalue()


def api_response(n: int = 2) -> bytes:
    return json.dumps(
        {
            "items": [
                {
                    "title": f"Result {i}",
                    "link": f"https://cdn.example.com/img{i}.png",
                    "mime": "image/png",
                    "displayLink": "example.com",
                    "image": {
                        "contextLink": f"https://example.com/page{i}",
                        "width": 800,
                        "height": 600,
                    },
                }
                for i in range(n)
            ]
        }
    ).encode()


class FakeResponse(io.BytesIO):
    """夠用的 urlopen 回應替身（支援 with 與 .headers）。"""

    def __init__(self, payload: bytes, headers: dict | None = None):
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class SearchTests(TestCase):
    def test_missing_credentials_raises_config_error(self):
        with mock.patch.dict("os.environ", {"GOOGLE_CSE_API_KEY": "", "GOOGLE_CSE_ID": ""}, clear=False):
            with self.assertRaises(gi.ConfigError):
                gi.credentials()

    @mock.patch.dict("os.environ", CREDS)
    def test_search_parses_hits(self):
        with mock.patch.object(gi, "urlopen", return_value=FakeResponse(api_response(2))):
            hits = gi.search("ball screw")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].image_url, "https://cdn.example.com/img0.png")
        self.assertEqual(hits[0].page_url, "https://example.com/page0")
        self.assertEqual((hits[0].width, hits[0].height), (800, 600))

    @mock.patch.dict("os.environ", CREDS)
    def test_search_sends_image_search_params(self):
        with mock.patch.object(gi, "urlopen", return_value=FakeResponse(api_response(1))) as m:
            gi.search("ball screw", count=3, rights="cc_publicdomain")
        url = m.call_args[0][0].full_url
        for expected in ("searchType=image", "num=3", "rights=cc_publicdomain", "q=ball+screw"):
            self.assertIn(expected, url)

    @mock.patch.dict("os.environ", CREDS)
    def test_quota_exceeded_maps_to_quota_error(self):
        err = HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b'{"error":"quotaExceeded"}'))
        with mock.patch.object(gi, "urlopen", side_effect=err):
            with self.assertRaises(gi.QuotaError):
                gi.search("x")


class DownloadTests(TestCase):
    def hit(self, url="https://cdn.example.com/a.png"):
        return gi.Hit("t", url, "https://example.com/p", "example.com", "image/png", 800, 600)

    def test_download_accepts_real_image(self):
        with mock.patch.object(gi, "urlopen", return_value=FakeResponse(png_bytes())):
            raw, ext = gi.download(self.hit())
        self.assertEqual(ext, ".png")
        self.assertGreater(len(raw), 100)

    def test_download_rejects_non_image(self):
        with mock.patch.object(gi, "urlopen", return_value=FakeResponse(b"<html>404</html>")):
            with self.assertRaises(Exception):
                gi.download(self.hit())

    def test_download_rejects_tiny_image(self):
        with mock.patch.object(gi, "urlopen", return_value=FakeResponse(png_bytes(50, 40))):
            with self.assertRaisesMessage(ValueError, "解析度太低"):
                gi.download(self.hit())

    def test_download_rejects_oversized_by_content_length(self):
        resp = FakeResponse(png_bytes(), headers={"Content-Length": str(gi.MAX_BYTES + 1)})
        with mock.patch.object(gi, "urlopen", return_value=resp):
            with self.assertRaisesMessage(ValueError, "檔案過大"):
                gi.download(self.hit())

    @mock.patch.dict("os.environ", CREDS)
    def test_best_falls_through_to_next_candidate(self):
        """第一個候選壞掉時要自動換下一個，而不是整筆放棄。"""
        responses = [
            FakeResponse(api_response(2)),   # search
            FakeResponse(b"not an image"),   # 第一個候選：壞的
            FakeResponse(png_bytes()),       # 第二個候選：好的
        ]
        with mock.patch.object(gi, "urlopen", side_effect=responses):
            hit, raw, ext = gi.best("ball screw", count=2, delay=0)
        self.assertEqual(hit.image_url, "https://cdn.example.com/img1.png")
        self.assertEqual(ext, ".png")


class CommandTests(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media, True)
        # 自備關鍵字對照檔，測試才不會綁死 seed 內容
        self.queries = self.media / "queries.json"
        self.queries.write_text(
            json.dumps({"components": {"ball-screw": "ball screw"}, "cards": {}}),
            encoding="utf-8",
        )
        eq = Equipment.objects.create(slug="aoi", name="AOI", summary="s", scene_key="aoi")
        mod = Module.objects.create(equipment=eq, slug="m", name="模組", domain="mechanical")
        self.comp = Component.objects.create(
            module=mod, slug="ball-screw", name="滾珠螺桿", function="f", install_location="l"
        )

    def run_cmd(self, **kw):
        out = io.StringIO()
        kw.setdefault("queries", str(self.queries))
        call_command("fetch_google_photos", stdout=out, stderr=io.StringIO(), **kw)
        return out.getvalue()

    def test_dry_run_does_not_call_api(self):
        with mock.patch.object(gi, "urlopen", side_effect=AssertionError("不該連外")):
            out = self.run_cmd(dry_run=True, target="components", slug="ball-screw")
        self.assertIn("components/aoi/ball-screw.jpg", out)

    @mock.patch.dict("os.environ", CREDS)
    def test_saves_to_expected_path_and_records_provenance(self):
        responses = [FakeResponse(api_response(1)), FakeResponse(png_bytes())]
        with override_settings(MEDIA_ROOT=self.media):
            with mock.patch.object(gi, "urlopen", side_effect=responses):
                self.run_cmd(target="components", slug="ball-screw", delay=0)

        self.comp.refresh_from_db()
        # 副檔名要跟著實際格式走（API 說 png，就存 .png）
        self.assertEqual(self.comp.photo.name, "components/aoi/ball-screw.png")
        self.assertTrue((self.media / "components/aoi/ball-screw.png").exists())
        self.assertIn("example.com", self.comp.photo_credit)
        self.assertEqual(self.comp.photo_source_url, "https://example.com/page0")

    @mock.patch.dict("os.environ", CREDS)
    def test_skips_items_that_already_have_photo(self):
        self.comp.photo = "components/aoi/ball-screw.jpg"
        self.comp.save(update_fields=["photo"])
        with mock.patch.object(gi, "urlopen", side_effect=AssertionError("不該連外")):
            out = self.run_cmd(target="components", slug="ball-screw")
        self.assertIn("沒有要處理的項目", out)

    @mock.patch.dict("os.environ", CREDS)
    def test_limit_then_resume_picks_up_where_it_left_off(self):
        """分天抓圖的核心行為：--limit 抓一批，隔天再跑要接著抓沒抓過的，不重覆也不漏。"""
        mod = self.comp.module
        for slug in ("linear-guide", "coupling"):
            Component.objects.create(
                module=mod, slug=slug, name=slug, function="f", install_location="l"
            )
        self.queries.write_text(
            json.dumps({
                "components": {s: s for s in ("ball-screw", "linear-guide", "coupling")},
                "cards": {},
            }),
            encoding="utf-8",
        )

        def run(limit):
            responses = []
            for _ in range(limit):
                responses += [FakeResponse(api_response(1)), FakeResponse(png_bytes())]
            with mock.patch.object(gi, "urlopen", side_effect=responses):
                self.run_cmd(target="components", limit=limit, delay=0)

        with override_settings(MEDIA_ROOT=self.media):
            run(2)   # 第一天
            done_day1 = set(
                Component.objects.exclude(photo="").values_list("slug", flat=True)
            )
            self.assertEqual(len(done_day1), 2)

            run(2)   # 第二天：只剩 1 筆沒抓，不該重抓前一天的
            done_day2 = set(
                Component.objects.exclude(photo="").values_list("slug", flat=True)
            )

        self.assertEqual(done_day2, {"ball-screw", "linear-guide", "coupling"})
        self.assertTrue(done_day1 < done_day2, "第二天應該只補沒抓過的")

    @mock.patch.dict("os.environ", CREDS)
    def test_quota_error_stops_cleanly(self):
        err = HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b'{"error":"quotaExceeded"}'))
        with override_settings(MEDIA_ROOT=self.media):
            with mock.patch.object(gi, "urlopen", side_effect=err):
                out = self.run_cmd(target="components", slug="ball-screw", delay=0)
        self.assertIn("完成：0 張下載", out)
        self.comp.refresh_from_db()
        self.assertFalse(self.comp.photo)
