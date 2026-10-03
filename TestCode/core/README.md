# core：3D 自動化動畫共用框架

TestCode 底下每個有 `web/index.html` 的資料夾都是一個展示專案。共用的程式、three.js、檢查工具與建置都放在這裡，各專案直接引用，不複製。

## 目錄

| 路徑 | 內容 |
|---|---|
| `vendor/` | three.js r160（`three.module.js`）與 addons，全站只有這一份 |
| `geom/` | `shapes.js`（統一形狀：block／blockBetween／cylinder／rod／tube／pipe／profile／rounded／bevelBox／screw／decal／plate／floorText）、`materials.js`（共用材質表 MAT）、`hardware.js`（倒角外殼、螺栓、腳座、馬達、感測器…）、`finish.js`、`surfaces.js`、`perforated.js` |
| `robot/` | `kinematics.js`：6 軸阻尼最小平方 IK（參數可調） |
| `models/` | 共用模型庫：每個模型有 `meta`（名稱、分類、可調參數、可動狀態、用法）與 `create(params) → { root, set(state) }`，在 `models/index.js` 登記；目錄頁 `/core/catalog/` 可預覽與調參 |
| `catalog/` | 模型目錄頁（發布在 Pages） |
| `anim/` | `track.js`：時間軌與時間軸（`createTimeline`、`Track`、`smooth`），狀態只由時間決定 |
| `electrical/` | 線材、拖鏈、電盤、電控元件與檢視器 |
| `movie/` | 錄影程式（4K 取樣 1080p、絕對時間取樣、追焦運鏡），各專案以 `?movie` 呼叫 |
| `ui/` | `stage.js`（renderer／場景／相機／燈光／3D 標籤／視角轉場／畫面迴圈／`exposeSim`）、`player.js`（標準播放列）、`viewer-workspace`（相機視窗與焦點）、`view-controls`、`vision-overlay` |
| `verify/` | 統一檢查：`scene.mjs`（全場干涉＋重合面閃爍）、`determinism.mjs`（倒序一致）、`run.mjs`（執行入口）、`dom-stub.mjs` |
| `template/` | 新專案範本（`tools/new-project.mjs` 複製） |
| `tools/` | 伺服器、檢查執行器、截圖比對、Pages 建置、建立新專案（不發布） |

## 新專案

```powershell
node core/tools/new-project.mjs MyStation "我的工作站" "首頁卡片上的一句說明"
```

範本已經接好舞台、播放列、時間軸、`project.js` 與一支自有檢查，建好就能開啟、檢查，推送後自動出現在 Pages 首頁。之後在 `project.js` 建模型與時間軸，在 `main.js` 加視角與面板。

## 引用方式

各專案 `index.html` 的 importmap：

```html
<script type="importmap">
{ "imports": {
    "three": "../core/vendor/three.module.js",
    "three/addons/": "../core/vendor/addons/",
    "@core/": "../core/"
} }
</script>
```

程式中寫 `import { block, cylinder } from '@core/geom/shapes.js'`、`import { MAT } from '@core/geom/materials.js'`。Node 端用 `core/tools/register.mjs` 解析相同名稱：

```powershell
node --import ../core/tools/register.mjs tools/verify.mjs      # 在專案資料夾
node core/tools/run.mjs <專案> tools/verify.mjs                 # 在 TestCode
```

## 網址（本機與 GitHub Pages 相同）

| 網址 | 來源 |
|---|---|
| `/` | 首頁（`tools/site.mjs` 依各專案 `project.json` 產生） |
| `/core/…` | `core/`（不含 tools） |
| `/<專案>/…` | `<專案>/web/…` |

```powershell
node core/tools/serve.mjs                 # http://127.0.0.1:8770/  首頁
node core/tools/serve.mjs Chemical        # 直接開某專案（名稱可只打開頭）
```

各專案的 `run.bat` 就是呼叫它。

## project.json

```json
{
  "title": "200L 化學桶自動清洗線",
  "summary": "首頁卡片上的一句說明",
  "order": 2,
  "checks": { "quick": ["tools/verify.mjs"], "full": ["tools/verify-gripper.mjs"] },
  "core": { "skip": [], "quick": [] },
  "shots": { "views": ["iso", "robot"], "skip": ["follow"] }
}
```

## 專案介面：`web/js/project.js`

網頁（`main.js`）與統一檢查用同一個函式建立場景，所以檢查的就是畫面上的幾何。

```js
export function createProject({ scene, headless }) {
  // 建立所有設備並加入 scene；不得碰 DOM（文字貼圖可用 canvas，Node 端有 dom-stub）
  return {
    total,                 // 動畫總長（秒）
    apply(t, opts) {},     // 把整個場景放到時間 t；必須只依 t 決定（倒序、跳播結果相同）
    layoutChecks() {},     // 選用：[{ group, name, ok, value, note }]
    verify: {              // 選用：全場檢查設定
      dt: .5,              //   動態取樣間隔（預設 total/400，至少 0.05 s）
      skip(obj) {},        //   非實體（尺寸標註、地面分區、天花板…）→ true
      moduleOf(mesh) {},   //   模組名稱（預設：scene 第一層子物件的 name）
      stationOf(mesh) {},  //   同模組再分工位；不同工位的固定件穿插也算相撞
      allow: [{ why, test(a, b, ctx) {} }],   // 允許的接觸，逐條寫原因；ctx.moduleOf(m)、ctx.bodyOf(m)
      envelope: ['robot'], //   回報這些模組的掃掠外圍（配置圍籬用）
    },
    // 其他給 main.js 用的物件（robot、sequence…）照常附上
  };
}
```

物件標記（`userData`）：

- `fx`：效果（噴霧、光束、氣流），不是實體，不檢查；
- `guide = 'id'`／`on = 'id'`：導軌與在其上滑行的移動件；
- `nested = 另一個關節物件`：套筒式伸縮（內外管）。

`window.sim` 至少提供：`seekTo(t)`、`setView(name, instant)`、`views`（視角名稱陣列）、`total`、`play()`、`pause()`。

## 共用舞台（`core/ui/stage.js`）

```js
const stage = createStage({ canvas, exposure: .86, fog: [5000, 11000], logDepth: true,
  camera: { fov: 40, near: 2, far: 20000 }, controls: { minDistance: 8, maxDistance: 7000 },
  envLight: 220, sun: { position, target, shadow: { mapSize, camera, bias, normalBias } }, fill: { … },
  extraLights: [{ color, intensity, position, target, shadow }] });
stage.loop(dt => { /* 推進時間、更新面板 */ return changed; }, { render: drawEverything });
exposeSim({ seekTo, setView, views, total, play, pause, get T() { return T; } });
```

- 網址參數一致：`?shadow=0`、`?aa=0`、`?logdepth=0/1`、`?movie`（錄影：不跑迴圈、不聽 resize、強制對數深度）。
- `loop(tick, { render })`：多畫面專案（主畫面＋相機子畫面＋疊圖）傳自己的整格繪製；不傳則只畫主畫面。
- 錄影：`?movie` 時在 main.js 呼叫 `installMovie({...})`（`core/movie/movie.js`），各站的取樣、追焦、細節重播設定寫在專案裡；`tools/movie-export/prepare.py` 只建網站副本。

## 統一寫法（新專案與既有專案都照這個）

| 項目 | 用法 |
|---|---|
| 形狀與材質 | `@core/geom/shapes.js`（block／cylinder／rod…，陣列參數）＋`@core/geom/materials.js` 的 `MAT`。常見材質（鋼、鋁、烤漆、黑件、指示燈）用 MAT，產品專屬外觀才在專案自建 |
| 排程 | 單一手臂依序作業：`createStepSequence`（`@core/anim/sequence.js`）；多台設備並行：`createTimeline`（`@core/anim/track.js`）。兩者都提供 `events`、`stationStart`、`total` |
| 播放列 | `createPlayer`（`@core/ui/player.js`）綁定標準元素 `playBtn／restartBtn／speed／speedVal／timeline／clock／stepSelect／previous／next`，事件選單用排程的 `events` |
| 3D 標籤 | `stage.addLabel(html, getPos, cls)`，每格 `stage.updateLabels(show)` |
| 視角 | `VIEWS = { 名稱: [位置, 注視點] 或 () => [...] }`，切換用 `stage.goTo(位置, 注視點, instant)` |
| 相機子畫面與焦點追隨 | `createViewerWorkspace`（`@core/ui/viewer-workspace.js`） |
| window.sim | `exposeSim({ seekTo, setView, views, total, play, pause, … })` |

## 檢查

```powershell
node core/tools/check.mjs                  # 全部專案完整檢查
node core/tools/check.mjs Chemical         # 單一專案
node core/tools/check.mjs --quick          # 部署前快速檢查（GitHub Actions）
node core/tools/check.mjs --only scene     # 只跑某項
```

| 檢查 | 快速 | 內容 |
|---|---|---|
| `models`（core） | ✓ | 每個共用模型以預設參數建立，狀態走完全範圍，做干涉與重合面檢查（`core/review/models.json`） |
| `imports` | ✓ | 從 index.html 走遍 import 圖，找不到的檔案（部署後才會壞的路徑） |
| `determinism` | ✓ | 40 個時間點順序與倒序取樣，所有可見物件的世界矩陣必須相同 |
| `layout` | ✓ | `layoutChecks()` 全數通過 |
| `scene` | ✓ | 動態干涉、靜態架設相撞、重合面閃爍；結果寫入 `review/scene-verification.json/.txt` |
| 專案自有 | 依 `checks` | `project.json` 的 `checks.quick`／`checks.full` |

## 回歸比對（改共用模組或渲染時）

```powershell
node core/tools/shots.mjs --out TEMP/shots-base                          # 先拍基準
node core/tools/shots.mjs --out TEMP/shots-new --compare TEMP/shots-base # 改完比對
python core/tools/compare-review.py TEMP/review-base                     # review JSON 結果比對
```

截圖在同一台機器重拍差異為 0，超過門檻（預設 0.2% 像素）的會另存 `.diff.png`。

## GitHub Pages

`.github/workflows/static.yml` 會先跑 `check.mjs --quick`，再用 `tools/build-site.mjs _site` 建置。新增專案只要有 `web/index.html` 與 `project.json` 就會出現在首頁，不必改工作流程。
