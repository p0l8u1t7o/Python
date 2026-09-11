# AI 助手：影像、ROI 與一句話產生檢測流程

AI 助手（側欄 `/agent`）讓不熟悉工具鏈的人以三步建立檢測：**上傳影像 -> 標記要檢查的區域（可有多個 ROI，各自帶提示） -> 用一句話描述需求**。助手會產生一般流程圖，立即在該影像上執行，並把結果畫回影像。若結果不正確，可用自然語言回饋，例如「誤判過多」、「漏檢」、「改成 4」，它會反覆調整。完成後可儲存為流程並在編輯器繼續調校。

## Part 1 · 全域助手（每個頁面皆有） {#editor}

每個頁面右下角的聊天面板可回答文件與介面地圖問題、讀取目前情境、查詢即時狀態、編輯目前流程、依批次資料調校，並記住您要求它記住的內容。右下角 **AI assistant** 按鈕存在於 `AssistantDock`，切換頁面不會關閉面板。面板標題列的面板按鈕可把它**展開成右側面板**（頁面會讓出寬度）或縮回右下角，選擇記在這台裝置。對話屬於您的帳號，會寫入伺服端；歷史按鈕可重新開啟或刪除。

| 情境（頁面） | 作用 | 後端 |
|---|---|---|
| 任何頁面 | **Help**：依文件回答平台使用問題，並附引用段落連結 | `POST /agent/chat` -> `help.py` |
| 流程編輯器與工具頁 | **Edit the flow**：依指令修改目前畫布，含未儲存變更；工具頁則提供參數建議 | `service.edit` 或 agentic `/agent/jobs` |
| 批次頁，且選定完成執行 | **Consult the data** 與 **Tune from the data**：回答資料問題並提供參數建議，或產生新調校執行 | `consult.consult`、`service.tune`、`persist_tune` |

模式 chip 預設 Auto。問題會走 help；編輯指令會改流程；批次頁上談到資料、影像、NG、threshold、results 時會走資料諮詢。猜錯時可手動選 Help、Edit flow、Consult data 或 Tune from data。頁面以 `useRegisterAssistantContext` 登錄情境，離開時清除。

### 從對話產生檢測任務清單 {#tasklist}

在**檢測任務**頁，助手會把您說的話轉成一份任務清單的提案，而不是直接產生流程圖。一句話可以同時包含好幾項需求——「用十字標記定位工件、允許旋轉；外徑 35±0.2 mm、內徑 26±0.2 mm；缺口超過 2 mm 判不合格」——也可以是修改（「外徑公差改成 ±0.1」）或刪除。提案以卡片呈現，每項任務一個區塊：您說出的值標為已確認，助手推測的值標為**假設**，必填卻沒人給的值標為缺少。助手從影像推估的候選區域，按**顯示在影像上**會以虛線畫出；在您套用之前都只是提案。

流程有多個影像來源時，每張新增任務卡都會詢問要用哪一個；在句子裡說出來源名稱就會預先選好。定位標記這類圖片欄位有**從影像裁切**：在影像上框出範圍，平台會擺正裁切並存進該欄位。在檢測任務頁或畫布說「存成正式版本」會交給代理模式：先試執行，再請您核准儲存；沒有支援動作的 AI 供應商時，請直接按「儲存」。

按下**全部確認**之前什麼都不會改變；**捨棄**則丟掉這份提案。還有值缺少、要用毫米卻沒有標定、或影像來源有歧義時，卡片不會套用，而是先問您。套用走的是與頁面表單相同的任務建立程序，結果與手動建立完全一樣；之後照常在頁面上儲存。

### 接著上次的進度 {#resume}

在某條流程上開啟的對話會綁定那條流程，並在流程圖之外保存工作進度：做過的決策、尚未回答的問題、未確認的假設、哪些樣本圖用來調參、哪些用來驗收，以及上次的試跑結果。之後在這條流程上再開助手，會出現恢復卡：按繼續就載入對話，未回答的問題可以直接在卡片上回答；如果流程在這之後存過，卡片會說明，並依流程的版本歷史列出改了什麼。檢測規格本身永遠從流程讀回——對話不會另存一份。列在「工程決策」底下的決策可以存成工程筆記草稿。

### 說明回答如何運作 {#help-answering}

第一次查詢時，`agent/help.py` 會把 `docs/*.html` 依 h2/h3 與錨點切成段落，加入各工具 skill text，並建立索引。分詞使用英數詞與 CJK bigram；BM25 以標題命中、使用者指南、批次與助手頁加權。文件變更時索引會重建。有 LLM 時會把最相關五段與近期對話送到 provider，系統提示要求只從段落回答、未涵蓋時明說、少於 300 字並列出使用段落。離線或 LLM 失敗時，回傳摘要與連結，並在 warnings 說明原因。

| 離線指令 | 效果 |
|---|---|
| set the threshold of "Binarise" to 80 | 依節點標題、id 或工具名找節點，依 key 或 label 找參數 |
| disable / enable "Denoise" | 切換節點 enabled |
| delete "Result image" | 移除節點與邊；`image_source` 不可刪 |
| too many false rejects / it is missing them / make it 4 / ±0.2 | 使用 iterative refinement 的同一參數映射 |
| 先找外圓心，內圓心 ROI 再跟著外圓心位移 | 新增 `shape_align`，接第一個節點的中心（`cx`／`cy` 或 `matches`），其 `transform` 接到第二個節點的隱含輸入埠 `_transform`；「外／內」對不到節點標題時取 ROI 最大／最小的節點。參考位置由目前影像的試執行教導 |
| 請幫我直接修改畫布 | 指令本身沒有內容時，沿用對話裡上一句需求 |

連接 LLM provider 後沒有固定語法；模型會收到目前 graph、工具目錄與近期對話，只修改必要部分並保留 node id。不論由誰改的，回覆都會列出與目前 graph 的差異（新增或移除的步驟、參數與啟用狀態的變更、連線數）；沒有任何改動的回覆不會出現「套用」按鈕。

### 助手知道哪些螢幕情境 {#situation}

每個問題除了文件，也帶有目前情境，使回答能對準頁面狀態：

| 送出的內容 | 來源 | 例子 |
|---|---|---|
| 頁面種類、route、介面語言 | `AssistantDock` | `tool page, /flows/3/tools/blob, zh-Hant` |
| 頁面快照 | 各頁 `describe()` callback 或 DOM snapshot | selected step、dirty、last_run error |
| 活動軌跡 | `lib/activity.ts` 的 in-memory ring buffer | 近期導覽、失敗 request、toast、run result |
| 呼叫者與鎖定 | 伺服端 `agent/situation.py` | 角色、功能權限、engine lock |

LLM 被要求先解釋近期錯誤、指出確切頁面/分頁/按鈕，且不得建議角色無權執行的動作。**介面語言**控制回答語言，zh-Hant 與 zh-Hans 不混用。`frontend/src/lib/uiMap.ts` 產生的介面地圖列出每頁 route、用途、必要功能、tabs 與主要按鈕，並由 vitest 保持完整。

### 即時查詢與捷徑 {#lookups}

支援 tool calling 的 LLM provider 可先呼叫唯讀 lookup（`agent/lookup.py`）再回答。最多四輪；之後必須依已取得資訊作答。每個 lookup 都依呼叫者角色檢查權限、遮蔽秘密並限制大小。`VISION_AGENT_HELP_LOOKUPS=0` 可關閉。

| Lookup | 回傳 | 需要 |
|---|---|---|
| `list_flows`, `get_flow` | 流程、版本、步驟、recipe、統計、連續狀態與最近執行 | 已登入 |
| `get_run` | 單次執行狀態、錯誤、輸出與各節點訊息 | `flows.run` |
| `list_sources`, `capture_clients` | 影像來源狀態與擷取端/channel | `sources` |
| `list_connections` | 整合連線、即時狀態與啟動錯誤 | `connections` |
| `list_plugins` | 外掛載入狀態、停用項與載入錯誤 | `integration` |
| `engine_status`, `my_permissions` | 版本、站台、鎖定、worker pool 與角色矩陣 | 已登入 |
| `search_docs`, `get_tool` | 文件/介面地圖搜尋與工具完整 skill text | 已登入 |

回答會列出 checked 項目，並可用一行 `ACTIONS:` 產生捷徑 chip，例如前往頁面、開啟分頁、聚焦流程步驟或開啟工具頁。

### 主動提示與畫面文字 {#hints}

`lib/hints.ts` 監看活動軌跡，針對引擎鎖定、角色無權、receiver 未監聽、來源未設定、port 佔用、run/preview 失敗、逾時與伺服端錯誤顯示提示卡。提示卡在助手面板頂部，面板關閉時算未讀；「Ask the assistant」會把錯誤與完整情境送出，「Dismiss」在此 session 隱藏同類提示。規則只在瀏覽器執行，使用者提問前不送出資料。

螢幕圖示會把**畫面文字摘要**附到下一個問題：標題、警示、作用中分頁、可見表格前幾列、表單欄位值與按鈕名稱。密碼、hidden、file 欄位不讀，側欄與助手面板略過，摘要上限 3,000 字。

### 螢幕截圖 {#screenshot}

相機圖示會擷取目前頁面為 JPEG，最長邊 1,600 px、品質 0.8，排除助手面板與 toast，並以縮圖釘在對話下方。截圖只隨下一個問題送一次，作為 `context.screenshot`，之後清除。伺服端只接受 JPEG、base64 最多 4 MB，並把影像與文字一起交給 LLM。無 LLM provider 或分享關閉時按鈕停用；離線規則引擎看不到影像。

### 長期記憶 {#user-memory}

每位登入使用者都有私人記憶（`AssistantMemory`、`agent/notes.py`）；管理員無法讀他人記憶，刪帳號時會一併刪除。

| 內容 | 如何進入 | 如何使用 |
|---|---|---|
| **事實**：使用者要求記住的事項 | 輸入 `remember: ...`，或在 Memory 面板新增；`forget: ...` 移除含該文字的事實 | 列入 LLM prompt 的「使用者要求記住的事項」 |
| **評分回答**：每次 help exchange | 回答下方 thumbs up/down；最多 200 筆 | 類似問題時，評為有用的回答會提供給 LLM；離線可直接回傳近似回答 |

站台與個人的 platform skill 補充也會進入 help prompt，使站台慣例影響 help 回答與流程產生。

### 從一批影像調校 {#tune}

[批次頁](batch.md) 透過全域助手與調校面板提供三項能力：**consultation**、**tuning** 與 **auto-tuning**。執行批次後，在結果表下方使用「Ask the AI to tune from these results」輸入提示，助手會看到每張影像 verdict，調整流程並**重新執行同一批影像**，回報前後 OK、NG、failed 與每張變化。滿意後可套用到畫布。

```text
POST /api/vision/agent/tune  {graph, instruction, runs:[{name, image_ref, status, outputs}]}
-> {graph, rationale, changes, before, after, applied}
```

### 相機、鏡頭與照明建議 {#imaging}

「120 mm 視野和 0.2 mm 缺陷要用哪種相機與鏡頭？」、「暗色表面的刮痕如何打光？」、「GigE 能否支援 20 fps？」這類問題由 `agent/skills/imaging.md` 回答，該 skill 與其他文件一樣在 help index 中，回答會引用它。

算術不靠猜測。唯讀 lookup `camera_optics` 會依視野、工作距離與 sensor format 計算焦距、最近標準鏡頭、特徵所需 sensor pixel、mm/px、景深、在輸送帶速度下保持運動模糊小於一像素的曝光，以及介面頻寬。

### 參考圖片跟著流程走 {#pictures}

設計需要參考圖時，例如 `template_match` 樣板、`defect_diff` golden sample、`shading_correct` 白參考，助手會從您上傳的影像裁切並放入 **Fixed image** 步驟（role `"reference"`），再接到工具影像輸入，而不是建立資產。圖片隨流程儲存與匯出，資產庫不會累積一次性檔案。

## Part 2 · 在助手頁產生流程 {#generate}

側欄 AI 助手頁把影像、少量 ROI 與一句話變成可執行流程。本部分說明產生前的提問、多張影像與編號 ROI、候選流程與自動調校、定位校正、文字回饋、agentic mode、session memory 與 provider 設定。

### 產生前先詢問 {#clarify}

點選「Generate」後不會立刻開始，而是先呼叫 `POST /agent/clarify` 判斷資訊是否足夠；不足時最多問**三個**關鍵問題，可為選項、數字、文字或要求再標記 ROI。回答後會再檢查，準備好才產生。「Skip the questions and generate」永遠可用，結果卡會列出缺漏資訊與採用的預設。

| 情況 | 會問什麼 |
|---|---|
| 模糊提示 | 要檢查什麼：數量、直徑、寬度、角度、缺陷、顏色、存在、碼、亮度 |
| 計數但未給數量 | 預期幾個；沒有 ROI 時問全圖或特定區域；深淺粒子相近時問目標較暗或較亮 |
| 直徑但無圓形 ROI/圓偵測 | 請在孔邊標記圓環；若要求毫米但無比例，問每像素幾毫米 |
| 寬度或角度 | 缺少的 ROI、第二邊 ROI、名目值與公差 |
| 表面缺陷 | 是否有良品可比較；若有則使用 golden comparison |
| 顏色判斷但無 ROI | 請標記判斷區域，目標色由此擷取 |

答案會折回 prompt，例如「expect 5」、「target is darker」、「nominal 17.5 ± 0.4 mm」，規則引擎與 LLM 讀同一段文字。執行中按鈕會變成 Stop；取消後伺服端完成該次呼叫也不會套用結果。

### 多張影像與編號 ROI {#multi}

可一次上傳多張影像，縮圖列用來切換，且可在每張影像標 ROI。ROI 依加入順序編號為 `ROI01`、`ROI02`，每個都可帶 hint，prompt 可引用編號。

```text
ROI01 is a good part and ROI02 is a bad one; find the difference
```

此例觸發 golden comparison intent：良品 ROI 被裁切為資產群組「AI assistant」中的樣板，檢測視窗放在壞品 ROI 位置並保持樣板尺寸，再產生 `defect_diff` 流程。每張影像都會實際執行，縮圖角落標示 OK 或 NG。

### 候選、影像標籤與自動調校 {#candidates}

規則引擎現在不只產生一個流程；每個 intent 會有主方案與一兩個參數變體。所有候選會在每張上傳影像上靜默執行，依**影像標籤**計分，只有勝出者會正式執行並保留疊圖。`candidates[]` 列出各方案 verdict 與分數，助手頁可切換候選並由 `POST /agent/run` 重跑。

影像縮圖右下角可標記該圖期望 OK/NG；ROI hint 為 good/bad 時會自動成為標籤。若有兩個以上標籤且勝出者未全命中，generation 會跑小預算 auto-tune（24 次評估、10 秒），只在改善時採用。

**Auto-tuning** 是 coordinate descent：只移動 `teach=True` 參數，依目前值周圍的幾何階梯測候選，並以標註影像比較 hits、errors、failures。只有嚴格改善才採用；平手保留原值，小變更優先以降低過擬合。規格參數不會被動到。

### 定位校正與較新的 intent {#locate}

prompt 提到位置移動、定位、位移或跟隨，或 ROI hint 為 `locator` 時，該 ROI 不參與檢測，而是裁切成**定位樣板**，並由 `synth.wrap_with_locate` 在流程前段包上 template match -> locate correction -> ROI follow。搜尋區為 locator ROI 放大 1.5 倍，reference position 為其中心。找不到樣板時走 NG（locate_failed）。沒有 locator 時 clarify 會要求在不移動特徵上標一個。

若沒有封閉 intent 命中，規則引擎會以 prompt 比對樣板圖庫，足夠相似時套用該範本。2026-09-10 新增 `focus` 與 `roundness`；後續又加入 `text`、`distance` 與 `template_presence`，各自帶專屬 clarify 問題。

### 反覆精修 {#refine}

每個結果都有 reasoning 與 run report。可在 feedback box 輸入自然語言：

| 回饋 | 規則引擎變更 |
|---|---|
| too sensitive / false rejects / catching too much | blob minimum area x2、顏色 tolerance +40%、match score threshold -0.1 |
| missing them / not finding it / too loose | blob minimum area x0.5、edge threshold x0.6、顏色 tolerance -20% |
| make it 4 | count check 的 expected value 改為 4 |
| ±0.2 | tolerance judge 改為 ±0.2 |
| 無符合參數 | 把回饋併回 request 後重新產生 |

LLM mode 會把目前 graph 與 feedback 交給模型；每次精修都會重新實際執行。

### Agentic mode：嘗試、編輯、驗證、重複 {#agentic}

在 provider 設定選 agentic，或設定 `VISION_AGENT_MODE=agentic`，會把助手產生、全域助手流程編輯與資料調校導向**背景工作**（`POST /agent/jobs`, 202）。介面每秒輪詢 `GET /agent/jobs/{id}?step_from=`，顯示**步驟時間軸**：turn/trial 次數、每個 action 摘要與時間，並可取消。需要回答時 job 進入 waiting 狀態，`POST /agent/jobs/{id}/answer` 後續跑。

action layer（`apps/vision/agent/actions.py`）提供 `get_state`、`list_tools`、`get_tool_skill`、`analyze_region`、`draft_from_rules`、`use_candidate`、`replace_graph`、`patch_graph`、`run_trial`、`inspect_node`、`crop_template`、`auto_tune`、`ask_user`、`finish`。每次 graph 變更都經 `validate_graph`；dl_* 一律拒絕，write_modbus 與 save_image 只能經由核准過的動作加入（見[需要您核准的動作](#approval)），而且流程必須恰好有一個取像步驟。

loop 預算為 12 turns、8 trials、30 tool calls、240 秒；若預算耗盡但已有 flow，該 flow 會作為結果並在 warnings 註記。provider shim 將中立 history 轉為 Claude tools、OpenAI functions、Gemini functionDeclarations 或 OpenAI-compatible functions。

### 與影像視窗互動 {#viewer-protocol}

在 agentic mode 下，助手可以把滑鼠交給您，而不是猜座標。有三種提問直接在影像上回答，而不是打字：**請畫一個區域**（助手需要搜尋範圍；它指明步驟與參數時，平台會直接把區域寫進該參數）、**請框一張參考圖**（框出定位標記或良品，平台裁成固定影像並接到指定的步驟）、**請確認預覽**（先看某個步驟的輸出，助手再往下）。卡片出現在助手面板：**在影像上畫**會把目前頁面的影像檢視器切成畫圖模式，**使用此區域**把區域交回，**送出**送給助手。流程編輯器與 AI 助手頁可以畫；其他頁面的卡片會提示該去哪裡。

### 把結果存成複合工具 {#save-tool}

助手頁的結果卡有**封裝成複合工具**（有工具庫編輯權限時預設勾選）。儲存時會把檢測步驟建成一個複合工具（現場參數與區域就是工具的參數），再建一條含影像來源與一個工具實例的流程並開啟它。工具會出現在工具庫與工具箱，下一條流程可以直接重用。取消勾選則存成一般流程。

在代理模式下，助手也可以自己提出同樣的動作（**存成工具**）：必須先在目前的流程上試執行，工具 key 不得與既有工具重複，而且要等您核准它的卡片才會建立。

### 沒有 AI 供應商時 {#offline-toolbox}

尚未設定供應商時，助手以離線規則引擎運作並明確告知：生成、修改流程與從對話產生任務清單仍在規則範圍內可用，而且每一則這類回覆都附上**開啟檢測任務工具**的捷徑——在流程編輯器會直接開工具箱的「檢測任務」分類，其他頁面則前往工具庫。助手頁的步驟上方也有同樣的提示。

### 需要您核准的動作 {#approval}

在 agentic mode 下，助手可以在**您的**權限範圍內操作平台：選擇影像來源、資產或標定，建立、修改或刪除檢測任務，接上來源，試跑，自動調參（只用調參組的影像），以及執行批次。每個動作都會重新檢查您的權限、遵守引擎鎖定，並回報成功、未執行或不確定，附上證據——逾時算不確定，絕不會回報成成功。

有些動作會改變產線狀態，一定會停下來等您：寫輸出到設備、存檔到共用資料夾、啟用結果回送、解除引擎鎖定、刪除流程或資產，以及把草稿存成流程版本。工作會暫停，面板上出現**動作核准**卡，列出動作、會改變什麼與風險。只有按卡片上的**核准**才會執行；按**拒絕**則什麼都不動，模型用文字說「已核准」也不算數。修改工程規格（放寬公差、換單位）同樣會先問。儲存版本時若發現別人已存了較新的版本，這次儲存不會執行——助手會說明差異並詢問您，絕不覆蓋。助手要結束前，一定要在目前的流程上試跑過一次；試跑之後流程若又改過，就得再跑一次。

### 記憶：sessions、priors 與自訂 skills {#memory}

**Sessions (AgentSession)** 保存每次產生的影像、ROI、request、問答、影像標籤、feature vector、graph、reasoning、候選摘要、每張 verdict、provider 與 mode。History 可列出、還原與刪除；一般使用者只看自己的 session，管理員或 integrator 可看全部。

**相似案例 priors** 由 `memory.find_similar` 取第一個 ROI 或全圖的 mean grey、標準差、edge density、dark fraction、dominant HSV 與 log area，找出相同 intent 且成功或 thumb up 的近鄰。prior 會讓規則引擎重用成功參數、讓 auto-tune 候選值靠前，也會提供給 LLM 作為過去成功案例。

**Custom skills (AgentSkill)** 可在「AI skills」視窗下替平台規則、設計原則、agentic 工作方式與各工具寫補充 notes。個人 note 只影響自己，site note 由管理員設定並影響所有人。API 包含 `GET /agent/skills/custom`、`PUT /agent/skills/custom/{key}`、`DELETE` 與 `GET /agent/skills/{key}`。

### Providers 與 key（依個人保存） {#providers}

助手頁右上角的「AI provider」可選**離線規則引擎、Claude、GPT 或 Gemini**，並輸入自己的 API key 與模型名稱。設定屬於您的帳號；其他人看不到，`/auth/me` 也只回傳 configured 與末四碼。

| Provider | 實作 | 預設模型 |
|---|---|---|
| offline | 規則引擎；完全無外部呼叫 | - |
| claude | 官方 `anthropic` SDK，選用且延遲載入 | claude-opus-5 |
| openai | urllib 呼叫 REST `/v1/chat/completions`，無依賴 | gpt-4o |
| gemini | urllib 呼叫 REST `generateContent` | gemini-3.6-flash |
| openai_compatible | 任意 OpenAI-compatible endpoint，例如 Ollama、vLLM、LM Studio | endpoint 提供的模型 |

解析順序為使用者設定 -> 伺服端 `.env` -> offline。OpenAI、compatible 與 Gemini 會要求 JSON 輸出；OpenAI reasoning models 自動改用 `max_completion_tokens`。LLM 呼叫失敗會回退到規則引擎，原因列在 warnings。

## Part 3 · 內部機制 {#internals}

此部分說明架構、離線規則引擎、選用 LLM 路徑、助手讀取的 skills、API、保護規則引擎的 benchmark 與設計取捨。

### 架構 {#arch}

助手產生的是**一般 graph JSON**：由既有 dataflow engine 執行，可在編輯器開啟，可接任何影像來源，也可綁定 recipe 並透過 TCP 或 HTTP 觸發。助手只是「寫流程的層」，沒有第二套執行路徑。

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
| `intents.py` | 將 prompt、ROI shapes 與 features 轉為封閉 intent，並擷取 expected count、nominal、tolerance、mm-per-pixel |
| `synth.py` | 每個 intent 一個 synthesiser，填入 ROI 與參數，輸出 graph 與 reasoning |
| `providers.py` | provider、設定解析與 key masking |
| `skills.py` 與 `skills/*.md` | 載入平台規則、設計原則與工具 notes，並做 relevance selection |
| `llm.py` | generate、refine、edit、tune 四任務共用系統 prompt，JSON 經 validate_graph |
| `service.py` | orchestration、trial runs、rule-based refinement、edit_rules 與 batch tuning |
| `api.py` | `/vision/agent/*` endpoints 與 execute permission |

### 離線規則引擎 {#rules}

預設模式**完全離線**且無外部依賴。intent 依特異性比對，所有參數由 ROI features 推得。

| Prompt 範例 | Intent | 產生的流程 | 自動參數 |
|---|---|---|---|
| there should be 5 holes | count | grayscale -> denoise -> threshold -> open -> blob -> count check -> OK/NG | threshold polarity、blob minimum area |
| measure the diameter, 17.5 ± 0.4 mm | diameter | find circle -> diameter -> pixel calibration -> tolerance judge | annulus、mm/px、tolerance |
| measure the width, 160 ± 10 | width | caliper -> tolerance judge | - |
| the angle between the two edges | angle | find line x2 -> angle -> range check | 需兩個 ROI |
| any scratches on the surface? | defect | blur -> fixed threshold -> open -> blob -> OK only at zero | threshold 依 ROI mean 與 polarity |
| is this colour right? | color_match | colour comparison -> OK/NG plus stats | ROI dominant colour |
| is the red plug present? | color_presence | colour range mask -> pixel count -> threshold | dominant hue ±12 度與 ROI 面積比例 |
| read the barcode | barcode | read code -> OK/NG plus content output | - |
| is the brightness normal? | brightness | region statistics -> range check | current mean ±30% |
| (unclear) | generic | statistics、histogram、edge density 的資訊流程 | note 要求更多細節 |

### LLM 產生（選用） {#llm}

在 `.env` 設 `VISION_AGENT_API_KEY`（Claude 另需 `pip install anthropic`）後可由模型產生。LLM 能理解較自由描述並組合規則引擎沒有的流程形狀。

- 檢查不變：LLM graph 仍經 `validate_graph` 與實際執行；無效輸出重試一次，仍失敗則回規則引擎。
- key 留在伺服端：前端只呼叫自家後端，key 不到瀏覽器。List models 與 Test connection 使用畫面上的 provider/key/endpoint 立即測試。
- 資料流向：啟用 LLM 時會把縮小影像、ROI 與 feature summary 送到 provider；封閉環境請不要設定 key。
- 成本：工具目錄與規格放在可快取 system section，精修只支付增量。

### 助手的 skills {#skills}

LLM 依 `apps/vision/agent/skills/` 中三份文件學會「平台方式」。它們也是人可閱讀的文件，可在助手頁 AI skills 或 `GET /api/vision/agent/skills` 瀏覽。

| 檔案 | 內容 | 放在哪裡 |
|---|---|---|
| `platform.md` | graph 格式、port、`_flow` 分支、ROI、終點、位元深度、禁止事項、notes、layout | system |
| `design.md` | 標準骨架、需求對工具表、自動調校實務、多張影像與常見錯誤 | system |
| `tools.md` | 各工具何時用、如何接、如何調、注意事項，加上參數/port/bit depth 表 | 依 relevance 選入 user message |

`skills.select_tools` 會固定帶核心工具，再依 prompt、intent、ROI 形狀與既有 graph 選最多 18 個相關工具。其餘工具以一行目錄列在 system catalogue 中。

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

`report` 形狀與 preview endpoint 相同，包含每節點狀態、輸出、疊圖與影像 ref。執行 endpoint 在引擎鎖定時回 423，並開放給一般使用者。

### Benchmark {#bench}

`manage.py agent_bench` 會以 `apps/vision/agent/bench.py` 中的 synthetic cases 跑離線規則引擎，列出 intent accuracy、per-case/per-image verdict accuracy、valid graph 比例與時間。`--llm` 使用伺服端 provider，`--keys` 只跑指定 case，`--json` 輸出完整 JSON。`tests/test_agent_bench.py` 以門檻守住品質；新增能力以同一把尺量測。

2026 年 9 月的 LLM mode 測量顯示：intent 100%、verdict 76%、valid 81%，每 case 約七秒。validation 可攔住 port type mismatch 與不存在 node 等錯誤；所有 trial 失敗時 `service.generate` 會切回規則引擎；純誤判則靠 image labels 與 auto-tuning 改善。

### 設計取捨 {#design}

- **產品是 graph，不是黑盒**：所有助手產生的內容都能在編輯器開啟、逐工具檢查與修改。
- **規則引擎是下限，LLM 是上限**：規則引擎涵蓋多數工廠檢測且完全離線；加 key 後 LLM 提升能力，拿掉 key 也不缺核心功能。
- **一定實際執行驗證**：流程回傳前會真的在使用者影像上跑，OK/NG 與疊圖才算數。
- **深度學習不會自動生成**：dl_* 需要先訓練模型，助手只留下指向教導頁的 note；write_modbus 也需已有連線。
- **原則不變**：graph 格式、engine 與單一 API process 都不改；trial run 直接呼叫 engine.execute，不佔 flow thread pool。
