---
name: cell-vendor-sourcing
description: Add traceable vendor CAD and robot definitions to CellForge, or create an explicitly approximate catalog-based stub when originals are unavailable.
---

# CellForge vendor sourcing

Prefer manufacturer CAD and URDF, then ROS-Industrial sources, then established CAD catalogs such
as MISUMI or TraceParts. Record source URL/file, retrieval date, SHA-256, file units, up axis,
frames, part number, joint limits/speeds, reach, payload, and whether the asset is approximated.

Use `cell vendor add` for supplied files. Use `cell vendor stub` only when an original cannot be
obtained; never describe a stub as vendor geometry. URDF lengths are metres and joint angles are
radians; CellForge converts them to millimetres/degrees internally. Verify joint count, axes,
origins, limit direction, tool/flange frame, STEP scale, and zero-pose FK before accepting it.

Build L1 after changes and inspect both OCP STEP name preservation and an articulated snapshot.
