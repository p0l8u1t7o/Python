---
name: cell-review
description: Review CellForge L1 geometry, animation, checks, snapshots, and change requests for causal engineering correctness.
---

# CellForge review

Read `build/checks.json` together with `build/timeline.json`, `process.yaml`, and station snapshots.
Do not accept a summary count alone.

- For `interference`, inspect `objects`, `t`, signed `min_dist_mm`, `source`, and the snapshot.
  Driven tool/cover contact may be green. Support contact up to 1 mm is allowed; deeper support
  penetration remains red. Confirm a warning is not an intended attachment or adjacent link.
- For `reachability`, use recorded `ik_failures`; check position/orientation errors and whether
  warm-started joints remain continuous.
- For `joint_limit`, compare the reported sample with the chain limits. Yellow begins near the
  configured limit, not a universal angle.
- For `hardware`, check payload while attached, module stroke, and differentiated speed.
- For `takt`, report effective duration, station occupancy, and the bottleneck. Never alter time
  or parallel workpieces solely to change severity.

Scrub to every red/yellow time. Confirm robot links are connected and posed, covers rotate about
their hinges, the workpiece follows its support/tool and flips at the intended station, and static
equipment does not jump. Check ISO, top, and relevant station cameras.

For a CR, record the original check and process field, apply the smallest frame-based change,
validate and rebuild L1, then compare versions. A retract changes target offset Z because frame Z
is the approach/outward normal. Recheck all red/yellow items, not only the targeted pair, and fill
代理解讀、影響、差異、結果、狀態 in the CR.
