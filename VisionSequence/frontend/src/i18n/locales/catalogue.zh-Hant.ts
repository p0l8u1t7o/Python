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
      label: 'Modbus/TCP 主站（連到 PLC）',
      description: '平台當客戶端連到 PLC 或設備，讀寫它的線圈與暫存器；也可以輪詢一個位址當觸發來源。',
    },
    modbus_server: {
      label: 'Modbus/TCP 從站（本機開埠等待連入）',
      description: '平台當伺服器開埠，讓 PLC 或上位機來讀寫我們的暫存器；流程把結果寫進去給主站取用。設定觸發位址後，主站寫入旗標就會執行一次流程。伺服器啟動時會自動開埠。',
    },
    tcp_client: { label: 'TCP 文字或 JSON（上位機）' },
    dio_sim: { label: '模擬數位 I/O（只記錄狀態）' },
    plugin: { label: '外掛（自行指定類別路徑）' },
  },
  trainers: {
    mlp_classify: {
      label: '影像分類（MLP）',
      description: '把整張樣本影像（或其裁切）分到您定義的類別。輕量全連接網路，CPU 幾秒就能訓好；產物給「深度學習分類」工具使用。',
    },
    patch_segment: {
      label: '語意分割（輕量）',
      description: '從多邊形標記學會逐像素分類（背景加上您的類別）。區塊特徵加輕量網路，CPU 幾秒完成，匯出成全卷積 ONNX 給「深度學習語意分割」工具。適合由顏色與紋理界定的區域與缺陷。',
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
    dl_segment_demo: { name: '語意分割：刮痕面積（教導模型）', description: '由 seed 訓練的 patch_segment 模型接 dl_segment 刮痕面積門檻與 OK/NG' },
  },
}
