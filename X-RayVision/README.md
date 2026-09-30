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
- 檢測紀錄快速檢視與配方調整重新分析：[docs/review-and-recipe-iteration-plan.md](docs/review-and-recipe-iteration-plan.md)（PLAN-003）
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

開發時可用腳本在背景啟動與停止（預設資料目錄 `temp\dev-data`、連接埠 8600，記錄在 `temp\dev-service\`）：

```
scripts\start.cmd [-Data D:\XRV] [-Port 8600] [-NoWatch] [-SkipLicense]   背景啟動，等到網頁回應
scripts\status.cmd                                         查詢狀態
scripts\stop.cmd                                           正常關閉；30 秒未結束才強制結束
```

`start.cmd` 啟動前會執行 `scripts\dev_license.py`：資料目錄沒有有效授權（或剩不到 30 天）時，以開發用私鑰 `tools\keys\license_private_DEV.pem` 簽發 10 年授權並匯入，開發時不需手動啟用。產品程式的授權檢查不變；`-SkipLicense` 可略過，用來測試未授權畫面。直接執行 `python -m xrayvision serve` 時可另外執行 `python scripts\dev_license.py <資料目錄>`。產品公鑰換成正式金鑰後，開發私鑰簽的授權會驗證失敗，屆時需另行處理。

安裝版以 Windows 服務執行，改用安裝目錄 `service\` 內的 `start-service.cmd`、`stop-service.cmd`、`restart-service.cmd`、`service-status.cmd`（開始功能表也有捷徑；需要系統管理員權限，會自動要求提升）。

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
| 外部模組套件 | 離線安裝流程（簽章、網頁上傳）未提供；目前隨更新檔的執行環境交付 |
| 檢測區域 | 固定影像座標，不隨樣品位置自動對位；位置差異大的影像可在檢閱頁改用本影像自訂檢測區域（PLAN-004） |
| validate-module | 成像條件不變性與重拍重複性仍以 `validate` 指令另外驗證 |
| 操作手冊 | 只有繁體中文版 |
| 配方編輯器 | 手動修改網址從某配方直接跳到新配方時，畫面不會重新載入（一般操作不會發生） |
| 輪廓高度敏感度 | 舊版批次工具的 `--sweep` 敏感度表已隨舊版工具移除；可在配方編輯器以不同 `bump_level`／`pad_level` 試跑比較，或各跑一次 `analyze` |
| 紀錄預覽 | 預覽先載入 1024 px 縮圖，高解析度需按「載入高解析度」；檢閱頁的上一張／下一張只在紀錄頁同一頁（50 筆）內切換 |
| 試跑與手動檢測 | 共用一個互動分析子行程，多人同時使用時依序處理；結果不寫入正式紀錄（手動檢測工作區 7 天未用清除） |

## E. 建議檢討議題

1. ~~空洞檢測預設方法~~ → 2026-09-30 決議：新增配方範本預設用模型（PLAN-005）；取得實際影像後仍需驗證
2. 空洞與焊墊重疊時擴大估計誤差的取捨（安全性 vs. 需複判數量）。
3. 取得空洞影像後的驗證與重新訓練排程。
4. 實機驗證（安裝、服務、設備電腦）的時程與環境。
5. 正式金鑰、程式碼簽章憑證與產品名稱。
6. ~~後續檢測項目的優先順序~~ → 2026-09-30 決議：先不新增，等客戶資料與現場驗證。檢測區域自動對位也先觀察現場（手動以本影像自訂檢測區域處理）。
