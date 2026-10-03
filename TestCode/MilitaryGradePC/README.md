# 軍規筆電自動化 QC 線：第一階段設備模擬

以 V110 系列外觀 QII、工單 RMK12608372 及 `../Temp/MilitaryGradePC` 的實機照片重建。保留路線 B：六軸手臂＋F/T 力覺末端＋工業相機／線雷射、五站載具輸送、進出料升降堆料架及翻轉治具。所有 Three.js 依賴在 `web/vendor`，可離線執行。

## 第一階段範圍

**閉合、未接電的產品，進行可見外觀、側邊護蓋與翻面底部檢查。** 工單的 FT、LCD／鍵盤／掌托標籤、模組拆拔、Recover、摔機、附件包材仍由其他工位負責。

| 工位 | 更新後動作 |
|---|---|
| S0 進料 | 上層托叉承重 → 最底層推出 → 推桿退回 → 平台接管上層 → 下降一個間距 → SN → 四角側夾定位 |
| S1 閉合外觀 | 取像頭（頂視相機＋穹頂光）沿前側懸臂移入 → 頂視外蓋 → 取像頭退出 → 手臂四側取像 → 指定接縫雷射掃描 |
| S2 側邊護蓋 | 六個可開啟護蓋逐門定位、接觸、抬扣、沿弧線開門、連接器取像、保持抬扣閉門、換壓頭鎖定、閉合確認；兩個電池門只檢外觀與封印 |
| S3 翻面 | 翻轉治具從待命高度下降 → 夾具先夾緊 → 載具鬆開 → 抬升 210 mm → 翻轉 → 印刷／SN／警語／外露 Docking／螺絲腳墊取像 → 手臂退讓 → 翻回落座 → 載具夾緊 → 翻轉治具鬆開 → 上升 100 mm 讓出輸送通道 |
| S4 出料 | 模擬結果彙整；OK 拉入堆料架、平台接管、托叉退出、上升、托叉承重、平台復歸；NG 停留 S4 待人工覆判 |

照片中的 Docking 是外露接點，已移除舊版底面假想護蓋。標準配方移除 RF／GPS，HDD 僅開門取像不拔除，電池保持封印。OS／CPU 標籤位於掌托，不再放到底面計為已檢。

完整檢驗對照、QII 頁碼、排除項目、照片與 G7 工單差異，以及工程假設見 [第一階段檢驗映射](docs/phase1-scope.md)。

畫面預覽：[護蓋與連接器](review/screenshots/door-inspection.jpg)、[底面翻轉取像](review/screenshots/bottom-inspection.jpg)。

## 啟動

```powershell
node ../core/tools/serve.mjs MilitaryGradePC
# 或不自動開外部瀏覽器
node ../core/tools/serve.mjs MilitaryGradePC --no-open
```

開啟 [本地模擬](http://127.0.0.1:8770/MilitaryGradePC/)，也可雙擊 `run.bat`（所有專案共用 `core/tools/serve.mjs`，首頁 http://127.0.0.1:8770/ 列出全部專案）。ES module 需 HTTP，請勿直接用 `file://` 開啟 HTML。

## 操作

- 站別按鈕跳至 S0–S4；下方下拉選單列出完整動作步驟（含退離與取像預備點），搭配前後步與時間滑桿查看交接過程。
- 播放／暫停會同步控制所有軸，支援 0.25–4×；單台完成後停止，按播放或重播重新開始。
- 全景、堆料架、手臂、護蓋特寫、翻面、俯視、產品特寫；護蓋視角會隨目前門的位置改變。滑鼠可自由旋轉縮放。
- 右側顯示設備訊號、TCP 位置／姿態誤差、模擬力值與檢驗清單。曝光與動作銜接等待手臂到位，逾時會停止並顯示原因。
- 下方可顯示 TCP 路徑與參考包絡；右側可顯示／隱藏圍籬、控制櫃及設備標籤。
- 「示意 NG」會使播放在 S4 停止。切回 OK 只是在示範正常流程，不代表真實覆判；時間滑桿仍可檢視其他步驟。
- 「匯出紀錄」產生 JSON：模擬 SN、配方、完成／未完成項目、曝光事件及目前模型誤差。**無實拍影像、無實測數值、未接 MES。**
- `V110-RF` 保留為非本工單的擴充示意，不冒充 G7-STND 配置。

測試網址：`?pause&st=2&view=product`、`?pause&step=43&view=door`；`cam=x,y,z,tx,ty,tz` 可指定鏡頭。
主控台支援 `window.sim.jump(st, view, off)`、`seekTo(sec)`、`setView(name, instant)`、`pause()`、`play()`；`window.sim.views` 列出視角名稱，`window.sim.steps` 列出步驟起點。
- `?pause&movie`：展示影片模式。不跑一般畫面迴圈，改由 `core/movie/movie.js` 的 `installMovie` 依絕對時間逐格取樣（與 `project.apply` 同一路徑），鏡頭追焦載具，提供預覽、鏡頭檢查與「輸出完整影片」。本站自己的 1080p 影片輸出（`?capture=1`）照舊，見下方「MP4 影片與再次輸出」。

## 建模與運動

上蓋四區壓紋、Getac 字樣、護角、前拉帶、門軸／門扣／膠條、獨立介面端子、底部維修蓋、螺絲十字槽、可讀法規示意字體、Docking 接點均為程式幾何。托叉、推料桿、夾墊、止擋、感測器、驅動馬達、導軌、線管、調壓器與控制面板補入設備模型。

動作由絕對時間和步驟快照驅動，避免跳站殘留；換 TCP 以法蘭座標插值保持連續。手臂採幾何初始解＋阻尼最小平方 IK，依流程順序選擇接近上一姿態的等價手腕解，避免轉位時多轉一圈。自由移位走關節插值（PTP），接近、接觸、減速與掃描走直線，皆有關節與線性限速；夾持交接先取得新約束再解除舊約束。新增退離與預備點後，規劃時間約 **348 秒＋到位等待**（2026-10 全場干涉修正加入翻轉治具升降、門邊作業後垂直上升與鉤爪預備點，比原本的 330 秒多 18 秒）。

產品本體 300×210×36 mm、載具 440×330 mm、節距 110 mm、輸送面 760 mm 沿用概念尺寸；翻轉抬升改為 210 mm。手臂依 DENSO VM-60B1 型錄的臂長、偏移與關節範圍建模（見 [第一階段檢驗映射](docs/phase1-scope.md)），立在 600 mm 立座上（手臂本體在共用模型 `core/models/robots/denso-vm60b1.js`，滑軌、立座與末端工具留在本專案）；基座與手腕長度、關節零點方向仍待 DENSO CAD 核對，目前結果不能當成實機可達性保證。前、後側改由斜上方 35° 取像，因手腕 ±120° 限制。S1 改為前側單邊懸臂（立柱 z=1050），取像頭移入時穹頂底緣距產品 80 mm、退出 780 mm 讓手臂巡拍；S3 翻轉龍門移到輸送線前側、橫樑 1800 mm，後側留給手臂。

全場干涉修正（2026-10，`node ../core/tools/check.mjs MilitaryGradePC` 的 scene 動態／靜態皆 0）：S3 移到 x=1150，翻轉治具輸送期間停在上方 100 mm；右側護蓋改在滑軌 575 作業；鉤爪、壓頭、線雷射作業時工具繞軸轉動，讓環形光在 TCP 正上方，線雷射一律由斜上方 20° 掃描；護蓋開度 100°；門邊作業結束先垂直上升 150 mm 再轉位；待命位姿改為 TCP y=1150、z=-220；載具側夾氣缸放低；側門縮短並避開四角護角；滑軌供電線改沿地面繞過滑軌端部。實際尺寸、力／速度參數、量測 ROI 和安全回路須於實測後校正。碰撞檢查涵蓋手臂對 S1 懸臂／取像頭與 S3 龍門，以及末端工具對手臂、光學機殼對筆電本體、工具對翻轉治具；未涵蓋完整輸送線、堆料架與所有非相鄰連桿組合。

## 檔案

| 檔案 | 用途 |
|---|---|
| `web/js/notebook.js` | 產品、介面、封印與 SKU |
| `core/geom/primitives.js` | 幾何、可讀文字貼圖、配線共用元件（各專案共用） |
| `web/js/cell.js` | 載具、進出料、輸送與翻轉設備 |
| `core/models/robots/denso-vm60b1.js` | DENSO VM-60B1 手臂本體（共用模型）：基座、連桿、關節 j1～j6、手臂線材保護段、法蘭工具安裝座、限位、關節速度、IK 參數與幾何初始解；模型目錄 `/core/catalog/` 可預覽 |
| `web/js/robot.js` | 本站部分：第七軸滑軌與拖鏈、600 mm 立座、力覺末端（F/T、相機＋環形光、鉤爪／壓頭、線雷射）、TCP、逆解選解、PTP 與位姿快取；手臂本體取自共用模型 |
| `web/js/sequence.js` | 第一階段逐步流程、時間、狀態快照 |
| `web/js/project.js` | 專案介面 `createProject`：建立全部設備、產品與動作序列，`apply(t)` 把場景放到時間 t；網頁與 core 統一檢查共用 |
| `web/js/main.js` | 控制、到位等待、紀錄匯出、手臂鏡頭子畫面、`?movie` 錄影掛勾與 `?capture=1` 影片輸出（場景物件由 `project.js` 建立）。renderer、相機、軌道控制、環境光與燈光（含跟隨載具的特寫陰影光）、畫面迴圈用共用舞台 `core/ui/stage.js` 的 `createStage`；`window.sim` 由 `exposeSim` 提供 |
| `docs/phase1-scope.md` | 文件依據與範圍映射 |
| `docs/cost-estimate.xlsx` | 元件選型與成本估算（預算級） |
| `tools/verify.mjs` | 狀態／幾何／運動驗證 |

## 驗證

需要 Node.js 22 以上，幾何測試不需 npm 套件：

```powershell
node --import ../core/tools/register.mjs tools/verify.mjs
# 或在 TestCode 執行統一檢查（imports、倒序一致、全場干涉／重合面，再加上本專案 tools/verify*.mjs）
node ../core/tools/check.mjs MilitaryGradePC
```

統一檢查讀取 `web/js/project.js`（預設 SKU `V110-STND`），全場干涉與重合面結果寫入 `review/scene-verification.txt`。

涵蓋兩個 SKU、全部步驟的代表時刻、任意倒退／跳站一致性、封印保持、翻面升降與夾持條件、TCP 可達性（PTP 步驟檢查終點）、手臂對 S1／S3 固定結構的碰撞（代表時刻＋連續播放每 0.25 秒），以及連續播放。最近一次結果在 `review/verification.json`；模型計算誤差並非設備精度。瀏覽器畫面驗證（全景、產品、護蓋、翻面、控制及 NG 停留）是改用 VM-60B1 與 S1 懸臂之前做的，本版尚未重做。

## MP4 影片與再次輸出

目前影片：`videos/V110_QC_1080p30.mp4`，1920×1080、固定 30 fps、約 3 分 6 秒，H.264 / yuv420p。包含完整工序順序：入料 → 外觀拍照 → 護蓋開閉／端子拍照 → 翻面／底部拍照 → 出料。影片縮短自由移位時間，接觸與翻轉動作保留較慢速度；片長不是實機節拍。

影片按時機切換全景、堆料架、移載追蹤、護蓋近景、翻轉治具及底部拍照視角，含繁體中文工序字幕、曝光提示與進度條。使用 RTX 5070 Ti 的 Direct3D 11 / WebGL 渲染及 NVIDIA NVENC H.264 編碼，逐格完成後才送入編碼器，與螢幕更新率及渲染耗時無關。

再次輸出：

```powershell
python tools/render_server.py
```

開啟 [影片輸出頁](http://127.0.0.1:8766/?capture=1)，按「輸出 1080p / 30 fps MP4」。頁面須保持開啟直到顯示完成。使用本機 `tools/bin/ffmpeg.exe`（需支援 `h264_nvenc`）及 NVIDIA 驅動；不需 Playwright 或網際網路。

- `web/js/video.js`：從實際工序生成分鏡，以確定時間取樣，合成 1080p 字幕與畫面。
- `tools/render_server.py`：僅監聽 127.0.0.1:8766，驗證影格順序與總數，交給 NVENC 編碼。
- `videos/*.shots.json`：每個工序的影片／模擬時間對照及實際 WebGL GPU 名稱。
- `videos/*.encode.log`：編碼紀錄；同名影片已存在時自動新增編號，避免覆蓋。
- 若連線中斷，重新開啟輸出頁並按輸出，可在服務仍執行時從已接收的影格續傳；相同影格重送不會重複寫入。
- `python tools/verify_video.py`：核對編碼、解析度、固定幀率與總格數，完整解碼，並產生 `review/video/contact-sheet.jpg` 與驗證紀錄。
- `?capture=1&vt=43`：預覽影片指定秒數。既有 `tools/capture_video.js` 保留作外部逐格截圖工具，預設已改為 30 fps；本次成片使用上述輸出頁製作。

本次成片驗證：186.000 秒、5,580 格、固定 30/1 fps、92,962,618 bytes；完整解碼零錯誤。關鍵工序抽格與動作差異檢查通過，紀錄位於 review/video/verification.json。


## 近拍與實際鏡頭視角

- 補上塑膠／橡膠細紋、金屬粗糙度與跟隨產品的局部陰影；校正環境反射，保留深色外殼層次。
- HDMI／COM 使用梯形金屬殼，USB-C 使用圓角開口；接口有中空金屬壁、內部舌片及端子。
- 「手臂取景」從工具鏡頭前端取像，維持 3:2 全視野，隱藏 ROI／軌跡等輔助線。點按時會暫停到下一個手臂取像步驟；時間軸仍可查看移動中的真實朝向。
- [接口取像](http://127.0.0.1:8770/MilitaryGradePC/?pause&step=48&view=sensor)、[底面 Docking](http://127.0.0.1:8770/MilitaryGradePC/?pause&step=186&view=sensor)。
- 鏡頭以 12 mm、13.2 × 8.8 mm 感光面建模，屬示意光學參數，須按實機鏡頭校正；不代表已產生實測檢查結果。
- 新增相機驗證：`node --import ../core/tools/register.mjs tools/verify-camera.mjs`，涵蓋兩種 SKU 共 50 個光軸位置與 20 個接口遮擋檢查。
## 干涉修正與驗證

本輪干涉位置、幾何／路徑修正及驗證範圍見[四站干涉修正紀錄](../tools/docs/interference-review.md)。

新增驗證：`node --import ../core/tools/register.mjs tools/verify-clearance.mjs`。


## 相機視覺標記

相機畫面新增可開關的檢測框、中心標記及對應結果；依當前取像與 3D 模型更新，所有數值均為模擬。詳見 [標記內容、預覽與驗證](../tools/docs/vision-review.md)。

## 成本估算

[成本試算表](docs/cost-estimate.xlsx)｜[估價範圍與摘要](docs/cost-estimate.md)。含設備、工程人日、選配、預備費、上下限及含稅預算；正式價格以供應商報價為準。

## 防干涉回歸

- 線雷射輪廓儀向側邊移至工具 X=90 mm，與環形光保留 7 mm 間距；視窗、雷射示意與量測 TCP 同步移動。
- 待命相機 TCP 升至 Y=1250 mm，避免工具掃入 J2；按流程選擇相近的手腕逆解。
- 低位量測／接觸姿態轉腕前先沿工具軸退離 120 mm；右側取像先到門面上方 300 mm 預備點，再直線下降，避開 S3 立柱。
- 新增兩種 SKU 的工具／手臂、光學機殼／筆電本體、工具／翻轉治具檢查，包含 50 ms 以內路徑抽樣與連續播放。

結果見 [自干涉與治具淨空](review/self-clearance.json)；四站統一執行方式見 [檢查工具](../tools/README.md)。


## 線材配置與防干涉

網頁新增「線材配置」視角與配色說明，包含主要外露線束、固定夾、分隔線槽與適用的活動拖鏈。

第七軸 R65 mm 拖鏈與 S1 取像頭 R55 mm 拖鏈保持定長；立座沿背面走線，末端相機、光源與輪廓儀各有支線。

[配線研究與實機確認項目](../tools/docs/cable-routing-review.md)｜[本機 docs 配線紀錄](docs/cable-management.md)｜[線材檢查結果](review/cables.json)｜[配線畫面](review/cables.png)

共用檢查：在 TestCode 執行 `node tools/verify-cable-routing.mjs`。docs 依現有忽略規則僅留在本機；根目錄研究文件隨原始碼保存。


## 視窗操作與產品焦點

相機標題列可拖曳，右上角可放大、獨立開窗或隱藏；主畫面上方的 ◧／◨ 可收合資訊，▣ 恢復相機面板，◎ 切換近距離產品追隨。獨立視窗共用主時間軸與檢測標記。

[完整操作說明與驗證範圍](../tools/docs/viewer-controls.md)｜[介面畫面](review/viewer-workspace.png)

## 電控規劃檢視

上方「⚡ 電控規劃」可查看元件用途、功能連接及配置外形；支援剖視、透視、點選與特寫，顯示狀態共用主時間軸。[本站元件清單](docs/electrical-plan.md)。

## 電路圖

[圖紙索引與設計說明](docs/circuit-diagrams.md) · [A3 PDF 圖冊](docs/circuit-diagrams.pdf)。可編輯 SVG 與圖面資料位於 `docs/electrical/`。
