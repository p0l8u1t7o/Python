import mmap
import cv2 as cv
import numpy as np

# fmt -> (dtype, bytes_per_pixel, channels)
FORMATS = {
    "u8":    (np.uint8,   1, 1),
    "u16":   (np.uint16,  2, 1),
    "i16":   (np.int16,   2, 1),
    "sgl":   (np.float32, 4, 1),
    "rgb32": (np.uint8,   4, 4),   # 記憶體順序 BGRA
}


# ==================================================
# MMap Reader
# ==================================================

class MMapReader:
    """讀取 LabVIEW 寫入的共享記憶體。

    line_width 為 IMAQ GetImageInfo 的 Line Width（單位像素，含 padding）。
    size 為映射總長度，0 表示只有單張影像。
    """

    def __init__(self, tag_name, width, height, line_width=0, fmt="u8", size=0):

        self.dtype, bpp, self.ch = FORMATS[fmt]
        self.w, self.h = width, height
        self.row = (line_width or width) * bpp
        self.valid = width * bpp
        self.frame_bytes = self.row * height

        self.mm = mmap.mmap(-1, size or self.frame_bytes,
                            tagname=tag_name, access=mmap.ACCESS_READ)
        self.buf = np.frombuffer(self.mm, dtype=np.uint8)
        self.buf[::4096].sum()          # prefault，把 page fault 成本移到開場

    def read_frame(self, offset=0, copy=False):
        """回傳影像。copy=False 為 zero-copy view。"""
        raw = self.buf[offset:offset + self.frame_bytes].reshape(self.h, self.row)
        blk = raw[:, :self.valid]

        if copy or (self.dtype != np.uint8 and not blk.flags["C_CONTIGUOUS"]):
            blk = np.ascontiguousarray(blk)

        arr = blk if self.dtype == np.uint8 else blk.view(self.dtype)
        return arr.reshape(self.h, self.w, self.ch) if self.ch > 1 \
            else arr.reshape(self.h, self.w)

    def close(self):
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

_READERS = {}


def lv_open(tag, width, height, line_width=0, fmt="u8", size=0):
    if tag in _READERS:
        _READERS.pop(tag).close()
    _READERS[tag] = MMapReader(tag, int(width), int(height),
                               int(line_width), str(fmt), int(size))
    r = _READERS[tag]
    return f"OK {tag} {r.w}x{r.h} row={r.row} frame={r.frame_bytes:,}"


def lv_stats(tag, offset=0, sample=8):
    """抽樣統計，約 1 ms。可放在 LabVIEW 迴圈裡輪詢。"""
    a = _READERS[tag].read_frame(int(offset))[::int(sample), ::int(sample)]
    return (f"OK min/max={a.min()}/{a.max()} "
            f"mean={a.mean():.2f} std={a.std():.2f}")


def lv_show(tag, offset=0, wait_ms=1000, max_side=900):
    a = _READERS[tag].read_frame(int(offset))
    step = max(1, max(a.shape[:2]) // int(max_side))
    d = np.ascontiguousarray(a[::step, ::step])

    if d.ndim == 3:
        d = d[:, :, :3]
    elif d.dtype != np.uint8:
        d = cv.normalize(d, None, 0, 255, cv.NORM_MINMAX).astype(np.uint8)

    #cv.imshow(tag, d)
    #cv.waitKey(int(wait_ms))
    #cv.destroyAllWindows()
    return f"OK shape={a.shape} disp={d.shape}"



def lv_close(tag=""):
    for t in ([tag] if tag else list(_READERS)):
        _READERS.pop(t).close()
    return "OK"