"""維運：每小時彙總（永久保留）、保留策略、備份還原、purge、doctor。"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.core.models import AuditLog
from apps.vision import archive
from apps.vision.models import Flow, FlowRun, FlowRunHourly, ImageSource
from apps.vision.runner import persister, runner

VISION = settings.VISION


def graph(source_id: int) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
        ],
        "edges": [],
    }


class RollupTests(TestCase):
    """彙總是純計算：明細清掉之後趨勢還在。"""

    def setUp(self):
        self.flow = Flow.objects.create(name="rolled", graph={})

    def _rows(self, when, statuses, station="ST01", recipe=""):
        return [
            FlowRun(flow=self.flow, flow_version=1, status=s, station_id=station, recipe=recipe,
                    duration_ms=10 * (i + 1), started_at=when, finished_at=when)
            for i, s in enumerate(statuses)
        ]

    def test_batch_is_folded_into_one_hourly_row(self):
        when = timezone.now().replace(minute=17, second=3, microsecond=0)
        persister._rollup(self._rows(when, ["ok", "ok", "ng", "failed"]))  # noqa: SLF001
        row = FlowRunHourly.objects.get(flow=self.flow)
        self.assertEqual((row.ok, row.ng, row.failed, row.total), (2, 1, 1, 4))
        self.assertEqual(row.hour, when.replace(minute=0, second=0, microsecond=0))
        self.assertEqual(row.max_ms, 40)
        self.assertEqual(row.total_ms, 100)

    def test_second_batch_accumulates(self):
        when = timezone.now().replace(minute=5, second=0, microsecond=0)
        persister._rollup(self._rows(when, ["ok"]))       # noqa: SLF001
        persister._rollup(self._rows(when, ["ng", "ok"]))  # noqa: SLF001
        row = FlowRunHourly.objects.get(flow=self.flow)
        self.assertEqual((row.ok, row.ng, row.total), (2, 1, 3))
        self.assertEqual(FlowRunHourly.objects.count(), 1)

    def test_station_and_recipe_are_separate_rows(self):
        when = timezone.now().replace(minute=0, second=0, microsecond=0)
        persister._rollup(self._rows(when, ["ok"], station="ST01", recipe="A"))  # noqa: SLF001
        persister._rollup(self._rows(when, ["ok"], station="ST02", recipe="A"))  # noqa: SLF001
        persister._rollup(self._rows(when, ["ok"], station="ST01", recipe="B"))  # noqa: SLF001
        self.assertEqual(FlowRunHourly.objects.count(), 3)

    def test_stats_survives_detail_being_purged(self):
        when = timezone.now().replace(minute=30, second=0, microsecond=0)
        rows = self._rows(when, ["ok", "ok", "ng"])
        FlowRun.objects.bulk_create(rows)
        persister._rollup(rows)  # noqa: SLF001
        FlowRun.objects.all().delete()  # 明細過了保留期被清掉
        body = self.client.get(f"/api/vision/flows/{self.flow.id}/stats?hours=24").json()
        self.assertEqual(body["total"], 3, "明細清掉之後良率曲線就不見了，這正是彙總要解決的事")
        self.assertEqual(body["by_status"], {"ok": 2, "ng": 1})
        self.assertEqual(len(body["hourly"]), 1)
        self.assertGreater(body["avg_ms"], 0)


@override_settings(VISION={**VISION, "PERSIST_RUNS": True, "ARCHIVE_DIR": str(VISION["ASSET_DIR"].parent / "archive-ops")})
class RetentionTests(TransactionTestCase):
    def setUp(self):
        archive.clear()
        self.addCleanup(archive.clear)
        self.source = ImageSource.objects.create(name="s", kind="synthetic", config={"width": 32, "height": 32})
        self.flow = Flow.objects.create(name="kept", graph=graph(self.source.id))
        self.addCleanup(runner.forget, self.flow.id)

    def test_old_runs_and_their_images_go_together(self):
        old = timezone.now() - dt.timedelta(days=100)
        run = FlowRun.objects.create(flow=self.flow, flow_version=1, status="ng", duration_ms=5,
                                     started_at=old, finished_at=old, images={"r:n:image": "kept/x.jpg"})
        path = archive.root() / "kept" / "x.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpegdata")
        call_command("purge", "--runs", "30", "--audit", "0", stdout=io.StringIO())
        self.assertFalse(FlowRun.objects.filter(pk=run.pk).exists())
        self.assertFalse(path.exists(), "刪了執行紀錄卻留下影像檔就會養出孤兒")

    def test_dry_run_deletes_nothing(self):
        old = timezone.now() - dt.timedelta(days=100)
        FlowRun.objects.create(flow=self.flow, flow_version=1, status="ok", duration_ms=1, started_at=old, finished_at=old)
        AuditLog.objects.create(action="flow.update")
        call_command("purge", "--dry-run", stdout=io.StringIO())
        self.assertEqual(FlowRun.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), 1)


class BackupRestoreTests(TestCase):
    def test_round_trip(self):
        out = Path(settings.DATA_DIR) / "backups" / "test-backup.zip"
        out.unlink(missing_ok=True)
        Flow.objects.create(name="in-the-backup", graph={})
        call_command("backup", "--out", str(out), stdout=io.StringIO())
        self.assertTrue(out.exists())
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            self.assertIn("db.sqlite3", names)
            self.assertIn("manifest.json", names)
            manifest = json.loads(zf.read("manifest.json"))
            self.assertFalse(manifest["with_images"])
            self.assertIn("station_id", manifest)
        out.unlink(missing_ok=True)

    def test_restore_refuses_a_zip_that_is_not_a_backup(self):
        from django.core.management.base import CommandError

        bogus = Path(settings.DATA_DIR) / "not-a-backup.zip"
        with zipfile.ZipFile(bogus, "w") as zf:
            zf.writestr("hello.txt", "hi")
        with self.assertRaises(CommandError):
            call_command("restore", str(bogus), "--yes", stdout=io.StringIO())
        bogus.unlink(missing_ok=True)


class DoctorTests(TestCase):
    def test_doctor_reports_the_essentials(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as caught:  # 沒有管理員＝有問題，離開碼 1（監控腳本靠它）
            call_command("doctor", "--json", stdout=buf)
        self.assertEqual(caught.exception.code, 1)
        checks = {c["check"]: c for c in json.loads(buf.getvalue())}
        for expected in ("version", "database", "disk", "image archive", "history", "accounts"):
            self.assertIn(expected, checks)
        from apps.vision import __version__

        self.assertEqual(checks["version"]["detail"], __version__)
        self.assertEqual(checks["accounts"]["state"], "bad", "沒有管理員應該要被指出來")

    def test_doctor_is_quiet_when_everything_is_fine(self):
        from django.contrib.auth.models import User

        User.objects.create_user("admin", password="x", is_staff=True)
        buf = io.StringIO()
        call_command("doctor", "--json", stdout=buf)  # 不該拋 SystemExit
        checks = {c["check"]: c for c in json.loads(buf.getvalue())}
        self.assertEqual(checks["accounts"]["state"], "ok")
