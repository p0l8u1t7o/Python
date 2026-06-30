import cv2
import os

def video_to_images(video_path, output_folder, filename="frame_",img_format="jpg", step=1):
    """
    video_path: AVI 檔案路徑
    output_folder: 輸出圖片資料夾
    img_format: jpg / png
    step: 每幾幀存一次 (1=每張都存, 2=隔一張存)
    """

    # 建立資料夾
    os.makedirs(output_folder, exist_ok=True)

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print("❌ 無法開啟影片:", video_path)
        return

    frame_id = 0
    saved_id = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            break

        # 控制抽幀
        if frame_id % step == 0:
            finalfilename = os.path.join(
                output_folder,
                f"{filename}{saved_id:06d}.{img_format}"
            )

            cv2.imwrite(finalfilename, frame)
            saved_id += 1

        frame_id += 1

    cap.release()
    print(f"✅ 完成，共輸出 {saved_id} 張圖片")


# =========================
# 使用範例
# =========================
video_path = r"D:\CaptureImage\0\0.avi"
output_folder = r"D:\CaptureImage\0\Image"

video_to_images(video_path, output_folder, filename="frame_", img_format="jpg", step=1)