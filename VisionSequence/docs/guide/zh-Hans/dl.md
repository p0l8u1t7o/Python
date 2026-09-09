# 深度学习教导：在平台内标注、训练与导出

深度学习页（`/dl`）帶您在**不離開平台**的情況下完成一輪教导：建立教导项目、收集样本、标注、在服务端训练，最后將模型导出為**资产**，可在任何流程的 DL 工具中選用。模型種类（trainer）是註冊表；新增 trainer 會重用同一介面，不需要前端變更。

## 1. 從用户角度看教导流程 {#flow}

1. **建立教导项目**：输入名稱、模型種类与类別，例如 `OK, NG`；之后仍可新增或移除。
2. **收集样本**：使用「Upload images」多選上传，也接受 zip；或用「Grab from source」選图像来源擷取 N 張，可預先標籤。所有上传都以解碼后像素 SHA256 去重。
3. **标注分类**：Grid 適合大量縮圖快速標籤；Large 左側為縮圖牆、右側為全圖檢視器，含縮放与 1:1。
4. **训练**：右側面板显示由 trainer 宣告產生的超参数、裝置与模型资产名稱。進度与指標即時更新，训练在背景执行，不佔用检测线程池。
5. **保留或丟棄**：训练完成不會自動寫入资产庫。**Save to Assets** 會保存模型並更新项目最后模型，**Discard** 會删除 pending 檔案。
6. **使用**：保存模型后會出現在资产庫（kind=model）。在流程加入 DL 工具、選模型並貼上类別清單即可。

### Quick register {#quick-register}

**Quick register** 是 box 项目最短路徑：加入至少兩張图像、檢視建议框、命名资产，並從既有训练面板開始。服务端會把建议框存到尚未标注样本、選保守 preset，然后啟動与一般路徑相同的训练工作。工作完成並命名保留前，不會存到 Assets。

- 僅適用於至少一個类別、至少兩個样本的 box 项目。
- preset 刻意小且短：size `n`、`epochs=20`、`batch=4`、`patience=8`、`lr0=0.001`、`val_ratio=0.2`、`workers=0`，無旋转、翻转或混圖。
- 回覆含 `job_id`、`labeled`、`skipped` 与 `params`，可檢視並重用设置。
- 错误状态明確：缺样本、类別或框為 `422`；已有训练為 `409`；無 DL 權限為 `403`。

**圖庫中的深度学习模板**：「AI object count (stock model)」与「AI instance segmentation: sign area」使用 COCO stock model，不需训练。「Classification: good / missing hole」与「Semantic segmentation: scratch area」使用 `seed_demo` 以內建 trainer 训练的示範模型。見 [範例模板](samples.md)。

## 2. 自動标注 {#auto}

标注是起步最慢的部分，因此每個 trainer 可实现 `suggest()`，為尚未标注样本提供建议类別与信心值。內建分类器使用**特徵空間 cosine kNN (k=3)**，每类有少量人工标注后即可即時回應，無需先训练。

- 点击「Auto label」后，尚未标注縮圖會出現虛线建议，例如 `NG? 87%`；可全部接受或個別改標。
- 自動标注样本記為 `labeled_by=auto`；人工重標后變成 `human`。
- 只有 `human` 標籤可作 kNN 參考，避免自動標籤自我強化。
- 網路 trainer 在已有训练后用最后的 best.pt 建议；之前則用 stock model。
- shapes 项目的 whole-image proposal 使用 SAM2 產生最多 30 個区域，每次 20 張，提案附到第一类等待確認。
- Smart select 与 smart box 在标注编辑器中用 S/X 觸發 SAM2，權重首次使用時下載，缺依賴時會显示安裝命令。

## 3. 服务端資源与裝置设置 {#devices}

训练与推論都使用**服务端**資源。页面頂端由 `GET /dl/devices` 显示检测到的加速器与 GPU：

| 欄位 | 內容 |
|---|---|
| `providers` | 此服务端的 onnxruntime execution providers，例如 CPU、CUDA、DirectML、TensorRT |
| `gpus` | NVIDIA GPU 名稱、内存使用与使用率；只有 `nvidia-smi` 可用時有值 |
| `preferred_providers` / `train_device` | 目前選擇；由管理員以 `PATCH /dl/settings` 修改 |

- **推論**：`preferred_providers` 決定 dl_* 工具建立 ORT session 時使用的 providers；不可用項會過濾，CPU 永遠最后。變更會清除 session 快取並立即生效。
- **训练**：裝置下拉列列出服务端具備且 trainer 支持的裝置。內建 MLP 只需 CPU，數秒即可完成。

## 4. shapes 标注编辑器（分割与检测） {#shapes}

`label_mode="shapes"` 的語意/實例分割与检测模型使用**标注编辑器**。每張圖可有多個多边形或框實例，各自帶类別。座標一律以 **0-1 正規化**保存，只有畫布显示時转回像素。

- **编辑**：畫布左側是大型圖示工具列，包含 select、polygon、box、refine、delete、undo 与快捷鍵；上方状态列显示前后圖、样本尺寸、標籤數、提示、未保存状态与 save。
- **多边形逐点绘制且無点數限制**：N 或工具列進入模式，每次点击加頂点；双擊、点击第一点或 Enter 关闭，Backspace 移除上一点，Esc 取消。
- **Smart select**：按 S 並点击物件，服务端分割輪廓、簡化為多边形並套用目前类別。
- **Smart box**：按 X 拖出框，SAM2 回傳框內物件輪廓。
- **Refine**：純前端 JavaScript 在灰階梯度圖上沿頂点法线尋边，迭代、平滑並用 Douglas-Peucker 簡化，需手動保存。
- **縮圖牆檢視**：縮圖繪出标注輪廓，可快速看出不良标注；自動提案以 `?` 標示。
- **自動标注**：shapes 模式的提案是一整組形狀，可單張或全部接受，接受后仍標為 auto 等待檢視。

## 5. 数据集管理（去重、分割、版本） {#dataset}

- **重复检测**：每個样本保存解碼后像素 SHA256，项目內上传、zip、来源 burst 与数据夾导入都會去重並回報 `duplicates`。
- **train/val/test 分割**：右側 Dataset 面板显示各 split 數量。「Auto split」依比例分層隨機指派；工作區状态列的 split chip 可在 train -> val -> test -> unset 間切換。
- **训练如何使用**：標為 `val` 的样本成為 validation；標為 `test` 的样本永不進入训练，保留為 blind check 並回報 `test_holdout`。
- **凍結版本**：「Freeze」把目前样本、標籤与 split 导出為 zip 到**资产庫（kind=dataset）**，含统计。版本可下載或删除。

### 從影片建立样本 {#video-extract}

采集端可在本機记录各 channel、上传到 `DATA_DIR/videos/<client>/`，或在同機時直接寫入服务端数据夾。DL 页以 `GET /api/vision/videos` 列出檔案。

實例分割项目的「Create samples from video」面板會啟動背景擷取：錄影、上传、擷取、在既有 shape editor 校正標籤、训练，再於流程中選用新模型。擷取每 `stride` 張處理一張，执行目前分割模型、套 edge margin filter，再以私有状态追蹤物件，因此不會改動流程變數。每條 track 首次 confirmed 保存一張全圖样本，之后每 `k` 張處理畫格再存一次，直到該 track 達到 `n` 張；默认 `n=3`、`k=5`。

## 6. 內建模型与 augmentation {#builtin}

| kind | 任務 / 標籤 | 方法 | 推論工具 | 依賴 |
|---|---|---|---|---|
| `mlp_classify` | 图像分类（classes） | numpy 训练 MLP，手工导出 ONNX，預處理与工具默认一致；含 learning-rate protection | dl_classify | 無 |
| `patch_segment` | 語意分割（shapes） | numpy patch classifier，导出 fully convolutional ONNX，可接受任意输入尺寸 | dl_segment | 無 |
| `retrieval` | 图像檢索分类 | 從标注图像建立自含參考庫，执行時由最近參考投票 | dl_retrieval | 內建 reference matcher |
| `ai_seg` | 實例分割 | 以数据庫样本建立训练数据集，回報 loss、mAP 与 log，输出 best.pt 与 ONNX | **ai_segment** 或 dl_instance | 選用 DL 依賴 |
| `ai_detect` | 物件检测 | 以框训练 stock detection network，标注成本最低 | **ai_detect** 或 dl_detect | 選用 |
| `ai_cls` | 图像分类 | 寫成 classification dataset 后從 stock model 微調 | **ai_classify** 或 dl_classify | 選用 |
| `anomaly` | 異常检测（只需良品） | ResNet18 backbone 產生 patch features，coreset 記憶庫保留良品特徵，阈值由良品 leave-one-out 分數推得 | dl_anomaly | backbone ONNX |
| `ai_obb` | 旋转框 | 多边形转 minimum-area rotated rectangle 后训练 oriented-box network | **ai_obb** | 選用 |

### 參考庫分类 {#retrieval-library}

retrieval 项目適合类別持續增加的產线。右側面板稱為 **Build library** 而非 train：它掃描已标注图像，每張原圖与選用光照變體保存一筆 reference，最后存成 `.npz` 资产。资产含类別清單、正規化 reference matrix、每列 label index、縮圖与 matcher bytes，可在站台間移動。

`dl_retrieval` 执行時把输入 ROI 与庫比較，回傳 top matches，並由近鄰加權投票選 label。`min_similarity` 讓弱 match 走 `not_matched` 且 status `ng`；`expected` 可把選定 label 转成 `ok`/`ng` 判斷。DL 页可直接把另一張已标注图像加入已保存庫，無需重建全部內容。

**Augmentation** 默认关闭。`mlp_classify` 只在训练集加入水平翻转与亮度抖動；`patch_segment` 也從翻转图像取樣並同步翻转標籤；四個 network trainer 直接暴露 `degrees`、`fliplr`、`mosaic`。

### 無训练登錄检测 {#registration}

**Registration detection** 以少量裁切範例尋找零件。Registered pictures 下加入少於十張圖，每張含單一目標与少量背景；Excluded pictures 可描述不可計入的相似物。無需训练项目、標籤或擬合模型；深度学习加裝包提供的 feature model 必須已安裝，检测時不下載。

工具页的 **Add from current image** 可在目前預覽圖上畫矩形或旋转矩形，直接把裁切加入清單。Detect 走 Found/Not found，Count 檢查最小/最大數量，Presence 檢查 Present/Absent。搜尋區可為矩形或旋转矩形；相對尺寸与角度範圍涵蓋尺寸和姿態變化。Minimum similarity 是主要調整項。

## 7. 標籤数据集导出与导入 {#interop}

標籤存在数据庫中，也可以与 txt label dataset 双向移動。格式与同系列标注工具相容：tab 分隔、LF、utf-8-sig、六位小數；五欄代表 box，七欄以上偶數座標代表 polygon。

```text
POST /api/vision/dl/projects/{id}/dataset-export   {"dir": "D:/TrainingImage/NEW", "val_ratio": 0.2}
POST /api/vision/dl/projects/{id}/dataset-import   {"dir": "D:/TrainingImage/ATD3"}
```

- Export 寫入 images/labels/{train,val} 与 data.yaml，之后清除 `labels/*.cache`。
- Import 接受 `root/` 或 `root/dataset/` 版型与任何 split 子数据夾；项目缺少的 data.yaml 类別會新增，重复图像依像素 hash 略過。
- **介面中**：右側 Dataset 面板的「Export labels」与「Import labels」，適用 shapes 项目，路徑為服务端本機数据夾。

### 內建分类器細節 {#mlp}

| 項目 | 細節 |
|---|---|
| kind | `mlp_classify`（label mode `classes`；結果由 `dl_classify` 使用） |
| 方法 | 样本縮放到输入尺寸，转 RGB，以 ImageNet mean/std 正規化，再送入單隱藏層全连接網路，以 numpy full-batch gradient descent 训练 |
| 导出 | 手工 ONNX；`apps/vision/dl/onnx_io.py` 避免 onnx 或 torch 成為必要依賴 |
| 超参数 | 输入尺寸、hidden width、epochs、learning rate、validation ratio，皆有合理默认 |
| 適合 | 區分整體外觀，例如正反面、型號差異或明顯缺陷；光照或位置變化大時請先裁切 ROI 並提高输入尺寸 |

## 8. 擴充：新增模型種类（Trainer） {#extend}

模式与工具、来源、連线一致：繼承 `apps.vision.dl.base.Trainer`，放到 `plugins/`（見 [Plugins](/docs/plugins.html)）。项目建立、标注、超参数表單与训练面板都由 `GET /dl/trainers` 目錄驅動，**新模型不需要前端變更**。

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

- 重依賴如 torch 請以 requirements.txt 隨插件提供，在 `train()` 內延遲 import，缺少時以 `TrainError` 回報安裝命令。
- 產物必須是 **ONNX bytes**，這是训练与推論之間的唯一契約。
- `label_mode` 是封閉集合；新增模式時需同時擴充后端集合与标注介面。

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

讀取、标注与训练開放給任何已登录用户与 integrator key；训练另需通過 `can_execute()`，引擎鎖定時為 423；裝置设置僅限管理員。

## 10. 內部結構与取捨 {#internals}

- `apps/vision/dl/` 包含 trainer registry、內建 MLP 与輕量 segmenter、network trainer、shape validation、ONNX 导出、SAM 輔助标注、quick register、video extraction、devices、jobs 与 API。前端包含 `DlPage.tsx`、`ShapeWorkspace.tsx`、`VideoExtractPanel.tsx` 与 `optimize.ts`。
- 数据模型包含 `DlProject`、`DlSample`、`DlDatasetVersion` 与 `DlSettings`。图像以 imencode + tofile 寫入，支持非 ASCII 路徑；`sha256` 供去重，`split` 供分割。
- 相較 Roboflow 式規格，功能都在：去重、split、version、augmentation、SAM 輔助标注、训练指標；架構仍維持平台約束。Celery/Redis 改為背景线程中的單一训练槽，React-Konva 改用既有双層 ImageViewer，DRF 仍為 django-ninja，SQLite/WAL 与 0-1 JSON 座標沿用平台慣例。
- 一次只允許一個训练；第二個請求回 409。進度每 700 ms 輪詢，不走 SSE bus。
- `preferred_providers` 是 hot-path 设置；数据庫只在啟動与设置 endpoint 觸碰。
- torch 不是必要依賴；內建 trainer 使用 numpy 並导出手工 ONNX。重框架屬於插件 trainer。

## 11. 安裝与陷阱（torch、ultralytics、onnxruntime-gpu） {#install}

深度学习依賴是**選用**。平台沒有它們也能啟動；ONNX dl_* 工具可用 CPU，ai_* 工具与 SAM 會回報尚未安裝。GPU 训练与推論可用：

```powershell
.\scripts\setup_dl.ps1
.\.venv\Scripts\python.exe manage.py dl_check --predict
```

順序很重要：先從 pytorch.org index 安裝 torch，再安裝 `requirements-dl.txt`。已安裝站台不需手動输入；供應商會預先建置加裝包並由 `vsctl dl install ... -Predict` 離线安裝。

| 症狀 | 原因 | 修正 |
|---|---|---|
| 训练只用 CPU | PyPI 的 ultralytics 拉入 CPU torch | 先安裝 CUDA torch，再裝 ultralytics |
| RTX 50 出現 no kernel image | 需要 cu128 以上 wheel | 使用 `setup_dl.ps1 -Cuda cu128` |
| CUDA provider 存在但 session 落到 CPU | onnxruntime-gpu 与 CUDA DLL 版本不合 | pin `onnxruntime-gpu==1.22.0` |
| provider list 每次不同 | 同時安裝多個 onnxruntime wheel | 只保留一個 runtime package |
| 處理器加速未出現 | openvino runtime 也共用 import name | 改安裝 `onnxruntime-openvino` 並移除其他 runtime |
| ONNX 导出警告 AutoUpdate | ultralytics 查套件名而非 GPU 版 | 忽略，且不要讓它 AutoUpdate |
| Windows 训练卡住 | 背景线程內啟動 DataLoader worker 會 deadlock | 保持 `workers=0` |
| 離线首次训练卡下載 | ultralytics 自行檢查網路 | 檔案事先放入 `ASSET_DIR/dl/weights/` |
| sam2 module not found | 不需要 Facebook sam2 package | 使用 ultralytics 內建 SAM2 |
| 分类训练后类別錯 | ultralytics 依数据夾順序定 class index | 依 `model.names` 回寫標籤 |
| half deprecated 警告 | ultralytics 對 `half=False` 也警告 | 只有真正 half precision 時傳 half=True |

2026 年 9 月已驗證組合：Python 3.12、torch 2.11.0+cu128、torchvision 0.26、ultralytics 8.4.137、onnx 1.22、onnxslim 0.1.96、onnxruntime-gpu 1.22.0。

### 異常检测 backbone {#install-anomaly}

`anomaly` 模型種类需要 `ASSET_DIR/dl/weights/resnet18_l2l3.onnx`，這是 ImageNet 預训练 ResNet18 截到 layer3 的 ONNX 檔，約 11 MB。深度学习加裝包會攜帶並由 `vsctl dl install` 複製；開發機可用 `manage.py anomaly_backbone --export` 產生，`--check` 可执行一次並回報 provider。执行時不下載；缺檔時训练會以指明路徑的訊息失敗。
