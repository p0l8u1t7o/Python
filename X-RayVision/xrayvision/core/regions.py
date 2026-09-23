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
"""
import cv2
import numpy as np

KINDS = ("include", "exclude")
MAX_SHAPES = 50
MAX_POINTS = 200


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
    if not out["include"] and not out["exclude"]:
        return None
    if out["reference"] is None:
        raise RegionError("reference")
    return out


def build_mask(regions, shape):
    """
    依影像尺寸產生布林遮罩 (True = 檢測)；regions 為 None 時回傳 None。
    回傳 (mask, scaled)：scaled 表示影像尺寸與參考影像不同、座標已依比例縮放
    """
    if not regions:
        return None, False
    H, W = shape[:2]
    ref = regions["reference"]
    sx, sy = W / ref["width"], H / ref["height"]
    scaled = abs(sx - 1) > 1e-6 or abs(sy - 1) > 1e-6

    def fill(m, s, val):
        if s["type"] == "rect":
            cv2.rectangle(m, (int(round(s["x0"] * sx)), int(round(s["y0"] * sy))),
                          (int(round(s["x1"] * sx)), int(round(s["y1"] * sy))), val, -1)
        else:
            pts = np.array([[p[0] * sx, p[1] * sy] for p in s["points"]], np.float64).round().astype(np.int32)
            cv2.fillPoly(m, [pts.reshape(-1, 1, 2)], val)

    m = np.zeros((H, W), np.uint8) if regions["include"] else np.ones((H, W), np.uint8)
    for s in regions["include"]:
        fill(m, s, 1)
    for s in regions["exclude"]:
        fill(m, s, 0)
    return m.astype(bool), scaled


def inside(mask, x, y):
    """點是否在檢測區域內 (mask 為 None 表示整張影像)"""
    if mask is None:
        return True
    H, W = mask.shape
    xi, yi = int(round(x)), int(round(y))
    return 0 <= xi < W and 0 <= yi < H and bool(mask[yi, xi])
