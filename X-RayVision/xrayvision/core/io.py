"""影像載入與格式判定"""
import hashlib
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

IMAGE_EXTENSIONS = (".tif", ".tiff", ".png", ".bmp", ".jpg", ".jpeg")

# 影像種類
KIND_RAW16 = "raw16"     # 偵測器 16-bit 原始影像 (灰階線性，可做定量量測)
KIND_RGB8 = "rgb8"       # 檢視軟體轉存的 8-bit 影像 (灰階已被拉伸，量測結果僅供參考)


class ImageFormatError(ValueError):
    """影像無法讀取或格式不支援；code 對應語系檔 error.<code>"""

    def __init__(self, code, path):
        super().__init__(f"{code}: {path}")
        self.code = code
        self.path = path


@dataclass
class ImageData:
    path: str
    pixels: np.ndarray           # 單通道：raw16 為 uint16，rgb8 為 uint8
    kind: str
    sha256: str
    source_channels: int = 1
    meta: dict = field(default_factory=dict)

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def shape(self):
        return self.pixels.shape

    @property
    def is_raw(self):
        return self.kind == KIND_RAW16


def file_sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_image(path):
    """
    讀取影像並判定種類。
    - 單通道 16-bit：raw16
    - 8-bit (灰階、RGB 或 RGBA)：轉灰階後為 rgb8
    其他格式 (浮點、32-bit、多頁) 不支援。
    """
    if not os.path.isfile(path):
        raise ImageFormatError("file_not_found", path)
    # cv2.imread 不支援非 ASCII 路徑，改用 imdecode
    buf = np.fromfile(path, dtype=np.uint8)
    im = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise ImageFormatError("unreadable_image", path)
    channels = 1 if im.ndim == 2 else im.shape[2]
    if im.ndim == 3:
        if im.dtype != np.uint8:
            raise ImageFormatError("unsupported_format", path)
        im = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY)
    if im.dtype == np.uint16:
        kind = KIND_RAW16
    elif im.dtype == np.uint8:
        kind = KIND_RGB8
    else:
        raise ImageFormatError("unsupported_format", path)
    return ImageData(path=os.path.abspath(path), pixels=im, kind=kind, sha256=file_sha256(path),
                     source_channels=channels)


def list_images(inputs):
    """展開檔案與資料夾 (不遞迴)，依檔名排序"""
    files = []
    for p in inputs:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(IMAGE_EXTENSIONS))
        else:
            files.append(p)
    return files
