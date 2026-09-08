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


#: key → (顯示名, 產生器)。key 同時是 data/samples/ 下的資料夾名。
SAMPLE_SETS: dict[str, tuple[str, callable]] = {
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
