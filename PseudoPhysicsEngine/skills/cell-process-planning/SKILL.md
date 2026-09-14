---
name: cell-process-planning
description: Turn a checklist map into a bounded CellForge station and event sequence.
---

# CellForge process planning

Build a five-stage flow when the inputs do not justify a different count:

1. S1 infeed and singulation.
2. S2 accessible-surface vision inspection.
3. S3 robot and force-tool cover/connector inspection.
4. S4 turnover and rear-surface inspection.
5. S5 result routing and outfeed stacking.

Use stable station ids and step ids. Within a station, steps are sequential. Across stations,
express dependencies with `requires` and `emits`; event names use `<step-id>.done`. A capture
must depend on positioning completion. A transfer must make attachment and detachment events
explicit. Derive durations from the takt target where possible and label estimates as inferred.

Every checklist_map row needs a station or an explicit manual/out-of-scope disposition. Do not
claim that machine vision can verify internal, electrical, or destructive properties unless the
input names suitable hardware and a feasible method.
