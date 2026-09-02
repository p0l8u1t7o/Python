# CLAUDE.md — VisionSequence 開發須知

> 給 AI 協作者（Claude Code／Claude Projects）與開發者的單一入口：先讀「專案全貌」建立心智模型，動手前照「工作方式」與「驗證清單」，改到對應模組再看「模組要點」與「踩過的坑」。功能總覽與文件地圖在 `README.md`，細節文件在 `docs/`（HTML）。

## 1. 專案全貌

- **是什麼**：類 VisionMaster 的畫布式工業機器視覺平台。使用者在瀏覽器拉工具節點、畫 ROI、調參看結果；PLC／上位機以 HTTP／TCP／Modbus 觸發並取回 OK/NG 與量測值。
- **技術棧**：Django 5.1 + django-ninja + OpenCV/numpy（後端）；React 19 + Vite + TS + Tailwind v4 + @xyflow/react + TanStack Query + i18next（前端）；SQLite 預設。
- **規模**：61 個內建工具（8 類）、119 個 API 端點、17 個資料模型、17 個前端頁面、15 頁 docs、後端 237 項＋前端 22 項測試；Python 約 17.6k 行、TS 約 21.5k 行。
- **核心概念**：
  - 流程 = `Flow.graph`（JSON：nodes/edges）。工具節點有型別化埠；`_flow` 隱含輸入埠＝控制分支、`_overlays` 隱含輸出埠＝該節點標記、`_image` 隱含直通埠＝每個工具預設可把影像原樣傳出。
  - 引擎是**資料流 DAG**：一次 run 在執行緒池的一條執行緒內以拓樸順序跑完，影像以 numpy 在記憶體傳；overlays 只是顯示層 metadata，不畫進影像。
  - **只能有一個 API 行程**（引擎狀態、影像快取、SSE bus 都在行程內）。`manage.py serve` = uvicorn workers=1 + TCP；`runserver` 只用來開發且加 `--noreload`。
  - 三種身分：使用者（登入 token）、整合方（API 金鑰、永遠可執行、可鎖引擎）、bootstrap（沒有任何使用者時放行 `/auth/setup`）。
- **目錄**：`config/`（settings：`VISION` dict 全部走 .env；`api.py` 掛 Router）、`apps/core`（錯誤、外掛掃描）、`apps/accounts`（身分、鎖定、偏好）、`apps/vision`（models / graph / engine / runner / images / api* / stream / tcp_server / sources / tools / dl / agent / demo）、`apps/comm`（Modbus 等主動輸出）、`apps/golden`（回歸）、`plugins/`（資料夾外掛）、`frontend/`、`tests/`、`docs/`、`scripts/`（dev.ps1／stop.ps1／bench_tools.py）。
- **一次執行的路徑**：觸發 → `Runner.compiled_for`（validate → apply_recipe → compile，快取鍵 `(version, recipe_id, updated_at)`）→ `_prefetch` 在呼叫者執行緒開來源／資產 → 執行緒池 `engine.execute`（`ToolContext.image()` 依 `accepts` 做位深 coerce）→ 影像進 `images.store`、`RunReport` → SSE／統計／背景批次寫 `FlowRun`。
- **前端接縫**：頁面只透過 `lib/api.ts`（`BASE_URL`＝`VITE_API_BASE_URL` 或 `/api`）、`lib/queries.ts`、`lib/flowStream.ts` 與後端往來，不直接 fetch；各頁 lazy chunk；跨頁草稿在 `lib/flowDraft.ts`。
- **文件**：`README.md`（全貌）、`docs/*.html`（使用者手冊、設計手冊、合約、自動化、Modbus、檢測功能、範例樣板、AI 助手、DL、Golden、外掛、名詞規範、效能）。

## 2. 工作方式

### 語言與 Git
- 對話、commit、文件一律繁體中文；程式碼、識別字、術語保持原文。
- **git 根目錄是上一層 `d:\Working Space\Python`**（多專案工作區）。只 `git add` VisionSequence 底下的明確路徑，不要 `git add -A`。
- 一個需求一個 commit；訊息寫清楚做了什麼、為什麼、驗證結果；結尾 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

### 啟動
- `.\scripts\dev.ps1 -Setup` 第一次；`.\scripts\dev.ps1` 之後；`.\scripts\stop.ps1` 停止。從 Bash 工具重啟要包成 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1`（外掛 INFO 日誌走 stderr，PowerShell 工具直跑會誤觸 `$ErrorActionPreference=Stop`）。
- 手動：`manage.py migrate` → `manage.py seed_demo` → `manage.py serve`；前端 `npm run dev`。
- `seed_demo` 建 2 個示範流程＋每個範例樣板一組合成樣本圖（`apps/vision/demo_images.py` → `data/samples/`，folder 來源、群組「範例」）＋範本／良品資產，可重複執行；範例樣板本身在範本畫廊（`demo.BUILTIN_TEMPLATES`，14 個）。`tests/test_demo.py` 逐範本掛上對應樣本來源實跑鎖住。改樣本圖形要刪 `data/samples/<key>/` 重生成。

### 驗證清單（改完就跑，報告附實際結果）
- 後端：`.venv/Scripts/python.exe manage.py test --noinput`、`.venv/Scripts/python.exe -m ruff check apps tests config`。`tests/test_smoke_api.py` 掃所有 GET 端點不 5xx／405——新增 GET 端點記得加進清單。
- 前端：`cd frontend && npm run -s typecheck && npm test && npm run build`。vitest 有：i18n 三語系 key／占位符對齊與**禁用口語詞**檢查、`graphMapping`／`geometry`／`flowDraft` 單元、9 個頁面在假後端下 render smoke。新頁面在 `src/test/pages.test.tsx` 加 case，新 API 路徑在 `src/test/apiMock.ts` 補假資料。
- 改了頁面就開瀏覽器看一眼（影像檢視器與畫布的問題肉眼最快）；改了服務端要重啟後 curl 一次（api 401＝需登入是正常、front 200）。
- 改動**優化過的函式**（blob 預濾、`_roi_hist`、`find_edges_rows`、`caliper_points`、`apply_mask`、`mask_for`、RANSAC 向量化、template_match 金字塔）必須重跑等價性檢查（`scripts/bench_tools.py`），不能只看測試綠。

### 紅線
- 不重寫引擎、不改 graph JSON 格式、不把 `Flow.graph` 搬出資料庫、不引入 Node.js 服務／微服務、不開第二個 API 行程。
- 使用者可見文案不得出現技術來源字樣（NI Vision／OpenCV／cv2）；`plugins.html` 程式碼範例的 import 是例外。

### 文件與命名
- **`docs/` 下只放 HTML**（每頁內嵌同一段 CSS、無外部依賴）；新文件也要 HTML，並在 `docs/index.html` 加連結、各頁 `nav.site` 同步。改了行為要同步更新對應的 docs 頁、`README.md` 與本檔。
- UI 文案、元件名、i18n key 一律照 `docs/glossary.html`；新名詞先加表再用。**商用產品語氣**：「點選」不用「點一下」、「試執行」不用「試跑」、「尚無／無法／此」不用「還沒有／不能／這個」、稱呼使用者用「您」；範例提示詞除外。`src/test/i18n.test.ts` 有禁用詞清單會擋。
- 語系：zh-Hant（完整、fallback）、zh-Hans（由 zh-Hant 轉出＋詞彙微調；改文案後同步）、en（部分）。三語系 key 必須對齊（測試會擋）。

## 3. 模組要點

### 工具框架（apps/vision/tools）
- 繼承 `Tool`，宣告 `params`（kind 只能是 `PARAM_KINDS`）、`inputs`、`outputs`（type 只能是 `PORT_TYPES`），`execute(ctx) -> Result`。內建放進對應 builtin 模組的 `TOOLS`。
- 找不到東西回 `status="ng"` 或分支，不要 `raise`；可預期失敗 `raise ToolError(...)`。overlays 座標一律是**該節點輸入影像**的全圖座標；ROI 用 `tools/roi.py` 的 `crop()` 與 `Crop.to_full()`。**overlays 不得畫進影像、不得就地修改輸入 ndarray**（`tests/test_tools.py ToolPurityTests` 全工具掃描鎖住）。
- 影像位深：工具預設只吃 u8（其他自動正規化）；cv2 原生支援 u16/f32 的工具宣告 `accepts = ("u8","u16","f32")`（`imgfmt.py`）。
- 新增工具 checklist：`register()`（放進模組 `TOOLS`）→ `tests/test_tools.py` 至少一案例 → `scripts/bench_tools.py` 加一筆 → 現場調的參數標 `teach=True` → `agent/skills/tools.md` 補一段要領 → 需要的話加進範例樣板。前端不用改。
- 新增 `Param.kind` 或 `Port.type`：後端封閉集合、前端 `ParamField` switch、`catalogue()`、`docs/contract.html`、`docs/glossary.html` 五處同步。新增 ROI 形狀＝`tools/roi.py` 各 helper＋前端 `types.ts Region`／`roiEditor.ts`／`geometry.ts` 的 switch 同步（typecheck 會抓漏），見 docs/vision-capabilities.html。
- 舊工具名（`edges`→`filter`、`hist_eq`→`lut`、`write_plc`→`write_modbus`）由 `graph.LEGACY_TOOL_TYPES` 在 validate／compile 時自動換，參數名刻意相容。

### 資料夾外掛（plugins/）
- 繼承 `Tool`／`Grabber`／`Writer`／`Trainer` 的單檔或資料夾型模組丟進 `plugins/` 即自動掛載（`apps/core/plugins.py`；不用改 .env）。外掛內 `ENABLED`／`enabled`／`label`／`description` 控制掛載與顯示；key／kind 重複時內建優先。外掛依賴附 requirements.txt（`dev.ps1 -Setup` 自動安裝）；Python 版本不一致走 sidecar，見 docs/plugins.html。範例：`plugins/example_dark_ratio.py`、`plugins/example_csv_writer.py`。

### 引擎、Runner、影像快取
- 執行緒池內的熱路徑**不碰資料庫**：來源與資產在 `Runner._prefetch()`（呼叫者執行緒）先開好；連續模式每 2 秒才回 DB 確認一次。
- 配方（`FlowRecipe`）：執行時 `apply_recipe()` 疊參數再編譯；`run`／`preview`／TCP `recipe=` 都可指定，未指定用預設配方。每筆 run 帶 `station_id`（`VISION_STATION_ID`）；未 `commissioned` 的流程只加 warnings 不阻擋。
- 影像快取 `images.ImageStore`：每流程保留最近 N 次 run 的影像（`KEEP_RUN_IMAGES`）；**暫存影像上傳與 AI 助手影像用 `store.put(..., pinned=True)`**，不佔 run 輪替名額（否則工具頁試執行 N+1 次就把暫存影像擠掉）；總量 LRU。engine 會把節點影像輸出自動放進 store（ref＝`{run_id}:{node}:{port}`）。
- viewer 規則：執行前（mode='input'）一律不疊 overlays；無影像輸出的工具只在 output-fallback 時疊標記；`firstImageOutput`／`lastImage` 忽略 `_image`。

### API 與帳號（apps/accounts、apps/vision/api*）
- 身分在 `security.py`：`Principal(kind=integrator|user|bootstrap)`；`request.auth` 就是它。執行類端點（run／preview／continuous／agent）都要 `principal(request).can_execute()`（鎖定時 423）；修改類端點用 `_editable_flow()`（擁有者或管理員）；讀取用 `_visible_flows()`。新增端點照這三個接縫。
- 鎖是 `EngineLock` 單列（id=1）；鎖定時停掉所有連續執行並發 SSE `lock` 事件。測試裡預設沒有使用者 → bootstrap 放行；要測 401 先建一個 User；要以使用者身分測就 `POST /auth/setup` 拿 token 帶 `Authorization: Bearer`。
- ninja 路由依註冊順序比對：固定路徑（`/flows/import`、`/assets/from-image`）要註冊在 `/{id}` 之前。`APIKeyHeader` 要實作 `authenticate(request, key)`；金鑰選填時覆寫 `__call__` 直接放行。
- `UserPref`（OneToOne auth.User）：`ui`（主題等；`PATCH /auth/prefs`、`/auth/me` 帶回）、`agent`（AI 供應商設定，金鑰只在伺服器、API 只回尾 4 碼、不進 `/auth/me`）。主題是封閉集合（後端 `UI_THEMES`＝前端 `THEMES`＋index.html 開機腳本三處同步）；新主題＝index.css 加 `.theme-<id>` 變數覆蓋。
- 資源群組 `ResourceGroup(kind=source|asset)`；範例來源／資產在群組「範例」。

### 範本與範例（demo.py、api_more.py）
- 內建範本目錄 `demo.BUILTIN_TEMPLATES`（key、名稱、說明、分類、builder）；builder 在 request 時呼叫，範例資產 id 由 `_demo_asset` 現查；`api_more._builtin_templates` 快取 30 秒。範本以 `{SOURCE}` 佔位，instantiate 時換來源並可加節點 id 前綴。
- `TEMPLATE_SAMPLE_SOURCES` 映射 builtin key → 範例來源名稱（測試與文件用）。`test_more` 對深度樣板在空白圖上 failed 視為預期，能跑的職責在 `test_demo`。

### AI 助手（apps/vision/agent）
- 上傳影像＋圈 ROI＋提示詞 → 生成標準 graph 並在該影像實跑（`service.generate/refine`、`/vision/agent/*`、前端 `/agent`）。
- 兩層供應器：`intents.py`＋`synth.py` 離線規則引擎（意圖封閉集合，特異性排序；`Intent.polarity` 可由提示詞／問答覆寫極性）；`providers.py` 多供應商（claude 走 anthropic SDK 延後 import；openai／gemini 走 urllib REST 零依賴；`GENERATE_TIMEOUT` 120s／`TEST_TIMEOUT` 15s；`_explain` 把供應商例外翻成原因，404 會帶出供應商建議的替代模型名）＋`llm.py` 四種任務（generate／refine／edit／tune）＋`llm.clarify`。設定解析 `providers.resolve(user)`：使用者自己的 `UserPref.agent` → .env（`VISION_AGENT_PROVIDER/API_KEY/MODEL`）→ offline；LLM 失敗自動落回規則。兩邊產物都過 `validate_graph`＋`trial_run`（engine.execute 直跑、flow_id=0、不佔執行緒池、不落 DB；多張影像各跑一次回 `reports`）。
- 詢問機制 `clarify.py`：生成前 `/agent/clarify` 依意圖找關鍵缺口提問（最多 3 題，choice／number／text／roi，可 optional；問過的不重問，全部問完即 ready）；answers 以補充句併回提示詞（`service.effective_prompt`），規則與 LLM 讀同一份；generate 回 `warnings`（未回答的缺口用了預設值）。前端所有助手呼叫帶 AbortController（中斷鍵）。
- 多圖＋ROI 編號（ROI01…，regions[i].image 指影像索引；「ROI01 是好品、ROI02 是壞品」→ golden 意圖，好品 ROI 自動裁成資產）。編輯器右側「AI」分頁走 `/agent/edit`（離線句型見 `service.edit_rules`）；批次測試「請 AI 調整」走 `/agent/tune`（同批影像重跑回前後對比）。
- AI 代理技能在 `agent/skills/`（platform.md 平台規則、design.md 設計原則含謹慎原則、tools.md 每工具要領 `## <type>` 分段）；`skills.py` 組裝：system＝規則＋原則＋精簡目錄（穩定可快取），相關工具完整技能（自動骨架＋要領）由 `select_tools` 挑進 user 訊息。**新增工具要在 tools.md 補一段要領**。
- 供應商設定存完會打 `providers.test_connection` 驗證並回原因；`list_models` 列金鑰可用模型。新增意圖＝`INTENT_KINDS`＋`intents.parse` 規則＋`synth.SYNTHESIZERS` 合成器＋`clarify.build_questions` 缺口問題＋`tests/test_agent.py` 案例。規則式微調映射在 `service.refine_rules`。詳見 docs/agent.html。

### 深度學習教導（apps/vision/dl）
- `Trainer` registry（base.py）：kind／label_mode（封閉集合：classes｜shapes）／params（沿用 Param）／devices，實作 `train()`（回 ONNX bytes＋tool_params）與 `suggest()`（自動標記）。內建：`mlp_classify`、`patch_segment`（手刻 ONNX 給 dl_segment）、`yolo_seg`（torch/ultralytics **可選安裝、延後 import**，缺件時提示 pip 指令；產物給 `dl_instance`）。外掛 trainer 丟 `plugins/` 即掛載，前端 UI 由 `/dl/trainers` 目錄驅動。
- shapes 標記存 DlSample.shapes（0~1 正規化），`shapes.py` 與 YOLO txt 互轉；`dataset-export`／`dataset-import` 雙向互通。訓練跑背景執行緒（jobs.py，單一訓練槽、409 擋第二個），前端輪詢 `/dl/train/status`。產物存 kind=model 資產。
- 推論 providers 是熱路徑設定：工具只讀 `devices.preferred_providers()`（記憶體）；`PATCH /dl/settings` 寫 DB＋更新快取＋`clear_sessions()`；裝置資訊 `GET /dl/devices`。
- 資料集：樣本以解碼後像素 SHA256 去重；`DlSample.split`（train/val/test）；`DlDatasetVersion` 凍結成 zip 資產。SAM 智慧選取（`sam.py`）：`mobile_sam.pt` 經 `yolo.resolve_model` 自動下載，session 模組層快取＋鎖。樣本影像在 `ASSET_DIR/dl/<project_id>/`；訓練執行緒自己開 DB 連線、結束 `close_old_connections()`。詳見 docs/dl.html。

### 前端
- 工具箱：`FavoriteTools`（新增工具／新增註解／收藏，hover 可移除）＋`ToolPicker`（Modal 固定高、內部捲動）。畫布 ⇄ graph 的轉換在 `graphMapping.ts`；note 是裝飾節點（type=note，不接邊）。
- 工具頁 `ToolPage`：參數改在草稿（`flowDraft.patchDraftNode`），儲存才寫回；`goBack` 只在 dirty 時比對快照；輸出值只列在下方參考資訊，不疊浮層擋圖。
- 影像檢視器：`roiEditor.ts`（互動）與 `geometry.ts`（純函式，有單元測試）分離；ROI 形狀 switch 要 exhaustive。
- 版面：一般頁面用 `Page` 容器（`AppShell.tsx`）取得一致內距；全高頁（編輯器、參數卡）自帶 header。

## 4. 踩過的坑
- Django `TestCase` 的交易會鎖住 SQLite，跨執行緒（執行緒池、背景持久化）會 `database table is locked`：測試 DB 是**檔案 + WAL**，跨執行緒寫入的測試用 `TransactionTestCase`；會啟動背景持久化的測試用 `override_settings(VISION={**VISION, "PERSIST_RUNS": False})`，否則 teardown 刪 DB 檔會 WinError 32。
- `threading.Thread` 子類別**不要用 `_started`／`_stop` 當屬性名**（會蓋掉 Thread 內部欄位）。
- `IntegrityError` 要包在 `transaction.atomic()` 內再 catch，否則在測試交易裡會變 `TransactionManagementError`。`close_old_connections()` 只在「自己執行緒」結束時呼叫。
- SSE 串流測試帶 `?max_seconds=0.2`，不然測試 client 會把 55 秒的串流讀完。
- Windows 中文路徑：讀圖用 `np.fromfile` + `cv2.imdecode`，寫圖用 `imencode` + `tofile`。console 輸出含特殊符號時設 `PYTHONIOENCODING=utf-8`。
- **Git Bash heredoc 會吞反斜線**（`"\n"` 變真換行）且長內容會被截斷（unexpected EOF）：長內容、含反斜線或 TSX 的檔案一律用 Write 工具寫檔，再用 Bash 執行 patch 腳本。`.ps1` 保留 UTF-8 BOM。
- Vite dev server 的 `/api` 代理與直打後端行為一致；LLM 供應商 hang 時不會拖垮平台（uvicorn 執行緒池），但要給短逾時。
- 前端 `max-h` 擋不住 CSS grid 內容溢出：Modal 內部要捲動就用固定高 `h-[..]` + `min-h-0` + `overflow-hidden`，捲動容器留內距免得 hover 邊框被裁。
- i18n：一次多檔替換若中途失敗要檢查已成功的檔案，避免重複插入（TS1117）；en 是單行物件格式，錨點與 zh 不同。
