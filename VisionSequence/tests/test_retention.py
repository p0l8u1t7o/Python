"""資料保留：設定、分批刪除、引擎忙就讓路、維護視窗、備份份數、API。"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import uuid
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AuthToken
from apps.core.models import AuditLog
from apps.vision import retention
from apps.vision.models import Flow, FlowRun, MeasurementLog, RetentionSettings

VISION = {**__import__("django.conf", fromlist=["settings"]).settings.VISION}


def _run(flow: Flow, *, days_ago: float, status: str = "ok") -> FlowRun:
    when = timezone.now() - dt.timedelta(days=days_ago)
    row = FlowRun.objects.create(id=uuid.uuid4(), flow=flow, flow_version=1, status=status, trigger="test",
                                 station_id="ST01", recipe="", duration_ms=1.0, nodes={}, outputs={}, images={},
                                 error="", started_at=when, finished_at=when)
    FlowRun.objects.filter(pk=row.pk).update(started_at=when)  # auto_now_add 會蓋掉
    return row


class RetentionSettingsTests(TestCase):
    def setUp(self):
        retention.invalidate()
        self.addCleanup(retention.invalidate)

    def test_defaults_are_one_year_and_row_wins(self):
        cfg = retention.effective()
        self.assertEqual(cfg["run_days"], 365)
        self.assertEqual(cfg["audit_days"], 365)
        self.assertEqual(cfg["measurement_days"], 365)
        self.assertTrue(cfg["enabled"])
        retention.save({"run_days": 30, "vacuum": False})
        self.assertEqual(retention.effective()["run_days"], 30)
        self.assertFalse(retention.effective()["vacuum"])
        self.assertEqual(RetentionSettings.objects.count(), 1)

    def test_values_are_clamped_and_unknown_keys_ignored(self):
        saved = retention.save({"run_days": -5, "window_hour": 99, "archive_max_gb": -1, "backup_keep": 99999, "nonsense": 1})
        self.assertEqual(saved["run_days"], 0)  # 0 = 永久保留
        self.assertEqual(saved["window_hour"], 23)
        self.assertEqual(saved["archive_max_gb"], 0.0)
        self.assertEqual(saved["backup_keep"], 1000)
        self.assertNotIn("nonsense", saved)


class SweepTests(TestCase):
    def setUp(self):
        retention.invalidate()
        self.addCleanup(retention.invalidate)
        self.flow = Flow.objects.create(name="retention", graph={"nodes": [], "edges": []})

    def test_sweep_deletes_past_the_keep_by_date_only(self):
        old = [_run(self.flow, days_ago=400) for _ in range(3)]
        fresh = _run(self.flow, days_ago=1)
        MeasurementLog.objects.create(flow=self.flow, run_id=uuid.uuid4(), name="d", value=1.0,
                                      ts=timezone.now() - dt.timedelta(days=400))
        MeasurementLog.objects.filter(name="d").update(ts=timezone.now() - dt.timedelta(days=400))
        AuditLog.objects.create(action="flow.update", actor_name="x")
        AuditLog.objects.filter(action="flow.update").update(at=timezone.now() - dt.timedelta(days=400))
        AuditLog.objects.create(action="flow.create", actor_name="x")

        result = retention.sweep(force=True)
        self.assertEqual(result["runs"], len(old))
        self.assertEqual(result["measurements"], 1)
        self.assertEqual(result["audit"], 1)
        self.assertEqual(list(FlowRun.objects.values_list("id", flat=True)), [fresh.id])
        self.assertEqual(MeasurementLog.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 1)
        row = RetentionSettings.objects.get(id=1)
        self.assertIsNotNone(row.last_sweep_at)
        self.assertEqual(row.last_result["runs"], len(old))

    def test_zero_days_keeps_everything(self):
        _run(self.flow, days_ago=5000)
        retention.save({"run_days": 0, "audit_days": 0, "measurement_days": 0})
        self.assertEqual(retention.sweep(force=True)["runs"], 0)
        self.assertEqual(FlowRun.objects.count(), 1)

    def test_disabled_does_nothing_unless_forced(self):
        _run(self.flow, days_ago=400)
        retention.save({"enabled": False})
        self.assertEqual(retention.sweep()["runs"], 0)
        self.assertEqual(FlowRun.objects.count(), 1)
        self.assertEqual(retention.sweep(force=True)["runs"], 1)

    def test_busy_engine_stops_the_sweep(self):
        for _ in range(3):
            _run(self.flow, days_ago=400)
        with mock.patch.object(retention, "busy", return_value=True):
            self.assertEqual(retention.sweep()["runs"], 0)
        self.assertEqual(FlowRun.objects.count(), 3)

    def test_deletes_in_batches(self):
        for _ in range(7):
            _run(self.flow, days_ago=400)
        with mock.patch.object(retention, "BATCH", 2):
            result = retention.sweep(force=True, budget=4)
        self.assertEqual(result["runs"], 4)  # budget 用完就停，剩下的下次再刪
        self.assertEqual(FlowRun.objects.count(), 3)

    def test_maybe_sweep_waits_for_the_interval(self):
        _run(self.flow, days_ago=400)
        retention._last_sweep = 0.0
        retention._idle_since = 0.0
        with mock.patch.object(retention, "busy", return_value=False):
            self.assertIsNotNone(retention.maybe_sweep())
            self.assertIsNone(retention.maybe_sweep())  # 間隔還沒到
        self.assertEqual(FlowRun.objects.count(), 0)

    def test_maybe_sweep_skips_a_busy_engine(self):
        retention._last_sweep = 0.0
        retention._idle_since = 0.0
        with mock.patch.object(retention, "busy", return_value=True):
            self.assertIsNone(retention.maybe_sweep())

    def test_window_only_admits_the_deep_sweep(self):
        hour = timezone.localtime().hour
        self.assertTrue(retention._in_window(hour))
        self.assertFalse(retention._in_window((hour + 1) % 24))


class BackgroundGateTests(TestCase):
    """背景整理只有 manage.py serve 會打開：測試與一次性 CLI 的持久化執行緒不該在背後刪資料。"""

    def setUp(self):
        retention.enable_background(False)
        self.addCleanup(retention.enable_background, False)

    def test_persister_housekeeping_honours_the_gate(self):
        from apps.vision.runner import persister

        with mock.patch.object(retention, "maybe_sweep") as swept:
            persister._housekeeping()
            swept.assert_not_called()
            retention.enable_background()
            persister._housekeeping()
            swept.assert_called_once()

    def test_serve_turns_it_on(self):
        import inspect

        from apps.vision.management.commands import serve

        source = inspect.getsource(serve)
        self.assertIn("retention.enable_background()", source)
        self.assertIn("persister.ensure()", source)


class BackupPruneTests(TestCase):
    def setUp(self):
        retention.invalidate()
        self.addCleanup(retention.invalidate)
        self.tmp = tempfile.mkdtemp(prefix="vs-backups-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _make(self, name: str, age_s: float) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(b"x" * 16)
        stamp = __import__("time").time() - age_s
        os.utime(path, (stamp, stamp))
        return path

    def test_keeps_the_newest_of_each_kind(self):
        os.makedirs(os.path.join(self.tmp, "backups"), exist_ok=True)
        zips = [self._make(os.path.join("backups", f"visionsequence-{i}.zip"), age_s=i * 60) for i in range(5)]
        copies = [self._make(f"vision.sqlite3.before-restore-{i}", age_s=i * 60) for i in range(4)]
        db = os.path.join(self.tmp, "vision.sqlite3")
        with open(db, "wb") as fh:
            fh.write(b"db")
        with override_settings(DATA_DIR=self.tmp, DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db}}):
            self.assertEqual(len(retention.backup_files()), 9)
            self.assertEqual(retention.purge_backups(2), 5)  # 兩種各留 2 份
            left = {os.path.basename(p) for p, _st in retention.backup_files()}
        self.assertEqual(left, {os.path.basename(zips[0]), os.path.basename(zips[1]),
                                os.path.basename(copies[0]), os.path.basename(copies[1])})

    def test_keep_zero_means_keep_everything(self):
        with override_settings(DATA_DIR=self.tmp):
            self.assertEqual(retention.purge_backups(0), 0)


class RetentionApiTests(TestCase):
    def setUp(self):
        retention.invalidate()
        self.addCleanup(retention.invalidate)

    def _admin(self) -> str:
        r = self.client.post("/api/auth/setup", data='{"username": "admin", "password": "Admin12345"}', content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        return r.json()["token"]

    def test_get_patch_and_sweep(self):
        token = self._admin()
        head = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        r = self.client.get("/api/vision/retention", **head)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["settings"]["run_days"], 365)
        self.assertIn("db_bytes", body["usage"])

        r = self.client.patch("/api/vision/retention", data='{"run_days": 90, "window_hour": 2}',
                              content_type="application/json", **head)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["settings"]["run_days"], 90)
        self.assertEqual(retention.effective()["window_hour"], 2)
        self.assertTrue(AuditLog.objects.filter(action="retention.update").exists())

        r = self.client.patch("/api/vision/retention", data='{"nope": 1}', content_type="application/json", **head)
        self.assertEqual(r.status_code, 422, r.content)

        r = self.client.post("/api/vision/retention/sweep", data="{}", content_type="application/json", **head)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("runs", r.json()["result"])
        self.assertTrue(AuditLog.objects.filter(action="retention.sweep").exists())

    def test_needs_an_administrator(self):
        self._admin()
        token = AuthToken.issue(__import__("django.contrib.auth", fromlist=["models"]).models.User.objects.create_user("op", password="x"))
        r = self.client.get("/api/vision/retention", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(self.client.get("/api/vision/retention").status_code, 401)
