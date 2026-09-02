# CLAUDE.md — VisionSequence 開發須知

## 回覆與文件語言
- 對話、commit、文件一律繁體中文；程式碼、識別字、術語保持原文。

## Git
- **git 根目錄是上一層 `d:\Working Space\Python`**。只 `git add` VisionSequence 底下的明確路徑，不要 `git add -A`。
- 一個需求一個 commit，結尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## 專案形狀
- `config/`（settings：`VISION` dict 全部走 .env）、`apps/vision/`（models / graph / engine / runner / images / api / stream / tcp_server / sources / tools / dl）、`apps/comm/`（Modbus TCP／上位機主動輸出）、`plugins/`（資料夾外掛）、`frontend/`（Vite + React 19 + Tailwind v4 + @xyflow/react）、`tests/`、`docs/`。
- 引擎是**資料流 DAG**（不是 ZQS 的 DB token stepper）：一次 run 在執行緒池的一條執行緒內以拓樸順序跑完，影像用 numpy 在記憶體傳。`_flow` 隱含輸入埠 = 控制分支；`_overlays` 隱含輸出埠 = 該節點標記；`_image` 隱含直通埠 = 每個工具預設可把影像傳進（無 image 輸入者）、傳出（原樣，引擎在 execute 後發值；宣告輸出之後登記）。
- **只能有一個 API 行程**（引擎狀態、影像快取、SSE bus 都在行程內）。`manage.py serve` = uvicorn workers=1 + TCP。`runserver` 只用來開發（且加 `--noreload`，否則工具外掛與執行緒池會被重載兩次）。

## 啟動
- `.\scripts\dev.ps1 -Setup` 第一次；`.\scripts\dev.ps1` 之後；`.\scripts\stop.ps1` 停止。
- 手動：`manage.py migrate` → `manage.py seed_demo` → `manage.py serve`；前端 `npm run dev`。

## 驗證清單（改完就跑，報告附實際結果）
- 後端：`.venv/Scripts/python.exe manage.py test --noinput`、`.venv/Scripts/python.exe -m ruff check apps tests config`。
- 前端：`cd frontend && npm run -s typecheck && npm run build`。
- 改了頁面就開瀏覽器看一眼（影像檢視器與畫布的問題肉眼最快）。

## 踩過的坑
- Django `TestCase` 的交易會鎖住 SQLite，跨執行緒（執行緒池、背景持久化）會 `database table is locked`：測試 DB 已改為**檔案 + WAL**（`DATABASES.default.TEST`），跨執行緒寫入的測試用 `TransactionTestCase`。
- `threading.Thread` 子類別**不要用 `_started`／`_stop` 當屬性名**（會蓋掉 Thread 內部欄位，症狀是 `'bool' object has no attribute 'is_set'`／`'Event' object is not callable`）。
- ninja `APIKeyHeader` 要實作 `authenticate(request, key)`；金鑰選填時覆寫 `__call__` 直接放行。
- 執行緒池內的熱路徑**不碰資料庫**：來源與資產在 `Runner._prefetch()`（呼叫者執行緒）先開好；連續模式每 2 秒才回 DB 確認一次。
- `IntegrityError` 要包在 `transaction.atomic()` 內再 catch，否則在測試交易裡會變 `TransactionManagementError`。
- `close_old_connections()` 只在「自己執行緒」結束時呼叫；在共用執行緒（測試 client 直接呼叫 `handle_command`）呼叫會把主連線關掉。
- SSE 串流測試帶 `?max_seconds=0.2`，不然測試 client 會把 55 秒的串流讀完。
- Windows 中文路徑：讀圖用 `np.fromfile` + `cv2.imdecode`，寫圖用 `imencode` + `tofile`。
- Git Bash heredoc 會吞反斜線；長內容用 Write 寫檔。`.ps1` 保留 UTF-8 BOM。

## 新增工具與外掛
- 繼承 `apps.vision.tools.base.Tool`，宣告 `params`（kind 只能是 `PARAM_KINDS`）、`inputs`、`outputs`（type 只能是 `PORT_TYPES`），`execute(ctx) -> Result`。內建放進對應 builtin 模組的 `TOOLS`。
- **資料夾外掛**：繼承 `Tool`／`Grabber`／`Writer` 的單檔（`plugins/x.py`）或資料夾型（`plugins/x/__init__.py`）丟進 `plugins/` 即自動掛載（`apps/core/plugins.py`；不用改 .env）。外掛內 `ENABLED`（模組層）／`enabled`／`label`／`description`（類別層）控制掛載與顯示；key／kind 重複時內建優先。外掛依賴附 requirements.txt（`dev.ps1 -Setup` 自動安裝）；Python 版本不一致走 sidecar，見 docs/plugins.html「整合考量」。範例：`plugins/example_dark_ratio.py`、`plugins/example_csv_writer.py`。
- 找不到東西回 `status="ng"` 或分支，不要 `raise`；可預期失敗 `raise ToolError(...)`。overlays 座標一律是**該節點輸入影像**的全圖座標；ROI 用 `tools/roi.py` 的 `crop()` 與 `Crop.to_full()`。**overlays 只是顯示層 metadata——不得畫進影像、不得就地修改輸入 ndarray**（下游工具的檢測不受標記影響；`tests/test_tools.py ToolPurityTests` 全工具掃描鎖住這條）。
- 前端不用改；想加新的 Param.kind 要同時改 `PARAM_KINDS` 與前端 `ParamField`。

## 深度學習教導（apps/vision/dl）
- `Trainer` registry（base.py）：kind／label_mode（封閉集合：classes｜shapes）／params（沿用 Param）／devices，實作 `train()`（回 ONNX bytes＋tool_params）與 `suggest()`（自動標記）。內建：`mlp_classify`（分類）、`patch_segment`（輕量語意分割，全卷積手刻 ONNX 給 dl_segment）、`yolo_seg`（實例分割；torch/ultralytics **可選安裝、延後 import**，缺件訓練時提示 pip 指令；產物給新工具 `dl_instance`）。外掛 trainer 丟 `plugins/` 即掛載，前端 UI 由 `/dl/trainers` 目錄驅動、共用。
- shapes 標記存 DlSample.shapes（0~1 正規化），`shapes.py` 與 YOLO txt 互轉（TAB/LF，相容 VisionStereo）；`dataset-export`／`dataset-import` API 雙向互通。訓練 job 帶 history 曲線與 log 環形緩衝（`?log_from=`）。
- 訓練跑背景執行緒（jobs.py，單一訓練槽、409 擋第二個），不占檢測執行緒池；前端輪詢 `/dl/train/status`。產物存成 kind=model 資產，`dl_classify` 直接用（前處理與工具預設一致）。
- 推論 providers 是熱路徑設定：工具只讀 `devices.preferred_providers()`（記憶體）；`PATCH /dl/settings` 寫 DB＋更新快取＋`clear_sessions()`。
- 資料集管理：樣本以**解碼後像素 SHA256** 去重（上傳／zip 批次／連抓／匯入都回報 duplicates）；`DlSample.split`（train/val/test，`POST /split` 分層自動分派；val=驗證集、test 不進訓練）；`DlDatasetVersion` 凍結成 zip 資產（kind=dataset，shapes=YOLO 樹、classes=類別資料夾＋manifest）。
- SAM 智慧選取（`sam.py`）：標記編輯器點一下物件→polygon 掛目前類別；`mobile_sam.pt` 經 `yolo.resolve_model` 自動下載（`_ASSET_NAME` 白名單含 SAM 系列）、與 yolo_seg 同一套可選依賴；session 模組層快取＋鎖。增強參數放「增強」群組（預設關：內建=翻轉＋亮度、yolo=degrees/fliplr/mosaic）。
- 樣本影像在 `ASSET_DIR/dl/<project_id>/`；訓練執行緒自己開 DB 連線、結束 `close_old_connections()`。詳見 docs/dl.html。

## 文件
- **`docs/` 下只放 HTML**（每頁內嵌同一段 CSS、無外部依賴）；新文件也要 HTML，並在 `docs/index.html` 加連結。改了行為要同步更新對應的 docs 頁與 `CLAUDE.md`。

## 前端命名
- UI 文案、元件名、i18n key 一律照 `docs/glossary.html`；新名詞先加表再用。
- 語系：zh-Hant（完整、fallback）、zh-Hans（OpenCC tw2sp 由 zh-Hant 轉出＋詞彙微調「缺省→默认」；改文案後記得重轉或同步）、en（部分）。

## 帳號與鎖定（apps/accounts）
- 身分在 `security.py`：`Principal(kind=integrator|user|bootstrap)`；`request.auth` 就是它。整合方 = API 金鑰、永遠可執行；沒有任何使用者時放行 bootstrap 讓 `/auth/setup` 能建帳號。
- 執行類端點（run／preview／continuous）都要 `principal(request).can_execute()`（鎖定時 423）；修改類端點用 `_editable_flow()`（擁有者或管理員）；讀取用 `_visible_flows()`。新增端點時照這三個接縫。
- 鎖是 `EngineLock` 單列（id=1）；鎖定時會停掉所有連續執行並發 SSE `lock` 事件。
- 測試裡預設沒有使用者 → bootstrap 放行；要測 401 先建一個 User。
- 使用者介面偏好在 `UserPref`（OneToOne auth.User；`PATCH /auth/prefs`、`/auth/me` 帶回 prefs）。主題風格是封閉集合（後端 `UI_THEMES`＝前端 ThemeProvider `THEMES`＋index.html 開機腳本三處同步）；新主題＝index.css 加 `.theme-<id>` 變數覆蓋（顏色/圓角/陰影/字體 tokens 都可換）。

## 開發計畫 v0.2 的規則（visionsequence-plan-v0.2.md）
- 新增工具 checklist：`register()`（放進模組 `TOOLS`）→ `tests/test_tools.py` 至少一案例 → `scripts/bench_tools.py` 加一筆 → 需要現場調的參數標 `teach=True`。
- **改動優化過的函式**（blob 預濾、`_roi_hist`、`find_edges_rows`、`caliper_points`、`apply_mask`、`mask_for`、RANSAC 向量化、template_match 金字塔）必須重跑等價性檢查，不能只看測試綠。
- 新增 `Param.kind` 或 `Port.type`：後端封閉集合、前端 `ParamField` switch、`catalogue()`、`docs/contract.html`、`docs/glossary.html` 五處同步。
- 影像位深：工具預設只吃 u8（其他自動正規化）；cv2 原生支援 u16/f32 的工具宣告 `accepts = ("u8","u16","f32")`。新增 ROI 形狀＝`tools/roi.py` 各 helper＋前端 `types.ts Region`／`roiEditor.ts`／`geometry.ts` 的 switch 同步（typecheck 會抓漏），見 docs/ni-vision.html。
- 紅線：不重寫引擎、不改 graph JSON 格式、不把 `Flow.graph` 搬出資料庫、不引入 Node.js／微服務。
- 配方（`FlowRecipe`）：執行時 `apply_recipe()` 疊參數再編譯，編譯快取鍵 `(version, recipe_id, updated_at)`；`run`／`preview`／TCP `recipe=` 都可指定，未指定用預設配方。
- 每筆 run 帶 `station_id`（`VISION_STATION_ID`）；未 `commissioned` 的流程只加 warnings 不阻擋。
