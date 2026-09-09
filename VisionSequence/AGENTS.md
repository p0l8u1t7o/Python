# AGENTS.md — 給 Codex（與其他被派工的 AI 代理）的守則

> 這一份是派工時的**硬性規定**，每次開工先讀完；細節與專案全貌在 `CLAUDE.md`（同目錄），兩份衝突時以本檔為準。
> 另一位工程師（Claude）負責審 diff、獨立驗證、整合與 commit；你只做被指定的那一塊。

## 1. 紅線（違反就整批退回）

- **不重寫引擎、不改 graph JSON 格式、不把 `Flow.graph` 搬出資料庫、不引入 Node.js 服務／微服務、不開第二個 API 行程。**
- **只能改派工提示詞列出的檔案**；需要動清單以外的檔案（含 `models.py`、migration、`requirements*.txt`、`CLAUDE.md`、`README.md`、`scripts/bench_tools.py`）就**停下來回報**，不要用 fallback 繞過（例如把 model 塞進 api 檔、把測試合併去躲守門）。
- **不要 git add／commit／stash／checkout／restore／update-index**，也不要對沒改過的檔案做「換行正規化」或格式化——工作樹的每一個變動都要是你被要求的內容。寫入被拒、唯讀沙盒、上游容量錯誤就立刻回報。
- **不碰未追蹤的目錄**（`frontend/ui-audit/`、`logs/`、`build/`、`data/`）。
- **產品表面一律英文，且不得出現技術來源與廠商字樣**（OpenCV／cv2／NI Vision／YOLO／ultralytics／SAM／NVIDIA／OpenVINO 等）：工具目錄的 label／description／help_text／選項、`ToolError`／`APIError`／`Result(message=)`、前端字典、`docs/`。技術名稱只留在程式碼註解與模組名。`tests/test_product_surface.py` 會掃。
- **程式碼註解與 docstring 用繁體中文**，識別字與術語保持英文；測試斷言用英文。
- **不新增第三方依賴**，除非提示詞明說。
- 熱路徑（執行緒池內、`ToolContext` 內、連續模式迴圈內）**不碰資料庫**；工具**不得就地修改輸入 ndarray、overlays 不得畫進影像**。

## 2. 之前犯過、不准再犯的錯

1. **只在 bench 尺寸驗等價性**：bench 的 1280×960 與 640×480 都是偶數且 DFT 最佳尺寸；`fft_filter` 第一版在那裡全綠，333×97 卻差 11 灰階。改優化過的函式一律另外用**奇數尺寸、全部模式／樣式／位深**比對舊實作（`tests/test_perf_equivalence.py` 的做法：保留舊實作的純函式副本逐像素比）。
2. **為了躲文件數字守門去合併測試**（`test_docs_claims` 的測試數容差）：守門紅了就回報「數字要更新」，不要改測試結構讓它變綠。
3. **模型寫進 api 檔當 fallback**（沙盒寫不進 `models.py`）：寫不進去就回報，模型一律放 `models.py` 並附 migration。
4. **對沒改過的檔案做換行正規化**（`detect.py` 被標成 modified，還去跑 `git update-index`）：不要碰 git，不要動別人的檔案。
5. **執行緒池熱路徑打資料庫**（並行度閘門的 wait 迴圈每 50 ms 查一次 `Flow`，實測 17 次／秒）：容量放記憶體欄位，由呼叫者執行緒更新。
6. **1 維佔位陣列存進流程變數**（`np.empty((0,))`）把看板／變數／儀表板端點全部打成 500：流程變數只存純量與清單，影像用 `None` 佔位。
7. **產品表面出現模型名稱**（「SAM」「OpenCV threads」「cv2.HoughCircles」）：見紅線。
8. **缺資產時直接 `Path(None)`**（`ctx.asset_path` 查不到是回 None 不是丟例外）：一律先擋，回 `ToolError` 指出缺哪個資產。
9. **選填文字屬性的空字串被當「必填沒填」丟掉整個 widget**：只有 `required` 的欄位才要求非空，並補「每種 widget 存得進去又讀得回來」的測試。
10. **測試直接呼叫 OpenCV 而不是平台的函式**（標定板測試呼叫 `cv2.findCirclesGrid` 全綠，平台自己的 `calib.find_board` 卻讀不到）：測平台的入口，不測底層函式庫。
11. **量測數字不同環境比對**（bench 結果字串含 `DATA_DIR` 路徑）：前後比對用同一個 `DATA_DIR`、同一台機器、同一組執行緒設定，數字要寫進回報。
12. **實作在別的檔案就放棄**（`contour_find` 在 `contours.py` 不在 `detect.py`）：發現檔案不在允許清單就回報請求加入，不要靜默略過或硬改。
13. **在網路讀取執行緒上同步等相機**（擷取端第一版在 vsc-net 執行緒處理 `CHANNEL_SET`、`Channel.call()` 等相機結果，通道 a 改參數卡 800 ms 時通道 b 的取像延遲 743 ms）：任何會等相機、等磁碟、等別的執行緒的訊息都丟給背景執行緒處理，收訊執行緒只做分派；驗證時要量「別的通道有沒有被拖住」，不能只看命令本身成功。
14. **新工具的測試只直接呼叫 `execute()`，沒走圖驗證接線**（`multi_light_grab.images` 是 `list`，融合與光度立體的 `images` 是 multiple 影像埠，執行層吃得下但 `graph.validate_graph` 擋掉，畫布上接不上線，測試卻全綠）：新增工具或新埠時，至少一條測試要用 `validate_graph` 把上下游真的接起來，跨工具的資料型別要在圖驗證那一層證明相容。
15. **選填輸入埠沒接時靜默放行**（`edge_filter` 的影像埠設成選填，沒接就沒有寬高，碰下邊的物體被當成沒碰、kept=1，測試只測了有接影像的情況）：一個埠沒接會讓判斷失效時，要嘛設必接、要嘛 `ToolError` 講明，絕不能靜默回「沒問題」；每條「排除」邏輯的測試都要涵蓋輸入缺席的情況。
16. **包裝框架內部函式時自己補關鍵字參數**（TorchScript wrapper 退回時呼叫 `module(im, augment=…, visualize=…, embed=…)`，8.4.137 的 `BaseModel.predict` 已沒有 `visualize`，換一種影像尺寸就炸；且 wrapper 只記最後一種輸入形狀）：退回原路徑一律**原樣轉傳**呼叫者給的 `*args, **kwargs` 給**原本被換掉的函式**，不要重組簽名；依輸入形狀快取的東西要用「形狀 → 結果」表，並用兩種不同尺寸交替呼叫驗證。

## 3. 開工前必讀、做完必跑

- 先讀：`CLAUDE.md`「工作方式」與「模組要點」裡與本次相關的段落；提示詞列的「事實來源檔案（只讀）」。
- 新工具 checklist（CLAUDE.md）：`TOOLS` 登錄 → `tests/test_tools.py` 至少一案例 → `scripts/bench_tools.py` 加一筆（**只能加，不能改既有案例**）→ 現場會調的參數標 `teach=True`（`test_teach_params_marked` 的集合要跟著改）→ `agent/skills/tools.md` 補一段 → `tools.zh-Hant.ts`／`tools.zh-Hans.ts` 補中文 → 需要的話加範例樣板。
- 改既有工具：**既有參數、預設值、輸出埠、訊息一字不變**（bench 結果字串 0 差異），新功能一律加參數且預設值＝舊行為。
- 測試一律用專案外的資料目錄：`$env:DATA_DIR="$env:TEMP\vs-codex-testdata"`；跑測試與 bench 時不要同時跑別的 Python 程序。
- 做完自己跑並把**實際輸出**貼進回報：`.venv\Scripts\python.exe manage.py test --noinput`（全套）、`.venv\Scripts\python.exe -m ruff check apps tests config vscapture`、動到工具就跑 `scripts\bench_tools.py`、動到 docs 就跑 `scripts\docs_style.py --check`、動到前端就 `cd frontend; npm run -s typecheck; npx vitest run; npm run build`。
- 回報用繁體中文：改了什麼（逐檔）、為什麼、測試與量測的實際數字、放棄了什麼與原因、有沒有偏離提示詞。**不要宣稱沒跑過的驗證。**
