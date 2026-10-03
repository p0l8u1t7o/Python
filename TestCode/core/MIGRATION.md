# TestCode 3D 動畫統一框架：遷移計畫與進度

2026-10-03 拍板（選項對話）：
- 單一 `core/` 直接引用（importmap `@core/`），不再複製同步；
- 7 個專案一次全部遷移；
- 本機跑完整檢查，Pages 部署前跑快速檢查，沒過就不發佈；
- 共用 3D 模組用程序式 JS，統一 `createX(參數) → { root, set(state), meta }`，另做模型目錄頁。

## 網址與檔案配置（本機與 Pages 相同）

| 網址 | 本機來源 | 說明 |
|---|---|---|
| `/` | 由 `core/tools/site.mjs` 產生 | 展示首頁 |
| `/core/…` | `core/` | 共用模組與 three.js（只發佈一份） |
| `/<專案>/…` | `<專案>/web/…` | 各專案頁面 |

各專案 `index.html` 的 importmap 一律寫成：
`three` → `../core/vendor/three.module.js`、`three/addons/` → `../core/vendor/addons/`、`@core/` → `../core/`。
Node 端由 `core/tools/loader.mjs` 解析相同的三種名稱，檢查程式直接載入網頁用的同一份模組。

## 階段

| 階段 | 內容 | 狀態 |
|---|---|---|
| P0 基準 | 遷移前各專案原有檢查紀錄＋各視角截圖，作為逐一比對的依據 | 完成 |
| P1 骨架 | `core/vendor`、`loader.mjs`、統一伺服器 `serve.mjs`、`project.json`、importmap、移除 7 份 vendor／three-loader／serve.py、Pages 建置改用 `build-site.mjs` | 完成 d1392707 |
| P2 共用模組 | 根目錄 `tools/` 共用檔與手動複製檔移入 core；`detail.js`（A／A+／B）、`kinematics.js`（A／B）合併；移除 sync 腳本與無用檔 | 完成 03b6af01 |
| P3 標準介面＋統一檢查 | 各專案 `web/js/project.js` 提供 `createProject()`；`window.sim` 標準化；core 檢查：全場干涉、重合面閃爍、倒序一致、空間檢核；`check.mjs` 依 `project.json` 執行專案自有檢查；情境（variants）與分模組門檻 | 完成（7 專案） |
| P4 修正發現 | 各專案依新檢查修正閃爍與干涉 | 完成：7 專案 scene 全 0（PCB S1／S3 改懸臂、MGPC 加步驟並移 S3，均經使用者決定） |
| P5 渲染與 UI 共用 | `core/ui/stage.js`、`player.js`；錄影改用 `?movie` 掛鉤（`core/movie`） | 完成：7 專案改用 createStage＋exposeSim，截圖逐張差異 0 |
| P6 模型庫 | 手臂、AGV、桶、輸送、龍門、標準件移入 `core/models`；目錄頁 | 完成：12 個模型（FANUC R-2000iC、DENSO VS-068／VM-60B1／COBOTTA PRO 900／HSR065、AGV、200L 桶、輸送線、龍門、4 標準件） |
| P7 新專案範本與文件 | `core/template` ＋ `new-project.mjs`；README | 完成 |

## 比對方式

- 每階段前後跑 `core/tools/shots.mjs`，逐張比對截圖（像素差異），再跑各專案原有檢查，結果需與 P0 相同。
- 刻意的外觀改變（例如修閃爍）在該階段紀錄中註明。

## 進度紀錄

- 2026-10-03 P0：26 支專案檢查＋4 支根目錄檢查全數通過；`TEMP/shots-base`（91 張）重拍兩次差異 0，可作基準；`TEMP/review-base` 為 review JSON 基準（`core/tools/compare-review.py` 比對，忽略時間與雜湊欄位）。
- 2026-10-03 P1（d1392707）：截圖 91 張差異 0、檢查 33/33、review 結果相同。另刪除 MonocularDepthEstimation（性質不同，b575e21d）。
- 2026-10-03 P2：`core/electrical`（線材、電盤、元件、檢視器）、`core/ui`（viewer-workspace、vision-overlay、view-controls）、`core/geom`（primitives＝原 detail A+、parts／hardware＝原化學桶 parts／detail、finish、surfaces、perforated）、`core/robot/kinematics.js`（合併 A／B，B 的參數改由化學桶 robot.js 傳入）。刪除根目錄 tools 的 7 個正本與 3 支 sync 腳本、3 份未使用的 camera-panel.js。截圖差異 0、檢查 33/33＋根目錄 4 支、review 結果相同。
  - 原 detail A 的專案（滴定、軍規、PCB）改用 A+，`tube()` 多了陰影；截圖差異在門檻內。
  - 兩套基本形狀並存：`primitives.js`（block／cylinder／decal…）與 `parts.js`（MAT／box／cyl／plate…）。統一留到 P6 模型庫時決定。
- 2026-10-03 P3（95578342）：`core/verify/{scene,determinism,run,dom-stub}.mjs`；化學桶改用 `project.js`，舊的 `tools/verify-scene.mjs` 退役。dom-stub 讓瀏覽器才有的文字牌也進檢查，抓到「取桶位／放回位」牌在夾爪路徑上（已移到輸送架下方）。其餘 6 專案由平行代理各自完成 project.js、main.js 接上、修正 scene 發現。
- 2026-10-03 P5／P6／P7 先行（2595b72f、73d5d9f9、27b9886a）：stage／player／track、範本與 new-project、模型庫（輸送線、龍門、標準件）＋目錄頁＋models 檢查；Pages 不再發布 verify 與 review。範本產生的專案通過全部 core 檢查；檢查也抓到範本初稿的 2 組重合面與龍門原點超出行程。
- 2026-10-03 收尾：
  - 檢查規則修正：`bodyOf` 為 null 時「同一剛體」誤放行（固定件之間、頂層移動件對固定件），修正後各專案抓到大量真問題並全部處理；另加曲面／開孔擠出件頂點複核、線材端點與小型配線五金規則、自轉件歸屬、快取（MGPC 由 2 小時以上降到 90 秒）。
  - 部署前快速檢查加入 scene（干涉＋閃爍）。
  - 已知待實機確認：PCB S1／S3 相機與 S2 Y 軌間隙 1.75 mm；MGPC 週期 329.75 → 347.75 s。
  - 待延伸：各專案的 3D 標籤、視角轉場仍是自己的寫法（行為與 stage 版略有不同）；兩套基本形狀（primitives／parts）並存。
