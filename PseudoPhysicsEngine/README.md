# CellForge

CellForge is a local-first engineering workspace for building and reviewing articulated
manufacturing-cell simulations. Engineering truth stays in YAML, CadQuery modules, and vendor
URDF/STEP; each build produces a named STEP assembly, hierarchical GLB, sampled timeline, and L1
evidence.

## Python setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## CLI smoke test

```powershell
cell validate --project examples/getac_qc/handwritten
cell build --project examples/getac_qc/handwritten --level L0
cell snapshot --project examples/getac_qc/handwritten --t 40 --cam iso
```

## Articulated simulation and L1 workflow

```powershell
# Traceable vendor source or an explicit approximation
cell vendor add-urdf vs060 <urdf-or-url> --file <mesh> --file <mesh> ... `
  --flange-link J6 --source-url <vendor page> --project <project>
cell vendor stub denso_vs060 --project <project> --reach-mm 905 --payload-kg 7
cell vendor add camera_model <file-or-url> --kind sensor --project <project>

# Named CAD, IK motion, 20 ms signed-distance samples, and immutable version
cell build --project <project> --level L1
cell checks --project <project>
cell diff v1 v2 --project <project>

# Complete customer pack: STEP, DXF, BOM, DOCX, PPTX, HTML, MP4
cell export --project <project> --kinds all
```

Vendor modules take their kinematics and shape from the vendor files (D-036). A URDF supplies the
chain (metres/radians converted to mm/degrees, revolute/prismatic/continuous/fixed in any order,
e.g. SCARA stays four-axis), per-link visual meshes (STL/OBJ/DAE, faceted into the STEP and cached
by mesh hash) and `<collision>` geometry; the registered flange link/offset and the tool's TCP are
fixed links on the same chain, so GLB nodes, sampling, collision parts, and frames share one FK. A
STEP or mesh alone is a static module and can never be a robot actor. Every vendor file keeps its
own SHA-256 and validation fails when one changes. Parametric catalogue approximations
(`library/robot_stub.py`, `approximated: true` vendor entries) are marked `approximated` in the
build warnings, version manifest, GLB extras, check items, the check panel, and the report.

Products may consist of several parts (`workpiece.yaml` → `parts`, D-037): each part is a SKU
box or a CadQuery part module with its own frames, state axes (e.g. a connector's tilt), mass, and
initial frame. Every part has exactly one holder at any time (a module, a robot tool, or another
part) and follows its holder; steps name the part they act on with `object`/`objects`. Action
contracts `pick`, `place`, `insert`, `press`, and `inspect` (D-038, D-039) combine primitive moves,
check their preconditions, and record `timeline.action_results` with fixed failure codes; `press`
flattens tilted parts with a limited-stroke spring model, and `inspect` judges field of view, depth
of field, mm/px, and occlusion from `ModuleDef.cameras`. Legal contacts are declared in
`process.yaml` → `contacts` (pair, step window, tolerance, region, approach axis) and are allowed
only inside that declaration. `cell snapshot --cam <module>.<camera frame>` renders a device camera.
`examples/ssd_press/handwritten` is the USB-connector press case (ACC-04).

Costing (D-040) lives in `costing.yaml`: an item catalogue (kind, subsystem, unit, price with
currency, source, quote date, validity, trust, grade and ± range, optional components), equipment
rules that price every matching module instance (so adding a camera module adds its camera cost),
fixed BOM lines, labour rates and tasks, exchange rates, and a policy (overhead, contingency, tax,
rounding stages, and an explicit `margin` or `markup` pricing method; without one only the budget
is produced). Builds write a versioned `costing.json`; `GET /api/projects/{p}/versions/{v}/costing`
serves it, the web 成本 tab summarises it, and `cell export --kinds costing,purchase_bom` writes an
XLSX with live formulas plus a merged purchase BOM CSV. Missing prices are listed and never counted
as zero; an item counted twice for the same module, or a priced assembly together with its own
components, is reported and counted once.

Electrical data (D-041) lives in `electrical.yaml`: potential nets, devices with terminals
(signal type, potential domain such as `24VDC`/`0V`/`AC-L`/`PE`, direction, required), internal
bridges, `module_ref` to the 3D module and `catalog_ref` to the costing item, connections, I/O rows
(fixed address or allocated from a pool, routed through a terminal strip), equipment templates that
expand per matching module instance (`{module}` is substituted, so adding a camera module adds its
camera device, network port, and trigger point), safety circuits, the panel layout, and the drawing
title-block fields. Manual addresses are claimed first and duplicates are red. Undefined devices,
terminals, nets, pools, rails, or modules fail validation. Builds write a versioned `electrical.json`,
and at L1 its checks join `checks.json` (`type: electrical`, with `status`): missing wires, open
circuits (a supply's outputs are dead when its own inputs are), wrong potential domains,
incompatible signals, duplicate addresses, exhausted pools, process modules without an electrical
device, panel overflow, and BOM quantity mismatches against `costing.json`. Power budgets without
ratings and all safety circuits are reported as `not_evaluated`, never as passed. PDF/SVG drawings
and the web 電控 tab are the next part of DEV-010 (see `docs/DEV010_PROGRESS.md`).

`process.yaml` targets named frames (`<module>.<frame>`, `<robot>.tool`, and workpiece cover
hinge/edge frames). The simulator schedules event dependencies and serializes each actor, solves
robot IK, interpolates all six joints and module axes, tracks hinged covers, and carries the
workpiece through attachment, transfer, placement, and flip states.

L1 checks use native python-fcl on convex CadQuery sub-parts every 20 ms with a vectorised AABB
broadphase: `collide` (MPR) supplies penetration depth, and unsigned GJK distance supplies the gap
for separated pairs (FCL's own signed-distance query can loop forever on exactly touching faces, see
D-035). They also consume recorded IK failures, linear-path IK discontinuities, actual URDF limits/speeds, module strokes,
payload data, and station occupancy/takt. Check values are computed evidence—not acceptance
constants. During a hand-off, shallow contact with departing/arriving supports is allowed, while
penetration deeper than 1 mm remains red.

The browser applies timeline values to GLB joint nodes from their zero-pose rest transforms. It can
play at 0.25–4×, jump by station or red/yellow marker, highlight involved objects, select a node for
station/vendor/trust/world-position details, show collision geometry, tint inferred geometry, use
station cameras, and overlay another version. Context changes retain object and time; a retract
edits offset Z in the target frame. HTML export embeds the same articulated viewer, GLB, timeline,
and checks in one file that works offline via `file://`.

CellForge exposes the same engineering boundary over stdio MCP:

```powershell
cellforge-mcp
```

Available tools are `cell_build`, `cell_snapshot`, `cell_validate`,
`cell_checks`, `cell_timeline_summary`, and `cell_diff`.

## Start and stop on Windows

Double-click the wrappers, or run them from a terminal:

```powershell
.\start.cmd
.\stop.cmd
```

The PowerShell scripts expose optional settings:

```powershell
.\scripts\start.ps1 -Port 8765 -OpenBrowser
.\scripts\stop.ps1 -ShutdownTimeoutSeconds 10
```

Startup runs Uvicorn in a hidden background process and returns after the
health check succeeds. Startup and shutdown both have bounded timeouts, and
both operations are safe to run repeatedly. Runtime PID metadata and logs are
stored under `.cellforge-runtime/`.

Deleting a project in the web UI (card → 刪除) moves the whole project directory,
versions and exports included, to a trash folder next to the projects root
(`.cellforge-runtime/trash/` by default, `CELLFORGE_TRASH_ROOT` overrides it).
The 回收區 panel restores it under its original id, or under a new id if that id
is taken again, or deletes it permanently. A project with a queued or running job
cannot be deleted (`DELETE /api/projects/{id}` returns 409); the trash API is
`GET /api/trash`, `POST /api/trash/{id}/restore`, and `DELETE /api/trash/{id}`.

## Engineering agent

Production intake and first-build jobs use Claude Code. The runner validates
the CLI with `--version` and `--help`, then selects the newest usable Claude
binary found on PATH or in an installed VS Code/Cursor extension.

```powershell
$env:CELLFORGE_ENGINEERING_AGENT_MODE = "claude"
$env:CELLFORGE_CLAUDE_MODEL = "sonnet"
$env:CELLFORGE_CLAUDE_EFFORT = "low"
.\start.cmd
```

First build only starts after the latest intake succeeded
(`analysis/intake_state.json`), the input evidence has not changed since, and —
in `claude` mode — that intake was produced by the real agent, not the offline
runner. A first build succeeds only if the job itself published an L1 version
(`build.job_id` in the version manifest) that passes `cell version verify`
(manifest, hashes, schemas, GLB nodes and an OCP re-read of the STEP). The agent
has a total deadline that covers its retries; only network or service errors are
retried. Cancelling a job terminates the agent together with every process it
started (a Windows Job Object, or a POSIX process group). To build the current
YAML without the agent, use `POST /api/projects/{id}/builds/manual` or the
"手寫資料建置（非代理驗收）" button; such versions are never agent acceptance.

For deterministic offline development and tests only:

```powershell
$env:CELLFORGE_ENGINEERING_AGENT_MODE = "local"
$env:CELLFORGE_ASTRA_AGENT_MODE = "local"
.\start.cmd
```

To use Codex Astra for presentation work:

```powershell
$env:CELLFORGE_ASTRA_AGENT_MODE = "codex"
$env:CELLFORGE_ASTRA_COMMAND = "codex"
$env:CELLFORGE_ASTRA_MODEL = "gpt-6-astra"
.\start.cmd
```

Astra is restricted to presentation outputs. CellForge hashes every file under
`build/` before and after the run; a mismatch restores the latest immutable
version and fails the task. Every successful L1 browser build automatically
refreshes the theme, camera/easing plan and 1920×1080 review video.

## Windows production checklist

1. Install Python 3.12, Node.js 20+, Microsoft Edge/Chrome, and optionally Word
   and PowerPoint for Office rendering.
2. Create `.venv`, install `.[dev]`, run `python -m playwright install chromium`, then run
   `npm ci`, `npm run lint`, `npx tsc --noEmit`, and `npm run build` under `web/`. The web build
   also creates the inline offline-viewer bundle used by HTML export.
3. Set `CELLFORGE_PROJECTS_ROOT` to a writable local directory. Do not place
   active projects on a sync drive while CAD builds are running.
4. Run `start.cmd`; it returns only after `/api/health` succeeds or the bounded
   startup deadline expires. Run `stop.cmd`; it validates workspace PID metadata
   and always returns within the configured shutdown deadline.
5. Before SolidWorks delivery, inspect `step_validation.json`: name/count match
   and `all_names_preserved` must be true. The final physical validation remains
   opening the STEP in the customer's SolidWorks version.

Logs and PID metadata live in `.cellforge-runtime/`. Generated versions are
immutable under each project’s `.cellforge/vN`; presentation and export outputs
are reproducible and never replace the engineering source.

Every build first reserves a version number, freezes the project sources into
`.cellforge/_staging/`, builds only from that frozen copy, reads every artifact
back, and then publishes it with a single rename to `.cellforge/vN`. A failed or
interrupted build never leaves a directory that looks like a version.
`vN/manifest.json` records the SHA-256 of every source file, every library module
the build imported, every input evidence file and every artifact, together with
the expanded module parameters, engine commit, package versions and schema
fingerprint. Evidence files are stored once by content hash in
`.cellforge/objects/` and hard-linked into each version. `build/` is only a
mirror of the newest published version (see `build/.cellforge_version.json`).
Exports read the requested version exclusively through `VersionContext` and
report missing snapshot data instead of falling back to the workspace. Items a
version cannot supply are listed under `missing` in `export/vN/manifest.json`
(status `incomplete`) rather than substituted. Screenshots and review videos are
derived artifacts produced after a version is published: they are registered in
`.cellforge/derived/vN.json` with their source hashes and render settings;
screenshots are kept in `.cellforge/derived/vN/snapshots/`, videos in the
git-ignored `TEMP/videos/vN/`. A video whose temporary file was cleared is shown
as regenerable, never replaced by another version's video.

The intake pipeline extracts PDF text and page images, converts XLS/XLSX/CSV
rows to reviewable Markdown, and prepares EXIF-corrected product-photo review
copies. Visual evidence is analyzed in isolated, time-bounded Claude calls and
cached by content hash before the main engineering session starts.

Questions can also be handled from the CLI:

```powershell
cell question answer --project <project-path> Q-001 "confirmed value"
cell question skip --project <project-path> Q-002
cell question skip-all --project <project-path>
cell agent run --project <project-path> --owner engineering --task <task-id> --effort low
```
