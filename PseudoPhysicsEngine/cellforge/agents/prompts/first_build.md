# First-build task

Read all answered and skipped questions. Ensure every skipped question has a corresponding
active assumption whose text equals default_if_skipped. Update inferred engineering files as
needed, while keeping the established ids stable.

Run `cell validate --project . --json`, then `cell build --project . --level L0 --json`.
Create ISO, top, and station-focused snapshots and verify that each PNG exists and has non-zero
dimensions. Do NOT call Read on any PNG/JPG in this main session; long-context image payloads
are handled by isolated vision jobs and can stall Claude Code. Do not edit build/ directly.
Return the resulting version number in the required final JSON.
