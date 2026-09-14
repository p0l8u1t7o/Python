# First-build task

Read all answered and skipped questions. Ensure every skipped question has a corresponding
active assumption whose text equals default_if_skipped. Update inferred engineering files as
needed, while keeping the established ids stable.

Model motion through stable named frames (`<module>.<frame>`, `<robot>.tool`, and
`workpiece.<cover>.<hinge|edge>`). Target offsets are local to the frame and offset Z is its
approach/outward normal. Use `move_to` for IK, `linear: true` for Cartesian motion,
`grip`/`release` for robot handling, `transfer` for support-to-support travel, and `actuate` with
`driven_by` for robot-tracked covers. Use `requires`/`emits` for cross-station dependencies; do not
serialize independent actors or invent waits to satisfy takt.

Run `cell validate --project . --json`, then `cell build --project . --level L1 --json`. Read every
red/yellow check as measured evidence from geometry, IK, limits, payload/stroke/speed, or takt;
never hardcode a check value or a project-specific exception. Create ISO, top, and station-focused
snapshots at meaningful motion/check times and verify their dimensions. Do NOT call Read on PNG/JPG
in this main session; isolated vision jobs handle image payloads. Do not edit build/ directly.
Return the version and check summary in the required final JSON.
