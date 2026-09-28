# DEV-010 工作進度（暫停交接）

最後更新：2026-09-28。任務來源：`docs/CellForge_平台擴充開發書_v2.0.md` 的 P3／DEV-010「新增電控連接、I/O、盤面與圖面樣板，完成 PDF／SVG」，驗收 ACC-06「加相機、改 I/O、刪供電連接 → 3D、BOM、圖面與連接檢查同步變更」。

DEV-010 分三段進行，目前**第一段已完成並提交**，第二、三段尚未開始。

| 段落 | 內容 | 狀態 |
|---|---|---|
| （一） | 電控資料模型、設備樣板與點位池配置、連接檢查、建置整合、SSD 電控資料、測試 | ✅ 完成（D-041） |
| （二） | 圖面引擎（IR → SVG／PDF）、A3 圖框與標題欄樣板、各類圖頁、出圖檢查、匯出與 API | ⏳ 未開始 |
| （三） | 前端「電控」分頁與圖面↔3D 雙向定位、ACC-06 驗收、人工追線紀錄、驗收文件與 README | ⏳ 未開始 |

## 使用者已決定的事項（不需再問）

- **LOGO**：當作圖框樣板欄位，圖檔由使用者提供，放在案內 `drawing_templates/`（`electrical.yaml` → `drawing.logo`）。未提供時標題欄 LOGO 區顯示案名文字。**不要從參考 PDF 擷取 ideskvision 標誌**，也不要把客戶圖面複製進 repo。
- **SSD 電控資料**：由 TestCode `circuit-data.json` 轉入，全部標 inferred，並列入假設與待確認問題。已完成。
- **自動同步**：採「設備樣板＋自動配置 I/O」。手動指定的位址優先，並檢查是否重複。已完成。

## 第一段已完成的內容

程式與資料：

- `cellforge/schema/electrical.py`：`Electrical` 及其子模型，欄位說明見 D-041。已註冊到 `SCHEMAS`，並重新輸出 `docs/schema/electrical.schema.json` 與 `checks.schema.json`。
- `cellforge/electrical/resolve.py`：
  - `resolve_electrical(electrical, cell)`：設備樣板依模組實例展開；先佔用手動位址與端子排位置，再依點位池配置；I/O 展開成「通道 →（端子排）→ 現場」兩段接線。
  - `_check_references`：檢查引用錯誤。
  - `require_valid`。
- `cellforge/electrical/checks.py`：
  - `electrical_checks(resolved, required_modules=, costing=)`。
  - 檢查項目：
    - 缺接線（`MISSING_WIRE`）。
    - 斷路（`OPEN_CIRCUIT`），含上游電源器件失電的不動點推算。
    - 電壓域錯誤（`WRONG_VOLTAGE`）。
    - 電位網電壓不符。
    - 訊號型別不相容。
    - 重複位址（`DUPLICATE_ADDRESS`）與點位不足（`POOL_EXHAUSTED`）。
    - 模組未連到電控。
    - 供電容量：額定值不全時為 not_evaluated。
    - 安全回路：一律為 not_evaluated。
    - 採購 BOM 數量對照。
    - 盤面排版。
- `cellforge/electrical/panel.py`：`layout_panel(resolved)`，依軌道與順序排版，檢查寬度溢出與上下間距。第二段的盤面圖要直接使用這份結果。
- `cellforge/electrical/report.py`：
  - `required_modules(scene, process)`：必須接電控的模組。
  - `electrical_report(...)`：產生 `electrical.json` 的內容。
- 整合：
  - `validation.py`：引用錯誤使驗證失敗；檢查 LOGO 路徑與格式。
  - `build/pipeline.py`：產生 `electrical.json`；L1 時把檢查項目併入 `checks.json` 並重算摘要；`report["electrical"]` 摘要。
  - `version_store.py`：凍結 `electrical.yaml` 與 `drawing_templates/**`；回讀驗證 `electrical.json` 的版本號。
  - `project.py`：由範例建案時一併複製 `electrical.yaml`。
  - `CheckItem` 新增 `type: electrical`、`status`、`code` 三個欄位。
- `examples/ssd_press/handwritten/electrical.yaml`：37 個器件、I/O 18 列（DI00–DI09、DO00–DO06、頻閃觸發），另有固定相機樣板。展開後共 38 個器件、121 條接線、19 個 I/O。
  - 分析檔新增假設 A-SSD-ELEC／SUPPLY／PANEL／SAFETY／TRIGGER，以及問題 Q-SSD-E01～E06。
  - 目前結果為 0 紅、3 黃（容量未評估、兩個安全回路），BOM 數量一致。
  - 轉檔腳本是一次性工具，放在工作階段暫存區，沒有進版控。之後直接改 YAML 即可。
- `tests/test_electrical.py`：21 項測試。
  - 涵蓋：刪 24 V 供電線、斷 AC 支路導致 24 V 連帶失電、重複位址與池配置跳過手動點位、錯誤電壓域、訊號不相容、7 種引用錯誤、端點與 I/O 格式、加相機時器件／影像埠／觸發點位／BOM 同步、影像埠用盡、模組涵蓋、供電容量、盤面溢出與重疊、DI01 人工追線、建置產物。
  - 缺陷注入 10 項全部被測試抓到。

## 第二段（圖面引擎）待辦

1. 建立 `cellforge/drawings/`：
   - 先產生中介表示（IR）：線段、文字、符號、節點、端子、跨頁參照，全部以 mm 座標表示。
   - 由 IR 各自輸出 SVG 與 PDF。PDF 用 PyMuPDF，中文字型用內建 `china-t`（Droid Sans Fallback）；Windows 上另有 `NotoSansTC-VF.ttf` 可用。
   - 注意 D-011 的載入順序：pytest 已由 `tests/conftest.py` 先載入 PyMuPDF。
2. A3 橫式圖框（1191×842 pt）：
   - 周邊加區格標示：欄 1–6、列 A–D。
   - 底部標題欄欄位依序為：LOGO、DATE、DRAWING BY／CHECKED BY、DESIGNED BY／APPROVAL BY、Project、Type（頁名）、版次、頁碼。
   - 欄位值取自 `electrical.yaml` 的 `drawing`；狀態列顯示「工程規劃圖／非施工放行版」。
3. 頁面只在有內容時產生，不做充數頁。候選頁面：
   - 封面／目錄
   - 電源
   - 控制／安全（急停、門互鎖，只畫規劃回路，不宣稱安全等級）
   - I/O
   - 通訊
   - 端子接線表
   - 盤面配置：使用 `layout_panel`
   - 器件清單
4. 圖面慣例參考客戶圖（見下方「參考資料」）：
   - 上方畫 P24A／N24A 電源軌，並加跨頁箭頭。
   - 線號標記（藍）、訊號名（綠）。
   - 繼電器線圈畫成圓並加標籤，畫出 NC／C 接點。
   - 跨頁參照格式如 `To Page 400(C,2)`。
   - I/O 頁版面：左側模組框，逐列畫腳位、位址、說明、線號與去向。
5. 要能區分四種情形：連接點（實心點）、交叉不連接、端子排、跨頁參照。
6. 出圖檢查（寫進 `electrical.json` 或另一份 `drawings.json` 產物），逐頁檢查：
   - 文字都在圖框內，沒有被裁切。
   - 符號之間的包圍盒不重疊。
   - 線段端點都落在端子、節點或跨頁參照上，沒有斷線或懸空。
   - 跨頁參照的目標頁與區格確實存在，且目標上有同一個訊號。
7. 匯出與介面：
   - 匯出新增 `electrical_pdf`、`electrical_svg`，比照 `COST_KINDS`：版本有 `electrical.json` 才納入「全部」匯出。
   - API 新增兩個端點：`GET /projects/{p}/versions/{v}/electrical`（JSON），以及逐頁 SVG。
   - 圖元帶器件 id（例如 SVG 的 `data-device`），供第三段做點選定位。

## 第三段待辦

1. 前端 `web/src/components/` 新增「電控」分頁，放在 `MainWorkspace` 的分頁列：
   - 顯示 SVG 圖頁、I/O 表、器件清單與電控檢查。
   - 點圖上器件時，依 `electrical.json.modules` 的 `module_ref` 在 3D 高亮並定位模組。
   - 反向也要能用：在 3D 選模組時，列出並定位它的器件。
2. ACC-06 驗收，用隔離副本進行：
   - **加相機**：新增一個 `parts/global_camera.py` 模組實例。
     - 預期：3D 多一個節點；成本 3-01 數量加 1；電控多一個相機器件、一個 IPC1 影像埠、一個 DO 觸發點位；圖面的 I/O 頁、通訊頁與器件清單都跟著更新。
   - **改 I/O**：
     - 把 DI09 移到空點位：I/O 表、端子表與圖面同步變更。
     - 改成與 DI08 重複：出現紅色「重複 I/O 位址」。
   - **刪供電連接**：刪 PW-30（PS1 V+ → P24A）。
     - 預期：紅色「缺接線」與「斷路」；圖面上該線消失、出圖檢查仍然通過。
3. 人工追線：
   - 把代表回路寫進驗收文件，例如 DI01：PS1 V+ → P24A → B01 BN；B01 BK → XDI:02 → IO1 DI01（線號 W-DI01）；B01 BU → N24A → PS1 V-。
   - 這條回路已在 `test_hand_traced_di01_sensor_loop` 用資料驗證過；第三段要在 PDF 上逐頁對照再追一次。
4. 文件收尾：
   - 撰寫 `docs/DEV010_ACCEPTANCE.md`。
   - 補充 D-041 或新增 D-042，記錄圖面引擎的決策。
   - 更新 README。
   - 勾選開發書的 DEV-010。
5. 品質閘門：
   - 後端：pytest、ruff check、ruff format --check。
   - 前端：`npm run lint`、`npx tsc --noEmit`、`npm run build`。
   - 通過後提交。

## 參考資料（位於 repo 外，不要複製進來）

- 客戶參考圖：`G:\共用雲端硬碟\公司共用雲端資料夾\14_電控部\1.專案資料\2026年度專案\台全-壓鑄件檢測設備\04_電路圖\台全-壓鑄件檢測設備_V1.00_20260714.pdf`。
  - A3 橫式，38 頁，AutoCAD 輸出。
  - 頁碼依區段編排：P1 盤面、102 PLC、105 EMO、206 DI、505 Mini I/O。
- TestCode 電控資料：`D:\Working Space\Python\TestCode\RobotArmPressSSD\docs\electrical\`。
  - `circuit-data.json`：本案的來源資料。
  - `E01.svg`～`E13.svg`：TestCode 的舊圖，可參考頁面分法。
  - `verification.json`。

## 恢復工作時

1. 先讀這份文件、D-041，以及開發書 P3 與 DEV-010。
2. 確認基準：`.\.venv\Scripts\python -m pytest tests/test_electrical.py` 應全數通過。
3. 從「第二段待辦」第 1 項開始。
