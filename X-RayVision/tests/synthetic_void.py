"""
空洞檢測的合成影像產生器 (規劃書 PLAN-002 第 3.5 節)

以穿透厚度建立吸收量影像，再依光子雜訊轉成 16-bit 強度影像，並提供正確答案：
  - 焊球：截頂球 (上下被焊墊壓平)，穿透厚度 min(2·sqrt(Rs² - d²), h)
  - 焊墊：焊球下方偏心的薄圓盤，吸收量較高 (實際影像中焊球內的亮斑)
  - 空洞：焊球內的球形氣泡，扣除其弦長厚度
  - 背景：平面漸層＋走線格紋；邊緣模糊 (焦點尺寸)；光子雜訊
數值依 Batch2 實測：背景吸收量約 0.75、焊球對比約 0.3、焊墊約 +0.08、背景雜訊約 0.016。

也可單獨執行，輸出範例影像：python -m tests.synthetic_void temp/void_synth
"""
import math
import os
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Ball:
    x: float
    y: float
    r: float
    voids: list = field(default_factory=list)          # [(x, y, r)]
    pad: tuple = None                                   # (x, y, r)

    def void_mask(self, shape):
        m = np.zeros(shape, np.uint8)
        for vx, vy, vr in self.voids:
            cv2.circle(m, (int(round(vx * 8)), int(round(vy * 8))), int(round(vr * 8)), 1, -1, shift=3)
        return m

    def void_pct(self, shape):
        """空洞 (聯集) 投影面積 ÷ 焊球投影面積 × 100；只計入焊球輪廓內"""
        m = self.void_mask(shape)
        b = np.zeros(shape, np.uint8)
        cv2.circle(b, (int(round(self.x * 8)), int(round(self.y * 8))), int(round(self.r * 8)), 1, -1, shift=3)
        return 100.0 * float((m & b).sum()) / (math.pi * self.r ** 2)


def _chord(d2, R):
    return 2.0 * np.sqrt(np.clip(R * R - d2, 0, None))


def make_image(shape=(900, 1100), radius=70.0, pitch=190.0, flat=0.8, contrast=0.30, pad_contrast=0.08,
               bg=0.75, texture=0.02, gradient=0.10, blur=1.5, photons=4000.0, voids="random",
               void_rate=0.6, void_r_range=(0.08, 0.45), seed=0, exposure=1.0, power=1.0, pad=True,
               oblique_deg=0.0, max_rho=0.8, noise_seed=None):
    """
    產生一張焊球陣列影像。
      flat：截頂高度 / 球直徑 (1 為完整球)；contrast：焊球中心吸收量 (背景以上)
      voids："random" 依 void_rate 隨機產生，或 {焊球索引: [(dx/R, dy/R, r/R), ...]} 指定；None 為無空洞
      exposure：光子數倍率 (雜訊隨之改變)；power：吸收量倍率 (模擬管電壓改變造成的對比變化)
      oblique_deg：斜射角，焊球投影沿 x 方向拉長 1/cos
      max_rho：空洞外緣離焊球中心的最大距離 / R (0.95 表示可貼近焊球邊緣)
      noise_seed：光子雜訊的亂數種子 (None 時沿用 seed 的亂數序列)；固定幾何、只換雜訊時使用
    回傳 (uint16 影像, [Ball])
    """
    rng = np.random.default_rng(seed)
    H, W = shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    A = bg + gradient * (xx / W - 0.5) + 0.5 * gradient * (yy / H - 0.5)
    if texture:
        grid = ((xx % 23) < 2) | ((yy % 23) < 2)
        A = A + texture * grid
    stretch = 1.0 / math.cos(math.radians(oblique_deg))
    h = flat * 2 * radius
    scale = contrast / h                                   # 每單位厚度的吸收量
    balls = []
    n_x = int((W - 2 * radius) // pitch)
    n_y = int((H - 2 * radius) // pitch)
    x0 = (W - (n_x - 1) * pitch) / 2
    y0 = (H - (n_y - 1) * pitch) / 2
    idx = 0
    for j in range(n_y):
        for i in range(n_x):
            cx = x0 + i * pitch + rng.uniform(-3, 3)
            cy = y0 + j * pitch + rng.uniform(-3, 3)
            R = radius * rng.uniform(0.97, 1.03)
            b = Ball(cx, cy, R)
            u = (xx - cx) / stretch
            d2 = u * u + (yy - cy) ** 2
            t = np.minimum(_chord(d2, R), h)
            if pad:
                ang = rng.uniform(0, 2 * math.pi)
                pr = 0.35 * R
                px, py = cx + 0.3 * R * math.cos(ang), cy + 0.3 * R * math.sin(ang)
                b.pad = (px, py, pr)
                A = A + pad_contrast * ((xx - px) ** 2 + (yy - py) ** 2 <= pr * pr)
            spec = None
            if voids == "random":
                if rng.uniform() < void_rate:
                    spec = []
                    for _ in range(int(rng.integers(1, 4))):
                        vr = rng.uniform(*void_r_range)
                        rho = rng.uniform(0, max_rho - vr) if vr < max_rho else 0.0
                        a = rng.uniform(0, 2 * math.pi)
                        spec.append((rho * math.cos(a), rho * math.sin(a), vr))
            elif isinstance(voids, dict):
                spec = voids.get(idx)
            for dx, dy, vr in spec or ():
                vx, vy, rv = cx + dx * R * stretch, cy + dy * R, vr * R
                dv2 = ((xx - vx) / stretch) ** 2 + (yy - vy) ** 2
                # 空洞在截頂球內：弦長不超過焊球在該點的厚度
                t = t - np.minimum(_chord(dv2, rv), t)
                b.voids.append((vx, vy, rv))
            A = A + scale * t
            balls.append(b)
            idx += 1
    A = A * power
    if blur:
        A = cv2.GaussianBlur(A, (0, 0), blur)
    # 光子雜訊：背景處平均 photons×exposure 個光子
    ref = bg * power
    n0 = photons * exposure
    lam = n0 * np.exp(-(A - ref))
    nrng = rng if noise_seed is None else np.random.default_rng(noise_seed)
    counts = nrng.poisson(lam).astype(np.float32)
    A_noisy = ref - np.log(np.clip(counts, 1, None) / n0)
    img = np.clip(65535.0 * np.exp(-A_noisy), 1, 65535).astype(np.uint16)
    return img, balls


def main(out):
    os.makedirs(out, exist_ok=True)
    for i, kw in enumerate([dict(), dict(exposure=0.5), dict(power=1.5), dict(oblique_deg=35)]):
        img, balls = make_image(seed=7, **kw)
        cv2.imwrite(os.path.join(out, f"synth_{i}.tiff"), img)
        print(i, kw, [round(b.void_pct(img.shape), 1) for b in balls])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "temp/void_synth")
