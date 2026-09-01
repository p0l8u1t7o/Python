# VisionSequence — 工業機器視覺流程平台

類 Hikrobot VisionMaster 的畫布式機器視覺平台：自動化人員在瀏覽器裡拉工具節點、在影像上畫 ROI、
調參數即時看結果，再以 HTTP / TCP 讓 Modbus TCP 設備或上位機觸發檢測並取回 OK/NG 與量測值。

- 後端：Django 5.1 + django-ninja + OpenCV / numpy（可選 onnxruntime 深度學習推論）
- 前端：React 19 + Vite + TypeScript + Tailwind v4 + React Flow
- 執行：行程內資料流引擎，執行緒池預設 **10 個流程並行**（`VISION_MAX_WORKERS` 可擴充），
  單節點 0.1 ms 等級、影像全程以 numpy 在記憶體傳遞、只有被檢視時才編碼縮圖

## 快速開始（Windows）

```powershell
.\scripts\dev.ps1 -Setup     # 第一次：建 .venv、安裝、migrate、示範資料、npm install
.\scripts\dev.ps1            # 之後：啟動後端（HTTP 8000 + TCP 9000）與前端 5173
.\scripts\stop.ps1
```

手動：
```bash
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo          # 合成影像來源 + 兩個示範流程
.venv/Scripts/python.exe manage.py serve              # uvicorn :8000 + TCP :9000（同一行程）
cd frontend && npm run dev                            # http://127.0.0.1:5173
```
API 文件：http://127.0.0.1:8000/api/docs

## 功能

| 區塊 | 內容 |
|---|---|
| 流程編輯器 | 工具調色盤（依類別／搜尋）、資料流畫布（型別化埠、分支把手）、參數表單由工具目錄自動產生、大尺寸影像檢視器（縮放／平移／像素值／overlay／ROI 繪製與把手編輯）、試跑（未存檔的圖、可固定同一張影像調參）、執行一次、連續執行、復原／複製貼上／自動排列 |
| 內建工具 | 影像來源、前處理（灰階、裁切、平滑、二值化、形態學、縮放、色彩、對比、運算、邊緣、旋轉）、定位（範本比對、定位補正、ROI 跟隨、找圓、找線、Hough）、量測（卡尺、距離、角度、灰階統計、校正、直方圖）、檢測（Blob、差異缺陷、條碼／QR、色彩、邊緣密度、像素計數）、深度學習（ONNX 分類／偵測／分割）、邏輯（數值／範圍判斷、布林、公式、計數）、輸出（OK/NG 判定、具名輸出、存檔、結果影像） |
| 影像來源 | 資料夾循環、單檔、USB 相機、合成測試影像、API 送圖、外掛（GigE 等以 `module:Class` 註冊） |
| 自動化介面 | `POST /api/vision/flows/{id}/run`（同步回 JSON，可附影像）、TCP 一行指令 `RUN <flow>` 回一行 JSON、SSE 即時事件 |
| 執行記錄 | 記憶體保留最近 N 次含影像；資料庫由背景執行緒批次寫入摘要（可關） |
| 擴充 | 新工具：繼承 `Tool` 並 `register()`（或放 `VISION_TOOL_PLUGINS` 模組）；前端零修改 |

## 開發計畫 v0.2 已落地的項目

- **參數卡**（`/flows/:id/teach`）：只列 `teach=True` 的現場參數、改動即時試跑到該步驟、標記「已教導」（未教導的流程執行時帶 warnings）
- **配方**：同一流程多組參數覆寫（換線），`POST run` 帶 `recipe`、TCP `RUN 1 recipe=partA`
- **Golden Set 回歸**：案例＋期望值、基準比對列出 regressed、`manage.py regress <flow> --fail-under 0.98` 可進 CI
- **流程匯出／匯入**：`manage.py flow export|import|run`，穩定序列化可進 git
- **站台識別** `VISION_STATION_ID` 寫進每筆執行紀錄與回傳
- **Modbus 主動輸出**：連線（Modbus TCP／TCP 文字／模擬 DIO／外掛）＋ `write_modbus` 工具，失敗降級不停線
- **深度學習教導**（`/dl`）：平台內標記（自動標記加速）、伺服端訓練（GPU／provider 資訊與選擇）、模型匯出到資產直接給 `dl_classify` 用；模型種類（Trainer）可用外掛擴充、UI 共用
- **資料夾外掛**：繼承 Tool／Grabber／Writer 的 .py 丟進 `plugins/` 自動偵測掛載（不用改 .env），外掛內變數控制名稱／說明／是否掛載
- **量測工具**：fit_arc、fit_ellipse、wall_thickness、concentricity、chamfer_angle、tolerance_judge（保留標稱值與公差來源）＋「深抽杯件量測」範本
- 尚未做：標定子系統、GenICam 內建來源、C 級（零樣本異常、少樣本訓練、GPU、LLM 生成流程）

## 文件

- `docs/index.html` — 文件總覽（docs/ 一律 HTML）
- `docs/architecture.html` — 設計手冊（資料模型、工具框架、引擎、Runner、API、前端、踩過的坑）
- `docs/automation.html` — 設備 / 上位機整合（HTTP、TCP、SSE、回傳格式）
- `docs/golden.html` — Golden Set 回歸與流程匯出入
- `docs/modbus.html` — Modbus 主動輸出（連線、位址、mapping、降級）
- `docs/performance.html` — 效能報告
- `docs/dl.html` — 深度學習教導（標記、自動標記、訓練、裝置設定、Trainer 擴充）
- `docs/plugins.html` — 擴充外掛（資料夾丟檔即掛載：工具／影像來源／整合輸出）
- `docs/contract.html` — 前後端資料合約
- `docs/glossary.html` — 前端名詞與命名規範（頁面、區塊、埠顏色、狀態用語）
- `CLAUDE.md` — 開發須知與驗證清單

## 驗證

```bash
.venv/Scripts/python.exe manage.py test --noinput
.venv/Scripts/python.exe -m ruff check apps tests config
cd frontend && npm run -s typecheck && npm run build
```

## 帳號與鎖定

- 第一次開啟前端會要求建立管理員（或 `manage.py create_admin admin --password ...`）。管理員可在「使用者」頁新增帳號；每位使用者各自擁有流程（含每個節點的參數設定），共用流程只有管理員能改、其他人可複製。
- 整合方（API 金鑰）可 `POST /api/vision/lock` 鎖定引擎：其他人只能編輯不能執行，直到 `DELETE /api/vision/lock`。細節見 `docs/automation.html` 第 5 節。
