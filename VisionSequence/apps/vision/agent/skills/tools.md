# 工具使用要領（AI 代理技能；每段以 `## <工具 type>` 開頭）

每段寫「什麼時候用、怎麼接、參數要領、陷阱」。參數與埠的完整定義由平台自動附在後面，這裡只寫目錄看不出來的經驗。

## image_source
流程的起點、只能有一個。AI 生成時 `params` 只填 `{"mode": "auto"}`：試跑吃上傳影像，存成流程後使用者在編輯器選來源。不要綁 `source_id`。

## grayscale
幾乎所有幾何／二值化工具的前置。彩色判斷（color_range／color_check／color_stats）**不要**經過它。

## blur
去雜訊。`median`（ksize 3～7）對椒鹽雜訊最好且保邊；`gaussian` 對高斯雜訊；`bilateral` 保邊但慢。ksize 必須是奇數。

## threshold
二值化。門檻不確定用 `method="otsu"`；背景不均用 `adaptive`（block 31～101、c 5～10）；已知固定灰階用 `fixed`。目標比背景暗要 `invert=true`（讓目標變白 255）。輸出 `threshold_used` 可當曝光指標。

## morphology
二值化後整理：`open` 去小雜點、`close` 補小洞、`erode`／`dilate` 調粗細。ksize 3～7；比目標小、比雜訊大。

## lut
灰階映射：`gamma`<1 提亮暗部、>1 壓亮部；`clahe` 局部對比（clip 2～4、tile 8）；`linear` 用 brightness／contrast。放在 threshold 前面救對比。

## filter
銳化／邊緣：`sharpen` 補模糊；`canny`（low/high 約 1:2～1:3）取邊緣圖給 hough_lines／edge_density；`laplacian`／`sobel` 取梯度圖。

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

## apply_mask
把遮罩（255 保留、0 填 fill）套到影像，常用來只留缺陷區或只看某個色塊；`mask` 埠接 blob.mask／threshold 影像。

## arithmetic
兩張影像運算：`absdiff` 看處理前後或兩張差異；`subtract` 去背景（先拍空景）；`add`／`multiply` 做加權。兩張尺寸要一致。

## warp_perspective
四點透視校正：`roi` 用 `polygon` 四個角點（順序自動排），`width/height` 給輸出尺寸。標籤斜貼、相機斜拍時放在 barcode／text_presence／量測前面。

## undistort
鏡頭畸變校正：選一個 `calibration` 資產（標定頁做的），放在取像後、量測前。廣角或近距離時邊角的直線會拱起來，
校正後量測值才不會隨位置漂。`keep_edges` 開＝整個畫面留著（角落補黑），關＝縮放到全部都是有效像素。
沒有標定資產就別放這個節點。

## convert_depth
16-bit／浮點影像轉 8-bit（`shift` 右移保線性、`minmax` 拉滿），或反向。多數工具會自動正規化，只有要控制映射方式時才放。

## rotate_flip
固定角度旋轉／翻轉（相機裝反）。`keep_size=true` 不改尺寸會裁角。

## template_match
範本比對定位：`template` 是資產 id（使用者框選建立），`threshold` 0.6～0.8（NCC 分數），旋轉件給 `angle_range`（±度）與 `angle_step`（5 即可，`subpixel` 預設開會把位置內插到 0.05px、角度內插到步進的 1/10）。角度以畫面順時針為正，與 ROI／找直線一致，可直接餵 shape_align。輸出 `matches` 給 shape_align、`best_x/best_y`；`not_found` 分支接 judge(ng)。AI 生成時沒有資產可填就留空並在 note 提醒。

## shape_align
定位補正：吃 template_match.matches，與 `ref_x/ref_y/ref_angle`（教導時的參考位置）算出 `transform`。試跑一次後把參考位置設成目前匹配位置（前端一鍵帶入）。

## fixture_roi
ROI 跟隨：`roi` 填教導時的固定 ROI，`transform` 接 shape_align.transform，輸出 `region` 接量測工具的 `roi` 輸入埠。每個要跟著動的 ROI 一個 fixture_roi。

## find_circle
射線式找圓（精量測）：`roi` 用 `annulus`，環要蓋住圓緣（r_inner ≈ 0.6r、r_outer ≈ 1.4r）；只有一段弧時給 `a0/a1` 起迄角，掃描線只落在扇形內。`edge_select` first/last 決定內緣或外緣（同心環杯件：外徑 last、內徑 first）。ROI 沒對準圓心也沒關係：`refine`（預設開）會從擬合圓心重掃一次。擬合是幾何最小平方（部分弧無偏）。輸出 `cx/cy/r`、`points`（給 calibration）。`not_found` 接 judge(ng)。

## find_line
卡尺式找直線：`roi` rect/rotated_rect，短邊方向掃描；輸出 `line`（接 angle／geometry 的 a/b）、`x1..y2`、`angle`。`direction` first/last/strongest 選邊。多用 RANSAC（預設開）抗雜點。

## caliper
量兩條邊的距離：ROI 長邊沿掃描方向、要橫跨兩條邊。`edge_pair` widest 抓最外側對、first_last 抓頭尾、`polarity` 限制邊緣方向。量亮條／暗條寬度給 `pair_polarity`（bright＝暗→亮再亮→暗、dark 相反）；知道大約寬度就填 `expected_width`（挑最接近的一對，旁邊有高對比雜訊邊也不會挑錯）。輸出 `width`（px）。

## wall_thickness
沿壁放多條卡尺量厚度：`roi` 用 **line 橫切壁**（最直觀）或矩形長邊沿壁。輸出 `thickness`（平均）、min/max。「沒有找到成對的邊緣」通常是掃描方向錯或 band 太窄。

## fit_arc
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
兩點距離：`ax/ay/bx/by` 接 find_circle.cx/cy 等；輸出 `distance/dx/dy`（px）。

## geometry
兩線交點、點到線垂距、中點、投影：`a/b` 接 line 或 point（any 型）。

## concentricity
兩圓同心度：a/b 接 find_circle 的 cx/cy/r，`max_deviation` 填圖面同心度公差的一半。輸出 in_spec 給 bool_logic。

## to_world
像素→真實世界座標（mm 或機械手座標），選一個含世界對應的 `calibration` 資產。
`points` 進 → `points_world`／`x`／`y` 出（第一點）；`value`（像素長度）→ `length`；`angle`（影像角度）→ `angle`（世界角度）。
要把位置交給機械手抓取時用它，接在 template_match／find_circle 的中心座標後面，再接 output 具名輸出。
只換算長度用 calibration 就夠，不必用這個。

## calibration
像素→mm：`pixel_size` 模式填 `pixel_size_mm`（0.05 mm/px 之類）；`known_distance` 用 px_distance/real_mm；`asset` 模式直接吃標定資產（站台重新標定後所有流程一起更新，優先用這個）。`value` 進、`mm` 出，放在 tolerance_judge 前。

## tolerance_judge
標稱值±公差判定：`nominal/upper_tol/lower_tol/unit/spec_source/name`。輸出 `in_spec`（bool，接 bool_logic 或 judge by_input）、`pass/fail` 分支、`deviation`。

## in_range
數值落在 [low, high] → `inside`／`outside` 分支。簡單守門用它；有標稱值用 tolerance_judge。

## if_number
數值比較（eq/ne/gt/ge/lt/le）→ `true/false` 分支。計數 == N 就是它。

## bool_logic
多個 bool 彙總（and/or/not）：`values` 埠可接多條邊。輸出 `result` 給 judge(by_input)。

## formula
數值算式：`expression` 用 a/b/c 變數（`a*2`、`(a+b)/2`）。輸出 `value`。

## count_list
清單長度（hough_lines.lines、blob.blobs 等）→ `count`。

## judge
決定 run 的 OK/NG：`verdict` ok/ng 放在分支下游、`by_input` 收 bool。`label` 寫 NG 原因（上位機看得到）。每條互斥分支各接一個。

## format_text
把結果排成一行文字給讀不了 JSON 的設備：`template` 用 `{名字}` 取值（judge、先前的具名輸出、觸發帶進來的引數如 lot／sn、
本節點輸入 a~d，另有 run_id／station），`{width:.2f}` 控制小數，`\\r\\n` 會變成真的控制字元；`ending` 補行尾、`name` 決定
具名輸出的名字。設備端用 `RUN <flow> fmt=<name>`（TCP）或 `format=<name>`（HTTP）就拿到純文字。放在 judge 與其他 output 之後。

## output
具名輸出：`name` 英文鍵名，`value` 埠接數值／字串／影像。上位機從 `outputs[name]` 拿。

## draw_result
把所有 overlay 畫到影像上輸出（總覽／存檔用）；輸入接原圖。

## blob
粒子分析：內建二值化（`threshold_method` otsu/fixed、`polarity` bright/dark；非矩形 ROI 的 Otsu 只看遮罩內）或接已二值化的影像（fixed+128+bright）。`area` 是像素數（1 像素粒子就是 1），`min_area/max_area/min_circularity` 篩選；黏連粒子 `separate=true`（分水嶺，種子視窗依 min_area 推算的半徑，大小粒子混在一起也切得開）。輸出 `count`、`blobs`、`centers`、`mask`、`found/not_found`（`min_count` 決定）。

## pixel_count
數 ≥ threshold 的像素：接 color_range／threshold 輸出，`min_count/max_count` 決定 ok/ng。

## dark_ratio
暗部佔比守門：`threshold` 以下的比例 > `max_ratio` → fail。

## intensity
ROI 灰階統計（mean/std/min/max/median）。亮度守門、簡單有無。

## histogram
直方圖與 Otsu 門檻／峰值；教學與曝光診斷。

## line_profile
沿線／折線取灰階剖面：量溝深、找邊緣位置、看印刷條紋。`roi` 用 line/polyline。

## edge_density
Canny 邊緣像素比例 > `max_ratio` → ng：畫面異常（髒污、雜訊、對焦跑掉）守門。

## color_check
ROI 平均色與目標色（`color` 十六進位）距離 ≤ `tolerance` → match。`space` rgb/hsv（hsv 的色相差依飽和度加權，灰／白／黑目標不會被色相亂數影響）；目標色用使用者 ROI 的主色最穩。

## color_stats
ROI 顏色統計輸出（RGB/HSV 平均、hex）給上位機記錄或接 if_number。

## defect_diff
良品差異比對：`template` 良品資產（與 ROI 同尺寸），`align=phase` 補位移，`threshold`（灰階差）與 `min_area` 決定靈敏度，`border` 忽略對齊邊界假差異。輸出 `ok/defect` 分支、`count/total_area`、`defect_mask`。

## barcode
一維碼／QR：`roi` 縮小範圍加速；`expected` 填預期內容可直接判定。輸出 `first`（字串）、`count`、`found/not_found`。

## text_presence
文字有無（筆畫密度，不是 OCR）：`roi` 框住字區，`polarity` dark/bright，`min_ratio/max_ratio` 決定 present。

## save_image
每次執行寫檔；AI 不生成，需要時提醒使用者手動加。

## send_image
整合用（使用者要求「把影像傳給上位機」「NG 圖送到 MES」時才加）：把該步驟的影像推給 tcp_image 連線（JPEG／PNG／raw），
表頭帶 run_id、判定與具名輸出；only_ng=true 只送 NG；失敗預設降級不讓 run 失敗。放在流程尾端、判定之後，影像接想送的那一步的輸出。

## write_modbus / read_modbus
整合用（AI 不主動生成，使用者要求「把結果寫給設備」「從 Modbus 讀料號」時才加）：write_modbus 依對映表把判定或具名輸出寫到連線；
read_modbus 從連線讀線圈與暫存器（主站連線讀設備、從站連線讀對方主站寫進平台的值），輸出 values／value／ok，publish=true 才進具名輸出。
兩者都要先在「外部整合 ▸ Modbus 主站／從站」頁建立連線，以名稱引用；失敗預設降級不讓 run 失敗。

## note
不是工具：畫布便利貼（type=note、不接邊），寫流程說明或調機備註。

## yolo_detect
ultralytics YOLO 物件偵測（原生 torch 推論，GPU 自動使用）：`model` 選教導頁訓練的 .pt 資產，沒選時用 `model_name` 官方底模（`yolo11n.pt`，COCO 80 類，第一次自動下載）。`conf` 是主要調機參數、`iou` NMS、`filter_labels` 只留某些類別、`min_count/max_count_ok` 決定 ok/ng。輸出 `detections/matches`（x,y,w,h,cx,cy,label,score）、`count`、`labels`；`found/not_found` 分支。要客製類別請先在「深度學習教導」用「物件偵測（YOLO）」訓練。

## yolo_segment
ultralytics YOLO-seg 實例分割：同 yolo_detect 的模型與門檻參數，另有 `min_area` 濾小實例。輸出 `count`、`matches`（含 area）、`mask`（聯合遮罩，可接 blob／pixel_count）、`contours`（可接 geometry／量測）、`labels`。底模 `yolo11n-seg.pt`；自訂類別用「實例分割（YOLO-seg）」訓練。

## yolo_classify
ultralytics YOLO-cls 影像分類：`imgsz` 224；`threshold` 分數門檻、`pass_labels` 合格類別、`top_k`。輸出 `label/score/index/top`，`pass/fail` 分支。底模 `yolo11n-cls.pt` 是 ImageNet 類別，實務上必用「影像分類（YOLO-cls）」訓練自己的類別。

## yolo_pose
YOLO-pose 關鍵點：輸出每個物件的 `keypoints`（[x,y,conf]×N，COCO 人體 17 點）與 `matches` 框；`kpt_conf` 只影響顯示。適合姿勢／位置檢查、人員闖入。平台目前不提供關鍵點標記訓練，需用官方或自備 pose 權重。

## yolo_obb
YOLO-obb 旋轉框：輸出 `matches`（cx, cy, w, h, angle°, points 四角）、`contours`（四角輪廓）；適合傾斜擺放的工件計數／定位，角度可接 formula／tolerance_judge 做方向檢查。底模 `yolo11n-obb.pt`（DOTA 航拍類別）僅供試用，自訂類別用「旋轉框偵測（YOLO-obb）」訓練（polygon 標記自動取最小外接旋轉矩形）。

## python_script
自訂 Python 檢測（只在使用者明確要求「自己寫程式」時才用；一般需求優先用內建工具）。`code` 定義 `def run(ctx)`：`ctx.image`（唯讀）、`ctx.gray()`、`ctx.inputs['a'..'d']`、`ctx.params['p1'..'p3']`（現場參數，技術員可在參數卡調）、`ctx.roi()`／`ctx.crop()`；回傳 dict：`value`／`result`／`text`／`data`／`image`（新陣列）／`status`（ok|ng）／`branch`（pass|fail）／`overlays`／`message`。輸出埠固定：value、result、text、data、image；`pass`／`fail` 分支接 judge。只能匯入 numpy／cv2／math／json／re／statistics／itertools／collections／functools／time；不能用 dunder、exec／eval／open；純 Python 迴圈超過 `max_ms` 會中止。**只有管理員能儲存新腳本**，生成後要提醒使用者由管理員儲存核准。
