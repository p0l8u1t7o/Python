# Golden Set 回归、流程导出与导入，以及 CLI

目标：**改一个阈值后，在数分钟内知道哪些图像从 PASS 变成 FAIL**。流程可放在 git 中、接受 code review，并在 CI 中执行。执行时的权威来源仍是数据库。

## 1. 概念 {#concept}

- **Golden case**：一张图像加上一份期望结果（`expect_status`：ok、ng 或 any，并可选填 `expect_outputs`）。图像会落在 `ASSET_DIR/golden/<flow_id>/<uuid>.png`，且**永远不进图像缓存**；回归会直接从路径读取。
- **回归**：对该流程的每个 golden case 在**非试执行模式**执行，不保留中间图像，因此数百张图像不会撑爆内存；接着把每笔结果与期望比对得到 match 或 mismatch，再与上一个**基准**比对得到退步与进步。只有 mismatch 案例会再用 preview 重跑以取得界面图像 ref，最多 20 笔。
- **基准**：在回归所用流程版本下，每个案例结果的快照（`{case_id: {status, outputs, duration_ms}}`）。`save_baseline` 只会新增一行；最新行就是比对使用的基准。

## 2. 数据模型 (apps/golden/models.py) {#models}

| 模型 | 字段 | 备注 |
|---|---|---|
| GoldenCase | id, flow FK, name, image_path, expect_status (ok｜ng｜any), expect_outputs JSON, note, created_at | 删除案例会删除其图像文件。删除流程会 cascade，文件仍留在磁盘；若需要可手动清除 `golden/<flow_id>`。 |
| GoldenBaseline | flow FK, flow_version, results JSON, created_at | 每次 `save_baseline` 都新增一行；`GoldenBaseline.latest_for(flow_id)` 返回最新行。 |

## 3. 期望与比对方式 {#expect}

案例在以下条件下为**命中**：

1. 若 `expect_status` 是 `ok` 或 `ng`，执行状态必须相同（`failed` 永远不命中）。`any` 会略过状态检查。
2. `expect_outputs` 中的每个 key 都必须出现在执行的具名输出（来自 `output` 工具）中，且符合：

```
{"hole_count": 5,                          // equality: numbers compared as float; strings, bools and lists compared directly
 "width_mm":  {"value": 12.4, "tol": 0.2},  // numeric tolerance: |now - 12.4| <= 0.2
 "code":      {"value": "A123"}}            // value on its own is fine too
```

**混淆矩阵**以 `expect_status` 作为 ground truth，且 `ng` 是正类；预测为「not ok」（ng 或 failed）时计为正类。`expect_status=any` 的案例会排除。

|  | 预测 ng / failed | 预测 ok |
|---|---|---|
| 期望 ng | tp | fn — 漏出，最严重结果 |
| 期望 ok | fp — 误判 | tn |

## 4. Golden Set API {#api}

权限依流程规则：**任何看得到流程的人都可查看与执行**（`_visible_flows`），**工程师或管理员可新增、编辑、删除与保存基准**（`_editable_flow`），执行前会先检查 `principal.can_execute()`，引擎锁定时返回 423。

| 方法与路径 | 功能 |
|---|---|
| `GET /api/vision/flows/{id}/golden` | `{items:[{id, name, expect_status, expect_outputs, note, created_at, image_url}], total, can_manage, baseline_version, baseline_at, flow_version}` |
| `POST /api/vision/flows/{id}/golden` (multipart) | `images[]`（最多 200 张）加上选填表单字段 `expect_status`、`note`、`expect_outputs`（JSON 字符串）。每张图像建立一个案例，以文件名命名。返回 201 与 `{items, created}`。 |
| `POST /api/vision/flows/{id}/golden` (JSON) | `{"from_batch": [{"image_ref", "name", "expect_status", "expect_outputs", "note"}]}` — 从批量执行返回的 image ref 建立案例，前提是 ref 仍在图像缓存中。若任一 ref 已过期，整个请求返回 404 `image_gone`，且不建立任何案例。 |
| `GET /api/vision/flows/{id}/golden/baseline` | `{baseline: {id, flow_version, results, created_at, case_count} \| null, flow_version, case_count}` |
| `GET /api/vision/flows/{id}/golden/{case_id}/image?max=&fmt=&q=` | 缩略图或完整图像，JPEG 或 PNG。供 `<img>` 标签使用，因此接受 `?token=` 或 `?api_key=`。 |
| `PATCH /api/vision/flows/{id}/golden/{case_id}` | `{name?, expect_status?, expect_outputs?, note?}` |
| `DELETE /api/vision/flows/{id}/golden/{case_id}` | 204，且图像文件会删除。 |
| `POST /api/vision/flows/{id}/regress` | `{graph?, save_baseline?, fail_under?}` → 下方的回归报告。`graph` 可为编辑器未保存 graph，与 preview 相同。`fail_under` 为 0 到 1，只影响 `passed`。 |

## 5. 回归报告 {#regress}

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

- **regressed**：基准结果原本符合期望，但此次不符合。**improved** 则相反。两者都会用*当前*期望评估基准结果，因此编辑案例期望不会制造假退步。
- `node`：出错的节点（status error），或第一个判定 ng 的节点。`error` 是该节点的消息。
- `changed_since_baseline`：状态或输出与基准不同；没有基准时为 null。
- `image_ref` 只出现在 mismatch 案例，最多 20 笔；用 `GET /api/vision/images/{ref}` 取得。Golden 图像本身永远可通过 `image_url` 取得。
- 回归执行会进入统计与 FlowRun，`trigger="regress"`，受 `PERSIST_RUNS` 控制；preview 重跑不会记录。

### 自动调参 {#autotune}

Golden Set 页上的「自动调参」（`POST /flows/{id}/golden/autotune`，body `{graph?, max_evals?, deadline_s?}`）会把每个案例的期望状态与期望输出当作标记，对流程或未保存草稿 graph 的现场教导参数（`teach=True`）执行坐标下降搜索；公差、范围与期望数量会保留。只有严格更好的变更才会保留。它返回 `{graph, before:{match,total}, after, change_text[], evals, elapsed_ms, improved, budget_hit, cases, skipped[]}`。它不会写回流程：「送到编辑器」会把结果放进草稿，供您检查后再保存。详见 [AI 助手 › 自动调参](agent.md#candidates)。

## 6. CLI：manage.py regress {#cli-regress}

```
manage.py regress <flow_id|name> [--fail-under 0.98] [--json] [--save-baseline] [--graph file.flow.json --source <id>]
```

| 退出码 | 含义 |
|---|---|
| 0 | 命中率达到或高于阈值（`--fail-under` 默认为 1.0，因此任何 mismatch 都会失败） |
| 1 | 命中率低于阈值 |
| 3 | 流程没有 golden cases |

文字输出会先列出 **REGRESSED** 列表，也就是哪些图像从 PASS 变 FAIL，以及在哪个节点。`--json` 则输出完整报告。`--graph` 会用导出文件中的 graph 取代数据库中的 graph，这是检查 pull request 中流程变更的方式。

## 7. 流程导出格式 (apps/vision/serialize.py) {#export}

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

序列化是**稳定的**，因此 `git diff` 才有意义：

- 顶层 key 依固定顺序排列。节点 key 依序为 `id, type, label, description, enabled, continue_on_error, color, params, position, width, height`，再接字母排序；`params` 会递归依 key 排序；edge key 依序为 `id, source, source_handle, target, target_handle`。
- 节点依 `id` 排序，edge 依 `(source, target, source_handle, target_handle)` 排序，因此在画布上拖拽或重接线不会产生 diff。
- `position`（以及 width、height）会四舍五入成整数，因此微移节点不会产生 diff。
- `image_source.source_id` 会变成 `{SOURCE}` 占位符，也就是模板画廊使用的同一套 `templatize`，导入时再通过 `--source` 或 `source_id` 替换。若未提供：新建流程会得到空字符串，仍可用 pushed image 执行；**更新既有流程会保留产线已设置在采集步骤上的来源**，先找相同 node id，否则找任一采集步骤，所以导入不会抹掉现场设置好的来源。
- graph 会先通过 `validate_graph`，因此省略的 `source_handle` 与 `target_handle` 会在导出前补齐。
- 两空格缩进、`ensure_ascii=False`、UTF-8 无 BOM、LF、文件尾一个换行。
- `exported_at` 是实际导出时间。若需 byte-identical reproducibility，请依 reproducible-builds 惯例设置 `SOURCE_DATE_EPOCH=<unix seconds>`。`tests/test_flow_cli.py` 会用它验证 export → import → export 产生相同 bytes。

导入不会改变 graph JSON 格式，也不会把 Flow.graph 搬出数据库：文件只是数据库内容的稳定投影。

## 8. CLI：manage.py flow {#cli-flow}

```
manage.py flow export <id|name> -o flows/hole_count.flow.json     # without -o it prints to stdout
manage.py flow import flows/hole_count.flow.json [--source 3] [--owner kevin]
manage.py flow run <id|name|file> [--source 3] [--images ./samples] [--json]
```

- **import** 以 `name` upsert：既有流程会更新 graph、description 与 interval，并让 `version` 加一；否则建立新流程（`--owner` 设置拥有者，未提供则流程为共享）。schema_version 不符、source 缺失或文件缺失都会以 CommandError 结束。
- **run** 可直接使用数据库中的流程或 `.flow.json` 文件，后者不写入数据库，而是以 graph override 执行。`--images` 指向文件夹时，每张图像都会以 `input_image` 执行一次，不走 preview，并逐张印出 `status ms filename outputs`；否则使用流程自己的来源执行一次。`--json` 印出 `{flow, items[], total, ok, ng, failed}`。任何失败，包含图像无法解码，都以退出码 2 结束。
- 这些执行的 trigger 为 `cli`，且会进入统计与 FlowRun。

## 9. 导出与导入 API (apps/vision/api_flowio.py) {#flow-api}

| 方法与路径 | 功能 |
|---|---|
| `GET /api/vision/flows/{id}/export` | 与下载相同的 JSON，并带 `Content-Disposition: attachment; filename="<name>.flow.json"`。`?download=0` 会省略下载标头。任何看得到流程的人都可导出。 |
| `POST /api/vision/flows/import` | JSON body：整份导出文档（可选带 `source_id`），或 `{"doc": {...}, "source_id": 3}`。Multipart：`file` 加上 `source_id` 表单字段。返回 `{flow, created}`；建立时为 201，更新时为 200。更新既有流程需要工程师或管理员权限，否则返回 404；新建流程归调用者所有。 |

路由顺序：`/flows/import` 必须注册在 `/flows/{flow_id}` 之前，因为 ninja path parameters 不做类型转换，这也是 `config/api.py` 把 flow-io 与 golden router 挂在 vision router 前面的原因。

## 10. 在 CI 中执行 {#ci}

```
# 1. Import the flow file into a clean test database, pointing at the CI source
#    (or leave the source out and push images with --images)
manage.py migrate
manage.py flow import flows/hole_count.flow.json
# 2. Create the golden images through the API (or restore ASSET_DIR/golden and the database from a backup)
# 3. Regress; fail the pipeline below 0.98
manage.py regress hole_count --fail-under 0.98 --json > regress.json
```

当 pull request 只变更 `.flow.json` 时，可略过导入，改用 `manage.py regress hole_count --graph flows/hole_count.flow.json --source 3` 直接拿 pull request 中的 graph 测既有 Golden Set。

## 11. 文件与测试 {#files}

| 文件 | 内容 |
|---|---|
| `apps/golden/models.py`, `migrations/0001_initial.py` | GoldenCase、GoldenBaseline |
| `apps/golden/regress.py` | 图像访问、比对规则、API 与 CLI 共用的 `run_regression()` |
| `apps/golden/api.py` | Golden Set 与 regress 端点 |
| `apps/golden/management/commands/regress.py` | `manage.py regress` |
| `apps/vision/serialize.py` | 稳定序列化、parse、import_flow、find_flow |
| `apps/vision/api_flowio.py` | 导出与导入端点 |
| `apps/vision/management/commands/flow.py` | `manage.py flow export\|import\|run` |
| `tests/test_golden.py`, `tests/test_flow_cli.py` | 上传、从批量建立、图像端点、比对规则、回归报告与基准、CLI 退出码与权限；导出格式、byte-identical round trips、导入 upsert、用文件夹或文件执行，以及 API |
