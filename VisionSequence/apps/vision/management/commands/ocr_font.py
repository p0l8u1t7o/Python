"""從資料夾教字型：manage.py ocr_font --name NAME --folder DIR [--mode projection|components|fixed] [--polarity …] [--asset-name …]

DIR 裡每個影像檔是一行字，檔名（去掉副檔名與 _n 尾碼）就是正確字串，例如 240912.png、240912_2.png、LOT-A17.png。
切分後的樣本存進 ASSET_DIR/ocr_fonts/NAME/，接著訓練並存成 ocr_read 可選的模型資產。
"""

from __future__ import annotations

import os
import re

import cv2
import numpy as np
from django.core.management.base import BaseCommand, CommandError

from apps.core.errors import ValidationError
from apps.vision.api_ocr import add_line_samples, font_counts, train_font_asset

EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


class Command(BaseCommand):
    help = "Teach an OCR font from a folder of line images named after their text, and export the model asset"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Font name (letters, digits, - _)")
        parser.add_argument("--folder", required=True)
        parser.add_argument("--mode", default="projection", choices=["projection", "components", "fixed"])
        parser.add_argument("--polarity", default="dark_on_light", choices=["dark_on_light", "light_on_dark"])
        parser.add_argument("--asset-name", default="")
        parser.add_argument("--epochs", type=int, default=400)
        parser.add_argument("--no-train", action="store_true", help="Only add the samples")

    def handle(self, *args, **options):
        folder = options["folder"]
        if not os.path.isdir(folder):
            raise CommandError(f"Folder not found: {folder}")
        added = skipped = 0
        for fn in sorted(os.listdir(folder)):
            if not fn.lower().endswith(EXTS):
                continue
            text = re.sub(r"_\d+$", "", os.path.splitext(fn)[0])
            gray = cv2.imdecode(np.fromfile(os.path.join(folder, fn), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                skipped += 1
                continue
            try:
                out = add_line_samples(options["name"], gray, None, text, options["mode"], len(text) if options["mode"] == "fixed" else 0, options["polarity"])
                added += out["stored"]
            except ValidationError as exc:
                self.stderr.write(f"skip {fn}: {exc}")
                skipped += 1
        counts = font_counts(options["name"])
        self.stdout.write(f"samples added {added}, files skipped {skipped}; per character: " + ", ".join(f"{k}×{v}" for k, v in counts.items()))
        if options["no_train"]:
            return
        try:
            asset = train_font_asset(options["name"], options["asset_name"], epochs=options["epochs"])
        except ValidationError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"asset {asset.id}  {asset.name}  classes={len(asset.meta['classes'])}  val_accuracy={asset.meta['metrics'].get('val_accuracy')}")
