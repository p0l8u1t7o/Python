# CellForge WP-A／WP-C 前端規劃

模組分頁、check 面板、單模組 3D 預覽、佔位標示
日期：2026-09-19　狀態：規劃，尚未實作

**本工作包的三份文件，閱讀順序：**
1. `CellForge_WP-A-C_規格_v1.1.md` — 範圍、Tier 分級、模組品質標準、庫內容清單
2. `CellForge_WP-A-C_附錄_part-check與示範模組設計.md` — 十項檢查判定規格、兩個示範模組設計
3. 本文件 — 前端與後端 API

---

## 0. 為什麼需要這一塊

v1.1 與附錄把「代理能自建模組」與「庫要有真實機構」規劃完了，但漏了一件事：**附錄第 2 項（安裝介面）與第 7 項（配色）刻意設計成警告級，明文交代由目視把關——而目視的介面不存在。** 沒有這塊前端，這兩項形同虛設，`cell part check` 也只能活在代理的 log 裡。

另外三件缺口：模組庫在 UI 上完全看不到（現有八個分頁是資料、檢查、問題、假設、變更、任務、對話、流程）；佔位模組（`box`）在 3D 裡和「做得比較簡略的真模組」長得一樣，代理走捷徑看不出來；任務分頁看不到建模過程。

### 0.1 不需要改的部分（先確認，避免白工）

`web/src/viewer-core.ts` 已泛用處理模組軸：第 62 行取 `value_mm ?? value_deg ?? value`，第 86、92 行分別套用 revolute 與 prismatic。因此 `safety_door` 的擺動、`part_stopper` 的擋停、`camera_station` 的俯仰，只要 `ModuleDef.axes` 宣告正確就會在主場景動起來，**動畫層一行都不用改**。

唯一需要的小重構見第 3.3 節：把「依軸值套用變換」從「依 timeline 取樣」中抽出來，讓單模組預覽能直接給軸值。

---

## 1. 新增「模組」分頁

加在現有八個分頁之後，成為第九個。位置在主畫面右側面板，與其他分頁同層，不另開導覽層級。

### 1.1 版面

面板寬度有限（右側欄），因此採**清單／詳情切換**而非左右並列：預設顯示清單，點一項後整個面板換成該模組的詳情，左上角有返回鍵。詳情中的三視圖與 3D 預覽可按「放大」以覆蓋層（overlay）佔滿中央 3D 區，方便細看。

```
┌─ 模組 ─────────────────────────┐   ┌─ ← lift_rack ──────────────┐
│ [搜尋…] [全部▾] [只看有問題]     │   │ ┌──────────────────────┐   │
│                                │   │ │  三視圖 PNG   [放大]   │   │
│ ▾ 本案自建 (2)                  │   │ └──────────────────────┘   │
│   ● camera_station   ✔ 通過     │   │ ┌──────────────────────┐   │
│   ● part_stopper     ⚠ 2 警告   │   │ │  3D 預覽   [放大]      │   │
│                                │   │ │  lift ├────●──┤ 240mm  │   │
│ ▾ 搬運 (3)                      │   │ └──────────────────────┘   │
│   ○ lift_rack        ✔ 通過     │   │                            │
│   ○ conveyor         ✔ 通過     │   │ 檢查結果 8✔ 2⚠ 0✖          │
│   ⬚ pallet_magazine  — 未檢查   │   │  ✔ 1 尺寸依據               │
│                                │   │  ⚠ 2 安裝介面：看起來是…     │
│ ▾ 框架 (2)                      │   │  ✔ 3 具名子零件             │
│   ○ extrusion_frame  ✔ 通過     │   │  …                         │
│   ⬚ box  [佔位]      — 佔位     │   │                            │
│                                │   │ 參數 / frames / 軸 / 依據    │
│ ▾ 視覺 (3) …                    │   │ 本案使用：infeed_rack,      │
│ ▾ 安全 (2) …                    │   │          outfeed_rack      │
│                                │   │                            │
│ 本版佔位模組：1                  │   │ [請代理修正][重新檢查][在場景中定位] │
└────────────────────────────────┘   └────────────────────────────┘
```

### 1.2 清單

分組：第一組固定是「本案自建」（案內 `parts/`），其後依 `library/manifest.yaml` 的 `category` 分組（frame／conveying／handling／fixturing／vision／safety／electrical／material_handling，顯示中文名）。

每列顯示：使用狀態圖示（`●` 本案使用中、`○` 庫內未用、`⬚` 佔位）、模組 id、check 狀態徽章（`✔ 通過`／`⚠ n 警告`／`✖ n 失敗`／`— 未檢查`）。`box` 這類 `meta.placeholder: true` 的模組固定顯示 `[佔位]` 標記。

工具列：文字搜尋（比對 id 與 summary）、category 下拉、「只看有問題」切換（篩出有警告或失敗者）。

底部固定一行：`本版佔位模組：n`，n > 0 時整行轉琥珀色並可點擊（篩選到佔位模組）。這是防代理走捷徑的第一道提醒。

### 1.3 詳情

由上而下：

**三視圖 PNG** — `cell part render` 的產物。預設顯示縮圖，「放大」以覆蓋層佔滿中央區。這是附錄第 2、7 項目視把關的主要介面。

**3D 預覽** — 見第 2 節。

**檢查結果** — 十項逐項列出，沿用主畫面既有的紅黃綠樣式與圖示，每項顯示項次、名稱、中文訊息與關鍵數值（例如第 6 項顯示膨脹比、第 9 項顯示三角形數與前三大子零件）。第 10 項為資訊級，以灰色顯示。

**參數表** — 參數名、型別、預設值、上下限、目前案內實際帶入的值（若此模組被本案使用）。

**frames 表** — 名稱、xyz、所屬 link；frame 若在第 4 項被判警告（離表面 > 20 mm），該列標黃。

**軸表** — id、型別、parent／child、範圍、最大速度。

**尺寸依據** — `meta.basis` 原文。

**本案使用** — 列出引用此模組的 `cell.yaml` module instance id；點擊跳到主場景並高亮。

**動作列** — 「請代理修正」（以該模組的失敗與警告內容建立 CR 並派工程代理，沿用現有 CR 流程）、「重新檢查」（重跑 `cell part check` 與 `render`）、「在場景中定位」、以及本案自建模組專屬的「收進庫」（`cell part promote`，僅在零失敗時可用）。

---

## 2. 單模組 3D 預覽

### 2.1 目的

三視圖是靜態的，判斷不了可動機構的行程是否合理、門開到 110° 會不會撞到旁邊、擋停氣缸伸出後高度對不對。這個預覽讓你在模組層級就看出問題，不必等整線建好。

### 2.2 互動

- OrbitControls 旋轉、縮放、平移；四個快捷視角（ISO、前、側、上）。
- **每個 `ModuleDef.axes` 給一支滑桿**，範圍取軸的 `range`，即時套用到 GLB 節點。滑桿旁顯示目前值與單位。這是這個預覽的核心價值。
- 切換：碰撞體顯示（沿用 D-020 的 `extras.hidden` 判定）、frame 顯示（每個 frame 畫一組 RGB 三軸小三腳架，長度 50 mm，hover 顯示名稱）、線框模式。
- 底部顯示包圍盒尺寸（長×寬×高 mm）與三角形數。
- 地面格線與 z=0 平面，讓落地與否一眼可辨（呼應附錄第 10 項）。

### 2.3 實作方式

資料來源是新端點回傳的**單模組 GLB**（第 4 節），非主場景的 `scene.glb`。

`viewer-core.ts` 需要一個小重構：目前的流程是「timeline 取樣 → 得到軸值 → 套用變換」，其中「套用變換」已是獨立邏輯（第 86～92 行）。把它抽成可直接呼叫的函式（給節點與軸值，套用 rest TRS 加軸運動），主場景與單模組預覽共用。**不要另寫一套**——D-016 的教訓就是兩套關節語意會逐漸分歧。

單模組預覽是獨立的輕量元件（新檔 `components/ModulePreview.tsx`），不重用 `Viewer.tsx`——後者綁了時間軸、站別、checks 標記、版本疊圖，對單模組全是多餘。

---

## 3. 佔位模組標示

### 3.1 3D 主場景

`meta.placeholder: true` 的模組在主場景以**洋紅色虛線輪廓**標示，與 `trust: inferred` 的琥珀實線輪廓（D-019）明確區分。沿用 D-019 已驗證的做法：先按位置焊接顯示網格，再由 `EdgesGeometry` 畫輪廓，不用全表面 emissive。

viewer 工具列加一個切換：「標示佔位模組」，預設開啟。

### 3.2 其他位置

- 模組分頁清單的 `[佔位]` 標記與底部計數（第 1.2 節）。
- 檢查分頁最上方，若本版有佔位模組，顯示一則資訊級項目「本版有 n 個佔位模組未以真實機構取代」，點擊跳到模組分頁。
- 匯出對話框既有的「仍為推估的項目數」提示，加上佔位模組數。
- 代理 first_build 的最終 JSON `summary` 必須列出佔位模組（v1.1 第 4.2 節已規定），前端在對話分頁的回報摘要中原樣顯示。

---

## 4. 後端新增 API

沿用開發書第 5 節的既有風格，所有寫入仍轉成 `cell` 指令。

```
GET  /api/library/modules                         # library/manifest.yaml 全部，含 category、tier、status
GET  /api/projects/{p}/modules                    # 本案 parts/ + 本案引用的庫模組，含 check 狀態與使用位置
GET  /api/projects/{p}/modules/{id}               # 單一模組詳情：ModuleDef、參數、frames、axes、meta
GET  /api/projects/{p}/modules/{id}/check         # cell part check --json 的結果（讀快取，無則即時跑）
GET  /api/projects/{p}/modules/{id}/render.png    # cell part render 的三視圖（讀快取）
GET  /api/projects/{p}/modules/{id}/preview.glb   # 單模組 GLB（讀快取）
POST /api/projects/{p}/modules/{id}/recheck       # 重跑 check + render + preview → job
POST /api/projects/{p}/modules/{id}/fix           # 以 check 結果建 CR 並派工程代理 → job
POST /api/projects/{p}/modules/{id}/promote       # cell part promote → job
```

**快取**：`check`、`render.png`、`preview.glb` 三者都以「模組檔 SHA-256 ＋ 參數 JSON」為鍵，存在 `.cellforge-runtime/module-cache/<hash>/`。模組檔未變更時直接回傳，不重跑 CadQuery。這對預設參數的庫模組尤其重要——十幾個模組每次開分頁都重建會慢到不能用。

**庫模組的 check**：庫模組以預設參數檢查，結果可跨案共用，快取鍵不含案子。案內 `parts/` 模組的檢查則以案內實際參數為準。

---

## 5. 型別與既有檔案的改動

| 檔案 | 改動 |
|---|---|
| `web/src/types.ts` | 新增 `ModuleSummary`、`ModuleDetail`、`PartCheckResult`、`PartCheckItem`、`ModuleAxisInfo`、`FrameInfo` |
| `web/src/api.ts` | 新增第 4 節八個端點的呼叫 |
| `web/src/components/MainWorkspace.tsx` | `tabs` 陣列加「模組」；新增 `ModulePanel` 元件（清單＋詳情）；檢查分頁加佔位模組提示 |
| `web/src/components/ModulePreview.tsx` | 新檔：單模組 3D 預覽 |
| `web/src/components/Viewer.tsx` | 加佔位模組輪廓與工具列切換；加「在場景中定位到某 module instance」的對外方法 |
| `web/src/viewer-core.ts` | 抽出「依軸值套用變換」函式供兩處共用 |
| `web/src/styles.css` | 模組清單、徽章、滑桿、覆蓋層樣式 |

**不改** `offline.ts`：匯出的單檔 HTML 只含整線的 viewer，不含模組分頁。模組庫是工作中的工具，不是交付給客戶的內容。這一點要寫進 DECISIONS。

---

## 6. 驗收

1. 模組分頁列出庫內全部 production 模組（≥ 17 個）與本案自建模組，分組、搜尋、篩選可用。
2. 任一模組的詳情顯示三視圖、十項檢查、參數／frames／軸表與尺寸依據。
3. `safety_door` 的 3D 預覽可用滑桿把門從 0° 拉到 110°，門扇繞鉸鏈正確轉動（若門從錯誤位置甩出，代表附錄第二部分 B 的「零位世界變換」規則實作錯誤，這個預覽就是它的第一道檢驗）。
4. `extrusion_frame` 的預覽開啟碰撞體顯示後，看得出是逐桿件的碰撞盒，不是一個包住整框的大盒（呼應附錄第 6 項）。
5. 刻意把某模組換成 `box` 佔位後，主場景出現洋紅虛線輪廓、模組分頁底部計數為 1、檢查分頁出現提示。
6. 對一個有警告的模組按「請代理修正」，會建立 CR、派工程代理、任務分頁看得到進度，完成後該模組的 check 狀態更新。
7. 快取生效：同一模組第二次開啟詳情，`check`／`render`／`preview` 皆不重跑（以 job log 或回應時間確認）。
8. `npm run lint`、`npx tsc --noEmit`、`npm run build` 通過；後端 `pytest`、`ruff` 通過。

---

## 7. 開發順序

1. 後端八個端點與快取機制（前端可先用假資料）。
2. 模組分頁的清單與詳情（三視圖、檢查、各種表）。
3. 佔位標示（3D、清單、檢查分頁、匯出對話框）。
4. `viewer-core` 抽出軸套用函式，再做 `ModulePreview`。
5. 動作列（修正、重檢、promote、定位）。

第 4 步排在後面，是因為它依賴示範模組已經做好——沒有 `safety_door` 就驗不了滑桿。

---

## 8. 風險

**單模組預覽的建置成本。** 每個模組要獨立跑一次 CadQuery 建置加 tessellation，庫有十幾個模組時首次開啟分頁會慢。對策是快取（第 4 節）加上「詳情才建置，清單只讀 manifest」。若仍慢，考慮在 `cell part check` 通過時就順手產生 preview 與 render 並入快取。

**庫是跨案的，端點卻掛在案子底下。** `GET /api/projects/{p}/modules` 回傳的庫模組其實與案子無關，這是為了讓前端只打一次。若日後要做跨案的庫管理頁面，`/api/library/modules` 已經獨立存在，不需重構。

**check 結果的快取失效。** 模組檔改了但快取沒失效，會讓你看到舊結果做出錯誤判斷。快取鍵必須含模組檔 SHA，且 `cell part check` 每次執行都要更新快取，不可只寫不讀。

**面板寬度。** 十項檢查加四張表塞在右側欄會很擠。若實作時發現可讀性差，允許詳情改為覆蓋層佔滿中央區（與三視圖放大同一機制），在 DECISIONS 記錄。
