# Glossary and naming rules

One thing, one name — identical in the interface, in the code and in these documents. Add a new term to this table before you use it. The Chinese column is the wording used by the zh-Hant locale, which the translations must follow.

## Pages (sidebar and routes) {#pages}

| Name | Chinese | Route | Component | What it is |
|---|---|---|---|---|
| Overview | 總覽 | `/` | DashboardPage | Left: a vertical list of flow cards (click to watch; editor and statistics are small icon buttons). Middle: the live image of the selected flow. Right: live inspection detail. With no events it shows the last run (`GET /flows/{id}/recent`, which includes preview runs from the web interface) and subscribes to that flow's SSE for updates. Any flow the user can see can be watched. |
| Flows | 流程 | `/flows` | FlowsPage | The flow list |
| Flow editor | 流程編輯器 | `/flows/:id` | FlowEditorPage | Canvas, image viewer and inspector |
| Tool page | 工具頁 | `/flows/:id/tools/:nodeId` | ToolPage | A page dedicated to tuning one step. Left: parameters. Middle: the image before and after, with reference information below (histogram, statistics and series side by side). Right: the buttons (save, run to this step, auto apply, reuse image, scratch image). By default nothing runs until you press "Run to this step"; auto apply can be turned on. If the step has an ROI parameter with a value, it appears draggable as soon as you open the page. Parameters go into the shared draft; only Save writes them back, and Back only asks for confirmation when there really are unsaved changes (saving becomes the new baseline). |
| Image sources | 影像來源庫 | `/sources` | SourcesPage | Cameras, folders and synthetic sources, with user-defined groups (ResourceGroup: a manage-groups dialog, filter chips, a group dropdown). Folder and file paths can be picked with the server file browser (GET /vision/fs). Cameras come from the capture client: "Download capture client" plus the "capture client camera" kind (pick a client and a channel, GET /capture/clients). |
| Assets | 資產庫 | `/assets` | AssetsPage | Template images, model files and dataset archives, with the same user-defined groups as sources (`PATCH /assets/{id}`) |
| Tool library | 工具庫 | `/tools` | ToolLibraryPage | The station's composite tools: create, edit (opens the tool's canvas), save a copy, export and import `.tool.json`, delete (blocked while a flow uses it). Editing needs the `tools.edit` feature |
| Users | 使用者 | `/users` | UsersPage | Account management (administrators) |
| Settings | 設定 | `/settings` | SettingsPage | Keys, theme (light, dark, Cyberpunk or follow the system — the preview cards are the only place to switch, and a signed-in user's choice is stored with `PATCH /auth/prefs`), language (English, 繁中, 简中), the engine lock and the password |
| Help | 說明 | `/help` | HelpPage | Definitions and how-to |
| Sign in | 登入 | `/login` | LoginPage | Sign in, or create the first administrator |
| Statistics | 統計 | `/flows/:id/stats` | StatsPage | One flow's run history, yield, hourly OK/NG and duration trend (reachable from the dashboard card and the editor toolbar) |
| Batch test | 批次測試 | `/batch` | BatchPage | Image sets, batch runs, insights, tuning and comparison |
| Deep-learning teaching | 深度學習教導 | `/dl` | DlPage | Teaching projects, samples, labelling, training and export |
| AI assistant | AI 助手 | `/agent` | AgentPage | Image plus ROIs plus a prompt, in and a runnable flow out |
| Golden Set | Golden Set | `/flows/:id/golden` | GoldenPage | Cases, expectations, regression and baselines |
| Teach page | 參數卡 | `/flows/:id/teach` | TeachPage | Every teaching parameter in the flow, grouped by step |
| Integration | 外部整合 | `/integration/*` | IntegrationLayout | One page per integration method, expanding into a tree in the sidebar |

## Parts of the flow editor {#editor}

| Name | Chinese | Component | What it is |
|---|---|---|---|
| Toolbar | 頂列 | EditorToolbar | Two rows. First: the flow name, Save, the template dropdown, Recipes (opens the drawer), the bound-recipe dropdown (only when recipes exist), the "not commissioned" tag, and icons for the teach page, Golden Set, export and statistics. Second: preview, re-run with the last image, upload a scratch image, batch test, continuous, reset and the help dropdown. Buttons are an icon plus short text and wrap when there is no room. Select/pan is in the top-right corner of the canvas. |
| Tool palette | 工具箱 | ToolPalette (FavoriteTools + ToolPicker) | Top of the left column: an "Add tool" button plus the favourites list (click to insert at the centre of the canvas, or drag). The button opens the "Choose a tool" dialog: categories on the left, a grid of tool cards in the middle, and the full description of the selected tool on the right, searchable and favouritable; a click inserts it. |
| Step menu | 步驟選單 | NodeContextMenu | Right-click a step: open the tool page, duplicate, disable/enable, delete, copy or paste parameters (same type only) |
| Recipe drawer | 配方面板 | RecipeDrawer (`components/recipes/`) | Opened from "Recipes" on the flow list and "Manage recipes" on the teach page: the binding dropdown, add (optionally "use the current graph values as overrides (teaching parameters)"), rename, duplicate, delete, set as bound, export, export all, import, and an expandable override table. Saving and adding both go through the save-scope checklist. |
| Save-scope checklist | 儲存範圍 Check List | RecipeCheckList (`useSaveCheck`) | Before adding or saving a recipe it calls `POST /recipes/check` with `include_all: true`, so every declared parameter in the flow is listed — anything the overrides do not mention appears as unchanged at its graph value — as "step › parameter: current → new" with a status. Two sections: teaching parameters on top (teach=true; ok is ticked by default, unchanged is not) and a collapsed "Other parameters (N)" below (teach=false, collapsed and unticked, tickable once expanded; an ROI value is summarised as "rect 286×215 @ 373,277"). version_changed can be ticked; anything else in red cannot. The value sent for a ticked row is the value shown, so unchanged means the graph value. "Use the current graph values as overrides" runs through the same list. |
| Import check | 匯入合理化檢查 | RecipeImportModal | Before importing recipes, `POST /recipes/import/check` shows whether the flow name and fingerprint match and a checklist per recipe. Tick and send `POST /recipes/import {doc, accept}`; the result says how many were written and how many skipped. |
| Bound recipe | 綁定配方 | BoundRecipeSelect / BoundBadge | "The recipe currently bound for execution" = `is_default`. Selectable on each flow row, in the editor toolbar and in the recipe drawer. "No recipe (graph values)" clears is_default. Run once, continuous and external triggers without a `recipe` all use the bound one. Shown as "Bound: partA". |
| Navigation groups | 側欄分組 | AppShell (localStorage `vs.navOpen`) | Inspection (flows, batch test, AI assistant), Teaching (calibration, deep learning) and Resources (sources, assets); a group is a heading, not a page. Open by default, remembered per browser, and flattened when the sidebar is collapsed to icons. |
| Tree view | 樹狀檢視 | AssetTree / SourceViews (`vs.assetsView`, `vs.sourcesView`) | The asset and source libraries list by kind → group → item, with cards as the alternative. The tree is the default in both. |
| Sidebar collapse | 側欄摺疊 | AppShell (localStorage `vs.sidebar`) | The main menu switches between icons only and icons with labels; labels never wrap. Collapsed, hovering shows a tooltip. There is a collapse button in the top bar and at the bottom of the sidebar. |
| Panel | 面板 | Panel / Card | Content sits on a white panel with a thin border, a title bar with action icons on the right, and optional collapsing. Statistics KPIs use a Tile: a big number with a small label. |
| Template gallery | 範本畫廊 | TemplateGallery | Template cards grouped by category (tutorial, counting, measurement, quality, defects, identification, custom) with a filter row, a source picker and a flow name; a built-in template defaults to "The template's sample pictures", which turns the acquire step into a Fixed image step cycling through them. Shared by the Flows page and the editor toolbar |
| Step list | 步驟清單 | NodeList | Bottom of the left column: every step in the flow; clicking focuses the canvas on it |
| Image viewer | 影像視窗 | ImageViewer | Top of the middle column: the image, the overlays and ROI editing |
| Canvas | 畫布 | FlowCanvas | Bottom of the middle column: the React Flow canvas, with select/pan in the top-right corner (`CanvasModePanel`, styled like the zoom slider) |
| Inspector | 側欄 | Inspector | Right column: the flow's shared settings, or the selected step's basics and "Open tool page" |
| Results panel | 結果分頁 | ResultsPanel | The Results tab in the inspector: recent runs (with an extra column when recipes exist), output values, errors and warnings (`RunWarnings`, the yellow notices from run.warnings) |
| Lock banner | 鎖定橫幅 | LockBanner | The yellow banner shown while the engine is locked |

## Machine vision vocabulary {#vision-terms}

The words the industry uses, and what each one means here. Coordinates, angles and the reference-versus-current pair come up in every locating, measuring and correction job, so they are worth pinning down before the product terms below.

| Term | Chinese | Definition |
|---|---|---|
| Image coordinate system | 影像座標系 | Origin at the top left of the picture, x to the right, y down, **angle positive clockwise**. Every ROI, every overlay and every coordinate a step outputs is in this system, at full-image scale — a step that works on a crop converts back before it reports. |
| Physical coordinate system | 物理座標系 | Millimetres on the table, or the numbers the machine works in. A calibration asset holds the transform between it and the image system; Real-world coordinates applies it. |
| Handedness | 左手／右手座標系 | Whether the second axis turns clockwise or anticlockwise from the first. The image system is left-handed (y points down); most machines are right-handed (y points up), which is why an uncorrected angle comes out mirrored. |
| Chiral consistency | 手性一致性 | Whether the image system and the machine system have the same handedness. A calibration that maps pixels to machine coordinates has to preserve it, otherwise every correction is mirrored — worth checking once when a station is set up, not once per part. |
| Physical point | 物理點 | A point converted out of pixels into the physical system by a calibration. |
| Single pixel precision | 單像素精度（像素當量） | How much of the real world one pixel covers, in millimetres per pixel (`mm_per_px` on a calibration). Smaller is finer; it sets the floor on what a measurement can resolve. |
| Pose | 位姿 | Where a found object sits and how it is turned — x, y and angle together. Locate offset compares the pose it was taught with the pose in this picture and outputs the difference as a transform. |
| Teaching point | 示教點 | The reference taken from a good part: the reference x, y and angle on Locate offset, or the position the machine was taught to go to. |
| Run point | 運行點 | Where the part actually sits on this run — what the locating step found. The correction sent to the machine is the difference between the teaching point and the run point. |
| Line and line angle | 線／線角度 | A line travels as its two end points. Its angle is measured from the +x axis, positive clockwise, like every other angle here. |
| Caliper | 卡尺 | A small oriented rectangle whose grey values are projected onto one axis, so a step change in the profile locates an edge to sub-pixel accuracy. Find lines, Find circles, Caliper, Wall thickness and Circular caliper all place rows of them; a caliper's height averages across the edge, its width sets how far it searches. |
| Detection area | 檢測區 | The region a step actually works in — its ROI, after any exclusion zones are cut out and after ROI follow has moved it. |
| Mask | 遮罩 | A single-channel picture where 255 means "use this pixel" and 0 means "ignore it". Apply mask turns a region into one; several tools output theirs so a later step can reuse the same shape. |
| Box | 檢測框 | A rectangle given as centre, width, height and angle. Match and detection results travel as boxes on the `matches` port. |
| Blob | 連通區域 | A connected run of pixels that pass the threshold. Blob analysis measures each one's area, centre, bounding box and circularity, and can filter and sort on them. |
| Centroid | 形心 | The mean position of the pixels or points in a region. For a symmetric shape it is the centre; for a chipped one it moves towards the remaining material. |
| Probability map | 機率圖 | A greyscale picture whose pixel values are the strength of a result rather than brightness — a segmentation's class confidence, an anomaly score. Threshold it and measure the result with Blob analysis. |
| Model | 模型 | Three different things share this word: a **shape model** taught from an outline, a **statistical template** built from many good parts, and a **trained network**. All three are assets; the tool that consumes one says which it needs, so check the kind before wiring it. |
| Colour space | 色彩空間 | How a colour is split into numbers. RGB mixes brightness into all three; HSV and HSI separate hue and saturation from intensity; Lab and YUV separate a luma channel from two colour channels. Judging colour under changing light is easier in any of the last three. |
| Solution | 方案 | Other platforms keep one file per station holding the flows, camera settings, communication and operator screen. There is no such file here: the station is the unit — its flows, sources, connections and settings, backed up together by `manage.py backup` and moved by flow export and import. |
| Industrial computer (IPC) | 工控機 | The fanless PC in the cabinet that runs the platform. One station, one API process. |
| Robot arm | 機械手臂 | The machine that acts on what the inspection found — it receives a corrected position, not a picture. |

## Core terms {#terms}

| Term | Chinese | Definition |
|---|---|---|
| Flow | 流程 | One inspection graph of nodes and edges. A flow belongs to the line, not to a person: anyone signed in can see it, and an engineer or administrator can edit it. |
| Node / step | 步驟 | One box on the canvas — an instance of a tool |
| Tool | 工具 | A kind in the palette (grayscale, blob, …); `key` is its unique identifier |
| Edge | 連線 | A line between steps: an output port to an input port |
| Port | 埠 | Inputs on the left of a step, outputs on the right; each has a type |
| Flow handle | 分支把手 | An output port of type `flow` (true, false and so on); it can only connect to a step's diamond-shaped control input |
| Port interface | 埠介面 | Per step, which input and output ports are drawn on the canvas, in what order, and under which published name; edited on the tool page and stored with the flow (`node.interface`) |
| Published output | 已發布輸出 | An output port given a name on the port interface; its value is returned with the run's named outputs under that name |
| Parameter | 參數 | A step's setting; the kinds are a closed set (number, select, roi, …) |
| Teaching parameter / teach page | 教導參數／參數卡 | A parameter that has to be adjusted on the line (a threshold, a polarity, a tolerance), marked `teach=True` in the tool definition. The teach page lists only these, grouped by step, so a changeover needs no canvas. |
| Tolerance judge | 公差判定 | Compares a measurement against a nominal with upper and lower deviations and branches pass or fail. The verdict, nominal, upper, lower, unit and spec_source (where on the drawing it comes from) are written into `run.outputs.tolerances` for Cpk and traceability. |
| Concentricity | 同心度 | The centre offset between two circles. GD&T concentricity is twice the offset; over max_deviation takes the ng branch. |
| OCR / OCV / taught font | 文字辨識／字串驗證／教導字型 | OCR reads printed text into a string; OCV verifies the string against what it should be (a pattern such as LOT###### or a value from the host system) and names the first wrong character. A taught font is a small classifier trained from lines you label, for dot-matrix and laser-marked fonts that general models misread; it needs no model files and runs entirely offline. |
| Control chart (SPC) | 管制圖（SPC） | A named output plotted run by run with a centre line and control limits computed from the data itself (I-MR for single values, X̄-R for subgroups); points outside the limits or forming a pattern (Nelson rules) mean the process has changed, not just that a part is bad. |
| Cp / Cpk | 製程能力指數 | How much of the specification band the process uses: Cp = (USL − LSL) / 6σ ignores centring, Cpk = min(USL − μ, μ − LSL) / 3σ penalises an off-centre process; 1.33 is the usual acceptance value. The limits come from the Tolerance judge bound to the same value. |
| Nelson rules | Nelson 判異法則 | Eight patterns that flag a control chart as out of control — one point beyond 3σ, nine in a row on one side, six in a row rising or falling, fourteen alternating, two of three beyond 2σ, four of five beyond 1σ, fifteen within 1σ, eight beyond 1σ on both sides. |
| Repeatability / reproducibility | 重複性／再現性 | How much a measurement moves when the same picture is run again (repeatability — the algorithm alone) or when the same part is captured again (reproducibility — camera and lighting included). Reported as σ and range per named output by the precision study. |
| Gauge R&R | 量具重複性與再現性（GR&R） | A study over several parts and trials that splits the total variation into the measurement system (GRR) and the parts (PV), reported as %GR&R and the number of distinct categories (ndc) after AIAG MSA 4th edition; under 10% is excellent, over 30% unacceptable. |
| Barcode grade | 條碼等級 | A verifier-style quality grade for a barcode or 2D symbol, A (4.0) to F (0.0), the lowest of its parameter grades (ISO/IEC 15415 for 2D, 15416 for linear, AIM DPM for direct part marks). The parameters — symbol contrast, modulation, fixed pattern damage, axial and grid non-uniformity, unused error correction, defects, decodability — say why. |
| Unused error correction (UEC) | 未用錯誤更正 | The share of a 2D symbol's error-correction capacity that was not needed to decode it; 1.0 means no module had to be corrected. |
| Quiet zone | 靜區 | The blank margin a symbol needs around it (one module for Data Matrix, four for QR, ten for most linear codes); marks in it count as fixed pattern damage and can stop the decode. |
| Form and position tolerance | 形位公差 | Geometric tolerances as a drawing states them (ISO 1101): straightness, flatness, roundness, parallelism, perpendicularity, angularity. Measured as the minimum zone — the narrowest band or ring that holds every point — not a least-squares residual. |
| Minimum zone (MZC) | 最小區域（圓） | The narrowest ring between two concentric circles that contains every edge point; the roundness value is its radial width. The least-squares circle (LSC) is reported alongside for comparison. |
| Photometric stereo | 光度立體 | Several pictures of the same part, each lit from a different side, solved for the surface normal at every pixel. Its curvature map shows embossed or engraved characters, dents and bumps that no single picture shows; the albedo map is the material with the lighting removed. |
| Circular caliper / run-out | 圓形卡尺／徑向跳動 | A ring of radial calipers around a circular edge, one radius per angle. Run-out is the largest minus the smallest radius — the out-of-round. Profile defects turns the radius sequence into counted chips, nicks (inward) and burrs (outward). |
| Wall thickness | 壁厚 | The distance between paired outer and inner edges along a section, with min, max or mean over several calipers |
| Region / ROI | 區域／ROI | The area drawn on the image to inspect (rectangle, rotated rectangle, ellipse, annulus, polygon, polyline, line, point) |
| Contour | 輪廓 | The traced outline of a shape in a binary image, as a list of points in image coordinates. The `contours` port carries a list of them; Contour find produces them, Contour filter, Contour geometry and Contour match consume them. Area on these tools is the pixel count of the filled outline, the same definition as blob analysis. |
| Convexity defect | 凸缺陷 | A dent in an outline measured from its convex hull: the depth is how far the outline sinks below the hull. Contour geometry counts the dents deeper than *defect depth* — a chipped corner, a bite out of an edge, a foreign body caught in the silhouette. |
| Polar unwrap | 極座標展開 | Flattening a ring (an annulus ROI, optionally a sector) into a strip whose width is angle and height is radius, so circumferential features — threads, teeth, nicks, text on a round label — become straight rows for the ordinary tools. The `mapping` output describes the geometry; Polar restore uses it to put points and contours back on the original picture. |
| Anomaly detection / memory bank | 異常檢測／記憶庫 | Teaching from good pictures only: a pre-trained backbone turns each picture into patch features, the memory bank keeps a compact subset of the good patches, and the anomaly score of a patch is its distance to the nearest good patch. Nothing has to be labelled and no defect needs to exist in advance. |
| Shape model / shape match | 形狀範本／形狀比對 | Geometric matching: a model of a part's edge points and gradient directions (per pyramid level) built from one good picture, and a search that scores how well the edge directions agree at each candidate position, angle and scale. Unlike grey-value template matching it survives lighting changes, partial occlusion and clutter. |
| Statistical template | 統計範本 | A per-pixel mean and standard-deviation model built from many good images (aligned first), stored as an .npz file asset. Statistical defects (`defect_stat`) measures how many standard deviations a pixel strays from its own normal, so textured areas may vary and flat areas are held tight. |
| Flat field / shading correction | 平場校正／陰影校正 | Removing uneven lighting by dividing the image by a picture of a plain white board taken under the same light (the white reference), optionally after subtracting a dark frame. Afterwards one threshold holds across the whole field of view. |
| Composite region / exclusion zone | 組合區域／排除區 | A region built at run time from several drawn shapes: a base with shapes subtracted (holes, printing, glare bands), added or intersected. Made by Region combine from Region steps, carried on region ports, and honoured by every tool that takes a region input. |
| Overlay | 標記 | The result graphics a tool draws on the image (boxes, circles, points, text). Metadata only — never burned into the image. |
| Run | 執行 | One execution of the flow, complete or up to a step; the result is OK, NG or failed |
| Preview | 試執行 | Runs the unsaved graph and keeps every intermediate image; not written to history |
| Run once | 執行一次 | Runs the saved graph once and does write history and statistics. There is no button for it in the editor any more — integrators call `POST /flows/{id}/run`, TCP or the integration page. |
| Continuous | 連續執行 | Runs repeatedly at an interval |
| Scratch image | 暫存影像 | An image uploaded only for a preview; it does not join the source library |
| Retention | 資料保留 | How long each store keeps its rows (run detail, audit trail, measurements, archived pictures) plus the number of backups and the maintenance hour: a single row edited on the Settings page. Clean-up runs on the history-writing thread, only while the engine is idle, in batches of 500. Hourly totals are kept for ever. |
| Maintenance window | 維護時段 | The hour in which the heavy housekeeping runs — trimming backups, dropping pictures nothing refers to and compacting the database — and only after a minute of idleness. |
| Fixed image | 固定影像 | The `fixed_image` tool (Source category): pictures uploaded into the step and stored with the flow, one or several taken in turn on each run; also the way to hand a reference picture (template, golden sample, white reference) to a tool through its picture input port. Role "acquire" lets a pushed image or a batch-test picture take its place; "reference" never changes. |
| Image source | 影像來源 | The definition of a camera, folder, synthetic generator, pushed image or capture client camera |
| Capture client | 擷取端 | The desktop program (vscapture) installed on the PC the camera is attached to: it drives webcams, Basler and IDS cameras and connects out to the server's capture port 9100. Shared memory on the same machine, lossless TCP across machines. |
| Channel | 通道 | One camera inside a capture client (name, kind, device, ROI, parameters, delivery settings). A web source names a client plus a channel. |
| Capture source | 擷取端相機 | The `kind=capture` image source: client, channel, mode, timeout_ms, fresh, encoding |
| On demand / stream | 依需求取像／連續串流 | Ask the capture client for a frame taken after the request; or have it push the latest frame up to an fps limit and take whatever is current |
| Shared memory | 共享記憶體 | The image path when the capture client and the server are on one machine: the client creates a segment with slots, a FRAME message announces one, and the server copies it once and returns it with SLOT_FREE |
| Asset | 資產 | A file: a template image, an ONNX model, a dataset archive |
| Judge | 判定 | The OK/NG conclusion, from the judge tool |
| Named output | 具名輸出 | A key and value returned to the automation system, from the output tool |
| Composite tool | 複合工具 | A tool built from other tools: an inner graph plus an interface; stored in the tool library, shown in the tool picker like a built-in tool, flattened into its inner steps when a flow runs (`composite:<key>`) |
| Encapsulate as tool | 封裝成工具 | Turning the selected steps of a canvas into a composite tool; the selection becomes one step and the edges crossing it become ports |
| Interface (composite tool) | 對外介面 | Which inner ports are the tool's inputs and outputs, in what order and under which display name, and which inner parameters appear on its parameter form (optionally as teaching parameters) |
| Variable | 變數 | A value a flow keeps between runs (a running count, the previous part, the lot number a PLC sent); scope flow or station. Read and stored by the variable steps, the variables API and TCP VARS/SET; trial runs see a private copy |
| Board | 看板 | What the operator screen shows for a flow: the chosen named outputs with label, unit and tolerance, the picture, today's counts and variables. Configured in the flow editor, shown on the Dashboard and on the full-screen board page |
| Calibration | 標定 | One asset holding the lens correction and the pixel-to-real-world mapping for a camera, made on the Calibration page and used by the Lens correction, Real-world coordinates and Pixel calibration steps |
| Engine lock | 引擎鎖定 | An integrator holding the hardware: everyone else can edit but not execute. Set it over HTTP (`POST /vision/lock`) or TCP (`LOCK` / `UNLOCK`); while it holds, a banner across the top of the interface says who has it. |
| Integrator | 整合方 | An automation system calling with an API key |
| Role | 角色 | administrator, engineer or operator (`UserPref.role`). An administrator manages accounts, permissions and settings; the other two roles have whatever functions an administrator ticked for them (see Role permissions). |
| Role permissions | 角色權限 | Which functions an engineer and an operator may use, ticked by an administrator on the Users page (`RolePermission`, `accounts/permissions.py`). The factory setting is the old three tiers; administrators always have everything. Enforced server-side by `require_feature()`. |
| Reset | 重置 | Clears that flow's in-memory run records and statistics |
| Template library | 範本庫 | Flow templates, built in (`builtin:<key>`) or your own ("save as template"). The source id is the placeholder `{SOURCE}`, chosen when you create or load. |
| Template | 範本 | One entry in the library. "Load template" prefixes node ids with `t{n}_` to avoid collisions. The example templates (`demo.BUILTIN_TEMPLATES`) live here and run as they are with the matching "Example: …" source. |
| Note | 註解 | A decorative node in the graph (type=note, never executed). "Add note" drops one in the centre of the canvas; edit its title and body in the inspector and drag the corner to resize. |
| Batch test | 批次測試 | The tuning workbench at `/batch`: run an image set through a flow and keep every image's result, with expected labels, insights, re-running after tuning, comparison and AI consultation |
| Image set | 影像集 | A set of test images plus the expected label (OK/NG) of each; the files live in ASSET_DIR/batch/ |
| Batch run | 批次執行 | One execution of an image set against a graph snapshot. Per-image results and a summary are kept; origin is manual, draft, autotune or ai_tune, and parent links a tuning before to its after. |
| Insights | 資料洞察 | Hit rate, confusion matrix, missed images, failing nodes, suggested thresholds, output distributions and the difference from last time |
| Threshold suggestion | 建議門檻 | A better threshold derived from the judging input values of the expected-OK and expected-NG groups, applicable in one click |
| Consult | 資料諮詢 | Ask a question about one batch run's data: rule-based insights plus an LLM answer, with parameter suggestions you can apply |
| Assistant dock | 全域 AI 助手 | The chat panel pinned to the bottom-right corner that survives page changes (the conversation lives in the browser). It routes on page context: help answers, editing a flow, consulting on data, tuning from data. |
| Help answer | 使用說明問答 | The documentation sections and tool skills are indexed for retrieval; the question finds the relevant passages, the LLM answers only from them and cites the sections, and offline it returns an extract with a `/docs/` link |
| Assistant context | 助手脈絡 | What a page registers with the global assistant: kind (editor, tool page, batch test, …), the current graph, apply callbacks, the batch run id. Cleared when you leave the page. |
| Agent session | 工作階段 | The complete record of one AI assistant generation (image, ROIs, request, flow, verdicts, rating). It can be restored, and used as a prior for similar images. |
| Prior | 參數先驗 | The on-site teaching parameters of a similar successful case, applied to a new draft, put first among the auto-tuning candidates and included as a past example for the LLM |
| Custom skill | 補充要領 | A site-wide (administrator) or personal markdown supplement to the built-in AI skills. Site text goes into the system prompt, personal text into the user message. |
| Agentic mode | 代理模式 | The assistant working towards a flow step by step through actions (try, edit, verify, ask) as a background job, with a step timeline in the interface — as opposed to a single generation |
| Step timeline | 步驟時間軸 | Every action, reply, question and completion of an agent job, with a summary and a duration; it can be interrupted while running |
| Candidate | 候選方案 | The main solution plus parameter variants the rule engine produces for one intent. All are run silently and scored against the image labels; the winner runs for real, and you can switch between them on the assistant page. |
| Image label | 影像標記 | The expected verdict of each uploaded image — the basis for ranking candidates and for auto-tuning. An ROI hint of "good" or "bad" becomes a label automatically. |
| Autotune | 自動調參 | Data-driven coordinate descent: only teaching parameters move, and only a strict improvement is kept. Entry points: assistant generation, "Auto-tune" on the batch page, and "Auto-tune" on the Golden Set page. |
| Locate wrap | 定位補正三件套 | Template match → locate correction → ROI follow, which the assistant wraps around a flow automatically when the part can move (an ROI hinted as "locator") |
| AI assistant | AI 助手 | Upload an image, mark ROIs, write a prompt, and get a generated flow that is actually run. An offline rule engine (intent → synthesiser) plus an optional LLM (`VISION_AGENT_API_KEY`). See [AI assistant](agent.md). |
| Statistics | 統計 | KPIs from the database history, hourly OK/NG/failed, the duration trend and the run history table. "Live statistics" means the engine's in-memory FlowStats. |
| Hourly roll-up | 每小時彙總 | `FlowRunHourly`: one row per flow per hour, kept forever, so the yield trend survives detail purging and restarts |
| Image archive | 影像封存 | Optionally writing run images to disk (off by default, enabled per flow), so a defect from last week can still be looked at. Purged by age and then by total size. |
| Flow version | 流程版本 | `FlowVersion`: a snapshot of the graph on every save, with who saved it and a parameter-level diff, restorable |
| Audit log | 操作紀錄 | `AuditLog`: who changed what and when — flows, recipes, connections, accounts, the lock |
| Station | 站台 | The station identifier carried by every run (`VISION_STATION_ID`), shown on the dashboard cards and the statistics page |
| Integration page | 整合頁 | The interface reference and test tools for integrators; one page per method, expanding into a tree in the sidebar |
| Trace | 命令與結果 | The live log at the bottom of an integration page: the commands and replies this interface handled (time, direction, duration, success, full detail). An in-process ring buffer; with the page closed, only errors are kept. |
| Modbus client / server | Modbus 主站／從站 | Client (`modbus_tcp`) means the platform connects to the device to read and write. Server (`modbus_server`) means the platform listens and the PLC, as master, reads and writes the platform's registers. |
| Connection | 連線（外部） | The definition of an outgoing connection to Modbus TCP or a host system: kind ∈ modbus_tcp, modbus_server, tcp_client, plugin; each kind is managed on its own integration page. The write_modbus tool refers to it by name. (An edge on the canvas is a different thing.) |
| write_modbus | 寫入 Modbus | An output tool: following a mapping table (src → address, with dtype, scale, offset and value) it writes the verdict, a named output or an input port's value to a connection. A failure degrades to a warning by default. |
| Favourites | 收藏 | Tools starred in the palette (localStorage `vs.favoriteTools`) |
| Commissioned | 已教導／未教導 | `Flow.commissioned`, set by "Mark as commissioned" on the teach page. While false the flow list, dashboard and toolbar show a "not commissioned" tag and every run carries a warning in `RunReport.warnings`, without being blocked. |
| Recipe | 配方 | A set of parameter overrides for one flow, `param_overrides = {node_id: {param: value}}`, for changeovers between part numbers. Run, preview and TCP can name one with `recipe=` (by name or id); without one the bound recipe (is_default) applies. On the teach page, choosing a recipe as the edit target writes changes into the recipe instead of the graph. |
| Override | 覆寫 | One "step.parameter = value" inside a recipe, applied over the graph before compiling |
| Golden Set | Golden Set | A set of image cases with expectations (OK, NG or any) stored on the server, outside the image cache; created by upload or from batch test results |
| Golden case | 案例 | One image in a Golden Set plus an expected status, optional expected outputs and a note |
| Regression | 回歸 | Running every case in production mode and comparing against expectations and the baseline: total, match, mismatch, match_rate, the confusion matrix and the regressed and improved lists. Images are kept only for mismatches. |
| Baseline | 基準 | Every case's result at the moment a regression was saved as the baseline; the next regression uses it for regressed, improved and "differs from baseline" |
| Regressed / improved | 退步／進步 | Matched the baseline expectation but does not now = regressed (was → now); the reverse = improved. The first list to look at after changing a parameter. |
| fail_under | 合格門檻 | A regression whose match_rate falls below this is a failure (a non-zero CLI exit code) |
| DL project | 教導專案 | One model kind (a trainer) plus a class list plus a sample set. The trained result is exported as a `kind=model` asset. |
| Auto label | 自動標記 | `Trainer.suggest` proposes a class and a confidence for unlabelled samples (shown as dashed outlines, acceptable in bulk). Accepted proposals are recorded as auto, and become human once confirmed. |
| Trainer | 模型種類 | The registry of trainable model kinds. A trainer declares hyper-parameters (Param), a label mode and supported devices, and implements train and suggest. Plugins can add more. |
| Shape workspace | 標記編輯器 | The labelling workspace for shapes mode (segmentation and detection): a thumbnail wall, polygon and box editing, snap-to-contour refinement and shortcuts. Coordinates are normalised 0–1. |
| Classify workspace | 大圖檢視 | The classification workspace: a thumbnail wall, a full-image viewer (zoom, 1:1) and class buttons; switchable with the grid view, sharing the same filters |
| Tool rail | 工具欄 | The vertical rail of large icons on the left of the labelling canvas: select, polygon, box, smart select, refine, delete, undo — each showing its shortcut |
| Smart select | 智慧選取 | SAM-assisted labelling: click an object, the server segments it, and the outline becomes a polygon with the current class. The default weights (mobile_sam.pt) download on demand and need the optional deep-learning add-on. |
| Smart box | 智慧框選 | Drag a box and SAM2 returns the outline of the object inside it — the counterpart to smart select |
| SAM proposals | SAM 全圖提案 | Automatic labelling with no model at all: SAM2 segments the whole image and every proposal is attached to the first class for confirmation |
| Split | 資料集分割 | `DlSample.split`: train, val, test or unset. "Auto split" assigns stratified at random and the status-bar chip switches a single sample. val validates; test never enters training. |
| Dataset version | 資料集版本 | `DlDatasetVersion` freezes the current samples, labels and splits into a zip in the asset library (kind=dataset): an images/labels tree for shapes, class folders plus a manifest for classes. Downloadable and deletable. |
| Augmentation | 資料增強 | Expanding the samples during training: flips and brightness jitter for the built-in models (training set only), and degrees, fliplr and mosaic exposed for ai_seg. Off by default. |
| Dedupe | 重複偵測 | Uploads, imports and burst grabs are de-duplicated within a project on the SHA256 of the decoded pixels, and the number of duplicates is reported |
| dl_instance | DL 實例分割 | A DL tool: instance-segmentation ONNX inference (letterbox, NMS, mask assembly) returning each instance's outline, class and score; trainable on the teaching page |
| AI tools | AI 工具 | ai_detect, ai_segment, ai_classify, ai_pose and ai_obb: native network inference (torch, GPU used automatically). The model is either a .pt asset trained on the teaching page or the name of a stock model. Pose returns keypoints, OBB returns rotated boxes. |
| DL dependencies | DL 依賴 | `requirements-dl.txt`, `scripts/setup_dl.ps1` and `manage.py dl_check`: the optional torch, ultralytics and onnxruntime-gpu install (torch cu128 first) and how to verify it. Pitfalls in [Deep learning §11](dl.md). |
| Python script tool | Python 腳本 | `python_script`: your own `def run(ctx)` on the tool page, executed in the engine process under restrictions, with fixed output ports. Only an administrator saving the flow approves the code. |
| Plugin | 外掛 | A .py file subclassing Tool, Grabber, Writer or Trainer dropped into `plugins/` and loaded automatically; module variables ENABLED, label and description control loading and display (see [Plugins](/docs/plugins.html)) |
| Theme | 主題風格 | light, dark, cyber (neon green, hard angles, scan lines on the page ground and the sidebar only — never over the image area, all through CSS variable tokens) or system. Stored in localStorage and, for a signed-in user, written back to /auth/prefs and returned by /auth/me so it follows them between devices. |
| Bit depth | 影像位深 | u8, u16 or f32 (`tools/imgfmt.py`, `Tool.accepts`). A depth a tool does not declare is normalised to u8 automatically; use the bit-depth conversion tool to control it explicitly. Reading a file with IMREAD_UNCHANGED keeps 16-bit data. |
| Manual write | 手動寫入 | Sending one set of values (as JSON) to a connection from the connections page to test it. For dio_sim the channel values show up under "state". |
| Export / import | 匯出／匯入 | Export writes a stably serialised flow file that can live in git; import upserts on the name in the file and replaces the `{SOURCE}` placeholder on the acquire step with the source you choose. Without one, updating an existing flow keeps its current source and a new flow is left empty. |

## Port type colours (fixed, never reused) {#port-colors}

| Type | Colour | Carries |
|---|---|---|
| image | blue `#3b82f6` | Images |
| region | purple `#a855f7` | ROIs |
| number | green `#22c55e` | Numbers |
| bool | orange `#f97316` | Booleans |
| string | yellow `#eab308` | Strings |
| points | cyan `#06b6d4` | Point sets |
| contours | indigo `#6366f1` | Contours |
| matches | pink `#ec4899` | Match and detection results |
| list | teal `#14b8a6` | General lists, including overlays |
| any | grey-white `#cbd5e1` | Anything |
| flow | grey `#94a3b8` (diamond) | Branching |

## Status wording {#status}

| Status | Colour | Meaning |
|---|---|---|
| OK | green | Judged good |
| NG | red | Judged a reject |
| Failed | dark red border | A tool error, a timeout or no image; the step shows the error message on the canvas |
| Skipped | faded grey | A branch not taken, or an upstream failure |
| Running | pulsing border | In progress |

## Tone of voice {#tone}

This is industrial equipment, so the interface reads plainly and never chattily. In English: sentence case for labels and buttons, no exclamation marks, an imperative verb for an action ("Run to this step", not "Let's run it"), and a message that says what happened and what to do about it. Prefer "cannot" to "can't", and say what is missing rather than blaming the user. Avoid naming the underlying computer-vision libraries anywhere a user can see (the code examples on the plugins page are the one exception).

The zh-Hant locale follows this table, and the zh-Hans translation is derived from it. `frontend/src/test/i18n.test.ts` checks the banned words automatically.

| Avoid | Use | Why |
|---|---|---|
| 點一下、按一下 | 點選 | One verb for the action |
| 試跑、跑一次 | 試執行、執行一次 | "試執行" means running the current canvas, unsaved changes included, and keeping the intermediate images |
| 還沒有、沒有 | 尚無、尚未、無 | Empty states |
| 不能 | 無法、不得 | Limits and validation messages ("不得" for a hard limit) |
| 這個、這次 | 此、此次 |  |
| 抓、抓取 | 擷取、偵測 | "擷取" for acquiring an image, "偵測" for detecting |
| 你 | 您 | Addressing the user |
| 太敏感、漏抓 | 誤判過多、漏檢 | Describing inspection results (the assistant still understands the colloquial forms as input) |
| 接上、拉正、掛 | 連接、校正、套用 |  |

Example prompts written for the AI assistant may stay colloquial; everything else in the interface, the help page and these documents follows the table.
## Engineering note {#engineering-note}

An engineering note is shared knowledge about decisions, lessons, lighting, calibration, constraints, tolerance rationale or known issues. Inspection specifications still come from the flow. Notes may link a project, part number, flow, recipe, image source, evidence images and runs, with applicable conditions and an inclusive flow-version range. Empty version bounds mean no limit.

Any signed-in user can read notes. Flow editors can create and edit drafts. Self-confirmation is allowed by default for single-engineer stations; stations that require two-person review can disable it, so another engineer must confirm. Confirmed content is preserved: create a replacement to revise it. Creating a replacement immediately supersedes the old note, even while the replacement is a draft. Retraction preserves history but removes the note from assistant searches.

The assistant uses at most five confirmed notes for the current flow and related part numbers, filtered against the current flow version. Related part numbers come from that flow's applicable confirmed notes. Conditions must still be checked. The assistant and the conversation's decisions list can create drafts, but the assistant cannot confirm them. Fixed evidence images are retained; cached image references may expire.
