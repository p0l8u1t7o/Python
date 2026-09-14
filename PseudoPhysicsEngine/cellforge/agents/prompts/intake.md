# Intake task

Read inputs/manifest.yaml and analysis/extraction.json. PDF page text and images and
spreadsheet rows and review-sized photo copies have already been written below
analysis/extracted/. Read the numbered PDF text artifacts one at a time; do not open
`all-pages.txt` because Claude Code may truncate a large tool result. Image inspection has
already run in isolated Claude vision jobs for every product photo and low-text PDF diagram.
Read `analysis/extracted/vision.md`. Do NOT call Read on any `.png`, `.jpg`, or `.jpeg` file in
this main intake session; doing so is prohibited because image payloads destabilize long-context
Claude Code sessions.

Create or replace:

1. analysis/intake.md: a sourced Traditional-Chinese summary with file/page references.
2. analysis/checklist_map.md: map every identifiable checklist inspection row to an
   automation feasibility grade (high/medium/low/manual), method, and proposed station.
   Include a coverage line in the exact form `Coverage: M/N (P%)` and cover at least 80%.
3. analysis/questions.yaml: 5-15 high-impact questions. Every item must have id, topic,
   text, why, status: open, answer: null, and default_if_skipped.
4. workpiece.yaml, cell.yaml, and process.yaml as inferred first drafts that validate against
   the project schemas. Prefer five stations and the user's constraints.

Do not build in this task. Run `cell validate --project . --json`, repair validation errors,
then commit the changed engineering and analysis files with a concise message.
