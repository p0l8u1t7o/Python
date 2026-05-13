import numpy as np
import cv2 as cv
import mmap

class SharedImageContext:
    def __init__(self):
        self.mm = None
        self.view = None
        self.num_elements = 0


ctx = SharedImageContext()


# ==============================
# 初始化（只做一次 mmap）
# ==============================
def initialize(tag_name, num_elements):

    global ctx

    ctx.num_elements = num_elements

    # 建立 shared memory mapping（只做一次）
    ctx.mm = mmap.mmap(
        -1,
        num_elements,
        tagname=tag_name,
        access=mmap.ACCESS_READ
    )

    # 只建立 view，不 copy
    ctx.view = np.frombuffer(ctx.mm, dtype=np.uint8, count=num_elements)


# ==============================
# 分享記憶體空間
# ==============================
def shared_memory(tag_name=None, num_elements=None):

    global ctx

    if ctx.mm is None:
        raise RuntimeError("Shared memory not initialized")

    # 直接用 view（zero-copy）
    buffer_view = ctx.view

    # JPEG / PNG decode（這一步才是主要成本）
    image = cv.imdecode(buffer_view, cv.IMREAD_GRAYSCALE)
    
    #cv.imshow("Shared Memory Image", image)
    #cv.waitKey(0)


# ==============================
# 清理（正確釋放 mmap）
# ==============================
def cleanup():

    global ctx

    if ctx.view is not None:
        del ctx.view
        ctx.view = None

    if ctx.mm is not None:
        ctx.mm.close()
        ctx.mm = None

    ctx.num_elements = 0