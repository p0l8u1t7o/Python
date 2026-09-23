"""
原廠端工具：產生合成的模組驗證資料集 (xrv-validation-set/1)，供 validate-module 示範與測試

  python tools/model_training/make_synthetic_dataset.py --out build/validation/synthetic_void.zip [--images 12] [--seed 500]

每張影像的焊點與空洞為正確答案 (空洞以 48 點多邊形表示)；焊墊、曝光、功率隨機變化。
"""
import argparse
import io
import json
import math
import os
import sys
import time
import zipfile

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))


def build(out, n_images=12, seed=500, **extra):
    from synthetic_void import make_image
    rng = np.random.default_rng(seed)
    images = []
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for k in range(n_images):
            kw = dict(seed=seed + k, pad=bool(rng.uniform() < 0.5), exposure=float(rng.uniform(0.6, 1.6)),
                      power=float(rng.uniform(0.7, 1.4)))
            kw.update(extra)
            img, balls = make_image(**kw)
            ok, buf = cv2.imencode(".tiff", img)
            name = f"images/synth_{k + 1:03d}.tiff"
            z.writestr(name, buf.tobytes())
            voids = [[[vx + vr * math.cos(a), vy + vr * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 48, endpoint=False)]
                     for b in balls for vx, vy, vr in b.voids]
            images.append(dict(file=name, balls=[[b.x, b.y, b.r] for b in balls], voids=voids,
                               truth_void_pct=[b.void_pct(img.shape) for b in balls], params=kw))
        z.writestr("annotations.json", json.dumps(dict(format="xrv-validation-set/1", module_id="void",
                                                       created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                       source="synthetic", images=images), indent=1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--images", type=int, default=12)
    ap.add_argument("--seed", type=int, default=500)
    a = ap.parse_args()
    print(build(a.out, a.images, a.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
