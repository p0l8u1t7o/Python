"""
檢查 GPU 推論環境，並用深度模型做 CPU vs GPU 的速度比較。

    python check_gpu.py [--model yolo26n-depth.pt] [--imgsz 640] [--n 20]
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26n-depth.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--n", type=int, default=20, help="每種裝置量幾幀 (另加 3 幀暖機)")
    args = ap.parse_args()

    import torch
    print(f"torch {torch.__version__}  CUDA build {torch.version.cuda}  cuDNN {torch.backends.cudnn.version()}")
    ok = torch.cuda.is_available()
    print(f"CUDA 可用: {ok}")
    if ok:
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            print(f"  GPU {i}: {p.name}  sm_{p.major}{p.minor}  {p.total_memory / 2**30:.1f} GB  支援架構 {torch.cuda.get_arch_list()}")
    else:
        print("  → 沒有 CUDA。安裝 CUDA 版 torch： pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision")

    from depth_cam import load_model, predict_depth
    frame = (np.random.rand(480, 640, 3) * 255).astype(np.uint8)
    devices = ["cpu"] + (["0"] if ok else [])
    for dev in devices:
        for half in ([False, True] if dev != "cpu" else [False]):
            model = load_model(args.model, None)
            for _ in range(3):
                predict_depth(model, frame, args.imgsz, dev, half)
            if dev != "cpu":
                torch.cuda.synchronize()
            t0 = time.time()
            for _ in range(args.n):
                d = predict_depth(model, frame, args.imgsz, dev, half)
            if dev != "cpu":
                torch.cuda.synchronize()
            ms = (time.time() - t0) / args.n * 1000
            print(f"  {args.model} imgsz {args.imgsz}  device {dev:<3} {'FP16' if half else 'FP32'}: {ms:6.1f} ms/幀  ({1000 / ms:5.1f} fps)  depth {d.min():.2f}~{d.max():.2f} m")
    if ok:
        print(f"GPU 記憶體使用 {torch.cuda.max_memory_allocated() / 2**20:.0f} MB")


if __name__ == "__main__":
    main()
