# frontend/src 目錄對照（檔案 → docs/glossary.html 名稱）

命名規範在 `docs/glossary.html`：一個東西只有一個名字，UI 文案、程式識別字、文件三處一致。

## 頁面 `pages/`

| 檔案 | glossary 名稱 | 路由 |
|---|---|---|
| `DashboardPage.tsx` | 總覽 DashboardPage | `/` |
| `FlowsPage.tsx` | 流程 FlowsPage | `/flows` |
| `FlowEditorPage.tsx` | 流程編輯器 FlowEditorPage | `/flows/:id` |
| `ToolPage.tsx` | 工具頁 ToolPage | `/flows/:id/tools/:nodeId` |
| `SourcesPage.tsx` | 影像來源庫 SourcesPage | `/sources` |
| `AssetsPage.tsx` | 資產庫 AssetsPage | `/assets` |
| `UsersPage.tsx` | 使用者 UsersPage | `/users` |
| `SettingsPage.tsx` | 設定 SettingsPage | `/settings` |
| `HelpPage.tsx` | 說明 HelpPage | `/help` |
| `LoginPage.tsx` | 登入 LoginPage | `/login` |
| `StatsPage.tsx` | 統計 StatsPage（`TrendStrip` 迷你趨勢也在這） | `/flows/:id/stats` |
| `IntegrationPage.tsx`＋`pages/integration/*` | 整合頁 IntegrationPage（外框＋五個子頁：HTTP 測試與回傳格式、TCP 指令與失敗碼、事件監看、Modbus、擷取端；連線由用到它的頁面自己管） | `/integration/<section>` |
| `TeachPage.tsx` | 參數卡 TeachPage（三欄：步驟清單／聚焦步驟的教導參數／影像視窗＋結果摘要；頂列兩排；編輯對象下拉、存為新配方（走 Check List）、管理配方（`RecipeDrawer`）、綁定標籤、標記為已教導） | `/flows/:id/teach` |
| `GoldenPage.tsx` | Golden Set GoldenPage（案例表、上傳、回歸：KPI／混淆矩陣／退步清單／全部案例、影像視窗） | `/flows/:id/golden` |
| `components/integration/ConnectionsSection.tsx` | 連線（PLC／上位機連線 CRUD、測試連線、手動寫入、狀態檢視）；`section` 決定這一頁收哪些 kind | 內嵌在 Modbus／TCP 兩個整合頁 |
| `components/auth/RolePermissionsCard.tsx` | 角色權限勾選表（管理員決定工程師與操作員能用哪些功能） | 內嵌在 `/users` |

## 流程編輯器的區塊 `components/editor/`

| 檔案 | glossary 名稱 | 說明 |
|---|---|---|
| `EditorToolbar.tsx` | 頂列 EditorToolbar | 兩列：第一列流程名稱、儲存、範本下拉（載入／存為範本）、「配方」鈕（開 `RecipeDrawer`）、綁定配方下拉（`BoundRecipeSelect`，有配方才顯示）、「未教導」等標籤、參數卡／Golden Set／匯出／統計；第二列試跑、用上次影像重跑、上傳暫存影像、批次測試（導向 /batch）、連續執行、重置、說明下拉。按鈕圖示＋短文字、`flex-wrap` 換行；「執行一次」「上傳影像執行」已移除（整合方走 API）；選取／平移切換在畫布右上角（`ScratchBadge`、`Dropdown`、`MenuItem` 也在這） |
| `pages/BatchPage.tsx`＋`components/batch/*` | 批次測試頁 | 影像集清單、執行紀錄（進度、比較勾選）、結果表（期望可改、CSV、存 Golden）、影像集標記網格、洞察（建議門檻、圖表）、比較、調參面板（含自動調參）、單張預覽 Modal；資料層 `lib/batch.ts`；AI 諮詢／調整已併入全域助手 |
| `components/assistant/AssistantDock.tsx`＋`lib/assistantContext.ts` | 全域 AI 助手 | 右下角常駐聊天視窗（對話存 localStorage）：平台使用問答（`POST /agent/chat`，回答附 `/docs/` 連結）、流程編輯器修改並套用、批次頁資料諮詢與依資料調整；頁面用 `useRegisterAssistantContext` 登記脈絡（kind／graph／套用回呼） |
| `NodeContextMenu.tsx` | 步驟選單 NodeContextMenu | 右鍵：開啟工具頁、複製、停用、刪除、複製／貼上參數 |
| `../templates/TemplateGallery.tsx` | 範本畫廊 TemplateGallery | `TemplateGallery`（create／load 兩種模式）、`SaveTemplateModal`、`TemplateThumb` 節點示意 SVG |
| `ToolPalette.tsx` | 工具箱 ToolPalette | 可插入的工具（分類、搜尋）；一律拖曳到畫布新增（點擊無動作、title 顯示說明）；收藏（星號，`vs.favoriteTools`）。「最近使用」已移除 |
| `NodeList.tsx` | 步驟清單 NodeList | 本流程所有步驟；點一下畫布聚焦 |
| `../viewer/ImageViewer.tsx` | 影像視窗 ImageViewer | 影像、標記、ROI 編輯；前／後並排的兩個視窗各自 fit／縮放（`viewport`／`onViewportChange` 保留但目前沒有頁面使用） |
| `FlowCanvas.tsx` | 畫布 FlowCanvas | React Flow 薄包裝（nodeTypes、小地圖、縮放滑桿、右上角 `CanvasModePanel` 選取／平移切換）；互動模式預設平移（左鍵拖移、Shift+拖曳框選），`readInteractionMode`／`storeInteractionMode` 存 localStorage `vs.canvasMode`；雙擊步驟卡片開工具頁 |
| `Inspector.tsx` | 側欄 Inspector | 選取步驟的基本設定（名稱、備註、顏色、啟用、出錯時繼續）＋「開啟工具頁」 |
| `ResultsPanel.tsx` | 結果分頁 ResultsPanel | `RecentRunsTable`（有配方時多一欄）、`NodeResult`、`RunOutputs`、`RunErrorBlock`（失敗時的醒目錯誤區塊）、`RunWarnings`（run.warnings 黃色提示） |
| `../auth/LockBanner.tsx` | 鎖定橫幅 LockBanner | 引擎鎖定時的黃色橫幅 |
| `ParamForm.tsx` | 參數 Param（表單） | 步驟完整參數表單（工具頁左欄） |
| `ParamField.tsx` | 參數 Param（單欄位） | 依 `Param.kind` 產生欄位；roi／asset 透過 `InspectorActions` 與影像視窗互動；`key==='connection'` 的 text 用連線清單當 datalist |
| `ToolNode.tsx` | 步驟 Node（畫布卡片） | `ToolNode`／`NoteNode`；失敗時紅框＋錯誤訊息第一行 |
| `FlowEdge.tsx` | 連線 Edge | 依來源埠型別上色 |
| `Histogram.tsx` | — | 工具頁參考資訊用的 SVG 長條圖 |
| `ZoomSlider.tsx` | — | 畫布縮放滑桿 |
| `graphMapping.ts` | 流程 Flow ⇄ React Flow | graph JSON 與 React Flow 節點／邊的映射、自動排列 |

## 配方 `components/recipes/`

| 檔案 | glossary 名稱 | 說明 |
|---|---|---|
| `RecipeDrawer.tsx` | 配方面板 RecipeDrawer | 流程頁列上「配方」與參數卡「管理配方」共用的側滑面板：綁定下拉、新增／改名／複製／刪除／設綁定／匯出／全部匯出／匯入、展開編輯覆寫表；`useSaveCheck`（儲存範圍 Check List 流程，check 帶 `include_all: true`）、`teachOverridesOf`、`countOverrides`／`compactOverrides`／`pickOverrides` 也在這 |
| `RecipeCheckList.tsx` | 儲存範圍 Check List | `CheckItemsTable`（逐項勾選，狀態上色）、`RecipeCheckListModal`（兩區：上方「教導參數」、下方摺疊「其他參數（N）」＝`include_all` 補列的非教導參數，預設收合不勾）、`defaultSelection`（ok 預設勾）、`roiSummary`（ROI 值摘要「rect 286×215 @ 373,277」） |
| `RecipeImportModal.tsx` | 匯入合理化檢查 | 選檔 → `import/check` → 名稱／指紋／每配方清單 → `import {doc, accept}` |
| `BoundRecipeSelect.tsx` | 綁定配方 | `BoundRecipeSelect`（選 is_default；「不用配方（圖值）」清掉預設）、`BoundBadge`（「綁定：partA」）、`boundRecipe` |

## 外框 `components/layout/`

| 檔案 | 說明 |
|---|---|
| `AppShell.tsx` | Gentelella 風外框：深色側欄（可摺疊成只顯示圖示，`vs.sidebar`；摺疊時 hover tooltip）、頂部白色導覽列（摺疊鈕、麵包屑 `Breadcrumb`、容量、主題切換、使用者選單）、`Page` 容器；`CapacityPill` |
| `../ui/Card.tsx` | `Card`／`CardHeader`（面板標題列，可 `collapsed`／`onToggle`）／`Panel`（可摺疊面板）／`Tile`（tile_count KPI）／`PageHeader`／`DetailRow` |

## `lib/`

| 檔案 | 用途 |
|---|---|
| `flowDraft.ts` | 編輯器 ⇄ 工具頁共享的草稿（未儲存的圖）、暫存影像、最近試跑（`useFlowSession`） |
| `ports.ts` | 埠型別顏色（`PORT_COLOR` CSS 變數、`PORT_HEX` 圖例）與相容規則，照 glossary 表 |
| `queries.ts` | TanStack Query hooks；`previewFlow`（until_node／analysis／recipe／signal）、`useRunFlow`（recipe）、`useScratchImage`、`useClearRecent`、範本（`useTemplates`／`useTemplateMutations`）、批次（`useBatchTest`／`useBatchFromSource`／`fetchRun`）、統計（`useFlowStats`／`useRunHistory`）、整合（`useIntegrationInfo`／`useTcpCommand`）、配方（`useRecipes`／`useRecipeMutations`／`applyOverrides`／`checkRecipe`／`useRecipeImport`）、Golden Set（`useGolden`／`useGoldenBaseline`／`useGoldenMutations`：upload／fromBatch／patch／remove／regress）、匯入（`useImportFlow`）、連線（`useConnections`／`useConnectionKinds`／`useConnectionMutations`／`fetchConnectionState`） |
| `flowStream.ts` | SSE（含 `cleared` 事件） |
| `graphValidation.ts` | 連線與參數的前端檢查 |
| `types.ts` | API 型別（`NodeAnalysis`、`ScratchImage`、`FlowTemplate`、`BatchResult`、`FlowStatsDb`、`IntegrationInfo`、`FlowRecipe`、`RecipeCheckItem`／`RecipeCheckResult`／`RecipeImportCheck`／`RecipeImportResult`／`RECIPE_ACCEPTABLE`、`GoldenCase`／`GoldenList`／`RegressResult`、`Connection`／`ConnectionKind`…）；`ToolParam.teach`、`Flow.commissioned`／`recipe_count`、`RunReport.station_id`／`recipe`／`warnings` |
| `api.ts` | `request`／`api`、`imageUrl`、`goldenImageUrl`（Golden 案例縮圖帶 token）、`downloadFile`（fetch blob 下載，帶 token；匯出用） |

## i18n

`i18n/locales/zh-Hant.ts` 是預設與 fallback；`en.ts` 只翻一部分（後補的段落放在 `enExtra` 以深合併加入，避免物件重複 key）。UI 文案用 glossary 的中文名（步驟、工具箱、步驟清單、側欄、影像來源庫、資產庫、暫存影像、重置、範本庫、批次測試、統計、整合頁、收藏、參數卡、配方、綁定配方、儲存範圍 Check List、合理化檢查、Golden Set、回歸、基準、連線、匯出／匯入…）；`recipes.*`、`breadcrumb.*`、`nav.collapse`／`nav.expand` 是這一輪新增。影像視窗（`viewer.*`）與影像來源排序（`sources.sortOptions`）也走 i18n。
| `lib/useMediaQuery.ts`、`lib/sources.ts` | 響應式與清單摘要 | `useMediaQuery`（手機抽屜側欄、精簡麵包屑）；`summarizeSourceConfig`／`sourceStatus`（影像來源清單的設定／狀態摘要，取代原本印 JSON） |
