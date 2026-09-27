# TestCode 專案展示與研究

每個子專案的程式、模型、資料與說明均放在自己的資料夾。

| 子專案 | 用途 |
| --- | --- |
| [AutomaticAcid-BaseTitration](AutomaticAcid-BaseTitration/) | 自動酸鹼滴定 |
| [MilitaryGradePC](MilitaryGradePC/) | 軍規電腦自動檢測 |
| [PCB-CopperAssembly](PCB-CopperAssembly/) | 基板與散熱板組裝 |
| [RobotArmPressSSD](RobotArmPressSSD/) | SSD USB 銀腳壓合 |
| [shutter assembly](shutter%20assembly/) | 快門葉片與上蓋組裝 |
| [MonocularDepthEstimation](MonocularDepthEstimation/) | 單目深度估測工具 |

- 各 3D 專案：`web/` 為可獨立部署的網站、`tools/` 為專案驗證、`review/` 為該專案檢查結果、`docs/` 為本機參考資料。
- [tools](tools/)：共用模型工具、同步與驗證腳本；`tools/docs/` 是跨專案操作及研究文件，`tools/review/` 是共用工具的彙總結果。
- [GitHub Pages 部署](tools/github-pages/README.md)：僅發布五個 `web/`，首頁自動產生。
- `TEMP/`、`LOGS/`（不分大小寫）、`*.log` 與快取不納入版控。影片輸出位於 `TEMP/videos/`，不隨網站發布。
- CardServer、Bin 已退役並移出版控。本機暫存封存位於 `TEMP/retired-projects/`。
- 根目錄不集中安裝各專案的依賴；請依子專案 README 操作。
