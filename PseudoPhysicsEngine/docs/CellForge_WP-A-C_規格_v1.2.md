# CellForge WP-A／WP-C 規格 v1.2

代理自主建模能力 ＋ 機構樣板庫 ＋ 模組層前端
日期：2026-09-19　狀態：定稿，可開工
本文件取代並合併 v1.1、`附錄_part-check與示範模組設計`、`前端規劃` 三份草案。依據 `docs/CellForge_開發書_v1.0.md` 與 `docs/ENGINE_REWORK_PLAN.md`，衝突時以本文件為準並記入 `docs/DECISIONS.md`。

> 引擎（運動學、模擬、FCL 檢查、viewer 動畫、交付）已完成且**不在本次範圍**。本次補的是「內容」與「可見度」：讓代理有好的機構可用、缺的會自己建、而且你看得到品質。

---

## 0. 一頁摘要

同一份 Getac QC 案資料，跑完 `intake → first_build` 之後，產出的 3D 場景必須看得出是一條設備線，而不是方塊示意圖：有相機站與光源、有鋁擠框架與安全圍籬、手臂末端是看得出型式的力覺工具、堆料架有真實層板與導柱。代理在 `library/` 找不到需要的機構時，會自己在 `parts/` 寫出參數化模組並通過自檢，而不是拿箱體湊。你能在 UI 的「模組」分頁瀏覽全庫、看逐項檢查、拉動軸看可動機構、並一眼認出哪些還是佔位。

三個工作面：

- **WP-C 機構樣板庫**：既有九個模組全部升級、新增八個這條線缺的模組、建立 `library/manifest.yaml`。
- **WP-A 代理自主建模**：`cell part` 系列指令與十項自檢、prompt 與 skill 補強、自我修正迴圈。
- **WP-U 模組層前端**：「模組」分頁、check 面板、單模組 3D 預覽、佔位標示、後端 API。

### 0.1 現況缺口（開工前請先確認這幾點仍成立）

- `library/` 共 9 個模組、603 行，全部是箱體層級。`lift_rack` 是四根柱子加幾片板，`safety_fence` 32 行。
- 兩個實際案子的 `parts/` 都只有 `.gitkeep`：代理從未自建過任何模組。
- `cellforge/agents/prompts/first_build.md` 沒有任何一句話要求代理在缺機構時自建模組。
- 實際案子的 `cell.yaml` 只有 7 個模組，**整條線沒有任何相機、光源、安全圍籬、電控箱**，`library/flip_fixture.py` 也從未被引用。S2「外觀取像」站只有一個 `fixture_stand`。
- `skills/cell-modeling/SKILL.md` 46 行，已有 `ModuleDef`／`axes`／`mount` 的正確說明，但沒有建模觸發條件、沒有品質標準、沒有完整範例。
- 主畫面八個分頁（資料、檢查、問題、假設、變更、任務、對話、流程）**沒有任何地方看得到模組**。

### 0.2 不需要改的部分（先確認，避免白工）

`web/src/viewer-core.ts` 已泛用處理模組軸：第 62 行取 `value_mm ?? value_deg ?? value`，第 86、92 行分別套用 revolute 與 prismatic。因此 `safety_door` 的擺動、`part_stopper` 的擋停、`camera_station` 的俯仰，只要 `ModuleDef.axes` 宣告正確就會在主場景動起來，**動畫層一行都不用改**。唯一需要的小重構見第 8.3 節。

---

## 1. 模型來源分級

模組分兩級，判定原則是**可採購且型號固定者用原廠模型，依案調整尺寸者用參數化自建**。

### Tier V — 廠商原廠模型（走 `vendor/`）

適用：六軸手臂、平行夾爪與真空吸盤、工業相機與鏡頭、線性模組與電缸、氣缸、伺服馬達與減速機、光源本體。

要求：`vendor/manifest.yaml` 必須記錄 `source_url`、下載日期、SHA-256、`units_in_file`、`up_axis`、關鍵 `frames`（至少 `base` 與 `flange`／`mount`）、`limits`。取不到原廠檔時走 `cell vendor stub` 並標 `approximated: true`，但**型錄關鍵尺寸必須填真值**（reach、payload、外形包絡、法蘭規格），不可用預設值帶過。

本次不要求把 DENSO 真機跑通（那是 WP-B），但 Tier V 的 manifest 欄位與 stub 的型錄尺寸要求現在就要落實。

### Tier P — 參數化自建模組（`library/` 或案內 `parts/`）

適用：鋁擠框架、輸送段、治具與定位銷、相機與光源支架、安全圍籬與門、電控箱、作業桌、堆疊料倉、翻面機構、遮光罩、警示燈柱。

### 判定流程（代理必須照此順序）

1. 查 `library/manifest.yaml` 是否已有可用模組 → 有就用，只調參數。
2. 否則判定 Tier。屬 Tier V → 嘗試 `cell vendor add`，失敗則 `cell vendor stub` 並填型錄尺寸。
3. 屬 Tier P 且庫裡沒有 → 在案內 `parts/` 自建。
4. 任何一步的結果都要寫進 `analysis/assumptions.yaml`，尺寸依據寫在 `basis`。

---

## 2. 模組品質標準

一個模組要能通過 `cell part check`，必須滿足：

| # | 項目 | 判定 |
|---|---|---|
| 1 | 尺寸依據 | `ModuleDef.meta.basis` 非空，說明尺寸來自型錄、實測、工程圖或合理工程推估 |
| 2 | 安裝介面 | 有可見的安裝特徵（底板與螺孔位、T 槽、法蘭面、支撐腳），足以判斷裝得上而非懸空箱體 |
| 3 | 具名子零件 | 每個 `cq.Assembly` 子零件有意義的名稱（`post_fl`、`shelf_3`、`lens_barrel`），不可是 `solid1` |
| 4 | frames | 至少 `mount`；另含該機構的工作點。frame 必須落在幾何表面或機構學上正確的位置 |
| 5 | axes | 可動機構必須宣告 `axes`，`range` 非零，`max_speed` 為真實量級 |
| 6 | collision | 可產生碰撞幾何，且不得整體包住鏤空區（框架類要逐桿件給碰撞體） |
| 7 | 配色 | 依工程慣例給 `cq.Color`，不可全部留預設 |
| 8 | 參數 | `params_schema` 為有效 JSON Schema，關鍵參數有上下限，極端值可建置 |
| 9 | 三角形數 | 單一模組 visual 網格 ≤ 50,000 三角形 |
| 10 | 落地 | 落地模組最低點在 `z=0`±5 mm，或宣告 `mount`（D-018） |

**第 2 項是「貼近實體」與「箱體示意」的分界**，審查時以它為準。第 6 節是這十項的完整判定規格。

---

## 3. WP-C：機構樣板庫

### 3.1 `library/manifest.yaml`

新增此檔，每個模組一筆：

```yaml
modules:
  - id: lift_rack
    file: library/lift_rack.py
    tier: P
    category: material_handling    # frame | conveying | handling | fixturing | vision | safety | electrical | material_handling
    summary: 升降式堆料架，多層料位、伺服升降
    basis: 依一般料架型式與客戶堆疊需求推估
    params: [levels, pitch_mm, width_mm, depth_mm, max_speed_mm_s]
    frames: [mount, slot_0..slot_n, top]
    axes: [lift]
    status: production            # draft | production
    from_project: null            # 由案內 parts/ 升級而來時填案名
```

`cell part list`、前端模組分頁、代理的建模判定第 1 步都讀此檔。

### 3.2 既有九個模組的升級

全部重寫到符合第 2 節標準。重點：

- `lift_rack`：加真實層板結構（角鋼托架、背板、導柱、升降絲桿或皮帶）、料位定位擋塊；`slot_n` frame 落在層板上表面。
- `conveyor`：加帶輪、側擋邊、可調支撐腳、驅動端馬達包絡、擋停氣缸位置的介面 frame。
- `robot_stub`：保留參數化六軸鏈，但外形要像工業手臂（基座、大臂、小臂、腕部殼），依 reach 縮放連桿比例；法蘭面要有真實的 ISO 9409 法蘭外形與 `tool` frame。
- `force_eoat`：做成看得出型式的力覺末端（法蘭轉接板、力覺感測器圓柱、細長開蓋撥桿、圓角撥頭），撥頭尖端為 `tip` frame。
- `fixture_stand`：加桌腳、加強樑、桌面 T 槽或孔陣、定位銷孔。
- `flip_fixture`：真正的翻面機構（旋轉軸、夾持臂、氣缸驅動），宣告 revolute 軸 0～180°。
- `camera_light`：拆成 `camera_bracket` 與 `light_ring`／`light_bar`（見 3.3）。
- `safety_fence`：柱＋網片＋底座，可設段數與高度。
- `box`：保留為佔位用，但 `ModuleDef.meta.placeholder: true`，`cell part check` 對它放寬，且 `cell validate` 對使用 `box` 的模組發出中文警告「仍為佔位幾何」。

### 3.3 Getac QC 線需要新增的模組（本次必做）

| 新模組 | 用途 | 關鍵參數 | 關鍵 frames／axes |
|---|---|---|---|
| `camera_station` | S2／S3／S4 的相機安裝（立柱＋橫樑＋相機座） | `height_mm`, `reach_mm`, `tilt_deg`, `cameras` | `mount`, `cam_0.mount`；`tilt` revolute |
| `light_bar` | 條形光源 | `length_mm`, `angle_deg` | `mount`, `emit` |
| `light_ring` | 環形光源（同軸取像用） | `outer_d_mm`, `inner_d_mm` | `mount`, `emit` |
| `extrusion_frame` | 鋁擠機架 | `size_mm[3]`, `profile_mm`, `posts`, `beam_levels_mm` | `mount`, `top_*`, `rail_*` |
| `safety_door` | 圍籬門 | `width_mm`, `height_mm`, `hinge_side` | `hinge`；`swing` revolute 0～110° |
| `control_cabinet` | 電控箱 | `size_mm[3]` | `mount`, `front` |
| `part_stopper` | 輸送線擋停／定位氣缸 | `stroke_mm` | `stop` prismatic |
| `signal_tower` | 三色警示燈柱 | `tiers` | `mount` |

新增後 `cell.yaml` 的模組數會從 7 增至約 15～18。S2、S3、S4 三站都要有實際的相機與光源模組，且 `process.yaml` 的 `capture` 步驟要指向真實的相機 frame。

### 3.4 不在本次範圍

真實廠商 STEP 匯入與凸分解（WP-B）、相機視野與解析度檢查（WP-D）、廠務座標校正（WP-E）。

---

## 4. WP-A：代理自主建模

### 4.1 新增 CLI

| 指令 | 行為 |
|---|---|
| `cell part list [--library] [--project]` | 列出可用模組（讀 `library/manifest.yaml` 與案內 `parts/`），含 category、參數、frames |
| `cell part new <id> --category <c> [--from <library_id>]` | 在案內 `parts/<id>.py` 產生骨架（含 `build`、`module_definition`、`MODULE`、`meta.basis` 待填），或從既有庫模組複製後改寫 |
| `cell part check [<id>] [--json]` | 執行第 6 節十項檢查，輸出逐項通過／失敗與中文原因。回傳碼 0／2 |
| `cell part render <id> --out png` | 單獨渲染該模組三視圖＋ISO 一張 PNG |
| `cell part preview <id> --out glb` | 產生單模組 GLB，供前端 3D 預覽 |
| `cell part promote <id>` | 通過 check 後把案內模組收進 `library/`，更新 manifest 並填 `from_project` |

`cell part check` 併入 `cell validate`：案內 `parts/` 有任何模組未通過時，`validate` 回傳碼 2。

### 4.2 `first_build.md` 補強

在現有內容之後加入建模段落：

- 組線之前先跑 `cell part list`，確認每個規劃中的機構有對應模組。
- 缺件時依第 1 節判定流程處理；屬 Tier P 且庫內沒有 → `cell part new` 後改寫，**不可用 `library/box.py` 代替真實機構**。
- 每個自建模組完成後跑 `cell part check`；未通過就依中文原因修正，最多 3 輪；3 輪仍不過則把該模組降為 `box` 佔位、標 `trust: inferred`、寫入 `assumptions.yaml` 並在最終 JSON 的 `summary` 說明，不可靜默放過。
- `cell part render` 產生的 PNG 交由隔離 vision job 檢查（沿用 D-003 機制），主工作階段不得直接 Read 圖檔。
- 尺寸一律填進 `ModuleDef.meta.basis`；無依據的推估必須同時建立一則 assumption。

### 4.3 `cell-modeling` SKILL.md 補強

現有 46 行的說明保留，補上：建模觸發判定樹（第 1 節）、品質標準十項（第 2 節，每項附一句「怎麼做到」）、第 7 節的兩個完整範例、以及常見錯誤清單（frame 浮在空中、碰撞體包住鏤空、子零件名稱無意義、可動件幾何寫在錯誤的 link、落地模組沒碰到 z=0、參數沒有上下限導致極端值建置失敗）。

### 4.4 `cell-review` SKILL.md 補強

加入模組層級的目視檢查清單：這個機構看起來裝得上嗎、有沒有支撐、比例對不對、動件行程合理嗎、與相鄰模組的介面對得上嗎。

---

## 5. （保留編號，內容併入第 4 節）

---

## 6. `cell part check` 判定規格

### 6.0 通則

檢查對象是單一模組（`library/*.py` 或案內 `parts/*.py`）。檢查器以預設參數呼叫模組的 `build()` 取得 `cq.Assembly`，並取其 `ModuleDef`，之後所有判定都在這兩個物件上做，不需要 `cell.yaml`。

嚴重度三級：**失敗**（機器可明確判定、會讓後續出錯，任一項失敗 → 回傳碼 2）、**警告**（機器只能用代理指標判定，可能誤判，列出但不阻擋，由第 8 節的目視介面把關）、**資訊**（本層級判不了，只輸出數值）。

輸出為逐項一行 `[fail|warn|info] <項次> <模組id>：<中文訊息>`；`--json` 時輸出結構化結果供代理與前端解析。

### 6.1 尺寸依據 — 失敗

`meta.basis` 存在、去除空白後長度 ≥ 10 字元，且不等於 `cell part new` 骨架預填的 `TODO：填寫尺寸依據`。

> 模組 `<id>` 未填寫尺寸依據（meta.basis）。請說明尺寸來自型錄、實測、工程圖或工程推估。

### 6.2 安裝介面 — 警告

兩個代理指標，任一成立即通過：

- **次要子零件數**：子零件依包圍盒體積排序，體積小於最大者 20% 的數量 ≥ 2。
- **孔槽特徵**：任一子零件的 face 數 > 6。

> 模組 `<id>` 看起來是單純箱體（次要子零件 `<n>` 個、無孔槽特徵）。請補上安裝介面——底板與螺孔位、鋁擠 T 槽、法蘭面或支撐腳。

### 6.3 具名子零件 — 失敗

`name` 非空、長度 ≥ 2、不符合 `^(solid|part|object|shape|compound)_?\d*$`，且同模組內不得重複（GLB 匯出會自動加 `_1` 後綴，見 D-020）。以 `len(assembly.objects)` 等執行期計數命名雖可通過樣式檢查，但會隨結構調整而跳號，訊息中一併提醒。

### 6.4 frames — 失敗／警告

缺 `mount` → 失敗。frame 原點落在整體包圍盒外（容差 5 mm）→ 失敗。frame 的 `link` 指向不存在的子零件 → 失敗。frame 到最近實體表面 > 20 mm → 警告（光學中心、抓取點這類空間點是合法的）。

### 6.5 axes — 失敗

僅對有宣告 `axes` 的模組：`range` 上下限不得相等；`max_speed` > 0 且在合理量級（prismatic 1～2000 mm/s、revolute 1～720 deg/s）；`parent`／`child` 指向的 link 必須有對應子零件，`child` link 沒有任何幾何為失敗；`axis` 向量長度不得為零。

### 6.6 collision — 失敗／警告

碰撞幾何產生失敗即失敗。膨脹比 = 碰撞體總體積 ÷ 視覺實體總體積：

| 膨脹比 | 判定 |
|---|---|
| ≤ 3.0 | 通過 |
| > 3.0 | 警告 |
| > 6.0 | 失敗 |

> 模組 `<id>` 的碰撞體體積是實體的 `<r>` 倍，可能整包住鏤空區，會讓干涉檢查誤報。請對各桿件分別產生碰撞體。

門檻為依典型鏤空率推估，實作時先用既有九個模組實測一輪，不合再調整並記入 DECISIONS。

### 6.7 配色 — 警告

有指定 `cq.Color` 的子零件佔比 ≥ 80%（依子零件數計）。

### 6.8 參數 — 失敗／警告

`params_schema` 通過 JSON Schema（draft 2020-12）meta-validation → 否則失敗。以預設參數 `build()` 成功 → 否則失敗。每個數值型參數逐一拉到 `minimum` 與 `maximum`（其餘保持預設）各建置一次，不可拋例外 → 否則失敗，訊息指出是哪個參數的哪一端。數值型參數有上下限者佔比 ≥ 80% → 否則警告。

只測單參數兩端、不測組合，避免 check 時間爆炸。

### 6.9 三角形數 — 警告／失敗

以建置時相同的 tessellation 參數計算：≤ 50,000 通過、> 50,000 警告、> 150,000 失敗。訊息須列出實際數字與佔比最高的三個子零件。

### 6.10 落地 — 資訊

模組層級不知道它在 `cell.yaml` 裡是落地還是被承載，只輸出包圍盒最低點 z，真正判定由 `cell validate` 依 `mount` 宣告執行（D-018 已實作，不需重做）。

### 6.11 彙總與代理自我修正

`--json` 至少包含 `module_id`、`passed`、`items[]`（`index`、`severity`、`code`、`message`、`values`）。代理依第 4.2 節處理：失敗項修正後重跑，最多 3 輪；警告項不強制修正，但必須在最終 JSON 的 `summary` 列出。

---

## 7. 示範模組設計

這兩個要放進 `skills/cell-modeling/SKILL.md` 當完整範例，代理會照抄改寫，品質直接決定後續所有模組。一個靜態、一個可動，合起來涵蓋第 2、3、4、5、6、7 項的正確做法。

### 7.0 共通簡化原則（示範重點）

**看得出型式，但不畫製造細節。** 鋁擠不畫完整 T 槽，用「方形外廓＋四面各一道淺槽＋中心圓孔」；網片不畫網孔，用薄板加半透明深灰；螺絲不畫，只畫螺孔座或沉頭孔位置；圓角只在視覺上關鍵處加。判準是第 6.9 節的三角形預算與「站在三公尺外看得出這是什麼機構」。

### 7.1 `extrusion_frame`（靜態）

**參數**

| 參數 | 預設 | 範圍 | 說明 |
|---|---|---|---|
| `size_mm` | [1200, 800, 1800] | 各 200～6000 | 長×寬×高（外廓） |
| `profile_mm` | 40 | {30, 40, 45, 60} | 鋁擠斷面邊長 |
| `posts` | 4 | {4, 6} | 立柱數 |
| `beam_levels_mm` | [80, 1800] | 0～size_z | 橫樑層高度清單 |
| `with_feet` | true | — | 是否含可調地腳 |

**子零件**：立柱 `post_fl`／`post_fr`／`post_rl`／`post_rr`（六柱時加 `post_ml`／`post_mr`）；每層橫樑 `beam_<lvl>_front`／`_rear`／`_left`／`_right`；地腳 `foot_fl` 等；角件 `bracket_<post>_<lvl>`（同時滿足第 6.2 節的次要子零件指標）。

**frames**：`mount`（底面中心，z=0）；`top_front`／`top_rear`／`top_left`／`top_right`（上框各面中點，供相機站與光源掛載）；`rail_<lvl>_<side>`；`inner_center`。

**碰撞**：逐桿件 box，每根立柱與橫樑各一個。**不可**用整體凸包——這正是第 6.6 節要示範的反例。

**配色**：鋁擠 `Color(0.72, 0.74, 0.76)`；角件深灰 `Color(0.35, 0.37, 0.40)`；地腳黑。

**meta.basis**：`依 40×40 鋁擠型材標準斷面與一般設備機架尺寸，斷面簡化為方廓加四面淺槽`

**三角形預算**：斷面簡化後每根桿件約 200～400 面，20 根桿件＋角件約 12,000 三角形。

### 7.2 `safety_door`（可動）

**參數**

| 參數 | 預設 | 範圍 |
|---|---|---|
| `width_mm` | 900 | 400～1500 |
| `height_mm` | 1800 | 800～2500 |
| `hinge_side` | "left" | {left, right} |
| `profile_mm` | 30 | {30, 40} |
| `open_angle_deg` | 110 | 60～170 |

**link 與子零件**

`base` link：`frame_post_hinge`、`frame_post_latch`、`hinge_upper`、`hinge_lower`。
`door` link：`door_stile_hinge`、`door_stile_latch`、`door_rail_top`、`door_rail_bottom`、`door_mesh`（2 mm 薄板）、`door_handle`。

**關鍵示範點**：`door` link 的所有幾何**照門關著時的實際位置直接畫**（零位世界變換下的座標），不要自己先平移到鉸鏈原點。GLB 匯出時會乘上零位世界變換的反矩陣自動換算回 joint-local。這條規則 SKILL.md 已經寫了但沒有範例，是代理最常寫錯的地方。

**axis**

| 欄位 | 值 |
|---|---|
| `id` | `swing` |
| `type` | `revolute` |
| `parent` / `child` | `base` / `door` |
| `origin` | 鉸鏈軸線位置（依 `hinge_side` 決定） |
| `axis` | (0, 0, 1) |
| `range_deg` | (0, `open_angle_deg`) |
| `max_speed_deg_s` | 90 |

**frames**：`mount`（底部鉸鏈側，z=0）；`hinge`（`link="base"`）；`latch`（`link="door"`——示範 frame 掛在可動 link 上）。

**碰撞**：門扇整體一個 box（指派到 `door` link，隨軸轉動）；兩根門框立柱各一個 box。網片不另給碰撞體。

**配色**：門框與門扇料件安全黃 `Color(0.95, 0.75, 0.10)`；網片深灰半透明；門把與鉸鏈金屬灰。

**三角形預算**：約 3,000～5,000。

### 7.3 兩個範例的教學點

| 教學點 | 範例 |
|---|---|
| 具名子零件用方位／層序，不用執行期計數 | extrusion_frame |
| frame 陣列（多個掛載點）的組織 | extrusion_frame |
| 逐桿件碰撞體，避免凸包包住鏤空 | extrusion_frame |
| 工程配色與中性色的取捨 | 兩者 |
| 可動 link 的幾何寫在零位世界變換 | safety_door |
| revolute 軸的 origin／axis 寫法 | safety_door |
| frame 掛在可動 link | safety_door |
| 參數上下限與極端值可建置 | 兩者 |
| 「看得出型式，不畫製造細節」的簡化尺度 | 兩者 |

---

## 8. WP-U：模組層前端

### 8.1 新增「模組」分頁

加在現有八個分頁之後成為第九個，位置在主畫面右側面板，同層，不另開導覽層級。採**清單／詳情切換**而非左右並列（面板寬度有限）；詳情中的三視圖與 3D 預覽可「放大」為覆蓋層佔滿中央 3D 區。

**清單**：第一組固定是「本案自建」（案內 `parts/`），其後依 manifest 的 `category` 分組（顯示中文名）。每列顯示使用狀態（`●` 本案使用中／`○` 庫內未用／`⬚` 佔位）、id、check 徽章（`✔ 通過`／`⚠ n 警告`／`✖ n 失敗`／`— 未檢查`）。工具列：文字搜尋、category 下拉、「只看有問題」。底部固定一行 `本版佔位模組：n`，n > 0 時轉琥珀色並可點擊篩選。

**詳情**（由上而下）：三視圖 PNG（可放大）；單模組 3D 預覽（第 8.2 節）；十項檢查逐項（沿用主畫面紅黃綠樣式，第 10 項為資訊級灰色）；參數表（含本案實際帶入值）；frames 表（第 6.4 節警告者標黃）；軸表；`meta.basis` 原文；本案使用（引用此模組的 module instance id，可點擊跳到主場景並高亮）。

**動作列**：「請代理修正」（以失敗與警告內容建立 CR 並派工程代理，沿用現有 CR 流程）、「重新檢查」、「在場景中定位」、以及本案自建模組專屬的「收進庫」（僅在零失敗時可用）。

### 8.2 單模組 3D 預覽

**目的**：三視圖判斷不了可動機構的行程是否合理、門開到 110° 會不會撞到旁邊。

**互動**：OrbitControls 加四個快捷視角（ISO／前／側／上）；**每個 `ModuleDef.axes` 給一支滑桿**，範圍取軸的 `range`，即時套用到 GLB 節點，旁顯示目前值與單位——這是本預覽的核心價值；切換碰撞體顯示（依 D-020 的 `extras.hidden`）、frame 顯示（每個 frame 畫 RGB 三軸小三腳架，長度 50 mm，hover 顯示名稱）、線框模式；底部顯示包圍盒尺寸與三角形數；地面格線與 z=0 平面（呼應第 6.10 節）。

### 8.3 `viewer-core.ts` 小重構

目前流程是「timeline 取樣 → 得到軸值 → 套用變換」，其中「套用變換」已是獨立邏輯（第 86～92 行）。把它抽成可直接呼叫的函式（給節點與軸值，套用 rest TRS 加軸運動），主場景與單模組預覽共用。**不要另寫一套**——D-016 的教訓就是兩套關節語意會逐漸分歧。

單模組預覽是獨立的輕量元件（新檔 `components/ModulePreview.tsx`），**不重用** `Viewer.tsx`——後者綁了時間軸、站別、checks 標記、版本疊圖，對單模組全是多餘。

### 8.4 佔位模組標示

`meta.placeholder: true` 的模組在主場景以**洋紅色虛線輪廓**標示，與 `trust: inferred` 的琥珀實線輪廓（D-019）明確區分。沿用 D-019 已驗證的做法：先按位置焊接顯示網格，再由 `EdgesGeometry` 畫輪廓，不用全表面 emissive。viewer 工具列加切換「標示佔位模組」，預設開啟。

其他位置：模組分頁清單的 `[佔位]` 標記與底部計數；檢查分頁最上方若有佔位模組顯示一則資訊級項目並可跳轉；匯出對話框既有的「仍為推估的項目數」提示加上佔位模組數；代理 first_build 最終 JSON 的 `summary` 在對話分頁原樣顯示。

### 8.5 後端新增 API

```
GET  /api/library/modules                         # library/manifest.yaml 全部
GET  /api/projects/{p}/modules                    # 本案 parts/ + 本案引用的庫模組，含 check 狀態與使用位置
GET  /api/projects/{p}/modules/{id}               # ModuleDef、參數、frames、axes、meta
GET  /api/projects/{p}/modules/{id}/check         # cell part check --json（讀快取，無則即時跑）
GET  /api/projects/{p}/modules/{id}/render.png    # 三視圖（讀快取）
GET  /api/projects/{p}/modules/{id}/preview.glb   # 單模組 GLB（讀快取）
POST /api/projects/{p}/modules/{id}/recheck       # 重跑 check + render + preview → job
POST /api/projects/{p}/modules/{id}/fix           # 以 check 結果建 CR 並派工程代理 → job
POST /api/projects/{p}/modules/{id}/promote       # cell part promote → job
```

**快取**：`check`、`render.png`、`preview.glb` 以「模組檔 SHA-256 ＋ 參數 JSON」為鍵，存在 `.cellforge-runtime/module-cache/<hash>/`。模組檔未變更時直接回傳，不重跑 CadQuery。庫模組以預設參數檢查，快取鍵不含案子，可跨案共用；案內 `parts/` 模組以案內實際參數為準。

### 8.6 前端檔案改動

| 檔案 | 改動 |
|---|---|
| `web/src/types.ts` | 新增 `ModuleSummary`、`ModuleDetail`、`PartCheckResult`、`PartCheckItem`、`ModuleAxisInfo`、`FrameInfo` |
| `web/src/api.ts` | 新增第 8.5 節九個端點的呼叫 |
| `web/src/components/MainWorkspace.tsx` | `tabs` 加「模組」；新增 `ModulePanel`；檢查分頁加佔位模組提示 |
| `web/src/components/ModulePreview.tsx` | 新檔 |
| `web/src/components/Viewer.tsx` | 佔位輪廓與工具列切換；對外方法「定位到某 module instance」 |
| `web/src/viewer-core.ts` | 抽出「依軸值套用變換」函式 |
| `web/src/styles.css` | 模組清單、徽章、滑桿、覆蓋層樣式 |

**不改** `offline.ts`：匯出的單檔 HTML 只含整線 viewer，不含模組分頁。模組庫是工作中的工具，不是交付給客戶的內容。此決定寫進 DECISIONS。

---

## 9. 驗收

以 `.cellforge-runtime/projects/軍規筆電_QC_線_2` 或重新建立的同名案子為準，`CELLFORGE_ENGINEERING_AGENT_MODE=claude` 跑真實代理。

**模組庫與品質**

1. `cell part list` 列出 ≥ 17 個 production 模組，`library/manifest.yaml` 完整。
2. 既有九個模組全部通過 `cell part check`（`box` 除外，標記為 placeholder）。
3. 新增的八個模組全部通過 `cell part check`。

**代理能力**

4. 代理在 first_build 中至少自建一個案內模組（`parts/` 非空）且通過 check；若庫已齊全導致無需自建，則以「刻意移除庫內某模組後重跑」驗證此能力。
5. 產出的 `cell.yaml` 模組數 ≥ 15，且 S2／S3／S4 都有實際相機與光源模組，`process.yaml` 的 `capture` 步驟指向相機 frame。
6. `cell build --level L1` 成功，時間 < 90 秒（模組變多後自開發書的 60 秒放寬），STEP 回讀名稱與數量仍全數保留。
7. ISO 與各站近景截圖經目視確認：看得出設備型式，不是方塊堆疊。

**前端**

8. 模組分頁列出庫內全部 production 模組與本案自建模組，分組、搜尋、篩選可用；詳情顯示三視圖、十項檢查、參數／frames／軸表與尺寸依據。
9. `safety_door` 的 3D 預覽可用滑桿把門從 0° 拉到 110°，門扇繞鉸鏈正確轉動（**若門從錯誤位置甩出，代表第 7.2 節的「零位世界變換」規則實作錯誤，這個預覽就是它的第一道檢驗**）。
10. `extrusion_frame` 的預覽開啟碰撞體顯示後，看得出是逐桿件的碰撞盒，不是包住整框的大盒。
11. 刻意把某模組換成 `box` 佔位後，主場景出現洋紅虛線輪廓、模組分頁底部計數為 1、檢查分頁出現提示。
12. 對一個有警告的模組按「請代理修正」，會建立 CR、派工程代理、任務分頁看得到進度，完成後該模組 check 狀態更新。
13. 快取生效：同一模組第二次開啟詳情，`check`／`render`／`preview` 皆不重跑。

**品質閘門**

14. `python -m pytest`、`ruff check .`、`ruff format --check .` 通過；`npm run lint`、`npx tsc --noEmit`、`npm run build` 通過。

---

## 10. 開發順序

1. **`cell part check` 的第 6.1、6.3、6.4、6.5、6.8 項**（純結構判定，不需幾何運算）——能立刻抓出多數問題。
2. **第 6.6、6.9 項**（需 tessellation 與體積計算）。
3. **第 6.2、6.7 項**（代理指標）＋ `cell part render`、`cell part preview`——這兩項要靠目視補強。
4. **兩個示範模組**（第 7 節）——必須零警告通過自己定的檢查，否則它教出來的東西也會帶著同樣的問題。
5. **既有九個模組升級 ＋ 新增八個模組**（第 3 節）。
6. **後端九個端點與快取**（第 8.5 節）。
7. **模組分頁清單與詳情**（第 8.1 節）。
8. **佔位標示**（第 8.4 節）。
9. **`viewer-core` 抽出軸套用函式 ＋ `ModulePreview`**（第 8.2、8.3 節）——排在後面是因為它依賴示範模組已做好，沒有 `safety_door` 就驗不了滑桿。
10. **動作列**（修正、重檢、promote、定位）＋ prompt 與 skills 補強（第 4.2～4.4 節）。
11. **以 Getac 案跑真實代理驗收**（第 9 節）。

每個步驟結束時 `pytest`、`ruff check .`、`ruff format --check .` 必須通過；前端有改時 `npm run lint`、`npx tsc --noEmit`、`npm run build` 也必須通過。每步完成後提交一次 git。

---

## 11. 風險與處置

**模組變多後的建置與檢查時間。** 17～20 個模組、逐桿件碰撞體，FCL 配對數會明顯上升。若 L1 超過 90 秒，優先做碰撞體的 AABB 預篩與靜態配對只在 t=0 評估（D-012 已有此策略），**不要為了速度回頭簡化幾何**。

**品質標準第 2 項難以機器判定。** `cell part check` 只能用代理指標，真正把關靠 `cell part render` 的目視檢查。此項列為警告而非硬性失敗。

**代理可能濫用 `box` 佔位走捷徑。** 因此 `cell validate` 對使用 `box` 的模組發出警告，first_build 最終 JSON 必須列出所有佔位模組，前端三處顯示。

**單模組預覽的建置成本。** 每個模組要獨立跑一次 CadQuery 建置加 tessellation。對策是快取加上「詳情才建置，清單只讀 manifest」。若仍慢，考慮在 `cell part check` 通過時順手產生 preview 與 render 入快取。

**check 結果的快取失效。** 快取鍵必須含模組檔 SHA，且 `cell part check` 每次執行都要更新快取，不可只寫不讀。

**面板寬度。** 十項檢查加四張表塞在右側欄會很擠。若實作時可讀性差，允許詳情改為覆蓋層佔滿中央區，在 DECISIONS 記錄。

**膨脹比門檻。** 3.0／6.0 為推估值，實作時先用既有九個模組實測一輪再定案。

---

## 12. 前置狀態

平台根目錄已於 2026-09-19 建立 git 版控，baseline commit 為 `7e8a517`（開發書六步與引擎重做 WP1～WP4 完成狀態）。`.git/_stale/` 內是建立 baseline 時殘留的鎖檔與暫存物件，可直接刪除。

`.venv` 與 `web/node_modules` 已存在且不在版控內；開工前確認 `pytest` 為綠。
