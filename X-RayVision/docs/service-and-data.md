# 服務與資料

| 項目 | 內容 |
|---|---|
| 文件編號 | SPEC-003 |
| 版本 | v1.0（第 2 階段） |
| 對應程式 | `xrayvision/service/`、`xrayvision/store/`、`xrayvision/ingest/`、`xrayvision/core/judge.py` |
| 相關文件 | 產品規劃書 PLAN-001 第 4、6、13 節 |

本文件說明平台服務的組成、資料保存方式、配方版本管理、工作佇列、資料夾監看、判定規則、問題回報包與 HTTP API。

---

## 1. 啟動與資料目錄

```
python -m xrayvision recipe-import recipes/<配方>.json --data D:\XRV --release   匯入並發布配方
python -m xrayvision serve --data D:\XRV                                          啟動服務
```

服務預設只綁定本機 `127.0.0.1:8600`。資料目錄結構：

| 路徑 | 內容 |
|---|---|
| `settings.json` | 設定（服務位址、分析行程數、是否封存原始影像、監看間隔） |
| `xrayvision.db` | SQLite 資料庫 |
| `archive/<年>/<月>/<雜湊前兩碼>/<雜湊值>.<副檔名>` | 原始影像封存（複製並驗證雜湊值） |
| `results/<日期>/job<編號>.json` | 完整分析結果 |
| `calibration/<代碼>/` | 暗場／平場校正設定檔 |
| `uploads/<日期>/` | 由介面上傳的影像 |
| `exports/` | 問題回報包 |
| `logs/xrayvision.log*` | 應用程式日誌（每檔 10 MB，保留 10 份） |

`settings.json` 範例：

```json
{"host": "127.0.0.1", "port": 8600, "workers": 0, "archive_originals": true, "watch_interval_s": 5}
```

`workers` 為 0 時使用一半的處理器核心；分析行程以低於一般的優先權執行。

---

## 2. 資料庫

- **結構版本**：記錄於 `schema_version`；結構變更只新增資料表或欄位，不做反向遷移（退版採還原快照，見規劃書第 12.5 節）。
- **保護機制**（以資料庫觸發器強制，應用程式錯誤也無法繞過）：
  - 已發布的配方版本不可修改內容，也不可刪除。
  - 稽核紀錄只能新增，不可修改或刪除。
- **大型資料**：逐物件量測存於結果 JSON 檔；資料庫只存摘要，用於清單與統計。

| 資料表 | 內容 |
|---|---|
| `recipes` | 配方版本（草稿／已發布／停用）、完整內容、建立與發布人員 |
| `lots` | 批次（批號、配方、操作人員、拍攝參數） |
| `images` | 影像（雜湊值、原始路徑、封存路徑、種類、尺寸、樣品編號） |
| `jobs` | 分析工作（等待中／分析中／完成／失敗／已取消、重試次數、錯誤） |
| `runs` | 分析紀錄（結果檔、成像品質、自動判定、最終判定、摘要、軟體版本） |
| `module_results` | 各檢測模組的狀態、版本、判定、原因 |
| `reviews` | 人工複判紀錄 |
| `watch_folders`、`watch_seen` | 監看資料夾與已處理檔案 |
| `audit_log` | 稽核紀錄 |
| `diagnostic_exports` | 問題回報包匯出紀錄 |

---

## 3. 配方版本管理

```
建立草稿 → (修改草稿) → 發布 → (停用)
                ↘ 刪除草稿
```

- 同一配方代碼可有多個版本；新版本號自動遞增。
- 只有草稿可以修改或刪除；**分析只能使用已發布的版本**。
- 發布時記錄當下的檢測模組版本並鎖定。之後若模組升級：
  - 主版.次版相同（只有修訂版號不同）：配方照常使用。
  - 主版或次版不同（量測結果可能改變）：分析會停止並回報「模組版本不相容」，需由工程師建立新配方版本、驗證後發布。
- 資料夾監看使用該配方代碼的**最新已發布版本**。
- 「修改」（`POST /api/recipes/{pk}/revise`）：以該版本內容建立下一版草稿，note 記錄來源版本（`from vN`）；同一配方已有草稿時回傳該草稿。`GET /api/recipes/{pk}/diff` 回傳與來源版本的差異。
- 發布並重新分析：`POST /api/recipes/{pk}/release` 可帶 `{"reanalyze": "all_previous" | "lot" | "none", "lot_no"}`；範圍為目前結果使用同一配方代碼其他版本的影像（`GET /api/recipes/{pk}/reanalysis-scope` 回傳影像數、略過數、批號、平均分析時間）。
- 試跑：`POST /api/recipes/trial`（配方內容＋紀錄編號）以該紀錄的影像與拍攝參數同步分析，結果不寫入紀錄；獨立的低優先權子行程，同時只允許一個，逾時 180 秒中止；寫入稽核紀錄。

---

## 4. 影像匯入與工作佇列

### 4.1 匯入

匯入來源有三種：介面上傳、指定本機路徑（工程用）、資料夾監看。匯入時：

1. 確認影像可讀取並判定種類（16-bit 原始／8-bit 轉存）。
2. 計算 SHA-256 雜湊值；相同影像只建立一筆影像紀錄（可多次分析）。
3. 複製封存並驗證雜湊值（可於設定關閉）。
4. 於原始檔位置尋找拍攝參數檔，或使用手動輸入的參數。
5. 建立分析工作並寫入稽核紀錄。

### 4.2 佇列

- 工作存於資料庫，依優先權與建立順序執行。
- 服務重啟時，「分析中」的工作自動放回佇列，不會遺失。
- 子行程異常終止或分析發生例外時，自動重試一次；仍失敗則標示失敗與原因，可由介面重新執行。
- 同一影像可用另一個配方重新分析（建立新工作，舊紀錄保留）。沿用該影像最近一次的拍攝參數；影像檔（封存與原始位置）都已不存在時略過。
- **目前結果**：同一影像最新一筆紀錄；較早的紀錄標示為已被取代（`superseded_by`）。紀錄清單與 CSV 預設只列目前結果（`current_only`），總覽統計只計目前結果且日期依影像匯入時間。新結果重新自動判定，不沿用舊紀錄的人工複判。資料庫結構 6 新增索引 `runs(image_id, id)`。
- 批次重新分析：`POST /api/runs/reanalyze`（紀錄編號清單，配方版本未指定時用各紀錄配方的最新發布版本）；同一影像只建立一個工作。`GET /api/jobs/reanalysis` 回傳進行中的重新分析進度，`POST /api/jobs/reanalysis/cancel` 取消剩餘排隊工作。

---

## 5. 資料夾監看

| 規則 | 說明 |
|---|---|
| 掃描方式 | 輪詢（預設每 5 秒），相容網路磁碟 |
| 寫入完成判斷 | 連續兩次掃描檔案大小與修改時間不變，且可開啟讀取 |
| 原始檔 | 只讀取，不移動、不刪除、不鎖定 |
| 既有檔案 | 新增監看時，資料夾內既有檔案預設略過 |
| 不重複匯入 | 已處理的檔案（大小與修改時間未變）不再匯入 |
| 批號與樣品編號 | 命名規則為正規表示式，具名群組 `lot`、`sample`，套用於相對路徑；未設定時，批號為上一層資料夾名稱（位於根目錄時為日期），樣品編號為檔名 |

命名規則範例：`(?P<lot>[^/]+)/(?P<sample>[^/]+)\.tiff?$`

設備輸出的實際命名方式尚待確認（規劃書 Q16）。

---

## 6. 判定

### 6.1 模組判定（微凸塊對位）

配方的 `modules[].judgment` 設定規格：

| 規格 | 說明 |
|---|---|
| `die_shift_max_um` | 晶片偏移上限（µm）；需要像素尺寸 |
| `die_shift_max_px` | 晶片偏移上限（px）；未設定 µm 上限時使用 |
| `confidence_k` | 判定信心倍數，預設 2 |
| `check_groups` | 是否逐陣列判定，預設開啟 |

以偏移量 |shift| 與標準誤 se 判定：

| 判定 | 條件 |
|---|---|
| 合格 | \|shift\| + k·se ≤ 上限 |
| 不合格 | \|shift\| − k·se > 上限 |
| 需複判 | 其餘（接近規格邊界） |

開啟逐陣列判定時，等級中以上的各陣列也逐一判定；任一陣列不合格即不合格。未設定規格時為「未判定」，只提供量測值。

### 6.2 影像判定

| 優先順序 | 影像判定 | 條件 |
|---|---|---|
| 1 | 影像品質不足 | 品質閘門不合格 |
| 2 | 不合格 | 任一模組不合格 |
| 3 | 需複判 | 任一模組需複判、無法判定或執行錯誤 |
| 4 | 合格 | 所有有規格的模組皆合格 |
| 5 | 未判定 | 所有模組都未設定規格 |

8-bit 轉存影像的判定最多為「需複判」。人工複判後，最終判定改為複判結果；自動判定保留不變，複判紀錄寫入稽核。

---

## 7. 問題回報包

介面或 API 選取分析紀錄後匯出單一檔案，內容與選項見規劃書第 13 節。實作重點：

- 全程串流寫入磁碟，大量影像也不佔用大量記憶體。
- 每個檔案的 SHA-256 記錄於 `manifest.json`，原廠端開啟時逐一驗證。
- 加密：AES-256-GCM 分塊加密，金鑰以原廠 RSA 公鑰加密；**目前為開發用金鑰**，正式發布前須替換（`xrayvision/keys/README.md`）。
- 去識別化：批號、樣品編號、檔名、人員、原始路徑以代號取代，配方名稱清空。
- 原廠端重現：`python tools/diag_replay/replay.py <回報包> --key <私鑰>`，以相同配方重新分析並輸出差異報告。

---

## 8. HTTP API

完整規格：服務啟動後的 `/api/openapi.json`（互動文件 `/api/docs`）。操作者以標頭 `X-Operator` 傳入（第 4 階段改為登入）。錯誤回應格式為 `{"error": 代碼, "detail": 說明}`，前端以語系檔 `error.<代碼>` 顯示。

| 分類 | 端點 |
|---|---|
| 系統 | `GET /api/system`、`GET /api/i18n/{locale}`、`GET /api/modules` |
| 配方 | `GET/POST /api/recipes`、`GET/PUT/DELETE /api/recipes/{pk}`、`POST /api/recipes/{pk}/release`、`POST /api/recipes/{pk}/retire`、`POST /api/recipes/{pk}/revise`、`GET /api/recipes/{pk}/diff`、`GET /api/recipes/{pk}/reanalysis-scope`、`POST /api/recipes/trial`、`GET /api/recipe-template/{module_id}` |
| 匯入 | `POST /api/imports`（上傳）、`POST /api/imports/path`（本機路徑） |
| 工作 | `GET /api/jobs`、`POST /api/jobs/{id}/cancel`、`POST /api/jobs/{id}/retry`、`POST /api/images/{id}/reanalyze`、`GET /api/jobs/reanalysis`、`POST /api/jobs/reanalysis/cancel` |
| 分析紀錄 | `GET /api/runs`（篩選：判定、批號、配方、日期、`current_only`）、`GET /api/runs/{id}`（含 `history`）、`GET /api/runs/{id}/image`（伺服器端快取最近 24 張）、`POST /api/runs/{id}/review`、`POST /api/runs/reanalyze` |
| 統計 | `GET /api/stats`、`GET /api/lots` |
| 資料夾監看 | `GET/POST /api/watch-folders`、`PATCH /api/watch-folders/{id}`、`POST /api/watch-folders/scan` |
| 問題回報 | `POST/GET /api/diagnostics`、`GET /api/diagnostics/files/{name}` |
| 稽核 | `GET /api/audit` |

---

## 9. 實測

以 Batch2 共 9 張影像經 API 匯入（6 個分析行程）：22 秒內全部完成分析、判定與紀錄。
