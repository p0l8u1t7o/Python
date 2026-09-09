# 深度學習教導：在平台內標註、訓練與匯出

深度學習頁（`/dl`）帶您在**不離開平台**的情況下完成一輪教導：建立教導專案、收集樣本、標註、在伺服端訓練，最後將模型匯出為**資產**，可在任何流程的 DL 工具中選用。模型種類（trainer）是註冊表；新增 trainer 會重用同一介面，不需要前端變更。

## 1. 從使用者角度看教導流程 {#flow}

1. **建立教導專案**：輸入名稱、模型種類與類別，例如 `OK, NG`；之後仍可新增或移除。
2. **收集樣本**：使用「Upload images」多選上傳，也接受 zip；或用「Grab from source」選影像來源擷取 N 張，可預先標籤。所有上傳都以解碼後像素 SHA256 去重。
3. **標註分類**：Grid 適合大量縮圖快速標籤；Large 左側為縮圖牆、右側為全圖檢視器，含縮放與 1:1。
4. **訓練**：右側面板顯示由 trainer 宣告產生的超參數、裝置與模型資產名稱。進度與指標即時更新，訓練在背景執行，不佔用檢測執行緒池。
5. **保留或丟棄**：訓練完成不會自動寫入資產庫。**Save to Assets** 會儲存模型並更新專案最後模型，**Discard** 會刪除 pending 檔案。
6. **使用**：儲存模型後會出現在資產庫（kind=model）。在流程加入 DL 工具、選模型並貼上類別清單即可。

### Quick register {#quick-register}

**Quick register** 是 box 專案最短路徑：加入至少兩張影像、檢視建議框、命名資產，並從既有訓練面板開始。伺服端會把建議框存到尚未標註樣本、選保守 preset，然後啟動與一般路徑相同的訓練工作。工作完成並命名保留前，不會存到 Assets。

- 僅適用於至少一個類別、至少兩個樣本的 box 專案。
- preset 刻意小且短：size `n`、`epochs=20`、`batch=4`、`patience=8`、`lr0=0.001`、`val_ratio=0.2`、`workers=0`，無旋轉、翻轉或混圖。
- 回覆含 `job_id`、`labeled`、`skipped` 與 `params`，可檢視並重用設定。
- 錯誤狀態明確：缺樣本、類別或框為 `422`；已有訓練為 `409`；無 DL 權限為 `403`。

**圖庫中的深度學習範本**：「AI object count (stock model)」與「AI instance segmentation: sign area」使用 COCO stock model，不需訓練。「Classification: good / missing hole」與「Semantic segmentation: scratch area」使用 `seed_demo` 以內建 trainer 訓練的示範模型。見 [範例範本](samples.md)。

## 2. 自動標註 {#auto}

標註是起步最慢的部分，因此每個 trainer 可實作 `suggest()`，為尚未標註樣本提供建議類別與信心值。內建分類器使用**特徵空間 cosine kNN (k=3)**，每類有少量人工標註後即可即時回應，無需先訓練。

- 點選「Auto label」後，尚未標註縮圖會出現虛線建議，例如 `NG? 87%`；可全部接受或個別改標。
- 自動標註樣本記為 `labeled_by=auto`；人工重標後變成 `human`。
- 只有 `human` 標籤可作 kNN 參考，避免自動標籤自我強化。
- 網路 trainer 在已有訓練後用最後的 best.pt 建議；之前則用 stock model。
- shapes 專案的 whole-image proposal 使用 SAM2 產生最多 30 個區域，每次 20 張，提案附到第一類等待確認。
- Smart select 與 smart box 在標註編輯器中用 S/X 觸發 SAM2，權重首次使用時下載，缺依賴時會顯示安裝命令。

## 3. 伺服端資源與裝置設定 {#devices}

訓練與推論都使用**伺服端**資源。頁面頂端由 `GET /dl/devices` 顯示偵測到的加速器與 GPU：

| 欄位 | 內容 |
|---|---|
| `providers` | 此伺服端的 onnxruntime execution providers，例如 CPU、CUDA、DirectML、TensorRT |
| `gpus` | NVIDIA GPU 名稱、記憶體使用與使用率；只有 `nvidia-smi` 可用時有值 |
| `preferred_providers` / `train_device` | 目前選擇；由管理員以 `PATCH /dl/settings` 修改 |

- **推論**：`preferred_providers` 決定 dl_* 工具建立 ORT session 時使用的 providers；不可用項會過濾，CPU 永遠最後。變更會清除 session 快取並立即生效。
- **訓練**：裝置下拉列列出伺服端具備且 trainer 支援的裝置。內建 MLP 只需 CPU，數秒即可完成。

## 4. shapes 標註編輯器（分割與偵測） {#shapes}

`label_mode="shapes"` 的語意/實例分割與偵測模型使用**標註編輯器**。每張圖可有多個多邊形或框實例，各自帶類別。座標一律以 **0-1 正規化**儲存，只有畫布顯示時轉回像素。

- **編輯**：畫布左側是大型圖示工具列，包含 select、polygon、box、refine、delete、undo 與快捷鍵；上方狀態列顯示前後圖、樣本尺寸、標籤數、提示、未儲存狀態與 save。
- **多邊形逐點繪製且無點數限制**：N 或工具列進入模式，每次點選加頂點；雙擊、點選第一點或 Enter 關閉，Backspace 移除上一點，Esc 取消。
- **Smart select**：按 S 並點選物件，伺服端分割輪廓、簡化為多邊形並套用目前類別。
- **Smart box**：按 X 拖出框，SAM2 回傳框內物件輪廓。
- **Refine**：純前端 JavaScript 在灰階梯度圖上沿頂點法線尋邊，迭代、平滑並用 Douglas-Peucker 簡化，需手動儲存。
- **縮圖牆檢視**：縮圖繪出標註輪廓，可快速看出不良標註；自動提案以 `?` 標示。
- **自動標註**：shapes 模式的提案是一整組形狀，可單張或全部接受，接受後仍標為 auto 等待檢視。

## 5. 資料集管理（去重、分割、版本） {#dataset}

- **重複偵測**：每個樣本保存解碼後像素 SHA256，專案內上傳、zip、來源 burst 與資料夾匯入都會去重並回報 `duplicates`。
- **train/val/test 分割**：右側 Dataset 面板顯示各 split 數量。「Auto split」依比例分層隨機指派；工作區狀態列的 split chip 可在 train -> val -> test -> unset 間切換。
- **訓練如何使用**：標為 `val` 的樣本成為 validation；標為 `test` 的樣本永不進入訓練，保留為 blind check 並回報 `test_holdout`。
- **凍結版本**：「Freeze」把目前樣本、標籤與 split 匯出為 zip 到**資產庫（kind=dataset）**，含統計。版本可下載或刪除。

### 從影片建立樣本 {#video-extract}

擷取端可在本機記錄各 channel、上傳到 `DATA_DIR/videos/<client>/`，或在同機時直接寫入伺服端資料夾。DL 頁以 `GET /api/vision/videos` 列出檔案。

實例分割專案的「Create samples from video」面板會啟動背景擷取：錄影、上傳、擷取、在既有 shape editor 校正標籤、訓練，再於流程中選用新模型。擷取每 `stride` 張處理一張，執行目前分割模型、套 edge margin filter，再以私有狀態追蹤物件，因此不會改動流程變數。每條 track 首次 confirmed 儲存一張全圖樣本，之後每 `k` 張處理畫格再存一次，直到該 track 達到 `n` 張；預設 `n=3`、`k=5`。

## 6. 內建模型與 augmentation {#builtin}

| kind | 任務 / 標籤 | 方法 | 推論工具 | 依賴 |
|---|---|---|---|---|
| `mlp_classify` | 影像分類（classes） | numpy 訓練 MLP，手工匯出 ONNX，預處理與工具預設一致；含 learning-rate protection | dl_classify | 無 |
| `patch_segment` | 語意分割（shapes） | numpy patch classifier，匯出 fully convolutional ONNX，可接受任意輸入尺寸 | dl_segment | 無 |
| `retrieval` | 影像檢索分類 | 從標註影像建立自含參考庫，執行時由最近參考投票 | dl_retrieval | 內建 reference matcher |
| `ai_seg` | 實例分割 | 以資料庫樣本建立訓練資料集，回報 loss、mAP 與 log，輸出 best.pt 與 ONNX | **ai_segment** 或 dl_instance | 選用 DL 依賴 |
| `ai_detect` | 物件偵測 | 以框訓練 stock detection network，標註成本最低 | **ai_detect** 或 dl_detect | 選用 |
| `ai_cls` | 影像分類 | 寫成 classification dataset 後從 stock model 微調 | **ai_classify** 或 dl_classify | 選用 |
| `anomaly` | 異常偵測（只需良品） | ResNet18 backbone 產生 patch features，coreset 記憶庫保留良品特徵，閾值由良品 leave-one-out 分數推得 | dl_anomaly | backbone ONNX |
| `ai_obb` | 旋轉框 | 多邊形轉 minimum-area rotated rectangle 後訓練 oriented-box network | **ai_obb** | 選用 |

### 參考庫分類 {#retrieval-library}

retrieval 專案適合類別持續增加的產線。右側面板稱為 **Build library** 而非 train：它掃描已標註影像，每張原圖與選用光照變體保存一筆 reference，最後存成 `.npz` 資產。資產含類別清單、正規化 reference matrix、每列 label index、縮圖與 matcher bytes，可在站台間移動。

`dl_retrieval` 執行時把輸入 ROI 與庫比較，回傳 top matches，並由近鄰加權投票選 label。`min_similarity` 讓弱 match 走 `not_matched` 且 status `ng`；`expected` 可把選定 label 轉成 `ok`/`ng` 判斷。DL 頁可直接把另一張已標註影像加入已儲存庫，無需重建全部內容。

**Augmentation** 預設關閉。`mlp_classify` 只在訓練集加入水平翻轉與亮度抖動；`patch_segment` 也從翻轉影像取樣並同步翻轉標籤；四個 network trainer 直接暴露 `degrees`、`fliplr`、`mosaic`。

### 無訓練登錄偵測 {#registration}

**Registration detection** 以少量裁切範例尋找零件。Registered pictures 下加入少於十張圖，每張含單一目標與少量背景；Excluded pictures 可描述不可計入的相似物。無需訓練專案、標籤或擬合模型；深度學習加裝包提供的 feature model 必須已安裝，檢測時不下載。

工具頁的 **Add from current image** 可在目前預覽圖上畫矩形或旋轉矩形，直接把裁切加入清單。Detect 走 Found/Not found，Count 檢查最小/最大數量，Presence 檢查 Present/Absent。搜尋區可為矩形或旋轉矩形；相對尺寸與角度範圍涵蓋尺寸和姿態變化。Minimum similarity 是主要調整項。

## 7. 標籤資料集匯出與匯入 {#interop}

標籤存在資料庫中，也可以與 txt label dataset 雙向移動。格式與同系列標註工具相容：tab 分隔、LF、utf-8-sig、六位小數；五欄代表 box，七欄以上偶數座標代表 polygon。

```text
POST /api/vision/dl/projects/{id}/dataset-export   {"dir": "D:/TrainingImage/NEW", "val_ratio": 0.2}
POST /api/vision/dl/projects/{id}/dataset-import   {"dir": "D:/TrainingImage/ATD3"}
```

- Export 寫入 images/labels/{train,val} 與 data.yaml，之後清除 `labels/*.cache`。
- Import 接受 `root/` 或 `root/dataset/` 版型與任何 split 子資料夾；專案缺少的 data.yaml 類別會新增，重複影像依像素 hash 略過。
- **介面中**：右側 Dataset 面板的「Export labels」與「Import labels」，適用 shapes 專案，路徑為伺服端本機資料夾。

### 內建分類器細節 {#mlp}

| 項目 | 細節 |
|---|---|
| kind | `mlp_classify`（label mode `classes`；結果由 `dl_classify` 使用） |
| 方法 | 樣本縮放到輸入尺寸，轉 RGB，以 ImageNet mean/std 正規化，再送入單隱藏層全連接網路，以 numpy full-batch gradient descent 訓練 |
| 匯出 | 手工 ONNX；`apps/vision/dl/onnx_io.py` 避免 onnx 或 torch 成為必要依賴 |
| 超參數 | 輸入尺寸、hidden width、epochs、learning rate、validation ratio，皆有合理預設 |
| 適合 | 區分整體外觀，例如正反面、型號差異或明顯缺陷；光照或位置變化大時請先裁切 ROI 並提高輸入尺寸 |

## 8. 擴充：新增模型種類（Trainer） {#extend}

模式與工具、來源、連線一致：繼承 `apps.vision.dl.base.Trainer`，放到 `plugins/`（見 [Plugins](/docs/plugins.html)）。專案建立、標註、超參數表單與訓練面板都由 `GET /dl/trainers` 目錄驅動，**新模型不需要前端變更**。

```python
# plugins/my_trainer.py -- drop it in plugins/ and it loads
from apps.vision.dl.base import SampleRef, Suggestion, Trainer, TrainError, TrainResult
from apps.vision.tools.base import Param

class MyTrainer(Trainer):
    kind = "my_model"
    label = "My model"
    description = "..."
    label_mode = "classes"
    tool_key = "dl_classify"
    devices = ("cpu", "cuda")
    params = [Param("epochs", "Epochs", kind="number", default=100)]
```

- 重依賴如 torch 請以 requirements.txt 隨外掛提供，在 `train()` 內延遲 import，缺少時以 `TrainError` 回報安裝命令。
- 產物必須是 **ONNX bytes**，這是訓練與推論之間的唯一契約。
- `label_mode` 是封閉集合；新增模式時需同時擴充後端集合與標註介面。

## 9. API {#api}

```text
GET    /api/vision/dl/trainers
GET    /api/vision/dl/devices
PATCH  /api/vision/dl/settings
GET    /api/vision/dl/projects
POST   /api/vision/dl/projects
GET/PATCH/DELETE /api/vision/dl/projects/{id}
GET    /api/vision/dl/projects/{id}/samples
POST   /api/vision/dl/projects/{id}/samples
POST   /api/vision/dl/projects/{id}/samples/from-source
GET    /api/vision/dl/samples/{id}/file
PATCH  /api/vision/dl/samples/{id}
DELETE /api/vision/dl/samples/{id}
POST   /api/vision/dl/projects/{id}/labels
POST   /api/vision/dl/projects/{id}/auto-label
GET    /api/vision/videos
POST   /api/vision/dl/projects/{id}/video-extract
GET    /api/vision/dl/projects/{id}/video-extract/status?log_from=N
POST   /api/vision/dl/projects/{id}/video-extract/stop
POST   /api/vision/dl/projects/{id}/split
GET/POST /api/vision/dl/projects/{id}/versions
DELETE /api/vision/dl/versions/{id}
POST   /api/vision/dl/projects/{id}/sam-point
POST   /api/vision/dl/projects/{id}/quick-register
POST   /api/vision/dl/projects/{id}/train
GET    /api/vision/dl/train/status?log_from=N
POST   /api/vision/dl/train/save
POST   /api/vision/dl/train/discard
POST   /api/vision/dl/train/cancel
```

讀取、標註與訓練開放給任何已登入使用者與 integrator key；訓練另需通過 `can_execute()`，引擎鎖定時為 423；裝置設定僅限管理員。

## 10. 內部結構與取捨 {#internals}

- `apps/vision/dl/` 包含 trainer registry、內建 MLP 與輕量 segmenter、network trainer、shape validation、ONNX 匯出、SAM 輔助標註、quick register、video extraction、devices、jobs 與 API。前端包含 `DlPage.tsx`、`ShapeWorkspace.tsx`、`VideoExtractPanel.tsx` 與 `optimize.ts`。
- 資料模型包含 `DlProject`、`DlSample`、`DlDatasetVersion` 與 `DlSettings`。影像以 imencode + tofile 寫入，支援非 ASCII 路徑；`sha256` 供去重，`split` 供分割。
- 相較 Roboflow 式規格，功能都在：去重、split、version、augmentation、SAM 輔助標註、訓練指標；架構仍維持平台約束。Celery/Redis 改為背景執行緒中的單一訓練槽，React-Konva 改用既有雙層 ImageViewer，DRF 仍為 django-ninja，SQLite/WAL 與 0-1 JSON 座標沿用平台慣例。
- 一次只允許一個訓練；第二個請求回 409。進度每 700 ms 輪詢，不走 SSE bus。
- `preferred_providers` 是 hot-path 設定；資料庫只在啟動與設定 endpoint 觸碰。
- torch 不是必要依賴；內建 trainer 使用 numpy 並匯出手工 ONNX。重框架屬於外掛 trainer。

## 11. 安裝與陷阱（torch、ultralytics、onnxruntime-gpu） {#install}

深度學習依賴是**選用**。平台沒有它們也能啟動；ONNX dl_* 工具可用 CPU，ai_* 工具與 SAM 會回報尚未安裝。GPU 訓練與推論可用：

```powershell
.\scripts\setup_dl.ps1
.\.venv\Scripts\python.exe manage.py dl_check --predict
```

順序很重要：先從 pytorch.org index 安裝 torch，再安裝 `requirements-dl.txt`。已安裝站台不需手動輸入；供應商會預先建置加裝包並由 `vsctl dl install ... -Predict` 離線安裝。

| 症狀 | 原因 | 修正 |
|---|---|---|
| 訓練只用 CPU | PyPI 的 ultralytics 拉入 CPU torch | 先安裝 CUDA torch，再裝 ultralytics |
| RTX 50 出現 no kernel image | 需要 cu128 以上 wheel | 使用 `setup_dl.ps1 -Cuda cu128` |
| CUDA provider 存在但 session 落到 CPU | onnxruntime-gpu 與 CUDA DLL 版本不合 | pin `onnxruntime-gpu==1.22.0` |
| provider list 每次不同 | 同時安裝多個 onnxruntime wheel | 只保留一個 runtime package |
| 處理器加速未出現 | openvino runtime 也共用 import name | 改安裝 `onnxruntime-openvino` 並移除其他 runtime |
| ONNX 匯出警告 AutoUpdate | ultralytics 查套件名而非 GPU 版 | 忽略，且不要讓它 AutoUpdate |
| Windows 訓練卡住 | 背景執行緒內啟動 DataLoader worker 會 deadlock | 保持 `workers=0` |
| 離線首次訓練卡下載 | ultralytics 自行檢查網路 | 檔案事先放入 `ASSET_DIR/dl/weights/` |
| sam2 module not found | 不需要 Facebook sam2 package | 使用 ultralytics 內建 SAM2 |
| 分類訓練後類別錯 | ultralytics 依資料夾順序定 class index | 依 `model.names` 回寫標籤 |
| half deprecated 警告 | ultralytics 對 `half=False` 也警告 | 只有真正 half precision 時傳 half=True |

2026 年 9 月已驗證組合：Python 3.12、torch 2.11.0+cu128、torchvision 0.26、ultralytics 8.4.137、onnx 1.22、onnxslim 0.1.96、onnxruntime-gpu 1.22.0。

### 異常偵測 backbone {#install-anomaly}

`anomaly` 模型種類需要 `ASSET_DIR/dl/weights/resnet18_l2l3.onnx`，這是 ImageNet 預訓練 ResNet18 截到 layer3 的 ONNX 檔，約 11 MB。深度學習加裝包會攜帶並由 `vsctl dl install` 複製；開發機可用 `manage.py anomaly_backbone --export` 產生，`--check` 可執行一次並回報 provider。執行時不下載；缺檔時訓練會以指明路徑的訊息失敗。
