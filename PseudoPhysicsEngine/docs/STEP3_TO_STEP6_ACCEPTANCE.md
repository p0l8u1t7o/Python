# CellForge Step 3–6 acceptance

Date: 2026-09-14  
Project: `.cellforge-runtime/step2-projects/Step2_Claude_Acceptance`

## Step 3 — engineering depth

- DENSO VS060 is represented by a traceable six-axis URDF stub with SHA-256, units, frames, reach, payload and joint limits; `approximated: true` is explicit.
- Timeline animates all six workpiece covers (6/6).
- L1 emits interference, reachability, joint-limit, hardware and takt checks.
- v4 detected a real engineering-envelope penetration of −3.2 mm at `robot_1.flange` versus the S3 open-cover fixture envelope.
- Context CR-001 `法蘭退 20 mm` changed `robot_1.params.flange_clearance_mm`, built v5, and verified +16.8 mm; interference changed red → green. `cell diff v4 v5` reports the semantic change.

## Step 4 — Astra and task boundary

- Engineering jobs serialize per project; Astra tasks have dependency gates and may run independently.
- Codex CLI 0.154.0 runner uses workspace-write, ephemeral JSON execution and a hard timeout.
- The whole `build/` tree is SHA-256 protected; unauthorized mutation is restored from the latest immutable version and fails the task.
- Local acceptance of `請 Astra 美化` produced theme, camera, easing and H.264 1920×1080 MP4 while pre/post build hashes were identical.
- Stdio MCP tools: build, snapshot, validate, checks, timeline summary and diff.

## Step 5 — delivery pack

The v5 export manifest contains seven files: named STEP assembly, DXF layout, UTF-8 BOM CSV, 7-page DOCX report, 7-slide editable PPTX, self-contained HTML review and 1080p MP4. DOCX was rendered through Word to PDF and all seven pages inspected. PPTX was rendered through PowerPoint and all seven slides inspected; the final package passes ZIP integrity.

STEP independent OCP readback: root/free shapes 1, top-level parts 8, total components 48, assembly nodes 9, leaves 40, all names preserved, count/name match true, XCAF fallback true. Final SolidWorks opening remains a customer workstation acceptance item.

## Step 6 — final product pass

- Viewer: selection, contextual CR, collision toggle, trust colors, red/yellow check jumps, speed selector, station timeline, and version overlay.
- Workspace: Checks, Changes, Tasks, Chat, Process, Settings, export and error/retry states.
- Reusable library: force EOAT, turnover fixture, AOI camera/light, and safety fence.
- Windows README documents installation, agents, MCP, complete export, production checklist, and bounded idempotent startup/shutdown.
- Bounded launcher regression on Windows: `start.cmd` cold start 3316 ms, already-running start 400 ms, running stop 423 ms, already-stopped stop 1207 ms; all returned exit code 0. The launcher disposes redirected stream readers before exiting so it cannot remain attached to the server lifetime.

## Final regression

- Python: 14 tests passed; Ruff formatting and lint passed.
- Web: ESLint, Prettier, TypeScript and Vite production build passed.
- MCP: all six stdio tools imported and enumerated successfully.
- Repository: the acceptance project is clean at commit `aff2db9` (`complete Step 3-6 acceptance`).
- Final runtime state: CellForge stopped; no background server is intentionally left running.
