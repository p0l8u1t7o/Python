# 四站 3D 干涉回歸檢查

使用 Node.js 22 以上，不需安裝 npm 套件。在工作區根目錄執行：

```powershell
node tools/verify-interference.mjs
```

每次修改模型、工具尺寸、配方或路徑後重跑。可單獨指定一個或多個專案：

```powershell
node tools/verify-interference.mjs MilitaryGradePC RobotArmPressSSD
```

完整執行包含 16 組檢查。失敗或測試期間原始碼變更時，程序回傳非零退出碼；可直接作為後續提交或 CI 的檢查步驟。選擇部分專案時，報告只代表這次選定範圍。

- 總表：[interference-checks.json](../review/interference-checks.json)，記錄各項結果、耗時、來源 SHA-256 及完整紀錄路徑。
- 詳細輸出：各專案的 `review/checks/*.log`。
- 修正及涵蓋範圍：[四站干涉修正紀錄](../interference-review.md)。

`geometry-clearance.mjs` 提供模型網格的有向包圍盒分離軸檢查及含端點的時間取樣。工具法蘭安裝、壓頭接觸、滑軌支承等允許接觸由各測試明確定義。包圍盒正間距為保守淨空下限；重疊需要再檢視中空或曲面幾何，不能視為精確穿透深度。

這是可重跑的動畫回歸檢查，不是背景排程或實機安全認證；有限時間取樣不構成連續碰撞證明，仍未涵蓋完整動態軟管、線纜、公差與所有非相鄰連桿。
