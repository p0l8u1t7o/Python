---
name: cell-modeling
description: Create or revise articulated CadQuery modules and frame-based CellForge cell geometry, including reusable library mechanisms and robot integration.
---

# CellForge modeling

Treat `cell.yaml`, `workpiece.yaml`, `parts/`, `library/`, and vendor manifests as engineering
truth. Preserve ids and use millimetres, degrees, a right-handed coordinate system, and Z up.
Mark estimated poses and dimensions `trust: inferred`; never upgrade them to confirmed without
evidence.

A Python module exports `build(params) -> cq.Assembly` and a `ModuleDef` (or
`module_definition(params)`). Name every CadQuery sub-part. Define reusable frames as
`frames={"mount": Frame(...), "top": Frame(...)}`. A moving mechanism uses `ModuleDef.axes`:

```python
ModuleAxis(
    id="lift",
    type="prismatic",
    parent="base",
    child="lift",
    origin={"xyz": (0, 0, 0), "rpy_deg": (0, 0, 0)},
    axis=(0, 0, 1),
    range_mm=(0, 480),
    max_speed_mm_s=200,
)
```

For revolute axes use `range_deg` and `max_speed_deg_s`. Axis vectors are in the joint's local
frame. Geometry assigned to a child link must be authored at that link's zero-pose world transform
within the module; GLB export converts it back to joint-local geometry. Attach a frame to a moving
link with its `link` field.

Prefer reusable `library/` modules for conveyors, lift racks, boxes/fixtures, turnover fixtures,
camera/light brackets, force tools, extrusion frames, and safety fencing. Use vendor URDF/STEP when
traceable; otherwise use an explicitly approximated stub with real dimensions, axes, limits,
speeds, reach, and payload.

After editing, run `cell validate`, build L1, inspect OCP STEP name preservation, and take ISO plus
station snapshots at meaningful motion times. Never edit `build/` or `.cellforge/vN` directly.
