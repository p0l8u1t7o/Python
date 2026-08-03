"""透過具名共享記憶體（Named Shared Memory）讀取 LabVIEW IMAQ 影像的工具模組。

供 LabVIEW Python Node 呼叫：lv_open 建立/更新 reader，lv_stats / lv_show
用於除錯或顯示，lv_close 釋放資源。
"""

import mmap
import cv2 as cv
import numpy as np

# fmt（IMAQ 影像型別代碼）-> (dtype, bytes_per_pixel, channels)
# bytes_per_pixel 為單一像素「所有 channel 加總」的位元組數，
# 用來換算每一列（row）在記憶體中的實際跨距（stride）。
FORMATS = {
    0: (np.uint8,   1, 1),   # Grayscale (U8)
    1: (np.int16,   2, 1),   # Grayscale (I16)
    2: (np.float32, 4, 1),   # Grayscale (SGL)
    4: (np.uint8,   4, 4),   # RGB (U32)，記憶體順序 BGRA
    5: (np.uint8,   4, 4),   # HSL (U32)
    6: (np.uint16,  8, 4),   # RGB (U64)，每個 channel 16-bit
    7: (np.uint16,  2, 1),   # Grayscale (U16)
}


# ==================================================
# MMap Reader
# ==================================================

class MMapReader:
    """讀取 LabVIEW 寫入的共享記憶體。

    line_width 為 IMAQ GetImageInfo 的 Line Width（單位像素，含 padding）。
    size 為映射總長度，0 表示只有單張影像。
    """

    def __init__(self, tag_name, width, height, line_width=0, fmt=0, size=0):
        """開啟指定 tag 的具名共享記憶體並準備好讀取用的中介資訊。

        參數：
            tag_name:   LabVIEW 端建立共享記憶體時使用的名稱。
            width:      影像實際寬度（像素）。
            height:     影像實際高度（像素）。
            line_width: IMAQ GetImageInfo 回傳的 Line Width（像素，含 padding）；
                        0 表示沒有 padding，等同 width。
            fmt:        影像型別代碼，對應 FORMATS 字典的 key。
            size:       整段共享記憶體的總長度（bytes）；0 表示只映射單張影像。
        """
        self.dtype, bpp, self.ch = FORMATS[fmt]
        self.w, self.h = width, height
        self.row = (line_width or width) * bpp   # 每一列在記憶體中的實際 byte 數（含 padding）
        self.valid = width * bpp                  # 每一列中真正有效影像資料的 byte 數
        self.frame_bytes = self.row * height       # 單張影像佔用的總 byte 數

        # 以唯讀模式開啟 LabVIEW 已建立好的具名記憶體對映；
        # size 為 0 時代表只有單張影像，用 frame_bytes 當作映射長度。
        self.mm = mmap.mmap(-1, size or self.frame_bytes,
                            tagname=tag_name, access=mmap.ACCESS_READ)
        self.buf = np.frombuffer(self.mm, dtype=np.uint8)
        self.buf[::4096].sum()          # prefault，把 page fault 成本移到開場

    def read_frame(self, offset=0, copy=False):
        """從共享記憶體讀出一張影像，回傳 numpy array。

        參數：
            offset: 該影像在共享記憶體中的起始 byte 位移（多張影像串接時使用）。
            copy:   True 時強制回傳獨立複製；False（預設）盡量回傳 zero-copy view，
                    共享同一塊記憶體，效能較好但資料可能隨下次寫入而改變。
        """
        # 依 row（含 padding）切成 (h, row) 的 2D view，再裁掉 padding 只留有效資料
        raw = self.buf[offset:offset + self.frame_bytes].reshape(self.h, self.row)
        blk = raw[:, :self.valid]

        # uint8 以外的型別若不是連續記憶體（因裁切 padding 而不連續），
        # view() 轉型前必須先複製成連續記憶體，否則會出錯或結果不正確。
        if copy or (self.dtype != np.uint8 and not blk.flags["C_CONTIGUOUS"]):
            blk = np.ascontiguousarray(blk)

        # uint8 直接使用（沒有型別轉換需求），其餘型別以 view 重新解讀底層 bytes
        arr = blk if self.dtype == np.uint8 else blk.view(self.dtype)
        return arr.reshape(self.h, self.w, self.ch) if self.ch > 1 \
            else arr.reshape(self.h, self.w)

    def close(self):
        """釋放 numpy view 與 mmap 物件。"""
        self.buf = None
        self.mm.close()
        self.mm = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ==================================================
# LabVIEW Python Node Wrapper
# ==================================================
# 以下函式供 LabVIEW Python Node 直接呼叫；參數皆為基本型別（字串/數字），
# 回傳值為字串，方便 LabVIEW 端解析與顯示。

_READERS = {}   # tag -> MMapReader，記錄目前已開啟的所有共享記憶體


def lv_open(tag, width, height, line_width=0, fmt=0, size=0):
    """建立（或重新建立）指定 tag 的 MMapReader，並存入 _READERS 供後續呼叫使用。

    若同一個 tag 已存在對應的 reader，會先關閉舊的再重新開啟，
    避免 LabVIEW 重複呼叫（例如影像規格變更）時造成記憶體對映洩漏。
    回傳一段描述字串供 LabVIEW 顯示，內容包含實際 row/frame 大小以利除錯。
    """
    if tag in _READERS:
        _READERS.pop(tag).close()
    _READERS[tag] = MMapReader(tag, int(width), int(height),
                               int(line_width), int(fmt), int(size))
    r = _READERS[tag]
    return f"OK {tag} {r.w}x{r.h} row={r.row} frame={r.frame_bytes:,}"


def lv_stats(tag, offset=0, sample=8):
    """抽樣統計，約 1 ms。可放在 LabVIEW 迴圈裡輪詢。

    sample: 取樣間距（每隔 sample 個像素取一點），數值越大速度越快、精度越低，
    用於即時監看影像是否正常更新，而非精確統計。
    """
    a = _READERS[tag].read_frame(int(offset))[::int(sample), ::int(sample)]
    return (f"OK min/max={a.min()}/{a.max()} "
            f"mean={a.mean():.2f} std={a.std():.2f}")


def lv_show(tag, offset=0, wait_ms=1000, max_side=900):
    """讀取一張影像並用 OpenCV 顯示，主要用於本機除錯確認影像內容。

    max_side: 顯示視窗長邊的目標像素數，過大的影像會依比例downsample後再顯示，
    避免視窗超出螢幕範圍。
    """
    a = _READERS[tag].read_frame(int(offset))
    step = max(1, max(a.shape[:2]) // int(max_side))   # 依長邊換算縮放步距
    d = np.ascontiguousarray(a[::step, ::step])

    if d.ndim == 3:
        d = d[:, :, :3]   # 多 channel 影像（如 RGB/HSL）僅取前三個 channel 顯示，丟棄 alpha
    elif d.dtype != np.uint8:
        # 非 uint8 的灰階影像（I16/SGL/U16）需正規化到 0-255 才能用 imshow 正確顯示
        d = cv.normalize(d, None, 0, 255, cv.NORM_MINMAX).astype(np.uint8)

    cv.imshow(tag, d)
    cv.waitKey(int(wait_ms))
    cv.destroyAllWindows()
    return f"OK shape={a.shape} disp={d.shape}"


def lv_close(tag=""):
    """關閉指定 tag 的 reader；tag 為空字串時關閉所有已開啟的 reader。"""
    for t in ([tag] if tag else list(_READERS)):
        _READERS.pop(t).close()
    return "OK"