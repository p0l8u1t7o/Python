# MechanicalAssembly 工作進度與接續說明

更新日期：2026-10-02（台灣時間）。供使用者在 VS Code 開啟 Codex 後接續本專案。

目前程式更新、CAD 建庫、幾何測試、正式建置及**本檔列出的新版視覺與互動驗收均已完成**。2026-10-02 本次環境由 Browser 正式選用 Chrome，在原網址成功操作，未遭權限拒絕，沒有變更權限或改網址繞過。詳細結果、效能量測範圍與截圖索引見 `VALIDATION.md`。

## 最新：搬家與資料夾整理（2026-10-02，Claude Code）

- 專案由 `TestCode/MechanicalAssembly` 搬到 `Python/MechanicalAssembly`。CAD 來源預設改為 `../TestCode/Temp/自動爆炸圖與拆圖CAD設計`，可用環境變數 `CAD_SOURCE_DIR` 覆寫（`scripts/lib/paths.js`；Python 腳本讀同一個變數）。
- `src/` 依職責分成 `cad/`、`viewer/`、`planner/`（含 `client.js`、`worker.js`）、`project/`、`ui/`、`styles/`；`scripts/` 分成 `catalog/`（Node 建庫）、`cad/`（Python 解析與 SolidWorks COM）、`media/`、`lib/`；`tests/` 分成 `js/`、`python/`；`VALIDATION.md`、`WORK_PROGRESS.md` 移到 `docs/`。資料夾說明見 README「資料夾結構」。
- Python 由 `.python-libs`（pip --target）改為虛擬環境 `.venv`＋`requirements.txt`；`setup.ps1` 一鍵建置。npm 指令經 `scripts/lib/python.js` 使用 `.venv` 的 Python。
- 驗證：JavaScript 27 項、Python 4 項、正式建置通過；`npm.cmd run inventory` 重新產生的盤點檔與原檔逐位元相同；`.venv` 以 OCP 轉換 202401-AD01.STEP 成功（33 件）；開發伺服器各模組與 `/api/source` 皆回 200。

## 前輪：台車展示影片（2026-10-02，Claude Code）

- 新增 `scripts/media/render-showcase.mjs` 與 `window.studioAutomation`（`src/main.js`）：逐格算圖、NVENC 編碼、亮度稽核。
- 產出 `TEMP\videos\MechanicalAssembly-台車_1080p30.mp4`：86.9 秒、2607 格、約 93 MB；稽核 0 單格閃爍、0 黑畫面，相鄰格最大差 7.4（第一版因預組情境切換有 40.5 的跳變，已以交叉淡化修正）。
- 檢視器新增 `outsideContext = "hide"`（影片用：預組時隱藏其他零件）；地面 `renderOrder = -1` 固定透明排序。

## 前輪：模型朝上軸與 Z 朝上座標軸（2026-10-02，Claude Code）

- 使用者回報自動線總裝「基礎面沒有朝下」：原因是部分 SolidWorks 組合件以 Z 朝上建模，工作台一律當 Y 朝上。新增 `orientRoot()`（`src/cad/importer.js`）可讓任一軸朝上；工具列可逐站改正並隨專案保存，改正後依新方向重新推論。
- `scripts/catalog/orient-catalog.js`（`npm.cmd run catalog:orient`）以目視確認的總裝為起點，從擺放矩陣推算 441／969 個模型的朝上軸，輸出 `public/data/orientation.json`（含依據）。17 個預設站逐一在瀏覽器確認：LINE、EA00、TRAY、CHIP 為 z，WET 為 −z，JA00、SHARED 為 x，其餘 y。預先推論已依新方向重算，推論器版本升為 3。
- 依使用者要求，右下角座標軸改為隨視角轉動的 Z 朝上顯示；編輯器與步驟說明的軸向名稱同步改為此座標（內部 −Z 顯示為 +Y）。
- 已知限制：同名原生組合件與 STEP 的座標可能不同（例如 Load machine.SLDASM 在總裝中為 X 朝上，但 Load machine_240608.STEP 為 Y 朝上），STEP 整機一律目視確認；其餘 528 個模型無依據時預設 Y，切到資料庫中的其他 CAD 時可能需手動改正。

## 前輪：埠號、停止腳本、地面與基座動作（2026-10-02，Claude Code）

- 開發伺服器改用 6001（6000 被瀏覽器列為不安全埠會擋）；新增 `stop.ps1`，只停止本專案在該埠的 Vite 服務。換埠後瀏覽器的本機儲存不共用，舊專案需從 5173 匯出 JSON 再匯入。
- 使用者回報「設備底面沒有接觸地面」：原本地面跟著最低的可見零件移動，展開或從下方裝入時整機看起來浮空。現改為地面固定在組合完成時的最低點（`scene-viewer.js` `floorBase`），地面材質略透明。
- 「部分站別沒有動畫」：全新瀏覽器逐站檢查，16 個有幾何的站都有步驟（FA 無幾何、CHIP／SHARED 只有 1 件）。第一步「放置基座」原本不動，搭配每步暫停時看起來像沒有動畫，現改為由上方降落 0.5 倍距離。

## 前輪：互鎖組件、方向箭頭、作業指導書與錄影（2026-10-02，Claude Code）

- **互鎖改善**（`src/planner/`）：沒有單件可移出時，以方向阻擋圖的匯點強連通分量找出可一起移出的零件群，建立推論組件（`node.virtual`）；銷＋擋圈組成的購入品拆開；有軸向的緊固件沿軸鎖入不列為待確認；名稱分類也比對不嚴格還原的 Big5（皮帶等）。待確認步驟：上料機 144→41、下料機 137→42、上料機機架外罩分站 98→15。推論器版本升為 2，已重跑 `catalog:plan`。
- **箭頭**（`scene-viewer.js` `showArrows`）：本步每個移動節點一支琥珀色箭頭，畫在最上層。
- **作業指導書**（`src/project/exporters.js` `sopHtml`、`main.js` `exportSop`）：步驟範圍、約 1080p 截圖、說明、零件數量（未命名實體以幾何指紋合併）、檢查欄，單一 HTML 可列印成 PDF。範例 `output/sop-sample.html`。
- **錄影**（`main.js` `record`）：MediaRecorder＋合成畫布（3D 畫面＋字卡＋進度條），WebM，輸出時暫時提高算圖解析度。範例畫格 `output/video-frame.png`。
- 測試 27 項通過（新增推論組件、輸出模組 3 項）；正式建置通過。

## 前輪：組裝順序推論與作業員動畫（2026-10-02，Claude Code）

目標：CAD 匯入後自動產生爆炸圖與組裝順序動畫，讓作業員看動畫就懂組裝順序。使用者確認沒有 SolidWorks 機器、設計端也未畫爆炸視圖，因此主線是由 STEP／原生快取的階層與幾何推論。

- **資料格式 v2**（`src/project/core.js`）：零件 → 節點樹（root／unit 預組件／atomic）→ 步驟。驗證「預組件內的步驟必須早於該預組件安裝」。v1 專案讀入時自動轉換，保留分組、方向、審核。
- **推論器**（`src/planner/`）：沿用 CAD 階層；單元內以 BVH 射線測試 ±XYZ 與零件軸向／板面法向的可移出方向，基座取最大結構件，由外往內拆、反轉為組裝順序；螺絲／墊圈／擋圈（含幾何辨識）與皮帶／線材排在接觸零件之後；同形狀同方向合併為 ×N；自動產生步驟名稱與說明；找不到無干涉方向的步驟標示 ⚠。
- **動畫**（`src/viewer/scene-viewer.js`）：位移改為沿節點鏈累加，預組件整組移動、靜態爆炸圖成為分層爆炸；未裝零件淡影／隱藏／展開；本步零件高亮；預組步驟只顯示該預組件；鏡頭平滑跟隨。每步：淡入→移動→停留閱讀，1× 約 3.2 秒，可「每步暫停」。
- **介面**（`src/main.js`）：作業指引字卡、「自動推論」按鈕、步驟卡顯示預組標籤與 ⚠、編輯器改為節點指派並在套用前驗證、時間軸刻度在步驟多時抽樣顯示。
- **建庫**：`npm.cmd run catalog:plan` 預先推論 21 個預設／分站模型（26 秒），輸出 `public/data/plans/`；開啟站別時先讀取，沒有時在 Worker 即時推論（≤700 件自動）。
- **名稱**：STEP 內被誤解碼的 Big5 名稱（如「®ɳW¥ֱa」→「時規皮帶」）自動還原；預先推論以原始名稱比對，避免各平台解碼差異。
- 新增相依套件 `three-mesh-bvh@0.9.15`（MIT）。
- 測試：JavaScript 24 項（新增推論器 6 項、格式 v2 共 8 項）、Python 4 項通過；正式建置通過。瀏覽器驗收見 `VALIDATION.md` 最新區塊，截圖 `output/sequence-*.png`。

未完成／後續：互鎖結構（鉸鏈、滾輪軸承組）仍有大量 ⚠ 步驟待工程師確認；尚未做影片／獨立播放檔／SOP PDF 輸出；SolidWorks API 萃取（配合、爆炸視圖）因無 SolidWorks 暫緩。

## 前輪：全部設備組合圖與成品圖（2026-10-02）

已依追加需求新增左側「全部設備 · 組合圖／成品圖」入口：

- 預設整線總裝，保留來源 CAD 相對位置；可切換組合圖與亮色、無網格的成品圖，亦可切換任一站及四種方向視角。
- 所有站總覽圖包含目前專案全部站別。預設專案 17 站／分類有 16 張模型圖，FA 無幾何保留狀態卡；圖卡可開啟本站成品圖。
- 三種圖均可匯出 PNG，附名稱、來源完整度；全站圖明示獨立尺度、非實際配置及整機／子站可能重複。
- 新增 `equipment-overview.js`、`equipment-overview.css`、`overview-data.js`。總覽暫停底層工作台渲染，模型逐站載入並釋放，關閉後恢復工作台並釋放臨時 GPU 資源；不改寫原專案。
- 真實瀏覽器驗證組合／成品切換、17 站圖卡、圖卡進入、FA 禁止空圖下載、PNG 匯出、關閉／重新開啟、390px 版面；控制台無 warning／error。
- 自動測試 JavaScript 15 項、Python 4 項通過；正式建置通過。輸出為 `output/all-equipment-assembly.png`、`all-equipment-product.png`、`all-stations-overview.png`；畫面證據為 `output/overview-*.jpg`。
- 整線來源本身仍為部分還原（缺少 550、未解析 386 引用），沒有以重複疊加子站或假造幾何補齊。與來源內嵌預覽比對，保留原始總裝配置。

## 前輪：材質真實感加強（2026-10-02）

使用者在前輪驗收後反映 3D 缺乏材質感，本輪已直接改善渲染並重新實測：

- 新增 `studio-lighting.js`、`surface-detail.js`、`render-pipeline.js`，提供多面棚燈反射、細拉絲與微表面法線／粗糙度、GTAO 接縫陰影和 HDR 抗鋸齒後製。
- 修正建庫 STEP 沒有材質時，被 GLTFLoader 白色／高粗糙度預設值遮蔽自動材質的問題；推估限定已知 CAD，保留來源面色與匯入的明確 PBR 材質。
- 調整鋁、不鏽鋼、黃銅、塑膠、橡膠、玻璃及烤漆參數。單獨檢視取消選取染色與自動標籤遮擋，材質預覽更清楚。
- 工具列新增「精緻渲染／流暢操作」。大型整機保留完整幾何，精緻模式降低 AO 解析度；流暢模式關閉 AO／投影但保留反射。
- 台車明暗主題、上／下料整機、烘乾原生快取、黃銅／橡膠／透明材質切換、單獨檢視、爆炸與動畫、390px 版面已複驗。截圖使用 `output/render-v2-*.jpg`；前輪 `qa-*` 為先前外觀。
- 新增 3 項材質回歸測試；最終 JavaScript 13 項、Python 4 項及正式建置通過。細節見 `VALIDATION.md` 最新區塊。
- 測試材質未保存，最後重載捨棄，原已存專案／流程保留。最終停在台車、亮色、組合視圖、精緻渲染；視窗覆寫已解除。

## 前輪驗收與修正（2026-10-02）

- 修正爆炸比例滑桿誤切回組合模式，現在可連續調整 0–100%。
- 單獨檢視依可見零件重新取景，地面也依可見零件定位；恢復全部後重新容納整機。
- 修正重播、前後步驟、選擇步驟與拖曳時間軸後未重新取景造成的裁切；播放完成再播放亦重設取景。
- 降低過亮的照明／環境反射、調整亮色地面及輔助文字對比；保留來源材質與幾何。
- 手機版保留 CAD 資料庫入口，站別按鈕改為可水平捲動的緊湊寬度。
- 改用此版本 Three.js 支援的 `PCFShadowMap`，移除舊陰影設定警告。
- 17 站預設模型、可用替代 CAD、來源診斷、主題重載、材質保存、動畫、整機操作與 1100／900／390px 配置已實測。FA 沒有替代模型；WET／LINE 沒有第二份可顯示模型，沒有假造切換案例。
- `npm.cmd test`：10 項通過（新增單獨檢視取景回歸）；`npm.cmd run test:native`：4 項通過；`npm.cmd run build`：通過。
- 最終重新載入後瀏覽器 warning／error 均為空；本輪早期曾有一次 GPU shader 精度警告，完整保留於 `output/qa-browser-logs.json`。
- 材質保存測試已恢復來源／自動外觀並保存；後續 CAD 切換與材質測試未保存，已重載捨棄。最後停在原專案台車、組合視圖、亮色、1×；視窗尺寸覆寫已解除。
- 新版截圖位於 `output/qa-*.jpg`。舊的 `output/assembly-studio.png` 仍是 2026-10-01 舊版，請勿混用。

後續限制：原生幾何缺件、SolidWorks COM 未實測、各種使用者檔案上傳／JSON 回合測試及跨硬體效能基準，仍依下方與 `VALIDATION.md` 記錄；它們不等於本次已建庫模型的視覺驗收。

## 使用者需求

工作目錄：`D:\Working Space\Python\TestCode\MechanicalAssembly`。

CAD 來源：`D:\Working Space\Python\TestCode\Temp\自動爆炸圖與拆圖CAD設計`。

原始目標為匯入 SolidWorks／CAD 專案後，按設備站別呈現爆炸圖與逐步組裝動畫，並可沿用到其他專案。後續要求為補上漏載的 CAD／站別、加入暗／亮主題，以及提升所有可取得部件的渲染品質。最新工作是在完成視覺驗收後，進一步改善材質真實感並複驗。

## 已完成的程式與資料

- Vite、Three.js 網頁工作台，繁體中文介面；套件版本為 1.1.0。
- 暗／亮主題按鈕，同步切換介面與 3D 場景，偏好保存於本機。
- 完整 CAD 資料庫：搜尋、站別／狀態篩選、分頁、每站 CAD 下拉選單。
- 來源診斷顯示可解析部件、缺少引用、未解析引用、抑制／隱藏引用及原檔內嵌預覽。圖片預覽和可操作 3D 模型有明確區分。
- 組合視圖、爆炸展開、逐步動畫、時間軸、速度、方向視角、邊線、標籤及單獨檢視。
- 可編輯步驟、零件群組、順序、移動方向、距離及裝配指引；可跨站移動部件。
- PBR 材質、環境反射、柔和陰影，保留來源面色、法線與多材質。零件可指定鋁、不鏽鋼、黑化鋼、塑膠、橡膠、透明護罩、黃銅及烤漆外觀。
- 未提供物理材質時以名稱推估顯示外觀，並允許手動指定；不是實際材料或表面處理的工程判定。
- IndexedDB 專案保存及 JSON 匯入／匯出。新版完整資料庫使用 `sat-source-project-v2`，舊版已存專案保留在選單，沒有覆寫使用者舊資料。

## CAD 覆蓋與限制

來源盤點共 2,051 個非暫存檔案。完整 CAD 目錄有 1,747 個 CAD／圖面項目，其中 960 個原檔具有可顯示模型：82 個 STEP／IGES 模型，以及 878 個原生顯示快取模型。另由整機 STEP 抽出 9 個分站模型，共 969 份 GLB。原始 10 站加上上料機、下料機、入水設備、自動線總裝、Tray 盤與治具、晶片與待測物、共用件與 2D 圖面，合計 17 個站別／分類。

上料機 STEP：909 個零件實例、5,959,561 三角面。下料機 STEP：904 個零件實例、6,596,346 三角面。原 WebAssembly 解析器曾回報成功但產生空網格；已加入空網格拒絕，這兩份整機改用桌面 OpenCascade 8.0.1 轉換成功。AA、CA、DA、HA 預設優先使用設備 STEP 分站模型；其他來源仍可切換。

STEP／IGES 細分設定為 0.08 mm 弦差與 0.22 rad 角度。整個模型目錄約 1 GB，建置時會複製到 `dist`；超過 400 萬三角面的場景停用即時陰影以降低 GPU 負擔，不省略幾何。

重要限制：

- FA 換盤除水資料夾只有 `202401-FA00.SLDASM`，其目前配置的 6 個引用全部被抑制，沒有可啟用的機構幾何。頁面呈現診斷及原始預覽，沒有製造代用幾何。
- 部分原生組合件引用資料夾外的零件庫，部分面資料或舊版格式未能解析；頁面標示「部分顯示快取」。可顯示模型數不代表所有原檔完整還原。
- 自製原生快取解析器屬實驗性功能：驗證解壓大小、CRC、三角帶與組合變換後輸出網格；不重建 B-rep，也不保證所有版本或配置一致。詳見 README 與第三方說明。
- SolidWorks COM 轉換介面已實作，但本機未偵測到 SolidWorks，因此尚未實測。一般使用者匯入新的原生檔仍需可用的 SolidWorks 轉換環境，或先匯出 STEP。
- DWG／SLDDRW 是圖面；Parasolid 等格式需另行轉換。來源 ZIP 只包含 2D 圖面與 PDF。
- 自動組裝順序為工程待審核草稿，沒有配合約束、碰撞、工具可達性、扭力或工法驗證。

## 已完成的驗證

這些為前次程式工作時實際執行的結果，本次交接記錄沒有重新執行測試。

- `npm.cmd test`：9 項通過；逐檔解碼 969 份 GLB、13,391 個網格實例，核對數量、有限座標／变換、三角索引及材質群組覆蓋。實例跨檔會重複，不是設備唯一料號數。
- 測試也涵蓋動畫進度、流程指派、來源目錄完整性、空網格拒絕、面色保留、來源階層遺漏網格的補入，以及材質透明度／法線設定保留。
- `npm.cmd run test:native`：4 項通過，涵蓋三角帶繞序、損壞資料拒絕、CRC／解壓大小、組合放置及抑制／缺件診斷。
- `npm.cmd run build`：通過。Three.js 仍有超過 500 kB 的 bundle 提示，不影響建置。
- `VALIDATION.md` 下方保留 2026-10-01 舊版瀏覽器驗證。`output/assembly-studio.png` 為舊版截圖，不能當成本次暗／亮與新渲染的驗收證據。

## 先前視覺驗收阻塞歷史（本次已可操作）

預覽網址：`http://127.0.0.1:6001/`（2026-10-02 起由 5173 改為 6001；6000 是瀏覽器封鎖的不安全埠。下方歷史紀錄仍寫 5173）。

先前 Codex 桌面版的 Browser 工具能列出分頁與標題「Assembly Studio · 機械組裝工作台」，但開啟網址或讀取 DOM 被安全檢查拒絕，當時回覆原因為：`A saved user permission setting blocks this action`。以下保留排查歷史；不是本次狀態。

使用者已完成下列操作，請避免重複要求相同設定：

1. 在「設定 → 瀏覽器 → 智慧體權限」新增精確網址 `http://127.0.0.1:5173`，將「瀏覽中」設為「一律允許」，並提供截圖確認。
2. 已唯讀確認 `C:\Users\grown\.codex\config.toml` 含該 origin 的 `access = "allow"`，沒有由本工作修改該設定。
3. 使用者完整重開 Codex，之後重新啟動本機 Vite 服務並再試；工具仍拒絕。
4. 使用者手動開啟同網址分頁後再試，仍得到相同拒絕。

根因尚未確認，不能宣稱一定是設定快取或帳號問題。使用者現在改用 VS Code 的 Codex 嘗試接續。請依新環境真正可用且獲准的工具確認能否驗收；切換客戶端不代表網站封鎖自動解除。遇到相同安全拒絕，仍須尊重封鎖，不得用換網址／連接埠、另一控制介面或直接 CDP 繞過。

先前舊版測試也曾有 GLB 檔案上傳被拒絕，沒有以替代方式重試上傳。本次主要驗收可先使用已建庫的本機模型，沒有必要上傳檔案。

## 接續步驟與本次完成清單

1. 開啟本資料夾，先讀本檔、`README.md`、`VALIDATION.md`。
2. 檢查 6001 是否已有服務，避免重複啟動到其他連接埠。服務狀態會隨客戶端重啟而改變。
3. 必要時啟動：

```powershell
cd 'D:\Working Space\Python\TestCode\MechanicalAssembly'
npm.cmd run dev
```

`node_modules`、`.venv` 和預轉換模型已存在，通常不需重新安裝或重建所有 CAD。

4. 使用獲准的瀏覽器工具開啟上述網址，核對以下項目並修正發現的問題：

- [x] 亮／暗主題、文字對比、表單與對話框、重新載入後偏好保存。
- [x] 台車 153 件模型的組合與爆炸視圖；模型比例、方向、材質、陰影與部件取景範圍（不等同工程幾何完整性認證）。
- [x] 17 個站別／分類切換，尤其 AA／CA／DA／HA 的 STEP 分站，以及烘乾、掃描、水下移載等部分快取模型。
- [x] FA 的抑制配置與圖片預覽標示正確，沒有將圖片誤當可操作 3D。
- [x] 每站可用 CAD 切換、完整資料庫搜尋／篩選／分頁、來源診斷與模型範圍。
- [x] 選取零件、單獨檢視、材質切換與保存；恢復原選項並保留既有流程。
- [x] 爆炸比例、播放／暫停、前後步驟、拖曳進度、速度與重播；修正已重現的裁切。
- [x] 上／下料整機載入、旋轉與動畫可操作性；記錄 UI 載入與播放進度時間，非 FPS／跨硬體基準。
- [x] 瀏覽器錯誤紀錄、較窄視窗的按鈕與選單配置。
- [x] 保存新版亮色／暗色與模型截圖，更新 `VALIDATION.md` 並列明範圍外尚未完成項目。

若有改程式，再執行適合的回歸檢查：

```powershell
npm.cmd test
npm.cmd run test:native
npm.cmd run build
```

## 主要檔案位置

| 檔案 | 用途 |
|---|---|
| `src/main.js` | 專案、站別、模式、流程、匯入與保存 UI |
| `src/ui/catalog.js` | 完整 CAD 目錄、分站模型、來源診斷 |
| `src/viewer/scene-viewer.js` | 3D 場景、PBR 照明、相機、爆炸位移、點選、陰影 |
| `src/viewer/viewer.js` | 重新匯出 AssemblyViewer |
| `src/viewer/materials.js` | 保留來源外觀與手動材質預設 |
| `src/ui/theme.js`、`src/styles/themes.css` | 暗／亮主題與偏好保存 |
| `src/cad/cad-geometry.js`、`src/cad/importer.js` | CAD 面色、階層、GLB 多材質合併、格式匯入 |
| `scripts/cad/native-display.py`、`scripts/cad/inspect-native.py` | 原生檔顯示快取及組合引用解析 |
| `scripts/catalog/build-catalog.js` | 完整 CAD 建庫與大型 STEP 轉換 fallback |
| `scripts/cad/convert-step-native.py` | OpenCascade 桌面版 STEP 轉換 |
| `scripts/catalog/extract-stations.js` | 從整機 STEP 階層生成 9 份分站模型 |
| `public/data/cad-catalog.json` | 完整來源項目與預設模型 |
| `public/data/station-models.json` | 9 份分站模型來源 |
| `public/data/native-manifest.json` | 原生快取模型及缺件診斷 |
| `public/data/source-inventory.json` | 全部原始檔盤點與圖面摘要 |
| `public/data/model-manifest.json` | 舊版 7 份範例對照，保留舊專案相容性 |
| `README.md`、`THIRD_PARTY_NOTICES.md` | 操作、重建方式、限制與格式參考授權 |

CAD 重建命令為 `npm.cmd run inventory`、`npm.cmd run catalog:native`、`npm.cmd run catalog:build`；僅修改 UI 不需執行。重建會耗時並產生大量模型。STEP 結果目前按檔案 ID 快取，更新來源後需依 README 失效對應 GLB 與 metadata；不可直接刪除來源 CAD。

最後檢查時，Git 顯示本專案目錄仍為未追蹤項目，尚未替使用者提交 commit。`tmp`、`.cache`、`.venv`、`node_modules`、`dist` 與 Python 快取均列入忽略。

## 後續工作提示

> 請先閱讀 WORK_PROGRESS.md 與 VALIDATION.md 的 2026-10-02 全部設備總覽紀錄。組合圖、成品圖、所有站總覽及 PNG 匯出已實測，19 項測試與建置通過，最新截圖為 output/overview-*，圖檔為 output/all-*.png。保留來源 CAD、已存專案及流程；原始整線仍部分還原，FA 無幾何，不把總覽當作完整工程驗證。
