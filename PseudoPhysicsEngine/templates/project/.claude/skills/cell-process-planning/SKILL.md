---
name: cell-process-planning
description: Turn inspection requirements into a frame-based, schedulable CellForge process with realistic robot, transfer, fixture, and cover actions.
---

# CellForge process planning

Build a five-stage flow when the inputs do not justify a different count:

1. S1 infeed and singulation.
2. S2 accessible-surface vision inspection.
3. S3 robot and force-tool cover/connector inspection.
4. S4 turnover and rear-surface inspection.
5. S5 result routing and outfeed stacking.

Use stable station and step ids. Address geometry only through named frames:
`<module>.<frame>`, `<robot>.tool`, and `workpiece.<cover>.<hinge|edge>`. An offset is expressed
in the target frame; positive offset Z follows its outward normal.

Action semantics:

- `move_to` solves robot IK; `{linear: true}` samples a Cartesian path. Prefer omitted duration
  so joint speed limits and `speed_scale` determine it.
- `move_joint` accepts `home` or `joints_deg`; use only for a known collision-free transit pose.
- `grip`/`attach` bind the workpiece to the robot tool; `release`/`detach` place it at a target
  frame; `transfer` moves it between supports.
- Module or cover `actuate` changes its declared prismatic/revolute axis. Set `driven_by` when
  a robot tracks a cover edge.
- `capture`, `wait`, and `emit` record station work and handshakes without inventing motion.

Within a station steps are sequential. Across stations, use `requires`/`emits`; event names use
`<step-id>.done`. The scheduler also adds the previous station's done event. Actor timelines may
not overlap, while independent actors in different stations may. A capture must follow positioning.
Do not add fake waits merely to make takt pass; report the simulated duration and bottleneck.

Every checklist_map row needs a station or an explicit manual/out-of-scope disposition. Do not
claim that machine vision can verify internal, electrical, or destructive properties unless the
input names suitable hardware and a feasible method.
