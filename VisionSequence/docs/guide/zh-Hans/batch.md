# 批量测试：图像集、逐张保存结果、洞察与调参

批量测试页，也就是侧栏中的 `/batch`，让您**选择一条流程，让一组图像跑过它，并保留每次执行的每张图像结果**。为图像标记期望 OK 或 NG 后，就能得到命中率与混淆矩阵；洞察卡会追踪每个判定节点的输入值，并算出**建议阈值**。您可在同一页修改参数、再次执行同一图像集、比较前后结果，满意后写回流程、存为配方或送到编辑器。也可请 AI 助手依数据**咨询**或**调整**，其结果会成为另一笔批量执行。从侧栏进入此页，位置是「检测 › 批量测试」；在顶部选流程，若编辑器有未保存变更，会出现「使用编辑器未保存草稿」复选框。

## 1. 概念：图像集与执行 {#concept}

- **图像集 (BatchSet)**：一组测试图像，可上传或从图像来源采集，每组最多 `VISION_BATCH_MAX_IMAGES`（200）张，保存在服务端。**期望标记属于图像**，因此会保留到重复执行之后。`flow` 只记录**建立时所属的流程**，保留策略依它计算；图像集是测试数据，**可拿来测任何您看得到的流程**。
- **批量执行 (BatchRun)**：图像集针对一份 graph 快照的一次执行。逐张结果（状态、耗时、具名输出、每个节点的状态与标量输出、错误）会与摘要一起保存。执行可指定 `parent`，也就是被调整前的执行；`origin` 为 manual、draft、autotune 或 ai_tune。`flow` 记录**此次使用的流程**，当它与图像集流程不同时，界面会显示流程名称；空值代表使用图像集自己的流程。
- 与 Golden Set 的差异：Golden Set 是**正式回归基准**，通常图像较少、有精确期望、可在 CI 中执行；批量测试是**调参工作台**，图像可多次反复执行，数据会依保留策略过期。在批量页勾选图像并「保存到 Golden Set」即可移入正式基准。

## 2. 操作流程 {#flow}

1. 「新建图像集」：上传文件，或从图像来源采集 N 张图像。列表跨流程显示，当前测试流程的图像集排在前面。
2. 标头中的「测试流程」就是要执行的流程。从编辑器进入时会预先选取，选定图像集后则设为图像集自己的流程。改选另一条流程再执行时，两笔执行仍挂在同一图像集下，因此能直接比较。
3. 「以 *流程名称* 执行」：后台执行，执行列表显示进度，且可中断。若执行不同流程，该笔执行会标示该流程名称。
4. 在「图像」分页，为每张图像标记 OK 或 NG，也可全部 OK / 全部 NG；「结果」分页的 Expected 栏也可编辑。命中率与混淆矩阵会立即更新。
5. 「洞察」分页：漏检图像、失败节点、阈值建议、依期望分组的具名输出分布，以及跨执行趋势。「套用建议并重新执行」会直接产生新执行。
6. 「调整」分页：依分组编辑现场教导参数 →「再次执行」（新执行的 parent 是当前选取的执行）→「比较」分页逐张对照。「比较」分页最上方有「将 … 与下列执行比较」下拉，列出同一图像集其他已完成的执行；执行纪录里的比较图标也是同一件事。
7. 右下角全局 AI 助手（context = 批量页，且已选取完成的执行）：提问即可咨询数据，或给出调参指令。调整面板也有「自动调参」。这些操作都会产生新执行。
8. 结果正确后：「写回流程」（工程师或管理员）、「存为配方」（参数差异成为 FlowRecipe）或「送到编辑器」（成为草稿）。

## 3. 数据模型与文件 (apps/vision/models.py) {#models}

| 模型 | 字段 |
|---|---|
| `BatchSet` | `flow`、`owner`、`name`、`source`（upload 或 source:name）、`images` JSON `[{index, name, path, width, height, expected, expect_outputs, note}]`、`image_count`、`size_bytes` 与时间戳。文件位于 `ASSET_DIR/batch/<set_id>/NNN.png`；删除图像集会移除该目录。 |
| `BatchRun` | `batch_set`、`flow`（此次使用的流程；空值代表图像集自己的流程，且该流程删除时 SET_NULL）、`parent`、`owner`、`flow_version`、`graph`（实际执行的快照，已套用配方）、`recipe_name`、`label` 与 `note`、`origin`、`status`（queued、running、done、cancelled、failed）、`progress_done` 与 `progress_total`、`summary`、`items`（逐张图像：`status, duration_ms, outputs, error, error_node, nodes{id:{status, duration_ms, message, branch, outputs}}`，只存标量，NaN 存成 null）、`insights`（缓存）、`meta`（自动调参或 AI 调参备注）、`error` 与时间戳。 |

图像是否命中不存于 items：标记日后可编辑，因此序列化时由 `apps/golden/regress.evaluate_expect` 计算。标记变更后，`store.refresh_matches` 会重新计算该图像集内每个已完成执行的摘要与洞察。

## 4. 执行方式 (apps/vision/batch/jobs.py) {#exec}

- 后台线程处理，同时最多 `VISION_BATCH_MAX_RUNNING`（2）笔，而且同一图像集一次只跑一笔。`runner.compiled_for(flow, graph_override=graph)` 只编译一次，来源与资产会在调用者线程预先打开，接着每张图像直接进 `engine.execute(...)`。
- **不走 runner 队列**：不写流程统计、不送 SSE、不写 FlowRun 行，也不套用隐含默认配方，配方只在建立执行时以 `recipe_id` 明确指定。图像进入自己的缓存桶 `BATCH_FLOW_ID=-1`，完成后立即由 `store.drop_run` 丢弃，因此 200 张图像的批量不会挤掉编辑器试执行图像。
- 进度与完成数据每 10 张或每 2 秒以 `update()` 写回；界面每秒轮询一次。「中断」会设置标志，当前图像跑完后状态变为 cancelled。
- 服务端重启后残留在 running 的执行，下次读取时会标为 failed（「服务端已重新启动，执行遭中断」）。
- **自动调参模式**：先依图像集标记做坐标下降，优先抽样漏检图像，最多 40 张，且永远不动规格类参数，如公差、期望数量或范围；接着用调整后 graph 完整重跑。`meta.autotune` 记录前后命中率与变更内容。

## 5. 洞察与阈值建议 (apps/vision/batch/insights.py) {#insights}

- 命中率；混淆矩阵，期望 NG 是正类：tp 命中、fn 漏出、fp 误判、tn 正确；漏检列表，最多 20 张；哪些节点出错、出错次数与消息；最慢图像与最耗时节点；以及依期望与实际结果分组的具名数值输出统计。
- **阈值建议**：走访 `if_number`、`in_range` 与 `tolerance_judge` 节点，沿着 `value` 输入连线回到上游 `(node, port)`，从每张图像保存的节点输出中取该值，并依期望分成 OK 组与 NG 组：

  - `if_number`（gt、ge、lt、le）：方向由该分支通往的 judge 决定（true → OK 或 true → NG）。它扫描相邻数值中点，找出最高命中率，且只在严格优于当前值时提出建议。
  - `in_range`：只移动 NG 值所在侧的边界，移到 NG 与 OK 值之间的中点；另一侧保持不变。
  - `tolerance_judge`：显示偏差分布，但不提出建议，因为公差是规格。

- 若有 parent，也会计算与前一次执行的差异（判定改变、进步、退步、参数改动）。`text[]` 是离线咨询与 LLM 上下文共用的可读句子列表。`GET /batch/runs/{id}/insights` 另外返回 `suggestions[]`，内容是可直接套用的 `{node, key, value}` 项目。

## 6. 调整、写回、配方与 Golden Set {#tune}

- 调整面板的工作 graph 来自所选执行的 graph，或在勾选时来自编辑器草稿。它只列出 `teach=True` 参数，使用与参数卡相同的 `teachGroupsOf`，并以蓝色条标示已变更参数。
- 「再次执行」是 `POST /batch/sets/{id}/runs {graph, parent_run_id}`。「写回流程」是 `PATCH /flows/{id}`，版本 + 1。「存为配方」会比较工作 graph 与流程当前 graph 的差异，送进 `POST /flows/{id}/recipes`；服务端也有 `POST /batch/runs/{id}/to-recipe` 可直接从执行 graph 建配方。
- 「保存到 Golden Set」会直接复制图像文件并建立案例，期望来自标记或所选执行的判定，绕过图像缓存，因此不会变成「图像已释放」。

## 7. AI 咨询与调整 (apps/vision/agent/consult.py) {#ai}

- **咨询**，`POST /agent/consult {batch_run_id, question, graph?}`：一定先计算规则型洞察。有 LLM 可用时，它会收到流程 graph、洞察句子、逐张数据（漏检图像优先，最多 50 行，含判定节点输入值）与最多四张漏检图像。回复可在结尾带 `SUGGESTIONS: {"suggestions":[{node,key,value,reason}]}`，服务端会确认节点与参数存在且流程仍有效后才交给前端。离线或失败时，答案由洞察句子依问题关键词组合，`suggestions` 来自阈值建议。
- **依数据调整**：`POST /agent/tune`，或代理模式中的 `POST /agent/jobs(task=tune)`，带 `batch_run_id`。图像从磁盘载入，逐张数据与洞察会折入批量摘要，调整后流程再跑同一图像集，落成新执行（origin=ai_tune，parent = 原执行）。响应带新的 `batch_run_id`。离线时，若指令不符合规则，只要至少两张图像有标记，就会退回数据驱动自动调参。
- **自动调参**：批量页调用 `POST /batch/sets/{id}/runs {mode:"autotune"}`，后台且可中断；`POST /agent/autotune` 也接受 `batch_run_id`。

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

权限：能看到流程即可读取。建立图像集或执行需要执行权限，引擎锁定时为 423。编辑标记与删除需要是图像集建立者、工程师或管理员；保存到 Golden Set 或存为配方需要工程师或管理员。较旧的 `POST /flows/{id}/batch` 与 `/batch-source`，也就是立即批量且不保存结果的端点，仍保留给 API 集成方。

## 9. 保留设置 (.env) {#retention}

| 变量 | 默认值 | 控制内容 |
|---|---|---|
| `VISION_BATCH_MAX_IMAGES` | 200 | 每组图像数 |
| `VISION_KEEP_BATCH_SETS` | 10 | 每条流程保留的图像集数；最旧者会连同文件删除，除非有执行进行中 |
| `VISION_KEEP_BATCH_RUNS` | 20 | 每个图像集保留的已完成执行数 |
| `VISION_BATCH_MAX_RUNNING` | 2 | 同时执行的批量数 |

磁盘：图像会以收到时的 PNG 原样保存，缩小会改变检测结果，因此 200 张全分辨率相机图像可能达数百 MB。每张图像集卡片会显示大小，超过保留数的图像集会自动移除，也可手动删除。

## 10. 文件与测试 {#files}

| 文件 | 职责 |
|---|---|
| `apps/vision/batch/store.py` | 文件、序列化、摘要与命中计算、完成、保留、graph 参数差异、AI 结果落地 |
| `apps/vision/batch/jobs.py` | 后台执行、进度、取消、自动调参模式 |
| `apps/vision/batch/insights.py` | 洞察与阈值建议（纯函数） |
| `apps/vision/batch/api.py` | 端点 |
| `apps/vision/agent/consult.py` | 数据咨询 |
| `frontend/src/pages/BatchPage.tsx`, `components/batch/*`, `lib/batch.ts` | 页面：图像集与执行列表、结果表、标记、洞察、比较、调整与单张图像试执行（AI 咨询与调整当前由全局助手负责） |
| `tests/test_batch.py` | 图像集、执行、标记、洞察、比较、试执行、自动调参、配方与 Golden Set、保留、删除、权限，以及 AI 咨询与调整落成执行 |
