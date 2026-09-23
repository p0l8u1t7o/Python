"""
原始影像封存：以雜湊值命名複製一份，確保結果可追溯、可用新版本重新分析。
設備輸出資料夾的原始檔只讀取，不移動、不刪除、不修改。
"""
import os
import shutil
import time

from ..core.io import file_sha256


def archive_path(root, sha256, ext):
    t = time.localtime()
    return os.path.join(root, f"{t.tm_year:04d}", f"{t.tm_mon:02d}", sha256[:2], sha256 + ext.lower())


def store(root, src, sha256=None):
    """複製 src 至封存區並驗證雜湊值；已封存 (相同雜湊值) 時直接回傳既有路徑"""
    sha256 = sha256 or file_sha256(src)
    ext = os.path.splitext(src)[1] or ".bin"
    dst = archive_path(root, sha256, ext)
    if os.path.isfile(dst) and file_sha256(dst) == sha256:
        return dst, sha256
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    shutil.copyfile(src, tmp)
    if file_sha256(tmp) != sha256:
        os.remove(tmp)
        raise IOError(f"archive verification failed: {src}")
    os.replace(tmp, dst)
    return dst, sha256
