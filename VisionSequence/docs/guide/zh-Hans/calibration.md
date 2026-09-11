# 相机标定、鏡頭校正与機械手臂座標

标定页（`/calibration`）產生站台幾何与拼接设置。幾何保存在一個 **标定资产**（kind `calibration` 的 JSON 檔）中：鏡頭模型负责拉直廣角或近距鏡頭造成的彎曲，像素到毫米的映射描述零件所在平面，像素到機械手臂座標的映射供取放使用，相机到相机的映射則把一台相机的图像座標转到另一台。工具透過 `undistort`、`to_world`、`map_points`、`stitch_images`、`align_offset` 和 `calibration` 使用此资产。每個站台教导一次幾何；鏡頭或相机更換后重新教导，所有選用該资产的流程會一起更新。

## 1. 七種标定方式 {#modes}

| 模式 | 您要做什麼 | 會得到什麼 |
|---|---|---|
| Board | 拍攝 10 到 15 張棋盤或圆点板图像，讓板子分布在不同位置与傾角，包含图像边角与中央，並输入內角數与間距 | 鏡頭模型、每張重投影誤差，以及由您選定图像推得的平面毫米映射 |
| Points | 点击图像特徵並输入該点的機械手臂座標，至少 4 点，工作區分散 9 点更好 | 像素到機械手臂座標的仿射或透視映射，含每点殘差 |
| Distance | 点击兩点並输入实际距離 | 單純比例尺，足以支持只需毫米的量測流程 |
| Hand-eye | 依精靈移動機械手臂、输入回報座標、拍照並定位特徵，至少三處；可另加旋转階段 | 像素到機械手臂仿射映射、座標手性与角度正負慣例；旋转階段會加入旋转中心 |
| Camera mapping | 並排載入或擷取兩台相机畫面，標記 A/B 对应点；也可送入兩組同一标定板角点 | A 到 B 的仿射或透視映射，含每一對点殘差 |
| Stereo | 選左右来源，擷取至少五組成對标定板，求解双相机內參与固定 stereo transform，或导入舊 `stereo_config.json`；再量測一次皮帶 ROI 作為高度參考 | `stereo` 标定區塊，含 `M1`、`D1`、`M2`、`D2`、`R`、`T`、`baseline_mm`、殘差与選用 `z_ref` |
| Multi-camera stitching | 選 2 到 4 個来源，各擷取一張，選 grid 或 homography 拼接，必要時選各来源标定並預覽合成图像 | 一個一般检测流程，含每台相机一個 `image_source` 与一個 `stitch_images` 節点；参数存在流程圖中 |

**Solve** 只显示結果，不會保存：殘差、品質標章、覆蓋率与警告都會列出。請只在滿意后保存。少於所需点對時求解器會回 422，而不是靜默產生很差的擬合。

## 2. 產生可列印标定板 {#board-generator}

Board 模式包含 **Generate calibration board** 面板。選 `chessboard` 或 `acircles`，输入列、欄、毫米間距与 DPI 后即可預覽或下載 PNG。產生幾何以像素精確定义：一步等於 `spacing_mm / 25.4 * dpi`，例如 300 DPI 下 20 mm 會是 236.22 px。

PNG 會在紙上印出圖樣、列欄數、間距、DPI 与已知長度比例尺。請以 **100% / actual size** 列印，使用前量測比例尺；若比例尺错误，标定會忠實學到印表機縮放誤差。整合端可用 `GET /vision/calibration/board.png` 加 `pattern`、`rows`、`cols`、`spacing`、`dpi` 查詢取得同檔案；無效尺寸或 DPI 回 422。

## 3. 覆蓋率与重要警告 {#coverage}

鏡頭畸變在角落最大，因此只在畫面中央拍板的标定會在中央準確、在真正重要的边角失準。收集 board 图像時，页面維持 **coverage map**：图像被分為 4x3 格，尚未收到角点的格子以紅色虛线框標出，並显示十二個区域已覆蓋幾個、边緣区域還空幾個。請把板子推到空区域直到地圖清除。

- **Reprojection error above 0.5 px**：鏡頭模型解釋图像不佳，常見原因為模糊、照明不均、板子不平或傾斜不足。
- **Fewer than 8 pictures**：模型不穩；10 到 15 張是常規。
- **Coverage below three quarters, or empty edge areas**：請補拍边角。
- **Point residual above two pixels**：座標输入錯、点到错误特徵，或相机角度需要透視而非仿射映射。

API 也回傳同資訊：`POST /vision/calibration/solve` 在 payload 旁帶 `coverage` 与 `warnings[]`；`POST /vision/calibration/coverage` 以图像尺寸与目前角点集回傳格线、空格与現成疊圖。

## 4. Hand-eye 标定 {#hand-eye}

精靈把 **平移** 与 **旋转** 分開。先收集三個以上非共线的像素/機械手臂点對。若選 `translation_rotation`，再保持機械手臂 X/Y 不動，只旋转工具並於三個以上角度记录同一特徵；平移样本无法替代此旋转弧。

擬合會求得像素到機械手臂仿射映射 `robot.matrix`。其 2x2 线性區塊行列式給出 `handedness`：正為 `right`，負為 `left`（鏡射）。默认 `angle_sign` 依手性為 +1 或 -1；若控制器角度慣例不同，請保存前覆寫。旋转階段會以擬合圆得到像素旋转中心，再由矩陣转成機械手臂單位。`camera_mode` 记录相机為 `fixed` 或 `moving`；矩陣一律由实际点對求得。

機械手臂座標也可由連线提供。在 **Integration -> TCP -> Receive rules** 加入 action 為 `calibration_signal` 的 regex 規則：`^Start$` 清空队列並開始新輪，`^Calibration\((?P<x>[^,]+),(?P<y>[^,]+),(?P<r>[^)]+)\)$` 记录下一筆 X/Y/R，`^End$` 標記完成，`^Teach\((?P<x>[^,]+),(?P<y>[^,]+),(?P<r>[^)]+)\)$` 显示控制器目前教导点。精靈選 **Connection** 后會輪詢 `GET /vision/calibration/robot/signals?since=<seq>`，`DELETE /vision/calibration/robot/signals` 可清除本地队列。

**只用最小平方，不用 RANSAC。** 操作員输入的每個点都留在擬合中並得到殘差：`points[].error` 為機械手臂單位，`rotation_points[].error` 為到擬合圆的像素殘差。殘差最大的平移点以紅色显示。删除任一点后再求解會重新計算；原因很簡單，靜默丟棄点會掩蓋输入错误。

`POST /vision/calibration/solve` 可送 `mode: "robot"`、`image_size: [w,h]`、`unit: "mm"`、`kind: "translation"` 或 `"translation_rotation"`、`camera_mode`、`points` 与選用 `rotation_points`、`angle_sign`。回覆的 `payload.robot` 只計算不保存；若要保存，將完整 `payload` 与 `name` 送到 `POST /vision/calibration/assets`。

## 5. 相机到相机映射 {#camera-mapping}

相机映射是純 2D 幾何：点對為 `A pixel -> B pixel`。`kind="affine"` 至少三對，以最小平方解六個仿射係數；`kind="perspective"` 至少四對，以正規化 DLT 最小平方解 homography。沒有 RANSAC 或隱藏剔除，每一對都留在 `mapping.points[]` 並附像素殘差，最大殘差會在表格与疊圖標紅。API 也接受 board 数据，將兩側 pixel-to-board homography 組合成 A 到 B 的映射。

## 6. Stereo 标定与高度參考 {#stereo}

Stereo 模式把实体双相机對存在同一标定资产中。`mode: "stereo"` 接受同一板姿態的左右視圖，先分別做一般相机标定，再以固定內參执行 stereoCalibrate。每一對图像都保留在最小平方擬合並取得殘差；壞样本請删除后重算。

`POST /vision/calibration/stereo/import` 接受舊 `stereo_config.json` 欄位 `M1`、`D1`、`M2`、`D2`、`R`、`T`、`width`、`height`。平台會忽略既有 rectification matrix，改以 `stereoRectify(alpha=0)` 重算。`POST /vision/calibration/stereo/reference` 量測皮帶 ROI，保存 `z_ref.d0_mm`、`Z0_mm` 与選用 `scale`，不改原标定欄位。

## 7. 多相机拼接设置 {#stitching}

拼接模式是流程產生器，不是标定求解器。来源選擇寫入產生的 `image_source` 節点，幾何寫入 `stitch_images` 参数。讓设置維持一般流程，表示版本历史、預覽、批量测试与下游量測都走同一执行路徑；标定资产則保持為可重用站台幾何。

相机為固定 rows x columns 陣列且無透視差異時使用 `grid`。工具不會拉伸 cell；裁掉各边相同像素后，每個输入必須尺寸相同，不符時會指出图像。各相机有 `world.matrix` 或相机 2 到 4 有到图像 1 的 `mapping.matrix` 時使用 `homography`。输出包含拼接图像、图像數、寬高、grid offset、`origin` 与 `scale`。

## 8. 工具 {#tools}

### undistort (pre-processing) {#undistort}

使用标定中的鏡頭部分拉直图像。`alpha` 決定保留多少畫面：0 會縮放到每個像素都是真實图像，1 保留全畫面但有黑角，中間值保留对应比例。remap table 依标定、图像尺寸与 alpha 快取。执行解析度不同時會縮放 camera matrix；長寬比不同則拒絕並列出兩個尺寸，常見於相机更換。

### stitch_images (pre-processing) {#stitch-images}

在定位与量測前合併 2 到 4 台相机图像。即時流程應连接 `image_1` 到 `image_4`；固定图像只作示範与基準测试后備。`blend=uncover` 最快，后图像覆蓋前图像；`mean`、`min`、`max` 明確定义重疊像素。

### stereo_depth (measurement) {#stereo-depth}

`stereo_grab` 也有選用 `image` / `image_right` 输入。當左图像已接入時，工具不开启来源；右图像缺失時以左图像代替並警告，使流程仍能跑完但 `z` 為空。工具對整對图像校正一次，只在物件 ROI 內計算 SGBM，並在 segmentation polygon 中有效 disparity 像素上平均或取中位數。會寫入 `distance_mm`、`disparity`、`valid_ratio`、`compensated` 与 `z`。

### to_world (measurement) — 真實世界与機械手臂座標 {#to-world}

把像素位置转成标定的世界座標：將定位工具中心接到 `x`/`y`（或傳 `points` list），即可取得毫米或機械手臂單位。像素長度變成实际長度，图像角度變成世界角度，並依該位置的映射換算。鏡射映射會正確翻转角度。選用 `frame` 输入可先套用局部座標原点、角度与比例。`mode=to_pixel` 會反向把世界或 frame 座標转回像素。

可選标定资产也讓 `distance`、`caliper`、`find_circle`、`fit_arc`、`find_rectangle`、`find_parallel_lines`、`find_line` 与 `geometry` 直接输出物理值，新增 `<original key>_world` 与 `unit`，優先使用 robot mapping。`coordinate` 以 `point_angle`、`two_points` 或 `line` 定义局部座標框，输出 `frame`、`origin_x`、`origin_y`、`angle`。

### map_points (locate) {#map-points}

使用含 `mapping` 的标定资产，在兩個相机座標系間映射点。接受 `points`、`matches` 或單一 `x`/`y`。`direction=forward` 使用保存矩陣，`direction=inverse` 使用其反矩陣。资产沒有 `mapping` 時會明確丟出 `ToolError`。

### calibration (measurement) {#calibration-tool}

只做長度換算：像素尺寸、已知距離或资产。建议用 asset mode，讓站台重新教导后所有流程同步更新。

### align_offset (locate) {#align-offset}

使用同一标定资产把补偿后的絕對姿態转成 robot 或 world 座標。兩者都存在時優先 robot。资产另有 `mapping` 時，工具會加入 `mapped_x`、`mapped_y`、`mapped_angle`；沒有 `mapping` 時输出維持既有行為。四種模式、输入连接埠与位置校正输出見 [检测能力](vision-capabilities.md#tools)。

## 9. 资产內容 {#asset}

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

`lens`、`world`、`robot`、`mapping` 与 `stereo` 都是選用區塊，但至少要有一個。robot 區塊保存：

| 欄位 | 意義 |
|---|---|
| `kind`, `camera_mode` | `translation` 或 `translation_rotation`；相机 `fixed` 或 `moving` |
| `matrix`, `handedness`, `angle_sign` | 3x3 像素到機械手臂仿射矩陣、由行列式得到的 `right`/`left`，以及保存的角度慣例 |
| `rms`, `max_error`, `points[]` | RMS 与最大殘差；每個输入点及其 `error` |
| `rotation_center_px`, `rotation_center_world` | 旋转階段加入的像素与機械手臂單位中心 |
| `rotation_points[]`, `rotation_rms_px`, `rotation_max_error_px` | 各旋转样本与徑向殘差 |

`mapping` 區塊保存来源標籤、`affine` 或 `perspective`、3x3 matrix、每組 A/B 点与像素殘差。`stereo` 區塊保存兩側 camera matrix、distortion vector、左到右 `R`/`T`、图像尺寸、正的 `baseline_mm`、求解 RMS、board metadata、各對殘差与選用 `z_ref`。機械手臂高度為 `Z0_mm + (d0_mm - distance_mm) * scale`。

`GET /vision/calibration/assets/{id}` 回傳內容、摘要与品質。robot 摘要包含種类、点數、RMS、最大殘差、手性与是否有旋转中心。`manage.py` 沒有标定命令，因為图像是由页面透過相机取得。

## 10. 準確度檢查 {#accuracy}

- 已知畸變合成图像：求解器可在测试中回復 k1 与焦距。
- `to_world` 图像 -> world -> 图像 round trip 在 1e-6 內，包含鏡射映射。
- `undistort` 1280x960：第一張建立 map，后續為單純 remap。
- `solve_mapping` 逐元素回復合成仿射矩陣，保留 outlier 於殘差表，並驗證透視与 board-derived camera mapping。
- `stereo_depth` 合成测试檢查物頂距離、有效 disparity、`z_ref` 公式与软件觸發時間补偿。

不在範圍內：完整 3D hand-eye 姿態。Hand-eye 标定记录固定或移動相机，並由输入点對擬合 2D 映射，不求解手臂上相机的 3D 姿態。
