# TestCode 專案展示與研究

每個子專案的程式、模型、資料與說明均放在自己的資料夾。

| 子專案 | 用途 |
| --- | --- |
| [AutomaticAcid-BaseTitration](AutomaticAcid-BaseTitration/) | 自動酸鹼滴定 |
| [ChemicalTankWashing](ChemicalTankWashing/) | 200L 化學桶自動清洗線、夾具與相機追蹤 |
| [MilitaryGradePC](MilitaryGradePC/) | 軍規電腦自動檢測 |
| [PCB-CopperAssembly](PCB-CopperAssembly/) | 基板與散熱板組裝 |
| [RobotArmPressSSD](RobotArmPressSSD/) | SSD USB 銀腳壓合 |
| [shutter assembly](shutter%20assembly/) | 快門葉片與上蓋組裝 |
| [WorkpieceMeasurement](WorkpieceMeasurement/) | 杯體加工件 AOI 與共焦量測 |

所有 3D 專案共用 [core](core/README.md)：three.js、基本形狀、手臂與模型庫、時間軸、渲染舞台、播放列、錄影程式、統一檢查與 Pages 建置都只有一份，各專案以 `@core/` 直接引用。

```powershell
node core/tools/serve.mjs                     # 本機首頁 http://127.0.0.1:8770/（各專案 run.bat 也是它）
node core/tools/check.mjs                     # 全部專案完整檢查（干涉、閃爍、倒序一致、空間檢核、各專案自有檢查）
node core/tools/new-project.mjs <名稱> "<標題>"  # 由範本建立新專案
```

- 各 3D 專案：`web/` 為網站（`web/js/project.js` 是網頁與檢查共用的場景）、`project.json` 為首頁說明與檢查清單、`tools/` 為專案自有檢查、`review/` 為檢查結果、`docs/` 為本機參考資料。
- 共用模型目錄：本機 http://127.0.0.1:8770/core/catalog/，Pages 上為 `/core/catalog/`。
- [tools](tools/)：跨專案的配線、電盤、干涉回歸與影片輸出工具；`tools/docs/` 是跨專案研究文件，`tools/review/` 是彙總結果。
- [GitHub Pages 部署](tools/github-pages/README.md)：推送後先跑快速檢查，通過才發布；首頁依各專案 `project.json` 自動產生。
- `TEMP/`、`LOGS/`（不分大小寫）、`*.log` 與快取不納入版控。影片輸出位於 `TEMP/videos/`，不隨網站發布。
- CardServer、Bin 已退役並移出版控。本機暫存封存位於 `TEMP/retired-projects/`。
- 3D 專案只需 Node.js 22 以上，不需 npm 套件；其他依賴請依子專案 README。
