"""名片文字辨識與欄位解析（best-effort，非 100% 準確）。

辨識流程：
    1. 先用 cardimage.py 把名片從整張照片裡框出來、透視校正拉平、轉正、放大。
       手機拍的名片通常只占畫面一小塊又歪斜，少了這一步 Tesseract 幾乎讀不到字。
    2. 對數種前處理版本 x 數種版面分析模式各跑一次 Tesseract，
       每一次都解析成欄位，最後用投票合併（見 _merge_fields）。
       單一次辨識時好時壞，多跑幾次投票能明顯拉高穩定度。
    3. 用常見的名片版面規則（Email/電話格式、公司/職稱/地址關鍵字）把文字行分類到欄位。

這仍然只是啟發式規則，遇到版面特殊、字體花俏、拍照角度不佳的名片時可能辨識不到
甚至辨識錯誤——所以每個欄位都只是「預先幫忙填」，表單本身仍保持可編輯，辨識不到
或辨識錯的地方由使用者自行輸入/修正即可（見 app.py 的 /api/ocr）。

需另外安裝 Tesseract-OCR 執行檔（pip 只裝得到 Python 綁定，裝不到引擎本體）：
    Windows: https://github.com/UB-Mannheim/tesseract/wiki
             安裝時記得勾選「Chinese (Traditional)」語言包。
configure() 會自動尋找 PATH 與 Windows 常見安裝路徑，通常不需要手動指定；
真的找不到時可用 --tesseract-cmd 或環境變數 TESSERACT_CMD 指定完整路徑。
"""

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor

import cardimage

try:
    import pytesseract
except ImportError:
    pytesseract = None

# Windows 官方安裝程式預設不會把 Tesseract 加進 PATH，這裡把常見安裝位置列出來
# 自動尋找，省掉使用者一定要手動設定 --tesseract-cmd 才能用自動辨識的問題。
_WINDOWS_GUESSES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Tesseract-OCR\tesseract.exe"),
)

# 前處理版本 x 版面分析模式的組合，三種模式互補：
#   psm 3  = 自動版面分析，會自己切出欄位區塊。名片常是左右兩欄（姓名一欄、公司
#            聯絡方式另一欄），只有這個模式能把兩欄分開讀，姓名才不會和公司名黏成一行。
#   psm 6  = 視為單一文字區塊，適合排版規矩、由上到下的名片。
#   psm 11 = 稀疏文字，適合資訊散落四處、留白很多的名片。
# 這些回合是並行執行的（見 _run_passes），多一種模式幾乎不影響總耗時。
_PSM_MODES = (3, 6, 11)
_OCR_LANG = "chi_tra+eng"
# 並行辨識的上限。每個回合是一個 tesseract 子行程，開太多會反過來互相搶 CPU；
# 取核心數與 8 的較小值，單機同時服務數位使用者時也不會把 CPU 吃滿。
_MAX_WORKERS = min(8, (os.cpu_count() or 4))
# 方向探測（正向 vs 顛倒）用的影像寬度；只需比較兩邊誰讀得比較像文字，不必讀完整。
_PROBE_WIDTH = 1000

_COMPANY_KEYWORDS = ("股份有限公司", "有限公司", "企業社", "工作室", "集團",
                      "科技", "公司", "Co.,", "Co.", "Ltd", "Inc", "Corp",
                      "Corporation", "Group")
_TITLE_KEYWORDS = ("董事長", "執行長", "總經理", "副總經理", "副總", "總監", "協理",
                    "襄理", "副理", "經理", "主任", "工程師", "業務", "專員", "顧問",
                    "創辦人", "設計師", "管理師", "分析師", "規劃師", "技師",
                    "部長", "處長", "課長", "組長", "廠長", "特助", "秘書",
                    # 中文 C-level 職稱一律以「長」結尾，逐一列出比用「長」當關鍵字安全
                    # （只寫「長」會把「長春路」之類的地址也吃進來）
                    "人資長", "財務長", "技術長", "營運長", "資訊長", "行銷長", "策略長",
                    "主管", "助理", "代表", "研究員", "架構師", "會計師", "設計",
                    "CEO", "CTO", "COO", "CFO", "CHRO", "CIO", "CMO",
                    "Manager", "Director", "Engineer",
                    "Founder", "President", "Specialist", "Consultant", "Supervisor",
                    "Analyst", "Administrator", "Executive")
_ADDRESS_KEYWORDS = ("路", "街", "巷", "弄", "號", "樓", "市", "縣", "區", "段", "村", "里")

# 這些字眼旁邊的數字不是電話：統一編號、發票/股票代號都是純數字，長度也和市話接近，
# 不排除的話很容易被誤抓成電話。
_NOT_PHONE_MARKERS = ("統編", "統一編號", "統一編", "發票", "股票代號", "郵遞區號", "VAT")
# 傳真號碼格式和市話一模一樣，只能靠旁邊的標示區分；抓到也只當備援，不優先填入。
_FAX_MARKERS = ("傳真", "FAX", "Fax", "fax")
# 這些行含「號」又帶數字，長得很像地址但其實不是，必須排除（統編、證照號碼等）。
_NOT_ADDRESS_MARKERS = ("統編", "統一編號", "統一編", "發票", "股票代號", "執照號碼",
                         "證號", "登記證", "營利事業")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 台灣手機：09xx-xxx-xxx，或國際格式 +886-9xx-xxx-xxx
_MOBILE_RE = re.compile(r"(?:\+?886[-\s.]?|0)9\d{2}[-\s.]?\d{3}[-\s.]?\d{3}")
# 市話：含區碼，允許 +886 前綴與分機前的主號
_PHONE_RE = re.compile(r"(?:\+?886[-\s.]?)?\(?0?\d{1,2}\)?[-\s.]?\d{3,4}[-\s.]?\d{3,4}")
_NAME_CJK_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_NAME_EN_RE = re.compile(r"^[A-Za-z]+(?:[\s.-][A-Za-z]+){1,2}$")
# 「黃良祺 Kevin」這種中英並列的姓名行
_NAME_MIXED_RE = re.compile(r"^([\u4e00-\u9fff]{2,4})\s+([A-Za-z][A-Za-z.\s-]{1,20})$")
# 名片上的線條、圖示與色塊常被 OCR 讀成這些筆畫極簡的字，長度又剛好落在姓名的
# 2~4 字範圍內（例如把分隔線讀成「一一」），需要排除以免誤填成姓名。
_CJK_NOISE_CHARS = set("一二三十丨丶丿乙亅冫匚凵厂")
# 部門/單位名的結尾字。這些長度也常是 2~4 字，不排除就會被當成姓名。
_ORG_SUFFIXES = ("部", "處", "課", "組", "室", "廠", "中心", "公司", "事業群", "事業部")

# 常見中文姓氏（百家姓前段 + 台灣常見姓氏）。中文姓名的第一個字幾乎必然落在這裡，
# 用它把 OCR 讀出來的雜訊（「縣萬」「東佑達奈」這類剛好 2~4 字的碎片）擋掉——
# 沒有這道檢查，錯誤的姓名會被當成正確結果填進表單，比留白更難發現。
_COMMON_SURNAMES = set(
    "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴徐周葉蘇莊呂江何蕭羅高潘簡朱鍾游"
    "彭詹胡施沈余趙盧梁顏柯孫魏翁戴范方宋鄧杜傅侯曹薛丁卓阮馬董溫唐藍石"
    "蔣古紀姚連馮歐程白汪田涂尤巫韓龔嚴袁鐘邵柳錢秦孔任姜崔譚黎易常"
    "武喬賀聶管邢明計成戚辛官粘塗巴祝雷萬駱花安倪"
)
# 複姓：第一個字單獨看不像姓氏，需整組比對
_COMPOUND_SURNAMES = ("歐陽", "司馬", "諸葛", "上官", "皇甫", "尉遲", "夏侯", "南宮")

# 英文公司名和英文人名一樣是 Title Case，只能靠這些字眼區分（見 _is_plausible_latin_name）
_LATIN_COMPANY_WORDS = ("Corporation", "Corp", "Company", "Inc", "Ltd", "Limited", "LLC",
                         "Technology", "Technologies", "Tech", "Industry", "Industries",
                         "Enterprise", "Group", "Holdings", "Systems", "Solutions",
                         "International", "Electronics", "Instruments", "Semiconductor")

_FIELD_NAMES = ("name", "company", "title", "phone", "email", "address")


def _empty_fields():
    return {key: "" for key in _FIELD_NAMES}


def configure(tesseract_cmd=None):
    """指定 tesseract.exe 路徑。

    優先序：傳入參數 > TESSERACT_CMD 環境變數 > 系統 PATH > Windows 常見安裝路徑。
    最後一項是關鍵：Windows 安裝程式預設不會改 PATH，少了自動尋找就會出現
    「明明裝好了卻無法自動辨識」的狀況。
    """
    if pytesseract is None:
        return None

    candidates = [tesseract_cmd, os.environ.get("TESSERACT_CMD"), shutil.which("tesseract")]
    if os.name == "nt":
        candidates.extend(_WINDOWS_GUESSES)

    for candidate in candidates:
        if not candidate:
            continue
        # PATH 上找到的直接採用；其餘是猜測路徑，要確認檔案真的存在。
        if candidate == shutil.which("tesseract") or os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return candidate
    return None


def engine_status():
    """回傳 (是否可用, 說明訊息)，供啟動時印出診斷資訊。"""
    if pytesseract is None:
        return False, "未安裝 pytesseract 套件（pip install pytesseract）"
    try:
        version = pytesseract.get_tesseract_version()
    except Exception as exc:  # noqa: BLE001 - 執行檔不存在/無法執行都算引擎不可用
        return False, f"找不到或無法執行 Tesseract：{exc}"

    langs = []
    try:
        langs = pytesseract.get_languages()
    except Exception:  # noqa: BLE001 - 取語言清單失敗不影響辨識，只是少了提示
        pass
    if langs and "chi_tra" not in langs:
        return True, f"Tesseract {version} 可用，但缺少繁體中文語言包 (chi_tra)，中文將無法辨識"
    return True, f"Tesseract {version} 可用"


def recognize(image):
    """辨識名片影像，回傳 (fields: dict, raw_text: str, error: str | None)。

    error 不為 None 時代表 OCR 引擎不可用或辨識過程出錯，此時 fields 為全空字典；
    呼叫端（app.py 的 /api/ocr）應把這種情形視為「請使用者自行輸入」而非回傳錯誤
    給前端，避免使用者被迫處理技術性錯誤訊息。
    """
    if pytesseract is None:
        return _empty_fields(), "", "伺服器未安裝 OCR 套件（pytesseract）"

    try:
        card, detected = cardimage.extract_card(image)
        card = cardimage.normalize_orientation(card, _detect_rotation)
        variants = cardimage.build_variants(card)
        if detected:
            # 有裁切成功時，額外把整張原始照片也辨識一次一起投票：裁切版在公司/電話/
            # 地址等欄位較準，整張放大版則常補回被透視變換模糊掉的中文姓名與職稱。
            variants += cardimage.full_frame_variants(image)
    except Exception:  # noqa: BLE001 - 前處理失敗就退回原圖，不讓整個辨識掛掉
        variants = [("original", image)]

    jobs = [(prepared, psm) for _name, prepared in variants for psm in _PSM_MODES]
    results = _run_passes(jobs)
    if isinstance(results, str):  # 引擎層級的錯誤訊息
        return _empty_fields(), "", results

    passes = [(_text_score(text), text) for text in results if text.strip()]
    if not passes:
        return _empty_fields(), "", None

    passes.sort(key=lambda item: -item[0])
    fields = _merge_fields(passes)
    return fields, passes[0][1], None


def _run_passes(jobs):
    """並行執行所有辨識回合，回傳文字清單；引擎不可用時回傳錯誤訊息字串。

    每一次 pytesseract 呼叫都是啟動一個 tesseract.exe 子行程並等待它結束，等待期間
    會釋放 GIL，因此用執行緒池就能真正並行，不需要多行程。十來個回合原本是一個接
    一個跑，現在同時跑完，辨識時間幾乎只剩最慢的那一回合。
    """
    workers = min(len(jobs), _MAX_WORKERS)

    def run(job):
        prepared, psm = job
        return pytesseract.image_to_string(
            prepared, lang=_OCR_LANG, config=f"--oem 1 --psm {psm}"
        )

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(run, jobs))
    except Exception as exc:  # noqa: BLE001 - Tesseract 未安裝/語言包缺失/底層例外
        return f"OCR 引擎無法使用：{exc}"


def _detect_rotation(card_bgr):
    """判斷已轉成橫式的名片是否上下顛倒，回傳還需順時針旋轉的角度（0 或 180）。

    原本用 Tesseract 的 OSD，但名片文字量少、又中英混排，OSD 的信心值常低於 1
    （實測有樣本只有 0.69），判斷等同擲骰子。改成直接把兩個方向各辨識一次、
    比較文字品質分數：顛倒的那一邊幾乎讀不出完整的字，分數會明顯較低。
    為了省時間，探測用的影像縮到 _PROBE_WIDTH 就好，只是要比大小不用讀得完整。
    """
    try:
        probe = _probe_image(card_bgr)
        flipped = probe.rotate(180, expand=True)
        texts = _run_passes([(probe, 6), (flipped, 6)])
        if isinstance(texts, str):  # 引擎不可用，交給主流程回報
            return 0
        return 0 if _text_score(texts[0]) >= _text_score(texts[1]) else 180
    except Exception:  # noqa: BLE001 - 探測失敗就當作不需旋轉，交給後續辨識
        return 0


def _probe_image(card_bgr):
    """產生方向探測用的縮小灰階圖。"""
    image = cardimage.to_pil(card_bgr).convert("L")
    if image.width > _PROBE_WIDTH:
        factor = _PROBE_WIDTH / float(image.width)
        image = image.resize((_PROBE_WIDTH, max(1, int(image.height * factor))))
    return image


def _text_score(text):
    """粗略評估一次辨識結果的品質，用來排序多次辨識的結果。

    中文字與英數字越多分數越高，抓到 Email/電話樣式再加分；無法歸類的
    符號視為雜訊扣分。只用於「哪一次辨識比較可信」的相對比較。
    """
    cjk = len(re.findall(r"[一-鿿]", text))
    alnum = len(re.findall(r"[A-Za-z0-9]", text))
    bonus = 40 if _EMAIL_RE.search(text) else 0
    bonus += 25 if re.search(r"\d{3,4}[-\s]\d{3,4}", text) else 0
    junk = len(re.findall(r"[^\w\s一-鿿@.\-+()（），、:：/]", text))
    return cjk * 2 + alnum + bonus - junk * 2


def _merge_fields(passes):
    """把多次辨識的欄位結果合併成一組。

    多次辨識中重複出現的值通常才是真的讀對了；只出現一次的多半是某一次的雜訊，
    所以預設以「出現次數最多」為準，票數相同時取辨識品質分數較高的那一次
    （passes 已依分數排序，索引越小代表該次辨識整體品質越好）。

    地址是例外：各回合讀到的地址常常只差在被截斷多少（「303117 新竹縣」vs
    「303117 新竹縣湖口鄉八德路一段67號」），此時票多的反而可能是殘缺的那個，
    因此改以「地址完整度」優先、票數其次。
    """
    votes = {key: {} for key in _FIELD_NAMES}
    for index, (_score, text) in enumerate(passes):
        for key, value in parse_fields(text).items():
            if not value:
                continue
            record = votes[key].setdefault(value, [0, index])
            record[0] += 1
            record[1] = min(record[1], index)

    merged = _empty_fields()
    for key, candidates in votes.items():
        if not candidates:
            continue
        if key in ("company", "title"):
            # 中文名片上公司與職稱多半中英並列（人資長／CHRO、日揚科技／Highlight
            # Tech Corp.）。英文較好辨識，純比票數會讓英文版本勝出，但使用者要的是
            # 中文全名，因此先看有沒有中文，再比票數。
            rank = lambda kv: (bool(re.search(r"[一-鿿]", kv[0])),  # noqa: E731
                               kv[1][0], -kv[1][1])
        elif key == "address":
            # 完整度先粗分級再比票數：級距讓「只差一兩個字」的候選視為同級，
            # 由票數決勝（多次讀到同樣結果的通常才是對的），避免長度只多一個
            # 字元的誤讀（「3234…」vs「334…」）僅因為比較長就勝出；
            # 級距夠大時仍能讓明顯較完整的地址勝過被截斷的版本。
            rank = lambda kv: (_address_quality(kv[0]) // 15, kv[1][0],  # noqa: E731
                               _address_quality(kv[0]), -kv[1][1])
        else:
            rank = lambda kv: (kv[1][0], -kv[1][1])  # noqa: E731
        merged[key] = max(candidates.items(), key=rank)[0]
    return merged


def _clean_line(line):
    """去掉行首常見的圖示殘留（OCR 把電話/信箱小圖示讀成亂碼符號）與分隔線。"""
    line = line.strip()
    line = re.sub(r"^[^\w一-鿿+(]+", "", line)   # 行首非文字符號
    line = re.sub(r"^[|｜:：]+\s*", "", line)              # 圖示後常見的分隔線
    return line.strip()


def _digits(value):
    return re.sub(r"\D", "", value)


def parse_fields(text):
    """從 OCR 原始文字裡用關鍵字/格式規則猜出各欄位。逐行分類，
    每一行最多被分配到一個欄位（用 used 集合避免重複使用同一行）。"""
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    fields = _empty_fields()
    used = set()

    _extract_email(lines, fields, used)
    _extract_phone(lines, fields, used)
    _extract_company_title_address(lines, fields, used)
    _extract_address(lines, fields, used)
    _extract_name(lines, fields, used)
    return fields


def _extract_email(lines, fields, used):
    """Email 格式最明確，優先比對。"""
    for index, line in enumerate(lines):
        match = _EMAIL_RE.search(line)
        if match and not fields["email"]:
            # OCR 偶爾會把網址與 Email 讀在同一行，取比對到的那一段就好。
            fields["email"] = match.group().strip(".,;")
            used.add(index)


def _extract_phone(lines, fields, used):
    """抓電話：手機優先於市話，傳真只在沒有其他號碼時才用。

    名片上常同時有 M(手機)/T(市話)/F(傳真)，還有統一編號這種長得像電話的數字，
    所以先排除明確不是電話的行，再依「手機 > 市話 > 傳真」的順序挑。
    """
    mobile = landline = fax = None
    mobile_index = landline_index = fax_index = None

    for index, line in enumerate(lines):
        if index in used:
            continue
        if any(marker in line for marker in _NOT_PHONE_MARKERS):
            continue

        is_fax = any(marker in line for marker in _FAX_MARKERS) or bool(re.match(r"^F[\s+(]", line))

        match = _MOBILE_RE.search(line)
        if match and not is_fax:
            if mobile is None:
                mobile, mobile_index = match.group().strip(), index
            continue

        match = _PHONE_RE.search(line)
        if match and len(_digits(match.group())) >= 8:
            if is_fax:
                if fax is None:
                    fax, fax_index = match.group().strip(), index
            elif landline is None:
                landline, landline_index = match.group().strip(), index

    for value, index in ((mobile, mobile_index), (landline, landline_index), (fax, fax_index)):
        if value:
            fields["phone"] = value
            used.add(index)
            return


def _keyword_segment(line, keywords):
    """整行可能混進隔壁欄位或雜訊，取出真正含關鍵字的那一段並修掉頭尾雜訊。

    例如職稱行被讀成「罰點經理         了         é    |」，或公司行被讀成
    「f   2 沛龕科技有限公司 Aa ,79982174」，直接整行存進欄位會很難看。
    """
    segments = re.split(r"\s{3,}", line)
    if len(segments) > 1:
        hit = [seg for seg in segments if any(k in seg for k in keywords)]
        if hit:
            # 同一行可能有多段命中（中英文公司名常並列，如「日揚科技  Highlight Tech
            # Corp.」）。以中文字數優先，長度其次——這是中文名片系統，使用者要的是
            # 中文全名；只比長度的話英文名往往較長而勝出。
            line = max(hit, key=lambda seg: (len(re.findall(r"[一-鿿]", seg)), len(seg)))
    return _trim_edge_noise(line)


def _trim_edge_noise(value):
    """去掉頭尾明顯是雜訊的字詞。

    判定為雜訊的條件：單獨的一兩個字元（OCR 把線條、圖示讀成的「了」「é」「|」），
    或整段沒有任何字母與中文（純標點或標點加數字，如「,79982174」）。
    中間的內容一律保留，才不會把「軟體經理 Software Manager」的英文部分砍掉。
    """
    def is_noise(token):
        if not re.search(r"[A-Za-z一-鿿]", token):
            return True
        return len(token) <= 2 and not re.search(r"[一-鿿]{2}", token)

    tokens = value.split()
    while tokens and is_noise(tokens[0]):
        tokens.pop(0)
    while tokens and is_noise(tokens[-1]):
        tokens.pop()
    # 再修掉黏在字尾/字首的殘留標點（「工程師/」的那條斜線是分隔線被讀進來的）
    return " ".join(tokens).strip(" \t/|\\,;:·．、-_=+")


def _extract_company_title_address(lines, fields, used):
    """公司 / 職稱：用常見關鍵字比對整行，各取第一個命中的。"""
    for index, line in enumerate(lines):
        if index in used:
            continue
        if not fields["company"] and any(k in line for k in _COMPANY_KEYWORDS):
            fields["company"] = _keyword_segment(line, _COMPANY_KEYWORDS)
            used.add(index)
        elif not fields["title"] and any(k in line for k in _TITLE_KEYWORDS):
            fields["title"] = _keyword_segment(line, _TITLE_KEYWORDS)
            used.add(index)


def _tidy_address(value):
    """砍掉地址前面的標籤與雜訊，讓地址從郵遞區號或第一個中文字開始。

    OCR 常在地址前留下「地址：」這類標籤（還可能誤認成「總址:」），或把旁邊的
    圖示、標章讀成 'OAL ©' 之類的英文雜訊。這些前綴會讓同一個地址在不同回合被
    當成不同字串，投票時互相稀釋，清掉後才能正確合併。
    """
    value = value.strip()

    # 一行裡若有大片空白，多半是隔壁欄位或雜訊被讀進同一行（「…16號        2」），
    # 先切開只留最像地址的那一段。
    segments = re.split(r"\s{3,}", value)
    if len(segments) > 1:
        value = max(segments, key=_address_quality).strip()

    # 起點：郵遞區號緊接中文（「30442 新竹縣…」）最可靠。限制中間最多一個空白，
    # 否則同一行裡的統一編號也會被當成郵遞區號一起帶進來。
    match = re.search(r"\d{3,6} ?[一-鿿]", value)
    if match is None:
        # 退而求其次，從第一段連續兩個以上的中文開始（跳過「中 」這種單字雜訊）。
        match = re.search(r"[一-鿿]{2,}", value)
    if match:
        value = value[match.start():]

    # 終點：截到最後一個中文/數字/右括號，砍掉尾端讀進來的雜訊（「…16號    ee」）。
    # 少了這一步，帶雜訊的版本會因為字串較長而被完整度評分誤判為「比較完整」。
    for pos in range(len(value) - 1, -1, -1):
        if value[pos].isdigit() or "一" <= value[pos] <= "鿿" or value[pos] in ")）":
            value = value[:pos + 1]
            break
    return value.strip()


def _address_quality(value):
    """評估一段文字有多像完整地址：地址元素越齊全、越長，分數越高。"""
    if not value:
        return -1
    indicators = sum(1 for k in _ADDRESS_KEYWORDS if k in value)
    score = indicators * 10
    if re.match(r"^\d{3,6}", value):          # 有郵遞區號開頭
        score += 15
    if re.search(r"\d+\s*號", value):          # 有門牌號
        score += 20
    if re.search(r"[市縣]", value):
        score += 10
    if re.search(r"[路街道]", value):
        score += 10
    score += min(len(value), 40)              # 較長者通常較完整，但設上限避免灌水
    return score


def _extract_address(lines, fields, used):
    """地址：收集所有像地址的行，取最完整的一個。

    不能像其他欄位一樣「取第一個命中的」——名片上的統一編號、發票/股票代號都含
    「號」字又帶數字，很容易先被誤判成地址（實測有樣本填進「統一編號：22615380」）。
    因此先排除這些明確不是地址的行，再用完整度評分挑最好的一個。
    """
    best = None
    best_index = None
    for index, line in enumerate(lines):
        if index in used:
            continue
        if any(marker in line for marker in _NOT_ADDRESS_MARKERS):
            continue
        if not any(k in line for k in _ADDRESS_KEYWORDS) or not re.search(r"\d", line):
            continue
        candidate = _tidy_address(line)
        # 只有「號」沒有其他地址元素的短行（多半是編號殘留）不算地址
        if len(candidate) < 6:
            continue
        if best is None or _address_quality(candidate) > _address_quality(best):
            best, best_index = candidate, index

    if best:
        fields["address"] = best
        used.add(best_index)


def _is_plausible_cjk_name(value):
    """排除看起來不像人名的中文短行。

    三種常見誤判：一是線條、圖示被讀成「一一」這類重複字或簡單筆畫；二是部門名
    （工程部、人力資源處）長度剛好也是 2~4 字；三是公司名被截斷後剩下的片段
    （「東佑達奈」）。最後再要求開頭是常見姓氏——這是最有效的一道，OCR 雜訊
    幾乎不可能剛好以姓氏開頭。
    """
    if len(set(value)) == 1:                       # 「一一」「口口」這類重複字
        return False
    if value.endswith(_ORG_SUFFIXES):              # 部門/單位名不是人名
        return False
    if all(char in _CJK_NOISE_CHARS for char in value):
        return False
    if value.startswith(_COMPOUND_SURNAMES):
        return True
    return value[0] in _COMMON_SURNAMES


def _is_plausible_latin_name(value):
    """排除 OCR 雜訊被誤認成英文姓名的情況。

    真正的英文姓名是 Title Case、每個字至少兩個字母（Roy Hsiao、Jeffery Wei）；
    而名片上的線條、標章被誤讀出來的多半是全大寫或全小寫的亂碼（HRD ARS、
    WR VE HA、ee ee），或含單字母的碎片（a Ha），用這幾條規則就能濾掉。

    另外要擋掉英文公司名：「Southport Corporation」同樣是 Title Case 兩個字，
    格式上和人名無法區分，只能靠公司字眼（Corporation/Inc/Ltd…）排除。
    """
    tokens = value.split()
    if not 2 <= len(tokens) <= 3:
        return False
    if value.isupper() or value.islower():
        return False
    if any(keyword.lower() in value.lower() for keyword in _LATIN_COMPANY_WORDS):
        return False
    return all(len(t) >= 2 and t[0].isupper() and t[1:].islower() for t in tokens)


def _name_segments(lines):
    """把每一行整理成「可能是姓名」的片段，依序產出。

    需要處理兩件事，而且兩者對「空白」的解讀正好相反：
      1. 去掉「中文與中文之間」的空白。名片姓名常刻意加大字距，Tesseract 也會把
         中文逐字斷開（「邱      創      正」），不併回來就比對不出姓名。
      2. 依大片空白切段。名片常是左右兩欄，版面分析會把同一水平線上的兩欄併成一行
         （「32091 桃園市…8號        許啟原」），姓名於是和地址或 Email 黏在同一行，
         整行既被其他欄位認領、又不符合姓名格式，姓名就這樣被漏掉。

    麻煩在於「字距」與「欄位間隔」都是一長串空白，無法用寬度可靠地區分：先合併會把
    兩欄黏死（8號 + 許啟原 中間也是中文接中文），先切段又會把加大字距的姓名拆成單字。
    因此兩種順序各做一遍，把結果都當候選；不合理的候選自然會被姓氏與格式檢查濾掉。
    """
    for line in lines:
        # 解讀一：先合併中文字距，再切段 → 救得回「邱 創 正 ␣␣␣ Michael…」
        merged_first = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", line).strip()
        # 解讀二：先切段，再各自合併中文字距 → 救得回「…8號 ␣␣␣ 許啟 原」
        split_first = [re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", seg)
                       for seg in re.split(r"\s{3,}", line)]

        seen = set()
        for part in re.split(r"\s{3,}", merged_first) + split_first:
            part = _clean_line(part)
            if part and part not in seen:
                seen.add(part)
                yield part


def _extract_name(lines, fields, used):
    """姓名：在所有片段裡找最像人名的一個。

    優先序為「中文＋英文並列」(黃良祺 Kevin) > 純中文 2~4 字 > 純英文兩三個單字。
    中文姓名的可信度高於英文（英文行也可能是部門名、標語），因此分層挑選而不是
    取第一個符合的。名片姓名通常字級最大、位置偏上，OCR 輸出大致保留上到下的
    順序，所以同一層級內取最先出現的。

    這裡刻意不看 used：姓名常和已被認領的欄位擠在同一行（見 _name_segments），
    跳過整行會連帶漏掉姓名。改成排除「內容和其他欄位重複」的片段來避免重複取用。
    """
    mixed = cjk = latin = None
    assigned = [fields.get(key, "") for key in ("company", "title", "address")]

    for candidate in _name_segments(lines):
        # 已經被歸到公司/職稱/地址的內容（或其片段）不會是姓名
        if any(other and (candidate in other or other in candidate) for other in assigned):
            continue

        match = _NAME_MIXED_RE.match(candidate)
        if match and mixed is None and _is_plausible_cjk_name(match.group(1)):
            mixed = match.group(1)
        elif _NAME_CJK_RE.match(candidate) and _is_plausible_cjk_name(candidate) and cjk is None:
            cjk = candidate
        elif (_NAME_EN_RE.match(candidate) and _is_plausible_latin_name(candidate)
              and latin is None):
            latin = candidate

    fields["name"] = mixed or cjk or latin or ""
