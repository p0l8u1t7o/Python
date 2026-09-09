# 批次測試：影像集、逐張儲存結果、洞察與調參

批次測試頁，也就是側欄中的 `/batch`，讓您**選擇一條流程，讓一組影像跑過它，並保留每次執行的每張影像結果**。為影像標記期望 OK 或 NG 後，就能得到命中率與混淆矩陣；洞察卡會追蹤每個判定節點的輸入值，並算出**建議門檻**。您可在同一頁修改參數、再次執行同一影像集、比較前後結果，滿意後寫回流程、存為配方或送到編輯器。也可請 AI 助手依資料**諮詢**或**調整**，其結果會成為另一筆批次執行。從側欄進入此頁，位置是「檢測 › 批次測試」；在頂部選流程，若編輯器有未儲存變更，會出現「使用編輯器未儲存草稿」勾選框。

## 1. 概念：影像集與執行 {#concept}

- **影像集 (BatchSet)**：一組測試影像，可上傳或從影像來源擷取，每組最多 `VISION_BATCH_MAX_IMAGES`（200）張，儲存在伺服端。**期望標記屬於影像**，因此會保留到重複執行之後。`flow` 只記錄**建立時所屬的流程**，保留策略依它計算；影像集是測試資料，**可拿來測任何您看得到的流程**。
- **批次執行 (BatchRun)**：影像集針對一份 graph 快照的一次執行。逐張結果（狀態、耗時、具名輸出、每個節點的狀態與純量輸出、錯誤）會與摘要一起儲存。執行可指定 `parent`，也就是被調整前的執行；`origin` 為 manual、draft、autotune 或 ai_tune。`flow` 記錄**此次使用的流程**，當它與影像集流程不同時，介面會顯示流程名稱；空值代表使用影像集自己的流程。
- 與 Golden Set 的差異：Golden Set 是**正式回歸基準**，通常影像較少、有精確期望、可在 CI 中執行；批次測試是**調參工作台**，影像可多次反覆執行，資料會依保留策略過期。在批次頁勾選影像並「存到 Golden Set」即可移入正式基準。

## 2. 操作流程 {#flow}

1. 「新增影像集」：上傳檔案，或從影像來源擷取 N 張影像。清單跨流程顯示，當前測試流程的影像集排在前面。
2. 標頭中的「測試流程」就是要執行的流程。從編輯器進入時會預先選取，選定影像集後則設為影像集自己的流程。改選另一條流程再執行時，兩筆執行仍掛在同一影像集下，因此能直接比較。
3. 「以 *流程名稱* 執行」：背景執行，執行清單顯示進度，且可中斷。若執行不同流程，該筆執行會標示該流程名稱。
4. 在「影像」分頁，為每張影像標記 OK 或 NG，也可全部 OK / 全部 NG；「結果」分頁的 Expected 欄也可編輯。命中率與混淆矩陣會立即更新。
5. 「洞察」分頁：漏檢影像、失敗節點、門檻建議、依期望分組的具名輸出分布，以及跨執行趨勢。「套用建議並重新執行」會直接產生新執行。
6. 「調整」分頁：依群組編輯現場教導參數 →「再次執行」（新執行的 parent 是目前選取的執行）→「比較」分頁逐張對照。
7. 右下角全域 AI 助手（context = 批次頁，且已選取完成的執行）：提問即可諮詢資料，或給出調參指令。調整面板也有「自動調參」。這些操作都會產生新執行。
8. 結果正確後：「寫回流程」（工程師或管理員）、「存為配方」（參數差異成為 FlowRecipe）或「送到編輯器」（成為草稿）。

## 3. 資料模型與檔案 (apps/vision/models.py) {#models}

| 模型 | 欄位 |
|---|---|
| `BatchSet` | `flow`、`owner`、`name`、`source`（upload 或 source:name）、`images` JSON `[{index, name, path, width, height, expected, expect_outputs, note}]`、`image_count`、`size_bytes` 與時間戳。檔案位於 `ASSET_DIR/batch/<set_id>/NNN.png`；刪除影像集會移除該目錄。 |
| `BatchRun` | `batch_set`、`flow`（此次使用的流程；空值代表影像集自己的流程，且該流程刪除時 SET_NULL）、`parent`、`owner`、`flow_version`、`graph`（實際執行的快照，已套用配方）、`recipe_name`、`label` 與 `note`、`origin`、`status`（queued、running、done、cancelled、failed）、`progress_done` 與 `progress_total`、`summary`、`items`（逐張影像：`status, duration_ms, outputs, error, error_node, nodes{id:{status, duration_ms, message, branch, outputs}}`，只存純量，NaN 存成 null）、`insights`（快取）、`meta`（自動調參或 AI 調參備註）、`error` 與時間戳。 |

影像是否命中不存於 items：標記日後可編輯，因此序列化時由 `apps/golden/regress.evaluate_expect` 計算。標記變更後，`store.refresh_matches` 會重新計算該影像集內每個已完成執行的摘要與洞察。

## 4. 執行方式 (apps/vision/batch/jobs.py) {#exec}

- 背景執行緒處理，同時最多 `VISION_BATCH_MAX_RUNNING`（2）筆，而且同一影像集一次只跑一筆。`runner.compiled_for(flow, graph_override=graph)` 只編譯一次，來源與資產會在呼叫者執行緒預先開啟，接著每張影像直接進 `engine.execute(...)`。
- **不走 runner 佇列**：不寫流程統計、不送 SSE、不寫 FlowRun 列，也不套用隱含預設配方，配方只在建立執行時以 `recipe_id` 明確指定。影像進入自己的快取桶 `BATCH_FLOW_ID=-1`，完成後立即由 `store.drop_run` 丟棄，因此 200 張影像的批次不會擠掉編輯器試執行影像。
- 進度與完成資料每 10 張或每 2 秒以 `update()` 寫回；介面每秒輪詢一次。「中斷」會設定旗標，目前影像跑完後狀態變為 cancelled。
- 伺服器重啟後殘留在 running 的執行，下次讀取時會標為 failed（「伺服器已重新啟動，執行遭中斷」）。
- **自動調參模式**：先依影像集標記做座標下降，優先抽樣漏檢影像，最多 40 張，且永遠不動規格類參數，如公差、期望數量或範圍；接著用調整後 graph 完整重跑。`meta.autotune` 記錄前後命中率與變更內容。

## 5. 洞察與門檻建議 (apps/vision/batch/insights.py) {#insights}

- 命中率；混淆矩陣，期望 NG 是正類：tp 命中、fn 漏出、fp 誤判、tn 正確；漏檢清單，最多 20 張；哪些節點出錯、出錯次數與訊息；最慢影像與最耗時節點；以及依期望與實際結果分組的具名數值輸出統計。
- **門檻建議**：走訪 `if_number`、`in_range` 與 `tolerance_judge` 節點，沿著 `value` 輸入連線回到上游 `(node, port)`，從每張影像儲存的節點輸出中取該值，並依期望分成 OK 組與 NG 組：

  - `if_number`（gt、ge、lt、le）：方向由該分支通往的 judge 決定（true → OK 或 true → NG）。它掃描相鄰數值中點，找出最高命中率，且只在嚴格優於目前值時提出建議。
  - `in_range`：只移動 NG 值所在側的邊界，移到 NG 與 OK 值之間的中點；另一側保持不變。
  - `tolerance_judge`：顯示偏差分布，但不提出建議，因為公差是規格。

- 若有 parent，也會計算與前一次執行的差異（判定改變、進步、退步、參數改動）。`text[]` 是離線諮詢與 LLM 脈絡共用的可讀句子清單。`GET /batch/runs/{id}/insights` 另外回傳 `suggestions[]`，內容是可直接套用的 `{node, key, value}` 項目。

## 6. 調整、寫回、配方與 Golden Set {#tune}

- 調整面板的工作 graph 來自所選執行的 graph，或在勾選時來自編輯器草稿。它只列出 `teach=True` 參數，使用與參數卡相同的 `teachGroupsOf`，並以藍色條標示已變更參數。
- 「再次執行」是 `POST /batch/sets/{id}/runs {graph, parent_run_id}`。「寫回流程」是 `PATCH /flows/{id}`，版本 + 1。「存為配方」會比較工作 graph 與流程目前 graph 的差異，送進 `POST /flows/{id}/recipes`；伺服端也有 `POST /batch/runs/{id}/to-recipe` 可直接從執行 graph 建配方。
- 「存到 Golden Set」會直接複製影像檔並建立案例，期望來自標記或所選執行的判定，繞過影像快取，因此不會變成「影像已釋放」。

## 7. AI 諮詢與調整 (apps/vision/agent/consult.py) {#ai}

- **諮詢**，`POST /agent/consult {batch_run_id, question, graph?}`：一定先計算規則型洞察。有 LLM 可用時，它會收到流程 graph、洞察句子、逐張資料（漏檢影像優先，最多 50 列，含判定節點輸入值）與最多四張漏檢影像。回覆可在結尾帶 `SUGGESTIONS: {"suggestions":[{node,key,value,reason}]}`，伺服端會確認節點與參數存在且流程仍有效後才交給前端。離線或失敗時，答案由洞察句子依問題關鍵字組合，`suggestions` 來自門檻建議。
- **依資料調整**：`POST /agent/tune`，或代理模式中的 `POST /agent/jobs(task=tune)`，帶 `batch_run_id`。影像從磁碟載入，逐張資料與洞察會摺入批次摘要，調整後流程再跑同一影像集，落成新執行（origin=ai_tune，parent = 原執行）。回應帶新的 `batch_run_id`。離線時，若指令不符合規則，只要至少兩張影像有標記，就會退回資料驅動自動調參。
- **自動調參**：批次頁呼叫 `POST /batch/sets/{id}/runs {mode:"autotune"}`，背景且可中斷；`POST /agent/autotune` 也接受 `batch_run_id`。

## 8. API (apps/vision/batch/api.py) {#api}

```
GET    /vision/batch/sets[?flow_id=]                  {items[set… with flow_name and latest_run], total, max_images, keep_sets, keep_runs}
                                                      omit flow_id for every visible set (a set can test any flow)
POST   /vision/batch/sets                             multipart images[] + flow_id + name? → 201 set (with images)
POST   /vision/batch/sets/from-source                 {flow_id, source_id, count, name?} → 201
GET    /vision/batch/sets/{id}                        set (with images, latest_run, can_manage)
PATCH  /vision/batch/sets/{id}                        {name?, labels:[{index, expected?, expect_outputs?, note?}], remove:[index]}
DELETE /vision/batch/sets/{id}                        204 (409 while a run is in progress)
GET    /vision/batch/sets/{id}/images/{index}?max=    the image (?token= works, for <img>)
POST   /vision/batch/sets/{id}/to-golden              {indexes?, expect_from: label|status, run_id?, note?} → 201 {created, ids}
GET    /vision/batch/sets/{id}/runs                   {items[run summary… with flow_id, flow_name, set_flow_id], total}
POST   /vision/batch/sets/{id}/runs                   {flow_id? (which flow to test; omitted = the image set's), mode: run|autotune, graph?,
                                                       recipe_id?, label?, note?, parent_run_id?, origin?, max_evals?, deadline_s?} → 202 run
GET    /vision/batch/runs/{id}?items=1                run (items carry name, expected, match, reasons, image_url; plus graph and progress)
PATCH  /vision/batch/runs/{id}                        {label?, note?}
POST   /vision/batch/runs/{id}/cancel                 {cancelled}
DELETE /vision/batch/runs/{id}                        204
GET    /vision/batch/runs/{id}/insights               the insights (ready=false while unfinished) plus suggestions[]
GET    /vision/batch/runs/{id}/compare?other=         {a, b, rows[], summary{changed, improved, regressed, same, a_match, b_match}, param_diff}
POST   /vision/batch/runs/{id}/rows/{index}/preview   {graph?} → a RunReport with overlays; the images go into the cache for the viewer
POST   /vision/batch/runs/{id}/to-recipe              {name, description?, is_default?} → 201 recipe
POST   /vision/agent/consult                          {batch_run_id, question, graph?} → {answer, provider, insights, suggestions, warnings}
```

權限：能看到流程即可讀取。建立影像集或執行需要執行權限，引擎鎖定時為 423。編輯標記與刪除需要是影像集建立者、工程師或管理員；存到 Golden Set 或存為配方需要工程師或管理員。較舊的 `POST /flows/{id}/batch` 與 `/batch-source`，也就是立即批次且不儲存結果的端點，仍保留給 API 整合方。

## 9. 保留設定 (.env) {#retention}

| 變數 | 預設值 | 控制內容 |
|---|---|---|
| `VISION_BATCH_MAX_IMAGES` | 200 | 每組影像數 |
| `VISION_KEEP_BATCH_SETS` | 10 | 每條流程保留的影像集數；最舊者會連同檔案刪除，除非有執行進行中 |
| `VISION_KEEP_BATCH_RUNS` | 20 | 每個影像集保留的已完成執行數 |
| `VISION_BATCH_MAX_RUNNING` | 2 | 同時執行的批次數 |

磁碟：影像會以收到時的 PNG 原樣儲存，縮小會改變檢測結果，因此 200 張全解析度相機影像可能達數百 MB。每張影像集卡片會顯示大小，超過保留數的影像集會自動移除，也可手動刪除。

## 10. 檔案與測試 {#files}

| 檔案 | 職責 |
|---|---|
| `apps/vision/batch/store.py` | 檔案、序列化、摘要與命中計算、完成、保留、graph 參數差異、AI 結果落地 |
| `apps/vision/batch/jobs.py` | 背景執行、進度、取消、自動調參模式 |
| `apps/vision/batch/insights.py` | 洞察與門檻建議（純函式） |
| `apps/vision/batch/api.py` | 端點 |
| `apps/vision/agent/consult.py` | 資料諮詢 |
| `frontend/src/pages/BatchPage.tsx`, `components/batch/*`, `lib/batch.ts` | 頁面：影像集與執行清單、結果表、標記、洞察、比較、調整與單張影像試執行（AI 諮詢與調整目前由全域助手負責） |
| `tests/test_batch.py` | 影像集、執行、標記、洞察、比較、試執行、自動調參、配方與 Golden Set、保留、刪除、權限，以及 AI 諮詢與調整落成執行 |
