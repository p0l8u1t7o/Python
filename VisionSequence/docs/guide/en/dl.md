# Deep-learning teaching: label, train and export inside the platform

The Deep learning page (`/dl`) takes you through a full round of teaching **without leaving the platform**: create a teaching project → collect samples (upload, or grab a burst from an image source) → label them (with **automatic labelling** to speed it up) → train **on the server** (with the GPU and accelerator information in front of you and the device your choice) → and the model is exported as an **asset**, ready to select in a DL tool in any flow. Model kinds (trainers) are a registry, so a new one **reuses the same interface** with no front-end work.

## 1. Teaching, from the user's side {#flow}

1. **Create a teaching project**: a name, a model kind, and the classes (`OK, NG`, say — you can add and remove them later).
2. **Collect samples**: "Upload images" (multi-select, and **a zip is accepted too**) or "Grab from source" (pick an image source and take N frames, optionally pre-labelled). Every upload is **de-duplicated on the SHA256 of the decoded pixels** — re-uploading the same image, or a duplicate inside a zip, is skipped and reported.
3. **Label** (classification): two views. **Grid** — click a class button, then click thumbnails, which is the fast way through a lot of images (hovering a thumbnail gives you enlarge and delete). **Large** — a thumbnail wall on the left and a full-image viewer on the right, with zoom and 1:1 for detail, class buttons or the 0–9 keys to label, and ←/→ to move. Both share the same filters.
4. **Train**: the panel on the right holds the hyper-parameters (the form is generated from the trainer's declaration), the device and the name for the model asset. Progress and metrics (training and validation accuracy) update live, and training runs in the background without using the inspection thread pool.
5. **Keep it or drop it**: training does **not** write to the asset library on its own. When it finishes, the panel shows the metrics and a name field: **Save to Assets** stores the model (and updates the project's last model), **Discard** deletes the files. Trying three sets of hyper-parameters therefore leaves one model behind, not three. Until you decide, the files sit in `ASSET_DIR/dl/pending/<job>/`; starting another training discards whatever was left there.
6. **Use it**: the saved model appears in the asset library (kind=model). Add a DL tool to a flow, select that model, and paste the class list into labels — the trainer reports the parameters it suggests, and the built-in classifier's pre-processing matches the tool's defaults exactly, so the rest can stay at their defaults.

### Quick register {#quick-register}

**Quick register** is the shortest path for a box teaching project: add at least two images, review the proposed boxes, name the asset, and start from the existing training panel. The server stores proposed boxes on previously unlabelled samples, chooses a conservative preset, and starts the same training job used by the normal path. Nothing is saved to Assets until the finished job is named and kept.

- It is available only for box projects with at least one class and at least two samples.
- The preset is intentionally small and short: size `n`, `epochs=20`, `batch=4`, `patience=8`, `lr0=0.001`, `val_ratio=0.2`, `workers=0`, no rotation, no flip and no image mixing. The input image size is selected from the samples: `320`, `480` or `640`.
- The response includes `job_id`, `labeled`, `skipped` and `params`, so the exact settings can be reviewed and reused for a normal retrain.
- Failure states are deliberate: `422` when samples, classes or boxes are missing, `409` when another training job is running, and `403` without the DL feature permission.

**The deep-learning templates in the gallery**: "AI object count (stock model)" and "AI instance segmentation: sign area" need no training at all, using the COCO stock models. "Classification: good / missing hole" and "Semantic segmentation: scratch area" use the demonstration models that `seed_demo` trains with the built-in trainers (the assets "Example: classifier (good / missing hole)" and "Example: segmenter (scratch)"), showing how a taught model gets into a flow. See [Example templates](samples.md).

## 2. Automatic labelling {#auto}

Labelling is the slowest part of getting started, so every trainer can implement `suggest()`: a proposed class and a confidence for each unlabelled sample. The built-in classifier uses **cosine kNN (k=3) in feature space**, which becomes useful after a handful of images per class, answers instantly and needs no training first.

- Press "Auto label" and the unlabelled thumbnails get a dashed proposal (`NG? 87%`). "Accept all" writes them in bulk, or click individual ones to relabel.
- Automatically labelled samples are recorded as `labeled_by=auto` (the thumbnail shows `~87%`, and the "auto-labelled (unconfirmed)" filter finds them for review); relabelling by hand makes them `human`.
- Only `human` labels are used as kNN references, so automatic labels cannot reinforce themselves.
- **Network trainer proposals** (ai_seg, ai_detect, ai_obb, ai_cls): once trained, the last best.pt is used; before that, the stock model (COCO or ImageNet) proposes, and any class whose name does not match is attached to the first class for you to correct.
- **Whole-image proposals** (the "Whole-image proposals" button on a shapes project, `POST /auto-label {"method": "sam"}`): this works with no model at all — SAM2 segments the whole image (up to 30 regions, largest first, skipping anything covering the entire frame) and every proposal is attached to the first class, 20 images at a time (`remaining` in the response says whether to press again). About 1.6 seconds per image on a GPU.
- **Smart select and smart box** (S and X in the labelling editor): click an object or drag a box and SAM2 (`sam2.1_t.pt`; `VISION_SAM_MODEL` can select sam2.1_s, b or mobile_sam) returns its outline — about 60 ms per click on a GPU. The weights download on first use, falling back to mobile_sam.pt if that fails.

## 3. Server resources and device settings {#devices}

Both training and inference use the **server's** resources. The top of the page shows the accelerators and GPUs detected (`GET /dl/devices`):

| Field | Contents |
|---|---|
| `providers` | This server's onnxruntime execution providers (CPU, CUDA, DirectML, TensorRT and so on, depending on which onnxruntime package is installed). |
| `gpus` | NVIDIA GPU names, memory usage and utilisation (only where `nvidia-smi` is available; empty otherwise). |
| `preferred_providers` / `train_device` | The current choice (`PATCH /dl/settings`, administrator only). |

- **Inference**: `preferred_providers` decides the providers a dl_* tool builds its ORT session with (unavailable ones are filtered out and CPU is always last). Changing it clears the session cache and takes effect immediately. For GPU inference, replace `onnxruntime` with `onnxruntime-gpu` (or `onnxruntime-directml`) and select it here.
- **Training**: the device dropdown lists what the server has and the trainer supports (a trainer declares its `devices`; the built-in MLP is CPU and finishes in seconds).

## 4. The shapes labelling editor (segmentation and detection) {#shapes}

Models with label_mode=`shapes` — semantic and instance segmentation — use the **labelling editor**: several polygon or bounding-box instances per image, each with a class. Coordinates are always stored **normalised 0–1** (matching the label txt files) and converted to pixels only for the canvas.

- **Editing**: a **rail of large icons** on the left of the canvas (select, polygon, box, refine, delete, undo, each showing its shortcut), a status bar above it (previous and next image, sample size, label count, drawing hints, an unsaved indicator, the shortcut list, save) and **large class buttons** (a colour dot, the number key and a count).
- **A polygon is drawn point by point, with no limit**: press N (or use the rail) and each click adds a vertex, with the polyline and a dashed line to the cursor drawn live. **Double-click**, **click the first point** or press `Enter` to close it; `Backspace` removes the last point and `Esc` cancels. When it closes you return to select mode with the new shape selected, so you can drag vertices, double-click an edge to insert a point, or Alt-click to delete one. A box (B) is still dragged out.
- **Smart select (it traces the outline for you)**: press S (the wand) and **click an object**; the server segments it, simplifies the outline into a polygon and attaches the current class, and you can go straight on to the next object. Ctrl+Z undoes. The default weights are `mobile_sam.pt` (about 40 MB, downloaded to `ASSET_DIR/dl/weights/` on first use) and it needs `pip install ultralytics onnx onnxslim` — the same optional dependencies as ai_seg, with the command shown if they are missing.
- **Smart box (X)**: drag a rectangle around an object and SAM2 returns the outline of what is inside it — a box says "which one" more precisely than a click. Stay in the mode to keep boxing.
- **Other keys**: Delete removes a shape, Ctrl+Z undoes, Ctrl+S saves (switching image intercepts unsaved changes); V/N(P)/B/S/O for the tools, ←/→ to change image, 0–9 to set the class.
- **Refine (snap to edges)**: pure front-end JavaScript — on a grayscale gradient image scaled to a longest side of 1280, search along each vertex's normal for the strongest edge (with a displacement penalty), iterate three times, smooth, and simplify with Douglas–Peucker to at most 120 points. It does not save automatically, and Ctrl+Z undoes it.
- **Reviewing from the thumbnail wall**: the thumbnails on the left draw the label outlines, so you can see at a glance which images were labelled badly. Ones with an automatic proposal show a "?".
- **Automatic labelling**: in shapes mode a proposal is a whole set of shapes for the image, drawn semi-transparent in the editor and on the thumbnail. Accept one image at a time or all of them; accepted proposals are marked auto, awaiting review.

## 5. Dataset management (de-duplication, splits, versions) {#dataset}

- **Duplicate detection**: every sample stores the SHA256 of its decoded pixels (`DlSample.sha256`), and uploads, zip imports, source bursts and folder imports are all de-duplicated within the project, reporting a `duplicates` count. Grabbing N frames of a static scene keeps one.
- **train/val/test splits**: the Dataset panel on the right shows the count in each. "Auto split" takes validation and test ratios and assigns **stratified** at random (by class for classes projects, by whether anything is labelled for shapes projects), reassigning every sample. An individual sample's **split chip** in the workspace status bar cycles through train → val → test → unset, the thumbnail grid shows a corner badge, and the filter dropdown can show one split at a time.
- **How training uses them**: samples marked `val` become the validation set (without any, a random fraction is taken by ratio), and samples marked `test` **never enter training** — they are held back for a blind check afterwards, reported as `test_holdout`. The temporary dataset ai_seg exports respects the same assignment (unassigned samples fill val at random).
- **Freezing a version**: "Freeze" exports the current samples, labels and splits as a zip into the **asset library (kind=dataset)** along with statistics (total, per class, per split) — an images/labels tree for shapes projects (images/labels/{train,val,test} plus data.yaml) and class folders with a manifest.json for classes projects. Versions can be downloaded or deleted (which deletes the zip too).

### Creating samples from video {#video-extract}

The capture client can record each channel locally, upload the file to `DATA_DIR/videos/<client>/`, or write directly into that server folder when both programs run on the same machine. The DL page lists these files with `GET /api/vision/videos`.

For an instance-segmentation project, the "Create samples from video" panel runs a background extractor: record → upload → extract → correct labels in the existing shape editor → train → choose the new model in the flow. Extraction processes every `stride`th frame, runs the current segmentation model, applies the edge margin filter, then tracks objects with a private state overlay so no flow variable is changed.

Per track, the first confirmed object saves one whole-frame sample; after that, another sample is saved every `k` processed frames until `n` samples have been saved for that track. Defaults are `n=3` and `k=5`. Every saved sample carries all accepted polygons from that frame, normalised to 0-1, and project classes are extended when the model returns a new class name. SHA-256 de-duplication is the same as uploads and imports, so rerunning the same video does not duplicate samples.

## 6. Built-in models and augmentation {#builtin}

| kind | Task / labels | How | Inference tool | Dependencies |
|---|---|---|---|---|
| `mlp_classify` | Image classification (classes) | An MLP trained in numpy, exported as hand-built ONNX, with pre-processing identical to the tool's defaults. Full-batch gradient descent with **learning-rate protection**: if in the first 10% the loss sits at ln(k) and accuracy is chance (a large learning rate has killed the hidden layer), the rate is cut to a quarter and it restarts, up to three times (metrics.lr_restarts). It sees the whole downscaled image, which suits classes that differ in overall appearance; for small defects in random positions use patch_segment or instance segmentation | dl_classify | None (built in) |
| `patch_segment` | Semantic segmentation (shapes) | A patch classifier (background plus each class) trained in numpy, exported as a **fully convolutional ONNX** (Conv k×k → Relu → Conv 1×1, accepting any input size). Seconds on CPU. Suits colour- and texture-defined regions and defects | dl_segment (labels start with background) | None (built in) |
| `retrieval` | Image retrieval classification (classes) | Builds a self-contained reference library from labelled images. Each saved reference keeps a compact signature, a class index and a thumbnail; at run time the closest references vote by similarity. New classes are added by adding images to the library, not by running a new teaching cycle. The panel reports leave-one-out self-check accuracy so the user can see whether the library is clean enough before using it on a line. | dl_retrieval (label, similarity, top matches) | The same reference matcher file used by the good-parts tool; the saved library carries a copy so another station can run it without a download. |
| `ai_seg` | Instance segmentation (shapes) | The instance-segmentation network: samples from the database are staged into a training dataset (box labels become four-corner polygons), trained with callbacks reporting progress, loss, the mAP curves and the log (interruptible, and what has trained is still saved and exported), producing **two assets, best.pt and ONNX** — the .pt is the main product and the project's last_asset, and the ONNX asset's name gets "(ONNX)". A copy of best.pt is kept for automatic labelling and further training. Stock models download to `ASSET_DIR/dl/weights/` on first use | **ai_segment** (.pt, GPU) or dl_instance (ONNX) | **Optional**: `.\scripts\setup_dl.ps1` (requirements-dl.txt; torch cu128, ultralytics and onnxruntime-gpu, about 3 GB — see §11) |
| `ai_detect` | Object detection (shapes) | Bounding boxes (a polygon becomes its bounding box) trained with the detection network from the stock model. The fastest, and the cheapest to label | **ai_detect** or dl_detect |  |
| `ai_cls` | Image classification (classes) | Samples are written into a classification dataset (`train/<class>/`; **the class index follows folder order**, and the tool reads model.names), then the classification network is fine-tuned from the stock model. More accurate than the built-in MLP | **ai_classify** or dl_classify (the ONNX already includes softmax) |  |
| `anomaly` | Anomaly detection (good pictures only; unlabelled and first-class samples count as good) | PatchCore-style: a pre-trained ResNet18 backbone (layer2 + layer3 features, shipped as `ASSET_DIR/dl/weights/resnet18_l2l3.onnx`, never downloaded at run time) turns every good picture into patch features; a greedy coreset keeps 10% as the memory bank (with a fixed 128-dim random projection so run time stays short); the automatic threshold is mean + k·σ of the good pictures' own leave-one-out scores. Samples labelled with any other class are scored for a sanity check (AUROC). Seconds on CPU, no back-propagation. Automatic labelling here means *data cleaning*: unlabelled samples get an anomaly score so the odd defective part that slipped into the good set can be found | dl_anomaly (score map, mask, regions) | The backbone file (from the deep-learning pack, or `manage.py anomaly_backbone --export` on a machine with torch and torchvision) |
| `ai_obb` | Oriented boxes (shapes) | A polygon becomes its minimum-area rotated rectangle and a box its four corners, trained with the oriented-box network from the stock model | **ai_obb** (the ONNX is for external use only) |  |

### Reference library classification {#retrieval-library}

A retrieval project is for lines where classes keep growing. The right panel says **Build library**, not train: it scans the labelled images, stores one reference per original image and optional light variants, then saves a single `.npz` asset. That asset contains the class list, normalised reference matrix, label index per row, thumbnails and the matcher bytes, so it is portable between stations.

The runtime tool `dl_retrieval` compares the incoming ROI to the library, returns the top matches, and chooses the label by weighted voting across the nearest references. `min_similarity` sends weak matches to `not_matched` with status `ng`; `expected` turns the chosen label into an `ok`/`ng` judgement. The DL page can add another labelled image directly to the saved library, which is how a new class is introduced without rebuilding everything.

**Augmentation** (the "Augment" group of hyper-parameters, off by default so nothing existing changes): mlp_classify adds horizontally flipped and brightness-jittered copies to the training set only, reporting the `augmented` count; patch_segment additionally samples from a flipped version of each image, with the labels flipped to match; and the four network trainers expose `degrees`, `fliplr` and `mosaic` directly (classification has no mosaic).

**The inference tools** `ai_detect`, `ai_segment`, `ai_classify`, `ai_pose` and `ai_obb` use native network inference (torch, using the GPU automatically; `device` auto/cuda/cpu and `half`). The model is either a .pt asset trained on the teaching page (or a .pt/.onnx you uploaded), which takes priority, or a stock model chosen by size in the parameter (the stock weights download on first use). Models are cached in process (`apps/vision/dl/yolo_runtime.py`, six at most, with inference on one model serialised). Pose currently has only the inference tool — training it needs a keypoint labelling interface that does not exist yet.

The training panel shows the **loss and mAP curves** (mask metrics first for segmentation; fitness can exceed 1, and the axis scales itself) and an **incremental training log** (a 400-line ring buffer, `GET /dl/train/status?log_from=N`).

### Registration detection without training {#registration}

**Registration detection** finds parts from a few cropped example pictures. Add fewer than ten pictures under Registered pictures, each containing one target with a small background margin. Optional Excluded pictures describe lookalikes that must not count. No training project, labels or fitted model are needed. The feature model supplied in the deep learning add-on pack must already be installed; nothing is downloaded during inspection.

On the tool page, **Add from current image** beside a Registered pictures field lets you draw a rectangle or rotated rectangle on the current preview image and saves that crop directly into the list.

Use Detect to select Found or Not found, Count to accept an inclusive minimum and maximum count, or Presence to check an expected Present or Absent state. The tool returns labelled matches, count, best similarity and position, and a presence flag. No match gives zero best similarity and no valid best position. A missing feature model or registered picture is a setup error; an empty search region or a region smaller than the target simply produces no matches.

The search region may be rectangular or rotated. Relative sizes such as `0.8,1.0,1.25` and an angle range cover size and pose changes; either angle setting at zero disables rotation. Minimum similarity is the main adjustment. Minimum and maximum side length filter the reported boxes; zero disables a size limit. Maximum overlap removes duplicate boxes across pictures, sizes and angles. Max results caps the returned count, so keep it above the largest number that could occur when checking for excess parts.

The tool searches a spatial feature grid at a working size of 320, with registered grids resized for each size and angle. Positions are approximate at the grid spacing; a smaller search region helps with small parts. All reported boxes and overlays use full input-image coordinates. Reference features and the feature-model session are cached. The example `register_count`, *Count parts by registration*, crops its reference from the first synthetic parts picture: three pictures contain three parts (accepted), and the fourth has only two (rejected).

Choose Template match for stable appearance and precise positioning, Shape match when outlines remain stable as lighting changes, and DL anomaly detection when good examples must reveal previously unseen defects. Train a detection model when the target classes need broader variation or stronger separation than a few registered examples provide. Registration detects similar targets; it does not learn a general defect boundary.

## 7. Label dataset export and import {#interop}

Labels live in the database, but they move both ways with txt label datasets, in a format compatible with the labelling tool used elsewhere in the family (**tab separated, LF line endings, read as utf-8-sig, six decimal places**; five columns is a box, an even number of coordinates from seven up is a polygon):

```
POST /api/vision/dl/projects/{id}/dataset-export   {"dir": "D:/TrainingImage/NEW", "val_ratio": 0.2}
POST /api/vision/dl/projects/{id}/dataset-import   {"dir": "D:/TrainingImage/ATD3"}
```

- Export writes images/labels/{train,val} plus data.yaml (an existing data.yaml is left alone) and clears `labels/*.cache` afterwards — a trap of the training library.
- Import accepts either a `root/` or a `root/dataset/` layout and any split subfolder. Classes in data.yaml that the project does not have are added, and duplicate images (by pixel hash) are skipped.
- **In the interface**: "Export labels" and "Import labels" in the Dataset panel on the right (shapes projects; give a folder path on the server's own machine).

### The built-in classifier in detail {#mlp}

| Item | Detail |
|---|---|
| kind | `mlp_classify` (label mode `classes`; the result is used by `dl_classify`) |
| How | Samples are resized to the input size (32–128), converted to RGB and normalised with the ImageNet mean and standard deviation (matching the tool's defaults), then fed to a single-hidden-layer fully connected network trained by full-batch gradient descent in numpy, with a stratified validation split |
| Export | Hand-built ONNX (`Flatten→MatMul→Add→Relu→MatMul→Add`, weights as initializers; `apps/vision/dl/onnx_io.py`, so neither onnx nor torch becomes a dependency) |
| Hyper-parameters | Input size, hidden width, epochs, learning rate, validation ratio — all with sensible defaults |
| Suits | Telling appearances apart: front versus back, model variants, an obvious defect being present or not. The features are raw pixels, so where lighting or position varies a lot, crop to an ROI and use a larger input size. |

## 8. Extending: a new model kind (Trainer) {#extend}

The same pattern as tools, sources and connections: subclass `apps.vision.dl.base.Trainer` and drop it in `plugins/` (see [Plugins](/docs/plugins.html)). Project creation, labelling, the hyper-parameter form and the training panel are all driven by the `GET /dl/trainers` catalogue — **a new model needs no front-end change**.

```
# plugins/my_trainer.py — drop it in plugins/ and it loads
from apps.vision.dl.base import SampleRef, Suggestion, Trainer, TrainError, TrainResult
from apps.vision.tools.base import Param

class MyTrainer(Trainer):
    kind = "my_model"
    label = "My model"
    description = "…"
    label_mode = "classes"        # a closed set: classes (one class per image) | shapes (polygon/box instances)
    tool_key = "dl_classify"      # which tool consumes the result
    devices = ("cpu", "cuda")     # training devices supported (intersected with what the server has)
    params = [Param("epochs", "Epochs", kind="number", default=100)]

    def train(self, samples, classes, params, device, progress):
        # progress(0..1, "stage", metrics): call it regularly; it raises TrainCancelled on cancellation
        ...
        return TrainResult(onnx_bytes=..., metrics={...}, tool_key="dl_classify",
                           tool_params={"labels": "\n".join(classes), ...})

    def suggest(self, labeled, unlabeled, classes, params):  # automatic labelling (optional)
        return [Suggestion(sample_id=s.id, label="OK", score=0.9) for s in unlabeled]
```

- Ship a requirements.txt for heavy dependencies such as torch (see [Integration considerations](/docs/plugins.html#integration)), import them lazily inside `train()`, and raise `TrainError` with the install command when they are missing.
- The product must be **ONNX bytes** — that is the only contract between training and inference. Inference always goes through onnxruntime, so a trainer may use whatever framework it likes.
- `label_mode` is a closed set: adding one means extending the backend set and the labelling interface together, while the rest of the interface carries on unchanged.

## 9. API {#api}

```
GET    /api/vision/dl/trainers                     the trainer catalogue (the front-end forms come from this)
GET    /api/vision/dl/devices                      providers, GPU information and the current settings
PATCH  /api/vision/dl/settings                     administrator, {"providers": [...], "train_device": "cpu"}
GET    /api/vision/dl/projects                     the project list, with counts
POST   /api/vision/dl/projects                     {"name", "trainer_kind", "classes": [...]}
GET/PATCH/DELETE /api/vision/dl/projects/{id}      removing a class returns its samples to unlabelled
GET    /api/vision/dl/projects/{id}/samples        filter with ?label= and ?split=
POST   /api/vision/dl/projects/{id}/samples        multipart files[] (an optional label; a zip is accepted; duplicates are reported)
POST   /api/vision/dl/projects/{id}/samples/from-source   {"source_id", "count", "label"?}
GET    /api/vision/dl/samples/{id}/file            a thumbnail (?max=; for <img>, so the token goes in the query)
PATCH  /api/vision/dl/samples/{id}                 {"label"} or {"shapes"} (empty clears it) or {"split": "train|val|test|"}
DELETE /api/vision/dl/samples/{id}
POST   /api/vision/dl/projects/{id}/labels         bulk labelling, {"items": [{"id","label","score"?,"by"?}]}
POST   /api/vision/dl/projects/{id}/auto-label     {"method"?: "model"|"sam", "max_samples"?, "max_masks"?} → proposals (not stored until accepted); sam returns remaining
GET    /api/vision/videos                          server video list (name, path, size, duration, source)
POST   /api/vision/dl/projects/{id}/video-extract  {"video"|"video_path", "params": {"max_per_track", "frame_interval", "stride", "confirm_frames", "split"?}}
GET    /api/vision/dl/projects/{id}/video-extract/status?log_from=N
POST   /api/vision/dl/projects/{id}/video-extract/stop
POST   /api/vision/dl/projects/{id}/split          auto split, {"val": 0.15, "test": 0.1, "seed"?}, stratified
GET/POST /api/vision/dl/projects/{id}/versions     list versions / freeze one, {"name"?, "note"?} (the zip goes to the asset library)
DELETE /api/vision/dl/versions/{id}                delete a version (and its zip asset)
POST   /api/vision/dl/projects/{id}/sam-point      smart select, {"sample_id", "points"?: [[x,y] 0..1], "labels"?: [1|0], "boxes"?: [[x0,y0,x1,y1]], "model"?} → {shapes, model}
POST   /api/vision/dl/projects/{id}/quick-register 202 {"device"?, "asset_name"?} → {"job_id","labeled","skipped","params"}; 422 if not enough samples/classes/boxes, 409 while one is running
POST   /api/vision/dl/projects/{id}/train          202 {"params", "device", "asset_name"}; 409 while one is running
GET    /api/vision/dl/train/status?log_from=N      poll progress (progress, stage, metrics, the history curves, the incremental log; pending/saved/discarded)
POST   /api/vision/dl/train/save                  {"name"?} keep the trained model: creates the asset(s) and updates the project; 409 when nothing is waiting
POST   /api/vision/dl/train/discard               drop the trained model (deletes the pending files)
POST   /api/vision/dl/train/cancel
```

Permissions: reading, labelling and training are open to any signed-in user (and to an integrator key); training additionally passes `can_execute()` (423 while the engine is locked); device settings are administrator only.

## 10. Internals and the trade-offs {#internals}

- `apps/vision/dl/`: `base.py` (the trainer registry), `builtin.py` (the MLP classifier and the lightweight segmenter), `yolo.py` (the network trainers, imported lazily), `shapes.py` (shape validation, label txt conversion, rasterisation, dataset export and import), `onnx_io.py` (hand-built ONNX, including Conv and initializers), `sam.py` (SAM-assisted labelling, imported lazily with a cached session), `quick.py` (the quick-register flow layer), `video.py` (video-to-samples background extraction), `devices.py`, `jobs.py` (the training job with its history and log ring buffer) and `api.py`. On the front end, `DlPage.tsx`, `components/dl/ShapeWorkspace.tsx` (reusing the ImageViewer's ROI editing), `components/dl/VideoExtractPanel.tsx` and `components/dl/optimize.ts` (the edge snapping).
- Data model: `DlProject`, `DlSample` (image files in `ASSET_DIR/dl/<project_id>/`, written with imencode + tofile so non-ASCII paths work; `sha256` for de-duplication and `split` for the split), `DlDatasetVersion` (statistics plus the asset id) and `DlSettings` (a single row).
- **The trade-offs against a Roboflow-style specification**: the features are all here — de-duplication, splits, versions, augmentation, SAM-assisted labelling, training metrics — but the architecture stays inside the platform's constraints. Celery and Redis became **a single training slot on a background thread** (teaching does not need a queue or new infrastructure); React-Konva became the existing **two-layer canvas ImageViewer**; DRF stayed django-ninja; and SQLite with WAL and 0–1 normalised JSON coordinates were platform conventions already. Text-prompted grounding models and TorchScript export are not included (auto-labelling is covered by each trainer's suggest(), and ONNX is the one contract between training and inference); a plugin trainer can add them.
- **One training slot**: one training at a time, on a background thread outside the inspection pool, with a second request returning 409. Training is a teaching-time activity and does not need a queue; progress is polled every 700 ms rather than going through the SSE bus.
- **Providers are a hot-path setting**: a DL tool building a session reads only the in-memory cache (`devices.preferred_providers()`). The database is touched at start-up and by the settings endpoint, which calls `clear_sessions()` so sessions are rebuilt.
- **torch is not a dependency**: the built-in trainers train in numpy and export hand-built ONNX, so the platform's dependencies do not change. Heavy frameworks belong to plugin trainers, with their own requirements or a sidecar.
- Tests in `tests/test_dl_teach.py`: ONNX export end to end through dl_classify, too few samples, automatic labelling accuracy, the labelling API flow, the background training job (a TransactionTestCase), split and augmentation behaviour, de-duplication and zip import, auto split, version freezing, and the message when SAM's dependencies are missing.

## 11. Installing, and the traps (torch, ultralytics, onnxruntime-gpu) {#install}

The deep-learning dependencies are **optional**: the platform starts without them (the ONNX dl_* tools run on CPU; the ai_* tools and SAM report that they are not installed). For GPU training and inference:

```
.\scripts\setup_dl.ps1              # CUDA 12.8 wheels (required for RTX 50); -Cuda cu126 for others; -Cpu for a machine with no GPU
.\.venv\Scripts\python.exe manage.py dl_check --predict   # verifies torch/CUDA, the kernel architectures, ultralytics, the ORT providers, and runs a stock model
```

The order matters: install torch from the pytorch.org index **first**, then `requirements-dl.txt`. On an **installed station** none of this is typed: the vendor builds the add-on pack once (`scripts\build_dl_pack.ps1 -Cuda cu128` or `-Cpu`; torch from the PyTorch index, the rest frozen into a lock file, the stock detection and SAM2 weights included) and the station installs it offline with `vsctl dl install VisionSequence-DL-cu128-<ver>.zip -Predict`, which removes the CPU onnxruntime, installs torch before the rest, copies the weights into `data\assets\dl\weights`, records the pack in the version tree so `vsctl update` reinstalls it, and runs `dl_check` ([deployment §12](/docs/deployment.html#dl)). Every row below has been reproduced on this machine:

| Symptom | Cause | Fix |
|---|---|---|
| Training only uses the CPU; `torch.cuda.is_available()` is False | A plain `pip install ultralytics` pulls the CPU build of torch from PyPI | `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128` first, then ultralytics. `dl_check` flags a torch build ending in +cpu |
| The first inference throws `no kernel image is available for execution on the device` | RTX 50 (Blackwell, sm_120) has kernels only in cu128 wheels and later | `setup_dl.ps1 -Cuda cu128`; `dl_check` compares against `torch.cuda.get_arch_list()` |
| CUDA is in the providers list but the session ends up on CPU, or `cublasLt64_13.dll is missing` | onnxruntime-gpu 1.23 and later link against **CUDA 13**, while torch cu128 ships CUDA 12.8 DLLs | Pin `onnxruntime-gpu==1.22.0` (CUDA 12, cuDNN 9). The code also does `import torch` and `onnxruntime.preload_dlls()` before building a CUDA session (`tools/builtin/dl.py`) |
| The providers list changes from run to run | `onnxruntime` and `onnxruntime-gpu` share an import name, and installing both shadows one with the other | `pip uninstall -y onnxruntime` and keep only onnxruntime-gpu; `dl_check` reports when both are installed |
| Processor acceleration never appears as an option | The processor acceleration package is a third onnxruntime build, and it also shares the same import name | Install exactly one runtime package: uninstall `onnxruntime` and `onnxruntime-gpu`, then install `onnxruntime-openvino`. It exposes `OpenVINOExecutionProvider`, which the product labels as processor acceleration. Installing more than one runtime package makes whichever wheel was installed last shadow the others, so the provider list can change after an upgrade or repair install. |
| Exporting ONNX prints "requirement onnxruntime not found, attempting AutoUpdate" | ultralytics checks for the package name onnxruntime while onnxruntime-gpu is what is installed; with `YOLO_OFFLINE=1` it is only a warning | Ignore it — and do not let it AutoUpdate, which would pull the CPU build |
| Training hangs | On Windows, DataLoader worker processes (spawn) started from inside a background thread deadlock | Leave the `workers` hyper-parameter at 0 (the default) |
| The first training on an offline machine hangs downloading | ultralytics checks the network itself | The code sets `YOLO_OFFLINE=1`; stock models are downloaded by `yolo.resolve_model` from GitHub assets into `ASSET_DIR/dl/weights/` (trying v8.4.0 then v8.3.0). Offline, put the files there by hand |
| "sam2 module not found" | Facebook's sam2 package is not needed | ultralytics has SAM2 built in (sam2.1_t/s/b/l.pt), selected with `VISION_SAM_MODEL` |
| Classes come out wrong after classification training | An ultralytics classification dataset takes its class indices from **folder order**, not the project's class order | The trainer writes the labels back from `model.names` (metrics.classes); follow the same order in your own code |
| predict prints "'half' is deprecated" | ultralytics 8.4 warns even for `half=False` | Only pass half=True when half precision is actually requested |

The combination verified in September 2026: Python 3.12, torch 2.11.0+cu128, torchvision 0.26, ultralytics 8.4.137, onnx 1.22, onnxslim 0.1.96, onnxruntime-gpu 1.22.0. On an RTX 5070 Ti: the stock nano model at 640 takes about 10 ms (torch) or 7.5 ms (ORT CUDA), SAM2.1-t is 60 ms per click and 1.6 s for a whole image, and one epoch of each of the four trainers on a synthetic dataset takes about 40 seconds in total, export included.

### The anomaly-detection backbone {#install-anomaly}

The `anomaly` model kind needs one file that is not a Python package: `ASSET_DIR/dl/weights/resnet18_l2l3.onnx`, the ImageNet-pretrained ResNet18 cut after layer3 (about 11 MB). The deep-learning pack carries it and `vsctl dl install` copies it into place; on a development machine with torch and torchvision, `manage.py anomaly_backbone --export` writes it, and `manage.py anomaly_backbone --check` runs it once and reports the providers. Nothing is downloaded at run time: without the file, training the anomaly kind fails with a message that names the path, and the anomaly template loads with the model left for you to pick.
