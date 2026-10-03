# __TITLE__

__SUMMARY__

由 `node core/tools/new-project.mjs` 從 `core/template` 建立。框架說明見 [core/README.md](../core/README.md)。

## 啟動

雙擊 `run.bat`，或：

```powershell
node ../core/tools/serve.mjs "__ID__"
```

開啟 http://127.0.0.1:8770/__URL__/。網址參數：`?pause&t=5&view=pick`、`?shadow=0`、`?cam=x,y,z,tx,ty,tz`。

手機、平板與橫向手機自動改用精簡版面（☰ 製程與視角、⚙ 播放設定、工具列 ◨ 開側欄、▣ 相機視窗、◎ 追隨工件），由 `createViewerWorkspace` 處理；`css/style.css` 只寫桌面版面。

## 檢查

```powershell
node ../core/tools/check.mjs "__ID__"          # 完整：import 路徑、倒序一致、空間檢核、全場干涉與閃爍、四種尺寸的介面測試（ui）、本專案檢查
node ../core/tools/check.mjs "__ID__" --quick  # 部署前快速檢查
```

## 檔案

| 檔案 | 用途 |
|---|---|
| `project.json` | 標題、首頁說明、檢查清單 |
| `web/index.html` | 標準版面骨架：`#topbar`（`.brand`、`#stations`、`.views` 視角按鈕 `data-view`）、`#side`（`.card`）、`#bottombar`（`.ctl`、`.stepRow`、`#timeline`、`#clock`） |
| `web/css/style.css` | 桌面版面與深色主題（窄螢幕規則由 `core/ui/viewer-workspace.css` 負責，這裡不寫） |
| `web/js/project.js` | 建立場景（地面用 `floor()`）、站別、時間軸、`apply(t)`、空間檢核、全場檢查設定（網頁與檢查共用） |
| `web/js/main.js` | 舞台（`look`／`extent`）、`createViewerWorkspace`、視角、站別按鈕、3D 標籤、播放列、面板、`exposeSim` |
| `tools/verify.mjs` | 本專案的製程規則檢查 |
