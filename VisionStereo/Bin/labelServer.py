#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YOLO 分割資料集標註網頁伺服器
==================================================
用瀏覽器讀取／編輯本地 YOLO segmentation 訓練資料夾。

功能
  1. 讀取訓練資料夾內的影像（images/train、images/val …）
  2. 網頁上調整 polygon ROI（拖曳頂點、新增／刪除頂點、新增／刪除多邊形）
  3. 變更物件分類並存回 labels/<split>/<name>.txt
  4. 多圖瀏覽（縮圖牆，直接畫出標記輪廓）
  5. 隨時變更訓練資料夾（內建目錄瀏覽器）
  6. 資料夾結構同 D:\\TrainingImage\\ATD3
  9. 設定 train / val 比例並實際套用到本地端（搬移影像與標記檔）

執行：
    python Bin/labelServer.py                       # 用預設資料夾
    python Bin/labelServer.py --root D:\\TrainingImage\\ATD3 --port 8000

相依：僅 Python 標準函式庫；PyYAML 與 Pillow 若有安裝會自動使用（更佳的
data.yaml 寫入與縮圖效能），沒有也能正常運作。
"""

import argparse
import hashlib
import io
import json
import mimetypes
import os
import random
import shutil
import string
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import yaml
except ImportError:
    yaml = None

try:
    from PIL import Image
except ImportError:
    Image = None


# ╔══════════════════════════════════════════════════════════════╗
# ║                        ▼  預設設定  ▼                        ║
# ╚══════════════════════════════════════════════════════════════╝

DEFAULT_ROOT = r"D:\TrainingImage\ATD3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
SPLIT_ORDER = ["train", "val", "test"]
WEB_DIR = Path(__file__).resolve().parent / "web"


# ───────────────────────────────────────────────
# 資料集存取層
# ───────────────────────────────────────────────

class Dataset:
    """封裝一個 YOLO 資料夾（root/dataset/images|labels 或 root/images|labels）。"""

    def __init__(self, root):
        self.lock = threading.RLock()
        self.open(root)

    # ── 開啟 / 定位 ──────────────────────────────
    def open(self, root):
        p = Path(str(root)).expanduser()
        if not p.is_dir():
            raise ValueError(f"資料夾不存在：{p}")
        p = p.resolve()

        for cand in (p / "dataset", p):
            if (cand / "images").is_dir():
                ds = cand
                break
        else:
            raise ValueError(f"找不到 images 子目錄（需為 <root>/dataset/images 或 <root>/images）：{p}")

        with self.lock:
            self.root = p
            self.ds = ds
            self.images_dir = ds / "images"
            self.labels_dir = ds / "labels"
            self.yaml_path = ds / "data.yaml"
            self._cache = {}          # label path -> (mtime, size, shapes)
        return self

    # ── 基本資訊 ────────────────────────────────
    def splits(self):
        if not self.images_dir.is_dir():
            return []
        names = [d.name for d in self.images_dir.iterdir() if d.is_dir()]
        known = [s for s in SPLIT_ORDER if s in names]
        return known + sorted(n for n in names if n not in SPLIT_ORDER)

    def image_dir(self, split):
        return self.images_dir / split

    def label_dir(self, split):
        return self.labels_dir / split

    def image_path(self, split, name):
        return self._safe(self.image_dir(split), name)

    def label_path(self, split, name):
        return self.label_dir(split) / (Path(name).stem + ".txt")

    def _safe(self, base, name):
        """阻擋路徑穿越：name 必須是 base 底下的單一檔名。"""
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"不合法的檔名：{name}")
        p = (base / name).resolve()
        if base.resolve() not in p.parents:
            raise ValueError(f"不合法的路徑：{name}")
        return p

    def list_images(self, split):
        d = self.image_dir(split)
        if not d.is_dir():
            return []
        files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        return sorted(files, key=lambda f: _natural_key(f.name))

    # ── data.yaml ───────────────────────────────
    def read_yaml(self):
        if not self.yaml_path.is_file():
            return {}
        text = self.yaml_path.read_text(encoding="utf-8-sig", errors="ignore")
        if yaml is not None:
            try:
                data = yaml.safe_load(text)
                return data if isinstance(data, dict) else {}
            except Exception:
                pass
        return _naive_yaml(text)

    def class_names(self):
        data = self.read_yaml()
        names = data.get("names")
        if isinstance(names, dict):
            out = []
            for k in sorted(names, key=lambda x: int(x)):
                out.append(str(names[k]))
            return out
        if isinstance(names, list):
            return [str(n) for n in names]
        nc = int(data.get("nc") or 0)
        return [f"class{i}" for i in range(nc)]

    def write_class_names(self, names):
        names = [str(n).strip() or f"class{i}" for i, n in enumerate(names)]
        data = self.read_yaml()
        data["path"] = str(self.ds)
        for key in ("train", "val", "test"):
            sub = self.images_dir / key
            if key not in data and sub.is_dir():
                data[key] = f"images/{key}"
        data["nc"] = len(names)
        data["names"] = {i: n for i, n in enumerate(names)}

        if yaml is not None:
            ordered = {}
            for key in ("path", "train", "val", "test", "nc", "names"):
                if key in data:
                    ordered[key] = data[key]
            for key, val in data.items():
                ordered.setdefault(key, val)
            text = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, default_flow_style=False)
        else:
            lines = [f"path: {data['path']}"]
            for key in ("train", "val", "test"):
                if key in data:
                    lines.append(f"{key}: {data[key]}")
            lines.append(f"nc: {len(names)}")
            lines.append("names:")
            lines += [f"  {i}: {n}" for i, n in enumerate(names)]
            text = "\n".join(lines) + "\n"

        self.yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.yaml_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return names

    # ── 標記檔 ──────────────────────────────────
    def read_shapes(self, split, name):
        path = self.label_path(split, name)
        try:
            st = path.stat()
        except OSError:
            return []
        key = str(path)
        hit = self._cache.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        shapes = _parse_label(path)
        if len(self._cache) > 8000:
            self._cache.clear()
        self._cache[key] = (st.st_mtime_ns, st.st_size, shapes)
        return shapes

    def write_shapes(self, split, name, shapes):
        path = self.label_path(split, name)
        lines = []
        for s in shapes:
            pts = [[float(p[0]), float(p[1])] for p in s.get("points", [])]
            if len(pts) < 3:
                continue
            cls = max(0, int(s.get("cls", 0)))
            if s.get("kind") == "bbox":
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                vals = [(x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0]
            else:
                vals = [v for p in pts for v in p]
            vals = [min(1.0, max(0.0, v)) for v in vals]
            # 以 TAB 分隔，與既有標記檔一致
            lines.append("\t".join([str(cls)] + [f"{v:.6f}" for v in vals]))

        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n"：與既有標記檔一致，不寫成 Windows CRLF
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(("\n".join(lines) + "\n") if lines else "")
        self._cache.pop(str(path), None)
        self.clear_cache_files()
        return len(lines)

    def clear_cache_files(self):
        """刪除 ultralytics 的 *.cache，避免下次訓練沿用舊標記。"""
        removed = []
        if self.labels_dir.is_dir():
            for f in self.labels_dir.glob("*.cache"):
                try:
                    f.unlink()
                    removed.append(f.name)
                except OSError:
                    pass
        return removed

    # ── 統計 ────────────────────────────────────
    def summarize(self, split, name):
        shapes = self.read_shapes(split, name)
        return {
            "count": len(shapes),
            "classes": sorted({int(s["cls"]) for s in shapes}),
        }

    def stats(self):
        out = {}
        for sp in self.splits():
            imgs = self.list_images(sp)
            labeled = 0
            objs = 0
            per_class = {}
            for f in imgs:
                shapes = self.read_shapes(sp, f.name)
                if shapes:
                    labeled += 1
                objs += len(shapes)
                for s in shapes:
                    per_class[str(s["cls"])] = per_class.get(str(s["cls"]), 0) + 1
            out[sp] = {"images": len(imgs), "labeled": labeled,
                       "objects": objs, "perClass": per_class}
        return out

    # ── train / val 比例套用 ─────────────────────
    def apply_split(self, train_ratio, seed=0, shuffle=True, include_test=False, dry_run=False):
        ratio = min(1.0, max(0.0, float(train_ratio)))
        pools = ["train", "val"] + (["test"] if include_test else [])
        pools = [s for s in pools if self.image_dir(s).is_dir() or s in ("train", "val")]

        items = []   # (current_split, image Path)
        for sp in pools:
            for f in self.list_images(sp):
                items.append((sp, f))

        if not items:
            return {"total": 0, "moved": 0, "train": 0, "val": 0, "conflicts": [], "dryRun": dry_run}

        order = list(items)
        if shuffle:
            random.Random(int(seed)).shuffle(order)
        else:
            order.sort(key=lambda it: _natural_key(it[1].name))

        n_train = int(round(len(order) * ratio))
        n_train = max(0, min(len(order), n_train))
        targets = {}
        for i, (sp, f) in enumerate(order):
            targets[f] = "train" if i < n_train else "val"

        moved, conflicts = 0, []
        plan = [(sp, f, targets[f]) for sp, f in items if targets[f] != sp]

        if not dry_run:
            for sp, f, dst_split in plan:
                dst_img = self.image_dir(dst_split) / f.name
                if dst_img.exists():
                    conflicts.append(f"{sp}/{f.name} → {dst_split}（同名檔已存在，略過）")
                    continue
                dst_img.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dst_img))
                src_lbl = self.label_dir(sp) / (f.stem + ".txt")
                if src_lbl.is_file():
                    dst_lbl = self.label_dir(dst_split) / (f.stem + ".txt")
                    dst_lbl.parent.mkdir(parents=True, exist_ok=True)
                    if dst_lbl.exists():
                        dst_lbl.unlink()
                    shutil.move(str(src_lbl), str(dst_lbl))
                moved += 1
            self._cache.clear()
            self.clear_cache_files()
        else:
            for sp, f, dst_split in plan:
                if (self.image_dir(dst_split) / f.name).exists():
                    conflicts.append(f"{sp}/{f.name} → {dst_split}（同名檔已存在，將略過）")
            moved = len(plan) - len(conflicts)

        return {
            "total": len(order),
            "moved": moved,
            "train": n_train,
            "val": len(order) - n_train,
            "conflicts": conflicts[:50],
            "conflictCount": len(conflicts),
            "dryRun": dry_run,
        }


# ───────────────────────────────────────────────
# 工具函式
# ───────────────────────────────────────────────

def _natural_key(name):
    parts, num = [], ""
    for ch in name:
        if ch.isdigit():
            num += ch
        else:
            if num:
                parts.append((1, int(num), ""))
                num = ""
            parts.append((0, 0, ch.lower()))
    if num:
        parts.append((1, int(num), ""))
    return parts


def _parse_label(path):
    shapes = []
    try:
        # utf-8-sig：容忍其他工具寫出的 BOM
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return shapes
    for line in text.splitlines():
        # 以 TAB 為分隔；若該行沒有 TAB（舊檔以空白分隔）則退回空白切分
        tok = line.split("\t") if "\t" in line else line.split()
        tok = [t for t in (x.strip() for x in tok) if t]
        if len(tok) < 5:
            continue
        try:
            cls = int(float(tok[0]))
            nums = [float(x) for x in tok[1:]]
        except ValueError:
            continue
        if len(nums) == 4:
            cx, cy, w, h = nums
            pts = [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2],
                   [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]]
            shapes.append({"cls": cls, "kind": "bbox", "points": pts})
        elif len(nums) >= 6 and len(nums) % 2 == 0:
            pts = [[nums[i], nums[i + 1]] for i in range(0, len(nums), 2)]
            shapes.append({"cls": cls, "kind": "polygon", "points": pts})
    return shapes


def _naive_yaml(text):
    """PyYAML 不存在時的極簡解析（只處理本專案 data.yaml 的形態）。"""
    data, names, in_names = {}, {}, False
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indented = raw[:1].isspace()
        line = raw.strip()
        if in_names and indented and ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().strip("'\"")
            if k.isdigit():
                names[int(k)] = v.strip().strip("'\"")
                continue
        if in_names and indented and line.startswith("-"):
            names[len(names)] = line[1:].strip().strip("'\"")
            continue
        in_names = False
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k == "names":
                in_names = True
                continue
            data[k] = int(v) if v.isdigit() else v.strip("'\"")
    if names:
        data["names"] = names
    return data


def list_dirs(path):
    """給前端目錄瀏覽器用：回傳磁碟機或子目錄清單。"""
    if not path:
        if os.name == "nt":
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return {"path": "", "parent": None, "dirs": [{"name": d, "path": d} for d in drives]}
        path = "/"
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError(f"資料夾不存在：{p}")
    p = p.resolve()
    dirs = []
    try:
        for d in sorted(p.iterdir(), key=lambda x: _natural_key(x.name)):
            if d.is_dir() and not d.name.startswith("$"):
                dirs.append({"name": d.name, "path": str(d)})
    except PermissionError:
        pass
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "dirs": dirs}


def _file_etag(path, extra=""):
    """以完整路徑 + mtime + size 當版本；換資料集或檔案被改就一定不同。"""
    st = path.stat()
    key = f"{path}|{st.st_mtime_ns}|{st.st_size}|{extra}"
    return '"' + hashlib.md5(key.encode("utf-8", "ignore")).hexdigest() + '"'


def make_thumb(path, width):
    """回傳 (bytes, mimetype)；沒有 Pillow 就直接回原圖。"""
    if Image is None:
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with Image.open(path) as im:
        im.draft("RGB", (width, width))
        im = im.convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, max(1, round(h * width / w))), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
        return buf.getvalue(), "image/jpeg"


def _video_module():
    """延後載入 videoDataset（它會拉進 torch/ultralytics，啟動時不該付這個成本）。"""
    global _video_mod
    if _video_mod is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import videoDataset
        _video_mod = videoDataset
    return _video_mod


def _train_module():
    """延後載入 trainJob（同樣會拉進 torch/ultralytics）。"""
    global _train_mod
    if _train_mod is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import trainJob
        _train_mod = trainJob
    return _train_mod


_video_mod = None
_train_mod = None


# ───────────────────────────────────────────────
# HTTP 伺服器
# ───────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "YoloLabelServer/1.0"
    dataset = None            # 由 main() 指派

    # ── 回應輔助 ────────────────────────────────
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, ctype, cache=False, etag=None):
        """etag 不為 None 時走「必須回源驗證」的快取：內容換了就一定拿得到新的。

        影像不能用 max-age 直接快取——不同資料集的檔名幾乎都是 1.jpg、2.jpg，
        URL 會完全相同，瀏覽器就會拿上一個資料集的舊圖去配新的標記。
        """
        if etag is not None:
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_response(200)
            self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-store")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    # ── 路由 ────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = unquote(u.path)
        try:
            if path.startswith("/api/"):
                return self._api_get(path, q)
            return self._static(path)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except FileNotFoundError as e:
            self._json({"error": str(e)}, 404)
        except Exception as e:                                   # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        try:
            return self._api_post(path, self._body())
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:                                   # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ── MJPEG 預覽串流 ──────────────────────────
    def _mjpeg(self, fps):
        """multipart/x-mixed-replace 串流：一條連線由伺服器主動推畫面。

        比起前端不斷輪詢圖片，省掉每張圖一次 HTTP 來回；而且轉檔端是
        「有觀看者才產生預覽」，關掉這個分頁就完全不影響轉檔速度。
        """
        vd = _video_module()
        gap = 1.0 / max(0.2, min(10.0, fps))
        boundary = "vsframe"

        self.send_response(200)
        self.send_header("Content-Type",
                         f"multipart/x-mixed-replace; boundary={boundary}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()

        vd.viewer_enter(1.0 / gap)
        last_seq, last_sent = 0, 0.0
        idle_since = time.time()
        try:
            while True:
                got = vd.wait_preview(last_seq, timeout=1.0)
                if got is None:
                    # 工作沒在跑且已閒置一段時間才收線（用時間判斷，不數次數）
                    if time.time() - idle_since > 10 and not vd.is_running():
                        break
                    continue
                idle_since = time.time()
                last_seq, jpeg, _info = got
                now = time.time()
                if now - last_sent < gap:        # 依前端要求的 fps 節流
                    continue
                last_sent = now
                self.wfile.write(
                    f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass                                  # 前端關掉分頁就是這條路
        finally:
            vd.viewer_exit(1.0 / gap)

    # ── 靜態檔 ──────────────────────────────────
    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in f.parents or not f.is_file():
            self._json({"error": f"找不到 {rel}"}, 404)
            return
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._bytes(f.read_bytes(), ctype)

    # ── GET API ─────────────────────────────────
    def _api_get(self, path, q):
        ds = self.dataset

        if path == "/api/config":
            return self._json(self._config())

        if path == "/api/browse":
            return self._json(list_dirs(q.get("path", "")))

        if path == "/api/list":
            split = q.get("split") or (ds.splits() or ["train"])[0]
            files = ds.list_images(split)
            items = []
            for f in files:
                info = ds.summarize(split, f.name)
                items.append({"name": f.name, "objects": info["count"], "classes": info["classes"]})

            key = (q.get("q") or "").lower()
            if key:
                items = [it for it in items if key in it["name"].lower()]
            cls = q.get("cls")
            if cls not in (None, "", "-1"):
                cid = int(cls)
                items = [it for it in items if cid in it["classes"]]
            state = q.get("state") or "all"
            if state == "labeled":
                items = [it for it in items if it["objects"] > 0]
            elif state == "empty":
                items = [it for it in items if it["objects"] == 0]

            total = len(items)
            page = max(0, int(q.get("page") or 0))
            size = max(1, min(500, int(q.get("pageSize") or 60)))
            return self._json({"split": split, "total": total, "page": page,
                               "pageSize": size, "items": items[page * size:(page + 1) * size]})

        if path == "/api/label":
            split, name = q["split"], q["name"]
            return self._json({"split": split, "name": name,
                               "shapes": ds.read_shapes(split, name),
                               "labelPath": str(ds.label_path(split, name))})

        if path == "/api/image":
            p = ds.image_path(q["split"], q["name"])
            if not p.is_file():
                raise FileNotFoundError(f"影像不存在：{q['name']}")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return self._bytes(p.read_bytes(), ctype, etag=_file_etag(p))

        if path == "/api/thumb":
            p = ds.image_path(q["split"], q["name"])
            if not p.is_file():
                raise FileNotFoundError(f"影像不存在：{q['name']}")
            w = max(64, min(1024, int(q.get("w") or 320)))
            data, ctype = make_thumb(p, w)
            return self._bytes(data, ctype, etag=_file_etag(p, f"t{w}"))

        if path == "/api/stats":
            return self._json(ds.stats())

        # ── 影片轉資料集 ───────────────────────────
        if path == "/api/video/list":
            vd = _video_module()
            return self._json({"dir": q.get("dir") or vd.DEFAULT_VIDEO_DIR,
                               "videos": vd.list_videos(q.get("dir") or vd.DEFAULT_VIDEO_DIR)})

        if path == "/api/video/status":
            lf = q.get("logFrom")
            return self._json(_video_module().get_status(
                None if lf in (None, "") else int(lf)))

        if path == "/api/video/stream":
            return self._mjpeg(float(q.get("fps") or 2))

        if path == "/api/video/preview":
            got = _video_module().latest_preview()
            if not got:
                raise FileNotFoundError("目前沒有預覽畫面")
            return self._bytes(got[1], "image/jpeg")

        # ── 訓練 ───────────────────────────────────
        if path == "/api/train/status":
            lf = q.get("logFrom")
            return self._json(_train_module().get_status(
                None if lf in (None, "") else int(lf)))

        if path == "/api/train/defaults":
            tm = _train_module()
            d = dict(tm.DEFAULTS)
            # 預設用目前開啟的資料集，並把實驗名稱帶成資料集名稱
            if ds.yaml_path.is_file():
                d["data"] = str(ds.yaml_path)
            d["name"] = ds.root.name or d["name"]
            d["outputDir"] = str(Path(d["project"]) / d["name"])
            return self._json(d)

        if path == "/api/video/defaults":
            vd = _video_module()
            return self._json({"videoDir": vd.DEFAULT_VIDEO_DIR,
                               "outDir": vd.DEFAULT_OUT_DIR,
                               "modelPath": vd.DEFAULT_MODEL,
                               "consecutive": vd.CONSECUTIVE_FRAMES,
                               **vd.DEFAULTS})

        raise FileNotFoundError(f"未知的 API：{path}")

    # ── POST API ────────────────────────────────
    def _api_post(self, path, body):
        ds = self.dataset

        if path == "/api/root":
            ds.open(body.get("path", ""))
            return self._json(self._config())

        if path == "/api/label":
            n = ds.write_shapes(body["split"], body["name"], body.get("shapes", []))
            return self._json({"ok": True, "lines": n,
                               "labelPath": str(ds.label_path(body["split"], body["name"]))})

        if path == "/api/classes":
            names = ds.write_class_names(body.get("names", []))
            return self._json({"ok": True, "classes": names, "yaml": str(ds.yaml_path)})

        if path == "/api/video/start":
            vd = _video_module()
            return self._json(vd.start_job(
                video_dir=body.get("videoDir") or vd.DEFAULT_VIDEO_DIR,
                out_dir=body.get("outDir") or vd.DEFAULT_OUT_DIR,
                model_path=body.get("modelPath") or vd.DEFAULT_MODEL,
                conf=body.get("conf"),
                imgsz=body.get("imgsz"),
                minArea=body.get("minArea"),
                edgeMargin=body.get("edgeMargin"),
                maxPolyPoints=body.get("maxPolyPoints"),
                split=body.get("split"),
            ))

        if path == "/api/video/stop":
            return self._json(_video_module().stop_job())

        if path == "/api/train/start":
            tm = _train_module()
            cfg = {k: v for k, v in body.items() if k in tm.DEFAULTS}
            if not cfg.get("data"):
                cfg["data"] = str(ds.yaml_path)
            return self._json(tm.start_job(**cfg))

        if path == "/api/train/stop":
            return self._json(_train_module().stop_job())

        if path == "/api/split":
            res = ds.apply_split(
                train_ratio=body.get("trainRatio", 0.8),
                seed=body.get("seed", 0),
                shuffle=bool(body.get("shuffle", True)),
                include_test=bool(body.get("includeTest", False)),
                dry_run=bool(body.get("dryRun", False)),
            )
            res["ok"] = True
            return self._json(res)

        raise FileNotFoundError(f"未知的 API：{path}")

    def _config(self):
        ds = self.dataset
        return {
            "root": str(ds.root),
            "dataset": str(ds.ds),
            "yaml": str(ds.yaml_path),
            "splits": ds.splits(),
            "classes": ds.class_names(),
            "hasPillow": Image is not None,
            "hasYaml": yaml is not None,
        }


# ───────────────────────────────────────────────
# 建立伺服器
# ───────────────────────────────────────────────

def _attach_dataset(root):
    """指派 Handler.dataset；資料夾不合法時以空資料集啟動（可於網頁再指定）。"""
    try:
        Handler.dataset = Dataset(root)
        return ""
    except ValueError as e:
        ds = Dataset.__new__(Dataset)
        ds.lock = threading.RLock()
        ds.root = Path(root)
        ds.ds = Path(root)
        ds.images_dir = Path(root) / "images"
        ds.labels_dir = Path(root) / "labels"
        ds.yaml_path = Path(root) / "data.yaml"
        ds._cache = {}
        Handler.dataset = ds
        return str(e)


def _create_server(host, port):
    if not WEB_DIR.is_dir():
        raise FileNotFoundError(f"找不到前端目錄：{WEB_DIR}")
    return ThreadingHTTPServer((host, port), Handler)


# ══════════════════════════════════════════════════════════════
# LabVIEW Python Node 介面
# ══════════════════════════════════════════════════════════════
# 兩個函式都是「下達命令後立刻返回」，不會讓 Python Node 停在那裡等：
# 伺服器跑在背景 daemon thread，stop 也是丟給另一條執行緒去關。
# 回傳值一律是 JSON 字串（LabVIEW 端用 String 接）。
#
#   啟動：start_server("D:\\TrainingImage\\ATD3", "127.0.0.1", 8000)
#   停用：stop_server()
#   查詢：server_status()
# ══════════════════════════════════════════════════════════════

_srv = None
_srv_thread = None
_srv_lock = threading.RLock()
_srv_info = {"host": "", "port": 0, "url": "", "root": ""}


def start_server(root="", host=DEFAULT_HOST, port=DEFAULT_PORT, open_browser=False):
    """啟動標註伺服器後立即返回（不阻塞呼叫端）。

    root         訓練資料夾，留空則用 DEFAULT_ROOT
    host / port  監聽位址；port 傳 0 由系統指派
    open_browser 是否自動開瀏覽器（LabVIEW 端通常設 False）

    回傳 JSON：{"ok":true,"running":true,"url":"http://127.0.0.1:8000/", ...}
    重複呼叫不會重啟，會直接回傳目前的狀態。
    """
    global _srv, _srv_thread
    with _srv_lock:
        try:
            if _srv is not None:
                return json.dumps({"ok": True, "running": True,
                                   "message": "伺服器已在執行中", **_srv_info},
                                  ensure_ascii=False)

            warn = _attach_dataset(root or DEFAULT_ROOT)
            srv = _create_server(host, int(port))
            actual_port = srv.server_address[1]

            _srv = srv
            _srv_thread = threading.Thread(target=srv.serve_forever,
                                           kwargs={"poll_interval": 0.2},
                                           daemon=True, name="labelServer")
            _srv_thread.start()

            _srv_info.update({
                "host": host,
                "port": actual_port,
                "url": f"http://{host}:{actual_port}/",
                "root": str(Handler.dataset.ds),
            })
            if open_browser:
                threading.Timer(0.6, lambda: webbrowser.open(_srv_info["url"])).start()

            return json.dumps({"ok": True, "running": True, "warning": warn,
                               **_srv_info}, ensure_ascii=False)

        except Exception as e:                                # noqa: BLE001
            _srv = None
            _srv_thread = None
            return json.dumps({"ok": False, "running": False,
                               "error": f"{type(e).__name__}: {e}"},
                              ensure_ascii=False)


def stop_server():
    """停用伺服器後立即返回（實際關閉在背景執行緒完成）。

    回傳 JSON：{"ok":true,"running":false,...}
    """
    global _srv, _srv_thread
    with _srv_lock:
        srv = _srv
        _srv = None
        _srv_thread = None
        info = dict(_srv_info)
        _srv_info.update({"host": "", "port": 0, "url": "", "root": ""})

    if srv is None:
        return json.dumps({"ok": True, "running": False,
                           "message": "伺服器並未在執行"}, ensure_ascii=False)

    def _shutdown():
        # shutdown() 會等 serve_forever 迴圈收尾，所以不能在呼叫端執行緒裡做
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass

    threading.Thread(target=_shutdown, daemon=True, name="labelServerStop").start()
    return json.dumps({"ok": True, "running": False,
                       "message": "已送出停用命令", **info}, ensure_ascii=False)


def server_status():
    """回傳伺服器目前狀態 JSON（供 LabVIEW 確認是否真的起來了）。"""
    with _srv_lock:
        running = _srv is not None
        info = dict(_srv_info)
    return json.dumps({"ok": True, "running": running, **info}, ensure_ascii=False)


# ───────────────────────────────────────────────
# 主程式
# ───────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="YOLO 分割資料集標註網頁伺服器")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="訓練資料夾根目錄")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true", help="啟動後不自動開啟瀏覽器")
    ap.add_argument("--verbose", action="store_true", help="顯示 HTTP 請求記錄")
    args = ap.parse_args()

    if not WEB_DIR.is_dir():
        sys.exit(f"[ERROR] 找不到前端目錄：{WEB_DIR}")

    warn = _attach_dataset(args.root)
    if warn:
        print(f"[WARN] {warn}")
        print("[WARN] 先以空資料集啟動，請於網頁上方「變更資料夾」重新指定。")

    url = f"http://{args.host}:{args.port}/"
    srv = _create_server(args.host, args.port)
    print("=" * 60)
    print("  YOLO 分割標註網頁伺服器")
    print("=" * 60)
    print(f"  資料夾   : {Handler.dataset.ds}")
    print(f"  網址     : {url}")
    print(f"  PyYAML   : {'OK' if yaml else '未安裝（data.yaml 以簡易格式寫入）'}")
    print(f"  Pillow   : {'OK' if Image else '未安裝（縮圖改用原圖，較慢）'}")
    print("  Ctrl+C 結束")
    print("=" * 60)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 伺服器已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
