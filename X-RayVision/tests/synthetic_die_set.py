"""
合成晶片圖組 (規劃書 PLAN-006 第 8.1 節)：一顆比視野大的晶片，在不同位置拍攝的多張影像。

座標：以基板為準的共同座標 (單位 px，即平台座標換算到像素)。
- 焊墊在基板上的名目位置 P；晶片名目中心 Cd；
- 晶片相對基板的整體平移 t 與旋轉 theta：晶片座標 q 的點位於 Cd + t + R(theta)·q；
- 凸塊在晶片座標的位置等於焊墊的名目位置 (q = P - Cd)，所以凸塊對焊墊偏移 = t + (R - I)·q。
- 晶片本體是吸收較高的矩形平台 (邊緣柔和)，外側基板有較大的錫球。

視野影像以中心的共同座標 (平台座標) 定位，像素 (u, v) 對應共同座標 (cx + u - W/2, cy + v - H/2)。
"""
import argparse
import json
import os

import cv2
import numpy as np

DIE_W, DIE_H = 6000.0, 4800.0       # 晶片設計尺寸 (px)
PITCH = 90.0
BUMP_R, PAD_R = 24.0, 28.0
FOV = (1080, 1384)                  # 視野 (高, 寬)；比實機小以加快測試
BASE, DIE_STEP = 0.35, 0.12         # 基板吸收量、晶片平台高度
EDGE_SIGMA = 12.0                   # 晶片邊緣模糊
BALL_R, BALL_PITCH = 40.0, 230.0    # 基板錫球


def _rot(theta_deg):
    t = np.radians(theta_deg)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


def _disc(A, cx, cy, r, amp, dome=False):
    """以解析式抗鋸齒畫圓盤 (加到 A)"""
    h = int(np.ceil(r + 3))
    x0, y0 = int(np.floor(cx)) - h, int(np.floor(cy)) - h
    H, W = A.shape
    xa, xb, ya, yb = max(0, x0), min(W, x0 + 2 * h + 1), max(0, y0), min(H, y0 + 2 * h + 1)
    if xa >= xb or ya >= yb:
        return
    yy, xx = np.mgrid[ya:yb, xa:xb].astype(np.float32)
    d = np.hypot(xx - cx, yy - cy)
    cov = np.clip(r - d + 0.5, 0, 1)
    if dome:
        cov = cov * (0.6 + 0.4 * np.sqrt(np.clip(1 - (d / r) ** 2, 0, 1)))
    A[ya:yb, xa:xb] += amp * cov


def render(center, shift=(0.0, 0.0), theta_deg=0.0, die_center=(0.0, 0.0), fov=FOV, seed=0):
    """回傳一個視野的吸收量影像 (float32)"""
    H, W = fov
    cx, cy = center
    gx0, gy0 = cx - W / 2, cy - H / 2                       # 影像 (0, 0) 的共同座標
    R = _rot(theta_deg)
    Ri = R.T
    t = np.asarray(shift, float)
    Cd = np.asarray(die_center, float)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # 晶片平台：以晶片座標的到邊距離做柔和階梯
    gx, gy = xx + gx0 - Cd[0] - t[0], yy + gy0 - Cd[1] - t[1]
    qx, qy = Ri[0, 0] * gx + Ri[0, 1] * gy, Ri[1, 0] * gx + Ri[1, 1] * gy
    inside = np.minimum(DIE_W / 2 - np.abs(qx), DIE_H / 2 - np.abs(qy))
    die = 0.5 * (1 + _erf(inside / (np.sqrt(2) * EDGE_SIGMA)))
    A = (BASE + DIE_STEP * die).astype(np.float32)
    # 基板錫球 (只在晶片外側)
    for bx in np.arange(np.floor(gx0 / BALL_PITCH) * BALL_PITCH, gx0 + W + BALL_PITCH, BALL_PITCH):
        for by in np.arange(np.floor(gy0 / BALL_PITCH) * BALL_PITCH, gy0 + H + BALL_PITCH, BALL_PITCH):
            q = Ri @ (np.array([bx, by]) - Cd - t)
            if abs(q[0]) < DIE_W / 2 + BALL_R * 2 and abs(q[1]) < DIE_H / 2 + BALL_R * 2:
                continue
            _disc(A, bx - gx0, by - gy0, BALL_R, 0.25)
    # 焊墊與凸塊：焊墊在基板名目格點；凸塊在晶片座標的同一點，經平移旋轉後的位置
    margin = 2 * PITCH
    nx, ny = int((DIE_W - 2 * margin) // PITCH), int((DIE_H - 2 * margin) // PITCH)
    for i in range(nx + 1):
        for j in range(ny + 1):
            # 陣列之間留走道 (每 12 格空 1 格)
            if i % 12 == 11 or j % 12 == 11:
                continue
            q = np.array([-DIE_W / 2 + margin + i * PITCH, -DIE_H / 2 + margin + j * PITCH])
            p = Cd + q                                            # 焊墊 (基板)
            if not (gx0 - 60 <= p[0] <= gx0 + W + 60 and gy0 - 60 <= p[1] <= gy0 + H + 60):
                continue
            b = Cd + t + R @ q                                     # 凸塊 (晶片)
            _disc(A, p[0] - gx0, p[1] - gy0, PAD_R, 0.04)
            _disc(A, b[0] - gx0, b[1] - gy0, BUMP_R, 0.14, dome=True)
    return cv2.GaussianBlur(A, (0, 0), 2.0)


def _erf(x):
    # numpy 沒有 erf；以 Abramowitz-Stegun 近似 (誤差 < 1.5e-7)
    s = np.sign(x)
    x = np.abs(x)
    t = 1 / (1 + 0.3275911 * x)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return s * y


def to_raw16(A, gain=1.0, noise=0.004, seed=0):
    I = 65535.0 * np.exp(-A) * gain
    I *= 1 + np.random.default_rng(seed).normal(0, noise, I.shape)
    return np.clip(I, 0, 65535).astype(np.uint16)


def corner_truth(pos, shift, theta_deg, die_center=(0.0, 0.0)):
    """角點的共同座標 (以晶片平台邊緣 50% 位置計)"""
    sx = -1 if "left" in pos else 1
    sy = -1 if "top" in pos else 1
    q = np.array([sx * DIE_W / 2, sy * DIE_H / 2])
    return np.asarray(die_center, float) + np.asarray(shift, float) + _rot(theta_deg) @ q


def views(shift=(0.0, 0.0), theta_deg=0.0, inset=(0.25, 0.25), interior=1):
    """
    標準拍攝位置：四個角 (角點約在視野內 inset 比例處) 與 interior 張晶片中間的視野。
    回傳 [(名稱, 角落位置或 None, 視野中心的共同座標)]
    """
    H, W = FOV
    out = []
    for pos in ("top_left", "top_right", "bottom_left", "bottom_right"):
        c = corner_truth(pos, (0, 0), 0)                   # 依名目位置安排拍攝位置 (實機也是如此)
        sx = 1 if "left" in pos else -1
        sy = 1 if "top" in pos else -1
        center = c + np.array([sx * (0.5 - inset[0]) * W, sy * (0.5 - inset[1]) * H])
        out.append((pos, pos, center))
    for k in range(interior):
        out.append((f"center{k + 1}", None, np.array([k * 400.0, 0.0])))
    return out


def make_set(out_dir, shift=(1.2, -0.8), theta_deg=0.01, gains=(1.0, 0.7, 1.3, 0.85, 1.1), seed=0, interior=1,
             pixel_size_um=2.0):
    """寫出一組影像、平台座標參數檔與正確答案 (truth.json)"""
    os.makedirs(out_dir, exist_ok=True)
    truth = dict(shift=list(shift), theta_deg=theta_deg, die_size_px=[DIE_W, DIE_H], pixel_size_um=pixel_size_um,
                 fov=list(FOV), images={})
    for k, (name, pos, center) in enumerate(views(shift, theta_deg, interior=interior)):
        A = render(center, shift, theta_deg, seed=seed + k)
        path = os.path.join(out_dir, f"{name}.tiff")
        cv2.imwrite(path, to_raw16(A, gain=gains[k % len(gains)], seed=seed + k))
        # 平台座標參數檔 (同名 .json)：µm
        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(dict(stage_x_um=round(center[0] * pixel_size_um, 3), stage_y_um=round(center[1] * pixel_size_um, 3)), f)
        info = dict(position=pos, center=[float(center[0]), float(center[1])])
        if pos:
            g = corner_truth(pos, shift, theta_deg)
            info["corner_px"] = [float(g[0] - center[0] + FOV[1] / 2), float(g[1] - center[1] + FOV[0] / 2)]
        truth["images"][name] = info
    with open(os.path.join(out_dir, "truth.json"), "w", encoding="utf-8") as f:
        json.dump(truth, f, ensure_ascii=False, indent=1)
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="產生合成晶片圖組")
    ap.add_argument("out")
    ap.add_argument("--dx", type=float, default=1.2)
    ap.add_argument("--dy", type=float, default=-0.8)
    ap.add_argument("--theta", type=float, default=0.01)
    a = ap.parse_args()
    print(json.dumps(make_set(a.out, (a.dx, a.dy), a.theta), ensure_ascii=False, indent=1))
