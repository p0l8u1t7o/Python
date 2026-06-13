from ultralytics import YOLO

# 載入原本的 PyTorch 模型
model = YOLO("yolov8s.pt")

# 執行轉檔（這會花幾分鐘，請耐心等待）
# 它會在同目錄下生成一個 yolov8s.engine 檔案
model.export(format="engine", half=True, device=0)
print("轉檔完成！已生成 yolov8s.engine")