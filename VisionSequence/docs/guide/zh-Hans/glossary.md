# 词汇表与命名规则

一件事只用一個名稱，在介面、程序碼与文件中保持一致。新增術語前請先放進此表。简中欄位是 zh-Hans 介面使用的字詞，翻譯必須遵循。

## 页面（侧栏与路由） {#pages}

| 名稱 | 简中 | 路由 | Component | 说明 |
|---|---|---|---|---|
| Dashboard | 总览 | `/` | DashboardPage | 左側為流程卡片清單，中間為所選流程即時图像，右側為即時检测明細。無事件時显示最后一次执行並訂閱該流程 SSE。 |
| Flows | 流程 | `/flows` | FlowsPage | 流程清單 |
| Flow editor | 流程编辑器 | `/flows/:id` | FlowEditorPage | 畫布、图像檢視器与屬性檢查器 |
| Tool page | 工具页 | `/flows/:id/tools/:nodeId` | ToolPage | 專用於調校單一步骤；左参数、中图像与參考資訊、右操作按鈕 |
| Image sources | 图像来源 | `/sources` | SourcesPage | 相机、数据夾、合成来源与用户群組 |
| Assets | 资产 | `/assets` | AssetsPage | 樣板图像、模型檔与数据集封存 |
| Users | 用户 | `/users` | UsersPage | 帳號管理 |
| Settings | 设置 | `/settings` | SettingsPage | key、主題、語言、引擎鎖与密碼 |
| Help | 说明 | `/help` | HelpPage | 定义与操作说明 |
| Sign in | 登录 | `/login` | LoginPage | 登录或建立第一位管理員 |
| Statistics | 统计 | `/flows/:id/stats` | StatsPage | 單一流程的执行历史、良率、每小時 OK/NG 与耗時趨勢 |
| Batch test | 批量测试 | `/batch` | BatchPage | 图像集、批量执行、洞察、調校与比較 |
| Deep-learning teaching | 深度学习教导 | `/dl` | DlPage | 教导项目、样本、标注、训练与导出 |
| AI assistant | AI 助手 | `/agent` | AgentPage | 图像、ROI 与 prompt 進來，可执行流程出去 |
| Golden Set | Golden Set | `/flows/:id/golden` | GoldenPage | cases、expectations、回歸与 baseline |
| Teach page | 教导页 | `/flows/:id/teach` | TeachPage | 依步骤分組显示流程中所有教导参数 |
| Integration | 外部集成 | `/integration/*` | IntegrationLayout | 每種整合方式一页，侧栏展開為樹狀 |

## 流程编辑器部件 {#editor}

| 名稱 | 简中 | Component | 说明 |
|---|---|---|---|
| Toolbar | 工具列 | EditorToolbar | 流程名稱、保存、模板、Recipes、預覽、連續执行、重設与说明 |
| Tool palette | 工具面板 | ToolPalette | 左欄上方的 Add tool、常用工具与工具選擇對話框 |
| Step menu | 步骤選單 | NodeContextMenu | 右鍵步骤可開工具页、複製、停用、删除或貼参数 |
| Recipe drawer | Recipe 抽屜 | RecipeDrawer | 管理 recipe 綁定、增刪改名、导出导入与 override |
| Save-scope checklist | 保存範圍清單 | RecipeCheckList | 新增或保存 recipe 前列出教导参数与其他参数 |
| Import check | 导入檢查 | RecipeImportModal | 导入 recipe 前显示匹配与勾選清單 |
| Bound recipe | 綁定 recipe | BoundRecipeSelect | 目前执行時默认套用的 recipe |
| Navigation groups | 導覽群組 | AppShell | 检测、教导、資源与外部集成群組 |
| Tree view | 樹狀檢視 | AssetTree | 资产与来源庫依 kind、group、item 列出 |
| Sidebar collapse | 侧栏收合 | AppShell | 主選單在圖示与完整標籤間切換 |
| Panel | 面板 | Panel | 白底細框內容區，含標題列与操作圖示 |
| Template gallery | 模板圖庫 | TemplateGallery | 依类別分組的流程模板卡 |
| Step list | 步骤清單 | NodeList | 左欄底部列出流程所有步骤 |
| Image viewer | 图像檢視器 | ImageViewer | 中欄上方显示图像、疊圖与 ROI 编辑 |
| Canvas | 畫布 | FlowCanvas | React Flow 畫布 |
| Inspector | 屬性檢查器 | Inspector | 右欄显示流程设置或所選步骤基本数据 |
| Results panel | 結果面板 | ResultsPanel | 近期执行、输出值、错误与警告 |
| Lock banner | 鎖定橫幅 | LockBanner | 引擎被鎖定時显示的黃色橫幅 |

## 机器视觉词汇 {#vision-terms}

| 術語 | 简中 | 定义 |
|---|---|---|
| Image coordinate system | 图像座標系 | 原点在图像左上，x 向右、y 向下，角度順時針為正。 |
| Physical coordinate system | 实体座標系 | 工作台毫米座標或機台使用的数值；标定资产保存与图像座標間的转換。 |
| Handedness | 手性 | 第二軸由第一軸转向的方向；图像座標通常為 left-handed。 |
| Chiral consistency | 手性一致性 | 图像系统与機台系统是否同手性，站台建立時需檢查。 |
| Physical point | 实体点 | 由标定把像素转成实体系统的点。 |
| Single pixel precision | 單像素精度 | 一個像素覆蓋的实际距離，通常為 `mm_per_px`。 |
| Pose | 姿態 | 物件的位置与旋转，包含 x、y、angle。 |
| Teaching point | 教导点 | 良品上的參考位置或機台教导要去的位置。 |
| Run point | 执行点 | 本次执行中实际找到的零件位置。 |
| Line and line angle | 线与线角度 | 线由兩端点表示；角度自 +x 起算，順時針為正。 |
| Caliper | 卡尺 | 小型有方向矩形，將灰階投影到一軸以亞像素精度找边。 |
| Detection area | 检测區 | 步骤实际工作的区域，含 ROI、排除區与 ROI 跟隨后的位置。 |
| Mask | 遮罩 | 單通道图像，255 表示使用像素，0 表示忽略。 |
| Box | 框 | 由中心、寬、高与角度描述的矩形。 |
| Blob | 粒子 | 通過阈值的連通像素區段。 |
| Centroid | 質心 | 区域中像素或点的平均位置。 |
| Probability map | 機率圖 | 像素值表示結果強度而非亮度的灰階圖。 |
| Model | 模型 | 可指形狀模型、统计樣板或训练網路；皆為资产。 |
| Colour space | 色彩空間 | 將顏色拆成数值的方式，如 RGB、HSV、Lab。 |
| Solution | 解決方案 | 此平台沒有單一 solution 檔；站台与其流程、来源、連线、设置共同備份。 |
| Industrial computer (IPC) | 工業電腦 | 機櫃內执行平台的無風扇 PC。 |
| Robot arm | 機械手臂 | 接收校正位置並执行動作的機台。 |

## 核心術語 {#terms}

| 術語 | 简中 | 定义 |
|---|---|---|
| Flow | 流程 | 由節点与边組成的一個检测 graph。 |
| Node / step | 節点 / 步骤 | 畫布上的一個方塊，也是一個工具實例。 |
| Tool | 工具 | 面板中的種类，例如 grayscale、blob；`key` 是唯一識別。 |
| Edge | 边 | 步骤間的連线，從输出连接埠到输入连接埠。 |
| Port | 连接埠 | 步骤左側為输入、右側為输出，各有型別。 |
| Flow handle | 流程把手 | 型別為 `flow` 的输出，只能接到菱形控制输入。 |
| Parameter | 参数 | 步骤设置，種类為封閉集合。 |
| Teaching parameter / teach page | 教导参数 / 教导页 | 需在產线上調整的参数，標為 `teach=True`。 |
| Tolerance judge | 公差判定 | 以名目值与上下偏差判斷 pass/fail，並寫入 tolerances。 |
| Concentricity | 同心度 | 兩圆中心偏移；GD&T 同心度為偏移兩倍。 |
| OCR / OCV / taught font | OCR / OCV / 教导字型 | OCR 讀文字，OCV 驗證文字，教导字型針對点陣与雷刻字。 |
| Control chart (SPC) | 管制圖 (SPC) | 依执行順序绘制具中心线与管制界限的命名输出。 |
| Cp / Cpk | Cp / Cpk | 描述製程相對規格帶与置中程度的能力指標。 |
| Nelson rules | Nelson 規則 | 判斷管制圖失控的八種型態。 |
| Repeatability / reproducibility | 重复性 / 再現性 | 同图像重跑或同零件重拍時量測值變動。 |
| Gauge R&R | Gauge R&R | 依 AIAG MSA 分解量測系统与零件變異的研究。 |
| Barcode grade | 條碼等級 | 條碼或 2D 符號的驗證器式品質等級 A 到 F。 |
| Unused error correction (UEC) | 未用错误修正 | 2D 符號解碼后尚未使用的错误修正容量比例。 |
| Quiet zone | 靜區 | 符號周圍必要空白边界。 |
| Form and position tolerance | 形狀与位置公差 | ISO 1101 幾何公差。 |
| Minimum zone (MZC) | 最小区域 | 包住所有边点的最窄同心圆環或平行帶。 |
| Photometric stereo | 光度立體 | 多方向照明求表面法线、曲率与 albedo。 |
| Circular caliper / run-out | 圆形卡尺 / run-out | 圍繞圆边的徑向卡尺；run-out 為最大半徑減最小半徑。 |
| Wall thickness | 壁厚 | 一組成對外內边之間的距離。 |
| Region / ROI | 区域 / ROI | 在图像上畫出的检测範圍。 |
| Contour | 輪廓 | 二值图像中形狀外形的点列表。 |
| Convexity defect | 凸性缺陷 | 相對凸包向內凹陷的輪廓缺口。 |
| Polar unwrap | 極座標展開 | 將圆環展平成角度 x 半徑的長條。 |
| Anomaly detection / memory bank | 異常检测 / 記憶庫 | 只用良品教导，以 patch feature 距離評分。 |
| Shape model / shape match | 形狀模型 / 形狀比對 | 以边点与梯度方向做幾何比對。 |
| Statistical template | 统计樣板 | 多張良品對齊后建立的逐像素平均/標準差模型。 |
| Flat field / shading correction | 平場 / 陰影校正 | 用白參考与可選暗框移除照明不均。 |
| Composite region / exclusion zone | 複合区域 / 排除區 | 执行時由多個形狀 union/subtract/intersect 組成的区域。 |
| Overlay | 疊圖 | 工具畫在图像上的結果圖形，屬於 metadata。 |
| Run | 执行 | 流程完整或到某步的單次执行。 |
| Preview | 預覽 | 执行未保存 graph 並保存中間图像，不寫历史。 |
| Run once | 执行一次 | 执行已保存 graph 一次並寫入历史与统计。 |
| Continuous | 連續执行 | 以間隔重复执行。 |
| Scratch image | 臨時图像 | 只供預覽使用的上传图像。 |
| Retention | 保留期限 | run detail、audit trail、measurements、archived pictures 等保存規則。 |
| Maintenance window | 維護時段 | 执行備份修剪、孤立圖片删除与数据庫 compact 的時間。 |
| Fixed image | 固定图像 | `fixed_image` 工具，可將圖片存在流程中並作来源或參考。 |
| Image source | 图像来源 | 相机、数据夾、合成、pushed image 或 capture client camera 的定义。 |
| Capture client | 采集端 | 安裝於相机 PC 的 vscapture 桌面程序。 |
| Channel | 通道 | capture client 中的一台相机设置。 |
| Capture source | 擷取来源 | `kind=capture` 的图像来源。 |
| On demand / stream | 隨選 / 串流 | 請采集端拍新畫格，或讓它推送最新畫格。 |
| Shared memory | 共享内存 | 采集端与服务端同機時使用的图像傳輸路徑。 |
| Asset | 资产 | 樣板图像、ONNX 模型或数据集封存等檔案。 |
| Judge | 判定 | judge 工具產生的 OK/NG 結論。 |
| Named output | 命名输出 | output 工具回傳給自動化系统的 key/value。 |
| Variable | 變數 | 流程在执行間保留的值。 |
| Board | 运行界面 | 流程的操作員畫面，显示输出、图像、今日計數与變數。 |
| Calibration | 标定 | 保存鏡頭校正与像素到实体映射的资产。 |
| Engine lock | 引擎鎖定 | 整合端持有硬體時，其他人可编辑但不可执行。 |
| Integrator | 整合方 | 以 API key 呼叫的自動化系统。 |
| Role | 角色 | administrator、engineer 或 operator。 |
| Role permissions | 角色權限 | 管理員在 Users 页勾選 engineer/operator 可用功能。 |
| Reset | 重設 | 清除該流程的内存执行紀錄与统计。 |
| Template library | 模板庫 | 內建或自訂流程模板。 |
| Template | 模板 | 模板庫中的一個項目。 |
| Note | 註記 | graph 中不执行的裝飾節点。 |
| Batch test | 批量测试 | `/batch` 的調校工作台。 |
| Image set | 图像集 | 测试图像与每張 OK/NG 期望標籤的集合。 |
| Batch run | 批量执行 | 以 graph snapshot 對图像集执行一次。 |
| Insights | 洞察 | 命中率、混淆矩陣、缺失图像、失敗節点、阈值建议与输出分布。 |
| Threshold suggestion | 阈值建议 | 由 expected-OK/NG 群組推得可一鍵套用的較佳阈值。 |
| Consult | 諮詢 | 詢問一個 batch run 的数据。 |
| Assistant dock | AI 助手停駐窗 | 右下角跨页保留的聊天面板。 |
| Help answer | 说明回答 | 以文件段落与工具 skill 檢索后回答並引用来源。 |
| Assistant context | 助手情境 | 页面登錄給全域助手的 graph、callback 与 batch run id 等数据。 |
| Agent session | 代理工作階段 | 一次 AI 助手產生的完整紀錄。 |
| Prior | 先驗 | 相似成功案例中的站台教导参数。 |
| Custom skill | 自訂 skill | 站台或個人的 AI skill markdown 補充。 |
| Agentic mode | Agentic 模式 | 助手以背景工作逐步 try、edit、verify、ask。 |
| Step timeline | 步骤時間軸 | agent job 的每個 action、reply、question 与完成紀錄。 |
| Candidate | 候選 | 主方案与規則引擎產生的参数變體。 |
| Image label | 图像標籤 | 上传图像的期望 verdict，是候選排序与自動調校依據。 |
| Autotune | 自動調校 | 以数据驅動的 coordinate descent，只移動教导参数。 |
| Locate wrap | 定位包覆 | template match -> locate correction -> ROI follow。 |
| AI assistant | AI 助手 | 上传图像、標 ROI、输入 prompt，取得实际执行過的流程。 |
| Statistics | 统计 | 数据庫 KPI、每小時 OK/NG/failed、耗時趨勢与执行历史。 |
| Hourly roll-up | 每小時彙總 | `FlowRunHourly` 每流程每小時一列，永久保存。 |
| Image archive | 图像封存 | 可選擇把 run images 寫到磁碟。 |
| Flow version | 流程版本 | 每次保存 graph 的 snapshot。 |
| Audit log | 稽核记录 | 誰在何時變更了什麼。 |
| Station | 站台 | 每次执行攜帶的 `VISION_STATION_ID`。 |
| Integration page | 整合页 | 給 integrator 的介面參考与测试工具。 |
| Trace | 追蹤 | 整合页底部即時 log。 |
| Modbus client / server | Modbus 用戶端 / 服务端 | client 連到裝置；server 由平台監聽供 PLC 讀寫。 |
| Connection | 連线 | 對 Modbus TCP 或 host system 的 outgoing connection 定义。 |
| write_modbus | 寫入 Modbus | 依 mapping table 把 verdict、named output 或输入值寫到連线。 |
| Favourites | 常用 | 工具面板中加星號的工具。 |
| Commissioned | 已投產 | `Flow.commissioned`，未投產流程會显示 tag 並在执行報告警告。 |
| Recipe | Recipe | 一組流程参数 override。 |
| Override | 覆寫 | recipe 中的一個 `step.parameter = value`。 |
| Golden Set | Golden Set | 服务端保存的 image cases 与 expectations。 |
| Golden case | Golden case | Golden Set 中的一張图像与期望結果。 |
| Regression | 回歸 | 执行所有 case 並与期望和 baseline 比較。 |
| Baseline | 基準线 | 保存 regression 時每個 case 的結果。 |
| Regressed / improved | 退化 / 改善 | 与 baseline 比較后變差或變好。 |
| fail_under | fail_under | match_rate 低於此值時 regression 失敗。 |
| DL project | DL 项目 | 一個 trainer、类別清單与样本集。 |
| Auto label | 自動标注 | `Trainer.suggest` 提出类別与信心值。 |
| Trainer | Trainer | 可训练模型種类的註冊表。 |
| Shape workspace | 形狀工作區 | shapes mode 的标注工作區。 |
| Classify workspace | 分类工作區 | 分类项目的縮圖牆与全圖檢視器。 |
| Tool rail | 工具列軌 | 标注畫布左側的大圖示直列工具。 |
| Smart select | 智慧選取 | SAM 輔助标注：点击物件后產生多边形。 |
| Smart box | 智慧框 | 拖框后 SAM2 回傳框內物件輪廓。 |
| SAM proposals | SAM 提案 | 無模型的自動标注，SAM2 分割全圖。 |
| Split | 分割 | `DlSample.split`：train、val、test 或 unset。 |
| Dataset version | 数据集版本 | 將样本、標籤与 split 凍結成资产庫 zip。 |
| Augmentation | 数据增強 | 训练期間擴增样本。 |
| Dedupe | 去重 | 依解碼后像素 SHA256 略過重复样本。 |
| dl_instance | DL 實例 | 實例分割 ONNX 推論工具。 |
| AI tools | AI 工具 | ai_detect、ai_segment、ai_classify、ai_pose、ai_obb。 |
| DL dependencies | DL 依賴 | 選用 torch、ultralytics 与 onnxruntime-gpu 安裝。 |
| Python script tool | Python script 工具 | `python_script`，由管理員保存核准后执行。 |
| Plugin | 插件 | 放入 `plugins/` 並自動載入的 .py 檔。 |
| Theme | 主題 | light、dark、cyber 或 system。 |
| Bit depth | 位元深度 | u8、u16 或 f32；工具未宣告時自動正規化到 u8。 |
| Manual write | 手動寫入 | 在 connections 页送一組 JSON 值测试連线。 |
| Export / import | 导出 / 导入 | 导出穩定序列化流程檔；导入依名稱 upsert。 |

## 连接埠型別顏色（固定，不重用） {#port-colors}

| Type | 顏色 | 承載 |
|---|---|---|
| image | blue `#3b82f6` | 图像 |
| region | purple `#a855f7` | ROI |
| number | green `#22c55e` | 數字 |
| bool | orange `#f97316` | 布林 |
| string | yellow `#eab308` | 字串 |
| points | cyan `#06b6d4` | 点集 |
| contours | indigo `#6366f1` | 輪廓 |
| matches | pink `#ec4899` | match 与检测結果 |
| list | teal `#14b8a6` | 一般 list，含疊圖 |
| any | grey-white `#cbd5e1` | 任意数据 |
| flow | grey `#94a3b8` (diamond) | 分支 |

## 状态用語 {#status}

| 状态 | 顏色 | 意義 |
|---|---|---|
| OK | green | 判定良品 |
| NG | red | 判定不良 |
| Failed | dark red border | 工具错误、逾時或無图像；步骤在畫布上显示错误訊息 |
| Skipped | faded grey | 未走到的分支或上游失敗 |
| Running | pulsing border | 执行中 |

## 语气 {#tone}

此產品是工業設備，介面文字應平實、精確、不口語。英文標籤与按鈕用 sentence case，不用驚嘆號，動作用祈使動詞。訊息要说明發生什麼与下一步。简中遵循下表，簡中由此派生；`frontend/src/test/i18n.test.ts` 自動檢查禁用詞。

| 避免 | 使用 | 原因 |
|---|---|---|
| 口语点击说法 | 点击 | 動作動詞一致 |
| 临时试执行说法 | 預覽 / 試执行 | 區分未保存 graph 与正式执行 |
| 口语空状态 | 尚無 / 尚未 / 無 | 空状态 |
| 限制口语 | 无法 / 不得 | 限制与驗證訊息 |
| 指示口语 | 此 / 此次 | 文件语气較正式 |
| 口语采集说法 | 擷取 / 检测 | 图像取得与检测用語分開 |
| 你 | 您 | 對用户稱呼 |
| 口语检测结果 | 誤判過多 / 漏檢 | 描述检测結果 |
| 口语连接与应用 | 连接 / 校正 / 套用 | 工業文件用語 |

AI 助手的範例 prompt 可保留口語；其他介面、说明页与文件都遵循此表。
## 工程笔记 {#engineering-note}

工程笔记记录站点共用的决策、经验、打光、标定、限制、公差依据或已知问题。正式检测规格仍从流程读取。笔记可关联项目、料号、流程、配方、图像来源、证据图像与执行记录，并记载适用条件与包含起止版本的范围；版本界限留空表示不限。

任何登录者均可阅读。具流程编辑权限者可创建与编辑草稿。单人工程站点默认允许自我确认；多人站点可关闭此设置，改由另一位工程师确认。已确认内容保留，修改时创建替代笔记。替代草稿创建后，旧笔记立即变为已替代。撤回保留历史，但停止助手检索。

助手最多引用五条符合当前流程版本的已确认笔记，包含此流程与相关料号。相关料号取自此流程适用的已确认笔记，引用时仍须检查适用条件。助手与对话决策列表可创建草稿，助手无法确认。固定证据图像会保留，缓存图像引用可能过期。
