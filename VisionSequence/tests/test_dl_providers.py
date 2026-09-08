"""處理器加速 provider 的可用性、順序與產品表面名稱。"""

from __future__ import annotations

import glob
import json
import os
import re
from unittest import mock

from django.conf import settings
from django.test import TestCase

from apps.vision.dl import devices


CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"
PROC = devices.PROCESSOR_ACCEL_PROVIDER


def _hits(text: str) -> list[str]:
    return [m.group(0) for m in re.finditer("openvino", text, re.I)]


class DlProviderTests(TestCase):
    def setUp(self) -> None:
        self._old_preferred = list(devices._preferred)
        self._old_device = devices._train_device
        with devices._lock:
            devices._preferred = []
            devices._train_device = ""
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        with devices._lock:
            devices._preferred = self._old_preferred
            devices._train_device = self._old_device

    def test_unavailable_provider_keeps_current_cpu_default(self):
        with mock.patch.object(devices, "available_providers", return_value=[CPU]):
            self.assertEqual(devices.preferred_providers(), [CPU])

    def test_available_provider_is_after_cuda_before_cpu(self):
        with mock.patch.object(devices, "available_providers", return_value=[CPU, PROC, CUDA]):
            self.assertEqual(devices.preferred_providers(), [CUDA, PROC, CPU])

    def test_devices_endpoint_reports_processor_availability(self):
        with (
            mock.patch.object(devices, "available_providers", return_value=[CPU, PROC]),
            mock.patch.object(devices, "_torch_cuda_available", return_value=False),
            mock.patch.object(devices, "_gpus", return_value=[]),
        ):
            r = self.client.get("/api/vision/dl/devices")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["processor_acceleration_available"])
        self.assertIn("Processor acceleration", body["accelerators"])
        detail = next(item for item in body["provider_details"] if item["provider"] == PROC)
        self.assertEqual(detail["label"], "Processor acceleration")
        self.assertTrue(detail["available"])

    def test_settings_endpoint_accepts_processor_provider(self):
        with (
            mock.patch.object(devices, "available_providers", return_value=[CPU, PROC]),
            mock.patch("apps.vision.tools.builtin.dl.clear_sessions"),
        ):
            r = self.client.patch("/api/vision/dl/settings", data=json.dumps({"providers": [PROC]}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["preferred_providers"], [PROC])

    def test_product_surface_labels_do_not_name_vendor(self):
        with (
            mock.patch.object(devices, "available_providers", return_value=[CPU, PROC]),
            mock.patch.object(devices, "_torch_cuda_available", return_value=False),
            mock.patch.object(devices, "_gpus", return_value=[]),
        ):
            info = devices.info()
        surface = json.dumps({"accelerators": info["accelerators"], "labels": [p["label"] for p in info["provider_details"]]}, ensure_ascii=False)
        self.assertEqual(_hits(surface), [])

        root = str(settings.BASE_DIR)
        for path in glob.glob(os.path.join(root, "frontend", "src", "i18n", "locales", "*.ts")):
            with self.subTest(file=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(_hits(fh.read()), [])
        for path in glob.glob(os.path.join(root, "docs", "*.html")):
            with self.subTest(file=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                body = re.sub(r"<code>.*?</code>|<pre[\s\S]*?</pre>|<!--[\s\S]*?-->", "", body)
                self.assertEqual(_hits(body), [])
