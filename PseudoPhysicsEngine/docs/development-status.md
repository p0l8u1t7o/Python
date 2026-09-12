# 開發狀態

> 最後更新：2026-09-13  
> 結論：可在目前環境完成的本機 MVP 核心已交付；外部 CAD／Robot／Blender／SolidWorks 工作保持為明確介面與可診斷阻塞，不宣稱已產出工程結果。

## 工作邊界

- 專案固定在 `D:\Working Space\Python\PseudoPhysicsEngine`。
- 不建立獨立 Git repository；保留父層 repository。
- Git 指令只從本目錄執行，並使用 `-- .` 限定本專案。
- Python 固定 3.12；套件由 uv workspace 與 `uv.lock` 管理。
- 架構為 FastAPI 模組化單體、SQLite、檔案 artifact store、React Web 與隔離 worker。

## 已完成能力

### 數位主線與資料契約

- Project 建立、清單、恢復與不可變 ProjectRevision。
- 右手 Z-up、mm、4×4 row-major／column-vector 座標規則。
- revision-bound frame tree：單一 root、父節點、cycle、穩定 UUID 與 transaction rollback。
- ChangeSet preview／apply：before-state、impact、人工核准、冪等、稽核紀錄與完整 revision snapshot copy；Web 可預覽、核准並建立下一版。
- Revision history 與結構化 diff，可比較 frame、artifact、ProcessSpec、MotionSpec 與 SceneAssemblySpec。
- ProcessSpec、MotionSpec、SceneAssemblySpec 保存；Scene node 會檢查同 revision 的 frame 與 artifact，Motion track 會檢查 Scene node。
- Revision review comment、回覆、解決流程，以及涵蓋寫入、驗證、發布與 Job lifecycle 的統一 audit trail。
- 版本化 Pydantic contract、JSON Schema 與自動產生的 TypeScript 型別；目前匯出 24 份 schema。

### Artifact 與 3D

- STEP／GLB／PDF 串流上傳、大小限制、內容簽章、GLB v2 header、SHA-256 與 content-addressed store。
- 檔名正規化、跨 project/revision 防護、受控下載與相同內容去重。
- lazy-loaded Three.js GLB viewer：Z-up、orbit controls、自動置中縮放、光影、錯誤狀態。
- MotionSpec 第一軌可在 viewer 播放；網頁可組裝 artifact/frame 對應的 Scene node、編輯單步 Process/Motion 基線並顯示 cycle time。

### 分析、驗證與發布

- DAG critical-path 計算，支援平行分支並回報 cycle time 與是否符合目標。
- 規則式 ValidationReport 會檢查 ProcessSpec／MotionSpec／SceneAssemblySpec／STEP／座標缺漏、
  Motion 與 Scene 關聯、週期超標、未決問題、未解決 review comments、assumptions 與 `INFERRED` 座標轉換。
- 每次 validation 均保存；rules worker 可透過 durable Job API 執行 validation。
- Release gate 會重新驗證；只有 PASSED revision 可鎖定為 RELEASED 並產生不可變 ReleaseManifest。
- ReleaseManifest 保存 approver、validation report、artifact URI、大小、MIME 與 SHA-256；重送具冪等行為。
- 控制點 Kabsch 剛體校正 API：至少三個非共線點，輸出 transform、逐點殘差、RMS、最大誤差與允收判斷。

### Durable worker 與操作腳本

- SQLite job 狀態：`PENDING → RUNNING → SUCCEEDED | FAILED | CANCELLED`。
- idempotency key、工具版本、claim、lease、heartbeat、逾期重領、最大重試、worker ownership 與結果 artifact 防護。
- 獨立 Python rules worker 只 claim `SIMULATE`，支援 `ppe-rules`；未設定的工具會明確失敗而非假裝成功。
- `start-dev.cmd`／`stop-dev.cmd` 管理 API、Web、rules worker 三個隱藏背景程序。
- 同一 PowerShell 可連續 start／stop；自動避開占用 port，以 PID、process name 與 start time 防止誤殺。
- runtime state 位於 `.local/run`，log 位於 `.local/logs`。

## 最終驗證基線

- Python 3.12.10、uv lock/sync：通過。
- Alembic：`0011_audit_events (head)`，本機由 0009 連續升級至 0011 成功。
- Ruff format/check：通過。
- mypy strict：79 個 source file 無問題。
- pytest：64 passed，涵蓋 unit、contract、SQLite integration、完整 revision copy、review/audit、release gate 與 worker/API 端到端。
- JSON Schema export：24 份成功。
- Web oxlint、TypeScript、Vite production build：通過。
- npm audit：0 vulnerabilities。
- 同終端一鍵實測：API 8123、Web 5223、rules worker 成功啟動、健康檢查通過並全部安全停止。

## 外部阻塞與完成介面

以下工作不能在缺少實體輸入或合法工具環境時做可信驗收，因此不列為已完成工程輸出：

| 項目 | 目前證據 | 已備妥介面 | 解鎖所需資料／環境 |
|---|---|---|---|
| STEP → B-Rep → GLB tessellation | 無 Robot／輸送機 sample STEP；CMake/CAD kernel 未安裝 | `TESSELLATE` Job、artifact input/result、GLB viewer | 合法 sample STEP、選定 CAD kernel 與允收 bounding box／面數 |
| Robot reachability／碰撞／軸限位 | 未指定品牌、型號、軸數或運動學 | `SIMULATE` Job、MotionSpec、ValidationReport | Robot 型號、URDF/DH、軸限位、tool/frame、官方 simulator 或核准 solver |
| Blender MP4 | `check-environment.ps1` 顯示 Blender 未安裝 | `RENDER` Job、artifact result contract | 固定 Blender 版本、可重現場景與 MP4 驗收條件 |
| SolidWorks／Parasolid／SLDPRT／SLDASM | 無 SolidWorks 版本、授權或 Desktop API | `EXPORT` Job、ReleaseManifest；不接受未信任原生檔上傳 | 合法席次、指定版本、輸出優先順序與重開驗證環境 |
| 10～20 個受控模組庫 | 尚無模組 CAD 與參數規格 | SceneAssemblySpec 與 artifact ownership | 模組清單、CAD、安裝介面、參數範圍與碰撞幾何 |
| 廠務實測校正 | 無控制點資料與公差 | `/revisions/{id}/calibrate` 與合成 golden tests | 控制點格式、RMS／最大殘差允收門檻 |

## 尚需人工補驗

- 本次 Codex Browser runtime 沒有可連線的瀏覽器實例，因此無法在此工作階段做像素級互動驗收；Web 已通過 lint、TypeScript 與 production build。
- 真實 CAD 幾何、Robot 求解、Blender 影片及 SolidWorks 重開只能在上表資源到位後執行 golden／smoke test。

## 下一次開工條件

提供任一外部項目所需資料後，可沿既有 Job／Artifact contract 新增對應 adapter，不需改寫 Project、Revision、validation 或 release 核心。優先順序建議為：合法 sample STEP → 指定 Robot 運動學 → Blender → SolidWorks。
