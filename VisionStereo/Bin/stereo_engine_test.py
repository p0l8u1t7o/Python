from engine import StereoEngine
import cv2
import os
import time

def main():
    # 設定路徑
    CONFIG_PATH = r"D:\Working Space\Python\VisionStereo\stereo_config.json"
    L_IMG = r"D:\Working Space\Python\VisionStereo\Left(Test)\L-42.bmp"
    R_IMG = r"D:\Working Space\Python\VisionStereo\Right(Test)\R-42.bmp"

    if not os.path.exists(L_IMG):
        print("測試影像不存在")
        return

    # 1. 實體化引擎 (一次性)
    print("--- 正在初始化 StereoEngine (已開啟 0.5x 縮放優化) ---")
    # 極速優化參數：鎖定 288 ~ 640px 區間，且長寬縮小一半
    engine = StereoEngine(
        config_path=CONFIG_PATH,
        min_disparity=288,
        num_disparities=352,
        block_size=15,
        preprocess_mode="NORMAL",
        use_wls=True,
        scale=0.125 # 0.5 倍縮放，運算量變 1/8
    )
    print("✓ 引擎初始化完成\n")

    # 2. 模擬連續處理影像與動態 BBox
    img_l = cv2.imread(L_IMG)
    img_r = cv2.imread(R_IMG)
    H, W = img_l.shape[:2]

    # 模擬變動的 BBox 列表
    test_scenarios = [
        [
            (1500, 300, 500, 1000),
         ]
    ]

    for i, bboxes in enumerate(test_scenarios):
        print(f"=== 場景 {i+1}: 處理 {len(bboxes)} 個 BBox ===")

        t_start = time.time()
        # 啟動 debug 模式
        results = engine.compute_bboxes_depth(img_l, img_r, bboxes, debug=False)
        t_end = time.time()

        for j, res in enumerate(results):
            print(f"  BBox {j}: Mean Depth = {res['mean']} mm")
            print(f"  BBox {j}: Median Depth = {res['median']} mm")
            print(f"  BBox {j}: Min Depth = {res['min']} mm")
            print(f"  BBox {j}: Max Depth = {res['max']} mm")

            # 如果有視覺化影像，顯示出來
            if "debug_viz" in res and res["debug_viz"] is not None:
                viz_small = cv2.resize(res["debug_viz"], (int(W*0.4), int(H*0.4)))
                cv2.imshow("Debug View", viz_small)
                print(f"  [DEBUG] 已顯示視覺化熱度圖，按任意鍵繼續...")
                cv2.waitKey(0)

        print(f"  處理耗時: {(t_end - t_start)*1000:.2f} ms\n")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
