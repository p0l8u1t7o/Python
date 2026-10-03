# 自動化設備 3D 展示 — 專案記憶

這個庫原本是 `Python` 庫底下的 `TestCode/`，2026-10 搬成獨立庫（從頭開始，舊歷史留在原庫）。以下是之前累積、新 session 需要知道的事。框架細節以 `core/README.md` 為準，改版紀錄在 `core/MIGRATION.md`。

## 與使用者合作的方式

- **語言**：一律用繁體中文（台灣用語）回覆。程式碼、指令、檔名保持英文；程式註解用繁體中文；commit 訊息用英文。
- **要拍板的事用選項對話**（AskUserQuestion）：設計取捨、方案選擇都整理成 1～4 題、每題 2～4 個選項，推薦項放第一並標「（建議）」。有合理預設值的小事不必問。
- **提交與推送**：階段完成、檢查通過就直接 commit，不必問。**推送只在使用者要求時才做**；推送到 `main` 會觸發 Pages 檢查與發布。
- **不進版控**：各專案 `docs/`（使用者給的圖面、照片、影片、規劃與成本資料）、`TEMP/`、`question_log.txt`、ffmpeg 執行檔。新專案的 `docs/` 也要加進 `.gitignore`。
- **使用者自己也會改檔、提交**：改檔前先看 `git status`。有未提交改動的檔案**絕對不要** `git checkout`／`restore`／`stash`（曾經這樣弄丟過工作，只能事後重做）。
- 使用者要求「先討論不改」時，只討論、不動檔案。

## 環境

- 安裝：`powershell -ExecutionPolicy Bypass -File setup.ps1 [-All]`，需求見 `REQUIREMENTS.md`。
- **3D 專案只需要 Node.js 22 以上**（開發機 24.21），沒有 npm 套件；three.js 放在 `core/vendor/`。瀏覽器檢查用 Chrome 或 Edge（可設 `CHROME_PATH`）。
- Python 3.12 ＋ `requirements.txt` 只給選用工具用（錄影稽核、電路圖、成本表）。
- Node 端跑 core 模組要加 `--import ./core/tools/register.mjs`（解析 `three` 與 `@core/`）。`core/tools/run.mjs` 會自動加上。
- Shell 是 Windows 上的 Git Bash 或 PowerShell 5.1。

## 結構

| 位置 | 內容 |
|---|---|
| `core/` | 共用框架（以 importmap `@core/` 引用）：geom（形狀、材質、五金、地面）、models（12 個參數化模型＋目錄頁）、anim（時間軸、步驟序列、到位閘門）、ui（stage、player、viewer-workspace）、electrical、movie、verify、template、tools |
| `<專案>/` | `web/`（網站；`web/js/project.js` 是網頁與檢查共用的場景）、`project.json`（首頁說明、`checks.quick`／`checks.full`、`variants`、`ui`）、`tools/`（專案自有檢查）、`review/`（檢查結果，進版控）、`docs/`（只留本機） |
| `tools/` | 跨專案工具：配線、電盤、干涉回歸、電路圖、錄影輸出、搬庫腳本 |
| `.github/workflows/pages.yml` | PR 跑快速檢查；推送到 `main` 時快速檢查、建置、發布 Pages |

7 個專案：AutomaticAcid-BaseTitration（酸鹼滴定）、ChemicalTankWashing（200L 化學桶清洗線）、MilitaryGradePC（軍規筆電 QC 線）、PCB-CopperAssembly（散熱銅片植入）、RobotArmPressSSD（USB 接頭壓合）、shutter assembly（快門葉片組裝，資料夾名稱有空白）、WorkpieceMeasurement（杯體 AOI＋共焦量測）。

## 常用指令

```powershell
node core/tools/serve.mjs                         # http://127.0.0.1:8770/（首頁、/core/catalog/、/<專案>/）
node core/tools/check.mjs [專案…] [--quick] [--only 名稱]   # 統一檢查
node core/tools/ui-check.mjs <專案> --port <p> --shots TEMP/<資料夾>   # 四種尺寸互動測試＋截圖
node core/tools/shots.mjs [專案…] --out TEMP/<新> --compare TEMP/<基準> --port <p>   # 桌面截圖回歸
python core/tools/compare-review.py TEMP/<review 基準>   # review JSON 比對（忽略時間與雜湊）
node core/tools/new-project.mjs <資料夾> "<標題>" ["一句說明"]   # 由範本建立新專案
node --import ./core/tools/register.mjs tools/verify-cable-routing.mjs   # 也有 verify-interference、verify-electrical-plan
```

## 框架慣例（詳見 core/README.md「統一寫法」）

- **專案介面**：`project.js` 匯出 `createProject({ scene, ...params })`，回傳 `{ total, apply(t), layoutChecks?, verify }`。`verify` 包含 `skip`、`moduleOf`、`stationOf`、`allow`（必須寫原因）、`thresholds`、`envelope`。
- **形狀與材質**：`core/geom/shapes.js`、`materials.js` 的 `MAT`（含 `frame`、`chrome`）、`finished(MAT.alu, 'metal')`；地面用 `environment.js` 的 `floor()`。
- **排程**：
  - 單一手臂用 `createStepSequence`：`discrete`、`latch`、`nested`、`ease`／`easeKeys`、`peek`、`mark`／`rollback`、`retime`。
  - 多台並行用 `createTimeline`：`Track.at`、`stationStart`。
  - 兩者都提供 `events`、`stationStart`、`total`。
- **播放列**：`createPlayer({ apply(T,{seek,dt}), advance, maxStep, onChange(T,s,{seek}), loop })`。手臂要等到位的站用 `createArrivalGate`（`core/anim/arrival.js`），規則 `ARRIVAL` 放在該站的 `sequence.js`，網頁和 `tools/verify.mjs` 共用。
- **舞台**：
  - `createStage({ look: 'cell'|'plant'|'studio', extent? })`。
  - `addLabel(html, pos, cls, { anchor, priority })`。
  - `goTo(p, t, instant, dur, { fit })`、`cancelTween`、`shiftView`。
  - 窄畫布會自動拉遠（`narrowFit`），霧與 maxDistance 一起放大；精簡版面時標籤自動避讓（`declutter`）。
  - 視角可以回傳 `[位置, 注視點, { fit }]`。
- **版面**：骨架固定為 `#topbar`（`.brand`、`#stations`、`.views`）、`#side`／`#left`、`#bottombar`，並呼叫 `createViewerWorkspace`。
  - 精簡版面的觸發條件：≤900 px、觸控平板 ≤1100 px、橫向手機。
  - 精簡版面的操作：☰ 開製程與視角、⚙ 開播放設定、工具列開側欄。抽屜開啟時，`uncover` 會讓出畫面。
  - 專案 CSS 不要再寫隱藏或縮小這些區塊的窄螢幕規則。
- `window.sim` 用 `exposeSim(...)`；錄影在 `?movie` 時呼叫 `installMovie`。每頁都要連 `../core/favicon.svg`。
- **共用功能優先放 core**：專案內發現可共用的寫法，先在專案暫代，再搬進 core，然後各站改用。

## 檢查與回歸的做法

- **`check.mjs` 內建項目**：`imports`、`determinism`、`layout`、`scene`（干涉＋閃爍，部署前也會擋）、`ui`（只在完整檢查跑；平行執行時設 `UI_PORT`），再加上 `project.json` 列的自有檢查。core 本身另有 `models` 檢查。
- **改 core 或渲染時**：
  1. 先拍基準：`git worktree add <暫存資料夾> HEAD`，在 worktree 裡跑 `shots.mjs --out TEMP/shots-<名>-base`，用完 `git worktree remove`。
  2. 改完比對：7 站桌面截圖要 0 張超過門檻。刻意的外觀改變要逐張看過，並記進 `core/MIGRATION.md`。
- **review JSON**：只有時間戳、`seconds`、`generated` 改變的，提交前先還原。有實質內容變化的才提交。根目錄 `tools/review/*.json` 的 sourceHash 會隨程式改變，連同程式一起提交。
- **allow 規則**：必須窄，而且要寫原因；不能用 allow 蓋掉真問題。看到「0 筆干涉」時要先確認規則本身沒有放水。過去 `bodyOf` 為 null 時 `null===null` 讓固定件之間全部放行，修正後抓到大量真問題。
- 閃爍的根因通常是重合面，對數深度緩衝解決不了，要改幾何。
- 完整檢查（全部專案）要數十分鐘，MGPC 的 scene 約 90 秒，可以放到背景執行。

## 平行代理的慣例

- 每站只派一個代理，**代理只改自己那站**加上 `TEMP/<簡稱>*`；core 由主 session 修改。
- 每個代理分配不同的 port 區段（避開 8770、8771、8790），`UI_PORT` 與 `shots --port` 也要錯開。
- 代理不 commit、不 checkout。主 session 審過回報後，重新產生 `ui-check.json`、還原只有時間戳變動的 review，再逐站提交。
- 代理提出的 core 建議，由主 session 判斷後統一實作，再讓各站改用。

## 踩過的坑

- **Git Bash heredoc 會吃掉 `\n`、`\t`、`\\`**：含反斜線的內容用 Write／Edit 工具寫。經 heredoc 交給 Python 的替換字串也可能出錯，寫完要檢查結果。
- **PowerShell 5.1 讀沒有 BOM 的 UTF-8 腳本會變亂碼**：`.ps1` 一律存成 UTF-8 BOM。
- **`export { X } from '…'` 不會建立本地綁定**：本檔要用的話，先 import 再 export。
- **化學桶用按需重繪（onDemand）**：狀態改變要 `invalidate`。標籤等每格的量測不能依賴下一格補正。
- **GitHub API 未登入每小時只能呼叫 60 次**：監看 Actions 時輪詢間隔至少 30 秒。
- **review JSON 不要寫入耗時**：`run.mjs` 已經拿掉 `seconds`，否則每次跑檢查都會產生差異。
- **Windows 的 casadi＋nlopt**：import cadquery 後 python.exe 結束時可能崩潰。之後做 STEP 轉換時要注意，解法是替換 nlopt。

## 各站的使用者拍板紀錄

- **PCB-CopperAssembly**
  - S1、S3 改成完全懸臂，配置不變。相機與 S2 Y 軌的間隙只剩 1.75 mm，待實機確認。
  - 全部孔都放。以配方驅動：長圓 138 孔＋圓孔 72 孔，其中圓孔為假設值。
  - 雙龍門每頭 4 吸嘴，節拍約 54 s。
- **MilitaryGradePC**
  - 全部修，可以加步驟、可以調站位：S3 移到 x 1150，週期從 329.75 s 變成 347.75 s。
  - 選型：DENSO VM-60B1＋RC8A、Keyence KV-X、IDS GigE 相機。
  - 待用 DENSO CAD 核對關節零點與尺寸。
- **ChemicalTankWashing**
  - 穿梭車密集架、龍門翻轉、自動開蓋、FANUC R-2000iC/165F 沖洗。
  - 約 24 桶／h，週期 753.1 s。
  - 西牆捲門待現場確認。
- **RobotArmPressSSD**
  - 標準是 8 頭整排壓墊（SSD 用快拆單點）、全局相機、DENSO VS-068。
  - 其他機種用假設值。
- **shutter assembly**：DENSO HSR065 SCARA、吸塑盤雙抽屜、上視補正，23.8 s／顆。待使用者提供葉片圖面。
- **AutomaticAcid-BaseTitration**：COBOTTA PRO 900、Metrohm tiamo 主案、5 mL 移液模組、單一滴定頭，整批約 93 分。
- **WorkpieceMeasurement**
  - 照規格書做半自動；只做殼體 A／B／C。
  - 與規格書不同的地方已列在 README。規格 A 底孔、規格 C 口部依圖面判讀，待原始圖檔確認。
- **框架**
  - 4 輪統一：P0～P7、第二輪、精進輪、第四輪。第四輪內容是到位閘門、小螢幕、look 加地面、ui-check、favicon。
  - `extent` 推算的燈位對不上各站手調的值，所以各站只用 `look` 省掉配色設定。

## 待辦與規劃

1. **子專案開發規則（搬庫後要做，動工前先用選項對話確認範圍）**
   - 規則檔：`AGENTS.md`（`CLAUDE.md` 以 `@AGENTS.md` 引用），以及範本產生的子專案 `CLAUDE.md`。
   - 子專案代理只能改自己的資料夾。core 缺功能時，先本地暫代並登記在 `core/REQUESTS.md`，再由單一的 core 維護 session 實作（基準截圖＋全專案檢查）。
   - 工具：`core/tools/check-scope.mjs`、`install-hooks`（pre-commit）、PR CI 的範圍檢查；選用 Claude Code 的 PreToolUse 寫檔關卡。
   - 開發 DAG：規格 → new-project → 盤點 core → project.js → 排程 → main.js 與 verify（可平行）→ check → 截圖 → commit → PR → Pages。
2. **3D 動畫生成應用程式**：計畫書在本機 `TEMP/3d-app-plan.md`（不進版控）。
   - 已拍板：
     - 給公司內部同事用，Claude Code 與 Codex 並行，Electron 外殼，第一版就含電控與相機。
     - 依角色指定模型（plan、build、render、review、fix），並有獨立的渲染與細節補強流程。
     - 上傳檔只留本機；成品可匯出網站壓縮檔、MP4、內部 Pages、單一 HTML。
     - core 自動升級並自動驗證；同事之間用專案交接包。
     - P2 驗收重做 MGPC 與快門，再加 1 個新案。
     - STEP 輸入排進 P4；效能預算採中等；審查角色每段自動執行。
   - 順序：搬庫 → 子專案規則 → 命令列原型（雙 CLI 轉接、品質迴圈、提問機制、角色指派）→ P2 驗收 → Electron 外殼與第二段能力 → 內部安裝與更新。
   - 仍待提供：P2 新案的規格、內部 Pages 的發布目標、單一 HTML 的大小門檻。
