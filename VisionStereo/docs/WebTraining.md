# VisionStereo — Web 標註與線上訓練子系統

> 給其他專案的 AI 代理閱讀：本文完整描述 VisionStereo 內建的「瀏覽器版 YOLO 分割資料集標註 + 線上訓練」子系統的功能、API、資料格式與移植／開發時的注意事項。
> 對應原始碼：[Bin/labelServer.py](../Bin/labelServer.py)、[Bin/trainJob.py](../Bin/trainJob.py)、[Bin/videoDataset.py](../Bin/videoDataset.py)、[Bin/web/](../Bin/web/)

---

## 1. 這是什麼

一套**單機、免安裝框架、瀏覽器操作**的「線下錄影 → 線上訓練」閉環工具，用來持續迭代產線上的 YOLO segmentation 模型：

```
線下錄影 (.avi) → 影片轉資料集(自動標註) → 網頁標註修正 → 切分 train/val → 訓練 + 匯出 ONNX → 換回設備
       ↑                                                                                          │
       └──────────────────────────────────────────────────────────────────────────────────────────┘
```

特色是**後端只用 Python 標準函式庫起 HTTP 服務**（`http.server.ThreadingHTTPServer`），前端是**無建置流程的原生 HTML/CSS/JS 單頁**；`torch` / `ultralytics` 只在真正要轉檔或訓練時才 import。因此伺服器啟動幾乎是瞬間，也可以嵌進 LabVIEW 之類的宿主流程。

### 網頁功能頁面

| 頁面 | 功能 |
| --- | --- |
| 標註編輯 | Canvas 上編輯 polygon / bbox ROI：拖曳頂點、雙擊邊線插點、Alt+點刪點、新增／刪除多邊形、改分類、Ctrl+Z 還原、Ctrl+S 存回 txt。支援滑鼠與觸控（雙指縮放平移） |
| 自動優化 | 前端純 JS 的「輪廓貼邊」：在影像梯度圖上沿法線搜尋最強邊緣 → 平滑 → Douglas–Peucker 簡化。不自動儲存 |
| 多圖瀏覽 | 縮圖牆，直接把標記輪廓畫在縮圖上，快速巡檢哪些張標壞了 |
| 影片轉資料集 | 用現有權重掃過影片，自動產生 images/labels，含 MJPEG 即時預覽 |
| 模型訓練 | 完整的 ultralytics 訓練參數表單 + 即時進度、loss/mAP 曲線、log、中止 |
| 資料集設定 | 編輯 `data.yaml` 類別；設定 train/val 比例並**實際搬移本地檔案** |
| 統計 | 每個 split 的影像數、已標註數、物件數、各類別分佈 |
| 使用流程 | 內建教學頁，並顯示本機區網網址（給手機連線） |

---

## 2. 架構

```
Bin/labelServer.py     HTTP 伺服器 + 資料集存取層(Dataset) + 路由        ← 只依賴標準庫
   ├─ Bin/web/                index.html / app.js / style.css（靜態單頁前端）
   ├─ Bin/videoDataset.py     影片→資料集背景工作（延後 import torch）
   │     └─ Bin/yoloSegByteTrack.py   共用推論／追蹤／過濾邏輯
   └─ Bin/trainJob.py         YOLO 訓練背景工作（延後 import torch）
         └─ 參數對應 Bin/yoloTrackTraining.py
```

三個模組的分工很乾淨，可以單獨抽出來重用：

- **`labelServer.py`** — 純 I/O 與 HTTP。`Dataset` 類別封裝一個 YOLO 資料夾的讀寫、統計、切分。
- **`videoDataset.py` / `trainJob.py`** — 各自是一個「**模組級單例背景工作**」：`start_job()` / `get_status()` / `stop_job()` 三件式介面，狀態放在模組層的 `_state` dict，用 `threading.RLock` 保護。伺服器只是把 HTTP 請求轉成這三個呼叫。

### 目錄結構假設

```
<root>/                      ← 使用者選的資料夾
└── dataset/                 ← 若 <root>/images 存在，則 <root> 自己就是 dataset
    ├── images/{train,val,test}/*.jpg
    ├── labels/{train,val,test}/*.txt
    └── data.yaml
```

`Dataset.open()` 會依序試 `<root>/dataset` 與 `<root>`，取第一個含 `images/` 的當作資料集根。split 不限於 train/val/test，`images/` 底下任何子資料夾都算一個 split（已知的三個排前面，其餘依名稱排序）。

---

## 3. HTTP API

錯誤一律回 JSON `{"error": "訊息"}`，狀態碼 400（ValueError）／404（FileNotFoundError）／500（其他）。前端 `api()` 會把非 JSON 回應與含 `error` 的回應都轉成 throw。

### GET

| 路徑 | 查詢參數 | 回傳 |
| --- | --- | --- |
| `/api/config` | — | `{root, dataset, yaml, splits[], classes[], hasPillow, hasYaml}` |
| `/api/browse` | `path`（空字串在 Windows 回磁碟機清單） | `{path, parent, dirs:[{name,path}]}` |
| `/api/list` | `split, q, cls, state(all\|labeled\|empty), page, pageSize(≤500)` | `{split,total,page,pageSize,items:[{name,objects,classes[]}]}` |
| `/api/label` | `split, name` | `{split,name,shapes[],labelPath}` |
| `/api/image` | `split, name` | 原圖 bytes（帶 ETag） |
| `/api/thumb` | `split, name, w(64~1024)` | JPEG 縮圖（帶 ETag；無 Pillow 時退回原圖） |
| `/api/stats` | — | `{split: {images, labeled, objects, perClass}}` |
| `/api/net` | — | `{port, host, lan, addresses[]}` |
| `/api/video/list` | `dir` | `{dir, videos:[{name,path,sizeMB}]}` |
| `/api/video/status` | `logFrom` | 轉檔狀態（見 §7） |
| `/api/video/stream` | `fps`（0.2~10） | `multipart/x-mixed-replace` MJPEG 串流 |
| `/api/video/preview` | — | 最新一張預覽 JPEG |
| `/api/video/defaults` | — | 影片轉檔預設參數 |
| `/api/train/status` | `logFrom` | 訓練狀態（見 §7） |
| `/api/train/defaults` | — | `trainJob.DEFAULTS` + 依目前資料集覆寫 `data` / `name` / `outputDir` |

### POST（body 為 JSON）

| 路徑 | body | 說明 |
| --- | --- | --- |
| `/api/root` | `{path}` | 切換資料集，回傳新的 config |
| `/api/label` | `{split, name, shapes[]}` | 寫回標記檔，回 `{ok, lines, labelPath}` |
| `/api/classes` | `{names[]}` | 改寫 `data.yaml` 的 `nc` / `names` |
| `/api/video/start` | `{videoDir,outDir,modelPath,conf,imgsz,minArea,edgeMargin,maxPolyPoints,split}` | 啟動轉檔，立即返回 |
| `/api/video/stop` | `{}` | 要求中止 |
| `/api/train/start` | `trainJob.DEFAULTS` 的任意子集（伺服器會過濾掉不在 DEFAULTS 的 key） | 啟動訓練，立即返回 |
| `/api/train/stop` | `{}` | 要求中止（保留權重） |
| `/api/split` | `{trainRatio, seed, shuffle, includeTest, dryRun}` | 重新切分 train/val，**會實際搬移檔案** |

`shapes` 格式：`[{cls:int, kind:"polygon"|"bbox", points:[[x,y],…]}]`，座標一律為 **0~1 正規化**。

---

## 4. 標記檔格式（重要）

本專案的 YOLO txt 有兩個**與一般慣例不同**的地方，移植時務必保持一致：

- **欄位用 TAB 分隔**（不是空白）。讀取端 `_parse_label()` 有相容處理：該行有 TAB 就用 TAB 切，沒有才退回空白切分。
- **換行固定 LF**（`open(..., newline="\n")`），不寫成 Windows CRLF。

其他細節：

- 讀檔用 `encoding="utf-8-sig"`，容忍其他工具寫出的 BOM。
- 數值格式 `f"{v:.6f}"`，寫入前 clamp 到 `[0,1]`。
- 一行 5 個數字 = bbox（`cls cx cy w h`，讀進來會展成四個角點）；≥7 個數字且座標數為偶數 = polygon（`cls x1 y1 x2 y2 …`）。少於 3 個點的形狀會被丟棄。
- **每次寫標記檔或搬移檔案後，一定要刪掉 `labels/*.cache`**（`Dataset.clear_cache_files()`）。ultralytics 會快取資料集掃描結果，不清掉的話下次訓練會沿用舊標記 — 這是最容易踩的坑。

---

## 5. 影片轉資料集（自動標註）

`videoDataset.py` 沿用 `yoloSegByteTrack.py` 的整條線上推論流程：`FramePrep`（前處理／縮放）→ `YOLO.track(tracker="bytetrack.yaml", persist=True)` → conf / 最小面積 / 邊界距離過濾 → `approxPolyDP` 簡化 polygon。

**收錄規則**：當畫面中出現的**新 Track ID 連續 `CONSECUTIVE_FRAMES`（預設 2）幀都存在**時，把該幀整張原始解析度影像存成 `<n>.jpg`，並寫出該幀**所有**通過過濾的物件標記。每個 track id 只收錄一次，且 tracker 每部影片重置（`seg._reset_trackers()`），id 不跨影片延用。

其他要點：

- 檔名依**現有數字續編**（`_next_index()` 掃 `1.jpg…120.jpg` → 從 121 開始），所以可以反覆對同一個資料集累積資料而不覆蓋。
- `data.yaml` 若已存在就**不覆寫**（使用者可能改過類別名）。
- 類別名取自模型的 `model.names`。
- 模型必須是 **segmentation（`-seg`）模型**；沒有 `r.masks` 會直接 raise。
- 進度條的分母是先用 `CAP_PROP_FRAME_COUNT` 把所有影片掃一遍算出的總幀數。

### MJPEG 即時預覽的設計

預覽採「**有人看才做**」：`viewer_enter()` / `viewer_exit()` 維護觀看者計數與各自要求的 fps，`preview_interval()` 回傳目前最快觀看者的間隔；沒有觀看者時回 `None`，轉檔迴圈就**完全不複製影格、不畫 overlay、不編碼 JPEG**，轉檔速度不受影響。被收錄的那一幀則一定會送出預覽（不受節流限制）。

`wait_preview()` **必須寫成 deadline 迴圈**（`while` + `cv.wait(remain)`）。工作結束時 `_clear_preview()` 會把 `seq` 遞增但 `jpeg` 設為 `None`，若只判斷一次就返回，呼叫端會拿到「立刻返回的 None」而變成忙迴圈。

伺服器端 `Handler._mjpeg()` 在串流迴圈中，只要「工作沒在跑且已閒置超過 10 秒」就主動收線；前端關分頁則靠 `BrokenPipeError` 等例外收尾，`finally` 一定要呼叫 `viewer_exit()`，否則觀看者計數洩漏，轉檔會一直付預覽成本。

---

## 6. 訓練工作

`trainJob.py` 的參數與流程對應 `yoloTrackTraining.py`（訓練 → 匯出 → 複製到輸出資料夾），差別是改成背景執行緒 + 可查詢進度 + 可中止。

### 進度來源：ultralytics callbacks

| callback | 用途 |
| --- | --- |
| `on_train_start` | 取得總 epoch 數與每 epoch 的 batch 數、`save_dir` / `best` / `last` |
| `on_train_epoch_start` | 重置 batch 計數、記錄 epoch 起始時間 |
| `on_train_batch_end` | 更新 batch 進度與即時 loss；**也是中止的檢查點** |
| `on_fit_epoch_end` | 每個 epoch 的驗證指標（mAP 等），累積成 `history` 曲線 |
| `on_train_end` | 最終 best／last 權重路徑 |

### 兩個必須知道的 ultralytics 行為

1. **中止的做法是設 `trainer.stop = True`。** ultralytics 在 `on_train_batch_end` 之後緊接著就是 `if self.stop: break`，所以會在當前 batch 立刻跳出，然後**照常做驗證與存檔** — 中止不會讓已訓練的權重白費。中止後仍會走完匯出與複製流程。

2. **`on_fit_epoch_end` 在訓練結束後會被多觸發一次。** 那是 `final_eval` 在驗證 `best.pt`，`t.epoch` 已經加一，不是第 N+1 個 epoch。程式用 `_last_epoch_started`（最後一個真的進到訓練迴圈的 epoch）判斷：`ep > _last_epoch_started` 就只更新 `metrics`、不新增歷史列。中途中止的情況也適用同一個判斷。

### 其他要點

- `_filter_supported()` 會拿 `ultralytics.cfg.DEFAULT_CFG_DICT` 過濾增強參數，不支援的直接丟掉並記 log。**跨 ultralytics 版本移植時靠這個保命**；新增增強參數請一併加進 `AUG_KEYS`。
- ETA 用**最近 10 個 epoch** 的平均耗時估算（`del _epoch_times[:-10]`）。
- 指標 key 會去掉 `metrics/` 前綴；分割任務同時有 `(B)`（box）與 `(M)`（mask）兩組，取值時優先 `(M)`、退回 `(B)`。
- `fitness` 是加權和，**分割任務常常大於 1**，前端畫圖的座標軸要跟著資料放大，不能寫死 0~1。
- 訓練前檢查 `torch.cuda.is_available()`，沒 GPU 自動退回 CPU 並記 `[WARN]`。
- 匯出失敗只記 `[WARN]`，不影響已完成的訓練結果。
- 設 `YOLO_OFFLINE=1`，避免 ultralytics 在無網路環境卡住。
- 訓練完成後可依 `copyBest` / `copyLast` / `copyExport` 把權重與匯出檔複製到 `outputDir`，方便設備端直接取用。

---

## 7. 狀態輪詢與 log 協定（兩個工作模組共用）

```python
_state = {"running", "done", "error", "phase", …, "log": [...]}
_LOG_KEEP = 400          # 環形緩衝：只留最近 N 行（videoDataset 是 200）
_log_base = 0            # 已被丟棄的行數，用來換算「全域行號」
```

`get_status(log_from)` 的契約：

- 不給 `log_from` → 回全部保留中的 log，附 `logFrom`（第一行的全域行號）。
- 給了 `log_from` → 只回該行號之後的新行。
- 一律回 `logNext`，前端下次帶這個值進來。

`phase` 是狀態機字串：

- 訓練：`idle | loading | training | exporting | copying | finished | stopped | error`
- 轉檔：`idle | loading | running | finished | stopped | error`

**前端輪詢注意**：兩個輪詢同時在路上時，兩邊會用同一個 `logFrom` 去要記錄，回來就會重複又亂序。所以前端用 `TRAIN_INFLIGHT` / `VIDEO_INFLIGHT` 旗標擋住重入，有請求在飛就延後 400ms 再試。閒置時輪詢間隔放慢到 5 秒（執行中 1 秒）。

因為狀態在伺服器端，**關掉瀏覽器分頁不會中斷訓練**，重新開啟頁面就會接上進度。

---

## 8. 前端注意事項

> UI 設計語言（色彩權杖、元件、版面、響應式）與標記互動的完整規格另見 [WebUIDesign.md](WebUIDesign.md)，本節只列與後端協定相關的要點。

- **座標一律以正規化 0~1 儲存**，與 YOLO txt 一致；只有畫到 canvas 時才乘上尺寸。
- **影像快取必須用 ETag，不能用 `max-age`。** 不同資料集的檔名幾乎都是 `1.jpg`、`2.jpg`，URL 會完全相同，用 `max-age` 的話瀏覽器會拿上一個資料集的舊圖去配新的標記。後端 `_file_etag()` 用「完整路徑 + mtime + size」當版本並回 `Cache-Control: no-cache`（必須回源驗證）；前端另外在 URL 帶 `g=<資料集世代>`，換資料夾或搬移檔案後遞增。
- `openImage()` 用 `openSeq` 請求序號丟棄過期回應（快速連按下一張時的競態）。
- 換主題（深／淺色）後**必須重畫** canvas 與圖表，它們是自己畫的、不吃 CSS。
- 未存變更：切換影像前會 `confirmDirty()` 詢問，`beforeunload` 也會攔。
- 自動優化（`optimizeShape`）**不會自動儲存**，且會先 `pushHist()`，使用者可 Ctrl+Z 還原；toast 明確提示「尚未儲存」。演算法是在降到最長邊 1280 的灰階梯度圖上，沿各頂點法線 ±R 搜尋梯度最大處（帶 `PEN * |t|` 的位移懲罰），迭代 3 次並每次平滑，最後 Douglas–Peucker 簡化到 ≤120 點。

### 鍵盤快捷鍵

`Ctrl+S` 儲存、`Ctrl+Z` 還原、`N` 新增多邊形、`V` 選取、`O` 自動優化、`F` 適配視窗、`G` 100% 置中、`←/→` 或 `A/D` 上下張、`Delete` 刪除選取、`Esc` 取消繪製、`Enter` 完成繪製、`0~9` 指定分類、按住 `Space` 平移。輸入框內（`isTyping()`）不觸發。

---

## 9. 啟動方式

### 命令列

```bash
python Bin/labelServer.py                                   # 預設資料夾，只監聽本機
python Bin/labelServer.py --root D:\TrainingImage\ATD3 --port 8000
python Bin/labelServer.py --lan                             # 監聽 0.0.0.0，手機可連
python Bin/labelServer.py --verbose                         # 顯示 HTTP 請求記錄
python Bin/labelServer.py --no-browser
```

兩個工作模組也能單獨當 CLI 跑（會把 log 即時印到 stdout，結束時輸出 JSON 摘要）：

```bash
python Bin/videoDataset.py --videos D:\CaptureVideo --out D:\TrainingImage\NEW
python Bin/trainJob.py --data <data.yaml> --epochs 100 --no-export
```

### 嵌入宿主程式（LabVIEW Python Node 介面）

三個函式都**下命令後立刻返回**，不會阻塞呼叫端；回傳值一律是 JSON **字串**：

```python
labelServer.start_server(root, host="0.0.0.0", port=8000, open_browser=False)
labelServer.stop_server()      # 實際關閉丟給背景執行緒（shutdown() 會等 serve_forever 收尾）
labelServer.server_status()
```

`port` 傳 `0` 由系統指派，實際埠號從回傳的 JSON 讀。重複呼叫 `start_server()` 不會重啟，會直接回目前狀態。資料夾不合法時會**以空資料集啟動**（可在網頁上再指定），並在回傳的 `warning` 欄位說明。

### 相依

- 伺服器本體：**只要標準函式庫**。`PyYAML`（更完整的 `data.yaml` 讀寫，缺少時退回內建的簡易解析器 `_naive_yaml`）與 `Pillow`（縮圖，缺少時直接回原圖、較慢）是可選的。
- 影片轉檔／訓練：`torch`、`ultralytics`、`opencv-python`、`numpy`、`lap`（ByteTrack 需要）。這些都是**延後 import**，沒裝也不影響標註功能，只是對應頁面的 API 會回 500、前端靜默降級。
- 本專案實際驗證的版本（見 `requirements.txt`）：`torch 2.11.0+cu128`、`ultralytics 8.4.100`、`numpy 2.4.4`。

---

## 10. 移植／二次開發注意事項

### 安全性（最重要）

這套工具的設計前提是「**單人、可信任的區域網路**」，直接搬到別的環境前務必評估：

- **沒有任何身分驗證。** `--lan` 會綁 `0.0.0.0`，同網段任何人都能操作。
- `/api/browse` 會**列出整台機器的目錄樹**（Windows 下含所有磁碟機）；`/api/root` 可以把任意資料夾開成資料集。
- `/api/split` 與 `/api/label` 會**實際搬移／覆寫本地檔案**，`/api/train/start` 會啟動吃滿 GPU 的長時間工作。
- 已做的防護只有 `Dataset._safe()`：檔名不得含 `/`、`\`、`.`、`..`，且 resolve 後必須在 base 之下；靜態檔也有同樣的 `WEB_DIR` 前綴檢查。這擋得住路徑穿越，但擋不住「有人故意開別的資料夾」。

若要對外提供，至少要加上：反向代理 + 認證、把 `/api/browse` 限制在白名單根目錄、或把寫入類 API 關掉。

### 並行模型

- 每個工作模組**只有一個全域工作槽**，`start_job()` 在已有工作時直接回 `{"ok": false, "error": …}`。多人同時開網頁會共用同一份狀態，**不是多租戶設計**。
- 工作執行緒都是 `daemon=True`：宿主行程結束會直接砍掉訓練。若要讓訓練活過伺服器重啟，得改成獨立行程。
- `ThreadingHTTPServer` 每個請求一條執行緒；`Dataset` 有 `RLock`，但 `_cache` 的讀寫沒有全程持鎖（單人使用實務上沒問題，多人並發改資料集時要補）。

### 已知限制

- **多 GPU（`device="0,1"`）沒有驗證過。** ultralytics 的 DDP 會另起子行程，callback 進度回報與 `trainer.stop` 中止機制在該模式下不保證有效。
- `resume=True` 與網頁上的 `project` / `name` 組合要自己確認，程式沒有針對 resume 的特別處理。
- `apply_split()` 遇到目標資料夾同名檔會**略過**（記在 `conflicts`），不會覆蓋；`dryRun=true` 可先預覽會搬幾個檔。搬移完會清 `_cache` 與 `*.cache`。
- `Dataset._cache` 超過 8000 筆直接整個清空（不是 LRU）。
- 影片轉檔的檔名續編是掃描現有純數字檔名；混入非數字檔名的資料集不會出錯，但那些檔案不會納入計算。
- 標註頁一次只載入一張影像，`/api/list` 的每一項都要 `read_shapes()` 才能算物件數 — 資料集非常大時第一次列表會慢（之後靠 `_cache` 命中）。

### 想抽哪一塊來用

| 想要的東西 | 抽這些檔案 | 額外要處理的 |
| --- | --- | --- |
| 純標註網頁 | `labelServer.py` + `web/` | 拿掉 `/api/video/*`、`/api/train/*` 路由與對應頁面即可；標註功能完全不依賴 torch |
| 背景訓練 + 進度查詢 | `trainJob.py` | 改 `DEFAULTS` 的路徑；`task="segment"` 換成你的任務；自己接一層 HTTP 或其他 IPC |
| 自動標註 | `videoDataset.py` + `yoloSegByteTrack.py` | 兩者耦合較深（用了 `FramePrep`、`_border_hit_mask`、`_poly_and_centroid`、`_reset_trackers`、`_precision_kwargs`、`_normalize_names`、`_g_model`），要一起搬 |
| MJPEG 預覽機制 | `videoDataset.py` 的 `viewer_enter/exit`、`wait_preview`、`_publish_preview` + `labelServer._mjpeg` | 這段是通用的，換個影像來源就能用 |
| 「單例背景工作 + 增量 log 輪詢」樣板 | `trainJob.py` 的 `_state` / `_log` / `get_status` / `start_job` / `stop_job` 五個部件 | 約 100 行，換掉 `_train()` 的內容就是新工作 |

### 預設路徑（移植時一定要改）

散落在三個檔案的模組層常數，全都是這台機器的絕對路徑：

```python
labelServer.DEFAULT_ROOT       = r"D:\TrainingImage\ATD3"
videoDataset.DEFAULT_VIDEO_DIR = r"D:\CaptureVideo"
videoDataset.DEFAULT_OUT_DIR   = r"D:\TrainingImage\FromVideo"
videoDataset.DEFAULT_MODEL     = r"D:\Working Space\Python\VisionStereo\weights\best.pt"
trainJob.DEFAULTS["model"]     = r"...\weights\best.pt"
trainJob.DEFAULTS["project"]   = r"...\weights"
trainJob.DEFAULTS["outputDir"] = r"...\weights\ATD3"
```

---

## 11. 訓練參數清單（`trainJob.DEFAULTS`）

網頁表單的欄位與這份 dict 一一對應（`app.js` 的 `TR_FIELDS`）。伺服器只接受出現在 `DEFAULTS` 裡的 key，其餘忽略。

| 群組 | 參數 | 預設 |
| --- | --- | --- |
| 資料／模型 | `data`（空 = 用目前開啟的資料集）、`model` | — |
| 訓練 | `epochs` 100、`imgsz` 640、`batch` 16、`device` `"0"`、`workers` 8、`patience` 50、`lr0` 0.001、`lrf` 0.01 | |
| 開關 | `amp` True、`cache` False、`resume` False、`savePeriod` -1 | |
| 分割 | `overlapMask` True、`maskRatio` 4、`retinaMasks` False | |
| 輸出 | `project`、`name`、`outputDir` | |
| 增強 | `hsv_h/s/v`、`bgr`、`degrees` 15、`translate` 0.15、`scale` 0.5、`shear` 5、`perspective` 0.0005、`flipud` 0.3、`fliplr` 0.5、`mosaic` 1.0、`close_mosaic` 15、`mixup` 0.1、`copy_paste` 0.3、`copy_paste_mode` `"flip"` | |
| 匯出 | `doExport` True、`exportFormat` `"onnx"`（onnx / torchscript / engine / tflite / coreml）、`exportHalf`、`exportDynamic`、`copyBest` / `copyLast` / `copyExport` | |

影片轉檔的對應清單在 `videoDataset.DEFAULTS`：`imgsz` 640、`conf` 0.4、`minArea` 500、`edgeMargin` 50、`maxDet` 100、`maxPolyPoints` 12、`jpegQuality` 95、`split` `"train"`、`tracker` `"bytetrack.yaml"`，外加常數 `CONSECUTIVE_FRAMES = 2`。
