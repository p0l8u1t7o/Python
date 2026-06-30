"""
測試 Shared Memory 影像讀取時間
直接執行：python test_mmap_timing.py

測試項目：
  1. imdecode 耗時（灰階 / 彩色）
  2. 每幀平均 / 最小 / 最大 / 標準差
  3. 吞吐量（FPS）
"""

import numpy as np
import cv2 as cv
import mmap
import time
import os
import sys


# ╔══════════════════════════════════════════════════════════════╗
# ║                     ▼  請在這裡修改設定  ▼                   ║
# ╠══════════════════════════════════════════════════════════════╣

TAG_NAME     = "Image001"   # ← Shared Memory 名稱（與 LabVIEW 一致）
NUM_ELEMENTS = 1920 * 1080 * 3       # ← Shared Memory 大小（bytes）

TEST_FRAMES  = 500                   # 測試幀數
WARMUP_FRAMES = 20                   # 前 N 幀不計入統計（暖機）

# 測試模式：
#   "live"   → 從 Shared Memory 即時讀取（需要 LabVIEW 先送資料）
#   "dummy"  → 用假的 JPEG buffer 模擬（不需要 LabVIEW，純測試 imdecode 速度）
MODE = "live"

# dummy 模式的假影像設定
DUMMY_WIDTH  = 1280
DUMMY_HEIGHT = 720
DUMMY_QUALITY = 85   # JPEG 壓縮品質（影響 buffer 大小與 decode 時間）

# ╚══════════════════════════════════════════════════════════════╝


# ==================================================
# SharedImageContext
# ==================================================

class SharedImageContext:
    def __init__(self):
        self.mm           = None
        self.view         = None
        self.num_elements = 0


def initialize(tag_name, num_elements):
    ctx = SharedImageContext()
    ctx.num_elements = num_elements
    ctx.mm = mmap.mmap(
        -1,
        num_elements,
        tagname=tag_name,
        access=mmap.ACCESS_READ
    )
    ctx.view = np.frombuffer(ctx.mm, dtype=np.uint8, count=num_elements)
    return ctx


def get_image(ctx):
    if ctx.mm is None:
        raise RuntimeError("Shared memory not initialized")
    return cv.imdecode(ctx.view, cv.IMREAD_GRAYSCALE)


def get_image_color(ctx):
    if ctx.mm is None:
        raise RuntimeError("Shared memory not initialized")
    return cv.imdecode(ctx.view, cv.IMREAD_COLOR)


def cleanup(ctx):
    if ctx.view is not None:
        del ctx.view
        ctx.view = None
    if ctx.mm is not None:
        ctx.mm.close()
        ctx.mm = None
    ctx.num_elements = 0


# ==================================================
# Dummy JPEG buffer 產生器（模擬 Shared Memory 內容）
# ==================================================

def _make_dummy_jpeg_view(width, height, quality):
    """產生假的 JPEG buffer，模擬從 Shared Memory 讀到的資料"""
    img = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    ok, buf = cv.imencode(".jpg", img, [cv.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("imencode failed")
    jpeg_bytes = buf.tobytes()
    # 填入固定大小 buffer（模擬 mmap view）
    arr = np.zeros(NUM_ELEMENTS, dtype=np.uint8)
    arr[:len(jpeg_bytes)] = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    print(f"  Dummy JPEG size : {len(jpeg_bytes) / 1024:.1f} KB")
    return arr


# ==================================================
# 計時工具
# ==================================================

class Timer:
    def __init__(self, name):
        self.name    = name
        self.samples = []

    def record(self, elapsed_ms):
        self.samples.append(elapsed_ms)

    def report(self):
        if not self.samples:
            print(f"  [{self.name}] no data")
            return
        arr = np.array(self.samples)
        print(f"  [{self.name}]")
        print(f"    幀數    : {len(arr)}")
        print(f"    平均    : {arr.mean():.3f} ms")
        print(f"    最小    : {arr.min():.3f} ms")
        print(f"    最大    : {arr.max():.3f} ms")
        print(f"    標準差  : {arr.std():.3f} ms")
        print(f"    P95     : {np.percentile(arr, 95):.3f} ms")
        print(f"    P99     : {np.percentile(arr, 99):.3f} ms")
        print(f"    FPS     : {1000 / arr.mean():.1f}")


# ==================================================
# 測試主流程
# ==================================================

def run_live():
    """從 Shared Memory 即時讀取（需要 LabVIEW 已在執行）"""
    print(f"\n[模式] LIVE  tag={TAG_NAME}  size={NUM_ELEMENTS/1024:.0f} KB")

    try:
        ctx = initialize(TAG_NAME, NUM_ELEMENTS)
    except Exception as e:
        print(f"[ERROR] 無法開啟 Shared Memory：{e}")
        print("        請確認 LabVIEW 已啟動並寫入資料後再執行")
        sys.exit(1)

    t_gray  = Timer("imdecode GRAYSCALE")
    t_color = Timer("imdecode COLOR")
    t_total = Timer("總耗時（含 numpy）")

    print(f"  Warm-up {WARMUP_FRAMES} 幀...")
    for _ in range(WARMUP_FRAMES):
        get_image(ctx)

    print(f"  開始計時 {TEST_FRAMES} 幀...\n")

    for i in range(TEST_FRAMES):
        t0 = time.perf_counter()
        img_gray = get_image(ctx)
        t1 = time.perf_counter()
        img_color = get_image_color(ctx)
        t2 = time.perf_counter()

        t_gray.record((t1 - t0) * 1000)
        t_color.record((t2 - t1) * 1000)
        t_total.record((t2 - t0) * 1000)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{TEST_FRAMES} 幀  gray={t_gray.samples[-1]:.2f}ms  color={t_color.samples[-1]:.2f}ms")

    cleanup(ctx)
    return t_gray, t_color, t_total


def run_dummy():
    """用假 JPEG buffer 測試 imdecode 純速度"""
    print(f"\n[模式] DUMMY  {DUMMY_WIDTH}×{DUMMY_HEIGHT}  JPEG Q={DUMMY_QUALITY}")

    view = _make_dummy_jpeg_view(DUMMY_WIDTH, DUMMY_HEIGHT, DUMMY_QUALITY)

    t_gray  = Timer("imdecode GRAYSCALE")
    t_color = Timer("imdecode COLOR")
    t_total = Timer("總耗時（兩次 decode）")

    print(f"  Warm-up {WARMUP_FRAMES} 幀...")
    for _ in range(WARMUP_FRAMES):
        cv.imdecode(view, cv.IMREAD_GRAYSCALE)
        cv.imdecode(view, cv.IMREAD_COLOR)

    print(f"  開始計時 {TEST_FRAMES} 幀...\n")

    for i in range(TEST_FRAMES):
        t0 = time.perf_counter()
        cv.imdecode(view, cv.IMREAD_GRAYSCALE)
        t1 = time.perf_counter()
        cv.imdecode(view, cv.IMREAD_COLOR)
        t2 = time.perf_counter()

        t_gray.record((t1 - t0) * 1000)
        t_color.record((t2 - t1) * 1000)
        t_total.record((t2 - t0) * 1000)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{TEST_FRAMES} 幀  gray={t_gray.samples[-1]:.2f}ms  color={t_color.samples[-1]:.2f}ms")

    return t_gray, t_color, t_total


# ==================================================
# Main
# ==================================================

if __name__ == "__main__":

    print("=" * 60)
    print("  Shared Memory 影像讀取時間測試")
    print("=" * 60)
    print(f"  NUM_ELEMENTS : {NUM_ELEMENTS:,} bytes  ({NUM_ELEMENTS/1024:.0f} KB)")
    print(f"  TEST_FRAMES  : {TEST_FRAMES}")
    print(f"  WARMUP_FRAMES: {WARMUP_FRAMES}")

    if MODE == "live":
        t_gray, t_color, t_total = run_live()
    else:
        t_gray, t_color, t_total = run_dummy()

    print("\n" + "=" * 60)
    print("  測試結果")
    print("=" * 60)
    t_gray.report()
    print()
    t_color.report()
    print()
    t_total.report()

    print("\n" + "=" * 60)
    avg_total = np.mean(t_total.samples)
    print(f"  理論最大 FPS（imdecode）: {1000/avg_total:.1f}")
    print(f"  建議 LabVIEW 送幀間隔   : {avg_total:.1f} ms 以上")
    print("=" * 60)