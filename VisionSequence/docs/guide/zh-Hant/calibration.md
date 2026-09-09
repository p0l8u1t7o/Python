# 相機標定、鏡頭校正與機械手臂座標

標定頁（`/calibration`）產生站台幾何與拼接設定。幾何儲存在一個 **標定資產**（kind `calibration` 的 JSON 檔）中：鏡頭模型負責拉直廣角或近距鏡頭造成的彎曲，像素到毫米的映射描述零件所在平面，像素到機械手臂座標的映射供取放使用，相機到相機的映射則把一台相機的影像座標轉到另一台。工具透過 `undistort`、`to_world`、`map_points`、`stitch_images`、`align_offset` 和 `calibration` 使用此資產。每個站台教導一次幾何；鏡頭或相機更換後重新教導，所有選用該資產的流程會一起更新。

## 1. 七種標定方式 {#modes}

| 模式 | 您要做什麼 | 會得到什麼 |
|---|---|---|
| Board | 拍攝 10 到 15 張棋盤或圓點板影像，讓板子分布在不同位置與傾角，包含影像邊角與中央，並輸入內角數與間距 | 鏡頭模型、每張重投影誤差，以及由您選定影像推得的平面毫米映射 |
| Points | 點選影像特徵並輸入該點的機械手臂座標，至少 4 點，工作區分散 9 點更好 | 像素到機械手臂座標的仿射或透視映射，含每點殘差 |
| Distance | 點選兩點並輸入實際距離 | 單純比例尺，足以支援只需毫米的量測流程 |
| Hand-eye | 依精靈移動機械手臂、輸入回報座標、拍照並定位特徵，至少三處；可另加旋轉階段 | 像素到機械手臂仿射映射、座標手性與角度正負慣例；旋轉階段會加入旋轉中心 |
| Camera mapping | 並排載入或擷取兩台相機畫面，標記 A/B 對應點；也可送入兩組同一標定板角點 | A 到 B 的仿射或透視映射，含每一對點殘差 |
| Stereo | 選左右來源，擷取至少五組成對標定板，求解雙相機內參與固定 stereo transform，或匯入舊 `stereo_config.json`；再量測一次皮帶 ROI 作為高度參考 | `stereo` 標定區塊，含 `M1`、`D1`、`M2`、`D2`、`R`、`T`、`baseline_mm`、殘差與選用 `z_ref` |
| Multi-camera stitching | 選 2 到 4 個來源，各擷取一張，選 grid 或 homography 拼接，必要時選各來源標定並預覽合成影像 | 一個一般檢測流程，含每台相機一個 `image_source` 與一個 `stitch_images` 節點；參數存在流程圖中 |

**Solve** 只顯示結果，不會儲存：殘差、品質標章、覆蓋率與警告都會列出。請只在滿意後儲存。少於所需點對時求解器會回 422，而不是靜默產生很差的擬合。

## 2. 產生可列印標定板 {#board-generator}

Board 模式包含 **Generate calibration board** 面板。選 `chessboard` 或 `acircles`，輸入列、欄、毫米間距與 DPI 後即可預覽或下載 PNG。產生幾何以像素精確定義：一步等於 `spacing_mm / 25.4 * dpi`，例如 300 DPI 下 20 mm 會是 236.22 px。

PNG 會在紙上印出圖樣、列欄數、間距、DPI 與已知長度比例尺。請以 **100% / actual size** 列印，使用前量測比例尺；若比例尺錯誤，標定會忠實學到印表機縮放誤差。整合端可用 `GET /vision/calibration/board.png` 加 `pattern`、`rows`、`cols`、`spacing`、`dpi` 查詢取得同檔案；無效尺寸或 DPI 回 422。

## 3. 覆蓋率與重要警告 {#coverage}

鏡頭畸變在角落最大，因此只在畫面中央拍板的標定會在中央準確、在真正重要的邊角失準。收集 board 影像時，頁面維持 **coverage map**：影像被分為 4x3 格，尚未收到角點的格子以紅色虛線框標出，並顯示十二個區域已覆蓋幾個、邊緣區域還空幾個。請把板子推到空區域直到地圖清除。

- **Reprojection error above 0.5 px**：鏡頭模型解釋影像不佳，常見原因為模糊、照明不均、板子不平或傾斜不足。
- **Fewer than 8 pictures**：模型不穩；10 到 15 張是常規。
- **Coverage below three quarters, or empty edge areas**：請補拍邊角。
- **Point residual above two pixels**：座標輸入錯、點到錯誤特徵，或相機角度需要透視而非仿射映射。

API 也回傳同資訊：`POST /vision/calibration/solve` 在 payload 旁帶 `coverage` 與 `warnings[]`；`POST /vision/calibration/coverage` 以影像尺寸與目前角點集回傳格線、空格與現成疊圖。

## 4. Hand-eye 標定 {#hand-eye}

精靈把 **平移** 與 **旋轉** 分開。先收集三個以上非共線的像素/機械手臂點對。若選 `translation_rotation`，再保持機械手臂 X/Y 不動，只旋轉工具並於三個以上角度記錄同一特徵；平移樣本無法替代此旋轉弧。

擬合會求得像素到機械手臂仿射映射 `robot.matrix`。其 2x2 線性區塊行列式給出 `handedness`：正為 `right`，負為 `left`（鏡射）。預設 `angle_sign` 依手性為 +1 或 -1；若控制器角度慣例不同，請儲存前覆寫。旋轉階段會以擬合圓得到像素旋轉中心，再由矩陣轉成機械手臂單位。`camera_mode` 記錄相機為 `fixed` 或 `moving`；矩陣一律由實際點對求得。

機械手臂座標也可由連線提供。在 **Integration -> TCP -> Receive rules** 加入 action 為 `calibration_signal` 的 regex 規則：`^Start$` 清空佇列並開始新輪，`^Calibration\((?P<x>[^,]+),(?P<y>[^,]+),(?P<r>[^)]+)\)$` 記錄下一筆 X/Y/R，`^End$` 標記完成，`^Teach\((?P<x>[^,]+),(?P<y>[^,]+),(?P<r>[^)]+)\)$` 顯示控制器目前教導點。精靈選 **Connection** 後會輪詢 `GET /vision/calibration/robot/signals?since=<seq>`，`DELETE /vision/calibration/robot/signals` 可清除本地佇列。

**只用最小平方，不用 RANSAC。** 操作員輸入的每個點都留在擬合中並得到殘差：`points[].error` 為機械手臂單位，`rotation_points[].error` 為到擬合圓的像素殘差。殘差最大的平移點以紅色顯示。刪除任一點後再求解會重新計算；原因很簡單，靜默丟棄點會掩蓋輸入錯誤。

`POST /vision/calibration/solve` 可送 `mode: "robot"`、`image_size: [w,h]`、`unit: "mm"`、`kind: "translation"` 或 `"translation_rotation"`、`camera_mode`、`points` 與選用 `rotation_points`、`angle_sign`。回覆的 `payload.robot` 只計算不儲存；若要保存，將完整 `payload` 與 `name` 送到 `POST /vision/calibration/assets`。

## 5. 相機到相機映射 {#camera-mapping}

相機映射是純 2D 幾何：點對為 `A pixel -> B pixel`。`kind="affine"` 至少三對，以最小平方解六個仿射係數；`kind="perspective"` 至少四對，以正規化 DLT 最小平方解 homography。沒有 RANSAC 或隱藏剔除，每一對都留在 `mapping.points[]` 並附像素殘差，最大殘差會在表格與疊圖標紅。API 也接受 board 資料，將兩側 pixel-to-board homography 組合成 A 到 B 的映射。

## 6. Stereo 標定與高度參考 {#stereo}

Stereo 模式把實體雙相機對存在同一標定資產中。`mode: "stereo"` 接受同一板姿態的左右視圖，先分別做一般相機標定，再以固定內參執行 stereoCalibrate。每一對影像都保留在最小平方擬合並取得殘差；壞樣本請刪除後重算。

`POST /vision/calibration/stereo/import` 接受舊 `stereo_config.json` 欄位 `M1`、`D1`、`M2`、`D2`、`R`、`T`、`width`、`height`。平台會忽略既有 rectification matrix，改以 `stereoRectify(alpha=0)` 重算。`POST /vision/calibration/stereo/reference` 量測皮帶 ROI，儲存 `z_ref.d0_mm`、`Z0_mm` 與選用 `scale`，不改原標定欄位。

## 7. 多相機拼接設定 {#stitching}

拼接模式是流程產生器，不是標定求解器。來源選擇寫入產生的 `image_source` 節點，幾何寫入 `stitch_images` 參數。讓設定維持一般流程，表示版本歷史、預覽、批次測試與下游量測都走同一執行路徑；標定資產則保持為可重用站台幾何。

相機為固定 rows x columns 陣列且無透視差異時使用 `grid`。工具不會拉伸 cell；裁掉各邊相同像素後，每個輸入必須尺寸相同，不符時會指出影像。各相機有 `world.matrix` 或相機 2 到 4 有到影像 1 的 `mapping.matrix` 時使用 `homography`。輸出包含拼接影像、影像數、寬高、grid offset、`origin` 與 `scale`。

## 8. 工具 {#tools}

### undistort (pre-processing) {#undistort}

使用標定中的鏡頭部分拉直影像。`alpha` 決定保留多少畫面：0 會縮放到每個像素都是真實影像，1 保留全畫面但有黑角，中間值保留對應比例。remap table 依標定、影像尺寸與 alpha 快取。執行解析度不同時會縮放 camera matrix；長寬比不同則拒絕並列出兩個尺寸，常見於相機更換。

### stitch_images (pre-processing) {#stitch-images}

在定位與量測前合併 2 到 4 台相機影像。即時流程應連接 `image_1` 到 `image_4`；固定影像只作示範與基準測試後備。`blend=uncover` 最快，後影像覆蓋前影像；`mean`、`min`、`max` 明確定義重疊像素。

### stereo_depth (measurement) {#stereo-depth}

`stereo_grab` 也有選用 `image` / `image_right` 輸入。當左影像已接入時，工具不開啟來源；右影像缺失時以左影像代替並警告，使流程仍能跑完但 `z` 為空。工具對整對影像校正一次，只在物件 ROI 內計算 SGBM，並在 segmentation polygon 中有效 disparity 像素上平均或取中位數。會寫入 `distance_mm`、`disparity`、`valid_ratio`、`compensated` 與 `z`。

### to_world (measurement) — 真實世界與機械手臂座標 {#to-world}

把像素位置轉成標定的世界座標：將定位工具中心接到 `x`/`y`（或傳 `points` list），即可取得毫米或機械手臂單位。像素長度變成實際長度，影像角度變成世界角度，並依該位置的映射換算。鏡射映射會正確翻轉角度。選用 `frame` 輸入可先套用局部座標原點、角度與比例。`mode=to_pixel` 會反向把世界或 frame 座標轉回像素。

可選標定資產也讓 `distance`、`caliper`、`find_circle`、`fit_arc`、`find_rectangle`、`find_parallel_lines`、`find_line` 與 `geometry` 直接輸出物理值，新增 `<original key>_world` 與 `unit`，優先使用 robot mapping。`coordinate` 以 `point_angle`、`two_points` 或 `line` 定義局部座標框，輸出 `frame`、`origin_x`、`origin_y`、`angle`。

### map_points (locate) {#map-points}

使用含 `mapping` 的標定資產，在兩個相機座標系間映射點。接受 `points`、`matches` 或單一 `x`/`y`。`direction=forward` 使用儲存矩陣，`direction=inverse` 使用其反矩陣。資產沒有 `mapping` 時會明確丟出 `ToolError`。

### calibration (measurement) {#calibration-tool}

只做長度換算：像素尺寸、已知距離或資產。建議用 asset mode，讓站台重新教導後所有流程同步更新。

### align_offset (locate) {#align-offset}

使用同一標定資產把補償後的絕對姿態轉成 robot 或 world 座標。兩者都存在時優先 robot。資產另有 `mapping` 時，工具會加入 `mapped_x`、`mapped_y`、`mapped_angle`；沒有 `mapping` 時輸出維持既有行為。四種模式、輸入連接埠與位置校正輸出見 [檢測能力](vision-capabilities.md#tools)。

## 9. 資產內容 {#asset}

```json
{
  "unit": "mm",
  "image_size": [1280, 960],
  "lens": {"camera_matrix": [[0,0,0],[0,0,0],[0,0,1]], "dist_coeffs": [], "rms": 0.21},
  "world": {"kind": "affine", "matrix": [[0,0,0],[0,0,0],[0,0,1]], "mm_per_px": 0.0512},
  "robot": {"kind": "translation_rotation", "camera_mode": "fixed", "matrix": [[0.1,0,0],[0,0.1,0],[0,0,1]], "handedness": "right", "angle_sign": 1},
  "mapping": {"from_source": "top", "to_source": "side", "kind": "perspective", "matrix": [[0,0,0],[0,0,0],[0,0,1]]},
  "stereo": {"left_source": "left", "right_source": "right", "baseline_mm": 60}
}
```

`lens`、`world`、`robot`、`mapping` 與 `stereo` 都是選用區塊，但至少要有一個。robot 區塊保存：

| 欄位 | 意義 |
|---|---|
| `kind`, `camera_mode` | `translation` 或 `translation_rotation`；相機 `fixed` 或 `moving` |
| `matrix`, `handedness`, `angle_sign` | 3x3 像素到機械手臂仿射矩陣、由行列式得到的 `right`/`left`，以及儲存的角度慣例 |
| `rms`, `max_error`, `points[]` | RMS 與最大殘差；每個輸入點及其 `error` |
| `rotation_center_px`, `rotation_center_world` | 旋轉階段加入的像素與機械手臂單位中心 |
| `rotation_points[]`, `rotation_rms_px`, `rotation_max_error_px` | 各旋轉樣本與徑向殘差 |

`mapping` 區塊保存來源標籤、`affine` 或 `perspective`、3x3 matrix、每組 A/B 點與像素殘差。`stereo` 區塊保存兩側 camera matrix、distortion vector、左到右 `R`/`T`、影像尺寸、正的 `baseline_mm`、求解 RMS、board metadata、各對殘差與選用 `z_ref`。機械手臂高度為 `Z0_mm + (d0_mm - distance_mm) * scale`。

`GET /vision/calibration/assets/{id}` 回傳內容、摘要與品質。robot 摘要包含種類、點數、RMS、最大殘差、手性與是否有旋轉中心。`manage.py` 沒有標定命令，因為影像是由頁面透過相機取得。

## 10. 準確度檢查 {#accuracy}

- 已知畸變合成影像：求解器可在測試中回復 k1 與焦距。
- `to_world` 影像 -> world -> 影像 round trip 在 1e-6 內，包含鏡射映射。
- `undistort` 1280x960：第一張建立 map，後續為單純 remap。
- `solve_mapping` 逐元素回復合成仿射矩陣，保留 outlier 於殘差表，並驗證透視與 board-derived camera mapping。
- `stereo_depth` 合成測試檢查物頂距離、有效 disparity、`z_ref` 公式與軟體觸發時間補償。

不在範圍內：完整 3D hand-eye 姿態。Hand-eye 標定記錄固定或移動相機，並由輸入點對擬合 2D 映射，不求解手臂上相機的 3D 姿態。
