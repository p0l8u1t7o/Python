"""能源管理報表：數字對得上區間表、警報統計照時段分佈、PDF／Word 都產得出來。"""

from __future__ import annotations

import datetime as dt
from urllib.parse import quote

from django.utils import timezone

from apps.alerts.models import Alert, AlertStatus, Severity
from apps.ems.models import EnergyInterval
from tests import factories
from tests.test_api import API, ApiTestCase


class EnergyReportTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.plant = factories.site(self.org, code="plant", timezone_name="Asia/Taipei")
        self.workshop = factories.site(self.org, code="ws", parent=self.plant, timezone_name="Asia/Taipei")
        self.device = factories.device(self.org, "RPT-1", site_obj=self.workshop)
        self.end = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.start = self.end - dt.timedelta(days=2)
        t = self.start
        while t < self.end:
            EnergyInterval.objects.create(
                organization=self.org, site=self.workshop, interval_start=t, interval_seconds=3600,
                grid_import_kwh=10, grid_export_kwh=2, pv_kwh=6, load_kwh=14,
                battery_charge_kwh=1, battery_discharge_kwh=0.9, energy_cost=30, export_revenue=4,
                estimated_savings=5,
            )
            t += dt.timedelta(hours=1)
        for hour in (9, 9, 9, 15):
            started = self.start + dt.timedelta(hours=hour)
            Alert.objects.create(
                organization=self.org, device=self.device, severity=Severity.MAJOR,
                status=AlertStatus.RESOLVED, title="SOC low", code="SOC_LOW", fingerprint=f"fp-{hour}-{started.timestamp()}",
                started_at=started, last_triggered_at=started, resolved_at=started + dt.timedelta(minutes=30),
            )

    def query(self, **params) -> dict:
        params.setdefault("start", self.start.isoformat())
        params.setdefault("end", self.end.isoformat())
        qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        response = self.get(f"{API}/ems/reports/energy?{qs}", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_totals_sites_daily_and_alerts(self) -> None:
        body = self.query()
        self.assertEqual(body["totals"]["load_kwh"], 14 * 48)
        self.assertEqual(body["totals"]["grid_import_kwh"], 10 * 48)
        self.assertEqual(body["totals"]["energy_cost"], 30 * 48)
        rows = {row["site_name"]: row for row in body["sites"]}
        self.assertEqual(rows[self.workshop.name]["load_kwh"], 14 * 48)
        self.assertEqual(rows[self.plant.name]["load_kwh"], 0)
        self.assertGreaterEqual(len(body["daily"]), 2)
        self.assertEqual(len(body["hourly_load"]), 24)
        alerts = body["alerts"]
        self.assertEqual(alerts["total"], 4)
        self.assertEqual(alerts["by_severity"]["major"], 4)
        self.assertEqual(alerts["resolved"], 4)
        self.assertEqual(sum(alerts["by_hour"]), 4)
        self.assertEqual(max(alerts["by_hour"]), 3, "three alerts share one local hour")
        self.assertEqual(alerts["median_minutes_to_resolve"], 30)
        self.assertEqual(alerts["top_titles"][0]["count"], 4)
        self.assertTrue(any("警報" in i["text"] for i in body["insights"]))

    def test_site_scope_and_descendants(self) -> None:
        whole = self.query(site_id=self.plant.id)
        self.assertEqual(whole["site_count"], 2)
        self.assertEqual(whole["totals"]["load_kwh"], 14 * 48)
        own = self.query(site_id=self.plant.id, include_descendants="false")
        self.assertEqual(own["site_count"], 1)
        self.assertEqual(own["totals"]["load_kwh"], 0)

    def test_export_pdf_and_docx(self) -> None:
        qs = f"start={quote(self.start.isoformat())}&end={quote(self.end.isoformat())}"
        pdf = self.get(f"{API}/ems/reports/energy/export?format=pdf&{qs}", self.token)
        self.assertEqual(pdf.status_code, 200, pdf.content[:200])
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertIn("attachment", pdf["Content-Disposition"])
        docx = self.get(f"{API}/ems/reports/energy/export?format=docx&{qs}", self.token)
        self.assertEqual(docx.status_code, 200)
        self.assertTrue(docx.content.startswith(b"PK"))
        bad = self.get(f"{API}/ems/reports/energy/export?format=xls&{qs}", self.token)
        self.assertEqual(bad.status_code, 422)

    def test_viewer_can_read_and_window_is_capped(self) -> None:
        viewer = self.login("view@acme-demo.com")
        self.assertEqual(self.get(f"{API}/ems/reports/energy", viewer).status_code, 200)
        far = quote((self.end - dt.timedelta(days=500)).isoformat())
        response = self.get(f"{API}/ems/reports/energy?start={far}&end={quote(self.end.isoformat())}", viewer)
        self.assertEqual(response.status_code, 422)
