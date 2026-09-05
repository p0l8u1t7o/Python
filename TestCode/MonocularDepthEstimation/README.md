# MonocularDepthEstimation：YOLO26 單眼深度估計 + 相機疊圖

依 <https://docs.ultralytics.com/tasks/depth> 實作：`YOLO("yolo26n-depth.pt")` 對每一幀推論，
`result.depth.data` 取得與畫面同大小的公尺深度圖，上色後與相機畫面混合顯示。

## 安裝

```
pip install ultralytics pygrabber flask
```

專案 `.venv` 已裝好。第一次執行會自動下載權重（`yolo26n-depth.pt`，需要網路）。

## GPU 推論環境

這台機器：NVIDIA RTX 5070 Ti Laptop（Blackwell sm_120），驅動 616.56（CUDA 13.4）。
`.venv` 已改裝 CUDA 12.8 版 torch／torchvision（Blackwell 需要 cu128 以上）：

```
pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchvision
python check_gpu.py          # 列出 GPU、CPU vs GPU（FP32/FP16）每幀時間
```

實測（yolo26n-depth，640，這台機器）：CPU 約 36 ms/幀，GPU FP32 約 7 ms/幀（150 fps），GPU FP16 約 6 ms/幀。
注意 pip 把 `2.14.0+cpu` 與 `+cu128` 視為同版本，`--upgrade` 不會換掉，要先 `pip uninstall -y torch torchvision` 再裝；
cu128 索引目前給的是 torch 2.11.0+cu128。FP16 要用 ultralytics 8.4 的 `quantize="fp16"`，舊的 `half=True` 每幀重轉、反而慢 8 倍（程式已處理）。

換到別台機器時：有 NVIDIA 卡就照上面裝（驅動要支援 CUDA 12.8，即 ≥ 570 版）；
沒有 NVIDIA 卡就 `pip install torch torchvision`（CPU 版）即可，UI 會自動只列出 CPU。
網頁 UI 偵測到 GPU 時預設就用 GPU，並預設開 FP16；命令列版用 `--device 0 --half`。

## 網頁 UI（建議）

```
cd MonocularDepthEstimation
python ui.py --port 8003
```

瀏覽器開 `http://127.0.0.1:8003/`：

- **相機**：自動列出這台電腦的相機（可重新掃描），選解析度（清單或自訂寬高），可左右鏡像。
- **推論**：選 CPU 或每一張 CUDA GPU（沒有 CUDA 的環境 GPU 選項會反灰並說明原因）、模型 n/s/m/l/x、推論尺寸。
- **顯示**：深度疊圖／只看深度／原始畫面，透明度、色彩表、深度範圍（自動或固定）都能在串流中即時調整。
- **距離**：滑鼠移到畫面上就顯示該點距離（公尺）與座標；點一下用全解析度深度圖精確查一次；狀態欄有畫面中心距離、最近／最遠、fps 與推論時間。
- **快照**：存疊圖 png、原圖 png、深度 npy 到 `captures/`。

畫面以 MJPEG 串流（`/stream`），距離查表用每 0.3 秒同步一次的縮小深度圖在瀏覽器端就地查，不會卡串流。
API：`/api/cameras`、`/api/options`、`/api/start`、`/api/stop`、`/api/settings`、`/api/status`、`/api/depth?x&y`、`/api/depth_map`、`/api/snapshot`。

## 命令列版

```
cd MonocularDepthEstimation
python depth_cam.py --list                      # 列出這台電腦的相機
python depth_cam.py                             # 互動選相機後開視窗
python depth_cam.py --camera 1 --alpha 0.6      # 指定相機與透明度
python depth_cam.py --model yolo26s-depth.pt --device 0 --half   # 用 GPU 與較大模型
python depth_cam.py --source photo.jpg          # 用圖片測試
python depth_cam.py --source clip.mp4 --no-window --frames 30 --save-dir out   # 無視窗批次存檔
```

### 相機偵測

`cameras.py` 先用 pygrabber（DirectShow）取得裝置名稱，順序與 OpenCV `CAP_DSHOW` 索引一致；
沒有 pygrabber 時改用 Windows PnP 名稱。每個索引都用 OpenCV 實際試開，列出解析度與 fps，
打不開的會標示。只有一台可用就直接用，多台則在終端輸入編號。

### 視窗按鍵

| 鍵 | 功能 |
|---|---|
| q / Esc | 離開 |
| s | 存目前畫面（疊圖 png + 深度 npy）到 `captures/` |
| + / − | 深度疊圖透明度 |
| c | 切換色彩表（inferno / turbo / jet / magma / viridis） |
| d | 疊圖 → 只看深度 → 原圖 輪替 |
| r | 深度範圍自動（每幀 2～98 百分位）/ 固定（`--dmin --dmax`）切換 |
| 空白鍵 | 暫停 |
| 滑鼠 | 顯示游標處深度（公尺） |

畫面左上顯示來源、fps、推論時間、色彩範圍、中心點深度與最小／最大深度。

## 注意

- 深度是模型估計的絕對深度（公尺），室內一般場景大致合理，但精度取決於模型與場景，不是量測儀器。
- 沒有 GPU 時用 `yolo26n-depth.pt` 在 CPU 上約幾到十幾 fps（依電腦而定）；有 NVIDIA GPU 加 `--device 0 --half`。
- 相機被其他程式占用或被 Windows 隱私設定關閉時會顯示「打不開」。
