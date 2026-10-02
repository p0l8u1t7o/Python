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
| P0 基準 | 遷移前各專案原有檢查紀錄＋各視角截圖，作為逐一比對的依據 | 進行中 |
| P1 骨架 | `core/vendor`、`loader.mjs`、統一伺服器 `serve.mjs`、`project.json`、importmap、移除 7 份 vendor／three-loader／serve.py、Pages 建置改用 `build-site.mjs` | |
| P2 共用模組 | 根目錄 `tools/` 共用檔與手動複製檔移入 core；`detail.js`（A／A+／B）、`kinematics.js`（A／B）合併；移除 sync 腳本與無用檔 | |
| P3 標準介面＋統一檢查 | 各專案 `web/js/project.js` 提供 `createProject()`；`window.sim` 標準化；core 檢查：全場干涉、重合面閃爍、倒序一致、瀏覽器載入與截圖；`core/tools/check.mjs` 依 `project.json` 一併執行專案自有檢查 | |
| P4 修正發現 | 各專案依新檢查修正閃爍與干涉 | |
| P5 渲染與 UI 共用 | `core/ui/stage.js`（renderer、對數深度、陰影、環境光、縮放、3D 標籤）；影片匯出改用掛鉤，不再字串修補 `main.js` | |
| P6 模型庫 | 手臂（FANUC R-2000iC、DENSO VS-068／VM-60B1／COBOTTA PRO 900／HSR065）、AGV、桶、圍籬、電控櫃、輸送、相機等移入 `core/models`；目錄頁 | |
| P7 新專案範本與文件 | `core/template` ＋ `new-project.mjs`；README | |

## 比對方式

- 每階段前後跑 `core/tools/shots.mjs`，逐張比對截圖（像素差異），再跑各專案原有檢查，結果需與 P0 相同。
- 刻意的外觀改變（例如修閃爍）在該階段紀錄中註明。

## 進度紀錄
