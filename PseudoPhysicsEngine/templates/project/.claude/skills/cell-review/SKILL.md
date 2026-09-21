---
name: cell-review
description: 審查 CellForge L1 幾何、動畫、檢查、截圖、模組品質與變更請求的工程因果正確性。
---

# CellForge 工程審查

一起讀取 `build/checks.json`、`build/timeline.json`、`process.yaml` 與站別截圖；不可只接受
彙總數量。

- `interference`：檢查 `objects`、`t`、有號 `min_dist_mm`、`source` 與截圖。工具帶動蓋板
  的接觸可以是綠色；支撐接觸容許 1 mm，較深穿透仍是紅色。確認警告不是預期安裝或
  相鄰連桿。
- `reachability`：讀取 `ik_failures`，檢查位置／姿態誤差與 warm-start 關節連續性。
- `joint_limit`：把回報取樣與鏈的限位比較；黃色門檻來自設定，不是通用角度。
- `hardware`：檢查夾持時 payload、模組 stroke 與可微分的 speed。
- `takt`：回報有效工時、站別占用與瓶頸；不得只為改變嚴重度而竄改時間或平行工件。

逐一跳到每個紅／黃時間。確認機器人連桿相接且姿態正確、蓋板繞鉸鏈轉動、工件跟隨
支撐／工具並在預定站別翻面、靜態設備不跳動；檢查 ISO、俯視與相關站別相機。

## 模組層級目視清單

- 裝得上嗎：底板、孔位、T 槽或法蘭是否可辨識，mount frame 是否真的在介面上？
- 有支撐嗎：落地件是否接觸 z=0；懸掛件是否有可信的支架與 `mount` 宣告？
- 比例對嗎：桿件、板厚、馬達、把手與工作物相對尺寸是否符合機器型式？
- 行程合理嗎：在預覽中走完整個 axis range，確認不脫離導引、不撞固定件且旋轉中心正確。
- 相鄰介面對得上嗎：把配對 frames 轉到世界座標，比對位置、法向、間隙與產品通道。

處理 CR 時記錄原檢查與 process 欄位，套用最小的 frame-based 變更，validate 並重建
L1，再比較版本。後退動作應改目標 offset Z，因為 frame Z 是接近／向外法向。重新檢查
所有紅／黃項目，不只目標配對，並完整填寫代理解讀、影響、差異、結果、狀態。
