# Golden Set 回歸、流程匯出與匯入，以及 CLI

目標：**改一個門檻後，在數分鐘內知道哪些影像從 PASS 變成 FAIL**。流程可放在 git 中、接受 code review，並在 CI 中執行。執行時的權威來源仍是資料庫。

## 1. 概念 {#concept}

- **Golden case**：一張影像加上一份期望結果（`expect_status`：ok、ng 或 any，並可選填 `expect_outputs`）。影像會落在 `ASSET_DIR/golden/<flow_id>/<uuid>.png`，且**永遠不進影像快取**；回歸會直接從路徑讀取。
- **回歸**：對該流程的每個 golden case 在**非試執行模式**執行，不保留中間影像，因此數百張影像不會撐爆記憶體；接著把每筆結果與期望比對得到 match 或 mismatch，再與上一個**基準**比對得到退步與進步。只有 mismatch 案例會再用 preview 重跑以取得介面影像 ref，最多 20 筆。
- **基準**：在回歸所用流程版本下，每個案例結果的快照（`{case_id: {status, outputs, duration_ms}}`）。`save_baseline` 只會新增一列；最新列就是比對使用的基準。

## 2. 資料模型 (apps/golden/models.py) {#models}

| 模型 | 欄位 | 備註 |
|---|---|---|
| GoldenCase | id, flow FK, name, image_path, expect_status (ok｜ng｜any), expect_outputs JSON, note, created_at | 刪除案例會刪除其影像檔。刪除流程會 cascade，檔案仍留在磁碟；若需要可手動清除 `golden/<flow_id>`。 |
| GoldenBaseline | flow FK, flow_version, results JSON, created_at | 每次 `save_baseline` 都新增一列；`GoldenBaseline.latest_for(flow_id)` 回傳最新列。 |

## 3. 期望與比對方式 {#expect}

案例在以下條件下為**命中**：

1. 若 `expect_status` 是 `ok` 或 `ng`，執行狀態必須相同（`failed` 永遠不命中）。`any` 會略過狀態檢查。
2. `expect_outputs` 中的每個 key 都必須出現在執行的具名輸出（來自 `output` 工具）中，且符合：

```
{"hole_count": 5,                          // equality: numbers compared as float; strings, bools and lists compared directly
 "width_mm":  {"value": 12.4, "tol": 0.2},  // numeric tolerance: |now - 12.4| <= 0.2
 "code":      {"value": "A123"}}            // value on its own is fine too
```

**混淆矩陣**以 `expect_status` 作為 ground truth，且 `ng` 是正類；預測為「not ok」（ng 或 failed）時計為正類。`expect_status=any` 的案例會排除。

|  | 預測 ng / failed | 預測 ok |
|---|---|---|
| 期望 ng | tp | fn — 漏出，最嚴重結果 |
| 期望 ok | fp — 誤判 | tn |

## 4. Golden Set API {#api}

權限依流程規則：**任何看得到流程的人都可檢視與執行**（`_visible_flows`），**工程師或管理員可新增、編輯、刪除與儲存基準**（`_editable_flow`），執行前會先檢查 `principal.can_execute()`，引擎鎖定時回 423。

| 方法與路徑 | 功能 |
|---|---|
| `GET /api/vision/flows/{id}/golden` | `{items:[{id, name, expect_status, expect_outputs, note, created_at, image_url}], total, can_manage, baseline_version, baseline_at, flow_version}` |
| `POST /api/vision/flows/{id}/golden` (multipart) | `images[]`（最多 200 張）加上選填表單欄位 `expect_status`、`note`、`expect_outputs`（JSON 字串）。每張影像建立一個案例，以檔名命名。回傳 201 與 `{items, created}`。 |
| `POST /api/vision/flows/{id}/golden` (JSON) | `{"from_batch": [{"image_ref", "name", "expect_status", "expect_outputs", "note"}]}` — 從批次執行回傳的 image ref 建立案例，前提是 ref 仍在影像快取中。若任一 ref 已過期，整個請求回傳 404 `image_gone`，且不建立任何案例。 |
| `GET /api/vision/flows/{id}/golden/baseline` | `{baseline: {id, flow_version, results, created_at, case_count} \| null, flow_version, case_count}` |
| `GET /api/vision/flows/{id}/golden/{case_id}/image?max=&fmt=&q=` | 縮圖或完整影像，JPEG 或 PNG。供 `<img>` 標籤使用，因此接受 `?token=` 或 `?api_key=`。 |
| `PATCH /api/vision/flows/{id}/golden/{case_id}` | `{name?, expect_status?, expect_outputs?, note?}` |
| `DELETE /api/vision/flows/{id}/golden/{case_id}` | 204，且影像檔會刪除。 |
| `POST /api/vision/flows/{id}/regress` | `{graph?, save_baseline?, fail_under?}` → 下方的回歸報告。`graph` 可為編輯器未儲存 graph，與 preview 相同。`fail_under` 為 0 到 1，只影響 `passed`。 |

## 5. 回歸報告 {#regress}

```
{
  "flow_id": 1, "flow_name": "hole_count", "flow_version": 7, "graph_override": false,
  "total": 320, "match": 316, "mismatch": 4, "match_rate": 0.9875,
  "regressed": [{"case_id": 42, "name": "0042.png", "was": "ok", "now": "ng", "node": "ng-judge", "error": "", "reasons": ["status ng != ok"]}],
  "improved":  [{"case_id": 7,  "name": "0007.png", "was": "ng", "now": "ok", "node": null, "error": ""}],
  "confusion": {"tp": 118, "fp": 2, "tn": 198, "fn": 2},
  "cases": [{"case_id": 42, "name": "0042.png", "expect": "ok", "expect_outputs": {},
             "status": "ng", "outputs": {"hole_count": 4}, "duration_ms": 12.3,
             "match": false, "reasons": ["status ng != ok"],
             "was": "ok", "was_match": true, "changed_since_baseline": true,
             "node": "ng-judge", "error": "", "image_ref": "<run>:src:image", "preview_run_id": "..."}],
  "duration_ms": 4210, "baseline_version": 6, "baseline_at": "...",
  "fail_under": 0.98, "passed": true, "baseline_saved": false
}
```

- **regressed**：基準結果原本符合期望，但此次不符合。**improved** 則相反。兩者都會用*目前*期望評估基準結果，因此編輯案例期望不會製造假退步。
- `node`：出錯的節點（status error），或第一個判定 ng 的節點。`error` 是該節點的訊息。
- `changed_since_baseline`：狀態或輸出與基準不同；沒有基準時為 null。
- `image_ref` 只出現在 mismatch 案例，最多 20 筆；用 `GET /api/vision/images/{ref}` 取得。Golden 影像本身永遠可透過 `image_url` 取得。
- 回歸執行會進入統計與 FlowRun，`trigger="regress"`，受 `PERSIST_RUNS` 控制；preview 重跑不會記錄。

### 自動調參 {#autotune}

Golden Set 頁上的「自動調參」（`POST /flows/{id}/golden/autotune`，body `{graph?, max_evals?, deadline_s?}`）會把每個案例的期望狀態與期望輸出當作標記，對流程或未儲存草稿 graph 的現場教導參數（`teach=True`）執行座標下降搜尋；公差、範圍與期望數量會保留。只有嚴格更好的變更才會保留。它回傳 `{graph, before:{match,total}, after, change_text[], evals, elapsed_ms, improved, budget_hit, cases, skipped[]}`。它不會寫回流程：「送到編輯器」會把結果放進草稿，供您檢查後再儲存。詳見 [AI 助手 › 自動調參](agent.md#candidates)。

## 6. CLI：manage.py regress {#cli-regress}

```
manage.py regress <flow_id|name> [--fail-under 0.98] [--json] [--save-baseline] [--graph file.flow.json --source <id>]
```

| 結束碼 | 意義 |
|---|---|
| 0 | 命中率達到或高於門檻（`--fail-under` 預設為 1.0，因此任何 mismatch 都會失敗） |
| 1 | 命中率低於門檻 |
| 3 | 流程沒有 golden cases |

文字輸出會先列出 **REGRESSED** 清單，也就是哪些影像從 PASS 變 FAIL，以及在哪個節點。`--json` 則輸出完整報告。`--graph` 會用匯出檔中的 graph 取代資料庫中的 graph，這是檢查 pull request 中流程變更的方式。

## 7. 流程匯出格式 (apps/vision/serialize.py) {#export}

```
{
  "schema_version": 1,
  "exported_at": "2026-08-28T06:00:00Z",
  "name": "hole_count",
  "description": "Hole count inspection",
  "continuous_interval_ms": 0,
  "graph": {
    "nodes": [
      {
        "id": "blob",
        "type": "blob",
        "label": "Holes",
        "enabled": true,
        "params": {
          "max_area": 60000,
          "min_area": 300,
          "min_circularity": 0.6,
          "sort_by": "area"
        },
        "position": {
          "x": 1540,
          "y": 40
        }
      },
      {
        "id": "src",
        "type": "image_source",
        "label": "Acquire",
        "enabled": true,
        "params": {
          "source_id": "{SOURCE}"
        },
        "position": {
          "x": 40,
          "y": 40
        }
      }
    ],
    "edges": [
      {
        "id": "e-blob-count-cmp-value",
        "source": "blob",
        "source_handle": "count",
        "target": "cmp",
        "target_handle": "value"
      }
    ]
  }
}
```

序列化是**穩定的**，因此 `git diff` 才有意義：

- 頂層 key 依固定順序排列。節點 key 依序為 `id, type, label, description, enabled, continue_on_error, color, params, position, width, height`，再接字母排序；`params` 會遞迴依 key 排序；edge key 依序為 `id, source, source_handle, target, target_handle`。
- 節點依 `id` 排序，edge 依 `(source, target, source_handle, target_handle)` 排序，因此在畫布上拖曳或重接線不會產生 diff。
- `position`（以及 width、height）會四捨五入成整數，因此微移節點不會產生 diff。
- `image_source.source_id` 會變成 `{SOURCE}` 佔位符，也就是範本畫廊使用的同一套 `templatize`，匯入時再透過 `--source` 或 `source_id` 替換。若未提供：新建流程會得到空字串，仍可用 pushed image 執行；**更新既有流程會保留產線已設定在擷取步驟上的來源**，先找相同 node id，否則找任一擷取步驟，所以匯入不會抹掉現場設定好的來源。
- graph 會先通過 `validate_graph`，因此省略的 `source_handle` 與 `target_handle` 會在匯出前補齊。
- 兩空格縮排、`ensure_ascii=False`、UTF-8 無 BOM、LF、檔尾一個換行。
- `exported_at` 是實際匯出時間。若需 byte-identical reproducibility，請依 reproducible-builds 慣例設定 `SOURCE_DATE_EPOCH=<unix seconds>`。`tests/test_flow_cli.py` 會用它驗證 export → import → export 產生相同 bytes。

匯入不會改變 graph JSON 格式，也不會把 Flow.graph 搬出資料庫：檔案只是資料庫內容的穩定投影。

## 8. CLI：manage.py flow {#cli-flow}

```
manage.py flow export <id|name> -o flows/hole_count.flow.json     # without -o it prints to stdout
manage.py flow import flows/hole_count.flow.json [--source 3] [--owner kevin]
manage.py flow run <id|name|file> [--source 3] [--images ./samples] [--json]
```

- **import** 以 `name` upsert：既有流程會更新 graph、description 與 interval，並讓 `version` 加一；否則建立新流程（`--owner` 設定擁有者，未提供則流程為共享）。schema_version 不符、source 缺失或檔案缺失都會以 CommandError 結束。
- **run** 可直接使用資料庫中的流程或 `.flow.json` 檔案，後者不寫入資料庫，而是以 graph override 執行。`--images` 指向資料夾時，每張影像都會以 `input_image` 執行一次，不走 preview，並逐張印出 `status ms filename outputs`；否則使用流程自己的來源執行一次。`--json` 印出 `{flow, items[], total, ok, ng, failed}`。任何失敗，包含影像無法解碼，都以結束碼 2 結束。
- 這些執行的 trigger 為 `cli`，且會進入統計與 FlowRun。

## 9. 匯出與匯入 API (apps/vision/api_flowio.py) {#flow-api}

| 方法與路徑 | 功能 |
|---|---|
| `GET /api/vision/flows/{id}/export` | 與下載相同的 JSON，並帶 `Content-Disposition: attachment; filename="<name>.flow.json"`。`?download=0` 會省略下載標頭。任何看得到流程的人都可匯出。 |
| `POST /api/vision/flows/import` | JSON body：整份匯出文件（可選帶 `source_id`），或 `{"doc": {...}, "source_id": 3}`。Multipart：`file` 加上 `source_id` 表單欄位。回傳 `{flow, created}`；建立時為 201，更新時為 200。更新既有流程需要工程師或管理員權限，否則回 404；新建流程歸呼叫者所有。 |

路由順序：`/flows/import` 必須註冊在 `/flows/{flow_id}` 之前，因為 ninja path parameters 不做型別轉換，這也是 `config/api.py` 把 flow-io 與 golden router 掛在 vision router 前面的原因。

## 10. 在 CI 中執行 {#ci}

```
# 1. Import the flow file into a clean test database, pointing at the CI source
#    (or leave the source out and push images with --images)
manage.py migrate
manage.py flow import flows/hole_count.flow.json
# 2. Create the golden images through the API (or restore ASSET_DIR/golden and the database from a backup)
# 3. Regress; fail the pipeline below 0.98
manage.py regress hole_count --fail-under 0.98 --json > regress.json
```

當 pull request 只變更 `.flow.json` 時，可略過匯入，改用 `manage.py regress hole_count --graph flows/hole_count.flow.json --source 3` 直接拿 pull request 中的 graph 測既有 Golden Set。

## 11. 檔案與測試 {#files}

| 檔案 | 內容 |
|---|---|
| `apps/golden/models.py`, `migrations/0001_initial.py` | GoldenCase、GoldenBaseline |
| `apps/golden/regress.py` | 影像存取、比對規則、API 與 CLI 共用的 `run_regression()` |
| `apps/golden/api.py` | Golden Set 與 regress 端點 |
| `apps/golden/management/commands/regress.py` | `manage.py regress` |
| `apps/vision/serialize.py` | 穩定序列化、parse、import_flow、find_flow |
| `apps/vision/api_flowio.py` | 匯出與匯入端點 |
| `apps/vision/management/commands/flow.py` | `manage.py flow export\|import\|run` |
| `tests/test_golden.py`, `tests/test_flow_cli.py` | 上傳、從批次建立、影像端點、比對規則、回歸報告與基準、CLI 結束碼與權限；匯出格式、byte-identical round trips、匯入 upsert、用資料夾或檔案執行，以及 API |
