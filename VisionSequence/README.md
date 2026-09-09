# VisionSequence — 工業機器視覺流程平台

> **English summary** — VisionSequence is a browser-based industrial machine-vision platform (Django + django-ninja + OpenCV backend, React 19 + React Flow frontend). Engineers drag tool nodes onto a dataflow canvas, draw ROIs on images, tune parameters with live results, and expose the resulting flow to PLC/MES systems over HTTP, TCP and Modbus. It ships 132 built-in vision tools, a template gallery with synthetic sample images, in-platform deep-learning teaching (labeling → training → ONNX), and an AI assistant that turns "upload image + draw ROI + one sentence" into a runnable inspection flow (offline rule engine or Claude/GPT/Gemini). Single-process runtime, no Node.js services, no microservices. Docs are in `docs/` (19 HTML pages, English); contributor rules live in `CLAUDE.md` (Traditional Chinese).

類 Hikrobot VisionMaster 的畫布式機器視覺平台：自動化人員在瀏覽器裡拉工具節點、在影像上畫 ROI、
調參數即時看結果，再以 HTTP／TCP 讓 PLC、上位機或 MES 觸發檢測並取回 OK/NG 與量測值。

| 項目 | 內容 |
|---|---|
| 後端 | Django 5.1 + django-ninja + OpenCV／numpy／scipy（可選 onnxruntime、torch/ultralytics、anthropic） |
| 前端 | React 19 + Vite + TypeScript + Tailwind v4 + @xyflow/react（React Flow）+ TanStack Query + i18next |
| 執行 | 單一行程：uvicorn（HTTP + SSE）＋ TCP 介面同行程；資料流 DAG 引擎在執行緒池內跑，影像以 numpy 在記憶體傳遞 |
| 規模 | 145 個內建工具、242 個 API 端點、33 個資料模型、22 個前端頁面（另 7 個整合子頁）、19 頁文件、後端約 1307 項＋前端約 156 項自動測試；擷取端桌面程式（vscapture，PySide6） |

---

## 目錄

1. [快速開始](#快速開始)
2. [功能全貌](#功能全貌)
3. [架構](#架構)
4. [程式碼地圖](#程式碼地圖)
5. [資料模型](#資料模型)
6. [API 一覽](#api-一覽)
7. [執行模型與效能](#執行模型與效能)
8. [擴充點](#擴充點)
9. [設定（.env）](#設定env)
10. [驗證與測試](#驗證與測試)
11. [部署](#部署)
12. [文件地圖](#文件地圖)
13. [尚未實作](#尚未實作)

---

## 快速開始

Windows（PowerShell）：

```powershell
.\scripts\dev.ps1 -Setup     # 第一次：建 .venv、安裝、migrate、seed_demo、npm install
.\scripts\setup_dl.ps1          # 可選：GPU 深度學習依賴（torch cu128＋ultralytics＋onnxruntime-gpu，約 3GB），最後跑 manage.py dl_check 驗證
.\scripts\dev.ps1            # 之後：後端 HTTP 8000 + TCP 9000、前端 5173
.\scripts\stop.ps1
```

手動：

```bash
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo      # 樣本圖（固定影像）／範例資產＋2 個示範流程；範例樣板在範本畫廊
.venv/Scripts/python.exe manage.py serve          # uvicorn :8000 + TCP :9000（同一行程）
cd frontend && npm install && npm run dev         # http://127.0.0.1:5173
```

- 第一次開啟前端會要求建立管理員（或 `manage.py create_admin <user> --password-env NAME`）。
- 交付客戶：`.\scripts\build_release.ps1` 產出自帶 Python 的發行樹／zip／安裝程式，客戶端 `vsctl.cmd` 管服務、升級、外掛與 DL 加購包，見 [部署](#部署)。
- API 文件（OpenAPI）：http://127.0.0.1:8000/api/docs
- 使用者手冊：`docs/user-guide.html`；介面內「說明」頁有精簡版與工具目錄。

---

## 功能全貌

### 流程編輯與執行
- **流程編輯器**（`/flows/:id`）：資料流畫布（型別化埠、控制分支 `_flow`、隱含直通埠 `_image`）、工具選擇視窗（分群／搜尋／收藏）、註解便利貼、復原／複製貼上／自動排列、右側屬性與結果面板；右下角全域 AI 助手可用一句話修改目前畫布並套用。
- **工具頁**（`/flows/:id/tools/:nodeId`）：單一步驟的專屬調參頁——左參數、中「執行前／執行後」影像、下參考資訊（直方圖／統計／輸出值）、右按鍵；ROI 進頁即顯示；參數暫存、儲存才寫回。
- **影像檢視器**：縮放／平移／像素值／標記疊圖；ROI 形狀 rect / rotated_rect / circle / ellipse / annulus（可扇形）/ polygon / polyline / line / point。
- **試執行 vs 執行**：試執行用目前畫布（含未儲存）並保留中間影像；執行一次／連續執行用已儲存版本並寫入紀錄。暫存影像上傳只為試執行，不進來源庫。
- **參數卡**（`/flows/:id/teach`）：只列 `teach=True` 的現場參數、改動即時試執行；標記「已教導」。
- **配方**：同一流程多組參數覆寫（換線），HTTP／TCP 皆可指定。
- **Python 腳本工具**：管理員可在工具頁直接寫 `def run(ctx)` 做自訂檢測（同行程受限執行：白名單匯入、逾時中止、輸入唯讀），輸出數值／布林／文字／資料／影像與通過／不良分支；一般使用者可執行已核准的腳本並調整現場參數。
- **批次測試頁／Golden Set**：獨立頁面選流程、建立影像集（上傳或來源擷取，≤200 張）批量執行並暫存每次逐張結果；標記期望 OK／NG 得命中率與混淆矩陣，洞察卡給建議門檻、輸出分佈與歷次趨勢；調參重跑同一影像集並逐張比較，滿意後寫回流程／存為配方／帶回編輯器；右下角的全域 AI 助手可依資料諮詢或調整、調參面板可自動調參（結果成為新執行）。案例可存入 Golden Set 作回歸基準，`manage.py regress` 可進 CI。
- **統計**（`/flows/:id/stats`）：執行歷史、良率趨勢、每小時 OK/NG；封存影像可「在編輯器用這張重跑」。
- **標定**（`/calibration`）：標定板／機械手對點／已知距離／手眼／相機映射／多相機拼接，先看每點殘差或拼接預覽再保存；`undistort`、`stitch_images`、`to_world`、`map_points`、`calibration`、`align_offset` 共用標定資產或流程設定。
- **流程變數**：`variable_set`／`variable_get` 在執行之間保留計數、上一片、料號（flow／station 兩個範圍）；試執行與批次在沙箱不動產線的值。
- **現場看板**：每條流程設定要顯示哪些具名輸出（標籤、單位、公差）、哪張影像、哪些變數；總覽頁照它顯示，`/board/:id` 是給操作站的全螢幕看板。
- **參數訂閱**：門檻要跟著亮度走的時候，把上游的數值接到參數的輸入埠，執行時就用那個值，不必寫公式再手動填。
- **位置修正**：工件位置會變的時候，把定位補正接到量測步驟的「位置修正」埠，那一步畫的區域就自己跟著工件走（不必在圖裡插跟隨節點）；整條流程都要跟就用「影像跟隨」把影像轉回教導時的姿態。定位沒找到時區域留在原地並留下警告，不會靜默量到空氣。
- **除錯**：試執行後節點顯示耗時熱點（最慢紅）、右鍵「只跑到這裡」。

### 內建工具（145 個，8 類）
| 類別 | 工具 |
|---|---|
| 影像來源（2） | image_source, stereo_grab |
| 前處理（25） | grayscale, crop, resize, blur, threshold, morphology, lut, filter, surface_filter（表面缺陷濾波）, fft_filter, warp_perspective, undistort, shading_correct, stitch_images, polar_unwrap, polar_restore, photometric_stereo, convert_depth, rotate_flip, color_convert, color_range, color_segment, color_classify, apply_mask, arithmetic |
| 定位（18） | template_match（多模板、排序、縮放、邊界、逾時）, shape_match（幾何比對）, shape_align, fixture_roi, image_fixture（影像轉回教導姿態）, region_from_shape, region_combine（多重 ROI／排除區）, find_circle, find_line, find_rectangle, find_quadrilateral, find_parallel_lines, find_lines_multi, find_circles_matrix, hough_circles, hough_lines |
| 量測（27） | caliper, circular_caliper, profile_defect, wall_thickness, fit_arc, fit_ellipse, chamfer_angle, angle, distance（點／線／圓）, geometry（作圖）, points_merge, concentricity, calibration, to_world, intensity, histogram, line_profile, color_stats, edge_density, contour_find, contour_filter, contour_geometry, contour_match |
| 檢測／識別（15） | blob, edge_defect（邊緣缺陷：缺口／崩掉／錯位／寬度）, edge_model_defect（任意輪廓缺陷）, defect_diff, defect_stat（統計範本）, ocr_read（文字辨識）, ocv_verify（字串驗證）, barcode, text_presence, color_check, pixel_count, dark_ratio（外掛範例）, … |
| 深度學習（12） | dl_classify, dl_detect, dl_segment, dl_instance（ONNX 推論）, dl_anomaly（只教良品的異常檢測）, dl_retrieval；ai_detect, ai_segment, ai_classify, ai_pose, ai_obb（ultralytics 原生推論，GPU 自動使用，模型選教導產物或官方底模） |
| 邏輯（20） | if_number, in_range, tolerance_judge, bool_logic, formula, count_list, boxes_merge, boxes_filter, array_correct, list_sort, track_objects（連續模式目標追蹤）, parse_message（拆解設備送來的訊息）, switch（多路分支）, string_match（文字比對）, python_script（自寫 Python，管理員核准）, call_flow（同行程子流程）, for_each（逐項子流程）, tile（切片） |
| 輸出（9） | judge, output, draw_result, save_image, format_text, write_log, trigger_flow, write_modbus, send_image（TCP 傳圖） |

影像位深：工具預設只吃 8-bit，其餘自動正規化；宣告 `accepts` 的工具可原生處理 16-bit／浮點。詳見 `docs/vision-capabilities.html`。

**演算能力補強（2026-09，16 個工作包，規格見 `docs/vision-capabilities.html` 與 `docs/performance.html`）**：
- 前處理：`polar_unwrap`／`polar_restore`（環形工件展開）、`shading_correct`（平場校正）、`stitch_images`（硬拼／投影拼接）、`undistort` alpha 與 mm_per_pixel、`photometric_stereo`（四燈光度立體，刻印字／凹坑）、`accel` 透明 GPU 後端（只對 ≥ 4 MP 的 remap／中值／卷積／FFT，實測理由見效能頁）。
- 定位與區域：`shape_match`（幾何形狀比對，遮擋與打光變化不怕；可用內建 cross／square outline／disc Mark）、`region_from_shape`／`region_combine`（組合區域：聯集／挖除／交集）。
- 量測：`contour_find`／`contour_filter`／`contour_geometry`／`contour_match`（輪廓鏈與凸缺陷）、`circular_caliper`／`profile_defect`（圓形卡尺與序列缺陷）、`gdt_measure`（形位公差：直線度／平面度／真圓度 MZC／平行度／垂直度／傾斜度）、`to_world` 接數值埠、標定頁覆蓋率地圖與警告。
- 檢測：`defect_stat`（統計範本比對）、`dl_anomaly`（只教良品的異常檢測）、`dl_retrieval`、`ocr_read`／`ocv_verify`（離線 OCR 與字型教導）、`barcode_grade`（ISO 15415／15416／AIM DPM 條碼品質分級，解碼靠 zxing-cpp）。
- 品質資料：`manage.py precision`（重複性／再現性／GR&R 報告與 CI 門檻，統計頁精度卡）、量測值 SPC（`MeasurementLog`、管制圖／Cp,Cpk／Nelson 判異、總覽告警、`GET /flows/{id}/spc`、`GET /spc/alerts`）。

### 資料保留與自動整理

- 保存時限（執行明細、操作紀錄、量測值、封存影像、備份份數、維護時段）存在資料庫單列，**設定頁**（管理員）可改、立即生效；預設 **1 年**，0＝永久；每小時彙總永久保留，良率曲線不受影響。
- **不影響檢測**：清理跑在既有的歷史寫入執行緒的空檔，每批 500 列，發現有 run 在排隊／執行／連續模式立刻停手；備份整理、孤兒圖片與 VACUUM 只在維護時段且引擎閒置一分鐘後才做。
- `GET/PATCH /vision/retention`、`POST /vision/retention/sweep`（立即整理）、`manage.py purge [--pictures --backups N]`、`doctor` 的 retention／backups 兩行。

### 範本畫廊與範例樣板
34 個內建範本（計數、曝光、圓孔量測、邊線夾角、圓周齒數、輪廓崩邊、圓盤崩邊、真圓度形位公差、刻印字光度立體、條碼品質分級、排除區、平場校正、統計良品比對、形狀比對定位、異常檢測、日期碼讀取、良品比對、織紋瑕疵、前處理教學、多圓幾何、顏色有無、顏色比對、條碼標籤、定位量測、杯件量測…），每個都配合成樣本圖（`data/samples/`，第 4 張刻意 NG）與自動裁切的範本資產；從範本建立流程時選對應「範例：⋯」來源即可直接執行。覆蓋 82/132 個工具。詳見 `docs/samples.html`。
- **畫廊分類分組**（教學、計數、量測、品質、缺陷、辨識、自訂）＋篩選列；內建範本自帶樣本圖：來源留「範本自帶的樣本圖」時取像步驟變成 **固定影像** 工具（`fixed_image`，圖片跟著流程存、每次執行輪到下一張），要接相機再選來源。範本比對／良品比對／平場的參考圖也是固定影像節點接到工具的圖片輸入埠（`template_image`／`flat_image`／`dark_image`），不再建立範例來源與影像資產。

### AI 助手（`/agent`）

- **取像與打光**：問相機／鏡頭／光源怎麼選，助手用 `camera_optics` 算焦距、需要的像素、景深、曝光上限與頻寬（不是口算），判斷準則在 `agent/skills/imaging.md`。
- **對話（每位使用者）**：助手視窗可開新對話、回到過去的對話、刪除對話；存在伺服器（`AssistantChat`，每人 50 條、每條 60 則），換一台電腦登入還在。
- **參考圖不進資產庫**：助手要的範本／良品／白參考直接裁成**固定影像**節點接到工具的圖片輸入埠，跟著流程走（匯出會帶）。
- **全域 AI 助手**：每個頁面右下角的聊天視窗，切換頁面不消失（對話存瀏覽器）。一個輸入框依頁面脈絡分流：任何頁面可問平台怎麼用（`agent/help.py` 把 docs 章節與工具技能建成 BM25 索引，LLM 只依片段回答並附 `/docs/` 參考連結，離線回文件節錄）；流程編輯器內直接修改目前畫布並套用（可復原）；批次測試頁選定執行後資料諮詢或依資料調整（結果成為新執行）。模式晶片可強制指定。
- 上傳一張或多張影像 → 圈選 ROI（ROI01、ROI02…各配提示，可引用「ROI01 是好品，ROI02 是壞品」）→ 一句話描述需求 → **先確認再生成**（資訊不足時最多 3 個問題，可略過）→ 生成流程並在每張影像實跑、疊顯標記 → 口語回饋微調 → 存成流程。
- 兩層供應器：離線規則引擎（15 種意圖封閉集合＋合成器＋特徵驅動參數）；可選 LLM（Claude／GPT／Gemini／OpenAI 相容本地端點，每位使用者自己的金鑰只存伺服器），失敗自動落回規則並在 warnings 說明原因。
- **候選方案與自動調參**：規則引擎每次產主要方案＋參數變體，全部在上傳影像上試跑後依「影像標記」（縮圖 OK／NG 或 ROI 提示好品／壞品）打分擇優，可點選切換；有標記時再做小預算自動調參（只動現場調機參數，嚴格變好才採納）。
- **定位補正**：ROI 提示填「定位」或提示詞說位置會變，流程前自動包「範本比對 → 定位補正 → ROI 跟隨」；新增印字有無、兩孔中心距、圖案有無三種意圖。
- **代理模式**（工作模式選「代理模式」）：AI 以動作逐步起草、試跑、修改、驗證流程（背景工作＋步驟時間軸，可中斷、可回答提問後續跑），Claude／GPT／Gemini／本地相容端點皆可；預算用完以目前流程為結果，失敗自動退回單次生成與規則引擎。
- **記憶與學習**：每次生成存成工作階段（可還原、可評分、存成流程自動關聯）；標記全中或按讚的案例成為相似影像的參數先驗（候選「沿用過去成功參數」、自動調參首選、LLM 過去案例段）；「AI 技能」視窗可寫站點／個人補充要領，AI 一併讀取。
- 評測基準 `manage.py agent_bench`（21 個離線案例：意圖／判定／有效率），`tests/test_agent_bench.py` 守門檻。
- 全域 AI 助手在編輯器內可用一句話修改目前流程、在批次測試頁可依結果諮詢與調整；所有助手呼叫皆可中斷。
- 助手看得到「現況」：頁面快照（選取的步驟、未儲存、上次執行）、操作軌跡（最近的換頁、失敗的請求、執行結果；金鑰遮罩、不落地）、呼叫者角色與引擎鎖定，以及三語系的介面地圖（頁面、分頁、按鈕；`npm run ui-map` 產生）——回答會先解釋剛剛的錯誤、指到正確的頁面與按鈕、不建議角色做不到的事；助手視窗的眼睛圖示可關閉分享。
- 助手能「自己去查」：有 LLM 時問答路徑可呼叫唯讀查詢（流程清單與細節、執行報告、來源、連線、鎖定、外掛、擷取端、權限、文件），依呼叫者權限把關、最多 4 回合；回覆下方列出查了什麼，並可附「前往某頁某分頁」「聚焦節點」「開工具頁」的捷徑晶片（離線規則問「在哪裡」也給前往）。
- 助手會主動開口：鎖定 423、權限 403、接收端沒開、沒選來源、埠被佔、執行失敗、逾時、伺服器錯誤等失敗出現時，助手視窗顯示提示卡（一句說明＋「詢問助手」一鍵帶著錯誤與現況提問；同種 5 分鐘一次、可關閉）；標頭的螢幕圖示可把畫面文字摘要（標題、警示、分頁、表格前幾列、表單值、按鈕；不含密碼欄）附在之後的提問；相機圖示把此頁截圖（JPEG、最長邊 1600）附在下一則提問給看得懂影像的 LLM。
- 助手有長期記憶（每位使用者自己的）：「記住：…」存事實、「忘記：…」刪除，或在記憶面板（大腦圖示）管理；每則回答可評分，相似問題會把評過好的舊回答當範例，離線時幾乎同一題直接用舊回答。
- **響應式**：手機寬度側欄改抽屜、麵包屑精簡、表格只留主要欄位、編輯器只留畫布（參數走工具頁）、觸控目標放大；桌面／平板／手機三種寬度與深淺主題都經 Playwright 稽核。
- **視覺設計**：品牌標誌（取景框＋鏡頭）貫穿側欄、登入頁與 favicon；登入頁品牌柔光背景；標題階層、表格動作欄位置、時間格式、空狀態與 toast 位置全站一致。
- **上手引導**：流程還沒選影像來源時編輯器直接給下拉選；總覽卡一鍵「執行一次」；教導完成一鍵建立使用該模型的流程；批次影像集建立即跑第一次；工具頁「改參數即重跑」開關；取像步驟側欄直接選來源並看預覽縮圖；來源表單儲存前可「測試擷取」；離開未儲存的確認改為平台風格對話框。
- AI 代理技能（`apps/vision/agent/skills/*.md`）：平台規則、設計原則、每工具要領，AI 讀的與「AI 技能」視窗看到的是同一份。詳見 `docs/agent.html`。

### 深度學習教導（`/dl`）

- **YOLO 訓練（四種）**：物件偵測（bbox）、實例分割（polygon）、影像分類（classes）、旋轉框 OBB（polygon 取最小外接旋轉矩形）；ultralytics 訓練、進度／曲線／log 回報、可中止；產物 best.pt（主，給 ai_* 工具）＋ONNX（副，給 dl_* 工具）兩個資產。
- **SAM2 智慧標記**：點擊（正／負點）、拖曳框選、沒有模型時的「SAM 全圖提案」；權重 `VISION_SAM_MODEL`（預設 sam2.1_t.pt）自動下載，失敗退回 mobile_sam。
- **依賴**：`requirements-dl.txt`＋`scripts/setup_dl.ps1`（先 torch cu128 再 ultralytics；onnxruntime-gpu 鎖 1.22 配 CUDA 12；處理器加速 runtime 與其他 onnxruntime 套件互斥）＋`manage.py dl_check --predict` 驗證；踩坑清單見 docs/dl.html §11。
教導專案 → 樣本（上傳／zip／從來源連抓／匯入資料集，像素 SHA256 去重）→ 標記（分類點選；分割多邊形／矩形，SAM 智慧選取，自動標記）→ train/val/test 分割與資料集版本凍結 → 伺服端訓練（內建分類／輕量語意分割；YOLO-seg 選裝 ultralytics；曲線與 log、可中止）→ 模型匯出到資產庫給 DL 工具使用。詳見 `docs/dl.html`。

### 影像來源與資產
**擷取端相機**（webcam／Basler／IDS，由擷取端程式驅動）、資料夾（循環）、單檔、上傳、合成影像；folder／file 可用伺服器檔案瀏覽器選路徑。資產：範本影像、ONNX 模型、標定、資料集 zip。流程匯出可選擇把引用的資產一併內嵌，匯入時以 sha256 去重並把流程圖裡的資產 id 換成本機 id。兩者皆可群組分類。

### 擷取端（相機在別台電腦或需要廠牌 SDK）
- 可從網頁下載的 Windows 桌面程式（`vscapture/`，PySide6，PyInstaller 打包）：在相機所在的電腦驅動網路攝影機／Basler（pypylon）／IDS（ids_peak）／uEye／模擬相機，**主動連到伺服端擷取埠 9100**登記名稱與通道；多通道、即時預覽、ROI 圈選只傳 ROI（支援硬體 ROI）、相機參數自動表單並可存檔、傳送設定（不壓縮／LZ4／JPEG、單色、縮小、依需求取像／連續串流、測試傳送）、記錄、系統匣、無介面常駐。
- 同一台電腦走**共享記憶體**（一條連線一個區段、FRAME 訊息通知、伺服端 copy 一次後歸還槽），跨電腦走**單一持久 TCP**（定長二進位表頭、req_id 多工、raw 直接 `recv_into` 進 ndarray、LZ4 無損）。**2000 萬畫素彩色（59.9 MB／張）實測 117 fps**（緩衝池重用、`np.copyto` 放開 GIL、RAW 零複製送出）；跨電腦受網路頻寬限制，見 `docs/capture-client.html` §7、`scripts/bench_capture.py`。
- **自動更新**：伺服端重新建置後，已連線的擷取端收到通知，可自動從同一條已驗證的連線分塊下載安裝檔（驗 SHA-256）、解壓後由新版接手覆寫並重啟；設定為不檢查／通知我／自動安裝。
- **介面**：繁體中文／简体中文／English（與網頁相同三種語言）與深色／淺色主題，即時切換並記住；相機參數以樹狀圖分組展開（含搜尋）；視窗可自由縮放，版面依寬度重排成三欄／兩欄／單欄。
- **省電**：視窗縮到工作列且伺服端一段時間沒有要求取像時自動停止取像（相機仍開著，下次要影像自動恢復）；實測 2000 萬畫素 30 fps 由 13% CPU 降到 0%。
- 網頁：影像來源類型「擷取端相機」（下拉選擷取端與通道、模式、逾時、要求新影格、編碼；狀態欄顯示在線／離線／fps／最近影格），「外部整合」→「擷取端」分頁（下載、已連線的擷取端、串流開關、預覽）。建置：`scripts/build_capture_client.ps1`（`-WithBasler`／`-WithIds`）。詳見 `docs/capture-client.html`。

### 自動化整合
- HTTP：`POST /api/vision/flows/{id}/run`（可附影像、指定配方、同步／非同步）。
- TCP：一行指令 `RUN <flow> [recipe=…]` 回一行 JSON（同行程）；`RUN <flow> fmt=<輸出>` 回純文字給讀不了 JSON 的設備（流程裡用 `format_text` 排版）；`VARS`／`SET` 讀寫變數（換線送料號、重置計數）。
- 變數與看板 API：`GET/PUT /flows/{id}/variables`、`/vision/variables`；`GET /flows/{id}/board` 一次拿齊看板要顯示的一切（公差判定已算好），整合端自建畫面用它。
- SSE：即時事件串流；總覽頁可觀看任一流程的即時影像與結果。
- Modbus TCP／TCP 文字／模擬 DIO 主動輸出（`write_modbus` 工具，失敗降級不停線）。
- **Modbus 主站與從站**：`modbus_tcp` 平台連到 PLC 去讀寫；`modbus_server` 平台開埠（預設 5020）讓 PLC 當主站來讀寫平台的暫存器。流程工具 `write_modbus`（寫判定／量測值）與 `read_modbus`（讀料號／觸發旗標，可併進具名輸出）。
- **觸發規則表**：一條連線一張表，每一列是「設備做了什麼 → 平台做什麼」。來源是位址的值（變成非零／變回零／值變了／等於／進入範圍）或收到的一行文字（整行等於／包含／開頭是／樣式），動作是執行流程、換配方、存變數、鎖住或解除硬體。一輪只讀一次，十條規則與一條一樣輕。舊的單一觸發設定照樣讀得懂。
- **結果回送**：流程設定裡選一條連線、寫下 OK 與 NG 各要送什麼，跑完就送出去，不必在畫布上接線；樣板名字與「格式化回覆」同一套。逐片同步送，不會漏掉任何一片。
- **設定複製**：整份通訊設定（連線、觸發規則、接收規則）可以匯出成一個檔案再匯入到另一台；密碼在離開伺服器前就遮掉，匯入時還原成該台原本的值。
- **事件回報與心跳**：平台起來了、流程忙／閒、相機上下線、硬體被鎖住，選中的事件一發生就主動送一行給上位機；心跳讓對方知道這一站還活著（Modbus 連線寫的是遞增計數，就是 PLC 的看門狗）。逐片結果不走這條，接在流程裡才不會漏。
- **接收規則**：條碼機或舊上位機只送一行文字（不是指令）也能觸發——在「整合 ▸ TCP ▸ 接收規則」比對，抓到的料號可以帶進流程，回覆可設成純文字。
- **整合頁**：每一種整合方式都是獨立頁面（`/integration/http|tcp|events|modbus|capture`），側欄可展開成樹狀；**連線由用到它的整合頁自己管理**（Modbus 頁管 Modbus 主站／從站／模擬 DIO，TCP 頁管上位機 TCP 與外掛輸出），回傳格式與錯誤碼在 HTTP 頁、TCP 失敗碼在 TCP 頁；每頁下方有**命令與結果**即時追蹤（時間、方向、耗時、完整內容），便於除錯。
- 引擎鎖定：整合方以 HTTP（`POST /vision/lock`）或 TCP（`LOCK`／`UNLOCK`）鎖定，使用者只能編輯不能執行；鎖定期間網頁上方橫幅顯示持有者與原因。詳見 `docs/automation.html`、`docs/modbus.html`。

### 帳號、介面與文件
- 管理員／一般使用者／整合方（API 金鑰）三種身分；流程有擁有者；每人各自的介面偏好（主題：淺色／深色／Cyberpunk／跟隨系統；語系：繁中／簡中／英文）。
- 用詞依商用產品規範（`docs/glossary.html`），前端測試自動擋口語詞。
- 文件一律 HTML 在 `docs/`（無外部依賴，可離線閱讀）。

---

## 架構

```
                 瀏覽器（React SPA，lazy 分頁 chunk）
                 └── lib/api.ts (BASE_URL=/api 或 VITE_API_BASE_URL) ── lib/flowStream.ts (SSE)
                          │ HTTP / SSE
┌─────────────────────────┴──────────────────────────────────────────────┐
│ 單一 API 行程（uvicorn workers=1；manage.py serve 同時開 TCP 介面）      │
│                                                                        │
│  config/api.py  ── NinjaAPI，掛載各 app 的 Router                       │
│  apps/accounts  ── 身分（Principal：user / integrator / bootstrap）、鎖定 │
│  apps/vision    ── models / graph（驗證、編譯）/ engine（執行 DAG）        │
│                    runner（執行緒池、compile 快取、背景持久化）           │
│                    images（行程內影像快取，LRU + run 輪替，pinned）       │
│                    stream（SSE bus）/ tcp_server / sources（grabbers）    │
│                    tools/（Tool 框架＋145 內建）/ dl/（教導與訓練）        │
│                    agent/（AI 助手：分析→意圖→合成→試跑；LLM 供應器）      │
│  apps/comm      ── Modbus／TCP 主動輸出（Writer）                         │
│  apps/golden    ── Golden Set 回歸                                        │
│  apps/vision/capture ── 擷取端 hub（:9100，每個擷取端一條執行緒）＋ CaptureGrabber │
│  plugins/       ── 資料夾外掛（Tool／Grabber／Writer／Trainer 自動掛載）   │
└────────────────────────────────────────────────────────────────────────┘
        │ SQLite（預設；DATABASES 可換）    │ data/assets、data/samples（檔案）
```

### 執行路徑（一次檢測）
1. 觸發：HTTP `run`／TCP `RUN`／連續執行／編輯器試執行。
2. `Runner.compiled_for(flow, recipe)`：`validate_graph` → `apply_recipe` → `compile_graph`（快取鍵 `(version, recipe_id, updated_at)`）。
3. `Runner._prefetch()` 在呼叫者執行緒開好來源與資產（熱路徑不碰 DB）。
4. 執行緒池的一條執行緒：`engine.execute()` 依拓樸順序跑每個節點——`ToolContext.image()` 依 `accepts` 做位深 coerce、`_flow` 分支決定是否執行、影像輸出進 `images.store`、overlays 只是顯示層 metadata。
5. `RunReport` → SSE 事件、統計、背景批次寫 `FlowRun`（可關）；前端以 ref 取縮圖。

### AI 助手路徑
上傳影像（pinned 快取）→ `analysis.analyze`（ROI 特徵）→ `clarify`（規則或 LLM 提問）→ `intents.parse`＋`synth.synthesize`（或 `llm.generate`）→ `validate_graph` → `trial_run`（`engine.execute` 直跑、不佔執行緒池、不落 DB）→ 回 graph／rationale／reports／warnings。

---

## 程式碼地圖

### 後端（`apps/`，約 17.6k 行 Python）

| 路徑 | 職責 |
|---|---|
| `config/settings.py` | 全部設定走 `.env`；`VISION` dict 是引擎／快取／外掛／AI 助手的單一設定來源 |
| `config/api.py` | NinjaAPI 根、錯誤格式、各 Router 掛載順序（`/flows/import` 類固定路徑先於 `/flows/{id}`） |
| `apps/core/errors.py` | API 錯誤型別（`ValidationError`／`NotFound`／`Conflict`／`PermissionDenied`…）與統一 JSON |
| `apps/core/plugins.py` | 資料夾外掛掃描與掛載 |
| `apps/accounts/security.py` | `Principal`、`principal(request)`、`can_execute()`（鎖定時 423）、API 金鑰 |
| `apps/accounts/models.py` | `UserPref`（ui 偏好、agent 供應商設定）、`AuthToken`、`EngineLock` |
| `apps/vision/models.py` | `Flow`／`FlowRecipe`／`FlowRun`／`ImageSource`／`FlowTemplate`／`ResourceGroup`／`Asset`／DL 模型群 |
| `apps/vision/graph.py` | graph JSON 驗證（`validate_graph`）、舊工具名映射 `LEGACY_TOOL_TYPES`、編譯 `compile_graph` |
| `apps/vision/engine.py` | DAG 執行、`RunReport`／`NodeReport`、隱含埠（`_flow`／`_overlays`／`_image`） |
| `apps/vision/runner.py` | 執行緒池、每流程 runtime／統計、compile 快取、背景持久化、連續執行 |
| `apps/vision/images.py` | `ImageStore`（LRU、每流程 run 輪替、pinned、編碼快取） |
| `apps/vision/api*.py` | 主 API（flows／sources／assets／groups／fs／runs／preview…）、範本與批次（api_more）、配方（api_recipes）、匯出入（api_flowio） |
| `apps/vision/stream.py`、`tcp_server.py` | SSE bus 與 TCP 一行指令介面 |
| `apps/vision/tools/base.py` | `Tool`／`Param`／`Port`／`ToolContext`／`Result`、封閉集合 `PARAM_KINDS`／`PORT_TYPES`、`catalogue()` |
| `apps/vision/tools/roi.py`、`imgfmt.py` | ROI 全形狀 helper（crop／mask／overlay／transform）、位深轉換 |
| `apps/vision/tools/builtin/*.py` | 內建工具依類別分檔（source／preprocess／locate／measure／detect／logic／output／dl／modbus） |
| `apps/vision/sources/grabbers.py` | 影像來源：folder／file／usb／upload／synthetic／外掛 |
| `apps/vision/capture/` | 擷取端伺服端：`hub.py`（CaptureHub／ClientSession、共享記憶體附加）、`grabber.py`（`CaptureGrabber`、`channel_status`）、`api.py`（clients／preview／stream／download） |
| `vscapture/` | 擷取端桌面程式（不 import Django）：`protocol.py`（雙方共用）、`config`／`frames`／`channel`／`engine`／`shm`／`app`、`cameras/`（webcam／basler／ids／ueye／fake）、`transport/`、`ui/`（PySide6）；打包 `scripts/capture_client.spec`＋`build_capture_client.ps1`＋`package_capture_client.py` |
| `apps/vision/dl/` | Trainer registry（`base.py`）、內建 trainer、訓練 job、裝置／provider、SAM、YOLO 互轉、ONNX 輸出 |
| `apps/vision/agent/` | `analysis`／`intents`／`clarify`／`synth`（含候選方案、定位包裝）／`autotune`／`bench`／`llm`／`providers`（含工具呼叫 shim）／`actions`／`loop`／`jobs`（代理模式）／`memory`（工作階段、先驗）／`skills`（含自訂補充）／`service`／`api`＋`skills/*.md` |
| `apps/vision/demo.py`、`demo_images.py` | 範例樣板（`BUILTIN_TEMPLATES`）、合成樣本圖、`seed_demo` |
| `apps/comm/` | 連線模型與 Writer（Modbus TCP／TCP 文字／模擬 DIO／外掛） |
| `apps/golden/` | Golden 案例、基準、回歸 |
| `apps/vision/batch/` | 批次測試：`store`（檔案／序列化／淘汰）、`jobs`（背景執行）、`insights`（洞察與建議門檻）、`api` |
| `apps/vision/management/commands/` | `serve`、`seed_demo`、`flow export|import|run`、`run_tcp_server`、`regress`、`create_admin` |
| `tests/` | 26 個測試模組（引擎、工具純度與位深、API、smoke 掃描、範本實跑、AI 助手、DL、配方、Golden、外掛、通訊、擷取端、流程資產匯出、推論 providers…） |

### 前端（`frontend/src/`，約 21.5k 行 TS/TSX）

| 路徑 | 職責 |
|---|---|
| `App.tsx` | 路由（各頁 lazy chunk）、`RequireAuth` |
| `components/layout/` | `AppShell`（側欄／頂列／`Page` 容器）、全域搜尋 |
| `pages/` | Dashboard、Flows、FlowEditor、Tool、Teach、Stats、Golden、Batch、Sources、Assets、Dl、Agent、Integration、Users、Settings、Help、Login |
| `components/editor/` | 畫布（`FlowCanvas`／`ToolNode`／`FlowEdge`）、工具箱與選擇視窗、屬性面板、結果面板、`graphMapping.ts`（graph ⇄ React Flow） |
| `components/viewer/` | `ImageViewer`、`roiEditor.ts`（ROI 互動）、`geometry.ts`（ROI 幾何純函式）、Toolbar |
| `components/templates/`、`recipes/`、`dl/`、`auth/`、`ui/` | 範本畫廊、配方、DL 標記編輯器、登入／鎖定、共用 UI 元件 |
| `lib/api.ts`、`queries.ts`、`flowStream.ts` | 唯一的後端接縫：HTTP client（`BASE_URL`）、TanStack Query hooks、SSE |
| `lib/types.ts`、`ports.ts`、`graphValidation.ts`、`flowDraft.ts` | 型別（含 `Region` union）、埠顏色、連線檢查、跨頁草稿 store |
| `i18n/locales/` | en（正本與 fallback）、zh-Hant、zh-Hans；另有 `tools.zh-*.ts`（工具目錄）與 `catalogue.zh-*.ts`（來源／連線／訓練方式／範本）的對照字典 |
| `src/test/` | vitest：i18n 三語系對齊與用詞規範、原始碼不得寫死全形標點、頁面 render smoke、假後端 |

---

## 資料模型

| 模型 | 用途 |
|---|---|
| `Flow` | 流程：`graph` JSON、版本、擁有者、啟用、連續執行間隔、commissioned |
| `FlowRecipe` | 流程的參數覆寫組（配方），有預設配方 |
| `FlowRun` | 執行紀錄摘要（背景批次寫入，可關；每流程保留 N 列） |
| `FlowTemplate` | 自訂範本（`image_source.source_id` 以 `{SOURCE}` 佔位）；內建範本來自 `demo.BUILTIN_TEMPLATES` |
| `ImageSource` | 影像來源（kind／config／group） |
| `Asset` | 範本影像／模型／資料集檔案（`ASSET_DIR/<uuid>.<ext>`，group） |
| `ResourceGroup` | 來源庫／資產庫的群組（讓空群組可存在） |
| `DlProject`／`DlSample`／`DlDatasetVersion`／`DlSettings` | 深度學習教導：專案、樣本（標記、split、SHA256）、凍結版本、推論／訓練裝置設定 |
| `GoldenCase`／`GoldenBaseline` | 回歸案例與基準 |
| `Connection` | 主動輸出連線（Modbus 等） |
| `UserPref`／`AuthToken`／`EngineLock` | 介面偏好與 AI 供應商設定（金鑰不回前端）、登入 token、引擎鎖（單列） |

graph JSON 格式與埠合約見 `docs/contract.html`；**不改 graph 格式、不把 `Flow.graph` 搬出資料庫**是紅線。

---

## API 一覽

所有端點在 `/api/`，OpenAPI 於 `/api/docs`。身分：登入 token（`Authorization: Bearer`）或整合方金鑰（`X-API-Key`）；`<img>`／SSE 以 `?token=`／`?api_key=` 附帶。

| 群組 | 代表端點 |
|---|---|
| 帳號與鎖定 | `/auth/setup`、`/auth/login`、`/auth/me`、`/auth/prefs`、`/users`、`/vision/lock` |
| 流程 | `/vision/flows`（CRUD）、`/flows/{id}/run`、`/preview`、`/continuous`、`/recent`、`/runs`、`/stats`、`/events`（SSE）、`/scratch-image`、`/export`、`/flows/import` |
| 配方／範本／批次 | `/flows/{id}/recipes`、`/vision/templates`（builtin＋custom、instantiate）、`/flows/{id}/batch`、`/batch-source`（舊介面） |
| 批次測試頁 | `/vision/batch/sets`（＋`/from-source`、`/{id}`、`/images/{index}`、`/to-golden`、`/runs`）、`/vision/batch/runs/{id}`（＋`/cancel`、`/insights`、`/compare`、`/rows/{index}/preview`、`/to-recipe`）、`/vision/agent/consult` |
| Golden | `/flows/{id}/golden`、`/baseline`、`/regress` |
| 資源 | `/vision/sources`（含 `/kinds`、`/test` 儲存前測試擷取、`/preview`）、`/vision/assets`（含 `/from-image`、`/file`）、`/vision/groups`、`/vision/fs`、`/vision/images/{ref}` |
| 工具目錄與容量 | `/vision/tool-types`、`/vision/capacity` |
| 深度學習 | `/vision/dl/projects`、`/samples`、`/split`、`/dataset-export|import`、`/versions`、`/train`、`/train/status`、`/devices`、`/settings`、`/trainers`、`/sam` |
| AI 助手 | `/vision/agent/info`、`/settings`（＋`/test`、`/models`）、`/image`、`/clarify`、`/generate`、`/run`、`/refine`、`/edit`、`/tune`、`/autotune`、`/chat`、`/help/search`、`/jobs`（＋`/{id}`、`/cancel`、`/answer`）、`/sessions`（＋`/{id}`、`/restore`）、`/skills`、`/skills/custom/{key}`；`/flows/{id}/golden/autotune` |
| 整合 | `/vision/integration/info`、`/integration/tcp`、`/vision/connections` |
| 擷取端 | `/vision/capture/clients`（＋`/{name}/channels/{cid}/preview`、`/stream`）、`/vision/capture/download`（＋`/info`） |

執行類端點（run／preview／continuous／agent）在引擎鎖定時回 423；修改類端點要求擁有者或管理員。

---

## 執行模型與效能

- **只能有一個 API 行程**：引擎狀態、影像快取、SSE bus 都在行程內。`manage.py serve` = uvicorn workers=1 + TCP；`runserver` 只用來開發且要 `--noreload`。
- 執行緒池預設 10 個流程並行（`VISION_MAX_WORKERS`）；每流程一次一個 run，同一流程可同時等待的觸發數為 `VISION_MAX_QUEUE_PER_FLOW`（預設 16）。
- **產線化**：三級角色（管理員／工程師／操作員）＋**角色權限勾選**（管理員在使用者頁決定另外兩個角色能用哪些功能，伺服器端把關）、不良影像封存、流程版本歷史與發行標記、稽核軌跡、每小時良率彙總（永久保留）與 `backup`／`restore`／`purge`／`doctor`、`precision`（重複性／再現性／GR&R 報告，`--max-sigma`／`--max-grr` 當 CI 門檻） 維運指令。
- 熱路徑不碰資料庫；連續模式每 2 秒回 DB 確認一次。
- 影像快取：每流程保留最近 N 次 run（`VISION_KEEP_RUN_IMAGES`）；暫存上傳與 AI 助手影像 pinned 不佔名額；總量 LRU（`VISION_IMAGE_CACHE_MB`）；縮圖編碼另有 LRU。
- 引擎固定開銷每節點約 6 µs；示範流程 1280×960 全程約 8 ms（`docs/performance.html`）。
- 前端路由層級分割：主 bundle 約 466 KB，各頁獨立 chunk。

---

## 擴充點

| 想做什麼 | 怎麼做 |
|---|---|
| 新工具 | 繼承 `apps.vision.tools.base.Tool`，宣告 `params`／`inputs`／`outputs`，實作 `execute(ctx) -> Result`；內建放對應 builtin 模組的 `TOOLS`，外掛丟 `plugins/`。補 `tests/test_tools.py` 案例、`scripts/bench_tools.py`、`agent/skills/tools.md` 要領；現場參數標 `teach=True`。前端零修改 |
| 新影像來源／輸出連線 | 繼承 `Grabber`／`Writer`，丟 `plugins/`（或 `.env` 以 `kind=module:Class` 註冊） |
| 新 Trainer（模型種類） | 繼承 `apps.vision.dl.base.Trainer`，實作 `train()`／`suggest()`；UI 由 `/dl/trainers` 目錄驅動 |
| 新 AI 意圖 | `INTENT_KINDS`＋`intents.parse` 規則＋`synth.SYNTHESIZERS` 合成器＋`clarify.build_questions` 缺口問題＋測試 |
| 教 AI 場域知識 | 編輯 `apps/vision/agent/skills/{platform,design,tools}.md`，不用改程式 |
| 新 `Param.kind`／`Port.type`／ROI 形狀 | 後端封閉集合＋前端 `ParamField`／`types.ts`／`roiEditor.ts`／`geometry.ts`＋`catalogue()`＋docs 合約與名詞表同步 |
| 新主題 | `index.css` 加 `.theme-<id>` 變數覆蓋，`UI_THEMES`／`THEMES`／`index.html` 開機腳本三處同步 |
| 新頁面 | `pages/` + `App.tsx` lazy route + `AppShell` NAV + i18n 三語系 + `src/test/pages.test.tsx` smoke |

範例外掛：`plugins/example_dark_ratio.py`（工具）、`plugins/example_csv_writer.py`（輸出）。詳見 `docs/plugins.html`。

---

## 設定（.env）

複製 `.env.example` 為 `.env`；所有值都有預設。重點：

| 變數 | 說明 |
|---|---|
| `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`、`DATA_DIR`、`DB_PATH`、`BEHIND_HTTPS_PROXY`、`AUTH_TOKEN_TTL_HOURS` | Django 基本設定；資料（SQLite、資產、樣本）在 `DATA_DIR`（預設 `VS_HOME/data`）；反向代理後面設 `BEHIND_HTTPS_PROXY=1`；登入權杖壽命 |
| `VS_HOME`（環境變數） | 安裝根：發行版由樹的位置推得（`app/<ver>` 上兩層），開發＝專案根；`.env`、`data/`、`plugins/` 都在這裡 |
| `VISION_HTTP_PORT`、`VISION_TCP_AUTH`、`VISION_SSE_MAX_STREAMS` | serve 預設埠（doctor 也探它）、TCP 指令埠的 `AUTH <key>`（空＝不驗）、同時開的 SSE 串流上限（64；超過回 503） |
| `VISION_MAX_WORKERS`、`VISION_MAX_QUEUE_PER_FLOW`、`VISION_RUN_TIMEOUT_S` | 引擎並行與逾時 |
| `VISION_KEEP_RUN_IMAGES`、`VISION_IMAGE_CACHE_MB`、`VISION_PERSIST_RUNS`、`VISION_KEEP_RUN_ROWS` | 影像快取與執行紀錄 |
| `VISION_MEASUREMENT_LOG`、`VISION_MEASUREMENT_DAYS` | 量測值 SPC：具名數值輸出另存一年（統計頁「量測值」管制圖、總覽告警） |
| `VISION_ACCEL`、`VISION_ACCEL_MIN_PIXELS` | 前處理加速（auto／cpu／opencl／cuda）：只對 ≥ 4 MP 影像的重取樣／中值／卷積／FFT 走 OpenCL，實測理由見 docs/performance.html §5.7o |
| `VISION_PLUGIN_DIR`、`VISION_TOOL_PLUGINS`、`VISION_SOURCE_PLUGINS`、`VISION_COMM_PLUGINS` | 外掛 |
| `VISION_API_KEY`、`VISION_STATION_ID`、`VISION_TCP_HOST/PORT` | 整合方金鑰、站台識別、TCP 介面 |
| `VISION_CAPTURE_HOST/PORT`、`VISION_CAPTURE_AUTH`、`VISION_CAPTURE_MAX_FRAME_MB`、`VISION_CAPTURE_TIMEOUT_MS` | 擷取端擷取埠（預設 9100）、登錄金鑰（空＝沿用 API_KEY）、單張上限、預設逾時 |
| `VISION_BATCH_MAX_IMAGES`、`VISION_KEEP_BATCH_SETS`、`VISION_KEEP_BATCH_RUNS`、`VISION_BATCH_MAX_RUNNING` | 批次測試：影像集上限（200）、每流程保留影像集數（10）、每影像集保留執行次數（20）、同時執行數（2） |
| `VISION_AGENT_PROVIDER`、`VISION_AGENT_API_KEY`、`VISION_AGENT_MODEL`、`VISION_AGENT_BASE_URL`、`VISION_AGENT_TIMEOUT_S`、`VISION_AGENT_HELP_LOOKUPS`、`VISION_AGENT_MODE` | AI 助手伺服器預設供應商（使用者自己的設定優先；留空＝離線規則引擎；`BASE_URL` 給 Ollama 等 OpenAI 相容本地端點；`MODE`＝single／agentic） |
| `VISION_SAM_MODEL` | 深度學習教導的 SAM 權重（智慧選取／框選／全圖提案；sam2.1_t.pt 預設，mobile_sam.pt 較小、sam2.1_s.pt 更準） |
| `CORS_ALLOWED_ORIGINS` | 前端獨立部署時允許的來源 |

前端：`VITE_API_BASE_URL`（build 時設定，獨立部署用）、`VITE_PROXY_TARGET`（dev 代理目標）。

---

## 驗證與測試

```bash
# 後端：515 項（引擎、工具純度／位深、API、GET 端點 smoke、範例樣板實跑、AI 助手、DL、配方、Golden、角色權限、外掛、通訊、擷取端 hub 與擷取端程式）
.venv/Scripts/python.exe manage.py test --noinput
.venv/Scripts/python.exe -m ruff check apps tests config vscapture

# 擷取端：打包成 zip 供網頁下載（第一次會建 .venv-capture）；-WithBasler／-WithIds 一併打包 SDK
.\scripts\build_capture_client.ps1

# 擷取端傳輸效能（2000 萬畫素彩色，共享記憶體與 TCP）
.venv/Scripts/python.exe scripts/bench_capture.py

# 前端：型別、vitest（i18n 三語系對齊與用詞規範、原始碼不得寫死全形標點、純函式單元、頁面 render smoke）、build
cd frontend && npm run -s typecheck && npm test && npm run build

# 效能與等價性
.venv/Scripts/python.exe scripts/bench_tools.py
```

規則：改了優化過的函式要重跑等價性檢查；新增 GET 端點加進 `tests/test_smoke_api.py`；新頁面加 `src/test/pages.test.tsx` case；改文案不得出現禁用口語詞（測試會擋）。

---

## 部署

客戶電腦拿到的是**自帶 Python 的發行樹**（不需要裝 Python、不需要上網），細節在 `docs/deployment.html`：

| 產物 | 由誰產生 | 內容 |
|---|---|---|
| `VisionSequence-Setup-<ver>.exe`／`VisionSequence-<ver>-win64.zip` | `scripts/build_release.ps1`（Inno Setup 6 有裝才出 exe） | 內嵌 CPython 3.12＋全部 wheel、`apps/`、`config/`、`frontend/dist`（無 .map、預壓縮）、`docs/`、`scripts/{vsctl,install,service,proxy}.ps1`、`tools/{nssm,caddy,vc_redist}`、`examples/plugins/`、`capture-client/`、`release.json` |
| `VisionSequence-DL-cu128-<ver>.zip`／`-cpu-` | `scripts/build_dl_pack.ps1 -Cuda cu128`／`-Cpu` | torch、ultralytics、onnxruntime-gpu 的 wheel＋lock、YOLO11n／SAM2 權重、`dl-pack.json` |
| 擷取端 zip | `scripts/build_capture_client.ps1` | 相機電腦的桌面程式，隨發行樹發佈到 `data/downloads` |

客戶機的配置是三層：`<VS_HOME>\app\<ver>\`（不可變版本樹）＋ `current` junction ＋ `<VS_HOME>\{data,plugins,packs,certs,.env}`（升級不動）。安裝程式（或 `scripts\install.ps1`）產生 `.env`（`DEBUG=0`、隨機金鑰、絕對路徑）、先建管理員再開埠、NSSM 服務 `VisionSequence`（Ctrl-C 正常關閉、日誌輪替）＋ Caddy HTTPS 服務 `VisionSequenceProxy`（內建 CA 自簽／客戶憑證／無）、防火牆限子網。之後一律 `vsctl.cmd`：`status|logs|doctor|backup|restore|update <zip>|rollback|plugins install <zip>|dl install <pack>|env|admin create|firewall|certs`。

| 方式 | 前端 | 後端 |
|---|---|---|
| 客戶站台（發行版） | whitenoise 隨 API 行程服務（immutable `/assets`、`index.html` no-cache、預壓縮） | NSSM 服務 → uvicorn 127.0.0.1:8000，Caddy 443 在前 |
| 開發 | Vite dev server，`/api` 代理到 8000 | `scripts/dev.ps1` |
| 前端獨立部署 | build 時設 `VITE_API_BASE_URL=https://host/api`，放任何靜態主機 | `.env` 設 `CORS_ALLOWED_ORIGINS` |

- 單一行程是設計前提：不要開多個 worker 或多副本共用同一資料庫的引擎狀態；反向代理只能掛在 `/`（用主機名或埠分站台）。
- 其他客戶端電腦只要瀏覽器（Chrome/Edge 111+、Firefox 128+、Safari 16.4+）；語言與主題跟帳號、登出清掉使用者層的本機狀態、每站同時 64 條 SSE 串流、HTTPS 內建 CA 的 `certs\root.crt` 匯入一次。
- 可選依賴：`onnxruntime`（DL 推論；CPU、GPU 或處理器加速 runtime 只能留一個）、`ultralytics`＋`torch`（YOLO 訓練、SAM）、`anthropic`（Claude 供應器；GPT／Gemini 走標準庫 REST 零依賴）。缺件時對應功能提示安裝指令，其餘正常；客戶站台用 DL 加購包離線安裝。

---

## 文件地圖

> `docs/` 下 18 頁 **全部是英文**（`docs_style.py` 統一版面）。中文讀者請用瀏覽器的翻譯功能閱讀；之後也只維護英文版。

| 文件 | 內容 |
|---|---|
| `docs/index.html` | 總覽與索引 |
| `docs/user-guide.html` | 使用者手冊（圖文版）：依側欄順序逐頁說明，每節先放帶編號標記的截圖（`docs/img/`），標記對應下方清單指出按鈕與面板的位置——外框與導覽、帳號與權限、流程與範本、編輯器與工具選擇、工具頁與 ROI、參數卡與配方、執行與統計、批次測試、Golden Set、來源與擷取端、資產、深度學習、AI 助手頁與全域助手、整合頁、引擎鎖定、稽核／設定／說明、常見問題 |
| `docs/workflow-design.html` | 工作流程設計手冊 |
| `docs/architecture.html` | 設計手冊（資料模型、工具框架、引擎、Runner、API、前端、踩過的坑） |
| `docs/contract.html` | 前後端資料合約、graph JSON、錯誤碼、解耦部署 |
| `docs/automation.html`、`docs/modbus.html` | HTTP／TCP／SSE 整合、引擎鎖定；Modbus 主動輸出 |
| `docs/vision-capabilities.html` | ROI 種類、位深設計、檢測工具總覽 |
| `docs/samples.html` | 範例樣板與合成樣本圖 |
| `docs/agent.html` | AI 助手，分三部：全域助手（文件問答、看得到的現況、唯讀查詢與捷徑、主動提示、截圖、長期記憶、依批次資料調整）；在助手頁生成流程（詢問機制、多圖 ROI、候選與自動調參、定位補正、微調、代理模式、工作階段與先驗、供應商）；內部（架構、規則引擎、LLM、技能、API、基準、取捨） |
| `docs/dl.html` | 深度學習教導 |
| `docs/batch.html` | 批次測試：影像集、暫存結果、洞察與建議門檻、調參、AI 諮詢、API、保留策略 |
| `docs/golden.html` | Golden Set 與流程匯出入 |
| `docs/plugins.html` | 資料夾外掛 |
| `docs/capture-client.html` | 擷取端：安裝與連線、通道與 ROI、相機支援、共享記憶體與 TCP、網頁設定、效能、疑難排解、協定 v1、驗收清單 |
| `docs/deployment.html` | 部署與維運：安裝程式與三層配置、`vsctl`、NSSM 服務、埠與防火牆、HTTPS 與客戶端電腦、帳號與金鑰、備份還原、升級與回滾、現場外掛與 DL 加購包、監控、多站台、災難復原、資安、發行建置 |
| `docs/glossary.html` | 名詞規範與文案用詞規範 |
| `docs/performance.html` | 效能報告 |
| `CLAUDE.md` | 給 AI 協作者與開發者的專案須知：架構、慣例、驗證清單、踩過的坑、各模組要點 |

---

## 尚未實作

**伺服器端沒有通用 GenICam 來源**（擷取端另外支援 Basler／IDS／uEye 各自的 SDK）、**沒有單一登入（SSO）**、**沒有 PLC 專用協定**（Modbus 主／從站與外掛已足夠，客戶指名才以外掛形式做）。階段 4 硬體項目（相機曝光／增益動態控制、相機 IO、相機特徵寫入、多光源取像與融合）以假設備先行實作中，實機驗收待硬體到位。

AI 助手不自動生成需要模型、連線或寫檔副作用的工具（`dl_*`、`write_modbus`、`save_image`），需要時以註解提醒使用者。

> 標定（含手眼標定）、註冊式檢測（零訓練）、只教良品的異常檢測、快速註冊（H1b）與影像檢索分類（H2）**都已實作**，先前這一段把它們列為未實作是文件落後，已更正。
> 完整的未完成清單與排程在 `VM Help/分析/00-開發方案-對標VisionMaster.md` 的階段 2～4。
