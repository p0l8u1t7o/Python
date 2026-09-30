"""
檢測區域 (規劃書 PLAN-002 第 4 節)：配方可設定包含區域與排除區域，模組只處理
中心落在包含區域內、且不在排除區域內的目標；未設定包含區域時為整張影像。

配方格式 (選用欄位 regions)：
  {
    "reference": {"width": 2768, "height": 2160, "run_id": 12},   框選時的參考影像尺寸 (與來源紀錄)
    "include": [{"type": "rect", "x0":…, "y0":…, "x1":…, "y1":…}, {"type": "polygon", "points": [[x, y], …]}],
    "exclude": [...]
  }
座標為參考影像的像素座標；分析影像尺寸不同時依寬高比例縮放。

圖形選用欄位 (PLAN-004 第 3.2 節)：
  label      顯示名稱 (最多 32 字)
  as_array   僅包含區域可用；區域內的目標強制成為同一個陣列 (模組需宣告 supports_region_arrays)
"""
import cv2
import numpy as np

KINDS = ("include", "exclude")
MAX_SHAPES = 50
MAX_POINTS = 200
MAX_LABEL = 32


class RegionError(ValueError):
    pass


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
        raise RegionError(what)
    return float(v)


def normalize(d):
    """檢查並整理 regions；空或未設定時回傳 None"""
    if not d:
        return None
    if not isinstance(d, dict):
        raise RegionError("regions")
    ref = d.get("reference") or {}
    if not isinstance(ref, dict):
        raise RegionError("regions.reference")
    out = dict(reference=None, include=[], exclude=[])
    if ref:
        w, h = _num(ref.get("width"), "reference.width"), _num(ref.get("height"), "reference.height")
        if w < 1 or h < 1:
            raise RegionError("reference.size")
        out["reference"] = dict(width=int(w), height=int(h))
        if ref.get("run_id") is not None:
            out["reference"]["run_id"] = int(_num(ref["run_id"], "reference.run_id"))
    for kind in KINDS:
        shapes = d.get(kind) or []
        if not isinstance(shapes, list) or len(shapes) > MAX_SHAPES:
            raise RegionError(kind)
        for s in shapes:
            if not isinstance(s, dict):
                raise RegionError(kind)
            if s.get("type") == "rect":
                x0, y0, x1, y1 = (_num(s.get(k), f"{kind}.rect.{k}") for k in ("x0", "y0", "x1", "y1"))
                x0, x1 = sorted((x0, x1))
                y0, y1 = sorted((y0, y1))
                if x1 - x0 < 1 or y1 - y0 < 1:
                    raise RegionError(f"{kind}.rect.size")
                out[kind].append(dict(type="rect", x0=x0, y0=y0, x1=x1, y1=y1))
            elif s.get("type") == "polygon":
                pts = s.get("points")
                if not isinstance(pts, list) or not 3 <= len(pts) <= MAX_POINTS:
                    raise RegionError(f"{kind}.polygon.points")
                out[kind].append(dict(type="polygon", points=[[_num(p[0], "point"), _num(p[1], "point")]
                                                              for p in pts if isinstance(p, (list, tuple)) and len(p) == 2]))
                if len(out[kind][-1]["points"]) != len(pts):
                    raise RegionError(f"{kind}.polygon.points")
            else:
                raise RegionError(f"{kind}.type")
            _extras(s, out[kind][-1], kind)
    if not out["include"] and not out["exclude"]:
        return None
    if out["reference"] is None:
        raise RegionError("reference")
    return out


def _extras(src, dst, kind):
    """選用欄位；未設定時不寫入，舊格式整理後維持原樣"""
    label = src.get("label")
    if label not in (None, ""):
        if not isinstance(label, str) or len(label.strip()) > MAX_LABEL:
            raise RegionError(f"{kind}.label")
        if label.strip():
            dst["label"] = label.strip()
    as_array = src.get("as_array")
    if as_array not in (None, False):
        if as_array is not True or kind != "include":
            raise RegionError(f"{kind}.as_array")
        dst["as_array"] = True


def _scale(regions, shape):
    H, W = shape[:2]
    ref = regions["reference"]
    return W / ref["width"], H / ref["height"]


def _fill(m, s, val, sx, sy):
    if s["type"] == "rect":
        cv2.rectangle(m, (int(round(s["x0"] * sx)), int(round(s["y0"] * sy))),
                      (int(round(s["x1"] * sx)), int(round(s["y1"] * sy))), val, -1)
    else:
        pts = np.array([[p[0] * sx, p[1] * sy] for p in s["points"]], np.float64).round().astype(np.int32)
        cv2.fillPoly(m, [pts.reshape(-1, 1, 2)], val)


def array_shapes(regions):
    """勾選「視為一個陣列」的包含區域：[(序號 1 起, 圖形)]；序號對應 build_groups 的編號"""
    if not regions:
        return []
    return [(i, s) for i, s in enumerate((s for s in regions["include"] if s.get("as_array")), 1)]


def build_groups(regions, shape):
    """
    「視為一個陣列」區域編號遮罩 (int32，0 = 不屬於任何強制陣列)；沒有這類區域時回傳 None。
    區域重疊時，重疊部分屬於清單中較後面的區域 (與繪製順序一致)。
    """
    shapes = array_shapes(regions)
    if not shapes:
        return None
    sx, sy = _scale(regions, shape)
    m = np.zeros(shape[:2], np.int32)
    for i, s in shapes:
        _fill(m, s, int(i), sx, sy)
    return m


def group_at(groups, x, y):
    """點所在的強制陣列序號 (0 = 無)"""
    if groups is None:
        return 0
    H, W = groups.shape
    xi, yi = int(round(x)), int(round(y))
    return int(groups[yi, xi]) if 0 <= xi < W and 0 <= yi < H else 0


def build_mask(regions, shape):
    """
    依影像尺寸產生布林遮罩 (True = 檢測)；regions 為 None 時回傳 None。
    回傳 (mask, scaled)：scaled 表示影像尺寸與參考影像不同、座標已依比例縮放
    """
    if not regions:
        return None, False
    H, W = shape[:2]
    sx, sy = _scale(regions, shape)
    scaled = abs(sx - 1) > 1e-6 or abs(sy - 1) > 1e-6
    m = np.zeros((H, W), np.uint8) if regions["include"] else np.ones((H, W), np.uint8)
    for s in regions["include"]:
        _fill(m, s, 1, sx, sy)
    for s in regions["exclude"]:
        _fill(m, s, 0, sx, sy)
    return m.astype(bool), scaled


def inside(mask, x, y):
    """點是否在檢測區域內 (mask 為 None 表示整張影像)"""
    if mask is None:
        return True
    H, W = mask.shape
    xi, yi = int(round(x)), int(round(y))
    return 0 <= xi < W and 0 <= yi < H and bool(mask[yi, xi])
