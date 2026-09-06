"""示範樣板的合成影像：每個樣板一組 PNG（含 1 張 NG 變體），寫到 data/samples/<key>/。

seed_demo 呼叫 write_all()：資料夾已有檔就略過（idempotent）；每組配一個 folder 影像來源
（群組「範例」、循環讀取），對應的示範流程開箱就能連續執行。
"""

from __future__ import annotations

import os

import cv2
import numpy as np
from django.conf import settings


def samples_root() -> str:
    configured = settings.VISION.get("SAMPLE_DIR")
    if configured:
        return str(configured)
    return os.path.join(os.path.dirname(str(settings.VISION["ASSET_DIR"])), "samples")


def _canvas(w: int, h: int, value: int = 40) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def _noise(img: np.ndarray, sigma: float = 4.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = img.astype(np.int16) + rng.normal(0, sigma, img.shape).astype(np.int16)
    return np.clip(out, 0, 255).astype(np.uint8)


def circle_part() -> list[np.ndarray]:
    """圓孔尺寸量測：亮板＋中央暗圓孔。孔半徑 175/176/174/190（最後一張超差 NG）。"""
    out = []
    for i, r in enumerate((175, 176, 174, 190)):
        img = _canvas(1280, 960, 30)
        cv2.rectangle(img, (140, 100), (1140, 860), (190, 190, 195), -1)
        cv2.circle(img, (640 + (i % 2) * 6 - 3, 480 + (i % 3) * 4 - 4), r, (35, 35, 38), -1)
        out.append(_noise(img, 4, i))
    return out


def l_bracket() -> list[np.ndarray]:
    """邊線夾角：L 形亮工件，兩條邊夾角 90/90.6/89.4/84（最後一張 NG）；底邊右下角 45° 斜切（倒角量測用）。"""
    out = []
    for i, ang in enumerate((90.0, 90.6, 89.4, 84.0)):
        img = _canvas(1280, 960, 35)
        base = np.array([[260, 700], [950, 700], [1020, 630], [1020, 560], [400, 560]], dtype=np.float64)
        # 垂直臂依角度傾斜
        theta = np.deg2rad(ang - 90.0)
        arm = np.array([[260, 700], [400, 700], [400 + 420 * np.sin(theta), 700 - 420 * np.cos(theta) - 0], [260 + 420 * np.sin(theta), 700 - 420 * np.cos(theta)]], dtype=np.float64)
        cv2.fillPoly(img, [np.round(base).astype(np.int32)], (200, 200, 205))
        cv2.fillPoly(img, [np.round(arm).astype(np.int32)], (200, 200, 205))
        out.append(_noise(img, 4, 10 + i))
    return out


def golden_print() -> list[np.ndarray]:
    """良品比對：固定印刷圖案；第 1 張＝良品範本，第 4 張多一塊污漬（NG）。"""
    out = []
    for i in range(4):
        img = _canvas(1280, 960, 225)
        cv2.rectangle(img, (200, 160), (1080, 800), (60, 70, 80), 6)
        cv2.circle(img, (420, 420), 120, (50, 60, 200), -1)
        cv2.rectangle(img, (640, 300), (960, 540), (70, 160, 60), -1)
        cv2.putText(img, "VS-100", (430, 700), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (40, 40, 40), 8)
        if i == 3:
            cv2.circle(img, (820, 640), 42, (30, 30, 30), -1)  # 污漬
        out.append(_noise(img, 3, 20 + i))
    return out


def textile() -> list[np.ndarray]:
    """頻域瑕疵：週期性織紋；第 4 張有一道斜向刮痕（NG）。"""
    out = []
    x = np.arange(1280)
    y = np.arange(960)
    for i in range(4):
        wave = 128 + 46 * np.sin(x * np.pi / 6 + i) + 20 * np.sin(y[:, None] * np.pi / 9)
        img = cv2.cvtColor(np.clip(wave, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
        if i == 3:
            cv2.line(img, (300, 200), (900, 760), (30, 30, 30), 7)
        out.append(_noise(img, 3, 30 + i))
    return out


def gradient_chart() -> list[np.ndarray]:
    """前處理與剖面教學圖：水平灰階漸層＋亮暗階梯＋一條暗溝（線剖面量得到）。"""
    out = []
    for i in range(3):
        ramp = np.tile(np.linspace(20, 235, 1280).astype(np.uint8), (960, 1))
        img = cv2.cvtColor(ramp, cv2.COLOR_GRAY2BGR)
        for k in range(6):  # 階梯
            cv2.rectangle(img, (80 + k * 190, 120), (80 + k * 190 + 150, 300), (int(30 + k * 40),) * 3, -1)
        cv2.rectangle(img, (100, 600 + i * 10), (1180, 640 + i * 10), (15, 15, 15), -1)  # 暗溝
        out.append(_noise(img, 2, 40 + i))
    return out


def multi_circles() -> list[np.ndarray]:
    """幾何工具：多個圓孔＋兩條斜線；第 4 張少一個圓（NG）。"""
    out = []
    centers = [(300, 300), (640, 260), (980, 320), (420, 640), (860, 660)]
    for i in range(4):
        img = _canvas(1280, 960, 200)
        use = centers if i != 3 else centers[:-1]
        for k, (cx, cy) in enumerate(use):
            cv2.circle(img, (cx + i * 2, cy), 70 + (k % 3) * 10, (45, 45, 50), -1)
        cv2.line(img, (100, 120), (1180, 150), (60, 60, 65), 9)
        cv2.line(img, (120, 880), (1160, 820), (60, 60, 65), 9)
        out.append(_noise(img, 4, 50 + i))
    return out


def gear(teeth: int = 12) -> list[np.ndarray]:
    """圓周齒數：暗底亮齒輪（齒根 r=260、齒頂 r=320、中心孔），12 齒；第 4 張缺一齒（NG）。極座標展開範本用。"""
    out = []
    for i in range(4):
        img = _canvas(1280, 960, 30)
        cx, cy = 640 + (i % 2) * 4 - 2, 480 + (i % 3) * 3 - 3
        cv2.circle(img, (cx, cy), 260, (200, 200, 205), -1)
        phase = i * 2.0  # 齒相位小幅變動（展開起始角 18° 落在齒隙，不會把一顆齒切成兩塊）
        for k in range(teeth):
            if i == 3 and k == 4:
                continue  # NG：缺一齒
            a = np.deg2rad(phase + k * 360.0 / teeth)
            half_root, half_tip = np.deg2rad(9.0), np.deg2rad(6.0)
            pts = np.array([
                [cx + 250 * np.cos(a - half_root), cy + 250 * np.sin(a - half_root)],
                [cx + 320 * np.cos(a - half_tip), cy + 320 * np.sin(a - half_tip)],
                [cx + 320 * np.cos(a + half_tip), cy + 320 * np.sin(a + half_tip)],
                [cx + 250 * np.cos(a + half_root), cy + 250 * np.sin(a + half_root)],
            ], dtype=np.float64)
            cv2.fillPoly(img, [np.round(pts).astype(np.int32)], (200, 200, 205))
        cv2.circle(img, (cx, cy), 60, (30, 30, 30), -1)
        out.append(_noise(img, 4, 70 + i))
    return out


def stamped_part() -> list[np.ndarray]:
    """輪廓幾何：暗底亮沖壓件（八角板＋4 個孔＋長槽），位置與角度小幅變動；第 4 張上緣被咬掉一塊（崩邊，凸缺陷深約 40 px，NG）。"""
    out = []
    for i in range(4):
        img = _canvas(1280, 960, 30)
        cx, cy = 640 + (i % 2) * 6 - 3, 480 + (i % 3) * 4 - 4
        rot = np.deg2rad((i - 1.5) * 1.2)
        base = np.array([[-350, -210], [-290, -270], [290, -270], [350, -210], [350, 210], [290, 270], [-290, 270], [-350, 210]], dtype=np.float64)
        if i == 3:
            # 上緣中段咬掉一個三角（崩邊）
            base = np.array([[-350, -210], [-290, -270], [-40, -270], [0, -230], [40, -270], [290, -270], [350, -210], [350, 210], [290, 270], [-290, 270], [-350, 210]], dtype=np.float64)
        m = np.array([[np.cos(rot), -np.sin(rot)], [np.sin(rot), np.cos(rot)]])
        pts = base @ m.T + np.array([cx, cy])
        cv2.fillPoly(img, [np.round(pts).astype(np.int32)], (200, 200, 205))
        for hx, hy in ((-260, -160), (260, -160), (-260, 160), (260, 160)):
            px, py = (np.array([hx, hy]) @ m.T) + np.array([cx, cy])
            cv2.circle(img, (int(round(px)), int(round(py))), 38, (30, 30, 30), -1)
        slot = np.array([[-120, -25], [120, -25], [120, 25], [-120, 25]], dtype=np.float64) @ m.T + np.array([cx, cy])
        cv2.fillPoly(img, [np.round(slot).astype(np.int32)], (30, 30, 30))
        out.append(_noise(img, 4, 90 + i))
    return out


def color_blocks() -> list[np.ndarray]:
    """顏色檢驗：左＝目標紅色塊、中＝綠、右＝藍；第 4 張紅色偏橘（NG）。"""
    out = []
    for i in range(4):
        img = _canvas(1280, 960, 210)
        red = (40, 40, 210) if i != 3 else (40, 130, 220)
        cv2.rectangle(img, (120, 300), (420, 660), red, -1)
        cv2.rectangle(img, (500, 300), (800, 660), (60, 170, 60), -1)
        cv2.rectangle(img, (880, 300), (1180, 660), (190, 90, 40), -1)
        out.append(_noise(img, 3, 60 + i))
    return out


def label_qr() -> list[np.ndarray]:
    """條碼標籤：傾斜貼的標籤上有 QR；第 4 張沒有碼（NG）。四個標籤角點固定，供透視校正示範。"""
    try:
        enc = cv2.QRCodeEncoder.create()
        qr = enc.encode("VS-DEMO-0001")
    except Exception:  # noqa: BLE001 - 環境沒有 QR 編碼器就用棋盤替代（barcode 會 NG，但流程可跑）
        qr = ((np.indices((21, 21)).sum(axis=0) % 2) * 255).astype(np.uint8)
    qr = cv2.resize(qr, (300, 300), interpolation=cv2.INTER_NEAREST)
    out = []
    src = np.array([[0, 0], [560, 0], [560, 420], [0, 420]], dtype=np.float32)
    dst = np.array([[330, 240], [940, 300], [900, 720], [290, 660]], dtype=np.float32)  # 固定角點
    for i in range(4):
        label = np.full((420, 560, 3), 245, dtype=np.uint8)
        cv2.rectangle(label, (0, 0), (559, 419), (120, 120, 120), 4)
        if i != 3:
            label[60:360, 130:430] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        cv2.putText(label, "SN 0001", (150, 405), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (60, 60, 60), 3)
        img = _canvas(1280, 960, 70)
        matrix = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(label, matrix, (1280, 960), borderValue=(70, 70, 70))
        mask = cv2.warpPerspective(np.full((420, 560), 255, np.uint8), matrix, (1280, 960))
        img[mask > 0] = warped[mask > 0]
        out.append(_noise(img, 3, 70 + i))
    return out


def cup() -> list[np.ndarray]:
    """杯件量測：同心圓杯口（外徑 700、內徑 520、右側壁厚剖面）＋左上十字定位標記。
    第 4 張外徑偏大（NG）。標稱值對齊 cup_measure_flow 的公差設定。"""
    out = []
    for i, od in enumerate((350, 351, 349, 360)):
        img = _canvas(1280, 960, 50)
        c = (640 + (i % 2) * 4 - 2, 480 + (i % 2) * 3)
        cv2.circle(img, c, od, (185, 185, 190), -1)  # 杯口環外
        cv2.circle(img, c, 260, (70, 70, 75), -1)  # 內腔
        # 右側壁厚剖面帶（wall_roi 在 x≈960）
        cv2.rectangle(img, (c[0] + 260, c[1] - 60), (c[0] + od, c[1] + 60), (185, 185, 190), -1)
        # 定位十字標記（範本）
        mx, my = 200 + (i % 2) * 4, 170 + (i % 3) * 3
        cv2.line(img, (mx - 45, my), (mx + 45, my), (250, 250, 250), 9)
        cv2.line(img, (mx, my - 45), (mx, my + 45), (250, 250, 250), 9)
        out.append(_noise(img, 3, 80 + i))
    return out


def marker_plate() -> list[np.ndarray]:
    """定位＋卡尺：板上左上十字標記＋中央一條亮橫帶（量寬度）。第 4 張帶較寬（NG）。"""
    out = []
    for i, band in enumerate((160, 162, 158, 200)):
        img = _canvas(1280, 960, 45)
        cv2.rectangle(img, (120, 90), (1160, 870), (120, 120, 125), -1)
        mx, my = 260 + (i % 2) * 6, 220 + (i % 3) * 4
        cv2.line(img, (mx - 50, my), (mx + 50, my), (245, 245, 245), 10)
        cv2.line(img, (mx, my - 50), (mx, my + 50), (245, 245, 245), 10)
        cv2.rectangle(img, (340, 480 - band // 2), (1040, 480 + band // 2), (230, 230, 235), -1)
        out.append(_noise(img, 3, 90 + i))
    return out


def _stop_sign(img: np.ndarray, cx: int, cy: int, r: int) -> None:
    """紅色八角形＋白字 STOP：COCO 底模（yolo11n）對這種合成標誌信心 0.9 以上，拿來示範不用訓練的 YOLO 工具。"""
    pts = np.array([(int(cx + r * np.cos(np.deg2rad(22.5 + 45 * i))), int(cy + r * np.sin(np.deg2rad(22.5 + 45 * i)))) for i in range(8)])
    cv2.fillPoly(img, [pts], (30, 30, 200))
    cv2.polylines(img, [pts], True, (255, 255, 255), max(2, r // 18))
    scale = r / 50.0
    (tw, th), _ = cv2.getTextSize("STOP", cv2.FONT_HERSHEY_SIMPLEX, scale, max(2, int(3 * scale)))
    cv2.putText(img, "STOP", (int(cx - tw / 2), int(cy + th / 2)), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), max(2, int(3 * scale)))


def stop_signs() -> list[np.ndarray]:
    """YOLO 物件計數／實例分割：每張應有 2 個停止標誌；第 4 張只有 1 個、第 5 張有 3 個（NG）。"""
    specs = [
        [(160, 240, 70), (470, 240, 70)],
        [(140, 200, 55), (500, 280, 85)],
        [(200, 300, 90), (480, 160, 60)],
        [(320, 240, 45)],
        [(120, 130, 80), (330, 260, 85), (540, 380, 75)],
    ]
    out = []
    for i, spec in enumerate(specs):
        img = np.full((480, 640, 3), (200, 205, 210), np.uint8)
        for cx, cy, r in spec:
            _stop_sign(img, cx, cy, r)
        out.append(_noise(img, 3, i))
    return out


def _disc_part(seed: int, missing_hole: bool) -> np.ndarray:
    """分類教導：暗底亮圓盤零件（治具固定、位置 ±8 px）；NG 版少了中央孔。
    內建 MLP 分類器吃的是整張縮圖的像素，適合這種「整體外觀不同」的類別；位置隨機的細刮痕請改用語意分割或 YOLO。"""
    rng = np.random.default_rng(seed)
    img = _canvas(320, 320, 35)
    cx, cy = 160 + int(rng.integers(-8, 9)), 160 + int(rng.integers(-8, 9))
    cv2.circle(img, (cx, cy), 110, (205, 205, 208), -1)
    if not missing_hole:
        cv2.circle(img, (cx, cy), 28, (60, 60, 62), -1)
    return _noise(img, 3, seed)


def dl_parts() -> list[np.ndarray]:
    """DL 分類範本的樣本圖：4 張良品（有中央孔）、2 張缺孔（NG）。"""
    return [_disc_part(100 + i, missing_hole=i >= 4) for i in range(6)]


def dl_parts_labeled(n_per_class: int = 15) -> list[tuple[np.ndarray, str]]:
    """seed 用來訓練示範分類模型的標記資料（與樣本圖不同 seed，避免「背答案」）。"""
    return [(_disc_part(1000 + i, False), "ok") for i in range(n_per_class)] + [(_disc_part(2000 + i, True), "ng") for i in range(n_per_class)]


def _scratch_plate(seed: int, n_scratch: int) -> tuple[np.ndarray, list[dict]]:
    """分割教導：紋理鋁板＋ n 道暗刮痕；回 (影像, shapes[polygon，0~1 正規化])。"""
    rng = np.random.default_rng(seed)
    base = np.full((320, 320, 3), 150, np.uint8)
    tex = rng.normal(0, 9, (320, 320, 1)).astype(np.int16)
    img = np.clip(base.astype(np.int16) + tex, 0, 255).astype(np.uint8)
    shapes = []
    for _ in range(n_scratch):
        cx, cy = int(rng.integers(70, 250)), int(rng.integers(70, 250))
        length, thick = int(rng.integers(70, 140)), int(rng.integers(6, 10))
        ang = float(rng.uniform(0, 180))
        box = cv2.boxPoints(((float(cx), float(cy)), (float(length), float(thick)), ang)).astype(np.int32)
        cv2.fillPoly(img, [box], (58, 58, 60))
        shapes.append({"label": "scratch", "kind": "polygon", "points": [[float(np.clip(x / 320, 0, 1)), float(np.clip(y / 320, 0, 1))] for x, y in box]})
    return _noise(img, 2, seed), shapes


def dl_scratch() -> list[np.ndarray]:
    """DL 語意分割範本的樣本圖：3 張乾淨、2 張有刮痕（NG）。"""
    return [_scratch_plate(300 + i, 0 if i < 3 else (1 if i == 3 else 2))[0] for i in range(5)]


def dl_scratch_labeled(n: int = 10) -> list[tuple[np.ndarray, list[dict]]]:
    """seed 用來訓練示範分割模型的標記資料：每張 1～2 道刮痕。"""
    return [_scratch_plate(3000 + i, 1 + i % 2) for i in range(n)]


#: key → (顯示名, 產生器)。key 同時是 data/samples/ 下的資料夾名。
SAMPLE_SETS: dict[str, tuple[str, callable]] = {
    "circle_part": ("circle gauge", circle_part),
    "l_bracket": ("edge angle", l_bracket),
    "golden_print": ("print compare", golden_print),
    "textile": ("fabric defect", textile),
    "gradient_chart": ("preprocessing lab", gradient_chart),
    "multi_circles": ("circles and lines", multi_circles),
    "gear": ("gear teeth", gear),
    "stamped_part": ("stamped part", stamped_part),
    "color_blocks": ("colour blocks", color_blocks),
    "label_qr": ("barcode label", label_qr),
    "cup": ("cup gauge", cup),
    "marker_plate": ("locate and gauge", marker_plate),
    "stop_signs": ("stop sign", stop_signs),
    "dl_parts": ("classification teaching", dl_parts),
    "dl_scratch": ("segmentation teaching", dl_scratch),
}


def write_set(key: str) -> str:
    """產生一組樣本圖（已存在就沿用），回傳資料夾路徑。"""
    folder = os.path.join(samples_root(), key)
    os.makedirs(folder, exist_ok=True)
    if any(name.endswith(".png") for name in os.listdir(folder)):
        return folder
    _, maker = SAMPLE_SETS[key]
    for i, img in enumerate(maker(), start=1):
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(os.path.join(folder, f"{i:02d}.png"))
    return folder
