"""
YOLO26 單眼深度估計 網頁 UI

    python ui.py [--port 8003]
    瀏覽器開 http://127.0.0.1:8003/

功能：
    - 選相機 (自動列出這台電腦的相機，可重新掃描)、選解析度 (清單或自訂)
    - 選推論裝置 (CPU / 每一張 CUDA GPU)、模型大小 (n/s/m/l/x)、推論尺寸
    - 即時 MJPEG 串流顯示深度疊圖，透明度 / 色彩表 / 檢視模式 / 深度範圍 可即時調整
    - 滑鼠移到畫面上顯示該點距離 (公尺)，另有畫面中心距離
    - 快照：存疊圖 png + 深度 npy 到 captures/

後端只有一條工作執行緒抓相機與推論；瀏覽器要距離時用最近一幀的深度圖 (縮小版每 0.3 秒同步一次) 就地查表。
"""
import argparse
import os
import sys
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cameras  # noqa: E402
from depth_cam import COLORMAPS, colorize, load_model, overlay, predict_depth  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESOLUTIONS = [(640, 480), (800, 600), (1280, 720), (1920, 1080)]
MODELS = ["yolo26n-depth.pt", "yolo26s-depth.pt", "yolo26m-depth.pt", "yolo26l-depth.pt", "yolo26x-depth.pt"]


def list_devices():
    """可用的推論裝置：CPU + 每張 CUDA GPU (+ Apple MPS)"""
    devs = [dict(id="cpu", name="CPU", available=True)]
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                devs.append(dict(id=str(i), name=f"GPU {i}: {torch.cuda.get_device_name(i)}", available=True))
        else:
            devs.append(dict(id="0", name="GPU (此環境沒有 CUDA：torch 為 CPU 版或沒有 NVIDIA 顯示卡)", available=False))
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            devs.append(dict(id="mps", name="Apple MPS", available=True))
    except Exception as e:  # noqa: BLE001
        devs.append(dict(id="0", name=f"GPU (torch 無法載入: {e})", available=False))
    return devs


class DepthWorker:
    """相機 + 推論 + 疊圖 的背景執行緒，保存最近一幀給串流與查表用"""

    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.thread = None
        self.running = False
        self.error = ""
        self.settings = dict(camera=0, width=640, height=480, device="cpu", model=MODELS[0], imgsz=640,
                             alpha=0.55, cmap="inferno", view="overlay", dmin=None, dmax=None, flip=False, half=False)
        self.jpeg = None
        self.depth = None
        self.frame_id = 0
        self.stats = dict(fps=0.0, infer_ms=0.0, width=0, height=0, lo=0.0, hi=0.0, center=0.0,
                          dmin=0.0, dmax=0.0, model="", device="", camera_name="", loading=False)
        self.last_raw = None
        self.last_overlay = None

    # ------------------------------------------------------------ 控制
    def start(self, **settings):
        self.stop()
        with self.lock:
            self.settings.update({k: v for k, v in settings.items() if v is not None})
            self.error = ""
            self.running = True
            self.stats["loading"] = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
            self.cond.notify_all()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        self.thread = None

    def update(self, **settings):
        with self.lock:
            for k, v in settings.items():
                if k in ("alpha", "cmap", "view", "dmin", "dmax", "flip"):
                    self.settings[k] = v

    # ------------------------------------------------------------ 主迴圈
    def _run(self):
        s = dict(self.settings)
        cap = None
        try:
            cams, _ = cameras.list_cameras(do_probe=False)
            name = next((c["name"] for c in cams if c["index"] == s["camera"]), f"Camera {s['camera']}")
            cap = cv2.VideoCapture(int(s["camera"]), cameras.BACKEND)
            if s.get("width"):
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(s["width"]))
            if s.get("height"):
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(s["height"]))
            if not cap.isOpened():
                raise RuntimeError(f"相機 #{s['camera']} 打不開 (被其他程式占用或隱私設定關閉)")
            device = None if s["device"] in ("cpu", "", None) else s["device"]
            model = load_model(os.path.join(BASE_DIR, s["model"]) if os.path.exists(os.path.join(BASE_DIR, s["model"])) else s["model"], None)
            with self.lock:
                self.stats.update(camera_name=name, model=s["model"],
                                  device=("cpu" if device is None else f"cuda:{device}" + (" FP16" if s.get("half") else " FP32")), loading=False)
            t_prev = time.time()
            fps = 0.0
            while True:
                with self.lock:
                    if not self.running:
                        break
                    cur = dict(self.settings)
                ok, frame = cap.read()
                if not ok or frame is None:
                    raise RuntimeError("讀不到相機畫面")
                if cur.get("flip"):
                    frame = cv2.flip(frame, 1)
                t0 = time.time()
                depth = predict_depth(model, frame, int(cur["imgsz"]), device, bool(cur.get("half")))
                infer_ms = (time.time() - t0) * 1000
                now = time.time()
                inst = 1.0 / max(now - t_prev, 1e-6)
                fps = 0.85 * fps + 0.15 * inst if fps else inst
                t_prev = now
                cmap = dict(COLORMAPS).get(cur["cmap"], cv2.COLORMAP_INFERNO)
                fixed = cur.get("dmin") is not None and cur.get("dmax") is not None
                color, lo, hi = colorize(depth, cmap, cur["dmin"] if fixed else None, cur["dmax"] if fixed else None)
                view = cur.get("view", "overlay")
                if view == "depth":
                    out = color
                elif view == "raw":
                    out = frame
                else:
                    out = overlay(frame, color, float(cur["alpha"]))
                h, w = out.shape[:2]
                cv2.drawMarker(out, (w // 2, h // 2), (255, 255, 255), cv2.MARKER_CROSS, 16, 1)
                ok_j, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
                with self.lock:
                    self.jpeg = buf.tobytes() if ok_j else self.jpeg
                    self.depth = depth
                    self.last_raw = frame
                    self.last_overlay = out
                    self.frame_id += 1
                    self.stats.update(fps=fps, infer_ms=infer_ms, width=w, height=h, lo=lo, hi=hi,
                                      center=float(depth[h // 2, w // 2]), dmin=float(np.nanmin(depth)), dmax=float(np.nanmax(depth)))
                    self.cond.notify_all()
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.error = str(e)
                self.running = False
                self.stats["loading"] = False
                self.cond.notify_all()
        finally:
            if cap is not None:
                cap.release()

    # ------------------------------------------------------------ 輸出
    def wait_frame(self, last_id, timeout=1.0):
        with self.lock:
            if self.frame_id == last_id:
                self.cond.wait(timeout)
            return self.jpeg, self.frame_id

    def depth_at(self, x, y):
        with self.lock:
            if self.depth is None:
                return None
            h, w = self.depth.shape
            if not (0 <= x < w and 0 <= y < h):
                return None
            return float(self.depth[int(y), int(x)])

    def depth_small(self, max_w=160):
        with self.lock:
            if self.depth is None:
                return None
            d = self.depth
        h, w = d.shape
        sw = min(max_w, w)
        sh = max(1, int(round(h * sw / w)))
        small = cv2.resize(d, (sw, sh), interpolation=cv2.INTER_AREA)
        return dict(w=w, h=h, sw=sw, sh=sh, data=[round(float(v), 3) for v in small.ravel()])

    def snapshot(self, out_dir):
        with self.lock:
            if self.last_overlay is None:
                return None
            ov, raw, depth = self.last_overlay.copy(), self.last_raw.copy(), self.depth.copy()
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.join(out_dir, time.strftime("depth_%Y%m%d_%H%M%S"))
        cv2.imwrite(stem + "_overlay.png", ov)
        cv2.imwrite(stem + "_raw.png", raw)
        np.save(stem + "_depth.npy", depth)
        return stem

    def status(self):
        with self.lock:
            return dict(running=self.running, error=self.error, settings=self.settings, **self.stats)


worker = DepthWorker()
app = Flask(__name__)
_cam_cache = dict(cams=None, source=None)


@app.route("/")
def index():
    return render_template("ui.html")


@app.route("/api/cameras")
def api_cameras():
    if request.args.get("refresh") == "1" or _cam_cache["cams"] is None:
        was_running = worker.status()["running"]
        if was_running:
            worker.stop()          # 試開相機時不能同時被工作執行緒占用
        cams, src = cameras.list_cameras()
        _cam_cache.update(cams=cams, source=src)
    return jsonify(cameras=_cam_cache["cams"], source=_cam_cache["source"])


@app.route("/api/options")
def api_options():
    return jsonify(devices=list_devices(), resolutions=[list(r) for r in RESOLUTIONS], models=MODELS,
                   cmaps=[c[0] for c in COLORMAPS])


@app.route("/api/start", methods=["POST"])
def api_start():
    b = request.get_json(silent=True) or {}
    try:
        settings = dict(camera=int(b.get("camera", 0)), width=int(b.get("width") or 0) or None, height=int(b.get("height") or 0) or None,
                        device=str(b.get("device", "cpu")), model=str(b.get("model", MODELS[0])), imgsz=int(b.get("imgsz", 640)),
                        alpha=float(b.get("alpha", 0.55)), cmap=str(b.get("cmap", "inferno")), view=str(b.get("view", "overlay")),
                        dmin=(float(b["dmin"]) if b.get("dmin") not in (None, "") else None),
                        dmax=(float(b["dmax"]) if b.get("dmax") not in (None, "") else None), flip=bool(b.get("flip", False)),
                        half=bool(b.get("half", False)) and str(b.get("device", "cpu")) != "cpu")
    except (TypeError, ValueError) as e:
        return jsonify(error=f"參數錯誤: {e}"), 400
    if settings["model"] not in MODELS and not os.path.exists(settings["model"]):
        return jsonify(error="未知的模型"), 400
    if settings["device"] != "cpu":
        avail = {d["id"]: d for d in list_devices()}
        if settings["device"] not in avail or not avail[settings["device"]]["available"]:
            return jsonify(error=f"裝置 {settings['device']} 不可用：{avail.get(settings['device'], {}).get('name', '不存在')}。"
                                 "請選 CPU，或安裝 CUDA 版 torch (見 README「GPU 推論環境」)"), 400
    worker.start(**settings)
    return jsonify(ok=True)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    worker.stop()
    return jsonify(ok=True)


@app.route("/api/settings", methods=["POST"])
def api_settings():
    b = request.get_json(silent=True) or {}
    upd = {}
    if "alpha" in b:
        upd["alpha"] = float(np.clip(float(b["alpha"]), 0, 1))
    if "cmap" in b:
        upd["cmap"] = str(b["cmap"])
    if "view" in b:
        upd["view"] = str(b["view"])
    if "flip" in b:
        upd["flip"] = bool(b["flip"])
    if "dmin" in b or "dmax" in b:
        upd["dmin"] = float(b["dmin"]) if b.get("dmin") not in (None, "") else None
        upd["dmax"] = float(b["dmax"]) if b.get("dmax") not in (None, "") else None
    worker.update(**upd)
    return jsonify(ok=True)


@app.route("/api/status")
def api_status():
    return jsonify(worker.status())


@app.route("/api/depth")
def api_depth():
    try:
        x, y = int(float(request.args.get("x", -1))), int(float(request.args.get("y", -1)))
    except ValueError:
        return jsonify(depth=None)
    return jsonify(depth=worker.depth_at(x, y))


@app.route("/api/depth_map")
def api_depth_map():
    d = worker.depth_small(int(request.args.get("w", 160)))
    return jsonify(d or {})


@app.route("/api/snapshot", methods=["POST"])
def api_snapshot():
    stem = worker.snapshot(os.path.join(BASE_DIR, "captures"))
    if not stem:
        return jsonify(error="還沒有畫面"), 400
    return jsonify(ok=True, overlay=stem + "_overlay.png", raw=stem + "_raw.png", depth=stem + "_depth.npy")


@app.route("/stream")
def stream():
    def gen():
        last = -1
        idle = 0
        while True:
            jpeg, fid = worker.wait_frame(last, timeout=1.0)
            if fid == last or jpeg is None:
                idle += 1
                if idle > 30 and not worker.status()["running"]:
                    break
                continue
            idle = 0
            last = fid
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="YOLO26 深度估計 網頁 UI")
    ap.add_argument("--port", type=int, default=8003)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"開啟 http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
