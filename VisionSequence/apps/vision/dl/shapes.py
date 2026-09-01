"""shapes 標記（polygon / bbox）：驗證、YOLO txt 互轉、遮罩 rasterize、資料集匯出／匯入。

shapes 格式（DB 與 API）：[{"label": 類別名, "kind": "polygon"|"bbox", "points": [[x,y],…]}]，
座標一律 0~1 正規化。YOLO txt 相容 VisionStereo（WebTraining.md §4）：TAB 分隔、LF 換行、
utf-8-sig 讀、6 位小數、5 欄=bbox（cls cx cy w h）、≥7 欄偶數座標=polygon。
"""

from __future__ import annotations

import glob
import os
from typing import Any

import cv2
import numpy as np

from apps.core.errors import ValidationError

SHAPE_KINDS = ("polygon", "bbox")


def validate_shapes(raw: Any, classes: list[str]) -> list[dict[str, Any]]:
    """驗證並正規化 API 傳入的 shapes；座標 clamp 到 [0,1]。"""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValidationError("shapes 必須是清單", code="bad_shapes")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"shapes[{i}] 不是物件", code="bad_shapes")
        label = str(item.get("label") or "")
        if label not in classes:
            raise ValidationError(f"shapes[{i}] 的類別 '{label}' 不在類別清單內", code="bad_shapes")
        kind = str(item.get("kind") or "polygon")
        if kind not in SHAPE_KINDS:
            raise ValidationError(f"shapes[{i}] 的 kind '{kind}' 不合法（polygon / bbox）", code="bad_shapes")
        points = item.get("points")
        if not isinstance(points, list) or len(points) < (3 if kind == "polygon" else 2):
            raise ValidationError(f"shapes[{i}] 的點數不足", code="bad_shapes")
        clean = []
        for pt in points:
            try:
                x, y = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                raise ValidationError(f"shapes[{i}] 的座標格式錯誤", code="bad_shapes") from None
            clean.append([min(1.0, max(0.0, x)), min(1.0, max(0.0, y))])
        if kind == "bbox":
            xs, ys = [p[0] for p in clean], [p[1] for p in clean]
            clean = [[min(xs), min(ys)], [max(xs), max(ys)]]
        out.append({"label": label, "kind": kind, "points": clean})
    return out


# ---------------------------------------------------------------------------
# YOLO txt 互轉
# ---------------------------------------------------------------------------
def shapes_to_yolo(shapes: list[dict[str, Any]], classes: list[str]) -> str:
    """→ YOLO txt 內容（TAB 分隔、LF、6 位小數）。不在類別清單的形狀略過。"""
    lines = []
    for shape in shapes or []:
        if shape.get("label") not in classes:
            continue
        cls = classes.index(shape["label"])
        points = shape.get("points") or []
        if shape.get("kind") == "bbox" and len(points) >= 2:
            (x0, y0), (x1, y1) = points[0], points[1]
            values = [(x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0), abs(y1 - y0)]
        elif len(points) >= 3:
            values = [v for pt in points for v in pt]
        else:
            continue
        lines.append("\t".join([str(cls)] + [f"{min(1.0, max(0.0, v)):.6f}" for v in values]))
    return "\n".join(lines) + ("\n" if lines else "")


def yolo_to_shapes(text: str, classes: list[str]) -> list[dict[str, Any]]:
    """YOLO txt → shapes。5 欄=bbox、≥7 欄偶數座標=polygon；<3 點的丟棄；類別索引超界丟棄。"""
    out: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        try:
            cls = int(parts[0])
            values = [float(v) for v in parts[1:]]
        except (ValueError, IndexError):
            continue
        if cls < 0 or cls >= len(classes):
            continue
        if len(values) == 4:
            cx, cy, w, h = values
            out.append({"label": classes[cls], "kind": "bbox",
                        "points": [[cx - w / 2, cy - h / 2], [cx + w / 2, cy + h / 2]]})
        elif len(values) >= 6 and len(values) % 2 == 0:
            points = [[values[i], values[i + 1]] for i in range(0, len(values), 2)]
            if len(points) >= 3:
                out.append({"label": classes[cls], "kind": "polygon", "points": points})
    return out


# ---------------------------------------------------------------------------
# rasterize（輕量語意分割訓練用）
# ---------------------------------------------------------------------------
def rasterize(shapes: list[dict[str, Any]], classes: list[str], height: int, width: int) -> np.ndarray:
    """shapes → 類別遮罩 uint8（0=背景、i+1=classes[i]），後畫的蓋前畫的。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    for shape in shapes or []:
        if shape.get("label") not in classes:
            continue
        value = classes.index(shape["label"]) + 1
        points = np.array([[p[0] * width, p[1] * height] for p in shape.get("points") or []], dtype=np.float64)
        if shape.get("kind") == "bbox" and len(points) >= 2:
            x0, y0 = points[0]
            x1, y1 = points[1]
            cv2.rectangle(mask, (int(round(x0)), int(round(y0))), (int(round(x1)), int(round(y1))), int(value), -1)
        elif len(points) >= 3:
            cv2.fillPoly(mask, [np.round(points).astype(np.int32)], int(value))
    return mask


# ---------------------------------------------------------------------------
# 資料集匯出／匯入（與 VisionStereo 互通）
# ---------------------------------------------------------------------------
def export_dataset(samples, classes: list[str], out_dir: str, *, val_ratio: float = 0.2, seed: int = 7) -> dict[str, Any]:
    """把有標記的樣本寫成 YOLO 資料集（images/labels/{train,val} + data.yaml）。回傳統計。

    samples：iterable of (id_hex, image_path, shapes)。已存在的 data.yaml 不覆寫（相容 WebTraining 慣例）。
    """
    rng = np.random.default_rng(seed)
    rows = [(sid, path, shp) for sid, path, shp in samples if shp]
    if not rows:
        raise ValidationError("沒有任何已標記（shapes）的樣本可匯出", code="no_labeled_samples")
    order = rng.permutation(len(rows))
    n_val = max(1, int(round(len(rows) * val_ratio))) if val_ratio > 0 and len(rows) > 1 else 0
    val_set = {int(i) for i in order[:n_val]}
    counts = {"train": 0, "val": 0}
    for split in ("train", "val"):
        os.makedirs(os.path.join(out_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "labels", split), exist_ok=True)
    for i, (sid, path, shp) in enumerate(rows):
        split = "val" if i in val_set else "train"
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            continue
        buf.tofile(os.path.join(out_dir, "images", split, f"{sid}.jpg"))
        with open(os.path.join(out_dir, "labels", split, f"{sid}.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(shapes_to_yolo(shp, classes))
        counts[split] += 1
    yaml_path = os.path.join(out_dir, "data.yaml")
    if not os.path.exists(yaml_path):
        names = "\n".join(f"  {i}: {c}" for i, c in enumerate(classes))
        with open(yaml_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"path: {os.path.abspath(out_dir)}\ntrain: images/train\nval: images/val\nnc: {len(classes)}\nnames:\n{names}\n")
    # ultralytics 會快取掃描結果；清掉避免沿用舊標記（WebTraining.md §4 的坑）
    for cache in glob.glob(os.path.join(out_dir, "labels", "*.cache")):
        try:
            os.remove(cache)
        except OSError:
            pass
    return {"dir": os.path.abspath(out_dir), "train": counts["train"], "val": counts["val"], "classes": classes}


def iter_dataset(root: str) -> list[tuple[str, str]]:
    """YOLO 資料夾 → [(image_path, label_text)]；root 或 root/dataset 底下含 images/ 都接受。"""
    base = root
    if not os.path.isdir(os.path.join(base, "images")) and os.path.isdir(os.path.join(base, "dataset", "images")):
        base = os.path.join(base, "dataset")
    images_root = os.path.join(base, "images")
    if not os.path.isdir(images_root):
        raise ValidationError(f"找不到 YOLO 資料集（{root} 底下沒有 images/）", code="bad_dataset")
    out: list[tuple[str, str]] = []
    for split in sorted(os.listdir(images_root)):
        folder = os.path.join(images_root, split)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if os.path.splitext(name)[1].lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
                continue
            label_path = os.path.join(base, "labels", split, os.path.splitext(name)[0] + ".txt")
            text = ""
            if os.path.isfile(label_path):
                with open(label_path, encoding="utf-8-sig") as f:
                    text = f.read()
            out.append((os.path.join(folder, name), text))
    return out


def read_yaml_classes(root: str) -> list[str]:
    """讀 data.yaml 的 names（dict 或 list 兩種寫法都接受）；讀不到回空清單。"""
    for base in (root, os.path.join(root, "dataset")):
        path = os.path.join(base, "data.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        names: dict[int, str] = {}
        in_names = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("names:"):
                rest = stripped[6:].strip()
                if rest.startswith("["):  # names: [a, b]
                    inner = rest.strip("[]")
                    return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
                in_names = True
                continue
            if in_names:
                if not line.startswith((" ", "\t")) or ":" not in stripped:
                    break
                key, _, value = stripped.partition(":")
                try:
                    names[int(key.strip())] = value.strip().strip("'\"")
                except ValueError:
                    break
        if names:
            return [names[i] for i in sorted(names)]
    return []
