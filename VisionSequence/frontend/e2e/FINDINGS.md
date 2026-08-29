# 全面性測試發現（frontend/e2e/full.mjs）

每一條：症狀 → 原因 → 修法 → 檔案。狀態：已修／殘留。測試清單與逐項結果在 `CHECKLIST.md`，截圖在 `Image/70-*.png`。

## 已修

### 1. 總覽卡片 `<a>` 裡包 `<a>`，React 19 印 hydration 警告
- 症狀：開總覽頁 console.error「In HTML, <a> cannot be a descendant of <a>. This will cause a hydration error」。
- 原因：`FlowCard` 整張卡是 `<Link>`，右上角統計圖示又是一個 `<Link>`。
- 修法：內層改 `<button>`，onClick preventDefault + stopPropagation 後 `navigate()`。
- 檔案：`frontend/src/pages/DashboardPage.tsx`。

### 2. 畫布連線被拒（型別不相容／分支把手／單輸入／迴圈）完全沒有提示
- 症狀：把 number 埠拉到 image 埠放開，線沒出現也沒有任何訊息；`onConnect` 裡的 warning toast 從來不會執行。
- 原因：React Flow 對 `isValidConnection` 回 false 的連線不會呼叫 `onConnect`，只會呼叫 `onConnectEnd`。
- 修法：新增 `onConnectEnd`：`state.isValid === false && state.toHandle` 時用 `checkConnection` 算出原因（fromHandle 是 target 時對調）再 toast。
- 檔案：`frontend/src/pages/FlowEditorPage.tsx`。

### 3. 每次開編輯器 console.warning「React Flow: It seems like you are hiding the attribution…」
- 原因：`proOptions.hideAttribution` 與 `index.css` 的 `.react-flow__attribution { display:none }` 都會讓 React Flow（dev 模式）警告。
- 修法：兩者都移除，畫布右下角顯示小小的 React Flow 連結。
- 檔案：`frontend/src/components/editor/FlowCanvas.tsx`、`frontend/src/index.css`。

### 4. 步驟清單超過可視高度時無法捲動，後面的步驟看不到也點不到；且編輯器用的是舊版 NodeList
- 症狀：插入十幾個步驟後，左欄下半的步驟清單被截斷、沒有捲軸；`data-testid=node-list`／`data-node-id` 在編輯器裡找不到。
- 原因：`FlowEditorPage` 從 `ToolPalette.tsx` 匯入了一份未加 testid 的舊 `NodeList`；兩版根元素都是 `overflow-y-auto` 但沒有高度，外層 `overflow-hidden` 直接裁掉。
- 修法：編輯器改匯入 `NodeList.tsx`，刪除 `ToolPalette.tsx` 裡的重複版本；根元素加 `h-full`。
- 檔案：`frontend/src/components/editor/NodeList.tsx`、`frontend/src/components/editor/ToolPalette.tsx`、`frontend/src/pages/FlowEditorPage.tsx`。

### 5. 複製出來的流程預設「停用」，編輯器按「執行一次」只得到一個 409 錯誤 toast
- 症狀：流程列表「複製」→ 開副本 → 執行一次／連續執行 → 「流程已停用」；頂列看不出為什麼，要回列表才能開啟。
- 原因：`duplicate_flow` 以 `is_enabled=False` 建立；`Runner.submit` 對停用流程一律 409（試跑除外）。
- 修法：頂列加「流程已停用」badge，執行一次／上傳影像執行／連續執行 disabled 並帶提示；側欄（未選取步驟時）加「啟用（允許外部觸發）」勾選直接 PATCH。i18n 新增 `editor.flowDisabled`／`flowDisabledHint`（zh／en）。
- 檔案：`frontend/src/components/editor/EditorToolbar.tsx`、`frontend/src/pages/FlowEditorPage.tsx`、`frontend/src/i18n/locales/zh-Hant.ts`、`en.ts`。

### 6. 從編輯器開工具頁會把未儲存的變更丟掉（新插入／複製的步驟「找不到步驟」）
- 症狀：在畫布插入或複製一個步驟（未存檔）→ 右鍵「開啟工具頁」→ 「找不到步驟「blob-2」」；同理，側欄改過名稱再開工具頁，工具頁看到的是伺服器版本。
- 原因：`ToolPage` 的草稿初始化 effect 用 render 時的 `session.draft` 快照判斷「有沒有草稿」；從編輯器導過來時，編輯器是在工具頁 render 之後（unmount cleanup）才寫入草稿，快照看到的是舊值，於是用伺服器的圖 `setDraft` 蓋掉剛寫好的草稿。
- 修法：effect 內改讀 `getSession(flowId).draft` 的即時值。
- 檔案：`frontend/src/pages/ToolPage.tsx`。

### 7. `text_presence`／`color_check` 的 flow 埠與 bool 埠同名 → React「two children with the same key」、handle id 撞名
- 症狀：畫布上放「有無印字」或「顏色檢查」步驟時 console.error「Encountered two children with the same key, `present`／`match`」；兩個同名輸出埠的 handle id 一樣，連線時分不清接的是分支還是布林值。
- 原因：工具定義 `outputs` 同時宣告 `flow_out("present")` 與 `Port("present", "bool")`（color_check 是 `match`）。
- 修法：bool 埠改名 `is_present`／`is_match`，`Result.outputs` 的 key 同步；`tests/test_tools.py` 對應更新（未執行 manage.py test，以 API 實測工具目錄與試跑）。
- 檔案：`apps/vision/tools/builtin/detect.py`、`tests/test_tools.py`。

### 8. 範本畫廊：載入範本在 window.confirm 按「取消」後，已選的卡片被清掉
- 症狀：畫布有未儲存變更 → 載入範本 → 確認框取消 → 畫廊還開著但「載入範本」按鈕變 disabled，要重新點卡片。
- 原因：`TemplateGallery.confirm()` 不管 `onPick` 結果一律重設選取。
- 修法：`onPick` 可回傳 `false` 表示取消；`loadTemplate` 取消時回 `false`，畫廊保留選取。
- 檔案：`frontend/src/components/templates/TemplateGallery.tsx`、`frontend/src/pages/FlowEditorPage.tsx`。

### 9. 工具頁 Esc 不會結束 ROI 編輯／範本框選（編輯器會）
- 修法：`ToolPage` 的 keydown 加 Escape（輸入框內不處理）。
- 檔案：`frontend/src/pages/ToolPage.tsx`。

### 10. 右鍵選單按 Esc 關不掉（焦點在畫布節點上時）
- 症狀：右鍵點步驟開選單 → Esc → 選單還在（點外面才會關）。
- 原因：右鍵後焦點在 React Flow 節點（tabIndex=0），節點的 a11y keydown 處理 Escape 後停止冒泡，`NodeContextMenu` 掛在 document 冒泡階段的監聽收不到。
- 修法：keydown 監聽改 capture。
- 檔案：`frontend/src/components/editor/NodeContextMenu.tsx`。

### 11. 批次測試選檔超過 50 張時 console.error「Cannot update a component (ToastProvider) while rendering a different component (BatchTestModal)」
- 原因：`addFiles` 在 `setFiles` 的 updater 函式裡呼叫 `toast.warning`。
- 修法：先算 merged 再 toast，最後 `setFiles`。
- 檔案：`frontend/src/components/editor/BatchTestModal.tsx`。

### 12. 整合頁「複製」在剪貼簿權限被拒時是未處理的 promise rejection（pageerror）
- 症狀：非 https／權限被拒（Playwright 預設情境）按複製 → `Failed to execute 'writeText' on 'Clipboard': Write permission denied` 直接噴到 console，按鈕沒有任何反應。
- 修法：`copyText()`：Clipboard API 失敗退回隱藏 textarea + `execCommand('copy')`，都失敗才 toast 錯誤。
- 檔案：`frontend/src/pages/IntegrationPage.tsx`。

### 13. SSE 斷線後不會重連（經 proxy 時後端死掉，頁面一直顯示「即時」但收不到任何事件）
- 症狀：後端重啟後，編輯器／總覽／事件監看的 badge 仍是「即時」，之後的執行事件都收不到，要手動重新整理。
- 原因：Vite proxy（以及某些反向代理）在後端斷線時不會關閉已開始的 SSE 回應，瀏覽器的 `EventSource` 不會觸發 `onerror`；伺服器心跳是 `: ping` 註解，`EventSource` 不會交給 JS，前端無從得知連線已死。
- 修法：伺服器心跳改成具名事件 `ping`（每 15 秒）；前端 `watchdog()`：40 秒沒收到任何訊息（含 ping）就主動關閉重連（`useFlowStream`、`useLockEvents`、整合頁事件監看三處）。docs／說明頁事件清單補 `ping`。
- 檔案：`apps/vision/stream.py`、`frontend/src/lib/flowStream.ts`、`frontend/src/pages/IntegrationPage.tsx`、`frontend/src/pages/HelpPage.tsx`、`docs/automation.html`、`docs/architecture.html`。

### 14. 後端重啟後 SSE 重連成功卻再也收不到事件
- 症狀：（承上）看門狗重連後 badge 回到「即時」，但之後的執行事件不會出現在最近執行表。
- 原因：客戶端重連帶著舊的 `since`（例如 300），後端重啟後 `bus.seq` 從 0 起算，`bus.wait(since)` 永遠等不到 seq > 300 的事件。
- 修法：伺服器 `_Session` 把 `since` 夾到 `min(since, bus.seq)`；`hello` 事件帶的就是夾過的位置，前端一律採用（原本只在 since 為 0 時採用）。
- 檔案：`apps/vision/stream.py`、`frontend/src/lib/flowStream.ts`。

## 殘留（未修，附理由）

- ~~影像視窗（ImageViewer／Toolbar）文案是寫死的繁中；`SourcesPage` 排序下拉同樣寫死~~ → **已修**：`viewer.*`、`sources.sortOptions.*` 走 i18n（zh-Hant／en），viewer 元件用 `useTranslation`。
- ~~`Param.kind = json` 沒有任何內建工具使用~~ → v0.2 起 `write_plc.mapping` 是 json 欄位，N11 由 IO07 實測（工具頁 textarea、非法 JSON 顯示錯誤）。
- **註解節點沒有輸入把手**：「連到註解被拒（noteTarget）」在 UI 上拉不到線，只由 `checkConnection` 規則保證（I07 ⏭）。
- **編輯器側欄已沒有 ROI 編輯入口**：ROI 只能在工具頁編輯；「換選取步驟自動結束 ROI 編輯」的編輯器行為因此不適用（J15 註記）。
- **停用流程仍可「試跑」但不能「執行一次」**（後端 `Runner.submit` 規則）：本次以頂列提示處理，未改後端語意。

## v0.2 回合（參數卡／Golden Set／連線／匯出匯入／配方／write_plc；模組 teach、golden、connections、flowio，截圖 `Image/90-*.png`）

### 15. 參數卡「管理配方」Modal 有未儲存變更時按 Esc 直接關閉，跳過「放棄變更？」確認
- 症狀：在管理配方 Modal 改覆寫表或改名後按 Esc，Modal 直接消失，變更不見（其他 Modal 都會先問）。
- 原因：`TeachPage` 在 document 掛了 keydown 監聽，Escape 時直接 `setManageOpen(false)`；`Modal` 自己的 Escape 處理（dirty → 先問）跟它掛在同一個 document 上，`stopPropagation` 擋不住同層監聽，而 TeachPage 的先註冊先執行。
- 修法：拿掉 TeachPage 的 Escape 分支（Esc 一律交給 Modal 處理），順便移除不再用的 `isTypingTarget` 匯入。
- 檔案：`frontend/src/pages/TeachPage.tsx`。

### 16. 匯入同名流程（更新）沒指定來源時，會把現場設好的影像來源清成空白
- 症狀：流程列表「匯出」→ 原檔直接「匯入」（不選來源）→ 該流程之後「執行一次」全部失敗：「取像」執行失敗：沒有設定影像來源。整套走查裡示範流程被匯入一次後，後面所有以它複製出來的流程也跟著失敗。
- 原因：匯出時 `image_source.source_id` 換成 `{SOURCE}` 佔位符；`serialize.import_flow` 對既有流程 upsert 時，`source_id=None` 一律 materialize 成空字串再整份覆蓋 `flow.graph`。
- 修法：`import_flow` 更新既有流程且未指定 `source_id` 時，新增 `_carry_over_sources()`：取像步驟沿用原流程同 id 步驟的來源，沒有同 id 就用原流程任一取像步驟的來源；有指定 `source_id` 行為不變；新建流程仍留空字串。補測試 `test_import_update_keeps_existing_source_when_unspecified`；docs 同步。
- 檔案：`apps/vision/serialize.py`、`tests/test_flow_cli.py`、`docs/golden.html`。

### 17. 測試骨架：新頁面的 i18n 命名空間沒納入未翻譯 key 檢查；截圖／清單／清理未涵蓋新功能
- 修法：`full-lib.mjs` 的 `I18N_NS` 加 `app|teach|golden|connections|viewer`（並匯出 `I18N_RE` 給模組自用）；截圖前綴改 `90-`；`full-mark.mjs` 支援兩碼 ID（`IO01`）；`full.mjs` 加 teach／golden／connections／flowio 模組、清理配方／Golden 案例／連線／`(副本)` 流程、還原 `commissioned`、`demoFlow()` 排除副本與 E2E 流程、`--merge` 時以 ID 蓋掉舊 issue；`full-auth` B01 導覽改 9 項（多了「連線」）；`full-layout`／`full-lang` 加參數卡／Golden Set／連線／整合 PLC 分頁。
- React Flow（dev）掛載 1 秒後檢查 attribution 是否可見，測試在 1 秒內離開編輯器會誤報 console.warning（元素已 unmount）：harness 忽略該訊息（附註不是產品問題）。
- `N11`（Param.kind=json）自 v0.2 起可由 `write_plc` 的 `mapping` 欄位觸發，改由 IO07 回報，不再 ⏭（`full-tool.mjs` 移除 skip）。
- 舊清單因新功能而變動的預期：D03 操作圖示 4 → 7（多了參數卡／Golden Set／匯出）、M03 批次結果表 7 → 8 欄（多了「存為 Golden Set」勾選欄）、J07 輸出影像改為輪詢等待像素改變（原 600ms 在整套走查負載下偶發不夠）。

### v0.2 回合殘留（未修，附理由）
- **編輯器不會反映外部對流程中繼資料的修改**：用 API（或另一個分頁）PATCH `commissioned`／名稱後，已開著的編輯器頂列「未教導」標籤不會自己消失（`useFlow` 只在重新進頁或視窗聚焦時重抓；SSE 沒有 flow_updated 事件）。走查改走 UI 路徑（頂列標籤 → 參數卡「標記為已教導」→ 返回）就正確；屬既有行為，未在本回合加事件。
- **參數卡清掉暫存影像後，「用上次影像」仍會用剛才那張暫存影像**：`lastSourceRef` 來自上一次試跑（就是暫存影像那次），與編輯器「用上次影像重跑」語意一致；取消勾選即回到來源取像。保留不改。
- **Golden Set 的 regressed／improved 用「目前期望值」重算基準是否符合**：只改期望值不改參數，不會出現在退步清單（基準與這次同時不符），只在「只看不符」看得到；符合「改參數後最該看的清單」的定義，保留。
- **整合頁 TCP 常用指令的 `RUN <id> recipe=<name>` 用的是清單第一個流程的 id**（不跟 HTTP 分頁選的流程連動）；chips 只是範例，保留。

## 風格改版回合（Gentelella 風外框／參數卡三欄／配方面板／畫布預設拖移；模組 style、recipes 新增，截圖 `Image/110-*.png`）

### 18. 側欄摺疊時的 tooltip 被側欄裁掉，滑鼠移上去看不到（ST02）
- 症狀：側欄收合成只剩圖示後，hover 導覽項目 `.nav-tip` 的 opacity 確實變 1，但 `elementFromPoint` 落在 tooltip 中心拿到的是內容區元素——tooltip 被裁在側欄 60px 外、實際看不見。
- 原因：導覽清單容器是 `overflow-y-auto overflow-x-visible`；CSS 規定 overflow 只要有一軸不是 visible，另一軸就會被當成 auto，所以 `overflow-x-visible` 無效，`left-full` 的 tooltip 被裁掉。
- 修法：摺疊時清單改 `overflow-visible`（9 項一定塞得下，不需要捲動），展開時維持 `overflow-y-auto`。
- 檔案：`frontend/src/components/layout/AppShell.tsx`。

### 19. 「用上次影像重跑」的影像被快取淘汰後，工具頁／參數卡自動試跑只得到 404 image_gone，卡在錯誤上（W05）
- 症狀：編輯器跑過幾次（快取只留 `VISION_KEEP_RUN_IMAGES=8` 次的影像）後雙擊步驟開工具頁，頂列顯示「影像已不在快取中」、前／後影像都空的；console 一筆 404 POST /preview。
- 原因：`session.previewRun` 記著上次試跑的來源影像 ref；ref 被淘汰後仍原樣送 `reuse_image_ref`，後端照契約回 404 `image_gone`，前端沒有退路。
- 修法：`previewFlow()` 收到 `image_gone` 且有帶 `reuse_image_ref` 時，自動改用來源重新取像再送一次（編輯器／工具頁／參數卡共用）。後端契約不變（docs 已記載 404 image_gone）；測試骨架把這個 404 列為預期（`full-lib.mjs` allow）。
- 檔案：`frontend/src/lib/queries.ts`、`frontend/e2e/full-lib.mjs`。

### 20. 編輯器「前／後」分割對沒有影像輸出的步驟（blob、比較…）右邊顯示「尚無影像」，與工具頁不一致（J07）
- 症狀：選 blob 步驟開分割，右側「執行後」整片「尚無影像」；同一步驟在工具頁右側是「執行後 · 標記疊在輸入影像上」。
- 原因：改版時右側視窗只在 `hasOutput` 時給 src。
- 修法：無影像輸出時右側顯示輸入影像＋該步驟標記，標籤加「· 標記疊在輸入影像上」（沿用 `tool.overlaysOnInput`）。
- 檔案：`frontend/src/pages/FlowEditorPage.tsx`。

### 21. 「面板摺疊」（`Panel`／`CardHeader onToggle`）沒有任何頁面用到，UI 上測不到（ST06）
- 修法：設定頁「執行緒池」「自動化接口」兩張卡改用可摺疊的 `Panel`（`testId` 傳到 `Card`／內容區，方便測試）；`Card`／`Panel` 新增 `testId` prop。
- 檔案：`frontend/src/pages/SettingsPage.tsx`、`frontend/src/components/ui/Card.tsx`。

### 22. 參數卡在 1280×800 影像視窗只剩 400px（X17）
- 原因：三欄固定寬 左 240＋中 420，加上側欄 220 後右欄只剩 400。
- 修法：中欄改 `w-[360px] 2xl:w-[420px]`；1280 時右欄 460px，側欄摺疊後 620px。
- 檔案：`frontend/src/pages/TeachPage.tsx`。

### 23. 測試骨架與清單因改版而變動的預期
- `full-lib.mjs`：截圖前綴 `110-`；`full.mjs` MODULES 加 `style`、`recipes`；清理時配方名 `^part[A-Z]` 放寬（partB2）。
- 側欄：`nav a` → `[data-testid=sidebar] a`（麵包屑也是 `<nav>`，舊選擇器會 strict-mode 撞到兩個）；容量 pill 搬到 `[data-testid=topbar]`；`nav a.bg-brand-soft` → `.nav-item.active`（B01／B02／R01／U03／F21／N22）。
- 畫布預設「平移」：canvas 模組 `open()` 先切「選取」才做框選（I08／I10／I12）；I09 改驗證預設平移、Shift 框選、`vs.canvasMode` 持久化。
- 雙擊步驟改開工具頁：I18 改驗證草稿帶到工具頁與返回後仍 dirty；IO07 改點選＋結果分頁看降級訊息。
- 工具頁沒有「同步視角」：N01 只剩 1 個 switch；N18 改驗證前／後各自縮放。
- 參數卡三欄：`teach-groups` → `teach-steps`／`teach-params`，聚焦用 `data-focused`，中欄一次只顯示一個步驟（`numberOf()` 先點左欄）；X07／X08／X11 走 Check List；管理配方是 `recipe-drawer`（沒有 Esc 放棄確認，見殘留）；X16 每步「—」而不是沒有狀態。
- 編輯器配方下拉改「綁定」（IO06）；流程列表「· N 配方」改「綁定：partA」＋「配方 (1)」（IO10）；D03 表頭多「綁定」；O02 KPI 改 `.tile-count`；J03 放大前先適合視窗（格線只畫在影像範圍內，視窗中心在影像外時抓不到差異）。
- 清單新增 `ST01–ST13`（風格與側欄）、`RC01–RC12`（配方面板）；因 R／S 段已被使用者／整合頁占用，兩段用兩碼 ID。

### 24. 影像視窗的像素格線在白色／二值化亮區看不見（J03）
- 症狀：blob 步驟的輸入是形態學開運算後的白底遮罩；放大到 ≥8x 開「像素格線」畫面完全沒變（測試以 canvas 雜湊比對抓到）。
- 原因：格線固定用 `rgba(255,255,255,0.18)` 疊在影像層，白色像素上等於沒畫。
- 修法：格線改 `globalCompositeOperation = 'difference'` 疊色（白底變暗線、黑底變亮線）。
- 檔案：`frontend/src/components/viewer/ImageViewer.tsx`。

### 25. 流程列表名稱旁有「綁定：partA」標籤時，名稱被擠成一字一行（ST02 截圖）
- 原因：名稱欄沒有最小寬度，表格自動配寬把空間讓給其他欄，`whitespace-nowrap` 的標籤又不能縮，名稱只好逐字換行。
- 修法：名稱 `<Td>` 加 `min-w-52`、容器 `flex-wrap`、名稱包 `<span className="min-w-0 break-words">`。
- 檔案：`frontend/src/pages/FlowsPage.tsx`。

### 風格改版回合殘留（未修，附理由）
- **配方面板（RecipeDrawer）展開的覆寫表改了值、直接關面板（X／遮罩）不會問「放棄變更？」**：舊的管理配方 Modal 有 dirty 守門；側滑面板的 dirty 狀態在各列（`RecipeRow`）內部，面板本身不知道。改動只在記憶體、沒有寫入，且儲存有 Check List 把關，先保留。
- **RC12 的 worker 唯讀走查用示範流程**：`duplicate` 出來的副本是 admin 私有流程，worker 看不到；測試改在共用示範流程上用 API 放一個 `E2E worker` 配方再看面板（結束時刪）。
