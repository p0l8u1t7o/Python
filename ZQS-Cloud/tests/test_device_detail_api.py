"""Device detail, per-device energy, and moving a device between sites.

The first class is a regression guard. ``GET /devices/{id}`` used to serialise
the device to a dict and return that; Ninja then re-validated the dict against
the same schema, and every resolver-backed field - site, blueprint, category,
capabilities - fell back to its default, because the resolvers reach for
``obj.site`` and a dict has no attributes. The list endpoint was fine, so the
console showed a site in the table and a dash on the detail page.

The capability case is the one worth keeping: the defaults are all *true*, so
a meter's detail page claimed it could charge, discharge and export.
"""

from __future__ import annotations

import datetime as dt

from apps.devices.models import DeviceCategory
from apps.telemetry.models import TelemetrySample
from tests import factories
from tests.test_api import API, ApiTestCase


class DeviceDetailTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.site = factories.site(self.org, "plant", name="Taoyuan plant")
        self.blueprint = factories.blueprint(
            "acme-meter",
            org=self.org,
            name="Acme meter",
            category=DeviceCategory.METER,
            can_charge=False,
            can_discharge=False,
            can_export=False,
            is_dispatchable=False,
        )
        self.device = factories.device(
            self.org,
            "DETAIL-1",
            site_obj=self.site,
            device_type=self.blueprint,
            name="Main incomer",
        )

    def test_the_detail_response_carries_the_site_and_blueprint(self):
        token = self.login(self.admin.email)
        payload = self.get(f"{API}/devices/{self.device.id}", token).json()

        self.assertEqual(payload["site_name"], "Taoyuan plant")
        self.assertEqual(payload["site_id"], str(self.site.id))
        self.assertEqual(payload["device_type_name"], "Acme meter")
        self.assertEqual(payload["device_category"], "meter")

    def test_capabilities_are_the_real_ones_not_the_schema_defaults(self):
        """The defaults are permissive, so this failing looks like a meter
        that can export."""
        token = self.login(self.admin.email)
        payload = self.get(f"{API}/devices/{self.device.id}", token).json()
        self.assertEqual(
            payload["capabilities"],
            {
                "can_charge": False,
                "can_discharge": False,
                "can_export": False,
                "is_dispatchable": False,
            },
        )

    def test_the_detail_and_list_views_agree(self):
        token = self.login(self.admin.email)
        detail = self.get(f"{API}/devices/{self.device.id}", token).json()
        listing = self.get(f"{API}/devices", token).json()["items"][0]
        for field in ("site_name", "device_type_name", "device_category", "capabilities"):
            self.assertEqual(detail[field], listing[field], field)

    def test_the_alert_detail_view_keeps_its_device_fields(self):
        """Same double-serialisation bug, same fix, different router."""
        from apps.alerts.models import Alert, AlertStatus

        alert = Alert.objects.create(
            organization=self.org,
            device=self.device,
            severity="major",
            status=AlertStatus.FIRING,
            title="High import",
            started_at=self.device.created_at,
            last_triggered_at=self.device.created_at,
        )
        token = self.login(self.admin.email)
        payload = self.get(f"{API}/alerts/{alert.id}", token).json()
        self.assertEqual(payload["device_name"], "Main incomer")
        self.assertEqual(payload["device_external_id"], "DETAIL-1")
        self.assertEqual(payload["site_name"], "Taoyuan plant")


class DeviceSiteReassignmentTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.first = factories.site(self.org, "first", name="First")
        self.second = factories.site(self.org, "second", name="Second")
        self.device = factories.device(
            self.org, "MOVE-1", site_obj=self.first, name="Movable"
        )

    def test_a_device_can_be_moved_to_another_site(self):
        token = self.login(self.admin.email)
        response = self.patch(
            f"{API}/devices/{self.device.id}", token, {"site_id": str(self.second.id)}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["site_name"], "Second")

    def test_moving_records_both_sides_in_the_audit_log(self):
        """A bare site_id in the log says nothing a year later."""
        from apps.audit.models import AuditLog

        token = self.login(self.admin.email)
        self.patch(
            f"{API}/devices/{self.device.id}", token, {"site_id": str(self.second.id)}
        )
        entry = AuditLog.objects.filter(action="device.updated").latest("created_at")
        self.assertEqual(entry.payload["site"]["from"], "First")
        self.assertEqual(entry.payload["site"]["to"], "Second")

    def test_renaming_records_both_sides_too(self):
        from apps.audit.models import AuditLog

        token = self.login(self.admin.email)
        self.patch(f"{API}/devices/{self.device.id}", token, {"name": "Renamed"})
        entry = AuditLog.objects.filter(action="device.updated").latest("created_at")
        self.assertEqual(entry.payload["name"], {"from": "Movable", "to": "Renamed"})

    def test_a_device_can_be_detached_from_every_site(self):
        token = self.login(self.admin.email)
        response = self.patch(
            f"{API}/devices/{self.device.id}", token, {"site_id": None}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["site_id"])

    def test_a_site_holding_devices_cannot_be_deleted(self):
        token = self.login(self.admin.email)
        response = self.delete(f"{API}/sites/{self.first.id}", token)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "site_in_use")

    def test_the_site_can_be_deleted_once_its_devices_have_moved(self):
        token = self.login(self.admin.email)
        self.patch(
            f"{API}/devices/{self.device.id}", token, {"site_id": str(self.second.id)}
        )
        response = self.delete(f"{API}/sites/{self.first.id}", token)
        self.assertEqual(response.status_code, 200, response.content)

    def test_a_viewer_cannot_rename_a_device(self):
        token = self.login(self.viewer.email)
        response = self.patch(
            f"{API}/devices/{self.device.id}", token, {"name": "Nope"}
        )
        self.assertEqual(response.status_code, 403, response.content)


class DeviceEnergyTests(ApiTestCase):
    """Per-device energy: counters are differenced, gauges are integrated."""

    def setUp(self) -> None:
        super().setUp()
        self.site = factories.site(self.org, "hq")
        self.device = factories.device(self.org, "ENERGY-1", site_obj=self.site)
        self.start = self.device.created_at.replace(
            minute=0, second=0, microsecond=0
        ) - dt.timedelta(hours=2)

    def _samples(self, metric_key, values, step_minutes=15):
        TelemetrySample.objects.bulk_create(
            TelemetrySample(
                organization=self.org,
                device=self.device,
                metric_key=metric_key,
                ts=self.start + dt.timedelta(minutes=index * step_minutes),
                value=value,
            )
            for index, value in enumerate(values)
        )

    def _query(self, **params):
        # urlencode, not f-string interpolation: an ISO timestamp ends in
        # "+00:00", and a raw + in a query string decodes as a space.
        from urllib.parse import urlencode

        token = self.login(self.admin.email)
        query = urlencode(
            {
                "start": self.start.isoformat(),
                "end": (self.start + dt.timedelta(hours=2)).isoformat(),
                **params,
            }
        )
        response = self.get(f"{API}/devices/{self.device.id}/energy?{query}", token)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_a_counter_is_differenced(self):
        from apps.telemetry.models import Metric, MetricKind

        Metric.objects.create(
            organization=self.org,
            key="load_energy_kwh",
            display_name="Load energy",
            unit="kWh",
            kind=MetricKind.COUNTER,
        )
        self._samples("load_energy_kwh", [1000.0, 1010.0, 1025.0, 1040.0])
        payload = self._query(metric_key="load_energy_kwh")
        self.assertEqual(payload["basis"], "counter")
        self.assertAlmostEqual(payload["kwh"], 40.0)

    def test_a_counter_that_went_backwards_reports_unknown_not_zero(self):
        """A quietly short monthly total is worse than an admitted gap."""
        from apps.telemetry.models import Metric, MetricKind

        Metric.objects.create(
            organization=self.org,
            key="load_energy_kwh",
            display_name="Load energy",
            unit="kWh",
            kind=MetricKind.COUNTER,
        )
        self._samples("load_energy_kwh", [1000.0, 1010.0, 5.0, 12.0])
        payload = self._query(metric_key="load_energy_kwh")
        self.assertIsNone(payload["kwh"])
        self.assertTrue(payload["counter_reset"])

    def test_a_power_gauge_is_integrated_and_carries_its_coverage(self):
        self._samples("active_power_kw", [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
        payload = self._query(metric_key="active_power_kw")
        self.assertEqual(payload["basis"], "integrated")
        self.assertAlmostEqual(payload["kwh"], 20.0, places=3)
        self.assertGreater(payload["coverage"], 0.9)

    def test_a_device_that_has_reported_nothing_says_so(self):
        payload = self._query()
        self.assertIsNone(payload["kwh"])
        self.assertEqual(payload["basis"], "unknown")
        self.assertEqual(payload["available_metrics"], [])

    def test_a_viewer_may_read_energy(self):
        self._samples("active_power_kw", [5.0, 5.0, 5.0])
        token = self.login(self.viewer.email)
        response = self.get(f"{API}/devices/{self.device.id}/energy", token)
        self.assertEqual(response.status_code, 200, response.content)
