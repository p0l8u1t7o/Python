import numpy as np
import torch
import joblib
import cv2
import torch.nn.functional as F

from model import PatchCoreModel
from utils import embedding_concat, reshape_embedding, imread_unicode

try:
    import faiss
except ImportError:
    faiss = None

# ======================
# 初始化（只會跑一次）
# ======================
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IMAGE_SIZE = 224
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

if DEVICE == "cuda":
    torch.backends.cudnn.benchmark = True

model = PatchCoreModel().to(DEVICE)
model.eval()

knn = joblib.load(r"D:\Working Space\Python\Patchcore\output\knn.pkl")
KNN_NEIGHBORS = getattr(knn, "n_neighbors", 3)


def _build_faiss_index():
    if faiss is None or not hasattr(knn, "_fit_X"):
        return None

    memory_bank = np.asarray(knn._fit_X, dtype=np.float32)
    memory_bank = np.ascontiguousarray(memory_bank)

    index = faiss.IndexFlatL2(memory_bank.shape[1])
    index.add(memory_bank)
    return index


try:
    faiss_index = _build_faiss_index()
except Exception:
    faiss_index = None

# ======================
# 前處理
# ======================
def preprocess(img):
    img = cv2.resize(img, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_AREA)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)

    img = (img / 255.0 - MEAN) / STD
    img = np.transpose(img, (2, 0, 1))

    return torch.from_numpy(np.ascontiguousarray(img)).unsqueeze(0)


def _kneighbors(feat):
    if faiss_index is not None:
        distances, _ = faiss_index.search(feat, KNN_NEIGHBORS)
        return np.sqrt(distances, out=distances)

    distances, _ = knn.kneighbors(feat)
    return distances

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

    x = preprocess(img).to(DEVICE, non_blocking=True)
    if DEVICE == "cuda":
        x = x.contiguous(memory_format=torch.channels_last)

    # ======================
    # 特徵抽取
    # ======================
    with torch.inference_mode():
        f2, f3 = model(x)

    # ======================
    # PatchCore embedding
    # ======================
    emb = embedding_concat(f2, f3)
    B, C, H, W = emb.shape

    feat = reshape_embedding(emb)
    feat = F.normalize(feat, p=2, dim=1)
    feat = np.ascontiguousarray(feat.cpu().numpy(), dtype=np.float32)

    # ======================
    # KNN anomaly score
    # ======================
    distances = _kneighbors(feat)

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
