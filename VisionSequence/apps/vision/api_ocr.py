"""OCR 字型教導的 API（WP-02）。

    GET    /vision/ocr/models                       模型是否安裝、來源與授權（MODELS.json）
    GET    /vision/ocr/fonts                        教導中的字型（每個字元的樣本數）
    GET    /vision/ocr/fonts/{name}                 一個字型的樣本統計
    DELETE /vision/ocr/fonts/{name}                 刪掉樣本
    POST   /vision/ocr/fonts/{name}/samples         {ref|asset_id, region, text, mode?, count?, polarity?} → 切分並存字元樣本；
                                                    切出的字數與 text 不符時回 422（帶切分結果，換 mode 或給 count 再試）
    POST   /vision/ocr/fonts/{name}/train           {asset_name?, hidden?, epochs?} → 201 模型資產（npz，ocr_read 的 model 選它）

樣本存在 ASSET_DIR/ocr_fonts/<name>/<label>/<n>.png（24×24 灰階切片）；label 用 U+XXXX 目錄名，才能放 '/' 這種字。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.http import HttpRequest
from ninja import Router

from apps.accounts.security import require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision import ocr
from apps.vision.api import _asset_out
from apps.vision.images import store
from apps.vision.models import Asset
from apps.vision.tools.roi import crop as roi_crop

router = Router(tags=["ocr"])
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
MAX_SAMPLES_PER_CHAR = 500


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(data, dict):
        raise ValidationError("The body must be a JSON object", code="bad_json")
    return data


def fonts_root() -> str:
    return os.path.join(str(settings.VISION["ASSET_DIR"]), "ocr_fonts")


def font_dir(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise ValidationError("The font name may use letters, digits, - and _ (1 to 40 characters)", code="bad_name")
    return os.path.join(fonts_root(), name)


def _label_dir(ch: str) -> str:
    return "U+%04X" % ord(ch)


def _label_from_dir(name: str) -> str:
    return chr(int(name[2:], 16)) if name.startswith("U+") else name


def font_counts(name: str) -> dict[str, int]:
    folder = font_dir(name)
    if not os.path.isdir(folder):
        return {}
    out: dict[str, int] = {}
    for d in sorted(os.listdir(folder)):
        sub = os.path.join(folder, d)
        if os.path.isdir(sub):
            out[_label_from_dir(d)] = sum(1 for f in os.listdir(sub) if f.endswith(".png"))
    return out


def load_font_samples(name: str) -> tuple[list[np.ndarray], list[str]]:
    tiles: list[np.ndarray] = []
    labels: list[str] = []
    folder = font_dir(name)
    for d in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        sub = os.path.join(folder, d)
        if not os.path.isdir(sub):
            continue
        ch = _label_from_dir(d)
        for f in sorted(os.listdir(sub)):
            if f.endswith(".png"):
                img = cv2.imdecode(np.fromfile(os.path.join(sub, f), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    tiles.append(img)
                    labels.append(ch)
    return tiles, labels


def _source_image(body: dict[str, Any]) -> np.ndarray:
    asset_id = body.get("asset_id")
    if asset_id:
        asset = Asset.objects.filter(pk=asset_id).first()
        if asset is None:
            raise NotFound(f"Asset {asset_id} not found", code="asset_not_found")
        image = cv2.imdecode(np.fromfile(asset.path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValidationError("The asset is not a decodable image", code="bad_image")
        return image
    ref = str(body.get("ref") or "")
    image = store.get(ref) if ref else None
    if image is None:
        raise NotFound("Give asset_id (an image asset) or ref (a cached picture)", code="image_gone")
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def add_line_samples(name: str, gray: np.ndarray, region: dict[str, Any] | None, text: str, mode: str = "projection", count: int = 0, polarity: str = "dark_on_light") -> dict[str, Any]:
    """一行字＋正確字串 → 切分、存樣本；回 {chars: [{ch, box}], stored, counts}。切出的字數不符 → ValidationError（帶 boxes）。"""
    text = (text or "").replace(" ", "")
    if not text:
        raise ValidationError("text is required (the characters in the line, without spaces)", code="bad_text")
    c = roi_crop(gray, region, upright=True)
    if c.image.size == 0:
        raise ValidationError("The region falls outside the image", code="bad_region")
    line = np.ascontiguousarray(c.image)
    if mode not in ocr.SEG_MODES:
        raise ValidationError(f"mode must be one of {', '.join(ocr.SEG_MODES)}", code="bad_mode")
    boxes = ocr.segment_chars(line, mode, count or (len(text) if mode == "fixed" else 0), polarity)
    if len(boxes) != len(text):
        raise ValidationError(f"{len(boxes)} characters were segmented but the text has {len(text)}; try another segmentation mode or fixed pitch with count",
                              code="segment_mismatch", details={"segments": len(boxes), "boxes": [[b[0] + c.x0, b[1] + c.y0, b[2] + c.x0, b[3] + c.y0] for b in boxes] if c.inverse is None else []})
    folder = font_dir(name)
    stored = 0
    chars = []
    for b, ch in zip(boxes, text):
        tile = ocr.char_tile(line, b, polarity=polarity)
        sub = os.path.join(folder, _label_dir(ch))
        os.makedirs(sub, exist_ok=True)
        existing = [f for f in os.listdir(sub) if f.endswith(".png")]
        if len(existing) >= MAX_SAMPLES_PER_CHAR:
            continue
        ok, buf = cv2.imencode(".png", tile)
        if ok:
            buf.tofile(os.path.join(sub, f"{uuid.uuid4().hex[:10]}.png"))
            stored += 1
        chars.append({"ch": ch, "box": [round(float(v), 1) for v in c.to_full(b[0], b[1])] + [round(float(v), 1) for v in c.to_full(b[2], b[3])]})
    return {"chars": chars, "stored": stored, "counts": font_counts(name)}


def train_font_asset(name: str, asset_name: str = "", hidden: int = 64, epochs: int = 400, group: str = "") -> Asset:
    tiles, labels = load_font_samples(name)
    if len(tiles) < 4:
        raise ValidationError("At least 4 character samples are needed (add lines first)", code="too_few_samples")
    try:
        model = ocr.train_font(tiles, labels, hidden=hidden, epochs=epochs)
    except ocr.OcrError as exc:
        raise ValidationError(str(exc), code="bad_samples") from None
    data = ocr.pack_font(model)
    asset_id = uuid.uuid4()
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.npz")
    with open(path, "wb") as fh:
        fh.write(data)
    meta = {"trainer": "ocr_font", "font": name, "tool_key": "ocr_read", "tool_params": {"model": str(asset_id), "charset": "custom", "custom_charset": "".join(model["classes"])},
            "classes": model["classes"], "metrics": model["metrics"], "format": "npz", "ocr_font": True}
    return Asset.objects.create(id=asset_id, name=(asset_name or f"font {name}")[:200], kind="model", group=group[:60], path=path, size=len(data), meta=meta)


@router.get("/ocr/models")
def ocr_models(request: HttpRequest):
    require_feature(request, "assets")
    info_path = os.path.join(ocr.models_dir(), "MODELS.json")
    info: dict[str, Any] = {}
    if os.path.isfile(info_path):
        try:
            with open(info_path, encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, json.JSONDecodeError):
            info = {}
    return {"available": ocr.models_available(), "dir": ocr.models_dir(), "files": [f for f in ocr.MODEL_FILES if os.path.isfile(ocr.model_path(f))], "info": info}


@router.get("/ocr/fonts")
def list_fonts(request: HttpRequest):
    require_feature(request, "assets")
    root = fonts_root()
    names = sorted(d for d in os.listdir(root)) if os.path.isdir(root) else []
    return {"items": [{"name": n, "counts": font_counts(n), "samples": sum(font_counts(n).values())} for n in names if os.path.isdir(os.path.join(root, n))]}


@router.get("/ocr/fonts/{name}")
def get_font(request: HttpRequest, name: str):
    require_feature(request, "assets")
    counts = font_counts(name)
    if not os.path.isdir(font_dir(name)):
        raise NotFound(f"Font {name} not found", code="font_not_found")
    return {"name": name, "counts": counts, "samples": sum(counts.values()), "assets": [_asset_out(a) for a in Asset.objects.filter(kind="model", meta__font=name)]}


@router.delete("/ocr/fonts/{name}")
def delete_font(request: HttpRequest, name: str):
    require_feature(request, "assets")
    import shutil

    folder = font_dir(name)
    if not os.path.isdir(folder):
        raise NotFound(f"Font {name} not found", code="font_not_found")
    shutil.rmtree(folder, ignore_errors=True)
    audit.record(request, "ocr.font_delete", f"font:{name}", summary=f"font samples {name} deleted")
    return {"deleted": True}


@router.post("/ocr/fonts/{name}/samples", response={201: dict})
def add_samples(request: HttpRequest, name: str):
    require_feature(request, "assets")
    font_dir(name)  # 先驗名稱（422），再找影像（404）
    body = _body(request)
    gray = _source_image(body)
    region = body.get("region")
    if region is not None and (not isinstance(region, dict) or not region.get("shape")):
        raise ValidationError("region must be an ROI object", code="bad_region")
    out = add_line_samples(name, gray, region, str(body.get("text") or ""), str(body.get("mode") or "projection"), int(body.get("count") or 0), str(body.get("polarity") or "dark_on_light"))
    return 201, out


@router.post("/ocr/fonts/{name}/train", response={201: dict})
def train_font(request: HttpRequest, name: str):
    require_feature(request, "assets")
    body = _body(request)
    if not os.path.isdir(font_dir(name)):
        raise NotFound(f"Font {name} not found", code="font_not_found")
    asset = train_font_asset(name, str(body.get("asset_name") or ""), int(body.get("hidden") or 64), int(body.get("epochs") or 400), str(body.get("group") or ""))
    audit.record(request, "asset.ocr_font", f"asset:{asset.id}", summary=f"{asset.name}: {len(asset.meta['classes'])} characters, val {asset.meta['metrics'].get('val_accuracy')}")
    return 201, _asset_out(asset)
