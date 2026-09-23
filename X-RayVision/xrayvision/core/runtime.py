"""
執行資源限制：本產品與 X 光設備控制軟體共用電腦，分析運算不得影響設備操作。
"""
import os
import sys

import cv2

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def default_workers():
    """預設使用一半的處理器核心 (至少 1)"""
    return max(1, (os.cpu_count() or 2) // 2)


def apply_limits(low_priority=True, cv_threads=1):
    """在目前行程套用限制：降低優先權、限制 OpenCV 執行緒數"""
    cv2.setNumThreads(cv_threads)
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, str(cv_threads))
    if not low_priority:
        return
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
    else:
        try:
            os.nice(5)
        except OSError:
            pass
