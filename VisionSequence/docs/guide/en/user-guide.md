# User guide

This guide follows the sidebar from top to bottom: where each page is, what is on it, and what to press. Every section opens with a screenshot; the numbered markers on the picture match the numbered list under it. The screenshots show the English interface; the Chinese interfaces have the same layout with translated labels. This guide is also the Help page inside the product (sidebar › Help), in the interface language, together with the tool catalogue.

## 1. Getting around {#shell}

<figure class="shot"><img src="/docs/img/shell.jpg" alt="The application shell on the Overview page"><figcaption><b>Overview</b> (sidebar › Overview, route <code>/</code>)
<ol class="callouts">
<li data-n="1">The <strong>sidebar</strong>, grouped by what you are doing: <strong>Inspection</strong> (flows, batch test, AI assistant), <strong>Teaching</strong> (station teach, calibration, deep-learning teaching) and <strong>Resources</strong> (source library, asset library), then External integration — which expands into its sub-pages — and the administration pages. Groups open and close with a click and remember their state; items your role cannot use are hidden, and a group disappears when none of its pages are available. "Collapse sidebar" at the bottom shrinks it to icons; on a phone it becomes a drawer behind the ☰ button.</li>
<li data-n="2">The <strong>breadcrumb</strong> shows where you are (Overview › Flows › flow name) and each part is a link back.</li>
<li data-n="3">The <strong>capacity</strong> indicator: how many of the engine's workers are busy and how many images are cached; click for details.</li>
<li data-n="4">The <strong>user menu</strong>: who is signed in, change password, sign out. A green dot means the engine is free; when an integrator locks it a banner appears under the top bar (see <a href="#lock">15. The engine lock</a>).</li>
<li data-n="5">The <strong>AI assistant</strong> button, available on every page (see <a href="#assistant">14. The global assistant</a>).</li>
<li data-n="6">The <strong>flow list</strong>: one card per flow with its last result and run count. Select a card to see its live image in the middle and the verdict and output values on the right.</li>
<li data-n="7"><strong>Run once</strong> on a card runs the saved flow immediately, no editor needed.</li>
<li data-n="8">The <strong>statistics</strong> shortcut opens the flow's run history, yield trend and image archive.</li>
</ol></figcaption></figure>

With no run yet the middle shows "Waiting for the next inspection"; as soon as an external trigger, continuous mode or "Run once" produces a run, the image with its overlays and the result appear there live.

### 1-1. Using the station from another PC {#another-pc}

Nothing is installed on your PC: open the station's address in Chrome, Edge (111 or newer), Firefox (128+) or Safari (16.4+) — `https://<station name>/`, or the address your administrator gave you. The first time on a new PC the browser may warn about the certificate: your administrator has a small file, `root.crt`, to import once ([how](/docs/deployment.html#https)). Your language and theme are saved with your account, so every PC you sign in from looks the same; on a shared PC, sign out when you leave — that clears the assistant conversation and the command history from that browser. If the page stays blank and shows a notice about the browser version, the browser on that PC needs updating; the station is fine.

## 2. Signing in, roles and permissions {#login}

<figure class="shot"><img src="/docs/img/users.jpg" alt="The Users page"><figcaption><b>Users</b> (sidebar › Users, administrators only)
<ol class="callouts">
<li data-n="1"><strong>New user</strong>: username, display name, role and password.</li>
<li data-n="2">The account table: change a role, disable an account, reset a password.</li>
<li data-n="3"><strong>Role permissions</strong>: tick, function by function, what an engineer and an operator may use.</li>
</ol></figcaption></figure>

- With no users yet, the sign-in page offers "Create the first administrator", and you are signed in as that account. An integrator uses an API key and never signs in.
- There are **three roles**; the table is the factory setting, and the Role permissions card adjusts it: 

| Role | Can | Cannot |
|---|---|---|
| Administrator | Everything, including accounts, connections and system settings | — |
| Engineer | Create and edit flows, image sources and assets; deep-learning teaching, batch testing, Golden Set regression; change any parameter | Accounts, outgoing connections, system settings |
| Operator | Run inspections, start and stop continuous mode, change over (switch the bound recipe), adjust **on-site parameters** on the teach page, view statistics | Change a flow's structure, train models, batch test, edit sources or connections |

- **Role permissions**: take deep-learning teaching away from engineers, hand batch testing or the audit trail to operators, delegate the outgoing connections. Administrators always have everything and cannot be ticked off, so nobody can lock themselves out. The server checks every request, so a function that is not ticked cannot be reached by typing its address either; the sidebar and the buttons simply disappear.
- **A flow belongs to the line, not to a person**: every engineer can see and edit every flow (the Owner column only records who created it), so an engineer leaving never orphans a flow.
- **On-site parameters** are the ones a tool's author marked as teaching parameters — a threshold, a blob's minimum area. An operator changing those on the teach page writes straight back to the flow; changing anything else, or the structure, is refused by the server. Which parameters those are is shown in the "On-site" column of the tool page's parameter table.

## 3. The Flows page and templates {#flows}

<figure class="shot"><img src="/docs/img/flows.jpg" alt="The Flows page"><figcaption><b>Flows</b> (sidebar › Flows)
<ol class="callouts">
<li data-n="1"><strong>New inspection</strong> creates an empty flow and opens its Inspection tasks page.</li>
<li data-n="2"><strong>New advanced flow</strong> creates an empty flow and opens the canvas editor.</li>
<li data-n="3"><strong>Create from template</strong> opens the template gallery.</li>
<li data-n="4"><strong>Import</strong> loads a flow exported as JSON (from another station or from version control).</li>
<li data-n="5">Per flow: <strong>Inspection tasks</strong> opens that flow's task page; selecting the row does the same.</li>
<li data-n="6"><strong>More</strong>: the teach page, Golden Set, statistics, export, duplicate and delete. The pencil icon opens the canvas.</li>
<li data-n="7"><strong>Recipes</strong>: the parameter sets for changeover.</li>
</ol></figcaption></figure>

**The template gallery** holds more than sixty built-in templates **grouped by category** — tutorial, counting, measurement, quality, defects, identification, then your own — with a filter row above the cards. Each built-in template carries its synthetic sample pictures: leave the source at "The template's sample pictures" and the acquire step becomes a **Fixed image** step that takes the next sample on each run (the fourth picture of most sets is the deliberate reject), so the new flow runs immediately; pick a real source instead when the camera is ready. Your own flow can be saved as a template for others to reuse. Details in [Example templates](samples.md).

Export and import use a stable JSON format, so flows can be kept in version control and moved between stations; the page asks which image source to bind on import. See [Golden Set and export](golden.md).

### 3-1. Inspection tasks: build an inspection without wiring {#inspect}

The **Inspection tasks** page (the button on a flow's row on the Flows page, or in the editor toolbar; route `/flows/:id/inspect`) builds an inspection from a list of tasks instead of steps and connections. **Add task** above the task list opens a three-step guide: choose the task type (Locate part, Measure diameter, Measure distance, Inspect edge defect, Read and verify…), draw the region on the image, then fill in the specification (nominal value, tolerances, unit, calibration) and select **Create task**. **Remove task** next to it removes the selected task. The page builds the steps, the connections and a pass/fail summary for you; the tool picker and wiring are never needed.

- **Image source**: pick a source, add fixed images, or **Upload temporary image**. **Try run** is refused until there is an image to run on.
- **Readings and status**: each task shows Pass, Fail, Not found, Location failed, Error, Skipped or Not run. A required task that fails or is skipped makes the whole result fail — a skipped check is never counted as a pass. When locating fails, the tasks that depend on it report Location failed instead of measuring the wrong place.
- **Stale**: after you change a specification, the last readings are marked **Stale** until you select **Try run** again.
- **The last readings are kept on the server**: after a try run the page stores the readings summary for the flow, so reopening the page — on another PC or in a fresh browser — shows the last readings. If the flow has changed since, they are marked Stale. Images and teaching need a new try run.
- **Millimetres** need a calibration: the form asks you to select one (**Open calibration**) instead of silently reporting pixels.
- **Custom**: if a task's steps are edited in the **Advanced flow** (a step added, a tool changed, an internal connection changed), the task is marked **Custom** with the reason and its form is hidden; **Open in advanced flow** jumps to that step. Moving steps or changing parameters the task does not manage keeps it editable.
- **Save** stores the flow; if someone else saved it in the meantime, the save-conflict dialog lets you load their version, overwrite or cancel. **Advanced flow** opens the full graph at any time for viewing and debugging.

Locating a part that may rotate: in **Locate part**, crop the locator mark from the current image (**Use this crop**), allow rotation and set the angle range; after the first try run, **Teach pose from this run** records the reference position. Use a mark that is not symmetric every 90° — a plain cross is ambiguous when the angle range is wide.

The AI assistant can build the same task list from a conversation; see [From a conversation to an inspection task list](agent.md#tasklist).

### 3-2. Engineering notes {#notes}

**Engineering notes** (sidebar › Inspection › Engineering notes, route `/notes`) keep the reasons behind a setup — decisions, lessons, lighting, calibration, constraints, tolerance rationale and known issues — next to the flow they apply to. A note can link a project, part number, flow, recipe and image source, evidence images and run IDs, applicable conditions and a flow-version range. The inspection specification itself always stays in the flow.

- A new note is a **draft**. Only a **confirmed** note is quoted by the AI assistant. By default an engineer can confirm their own draft; a station can require another engineer instead (`VISION_ENGINEERING_NOTE_SELF_CONFIRM=0`).
- **Create replacement** writes a new draft that supersedes an old note: once it is saved, the old note stops appearing in assistant searches, and its history is kept. **Retract** withdraws a note without deleting it.
- The editor and the Inspection tasks page link to the notes of the current flow, and decisions recorded in an assistant conversation can be saved as a draft with **Save as engineering note**.

## 4. The flow editor {#editor}

<figure class="shot"><img src="/docs/img/editor.jpg" alt="The flow editor with a step selected"><figcaption><b>Flow editor</b> (Flows › a flow, route <code>/flows/:id</code>)
<ol class="callouts">
<li data-n="1">Toolbar row 1: the flow name, <strong>Save</strong>, the current recipe and the "Not taught" badge that links to the teach page. Everything else lives in the flow navigation and the More menu on the right.</li>
<li data-n="2">Toolbar row 2: <strong>Preview</strong>, <strong>Image sequence preview</strong> when the source is a folder or Fixed image, "Rerun with last image", <strong>Upload scratch image</strong> and <strong>Continuous</strong>. Batch testing has its own page under the sidebar's Inspection group.</li>
<li data-n="3"><strong>Add tool</strong> opens the tool picker (next figure); "Add note" drops a sticky note. Favourites you star in the picker appear underneath, and the step list at the bottom of the column jumps to a step.</li>
<li data-n="4">The <strong>canvas</strong>: steps and their typed ports. Drag from an output port to the next step's input port; only ports of the same colour connect.</li>
<li data-n="5">The <strong>image viewer</strong>: before and after images of the selected step with its overlays; the strip below switches input, output, before/after and "Overlay every step's marks".</li>
<li data-n="6">The <strong>inspector</strong> on the right: title, enabled, colour, "Continue on error" and the parameters of the selected step; its Results tab shows the last preview.</li>
<li data-n="7"><strong>Open tool page</strong> goes to the dedicated tuning page for that step.</li>
<li data-n="8"><strong>Preview</strong> runs the current canvas, unsaved changes included.</li>
<li data-n="9">The <strong>flow navigation</strong> shared by the four pages of a flow: Inspection tasks, Canvas, Teach page and Statistics.</li>
<li data-n="10"><strong>More</strong>: templates, recipes, versions (history and restore), auto-layout, collapse tasks, Golden Set, export, <strong>Clear result</strong> and <strong>Clear run history</strong> (the dialog lists what it affects). The icons next to it are undo and redo.</li>
</ol></figcaption></figure>

The image viewer toolbar includes a **Crosshair** button. Turn it on to show one horizontal and one vertical line, then drag either line to measure an image position. The viewer shows the line intersection as image X/Y coordinates and reads the pixel value at that point. Moving the mouse over the image also shows a cursor information bar with image coordinates and the current grey or RGB value; zooming and panning do not change the coordinate system.

When the editor has both the selected step input and output image, the main viewer can overlay the second image on top of the first. Use **Overlay opacity** in the viewer toolbar to blend before and after. If the two images have different dimensions, the overlay is centred at its own size instead of being stretched to the main image, and the viewer marks the size mismatch.

Use **Grid** in the image viewer strip to switch the editor into grid view. Choose 1, 2, 4, 6 or 9 cells, then bind each cell to a step and one of its image output ports. The grid layout and bindings are remembered per flow on this browser, so common tuning views can be reopened without rebuilding the layout.

1. Wiring a judging tool's branch port to a step's `_flow` port makes that step conditional; every step also passes its image straight through on the `_image` port, so a tool that only produces numbers can still sit in the middle of an image chain.
2. Ctrl+S saves. Unsaved changes are kept as a draft and survive leaving and coming back; "Run once" and "Continuous" use the saved version, "Preview" uses the draft.
3. **Image sequence preview** appears when the flow acquires images from a folder source or a Fixed image step. It previews one image at a time, shows the current image number and OK/NG counts, and can be paused or stopped. It is still preview only: it does not enter production history or statistics.
4. Ctrl+F opens node search. It matches a step's id, title, tool type and filled parameter values; Enter jumps through matches, Esc closes it. Undo and redo share the same edit history: Ctrl+Z undoes, Ctrl+Shift+Z or Ctrl+Y redoes.
5. **Where is the time going?** After a preview every step shows its time and a thin bar: the slowest step of that run is red, anything over half of it orange. The Results tab also has **Span timing**: choose a source step and a target step to total every step on the data-flow path between them, including branched paths once. Right-click a step and choose **Run to here** to run only that step and the ones before it — when you are tuning one step there is no need to wait for the rest of the flow.
6. **Values on the connections**: after a preview every connection shows the value it carried (a number, a text, true/false, the item count of a list); images are not shown. The tag button in the zoom bar at the bottom turns this on or off. The auto-layout button next to it lays the steps out left to right and spaces the rows by each step's real height.
7. **Clear result** only clears what is currently displayed: step colours, timing heat, overlays, the image viewer marks and the Results tab. It does not edit the draft, save the flow or call the server; the next preview or run fills the result again.
8. The inspector with **nothing selected** shows **Flow settings** (description, continuous interval, flow timeout, concurrency, enabled and "Stop on NG") and, under **More settings**, three buttons that each open a dialog: **Variables** — the values this flow keeps between runs (a count, the previous part, the lot number a device sent), which you can read, change or clear right there; **Board settings** — what the operator board shows for this flow (see [7-1](#board)); and **Result reporting** — which connection receives a formatted line after every run (see [Automation](/docs/automation.html)).
9. **No image source chosen yet?** A yellow banner appears at the top of the editor; pick a source from the dropdown in the banner (or upload a scratch image) and you can preview straight away. Selecting the acquire step shows the current source in a dropdown with a preview thumbnail in the inspector, where you can switch source directly.
10. **No camera at all?** Add a **Fixed image** step (Source category) instead of an image source and upload one or more pictures into it; they are stored with the flow (export carries them along) and each run — a preview included — takes the next one, so pressing Run repeatedly walks through the set. The same step, with its role set to "reference", hands a template, golden sample or white reference to a locating, golden-comparison or flat-field tool through that tool's picture input port — no asset needed.
11. **Want to write a little Python?** The Logic category has a "Python script" tool: write `def run(ctx)` in the code editor on the tool page (np, cv2 and math are available), read `ctx.image`, the upstream values in `ctx.inputs`, the on-site parameters `ctx.params['p1'..'p3']` and the region from `ctx.roi()`, and return a number, a bool, text, data, a new image and overlays, choosing the pass or fail branch. The output ports are fixed (value, result, text, data, image). The script runs in the engine process under restrictions — allow-listed imports, a timeout, a read-only input image — and **only an administrator can edit and save it, which is what approves it**. Everyone else can view and run an approved script, and adjust its on-site parameters on the teach page without touching the code.

<figure class="shot"><img src="/docs/img/editor-flow-settings.jpg" alt="The flow editor inspector with nothing selected"><figcaption><b>Flow settings</b> (editor › click an empty spot on the canvas)
<ol class="callouts">
<li data-n="1">The <strong>inspector</strong> with nothing selected: <strong>Flow settings</strong> on top (description, continuous interval, flow timeout, concurrency, enabled, "Stop on NG"), then <strong>More settings</strong>.</li>
<li data-n="2"><strong>Variables</strong> opens the flow's variables in a dialog: read, change or clear the values it keeps between runs.</li>
<li data-n="3"><strong>Board settings</strong> opens the operator-board configuration for this flow (<a href="#board">7-1</a>) in a dialog.</li>
<li data-n="4"><strong>Result reporting</strong> opens the per-run reporting rules (which connection gets which formatted line) in a dialog; each dialog has its own Save button.</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/tool-picker.jpg" alt="The tool picker"><figcaption><b>Tool picker</b> (editor › Add tool)
<ol class="callouts">
<li data-n="1"><strong>Search</strong> by name or key.</li>
<li data-n="2"><strong>Categories</strong>: acquisition, pre-processing, locating, measurement, inspection, deep learning, logic, output.</li>
<li data-n="3">The <strong>tool cards</strong> of the category (icon, name, key).</li>
<li data-n="4">The <strong>details</strong> of the selected tool: description, input and output ports with their type colours, and the parameter table with defaults, ranges and the on-site flag. The star marks it as a favourite.</li>
<li data-n="5"><strong>Add to canvas</strong> (or double-click a card) inserts the step in the centre of the canvas.</li>
</ol></figcaption></figure>

### 4-1. Composite tools {#composite}

A **composite tool** is a tool you build from other tools: several steps wired together, with an **interface** that says which inner ports are its inputs and outputs and which inner parameters appear on its parameter form. Once saved it lives in the **Tool library** (Resources › Tool library) and appears in the tool picker like any built-in tool; drop it on a canvas, wire it and tune its parameters on the tool page. Every flow that uses it runs the same implementation.

- **Encapsulate as tool** (the main path): select the steps on a canvas, right-click and choose "Encapsulate as tool…" (or use the button in the multi-selection panel), give it a name, a key and a category. The selected steps are replaced by one step; edges that crossed the selection become its ports and published output names move onto the new step.
- **Edit a tool**: double-click a composite step, choose "Open the tool canvas" from its menu, or press Edit in the tool library. The tool's canvas is the ordinary editor with an **Interface** panel on the right: tick the inner ports to expose, drag or use the arrows to order them, give them display names, tick the inner parameters to expose and mark the ones the operator may teach. Try-run feeds the scratch image to every exposed image input.
- **Direct reference**: tools are not versioned yet. Saving a tool changes every flow that uses it immediately, so Save first lists the flows and tools affected and asks you to confirm. A tool that is still in use cannot be deleted.
- **Two levels only**: a flow uses tools, and a tool is built from built-in tools. A composite tool cannot contain another composite tool, so the tool picker on a tool's canvas hides composite tools and "Encapsulate as tool" is unavailable there.
- **Built-in inspection tools**: the tool picker's **Inspection tasks** category holds one composite tool per inspection method (measure diameter or roundness, locate part by template, shape model or registered picture, measure distance by edge pair or hole centres, count objects, check presence by template, blob or print, inspect edge defect (simple or free-form outline), read code, read and verify text). Drop one on a canvas, connect the image, draw the region and set the specification on its tool page. They are read-only; use **Save a copy** in the tool library to adapt one.
- **Export and import**: a tool downloads as a `.tool.json` file (nested tools included) and can be imported on another station; a flow export embeds the composite tools it uses so the flow can be imported on its own.
- Built-in composite tools are read-only; use **Save a copy** in the tool library to get an editable one.

## 5. The tool page and ROIs {#tool}

<figure class="shot"><img src="/docs/img/tool.jpg" alt="The tool page"><figcaption><b>Tool page</b> (editor › inspector › Open tool page, route <code>/flows/:id/tools/:step</code>)
<ol class="callouts">
<li data-n="1">The <strong>parameters</strong> of this step, grouped, with help text; a region parameter is drawn on the image instead.</li>
<li data-n="2">The <strong>input image</strong> (what the step receives), where ROIs are drawn.</li>
<li data-n="3">The <strong>output image</strong> with the step's overlays.</li>
<li data-n="4"><strong>Reference information</strong>: histogram, statistics and the step's output values.</li>
<li data-n="5"><strong>Run to this step</strong> previews the flow up to here.</li>
<li data-n="6"><strong>Save</strong> writes the parameter draft back to the flow.</li>
<li data-n="7"><strong>Upload scratch image</strong> gives the previews an image without touching the source library.</li>
<li data-n="8"><strong>Back</strong> to the editor (asks before discarding unsaved parameters).</li>
</ol></figcaption></figure>

- Changing a parameter **does not** run anything by default; press "Run to this step" to see the result. With "Auto apply" on, it previews 500 ms after each change and only the final change in a burst is sent.
- Parameter changes are held as a draft: "Save" writes them back to the flow, and leaving with unsaved changes asks whether to discard them.
- ROIs: a tool with a region parameter shows its ROI as soon as you open the page. Draw on the input image — rectangle, rotated rectangle, circle, ellipse, annulus (optionally a sector), polygon, polyline, line or point. Coordinates are pixels in that step's input image; a positive angle is clockwise on screen.
- "Re-run with last image" pins the same image while you tune; a template for locating or golden comparison can be created from a box drawn on the current image and saved as an asset directly.
- Tools with picture-list parameters can add a crop from the current preview image directly to that list; press Add from current image, draw a rectangle or rotated rectangle, then confirm. The free-form edge defect tool can also teach its contour model from the current image.
- **Ports** (below the parameters): tick which input and output ports are drawn on the canvas, drag a row or use the arrows to change their order, and give an output a published name. Connected ports are always drawn (remove the link first to hide one); "Order by downstream position" sorts the outputs so the edges do not cross. Hiding a required input that is not connected keeps the problem visible: the step gets a red badge and the check still fails. See [Ports](#ports) for the default rule.

## 6. The teach page, on-site parameters and recipes {#teach}

<figure class="shot"><img src="/docs/img/teach.jpg" alt="The teach page"><figcaption><b>Teach page</b> (Flows › teach icon, or the editor's "Not taught" badge, route <code>/flows/:id/teach</code>)
<ol class="callouts">
<li data-n="1">The <strong>steps</strong> that have on-site parameters; pick one.</li>
<li data-n="2">The <strong>on-site parameters</strong> of that step: only the ones the tool's author marked as teachable.</li>
<li data-n="3">A <strong>live preview</strong> that re-runs as you change values.</li>
<li data-n="4">The <strong>recipe</strong> row: which parameter set is being edited (the graph itself or a named recipe), and the recipe manager.</li>
<li data-n="5"><strong>Save</strong> writes the values to the graph or the recipe (Ctrl+S).</li>
<li data-n="6"><strong>Mark as commissioned</strong>: the engineer's sign-off that the flow is tuned; an uncommissioned flow still runs, its runs just carry a warning.</li>
<li data-n="7">The step's <strong>output values</strong> for the current image.</li>
</ol></figcaption></figure>

- **Recipes** are named parameter overrides for the same flow (product A, product B). "Save as recipe" stores the current values; the flow's default recipe is applied when nothing else is asked for, and an external trigger can name the recipe to use.
- **Changeover** is switching the active recipe on this page or through the API; an operator may do it, while changing a recipe's contents needs an engineer.
- An operator sees this page read-only when the role lacks "On-site parameters and changeover"; the header says why.

### 6-1. Station teach page and custom groups {#station-teach}

The **Station teach page** under Teaching gathers every visible flow's on-site parameters in one list. Use the Flow, Tool and Search filters when a station runs several flows for different camera sides or fixtures. Each row shows the flow, the step, the tool and the parameter, so a value is never detached from the flow graph it will update.

Saving uses the same flow update path as the single-flow teach page: the page builds one graph patch per changed flow and sends `PATCH /api/vision/flows/{id}` for each flow. If one flow saves and another is rejected, the result panel lists each flow separately with success or failure instead of hiding the partial result. Operators can still change only parameters marked as on-site teach parameters; changing a non-teach parameter is rejected by the server.

Custom groups are personal shortcuts stored with your account preferences. A group records only `flow_id`, `node_id` and parameter key; the current value always comes from the flow graph. If a shortcut points to a deleted flow, step or parameter, the page marks it as invalid and lets you remove it without breaking the rest of the page. Each user can keep up to 32 groups.

### Where the newer inspection tools live {#new-tools}

The tool picker groups every tool by category, so the additions of the algorithm round are found where their job is: **Pre-process** — Polar unwrap and Polar restore (rings, gears, threads), Flat-field correction (uneven lighting), Lens undistortion, Photometric stereo (four-light surface shape for embossed and engraved marks); **Locate** — Shape match (edge-direction matching that survives occlusion and lighting), Region from shape and Region combine (exclusion zones); **Measure** — the contour chain (Contour find, filter, geometry, match), Circular caliper and Profile defects (chipped rims), Form and position tolerance (straightness, roundness, parallelism and friends), Real-world coordinates; **Detect** — Statistical template compare, Anomaly detection (good parts only), OCR read and OCV verify, Barcode quality grade. Each has a ready template in the gallery whose sample pictures show the intended use, and the [Inspection capabilities](vision-capabilities.md) page lists what every one measures and how accurately.

## 7. Preview, run, continuous and statistics {#run}

| Action | Which version | What it does |
|---|---|---|
| Preview | The current canvas, unsaved changes included | Keeps every intermediate image; nothing is written to the run history. |
| Run once | The saved version | A real run, the same as an external trigger; written to the run history and the statistics. |
| Continuous | The saved version | Runs repeatedly at the configured interval; the dashboard shows the live image and result. |

<figure class="shot"><img src="/docs/img/stats.jpg" alt="The statistics page"><figcaption><b>Statistics</b> (dashboard card › statistics icon, or the editor toolbar, route <code>/flows/:id/stats</code>)
<ol class="callouts">
<li data-n="1">The <strong>KPI</strong> strip: runs, OK, NG, failed, yield and timing, from the hourly totals that survive restarts and clean-ups.</li>
<li data-n="2">The <strong>status filter</strong> for the run history below; clicking a row opens the run's images when they were archived.</li>
</ol></figcaption></figure>

Open an archived picture and press **Rerun this picture in the editor**: it becomes the editor's scratch image, so the reject from three days ago can be run again through the current flow while you adjust it.

**Image archive**: the platform **keeps no run images by default** (memory holds the last few and a restart clears them). To be able to show what the camera saw when a customer complains, turn on the image archive on this page (rejects only, or every run, with a sample rate for OK runs). From then on every reject and failure writes its source and result image to disk, reachable by clicking a row in the run history, and old ones are purged automatically once they exceed the retention period or the total size limit (`VISION_ARCHIVE_DAYS`, `VISION_ARCHIVE_MAX_GB`; ship a whole plant with it on using `VISION_ARCHIVE_DEFAULT`). The page reminds you when there are rejects but the archive is off.

### 7-1. The operator board {#board}

<figure class="shot"><img src="/docs/img/board.jpg" alt="The full-screen operator board"><figcaption><b>Operator board</b> (Overview › "Open the board", or the editor's Board settings, route <code>/board/:id</code>)
<ol class="callouts">
<li data-n="1">The <strong>board title</strong> (the flow name unless you set one).</li>
<li data-n="2">The <strong>verdict</strong> of the last part, large enough to read from across the line, with the verdict label when the flow gives one.</li>
<li data-n="3">The <strong>values</strong> chosen for this flow, each with its label and unit; a value outside its tolerance turns red.</li>
<li data-n="4"><strong>Today</strong>: total, OK, NG and yield, from the same hourly totals as the statistics page.</li>
<li data-n="5">The flow's <strong>variables</strong> (the lot number, the running count).</li>
<li data-n="6"><strong>Back to the platform</strong>. The board needs no sidebar; open it in the browser's kiosk mode on a screen by the line.</li>
</ol></figcaption></figure>

**Choosing what the board shows.** In the flow editor, with nothing selected, the Settings tab has a **Board** card: tick the named outputs to display, give each a label, a unit, the number of decimals and a min and max (values outside turn red on the board and on the Dashboard), pick which step's picture to show (the last one by default), list the variables to show, and switch the verdict, today's counts and the marks on or off. Save, then open the board. The Dashboard follows the same settings, so the live panel there shows the same values with the same colours.

Every part updates the board as it is inspected; the counts refresh every fifteen seconds. Building your own screen instead? One request, `GET /api/vision/flows/{id}/board`, returns exactly what this page shows, tolerance verdicts included ([Automation](/docs/automation.html#board)).

### 7-2. Operator dashboards {#dashboard}

The **Operator dashboards** page (`/dashboards`) lists the station dashboards that operators can open in kiosk mode. Each row shows the dashboard name, whether it is the default, the number of widgets, the last update time and the available actions. Operators can open a dashboard. Engineers can create a dashboard from an empty layout, the default layout or a built-in template, mark one dashboard as the default, copy one, delete one and open the visual layout designer.

#### Designing a layout {#dashboard-design}

The **Dashboard designer** (`/dashboards/:id/design`) is the engineering workspace for changing an operator dashboard without editing JSON first. The left column is the widget catalogue, the centre canvas is a row and column grid, and the right column shows layout, widget and advanced settings. Change the row and column count at the top of the canvas, click a cell to select it, drag across neighbouring cells to merge them, use Split to return a merged cell to single grid cells, and drag widgets from the catalogue into any cell. Widgets already in a cell can be selected, moved to another cell, reordered, duplicated or deleted.

The properties panel builds the available controls from the dashboard widget contract. Boolean options use checkboxes, numeric options use bounded number fields, choices use selectors, colours use swatches, and list-shaped options such as table columns, tabs, rules and image wall items use compact row editors. Source settings let engineers choose whether a widget reads a flow output, variable, image, status, count, SPC series or device value. The selected flow controls the available output, variable and image keys when that information is known.

| Widget | Use |
|---|---|
| Child dashboard | Embeds another dashboard one level deep. Nested child dashboards inside that child are hidden in the viewer, and the server collects only the child dashboard's direct flow references. |

Use **Save** to patch the dashboard layout, **Preview** to show a scaled kiosk view in the right panel, **Templates** to replace the current layout with a built-in starting point, and **Export JSON** or **Import JSON** to move layouts between stations. The advanced tab still contains the full JSON editor for exact changes and troubleshooting. Leaving the designer with unsaved changes asks for confirmation.

The full-screen viewer (`/dashboard/:id`, or `/dashboard` for the default) uses the layout JSON saved on the server. The center area is a cell grid. The top and bottom bars show the title, clock and device status when the layout enables them. The viewer subscribes to every flow referenced by the layout, so images, verdicts and values update as runs finish; the dashboard data packet refreshes every fifteen seconds for today's counts, station variables and device state.

**Editing the layout JSON.** Open **Edit layout**, change the `rows`, `cols`, `cells`, `bars`, `default_flow_id`, `widgets` and `theme` fields, then save. Each widget has an `id`, `type`, `cell`, optional `props` and optional `source`. The server validates the layout and returns the exact widget and field that need adjustment when the JSON is invalid. Use **Load default layout** to reset the text box, **Export JSON** to download the current layout and **Import JSON** to paste in a saved layout file.

### Measurements and precision on the Statistics page {#measurements}

The Statistics page has two views. **Yield** is the OK/NG history described above. **Measurements** is a control chart of one named output over time: pick the output, the chart (I-MR for one value per run, X̄-R with a subgroup size when runs come in batches) and the period (24 h, 7 d, 30 d). The chart draws the centre line and the control limits computed from the data, and the specification limits (USL/LSL, dashed) when a *Tolerance judge* step is bound to the same value — that binding is also what gives Cp and Cpk. Points that trigger a Nelson rule (one point beyond 3σ, nine on one side, six rising or falling, and so on) are drawn in red and the rules are listed under the chart. The values come from the measurement log, which keeps a year of numeric outputs independently of the run history, so a drift over the last three months is visible even though the run detail is long gone.

When a flow is drifting or out of specification *right now* (the latest points trigger a rule, or the last thirty include values outside the specification), the dashboard shows a measurement alert with a link to the flow's statistics. There is no push notification; the alert is on screen.

The **Precision study** card at the bottom of the Yield view runs the flow the way a verifier would test it — the same picture N times (repeatability) or the same part captured N times (reproducibility) — and reports the σ and range of every numeric output, with a copyable report. Gauge R&R over several parts runs from the command line (`manage.py precision`, see Performance).

## 8. Batch testing {#batch}

<figure class="shot"><img src="/docs/img/batch.jpg" alt="The batch test page"><figcaption><b>Batch test</b> (sidebar › Batch test, route <code>/batch</code>)
<ol class="callouts">
<li data-n="1"><strong>Test flow</strong>: the flow the images will run through; any set can test any flow.</li>
<li data-n="2"><strong>New image set</strong>: upload images or grab N from an image source (200 per set at most).</li>
<li data-n="3"><strong>Run</strong> the selected set with the test flow; it runs in the background with a progress bar and can be interrupted.</li>
<li data-n="4">The <strong>Results</strong> tab: per-image status, expected label, hit and outputs.</li>
<li data-n="5">The <strong>Insights</strong> tab: missed images, failing steps, threshold suggestions, output distributions and the trend across runs.</li>
<li data-n="6">The <strong>Tune</strong> tab: change on-site parameters and re-run, then write back to the flow, save as a recipe or send to the editor; the Images tab labels expectations and the Compare tab puts two runs side by side.</li>
<li data-n="7">The <strong>assistant</strong>: with a finished run selected it consults on the data or tunes from it.</li>
</ol></figcaption></figure>

1. Selecting a set fills in the flow it was created under; to compare a different flow, change the dropdown and run again. With unsaved changes in the editor you can tick "use the editor's unsaved draft".
2. Every run's per-image results are kept and can be revisited from the run list (a run against a different flow shows that flow's name).
3. On the Images tab, label each image with its expected OK or NG; the Results tab then shows the hit rate and which images matched, and Insights can suggest thresholds. "Apply and re-run" produces a new run.
4. Ask the assistant "why was image 3 NG?" or give a tuning instruction; the Tune tab also has "Auto-tune". All of them land as new runs, so nothing is lost.
5. Tick images and "Save to Golden Set" to make them a regression baseline. See [Batch testing](batch.md).

## 9. The Golden Set {#golden}

<figure class="shot"><img src="/docs/img/golden.jpg" alt="The Golden Set page"><figcaption><b>Golden Set</b> (Flows › Golden Set icon, route <code>/flows/:id/golden</code>)
<ol class="callouts">
<li data-n="1"><strong>Upload images</strong> as cases, each with its expected OK or NG (or send them from a batch run).</li>
<li data-n="2"><strong>Run regression</strong>: every case runs and is compared with its expectation and the baseline; regressed cases come first.</li>
<li data-n="3"><strong>Auto-tune</strong> searches the on-site parameters for a better hit rate and lets you apply the result.</li>
<li data-n="4"><strong>Baseline</strong>: freeze the current results as the reference for the next regression.</li>
</ol></figcaption></figure>

The Golden Set is the safety net after tuning: it tells you exactly which images flipped between OK and NG. It also runs from the command line (`manage.py regress`) so it can gate a CI pipeline. See [Golden Set and export](golden.md).

## 10. Image sources {#sources}

<figure class="shot"><img src="/docs/img/sources.jpg" alt="The Source library"><figcaption><b>Source library</b> (sidebar › Source library, route <code>/sources</code>)
<ol class="callouts">
<li data-n="1"><strong>New source</strong> opens the form (next figure).</li>
<li data-n="2"><strong>Download capture client</strong>: the desktop program for cameras on another PC or behind a vendor SDK.</li>
<li data-n="3"><strong>Manage groups</strong>: rename or delete the groups shown as filter chips above the list.</li>
<li data-n="4">The list, in two shapes chosen at the top right: <strong>the tree (default)</strong> groups the sources by kind and then by group, and <strong>cards</strong> show a preview picture of each. Both give the name, settings summary and live status (connected, fps, last frame), the switch that enables or disables a source and the eye that previews it.</li>
</ol></figcaption></figure>

The example sample pictures do not appear here any more: they travel with the templates as fixed images (see the Fixed image step above), so the library only holds your cameras, folders and pushed sources.

<figure class="shot"><img src="/docs/img/source-form.jpg" alt="The new source form"><figcaption><b>New source</b>
<ol class="callouts">
<li data-n="1">The <strong>kind</strong>: capture client camera, folder (read in a loop), a single file, pushed uploads, a synthetic generator, or a plugin kind.</li>
<li data-n="2"><strong>Browse</strong> opens a server-side file browser for folder and file kinds.</li>
<li data-n="3"><strong>Test grab</strong> grabs one image with the current settings before saving.</li>
<li data-n="4">The result: size, time taken and a thumbnail, or the reason it failed.</li>
</ol></figcaption></figure>

### When the camera is on another PC, or needs a Basler or IDS SDK {#sources-capture}

You do not have to move the camera to the server. Use "Download capture client", unzip and run `VisionSequenceCapture.exe` on the camera's PC, fill in the server address (port 9100) and a client name under Connection, then add the camera as a channel, open it and start acquiring (you can draw an ROI on the preview to send only that region, and adjust and save camera parameters). Back in the web interface, add a source of kind "capture client camera", pick the client and the channel, choose "on demand" (a fresh frame for every run) or "continuous stream", and press Test grab before saving. The status column shows whether the client is online, its fps and the age of the last frame; Integration › Capture client lists every connected client and lets you turn streaming on and preview. On the same machine it uses shared memory automatically; across machines it is lossless over TCP. "Capture client offline" in the list means the program is not connected. Details in [Capture client](/docs/capture-client.html).

**A capture client camera times out during a run**: first check on the client that the channel says it is acquiring and the preview is live. A camera in trigger mode needs a trigger signal. With a long exposure, or across a network, increase the source's timeout in milliseconds. Turning off "require a fresh frame" lets it use whatever frame the client already has.

### 10-2. Calibration: millimetres, lens distortion and robot coordinates {#calibration}

<figure class="shot"><img src="/docs/img/calibration.jpg" alt="The Calibration page"><figcaption><b>Calibration</b> (sidebar › Calibration, route <code>/calibration</code>)
<ol class="callouts">
<li data-n="1">The three ways to teach it, and what each one gives you. <strong>Calibration board</strong>: a few pictures of a printed board give the lens correction and the scale together. <strong>Robot points</strong>: mark places in the picture and type the coordinates your robot reports, so a position can be handed straight to the robot. <strong>Known distance</strong>: mark two points, type how far apart they really are, done.</li>
<li data-n="2">The <strong>image source</strong> to take pictures from; you can also upload photos taken earlier.</li>
<li data-n="3"><strong>Capture</strong> takes a picture. In board mode every picture is searched for the board straight away and listed with the number of points found, so you see immediately whether that angle worked.</li>
<li data-n="4">The <strong>board</strong>: pattern, and its size in <em>inner corners</em> (a board of 10 x 7 squares is 9 x 6) plus the spacing between two neighbours. Get these wrong and no board is found; the page says so rather than failing silently.</li>
<li data-n="5">The <strong>unit</strong> your drawings and your robot use.</li>
<li data-n="6"><strong>Calculate</strong> works it out but does <em>not</em> save it: you first see how well it fits.</li>
<li data-n="7"><strong>Save calibration</strong> stores it as an asset. Pick it afterwards in the Lens correction, Real-world coordinates or Pixel calibration step.</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/calibration-stereo.jpg" alt="Calibration › Stereo height"><figcaption><b>Stereo height</b> (a left/right camera pair measuring object height for robot picking)
<ol class="callouts">
<li data-n="1">The <strong>Stereo height</strong> mode: two cameras looking at the same belt from slightly different places; the difference between the two views gives the distance to each object.</li>
<li data-n="2"><strong>Import stereo_config.json</strong> if the pair was calibrated elsewhere; only the two camera models and their relative pose are read, the rest is recomputed here.</li>
<li data-n="3"><strong>Capture pair</strong> takes both pictures at once and lists every pair with its time offset and fit error; at least five pairs of the same board, then Calculate, then Save.</li>
</ol></figcaption></figure>

**Belt height reference.** Below the pair list, measure the empty belt once and type the robot Z that belt surface corresponds to; from then on the Stereo depth step reports each object top as an absolute robot Z, not just a distance from the camera. Without that reference the step still reports the distance and leaves Z empty.

**Which way to use.** If you only need measurements in millimetres, *Known distance* takes a minute: mark two points on something you have measured, type the distance. If the lens visibly bows straight edges near the corners, or the same part measures differently in the middle and at the edge of the field, use a *calibration board* — take three or more pictures with the board tilted and at different distances, filling the frame. If a robot has to go and pick the part up, use *Robot points*: jog the robot to three or more spots you can see, and type the coordinates it reports at each one.

**Read the error before you save.** Every method reports how well it fits. A board calibration shows the reprojection error per picture, so you can delete the one that was blurred and calculate again. Robot points show the error of *each* point, and the worst one is marked red on the image — usually that is where the robot was jogged to the wrong place or a coordinate was typed wrong. The result carries a plain verdict: good, fair, or do it again.

**Marking points is forgiving.** Click near a hole, a printed dot or a corner and the mark snaps to its centre, so you do not have to hit the exact pixel. Turn that off if you really want the spot you clicked.

**Using it in a flow.** One saved calibration serves all three steps: *Lens correction* straightens the picture (put it right after the image source, before anything that measures), *Pixel calibration* in "from a calibration" mode converts a length to millimetres, and *Real-world coordinates* converts a position to the coordinates your machine works in, along with lengths and angles. Because they all read the same asset, recalibrating the station updates every flow at once — you do not go hunting for the number typed into each step.

If the camera is later moved, refocused or swapped, calibrate again. A calibration made at full resolution still works when the flow runs at half resolution: the lens correction is rescaled automatically, and if the aspect ratio differs the step says so instead of quietly correcting the wrong amount.

## 11. Assets {#assets}

<figure class="shot"><img src="/docs/img/assets.jpg" alt="The Asset library"><figcaption><b>Asset library</b> (sidebar › Asset library, route <code>/assets</code>)
<ol class="callouts">
<li data-n="1"><strong>Upload asset</strong>: a template image, a model file (ONNX or a trained weight) or a dataset archive.</li>
<li data-n="0"><strong>Tree or cards</strong>: the switch at the top right of the page. <strong>The tree is the default</strong> — kind, then group, then the assets with their sizes and dates, which is what you want when the library holds models and files that have no thumbnail; cards show thumbnails instead. Your choice is remembered on this browser.</li>
<li data-n="2"><strong>Manage groups</strong>, the same way as sources.</li>
<li data-n="3">The asset cards; a tool page can also create a template from a box drawn on the current image and save it here directly.</li>
</ol></figcaption></figure>

Templates are used by locating and golden-comparison tools, models by the deep-learning tools, and dataset archives by the teaching page. A reference picture can also be given to a tool without an asset: connect a Fixed image step (role "reference") to the tool's picture input port, which is how the built-in templates carry their golden prints and locator templates. The example statistical template, shape model and taught models are in the "Examples" group.

## 12. Deep-learning teaching {#dl}

<figure class="shot"><img src="/docs/img/dl.jpg" alt="The DL teaching page"><figcaption><b>DL teaching</b> (sidebar › DL teaching, route <code>/dl</code>)
<ol class="callouts">
<li data-n="1"><strong>New teaching project</strong>: choose the model kind (classification, semantic segmentation, instance segmentation, detection, pose, oriented boxes).</li>
<li data-n="2"><strong>Auto-label</strong>: let the current model, or the smart-select model, propose labels that you confirm.</li>
<li data-n="3"><strong>Train</strong>: split into train, val and test, freeze a dataset version and start training on the server; the finished model lands in the asset library.</li>
<li data-n="4"><strong>Create samples from video</strong> (collapsed until you open it): pick a video recorded by the capture client, the model to segment with, how many pictures to keep per tracked object and the frame interval between them; every kept frame becomes a sample with its objects already outlined, ready for correction.</li>
</ol></figcaption></figure>

1. Samples: upload pictures or a zip, grab a burst from a source, import a dataset folder, or extract them from a video; duplicates are skipped automatically. Click a thumbnail to label it.
2. Label: for classification, click a thumbnail and choose the class; for segmentation and detection, draw polygons or boxes, with "Smart select" clicking an object to trace it automatically.
3. "Create a flow with this model" after training builds an acquire → inference flow and opens it in the editor.

See [Deep-learning teaching](dl.md) for trainers, GPU setup and export formats.

## 13. The AI assistant page: a flow from an image {#agent}

<figure class="shot"><img src="/docs/img/agent.jpg" alt="The AI assistant page"><figcaption><b>AI assistant</b> (sidebar › AI assistant, route <code>/agent</code>)
<ol class="callouts">
<li data-n="1"><strong>Upload image</strong>: one or more images; draw the areas to inspect on them. Each ROI is numbered (ROI01, ROI02…) and can carry a hint such as "good", "bad" or "locator".</li>
<li data-n="2">The <strong>request</strong>: one sentence — "there should be 5 holes", "measure the diameter, 17.5 ± 0.4 mm", "ROI01 is good and ROI02 is bad, find the difference".</li>
<li data-n="3"><strong>Generate</strong>: the assistant asks for anything it still needs, generates the flow and runs it on every image, marking each thumbnail OK or NG.</li>
<li data-n="4"><strong>AI provider</strong>: the offline rule engine or Claude, GPT or Gemini with your own key (stored on the server, tied to your account); saving tests the connection, "List models" shows what the key can use, and the working mode chooses single or agentic.</li>
<li data-n="5"><strong>Skills</strong>: what the assistant follows, with your own or the site's notes added under each skill.</li>
</ol></figcaption></figure>

1. Optionally mark each thumbnail with the verdict it should get; an image whose ROI hint says "good" or "bad" is labelled automatically. An ROI hinted as "locator" marks a fixed feature, and the flow then gets locate correction added in front when the part can move.
2. The rule engine produces several candidates and picks the best against your labels — the result card lets you switch between them — and with two or more labelled images it auto-tunes.
3. Refine it in words ("too many false rejects", "expect 4 instead", "tolerance ±0.2"), then "Save as flow" to open it in the editor. Thumbs up or down on the result card influences whether these parameters are reused on similar images later.
4. History shows past sessions, and "Restore" brings back the images, ROIs, request and labels and re-runs them. In agentic mode the assistant drafts, tries, edits and verifies step by step, showing a timeline you can interrupt or answer questions in.

See [AI assistant](agent.md).

## 14. The global assistant (on every page) {#assistant}

<figure class="shot"><img src="/docs/img/assistant.jpg" alt="The assistant panel open on the Source library"><figcaption><b>AI assistant panel</b> (the button in the bottom-right corner of every page)
<ol class="callouts">
<li data-n="1">The <strong>button</strong> opens and closes the panel; a badge counts unread hints.</li>
<li data-n="2">The <strong>mode</strong> chips: Auto routes by itself; Help, Edit flow, Consult data and Tune from data force a mode.</li>
<li data-n="3"><strong>Memory</strong>: the facts you asked it to remember and your rated answers.</li>
<li data-n="0"><strong>New conversation</strong> (＋) and <strong>past conversations</strong> (the clock, next to it): conversations are kept with your account — the panel saves the current one as you talk, and the list reopens or deletes an older one. Fifty conversations per person, sixty messages each; the newest survive.</li>
<li data-n="4"><strong>Screenshot</strong>: attach a picture of this page to the next question (needs an LLM provider that reads images).</li>
<li data-n="5"><strong>Screen text</strong>: attach a text summary of what is on screen to the following questions.</li>
<li data-n="6"><strong>Sharing</strong>: whether the page snapshot and your recent actions travel with each question; off means it only knows which page you are on.</li>
<li data-n="7"><strong>Quick prompts</strong> for the current page.</li>
<li data-n="8">The <strong>input</strong>: a question, an instruction, or "remember: …" to store a fact.</li>
</ol></figcaption></figure>

- Type a question ("how do I create an image source from a folder?") and it answers from the platform documentation, in the interface language, naming the page, tab and button, with links to the sections it used and a "go there" chip when the answer is a place.
- In the flow editor, type an instruction ("set the blob minimum area to 40", "disable the noise removal") and it edits the current canvas; "Apply to canvas" writes it back, and it can be undone. On the batch page, with a finished run selected, ask about the data or give a tuning instruction, and the result becomes a new run.
- It sees your situation: the page, what is selected, the last run, recent errors, your role and the engine lock. When something recognisable fails — a locked engine, a role that is not allowed, a receiver that is not listening, a step without a source — a hint card appears with a one-line explanation and "Ask the assistant".
- With an LLM provider it can also read the live state (flows, sources, connections, a run report, the lock, plugins) before answering, always within your own permissions; the reply lists what it checked.
- **Choosing hardware**: ask which camera, lens or lighting a job needs (field of view, working distance, smallest feature, belt speed, frame rate) and it works the numbers out — focal length and the nearest stock lens, the pixels the feature needs, depth of field, the exposure that stops motion blur, the bandwidth and which interface carries it — then explains the lighting that makes the defect visible.
- Rate answers with thumbs up or down: good ones are reused for similar questions. Conversations and memory are yours alone — another person signing in sees their own.

## 15. Integration {#integration}

<figure class="shot"><img src="/docs/img/integration-http.jpg" alt="Integration › HTTP API"><figcaption><b>Integration › HTTP API</b> (sidebar › External integration › HTTP API, route <code>/integration/http</code>)
<ol class="callouts">
<li data-n="1">The <strong>sub-pages</strong>: HTTP API, TCP commands, Event monitor, Modbus server, Modbus client, Capture client, Plugins.</li>
<li data-n="2">The <strong>info bar</strong>: HTTP base, TCP port, capture port, whether an API key is required, workers and timeout.</li>
<li data-n="3">The <strong>tabs</strong> of the page: Try it, Response format, Commands and results.</li>
<li data-n="4"><strong>Search</strong> the API.</li>
<li data-n="5">The <strong>endpoints</strong>, the essential ones first with a plain-language description; open one to fill in parameters, execute it and copy a curl, Python or C# snippet.</li>
</ol></figcaption></figure>

- HTTP: `POST /api/vision/flows/{id}/run` (optionally with an image and a recipe) returns the verdict, the named outputs and the run id. TCP: `RUN <id>` on one line; the TCP page lists every command with its failure codes and has a console to try them. Events: an SSE stream that the Event monitor page shows live.
- The **Commands and results** tab on each page shows what came in and what went out on that channel in the last minutes — the first place to look when a device "did nothing".

<figure class="shot"><img src="/docs/img/integration-modbus.jpg" alt="Integration › Modbus server"><figcaption><b>Integration › Modbus server</b> (route <code>/integration/modbus-server</code>; Modbus client and TCP commands manage their connections the same way)
<ol class="callouts">
<li data-n="1"><strong>Connections</strong>: the connections of this kind; the platform listens here and any Modbus TCP master reads results and writes triggers.</li>
<li data-n="2"><strong>Address format and mapping</strong>: how registers and coils map to flow outputs and triggers.</li>
<li data-n="3"><strong>Commands and results</strong>: every request the master sent.</li>
<li data-n="4"><strong>New connection</strong> (no kind to choose; the page decides it).</li>
<li data-n="5">The connection list with live status; the icons test a connection, write values by hand, edit and delete.</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/integration-capture.jpg" alt="Integration › Capture client"><figcaption><b>Integration › Capture client</b>
<ol class="callouts">
<li data-n="1"><strong>Download capture client</strong> (version, size, SHA-256) with the setup steps and whether the capture port is listening.</li>
<li data-n="2">Every connected client and channel (size, mode, fps, last frame, which source uses it) with streaming and preview controls.</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/integration-plugins.jpg" alt="Integration › Plugins"><figcaption><b>Integration › Plugins</b>
<ol class="callouts">
<li data-n="1"><strong>Rescan</strong> mounts files newly dropped into <code>plugins/</code> and retries failed ones (a changed file that was already loaded needs a restart).</li>
<li data-n="2">What each plugin file mounted (tools, sources, writers, trainers), disabled ones and load errors with the pip hint.</li>
<li data-n="3">Connections whose kind comes from a plugin.</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/integration-devices.jpg" alt="Integration › Device connections"><figcaption><b>Integration › Device connections</b>
<ol class="callouts">
<li data-n="1"><strong>New connection</strong>: serial port, UDP, a local TCP text server or a light controller; a light controller preset fills the command templates, the saved configuration stays the source of truth.</li>
<li data-n="2">Each connection with its kind, settings and live state; the state of a light controller shows the last brightness per channel and the last command sent.</li>
<li data-n="3"><strong>Export</strong> and <strong>Import</strong> move every connection and rule table between stations with secrets masked.</li>
</ol></figcaption></figure>

Line-based equipment (barcode readers, older hosts, light controllers) lives here; each received line runs through the same station rules as the TCP command port, and flows drive lights with `set_light`, `io_output` and `multi_light_grab`.

See [Automation](/docs/automation.html), [Modbus](/docs/modbus.html), [Capture client](/docs/capture-client.html) and [Plugins](/docs/plugins.html).

## 16. The engine lock {#lock}

<figure class="shot"><img src="/docs/img/lock-banner.jpg" alt="The lock banner on the Overview page"><figcaption><b>Locked engine</b>
<ol class="callouts">
<li data-n="1">The <strong>banner</strong> under the top bar: who holds the lock and why; an administrator or the holder can release it from here.</li>
<li data-n="2">Everything that runs the engine — Run once, Preview, Continuous — is refused with error 423 while locked; editing and saving still work.</li>
</ol></figcaption></figure>

An integrator or an administrator locks the engine from the outside — HTTP `POST /api/vision/lock` or the TCP command `LOCK` — to keep the hardware for a machine cycle or a maintenance window; `UNLOCK` or `DELETE` releases it, and a lock can carry a time-to-live so a forgotten one expires. Every continuous run stops when the lock is taken. The integrator's own triggers are not affected.

## 17. Audit trail, settings and help {#admin}

<figure class="shot"><img src="/docs/img/audit.jpg" alt="The Audit trail"><figcaption><b>Audit trail</b> (sidebar › Audit trail; administrators, or a role given the audit function)
<ol class="callouts">
<li data-n="1">Filter by <strong>action</strong> (flow.update, recipe.activate, user.create, lock.acquire…) or by actor.</li>
<li data-n="2"><strong>Search</strong> the summaries and target names.</li>
<li data-n="3"><strong>Export CSV</strong>.</li>
</ol></figcaption></figure>

Next to the search box, **From** and **To** restrict the list to a date range (the To day included) and **Rows per page** chooses 25 to 500 rows; the same `since`/`until`/`limit` parameters work on the API and the CSV export.

The trail records changes, not runs: who changed which flow, parameter, recipe, source, connection, account or lock, when and from where, with a parameter-level diff for flows. Runs are in the statistics and the image archive instead.

<figure class="shot"><img src="/docs/img/settings.jpg" alt="The Settings page"><figcaption><b>Settings</b> (sidebar › Settings)
<ol class="callouts">
<li data-n="1">Your own <strong>display name</strong> (an administrator still manages usernames, roles and other people's passwords on the Users page).</li>
<li data-n="2"><strong>Change password</strong>.</li>
<li data-n="3">The interface <strong>language</strong> (English, 繁體中文, 简体中文).</li>
<li data-n="4">The <strong>theme</strong> (light, dark, Cyberpunk or follow the system). Language and theme are stored with your account and follow you between devices.</li>
</ol></figcaption></figure>

**Data retention** (administrators only, on the same page): how long run detail, the audit trail, measurements and archived pictures are kept — a year by default, and zero means for ever — plus how many backups to keep and which hour the maintenance window runs in. The card also shows the database size, how many rows each store holds and when the last clean-up ran, with a "Clean up now" button. Clean-up only happens while the engine is idle, in small batches, so it never delays an inspection; hourly totals (the yield curves) are never deleted. See [Deployment §9a](/docs/deployment.html#retention).

**Display** is stored per browser. The mark display limit controls how many overlays the image viewer draws from a dense result; when a run produces more marks than the limit, the viewer draws the first set and shows a count badge so the browser stays responsive. The same card can turn off editor draft version auto-save; when it is on, the editor saves a version every 5 minutes only if the draft graph changed since the last save.

<figure class="shot"><img src="/docs/img/help.jpg" alt="The Help page"><figcaption><b>Help</b> (sidebar › Help)
<ol class="callouts">
<li data-n="1"><strong>Quick start</strong>: the condensed walkthrough.</li>
<li data-n="2"><strong>Glossary</strong>: pages, editor areas, core terms and status wording.</li>
<li data-n="3">The <strong>tool catalogue</strong>: every tool with its parameters and ports, in the interface language; the other tabs cover port colours, shortcuts, the automation API and accounts.</li>
<li data-n="4">The content of the selected tab.</li>
</ol></figcaption></figure>

## 18. Common questions {#faq}

| Situation | What to do |
|---|---|
| A preview says the image is no longer in the cache | Upload the scratch image again, or run the flow once to get a new image. |
| find_circle or find_line reports nothing found | Check the ROI covers the edge (an annulus for a circle, a caliper ROI straddling both edges), lower the edge threshold, or change the polarity. |
| Testing an AI provider fails | Follow the reason shown: an invalid key, a model that has been retired (rename it as suggested), the provider overloaded (retry later or switch model), or a timeout (check the network). |
| A run reports the engine is locked | An integrator holds the lock; wait for it to be released, or ask an administrator to clear it from the banner ([16](#lock)). |
| Continuous mode keeps reporting a full queue | Increase the interval, or check how long the flow takes; the performance report gives the cost of each tool. |
| A connection test says nothing is listening | The platform connects out to the host program: start the receiver first, then test again. The receiver example is in [Modbus](/docs/modbus.html). |
| The camera is on another PC, or needs a Basler or IDS SDK | Use the capture client ([10](#sources-capture)). |
| An operator cannot change a parameter | Only on-site parameters are editable by operators, and only when the role has "On-site parameters and changeover"; an administrator grants it on the Users page ([2](#login)). |
| Where is …? | Ask the assistant in the bottom-right corner: it names the page and tab and offers a "go there" chip. |

## Quick reference {#quick-reference}

### Quick start {#quick-start}

1. **Create a flow** Press "New inspection" (task page) or "New advanced flow" (canvas) on the Flows page, or copy one of the demo flows. A flow belongs to the line rather than to a person: any engineer can see and edit it, and the Owner column only records who created it.
2. **Acquire an image** Insert an "Image source" step from the palette and pick a folder, synthetic or capture client source from the source library — or use "Upload scratch image" in the toolbar to provide one image for previews only (it does not join the library). Cameras are driven by the capture client on the PC they are attached to ("Download capture client" on the Image sources page): connect it to the server and add a "capture client camera" source naming the client and the channel.
3. **Add tools** Drag a tool from the palette onto the canvas (or click to insert it at the right), then drag from one step's output port to the next step's input port. Only ports of the same colour connect.
4. **Draw an ROI** For a tool with a region parameter, press "Edit on image" on the tool page or in the inspector and drag out a rectangle, circle, polygon or any other shape directly on the image. Coordinates are pixels in that step's input image.
5. **Preview** "Preview" in the toolbar runs the current canvas, unsaved changes included, and keeps every intermediate image; "Re-run with last image" pins the same image while you tune. The icon beside a step name opens its tool page, where changing a parameter re-runs to that step and shows the before and after images with a histogram.
6. **Judge** Use the "Judge" tool to give an OK or NG, and "Named output" to name the values you want returned to the automation system.
7. **Save** Ctrl+S, or "Save" in the toolbar. "Run once" and "Continuous" use the saved version.
8. **Trigger it from outside** An external system triggers a flow with HTTP POST /api/vision/flows/{id}/run (optionally with an image) or a TCP command, and collects the result from the response or over SSE. Details on the Automation API tab.
9. **Template gallery** "Create from template" on the Flows page, or "Load template" in the editor toolbar: more than sixty built-in templates covering counting, measurement, defects, colour, code reading and deep learning (stock models and taught models). Pick the matching "Example: …" image source and it runs as it is. Your own flow can be saved as a template too.
10. **AI assistant** The AI assistant page: upload an image, mark the areas to inspect (ROI01, ROI02… each with its own hint) and describe what you want in a sentence. The assistant checks it has enough to go on, generates the flow and runs it on that image. Mark each thumbnail with the verdict it should get and the assistant ranks its candidates against them and auto-tunes. Refine it in words, then "Save as flow". History restores a past session and AI skills takes your own notes; with the working mode set to agentic, the assistant tries, edits and verifies step by step with a timeline. The global assistant in the bottom-right corner opens on any page: it answers questions from the documentation with links, edits the current flow in the editor, and consults or tunes from the data on the batch page.
11. **Batch testing and the Golden Set** "Batch test" in the sidebar: pick a flow, upload images or grab them from a source to build an image set, and every run keeps its per-image results. Label the images with their expected OK or NG to get a hit rate, insights and suggested thresholds; change parameters, run the same set again and compare; then write it back to the flow or save it as a recipe. You can also ask the AI assistant to consult on or tune from the data. Tick cases and save them to a Golden Set as a regression baseline.
12. **Deep-learning teaching** "Deep learning" in the sidebar: create a teaching project, collect samples (uploaded or grabbed from a source), label classes or shapes (smart select included), train, and export the model to the asset library for a DL tool to use in a flow.
13. **Source and asset groups** Both the image source library and the asset library support groups: filter with the chips above the list, and rename or delete under "Manage groups". The example sources and assets are all in the "Examples" group.

### Ports {#ports}

| Type | Colour | Used for |
|---|---|---|
| `image` | blue `#3b82f6` | Images |
| `region` | purple `#a855f7` | ROIs |
| `number` | green `#22c55e` | Numbers |
| `bool` | orange `#f97316` | Booleans |
| `string` | yellow `#eab308` | Strings |
| `points` | cyan `#06b6d4` | Point sets |
| `contours` | indigo `#6366f1` | Contours |
| `matches` | pink `#ec4899` | Match and detection results |
| `list` | teal `#14b8a6` | General lists, overlays included |
| `any` | grey-white `#cbd5e1` | Anything |
| `flow` | grey (diamond) `#94a3b8` | Branching |

Not every port is drawn. A step shows its connected ports, the tool's default ports (the first image port and the branch outputs), outputs with a published name, and required inputs that are not connected; the rest are collapsed behind a "+N" badge on the card — click it to expand the step for this view only. Which ports are shown, their order and their published names are edited on the tool page (Ports section, also reachable from "Edit ports…" in the inspector) and stored with the flow.

### Keyboard shortcuts {#shortcuts}

| Key | Action |
|---|---|
| `Ctrl+S` | Save the flow |
| `Right-click a step` | Step menu: open the tool page, duplicate, disable, delete, copy or paste parameters |
| `Ctrl+Z` | Undo |
| `Ctrl+C / Ctrl+V` | Copy and paste the selected steps, internal edges included |
| `Delete / Backspace` | Delete the selected steps or edges |
| `Esc` | Clear the selection, or leave ROI editing |
| `Left-drag (select mode)` | Rubber-band several steps; middle- or right-drag pans the canvas |
| `Shift+drag (pan mode)` | Rubber-band selection |
| `Scroll wheel` | Zoom the image viewer and the canvas |
| `F / 1 / + / − (image viewer)` | Fit, 1:1, zoom in, zoom out |
| `Double-click the image` | Fit to window |

### Automation entry points {#automation-entry}

**HTTP trigger**

```
POST /api/vision/flows/{id}/run?wait=1
Headers: X-API-Key: <key>  (or Authorization: Bearer <token>)
multipart: image=<file>   or   JSON: {"context": {...}}
-> 200 RunReport (wait=1) / 202 {"queued": true} (wait=0)
```

**Preview (what the tool page uses)**

```
POST /api/vision/flows/{id}/preview
{"graph": {...}, "reuse_image_ref": "...", "until_node": "blob", "analysis": true}
```

**Scratch image / reset**

```
POST /api/vision/flows/{id}/scratch-image  (multipart image) -> {ref,width,height,name}
DELETE /api/vision/flows/{id}/recent -> clears the in-memory run records and statistics (SSE sends cleared)
```

**Event stream (SSE)**

```
GET /api/vision/flows/{id}/stream?since=<seq>
Events: run_started / run_finished (with run) / stats / continuous / lock / cleared / ping (a 15 second heartbeat)
```

**Capture client (the camera is on another PC)**

```
Image sources -> "Download capture client" -> unzip and run VisionSequenceCapture.exe on the camera's PC
Connection: the server address and port 9100 (VISION_CAPTURE_PORT), a client name, and the key when the server sets VISION_CAPTURE_AUTH or API_KEY
Channel: choose the camera, open it, start acquiring; draw an ROI to send only that region
Web: add an image source of kind=capture {client, channel, mode: on_demand|stream, timeout_ms, fresh, encoding}
Headless: VisionSequenceCapture-console.exe --headless --connect  (for Task Scheduler or a service wrapper)
```

**TCP**

```
One command per line (terminated with \n, case-insensitive), one JSON reply per line:
RUN <flow id or name> [key=value ...] -> {"ok": true, "status": "ok|ng|failed", "judge": "OK|NG|FAILED|NONE", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}
TRIGGER <flow>   -> trigger without waiting, {"ok": true, "queued": true}
STATUS [flow]    -> statistics; without a flow, the capacity and the engine lock
START <flow> / STOP <flow> -> continuous mode
LOCK [reason="..." ttl=600] / UNLOCK -> hold the hardware: the interface can edit but not run
LIST / PING
Images are pushed into an image source of kind=upload with POST /api/vision/sources/{id}/push.
```

### Accounts and the engine lock {#accounts-quick}

- The first time you use it there are no accounts at all, and the sign-in page lets you create the first administrator.
- Administrator: manages accounts, role permissions and system settings. Engineer (the default): creates and edits flows, sources, assets, deep-learning teaching, batch tests and Golden Sets. Operator: runs inspections, starts and stops continuous mode, changes over between recipes, and adjusts on-site parameters on the teach page.
- Role permissions: that split is the factory setting, not a fixed rule. On the Users page an administrator ticks function by function what an engineer and an operator may use — deep learning, batch testing, the audit trail, the outgoing connections. Administrators always have everything, and the server checks every request, so an untick cannot be worked around by typing the address.
- A flow belongs to the line, not to a person: every engineer can see and edit every flow, and the Owner column only records who created it.
- An integrator (an automation system) calls with an API key (X-API-Key) and can always execute a flow.
- Engine lock: an integrator takes it over HTTP (POST /api/vision/lock) or TCP (LOCK), which stops every continuous run and leaves everyone else able to edit but not preview or run. A banner across the top of the interface says who holds it and why; an administrator or the holder can release it from there, and a lock can carry a timeout after which it releases itself.
- Change your own display name and password on the Settings page; an administrator can reset someone else's password, change roles and disable an account on the Users page.
