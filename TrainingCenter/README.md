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

前端的設備清單、元件詳細面板、元件字典與知識卡共用 `ComponentImage`：實拍照片優先，缺少或載入失敗時使用本地 CAD 渲染縮圖（標示「3D 示意」）；只有未知類型或縮圖損壞才退回 SVG。軟體元件以螢幕與流程／資料／視覺畫面呈現，標示「概念圖」。圖庫不覆蓋資料庫的照片與來源，也不宣稱是特定品牌型號的原廠模型。

### 本地 3D 圖庫與動畫

`frontend/public/component-visuals/` 隨專案提供 110 組 GLB + 640×480 PNG，透過 `frontend/src/assets/component-visuals.json` 精確對應全部 175 個設備元件與 185 張知識卡（相同零件家族共用資產）。正常啟動不需要另外安裝 CAD 環境或下載圖床圖片。

- 點選設備元件後可拖曳旋轉、縮放、自動旋轉與重設 3D 視角。既有 `model_file` 優先，缺檔時回到內建模型。
- 列表只載入靜態縮圖；詳細檢視進入可視範圍才建立 Canvas，靜止時按需重繪。
- 機台動畫提供 0.5×／1×／2×、暫停與重播；暫停不累積模擬時間。AOI 每三件示範一次 NG 剔除，其餘 OK 放行；相機平滑回程。新增 CAD 節點保留原始位置與關節姿態。
- 機台場景中未建模的元件，使用圖庫模型呈現可點選的小型實體；尺寸為辨識用途，不作機台尺寸量測。

修改模型後重建（需要既有 `cad/.venv`；圖庫生成器對缺漏對應或建置失敗會回傳非零結束碼）：

```powershell
$env:PYTHONUTF8 = '1'
cad/.venv/Scripts/python.exe cad/build_visual_library.py
# 另一個終端先在 frontend 執行 npm run dev
cd frontend
# 首次：npx playwright-core install chromium；或指定已安裝 Chromium 的 chrome.exe
$env:CHROMIUM_PATH = 'C:/Users/grown/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
npm run render:icons
npm test
npm run build
```

`cad/lib/parts.py` 為既有零件庫，`cad/lib/visual_parts.py` 補充手臂分節、軸承、減速機、卡套接頭與軟體概念模型；`cad/build_visual_library.py` 維護 slug／知識卡料號的對應。`frontend/tools/render-components.ts` 使用同一套材質分類、室內環境光與陰影批次渲染，無外部 HDR 相依。新增元件後先新增對應與模型再重建，`npm test` 會檢查所有 seed 的 GLB 與縮圖是否完整。

外觀參考：[SMC CQ2 氣缸](https://www.smcworld.com/webcatalog/en-sg/air-cylinders/compact-air-cylinders/CQ2-CDQ2-Z-E/)、[Siemens S7-1200](https://www.siemens.com/en-us/products/simatic/s7-1200-g2/)、[Basler 工業相機](https://www.baslerweb.com/en/use-cases/helmee-imaging-aoi-high-gloss-car-parts/)、[Festo DHPS 夾爪](https://media.festo.com/media/202808_documentation.pdf)。上述照片僅供外觀研究，圖庫圖片為本專案 CAD 自行渲染。

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

### 來源二：Google 圖片（`fetch_google_photos`）

Commons 對工業元件的覆蓋率不好（實測約四成抓錯），想要原廠產品照就用這個。

**設定**（一次就好，填在專案根目錄 `.env`）：

1. 到 Google Cloud 建一把 API key，並在同一個專案啟用 **Custom Search API**。
2. 到 <https://programmablesearchengine.google.com/> 建搜尋引擎，開「**搜尋整個網路**」與「**圖片搜尋**」，複製搜尋引擎 ID（cx）。
3. 填進 `.env`：

```
GOOGLE_CSE_API_KEY=...
GOOGLE_CSE_ID=...
```

改完要 `.\stop.ps1` 再 `.\start.ps1`（`.env` 在啟動時載入）。

**用法**：

```bash
python backend/manage.py fetch_google_photos --dry-run     # 先看會抓什麼、用掉幾次查詢
python backend/manage.py fetch_google_photos               # 只補沒照片的
python backend/manage.py fetch_google_photos --target cards --category arm
python backend/manage.py fetch_google_photos --equipment aoi --limit 20
python backend/manage.py fetch_google_photos --code MEC-01 --force
python backend/manage.py fetch_google_photos --rights cc_publicdomain,cc_attribute
```

**免費層每天只有 100 次查詢**，一筆一次。全部 360 筆（175 元件 + 185 知識卡）要分四天，
或用 `--limit` / `--target` / `--category` 分批。配額用完會停下來並保留已抓到的，隔天接著跑即可。

**存檔位置與檔名**（前端就是照這個路徑讀，不要自己改）：

| 對象 | 路徑 |
|---|---|
| 設備元件 `Component` | `media/components/<設備 slug>/<元件 slug>.<ext>` |
| 元件知識卡 `KnowledgeCard` | `media/knowledge/<料號>.<ext>`（例 `knowledge/MEC-01.jpg`） |

副檔名依實際解碼出來的格式決定（jpg／png／webp），不是照網址猜的。

**搜尋關鍵字**在 `backend/catalog/seed/image_queries.json`，抓到的圖不對就改那裡再 `--force` 重抓；
也可以用 `--queries 自己的檔.json` 指向覆寫檔。

**分四天抓完**（免費層每天 100 次查詢，一筆一次；用 95 留點餘裕）：

| 天 | 指令 | 抓什麼 |
|---|---|---|
| 第 1 天 | `... fetch_google_photos --target cards --limit 95` | 知識卡 95 / 185 |
| 第 2 天 | `... fetch_google_photos --target cards --limit 95` | 知識卡剩下 90 |
| 第 3 天 | `... fetch_google_photos --target components --limit 95` | 設備元件 95 / 175 |
| 第 4 天 | `... fetch_google_photos --target components --limit 95` | 設備元件剩下 80 |

**不加 `--force` 就只會抓還沒有照片的**，所以每天跑同一行就會自動接續，不會重覆也不會漏。
配額中途用完也一樣，隔天接著跑即可。

**檢查抓得對不對**：

```bash
python backend/manage.py photo_report            # 產生 Docs/photo-report.html 縮圖對照表
python backend/manage.py photo_report --missing  # 只列還沒有照片的
```

用瀏覽器開，紅框是還沒有照片的。看到抓錯的就改 `image_queries.json` 的關鍵字，再
`fetch_google_photos --code MEC-01 --force`（或 `--slug <元件 slug>`）單獨重抓。

**品質把關**：每筆取 5 個候選依序嘗試，會擋掉非圖片、壞檔、短邊 < 200px 與 > 8MB 的檔案，
第一個能通過的才存檔。

> **版權**：Google 圖片搜到的多半是有版權的第三方圖片。指令會把來源網站與來源頁寫進
> `photo_credit` / `photo_source_url`，前端也會顯示，方便日後追溯或撤換。
> 內部教育訓練通常風險較低，對外發布請先確認授權，或加 `--rights` 只抓標示可自由使用的圖。

### 手動匯入（不需要任何金鑰）

挑好的圖直接丟資料夾，用檔名決定掛到哪裡：

```bash
python backend/manage.py import_photos D:\photos --dry-run   # 先看對應關係
python backend/manage.py import_photos D:\photos --credit "翻攝自原廠型錄"
```

| 檔名 | 掛到 |
|---|---|
| `MEC-01.jpg` | 元件知識卡 MEC-01 |
| `aoi/belt-conveyor.jpg` | AOI 設備的 belt-conveyor 元件（子資料夾＝設備 slug） |
| `aoi__belt-conveyor.jpg` | 同上，用雙底線分隔 |
| `frl.jpg` | 所有設備裡 slug 為 frl 的元件 |

會驗證檔案真的是圖片、副檔名依實際格式決定，對不到的檔名會列出來而不是默默跳過。
搭配 `Docs/photo-candidates.html` 的原廠連結挑圖，是目前最務實的做法。

### 來源三：公司自行拍攝

1. 把照片放到 `backend/media/components/<設備 slug>/<元件 slug>.jpg`（也支援 png / webp）
   - 設備 slug：`fuel-cell`、`aoi`、`transfer`、`robot-cell`
   - 元件 slug 見對應的 `backend/catalog/seed/*.json`
2. 重新執行 `python manage.py load_seed`，會自動掛上照片
3. 或直接到 `/admin` → Components 逐一上傳，並填寫 `photo_credit`（拍攝者／來源）

> 三種來源可以混用：Commons 抓得準的直接用，抓不準的改用 Google 圖片，關鍵元件最好還是自己拍。
> 種子資料中的品牌與型號為「範例」，請依實際 BOM 修改。

## 互動方式

- 設備頁：滑鼠移到 3D 零件上高亮並顯示名稱；點擊任何零件（不限目前分頁）會自動切到該元件所屬的領域分頁、捲到分頁頂顯示詳細資訊，並把清單中的該列捲入視野。
- 元件字典：依機構／電控／軟體／水氣電分頁，再用類別 pill 與關鍵字過濾。

## 教育訓練平台（LMS）

除了設備 3D 之外，平台另有一套依 `Automation_Training_Hub_PRD.md` 建的學習系統（`backend/training/`），
教材內容來自 `Docs/automation-training.html`：

| 功能 | 路徑 | 內容 |
|---|---|---|
| 學習地圖 | `/learn` | 3 個 Level、9 個章節；**修完一級的全部章節才解鎖下一級** |
| 章節 | `/learn/<課程>/<章節>` | Markdown 教材 + 本章元件卡 + 標記完成；部分章節可跳到對應設備的 3D 頁 |
| 全站搜尋 | `/search` | 一次搜元件知識卡、設備元件、課程章節、技術文檔與實戰題目；**錯誤碼可直接搜**（如 `0x001B`、`-1073807339`） |
| 元件知識卡 | `/knowledge` | 185 張元件知識卡（功用／安裝位置／現場重點），依 8 個系統分類 + 全文搜尋 |
| 技術文檔 | `/docs` | 11 篇技術文檔（通訊協定、運動控制、視覺、除錯與錯誤碼速查），依分類與標籤篩選 |
| 來料辨識 | `/identify` | 12 組「看到這個外觀 → 怎麼分辨 → 要核對什麼 → 常見收錯」 |
| 隨堂測驗 | `/quiz` | 15 題單選，**由後端判題**（前端拿不到答案），登入後留作答紀錄 |
| 實戰演練 | `/projects` | Mini Project 規格與驗收標準、提交 repo；導師在同一頁批改與評分 |
| 個人中心 | `/me` | 登入／註冊、章節完成度與測驗統計 |

### 角色

`training.Profile.role` 分三級，註冊一律開為**學員**，導師與管理員請在 `/admin` → Profiles 調整：

- **學員**：瀏覽全部教材、作答、提交專案，只看得到自己的提交紀錄。
- **導師**：另可在 `/projects` 批改所有人的提交、給分與評語；在 `/admin` 上架課程與撰寫技術文檔。
- **管理員**：同導師，另負責帳號與權限。

### 知識卡與實機元件的關係

`catalog.Component` 是「某台設備的某顆料」（綁 Equipment/Module，有 3D 座標與 mesh）；
`training.KnowledgeCard` 是「這類元件的通用知識」（跨設備）。兩者用 M2M 連結，
對照表在 `backend/training/management/commands/load_training_seed.py` 的 `LINKS`（目前對到 137/175 個元件）。

### 匯入教材

```bash
python backend/manage.py load_training_seed          # 以 code / slug upsert，可重複執行
python backend/manage.py load_training_seed --relink # 只重建知識卡與元件的關聯
```

種子在 `backend/training/seed/`（knowledge_cards / identification / quiz / courses / projects）。
要改教材文字直接編 JSON 再跑一次即可；`load_seed`（設備元件）與 `load_training_seed`（教材）互不影響。

### 驗證

```bash
python backend/manage.py test training   # 解鎖規則、判題不外洩答案、角色權限、CSRF
```

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
