# AI assistant: an image, some ROIs and a sentence become an inspection flow

The AI assistant (in the sidebar, `/agent`) lets someone who does not know the tool chain build an inspection in three steps: **upload an image → mark the areas to inspect (several ROIs, each with its own hint) → describe what you want in a sentence**. The assistant generates an ordinary flow graph, runs it on that image immediately and draws the results back onto the picture. If it is not right, say so in plain language ("too many false rejects", "it is missing them", "make it 4") and it iterates. When it is right, save it as a flow and carry on tuning in the editor.

## Part 1 · The global assistant (on every page) {#editor}

The chat panel in the bottom-right corner of every page: it answers questions from the documentation and the interface map, sees your situation, can read the live state, edits the flow you are looking at, tunes from batch data, and remembers what you tell it.

The **AI assistant** button in the bottom-right corner is on every page (`AssistantDock` lives in the AppShell) and opens a chat panel that stays put: changing page does not close it. The panel button in its header docks it as a **side panel** (the page makes room for it) or floats it back into the corner; the choice is remembered on this device. **Conversations belong to your account**: the panel keeps writing the current one to the server, ＋ starts a new one, and the history button lists the past ones to reopen or delete (fifty per person, sixty messages each), so the same conversation is there from another PC. One input box routes on **the current page's context**, so there is no hunting for the AI feature on each page:

| Context (page) | What it does | Backend |
|---|---|---|
| Any page | **Help**: answers questions about using the platform, with links to the documentation sections it used (`/docs/…`) | `POST /agent/chat` → `help.py` |
| Flow editor and tool page | **Edit the flow**: an instruction edits **the current canvas**, unsaved changes included, and the reply says what changed; "Apply to canvas" writes it back and can be undone. On a tool page it offers guidance for that tool's parameters | `service.edit` (in agentic mode via `/agent/jobs` task=edit) |
| Batch page, with a finished run selected | **Consult the data** (the answer carries applicable parameter suggestions) and **tune from the data** (the result becomes a new run and is selected) | `consult.consult` and `service.tune` plus `persist_tune` |

The mode chip defaults to Auto: a question (with "how", "why", "what" or a question mark) always goes to help; an instruction ("change", "disable", "loosen", "add") edits the flow in the editor and tunes on the batch page; and words about the data ("image 3", "NG", "threshold", "results") on the batch page go to consultation. When it guesses wrong, pick "Help", "Edit flow", "Consult data" or "Tune from data" by hand. A page registers its context with `useRegisterAssistantContext` (kind, the current graph, the apply callbacks, the batch run id), which is cleared when you leave.

### From a conversation to an inspection task list {#tasklist}

On the **Inspection tasks** page the assistant turns what you say into a proposed task list instead of a graph. One message can carry several requests — "locate the part with the cross mark and allow rotation; outer diameter 35 ±0.2 mm, inner 26 ±0.2 mm; gaps over 2 mm fail" — as well as changes ("tighten the outer diameter to ±0.1") and removals. The proposal appears as a card with one block per task: values you said are **Confirmed**, values the assistant guessed are marked **Assumption**, and required values nobody gave are **Missing**. Regions it estimated from the image are drawn as dashed outlines when you select **Show on image**; they stay proposals until you apply them.

Nothing changes until you select **Confirm all**; **Discard** drops the proposal. The card will not apply while a value is missing, when millimetres are asked for without a calibration, or when the image source is ambiguous — it asks instead. Applying goes through the same task builder as the form on the page, so the result is identical to building it by hand; save it from the page as usual.

### Picking up where you left off {#resume}

A conversation opened on a flow is linked to that flow and keeps its working state outside the graph: the decisions made, questions still open, unconfirmed assumptions, which sample images were for tuning and which for acceptance, and the last trial. Opening the assistant on that flow again shows a **Resume** card: **Continue** reloads the conversation, pending questions can be answered straight from the card, and if the flow has been saved since, the card says so and lists what changed from the flow's version history. The specification itself is always read back from the flow — the conversation never keeps a second copy. Decisions listed under **Engineering decisions** can be saved as an engineering-note draft.

### How help answering works {#help-answering}

On the first query, `agent/help.py` splits `docs/*.html` into sections (by h2 and h3, with their anchors), adds each tool's skill text (`skills.base_skill_text`) and builds an index. Tokenisation is whole alphanumeric words plus CJK bigrams; scoring is BM25 with a small boost for title hits and for the user guide, batch and assistant pages. The index rebuilds itself when the documentation files change. With an LLM available, the five most relevant sections (plus that tool's skill on a tool page) go to the provider along with the recent conversation and the question, under a system prompt that requires it to **answer only from the passages, say plainly when the documentation does not cover it, stay under 300 words and list the sections it used**. Offline, or when the LLM fails, it returns an extract and links, with the reason in warnings.

Instructions the editor understands offline:

| Offline instruction | Effect |
|---|---|
| set the threshold of "Binarise" to 80 | Finds the node by its title, id or tool name; the parameter by its key or its label |
| disable / enable "Denoise" | Toggles the node's enabled flag |
| delete "Result image" | Removes the node and its edges (image_source cannot be deleted) |
| too many false rejects / it is missing them / make it 4 / ±0.2 | The same parameter mapping as iterative refinement |
| find the outer circle first, then let the inner circle's ROI follow it | Adds a `shape_align` fed by the first node's centre (`cx`/`cy`, or `matches`) and wires its `transform` into the second node's implicit `_transform` port; "outer / inner" that match no node title pick the largest / smallest ROI. The reference position is taught from the current picture's trial run |
| just do it / please change the canvas | An instruction with no content of its own reuses the previous request from the conversation |

With an LLM provider connected there is no fixed grammar: "add a tolerance judge of ±0.5 after the circle find", "replace the colour comparison with a colour range and a pixel count". The LLM receives the current graph, the tool catalogue and the recent conversation, changes only what it needs to and keeps the node ids. Whatever produced the change, the reply lists what differs from the current graph (added or removed steps, parameter and enabled changes, link counts); a reply that changes nothing has no "Apply" button.

### What the assistant knows about your screen {#situation}

Besides the documentation, every question carries the user's **current situation**, so the answer matches what is on screen instead of being generic:

| What is sent | Where it comes from | Example |
|---|---|---|
| Page kind, route and interface language | `AssistantDock` (always) | `tool page, /flows/3/tools/blob, zh-Hant` |
| Page snapshot: what the page shows now | Each page registers a `describe()` callback (`lib/assistantContext.ts`); the flow editor reports the selected step, unsaved changes and the last run; the tool page its parameters and last result; the batch page the image set and the run summary. A DOM snapshot adds the page title, an open dialog and the lock banner for pages without a callback | `{"selected": {"id": "blob"}, "dirty": true, "last_run": {"status": "failed", "error": "Image source is not set"}}` |
| Activity trail: the last 20 navigations, failed requests, toasts and run results | `lib/activity.ts`, an in-memory ring buffer fed by the API client, the toast provider and the run/preview hooks; secrets are masked before anything leaves the browser | `5s ago [error] POST /vision/sources/test -> 422 no_frame — Nothing is listening at 127.0.0.1:9001` |
| Caller and lock | Added on the server from the request itself (`agent/situation.py`): the caller's role and allowed features, and the engine lock | `Caller: op, role operator, allowed features: flows.run` |

The LLM is told to explain a recent error first when it explains the question, to point at the exact page, tab and button, and never to suggest an action the caller's role cannot perform. The **interface language** governs the answer: the prompt names it (en, zh-Hant or zh-Hans, so the two Chinese scripts are never mixed), the interface map is given as "English / interface-language" names so pages, tabs and buttons are called what the user sees, and the rule-mode texts and warnings are localised the same way. When the question itself is about a failure ("why", "failed", "error"…), the rule answer starts with the most recent error and the error text joins the search terms, so the failure code lands on the right documentation section; an unrelated "where is…" question is not pulled towards the last error.

The **interface map** (`frontend/src/lib/uiMap.ts`, resolved in the three interface languages into `apps/vision/agent/ui_map.json` by `npm run ui-map`) lists every page with its route, purpose, required feature, tabs and main buttons. Each page is a section of the help index, so "where do I set up the Modbus server" finds the page in whichever language it was asked, and the reference link opens the page itself rather than a document; the same map is given to the LLM in its system prompt so it names pages and buttons exactly as the interface shows them. A vitest keeps the map complete (every route in `App.tsx`) and the JSON current.

The eye icon in the assistant header turns sharing off: the assistant then only knows the page kind. The preference is kept in the browser (`vs.assistant.share`); nothing from the trail is stored on the server.

### Live lookups and shortcuts {#lookups}

With an LLM provider that supports tool calling (Claude, OpenAI, Gemini, OpenAI-compatible), a help question is not answered from the documentation alone: the model may first call **read-only lookups** (`agent/lookup.py`) and then answer from what it saw. Up to four rounds; after that it is told to answer with what it has. Every lookup is checked against the caller's role (`Principal.can`), so an operator asking about connections gets "not permitted" and the reply says which role can see them. Lookups never run a flow or change anything, strip secrets from configurations and cap their size. `VISION_AGENT_HELP_LOOKUPS=0` turns them off (documentation-only answers); when the provider cannot call tools or the call fails, the assistant falls back to the single-shot answer and says so in a warning.

| Lookup | Returns | Needs |
|---|---|---|
| `list_flows`, `get_flow` | Flows with version, steps (id, type, label, scalar params), recipes, statistics, continuous state and the last runs | signed in |
| `get_run` | One run by id: status, error, outputs and every node's status and message (memory first, then the stored history) | `flows.run` |
| `list_sources`, `capture_clients` | Image sources with live status; connected capture clients and channels | `sources` |
| `list_connections` | Integration connections with live status and start errors, and the integration page they belong to | `connections` |
| `list_plugins` | What each plugin file mounted, disabled ones and load errors | `integration` |
| `engine_status`, `my_permissions` | Version, station, engine lock, worker pool; the caller's role, allowed features and the role matrix | signed in |
| `search_docs`, `get_tool` | Documentation and interface-map search; a tool's full skill text | signed in |

The reply lists what was checked ("Checked: list_connections, engine_status"), and the model may end with one `ACTIONS:` line that becomes **shortcut chips** under the answer: go to a page (and open a tab: `{"kind":"navigate","to":"/integration/modbus-server","tab":"connections"}`), focus a step in the flow editor, or open a step's tool page. The server validates every action against the interface map (unknown routes and tabs are dropped; step actions need the flow and, when the graph was sent, an existing node id) before the front end shows it. Offline, a "where is…" question whose best hit is an interface page gets a "go there" chip from the rules. `POST /agent/chat` returns them as `actions[]` and `lookups[]`.

### Proactive hints and the screen text {#hints}

The assistant also speaks first when something recognisable fails. `lib/hints.ts` watches the activity trail with a small rule table: engine locked (423), a role that is not allowed (403), a receiver that is not listening, a capture step without a source, a port already in use, a failed run or preview, a run that timed out, a server error. A matching event shows a hint card at the top of the assistant panel (and counts as unread while the panel is closed) with a one-line explanation and an "Ask the assistant" button that sends the error, with the full situation, as a question; "Dismiss" hides that kind of hint for the session, and the same kind is shown at most once every five minutes. The rules run in the browser only, so nothing is sent until the user asks.

The monitor icon in the header attaches a **text summary of the screen** to the following questions (`screenSummary()` in `lib/screen.ts`): headings, alerts and banners, the active tab, the first rows of visible tables, form fields with their values, and button names. Password, hidden and file fields are never read, the sidebar and the assistant panel are skipped, and the summary is capped at 3,000 characters. It is off by default, needs sharing to be on, and is meant for "what is this page showing me" questions. There is no screenshot: the text form works with every provider and costs a fraction of an image.

### Screenshots {#screenshot}

The camera icon captures the current page as a JPEG (`lib/screenshot.ts`, DOM rendered through `html-to-image`, so it works over plain HTTP on a LAN and does not open a system picker; longest side 1,600 px, quality 0.8, the assistant panel and toasts left out) and pins it as a thumbnail under the conversation. It is sent once, with the next question, as `context.screenshot`, then cleared. The server accepts JPEG only, at most 4 MB of base64, and hands it to the LLM as an image together with the text (the tool-calling loop gets it in the first turn too); the prompt says a screenshot is attached and asks the model to read what is visible rather than guess. The button is disabled without an LLM provider or while sharing is off; the offline rule engine cannot see images and says so in a warning. Nothing is stored on the server.

### Long-term memory {#user-memory}

Each signed-in user has a private memory (`AssistantMemory`, `agent/notes.py`); administrators cannot read another user's memory and deleting the account deletes it.

| What | How it gets in | How it is used |
|---|---|---|
| **Facts**: things the user wants remembered ("line 3 uses flow Inspect A", "I look after the B line") | Type `remember: …` (or 記住：…) in the assistant, or add them in the Memory panel (brain icon); `forget: …` removes every fact containing the text. At most 50, oldest dropped | Listed in the LLM prompt under "Things the user asked you to remember" and treated as true for that user |
| **Rated answers**: every help exchange is kept (question, answer, page) | Thumbs up / down under an answer; the Memory panel lists recent questions with their rating. At most 200, oldest unrated dropped | For a similar question (token Jaccard ≥ 0.35), answers rated up are shown to the LLM as "previously helpful answers"; offline, a nearly identical question (≥ 0.6) returns the rated answer directly, marked `provider: memory` |

Site-wide and personal supplements to the platform skill (`AgentSkill`, Settings › AI skills) now also go into the help prompt, so a station's conventions written there reach the help answers as well as flow generation.

### Tuning from a batch of images {#tune}

The [batch page](batch.md) offers three capabilities through the global assistant (bottom-right, context = batch page) and the tuning panel, all working from the stored per-image data: **consultation** (`POST /agent/consult`: rule-based insights plus an LLM answer, with applicable parameter suggestions), **tuning** (`/agent/tune`, or agentic `/agent/jobs` with a `batch_run_id`, landing as a new run) and **auto-tuning** (`POST /batch/sets/{id}/runs {mode:"autotune"}`). The older interface, which takes image cache refs, still works:

After running a batch, "Ask the AI to tune from these results" below the results table takes a prompt ("the NG ones are actually good, it is too sensitive", "make it 4"). The assistant sees each image's verdict and outputs — in LLM mode a few thumbnails too — adjusts the flow and **re-runs the same images**, reporting the OK, NG and failed counts before and after with the per-image changes. "Apply to canvas" when you are happy.

```
POST /api/vision/agent/tune  {graph, instruction, runs:[{name, image_ref, status, outputs}]}
→ {graph, rationale, changes, before:{ok,ng,failed}, after:{…}, items:[{name, before, after}], applied}
```

### Camera, lens and lighting advice {#imaging}

"Which camera and lens for a 120 mm field of view and a 0.2 mm defect?", "how should I light a scratch on a dark surface?", "will GigE keep up at 20 fps?" — the assistant answers these from a skill of its own (`agent/skills/imaging.md`: choosing order, cameras, lenses, interfaces, lighting techniques and worked situations), which is in the help index like every other section, so the answer cites it.

**The arithmetic is not guessed.** A read-only lookup, `camera_optics` (`agent/optics.py`), computes the focal length from field of view, working distance and sensor format (and names the nearest stock lens plus the field of view it actually gives), the sensor pixels needed for a feature at 3 px for detection, 10 for measurement or 20 for reading, mm per pixel, depth of field, the exposure that keeps motion blur under a pixel at a given belt speed, and the bandwidth with the interfaces that carry it. It needs no permissions beyond being signed in, and the reply lists it under "checked".

### Reference pictures travel with the flow {#pictures}

When a design needs a reference picture — the template for `template_match`, the golden sample for `defect_diff`, the white reference for `shading_correct` — the assistant crops it out of the picture you uploaded and puts it in a **Fixed image** step (role "reference") wired into that tool's picture input, instead of creating an asset. The picture is stored with the flow and travels with an export, so nothing accumulates in the asset library and the flow runs as-is on another station. In agentic mode this is the `crop_template` action, which takes the `target` node and the port to wire into.

## Part 2 · Generating a flow on the assistant page {#generate}

The AI assistant page in the sidebar turns an image, a few ROIs and a sentence into a runnable flow. This part covers the questions it asks first, several images and numbered ROIs, candidates and auto-tuning, locate correction, refinement in words, agentic mode, the session memory and the provider settings.

### Asking before generating {#clarify}

Pressing "Generate" does not go straight to work: it first calls `POST /agent/clarify` to decide whether it has enough to go on, and if not asks **at most three** key questions (a choice, a number, some text, or "please mark another ROI"). After you answer it checks again, possibly asking another round, and only generates once it is ready. "Skip the questions and generate" is always available, and then the result card lists what was not provided and what default was used.

| Situation | What it asks |
|---|---|
| A vague prompt ("have a look", "check it") | What should be inspected? (count, diameter, width, angle, defect, colour, presence, code, brightness) |
| Counting, but no number given | How many are expected? (skippable — it will just report). With no ROI: the whole image or a particular area? With similar numbers of dark and bright particles: is the target darker or brighter than the background? |
| A diameter, with no circular ROI and no circle detected | Please mark an annulus on the hole edge. Millimetres requested with no pixel size: how many millimetres per pixel? |
| A width or an angle | The missing ROI, or the ROI for the second edge; the nominal and the tolerance (skippable) |
| A surface defect | Is there a good part to compare against? (if so, it uses golden comparison) |
| A colour judgement with no ROI | Please mark the area to judge (the target colour is taken from it) |

Answers are folded back into the prompt as extra sentences ("expect 5", "the target is darker than the background", "nominal 17.5 ± 0.4 mm"), and both the rule engine and the LLM read the same text. In LLM mode the model decides for itself whether and what to ask, following the "be careful" principle in `skills/design.md`, falling back to the rule-based questions if its output does not fit the format.

**Interrupting**: while the assistant is checking or generating, the button becomes "Stop". The global assistant (editor edits, batch consultation and tuning) has the same stop button — the front end cancels the request and the server applies nothing from that call once it finishes.

### Several images, and numbered ROIs {#multi}

You can upload several images at once (a thumbnail strip switches between them) and mark ROIs on each. ROIs are numbered in the order you add them — `ROI01`, `ROI02`… — each can carry a hint, and the prompt can refer to the numbers:

```
ROI01 is a good part and ROI02 is a bad one; find the difference
```

That triggers the golden comparison intent: the good ROI is cropped into a template asset (in the asset group "AI assistant"), the inspection window is placed at the bad ROI's position at the template's size, and a `defect_diff` flow is generated. **Every image is then actually run**, each thumbnail is marked OK or NG in the corner, and switching image shows that image's overlays and outputs.

### Candidates, image labels and auto-tuning {#candidates}

The rule engine no longer produces just one flow: every intent yields a main solution plus one or two parameter variants — an adaptive threshold or strict particles for counting, conservative or sensitive for defects, first-and-last or strongest edge pairs for a caliper, conservative or ECC-aligned for golden comparison. All candidates are run silently on every uploaded image (releasing their node images immediately, so the cache is untouched) and scored against the **image labels** (+10 for a hit, −5 for a node in error, −3 for a failure). Only the winner is run for real and keeps its overlays. The response's `candidates[]` lists each one's verdicts and score, and the assistant page can switch between them (`POST /agent/run` re-runs the same images).

**Image labels**: the bottom-right corner of each thumbnail on the assistant page marks what that image should be judged as (`GenerateIn.labels`), and an image whose ROI hint says "good" or "bad" is labelled automatically. With two or more labels, and a winner that has not hit all of them, generation runs a **small-budget auto-tune** (24 evaluations, 10 seconds) and adopts it only if it improves, noting so in the reasoning.

**Auto-tuning** (`apps/vision/agent/autotune.py`) is coordinate descent: walk the `teach=True` parameters in the graph, with candidate values a geometric ladder around the current one (nearest first: ×0.7, ×1.4, ×0.5, ×2, ×0.25, ×4, ×0.1, ×10, clamped to the minimum and maximum; ±0.1 and ±0.2 for 0–1 parameters; every option of a select; the opposite of a boolean), compared on the labelled images by (hits, −errors, −failures). **Only a strict improvement is adopted** — a tie keeps the current value and small changes are tried first, which resists overfitting — and it stops when everything hits or the budget runs out. Specification parameters are never touched: tolerance judges, range checks, the expected count in a number check, pixel calibration, code reading and locate correction. Three entry points:

- Assistant generation (the small budget above).
- Batch testing: each row in the results table takes an expected OK or NG, and "Auto-tune" calls `POST /agent/autotune` (`runs[].expected`), returning the same before/after comparison as "ask the AI to tune" for applying to the canvas. A tuning instruction containing "auto-tune" takes the same path, as does an offline instruction with two or more expectations set.
- The Golden Set page: "Auto-tune" calls `POST /flows/{id}/golden/autotune`, using the cases' expected statuses and outputs. It does not write back to the flow; "Send to editor" turns the result into a draft.

### Locate correction, and the newer intents {#locate}

When the prompt mentions the position moving, locating, displacement or following — or an ROI's hint says "locator" (marker or fiducial also work) — that ROI does not take part in the inspection. It is cropped into a **locating template** and the flow gets the three-part locate correction wrapped around the front (`synth.wrap_with_locate`): template match → locate correction → ROI follow. The template's search area is the locator ROI expanded 1.5×, the reference position is its centre, and every inspection node with a fixed ROI gets its own `fixture_roi` (the ROI input port takes priority over the canvas parameter). Failing to find the template goes NG (locate_failed). With no ROI marked as a locator, the clarify step asks for one on a feature that does not move.

When no closed intent matches, the rule engine compares the prompt with the template gallery (names, descriptions and the tools each template uses) and, given enough overlapping words, applies that template with the uploaded picture as its source (`template` intent) — so every gallery flow is reachable offline by describing it. Two more intents were added on 2026-09-10: `focus` (is the picture in focus — `sharpness` scored against half of the current picture's score, triggered by "focus", "blur", "sharp") and `roundness` (`find_circle` edge points into `gdt_measure` minimum-zone roundness with the tolerance from the prompt, triggered by "roundness", "out of round"). Three later intents: `text` (is anything printed — `text_presence` stroke density, triggered by "printing", "text", "serial number"), `distance` (the distance between two hole centres — two circle finds → `distance` → calibration and tolerance, triggered by "distance", "hole spacing", "centre distance" with holes or circles, or two circular ROIs) and `template_presence` (is a pattern there — the ROI becomes a template and `template_match` branches found or not_found, triggered by "pattern", "template", "logo"). Each has its own clarify question: which area carries the printing, where the second hole is, which pattern to look for.

### Iterative refinement {#refine}

Every result comes with its reasoning and the run report. Type plain language into the feedback box:

| Feedback | What the rule engine changes |
|---|---|
| too sensitive / false rejects / catching too much | blob minimum area ×2, colour tolerance +40%, match score threshold −0.1 |
| missing them / not finding it / too loose | blob minimum area ×0.5, edge threshold ×0.6, colour tolerance −30% |
| make it 4 | The count check's expected value becomes 4 |
| ±0.2 | The tolerance judge becomes ±0.2 |
| (no parameter matches) | The feedback is folded into the request and it regenerates |

In LLM mode, refinement hands the current graph and the feedback to the model. Every refinement re-runs for real.

### Agentic mode: try, edit, verify, repeat {#agentic}

Setting the working mode to "agentic" in the provider settings (or `VISION_AGENT_MODE=agentic`) routes assistant generation, global-assistant flow edits and tuning from data through a **background job** (`POST /agent/jobs`, 202). The interface polls `GET /agent/jobs/{id}?step_from=` once a second and shows a **step timeline** — the turn and trial counts, and each action's summary and duration — which can be cancelled at any time. When the assistant asks something, the job enters "waiting for an answer" and continues after `POST /agent/jobs/{id}/answer`. With no LLM provider a job can still be created; it completes immediately through the rule engine and says so in warnings. With the working mode still "single generation", a background job also takes the single-pass path rather than entering the loop.

**The action layer** (`apps/vision/agent/actions.py`) is what the LLM can call: `get_state` (the request, ROIs, features, labels and the current flow), `list_tools` and `get_tool_skill`, `analyze_region`, `draft_from_rules` (a rule-engine draft, usually the starting point), `use_candidate`, `replace_graph`, `patch_graph` (set_param, set_params, enable, disable, remove_node, add_node, add_edge, remove_edge, set_label — applied as a batch and then validated), `run_trial` (each image's status, named outputs, node messages and label hits), `inspect_node`, `crop_template`, `auto_tune`, `ask_user` (three questions at most) and `finish`. Every graph change goes through `validate_graph`; dl_* steps are refused, write_modbus and save_image can only be added through an approved action (see [Actions that need your approval](#approval)), and a flow must have exactly one acquisition step. Trials use `trial_run(keep_images=False)` so the image cache is untouched.

**The loop** (`loop.py`): a budget of `Budget(max_turns=12, max_trials=8, max_tool_calls=30, deadline_s=240)`, with cancellation checked every turn, and a status of `done｜needs_input｜budget｜cancelled｜error`. If the budget runs out with a flow in hand, that flow is the result (noted in warnings). If the model replies with text and calls nothing: with a flow already, that counts as finished and the text is the explanation; with no flow, it is reminded once before the job fails.

**The provider shim** (`providers.complete_tools`) converts a neutral history — user text and images, assistant text and tool calls, tool results — into Claude tools (`tool_use` and `tool_result`, with consecutive results merged into one user message), OpenAI functions (`tool_calls` and `role=tool`), or Gemini `functionDeclarations` and `functionResponse` (the schema converted to the OpenAPI subset; Gemini 3's `functionCall` carries a `thoughtSignature`, and the native parts are kept and returned verbatim in the history, or the next call is a 400). OpenAI-compatible local endpoints use the functions format; where it is not supported the agentic loop fails, falls back to single-pass JSON generation, and then to the rule engine. `tool_choice` is always auto. The system prompt is the platform rules, the design principles, `skills/agentic.md` (how to work as an agent) and the condensed catalogue — stable and cacheable — and the first message carries up to four images and the relevant tool skills.

Cost and latency: trial results come back as concise text with no images, action results are capped at 12k characters, and the budget is conservative. A long job never occupies the inspection thread pool (it runs on a background thread), and one process runs at most three jobs at once.

### Working with the image window {#viewer-protocol}

In agentic mode the assistant can hand the mouse to you instead of guessing coordinates. Three question kinds are answered on the image rather than in text: **Draw a region** (the assistant needs a search area; when it names the step and parameter, the platform writes the region straight into that parameter), **Crop a reference picture** (frame the locator mark or the good part; the platform crops it into a fixed image and connects it to the named step), and **Check a preview** (look at a step's output before the assistant goes on). The card appears in the assistant panel; **Draw on the image** switches the current page's image viewer into drawing mode, **Use this region** hands the region back, and **Send** delivers it. Drawing works on the flow editor and on the AI assistant page; on other pages the card says where to go.

### Saving the result as a composite tool {#save-tool}

On the assistant page the result card offers **Encapsulate as a composite tool** (on by default when you may edit the tool library). Saving then creates one composite tool from the inspection steps (its on-site parameters and regions are the tool's parameters) and a flow that contains the image source and one instance of that tool, and opens the flow. The tool appears in the tool library and the tool picker, so the next flow can reuse it. Untick the box to save the steps as an ordinary flow instead.

### Without an AI provider {#offline-toolbox}

When no provider is configured the assistant runs its offline rule engine and says so: generation, flow edits and task lists from a conversation still work within the rules, and every such reply carries an **Open the Inspection tasks tools** shortcut. In the flow editor it opens the tool picker on the Inspection tasks category, elsewhere it opens the tool library. The assistant page shows the same note above the steps.

### Actions that need your approval {#approval}

In agentic mode the assistant can act on the platform within **your** permissions: select an image source, asset or calibration, build, update or remove inspection tasks, connect a source, run a trial, auto-tune (on the tuning images only) and run a batch. Every action checks your permissions again, respects the engine lock, and reports succeeded, not executed or uncertain together with its evidence — a timeout is uncertain and is never reported as a success.

Some actions change production state and always stop for you: writing an output to a device, saving to a shared folder, enabling result reporting, unlocking the engine, deleting a flow or an asset, and saving the draft as a flow version. The job pauses and the panel shows an **Action approval** card with the action, what it will change and the risk. Only **Approve** on that card runs it; **Reject** leaves everything untouched, and the model saying "approved" in text does not count. Changing an engineering specification (a wider tolerance, a different unit) also asks first. A version save that meets a newer version saved by someone else is not executed — the assistant shows the difference and asks; it never overwrites. Before it can finish, the assistant must have run a trial on the current flow, and if the flow changed after that trial it has to run again.

### Memory: sessions, priors and custom skills {#memory}

**Sessions (AgentSession)**: every generation, single-pass or agentic, is stored — the image files (`ASSET_DIR/agent/<id>/`), the ROIs, the request and the questions and answers, the image labels, the feature vector, the resulting graph, reasoning and candidate summary, each image's verdict, and the provider and mode. `success` means every label was hit (null when there are no labels), the result card's thumbs up or down sets `rating` to ±1, and saving as a flow links the `flow_id`. "History" on the assistant page lists them, **restores** one (the images go back into the cache, the ROIs, request and labels come back, and the flow re-runs on the original images) and deletes them. API: `GET /agent/sessions[/{id}]`, `PATCH /agent/sessions/{id}` (rating, success, note, flow_id), `POST /agent/sessions/{id}/restore` and `DELETE`. An ordinary user sees only their own; an administrator or integrator sees all. Storing is best-effort: a failure is logged and does not affect generation.

**Priors from similar cases (memory.find_similar)**: the feature vector is the first ROI's (or the whole image's) mean grey, σ, robust σ, edge density, dark fraction, dominant HSV and log area. The nearest two sessions with the same intent that succeeded or were thumbed up (thumbed down excluded) within a Euclidean distance of 0.35 become priors, used in three places: the rule engine applies a successful flow's teaching parameters to the new draft as a candidate called "reuse what worked before" (ranked first, with the original main solution second, and the label ranking able to overrule it); auto-tuning puts the prior values at the front of the candidate ladder; and the LLM's or agent's user message gains a "past successful cases" section (the request, the flow's nodes, the key parameters and the reasoning). The response's `similar[]` lists which cases were referenced.

**Custom skills (AgentSkill)**: under each skill in the "AI skills" window — platform rules, design principles, agentic working, and each tool — you can write **supplementary notes**. A personal note affects only you; a site note (administrator) affects everyone. Site notes join the cacheable system section (`skills.build_system(epoch)`, rebuilt only when saving calls `skills.invalidate()` and the epoch changes); personal notes go into the user message (`focus_text(keys, user)`: the full tool skill including the supplement, plus "personal notes" sections for the platform rules, design principles and agentic working). API: `GET /agent/skills/custom`, `PUT /agent/skills/custom/{key}` (`{markdown, scope}`, 20000 characters at most), `DELETE /agent/skills/custom/{key}?scope=`; `GET /agent/skills/{key}` returns the merged text and the raw supplement.

### Providers and keys (stored per person) {#providers}

"AI provider" in the top right of the assistant page selects the **offline rule engine, Claude, GPT or Gemini** and takes your own API key and model name (blank uses the default). The settings belong to your account (`UserPref.agent`): nobody else can see them, and they do not come back with `/auth/me` — the API returns only "configured" plus the last four characters.

| Provider | Implementation | Default model |
|---|---|---|
| offline | The rule engine (intents plus synth); no external calls at all | — |
| claude | The official `anthropic` SDK (optional, imported lazily) | claude-opus-5 |
| openai | REST `/v1/chat/completions` over urllib, no dependency | gpt-4o |
| gemini | REST `generateContent` over urllib, no dependency | gemini-3.6-flash (2.0 and 2.5 flash have been retired; the "-latest" aliases return 503 at peak times) |
| openai_compatible | Any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio): set the base URL, and the key may be empty — for a local vision model where the plant has no internet access | Whatever the endpoint offers ("List models" queries it) |

Resolution order: the user's own settings (explicitly choosing offline counts) → the server's `.env` (`VISION_AGENT_PROVIDER`, `VISION_AGENT_API_KEY`, `VISION_AGENT_MODEL`, `VISION_AGENT_BASE_URL`, `VISION_AGENT_TIMEOUT_S`) → offline. OpenAI, compatible endpoints and Gemini are asked for JSON output; OpenAI reasoning models (the o series and gpt-5) automatically switch to `max_completion_tokens`. When an LLM call fails and the rule engine takes over, the reason appears in the result's warnings. An integrator (an API key) has no user, so the server settings apply. A failed LLM call — a bad key, a timeout, invalid output — always falls back to the rule engine, so nothing stops working.

## Part 3 · Under the hood {#internals}

How it is built: the architecture, the offline rule engine, the optional LLM path, the skills the assistant reads, the API, the benchmark that guards the rule engine, and the design trade-offs.

### Architecture {#arch}

What the assistant produces is **an ordinary graph JSON**: it runs on the existing dataflow engine, opens in the editor, takes any image source, and can be bound to a recipe and triggered over TCP or HTTP. The assistant is only "a layer that writes flows"; there is no second execution path.

```
the user's images + ROIs + prompt
        │
        ▼
  analysis.py ── ROI features (histogram/Otsu, edge density, dominant colour, circle probe, particle statistics)
        │
        ▼
  ┌─ generation (one of two, switched automatically) ──────┐
  │  llm.py     with an API key → the provider generates   │
  │  intents.py + synth.py    otherwise → the rule engine  │
  └────────────────────────────────────────────────────────┘
        │  a graph (always checked by validate_graph)
        ▼
  service.trial_run ── actually run on the uploaded images (engine.execute; nothing
                       written to the database, no flow thread pool used)
        │
        ▼
  {graph, rationale, report}  ← the interface shows the overlays, outputs and OK/NG,
                                ready to refine or save as a flow
```

| Module | Responsibility |
|---|---|
| `apps/vision/agent/analysis.py` | The ROI feature pack: mean, standard deviation and Otsu; the dark fraction; edge density; the dominant HSV colour; dark and bright particle statistics from connected components; a Hough circle probe. The rule engine tunes from it, and the LLM gets its text summary to save tokens. |
| `intents.py` | The prompt (English and Chinese keywords), the ROI shapes and the features become an intent from a closed set — count, diameter, width, angle, defect, color_match, color_presence, presence, brightness, barcode, text, distance, template_presence, generic — and it extracts the expected count, nominal, tolerance and mm-per-pixel. |
| `synth.py` | One synthesiser per intent: attach the user's ROIs, fill parameters from the features (threshold polarity, blob minimum area, HSV range, an automatically derived annulus…) and emit the graph plus the reasoning. |
| `providers.py` | The providers: offline, claude (the anthropic SDK), openai and gemini (REST); settings resolution (user → server → offline) and key masking. |
| `skills.py` and `skills/*.md` | Loading and assembling the platform rules, design principles and per-tool notes; relevance selection; the skills API. |
| `llm.py` | Four tasks (generate, refine, edit, tune) sharing one system prompt (tool catalogue, graph specification and rules — cacheable). Thumbnails, ROI numbers and the feature summary go in the user message; the JSON output goes through validate_graph, retrying once with the error attached. |
| `service.py` | Orchestration and trial runs (each image once); rule-based refinement, instruction parsing (edit_rules) and batch tuning. A failed LLM falls back to the rule engine. |
| `api.py` | The `/vision/agent/*` endpoints, with execute permissions (423 while locked). |

### The offline rule engine {#rules}

The default mode, **completely offline** with no external dependency. Intents are matched by specificity (explicit words such as "read the code" or "angle" first, the generic "is it there" last) and every parameter is derived from the ROI features:

| Prompt (example) | Intent | The flow it builds | Automatic parameters |
|---|---|---|---|
| there should be 5 holes | count | grayscale → denoise → threshold → open → blob → count check → OK/NG | Threshold polarity (which side has more particles), blob minimum area (median area × 0.3) |
| measure the diameter, 17.5 ± 0.4 mm, 0.05 mm per pixel | diameter | find circle → diameter → pixel calibration → tolerance judge | A circular ROI becomes an annulus (r × 0.6–1.4), the mm/px scale, the tolerance |
| measure the width, 160 ± 10 | width | caliper → tolerance judge | — |
| the angle between the two edges, 90 ± 1 | angle | find line ×2 → angle → range check (needs two ROIs) | — |
| any scratches on the surface? | defect | blur → fixed threshold → open → blob → OK only at zero | The threshold is the ROI mean shifted 3σ darker or brighter (the polarity comes from the particle probe) |
| is this colour right? | color_match | colour comparison → OK/NG plus colour statistics | The target colour is the ROI's dominant colour |
| is the red plug present? | color_presence | colour range mask → pixel count → threshold | The HSV range is the dominant hue ±12°, the threshold a quarter of the ROI area |
| read the barcode | barcode | read code → OK/NG plus the content as an output | — |
| is the brightness normal? | brightness | region statistics → range check | The range is the current mean ±30% |
| (unclear) | generic | An informational flow: statistics, histogram, edge density | A note asks for more detail |

### LLM generation (optional) {#llm}

Set `VISION_AGENT_API_KEY` in `.env` (and `pip install anthropic` for Claude) and generation is done by the model instead. An LLM understands freer descriptions ("measure the inner and outer rim of the cup mouth, and the wall thickness too") and can put together flow shapes the rule engine does not have.

- **The checks do not change**: an LLM's graph still goes through `validate_graph` and a real run. Invalid output is retried once with the error, and after that the rule engine takes over.
- **Keys stay on the server**: the front end only ever calls its own backend, and the key never reaches the browser. Saving the settings immediately makes a minimal request to verify them (`POST /agent/settings/test`), showing the model and the latency on success or the reason on failure. **List models** and **Test connection** take the provider, key and endpoint currently on screen, so a provider can be tried before it is saved; switching provider without entering that provider's key reports a missing key rather than a puzzling rejection. Every failure carries a `reason_code` (`no_key`, `bad_key`, `bad_model`, `no_credit`, `rate_limit`, `overloaded`, `timeout`, `network`…) which the interface turns into a sentence in its own language, with the provider's own words underneath — an exhausted balance and a rate limit are both HTTP 429 but need different actions.
- **Where the data goes**: with an LLM enabled, downscaled images plus the ROIs and the feature summary are sent to the provider. In a closed or confidential environment, do not set a key — the rule engine is fully functional on its own.
- **Cost**: the tool catalogue and the specification sit in the cacheable system section (prompt caching), so refinement only pays for the increment.

### The assistant's skills {#skills}

What lets an LLM design a flow "the platform's way" is that it reads three documents in `apps/vision/agent/skills/` every time. They are both the prompt the AI reads and documentation people can read (browse them under "AI skills" on the assistant page, or `GET /api/vision/agent/skills`):

| File | Contents | Where it goes |
|---|---|---|
| `platform.md` | Platform rules: the graph format, ports and the `_flow` control branch, ROI coordinates and shapes, how a flow must end (judge, output, not_found), bit depth, what is forbidden, notes, layout | system (stable, cacheable) |
| `design.md` | Design principles: the standard skeleton, a table of which tool for which need, auto-tuning practice, several images and good/bad parts, common mistakes | system (stable, cacheable) |
| `tools.md` | Human-written notes for each tool (in `## <type>` sections): when to use it, how to wire it, how to tune it, what to watch out for. The platform appends that tool's parameter table (with ranges, options, units and descriptions), its ports and its accepted bit depths to make the complete skill | Selected by relevance into the user message |

Relevance selection (`skills.select_tools`): the core tools always come along (image_source, grayscale, threshold, blob, if_number, in_range, judge, output, draw_result, note), plus keyword matches from the prompt ("diameter" → find_circle, calibration, tolerance_judge…), the intent the rule engine parsed, the shapes of the ROIs drawn (a line → wall_thickness, line_profile) and whatever the existing graph already uses — 18 at most. The rest appear as one-line entries in the system catalogue, so the LLM knows they exist.

That way the system section is completely stable (so prompt caching hits) while the tools that actually matter this time arrive with their full parameters and notes. To teach the assistant about your own site — the parameters your plant favours, how a particular part is wired up — edit these markdown files; no code changes.

### API {#api}

Memory (own items only): `GET /agent/memory` lists facts and recent questions with limits; `POST /agent/memory {text}` adds a fact; `POST /agent/memory/{id}/rate {rating}` sets 1 / 0 / -1; `DELETE /agent/memory/{id}`. A help reply from `POST /agent/chat` carries `memory_id` for rating, and the context may carry `screenshot` (JPEG base64 or data URL).

```
GET   /api/vision/agent/info       the provider in effect (without the key) and the available choices
GET   /api/vision/agent/settings   your own provider settings (the key comes back masked)
PATCH /api/vision/agent/settings   {provider, model?, api_key?, clear_key?}
POST  /api/vision/agent/image      multipart image → {ref, width, height}
POST  /api/vision/agent/clarify    {images, prompt, regions, answers?} → {ready, questions[], summary, intent}
POST  /api/vision/agent/generate   {images:[ref], prompt, regions:[{region, hint?, image?}], use_llm?, answers?, labels?:["ok"|"ng"|""]}
                                   → {graph, rationale, provider, intent, report, reports, main_image, candidates[], labels, warnings?, autotune?}
POST  /api/vision/agent/run        {images, graph, main?} → {graph, report, reports, main_image}  (switching candidate)
POST  /api/vision/agent/autotune   {graph, runs:[{name, image_ref, status, expected}], max_evals?, deadline_s?} → as tune, plus an autotune summary
POST  /api/vision/flows/{id}/golden/autotune  {graph?, max_evals?, deadline_s?} → {graph, before, after, change_text[], improved, budget_hit, cases}
POST  /api/vision/agent/refine     {images, prompt, regions, graph, feedback} → as above
POST  /api/vision/agent/edit       {graph, instruction, image_ref?} → {graph, rationale, changes, report?, applied}
POST  /api/vision/agent/tune       {graph, instruction, runs} → the before/after comparison above
POST  /api/vision/agent/chat       the global assistant: {message, mode?, context{kind, route, flow_id, flow_name, node_id, node_type,
                                   batch_run_id, image_ref, graph}, history[]}
                                   → {kind: help|edit|consult|tune, answer, provider, sources[]?, result?, suggestions?, warnings?,
                                      batch_run_id?, agentic?}
GET   /api/vision/agent/help/search?q=&k=  search the help index → {items[{title, page, heading, url, score, snippet}], sections, pages, tools}
```

`report` has the same shape as the preview endpoint's (per-node status, outputs, overlays and image refs). A region is an ordinary ROI dict (rect, rotated_rect, circle, annulus, polygon, line — in full-image pixel coordinates). The executing endpoints return 423 while the engine is locked, and are open to ordinary users.

### The benchmark {#bench}

`manage.py agent_bench` runs the cases in `apps/vision/agent/bench.py` (a synthetic sample image, ROIs, a prompt, the expected intent and the expected verdict for each image) through the offline rule engine and prints the intent accuracy, the verdict accuracy per case and per image, the proportion of valid graphs and the timings. `--llm` uses the server's provider instead, `--keys` runs only named cases and `--json` prints everything. `tests/test_agent_bench.py` holds the line with thresholds (currently intent ≥ 0.9, verdict ≥ 0.8, all graphs valid), and every capability added is measured with the same ruler. A case can carry `labels` to cover the candidate ranking and auto-tuning paths; five cases were added for printing, centre distance, patterns, locate-plus-caliper and counting with labels, for 21 in all.

**Measured LLM mode** (`--llm`, gemini-3.5-flash-lite, single-pass, September 2026): intent 100%, verdict 76%, valid 81%, about seven seconds per case. Three kinds of failure. Caught by validation (a port type mismatch, an edge to a node that does not exist) → already falls back to the rules with a warning. Passing validation but failing every trial run (an invented template asset id, contours wired into the result image's overlay port) → `service.generate` now switches to the rule engine when every trial fails and says why, and `draw_result` skips inputs that are not overlays. And plain misjudgement (a colour presence threshold that is too loose) → that is model capability, and the answer is image labels plus auto-tuning. The rule engine scores 100% on the same cases, so a single LLM generation is best treated as a starting point; agentic mode, or labels plus auto-tuning, is what gets the verdicts right.

### Design trade-offs {#design}

- **The product is a graph, not a black box**: everything the assistant generates opens in the editor and can be inspected tool by tool, so the engineer on the line can read it and change it. The assistant is an opening move, not a replacement for the editor.
- **The rule engine is the floor, the LLM is the ceiling**: the rule engine covers the great majority of ordinary factory inspections and is completely offline; the LLM is an optional upgrade that makes it smarter the moment a key is added, and nothing is missing when the key is taken away.
- **Always verified by running**: whoever generated it, the flow is really run on the user's images before it comes back — "looks reasonable" does not count, OK/NG and overlays do.
- **Deep learning is never generated automatically**: dl_* tools need a trained model first, so the assistant leaves a note pointing at the teaching page when one is called for. write_modbus needs a configured connection, and is likewise never generated.
- **The principles hold**: the graph format does not change, the engine does not change, and there is still one API process. Agent trial runs call engine.execute directly on the caller's thread and never occupy the flow thread pool.
