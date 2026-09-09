# 检测能力：ROI、图像格式与工具

此页以主流机器视觉套裝软件作為對照，说明平台提供哪些 ROI 形狀、如何实现多種位元深度，以及各类检测需求在此平台中对应到哪些工具。也列出近期新增的能力，以及刻意留給插件或不納入核心的項目。

## 1. ROI 形狀与運作方式 {#roi}

ROI 面板涵蓋產线常用的形狀。区域是一個自由格式 dict，格式由 `tools/roi.py` 的檔頭定义；所有工具都走相同輔助函式：`bounding_rect`、`mask_for`、`crop`、`region_overlay`、`region_center` 与 `transform_region`。前端由 `roiEditor.ts` 与 `geometry.ts` 负责绘制、控制点编辑与命中测试。

| 形狀 | 平台形狀 | 状态 | 運作方式 |
|---|---|---|---|
| 矩形 | `rect` | 原有 | 八個控制点 |
| 旋转矩形 | `rotated_rect` | 原有 | 一個旋转控制点；量測工具用 `crop(upright=True)` 校正方向 |
| 橢圆 | `ellipse` (cx, cy, rx, ry, angle) | **已新增** | 兩個半徑控制点与一個旋转控制点；遮罩為填滿橢圆，疊圖用 36 边近似 |
| 点 | `point` (x, y) | **已新增** | 單一像素遮罩，供灰階统计工具做定点讀值 |
| 线 | `line` | 原有 | 端点控制点，Shift 會吸附到 15 度 |
| 折线 | `polyline` (points) | **已新增** | 開放折线：拖曳頂点、双擊边插入、右鍵移除；与多边形共用编辑路徑，供线剖面工具使用 |
| 多边形 | `polygon` | 原有 | 頂点编辑；标注编辑器也用逐点方式绘制 |
| 圆環，可選扇區 | `annulus` 加選用 `a0`/`a1` | 扇區角度 **已新增** | 內外半徑控制点；设置 a0/a1 時另有兩個角度控制点。遮罩先填滿外扇區，再挖掉內圆 |
| 多重区域与排除區 | `composite` (ops: union / subtract / intersect, 可巢狀) | **已新增** | 不直接畫在畫布上；`region_from_shape` 各自保存一個绘制形狀，`region_combine` 在执行時組合。`mask_for` 依序套用操作，`bounding_rect` 取加入部分的聯集，排除不會擴大边界；疊圖會显示含孔洞的实际外形，ROI 跟隨會移動每一部分 |
| 手繪区域或手繪线 | - | 未实现 | 多边形与折线已涵蓋用途；手繪 ROI 在產线上重复性差 |

任何 ROI 也可經由 `region` 输入连接埠傳入，`transform_region()` 會平移並旋转每種形狀。位置校正即建立在此機制上：將定位偏移接到步骤的 `_transform` 输入后，`ToolContext.roi()` 會先移動已绘制区域，工具看到的裁切、遮罩与標記仍維持全圖座標，工具本身不需要知道校正存在。

**紋理表面上的表面缺陷**，例如刮痕、細毛与細裂紋，使用 `surface_filter`。它沿著痕跡方向平均、垂直方向微分，默认測八個角度並保留最強回應，因此細長痕跡會凸顯，底紋不會。`fft_filter` 適合重复背景的頻率低通，此工具適合非週期背景。成本為每角度一次卷積，八角度約 640x480 25 ms、1280x960 90 ms；零件大於關注區時請指定区域。

**整條边一次檢查** 使用 `edge_defect`。卡尺沿直线或圆弧边排列，可使用畫布区域，也可使用前一步实际找到的线或圆。偏離理想边的連續段會以缺陷回傳並附上类型：缺口或毛边是边緣過度內縮或外凸的區段，崩边是边緣消失的區段，錯位是相鄰卡尺之間的突跳；成對模式會直接檢查兩边間寬度。每個缺陷都有框、沿边長度与面積，可依最嚴重缺陷或數量判定。

## 2. 图像格式与位元深度 {#depth}

机器视觉常見型別包含灰階 U8、I16、float、complex、RGB U32、HSL U32 与 RGB U64。平台在 `tools/imgfmt.py` 中对应到 numpy dtype。

| 常見型別 | 此平台 | 備註 |
|---|---|---|
| Grayscale U8 / RGB U32 | `uint8` (HxW 或 HxWx3 BGR) | 默认；所有工具支持 |
| Grayscale I16 | `uint16` | 16-bit PNG 与 TIFF 會以原樣讀入；signed 16-bit 以 offset 視為 unsigned |
| RGB U64 | `uint16` x3 (BGR) | 每通道 16 bit |
| Grayscale float | `float32` | 浮点 TIFF、FFT 与标定中間数据 |
| HSL U32 | - (編碼) | 不需要原生保存；`color_convert` 擷取 H/S/L 或 V，`color_stats` 報告 HSV 统计 |
| Complex | - (工具內部) | 僅用於 `fft_filter`，不沿圖流傳遞 |

安全边界在於工具以 `Tool.accepts = ("u8", ...)` 宣告可接受深度，`ToolContext.image()` 會以 `normalize_u8` 將其他深度转成新陣列，不改動输入。能原生處理更多深度的工具，例如 crop、resize、blur、morphology、arithmetic、apply_mask、grayscale、rotate_flip、save_image、convert_depth、fft_filter、line_profile、warp_perspective，會宣告較寬集合並原樣傳遞数据。显示端 `encode_image` 一直都會在編碼前正規化。若您要自行控制转換，請使用位元深度转換工具。

## 3. 各能力对应到哪些工具 {#tools}

### 畫格緩衝与 ROI 寫回 {#frame-buffers}

`frame_accumulate` 將目前流程的近期畫格保存在流程變數中，等指定數量準備好后输出平均、最小或最大，也可在即時調校時每次执行都输出。預覽、`flow_id<=0` 与沙盒上下文只寫入變數疊圖，不會推進正式累積。`previous_image` 讀取前一次执行中某節点输出的图像快取，或依 `k` 讀較舊执行；快取消失時走 `not_found`。`paste_back` 完成 ROI 迴圈：裁切区域、處理小圖，再依区域或 `x`/`y` 貼回全圖，可替換、混合或套遮罩，並會在图像边界裁切。

| 能力 | 工具 | 状态 |
|---|---|---|
| 登錄检测、計數、存在判斷（零训练） | `register_detect` 以少量裁切登錄圖尋找相似零件，可加入排除相似物、搜尋區、尺寸与角度；回傳標籤、數量、最佳位置、相似度与存在状态 | **已新增** |
| 查找表与亮度曲线 | `lut`，含直方圖等化与 CLAHE；舊 contrast 工具會自動映射 | **已新增** |
| 卷積与濾波 | `filter`（sharpen、Canny、Laplacian、Sobel、Prewitt、high pass、emboss、自訂 3x3）；平滑為 `blur` | **已新增** |
| FFT 頻率濾波 | `fft_filter`，含頻譜输出 | **已新增** |
| 多畫格降噪与時間比較 | `frame_accumulate` 与 `previous_image` | **已新增** |
| 图像運算与遮罩 | `arithmetic`、`apply_mask`、`paste_back` | **已擴充** |
| 灰階形態學 | `morphology` | 原有 |
| 阈值 | `threshold`：fixed、Otsu、Triangle、adaptive mean、adaptive Gaussian、range | 原有加新增 |
| 粒子分析 | `blob`：面積、圆度、外框、周長、方向、延伸率、最大內接矩形、遲滯与軟加權阈值 | 原有加新增 |
| 標籤圖 blob 分析 | `blob_label` 由整數 label map 依类別分析連通 blob | **已新增** |
| 合併与過濾框 | `boxes_merge`、`boxes_filter` 依 IoU、中心距、尺寸、分數、標籤与区域處理 match box | **已新增** |
| 矩形陣列校正与排序 | `array_correct`、`list_sort` | **已新增** |
| 分離相連粒子 | `blob` 的 split touching particles 選項 | **已新增** |
| 光度、线剖面、清晰度 | `intensity`、`line_profile`、`sharpness` | 原有加新增 |
| 顏色统计、分割与分类 | `color_stats`、`color_segment`、`color_classify`、`color_convert`、`merge_rgb`、`color_check`、`color_range` | 原有加新增 |
| 边緣、卡尺与輪廓鏈 | `find_line`、`find_circle`、`caliper`、`path_extract`、`edge_model_defect`、`edge_trend`、`circular_caliper`、`profile_defect` | 已擴充 |
| GD&T 形狀与位置公差 | `gdt_measure` 量測直线度、平面度、圆度、平行度、垂直度与角度 | **已新增** |
| 多光源表面形狀与融合 | `photometric_stereo`、`multi_light_grab`、`multi_light_fuse` | **已新增** |
| 樣板与形狀比對 | `template_match`、`shape_match`、`shape_align`，支持多樣板、旋转、遮擋、尺度与 NMS | 已擴充 |
| 連續执行追蹤与輸送帶 | `track_objects`、`edge_filter`、`ai_segment`、`stereo_depth` | **已新增** |
| 座標转換与機械手臂补偿 | `coordinate`、`to_world`、`map_points`、`align_offset` | **已新增** |
| 解析幾何与形狀尋找 | `geometry`、`find_rectangle`、`find_quadrilateral`、`find_parallel_lines`、`find_lines_multi`、`find_circles_matrix` | 原有加新增 |
| 透視校正与多相机拼接 | `warp_perspective`、`stitch_images` | **已新增** |
| 平場与陰影校正 | `shading_correct` | **已新增** |
| 輪廓、極座標展開 | `contour_find`、`contour_filter`、`contour_geometry`、`contour_match`、`polar_unwrap`、`polar_restore` | **已新增** |
| 鏡頭畸變与直接物理量測 | `undistort` 与可選标定资产，讓多個量測工具新增 `*_world` 与 `unit` 输出 | **已新增** |
| Golden 比較与统计樣板 | `defect_diff`、`defect_stat`，搭配 Golden Set 回歸页 | 原有加新增 |
| OCR、OCV 与條碼 | `ocr_read`、`ocv_verify`、`barcode`、`barcode_grade` | 已擴充 |
| 深度学习推論 | `dl_classify`、`dl_anomaly`、`ai_detect`、`ai_segment`、`ai_pose`、`ai_obb`、`ai_classify` | 原有加新增 |
| 登錄存在判斷 | `register_detect` 的 Detect 模式，依登錄图回傳 found / not_found | **已新增** |
| 登錄计数判斷 | `register_detect` 的 Count 模式，检查最小與最大数量 | **已新增** |
| 登錄存在狀態 | `register_detect` 的 Presence 模式，检查 Present 或 Absent | **已新增** |
| CLAHE 對比 | `lut` 中的局部直方图等化 | **已新增** |
| 自訂 3x3 滤波 | `filter` 的 custom kernel | **已新增** |
| ROI 裁切寫回 | `paste_back` 以遮罩或混合模式放回全图 | **已新增** |
| label map 類別保留 | `blob_label` 保留 class id 與 class name | **已新增** |
| match 去重 | `boxes_merge` 依 IoU 或中心距合併 | **已新增** |
| match 篩选 | `boxes_filter` 依尺寸、分数、標籤與區域篩选 | **已新增** |
| 缺格補位 | `array_correct` 回報缺格並建立 placeholder box | **已新增** |
| pick 順序 | `list_sort` 依 x、y、reading order、score 或 label 排序 | **已新增** |
| 點光度 | `intensity` 支持 point ROI | **已新增** |
| 线剖面 | `line_profile` 沿折线输出剖面與统计 | **已新增** |
| 低光誤高分抑制 | `sharpness` 加入 robust high-frequency noise estimate | **已新增** |
| 顏色 label map | `color_segment` 输出整張整数 label map | **已新增** |
| 顏色樣本比對 | `color_classify` 回傳最接近樣本與 top-three | **已新增** |
| 多通道合成 | `merge_rgb` 將 R/G/B 灰階输入合成彩色图像 | **已新增** |
| 任意輪廓採樣 | `path_extract` 沿线或多邊形等距取樣 | **已新增** |
| 輪廓缺陷模型 | `edge_model_defect` 依教导輪廓寻找缺口、毛邊與斷角 | **已新增** |
| 邊緣趨勢 | `edge_trend` 回傳 offset 序列與统计 | **已新增** |
| 圓周半徑序列 | `circular_caliper` 回傳每角度半徑與 run-out | **已新增** |
| 一維剖面缺陷 | `profile_defect` 將半徑或线剖面分段為缺陷 | **已新增** |
| 光度立體曲率 | `photometric_stereo` 输出 curvature、shape-strength、albedo 與 normal | **已新增** |
| 多光源采集序列 | `multi_light_grab` 控制光源 channel、亮度、曝光與角度 | **已新增** |
| 多光源融合模式 | `multi_light_fuse` 提供 reflection、shadow、mean 與 direction 模式 | **已新增** |
| 多模板同時比對 | `template_match` 每個 match 回報命中的模板與排序 | **已擴充** |
| 內建 fiducial 形狀 | `shape_match` 可即時合成 cross、square_outline 或 disc | **已擴充** |
| 物件穩定 ID | `track_objects` 保留位置、速度、age 與 missing-frame count | **已新增** |
| 雙线计数 | `track_objects` 的 two-point count line 依方向累計 | **已新增** |
| 立體高度 Z | `stereo_depth` 透過 `stereo.z_ref` 寫入 robot `z` | **已新增** |
| 局部座標框 | `coordinate` 建立 frame 供 `to_world` 使用 | **已新增** |
| 相机交接點 | `map_points` 映射單點、點集或 locate matches | **已新增** |
| 不寫插件的自訂演算法 | `python_script` 在工具页撰寫 `def run(ctx)`，由管理員保存核准 | **已新增** |

### 輸送帶追蹤 {#conveyor-tracking}

單相机輸送帶取放流程通常连接 `image_source` -> `ai_segment` -> `edge_filter` -> `track_objects` -> `format_text` -> 输出寫入器。立體 Z 版本以 `stereo_grab` 開始，並在 `track_objects` 前后插入 `stereo_depth`；放在前面會量測每個 match，放在后面只量測送往機械手臂的 `new_confirmed`。`ai_segment` 保留原 match 欄位並加入 `polygon`、`centroid` 与 `mask_area`。`edge_filter` 可分別檢查四側边界，0 表示停用該側。`track_objects` 指派平台 ID，重設后仍保持單調遞增，物件達到 `confirm_frames` 后標為 confirmed，且只在首次 confirmed 的畫格输出 `new_confirmed`。

## 4. 刻意略過，或交給插件 {#skip}

- **顏色樣板比對、顏色定位**：`shape_match`、`template_match` 与深度学习工具已涵蓋主要用途；需要顏色專用比對時可作為插件工具加入（[Plugins](/docs/plugins.html)）。
- **儀表讀值**：用 `ocr_read` 讀數字（七段显示器可用教导字型），再以 `formula` 转換；指針式儀表讀取適合插件。
- **完整 3D hand-eye 标定**： [Hand-eye wizard](calibration.md#hand-eye) 记录固定或移動相机，以实际点對擬合 2D 像素到機械手臂仿射映射，也可找工具旋转中心。由機械手臂姿態求完整 3D 相机姿態仍留給機械手臂程序或插件。
- **手繪 ROI**：見第 1 節。
- **complex 图像型別**：只存在於 `fft_filter` 內部，不作為连接埠型別，讓数据流保持簡單。

## 條碼品質分級：参数代表什麼 {#barcode-grading}

`barcode_grade` 步骤以驗證器方式量測符號，並對每個参数回報獨立等級（A = 4 到 F = 0）。2D 符號的總等級取最低参数等級；线性條碼則取十條掃描线的平均，而每條掃描线先取自身最低参数。此工具把 8-bit 灰階視為反射率並以圆盤濾波近似光學孔徑，因此数值量級接近驗證器；但它不是認證驗證器，也未套用照明或反射率校正。*Parameters* 输出會列出每個值、等級与註記。

### 2D 符號：ISO/IEC 15415 (Data Matrix, QR) {#grading-2d}

| 参数 | 量測內容 | 降級常見原因 | 等級門檻 |
|---|---|---|---|
| Decode | 符號是否能解碼 | quiet zone 缺失、模組損壞過多、symbology filter 错误 | 可解碼為 A，否則 F |
| Symbol contrast | 符號与 quiet zone 中最亮与最暗反射率差 | 墨色不足、基材反光或太暗、曝光不足 | >=0.70 A，>=0.55 B，>=0.40 C，>=0.20 D |
| Modulation | 各模組相對全域阈值与對比的距離 | 模糊、噪聲、油墨擴散或空洞、照明不均 | 依模組門檻並結合未用错误修正 |
| Fixed pattern damage | finder、clock、timing、alignment、format 与 quiet zone 的損壞 | 符號边緣髒污、列印被截斷、quiet zone 有標記 | 依損壞比例与格式位元错误分級 |
| Axial non-uniformity | 水平与垂直模組 pitch 相對平均值的差 | 相机未垂直零件、列印伸縮、非方形像素 | <=0.06 A，<=0.08 B，<=0.10 C，<=0.12 D |
| Grid non-uniformity | 模組边緣偏離理想格线的最大值 | 標籤翹曲、透視、打標頭抖動 | <=0.38 A，<=0.50 B，<=0.63 C，<=0.75 D |
| Unused error correction | 解碼后仍未使用的错误修正容量比例 | 模組損壞、反相或缺失 | >=0.62 A，>=0.50 B，>=0.37 C，>=0.25 D |

### 直接零件標記：AIM DPM (ISO/IEC TR 29158) {#grading-dpm}

金屬或塑膠上的標記通常達不到印刷標籤的對比，因此 DPM 標準替換兩個参数並新增一個，同時允許中值預濾波与較小孔徑。Decode、fixed pattern damage、axial/grid non-uniformity 与 unused error correction 依上方規則分級。

| 参数 | 量測內容 | 等級門檻 |
|---|---|---|
| Cell contrast | (亮 cell 平均 - 暗 cell 平均) / 亮 cell 平均；使用 cell 平均而非極值 | >=0.30 A，>=0.25 B，>=0.20 C，>=0.15 D |
| Cell modulation | 各 cell 与阈值的距離，相對於亮或暗 cell 平均，並套用同樣错误修正餘裕 | >=0.50 A，>=0.40 B，>=0.30 C，>=0.20 D |
| Minimum reflectance | 最暗点相對最亮点的比例；曝光檢查 | <=5% A，否則 F |

### 线性符號：ISO/IEC 15416 (EAN, UPC, Code 128, Code 39) {#grading-1d}

工具會在條高 10% 到 90% 之間取十條掃描线。每條线依下列参数分級並取最低值，總等級為十條线平均；3.5 以上 A、2.5 B、1.5 C、0.5 D。线性符號一律依 15416 分級。

| 参数 | 量測內容 | 等級門檻 |
|---|---|---|
| Decode | 掃描线是否解出相同內容 | 每條线 A 或 F |
| Symbol contrast | 掃描线上的 Rmax - Rmin | >=0.70 A，>=0.55 B，>=0.40 C，>=0.20 D |
| Minimum reflectance | 最暗 bar 必須不超過最亮 space 的一半 | Rmin <= 0.5 x Rmax 為 A，否則 F |
| Edge contrast | 任一相鄰 bar/space 的最小對比 | >=0.15 A，否則 F |
| Modulation | Edge contrast / symbol contrast | >=0.70 A，>=0.60 B，>=0.50 C，>=0.40 D |
| Defects | space 中斑点或 bar 中空洞的最大值 / symbol contrast | <=0.15 A，<=0.20 B，<=0.25 C，<=0.30 D |
| Decodability | bar/space 寬度接近模組名目倍數的程度 | >=0.62 A，>=0.50 B，>=0.37 C，>=0.25 D |

將 *Minimum grade* 設為客戶規格要求的等級；汽車与醫療標籤通常要求 C 以上，有時要求 B。步骤在總等級達到或高於該设置時通過。2D 符號的參考格线由符號自身固定圖樣細化，因此分級不依賴哪個解碼器找到符號。
