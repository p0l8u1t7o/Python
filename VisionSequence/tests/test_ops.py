"""維運：每小時彙總（永久保留）、保留策略、備份還原、purge、doctor。"""

from __future__ import annotations

import datetime as dt
import io
import json
import shutil
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

    def test_backup_includes_env_and_plugins(self):
        import tempfile

        from django.test import override_settings

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        (home / ".env").write_text("VISION_STATION_ID=BK\n", encoding="utf-8")
        plugins = home / "plugins"
        (plugins / "mine" / "wheels").mkdir(parents=True)
        (plugins / "mine" / "__init__.py").write_text("ENABLED = False\n", encoding="utf-8")
        (plugins / "mine" / "wheels" / "x-1.0-py3-none-any.whl").write_bytes(b"whl")
        (plugins / "mine" / "__pycache__").mkdir()
        (plugins / "mine" / "__pycache__" / "a.pyc").write_bytes(b"pyc")
        (plugins / "solo.py").write_text("ENABLED = False\n", encoding="utf-8")
        downloads = Path(settings.DATA_DIR) / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        (downloads / "manifest.json").write_text('{"version": "9.9.9", "filename": "VisionSequenceCapture-9.9.9-win64.zip"}', encoding="utf-8")
        (downloads / "VisionSequenceCapture-9.9.9-win64.zip").write_bytes(b"zip")
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in (downloads / "manifest.json", downloads / "VisionSequenceCapture-9.9.9-win64.zip")])
        out = Path(settings.DATA_DIR) / "backups" / "test-env-backup.zip"
        with override_settings(VS_HOME=home, VISION={**settings.VISION, "PLUGIN_DIR": plugins}):
            call_command("backup", "--out", str(out), stdout=io.StringIO())
            with zipfile.ZipFile(out) as zf:
                names = set(zf.namelist())
                manifest = json.loads(zf.read("manifest.json"))
            self.assertIn("env/.env", names)
            self.assertIn("plugins/mine/__init__.py", names)
            self.assertIn("plugins/solo.py", names)
            self.assertNotIn("plugins/mine/wheels/x-1.0-py3-none-any.whl", names)  # 預設不帶 wheel
            self.assertNotIn("plugins/mine/__pycache__/a.pyc", names)
            self.assertIn("downloads/manifest.json", names)
            self.assertNotIn("downloads/VisionSequenceCapture-9.9.9-win64.zip", names)
            self.assertTrue(manifest["env_included"])
            self.assertEqual(manifest["plugin_files"], 2)
            self.assertEqual(manifest["capture_client_files"], 1)
            self.assertIn("version", manifest)
            out2 = out.with_name("test-env-backup-2.zip")
            call_command("backup", "--out", str(out2), "--no-env", "--with-wheels", "--with-client", stdout=io.StringIO())
            with zipfile.ZipFile(out2) as zf:
                names = set(zf.namelist())
            self.assertNotIn("env/.env", names)
            self.assertIn("plugins/mine/wheels/x-1.0-py3-none-any.whl", names)
            self.assertIn("downloads/VisionSequenceCapture-9.9.9-win64.zip", names)
            # 還原：外掛與擷取端進對應資料夾，.env 另存不覆蓋
            shutil.rmtree(plugins)
            (downloads / "manifest.json").unlink()
            (home / ".env").write_text("VISION_STATION_ID=CURRENT\n", encoding="utf-8")
            call_command("restore", str(out), "--yes", stdout=io.StringIO())  # 第一份（含 .env＝BK）
            self.assertTrue((plugins / "mine" / "__init__.py").exists())
            self.assertTrue((plugins / "solo.py").exists())
            self.assertTrue((downloads / "manifest.json").exists())
            self.assertEqual((home / ".env").read_text(encoding="utf-8"), "VISION_STATION_ID=CURRENT\n")
            self.assertEqual((home / ".env.from-backup").read_text(encoding="utf-8"), "VISION_STATION_ID=BK\n")
        out.unlink(missing_ok=True)
        out2.unlink(missing_ok=True)

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
        for expected in ("version", "python", "layout", "database", "disk", "image archive", "history", "accounts", "web interface", "plugins dir", "capture client build",
                         "settings: DEBUG", "settings: SECRET_KEY", "settings: ALLOWED_HOSTS", "settings: API key", "settings: TCP auth"):
            self.assertIn(expected, checks)
        self.assertTrue(any(c.startswith("HTTP port ") for c in checks), checks.keys())
        self.assertTrue(any(c.startswith("TCP commands port ") for c in checks), checks.keys())
        self.assertNotIn("API port 9000", checks)  # 以前把 TCP 埠標成 API
        from apps.vision import __version__

        self.assertEqual(checks["version"]["detail"], __version__)
        self.assertEqual(checks["accounts"]["state"], "bad", "沒有管理員應該要被指出來")

    def test_doctor_is_quiet_when_everything_is_fine(self):
        from django.contrib.auth.models import User

        import tempfile

        from django.test import override_settings

        User.objects.create_user("admin", password="x", is_staff=True)
        dist = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dist, True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        # 正式環境的樣子：隨機 SECRET_KEY、前端已 build；沒有 BAD 就不該拋 SystemExit
        with override_settings(SECRET_KEY="a-real-random-secret-key-of-fifty-characters-1234567890", FRONTEND_DIST=dist):
            buf = io.StringIO()
            call_command("doctor", "--json", stdout=buf)
        checks = {c["check"]: c for c in json.loads(buf.getvalue())}
        self.assertEqual(checks["accounts"]["state"], "ok")
        self.assertEqual(checks["web interface"]["state"], "ok")
        self.assertEqual(checks["settings: SECRET_KEY"]["state"], "ok")

    def test_doctor_flags_insecure_defaults_and_missing_plugin_dir(self):
        from django.contrib.auth.models import User
        from django.test import override_settings

        User.objects.create_user("admin", password="x", is_staff=True)
        with override_settings(DEBUG=True, SECRET_KEY="change-me", ALLOWED_HOSTS=["*"], VISION={**settings.VISION, "API_KEY": "", "TCP_AUTH": "", "PLUGIN_DIR": Path(settings.DATA_DIR) / "no-such-plugins"}):
            buf = io.StringIO()
            with self.assertRaises(SystemExit):
                call_command("doctor", "--json", stdout=buf)
            checks = {c["check"]: c for c in json.loads(buf.getvalue())}
        self.assertEqual(checks["settings: DEBUG"]["state"], "warn")
        self.assertEqual(checks["settings: SECRET_KEY"]["state"], "bad")
        self.assertEqual(checks["settings: API key"]["state"], "warn")
        self.assertEqual(checks["settings: TCP auth"]["state"], "warn")
        self.assertEqual(checks["plugins dir"]["state"], "bad")
        with override_settings(DEBUG=False, SECRET_KEY="a-real-random-secret-key-of-fifty-characters-1234567890", ALLOWED_HOSTS=["vision-st01", "192.168.1.5"],
                               VISION={**settings.VISION, "API_KEY": "k", "TCP_AUTH": "t"}):
            buf = io.StringIO()
            try:
                call_command("doctor", "--json", stdout=buf)
            except SystemExit:
                pass  # 其他檢查（例如前端 build）可能 BAD，這裡只看設定類
            checks = {c["check"]: c for c in json.loads(buf.getvalue())}
        for name in ("settings: DEBUG", "settings: SECRET_KEY", "settings: ALLOWED_HOSTS", "settings: API key", "settings: TCP auth", "plugins dir"):
            self.assertEqual(checks[name]["state"], "ok", name)
