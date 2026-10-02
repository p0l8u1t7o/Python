# __TITLE__

__SUMMARY__

由 `node core/tools/new-project.mjs` 從 `core/template` 建立。框架說明見 [core/README.md](../core/README.md)。

## 啟動

雙擊 `run.bat`，或：

```powershell
node ../core/tools/serve.mjs "__ID__"
```

開啟 http://127.0.0.1:8770/__URL__/。網址參數：`?pause&t=5&view=pick`、`?shadow=0`、`?cam=x,y,z,tx,ty,tz`。

## 檢查

```powershell
node ../core/tools/check.mjs "__ID__"          # 完整：import 路徑、倒序一致、空間檢核、全場干涉與閃爍、本專案檢查
node ../core/tools/check.mjs "__ID__" --quick  # 部署前快速檢查
```

## 檔案

| 檔案 | 用途 |
|---|---|
| `project.json` | 標題、首頁說明、檢查清單 |
| `web/js/project.js` | 建立場景、時間軸、`apply(t)`、空間檢核、全場檢查設定（網頁與檢查共用） |
| `web/js/main.js` | 舞台、播放控制、視角與面板 |
| `tools/verify.mjs` | 本專案的製程規則檢查 |
