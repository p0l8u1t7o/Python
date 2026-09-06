/**
 * 後端目錄的繁體中文對照（影像來源種類、連線種類、深度學習訓練方式、內建範本）。
 *
 * 後端是英文的唯一事實來源；這裡只翻譯**顯示的文字**，`kind`／`key` 這些**存進資料庫的值一律
 * 保持英文原樣**。沒有對照的項目（外掛）就顯示後端給的英文，這正是外掛作者預期的行為。
 * 由 `lib/catalogueLocale.ts` 疊上去，工具目錄則另有 `tools.zh-Hant.ts`。
 */
export default {
  sourceKinds: {
    folder: { label: '資料夾（循環讀取影像檔）' },
    file: { label: '單一影像檔' },
    synthetic: { label: '合成測試影像' },
    upload: { label: '推送影像（由 API 上傳）' },
    capture: {
      label: '擷取端相機',
      description: '相機所在電腦上的擷取端程式取像後送到平台；同一台電腦會自動走共享記憶體。',
    },
    plugin: { label: '外掛（自行指定類別路徑）' },
  },
  connectionKinds: {
    modbus_tcp: {
      label: 'Modbus TCP 主站（連到設備）',
      description: '平台當客戶端連到任何 Modbus TCP 設備——控制器、驅動器、I/O 模組、上位程式——讀寫它的線圈與暫存器；也可以輪詢一個位址當觸發來源。',
    },
    modbus_server: {
      label: 'Modbus TCP 從站（本機開埠等待連入）',
      description: '平台當伺服器開埠，讓任何 Modbus TCP 主站來讀寫我們的暫存器；流程把結果寫進去給主站取用。設定觸發位址後，主站寫入旗標就會執行一次流程。伺服器啟動時會自動開埠。',
    },
    tcp_client: { label: 'TCP 文字或 JSON（上位機）' },
    tcp_image: {
      label: 'TCP 傳圖（上位機）',
      description: '把流程某一步的影像經一條長連線推給上位程式：13 位元組定長前綴、JSON 表頭（尺寸、編碼、run id、判定與具名輸出）、影像 bytes（JPEG／PNG／原始像素）。',
    },
    plugin: { label: '外掛（自行指定類別路徑）' },
  },
  /** Advanced／Augment 這些分組名稱每個訓練方式共用。 */
  paramGroups: {
    Advanced: '進階',
    Augment: '資料增強',
  },
  /** 四種 YOLO 訓練方式的超參數幾乎相同，共用這一份。 */
  yoloParams: {
    model: { label: '底模', help: 'ultralytics 的模型名稱（第一次使用時下載）或 .pt 檔路徑；填上一次訓練的 best.pt 就會接著它繼續訓練。' },
    epochs: { label: '訓練回合數' },
    imgsz: { label: '影像尺寸', options: { 224: '224（建議）', 320: '320', 480: '480', 640: '640（建議）', 960: '960' } },
    batch: { label: '批次大小' },
    patience: { label: '早停耐心值' },
    lr0: { label: '初始學習率' },
    val_ratio: { label: '驗證集比例' },
    workers: { label: 'DataLoader 執行緒', help: 'Windows 建議填 0；在背景執行緒訓練時最穩。' },
    suggest_conf: { label: '自動標記的信心門檻', help: '還沒訓練前用官方底模提出建議（名稱對不上的會掛在第一個類別，您再修正）；訓練過後改用 best.pt。' },
    degrees: { label: '旋轉角度（±）', help: '隨機旋轉的最大角度；產線上物件方向固定時建議填 0。' },
    fliplr: { label: '水平翻轉機率' },
    mosaic: { label: 'Mosaic 增強', help: '把四張樣本拼成一張訓練影像；樣本少的時候調低。' },
  },
  trainers: {
    mlp_classify: {
      label: '影像分類（MLP）',
      description: '把整張樣本影像（或其裁切）分到您定義的類別。輕量全連接網路，CPU 幾秒就能訓好；產物給「深度學習分類」工具使用。',
      params: {
        input_size: { label: '輸入尺寸', options: { 32: '32x32（最快）', 64: '64x64（建議）', 96: '96×96', 128: '128x128（細節較多）' } },
        hidden: { label: '隱藏層寬度' },
        epochs: { label: '訓練回合數' },
        learning_rate: { label: '學習率' },
        val_split: { label: '驗證集比例', help: '填 0 代表全部拿來訓練，適用於樣本非常少的時候；手動指定為 val 的樣本優先。' },
        augment: { label: '啟用資料增強', help: '只在訓練集加入水平翻轉與亮度抖動的副本；樣本少時有助於泛化。' },
        augment_brightness: { label: '亮度抖動' },
      },
    },
    patch_segment: {
      label: '語意分割（輕量）',
      description: '從多邊形標記學會逐像素分類（背景加上您的類別）。區塊特徵加輕量網路，CPU 幾秒完成，匯出成全卷積 ONNX 給「深度學習語意分割」工具。適合由顏色與紋理界定的區域與缺陷。',
      params: {
        input_size: { label: '工作尺寸', help: '訓練用的尺寸，也是建議的推論尺寸。模型是全卷積的，推論時可以用別的尺寸。', options: { 128: '128（最快）', 192: '192（建議）', 256: '256（細節較多）' } },
        kernel: { label: '感受野', options: { 5: '5×5', 7: '7×7', 9: '9×9' } },
        hidden: { label: '隱藏層寬度' },
        epochs: { label: '訓練回合數' },
        learning_rate: { label: '學習率' },
        samples_per_image: { label: '每張取樣的像素數' },
        augment: { label: '啟用資料增強', help: '每張影像另外取樣一份水平翻轉的版本，標記一併翻轉。' },
      },
    },
    anomaly: {
      label: '異常檢測（只教良品）',
      description: '只用良品影像學會「正常長什麼樣」——不需要缺陷樣本、不需要標記——沒看過的就標成異常。預訓練 backbone 把每張圖變成區塊特徵，記憶庫留一小部分，執行時每個區塊到最近良品區塊的距離就是異常分數。訓練＝抽特徵＋建庫，CPU 幾秒到一分鐘。',
      params: {
        backbone: { label: '特徵抽取器', options: { resnet18: 'ResNet18 layer2+3（ImageNet）' } },
        input_size: { label: '輸入尺寸', options: { 224: '224（最快）', 320: '320（建議）', 448: '448（更細的缺陷）' } },
        coreset_ratio: { label: '記憶庫比例', help: '貪婪子抽樣後保留的良品區塊比例。0.1 兼顧準確與執行速度。' },
        threshold_sigma: { label: '門檻 σ 倍數', help: '自動門檻＝良品自身分數的平均 + σ 倍數 × 標準差。' },
        augment: { label: '資料增強（翻轉與亮度）', help: '每張良品另加一份翻轉與兩份亮度偏移的版本進記憶庫。' },
        augment_brightness: { label: '亮度擾動' },
        blur_sigma: { label: '分數圖平滑' },
        projection_dims: { label: '特徵投影', help: '384 維特徵的固定隨機投影。128 維保留距離排序，執行時間約縮短三倍。', options: { 0: '不投影（384 維，最慢）', 128: '128 維（建議）', 64: '64 維（最快）' } },
      },
    },
    yolo_cls: {
      label: '影像分類（YOLO-cls）',
      description: '一張一類，從 ImageNet 預訓練底模微調 YOLO 分類模型。比內建 MLP 分類準確，但需要 ultralytics（torch）。產物：best.pt 給 YOLO 分類工具、ONNX 給深度學習分類工具。',
    },
    yolo_detect: {
      label: '物件偵測（YOLO）',
      description: '從外框標記訓練 YOLO 偵測模型（多邊形會取外接框），找出每個物件的框與類別。訓練最快、標記成本最低。產物：best.pt 給 YOLO 物件偵測工具、ONNX 給深度學習物件偵測工具。',
    },
    yolo_obb: {
      label: '旋轉框偵測（YOLO-obb）',
      description: '從多邊形（取最小面積旋轉矩形）或外框訓練 YOLO OBB 模型，回傳每個物件的旋轉矩形（中心、尺寸、角度），適合斜擺的零件。產物：best.pt 給 YOLO 旋轉框工具（ONNX 僅供外部使用）。',
    },
    yolo_seg: {
      label: '實例分割（YOLO-seg）',
      description: '從多邊形標記訓練 YOLO 分割模型，找出每個物件的輪廓與類別。需要 ultralytics（torch），建議搭配 NVIDIA GPU。官方底模第一次使用時下載，訓練前也能自動標記（底模提出輪廓，掛在第一個類別）。產物：best.pt 給 YOLO 實例分割工具、ONNX 給深度學習實例分割工具。',
    },
  },
  templates: {
    hole_count: { name: '孔數計數', description: '灰階、去噪、二值化、形態學、斑點計數、數值檢查、OK/NG——含具名輸出與結果影像' },
    exposure: { name: '曝光檢查', description: '縮小、Otsu 二值化、範圍檢查、OK/NG' },
    circle_gauge: { name: '圓量測', description: '找圓、直徑、像素換算 mm、公差判定——另含扇形 ROI 圓弧擬合與橢圓真圓度' },
    edge_angle: { name: '邊線夾角', description: '兩次找直線求夾角公差、交點，以及 45 度倒角量測' },
    golden_compare: { name: '印刷良品比對', description: '與良品範本做差異，抓重印、髒污與缺印；範本資產由範例樣本影像建立' },
    fft_defect: { name: '布面瑕疵', description: '頻域低通去掉週期性織紋，剩下的就是刮痕；再用遮罩取出缺陷面積' },
    preprocess_lab: { name: '前處理與量測實驗室', description: '位深、查表、濾波、翻轉的影像鏈，再走一遍線剖面、統計、直方圖與邊緣密度' },
    geometry_count: { name: '圓與直線', description: 'Hough 圓計數、Hough 直線以清單計數，再用兩次找圓求中心距' },
    color_presence: { name: '顏色存在', description: '顏色範圍遮罩接像素計數，再依門檻判定' },
    color_verify: { name: '顏色驗證', description: '區域平均色與目標色的距離比對，色彩統計回報十六進位色碼' },
    barcode_read: { name: '條碼／QR 讀取', description: '讀碼、檢查有沒有讀到、輸出內容' },
    label_read: { name: '含透視校正的條碼標籤', description: '四點透視校正把歪斜的標籤拉正再讀，另加序號區的文字存在檢查' },
    locate_measure: { name: '定位與量測', description: '範本比對、定位補正、ROI 跟隨、卡尺寬度、公差判定' },
    cup_measure: { name: '深沖杯件量測', description: '範本比對、定位補正、三個 ROI 跟隨、內外圓與壁厚、同心度、三個公差判定、具名輸出、OK/NG' },
    yolo_count: { name: 'YOLO 物件計數（官方底模）', description: 'yolo_detect 以 COCO 官方底模找停止標誌並判定數量。免訓練、自動用 GPU（需要深度學習依賴）' },
    yolo_area: { name: 'YOLO 實例分割：標誌面積', description: 'yolo_segment 的聯集遮罩接像素計數與面積門檻，示範分割接量測（需要深度學習依賴）' },
    dl_classify_demo: { name: '分類：良品／缺孔（教導模型）', description: '由 seed 訓練的內建 MLP 分類器接 dl_classify 判定——示範教導出來的模型怎麼進流程' },
    gear_teeth: { name: '圓周齒數（極座標展開）', description: '極座標展開把齒圈攤平成長條圖，二值化與 blob 數齒，極座標還原把每顆齒標回原圖' },
    contour_defect: { name: '崩邊檢測（輪廓幾何）', description: '輪廓萃取、篩出工件本體、輪廓幾何數超過 12 px 的凸缺陷、OK/NG，另以 Hu 矩與範例外形比對' },
    circular_defect: { name: '圓盤崩邊（圓形卡尺）', description: '180 把徑向卡尺給每個角度的半徑與跳動量；序列缺陷擬合圓後把每處凹陷或打空的卡尺標成崩邊，畫成圓緣上的紅弧' },
    exclusion_zone: { name: '排除區（組合區域）', description: '兩個畫好的區域由區域組合從板面矩形挖掉，經區域輸入埠餵給統計與 blob 步驟，孔內像素完全不算' },
    shading: { name: '平場校正（打光不均）', description: '除以白板參考資產，讓同一個固定門檻在角落也找得到暗污點；旁支示範不校正時同一門檻的誤判' },
    stat_compare: { name: '統計良品比對', description: '30 張良品建的逐像素平均與變異，偏離 4 個標準差以上就是缺陷，光線與紋理變動不再逼門檻放鬆' },
    shape_locate: { name: '形狀比對定位（任意角度、任意光線）', description: '以邊緣方向比對找出旋轉、變暗、雜物中的工件，接定位補正與 ROI 跟隨，並拒絕不同的零件' },
    anomaly_demo: { name: '異常檢測：只教良品（教導模型）', description: 'seed 由 20 張乾淨鋁板建的異常模型把每個區塊與良品記憶庫比對，沒看過的刮痕就是異常（需要異常檢測 backbone）' },
    dl_segment_demo: { name: '語意分割：刮痕面積（教導模型）', description: '由 seed 訓練的 patch_segment 模型接 dl_segment 刮痕面積門檻與 OK/NG' },
  },
}
