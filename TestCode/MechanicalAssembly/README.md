# Assembly Studio · 設備組裝爆炸圖工作台

此專案讀取來源 CAD 幾何及可解析的原生顯示快取，提供分站 3D 爆炸圖與可編輯的逐步組裝動畫。介面為繁體中文。

## 啟動

需要 Node.js 20.19+ 或 22.12+；此環境已完成套件安裝。

```powershell
cd 'D:\Working Space\Python\TestCode\MechanicalAssembly'
npm.cmd install
npm.cmd run dev
```

開啟 http://127.0.0.1:6001/ 。亦可執行 `start.ps1` 啟動、`stop.ps1` 停止（只停止本專案的 Vite 服務，埠被其他程式佔用時不會動它）。CAD 與儲存的專案在本機處理，不傳送到外部服務。

```powershell
npm.cmd test        # 動畫進度、完整性、資料格式與檔案路徑檢查
npm.cmd run build  # 產生 dist
npm.cmd run preview # 檢查靜態版本
```

靜態版本包含完整目錄與預轉換模型，仍可在瀏覽器匯入 STEP / IGES / GLB 等檔案；直接讀取尚未轉換的來源檔與 SolidWorks COM 轉換需使用 `npm run dev` 的本機 API。不能直接雙擊 index.html，WebAssembly 與模組需 HTTP 服務。

## 功能與操作

- 右上角「暗色／亮色」切換介面與 3D 場景主題，選擇會保存於本機。
- 左側 17 個站別與分類；每站「本站 CAD」下拉選單可切換全部原始 CAD 與設備 STEP 分站模型。資料庫可搜尋、按站別與可顯示狀態篩選，並提供分頁。
- 「来源狀態」列出模型來源、缺少／未解析／抑制引用及原檔內嵌預覽。內嵌預覽圖片不等於可操作 3D 模型。
- 可新增站別與建立獨立設備專案。原本 v1 專案仍保留在專案選單；新完整資料庫使用獨立 v2 專案 ID。
- 中央組合視圖、爆炸展開比例、旋轉／平移／縮放、等角／正面／側面／俯視、邊線、零件標籤與 PNG 截圖。
- 組裝流程可播放／暫停、逐步前進／返回、拖曳進度、設定速度與重播。空白鍵播放；左右方向鍵切換步驟。每步依序為淡入、沿裝入方向移動、停留閱讀（1× 約 3.2 秒）；「每步暫停」會停在下一步起點，「鏡頭跟隨」平滑移到本步零件。
- 作業指引字卡顯示目前步驟與裝配說明；本步零件以琥珀色高亮。未裝零件可選「淡影」（在完成位置淡化顯示）、「隱藏」或「展開」。預組步驟只顯示該預組件，其他零件淡化，如同在工作台另外組裝。
- 「自動推論」依 CAD 階層與幾何干涉重新排出組裝順序（見下方「組裝順序推論」）。
- 右下角座標軸隨視角轉動，採 **Z 朝上、XY 為水平面** 的顯示座標；流程編輯器與步驟說明中的 ±X／±Y／±Z 都以此為準。
- 工具列「CAD ? 軸朝上」指原檔自身哪一軸朝上。SolidWorks 預設 Y 朝上，但部分組合件以上視基準面建模（Z 朝上），直接顯示會躺倒或倒立。各模型的預設值見 `public/data/orientation.json`：自動線總裝、入水除泡、Tray、晶片為 Z，入水設備為 −Z，掃描與共用件為 X，其餘為 Y。若某個模型仍不對，可在選單改正，該站會依新方向重新推論組裝順序並隨專案保存。
- 地面固定在組合完成時的設備底部（單獨檢視除外），不隨展開或從下方裝入的零件下移；地面略透明，地面以下的零件仍看得到。第一步「放置基座」由上方降落定位，播放時看得出動作。
- 本步零件顯示琥珀色箭頭，由展開位置指向完成位置，播放與輸出的圖片都看得到裝入方向。
- 「⇩ 作業指導書」：選擇步驟範圍，每步擷取零件在起始位置＋箭頭的畫面（約 1080p），附說明、零件數量表與完成／自主檢查欄，輸出單一 HTML 並在新分頁開啟，可直接「列印／另存 PDF」。超過 120 步預設只輸出前 120 步，可分冊。
- 「● 錄影」：選擇步驟範圍與速度，依目前視角與鏡頭跟隨即時播放，錄成含步驟字卡與進度條的 WebM（高度至少約 1080 像素）。錄影時請勿切換分頁，可隨時停止。
- 點選零件或使用零件搜尋，可單獨檢視、移至其他站別與設定顯示材質（鋁、不鏽鋼、黑化鋼、塑膠、橡膠、透明護罩、黃銅、烤漆）。模型世界座標保留，重新分站後會依站別重新置中。
- 編輯組裝流程：步驟名稱、工程指引、順序、零件／預組件指派、移動方向（推論方向、徑向或座標軸）、展開距離、新增／合併步驟與審核標記。套用前檢查「預組件內的零件必須在該預組件安裝前完成」，違反時顯示原因不套用。
- 儲存專案使用 IndexedDB；同一瀏覽器與網址重新開啟即可延續。匯入面板可匯出完整 `.assembly.json`（包含模型幾何與步驟），供備份與跨裝置重用。不同瀏覽器、不同連接埠的本機儲存彼此獨立。
- 多檔匯入可建立新站；資料夾匯入按檔案的直接父資料夾分站。完整設備檔可先匯入一站，再使用零件檢視器分配到其他站。

## 支援格式

| 格式 | 處理方式 | 限制 |
|---|---|---|
| STEP / STP、IGES / IGS、BREP | OpenCascade WebAssembly 在 Worker 中解析 | 保留解析器提供的階層與實體，輸出為毫米；不保留原生配合約束 |
| GLB | Three.js GLTFLoader | 保留網格變換；不播放來源檔原有動畫；壓縮的 Draco / Meshopt 模型尚未加入解碼器 |
| STL | STLLoader | 一般只有單一網格，無法憑空還原 BOM 或零件關係；預設 Z 為上方向 |
| OBJ | OBJLoader | 支援幾何與群組；不載入外部 MTL／貼圖；預設 Y 為上方向 |
| SLDASM / SLDPRT | 本機 SolidWorks COM 轉換為 STEP，再交給相同匯入流程 | 需要 Windows、已安裝並授權 SolidWorks，完整引用檔案與可用配置 |
| Parasolid X_T、DWG、SLDDRW | 請在 CAD 軟體另存 STEP 或 GLB | 目前不直接解析；2D 圖面不能還原完整 3D 裝配 |
| assembly.json | 完整模型與流程匯入 | schemaVersion 必須為 1，零件與步驟指派需一致 |

單檔上限 200 MB；CAD Worker 解析上限 180 秒。大型設備建議按站別匯出。大型模型超過 100 件時只顯示選取零件的標籤。

## 原始資料覆蓋（2026-10-02）

來源：`../Temp/自動爆炸圖與拆圖CAD設計`。所有原始檔保持原樣。

已盤點 2,051 個非暫存檔，其中有 207 個 SLDASM、875 個 SLDPRT、79 個 STEP/STP、3 個 IGES、559 個 DWG/SLDDRW 與 296 個 PDF。原始資料內的 ZIP 為 2D 圖面與 PDF，未提供額外 3D 裝配。

完整 CAD 目錄包含 1,747 個原始 CAD／圖面項目：960 個已產生可顯示模型（82 個 STEP/IGES、878 個原生顯示快取），另外從上、下料機 STEP 階層產生 9 個可獨立開啟的站別模型。這是「可顯示檔案數」，不代表每份原生組合件都已完整還原；狀態標記及診斷列明限制。

| 站別／分類 | 預設模型的零件數 | 來源與覆蓋範圍 |
|---|---:|---|
| 202401-AA00 機架外罩 | 243 | 設備 STEP 分站模型；202401-AA00 · 上料機 STEP 分站 |
| 202401-BA00 台車 | 153 | 精細 CAD 網格；202401-BA00(Magzin).STEP |
| 202401-CA00 conveyorⅡ | 499 | 設備 STEP 分站模型；202401-CA00 · 上料機 STEP 分站 |
| 202401-DA00 升降 | 37 | 設備 STEP 分站模型；202401-DA00 · 上料機 STEP 分站 |
| 202401-EA00 入水除泡 | 280 | 原生組合件顯示快取 · 部分還原；202401-EA00.SLDASM |
| 202401-FA00 換盤除水 | 0 | 來源配置無可顯示零件；202401-FA00.SLDASM |
| 202401-GA00 烘乾 | 147 | 原生組合件顯示快取 · 部分還原；202401-GA00.SLDASM |
| 202401-HA00 NG排除 | 46 | 設備 STEP 分站模型；202401-HA00 · 下料機 STEP 分站 |
| 202401-IA00 水下移載 | 29 | 原生組合件顯示快取 · 部分還原；202401-IA00.SLDASM |
| 202401-JA00 掃描 | 10 | 原生組合件顯示快取 · 部分還原；202401-JA00.SLDASM |
| LOAD 上料機 | 909 | 精細 CAD 網格；Load machine_240608.STEP |
| UNLOAD 下料機 | 904 | 精細 CAD 網格；UnLoad machine_240608.STEP |
| WET 入水設備 | 802 | 原生組合件顯示快取 · 部分還原；入水站.SLDASM |
| LINE 自動線總裝 | 2283 | 原生組合件顯示快取 · 部分還原；自動線規劃_240503.SLDASM |
| TRAY Tray 盤與治具 | 5 | 精細 CAD 網格；Tray盤組件-5.STEP |
| CHIP 晶片與待測物 | 1 | 原生零件顯示快取；JM0004-AMS-3-01-250312.SLDPRT |
| SHARED 共用件與 2D 圖面 | 1 | 精細 CAD 網格；202401-ED01.STEP |

AA、CA、DA、HA 預設優先使用設備 STEP 內的對應站別，保留原始放置座標與階層。下拉選單仍可選其他版本及原始檔；不同日期／配置的 CAD 不視為同一份完整設計。

FA 換盤除水的資料夾只有原生組合件，其目前配置的 6 個引用全部被抑制；此來源沒有可啟用的 3D 幾何。其他原生組合件還引用資料夾外的零件庫。頁面提供原始預覽與診斷，缺件需從原設計端補齊，不能靠渲染重建。

原生快取讀取器屬實驗性功能：驗證容器 CRC／解壓長度、面三角帶記錄與有限座標，再套用 XML 中的組合變換。它不重建 B-rep、不驗證配合，不保證支援所有 SolidWorks 版本或組態；隱藏／抑制引用及不支援的資料不會冒充已完成模型。快取精度受原始儲存設定限制。

STEP/IGES 以 0.08 mm 弦差、0.22 rad 角度設定重新細分。大型 STEP 的 WebAssembly 解析器若未產生三角面，建庫時改用桌面 OpenCascade；不把空網格標成成功。保留來源面色、法線、多材質與重複元件，渲染使用 PBR 材質、環境反射、柔和陰影及邊線。未提供物理材質者使用名稱推估外觀，可手動更改；它不是實際材質／表面處理的工程判定。

2026-10-02 材質加強：使用多面棚燈反射環境、金屬細拉絲／非金屬表面微紋理、GTAO 接縫與接觸陰影、HDR 後製與抗鋸齒。已建庫 CAD 的空白預設材質會補上顯示外觀，來源面色和使用者匯入的明確 PBR 材質仍保留。單獨檢視不再染上選取色，可直接判斷材質本色。

工具列可選「精緻渲染」或「流暢操作」：流暢模式關閉 AO 和即時投影，保留材質反射；超過 400 萬三角面的精緻場景使用較低解析度 AO，停用方向光投影，不刪減幾何。下載視角圖片使用相同渲染管線。

### 全部設備組合圖與成品圖

左側「全部設備 · 組合圖／成品圖」開啟設備總覽，預設顯示原始自動線總裝的組合位置。「成品圖」使用亮色棚燈外觀、隱藏網格；可旋轉、切換等角／正面／俯視／側面，亦可由選單選取任一站。

「所有站總覽圖」依序產生目前專案全部站別的圖卡，點選圖卡可進入該站成品視圖。完整資料庫目前共 17 個站別／分類、16 個可顯示模型，FA 無幾何仍保留狀態卡。總覽各站獨立取景，並非實際廠區配置，整機與子站也可能包含相同零件。

三種視圖皆可下載 PNG，圖片包含名稱與來源完整度；全站圖為 1920px 寬。整線來源仍有缺少／未解析引用，成品圖僅呈現現有 CAD 的完成組合外觀。總覽不寫入專案、不更動零件與流程；關閉時釋放臨時模型及渲染資源。

PDF 已擷取 296 份文字，包含根目錄 18 份設備參考圖；它們提供部件與尺寸參考，未提供完整装配工法。

重新盤點與轉換（執行於專案根目錄）：

```powershell
python -m pip install --target .python-libs pymupdf olefile cadquery-ocp==8.0.1.0.0
npm.cmd run inventory
npm.cmd run catalog:native
npm.cmd run catalog:build
npm.cmd test
npm.cmd run test:native
npm.cmd run build
```

`npm.cmd run catalog:orient` 推算各模型的朝上軸：以目視確認方向的總裝為起點，讀出每個子組合件／零件在總裝中的擺放旋轉，反推它自身的朝上軸（多處引用取多數），再由已確定的子件反推未出現在總裝的組合件；整機 STEP 分出的分站沿用整機方向，STEP 零件比照同名原生檔。目前 969 個模型中 441 個有依據，其餘預設 Y，依據寫在 `orientation.json` 的 `evidence`。改了朝上軸後要重跑 `catalog:plan`。

`npm.cmd run catalog:plan` 為各站預設模型與 STEP 分站模型預先推論組裝順序（約 26 秒），輸出 `public/data/plans/`；加 `--all` 可涵蓋全部可顯示模型。模型或推論器版本變更後需重跑，否則開啟站別時改為即時推論。

`catalog:build` 會重用既有 STEP 轉換結果；來源檔更新時請刪除該來源對應的 `public/models/cad/<id>.glb` 與 `.meta.json` 後重建。`id` 可在 `public/data/cad-catalog.json` 查詢。原生快取會重新建立；既有專案的手動流程應由工程師確認是否仍適用新模型。

完整資料集目前約 1 GB，正式建置會複製到 `dist`；首次載入整機仍需時間。超過 400 萬三角面的視圖會停用即時陰影以降低 GPU 負擔，零件幾何不因此省略。

## 展示影片

```powershell
npm.cmd run dev   # 另開視窗
node scripts/render-showcase.mjs --station=202401-BA00 --out="D:\Working Space\Python\TestCode\TEMPideos\MechanicalAssembly-台車_1080p30.mp4"
```

以 Playwright 開啟工作台，透過 `window.studioAutomation` 以虛擬時鐘逐格指定狀態並算圖（GPU，1920×1080、30 fps），不受即時效能影響、不會掉格；畫面依序為片頭、組合外觀環繞、爆炸圖展開與環繞、收合、逐步組裝（字卡、箭頭、鏡頭跟隨）、片尾。以 NVENC（`MilitaryGradePC/tools/bin/ffmpeg.exe`，可用 `--ffmpeg=` 指定）編碼 H.264。

防閃爍：地面固定先畫、預組步驟隱藏其他零件、進入組裝與預組情境切換時以上一格交叉淡化、不開 temporal AQ。輸出後解碼逐格比對亮度，`-verification.json` 記錄單格閃爍、黑畫面與變化最大的幾格，另產生 `-contact.jpg` 縮圖總覽。

## 組裝順序推論

開啟站別時，若流程仍是未編輯的自動草稿，會先讀取建庫時的推論結果；沒有時在背景執行緒即時推論（700 件以下自動執行，更大的模型按「自動推論」）。匯入的 STEP／GLB 也走相同流程。

1. **階層**：沿用 CAD 的組合件階層。子組合件成為「預組件」，先在旁邊組好再整組裝上；單一零件的多個實體、`MISUMI_`／`SMC_` 等購入品視為一件。
2. **拆卸方向**：每個單元內，對每件零件測試 ±X／±Y／±Z 及其軸向（螺絲、銷、軸）或板面法向。取樣點沿表面往內縮 0.25 mm，沿方向發出射線（BVH 加速），撞到其他零件即視為被擋；貼合面不會誤判。
3. **順序**：先選體積最大的結構件為基座，其餘由外往內逐件拆下（小件優先、同形狀連續處理），反轉即為組裝順序；移動方向優先由上往下。
4. **互鎖時先組合**：沒有任何單件能移出時，在方向阻擋圖中找「彼此卡住、但可沿同一方向一起移出」的最小零件群（例如軸＋軸承），自動建立「〇〇 組件」，步驟說明會寫明先組合再整組裝入。銷＋擋圈組成的購入品會拆開，擋圈先拆、銷沿軸抽出。
5. **緊固件與可撓件**：螺絲、螺帽、墊圈、銷，以及幾何辨識的擋圈／墊圈，排在它接觸的零件都裝好之後，沿自身軸向鎖入（螺紋段與孔重疊是 CAD 常態，不列為待確認）；皮帶、線材、氣管同樣後裝，不做剛體干涉判斷。
6. **分組與說明**：相鄰、同形狀、同名稱、同方向的零件合併為一步（×N），自動產生步驟名稱與裝配說明；STEP 內誤解碼的 Big5 中文名稱會還原。

上料機 909 件約 7 秒、自動線總裝 2,283 件約 9 秒（Node，建庫時）。

### 實際限制

- 推論結果是**待審核草稿**：沒有配合約束、扭力、工具可達性、治具或人因判斷。
- 互鎖結構（鉸鏈銷穿過多件、皮帶包覆帶輪、壓入件、螺紋段與孔重疊的 CAD）找不到無干涉方向時，取阻擋最少者並在步驟標示 ⚠。目前上料機 715 步中有 41 步、下料機 740 步中有 42 步需確認（第一版各為 144、137 步），剩下的多為推論組件內的軸承、緊配件與無法還原名稱的皮帶。
- 只測直線移出，不含旋轉、螺旋或先移後轉的路徑；撓性件與擋圈的變形不模擬。
- 緊固件辨識靠名稱與薄環幾何；未命名、非標準名稱的螺絲會當一般零件處理。
- 實體由來源 CAD 決定：STEP 的未命名實體顯示為「〇〇 零件 N」，部分無法完整還原的 Big5 名稱維持原樣。

SolidWorks 轉換服務已實作，但此機器未偵測到 SolidWorks COM 註冊，因而無法在此環境實測原生轉換。服務會回傳明確狀態，不產生代用假模型。未來在有 SolidWorks 的機器上需驗證 API 版本、引用解析與 STEP 組合結構輸出設定。開檔／輸出出現錯誤或警告將拒絕轉換，避免顯示不完整模型。

## 擴充結構

```text
src/core.js         專案格式 v2、驗證、v1 轉換與動畫時間
src/planner/        組裝順序推論：階層整理、BVH 射線干涉、拆卸排序
src/planner-*.js    推論的 Worker 與預先推論結果讀取
src/names.js        Big5 誤解碼名稱還原
src/scene-viewer.js 3D 場景、爆炸位移、點選、標籤與視角
src/materials.js    來源材質保留與顯示材質設定
src/theme.js        暗／亮主題與偏好保存
src/catalog.js      完整檔案目錄、分站模型與缺件診斷
src/cad-geometry.js CAD 面色、階層與三角面完整性
src/importer.js     CAD／GLB／STL／OBJ 轉為共同 Three.js 模型
src/cad-worker.js   OpenCascade 解析與 typed array 傳輸
src/storage.js      IndexedDB 專案儲存
src/main.js         專案／站別／組裝編輯介面
vite.config.js      本機原始檔 API 與 SolidWorks 轉換服務
scripts/            檔案盤點、GLB 範例轉換、SolidWorks COM、預先推論（plan-catalog.js）
public/data/        原始檔案盤點與範例來源對照
public/models/      真實 CAD 預先轉換的 GLB
public/vendor/      OCCT JavaScript / WASM，無需外部 CDN
```

共同專案資料為 `{schemaVersion:2, id, name, stations:[...]}`。每站含 `id/name/source/scope/parts/nodes/plan/model`；`model` 使用 Three.js Object3D JSON。`parts[].id` 對應模型 `userData.partId`，`parts[].nodeId` 指向一個 `atomic` 節點。`nodes[]` 為 `{id, name, parentId, kind: "unit"|"atomic"}` 的樹，`root` 為本站。`plan[]` 含 `id/name/kind/unitId/nodeIds/instruction/axis/dir/distance/reviewed`：每個非 root 節點恰好在一步安裝，子節點的步驟必須早於其預組件的安裝步驟。`axis: "auto"` 使用推論方向 `dir`（移出方向，即零件起始位置相對完成位置的方向）。v1 專案（`plan[].partIds`）讀入時自動轉成每件一個節點，保留原分組、方向與審核狀態。此結構能替換匯入介面，未來接入商用 CAD SDK、PDM、BOM 或企業資料庫而沿用視圖與流程編輯器。

本機 API 固定綁定 127.0.0.1，檔案庫限制在指定來源根目錄。原生上傳暫存於 `.cache/imports`；可在停止服務後移除不用的暫存資料。此版本為單使用者本機工作台，未包含帳號、多人同步與伺服器授權，不能直接當作對外 CAD 上傳服務。

## 技術依據

- [OCCT import API 與階層／網格格式](https://github.com/kovacsv/occt-import-js/blob/main/README.md)
- [Three.js GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html)
- [SolidWorks OpenDoc6](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~OpenDoc6.html)
- [SolidWorks SaveAs](https://help.solidworks.com/2022/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IModelDocExtension~SaveAs.html)
