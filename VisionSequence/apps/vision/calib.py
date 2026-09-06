"""標定：把像素換算成真實世界（毫米或機械手座標），並校正鏡頭畸變。

**一份標定＝一個資產**（`Asset.kind="calibration"`，內容是這裡定義的 JSON）。刻意不拆成「內參檔」與「標定檔」
兩種東西——現場的人只要在工具上選一個標定，畸變校正、量測換算、座標輸出就都對了。

payload 結構（`validate()` 是唯一的事實來源）::

    {
      "version": 1,
      "unit": "mm",                       # 世界座標的單位（顯示用；數學上只是「真實單位」）
      "image_size": [w, h],               # 標定當下的影像尺寸；套用時尺寸不同會自動換算內參
      "lens": {                           # 選配：鏡頭畸變（要標定板多張）
          "camera_matrix": [[3x3]], "dist_coeffs": [k1,k2,p1,p2,k3],
          "rms": 0.21, "views": 12, "view_errors": [...]
      },
      "world": {                          # 選配：像素 → 世界
          "kind": "scale" | "affine" | "perspective",
          "matrix": [[3x3]],              # 齊次座標，像素 → 世界
          "mm_per_px": 0.0532,            # 等效比例（影像中心處）
          "rms": 0.03, "max_error": 0.07, # 殘差，單位同 unit
          "points": [{"px": [x,y], "world": [X,Y], "error": 0.02}, ...]
      },
      "note": ""
    }

`lens` 與 `world` 都是選配：只想要 mm/px 就只有 world.scale；只想校正畸變就只有 lens。

幾何慣例與平台其他地方一致：影像座標 y 向下、像素中心在整數座標、影像角度正值＝畫面順時針。
世界角度則以世界座標軸本身度量（+X 轉向 +Y 為正），因為機械手的座標系是使用者自己定的。
"""

from __future__ import annotations

import json
import math
import os
import threading
from typing import Any

import cv2
import numpy as np

VERSION = 1
#: 標定板種類：西洋棋盤格（內角點）、對稱圓點、交錯圓點
BOARD_KINDS = ("chessboard", "circles", "acircles")
#: 世界座標對應的解法；點數下限
WORLD_KINDS = {"scale": 2, "affine": 3, "perspective": 4}


class CalibError(ValueError):
    """標定資料有問題（訊息給使用者看，一律英文）。"""


# ---------------------------------------------------------------------------
# 讀寫與驗證
# ---------------------------------------------------------------------------
def validate(payload: Any) -> dict[str, Any]:
    """檢查並正規化 payload；壞掉的標定要在存檔與載入時就擋下來，不是等到產線上才炸。"""
    if not isinstance(payload, dict):
        raise CalibError("A calibration must be a JSON object")
    out: dict[str, Any] = {"version": VERSION, "unit": str(payload.get("unit") or "mm")[:12]}
    size = payload.get("image_size") or []
    try:
        w, h = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        raise CalibError("image_size must be [width, height]") from None
    if w <= 0 or h <= 0:
        raise CalibError("image_size must be positive")
    out["image_size"] = [w, h]
    out["note"] = str(payload.get("note") or "")[:500]

    lens = payload.get("lens")
    if lens:
        try:
            cam = np.asarray(lens["camera_matrix"], dtype=np.float64).reshape(3, 3)
            dist = np.asarray(lens["dist_coeffs"], dtype=np.float64).reshape(-1)
        except (KeyError, TypeError, ValueError):
            raise CalibError("lens needs camera_matrix (3x3) and dist_coeffs") from None
        if not np.isfinite(cam).all() or not np.isfinite(dist).all():
            raise CalibError("lens contains non-finite numbers")
        if cam[0, 0] <= 0 or cam[1, 1] <= 0:
            raise CalibError("lens focal length must be positive")
        if dist.size not in (4, 5, 8, 12, 14):
            raise CalibError("dist_coeffs must have 4, 5, 8, 12 or 14 values")
        out["lens"] = {
            "camera_matrix": cam.tolist(), "dist_coeffs": dist.tolist(),
            "rms": _num(lens.get("rms")), "views": int(lens.get("views") or 0),
            "view_errors": [_num(v) for v in (lens.get("view_errors") or [])],
        }

    world = payload.get("world")
    if world:
        kind = str(world.get("kind") or "")
        if kind not in WORLD_KINDS:
            raise CalibError(f"world.kind must be one of {', '.join(WORLD_KINDS)}")
        try:
            matrix = np.asarray(world["matrix"], dtype=np.float64).reshape(3, 3)
        except (KeyError, TypeError, ValueError):
            raise CalibError("world needs a 3x3 matrix") from None
        if not np.isfinite(matrix).all():
            raise CalibError("world.matrix contains non-finite numbers")
        if abs(np.linalg.det(matrix)) < 1e-12:
            raise CalibError("world.matrix is singular (the points are collinear?)")
        out["world"] = {
            "kind": kind, "matrix": matrix.tolist(),
            "mm_per_px": _num(world.get("mm_per_px")) or scale_at(matrix, (w / 2, h / 2)),
            "rms": _num(world.get("rms")), "max_error": _num(world.get("max_error")),
            "points": [
                {"px": [_num(p.get("px", [0, 0])[0]), _num(p.get("px", [0, 0])[1])],
                 "world": [_num(p.get("world", [0, 0])[0]), _num(p.get("world", [0, 0])[1])],
                 "error": _num(p.get("error"))}
                for p in (world.get("points") or []) if isinstance(p, dict)
            ][:200],
        }
    if "lens" not in out and "world" not in out:
        raise CalibError("A calibration needs a lens, a world mapping, or both")
    return out


def _num(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def save(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    checked = validate(payload)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(checked, fh, ensure_ascii=False, indent=2)
    return checked


_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def load(path: str) -> dict[str, Any]:
    """讀標定檔（依 mtime 快取；熱路徑每張影像都會呼叫）。"""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        raise CalibError("The calibration file is missing") from None
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
    try:
        with open(path, encoding="utf-8-sig") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibError(f"Could not read the calibration: {exc}") from None
    checked = validate(payload)
    with _cache_lock:
        _cache[path] = (stamp, checked)
        if len(_cache) > 32:
            _cache.pop(next(iter(_cache)))
    return checked


def invalidate(path: str = "") -> None:
    with _cache_lock:
        _cache.pop(path, None) if path else _cache.clear()


def from_asset(asset_id: Any, resolve: Any) -> dict[str, Any]:
    """工具用：資產 id → payload（`resolve` 就是 `ToolContext.asset_path`）。"""
    if not asset_id:
        raise CalibError("No calibration is selected: pick one made on the Calibration page")
    path = resolve(str(asset_id))
    if not path:
        raise CalibError("That calibration was deleted; pick another one")
    return load(path)


def summary(payload: dict[str, Any]) -> str:
    """一行白話摘要（資產清單與工具訊息用）。"""
    bits = []
    lens = payload.get("lens")
    if lens:
        bits.append(f"lens {lens.get('views', 0)} views, error {lens.get('rms', 0):.2f} px")
    world = payload.get("world")
    if world:
        unit = payload.get("unit", "mm")
        bits.append(f"{world['kind']} {world.get('mm_per_px', 0):.5f} {unit}/px")
        if world.get("points"):
            bits.append(f"fit {world.get('rms', 0):.3f} {unit}")
    return "; ".join(bits) or "empty"


# ---------------------------------------------------------------------------
# 標定板
# ---------------------------------------------------------------------------
def board_object_points(cols: int, rows: int, spacing: float, kind: str = "chessboard") -> np.ndarray:
    """標定板上每個特徵點的真實座標（Z=0 平面，單位＝spacing 的單位）。"""
    if cols < 2 or rows < 2:
        raise CalibError("The board needs at least 2 x 2 features")
    if spacing <= 0:
        raise CalibError("The board spacing must be greater than 0")
    pts = np.zeros((rows * cols, 3), dtype=np.float64)
    grid = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2).astype(np.float64)
    if kind == "acircles":
        # 交錯圓點：奇數列往右偏半格，列距是格距的一半（OpenCV 的慣例）
        pts[:, 0] = (2 * grid[:, 0] + (grid[:, 1] % 2)) * spacing / 2
        pts[:, 1] = grid[:, 1] * spacing / 2
    else:
        pts[:, :2] = grid * spacing
    return pts


def find_board(image: np.ndarray, cols: int, rows: int, kind: str = "chessboard") -> np.ndarray | None:
    """偵測標定板特徵點；回 (N,2) float64（順序與 board_object_points 對應），找不到回 None。"""
    if kind not in BOARD_KINDS:
        raise CalibError(f"kind must be one of {', '.join(BOARD_KINDS)}")
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    size = (int(cols), int(rows))
    if kind == "chessboard":
        # SB 版對模糊與不均勻打光穩健得多；舊版當退路
        found, corners = cv2.findChessboardCornersSB(gray, size, flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
        if not found:
            found, corners = cv2.findChessboardCorners(gray, size, flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
            if found:
                corners = cv2.cornerSubPix(
                    gray, corners.astype(np.float32), (11, 11), (-1, -1),
                    (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01),
                )
    else:
        flags = cv2.CALIB_CB_ASYMMETRIC_GRID if kind == "acircles" else cv2.CALIB_CB_SYMMETRIC_GRID
        found, corners = cv2.findCirclesGrid(gray, size, flags=flags | cv2.CALIB_CB_CLUSTERING)
        if not found:  # 深色底白點的板子
            found, corners = cv2.findCirclesGrid(255 - gray, size, flags=flags | cv2.CALIB_CB_CLUSTERING)
    if not found or corners is None:
        return None
    return np.asarray(corners, dtype=np.float64).reshape(-1, 2)


def calibrate_lens(views: list[np.ndarray], object_points: np.ndarray, image_size: tuple[int, int]) -> dict[str, Any]:
    """多張標定板影像的角點 → 內參與畸變係數（含每張的重投影誤差，讓使用者剔掉爛的那幾張）。"""
    if len(views) < 3:
        raise CalibError("Lens calibration needs at least 3 board views (10 or more from different angles is better)")
    obj = [object_points.astype(np.float32) for _ in views]
    img = [np.asarray(v, dtype=np.float32).reshape(-1, 1, 2) for v in views]
    for v in img:
        if v.shape[0] != object_points.shape[0]:
            raise CalibError("Every view must have the same number of points as the board")
    rms, cam, dist, rvecs, tvecs = cv2.calibrateCamera(obj, img, (int(image_size[0]), int(image_size[1])), None, None)
    errors = []
    for i, v in enumerate(img):
        projected, _ = cv2.projectPoints(obj[i], rvecs[i], tvecs[i], cam, dist)
        errors.append(float(cv2.norm(v, projected, cv2.NORM_L2) / math.sqrt(len(projected))))
    return {
        "camera_matrix": np.asarray(cam, dtype=np.float64).tolist(),
        "dist_coeffs": np.asarray(dist, dtype=np.float64).reshape(-1).tolist(),
        "rms": float(rms), "views": len(views), "view_errors": errors,
    }


# ---------------------------------------------------------------------------
# 世界座標
# ---------------------------------------------------------------------------
def solve_world(pairs: list[tuple[tuple[float, float], tuple[float, float]]], kind: str = "affine") -> dict[str, Any]:
    """像素↔世界的對應點 → 轉換矩陣與**每個點的殘差**。

    殘差是這裡最重要的產出：VM 只告訴你標定完了，我們告訴你哪一點沒對準、差多少。
    """
    if kind not in WORLD_KINDS:
        raise CalibError(f"kind must be one of {', '.join(WORLD_KINDS)}")
    need = WORLD_KINDS[kind]
    if len(pairs) < need:
        raise CalibError(f"{kind} needs at least {need} points, got {len(pairs)}")
    src = np.asarray([p[0] for p in pairs], dtype=np.float64).reshape(-1, 2)
    dst = np.asarray([p[1] for p in pairs], dtype=np.float64).reshape(-1, 2)
    if not np.isfinite(src).all() or not np.isfinite(dst).all():
        raise CalibError("The points contain non-finite numbers")

    if kind == "scale":
        # 純比例：用所有點對的距離比（最小平方），原點對齊第一點
        du = np.linalg.norm(src[1:] - src[0], axis=1)
        dw = np.linalg.norm(dst[1:] - dst[0], axis=1)
        if float(du.sum()) <= 0:
            raise CalibError("The pixel points are all at the same place")
        k = float((du * dw).sum() / (du * du).sum())
        matrix = np.array([[k, 0.0, dst[0, 0] - k * src[0, 0]], [0.0, k, dst[0, 1] - k * src[0, 1]], [0.0, 0.0, 1.0]])
    elif kind == "affine":
        # 最小平方（不是 RANSAC）：標定點是使用者一個個指定的，不該被悄悄丟掉
        a = np.hstack([src, np.ones((len(src), 1))])
        sol, *_ = np.linalg.lstsq(a, dst, rcond=None)
        matrix = np.vstack([sol.T, [0.0, 0.0, 1.0]])
    else:
        found, _ = cv2.findHomography(src, dst, 0)
        if found is None:
            raise CalibError("Could not fit a perspective mapping to those points")
        matrix = np.asarray(found, dtype=np.float64)
    if abs(np.linalg.det(matrix)) < 1e-12:
        raise CalibError("The points are collinear or repeated; the mapping is singular")

    mapped = apply(matrix, src)
    errors = np.linalg.norm(mapped - dst, axis=1)
    return {
        "kind": kind, "matrix": matrix.tolist(),
        "mm_per_px": scale_at(matrix, tuple(src.mean(axis=0))),
        "rms": float(math.sqrt(float((errors**2).mean()))), "max_error": float(errors.max()),
        "points": [
            {"px": [float(src[i, 0]), float(src[i, 1])], "world": [float(dst[i, 0]), float(dst[i, 1])], "error": float(errors[i])}
            for i in range(len(src))
        ],
    }


def world_from_board(corners: np.ndarray, object_points: np.ndarray) -> dict[str, Any]:
    """一張平放的標定板 → 像素到板面座標的透視對應（原點在板子的第一個特徵點）。"""
    pairs = [((float(c[0]), float(c[1])), (float(o[0]), float(o[1]))) for c, o in zip(corners, object_points[:, :2], strict=True)]
    return solve_world(pairs, "perspective")


def apply(matrix: Any, points: Any) -> np.ndarray:
    """像素點 → 世界點（齊次除法；(N,2) 進 (N,2) 出）。"""
    m = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if pts.size == 0:
        return pts.reshape(0, 2)
    homo = np.hstack([pts, np.ones((len(pts), 1))]) @ m.T
    w = homo[:, 2:3]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return homo[:, :2] / w


def scale_at(matrix: Any, point: tuple[float, float]) -> float:
    """該點附近「一個像素等於多少世界單位」（面積開根號，透視也適用）。"""
    m = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    x, y = float(point[0]), float(point[1])
    probe = apply(m, [[x, y], [x + 1.0, y], [x, y + 1.0]])
    area = abs(np.cross(probe[1] - probe[0], probe[2] - probe[0]))
    return float(math.sqrt(area)) if area > 0 else 0.0


def angle_to_world(matrix: Any, degrees: float, at: tuple[float, float] | None = None) -> float:
    """影像角度（正值＝畫面順時針）→ 世界角度（+X 轉向 +Y 為正）。"""
    m = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    x, y = at if at is not None else (0.0, 0.0)
    rad = math.radians(float(degrees))
    tip = (x + math.cos(rad), y + math.sin(rad))
    a, b = apply(m, [[x, y], list(tip)])
    return float(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))


# ---------------------------------------------------------------------------
# 鏡頭校正（熱路徑：映射表快取）
# ---------------------------------------------------------------------------
_maps: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
_maps_lock = threading.Lock()


def scaled_camera_matrix(lens: dict[str, Any], calib_size: tuple[int, int], image_size: tuple[int, int]) -> np.ndarray:
    """影像尺寸與標定當下不同時（binning、換解析度）自動換算內參——不然畸變會靜默校正錯。"""
    cam = np.asarray(lens["camera_matrix"], dtype=np.float64).reshape(3, 3).copy()
    cw, ch = float(calib_size[0]), float(calib_size[1])
    iw, ih = float(image_size[0]), float(image_size[1])
    if cw <= 0 or ch <= 0 or (abs(cw - iw) < 0.5 and abs(ch - ih) < 0.5):
        return cam
    sx, sy = iw / cw, ih / ch
    if abs(sx - sy) > 0.02:
        raise CalibError(
            f"This image is {int(iw)}x{int(ih)} but the calibration was made at {int(cw)}x{int(ch)}; "
            "the aspect ratio differs, so the lens correction cannot be rescaled. Calibrate at the size you run at."
        )
    cam[0, :] *= sx
    cam[1, :] *= sy
    return cam


def undistort(image: np.ndarray, payload: dict[str, Any], alpha: float = 0.0) -> np.ndarray:
    """套用鏡頭校正。alpha 0＝裁掉黑邊只留有效區、1＝保留全部畫面。"""
    lens = payload.get("lens")
    if not lens:
        raise CalibError("This calibration has no lens data (calibrate with a board first)")
    h, w = image.shape[:2]
    cam = scaled_camera_matrix(lens, tuple(payload["image_size"]), (w, h))
    dist = np.asarray(lens["dist_coeffs"], dtype=np.float64)
    alpha = min(1.0, max(0.0, float(alpha)))
    key = (round(float(cam[0, 0]), 6), round(float(cam[1, 1]), 6), round(float(cam[0, 2]), 6), round(float(cam[1, 2]), 6),
           tuple(np.round(dist, 8).tolist()), w, h, round(alpha, 3))
    with _maps_lock:
        maps = _maps.get(key)
    if maps is None:
        new_cam, _ = cv2.getOptimalNewCameraMatrix(cam, dist, (w, h), alpha, (w, h))
        maps = cv2.initUndistortRectifyMap(cam, dist, None, new_cam, (w, h), cv2.CV_16SC2)
        with _maps_lock:
            if len(_maps) > 8:
                _maps.pop(next(iter(_maps)))
            _maps[key] = maps
    from apps.vision.tools import accel

    return accel.remap(image, maps[0], maps[1], cv2.INTER_LINEAR, border_mode=cv2.BORDER_CONSTANT)


RMS_WARN_PX = 0.5


def coverage(views: list[Any], image_size: tuple[int, int], cols: int = 4, rows: int = 3) -> dict[str, Any]:
    """標定板角點的視野覆蓋率：把畫面切成 cols×rows 格，數每格落了幾個角點；沒樣本的格子（多半在邊角）就是畸變估不準的地方。"""
    w, h = max(1, int(image_size[0])), max(1, int(image_size[1]))
    grid = [[0] * cols for _ in range(rows)]
    total = 0
    for v in views or []:
        pts = np.asarray(v, dtype=np.float64).reshape(-1, 2)
        for x, y in pts:
            cx = min(cols - 1, max(0, int(x * cols / w)))
            cy = min(rows - 1, max(0, int(y * rows / h)))
            grid[cy][cx] += 1
            total += 1
    missing = [{"col": c, "row": r, "x": (c + 0.5) * w / cols, "y": (r + 0.5) * h / rows} for r in range(rows) for c in range(cols) if grid[r][c] == 0]
    covered = cols * rows - len(missing)
    edge_missing = [m for m in missing if m["col"] in (0, cols - 1) or m["row"] in (0, rows - 1)]
    return {"cols": cols, "rows": rows, "grid": grid, "points": total, "cells": cols * rows, "covered": covered,
            "ratio": round(covered / (cols * rows), 3), "missing": missing, "edge_missing": len(edge_missing)}


def warnings(payload: dict[str, Any], cov: dict[str, Any] | None = None) -> list[str]:
    """給人看的警告（英文，介面翻譯）：重投影誤差過大、視野覆蓋不足、張數太少、世界殘差大。"""
    out: list[str] = []
    lens = payload.get("lens") or {}
    if lens:
        rms = float(lens.get("rms") or 0)
        if rms > RMS_WARN_PX:
            out.append(f"Reprojection error {rms:.2f} px is above {RMS_WARN_PX:g} px: redo the calibration with sharper, evenly lit pictures and the board tilted more, especially near the edges")
        if int(lens.get("views") or 0) < 8:
            out.append(f"Only {int(lens.get('views') or 0)} pictures: 10 to 15 with the board at different positions and tilts gives a steadier lens model")
    if cov and cov.get("cells"):
        if cov["ratio"] < 0.75:
            out.append(f"The board covered {cov['covered']} of {cov['cells']} areas of the picture; take pictures with the board near the edges and corners too")
        elif cov.get("edge_missing"):
            out.append(f"{cov['edge_missing']} edge areas have no corners yet: distortion is largest there, so add pictures with the board at the edges")
    world = payload.get("world") or {}
    if world and world.get("rms") is not None:
        unit = payload.get("unit", "mm")
        mm_per_px = float(world.get("mm_per_px") or 0)
        if mm_per_px > 0 and float(world["rms"]) > 2.0 * mm_per_px:
            out.append(f"Point residual {float(world['rms']):.3f} {unit} is more than two pixels: check the point pairs, or use a perspective mapping if the camera looks at the plane at an angle")
    return out


def quality(payload: dict[str, Any]) -> dict[str, str]:
    """把 rms 翻成白話等級：現場的人不需要知道「重投影誤差」是什麼。"""
    out: dict[str, str] = {}
    lens = payload.get("lens")
    if lens:
        rms = float(lens.get("rms") or 0)
        out["lens"] = "good" if rms <= 0.5 else ("fair" if rms <= 1.0 else "poor")
    world = payload.get("world")
    if world and world.get("points"):
        rms, px = float(world.get("rms") or 0), float(world.get("mm_per_px") or 0)
        in_px = rms / px if px > 0 else 0.0
        out["world"] = "good" if in_px <= 1.0 else ("fair" if in_px <= 3.0 else "poor")
    return out
