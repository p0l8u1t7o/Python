import numpy as np
import torch
import torch.nn.functional as F
import cv2

def embedding_concat(x, y):
    y = F.interpolate(y, size=x.shape[-2:], mode='bilinear', align_corners=False)
    return torch.cat([x, y], dim=1)

def reshape_embedding(embedding):
    B, C, H, W = embedding.shape
    return embedding.reshape(B, C, -1).permute(0, 2, 1).reshape(-1, C)

def normalize(feat):
    return feat / np.linalg.norm(feat, axis=1, keepdims=True)


def imread_unicode(path):
    """
    支援中文路徑的 OpenCV 讀圖方式
    """
    img_array = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return img