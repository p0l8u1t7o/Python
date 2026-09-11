# AI 助手：图像、ROI 与一句話產生检测流程

AI 助手（侧栏 `/agent`）讓不熟悉工具鏈的人以三步建立检测：**上传图像 -> 標記要檢查的区域（可有多個 ROI，各自帶提示） -> 用一句話描述需求**。助手會產生一般流程圖，立即在該图像上执行，並把結果畫回图像。若結果不正確，可用自然語言回饋，例如「誤判過多」、「漏檢」、「改成 4」，它會反覆調整。完成后可保存為流程並在编辑器繼續調校。

## Part 1 · 全域助手（每個页面皆有） {#editor}

每個页面右下角的聊天面板可回答文件与介面地圖問題、讀取目前情境、查詢即時状态、编辑目前流程、依批量数据調校，並記住您要求它記住的內容。右下角 **AI assistant** 按鈕存在於 `AssistantDock`，切換页面不會关闭面板。面板标题栏的面板按钮可把它**展开成右侧面板**（页面会让出宽度）或缩回右下角，选择记在这台设备。對話屬於您的帳號，會寫入服务端；历史按鈕可重新开启或删除。

| 情境（页面） | 作用 | 后端 |
|---|---|---|
| 任何页面 | **Help**：依文件回答平台使用問題，並附引用段落連結 | `POST /agent/chat` -> `help.py` |
| 流程编辑器与工具页 | **Edit the flow**：依指令修改目前畫布，含未保存變更；工具页則提供参数建议 | `service.edit` 或 agentic `/agent/jobs` |
| 批量页，且選定完成执行 | **Consult the data** 与 **Tune from the data**：回答数据問題並提供参数建议，或產生新調校执行 | `consult.consult`、`service.tune`、`persist_tune` |

模式 chip 默认 Auto。問題會走 help；编辑指令會改流程；批量页上談到数据、图像、NG、threshold、results 時會走数据諮詢。猜錯時可手動選 Help、Edit flow、Consult data 或 Tune from data。页面以 `useRegisterAssistantContext` 登錄情境，離開時清除。

### 从对话生成检测任务清单 {#tasklist}

在**检测任务**页，助手会把您说的话转成一份任务清单的提案，而不是直接生成流程图。一句话可以同时包含好几项需求——“用十字标记定位工件、允许旋转；外径 35±0.2 mm、内径 26±0.2 mm；缺口超过 2 mm 判不合格”——也可以是修改（“外径公差改成 ±0.1”）或删除。提案以卡片呈现，每项任务一个区块：您说出的值标为已确认，助手推测的值标为**假设**，必填却没人给的值标为缺少。助手从图像推估的候选区域，点**在图像上显示**会以虚线画出；在您应用之前都只是提案。

点击**全部确认**之前什么都不会改变；**舍弃**则丢掉这份提案。还有值缺少、要用毫米却没有标定、或图像来源有歧义时，卡片不会应用，而是先问您。应用走的是与页面表单相同的任务建立程序，结果与手动建立完全一样；之后照常在页面上保存。

### 接着上次的进度 {#resume}

在某条流程上打开的对话会绑定那条流程，并在流程图之外保存工作进度：做过的决策、尚未回答的问题、未确认的假设、哪些样本图用于调参、哪些用于验收，以及上次的试运行结果。之后在这条流程上再打开助手，会出现恢复卡：点继续就载入对话，未回答的问题可以直接在卡片上回答；如果流程在这之后保存过，卡片会说明，并依流程的版本历史列出改了什么。检测规格本身永远从流程读回——对话不会另存一份。列在“工程决策”下的决策可以存成工程笔记草稿。

### 说明回答如何運作 {#help-answering}

第一次查詢時，`agent/help.py` 會把 `docs/*.html` 依 h2/h3 与錨点切成段落，加入各工具 skill text，並建立索引。分詞使用英數詞与 CJK bigram；BM25 以標題命中、用户指南、批量与助手页加權。文件變更時索引會重建。有 LLM 時會把最相關五段与近期對話送到 provider，系统提示要求只從段落回答、未涵蓋時明說、少於 300 字並列出使用段落。離线或 LLM 失敗時，回傳摘要与連結，並在 warnings 说明原因。

| 離线指令 | 效果 |
|---|---|
| set the threshold of "Binarise" to 80 | 依節点標題、id 或工具名找節点，依 key 或 label 找参数 |
| disable / enable "Denoise" | 切換節点 enabled |
| delete "Result image" | 移除節点与边；`image_source` 不可刪 |
| too many false rejects / it is missing them / make it 4 / ±0.2 | 使用 iterative refinement 的同一参数映射 |
| 先找外圆心，内圆心 ROI 再跟着外圆心位移 | 新增 `shape_align`，接第一个节点的中心（`cx`／`cy` 或 `matches`），其 `transform` 接到第二个节点的隐含输入端口 `_transform`；「外／内」对不到节点标题时取 ROI 最大／最小的节点。参考位置由当前图像的试执行教导 |
| 请帮我直接修改画布 | 指令本身没有内容时，沿用对话里上一句需求 |

连接 LLM provider 后没有固定语法；模型会收到当前 graph、工具目录与近期对话，只修改必要部分并保留 node id。不论由谁修改，回复都会列出与当前 graph 的差异（新增或移除的步骤、参数与启用状态的变更、连线数）；没有任何改动的回复不会出现「应用」按钮。

### 助手知道哪些螢幕情境 {#situation}

每個問題除了文件，也帶有目前情境，使回答能對準页面状态：

| 送出的內容 | 来源 | 例子 |
|---|---|---|
| 页面種类、route、介面語言 | `AssistantDock` | `tool page, /flows/3/tools/blob, zh-Hans` |
| 页面快照 | 各页 `describe()` callback 或 DOM snapshot | selected step、dirty、last_run error |
| 活動軌跡 | `lib/activity.ts` 的 in-memory ring buffer | 近期導覽、失敗 request、toast、run result |
| 呼叫者与鎖定 | 服务端 `agent/situation.py` | 角色、功能權限、engine lock |

LLM 被要求先解釋近期错误、指出確切页面/分页/按鈕，且不得建议角色無權执行的動作。**介面語言**控制回答語言，zh-Hans 与 zh-Hans 不混用。`frontend/src/lib/uiMap.ts` 產生的介面地圖列出每页 route、用途、必要功能、tabs 与主要按鈕，並由 vitest 保持完整。

### 即時查詢与捷徑 {#lookups}

支持 tool calling 的 LLM provider 可先呼叫唯讀 lookup（`agent/lookup.py`）再回答。最多四輪；之后必須依已取得資訊作答。每個 lookup 都依呼叫者角色檢查權限、遮蔽秘密並限制大小。`VISION_AGENT_HELP_LOOKUPS=0` 可关闭。

| Lookup | 回傳 | 需要 |
|---|---|---|
| `list_flows`, `get_flow` | 流程、版本、步骤、recipe、统计、連續状态与最近执行 | 已登录 |
| `get_run` | 單次执行状态、错误、输出与各節点訊息 | `flows.run` |
| `list_sources`, `capture_clients` | 图像来源状态与采集端/channel | `sources` |
| `list_connections` | 整合連线、即時状态与啟動错误 | `connections` |
| `list_plugins` | 插件加载状态、停用項与載入错误 | `integration` |
| `engine_status`, `my_permissions` | 版本、站台、鎖定、worker pool 与角色矩陣 | 已登录 |
| `search_docs`, `get_tool` | 文件/介面地圖搜尋与工具完整 skill text | 已登录 |

回答會列出 checked 項目，並可用一行 `ACTIONS:` 產生捷徑 chip，例如前往页面、开启分页、聚焦流程步骤或开启工具页。

### 主動提示与畫面文字 {#hints}

`lib/hints.ts` 監看活動軌跡，針對引擎鎖定、角色無權、receiver 未監聽、来源未设置、port 佔用、run/preview 失敗、逾時与服务端错误显示提示卡。提示卡在助手面板頂部，面板关闭時算未讀；「Ask the assistant」會把错误与完整情境送出，「Dismiss」在此 session 隱藏同类提示。規則只在瀏覽器执行，用户提問前不送出数据。

螢幕圖示會把**畫面文字摘要**附到下一個問題：標題、警示、作用中分页、可見表格前幾列、表單欄位值与按鈕名稱。密碼、hidden、file 欄位不讀，侧栏与助手面板略過，摘要上限 3,000 字。

### 螢幕截圖 {#screenshot}

相机圖示會擷取目前页面為 JPEG，最長边 1,600 px、品質 0.8，排除助手面板与 toast，並以縮圖釘在對話下方。截圖只隨下一個問題送一次，作為 `context.screenshot`，之后清除。服务端只接受 JPEG、base64 最多 4 MB，並把图像与文字一起交給 LLM。無 LLM provider 或分享关闭時按鈕停用；離线規則引擎看不到图像。

### 長期記憶 {#user-memory}

每位登录用户都有私人記憶（`AssistantMemory`、`agent/notes.py`）；管理員無法讀他人記憶，刪帳號時會一併删除。

| 內容 | 如何進入 | 如何使用 |
|---|---|---|
| **事實**：用户要求記住的事項 | 输入 `remember: ...`，或在 Memory 面板新增；`forget: ...` 移除含該文字的事實 | 列入 LLM prompt 的「用户要求記住的事項」 |
| **評分回答**：每次 help exchange | 回答下方 thumbs up/down；最多 200 筆 | 类似問題時，評為有用的回答會提供給 LLM；離线可直接回傳近似回答 |

站台与個人的 platform skill 補充也會進入 help prompt，使站台慣例影響 help 回答与流程產生。

### 從一批图像調校 {#tune}

[批量页](batch.md) 透過全域助手与調校面板提供三項能力：**consultation**、**tuning** 与 **auto-tuning**。执行批量后，在結果表下方使用「Ask the AI to tune from these results」输入提示，助手會看到每張图像 verdict，調整流程並**重新执行同一批图像**，回報前后 OK、NG、failed 与每張變化。滿意后可套用到畫布。

```text
POST /api/vision/agent/tune  {graph, instruction, runs:[{name, image_ref, status, outputs}]}
-> {graph, rationale, changes, before, after, applied}
```

### 相机、鏡頭与照明建议 {#imaging}

「120 mm 視野和 0.2 mm 缺陷要用哪種相机与鏡頭？」、「暗色表面的刮痕如何打光？」、「GigE 能否支持 20 fps？」這类問題由 `agent/skills/imaging.md` 回答，該 skill 与其他文件一樣在 help index 中，回答會引用它。

算術不靠猜測。唯讀 lookup `camera_optics` 會依視野、工作距離与 sensor format 計算焦距、最近標準鏡頭、特徵所需 sensor pixel、mm/px、景深、在輸送帶速度下保持運動模糊小於一像素的曝光，以及介面頻寬。

### 參考圖片跟著流程走 {#pictures}

設計需要參考圖時，例如 `template_match` 樣板、`defect_diff` golden sample、`shading_correct` 白參考，助手會從您上传的图像裁切並放入 **Fixed image** 步骤（role `"reference"`），再接到工具图像输入，而不是建立资产。圖片隨流程保存与导出，资产庫不會累積一次性檔案。

## Part 2 · 在助手页產生流程 {#generate}

侧栏 AI 助手页把图像、少量 ROI 与一句話變成可执行流程。本部分说明產生前的提問、多張图像与編號 ROI、候選流程与自動調校、定位校正、文字回饋、agentic mode、session memory 与 provider 设置。

### 產生前先詢問 {#clarify}

点击「Generate」后不會立刻開始，而是先呼叫 `POST /agent/clarify` 判斷資訊是否足夠；不足時最多問**三個**關鍵問題，可為選項、數字、文字或要求再標記 ROI。回答后會再檢查，準備好才產生。「Skip the questions and generate」永遠可用，結果卡會列出缺漏資訊与採用的默认。

| 情況 | 會問什麼 |
|---|---|
| 模糊提示 | 要檢查什麼：數量、直徑、寬度、角度、缺陷、顏色、存在、碼、亮度 |
| 計數但未給數量 | 預期幾個；沒有 ROI 時問全圖或特定区域；深淺粒子相近時問目標較暗或較亮 |
| 直徑但無圆形 ROI/圆检测 | 請在孔边標記圆環；若要求毫米但無比例，問每像素幾毫米 |
| 寬度或角度 | 缺少的 ROI、第二边 ROI、名目值与公差 |
| 表面缺陷 | 是否有良品可比較；若有則使用 golden comparison |
| 顏色判斷但無 ROI | 請標記判斷区域，目標色由此擷取 |

答案會折回 prompt，例如「expect 5」、「target is darker」、「nominal 17.5 ± 0.4 mm」，規則引擎与 LLM 讀同一段文字。执行中按鈕會變成 Stop；取消后服务端完成該次呼叫也不會套用結果。

### 多張图像与編號 ROI {#multi}

可一次上传多張图像，縮圖列用來切換，且可在每張图像標 ROI。ROI 依加入順序編號為 `ROI01`、`ROI02`，每個都可帶 hint，prompt 可引用編號。

```text
ROI01 is a good part and ROI02 is a bad one; find the difference
```

此例觸發 golden comparison intent：良品 ROI 被裁切為资产群組「AI assistant」中的樣板，检测窗口放在壞品 ROI 位置並保持樣板尺寸，再產生 `defect_diff` 流程。每張图像都會实际执行，縮圖角落標示 OK 或 NG。

### 候選、图像標籤与自動調校 {#candidates}

規則引擎現在不只產生一個流程；每個 intent 會有主方案与一兩個参数變體。所有候選會在每張上传图像上靜默执行，依**图像標籤**計分，只有勝出者會正式执行並保留疊圖。`candidates[]` 列出各方案 verdict 与分數，助手页可切換候選並由 `POST /agent/run` 重跑。

图像縮圖右下角可標記該圖期望 OK/NG；ROI hint 為 good/bad 時會自動成為標籤。若有兩個以上標籤且勝出者未全命中，generation 會跑小預算 auto-tune（24 次評估、10 秒），只在改善時採用。

**Auto-tuning** 是 coordinate descent：只移動 `teach=True` 参数，依目前值周圍的幾何階梯測候選，並以标注图像比較 hits、errors、failures。只有嚴格改善才採用；平手保留原值，小變更優先以降低過擬合。規格参数不會被動到。

### 定位校正与較新的 intent {#locate}

prompt 提到位置移動、定位、位移或跟隨，或 ROI hint 為 `locator` 時，該 ROI 不參与检测，而是裁切成**定位樣板**，並由 `synth.wrap_with_locate` 在流程前段包上 template match -> locate correction -> ROI follow。搜尋區為 locator ROI 放大 1.5 倍，reference position 為其中心。找不到樣板時走 NG（locate_failed）。沒有 locator 時 clarify 會要求在不移動特徵上標一個。

若沒有封閉 intent 命中，規則引擎會以 prompt 比對樣板圖庫，足夠相似時套用該模板。2026-09-10 新增 `focus` 与 `roundness`；后續又加入 `text`、`distance` 与 `template_presence`，各自帶專屬 clarify 問題。

### 反覆精修 {#refine}

每個結果都有 reasoning 与 run report。可在 feedback box 输入自然語言：

| 回饋 | 規則引擎變更 |
|---|---|
| too sensitive / false rejects / catching too much | blob minimum area x2、顏色 tolerance +40%、match score threshold -0.1 |
| missing them / not finding it / too loose | blob minimum area x0.5、edge threshold x0.6、顏色 tolerance -20% |
| make it 4 | count check 的 expected value 改為 4 |
| ±0.2 | tolerance judge 改為 ±0.2 |
| 無符合参数 | 把回饋併回 request 后重新產生 |

LLM mode 會把目前 graph 与 feedback 交給模型；每次精修都會重新实际执行。

### Agentic mode：嘗試、编辑、驗證、重复 {#agentic}

在 provider 设置選 agentic，或设置 `VISION_AGENT_MODE=agentic`，會把助手產生、全域助手流程编辑与数据調校導向**背景工作**（`POST /agent/jobs`, 202）。介面每秒輪詢 `GET /agent/jobs/{id}?step_from=`，显示**步骤時間軸**：turn/trial 次數、每個 action 摘要与時間，並可取消。需要回答時 job 進入 waiting 状态，`POST /agent/jobs/{id}/answer` 后續跑。

action layer（`apps/vision/agent/actions.py`）提供 `get_state`、`list_tools`、`get_tool_skill`、`analyze_region`、`draft_from_rules`、`use_candidate`、`replace_graph`、`patch_graph`、`run_trial`、`inspect_node`、`crop_template`、`auto_tune`、`ask_user`、`finish`。每次 graph 变更都经 `validate_graph`；dl_* 一律拒绝，write_modbus 与 save_image 只能经由已核准的动作加入（见[需要您核准的动作](#approval)），而且流程必须恰好有一个采集步骤。

loop 預算為 12 turns、8 trials、30 tool calls、240 秒；若預算耗盡但已有 flow，該 flow 會作為結果並在 warnings 註記。provider shim 將中立 history 转為 Claude tools、OpenAI functions、Gemini functionDeclarations 或 OpenAI-compatible functions。

### 与图像窗口互动 {#viewer-protocol}

在 agentic mode 下，助手可以把鼠标交给您，而不是猜坐标。有三种提问直接在图像上回答，而不是打字：**请画一个区域**（助手需要搜索范围；它指明步骤与参数时，平台会直接把区域写进该参数）、**请框一张参考图**（框出定位标记或良品，平台裁成固定图像并接到指定的步骤）、**请确认预览**（先看某个步骤的输出，助手再往下）。卡片出现在助手面板：**在图像上画**会把当前页面的图像查看器切成画图模式，**使用此区域**把区域交回，**发送**送给助手。流程编辑器与 AI 助手页可以画；其他页面的卡片会提示该去哪里。

### 把结果存成复合工具 {#save-tool}

助手页的结果卡有**封装成复合工具**（有工具库编辑权限时默认勾选）。保存时会把检测步骤建成一个复合工具（现场参数与区域就是工具的参数），再建一条含图像来源与一个工具实例的流程并打开它。工具会出现在工具库与工具箱，下一条流程可以直接重用。取消勾选则存成一般流程。

### 没有 AI 供应商时 {#offline-toolbox}

尚未设置供应商时，助手以离线规则引擎运作并明确告知：生成、修改流程与从对话生成任务清单仍在规则范围内可用，而且每一条这类回复都附上**打开检测任务工具**的快捷方式——在流程编辑器会直接打开工具箱的“检测任务”分类，其他页面则前往工具库。助手页的步骤上方也有同样的提示。

### 需要您核准的动作 {#approval}

在 agentic mode 下，助手可以在**您的**权限范围内操作平台：选择图像来源、资产或标定，建立、修改或删除检测任务，接上来源，试运行，自动调参（只用调参组的图像），以及运行批量。每个动作都会重新检查您的权限、遵守引擎锁定，并回报成功、未执行或不确定，附上证据——超时算不确定，绝不会回报成成功。

有些动作会改变产线状态，一定会停下来等您：写输出到设备、存档到共享文件夹、启用结果回传、解除引擎锁定、删除流程或资产，以及把草稿存成流程版本。工作会暂停，面板上出现**动作核准**卡，列出动作、会改变什么与风险。只有点卡片上的**核准**才会执行；点**拒绝**则什么都不动，模型用文字说“已核准”也不算数。修改工程规格（放宽公差、换单位）同样会先问。保存版本时若发现别人已存了较新的版本，这次保存不会执行——助手会说明差异并询问您，绝不覆盖。助手要结束前，一定要在当前的流程上试运行过一次；试运行之后流程若又改过，就得再运行一次。

### 記憶：sessions、priors 与自訂 skills {#memory}

**Sessions (AgentSession)** 保存每次產生的图像、ROI、request、問答、图像標籤、feature vector、graph、reasoning、候選摘要、每張 verdict、provider 与 mode。History 可列出、還原与删除；一般用户只看自己的 session，管理員或 integrator 可看全部。

**相似案例 priors** 由 `memory.find_similar` 取第一個 ROI 或全圖的 mean grey、標準差、edge density、dark fraction、dominant HSV 与 log area，找出相同 intent 且成功或 thumb up 的近鄰。prior 會讓規則引擎重用成功参数、讓 auto-tune 候選值靠前，也會提供給 LLM 作為過去成功案例。

**Custom skills (AgentSkill)** 可在「AI skills」窗口下替平台規則、設計原則、agentic 工作方式与各工具寫補充 notes。個人 note 只影響自己，site note 由管理員设置並影響所有人。API 包含 `GET /agent/skills/custom`、`PUT /agent/skills/custom/{key}`、`DELETE` 与 `GET /agent/skills/{key}`。

### Providers 与 key（依個人保存） {#providers}

助手页右上角的「AI provider」可選**離线規則引擎、Claude、GPT 或 Gemini**，並输入自己的 API key 与模型名稱。设置屬於您的帳號；其他人看不到，`/auth/me` 也只回傳 configured 与末四碼。

| Provider | 实现 | 默认模型 |
|---|---|---|
| offline | 規則引擎；完全無外部呼叫 | - |
| claude | 官方 `anthropic` SDK，選用且延遲載入 | claude-opus-5 |
| openai | urllib 呼叫 REST `/v1/chat/completions`，無依賴 | gpt-4o |
| gemini | urllib 呼叫 REST `generateContent` | gemini-3.6-flash |
| openai_compatible | 任意 OpenAI-compatible endpoint，例如 Ollama、vLLM、LM Studio | endpoint 提供的模型 |

解析順序為用户设置 -> 服务端 `.env` -> offline。OpenAI、compatible 与 Gemini 會要求 JSON 输出；OpenAI reasoning models 自動改用 `max_completion_tokens`。LLM 呼叫失敗會回退到規則引擎，原因列在 warnings。

## Part 3 · 內部機制 {#internals}

此部分说明架構、離线規則引擎、選用 LLM 路徑、助手讀取的 skills、API、保護規則引擎的 benchmark 与設計取捨。

### 架構 {#arch}

助手產生的是**一般 graph JSON**：由既有 dataflow engine 执行，可在编辑器开启，可接任何图像来源，也可綁定 recipe 並透過 TCP 或 HTTP 觸發。助手只是「寫流程的層」，沒有第二套执行路徑。

```text
the user's images + ROIs + prompt
  -> analysis.py ROI features
  -> llm.py with an API key, or intents.py + synth.py offline
  -> a graph checked by validate_graph
  -> service.trial_run
  -> {graph, rationale, report}
```

| 模組 | 職責 |
|---|---|
| `apps/vision/agent/analysis.py` | ROI feature pack：mean、std、Otsu、dark fraction、edge density、dominant HSV、particle stats、Hough circle probe |
| `intents.py` | 將 prompt、ROI shapes 与 features 转為封閉 intent，並擷取 expected count、nominal、tolerance、mm-per-pixel |
| `synth.py` | 每個 intent 一個 synthesiser，填入 ROI 与参数，输出 graph 与 reasoning |
| `providers.py` | provider、设置解析与 key masking |
| `skills.py` 与 `skills/*.md` | 載入平台規則、設計原則与工具 notes，並做 relevance selection |
| `llm.py` | generate、refine、edit、tune 四任務共用系统 prompt，JSON 經 validate_graph |
| `service.py` | orchestration、trial runs、rule-based refinement、edit_rules 与 batch tuning |
| `api.py` | `/vision/agent/*` endpoints 与 execute permission |

### 離线規則引擎 {#rules}

默认模式**完全離线**且無外部依賴。intent 依特異性比對，所有参数由 ROI features 推得。

| Prompt 範例 | Intent | 產生的流程 | 自動参数 |
|---|---|---|---|
| there should be 5 holes | count | grayscale -> denoise -> threshold -> open -> blob -> count check -> OK/NG | threshold polarity、blob minimum area |
| measure the diameter, 17.5 ± 0.4 mm | diameter | find circle -> diameter -> pixel calibration -> tolerance judge | annulus、mm/px、tolerance |
| measure the width, 160 ± 10 | width | caliper -> tolerance judge | - |
| the angle between the two edges | angle | find line x2 -> angle -> range check | 需兩個 ROI |
| any scratches on the surface? | defect | blur -> fixed threshold -> open -> blob -> OK only at zero | threshold 依 ROI mean 与 polarity |
| is this colour right? | color_match | colour comparison -> OK/NG plus stats | ROI dominant colour |
| is the red plug present? | color_presence | colour range mask -> pixel count -> threshold | dominant hue ±12 度与 ROI 面積比例 |
| read the barcode | barcode | read code -> OK/NG plus content output | - |
| is the brightness normal? | brightness | region statistics -> range check | current mean ±30% |
| (unclear) | generic | statistics、histogram、edge density 的資訊流程 | note 要求更多細節 |

### LLM 產生（選用） {#llm}

在 `.env` 設 `VISION_AGENT_API_KEY`（Claude 另需 `pip install anthropic`）后可由模型產生。LLM 能理解較自由描述並組合規則引擎沒有的流程形狀。

- 檢查不變：LLM graph 仍經 `validate_graph` 与实际执行；無效输出重試一次，仍失敗則回規則引擎。
- key 留在服务端：前端只呼叫自家后端，key 不到瀏覽器。List models 与 Test connection 使用畫面上的 provider/key/endpoint 立即测试。
- 数据流向：啟用 LLM 時會把縮小图像、ROI 与 feature summary 送到 provider；封閉環境請不要设置 key。
- 成本：工具目錄与規格放在可快取 system section，精修只支付增量。

### 助手的 skills {#skills}

LLM 依 `apps/vision/agent/skills/` 中三份文件學會「平台方式」。它們也是人可閱讀的文件，可在助手页 AI skills 或 `GET /api/vision/agent/skills` 瀏覽。

| 檔案 | 內容 | 放在哪裡 |
|---|---|---|
| `platform.md` | graph 格式、port、`_flow` 分支、ROI、終点、位元深度、禁止事項、notes、layout | system |
| `design.md` | 標準骨架、需求對工具表、自動調校實務、多張图像与常見错误 | system |
| `tools.md` | 各工具何時用、如何接、如何調、注意事項，加上参数/port/bit depth 表 | 依 relevance 選入 user message |

`skills.select_tools` 會固定帶核心工具，再依 prompt、intent、ROI 形狀与既有 graph 選最多 18 個相關工具。其餘工具以一行目錄列在 system catalogue 中。

### API {#api}

Memory endpoint 只操作自己的項目：`GET /agent/memory`、`POST /agent/memory {text}`、`POST /agent/memory/{id}/rate {rating}`、`DELETE /agent/memory/{id}`。help 回覆會帶 `memory_id` 供評分，context 可帶 `screenshot`。

```text
GET   /api/vision/agent/info
GET   /api/vision/agent/settings
PATCH /api/vision/agent/settings
POST  /api/vision/agent/image
POST  /api/vision/agent/clarify
POST  /api/vision/agent/generate
POST  /api/vision/agent/run
POST  /api/vision/agent/autotune
POST  /api/vision/flows/{id}/golden/autotune
POST  /api/vision/agent/refine
POST  /api/vision/agent/edit
POST  /api/vision/agent/tune
POST  /api/vision/agent/chat
GET   /api/vision/agent/help/search?q=&k=
```

`report` 形狀与 preview endpoint 相同，包含每節点状态、输出、疊圖与图像 ref。执行 endpoint 在引擎鎖定時回 423，並開放給一般用户。

### Benchmark {#bench}

`manage.py agent_bench` 會以 `apps/vision/agent/bench.py` 中的 synthetic cases 跑離线規則引擎，列出 intent accuracy、per-case/per-image verdict accuracy、valid graph 比例与時間。`--llm` 使用服务端 provider，`--keys` 只跑指定 case，`--json` 输出完整 JSON。`tests/test_agent_bench.py` 以門檻守住品質；新增能力以同一把尺量測。

2026 年 9 月的 LLM mode 測量显示：intent 100%、verdict 76%、valid 81%，每 case 約七秒。validation 可攔住 port type mismatch 与不存在 node 等错误；所有 trial 失敗時 `service.generate` 會切回規則引擎；純誤判則靠 image labels 与 auto-tuning 改善。

### 設計取捨 {#design}

- **產品是 graph，不是黑盒**：所有助手產生的內容都能在编辑器开启、逐工具檢查与修改。
- **規則引擎是下限，LLM 是上限**：規則引擎涵蓋多數工廠检测且完全離线；加 key 后 LLM 提升能力，拿掉 key 也不缺核心功能。
- **一定实际执行驗證**：流程回傳前會真的在用户图像上跑，OK/NG 与疊圖才算數。
- **深度学习不會自動生成**：dl_* 需要先训练模型，助手只留下指向教导页的 note；write_modbus 也需已有連线。
- **原則不變**：graph 格式、engine 与單一 API process 都不改；trial run 直接呼叫 engine.execute，不佔 flow thread pool。
