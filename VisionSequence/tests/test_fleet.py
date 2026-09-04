"""多站台唯讀看板：摘要端點、輪詢、離線時保留最後已知數字並標記多舊。"""

from __future__ import annotations

import json
import time
from unittest import mock
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AuthToken, UserPref
from apps.vision import fleet
from apps.vision.models import Flow, FlowRun, FlowRunHourly, Station
from apps.vision.runner import persister

VISION = settings.VISION


@override_settings(VISION={**VISION, "PERSIST_RUNS": False, "STATION_ID": "ST07"})
class SummaryTests(TestCase):
    """站台回報給看板的那一份摘要（本站總覽也用同一份）。"""

    def setUp(self):
        self.flow = Flow.objects.create(name="line-a", graph={})
        self.token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}),
                                      content_type="application/json").json()["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def _rollup(self, ok=0, ng=0, failed=0):
        when = timezone.now().replace(minute=0, second=0, microsecond=0)
        rows = [FlowRun(flow=self.flow, flow_version=1, status=s, duration_ms=10, started_at=when, finished_at=when)
                for s in ["ok"] * ok + ["ng"] * ng + ["failed"] * failed]
        persister._rollup(rows)  # noqa: SLF001

    def test_summary_reports_yield_from_the_rollup(self):
        self._rollup(ok=8, ng=2)
        body = self.client.get("/api/vision/summary", **self.auth).json()
        self.assertEqual(body["station_id"], "ST07")
        self.assertTrue(body["version"])
        self.assertEqual(body["totals"], {"total": 10, "ok": 8, "ng": 2, "failed": 0, "yield": 80.0})
        self.assertEqual(body["flows"][0]["name"], "line-a")
        self.assertEqual(body["flows"][0]["yield"], 80.0)

    def test_summary_is_fine_with_no_runs(self):
        body = self.client.get("/api/vision/summary", **self.auth).json()
        self.assertEqual(body["totals"]["total"], 0)
        self.assertIsNone(body["totals"]["yield"])
        self.assertEqual(body["flows"][0]["total"], 0)

    def test_summary_needs_a_login(self):
        User.objects.create_user("someone", password="x")
        self.assertEqual(self.client.get("/api/vision/summary").status_code, 401)


class FleetBoardTests(TestCase):
    def setUp(self):
        fleet._state.clear()  # noqa: SLF001
        self.addCleanup(fleet._state.clear)  # noqa: SLF001
        self.token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}),
                                      content_type="application/json").json()["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        self.station = Station.objects.create(name="Line A", base_url="http://10.0.0.5:8000", api_key="k")

    SUMMARY = {"station_id": "ST01", "version": "1.0.0", "locked": False,
               "totals": {"total": 100, "ok": 95, "ng": 5, "failed": 0, "yield": 95.0},
               "flows": [{"id": 1, "name": "f", "total": 100, "ok": 95, "ng": 5, "failed": 0, "yield": 95.0}]}

    def test_board_shows_a_reachable_station(self):
        with mock.patch.object(fleet, "fetch", return_value=self.SUMMARY):
            body = self.client.get("/api/vision/fleet", **self.auth).json()
        item = body["items"][0]
        self.assertTrue(item["online"])
        self.assertEqual((item["name"], item["station_id"], item["version"]), ("Line A", "ST01", "1.0.0"))
        self.assertEqual(item["totals"]["yield"], 95.0)
        self.assertEqual(body["totals"], {"total": 100, "ok": 95, "ng": 5, "failed": 0, "stations": 1, "online": 1, "yield": 95.0})

    def test_offline_keeps_the_last_numbers_but_marks_them_stale(self):
        with mock.patch.object(fleet, "fetch", return_value=self.SUMMARY):
            self.client.get("/api/vision/fleet", **self.auth)
        # 讓上一次的結果過期，看板才會再問一次（背景執行緒在測試裡不跑）
        fleet._state[self.station.id]["checked_at"] -= fleet.INTERVAL_S * 3  # noqa: SLF001
        with mock.patch.object(fleet, "fetch", side_effect=URLError("timed out")):
            body = self.client.get("/api/vision/fleet", **self.auth).json()
        item = body["items"][0]
        self.assertFalse(item["online"])
        self.assertTrue(item["stale"], "舊數字看起來像即時的，是產線看板最危險的事")
        self.assertEqual(item["totals"]["yield"], 95.0, "最後已知數字要留著")
        self.assertIn("unreachable", item["error"])
        self.assertIsNotNone(item["age_s"])
        self.assertEqual(body["totals"]["online"], 0)
        self.assertEqual(body["totals"]["total"], 0, "離線的站台不該被算進全廠合計")

    def test_a_bad_key_says_so(self):
        with mock.patch.object(fleet, "fetch", side_effect=HTTPError("u", 403, "Forbidden", {}, None)):
            body = self.client.get("/api/vision/fleet", **self.auth).json()
        self.assertEqual(body["items"][0]["error"], "API key rejected")

    def test_one_slow_station_does_not_hide_the_others(self):
        Station.objects.create(name="Line B", base_url="http://10.0.0.6:8000")

        def answer(base_url, api_key="", timeout=fleet.TIMEOUT_S):
            if "10.0.0.5" in base_url:
                raise URLError("timed out")
            return self.SUMMARY

        with mock.patch.object(fleet, "fetch", side_effect=answer):
            body = self.client.get("/api/vision/fleet", **self.auth).json()
        by_name = {i["name"]: i for i in body["items"]}
        self.assertFalse(by_name["Line A"]["online"])
        self.assertTrue(by_name["Line B"]["online"])
        self.assertEqual(body["totals"]["online"], 1)

    def test_disabled_stations_are_not_polled(self):
        Station.objects.filter(pk=self.station.pk).update(is_enabled=False)
        with mock.patch.object(fleet, "fetch") as fetched:
            body = self.client.get("/api/vision/fleet", **self.auth).json()
        fetched.assert_not_called()
        self.assertEqual(body["items"], [])

    def test_fetch_normalises_the_url_and_sends_the_key(self):
        captured = {}

        class _Response:
            def read(self):
                return json.dumps(FleetBoardTests.SUMMARY).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("X-api-key")
            return _Response()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            fleet.fetch("http://10.0.0.5:8000/", "secret")
        self.assertEqual(captured["url"], "http://10.0.0.5:8000/api/vision/summary")
        self.assertEqual(captured["key"], "secret")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            fleet.fetch("http://10.0.0.5:8000/api", "")
        self.assertEqual(captured["url"], "http://10.0.0.5:8000/api/vision/summary")

    def test_fetch_rejects_something_that_is_not_a_station(self):
        class _Response:
            def read(self):
                return b'{"hello": 1}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", lambda *a, **k: _Response()), self.assertRaises(ValueError):
            fleet.fetch("http://example.test", "")


class StationApiTests(TestCase):
    def setUp(self):
        self.token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}),
                                      content_type="application/json").json()["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_crud_and_key_is_never_returned(self):
        r = self.client.post("/api/vision/stations", data=json.dumps({"name": "Line A", "base_url": "http://10.0.0.5:8000", "api_key": "supersecret"}),
                             content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["api_key_hint"], "…cret")
        self.assertNotIn("api_key", r.json())
        sid = r.json()["id"]
        r = self.client.patch(f"/api/vision/stations/{sid}", data=json.dumps({"note": "east wing"}),
                              content_type="application/json", **self.auth)
        self.assertEqual(r.json()["note"], "east wing")
        self.assertEqual(self.client.get("/api/vision/stations", **self.auth).json()["items"][0]["name"], "Line A")
        self.assertEqual(self.client.delete(f"/api/vision/stations/{sid}", **self.auth).status_code, 204)

    def test_duplicate_name_and_missing_fields(self):
        body = {"name": "A", "base_url": "http://x"}
        self.client.post("/api/vision/stations", data=json.dumps(body), content_type="application/json", **self.auth)
        r = self.client.post("/api/vision/stations", data=json.dumps(body), content_type="application/json", **self.auth)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "station_name_taken"))
        r = self.client.post("/api/vision/stations", data=json.dumps({"name": " ", "base_url": ""}), content_type="application/json", **self.auth)
        self.assertEqual(r.json()["error"]["code"], "station_incomplete")

    def test_test_endpoint_reports_the_reason(self):
        with mock.patch.object(fleet, "fetch", side_effect=URLError("no route")):
            r = self.client.post("/api/vision/stations/test", data=json.dumps({"name": "x", "base_url": "http://nope"}),
                                 content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("unreachable", r.json()["error"])
        with mock.patch.object(fleet, "fetch", return_value=FleetBoardTests.SUMMARY):
            r = self.client.post("/api/vision/stations/test", data=json.dumps({"name": "x", "base_url": "http://ok"}),
                                 content_type="application/json", **self.auth)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["station_id"], "ST01")

    def test_only_administrators_may_change_the_list(self):
        eng = User.objects.create_user("eng", password="x")
        UserPref.objects.create(user=eng, role="engineer")
        h = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(eng)}"}
        self.assertEqual(self.client.get("/api/vision/stations", **h).status_code, 200)
        self.assertEqual(self.client.get("/api/vision/fleet", **h).status_code, 200)
        r = self.client.post("/api/vision/stations", data=json.dumps({"name": "n", "base_url": "http://x"}),
                             content_type="application/json", **h)
        self.assertEqual(r.status_code, 403)

    def test_polling_stops_when_nobody_watches(self):
        fleet._watch_until = 0.0  # noqa: SLF001
        self.assertFalse(fleet.watching())
        fleet.watch(60)
        self.assertTrue(fleet.watching())
        _ = time, FlowRunHourly
