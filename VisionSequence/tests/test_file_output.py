from __future__ import annotations

import csv
import os
import queue
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from django.conf import settings
from django.test import TestCase, override_settings

from apps.vision import fileout, retention
from apps.vision.models import RetentionSettings
from apps.vision.tools import base, register_builtins
from apps.vision.tools.base import ToolContext, ToolError

register_builtins()


MOMENT = time.mktime((2026, 9, 8, 10, 11, 12, 0, 0, -1))


class FileOutputTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="vs-fileout-")
        self.data_dir = Path(self.tmp.name)
        self.override = override_settings(
            DATA_DIR=self.data_dir,
            VISION={**settings.VISION, "FILE_OUTPUT_DIR": "", "STATION_ID": "ST99", "RETENTION_SWEEP": False},
        )
        self.override.enable()
        retention.invalidate()
        fileout.clear()

    def tearDown(self) -> None:
        fileout.flush()
        fileout.clear()
        retention.invalidate()
        self.override.disable()
        self.tmp.cleanup()

    def ctx(
        self,
        key: str,
        params: dict[str, Any],
        *,
        flow_id: int = 1,
        preview: bool = False,
        inputs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolContext:
        tool = base.get(key)
        return ToolContext(
            run_id="abcdef0123456789",
            flow_id=flow_id,
            node={"id": key, "type": key, "params": params},
            inputs=inputs or {},
            context=context or {},
            moment=MOMENT,
            log=lambda *a, **k: None,
            asset_path=lambda aid: None,
            grab=lambda sid: None,
            preview=preview,
            depth=getattr(tool, "accepts", ("u8",)),
        )

    def write_log(self, params: dict[str, Any], **kw: Any):
        return base.get("write_log").execute(self.ctx("write_log", params, **kw))

    def test_write_log_csv_values_filename_and_daily_folder(self):
        res = self.write_log(
            {
                "path": "qa/line1",
                "format": "csv",
                "fields": "judge\n{width:.2f}\nlot\na\nrun_id\nstation",
                "filename": "{station}_{lot}_{date}",
                "daily_folder": True,
                "header": True,
            },
            inputs={"a": 5},
            context={"_judge": "ok", "_outputs": {"width": 12.3456}, "lot": "A17"},
        )
        self.assertTrue(res.outputs["queued"])
        self.assertTrue(fileout.flush())
        path = Path(res.outputs["path"])
        self.assertEqual(path.parent.name, "20260908")
        self.assertEqual(path.name, "ST99_A17_20260908.csv")
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["judge", "width", "lot", "a", "run_id", "station"])
        self.assertEqual(rows[1], ["OK", "12.35", "A17", "5", "abcdef0123456789", "ST99"])

    def test_write_log_rotates_by_rows(self):
        params = {"path": "qa", "format": "csv", "fields": "run_id", "filename": "parts", "daily_folder": False, "rotate_rows": 1}
        self.write_log(params)
        self.write_log(params)
        self.assertTrue(fileout.flush())
        files = sorted((self.data_dir / "file_outputs" / "qa").glob("parts*.csv"))
        self.assertEqual([p.name for p in files], ["parts.csv", "parts_002.csv"])

    def test_write_log_rotates_by_size(self):
        params = {
            "path": "qa",
            "format": "txt",
            "fields": "lot",
            "filename": "big",
            "daily_folder": False,
            "rotate_mb": 0.000001,
            "header": False,
        }
        self.write_log(params, context={"lot": "A" * 80})
        self.write_log(params, context={"lot": "B" * 80})
        self.assertTrue(fileout.flush())
        files = sorted((self.data_dir / "file_outputs" / "qa").glob("big*.txt"))
        self.assertEqual([p.name for p in files], ["big.txt", "big_002.txt"])

    def test_write_log_rejects_path_escape(self):
        for bad in ("..", "../qa", str(self.data_dir / "outside"), "C:/outside"):
            with self.subTest(bad=bad), self.assertRaises(ToolError):
                self.write_log({"path": bad, "format": "csv", "fields": "run_id", "filename": "x"})

    def test_preview_and_batch_do_not_write_files(self):
        params = {"path": "qa", "format": "csv", "fields": "run_id", "filename": "parts", "daily_folder": False}
        self.write_log(params, preview=True)
        self.write_log(params, flow_id=0)
        self.assertTrue(fileout.flush())
        self.assertFalse((self.data_dir / "file_outputs").exists())

    def test_full_queue_drops_without_failing_run(self):
        old_queue, old_started = fileout._queue, fileout._started  # noqa: SLF001
        try:
            fileout._queue = queue.Queue(maxsize=1)  # noqa: SLF001
            fileout._queue.put_nowait(object())  # noqa: SLF001
            fileout._started = True  # noqa: SLF001
            res = self.write_log({"path": "qa", "format": "csv", "fields": "run_id", "filename": "parts"})
            self.assertEqual(res.status, "ok")
            self.assertFalse(res.outputs["queued"])
        finally:
            fileout._queue = old_queue  # noqa: SLF001
            fileout._started = old_started  # noqa: SLF001

    def test_retention_sweep_deletes_old_file_outputs(self):
        base = self.data_dir / "file_outputs" / "qa"
        base.mkdir(parents=True)
        old = base / "old.csv"
        new = base / "new.csv"
        old.write_text("old\n", encoding="utf-8")
        new.write_text("new\n", encoding="utf-8")
        os.utime(old, (time.time() - 3 * 86400, time.time() - 3 * 86400))
        RetentionSettings.objects.update_or_create(
            id=1,
            defaults={
                "run_days": 0,
                "audit_days": 0,
                "measurement_days": 0,
                "archive_days": 0,
                "archive_max_gb": 0,
                "file_output_days": 1,
                "file_output_max_gb": 20.0,
            },
        )
        retention.invalidate()
        result = retention.sweep(force=True)
        self.assertEqual(result["file_output_files"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_save_image_uses_template_daily_folder_and_jpeg_quality(self):
        image = np.full((32, 32), 128, np.uint8)
        res = base.get("save_image").execute(
            self.ctx(
                "save_image",
                {
                    "folder": str(self.data_dir / "images"),
                    "format": "jpg",
                    "split_by_judge": False,
                    "condition": "all",
                    "filename": "{station}_{lot}_{date}",
                    "daily_folder": True,
                    "jpeg_quality": 50,
                },
                inputs={"image": image},
                context={"_judge": "ok", "lot": "A17"},
            )
        )
        self.assertTrue(fileout.flush())
        path = Path(res.outputs["path"])
        self.assertEqual(path.parent.name, "20260908")
        self.assertEqual(path.name, "ST99_A17_20260908.jpg")
        self.assertTrue(path.exists())


class ExitDrainTests(TestCase):
    """行程結束前要把待寫的檔案寫完——品保靠這些 CSV，服務重啟不該吃掉最後幾列。"""

    def test_drain_on_exit_writes_what_is_still_queued(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "exit.csv"
            fileout.submit(fileout.TextJob(
                path=target, fmt="csv", row=["r1"], header=["run_id"], write_header=True,
                rotate_bytes=0, rotate_rows=0, encoding="utf-8",
            ))
            fileout._drain_on_exit()
            self.assertTrue(target.exists(), "結束前應該把待寫的那一列寫出來")
            self.assertIn("r1", target.read_text(encoding="utf-8"))

    def test_drain_on_exit_does_nothing_when_the_queue_is_empty(self):
        fileout.flush(2.0)
        fileout._drain_on_exit()   # 佇列空的時候不該丟例外，也不該卡住
