"""從影像檔建形狀範本資產：manage.py shape_model --name NAME --image PATH [--region JSON] [--exclude JSON] [--min-contrast 10] [--levels 0] [--group G]"""

from __future__ import annotations

import json
import os
import uuid

import cv2
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vision import shapemodel
from apps.vision.api_shapemodel import build_model
from apps.vision.models import Asset


class Command(BaseCommand):
    help = "Build a shape model asset (edge points and gradient directions per pyramid level) from an image"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--image", required=True, help="Image file (png/jpg/bmp/tif)")
        parser.add_argument("--region", default="", help='Template ROI JSON, e.g. {"shape":"rect","x":10,"y":10,"w":200,"h":100}; blank = whole image')
        parser.add_argument("--exclude", default="", help="ROI JSON of an area to leave out of the model")
        parser.add_argument("--min-contrast", type=float, default=10.0)
        parser.add_argument("--contrast-low", type=float, default=None)
        parser.add_argument("--contrast-high", type=float, default=None)
        parser.add_argument("--levels", type=int, default=0, help="Pyramid levels; 0 = automatic")
        parser.add_argument("--max-points", type=int, default=1024)
        parser.add_argument("--angle-start", type=float, default=-180.0)
        parser.add_argument("--angle-extent", type=float, default=360.0)
        parser.add_argument("--scale-min", type=float, default=1.0)
        parser.add_argument("--scale-max", type=float, default=1.0)
        parser.add_argument("--group", default="")

    def handle(self, *args, **options):
        path = options["image"]
        if not os.path.isfile(path):
            raise CommandError(f"Image not found: {path}")
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise CommandError("Not a decodable image")

        def roi(text: str, label: str):
            if not text:
                return None
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise CommandError(f"--{label} is not valid JSON: {exc}") from None
            if not isinstance(value, dict) or not value.get("shape"):
                raise CommandError(f"--{label} must be an ROI object")
            return value

        params = {"min_contrast": options["min_contrast"], "contrast_low": options["contrast_low"], "contrast_high": options["contrast_high"],
                  "pyramid_levels": options["levels"], "max_points": options["max_points"], "angle_start": options["angle_start"],
                  "angle_extent": options["angle_extent"], "scale_min": options["scale_min"], "scale_max": options["scale_max"]}
        try:
            model, meta = build_model(image, roi(options["region"], "region"), roi(options["exclude"], "exclude"), params)
        except (shapemodel.ShapeModelError, ValueError) as exc:
            raise CommandError(str(exc)) from None
        asset_id = uuid.uuid4()
        out = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.npz")
        size = shapemodel.save(out, model)
        asset = Asset.objects.create(id=asset_id, name=options["name"], kind="file", group=options["group"].strip(), path=out, size=size, meta=meta)
        self.stdout.write(f"asset {asset.id}  {asset.name}  {meta['width']}x{meta['height']}  levels={meta['levels']}  points={meta['points']}  "
                          f"contrast {meta['contrast_low']}/{meta['contrast_high']}  radius {meta['radius']}")
