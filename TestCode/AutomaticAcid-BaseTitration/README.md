# 酸鹼自動滴定：機械手臂前處理系統 3D 模擬

用 DENSO COBOTTA PRO 900 取代人員，完成滴定前處理，再交給 Metrohm 自動進樣器與滴定儀分析。一批 6 瓶樣品（3 × 500 mL、3 × 100 mL），每瓶取兩次，共 12 次滴定。前處理包括：

- 讀條碼
- 開蓋
- 空杯秤重
- 移液潤洗與取樣 20 mL（機器人專用 5 mL 移液模組，4 × 5 mL）
- 樣品秤重
- 放入進樣器
- 關蓋
- 分析完成後取杯

整合軟體是主控。Metrohm 以 tiamo＋Titrando 為主案（Remote Box＋樣品表／結果檔），OMNIS 列為備案。滴定前由滴定頭加純水 50 mL。所有 Three.js 依賴在 `web/vendor`，可離線執行。

方案說明、配置、時間、Metrohm 整合、選型與待確認事項見 [系統規劃](docs/system-plan.md)。用戶提供的流程在 `docs/酸鹼自動滴定-機械手臂規劃-0828.pptx`。

## 結果（模擬）

| 項目 | 數值 |
|---|---|
| 整批時間 | 約 93 分鐘（第一杯 3.9 分鐘開始滴定，之後每 7 分 24 秒一杯） |
| 手臂前處理 | 每瓶約 6.9 分鐘，6 瓶共 41.5 分鐘；手臂忙碌約佔 47% |
| 瓶頸 | 滴定（每杯 7 分鐘）；已決定維持單一滴定頭 |

## 啟動

```powershell
node ../core/tools/serve.mjs AutomaticAcid-BaseTitration
# 或不自動開外部瀏覽器
node ../core/tools/serve.mjs AutomaticAcid-BaseTitration --no-open
```

開啟 [本地模擬](http://127.0.0.1:8770/AutomaticAcid-BaseTitration/)，也可雙擊 `run.bat`（所有專案共用 `core/tools/serve.mjs`，首頁 http://127.0.0.1:8770/ 列出全部專案）。ES module 需 HTTP，請勿直接用 `file://` 開啟 HTML。

## 操作

- **時間軸**是整批約 93 分鐘，播放列為共用的 `core/ui/player.js`。預設 5 倍速（速度選單選定的選項，`?speed=` 優先）；勾選「等待時加速」時，手臂等待分析的時段再加快 10 倍（player 的 `advance`）。下拉選單與 ‹ › 依排程的流程節點（每瓶、每杯的各步驟）跳轉。
- **上方流程按鈕**對照用戶文件的步驟（①初始化 … ⑨分析・取杯），按下跳到下一次出現的時間點。⑦（第二杯重複 ②④⑤⑥）沒有自己的步驟，所以沒有按鈕。
- **視角**：全景、天平、開蓋、移液、進樣器、跟隨手臂、俯視。
- **整合方式**：選單切換 tiamo／OMNIS，通訊紀錄與電腦畫面跟著改。
- **左側**：
  - 樣品表：空杯重、淨重、進樣器位置、狀態、結果。
  - 通訊紀錄：整合軟體與手臂、天平、移液模組、讀碼器、Metrohm 之間的訊息。
- **右側**：
  - 目前動作。
  - 滴定曲線（pH 對滴定液體積）。
  - 天平讀值。
  - 交握訊號。
- 「匯出紀錄」產生 JSON，內容是樣品表、滴定排程與通訊紀錄。**全部是模擬值，非實測。**

網址參數：`?t=600&pause&view=sampler`、`?mode=omnis`、`?speed=30`、`?shadow=0`；主控台：`window.sim.seekTo(sec)`、`setView(name)`、`plan`（`plan.events`、`plan.stationStart`、`plan.total` 為共用事件介面，`plan.timeline` 為進樣器時間軸）。station 即用戶文件的流程編號：1～6、8、9，10 為 Cycle Complete；0 與 7 沒有步驟，`stationStart[0]`、`[7]` 是空位。

展示影片：開 `?pause&movie`，`main.js` 不跑一般迴圈，改載入 `core/movie/movie.js` 的 `installMovie`（逐格取樣排程、秤重步驟對準天平秤盤、其餘跟隨目前的杯／瓶），頁面下方出現影片預覽與輸出按鈕；此時舞台強制開對數深度。

## 檔案

| 檔案 | 用途 |
|---|---|
| `web/js/layout.js` | 站別位置、器皿尺寸、時間與速度參數、樣品批次 |
| `web/js/robot.js` | COBOTTA PRO 900 模型、逆解（肘部朝上、J1 固定角度窗）、長行程夾爪 |
| `web/js/lab.js` | 地坪（`core/geom/environment.js` 的 `floor()`：9 × 7 m、100 mm 格、格線 9 m 見方高 1 mm，地坪與格線顏色沿用本站原本略深的 0x1a1f26／0x2c3440、0x222831）、實驗桌、天平、樣品瓶座、移液區（廢液漏斗、吸頭廢料口、吸頭架、移液模組座）、讀碼器、料架、Metrohm 進樣器與滴定儀、電腦、安全掃描器、器皿 |
| `web/js/plan.js` | 手臂動作序列（逐步計算 PTP 與直線移動時間，直接寫入 `core/anim/sequence.js` 的 `createStepSequence`；進樣器區先試排，撞到轉盤轉動時用序列的 `mark()`／`rollback()` 退回重排；station＝流程編號 ①～⑨）、轉盤與滴定頭排程（`core/anim/track.js` 的 `createTimeline`，rack／head 兩條軌）、樣品表與通訊紀錄 |
| `web/js/sim.js` | 把排程在任一時間的狀態套到場景（畫面與驗證共用） |
| `web/js/project.js` | 專案介面 `createProject({ scene })`：建立場景、`apply(t)` 套到時間 t，並提供 core 全場檢查的設定（非實體物件、設備分工位、逐條說明的允許接觸）；`main.js` 與 core 檢查共用同一份場景 |
| `web/js/main.js` | renderer、場景、相機、軌道控制、環境光與主要燈光由共用舞台 `core/ui/stage.js` 的 `createStage` 建立：`look: 'cell'` 給背景、環境光與補光配色強度，本站只寫與 look 不同的曝光（1.0）、環境點光（240）、暖色主光（0xfff8ef、1.25）與霧；主光／補光位置與陰影範圍是本站手調值，不用 `extent` 推算（推算結果會改變桌面陰影）；滴定杯補光（貼著杯座的小陰影相機）放在 `extraLights`。標籤避讓用 core 預設（精簡版面或畫布 < 900 px；本站桌面畫布約 960 px，不會避讓）；手臂（`priority` 2）與天平、進樣器、滴定儀（1）的標籤在小畫布優先保留；畫面迴圈用 `stage.loop`，3D 標籤用 `stage.addLabel`（`anchor: 'above'`，畫布偏移由 stage 處理），固定視角（`VIEWS`）用 `stage.goTo`、停止轉場用 `stage.cancelTween`、液面俯拍跟著液面平移用 `stage.shiftView`，`window.sim` 用 `exposeSim`；播放列用 `createPlayer`；液面俯拍、跟隨手臂、流程按鈕、樣品表、滴定曲線、交握訊號、通訊紀錄、匯出為本站自有；場景物件取自 `project.js` |
| 材質 | 桌架、不鏽鋼件（`finished(MAT.steel, 'metal', .008)`）、黑件、狀態燈、安全掃描器、夾爪陽極件用 `core/geom/materials.js` 的 `MAT`；灰色件（電控箱、防風罩框、夾爪座、鍵帽、移液模組本體）是烤漆／塑膠，不用 `MAT.frame`（鋁擠型）；實驗桌面、Metrohm 外殼、POM、瓶蓋、玻璃、液體、吸頭與安全區留在 `lab.js`／`render-details.js` |
| `tools/verify.mjs` | 排程與幾何驗證 |
| `web/css/style.css` | 桌面版面（左側樣品表／通訊紀錄、右側狀態卡、下方播放列）；900～1100 px 的非觸控視窗標題列改三列、≤1300 px 先收起左側欄。手機直向、橫向與 ≤1100 px 觸控平板由 `core/ui/viewer-workspace.js` 的精簡版面接手（☰ 製程與視角、⚙ 播放設定、工具列 ◧／◨ 開左右側欄抽屜，畫布全寬），本檔不再寫 ≤760 px 的窄螢幕規則；手機直向的取景由 stage 的 `narrowFit` 自動拉遠，視角照桌面寫 |

## 驗證

需要 Node.js 22 以上，不需 npm 套件。一次跑完 core 共用檢查（import 路徑、倒序一致、全場干涉與重合面閃爍，以及桌面、手機直向、手機橫向、觸控平板四種尺寸的標準互動測試 `ui`，結果在 `review/ui-check.json`，port 用環境變數 `UI_PORT` 指定）與本專案 `tools/verify*.mjs`：

```powershell
node ../core/tools/check.mjs AutomaticAcid-BaseTitration          # 在本資料夾；在 TestCode 則為 node core/tools/check.mjs AutomaticAcid
```

全場檢查結果在 `review/scene-verification.txt`。只跑排程與幾何驗證：

```powershell
node --import ../core/tools/register.mjs tools/verify.mjs
```

檢查項目：
- 所有目標位姿可達（誤差 < 0.5 mm）。
- 關節不超限。
- 以 20 ms 取樣，關節速度不超過上限。
- 直線移動路徑誤差 < 0.5 mm。
- 手臂與手上的器皿不碰設備與其他器皿（器皿以直立圓柱判斷，只有該步驟預期接觸的物件例外）。
- 器皿交接時不跳位。
- 每杯都有空杯重與淨重。
- 秤重時天平門關著。
- 滴定依序進行，開始時杯子在滴定頭正下方。
- 放杯位置離滴定頭 ≥ 90°。
- 手臂在進樣器區時轉盤不轉。
- 批次結束時：
  - 瓶子已關蓋、回到完成區，每瓶用掉 52 mL。
  - 用過的 6 支吸頭已退除。
  - 移液模組回座、天平門關上。
- 倒退／跳站結果一致。

最近一次結果在 `review/verification.json`。

## 渲染細節與近看模式

本次依 `docs/酸鹼自動滴定-機械手臂規劃-0828.pptx` 的九步流程／配置圖，以及 `docs/system-plan.md` 的既有設備方案加強外觀。文件沒有實機照片與精確 CAD，玻璃壁厚、接頭、螺絲、管線與表面材質仍為示意。

- 樣品瓶和滴定杯改用有壁厚的空心玻璃輪廓，加入厚底、口緣、體積刻度、瓶口螺紋與貼合瓶身的條碼標籤。
- 液面高度依排程體積換算；補上彎月面、滴定攪拌波紋、移液流束、加水流束、滴定液滴和電極噴洗。錐形吸頭中的液柱依錐台體積計算，避免液柱穿出吸頭。
- 文件未指定指示劑，因此終點不再把液體變粉紅。液體淡色僅幫助辨識，濃度／終點仍由原有理論 pH 曲線與模擬結果顯示。
- 修正滴定頭待機時向下移 190 mm 的錯誤，改成向上抬升 190 mm；攪拌棒與液面動畫改由模擬時間驅動，暫停與倒帶一致。
- 增加電極球泡、管線接頭與升降軟管、轉盤輪轂、螺絲、天平秤盤邊緣、鍵盤與手臂外殼倒角；改善反光與照明。

上方新增「滴定特寫」「液面近看」與「細節示範」選單，直接定位樣品瓶、移液注入、加水、滴液攪拌的時點。設備標籤預設收起，可在右側重新開啟。

預覽：`http://127.0.0.1:8770/AutomaticAcid-BaseTitration/?pause&t=300&view=titration`。

新增渲染狀態驗證：

```powershell
node --import ../core/tools/register.mjs tools/verify-render.mjs
```

涵蓋 12 次滴定的抬頭高度、液面與體積、流束出現／停止、吸頭容量及倒帶後畫面狀態一致性。流束、液滴和波紋是流程示意，並非流體力學或計量模擬。

## 液面近拍更新

- 新增「液面俯拍」，隨當前滴定杯及液位移動；仍可用滑鼠調整觀察角度。
- 玻璃杯壁與杯口同步形成倒液嘴，杯號貼合圓柱杯壁；避免重複杯口及平面標籤懸浮。
- 增加進樣器局部陰影、塑膠及不鏽鋼細紋。液位、管路、攪拌與滴液沿用絕對時間狀態，可倒退、暫停、跳站。
- [液面俯拍](http://127.0.0.1:8770/AutomaticAcid-BaseTitration/?pause&t=300&view=meniscus)；此為觀察視角，並非文件已指定的新增工業相機。
## 干涉修正與驗證

本輪干涉位置、幾何／路徑修正及驗證範圍見[四站干涉修正紀錄](../tools/docs/interference-review.md)。

新增驗證：`node --import ../core/tools/register.mjs tools/verify-clearance.mjs`。


## 相機視覺標記

相機畫面新增可開關的檢測框、中心標記及對應結果；依當前取像與 3D 模型更新，所有數值均為模擬。詳見 [標記內容、預覽與驗證](../tools/docs/vision-review.md)。

## 成本估算

[成本試算表](docs/cost-estimate.xlsx)｜[估價範圍與摘要](docs/cost-estimate.md)。含設備、工程人日、選配、預備費、上下限及含稅預算；正式價格以供應商報價為準。

## 防干涉回歸

新增夾爪對手臂的全批次淨空檢查（移動每 50 ms 以內、含步驟端點），以及攪拌軸／槳葉對電極與管路的檢查。四站統一執行方式及報告見 [檢查工具](../tools/README.md)。


## 線材配置與防干涉

網頁新增「線材配置」視角與配色說明，包含主要外露線束、固定夾、分隔線槽與適用的活動拖鏈。

桌下分隔線槽管理電源與訊號；滴定頭使用 R40 mm 升降拖鏈容納兩路液管與電極線；機器人供電經實際穿線孔。

[配線研究與實機確認項目](../tools/docs/cable-routing-review.md)｜[本機 docs 配線紀錄](docs/cable-management.md)｜[線材檢查結果](review/cables.json)｜[配線畫面](review/cables.png)

共用檢查：在 TestCode 執行 `node tools/verify-cable-routing.mjs`。docs 依現有忽略規則僅留在本機；根目錄研究文件隨原始碼保存。


## 視窗操作與產品焦點

相機標題列可拖曳，右上角可放大、獨立開窗或隱藏；主畫面上方的 ◧／◨ 可收合資訊，▣ 恢復相機面板，◎ 切換近距離產品追隨。獨立視窗共用主時間軸與檢測標記。

[完整操作說明與驗證範圍](../tools/docs/viewer-controls.md)｜[介面畫面](review/viewer-workspace.png)

## 電控規劃檢視

上方「⚡ 電控規劃」可查看元件用途、功能連接及配置外形；支援剖視、透視、點選與特寫，顯示狀態共用主時間軸。[本站元件清單](docs/electrical-plan.md)。

## 電路圖

[圖紙索引與設計說明](docs/circuit-diagrams.md) · [A3 PDF 圖冊](docs/circuit-diagrams.pdf)。可編輯 SVG 與圖面資料位於 `docs/electrical/`。
