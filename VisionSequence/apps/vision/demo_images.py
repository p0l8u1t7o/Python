"""示範樣板的合成影像：每個樣板一組 PNG（含 1 張 NG 變體），寫到 data/samples/<key>/。

每個內建範本都對應一組（`demo.TEMPLATE_SAMPLE_SOURCES`），圖存成固定影像跟著範本走：
範本畫廊載入後第一個節點就是帶著這些圖的「固定影像」，不必先建影像來源。
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


def golden_print_variants(n: int = 30) -> list[np.ndarray]:
    """統計範本的建模樣本：印刷良品（golden_print 第 1 張的圖案）加整張亮度擾動 ±8、位移 ±3、雜訊，n 張。"""
    base = golden_print()[0]
    out = []
    for i in range(n):
        r = np.random.default_rng(500 + i)
        m = np.array([[1, 0, int(r.integers(-3, 4))], [0, 1, int(r.integers(-3, 4))]], np.float32)
        img = cv2.warpAffine(base, m, (base.shape[1], base.shape[0]), borderMode=cv2.BORDER_REPLICATE)
        img = np.clip(img.astype(np.int16) + int(r.integers(-8, 9)), 0, 255).astype(np.uint8)
        out.append(_noise(img, 3, 600 + i))
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


def brushed_surface() -> list[np.ndarray]:
    """表面缺陷濾波：拉絲金屬面（**沒有週期性**，所以頻域那一招無效）；第 4 張有一道細刮傷（NG）。

    與「織紋瑕疵」刻意配成一對：織紋是規則的，低通就濾掉了；拉絲面是隨機的，
    只能靠「沿著缺陷平均、跨著缺陷微分」把細長的東西挑出來。
    """
    out = []
    for i in range(4):
        rng = np.random.default_rng(700 + i)
        base = np.full((960, 1280), 175.0, np.float32)
        base += rng.normal(0, 16, base.shape).astype(np.float32)
        base = cv2.GaussianBlur(base, (61, 3), 0)          # 沿 x 拉長 → 拉絲紋理
        base += rng.normal(0, 4, base.shape).astype(np.float32)
        img = np.clip(base, 0, 255).astype(np.uint8)
        if i == 3:
            cv2.line(img, (280, 240), (980, 700), 120, 3)  # 細刮傷：比表面暗一點點
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        out.append(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
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


def _vignette_field(w: int = 1280, h: int = 960, strength: float = 0.55) -> np.ndarray:
    """徑向漸暈係數（中心 1、角落 1−strength），模擬打光不均。"""
    yy, xx = np.mgrid[0:h, 0:w]
    return 1.0 - strength * (((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / ((w / 2) ** 2 + (h / 2) ** 2))


def vignette_flat() -> np.ndarray:
    """白板參考影像：均勻白板在同一組打光下拍的樣子（只有漸暈）。seed 存成資產給平場校正範本。"""
    return np.clip(_vignette_field() * 235, 0, 255).astype(np.uint8)


def vignette_parts() -> list[np.ndarray]:
    """平場校正：亮板上有 6 顆暗污點分布到角落，整張套強漸暈（角落只剩 45% 亮度）；第 4 張多一大塊污漬（NG）。
    不校正時角落整片低於門檻、污點數不對；校正後每張的 6 顆（第 4 張 7 顆）都數得出來。"""
    out = []
    field = _vignette_field()
    spots = [(140, 120), (1140, 130), (640, 480), (150, 840), (1130, 830), (640, 150)]
    for i in range(4):
        base = np.full((960, 1280), 200, np.float64)
        for k, (sx, sy) in enumerate(spots):
            cv2.circle(base, (sx + (i % 2) * 5, sy + (i % 3) * 4), 22 + (k % 3) * 4, 60, -1)
        if i == 3:
            cv2.circle(base, (400, 700), 45, 60, -1)
        img = np.clip(base * field, 0, 255).astype(np.uint8)
        out.append(_noise(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 4, 110 + i))
    return out


def _bracket(img: np.ndarray, cx: float, cy: float, angle: float, bright: float = 1.0) -> None:
    """形狀比對的示範工件：不對稱五邊形亮件＋偏心暗孔；角度為畫面順時針。"""
    base = np.array([[-110, -80], [110, -80], [110, 30], [40, 80], [-110, 80]], np.float64)
    t = np.deg2rad(angle)
    r = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    poly = (base @ r.T + [cx, cy]).round().astype(np.int32)
    cv2.fillPoly(img, [poly], (int(205 * bright), int(200 * bright), int(200 * bright)))
    hole = np.array([-40.0, -15.0]) @ r.T + [cx, cy]
    cv2.circle(img, (int(round(hole[0])), int(round(hole[1]))), 24, (int(70 * bright), int(70 * bright), int(75 * bright)), -1)


def shape_parts() -> list[np.ndarray]:
    """形狀比對：第 1 張正放（建模用）、第 2 張轉 37° 且變暗 0.6、第 3 張轉 −120° 加雜物、第 4 張換成別的零件（找不到 → NG）。"""
    out = []
    img = _canvas(1280, 960, 45)
    _bracket(img, 640, 480, 0)
    out.append(_noise(img, 4, 130))
    img = _canvas(1280, 960, 45)
    _bracket(img, 780, 520, 37, bright=0.6)
    out.append(_noise(img, 4, 131))
    img = _canvas(1280, 960, 45)
    _bracket(img, 520, 430, -120)
    rng = np.random.default_rng(7)
    for _ in range(25):
        x, y = rng.integers(40, 1200), rng.integers(40, 900)
        cv2.rectangle(img, (int(x), int(y)), (int(x) + 34, int(y) + 34), (175, 170, 170), -1)
    out.append(_noise(img, 4, 132))
    img = _canvas(1280, 960, 45)
    cv2.circle(img, (640, 480), 120, (205, 200, 200), -1)  # 別的零件：圓盤
    cv2.circle(img, (600, 465), 24, (70, 70, 75), -1)
    out.append(_noise(img, 4, 133))
    return out


def chipped_disc() -> list[np.ndarray]:
    """圓形工件崩邊：暗底亮圓盤（r=300），中心小孔；第 4 張右下緣有一個 24°×7 px 的缺口（NG）。圓形卡尺範本用。"""
    out = []
    for i in range(4):
        img = _canvas(1280, 960, 40)
        cx, cy = 640 + (i % 2) * 5 - 2, 480 + (i % 3) * 4 - 4
        cv2.circle(img, (cx, cy), 300, (200, 200, 205), -1)
        cv2.circle(img, (cx, cy), 40, (40, 40, 40), -1)
        if i == 3:
            a0, a1 = np.deg2rad(40 - 12), np.deg2rad(40 + 12)
            inner = [(cx + 293 * np.cos(a), cy + 293 * np.sin(a)) for a in np.linspace(a0, a1, 14)]
            outer = [(cx + 330 * np.cos(a), cy + 330 * np.sin(a)) for a in np.linspace(a1, a0, 14)]
            cv2.fillPoly(img, [np.round(np.array(inner + outer)).astype(np.int32)], (40, 40, 40))
        out.append(_noise(img, 4, 150 + i))
    return out


EMBOSS_DENT_ZONE = {"shape": "rect", "x": 380, "y": 60, "w": 200, "h": 170}


def emboss_quad() -> list[np.ndarray]:
    """刻印字／凹凸缺陷（光度立體）：每張 1280×960 是同一塊板在四個方向打光下的 2×2 拼圖（左上＝光 1 自右、右上＝光 2 自下、
    左下＝光 3 自左、右下＝光 4 自上，各 640×480）。板面反射率有斑駁（四張相同，單張二值化抓不到字），只有高度差：
    浮凸「VS 42」6 px；第 4 張右上角區多一個凹坑（NG）。用 photometric_stereo 的 shape strength 抓凹坑。"""
    from apps.vision.tools.builtin.photometric import light_directions

    out = []
    qw, qh = 640, 480
    lights = light_directions([0, 90, 180, 270], 30)
    for i in range(4):
        rng = np.random.default_rng(700 + i)
        mask = np.zeros((qh, qw), np.uint8)
        cv2.putText(mask, "VS 42", (60, 400), cv2.FONT_HERSHEY_SIMPLEX, 5, 255, 24)
        height = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 3) * 6.0
        if i == 3:
            yy, xx = np.mgrid[0:qh, 0:qw].astype(np.float32)
            height -= 5.0 * np.exp(-((xx - 480) ** 2 + (yy - 145) ** 2) / (2 * 14.0**2))
        gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
        gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
        nrm = np.dstack([-gx, -gy, np.ones_like(gx)])
        nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
        albedo = cv2.GaussianBlur(rng.normal(0, 22, (qh, qw)).astype(np.float32), (0, 0), 2) + 175.0
        tiles = []
        for k in range(4):
            shade = np.clip(nrm @ lights[k], 0, None)
            img = np.clip(albedo * shade + 8 + rng.normal(0, 2, (qh, qw)), 0, 255).astype(np.uint8)
            tiles.append(img)
        quad = np.vstack([np.hstack(tiles[0:2]), np.hstack(tiles[2:4])])
        out.append(cv2.cvtColor(quad, cv2.COLOR_GRAY2BGR))
    return out


BARCODE_GRADE_ROI = {"shape": "rect", "x": 380, "y": 260, "w": 520, "h": 440}


def _datamatrix_bitmap(text: str) -> np.ndarray:
    """zxing 產 Data Matrix 位圖（0/255，含 1 模組靜區）；沒有 zxing 就用棋盤替代（解不出來→分級 F，流程仍可跑）。"""
    try:
        import zxingcpp

        return np.array(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.DataMatrix, text, quiet_zone=1))
    except Exception:  # noqa: BLE001
        board = np.indices((14, 14)).sum(axis=0) % 2
        return (board * 255).astype(np.uint8)


def barcode_grades() -> list[np.ndarray]:
    """條碼品質分級：白標籤上一個 Data Matrix（模組 14 px），四張品質遞減——1 乾淨（A）、2 對比偏低（B）、3 對比低＋模糊＋雜訊（C）、
    4 四個散開的墨點翻轉了四格＋靜區污漬（D，NG）。符號是 8×32 的長方形 Data Matrix；標籤上另有一行料號文字當背景。"""
    out = []
    bitmap = _datamatrix_bitmap("VS-SN-000123")
    module = 14
    sym = np.kron(bitmap, np.ones((module, module), np.uint8))
    for i in range(4):
        rng = np.random.default_rng(900 + i)
        img = _canvas(1280, 960, 70)
        cv2.rectangle(img, (400, 280), (880, 680), (238, 238, 236), -1)  # 標籤
        cv2.putText(img, "VS-SN-000123", (430, 650), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 40, 40), 2)
        label = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        x0, y0 = 640 - sym.shape[1] // 2, 460 - sym.shape[0] // 2
        patch_ = sym.astype(np.float32)
        lo, hi = {0: (10, 238), 1: (72, 235), 2: (100, 215), 3: (10, 238)}[i]
        patch_ = lo + patch_ / 255.0 * (hi - lo)
        if i == 2:
            patch_ = cv2.GaussianBlur(patch_, (0, 0), 2.2)
        region = label[y0:y0 + sym.shape[0], x0:x0 + sym.shape[1]].astype(np.float32)
        region[:] = np.where(sym.reshape(sym.shape) >= 0, patch_, region)
        if i == 3:
            for r_, c_ in ((2, 5), (4, 11), (6, 19), (3, 27)):  # 四個散開的墨點／針孔：各翻一格（四個碼字錯）
                blk = patch_[module * r_:module * (r_ + 1), module * c_:module * (c_ + 1)]
                blk[:] = 248 - blk
            cv2.rectangle(patch_, (2, module * 2), (module - 4, module * 6), 30, -1)              # 靜區污漬
            region[:] = patch_
        label[y0:y0 + sym.shape[0], x0:x0 + sym.shape[1]] = np.clip(region, 0, 255).astype(np.uint8)
        noise_sigma = {0: 2, 1: 4, 2: 9, 3: 3}[i]
        label = np.clip(label.astype(np.float32) + rng.normal(0, noise_sigma, label.shape), 0, 255).astype(np.uint8)
        out.append(cv2.cvtColor(label, cv2.COLOR_GRAY2BGR))
    return out


def _date_code_font(size: int = 40):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def _render_code(text: str, w: int = 520, h: int = 110, size: int = 44) -> np.ndarray:
    """PIL 內建 TrueType 字型渲染一行字（暗字亮底）。"""
    from PIL import Image, ImageDraw

    font = _date_code_font(size)
    img = Image.new("L", (w, h), 232)
    d = ImageDraw.Draw(img)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((w - tw) // 2 - bb[0], (h - th) // 2 - bb[1]), text, fill=28, font=font)
    return np.array(img)


def date_codes() -> list[np.ndarray]:
    """日期碼標籤：白標籤上一行 8 位數字（噴印風格）；第 4 張第 4 個字被污點蓋住一半（讀錯 → NG）。"""
    out = []
    codes = ["24091201", "24091202", "24091203", "24091204"]
    for i, code in enumerate(codes):
        img = _canvas(1280, 960, 70)
        cv2.rectangle(img, (240, 300), (1040, 660), (225, 225, 228), -1)
        line = _render_code(code)
        y0, x0 = 430 + (i % 2) * 6, 380 + (i % 3) * 5
        img[y0 : y0 + line.shape[0], x0 : x0 + line.shape[1]] = cv2.cvtColor(line, cv2.COLOR_GRAY2BGR)
        if i == 3:
            cv2.circle(img, (x0 + 235, y0 + 40), 16, (60, 60, 65), -1)  # 污點蓋住第 4 個字
        out.append(_noise(img, 3, 170 + i))
    return out


def date_code_lines(n: int = 24) -> list[tuple[np.ndarray, str]]:
    """seed 教字型用的行影像：隨機 8 位數字（同一個 PIL 字型）。"""
    rng = np.random.default_rng(77)
    return [(_render_code("".join(rng.choice(list("0123456789"), 8)), w=400, h=80, size=36), None) for _ in range(n)]


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


def _hole_plate(seed: int, angle: float, holes: int = 5, scratch: bool = False, plate: int = 200, back: int = 70) -> np.ndarray:
    """孔數／曝光範本共用的板件：暗底上一塊亮板，四角＋中央共 5 個暗孔，另有打印的批號（細筆畫，開運算會濾掉）。
    `holes=4` 少一個角孔（孔數 NG）；`plate`／`back` 調整曝光（曝光範本用）。"""
    w, h = 1280, 960
    img = _canvas(w, h, back)
    cx, cy = w / 2, h / 2
    rect = ((cx, cy), (w * 0.52, h * 0.44), angle)
    cv2.fillPoly(img, [np.round(cv2.boxPoints(rect)).astype(np.int32)], (plate, plate, plate + 5))
    m = cv2.getRotationMatrix2D((cx, cy), -angle, 1.0)

    def at(ox: float, oy: float) -> tuple[int, int]:
        p = m @ np.array([cx + ox, cy + oy, 1.0])
        return int(round(p[0])), int(round(p[1]))

    dark = max(0, min(plate, back) - 30)
    for i, (ox, oy) in enumerate(((-w * 0.18, -h * 0.13), (w * 0.18, -h * 0.13), (-w * 0.18, h * 0.13), (w * 0.18, h * 0.13))):
        if holes < 5 and i == 2:
            continue
        cv2.circle(img, at(ox, oy), 34, (dark, dark, dark + 3), -1)
    cv2.circle(img, at(0, 0), 76, (dark, dark, dark + 3), -1)
    cv2.putText(img, f"LOT {seed:05d}", at(-w * 0.09, h * 0.18), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (dark, dark, dark), 2)
    if scratch:
        # 刮痕畫在板面空白處：不能穿過孔（會把孔切成兩半而少算一個）
        cv2.line(img, at(w * 0.10, -h * 0.05), at(w * 0.15, -h * 0.01), (min(255, plate + 40),) * 3, 3)
    return _noise(img, 4, seed)


def plate_holes() -> list[np.ndarray]:
    """孔數檢測：亮板上 5 個暗孔（四角＋中央），位置與角度略有變化；第 4 張少一個孔（NG）。"""
    return [
        _hole_plate(1, 0.0),
        _hole_plate(2, 5.0),
        _hole_plate(3, -6.0, scratch=True),
        _hole_plate(4, 3.0, holes=4),
    ]


def exposure_frames() -> list[np.ndarray]:
    """曝光檢查：同一塊板在四種曝光下的 Otsu 門檻約 135／70／180／238；第 4 張過曝（NG）。"""
    return [
        _hole_plate(11, 0.0),
        _hole_plate(12, 2.0, plate=110, back=30),
        _hole_plate(13, -3.0, plate=240, back=120),
        _hole_plate(14, 1.0, plate=252, back=225),
    ]


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


def dl_clean_plates(n: int = 20) -> list[tuple[np.ndarray, str]]:
    """seed 用來訓練示範異常檢測模型的良品（沒有刮痕的紋理鋁板），與樣本圖不同 seed。"""
    return [(_scratch_plate(5000 + i, 0)[0], "") for i in range(n)]


def dl_scratch() -> list[np.ndarray]:
    """DL 語意分割範本的樣本圖：3 張乾淨、2 張有刮痕（NG）。"""
    return [_scratch_plate(300 + i, 0 if i < 3 else (1 if i == 3 else 2))[0] for i in range(5)]


def dl_scratch_labeled(n: int = 10) -> list[tuple[np.ndarray, list[dict]]]:
    """seed 用來訓練示範分割模型的標記資料：每張 1～2 道刮痕。"""
    return [_scratch_plate(3000 + i, 1 + i % 2) for i in range(n)]


def ai_classifier_gate_parts() -> list[np.ndarray]:
    """Small product-card pictures used to demonstrate stock classification routing."""
    out = []
    colours = [(64, 126, 216), (72, 176, 96), (202, 136, 58), (118, 82, 188)]
    for i, colour in enumerate(colours):
        img = _canvas(360, 260, 205)
        cv2.rectangle(img, (46, 42), (314, 218), (236, 238, 240), -1)
        cv2.rectangle(img, (46, 42), (314, 218), (52, 56, 62), 2)
        cv2.circle(img, (126, 132), 42, colour, -1)
        cv2.rectangle(img, (196, 91), (272, 173), tuple(max(0, int(c) - 34) for c in colour), -1)
        cv2.putText(img, f"G{i + 1}", (92, 224), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (58, 62, 68), 2)
        out.append(_noise(img, 2, 6200 + i))
    return out


def ai_tilted_parts() -> list[np.ndarray]:
    """Tilted synthetic parts for the oriented-box stock-model wiring template."""
    out = []
    specs = [(0, 0), (12, -16), (-18, 10), (26, 22)]
    for i, (angle, dx) in enumerate(specs):
        img = _canvas(480, 320, 44)
        rect = ((240.0 + dx, 160.0), (210.0, 82.0), float(angle))
        box = np.round(cv2.boxPoints(rect)).astype(np.int32)
        cv2.fillPoly(img, [box], (204, 210, 214))
        cv2.polylines(img, [box], True, (52, 56, 62), 3)
        cv2.line(img, tuple(box[0]), tuple(box[2]), (78, 82, 88), 2)
        out.append(_noise(img, 3, 6300 + i))
    return out


def ai_pose_parts() -> list[np.ndarray]:
    """Stick-figure-like samples; stock pose models may not recognise them."""
    out = []
    for i in range(4):
        img = _canvas(320, 440, 226)
        cx = 160 + (i - 1) * 8
        cv2.circle(img, (cx, 88), 28, (82, 86, 92), 3)
        cv2.line(img, (cx, 118), (cx, 245), (82, 86, 92), 6)
        cv2.line(img, (cx, 150), (cx - 74, 202), (82, 86, 92), 5)
        cv2.line(img, (cx, 150), (cx + 74, 202), (82, 86, 92), 5)
        cv2.line(img, (cx, 245), (cx - 54, 346), (82, 86, 92), 6)
        cv2.line(img, (cx, 245), (cx + 58, 346), (82, 86, 92), 6)
        if i == 3:
            cv2.rectangle(img, (82, 128), (238, 310), (226, 226, 226), -1)
        out.append(_noise(img, 2, 6400 + i))
    return out


def _retrieval_part(label: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = _canvas(224, 224, 46)
    jitter = int(rng.integers(-5, 6))
    if label == "part_a":
        cv2.circle(img, (112 + jitter, 112), 58, (54, 116, 222), -1)
        cv2.circle(img, (112 + jitter, 112), 20, (235, 238, 242), -1)
    elif label == "part_b":
        cv2.rectangle(img, (58 + jitter, 58), (166 + jitter, 166), (82, 190, 92), -1)
        cv2.line(img, (80 + jitter, 80), (144 + jitter, 144), (235, 238, 242), 9)
    elif label == "part_c":
        pts = np.array([[112 + jitter, 42], [184 + jitter, 174], [40 + jitter, 174]], dtype=np.int32)
        cv2.fillPoly(img, [pts], (216, 144, 58))
        cv2.rectangle(img, (86 + jitter, 128), (138 + jitter, 146), (235, 238, 242), -1)
    else:
        for x in range(34, 190, 24):
            cv2.line(img, (x, 38), (x + 42, 186), (152, 92, 190), 8)
    return _noise(img, 2, seed)


def retrieval_library_labeled() -> list[tuple[np.ndarray, str]]:
    """Three classes, two references per class, for the demo retrieval library asset."""
    return [
        (_retrieval_part(label, seed), label)
        for label, seeds in (("part_a", (6500, 6501)), ("part_b", (6510, 6511)), ("part_c", (6520, 6521)))
        for seed in seeds
    ]


def retrieval_query_parts() -> list[np.ndarray]:
    """Three known part_a queries and one unrelated part for the not_matched branch."""
    return [_retrieval_part("part_a", seed) for seed in (6500, 6501, 6500)] + [_retrieval_part("unknown", 6530)]


def _multi_light_frames(seed: int, scratch: bool) -> list[np.ndarray]:
    """同一表面四個打光方向（0°／90°／180°／270°）的 300×200 灰階幀；scratch 時 270° 幀多一道刮痕。"""
    h, w = 200, 300
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.full((h, w), 142.0, np.float32)
    base += 5.0 * np.sin(xx / 19.0) + 3.0 * np.sin(yy / 23.0)
    bump = np.exp(-(((xx - 150.0) / 62.0) ** 2 + ((yy - 100.0) / 36.0) ** 2))
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    out = []
    for i, (dx, dy) in enumerate(dirs):
        shade = base + 28.0 * bump * (0.55 + 0.45 * (dx * (xx - 150.0) / 62.0 + dy * (yy - 100.0) / 36.0))
        img = np.clip(shade, 0, 255).astype(np.uint8)
        if scratch and i == 3:
            cv2.line(img, (84, 138), (226, 62), 238, 4, cv2.LINE_AA)
            cv2.line(img, (84, 142), (226, 66), 54, 2, cv2.LINE_AA)
        out.append(_noise(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 1.5, seed + i))
    return out


def multi_light_surface() -> list[np.ndarray]:
    """多光源表面缺陷：每張樣本是同一工件四個打光方向的 2×2 拼圖（左上 0°、右上 90°、左下 180°、右下 270°），
    範本把四格裁出來再融合；前三張乾淨，第四張的 270° 幀有一道刮痕。"""
    out = []
    for i in range(4):
        f = _multi_light_frames(6600 + i * 10, scratch=(i == 3))
        out.append(np.vstack([np.hstack([f[0], f[1]]), np.hstack([f[2], f[3]])]))
    return out

def registered_parts() -> list[np.ndarray]:
    """註冊計數：三張各三個帶孔方塊，第四張缺一個；留背景邊界供裁切註冊。"""
    out = []
    for i, (dx, dy) in enumerate([(0, 0), (16, 12), (-16, 24), (0, 0)]):
        image = np.full((480, 640, 3), 30, np.uint8)
        for x, y in [(64, 48), (256, 48), (64, 240)][:2 if i == 3 else 3]:
            x, y = x + dx, y + dy
            image[y + 16:y + 80, x + 16:x + 80] = (210, 220, 230)
            cv2.circle(image, (x + 48, y + 48), 12, (30, 30, 30), -1)
        out.append(image)
    return out


def conveyor_sequence() -> list[np.ndarray]:
    """輸送帶追蹤取料：同一組物體沿 y 方向前進；第 1 張碰上邊、最後一張碰下邊。"""
    out = []
    objects = [(-85, 34, 74, 46, (70, 170, 225)), (-15, 30, 58, 58, (210, 190, 80)), (58, 36, 86, 42, (100, 205, 120))]
    for i, y in enumerate((-12, 52, 116, 180, 244, 308)):
        img = np.full((360, 480, 3), (44, 48, 52), np.uint8)
        for x in range(0, 480, 48):
            cv2.line(img, (x, 0), (x - 120, 359), (58, 62, 66), 1)
        cv2.rectangle(img, (0, 42), (479, 318), (62, 68, 72), -1)
        for j, (dx, dy, w, h, color) in enumerate(objects):
            cx = 240 + dx + (i % 2) * (j - 1) * 2
            cy = y + dy + j * 4
            rect = ((float(cx), float(cy)), (float(w), float(h)), float((-8, 5, 13)[j]))
            box = np.round(cv2.boxPoints(rect)).astype(np.int32)
            cv2.fillPoly(img, [box], color)
            cv2.polylines(img, [box], True, (235, 235, 235), 2)
        out.append(_noise(img, 3, 1800 + i))
    return out


def conveyor_stereo_sequence() -> list[np.ndarray]:
    """合成輸送帶左視野樣本；右視野由現場 stereo_grab 的 right source 提供。"""
    out = []
    f, baseline, depth = 1200.0, 60.0, 600.0
    disp = int(round(f * baseline / depth))
    for i, y in enumerate((62, 116, 170, 224)):
        rng = np.random.default_rng(2400 + i)
        left = rng.integers(28, 86, (360, 480), np.uint8)
        right = np.full_like(left, 50)
        right[:, : 480 - disp] = left[:, disp:]
        for cx, cy, bw, bh in ((170, y, 72, 48), (290, y + 26, 84, 52), (375, y - 18, 64, 64)):
            texture = rng.integers(150, 245, (bh, bw), np.uint8)
            x0, y0 = int(cx - bw / 2), int(cy - bh / 2)
            if 0 <= y0 < 360 - bh and 0 <= x0 < 480 - bw and x0 - disp >= 0:
                left[y0 : y0 + bh, x0 : x0 + bw] = texture
                right[y0 : y0 + bh, x0 - disp : x0 - disp + bw] = texture
        out.append(cv2.cvtColor(left, cv2.COLOR_GRAY2BGR))
    return out


def small_code_scenes() -> list[np.ndarray]:
    """大背景上的小碼樣本: 前三張有移動的小 QR, 第四張缺碼作為 NG。"""
    try:
        enc = cv2.QRCodeEncoder.create()
        qr = enc.encode("VS-G3-0001")
    except Exception:  # noqa: BLE001 - 測試環境缺 QR 編碼器時仍保留可辨識的方格結構
        qr = ((np.indices((25, 25)).sum(axis=0) % 2) * 255).astype(np.uint8)
    qr = cv2.resize(qr, (84, 84), interpolation=cv2.INTER_NEAREST)
    positions = [(920, 260), (760, 560), (1030, 610), (860, 420)]
    out = []
    for i, (x0, y0) in enumerate(positions):
        rng = np.random.default_rng(1200 + i)
        img = _canvas(1280, 960, 96)
        texture = rng.normal(0, 18, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + texture, 0, 255).astype(np.uint8)
        for _ in range(34):
            x, y = int(rng.integers(40, 1180)), int(rng.integers(40, 860))
            w, h = int(rng.integers(35, 160)), int(rng.integers(20, 95))
            color = tuple(int(v) for v in rng.integers(45, 185, size=3))
            cv2.rectangle(img, (x, y), (min(1279, x + w), min(959, y + h)), color, -1)
        cv2.rectangle(img, (120, 120), (1160, 820), (135, 140, 142), 3)
        cv2.putText(img, "PACK-24", (165, 760), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (210, 210, 210), 6)
        if i != 3:
            pad = 16
            panel = np.full((qr.shape[0] + pad * 2, qr.shape[1] + pad * 2, 3), 238, np.uint8)
            panel[pad:pad + qr.shape[0], pad:pad + qr.shape[1]] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
            img[y0:y0 + panel.shape[0], x0:x0 + panel.shape[1]] = panel
        out.append(_noise(img, 4, 1210 + i))
    return out


def list_parts() -> list[np.ndarray]:
    """小零件散布圖；前三張有 6 顆合格尺寸，第四張少一顆且多一顆過大的干擾物。"""
    base = [(92, 98, 19), (214, 122, 27), (338, 92, 22), (480, 140, 31), (156, 288, 24), (404, 310, 29)]
    out = []
    for i in range(4):
        img = _canvas(560, 400, 38)
        parts = base if i != 3 else base[:-1]
        for j, (cx, cy, r) in enumerate(parts):
            dx = (i % 3 - 1) * (j % 2 + 1)
            dy = ((i + j) % 3 - 1) * 2
            cv2.circle(img, (cx + dx, cy + dy), r, (202, 208, 212), -1)
            cv2.circle(img, (cx + dx, cy + dy), max(4, r // 4), (78, 82, 88), -1)
        if i == 3:
            cv2.circle(img, (462, 292), 58, (218, 220, 222), -1)
        out.append(_noise(img, 3, 3100 + i))
    return out


def cleanup_boxes() -> list[np.ndarray]:
    """重複定位標記與禁區；第四張多一個標記壓到禁區。"""
    out = []
    markers = [(92, 92), (156, 240), (244, 142)]
    for i in range(4):
        img = _canvas(520, 360, 42)
        cv2.rectangle(img, (325, 92), (445, 240), (88, 92, 96), -1)
        cv2.rectangle(img, (325, 92), (445, 240), (126, 130, 136), 3)
        cv2.putText(img, "NO", (360, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (58, 62, 66), 2)
        use = markers + ([(384, 170)] if i == 3 else [])
        for j, (cx, cy) in enumerate(use):
            x, y = cx + (i % 2) * 3 - 1, cy + ((i + j) % 2) * 2 - 1
            cv2.rectangle(img, (x - 24, y - 20), (x + 24, y + 20), (214, 216, 220), -1)
            cv2.line(img, (x - 15, y), (x + 15, y), (52, 56, 62), 4)
            cv2.line(img, (x, y - 12), (x, y + 12), (52, 56, 62), 4)
        out.append(_noise(img, 3, 3200 + i))
    return out


def component_array() -> list[np.ndarray]:
    """3x4 元件陣列；第四張缺一格。"""
    out = []
    for i in range(4):
        img = _canvas(560, 360, 36)
        missing = (1, 2) if i == 3 else None
        for r in range(3):
            for c in range(4):
                if (r, c) == missing:
                    continue
                cx = 100 + c * 115 + ((i + r) % 2) * 2
                cy = 80 + r * 90 + ((i + c) % 2) * 2
                cv2.rectangle(img, (cx - 24, cy - 18), (cx + 24, cy + 18), (204, 210, 214), -1)
                cv2.circle(img, (cx, cy), 6, (80, 84, 88), -1)
        out.append(_noise(img, 3, 3300 + i))
    return out


def label_map_colours() -> list[np.ndarray]:
    """紅綠藍三色圓點計數；第四張少了藍色。"""
    out = []
    for i in range(4):
        img = _canvas(520, 320, 52)
        cv2.circle(img, (130, 160), 48, (45, 45, 218), -1)
        cv2.circle(img, (260, 160), 48, (62, 178, 62), -1)
        if i != 3:
            cv2.circle(img, (390, 160), 48, (210, 92, 45), -1)
        out.append(_noise(img, 2, 3400 + i))
    return out


def sample_colour_cards() -> list[np.ndarray]:
    """樣本色分類卡；第四張是樣本外的橘色。"""
    colours = [(45, 45, 218), (62, 178, 62), (210, 92, 45), (45, 142, 228)]
    out = []
    for i, colour in enumerate(colours):
        img = _canvas(420, 280, 205)
        cv2.rectangle(img, (120, 70), (300, 210), colour, -1)
        cv2.rectangle(img, (120, 70), (300, 210), (45, 48, 52), 2)
        out.append(_noise(img, 2, 3500 + i))
    return out


def plate_corners() -> list[np.ndarray]:
    """矩形板角點與歪斜量測；前三張尺寸合格，第四張寬度與角度超差。"""
    out = []
    specs = [((260, 180), (300, 170), -2), ((264, 178), (302, 168), 1.5), ((256, 182), (298, 172), 0.8), ((260, 180), (355, 155), 8)]
    for i, (center, size, angle) in enumerate(specs):
        img = _canvas(520, 360, 38)
        pts = np.round(cv2.boxPoints((center, size, angle))).astype(np.int32)
        cv2.fillPoly(img, [pts], (212, 216, 220))
        cv2.circle(img, tuple(pts[0]), 9, (70, 76, 82), -1)
        out.append(_noise(img, 3, 4200 + i))
    return out


def parallel_edges() -> list[np.ndarray]:
    """槽寬與條紋數；第四張槽變寬。"""
    out = []
    widths = [70, 72, 68, 116]
    for i, width in enumerate(widths):
        img = _canvas(560, 340, 62)
        cv2.rectangle(img, (55, 46), (505, 294), (198, 202, 206), -1)
        y0, y1 = 170 - width // 2, 170 + width // 2
        cv2.rectangle(img, (90, y0), (470, y1), (42, 46, 52), -1)
        for x in (125, 205, 285, 365, 445):
            cv2.line(img, (x + (i % 2), 55), (x + (i % 2), 130), (58, 62, 68), 5)
        out.append(_noise(img, 3, 4300 + i))
    return out


def hole_matrix() -> list[np.ndarray]:
    """3x3 孔陣列；第四張缺中右孔。"""
    out = []
    for i in range(4):
        img = _canvas(500, 360, 48)
        cv2.rectangle(img, (70, 50), (430, 310), (208, 212, 216), -1)
        missing = (1, 2) if i == 3 else None
        for r in range(3):
            for c in range(3):
                if (r, c) == missing:
                    continue
                cx = 130 + c * 120 + (i % 2) * 2
                cy = 100 + r * 80 + ((i + c) % 2)
                cv2.circle(img, (cx, cy), 23, (42, 46, 52), -1)
        out.append(_noise(img, 3, 4400 + i))
    return out


def edge_trend_peaks() -> list[np.ndarray]:
    """直邊趨勢與亮峰數；第四張直邊有凸起。"""
    out = []
    for i in range(4):
        img = _canvas(560, 360, 44)
        cv2.rectangle(img, (70, 188), (500, 270), (204, 208, 212), -1)
        if i == 3:
            cv2.rectangle(img, (285, 172), (350, 205), (204, 208, 212), -1)
        for x in (145, 235, 325, 415):
            cv2.rectangle(img, (x - 9 + (i % 2), 65), (x + 9 + (i % 2), 128), (224, 226, 228), -1)
        out.append(_noise(img, 3, 4500 + i))
    return out


def outline_model_parts() -> list[np.ndarray]:
    """教導輪廓缺陷；第 2、3 張平移旋轉，第四張缺口。"""
    out = []
    poses = [(260, 180, 0, False), (283, 194, 4, False), (238, 166, -5, False), (260, 180, 0, True)]
    base = np.array([[-130, -78], [115, -78], [145, -48], [145, 68], [108, 92], [-124, 92], [-150, 58], [-150, -44]], dtype=np.float64)
    for i, (cx, cy, angle, defect) in enumerate(poses):
        img = _canvas(520, 360, 36)
        pts = base.copy()
        if defect:
            pts = np.array([[-130, -78], [-25, -78], [2, -45], [30, -78], [115, -78], [145, -48], [145, 68], [108, 92], [-124, 92], [-150, 58], [-150, -44]], dtype=np.float64)
        rad = np.deg2rad(angle)
        rot = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
        cv2.fillPoly(img, [np.round(pts @ rot.T + [cx, cy]).astype(np.int32)], (206, 210, 214))
        mark = np.round(np.array([[-38, -22], [38, -22], [38, 22], [-38, 22]], dtype=np.float64) @ rot.T + [cx, cy]).astype(np.int32)
        cv2.fillPoly(img, [mark], (70, 74, 80))
        out.append(_noise(img, 3, 4600 + i))
    return out


def path_edge_parts() -> list[np.ndarray]:
    """折線路徑上的亮膠條；第四張中段缺口。"""
    out = []
    for i in range(4):
        img = _canvas(560, 340, 42)
        cv2.line(img, (45, 170), (525, 170), (210, 214, 218), 24, cv2.LINE_AA)
        cv2.line(img, (45, 170), (525, 170), (238, 240, 242), 8, cv2.LINE_AA)
        if i == 3:
            cv2.line(img, (250, 170), (325, 170), (42, 42, 42), 34, cv2.LINE_AA)
        out.append(_noise(img, 3, 4700 + i))
    return out


def focus_gate_parts() -> list[np.ndarray]:
    """焦距閘門；第四張模糊。"""
    out = []
    for i in range(4):
        img = _canvas(460, 300, 58)
        for y in range(55, 245, 16):
            cv2.line(img, (85, y), (375, y + (i % 2) * 2), (218, 220, 222), 3)
        cv2.putText(img, "FOCUS", (118, 168), cv2.FONT_HERSHEY_SIMPLEX, 1.35, (40, 44, 50), 4)
        if i == 3:
            img = cv2.GaussianBlur(img, (21, 21), 0)
        out.append(_noise(img, 2, 4800 + i))
    return out


def temporal_frames() -> list[np.ndarray]:
    """跨幀平均與前一幀差異；第四張多一顆亮點。"""
    out = []
    for i in range(4):
        img = _canvas(420, 300, 36)
        cv2.circle(img, (150, 150), 34, (214, 218, 222), -1)
        cv2.circle(img, (270, 150), 34, (214, 218, 222), -1)
        if i == 3:
            cv2.circle(img, (210, 220), 28, (214, 218, 222), -1)
        out.append(_noise(img, 3, 4900 + i))
    return out


def roi_process_paste() -> list[np.ndarray]:
    """ROI 內前處理後貼回整張；第四張 ROI 多一個缺陷。"""
    out = []
    for i in range(4):
        img = _canvas(520, 320, 54)
        cv2.rectangle(img, (95, 70), (425, 250), (198, 202, 206), -1)
        for x in (165, 260, 355):
            cv2.circle(img, (x, 160), 26, (78, 82, 88), -1)
        if i == 3:
            cv2.circle(img, (260, 96), 20, (36, 38, 42), -1)
        out.append(_noise(img, 3, 5000 + i))
    return out


def undistort_world_parts() -> list[np.ndarray]:
    """手動鏡頭修正與像素比例；第四張兩孔距離超差。"""
    out = []
    for i, dist in enumerate((200, 202, 198, 236)):
        img = _canvas(520, 340, 48)
        cv2.rectangle(img, (70, 52), (450, 288), (204, 208, 212), -1)
        cx1, cx2, cy = 260 - dist // 2, 260 + dist // 2, 170
        cv2.circle(img, (cx1, cy), 24, (42, 46, 52), -1)
        cv2.circle(img, (cx2, cy + (i % 2)), 24, (42, 46, 52), -1)
        out.append(_noise(img, 3, 5100 + i))
    return out


def camera_mapping_parts() -> list[np.ndarray]:
    """相機 A 座標映射到相機 B；第四張找不到孔。"""
    out = []
    for i in range(4):
        img = _canvas(420, 300, 45)
        if i != 3:
            cv2.circle(img, (175 + i * 8, 142 + i * 3), 26, (214, 218, 222), -1)
            cv2.circle(img, (175 + i * 8, 142 + i * 3), 10, (50, 54, 60), -1)
        cv2.rectangle(img, (48, 50), (372, 250), (88, 92, 98), 2)
        out.append(_noise(img, 3, 5200 + i))
    return out


def pick_offset_parts() -> list[np.ndarray]:
    """教導取料點補正；第 2、3 張平移旋轉，第四張無零件。"""
    out = []
    poses = [(230, 155, 0), (258, 174, 6), (204, 136, -7), (0, 0, 0)]
    base = np.array([[-70, -42], [72, -42], [88, 24], [20, 62], [-74, 42]], dtype=np.float64)
    for i, (cx, cy, angle) in enumerate(poses):
        img = _canvas(460, 300, 38)
        if i != 3:
            rad = np.deg2rad(angle)
            rot = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
            cv2.fillPoly(img, [np.round(base @ rot.T + [cx, cy]).astype(np.int32)], (210, 214, 218))
            cv2.circle(img, tuple(np.round(np.array([20, 0]) @ rot.T + [cx, cy]).astype(int)), 12, (70, 74, 80), -1)
        out.append(_noise(img, 3, 5300 + i))
    return out


def fixture_rerun_parts() -> list[np.ndarray]:
    """整張影像回正後量測；第 2、3 張平移旋轉，第四張帶寬超差。"""
    out = []
    specs = [(260, 170, 0, 86), (285, 188, 5, 84), (236, 150, -6, 88), (260, 170, 0, 124)]
    for i, (cx, cy, angle, band_h) in enumerate(specs):
        img = _canvas(520, 340, 40)
        rad = np.deg2rad(angle)
        rot = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
        body = np.array([[-150, -92], [150, -92], [150, 92], [-150, 92]], dtype=np.float64)
        cv2.fillPoly(img, [np.round(body @ rot.T + [cx, cy]).astype(np.int32)], (196, 200, 204))
        band = np.array([[-105, -band_h / 2], [105, -band_h / 2], [105, band_h / 2], [-105, band_h / 2]], dtype=np.float64)
        cv2.fillPoly(img, [np.round(band @ rot.T + [cx, cy]).astype(np.int32)], (76, 80, 86))
        marker = np.array([[-28, -28], [28, -28], [28, 28], [-28, 28]], dtype=np.float64)
        cv2.fillPoly(img, [np.round(marker @ rot.T + [cx - 92, cy - 56]).astype(np.int32)], (226, 228, 230))
        out.append(_noise(img, 3, 5400 + i))
    return out


def stitch_views() -> list[np.ndarray]:
    """左視野零件；右視野由固定影像提供，第四張少一顆。"""
    out = []
    for i in range(4):
        img = _canvas(280, 240, 42)
        pts = [(92, 86), (188, 150)] if i != 3 else [(92, 86)]
        for cx, cy in pts:
            cv2.circle(img, (cx + i % 2, cy), 24, (218, 222, 226), -1)
        out.append(_noise(img, 3, 5500 + i))
    return out


def stitch_right_view() -> np.ndarray:
    """拼接範本的右視野固定影像。"""
    img = _canvas(280, 240, 42)
    for cx, cy in ((84, 145), (188, 84)):
        cv2.circle(img, (cx, cy), 24, (218, 222, 226), -1)
    return _noise(img, 3, 5510)


def variable_recipe_parts() -> list[np.ndarray]:
    """變數配方範例；預設 bright 分支，第四張亮度不符合該分支。"""
    out = []
    levels = [214, 206, 218, 118]
    for i, level in enumerate(levels):
        img = _canvas(460, 320, 34)
        for cx, cy in [(150, 120), (300, 120), (225, 220)]:
            cv2.circle(img, (cx + (i % 2) * 3, cy), 34, (level, level, level + 2), -1)
        out.append(_noise(img, 3, 3600 + i))
    return out


def tiled_panels() -> list[np.ndarray]:
    """2x2 分格板；第四張右下格有暗污點。"""
    out = []
    for i in range(4):
        img = _canvas(480, 320, 58)
        for y in (0, 160):
            for x in (0, 240):
                cv2.rectangle(img, (x + 16, y + 16), (x + 224, y + 144), (202, 206, 210), -1)
                cv2.rectangle(img, (x + 16, y + 16), (x + 224, y + 144), (82, 86, 90), 2)
        if i == 3:
            cv2.circle(img, (356, 238), 28, (48, 50, 52), -1)
        out.append(_noise(img, 3, 3700 + i))
    return out


def script_rectangles() -> list[np.ndarray]:
    """自訂量測用矩形；前三張長寬比合格，第四張過細。"""
    out = []
    sizes = [(180, 110), (172, 116), (188, 108), (230, 58)]
    for i, (w, h) in enumerate(sizes):
        img = _canvas(460, 300, 42)
        rect = ((230.0, 150.0), (float(w), float(h)), float((-4, 3, 0, 2)[i]))
        pts = np.round(cv2.boxPoints(rect)).astype(np.int32)
        cv2.fillPoly(img, [pts], (210, 214, 218))
        out.append(_noise(img, 3, 3800 + i))
    return out


def coded_messages() -> list[np.ndarray]:
    """QR 訊息規則；第四張批號格式錯誤。"""
    payloads = ["B240901|PN-100", "B240902|PN-100", "B240903|PN-100", "BAD901|PN-100"]
    out = []
    for i, payload in enumerate(payloads):
        try:
            enc = cv2.QRCodeEncoder.create()
            qr = enc.encode(payload)
        except Exception:  # noqa: BLE001 - 測試環境沒有 QR 編碼器時仍產生可見圖樣。
            qr = ((np.indices((25, 25)).sum(axis=0) % 2) * 255).astype(np.uint8)
        qr = cv2.resize(qr, (170, 170), interpolation=cv2.INTER_NEAREST)
        img = _canvas(420, 300, 68)
        cv2.rectangle(img, (90, 42), (330, 258), (238, 238, 236), -1)
        img[62:232, 125:295] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        cv2.putText(img, "PN-100", (145, 252), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (45, 45, 45), 2)
        out.append(_noise(img, 2, 3900 + i))
    return out


def io_signal_parts() -> list[np.ndarray]:
    """I/O 順序範例；前三張有三個亮點，第四張少一點。"""
    out = []
    for i in range(4):
        img = _canvas(420, 300, 38)
        pts = [(120, 100), (210, 180), (305, 110)] if i != 3 else [(120, 100), (210, 180)]
        for cx, cy in pts:
            cv2.circle(img, (cx + i % 2, cy), 28, (218, 220, 222), -1)
        out.append(_noise(img, 3, 4000 + i))
    return out


def output_bundle_parts() -> list[np.ndarray]:
    """輸出打包範例；前三張三顆零件，第四張多一顆。"""
    out = []
    for i in range(4):
        img = _canvas(420, 300, 40)
        pts = [(118, 145), (210, 145), (302, 145)] + ([(210, 220)] if i == 3 else [])
        for cx, cy in pts:
            cv2.rectangle(img, (cx - 24, cy - 24), (cx + 24, cy + 24), (208, 214, 218), -1)
        out.append(_noise(img, 3, 4100 + i))
    return out


#: key → (顯示名, 產生器)。key 同時是 data/samples/ 下的資料夾名。
SAMPLE_SETS: dict[str, tuple[str, callable]] = {
    "registered_parts": ("registered parts", registered_parts),
    "plate_holes": ("plate holes", plate_holes),
    "exposure_frames": ("exposure", exposure_frames),
    "circle_part": ("circle gauge", circle_part),
    "l_bracket": ("edge angle", l_bracket),
    "golden_print": ("print compare", golden_print),
    "textile": ("fabric defect", textile),
    "brushed_surface": ("brushed surface", brushed_surface),
    "gradient_chart": ("preprocessing lab", gradient_chart),
    "multi_circles": ("circles and lines", multi_circles),
    "gear": ("gear teeth", gear),
    "stamped_part": ("stamped part", stamped_part),
    "vignette": ("uneven lighting", vignette_parts),
    "shape_parts": ("shape match", shape_parts),
    "chipped_disc": ("chipped disc", chipped_disc),
    "emboss_quad": ("embossed plate (four lights)", emboss_quad),
    "barcode_grades": ("barcode grading", barcode_grades),
    "date_codes": ("date code label", date_codes),
    "color_blocks": ("colour blocks", color_blocks),
    "label_qr": ("barcode label", label_qr),
    "small_code_scenes": ("small code in clutter", small_code_scenes),
    "cup": ("cup gauge", cup),
    "marker_plate": ("locate and gauge", marker_plate),
    "stop_signs": ("stop sign", stop_signs),
    "conveyor_sequence": ("conveyor sequence", conveyor_sequence),
    "conveyor_stereo_sequence": ("conveyor stereo sequence", conveyor_stereo_sequence),
    "list_parts": ("list postprocess parts", list_parts),
    "cleanup_boxes": ("box cleanup", cleanup_boxes),
    "component_array": ("component array", component_array),
    "label_map_colours": ("label map colours", label_map_colours),
    "sample_colour_cards": ("sample colour cards", sample_colour_cards),
    "plate_corners": ("plate corners", plate_corners),
    "parallel_edges": ("parallel edges", parallel_edges),
    "hole_matrix": ("hole matrix", hole_matrix),
    "edge_trend_peaks": ("edge trend peaks", edge_trend_peaks),
    "outline_model_parts": ("outline model parts", outline_model_parts),
    "path_edge_parts": ("path edge search", path_edge_parts),
    "focus_gate_parts": ("focus gate", focus_gate_parts),
    "temporal_frames": ("temporal frames", temporal_frames),
    "roi_process_paste": ("ROI process paste", roi_process_paste),
    "undistort_world_parts": ("undistort world parts", undistort_world_parts),
    "camera_mapping_parts": ("camera mapping parts", camera_mapping_parts),
    "pick_offset_parts": ("pick offset parts", pick_offset_parts),
    "fixture_rerun_parts": ("fixture rerun parts", fixture_rerun_parts),
    "stitch_views": ("stitch views", stitch_views),
    "variable_recipe_parts": ("variable recipe parts", variable_recipe_parts),
    "tiled_panels": ("tiled panels", tiled_panels),
    "script_rectangles": ("script rectangles", script_rectangles),
    "coded_messages": ("coded messages", coded_messages),
    "io_signal_parts": ("io signal parts", io_signal_parts),
    "output_bundle_parts": ("output bundle parts", output_bundle_parts),
    "dl_parts": ("classification teaching", dl_parts),
    "dl_scratch": ("segmentation teaching", dl_scratch),
    "ai_classifier_gate_parts": ("AI classifier gate parts", ai_classifier_gate_parts),
    "ai_tilted_parts": ("AI tilted parts", ai_tilted_parts),
    "ai_pose_parts": ("AI pose stick figures", ai_pose_parts),
    "retrieval_query_parts": ("retrieval query parts", retrieval_query_parts),
    "multi_light_surface": ("multi-light surface", multi_light_surface),
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
