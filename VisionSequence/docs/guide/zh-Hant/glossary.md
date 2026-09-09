# 詞彙表與命名規則

一件事只用一個名稱，在介面、程式碼與文件中保持一致。新增術語前請先放進此表。繁中欄位是 zh-Hant 介面使用的字詞，翻譯必須遵循。

## 頁面（側欄與路由） {#pages}

| 名稱 | 繁中 | 路由 | Component | 說明 |
|---|---|---|---|---|
| Dashboard | 總覽 | `/` | DashboardPage | 左側為流程卡片清單，中間為所選流程即時影像，右側為即時檢測明細。無事件時顯示最後一次執行並訂閱該流程 SSE。 |
| Flows | 流程 | `/flows` | FlowsPage | 流程清單 |
| Flow editor | 流程編輯器 | `/flows/:id` | FlowEditorPage | 畫布、影像檢視器與屬性檢查器 |
| Tool page | 工具頁 | `/flows/:id/tools/:nodeId` | ToolPage | 專用於調校單一步驟；左參數、中影像與參考資訊、右操作按鈕 |
| Image sources | 影像來源 | `/sources` | SourcesPage | 相機、資料夾、合成來源與使用者群組 |
| Assets | 資產 | `/assets` | AssetsPage | 樣板影像、模型檔與資料集封存 |
| Users | 使用者 | `/users` | UsersPage | 帳號管理 |
| Settings | 設定 | `/settings` | SettingsPage | key、主題、語言、引擎鎖與密碼 |
| Help | 說明 | `/help` | HelpPage | 定義與操作說明 |
| Sign in | 登入 | `/login` | LoginPage | 登入或建立第一位管理員 |
| Statistics | 統計 | `/flows/:id/stats` | StatsPage | 單一流程的執行歷史、良率、每小時 OK/NG 與耗時趨勢 |
| Batch test | 批次測試 | `/batch` | BatchPage | 影像集、批次執行、洞察、調校與比較 |
| Deep-learning teaching | 深度學習教導 | `/dl` | DlPage | 教導專案、樣本、標註、訓練與匯出 |
| AI assistant | AI 助手 | `/agent` | AgentPage | 影像、ROI 與 prompt 進來，可執行流程出去 |
| Golden Set | Golden Set | `/flows/:id/golden` | GoldenPage | cases、expectations、回歸與 baseline |
| Teach page | 教導頁 | `/flows/:id/teach` | TeachPage | 依步驟分組顯示流程中所有教導參數 |
| Integration | 外部整合 | `/integration/*` | IntegrationLayout | 每種整合方式一頁，側欄展開為樹狀 |

## 流程編輯器部件 {#editor}

| 名稱 | 繁中 | Component | 說明 |
|---|---|---|---|
| Toolbar | 工具列 | EditorToolbar | 流程名稱、儲存、範本、Recipes、預覽、連續執行、重設與說明 |
| Tool palette | 工具面板 | ToolPalette | 左欄上方的 Add tool、常用工具與工具選擇對話框 |
| Step menu | 步驟選單 | NodeContextMenu | 右鍵步驟可開工具頁、複製、停用、刪除或貼參數 |
| Recipe drawer | Recipe 抽屜 | RecipeDrawer | 管理 recipe 綁定、增刪改名、匯出匯入與 override |
| Save-scope checklist | 儲存範圍清單 | RecipeCheckList | 新增或儲存 recipe 前列出教導參數與其他參數 |
| Import check | 匯入檢查 | RecipeImportModal | 匯入 recipe 前顯示匹配與勾選清單 |
| Bound recipe | 綁定 recipe | BoundRecipeSelect | 目前執行時預設套用的 recipe |
| Navigation groups | 導覽群組 | AppShell | 檢測、教導、資源與外部整合群組 |
| Tree view | 樹狀檢視 | AssetTree | 資產與來源庫依 kind、group、item 列出 |
| Sidebar collapse | 側欄收合 | AppShell | 主選單在圖示與完整標籤間切換 |
| Panel | 面板 | Panel | 白底細框內容區，含標題列與操作圖示 |
| Template gallery | 範本圖庫 | TemplateGallery | 依類別分組的流程範本卡 |
| Step list | 步驟清單 | NodeList | 左欄底部列出流程所有步驟 |
| Image viewer | 影像檢視器 | ImageViewer | 中欄上方顯示影像、疊圖與 ROI 編輯 |
| Canvas | 畫布 | FlowCanvas | React Flow 畫布 |
| Inspector | 屬性檢查器 | Inspector | 右欄顯示流程設定或所選步驟基本資料 |
| Results panel | 結果面板 | ResultsPanel | 近期執行、輸出值、錯誤與警告 |
| Lock banner | 鎖定橫幅 | LockBanner | 引擎被鎖定時顯示的黃色橫幅 |

## 機器視覺詞彙 {#vision-terms}

| 術語 | 繁中 | 定義 |
|---|---|---|
| Image coordinate system | 影像座標系 | 原點在影像左上，x 向右、y 向下，角度順時針為正。 |
| Physical coordinate system | 實體座標系 | 工作台毫米座標或機台使用的數值；標定資產保存與影像座標間的轉換。 |
| Handedness | 手性 | 第二軸由第一軸轉向的方向；影像座標通常為 left-handed。 |
| Chiral consistency | 手性一致性 | 影像系統與機台系統是否同手性，站台建立時需檢查。 |
| Physical point | 實體點 | 由標定把像素轉成實體系統的點。 |
| Single pixel precision | 單像素精度 | 一個像素覆蓋的實際距離，通常為 `mm_per_px`。 |
| Pose | 姿態 | 物件的位置與旋轉，包含 x、y、angle。 |
| Teaching point | 教導點 | 良品上的參考位置或機台教導要去的位置。 |
| Run point | 執行點 | 本次執行中實際找到的零件位置。 |
| Line and line angle | 線與線角度 | 線由兩端點表示；角度自 +x 起算，順時針為正。 |
| Caliper | 卡尺 | 小型有方向矩形，將灰階投影到一軸以亞像素精度找邊。 |
| Detection area | 檢測區 | 步驟實際工作的區域，含 ROI、排除區與 ROI 跟隨後的位置。 |
| Mask | 遮罩 | 單通道影像，255 表示使用像素，0 表示忽略。 |
| Box | 框 | 由中心、寬、高與角度描述的矩形。 |
| Blob | 粒子 | 通過閾值的連通像素區段。 |
| Centroid | 質心 | 區域中像素或點的平均位置。 |
| Probability map | 機率圖 | 像素值表示結果強度而非亮度的灰階圖。 |
| Model | 模型 | 可指形狀模型、統計樣板或訓練網路；皆為資產。 |
| Colour space | 色彩空間 | 將顏色拆成數值的方式，如 RGB、HSV、Lab。 |
| Solution | 解決方案 | 此平台沒有單一 solution 檔；站台與其流程、來源、連線、設定共同備份。 |
| Industrial computer (IPC) | 工業電腦 | 機櫃內執行平台的無風扇 PC。 |
| Robot arm | 機械手臂 | 接收校正位置並執行動作的機台。 |

## 核心術語 {#terms}

| 術語 | 繁中 | 定義 |
|---|---|---|
| Flow | 流程 | 由節點與邊組成的一個檢測 graph。 |
| Node / step | 節點 / 步驟 | 畫布上的一個方塊，也是一個工具實例。 |
| Tool | 工具 | 面板中的種類，例如 grayscale、blob；`key` 是唯一識別。 |
| Edge | 邊 | 步驟間的連線，從輸出連接埠到輸入連接埠。 |
| Port | 連接埠 | 步驟左側為輸入、右側為輸出，各有型別。 |
| Flow handle | 流程把手 | 型別為 `flow` 的輸出，只能接到菱形控制輸入。 |
| Parameter | 參數 | 步驟設定，種類為封閉集合。 |
| Teaching parameter / teach page | 教導參數 / 教導頁 | 需在產線上調整的參數，標為 `teach=True`。 |
| Tolerance judge | 公差判定 | 以名目值與上下偏差判斷 pass/fail，並寫入 tolerances。 |
| Concentricity | 同心度 | 兩圓中心偏移；GD&T 同心度為偏移兩倍。 |
| OCR / OCV / taught font | OCR / OCV / 教導字型 | OCR 讀文字，OCV 驗證文字，教導字型針對點陣與雷刻字。 |
| Control chart (SPC) | 管制圖 (SPC) | 依執行順序繪製具中心線與管制界限的命名輸出。 |
| Cp / Cpk | Cp / Cpk | 描述製程相對規格帶與置中程度的能力指標。 |
| Nelson rules | Nelson 規則 | 判斷管制圖失控的八種型態。 |
| Repeatability / reproducibility | 重複性 / 再現性 | 同影像重跑或同零件重拍時量測值變動。 |
| Gauge R&R | Gauge R&R | 依 AIAG MSA 分解量測系統與零件變異的研究。 |
| Barcode grade | 條碼等級 | 條碼或 2D 符號的驗證器式品質等級 A 到 F。 |
| Unused error correction (UEC) | 未用錯誤修正 | 2D 符號解碼後尚未使用的錯誤修正容量比例。 |
| Quiet zone | 靜區 | 符號周圍必要空白邊界。 |
| Form and position tolerance | 形狀與位置公差 | ISO 1101 幾何公差。 |
| Minimum zone (MZC) | 最小區域 | 包住所有邊點的最窄同心圓環或平行帶。 |
| Photometric stereo | 光度立體 | 多方向照明求表面法線、曲率與 albedo。 |
| Circular caliper / run-out | 圓形卡尺 / run-out | 圍繞圓邊的徑向卡尺；run-out 為最大半徑減最小半徑。 |
| Wall thickness | 壁厚 | 一組成對外內邊之間的距離。 |
| Region / ROI | 區域 / ROI | 在影像上畫出的檢測範圍。 |
| Contour | 輪廓 | 二值影像中形狀外形的點列表。 |
| Convexity defect | 凸性缺陷 | 相對凸包向內凹陷的輪廓缺口。 |
| Polar unwrap | 極座標展開 | 將圓環展平成角度 x 半徑的長條。 |
| Anomaly detection / memory bank | 異常偵測 / 記憶庫 | 只用良品教導，以 patch feature 距離評分。 |
| Shape model / shape match | 形狀模型 / 形狀比對 | 以邊點與梯度方向做幾何比對。 |
| Statistical template | 統計樣板 | 多張良品對齊後建立的逐像素平均/標準差模型。 |
| Flat field / shading correction | 平場 / 陰影校正 | 用白參考與可選暗框移除照明不均。 |
| Composite region / exclusion zone | 複合區域 / 排除區 | 執行時由多個形狀 union/subtract/intersect 組成的區域。 |
| Overlay | 疊圖 | 工具畫在影像上的結果圖形，屬於 metadata。 |
| Run | 執行 | 流程完整或到某步的單次執行。 |
| Preview | 預覽 | 執行未儲存 graph 並保存中間影像，不寫歷史。 |
| Run once | 執行一次 | 執行已儲存 graph 一次並寫入歷史與統計。 |
| Continuous | 連續執行 | 以間隔重複執行。 |
| Scratch image | 臨時影像 | 只供預覽使用的上傳影像。 |
| Retention | 保留期限 | run detail、audit trail、measurements、archived pictures 等保存規則。 |
| Maintenance window | 維護時段 | 執行備份修剪、孤立圖片刪除與資料庫 compact 的時間。 |
| Fixed image | 固定影像 | `fixed_image` 工具，可將圖片存在流程中並作來源或參考。 |
| Image source | 影像來源 | 相機、資料夾、合成、pushed image 或 capture client camera 的定義。 |
| Capture client | 擷取端 | 安裝於相機 PC 的 vscapture 桌面程式。 |
| Channel | 通道 | capture client 中的一台相機設定。 |
| Capture source | 擷取來源 | `kind=capture` 的影像來源。 |
| On demand / stream | 隨選 / 串流 | 請擷取端拍新畫格，或讓它推送最新畫格。 |
| Shared memory | 共享記憶體 | 擷取端與伺服端同機時使用的影像傳輸路徑。 |
| Asset | 資產 | 樣板影像、ONNX 模型或資料集封存等檔案。 |
| Judge | 判定 | judge 工具產生的 OK/NG 結論。 |
| Named output | 命名輸出 | output 工具回傳給自動化系統的 key/value。 |
| Variable | 變數 | 流程在執行間保留的值。 |
| Board | 運行介面 | 流程的操作員畫面，顯示輸出、影像、今日計數與變數。 |
| Calibration | 標定 | 保存鏡頭校正與像素到實體映射的資產。 |
| Engine lock | 引擎鎖定 | 整合端持有硬體時，其他人可編輯但不可執行。 |
| Integrator | 整合方 | 以 API key 呼叫的自動化系統。 |
| Role | 角色 | administrator、engineer 或 operator。 |
| Role permissions | 角色權限 | 管理員在 Users 頁勾選 engineer/operator 可用功能。 |
| Reset | 重設 | 清除該流程的記憶體執行紀錄與統計。 |
| Template library | 範本庫 | 內建或自訂流程範本。 |
| Template | 範本 | 範本庫中的一個項目。 |
| Note | 註記 | graph 中不執行的裝飾節點。 |
| Batch test | 批次測試 | `/batch` 的調校工作台。 |
| Image set | 影像集 | 測試影像與每張 OK/NG 期望標籤的集合。 |
| Batch run | 批次執行 | 以 graph snapshot 對影像集執行一次。 |
| Insights | 洞察 | 命中率、混淆矩陣、缺失影像、失敗節點、閾值建議與輸出分布。 |
| Threshold suggestion | 閾值建議 | 由 expected-OK/NG 群組推得可一鍵套用的較佳閾值。 |
| Consult | 諮詢 | 詢問一個 batch run 的資料。 |
| Assistant dock | AI 助手停駐窗 | 右下角跨頁保留的聊天面板。 |
| Help answer | 說明回答 | 以文件段落與工具 skill 檢索後回答並引用來源。 |
| Assistant context | 助手情境 | 頁面登錄給全域助手的 graph、callback 與 batch run id 等資料。 |
| Agent session | 代理工作階段 | 一次 AI 助手產生的完整紀錄。 |
| Prior | 先驗 | 相似成功案例中的站台教導參數。 |
| Custom skill | 自訂 skill | 站台或個人的 AI skill markdown 補充。 |
| Agentic mode | Agentic 模式 | 助手以背景工作逐步 try、edit、verify、ask。 |
| Step timeline | 步驟時間軸 | agent job 的每個 action、reply、question 與完成紀錄。 |
| Candidate | 候選 | 主方案與規則引擎產生的參數變體。 |
| Image label | 影像標籤 | 上傳影像的期望 verdict，是候選排序與自動調校依據。 |
| Autotune | 自動調校 | 以資料驅動的 coordinate descent，只移動教導參數。 |
| Locate wrap | 定位包覆 | template match -> locate correction -> ROI follow。 |
| AI assistant | AI 助手 | 上傳影像、標 ROI、輸入 prompt，取得實際執行過的流程。 |
| Statistics | 統計 | 資料庫 KPI、每小時 OK/NG/failed、耗時趨勢與執行歷史。 |
| Hourly roll-up | 每小時彙總 | `FlowRunHourly` 每流程每小時一列，永久保存。 |
| Image archive | 影像封存 | 可選擇把 run images 寫到磁碟。 |
| Flow version | 流程版本 | 每次儲存 graph 的 snapshot。 |
| Audit log | 稽核記錄 | 誰在何時變更了什麼。 |
| Station | 站台 | 每次執行攜帶的 `VISION_STATION_ID`。 |
| Integration page | 整合頁 | 給 integrator 的介面參考與測試工具。 |
| Trace | 追蹤 | 整合頁底部即時 log。 |
| Modbus client / server | Modbus 用戶端 / 伺服端 | client 連到裝置；server 由平台監聽供 PLC 讀寫。 |
| Connection | 連線 | 對 Modbus TCP 或 host system 的 outgoing connection 定義。 |
| write_modbus | 寫入 Modbus | 依 mapping table 把 verdict、named output 或輸入值寫到連線。 |
| Favourites | 常用 | 工具面板中加星號的工具。 |
| Commissioned | 已投產 | `Flow.commissioned`，未投產流程會顯示 tag 並在執行報告警告。 |
| Recipe | Recipe | 一組流程參數 override。 |
| Override | 覆寫 | recipe 中的一個 `step.parameter = value`。 |
| Golden Set | Golden Set | 伺服端保存的 image cases 與 expectations。 |
| Golden case | Golden case | Golden Set 中的一張影像與期望結果。 |
| Regression | 回歸 | 執行所有 case 並與期望和 baseline 比較。 |
| Baseline | 基準線 | 儲存 regression 時每個 case 的結果。 |
| Regressed / improved | 退化 / 改善 | 與 baseline 比較後變差或變好。 |
| fail_under | fail_under | match_rate 低於此值時 regression 失敗。 |
| DL project | DL 專案 | 一個 trainer、類別清單與樣本集。 |
| Auto label | 自動標註 | `Trainer.suggest` 提出類別與信心值。 |
| Trainer | Trainer | 可訓練模型種類的註冊表。 |
| Shape workspace | 形狀工作區 | shapes mode 的標註工作區。 |
| Classify workspace | 分類工作區 | 分類專案的縮圖牆與全圖檢視器。 |
| Tool rail | 工具列軌 | 標註畫布左側的大圖示直列工具。 |
| Smart select | 智慧選取 | SAM 輔助標註：點選物件後產生多邊形。 |
| Smart box | 智慧框 | 拖框後 SAM2 回傳框內物件輪廓。 |
| SAM proposals | SAM 提案 | 無模型的自動標註，SAM2 分割全圖。 |
| Split | 分割 | `DlSample.split`：train、val、test 或 unset。 |
| Dataset version | 資料集版本 | 將樣本、標籤與 split 凍結成資產庫 zip。 |
| Augmentation | 資料增強 | 訓練期間擴增樣本。 |
| Dedupe | 去重 | 依解碼後像素 SHA256 略過重複樣本。 |
| dl_instance | DL 實例 | 實例分割 ONNX 推論工具。 |
| AI tools | AI 工具 | ai_detect、ai_segment、ai_classify、ai_pose、ai_obb。 |
| DL dependencies | DL 依賴 | 選用 torch、ultralytics 與 onnxruntime-gpu 安裝。 |
| Python script tool | Python script 工具 | `python_script`，由管理員儲存核准後執行。 |
| Plugin | 外掛 | 放入 `plugins/` 並自動載入的 .py 檔。 |
| Theme | 主題 | light、dark、cyber 或 system。 |
| Bit depth | 位元深度 | u8、u16 或 f32；工具未宣告時自動正規化到 u8。 |
| Manual write | 手動寫入 | 在 connections 頁送一組 JSON 值測試連線。 |
| Export / import | 匯出 / 匯入 | 匯出穩定序列化流程檔；匯入依名稱 upsert。 |

## 連接埠型別顏色（固定，不重用） {#port-colors}

| Type | 顏色 | 承載 |
|---|---|---|
| image | blue `#3b82f6` | 影像 |
| region | purple `#a855f7` | ROI |
| number | green `#22c55e` | 數字 |
| bool | orange `#f97316` | 布林 |
| string | yellow `#eab308` | 字串 |
| points | cyan `#06b6d4` | 點集 |
| contours | indigo `#6366f1` | 輪廓 |
| matches | pink `#ec4899` | match 與偵測結果 |
| list | teal `#14b8a6` | 一般 list，含疊圖 |
| any | grey-white `#cbd5e1` | 任意資料 |
| flow | grey `#94a3b8` (diamond) | 分支 |

## 狀態用語 {#status}

| 狀態 | 顏色 | 意義 |
|---|---|---|
| OK | green | 判定良品 |
| NG | red | 判定不良 |
| Failed | dark red border | 工具錯誤、逾時或無影像；步驟在畫布上顯示錯誤訊息 |
| Skipped | faded grey | 未走到的分支或上游失敗 |
| Running | pulsing border | 執行中 |

## 語氣 {#tone}

此產品是工業設備，介面文字應平實、精確、不口語。英文標籤與按鈕用 sentence case，不用驚嘆號，動作用祈使動詞。訊息要說明發生什麼與下一步。繁中遵循下表，簡中由此派生；`frontend/src/test/i18n.test.ts` 自動檢查禁用詞。

| 避免 | 使用 | 原因 |
|---|---|---|
| 口語點選說法 | 點選 | 動作動詞一致 |
| 臨時試行說法 | 預覽 / 試執行 | 區分未儲存 graph 與正式執行 |
| 口語空狀態 | 尚無 / 尚未 / 無 | 空狀態 |
| 限制口語 | 無法 / 不得 | 限制與驗證訊息 |
| 指示口語 | 此 / 此次 | 文件語氣較正式 |
| 口語擷取說法 | 擷取 / 偵測 | 影像取得與檢測用語分開 |
| 你 | 您 | 對使用者稱呼 |
| 口語檢測結果 | 誤判過多 / 漏檢 | 描述檢測結果 |
| 口語連接與套用 | 連接 / 校正 / 套用 | 工業文件用語 |

AI 助手的範例 prompt 可保留口語；其他介面、說明頁與文件都遵循此表。
