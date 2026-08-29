# 設備教育訓練中心（TrainingCenter）

給自動化公司新人的互動式教材：以 3D 多角度觀察設備，逐一認識每台機台的**機構／電控／軟體**元件，
包含元件的功用、安裝位置、真實照片、規格與動作動畫。

目前收錄 4 台設備、29 個模組、175 個元件，每台設備分四個領域：**機構／電控／軟體／水氣電**（機器視覺歸在軟體）：

| 設備 | 重點 |
|---|---|
| 氫燃料電池發電平台 | 氫氣供應與純化、PEM 電堆、水熱管理、DC/DC 與併網、安全監控 |
| AOI 檢測機 | 輸送定位（含擋停／頂升／剔除氣缸）、XY 龍門、相機／鏡頭／光源、視覺軟體 |
| 自動化搬運移載設備 | 滾筒／皮帶輸送、頂升移載機、完整氣路（FRL、閥組、速度閥、磁簧）、RFID、AGV 對接 |
| 多站機械手臂協作與視覺手眼協調 | 六軸手臂各部件（底座～腕部、減速機、煞車、法蘭）、EOAT、Eye-to-Hand / Eye-in-Hand、手眼校正、安全 PLC |

水氣電分頁除了元件（NFB、進線端、接地、主氣閥、冷卻水閥）之外，還有各設備的「水氣電教育訓練」指南：供應規格、接點位置、送電／供氣／供水順序、斷開順序、LOTO 與日常點檢（`utility_guide`，可在 admin 編輯）。

## 技術架構

- **後端**：Django 6 + django-ninja（`backend/`），SQLite，種子資料為 `backend/catalog/seed/*.json`
- **前端**：Vite + React 19 + TypeScript（`frontend/`）
  - UI：Siemens iX（`@siemens/ix-react`，深色 classic 主題，遵循 https://ix.siemens.io/）
  - 3D：three.js + @react-three/fiber + drei（程序化設備模型、五種預設視角、軌道旋轉；滑鼠移到零件上高亮並顯示名稱，點擊選取；Lightformer 程序化環境光做金屬反射，離線可用）
  - 場景中沒有專屬 mesh 的元件（接頭、端子台、斷路器等）會依 seed 的 `pos` 自動補一個小型 3D 實體（`AutoParts`），確保每個元件都能在 3D 上被指到
  - 動畫：3D 場景內的機構動作（手臂關節、氣缸、輸送帶、風扇）＋ framer-motion 2D 原理動畫

## 快速開始

最簡單：在 PowerShell 執行

```powershell
.\start.ps1           # 背景啟動：遷移 + 種子資料 + Django(8001) + Vite(5174)，並開啟瀏覽器
.\start.ps1 -Attach   # 前景模式：視窗保持開啟，按 Ctrl+C（或關閉視窗）自動停止兩個服務
.\stop.ps1            # 停止（taskkill 整棵程序樹 + 釋放 8001/5174；PID 檔過期會自動清理）
```

> 背景模式下關閉 PowerShell 視窗**不會**停止服務（它們是獨立程序），要用 `.\stop.ps1`；想要「關視窗就停」請用 `-Attach`。

日誌在 `.run/backend.log`、`.run/frontend.log`。

手動啟動：

```powershell
# 1. 後端
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py load_seed
.\.venv\Scripts\python.exe backend\manage.py createsuperuser   # 選用：進 /admin 編輯內容
.\.venv\Scripts\python.exe backend\manage.py runserver 8001

# 2. 前端（另一個終端）
cd frontend
npm install
npm run dev        # http://localhost:5174（/api 與 /media 會 proxy 到 8001）
```

API 文件：http://127.0.0.1:8001/api/docs

## 元件照片

### 來源一：Wikimedia Commons（預設，已內建）

每個元件的 seed 都有 `photo_query`，以 `|` 分隔多組、依序嘗試：

- `cat:<Commons 分類> ~ 提示詞`：取分類的直接成員，提示詞用來在成員中排序（最準確，優先使用）
- `deep:<Commons 分類>`：含子分類（很容易跑題，慎用）
- 純英文關鍵字：全文搜尋，需所有詞命中標題／描述／分類

執行：

```powershell
.\.venv\Scripts\python.exe backend\manage.py fetch_photos             # 只補沒有照片的
.\.venv\Scripts\python.exe backend\manage.py fetch_photos --force     # 全部重抓
.\.venv\Scripts\python.exe backend\manage.py fetch_photos --equipment aoi
```

- 只接受 CC / Public domain 授權的 JPEG/PNG；作者與授權寫入 `photo_credit`，檔案頁寫入 `photo_source_url`，前端會顯示並可點連結（符合 CC 標示義務）。
- 縮圖經 Commons `thumb.php` 取得（直接抓 `upload.wikimedia.org` 會被機器人政策擋 403）。
- 抓到的照片是「同類示意」而非該型號；目前約 85% 合適，已知仍不理想的有：散熱器與風扇、IIoT 資料閘道、環形 LED 光源、RFID 讀寫頭、橫向移載皮帶組、條形 LED 光源、手眼校正板。請在 `/admin` 檢視，不合適的可換 `photo_query` 後 `--force` 重抓，或直接上傳自拍照片（自拍照片優先，`fetch_photos` 不會覆蓋已有照片，除非 `--force`）。
- 修改關鍵字：編輯 `backend/catalog/seed/add_photo_queries.py` 後執行它，再 `load_seed`。

### 來源二：公司自行拍攝

1. 把照片放到 `backend/media/components/<設備 slug>/<元件 slug>.jpg`（也支援 png / webp）
   - 設備 slug：`fuel-cell`、`aoi`、`transfer`、`robot-cell`
   - 元件 slug 見對應的 `backend/catalog/seed/*.json`
2. 重新執行 `python manage.py load_seed`，會自動掛上照片
3. 或直接到 `/admin` → Components 逐一上傳，並填寫 `photo_credit`（拍攝者／來源）

> 照片請使用公司自行拍攝或取得授權的圖片；種子資料中的品牌與型號為「範例」，請依實際 BOM 修改。

## 互動方式

- 設備頁：滑鼠移到 3D 零件上高亮並顯示名稱；點擊任何零件（不限目前分頁）會自動切到該元件所屬的領域分頁、捲到分頁頂顯示詳細資訊，並把清單中的該列捲入視野。
- 元件字典：依機構／電控／軟體／水氣電分頁，再用類別 pill 與關鍵字過濾。

## CAD Studio：輸入文字 → 產生 3D CAD → 匯出

側欄「CAD Studio」（`/cad-studio`）：

1. **AI 產生 3D CAD**（主要流程）：用中文描述零件——可以只給品牌型號（例：`DENSO HSR-048 四軸 SCARA`），AI 會解讀型號、列出尺寸假設，LLM（預設 Google Gemini；可切換 Groq／OpenRouter／Ollama／Claude）依 text-to-cad skill 的建模規範＋本專案零件庫 API 寫出 build123d 程式 → cadgen 建置 → 右側 3D 預覽。建置失敗會**自動把錯誤回饋給 AI 重寫**（最多 2 次，說明欄會標「自動修復第 N 次」）；仍失敗可再按「依上一版修訂」或自行改程式。執行環境另有相容包裝：AI 常見的誤用（`asm.add(..., loc=...)`／`position=`／`asm.root`）會被自動轉成正確呼叫。
2. **執行下方程式**（進階）：自己寫／修改 build123d 程式（可 `import parts` 用 93 個零件 builder，或從下拉選單插入範本）→ 建置。
3. **匯出**：STEP（主要 CAD 檔）、GLB、STL、3MF、快照 PNG；並可一鍵「掛到教育訓練頁」的某個元件或整台設備。

需求：
- 先執行一次 `.\setup-cad.ps1`：建立 `cad/.venv`（cadgen）並下載 `cad/text-to-cad`（skill 工具）；或用環境變數 `CAD_PYTHON`／`CAD_SKILL` 指向既有環境。`start.ps1` 啟動時若缺少會提示。
- AI 模式預設用 **Google Gemini（免費層）**：到 https://aistudio.google.com/apikey 申請金鑰，把 `.env.example` 複製成 `.env` 填入 `GEMINI_API_KEY`，再 `.\stop.ps1`、`.\start.ps1`（`start.ps1` 與後端都會自動載入 `.env`，不進版控）。預設模型 `gemini-pro-latest`（Google 別名，避免特定版本被停用），模型不存在或配額用盡時會自動依序改試 `gemini-3.1-pro-preview` → `gemini-flash-latest` → `gemini-2.5-flash`；也可用 `CAD_STUDIO_MODEL` 固定。
- 其他 provider（`.env` 的 `CAD_STUDIO_PROVIDER`）：`openai_compat` 走任何 OpenAI 相容端點（Groq、OpenRouter、本機 Ollama 等，設 `CAD_STUDIO_BASE_URL`／`CAD_STUDIO_API_KEY`／`CAD_STUDIO_MODEL`）；`claude` 用 `ANTHROPIC_API_KEY`。沒有金鑰時頁面會提示，程式模式仍可用。
- 建置在背景執行緒進行、結果存 `media/cadstudio/<job>/`，前端每 1.5 秒輪詢。
- 注意：程式模式會在伺服器上執行使用者提供的 Python，只適合內網教育訓練環境。

後端：`backend/cadstudio/`（`runner.py` 呼叫 skill 的 gen/export/inspect/snapshot；`ai.py` 依 provider 呼叫 LLM；`api.py` 提供 `/api/cad/*`）。

## 3D：全部元件為 text-to-cad CAD，整機以 AssemblyHelper 組裝

目前四台設備的 3D 已**不再是程序化 three.js 場景**，而是 build123d 參數化 CAD：

- `cad/lib/parts.py`：93 個參數化零件 builder（PLC、氣缸、閥組、接頭、相機、輸送機、機架、電控櫃…），單位 mm、+Z 向上、原點在底面中心。
- `cad/lib/robot.py`：六軸手臂，巢狀關節子組（`r1-j1 ⊃ r1-j2 ⊃ r1-j3 ⊃ r1-wrist ⊃ flange/gripper`）。
- `cad/lib/layout.py`：場景座標（公尺、Y-up，與前端相同）→ CAD 座標；`anim_datums()` 在可動節點內嵌入隱形基準點 `_pivot`／`_axis`／`_anim_<kind>`（kind：rev 擺動、spin 旋轉、rod 往復、carrier 循環、blink 閃爍）。
- `cad/models/{fuel_cell,aoi,transfer,robot_cell}.step.py`：整機組裝（`cadgen.assembly.AssemblyHelper`），**節點名稱 = seed 的 `mesh_name`**，前端據此 hover／點選／高亮。
- 前端 `frontend/src/three/GltfScene.tsx`：載入整機 glb，往上找最近的已知節點名做互動，依基準點做動畫（關節繞樞軸擺動、滾筒各自自轉、載具循環、氣缸桿往復）。程序化場景（`three/scenes/`）保留作為沒有 glb 時的備援。

### 建置流程

```powershell
.\setup-cad.ps1     # 一次性：cad\.venv（cadgen）+ cad\text-to-cad（skill 工具）

$env:PYTHONUTF8 = "1"
cad\.venv\Scripts\python.exe caduild_parts.py                 # 93 個零件 → cad/out/parts/*.glb（煙霧測試）
cad\.venv\Scripts\python.exe caduild_all.py                   # 四台整機 glb + 所有元件 glb，並掛到資料庫
cad\.venv\Scripts\python.exe caduild_all.py --equipment aoi --skip-parts   # 只重建一台
```

`build_all.py` 用 skill 的 `scripts/export` 匯出整機（保留節點名稱與階層），用 `attach_model` 掛到 `Equipment.model_file`；元件 glb 依 `COMPONENT_BUILDER` 對照表掛到 `Component.model_file`（詳細面板的 3D CAD 檢視器）。

### 修改或新增元件的 3D

1. 在 `parts.py` 加 builder（或調參數），`build_parts.py --only <name>` 確認。
2. 在對應的 `cad/models/<設備>.step.py` 用 `place(builder, (x, y, z))` 放到場景座標；名稱要等於 seed 的 `mesh_name`；會動的用 `sub_compound(name, [...] + anim_datums(kind, pivot, axis))`。
3. `build_all.py --equipment <slug> --skip-parts`，前端重新整理即可（Vite 會 proxy `/media`）。
4. 驗證：`cad/out/equipment/*.png`（`scripts/snapshot --input x.glb`）與瀏覽器。

### 品質與限制

- 零件是「型錄外形」等級的參數化 CAD，尺寸可量測、可出 STEP；不是原廠模型。要更像實物，改 builder 的參數與特徵即可（例如把型錄的孔位、法蘭尺寸填進去）。
- `add_module` 的 `location` 不會匯出成 glb 節點轉換，所以幾何一律以絕對座標烘入，關節樞軸靠基準點。
- 踩過的坑見 CLAUDE.md（`PYTHONUTF8`、布林單一清單、`(Pos * Cylinder).rotate` 括號、巢狀清單攤平）。

## 使用真實 3D 模型（選用）

程序化模型是為了在沒有 CAD 的情況下也能上線。若要更真實的渲染：

1. 由 SolidWorks / Inventor 匯出 glTF（`.glb`），建議先減面到 < 20 MB
2. 放到 `backend/media/models/<設備>.glb`，在 `/admin` 的 Equipment 設定 `model_file`
3. 前端偵測到 `model_file` 時會改載入 glb；元件熱點仍使用 seed 中的 `pos` 座標，需依模型原點調整

## 種子資料版本

- `backend/catalog/seed/*.json`：主要資料
- `backend/catalog/seed/add_photo_queries.py`：照片關鍵字（改完執行它）
- `backend/catalog/seed/update_v2.py`：第二版調整（改名、視覺歸軟體、接頭、水氣電）；可重複執行，已存在的元件不會被覆寫

## 新增設備或元件

編輯或新增 `backend/catalog/seed/<slug>.json`，欄位：

- `pos`：熱點在 3D 場景中的座標（公尺，Y 向上）
- `mesh_name`：對應 `frontend/src/three/scenes/*.tsx` 中 `<Box name=...>` 的名稱，點選 3D 零件時用來對應元件
- `animation_key`：`cylinder`、`gripper`、`robot-joint`、`belt`、`rollers`、`valve`、`spin`、`flow`、`lift`、`gantry`、`flash`／`blink`、`glow`

新設備需同時在 `frontend/src/three/Viewer.tsx` 的 `SCENES` 註冊一個場景元件。
