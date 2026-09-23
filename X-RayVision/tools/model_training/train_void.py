"""
原廠端工具 (不隨產品發布)：訓練空洞分割模型並打包成 .xrvmodel

  python tools/model_training/train_void.py --out build/models --key tools/keys/update_private_DEV.pem
        [--version 1.0.0] [--images 160] [--epochs 14] [--dataset <5d 匯出的訓練資料集.zip> ...]

資料來源：
  - 合成影像 (tests/synthetic_void.py)：焊墊有無、曝光、功率、焊球大小、模糊隨機變化，提供正確答案
  - 標註資料集 (選用，5d「訓練資料匯出」)：實際影像的焊點裁切與空洞遮罩
前處理與產品共用 xrayvision/inspections/void/model_seg.py (ball_crop)，確保一致。
模型：小型 U-Net (16/32/64 通道)，輸入 1x64x64 正規化吸收量，輸出空洞機率；ONNX opset 17，批次維度可變。
需要 PyTorch 與 onnx (只在原廠端安裝)。
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
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from xrayvision.core import modelpkg  # noqa: E402
from xrayvision.inspections.void.model_seg import NORMALIZATION, ball_crop, mask_crop  # noqa: E402

SIZE, CROP_SCALE = 64, 1.4


# ---------------------------------------------------------------------------
# 資料
# ---------------------------------------------------------------------------
def synthetic_samples(n_images, seed0):
    from synthetic_void import make_image
    rng = np.random.default_rng(seed0)
    X, Y = [], []
    for k in range(n_images):
        kw = dict(seed=seed0 + k, pad=bool(rng.uniform() < 0.6), exposure=float(rng.uniform(0.5, 2.0)),
                  power=float(rng.uniform(0.6, 1.5)), void_rate=0.7, max_rho=float(rng.uniform(0.8, 0.95)),
                  radius=float(rng.uniform(50, 80)), blur=float(rng.uniform(1.0, 2.2)))
        kw["pitch"] = kw["radius"] * 2.7
        img, balls = make_image(**kw)
        A = -np.log(np.clip(img.astype(np.float32), 1, None) / 65535)
        for b in balls:
            vm = b.void_mask(A.shape)
            disc = np.zeros(A.shape, np.uint8)
            cv2.circle(disc, (int(round(b.x * 8)), int(round(b.y * 8))), int(round(b.r * 8)), 1, -1, shift=3)
            vm &= disc
            # 模擬規則式擬合的位置與半徑誤差
            x, y, r = b.x + rng.normal(0, 0.8), b.y + rng.normal(0, 0.8), b.r * (1 + rng.normal(0, 0.01))
            c, win = ball_crop(A, x, y, r, SIZE, CROP_SCALE)
            X.append(c)
            Y.append(mask_crop(vm, win, SIZE))
    return np.stack(X)[:, None], np.stack(Y)[:, None]


def dataset_samples(path):
    """5d 匯出的訓練資料集：crops/*.png (16-bit，正規化吸收量) + masks/*.png + dataset.json"""
    X, Y = [], []
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("dataset.json"))
        for item in meta["items"]:
            c = cv2.imdecode(np.frombuffer(z.read(item["crop"]), np.uint8), cv2.IMREAD_UNCHANGED).astype(np.float32)
            lo, hi = meta["crop_encoding"]["range"]
            c = c / 65535.0 * (hi - lo) + lo
            m = cv2.imdecode(np.frombuffer(z.read(item["mask"]), np.uint8), cv2.IMREAD_UNCHANGED) > 0
            if c.shape != (SIZE, SIZE):
                c = cv2.resize(c, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
                m = cv2.resize(m.astype(np.float32), (SIZE, SIZE)) >= 0.5
            X.append(c)
            Y.append(m.astype(np.float32))
    return np.stack(X)[:, None], np.stack(Y)[:, None]


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
def build_net():
    import torch
    from torch import nn

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.e1, self.e2, self.e3 = block(1, 16), block(16, 32), block(32, 64)
            self.pool = nn.MaxPool2d(2)
            self.u2, self.d2 = nn.ConvTranspose2d(64, 32, 2, stride=2), block(64, 32)
            self.u1, self.d1 = nn.ConvTranspose2d(32, 16, 2, stride=2), block(32, 16)
            self.head = nn.Conv2d(16, 1, 1)

        def forward(self, x):
            e1 = self.e1(x)
            e2 = self.e2(self.pool(e1))
            e3 = self.e3(self.pool(e2))
            d2 = self.d2(torch.cat([self.u2(e3), e2], 1))
            d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
            return self.head(d1)

    return UNet()


def augment(x, y, rng):
    k = int(rng.integers(0, 4))
    x, y = np.rot90(x, k, axes=(2, 3)), np.rot90(y, k, axes=(2, 3))
    if rng.uniform() < 0.5:
        x, y = x[..., ::-1], y[..., ::-1]
    return np.ascontiguousarray(x), np.ascontiguousarray(y)


def disc_mask():
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    s = 2 * CROP_SCALE / SIZE                       # 以 R 為單位
    d = np.hypot((xx + 0.5) * s - CROP_SCALE, (yy + 0.5) * s - CROP_SCALE)
    return d < 0.9                                  # 與產品的邊緣排除環帶一致


def train(X, Y, Xv, Yv, epochs, seed=0):
    import torch
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
    net = build_net()
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    bce = torch.nn.BCEWithLogitsLoss()
    rng = np.random.default_rng(seed)
    n = len(X)
    for ep in range(epochs):
        net.train()
        idx = rng.permutation(n)
        tot = 0.0
        for i in range(0, n, 64):
            xb, yb = augment(X[idx[i:i + 64]], Y[idx[i:i + 64]], rng)
            xb, yb = torch.from_numpy(xb), torch.from_numpy(yb)
            logit = net(xb)
            p = torch.sigmoid(logit)
            dice = 1 - (2 * (p * yb).sum() + 1) / (p.sum() + yb.sum() + 1)
            loss = bce(logit, yb) + dice
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(xb)
        sched.step()
        m = evaluate(net, Xv, Yv)
        print(f"epoch {ep + 1}/{epochs} loss {tot / n:.4f} val dice {m['dice']:.3f} void% MAE {m['void_pct_mae']:.2f}",
              flush=True)
    return net, evaluate(net, Xv, Yv)


def predict(net, X):
    import torch
    net.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X), 256):
            out.append(torch.sigmoid(net(torch.from_numpy(X[i:i + 256]))).numpy())
    return np.concatenate(out)


def evaluate(net, X, Y):
    P = predict(net, X) >= 0.5
    zone = disc_mask()
    T = Y >= 0.5
    inter = (P & T).sum()
    dice = 2 * inter / max(P.sum() + T.sum(), 1)
    # 焊點面積 (以 R 為 1 的圓) 對應的裁切像素數
    ball_px = math.pi * (SIZE / (2 * CROP_SCALE)) ** 2
    pv = (P[:, 0] & zone).sum((1, 2)) / ball_px * 100
    tv = (T[:, 0] & zone).sum((1, 2)) / ball_px * 100
    err = np.abs(pv - tv)
    return dict(dice=float(dice), void_pct_mae=float(err.mean()), void_pct_p95=float(np.percentile(err, 95)),
                n=int(len(X)))


def export_onnx(net):
    import torch
    net.eval()

    class WithSigmoid(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            return torch.sigmoid(self.m(x))

    buf = io.BytesIO()
    torch.onnx.export(WithSigmoid(net), torch.zeros(1, 1, SIZE, SIZE), buf, input_names=["input"],
                      output_names=["void_probability"], opset_version=17,
                      dynamic_axes={"input": {0: "batch"}, "void_probability": {0: "batch"}}, dynamo=False)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "models"))
    ap.add_argument("--key", required=True, help="vendor signing private key (update key)")
    ap.add_argument("--model-id", default="void_unet")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--images", type=int, default=160)
    ap.add_argument("--epochs", type=int, default=14)
    ap.add_argument("--dataset", action="append", default=[])
    a = ap.parse_args()
    t0 = time.time()
    X, Y = synthetic_samples(a.images, 1000)
    Xv, Yv = synthetic_samples(max(10, a.images // 8), 900000)
    sources = [dict(kind="synthetic", images=a.images, crops=int(len(X)))]
    for d in a.dataset:
        x2, y2 = dataset_samples(d)
        X, Y = np.concatenate([X, x2]), np.concatenate([Y, y2])
        sources.append(dict(kind="annotated_dataset", file=os.path.basename(d), crops=int(len(x2))))
    print(f"training crops {len(X)}, validation {len(Xv)}  ({time.time() - t0:.0f}s)", flush=True)
    net, metrics = train(X, Y, Xv, Yv, a.epochs)
    onnx_bytes = export_onnx(net)
    meta = dict(model_id=a.model_id, version=a.version, module_id="void", task="void_segmentation",
                names={"zh-TW": "空洞分割模型（示範）", "en": "Void Segmentation Model (Demo)"},
                input=dict(size=SIZE, channels=1, crop_scale=CROP_SCALE, normalization=NORMALIZATION),
                output=dict(type="void_probability", threshold=0.5),
                training=dict(sources=sources, epochs=a.epochs, framework="pytorch", architecture="unet-16-32-64"),
                metrics=metrics, created_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"{a.model_id}-{a.version}.xrvmodel")
    modelpkg.build(out, meta, onnx_bytes, a.key)
    print(f"model {a.model_id}@{a.version}: dice {metrics['dice']:.3f}, void% MAE {metrics['void_pct_mae']:.2f} "
          f"(p95 {metrics['void_pct_p95']:.2f}), {len(onnx_bytes) / 1024:.0f} KB → {out}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
