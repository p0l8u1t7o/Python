"""Address lookup, and the promise that it is never load-bearing.

The whole feature is a convenience: every failure path has to end with the
operator typing the coordinates in. So most of what is worth pinning here is
what happens when it *does not* work - offline, rate limited, disabled, or
answering with nonsense.
"""

from __future__ import annotations

import json
import urllib.error
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.devices import geocoding
from tests.test_api import API, ApiTestCase


class _Response:
    """Minimal stand-in for what urlopen returns."""

    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


TAIPEI = [
    {"lat": "25.0339", "lon": "121.5645", "display_name": "Taipei 101, Taipei"},
    {"lat": "25.0400", "lon": "121.5100", "display_name": "Taipei Main Station"},
]


class GeocodingTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        # The module throttles to one call per second; without this every test
        # in the class would sit in a sleep.
        geocoding._last_call = 0.0

    def search(self, payload, **settings_overrides):
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", return_value=_Response(payload)
        ):
            return geocoding.search("Taipei 101", **settings_overrides)

    def test_a_match_becomes_coordinates(self):
        places = self.search(TAIPEI)
        self.assertEqual(len(places), 2)
        self.assertAlmostEqual(places[0].latitude, 25.0339)
        self.assertAlmostEqual(places[0].longitude, 121.5645)

    def test_an_unreachable_service_returns_nothing_rather_than_raising(self):
        """Site creation must not depend on an outbound connection."""
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("offline")
        ):
            self.assertEqual(geocoding.search("Taipei 101"), [])

    def test_a_timeout_returns_nothing(self):
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", side_effect=TimeoutError
        ):
            self.assertEqual(geocoding.search("Taipei 101"), [])

    def test_a_nonsense_response_is_skipped_entry_by_entry(self):
        """One malformed row must not discard the rows that parsed."""
        places = self.search(
            [{"lat": "not-a-number", "lon": "1"}, TAIPEI[0], {"nothing": True}]
        )
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].display_name, "Taipei 101, Taipei")

    def test_a_response_that_is_not_a_list_returns_nothing(self):
        self.assertEqual(self.search({"error": "rate limited"}), [])

    def test_a_short_query_never_leaves_the_process(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.assertEqual(geocoding.search("a"), [])
            urlopen.assert_not_called()

    def test_disabled_never_leaves_the_process(self):
        with self.settings(GEOCODING={**geocoding.settings.GEOCODING, "ENABLED": False}):
            with mock.patch("urllib.request.urlopen") as urlopen:
                self.assertEqual(geocoding.search("Taipei 101"), [])
                urlopen.assert_not_called()

    def test_results_are_cached(self):
        """The rate limit is the scarce resource, not the CPU."""
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", return_value=_Response(TAIPEI)
        ) as urlopen:
            geocoding.search("Taipei 101")
            geocoding.search("Taipei 101")
            self.assertEqual(urlopen.call_count, 1)

    def test_an_empty_result_is_cached_too(self):
        """A misspelled address does not become spellable by being asked
        about again."""
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", return_value=_Response([])
        ) as urlopen:
            geocoding.search("zzzzzz nowhere")
            geocoding.search("zzzzzz nowhere")
            self.assertEqual(urlopen.call_count, 1)

    def test_the_request_identifies_itself(self):
        """Nominatim's usage policy requires it, and blocks generic agents."""
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", return_value=_Response(TAIPEI)
        ) as urlopen:
            geocoding.search("Taipei 101")
        request = urlopen.call_args[0][0]
        self.assertIn("ZQS", request.get_header("User-agent"))


class GeocodeEndpointTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        geocoding._last_call = 0.0
        self.token = self.login(self.admin.email)

    def test_the_endpoint_returns_candidates(self):
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", return_value=_Response(TAIPEI)
        ):
            response = self.get(f"{API}/sites/geocode?q=Taipei+101", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["available"])
        self.assertEqual(len(body["results"]), 2)

    def test_a_failure_is_an_empty_list_not_an_error(self):
        """The console's fallback is identical for every failure mode, so the
        API must not make it distinguish them."""
        with mock.patch.object(geocoding, "_throttle"), mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("offline")
        ):
            response = self.get(f"{API}/sites/geocode?q=Taipei+101", self.token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_it_reports_when_lookup_is_switched_off(self):
        with self.settings(GEOCODING={**geocoding.settings.GEOCODING, "ENABLED": False}):
            body = self.get(f"{API}/sites/geocode?q=Taipei+101", self.token).json()
        self.assertFalse(body["available"])

    def test_it_needs_authentication(self):
        response = self.get(f"{API}/sites/geocode?q=Taipei+101")
        self.assertEqual(response.status_code, 401)
