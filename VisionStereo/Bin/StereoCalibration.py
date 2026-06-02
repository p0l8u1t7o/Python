import numpy as np
import cv2
import glob
import os
import json
import time


# =====================================================================================================================
def run_stereo_calibration(img_folder_left,img_folder_right,save_path,board_size=(9, 6),square_size=25.0,show_preview=True):

    """
    1. 5MP 高解析度
    2. findChessboardCornersSB
    3. 自動進度顯示
    4. RMS 顯示
    5. 影像成功/失敗統計
    6. LabVIEW 可直接呼叫
    7. JSON 輸出
    """

    t_start = time.time()

    print("==========================================")
    print("Stereo Calibration Start")
    print("==========================================")

    # =============================================================================================================
    # 建立 3D 棋盤格座標
    # =============================================================================================================

    objp = np.zeros((board_size[0] * board_size[1], 3), np.float32)

    objp[:, :2] = np.mgrid[
        0:board_size[0],
        0:board_size[1]
    ].T.reshape(-1, 2)

    objp *= square_size

    objpoints = []
    imgpoints_l = []
    imgpoints_r = []

    # =============================================================================================================
    # 支援多種副檔名
    # =============================================================================================================

    exts = ['*.bmp', '*.jpg', '*.png', '*.jpeg', '*.BMP', '*.JPG']

    images_l = []
    images_r = []

    for ext in exts:
        images_l.extend(glob.glob(os.path.join(img_folder_left, ext)))
        images_r.extend(glob.glob(os.path.join(img_folder_right, ext)))

    images_l = sorted(images_l)
    images_r = sorted(images_r)

    total_images = min(len(images_l), len(images_r))

    print(f"Left Images : {len(images_l)}")
    print(f"Right Images: {len(images_r)}")

    # =============================================================================================================
    # 防呆檢查
    # =============================================================================================================

    if total_images == 0:
        print("錯誤：找不到影像")
        return False

    if len(images_l) != len(images_r):
        print("錯誤：左右影像數量不一致")
        return False

    # =============================================================================================================
    # Subpixel Criteria
    # =============================================================================================================

    subpix_criteria = (
        cv2.TERM_CRITERIA_EPS +
        cv2.TERM_CRITERIA_MAX_ITER,
        100,
        0.0001
    )

    success_count = 0
    fail_count = 0

    img_size = None

    # =============================================================================================================
    # 逐張處理
    # =============================================================================================================

    for idx, (fname_l, fname_r) in enumerate(zip(images_l, images_r)):

        progress = ((idx + 1) / total_images) * 100

        print(f"\n[{idx+1}/{total_images}] Progress: {progress:.1f}%")

        print(f"L : {os.path.basename(fname_l)}")
        print(f"R : {os.path.basename(fname_r)}")

        # =============================================================================================
        # 讀圖
        # =============================================================================================

        img_l = cv2.imread(fname_l, cv2.IMREAD_GRAYSCALE)
        img_r = cv2.imread(fname_r, cv2.IMREAD_GRAYSCALE)

        if img_l is None or img_r is None:
            print("影像讀取失敗")
            fail_count += 1
            continue

        img_size = img_l.shape[::-1]

        # =============================================================================================
        # 對比增強
        # =============================================================================================

        img_l = cv2.equalizeHist(img_l)
        img_r = cv2.equalizeHist(img_r)

        # =============================================================================================
        # 5MP 建議縮圖找角點
        # 提高速度與穩定性
        # =============================================================================================

        scale = 0.5

        small_l = cv2.resize(img_l,None,fx=scale,fy=scale)

        small_r = cv2.resize(img_r,None,fx=scale,fy=scale)

        # =============================================================================================
        # 新版 SB Corner Detection
        # =============================================================================================

        ret_l, corners_l = cv2.findChessboardCornersSB(
            small_l,
            board_size,
            flags=cv2.CALIB_CB_EXHAUSTIVE +
                  cv2.CALIB_CB_ACCURACY
        )

        ret_r, corners_r = cv2.findChessboardCornersSB(
            small_r,
            board_size,
            flags=cv2.CALIB_CB_EXHAUSTIVE +
                  cv2.CALIB_CB_ACCURACY
        )

        print(f"Corner Left : {ret_l}")
        print(f"Corner Right: {ret_r}")

        # =============================================================================================
        # 成功找到角點
        # =============================================================================================

        if ret_l and ret_r:

            # 放大回原解析度
            corners_l /= scale
            corners_r /= scale

            # Subpixel
            cv2.cornerSubPix(
                img_l,
                corners_l,
                (11, 11),
                (-1, -1),
                subpix_criteria
            )

            cv2.cornerSubPix(
                img_r,
                corners_r,
                (11, 11),
                (-1, -1),
                subpix_criteria
            )

            objpoints.append(objp)

            imgpoints_l.append(corners_l)
            imgpoints_r.append(corners_r)

            success_count += 1

            print("SUCCESS")

            # =====================================================================================
            # 顯示預覽
            # =====================================================================================

            if show_preview:

                disp_l = cv2.cvtColor(img_l, cv2.COLOR_GRAY2BGR)
                disp_r = cv2.cvtColor(img_r, cv2.COLOR_GRAY2BGR)

                cv2.drawChessboardCorners(
                    disp_l,
                    board_size,
                    corners_l,
                    ret_l
                )

                cv2.drawChessboardCorners(
                    disp_r,
                    board_size,
                    corners_r,
                    ret_r
                )

                merge = np.hstack([
                    cv2.resize(disp_l, (960, 540)),
                    cv2.resize(disp_r, (960, 540))
                ])

                cv2.imshow("Stereo Calibration", merge)

                key = cv2.waitKey(1)

                if key == 27:
                    print("使用者中止")
                    cv2.destroyAllWindows()
                    return False

        else:

            fail_count += 1
            print("FAILED")

    # =============================================================================================================
    # 結束預覽
    # =============================================================================================================

    cv2.destroyAllWindows()

    print("\n==========================================")
    print("Detection Result")
    print("==========================================")
    print(f"Success : {success_count}")
    print(f"Fail    : {fail_count}")

    # =============================================================================================================
    # 防呆
    # =============================================================================================================

    if success_count < 5:
        print("錯誤：成功圖片過少")
        return False

    # =============================================================================================================
    # Camera Calibration
    # =============================================================================================================

    print("\n==========================================")
    print("Single Camera Calibration")
    print("==========================================")

    w, h = img_size

    ret_l, M1, D1, _, _ = cv2.calibrateCamera(
        objpoints,
        imgpoints_l,
        (w, h),
        None,
        None
    )

    ret_r, M2, D2, _, _ = cv2.calibrateCamera(
        objpoints,
        imgpoints_r,
        (w, h),
        None,
        None
    )

    print(f"Left RMS : {ret_l}")
    print(f"Right RMS: {ret_r}")

    # =============================================================================================================
    # Stereo Calibration
    # =============================================================================================================

    print("\n==========================================")
    print("Stereo Calibration")
    print("==========================================")

    stereo_criteria = (
        cv2.TERM_CRITERIA_MAX_ITER +
        cv2.TERM_CRITERIA_EPS,
        100,
        1e-5
    )

    flags = (
        cv2.CALIB_FIX_INTRINSIC
    )

    ret_s, M1, D1, M2, D2, R, T, E, F = cv2.stereoCalibrate(
        objpoints,
        imgpoints_l,
        imgpoints_r,
        M1,
        D1,
        M2,
        D2,
        (w, h),
        criteria=stereo_criteria,
        flags=flags
    )

    print(f"Stereo RMS Error: {ret_s}")

    # =============================================================================================================
    # Stereo Rectify
    # =============================================================================================================

    R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
        M1,
        D1,
        M2,
        D2,
        (w, h),
        R,
        T,
        alpha=0
    )

    # =============================================================================================================
    # Rectification Map
    # =============================================================================================================

    mapL_x, mapL_y = cv2.initUndistortRectifyMap(
        M1,
        D1,
        R1,
        P1,
        (w, h),
        cv2.CV_32FC1
    )

    mapR_x, mapR_y = cv2.initUndistortRectifyMap(
        M2,
        D2,
        R2,
        P2,
        (w, h),
        cv2.CV_32FC1
    )

    # =============================================================================================================
    # 儲存 JSON
    # =============================================================================================================

    calib_data = {

        "RMS_Error": float(ret_s),

        "M1": M1.tolist(),
        "D1": D1.tolist(),

        "M2": M2.tolist(),
        "D2": D2.tolist(),

        "R": R.tolist(),
        "T": T.tolist(),

        "E": E.tolist(),
        "F": F.tolist(),

        "R1": R1.tolist(),
        "R2": R2.tolist(),

        "P1": P1.tolist(),
        "P2": P2.tolist(),

        "Q": Q.tolist(),

        "width": w,
        "height": h,

        "mapL_x_shape": mapL_x.shape,
        "mapL_y_shape": mapL_y.shape,

        "mapR_x_shape": mapR_x.shape,
        "mapR_y_shape": mapR_y.shape,

        "board_size": board_size,
        "square_size": square_size,

        "success_count": success_count,
        "fail_count": fail_count
    }

    with open(save_path, 'w') as f:
        json.dump(calib_data, f, indent=4)

    # =============================================================================================================
    # 完成
    # =============================================================================================================

    t_end = time.time()

    print("\n==========================================")
    print("Calibration Complete")
    print("==========================================")

    print(f"Stereo RMS Error : {ret_s:.6f}")

    print(f"Baseline X(mm)   : {abs(T[0][0]):.3f}")

    print(f"Total Time       : {t_end - t_start:.2f} sec")

    print(f"Save To          : {save_path}")

    print("==========================================")

    return True


# =====================================================================================================================
# Main
# =====================================================================================================================

if __name__ == "__main__":

    PATH_L = r'D:\CaptureVideo\Image\Left'

    PATH_R = r'D:\CaptureVideo\Image\Right'

    SAVE_TO = r'D:\CaptureVideo\Image\stereo_config.json'

    run_stereo_calibration(
        PATH_L,
        PATH_R,
        SAVE_TO,
        board_size=(9, 6),
        square_size=27.0,
        show_preview=True
    )