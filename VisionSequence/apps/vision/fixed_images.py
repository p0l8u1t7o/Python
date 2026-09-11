"""固定影像（fixed image）的檔案庫：使用者在流程裡直接上傳、由 `fixed_image` 工具記住的圖片。

不是資產：資產庫留給使用者管理的模型、標定、npz；固定影像只跟著流程走（節點參數裡的描述子），檔案以內容雜湊命名放在
`ASSET_DIR/fixed/<id>.png`——同一張圖上傳兩次只存一份，範本畫廊的樣本圖也是這樣存（seed_demo 寫進來，id 固定，重跑不重複）。
描述子 `{"id", "name", "width", "height", "size"}` 是 `Param(kind="images")` 的值元素；工具用 `load(id)` 取 ndarray（依 mtime 快取）。
孤兒（沒有任何流程／範本引用的檔案）由 `orphans()` 列出，交給 purge 清。
"""

from __future__ import annotations

import hashlib
import os
import threading
from typing import Any

import cv2
import numpy as np
from django.conf import settings

ID_LEN = 20
MAX_BYTES = 64 * 1024 * 1024
_cache: dict[str, tuple[float, np.ndarray]] = {}
_lock = threading.Lock()
_CACHE_MAX = 64


class FixedImageError(Exception):
    pass


def root() -> str:
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), "fixed")
    os.makedirs(path, exist_ok=True)
    return path


def path_of(image_id: str) -> str:
    image_id = str(image_id or "")
    if not image_id.isalnum() or len(image_id) != ID_LEN:
        raise FixedImageError("Bad fixed image id")
    return os.path.join(root(), f"{image_id}.png")


def store(image: np.ndarray, name: str = "") -> dict[str, Any]:
    """存一張 ndarray（BGR 或灰階）：PNG 編碼、內容雜湊命名、已存在就沿用；回描述子。"""
    if image is None or image.size == 0:
        raise FixedImageError("Empty image")
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise FixedImageError("The picture could not be encoded")
    data = buf.tobytes()
    image_id = hashlib.sha256(data).hexdigest()[:ID_LEN]
    path = path_of(image_id)
    if not os.path.isfile(path):
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    h, w = image.shape[:2]
    return {"id": image_id, "name": (name or f"{image_id}.png")[:120], "width": int(w), "height": int(h), "size": len(data)}


def store_bytes(data: bytes, name: str = "") -> dict[str, Any]:
    """上傳的檔案 bytes → 解碼驗證 → store()（統一轉成 PNG，多餘的 EXIF／JPEG 都不留）。"""
    if not data:
        raise FixedImageError("Empty file")
    if len(data) > MAX_BYTES:
        raise FixedImageError("The picture is larger than 64 MB")
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FixedImageError("The file is not a decodable picture")
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return store(image, name)


def load(image_id: str) -> np.ndarray | None:
    """讀一張（依 mtime 快取，最多 64 張）；找不到回 None。"""
    try:
        path = path_of(image_id)
    except FixedImageError:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    with _lock:
        hit = _cache.get(image_id)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    image.setflags(write=False)
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[image_id] = (mtime, image)
    return image


def exists(image_id: str) -> bool:
    try:
        return os.path.isfile(path_of(image_id))
    except FixedImageError:
        return False


def describe(image_id: str, name: str = "") -> dict[str, Any] | None:
    img = load(image_id)
    if img is None:
        return None
    h, w = img.shape[:2]
    return {"id": image_id, "name": name or f"{image_id}.png", "width": int(w), "height": int(h), "size": os.path.getsize(path_of(image_id))}


def thumbnail(image_id: str, width: int = 160) -> bytes | None:
    img = load(image_id)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = min(1.0, float(width) / max(1, w))
    small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1.0 else img
    if small.dtype != np.uint8:
        small = cv2.normalize(small, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes() if ok else None


def ids_in_graph(graph: dict[str, Any] | None) -> set[str]:
    """一張流程圖裡引用的固定影像 id（所有 kind=images 參數的描述子；不查目錄，靠值的形狀）。"""
    out: set[str] = set()
    for node in (graph or {}).get("nodes") or []:
        for value in (node.get("params") or {}).values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and len(item["id"]) == ID_LEN and "width" in item:
                        out.add(item["id"])
    return out


def referenced_ids() -> set[str]:
    """所有流程、流程版本快照與自訂範本引用的 id（內建範本由 demo 現算）。"""
    from apps.vision.models import EngineeringNote, Flow, FlowTemplate, FlowVersion

    out: set[str] = set()
    # 工程證據即使撤回仍需保留，避免孤兒清理破壞追溯。
    for images in EngineeringNote.objects.values_list("images", flat=True):
        out.update(item["id"] for item in images if isinstance(item, dict) and isinstance(item.get("id"), str))
    for graph in Flow.objects.values_list("graph", flat=True):
        out |= ids_in_graph(graph)
    for graph in FlowVersion.objects.values_list("graph", flat=True):
        out |= ids_in_graph(graph)
    for graph in FlowTemplate.objects.values_list("graph", flat=True):
        out |= ids_in_graph(graph)
    try:
        from apps.vision import demo

        out |= demo.builtin_fixed_ids()
    except Exception:  # noqa: BLE001 - 內建範本算不出來就當全部都要留
        return out | set(list_ids())
    return out


def list_ids() -> list[str]:
    try:
        return sorted(f[:-4] for f in os.listdir(root()) if f.endswith(".png") and len(f) == ID_LEN + 4)
    except OSError:
        return []


def orphans() -> list[str]:
    used = referenced_ids()
    return [i for i in list_ids() if i not in used]


def remove(image_id: str) -> bool:
    try:
        path = path_of(image_id)
    except FixedImageError:
        return False
    with _lock:
        _cache.pop(image_id, None)
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def total_bytes() -> int:
    total = 0
    for i in list_ids():
        try:
            total += os.path.getsize(path_of(i))
        except OSError:
            pass
    return total
