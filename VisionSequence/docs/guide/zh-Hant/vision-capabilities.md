# 檢測能力：ROI、影像格式與工具

此頁以主流機器視覺套裝軟體作為對照，說明平台提供哪些 ROI 形狀、如何實作多種位元深度，以及各類檢測需求在此平台中對應到哪些工具。也列出近期新增的能力，以及刻意留給外掛或不納入核心的項目。

## 1. ROI 形狀與運作方式 {#roi}

ROI 面板涵蓋產線常用的形狀。區域是一個自由格式 dict，格式由 `tools/roi.py` 的檔頭定義；所有工具都走相同輔助函式：`bounding_rect`、`mask_for`、`crop`、`region_overlay`、`region_center` 與 `transform_region`。前端由 `roiEditor.ts` 與 `geometry.ts` 負責繪製、控制點編輯與命中測試。

| 形狀 | 平台形狀 | 狀態 | 運作方式 |
|---|---|---|---|
| 矩形 | `rect` | 原有 | 八個控制點 |
| 旋轉矩形 | `rotated_rect` | 原有 | 一個旋轉控制點；量測工具用 `crop(upright=True)` 校正方向 |
| 橢圓 | `ellipse` (cx, cy, rx, ry, angle) | **已新增** | 兩個半徑控制點與一個旋轉控制點；遮罩為填滿橢圓，疊圖用 36 邊近似 |
| 點 | `point` (x, y) | **已新增** | 單一像素遮罩，供灰階統計工具做定點讀值 |
| 線 | `line` | 原有 | 端點控制點，Shift 會吸附到 15 度 |
| 折線 | `polyline` (points) | **已新增** | 開放折線：拖曳頂點、雙擊邊插入、右鍵移除；與多邊形共用編輯路徑，供線剖面工具使用 |
| 多邊形 | `polygon` | 原有 | 頂點編輯；標註編輯器也用逐點方式繪製 |
| 圓環，可選扇區 | `annulus` 加選用 `a0`/`a1` | 扇區角度 **已新增** | 內外半徑控制點；設定 a0/a1 時另有兩個角度控制點。遮罩先填滿外扇區，再挖掉內圓 |
| 多重區域與排除區 | `composite` (ops: union / subtract / intersect, 可巢狀) | **已新增** | 不直接畫在畫布上；`region_from_shape` 各自保存一個繪製形狀，`region_combine` 在執行時組合。`mask_for` 依序套用操作，`bounding_rect` 取加入部分的聯集，排除不會擴大邊界；疊圖會顯示含孔洞的實際外形，ROI 跟隨會移動每一部分 |
| 手繪區域或手繪線 | - | 未實作 | 多邊形與折線已涵蓋用途；手繪 ROI 在產線上重複性差 |

任何 ROI 也可經由 `region` 輸入連接埠傳入，`transform_region()` 會平移並旋轉每種形狀。位置校正即建立在此機制上：將定位偏移接到步驟的 `_transform` 輸入後，`ToolContext.roi()` 會先移動已繪製區域，工具看到的裁切、遮罩與標記仍維持全圖座標，工具本身不需要知道校正存在。

**紋理表面上的表面缺陷**，例如刮痕、細毛與細裂紋，使用 `surface_filter`。它沿著痕跡方向平均、垂直方向微分，預設測八個角度並保留最強回應，因此細長痕跡會凸顯，底紋不會。`fft_filter` 適合重複背景的頻率低通，此工具適合非週期背景。成本為每角度一次卷積，八角度約 640x480 25 ms、1280x960 90 ms；零件大於關注區時請指定區域。

**整條邊一次檢查** 使用 `edge_defect`。卡尺沿直線或圓弧邊排列，可使用畫布區域，也可使用前一步實際找到的線或圓。偏離理想邊的連續段會以缺陷回傳並附上類型：缺口或毛邊是邊緣過度內縮或外凸的區段，崩邊是邊緣消失的區段，錯位是相鄰卡尺之間的突跳；成對模式會直接檢查兩邊間寬度。每個缺陷都有框、沿邊長度與面積，可依最嚴重缺陷或數量判定。

## 2. 影像格式與位元深度 {#depth}

機器視覺常見型別包含灰階 U8、I16、float、complex、RGB U32、HSL U32 與 RGB U64。平台在 `tools/imgfmt.py` 中對應到 numpy dtype。

| 常見型別 | 此平台 | 備註 |
|---|---|---|
| Grayscale U8 / RGB U32 | `uint8` (HxW 或 HxWx3 BGR) | 預設；所有工具支援 |
| Grayscale I16 | `uint16` | 16-bit PNG 與 TIFF 會以原樣讀入；signed 16-bit 以 offset 視為 unsigned |
| RGB U64 | `uint16` x3 (BGR) | 每通道 16 bit |
| Grayscale float | `float32` | 浮點 TIFF、FFT 與標定中間資料 |
| HSL U32 | - (編碼) | 不需要原生儲存；`color_convert` 擷取 H/S/L 或 V，`color_stats` 報告 HSV 統計 |
| Complex | - (工具內部) | 僅用於 `fft_filter`，不沿圖流傳遞 |

安全邊界在於工具以 `Tool.accepts = ("u8", ...)` 宣告可接受深度，`ToolContext.image()` 會以 `normalize_u8` 將其他深度轉成新陣列，不改動輸入。能原生處理更多深度的工具，例如 crop、resize、blur、morphology、arithmetic、apply_mask、grayscale、rotate_flip、save_image、convert_depth、fft_filter、line_profile、warp_perspective，會宣告較寬集合並原樣傳遞資料。顯示端 `encode_image` 一直都會在編碼前正規化。若您要自行控制轉換，請使用位元深度轉換工具。

## 3. 各能力對應到哪些工具 {#tools}

### 畫格緩衝與 ROI 寫回 {#frame-buffers}

`frame_accumulate` 將目前流程的近期畫格保存在流程變數中，等指定數量準備好後輸出平均、最小或最大，也可在即時調校時每次執行都輸出。預覽、`flow_id<=0` 與沙盒上下文只寫入變數疊圖，不會推進正式累積。`previous_image` 讀取前一次執行中某節點輸出的影像快取，或依 `k` 讀較舊執行；快取消失時走 `not_found`。`paste_back` 完成 ROI 迴圈：裁切區域、處理小圖，再依區域或 `x`/`y` 貼回全圖，可替換、混合或套遮罩，並會在影像邊界裁切。

| 能力 | 工具 | 狀態 |
|---|---|---|
| 登錄偵測、計數、存在判斷（零訓練） | `register_detect` 以少量裁切登錄圖尋找相似零件，可加入排除相似物、搜尋區、尺寸與角度；回傳標籤、數量、最佳位置、相似度與存在狀態 | **已新增** |
| 查找表與亮度曲線 | `lut`，含直方圖等化與 CLAHE；舊 contrast 工具會自動映射 | **已新增** |
| 卷積與濾波 | `filter`（sharpen、Canny、Laplacian、Sobel、Prewitt、high pass、emboss、自訂 3x3）；平滑為 `blur` | **已新增** |
| FFT 頻率濾波 | `fft_filter`，含頻譜輸出 | **已新增** |
| 多畫格降噪與時間比較 | `frame_accumulate` 與 `previous_image` | **已新增** |
| 影像運算與遮罩 | `arithmetic`、`apply_mask`、`paste_back` | **已擴充** |
| 灰階形態學 | `morphology` | 原有 |
| 閾值 | `threshold`：fixed、Otsu、Triangle、adaptive mean、adaptive Gaussian、range | 原有加新增 |
| 粒子分析 | `blob`：面積、圓度、外框、周長、方向、延伸率、最大內接矩形、遲滯與軟加權閾值 | 原有加新增 |
| 標籤圖 blob 分析 | `blob_label` 由整數 label map 依類別分析連通 blob | **已新增** |
| 合併與過濾框 | `boxes_merge`、`boxes_filter` 依 IoU、中心距、尺寸、分數、標籤與區域處理 match box | **已新增** |
| 矩形陣列校正與排序 | `array_correct`、`list_sort` | **已新增** |
| 分離相連粒子 | `blob` 的 split touching particles 選項 | **已新增** |
| 光度、線剖面、清晰度 | `intensity`、`line_profile`、`sharpness` | 原有加新增 |
| 顏色統計、分割與分類 | `color_stats`、`color_segment`、`color_classify`、`color_convert`、`merge_rgb`、`color_check`、`color_range` | 原有加新增 |
| 邊緣、卡尺與輪廓鏈 | `find_line`、`find_circle`、`caliper`、`path_extract`、`edge_model_defect`、`edge_trend`、`circular_caliper`、`profile_defect` | 已擴充 |
| GD&T 形狀與位置公差 | `gdt_measure` 量測直線度、平面度、圓度、平行度、垂直度與角度 | **已新增** |
| 多光源表面形狀與融合 | `photometric_stereo`、`multi_light_grab`、`multi_light_fuse` | **已新增** |
| 樣板與形狀比對 | `template_match`、`shape_match`、`shape_align`，支援多樣板、旋轉、遮擋、尺度與 NMS | 已擴充 |
| 連續執行追蹤與輸送帶 | `track_objects`、`edge_filter`、`ai_segment`、`stereo_depth` | **已新增** |
| 座標轉換與機械手臂補償 | `coordinate`、`to_world`、`map_points`、`align_offset` | **已新增** |
| 解析幾何與形狀尋找 | `geometry`、`find_rectangle`、`find_quadrilateral`、`find_parallel_lines`、`find_lines_multi`、`find_circles_matrix` | 原有加新增 |
| 透視校正與多相機拼接 | `warp_perspective`、`stitch_images` | **已新增** |
| 平場與陰影校正 | `shading_correct` | **已新增** |
| 輪廓、極座標展開 | `contour_find`、`contour_filter`、`contour_geometry`、`contour_match`、`polar_unwrap`、`polar_restore` | **已新增** |
| 鏡頭畸變與直接物理量測 | `undistort` 與可選標定資產，讓多個量測工具新增 `*_world` 與 `unit` 輸出 | **已新增** |
| Golden 比較與統計樣板 | `defect_diff`、`defect_stat`，搭配 Golden Set 回歸頁 | 原有加新增 |
| OCR、OCV 與條碼 | `ocr_read`、`ocv_verify`、`barcode`、`barcode_grade` | 已擴充 |
| 深度學習推論 | `dl_classify`、`dl_anomaly`、`ai_detect`、`ai_segment`、`ai_pose`、`ai_obb`、`ai_classify` | 原有加新增 |
| 登錄存在判斷 | `register_detect` 的 Detect 模式，依登錄圖回傳 found / not_found | **已新增** |
| 登錄計數判斷 | `register_detect` 的 Count 模式，檢查最小與最大數量 | **已新增** |
| 登錄存在狀態 | `register_detect` 的 Presence 模式，檢查 Present 或 Absent | **已新增** |
| CLAHE 對比 | `lut` 中的局部直方圖等化 | **已新增** |
| 自訂 3x3 濾波 | `filter` 的 custom kernel | **已新增** |
| ROI 裁切寫回 | `paste_back` 以遮罩或混合模式放回全圖 | **已新增** |
| label map 類別保留 | `blob_label` 保留 class id 與 class name | **已新增** |
| match 去重 | `boxes_merge` 依 IoU 或中心距合併 | **已新增** |
| match 篩選 | `boxes_filter` 依尺寸、分數、標籤與區域篩選 | **已新增** |
| 缺格補位 | `array_correct` 回報缺格並建立 placeholder box | **已新增** |
| pick 順序 | `list_sort` 依 x、y、reading order、score 或 label 排序 | **已新增** |
| 點光度 | `intensity` 支援 point ROI | **已新增** |
| 線剖面 | `line_profile` 沿折線輸出剖面與統計 | **已新增** |
| 低光誤高分抑制 | `sharpness` 加入 robust high-frequency noise estimate | **已新增** |
| 顏色 label map | `color_segment` 輸出整張整數 label map | **已新增** |
| 顏色樣本比對 | `color_classify` 回傳最接近樣本與 top-three | **已新增** |
| 多通道合成 | `merge_rgb` 將 R/G/B 灰階輸入合成彩色影像 | **已新增** |
| 任意輪廓採樣 | `path_extract` 沿線或多邊形等距取樣 | **已新增** |
| 輪廓缺陷模型 | `edge_model_defect` 依教導輪廓尋找缺口、毛邊與斷角 | **已新增** |
| 邊緣趨勢 | `edge_trend` 回傳 offset 序列與統計 | **已新增** |
| 圓周半徑序列 | `circular_caliper` 回傳每角度半徑與 run-out | **已新增** |
| 一維剖面缺陷 | `profile_defect` 將半徑或線剖面分段為缺陷 | **已新增** |
| 光度立體曲率 | `photometric_stereo` 輸出 curvature、shape-strength、albedo 與 normal | **已新增** |
| 多光源擷取序列 | `multi_light_grab` 控制光源 channel、亮度、曝光與角度 | **已新增** |
| 多光源融合模式 | `multi_light_fuse` 提供 reflection、shadow、mean 與 direction 模式 | **已新增** |
| 多樣板同時比對 | `template_match` 每個 match 回報命中的樣板與排序 | **已擴充** |
| 內建 fiducial 形狀 | `shape_match` 可即時合成 cross、square_outline 或 disc | **已擴充** |
| 物件穩定 ID | `track_objects` 保留位置、速度、age 與 missing-frame count | **已新增** |
| 雙線計數 | `track_objects` 的 two-point count line 依方向累計 | **已新增** |
| 立體高度 Z | `stereo_depth` 透過 `stereo.z_ref` 寫入 robot `z` | **已新增** |
| 局部座標框 | `coordinate` 建立 frame 供 `to_world` 使用 | **已新增** |
| 相機交接點 | `map_points` 映射單點、點集或 locate matches | **已新增** |
| 不寫外掛的自訂演算法 | `python_script` 在工具頁撰寫 `def run(ctx)`，由管理員儲存核准 | **已新增** |

### 輸送帶追蹤 {#conveyor-tracking}

單相機輸送帶取放流程通常連接 `image_source` -> `ai_segment` -> `edge_filter` -> `track_objects` -> `format_text` -> 輸出寫入器。立體 Z 版本以 `stereo_grab` 開始，並在 `track_objects` 前後插入 `stereo_depth`；放在前面會量測每個 match，放在後面只量測送往機械手臂的 `new_confirmed`。`ai_segment` 保留原 match 欄位並加入 `polygon`、`centroid` 與 `mask_area`。`edge_filter` 可分別檢查四側邊界，0 表示停用該側。`track_objects` 指派平台 ID，重設後仍保持單調遞增，物件達到 `confirm_frames` 後標為 confirmed，且只在首次 confirmed 的畫格輸出 `new_confirmed`。

## 4. 刻意略過，或交給外掛 {#skip}

- **顏色樣板比對、顏色定位**：`shape_match`、`template_match` 與深度學習工具已涵蓋主要用途；需要顏色專用比對時可作為外掛工具加入（[Plugins](/docs/plugins.html)）。
- **儀表讀值**：用 `ocr_read` 讀數字（七段顯示器可用教導字型），再以 `formula` 轉換；指針式儀表讀取適合外掛。
- **完整 3D hand-eye 標定**： [Hand-eye wizard](calibration.md#hand-eye) 記錄固定或移動相機，以實際點對擬合 2D 像素到機械手臂仿射映射，也可找工具旋轉中心。由機械手臂姿態求完整 3D 相機姿態仍留給機械手臂程式或外掛。
- **手繪 ROI**：見第 1 節。
- **complex 影像型別**：只存在於 `fft_filter` 內部，不作為連接埠型別，讓資料流保持簡單。

## 條碼品質分級：參數代表什麼 {#barcode-grading}

`barcode_grade` 步驟以驗證器方式量測符號，並對每個參數回報獨立等級（A = 4 到 F = 0）。2D 符號的總等級取最低參數等級；線性條碼則取十條掃描線的平均，而每條掃描線先取自身最低參數。此工具把 8-bit 灰階視為反射率並以圓盤濾波近似光學孔徑，因此數值量級接近驗證器；但它不是認證驗證器，也未套用照明或反射率校正。*Parameters* 輸出會列出每個值、等級與註記。

### 2D 符號：ISO/IEC 15415 (Data Matrix, QR) {#grading-2d}

| 參數 | 量測內容 | 降級常見原因 | 等級門檻 |
|---|---|---|---|
| Decode | 符號是否能解碼 | quiet zone 缺失、模組損壞過多、symbology filter 錯誤 | 可解碼為 A，否則 F |
| Symbol contrast | 符號與 quiet zone 中最亮與最暗反射率差 | 墨色不足、基材反光或太暗、曝光不足 | >=0.70 A，>=0.55 B，>=0.40 C，>=0.20 D |
| Modulation | 各模組相對全域閾值與對比的距離 | 模糊、噪聲、油墨擴散或空洞、照明不均 | 依模組門檻並結合未用錯誤修正 |
| Fixed pattern damage | finder、clock、timing、alignment、format 與 quiet zone 的損壞 | 符號邊緣髒污、列印被截斷、quiet zone 有標記 | 依損壞比例與格式位元錯誤分級 |
| Axial non-uniformity | 水平與垂直模組 pitch 相對平均值的差 | 相機未垂直零件、列印伸縮、非方形像素 | <=0.06 A，<=0.08 B，<=0.10 C，<=0.12 D |
| Grid non-uniformity | 模組邊緣偏離理想格線的最大值 | 標籤翹曲、透視、打標頭抖動 | <=0.38 A，<=0.50 B，<=0.63 C，<=0.75 D |
| Unused error correction | 解碼後仍未使用的錯誤修正容量比例 | 模組損壞、反相或缺失 | >=0.62 A，>=0.50 B，>=0.37 C，>=0.25 D |

### 直接零件標記：AIM DPM (ISO/IEC TR 29158) {#grading-dpm}

金屬或塑膠上的標記通常達不到印刷標籤的對比，因此 DPM 標準替換兩個參數並新增一個，同時允許中值預濾波與較小孔徑。Decode、fixed pattern damage、axial/grid non-uniformity 與 unused error correction 依上方規則分級。

| 參數 | 量測內容 | 等級門檻 |
|---|---|---|
| Cell contrast | (亮 cell 平均 - 暗 cell 平均) / 亮 cell 平均；使用 cell 平均而非極值 | >=0.30 A，>=0.25 B，>=0.20 C，>=0.15 D |
| Cell modulation | 各 cell 與閾值的距離，相對於亮或暗 cell 平均，並套用同樣錯誤修正餘裕 | >=0.50 A，>=0.40 B，>=0.30 C，>=0.20 D |
| Minimum reflectance | 最暗點相對最亮點的比例；曝光檢查 | <=5% A，否則 F |

### 線性符號：ISO/IEC 15416 (EAN, UPC, Code 128, Code 39) {#grading-1d}

工具會在條高 10% 到 90% 之間取十條掃描線。每條線依下列參數分級並取最低值，總等級為十條線平均；3.5 以上 A、2.5 B、1.5 C、0.5 D。線性符號一律依 15416 分級。

| 參數 | 量測內容 | 等級門檻 |
|---|---|---|
| Decode | 掃描線是否解出相同內容 | 每條線 A 或 F |
| Symbol contrast | 掃描線上的 Rmax - Rmin | >=0.70 A，>=0.55 B，>=0.40 C，>=0.20 D |
| Minimum reflectance | 最暗 bar 必須不超過最亮 space 的一半 | Rmin <= 0.5 x Rmax 為 A，否則 F |
| Edge contrast | 任一相鄰 bar/space 的最小對比 | >=0.15 A，否則 F |
| Modulation | Edge contrast / symbol contrast | >=0.70 A，>=0.60 B，>=0.50 C，>=0.40 D |
| Defects | space 中斑點或 bar 中空洞的最大值 / symbol contrast | <=0.15 A，<=0.20 B，<=0.25 C，<=0.30 D |
| Decodability | bar/space 寬度接近模組名目倍數的程度 | >=0.62 A，>=0.50 B，>=0.37 C，>=0.25 D |

將 *Minimum grade* 設為客戶規格要求的等級；汽車與醫療標籤通常要求 C 以上，有時要求 B。步驟在總等級達到或高於該設定時通過。2D 符號的參考格線由符號自身固定圖樣細化，因此分級不依賴哪個解碼器找到符號。
