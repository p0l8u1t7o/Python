# 檢測流程設計原則

## 謹慎原則（先確認再生成）

- 目標不明（提示詞只有「看一下」「檢查」）、量測沒有位置（找圓沒圈孔、卡尺沒圈邊）、夾角只有一條邊、
  缺陷檢測不知道有沒有良品、要換算 mm 卻沒有像素尺寸——這些情況先提問，不要猜。
- 一次最多 3 個問題，問最關鍵的；可以合理預設的（公差 ±2%、極性由影像特徵判斷）就不問，但在 rationale 註明用了什麼預設值。
- 使用者已回答或提示詞已說明的事不要再問；回答會以補充句併在需求後面。
- 生成後仍有不確定的地方，用 note 節點寫給使用者看，並在 rationale 條列「假設」。

## 標準骨架

```
取像 → 前處理 → （定位補正）→ 檢測／量測 → 判定 → 輸出
```

- **前處理**：`grayscale` 幾乎必做；雜訊多先 `blur`（median 對椒鹽雜訊最好）；對比差用 `lut`（gamma／CLAHE）；二值化用 `threshold`（不確定門檻用 `otsu`），二值化後 `morphology`（open 去雜點、close 補洞）。
- **定位補正**：工件位置會變就用「範本比對 → 定位補正 → ROI 跟隨」三件套；只是小位移且特徵單一，用 `find_circle`／`find_line` 直接在大一點的 ROI 裡找也行。
- **判定**：數值走 `if_number`／`in_range`／`tolerance_judge`，多個條件用 `bool_logic(and)` 彙總後 `judge(by_input)`；不良分支各接 `judge(ng, label=原因)`，讓上位機看得出是哪種 NG。

## 依需求選工具

| 需求 | 首選 | 備選／搭配 |
|---|---|---|
| 數幾個 | `threshold` → `morphology` → `blob` → `if_number(eq N)` | 圓形零件多時 `hough_circles.count` |
| 有沒有（無色） | `blob(min_count=1)` 的 found/not_found | `template_match` 找特徵、`intensity` 亮度差 |
| 有沒有（有色） | `color_range` → `pixel_count` | `color_check` 比平均色 |
| 顏色對不對 | `color_check(color=目標色)` | `color_stats` 輸出色碼給上位機 |
| 圓的直徑／圓心 | `find_circle`（annulus ROI）→ `formula(a*2)` | 多圓 `hough_circles`；圓度 `fit_ellipse.roundness`；只有一段弧 `fit_arc` |
| 寬度／間距 | `caliper`（ROI 橫跨兩條邊） | 多點壁厚 `wall_thickness`（line ROI 橫切壁） |
| 角度 | `find_line`×2 → `angle` | 斜切角 `chamfer_angle`；交點 `geometry(intersect)` |
| 距離 | 兩個找圓／找線 → `distance` | 點到線 `geometry(point_line)` |
| 定位（任意角度／光照變化／遮擋／多件） | `shape_match(model=形狀資產)` → `shape_align` → `fixture_roi` | 光照穩定、正放的件 `template_match` 也可 |
| 換算 mm | `calibration(pixel_size_mm)` 在數值進 `tolerance_judge` 之前 | |
| 表面缺陷（只有良品、缺陷型態不固定） | `dl_anomaly(model=異常模型)` → `if_number(count eq 0)` | 教導頁「Anomaly detection」20～50 張良品即可；門檻先用自動值 |
| 表面缺陷（有良品） | 良品 ≥ 10 張：`defect_stat(model=統計範本資產, sigma=4)`；只有 1 張：`defect_diff(template=良品資產)` | 統計範本用 POST /vision/assets/stat-template 建（可直接吃批次影像集） |
| 表面缺陷（規律紋理） | `fft_filter(lowpass)` → `threshold` → `blob` | |
| 表面缺陷（均勻表面） | `blur` → `threshold(fixed, 平均±3σ)` → `morphology` → `blob(count==0)` | `edge_density` 守門 |
| 讀字（日期碼／批號／料號） | `ocr_read(charset=digits 或 upper)` → `ocv_verify(expected="LOT######")` | 噴印／打標字體先教字型再選 `model`；多行 `mode=detect` |
| 讀碼 | `barcode` | 斜貼先 `warp_perspective` 拉正；文字有無 `text_presence` |
| 亮度／曝光守門 | `intensity.mean` → `in_range` | `histogram.otsu` |
| 角落偏暗／打光不均 | `shading_correct(flat_field, flat=白板資產)` 放在 threshold 前 | 沒有白板 `estimate`；只是曝光整體偏 `lut` |
| 量測區要挖掉孔／字樣／反光 | `region_from_shape`×N → `region_combine(subtract)` → 接量測工具的 `roi` 埠 | `union` 合併幾塊、`intersect` 取重疊 |
| 圓形工件的崩邊／缺口／毛刺／徑向跳動 | `circular_caliper`（annulus ROI）→ `profile_defect(fit_circle)` → `if_number(count eq 0)` | 跳動量 `circular_caliper.runout` 接 tolerance_judge；不規則外形用 contour_geometry 的凸缺陷 |
| 缺角／崩邊／外形是否對 | `contour_find` → `contour_filter(max_count=1)` → `contour_geometry(defect_depth)` → `if_number(first_defects eq 0)` | 外形換料 `contour_match(template)`；面積與計數用 `blob` 即可 |
| 圖面上的形位公差（直線度／真圓度／平行度／垂直度） | 取點（`find_line.points`／`circular_caliper.points`／`contour_filter.contours`）或兩條 `find_line.line` → `gdt_measure(mode, tolerance)` → pass／fail | mm 要接 `scale`（undistort 的 mm_per_pixel）；真圓度是 MZC，detail.lsc 給最小二乘對照 |
| 刻印字／浮凸／凹坑／拋光面刮痕（單張看不見） | 四方向打光各一張 → `photometric_stereo(output=curvature_abs)` → `threshold`／`blob` 或 `ocr_read` | 來源端不能連拍時用 `crop` 拆 2×2 拼圖；`albedo` 輸出給印刷／髒污 |
| 圓周上的齒／缺口／螺紋 | `polar_unwrap`（annulus ROI）→ `threshold` → `blob` → `if_number(eq N)` | 位置標回原圖 `polar_restore(mapping)`；沿圓周量寬度用展開圖上的 `caliper`／`line_profile` |

## 自動調參要領

- 二值化極性：目標比背景暗 → `invert=true`（或 blob `polarity="dark"`）。
- `blob.min_area`：目標粒子面積的 1/3 左右；`max_area` 擋整片背景。
- 找圓／找線 `edge_threshold`：對比高（>100 灰階差）用 20～40；對比低用 8～15；`polarity` 依「由 ROI 內→外」遇到的灰階變化選。
- 公差：使用者給標稱值沒給公差時，量測類預設 ±2%（直徑）或 ±5%（寬度），角度 ±1°。
- 顏色範圍：H 取主色 ±12°、S 與 V 下限取主色的 40%（光源變動大時再放寬）。
- 缺陷門檻：ROI 平均灰階往缺陷極性偏 max(30, 3σ)；最小面積擋雜訊（≥ 200 px²）。

## 多張影像／好品壞品

- 使用者說「ROI01 是好品、ROI02 是壞品」：好品 ROI 裁成範本資產 → `defect_diff(template=資產id, roi=壞品位置且與範本同尺寸)`；主影像用壞品那張試跑，應得到 NG。
- 多張影像的流程要對每張都合理（同一套參數）；差異大時用定位補正，不要為每張各寫一套。

## 常見錯誤

- 忘了 `grayscale` 就接 `threshold`（彩色進二值化會走 BGR 平均，結果不穩）。
- 把 `not_found` 接到 `_flow` 以外的埠。
- `judge` 只接一邊分支，另一邊沒收尾。
- ROI 用了工具不支援的形狀。
- 數值埠接錯型別（list 接到 number）。
