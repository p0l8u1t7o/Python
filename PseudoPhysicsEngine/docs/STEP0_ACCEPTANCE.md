# 步驟 0 驗收紀錄

日期：2026-09-14  
案例：`examples/getac_qc/handwritten/`

## 執行結果

- `cell validate`：通過。
- `cell build --level L0`：通過，產生 55 秒五站 timeline、STEP、GLB、render brief 與 v2 最終快照。
- `cell snapshot --t 40 --cam iso`：通過，Playwright Chromium 產生 1280×720 PNG；人工檢視確認七個模組沿產線展開、碰撞幾何預設隱藏、ISO 相機涵蓋完整配置。
- Python tests：6 passed。
- Ruff：通過。
- Vite production build：通過。

## STEP / OCP XCAF 關鍵驗收

使用 CadQuery 2.6.1 / cadquery-ocp 7.8.1.1.post1。CadQuery 初次匯出的頂層 component instance 名稱為數字 label，因此 build 確實啟用了開發書第 11 節的 OCP XCAF 備案。流程如下：

1. `cq.Assembly.save(..., mode="default")` 匯出 STEP。
2. 用全新 OCP `STEPCAFControl_Reader` / XCAF document 重讀。
3. 遞迴把 component instance label 寫成對應 reference part id。
4. 用 `STEPCAFControl_Writer` 直接重寫 STEP。
5. 再建立另一份全新 XCAF document 重讀並逐層驗證；任一數量或名稱不符即讓 build 以回傳碼 3 失敗。

最終讀回結果：

- free shapes：1（根名稱 `CellForge`）
- 頂層零件：7 / 預期 7
- 全樹 component：46
- assembly nodes：8（根 assembly + 7 個模組子組件）
- leaf parts：39
- 頂層 id：`infeed_rack`, `conveyor_1`, `robot_1`, `vision_fixture`, `robot_2`, `conveyor_2`, `outfeed_rack`
- 全部 46 個 component 的 instance name 均非空且等於 reference part name
- `xcaf_fallback_used`：`true`

機器可讀完整樹在 `build/step_validation.json` 與 `.cellforge/v2/step_validation.json`。

## 資料限制

起始 repo 未含開發書第 9 節列出的真實 PDF、Check List、照片與 expected 資料。本步只建立規格明示的 handwritten 五站案例，未偽造任何檢驗規範；步驟 1、2 的真實資料驗收仍需 Kevin 的檔案。
