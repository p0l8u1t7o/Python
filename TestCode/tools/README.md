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

- 總表：[interference-checks.json](review/interference-checks.json)，記錄各項結果、耗時、來源 SHA-256 及完整紀錄路徑。
- 詳細輸出：各專案的 `review/checks/*.log`。
- 修正及涵蓋範圍：[四站干涉修正紀錄](docs/interference-review.md)。

`geometry-clearance.mjs` 提供模型網格的有向包圍盒分離軸檢查及含端點的時間取樣。工具法蘭安裝、壓頭接觸、滑軌支承等允許接觸由各測試明確定義。包圍盒正間距為保守淨空下限；重疊需要再檢視中空或曲面幾何，不能視為精確穿透深度。

這是可重跑的動畫回歸檢查，不是背景排程或實機安全認證；有限時間取樣不構成連續碰撞證明，仍未涵蓋完整動態軟管、線纜、公差與所有非相鄰連桿。

## 五站配線檢查

共用線材模型修改後，先同步至各站，再執行配線檢查：

```powershell
node tools/sync-cable-routing.mjs
node tools/sync-electrical-cabinet.mjs
node tools/verify-cable-routing.mjs
```

涵蓋上述四站與 `shutter assembly`，檢查主要外露線路的取樣碰撞、拖鏈定長、折返半徑及行程。總表為 [cable-checks.json](review/cable-checks.json)，各站 `review/cables.json` 記錄配方、取樣數與失敗項目。程序同時確認五站共用來源一致，以及執行期間來源沒有變更。

配線檢查補充原有機構檢查，不能取代它。現在也檢查帶有 `userData.support` 的支架、線夾腳與拖鏈承托板；未模擬軟線下垂、疲勞、全線材互撞及支架強度。配置與選型依據見[五站線材研究](docs/cable-routing-review.md)，本次修正見[支架檢查紀錄](docs/support-routing-review.md)。網頁的「線材配置」按鈕提供觀察視角，右下角可展開配色說明。


## 穿板孔與電盤

`electrical-cabinet.js` 提供真實開孔、穿板接頭、中空機櫃、固定背板及端子配線；五站「電盤配線」可查看櫃內。配線檢查另驗證孔洞暢通、接頭上下連續穿線及背板固定柱接觸櫃壁。詳見[穿板與電盤紀錄](docs/electrical-routing-review.md)。

## 電控元件配置

`electrical-components.js` 定義各站的元件、功能連接與安裝包絡；`electrical-inspector.js/css` 提供選取、特寫、剖視／透視及同步狀態。修改後執行 `node tools/sync-electrical-cabinet.mjs` 同步五站。

```powershell
node --no-warnings --experimental-loader ./MilitaryGradePC/tools/three-loader.mjs tools/verify-electrical-plan.mjs
```

這項檢查不需 npm 套件，總表為 `tools/review/electrical-plan-checks.json`；另重跑原有配線與機構檢查。操作與來源見[五站電控規劃](docs/electrical-control-plan.md)。

## 五站共用視窗控制

`viewer-workspace.js`、`viewer-workspace.css` 管理相機拖曳、獨立視窗與產品焦點；修改後執行 `node tools/sync-viewer-workspace.mjs` 同步五站。詳見[操作說明](docs/viewer-controls.md)與[瀏覽器驗證紀錄](review/viewer-workspace-checks.json)。
