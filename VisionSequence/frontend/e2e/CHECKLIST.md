# 全面性測試清單（frontend/e2e/full.mjs）

執行：`node frontend/e2e/full.mjs`（需後端 :8000 `manage.py serve`、前端 :5173）。
每一項有一個 ID，`full-*.mjs` 以 `h.item('ID', 條件, 說明)` 回報；`node frontend/e2e/full-mark.mjs` 依 `full-results.json` 把 ✅／❌ 標回本檔。
截圖：`Image/120-*.png`（配方儲存範圍／頂列兩列回合；風格改版回合為 `110-*`、v0.2 回合為 `90-*`、更早為 `70-*`）。狀態：✅ 通過、❌ 失敗（附原因與是否已修）、⏭ 無法以 UI 觸發（附理由）。

## A. 登入／設定初始化（LoginPage）
- ✅ `A01` 未登入直接開 /flows → 導向 /login，登入後回到原頁
- ✅ `A02` 帳號／密碼欄位存在，帳號欄 autoFocus
- ✅ `A03` 空白送出 → 「請輸入帳號與密碼」（role=alert）
- ✅ `A04` 錯誤密碼 → 「帳號或密碼錯誤」（預期 401）
- ✅ `A05` 正確登入 → 使用者選單顯示名稱
- ✅ `A06` 送出中按鈕 loading／disabled（避免重複送出）
- ✅ `A07` 系統無使用者時顯示「建立第一個管理員」表單：提示、顯示名稱欄、密碼 <6 → 弱密碼錯誤、建立後登入
- ✅ `A08` 已登入再開 /login → 導回 /
- ✅ `A09` 登入頁深色模式截圖

## B. 外框（AppShell）
- ✅ `B01` 左側側欄（`[data-testid=sidebar]`）導覽 9 項（管理員，含「連線」）、目前頁 `.nav-item.active` 樣式、展開時 title
- ✅ `B02` 頂列（`[data-testid=topbar]`）容量 pill「0/N 忙碌」（改版後由側欄底部搬到頂列）
- ✅ `B03` 主題切換按鈕：html.dark 切換、圖示 Sun/Moon 互換
- ✅ `B04` 使用者選單：開啟、顯示 @帳號 · 管理員、點外面關閉
- ✅ `B05` 修改密碼 Modal：空白→錯誤；不一致→錯誤；舊密碼錯→伺服器錯誤（預期 4xx）；成功→toast「密碼已更新」；改回原密碼
- ✅ `B06` 修改密碼 Modal 有輸入時 Esc → 「放棄變更？」→ 繼續編輯／放棄
- ✅ `B07` 登出 → /login，localStorage token 清除
- ✅ `B08` Toast 出現、手動 X 關閉

## C. 總覽（DashboardPage）
- ✅ `C01` 「即時」badge（SSE 已連線）
- ✅ `C02` 容量條與「快取 N 張影像（MB）」
- ✅ `C03` 流程卡片：名稱、描述／步驟數、最近判定 StatusBadge、次數、OK 率、平均、最大、趨勢條
- ✅ `C04` 連續執行時卡片顯示「連續執行中」badge
- ✅ `C05` 停用流程顯示「停用」badge
- ✅ `C06` 卡片右上統計圖示 → /flows/:id/stats（不觸發卡片本身導覽）
- ✅ `C07` 點卡片 → 編輯器
- ✅ `C08` 空狀態（無流程）：「還沒有任何流程」＋「新增流程」按鈕（以 route mock 空回應）
- ✅ `C09` 錯誤狀態＋「重試」（以 route mock 500）
- ✅ `C10` SSE：執行一次後卡片次數／最近判定即時更新（不重新整理）
- ✅ `C11` 深色模式截圖

## D. 流程列表（FlowsPage）
- ✅ `D01` 搜尋框即時篩選（q）
- ✅ `D02` 「只看我的」開關（admin 無自有流程 → 空列表）
- ✅ `D03` 表格欄位：名稱／描述、擁有者（共用／(你)）、啟用開關、步驟、版本 vN、統計（badge、N 次 · ms、連續執行中）、綁定（配方欄）、更新時間、操作圖示 7 顆
- ✅ `D04` 新增流程 Modal：空名稱→toast「請輸入名稱」；Enter 送出；建立→toast＋導向編輯器
- ✅ `D05` 新增流程 Modal 有輸入時 Esc → 放棄確認；點遮罩也一樣
- ✅ `D06` 啟用開關 → PATCH → 列表更新；停用後總覽顯示「停用」；再啟用
- ✅ `D07` 點列 → 編輯器；操作區點擊不會觸發列導覽
- ✅ `D08` 複製 → toast「已複製流程」＋列表多一列
- ✅ `D09` 刪除 → ConfirmDialog（危險樣式、名稱）→ toast → 列表移除
- ✅ `D10` 空狀態：搜尋無結果 → 「還沒有流程」＋提示
- ✅ `D11` 從範本建立按鈕 → 範本畫廊
- ✅ `D12` 長名稱／長描述在列表不破版（截斷）
- ✅ `D13` 錯誤狀態＋重試（mock 500）

## E. 範本畫廊／存為範本（TemplateGallery、SaveTemplateModal）
- ✅ `E01` 卡片 ≥5：縮圖 SVG、名稱、描述、內建 badge、類別 badge、N 個步驟
- ✅ `E02` 搜尋篩選；無符合 → 「沒有符合的範本」
- ✅ `E03` 選卡片 → 右側名稱／描述、流程名稱自動帶入、可改
- ✅ `E04` 影像來源下拉（含「先不選」）
- ✅ `E05` 未選卡片時「建立流程」disabled；名稱清空→toast
- ✅ `E06` 不選來源建立 → warning toast「請在取像步驟選擇影像來源」＋畫布問題計數
- ✅ `E07` 編輯器「載入範本」：dirty 時 window.confirm；載入後節點 id 帶 t1_ 前綴；toast「已載入範本」
- ✅ `E08` 存為範本 Modal：名稱預設流程名、描述、類別下拉 6 項、儲存 → toast；同名再存 → 錯誤 toast（預期 4xx）
- ✅ `E09` 自訂範本卡片有刪除圖示 → ConfirmDialog → toast「已刪除範本」；內建無刪除圖示
- ✅ `E10` Esc 關閉畫廊

## F. 流程編輯器 — 頂列（EditorToolbar）
- ✅ `F01` 名稱輸入 → dirty、「有未儲存的變更」、儲存變 primary
- ✅ `F02` 儲存（按鈕與 Ctrl+S）→ toast「流程已儲存」、version +1、「已儲存」
- ✅ `F03` 範本下拉：兩項；Esc 關閉；點外面關閉
- ✅ `F04` 問題計數：插入必填未填工具 → 「N 個問題」；存檔 warning toast「有 N 個步驟的參數有問題」
- ✅ `F05` 試跑 → toast「試跑完成：OK/NG（ms）」、影像視窗有影像、badge
- ✅ `F06` 「用上次影像重跑」：試跑前 disabled、試跑後可勾、有暫存影像時 disabled；勾選後試跑 body 帶 reuse_image_ref
- ✅ `F07` 上傳暫存影像 → toast、badge（檔名＋尺寸）；清除 X
- ✅ `F08` 批次測試按鈕開 Modal
- ⏭ `F09` 已移除：「執行一次」按鈕（整合方走 API／整合頁；F24 驗證頂列沒有此鈕） — 已移除：「執行一次」按鈕（整合方走 API／整合頁）
- ⏭ `F10` 已移除：「上傳影像執行」按鈕（只保留「上傳暫存影像」；F24 驗證） — 已移除：「上傳影像執行」按鈕（只保留「上傳暫存影像」）
- ✅ `F11` 連續執行：開 → active、「連續執行中」、fps／ms 標籤；關 → toast
- ✅ `F12` 重置 → ConfirmDialog → toast「已重置」、結果分頁「還沒有執行記錄」、影像清空
- ✅ `F13` 選取／平移切換在畫布右上角（`.react-flow__panel.top.right[data-testid=canvas-mode]`，與縮放滑桿同風格；頂列沒有）：aria-pressed；預設平移，存 localStorage `vs.canvasMode`
- ✅ `F14` 即時／離線 badge＋容量 pill
- ✅ `F15` 復原按鈕（移動節點後按 → 位置還原）
- ✅ `F16` 自動排列（頂列）→ 位置改變＋dirty
- ✅ `F17` 統計圖示 → /flows/:id/stats
- ✅ `F18` 說明下拉 3 項：說明頁、快捷鍵（/help?tab=shortcuts）、整合頁
- ✅ `F19` 唯讀 badge（worker 開共用流程）、儲存 disabled
- ✅ `F20` 「引擎已鎖定」badge（worker、鎖定時）
- ✅ `F21` dirty 時離開頁面 → window.confirm 攔截：到參數卡（btn-teach）不問且回來仍 dirty；到總覽／流程列表都問（取消留在頁面、確定離開）
- ✅ `F22` 頂列在 1280×800 換行不重疊、不產生水平捲軸
- ✅ `F23` 流程停用（複製出來的副本預設停用）：頂列「流程已停用」badge、連續執行 disabled（試跑仍可）、側欄「啟用」勾選即開啟
- ✅ `F24` 頂列兩列（`toolbar-row-1`：名稱／儲存／範本／配方／綁定；`toolbar-row-2`：試跑／用上次影像／上傳暫存影像／批次／連續執行／重置／說明）；沒有「執行一次」「上傳影像執行」、只剩一個隱藏 file input
- ✅ `F25` 頂列在 1280×800／1440×900／1920×1080 都換行不重疊、元素都在視窗內、無水平捲軸（截圖 toolbar-1280／1440／1920）

## G. 工具箱（ToolPalette）
- ✅ `G01` 搜尋：輸入「blob」只剩符合項；清空還原；搜尋時收藏／最近區隱藏
- ✅ `G02` 分類標題點擊收合／展開，計數正確
- ✅ `G03` 收藏：星號 hover 顯示、點擊加入「收藏」區、localStorage vs.favoriteTools、再點取消；無收藏時提示文字
- ⏭ `G04` 已移除：工具箱「最近使用」（`vs.recentTools`／`rememberRecentTool`） — 已移除：工具箱「最近使用」（vs.recentTools）
- ✅ `G05` 點擊工具不新增（節點數不變、不 dirty）；工具箱標題提示「拖到畫布新增」
- ✅ `G06` 拖放到畫布（DataTransfer application/x-vs-tool）→ 節點出現在放下位置
- ✅ `G07` 工具按鈕 title 為描述＋「拖到畫布新增」
- ✅ `G08` 工具箱只有「收藏」區，沒有「最近使用」區

## H. 步驟清單（NodeList）
- ✅ `H01` 列出全部步驟＋標題計數 (N)
- ✅ `H02` 狀態點：試跑後 ok 綠／ng 橘／error 紅
- ✅ `H03` 點擊 → 選取＋畫布聚焦（viewport transform 改變）
- ✅ `H04` 停用步驟半透明
- ✅ `H05` 新流程空狀態「畫布上還沒有步驟」

## I. 畫布（FlowCanvas）
- ✅ `I01` 節點：圖示、名稱、工具名、輸入埠（必填 *）、輸出埠、隱含 _overlays 小埠、控制輸入菱形
- ✅ `I02` 連線成功（image→image）→ 邊出現、dirty
- ✅ `I03` 連線型別不相容（number→image）→ warning toast、邊未新增
- ✅ `I04` 分支把手接到一般輸入 → 拒絕（flowOnly）
- ✅ `I05` 同一輸入埠第二條線 → 拒絕（singleInput）
- ✅ `I06` 連回上游 → 拒絕（cycle）
- ⏭ `I07` 連到註解 → 拒絕（noteTarget） — 註解節點沒有輸入把手，UI 上拉不到線；規則由 graphValidation.checkConnection 的 noteTarget 涵蓋
- ✅ `I08` 框選（選取模式；測試先在畫布右上角切到「選取」）→ 多個 selected、側欄「已選取 N 個步驟」；模式切換鈕在畫布右上角（2 顆）、頂列沒有
- ✅ `I09` 預設平移模式（清掉 localStorage 重載 → 「平移」pressed）：左鍵拖曳空白處平移且不選取；Shift+拖曳框選；切到「選取」→ `vs.canvasMode=select`、重載保留；切回平移 → `pan`
- ✅ `I10` 多選拖曳整體移動；Delete 一次刪除；側欄「刪除這 N 個步驟」
- ✅ `I11` 右鍵選單：標題、開啟工具頁、複製、停用／啟用、複製參數、貼上參數（同型別 enabled、不同型別 disabled）、刪除；Esc／點外面關閉；註解只有複製／刪除
- ✅ `I12` Ctrl+C／Ctrl+V 複製整組含內部連線；貼上位置偏移 40
- ✅ `I13` Ctrl+Z 復原（插入、刪除、移動、連線）
- ✅ `I14` Delete／Backspace 刪除選取節點（拖曳新增 6 個再逐一刪除）；Esc 取消選取
- ✅ `I15` 點選邊後 Delete 刪除邊
- ✅ `I16` 縮放滑桿：−、+、range、%、符合視窗、自動排列
- ✅ `I26` 工具箱點擊不新增；DataTransfer drop 新增 → 節點被選取（blur-1）
- ✅ `I17` 小地圖存在且可點
- ✅ `I18` 雙擊步驟卡片 → 直接開工具頁（未儲存的改名一起帶過去、工具頁頂列 dirty）；返回編輯器仍 dirty、改名保留（原「切到結果分頁」改為右鍵選單／步驟清單）
- ✅ `I19` 執行狀態：ok 綠點、ng 橘點、error 紅框＋訊息第一行（data-testid=node-error）、skipped 淡化、耗時 ms 角標
- ✅ `I20` 參數問題節點紅框＋訊息（必填 ROI）
- ✅ `I21` 註解節點：選取後可調大小（NodeResizer）、文字換行、自訂顏色
- ✅ `I22` 節點自訂顏色：深色底自動白字、淺色底黑字
- ✅ `I23` 拖曳節點 → dirty
- ✅ `I24` 在輸入框內按 Delete／Ctrl+Z 不影響畫布
- ✅ `I25` 停用節點：虛線框＋PowerOff 圖示，執行時 skipped

## J. 影像視窗（ImageViewer）
- ✅ `J01` 空狀態「尚無影像」＋底列「尚無影像；按「試跑」產生」
- ✅ `J02` 試跑後影像載入（canvas 非空像素）
- ✅ `J03` 工具列：適合視窗、1:1（比例 100%）、縮小、放大（比例 % 變化）、格線開關（放大 ≥8x 顯示格線）、標記顯示／隱藏
- ✅ `J04` hover 顯示像素座標與灰階／RGB 值；離開清空
- ✅ `J05` 滾輪縮放（以游標為中心）、左鍵拖曳平移、雙擊 fit、F／1／+／− 快捷鍵
- ✅ `J06` badge：「OK · ms · 節點名」綠／NG 紅
- ✅ `J07` 底列：輸入／輸出切換（無輸出時 disabled）、疊加所有步驟標記、前／後分割（右側「執行後」有影像；無影像輸出的步驟顯示「執行後 · 標記疊在輸入影像上」、選項 disabled）、pinned run 時「最新」按鈕
- ✅ `J08` overlay 座標對齊：blob 中心點 overlay 落在對應像素（取樣顏色）；縮圖（max=1600）下座標仍以 imageWidth 為準
- ✅ `J09` ROI 繪製 rect（裁切 ROI）：拖曳 → 參數更新、描述文字、繪製提示消失
- ✅ `J10` ROI 六種形狀（ROI 跟隨工具）：rect／rotated_rect／circle／annulus／polygon／line 各繪製一次，參數 shape 正確
- ✅ `J11` ROI 把手：rect 角把手 resize、邊把手；rotated_rect 旋轉把手（Shift 吸附 15°）；circle 半徑把手；annulus 內／外把手；polygon 頂點拖曳、雙擊邊新增頂點、右鍵刪頂點、Delete 刪選取頂點；line 端點（Shift 角度吸附）
- ✅ `J12` ROI 本體拖曳移動；游標樣式（move／resize／grab）
- ✅ `J13` 形狀切換按鈕轉換現有 ROI（rect→circle…）；「夾入」把超出影像的 ROI 夾回
- ✅ `J14` 太小的拖曳（<2px）不建立 ROI；Shift 拖曳正方形
- ✅ `J15` 「清除」ROI → 尚未設定；Esc 結束編輯；完成按鈕；換選取步驟自動結束編輯
- ✅ `J16` 深／淺色下 viewer 背景與工具列對比

## K. 側欄設定分頁（Inspector）
- ✅ `K01` 無選取：提示文字、流程描述輸入（dirty）、連續執行間隔（PATCH 即存）
- ✅ `K02` 選取工具：名稱＋工具頁圖示、工具描述、「開啟工具頁」按鈕、名稱（placeholder 工具名、hint）、備註、顏色 8 色＋自訂 color input＋還原、啟用此步驟、出錯時繼續、輸入／輸出列表、id、刪除步驟
- ✅ `K03` 問題提示「此步驟有 N 個參數問題」
- ✅ `K04` 註解：無工具頁、備註 5 列、無啟用／出錯時繼續
- ✅ `K05` 多選摘要＋刪除按鈕

## L. 結果分頁（ResultsPanel）
- ✅ `L01` 分頁標籤帶 StatusBadge
- ✅ `L02` 錯誤區塊：「「X」執行失敗」＋訊息＋「前往該步驟」選取該節點
- ✅ `L03` 最近執行表 5 欄；點列 pin → 影像視窗切換、「最新」按鈕出現、再按回最新
- ✅ `L04` 步驟結果：狀態、耗時、分支、標記數、訊息、輸出表（image WxH、數值、list [n]）、記錄、detail 摺疊
- ✅ `L05` 流程輸出表＋run.error
- ✅ `L06` 空狀態「還沒有執行記錄」「此步驟尚無結果」

## M. 批次測試（BatchTestModal）
- ✅ `M01` 選擇影像檔（多選）→ 「已選 N 個檔案」；清除；>50 → warning「一次最多 50 張」且截到 50
- ✅ `M02` 拖放區：dragover 高亮、drop 加入檔案；非影像檔被過濾
- ✅ `M03` 執行批次 → 執行中文案 → 摘要 8 格（總數／OK／NG／失敗／良率／平均／最大／總耗時）、結果表 8 欄（含「存為 Golden Set」勾選欄）、縮圖、StatusBadge、輸出摘要
- ✅ `M04` 從來源抓取：來源下拉、張數（夾 1–50）、按鈕文字「抓 N 張並執行」→ 結果
- ✅ `M05` 「使用目前畫布」checkbox；dirty 時 hint「有未儲存的變更」；取消勾選用已儲存版本
- ✅ `M06` 篩選全部／只看 NG／只看失敗＋「x / y」計數；無符合列顯示「—」
- ✅ `M07` 匯出 CSV（download 事件、檔名 batch-flow…csv、BOM＋標題列）
- ✅ `M08` 點列 → 列高亮、「正在檢視批次結果」badge；關閉 Modal 後影像視窗顯示該 run 且結果分頁被 pin
- ✅ `M09` 影像已釋放：跑 >8 張後前面的縮圖顯示 ImageOff；點該列 → warning「這次執行的影像已釋放」
- ✅ `M10` Esc 關閉；引擎鎖定（worker）時執行按鈕 disabled
- ✅ `M11` 未執行時「尚未執行」

## N. 工具頁（ToolPage）
- ✅ `N01` 頂列：返回編輯器、圖示＋名稱＋工具名 · id、儲存（dirty→primary）、試跑到此步驟、用上次影像重跑、上傳暫存影像／badge、自動套用開關（唯一的 switch；改版後沒有「同步視角」）、更新中…、錯誤文字
- ✅ `N02` Param kind：text（判定 label）
- ✅ `N03` Param kind：number（min/max/step、單位 suffix）
- ✅ `N04` Param kind：boolean（Checkbox）
- ✅ `N05` Param kind：select（含 visible_when 條件欄位顯示／隱藏）
- ✅ `N06` Param kind：range（滑桿＋數字框連動）
- ✅ `N07` Param kind：roi（描述文字、在影像上編輯／完成、清除、形狀提示）
- ✅ `N08` Param kind：source（下拉列影像來源、停用者 disabled、清空→null）
- ✅ `N09` Param kind：asset（下拉、上傳按鈕→資產→自動選取＋toast、「從目前影像框選建立範本」→框選→建立範本 Modal→toast＋自動選取）
- ✅ `N10` Param kind：color（color input＋hex 文字框）
- ✅ `N11` Param kind：json（write_plc 的 mapping：textarea、非法 JSON 顯示錯誤、合法後參數更新；v0.2 起可由 UI 觸發，由 IO07 回報）
- ✅ `N12` Param kind：expression（公式 textarea）
- ✅ `N13` Param kind：output_key（monospace 輸入）
- ✅ `N14` Param kind：multiline（DL labels textarea）
- ✅ `N15` 進階群組「進階（N）」收合／展開
- ✅ `N16` 驗證訊息：必填 ROI 未填、數值超過上限
- ✅ `N17` 自動套用開：改參數 250ms 內送 preview（until_node、analysis、reuse_image_ref）；關：不送；手動「試跑到此步驟」送
- ✅ `N18` 前／後影像視窗各自 fit／縮放：左邊放大右邊不動、右邊放大左邊不動、各自「適合視窗」回到相同比例（改版後不同步）
- ✅ `N19` 參考資訊：輸入直方圖＋統計、輸出直方圖（port）、數值分布（series）、輸出表、記錄
- ✅ `N20` 無影像輸出工具（blob）：右側「執行後 · 標記疊在輸入影像上」＋輸出值表
- ✅ `N21` 錯誤時底部訊息列（bg-critical）＋頂列錯誤
- ✅ `N22` Ctrl+S 儲存；返回編輯器參數保留；dirty 離開到其他頁 → confirm
- ✅ `N23` 不存在的 nodeId → 「找不到步驟」＋返回連結
- ✅ `N24` 唯讀（worker）儲存 disabled；引擎鎖定時不自動試跑

## O. 統計頁（StatsPage）
- ✅ `O01` 標題含流程名、期間 4 選項、回編輯器
- ✅ `O02` KPI 6 格 tile（`.tile-count`：總執行數／良率 %／NG 數／失敗數／平均／最大）
- ✅ `O03` 記憶體即時統計列＋趨勢條
- ✅ `O04` 每小時堆疊長條與耗時折線（recharts svg）；無資料 → 「此期間沒有執行紀錄」
- ✅ `O05` 歷史表、狀態篩選（ok/ng/failed/cancelled）、分頁「顯示 a–b / 共 n」、上一頁 disabled 於第一頁、下一頁
- ✅ `O06` 錯誤狀態＋重試（mock 500）
- ✅ `O07` 深色模式圖表可讀

## P. 影像來源庫（SourcesPage）
- ✅ `P01` 表格：名稱 #id、類型 badge、設定 JSON 截斷 title、狀態、啟用開關、操作
- ✅ `P02` 新增 folder：路徑、循環讀取、排序下拉、檔名樣式；名稱必填 toast；儲存 toast「已建立來源」
- ✅ `P03` 新增 file：路徑
- ✅ `P04` 新增 usb：裝置索引、寬、高、FPS
- ✅ `P05` 新增 synthetic：寬、高、樣式下拉（圓點／條紋／隨機）、隨機種子
- ✅ `P06` 新增 upload：無欄位；列上出現上傳圖示 → push 檔案 → toast「已儲存」
- ✅ `P07` 新增 plugin：類別路徑
- ✅ `P08` 切換類型時 config 重設為該類型預設
- ✅ `P09` 預覽 Modal：img 載入成功（synthetic）、重新整理換 url、Esc；不存在路徑的 folder 預覽 → 圖片錯誤（預期 4xx）
- ✅ `P10` 編輯：帶入既有值、修改後 toast「已更新來源」、列表更新
- ✅ `P11` 啟用開關 → PATCH
- ✅ `P12` 刪除 → ConfirmDialog → toast → 列表刷新
- ✅ `P13` 空狀態（mock）、錯誤狀態（mock 500）

## Q. 資產庫（AssetsPage）
- ✅ `Q01` 類型篩選下拉（無／影像／模型／檔案）
- ✅ `Q02` 上傳 Modal：類型 3 種（image 時 accept=image/*）、檔案、名稱 placeholder＝檔名、未選檔案時上傳 disabled
- ✅ `Q03` 上傳 image／model／file 各一 → toast「已上傳」、卡片出現（縮圖或 FileBox 圖示、badge 色調、大小、尺寸）
- ✅ `Q04` 長名稱截斷＋title
- ✅ `Q05` 刪除 → ConfirmDialog → toast「已刪除」→ 卡片消失
- ✅ `Q06` 空狀態「還沒有資產」（篩選 model 且無 → 空）

## R. 使用者（UsersPage）
- ✅ `R01` 非管理員開 /users → 導向 /；導覽無「使用者」
- ✅ `R02` 表格：帳號＋「你」badge、顯示名稱、管理員開關、啟用開關、最近登入、操作；自己列開關與刪除 disabled
- ✅ `R03` 新增 Modal：必填 toast、密碼 <6 toast、管理員 checkbox＋hint、建立 toast＋列表新增；重複帳號 → 錯誤 toast（預期 4xx）；有輸入 Esc → 放棄確認
- ✅ `R04` 管理員開關 → ConfirmDialog（設為／取消）→ toast「已更新使用者」
- ✅ `R05` 啟用開關 → ConfirmDialog（停用為危險樣式）→ toast；停用後該帳號登入 401；再啟用
- ✅ `R06` 重設密碼 Modal：<6 toast、Enter 送出、toast「密碼已重設」；新密碼可登入
- ✅ `R07` 刪除 → ConfirmDialog → toast「已刪除使用者」→ 列表移除
- ✅ `R08` 空狀態（mock）

## S. 整合頁（IntegrationPage）
- ✅ `S01` 資訊列：HTTP 位址、TCP host:port＋「監聽中」、API 金鑰不需要、執行緒、逾時
- ✅ `S02` HTTP 測試：流程下拉、觸發方式 json／附影像檔（file input 出現）、context 非法 JSON → toast、wait 取消 → 逾時 disabled、送出 → 狀態碼 200 badge、耗時、回應摺疊 ▾／▸、複製、影像縮圖
- ✅ `S03` 程式碼片段 tabs curl／Python／C# 隨表單變、複製 → 「已複製」
- ✅ `S04` TCP：指令 Enter 送出、常用指令 chips、送出 PING → 路徑 tcp、回應 JSON；RUN → status；歷史列表、重送、清除歷史
- ✅ `S05` 事件監看：已連線 badge、執行後出現 event-row（run_finished 帶狀態與 ms）、暫停後不新增、繼續、清除、空狀態文字
- ✅ `S06` 鎖定分頁：狀態 badge、鎖定時持有者／原因／TTL、三段 curl、設定頁連結
- ✅ `S07` 回傳格式：RunReport 欄位表、outputs 範例、錯誤碼表
- ✅ `S08` `?tab=` 深連結與切換時 URL 更新

## T. 說明頁（HelpPage）
- ✅ `T01` 7 個分頁可切換、URL ?tab=
- ✅ `T02` 快速上手 8 步驟
- ✅ `T03` 名詞定義 4 張表
- ✅ `T04` 埠型別 11 列色點（flow 為菱形）
- ✅ `T05` 工具目錄依分類、每工具輸入／輸出／參數
- ✅ `T06` 快捷鍵表 kbd
- ✅ `T07` 自動化接口＋「整合」按鈕 → /integration
- ✅ `T08` 帳號與鎖定 5 條

## U. 設定頁（SettingsPage）
- ✅ `U01` API 金鑰儲存 → toast、localStorage vs.apiKey；清空儲存移除
- ✅ `U02` 主題 淺色／深色／跟隨系統 → html.dark、localStorage vs.theme
- ✅ `U03` 語言切換 English → 各頁（總覽、流程、編輯器、工具頁、來源、資產、使用者、設定、說明、整合、統計、登入、參數卡、Golden Set、連線、PLC 輸出）無未翻譯 key（xxx.yyy）；切回繁中
- ✅ `U04` 引擎鎖定：原因＋秒數 → 鎖定 → 狀態 badge「已鎖定」、持有者／原因／自動解鎖時間、橫幅；解鎖 → toast
- ✅ `U05` 帳號卡片（帳號／顯示名稱／角色）＋修改密碼按鈕
- ✅ `U06` 執行緒池卡片（max_workers／active／images／各流程狀態）
- ✅ `U07` 自動化接口文字

## V. 引擎鎖定與一般使用者（worker）視角
- ✅ `V01` 管理員鎖定後 worker 編輯器：橫幅無「解鎖」、試跑／連續執行／批次測試 disabled、API run → 423
- ✅ `V02` 持有者（admin）本人仍可試跑
- ✅ `V03` 橫幅「解鎖」→ 橫幅消失；worker 頁靠 SSE 同步解除 disabled
- ✅ `V04` API 上鎖 → worker 頁不重整出現橫幅（SSE）
- ✅ `V05` worker 流程列表：共用流程顯示鎖圖示、啟用開關與刪除 disabled；「只看我的」
- ✅ `V06` worker 編輯共用流程：唯讀 badge、儲存 disabled、Ctrl+S → warning toast；複製後可編輯自己的流程
- ✅ `V07` 設定頁 worker：鎖定卡片顯示「只有管理員或整合方能鎖定引擎」；鎖定時顯示提示

## W. 版面／主題／SSE
- ✅ `W01` 1280×800：各頁（含參數卡／Golden Set／連線／PLC 輸出）無水平捲軸（document.scrollWidth ≤ clientWidth）、編輯器三欄可見、頂列換行
- ✅ `W02` 1600×1000：同上
- ✅ `W03` 深色模式各頁截圖：總覽、流程、編輯器（含影像）、工具頁、統計、整合、設定、說明、參數卡、Golden Set、連線、PLC 輸出
- ✅ `W04` SSE 斷線後重連：阻斷 /stream 5 秒 → badge「離線」→ 恢復後「即時」，之後執行事件仍收到
- ✅ `W05` 全程 console error／warning、pageerror、非預期 HTTP ≥400 為 0
- ✅ `W06` 全程無未翻譯 key（zh 與 en）

## X. 參數卡（TeachPage）— v0.2 回合
- ✅ `X01` 開啟 /flows/:id/teach：三欄（左步驟清單 `teach-steps`、中聚焦步驟參數 `teach-params`、右影像視窗 `teach-viewer` 最寬）、頂列兩排（動作／配方）、返回編輯器、標題含流程名、步驟依拓樸順序（thr→blob→cmp）、第一步預設聚焦、中欄圖示／名稱／工具名 · id、「綁定：圖值」標籤；進頁整條試跑後每步狀態點＋ms
- ✅ `X02` 教導參數欄位種類：number（門檻）、range（圓度滑桿＋數字框）、in_range 的 low/high；非 teach 參數（method、roi）不出現
- ✅ `X03` 改值 → 250ms 內送 preview（until_node＝該步驟）→ 該步狀態更新、仍聚焦該步（`data-focused`）、「有未儲存的變更」、儲存變 primary
- ✅ `X04` 點左欄另一步 → 聚焦切換（左邊 3px 品牌色條、中欄只顯示該步）、右側「正在檢視：名稱」、影像視窗有影像（canvas 非空）、結果摘要（teach-outputs）
- ✅ `X05` 儲存到圖（按鈕）與 Ctrl+S → PATCH 200、toast「流程已儲存」、API graph 更新、未儲存文字消失
- ✅ `X06` 暫存影像：上傳 → toast＋badge、「用上次影像」disabled；清除 X → badge 消失、checkbox 恢復
- ✅ `X07` 存為新配方：空名稱 toast「請輸入名稱」；Enter → 儲存範圍 Check List（標題含配方名；圖模式 5 項全 unchanged 預設不勾、「納入 0 / 5 項」）→ 確認 → toast「已建立配方」、覆寫 {}、第一個配方自動綁定（「綁定：partA」）、編輯對象切到新配方、「管理配方 (1)」、「0 個覆寫」、儲存按鈕變「儲存到配方」、中欄「正在編輯配方」提示
- ✅ `X08` 配方模式改值 → 覆寫標示（左邊框、「配方值 · 圖值」、還原為圖值）、頂列與左欄「1 個覆寫」、Ctrl+S → Check List（include_all：教導參數區 5 項，只有 blob.min_area ok 預設勾、其餘 unchanged 不勾、「其他參數（N）」摺疊未展開；顯示 目前值 → 新值）→ 確認 → toast「已儲存配方」→ API param_overrides；圖值未變、未儲存文字消失
- ✅ `X09` 「還原為圖值」→ 覆寫移除、覆寫計數 −1
- ✅ `X10` 配方未儲存時切換下拉 → window.confirm：取消留在配方；確定切回「（圖的值）」；下拉選項標「· 綁定」
- ✅ `X11` 管理配方＝側滑面板（recipe-drawer）：清單（綁定 badge、覆寫計數）、新增（Enter → Check List → 建立、自動展開）、改名（Enter）→ toast「已改名為」、設為綁定 → toast、頂列「綁定：」跟著換、展開覆寫表：從目前圖值填入（列數＝教導參數數）、新增一列／移除、列顯示圖值、儲存（檢查儲存範圍）→ Check List（改過的 ok 預設勾、其餘 unchanged 不勾、全選）→ toast「已更新配方」→ API 5 項、刪除配方 → ConfirmDialog → toast「已刪除配方」、X 關閉
- ✅ `X12` 標記為已教導 → toast、API commissioned=true、badge「已教導」＋「取消已教導」；取消 → 回「未教導」；編輯器頂列「未教導」標籤連到參數卡
- ✅ `X13` 返回編輯器：圖草稿未儲存不攔截且編輯器顯示 dirty；配方未儲存離開 → window.confirm 攔截
- ✅ `X14` 非管理員開共用流程：儲存／存為新配方／標記 disabled；配方面板無新增區、無儲存、匯入 disabled；Ctrl+S → warning toast
- ✅ `X15` 沒有教導參數的流程 → 左欄「此流程沒有需要教導的參數」＋提示、中欄「從左側選一個步驟」
- ✅ `X16` 引擎鎖定（worker 視角）：不自動試跑（左欄每步「—」無 ms、無「試跑中」、結果摘要「尚未試跑」）
- ✅ `X17` 1280×800 頂列換行無水平捲軸、影像視窗仍 ≥440px（中欄 360px，2xl 才 420px）；深色截圖（含配方面板）

## Y. Golden Set（GoldenPage）— v0.2 回合
- ✅ `Y01` 空狀態「還沒有案例…」、控制列（用草稿 disabled 無草稿、存為基準、合格門檻、執行回歸 disabled 當 0 案例）、「尚未儲存基準」、返回編輯器
- ✅ `Y02` 上傳影像（期望 NG、備註、3 張）→ toast「已新增 3 個案例」、表 3 列、縮圖載入、期望下拉值、備註、上次結果「尚無基準」、備註欄清空
- ✅ `Y03` 直接改期望／名稱／備註（blur）→ PATCH → API 更新
- ✅ `Y04` 刪除 → ConfirmDialog（名稱）→ toast「已刪除案例」→ 列減
- ✅ `Y05` 批次測試結果「存為 Golden Set」：未勾 disabled、全選 → 按鈕 → toast「已存 N 個案例」、「開啟 Golden Set 頁」連結 → 案例表多 N 列（期望＝該次狀態）
- ✅ `Y06` 回歸（存為基準＋門檻 0.5）→ 結果區：KPI 8 格、「通過」、「已存為基準」badge、「沒有退步的案例」、全部案例表列數＝總數、基準標籤「基準：流程 vN」、案例表上次結果有 badge、toast「已存為基準」
- ✅ `Y07` 改參數（孔數判斷門檻）後再回歸（不存基準）→ regressed 清單（was → now、原因）＝不符數、「未通過」；把不符存成基準、改回參數再回歸 → improved 清單、無退步
- ✅ `Y08` 篩選 全部／只看不符／只看與基準不同 → 「x / y」計數正確、無符合列顯示「—」
- ✅ `Y09` 點退步列縮圖／「在影像視窗檢視」→ Modal「正在檢視「名稱」」、影像載入、狀態 badge；Esc 關閉；符合的列無影像（ImageOff）且不可點
- ✅ `Y10` 「用目前畫布未儲存的圖」：編輯器改名不存 → 頂列 Golden 圖示進入 → checkbox 可勾（hint「有未儲存的變更」）→ 回歸結果 badge「用目前畫布未儲存的圖」
- ✅ `Y11` 合格門檻 >1 → 錯誤 toast（預期 422）
- ✅ `Y12` 非管理員開共用流程：「只有擁有者或管理員能修改案例」、無上傳、欄位 disabled、存為基準 disabled、刪除 disabled；仍可執行回歸
- ✅ `Y13` 1280×800 無水平捲軸（含回歸結果）；深色截圖

## Z. 連線（ConnectionsPage）— v0.2 回合
- ✅ `Z01` 頁面：標題、副標連到整合頁「PLC 輸出」、新增連線按鈕、表格 6 欄（名稱／種類／設定／狀態／啟用／操作）或空狀態「還沒有連線」
- ✅ `Z02` 新增 Modal 每種 kind 表單：dio_sim（通道）、modbus_tcp（主機／埠／Unit ID／逾時／字組順序下拉）、tcp_client（主機／埠／逾時／訊息範本／結尾字元／等待回覆）、plugin（類別路徑）；切換 kind config 重設為預設；名稱空 → toast
- ✅ `Z03` 建立 dio_sim → toast「已建立連線」、列：kind badge、config JSON；建立 modbus_tcp（連不到的埠、逾時 0.3）
- ✅ `Z04` 測試連線：dio_sim → toast「連線成功」＋狀態 badge「已連線」；modbus → toast「連線失敗：…」
- ✅ `Z05` 手動寫入 Modal：預設 values 帶第一通道；非法 JSON／陣列 → toast「values 必須是 JSON 物件」；寫入 → 結果框 ok:true、toast「已寫入 N 筆」；modbus 寫入 → 結果框紅底、toast「寫入失敗」
- ✅ `Z06` 狀態檢視：dio_sim → 通道表（含剛寫入的值）＋重新整理；modbus → 位址輸入＋讀取 → 錯誤結果、無通道表
- ✅ `Z07` 編輯：帶入既有值、改通道 → toast「已更新連線」、列 config 更新；改成同名 → 錯誤 toast（預期 409）
- ✅ `Z08` 啟用開關 → PATCH → 列更新
- ✅ `Z09` 刪除 → ConfirmDialog（訊息提到 write_plc 降級）→ toast「已刪除連線」→ 列消失
- ✅ `Z10` 非管理員：新增 disabled（title「只有管理員…」）、測試／手動寫入／編輯／刪除／開關 disabled、狀態檢視可用
- ✅ `Z11` 空狀態（mock）與錯誤狀態＋重試（mock 500）
- ✅ `Z12` 1280×800 無水平捲軸；深色截圖（含手動寫入 Modal）

## IO. 匯出／匯入、配方、站台、PLC 輸出（跨頁）— v0.2 回合
- ✅ `IO01` 流程列表「匯出」→ download 檔名 `<名稱>.flow.json`、內容 JSON 含 schema_version／name／graph、toast「已下載」；編輯器頂列匯出圖示同樣
- ✅ `IO02` 匯入 Modal：未選檔 → toast「請先選擇 .flow.json 檔」；選檔顯示檔名；來源下拉含「（不指定）」；同名匯入 → toast「已更新流程」、version +1、導向編輯器（且不清掉原本的影像來源）
- ✅ `IO03` 改名的檔匯入（指定來源）→ toast「已匯入流程…（新建）」、列表多一列、取像步驟 source_id＝指定來源
- ✅ `IO04` 整合頁「PLC 輸出」分頁：`?tab=plc` 深連結、標題、「前往連線頁」→ /connections、src／address 清單、降級提示、mapping 範例 code
- ✅ `IO05` 整合頁 HTTP 測試「配方」欄：片段（curl／Python）含 recipe、送出後 recent.recipe＝該配方；TCP 常用指令含 `RUN <id> recipe=<name>`、送出後回應含 recipe
- ✅ `IO06` 編輯器頂列綁定配方下拉：無配方時隱藏；有配方後顯示（「不用配方（圖值）」＋配方名、目前綁定為選中）；選「不用配方」→ toast、API 全部 is_default=false；選回 partA → toast「已綁定配方」；試跑／API 執行（無 recipe）都用綁定配方 → recent.recipe；結果分頁最近執行表「配方」欄
- ✅ `IO07` 工具箱 write_plc：插入 → 工具頁 connection 欄有 datalist（含連線名）、mapping 為 JSON textarea、on_error 下拉（warn／fail）；API 執行 → plc 節點 ok、dio_sim 狀態更新；連線不存在 → 節點 message「已降級」、run 不失敗、結果分頁看得到
- ✅ `IO08` 總覽卡片 card-meta「站台 ST01 · 配方 partA」；統計頁副標站台／配方、歷史表「配方」「站台」欄
- ✅ `IO09` 未教導流程 API 執行 → 結果分頁 run-warnings「未完成現場教導」；標記後執行無 warnings、頂列標籤消失
- ✅ `IO10` 流程列表「未教導」標籤＋名稱旁「綁定：partA」＋綁定欄「配方 (1)」鈕；總覽「未教導」badge；頂列 not-commissioned-badge
- ✅ `IO11` en 模式：參數卡／配方管理 Modal／Golden Set／連線表單／整合 PLC 分頁／匯入 Modal 無未翻譯 key
- ✅ `IO12` 深色模式：參數卡／Golden Set／連線頁／PLC 輸出截圖

## ST. 風格與側欄（Gentelella 風外框）— 風格改版回合
- ✅ `ST01` 側欄摺疊／展開：側欄底部「收合側欄」鈕與頂列摺疊鈕都可切換；寬 220 ↔ 60、`data-collapsed`、localStorage `vs.sidebar`（collapsed／expanded）、重新整理保留；展開時項目不換行、品牌區「VS」＋「功能」小標
- ✅ `ST02` 摺疊時 hover 顯示 tooltip（`.nav-tip`，role=tooltip、opacity 0→1、文字＝項目名、不被內容區蓋住）；展開時每項有 title、無 tooltip；摺疊鈕 title「展開側欄」
- ✅ `ST03` 導覽 9 項（管理員）順序：總覽／流程／影像來源庫／資產庫／整合／連線／使用者／設定／說明；目前頁 `.nav-item.active`（左側 3px 品牌色條）、切頁後 active 跟著換；每項 `data-testid=nav-*`
- ✅ `ST04` 頂列麵包屑：各頁「總覽 › 頁名」；流程子頁「總覽 › 流程 › 流程名 › 參數卡／工具頁／統計／Golden Set」，流程名連回編輯器、「流程」連回列表（編輯器本身流程名不是連結）
- ✅ `ST05` 頂列：容量 pill、主題切換（切換後側欄底色跟著換）、使用者選單（@帳號 · 管理員、修改密碼、登出；選單落在頂列下方、點外面關閉）都在頂列而非側欄；頂列高 48px
- ✅ `ST06` 面板摺疊（設定頁「執行緒池」「自動化接口」）：標題列摺疊鈕 `aria-expanded`、收合後內容消失標題仍在、再展開恢復；無摺疊鈕的卡片不受影響
- ✅ `ST07` 編輯器頂列：無配方時綁定下拉隱藏、「配方」鈕開側滑面板（標題含流程名、「還沒有配方」）；面板內新增（不以圖值 → 直接建立）→ 第一個自動綁定 → 頂列出現綁定下拉（「不用配方（圖值）」＋配方名、已選）；切「不用配方」→ toast、API 解除；選回 → toast；API 執行 → recent.recipe＝綁定配方
- ✅ `ST08` 工具頁：頂列只有「自動套用」一個 switch、沒有「同步視角」；前／後影像各自縮放（滾輪左邊右邊不動、右邊左邊不動）
- ✅ `ST09` 編輯器前／後分割：右側滾輪縮放左側比例不變
- ✅ `ST10` 深色模式每頁（總覽／流程／來源／資產／整合／連線／使用者／設定／說明／編輯器／參數卡／工具頁／統計／Golden Set）：html.dark、側欄底色為深色版（非淺色的 #2a3f54）、頂列與內容區深色；摺疊側欄 tooltip 與使用者選單深色截圖
- ✅ `ST11` en 模式：側欄 9 項英文、「Collapse sidebar」、tooltip「Source library」、麵包屑（Dashboard › Flows › 名稱 › Teach page／Tool page）、配方面板／Check List／匯入 Modal 英文、無未翻譯 key
- ✅ `ST12` 1280×800：流程／編輯器／參數卡／工具頁／設定無水平捲軸（document 與 main）；摺疊側欄後畫布加寬 ≥150px；配方面板寬 480–560px
- ✅ `ST13` worker：側欄 8 項（無「使用者」）、使用者選單 title 無「管理員」；共用流程的配方面板唯讀（無新增區、匯入 disabled、綁定下拉 disabled）

## RC. 配方面板（RecipeDrawer／Check List／匯入檢查）— 風格改版回合
- ✅ `RC01` 流程頁「綁定」欄：無配方時「—」＋「配方」鈕、名稱旁無綁定標籤；點鈕不觸發列導覽；面板標題（配方 · 流程名 · 0 個配方）、綁定下拉只有「不用配方（圖值）」、「還沒有配方」、全部匯出 disabled、「以目前教導參數的圖值作為覆寫（5 項）」；X 關閉、點遮罩關閉
- ✅ `RC02` 新增（以圖值）：空名稱 toast；→ Check List（標題含配方名、欄位 步驟 › 參數／目前值 → 新值／狀態、教導參數區 5 項全 unchanged 預設不勾、「納入 0 / 5 項」、點列切換、全選／全不選）；取消不建立；全選確認 → toast「已建立配方」、第一個自動綁定（data-bound）、自動展開、名稱欄清空、API 3 節點覆寫、「5 個覆寫」、標題「1 個配方」
- ✅ `RC03` 展開編輯覆寫表：5 列、節點／參數下拉（教導參數 ★）、列下方「圖值 …」、改值後儲存鈕變 primary、新增一列／移除；儲存（檢查儲存範圍）→ Check List（只有改過的 thr.threshold ok 預設勾、其餘 unchanged 不勾、「納入 1 / 5 項」）→ toast「已更新配方」→ API 只剩勾選的 1 項、「1 個覆寫」
- ✅ `RC04` 改名：輸入框帶入原名、Esc 取消、✓ 與 Enter 都可 → toast「已改名為」、API 更新
- ✅ `RC05` 第二個配方（不以圖值 → 無 Check List 直接建立、0 個覆寫、未綁定）；複製 → 「名稱 (2)」帶相同覆寫、未綁定；設綁定（列圖示）→ toast、原綁定 badge 消失、綁定中的列沒有設綁定鈕、面板綁定下拉同步；面板下拉「不用配方」→ toast、API 全部解除
- ✅ `RC06` 列上綁定下拉（4 選項）→ toast、名稱旁「綁定：E2E partA」、API is_default、仍在列表頁；「配方 (3)」鈕；API 執行 → recent.recipe＝綁定配方；總覽卡片 card-meta「配方 E2E partA」；統計頁副標含配方
- ✅ `RC07` 匯出單一 → 下載 `<流程>.<配方>.recipe.json`（kind=recipe、recipe.param_overrides、flow_fingerprint、flow_name）＋toast；全部匯出 → `<流程>.recipes.json`（kind=recipes、3 筆）＋toast「已下載 3 個配方」
- ✅ `RC08` 匯入 → 合理化檢查：未選檔時匯入鈕 disabled；選檔顯示檔名；badge「流程名稱不同（檔案：…）」「流程指紋相同」；配方列「新建」「2 / 5 項可寫入」；狀態 ok／unchanged／node_missing／param_missing／value_invalid（紅色不可勾）；「納入 1 / 2」→ 勾 unchanged → 2 / 2；「匯入後設為綁定配方」→ 匯入 → toast「已匯入 1 個配方：寫入 2 項、略過 N 項」→ API 只有 ok＋勾選的 unchanged、綁定；同名再匯入 → 「會覆寫既有同名配方」
- ✅ `RC09` 刪除 → ConfirmDialog（名稱、危險樣式、取消保留）→ 刪除 → toast「已刪除配方」→ 列減、標題計數更新
- ✅ `RC10` 匯入非 JSON 檔 → 錯誤 toast、匯入鈕 disabled；新增同名配方 → 錯誤 toast（預期 409）
- ✅ `RC11` 參數卡：「綁定：」標籤與編輯對象下拉「· 綁定」跟流程頁一致；存為新配方 → Check List（教導參數 5 項）→ 全選 → toast、編輯對象切到新配方、「5 個覆寫」；「管理配方」開同一個側滑面板（含新增區、清單含新配方）
- ✅ `RC12` worker 開共用流程：列上綁定下拉 disabled；面板無新增區、匯入 disabled、匯出可用、改名／複製／刪除／設綁定 disabled、展開後無儲存鈕、覆寫表欄位 disabled
- ✅ `RC13` Check List 兩區（include_all；條件隱藏的教導參數如 thr.low／high／block／c 降到「其他參數」）：新增文案「以目前圖值作為覆寫（教導參數 N 項）」；上方「教導參數」5 項 unchanged 不勾；下方「其他參數（N）」預設收合（表格不在 DOM）、展開後 N 項 teach=false 全 unchanged 不勾、ROI 值顯示摘要「rect W×H @ x,y」；勾一項 → 「納入 0 / 5 項、其他參數 1 項」、教導區仍 0；確認 → toast、API param_overrides 只含那一項（值＝圖值）
