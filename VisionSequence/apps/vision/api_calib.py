"""標定頁的 API：拍照／偵測標定板／吸附特徵／解算／存成資產。

    POST /vision/calibration/capture        {source_id} 或 multipart image → 影像 ref（釘在快取裡，不落地）
    POST /vision/calibration/detect         {ref, kind, cols, rows} → 角點與可直接畫的標記
    POST /vision/calibration/snap           {ref, x, y, radius?} → 吸附到附近特徵的中心（點不準也沒關係）
    POST /vision/calibration/solve          {mode, ...} → payload＋品質評語（**先看再存**，不會偷偷寫進資產）
    POST /vision/calibration/assets         {name, payload} → 201 資產
    GET  /vision/calibration/assets/{id}    → 資產內容、摘要與品質

`solve` 與 `assets` 分開是刻意的：使用者先看到殘差、決定要不要剔掉某一點或某一張，滿意了才存。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.http import HttpRequest
from ninja import File, Router, UploadedFile

from apps.accounts.security import require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision import calib, sources
from apps.vision.images import store
from apps.vision.models import Asset

router = Router(tags=["calibration"])

MAX_VIEWS = 40
MAX_POINTS = 200


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(data, dict):
        raise ValidationError("The body must be a JSON object", code="bad_json")
    return data


def _image(ref: str) -> np.ndarray:
    image = store.get(str(ref or ""))
    if image is None:
        raise NotFound("That picture is no longer cached; take it again", code="image_gone")
    return image


def _fail(exc: calib.CalibError) -> ValidationError:
    return ValidationError(str(exc), code="bad_calibration")


@router.post("/calibration/capture", response={201: dict})
def capture(request: HttpRequest, image: UploadedFile = File(None), source_id: int | None = None):
    """拍一張給標定用：帶 source_id 從影像來源抓，或直接上傳檔案。影像只進快取（pinned），不進資產庫。"""
    require_feature(request, "assets")
    if image is not None:
        data = np.frombuffer(image.read(), dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValidationError("Could not decode that image", code="bad_image")
        name = image.name or "upload"
    else:
        if source_id is None:
            raise ValidationError("Give a source_id or upload an image", code="no_input")
        frame = sources.grab_by_id(source_id)
        if frame is None:
            reason = sources.last_error_of(source_id) or "the source did not return a frame"
            raise ValidationError(f"Could not capture: {reason}", code="grab_failed")
        name = f"source {source_id}"
    run_id = f"calib{uuid.uuid4().hex[:12]}"
    info = store.put(f"{run_id}:capture:image", frame, flow_id=0, run_id=run_id, pinned=True)
    return 201, {**info, "name": name}


@router.post("/calibration/detect")
def detect(request: HttpRequest):
    """找標定板。回 `found`＋角點；找不到會說明常見原因，而不是只回一個 false。"""
    require_feature(request, "assets")
    data = _body(request)
    frame = _image(str(data.get("ref") or ""))
    kind = str(data.get("kind") or "chessboard")
    try:
        cols, rows = int(data.get("cols") or 0), int(data.get("rows") or 0)
        corners = calib.find_board(frame, cols, rows, kind)
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc) or "cols and rows must be numbers", code="bad_board") from None
    except calib.CalibError as exc:
        raise _fail(exc) from None
    h, w = frame.shape[:2]
    if corners is None:
        hint = ("No board found. Check that the number of inner corners matches the board "
                f"({cols} x {rows} is what the platform looked for), that the whole board is in the picture, "
                "and that it is evenly lit without glare.")
        return {"found": False, "hint": hint, "width": w, "height": h, "corners": [], "overlays": []}
    pts = [[float(x), float(y)] for x, y in corners]
    overlays = [
        {"kind": "points", "points": pts, "color": "#22c55e"},
        {"kind": "polyline", "points": [pts[0], pts[cols - 1]], "color": "#38bdf8", "label": "row 1"},
        {"kind": "point", "x": pts[0][0], "y": pts[0][1], "color": "#f59e0b", "label": "origin"},
    ]
    return {"found": True, "corners": pts, "overlays": overlays, "width": w, "height": h, "count": len(pts)}


@router.post("/calibration/snap")
def snap(request: HttpRequest):
    """把點擊位置吸附到附近特徵的中心（孔、圓點、角）。使用者點得準不準就不重要了。"""
    require_feature(request, "assets")
    data = _body(request)
    frame = _image(str(data.get("ref") or ""))
    try:
        x, y = float(data.get("x")), float(data.get("y"))
    except (TypeError, ValueError):
        raise ValidationError("x and y must be numbers", code="bad_point") from None
    radius = max(4, min(200, int(data.get("radius") or 25)))
    h, w = frame.shape[:2]
    x0, y0 = int(max(0, x - radius)), int(max(0, y - radius))
    x1, y1 = int(min(w, x + radius + 1)), int(min(h, y + radius + 1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return {"found": False, "x": x, "y": y}
    patch = frame[y0:y1, x0:x1]
    gray = patch if patch.ndim == 2 else cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 中心是亮是暗都可能：挑「包含點擊位置」的那一團
    cx, cy = int(round(x)) - x0, int(round(y)) - y0
    if binary[min(max(cy, 0), binary.shape[0] - 1), min(max(cx, 0), binary.shape[1] - 1)] == 0:
        binary = 255 - binary
    count, _, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
    best, best_d = -1, 1e18
    for i in range(1, count):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 4 or area > 0.9 * binary.size:
            continue
        d = (centroids[i][0] - cx) ** 2 + (centroids[i][1] - cy) ** 2
        if d < best_d:
            best, best_d = i, d
    if best < 0 or best_d > (radius * radius):
        return {"found": False, "x": x, "y": y}
    return {"found": True, "x": float(centroids[best][0] + x0), "y": float(centroids[best][1] + y0),
            "area": int(stats[best, cv2.CC_STAT_AREA])}


@router.post("/calibration/solve")
def solve(request: HttpRequest):
    """算出標定但**不存**，讓使用者先看殘差。

    mode=board       views[[[x,y],...],...]＋cols/rows/spacing(+kind)：多張出鏡頭內參，指定的那一張同時給世界座標
    mode=points      points[{px:[x,y], world:[X,Y]}]＋world_kind：影像↔機械手（或治具）座標
    mode=distance    points 兩點＋distance：純比例（最快的一種，量測換算用這個就夠）
    mode=robot       points[{px,py,rx,ry}]＋kind/camera_mode；rotation_points[[x,y],...] 為另外採集的旋轉軌跡
    """
    require_feature(request, "assets")
    data = _body(request)
    mode = str(data.get("mode") or "")
    size = data.get("image_size") or []
    try:
        width, height = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        raise ValidationError("image_size must be [width, height]", code="bad_size") from None
    if width <= 0 or height <= 0:
        raise ValidationError("image_size must be positive", code="bad_size")
    payload: dict[str, Any] = {"unit": str(data.get("unit") or "mm"), "image_size": [width, height],
                               "note": str(data.get("note") or "")}
    try:
        if mode == "board":
            views = data.get("views") or []
            if not isinstance(views, list) or not views:
                raise ValidationError("Add at least one board picture", code="no_views")
            if len(views) > MAX_VIEWS:
                raise ValidationError(f"At most {MAX_VIEWS} pictures", code="too_many_views")
            cols, rows = int(data.get("cols") or 0), int(data.get("rows") or 0)
            spacing = float(data.get("spacing") or 0)
            board_kind = str(data.get("kind") or "chessboard")
            obj = calib.board_object_points(cols, rows, spacing, board_kind)
            corners = [np.asarray(v, dtype=np.float64).reshape(-1, 2) for v in views]
            if len(corners) >= 3 and not data.get("skip_lens"):
                payload["lens"] = calib.calibrate_lens(corners, obj, (width, height))
            index = int(data.get("world_view") if data.get("world_view") is not None else 0)
            if 0 <= index < len(corners) and not data.get("skip_world"):
                payload["world"] = calib.world_from_board(corners[index], obj)
            if "lens" not in payload and "world" not in payload:
                raise ValidationError("Lens calibration needs 3 or more pictures", code="not_enough_views")
        elif mode in ("points", "distance"):
            raw = data.get("points") or []
            if not isinstance(raw, list):
                raise ValidationError("points must be a list", code="bad_points")
            if len(raw) > MAX_POINTS:
                raise ValidationError(f"At most {MAX_POINTS} points", code="too_many_points")
            if mode == "distance":
                if len(raw) != 2:
                    raise ValidationError("Mark exactly two points and give the real distance between them", code="bad_points")
                real = float(data.get("distance") or 0)
                if real <= 0:
                    raise ValidationError("The real distance must be greater than 0", code="bad_distance")
                a = np.asarray(raw[0].get("px"), dtype=np.float64).reshape(2)
                b = np.asarray(raw[1].get("px"), dtype=np.float64).reshape(2)
                span = float(np.linalg.norm(b - a))
                if span <= 0:
                    raise ValidationError("The two points are in the same place", code="bad_points")
                k = real / span
                pairs = [((float(a[0]), float(a[1])), (0.0, 0.0)), ((float(b[0]), float(b[1])), (real, 0.0))]
                payload["world"] = calib.solve_world(pairs, "scale")
                payload["world"]["mm_per_px"] = k
            else:
                pairs = []
                for item in raw:
                    px = np.asarray(item.get("px"), dtype=np.float64).reshape(2)
                    wd = np.asarray(item.get("world"), dtype=np.float64).reshape(2)
                    pairs.append(((float(px[0]), float(px[1])), (float(wd[0]), float(wd[1]))))
                payload["world"] = calib.solve_world(pairs, str(data.get("world_kind") or "affine"))
        elif mode == "robot":
            raw = data.get("points")
            rotation = data.get("rotation_points", [])
            for name, values in (("points", raw), ("rotation_points", rotation)):
                if not isinstance(values, list):
                    raise ValidationError(f"{name} must be a list", code="bad_points")
                if len(values) > MAX_POINTS:
                    raise ValidationError(f"At most {MAX_POINTS} {name}", code="too_many_points")
            payload["robot"] = calib.solve_robot(
                {"translation": raw, "rotation": rotation},
                kind=data.get("kind", "translation"), camera_mode=data.get("camera_mode", "fixed"),
            )
            if "angle_sign" in data:
                payload["robot"]["angle_sign"] = data["angle_sign"]
            if data.get("world"):
                payload["world"] = data["world"]
        else:
            raise ValidationError("mode must be board, points, distance or robot", code="bad_mode")
        if data.get("lens"):  # 沿用既有標定的鏡頭部分（只想重做世界座標時）
            payload["lens"] = data["lens"]
        checked = calib.validate(payload)
    except calib.CalibError as exc:
        raise _fail(exc) from None
    except (TypeError, ValueError, IndexError, AttributeError) as exc:
        raise ValidationError(f"Those numbers do not make a calibration: {exc}", code="bad_calibration") from None
    cov = calib.coverage(data.get("views") or [], (width, height)) if mode == "board" else None
    return {"payload": checked, "summary": calib.summary(checked), "quality": calib.quality(checked), "coverage": cov, "warnings": calib.warnings(checked, cov)}


@router.post("/calibration/coverage")
def board_coverage(request: HttpRequest):
    """已採集的標定板角點蓋住了畫面的哪些區域（採集中即時提示「邊角樣本不足」）。{image_size, views[[[x,y],...],...]}"""
    require_feature(request, "assets")
    data = _body(request)
    size = data.get("image_size") or []
    try:
        width, height = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        raise ValidationError("image_size must be [width, height]", code="bad_size") from None
    views = data.get("views") or []
    if not isinstance(views, list) or len(views) > MAX_VIEWS:
        raise ValidationError(f"views must be a list of at most {MAX_VIEWS} corner sets", code="bad_views")
    try:
        cov = calib.coverage(views, (width, height), int(data.get("cols") or 4), int(data.get("rows") or 3))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"views must be lists of [x, y] points: {exc}", code="bad_views") from None
    cell_w, cell_h = width / cov["cols"], height / cov["rows"]
    overlays = [{"kind": "rect", "x": m["col"] * cell_w, "y": m["row"] * cell_h, "w": cell_w, "h": cell_h, "color": "#ef4444", "width": 1, "dash": True, "label": "no corners"} for m in cov["missing"]]
    overlays.append({"kind": "points", "points": [[float(p[0]), float(p[1])] for v in views for p in np.asarray(v, dtype=np.float64).reshape(-1, 2)][:4000], "color": "#38bdf8"})
    return {**cov, "overlays": overlays, "warnings": calib.warnings({}, cov)}


@router.post("/calibration/assets", response={201: dict})
def create_asset(request: HttpRequest):
    """把算好的 payload 存成標定資產（工具用 asset 參數選它）。"""
    require_feature(request, "assets")
    data = _body(request)
    try:
        payload = calib.validate(data.get("payload"))
    except calib.CalibError as exc:
        raise _fail(exc) from None
    name = str(data.get("name") or "").strip() or "calibration"
    asset_id = uuid.uuid4()
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.json")
    calib.save(path, payload)
    asset = Asset.objects.create(
        id=asset_id, name=name[:200], kind="calibration", path=path, size=os.path.getsize(path),
        group=str(data.get("group") or "").strip()[:60],
        meta={"summary": calib.summary(payload), "quality": calib.quality(payload), "unit": payload["unit"],
              "image_size": payload["image_size"], "has_lens": "lens" in payload, "has_world": "world" in payload,
              "has_robot": "robot" in payload},
    )
    audit.record(request, "asset.calibration", f"asset:{asset.id}", summary=f"{name}: {calib.summary(payload)}")
    return 201, {"id": str(asset.id), "name": asset.name, "kind": asset.kind, "group": asset.group,
                 "size": asset.size, "meta": asset.meta, "payload": payload}


@router.get("/calibration/assets/{asset_id}")
def read_asset(request: HttpRequest, asset_id: uuid.UUID):
    """讀回標定內容（工具頁與標定頁都用它顯示現況）。"""
    require_feature(request, "assets")
    asset = Asset.objects.filter(pk=asset_id, kind="calibration").first()
    if asset is None:
        raise NotFound("Calibration not found", code="asset_not_found")
    try:
        payload = calib.load(asset.path)
    except calib.CalibError as exc:
        raise _fail(exc) from None
    return {"id": str(asset.id), "name": asset.name, "group": asset.group, "payload": payload,
            "summary": calib.summary(payload), "quality": calib.quality(payload)}
