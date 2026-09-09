from __future__ import annotations

import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.vision import fileout


class FileOutputRootsTests(SimpleTestCase):
    def test_absolute_path_is_allowed_only_under_extra_roots(self):
        with tempfile.TemporaryDirectory(prefix="vs-fileout-root-") as tmp:
            allowed = Path(tmp).resolve()
            with override_settings(VISION={**settings.VISION, "FILE_OUTPUT_ROOTS": [str(allowed)]}):
                target = fileout.resolve_dir(str(allowed / "line1" / "logs"))
                self.assertEqual(target, allowed / "line1" / "logs")
                with self.assertRaisesRegex(ValueError, "inside an allowed output root"):
                    fileout.resolve_dir(str(allowed.parent / "other"))

    def test_parent_segments_are_rejected_even_under_extra_roots(self):
        with tempfile.TemporaryDirectory(prefix="vs-fileout-root-") as tmp:
            allowed = Path(tmp).resolve()
            with override_settings(VISION={**settings.VISION, "FILE_OUTPUT_ROOTS": [str(allowed)]}):
                with self.assertRaisesRegex(ValueError, "must not contain"):
                    fileout.resolve_dir(str(allowed / "line1" / ".." / "logs"))

