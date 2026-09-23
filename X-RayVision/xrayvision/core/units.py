"""像素尺寸換算 (成像條件對策第三層)：以 _px 結尾的量測值自動加上 _um 值，_px2 (面積) 加上 _um2 值"""


def add_um(d, pixel_size_um):
    """d 中以 _px 結尾的數值鍵加上 _um 鍵、以 _px2 結尾的加上 _um2 鍵 (pixel_size_um 為 None 時不變)"""
    if not pixel_size_um or not isinstance(d, dict):
        return d
    for k in list(d):
        v = d[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        if k.endswith("_px"):
            d[k[:-3] + "_um"] = v * pixel_size_um
        elif k.endswith("_px2"):
            d[k[:-4] + "_um2"] = v * pixel_size_um ** 2
    return d
