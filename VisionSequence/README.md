# VisionSequence — 工業機器視覺流程平台

> **English summary** — VisionSequence is a browser-based industrial machine-vision platform (Django + django-ninja + OpenCV backend, React 19 + React Flow frontend). Engineers drag tool nodes onto a dataflow canvas, draw ROIs on images, tune parameters with live results, and expose the resulting flow to PLC/MES systems over HTTP, TCP and Modbus. It ships 61 built-in vision tools, a template gallery with synthetic sample images, in-platform deep-learning teaching (labeling → training → ONNX), and an AI assistant that turns "upload image + draw ROI + one sentence" into a runnable inspection flow (offline rule engine or Claude/GPT/Gemini). Single-process runtime, no Node.js services, no microservices. Docs are in `docs/` (HTML, Traditional Chinese); contributor rules live in `CLAUDE.md`.

類 Hikrobot VisionMaster 的畫布式機器視覺平台：自動化人員在瀏覽器裡拉工具節點、在影像上畫 ROI、
調參數即時看結果，再以 HTTP／TCP 讓 PLC、上位機或 MES 觸發檢測並取回 OK/NG 與量測值。

| 項目 | 內容 |
|---|---|
| 後端 | Django 5.1 + django-ninja + OpenCV／numpy／scipy（可選 onnxruntime、torch/ultralytics、anthropic） |
| 前端 | React 19 + Vite + TypeScript + Tailwind v4 + @xyflow/react（React Flow）+ TanStack Query + i18next |
| 執行 | 單一行程：uvicorn（HTTP + SSE）＋ TCP 介面同行程；資料流 DAG 引擎在執行緒池內跑，影像以 numpy 在記憶體傳遞 |
| 規模 | 66 個內建工具、164 個 API 端點、21 個資料模型、18 個前端頁面、16 頁文件、後端 363 項＋前端 46 項自動測試 |

---

## 目錄

1. [快速開始](#快速開始)
2. [功能全貌](#功能全貌)
3. [架構](#架構)
4. [程式碼地圖](#程式碼地圖)
5. [資料模型](#資料模型)
6. [API 一覽](#api-一覽)
7. [執行模型與效能](#執行模型與效能)
8. [擴充點](#擴充點)
9. [設定（.env）](#設定env)
10. [驗證與測試](#驗證與測試)
11. [部署](#部署)
12. [文件地圖](#文件地圖)
13. [尚未實作](#尚未實作)

---

## 快速開始

Windows（PowerShell）：

```powershell
.\scripts\dev.ps1 -Setup     # 第一次：建 .venv、安裝、migrate、seed_demo、npm install
.\scripts\setup_dl.ps1          # 可選：GPU 深度學習依賴（torch cu128＋ultralytics＋onnxruntime-gpu，約 3GB），最後跑 manage.py dl_check 驗證
.\scripts\dev.ps1            # 之後：後端 HTTP 8000 + TCP 9000、前端 5173
.\scripts\stop.ps1
```

手動：

```bash
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo      # 範例來源／樣本圖／資產＋2 個示範流程；範例樣板在範本畫廊
.venv/Scripts/python.exe manage.py serve          # uvicorn :8000 + TCP :9000（同一行程）
cd frontend && npm install && npm run dev         # http://127.0.0.1:5173
```

- 第一次開啟前端會要求建立管理員（或 `manage.py create_admin`）。
- API 文件（OpenAPI）：http://127.0.0.1:8000/api/docs
- 使用者手冊：`docs/user-guide.html`；介面內「說明」頁有精簡版與工具目錄。

---

## 功能全貌

### 流程編輯與執行
- **流程編輯器**（`/flows/:id`）：資料流畫布（型別化埠、控制分支 `_flow`、隱含直通埠 `_image`）、工具選擇視窗（分群／搜尋／收藏）、註解便利貼、復原／複製貼上／自動排列、右側屬性與結果面板；右下角全域 AI 助手可用一句話修改目前畫布並套用。
- **工具頁**（`/flows/:id/tools/:nodeId`）：單一步驟的專屬調參頁——左參數、中「執行前／執行後」影像、下參考資訊（直方圖／統計／輸出值）、右按鍵；ROI 進頁即顯示；參數暫存、儲存才寫回。
- **影像檢視器**：縮放／平移／像素值／標記疊圖；ROI 形狀 rect / rotated_rect / circle / ellipse / annulus（可扇形）/ polygon / polyline / line / point。
- **試執行 vs 執行**：試執行用目前畫布（含未儲存）並保留中間影像；執行一次／連續執行用已儲存版本並寫入紀錄。暫存影像上傳只為試執行，不進來源庫。
- **參數卡**（`/flows/:id/teach`）：只列 `teach=True` 的現場參數、改動即時試執行；標記「已教導」。
- **配方**：同一流程多組參數覆寫（換線），HTTP／TCP 皆可指定。
- **批次測試頁／Golden Set**：獨立頁面選流程、建立影像集（上傳或來源擷取，≤200 張）批量執行並暫存每次逐張結果；標記期望 OK／NG 得命中率與混淆矩陣，洞察卡給建議門檻、輸出分佈與歷次趨勢；調參重跑同一影像集並逐張比較，滿意後寫回流程／存為配方／帶回編輯器；右下角的全域 AI 助手可依資料諮詢或調整、調參面板可自動調參（結果成為新執行）。案例可存入 Golden Set 作回歸基準，`manage.py regress` 可進 CI。
- **統計**（`/flows/:id/stats`）：執行歷史、良率趨勢、每小時 OK/NG。

### 內建工具（61 個，8 類）
| 類別 | 工具 |
|---|---|
| 影像來源（1） | image_source |
| 前處理（16） | grayscale, crop, resize, blur, threshold, morphology, lut, filter, fft_filter, warp_perspective, convert_depth, rotate_flip, color_convert, color_range, apply_mask, arithmetic |
| 定位（7） | template_match, shape_align, fixture_roi, find_circle, find_line, hough_circles, hough_lines |
| 量測（15） | caliper, wall_thickness, fit_arc, fit_ellipse, chamfer_angle, angle, distance, geometry, concentricity, calibration, intensity, histogram, line_profile, color_stats, edge_density |
| 檢測／識別（8） | blob, defect_diff, barcode, text_presence, color_check, pixel_count, dark_ratio（外掛範例）, … |
| 深度學習（9） | dl_classify, dl_detect, dl_segment, dl_instance（ONNX 推論）；yolo_detect, yolo_segment, yolo_classify, yolo_pose, yolo_obb（ultralytics 原生推論，GPU 自動使用，模型選教導產物或官方底模） |
| 邏輯（5） | if_number, in_range, tolerance_judge, bool_logic, formula, count_list |
| 輸出（5） | judge, output, draw_result, save_image, write_modbus |

影像位深：工具預設只吃 8-bit，其餘自動正規化；宣告 `accepts` 的工具可原生處理 16-bit／浮點。詳見 `docs/vision-capabilities.html`。

### 範本畫廊與範例樣板
18 個內建範本（計數、曝光、圓孔量測、邊線夾角、良品比對、織紋瑕疵、前處理教學、多圓幾何、顏色有無、顏色比對、條碼標籤、定位量測、杯件量測…），每個都配合成樣本圖（`data/samples/`，第 4 張刻意 NG）與自動裁切的範本資產；從範本建立流程時選對應「範例：⋯」來源即可直接執行。覆蓋 55/61 個工具。詳見 `docs/samples.html`。

### AI 助手（`/agent`）

- **全域 AI 助手**：每個頁面右下角的聊天視窗，切換頁面不消失（對話存瀏覽器）。一個輸入框依頁面脈絡分流：任何頁面可問平台怎麼用（`agent/help.py` 把 docs 章節與工具技能建成 BM25 索引，LLM 只依片段回答並附 `/docs/` 參考連結，離線回文件節錄）；流程編輯器內直接修改目前畫布並套用（可復原）；批次測試頁選定執行後資料諮詢或依資料調整（結果成為新執行）。模式晶片可強制指定。
- 上傳一張或多張影像 → 圈選 ROI（ROI01、ROI02…各配提示，可引用「ROI01 是好品，ROI02 是壞品」）→ 一句話描述需求 → **先確認再生成**（資訊不足時最多 3 個問題，可略過）→ 生成流程並在每張影像實跑、疊顯標記 → 口語回饋微調 → 存成流程。
- 兩層供應器：離線規則引擎（15 種意圖封閉集合＋合成器＋特徵驅動參數）；可選 LLM（Claude／GPT／Gemini／OpenAI 相容本地端點，每位使用者自己的金鑰只存伺服器），失敗自動落回規則並在 warnings 說明原因。
- **候選方案與自動調參**：規則引擎每次產主要方案＋參數變體，全部在上傳影像上試跑後依「影像標記」（縮圖 OK／NG 或 ROI 提示好品／壞品）打分擇優，可點選切換；有標記時再做小預算自動調參（只動現場調機參數，嚴格變好才採納）。
- **定位補正**：ROI 提示填「定位」或提示詞說位置會變，流程前自動包「範本比對 → 定位補正 → ROI 跟隨」；新增印字有無、兩孔中心距、圖案有無三種意圖。
- **代理模式**（工作模式選「代理模式」）：AI 以動作逐步起草、試跑、修改、驗證流程（背景工作＋步驟時間軸，可中斷、可回答提問後續跑），Claude／GPT／Gemini／本地相容端點皆可；預算用完以目前流程為結果，失敗自動退回單次生成與規則引擎。
- **記憶與學習**：每次生成存成工作階段（可還原、可評分、存成流程自動關聯）；標記全中或按讚的案例成為相似影像的參數先驗（候選「沿用過去成功參數」、自動調參首選、LLM 過去案例段）；「AI 技能」視窗可寫站點／個人補充要領，AI 一併讀取。
- 評測基準 `manage.py agent_bench`（21 個離線案例：意圖／判定／有效率），`tests/test_agent_bench.py` 守門檻。
- 全域 AI 助手在編輯器內可用一句話修改目前流程、在批次測試頁可依結果諮詢與調整；所有助手呼叫皆可中斷。
- **響應式**：手機寬度側欄改抽屜、麵包屑精簡、表格只留主要欄位、編輯器只留畫布（參數走工具頁）、觸控目標放大；桌面／平板／手機三種寬度與深淺主題都經 Playwright 稽核。
- **視覺設計**：品牌標誌（取景框＋鏡頭）貫穿側欄、登入頁與 favicon；登入頁品牌柔光背景；標題階層、表格動作欄位置、時間格式、空狀態與 toast 位置全站一致。
- **上手引導**：流程還沒選影像來源時編輯器直接給下拉選；總覽卡一鍵「執行一次」；教導完成一鍵建立使用該模型的流程；批次影像集建立即跑第一次；工具頁「改參數即重跑」開關；取像步驟側欄直接選來源並看預覽縮圖；來源表單儲存前可「測試擷取」；離開未儲存的確認改為平台風格對話框。
- AI 代理技能（`apps/vision/agent/skills/*.md`）：平台規則、設計原則、每工具要領，AI 讀的與「AI 技能」視窗看到的是同一份。詳見 `docs/agent.html`。

### 深度學習教導（`/dl`）

- **YOLO 訓練（四種）**：物件偵測（bbox）、實例分割（polygon）、影像分類（classes）、旋轉框 OBB（polygon 取最小外接旋轉矩形）；ultralytics 訓練、進度／曲線／log 回報、可中止；產物 best.pt（主，給 yolo_* 工具）＋ONNX（副，給 dl_* 工具）兩個資產。
- **SAM2 智慧標記**：點擊（正／負點）、拖曳框選、沒有模型時的「SAM 全圖提案」；權重 `VISION_SAM_MODEL`（預設 sam2.1_t.pt）自動下載，失敗退回 mobile_sam。
- **依賴**：`requirements-dl.txt`＋`scripts/setup_dl.ps1`（先 torch cu128 再 ultralytics；onnxruntime-gpu 鎖 1.22 配 CUDA 12）＋`manage.py dl_check --predict` 驗證；踩坑清單見 docs/dl.html §11。
教導專案 → 樣本（上傳／zip／從來源連抓／匯入資料集，像素 SHA256 去重）→ 標記（分類點選；分割多邊形／矩形，SAM 智慧選取，自動標記）→ train/val/test 分割與資料集版本凍結 → 伺服端訓練（內建分類／輕量語意分割；YOLO-seg 選裝 ultralytics；曲線與 log、可中止）→ 模型匯出到資產庫給 DL 工具使用。詳見 `docs/dl.html`。

### 影像來源與資產
相機（USB、GigE 外掛）、資料夾（循環）、單檔、上傳、合成影像；folder／file 可用伺服器檔案瀏覽器選路徑，USB 可掃描相機。資產：範本影像、ONNX 模型、資料集 zip。兩者皆可群組分類。

### 自動化整合
- HTTP：`POST /api/vision/flows/{id}/run`（可附影像、指定配方、同步／非同步）。
- TCP：一行指令 `RUN <flow> [recipe=…]` 回一行 JSON（同行程）。
- SSE：即時事件串流；總覽頁可觀看任一流程的即時影像與結果。
- Modbus TCP／TCP 文字／模擬 DIO 主動輸出（`write_modbus` 工具，失敗降級不停線）。
- 引擎鎖定：整合方以 API 金鑰鎖定，使用者只能編輯不能執行。詳見 `docs/automation.html`、`docs/modbus.html`。

### 帳號、介面與文件
- 管理員／一般使用者／整合方（API 金鑰）三種身分；流程有擁有者；每人各自的介面偏好（主題：淺色／深色／Cyberpunk／跟隨系統；語系：繁中／簡中／英文）。
- 用詞依商用產品規範（`docs/glossary.html`），前端測試自動擋口語詞。
- 文件一律 HTML 在 `docs/`（無外部依賴，可離線閱讀）。

---

## 架構

```
                 瀏覽器（React SPA，lazy 分頁 chunk）
                 └── lib/api.ts (BASE_URL=/api 或 VITE_API_BASE_URL) ── lib/flowStream.ts (SSE)
                          │ HTTP / SSE
┌─────────────────────────┴──────────────────────────────────────────────┐
│ 單一 API 行程（uvicorn workers=1；manage.py serve 同時開 TCP 介面）      │
│                                                                        │
│  config/api.py  ── NinjaAPI，掛載各 app 的 Router                       │
│  apps/accounts  ── 身分（Principal：user / integrator / bootstrap）、鎖定 │
│  apps/vision    ── models / graph（驗證、編譯）/ engine（執行 DAG）        │
│                    runner（執行緒池、compile 快取、背景持久化）           │
│                    images（行程內影像快取，LRU + run 輪替，pinned）       │
│                    stream（SSE bus）/ tcp_server / sources（grabbers）    │
│                    tools/（Tool 框架＋61 內建）/ dl/（教導與訓練）         │
│                    agent/（AI 助手：分析→意圖→合成→試跑；LLM 供應器）      │
│  apps/comm      ── Modbus／TCP 主動輸出（Writer）                         │
│  apps/golden    ── Golden Set 回歸                                        │
│  plugins/       ── 資料夾外掛（Tool／Grabber／Writer／Trainer 自動掛載）   │
└────────────────────────────────────────────────────────────────────────┘
        │ SQLite（預設；DATABASES 可換）    │ data/assets、data/samples（檔案）
```

### 執行路徑（一次檢測）
1. 觸發：HTTP `run`／TCP `RUN`／連續執行／編輯器試執行。
2. `Runner.compiled_for(flow, recipe)`：`validate_graph` → `apply_recipe` → `compile_graph`（快取鍵 `(version, recipe_id, updated_at)`）。
3. `Runner._prefetch()` 在呼叫者執行緒開好來源與資產（熱路徑不碰 DB）。
4. 執行緒池的一條執行緒：`engine.execute()` 依拓樸順序跑每個節點——`ToolContext.image()` 依 `accepts` 做位深 coerce、`_flow` 分支決定是否執行、影像輸出進 `images.store`、overlays 只是顯示層 metadata。
5. `RunReport` → SSE 事件、統計、背景批次寫 `FlowRun`（可關）；前端以 ref 取縮圖。

### AI 助手路徑
上傳影像（pinned 快取）→ `analysis.analyze`（ROI 特徵）→ `clarify`（規則或 LLM 提問）→ `intents.parse`＋`synth.synthesize`（或 `llm.generate`）→ `validate_graph` → `trial_run`（`engine.execute` 直跑、不佔執行緒池、不落 DB）→ 回 graph／rationale／reports／warnings。

---

## 程式碼地圖

### 後端（`apps/`，約 17.6k 行 Python）

| 路徑 | 職責 |
|---|---|
| `config/settings.py` | 全部設定走 `.env`；`VISION` dict 是引擎／快取／外掛／AI 助手的單一設定來源 |
| `config/api.py` | NinjaAPI 根、錯誤格式、各 Router 掛載順序（`/flows/import` 類固定路徑先於 `/flows/{id}`） |
| `apps/core/errors.py` | API 錯誤型別（`ValidationError`／`NotFound`／`Conflict`／`PermissionDenied`…）與統一 JSON |
| `apps/core/plugins.py` | 資料夾外掛掃描與掛載 |
| `apps/accounts/security.py` | `Principal`、`principal(request)`、`can_execute()`（鎖定時 423）、API 金鑰 |
| `apps/accounts/models.py` | `UserPref`（ui 偏好、agent 供應商設定）、`AuthToken`、`EngineLock` |
| `apps/vision/models.py` | `Flow`／`FlowRecipe`／`FlowRun`／`ImageSource`／`FlowTemplate`／`ResourceGroup`／`Asset`／DL 模型群 |
| `apps/vision/graph.py` | graph JSON 驗證（`validate_graph`）、舊工具名映射 `LEGACY_TOOL_TYPES`、編譯 `compile_graph` |
| `apps/vision/engine.py` | DAG 執行、`RunReport`／`NodeReport`、隱含埠（`_flow`／`_overlays`／`_image`） |
| `apps/vision/runner.py` | 執行緒池、每流程 runtime／統計、compile 快取、背景持久化、連續執行 |
| `apps/vision/images.py` | `ImageStore`（LRU、每流程 run 輪替、pinned、編碼快取） |
| `apps/vision/api*.py` | 主 API（flows／sources／assets／groups／fs／runs／preview…）、範本與批次（api_more）、配方（api_recipes）、匯出入（api_flowio） |
| `apps/vision/stream.py`、`tcp_server.py` | SSE bus 與 TCP 一行指令介面 |
| `apps/vision/tools/base.py` | `Tool`／`Param`／`Port`／`ToolContext`／`Result`、封閉集合 `PARAM_KINDS`／`PORT_TYPES`、`catalogue()` |
| `apps/vision/tools/roi.py`、`imgfmt.py` | ROI 全形狀 helper（crop／mask／overlay／transform）、位深轉換 |
| `apps/vision/tools/builtin/*.py` | 內建工具依類別分檔（source／preprocess／locate／measure／detect／logic／output／dl／modbus） |
| `apps/vision/sources/grabbers.py` | 影像來源：folder／file／usb／upload／synthetic／外掛 |
| `apps/vision/dl/` | Trainer registry（`base.py`）、內建 trainer、訓練 job、裝置／provider、SAM、YOLO 互轉、ONNX 輸出 |
| `apps/vision/agent/` | `analysis`／`intents`／`clarify`／`synth`（含候選方案、定位包裝）／`autotune`／`bench`／`llm`／`providers`（含工具呼叫 shim）／`actions`／`loop`／`jobs`（代理模式）／`memory`（工作階段、先驗）／`skills`（含自訂補充）／`service`／`api`＋`skills/*.md` |
| `apps/vision/demo.py`、`demo_images.py` | 範例樣板（`BUILTIN_TEMPLATES`）、合成樣本圖、`seed_demo` |
| `apps/comm/` | 連線模型與 Writer（Modbus TCP／TCP 文字／模擬 DIO／外掛） |
| `apps/golden/` | Golden 案例、基準、回歸 |
| `apps/vision/batch/` | 批次測試：`store`（檔案／序列化／淘汰）、`jobs`（背景執行）、`insights`（洞察與建議門檻）、`api` |
| `apps/vision/management/commands/` | `serve`、`seed_demo`、`flow export|import|run`、`run_tcp_server`、`regress`、`create_admin` |
| `tests/` | 22 個測試模組（引擎、工具純度與位深、API、smoke 掃描、範本實跑、AI 助手、DL、配方、Golden、外掛、通訊…） |

### 前端（`frontend/src/`，約 21.5k 行 TS/TSX）

| 路徑 | 職責 |
|---|---|
| `App.tsx` | 路由（各頁 lazy chunk）、`RequireAuth` |
| `components/layout/` | `AppShell`（側欄／頂列／`Page` 容器）、全域搜尋 |
| `pages/` | Dashboard、Flows、FlowEditor、Tool、Teach、Stats、Golden、Batch、Sources、Assets、Dl、Agent、Integration、Users、Settings、Help、Login |
| `components/editor/` | 畫布（`FlowCanvas`／`ToolNode`／`FlowEdge`）、工具箱與選擇視窗、屬性面板、結果面板、`graphMapping.ts`（graph ⇄ React Flow） |
| `components/viewer/` | `ImageViewer`、`roiEditor.ts`（ROI 互動）、`geometry.ts`（ROI 幾何純函式）、Toolbar |
| `components/templates/`、`recipes/`、`dl/`、`auth/`、`ui/` | 範本畫廊、配方、DL 標記編輯器、登入／鎖定、共用 UI 元件 |
| `lib/api.ts`、`queries.ts`、`flowStream.ts` | 唯一的後端接縫：HTTP client（`BASE_URL`）、TanStack Query hooks、SSE |
| `lib/types.ts`、`ports.ts`、`graphValidation.ts`、`flowDraft.ts` | 型別（含 `Region` union）、埠顏色、連線檢查、跨頁草稿 store |
| `i18n/locales/` | zh-Hant（完整、fallback）、zh-Hans、en |
| `src/test/` | vitest：i18n 對齊與用詞規範、頁面 render smoke、假後端 |

---

## 資料模型

| 模型 | 用途 |
|---|---|
| `Flow` | 流程：`graph` JSON、版本、擁有者、啟用、連續執行間隔、commissioned |
| `FlowRecipe` | 流程的參數覆寫組（配方），有預設配方 |
| `FlowRun` | 執行紀錄摘要（背景批次寫入，可關；每流程保留 N 列） |
| `FlowTemplate` | 自訂範本（`image_source.source_id` 以 `{SOURCE}` 佔位）；內建範本來自 `demo.BUILTIN_TEMPLATES` |
| `ImageSource` | 影像來源（kind／config／group） |
| `Asset` | 範本影像／模型／資料集檔案（`ASSET_DIR/<uuid>.<ext>`，group） |
| `ResourceGroup` | 來源庫／資產庫的群組（讓空群組可存在） |
| `DlProject`／`DlSample`／`DlDatasetVersion`／`DlSettings` | 深度學習教導：專案、樣本（標記、split、SHA256）、凍結版本、推論／訓練裝置設定 |
| `GoldenCase`／`GoldenBaseline` | 回歸案例與基準 |
| `Connection` | 主動輸出連線（Modbus 等） |
| `UserPref`／`AuthToken`／`EngineLock` | 介面偏好與 AI 供應商設定（金鑰不回前端）、登入 token、引擎鎖（單列） |

graph JSON 格式與埠合約見 `docs/contract.html`；**不改 graph 格式、不把 `Flow.graph` 搬出資料庫**是紅線。

---

## API 一覽

所有端點在 `/api/`，OpenAPI 於 `/api/docs`。身分：登入 token（`Authorization: Bearer`）或整合方金鑰（`X-API-Key`）；`<img>`／SSE 以 `?token=`／`?api_key=` 附帶。

| 群組 | 代表端點 |
|---|---|
| 帳號與鎖定 | `/auth/setup`、`/auth/login`、`/auth/me`、`/auth/prefs`、`/users`、`/vision/lock` |
| 流程 | `/vision/flows`（CRUD）、`/flows/{id}/run`、`/preview`、`/continuous`、`/recent`、`/runs`、`/stats`、`/events`（SSE）、`/scratch-image`、`/export`、`/flows/import` |
| 配方／範本／批次 | `/flows/{id}/recipes`、`/vision/templates`（builtin＋custom、instantiate）、`/flows/{id}/batch`、`/batch-source`（舊介面） |
| 批次測試頁 | `/vision/batch/sets`（＋`/from-source`、`/{id}`、`/images/{index}`、`/to-golden`、`/runs`）、`/vision/batch/runs/{id}`（＋`/cancel`、`/insights`、`/compare`、`/rows/{index}/preview`、`/to-recipe`）、`/vision/agent/consult` |
| Golden | `/flows/{id}/golden`、`/baseline`、`/regress` |
| 資源 | `/vision/sources`（含 `/kinds`、`/usb-scan`、`/test` 儲存前測試擷取、`/preview`）、`/vision/assets`（含 `/from-image`、`/file`）、`/vision/groups`、`/vision/fs`、`/vision/images/{ref}` |
| 工具目錄與容量 | `/vision/tool-types`、`/vision/capacity` |
| 深度學習 | `/vision/dl/projects`、`/samples`、`/split`、`/dataset-export|import`、`/versions`、`/train`、`/train/status`、`/devices`、`/settings`、`/trainers`、`/sam` |
| AI 助手 | `/vision/agent/info`、`/settings`（＋`/test`、`/models`）、`/image`、`/clarify`、`/generate`、`/run`、`/refine`、`/edit`、`/tune`、`/autotune`、`/chat`、`/help/search`、`/jobs`（＋`/{id}`、`/cancel`、`/answer`）、`/sessions`（＋`/{id}`、`/restore`）、`/skills`、`/skills/custom/{key}`；`/flows/{id}/golden/autotune` |
| 整合 | `/vision/integration/info`、`/integration/tcp`、`/vision/connections` |

執行類端點（run／preview／continuous／agent）在引擎鎖定時回 423；修改類端點要求擁有者或管理員。

---

## 執行模型與效能

- **只能有一個 API 行程**：引擎狀態、影像快取、SSE bus 都在行程內。`manage.py serve` = uvicorn workers=1 + TCP；`runserver` 只用來開發且要 `--noreload`。
- 執行緒池預設 10 個流程並行（`VISION_MAX_WORKERS`）；每流程一次一個 run、排隊上限 `VISION_MAX_QUEUE_PER_FLOW`。
- 熱路徑不碰資料庫；連續模式每 2 秒回 DB 確認一次。
- 影像快取：每流程保留最近 N 次 run（`VISION_KEEP_RUN_IMAGES`）；暫存上傳與 AI 助手影像 pinned 不佔名額；總量 LRU（`VISION_IMAGE_CACHE_MB`）；縮圖編碼另有 LRU。
- 引擎固定開銷每節點約 6 µs；示範流程 1280×960 全程約 8 ms（`docs/performance.html`）。
- 前端路由層級分割：主 bundle 約 466 KB，各頁獨立 chunk。

---

## 擴充點

| 想做什麼 | 怎麼做 |
|---|---|
| 新工具 | 繼承 `apps.vision.tools.base.Tool`，宣告 `params`／`inputs`／`outputs`，實作 `execute(ctx) -> Result`；內建放對應 builtin 模組的 `TOOLS`，外掛丟 `plugins/`。補 `tests/test_tools.py` 案例、`scripts/bench_tools.py`、`agent/skills/tools.md` 要領；現場參數標 `teach=True`。前端零修改 |
| 新影像來源／輸出連線 | 繼承 `Grabber`／`Writer`，丟 `plugins/`（或 `.env` 以 `kind=module:Class` 註冊） |
| 新 Trainer（模型種類） | 繼承 `apps.vision.dl.base.Trainer`，實作 `train()`／`suggest()`；UI 由 `/dl/trainers` 目錄驅動 |
| 新 AI 意圖 | `INTENT_KINDS`＋`intents.parse` 規則＋`synth.SYNTHESIZERS` 合成器＋`clarify.build_questions` 缺口問題＋測試 |
| 教 AI 場域知識 | 編輯 `apps/vision/agent/skills/{platform,design,tools}.md`，不用改程式 |
| 新 `Param.kind`／`Port.type`／ROI 形狀 | 後端封閉集合＋前端 `ParamField`／`types.ts`／`roiEditor.ts`／`geometry.ts`＋`catalogue()`＋docs 合約與名詞表同步 |
| 新主題 | `index.css` 加 `.theme-<id>` 變數覆蓋，`UI_THEMES`／`THEMES`／`index.html` 開機腳本三處同步 |
| 新頁面 | `pages/` + `App.tsx` lazy route + `AppShell` NAV + i18n 三語系 + `src/test/pages.test.tsx` smoke |

範例外掛：`plugins/example_dark_ratio.py`（工具）、`plugins/example_csv_writer.py`（輸出）。詳見 `docs/plugins.html`。

---

## 設定（.env）

複製 `.env.example` 為 `.env`；所有值都有預設。重點：

| 變數 | 說明 |
|---|---|
| `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`、`DATA_DIR` | Django 基本設定；資料（SQLite、資產、樣本）在 `DATA_DIR` |
| `VISION_MAX_WORKERS`、`VISION_MAX_QUEUE_PER_FLOW`、`VISION_RUN_TIMEOUT_S` | 引擎並行與逾時 |
| `VISION_KEEP_RUN_IMAGES`、`VISION_IMAGE_CACHE_MB`、`VISION_PERSIST_RUNS`、`VISION_KEEP_RUN_ROWS` | 影像快取與執行紀錄 |
| `VISION_PLUGIN_DIR`、`VISION_TOOL_PLUGINS`、`VISION_SOURCE_PLUGINS`、`VISION_COMM_PLUGINS` | 外掛 |
| `VISION_API_KEY`、`VISION_STATION_ID`、`VISION_TCP_HOST/PORT` | 整合方金鑰、站台識別、TCP 介面 |
| `VISION_BATCH_MAX_IMAGES`、`VISION_KEEP_BATCH_SETS`、`VISION_KEEP_BATCH_RUNS`、`VISION_BATCH_MAX_RUNNING` | 批次測試：影像集上限（200）、每流程保留影像集數（10）、每影像集保留執行次數（20）、同時執行數（2） |
| `VISION_AGENT_PROVIDER`、`VISION_AGENT_API_KEY`、`VISION_AGENT_MODEL`、`VISION_AGENT_BASE_URL`、`VISION_AGENT_TIMEOUT_S`、`VISION_AGENT_MODE` | AI 助手伺服器預設供應商（使用者自己的設定優先；留空＝離線規則引擎；`BASE_URL` 給 Ollama 等 OpenAI 相容本地端點；`MODE`＝single／agentic） |
| `VISION_SAM_MODEL` | 深度學習教導的 SAM 權重（智慧選取／框選／全圖提案；sam2.1_t.pt 預設，mobile_sam.pt 較小、sam2.1_s.pt 更準） |
| `CORS_ALLOWED_ORIGINS` | 前端獨立部署時允許的來源 |

前端：`VITE_API_BASE_URL`（build 時設定，獨立部署用）、`VITE_PROXY_TARGET`（dev 代理目標）。

---

## 驗證與測試

```bash
# 後端：350 項（引擎、工具純度／位深、API、GET 端點 smoke、範例樣板實跑、AI 助手、DL、配方、Golden、外掛、通訊）
.venv/Scripts/python.exe manage.py test --noinput
.venv/Scripts/python.exe -m ruff check apps tests config

# 前端：型別、vitest（i18n 三語系對齊與用詞規範、純函式單元、9 頁 render smoke）、build
cd frontend && npm run -s typecheck && npm test && npm run build

# 效能與等價性
.venv/Scripts/python.exe scripts/bench_tools.py
```

規則：改了優化過的函式要重跑等價性檢查；新增 GET 端點加進 `tests/test_smoke_api.py`；新頁面加 `src/test/pages.test.tsx` case；改文案不得出現禁用口語詞（測試會擋）。

---

## 部署

| 方式 | 前端 | 後端 |
|---|---|---|
| 同站（預設） | `npm run build` 產物由 whitenoise 隨 API 行程服務（`BASE_URL=/api`） | `manage.py serve` |
| 開發 | Vite dev server，`/api` 代理到 8000 | 同上 |
| 前端獨立部署 | build 時設 `VITE_API_BASE_URL=https://host/api`，放任何靜態主機 | `.env` 設 `CORS_ALLOWED_ORIGINS` |

- 單一行程是設計前提：不要開多個 worker 或多副本共用同一資料庫的引擎狀態。
- 可選依賴：`onnxruntime`（DL 推論）、`ultralytics`＋`torch`（YOLO-seg 訓練、SAM）、`anthropic`（Claude 供應器；GPT／Gemini 走標準庫 REST 零依賴）。缺件時對應功能提示安裝指令，其餘正常。

---

## 文件地圖

| 文件 | 內容 |
|---|---|
| `docs/index.html` | 總覽與索引 |
| `docs/user-guide.html` | 使用者手冊（登入→來源資產→流程→工具頁 ROI→執行→批次／Golden→範本→AI 助手→DL→整合→設定→FAQ） |
| `docs/workflow-design.html` | 工作流程設計手冊 |
| `docs/architecture.html` | 設計手冊（資料模型、工具框架、引擎、Runner、API、前端、踩過的坑） |
| `docs/contract.html` | 前後端資料合約、graph JSON、錯誤碼、解耦部署 |
| `docs/automation.html`、`docs/modbus.html` | HTTP／TCP／SSE 整合、引擎鎖定；Modbus 主動輸出 |
| `docs/vision-capabilities.html` | ROI 種類、位深設計、檢測工具總覽 |
| `docs/samples.html` | 範例樣板與合成樣本圖 |
| `docs/agent.html` | AI 助手：詢問機制、多圖 ROI、供應商與金鑰、全域 AI 助手（使用說明問答、編輯器修改、批次諮詢）、批次調參、候選方案與自動調參、定位補正、代理模式、記憶與學習、評測基準、技能、架構 |
| `docs/dl.html` | 深度學習教導 |
| `docs/batch.html` | 批次測試：影像集、暫存結果、洞察與建議門檻、調參、AI 諮詢、API、保留策略 |
| `docs/golden.html` | Golden Set 與流程匯出入 |
| `docs/plugins.html` | 資料夾外掛 |
| `docs/glossary.html` | 名詞規範與文案用詞規範 |
| `docs/performance.html` | 效能報告 |
| `CLAUDE.md` | 給 AI 協作者與開發者的專案須知：架構、慣例、驗證清單、踩過的坑、各模組要點 |

---

## 尚未實作

標定子系統、GenICam 內建來源、零樣本異常偵測、少樣本訓練、SSO。AI 助手目前不自動生成需要模型／連線／寫檔副作用的工具（dl_*、write_modbus、save_image），需要時以註解提醒使用者。
