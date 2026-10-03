# GitHub Pages：自動化設備 3D 展示

工作流程在儲存庫根目錄的 [`.github/workflows/pages.yml`](../../.github/workflows/pages.yml)。第一次使用要到 Settings → Pages，把 Source 選成 GitHub Actions。

| 觸發 | 做什麼 |
|---|---|
| PR | 只跑快速檢查與建置，不發布 |
| 推送到 `main` | 快速檢查 → 建置 → 發布 |
| 手動（Actions → Run workflow） | 同推送到 `main` |

流程：

1. `node core/tools/check.mjs --quick`：
   - 共用模型檢查；
   - 每個專案的 import 路徑、倒序一致、空間檢核、全場干涉與閃爍（含各情境）；
   - `project.json` 的 `checks.quick`（各專案的 `tools/verify.mjs`）。

   任一項失敗就不發布，約需數分鐘。瀏覽器互動檢查（`ui`）只在本機完整檢查跑，不在 CI。
2. `node core/tools/build-site.mjs _site`：
   - 首頁 `/` 由 `core/tools/site.mjs` 產生，標題與說明取自各專案 `project.json`；
   - `/core/` 只發布一份共用模組與 three.js（不含 `core/tools`、`core/template`、`core/verify`、`core/review` 與文件）；
   - `/<專案>/` 發布該專案 `web/` 的全部內容。

新增專案（`node core/tools/new-project.mjs …`）後，只要有 `web/index.html` 與 `project.json`，就會自動出現在首頁，不必改工作流程。

網址配置與本機 `node core/tools/serve.mjs` 相同，本機看到的就是發布後的結果。所有連結都是相對路徑，庫名改變不影響網站。

- 線上網址：`https://<帳號>.github.io/<庫名>/`。
- 專案頁：`https://<帳號>.github.io/<庫名>/<專案>/`。`shutter assembly` 網址中的空白為 `%20`。

不發布 docs、成本表、原始照片、影片與驗證報告。這只控制 Pages 網站內容，不會改變儲存庫本身的公開／私有設定。

動畫與相機模擬在瀏覽器運行。MP4 錄影輸出要在本機跑 `tools/movie-export`（需要 `setup.ps1 -Ffmpeg`）。
