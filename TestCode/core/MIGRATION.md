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
  - 兩套基本形狀並存：`primitives.js`（block／cylinder／decal…）與 `parts.js`（MAT／box／cyl／plate…）。→ 2026-10-03 第二輪統一為 `shapes.js`＋`materials.js`。
- 2026-10-03 P3（95578342）：`core/verify/{scene,determinism,run,dom-stub}.mjs`；化學桶改用 `project.js`，舊的 `tools/verify-scene.mjs` 退役。dom-stub 讓瀏覽器才有的文字牌也進檢查，抓到「取桶位／放回位」牌在夾爪路徑上（已移到輸送架下方）。其餘 6 專案由平行代理各自完成 project.js、main.js 接上、修正 scene 發現。
- 2026-10-03 P5／P6／P7 先行（2595b72f、73d5d9f9、27b9886a）：stage／player／track、範本與 new-project、模型庫（輸送線、龍門、標準件）＋目錄頁＋models 檢查；Pages 不再發布 verify 與 review。範本產生的專案通過全部 core 檢查；檢查也抓到範本初稿的 2 組重合面與龍門原點超出行程。
- 2026-10-03 收尾：
  - 檢查規則修正：`bodyOf` 為 null 時「同一剛體」誤放行（固定件之間、頂層移動件對固定件），修正後各專案抓到大量真問題並全部處理；另加曲面／開孔擠出件頂點複核、線材端點與小型配線五金規則、自轉件歸屬、快取（MGPC 由 2 小時以上降到 90 秒）。
  - 部署前快速檢查加入 scene（干涉＋閃爍）。
  - 已知待實機確認：PCB S1／S3 相機與 S2 Y 軌間隙 1.75 mm；MGPC 週期 329.75 → 347.75 s。
  - 待延伸：各專案的 3D 標籤、視角轉場仍是自己的寫法（行為與 stage 版略有不同）；兩套基本形狀（primitives／parts）並存。
- 2026-10-03 第二輪統一（使用者選：四項全做、允許小幅外觀改變、一次做完）：
  - 形狀：`shapes.js`＋`materials.js` 取代 parts／primitives（codemod-shapes.py 自動轉換，91 張截圖不變）。
  - 排程：`createStepSequence`（SSD、快門、MGPC、WPM、滴定手臂）與 `createTimeline`（化學桶、PCB、滴定轉盤與滴定頭）；統一事件格式 `{time,dur,label,sub,station}`。各站排程結果與改寫前逐位元／1e-7 相同。
  - 介面：7 站播放列改用 `createPlayer`，標籤 `stage.addLabel`，視角 `stage.goTo`；化學桶相機視窗改用 viewer-workspace，`view-controls.js` 刪除。WPM 的 2D 模擬相機維持專案自有。
  - 材質：常見材質改用 MAT，框架、儀表盤等外觀略有變化（各站截圖差異已逐張檢視）。
  - 代理回報的 core 補強建議（尚未做）：標籤自動加畫布偏移（6 站各自補正）、player 的到位閘門／loop／speed getter／select 速度、步驟逐鍵緩動與 latch／retime／rollback、stage 取消轉場與 shiftView、Track.at(T)、MAT.frame（0x6b7480）／chrome／帶細紋材質、viewer-workspace 的 focusOffset 函式與 startFollowing、2D 影像來源、verify-cables 改讀 tr.steps 後移除 PCB 的 segs 別名。
- 2026-10-03 精進輪（使用者選：四項全做、做完更新 Pages）：
  - core（07b00ea1）：player 的 `advance`／`loop`／`<select>` 速度／`speed`；標籤自動加畫布偏移與 `anchor`；`stage.cancelTween`／`shiftView`；`createStepSequence` 的 `latch`、逐鍵緩動、`peek`、`mark`／`rollback`、`retime`、`nested`；`Track.at(T)`；`MAT.frame`／`chrome`／`finished()`；viewer-workspace 的 `renderImage`／`setSources`／`startFollowing`／focusOffset 函式。
  - 7 站改用（ced15a38 化學桶、3dfc1a3a PCB、318e5f8a WPM、5d72ca9f 快門、ab2db938 滴定、864a053d 軍規、6592d70c SSD）：各站排程指紋、review JSON、專案檢查與改前相同；外觀差異只在改用 MAT.frame／chrome／finished 的框架、銷、鋁件。
  - 收尾補 core：上一步改為逐步回退（短步驟不再被跳過）；追隨目標離線後重新出現時平移回目標（化學桶的 focusAbsent 變通寫法移除）；獨立相機視窗的 2D 影像也更新標題時間；player 加 `apply` 的 `dt`、`onChange` 的 `seek`、`maxStep`（軍規的 stepDt／seeking／自拆子步移除）；`createStepSequence.add` 由 O(n²) 改用 Set；滴定、軍規樣式表中被 stage 覆蓋的 `.label3d` transform 移除。
  - 仍在專案內（刻意）：各站手臂 IK／PTP 規劃與到位判斷規則、SSD 的 `resume()`、各站自己的光源與產品外觀。
- 2026-10-03 第四輪（使用者選：手臂到位閘門、標準互動測試、光源與地面預設、favicon，另加「手機、平板等小螢幕可以順利觀看」）：
  - 到位閘門（43376644）：`core/anim/arrival.js` 的 `createArrivalGate`；MGPC、SSD 的網頁與 `tools/verify.mjs` 共用各站 `sequence.js` 的 `ARRIVAL`，9 支工具輸出逐字相同。
  - 小螢幕（d7e68b64、0af3983f、365678c0）：stage 的 `narrowFit`（窄畫布拉遠，旋轉時依視角的 `fit` 重算，霧與 maxDistance 一起放大）、標籤避讓（精簡版面時依 priority）；viewer-workspace 精簡版面擴及觸控平板 ≤1100 px，大平板加大點按目標，觸控裝置預設不開相機視窗；播放設定展開時步驟列緊接播放列；橫向手機的側欄與電控面板改為右側面板；手機直向電控面板精簡。
  - 光源與地面：`createStage({ look, extent })`（cell／plant／studio）、`core/geom/environment.js` 的 `floor()`。7 站都改用 look；`extent` 推算的燈位與各站手調值不同，為了桌面畫面不變，各站保留原本的燈位與陰影。地面：Acid、MGPC、PCB、SSD、快門改用 `floor()`，WPM 用 `material` 保留展示地面，化學桶的廠房地坪維持專案自建。
  - 標準互動測試：`core/tools/ui-check.mjs`（桌面、手機直向、手機橫向、觸控平板 × 載入、溢出、畫布、播放、步驟、視角、側欄、標籤、點按目標、?movie），接進 check.mjs 完整檢查的 `ui`（`UI_PORT`），結果在各站 `review/ui-check.json`。7 站四種尺寸全過。
  - favicon：`core/favicon.svg`，首頁、目錄頁、7 站與範本都連上。
  - 範本改為標準版面（viewer-workspace、look／extent、floor、標籤 priority），並修掉範本原本的靜態相撞（龍門 offset 300→400）；new-project 依檔案類型跳脫標題；`createTimeline` 補上 `stationStart`。
  - 桌面截圖：各站與第四輪前的 HEAD 逐張比對，差異 0；刻意改動只有 WPM 工件跟拍（原本同一格先跳播再切視角會空白）與 MGPC 手臂取景說明文字（原本壓在影像資訊框上，改到影像左下角）。
