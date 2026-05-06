import cv2
import numpy as np
import torch
import joblib

from model import PatchCoreModel
from utils import embedding_concat, reshape_embedding, normalize, imread_unicode

# ======================
# 初始化（只會跑一次）
# ======================
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IMAGE_SIZE = 224

model = PatchCoreModel().to(DEVICE)
model.eval()

knn = joblib.load(r"C:\Users\grown\Desktop\Patchcore\output\knn.pkl")

# ======================
# 前處理
# ======================
def preprocess(img):
    img = cv2.resize(img, (IMAGE_SIZE, IMAGE_SIZE))
    img = img[:, :, ::-1] / 255.0

    img = (img - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    img = np.transpose(img, (2, 0, 1))

    return torch.tensor(img, dtype=torch.float32).unsqueeze(0)

# ======================
# ⭐ LabVIEW 呼叫用函式
# ======================
def infer_image(img_path, threshold=0.8):
    """
    給 LabVIEW Python Node 使用

    Parameters:
        img_path (str)   : 影像路徑
        threshold (float): 異常判斷閾值 (0~1)

    Returns:
        score (float)        : 整張圖異常分數
        heatmap (uint8 2D)   : 異常熱力圖 (0~255)
        mask (uint8 2D)      : 二值異常區域 (0 or 255)
    """

    # ======================
    # 讀圖
    # ======================
    img = imread_unicode(img_path)
    if img is None:
        raise ValueError("Image load failed")

    x = preprocess(img).to(DEVICE)

    # ======================
    # 特徵抽取
    # ======================
    with torch.no_grad():
        f2, f3 = model(x)

    # ======================
    # PatchCore embedding
    # ======================
    emb = embedding_concat(f2, f3)
    B, C, H, W = emb.shape

    feat = reshape_embedding(emb).cpu().numpy()
    feat = normalize(feat)

    # ======================
    # KNN anomaly score
    # ======================
    distances, _ = knn.kneighbors(feat)

    score_map = distances.mean(axis=1).reshape(H, W)

    # global score
    score = float(score_map.max())

    # ======================
    # resize 回原圖
    # ======================
    score_map = cv2.resize(score_map, (img.shape[1], img.shape[0]))

    # normalize 0~1
    score_map = (score_map - score_map.min()) / (score_map.max() - score_map.min() + 1e-8)

    # ======================
    # heatmap (uint8)
    # ======================
    heatmap = (score_map * 255).astype(np.uint8)

    # ======================
    # threshold mask
    # ======================
    mask = (score_map > threshold).astype(np.uint8) * 255

    return score, heatmap, mask