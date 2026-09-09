# Camera calibration, lens correction and robot coordinates

The Calibration page (`/calibration`) produces station geometry and a stitching setup. The geometry is stored in one **calibration asset** (kind `calibration`, a JSON file): the lens model that straightens what a wide-angle or close lens bends, the mapping from pixels to millimetres on the plane the parts sit on, the mapping from pixels to the coordinates a robot expects, and the mapping from one camera's image coordinates into another camera's image coordinates. The tools consume it through `undistort` before measuring, `to_world` after locating, `map_points` for camera hand-off, `stitch_images` for multi-camera mosaics and `align_offset` for robot pick compensation; the `calibration` tool's asset mode converts a single length. Teach geometry once per station; every flow that picks the asset follows, and re-teaching after a lens or camera change updates them all.

## 1. The seven ways to calibrate {#modes}

| Mode | What you do | What you get |
|---|---|---|
| Board | Take 10 to 15 pictures of a chessboard or circle grid at different positions and tilts, filling the edges and corners of the picture as well as the middle; enter the inner-corner count and spacing | The lens model (camera matrix and distortion coefficients, with the reprojection error per picture) and, from the picture you choose, the millimetre mapping of the plane |
| Points | Click a feature on the picture, type the robot's coordinates for that spot, repeat for at least 4 spots (9 spread over the working area is better) | An affine or perspective mapping from pixels to robot coordinates with the residual of every point, so a mistyped one shows up immediately |
| Distance | Click two points and type the real distance between them | A plain scale — enough for measurement flows that only need millimetres |
| Hand-eye | Follow the wizard: move the robot to a place, type the coordinates the robot reports, take a picture and mark the feature (click with snap-to-centre, or let a flow step such as a template match find it). Repeat for three or more places. Optionally record the same feature at three or more angles in a second stage, with the robot held still and only the tool turning | A pixel-to-robot affine mapping, handedness and angle sign convention; the second stage adds the centre of rotation in pixels and robot units |
| Camera mapping | Load or capture two camera views side by side, then mark corresponding points in A and B. Alternatively send two sets of board corners from cameras looking at the same calibration board | An affine or perspective A-camera-to-B-camera mapping, with the residual of every pair so the worst pair is visible and can be deleted before solving again |
| Stereo | Pick left and right sources, capture at least five paired board views, solve intrinsics plus the fixed stereo transform, or import a legacy `stereo_config.json`. Then measure a belt ROI once to store the height reference | A `stereo` calibration block with `M1`, `D1`, `M2`, `D2`, `R`, `T`, `baseline_mm`, per-pair residuals and optional `z_ref` for robot Z |
| Multi-camera stitching | Select 2 to 4 sources, capture one frame from each, choose grid or homography stitching, choose each source's calibration when the projection mode needs it, then preview the combined picture | A normal inspection flow with one image source per camera and one `stitch_images` node. No new calibration asset or database migration is needed; the chosen sources and stitching parameters live in the flow graph |

The **Solve** step shows the result without saving it: the residuals, the quality badge, the coverage of the picture and the warnings. Save only when you are satisfied. The solver refuses fewer than 4 point pairs for a perspective mapping (3 for affine, 2 for a scale) with a 422 rather than a silently poor fit.

## 2. Generate a printable board {#board-generator}

The board mode includes a **Generate calibration board** panel. Choose `chessboard` or `acircles`, enter rows, columns, spacing in millimetres and DPI, then preview or download the PNG. The generated geometry is exact in pixels: one step equals `spacing_mm / 25.4 * dpi`. For example, 20 mm at 300 DPI is 236.22 px between neighbouring chessboard corners or circle centres.

The PNG prints the pattern, row and column count, spacing and DPI on the sheet, plus a known-length scale bar. Print with scaling set to **100% / actual size**, then measure the scale bar before using the board. If the measured bar is wrong, the calibration will faithfully learn the printer scaling error.

The same file is available to integrations at `GET /vision/calibration/board.png` with query parameters `pattern`, `rows`, `cols`, `spacing` and `dpi`. It uses the same permission as the rest of the calibration page and returns 422 for invalid sizes or DPI instead of guessing.

## 3. Coverage and the warnings that matter {#coverage}

Lens distortion is largest in the corners, so a calibration whose board pictures all sit in the middle of the frame is accurate in the middle and wrong where it matters. While you collect board pictures the page keeps a **coverage map**: the picture is divided into a 4×3 grid and every cell that has received no corner yet is drawn as a red dashed box on the current picture, with a line saying how many of the twelve areas are covered and how many *edge* areas are still empty. Add pictures with the board pushed into those areas until the map is clear.

After solving, the page shows the warnings the solver raises, in plain words:

- **Reprojection error above 0.5 px** — the lens model does not explain the pictures well: blurred or unevenly lit pictures, a board that is not flat, or too little tilt. Redo it.
- **Fewer than 8 pictures** — the model will be unsteady; 10 to 15 is the norm.
- **Coverage below three quarters, or empty edge areas** — see above.
- **Point residual above two pixels** (points mode) — a mistyped coordinate, a feature clicked on the wrong spot, or a camera looking at the plane at an angle that needs the perspective mapping rather than the affine one.

The same information comes back from the API: `POST /vision/calibration/solve` returns `coverage` and `warnings[]` next to the payload, and `POST /vision/calibration/coverage` (image size plus the corner sets collected so far) returns the grid, the empty cells and ready-made overlays for a custom front end.

## 4. Hand-eye calibration {#hand-eye}

The wizard separates **translation** from **rotation**. First collect three or more non-collinear pixel/robot point pairs by moving, entering the reported coordinates, taking a picture and locating the feature. Choose `translation_rotation` to add a separate rotation stage: keep the robot's X/Y position still, turn only the tool and record the same feature at three or more angles. Translation samples cannot stand in for this rotation arc.

The fit solves a pixel → robot affine mapping (`robot.matrix`). The determinant of its 2×2 linear part gives `handedness`: positive is `right`, negative is `left` (mirrored). The default `angle_sign` is respectively +1 or −1 for the robot's +X-to-+Y angle convention; override it before saving if the controller uses a different convention. With the rotation stage, the fitted circle gives the centre in pixels and the matrix converts it to robot units.

`camera_mode` records whether the camera is `fixed` or `moving`. In either case the matrix comes from the actual point pairs; selecting a moving camera does not invert the mapping.

Robot coordinates can also come from the line connection instead of manual typing. On **Integration ▸ TCP ▸ Receive rules**, add regex rules whose action is `calibration_signal`: `^Start$` clears the signal queue and starts a fresh wizard pass, `^Calibration\((?P<x>[^,]+),(?P<y>[^,]+),(?P<r>[^)]+)\)$` records the next robot X/Y and optional R, `^End$` marks the stream complete, and `^Teach\((?P<x>[^,]+),(?P<y>[^,]+),(?P<r>[^)]+)\)$` is displayed as the controller's current taught point. Then open the robot wizard and choose **Connection** for the robot coordinate source; the page polls `GET /vision/calibration/robot/signals?since=<seq>`, while `DELETE /vision/calibration/robot/signals` clears the local queue.

**Least squares only, never RANSAC.** Every point the operator entered stays in the fit and gets a residual: `points[].error` in robot units, and `rotation_points[].error` in pixels to the fitted circle. The worst translation point is drawn red on the picture when its residual is non-zero. Delete any point in either stage and solve again to recalculate the fit. The reason is simple: the operator typed those points; silently discarding one hides a typo.

Send `POST /vision/calibration/solve` with `mode: "robot"`, `image_size: [w,h]`, `unit: "mm"`, `kind: "translation"` or `"translation_rotation"`, `camera_mode: "fixed"` or `"moving"`, and `points` containing `{"px":..,"py":..,"rx":..,"ry":..}` objects. `rotation_points` is a separate list of `[x,y]` pixel positions, required for `translation_rotation`; omit it or send an empty list for `translation`. The optional `angle_sign` is 1 or −1. For example:

```
{
  "mode": "robot", "image_size": [1280, 960], "unit": "mm",
  "kind": "translation_rotation", "camera_mode": "fixed",
  "points": [
    {"px": 100, "py": 100, "rx": 10, "ry": 10},
    {"px": 300, "py": 100, "rx": 30, "ry": 10},
    {"px": 100, "py": 300, "rx": 10, "ry": 30}
  ],
  "rotation_points": [[250,200], [200,250], [150,200]],
  "angle_sign": 1
}
```

The reply's `payload.robot` block is shown below (values rounded for readability). Solve only computes; to store it, send `POST /vision/calibration/assets` with a `name` and the complete returned `payload`.

```
{
  "kind": "translation_rotation", "camera_mode": "fixed",
  "matrix": [[0.1,0,0], [0,0.1,0], [0,0,1]],
  "handedness": "right", "angle_sign": 1, "rms": 0, "max_error": 0,
  "points": [
    {"px": 100, "py": 100, "rx": 10, "ry": 10, "error": 0},
    {"px": 300, "py": 100, "rx": 30, "ry": 10, "error": 0},
    {"px": 100, "py": 300, "rx": 10, "ry": 30, "error": 0}
  ],
  "rotation_center_px": [200,200], "rotation_center_world": [20,20],
  "rotation_points": [
    {"px": 250, "py": 200, "error": 0},
    {"px": 200, "py": 250, "error": 0},
    {"px": 150, "py": 200, "error": 0}
  ],
  "rotation_rms_px": 0, "rotation_max_error_px": 0
}
```

The robot result also shows the approximate physical distance per pixel, computed as the square root of the absolute determinant of the mapping's 2×2 linear block. This is a pixel scale estimate, separate from the fit residual.

## 5. Camera-to-camera mapping {#camera-mapping}

The camera mapping mode is pure 2D geometry: point pairs are `A pixel → B pixel`. `kind="affine"` needs at least three pairs and solves the six affine coefficients with least squares. `kind="perspective"` needs at least four pairs and solves the homography with normalised DLT least squares. There is no RANSAC and no hidden point rejection; every pair stays in `mapping.points[]` with its residual in pixels, and the largest residual is marked red in the table and overlays.

The same API endpoint accepts board data. Send `mode: "mapping"`, `views_a`, `views_b`, `cols`, `rows`, `spacing` and optionally `board_kind`. For one shared board view, the solver builds two pixel-to-board homographies, `H_a` and `H_b`, then composes `mapping = H_b^-1 · H_a`, which maps A pixels into B pixels. Multiple board views are flattened into corresponding corner pairs and solved the same way as manual points.

```
{
  "mode": "mapping", "kind": "perspective", "image_size": [1280, 960],
  "from_source": "top", "to_source": "side",
  "points": [
    {"a": [100, 120], "b": [42, 310]},
    {"a": [320, 120], "b": [260, 304]},
    {"a": [100, 360], "b": [50, 530]},
    {"a": [320, 360], "b": [270, 520]}
  ]
}
```

## 6. Stereo calibration and height reference {#stereo}

The stereo mode stores a physical stereo pair in the same calibration asset. Solve accepts `mode: "stereo"` with left and right board views from the same board pose. It runs normal camera calibration on each side, then `stereoCalibrate` with fixed intrinsics. Every pair remains in the least-squares fit and receives a residual; delete a bad pair and solve again rather than relying on hidden outlier rejection.

`POST /vision/calibration/stereo/import` accepts the legacy `stereo_config.json` fields `M1`, `D1`, `M2`, `D2`, `R`, `T`, `width` and `height`. The platform ignores saved rectification matrices and recomputes its own maps through `stereoRectify(alpha=0)`. `POST /vision/calibration/stereo/reference` measures a belt ROI, stores `z_ref.d0_mm`, `Z0_mm` and optional `scale`, and leaves the original calibration fields unchanged.

## 7. Multi-camera stitching setup {#stitching}

The stitching mode is a flow builder, not a calibration solver. It records the source choices in the generated `image_source` nodes and records the geometry in the `stitch_images` node parameters. Keeping the setup as a normal flow means version history, preview, batch testing and downstream measurement all use the same runtime path; calibration assets remain the reusable station geometry instead of becoming one-off process recipes.

Use `grid` when the cameras are mounted as a fixed rows×columns array with no perspective difference. The tool never stretches cells: after trimming the same number of pixels from every edge, every input must have the same size, and a mismatch names the offending image. Use `homography` when each camera has its own `world.matrix` pixel-to-plane calibration, or when cameras 2 to 4 have a saved `mapping.matrix` into image 1. The output includes the stitched image, picture count, width, height, grid offsets, `origin` as the output pixel where world coordinate (0,0) lands, and `scale` as world units per output pixel.

## 8. The tools {#tools}

### undistort (pre-processing) {#undistort}

Straightens the picture with the lens part of the calibration. `alpha` chooses how much of the frame to keep: 0 zooms so that every pixel is real image (no black borders), 1 keeps the whole frame with black corners, values between keep that share. The remap tables are built once per (calibration, image size, alpha) and cached, so a frame costs one `remap`; the *mm per pixel* output carries the plane scale when the calibration has one, ready to feed the `calibration` tool. A picture whose size differs from the calibration is handled by rescaling the camera matrix; a different *aspect ratio* is refused with a message that names both sizes — the usual symptom of a camera swap.

### stitch_images (pre-processing) {#stitch-images}

Combines 2 to 4 camera images before the locating and measuring steps. Live flows should wire `image_1` through `image_4`; fixed images are a fallback for demos and bench cases when no image port is connected. `blend=uncover` is the fastest path and lets later images cover earlier ones; `mean`, `min` and `max` define the overlap pixels explicitly. Homography remapping uses the same acceleration path as other large remaps.

### stereo_depth (measurement) {#stereo-depth}

`stereo_grab` also has optional `image` / `image_right` input ports: when the left image is wired (template sample pictures, batch tests, video extraction) the tool does not open the sources; a missing right image is stood in by the left one with a warning, so the flow still runs end to end and `z` is simply empty.

Measures object-top distance from `stereo_grab` pairs. The tool rectifies the full pair once, computes SGBM only inside each object ROI, and averages or takes the median only over valid disparity pixels inside the segmentation polygon. When `dt_ms` and match velocity are available, the right ROI is shifted by `vx * dt` and `vy * dt` before disparity. It writes `distance_mm`, `disparity`, `valid_ratio`, `compensated` and `z` to every match. Without `stereo.z_ref`, `z` is empty and the distance is still reported. The pair offset `dt_ms` is signed (right capture time minus left, positive when the right camera exposed later); motion compensation shifts the right ROI by `-v·dt`, so the sign matters.

### to_world (measurement) — real-world and robot coordinates {#to-world}

Turns pixel positions into the calibration's world coordinates: wire a locate tool's centre into the `x`/`y` ports (or a `points` list), read `x`/`y` in millimetres or robot units; a pixel length becomes a real length and an image angle becomes a world angle, both converted with the mapping at that position (so a perspective mapping's varying scale is respected). A mirrored mapping — a camera mounted so that the image is flipped relative to the robot's axes — flips the angle sign accordingly, which is why the angle goes through the mapping rather than being copied. Wire the outputs to `output` steps to hand a pick position to the robot.

The optional `frame` input comes from `coordinate`. Forward conversion subtracts its origin, rotates by minus its angle, divides by its scale, then applies calibration. The calibration must describe those frame coordinates. Without calibration, the result is in frame pixels; without either input, positions are unchanged. Existing calibrated flows retain the world mapping when available, with robot mapping as a fallback.

`mode=to_world` is the default. Select `to_pixel` to treat `x`/`y`/`points` as world or frame coordinates and invert the calibration and frame, including perspective mappings. Output names remain `x`/`y`/`points_world`, but their values are now image pixels. Length and angle inputs follow the selected direction. `decimals` controls display text only. Forward length-only or angle-only conversion still requires a calibration or frame when no position is supplied.

Measurement tools can output physical values directly when an optional `calibration` asset is selected: `distance`, `caliper`, `find_circle`, `fit_arc`, `find_rectangle`, `find_parallel_lines`, `find_line` and `geometry` add `<original key>_world` and `unit` outputs, preferring robot mapping. Without calibration their existing pixel results remain unchanged and the extra ports have no value. In particular, arc radius is `radius_world`, parallel-line width is `distance_world`, and geometry uses `distance_world` for its length or radius. Lengths use the local area-equivalent pixel scale at the measurement centre; under anisotropic or perspective mappings this is an approximation, not an integrated endpoint distance. Angles remain in degrees.

`coordinate` defines an origin and X axis using `point_angle` (point and angle inputs, or taught `origin_x/origin_y/axis_angle`), `two_points` (origin and `point2`), or `line` (directed segment start and direction). It outputs `frame`, `origin_x`, `origin_y` and `angle`, with scale 1 and clockwise image angles. Missing or coincident input points take the `not_found` branch; the overlay shows the origin and both axes.

### map_points (locate) {#map-points}

Maps points from one camera coordinate system to the other with a calibration asset that contains `mapping`. It accepts `points`, `matches`, or one `x`/`y` pair. `direction=forward` applies the saved matrix; `direction=inverse` applies its inverse. If the asset has no `mapping` block the tool fails with a clear `ToolError` instead of returning unchanged coordinates.

### calibration (measurement) {#calibration-tool}

Length conversion only: pixel size, a known distance, or the asset. Use the asset mode so that re-teaching the station updates every flow.

### align_offset (locate) {#align-offset}

Takes the same calibration asset to convert the compensated absolute pose to robot or world coordinates. When both mappings exist it prefers `robot` over `world`. If the asset also has `mapping`, the tool adds `mapped_x`, `mapped_y` and `mapped_angle` by applying the camera mapping to the absolute pose; without `mapping` its outputs are exactly the same as before. See [Inspection capabilities](vision-capabilities.md#tools) for the four modes, input ports and position-correction output.

## 9. What the asset holds {#asset}

```
{
  "unit": "mm", "image_size": [1280, 960],
  "lens":  {"camera_matrix": [[fx,0,cx],[0,fy,cy],[0,0,1]], "dist_coeffs": [k1,k2,p1,p2,k3], "rms": 0.21, "views": 12, "view_errors": [...]},
  "world": {"kind": "affine", "matrix": [[...3x3...]], "mm_per_px": 0.0512, "rms": 0.03, "max_error": 0.07, "points": [{"px":[..],"world":[..],"error":..}]},
  "robot": {"kind": "translation_rotation", "camera_mode": "fixed", "matrix": [[...3x3...]], "handedness": "right", "angle_sign": 1,
            "rms": 0.03, "max_error": 0.07, "points": [{"px":..,"py":..,"rx":..,"ry":..,"error":..}],
            "rotation_center_px": [..,..], "rotation_center_world": [..,..], "rotation_points": [{"px":..,"py":..,"error":..}],
            "rotation_rms_px": 0.12, "rotation_max_error_px": 0.2},
  "mapping": {"from_source": "top", "to_source": "side", "kind": "perspective", "matrix": [[...3x3...]],
              "points": [{"ax":..,"ay":..,"bx":..,"by":..,"error":..}], "rms": 0.04, "max_error": 0.08},
  "stereo": {"left_source": "left", "right_source": "right", "M1": [[...3x3...]], "D1": [...], "M2": [[...3x3...]], "D2": [...],
             "R": [[...3x3...]], "T": [tx,ty,tz], "image_size": [1280, 960], "rms": 0.2, "baseline_mm": 60,
             "board": {"pattern": "chessboard", "rows": 6, "cols": 9, "spacing": 20},
             "points": [{"index": 0, "error": 0.08}], "z_ref": {"d0_mm": 800, "Z0_mm": 100, "scale": 1}}
}
```

`lens`, `world`, `robot`, `mapping` and `stereo` are optional blocks; at least one must be present. The robot block holds:

| Field | Meaning |
|---|---|
| `kind`, `camera_mode` | `translation` or `translation_rotation`; camera `fixed` or `moving` |
| `matrix`, `handedness`, `angle_sign` | The 3×3 pixel-to-robot affine matrix (last row `[0,0,1]`), `right` or `left` from its determinant, and the saved +1 or −1 angle convention |
| `rms`, `max_error`, `points[]` | RMS and worst residual in robot units; every entered `px`/`py`/`rx`/`ry` pair with its `error` |
| `rotation_center_px`, `rotation_center_world` | The fitted centre as `[x,y]` in pixels and robot units, added by the rotation stage |
| `rotation_points[]`, `rotation_rms_px`, `rotation_max_error_px` | Each rotation sample's `px`/`py` and radial `error`, plus RMS and worst radial error, all in pixels; added by the rotation stage |

The `mapping` block holds the source labels, `affine` or `perspective`, a 3×3 matrix, every entered A/B pair as `ax`/`ay`/`bx`/`by`, and the pair residuals in pixels.

The `stereo` block holds two camera matrices, two distortion vectors, the left-to-right `R`/`T`, image size, positive `baseline_mm`, solve RMS, board metadata, per-pair residuals, and optional `z_ref`. Robot height is `Z0_mm + (d0_mm - distance_mm) * scale`.

`GET /vision/calibration/assets/{id}` returns the content with the summary and quality. The robot summary includes the kind, point count, RMS, worst residual, handedness and whether a rotation centre exists; with rotation samples it also lists their count and radial errors. `manage.py` has no calibration command because the pictures come from the camera through the page.

## 10. Accuracy, checked {#accuracy}

- Synthetic pictures with known distortion (k1 = −0.28, k2 = 0.12): the solver recovers k1 within 2% and the focal length within one pixel (`tests/test_calib.py`).
- `to_world` round trip image → world → image within 1e-6, including a mirrored mapping.
- `undistort` at 1280×960: the first frame builds the maps, every following frame is the plain remap; the test asserts that 100 frames average the steady-state time.
- `solve_mapping` recovers a synthetic affine matrix element by element within 1e-6, keeps an added outlier in the residual table, verifies perspective mappings with four or more points, and checks that board-derived camera mapping matches direct point-pair solving within 1e-6 (`tests/test_mapping.py`).
- `stereo_depth` synthetic stereo checks object-top distance within 1%, valid disparity inside a belt mask above 0.9, the `z_ref` formula, and that software trigger time compensation improves a shifted right image (`tests/test_stereo.py`).

Not in scope: full 3D hand-eye poses. Hand-eye calibration records a fixed or moving camera and fits a 2D mapping from the supplied point pairs; it does not solve the camera's 3D pose on the arm.
