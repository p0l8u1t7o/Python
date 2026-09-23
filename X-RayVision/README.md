# X-RayVision：X 光半導體檢測影像分析平台

產線用 X 光影像分析平台。平台提供影像校正、成像品質、配方、判定、報告等共用能力，檢測項目以「檢測模組」掛載擴充。目前的模組：微凸塊對位（Micro Bump Alignment）、空洞檢測（Void Inspection，尚未以實際影像驗證）。

- 產品規劃書：[docs/product-plan.md](docs/product-plan.md)
- 檢測模組介面規格：[docs/inspection-module-interface.md](docs/inspection-module-interface.md)
- 微凸塊對位檢測流程：[docs/bump-pad-detection-flow.md](docs/bump-pad-detection-flow.md)
- 成像條件管理與不變性驗證：[docs/imaging-conditions.md](docs/imaging-conditions.md)
- 服務與資料（資料庫、佇列、監看、判定、問題回報包、API）：[docs/service-and-data.md](docs/service-and-data.md)
- 使用者介面：[docs/user-interface.md](docs/user-interface.md)
- 產線化（帳號權限、授權、更新退版、安裝部署、發行建置）：[docs/production-deployment.md](docs/production-deployment.md)
- 操作手冊：[docs/operation-manual.md](docs/operation-manual.md)
- 第 5 階段規劃（檢測擴充）：[docs/phase5-plan.md](docs/phase5-plan.md)
- 空洞檢測模組與模組驗證狀態：[docs/void-inspection.md](docs/void-inspection.md)
- 深度學習推論、模型管理、標註與模組驗證：[docs/deep-learning-and-annotation.md](docs/deep-learning-and-annotation.md)
- 檢測模組開發指南：[docs/module-development-guide.md](docs/module-development-guide.md)（範例模組 `examples/module_template/`）
- **待辦事項**：本文件最後的「待辦與待檢討事項」

## 服務

```
python -m xrayvision recipe-import recipes/bump_alignment_default.json --data D:\XRV --release
python -m xrayvision serve --data D:\XRV            http://127.0.0.1:8600 ；API 文件 /api/docs
python -m xrayvision reset-password <帳號> --data D:\XRV    本機重設為一次性密碼
```

首次開啟網頁會要求建立系統管理員帳號。以 `serve` 直接執行時會檢查軟體授權；開發測試可用 `tools/license_admin/license_admin.py` 以開發用金鑰簽發授權檔。

## 前端

```
cd web
npm install
npm run dev          開發伺服器（/api 轉送到 8600）
npm run typecheck
npm run build        輸出 web/dist，由後端提供
```

## 發行建置（原廠端）

```
python tools/release/build_release.py --update-key tools/keys/update_private_DEV.pem
```

產出 `build/release/<版本>/`：安裝目錄樹、`X-RayVision-<版本>-setup.exe`、`X-RayVision-<版本>.xrvupd`、`build-info.json`。需要 Node.js 與 Inno Setup 6。建置過程會以安裝目錄樹實際啟動服務並執行自我檢查。正式發行前必須更換開發用金鑰並做程式碼簽章，詳見 [docs/production-deployment.md](docs/production-deployment.md) 第 6 節。

## 開發環境

```
python -m venv .venv
.venv\Scripts\pip install -r tools\release\runtime-requirements.txt pytest httpx
```

從專案根目錄執行即可，不需安裝本套件。請勿使用 `pip install -e .`：可編輯安裝會蓋過 `PYTHONPATH`，使端到端進版測試載入錯誤的版本。

## 命令列

```
python -m xrayvision modules                                   列出檢測模組與參數
python -m xrayvision recipe-template bump_alignment            產生預設配方
python -m xrayvision analyze image/Batch2 --recipe recipes/bump_alignment_default.json --out temp/out
python -m xrayvision validate image/Batch2/1.tiff image/Batch2/2.tiff --recipe recipes/bump_alignment_default.json --out temp/val
python -m xrayvision calib-create --id kv90 --flat flat/ --dark dark/ --conditions "kv=90"
python -m tests.synthetic_void temp/void_synth                  產生空洞合成影像範例
python -m xrayvision validate-module void --dataset <資料集.zip> --recipe <配方.json> --out <資料夾> [--model 參照=<.xrvmodel>]
python tools/model_training/make_synthetic_dataset.py --out build/validation/synthetic_void.zip   合成驗證資料集
python tools/model_training/train_void.py --key tools/keys/update_private_DEV.pem [--dataset <匯出的訓練資料.zip>]   訓練空洞模型 (需 PyTorch)
```

`analyze` 對每張影像輸出 `<名稱>.result.json`（完整分析結果，含影像雜湊值、配方、軟體與模組版本、成像品質、拍攝參數、校正設定檔）與 `<名稱>.overlay.jpg`，並輸出 `summary.csv`（每張的結果與成像品質）與 `quality.csv`（每項品質指標與判定）。`validate` 對同一視野、不同拍攝條件的影像產生量測不變性驗證報告。分析行程以較低優先權執行，預設使用一半的處理器核心，避免影響設備操作。

## 測試

```
python -m pytest                          單元測試、合成影像測試、回歸影像集、端到端進版測試
python -m pytest -m "not slow"            略過端到端進版測試（約 3 分鐘）
python -m tests.regression.regress        只跑回歸影像集並列出差異
python -m tests.regression.regress --update   更新基準（演算法有意變更並經審閱後才執行）
```

## 專案結構

```
xrayvision/core/          平台核心：影像載入、吸收量轉換、幾何、模組介面、分析流程、疊圖
xrayvision/inspections/   檢測模組（bump_alignment、void）
xrayvision/service/       平台服務：API、帳號、授權、更新、資料保留、佇列、配方、問題回報包
xrayvision/store/         資料庫與影像封存
xrayvision/ingest/        資料夾監看
xrayvision/i18n/          語系檔（zh-TW、en）
web/                      React＋TypeScript 前端
launcher/                 啟動器（Windows 服務主程式，負責進版與退版）
installer/                安裝程式腳本（Inno Setup）
tools/                    原廠端工具：發行建置、更新檔、授權簽發、問題回報包重現、模型訓練與驗證資料集
examples/module_template/ 外部檢測模組範例 (亮點計數)
recipes/                  配方
tests/                    測試與回歸基準
docs/                     規劃書、規格與操作手冊
```

---

# 待辦與待檢討事項（2026-09-23 整理，第 0～5 階段開發完成後一起檢討）

第 0～5 階段（平台、成像條件、服務與資料、介面、產線化、檢測擴充 5a～5e）的程式都已完成，
`python -m pytest` 全部通過。以下為尚未完成、尚未驗證或需要決定的事項。

## A. 需要客戶或現場提供

| 編號 | 事項 | 影響 |
|---|---|---|
| Q1 | 設備能否匯出拍攝參數、格式 | 拍攝參數追溯 |
| Q2 | 參數掃描影像、空拍與暗場影像、標準樣品 | 品質門檻校正、平場校正、不變性驗證 |
| Q3 | 凸塊、焊墊、焊球的設計直徑、pitch、像素尺寸 | µm 換算、配方預設半徑範圍 |
| Q4 | 晶片偏移規格上限（µm） | 微凸塊對位判定 |
| Q13 | 授權申請檔與授權檔的交付窗口 | 原廠端作業流程 |
| Q16 | 設備輸出影像的檔名與資料夾命名規則 | 資料夾監看批號解析 |
| Q17 | **含空洞的實際影像**（每種焊點 20 張以上，含同一視野不同功率） | 空洞模組驗證與核准、以實際資料重新訓練模型 |
| Q18 | 焊點種類與設計直徑（BGA、C4、微凸塊） | 空洞配方預設半徑範圍 |
| Q19 | 客戶採用的空洞判定標準 | 預設判定規格（目前單顆 25%） |
| Q20 | 空洞檢測是否與微凸塊對位放在同一配方 | 配方範本 |

## B. 尚未實機驗證

- setup.exe 實際安裝、Windows 服務註冊與開機啟動、解除安裝（需系統管理員權限；建議乾淨的 Windows 10 虛擬機）。
- 以服務身分執行時，停止服務是否能以 CTRL_BREAK 正常關閉平台服務（無效時 30 秒後結束行程樹）。
- 設備電腦實機：防毒軟體、與設備原廠軟體並行、5120×2160 螢幕、GPU（DirectML）推論與 3D 重建並行。
- 空洞模組（規則式與模型）在實際影像上的準確度：目前只以合成影像驗收，模組維持「未驗證」。

## C. 正式發行前必須處理

- 更換開發用金鑰：授權、更新（模型檔也用它簽章）、問題回報包；示範模型需以正式金鑰重新簽章或重新訓練。
- 取得程式碼簽章憑證，簽署 setup.exe、解除安裝程式與服務包裝程式。
- 產品正式名稱（目前為工作名稱 X-RayVision，集中於語系檔與安裝腳本）。
- 各品質門檻（空洞、微凸塊對位）以現場參數掃描影像校正。

## D. 已知限制與未做的功能

| 項目 | 說明 |
|---|---|
| 空洞蓋住焊墊（規則式） | 焊墊抵消空洞深度，屬量測極限；以擴大估計誤差轉需複判。模型在合成資料上可處理，需實際影像確認 |
| 複合結構誤報 | 以複合凸塊為主的影像與 8-bit 影像有少量空洞誤報；以配方半徑範圍與檢測區域排除 |
| 模型訓練資料 | 示範模型只以合成影像訓練，結果偏樂觀；需以實際標註資料重新訓練與驗證 |
| 標註工具 | 只有多邊形，規劃中的筆刷工具未做 |
| 外部模組套件 | 離線安裝流程（簽章、網頁上傳）未提供；目前隨更新檔的執行環境交付 |
| 檢測區域 | 固定影像座標，不隨樣品位置自動對位 |
| 疊圖 | 焊點圓未依判定著色（超規焊點以判定原因與排行表呈現） |
| validate-module | 成像條件不變性與重拍重複性仍以 `validate` 指令另外驗證 |
| 操作手冊 | 只有繁體中文版 |
| 配方編輯器 | 手動修改網址從某配方直接跳到新配方時，畫面不會重新載入（一般操作不會發生） |
| 舊版工具 | `BumpPadShift.py`、`FlipChipShift.py`、`app.py` 仍保留供對照，平台報告已涵蓋後可移除 |

## E. 建議檢討議題

1. 空洞檢測預設用「規則式」、「模型」或「兩者並用」？（合成資料上模型較準，但缺實際驗證）
2. 空洞與焊墊重疊時擴大估計誤差的取捨（安全性 vs. 需複判數量）。
3. 取得空洞影像後的驗證與重新訓練排程。
4. 實機驗證（安裝、服務、設備電腦）的時程與環境。
5. 正式金鑰、程式碼簽章憑證與產品名稱。
6. 後續檢測項目（裂紋、橋接、缺球）的優先順序。

---

# 工程工具（舊版）

以下為平台化之前的工程工具，保留供對照，正式產品不採用。

## X-Ray_Flip-Chip：Flip-Chip X 光互動標註工具

以同目錄 `FlipChipShift.py` 的演算法為核心的網頁工具：

1. 匯入 X 光影像，量測後把「晶片矩形 / 金屬凸塊圓 / 基板焊點圓」疊在影像上。
2. 用框選或套索圈選物件，重新指定類別（晶片、金屬凸塊、基板焊點、忽略），
   也能手動新增漏檢或刪除誤檢；標註存在 `data/labels/`。
3. 匯出「演算法結果 + 人工分類 + 差異清單」的 Markdown 與 JSON，直接貼給語言模型討論優化。
4. 品質篩選與整體位移估計：同一片晶片的凸塊大小應一致、凸塊應落在焊點內，
   據此篩掉辨識不佳的圓（疊圖淡灰），再對每個主要晶片矩形穩健估計
   「晶片要位移多少才會和焊點重合」（右側「整體位移估計」面板與畫布上的黃色箭頭）。

## 啟動

```
cd X-Ray_Flip-Chip
pip install -r requirements.txt
python app.py --port 8002
```

瀏覽器開 `http://127.0.0.1:8002/`。依賴見 `requirements.txt`（Flask、OpenCV、NumPy）。

## 操作

| 動作 | 方式 |
|---|---|
| 匯入 | 左側選檔（或拖放到畫布），可設尺寸倍率（`--scale`）、偏移門檻、µm/px（填了就多算 µm） |
| 縮放 / 平移 | 滾輪縮放、雙擊置中；平移工具 (H)、空白鍵或中鍵拖拉 |
| ROI | 工具 R，拖拉畫出矩形，按「分析 ROI」只對該區域運算（偵測、晶片矩形、量測都只在 ROI 內）；「分析整張」回到全圖；ROI 結果另存一筆，歷史清單會標示 |
| 框選 | 工具 V，拖拉矩形；點一下選單一物件；Shift 加選 |
| 套索 | 工具 L，逐點點出多邊形，雙擊或 Enter 結束 |
| 重新分類 | 選好後按 1 晶片 / 2 金屬凸塊 / 3 基板焊點 / 0 忽略 |
| 新增 | 工具 A，先選類別再拖拉（晶片畫矩形，其餘畫圓） |
| 刪除 / 復原 | Delete、Ctrl+Z |
| 儲存 | 右側「儲存標註」（改動後也會自動存） |
| 匯出 | 右側「產生匯出內容」→ 下載 .md / .json 或複製 Markdown |

## 資料夾

```
data/uploads/   原始上傳檔
data/display/   顯示用 JPEG（去噪版與原圖版）
data/results/   演算法結果 JSON（重新開啟不用再算）
data/labels/    人工標註 JSON
```

## 位點量測模式（雙瓣模型）

X 光下焊點通常比凸塊大一圈，兩者錯開時外形呈「暗圓＋淡瓣」。程式先用暗圓等高線擬合凸塊圓，
再從凸塊心出發取聯集（暗圓∪淡瓣）等高線最外側的跨越點，只用離凸塊圓外緣 > 5.5 px 的「露出弧」擬合焊點圓：
弧夠長（≥150°）時自由擬合含半徑，否則用同一矩形內自由擬合的中位半徑固定半徑只解圓心。
瓣區必須真的比背景暗、弧殘差要小，否則退回舊的同心兩層或單圓。CSV／JSON 的 `mode` 欄：
`lobe`（雙瓣）、`concentric`（同心兩層）、`single`（分不出）。暗圓＝凸塊、淡瓣＝焊點的假設可由 `dark_is_bump` 對調。

## 整體位移估計怎麼算

1. 品質篩選（`FlipChipShift.quality_filter`）：凸塊圓存在、不貼影像邊、內圓擬合可靠、
   凸塊半徑與同矩形中位數差 ≤ 12%（面積約 ±25%）、焊點半徑差 ≤ 15%、深度 ≥ 中位數 × 0.5、
   凸塊落在焊點內。被篩掉的位點在 CSV／JSON 有 `reject_reason`。
2. 穩健估計（`estimate_shift`）：以偏移向量的中位數起始取內點，再對內點擬合「平移＋旋轉＋縮放」的相似變換
   （錐形束放大率差會讓偏移隨位置線性變化，縮放項吸收它），以變換殘差重選內點；
   回報變換在晶片中心處的偏移向量、旋轉、縮放 ppm 與邊角差、內點比、標準誤、信心。
3. 主要晶片矩形：在巢狀矩形鏈裡挑邊界對比最高、且有足夠可用位點的那一層（★）。
   `correction = −(凸塊心 − 焊點心)` 即晶片需位移量。
4. 前處理敏感度：同一批候選位點另外用三種去噪（高斯 σ1.5、雙邊、Non-Local Means）重量，
   四個估計的半幅當系統不確定度，與統計標準誤合併成「合併不確定度」。
   這是量測目前最大的誤差來源，數字比 ±se 更能代表實際可信範圍。

## 圓尺寸表

右側「圓尺寸表 (px)」列出每個圓（焊點 P#、凸塊 B#）的圓心、半徑、直徑、面積，
可依類別／採用與否篩選、搜尋編號或矩形、點列跳到該圓，並可下載 `circles.csv`；
上方另有每個矩形的直徑統計。CLI 同樣輸出 `<name>_circles.csv`，`--print-sizes` 會在終端印全表。

## 物件編號規則

`D#` 晶片矩形、`P#` 第 # 個位點的基板焊點圓、`B#` 同位點的金屬凸塊圓，人工新增的為 `U#`。
匯出 JSON 每個物件都有 `alg_class`（演算法）、`user_class`（人工）、`final_class`，以及量測欄位。

## 批次量測 CLI：`BumpPadShift.py`（支援 16-bit 原始影像）

獨立於網頁工具的批次量測程式，同時處理 16-bit 原始影像（如 `image/Batch2/*.tiff`）
與檢視軟體轉存的 8-bit RGB 影像（如 `image/Batch1/*.tif`）。

```
python BumpPadShift.py image/Batch1 image/Batch2 --out temp/output --sweep
```

| 參數 | 說明 |
|---|---|
| `--out` | 輸出資料夾；每個輸入資料夾各一個子資料夾 |
| `--workers` | 平行處理的行程數（預設 min(8, CPU)） |
| `--bump-level` / `--pad-level` | 凸塊／pad 等高線（背景 0 → 核心 1），預設 0.75 / 0.25 |
| `--lobe auto\|on\|off` | pad 露出弧模式；auto 只用在 8-bit RGB 影像 |
| `--sweep` | 另以 0.70/0.30、0.80/0.20 重算，報告列出等高線敏感度 |
| `--px-um` | 每像素微米，給了就多列 µm |

輸出：`<name>_overlay.jpg`（紅＝凸塊、綠＝pad、黃線＝偏移 ×10、陣列框與大箭頭 ×40）、
`<name>_sites.csv`、`<name>_arrays.csv`、`summary.csv`、`report.md`
（含同視野重拍影像的逐點重複性比較）。

做法重點：

1. 16-bit 影像取 −ln(I) 成吸收量（重疊材料可相加），8-bit 影像中值＋高斯去噪後以 (255−I)/255 近似。
2. LoG 尺度空間偵測圓盤；凸塊半徑 R0 取主峰，半徑 ≥ 1.8·R0 的是大球（BGA 等），連同疊在上面的凸塊一起排除。
3. 每顆凸塊先擬合「二次背景＋模糊圓盤（含圓頂）」模型，精修圓心並扣除背景，正規化成背景 0～核心 1。
4. 放射線取 0.75 等高線 → 凸塊圓（穩健修剪）；0.25 等高線是凸塊 ∪ pad 的外緣 → pad 圓。
   只剔除窄的離群段（< 40°，走線／via 接點），較寬的離群弧是 pad 略微露出，保留下來。
   8-bit 影像另有露出弧模式：低等高線明顯超出凸塊圓的連續寬弧（≥ 50°）是 pad 露出（暗圓＋淡瓣），只用這段弧擬合 pad。
5. 位點依 pitch 連結成陣列；每個陣列與整張各做 pad→凸塊 的相似變換穩健估計，
   報變換在陣列中心處的平移（shift＝凸塊−pad；修正量＝−shift）、旋轉、縮放 ppm 與標準誤。

已知限制：16-bit 影像上每顆凸塊旁的淡色淚滴（約 1.5·R0 處、方向有上有下）是基板走線／via，不是 pad。
pad 大致藏在凸塊正下方，偏移量只能從外緣的不對稱量出來，絕對值會隨等高線選擇變化約 ±0.2 px（見報告的敏感度表）。
