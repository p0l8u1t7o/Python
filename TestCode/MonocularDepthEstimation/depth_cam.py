"""
單眼深度估計 (Ultralytics YOLO26 depth) + 相機即時疊圖

    python depth_cam.py --list                 # 列出相機
    python depth_cam.py                        # 互動選相機，開視窗即時顯示
    python depth_cam.py --camera 1 --alpha 0.6 # 指定相機
    python depth_cam.py --source photo.jpg     # 用圖片 / 影片檔測試
    python depth_cam.py --source photo.jpg --no-window --save-dir out   # 無視窗，存檔 (測試用)

視窗按鍵：
    q / Esc 離開      s 存目前畫面 (疊圖 png + 深度 npy)     space 暫停
    + / -  疊圖透明度  c 切換色彩表   d 只看深度圖 / 疊圖 / 原圖 輪替
    r 深度範圍：自動 (每幀 2~98 百分位) / 固定 (--dmin --dmax)   滑鼠移動顯示該點深度
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cameras  # noqa: E402

COLORMAPS = [("inferno", cv2.COLORMAP_INFERNO), ("turbo", cv2.COLORMAP_TURBO), ("jet", cv2.COLORMAP_JET),
             ("magma", cv2.COLORMAP_MAGMA), ("viridis", cv2.COLORMAP_VIRIDIS)]


def resolve_device(device):
    """'0' / 'cuda:0' / 'cpu' / None → 可用的裝置字串；要求 GPU 但沒有 CUDA 時退回 CPU 並提示"""
    if device in (None, "", "cpu"):
        return None
    import torch
    if not torch.cuda.is_available():
        print(f"[警告] 要求 device={device} 但此環境沒有 CUDA (torch {torch.__version__})，改用 CPU。"
              " 安裝 CUDA 版： pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision")
        return None
    return str(device)


def load_model(weights, device=None):
    from ultralytics import YOLO
    model = YOLO(weights)
    return model


def predict_depth(model, frame, imgsz, device, half):
    """回傳與 frame 同大小的 float32 深度圖 (公尺)"""
    kw = dict(imgsz=imgsz, verbose=False)
    if device:
        kw["device"] = device
    if half:
        kw["quantize"] = "fp16"    # ultralytics 8.4：舊的 half=True 路徑慢 8 倍 (每次重轉)，要用 quantize
    results = model.predict(frame, **kw)
    r = results[0]
    depth = r.depth.data
    if hasattr(depth, "cpu"):
        depth = depth.cpu().numpy()
    depth = np.asarray(depth, dtype=np.float32)
    if depth.ndim == 3:
        depth = depth[0]
    if depth.shape != frame.shape[:2]:
        depth = cv2.resize(depth, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR)
    return depth


def colorize(depth, cmap, dmin=None, dmax=None, near_bright=True):
    """深度 → 彩色圖。dmin/dmax 為 None 時用每幀 2~98 百分位；near_bright 讓近處是暖/亮色"""
    valid = np.isfinite(depth)
    if dmin is None or dmax is None:
        if valid.any():
            lo, hi = np.percentile(depth[valid], (2, 98))
        else:
            lo, hi = 0.0, 1.0
    else:
        lo, hi = dmin, dmax
    if hi - lo < 1e-6:
        hi = lo + 1e-6
    norm = np.clip((depth - lo) / (hi - lo), 0, 1)
    if near_bright:
        norm = 1.0 - norm
    u8 = (norm * 255).astype(np.uint8)
    color = cv2.applyColorMap(u8, cmap)
    color[~valid] = 0
    return color, float(lo), float(hi)


def overlay(frame, color, alpha):
    return cv2.addWeighted(frame, 1.0 - alpha, color, alpha, 0)


def draw_hud(img, lines, org=(10, 24)):
    x, y = org
    for ln in lines:
        cv2.putText(img, ln, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, ln, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        y += 22
    return img


def open_source(args):
    """回傳 (cap, 描述字串)"""
    if args.source:
        if os.path.isfile(args.source) and args.source.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "bmp", "tif", "tiff"):
            return None, f"image {os.path.basename(args.source)}"
        cap = cv2.VideoCapture(args.source)
        return cap, f"video {os.path.basename(args.source)}"
    index = args.camera
    cams, src = cameras.list_cameras()
    print(cameras.format_table(cams, src))
    if index is None:
        index = cameras.choose_camera(cams)
        if index is None:
            print("沒有可用的相機。可用 --source 指定圖片或影片檔測試。")
            sys.exit(1)
    name = next((c["name"] for c in cams if c["index"] == index), f"Camera {index}")
    cap = cv2.VideoCapture(index, cameras.BACKEND)
    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        print(f"相機 #{index} 打不開")
        sys.exit(1)
    return cap, f"camera #{index} {name}"


def main():
    ap = argparse.ArgumentParser(description="YOLO26 單眼深度估計 + 相機疊圖")
    ap.add_argument("--list", action="store_true", help="只列出相機")
    ap.add_argument("--camera", type=int, default=None, help="相機索引 (不給則互動選擇)")
    ap.add_argument("--source", default=None, help="改用圖片或影片檔")
    ap.add_argument("--model", default="yolo26n-depth.pt", help="權重 (n/s/m/l/x-depth.pt，第一次會自動下載)")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None, help="cpu / 0 (GPU)；預設自動")
    ap.add_argument("--half", action="store_true", help="GPU 用 FP16 (quantize=fp16)")
    ap.add_argument("--alpha", type=float, default=0.55, help="深度疊圖透明度 0~1")
    ap.add_argument("--cmap", default="inferno", choices=[c[0] for c in COLORMAPS])
    ap.add_argument("--dmin", type=float, default=None, help="固定深度範圍下限 (m)，與 --dmax 一起給")
    ap.add_argument("--dmax", type=float, default=None, help="固定深度範圍上限 (m)")
    ap.add_argument("--width", type=int, default=None, help="相機擷取寬")
    ap.add_argument("--height", type=int, default=None, help="相機擷取高")
    ap.add_argument("--flip", action="store_true", help="左右翻轉 (自拍鏡像)")
    ap.add_argument("--save-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures"))
    ap.add_argument("--no-window", action="store_true", help="不開視窗：跑 --frames 幀後把疊圖存到 --save-dir (測試 / 無螢幕環境)")
    ap.add_argument("--frames", type=int, default=1, help="--no-window 時要處理的幀數")
    args = ap.parse_args()

    if args.list:
        cams, src = cameras.list_cameras()
        print(cameras.format_table(cams, src))
        return

    cap, desc = open_source(args)
    print(f"來源: {desc}")
    args.device = resolve_device(args.device)
    if args.half and args.device is None:
        args.half = False
    print(f"載入模型 {args.model} … (device {args.device or 'cpu'}{' FP16' if args.half else ''})")
    model = load_model(args.model, args.device)
    cmap_idx = [c[0] for c in COLORMAPS].index(args.cmap)
    alpha = float(np.clip(args.alpha, 0, 1))
    fixed_range = args.dmin is not None and args.dmax is not None
    view = 0                # 0 疊圖, 1 只看深度, 2 原圖
    paused = False
    hover = [None]
    os.makedirs(args.save_dir, exist_ok=True)
    win = "YOLO26 Depth"
    if not args.no_window:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(win, lambda ev, x, y, flags, param: hover.__setitem__(0, (x, y)))

    still = cv2.imread(args.source) if cap is None else None
    if cap is None and still is None:
        print(f"讀不到圖片 {args.source}")
        sys.exit(1)

    t_prev = time.time()
    fps = 0.0
    n_done = 0
    frame = None
    depth = None
    while True:
        if not paused:
            if cap is None:
                frame = still.copy()
            else:
                ok, frame = cap.read()
                if not ok or frame is None:
                    if args.source:
                        print("影片結束")
                        break
                    print("讀不到相機畫面")
                    break
            if args.flip:
                frame = cv2.flip(frame, 1)
            t0 = time.time()
            depth = predict_depth(model, frame, args.imgsz, args.device, args.half)
            dt = time.time() - t0
            fps = 0.9 * fps + 0.1 * (1.0 / max(time.time() - t_prev, 1e-6)) if fps else 1.0 / max(time.time() - t_prev, 1e-6)
            t_prev = time.time()

        color, lo, hi = colorize(depth, COLORMAPS[cmap_idx][1],
                                 args.dmin if fixed_range else None, args.dmax if fixed_range else None)
        if view == 0:
            out = overlay(frame, color, alpha)
        elif view == 1:
            out = color.copy()
        else:
            out = frame.copy()
        h, w = out.shape[:2]
        cx, cy = w // 2, h // 2
        cv2.drawMarker(out, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 16, 1)
        lines = [f"{desc}  {w}x{h}  {fps:.1f} fps  infer {dt * 1000:.0f} ms",
                 f"model {os.path.basename(args.model)}  alpha {alpha:.2f}  cmap {COLORMAPS[cmap_idx][0]}  "
                 f"range {'fixed' if fixed_range else 'auto'} {lo:.2f}~{hi:.2f} m",
                 f"center depth {depth[cy, cx]:.2f} m   min {np.nanmin(depth):.2f}  max {np.nanmax(depth):.2f} m"]
        if hover[0] is not None:
            hx, hy = hover[0]
            if 0 <= hx < w and 0 <= hy < h:
                lines.append(f"cursor ({hx},{hy}) depth {depth[hy, hx]:.2f} m")
                cv2.circle(out, (hx, hy), 6, (0, 255, 255), 1)
        draw_hud(out, lines)

        if args.no_window:
            stem = os.path.join(args.save_dir, f"depth_{n_done:04d}")
            cv2.imwrite(stem + "_overlay.png", out)
            cv2.imwrite(stem + "_depth.png", color)
            np.save(stem + "_depth.npy", depth)
            print(f"saved {stem}_overlay.png  (infer {dt * 1000:.0f} ms, depth {lo:.2f}~{hi:.2f} m, center {depth[cy, cx]:.2f} m)")
            n_done += 1
            if n_done >= args.frames or cap is None:
                break
            continue

        cv2.imshow(win, out)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("s"):
            stem = os.path.join(args.save_dir, time.strftime("depth_%Y%m%d_%H%M%S"))
            cv2.imwrite(stem + "_overlay.png", out)
            np.save(stem + "_depth.npy", depth)
            print(f"saved {stem}_overlay.png / _depth.npy")
        elif key in (ord("+"), ord("=")):
            alpha = min(1.0, alpha + 0.05)
        elif key in (ord("-"), ord("_")):
            alpha = max(0.0, alpha - 0.05)
        elif key == ord("c"):
            cmap_idx = (cmap_idx + 1) % len(COLORMAPS)
        elif key == ord("d"):
            view = (view + 1) % 3
        elif key == ord("r"):
            if args.dmin is not None and args.dmax is not None:
                fixed_range = not fixed_range
            else:
                print("要固定範圍請用 --dmin --dmax 指定")
        elif key == ord(" "):
            paused = not paused

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
