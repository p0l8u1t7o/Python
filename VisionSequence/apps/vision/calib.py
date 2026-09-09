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

`lens`、`world` 與 `robot` 都是選配，至少提供一塊；`robot` 保存像素到機構的仿射與旋轉中心。

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
MAPPING_KINDS = {"affine": 3, "perspective": 4}
ROBOT_KINDS = ("translation", "translation_rotation")
CAMERA_MODES = ("fixed", "moving")


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
    if "robot" in payload:
        out["robot"] = _validate_robot(payload["robot"])
    if "mapping" in payload:
        out["mapping"] = _validate_mapping(payload["mapping"])
    if not any(key in out for key in ("lens", "world", "robot", "mapping")):
        raise CalibError("A calibration needs a lens, a world mapping, a robot mapping, or a camera mapping")
    return out


def _mapping_points(raw: Any, *, errors: bool = False) -> list[dict[str, float]]:
    """檢查相機間對應點；每一點都保留，讓前端能標出最大殘差。"""
    if not isinstance(raw, list):
        raise CalibError("mapping.points must be a list")
    fields = ("ax", "ay", "bx", "by", "error") if errors else ("ax", "ay", "bx", "by")
    points = []
    for i, point in enumerate(raw):
        if not isinstance(point, dict):
            raise CalibError(f"mapping.points[{i}] must be an object with ax, ay, bx and by")
        points.append({key: _robot_number(point.get(key), f"mapping.points[{i}].{key}", nonnegative=key == "error") for key in fields})
    return points


def _validate_mapping(mapping: Any) -> dict[str, Any]:
    """檢查相機 A 到相機 B 的 3x3 映射。"""
    if not isinstance(mapping, dict):
        raise CalibError("mapping must be an object")
    kind = str(mapping.get("kind") or "")
    if kind not in MAPPING_KINDS:
        raise CalibError("mapping.kind must be affine or perspective")
    try:
        matrix = np.asarray(mapping.get("matrix"), dtype=np.float64).reshape(3, 3)
    except (TypeError, ValueError, OverflowError):
        raise CalibError("mapping.matrix must be a finite 3x3 matrix") from None
    if not np.isfinite(matrix).all():
        raise CalibError("mapping.matrix contains non-finite numbers")
    if abs(np.linalg.det(matrix)) < 1e-12:
        raise CalibError("mapping.matrix is singular")
    points = _mapping_points(mapping.get("points", []), errors=True)
    return {
        "from_source": str(mapping.get("from_source") or "")[:200],
        "to_source": str(mapping.get("to_source") or "")[:200],
        "kind": kind,
        "matrix": matrix.tolist(),
        "points": points[:200],
        "rms": _robot_number(mapping.get("rms"), "mapping.rms", nonnegative=True),
        "max_error": _robot_number(mapping.get("max_error"), "mapping.max_error", nonnegative=True),
    }


def _robot_number(value: Any, field: str, *, nonnegative: bool = False) -> float:
    """機構標定不默默補零；指出錯誤欄位，讓使用者修正原始資料。"""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise CalibError(f"{field} must be a finite number") from None
    if isinstance(value, (bool, list, dict)) or not math.isfinite(number):
        raise CalibError(f"{field} must be a finite number")
    if nonnegative and number < 0:
        raise CalibError(f"{field} must be non-negative")
    return number


def _robot_points(raw: Any, *, errors: bool = False) -> list[dict[str, float]]:
    """平移點使用獨立純量欄位；保留順序與所有點，不做截斷或剔除。"""
    if not isinstance(raw, list):
        raise CalibError("robot.points must be a list")
    if len(raw) < 3:
        raise CalibError("robot.points needs at least 3 points")
    fields = ("px", "py", "rx", "ry", "error") if errors else ("px", "py", "rx", "ry")
    points = []
    for i, point in enumerate(raw):
        if not isinstance(point, dict):
            raise CalibError(f"robot.points[{i}] must be an object with px, py, rx and ry")
        points.append({key: _robot_number(point.get(key), f"robot.points[{i}].{key}", nonnegative=key == "error") for key in fields})
    return points


def _validate_robot(robot: Any) -> dict[str, Any]:
    """驗證機構仿射、方向慣例與殘差，旋轉中心若兩種座標都有就互驗。"""
    if not isinstance(robot, dict):
        raise CalibError("robot must be an object")
    if robot.get("kind") not in ROBOT_KINDS:
        raise CalibError("robot.kind must be translation or translation_rotation")
    if robot.get("camera_mode") not in CAMERA_MODES:
        raise CalibError("robot.camera_mode must be fixed or moving")
    try:
        matrix = np.asarray(robot.get("matrix"), dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        raise CalibError("robot.matrix must be a finite 3x3 affine matrix") from None
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise CalibError("robot.matrix must be a finite 3x3 affine matrix")
    if not np.allclose(matrix[2], [0, 0, 1], rtol=0, atol=1e-12):
        raise CalibError("robot.matrix must be affine with last row [0, 0, 1]")
    det = float(np.linalg.det(matrix[:2, :2]))
    if not math.isfinite(det) or abs(det) < 1e-12:
        raise CalibError("robot.matrix is singular")
    handedness = "left" if det < 0 else "right"
    if robot.get("handedness") not in ("left", "right"):
        raise CalibError("robot.handedness must be right or left")
    if robot["handedness"] != handedness:
        raise CalibError("robot.handedness does not match robot.matrix")
    sign = _robot_number(robot.get("angle_sign"), "robot.angle_sign")
    if sign not in (-1, 1):
        raise CalibError("robot.angle_sign must be +1 or -1")
    points = _robot_points(robot.get("points"), errors=True)
    out = {"kind": robot["kind"], "camera_mode": robot["camera_mode"], "matrix": matrix.tolist(),
           "handedness": handedness, "angle_sign": int(sign), "points": points,
           "rms": _robot_number(robot.get("rms"), "robot.rms", nonnegative=True),
           "max_error": max(p["error"] for p in points)}
    for key in ("rotation_center_px", "rotation_center_world"):
        if key in robot:
            value = robot[key]
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise CalibError(f"robot.{key} must be [x, y]")
            out[key] = [_robot_number(v, f"robot.{key}") for v in value]
    if "rotation_center_px" in out and "rotation_center_world" in out:
        expected = apply(matrix, [out["rotation_center_px"]])[0]
        if not np.allclose(expected, out["rotation_center_world"], rtol=1e-9, atol=1e-6):
            raise CalibError("robot.rotation_center_world does not match robot.rotation_center_px and matrix")
    if "rotation_points" in robot:
        raw = robot["rotation_points"]
        if not isinstance(raw, list) or len(raw) < 3:
            raise CalibError("robot.rotation_points must contain at least 3 points")
        out["rotation_points"] = []
        for i, point in enumerate(raw):
            if not isinstance(point, dict):
                raise CalibError(f"robot.rotation_points[{i}] must be an object with px, py and error")
            out["rotation_points"].append({
                key: _robot_number(point.get(key), f"robot.rotation_points[{i}].{key}", nonnegative=key == "error")
                for key in ("px", "py", "error")
            })
        radial_errors = np.array([p["error"] for p in out["rotation_points"]])
        out["rotation_rms_px"] = float(np.sqrt(np.mean(radial_errors**2)))
        out["rotation_max_error_px"] = float(radial_errors.max())
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
    robot = payload.get("robot")
    if robot:
        unit = payload.get("unit", "mm")
        center = "yes" if "rotation_center_px" in robot and "rotation_center_world" in robot else "no"
        bits.append(f"robot {robot['kind']}, {len(robot['points'])} points, RMS {robot['rms']:.3f} {unit}, "
                    f"max {max(p['error'] for p in robot['points']):.3f} {unit}, {robot['handedness']}-handed, rotation center: {center}")
        if robot.get("rotation_points"):
            bits.append(f"rotation {len(robot['rotation_points'])} points, RMS {robot['rotation_rms_px']:.3f} px, "
                        f"max {robot['rotation_max_error_px']:.3f} px")
    mapping = payload.get("mapping")
    if mapping:
        label = "camera mapping"
        if mapping.get("from_source") or mapping.get("to_source"):
            label = f"{mapping.get('from_source') or 'camera A'} to {mapping.get('to_source') or 'camera B'}"
        bits.append(f"{label} {mapping['kind']}, {len(mapping.get('points') or [])} points, RMS {mapping['rms']:.3f} px, "
                    f"max {mapping['max_error']:.3f} px")
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
        # CLUSTERING 對透視變形大的實拍照片比較穩，但**在乾淨的合成／列印板上會失敗**
        # （平台自己產生的圓點板實測四種行列組合全部找不到，拿掉這個旗標就都找得到）。
        # 所以兩種都試：先 CLUSTERING 維持既有偏好，再退回一般版；各自再試深底白點。
        found, corners = False, None
        for source in (gray, 255 - gray):          # 第二輪是深色底白點的板子
            for extra in (cv2.CALIB_CB_CLUSTERING, 0):
                found, corners = cv2.findCirclesGrid(source, size, flags=flags | extra)
                if found:
                    break
            if found:
                break
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


def _normalize_points_2d(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """把點正規化到平均距離 sqrt(2)，提升 DLT 的數值穩定度。"""
    centroid = points.mean(axis=0)
    shifted = points - centroid
    mean_dist = float(np.linalg.norm(shifted, axis=1).mean())
    if mean_dist <= 1e-12:
        raise CalibError("The points are repeated; the camera mapping is singular")
    scale = math.sqrt(2.0) / mean_dist
    transform = np.array([[scale, 0.0, -scale * centroid[0]], [0.0, scale, -scale * centroid[1]], [0.0, 0.0, 1.0]], dtype=np.float64)
    homo = np.column_stack([points, np.ones(len(points), dtype=np.float64)])
    return (transform @ homo.T).T[:, :2], transform


def _solve_homography_lstsq(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """以所有對應點做正規化 DLT 最小平方，解出 src 到 dst 的 homography。"""
    src_n, t_src = _normalize_points_2d(src)
    dst_n, t_dst = _normalize_points_2d(dst)
    rows = []
    for (x, y), (u, v) in zip(src_n, dst_n, strict=True):
        rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
        rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.asarray(rows, dtype=np.float64))
    h = vt[-1].reshape(3, 3)
    matrix = np.linalg.inv(t_dst) @ h @ t_src
    if abs(matrix[2, 2]) > 1e-12:
        matrix = matrix / matrix[2, 2]
    return matrix


def solve_mapping(
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
    kind: str = "affine",
    *,
    from_source: str = "",
    to_source: str = "",
    matrix: Any | None = None,
) -> dict[str, Any]:
    """以最小平方解相機 A 像素到相機 B 像素的映射，並回傳每個點的殘差。"""
    if kind not in MAPPING_KINDS:
        raise CalibError(f"kind must be one of {', '.join(MAPPING_KINDS)}")
    need = MAPPING_KINDS[kind]
    if len(pairs) < need:
        raise CalibError(f"{kind} needs at least {need} points, got {len(pairs)}")
    src = np.asarray([p[0] for p in pairs], dtype=np.float64).reshape(-1, 2)
    dst = np.asarray([p[1] for p in pairs], dtype=np.float64).reshape(-1, 2)
    if not np.isfinite(src).all() or not np.isfinite(dst).all():
        raise CalibError("The mapping points contain non-finite numbers")

    if matrix is None:
        if kind == "affine":
            a = np.hstack([src, np.ones((len(src), 1))])
            sol, *_ = np.linalg.lstsq(a, dst, rcond=None)
            matrix_arr = np.vstack([sol.T, [0.0, 0.0, 1.0]])
        else:
            matrix_arr = _solve_homography_lstsq(src, dst)
    else:
        try:
            matrix_arr = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
        except (TypeError, ValueError, OverflowError):
            raise CalibError("mapping.matrix must be a finite 3x3 matrix") from None
        if not np.isfinite(matrix_arr).all():
            raise CalibError("mapping.matrix contains non-finite numbers")
    if abs(np.linalg.det(matrix_arr)) < 1e-12:
        raise CalibError("The points are collinear or repeated; the camera mapping is singular")

    mapped = apply(matrix_arr, src)
    errors = np.linalg.norm(mapped - dst, axis=1)
    payload = {
        "from_source": from_source,
        "to_source": to_source,
        "kind": kind,
        "matrix": matrix_arr.tolist(),
        "points": [
            {"ax": float(src[i, 0]), "ay": float(src[i, 1]), "bx": float(dst[i, 0]), "by": float(dst[i, 1]), "error": float(errors[i])}
            for i in range(len(src))
        ],
        "rms": float(math.sqrt(float((errors**2).mean()))),
        "max_error": float(errors.max()),
    }
    return _validate_mapping(payload)


def solve_mapping_from_boards(
    corners_a: Any,
    corners_b: Any,
    object_points: np.ndarray,
    *,
    from_source: str = "",
    to_source: str = "",
) -> dict[str, Any]:
    """由兩台相機看到的同一塊標定板角點組成 A 像素到 B 像素的透視映射。"""
    a = np.asarray(corners_a, dtype=np.float64).reshape(-1, 2)
    b = np.asarray(corners_b, dtype=np.float64).reshape(-1, 2)
    obj = np.asarray(object_points, dtype=np.float64).reshape(-1, 3)
    if len(a) != len(obj) or len(b) != len(obj):
        raise CalibError("Each camera view must have the same number of points as the board")
    a_to_board = _solve_homography_lstsq(a, obj[:, :2])
    b_to_board = _solve_homography_lstsq(b, obj[:, :2])
    board_to_b = np.linalg.inv(b_to_board)
    matrix = board_to_b @ a_to_board
    matrix = matrix / matrix[2, 2]
    pairs = [((float(pa[0]), float(pa[1])), (float(pb[0]), float(pb[1]))) for pa, pb in zip(a, b, strict=True)]
    return solve_mapping(pairs, "perspective", from_source=from_source, to_source=to_source, matrix=matrix)


def solve_robot(points: Any, *, kind: str, camera_mode: str) -> dict[str, Any]:
    """解手眼平移與旋轉中心，所有取樣一律最小平方。

    平移輸入為 [{px, py, rx, ry}, ...]；含旋轉時用
    {translation: [...], rotation: [[x, y], ...]}，兩組必須分別採集。
    rotation 是機構 XY 不動、同一特徵繞軸旋轉的像素軌跡，不可拿平移走點代替。
    相機模式只是記錄取樣架構；兩者的矩陣都由實際點對決定，不擅自反轉。
    angle_sign 依 +X→+Y 的機構角度慣例由手性決定；不同控制器可在保存前明確覆寫。
    points[].error 是機構座標殘差；rotation_points[].error 是到擬合圓的徑向像素殘差。
    """
    if kind not in ROBOT_KINDS:
        raise CalibError("robot.kind must be translation or translation_rotation")
    if camera_mode not in CAMERA_MODES:
        raise CalibError("robot.camera_mode must be fixed or moving")
    raw = points.get("translation") if isinstance(points, dict) else points
    samples = _robot_points(raw)
    src = np.array([[p["px"], p["py"]] for p in samples])
    if np.linalg.matrix_rank(src - src.mean(axis=0)) < 2:
        raise CalibError("robot.points are collinear or repeated")
    try:
        world = solve_world([((p["px"], p["py"]), (p["rx"], p["ry"])) for p in samples], "affine")
    except np.linalg.LinAlgError:
        raise CalibError("Could not fit robot.points; check the point coordinates") from None
    matrix = np.asarray(world["matrix"])
    left = np.linalg.det(matrix[:2, :2]) < 0
    robot = {"kind": kind, "camera_mode": camera_mode, "matrix": world["matrix"],
             "handedness": "left" if left else "right", "angle_sign": -1 if left else 1,
             "rms": world["rms"], "max_error": world["max_error"],
             "points": [{**p, "error": fit["error"]} for p, fit in zip(samples, world["points"], strict=True)]}
    if kind == "translation_rotation":
        from apps.vision.tools.builtin.locate import fit_circle_lsq

        raw_rotation = points.get("rotation") if isinstance(points, dict) else None
        try:
            rotation = np.asarray(raw_rotation, dtype=np.float64)
        except (TypeError, ValueError, OverflowError):
            raise CalibError("rotation_points must contain at least 3 finite [x, y] points") from None
        if rotation.ndim != 2 or rotation.shape[1] != 2 or len(rotation) < 3 or not np.isfinite(rotation).all():
            raise CalibError("rotation_points must contain at least 3 finite [x, y] points")
        if np.linalg.matrix_rank(rotation - rotation.mean(axis=0)) < 2:
            raise CalibError("rotation_points are collinear or repeated; a rotation arc is required")
        try:
            circle = fit_circle_lsq(rotation)
        except np.linalg.LinAlgError:
            circle = None
        if circle is None or not np.isfinite(circle).all() or circle[2] <= 0:
            raise CalibError("Could not fit a rotation center to rotation_points")
        robot["rotation_center_px"] = list(circle[:2])
        robot["rotation_center_world"] = apply(matrix, [circle[:2]])[0].tolist()
        radial_errors = np.abs(np.linalg.norm(rotation - circle[:2], axis=1) - circle[2])
        robot["rotation_points"] = [{"px": float(p[0]), "py": float(p[1]), "error": float(error)}
                                    for p, error in zip(rotation, radial_errors, strict=True)]
    return _validate_robot(robot)


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
    robot = payload.get("robot") or {}
    if robot:
        if len(robot["points"]) <= 3:
            out.append("Robot calibration has only 3 points: add more points across the working area to check residuals")
        px = scale_at(robot["matrix"], (0, 0))
        maximum = max(p["error"] for p in robot["points"])
        if robot["rms"] > 2 * px or maximum > 3 * px:
            out.append(f"Robot RMS {robot['rms']:.3f}, maximum residual {maximum:.3f} {payload.get('unit', 'mm')}: check all point pairs")
        if robot["handedness"] == "left":
            out.append("Robot mapping is left-handed: verify the controller angle direction and angle_sign")
        if "rotation_center_px" not in robot or "rotation_center_world" not in robot:
            out.append("Robot rotation center is unavailable: collect a rotation arc before using rotation compensation")
        if robot.get("rotation_rms_px", 0) > RMS_WARN_PX:
            out.append(f"Robot rotation residual {robot['rotation_rms_px']:.3f} px: check that the same feature rotates with robot XY held fixed")
    mapping = payload.get("mapping") or {}
    if mapping and mapping.get("rms") is not None:
        points = mapping.get("points") or []
        if len(points) <= MAPPING_KINDS.get(str(mapping.get("kind")), 4):
            out.append("Camera mapping has only the minimum number of points: add more spread across the overlap to check residuals")
        if float(mapping.get("rms") or 0) > 1.0 or float(mapping.get("max_error") or 0) > 3.0:
            out.append(f"Camera mapping RMS {float(mapping['rms']):.3f} px, maximum residual {float(mapping.get('max_error') or 0):.3f} px: check all point pairs")
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
    robot = payload.get("robot")
    if robot:
        px = scale_at(robot["matrix"], (0, 0))
        in_px = robot["rms"] / px if px > 0 else math.inf
        in_px = max(in_px, robot.get("rotation_rms_px", 0))
        out["robot"] = "good" if in_px <= 1.0 else ("fair" if in_px <= 3.0 else "poor")
    mapping = payload.get("mapping")
    if mapping:
        rms = float(mapping.get("rms") or 0)
        out["mapping"] = "good" if rms <= 1.0 else ("fair" if rms <= 3.0 else "poor")
    return out
