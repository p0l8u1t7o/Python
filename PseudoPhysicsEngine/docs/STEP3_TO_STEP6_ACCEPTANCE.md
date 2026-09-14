# CellForge Step 3–6 acceptance

Date: 2026-09-14  
Reference project: `examples/getac_qc/handwritten`

## Engineering engine

- Robots use a six-axis kinematic chain with URDF-compatible axes, origins, limits, speeds, FK,
  Jacobian, and warm-started numerical IK. GLB nodes are nested `robot → j1…j6 → tool`; module and
  cover axes use the same rest-TRS-plus-axis-motion convention.
- The workpiece is generated from `workpiece.yaml`, travels through named support/tool attachments,
  opens `cover_lan` by robot edge tracking, and is flipped before outfeed.
- The scheduler resolves explicit events, implicit preceding-station dependencies, and actor
  serialization. Timeline output records steps, joint names, quaternion poses, attachments,
  driven-by relationships, and every IK failure.

## L1 evidence

- Interference is native python-fcl signed distance (`native_fcl: true`) sampled every 20 ms over
  convex CadQuery sub-parts. Numpy AABB broadphase limits FCL calls. FCL contact depth is preferred
  for penetration, with a named AABB fallback when the binding cannot return depth.
- Hand-off support windows come from steps, attachments, and destination frame ownership. Contact
  within 1 mm is permitted for the workpiece body and covers; deeper support penetration is red.
- Reachability consumes the simulator's recorded IK attempts. Joint-limit checks use each chain's
  actual range. Hardware checks derive payload, stroke, and speed from scene/timeline data. Takt
  reports effective duration, station occupancy, and bottleneck.
- In the handwritten example, the S3 approach produces a genuine FCL red contact between the force
  tool and workpiece/cover. A contextual CR “法蘭退 20 mm” changes `S3.approach.target.offset.xyz[2]`
  and removes all red interference after an L1 rebuild; no clearance parameter or fixed result is
  involved.
- Current measured L1: 48.441 s duration, 2,318 changed-state samples and 5,842 native-FCL pair
  evaluations. The designed contacts are −2.000 mm (`robot_1.tool` ↔ `workpiece.cover_lan`,
  t=18.32 s) and −0.949 mm (`robot_1.tool` ↔ `workpiece`, t=18.34 s). Takt is honestly yellow at
  48.44/45.00 s; S3 is the 12.79 s bottleneck and the estimated pipelined steady-state takt is
  12.79 s. There is no joint-limit warning after the frame-based clear move.

## Viewer and delivery

- The React/Three.js viewer applies every joint/axis track from stored rest transforms, interpolates
  workpiece quaternion poses, offers 0.25–4× playback, station segments/cameras, check-time markers,
  object highlighting, metadata selection, collision/trust toggles, and version overlay.
- The HTML delivery is a self-contained WebGL viewer containing an inline bundle, base64 GLB,
  timeline, and checks. It plays the articulated scene directly from `file://`; it is not a 2D
  canvas diagram.
- STEP validation still independently reads the XCAF hierarchy and requires component names and
  expected counts to match. Opening the final STEP in the customer's SolidWorks version remains a
  workstation acceptance item.

## Verification record

The WP4 reference build completed L1 in 21.433 s. OCP read-back measured 8 top-level components,
49 total components, 9 assembly nodes, and 41 leaves with names/counts preserved. Frontend/Python
regression results and inspected screenshot paths are recorded in the implementation handoff;
none of these measured values appear in acceptance logic.
