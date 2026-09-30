# CLAUDE.md — X-RayVision

本檔記錄專案定位、規範與決策，供後續開發延續。回覆使用者一律使用繁體中文（台灣用語）。

## 產品定位

- 產線用 **X 光半導體檢測影像分析平台**：平台提供影像校正、成像品質、配方、判定、報告、稽核等共用能力，檢測項目以「檢測模組」掛載擴充。
- 首個檢測模組為微凸塊對位：分析覆晶封裝的微凸塊（Micro Bump）與基板焊墊（Pad）對位，量測逐點偏移與晶片整體偏移。之後依需求擴充空洞（Void）、裂紋（Crack）、橋接等模組（規劃書第 5 節）。
- 本產品不控制 X 光設備，只分析設備輸出的影像。
- 前端使用 React，簡潔設計，提供亮色／暗色主題（規劃書第 4.3 節）。
- 規劃書：[docs/product-plan.md](docs/product-plan.md)（PLAN-001）。檢測邏輯說明：[docs/bump-pad-detection-flow.md](docs/bump-pad-detection-flow.md)。

## 產品規範（必須遵守）

1. **產品內不得出現任何設備廠牌或型號**，包括介面、報告、說明文件、安裝程式、檔名、中繼資料、程式內的顯示字串。一律稱「X 光檢測設備」。
   - 開發備註（僅限本檔，不得進入產品）：現場設備為微焦點 X 光檢測設備，型號 Nordson MXI QUADRA 7 Pro。
2. 產品文字使用**正式商業用語**；名詞依規劃書第 9 節的用語對照表，全產品一致。
3. 介面與報告支援**繁體中文與英文**切換，預設繁體中文；字串集中在語系檔，不寫死在程式。
4. 程式碼、變數、函式名稱使用英文；程式註解使用繁體中文。

## 工作方式

- **開工前先寫規劃書放在 `docs/`，經使用者核准後才實作。**
- 遇到需要使用者決定的事項，用選項對話框詢問，並提供建議選項。
- 依規劃書分階段進行，每階段完成後提交成果供審閱，核准後再進入下一階段。
- 未經使用者要求不 commit、不 push。

## 已決定事項

| 日期 | 決定 |
|---|---|
| 2026-09-23 | Batch2（16-bit）的焊墊在凸塊正下方；凸塊旁約 1.5 倍半徑處的淡色淚滴是基板走線／via，不是焊墊 |
| 2026-09-23 | 部署形式：核心分析引擎＋本機網頁介面（延續 Flask），日後可擴充為伺服器 |
| 2026-09-23 | 影像匯入：資料夾監看自動分析＋手動匯入，兩者都支援 |
| 2026-09-23 | 拍攝參數：來源不確定，兩種都支援（有參數檔或手動輸入時記錄並比對；沒有時以影像品質指標作為成像條件指紋） |
| 2026-09-23 | 語系：繁體中文＋英文可切換 |
| 2026-09-23 | 像素尺寸未知，結果暫以 px 表示 |
| 2026-09-23 | 產品定位為可擴充的檢測平台；平台核心與檢測模組分離，模組以統一介面與結果格式掛載 |
| 2026-09-23 | 前端改用 React（Vite 建置），簡潔設計、亮色／暗色主題；建置後的靜態檔由後端提供，離線可用 |
| 2026-09-23 | 授權：一台電腦一份授權、只能執行一套；綁定電腦硬體特徵產生的機器碼；離線以申請檔／授權檔交換啟用；原廠私鑰簽章 |
| 2026-09-23 | 授權期限：訂閱制，到期停止分析，但保留檢視、報告、匯出與匯入續約授權；授權檔列出可用檢測模組 |
| 2026-09-23 | 更新：工廠端離線，管理員於網頁匯入簽章更新檔進版；進版前自動快照、失敗自動退回；保留最近 3 個版本 |
| 2026-09-23 | 退版：還原升版前快照；升版後的紀錄另存封存檔，日後升版可再匯入 |
| 2026-09-23 | 問題回報包：勾選影像／批次匯出單一檔案（原始影像、結果、配方、版本、日誌），可去識別化、加密、分割 |
| 2026-09-23 | 前端 TypeScript；寬限天數由授權檔決定；回報包預設不加密；8-bit 可分析但判定最多「需複判」；工作名稱 X-RayVision；不接 MES；第二個模組為空洞（Void） |
| 2026-09-23 | 部署環境即 X 光設備電腦：Windows 10/11 64 位元、NVIDIA GPU、已裝防毒（規劃書第 8.1 節） |
| 2026-09-23 | 第 4 階段：標準 setup.exe（Inno Setup）；Windows 服務；產品內建帳號（操作員／工程師／系統管理員）；預設不自動刪除＋磁碟空間警示，管理員可設保留天數 |
| 2026-09-23 | 第 5 階段：空洞檢測針對焊球／凸塊內空洞（逐顆）；客戶之後提供空洞影像，先以合成影像開發並標示未驗證；範圍含深度學習（推論、模型管理、標註匯出）；預設單顆空洞率 ≤25% |
| 2026-09-23 | Batch1／Batch2 的錫球與凸塊沒有可見空洞；錫球內的亮斑是與焊墊重疊，不是空洞（空洞在吸收量影像中是較暗的區域） |
| 2026-09-23 | 5a 取捨：空洞蓋住焊墊時寧可需複判也不可判合格（擴大估計誤差）；空洞最小相對深度 0.07；複合凸塊等非目標結構以配方半徑範圍與檢測區域排除 |
| 2026-09-23 | 5c 同意：產品加入 ONNX Runtime（DirectML 版）、開發機裝 PyTorch CPU 訓練示範模型；5c～5e 一次做完，待辦寫在 README，開發完一起檢討 |
| 2026-09-24 | 使用情境為產線 QC 站抽檢，非連續生產；不需為即時檢測調整佇列優先權 |
| 2026-09-24 | PLAN-003：紀錄頁左清單＋右預覽；已發布配方以「修改」建新版本、發布時挑選重跑範圍（預設舊版本全部影像）；新結果成為目前結果、舊結果標示已被取代；不沿用人工複判；配方編輯器草稿試跑 |
| 2026-09-30 | PLAN-004：手動檢測不進正式紀錄（工作區暫存、可另存配方草稿與匯出）、工程師以上；正式流程保留配方區域並加檢閱頁單張自訂檢測區域（新紀錄、可追溯）；包含區域可勾選「視為一個陣列」；重新分析預設沿用自訂區域；工作區 7 天未用清除、每人 50 張／2 GB；不做參數並列比較；微凸塊對位升 1.1.1 而非 1.2.0（避免既有已發布配方版本鎖定失效） |

## 目前狀態

- PLAN-001 規劃書 v0.4 已於 2026-09-23 核准。
- **第 1 階段（成像條件對策）已完成**（2026-09-23）：
  - 品質閘門 `core/quality.py`（平台預設→模組預設→配方覆寫；pass/warn/fail）；斜射偵測用「一致扁平度」換算等效斜射角，只能可靠偵測約 25° 以上，小角度靠拍攝參數 `view_angle_deg`。
  - 暗場／平場校正設定檔 `core/calibration.py`（`calib-create`，存於 `calibration/<代碼>/`）。
  - 拍攝參數 `core/acquisition.py`（同名 .json/.txt/.ini 參數檔、手動輸入、別名對應、配方允許範圍）。
  - 像素尺寸：配方 `pixel_size_um` 或模組參數 `design_pitch_um` 推得；`_px` 量測自動加 `_um`；間距偏差檢查。
  - 不變性驗證 `core/validation.py` 與 `validate` 指令；Batch2 1 vs 2 張間差異 0.076 px（通過）。
  - 說明文件 [docs/imaging-conditions.md](docs/imaging-conditions.md)（SPEC-002，含參數掃描驗證 SOP）。
  - 41 項測試通過；量測結果與第 0 階段基準完全相同（模組版本 1.1.0 只新增指標）。
  - 品質門檻是依 Batch1/2 訂的初始值，需現場參數掃描影像校正。
- **第 2 階段（服務與資料）已完成**（2026-09-23），說明見 [docs/service-and-data.md](docs/service-and-data.md)（SPEC-003）：
  - `store/db.py`：SQLite、結構版本、觸發器保護（已發布配方不可改、稽核只能新增）。
  - `service/recipes.py`：配方草稿→發布→停用；發布時鎖定模組版本，主版.次版不同即拒用。
  - `service/jobs.py`：匯入（雜湊、封存、拍攝參數於原始位置讀取）、資料庫佇列、子行程低優先權、當機復原、重試。
  - `ingest/watcher.py`：輪詢、兩次掃描穩定才匯入、既有檔案略過、命名規則解析批號。
  - `core/judge.py` 與模組 `judge()`：|shift|±k·se 對規格；影像判定優先順序；8-bit 最多需複判；人工複判。
  - `service/diagnostics.py`：串流 ZIP、SHA-256 manifest、去識別化、AES-GCM＋RSA 加密（開發用金鑰）、分割；`tools/diag_replay/replay.py` 原廠端重現。
  - `service/api.py`：FastAPI，26 個端點，`serve` 與 `recipe-import` 指令。
  - 50 項測試通過；Batch2 經 API 端到端 9 張 22 秒完成。
- **第 3 階段（React 介面與報告）已完成**（2026-09-23），說明見 [docs/user-interface.md](docs/user-interface.md)（SPEC-004）：
  - `web/`：React 19＋TypeScript＋Vite，HashRouter，只依賴 react／react-dom／react-router-dom；`npm run build` → `web/dist/` 由後端提供。
  - 設計代幣 `web/src/styles/theme.css`（亮／暗主題、固定判定色、中性灰影像區）。
  - 畫面：總覽、紀錄（篩選、CSV、回報包）、影像檢閱與複判（Canvas 檢視器、通用疊圖、六個分頁）、A4 報告、匯入、配方管理與依參數結構產生的編輯器、資料夾監看、問題回報、稽核。
  - 介面文字放在後端語系檔 `ui.*`；`tests/test_i18n.py` 檢查前端用到的鍵都有翻譯。
  - 後端新增 `/api/runs/export.csv`、模組描述含疊圖樣式；操作者名稱以 URL 編碼傳送。
  - 52 項測試通過；以 Edge 無頭模式截圖檢查亮／暗主題的總覽、紀錄、檢閱、配方、報告。
  - 前端改動後要 `cd web && npm run typecheck && npm run build`。
- **第 4 階段（產線化）已完成**（2026-09-23），說明見 [docs/production-deployment.md](docs/production-deployment.md)（SPEC-005）與操作手冊 [docs/operation-manual.md](docs/operation-manual.md)（MAN-001）：
  - 帳號：`service/auth.py`（scrypt、Cookie 工作階段、鎖定、三種角色與 `PERMISSIONS`）；首次使用建立系統管理員；`reset-password` 指令做本機救援。
  - 資料保留：`service/maintenance.py`（保留天數、磁碟警示、每小時清除封存影像）。
  - 授權：`service/license.py`（Ed25519、機器碼四項容許一項變更、九種狀態）；原廠端 `tools/license_admin/`。
  - 更新退版：`service/updates.py`、`service/archive_import.py`、`launcher/launcher.py`（只用標準函式庫；快照、自我檢查、自動退回、退版封存檔）；原廠端 `tools/release/make_update.py`。
  - 發行：`tools/release/build_release.py`（embeddable Python 3.12＋`runtime-requirements.txt`、WinSW 服務包裝、冒煙測試、Inno Setup `installer/xrayvision.iss`、更新檔、build-info）；產出在 `build/`（不納入版控）。
  - 前端：登入／首次設定／變更密碼、帳號管理、系統管理（儲存空間、授權、軟體更新）、授權與磁碟警示橫幅。
  - 63 項測試（不含 slow）＋端到端進版退版測試通過；冒煙測試（stage 內啟動器實際啟動並通過自我檢查）通過；setup.exe 已編譯。
  - **尚未驗證**：setup.exe 實際安裝／服務註冊／解除安裝（需系統管理員權限，建議乾淨 Win10 VM）；服務身分下 CTRL_BREAK 正常停止；設備電腦實機。
  - **正式發行前**：`xrayvision/keys/*.pem` 與 `tools/keys/` 都是開發用金鑰，必須更換；程式碼簽章憑證尚未取得。
- **第 5 階段（檢測擴充）**：規劃書 [docs/phase5-plan.md](docs/phase5-plan.md)（PLAN-002）2026-09-23 核准；子階段 5a 空洞模組→5b 檢測區域→5c ONNX 推論與模型管理→5d 標註與訓練資料→5e 開發指南與驗證工具。
  - **5a 已完成**（2026-09-23），說明見 [docs/void-inspection.md](docs/void-inspection.md)（SPEC-006）：
    - `inspections/void/`（1.0.0，未驗證）：邊緣擬合定位 → 邊緣模型殘差找焊墊 → 非對稱初始化＋非對稱穩健擬合（截頂球弦長＋焊墊圓盤）→ 相對殘差分割 → 排除空洞重新擬合 → 物理合理性過濾；典型尺度補漏 (須像焊點才計入)。
    - 空洞蓋住焊墊是量測極限，以擴大估計誤差轉為需複判；安全性測試確保實際 ≥25% 的焊點不漏偵測、不判合格。
    - 模組驗證狀態：`service/modules.py`、資料庫結構 3 `module_validations`、`pipeline.analyze_image(validated=)`、`judge.overall` 把未驗證模組的合格／不合格改為需複判；「配方管理 > 檢測模組」核准／撤銷。
    - 平台擴充：`_px2`→`_um2`、模組 `finding_table`（排行表＋分布）、通用摘要 `summary.*`、`ballN` 判定對象。
    - 合成影像 `tests/synthetic_void.py`；`tests/test_void.py` 13 項；全部 76 項（不含 slow）通過。
    - 合成影像驗收：檢出 100%、誤報 0/115、誤差 95% 分位 1.66 個百分點、不變性偏移 ≤1.17、6 MP 252 顆 3.4～4.9 秒。實際影像：Batch2 BGA 範圍 0/83 誤報；複合凸塊為主的影像與 8-bit 有少量誤報。
    - **沒有含空洞的實際影像**，模組維持未驗證；取得影像後以 5e 驗證工具驗證再核准。
  - **5b 已完成**（2026-09-23）：配方 `regions`（包含／排除、矩形／多邊形、參考影像尺寸，尺寸不同依比例縮放）；`core/regions.py`；`ctx.region_mask`／`ctx.in_region`；兩個模組都只量測區域內目標；配方編輯器 `RegionEditor`（選參考影像、拖拉矩形、點選多邊形）；疊圖「檢測區域」圖層；`tests/test_regions.py` 6 項，全部 82 項通過。
  - **5c～5e 已完成**（2026-09-23，使用者指示「繼續進行的全部結束，待辦紀錄在 README，開發完再一起檢討」），說明見 [docs/deep-learning-and-annotation.md](docs/deep-learning-and-annotation.md)（SPEC-007）、[docs/module-development-guide.md](docs/module-development-guide.md)（GUIDE-001）：
    - 5c：`core/inference.py`（ONNX Runtime DirectML 版，GPU 預設關閉）、`core/modelpkg.py`（.xrvmodel 簽章）、`service/models.py`、資料庫 4 `models`、參數型別 `model`、空洞模組 1.1.0 `method`/`model`、`inspections/void/model_seg.py`（裁切與正規化，訓練共用）、示範模型 `tests/data/void_unet-1.0.0.xrvmodel`（`tools/model_training/train_void.py`，合成資料）。
    - 5d：資料庫 5 `annotations`（只新增）、`service/annotations.py`、權限 `annotate`、標註頁 `web/src/pages/Annotate.tsx`、訓練資料匯出（可附原始影像作為驗證資料集）。
    - 5e：`core/module_validation.py` + `validate-module` 指令、`inspections/void/validate.py`、`tools/model_training/make_synthetic_dataset.py`、`examples/module_template/`、外部模組 `translations` 併入語系。
  - **全部開發完成，待辦與檢討事項整理在 README 最後一節**；等使用者一起檢討後再決定下一步。
- **PLAN-003（檢測紀錄快速檢視與配方調整重新分析）已完成**（2026-09-24），規劃書 [docs/review-and-recipe-iteration-plan.md](docs/review-and-recipe-iteration-plan.md) 第 12 節有完成紀錄：
  - 目前結果＝同一影像最新一筆紀錄（`api.CURRENT`、`superseded_by`、`current_only`）；總覽只計目前結果、日期依影像匯入時間；資料庫結構 6 只加索引。
  - 紀錄頁左清單＋右預覽（`Runs.tsx`、`RunPreview.tsx`）；檢閱頁上一張／下一張（sessionStorage `xrv.runs.nav`）、分析歷程分頁。
  - 配方「修改」（`RecipeStore.revise`，note `from vN` 記來源版本）、差異（`body_diff`）、發布並重新分析（`reanalyze`: all_previous／lot／none）、批次重新分析（`jobs.queue_reanalysis`）。
  - 試跑（`jobs.TrialRunner`，`POST /api/recipes/trial`，不寫紀錄）。重新分析不沿用人工複判。
  - `tests/test_iteration.py` 4 項；全部 103 項（不含 slow）通過。
  - 截圖腳本：Edge 無頭模式要用絕對路徑的 `--user-data-dir`，並加 `--no-first-run --disable-sync --disable-extensions`；`edge.kill()` 只結束主程序，殘留程序要另外清掉，否則會拖慢之後的截圖。
- **PLAN-004（手動檢測與手動檢測區域）已完成**（2026-09-30），規劃書 [docs/manual-inspection-and-roi-plan.md](docs/manual-inspection-and-roi-plan.md) 第 10 節有完成紀錄，待使用者審閱：
  - 區域格式 `label`／`as_array`（視為一個陣列）；`RegionCanvas`（可縮放平移、選取移動、復原）三處共用；微凸塊對位 1.1.1（舊配方結果不變，不升次版以免既有配方版本鎖定失效）。
  - 手動檢測 `/#/manual`：`service/workspace.py`（每人 50 張／2 GB，7 天未用清除）、`jobs.InteractiveRunner`（試跑與手動檢測共用、影像快取、同 key 取代）、尺度空間偵測快取 `algorithm.scale_space_blobs`（重複分析約 1.7 秒）；切換影像時背景預先準備（`/api/workspace/prefetch` → `jobs.warm_image` → 模組 `warm()`），預先載入後第一次分析約 2.3 秒。
  - 本影像自訂檢測區域：結構 7 `jobs.regions_json`、`/api/runs/{id}/regions(/trial)`、權限 `image_regions`、重新分析預設沿用。
  - `tests/test_manual_inspection.py` 11 項（含預先準備與授權不可分析）；回歸 0 差異。主體已提交 170acce；審閱後追加的預先載入與授權測試見規劃書第 10.1 節。
  - 截圖／操作腳本：Node 24 內建 WebSocket 走 CDP 控制 Edge 無頭模式即可（不需裝套件）；注意 hash 導覽不會重新載入頁面，改 localStorage 後要 `Page.reload`。
- **第 0 階段（平台基礎）已完成**：
  - `xrayvision/` 套件：平台核心、檢測模組介面、微凸塊對位模組、命令列、語系檔。
  - 模組介面規格見 [docs/inspection-module-interface.md](docs/inspection-module-interface.md)（SPEC-001）。
  - 新引擎與舊版批次工具 `BumpPadShift.py` 逐顆比對 4304 個位點，差異僅為四捨五入（≤0.0005 px）。舊版工具（`BumpPadShift.py`、`FlipChipShift.py`、Flask `app.py`）已於 2026-09-24 移除。
  - 24 項測試通過，包含合成影像的曝光不變性測試，以及 Batch1／Batch2 回歸基準（`tests/regression/baseline.json`）。
- 尚待確認事項見規劃書第 15.1 節（Q1～Q4、Q13、Q16、Q17，多為需現場提供的資料）。

## 現有程式

| 檔案 | 說明 |
|---|---|
| `xrayvision/core/` | 平台核心：`io`（影像載入與種類判定）、`calibration`（吸收量）、`geometry`（圓擬合、相似變換、偏移估計）、`plugin`（模組介面、參數結構、結果格式、註冊）、`pipeline`（配方與分析流程）、`render`（通用疊圖）、`runtime`（低優先權、執行緒限制）、`serialize` |
| `xrayvision/inspections/bump_alignment/` | 微凸塊對位模組；`algorithm.py` 為量測演算法，`__init__.py` 宣告參數結構並轉成統一結果格式 |
| `xrayvision/inspections/void/` | 空洞檢測模組（SPEC-006）；`algorithm.py` 演算法，`__init__.py` 參數、判定、物件格式 |
| `tests/synthetic_void.py` | 空洞合成影像產生器（截頂球、球形空洞、偏心焊墊、光子雜訊；提供正確答案） |
| `tools/model_training/` | 原廠端：空洞模型訓練（PyTorch，需另裝）、合成驗證資料集產生器 |
| `examples/module_template/` | 外部檢測模組範例（亮點計數）；測試納入主測試集 |
| `tests/data/void_unet-1.0.0.xrvmodel` | 示範模型（合成資料訓練、開發金鑰簽章） |
| `xrayvision/i18n/` | 語系檔；所有原因代碼與顯示文字都要有 zh-TW 與 en |
| `xrayvision/service/`、`store/`、`ingest/` | 平台服務：API、帳號、授權、更新、保留、佇列、配方、回報包；SQLite；資料夾監看 |
| `xrayvision/keys/`、`selftest/` | 公鑰（目前為開發用）；內建標準影像與預期結果（進版自我檢查） |
| `web/` | React＋TypeScript 前端；`web/dist/` 由後端提供（紀錄清單＋預覽、配方修改／發布／試跑元件見 PLAN-003；手動檢測、`RegionCanvas`、`RecipeForm`、`ImageRegionsDialog` 見 PLAN-004） |
| `xrayvision/service/workspace.py` | 手動檢測工作區（PLAN-004）：每位使用者的影像、參數組、結果；不寫入正式紀錄 |
| `launcher/launcher.py` | 啟動器（Windows 服務主程式）：啟動平台服務、進版、退版 |
| `installer/xrayvision.iss` | Inno Setup 安裝腳本（由 build_release.py 呼叫） |
| `installer/scripts/` | 安裝版服務控制腳本（`service-control.ps1` 與 `start-service.cmd` 等），建置時複製到安裝目錄 `service\`，開始功能表有捷徑 |
| `tools/release/` | 原廠端發行建置與更新檔工具；`runtime-requirements.txt` 為產品執行環境的固定版本依賴 |
| `tools/license_admin/`、`tools/diag_replay/` | 原廠端授權簽發、問題回報包重現；`tools/keys/` 開發用私鑰（不納入版控） |
| `recipes/` | 配方 JSON（第 2 階段改由資料庫管理） |
| `tests/` | 單元測試、合成影像測試、`regression/`（回歸基準與比對） |
| `scripts/` | 開發用啟動／停止服務腳本（`start.cmd`、`stop.cmd`、`status.cmd`）；`start.cmd` 以 `dev_license.py` 自動簽發開發授權（開發私鑰，產品不變） |
| `image/Batch1` | 8-bit RGBA 轉存影像（非原始），10 張 |
| `image/Batch2` | 16-bit 原始影像，9 張；1.tiff 與 2.tiff 為同視野重拍，可做重複性驗證 |
| `temp/` | 暫存與輸出（不納入版控） |

常用指令（使用專案虛擬環境 `.venv`）：

```
.venv\Scripts\python -m xrayvision analyze image/Batch1 image/Batch2 --recipe recipes/bump_alignment_default.json --out temp/phase0
.venv\Scripts\python -m pytest                              # 全部測試（約 40 秒）
.venv\Scripts\python -m tests.regression.regress            # 回歸比對；演算法有意變更並經審閱後才加 --update
scripts\start.cmd                                            # 背景啟動開發服務（資料 temp\dev-data，埠 8600）
scripts\stop.cmd                                             # 停止開發服務
.venv\Scripts\python -m pytest -m "not slow"                # 不含端到端進版測試（約 1 分鐘）
.venv\Scripts\python -m pytest -m slow                      # 端到端進版／退版（實際啟動啟動器，約 3 分鐘）
.venv\Scripts\python tools\release\build_release.py --update-key tools\keys\update_private_DEV.pem   # 發行建置
```

- 不要用 `pip install -e .` 安裝本專案：可編輯安裝的匯入攔截會蓋過 `PYTHONPATH`，使端到端測試載入錯誤版本。
- embeddable Python 有 `._pth` 時忽略 `PYTHONPATH`；版本目錄的程式路徑寫在 `python312._pth`（`..\app`）。
- Inno Setup 裝在使用者層級：`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`；繁中語系檔取自 issrc `is-6_7_1` 標籤的 Unofficial 目錄。

開發規則：
- 改動演算法後必須跑回歸比對；結果改變時要說明原因，並經使用者同意才更新基準。
- 新增原因代碼或顯示文字時，同步更新 `xrayvision/i18n/zh-TW.json` 與 `en.json`。
- 模組版本：量測結果可能改變時至少提升次版號。

## 技術要點

- 影像檔內**沒有**拍攝參數（TIFF 只有尺寸與位元深度）。
- 同批影像亮度差可達 50% 以上。量測以吸收量（−ln I）加上逐顆局部正規化（背景 0、核心 1）處理，不使用絕對灰階門檻。
- 1.tiff 與 2.tiff 亮度差約 30%，晶片偏移量測仍一致（差 < 0.08 px），逐點相關約 0.92。管電壓變動的影響尚未驗證。
- 主要系統誤差來自輪廓高度的選擇：由 0.75/0.25 改為 0.7/0.3 或 0.8/0.2，結果變動約 ±0.2 px。需以設計尺寸或已知答案樣品校正。
- 露出弧模式（暗圓＋淡瓣）只適用 8-bit 轉存影像；用在 16-bit 影像會把 via 淚滴誤判為焊墊。
