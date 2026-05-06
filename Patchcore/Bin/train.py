import torch
import cv2
import os
import numpy as np
import time
from tqdm import tqdm
from sklearn.neighbors import NearestNeighbors
import joblib

from model import PatchCoreModel
from utils import embedding_concat, reshape_embedding, normalize

# ======================
# 基本設定
# ======================
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"   # 自動選擇 GPU / CPU
IMAGE_SIZE = 224                                         # 輸入影像尺寸（ResNet標準）

DATASET = "./dataset/normal"                             # 正常樣本資料夾
SAVE_PATH = "./output/"                                  # 模型輸出資料夾

os.makedirs(SAVE_PATH, exist_ok=True)

# ======================
# 初始化模型（PatchCore backbone）
# ======================
model = PatchCoreModel().to(DEVICE)
model.eval()   # 設定為 inference 模式（不更新權重）

print(f"[INFO] Using device: {DEVICE}")

# ======================
# 前處理函式
# ======================
def preprocess(img):
    """
    將 OpenCV 影像轉成 ResNet 可用格式
    步驟：
    1. resize
    2. BGR → RGB
    3. normalize（ImageNet）
    4. HWC → CHW
    5. 加 batch 維度
    """
    img = cv2.resize(img, (IMAGE_SIZE, IMAGE_SIZE))
    img = img[:, :, ::-1] / 255.0

    img = (img - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    img = np.transpose(img, (2, 0, 1))

    return torch.tensor(img, dtype=torch.float32).unsqueeze(0)

# ======================
# 載入資料
# ======================
def load_images(folder):
    """
    讀取資料夾內所有圖片
    """
    imgs = []
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        img = cv2.imread(p)
        if img is not None:
            imgs.append(img)

    return imgs

# ======================
# 開始訓練（建立 Memory Bank）
# ======================
print("[INFO] Loading images...")
images = load_images(DATASET)
total_images = len(images)

print(f"[INFO] Total images: {total_images}")

memory_bank = []

start_time = time.time()

# tqdm 進度條
for idx, img in enumerate(tqdm(images, desc="Extracting features")):

    img_start_time = time.time()

    # ======================
    # 影像前處理
    # ======================
    x = preprocess(img).to(DEVICE)

    # ======================
    # 特徵抽取（ResNet layer2 + layer3）
    # ======================
    with torch.no_grad():
        f2, f3 = model(x)

    # ======================
    # PatchCore 特徵融合
    # ======================
    emb = embedding_concat(f2, f3)

    # ======================
    # 轉成 (N_patches, feature_dim)
    # ======================
    emb = reshape_embedding(emb).cpu().numpy()

    # ======================
    # 特徵正規化（非常重要）
    # ======================
    emb = normalize(emb)

    memory_bank.append(emb)

    # ======================
    # 額外訓練資訊（工業用監控）
    # ======================
    current_patches = emb.shape[0]
    total_patches = sum(m.shape[0] for m in memory_bank)

    elapsed = time.time() - start_time
    avg_time = elapsed / (idx + 1)
    remain_time = avg_time * (total_images - idx - 1)

    print(f"[Progress] {idx+1}/{total_images} | "
          f"Patches: {current_patches} | "
          f"Total: {total_patches} | "
          f"ETA: {remain_time:.1f}s")

# ======================
# 合併所有特徵
# ======================
memory_bank = np.concatenate(memory_bank, axis=0)

print("\n[INFO] Before coreset:", memory_bank.shape)

# ======================
# Coreset Sampling（降維減量）
# ======================
# 目的：減少記憶體與加速 KNN
ratio = 1
sample_size = int(len(memory_bank) * ratio)

print(f"[INFO] Coreset sampling: {sample_size} / {len(memory_bank)}")

idx = np.random.choice(len(memory_bank), sample_size, replace=False)
memory_bank = memory_bank[idx]

print("[INFO] After coreset:", memory_bank.shape)

# ======================
# 建立 KNN（異常檢測核心）
# ======================
print("[INFO] Training KNN...")

knn = NearestNeighbors(n_neighbors=3)
knn.fit(memory_bank)

# ======================
# 儲存模型
# ======================
print("[INFO] Saving model...")

np.save(os.path.join(SAVE_PATH, "memory_bank.npy"), memory_bank)
joblib.dump(knn, os.path.join(SAVE_PATH, "knn.pkl"))

# ======================
# 完成
# ======================
total_time = time.time() - start_time

print(f"\n[INFO] Training completed in {total_time:.2f} seconds")
print("[INFO] Model saved to:", SAVE_PATH)