"""The fleet-wide event log, and the scope rules it must not leak past.

The per-device tab answers "what happened to this unit". This answers the
question an operator starts with - "something went wrong around four, where?" -
which needs every device at once, and therefore needs the site scope to hold
across all of them.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlencode

from apps.core.timeutils import now
from apps.devices.models import DeviceEvent, EventLevel
from tests import factories
from tests.test_api import API, ApiTestCase


class EventLogTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.taipei = factories.site(self.org, "Taipei")
        self.hsinchu = factories.site(self.org, "Hsinchu")
        self.bess = factories.device(self.org, "EV-BESS", site_obj=self.taipei)
        self.meter = factories.device(self.org, "EV-METER", site_obj=self.hsinchu)
        self.token = self.login(self.admin.email)

        moment = now()
        self.events = [
            DeviceEvent.objects.create(
                organization=self.org,
                device=self.bess,
                ts=moment - dt.timedelta(minutes=index),
                level=level,
                code=code,
                message=message,
            )
            for index, (level, code, message) in enumerate(
                [
                    (EventLevel.WARNING, "E0231", "Cooling fan speed low"),
                    (EventLevel.ERROR, "E0500", "Insulation resistance low"),
                    (EventLevel.INFO, "E0100", "Firmware updated"),
                ]
            )
        ]
        DeviceEvent.objects.create(
            organization=self.org,
            device=self.meter,
            ts=moment - dt.timedelta(minutes=5),
            level=EventLevel.CRITICAL,
            code="M0001",
            message="Phase loss",
        )

    def fetch(self, token=None, **params):
        query = urlencode({k: v for k, v in params.items() if v is not None})
        path = f"{API}/events" + (f"?{query}" if query else "")
        return self.get(path, token or self.token).json()

    # ---- the basics ------------------------------------------------------
    def test_every_device_appears_in_one_list(self):
        body = self.fetch()
        codes = {row["code"] for row in body["items"]}
        self.assertEqual(codes, {"E0231", "E0500", "E0100", "M0001"})

    def test_newest_first(self):
        stamps = [row["ts"] for row in self.fetch()["items"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_each_row_names_its_device_and_site(self):
        """Without these the list is a wall of messages with no "where"."""
        row = next(r for r in self.fetch()["items"] if r["code"] == "M0001")
        self.assertEqual(row["device_external_id"], "EV-METER")
        self.assertEqual(row["site_name"], self.hsinchu.name)

    # ---- filters ---------------------------------------------------------
    def test_filter_by_level(self):
        body = self.fetch(level="error")
        self.assertEqual([r["code"] for r in body["items"]], ["E0500"])

    def test_filter_by_code_ignores_case(self):
        body = self.fetch(code="e0231")
        self.assertEqual([r["code"] for r in body["items"]], ["E0231"])

    def test_filter_by_site(self):
        body = self.fetch(site_id=str(self.hsinchu.id))
        self.assertEqual([r["code"] for r in body["items"]], ["M0001"])

    def test_search_covers_message_and_code(self):
        """Operators remember a phrase, not an enum."""
        self.assertEqual(
            [r["code"] for r in self.fetch(search="insulation")["items"]], ["E0500"]
        )
        self.assertEqual(
            [r["code"] for r in self.fetch(search="M000")["items"]], ["M0001"]
        )

    def test_the_window_excludes_older_events(self):
        DeviceEvent.objects.create(
            organization=self.org,
            device=self.bess,
            ts=now() - dt.timedelta(days=30),
            level=EventLevel.INFO,
            code="ANCIENT",
            message="Long ago",
        )
        codes = {row["code"] for row in self.fetch()["items"]}
        self.assertNotIn("ANCIENT", codes)

    # ---- codes -----------------------------------------------------------
    def test_codes_come_from_what_actually_arrived(self):
        """The codes belong to the device vendor, so a shipped list would be
        wrong for somebody."""
        body = self.get(f"{API}/events/codes", self.token).json()
        counts = {row["code"]: row["count"] for row in body}
        self.assertEqual(counts, {"E0231": 1, "E0500": 1, "E0100": 1, "M0001": 1})

    # ---- scope -----------------------------------------------------------
    def test_a_member_scoped_to_one_site_sees_only_its_events(self):
        from apps.accounts.models import Role

        account, membership = factories.member(
            self.org, Role.VIEWER, email="scoped@acme-demo.com"
        )
        membership.sites.set([self.taipei])
        token = self.login(account.email)

        codes = {row["code"] for row in self.fetch(token=token)["items"]}
        self.assertEqual(codes, {"E0231", "E0500", "E0100"})
        self.assertNotIn("M0001", codes)

    def test_another_tenants_events_are_invisible(self):
        other = self.other_org
        stranger = factories.device(other, "RIVAL-1")
        DeviceEvent.objects.create(
            organization=other,
            device=stranger,
            ts=now(),
            level=EventLevel.CRITICAL,
            code="SECRET",
            message="Not yours",
        )
        codes = {row["code"] for row in self.fetch()["items"]}
        self.assertNotIn("SECRET", codes)


class WindowBoundaryTests(ApiTestCase):
    """An event written in the same clock tick as the request must be visible.

    With an exclusive bound of exactly ``now()`` it was not, and the tick is
    not small: Windows resolves to roughly 15 ms, so the newest event routinely
    vanished from a default window on the way in. Every time-window endpoint
    shares this code path, so the audit log had the same hole.
    """

    def setUp(self) -> None:
        super().setUp()
        self.device = factories.device(self.org, "EDGE-1")
        self.token = self.login(self.admin.email)

    def test_an_event_created_right_now_is_listed(self):
        DeviceEvent.objects.create(
            organization=self.org,
            device=self.device,
            ts=now(),
            level=EventLevel.INFO,
            code="RIGHT-NOW",
            message="Same tick as the request",
        )
        body = self.get(f"{API}/events", self.token).json()
        self.assertIn("RIGHT-NOW", {row["code"] for row in body["items"]})

    def test_an_explicit_window_stays_half_open(self):
        """Explicit windows still tile: the grace applies only to a default."""

        edge = now()
        DeviceEvent.objects.create(
            organization=self.org,
            device=self.device,
            ts=edge,
            level=EventLevel.INFO,
            code="ON-THE-EDGE",
            message="Exactly at the boundary",
        )
        query = urlencode(
            {
                "start": (edge - dt.timedelta(hours=1)).isoformat(),
                "end": edge.isoformat(),
            }
        )
        body = self.get(f"{API}/events?{query}", self.token).json()
        self.assertNotIn("ON-THE-EDGE", {row["code"] for row in body["items"]})
