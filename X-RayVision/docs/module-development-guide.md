# 檢測模組開發指南

| 項目 | 內容 |
|---|---|
| 文件編號 | GUIDE-001 |
| 版本 | v1.0（第 5e 階段） |
| 日期 | 2026-09-23 |
| 對象 | 開發新檢測模組的工程師（原廠或合作夥伴） |
| 相關文件 | 模組介面規格 [SPEC-001](inspection-module-interface.md)、空洞檢測 [SPEC-006](void-inspection.md)、深度學習與標註 [SPEC-007](deep-learning-and-annotation.md) |
| 範例 | 範例模組樣板 `examples/module_template/`（亮點計數）、空洞檢測模組 `xrayvision/inspections/void/` |

本指南說明如何從零開發一個檢測模組、驗證並交付到產線。介面細節以 SPEC-001 為準。

---

## 1. 開發流程

```
需求與樣品影像 → 合成影像與正確答案 → 演算法 → 模組外殼 → 單元測試 → 模組驗證 (validate-module)
→ 成像條件不變性與重複性 (validate) → 驗證報告 → 打包 (更新檔或外部套件) → 現場核准 → 產線配方
```

| 步驟 | 產出 | 說明 |
|---|---|---|
| 1 | 需求與影像 | 檢測對象、量測值、判定規格；實際樣品影像（含良品與不良品）與同一視野不同拍攝條件的影像 |
| 2 | 合成影像 | 依物理模型產生可控制的測試影像與正確答案，見第 5 節 |
| 3 | 演算法 | 只依賴 `ctx` 提供的輸入；門檻相對於目標自身（第 3 節） |
| 4 | 模組外殼 | 參數、判定、品質規則、結果格式、顯示文字（第 2 節） |
| 5 | 測試 | 單元測試、合成影像準確度、曝光不變性、判定規則 |
| 6 | 模組驗證 | `validate-module` 以標註資料集驗證，產生報告（第 6 節） |
| 7 | 交付 | 內建模組隨更新檔交付，或外部套件（第 7 節） |
| 8 | 核准 | 工程師審閱報告後於「配方管理 > 檢測模組」核准；未核准的模組判定最多為需複判 |

---

## 2. 模組結構

最小可執行的範例見 `examples/module_template/xrayvision_blob_count/__init__.py`。

```python
class BlobCount(InspectionModule):
    module_id = "blob_count"                 # 小寫英文與底線，全平台唯一
    version = "1.0.0"                        # 量測結果可能改變時至少提升次版號
    names = {"zh-TW": "…", "en": "…"}
    supported_kinds = (KIND_RAW16, KIND_RGB8)
    params = (Param(...), ...)               # 配方參數：平台自動產生設定畫面並檢查輸入
    judgment_params = (Param(...), ...)      # 判定規格：數值由配方設定
    quality_rules = (QualityRule(...), ...)  # 模組品質指標的預設門檻
    overlay_styles = {"blob": {...}}         # 疊圖樣式 (依幾何名稱)
    finding_table = dict(...)                # 選用：檢閱畫面與報告的物件排行表與分布
    translations = {"zh-TW": {...}, "en": {...}}   # 外部模組的顯示文字
    validation_criteria = {...}              # 選用：validate-module 的驗收標準
    def run(self, ctx, params): ...          # 回傳 ModuleResult
    def judge(self, result, spec, pixel_size_um=None): ...
    @classmethod
    def validation_metrics(cls, pairs, spec): ...   # 選用：與標註比對的指標
```

### 2.1 參數型別

| 型別 | 用途 |
|---|---|
| `float`／`int` | 數值；以 `min`、`max` 限制範圍，`unit` 為顯示單位（`px`、`um`、`deg`、`ratio`、`%`、`sigma`） |
| `bool` | 開關 |
| `enum` | 選項，`choices` 列出代碼；顯示文字為語系鍵 `ui.choice.<參數>.<代碼>` |
| `model` | 深度學習模型參照「模型代碼@版本」；`choices` 列出適用的任務（例如 `void_segmentation`）。配方發布時檢查模型存在、啟用中、適用於該模組 |

進階參數設 `advanced=True`，配方畫面預設收合。

### 2.2 執行輸入 `ctx`

| 欄位 | 說明 |
|---|---|
| `ctx.prepared.absorption` | 吸收量影像（float32，越大越暗）；16-bit 影像為 −ln(I) |
| `ctx.image.kind` | `raw16`／`rgb8` |
| `ctx.pixel_size_um` | 像素尺寸；`None` 時以 px 輸出 |
| `ctx.in_region(x, y)` | 檢測區域判斷；區域外的目標不量測、也不列入未量測 |
| `ctx.models`／`ctx.gpu` | 配方參照的模型 `{參照: dict(path, meta)}`；推論是否使用 GPU |

### 2.3 執行輸出

- `findings`：檢測物件（類別、具名幾何 `circle`／`vector`／`bbox`／`polygon`、量測值、`used`／`reason`、`flags`）。
- `summary`：影像層級結果；數值欄位由平台以 `summary.<鍵>` 顯示，不需另寫畫面。
- `metrics`：模組品質指標，鍵為 `<module_id>.<指標>`。
- `status`：`ok`／`no_result`（無法判定，`reasons` 說明原因）；例外由平台捕捉為 `error`。
- 量測值鍵以 `_px`、`_px2` 結尾，用 `core.units.add_um` 加上 `_um`、`_um2`。

### 2.4 判定

`judge()` 回傳 `(等級, 原因)`，等級為 `pass`／`fail`／`review`／`not_judged`。原因代碼可用 `代碼:對象` 指出物件（例如 `void_pct_exceeds_limit:ball12`）。平台再套用：

- 成像品質不合格 → 影像判定為品質不足
- 8-bit 轉存影像、未驗證模組 → 合格／不合格改為需複判
- 量測值接近規格時應回傳需複判（以量測值 ± k × 估計誤差比較）

---

## 3. 演算法規範

1. **不使用絕對灰階門檻**：以目標自身（例如焊點中心吸收量、局部雜訊）或整張影像的響應分布為基準。X 光功率、曝光改變時結果不可改變。
2. **明確回報不確定性**：提供估計誤差；無法可靠量測時回報 `no_result` 或把物件標示未採用，並說明原因。
3. **不可默默略過目標**：偵測到卻無法量測的目標要計入「未量測」，由判定轉為需複判。
4. **只使用 `ctx`**：不直接存取資料庫、檔案系統或網路。
5. **效能**：分析在低優先權子行程中執行，每個行程只用 1 個執行緒；以一般產線影像（約 6 百萬像素）在數秒內完成為目標。
6. **文字**：全部來自語系（內建模組放平台語系檔；外部模組用 `translations`），不得包含設備廠牌。

---

## 4. 顯示文字

外部模組以 `translations` 提供，平台載入時併入（平台既有的鍵不覆蓋）。至少提供：

| 鍵 | 說明 |
|---|---|
| `module.<代碼>` | 模組名稱 |
| `metric.<代碼>.<指標>` | 品質指標名稱 |
| `reason.<代碼>` | 判定原因與無法判定原因 |
| `finding.<類別>`、`measure.<量測值>`、`summary.<鍵>`、`ui.layer.<幾何名稱>` | 檢測物件、量測值、摘要、疊圖圖層 |

內建模組把文字加入 `xrayvision/i18n/zh-TW.json` 與 `en.json`；`tests/test_i18n.py` 會檢查原因代碼與前端用到的鍵都有翻譯。

---

## 5. 合成影像與正確答案

沒有足夠實際不良品時，先以物理模型產生合成影像開發與測試。參考 `tests/synthetic_void.py`：

- 以穿透厚度建立吸收量（例如截頂球弦長、球形空洞扣除厚度），再依光子雜訊轉成 16-bit 強度
- 數值（背景吸收量、對比、雜訊、邊緣模糊）依實際影像實測訂定
- 提供正確答案（空洞位置與面積）
- 可控制曝光、功率、斜射、焊墊等干擾，用於不變性與誤報測試

合成影像只能證明演算法「在模型假設下」正確；模組必須以實際影像驗證後才能核准。

---

## 6. 模組驗證

### 6.1 驗證資料集

格式 `xrv-validation-set/1`：`annotations.json`（每張影像的焊點與空洞輪廓）＋ `images/`。取得方式：

| 來源 | 做法 |
|---|---|
| 產線實際影像 | 檢閱畫面「標註」修正空洞 → 「檢測紀錄」勾選 →「匯出訓練資料」勾選「包含原始影像與整張標註」 |
| 合成影像 | `python tools/model_training/make_synthetic_dataset.py --out build/validation/synthetic_void.zip` |

### 6.2 執行

```
python -m xrayvision validate-module void --dataset <資料集.zip> --recipe <配方.json> --out <資料夾>
       [--model void_unet@1.0.0=<void_unet-1.0.0.xrvmodel>]
```

輸出 `report.json` 與 `report.html`，列出各驗收項目的結果與是否達標。模組以 `validation_metrics()` 計算指標、`validation_criteria` 宣告驗收標準。空洞檢測的標準：

| 項目 | 標準 |
|---|---|
| 空洞檢出率（直徑 ≥ 焊點直徑 15%） | ≥ 95% |
| 無空洞焊點誤報率 | ≤ 2% |
| 空洞率誤差 95% 分位 | ≤ 2 個百分點 |
| 漏判（實際超規卻判合格） | 0 |
| 未量測焊點比例 | ≤ 5% |

成像條件不變性與重拍重複性另以 `python -m xrayvision validate` 驗證（同一視野、不同拍攝條件的影像，見 SPEC-002）。

### 6.3 核准

工程師審閱驗證報告後，於「配方管理 > 檢測模組」按「核准驗證」，填寫說明（驗證資料集、結果摘要）與報告編號。核准以主版.次版為單位。

---

## 7. 打包與交付

| 方式 | 適用 | 做法 |
|---|---|---|
| 內建模組 | 原廠維護的模組 | 放在 `xrayvision/inspections/<代碼>/`，於 `xrayvision/inspections/__init__.py` 匯入；隨更新檔（`.xrvupd`）交付 |
| 外部套件 | 合作夥伴或客製模組 | 依 `examples/module_template/pyproject.toml` 宣告 entry point（群組 `xrayvision.inspections`）；安裝到產品執行環境後重新啟動服務即載入 |

> 目前更新檔只包含平台程式與執行環境；外部套件的離線安裝流程（簽章、網頁上傳）尚未提供，暫以隨更新檔的執行環境一併交付（見 README 待辦事項）。

深度學習模型另以 `.xrvmodel` 交付（SPEC-007）：`python tools/model_training/train_void.py --key <原廠簽章私鑰>`。

---

## 8. 檢查清單

- [ ] `module_id`、版本、名稱（繁中、英文）
- [ ] 參數有範圍與單位，進階參數標示 `advanced`
- [ ] 門檻相對於目標自身，曝光 ×0.5～×2 時結果不變（測試）
- [ ] 無法量測的目標計入未量測；接近規格回傳需複判
- [ ] 遵守檢測區域 `ctx.in_region`
- [ ] 品質指標與預設規則（至少「可量測目標數」與「對比」）
- [ ] 顯示文字齊全（`tests/test_i18n.py` 通過），不含設備廠牌
- [ ] 單元測試、合成影像準確度測試
- [ ] `validate-module` 報告達標；`validate` 不變性驗證通過
- [ ] 量測結果改變時提升次版號，並重新驗證與核准
