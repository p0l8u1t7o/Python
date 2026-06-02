import cv2
import numpy as np
import json
import os

def load_calibration_data(config_path, img_shape):
    """
    載入校正 JSON 並產生地圖、焦距與基線。
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Calibration file not found: {config_path}")
        
    with open(config_path, "r") as f:
        data = json.load(f)
        
    h, w = img_shape
    M1, D1 = np.array(data["M1"]), np.array(data["D1"])
    M2, D2 = np.array(data["M2"]), np.array(data["D2"])
    
    if "R1" in data:
        R1, R2, P1, P2, Q = np.array(data["R1"]), np.array(data["R2"]), \
                            np.array(data["P1"]), np.array(data["P2"]), np.array(data["Q"])
    else:
        # 動態計算 Rectify
        R, T = np.array(data["R"]), np.array(data["T"])
        if T.ndim == 1: T = T.reshape(3, 1)
        R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(M1, D1, M2, D2, (w, h), R, T)

    # 建立校正地圖
    map_l_x, map_l_y = cv2.initUndistortRectifyMap(M1, D1, R1, P1, (w, h), cv2.CV_32FC1)
    map_r_x, map_r_y = cv2.initUndistortRectifyMap(M2, D2, R2, P2, (w, h), cv2.CV_32FC1)
    
    # 物理參數
    focal_length = Q[2][3]
    baseline = 1.0 / abs(Q[3][2]) if abs(Q[3][2]) > 1e-6 else abs(P2[0][3] / P2[0][0])
    
    return {
        "map_l": (map_l_x, map_l_y),
        "map_r": (map_r_x, map_r_y),
        "f": focal_length,
        "b": baseline,
        "Q": Q
    }

def preprocess_image(img, mode="NORMAL"):
    """
    影像預處理：抑制反光或增強邊緣
    """
    if mode == "CLAHE":
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(img)
    elif mode == "SOBEL":
        gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        return cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    elif mode == "LAPLACIAN":
        lap = cv2.Laplacian(img, cv2.CV_32F, ksize=3)
        return cv2.normalize(np.abs(lap), None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    return img
