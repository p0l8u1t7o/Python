# 檢測模組介面規格

| 項目 | 內容 |
|---|---|
| 文件編號 | SPEC-001 |
| 版本 | v1.4（第 5c～5e 階段：模型參數型別、推論、顯示文字、模組驗證介面；5b 檢測區域；5a 物件排行表、驗證狀態、面積單位） |
| 對應程式 | `xrayvision/core/plugin.py`、`xrayvision/core/pipeline.py` |

本文件定義檢測模組掛載於平台的介面。依本規格開發的模組不需修改平台核心，即可在配方中啟用，並由平台提供疊圖、判定彙整、報告與稽核（後續階段）。

---

## 1. 模組宣告

檢測模組繼承 `InspectionModule`，並宣告下列屬性：

| 屬性 | 說明 |
|---|---|
| `module_id` | 模組代碼，小寫英文與底線，全平台唯一，例如 `bump_alignment`、`void` |
| `version` | 語意化版本（主版.次版.修訂）；量測結果可能改變時至少提升次版號 |
| `names` | 顯示名稱，`{"zh-TW": …, "en": …}`，不得包含設備廠牌 |
| `supported_kinds` | 支援的影像類型：`raw16`（16-bit 原始影像）、`rgb8`（8-bit 轉存影像） |
| `params` | 參數結構（第 2 節） |
| `overlay_styles` | 各幾何名稱的疊圖樣式（顏色、線寬、向量放大倍率） |
| `quality_rules` | 模組預設品質規則（`QualityRule`），指標鍵為 `<module_id>.<指標>`；見 SPEC-002 |
| `repeat_anchor` | 不變性驗證時用來配對同一物件的幾何名稱（取其圓心），例如 `bump` |
| `repeat_keys` | 不變性驗證時比較的量測值，例如 `("dx_px", "dy_px")` |
| `summary_vector` | `summary` 中含 `dx`、`dy` 的影像層級結果鍵，例如 `die_shift` |
| `finding_table` | 選用。檢閱畫面與報告的物件排行表：`dict(category=物件類別, sort=排序量測值, columns=(量測值, …), limit=筆數)`，例如空洞檢測依空洞率列出前 10 顆焊點，並附分布直方圖 |

並實作 `run(ctx, params) -> ModuleResult`。

## 2. 參數結構

每個參數以 `Param` 宣告：

| 欄位 | 說明 |
|---|---|
| `key` | 參數鍵，小寫英文與底線；有單位時以後綴表示，例如 `_px`、`_deg`、`_um` |
| `type` | `float`、`int`、`bool`、`enum` |
| `default` | 預設值 |
| `label` | 顯示名稱（繁中、英文） |
| `min`／`max`／`choices` | 允許範圍或選項 |
| `unit` | 顯示單位 |
| `advanced` | 進階參數，配方畫面預設收合 |

平台依參數結構產生配方設定畫面，並在載入配方時檢查：未知參數、型別錯誤、超出範圍都會拒絕，不會靜默使用預設值。

## 3. 執行輸入

`ctx`（`AnalysisContext`）提供：

| 欄位 | 說明 |
|---|---|
| `ctx.image` | 原始影像資料：像素、影像類型、檔案雜湊值 |
| `ctx.prepared.absorption` | 吸收量影像（float32，越大越暗）；16-bit 影像為 −ln(I)，已由平台完成成像條件第一層正規化 |
| `ctx.prepared.display` | 顯示用 8-bit 影像 |
| `ctx.pixel_size_um` | 配方指定的像素尺寸（µm）；未指定時為 `None`，模組可依設計尺寸自行推得並回報 |
| `ctx.prepared.calibration` | 使用的暗場／平場校正設定檔摘要；未使用時為 `None` |
| `ctx.region_mask`／`ctx.in_region(x, y)` | 配方的檢測區域（第 5b 階段）；`region_mask` 為 `None` 時是整張影像。模組應只量測中心在區域內的目標，區域外的目標不量測、也不列入未量測 |

`params` 為平台依配方解析並檢查後的完整參數。

## 4. 執行輸出

回傳 `ModuleResult`：

| 欄位 | 說明 |
|---|---|
| `status` | `ok`、`no_result`（無法判定）、`error`（平台捕捉例外時設定） |
| `findings` | 檢測物件清單（第 5 節） |
| `groups` | 檢測物件群組，例如凸塊陣列，含群組層級估計值與等級 |
| `summary` | 影像層級結果，例如晶片偏移、空洞率 |
| `metrics` | 模組品質指標，鍵為 `<module_id>.<指標>`；平台依品質規則判定成像品質 |
| `reasons` | 原因代碼，例如 `no_bumps_found`、`insufficient_sites` |
| `rejects`／`rejected` | 候選物件剔除原因統計與位置 |

所有原因代碼都必須在語系檔（`xrayvision/i18n/*.json`）提供繁中與英文文字。

## 5. 檢測物件

`Finding` 以一般資料表示，介面與報告不需為新模組另外開發：

| 欄位 | 說明 |
|---|---|
| `category` | 物件類別，例如 `bump_site`、`void` |
| `geometry` | 具名幾何，類型包括 `circle`（x, y, r）、`vector`（x, y, dx, dy）、`bbox`（x0, y0, x1, y1）、`polygon`（points） |
| `measurements` | 數值量測，鍵名附單位後綴 |
| `group` | 所屬群組編號（0 為未分群） |
| `used`／`reason` | 是否採用；未採用時的原因代碼 |
| `flags` | 其他標記 |

## 6. 開發規範

1. 不使用絕對灰階門檻；以局部背景或目標自身為基準定義門檻。
2. 長度以 `_px`、面積以 `_px2` 結尾命名，像素尺寸可用時以 `core.units.add_um` 同時提供 `_um`、`_um2` 值。
3. 無法可靠量測時回傳 `no_result` 與原因代碼，不輸出看似精確的數字。
4. 不直接存取資料庫、檔案系統或網路；只使用 `ctx` 提供的輸入。
5. 顯示文字一律來自語系檔，不得包含設備廠牌名稱。
6. 模組發布前須附回歸影像集，並通過成像條件不變性驗證（規劃書第 3.3、5.6 節）。
7. 提供模組品質指標與預設規則，至少涵蓋「可量測目標數」與「對比」；能偵測模組特有的不適用情況時（例如斜射影像），以品質指標表示，不在模組內直接拒絕。

## 7. 註冊方式

- **內建模組**：放在 `xrayvision/inspections/<module_id>/`，以 `@register` 註冊，並於 `xrayvision/inspections/__init__.py` 匯入。
- **外部模組套件**：於套件的 `pyproject.toml` 宣告 entry point，平台啟動時自動載入：

```toml
[project.entry-points."xrayvision.inspections"]
void = "xrayvision_void:VoidInspection"
```

## 8. 配方格式（第 1 階段）

```json
{
  "recipe_id": "bump_alignment-default",
  "version": 1,
  "name": {"zh-TW": "微凸塊對位（預設）", "en": "Micro Bump Alignment (Default)"},
  "pixel_size_um": null,
  "calibration_profile": null,
  "quality_rules": [{"metric": "image.snr", "warn_below": 80, "fail_below": 30}],
  "acquisition_limits": {"tube_voltage_kv": [60, 110]},
  "modules": [
    {"module_id": "bump_alignment", "params": {"bump_level": 0.75}}
  ]
}
```

第 2 階段起，配方改由資料庫管理並加入版本鎖定與模組版本鎖定。

## 9. 模組驗證狀態（第 5a 階段）

- 模組版本以「主版.次版」為單位記錄驗證狀態（`module_validations` 資料表）；修訂版號只修正錯誤、不改變量測結果，沿用同一核准。
- 未驗證的模組仍可使用，但平台把其合格／不合格改為需複判，原因代碼 `module_unvalidated`，並在紀錄與報告註記。
- 新模組或次版號提升後，須依驗證程序（規劃書 PLAN-001 第 5.6 節）驗證，由工程師於「配方管理 > 檢測模組」核准。
- 影像層級的摘要：`summary` 中的數值欄位由平台以語系鍵 `summary.<鍵>` 顯示，不需另寫畫面；判定原因可用 `代碼:對象` 指出物件，例如 `void_pct_exceeds_limit:ball12`。
- 範例：空洞檢測模組（`xrayvision/inspections/void/`），說明見 [SPEC-006](void-inspection.md)。

## 10. 第 5c～5e 階段新增

| 項目 | 說明 |
|---|---|
| 參數型別 `model` | 深度學習模型參照「模型代碼@版本」，`choices` 為適用任務；配方發布時檢查模型 |
| `ctx.models`／`ctx.gpu` | 配方參照的模型 `{參照: dict(path, meta)}` 與推論是否使用 GPU；推論以 `core.inference.run(path, batch, gpu)` |
| `translations` | 外部模組的顯示文字 `{"zh-TW": {...}, "en": {...}}`，併入平台語系（既有的鍵不覆蓋） |
| `validation_metrics(pairs, spec)`／`validation_criteria` | 模組驗證工具 `validate-module` 的指標與驗收標準 |

完整開發流程見 [GUIDE-001 模組開發指南](module-development-guide.md)。

## 11. 檢測區域「視為一個陣列」（PLAN-004）

| 項目 | 說明 |
|---|---|
| 區域格式 | 圖形新增選用欄位 `label`（最多 32 字）與 `as_array`（僅包含區域）；未設定時與舊格式相同 |
| `supports_region_arrays` | 模組類別屬性（預設 False）；宣告支援時介面才提供「視為一個陣列」 |
| `ctx.region_group(x, y)` | 目標所在「視為一個陣列」區域的序號（0 表示由模組自動分群）；`ctx.region_labels` 為 `{序號: 名稱}`；重疊時屬於較後面的區域 |
| `Group.source`／`Group.label` | 群組來源 `auto`／`region` 與區域名稱，疊圖以名稱標示 |
| `warm(ctx, params)` | 選用：互動分析在背景先做與參數無關、耗時的步驟並快取，之後 `run()` 沿用；不得改變 `run()` 的結果。`ctx` 只有影像與校正結果（無檢測區域） |

微凸塊對位 1.1.1：強制陣列不套用最少凸塊數；可採用位點少於 3 個時不估計偏移，模組原因 `region_array_insufficient_sites:groupN`。未使用此功能時結果與 1.1.0 相同。
