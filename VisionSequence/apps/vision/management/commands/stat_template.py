"""從資料夾的良品影像建統計範本資產：manage.py stat_template --name NAME --folder DIR [--region JSON] [--align phase|none] [--group G]"""

from __future__ import annotations

import json
import os
import uuid

import cv2
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vision import stattpl
from apps.vision.models import Asset

EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


class Command(BaseCommand):
    help = "Build a statistical template asset (per-pixel mean/std) from a folder of good images"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Asset name")
        parser.add_argument("--folder", required=True, help="Folder of good images (png/jpg/bmp/tif)")
        parser.add_argument("--region", default="", help='ROI JSON, e.g. {"shape":"rect","x":10,"y":10,"w":200,"h":100}')
        parser.add_argument("--align", default="phase", choices=["phase", "none"])
        parser.add_argument("--max-shift", type=float, default=0.0, help="Drop images that align further than this many px (0 = keep all)")
        parser.add_argument("--group", default="", help="Asset group")
        parser.add_argument("--limit", type=int, default=200, help="Use at most this many images")

    def handle(self, *args, **options):
        folder = options["folder"]
        if not os.path.isdir(folder):
            raise CommandError(f"Folder not found: {folder}")
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(EXTS))[: max(1, int(options["limit"]))]
        images = []
        for n in names:
            buf = np.fromfile(os.path.join(folder, n), dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
            if img is None:
                self.stderr.write(f"skip (not an image): {n}")
                continue
            images.append(img)
        region = None
        if options["region"]:
            try:
                region = json.loads(options["region"])
            except json.JSONDecodeError as exc:
                raise CommandError(f"--region is not valid JSON: {exc}") from None
        try:
            payload, meta = stattpl.build(images, region, options["align"], options["max_shift"])
        except stattpl.StatTemplateError as exc:
            raise CommandError(str(exc)) from None
        asset_id = uuid.uuid4()
        path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.npz")
        size = stattpl.save(path, payload)
        asset = Asset.objects.create(id=asset_id, name=options["name"], kind="file", group=options["group"].strip(), path=path, size=size, meta=meta)
        self.stdout.write(f"asset {asset.id}  {asset.name}  samples={meta['samples']}  {meta['width']}x{meta['height']}  "
                          f"shift max {meta['shift_max']} px  std p50/p90/p99 {meta['std_p50']}/{meta['std_p90']}/{meta['std_p99']}  valid {meta['valid_ratio']:.1%}")
