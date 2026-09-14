# CellForge

CellForge is a local-first engineering workspace for generating and reviewing
manufacturing cells.

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

## Step 3–6 engineering workflow

```powershell
# Traceable vendor source or an explicit approximation
cell vendor stub denso_vs060 --project <project> --reach-mm 905 --payload-kg 7
cell vendor add camera_model <file-or-url> --kind sensor --project <project>

# Named CAD, motion, 20 ms swept-envelope checks, and immutable version
cell build --project <project> --level L1
cell checks --project <project>
cell diff v1 v2 --project <project>

# Complete customer pack: STEP, DXF, BOM, DOCX, PPTX, HTML, MP4
cell export --project <project> --kinds all
```

The L1 result contains interference, reachability, joint-limit, hardware and takt
checks. A check records its measured value, limit, unit, affected objects and
evidence source. The browser can jump to red/yellow times, toggle collision
geometry, overlay another version, select a module, and create a contextual CR.

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
2. Create `.venv`, install `.[dev]`, run `python -m playwright install chromium`,
   then run `npm ci` and `npm run build` under `web/`.
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
