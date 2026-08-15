#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
影片 → YOLO 分割資料集
==================================================
掃描指定資料夾（預設 D:\\CaptureVideo）內所有 .avi，沿用 yoloSegByteTrack.py 的
推論／追蹤／過濾流程（FramePrep → YOLO.track(bytetrack) → conf/area/edge 過濾
→ approxPolyDP 簡化 polygon），當畫面中出現的「新 Track ID」連續 2 幀都在時，
就把該幀收進資料集：

    <輸出資料夾>/dataset/images/train/<n>.jpg     整幀原始解析度影像
    <輸出資料夾>/dataset/labels/train/<n>.txt     該幀所有物件的 YOLO seg 標記
    <輸出資料夾>/dataset/data.yaml                類別取自模型

檔名依數字續編（資料夾已有 1~120.jpg 就從 121 開始）。

用法
    # 命令列
    python Bin/videoDataset.py --videos D:\\CaptureVideo --out D:\\TrainingImage\\NEW

    # 由 labelServer 的網頁介面呼叫（背景執行緒 + 進度查詢）
    import videoDataset
    videoDataset.start_job(video_dir, out_dir)
    videoDataset.get_status()
    videoDataset.stop_job()

註：torch / ultralytics 只在真正開始轉換時才 import，伺服器啟動不受影響。
"""

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))


# ╔══════════════════════════════════════════════════════════════╗
# ║                        ▼  預設設定  ▼                        ║
# ╚══════════════════════════════════════════════════════════════╝

DEFAULT_VIDEO_DIR = r"D:\CaptureVideo"
DEFAULT_OUT_DIR = r"D:\TrainingImage\FromVideo"
DEFAULT_MODEL = r"D:\Working Space\Python\VisionStereo\weights\best.pt"

VIDEO_EXTS = (".avi", ".mp4", ".mkv", ".mov", ".wmv")

# 新 Track ID 連續出現幾幀才收錄
CONSECUTIVE_FRAMES = 2

# ── 即時預覽 ────────────────────────────────────
# 預覽是「有人在看才做」：沒有任何瀏覽器連上 /api/video/stream 時，
# 完全不會複製影格、不畫 overlay、也不編碼 JPEG，轉檔速度不受影響。
PREVIEW_MAX_FPS = 4          # 產生端上限（實際送出速率由前端要求的 fps 再節流）
PREVIEW_QUALITY = 70         # JPEG 品質
PREVIEW_MAX_W = 720          # 超過此寬度才縮圖（推論影格通常已經 640 左右）

# 以下預設值與 yoloSegByteTrack.py 一致，可由 start_job() 覆寫
DEFAULTS = {
    "imgsz": 640,
    "conf": 0.4,
    "minArea": 500,
    "edgeMargin": 50,
    "maxDet": 100,
    "maxPolyPoints": 12,
    "jpegQuality": 95,
    "split": "train",
    "tracker": "bytetrack.yaml",
}


# ══════════════════════════════════════════════════════════════
# 工作狀態（供網頁輪詢）
# ══════════════════════════════════════════════════════════════

_lock = threading.RLock()
_thread = None
_stop_flag = threading.Event()

_state = {
    "running": False,
    "done": False,
    "error": "",
    "phase": "idle",          # idle | loading | running | finished | stopped | error
    "videoDir": "",
    "outDir": "",
    "datasetDir": "",
    "videos": [],             # [{name, frames, processed, captured}]
    "videoIndex": 0,
    "videoCount": 0,
    "currentVideo": "",
    "framesDone": 0,
    "framesTotal": 0,
    "captured": 0,
    "firstIndex": 0,
    "lastIndex": 0,
    "classes": [],
    "startedAt": 0.0,
    "elapsed": 0.0,
    "log": [],
}


_LOG_KEEP = 200
_log_base = 0                  # 已被丟棄的行數，用來換算全域行號


def _set(**kw):
    with _lock:
        _state.update(kw)


def _log(msg):
    global _log_base
    with _lock:
        _state["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
        over = len(_state["log"]) - _LOG_KEEP
        if over > 0:
            del _state["log"][:over]
            _log_base += over


def get_status(log_from=None):
    """回傳目前進度。

    log_from 給定時只回傳該行號之後的新記錄（前端每秒輪詢，不必每次都把
    整份 log 重傳一遍）。回傳的 logNext 就是下次要帶入的行號。
    """
    with _lock:
        st = dict(_state)
        st["videos"] = [dict(v) for v in _state["videos"]]
        total = _log_base + len(_state["log"])
        if log_from is None:
            st["log"] = list(_state["log"])
            st["logFrom"] = _log_base
        else:
            start = max(0, min(len(_state["log"]), int(log_from) - _log_base))
            st["log"] = _state["log"][start:]
            st["logFrom"] = _log_base + start
        st["logNext"] = total
        st["viewers"] = _pv_viewers          # 目前有幾個預覽連線
        if st["running"] and st["startedAt"]:
            st["elapsed"] = round(time.time() - st["startedAt"], 1)
        return st


def is_running():
    with _lock:
        return bool(_state["running"])


# ══════════════════════════════════════════════════════════════
# 即時預覽（產生端 / 觀看端）
# ══════════════════════════════════════════════════════════════

_pv_cv = threading.Condition()
_pv = {"seq": 0, "jpeg": None, "info": {}}
_pv_viewers = 0
_pv_fps = []                   # 各觀看者要求的 fps；產生端只需滿足最快的那個


def viewer_enter(fps=2.0):
    global _pv_viewers
    with _pv_cv:
        _pv_viewers += 1
        _pv_fps.append(float(fps))
        return _pv_viewers


def viewer_exit(fps=2.0):
    global _pv_viewers
    with _pv_cv:
        _pv_viewers = max(0, _pv_viewers - 1)
        try:
            _pv_fps.remove(float(fps))
        except ValueError:
            pass
        if _pv_viewers == 0:
            _pv_fps.clear()
        return _pv_viewers


def has_viewers():
    with _pv_cv:
        return _pv_viewers > 0


def preview_interval():
    """產生端的最小間隔：跟著目前最快的觀看者，沒人看就回 None。"""
    with _pv_cv:
        if not _pv_viewers:
            return None
        want = max(_pv_fps) if _pv_fps else 1.0
        return 1.0 / max(0.2, min(PREVIEW_MAX_FPS, want))


def wait_preview(last_seq, timeout=1.0):
    """等到有比 last_seq 更新的畫面，回傳 (seq, jpeg_bytes, info)；逾時回 None。

    必須用 deadline 迴圈：工作結束時 _clear_preview() 會把 seq 往上加、jpeg 設成
    None，若只判斷一次就返回，呼叫端會拿到「立刻返回的 None」而變成忙迴圈。
    """
    deadline = time.time() + max(0.05, timeout)
    with _pv_cv:
        while _pv["jpeg"] is None or _pv["seq"] <= last_seq:
            remain = deadline - time.time()
            if remain <= 0:
                return None
            _pv_cv.wait(remain)
        return _pv["seq"], _pv["jpeg"], dict(_pv["info"])


def latest_preview():
    with _pv_cv:
        return (_pv["seq"], _pv["jpeg"], dict(_pv["info"])) if _pv["jpeg"] else None


def _publish_preview(jpeg, info):
    with _pv_cv:
        _pv["seq"] += 1
        _pv["jpeg"] = jpeg
        _pv["info"] = info
        _pv_cv.notify_all()


def _clear_preview():
    with _pv_cv:
        _pv["jpeg"] = None
        _pv["info"] = {}
        _pv["seq"] += 1
        _pv_cv.notify_all()


# overlay 用色（BGR）
_PV_COLORS = [(240, 176, 80), (60, 76, 235), (110, 200, 90),
              (60, 170, 240), (200, 110, 200), (200, 190, 70)]


def _ascii(s):
    """cv.putText 畫不出中日文，非 ASCII 一律換掉，避免整串變成問號。"""
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(s))


def _render_preview(cv, np, small, det, names, header, captured):
    """把推論影格畫上 overlay 並編成 JPEG。只有在有人觀看時才會被呼叫。"""
    img = small.copy()
    h, w = img.shape[:2]

    if det:
        for i in range(len(det["cls"])):
            pts = det["masks"][i]
            if pts is None or len(pts) < 3:
                continue
            kept = det["kept"][i]
            cls = int(det["cls"][i])
            col = _PV_COLORS[cls % len(_PV_COLORS)] if kept else (150, 150, 150)
            poly = np.asarray(pts, dtype=np.int32).reshape(-1, 1, 2)
            cv.polylines(img, [poly], True, col, 2 if kept else 1, cv.LINE_AA)
            if not kept:
                continue
            x, y = poly[:, 0, 0].min(), poly[:, 0, 1].min()
            tag = _ascii(f"#{det['ids'][i]} {names.get(cls, cls)} {det['conf'][i]:.2f}")
            (tw, th), _ = cv.getTextSize(tag, cv.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            ty = max(th + 4, int(y) - 4)
            cv.rectangle(img, (int(x), ty - th - 4), (int(x) + tw + 6, ty + 2), col, -1)
            cv.putText(img, tag, (int(x) + 3, ty - 1),
                       cv.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv.LINE_AA)

    cv.rectangle(img, (0, 0), (w, 22), (40, 40, 40), -1)
    cv.putText(img, _ascii(header), (6, 15),
               cv.FONT_HERSHEY_SIMPLEX, 0.44, (235, 235, 235), 1, cv.LINE_AA)

    if captured:
        cv.rectangle(img, (0, h - 24), (w, h), (60, 160, 60), -1)
        cv.putText(img, _ascii(f"CAPTURED -> {captured}"), (6, h - 7),
                   cv.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv.LINE_AA)
        cv.rectangle(img, (1, 1), (w - 2, h - 2), (60, 200, 60), 3)

    if w > PREVIEW_MAX_W:
        img = cv.resize(img, (PREVIEW_MAX_W, int(h * PREVIEW_MAX_W / w)),
                        interpolation=cv.INTER_AREA)

    ok, buf = cv.imencode(".jpg", img, [int(cv.IMWRITE_JPEG_QUALITY), PREVIEW_QUALITY])
    return buf.tobytes() if ok else None


def stop_job():
    """要求中止；已寫入的影像與標記會保留。立即返回。"""
    if not _state["running"]:
        return {"ok": True, "running": False, "message": "目前沒有進行中的工作"}
    _stop_flag.set()
    _log("收到中止要求…")
    return {"ok": True, "running": True, "message": "已送出中止要求"}


# ══════════════════════════════════════════════════════════════
# 檔案 / 資料夾
# ══════════════════════════════════════════════════════════════

def list_videos(video_dir=DEFAULT_VIDEO_DIR):
    """列出資料夾內所有影片檔（依檔名自然排序）。"""
    d = Path(str(video_dir)).expanduser()
    if not d.is_dir():
        raise ValueError(f"影片資料夾不存在：{d}")
    files = [f for f in d.iterdir()
             if f.is_file() and f.suffix.lower() in VIDEO_EXTS]
    files.sort(key=lambda f: _natural_key(f.name))
    return [{"name": f.name,
             "path": str(f),
             "sizeMB": round(f.stat().st_size / 1048576, 1)} for f in files]


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


def _next_index(img_dir):
    """掃描既有檔名，回傳下一個可用的數字（1.jpg…120.jpg → 121）。"""
    mx = 0
    if img_dir.is_dir():
        for f in img_dir.iterdir():
            stem = f.stem
            if f.is_file() and stem.isdigit():
                mx = max(mx, int(stem))
    return mx + 1


def _write_yaml(ds_dir, names, split):
    """產生 / 更新 data.yaml（沿用 ATD3 的欄位形式）。"""
    lines = [f"path: {ds_dir}"]
    for key in ("train", "val", "test"):
        lines.append(f"{key}: images/{key}")
    lines.append(f"nc: {len(names)}")
    lines.append("names:")
    lines += [f"  {i}: {n}" for i, n in enumerate(names)]
    p = ds_dir / "data.yaml"
    if p.exists():                       # 已存在就不覆蓋使用者可能改過的內容
        return p
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return p


def _write_label(path, items, w, h):
    """items = [(cls, [[x,y],…])]，座標為原始影像 pixel。輸出 TAB 分隔、LF 換行。"""
    lines = []
    for cls, pts in items:
        if len(pts) < 3:
            continue
        vals = []
        for x, y in pts:
            vals.append(min(1.0, max(0.0, x / w)))
            vals.append(min(1.0, max(0.0, y / h)))
        lines.append("\t".join([str(int(cls))] + [f"{v:.6f}" for v in vals]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(("\n".join(lines) + "\n") if lines else "")
    return len(lines)


# ══════════════════════════════════════════════════════════════
# 轉換主流程
# ══════════════════════════════════════════════════════════════

def start_job(video_dir=DEFAULT_VIDEO_DIR, out_dir=DEFAULT_OUT_DIR,
              model_path=DEFAULT_MODEL, **opts):
    """啟動背景轉換工作，立即返回。重複呼叫會被拒絕。"""
    global _thread
    with _lock:
        if _state["running"]:
            return {"ok": False, "error": "已有進行中的轉換工作"}

        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in opts.items() if v is not None})
        cfg["videoDir"] = str(video_dir)
        cfg["outDir"] = str(out_dir)
        cfg["modelPath"] = str(model_path or DEFAULT_MODEL)

        _stop_flag.clear()
        _state.update({
            "running": True, "done": False, "error": "", "phase": "loading",
            "videoDir": cfg["videoDir"], "outDir": cfg["outDir"], "datasetDir": "",
            "videos": [], "videoIndex": 0, "videoCount": 0, "currentVideo": "",
            "framesDone": 0, "framesTotal": 0, "captured": 0,
            "firstIndex": 0, "lastIndex": 0, "classes": [],
            "startedAt": time.time(), "elapsed": 0.0, "log": [],
        })

    _thread = threading.Thread(target=_run, args=(cfg,), daemon=True,
                               name="videoDataset")
    _thread.start()
    return {"ok": True, "running": True}


def _run(cfg):
    try:
        _convert(cfg)
    except Exception as e:                                   # noqa: BLE001
        _log(f"[ERROR] {e}")
        _log(traceback.format_exc())
        _set(error=str(e), phase="error")
    finally:
        with _lock:
            _state["running"] = False
            _state["done"] = True
            _state["elapsed"] = round(time.time() - _state["startedAt"], 1)
            if _state["phase"] not in ("error", "stopped"):
                _state["phase"] = "finished"


def _convert(cfg):
    import cv2 as cv
    import numpy as np

    _log("載入 ultralytics / torch…")
    import torch
    import yoloSegByteTrack as seg          # 沿用同一套前處理與過濾邏輯
    from ultralytics import YOLO

    videos = list_videos(cfg["videoDir"])
    if not videos:
        raise ValueError(f"{cfg['videoDir']} 內找不到影片（{'/'.join(VIDEO_EXTS)}）")

    model_path = cfg["modelPath"]
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"找不到模型檔：{model_path}")

    # ── 輸出資料夾（結構與 ATD3 相同）──────────────
    out_root = Path(cfg["outDir"]).expanduser()
    ds_dir = out_root / "dataset" if out_root.name.lower() != "dataset" else out_root
    img_dir = ds_dir / "images" / cfg["split"]
    lbl_dir = ds_dir / "labels" / cfg["split"]
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    idx = _next_index(img_dir)
    first_idx = idx
    _set(datasetDir=str(ds_dir), firstIndex=idx,
         videos=[{"name": v["name"], "frames": 0, "processed": 0, "captured": 0}
                 for v in videos],
         videoCount=len(videos))
    _log(f"輸出：{ds_dir}（自 {idx}.jpg 起續編）")

    # ── 模型 ────────────────────────────────────
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    half = (device != "cpu")
    if device != "cpu":
        torch.backends.cudnn.benchmark = False

    _log(f"載入模型 {model_path}（device={device}）")
    model = YOLO(model_path, task="segment")
    model.to(device)
    names = seg._normalize_names(model.names)
    class_names = [names[k] for k in sorted(names)]
    _set(classes=class_names)
    _write_yaml(ds_dir, class_names, cfg["split"])
    _log(f"類別：{', '.join(class_names)}")

    track_kw = dict(
        persist=True,
        imgsz=int(cfg["imgsz"]),
        tracker=cfg["tracker"],
        conf=float(cfg["conf"]),
        max_det=int(cfg["maxDet"]),
        device=device,
        verbose=False,
        save=False,
        show=False,
        **seg._precision_kwargs(half),
    )

    # 先算總幀數，進度條才有分母
    total_frames = 0
    for i, v in enumerate(videos):
        cap = cv.VideoCapture(v["path"])
        n = int(cap.get(cv.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
        cap.release()
        n = max(0, n)
        total_frames += n
        v["frames"] = n                      # 本地清單也留一份，預覽標頭要用
        with _lock:
            _state["videos"][i]["frames"] = n
    _set(framesTotal=total_frames, phase="running")
    _log(f"共 {len(videos)} 部影片、約 {total_frames} 幀")

    prep = None
    frames_done = 0
    captured_total = 0
    last_pv = 0.0

    for vi, v in enumerate(videos):
        if _stop_flag.is_set():
            break
        _set(videoIndex=vi, currentVideo=v["name"])
        _log(f"▶ {v['name']}")

        cap = cv.VideoCapture(v["path"])
        if not cap.isOpened():
            _log(f"  無法開啟，略過：{v['name']}")
            continue

        # 每部影片重置 tracker，track id 不跨影片延用
        seg._g_model = model
        seg._reset_trackers()

        streak = {}          # track_id -> 連續出現幀數
        captured_ids = set()  # 已收錄過的 track_id（每部影片獨立）
        v_captured = 0
        v_processed = 0

        while True:
            if _stop_flag.is_set():
                _set(phase="stopped")
                _log("已中止")
                break

            ok, frame_bgr = cap.read()
            if not ok:
                break
            v_processed += 1
            frames_done += 1
            if frames_done % 15 == 0:
                _set(framesDone=frames_done)
                with _lock:
                    _state["videos"][vi]["processed"] = v_processed

            h, w = frame_bgr.shape[:2]
            if prep is None or prep.src_h != h or prep.src_w != w:
                prep = seg.FramePrep(h, w, 3, np.uint8, int(cfg["imgsz"]))
                _log(f"  來源 {w}x{h} → 推論 {prep.dst_w}x{prep.dst_h}")

            # 沒人看預覽就完全不做 overlay/編碼；有人看就依他要求的 fps 節流
            pv_interval = preview_interval()
            watching = pv_interval is not None
            small = prep(frame_bgr)
            r = model.track(small, **track_kw)[0]
            sx, sy = prep.inv_scale_x, prep.inv_scale_y

            # ── 解析這一幀 ────────────────────────
            # pv_det 供預覽用（含被過濾掉的物件，方便現場調 conf / 面積 / 邊界）
            pv_det = None
            keep = np.empty(0, dtype=np.int64)
            masks_xy = ids = clss = confs = None

            boxes = r.boxes
            det = boxes.data.cpu().numpy() if (boxes is not None and len(boxes)) else None
            is_track = det is not None and getattr(boxes, "is_track", det.shape[1] == 7)

            if det is not None and is_track:
                xyxy = det[:, :4]
                confs = det[:, -2]
                clss = det[:, -1].astype(np.int32)
                ids = det[:, -3].astype(np.int32)

                areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
                valid = (confs >= float(cfg["conf"])) & \
                        (areas >= float(cfg["minArea"]) / (sx * sy))

                masks_xy = r.masks.xy if r.masks is not None else None
                if masks_xy is None:
                    raise RuntimeError("模型沒有輸出 mask，請確認是分割模型（-seg）")

                if valid.any():
                    margin_y = float(cfg["edgeMargin"]) * prep.scale_y
                    vidx = np.flatnonzero(valid)
                    hit = seg._border_hit_mask([masks_xy[i] for i in vidx],
                                               prep.dst_h, margin_y)
                    valid[vidx[hit]] = False

                keep = np.flatnonzero(valid)
                if watching:
                    pv_det = {"cls": clss, "ids": ids, "conf": confs,
                              "kept": valid, "masks": masks_xy}

            # ── 連續幀計數 → 收錄 ─────────────────
            captured_name = ""
            if keep.size == 0:
                streak.clear()
            else:
                now_ids = ids[keep]
                streak = {int(i): streak.get(int(i), 0) + 1 for i in now_ids}
                trigger = [i for i in streak
                           if streak[i] >= CONSECUTIVE_FRAMES and i not in captured_ids]
                if trigger:
                    items = []
                    for i in keep:
                        poly, _c = seg._poly_and_centroid(
                            masks_xy[i], sx, sy, int(cfg["maxPolyPoints"]))
                        if len(poly) >= 3:
                            items.append((int(clss[i]), poly))
                    if items:
                        cv.imwrite(str(img_dir / f"{idx}.jpg"), frame_bgr,
                                   [int(cv.IMWRITE_JPEG_QUALITY), int(cfg["jpegQuality"])])
                        n_obj = _write_label(lbl_dir / f"{idx}.txt", items, w, h)

                        captured_ids.update(trigger)
                        captured_name = f"{idx}.jpg"
                        v_captured += 1
                        captured_total += 1
                        _log(f"  {idx}.jpg ← {v['name']} frame {v_processed}"
                             f"（新 ID {','.join(map(str, trigger))}，{n_obj} 個物件）")
                        idx += 1

                        _set(captured=captured_total, lastIndex=idx - 1)
                        with _lock:
                            _state["videos"][vi]["captured"] = v_captured

            # ── 即時預覽（有人在看才做；收錄的那一幀一定送）──
            now = time.time()
            if watching and (captured_name or now - last_pv >= pv_interval):
                last_pv = now
                jpeg = _render_preview(
                    cv, np, small, pv_det, names,
                    f"{v['name']}  frame {v_processed}/{v.get('frames') or '?'}"
                    f"  keep {keep.size}  captured {captured_total}",
                    captured_name)
                if jpeg:
                    _publish_preview(jpeg, {
                        "video": v["name"], "frame": v_processed,
                        "kept": int(keep.size), "captured": captured_total,
                        "savedAs": captured_name,
                    })

        cap.release()
        with _lock:
            _state["videos"][vi]["processed"] = v_processed
            _state["videos"][vi]["captured"] = v_captured
        _set(framesDone=frames_done)
        _log(f"  {v['name']} 完成：處理 {v_processed} 幀、收錄 {v_captured} 張")

    # 標記檔異動 → 清掉 ultralytics 的掃描快取
    for c in (ds_dir / "labels").glob("*.cache"):
        try:
            c.unlink()
        except OSError:
            pass

    _set(captured=captured_total, framesDone=frames_done,
         firstIndex=first_idx, lastIndex=idx - 1)
    _clear_preview()                       # 讓還連著的預覽串流收尾
    _log(f"完成：共收錄 {captured_total} 張影像 → {ds_dir}")


# ══════════════════════════════════════════════════════════════
# 命令列
# ══════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description="影片 → YOLO 分割資料集")
    ap.add_argument("--videos", default=DEFAULT_VIDEO_DIR, help="影片資料夾")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR, help="輸出資料夾")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="分割模型 .pt")
    ap.add_argument("--conf", type=float, default=DEFAULTS["conf"])
    ap.add_argument("--imgsz", type=int, default=DEFAULTS["imgsz"])
    ap.add_argument("--min-area", type=int, default=DEFAULTS["minArea"])
    ap.add_argument("--edge-margin", type=int, default=DEFAULTS["edgeMargin"])
    ap.add_argument("--split", default=DEFAULTS["split"], help="train / val")
    args = ap.parse_args()

    start_job(args.videos, args.out, args.model,
              conf=args.conf, imgsz=args.imgsz, minArea=args.min_area,
              edgeMargin=args.edge_margin, split=args.split)

    shown = 0
    while True:
        with _lock:
            new = _state["log"][shown:]
            shown = len(_state["log"])
            running = _state["running"]
        for line in new:
            print(line)
        if not running:
            break
        time.sleep(0.5)
    st = get_status()
    print(json.dumps({k: st[k] for k in
                      ("phase", "captured", "framesDone", "datasetDir", "error")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
