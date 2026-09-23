# 深度學習推論、模型管理、標註與模組驗證　技術規格

| 項目 | 內容 |
|---|---|
| 文件編號 | SPEC-007 |
| 版本 | v1.0（第 5c～5e 階段） |
| 日期 | 2026-09-23 |
| 對應規劃書 | PLAN-002 第 5～7 節 |
| 相關文件 | 空洞檢測 [SPEC-006](void-inspection.md)、模組開發指南 [GUIDE-001](module-development-guide.md) |

---

## 1. 推論執行環境（5c）

| 項目 | 內容 |
|---|---|
| 執行環境 | ONNX Runtime 1.24（DirectML 版）：同一套件支援 CPU 與 Windows 上的 GPU（NVIDIA、AMD、Intel），不需安裝 CUDA；加入 `tools/release/runtime-requirements.txt`，安裝包增加約 25 MB |
| GPU | 系統設定 `gpu_inference`，預設關閉，由系統管理員於「系統管理 > 深度學習推論」啟用；GPU 無法使用或建立失敗時自動改用 CPU |
| 資源 | 推論在分析子行程中執行（低優先權）；每個子行程對同一模型只建立一次工作階段；執行緒數 1 |
| 程式 | `xrayvision/core/inference.py` |

## 2. 模型檔與模型管理（5c）

### 2.1 模型檔 `.xrvmodel`

ZIP：`model.json`（格式、產品、模型代碼、版本、適用模組、任務、輸入、輸出、訓練資料摘要、驗證指標、`model.onnx` 的 SHA-256）、`model.sig`（`model.json` 的 Ed25519 簽章，原廠更新簽章金鑰）、`model.onnx`。程式 `xrayvision/core/modelpkg.py`。

### 2.2 管理

| 項目 | 內容 |
|---|---|
| 資料 | 資料庫結構版本 4 `models`；檔案存於 `<資料目錄>/models/<模型代碼>/<版本>/` |
| 匯入 | 「配方管理 > 深度學習模型」（工程師以上）；驗證簽章、格式、雜湊、適用模組；同一版本不可重複匯入；記入稽核 `model.import`（失敗為 `model.rejected`） |
| 停用／啟用 | 停用後不能用於新發布的配方；已發布的配方仍可執行（避免產線中斷） |
| 配方參照 | 模組參數型別 `model`，值為「模型代碼@版本」；配方發布時檢查存在、啟用中、適用模組 |
| 分析 | 工作佇列把配方參照的模型路徑與 GPU 設定帶入子行程（`ctx.models`、`ctx.gpu`） |
| API | `GET /api/models`、`POST /api/models/import`、`POST /api/models/{id}/status` |

## 3. 空洞檢測的深度學習路徑（空洞模組 1.1.0）

| 參數 | 說明 |
|---|---|
| `method` | `rule`（規則式，預設）、`model`（模型）、`both`（兩者並用） |
| `model` | 模型參照 |

- 焊點位置與半徑沿用規則式擬合；模型只做每顆焊點的空洞分割。
- 前處理（`inspections/void/model_seg.py`，訓練腳本共用）：以焊點為中心裁切 2 × 1.4 R 視窗、縮放為 64 × 64；依焊點自身正規化（1.15～1.35 R 環帶中位數 = 0、0.5 R 內 90 百分位 = 1），不受曝光與功率影響。
- `model`：以模型結果為準；找不到模型時無法判定（原因「指定的深度學習模型無法使用」）。
- `both`：兩者都算，空洞率取較大者（保守）；差異超過 3 個百分點的焊點標示並列為需複判；找不到模型時退回規則式並需複判。
- 量測值另列 `void_pct_rule`、`void_pct_model`。

### 3.1 示範模型 `void_unet@1.0.0`

| 項目 | 內容 |
|---|---|
| 訓練 | `tools/model_training/train_void.py`（PyTorch，原廠端）；小型 U-Net（16/32/64 通道，約 460 KB）；合成影像 160 張、3210 個焊點裁切，焊墊有無、曝光 ×0.5～×2、吸收量 ×0.6～×1.5、焊球半徑 50～80 px、模糊 1～2.2 px 隨機；14 輪，CPU 約 4 分鐘 |
| 驗證（裁切層級） | Dice 0.976；空洞率平均誤差 0.23、95% 分位 0.79 個百分點 |
| 檔案 | `tests/data/void_unet-1.0.0.xrvmodel`（開發用金鑰簽章，供測試與示範） |

### 3.2 整體比較（合成影像 16 張，另一組亂數種子）

| 方法 | 空洞率誤差 95% 分位（焊墊未被遮住） | 含空洞蓋住焊墊 | 無空洞焊點誤報 | 6 MP、251 顆 |
|---|---|---|---|---|
| 規則式 | 1.34 | 2.40（最大 6.25） | 0／123 | 4.0 秒 |
| 模型 | 0.46 | 0.76（最大 1.19） | 0／123 | 4.7 秒 |
| 兩者並用 | 1.34 | 1.71（最大 2.46） | 0／123 | 5.0 秒 |

模型在「空洞蓋住焊墊」的情況也明顯優於規則式（規則式的量測極限，見 SPEC-006）。**注意：模型以同一套合成影像模型訓練與評估，結果偏樂觀；實際影像須重新驗證，必要時以實際標註資料重新訓練。**

## 4. 標註（5d）

| 項目 | 內容 |
|---|---|
| 畫面 | 檢測紀錄的檢閱畫面「標註」→ 標註頁（`/runs/:id/annotate`）：畫空洞（逐點點選，連按兩下或 Enter 完成）、選取後刪除、清除焊點空洞；滾輪縮放、拖曳平移；還原為模組結果 |
| 權限 | 新權限 `annotate`（工程師以上）；操作員可檢視 |
| 資料 | 資料庫結構版本 5 `annotations`（只新增，觸發器禁止修改）；以影像＋模組為單位，最新一筆為目前標註；內容為焊點 `[[x, y, r]]` 與空洞輪廓（影像座標）；不改變檢測紀錄的判定 |
| API | `GET/PUT /api/runs/{id}/annotation`、`POST /api/annotations/export`；稽核 `annotation.save`、`annotation.export` |

## 5. 訓練資料匯出（5d）

「檢測紀錄」勾選紀錄 →「匯出訓練資料」，只匯出已標註的影像，單一 ZIP：

| 內容 | 說明 |
|---|---|
| `crops/*.png` | 每顆焊點 64 × 64 裁切，16-bit，正規化吸收量範圍 −0.5～1.5 線性編碼 |
| `masks/*.png` | 空洞遮罩 |
| `dataset.json` | 格式 `xrv-void-dataset/1`、編碼方式、每筆的來源影像雜湊、檔名、批號、焊點、拍攝參數、標註者、空洞率 |
| 選用：`images/`＋`annotations.json` | 勾選「包含原始影像與整張標註」時附上，作為模組驗證資料集（`xrv-validation-set/1`） |

可去識別化（以代號取代檔名、批號、樣品編號、標註者）。原廠以 `train_void.py --dataset <ZIP>` 併入訓練。

## 6. 模組驗證工具（5e）

`python -m xrayvision validate-module <模組> --dataset <資料集> --recipe <配方> --out <資料夾> [--model 參照=檔案]`

- 平台流程：`xrayvision/core/module_validation.py`（讀資料集、逐張分析、比對、報告 JSON／HTML）。
- 模組宣告：`validation_metrics(pairs, spec)` 與 `validation_criteria`；空洞模組的指標與標準見 GUIDE-001 第 6 節。
- 合成驗證資料集：`tools/model_training/make_synthetic_dataset.py`。

示範結果（合成驗證資料集 10 張，含焊墊影像）：

| 方法 | 檢出率 | 誤報率 | 空洞率誤差 95% 分位 | 漏判 | 結果 |
|---|---|---|---|---|---|
| 規則式 | 97.6% | 0% | 2.53（未達 2.0） | 0 | 未通過（空洞蓋住焊墊的量測極限） |
| 模型 | 100% | 0% | 0.63 | 0 | 通過 |

## 7. 模組開發指南與範例（5e）

- [GUIDE-001 模組開發指南](module-development-guide.md)
- `examples/module_template/`：外部模組套件範例（亮點計數），含 entry point、`translations`、單元測試；測試納入主測試集。
- 平台新增：外部模組的 `translations` 併入語系（`i18n.catalog`，平台既有的鍵不覆蓋）。

## 8. 測試

| 檔案 | 項目 |
|---|---|
| `tests/test_models.py` | 模型檔驗證（竄改、簽章）、模型方法準確度、兩者並用、找不到模型、模型管理 API 與配方發布、工作佇列使用模型、GPU 設定、標註儲存／歷程／權限、訓練資料匯出與讀回 |
| `tests/test_module_validation.py` | validate-module（規則式、模型、命令列、錯誤資料集）、平台標註 → 匯出（含影像）→ 驗證的往返 |
| `examples/module_template/tests/` | 範例模組：數量、曝光不變性、判定、顯示文字併入 |
