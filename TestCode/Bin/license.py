import json
import time
import winreg

SECRET = "mINi-pCdA-DaLic-eNSe"      #加密金鑰，加密和解密都需要。
DAY = 86400
TOLERANCE = 60                    # 容許用戶時間回退（NTP 校時）
LV_EPOCH = 2082844800              # 1904/01/01(Win) 至 1970/01/01(Unix)的秒數


class LicenseFile:
    """編碼、檔案與登錄檔讀寫、時間工具。"""

    MAGIC = "LIC1"          # 檔案/登錄值的格式標頭，用來快速辨識版本並擋掉明顯無效的內容
    M32 = 0xFFFFFFFF        # 32 位元遮罩，所有雜湊/LCG 運算都截斷在 32 位元內
    LCG_A, LCG_C = 1103515245, 12345  # 線性同餘產生器 (LCG) 的乘數與加數

    ROOT = winreg.HKEY_CURRENT_USER   # 只寫入目前使用者範圍，不需要系統管理員權限
    SUBKEY = r"AppKeys"
    D1, D2 = "Data1", "Data2" # Data1: 授權條款（user/days/start/expire）
                              # Data2: 最後一次檢查時間（last）


    def __init__(self, secret=SECRET):

        self.key = self.hash32(secret)

    # ---------------------------------------------------- 編碼
    @classmethod
    def hash32(cls, text, h=5381):
        """djb2: h = h * 33 + byte

        逐位元組把字串壓縮成一個 32 位元整數。這裡呼叫時傳入不同的初始值 h：
        - 預設 h=5381 時，用來把 secret 字串雜湊成 self.key。
        - 呼叫時傳入 h=self.key 時（見 encode/decode），
          則是把「secret 的雜湊」再混入「內容文字」，
          當作校驗碼，用來驗證解密出來的內容是否完整、未被竄改。
        """
        for b in text.encode("utf-8"):
            h = (h * 33 + b) & cls.M32
        return h

    def cipher(self, data):
        """XOR 金鑰流。加密解密是同一個動作。

        以 self.key 為起始狀態，每處理一個位元組就先用 LCG
        (s = s*A + C) 推進一次狀態，取新狀態的高位元組 (bits 16-23)
        當作這個位置的金鑰位元組，再與原始資料 XOR。
        因為 XOR 兩次會抵銷，且金鑰流只取決於 self.key（=secret）與
        資料在序列中的位置，所以加密與解密都呼叫同一支函式即可互逆。
        """
        s = self.key
        out = bytearray()
        for b in data:
            s = (s * self.LCG_A + self.LCG_C) & self.M32
            out.append(b ^ ((s >> 16) & 0xFF))
        return bytes(out)

    def encode(self, data):
        """將 dict 編碼成純 ASCII 字串，格式為：
            MAGIC(4) + checksum(8 hex) + ciphertext(hex, 每 byte 2 碼)
        checksum 是「明文文字」以 self.key 為起始值做 djb2 雜湊的結果，
        用來在 decode() 時驗證還原出的內容是否正確（密鑰正確 + 未遭竄改）。
        整段輸出全部是十六進位大寫字元，方便 LabVIEW 端當字串直接解析。
        """
        text = json.dumps(data, separators=(",", ":"))
        return (f"{self.MAGIC}{self.hash32(text, self.key):08X}"
                f"{self.cipher(text.encode('utf-8')).hex().upper()}")

    def decode(self, blob):
        """將 encode() 產生的字串還原成原始 dict。

        blob 可能來自登錄檔（REG_SZ 讀出時常帶有結尾的 \\x00 或空白）
        或 .lic 檔案，因此先做多輪 strip 清理雜訊字元，再統一轉大寫
        以兼容大小寫混雜的十六進位輸入。
        接著拆出 checksum(4:12) 與密文(12:)，用 cipher() 還原成明文，
        並重新計算 checksum 比對，任何不符（格式錯誤、secret 不對、
        內容被改過）都會拋出 ValueError，交由呼叫端統一視為
        「授權檔/登錄資料已損毀或遭竄改」。
        """
        blob = blob.strip().strip("\x00").strip().upper()
        if not blob.startswith(self.MAGIC) or len(blob) < 12:
            raise ValueError
        text = self.cipher(bytes.fromhex(blob[12:])).decode("utf-8")
        if self.hash32(text, self.key) != int(blob[4:12], 16):
            raise ValueError
        return json.loads(text)

    # ---------------------------------------------------- .lic 檔
    def file_save(self, path, data):
        """將 dict 編碼後覆寫寫入 .lic 檔案。"""
        with open(path, "w") as f:
            f.write(self.encode(data))

    def file_load(self, path):
        """讀取 .lic 檔案並解碼回 dict；檔案不存在時拋出 FileNotFoundError。"""
        with open(path) as f:
            return self.decode(f.read().strip())

    # ---------------------------------------------------- 登錄檔
    def reg_set(self, name, data):
        """將 dict 編碼後寫入 HKCU\\AppKeys 底下指定名稱的 REG_SZ 值。
        CreateKeyEx 會在子機碼不存在時自動建立，因此第一次啟用時
        不需要另外檢查/建立 AppKeys 機碼。"""
        with winreg.CreateKeyEx(self.ROOT, self.SUBKEY, 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, self.encode(data))

    def reg_get(self, name):
        """讀取並解碼登錄檔中指定名稱的值；機碼或數值不存在時
        winreg 會拋出 FileNotFoundError，與 .lic 檔案不存在時的例外一致，
        方便呼叫端用同一組 except 處理『尚未啟用』的狀況。"""
        with winreg.OpenKey(self.ROOT, self.SUBKEY, 0, winreg.KEY_READ) as k:
            blob, _ = winreg.QueryValueEx(k, name)
        return self.decode(blob)

    def reg_clear(self):
        """移除整個 AppKeys 機碼（Data1、Data2 一併刪除），
        供解除安裝或重置授權狀態時呼叫；機碼原本就不存在則靜默略過。"""
        try:
            winreg.DeleteKey(self.ROOT, self.SUBKEY)
        except FileNotFoundError:
            pass

    # ---------------------------------------------------- 時間（UTC 秒數）
    @staticmethod
    def now():
        """當下時間，1904/01/01 UTC 起算的秒數

        time.time() 回傳的是 Unix epoch（1970/01/01 UTC）秒數，
        加上 LV_EPOCH（兩個紀元之間的秒數差）即可轉成 LabVIEW 的
        Get Date/Time In Seconds 所使用的時間戳格式，讓 Python 與
        LabVIEW 兩端可以用同一個整數直接比較大小，不必互相換算。
        """
        return int(time.time()) + LV_EPOCH

    @staticmethod
    def show(ts):
        """秒數 -> 可讀的 UTC 字串，僅供訊息顯示

        將 LabVIEW 時間戳（1904 紀元）先扣回 LV_EPOCH 還原成 Unix
        epoch 秒數，再用 gmtime 轉成 UTC 時間字串；只用於組成
        回傳訊息，不影響任何比較或判斷邏輯。
        """
        return time.strftime("%Y/%m/%d %H:%M:%S",
                             time.gmtime(int(ts) - LV_EPOCH))









# ==================範例程式========================================


def license_gen(path, username, days):
    """產生 .lic 授權檔。以產生當下為開始時間，加上 days 為到期時間。"""
    lic = LicenseFile()
    now = lic.now()
    expire = now + int(days) * DAY
    lic.file_save(path, {"user": str(username), "days": int(days),
                         "start": now, "expire": expire, "used": 0})
    return f"OK|已產生 {days} 天授權，到期 {lic.show(expire)} UTC|{username}"


def license_active(path):
    """讀取 .lic 並啟用，將授權寫入登錄檔 Data1 / Data2。

    啟用前會做兩層防護：
    1. 檢查 .lic 檔本身的 used 旗標 —— 若非 0 代表這份檔案已經在某個時間
       啟用過，直接拒絕，防止同一份授權檔被複製到多台機器分別啟用。
    2. 檢查本機登錄檔 Data1 是否已存在有效的 start —— 若有，代表本機
       已經啟用過其他授權，同樣拒絕（reg_get 找不到機碼/數值時視為
       尚未啟用，屬正常狀況，故用 try/except 吞掉例外繼續往下走）。

    通過檢查後，再驗證 .lic 檔本身記錄的 start/expire 是否落在合理區間
    （理論上剛產生的授權檔不會到期或尚未生效，這裡是保險性檢查），
    最後把授權條款寫入 Data1、把目前時間當作首次的 last 寫入 Data2，
    並回寫 .lic 檔把 used 標記為目前時間，完成啟用。
    """
    lic = LicenseFile()
    try:
        f = lic.file_load(path)
    except FileNotFoundError:
        return "FAIL|找不到授權檔|"
    except (ValueError, KeyError, UnicodeDecodeError):
        return "FAIL|授權檔已損毀或遭竄改|"

    if f["used"]:
        return f"FAIL|此授權檔已於 {lic.show(f['used'])} UTC 使用過|{f['user']}"

    try:
        if lic.reg_get(lic.D1)["start"]:
            return "FAIL|本機已啟用過授權|"
    except (FileNotFoundError, ValueError, KeyError, UnicodeDecodeError):
        # 登錄檔不存在、或內容無法解碼，都代表本機尚未啟用過任何授權，
        # 屬正常情況，直接放行繼續啟用流程。
        pass

    now = lic.now()
    if now > f["expire"]:
        return f"FAIL|授權已於 {lic.show(f['expire'])} UTC 到期，無法啟用|{f['user']}"
    if now < f["start"]:
        return f"FAIL|授權尚未生效（{lic.show(f['start'])} UTC 起）|{f['user']}"

    # 只把授權條款（user/days/start/expire）寫進 Data1，used 旗標留在
    # .lic 檔案裡即可，登錄檔不需要這個欄位。
    lic.reg_set(lic.D1, {"user": f["user"], "days": f["days"],
                         "start": f["start"], "expire": f["expire"]})
    # Data2 只存最後一次檢查時間，啟用當下即為第一筆記錄。
    lic.reg_set(lic.D2, {"last": now})

    f["used"] = now
    lic.file_save(path, f)
    return f"OK|啟用成功，到期 {lic.show(f['expire'])} UTC|{f['user']}"


def license_check():
    """驗證授權。回傳 OK/FAIL|訊息|使用者|到期日(UTC)|剩餘天數

    不需要 path 參數，因為驗證只看登錄檔（Data1 授權條款 + Data2 最後執行
    時間），完全不依賴 .lic 檔案是否還存在。驗證依序檢查：
    1. Data1/Data2 是否存在、能否正確解碼（未損毀/未遭竄改，也代表尚未啟用）。
    2. now < start：理論上不該發生，除非系統時間被調到比啟用當下還早。
    3. now > expire：已超過授權天數，判定到期。
    4. now < last - TOLERANCE：防止使用者把系統時間往回調來延長試用期——
       每次驗證通過都會把 Data2.last 更新成目前時間，若下次驗證時的
       系統時間反而「早於」上次記錄的 last 超過 TOLERANCE（5 分鐘），
       就代表時間被人為回撥過，直接判定失敗。TOLERANCE 抓 5 分鐘是為了
       容忍系統做 NTP 校時時可能出現的小幅度時間回調，避免誤判。
    全部通過後才更新 Data2.last 並回傳 OK，讓下一次的時間回撥偵測有最新基準。
    """
    lic = LicenseFile()
    try:
        d1 = lic.reg_get(lic.D1)
        d2 = lic.reg_get(lic.D2)
    except FileNotFoundError:
        return "FAIL|尚未啟用|||0"
    except (ValueError, KeyError, UnicodeDecodeError):
        return "FAIL|授權資料已損毀或遭竄改|||0"

    now = lic.now()
    start, expire, last = d1["start"], d1["expire"], d2["last"]
    # tail 是共用的回傳訊息尾段（使用者|到期日|剩餘天數），
    # 不論成功或失敗都附上，方便呼叫端顯示授權資訊；
    # 剩餘天數用整數除法無條件捨去，並以 max(0, ...) 避免出現負數。
    tail = f"{d1['user']}|{lic.show(expire)}|{max(0, (expire - now) // DAY)}"

    if now < start:
        return f"FAIL|授權尚未生效|{tail}"
    if now > expire:
        return f"FAIL|授權已到期|{tail}"
    if now < last - TOLERANCE:
        return f"FAIL|偵測到系統時間異常|{tail}"

    # 驗證通過：更新 Data2.last 為目前時間；取 max 是保險寫法，
    # 理論上會走到這裡時 now 必定 >= last，避免邊界狀況把 last 往回寫。
    lic.reg_set(lic.D2, {"last": max(now, last)})
    return f"OK|驗證通過|{tail}"


if __name__ == "__main__":
    # 簡單的命令列測試流程：僅產生授權檔並印出結果；
    # 下面兩行啟用/驗證預設註解關閉，需要時再手動打開測試。
    #print(license_gen("license.lic", input("使用者名稱: ").strip(),int(input("授權天數: ").strip())))
    print(license_active("license.vlic"))
    #print(license_check())