# Batch testing: image sets, stored per-image results, insights and tuning

The batch page (`/batch` in the sidebar) lets you **pick a flow, run a set of images through it, and keep every image's result from every run**. Label the images with their expected OK or NG and you get a hit rate and a confusion matrix; the insights card traces the value feeding each judging node and works out a **suggested threshold**. Change parameters on the same page, run the same image set again, compare before and after, and when you are happy write the result back to the flow, save it as a recipe or send it to the editor. You can also ask the AI assistant to **consult** on the data or **tune** from it, and its result becomes another run. The page is reached from the sidebar (Inspection › Batch test); pick the flow at the top, and a "use the editor's unsaved draft" tick box appears when the editor holds unsaved changes.

## 1. The idea: image sets and runs {#concept}

- **Image set (BatchSet)**: a group of test images, uploaded or grabbed from an image source, up to `VISION_BATCH_MAX_IMAGES` (200) per set, stored on the server. **The expected label belongs to the image**, so it survives repeated runs. `flow` only records **which flow it was created under** (retention counts by it) — an image set is test data and **can be run against any flow you can see**.
- **Batch run (BatchRun)**: one pass of the image set against a graph snapshot. Per-image results (status, duration, named outputs, each node's status and scalar outputs, errors) are stored alongside a summary. A run can name a `parent` (the run it was tuned from), and `origin` is manual, draft, autotune or ai_tune. `flow` records **which flow was used this time** — the interface shows the flow name when it differs from the image set's — and empty means the image set's own flow.
- Against the Golden Set: a Golden Set is the **formal regression baseline** (few images, exact expectations, runs in CI); batch testing is the **tuning workbench** (many images, run repeatedly, data ages out). Tick images on the batch page and "Save to Golden Set" moves them across.

## 2. Working through it {#flow}

1. "New image set": upload files, or grab N images from an image source. The list spans flows, with the current test flow's sets first.
2. "Test flow" in the header is the flow to run. It arrives pre-selected from the editor, or is set to the image set's own flow when you select one. Run the same images against a different flow and both runs hang off the same image set, so you can compare them directly.
3. "Run with *flow name*": it runs in the background, the run list shows progress, and you can interrupt it. A run against a different flow is labelled with that flow's name.
4. On the Images tab, label each image OK or NG (or all OK / all NG); the Expected column on the Results tab works too. The hit rate and confusion matrix update immediately.
5. The Insights tab: missed images, failing nodes, threshold suggestions, named output distributions coloured by expectation, and the trend across runs. "Apply suggestions and re-run" produces a new run directly.
6. The Tuning tab: the on-site teaching parameters grouped for editing → "Run again" (the new run's parent is the selected one) → the Compare tab, image by image.
7. The global AI assistant in the bottom-right corner (context = batch page, once a finished run is selected): ask a question (consult) or tune from the data. The Tuning panel also has "Auto-tune". All of them produce a new run.
8. When it looks right: "Write back to flow" (engineer or administrator), "Save as recipe" (the parameter differences become a FlowRecipe) or "Send to editor" (it becomes the draft).

## 3. Data model and files (apps/vision/models.py) {#models}

| Model | Fields |
|---|---|
| `BatchSet` | `flow`, `owner`, `name`, `source` (upload or source:name), `images` JSON `[{index, name, path, width, height, expected, expect_outputs, note}]`, `image_count`, `size_bytes` and timestamps. Files live in `ASSET_DIR/batch/<set_id>/NNN.png`; deleting the set removes the directory. |
| `BatchRun` | `batch_set`, `flow` (which flow was used; empty means the image set's own, and SET_NULL if that flow is deleted), `parent`, `owner`, `flow_version`, `graph` (the snapshot actually executed, with the recipe already applied), `recipe_name`, `label` and `note`, `origin`, `status` (queued, running, done, cancelled, failed), `progress_done` and `progress_total`, `summary`, `items` (per image: `status, duration_ms, outputs, error, error_node, nodes{id:{status, duration_ms, message, branch, outputs}}` — scalars only, NaN stored as null), `insights` (a cache), `meta` (notes from auto-tuning or AI tuning), `error` and timestamps. |

Whether an image matched is not stored in items: labels can be edited afterwards, so it is computed on serialisation with `apps/golden/regress.evaluate_expect`. After a label change, `store.refresh_matches` recomputes the summary and insights of every finished run in that image set.

## 4. How runs execute (apps/vision/batch/jobs.py) {#exec}

- A background thread — at most `VISION_BATCH_MAX_RUNNING` (2) at once, and only one per image set. `runner.compiled_for(flow, graph_override=graph)` compiles once (sources and assets are opened in advance on the caller's thread) and each image goes straight through `engine.execute(...)`.
- **It does not go through the runner queue**: no flow statistics, no SSE, no FlowRun row, and no implicit default recipe (a recipe is named explicitly with `recipe_id` when the run is created). Images go into their own cache bucket, `BATCH_FLOW_ID=-1`, and each is dropped with `store.drop_run` as soon as it finishes, so a 200-image batch cannot evict the editor's preview images.
- Progress and finished rows are written back with `update()` every 10 images or 2 seconds; the interface polls once a second. "Interrupt" sets a flag, the current image finishes, and the status becomes cancelled.
- A run left in "running" by a server restart is marked failed when it is next read ("the server restarted and the run was interrupted").
- **Auto-tune mode**: coordinate descent against the image set's labels first (sampling missed images preferentially, at most 40, and never touching specifications such as tolerances, expected counts or ranges), then a full re-run with the tuned graph. `meta.autotune` records the hit rate before and after and what changed.

## 5. Insights and threshold suggestions (apps/vision/batch/insights.py) {#insights}

- Hit rate; the confusion matrix (expected NG is the positive class: tp caught, fn escaped, fp false reject, tn correct); the missed list (up to 20); which nodes errored, how often and with what message; the slowest images and the most expensive nodes; and statistics for named numeric outputs grouped by expectation and by actual result.
- **Threshold suggestions**: walk the `if_number`, `in_range` and `tolerance_judge` nodes, follow the `value` input edge back to the upstream (node, port), take that value from each image's stored node outputs, and split into an OK group and an NG group by expectation: 

  - `if_number` (gt, ge, lt, le): the direction comes from the judge the branch feeds (true → OK or true → NG). It scans the midpoints between adjacent values for the highest hit rate and only suggests one that is strictly better than the current value.
  - `in_range`: only the boundary with NG values on its side moves, to the midpoint between the NG and OK values; the other side stays.
  - `tolerance_judge`: the deviation distribution is shown but nothing is suggested — a tolerance is a specification.

- With a parent, the difference from the previous run is also computed (verdicts changed, improved, regressed, parameters altered). `text[]` is a list of readable sentences shared by offline consultation and the LLM context. `GET /batch/runs/{id}/insights` additionally returns `suggestions[]`, ready-to-apply `{node, key, value}` entries.

## 6. Tuning, writing back, recipes and the Golden Set {#tune}

- The tuning panel's working graph comes from the selected run's graph, or from the editor draft if that box is ticked. It lists only `teach=True` parameters, using the same `teachGroupsOf` as the teach page, and marks changed parameters with a blue bar.
- "Run again" is `POST /batch/sets/{id}/runs {graph, parent_run_id}`. "Write back to flow" is `PATCH /flows/{id}` (version + 1). "Save as recipe" diffs the working graph against the flow's current graph into `POST /flows/{id}/recipes`; the server also has `POST /batch/runs/{id}/to-recipe` to build a recipe straight from a run's graph.
- "Save to Golden Set" copies the image files and creates cases directly (the expectation comes from the label or from a chosen run's verdict), bypassing the image cache — so nothing can turn into "image released".

## 7. AI consultation and tuning (apps/vision/agent/consult.py) {#ai}

- **Consult**, `POST /agent/consult {batch_run_id, question, graph?}`: the rule-based insights are always computed first. When an LLM is available it receives the flow graph, the insight sentences, the per-image data (missed images first, up to 50 rows, including the values feeding the judging nodes) and up to four missed images. Its answer may end with `SUGGESTIONS: {"suggestions":[{node,key,value,reason}]}`, which the server only passes on after checking that the nodes and parameters exist and the flow is still valid. Offline, or on failure, the answer is assembled from the insight sentences by matching keywords in the question, and `suggestions` comes from the threshold suggestions.
- **Tune from data**: `POST /agent/tune`, or `POST /agent/jobs(task=tune)` in agentic mode, with a `batch_run_id`. Images are loaded from disk, the per-image data and insights are folded into the batch summary, and the tuned flow is re-run against the same image set, landing as a new run (origin=ai_tune, parent = the original). The response carries the new `batch_run_id`. Offline, an instruction that matches no rule falls back to data-driven auto-tuning as long as at least two images are labelled.
- **Auto-tune**: from the batch page it is `POST /batch/sets/{id}/runs {mode:"autotune"}` (background, interruptible), and `POST /agent/autotune` also accepts a `batch_run_id`.

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

Permissions: seeing the flow is enough to read. Creating an image set or a run needs execute permission (423 while the engine is locked). Editing labels and deleting need to be the set's creator, an engineer or an administrator; saving to a Golden Set or as a recipe needs an engineer or an administrator. The older `POST /flows/{id}/batch` and `/batch-source` (immediate batches, nothing stored) remain for API integrators.

## 9. Retention settings (.env) {#retention}

| Variable | Default | What it controls |
|---|---|---|
| `VISION_BATCH_MAX_IMAGES` | 200 | Images per set |
| `VISION_KEEP_BATCH_SETS` | 10 | Sets kept per flow; the oldest are deleted with their files, unless a run is in progress |
| `VISION_KEEP_BATCH_RUNS` | 20 | Finished runs kept per image set |
| `VISION_BATCH_MAX_RUNNING` | 2 | Batches running at once |

Disk: images are stored as PNG exactly as they came in — downscaling them would change the inspection result — so 200 full-resolution camera images can run to several hundred megabytes. Each set's card shows its size, sets beyond the retention count are removed automatically, and you can delete them by hand. 

## 10. Files and tests {#files}

| File | Responsibility |
|---|---|
| `apps/vision/batch/store.py` | Files, serialisation, the summary and match calculation, completion, retention, graph parameter diffs, landing AI results |
| `apps/vision/batch/jobs.py` | Background execution, progress, cancellation, auto-tune mode |
| `apps/vision/batch/insights.py` | Insights and threshold suggestions (pure functions) |
| `apps/vision/batch/api.py` | The endpoints |
| `apps/vision/agent/consult.py` | Data consultation |
| `frontend/src/pages/BatchPage.tsx`, `components/batch/*`, `lib/batch.ts` | The page: image set and run lists, the results table, labelling, insights, comparison, tuning and single-image preview (AI consultation and tuning now live in the global assistant) |
| `tests/test_batch.py` | Image sets, runs, labels, insights, comparison, preview, auto-tuning, recipes and Golden Set, retention, deletion, permissions, and AI consultation and tuning landing as runs |
