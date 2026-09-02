# VisionStereo — Web 前端 UI 設計規範與標註互動規格

> 給其他專案的 AI 代理閱讀：本文把 VisionStereo 內建標註網頁的**視覺設計語言**與**標記（annotation）互動模型**抽出來寫成可直接複製的規格，目的是讓其他工具（不同框架、不同任務）能做出風格一致、操作手感一致的介面。
> 對應原始碼：[Bin/web/index.html](../Bin/web/index.html)、[Bin/web/style.css](../Bin/web/style.css)、[Bin/web/app.js](../Bin/web/app.js)；標記檔的後端讀寫在 [Bin/labelServer.py](../Bin/labelServer.py)。
> 系統架構、HTTP API、訓練／轉檔流程請看 [WebTraining.md](WebTraining.md)，本文不重複。

---

## 0. 一頁摘要

| 面向 | 決策 |
| --- | --- |
| 風格 | 淺色 admin dashboard（固定側欄 + 頂欄 + 白卡片 + 柔和陰影 + stat tiles），深色為完整對應版本 |
| 主色 | indigo `#6366f1`，輔色 violet / green / amber / red / blue；換色只要改 `--primary` 一組 |
| 技術 | 原生 HTML/CSS/JS 單頁，**零建置、零 CDN、零框架**；全部樣式走 CSS 變數 |
| 圖示 | 全部 inline SVG（`viewBox="0 0 24 24"`、`stroke:currentColor`、`fill:none`），不用圖示字型 |
| 版面 | CSS Grid 三欄（清單 / 畫布 / 面板），5 個斷點一路收斂成單欄 |
| 標記 | Canvas 2D 自繪；座標一律 **0~1 正規化**；shape = `{cls, kind, points}` |
| 輸入 | Pointer Events 統一滑鼠與觸控（單指拖曳、雙指縮放平移） |
| 安全網 | dirty 旗標 + 60 步 undo + 切圖／關頁攔截；破壞性動作一律先 `confirm()` |

---

## 1. 設計權杖（Design Tokens）

全部樣式只透過 CSS 變數取色，**沒有任何硬寫的十六進位色碼出現在元件規則裡**。這是能一鍵換主題與換主色的前提。

### 1.1 淺色（`:root`）

```css
:root{
  /* 品牌 / 語意色 */
  --primary:#6366f1;  --primary-600:#4f46e5;  --primary-50:#eef2ff;
  --violet:#8b5cf6;   --green:#10b981;  --amber:#f59e0b;  --red:#ef4444;  --blue:#3b82f6;

  /* 介面底色與文字 */
  --bg:#f4f5fa;       /* 內容區背景，比卡片深一階 */
  --card:#ffffff;     /* 卡片 / 側欄 / 頂欄 */
  --text:#1f2937;     /* 主要文字 */
  --text-2:#4b5563;   /* 次要文字、按鈕文字 */
  --muted:#8b93a7;    /* 說明文字、單位、佔位 */
  --line:#e8eaf0;     /* 邊框 */
  --line-2:#f1f2f7;   /* 淺分隔線、預設按鈕底、hover 底 */

  /* 自繪元素（JS 會讀這些值） */
  --canvas-bg:#eceff5;  --chart-bg:#fbfbfe;  --row-hover:#fafbfe;
  --console-bg:#1e2230; --console-fg:#c9d3e6; --code-fg:#e685b5; --kbd-bg:var(--line-2);

  /* 柔色（soft）：淡底 + 深字，用在 stat 圖示、次級按鈕、狀態 badge */
  --soft-amber-bg:#fff7e6;  --soft-amber-fg:#b45309;  --soft-amber-line:#fde3ab;
  --soft-red-bg:#fee9e9;    --soft-red-fg:#b91c1c;
  --soft-green-bg:#e7f8f1;  --soft-green-fg:#047857;
  --soft-blue-bg:#e8f1ff;   --soft-blue-fg:#2563eb;
  --soft-violet-bg:#f1ebff; --soft-violet-fg:#7c3aed;
  --accent-text:#4f46e5;    --scroll-thumb:#d5d9e4;

  /* 形狀與尺寸 */
  --radius:14px;  --radius-sm:9px;
  --shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 14px rgba(16,24,40,.06);
  --shadow-lg:0 12px 40px rgba(16,24,40,.16);
  --side-w:236px; --top-h:66px;
}
```

### 1.2 深色（`[data-theme="dark"]`）

深色**只覆寫同一組變數**，不新增任何選擇器分支；並且加 `color-scheme:dark` 讓原生控制項（scrollbar、日期選擇器）跟著變。

```css
[data-theme="dark"]{
  --primary:#7c83f7; --primary-600:#6366f1; --primary-50:#242a4a;
  --bg:#12151d; --card:#1a1e27; --text:#e7eaf1; --text-2:#aeb6c6; --muted:#7c8598;
  --line:#2a3040; --line-2:#232937;
  --canvas-bg:#0e1116; --chart-bg:#161a23; --row-hover:#1f2531;
  --console-bg:#0e1116; --console-fg:#c3cddf; --code-fg:#f0a6c8;
  --soft-amber-bg:#3a2c10; --soft-amber-fg:#f2c25c; --soft-amber-line:#5c4517;
  --soft-red-bg:#3a1f21;   --soft-red-fg:#f39a9a;
  --soft-green-bg:#12312a; --soft-green-fg:#5fd3ab;
  --soft-blue-bg:#16283f;  --soft-blue-fg:#7db1f5;
  --soft-violet-bg:#251f3d;--soft-violet-fg:#b195f5;
  --accent-text:#a5b4fc;   --scroll-thumb:#333b4d;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 4px 14px rgba(0,0,0,.28);
  --shadow-lg:0 12px 40px rgba(0,0,0,.55);
  color-scheme:dark;
}
```

深色的三個要點：
- **不是把淺色反相**，而是重新挑一組低飽和的深藍灰（`#12151d` / `#1a1e27`），主色也調亮一階（`#6366f1` → `#7c83f7`）避免在深底上發黑。
- 陰影從「灰藍半透明」換成「純黑更重」，否則在深底上看不出層次。
- `--console-bg` 淺色時就已經是深色（終端機一律深底），深色時再壓更暗。

### 1.3 字級與間距刻度

| 用途 | 值 |
| --- | --- |
| 全域字體 | `400 14px/1.55 "Inter", system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif` |
| 頁標題 `#pageTitle` | 17px / 600 |
| 卡片標題 `.card-head h2` | 14.5px / 600 |
| 內文 | 13~13.5px |
| 說明文字 `.hint-text` | 12px、`line-height:1.7`、`--muted` |
| 表格 | 12.5px；表頭 11.5px、大寫、`letter-spacing:.4px` |
| stat 數值 | 21px / 700 / `letter-spacing:-.3px` |
| 卡片內距 | `.card-head` 14×18、`.card-body` 18、`.card-foot` 10×14 |
| 卡片間距 | 18px（手機 12px） |
| 圓角 | 卡片 14、按鈕／輸入 9、小控制 7~8、Modal 16、chip/badge 20（膠囊） |

字體刻意用 0.5px 的小數（14.5 / 12.5 / 13.5）微調視覺重量，這是原設計的一部分，照抄即可。

---

## 2. 版面骨架

```
┌───────────┬──────────────────────────────────────────────┐
│ #sidebar  │ #topbar  （fixed, left:var(--side-w)）        │
│ 236px     ├──────────────────────────────────────────────┤
│ fixed     │ #content （fixed, inset:top-h 0 0 side-w）    │
│ 品牌      │   .page.active                               │
│ 分組導覽  │     .card / .stat-row / grid…                │
│ 底部資訊  │                                              │
└───────────┴──────────────────────────────────────────────┘
```

- `body{overflow:hidden}`，捲動交給 `#content`（`overflow:auto`）與各卡片內部容器。**這是讓標註頁能滿版、畫布高度可算的關鍵**。
- 側欄結構：`.brand`（漸層方塊 logo + 名稱）→ `.nav`（`.nav-label` 分組標題 + `.nav-item`）→ `.sidebar-foot`（目前資料集）。
- 導覽分組：工作區 / 資料集 / 說明。`.nav-item.active` 用 `--primary-50` 底 + `--accent-text` 字 + 600 字重，圖示也跟著換色。
- 執行中的長工作在導覽項右側掛一顆 `.dot`（綠點 + 光暈 + `pulse` 動畫），讓使用者在別的頁面也知道背景還在跑。
- 頁面切換是**純前端 hash 路由**：`switchPage(p)` 切 `.nav-item.active` 與 `.page.active`、改標題、同步 `location.hash`，並在進入特定頁時觸發副作用（重算畫布 / 重繪縮圖牆 / 開始輪詢 / 斷開預覽串流）。

### 標註頁三欄

```css
.annotate-grid{
  display:grid;
  grid-template-columns:270px minmax(0,1fr) 300px;   /* 清單 / 畫布 / 面板 */
  gap:18px;
  height:calc(100vh - var(--top-h) - 40px);          /* 撐滿視窗，內部各自捲動 */
}
@media (max-width:1500px){ .annotate-grid{grid-template-columns:240px minmax(0,1fr) 270px} }
```

`minmax(0,1fr)` 不可省略——否則 canvas 的內容寬度會把中欄撐爆。

---

## 3. 元件規格

以下每個元件都是**單一 class + 修飾 class**的寫法，沒有巢狀依賴，可以整段複製。

### 3.1 按鈕

| Class | 外觀 | 用在哪 |
| --- | --- | --- |
| `.btn` | `--line-2` 底、`--text-2` 字，9px 圓角 | 中性動作 |
| `.btn-primary` | 主色實心 + 主色光暈陰影 | 每個區塊**最多一顆**：儲存、套用、開始 |
| `.btn-ghost` | 透明底 + `--line` 邊框 | 次要動作（瀏覽、預覽、復原） |
| `.btn-warn` / `.btn-warn-soft` | amber 實心 / 淡底深字 | 「會改資料但不寫檔」的動作，例如自動優化 |
| `.btn-danger` / `.btn-danger-soft` | red 實心 / 淡底深字 | 刪除、清空、套用切分、中止 |
| `.btn-icon` | 正方形 8px 內距、只有圖示 | 頂欄工具、關閉 |
| `.btn-sm` | 6×11、12.5px | 工具列與卡片內密集操作 |

共同行為：`:hover{filter:brightness(.97)}`（深色改 `1.18`）、`:active{transform:translateY(1px)}`、`:disabled{opacity:.5; pointer-events:none}`、內含 svg 自動縮到 16px。

**語意規則**：實心紅只給「立刻改動本地檔案且不可逆」的動作（例如套用 train/val 切分），可還原的刪除用 `-soft` 版本。

### 3.2 輸入

```css
.input{ width:100%; padding:8px 11px; font-size:13px; background:var(--card);
        border:1px solid var(--line); border-radius:9px; outline:none }
.input:focus{ border-color:var(--primary); box-shadow:0 0 0 3px rgba(99,102,241,.15) }
```

- `select.input` 用 `appearance:none` + data-URI 的箭頭 SVG 當背景，讓深淺色下的外觀一致。
- `.lbl` 是欄位標籤（12px / 500 / `--text-2`），`.hint-text` 是欄位下方的說明。
- `.field-group` 是「輸入框 + 附掛按鈕」的膠囊容器（灰底、內縮 padding、內部 input 去邊框）；`.field-group.plain` 是無底無邊的版本，用在卡片內部。
- 表單網格用 `.two` / `.four`（`grid-template-columns:repeat(n,1fr)`），窄螢幕自動降成 2 欄 → 1 欄。
- 進階參數放 `<details class="fold">`（資料增強、匯出設定），預設收合，避免主表單過長。

### 3.3 其他元件

| Class | 說明 |
| --- | --- |
| `.card` | 基本容器：`--card` 底 + `--line` 邊 + `--shadow` + 14px 圓角，`flex-direction:column`；由 `.card-head` / `.card-body` / `.card-foot` 組成 |
| `.seg` / `.seg-btn` | 分段控制（工具模式、split 分頁）：灰槽 + 白色滑塊，`.active` 才有卡片底與陰影 |
| `.chip` | 膠囊型可點標籤（快速分類），`.active` 換主色淡底 + 主色邊框 |
| `.badge` | 小圓標；`.ok`（綠）/`.zero`（紅）表示有無標記，`.run`/`.fin`/`.err` 表示工作狀態 |
| `.stat` | 統計磚：46px 圓角圖示方塊（`.i-blue`/`.i-violet`/`.i-green`/`.i-amber`/`.i-red`）+ 標籤 + 大數字；四欄 `.stat-row` |
| `.progress` / `.progress-bar` | 9px 高膠囊，填色是 `primary → violet` 漸層，`transition:width .3s`；下方 `.progress-meta` 左右分列文字與百分比 |
| `.console` | 終端機記錄：`--console-bg` 深底、等寬字 12px、固定高 230px、`white-space:pre-wrap` |
| `.chart` | 自繪 canvas，外觀由 `--chart-bg` + `--line` 統一 |
| `.table` | 表頭大寫小字灰底、列 hover 換 `--row-hover`；外面套 `.table-wrap`（邊框 + 圓角 + `overflow-x:auto`） |
| `.modal` | 半透明黑 + `backdrop-filter:blur(2px)`；`.modal-box` 分 sm(430)/預設(640)/lg(820)，`max-height:88vh` 且 body 自行捲動 |
| `.toast` | 底部置中浮層，左側 4px 色條標示 `ok`/`err`/`warn`，3.4 秒自動收起 |
| `kbd` / `code` | 快捷鍵與路徑的行內樣式；`kbd` 下邊框加粗 2px 做出鍵帽感 |
| `.swatch` | 14px 圓角色塊，用來顯示類別顏色（清單、chip、物件列共用） |

### 3.4 圖示規範

```css
svg{ width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.8;
     stroke-linecap:round; stroke-linejoin:round; flex:none }
```

全部圖示都是 24×24 viewBox 的線性圖示直接內嵌在 HTML 裡（Feather/Lucide 風格），**不載入任何圖示套件**。因為 `stroke:currentColor`，圖示會自動跟著容器文字色變化。

> 坑：這條全域規則會替 SVG 內的 `<text>` 也描邊，使文字看起來糊掉。任何自製的 SVG 圖表都要補一條 `.yourfigure text{stroke:none}`（本專案在 `.flow text` 這樣做）。

---

## 4. 主題切換

1. **防閃爍**：在 `<head>`、CSS 之前放一段同步 script，讀 `localStorage['ys-theme']`，沒有就看 `prefers-color-scheme`，立刻寫上 `document.documentElement.dataset.theme`。這樣第一次繪製就是正確主題，不會先閃一下白底。
2. **切換**：`applyTheme(t)` 寫 `data-theme`、存 localStorage、更新 `<meta name="theme-color">`（深 `#1a1e27` / 淺 `#ffffff`）。
3. **跟隨系統**：監聽 `matchMedia('(prefers-color-scheme: dark)')` 的 `change`；**只有在使用者沒手動選過時**（localStorage 沒有有效值）才跟著換。
4. **自繪內容要重畫**：canvas 與圖表不吃 CSS，換主題後必須重新呼叫繪製函式。JS 端取色一律用

```js
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
```

  絕不在 JS 裡寫死顏色（唯一例外是訓練曲線的三條系列色，因為它們要跨主題保持可辨識）。

---

## 5. 響應式與觸控

| 斷點 | 變化 |
| --- | --- |
| ≤1500px | 標註頁三欄收窄（240 / 1fr / 270） |
| ≤1280px | 雙欄工作區（影片頁、訓練頁）改單欄 |
| ≤1180px | stat 四欄 → 兩欄；`.four` → 兩欄 |
| ≤1100px | 標註頁變兩欄（清單 + 畫布），右側面板移到下方整列 |
| ≤820px | **行動版**：側欄變抽屜、頂欄工具收進下拉面板、標註頁改上下堆疊、觸控目標放大 |
| ≤480px | 全部單欄，畫布高度降到 48vh |

行動版的三個模式轉換：

- **側欄 → 抽屜**：`transform:translateX(-100%)`，`body.nav-open` 時滑出，配一層 `.scrim` 半透明遮罩點擊關閉。
- **頂欄工具 → 下拉面板**：`.topbar-tools` 改 `position:fixed` 掛在頂欄下方，由 `⋯` 按鈕切 `.open`。資料夾輸入、split 分頁、儲存鈕都在裡面。
- **標註頁 → 直式堆疊**：`display:flex; flex-direction:column`，畫布固定 `56vh`，檔案清單限高 `46vh`。

觸控相關：

```css
#canvas{ touch-action:none }   /* 手勢自己處理，別讓瀏覽器搶去捲動／縮放 */
@media (max-width:820px){ .btn{padding:9px 15px} .nav-item{padding:12px 11px} }
```

命中半徑也要跟著輸入裝置變：`HIT = e.pointerType === 'touch' ? 16 : 8`，且觸控時頂點畫大一點（半徑 6.5 對 4.5）。

---

## 6. 標記資料模型

### 6.1 前端形狀

```js
shape = {
  cls:    0,                    // 類別 id（整數，可大於 classes 長度 → 顯示「(未定義)」）
  kind:   'polygon' | 'bbox',   // bbox 只是「還沒被編輯過的矩形」
  points: [[x, y], …]           // 至少 3 點，x/y 皆為 0~1 正規化
}
```

**座標一律正規化儲存，只有畫到畫布時才乘上影像尺寸。** 這讓縮放、切換顯示尺寸、存回 YOLO txt 都不需要換算表。

`kind` 的處理規則很重要：讀進來的 bbox（YOLO 的 `cls cx cy w h`）會展開成四個角點，一旦使用者**拖動頂點、插點或刪點**就自動翻成 `'polygon'`，寫檔時才會改用 polygon 格式。沒被編輯過的 bbox 會原樣寫回 bbox 行，不會無謂地把整個資料集轉成 polygon。

### 6.2 與 YOLO txt 的對應

| 檔案內容 | 前端形狀 |
| --- | --- |
| `cls cx cy w h`（5 欄） | `kind:'bbox'`，四個角點 |
| `cls x1 y1 x2 y2 …`（≥7 欄、偶數座標） | `kind:'polygon'` |

寫檔細節（移植時要保持一致）：欄位用 **TAB** 分隔、換行固定 **LF**、數值 `%.6f` 且 clamp 到 `[0,1]`、少於 3 點的形狀丟棄、讀檔用 `utf-8-sig` 容忍 BOM。詳見 [WebTraining.md §4](WebTraining.md)。

### 6.3 類別顏色

```js
function classColor(i) {
  const hues = [230, 12, 152, 38, 280, 190, 330, 96, 20, 258];
  const h = hues[i % hues.length] + Math.floor(i / hues.length) * 17;
  return `hsl(${h % 360} 72% 55%)`;
}
```

固定色相表（前 10 類彼此差異最大），超過 10 類就整體偏移 17°。飽和度／亮度鎖死 72%/55%，保證在深淺兩種底色上都看得見。

**半透明填色的寫法**（常見坑）：

```js
// hsl(230 72% 55%) → hsla(230 72% 55% / .3)
CTX.fillStyle = col.replace('hsl', 'hsla').replace(')', ' / .3)');
```

用的是 CSS Color 4 的斜線 alpha 語法。如果把顏色改成 `hsl(230, 72%, 55%)` 這種逗號舊語法，這個字串拼接就會產生無效色而畫不出東西——改寫色票函式時務必連這裡一起改（或改用 `color-mix()` / 直接產生 `hsla`）。

---

## 7. 畫布與視圖

### 7.1 視圖轉換

狀態只有三個數：`zoom`、`ox`、`oy`（畫面像素的平移量）。

```js
const toScr  = (nx, ny) => [nx * img.naturalWidth  * S.zoom + S.ox,
                            ny * img.naturalHeight * S.zoom + S.oy];
const toNorm = (px, py) => [(px - S.ox) / (S.zoom * img.naturalWidth),
                            (py - S.oy) / (S.zoom * img.naturalHeight)];
```

| 函式 | 行為 |
| --- | --- |
| `fitView()` | `zoom = min(w/iw, h/ih) * 0.96` 並置中（留 4% 邊距） |
| `fitCenter()` | 保持 zoom 只重新置中（給 1:1 用） |
| `zoomAt(px,py,f)` | **以游標為錨點**縮放：`ox = px - (px-ox) * (nz/zoom)`，clamp 到 `0.02~40` |
| `resizeCanvas()` | 依 DPR 設 `canvas.width/height`，`ctx.setTransform(dpr,0,0,dpr,0,0)` |

兩個細節：

- **DPR**：畫布實體尺寸乘 `devicePixelRatio`，再用 `setTransform` 把繪圖座標拉回 CSS 像素，否則高解析螢幕上線條會糊。
- **`userView` 旗標**：使用者自己縮放／平移過就設為 true，之後版面變動（`ResizeObserver`）只重畫不重置視圖；沒動過才自動重新 fit。按「符合」會把旗標清掉。
- 版面尺寸在字型與清單載入後才穩定，所以用 `ResizeObserver` 觀察容器而不是只聽 `window.resize`；量到 `< 2px` 時直接跳過（版面還沒成形）。

### 7.2 繪製流程

```
清空 → 填 --canvas-bg → drawImage（zoom<4 才開 imageSmoothing）
     → 每個 shape：路徑 → 填色(選取 .3 / 未選 .15) → 描邊(選取 2.5px / 未選 1.6px)
                  → 類別標籤（最上方頂點上緣的實心色條 + 白字）
                  → 若選取：畫每個頂點（白心 + 類別色環，拖曳中的那顆放大 1.5px）
     → 若在繪製中：虛線折線到游標位置，首點畫大一點（提示可點擊閉合）
     → updateStatus()
```

類別標籤放在**最上方頂點**（`pts.reduce((a,p)=>p[1]<a[1]?p:a)`）的上緣，寬度用 `measureText().width + 10` 算，避免遮住物件本身。文字內容是 `${cls} ${className(cls)}`，bbox 另外加 ` [box]` 尾綴，讓使用者一眼看出哪些還沒被編輯過。

### 7.3 命中測試

| 函式 | 演算法 | 半徑 |
| --- | --- | --- |
| `hitVertex` | 逐頂點的方形距離（`abs(dx)<=HIT && abs(dy)<=HIT`） | `HIT`（8 / 觸控 16） |
| `hitShape` | 正規化座標上的射線法 `pointInPoly` | — |
| `hitEdge` | 點到線段距離 `distToSeg`（含端點投影 clamp） | `HIT` |

三者都**從最後一個 shape 往前找**（後畫的在上層，先命中）。優先序是：頂點 → 多邊形內部 → 空白（平移）。

---

## 8. 標記互動規格

### 8.1 操作對照表

| 操作 | 行為 |
| --- | --- |
| 滾輪 | 以游標為中心縮放 |
| 中鍵拖曳 / `Space`+拖曳 / 拖曳空白處 | 平移畫面 |
| 拖曳頂點 | 調整該點（拖曳中即時 `markDirty()`） |
| 拖曳多邊形內部 | 整體位移（用起始點的 `orig` 快照 + delta，避免累積誤差） |
| 雙擊邊線 | 在最近的邊上插入頂點 |
| `Alt`+點頂點 / 右鍵點頂點 | 刪除該頂點（少於 3 點時拒絕並提示） |
| 點多邊形 | 選取（同步高亮右側物件清單） |
| 點空白 | 取消選取並開始平移 |
| 單指拖曳（觸控） | 依命中結果 = 拖頂點 / 移動形狀 / 平移 |
| 雙指（觸控） | 以起始中點為錨縮放，同時跟著中點位移平移 |

### 8.2 繪製新多邊形

進入 `draw` 模式（工具列或 `N`）後：每點一下推一個點；點滿 3 點後**點回第一點附近**（`HIT+2` 內）閉合；`Enter` 直接完成；雙擊完成（並丟掉雙擊產生的重複點）；`Esc` 取消。完成後自動回到 `select` 模式並選取新形狀——這個「畫完就回選取」的設計避免使用者誤畫出一堆多邊形。

游標在繪製模式改成 `crosshair`，並在狀態列顯示「新增多邊形中（Enter 完成 / Esc 取消）」。

### 8.3 鍵盤快捷鍵

| 鍵 | 動作 |
| --- | --- |
| `Ctrl+S` / `Ctrl+Z` | 儲存 / 復原 |
| `N` / `V` | 新增多邊形 / 選取模式 |
| `O` | 自動優化（選取者，未選則全部） |
| `F` / `G` | 符合視窗 / 100% 置中 |
| `←` `→` 或 `A` `D` | 上一張 / 下一張（跨頁時自動翻頁） |
| `Delete` / `Backspace` | 刪除選取的多邊形 |
| `Esc` / `Enter` | 取消繪製 / 完成繪製 |
| `0`~`9` | 把選取物件改成該類別，同時把「新形狀預設類別」設成它 |
| 按住 `Space` | 暫時切換成平移 |

防護規則（**移植時最容易漏掉**）：

```js
const isTyping = (e) => ['INPUT','SELECT','TEXTAREA'].includes(e.target?.tagName);
// Ctrl+S / Ctrl+Z 先處理（表單內也要能存檔）
// 其餘快捷鍵：isTyping 或帶修飾鍵時一律不處理，且只在標註頁生效
if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
if (S.page_ !== 'annotate') return;
```

有 Modal 開著時也應該停用工作區快捷鍵（`0~9`、`Delete` 尤其危險）。若圖片檢視器元件自己吃了數字鍵，類別指定要掛在 capture 階段才搶得到。

### 8.4 未儲存保護

四道防線，缺一不可：

1. `markDirty()` → 狀態列顯示琥珀色「● 未儲存」。
2. 切換影像、切 split、換資料夾、套用切分前都走 `await confirmDirty()`；有變更就跳「儲存 / 不儲存 / 取消」三選一 Modal（`Enter` = 儲存、`Esc` = 取消），回傳 false 就中止整個動作。
3. `beforeunload` 攔截關閉分頁。
4. `hist` 保留最近 **60 步**的 `JSON.stringify(shapes)` 快照，`Ctrl+Z` 逐步還原。

`pushHist()` 的呼叫時機是「**動作開始前**」：按下頂點時、開始拖曳形狀時、插點／刪點前、改類別前、刪除形狀前、自動優化前。優化若一個物件都沒改成功，要把剛推入的快照 `pop()` 掉，避免製造一步空的還原。

### 8.5 自動優化（輪廓貼邊）

前端純 JS，不需要後端也不需要模型：

```
建梯度圖（每張影像只做一次，快取在 GRAD）
  最長邊縮到 1280 → 灰階(0.299/0.587/0.114) → 3×3 均值降噪 → Sobel 幅值 → 正規化到 0~1
逐形狀：
  等距重取樣（step = max(2, R*0.6)，總點數上限 2000）
  迭代 3 次：
     每點沿法線在 ±R 內以 0.5px 步進搜尋 (梯度 − 0.035×|位移|) 的最大值   ← 位移懲罰避免亂跑
     Laplacian 平滑（alpha 0.3）
  Douglas–Peucker 簡化（eps = max(0.9, R*0.22)；超過 120 點就 eps×1.5 再簡化）
  寫回並把 kind 轉成 polygon
```

`R` 由「優化強度」下拉決定：弱 4 / 中 7 / 強 12。

UI 上的三個約定：
- **不自動儲存**，完成後用 warn 色 toast 明說「尚未儲存，確認後請按 Ctrl+S（Ctrl+Z 可還原）」。
- 按鈕用 amber（`.btn-warn`）而不是主色，把「這會大幅改動資料」的意思做進顏色裡。
- 影像跨來源時 `getImageData()` 會丟例外（畫布被污染），要 try/catch 後提示「無法讀取影像像素」，不能讓整頁掛掉。

### 8.6 周邊面板

- **影像清單**（左）：縮圖 44×33 + 檔名 + 物件數 badge（0 顯示紅底）；上方有搜尋（250ms debounce）、狀態篩選（全部／已標記／未標記）、類別篩選；底部分頁器可選每頁 30/60/120/240。
- **物件清單**（右）：每列 = 色塊 + 類別下拉 + 頂點數 + 刪除鈕，點列即選取並同步畫布。下面兩排是「優化選取／優化全部」與「刪除選取／清空全部」。
- **快速分類**（右）：類別 chips，點選決定**新多邊形**的類別；配合 `0~9` 快捷鍵。
- **多圖瀏覽**：縮圖牆（`repeat(auto-fill,minmax(210px,1fr))`），每格是一張 380×285 的 canvas，把該張的標記輪廓直接畫在縮圖上（填色 alpha .26），用來快速巡檢哪幾張標壞了；點一下開圖並跳回標註頁。

---

## 9. 前端程式慣例

無框架、無建置，靠幾條約定維持可讀性：

```js
const $ = (id) => document.getElementById(id);   // 全部元素用 id 取
const S = { … };                                 // 單一全域狀態物件（資料集、影像、形狀、視圖、模式）
async function api(path, opts)                   // fetch 包裝：非 JSON 或含 error 一律 throw
const post = (path, body) => api(path, {method:'POST', headers:{…}, body:JSON.stringify(body)});
function toast(msg, kind)                        // 統一回饋出口：'' / 'ok' / 'err' / 'warn'
```

- **所有錯誤都走 `toast(e.message, 'err')`**，不用 `alert`；只有破壞性動作用原生 `confirm()`（且訊息要寫清楚會動到哪些檔案）。
- **DOM 用 `createElement` 組**，只有純資料表格才用字串樣板；任何來自使用者或檔名的字串都不進 `innerHTML`。
- **渲染函式命名一致**：`renderList` / `renderShapes` / `renderClasses` / `renderGrid` / `renderVideoStatus` / `renderTrainStatus`，每個都是「從 `S` 重畫整塊」，不做增量 DOM 更新。
- **競態處理**：`openImage()` 用遞增的 `openSeq` 丟棄過期回應（連按下一張時，先發的請求可能後回來，畫面會停在舊圖但 `S.cur` 已經換人，存檔就會寫錯檔案）。
- **快取世代**：影像 URL 帶 `g=<S.gen>`，換資料夾或搬移檔案後 `S.gen++`。不同資料集的檔名幾乎都是 `1.jpg`，沒有這個參數瀏覽器會拿舊圖配新標記。
- **輪詢**：用 `*_INFLIGHT` 旗標擋重入（兩個輪詢同時在路上會用同一個 `logFrom` 重複取 log），執行中 1 秒、閒置 5 秒；log 只取增量並在「原本就捲到底」時才自動捲到底。

---

## 10. 移植檢查清單

搬到別的專案（尤其是 React / Vue / Tailwind）時，照這張表逐項確認：

**視覺**
- [ ] 先把 §1 的兩組 CSS 變數搬過去（Tailwind 就映射成 theme tokens 或直接用 CSS 變數），元件才有共同語言。
- [ ] 深色不是反相，要用另一組刻意挑過的深藍灰；陰影也要換成純黑。
- [ ] 主題初始化 script 放在 CSS 之前，避免載入閃白。
- [ ] 換主題後手動重畫所有 canvas / 圖表。
- [ ] SVG 全域描邊規則會影響 `<text>`，自製圖表補 `text{stroke:none}`。

**版面**
- [ ] 容器要有明確高度（`height:100%` / `h-full w-full` 一路傳到畫布容器）。**把 ImageViewer 包進新版面時最常見的災情就是 root 少了高度而塌成 0，畫面全黑。**
- [ ] 三欄 grid 的中欄用 `minmax(0,1fr)`。
- [ ] 容器尺寸用 `ResizeObserver` 監看，量到 ≤1px 時不要鎖定「已完成 fit」的旗標。

**標記**
- [ ] 座標正規化、`{cls, kind, points}`、bbox 被編輯後才轉 polygon。
- [ ] 半透明填色的字串拼接與色票函式的語法要對得上（`hsl(h s% l%)` + ` / alpha`）。
- [ ] 命中半徑依 `pointerType` 切換，觸控頂點畫大一點。
- [ ] Pointer Events 一套處理滑鼠與觸控；`touch-action:none`；`setPointerCapture` 要包 try/catch。
- [ ] `pushHist()` 在動作前呼叫；優化失敗要 `pop()`。
- [ ] 快捷鍵排除輸入框與 `select` 聚焦、Modal 開啟時停用；被子元件吃掉的鍵改掛 capture 階段。
- [ ] dirty → 切圖確認 → `beforeunload` 三道都要在。
- [ ] 影像 URL 帶版本參數；後端用 ETag 而非 `max-age`。

**行動版**
- [ ] 側欄抽屜 + 遮罩、頂欄工具下拉面板、標註頁直式堆疊。
- [ ] 觸控目標放大到 ≥40px；縮圖牆的刪除鈕要防誤觸（用兄弟元素 + `pointer-events` 防護，不要疊在可點的縮圖上）。

### 已知的衍生變體

同一套設計語言在 React + Tailwind 的專案（VisionSequence 教導畫面）上做過一次移植，主要差異可以直接參考：工具改成畫布左側的**垂直大圖示工具欄**（44px 按鈕、22px 圖示、角落標快捷鍵）、上方固定狀態列（上下張 / 尺寸 / 標記數 / 未儲存指示 / 快捷鍵說明 Modal / 儲存）、類別改成**大顆按鈕**（色點 + 數字鍵標示 + 計數）、縮圖牆與畫布等高且選中自動捲入視野。色票抽成獨立模組（固定色相表 + 超過 10 類偏移），與 §6.3 的邏輯完全一致。

---

## 11. 檔案對照

| 想改什麼 | 看哪裡 |
| --- | --- |
| 配色、圓角、陰影、尺寸 | `style.css` 開頭的 `:root` / `[data-theme="dark"]` |
| 版面骨架與斷點 | `style.css` 的 `#sidebar` / `#topbar` / `#content` / `.annotate-grid` / 檔尾 media queries |
| 元件樣式 | `style.css` 的 Buttons / Inputs / Card / Table / Modal / Toast 分節 |
| 頁面結構與文案 | `index.html`（每個 `<section class="page" data-page="…">` 是一頁） |
| 畫布繪製與視圖 | `app.js` §繪製 / §視圖轉換 |
| 互動與快捷鍵 | `app.js` §指標輸入 / §鍵盤 |
| 自動優化演算法 | `app.js` §一鍵自動優化 polygon ROI |
| 標記檔讀寫 | `labelServer.py` 的 `_parse_label()` / `Dataset.write_shapes()` |
