"""名片影像前處理：從整張照片裡找出名片、裁切拉正，並產生適合 OCR 的影像。

為什麼需要這一層？
    手機拍名片時，名片通常只占畫面的 1/5 左右，還會歪斜、帶著桌面/鍵盤等背景。
    直接把整張原圖丟給 Tesseract，字太小又混著背景雜訊，辨識結果經常是「完全空白」。
    先把名片框出來、透視校正拉平、再放大到足夠解析度，辨識率才會從 0 變成可用。

流程：
    1. detect_card()  以 HSV 的「亮且低飽和」特徵找出白色名片區塊（木桌偏橘=高飽和、
       鍵盤偏暗=低亮度，都會被濾掉），再用最小外接矩形 + 名片長寬比 (91:55) 評分挑出最像
       名片的那一塊。
    2. warp_card()    四點透視變換，把歪斜的名片拉成正對鏡頭的矩形。
    3. normalize_orientation() 轉成橫式，再用 Tesseract OSD 修正上下顛倒。
    4. build_variants() 產生數種前處理版本（原灰階 / CLAHE 增強對比 / 去光暈），
       由 ocr.py 各跑一次辨識後合併結果——不同名片對前處理的偏好不同，多跑幾種再
       投票，比賭單一種前處理穩定得多。
    5. full_frame_variants() 另外提供「整張未裁切照片放大」的版本。裁切版在公司/
       電話/地址等欄位較準，但透視變換的重取樣會讓筆畫多的中文姓名變糊；兩邊一起
       投票可取兩者之長。

OpenCV / NumPy 為選用相依：沒有安裝時自動退回純 Pillow 的簡易處理（僅放大與提高對比，
不做名片偵測），功能仍可用只是辨識率較低。
"""

from PIL import Image, ImageOps

# OpenCV 與 NumPy 是一組的（cv2 的所有運算都以 ndarray 進行），缺任何一個就整組停用，
# 改走純 Pillow 的簡易路徑。這樣即使部署環境裝不了 OpenCV，伺服器仍能正常啟動與辨識，
# 只是少了名片自動裁切校正、辨識率較低。
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

# 標準名片 91mm x 55mm，用來判斷偵測到的矩形像不像名片
CARD_ASPECT = 91.0 / 55.0
# 偵測時先縮到這個邊長做運算（省時間，且能濾掉細微雜訊）
DETECT_MAX_SIDE = 900
# 送進 OCR 前把名片放大到這個寬度；中文字筆畫多，太小會辨識不出來
OCR_TARGET_WIDTH = 1800


def available():
    """是否具備完整的影像前處理能力（有 OpenCV）。"""
    return cv2 is not None


# ---------------------------------------------------------------- 影像格式轉換
def pil_to_bgr(image):
    """PIL Image -> OpenCV BGR ndarray。"""
    rgb = image.convert("RGB")
    return np.asarray(rgb)[:, :, ::-1].copy()


def to_pil(array):
    """灰階或 BGR 的 ndarray -> PIL Image；已經是 PIL Image 則原樣回傳。

    沒有 OpenCV 時整條流程都以 PIL Image 傳遞，這裡直接放行，
    呼叫端就不必到處判斷目前手上的是哪一種型別。
    """
    if isinstance(array, Image.Image):
        return array
    if array.ndim == 2:
        return Image.fromarray(array)
    return Image.fromarray(array[:, :, ::-1])


# ---------------------------------------------------------------- 名片區塊偵測
def _order_points(pts):
    """把四個角點排成 左上 / 右上 / 右下 / 左下。

    左上角的 x+y 最小、右下角最大；右上角的 y-x 最小、左下角最大。
    這個排序是透視變換的前提，順序錯了圖會被扭曲或翻面。
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def _card_masks(small):
    """產生數種「可能是名片」的二值遮罩，依序當作偵測候選來源。"""
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]
    masks = []

    # 主要策略：先做光照平坦化，再取「亮且不飽和」的區域。
    # 用大半徑模糊估出背景亮度後相除，可以把拍照時打在名片上的陰影漸層壓掉；
    # 少了這一步，只要有手影或桌燈斜射，名片就會被陰影切成好幾塊，偵測到的往往
    # 只是其中一小片（實測有樣本只框到名片的 8%，等於整張名片幾乎都沒進 OCR）。
    background = cv2.GaussianBlur(value, (0, 0), max(small.shape) / 12.0)
    flattened = cv2.divide(value, background, scale=255)
    masks.append(((saturation < 90) & (flattened > 170)).astype(np.uint8) * 255)

    # 備援策略一：不做平坦化的純亮度門檻，處理整體偏暗、平坦化後對比不足的照片。
    bright = max(120, int(np.percentile(value, 80)))
    masks.append(((saturation < 90) & (value > bright)).astype(np.uint8) * 255)

    # 備援策略二：純亮度 Otsu 二值化，處理名片本身偏灰或背景也偏白的情況。
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks.append(otsu)

    cleaned = []
    for mask in masks:
        # 先閉運算補起名片上文字/圖案造成的破洞（順便橋接陰影造成的細縫），
        # 再開運算去掉背景碎點。
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8), iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        cleaned.append(mask)
    return cleaned


def _best_candidate(mask, total_area, scale):
    """在單一遮罩裡挑出最像名片的矩形，回傳 (分數, 角點) 或 None。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        area = cv2.contourArea(contour)
        # 太小的多半是反光或雜物；幾乎占滿整張的多半是桌面而不是名片。
        if area < 0.03 * total_area or area > 0.95 * total_area:
            continue

        rect = cv2.minAreaRect(contour)
        rect_w, rect_h = rect[1]
        if rect_w < 10 or rect_h < 10:
            continue

        aspect = max(rect_w, rect_h) / min(rect_w, rect_h)
        # 輪廓填滿最小外接矩形的比例；名片是實心矩形，比例應該很接近 1。
        fill = area / (rect_w * rect_h)
        if fill < 0.75:
            continue
        aspect_penalty = abs(aspect - CARD_ASPECT) / CARD_ASPECT
        if aspect_penalty > 0.45:  # 長寬比離名片太遠，直接排除
            continue

        # 綜合評分：形狀越像矩形、長寬比越接近名片、面積越大者優先。
        score = fill * (1.0 - aspect_penalty) * (area / total_area) ** 0.25
        if best is None or score > best[0]:
            best = (score, cv2.boxPoints(rect).astype("float32") / scale)
    return best


def detect_card(bgr):
    """在整張照片裡找出最像名片的四邊形，回傳原圖座標的 4x2 角點；找不到回傳 None。"""
    if cv2 is None:
        return None

    height, width = bgr.shape[:2]
    scale = DETECT_MAX_SIDE / float(max(height, width))
    small = cv2.resize(bgr, None, fx=scale, fy=scale) if scale < 1 else bgr.copy()
    if scale >= 1:
        scale = 1.0
    total_area = float(small.shape[0] * small.shape[1])

    # 依序嘗試各遮罩策略，第一個找得到候選的就採用，不把所有候選放在一起比分數。
    # 主策略（亮且低飽和）針對名片設計，備援的 Otsu 只看亮度，在木質桌面上很容易
    # 把整片桌子當成一個又大又方正的矩形——放在一起比分數時，桌子會因為面積大而
    # 蓋過真正的名片，所以備援只在主策略失效時才輪到它。
    for mask in _card_masks(small):
        best = _best_candidate(mask, total_area, scale)
        if best is not None:
            return best[1]
    return None


def warp_card(bgr, quad, inset_ratio=0.01):
    """依四個角點做透視變換，把歪斜的名片拉正成矩形。

    inset_ratio 會沿著中心稍微內縮，切掉邊緣可能殘留的背景細邊；名片本身
    留白足夠，內縮 1% 不會吃到文字。
    """
    rect = _order_points(quad)
    if inset_ratio:
        center = rect.mean(axis=0)
        rect = center + (rect - center) * (1.0 - inset_ratio)

    top_left, top_right, bottom_right, bottom_left = rect
    width = int(max(np.linalg.norm(bottom_right - bottom_left),
                    np.linalg.norm(top_right - top_left)))
    height = int(max(np.linalg.norm(top_right - bottom_right),
                     np.linalg.norm(top_left - bottom_left)))
    if width < 10 or height < 10:
        return None

    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                   dtype="float32")
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(bgr, matrix, (width, height))


def extract_card(image):
    """PIL 照片 -> 裁切拉正後的名片影像, 是否真的偵測到名片。

    有 OpenCV 時回傳 BGR ndarray，沒有時原樣回傳 PIL Image；後續的
    normalize_orientation / build_variants 兩種都吃得下。

    偵測不到名片時（例如使用者上傳的本來就是裁好的掃描檔）直接回傳整張圖，
    讓後續辨識照常進行。
    """
    if cv2 is None:
        return image, False

    bgr = pil_to_bgr(image)
    quad = detect_card(bgr)
    if quad is None:
        return bgr, False

    warped = warp_card(bgr, quad)
    if warped is None:
        return bgr, False
    return warped, True


# ---------------------------------------------------------------- 方向校正
def normalize_orientation(bgr, detect_rotation=None):
    """把名片轉成正向：先轉成橫式，再依 Tesseract OSD 的結果修正剩下的旋轉。

    名片幾乎都是橫式版面，因此裁切結果若是直的，代表拍攝時轉了 90 度，先轉回橫式；
    轉成橫式後仍可能上下顛倒（差 180 度），這部分要靠 OSD 判斷。

    detect_rotation 是一個 callable，接收「已轉成橫式」的影像並回傳還需順時針旋轉
    幾度。順序很重要：OSD 必須在轉成橫式「之後」才量測，否則量到的角度是針對舊方向，
    套用後會和轉橫式的那一次相加，反而把原本擺正的名片轉歪（90 度的照片會失敗）。
    """
    if cv2 is None:
        return bgr

    height, width = bgr.shape[:2]
    if height > width:
        bgr = cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)

    if detect_rotation is None:
        return bgr

    rotation = {90: cv2.ROTATE_90_CLOCKWISE,
                180: cv2.ROTATE_180,
                270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(detect_rotation(bgr) % 360)
    return bgr if rotation is None else cv2.rotate(bgr, rotation)


# ---------------------------------------------------------------- OCR 前處理版本
def _resize_for_ocr(bgr):
    """把影像縮放到 OCR 適合的寬度——太小要放大，太大也要縮小。

    「縮小」這一半同樣重要：現在的手機動輒 1200 萬畫素，名片照片常有 4000px 寬，
    直接丟給 Tesseract 會慢上好幾倍卻不會更準（文字早已遠超辨識所需的解析度）。
    統一到 OCR_TARGET_WIDTH 能大幅縮短辨識時間。
    縮小用 INTER_AREA（不會產生鋸齒），放大用 INTER_CUBIC（邊緣較銳利）。
    """
    height, width = bgr.shape[:2]
    if width == OCR_TARGET_WIDTH:
        return bgr
    factor = OCR_TARGET_WIDTH / float(width)
    interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC
    return cv2.resize(bgr, (OCR_TARGET_WIDTH, max(1, int(height * factor))),
                      interpolation=interpolation)


def build_variants(bgr):
    """產生數種前處理版本供 OCR 多次嘗試，回傳 [(名稱, PIL Image), ...]。

    不同名片（底色、字體、反光程度）適合的前處理不同，與其賭一種，不如各跑一次
    再由 ocr.py 合併欄位結果。實測三種版本已能涵蓋大部分情況，再多只是拖慢速度。
    """
    if cv2 is None:
        return _pillow_variants(to_pil(bgr))

    bgr = _resize_for_ocr(bgr)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # CLAHE：局部直方圖均衡，救回照片一邊亮一邊暗時暗處的文字。
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    # 去光暈：用閉運算估出背景亮度再相除，壓掉拍照時的陰影與反光漸層。
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    flattened = cv2.divide(gray, background, scale=255)

    return [("clahe", to_pil(clahe)), ("gray", to_pil(gray)), ("flat", to_pil(flattened))]


def full_frame_variants(image):
    """把「整張未裁切的照片」放大後也產生 OCR 版本，作為裁切結果之外的第二意見。

    裁切拉正後的名片在多數欄位上明顯較準，但透視變換難免有重取樣造成的模糊，
    對字體特殊、筆畫多的中文姓名反而可能失分；實測整張放大這一路常能補回姓名
    與職稱。兩邊的辨識結果一起投票（見 ocr._merge_fields），可取兩者之長。
    純 Pillow 實作，沒有 OpenCV 也能用。
    """
    return _pillow_variants(image, prefix="full")


def _pillow_variants(image, prefix=""):
    """純 Pillow 的前處理：轉灰階、放大到 OCR 可讀的解析度、再加一版自動對比。

    同時作為「沒有 OpenCV 時的退化路徑」與 full_frame_variants 的實作。
    放大這一步最關鍵——名片文字在原始照片裡往往只有十幾像素高，不放大 Tesseract
    幾乎讀不出任何東西。
    """
    image = image.convert("L")
    if image.width != OCR_TARGET_WIDTH:
        # 同樣是雙向縮放：手機原圖過大時縮小可省下數倍辨識時間（見 _resize_for_ocr）。
        factor = OCR_TARGET_WIDTH / float(image.width)
        image = image.resize((OCR_TARGET_WIDTH, max(1, int(image.height * factor))),
                             Image.LANCZOS)
    tag = f"{prefix}_" if prefix else ""
    return [(f"{tag}gray", image), (f"{tag}autocontrast", ImageOps.autocontrast(image))]
