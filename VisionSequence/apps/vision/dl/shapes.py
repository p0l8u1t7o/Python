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
#: 匯出任務：mixed（原樣：bbox 5 欄、polygon 多邊形；資料集匯出／匯入互通用）、segment（polygon；bbox 轉四角，
#: ultralytics 分割訓練不吃 5 欄）、detect（bbox；polygon 取外接框）、obb（四角；polygon 取最小外接旋轉矩形）。
EXPORT_TASKS = ("mixed", "segment", "detect", "obb")


def _row_values(shape: dict[str, Any], task: str) -> list[float] | None:
    points = shape.get("points") or []
    kind = shape.get("kind")
    if kind == "bbox":
        if len(points) < 2:
            return None
        (x0, y0), (x1, y1) = points[0], points[1]
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        if task in ("detect", "mixed"):
            return [(x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0]
        return [x0, y0, x1, y0, x1, y1, x0, y1]  # segment／obb：四角
    if len(points) < 3:
        return None
    if task == "detect":
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        return [(x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0]
    if task == "obb":
        # 正規化座標的最小外接旋轉矩形（用 1000×1000 的虛擬像素避免 float 精度問題）
        arr = np.asarray([[p[0] * 1000.0, p[1] * 1000.0] for p in points], dtype=np.float32)
        box = cv2.boxPoints(cv2.minAreaRect(arr))
        return [float(v) / 1000.0 for pt in box for v in pt]
    return [v for pt in points for v in pt]


def shapes_to_yolo(shapes: list[dict[str, Any]], classes: list[str], task: str = "mixed") -> str:
    """→ YOLO txt 內容（TAB 分隔、LF、6 位小數）。不在類別清單的形狀略過；依 task 轉換形狀（見 EXPORT_TASKS）。"""
    if task not in EXPORT_TASKS:
        raise ValidationError(f"未知的匯出任務 '{task}'", code="bad_task")
    lines = []
    for shape in shapes or []:
        if shape.get("label") not in classes:
            continue
        cls = classes.index(shape["label"])
        values = _row_values(shape, task)
        if values is None:
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
def export_dataset(samples, classes: list[str], out_dir: str, *, val_ratio: float = 0.2, seed: int = 7, task: str = "mixed") -> dict[str, Any]:
    """把有標記的樣本寫成 YOLO 資料集（images/labels/{train,val[,test]} + data.yaml）。回傳統計。

    samples：iterable of (id_hex, image_path, shapes[, split])。第 4 欄 split（train｜val｜test）
    有指定就照指定；未指定的樣本照 val_ratio 隨機進 val（沒有任何指定 val 時至少 1 張）。
    已存在的 data.yaml 不覆寫（相容 WebTraining 慣例）。
    """
    rng = np.random.default_rng(seed)
    rows = [(r[0], r[1], r[2], r[3] if len(r) > 3 and r[3] in ("train", "val", "test") else "") for r in samples if r[2]]
    if not rows:
        raise ValidationError("沒有任何已標記（shapes）的樣本可匯出", code="no_labeled_samples")
    # 未指定 split 的樣本隨機補 val；已有人工指定 val 時不強迫至少 1 張（尊重指定）
    unassigned = [i for i, r in enumerate(rows) if not r[3]]
    explicit_val = any(r[3] == "val" for r in rows)
    n_val = int(round(len(unassigned) * val_ratio)) if val_ratio > 0 else 0
    if not explicit_val and val_ratio > 0 and len(rows) > 1 and unassigned:
        n_val = max(1, n_val)
    order = rng.permutation(len(unassigned))
    val_set = {unassigned[int(i)] for i in order[:n_val]}
    has_test = any(r[3] == "test" for r in rows)
    counts = {"train": 0, "val": 0, "test": 0}
    for split in ("train", "val", *(("test",) if has_test else ())):
        os.makedirs(os.path.join(out_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "labels", split), exist_ok=True)
    for i, (sid, path, shp, assigned) in enumerate(rows):
        split = assigned or ("val" if i in val_set else "train")
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            continue
        buf.tofile(os.path.join(out_dir, "images", split, f"{sid}.jpg"))
        with open(os.path.join(out_dir, "labels", split, f"{sid}.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(shapes_to_yolo(shp, classes, task))
        counts[split] += 1
    yaml_path = os.path.join(out_dir, "data.yaml")
    if not os.path.exists(yaml_path):
        names = "\n".join(f"  {i}: {c}" for i, c in enumerate(classes))
        test_line = "test: images/test\n" if counts["test"] else ""
        with open(yaml_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"path: {os.path.abspath(out_dir)}\ntrain: images/train\nval: images/val\n{test_line}nc: {len(classes)}\nnames:\n{names}\n")
    # ultralytics 會快取掃描結果；清掉避免沿用舊標記（WebTraining.md §4 的坑）
    for cache in glob.glob(os.path.join(out_dir, "labels", "*.cache")):
        try:
            os.remove(cache)
        except OSError:
            pass
    return {"dir": os.path.abspath(out_dir), "train": counts["train"], "val": counts["val"], "test": counts["test"], "classes": classes, "task": task}


def export_classify_dataset(samples, classes: list[str], out_dir: str, *, val_ratio: float = 0.2, seed: int = 7) -> dict[str, Any]:
    """classes 模式 → ultralytics 分類資料集（out_dir/{train,val[,test]}/<class>/<id>.jpg）。

    samples：iterable of (id_hex, image_path, label[, split])。類別索引以資料夾名排序為準（ultralytics 慣例），
    所以訓練後要用 model.names 取類別順序，不能假設與 classes 相同。"""
    rng = np.random.default_rng(seed)
    rows = [(r[0], r[1], r[2], r[3] if len(r) > 3 and r[3] in ("train", "val", "test") else "") for r in samples if r[2] in classes]
    if not rows:
        raise ValidationError("沒有任何已標記的樣本可匯出", code="no_labeled_samples")
    # 分層抽 val：每個類別各抽 val_ratio（有 2 張以上就至少 1 張），否則 ultralytics 會抱怨 val 缺類別
    explicit_val = any(r[3] == "val" for r in rows)
    val_set: set[int] = set()
    if val_ratio > 0 and not explicit_val:
        for c in classes:
            idx = [i for i, r in enumerate(rows) if not r[3] and r[2] == c]
            n_val = int(round(len(idx) * val_ratio))
            if len(idx) >= 2:
                n_val = max(1, n_val)
            order = rng.permutation(len(idx))
            val_set |= {idx[int(k)] for k in order[:n_val]}
    counts = {"train": 0, "val": 0, "test": 0}
    for i, (sid, path, label, assigned) in enumerate(rows):
        split = assigned or ("val" if i in val_set else "train")
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            continue
        folder = os.path.join(out_dir, split, _safe_name(label))
        os.makedirs(folder, exist_ok=True)
        buf.tofile(os.path.join(folder, f"{sid}.jpg"))
        counts[split] += 1
    # 每個 split 都要有全部類別的資料夾（ultralytics 以 train 的資料夾決定 names；val 缺類別會對不上索引）
    for split in ("train", "val"):
        for c in classes:
            os.makedirs(os.path.join(out_dir, split, _safe_name(c)), exist_ok=True)
    return {"dir": os.path.abspath(out_dir), "train": counts["train"], "val": counts["val"], "test": counts["test"], "classes": sorted(classes), "task": "classify"}


def _safe_name(label: str) -> str:
    """類別名當資料夾名：去掉路徑分隔與不可見字元（中文可以）。"""
    return "".join(ch for ch in str(label) if ch not in "\\/:*?\"<>|\n\r\t").strip() or "class"


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
