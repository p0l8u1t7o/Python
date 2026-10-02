# GitHub Pages：自動化設備 3D 展示

`static.yml` 與儲存庫最外層的 `.github/workflows/static.yml` 相同。Pages 的 Source 選 GitHub Actions，推送到 `main` 後發布，也可在 Actions 手動執行。

流程：

1. `node TestCode/core/tools/check.mjs --quick`：每個專案的靜態 import 路徑檢查，以及 `project.json` 的 `checks.quick`（目前為各專案的 `tools/verify.mjs`）。任一項失敗就不發布。
2. `node TestCode/core/tools/build-site.mjs _site`：
   - 首頁 `/` 由 `core/tools/site.mjs` 產生，標題與說明取自各專案 `project.json`；
   - `/core/` 只發布一份共用模組與 three.js（不含 `core/tools`、`core/template` 與文件）；
   - `/<專案>/` 發布該專案 `web/` 的全部內容。

新增專案時，在 `TestCode/<專案>/` 放 `web/index.html` 與 `project.json`，就會自動出現在首頁，不必改工作流程。

網址配置與本機 `node TestCode/core/tools/serve.mjs` 相同，本機看到的就是發布後的結果。

線上展示：[展示首頁](https://p0l8u1t7o.github.io/Python/) · [化學桶清洗線](https://p0l8u1t7o.github.io/Python/ChemicalTankWashing/)。`shutter assembly` 網址中的空白為 `%20`。

不發布 docs、成本表、原始照片、影片與驗證報告。這只控制 Pages 網站內容，不會改變儲存庫本身的公開／私有設定。

動畫與相機模擬在瀏覽器運行。MilitaryGradePC 的 MP4 伺服器輸出仍需獨立後端。
