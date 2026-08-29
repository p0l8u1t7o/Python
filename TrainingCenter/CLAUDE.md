# TrainingCenter

自動化設備教育訓練平台：設備 → 模組（機構／電控／軟體）→ 元件，含 3D 檢視與動畫。使用說明見 README.md。

## 語言與慣例
- 對話與文件使用繁體中文；程式碼、識別字與技術術語保持英文。
- 種子資料與 UI 文案一律繁中；品牌／型號標示「範例：」代表尚未對照實際 BOM。
- 領域固定四個：mechanical／electrical／software／utility（水氣電）；機器視覺相關模組歸 software。
- 改 seed 的流程：`update_v2.py`（結構性調整）→ `add_photo_queries.py`（照片關鍵字）→ `load_seed` → `fetch_photos`。

## 開發環境
- Python 3.12 於 `.venv/`；一律用 `.venv/Scripts/python.exe`（Git Bash：`./.venv/Scripts/python.exe`）。
- 安裝 Python 套件後更新 `requirements.txt`（`pip freeze`）。
- 前端在 `frontend/`，Node 24；`npm run dev` 走 Vite proxy 到 Django 8001。
- 啟停：`.\start.ps1`（背景；`-Attach` 前景 Ctrl+C 即停）/ `.\stop.ps1`（taskkill /T 砍程序樹＋釋放埠）；Web 5174、API 8001。Django 以 `--noreload` 啟動，改後端要重啟。
- CAD Studio（`backend/cadstudio/`）：AI 產碼預設 Gemini（OpenAI 相容端點，`openai` SDK），可切 openai_compat／claude，建置走 `runner.py` 呼叫 skill 工具；金鑰與設定放專案根目錄 `.env`（settings.py 與 start.ps1 都會載入，已 gitignore）。
- 元件照片：`manage.py fetch_photos` 從 Wikimedia Commons 依 seed 的 `photo_query` 抓（`|` 分隔備用關鍵字）。

## 驗證清單（改完必做）
- 後端：`python backend/manage.py check`、改 seed 後 `load_seed`（可重複執行，以 slug 為鍵 upsert）。
- 前端：`cd frontend && npx tsc -p tsconfig.app.json --noEmit && npx vite build`。
- 3D／版面改動：啟動兩個 server 後用 Playwright 截圖確認（scratchpad 內裝 playwright，Chromium 已在 ~/AppData/Local/ms-playwright）。

## 3D（text-to-cad CAD 為主）
- 整機與元件 3D 來自 `cad/`：`lib/parts.py`（零件 builder）、`lib/robot.py`、`lib/layout.py`（座標轉換與動畫基準點）、`models/*.step.py`（整機組裝）。建置：`PYTHONUTF8=1 cad/.venv/Scripts/python.exe cad/build_all.py`。
- 整機 glb 節點名稱必須等於 seed `mesh_name`（`asm.add(shape, name)` 的 name 會覆寫標籤，同名可重複）；改完用 build_all 後檢查「missing mesh_names」為空。
- 可動節點：`sub_compound(name, geometry + anim_datums(kind, pivot_m, axis_dir))`；前端 `GltfScene.tsx` 讀 `_pivot`／`_axis`／`_anim_<kind>`。
- cadgen 的 `add_module(...).location` 不會匯出；幾何用 `place()` 烘成絕對座標。
- `comp()` 會遞迴攤平巢狀清單；`export_gltf` 要 `unit=Unit.MM`。

## 3D 程序化模型慣例（備援場景）
- 共用零件在 `frontend/src/three/Parts.tsx`：`RobotArm`（關節殼＋膠囊連桿重疊，轉動不露空隙）、`BeltConveyor`／`RollerConveyor`（含頭尾滾輪、側框、`Frame` 機架）、`Cylinder`、`Fan`、`Cabinet`。
- 同一元件的多個 mesh 共用 `name`；`Static`／`StaticCyl` 是裝飾，不可點選。
- 元件 3D CAD：用 earthtojake/text-to-cad skill 寫 build123d 生成器（`cad/models/*.step.py`）→ `cadgen` gen/export glb → `manage.py attach_model` 掛到 `Component.model_file` → 詳細面板 `ModelViewer`。流程與坑見 README「Text-to-CAD」。
- cadgen 在 Windows 要 `PYTHONUTF8=1`；build123d 布林刀具一次傳單一清單；`(Pos * Cylinder).rotate` 要加括號；每次看 `inspect refs --facts` 的 faceCount 確認孔真的切到。

## 踩過的坑
- Siemens iX v5 主題不是 class，而是 `<html data-ix-theme="classic" data-ix-color-schema="dark">`；沒設會是白底、卡片無背景。
- iX v5 React 屬性：`IxTabs` 用 `activeTabKey` + `onTabChange`（`IxTabItem` 需 `tabKey`），沒有 `selected`；`IxButton` 沒有 `size`，變體用 `subtle-secondary`；`IxIconButton` 的 `size` 是 `"12"|"16"|"24"`。
- `IxTabs` 在程式改 `activeTabKey` 時也會發 `tabChange`，handler 不要在裡面做「使用者切頁」才該做的事（如清除選取），否則 3D 點選跨分頁時會被自己清掉。
- `@siemens/ix-icons` 沒有 `iconRobot`，用 `iconRoboticArm`／`iconRoboticGripper`。
- drei 的 `Environment` preset 會從外部 CDN 抓 HDR，離線／內網會失敗；改用 `<Environment><Lightformer/></Environment>` 程序化環境光（無網路需求）。
- drei `SoftShadows` 與 three r185 的 shader 不相容（Fragment shader 編譯失敗、畫面全黑），不要用。
- 滾筒要各自轉動：cylinder 幾何軸是 Y，已 `rotation.x=PI/2` 後要動 `rotation.y`（動 z 會整排翻滾）。
- 場景中沒有 mesh 的元件由 `Viewer.tsx` 的 `AutoParts` 依 `pos` 自動補實體；新增元件只要給 `pos` 與唯一 `mesh_name` 即可，不一定要改場景。
- 3D 場景中同一元件的多個 mesh 可共用同一個 `name`，高亮與點選都靠 `SceneCtx` 比對 `mesh_name`。
- Git Bash 終端機印中文會亂碼，不影響實際輸出；Django 指令輸出含 ✓ 等符號在 cp950 會炸，執行時加 `PYTHONIOENCODING=utf-8` 或只用 ASCII。
- `upload.wikimedia.org` 對非瀏覽器 UA 一律 403（robot policy），下載縮圖要走 `commons.wikimedia.org/w/thumb.php?f=<檔名>&w=1024`。
- Commons 全文搜尋很模糊（"six axis industrial robot" 會回美洲獅）；`deepcategory` 又太深（Industrial robots → 環球影城城堡）。最穩的是 `incategory` 直接成員 + 提示詞排序，即 seed 的 `cat:分類 ~ 提示詞` 語法。
- Gemini：`gemini-2.5-pro` 已對新用戶停用（404），預設用別名 `gemini-pro-latest` 並在 404／429／5xx 時依 `GEMINI_FALLBACKS` 遞補；免費層 Pro 常 503，實際多半落到 flash 系列。
- CAD Studio 早期版本的模式切換讓使用者誤按「直接執行程式」而建置範本；現在是兩個明確按鈕（AI 產生／執行下方程式），不要再做隱性模式。
- `parts.col()` 同時接受 hex 字串與 build123d Color（AI 常傳 `srgb()` 物件）。`runner.HEADER` 對 `AssemblyHelper.add` 加了 `loc/location/position/rotation` 相容包裝與 `asm.root`；AI 模式失敗會自動修復最多 `MAX_REPAIR=2` 次。
- Commons 分類名稱要先用 `prop=categoryinfo` 確認存在（很多直覺名稱不存在，如 Safety relays、Light curtains）。
