"""
圖組量測的配方設定與單張影像的角點偵測 (規劃書 PLAN-006)。

配方格式 (選用欄位 image_set)：
  {
    "enabled": true,
    "reference": {"width": 2768, "height": 2160, "run_id": 12},     圈選角點搜尋區域時的參考影像尺寸
    "corner_regions": [{"type": "rect", "x0":…, "y0":…, "x1":…, "y1":…, "position": "top_left"}]
  }
corner_regions 為角點搜尋區域 (參考影像像素座標，影像尺寸不同時依比例縮放)；position 為該區域的角落位置，
"auto" 表示由偵測結果判斷。沒有搜尋區域時搜尋整張影像。
"""
from . import die_corner
from .regions import RegionError, _num

POSITION_CHOICES = ("auto",) + die_corner.POSITIONS
MAX_CORNER_REGIONS = 8


def normalize(d):
    """檢查並整理 image_set；未設定或未啟用且沒有其他內容時回傳 None。格式錯誤拋出 RegionError"""
    if not d:
        return None
    if not isinstance(d, dict):
        raise RegionError("image_set")
    out = dict(enabled=bool(d.get("enabled", False)), reference=None, corner_regions=[])
    ref = d.get("reference") or {}
    if ref:
        if not isinstance(ref, dict):
            raise RegionError("image_set.reference")
        w, h = _num(ref.get("width"), "image_set.reference.width"), _num(ref.get("height"), "image_set.reference.height")
        if w < 1 or h < 1:
            raise RegionError("image_set.reference.size")
        out["reference"] = dict(width=int(w), height=int(h))
        if ref.get("run_id") is not None:
            out["reference"]["run_id"] = int(_num(ref["run_id"], "image_set.reference.run_id"))
    regions = d.get("corner_regions") or []
    if not isinstance(regions, list) or len(regions) > MAX_CORNER_REGIONS:
        raise RegionError("image_set.corner_regions")
    for s in regions:
        if not isinstance(s, dict) or s.get("type") != "rect":
            raise RegionError("image_set.corner_regions.type")
        x0, y0, x1, y1 = (_num(s.get(k), f"image_set.corner_regions.{k}") for k in ("x0", "y0", "x1", "y1"))
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 16 or y1 - y0 < 16:
            raise RegionError("image_set.corner_regions.size")
        pos = s.get("position") or "auto"
        if pos not in POSITION_CHOICES:
            raise RegionError("image_set.corner_regions.position")
        out["corner_regions"].append(dict(type="rect", x0=x0, y0=y0, x1=x1, y1=y1, position=pos))
    if out["corner_regions"] and out["reference"] is None:
        raise RegionError("image_set.reference")
    if not out["enabled"] and not out["corner_regions"]:
        return None
    return out


def scaled_regions(cfg, shape):
    """角點搜尋區域換算到分析影像的像素座標：[((x0, y0, x1, y1), position 或 None)]"""
    H, W = shape[:2]
    ref = cfg["reference"]
    sx, sy = (W / ref["width"], H / ref["height"]) if ref else (1.0, 1.0)
    return [((r["x0"] * sx, r["y0"] * sy, r["x1"] * sx, r["y1"] * sy), None if r["position"] == "auto" else r["position"])
            for r in cfg["corner_regions"]]


def detect_corner(A, cfg):
    """
    依配方設定偵測一張影像的晶片角點。有搜尋區域時逐區搜尋，取分數最高者；沒有時搜尋整張影像。
    回傳 die_corner.detect 的結果，另加 source (auto = 整張影像；recipe_region = 配方搜尋區域)、
    region (採用的搜尋區域序號，1 起) 與 found_count (找到角點的區域數)。
    """
    if not cfg["corner_regions"]:
        r = die_corner.detect(A)
        return dict(r, source="auto", region=None, found_count=int(r["found"]))
    results = []
    for i, (box, pos) in enumerate(scaled_regions(cfg, A.shape), 1):
        r = die_corner.detect(A, region=box, position=pos)
        results.append(dict(r, source="recipe_region", region=i))
    found = [r for r in results if r["found"]]
    if not found:
        # 回報第一個區域的未找到原因；有單邊時優先回報單邊
        r = next((r for r in results if r.get("edge_only")), results[0])
        return dict(r, found_count=0)
    best = max(found, key=lambda r: r["quality"]["score"])
    return dict(best, found_count=len(found))
