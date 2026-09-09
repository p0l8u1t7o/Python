# 範例範本與合成樣本影像

範例範本位於**範本畫廊**中，即「流程」頁的「從範本建立」與編輯器頂列的「載入範本」，共有 37 個內建範本，因此不會讓流程清單變得雜亂。`manage.py seed_demo` 或 `dev.ps1 -Setup` 會建立與它們搭配的一切：兩條示範流程、每個範本各一組合成樣本圖，這些圖會以**固定影像**儲存並隨範本移動；參考圖，也就是定位範本、Golden 列印圖與白參考，會以固定影像連接到工具的影像輸入埠；統計範本、形狀模型與教導模型資產也會一併建立。從範本建立流程後保留來源不變即可，每個範本都以內含自身樣本圖的 Fixed image 步驟開始，因此可**原樣執行**。擷取步驟會成為 Fixed image 步驟，逐次循環樣本圖，第四張通常是刻意安排的 NG。146 個內建工具中有 88 個至少出現在一個範本內，因此開啟任一範本即可看到該工具實際如何接線，以及參數在實務中如何設定。

每組有四張影像，教學範本為三張，最後一張刻意設為 NG。來源會循環，因此連續執行或反覆按「執行」會得到 OK → OK → OK → NG。座標與公差都符合合成影像的標稱值，所以開始使用前不需要調參。

## 範本清單 {#list}

| 範本 | 樣本影像 | 教導重點 | 主要工具 |
|---|---|---|---|
| 孔洞計數 | 亮色板件有四個角孔與較大的中心孔，並旋轉數度；第四張缺少一個角孔 | 最基本的骨架：threshold → blob → count → 依數量分支 | `grayscale``blur``threshold``morphology``blob``if_number``judge``output``draw_result` |
| 曝光檢查 | 同一片板件的四種曝光：正常、偏暗、偏亮與過曝；第四張超出範圍 | 純前處理與邏輯的把關流程：縮小加速，並以 Otsu 門檻作為曝光指標 | `resize``threshold``in_range` |
| 圓規量測 | 亮色板件搭配深色孔洞；第四張超出公差 | 找圓、把像素轉成毫米，再依公差判定。也示範**扇形 ROI**，也就是帶起訖角的環形 ROI，用於弧線擬合，以及用橢圓擬合評估圓度 | `find_circle``formula``calibration``tolerance_judge``fit_arc``fit_ellipse` |
| 邊角角度 | L 形零件；第四張為 84°，右下有 45° 倒角 | 兩次找線得到角度與交點；倒角工具量測斜邊 | `find_line``angle``geometry``chamfer_angle``in_range` |
| 印刷比對 | 一個印刷圖案；第四張多了一塊汙點 | 與 Golden 範本做差異比對，可找出事先無法描述的缺陷。範本資產由 seed 建立 | `defect_diff` |
| 統計印刷比對 | 印刷比對影像，第四張有汙點 | seed 會由 30 張抖動的良品印刷建立統計範本，亮度 ±8、位移 ±3 px；`defect_stat` 會標出每個像素超過自身正常值 4 個標準差的位置，因此照明與紋理變化不會迫使門檻放寬 | `defect_stat``if_number` |
| 織物缺陷 | 週期性織紋；第四張有刮痕 | 頻域低通會抹除規則紋理並留下深色痕跡，也就是缺陷。遮罩會取出缺陷區域 | `fft_filter``threshold``blob``apply_mask` |
| 前處理與量測實驗室 | 漸層、灰階階梯楔與深色溝槽 | 影像鏈，包含位深 → gamma → 銳化 → 翻轉 → 前後差異；並巡覽量測工具：線剖面、區域統計、直方圖、邊緣密度、暗區比例、裁切與色彩平面 | `convert_depth``lut``filter``rotate_flip``arithmetic``line_profile``intensity``histogram``edge_density``dark_ratio``crop``color_convert` |
| 圓與線 | 五個孔與兩條斜線；第四張缺少一個孔 | 示範 Hough 可一次找出多個圓，find-circle 可精準量測單一圓；並計算線段清單數量與兩個孔中心距離 | `hough_circles``hough_lines``count_list``find_circle``distance` |
| 齒輪齒數（極座標展開） | 深色背景上的亮色十二齒齒輪；第四張缺齒 | Polar unwrap 會把齒根與齒尖之間的環帶攤平成條帶，讓每個齒成為亮區塊、每個間隙成為暗欄；threshold 與 blob 計算區塊，Polar restore 在原圖上標示各齒。起始角放在間隙，因此接縫不會切開齒形 | `polar_unwrap``threshold``blob``if_number``polar_restore` |
| 邊緣缺口（輪廓幾何） | 深色背景上的亮色沖壓件，含孔與槽；第四張上緣被咬掉一塊 | Contour find 追蹤外形，filter 只保留最大輪廓，也就是零件；contour geometry 計算深度超過 12 px 的凸性缺陷，即缺口。Contour match 以 Hu moments 與樣本外形資產比對輪廓，用於防止零件錯誤或嚴重變形 | `contour_find``contour_filter``contour_geometry``contour_match``if_number` |
| 圓邊缺口（圓形卡尺） | 亮色圓片有中心孔；第四張右下外緣有 24° 缺口 | 180 個徑向卡尺每 2° 給出半徑與徑向跳動；Profile defects 會對邊緣點擬合圓，並標記低於該圓 3 px 的每一段，或卡尺完全找不到邊緣的位置。缺口會在外緣畫成紅色弧段 | `circular_caliper``profile_defect``if_number` |
| 圓度（形位公差） | 缺口圓片組：亮色圓片有中心孔；第四張右下外緣有 7 px 深缺口 | 180 個徑向卡尺給出邊緣點；Form and position tolerance 擬合最小區域圓（ISO 1101），同心雙圓之間的環寬在 5 px 內即通過。明細也回報最小二乘值與兩個極值點 | `circular_caliper``gdt_measure` |
| 浮凸字元與凹痕（光度立體） | 同一片板件在四向打光下的 2×2 影像，光源來自右、下、左、上；板件有斑駁反射率與浮凸字樣「VS 42」；第四張在字元上方檢查區有凹痕 | 四個 Crop 步驟切出各視角，Photometric stereo 轉成形狀強度圖，斑駁消失後只留下表面形狀，再以檢查區中的像素計數找出單張影像看不到的凹痕。良品答案是空區，所以用像素計數而非 blob 計數判定 | `crop``photometric_stereo``pixel_count` |
| 條碼品質等級（ISO 15415） | 白色標籤含 Data Matrix 與料號；四種印刷品質為乾淨、低對比、模糊且有雜訊，以及靜區有髒汙的符號 | Barcode quality grade 像驗證器一樣量測符號，C 級以上通過；parameters 輸出會說明哪一項參數拉低等級，第四張標籤會失敗 | `barcode_grade` |
| 排除區（組合區域） | 圓規量測板件：亮色板件的深色中心孔會改變大小 | 兩個 Region 步驟畫出孔與標籤區，Region combine 從板件矩形中切除它們，並把組合區域經由區域輸入提供給統計與 blob 步驟。即使孔變大，板件平均值仍保持穩定，因為孔的像素從未計入 | `region_from_shape``region_combine``intensity``in_range``blob` |
| 平場校正（不均勻照明） | 亮色板件在強烈暗角下有深色斑點，角落亮度只有 45%；第四張多了一個大標記 | 除以白參考資產可攤平照明，因此固定門檻能找到所有斑點；側支路用同一門檻跑未校正影像，計數會錯。參考圖由 seed 寫入 | `shading_correct``threshold``blob``if_number` |
| 顏色存在 | 三個色塊；第四張紅色偏橘 | HSV 範圍遮罩進入像素計數，用於典型存在／缺失判定 | `color_range``pixel_count` |
| 顏色驗證 | 同一組影像 | 以距離比對區域平均色與目標色；色彩統計會輸出十六進位色碼給主機系統 | `color_check``color_stats` |
| 條碼 / QR 讀取 | 傾斜標籤含 QR code；第四張沒有印碼 | 最短識別流程：讀碼、檢查是否讀到內容、輸出內容 | `barcode``output` |
| 定位後讀碼 | 大型雜亂背景中有一個移動的小 QR code；第四張無碼 | 示範難讀碼的接線：偵測器找出可能的碼區，ROI follow 移動裁切區，crop 放大後讓解碼器只讀該小區塊。內建偵測器尺寸僅用於示範連接；在線上使用前應先為碼的位置訓練偵測器 | `ai_detect``shape_align``fixture_roi``crop``resize``barcode` |
| 日期碼讀取與驗證（教導字型） | 白色標籤含八位數代碼；第四張有一位數被汙點遮住 | seed 會由 24 行渲染文字教導數字字型，包含分割與小型分類器，完全離線且不需要 OCR 模型檔；Text read 輸出字串與每字元信心度，Text verify 檢查八位數樣板與信心度，並在 NG 影像以紅框標出被汙損的數字 | `ocr_read``ocv_verify` |
| 透視校正條碼標籤 | 同一組影像 | 四點透視校正會先拉正傾斜標籤再讀取，並在序號區做文字存在檢查 | `warp_perspective``barcode``text_presence` |
| 形狀比對定位（任意角度、任意光線） | 非對稱支架：正向、旋轉 37° 且變暗、在雜亂中旋轉 −120°；第四張為不同零件 | Shape match 會評分邊緣方向，因此旋轉、變暗與雜亂中的影像都能以高分找到，並提供給 Locate offset 與 ROI follow；不同零件低於分數下限而走 NG 分支。形狀模型資產由 seed 從第一張圖建立 | `shape_match``shape_align``fixture_roi``intensity` |
| 定位與量測 | 十字標記與亮色帶；第四張亮帶太寬 | 三段式定位補正：template match → locate correction → ROI follow → 卡尺寬度。範本資產由 seed 自動裁切 | `template_match``shape_align``fixture_roi``caliper` |
| 深拉杯量測 | 同心杯緣與壁厚截面；第四張外徑超差 | 完整量測流程：定位、三個跟隨定位的 ROI、外徑與內徑找圓、穿過壁面的**線 ROI**量厚度、同心度，以及多個公差合併判定 | `find_circle``wall_thickness``concentricity``tolerance_judge``bool_logic` |
| 輸送帶取料（單相機） | 六張合成輸送帶影格；零件沿皮帶移動，第一張與最後一張碰到邊界 | 單相機取料交握：分割、邊緣過濾、平台追蹤與確認、格式化 `cls,x,y,z` 文字，以及機械手臂寫出 | `ai_segment``edge_filter``track_objects``format_text``write_modbus` |
| 輸送帶取料（ByteTrack） | 同一組六張輸送帶影格 | 分割工具使用內建 ByteTrack 追蹤器，讓每個零件保有一個 tracker ID；`track_objects` 以追蹤器參考模式依該 ID 確認，而不是自行比對位置 | `ai_segment``edge_filter``track_objects``format_text``write_modbus` |
| 輸送帶取料（立體 Z） | 已知視差的合成輸送帶零件立體影像對 | 立體取料交握：成對取像、分割、邊緣過濾、追蹤確認、由 `stereo_depth` 取得物件頂面 Z、格式化 `cls,x,y,z` 文字，以及機械手臂寫出 | `stereo_grab``ai_segment``edge_filter``track_objects``stereo_depth``format_text``write_modbus` |
| AI 物件計數（官方底模） | 停止標誌；第四張有一個，第五張有三個 | 無需訓練的深度學習：官方底模可直接辨識並判定數量。權重會在首次執行時下載，需要深度學習依賴 | `ai_detect``if_number` |
| AI 實例分割：標誌面積 | 同一組影像 | 分割的聯集遮罩進入像素計數得到總面積，再依門檻判定，是分割接到下游量測的範例 | `ai_segment``pixel_count` |
| 分類：良品 / 缺中心孔（教導模型） | 深色背景上的亮色圓片；第五與第六張缺少中心孔 | 示範教導模型如何進入流程：seed 以 30 張合成樣本與資料增強訓練內建 MLP，成為「Example: classifier (good / missing hole)」，再由 `dl_classify` 判定通過或失敗。整張縮小影像分類適合整體外觀不同的類別 | `dl_classify` |
| 異常偵測：只有良品（教導模型） | 分割教導板件，三張乾淨、兩張有刮痕 | 安裝異常 backbone 時，seed 會以 20 張乾淨板件建立「Example: anomaly (scratch plate)」；`dl_anomaly` 會把每個 patch 與良品記憶庫比對，即使訓練時未曾看過刮痕，刮傷板也會成為異常。沒有 backbone 時範本仍可載入，模型留給您選擇 | `dl_anomaly``if_number` |
| 語意分割：刮痕面積（教導模型） | 有紋理的面板；第四與第五張有刮痕 | seed 以 10 張多邊形標記影像訓練 patch_segment，成為「Example: segmenter (scratch)」，再由 `dl_segment` 依刮痕面積門檻判定 | `dl_segment` |

## 影像與資產位置 {#files}

- 樣本影像：`data/samples/<set>/01.png…`，由 `apps/vision/demo_images.py` 產生。若資料夾已有 PNG，會直接重用。要重新產生時，刪除該資料夾並再次執行 `manage.py seed_demo`。
- 固定影像：每張樣本圖與參考圖只會儲存一次，位置在 `ASSET_DIR/fixed/<sha>.png`，以內容定址，因此重複 seed 不會產生副本，並由範本 graph 參照；`instantiate` 會把 `{SOURCE}` 擷取步驟轉成持有該組影像的 `fixed_image` 步驟。不再建立資料夾來源或影像資產，舊版 seed 留下的「Example: …」資料夾來源與圖片資產在無引用時會移除。
- 資產：由 30 張抖動良品印刷建立的統計範本，從第一張形狀比對影像建立的支架形狀模型，以及教導模型，位於「Examples」群組。兩個定位範本、Golden 列印圖與沖壓件外形會從第一張樣本圖裁成固定影像，平場範本的白參考也是固定影像。
- `seed_demo` 可安全重複執行：既有來源與資產會重用，流程 graph 會更新到目前版本。

## 尚無範本使用的工具 {#not-included}

深度學習：`ai_pose` 需要人物影像，`ai_obb` 需要訓練或 DOTA 風格影像，而 `ai_classify`、`dl_instance` 與 `dl_detect` 的接線方式與已涵蓋的對應工具相同。`dl_classify`、`dl_detect`、`dl_segment` 與 `dl_instance` 都需要先在深度學習教導頁訓練模型資產。`write_modbus` 與 `read_modbus` 需要實際的 Modbus 連線，`python_script` 會執行您自行撰寫的程式碼，而 `save_image` 會在每次執行寫出檔案，不適合放進循環範例。請參考各工具自身說明，以及[深度學習教導](dl.md)與 [Modbus](/docs/modbus.html)。

## 如何維持正確 {#test}

深度學習範本：`tests/test_demo.py` 會實際執行兩個教導模型範本，seed 會在 CPU 上於數秒內完成訓練。三個官方模型接線範本需要深度學習依賴，因此該處只檢查 graph；真正執行由 `VISION_TEST_DL=1 manage.py test tests.test_dl_live` 負責，五張標誌樣本會得到 OK、OK、OK、NG、NG。

`tests/test_demo.py` 每次測試都會把整組範例 seed 到暫存環境，並以對應樣本來源執行每個內建範本，鎖住「每個範本都可執行且沒有節點錯誤」這句話。範本或工具一旦壞掉，測試會立即變紅。
