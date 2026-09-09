# Golden Set regression, flow export and import, and the CLI

The goal: **change one threshold and know within minutes which images went from PASS to FAIL**. Flows can live in git, be code reviewed and run in CI. The database is still the authority at run time.

## 1. The idea {#concept}

- **Golden case**: one image plus an expected result (`expect_status`: ok, ng or any, and optionally `expect_outputs`). The image lands in `ASSET_DIR/golden/<flow_id>/<uuid>.png` and **never enters the image cache**; regression reads it straight from the path.
- **Regression**: run every golden case for the flow **outside preview mode** — no intermediate images are kept, so hundreds of images will not blow up memory — compare each result against its expectation to get match or mismatch, and compare against the last **baseline** to get regressed and improved. Only mismatched cases are re-run in preview to get an image ref for the interface, capped at 20.
- **Baseline**: a snapshot of every case's result at the flow version the regression ran on (`{case_id: {status, outputs, duration_ms}}`). `save_baseline` simply adds a row; the newest one is what comparisons use.

## 2. Data model (apps/golden/models.py) {#models}

| Model | Fields | Notes |
|---|---|---|
| GoldenCase | id, flow FK, name, image_path, expect_status (ok｜ng｜any), expect_outputs JSON, note, created_at | Deleting a case deletes its image file. Deleting a flow cascades (the files stay on disk; clear `golden/<flow_id>` by hand if you want). |
| GoldenBaseline | flow FK, flow_version, results JSON, created_at | Every `save_baseline` adds a row; `GoldenBaseline.latest_for(flow_id)` returns the newest. |

## 3. Expectations and how they are compared {#expect}

A case **matches** when:

1. If `expect_status` is `ok` or `ng`, the run's status is the same (`failed` never matches). `any` skips the status check.
2. Every key in `expect_outputs` appears in the run's named outputs (from the `output` tool) and agrees:

```
{"hole_count": 5,                          // equality: numbers compared as float; strings, bools and lists compared directly
 "width_mm":  {"value": 12.4, "tol": 0.2},  // numeric tolerance: |now - 12.4| <= 0.2
 "code":      {"value": "A123"}}            // value on its own is fine too
```

The **confusion matrix** takes `expect_status` as ground truth with `ng` as the positive class; a prediction of "not ok" (ng or failed) counts as positive. Cases with `expect_status=any` are excluded.

|  | predicted ng / failed | predicted ok |
|---|---|---|
| expected ng | tp | fn — an escape, the worst outcome |
| expected ok | fp — a false reject | tn |

## 4. Golden Set API {#api}

Permissions follow the flow rules: **anyone who can see the flow can view and run** (`_visible_flows`), **an engineer or administrator can add, edit, delete and save a baseline** (`_editable_flow`), and running first checks `principal.can_execute()` (423 while the engine is locked).

| Method and path | What it does |
|---|---|
| `GET /api/vision/flows/{id}/golden` | `{items:[{id, name, expect_status, expect_outputs, note, created_at, image_url}], total, can_manage, baseline_version, baseline_at, flow_version}` |
| `POST /api/vision/flows/{id}/golden` (multipart) | `images[]` (up to 200) plus optional form fields `expect_status`, `note`, `expect_outputs` (a JSON string). One case per image, named after the file. Returns 201 with `{items, created}`. |
| `POST /api/vision/flows/{id}/golden` (JSON) | `{"from_batch": [{"image_ref", "name", "expect_status", "expect_outputs", "note"}]}` — build cases from image refs returned by a batch run, as long as they are still in the image cache. If any ref has expired the whole request returns 404 `image_gone` and nothing is created. |
| `GET /api/vision/flows/{id}/golden/baseline` | `{baseline: {id, flow_version, results, created_at, case_count} \| null, flow_version, case_count}` |
| `GET /api/vision/flows/{id}/golden/{case_id}/image?max=&fmt=&q=` | Thumbnail or full image, JPEG or PNG. Meant for an `<img>` tag, so it accepts `?token=` or `?api_key=`. |
| `PATCH /api/vision/flows/{id}/golden/{case_id}` | `{name?, expect_status?, expect_outputs?, note?}` |
| `DELETE /api/vision/flows/{id}/golden/{case_id}` | 204, and the image file is deleted. |
| `POST /api/vision/flows/{id}/regress` | `{graph?, save_baseline?, fail_under?}` → the regression report below. `graph` may be the unsaved graph from the editor, exactly like preview. `fail_under` is 0 to 1 and only affects `passed`. |

## 5. The regression report {#regress}

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

- **regressed**: the baseline result met the expectation and this one does not. **improved** is the reverse. Both evaluate the baseline result against the *current* expectation, so editing a case's expectation cannot produce a false regression.
- `node`: the node that errored (status error), or the first node that judged ng. `error` is that node's message.
- `changed_since_baseline`: status or outputs differ from the baseline; null when there is no baseline.
- `image_ref` only exists for mismatched cases, up to 20 of them; fetch it with `GET /api/vision/images/{ref}`. The golden image itself is always available through `image_url`.
- Regression runs go into the statistics and FlowRun with `trigger="regress"` (subject to `PERSIST_RUNS`); the preview re-runs are not recorded.

### Auto-tuning {#autotune}

"Auto-tune" on the Golden Set page (`POST /flows/{id}/golden/autotune`, body `{graph?, max_evals?, deadline_s?}`) uses every case's expected status and expected outputs as labels and runs a coordinate-descent search over the on-site teaching parameters (`teach=True`; tolerances, ranges and expected counts are left alone) of the flow, or of an unsaved draft graph. A change is only kept if it is strictly better. It returns `{graph, before:{match,total}, after, change_text[], evals, elapsed_ms, improved, budget_hit, cases, skipped[]}`. It does not write back to the flow: "Send to editor" puts the result in the draft so you can review it before saving. Details in [AI assistant › Auto-tuning](agent.md#candidates).

## 6. CLI: manage.py regress {#cli-regress}

```
manage.py regress <flow_id|name> [--fail-under 0.98] [--json] [--save-baseline] [--graph file.flow.json --source <id>]
```

| Exit code | Meaning |
|---|---|
| 0 | Match rate at or above the threshold (`--fail-under` defaults to 1.0, so any mismatch fails) |
| 1 | Match rate below the threshold |
| 3 | The flow has no golden cases |

The text output leads with the **REGRESSED** list — which images went from PASS to FAIL, and at which node. `--json` prints the full report instead. `--graph` replaces the graph in the database with the one in an export file, which is how you check a flow changed in a pull request.

## 7. The flow export format (apps/vision/serialize.py) {#export}

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

The serialisation is **stable**, so that `git diff` means something:

- Top-level keys are in a fixed order. Node keys go `id, type, label, description, enabled, continue_on_error, color, params, position, width, height` and then alphabetically; `params` is sorted by key, recursively; edge keys go `id, source, source_handle, target, target_handle`.
- Nodes are sorted by `id` and edges by `(source, target, source_handle, target_handle)`, so dragging on the canvas or reconnecting an edge produces no diff.
- `position` (and width and height) are rounded to integers, so nudging a node produces no diff.
- `image_source.source_id` becomes the placeholder `{SOURCE}` — the same `templatize` the template gallery uses — and is substituted back on import via `--source` or `source_id`. Without one: a newly created flow gets an empty string (it can still run with a pushed image), and **updating an existing flow keeps the source already configured on its acquire step** (same node id first, otherwise any acquire step), so an import never wipes the source someone set up on the line.
- The graph goes through `validate_graph` first, so omitted `source_handle` and `target_handle` values are filled in before export.
- Two-space indent, `ensure_ascii=False`, UTF-8 without BOM, LF, one trailing newline.
- `exported_at` is the real export time. For byte-identical reproducibility set `SOURCE_DATE_EPOCH=<unix seconds>`, following the reproducible-builds convention. `tests/test_flow_cli.py` uses it to verify that export → import → export produces identical bytes.

Import does not change the graph JSON format, and does not move Flow.graph out of the database: the file is only a stable projection of what the database holds. 

## 8. CLI: manage.py flow {#cli-flow}

```
manage.py flow export <id|name> -o flows/hole_count.flow.json     # without -o it prints to stdout
manage.py flow import flows/hole_count.flow.json [--source 3] [--owner kevin]
manage.py flow run <id|name|file> [--source 3] [--images ./samples] [--json]
```

- **import** upserts on `name`: an existing flow has its graph, description and interval updated and `version` incremented; otherwise one is created (`--owner` sets the owner, and without it the flow is shared). A schema_version mismatch, a missing source or a missing file all end in a CommandError.
- **run** takes a flow from the database or a `.flow.json` file directly (not written to the database — it runs as a graph override). With `--images` pointing at a folder, every image is run once as `input_image`, outside preview, printing `status ms filename outputs` per image; otherwise it runs once using the flow's own source. `--json` prints `{flow, items[], total, ok, ng, failed}`. Any failure, including an image that cannot be decoded, exits with code 2.
- These runs carry the trigger `cli` and do go into the statistics and FlowRun.

## 9. Export and import API (apps/vision/api_flowio.py) {#flow-api}

| Method and path | What it does |
|---|---|
| `GET /api/vision/flows/{id}/export` | The same JSON as a download, with `Content-Disposition: attachment; filename="<name>.flow.json"`. `?download=0` omits the download header. Anyone who can see the flow can export it. |
| `POST /api/vision/flows/import` | JSON body: the whole export document (optionally with `source_id`), or `{"doc": {...}, "source_id": 3}`. Multipart: `file` plus a `source_id` form field. Returns `{flow, created}` — 201 when created, 200 when updated. Updating an existing flow requires an engineer or administrator (otherwise 404); a newly created flow is owned by the caller. |

Route order: `/flows/import` must be registered before `/flows/{flow_id}`, because ninja path parameters carry no type conversion — which is why `config/api.py` mounts the flow-io and golden routers ahead of the vision router. 

## 10. Running it in CI {#ci}

```
# 1. Import the flow file into a clean test database, pointing at the CI source
#    (or leave the source out and push images with --images)
manage.py migrate
manage.py flow import flows/hole_count.flow.json
# 2. Create the golden images through the API (or restore ASSET_DIR/golden and the database from a backup)
# 3. Regress; fail the pipeline below 0.98
manage.py regress hole_count --fail-under 0.98 --json > regress.json
```

When a pull request only changes a `.flow.json`, skip the import and run `manage.py regress hole_count --graph flows/hole_count.flow.json --source 3` to test the graph from the pull request against the existing golden set.

## 11. Files and tests {#files}

| File | Contents |
|---|---|
| `apps/golden/models.py`, `migrations/0001_initial.py` | GoldenCase, GoldenBaseline |
| `apps/golden/regress.py` | Image access, the comparison rules, `run_regression()` shared by the API and the CLI |
| `apps/golden/api.py` | The Golden Set and regress endpoints |
| `apps/golden/management/commands/regress.py` | `manage.py regress` |
| `apps/vision/serialize.py` | Stable serialisation, parse, import_flow, find_flow |
| `apps/vision/api_flowio.py` | The export and import endpoints |
| `apps/vision/management/commands/flow.py` | `manage.py flow export\|import\|run` |
| `tests/test_golden.py`, `tests/test_flow_cli.py` | Upload, building from a batch, the image endpoint, comparison rules, the regression report and baselines, CLI exit codes and permissions; the export format, byte-identical round trips, upsert on import, run against a folder or a file, and the API |
