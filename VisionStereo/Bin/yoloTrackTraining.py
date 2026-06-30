"""
YOLO 實例分割 — 訓練 + 自動匯出版
直接修改下方 CONFIG，執行：python yolo_seg_train_export.py

安裝依賴：
    pip install ultralytics torch torchvision opencv-python pyyaml
"""

import sys
import shutil
import yaml
from pathlib import Path


# ╔══════════════════════════════════════════════════════════════╗
# ║                  ▼  請在這裡修改所有設定  ▼                  ║
# ╠══════════════════════════════════════════════════════════════╣

# ── 資料集 ──────────────────────────────────────────────────────
DATASET_DIR = r"D:\TrainingImage\CITD\dataset"           # 資料集根目錄（含 images/train, images/val）
CLASS_NAMES = ["Plastic", "HDPE", "Other"]        # 類別名稱（依標籤 id 順序）
DATA_YAML   = r"D:\TrainingImage\CITD\dataset\data.yaml"         # data.yaml 路徑（不存在時自動產生）

# ── 訓練參數 ─────────────────────────────────────────────────────
MODEL        = r"D:\Working Space\Python\VisionStereo\Bin\yolo11n-seg.pt"     # 預訓練權重（自動下載）
# 可選：yolo11n/s/m/l/x-seg.pt  或  yolov8n/s/m/l/x-seg.pt
EPOCHS       = 100
IMGSZ        = 640
BATCH        = 16
DEVICE       = "0"                  # "0"=GPU0 ; "cpu"=CPU ; "0,1"=多GPU
WORKERS      = 8
PATIENCE     = 50                   # Early stopping
LR0          = 1e-3
LRF          = 1e-2
AMP          = True                 # 混合精度（節省顯存）
CACHE        = False                # 快取至 RAM（需大記憶體）
RESUME       = False                # 繼續上次中斷的訓練
SAVE_PERIOD  = -1                   # -1 = 只存最佳; N = 每 N epoch 存一次
OVERLAP_MASK = True
MASK_RATIO   = 4
RETINA_MASKS = False
PROJECT      = r"D:\Working Space\Python\VisionStereo\weights"       # 訓練輸出根目錄
EXP_NAME     = "CITD"                # 實驗名稱

# ── 匯出設定 ─────────────────────────────────────────────────────
# 支援格式：onnx | torchscript | tflite | coreml | engine(TensorRT)
EXPORT_FORMAT  = "onnx"
EXPORT_HALF    = False              # FP16（TensorRT / CoreML 才有效）
EXPORT_DYNAMIC = False              # 動態 batch size（ONNX）

# ── 輸出路徑設定 ──────────────────────────────────────────────────
# 訓練完成後，以下檔案會被複製到 OUTPUT_DIR：
#   best.pt          → 最佳 PyTorch 權重
#   last.pt          → 最後一個 epoch 的權重
#   best.<format>    → 匯出格式（如 best.onnx）
OUTPUT_DIR       = r"D:\Working Space\Python\VisionStereo\weights"       # ← 修改為你想要的輸出資料夾
COPY_BEST_PT     = True             # 複製 best.pt
COPY_LAST_PT     = True             # 複製 last.pt
COPY_EXPORT_FILE = True             # 複製匯出檔（如 .onnx）

# ╚══════════════════════════════════════════════════════════════╝


# ───────────────────────────────────────────────
# 工具函式
# ───────────────────────────────────────────────

def print_banner(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ensure_data_yaml() -> str:
    """若 data.yaml 不存在則自動產生。"""
    p = Path(DATA_YAML)
    if p.exists():
        print(f"[INFO] 使用現有 data.yaml：{p.resolve()}")
        return str(p.resolve())

    data = {
        "path":  str(Path(DATASET_DIR).resolve()),
        "train": "images/train",
        "val":   "images/val",
        "test":  "images/test",
        "nc":    len(CLASS_NAMES),
        "names": CLASS_NAMES,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    print(f"[INFO] data.yaml 已自動產生：{p.resolve()}")
    return str(p.resolve())


def load_yolo(weights: str):
    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("[ERROR] 請先安裝 ultralytics：pip install ultralytics")
    return YOLO(weights)


def copy_file(src: Path, dst_dir: Path, label: str) -> None:
    """複製單一檔案到目標目錄，並印出結果。"""
    if not src.exists():
        print(f"[WARN] {label} 不存在，跳過：{src}")
        return
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    print(f"[COPY] {label:12s}  {src}  →  {dst}")


# ───────────────────────────────────────────────
# 主流程
# ───────────────────────────────────────────────

def main():
    # ── Step 1：確認 data.yaml ──────────────────
    data_yaml = ensure_data_yaml()

    # ── Step 2：訓練 ────────────────────────────
    print_banner("Step 1 / 3  —  YOLO 訓練")
    print(f"  模型    : {MODEL}")
    print(f"  資料    : {data_yaml}")
    print(f"  Epochs  : {EPOCHS}  |  imgsz : {IMGSZ}  |  batch : {BATCH}")
    print(f"  Device  : {DEVICE}  |  AMP   : {AMP}")
    print(f"  輸出    : {PROJECT}/{EXP_NAME}/")
    print()

    yolo = load_yolo(MODEL)
    train_results = yolo.train(
        data         = data_yaml,
        epochs       = EPOCHS,
        imgsz        = IMGSZ,
        batch        = BATCH,
        device       = DEVICE,
        project      = PROJECT,
        name         = EXP_NAME,
        workers      = WORKERS,
        patience     = PATIENCE,
        lr0          = LR0,
        lrf          = LRF,
        amp          = AMP,
        cache        = CACHE,
        resume       = RESUME,
        save_period  = SAVE_PERIOD,
        overlap_mask = OVERLAP_MASK,
        mask_ratio   = MASK_RATIO,
        retina_masks = RETINA_MASKS,
    )

    save_dir   = Path(train_results.save_dir)
    best_pt    = save_dir / "weights" / "best.pt"
    last_pt    = save_dir / "weights" / "last.pt"

    print(f"\n[INFO] 訓練完成")
    print(f"  最佳權重 : {best_pt}")
    print(f"  最後權重 : {last_pt}")

    # ── Step 3：匯出 ────────────────────────────
    print_banner(f"Step 2 / 3  —  匯出模型（{EXPORT_FORMAT.upper()}）")

    export_yolo = load_yolo(str(best_pt))
    exported_path = export_yolo.export(
        format  = EXPORT_FORMAT,
        imgsz   = IMGSZ,
        half    = EXPORT_HALF,
        dynamic = EXPORT_DYNAMIC,
    )
    exported_path = Path(exported_path)
    print(f"\n[INFO] 匯出完成：{exported_path}")

    # ── Step 4：複製到指定輸出目錄 ──────────────
    print_banner(f"Step 3 / 3  —  複製到輸出目錄")

    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  目標目錄 : {out_dir.resolve()}\n")

    if COPY_BEST_PT:
        copy_file(best_pt, out_dir, "best.pt")

    if COPY_LAST_PT:
        copy_file(last_pt, out_dir, "last.pt")

    if COPY_EXPORT_FILE:
        copy_file(exported_path, out_dir, exported_path.suffix.lstrip(".").upper())

    # ── 完成摘要 ────────────────────────────────
    print_banner("完成！")
    print(f"  輸出目錄 : {out_dir.resolve()}")
    for f in sorted(out_dir.iterdir()):
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"    {f.name:<30}  {size_mb:6.2f} MB")
    print()


if __name__ == "__main__":
    main()