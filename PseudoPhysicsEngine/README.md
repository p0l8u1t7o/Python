# PseudoPhysicsEngine

AI-assisted automation-equipment digital twin and feasibility proposal platform.

Status: the local, vendor-neutral MVP core is implemented. Native CAD, Robot, Blender, and
SolidWorks adapters await the external inputs listed in `docs/development-status.md`.

## Documents

- Product and architecture baseline: `docs/automation-digital-twin-platform-plan.md`
- Development execution plan: `docs/development-plan.md`
- Current implementation status: `docs/development-status.md`

## Local environment

The prepared baseline is Python 3.12 with a React/TypeScript/Vite web client.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements\dev.txt
.\scripts\init-dev.ps1
.\scripts\check-environment.ps1
```

## One-click development startup

Double-click `start-dev.cmd`, or run it from PowerShell:

```powershell
.\start-dev.cmd
```

The command prepares packages and migrations, starts the API, web client, and rules worker as
hidden background processes, waits for health checks, and opens the web app. If ports 8000 or
5173 are occupied, it selects the next available ports and prints the actual URLs.

Stop only the processes recorded by this project:

```powershell
.\stop-dev.cmd
```

Process identity and selected ports are recorded under `.local/run`; stdout and stderr logs are
under `.local/logs`. Background services use isolated standard input, so start and stop commands
can be run consecutively in the same terminal. Stale or mismatched process identities are never
terminated.

PowerShell users can override the preferred ports or skip the bootstrap on later starts:

```powershell
.\scripts\start-dev.ps1 -ApiPort 8100 -WebPort 5200
.\scripts\start-dev.ps1 -SkipBootstrap
.\scripts\stop-dev.ps1
```

For manual startup, run the API baseline:

```powershell
.\.venv\Scripts\uv.exe run alembic upgrade head
.\.venv\Scripts\uv.exe run ppe-api
```

OpenAPI documentation is then available at `http://127.0.0.1:8000/docs`.

In a second terminal, run the web workspace:

```powershell
Set-Location apps\web
npm install
npm run dev
```

Vite prints the local web URL and proxies `/api` to the API on port 8000.

## Current vertical slices

- Projects, immutable revisions, coordinate-frame trees, revision history/diff, and Web-driven
  approved ChangeSet preview/application with complete engineering snapshot copying.
- Content-addressed STEP, GLB, and PDF uploads with signature checks, SHA-256 metadata, listing,
  and controlled downloads. Parasolid and SolidWorks uploads remain rejected until a trusted
  parser is integrated.
- Lazy-loaded Three.js GLB viewer with Z-up grid, orbit controls, model fitting, and project
  resume after page reload.
- Frontend API contracts generated from the versioned Pydantic JSON Schemas.
- Durable jobs with lease/heartbeat/retry semantics and a standalone rules-validation worker.
- Versioned ProcessSpec, MotionSpec, and SceneAssemblySpec persistence with same-revision
  relationship checks, critical-path cycle time analysis, Scene assembly editing, and MotionSpec
  playback in the GLB viewer.
- Persisted ValidationReport, Kabsch control-point calibration, release gate, immutable released
  revisions, and SHA-256 ReleaseManifest generation.
- Revision review comments, resolution-aware release validation, unified audit history, and Web
  controls for background rules validation.

Quality commands become active as source code is added:

```powershell
.\scripts\verify.ps1
```

CAD libraries, Blender, Docker, and SolidWorks integration require real sample data and licensed
tool environments; the worker contracts are ready but those outputs are not simulated. Do not
install Git hooks from this directory: it intentionally lives inside a parent repository, and
every Git command must be restricted to this project path.
