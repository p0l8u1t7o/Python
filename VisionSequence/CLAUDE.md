# CLAUDE.md — VisionSequence 開發須知

> 給 AI 協作者（Claude Code／Claude Projects）與開發者的單一入口：先讀「專案全貌」建立心智模型，動手前照「工作方式」與「驗證清單」，改到對應模組再看「模組要點」與「踩過的坑」。功能總覽與文件地圖在 `README.md`，細節文件在 `docs/`（HTML）。

## 1. 專案全貌

- **是什麼**：類 VisionMaster 的畫布式工業機器視覺平台。使用者在瀏覽器拉工具節點、畫 ROI、調參看結果；PLC／上位機以 HTTP／TCP／Modbus 觸發並取回 OK/NG 與量測值。
- **技術棧**：Django 5.1 + django-ninja + OpenCV/numpy（後端）；React 19 + Vite + TS + Tailwind v4 + @xyflow/react + TanStack Query + i18next（前端）；SQLite 預設。
- **規模**：66 個內建工具（8 類）、163 個 API 端點、21 個資料模型、18 個前端頁面、16 頁 docs、後端 319 項＋前端 39 項測試；Python 約 17.6k 行、TS 約 21.5k 行。
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
- 深度學習依賴可選：`.\scripts\setup_dl.ps1`（先 torch cu128 index，再 requirements-dl.txt；`-Cpu` 無 GPU）→ `manage.py dl_check --predict` 驗證。順序錯會拉到 CPU 版 torch。
- 手動：`manage.py migrate` → `manage.py seed_demo` → `manage.py serve`；前端 `npm run dev`。
- `seed_demo` 建 2 個示範流程＋每個範例樣板一組合成樣本圖（`apps/vision/demo_images.py` → `data/samples/`，folder 來源、群組「範例」）＋範本／良品資產，可重複執行；範例樣板本身在範本畫廊（`demo.BUILTIN_TEMPLATES`，14 個）。`tests/test_demo.py` 逐範本掛上對應樣本來源實跑鎖住。改樣本圖形要刪 `data/samples/<key>/` 重生成。

### 驗證清單（改完就跑，報告附實際結果）
- 後端：`.venv/Scripts/python.exe manage.py test --noinput`、`.venv/Scripts/python.exe -m ruff check apps tests config`。`tests/test_smoke_api.py` 掃所有 GET 端點不 5xx／405——新增 GET 端點記得加進清單。
- 深度學習實機測試（GPU／網路）：`VISION_TEST_DL=1 manage.py test tests.test_dl_yolo`（yolo_* 五工具、SAM2 點／框／全圖、sam-point／auto-label API、四個 trainer 各 1 epoch 約 40 秒）；改了 yolo 工具、trainer、sam.py、yolo_runtime 一定跑。bench 的 yolo 案例也只在 VISION_TEST_DL=1 納入。
- AI 助手：`manage.py agent_bench`（離線規則引擎跑 `agent/bench.py` 的案例，印意圖／判定準確率；`--llm` 用伺服器供應商比較）；`tests/test_agent_bench.py` 守門檻（意圖 ≥ 0.9、判定 ≥ 0.8、graph 全有效）。改規則引擎、合成器、特徵或自動調參後一定跑，新意圖加案例（案例可帶 `labels`）。
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
- **全域 AI 助手** `help.py`＋`POST /agent/chat`：前端 `AssistantDock`（掛在 AppShell，任何頁面右下角）送 `{message, mode, context{kind, flow_id, node_type, batch_run_id, image_ref, graph}, history}`；`api.chat_intent` 依脈絡分流——問句一律 help；修改語氣在 flow_editor／tool（帶 graph）→ `service.edit`、在 batch（帶 batch_run_id）→ `service.tune`＋`persist_tune`；batch 的資料字眼 → `consult.consult`；代理模式下 edit／tune 回 `{agentic: true}` 讓前端改走 `/agent/jobs`。`help.answer`：docs/*.html 拆 h2／h3 章節（帶錨點）＋每個工具技能 → BM25（中文雙字詞、標題與頁面加權；docs mtime 變了自動重建），LLM 只依片段回答並列參考章節，離線／失敗回 `offline_answer` 節錄；`sources[].url` 指向 `/docs/<page>#<anchor>`（`config/urls.py` 用 `serve` 提供 docs、vite 代理 `/docs`）。改了 docs 章節標題會影響檢索測試（`tests/test_agent_help.py`）。`tests/test_assistant_deep.py` 守門檻：分流語料 40 句準確率 ≥ 0.95、說明檢索基準 24 題 hit@3 ≥ 0.85／hit@1 ≥ 0.6，並涵蓋邊界輸入、索引重建、多執行緒、權限／鎖定（問答不受鎖定影響，修改／諮詢／調整 423）、代理模式經 /agent/jobs；改分流規則或索引要跑。
- 多圖＋ROI 編號（ROI01…，regions[i].image 指影像索引；「ROI01 是好品、ROI02 是壞品」→ golden 意圖，好品 ROI 自動裁成資產）。全域 AI 助手在編輯器走 `/agent/chat`→`service.edit`（`/agent/edit` 仍可直接呼叫）（離線句型見 `service.edit_rules`）；批次頁的依資料調整走 `/agent/chat`→`service.tune`（`/agent/tune` 仍可直接呼叫）（同批影像重跑回前後對比）。
- AI 代理技能在 `agent/skills/`（platform.md 平台規則、design.md 設計原則含謹慎原則、agentic.md 代理工作方式、tools.md 每工具要領 `## <type>` 分段）；`skills.py` 組裝：system＝規則＋原則＋精簡目錄（穩定可快取），相關工具完整技能（自動骨架＋要領）由 `select_tools` 挑進 user 訊息。**新增工具要在 tools.md 補一段要領**。
- 供應商：`openai_compatible`（Ollama／vLLM／LM Studio；`base_url`、金鑰可空）與 OpenAI／Gemini 的 JSON 模式在 `providers.openai_body`／`_gemini`；OpenAI 推理模型（o 系列／gpt-5）自動用 `max_completion_tokens`；生成逾時 `providers.generate_timeout()`（`VISION_AGENT_TIMEOUT_S`）。LLM 失敗時 `service._try_llm` 回 `(None, reason)`，原因進回應 `warnings`。
- 供應商設定存完會打 `providers.test_connection` 驗證並回原因；`list_models` 列金鑰可用模型。
- **候選方案與自動調參**：`synth.candidates` 每意圖產主要方案＋參數變體（`VARIANTS` 表），`service._rank_candidates` 全部靜默試跑（`trial_run(keep_images=False)` → `store.drop_run`）依 `expected_labels`（`GenerateIn.labels` 或 ROI 提示好品／壞品）打分；回應 `candidates[]`，前端切換走 `POST /agent/run`。`autotune.coordinate_search` 只搜 `teach=True` 且不在 `SKIP` 的參數、嚴格變好才採納；入口：生成（`GENERATE_AUTOTUNE_EVALS`）、`POST /agent/autotune`／`tune` 指令含「自動調參」、`POST /flows/{id}/golden/autotune`（golden api）。改工具的 `teach` 標記會改變搜尋空間。
- **代理模式**：`AgentSettings.mode`（`UserPref.agent.mode`／`VISION_AGENT_MODE`）＝agentic 時前端走 `POST /agent/jobs`（`jobs.py` 背景執行緒、單行程最多 3 個、`GET /jobs/{id}?step_from=` 輪詢、cancel／answer）。`actions.py`＝動作層（`ACTIONS` 表；改 graph 一律複本→`check_graph`；`dispatch` 把例外翻成 `{"error"}` 回模型並記 `state.steps`）、`loop.py`＝迴圈與 `Budget`、`providers.complete_tools`＝中立歷史→各供應商工具呼叫格式（純函式 `claude_messages`／`openai_messages`／`gemini_contents`＋`parse_*_reply` 有測試）。沒 LLM 或工具呼叫失敗 → `jobs._run_single` 退回單次路徑。新增動作＝`ACTIONS` 加一筆（schema 只用 type/properties/required/items/enum，Gemini 才吃）＋`skills/agentic.md` 補要領＋`tests/test_agent_loop.py` 案例；假供應商用 `mock.patch.object(providers, "complete_tools", side_effect=...)`。
- **記憶**：`memory.remember` 在 `service.generate`／`jobs._finalize` 之後存 `AgentSession`（best-effort，失敗只記 log；影像在 `ASSET_DIR/agent/<id>/`，刪除走 `memory.forget`）；`service.recall(intent, feats)` → 相似成功案例（同意圖、`success` 或 `rating>0`、特徵距離 ≤ 0.35）→ `priors`（`synth.candidates(priors=)` 產候選「prior」排第一、`autotune.search_space(priors)` 先試）＋ `examples`（LLM／代理的 user 訊息）。跨執行緒寫 session 的測試用 `TransactionTestCase`（`JobApiTests`）。自訂技能 `AgentSkill`：`skills.with_custom`／`custom_texts`，站點補充進 `build_system(epoch)`（存檔後 `skills.invalidate()`），個人補充進 `focus_text(keys, user)`；`skill_text(key, user)` 回合併全文、`base_skill_text` 回內建。
- **定位包裝**：ROI 提示含「定位／標記／marker」→ `Intent.locator_roi`，該 ROI 不參與檢測（`synth._work_regions` 同步重編 ROI 索引），`wrap_with_locate` 在流程前包範本比對／定位補正／ROI 跟隨（ROI 輸入埠優先於參數）。新意圖 `text`／`distance`／`template_presence`（後者與 golden 一樣需要 `make_asset`）。
- 特徵驅動參數：`analysis` 的 `mad`（穩健 σ）／`smooth_mad`（低通後 σ，紋理面缺陷門檻用）／`gradient`／`color_std`／`area`；`synth` 的 `_blob_min_area`、`_clip`；計數意圖 `round_target` 加圓形度下限排除線段。新增意圖＝`INTENT_KINDS`＋`intents.parse` 規則＋`synth.SYNTHESIZERS` 合成器＋`clarify.build_questions` 缺口問題＋`tests/test_agent.py` 案例。規則式微調映射在 `service.refine_rules`。詳見 docs/agent.html。

### 批次測試（apps/vision/batch）
- 兩個模型：`BatchSet`（影像檔在 `ASSET_DIR/batch/<id>/NNN.png`，`images` JSON 帶期望標記）、`BatchRun`（graph 快照＋`items` 逐張結果含各節點**純量**輸出（NaN 轉 null，SQLite JSON_VALID 會擋）＋`summary`＋`insights` 快取，`parent` 串調參前後，`origin`＝manual／draft／autotune／ai_tune）。命中不存，讀時用 `regress.evaluate_expect` 現算；改標記後 `store.refresh_matches`。
- 執行走 `batch/jobs.py` 背景執行緒：`runner.compiled_for(flow, graph_override=)` 編一次、每張 `engine.execute(flow_id=BATCH_FLOW_ID=-1, preview=False)` 後 `store.drop_run`——**不走 runner 佇列**（不計統計、不發 SSE、不寫 FlowRun、不隱含套預設配方）。進度每 10 張／2 秒 `update()`；`jobs.wait()` 給測試；重啟殘留 running 讀取時 `store.reconcile` 標 failed。autotune 模式先 `autotune.coordinate_search`（未命中優先抽樣 ≤40）再全量重跑。
- `insights.compute` 純函式：沿 `value` 輸入邊找判定節點的上游值（所以 items 一定要存節點純量輸出），if_number 掃相鄰中點、in_range 只動有 NG 那側、tolerance_judge 只列分佈；`suggestions_of`／`apply_suggestions` 給諮詢與前端套用。
- AI 接縫：`agent/api._batch_context(batch_run_id)` 從磁碟組 `runs`（未命中優先、帶 index）＋影像 dict＋洞察文字；`service.tune(..., extra_summary, detail=True)`／`_rerun_items(detail=True)` 回逐節點資料；`store.persist_tune` 把 tune／autotune／代理結果落成新 `BatchRun`；`agent/consult.py` 諮詢（LLM 尾端 `SUGGESTIONS:` JSON 需驗證）。前端 `BatchPage`＋`components/batch/*`＋`lib/batch.ts`；編輯器「批次測試」改導頁（`/batch?flow=&draft=1`），舊彈窗已移除，舊端點 `/flows/{id}/batch` 保留給整合方。
- 淘汰：`KEEP_BATCH_SETS`／`KEEP_BATCH_RUNS`／`BATCH_MAX_IMAGES`／`BATCH_MAX_RUNNING`（.env）。新 GET 端點已進 smoke 清單（setUp 會建一個影像集並 `jobs.wait`）。

### 深度學習教導（apps/vision/dl）
- `Trainer` registry（base.py）：kind／label_mode（封閉集合：classes｜shapes）／params（沿用 Param）／devices，實作 `train()`（回 `TrainResult`：ONNX bytes＋tool_params，可另帶 `weights_bytes/weights_tool_key/weights_tool_params`＝原生權重）與 `suggest()`（自動標記）。內建：`mlp_classify`、`patch_segment`（手刻 ONNX 給 dl_segment）、YOLO 四種（`yolo.py` 的 `_YoloTrainer` 依 task：`yolo_seg`／`yolo_detect`／`yolo_cls`／`yolo_obb`；torch/ultralytics **可選安裝、延後 import**，缺件提示 setup_dl.ps1）。jobs.py `_train` 有 weights 時建兩個 model 資產（.pt 主產物、ONNX 名加「（ONNX）」、meta.format／onnx_asset_id），專案 last_asset 指向 .pt。外掛 trainer 丟 `plugins/` 即掛載，前端 UI 由 `/dl/trainers` 目錄驅動。
- **yolo_* 工具**（`tools/builtin/yolo.py`：detect／segment／classify／pose／obb）：模型＝`model` 資產（.pt／.onnx）優先、否則 `model_name` 官方底模（`yolo.resolve_model` 下載，release v8.4.0→v8.3.0）；推論走 `dl/yolo_runtime.py`（行程內模型快取最多 6 個、同模型鎖序列化、`pick_device` auto→cuda）；座標用 crop／to_full 回全圖；任務不符回 ToolError。ONNX 資產交給 ultralytics 的 ORT 後端（會印 onnxruntime 套件名警告，可忽略）。
- shapes 標記存 DlSample.shapes（0~1 正規化），`shapes.py` 與 YOLO txt 互轉；`shapes_to_yolo(task=)`：mixed（原樣，互通用）／segment（bbox→四角）／detect（polygon→外接框）／obb（polygon→minAreaRect）；`export_classify_dataset` 產 ultralytics 分類資料夾（**類別索引以資料夾排序為準**，trainer 用 model.names 回填）。`dataset-export`／`dataset-import` 雙向互通。訓練跑背景執行緒（jobs.py，單一訓練槽、409 擋第二個），前端輪詢 `/dl/train/status`。
- 推論 providers 是熱路徑設定：工具只讀 `devices.preferred_providers()`（記憶體）；`PATCH /dl/settings` 寫 DB＋更新快取＋`clear_sessions()`；裝置資訊 `GET /dl/devices`。dl.py `get_session` 選到 GPU provider 前先 `preload_gpu_dlls()`（import torch＋`ort.preload_dlls()`），否則 CUDA session 靜默退回 CPU。
- 資料集：樣本以解碼後像素 SHA256 去重；`DlSample.split`（train/val/test）；`DlDatasetVersion` 凍結成 zip 資產。SAM 智慧標記（`sam.py`）：權重 `VISION_SAM_MODEL`（預設 sam2.1_t.pt，下載失敗退回 mobile_sam.pt）、session 模組層快取＋鎖；`suggest_shapes(points／boxes)` 點擊與框選、`suggest_everything` 全圖提案（auto-label `method=sam`，每次 ≤ max_samples 張回 remaining）。樣本影像在 `ASSET_DIR/dl/<project_id>/`；訓練執行緒自己開 DB 連線、結束 `close_old_connections()`。詳見 docs/dl.html（§11 安裝與踩坑）。

### 前端
- 全域 AI 助手：`components/assistant/AssistantDock.tsx`（對話存 localStorage `vs.assistant.v1`、模式晶片、快速提示、參考連結、套用到畫布／套用建議／新執行、代理工作走 `useAgentJob`＋`AgentTimeline`）；頁面用 `lib/assistantContext.ts` 的 `useRegisterAssistantContext({kind, flowId, flowName, nodeType, batchRunId, imageRef, getGraph, applyGraph, applySuggestions, onNewRun}, deps)` 登記脈絡（編輯器、工具頁、批次頁已登記；未登記的頁面由路徑推 kind）。編輯器右側與批次頁的 AI 分頁已併入 dock（`AiAssistPanel`／`BatchAiPanel` 已刪），新頁面要讓助手能「動手」就登記回呼。
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
- 前端 `Card` 只認 `testId` 屬性，寫 `data-testid` 會被丟掉（TS 不會報錯）；要給測試或截圖腳本用的 Card 一律用 `testId=`。
- `manage.py agent_bench --llm` 用伺服器供應商；要用某位使用者的金鑰跑就在 shell 裡 `bench.run_bench(providers.resolve(user), use_llm=True)`。LLM 單次生成實測（gemini-3.5-flash-lite）判定 76%、有效 81%，規則引擎 100%——LLM 產物一定要過試執行；全部失敗時 `service.generate` 已會退回規則。
- **Gemini 3 function calling**：模型回的 `functionCall` part 帶 `thoughtSignature`，下一回合必須原樣回傳（`ToolReply.raw` → 歷史 `raw` → `gemini_contents` 直接用原生 parts），否則 400「missing a thought_signature」；實機用 gemini-3.5-flash-lite 驗過代理迴圈 4 回合 5.6 秒完成。
- jsdom 沒有 `Element.scrollTo`：元件捲到底用 `el.scrollTop = el.scrollHeight`，不然 vitest 會炸。i18n 的陣列值（快速提示）三語系長度要一致（key 對齊測試把索引當 key）。
- i18n：一次多檔替換若中途失敗要檢查已成功的檔案，避免重複插入（TS1117）；en 是單行物件格式，錨點與 zh 不同。
- **DL 依賴**：ultralytics 要在 torch（pytorch.org cu128 index）之後裝，否則拉 CPU 版；RTX 50（sm_120）只有 cu128+ 有 kernel；`onnxruntime-gpu` 1.23+ 預設 CUDA 13，配 torch cu128 要鎖 1.22.0，且建 CUDA session 前先 import torch／`preload_dlls()`（providers 列表有 CUDA 不代表 session 真的用到）；`onnxruntime` 與 `onnxruntime-gpu` 同名互蓋，只能裝一個；訓練 workers=0；`YOLO_OFFLINE=1`；分類資料集類別順序＝資料夾排序；ultralytics 8.4 對 `half=False` 也印棄用警告（只在需要時傳 True）。`manage.py dl_check --predict` 一次檢查完。
