# SSD USB 接頭壓合站：自動化方案 3D 模擬

取代影片中人員用壓板壓平 USB 接頭的作業：把前站放好、但可能翹起的 USB 接頭銀腳壓回 PCB 焊墊，再逐顆拍照確認貼合；不合格的原位補壓後複檢。

**多機種、共用治具**：
- 手臂上只有一套治具：DENSO VS-068 搭配 ATI 力覺感測器與 20MP 45° 斜視相機，快拆介面裝壓墊：
  - 有整排接頭的機種（8 顆、片距 21 mm）用 **8 頭整排壓墊**（標準），每頭獨立彈簧，一次壓一整排。
  - 只有單顆接頭的機種（例如 3.5 吋 SSD）快拆換單點彈簧壓頭。
- 換機種只換配方。固定的全局相機先拍整盤，找出每顆接頭的位置與方向。
- Three.js 與共用模組來自 `../core`（`core/vendor`），可離線執行。

文件：
- [多機種重新設計](docs/redesign-multi-product.md)：共用治具、配方、全局相機、節拍。
- [自動化方案規劃](docs/automation-plan.md)：現況分析、判定方法、風險與待確認。
- 用戶提供的照片與影片在 `docs/`。

## 配方

| 配方 | 內容 | 資料來源 | 標準壓墊 | 時間 | 單點逐顆（比較） |
|---|---|---|---|---|---|
| `usb-2x8` | USB 隨身碟 2×8 連板、USB-A | 照片目測 | 8 頭整排 | 約 17.5 s | 約 26.9 s |
| `usb-2x8-r90` | 同一連板、接頭轉 90° | 假設 | 8 頭整排 | 約 16.0 s | 約 26.7 s |
| `ssd35-usbc` | 3.5 吋 SSD ×2、USB-C、接頭朝左右 | 假設 | 單點（快拆） | 約 13.8 s | — |

時間為規劃循環、不含補壓；補壓一次約再加 3.2 s。

## 流程

| 站別 | 動作 |
|---|---|
| S0 進板定位 | 前一盤出站 → 止擋上升 → 上游送板（軌寬依配方）→ 到位 → 頂升 3 mm |
| S1 全局定位 | 固定全局相機拍整盤 → 讀載盤碼、確認配方、找出接頭位置與方向 |
| S2 壓合 | 8 頭整排：每排一次「移至 → 接近 → 壓合 40 N → 保壓 0.5 s → 回升」；單點：逐顆（蛇行） |
| S3 相機檢查 | 同方向、同一直線上的接頭自動分組，每張最多 4 顆；J6 依接頭方向轉向 |
| S4 補壓判定 | 間隙超標的接頭原位補壓（8 頭時整排重壓，已貼平的由各頭彈簧吸收）→ 單獨複拍 → 結果彙整 |
| S5 出板 | 手臂回待命 → 頂升下降 → 止擋下降 → 送往迴焊爐 |

## 啟動

```powershell
node ../core/tools/serve.mjs RobotArmPressSSD
# 或不自動開外部瀏覽器
node ../core/tools/serve.mjs RobotArmPressSSD --no-open
```

開啟 [本地模擬](http://127.0.0.1:8770/RobotArmPressSSD/)，也可雙擊 `run.bat`（所有專案共用 `core/tools/serve.mjs`，首頁 http://127.0.0.1:8770/ 列出全部專案）。ES module 需 HTTP，請勿直接用 `file://` 開啟 HTML。

## 操作

- 上方選單切換**機種配方**與**壓墊**。預設是配方的標準壓墊；有整排接頭的機種可改選「單點逐顆」比較時間，單顆機種不能選 8 頭。
- 站別按鈕跳至 S0–S5；S3 直接跳到第一次取像，讓 USB 出現在相機畫面。下拉選單可選任一步驟，搭配前後步與時間滑桿。
- 視角：全景、輸送站、手臂、壓合特寫、檢查特寫、俯視；滑鼠可自由旋轉縮放。
- 新增「載盤近看」與「銀腳特寫」。點右側接頭編號可對準該顆銀腳，視角會依配方方向旋轉，並隨載盤移動；使用時間軸比較壓前與壓後。
- **左下子畫面**是相機實際看到的畫面：
  - 全局定位、壓合與手臂移動時顯示固定全局相機，並標示畫面來源；載盤未到站時顯示等待訊息。
  - 手臂到達取像／判定位置後顯示手臂相機，標示每顆的模擬間隙與 OK／NG。
  - 相機維持 3:2 感光元件視野；標題及結果放在影像外，避免遮住 USB 或因縮小面板而裁掉接頭。
- 右側「USB 接頭」格依配方排列，顯示每顆狀態（翹起、壓合中、已壓合、貼合 OK、補壓中、NG）與模擬間隙。
- 「示意 NG」會讓回彈的那一顆補壓後仍未貼合，播放停在複檢並亮紅燈。
- 「匯出紀錄」產生 JSON：配方、壓墊、每顆的模擬間隙與狀態、取像事件。**無實拍影像、無實測力值、未接 MES。**

網址參數：
- `?recipe=ssd35-usbc`、`?insert=single`（整排機種改單點比較）、`?result=NG`
- `?pause&st=3&view=inspect`（直接看取像）；加 `t` 時仍以站別起點加秒數精確定位。
- `?pause&st=2&view=leads&focus=A1`、`?pause&st=2&view=product`
- `?shadow=0`、`cam=x,y,z,tx,ty,tz`、`speed=2`（播放速度）、`t=秒`（未給 `st`／`step` 時為絕對時間）
- `?pause&movie`：展示影片模式。不跑一般畫面迴圈，改由 `core/movie/movie.js` 的 `installMovie` 依絕對時間逐格取樣（與 `project.apply` 同一路徑），提供預覽、鏡頭檢查與「輸出完整影片」。

主控台：`window.sim.seekTo(sec)`、`pause()`、`play()`、`setView(name)`、`steps`、`events`、`T`、`playing`。

## 建模

### 現場參考與渲染細節

已檢視 `docs` 中四張照片，以及 `810029093.711498.mp4`（約 9.6 秒，抽幀查看人員分兩排壓合、移開長條壓板、放行載盤的動作）。外觀重建包含：

- 深色編織紋載盤、接頭沉槽、定位孔及盤號；PCB 銑槽、FR-4 板邊、走線、絲印、晶片引腳與被動元件金屬端帽。
- USB 外殼的穿透開孔、折邊、壓印點、內部舌片與接點；銀腳採彎折截面及平貼端，跟隨既有翹起／下壓／回彈狀態。
- 焊墊上的灰色未迴焊錫膏；不把尚未迴焊的接點表現成已完成焊接的錫角。
- 手臂外殼倒角、關節與工具螺絲、隨行程縮短的壓頭彈簧、相機鏡筒環及線纜；輸送軌螺絲與金屬紋理。
- 修正環境光源強度，補上作業區局部陰影。細節以程式生成並合併靜態網格，維持離線運行。

照片無法確定的尺寸、電路圖案及絲印為外觀示意，非產品 CAD／Gerber。銀腳特寫是同一 3D 場景的觀察視角；左下子畫面仍使用手臂相機或全局相機。間隙與判定仍為模擬資料。

視覺驗收：[載盤近看](review/product-overview.png)、[壓前](review/leads-before.png)、[壓後](review/leads-after.png)、[相機檢查](review/camera-inspection.png)。

- **產品**：依配方建出載盤、板子、零件與接頭（USB-A、USB-C 型錄）。翹起角為示意值，以插頭尖端為支點；壓頭碰到後才被壓回。每個配方指定一顆「壓後回彈」的接頭，用來示範補壓。
- **手臂**：VS-068 型錄的臂長 340＋340 mm 與關節範圍。基座到 J2 高度 345 mm、J5 到法蘭 80 mm、關節零點方向為假設值，需以 DENSO CAD 核對。
- **運動**：
  - 自由移位走同步關節插值（PTP），時間依關節角度差自動算，速度上限取型錄的 50%。
  - 接近、接觸與回升走直線。
  - 逆解依流程順序挑離前一點最近的解（含手腕翻轉的等價解）。
- **力值**：由壓頭彈簧（2.5 N/mm）與單顆壓回力推算的示意值，上限 60 N。

## 檔案

| 檔案 | 用途 |
|---|---|
| `web/js/recipes.js` | 接頭型錄與機種配方（載盤、板子、接頭位置與方向、翹起示意、壓合力） |
| `web/js/product.js` | 依配方建出產品；壓點、對焦點、翹起角與間隙 |
| `core/geom/surfaces.js` | 離線生成編織／金屬／PCB 材質，以及靜態網格合併（與快門站共用） |
| `web/js/cell.js` | 輸送段（後軌基準、前軌調寬）、止擋、頂升、全局相機、底櫃、外罩。鋁擠型框架 `MAT.frame`、拋光銷 `MAT.chrome`、拉絲鋁軌與支撐板 `finished(MAT.alu, 'metal')`；綠色皮帶、PC 外罩、深色展場地面為本站外觀，留在本檔 |
| `web/js/robot.js` | VS-068、共用末端工具（快拆壓頭、斜視相機）、關節規劃；IK 用 `core/robot/kinematics.js` |
| `web/js/sequence.js` | 由配方產生流程、拍攝分組、接頭狀態與力值計算。步驟、快照插值、`stationStart`、`total`、`events` 用共用步驟序列 `core/anim/sequence.js` 的 `createStepSequence`；本檔只加手臂姿態層（建立每步時記下起訖姿態與 `motion`；逆解規劃後用序列的 `retime` 依關節角度差重排 PTP 步驟時間；接觸／接近限速）；另匯出手臂到位規則 `ARRIVAL`（門檻、逾時 8 s、子步 10 ms），`main.js` 與 `tools/verify.mjs` 共用 |
| `web/js/station.js` | 組裝整站並套用狀態（畫面與驗證共用） |
| `web/js/project.js` | 專案介面 `createProject`：依配方／壓墊建整站、ROI 框與流程；`apply(t)` 把流程狀態、手臂姿態、燈號與 ROI 放到時間 t。`main.js` 與 core 統一檢查共用 |
| `web/js/main.js` | 配方選單、接頭狀態、相機子畫面、紀錄匯出、`?movie` 錄影掛勾（物件與時間狀態取自 `project.js`）。renderer、相機、軌道控制、環境光與燈光、畫面迴圈用共用舞台 `core/ui/stage.js` 的 `createStage`；作業區局部光（含陰影）在 main.js 另建。播放列用 `core/ui/player.js` 的 `createPlayer`（時間、播放／暫停、速度、時間軸、步驟選單、上一步／下一步）：`advance` 交給 core 的到位閘門 `createArrivalGate`（`core/anim/arrival.js`，規則 `ARRIVAL`：每格切成 ≤ 10 ms 子步、手臂未到位就停在步驟終點等、等超過 8 s 判故障、手臂限速追蹤；與 `tools/verify.mjs` 的連續播放用同一個閘門），本檔只加示意 NG 複檢後停線的故障判斷、`apply(T, { seek })`（跳播手臂直接到位、清除等待、故障與軌跡）與按播放時從故障處重新到位的 `resume`。3D 標籤用 `stage.addLabel(…, { anchor: 'above' })`、視角轉場用 `stage.goTo`／`stage.cancelTween`、載盤近看跟著輸送用 `stage.shiftView`；常用材質（框架、黑件、烤漆、工具鋼、PU、鏡頭玻璃）取 `core/geom/materials.js` 的 `MAT` |
| `tools/verify.mjs` | 全配方驗證 |

## 驗證

需要 Node.js 22 以上，不需 npm 套件。統一檢查（import 路徑、倒序一致、空間檢核、全場干涉與重合面，加上 `project.json` 列的本專案驗證）：

```powershell
node ../core/tools/check.mjs RobotArmPressSSD      # 在專案資料夾；在 TestCode 則是 node core/tools/check.mjs RobotArm
```

全場檢查結果寫在 `review/scene-verification.txt`。單獨執行本專案驗證：

```powershell
node --import ../core/tools/register.mjs tools/verify.mjs
node --import ../core/tools/register.mjs tools/verify-camera.mjs
node --import ../core/tools/register.mjs tools/verify-self-clearance.mjs
```

三個配方 × 可用的壓墊 × OK／NG 示意，共 8 種組合，每種都檢查：
- 全部步驟代表時刻的 TCP 可達性（PTP 步驟檢查終點）、力值上限、頂升條件。
- 任意倒退／跳站一致性。
- 手臂對軌道、止擋、全局相機、外罩、底櫃與產品的碰撞（接觸與接近步驟只允許壓頭進入產品包絡）。
- 結束時的接頭狀態（OK 全部貼合；NG 只剩回彈那一顆）。
- 連續播放（實際限速＋到位等待，與網頁同一個到位閘門與 `ARRIVAL`，每 0.25 秒做一次碰撞檢查）。

最近一次結果在 `review/verification.json`；模型計算誤差並非設備精度。

相機驗證另檢查 28 個全局／手臂取像位置的 USB 幾何是否完整位於視野內、S3 捷徑是否停在取像步驟、移動時畫面來源，以及不同面板尺寸是否維持完整感光元件比例。

## 相機近拍更新

- 相機子畫面新增「放大／縮小」，保持 3:2 完整視野；可用 `cameraSize=large` 直接開啟。
- 子畫面移除 3D ROI 輔助框，結果仍列在影像下方；採較低曝光，保留銀腳／外殼高光細節。
- 銀腳增加細微金屬粗糙度，錫膏使用不規則細紋，仍維持未迴焊外觀及原有接觸位置。
- [放大相機預覽](http://127.0.0.1:8770/RobotArmPressSSD/?pause&st=3&view=inspect&cameraSize=large)。
## 干涉修正與驗證

本輪干涉位置、幾何／路徑修正及驗證範圍見[四站干涉修正紀錄](../tools/docs/interference-review.md)。

新增驗證：`node --import ../core/tools/register.mjs tools/verify-clearance.mjs`。

### 起始相機與手臂干涉修正

待命時原本朝內的相機機身會進入 J2 肩部。起始及回待命姿態現改為相機朝外，並把相機線纜移至工具板外側，避開手腕轉動範圍；壓合及取像 TCP、鏡頭位置與視野設定維持原規格。

`verify-self-clearance.mjs` 先重現舊姿態的肩部干涉，再對三個配方、五種可用壓墊組合逐步抽樣（間隔不超過 25 ms，包含起點與終點），檢查相機、鏡頭、光源、支架及線纜對手臂的有向包圍盒淨空。門檻為 5 mm；本次 5,049 個樣本的保守淨空下限為 9.83 mm。連續播放測試也增加相同自干涉檢查。

結果見 [相機自干涉驗證](review/self-clearance.json)、[修正後起始姿態](review/start-camera-clearance.png)。這是動畫幾何包絡與離散抽樣驗證，實機仍須以原廠 CAD、實際線纜彎曲及安全距離校核。


## 相機視覺標記

相機畫面新增可開關的檢測框、中心標記及對應結果；依當前取像與 3D 模型更新，所有數值均為模擬。詳見 [標記內容、預覽與驗證](../tools/docs/vision-review.md)。

## 成本估算

[成本試算表](docs/cost-estimate.xlsx)｜[估價範圍與摘要](docs/cost-estimate.md)。含設備、工程人日、選配、預備費、上下限及含稅預算；正式價格以供應商報價為準。

## 防干涉回歸

相機自干涉、彈簧行程、完整動作、相機取像與視覺標記五組驗證已納入 [四站統一檢查工具](../tools/README.md)，改動幾何或路徑後可一次重跑。


## 線材配置與防干涉

網頁新增「線材配置」視角與配色說明，包含主要外露線束、固定夾、分隔線槽與適用的活動拖鏈。

基座電源與分段手臂護套、F/T 及光源支線、外罩內側相機支線、輸送感測器線路均已建立。

[配線研究與實機確認項目](../tools/docs/cable-routing-review.md)｜[本機 docs 配線紀錄](docs/cable-management.md)｜[線材檢查結果](review/cables.json)｜[配線畫面](review/cables.png)

共用檢查：在 TestCode 執行 `node tools/verify-cable-routing.mjs`。docs 依現有忽略規則僅留在本機；根目錄研究文件隨原始碼保存。


## 視窗操作與產品焦點

相機標題列可拖曳，右上角可放大、獨立開窗或隱藏；主畫面上方的 ◧／◨ 可收合資訊，▣ 恢復相機面板，◎ 切換近距離產品追隨。獨立視窗共用主時間軸與檢測標記。

[完整操作說明與驗證範圍](../tools/docs/viewer-controls.md)｜[介面畫面](review/viewer-workspace.png)

## 電控規劃檢視

上方「⚡ 電控規劃」可查看元件用途、功能連接及配置外形；支援剖視、透視、點選與特寫，顯示狀態共用主時間軸。[本站元件清單](docs/electrical-plan.md)。

## 電路圖

[圖紙索引與設計說明](docs/circuit-diagrams.md) · [A3 PDF 圖冊](docs/circuit-diagrams.pdf)。可編輯 SVG 與圖面資料位於 `docs/electrical/`。
