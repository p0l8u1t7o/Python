import cv2
import numpy as np
import torch
import joblib
import matplotlib.pyplot as plt

from model import PatchCoreModel
from utils import embedding_concat, reshape_embedding, normalize

# ======================
# 基本設定
# ======================
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IMAGE_SIZE = 224

# ======================
# 可調參數（重點）
# ======================
THRESHOLD = 0.8   # ⭐ 異常閾值（0~1，越小越敏感）
ALPHA = 0.5       # heatmap 疊圖透明度

# ======================
# 載入模型
# ======================
model = PatchCoreModel().to(DEVICE)
model.eval()

knn = joblib.load("./output/knn.pkl")

# ======================
# 前處理
# ======================
def preprocess(img):
    """
    將影像轉成模型輸入格式：
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
# 推論主流程
# ======================
def infer(img_path):
    """
    PatchCore 推論流程：
    1. 特徵抽取
    2. KNN 距離計算
    3. 產生 anomaly score map
    4. 視覺化（heatmap + 異常區）
    """

    # ======================
    # 讀圖
    # ======================
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError("Image load failed")

    x = preprocess(img).to(DEVICE)

    # ======================
    # 特徵抽取（layer2 + layer3）
    # ======================
    with torch.no_grad():
        f2, f3 = model(x)

    # ======================
    # PatchCore embedding
    # ======================
    emb = embedding_concat(f2, f3)

    B, C, H, W = emb.shape

    # ======================
    # reshape → (N_patches, feature_dim)
    # ======================
    feat = reshape_embedding(emb).cpu().numpy()

    # ======================
    # 特徵正規化（重要）
    # ======================
    feat = normalize(feat)

    # ======================
    # KNN 距離（異常分數）
    # ======================
    distances, _ = knn.kneighbors(feat)

    # 每個 patch 的 anomaly score
    score_map = distances.mean(axis=1).reshape(H, W)

    # 整張圖最大值作為 global score
    score = score_map.max()

    # ======================
    # resize 回原圖大小
    # ======================
    score_map = cv2.resize(score_map, (img.shape[1], img.shape[0]))

    # normalize 到 0~1
    score_map = (score_map - score_map.min()) / (score_map.max() - score_map.min() + 1e-8)

    # ======================
    # ⭐ 異常區域 threshold（二值化）
    # ======================
    anomaly_mask = (score_map > THRESHOLD).astype(np.uint8) * 255

    # ======================
    # heatmap
    # ======================
    heatmap = (score_map * 255).astype(np.uint8)
    heatmap = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)

    # ======================
    # 疊圖
    # ======================
    overlay = cv2.addWeighted(img, 1 - ALPHA, heatmap, ALPHA, 0)

    # ======================
    # 畫出異常輪廓（更清楚）
    # ======================
    contours, _ = cv2.findContours(anomaly_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = img.copy()
    cv2.drawContours(result, contours, -1, (0, 0, 255), 2)  # 紅框標異常

    # ======================
    # 輸出資訊
    # ======================
    print(f"Anomaly score: {score:.4f}")
    print(f"Threshold: {THRESHOLD}")

    # ======================
    # 顯示
    # ======================
    plt.figure(figsize=(12, 4))

    plt.subplot(1, 3, 1)
    plt.title("Original")
    plt.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    plt.subplot(1, 3, 2)
    plt.title("Heatmap Overlay")
    plt.imshow(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))

    plt.subplot(1, 3, 3)
    plt.title("Anomaly (Thresholded)")
    plt.imshow(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))

    plt.suptitle(f"Score: {score:.4f} | TH={THRESHOLD}")
    plt.show()

    return score, anomaly_mask


# ======================
# 執行
# ======================
infer(r"D:\Working Space\Python\Patchcore\000.jpg")