import numpy as np
import cv2
import glob
import os
import json

def run_stereo_calibration(img_folder_left, img_folder_right, save_path, board_size=(9, 6), square_size=25.0):
    """
    執行雙目標定並儲存結果檔
    
    參數說明 (LabVIEW 傳入建議):
    - img_folder_left:  字串，左相機棋盤格照片資料夾路徑 (例: "C:/Calib/Left")
    - img_folder_right: 字串，右相機棋盤格照片資料夾路徑 (例: "C:/Calib/Right")
    - save_path:        字串，設定檔儲存路徑 (例: "C:/Config/stereo_params.json")
    - board_size:       元組 (Tuple)，棋盤格內角點數量 (橫向點數, 縱向點數)
    - square_size:      浮點數，棋盤格單個正方形的實際物理邊長 (單位: mm)
    """
    
    # 1. 初始化 3D 空間參考點 (Object Points)
    # 這些點代表棋盤格在真實世界的坐標系統 (Z=0)
    objp = np.zeros((board_size[0] * board_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:board_size[0], 0:board_size[1]].T.reshape(-1, 2)
    objp *= square_size

    objpoints = []    # 存放真實世界 3D 點
    imgpoints_l = []  # 存放左圖 2D 像素座標
    imgpoints_r = []  # 存放右圖 2D 像素座標

    # 取得資料夾內所有影像 (請確保左右影像檔名對應，例如 L01.jpg 對應 R01.jpg)
    images_l = sorted(glob.glob(os.path.join(img_folder_left, '*.jpg')))
    images_r = sorted(glob.glob(os.path.join(img_folder_right, '*.jpg')))

    if len(images_l) != len(images_r):
        print("錯誤：左右資料夾照片數量不一致！")
        return False

    # 設定尋找角點的優化準則 (迭代 100 次或達到 0.001 精度)
    subpix_criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)

    for fname_l, fname_r in zip(images_l, images_r):
        img_l = cv2.imread(fname_l, 0) # 以灰階讀取提高處理速度
        img_r = cv2.imread(fname_r, 0)
        
        # 尋找棋盤格內角點
        ret_l, corners_l = cv2.findChessboardCorners(img_l, board_size, None)
        ret_r, corners_r = cv2.findChessboardCorners(img_r, board_size, None)

        if ret_l and ret_r:
            objpoints.append(objp)
            
            # 5MP 關鍵：亞像素精確化 (Sub-pixel accuracy)
            # 這能讓角點位置精確到像素以下，對深度計算至關重要
            cv2.cornerSubPix(img_l, corners_l, (11, 11), (-1, -1), subpix_criteria)
            cv2.cornerSubPix(img_r, corners_r, (11, 11), (-1, -1), subpix_criteria)
            
            imgpoints_l.append(corners_l)
            imgpoints_r.append(corners_r)

    # 2. 相機內標定 (Intrinsic Calibration)
    # 取得焦距、主點、畸變係數
    h, w = img_l.shape[:2]
    ret_l, M1, D1, _, _ = cv2.calibrateCamera(objpoints, imgpoints_l, (w, h), None, None)
    ret_r, M2, D2, _, _ = cv2.calibrateCamera(objpoints, imgpoints_r, (w, h), None, None)

    # 3. 雙目標定 (Stereo Calibration)
    # 取得兩台相機的相對旋轉 (R) 與平移 (T)
    # 120mm Baseline 會體現在 T 向量中
    flags = cv2.CALIB_FIX_INTRINSIC 
    ret_s, M1, D1, M2, D2, R, T, E, F = cv2.stereoCalibrate(
        objpoints, imgpoints_l, imgpoints_r, M1, D1, M2, D2, (w, h), 
        criteria=subpix_criteria, flags=flags
    )

    # 4. 立體校正矩陣計算 (Stereo Rectification)
    # 計算如何旋轉影像使左右極線平行
    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(M1, D1, M2, D2, (w, h), R, T)

    # 5. 儲存校正數據為 JSON 設定檔 (供後續推論程式讀取)
    calib_data = {
        "RMS_Error": ret_s,        # 標定總誤差 (越小越好，應 < 0.5)
        "M1": M1.tolist(),         # 左相機內參
        "D1": D1.tolist(),         # 左相機畸變
        "M2": M2.tolist(),         # 右相機內參
        "D2": D2.tolist(),         # 右相機畸變
        "R": R.tolist(),           # 旋轉矩陣
        "T": T.tolist(),           # 平移向量 (Baseline 約為 T[0])
        "Q": Q.tolist(),           # 深度映射矩陣 (Disparity-to-Depth)
        "width": w,
        "height": h
    }

    with open(save_path, 'w') as f:
        json.dump(calib_data, f, indent=4)

    print(f"校正完成！RMS Error: {ret_s}")
    print(f"結果已儲存至: {save_path}")
    return True

# --- LabVIEW 直接呼叫此區塊 ---
if __name__ == "__main__":
    # 範例路徑 (請根據實際環境修改)
    PATH_L = r'C:\Images\Stereo_Calib\Left'
    PATH_R = r'C:\Images\Stereo_Calib\Right'
    SAVE_TO = r'C:\Images\Stereo_Calib\stereo_config.json'
    
    run_stereo_calibration(PATH_L, PATH_R, SAVE_TO, board_size=(11, 8), square_size=20.0)