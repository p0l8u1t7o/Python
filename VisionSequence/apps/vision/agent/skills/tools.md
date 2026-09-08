# 工具使用要領（AI 代理技能；每段以 `## <工具 type>` 開頭）

每段寫「什麼時候用、怎麼接、參數要領、陷阱」。參數與埠的完整定義由平台自動附在後面，這裡只寫目錄看不出來的經驗。

## fixed_image
固定影像（source 類）：`images` 是上傳到步驟裡的圖片清單（跟著流程存，不是資產），`mode` cycle 每次執行輪下一張／fixed 固定第 `index` 張；
`role` acquire＝待檢影像（API 送圖、批次測試會取代它），reference＝參考圖（永不取代）。沒有相機時用它取代 image_source；
要把範本／良品／白參考交給 template_match、defect_diff、contour_match、shading_correct，就放一個 role=reference 的固定影像節點，
把 `image` 接到那些工具的 `template_image`／`flat_image`／`dark_image` 埠（接了埠就不必選資產）。

## image_source
流程的起點、只能有一個。AI 生成時 `params` 只填 `{"mode": "auto"}`：試跑吃上傳影像，存成流程後使用者在編輯器選來源。不要綁 `source_id`。

## grayscale
幾乎所有幾何／二值化工具的前置。彩色判斷（color_range／color_check／color_stats）**不要**經過它。

## blur
去雜訊。`median`（ksize 3～7）對椒鹽雜訊最好且保邊；`gaussian` 對高斯雜訊；`bilateral` 保邊但慢。ksize 必須是奇數。

## threshold
二值化。門檻不確定用 `method="otsu"`；背景不均用 `adaptive`（block 31～101、c 5～10）；已知固定灰階用 `fixed`。目標比背景暗要 `invert=true`（讓目標變白 255）。輸出 `threshold_used` 可當曝光指標。

光照左右不均、金屬表面文字／刻印在不同區域亮度落差很大時，用 `method="sauvola"` 或 `method="niblack"`。`sauvola` 會用局部平均與局部標準差調整門檻，平坦背景較穩；`niblack` 是局部平均加上 `k * std`，對低對比文字較敏感但也較吃雜訊。只想改門檻方向或等於門檻是否算前景時才設 `compare`；裁完 ROI 後只處理局部，`outside_roi=black` 做遮罩，`outside_roi=keep` 保留原灰階。

## morphology
二值化後整理：`open` 去小雜點、`close` 補小洞、`erode`／`dilate` 調粗細。ksize 3～7；比目標小、比雜訊大。

## lut
灰階映射：`gamma`<1 提亮暗部、>1 壓亮部；`clahe` 局部對比（clip 2～4、tile 8）；`linear` 用 brightness／contrast。放在 threshold 前面救對比。

`normalize_ratio` 是百分位拉伸，忽略極端離群值，把 `low_percent`～`high_percent` 映到 0～255，適合有少量反光點、黑點但主體對比不足。`normalize_std` 是把整張圖調到指定平均與標準差，適合同一批影像要維持亮度／對比尺度一致；它不會特別忽略離群值。

## filter
銳化／邊緣：`sharpen` 補模糊；`canny`（low/high 約 1:2～1:3）取邊緣圖給 hough_lines／edge_density；`laplacian`／`sobel` 取梯度圖。

## surface_filter
有紋理的面上找細長瑕疵（刮傷、髮絲、細裂紋）：`width` 填缺陷大概幾像素寬、`length` 填它延伸多長、
`polarity` 選比表面暗還是亮，`directions` 8 就夠。輸出是「回應影像」＋ `max_response`，
**接 threshold → blob 數面積**，或直接用 `max_response` 判定。
**與 fft_filter 分工**：背景是規則紋路（織品、網點）用頻域低通；背景是隨機紋理（拉絲、噴砂、毛絲面）用這個。
gain 調到刮傷看得清楚、表面仍然暗為止，再設門檻。

## fft_filter
頻域濾波。規律紋理（織紋、網點、印刷網格）背景：`lowpass` cutoff 0.05～0.1 把紋理濾掉，殘留的大尺度暗痕就是缺陷；`highpass` 去掉光照漸層，輸出以中灰 128 為零點（暗於 128＝負響應），接 threshold 時門檻要以 128 為中心。輸出 `spectrum` 可看頻譜。

## crop
裁 ROI 成小圖加速，輸出 `offset_x/offset_y`。裁完的座標系變了：下游工具的 overlay 會在小圖座標，要回全圖記得加 offset。

## resize
`scale` 0.25～0.5 縮小加速守門類流程（曝光、粗略計數）；量測流程不要縮，精度會掉。

## color_convert
取單一色彩面：`hsv_s`（飽和度，抓有色物件最穩）、`hsv_h`、`hsv_v`、`lab_a/b`。輸出是灰階圖，可直接接 threshold。

## color_range
HSV 範圍遮罩：H 0～179（紅色跨 0：用 0～10 或 170～179 兩段），S/V 0～255。輸出遮罩＋`ratio`。接 pixel_count 判斷有無。

## color_segment
多色分割：`segments` 一行一段，格式 `名稱:H下,H上,S下,S上,V下,V上`，第 1 行輸出標籤 1、第 2 行標籤 2，背景是 0。HSV 的紅色常跨過 0/180，當 H 下界大於上界（例如 `170,10`）時視為環繞，會抓 `170..179` 與 `0..10` 兩段。輸出 `labels` 可直接接 `blob_label.labels` 做每色 blob、面積與數量；`areas/classes` 給快速判定與顯示。多段重疊時前面的段先佔標籤，設定色域時要避免重疊。單一色域用 `color_range`；多色一次切用 `color_segment`。

## color_classify
樣本顏色分類：`samples` 選固定影像，每張影像名稱就是回傳 label；工具把 ROI 的顏色直方圖和樣本比對，輸出 `label/similarity/ranking`，低於 `min_similarity` 走 ng。少量穩定色票用 `histogram_intersection`；顏色有漸層或光照飄移時可試 `earth_mover`，但 bins 不要開太大。樣本直方圖會依固定影像 id、`space`、`bins` 快取，不會每片重算。

## color_convert merge_rgb
三通道合成：`mode=merge_rgb` 時改用選填的 `r/g/b` 灰階輸入合成彩色影像；沒接的通道補 0，三個已接通道尺寸必須一致。用在多光源或多通道拍攝，輸出仍是一般彩色影像可接後續工具。

## apply_mask
把遮罩（255 保留、0 填 fill）套到影像，常用來只留缺陷區或只看某個色塊；`mask` 埠接 blob.mask／threshold 影像。

## arithmetic
兩張影像運算：`absdiff` 看處理前後或兩張差異；`subtract` 去背景（先拍空景）；`add`／`multiply` 做加權。兩張尺寸要一致。

## warp_perspective
四點透視校正：`roi` 用 `polygon` 四個角點（順序自動排），`width/height` 給輸出尺寸。標籤斜貼、相機斜拍時放在 barcode／text_presence／量測前面。

## undistort
鏡頭畸變校正：選一個 `calibration` 資產（標定頁做的），放在取像後、量測前。廣角或近距離時邊角的直線會拱起來，
校正後量測值才不會隨位置漂。`alpha` 0＝縮放到全部都是有效像素、1＝整個畫面留著（角落補黑）；`mm_per_pixel` 輸出接 calibration。
沒有標定資產就別放這個節點。

## polar_unwrap
極座標展開：圓周類檢測（瓶蓋螺紋、齒輪齒數、軸承滾珠、O-ring 缺口、環形焊道、圓形標籤字元）先把環帶攤平成
「寬＝角度、高＝半徑（內圈在上）」的長條圖，再接一般工具：`threshold` → `blob` 數齒／數缺口、`caliper` 量沿圓周的寬度、
`line_profile` 看一圈的亮度、`find_line` 找環上的直邊。`roi` 用 `annulus`（環要蓋住要看的齒／紋；帶 `a0/a1` 只展開扇形）或 `circle`。
`angle_step` 留 `auto`（外緣弧長 1 px）；`start_angle` 是接縫位置（現場教導：把接縫放在齒隙或無特徵處，否則一顆齒會被切成兩塊）；
`direction` 決定條帶走向。輸出 `image`（展開圖）與 `mapping`（幾何描述，接 polar_restore）。

## polar_restore
展開圖座標換回原圖：`mapping` 接 polar_unwrap.mapping，`points`／`contours` 接展開圖上工具的輸出（blob.centers／contours），
`image` 接原圖（標記畫在原圖上給現場看）。輸出 `points`／`contours`（原圖座標）、`first_x/first_y`、`first_angle`（度，畫面順時針）、
`first_radius`。**在展開圖上找到缺陷後一定要接這個**，否則現場看不到缺陷在原圖的哪裡。

## shading_correct
平場／陰影校正：打光不均（角落暗、漸暈、側光）時放在取像後、二值化前。`flat_field` 除以白板參考影像資產（同一組光下拍一張均勻白板，
上傳成影像資產，尺寸要與工作解析度相同）；`dark_flat` 再扣暗場；`estimate` 沒有白板時用大核模糊估背景（`blur_sigma` 要比要留的特徵大）。
`target_level` 是白板映到的灰階（0＝白板自己的平均）。校正後固定門檻整個視野都適用；門檻類工具（threshold／blob／pixel_count）誤判在角落時先想到它。

## convert_depth
16-bit／浮點影像轉 8-bit（`shift` 右移保線性、`minmax` 拉滿），或反向。多數工具會自動正規化，只有要控制映射方式時才放。

## rotate_flip
固定角度旋轉／翻轉（相機裝反）。`keep_size=true` 不改尺寸會裁角。

## template_match
範本比對定位：範本圖有兩種給法——**首選** `crop_template` 動作把 ROI 裁成固定影像節點接到 `template_image` 埠（圖片跟著流程走），或 `template` 選既有影像資產；`threshold` 0.6～0.8（NCC 分數），旋轉件給 `angle_range`（±度）與 `angle_step`（5 即可，`subpixel` 預設開會把位置內插到 0.05px、角度內插到步進的 1/10）。角度以畫面順時針為正，與 ROI／找直線一致，可直接餵 shape_align。輸出 `matches` 給 shape_align、`best_x/best_y`；`not_found` 分支接 judge(ng)。兩者都沒有時留空並在 note 提醒使用者補圖。

**多模板**：`templates` 放好幾張固定影像（同一條線上兩種蓋子、同一工件的兩種姿態），每個 match 帶 `label` 說是哪一種，
`counts` 給每種各幾個；重疊的目標只留分數最高的那一個。
**排序** `sort_by`：score（預設）／x／y／xy（閱讀順序，取放最常用）／angle。
**縮放** `scale_x`／`scale_y` 在比對前把模板拉伸（工件成像比教導時大或扁）。
**邊界** `allow_clipped` 找跨在搜尋範圍邊上的工件（分數會低，門檻要放寬）。
**逾時** `timeout_ms` 到了就回目前最好的結果，不讓大角度搜尋拖住產線。
## shape_match
形狀比對定位（幾何比對）：以邊緣**梯度方向**計分，光照變化、部分遮擋、雜亂背景、任意角度都撐得住，是 template_match（NCC）撐不住時的首選
（機械手上下料、多件同時定位）。`model` 是形狀範本資產（用 `POST /vision/assets/shape-model` 從影像資產或試執行影像＋範本區建；
可給 `exclude` 排除會變的印字），`min_score` 0.6～0.8（遮 25% 分數約掉 0.25）、`max_matches`、`angle_start/angle_extent`
（範圍越窄越快）、`scale_min/max`（預設不搜尺度）、`polarity` ignore 找黑白反轉件。輸出 `matches`（與 template_match 同格式）接 shape_align、
`best_x/best_y/best_angle/best_scale/best_score`，`not_found` 接 judge(ng)。沒有形狀資產可填時留空並在 note 提醒先建模。

## shape_align
定位補正：吃 template_match.matches，與 `ref_x/ref_y/ref_angle`（教導時的參考位置）算出 `transform`。試跑一次後把參考位置設成目前匹配位置（前端一鍵帶入）。

## align_offset
對位偏移：把教導姿態與目前姿態的差算成「要修正多少」。`shape_align` 是給 ROI 跟隨用的，
這一顆是**給機構走的**——多了取料點補償與世界／機構座標輸出。
`mode`：point（單點＋角度，最常用）／point_set（2～8 組對應點做剛體解，兩個定位孔就夠）／
grab（教導時的取料點跟著轉，輸出 `abs_x/abs_y/abs_angle` 就是手臂要走的點）／line（線的中點與方向）。
姿態來源與 shape_align 同一套：`matches` 優先，其次 a/b/c 三個數值埠。上游這次沒找到就走 `not_found` 分支，不會丟例外。
選了 `calibration`（手眼標定資產）才會多出 `world_*`；沒選就只給像素。
輸出的 `transform` 與 shape_align 同格式，可以直接接到任何工具的位置修正埠。

## map_points
相機間座標映射：選一份含 `mapping` 區塊的標定資產，把 A 相機座標換成 B 相機座標；`direction=inverse` 會用反矩陣走回來。
輸入可接 `points`、`matches`，或單點 `x`/`y`。`matches` 會保留原本欄位，只更新 `cx`/`cy` 或 `x`/`y`，有 `angle` 時一併轉成另一台相機座標的角度。
沒有 mapping 區塊時工具會失敗並說明要先建立相機映射標定。

## image_fixture
把整張影像轉回教導時的姿態（`fixture_roi` 的另一種做法）：`transform` 接 `shape_align`，輸出的影像給下游所有步驟。
**跟隨區域與跟隨影像二選一**——區域少就用位置修正埠（每個有 ROI 的工具都有 `_transform`，接上去就好），
整條流程都要跟、或教導好的範本要照樣比得到，就在取像之後放一顆 `image_fixture`。
邊緣會空出來（`border` 決定填黑／白／最近的像素）；量測前不要關 `smooth`。定位沒找到時影像原樣傳下去並標 ng。

## fixture_roi
ROI 跟隨：`roi` 填教導時的固定 ROI，`transform` 接 shape_align.transform，輸出 `region` 接量測工具的 `roi` 輸入埠。每個要跟著動的 ROI 一個 fixture_roi。

## region_from_shape
把一個畫好的形狀變成 `region` 輸出（本身不動影像）：畫布上要有第二、第三個區域（排除區、加量的區域）就放它，接進 region_combine。

## region_combine
區域組合（多重 ROI 與排除區）：`base`（基底區域，可畫或接 `base` 埠）＋ `regions`（多條 region 邊）依 `mode` 組成一個 composite 區域——
`subtract` 挖掉孔位／字樣／反光帶／料號區、`union` 把幾塊合成一塊、`intersect` 只留重疊。輸出 `region` 接任何工具的 `roi` 輸入埠
（intensity／histogram／blob／pixel_count／edge_density／color_check／defect_diff／contour_find 全部照遮罩算；矩形類量測工具退化用外框）。
量測區裡有會變的孔或印字時一定要挖掉，否則平均值、粒子數會跟著跳。

## find_circle
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
射線式找圓（精量測）：`roi` 用 `annulus`，環要蓋住圓緣（r_inner ≈ 0.6r、r_outer ≈ 1.4r）；只有一段弧時給 `a0/a1` 起迄角，掃描線只落在扇形內。`edge_select` first/last 決定內緣或外緣（同心環杯件：外徑 last、內徑 first）。ROI 沒對準圓心也沒關係：`refine`（預設開）會從擬合圓心重掃一次。擬合是幾何最小平方（部分弧無偏）。輸出 `cx/cy/r`、`points`（給 calibration）。`not_found` 接 judge(ng)。

## find_rectangle
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
一次找出矩形工件的四條邊：ROI 畫得比工件大一點，卡尺從四邊往內掃，四條線的交點就是四個角。
`polarity` 是「由外往內」的灰階變化，`search` 是往內掃多深（區域的比例，夠碰到邊就好）。
輸出的 `rect` 是**區域**，直接接下游工具的 region 埠，工件落在哪裡就量哪裡。角點依畫面順時針排（左上起）。

## find_quadrilateral
四條線 → 四個角：`a~d` 依序（繞工件一圈）接四個 `find_line` 的 `line`。工件不是矩形時用它，
輸出角點、四條邊長、兩條對角線與面積。相鄰兩邊平行時走 `not_found`。

## find_parallel_lines
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
溝、肋、縫的兩側一次到手：ROI 長邊沿著那一對邊，每把卡尺找一對邊。
`pair_polarity` 說「兩邊之間」是亮的還是暗的，`pair_mode` 選最寬／最窄／最外／最強／最接近預期。
輸出兩條線、`center_line`（中線，後面要量的通常是它）、平均／最窄／最寬寬度與逐把的 `widths`。

## find_lines_multi
區域裡每一條直邊都找出來：Canny 取邊緣點 → RANSAC 擬合最強的一條 → 把它的點拿掉 → 再找下一條。
`min_points` 與 `min_length` 擋掉雜訊，`angle_filter`＋`angle_tolerance` 只留某個方向的線。
**一條有厚度的線會有兩個邊**，所以 `max_lines` 要抓兩倍。比 `hough_lines` 慢但給的是擬合好的線與點數。

## find_circles_matrix
整排的孔／球／墊一次找完：ROI 框住整個陣列，依 `rows`×`cols` 切格子，每格找一個圓。
輸出每個圓心與半徑、`missing`（哪幾格是空的，格子由左上往右下編號）與格距；有缺就走 `not_found`。

## find_line
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
卡尺式找直線：`roi` rect/rotated_rect，短邊方向掃描；輸出 `line`（接 angle／geometry 的 a/b）、`x1..y2`、`angle`。`direction` first/last/strongest 選邊。多用 RANSAC（預設開）抗雜點。

斷續的邊（虛線、被遮住一段）打開 `gap_tolerant`：線的兩端取真的找到邊的範圍；`coverage` 回報幾成的卡尺打到邊。

## caliper
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
量兩條邊的距離：ROI 長邊沿掃描方向、要橫跨兩條邊。`edge_pair` widest 抓最外側對、first_last 抓頭尾、`polarity` 限制邊緣方向。量亮條／暗條寬度給 `pair_polarity`（bright＝暗→亮再亮→暗、dark 相反）；知道大約寬度就填 `expected_width`（挑最接近的一對，旁邊有高對比雜訊邊也不會挑錯）。輸出 `width`（px）。

多候選：`max_results` 大於 1 時，`edges` 會列出前 N 個候選，每筆含掃描方向位置、兩個邊的位置、對比、分數與寬度；
`sort_by=position` 用由近到遠順序，`contrast` 用灰階/px 對比，`score` 則用加權分數排序。單一 `width/edge1_x/...`
永遠取排序後第一筆。
評分：權重全為 0 時分數退回對比；打開權重時，score = `contrast_weight * contrast`
- `position_weight * abs(position - expected_position)`（`expected_position=0` 不用）
- `width_weight * abs(width - expected_width)`（`expected_width=0` 不用）。位置與寬度都是 px；對比是灰階/px。

## edge_trend
整條邊趨勢：直接沿參考直線或圓放 `caliper_series`，不是重新掃描一套。上游 `line`／`circle` 優先於 ROI；沒有幾何輸入時，
ROI 用 rect/rotated_rect 表示直線邊、circle/annulus 表示圓邊。`calipers` 決定趨勢點數，`search` 是每把卡尺的法向搜尋距離，
`caliper_width` 是沿邊平均寬度，`mode=single/pair` 決定找單邊或邊緣對。
輸出 `offsets` 是每把卡尺相對基線的偏移，可接 `profile_defect.values`；`points` 是命中點，可接 `profile_defect.points`；
`missing` 保留打空的卡尺索引。`baseline=reference` 看相對教導幾何的偏移，`fit` 會用命中點擬合直線／圓後看殘差，
`median` 用滑動中位數看局部突變。`max_deviation` 是 px 門檻，超過走 `ng` 分支；overlay 會把超標命中點標紅。

## path_extract
沿任意折線或多邊形輪廓取樣。`equal_interval` 只把路徑轉成等距點集與每點切線角；`edge_search` 會在每個取樣點的法線方向放一把卡尺，輸出找到的邊緣點、相對路徑的 offsets、pair mode 的 widths，以及 missing 索引。

分工：直線邊要先用 `find_line`，圓或圓弧要用 `find_circle`/`fit_arc`；只有沖壓外緣、FPC 邊、膠道等任意折線或多邊形路徑，才用 `path_extract`。上游 `points` 會優先於畫布 ROI；polygon 預設封閉、line 與 wired points 預設開放，可用 `closed` 覆寫。`search` 是法線方向半徑，法線沿切線順時針轉 90 度。

`path_extract.points` 可直接接 `profile_defect.points` 或其他點集量測；若要做整條邊缺陷分段，通常用 `path_extract.offsets` 當序列、`path_extract.points` 當對應位置，再交給缺陷分段工具。

## wall_thickness
沿壁放多條卡尺量厚度：`roi` 用 **line 橫切壁**（最直觀）或矩形長邊沿壁。輸出 `thickness`（平均）、min/max。「沒有找到成對的邊緣」通常是掃描方向錯或 band 太窄。

## circular_caliper
圓形卡尺：`roi` 用 `annulus` 蓋住圓緣（帶 a0/a1 只量扇形），沿圓周放 `caliper_count` 把徑向卡尺（72～360），每把切向平均
`caliper_width` 個樣本降噪，`polarity`（由內往外的灰階變化）／`edge_select` first（內緣）last（外緣）／`edge_threshold` 與 find_circle 同義。
輸出 `radii`（每把一項，找不到為 null）、`all_points`（與 radii 對齊，缺的為 null）、`points`（找到的點，可接 fit_arc）、
`mean_r/min_r/max_r/runout`（徑向跳動＝max−min）、`missing_count`。離群半徑只從統計剔除、不從 radii 拿掉（缺口本身就是離群）。
崩邊／毛刺／缺口接 profile_defect；只要直徑用 find_circle 就好。

## profile_defect
序列缺陷：`values` 接 circular_caliper.radii（或 line_profile 剖面），`points` 接 all_points 讓缺陷畫回原圖圓周（紅弧）。
`baseline` fit_circle（圓周用，需 points）／median（滑動中位數，`window`）／fit_line／mean；`threshold`（絕對值或 `threshold_mode=sigma` 的倍數）、
`min_width`（連續點數，擋單點雜訊）、`direction` inward（缺口、凹陷）／outward（毛刺、凸起）／both、`max_defects`（0＝有就 NG）、
`wrap`（圓周開、線剖面關）。**卡尺打空（null）也算缺陷**（`missing_as_defect`），大缺口最容易漏判。輸出 `count`／`defects`
（start、end、peak_index、peak_deviation、direction、missing）／`max_deviation`，分支 ok／defect。

## fit_arc
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
只有一段弧（缺口、扇形、R 角）時用，`roi` 用 annulus 加 `a0/a1` 起迄角（掃描線只落在扇形內），或多邊形楔形。擬合是 Taubin＋幾何精修（30°～90° 的短弧也無偏），`refine` 預設開會從擬合圓心重掃。輸出 radius、cx/cy、residual_rms、start_angle/end_angle。

## fit_ellipse
橢圓擬合看圓度：`roundness` 越接近 1 越圓；也能量斜拍的圓。Direct 擬合＋重掃，只看得到一段弧（杯口被遮一半）也能擬合。

## hough_circles
一次抓很多圓（計數用，精度普通）：`min_radius/max_radius` 夾住目標半徑、`min_dist` ≥ 直徑、`param2` 15～30（越低越敏感）。輸出 `circles`（list）與 `count`。

## hough_lines
抓線段清單：先 canny（`canny_low/high`），`threshold` 投票數、`min_length` 擋短線。輸出 `lines`（list，可接 count_list）。

## chamfer_angle
倒角／斜切角：ROI 長邊沿輪廓走向、同時包住主邊與倒角段；輸出 `angle_deg`、`length`、交點。

## angle
兩條線夾角：`a/b` 接 find_line.line（或八個端點數值）。`range` 0_90 折成銳角、0_180 保留方向。

## distance
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
兩個東西的距離：`ax/ay/bx/by` 接 find_circle.cx/cy 等，或直接把 `a`／`b` 接線（`{x1,y1,x2,y2}`）或圓（`{cx,cy,r}`）。
`mode` 除了直線／X／Y 之外還有 **nearest（邊到邊）／farthest／centers**——**圖面標孔到孔多半是邊到邊，不是圓心距**。
輸出 `distance/dx/dy`（px）。

## geometry
選填 `calibration` 資產；選了標定就多出原始埠名加 `_world` 的物理量與 `unit`，機構 `robot.matrix` 優先於 `world.matrix`；未選時像素輸出不變。長度採量測位置的面積等效比例，非等向縮放與透視下不是沿線積分長度。
圖面標了、影像上看不到的幾何都在這裡：`intersect`（兩線交點，順便給夾角）、`point_line`／`project`、`midpoint`、
`line_2pts`、`parallel`（給 B 就過那個點，否則用 `offset` 平移）、`perpendicular`（B 是要通過的點）、`perp_bisector`、
`median`（兩邊的中線）、`bisector`（角平分線）、`circle_3pts`（A/B/C 三點）、`rotate`（繞 B 轉 `angle`，順時針為正）。
`a/b/c` 接 line、point 或 circle（any 型）；輸出多了 **`line` 與 `circle`**，可以直接接給下一個 geometry 或 distance。
裁切後要把子圖座標還原回原圖，用 `mode="offset"`：把 `crop.offset_x`／`crop.offset_y` 接到 geometry 的同名輸入埠，`points` 或 `matches` 接下游量到的點集／比對結果；`sign="add"` 加回原圖座標，`sign="subtract"` 反向扣回子圖座標。沒接 offset 埠時才用參數值。
畫布上畫的基準線用 `region_from_shape` 的 `line`／`circle`／`point` 輸出接進來。

## points_merge
把幾個步驟的點併成一組再一次擬合（四把卡尺量同一條邊、整排孔的圓心）：`a~d` 各吃一個點或一串點，
輸出 `points`／`count`／`cx`／`cy`。接 `find_line`／`fit_arc` 的 points 埠。

## concentricity
兩圓同心度：a/b 接 find_circle 的 cx/cy/r，`max_deviation` 填圖面同心度公差的一半。輸出 in_spec 給 bool_logic。

## contour_find
輪廓萃取：二值影像（灰階自動二值化，`polarity` 選亮／暗物件）取輪廓，`mode` external（只要外輪廓，最常用）／list（含孔洞）／
ccomp／tree。`min_area`（像素數）先擋雜訊。輸出 `contours`（全圖座標）、`count`、`areas`／`centers`（每條一項）與 `first_*`。
接 contour_filter／contour_geometry／contour_match；只要粒子數與面積用 blob 就好，要「拿輪廓本身來算」才用這一組。

## contour_filter
輪廓篩選：面積／周長／凸度（面積÷凸包面積）／長寬比（最小外接矩形）／`roi` 內（重心落在區域內）過濾，`sort_by` 排序後
`max_count` 只留前 N 條（`max_count=1`＋面積排序＝只留工件本體）。輸出篩後 `contours`、`count`、`rejected`。

## contour_geometry
輪廓幾何：每條輪廓算面積（像素數）、周長、重心、最小外接矩形（含角度）、最小外接圓、凸包面積／凸度、**凸缺陷**
（`defect_depth` 以上的凹陷：缺角、崩邊、異物咬入）、圓形度、Hu 矩。list 埠每條一項、`first_*` 為第一條、
`total_defects`／`max_defect_depth` 為全部。崩邊檢測：contour_find → contour_filter(max_count=1) → contour_geometry(defect_depth=…) →
`if_number(first_defects eq 0)`。

## contour_match
輪廓比對：以 Hu 矩距離比對外形（不受位置、縮放、旋轉影響）。範本是 `reference` 埠（另一個 contour_find 的第一條）或
`template` 影像資產（取二值化後最大形狀）；`max_distance` 0.05～0.3（同形狀接近 0）。輸出 `distance`（最佳）、`distances`、
`match_flag`／`match_count`、`matched`／`best` contours，分支 match／no_match。用來分料、抓錯料或嚴重變形；細小缺角用 contour_geometry 的凸缺陷。

## coordinate
自訂座標系（measure）：`mode=point_angle` 用 `point` 埠或 `origin_x/origin_y` 參數作原點，`angle` 埠或 `axis_angle`（預設 0）作 X 軸方向。
`mode=two_points` 用 `point`（也可填原點參數）與 `point2`（X 軸上的另一點）；`mode=line` 用 `line` 起點作原點、起點到終點作 X 軸。
輸出 `frame={"origin":[x,y],"angle":deg,"scale":1.0}`、`origin_x/origin_y/angle`，成功走 `found`，缺值或重合兩點走 `not_found`（ng），不使用舊座標。
角度正值＝畫面順時針；overlay 顯示原點與兩軸。`origin_x/origin_y/axis_angle` 可現場教導；接埠優先於參數，原點參數沒有預設值。

## to_world
像素→真實世界座標（mm、um、in 或機械手座標），`calibration` 改為選填。保留既有 world 映射優先行為，資產僅有 robot 時也可使用。
新增選填 `frame` 輸入：先平移到原點、旋轉 −angle、除以 scale，再套標定；標定需對應該座標系。未選標定只回座標系內的像素值，連 frame 也沒有則原樣回座標。
`mode=to_world` 為預設；`mode=to_pixel` 將輸入 x/y/points 當世界（或座標系）座標，反算標定與 frame 回全圖像素（透視也適用）。輸出沿用 `x/y/points_world`，反向時語意為像素，`value/angle` 亦依反向映射換算。`decimals` 只控制顯示文字，不截斷輸出精度。相容既有流程：正向只接長度或角度且無座標時，仍需標定或 frame。
`points` 進（或 `x`／`y` 數值埠接 find_circle.cx/cy、shape_match.best_x/best_y）→ `points_world`／`x`／`y` 出（第一點）；`value`（像素長度）→ `length`；`angle`（影像角度）→ `angle`（世界角度，鏡像安裝也對）。
要把位置交給機械手抓取時用它，接在 template_match／find_circle 的中心座標後面，再接 output 具名輸出。
量測工具已選 calibration 時可直接讀 *_world，不必再接長度換算。`fit_arc` 的半徑為 `radius_world`；`find_parallel_lines` 的寬度為 `distance_world`；`geometry` 的線段長度／半徑沿用 `distance_world`（circle_3pts），世界夾角由兩個方向的差值計算，無角度的模式輸出 `angle_world=None`。

## calibration
像素→mm：`pixel_size` 模式填 `pixel_size_mm`（0.05 mm/px 之類）；`known_distance` 用 px_distance/real_mm；`asset` 模式直接吃標定資產（站台重新標定後所有流程一起更新，優先用這個）。`value` 進、`mm` 出，放在 tolerance_judge 前。

## tolerance_judge
標稱值±公差判定：`nominal/upper_tol/lower_tol/unit/spec_source/name`。輸出 `in_spec`（bool，接 bool_logic 或 judge by_input）、`pass/fail` 分支、`deviation`。

## in_range
數值落在 [low, high] → `inside`／`outside` 分支。簡單守門用它；有標稱值用 tolerance_judge。

## if_number
數值比較（eq/ne/gt/ge/lt/le）→ `true/false` 分支。計數 == N 就是它。

## switch
一個值一條路（多料號、多等級）：`value` 接條碼／文字辨識／料號變數，`cases` 一行一個案例，
節點就長出對應數量的分支埠（`case_1`…），都不符走 `default`。`match`＝exact／contains／prefix／regex／number
（number 的一行可以是 `12` 或 `10-20`）。**一次只會走一條路**（第一個相符的），要多條同時走請並排放兩個 switch。

## string_match
文字在不在允許清單裡：`text` 接條碼或文字辨識，`list` 一行一個，走 `found`／`not_found`，
輸出 `index`／`matched`。`invert` 用在「這些字不准出現」的黑名單。單一字串比對也用它（清單只寫一行）。

## bool_logic
多個 bool 彙總（and/or/not）：`values` 埠可接多條邊。輸出 `result` 給 judge(by_input)。

## formula
數值算式：`expression` 用 a/b/c 變數（`a*2`、`(a+b)/2`）。輸出 `value`。

## count_list
清單長度（hough_lines.lines、blob.blobs 等）→ `count`。

## boxes_merge
框清單後處理：`matches` 接 template_match／register_detect／偵測類輸出的框。`mode=iou` 用重疊比例合併同一物件的重複框；
`mode=centre_distance` 用中心距離合併固定間距附近的重複框。`same_label_only=true` 只合併同類別。`keep` 決定 score／label 等 metadata
取自分數最高、面積最大或最早出現的框；輸出框本身會擴成整組的外接框。輸出 `matches`、`count`。

## boxes_filter
框清單篩選：`matches` 接框，依 `min/max_width`、`min/max_height`、`min/max_area`、`min/max_aspect`、`min/max_score`、
`labels` 與 `roi` 篩掉不合格框。`roi_mode=inside` 留中心在區域內的框，`outside` 則留區域外。輸出 `matches`、`count`、`removed`。
這不是輪廓篩選；輪廓請用 `contour_filter`。

## array_correct
規則陣列補點：點膠、插件、針腳這類應排成 `rows × cols` 的框清單，接到 `matches` 後用找到的中心分群出每列／每欄位置，
再回報缺格。`tolerance` 小於 1 時是 pitch 比例，大於等於 1 時是像素距離。輸出 `matches` 會包含補上的框（`filled=true`、
`grid_row/grid_col/grid_index`），`missing` 列出缺格索引與推估中心，並以 `ok/ng` 分支判斷完整或缺件。

## list_sort
排序清單：`matches` 可依 `x`、`y`、`xy`（閱讀順序：先分列再由左到右）、`score`、`label` 排序；`values` 只能用 `by=value`。
輸出排序後的 `matches` 或 `values`、`count`、`first`。要在取第一個、上位機輸出、機械手補正前固定順序時用它。

## judge
決定 run 的 OK/NG：`verdict` ok/ng 放在分支下游、`by_input` 收 bool。`label` 寫 NG 原因（上位機看得到）。每條互斥分支各接一個。

## variable_get / variable_set
跨執行、跨流程的狀態：累計計數、上一片的結果、PLC 用 `SET` 送來的料號。`scope` 選 `flow`（這條流程）或 `station`（整站共用）。
`variable_set` 的 `mode`：set 存值、add 累加（沒接輸入＝計數 +1）、max／min 留極值；`variable_get` 沒存過就用 `default`
（數字是數字、true/false 是布林）。試執行與批次測試在沙箱裡，不會動到產線的值。整合端用 `GET/PUT /flows/{id}/variables`
或 TCP `VARS`／`SET` 讀寫。要「跟上一片比」就把影像存進變數（只留記憶體）。

## parse_message
`format_text` 的反向：把一段文字或位元組拆成具名值。輸入 `text` 接條碼的 `text`、文字辨識的 `text`，或觸發帶進來的字串。
`mode` 三種——`delimiter`（`separator` 分段，最常用）、`regex`（`pattern` 的具名群組填同名欄位，否則依序填）、
`fixed`（設備送定長二進位時用位元組範圍）。`fields` 一行一個欄位：`lot`／`slot:int`／`qty:int:3`（第 3 段，0 起算）／
`w:float:2-5:DCBA`（位元組 2~5，位元組順序相反）／`w:int*0.01`（設備送 1234 代表 12.34）。
每個欄位都進具名輸出（`publish`），所以後面可以直接 `compare_number`／`ocv_verify` 判斷，或 `format_text` 取 `{lot}` 回送。
欄位取不到值走 `not_matched` 分支（缺值是 None，不會讓流程失敗）；要當成不合格才把 `on_missing` 設成 fail。

## format_text
把結果排成一行文字給讀不了 JSON 的設備：`template` 用 `{名字}` 取值（judge、先前的具名輸出、觸發帶進來的引數如 lot／sn、
本節點輸入 a~d，另有 run_id／station），`{width:.2f}` 控制小數，`\\r\\n` 會變成真的控制字元；`ending` 補行尾、`name` 決定
具名輸出的名字。設備端用 `RUN <flow> fmt=<name>`（TCP）或 `format=<name>`（HTTP）就拿到純文字。放在 judge 與其他 output 之後。

## write_log
每片要留下 CSV/TXT 紀錄時使用，例如品保要 `judge,width,lot,run_id`。`fields` 一行一欄，純欄位名依 `format_text` 的取值順序讀值，也可寫 `{width:.2f}`；`filename` 同樣可用 `{station}`、`{date}`、`{lot}`、`{run_id:.8}`。
`path` 是 `DATA_DIR/file_outputs` 下的相對子資料夾，`daily_folder` 會再加 yyyyMMdd，`rotate_mb`／`rotate_rows` 避免單檔過大。工具只排入背景佇列，preview 與批次沙盒不寫檔；佇列滿時丟棄當次輸出並讓 run 繼續。
文字紀錄用 `write_log`；即時回覆上位機仍用 `format_text` 搭配 HTTP/TCP，影像追溯用 `save_image`，統計頁回看用流程影像封存。

## trigger_flow
一條流程跑完要叫另一條流程時使用，例如前段定位後叫量測流程，或 NG 分支叫複檢流程。`target_flow_id` 選目標流程；`mode=async` 只排隊並輸出 `run_id`，父流程繼續；`mode=sync` 等子流程結果並輸出 `run_id/judge/ok`，依子流程結果走 ok／ng／failed 分支。
同步模式會先檢查 runner 容量與執行緒池，沒有明確空 worker 就失敗，避免父流程佔著 worker 等子流程、子流程又排不到 worker 的死結。自我觸發與 A→B→A 會用觸發鏈擋下。preview、批次、AI 試跑與 bench 是沙箱，只回 `Would trigger flow ...`，不真的排隊。
可勾選是否傳遞目前具名輸出與影像；影像只用快取 ref 傳遞，不把 ndarray 放進 context。

## call_flow
同行程子流程：把重複的一段檢測抽成另一條流程，父流程用 `target_flow_id` 呼叫。它不進 runner 佇列、不產生新的 FlowRun、不發 SSE、不累計統計；只在目前 run 的同一條執行緒內直呼 engine。輸出 `judge/ok/duration_ms/outputs`，並把子流程具名輸出加上 `prefix` 併回父流程。
與 `trigger_flow` 共用觸發鏈，所以 A→call→A、A→trigger→B→call→A 都會被擋；另有巢狀深度上限。逾時沿用父流程剩餘 deadline。

## for_each
逐項對 `matches`、`regions` 或多張 `images` 呼叫一條子流程。region 會先裁成子影像再執行，子圖座標的 points/matches 與常見 x/y 輸出會用 `geometry` 的 offset 規則加回原圖位移。輸出 `count/ok_count/ng_count/items/all_ok`，有 `max_items` 上限；`on_error` 可選 continue 或 stop。

## tile
純幾何切片工具：依 `rows/cols/overlap` 產生矩形 `regions` 與 `count`，不處理像素。可直接接 `for_each`，讓大圖逐塊跑同一段子流程。

## output
具名輸出：`name` 英文鍵名，`value` 埠接數值／字串／影像。上位機從 `outputs[name]` 拿。

## draw_result
把所有 overlay 畫到影像上輸出（總覽／存檔用）；輸入接原圖。

## blob
粒子分析：內建二值化（`threshold_method` otsu/fixed/hysteresis/soft、`polarity` bright/dark；非矩形 ROI 的 Otsu 只看遮罩內）或接已二值化的影像（fixed+128+bright）。`area` 是像素數（1 像素粒子就是 1）；`soft` 時 `area` 是權重和，可能是小數。`min_area/max_area/min_circularity` 篩選；黏連粒子 `separate=true`（分水嶺，種子視窗依 min_area 推算的半徑，大小粒子混在一起也切得開）。輸出 `count`、`blobs`、`centers`、`mask`、`found/not_found`（`min_count` 決定）。

亮塊裡有更亮核心、邊界灰階慢慢變淡、單一門檻要嘛只抓核心要嘛吃到旁邊雜訊時，用 `threshold_method=hysteresis`：`threshold` 是高門檻種子，`threshold_low` 是往外長的低門檻，只保留碰得到種子的低門檻連通區。邊界本來就模糊、希望面積不要被一個硬門檻跳動影響時，用 `threshold_method=soft`，`threshold` 放在過渡中心，`soft_width` 放灰階過渡寬度。

每筆 `blobs` 含 `bbox`、`perimeter`、`orientation`、`elongation`、`inscribed_rect`。`inscribed_rect` 是最大軸對齊內接矩形，用來判斷孔或區域能不能塞下指定矩形；需要按閱讀順序取點陣時 `sort_by=xy`。

## blob_label
標籤圖粒子分析：`labels` 接單通道整數標籤圖，`classes` 一行一個 `編號:名稱`，`ignore_label` 預設 0 當背景。最直接接 `dl_segment.class_map`，會保留每個像素的類別編號；若接 `ai_segment.mask`，它是 0/255 聯合遮罩，請把 `classes` 寫成 `255:part`，只能當單一類別使用。逐類別做連通元件，輸出帶 `label/class_id` 的 `blobs`、每類 `counts`、總 `count`、`contours`，`min_count/max_count_ok` 決定 `ok/ng`。

## pixel_count
數 ≥ threshold 的像素：接 color_range／threshold 輸出，`min_count/max_count` 決定 ok/ng。

## dark_ratio
暗部佔比守門：`threshold` 以下的比例 > `max_ratio` → fail。

## intensity
ROI 灰階統計（mean/std/min/max/median）。亮度守門、簡單有無。

## histogram
直方圖與 Otsu 門檻／峰值；教學與曝光診斷。

## sharpness
用來監看鏡頭失焦、震動或曝光時間過長造成的模糊；它輸出 `score`，並可用 `min_score` / `max_score` 直接走 `ok` / `ng` 分支。要做產線攔截時，先在良品清楚影像上取穩定分數，再把 `min_score` 設在良品低分側以下一點。`max_score` 通常不設，只有在過度銳化或雜訊會把分數拉高時才用。

`method=laplacian` 是最通用的預設，對細邊與紋理最敏感；`gradient` 適合 ROI 裡有穩定邊緣時使用，分數通常較平順；`autocorrelation` 用一、二像素位移的相關性落差，對隨機雜訊比較不敏感，但因為要多次掃描位移陣列，會比單次卷積型方法慢。

`normalize=true` 時分數已用 ROI 內灰階變異數縮放，比較適合跨 ROI 大小、照明強弱或對比不同的影像比較。雜訊會讓清晰度分數虛高，尤其是光量不足、相機增益拉高時；懷疑這種情況就開 `noise_estimate`，同時監看 `noise`，不要只靠 `score` 判定焦距。

分工上，`sharpness` 是影像品質監控工具；`caliper`、`find_line`、`find_circle`、`line_profile` 仍負責定位、找邊或量測。若要知道某條邊的位置或寬度，用那些工具；若要判斷整個 ROI 是否清楚、是否應先攔下不量，才用 `sharpness`。

## line_profile
沿線／折線取灰階剖面：量溝深、找邊緣位置、看印刷條紋。`roi` 用 line/polyline。

## edge_density
Canny 邊緣像素比例 > `max_ratio` → ng：畫面異常（髒污、雜訊、對焦跑掉）守門。

## color_check
ROI 平均色與目標色（`color` 十六進位）距離 ≤ `tolerance` → match。`space` rgb/hsv（hsv 的色相差依飽和度加權，灰／白／黑目標不會被色相亂數影響）；目標色用使用者 ROI 的主色最穩。

## color_stats
ROI 顏色統計輸出（RGB/HSV 平均、hex）給上位機記錄或接 if_number。

## edge_defect
**整條邊一次檢查完**（缺口、毛刺、崩掉、錯位、寬度不對都在這一顆）：沿參考邊佈一排卡尺，
偏離理想邊的那幾段就是缺陷，每個都帶種類、外框、沿邊長度與面積。
- 參考邊：畫矩形＝直邊（長邊沿著邊）、畫圓／圓環＝圓邊；**更好的做法是接上游的 `line`／`circle`**
  （`find_line.line`、`find_circle.circle`、`fit_arc.circle`），這樣理想邊是這一顆工件實際的邊，工件會動也不怕。
- 種類：`dislocation`（一整段偏進去或偏出來，看 `threshold` 與 `direction`）、`fracture`（連續幾把找不到邊＝那一段沒了，
  `fracture_run`）、`step`（相鄰兩處忽然接不上，`step_threshold`）、`width`（成對模式的 `width_min`／`width_max`）。
- `mode="pair"` 量的是兩邊之間的寬度（肋、溝、縫），基線一律取中位數寬度。
- 判定接 `count`（幾個）或 `max_size`／`max_deviation`（最嚴重的那個）；`max_defects` 是可以接受幾個。
- 與 `circular_caliper`＋`profile_defect` 的分工：那條路是「半徑序列」拿去別的地方用（畫趨勢、算跳動），
  這一顆是「就是要找缺陷並分類」。範本畫廊兩種都有（圓周崩邊／邊緣缺陷），同一組樣本可以對照。

## edge_model_defect
任意輪廓的缺口／毛刺／崩角：把良品外輪廓存成 `model` JSON（`version`、`image_size`、`closed`、`points`），
每次沿模型等距佈法向卡尺，輸出 `points`、`deviations`、`missing` 與分段後的 `defects`。閉合模型的正偏移是向外，
所以 `direction=inward` 只抓少料／缺口，`direction=outward` 只抓多料／毛刺；連續打空由 `fracture_run` 判 fracture。
模型為空但有 `reference` 固定影像時，會用第一張良品影像本次自動教導輪廓。

分工：直線或圓弧邊用 `edge_defect`（可接 `find_line.line`／`find_circle.circle`，幾何更簡單也更快）；沖壓件、
墊片、齒形、FPC 外形這種任意輪廓用 `edge_model_defect`；已經有序列要自行分段才用 `profile_defect`；
整面紋理、印刷、髒污或未知位置差異用 `defect_diff`／`defect_stat`，不要把它們拿來量輪廓偏移。

## defect_diff
良品差異比對：`template` 良品資產（與 ROI 同尺寸），`align=phase` 補位移，`threshold`（灰階差）與 `min_area` 決定靈敏度，`border` 忽略對齊邊界假差異。輸出 `ok/defect` 分支、`count/total_area`、`defect_mask`。

## defect_stat
統計良品比對：`model` 是統計範本資產（≥ 10 張良品用 `POST /vision/assets/stat-template` 或 `manage.py stat_template` 建的 npz，
每像素有自己的 mean／std）；`sigma`（幾倍 σ 算缺陷，先 3～4）、`min_sigma_floor`（std 下限，均勻區才不會炸假缺陷）、`min_area`、
`direction` darker／brighter／both。`roi` 要與建模時同一個區域（尺寸不同會報錯）。比 defect_diff 穩：打光波動、材質紋理、位置微移
都在各像素的正常範圍內，門檻不必放鬆。有多張良品時優先用它；只有一張良品才用 defect_diff。輸出 count／total_area／max_sigma／
defect_mask／deviation（1σ＝32 灰階的偏離影像）、分支 ok／defect。

## barcode
一維碼／QR／Data Matrix／Aztec／PDF417（zxing-cpp；沒裝時退回 QR＋EAN/UPC）：`roi` 縮小範圍加速；`types` all／qr／2d／1d；`expected` 填預期內容可直接判定。輸出 `first`（字串）、`count`、`found/not_found`、`codes`（type／points）。

## barcode_grade
條碼品質分級（驗證器等級）：`roi` 框住符號與靜區（teach）、`standard` iso15415（2D：Data Matrix／QR）／iso15416（1D，線性碼自動走這條）／aim_dpm
（金屬直接打標：cell_contrast／cell_modulation／minimum_reflectance 取代 15415 的對比與調變，`dpm_filter` 可先中值濾波）、`symbology` 限定碼制、
`min_grade`（teach，預設 C）。輸出 `grade`（A～F）、`grade_value`（4.0～0）、`params`（每分項 value／grade／note）、`text`、`symbology`＋pass／fail。
分項：decode、symbol_contrast、modulation、fixed_pattern_damage、axial_nonuniformity、grid_nonuniformity、unused_error_correction（1D：min_reflectance、
edge_contrast、defects、decodability）。總評＝最低分（1D 是 10 條掃描線平均）。detail 有 fixed_pattern 各段損傷與 1D 每條掃描線，被判 C 的原因看 params。
客戶規格寫「grade ≥ B」就把 min_grade 設 B；純讀內容用 barcode 就好，分級比讀慢（DM 240² 約 5 ms、1D 10 條掃描 15 ms）。

## ocr_read
文字辨識（讀日期碼、批號、料號）：`roi` 框一行字，`charset` 依內容限制字元集（日期碼 `digits`、料號 `upper`；`custom` 自訂）——
限制字元集準確率大幅提升；`polarity` 暗字亮底／亮字暗底；`min_confidence` 逐字信心門檻（低於就 not_found）。`mode=detect`
先偵測多行再逐行讀（多行標籤）。點陣噴印、DPM 打標這種通用模型會爛的字體：`model` 選教導過的字型（POST /vision/ocr/fonts/{name}/samples
存樣本、…/train 出模型），走切分＋逐字分類（`segmentation` projection／components／fixed＋`char_count`）。輸出 `text`、`items`
（每行 {text, box, confidence, chars:[{ch, conf, box}]}）、`confidence`（全體最小）；`pattern` 是位置樣板（`N` 數字、`A` 英文字母、
`X` 任意、其他字元必須完全相同），不符就走 `not_found/ng`；`confusables` 一行一個 `從:到`，只在替換後符合該位置樣板時才修正
（如 `O:0` 只會在該位要求 `N` 時套用）。`text` 永遠是原始辨識字串，`corrected` 是修正後字串，`pattern_ok` 是樣板結果，
`corrections` 是替換明細。接 ocv_verify 做比對時，若要用修正值就接 `corrected`。通用模型要先安裝
（manage.py ocr_models --install），沒有時走教導字型仍可用。

## ocv_verify
字串驗證：`text` 接 ocr_read.text、`items` 也接上（逐字信心與紅框）。`expected` 支援 `?`（任一字）與 `#`（任一數字），
`expected_source=input` 從 `expected` 埠拿 MES 下發的批號；`mode` exact／contains／regex；`min_char_confidence` 字對但信心不足也算 NG。
輸出 `match`、`actual`、`fail_index`（第一個不符的字元，−1＝全符），分支 pass／fail。

## text_presence
文字有無（筆畫密度，不是 OCR）：`roi` 框住字區，`polarity` dark/bright，`min_ratio/max_ratio` 決定 present。

## save_image
把影像排入背景檔案輸出佇列；AI 不生成，需要時提醒使用者手動加。`filename` 可用與 `format_text` 相同的 `{}` 樣板，`daily_folder` 加 yyyyMMdd 子資料夾，JPEG 用 `jpeg_quality` 控制品質；`condition` 可選 all/ok/ng，舊的 `only_ng` 等同 NG only。
此工具是使用者自訂的影像輸出，適合每片追溯到指定資料夾；流程的影像封存是統計頁回看用，依封存政策保存來源／結果圖，兩者分工不同。

## send_image
整合用（使用者要求「把影像傳給上位機」「NG 圖送到 MES」時才加）：把該步驟的影像推給 tcp_image 連線（JPEG／PNG／raw），
表頭帶 run_id、判定與具名輸出；only_ng=true 只送 NG；失敗預設降級不讓 run 失敗。放在流程尾端、判定之後，影像接想送的那一步的輸出。

## write_modbus / read_modbus
整合用（AI 不主動生成，使用者要求「把結果寫給設備」「從 Modbus 讀料號」時才加）：write_modbus 依對映表把判定或具名輸出寫到連線；
read_modbus 從連線讀線圈與暫存器（主站連線讀設備、從站連線讀對方主站寫進平台的值），輸出 values／value／ok，publish=true 才進具名輸出。
兩者都要先在「外部整合 ▸ Modbus 主站／從站」頁建立連線，以名稱引用；失敗預設降級不讓 run 失敗。

## note
不是工具：畫布便利貼（type=note、不接邊），寫流程說明或調機備註。

## ai_detect
神經網路物件偵測（原生 torch 推論，GPU 自動使用）：`model` 選教導頁訓練的 .pt 資產，沒選時用 `model_name` 官方底模（`yolo11n.pt`，COCO 80 類，第一次自動下載）。`conf` 是主要調機參數、`iou` NMS、`filter_labels` 只留某些類別、`min_count/max_count_ok` 決定 ok/ng。輸出 `detections/matches`（x,y,w,h,cx,cy,label,score）、`count`、`labels`；`found/not_found` 分支。要客製類別請先在「深度學習教導」用「物件偵測（YOLO）」訓練。

## ai_segment
實例分割網路：同 ai_detect 的模型與門檻參數，另有 `min_area` 濾小實例。輸出 `count`、`matches`（含 area）、`mask`（聯合遮罩，可接 blob／pixel_count）、`contours`（可接 geometry／量測）、`labels`。底模 `yolo11n-seg.pt`；自訂類別用「實例分割（YOLO-seg）」訓練。

## ai_classify
分類網路影像分類：`imgsz` 224；`threshold` 分數門檻、`pass_labels` 合格類別、`top_k`。輸出 `label/score/index/top`，`pass/fail` 分支。底模 `yolo11n-cls.pt` 是 ImageNet 類別，實務上必用「影像分類（YOLO-cls）」訓練自己的類別。

## ai_pose
姿態網路關鍵點：輸出每個物件的 `keypoints`（[x,y,conf]×N，COCO 人體 17 點）與 `matches` 框；`kpt_conf` 只影響顯示。適合姿勢／位置檢查、人員闖入。平台目前不提供關鍵點標記訓練，需用官方或自備 pose 權重。

## ai_obb
旋轉框網路：輸出 `matches`（cx, cy, w, h, angle°, points 四角）、`contours`（四角輪廓）；適合傾斜擺放的工件計數／定位，角度可接 formula／tolerance_judge 做方向檢查。底模 `yolo11n-obb.pt`（DOTA 航拍類別）僅供試用，自訂類別用「旋轉框偵測（YOLO-obb）」訓練（polygon 標記自動取最小外接旋轉矩形）。

## dl_retrieval
影像類別會一直增加時優先用這個：先把已標記圖片建成 reference library，之後新增類別只要加參考圖，不需要重訓。
工具參數 `model` 必填，`roi` 可限制比對範圍，`topk` 是投票數，`min_similarity` 低於門檻會走 `not_matched`（status=`ng`，不要當錯誤），`expected` 填了才把結果轉成 ok/ng 判定。
輸出 `label/similarity/confidence/topk/ok`；`topk` 每筆有 label、similarity、index。遇到缺 model 或庫壞掉要回 ToolError。
不要把它改寫成傳統分類模型流程；需求核心是「加圖即可加類別」。

## dl_anomaly
只教良品、找未知缺陷用此工具；只有少量目標裁切圖且要定位或計數時，改用 register_detect。
只教良品的異常檢測：`model` 是教導頁用「Anomaly detection (good parts only)」訓練的模型（只要 20～50 張良品、不用標記）；
`threshold` 0＝用模型自帶的自動門檻（良品分數 mean + kσ），良品被誤判就調高；`min_area` 擋雜訊；`roi` 檢測區（會縮放到模型輸入尺寸，
別框太大）；`device` auto／cpu／cuda。輸出 `score`（最大異常分數）、`count`／`total_area`、`score_map`（熱圖：門檻映到中灰、2 倍門檻飽和，
現場調門檻看它）、`mask`、`regions`，分支 ok／defect。沒有壞品樣本、缺陷型態不固定（刮痕、凹陷、缺料、異物）時優先用它；
有明確類別且壞品夠多再考慮 ai_*／dl_segment。

## register_detect
零訓練註冊式檢測：已有少量（建議少於十張）目標裁切圖，要找出所有相似零件、計數或判有無時用它，不需建立訓練專案。
`registrations` 是固定影像描述子清單，每張含一個目標與少許背景；`negatives` 放不該計入的相似物。
`roi` 可用矩形／旋轉矩形；`scales` 如 `0.8,1.0,1.25`；`angle_range` 和 `angle_step` 其中一個為 0 就不轉。
`min_similarity` 是主要教導門檻；`max_count` 限制回傳數，須大於預期實際數量以免漏報超量；`nms_overlap` 去重；
`min_size/max_size` 限制框的兩邊長（px，0 不限）。`mode=detect` 分支 found／not_found；`count` 用含端點的
`min_count/max_count_ok` 回 ok／ng；`presence` 用 `expected=present/absent` 回 ok／ng，無物件且預期 absent 時是 OK。
輸出 `matches`（與 template_match 相同的 x,y,cx,cy,w,h,angle,score,label；label 是註冊圖名稱）、`count`、`best_score`、
`best_x/best_y`、`present`；座標皆為輸入影像全圖。未找到時 best_score=0、best_x/best_y 無有效數值。
像素外觀穩定且需精確定位用 template_match；主要依外形且光線變動大用 shape_match；只教良品、找未知表面缺陷用 dl_anomaly。
需 DL 加購包附帶的特徵模型，執行期不下載；`device` auto／cpu／cuda。搜尋圖以 320 工作尺寸抽特徵，位置精度受特徵格距限制，
微小目標應縮小 ROI；多尺度與角度以調整註冊圖的特徵網格搜尋。`backbone_path` 僅供內部測試，不替使用者設定。
範例 `register_count` 直接由第一張樣本圖裁切註冊，前三張三個零件 OK，第四張缺一個 NG。

## gdt_measure
形位公差（ISO 1101 最小區域，不是最小二乘）：`mode` straightness／flatness（2D 投影，同一個帶）／roundness／parallelism／perpendicularity／angularity。
點集模式接 `points`（find_line.points、circular_caliper.points、find_circle.points、contour_filter.contours 取第一條）；基準模式 `a`／`b` 接兩條
find_line.line（或點集、`{"angle": 度}`），`b` 是基準：垂直度把基準轉 90°、傾斜度轉 `reference_angle`。直線度＝包住所有點的最小寬度平行帶
（凸包＋旋轉卡尺）；真圓度＝最小區域圓 MZC（Nelder–Mead 從最小二乘圓起步，detail.lsc 同時給 LSC 值）；平行度等＝a 的點到基準方向的偏差帶，
兩端點時＝|Δθ|×線長。`tolerance`（teach）是公差帶寬度；`unit` mm 時接 `scale` 埠（undistort／to_world 的 mm_per_pixel）或填 `mm_per_px`。
輸出 `deviation`／`in_spec`／`unit`＋pass／fail 分支；detail 有方法名、擬合參數、極值點索引，現場爭議拿得出來。

## photometric_stereo
光度立體：同一件在 3～4 個方向打光各拍一張（`image`＝光 1、`image_1..3`），`light_azimuth`（畫面 +x 起順時針，0＝自右、90＝自下）與
`light_elevation` 要與燈架一致。輸出 `curvature`（有號散度：凸亮凹暗，刻印字最清楚）、`curvature_abs`（shape strength，無號，接 threshold／blob）、
`albedo`（去掉打光的材質圖，印刷／髒污用它）、`normal_x/normal_y`。單張看不見的浮凸／凹坑／拋光面刮痕用這個，之後照一般流程 blob／ocr_read。
一次觸發要連拍四張：來源端還沒就緒時用 `crop` 把 2×2 拼圖拆開（範本「刻印字／凹凸缺陷」就是這樣）。「沒有凹坑＝好」的判定用 `pixel_count`（blob 找不到會回 ng，整次 run 就變 NG）。`drop_darkest` 預設開（四燈時每像素丟最暗一張，深槽陰影不拉歪）。

## python_script
自訂 Python 檢測（只在使用者明確要求「自己寫程式」時才用；一般需求優先用內建工具）。`code` 定義 `def run(ctx)`：`ctx.image`（唯讀）、`ctx.gray()`、`ctx.inputs['a'..'d']`、`ctx.params['p1'..'p3']`（現場參數，技術員可在參數卡調）、`ctx.roi()`／`ctx.crop()`；回傳 dict：`value`／`result`／`text`／`data`／`image`（新陣列）／`status`（ok|ng）／`branch`（pass|fail）／`overlays`／`message`。輸出埠固定：value、result、text、data、image；`pass`／`fail` 分支接 judge。只能匯入 numpy／cv2／math／json／re／statistics／itertools／collections／functools／time；不能用 dunder、exec／eval／open；純 Python 迴圈超過 `max_ms` 會中止。**只有管理員能儲存新腳本**，生成後要提醒使用者由管理員儲存核准。
