# 範例範本與合成樣本影像

範例範本位於**範本畫廊**中，即「流程」頁的「從範本建立」與編輯器頂列的「載入範本」，共有 68 個內建範本，因此不會讓流程清單變得雜亂。`manage.py seed_demo` 或 `dev.ps1 -Setup` 會建立與它們搭配的一切：兩條示範流程、每個範本各一組合成樣本圖，這些圖會以**固定影像**儲存並隨範本移動；參考圖，也就是定位範本、Golden 列印圖與白參考，會以固定影像連接到工具的影像輸入埠；統計範本、形狀模型與教導模型資產也會一併建立。從範本建立流程後保留來源不變即可，每個範本都以內含自身樣本圖的 Fixed image 步驟開始，因此可**原樣執行**。擷取步驟會成為 Fixed image 步驟，逐次循環樣本圖，第四張通常是刻意安排的 NG。146 個內建工具中有 146 個至少出現在一個範本內，因此開啟任一範本即可看到該工具實際如何接線，以及參數在實務中如何設定。

每組有四張影像，教學範本為三張，最後一張刻意設為 NG。來源會循環，因此連續執行或反覆點選「執行」會得到 OK → OK → OK → NG。座標與公差都符合合成影像的標稱值，所以開始使用前不需要調參。

## 範本清單 {#list}

| 範本 | 樣本影像 | 教導重點 | 主要工具 |
|---|---|---|---|
| 孔數計數 | 亮色板件有四個角孔與較大的中心孔，並旋轉數度；第四張缺少一個角孔 | 最基本的骨架：threshold → blob → count → 依數量分支 | `grayscale``blur``threshold``morphology``blob``if_number``judge``output``draw_result` |
| 曝光檢查 | 同一片板件的四種曝光：正常、偏暗、偏亮與過曝；第四張超出範圍 | 純前處理與邏輯的把關流程：縮小加速，並以 Otsu 門檻作為曝光指標 | `resize``threshold``in_range` |
| 圓量測 | 亮色板件搭配深色孔洞；第四張超出公差 | 找圓、把像素轉成毫米，再依公差判定。也示範**扇形 ROI**，也就是帶起訖角的環形 ROI，用於圓弧擬合，以及用橢圓擬合評估真圓度 | `find_circle``formula``calibration``tolerance_judge``fit_arc``fit_ellipse` |
| 邊線夾角 | L 形零件；第四張為 84°，右下有 45° 倒角 | 兩次找線得到角度與交點；倒角工具量測斜邊 | `find_line``angle``geometry``chamfer_angle``in_range` |
| 印刷良品比對 | 一個印刷圖案；第四張多了一塊汙點 | 與 Golden 範本做差異比對，可找出事先無法描述的缺陷。範本資產由 seed 建立 | `defect_diff` |
| 統計良品比對 | 印刷比對影像，第四張有汙點 | seed 會由 30 張抖動的良品印刷建立統計範本，亮度 ±8、位移 ±3 px；`defect_stat` 會標出每個像素超過自身正常值 4 個標準差的位置，因此照明與紋理變化不會迫使門檻放寬 | `defect_stat``if_number` |
| 布面瑕疵 | 週期性織紋；第四張有刮痕 | 頻域低通會抹除規則紋理並留下深色痕跡，也就是缺陷。遮罩會取出缺陷區域 | `fft_filter``threshold``blob``apply_mask` |
| 前處理與量測實驗室 | 漸層、灰階階梯楔與深色溝槽 | 影像鏈，包含位深 → gamma → 銳化 → 翻轉 → 前後差異；並巡覽量測工具：線剖面、區域統計、直方圖、邊緣密度、暗區比例、裁切與色彩平面 | `convert_depth``lut``filter``rotate_flip``arithmetic``line_profile``intensity``histogram``edge_density``dark_ratio``crop``color_convert` |
| Blob 結果排序與挑選 | 六個小圓形零件散布在深色背景上；第四張缺少一個有效零件，且有一個過大的零件 | Blob 結果會依面積過濾、依掃描順序排序、挑出最大的有效零件、將所有有效零件依尺寸分級，並把左右中心清單合併成一組點集 | `blob``list_filter``list_sort``list_pick``list_classify``points_merge``if_number` |
| 元件陣列缺位檢查 | 乾淨的 3×4 亮色元件陣列；第四張缺少一個位置 | Blob 檢測框送入 Correct array，補齊推斷出的格線、回報缺格、計數，並判定陣列是否完整 | `blob``array_correct``count_list``if_number` |
| 圓與直線 | 五個孔與兩條斜線；第四張缺少一個孔 | 示範 Hough 可一次找出多個圓，find-circle 可精準量測單一圓；並計算線段清單數量與兩個孔中心距離 | `hough_circles``hough_lines``count_list``find_circle``distance` |
| 圓周齒數（極座標展開） | 深色背景上的亮色十二齒齒輪；第四張缺齒 | Polar unwrap 會把齒根與齒尖之間的環帶攤平成條帶，讓每個齒成為亮區塊、每個間隙成為暗欄；threshold 與 blob 計算區塊，Polar restore 在原圖上標示各齒。起始角放在間隙，因此接縫不會切開齒形 | `polar_unwrap``threshold``blob``if_number``polar_restore` |
| 崩邊檢測（輪廓幾何） | 深色背景上的亮色沖壓件，含孔與槽；第四張上緣被咬掉一塊 | Contour find 追蹤外形，filter 只保留最大輪廓，也就是零件；contour geometry 計算深度超過 12 px 的凸性缺陷，即崩邊。Contour match 以 Hu moments 與樣本外形資產比對輪廓，用於防止零件錯誤或嚴重變形 | `contour_find``contour_filter``contour_geometry``contour_match``if_number` |
| 圓盤崩邊（圓形卡尺） | 亮色圓片有中心孔；第四張右下外緣有 24° 崩邊 | 180 個徑向卡尺每 2° 給出半徑與徑向跳動；Profile defects 會對邊緣點擬合圓，並標記低於該圓 3 px 的每一段，或卡尺完全找不到邊緣的位置。崩邊會在外緣畫成紅色弧段 | `circular_caliper``profile_defect``if_number` |
| 真圓度（形位公差） | 崩邊圓片組：亮色圓片有中心孔；第四張右下外緣有 7 px 深崩邊 | 180 個徑向卡尺給出邊緣點；Form and position tolerance 擬合最小區域圓（ISO 1101），同心雙圓之間的環寬在 5 px 內即通過。明細也回報最小二乘值與兩個極值點 | `circular_caliper``gdt_measure` |
| 刻印字與凹坑（光度立體） | 同一片板件在四向打光下的 2×2 影像，光源來自右、下、左、上；板件有斑駁反射率與浮凸字樣「VS 42」；第四張在字元上方檢查區有凹坑 | 四個 Crop 步驟切出各視角，Photometric stereo 轉成形狀強度圖，斑駁消失後只留下表面形狀，再以檢查區中的像素計數找出單張影像看不到的凹坑。良品答案是空區，所以用像素計數而非 blob 計數判定 | `crop``photometric_stereo``pixel_count` |
| 條碼品質分級（ISO 15415） | 白色標籤含 Data Matrix 與料號；四種印刷品質為乾淨、低對比、模糊且有雜訊，以及靜區有髒汙的符號 | Barcode quality grade 像驗證器一樣量測符號，C 級以上通過；parameters 輸出會說明哪一項參數拉低等級，第四張標籤會失敗 | `barcode_grade` |
| 排除區（組合區域） | 圓量測板件：亮色板件的深色中心孔會改變大小 | 兩個 Region 步驟畫出孔與標籤區，Region combine 從板件矩形中切除它們，並把組合區域經由區域輸入提供給統計與 blob 步驟。即使孔變大，板件平均值仍保持穩定，因為孔的像素從未計入 | `region_from_shape``region_combine``intensity``in_range``blob` |
| 平場校正（打光不均） | 亮色板件在強烈暗角下有深色斑點，角落亮度只有 45%；第四張多了一個大標記 | 除以白參考資產可攤平照明，因此固定門檻能找到所有斑點；側支路用同一門檻跑未校正影像，計數會錯。參考圖由 seed 寫入 | `shading_correct``threshold``blob``if_number` |
| 重疊匹配合併與禁區排除 | 三個定位標記位於灰色禁區旁；第四張在禁區內新增一個標記 | 固定標記圖送入 Template match，重複檢測框會合併，檢測框再依尺寸與分數過濾，剩下的標記框會與量到的禁區框比對 | `template_match``boxes_merge``boxes_filter``boxes_overlap``blob` |
| 自訂 Python 量測 | 單一亮色矩形零件；第四張矩形過於細長 | Blob 量測結果送入固定且已核准的 Python 腳本，計算長寬比與填滿分數，再由範圍檢查把自訂值轉成 OK/NG | `blob``python_script``in_range` |
| 顏色存在 | 三個色塊；第四張紅色偏橘 | HSV 範圍遮罩進入像素計數，用於典型存在／缺失判定 | `color_range``pixel_count` |
| 顏色驗證 | 同一組影像 | 以距離比對區域平均色與目標色；色彩統計會輸出十六進位色碼給主機系統 | `color_check``color_stats` |
| 多色分割轉計數 | 一個紅點、一個綠點與一個藍點；第四張缺少藍點 | 三段 HSV 範圍建立整數 label map，接著 Label map blobs 依類別計算連通區域，任何一種顏色缺席就失敗 | `color_segment``blob_label` |
| 固定樣本色分類 | 色卡上有紅色、綠色或藍色色票；第四張色票不屬於固定樣本 | 三個固定樣本色票隨範本附帶；Sample colour classify 比對色票 ROI 的直方圖，相似度不足時走 NG 分支 | `color_classify` |
| 矩形板角點與歪斜 | 深色背景上的亮色矩形板；第四張板件過寬且歪斜超出公差 | 同一零件用兩種方式量測：Find rectangle 直接回報已標定矩形，四次找邊則送入 Corners from four edges。寬度公差會拒絕不良板件 | `find_rectangle``find_line``find_quadrilateral``tolerance_judge` |
| 槽寬與條紋數 | 板件有深色槽與五條參考條紋；第四張槽寬過大 | Pair-edge search 在單一步驟量測槽的兩側，多線搜尋則計算影像其他位置的參考條紋 | `find_parallel_lines``find_lines_multi``in_range``if_number` |
| 孔矩陣完整性 | 3×3 深色孔陣列；第四張缺少一個孔 | Find circle matrix 將區域分成儲格、量測每個孔，並在某個格位無孔時回報缺格索引 | `find_circles_matrix``count_list` |
| 邊緣趨勢與剖面峰值 | 直板邊緣有四個亮色參考標記；第四張邊緣有局部凸起 | Edge trend 沿教導邊緣排列卡尺，並回報局部凸起造成的缺失樣本。Peak search 會從矩形灰階剖面讀出四個參考標記 | `edge_trend``peak_search``count_list` |
| 教導輪廓缺陷比對 | 自由外形沖壓件：正向、平移、往另一側平移，最後崩邊 | 固定定位裁切會教導位姿；Template match 與 Locate offset 修正平移樣本，Edge model defects 先由固定參考圖教導良品外形，再檢查即時邊緣 | `fixed_image``template_match``shape_align``edge_model_defect` |
| 沿路徑搜尋邊緣 | 亮色膠條沿著教導路徑分布；第四張有斷點 | Path extract 沿教導路徑放置卡尺，回傳找到的邊緣點與缺失索引，再由缺失樣本數驅動判定 | `path_extract``count_list``if_number` |
| 檢查前焦距閘門 | 銳利目標含細線與文字；第四張影像模糊 | Sharpness 在其餘檢查前先作為閘門，也回報高頻雜訊估計，避免把雜訊誤認為對焦 | `sharpness``output` |
| 跨幀平均與前幀差異 | 四個影格中有兩個亮色零件；第四個影格新增一個零件 | Frame accumulate 輸出兩幀平均，Previous image 將目前影格與上一個快取平均輸出比對。第一個影格無前一張影像，會正確回報 not found 而不是錯誤 | `frame_accumulate``previous_image``arithmetic``blob` |
| 處理區域後貼回 | 板件有三個深色特徵；第四張在處理區域內多了一個標記 | ROI 會先裁切、以 look-up table 增強、濾波，再貼回完整影像。完整畫面檢查接著在同一 ROI 計算深色特徵 | `crop``lut``filter``paste_back``blob` |
| 手動校正與零件座標 | 板件有兩個基準孔；第四張孔距過大 | Manual lens correction 校正影像，兩次找圓定義零件座標系，seed 建立的 0.05 mm 像素比例標定會把孔距換算成毫米進行公差檢查 | `undistort``find_circle``coordinate``to_world``distance` |
| 映射到第二相機 | A 相機基準孔位於三個位置；第四張無孔 | 找到的孔中心會透過 seed 建立且名為「Example: camera mapping (A→B)」的仿射相機映射資產，轉成 B 相機座標並格式化 | `find_circle``map_points``format_text` |
| 教導姿態取料補正 | 教導零件先正向，再平移並旋轉；第四張無零件 | Template match 找到教導零件，Alignment offset 以 grab 模式將教導取料點旋轉和平移到目前影像位姿 | `template_match``align_offset``format_text` |
| 整張回正後重跑量測 | 帶標記板件經平移與旋轉；第四張有一段帶寬超出公差 | 定位標記驅動 Locate offset，Image follow 將整張影像變換回教導位姿，固定座標卡尺即可每次量測同一條帶 | `template_match``shape_align``image_fixture``caliper` |
| 雙視野拼接計數 | 左視野有兩個零件，搭配固定右視野；第四張左視野缺少一個零件 | Image stitching 將即時左視野與固定右視野合成 1×2 格狀影像，下游計數即可把兩個相機畫面視為同一張影像 | `fixed_image``stitch_images``blob``if_number` |
| 條碼／QR 讀取 | 傾斜標籤含 QR code；第四張無印碼 | 最短識別流程：讀碼、檢查是否讀到內容、輸出內容 | `barcode``output` |
| 解碼、拆訊息與比對 | QR 訊息帶有批號與料號欄位；第四張使用錯誤批號格式 | 代碼 payload 依分隔符拆分，以正規表示式檢查批號欄位，並格式化簡短文字回覆給主機系統 | `barcode``parse_message``string_match``format_text` |
| 定位後讀碼 | 大型雜亂背景中有一個移動的小 QR code；第四張無碼 | 示範難讀碼的接線：template matching 找到碼區，ROI follow 將裁切區移到其上，crop 放大後讓解碼器只讀該小區塊；教導偵測器可透過 matches 埠連接到同一接線 | `template_match` `shape_align` `fixture_roi` `crop` `resize` `barcode` |
| 日期碼讀取與驗證（教導字型） | 白色標籤含八位數代碼；第四張有一位數被汙點遮住 | seed 會由 24 行渲染文字教導數字字型，包含分割與小型分類器，完全離線且不需要 OCR 模型檔；Text read 輸出字串與每字元信心度，Text verify 檢查八位數樣板與信心度，並在 NG 影像以紅框標出被汙損的數字 | `ocr_read``ocv_verify` |
| 含透視校正的條碼標籤 | 同一組影像 | 四點透視校正會先校正傾斜標籤再讀取，並在序號區做文字存在檢查 | `warp_perspective``barcode``text_presence` |
| 形狀比對定位（任意角度、任意光線） | 非對稱支架：正向、旋轉 37° 且變暗、在雜亂中旋轉 −120°；第四張為不同零件 | Shape match 會評分邊緣方向，因此旋轉、變暗與雜亂中的影像都能以高分找到，並提供給 Locate offset 與 ROI follow；不同零件低於分數下限而走 NG 分支。形狀模型資產由 seed 從第一張圖建立 | `shape_match``shape_align``fixture_roi``intensity` |
| 定位與量測 | 十字標記與亮色帶；第四張亮帶太寬 | 三段式定位補正：template match → ROI follow → 卡尺寬度。範本資產由 seed 自動裁切 | `template_match``shape_align``fixture_roi``caliper` |
| 深沖杯件量測 | 同心杯緣與壁厚截面；第四張外徑超差 | 完整量測流程：定位、三個跟隨定位的 ROI、外徑與內徑找圓、穿過壁面的**線 ROI**量厚度、同心度，以及多個公差合併判定 | `find_circle``wall_thickness``concentricity``tolerance_judge``bool_logic` |
| 輸送帶取料（單相機） | 六張合成輸送帶影格；零件沿皮帶移動，第一張與最後一張碰到邊界 | 單相機取料交握：分割、邊緣過濾、平台追蹤與確認、格式化 `cls,x,y,z` 文字，以及機械手臂寫出 | `ai_segment``edge_filter``track_objects``format_text``write_modbus` |
| 輸送帶取料（ByteTrack） | 同一組六張輸送帶影格 | 分割工具使用內建 ByteTrack 追蹤器，讓每個零件保有一個 tracker ID；`track_objects` 以追蹤器參考模式依該 ID 確認，而不是自行比對位置 | `ai_segment``edge_filter``track_objects``format_text``write_modbus` |
| 輸送帶取料（雙視野） | 已知視差的合成輸送帶零件立體影像對 | 立體取料交握：成對取像、分割、邊緣過濾、追蹤確認、由 `stereo_depth` 取得物件頂面 Z、格式化 `cls,x,y,z` 文字，以及機械手臂寫出 | `stereo_grab``ai_segment``edge_filter``track_objects``stereo_depth``format_text``write_modbus` |
| 依變數切換配方 | 預設配方有三個亮點；第四張對該分支而言太暗 | 讀取配方變數，用 switch 分流到亮或暗門檻分支，再儲存累計數。Sample mode 使用變數覆蓋層，因此不會持久化站台值 | `variable_get``switch``threshold``blob``variable_set` |
| 影像切片逐格巡檢 | 2×2 面板影像；第四張某一格有斑點，但 sample mode 只示範子流程接線 | Tile 建立四個區域，For each 會以 sandbox mode 對每格呼叫 seed 建立的示範流程，直接的 Call flow 節點則示範非迴圈版本 | `tile``for_each``call_flow` |
| 燈源、相機 I/O 與設備訊號 | 三個亮色訊號點；第四張缺少一個點 | 流程會套用相機設定、設定環形光源、檢查亮點，接著脈衝輸出站台與相機輸出並讀取 Modbus。缺少連線時會降級為警告 | `camera_set``set_light``threshold``blob``io_output``camera_io``read_modbus` |
| 記錄、存圖、送圖與觸發 | 三個方形零件；第四張多了一個零件 | 計數會格式化成文字、寫入 CSV 記錄、儲存 NG 影像、送出結果影像給影像主機，並觸發稽核流程。Sandbox mode 會回報 Would actions | `format_text``write_log``save_image``send_image``trigger_flow` |
| AI 物件計數（官方底模） | 停止標誌；第四張有一個，第五張有三個 | 無需訓練的深度學習：官方底模可直接辨識並判定數量。權重會在首次執行時下載，需要深度學習依賴 | `ai_detect``if_number` |
| AI 實例分割：標誌面積 | 同一組影像 | 分割的聯集遮罩進入像素計數得到總面積，再依門檻判定，是分割接到下游量測的範例 | `ai_segment``pixel_count` |
| 庫存分類器閘門 | 四張小型合成產品卡，顏色與形狀各不相同 | 庫存分類器輸出 ImageNet 標籤，接著 `string_match` 示範依標籤分流。合成產線零件未必會命中允收標籤；實務可訓練分類器或設定 `pass_labels` | `ai_classify``string_match``judge` |
| 傾斜工件的旋轉框 | 四個傾斜矩形零件 | 旋轉框官方底模接入後處理鏈：`ai_obb` 回傳旋轉框，`list_sort` 依角度排序，`format_text` 建立精簡角度報表 | `ai_obb``list_sort``format_text` |
| 關鍵點與幾何 | 四張類似火柴人的樣本 | `ai_pose` 回傳姿態框與關鍵點清單。此範本以偵測數量作為閘門；在教導關鍵點專案中，同一輸出也可接到幾何與距離檢查 | `ai_pose``if_number` |
| 分類：良品／缺孔（教導模型） | 深色背景上的亮色圓片；第五與第六張缺少中心孔 | 示範教導模型如何進入流程：seed 以 30 張合成樣本與資料增強訓練內建 MLP，成為「Example: classifier (good / missing hole)」，再由 `dl_classify` 判定通過或失敗。整張縮小影像分類適合整體外觀不同的類別 | `dl_classify` |
| 異常檢測：只教良品（教導模型） | 分割教導板件，三張乾淨、兩張有刮痕 | 安裝異常 backbone 時，seed 會以 20 張乾淨板件建立「Example: anomaly (scratch plate)」；`dl_anomaly` 會把每個 patch 與良品記憶庫比對，即使訓練時未曾看過刮痕，刮傷板也會成為異常。無 backbone 時範本仍可載入，模型留給您選擇 | `dl_anomaly``if_number` |
| 語意分割：刮痕面積（教導模型） | 有紋理的面板；第四與第五張有刮痕 | seed 以 10 張多邊形標記影像訓練 patch_segment，成為「Example: segmenter (scratch)」，再由 `dl_segment` 依刮痕面積門檻判定 | `dl_segment` |
| 教導式偵測與實例模型 | 傾斜零件樣本組 | `dl_detect` 與 `dl_instance` 並排放置，模型欄位留空。請在深度學習頁訓練偵測或實例分割專案，再於此選取那些 ONNX 模型資產 | `dl_detect``dl_instance` |
| 免重訓擴充的檢索庫 | 三張已知 part_a 查詢圖與一張無關零件圖 | 安裝異常 backbone 時，seed 會建立三類、每類兩張參考圖的檢索庫。`dl_retrieval` 接受預期標籤，並將低相似度影像送到 `not_matched`；日後新增類別只需加入參考影像，不需要重新訓練 | `dl_retrieval` |
| 四向打光融合表面缺陷 | 四張 2x2 拼圖，每張都是同一表面在四個打光方向下的影像；第四張在 270 度視角有刮痕 | 裁切四個視角，以 shadow mode 的 `multi_light_fuse` 融合，只保留不同方向間會變化的內容，並將刮痕偵測為強起伏；`multi_light_grab` 連接到樣本，用於示範線上擷取 | `multi_light_grab``multi_light_fuse``threshold``blob` |

## 影像與資產位置 {#files}

- 樣本影像：`data/samples/<set>/01.png…`，由 `apps/vision/demo_images.py` 產生。若資料夾已有 PNG，會直接重用。要重新產生時，刪除該資料夾並再次執行 `manage.py seed_demo`。
- 固定影像：每張樣本圖與參考圖只會儲存一次，位置在 `ASSET_DIR/fixed/<sha>.png`，以內容定址，因此重複 seed 不會產生副本，並由範本 graph 參照；`instantiate` 會把 `{SOURCE}` 擷取步驟轉成持有該組影像的 `fixed_image` 步驟。不再建立資料夾來源或影像資產，舊版 seed 留下的「Example: …」資料夾來源與圖片資產在無引用時會移除。
- 資產：由 30 張抖動良品印刷建立的統計範本，從第一張形狀比對影像建立的支架形狀模型，以及教導模型，位於「Examples」群組。兩個定位範本、Golden 列印圖與沖壓件外形會從第一張樣本圖裁成固定影像，平場範本的白參考也是固定影像。
- `seed_demo` 可安全重複執行：既有來源與資產會重用，流程 graph 會更新到目前版本。

## 尚無範本使用的工具 {#not-included}

無。每個內建工具現在都至少由一個畫廊範本代表。`dl_detect` 與 `dl_instance` 等模型特定工具仍需要站台訓練的模型資產才能執行，因此其畫廊範本是只示範 graph 接線的範例。

## 如何維持正確 {#test}

深度學習範本：`tests/test_demo.py` 會實際執行可快速 seed 的教導模型範本；設定 `VISION_TEST_DL=1` 且官方權重已可用時，也會執行官方模型範本。需要外部訓練模型資產的範本，例如 `dl_detect_instance_demo`，會在您選擇模型前先檢查 graph 層級。

`tests/test_demo.py` 每次測試都會把整組範例 seed 到暫存環境，並以對應樣本來源執行每個內建範本，鎖住「每個範本都可執行且無任何節點錯誤」這句話。範本或工具一旦壞掉，測試會立即變紅。
