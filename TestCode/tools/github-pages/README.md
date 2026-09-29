# GitHub Pages：六個自動化展示

將本資料夾的 `static.yml` 完整內容放到 GitHub 儲存庫最外層的 `.github/workflows/static.yml`，覆蓋先前版本。Pages 的 Source 選 GitHub Actions，推送到 `main` 後發布；也可在 Actions 手動執行。

工作流程自動建立首頁，包含：

- AutomaticAcid-BaseTitration
- MilitaryGradePC
- PCB-CopperAssembly
- RobotArmPressSSD
- shutter assembly（網址中的空白使用 `%20`）
- WorkpieceMeasurement（杯體加工件 AOI 與共焦量測）

來源可為 `TestCode/<專案>/web/`、`<專案>/web/`，或展示專用儲存庫中的 `<專案>/index.html` 結構。六個專案都必須已上傳；缺檔會停止發布，避免覆蓋成缺少入口的網站。

僅收集各網頁的 HTML、圖示、css、js、vendor、assets；不發布 docs、成本表、原始照片、影片、驗證報告。這個篩選控制 Pages 網站內容，不會改變 GitHub 儲存庫本身的公開／私有設定。

`site/` 為本機產生的預覽，`automation-demos.zip` 為同一批靜態網站檔案；兩者不納入 Git。若使用展示專用儲存庫，解壓縮後上傳檔案與子資料夾，不要只上傳 ZIP。GitHub Pages 不會自動解壓縮它。

動畫與相機模擬在瀏覽器運行。MilitaryGradePC 的 MP4 伺服器輸出仍需獨立後端。
