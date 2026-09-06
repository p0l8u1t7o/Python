"""OCR 模型：manage.py ocr_models --install <rapidocr wheel|zip|資料夾> ｜ --check

--install 把 PP-OCRv4 的三個 ONNX（det／rec／cls）複製到 ASSET_DIR/ocr 並寫 MODELS.json（來源、授權、輸入正規化）。
來源：`pip download rapidocr-onnxruntime --no-deps`（Apache-2.0；模型出自 PaddleOCR，Apache-2.0，可商用轉散布）。執行期不下載。
"""

from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand, CommandError

from apps.vision import ocr


class Command(BaseCommand):
    help = "Install or check the offline OCR models (PP-OCRv4 ONNX) in ASSET_DIR/ocr"

    def add_arguments(self, parser):
        parser.add_argument("--install", default="", help="A rapidocr-onnxruntime wheel/zip, or a folder holding the three ONNX files")
        parser.add_argument("--check", action="store_true")

    def handle(self, *args, **options):
        if options["install"]:
            try:
                copied = ocr.install_models(options["install"])
            except ocr.OcrError as exc:
                raise CommandError(str(exc)) from None
            self.stdout.write(f"installed {', '.join(copied)} into {ocr.models_dir()}")
        if options["check"] or not options["install"]:
            if not ocr.models_available():
                raise CommandError(f"OCR models missing in {ocr.models_dir()} (run --install <rapidocr wheel or folder>)")
            import numpy as np

            sess = ocr.session(ocr.model_path(ocr.REC_MODEL))
            x = np.zeros((1, 3, ocr.REC_HEIGHT, 320), np.float32)
            t0 = time.perf_counter()
            out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
            table = ocr.characters(ocr.model_path(ocr.REC_MODEL))
            self.stdout.write(f"ok rec {out.shape} ({(time.perf_counter() - t0) * 1000:.0f} ms, {len(table)} classes) providers={sess.get_providers()}; det {'present' if os.path.isfile(ocr.model_path(ocr.DET_MODEL)) else 'missing'}")
