"""異常檢測 backbone：manage.py anomaly_backbone [--export] [--check]

--export 用 torchvision 的 ImageNet 預訓練 ResNet18 匯出 layer2／layer3 特徵 ONNX 到 ASSET_DIR/dl/weights/（開發機／打包用；
現場機器由 DL 加購包附帶，執行期不下載）。--check 只回報檔案是否存在並試跑一次。
"""

from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand, CommandError

from apps.vision.dl import anomaly


class Command(BaseCommand):
    help = "Export or check the anomaly-detection backbone ONNX (ResNet18 layer2/layer3 features)"

    def add_arguments(self, parser):
        parser.add_argument("--export", action="store_true", help="Export with torchvision (needs torch and torchvision)")
        parser.add_argument("--check", action="store_true", help="Report whether the backbone is installed and run it once")
        parser.add_argument("--name", default="resnet18")

    def handle(self, *args, **options):
        name = options["name"]
        path = anomaly.backbone_path(name)
        if options["export"]:
            try:
                out = anomaly.export_backbone(path, name)
            except anomaly.AnomalyError as exc:
                raise CommandError(str(exc)) from None
            self.stdout.write(f"exported {out} ({os.path.getsize(out) // 1024} KB)")
        if options["check"] or not options["export"]:
            if not os.path.isfile(path):
                raise CommandError(f"backbone missing: {path} (run --export on a machine with torch and torchvision, or install the deep-learning pack)")
            import numpy as np

            sess = anomaly.session_for(path, path=path, device="auto")
            x = np.zeros((1, 3, 320, 320), np.float32)
            t0 = time.perf_counter()
            outs = sess.run(None, {sess.get_inputs()[0].name: x})
            self.stdout.write(f"ok {path}  providers={sess.get_providers()}  outputs={[o.shape for o in outs]}  {(time.perf_counter() - t0) * 1000:.0f} ms")
