/**
 * 後端目錄的繁體中文對照（影像來源種類、連線種類、深度學習訓練方式、內建範本）。
 *
 * 後端是英文的唯一事實來源；這裡只翻譯**顯示的文字**，`kind`／`key` 這些**存進資料庫的值一律
 * 保持英文原樣**。沒有對照的項目（外掛）就顯示後端給的英文，這正是外掛作者預期的行為。
 * 由 `lib/catalogueLocale.ts` 疊上去，工具目錄則另有 `tools.zh-Hant.ts`。
 */
export default {
  inspectKinds: {
  "measure_diameter": {
    "label": "量直徑",
    "help": "尋找圓形邊緣，並依規格檢查直徑或真圓度。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "check": "直徑",
          "roundness": "真圓度"
        }
      },
      "roi": {
        "label": "檢測區域",
        "help": "在目標邊緣周圍繪製圓形或環形搜尋區域。"
      },
      "edge": {
        "label": "量測邊緣",
        "options": {
          "outer": "外緣",
          "inner": "內緣"
        }
      },
      "polarity": {
        "label": "邊緣極性",
        "options": {
          "any": "任意",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "calibration": {
        "label": "標定",
        "help": "選填；留空時使用像素量測。"
      },
      "nominal": {
        "label": "標稱值"
      },
      "upper_tol": {
        "label": "上公差"
      },
      "lower_tol": {
        "label": "下公差"
      },
      "unit": {
        "label": "單位",
        "options": {
          "px": "像素",
          "mm": "毫米"
        }
      },
      "result_name": {
        "label": "結果名稱",
        "help": "執行結果中使用的名稱。"
      },
      "required": {
        "label": "必要任務",
        "help": "必要任務會納入檢測彙總。"
      },
      "locator": {
        "label": "定位任務",
        "help": "選填；用於位置修正的定位任務。"
      },
      "num_rays": {
        "label": "掃描線數"
      },
      "method": {
        "label": "定位方式",
        "options": {
          "template": "範本",
          "shape": "形狀模型",
          "register": "註冊範例"
        },
        "help": "形狀與註冊範例定位將在後續版本提供。"
      },
      "template_images": {
        "label": "定位標記",
        "help": "從教導工件裁切出的固定參考影像。"
      },
      "threshold": {
        "label": "分數門檻"
      },
      "allow_rotation": {
        "label": "允許旋轉"
      },
      "angle_range": {
        "label": "旋轉範圍"
      },
      "ref_x": {
        "label": "參考 X"
      },
      "ref_y": {
        "label": "參考 Y"
      },
      "ref_angle": {
        "label": "參考角度"
      }
    }
  },
  "locate_part": {
    "label": "定位工件",
    "help": "尋找教導範本，提供下游任務的位置修正。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "check": "直徑",
          "roundness": "真圓度"
        }
      },
      "roi": {
        "label": "檢測區域",
        "help": "留空時搜尋整張影像。"
      },
      "edge": {
        "label": "量測邊緣",
        "options": {
          "outer": "外緣",
          "inner": "內緣"
        }
      },
      "polarity": {
        "label": "邊緣極性",
        "options": {
          "any": "任意",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "calibration": {
        "label": "標定",
        "help": "選填；留空時使用像素量測。"
      },
      "nominal": {
        "label": "標稱值"
      },
      "upper_tol": {
        "label": "上公差"
      },
      "lower_tol": {
        "label": "下公差"
      },
      "unit": {
        "label": "單位",
        "options": {
          "px": "像素",
          "mm": "毫米"
        }
      },
      "result_name": {
        "label": "結果名稱",
        "help": "執行結果中使用的名稱。"
      },
      "required": {
        "label": "必要任務",
        "help": "必要任務會納入檢測彙總。"
      },
      "locator": {
        "label": "定位任務",
        "help": "選填；用於位置修正的定位任務。"
      },
      "num_rays": {
        "label": "掃描線數"
      },
      "method": {
        "label": "定位方式",
        "options": {
          "template": "範本",
          "shape": "形狀模型",
          "register": "註冊範例"
        },
        "help": "選擇範本、形狀模型或註冊影像定位。"
      },
      "template_images": {
        "label": "定位標記",
        "help": "從教導工件裁切出的固定參考影像。"
      },
      "threshold": {
        "label": "分數門檻"
      },
      "allow_rotation": {
        "label": "允許旋轉"
      },
      "angle_range": {
        "label": "旋轉範圍"
      },
      "ref_x": {
        "label": "參考 X"
      },
      "ref_y": {
        "label": "參考 Y"
      },
      "ref_angle": {
        "label": "參考角度"
      },
      "model": {
        "label": "形狀模型"
      }
    }
  },
  "check_presence": {
    "label": "檢查有無",
    "help": "使用目前影像設定並執行此檢測。",
    "fields": {
      "method": {
        "label": "方式",
        "options": {
          "template": "範本",
          "blob": "物件",
          "print": "印字"
        }
      },
      "roi": {
        "label": "檢測區域"
      },
      "expected": {
        "label": "期望內容",
        "options": {
          "present": "應存在",
          "absent": "應不存在"
        }
      },
      "template_images": {
        "label": "參考影像"
      },
      "threshold": {
        "label": "門檻"
      },
      "threshold_method": {
        "label": "門檻方式",
        "options": {
          "otsu": "自動",
          "fixed": "固定",
          "hysteresis": "雙門檻",
          "soft": "柔和門檻",
          "none": "不處理"
        }
      },
      "blob_threshold": {
        "label": "亮度門檻"
      },
      "polarity": {
        "label": "目標極性",
        "options": {
          "bright": "亮",
          "dark": "暗"
        }
      },
      "min_area": {
        "label": "最小面積"
      },
      "max_area": {
        "label": "最大面積"
      },
      "print_polarity": {
        "label": "印字極性",
        "options": {
          "dark": "暗",
          "bright": "亮"
        }
      },
      "min_ratio": {
        "label": "筆畫比例下限"
      },
      "max_ratio": {
        "label": "筆畫比例上限"
      },
      "required": {
        "label": "必要任務"
      },
      "locator": {
        "label": "定位任務"
      }
    }
  },
  "count_objects": {
    "label": "數數量",
    "help": "使用目前影像設定並執行此檢測。",
    "fields": {
      "roi": {
        "label": "檢測區域"
      },
      "threshold_method": {
        "label": "門檻方式",
        "options": {
          "otsu": "自動",
          "fixed": "固定",
          "hysteresis": "雙門檻",
          "soft": "柔和門檻",
          "none": "不處理"
        }
      },
      "threshold": {
        "label": "門檻"
      },
      "polarity": {
        "label": "目標極性",
        "options": {
          "bright": "亮",
          "dark": "暗"
        }
      },
      "min_area": {
        "label": "最小面積"
      },
      "max_area": {
        "label": "最大面積"
      },
      "min_circularity": {
        "label": "圓形度下限"
      },
      "min_count": {
        "label": "最少數量"
      },
      "max_count": {
        "label": "最多數量"
      },
      "result_name": {
        "label": "結果名稱"
      },
      "required": {
        "label": "必要任務"
      },
      "locator": {
        "label": "定位任務"
      }
    }
  },
  "inspect_circular_surface": {
    "label": "圓周表面檢測",
    "help": "使用目前影像設定並執行此檢測。",
    "fields": {
      "roi": {
        "label": "檢測區域"
      },
      "direction": {
        "label": "方向",
        "options": {
          "ccw": "逆時針",
          "cw": "順時針"
        }
      },
      "start_angle": {
        "label": "起始角度"
      },
      "polarity": {
        "label": "目標極性",
        "options": {
          "any": "不限",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "threshold": {
        "label": "門檻"
      },
      "max_defects": {
        "label": "允許缺陷數"
      },
      "search": {
        "label": "搜尋範圍"
      },
      "geometry": {
        "label": "缺陷位置表示",
        "options": {
          "centres": "中心點",
          "boxes": "外框",
          "spans": "起訖點"
        }
      },
      "required": {
        "label": "必要任務"
      },
      "locator": {
        "label": "定位任務"
      },
      "min_length": {
        "label": "最短缺陷長度",
        "help": "所有缺陷均適用，包括斷裂。弧長以教導環域的中線半徑計算。"
      },
      "unit": {
        "label": "長度單位",
        "options": {
          "deg": "角度",
          "mm": "毫米"
        }
      },
      "calibration": {
        "label": "標定"
      },
      "defect_direction": {
        "label": "缺陷方向",
        "options": {
          "both": "雙向",
          "inward": "向內缺料",
          "outward": "向外凸出"
        }
      },
      "result_name": {
        "label": "結果名稱"
      }
    }
  },
  "inspect_edge_defect": {
    "label": "邊緣缺陷檢測",
    "help": "使用目前影像設定並執行此檢測。",
    "fields": {
      "method": {
        "label": "方式",
        "options": {
          "simple": "直線或圓弧",
          "freeform": "自由輪廓"
        }
      },
      "roi": {
        "label": "檢測區域"
      },
      "reference": {
        "label": "參考幾何來源",
        "help": "選填上游直線或圓形來源；有接線時優先於繪製的區域。"
      },
      "mode": {
        "label": "模式",
        "options": {
          "single": "單邊",
          "pair": "成對"
        }
      },
      "polarity": {
        "label": "目標極性",
        "options": {
          "any": "不限",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "pair_polarity": {
        "label": "帶狀區域極性",
        "options": {
          "any": "不限",
          "bright": "亮",
          "dark": "暗"
        }
      },
      "search": {
        "label": "搜尋範圍"
      },
      "threshold": {
        "label": "門檻"
      },
      "min_width": {
        "label": "最小缺陷寬度"
      },
      "direction": {
        "label": "方向",
        "options": {
          "both": "兩側",
          "inward": "向內",
          "outward": "向外"
        }
      },
      "width_min": {
        "label": "寬度下限"
      },
      "width_max": {
        "label": "寬度上限"
      },
      "max_defects": {
        "label": "允許缺陷數"
      },
      "baseline": {
        "label": "理想邊緣",
        "options": {
          "fit": "擬合",
          "median": "中位數",
          "reference": "參考幾何"
        }
      },
      "model": {
        "label": "輪廓模型"
      },
      "required": {
        "label": "必要任務"
      },
      "locator": {
        "label": "定位任務"
      }
    }
  },
  "measure_distance": {
    "label": "量邊距",
    "help": "使用目前影像設定並執行此檢測。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "edge_pair": "邊對",
          "hole_centres": "兩孔中心"
        }
      },
      "roi": {
        "label": "檢測區域"
      },
      "roi_a": {
        "label": "孔 A 區域"
      },
      "roi_b": {
        "label": "孔 B 區域"
      },
      "polarity": {
        "label": "目標極性",
        "options": {
          "any": "不限",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "edge_pair": {
        "label": "邊對選擇",
        "options": {
          "first_last": "第一條與最後一條",
          "widest": "最寬",
          "narrowest": "最窄",
          "strongest": "最強"
        }
      },
      "pair_polarity": {
        "label": "帶狀區域極性",
        "options": {
          "any": "不限",
          "bright": "亮",
          "dark": "暗"
        }
      },
      "nominal": {
        "label": "標稱值"
      },
      "upper_tol": {
        "label": "上公差"
      },
      "lower_tol": {
        "label": "下公差"
      },
      "unit": {
        "label": "單位",
        "options": {
          "px": "像素",
          "mm": "毫米"
        }
      },
      "result_name": {
        "label": "結果名稱"
      },
      "calibration": {
        "label": "標定"
      },
      "required": {
        "label": "必要任務"
      },
      "locator": {
        "label": "定位任務"
      }
    }
  },
  "read_and_verify": {
    "label": "讀取與驗證",
    "help": "使用目前影像設定並執行此檢測。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "code": "條碼",
          "text": "文字"
        }
      },
      "roi": {
        "label": "檢測區域"
      },
      "types": {
        "label": "碼別",
        "options": {
          "all": "全部",
          "qr": "QR 碼",
          "2d": "二維碼",
          "1d": "一維碼"
        }
      },
      "expected": {
        "label": "期望內容"
      },
      "font_model": {
        "label": "字型模型"
      },
      "charset": {
        "label": "字元集",
        "options": {
          "alnum": "英數字",
          "digits": "數字",
          "upper": "大寫字母與數字",
          "any": "不限",
          "custom": "自訂"
        }
      },
      "custom_charset": {
        "label": "自訂字元集"
      },
      "polarity": {
        "label": "目標極性",
        "options": {
          "dark_on_light": "亮底暗字",
          "light_on_dark": "暗底亮字"
        }
      },
      "min_confidence": {
        "label": "最低信心"
      },
      "pattern": {
        "label": "位置樣板"
      },
      "verify_mode": {
        "label": "比對方式",
        "options": {
          "exact": "完全相同",
          "contains": "包含",
          "regex": "正規表示式"
        }
      },
      "result_name": {
        "label": "結果名稱"
      },
      "required": {
        "label": "必要任務"
      },
      "locator": {
        "label": "定位任務"
      }
    }
  }
},
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
    serial: {
      label: '串口文字設備',
      description: '透過串口收送逐行文字或十六進位位元組。',
    },
    udp: {
      label: 'UDP 文字設備',
      description: '把逐行文字或十六進位位元組送到 UDP 端點，也可開本機埠接收文字行。',
    },
    tcp_server_text: {
      label: 'TCP 文字設備伺服器',
      description: '本機開埠等待設備連進來，收送逐行文字或十六進位位元組。',
    },
    light: {
      label: '光源控制器',
      description: '透過串口或 TCP 送出光源控制命令，可設定亮度、開燈與關燈樣板。',
    },
    plugin: { label: '外掛（自行指定類別路徑）' },
  },
  /** Advanced／Augment 這些分組名稱每個訓練方式共用。 */
  paramGroups: {
    Advanced: '進階',
    Augment: '資料增強',
  },
  /** 四種神經網路訓練方式的超參數幾乎相同，共用這一份。 */
  sharedParams: {
    model: { label: '底模大小', help: '預訓練的起點（第一次使用時下載）；越大越準但訓練與執行越慢。透過 API 也接受 .pt 檔路徑。', options: { n: 'Nano（最快，預設）', s: 'Small', m: 'Medium', l: 'Large', x: 'Extra large（最準，最慢）' } },
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
    retrieval: {
      label: '影像檢索庫',
      description: '把已標記影像建立成參考庫；日後新增類別只需加入新影像。',
      params: {
        input_size: { label: '輸入尺寸', help: '新增參考圖時使用的方形尺寸。' },
        topk: { label: '投票數', help: '用幾張最接近的參考圖決定最終類別。' },
        augment: { label: '儲存輕度變化', help: '為每張已標記影像額外保存鏡射與小角度參考。' },
        augment_angle: { label: '傾斜角度', help: '儲存輕度變化時使用的小角度。' },
        projection_dims: { label: '壓縮參考庫', options: { 0: '關閉', 64: '小型', 128: '標準' } },
        backbone_path: { label: '參考比對檔', help: '測試用內部檔案覆寫。' },
      },
    },
    ai_cls: {
      label: '影像分類（AI）',
      description: '一張一類，從 ImageNet 預訓練底模微調 分類網路。比內建 MLP 分類準確，但需要深度學習加購包。產物：訓練好的權重給 AI 分類工具、ONNX 給深度學習分類工具。',
    },
    ai_detect: {
      label: '物件偵測（AI）',
      description: '從外框標記訓練 偵測網路（多邊形會取外接框），找出每個物件的框與類別。訓練最快、標記成本最低。產物：訓練好的權重給 AI 物件偵測工具、ONNX 給深度學習物件偵測工具。',
    },
    ai_obb: {
      label: '旋轉框偵測（AI）',
      description: '從多邊形（取最小面積旋轉矩形）或外框訓練 旋轉框網路，回傳每個物件的旋轉矩形（中心、尺寸、角度），適合斜擺的零件。產物：訓練好的權重給 AI 旋轉框工具（ONNX 僅供外部使用）。',
    },
    ai_seg: {
      label: '實例分割（AI）',
      description: '從多邊形標記訓練 實例分割網路，找出每個物件的輪廓與類別。需要深度學習加購包，建議搭配 NVIDIA GPU。官方底模第一次使用時下載，訓練前也能自動標記（底模提出輪廓，掛在第一個類別）。產物：訓練好的權重給 AI 實例分割工具、ONNX 給深度學習實例分割工具。',
    },
  },
  templates: {
    queue_handoff: {"name": "推入並配對工件", "description": "交接量測值與影像後配對、合併判定；尚無實際現場情境驗證。"},
    character_count: { name: '散亂字元計數', description: '在直線、曲線或散亂排列中偵測六個單字元' },
    seal_width: { name: '自由輪廓膠道寬度', description: '量測曲線膠道的兩側，排除縮窄或斷裂區段' },
    point_fitting: { name: '由邊緣點擬合幾何', description: '由量測邊界擬合直線、圓與橢圓，要求三項結果完整並計算圓面積' },
    polar_edge_check: { name: '展開並還原圓周缺陷', description: '檢查展開後的直邊，僅將檢出的缺口中心映回原圖' },
    absence_check: { name: '禁區異物檢查', description: '區域應保持無物件，出現異物即判 NG' },
    list_postprocess: { name: 'Blob 結果排序與挑選', description: '依面積過濾 blob 清單、掃描順序排序、挑出最大件、分級並合併中心點' },
    boxes_cleanup: { name: '重疊匹配合併與禁區排除', description: 'template_match 的多個結果先合併、依尺寸與分數過濾，再檢查是否壓到禁區' },
    array_placement: { name: '元件陣列缺位檢查', description: '把 blob 中心校正成 3 x 4 陣列，回報缺格位置並判定 OK/NG' },
    label_map_count: { name: '多色分割轉計數', description: '紅、綠、藍三段 HSV 範圍轉成 label map，再由 label-map blob 統計各色數量' },
    color_sample_classify: { name: '固定樣本色分類', description: '把 ROI 顏色直方圖與紅、綠、藍固定色票比對，相似度不足就判 NG' },
    plate_corners: { name: '矩形板角點與歪斜', description: '直接找矩形四邊，也用四條邊線重建四角，板寬或歪斜超差就判 NG' },
    parallel_edges: { name: '槽寬與條紋數', description: '成對邊緣搜尋量槽寬，另一支多線搜尋統計參考條紋數' },
    hole_matrix: { name: '孔矩陣完整性', description: '3 x 3 圓矩陣回報每個孔心與缺格索引，缺孔即 NG' },
    edge_trend_peaks: { name: '邊緣趨勢與剖面峰值', description: '沿教導直邊佈卡尺找局部凸起，同圖剖面搜尋確認四個亮峰' },
    outline_defect: { name: '教導輪廓缺陷比對', description: '範本定位補正工件姿態，再用良品輪廓模型檢出沖壓邊缺料' },
    path_edge_search: { name: '沿路徑搜尋邊緣', description: '沿教導路徑放卡尺確認亮膠條連續，回報缺邊索引' },
    focus_gate: { name: '檢查前焦距閘門', description: 'sharpness 分數與雜訊估計先擋下模糊影像，再進入後續檢查' },
    temporal_frames: { name: '跨幀平均與前幀差異', description: '累積兩幀平均，同時讀取前一幀做差異檢查；第一幀沒有快取會正常 not_found' },
    roi_process_paste: { name: '處理區域後貼回', description: '裁切 ROI 後做 LUT 與濾波，再貼回整張影像並在完整畫面上檢查' },
    manual_undistort_world: { name: '手動校正與零件座標', description: '手動鏡頭修正後找兩孔、建立零件座標，並用示範像素比例標定換算 mm' },
    camera_mapping: { name: '映射到第二相機', description: '在 A 相機找孔心，透過示範仿射標定映射成 B 相機座標並格式化輸出' },
    pick_offset: { name: '教導姿態取料補正', description: '範本比對找到教導姿態，grab 模式補正並輸出實際取料座標' },
    fixture_rerun: { name: '整張回正後重跑量測', description: '定位後把整張影像拉回教導姿態，固定座標 ROI 可直接重複量測' },
    stitch_two_views: { name: '雙視野拼接計數', description: '左視野與右側固定視野拼成 1 x 2 影像，再跨兩相機統計零件' },
    variable_switch: { name: '依變數切換配方', description: '讀取配方變數後用 switch 走不同門檻分支，並以 sandbox 覆蓋層累計檢查數' },
    tile_for_each: { name: '影像切片逐格巡檢', description: '將影像切成 2 x 2，for_each 逐格呼叫子流程，另示範直接 call_flow 接線' },
    script_measure: { name: '自訂 Python 量測', description: 'blob 量測結果交給核准腳本計算長寬比與填滿率，再做範圍判定' },
    code_message_rules: { name: '解碼、拆訊息與比對', description: '讀取 QR payload，拆出批號與料號，用正規表示式驗證批號並格式化回覆' },
    io_sequence: { name: '燈源、相機 I/O 與設備訊號', description: '相機設定、燈源、站台輸出、相機輸出與 Modbus 讀取在缺連線時都降級為警告' },
    outputs_bundle: { name: '記錄、存圖、送圖與觸發', description: '格式化結果、寫入 CSV、NG 存圖、送出結果影像並非同步觸發後續流程' },
    register_classes: {"name": "註冊多類別計數", "description": "各註冊類別恰好三個才合格，無需訓練。需要深度學習加購包。"},
    register_segment: {"name": "註冊紋理分割", "description": "使用前景與背景樣本尋找不規則目標紋理。需要深度學習加購包。"},
    register_count: { name: '以註冊圖計數零件', description: '由一張零件裁切圖尋找相似目標，恰好三個才合格，無需訓練。需要深度學習加購包。' },
    form_tolerance: { name: '真圓度（形位公差）', description: '180 把徑向卡尺取邊緣點，形位公差以最小區域圓（ISO 1101）評真圓度，兩同心圓的環寬在 5 px 內合格——崩邊的圓盤不合格' },
    emboss_defect: { name: '刻印字與凹坑（光度立體）', description: '四個裁切把四燈 2×2 拼圖拆開，光度立體合成形狀強度圖，檢查區的像素計數找出單張看不見的凹坑' },
    barcode_grade: { name: '條碼品質分級（ISO 15415）', description: '像驗證器一樣替標籤上的 Data Matrix 評級——對比、調變、固定圖形損傷、軸向與格點不均勻、未用錯誤更正——C 級以上合格，髒污的符號不合格' },
    hole_count: { name: '孔數計數', description: '灰階、去噪、二值化、形態學、斑點計數、數值檢查、OK/NG——含具名輸出與結果影像' },
    exposure: { name: '曝光檢查', description: '縮小、Otsu 二值化、範圍檢查、OK/NG' },
    circle_gauge: { name: '圓量測', description: '找圓、直徑、像素換算 mm、公差判定——另含扇形 ROI 圓弧擬合與橢圓真圓度' },
    edge_angle: { name: '邊線夾角', description: '兩次找直線求夾角公差、交點，以及 45 度倒角量測' },
    golden_compare: { name: '印刷良品比對', description: '與良品範本做差異，抓重印、髒污與缺印；良品圖隨範本附帶（固定影像）' },
    fft_defect: { name: '布面瑕疵', description: '頻域低通去掉週期性織紋，剩下的就是刮痕；再用遮罩取出缺陷面積' },
    preprocess_lab: { name: '前處理與量測實驗室', description: '位深、查表、濾波、翻轉的影像鏈，再走一遍線剖面、統計、直方圖與邊緣密度' },
    geometry_count: { name: '圓與直線', description: 'Hough 圓計數、Hough 直線以清單計數，再用兩次找圓求中心距' },
    color_presence: { name: '顏色存在', description: '顏色範圍遮罩接像素計數，再依門檻判定' },
    color_verify: { name: '顏色驗證', description: '區域平均色與目標色的距離比對，色彩統計回報十六進位色碼' },
    barcode_read: { name: '條碼／QR 讀取', description: '讀碼、檢查有沒有讀到、輸出內容' },
    guided_code_read: { name: '定位後讀碼', description: '先以範本比對找到碼區，讓 ROI 跟著移動，裁切放大後再解碼；教導的偵測模型可經 matches 埠接進同一條接線' },
    label_read: { name: '含透視校正的條碼標籤', description: '四點透視校正把歪斜的標籤拉正再讀，另加序號區的文字存在檢查' },
    locate_measure: { name: '定位與量測', description: '範本比對、定位補正、ROI 跟隨、卡尺寬度、公差判定' },
    cup_measure: { name: '深沖杯件量測', description: '範本比對、定位補正、三個 ROI 跟隨、內外圓與壁厚、同心度、三個公差判定、具名輸出、OK/NG' },
    ai_count: { name: 'AI 物件計數（官方底模）', description: 'ai_detect 以 COCO 官方底模找停止標誌並判定數量。免訓練、自動用 GPU（需要深度學習依賴）' },
    ai_area: { name: 'AI 實例分割：標誌面積', description: 'ai_segment 的聯集遮罩接像素計數與面積門檻，示範分割接量測（需要深度學習依賴）' },
    conveyor_pick: { name: '輸送帶取料（單相機）', description: '實例分割、邊界排除、追蹤確認與逐筆文字輸出，只在物件第一次確認時送出 x、y、z。' },
    conveyor_pick_bytetrack: { name: '輸送帶取料（ByteTrack）', description: '分割工具內建 ByteTrack 追蹤器給每個物件穩定的追蹤 ID，邊界排除後以追蹤 ID 確認，只在物件第一次確認時送出 x、y、z。' },
    conveyor_pick_stereo: { name: '輸送帶取料（雙視野）', description: '雙視野取像、實例分割、邊界排除、追蹤確認、stereo_depth 量 Z，並送出 x、y、z。' },
    dl_classify_demo: { name: '分類：良品／缺孔（教導模型）', description: '由 seed 訓練的內建 MLP 分類器接 dl_classify 判定——示範教導出來的模型怎麼進流程' },
    gear_teeth: { name: '圓周齒數（極座標展開）', description: '極座標展開把齒圈攤平成長條圖，二值化與 blob 數齒，極座標還原把每顆齒標回原圖' },
    contour_defect: { name: '崩邊檢測（輪廓幾何）', description: '輪廓萃取、篩出工件本體、輪廓幾何數超過 12 px 的凸缺陷、OK/NG，另以 Hu 矩與範例外形比對' },
    date_code: { name: '日期碼讀取與驗證（教導字型）', description: 'seed 教的字型讀出日期碼（切分＋逐字分類，完全離線），字串驗證比對 8 位數字圖樣與逐字信心，被污點蓋住的字以紅框標出' },
    circular_defect: { name: '圓盤崩邊（圓形卡尺）', description: '180 把徑向卡尺給每個角度的半徑與跳動量；序列缺陷擬合圓後把每處凹陷或打空的卡尺標成崩邊，畫成圓緣上的紅弧' },
    exclusion_zone: { name: '排除區（組合區域）', description: '兩個畫好的區域由區域組合從板面矩形挖掉，經區域輸入埠餵給統計與 blob 步驟，孔內像素完全不算' },
    shading: { name: '平場校正（打光不均）', description: '除以白板參考資產，讓同一個固定門檻在角落也找得到暗污點；旁支示範不校正時同一門檻的誤判' },
    stat_compare: { name: '統計良品比對', description: '30 張良品建的逐像素平均與變異，偏離 4 個標準差以上就是缺陷，光線與紋理變動不再逼門檻放鬆' },
    shape_locate: { name: '形狀比對定位（任意角度、任意光線）', description: '以邊緣方向比對找出旋轉、變暗、雜物中的工件，接定位補正與 ROI 跟隨，並拒絕不同的零件' },
    anomaly_demo: { name: '異常檢測：只教良品（教導模型）', description: 'seed 由 20 張乾淨鋁板建的異常模型把每個區塊與良品記憶庫比對，沒看過的刮痕就是異常（需要異常檢測 backbone）' },
    dl_segment_demo: { name: '語意分割：刮痕面積（教導模型）', description: '由 seed 訓練的 patch_segment 模型接 dl_segment 刮痕面積門檻與 OK/NG' },
    ai_classify_demo: { name: '庫存分類器閘門', description: 'ai_classify 先輸出庫存模型標籤，再用 string_match 依標籤分流判定；實務可改用教導模型或 pass_labels' },
    ai_obb_demo: { name: '傾斜工件的旋轉框', description: 'ai_obb 找旋轉外框，list_sort 依角度排序，再由 format_text 組成角度報表' },
    ai_pose_demo: { name: '關鍵點與幾何', description: 'ai_pose 輸出姿態與關鍵點，本範例用人數閘門示範，也可把關鍵點接到幾何量測' },
    dl_detect_instance_demo: { name: '教導式偵測與實例模型', description: 'dl_detect 與 dl_instance 並排，模型資產留空，供深度學習教導頁訓練後選用' },
    dl_retrieval_demo: { name: '免重訓擴充的檢索庫', description: '三類參考圖建立檢索庫，預期標籤相符走 OK，低相似度走 not_matched' },
    multi_light_surface: { name: '四向打光融合表面缺陷', description: '每張樣本是同一表面四個打光方向的 2×2 拼圖：裁四格進 multi_light_fuse（陰影模式）找只在強起伏才出現的刮痕；multi_light_grab 示範產線接法' },
  },
}
