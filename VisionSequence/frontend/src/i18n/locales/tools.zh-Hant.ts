/**
 * Tool catalogue in Traditional Chinese.
 *
 * The backend catalogue is English — that is the source of truth (`apps/vision/tools/`). This file
 * translates it for the Chinese interface: `lib/toolLocale.ts` overlays it, and a tool with no entry
 * (a folder plugin, say) keeps whatever wording the backend sent.
 *
 * Generated from the catalogue; keep it in step when tool wording changes.
 */
export default {
  trigger_flow: {
    label: '觸發流程',
    description: '從目前執行中啟動另一條流程。非同步只排隊後繼續；同步會在安全容量下等待子流程結果。',
    params: {
      target_flow_id: { label: '目標流程', help: '選擇下一條要執行的流程；圖中保存的是流程 id。' },
      mode: { label: '模式', options: { async: '非同步：排隊後繼續', sync: '同步：等待結果' } },
      timeout_ms: { label: '同步逾時' },
      pass_outputs: { label: '傳遞具名輸出' },
      pass_image: { label: '傳遞影像' },
    },
    ports: { image: '影像', run_id: '執行 ID', judge: '判定', ok: 'OK', ng: 'NG', failed: '失敗' },
  },
  call_flow: {
    label: '呼叫流程',
    description: '在目前執行中同行程執行另一條流程；不排隊、不建立執行紀錄，也不累計統計。',
    params: {
      target_flow_id: { label: '目標流程', help: '選擇要在目前執行內呼叫的流程；圖中保存的是流程 id。' },
      prefix: { label: '輸出前綴', help: '子流程具名輸出併回目前執行時，加在每個名稱前方。' },
      pass_outputs: { label: '傳遞具名輸出' },
      pass_image: { label: '傳遞影像' },
      timeout_ms: { label: '逾時', help: '0 表示使用父流程剩餘時間。' },
    },
    ports: { image: '影像', judge: '判定', ok: 'OK', ng: 'NG', failed: '失敗', duration_ms: '耗時', outputs: '子流程輸出' },
  },
  for_each: {
    label: '逐項執行',
    description: '對每個比對結果、區域或影像呼叫同一條子流程，並彙總逐項判定。',
    params: {
      target_flow_id: { label: '目標流程' },
      source: { label: '項目來源', options: { auto: '自動', regions: '區域', matches: '比對結果', images: '影像' } },
      max_items: { label: '最多項目' },
      on_error: { label: '項目失敗時', options: { continue: '繼續', stop: '停止' } },
      pass_outputs: { label: '傳遞具名輸出' },
      timeout_ms: { label: '逾時', help: '0 表示使用父流程剩餘時間。' },
    },
    ports: {
      image: '影像', regions: '區域', matches: '比對結果', images: '影像',
      count: '數量', ok_count: 'OK 數量', ng_count: 'NG 數量', items: '逐項結果', all_ok: '全部 OK',
      ok: '全部 OK', ng: '有 NG',
    },
  },
  tile: {
    label: '影像切片',
    description: '依列數與欄數產生矩形區域，可加重疊；只做幾何切片，不處理像素。',
    params: {
      rows: { label: '列數' },
      cols: { label: '欄數' },
      overlap: { label: '重疊量', help: '可用基礎切片比例或像素量。' },
      overlap_mode: { label: '重疊模式', options: { ratio: '比例', pixels: '像素' } },
      include_remainder: { label: '包含餘數' },
      width: { label: '寬度' },
      height: { label: '高度' },
    },
    ports: { image: '影像', regions: '區域', count: '數量' },
  },
  register_detect: {
    label: '註冊式檢測',
    description: '使用少量目標裁切圖尋找、計數或檢查零件有無，無需訓練。加入相似物的排除圖可減少誤判。',
    params: {
      registrations: { label: '註冊圖', help: '每張裁切圖包含一個目標並保留少許背景，建議少於十張。' },
      negatives: { label: '排除圖', help: '選填：不得計入的相似物裁切圖。' },
      roi: { label: '搜尋區域' },
      mode: { label: '模式', options: { detect: '檢測', count: '計數', presence: '有無' } },
      scales: { label: '搜尋尺寸', help: '以逗號分隔相對尺寸，例如 0.8,1.0,1.25。' },
      angle_range: { label: '角度範圍', help: '從零度向兩側搜尋，0 表示不旋轉。' },
      angle_step: { label: '角度間距', help: '相鄰搜尋角度的間距，0 表示不旋轉。' },
      min_similarity: { label: '最低相似度' },
      max_count: { label: '最多結果數' },
      nms_overlap: { label: '最大重疊比例' },
      min_size: { label: '最小邊長', help: '兩邊皆須達到此下限，0 表示不限。' },
      max_size: { label: '最大邊長', help: '任一邊皆不得超過此上限，0 表示不限。' },
      min_count: { label: '合格數量下限' },
      max_count_ok: { label: '合格數量上限' },
      expected: { label: '預期狀態', options: { present: '有', absent: '無' } },
      device: { label: '運算裝置', options: { auto: '自動', cpu: '處理器', cuda: '圖形處理器' } },
      backbone_path: { label: '特徵模型檔案', help: '內部測試用，留空使用已安裝的特徵模型。' },
    },
    ports: {
      image: '影像', roi: '搜尋區域', found: '已找到', not_found: '未找到', ok: '合格', ng: '不合格',
      matches: '比對結果', count: '數量', best_score: '最佳相似度', best_x: '最佳 X', best_y: '最佳 Y', present: '存在',
    },
  },
  coordinate: {
    "label": "自訂座標系",
    "description": "由原點與角度、兩點或有向直線定義原點及 X 軸；frame 輸出可接至真實世界座標工具。角度正值為畫面順時針。",
    "params": {
      "mode": {
        "label": "定義方式",
        "options": {
          "point_angle": "原點與角度",
          "two_points": "兩點",
          "line": "有向直線"
        }
      },
      "origin_x": {
        "label": "原點 X",
        "help": "未連接 point 埠時，與原點 Y 一起使用。"
      },
      "origin_y": {
        "label": "原點 Y"
      },
      "axis_angle": {
        "label": "X 軸角度",
        "help": "畫面順時針為正；未連接 angle 埠時使用。"
      }
    },
    "ports": {
      "point": "原點",
      "angle": "X 軸角度",
      "point2": "X 軸上的另一點",
      "line": "有向直線",
      "frame": "座標系",
      "origin_x": "原點 X",
      "origin_y": "原點 Y",
      "found": "已建立",
      "not_found": "未找到"
    }
  },
  angle: {
    label: "夾角",
    description: "兩條直線的夾角（度）。直線可為 {x1,y1,x2,y2} 或分別接八個數值。",
    params: {
      range: {
        label: "角度範圍",
        options: {
          "0_90": "0 ~ 90（不分方向）",
          signed: "-180 ~ 180（帶號）",
        },
      },
    },
    ports: {
      image: "影像",
      a: "直線 A",
      b: "直線 B",
      angle_deg: "夾角",
      angle_a: "A 角度",
      angle_b: "B 角度",
    },
  },
  frame_accumulate: {
    label: "多幀累積",
    description: "跨多次執行累積影像，輸出平均、最大或最小結果。",
    params: {
      mode: { label: "模式", options: { mean: "平均", max: "最大", min: "最小" } },
      count: { label: "張數" },
      emit: { label: "輸出", options: { ready: "滿張數才輸出", always: "每次都輸出" } },
      reset: { label: "重設" },
    },
    ports: { image: "影像", reset: "重設", frames: "已累積張數", ready: "已就緒", waiting: "等待中" },
  },
  previous_image: {
    label: "上一張影像",
    description: "從同一流程最近的執行影像快取讀取指定節點輸出。",
    params: { node: { label: "節點 ID" }, port: { label: "輸出埠" }, k: { label: "往前第幾次" } },
    ports: { image: "影像", found: "找到", not_found: "找不到" },
  },
  apply_mask: {
    label: "套用遮罩",
    description: "只保留遮罩為 255 的像素（其餘設為指定灰階）。",
    params: {
      side: { label: "填值位置", options: { outside: "遮罩外", inside: "遮罩內" } },
      fill_value: { label: "填值" },
      fill: {
        label: "遮罩外填值",
      },
    },
    ports: {
      image: "影像",
      mask: "遮罩",
    },
  },
  arithmetic: {
    label: "影像運算",
    description: "兩張影像相加／相減／差異／AND／OR，或單張的反相、亮度對比調整。",
    params: {
      op: {
        label: "運算",
        options: {
          absdiff: "絕對差 |A-B|",
          min: "最小值",
          max: "最大值",
          mean: "平均",
          weighted: "加權",
          invert: "反相 A",
        },
      },
      weight: { label: "A 權重" },
    },
    ports: {
      image: "影像",
    },
  },
  paste_back: {
    label: "貼回影像",
    description: "把處理後的小圖貼回大圖，超出邊界時自動裁切。",
    params: {
      x: { label: "X" },
      y: { label: "Y" },
      region: { label: "區域" },
      mode: { label: "模式", options: { replace: "取代", blend: "混合", masked: "遮罩貼回" } },
      alpha: { label: "Alpha" },
    },
    ports: { image: "底圖", patch: "小圖", region: "區域", mask: "遮罩" },
  },
  barcode: {
    label: "條碼 / QR",
    description: "解碼 QR code、Data Matrix、Aztec、PDF417 與一維條碼（EAN/UPC/Code 128/Code 39 等）。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      types: {
        label: "類型",
        options: {
          all: "全部碼制",
          "2d": "二維碼（QR、Data Matrix、Aztec、PDF417）",
          qr: "只 QR",
          "1d": "只一維條碼",
        },
      },
      expected: {
        label: "期望內容",
        help: "不為空時，內容需完全相同才走「符合」分支。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到／符合",
      not_found: "沒找到／不符",
      texts: "內容列表",
      count: "數量",
      first: "第一個內容",
      codes: "詳細",
    },
  },
  blob: {
    label: "Blob 分析",
    description: "連通區域／輪廓分析：面積、中心、外接矩形、圓形度；可依面積與圓形度篩選並排序。灰階輸入會自動二值化。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      threshold_method: {
        label: "門檻",
        options: {
          otsu: "Otsu 自動",
          fixed: "固定門檻",
          hysteresis: "雙門檻（高種子＋低成長）",
          soft: "軟門檻加權",
          none: "輸入已是遮罩（非 0 即前景）",
        },
      },
      threshold: {
        label: "門檻",
      },
      threshold_low: {
        label: "低門檻",
        help: "雙門檻會從高門檻種子往相連的低門檻像素成長。",
      },
      soft_width: {
        label: "軟門檻寬度",
        help: "門檻附近以 0～1 加權，面積可能是小數。",
      },
      polarity: {
        label: "前景",
        options: {
          bright: "亮物件",
          dark: "暗物件",
        },
      },
      min_area: {
        label: "最小面積",
      },
      max_area: {
        label: "最大面積",
        help: "0 表示不限。",
      },
      min_circularity: {
        label: "最小圓形度",
        help: "4πA/P²，正圓為 1。",
      },
      max_count: {
        label: "最多輸出",
      },
      sort_by: {
        label: "排序",
        options: {
          area: "面積（大→小）",
          x: "X（左→右）",
          y: "Y（上→下）",
          xy: "閱讀順序（先列後欄）",
          circularity: "圓形度（高→低）",
          perimeter: "周長（大到小）",
          width: "寬度（大到小）",
          height: "高度（大到小）",
        },
      },
      separate: {
        label: "分離黏連粒子",
        help: "距離轉換＋分水嶺把黏在一起的粒子切開再量測；種子視窗依「最小面積」推算的粒子半徑。",
        group: "進階",
      },
      fill_holes: {
        label: "填滿孔洞",
        group: "進階",
      },
      external_only: {
        label: "只取最外層輪廓",
        help: "關閉時面積會扣掉孔洞。",
        group: "進階",
      },
      min_count: {
        label: "合格最少數量",
        help: "找到的 blob 少於此值判 NG。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      blobs: "Blob 列表",
      count: "數量",
      largest_area: "最大面積",
      total_area: "總面積",
      contours: "輪廓",
      centers: "中心點",
      mask: "遮罩",
      first_cx: "第一個中心 X",
      first_cy: "第一個中心 Y",
    },
  },
  blob_label: {
    label: "標籤圖 Blob",
    description: "對單通道標籤圖逐類別做 blob 分析，輸出每個區塊的類別名稱、類別編號、面積、中心、外框、周長與最大內接矩形。可接 dl_segment 的 class_map；若接 ai_segment 的 mask，請用 255 當單一類別。",
    params: {
      roi: {
        label: "區域",
        help: "留空代表整張標籤圖。",
      },
      classes: {
        label: "類別表",
        help: "一行一個「編號:名稱」，例如 1:scratch。",
      },
      min_area: {
        label: "最小面積",
      },
      max_area: {
        label: "最大面積",
        help: "0 代表不限制。",
      },
      max_count: {
        label: "最多結果",
      },
      sort_by: {
        label: "排序",
        options: {
          area: "面積（大到小）",
          x: "X（左到右）",
          y: "Y（上到下）",
          xy: "閱讀順序（先列後欄）",
          circularity: "圓形度（高到低）",
          perimeter: "周長（大到小）",
          width: "寬度（大到小）",
          height: "高度（大到小）",
        },
      },
      ignore_label: {
        label: "忽略標籤",
        help: "通常 0 是背景。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多數量",
        help: "0 代表不限制。",
        group: "判定",
      },
    },
    ports: {
      labels: "標籤圖",
      roi: "區域（動態）",
      ok: "通過",
      ng: "失敗",
      blobs: "Blob 列表",
      counts: "各類數量",
      count: "總數",
      contours: "輪廓",
    },
  },
  blur: {
    label: "平滑 / 去雜訊",
    description: "高斯、中值、雙邊或均值濾波。",
    params: {
      method: {
        label: "方法",
        options: {
          gaussian: "高斯",
          median: "中值",
          bilateral: "雙邊（保邊）",
          box: "均值",
        },
      },
      ksize: {
        label: "核大小（奇數）",
      },
      sigma: {
        label: "Sigma（高斯／雙邊）",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
    },
  },
  bool_logic: {
    label: "布林組合",
    description: "把多個布林輸入以 AND / OR / NOT 組合，走 true / false 分支。",
    params: {
      mode: {
        label: "運算",
        options: {
          and: "AND（全部為真）",
          or: "OR（任一為真）",
        },
      },
    },
    ports: {
      values: "布林",
      result: "結果",
    },
  },
  calibration: {
    label: "像素校正",
    description: "把像素量測值換算成毫米：直接給每像素 mm，或用「已知距離」（像素數 ↔ 實際 mm）算比例。也可縮放點列表。",
    params: {
      mode: {
        label: "校正方式",
        options: {
          known_distance: "已知距離",
        },
      },
      pixel_size_mm: {
        label: "每像素 mm",
      },
      px_distance: {
        label: "像素距離",
      },
      real_mm: {
        label: "實際距離",
      },
      power: {
        label: "次方",
        help: "面積量測請選 k²。",
        options: {
          "1": "長度（×k）",
          "2": "面積（×k²）",
        },
      },
    },
    ports: {
      value: "像素值",
      points: "點列表",
      mm: "毫米",
      scale: "比例",
      points_mm: "點列表（mm）",
    },
  },
  caliper: {
    label: "卡尺",
    description: "在矩形區域內沿長邊投影灰階剖面，找一對邊緣並量測寬度（像素）。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      roi: {
        label: "區域",
        help: "沿長邊方向掃描，短邊方向取平均以抗雜訊。",
      },
      polarity: {
        label: "邊緣極性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
      },
      max_results: {
        label: "最多結果",
        help: "回傳排序後前 N 個邊緣對候選；單一寬度與邊緣座標仍取第一筆。",
      },
      sort_by: {
        label: "排序依據",
        help: "分數＝對比加權，扣掉位置誤差與寬度誤差的加權罰分。",
        options: { score: "分數", position: "位置", contrast: "對比" },
      },
      edge_pair: {
        label: "取邊緣對",
        options: {
          first_last: "第一個與最後一個",
          widest: "最寬的一對",
          narrowest: "最窄的一對（相鄰）",
          strongest: "最強的兩個",
        },
      },
      pair_polarity: {
        label: "邊緣對極性",
        help: "限制成對邊緣的極性順序：量亮條／暗條的寬度時不會配到旁邊的雜訊邊緣。",
        options: {
          any: "不限",
          bright: "亮條（暗→亮、亮→暗）",
          dark: "暗條（亮→暗、暗→亮）",
        },
      },
      expected_width: {
        label: "期望寬度",
        help: "大於 0 時改挑「寬度最接近此值」的邊緣對（優先於取邊緣對模式）。",
      },
      expected_position: {
        label: "期望位置",
        help: "沿掃描方向的期望候選中心（px）；0 表示不使用位置項。",
      },
      position_weight: {
        label: "位置權重",
        help: "每偏離期望位置 1 px 扣多少分。",
      },
      contrast_weight: {
        label: "對比權重",
        help: "每 1 灰階/px 邊緣對比加多少分；所有權重為 0 時分數退回對比。",
      },
      width_weight: {
        label: "寬度權重",
        help: "每偏離期望寬度 1 px 扣多少分。",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
    },
    ports: { width_world: "寬度（物理量）", edge1_x_world: "邊緣 1 X（世界）", edge1_y_world: "邊緣 1 Y（世界）", edge2_x_world: "邊緣 2 X（世界）", edge2_y_world: "邊緣 2 Y（世界）", unit: "單位",
      image: "影像",
      roi: "區域（動態）",
      width: "寬",
      edge1_x: "邊緣1 X",
      edge1_y: "邊緣1 Y",
      edge2_x: "邊緣2 X",
      edge2_y: "邊緣2 Y",
      edges: "邊緣候選",
      profile: "剖面",
    },
  },
  peak_search: {
    label: "峰值搜尋",
    description: "沿矩形區域長邊取灰階剖面，找亮峰、暗峰或兩者的中心位置。",
    params: {
      roi: { label: "區域", help: "沿長邊方向掃描，短邊方向取平均以抗雜訊。" },
      polarity: { label: "峰值極性", options: { bright: "亮峰", dark: "暗峰", both: "兩者" } },
      min_prominence: { label: "最小突出量" },
      min_distance: { label: "最小距離" },
      smoothing: { label: "剖面平滑", group: "進階" },
      max_results: { label: "最多結果" },
      sort_by: { label: "排序依據", options: { position: "位置", prominence: "突出量", value: "灰階值" } },
    },
    ports: {
      image: "影像", roi: "區域（動態）", found: "找到", not_found: "未找到",
      peaks: "峰值清單", count: "數量", first_x: "第一峰 X", first_y: "第一峰 Y",
      first_position: "第一峰位置", profile: "灰階剖面",
    },
  },
  chamfer_angle: {
    label: "倒角",
    description: "在旋轉矩形區域內以卡尺找輪廓邊緣點，RANSAC 擬合第一條直線後排除其內點再擬合第二條；輸出兩線夾角與倒角段長度。",
    params: {
      roi: {
        label: "區域",
        help: "長邊沿著輪廓走向、要同時包住主邊與倒角段；卡尺沿短邊掃描。",
      },
      polarity: {
        label: "邊緣極性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
      },
      num_calipers: {
        label: "卡尺數",
      },
      direction: {
        label: "取哪個邊緣",
        options: {
          first: "第一個",
          last: "最後一個",
          strongest: "最強",
        },
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "進階",
      },
      min_points: {
        label: "第二段最少點數",
        group: "進階",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      angle_deg: "夾角",
      length: "倒角長度",
      line1: "主邊",
      line2: "倒角邊",
      ix: "交點 X",
      iy: "交點 Y",
      points: "邊緣點",
    },
  },
  gdt_measure: {
    label: "形位公差",
    description: "照圖面語言量幾何公差（ISO 1101）：直線度與平面度是包住所有點的最窄平行帶，真圓度是兩個同心圓之間最窄的環，平行度、垂直度與傾斜度是特徵相對基準的偏差帶。回報偏差、是否在公差內，以及背後的方法與極值點。",
    params: {
      mode: { label: "公差項目", options: { straightness: "直線度（點集）", flatness: "平面度（點集，2D 投影）", roundness: "真圓度（點集）", parallelism: "平行度（a 對基準 b）", perpendicularity: "垂直度（a 對基準 b）", angularity: "傾斜度（a 對基準 b 成參考角）" } },
      tolerance: { label: "公差帶", help: "偏差必須落在的帶寬（像素；有比例時為毫米）。" },
      unit: { label: "單位", options: { px: "像素", mm: "毫米（比例來自標定工具）" } },
      mm_per_px: { label: "每像素 mm", help: "留 0 並接入標定工具的比例輸入。" },
      reference_angle: { label: "參考角", help: "特徵 a 應與基準 b 成的角度（正值＝畫面順時針）。" },
    },
    ports: { points: "點", a: "特徵 a", b: "基準 b", scale: "比例（每像素 mm）", image: "影像（顯示用）", pass: "合格", fail: "不合格", deviation: "偏差", in_spec: "在公差內", unit: "單位", tolerance: "公差" },
  },
  photometric_stereo: {
    label: "光度立體",
    description: "把同一件在三或四個方向打光各拍的一張合成表面形狀：浮凸與刻印字、凹坑、凸點與拋光面刮痕在曲率圖上一目了然，即使任何單張都看不出來。反射率輸出是去掉打光後的材質。",
    params: {
      light_azimuth: { label: "光源方位角", help: "每盞燈一個角度（度），繞畫面一圈（0＝自右、90＝自下，順時針）。四燈各隔 90° 是常見燈架。" },
      light_elevation: { label: "光源仰角", help: "燈離表面的仰角；所有燈相同。" },
      output: { label: "影像輸出", options: { curvature: "曲率（有號形狀圖：凸亮凹暗）", curvature_abs: "形狀強度（無號曲率，供二值化）", normal_x: "法向 X（左右斜度）", normal_y: "法向 Y（上下斜度）", albedo: "反射率（去掉打光）", all: "全部（影像＝曲率）" } },
      normalize: { label: "正規化為 8 位元", help: "關閉時保留 float32 圖（曲率與法向帶正負號）。" },
      drop_darkest: { label: "每像素丟掉最暗的燈", help: "四燈時每個像素用較亮的三張求解，深槽裡的陰影不會把法向拉歪。", group: "進階" },
    },
    ports: { image: "光 1", image_1: "光 2", image_2: "光 3", image_3: "光 4", curvature: "曲率", curvature_abs: "形狀強度", albedo: "反射率", normal_x: "法向 X", normal_y: "法向 Y", lights: "使用的燈數" },
  },
  barcode_grade: {
    label: "條碼品質分級",
    description: "像驗證器一樣替二維或一維條碼評級：Data Matrix 與 QR 走 ISO/IEC 15415、線性碼走 ISO/IEC 15416、金屬直接打標走 AIM DPM。每個分項（對比、調變、固定圖形損傷、軸向與格點不均勻、未用錯誤更正、缺陷、可解碼度）各自給分，總評 A 到 F，並判定是否達到最低等級。以 8 位元灰階當反射率，數值對得上驗證器的量級但不是認證。",
    params: {
      roi: { label: "區域", help: "符號與它的靜區；留空則整張影像。" },
      standard: { label: "標準", help: "線性碼一律以 15416 分級；DPM 以格對比與格調變取代 15415 的對比與調變。", options: { iso15415: "ISO/IEC 15415（2D：Data Matrix、QR）", iso15416: "ISO/IEC 15416（1D：EAN、UPC、Code 128、Code 39）", aim_dpm: "AIM DPM（ISO/IEC TR 29158，金屬直接打標）" } },
      symbology: { label: "碼制", options: { auto: "不限", datamatrix: "Data Matrix", qr: "QR Code", ean_upc: "EAN / UPC", code128: "Code 128", code39: "Code 39" } },
      aperture: { label: "孔徑", help: "合成孔徑直徑；0＝模組大小的 80%（DPM 為 50%）。" },
      min_grade: { label: "最低等級", help: "總評要達到此等級或更好才合格。", options: { A: "A（4.0）", B: "B（3.0）", C: "C（2.0）", D: "D（1.0）", F: "F（0.0）" } },
      dpm_filter: { label: "DPM 前置濾波", help: "AIM DPM 允許量測前先做影像處理。", options: { none: "無", median: "中值 3×3" }, group: "進階" },
    },
    ports: { image: "影像", roi: "區域（動態）", pass: "合格", fail: "不合格", grade: "等級", grade_value: "等級分數", params: "分項", text: "內容", symbology: "碼制", decoded: "已解碼" },
  },
  variable_get: {
    label: "讀取變數",
    description: "讀出流程或站台變數：料號、計數、上一件的量測值。尚未儲存時用預設值。",
    params: {
      name: { label: "變數", help: "英數字與底線。" },
      scope: { label: "範圍", help: "只限這條流程，或整站所有流程共用。", options: { flow: "這條流程", station: "整個站台" } },
      default: { label: "預設值", help: "尚未儲存前使用。數字仍是數字；true 與 false 是布林。" },
    },
    ports: { value: "值", number: "數值", text: "文字", found: "已設定" },
  },
  variable_set: {
    label: "儲存變數",
    description: "把值存進流程或站台變數：累計數量、記住最大值、把料號傳給下一條流程。試執行只寫在覆蓋層，不動真正的計數。",
    params: {
      name: { label: "變數" },
      scope: { label: "範圍", options: { flow: "這條流程", station: "整個站台" } },
      mode: { label: "方式", options: { set: "儲存這個值", add: "加上去（計數、總和）", max: "保留最大", min: "保留最小" } },
    },
    ports: { value: "值", previous: "先前的值" },
  },
  switch: {
    label: "多路分支",
    description: "一個值一條路：一個料號、一個配方碼、一個等級各走各的。案例一行一個，這一步就長出對應數量的輸出；都不符的走預設分支。",
    params: {
      cases: { label: "案例", help: "一行一個，由上往下比，第一個相符的勝出。比對選數字時，一行可以是單一數值（12）或範圍（10-20）。每一行都會多一個輸出埠，另外還有預設分支。" },
      match: {
        label: "比對",
        options: {
          exact: "值剛好是這個",
          contains: "值包含這個",
          prefix: "值開頭是這個",
          regex: "樣式（規則運算式）",
          number: "數字或範圍（10-20）",
        },
      },
      case_sensitive: { label: "區分大小寫" },
    },
    ports: { value: "值", default: "都不符", index: "第幾個案例", matched: "有相符", },
  },
  string_match: {
    label: "文字比對",
    description: "拿一段文字跟清單比對：這個條碼是不是我們的、日期碼在不在允許清單裡、讀到的內容有沒有包含料號。走相符／不相符分支，並回報是哪一筆。",
    params: {
      list: { label: "允許的值", help: "一行一個。比對選樣式時，每一行都是一個規則運算式。" },
      match: {
        label: "比對",
        options: { exact: "文字剛好是這個", contains: "文字包含這個", prefix: "文字開頭是這個", regex: "樣式（規則運算式）" },
      },
      case_sensitive: { label: "區分大小寫" },
      invert: { label: "相符時反而算失敗", help: "用在「這些字不准出現」的清單。" },
    },
    ports: { text: "文字", found: "相符", not_found: "不相符", index: "第幾筆", matched: "相符的那一筆" },
  },
  parse_message: {
    label: "拆解訊息",
    description: "把一段文字拆成具名值：條碼內容 LOT12345|2026-09-08|A7、文字辨識讀到的一行，或上位機隨觸發送來的訊息。每個欄位都會變成具名輸出，後面的步驟可以拿去判斷、比對或回送。",
    params: {
      mode: { label: "排列方式", options: { delimiter: "以字元分隔", regex: "以樣式（規則運算式）", fixed: "固定位元組位置" } },
      separator: { label: "分隔字元", help: "一個或多個字元。定位字元請輸入 \\t。" },
      pattern: { label: "樣式", help: "例如 LOT(?P<lot>\\d+)\\s+(?P<qty>\\d+)。具名群組會填進同名欄位，否則依序填。" },
      fields: {
        label: "欄位",
        help: "一行一個欄位，依序對應。只寫名稱就取下一段文字；加冒號指定型別（name:int、name:float、name:bool、name:hex）。要跳著取就寫位置，從 0 起算（name:int:3）。固定位元組位置改寫位元組範圍（name:int:0-1）；設備的位元組順序相反時再加順序（name:float:2-5:DCBA）。設備送 1234 代表 12.34 就加 *0.01。",
      },
      publish: { label: "併入回覆", help: "每個欄位也成為具名輸出，HTTP 與 TCP 的回覆就會帶上。" },
      prefix: { label: "名稱前綴", help: "加在每個欄位名稱前面，用來區分兩段訊息。" },
      on_missing: { label: "欄位取不到值時", options: { pass: "留空並繼續", fail: "讓步驟失敗" } },
    },
    ports: { text: "文字", matched: "相符", not_matched: "未相符", fields: "欄位", count: "取到幾個", first: "第一個欄位" },
  },
  format_text: {
    label: "格式化回覆",
    description: "用樣板組一行純文字給讀不懂 JSON 的設備：{名字} 依序取具名輸出、觸發引數（lot、sn）、本節點輸入 a～d，另有 {run_id} 與 {station}；支援 {width:.2f} 這類格式。設備端用 TCP 的 fmt= 或 HTTP 的 format 取這一行。",
    params: {
      template: { label: "樣板", help: "例如 OK;{diameter:.2f};{lot}。\\n 與 \\t 會轉成真正的控制字元。" },
      name: { label: "輸出名稱", help: "回覆以此名稱帶這一行；TCP 指令的 fmt 或 HTTP 的 format 指定它。" },
      ending: { label: "行尾", options: { none: "無", lf: "換行（\\n）", crlf: "回車換行（\\r\\n）", cr: "回車（\\r）" } },
      missing: { label: "名字沒有值時", options: { blank: "留空", keep: "保留名字原樣", fail: "讓步驟失敗" } },
    },
    ports: { a: "a", b: "b", c: "c", d: "d", text: "文字" },
  },
  circular_caliper: {
    label: "圓形卡尺",
    description: "沿圓形邊緣放一圈徑向卡尺，量出每個角度的半徑。半徑序列一眼看出崩邊、缺口、毛刺與不圓；跳動量（最大減最小）就是徑向偏差。把數值接進序列缺陷就能數出缺陷。",
    params: {
      roi: { label: "搜尋環", help: "環要蓋住邊緣；帶起迄角時只量該扇形。" },
      caliper_count: { label: "卡尺數" },
      caliper_width: { label: "卡尺寬度", help: "每把卡尺切向平均的寬度，用來降噪。" },
      edge_threshold: { label: "邊緣門檻" },
      polarity: { label: "極性", help: "由內往外的灰階變化。", options: { any: "不限", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      edge_select: { label: "選邊", options: { first: "第一個（最內）", last: "最後一個（最外）", strongest: "最強" } },
      outlier_sigma: { label: "離群 σ", help: "與中位數差超過幾倍穩健 σ 的半徑不進統計（仍保留在序列裡）。0 = 全部採計。" },
      smoothing: { label: "剖面平滑", group: "進階" },
    },
    ports: { image: "影像", roi: "搜尋環（動態）", found: "找到", not_found: "未找到", radii: "半徑列表", angles: "角度列表", points: "邊緣點", all_points: "每把卡尺的點", mean_r: "平均半徑", min_r: "最小半徑", max_r: "最大半徑", runout: "跳動量", missing_count: "未找到數", outlier_count: "離群數", cx: "中心 X", cy: "中心 Y" },
  },
  color_check: {
    label: "顏色檢查",
    description: "區域內平均顏色與目標色的距離（RGB 或 HSV 空間）是否在容差內。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      color: {
        label: "目標色",
      },
      space: {
        label: "比較空間",
        options: {
          rgb: "RGB 歐氏距離（0~441）",
          hsv: "HSV（色相為主）",
        },
      },
      tolerance: {
        label: "容差",
        help: "RGB：歐氏距離；HSV：色相差（0~180，依飽和度加權）＋飽和度／明度差÷4 的距離。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      match: "符合",
      mismatch: "不符",
      distance: "距離",
      is_match: "符合",
      mean_hex: "平均色",
      mean_bgr: "平均 BGR",
      mean_hsv: "平均 HSV",
    },
  },
  color_segment: {
    label: "多色分割",
    description: "一次依多個 HSV 或 Lab 色域切成整數標籤圖，並輸出各色面積與類別名稱。",
    params: {
      segments: { label: "分割段", help: "一行一段：名稱:H下,H上,S下,S上,V下,V上。HSV 的 H 下界大於上界時會跨過 0/180，常用於紅色。" },
      space: { label: "色彩空間", options: { hsv: "HSV", lab: "Lab" } },
      min_area: { label: "最小面積" },
      smooth: { label: "平滑" },
      roi: { label: "區域", help: "留空代表整張影像。" },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      labels: "標籤圖",
      areas: "面積",
      classes: "類別",
    },
  },
  color_classify: {
    label: "樣本顏色分類",
    description: "把區域內顏色直方圖與固定影像樣本比對，回傳最接近的樣本名稱與相似度。",
    params: {
      samples: { label: "樣本" },
      space: { label: "色彩空間", options: { hsv: "HSV", lab: "Lab" } },
      bins: { label: "分箱數" },
      metric: { label: "比對方式", options: { histogram_intersection: "直方圖交集", earth_mover: "搬移距離" } },
      min_similarity: { label: "最低相似度" },
      roi: { label: "區域", help: "留空代表整張影像。" },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      ok: "通過",
      ng: "低於相似度",
      label: "標籤",
      similarity: "相似度",
      ranking: "排名",
    },
  },
  color_convert: {
    label: "色彩空間 / 通道",
    description: "轉 HSV/Lab 或抽出單一通道，作為色彩檢測的前處理。",
    params: {
      mode: {
        label: "輸出",
        options: {
          bgr_b: "B 通道",
          bgr_g: "G 通道",
          bgr_r: "R 通道",
          hsv: "整張 HSV（3 通道）",
          merge_rgb: "合成 R/G/B 灰階",
          yuv_y: "YUV Y 通道",
          yuv_u: "YUV U 通道",
          yuv_v: "YUV V 通道",
          hsi_h: "HSI H 通道",
          hsi_s: "HSI S 通道",
          hsi_i: "HSI I 通道",
          gray_weighted: "加權灰階",
        },
      },
      weight_r: { label: "R 權重" },
      weight_g: { label: "G 權重" },
      weight_b: { label: "B 權重" },
    },
    ports: {
      image: "影像",
      r: "R 灰階",
      g: "G 灰階",
      b: "B 灰階",
    },
  },
  color_range: {
    label: "色彩範圍遮罩",
    description: "HSV 範圍內的像素為 255（支援 H 跨 0 的紅色）。",
    params: {
      h_low: {
        label: "H 下限",
      },
      h_high: {
        label: "H 上限",
      },
      s_low: {
        label: "S 下限",
      },
      s_high: {
        label: "S 上限",
      },
      v_low: {
        label: "V 下限",
      },
      v_high: {
        label: "V 上限",
      },
    },
    ports: {
      image: "遮罩",
      ratio: "覆蓋比例",
    },
  },
  color_stats: {
    label: "色彩統計",
    description: "區域內 RGB 與 HSV 的平均／標準差、主色相與平均色；供顏色驗證與上下游邏輯判斷。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      mean_r: "R 平均",
      mean_g: "G 平均",
      mean_b: "B 平均",
      mean_h: "色相平均",
      mean_s: "飽和度平均",
      mean_v: "明度平均",
      std_v: "明度標準差",
      hex: "平均色",
    },
  },
  concentricity: {
    label: "同心度",
    description: "兩個圓（例如外徑與內徑）圓心的偏移量；GD&T 同心度 = 2×偏移。接 find_circle 的 cx/cy/r 或 {cx,cy,r}。",
    params: {
      max_deviation: {
        label: "最大偏移",
        help: "圓心距離超過此值走 ng 分支。",
      },
    },
    ports: {
      image: "影像",
      a: "圓 A",
      b: "圓 B",
      ax: "A 圓心 X",
      ay: "A 圓心 Y",
      ar: "A 半徑",
      bx: "B 圓心 X",
      by: "B 圓心 Y",
      br: "B 半徑",
      ok: "合格",
      ng: "超差",
      deviation: "偏移量",
      concentricity: "同心度（2×偏移）",
      verdict: "判定",
      in_spec: "合格",
    },
  },
  contour_filter: {
    label: "輪廓篩選",
    description: "依面積、周長、凸度、長寬比與位置留下合格的輪廓並排序。放在輪廓萃取與幾何／比對工具之間，先去掉雜訊、孔洞與不量的部位。",
    params: {
      min_area: { label: "最小面積" },
      max_area: { label: "最大面積", help: "0 = 不限。" },
      min_perimeter: { label: "最小周長", group: "更多限制" },
      max_perimeter: { label: "最大周長", help: "0 = 不限。", group: "更多限制" },
      min_convexity: { label: "最小凸度", help: "面積除以凸包面積；凸形為 1。", group: "更多限制" },
      max_convexity: { label: "最大凸度", group: "更多限制" },
      min_aspect: { label: "最小長寬比", help: "最小外接矩形的長邊除以短邊。", group: "更多限制" },
      max_aspect: { label: "最大長寬比", help: "0 = 不限。", group: "更多限制" },
      roi: { label: "只留區域內", help: "只留下重心落在此區域內的輪廓。", group: "更多限制" },
      sort_by: {
        label: "排序",
        options: { area: "面積（大到小）", perimeter: "周長（長到短）", x: "X（左到右）", y: "Y（上到下）", none: "維持輸入順序" },
      },
      max_count: { label: "最多輸出", help: "排序後最多留這麼多條。" },
      min_count: { label: "最少通過數", help: "少於此數視為 NG。", group: "判定" },
    },
    ports: {
      contours: "輪廓", roi: "只留區域內（動態）", found: "找到", not_found: "未找到", count: "數量", rejected: "剔除數",
      areas: "面積列表", first_area: "第一條面積", centers: "重心", first_cx: "第一條重心 X", first_cy: "第一條重心 Y",
    },
  },
  contour_find: {
    label: "輪廓萃取",
    description: "從二值影像描出外形（灰階輸入先二值化）：只取外輪廓，或連孔洞一起。輪廓接輪廓篩選、輪廓幾何、輪廓比對與公差工具；座標是輸入影像的座標。",
    params: {
      roi: { label: "區域", help: "留空則整張影像。" },
      threshold_method: {
        label: "二值化",
        options: { otsu: "Otsu（自動）", fixed: "固定", none: "輸入已是遮罩（非零即前景）" },
      },
      threshold: { label: "門檻" },
      polarity: { label: "前景", options: { bright: "亮物件", dark: "暗物件" } },
      mode: {
        label: "擷取方式",
        options: { external: "只取外輪廓", list: "全部輪廓（含孔洞，不分層）", ccomp: "外輪廓與其孔洞", tree: "完整階層" },
      },
      approx: { label: "簡化", help: "開：直線段只留端點。關：每個邊界像素都留。" },
      min_points: { label: "最少點數", help: "點數少於此值的輪廓丟棄。" },
      min_area: { label: "最小面積", help: "0 = 全部保留。" },
      max_count: { label: "最多輸出" },
    },
    ports: {
      image: "影像", roi: "區域（動態）", found: "找到", not_found: "未找到", contours: "輪廓", count: "數量",
      areas: "面積列表", first_area: "第一條面積", centers: "重心", first_cx: "第一條重心 X", first_cy: "第一條重心 Y", mask: "遮罩",
    },
  },
  contour_geometry: {
    label: "輪廓幾何",
    description: "量每一條輪廓：面積、周長、重心、最小外接矩形（含角度）、最小外接圓、凸包面積與凸度、凸缺陷（缺角、邊緣被咬掉一塊、異物咬入外形——計數並回報最深的一個）、圓形度與 Hu 矩。列表每條一項；first_ 埠是第一條。",
    params: {
      defect_depth: { label: "缺陷深度", help: "外形相對凸包凹陷超過此深度就算一個凸缺陷。" },
      max_contours: { label: "最多輪廓數", help: "只量前 N 條。" },
    },
    ports: {
      contours: "輪廓", image: "影像（顯示用）", geometry: "幾何", count: "數量", areas: "面積列表", perimeters: "周長列表", centers: "重心",
      rects: "最小外接矩形", circles: "外接圓", convexities: "凸度列表", defect_counts: "缺陷數列表", defect_points: "缺陷點",
      first_area: "第一條面積", first_perimeter: "第一條周長", first_cx: "第一條重心 X", first_cy: "第一條重心 Y",
      first_w: "第一條長", first_h: "第一條寬", first_angle: "第一條角度", first_r: "第一條外接圓半徑", first_convexity: "第一條凸度",
      first_circularity: "第一條圓形度", first_defects: "第一條缺陷數", first_max_defect_depth: "第一條最深缺陷",
      total_defects: "缺陷總數", max_defect_depth: "最深缺陷",
    },
  },
  contour_match: {
    label: "輪廓比對",
    description: "以 Hu 矩距離把每條輪廓與參考外形比對，不受位置、縮放與旋轉影響。參考來自另一個輪廓萃取（參考埠）或範本影像中最大的形狀。距離低於上限即為相符——用來依外形分料，或抓錯料與變形件。",
    params: {
      template: { label: "範本影像", help: "參考埠沒接時使用；二值化後最大的亮形狀就是參考。" },
      template_threshold: {
        label: "範本二值化",
        options: { otsu: "Otsu（自動）", fixed: "固定", none: "範本已是遮罩" },
        group: "範本",
      },
      threshold: { label: "門檻", group: "範本" },
      polarity: { label: "範本前景", options: { bright: "亮形狀", dark: "暗形狀" }, group: "範本" },
      method: {
        label: "方法",
        options: { i1: "I1（|1/mA − 1/mB| 總和）", i2: "I2（|mA − mB| 總和）", i3: "I3（最大相對差）" },
      },
      max_distance: { label: "最大距離", help: "距離不超過此值即相符。相同形狀接近 0；可試 0.05～0.3。" },
      min_matches: { label: "最少相符數", help: "相符的輪廓少於此數視為 NG。", group: "判定" },
    },
    ports: {
      template_image: "範本圖",
      contours: "輪廓", reference: "參考輪廓", image: "影像（顯示用）", match: "相符", no_match: "不符",
      distances: "距離列表", distance: "最佳距離", best_index: "最佳索引", match_flag: "相符", match_count: "相符數",
      matched: "相符的輪廓", best: "最佳輪廓", first_distance: "第一條距離",
    },
  },
  convert_depth: {
    label: "位深轉換",
    description: "8 位元／16 位元／浮點影像互轉。轉 8 位元可選右移（線性、可預期）或 min-max 拉伸（吃滿動態範圍）。",
    params: {
      to: {
        label: "目標位深",
        options: {
          u8: "8 位元（U8）",
          u16: "16 位元（U16）",
          f32: "浮點（SGL）",
        },
      },
      scale: {
        label: "轉 8 位元方式",
        options: {
          shift: "等比例（16-bit 右移 8）",
          minmax: "min-max 拉伸",
          clip: "直接裁切",
        },
      },
    },
    ports: {
      image: "影像",
      depth: "位深",
    },
  },
  count_list: {
    label: "數量",
    description: "輸出 list／points／matches 的元素數量。",
    ports: {
      items: "清單",
      count: "數量",
    },
  },
  boxes_merge: {
    label: "合併框",
    description: "依重疊比例或中心距離合併重複的框，可限定同標籤才合併。",
    params: {
      mode: { label: "模式", options: { iou: "重疊比例", centre_distance: "中心距離" } },
      threshold: { label: "門檻" },
      same_label_only: { label: "只合併同標籤" },
      keep: { label: "保留資料來源", options: { highest_score: "最高分", largest: "最大框", first: "第一個" } },
    },
    ports: { matches: "框清單", values: "值清單", image: "影像（顯示用）", count: "數量" },
  },
  boxes_overlap: {
    label: "框重疊",
    description: "比較兩組框，回傳每個 A 框與 B 框的最大重疊率與對應索引。",
    params: {
      metric: { label: "重疊算法", options: { iou: "交併比", overlap_a: "重疊面積 / A 面積" } },
      min_overlap: { label: "最小重疊率" },
      mode: { label: "OK 條件", options: { any: "有重疊", none: "無重疊" } },
    },
    ports: { matches: "框清單", matches_b: "B 框清單", image: "影像（顯示用）", ok: "OK", ng: "NG", count: "數量", pairs: "重疊配對" },
  },
  list_filter: {
    label: "清單篩選",
    description: "依數值、文字或欄位條件篩選值清單或框清單。",
    params: {
      field: { label: "欄位" },
      op: {
        label: "條件",
        options: { gt: "大於", ge: "大於等於", lt: "小於", le: "小於等於", eq: "等於", ne: "不等於", between: "介於", in: "在清單內", regex: "符合文字規則", nonempty: "非空" },
      },
      value: { label: "值" },
      value2: { label: "第二值" },
    },
    ports: { values: "值清單", matches: "框清單", count: "數量", removed: "移除數", indices: "原始索引" },
  },
  list_classify: {
    label: "清單分類",
    description: "依每行分類範圍替值清單或框清單加上類別。",
    params: {
      field: { label: "欄位" },
      classes: { label: "分類規則", help: "一行一類：名稱:下限,上限；下限包含、上限不包含，空白代表無界。" },
    },
    ports: { values: "值清單", matches: "框清單", labels: "類別清單", counts: "類別數量", dominant: "最多類別" },
  },
  list_pick: {
    label: "清單取值",
    description: "從值清單、框清單或點清單取出第一筆、最後一筆、指定索引或最接近座標的一筆。",
    params: {
      by: { label: "取法", options: { index: "指定索引", first: "第一筆", last: "最後一筆", min: "最小值", max: "最大值", nearest: "最近座標" } },
      index: { label: "索引" },
      field: { label: "欄位" },
      x: { label: "目標 X" },
      y: { label: "目標 Y" },
    },
    ports: { values: "值清單", matches: "框清單", points: "點清單", image: "影像（顯示用）", found: "找到", not_found: "未找到", value: "值", index: "索引" },
  },
  boxes_filter: {
    label: "篩選框",
    description: "依尺寸、面積、長寬比、分數、標籤與位置區域留下合格的框。",
    params: {
      min_width: { label: "最小寬度", group: "尺寸" },
      max_width: { label: "最大寬度", group: "尺寸" },
      min_height: { label: "最小高度", group: "尺寸" },
      max_height: { label: "最大高度", group: "尺寸" },
      min_area: { label: "最小面積", group: "尺寸" },
      max_area: { label: "最大面積", group: "尺寸" },
      min_aspect: { label: "最小長寬比", group: "形狀" },
      max_aspect: { label: "最大長寬比", group: "形狀" },
      min_score: { label: "最低分數" },
      max_score: { label: "最高分數" },
      labels: { label: "標籤", help: "逗號分隔或一行一個；留空全部保留。" },
      roi: { label: "位置區域" },
      roi_mode: { label: "區域模式", options: { inside: "區域內", outside: "區域外" } },
    },
    ports: { matches: "框清單", values: "值清單", roi: "位置區域（動態）", image: "影像（顯示用）", count: "數量", removed: "移除數" },
  },
  array_correct: {
    label: "陣列補齊",
    description: "由已找到的框推回 rows × cols 網格，回報缺格並補上推估框。",
    params: {
      rows: { label: "列數" },
      cols: { label: "欄數" },
      tolerance: { label: "容許距離", help: "小於 1 表示 pitch 比例；大於等於 1 表示像素。" },
    },
    ports: { matches: "框清單", values: "值清單", image: "影像（顯示用）", ok: "完整", ng: "缺件", missing: "缺格", count: "數量" },
  },
  list_sort: {
    label: "清單排序",
    description: "排序值清單或框清單，可依座標閱讀順序、分數或標籤排列。",
    params: {
      by: { label: "排序依據", options: { value: "值", x: "X", y: "Y", xy: "閱讀順序", score: "分數", label: "標籤" } },
      descending: { label: "遞減" },
    },
    ports: { matches: "框清單", values: "值清單", count: "數量", first: "第一筆" },
  },
  crop: {
    label: "裁切 ROI",
    description: "裁出區域成為新影像（旋轉矩形會擺正）。下游工具在小圖上跑會快很多。",
    params: {
      roi: {
        label: "區域",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      offset_x: "偏移 X",
      offset_y: "偏移 Y",
    },
  },
  dark_ratio: {
    label: "暗區比例（範例外掛）",
    description: "ROI 內灰階低於門檻的像素比例，超過允許比例走「不良」分支。",
    params: {
      roi: {
        label: "區域",
      },
      threshold: {
        label: "門檻",
      },
      max_ratio: {
        label: "允許比例",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      ratio: "比例",
      pass: "合格",
      fail: "不良",
    },
  },
  edge_defect: {
    label: "邊緣缺陷",
    description: "整條邊一次檢查完，不是只量一個地方：沿著邊（直的或圓的）佈一排卡尺，凡是偏離理想邊的那幾段都會被指出來，並說明是哪一種不良。缺口與毛刺是「一整段偏進去或偏出來」，崩掉是「這一段根本找不到邊」，錯位是「相鄰兩處忽然接不上」；成對模式還會直接檢查寬度。每個缺陷都帶外框、沿邊長度與面積，所以要判最嚴重的還是判數量都可以。",
    params: {
      roi: { label: "區域", help: "直邊畫矩形（長邊沿著邊），圓邊畫圓或圓環。上游接進來的線或圓優先於這裡。" },
      mode: { label: "每把卡尺找什麼", options: { single: "一條邊", pair: "一對邊（肋、溝、縫）" } },
      polarity: { label: "邊緣極性", options: { any: "不限", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      pair_polarity: { label: "兩邊之間", options: { any: "都可以", bright: "比較亮", dark: "比較暗" } },
      calipers: { label: "卡尺數", help: "沿邊檢查幾個地方。愈多找得到愈小的缺陷，也愈慢。" },
      search: { label: "搜尋範圍", help: "每把卡尺在理想邊的兩側各找多遠。" },
      caliper_width: { label: "卡尺寬度", help: "沿著邊平均，用來降噪。" },
      edge_threshold: { label: "邊緣門檻" },
      baseline: {
        label: "理想邊是",
        help: "擬合適合會移動的工件；「就是區域本身」適合治具上邊必須在固定位置的場合。",
        options: { fit: "由找到的邊擬合（直線或圓）", median: "滑動中位數（跟著緩彎走）", reference: "就是區域或接進來的形狀" },
      },
      window: { label: "中位數視窗" },
      threshold: { label: "偏離超過", help: "離理想邊超過這麼多就算缺陷。" },
      min_width: { label: "至少連續幾把卡尺", help: "擋掉單把卡尺的雜訊。" },
      direction: { label: "哪一側算", options: { both: "兩側都算", inward: "只算少料", outward: "只算多料" } },
      fracture_run: { label: "連續幾把找不到邊算斷裂", help: "卡尺完全找不到邊，通常表示那一段的邊不見了。0＝不判斷裂。" },
      step_threshold: { label: "相鄰兩處落差超過", help: "從這一把到下一把忽然跳了：錯位或崩角。0＝不判階差。" },
      width_min: { label: "寬度不得小於", help: "0＝不檢查。" },
      width_max: { label: "寬度不得大於", help: "0＝不檢查。" },
      max_defects: { label: "超過幾個才算不良", help: "0＝有缺陷就不良。" },
      smoothing: { label: "剖面平滑" },
      edge_select: { label: "選邊", options: { strongest: "最強", first: "第一個", last: "最後一個" } },
    },
    ports: {
      image: "影像", roi: "區域（動態）", line: "理想直線", circle: "理想圓",
      ok: "沒有缺陷", defect: "有缺陷", count: "幾個", defects: "缺陷清單",
      max_deviation: "最大偏離", max_size: "最長的缺陷", total_area: "總面積",
      points: "邊緣點", deviation: "偏離序列", widths: "寬度序列",
    },
  },
  edge_model_defect: {
    label: "輪廓模型缺陷",
    description: "把良品外輪廓教成點集模型，每次沿著那條任意輪廓佈法向卡尺；向內連續偏移是少料或缺口，向外連續偏移是多料或毛刺，連續找不到邊是崩角或斷裂。",
    params: {
      roi: { label: "教導區域", help: "只在自動從參考影像教導時使用。留空則用整張參考影像。" },
      model: { label: "輪廓模型", help: "JSON：{version:1, image_size:[寬,高], closed:true, points:[[x,y],...]}。點是教導影像座標；閉合模型的正偏移代表向外。" },
      reference: { label: "參考影像", help: "選填良品影像。模型為空時，會用第一張參考影像在本次執行自動教導輪廓。" },
      calipers: { label: "卡尺數", help: "沿輪廓檢查幾個地方。愈多找得到愈小的缺陷，也愈慢。" },
      search: { label: "搜尋範圍", help: "每把法向卡尺跨過模型輪廓搜尋的總距離。" },
      caliper_width: { label: "卡尺寬度", help: "沿輪廓切線方向平均，用來降噪。" },
      edge_threshold: { label: "邊緣門檻" },
      polarity: { label: "邊緣極性", options: { any: "不限", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      edge_select: { label: "選邊", options: { strongest: "最強", first: "第一個", last: "最後一個" } },
      threshold: { label: "偏離超過", help: "離教導輪廓超過這麼多就算缺陷。" },
      min_width: { label: "至少連續幾把卡尺", help: "擋掉單把卡尺的雜訊。" },
      direction: { label: "哪一側算", options: { both: "兩側都算", inward: "只算少料", outward: "只算多料" } },
      fracture_run: { label: "連續幾把找不到邊算斷裂", help: "卡尺完全找不到邊，通常表示那一段的邊不見了。0＝不判斷裂。" },
      step_threshold: { label: "相鄰兩處落差超過", help: "從這一把到下一把忽然跳了。0＝不判階差。" },
      max_defects: { label: "超過幾個才算不良", help: "0＝有缺陷就不良。" },
      teach_simplify: { label: "教導簡化量", help: "模型為空且用參考影像教導時的多邊形近似公差。" },
      smoothing: { label: "剖面平滑" },
    },
    ports: {
      image: "影像", roi: "教導區域（動態）",
      ok: "沒有缺陷", defect: "有缺陷", count: "幾個", defects: "缺陷清單",
      max_deviation: "最大偏離", points: "邊緣點", deviations: "偏離序列", missing: "找不到邊的索引",
    },
  },
  defect_diff: {
    label: "差異缺陷",
    description: "與良品範本對齊後做灰階差異（absdiff → 門檻 → 形態學），差異區域即缺陷。",
    params: {
      template: {
        label: "良品範本",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。範本需與影像同尺寸（或會被縮放到相同尺寸）。",
      },
      align: {
        label: "對齊",
        options: {
          none: "不對齊",
          phase: "相位相關（平移）",
          ecc: "ECC（平移＋旋轉）",
        },
      },
      blur: {
        label: "前置高斯核",
        group: "進階",
      },
      threshold: {
        label: "差異門檻",
      },
      morph: {
        label: "形態學開運算核",
        group: "進階",
      },
      min_area: {
        label: "最小缺陷面積",
      },
      max_count: {
        label: "最多輸出",
      },
      border: {
        label: "忽略邊界",
        help: "對齊後邊界會有假差異，忽略此寬度。",
        group: "進階",
      },
    },
    ports: {
      template_image: "良品圖",
      image: "影像",
      roi: "區域（動態）",
      ok: "無缺陷",
      defect: "有缺陷",
      defects: "缺陷列表",
      count: "數量",
      total_area: "總面積",
      defect_mask: "缺陷遮罩",
      diff: "差異影像",
    },
  },
  defect_stat: {
    label: "統計良品比對",
    description: "與多張良品建的統計範本比對：每個像素有自己的平均與變異範圍，紋理區允許波動、平坦區抓得緊。偏離正常幾倍標準差以上就是缺陷。打光變動與材質紋理下比單張良品穩得多。",
    params: {
      model: { label: "統計範本", help: "用 POST /vision/assets/stat-template 或 manage.py stat_template 由良品影像建立（.npz 檔案資產）。" },
      roi: { label: "區域", help: "尺寸必須與建立範本時的區域相同；留空則整張影像。" },
      align: { label: "對齊", options: { none: "不對齊", phase: "相位相關（平移）" } },
      sigma: { label: "σ 門檻", help: "偏離正常幾倍標準差算缺陷。先用 3；良品被誤判就調高。" },
      min_sigma_floor: { label: "最小變異", help: "標準差不會低於此值，均勻區才不會把單階雜訊當缺陷。" },
      min_area: { label: "最小缺陷面積" },
      direction: { label: "方向", options: { both: "變暗或變亮", darker: "只看變暗", brighter: "只看變亮" } },
      border: { label: "忽略邊界", help: "對齊後邊界會有假差異，忽略這些像素。" },
      morph: { label: "開運算核", group: "進階" },
      max_count: { label: "最多輸出", group: "進階" },
    },
    ports: { image: "影像", roi: "區域（動態）", ok: "乾淨", defect: "有缺陷", count: "數量", total_area: "總面積", max_sigma: "最大偏離", defect_mask: "缺陷遮罩", deviation: "偏離影像", regions: "缺陷" },
  },
  distance: {
    label: "距離",
    description: "兩個東西之間的距離（像素）。多半是兩點，但 A 與 B 也可以是線或圓：孔到邊的間隙、兩孔之間的淨距、凸台到基準線多遠。點＝{x,y} 或 [x,y]（也可分別接四個數值），線＝{x1,y1,x2,y2}，圓＝{cx,cy,r}。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      mode: {
        label: "量測",
        help: "後三種在 A 或 B 是圓或線時才有差別：圖面標的通常是孔的邊緣，不是圓心。",
        options: {
          euclid: "直線距離",
          dx: "X 方向距離",
          dy: "Y 方向距離",
          nearest: "最近的兩點（邊到邊）",
          farthest: "最遠的兩點",
          centers: "中心到中心",
        },
      },
    },
    ports: { distance_world: "距離（物理量）", unit: "單位",
      image: "影像",
      a: "A（點／線／圓）",
      b: "B（點／線／圓）",
      distance: "距離",
    },
  },
  dl_retrieval: {
    label: '參考庫比對',
    description: '將影像與已儲存的參考庫比較，回傳最接近的類別。',
    params: {
      model: { label: '參考庫', help: '用於比對的已儲存參考庫。' },
      roi: { label: 'ROI', help: '要比對的區域；留空代表全圖。' },
      topk: { label: '投票數', help: '用幾張最接近的參考圖決定類別。' },
      min_similarity: { label: '最低相似度', help: '低於此值時走 not_matched。' },
      expected: { label: '預期類別', help: '選填；填入後只有相符才是 ok。' },
      device: { label: '執行裝置', options: { auto: '自動', cpu: 'CPU', cuda: 'CUDA', directml: 'DirectML' } },
      backbone_path: { label: '參考比對檔', help: '測試用內部檔案覆寫。' },
    },
    ports: {
      label: '類別',
      similarity: '相似度',
      confidence: '信心',
      topk: '最接近清單',
      ok: 'OK',
      ng: 'NG',
      not_matched: '未符合',
    },
  },
  dl_anomaly: {
    label: "深度學習異常檢測",
    description: "用只以良品訓練的模型，為畫面每個區域打「與教導良品差多少」的分數。超過門檻的就是異常——刮痕、凹陷、缺料、異物——完全不必給它看過缺陷。調門檻時看分數圖。",
    params: {
      model: { label: "異常模型", help: "在教導頁以「異常檢測（只教良品）」訓練。" },
      roi: { label: "區域", help: "留空則整張影像；區域會縮放到模型的輸入尺寸。" },
      threshold: { label: "門檻", help: "異常分數高於此值的像素視為缺陷。0 = 使用模型內建的自動門檻。" },
      min_area: { label: "最小缺陷面積" },
      device: { label: "裝置", options: { auto: "自動（有 GPU 就用）", cpu: "CPU", cuda: "CUDA" } },
      max_count: { label: "最多輸出", group: "進階" },
    },
    ports: { image: "影像", roi: "區域（動態）", ok: "乾淨", defect: "有缺陷", score: "最大分數", count: "數量", total_area: "總面積", score_map: "分數圖", mask: "遮罩", regions: "區域", threshold_used: "使用的門檻" },
  },
  dl_classify: {
    label: "DL 分類",
    description: "以 ONNX 分類模型判斷區域屬於哪一類；最高分類別分數達門檻走 pass。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "類別名稱",
        help: "每行一個類別，順序與模型輸出一致；留空則用索引。",
      },
      input_size: {
        label: "輸入尺寸",
        help: "模型輸入為固定尺寸時以模型為準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 為單位；偵測網路通常填 0。",
        group: "前處理",
      },
      std: {
        help: "偵測網路通常填 1。",
        group: "前處理",
      },
      color_order: {
        label: "色彩順序",
        group: "前處理",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      threshold: {
        label: "分數門檻",
      },
      pass_labels: {
        label: "合格類別",
        help: "逗號分隔；不為空時，最高分類別需在此清單內才 pass。",
      },
      apply_softmax: {
        label: "輸出套用 softmax",
        help: "模型已輸出機率時可關閉。",
        group: "前處理",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      pass: "合格",
      fail: "不良",
      label: "類別",
      score: "分數",
      index: "索引",
    },
  },
  dl_detect: {
    label: "DL 物件偵測",
    description: "以 ONNX 偵測模型（偵測網路風格輸出）找物件；含 letterbox 前處理與 NMS。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "類別名稱",
        help: "每行一個類別，順序與模型輸出一致；留空則用索引。",
      },
      input_size: {
        label: "輸入尺寸",
        help: "模型輸入為固定尺寸時以模型為準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 為單位；偵測網路通常填 0。",
        group: "前處理",
      },
      std: {
        help: "偵測網路通常填 1。",
        group: "前處理",
      },
      color_order: {
        label: "色彩順序",
        group: "前處理",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心門檻",
      },
      iou: {
        label: "NMS IoU",
      },
      max_count: {
        label: "最多輸出",
      },
      filter_labels: {
        label: "只保留類別",
        help: "逗號分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      normalized: {
        label: "輸出座標為 0~1",
        help: "模型輸出框為正規化座標時開啟。",
        group: "前處理",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      detections: "偵測結果",
      count: "數量",
      matches: "匹配（含 cx, cy）",
      labels: "類別列表",
    },
  },
  dl_instance: {
    label: "DL 實例分割",
    description: "以實例分割 ONNX 模型找出每個物件的輪廓與類別（含 letterbox 前處理、NMS 與 mask 合成）。可在平台的深度學習頁教導。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "類別名稱",
        help: "每行一個類別，順序與模型輸出一致；留空則用索引。",
      },
      input_size: {
        label: "輸入尺寸",
        help: "模型輸入為固定尺寸時以模型為準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 為單位；偵測網路通常填 0。",
        group: "前處理",
      },
      std: {
        help: "偵測網路通常填 1。",
        group: "前處理",
      },
      color_order: {
        label: "色彩順序",
        group: "前處理",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心門檻",
      },
      iou: {
        label: "NMS IoU",
      },
      max_count: {
        label: "最多輸出",
      },
      filter_labels: {
        label: "只保留類別",
        help: "逗號分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多數量",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      count: "數量",
      matches: "實例",
      mask: "聯合遮罩",
      contours: "輪廓",
    },
  },
  dl_segment: {
    label: "DL 語意分割",
    description: "以 ONNX 分割模型輸出每像素類別（argmax），回傳類別遮罩與各類面積。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "類別名稱",
        help: "每行一個類別，順序與模型輸出一致；留空則用索引。",
      },
      input_size: {
        label: "輸入尺寸",
        help: "模型輸入為固定尺寸時以模型為準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 為單位；偵測網路通常填 0。",
        group: "前處理",
      },
      std: {
        help: "偵測網路通常填 1。",
        group: "前處理",
      },
      color_order: {
        label: "色彩順序",
        group: "前處理",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      target_class: {
        label: "目標類別索引",
        help: "mask 輸出為此類別的 0/255 遮罩；class_map 為全部類別索引。",
      },
      min_area: {
        label: "合格最小面積",
        group: "判定",
      },
      max_area: {
        label: "合格最大面積",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      ok: "合格",
      ng: "不良",
      mask: "目標遮罩",
      class_map: "類別圖",
      area: "目標面積",
      classes: "各類面積",
    },
  },
  draw_result: {
    label: "結果影像",
    description: "把上游工具的標記畫進影像，產生可存檔／可顯示的結果圖（OK 綠、NG 紅）。",
    params: {
      thickness: {
        label: "線寬",
      },
      banner: {
        label: "顯示判定橫幅",
      },
    },
    ports: {
      image: "影像",
      overlays: "標記",
    },
  },
  edge_density: {
    label: "邊緣密度",
    description: "區域內 Canny 邊緣像素比例；平滑表面出現刮痕、髒污時比例會升高。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      canny_low: {
        label: "Canny 低門檻",
      },
      canny_high: {
        label: "Canny 高門檻",
      },
      blur: {
        label: "前置高斯核",
        group: "進階",
      },
      max_ratio: {
        label: "合格最大比例",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      ok: "合格",
      ng: "超標",
      ratio: "邊緣比例",
      edge_pixels: "邊緣像素數",
      edges: "邊緣影像",
    },
  },
  surface_filter: {
    label: "表面缺陷濾波",
    description: "在本身就有紋理的表面上把刮傷、髮絲與細裂紋挑出來。一般的邊緣濾波連紋理一起找；這一個沿著缺陷方向平均、跨著缺陷方向微分，換幾個角度取最強的，所以細長的痕跡會浮出來、紋路不會。結果拿去二值化，或直接用最強回應判定。",
    params: {
      polarity: { label: "要找的", options: { dark: "比表面暗（常見的刮傷）", bright: "比表面亮", any: "都可以" } },
      width: { label: "缺陷寬度", help: "痕跡大概幾個像素寬。太小紋理會穿過來，太大細刮傷會被吃掉。" },
      length: { label: "缺陷長度", help: "痕跡延伸多長。愈長把表面平均掉愈多，但短的痕跡也會跟著不見。" },
      directions: { label: "方向數", help: "在半圈裡試幾個角度。多了只是慢一點、好一點點；8 個大多夠用。" },
      gain: { label: "增益", help: "回應變成影像之前乘上去的倍數。調到刮傷看得清楚、表面仍然暗為止。" },
      offset: { label: "偏移", help: "每個像素都加上這個值。" },
      roi: { label: "區域", help: "只濾這一塊，其餘原樣傳下去。" },
    },
    ports: { image: "影像", region: "區域（動態）", max_response: "最強回應", mean_response: "平均回應" },
  },
  fft_filter: {
    label: "頻域濾波（FFT）",
    description: "頻域濾波：低通去週期性紋理／雜訊、高通留邊緣，截斷（truncate）或高斯衰減（attenuate）。另輸出頻譜圖供檢視。",
    params: {
      mode: {
        label: "濾波",
        options: {
          lowpass: "低通（保留大結構）",
          highpass: "高通（保留邊緣／細紋，以中灰 128 為零點）",
        },
      },
      style: {
        label: "方式",
        options: {
          truncate: "截斷",
          attenuate: "高斯衰減",
        },
      },
      cutoff: {
        label: "截止（半徑比例）",
      },
    },
    ports: {
      image: "影像",
      spectrum: "頻譜",
    },
  },
  filter: {
    label: "卷積濾波",
    description: "卷積與邊緣濾波：銳利化、Canny 邊緣、Laplacian、Sobel／Prewitt 梯度、高通、浮雕，或自訂 3×3 kernel（JSON）。平滑用「模糊」工具。",
    params: {
      method: {
        label: "方法",
        options: {
          sharpen: "銳利化",
          canny: "Canny 邊緣（二值）",
          gradient: "梯度強度（Sobel）",
          prewitt: "Prewitt 梯度",
          highpass: "高通",
          emboss: "浮雕",
          custom: "自訂 3×3",
        },
      },
      strength: {
        label: "強度",
      },
      low: {
        label: "Canny 低門檻",
      },
      high: {
        label: "Canny 高門檻",
      },
      ksize: {
        label: "核大小",
      },
      kernel: {
        label: "自訂 kernel",
        help: "3×3 數字陣列。",
      },
    },
    ports: {
      image: "影像",
    },
  },
  find_circle: {
    label: "找圓",
    description: "從 ROI 中心向外發射徑向掃描線找邊緣點，再以最小平方或 RANSAC 擬合圓。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      roi: {
        label: "區域",
        help: "圓／圓環：由中心往外掃到外半徑（圓環可設扇形起迄角，只掃該扇形）；矩形：掃到內切半徑。",
      },
      polarity: {
        label: "邊緣極性",
        help: "沿掃描線由內往外的灰階變化方向。",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
        help: "灰階梯度低於此值不算邊緣。",
      },
      num_rays: {
        label: "掃描線數",
      },
      edge_select: {
        label: "取哪個邊緣",
        options: {
          strongest: "最強",
          first: "第一個（最靠內）",
          last: "最後一個（最靠外）",
        },
      },
      ransac: {
        label: "RANSAC 剔除離群",
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "進階",
      },
      refine: {
        label: "重掃精修",
        help: "ROI 中心偏離圓心時，以擬合圓心重掃一次讓掃描線與邊緣垂直。",
        group: "進階",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
    },
    ports: { cx_world: "圓心 X（世界）", cy_world: "圓心 Y（世界）", r_world: "半徑（物理量）", unit: "單位",
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      cx: "中心 X",
      cy: "中心 Y",
      r: "半徑",
      points: "邊緣點",
      score: "分數",
      circle: "圓",
    },
  },
  find_rectangle: {
    label: "找矩形",
    description: "一次找出矩形工件的四條邊：卡尺從區域的四邊各自往內掃，每條邊擬合一條線，四個角就是線的交點。回中心、寬、高與角度，找到的矩形也直接當區域傳下去——後面那一步就能在工件落在哪裡就量哪裡。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      roi: { label: "區域", help: "畫得比工件大一點；卡尺會從四邊往內掃。" },
      polarity: { label: "邊緣極性", help: "由外往內掃時的灰階變化。" },
      edge_threshold: { label: "邊緣門檻" },
      calipers: { label: "每邊卡尺數" },
      search: { label: "搜尋深度", help: "每把卡尺往裡面掃多深，以區域的比例計。夠碰到邊就好，太深會掃到對面那條邊。" },
      caliper_width: { label: "卡尺寬度", help: "沿著邊平均，用來降噪。" },
      edge_select: { label: "選邊", options: { strongest: "最強", first: "第一個（最外）", last: "最後一個（最內）" } },
      ransac: { label: "RANSAC 去離群" },
      ransac_tol: { label: "RANSAC 容差" },
      smoothing: { label: "剖面平滑" },
    },
    ports: { cx_world: "中心 X（世界）", cy_world: "中心 Y（世界）", width_world: "寬度（物理量）", height_world: "高度（物理量）", angle_world: "角度（世界）", unit: "單位", image: "影像", roi: "區域（動態）", found: "找到", not_found: "沒找到", cx: "中心 X", cy: "中心 Y", width: "寬", height: "高", angle: "角度", rect: "矩形", corners: "角點", lines: "四條邊" },
  },
  find_quadrilateral: {
    label: "四邊求角點",
    description: "把四條邊變成一個四邊形：依序（繞工件一圈）接四個找線的結果，算出四個角、四條邊長與兩條對角線。工件不是矩形時用它——錐形墊、梯形、斜著看的工件。",
    params: {},
    ports: { image: "影像", a: "邊 1", b: "邊 2", c: "邊 3", d: "邊 4", found: "找到", not_found: "沒找到", corners: "角點", cx: "中心 X", cy: "中心 Y", sides: "邊長", diagonals: "對角線", area: "面積" },
  },
  find_parallel_lines: {
    label: "找一對邊",
    description: "一次找出溝、肋或縫的兩側：每把卡尺找的是一對邊而不是一條邊，兩側各擬合一條線，並回報每把卡尺量到的寬度與整體寬度。中線也一起給——後面要量的通常就是它。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      roi: { label: "區域", help: "長邊沿著這一對邊，卡尺跨著短邊掃。" },
      pair_polarity: { label: "兩邊之間", options: { any: "都可以", bright: "比周圍亮", dark: "比周圍暗" } },
      pair_mode: { label: "取哪一對", options: { widest: "最寬的一對", narrowest: "最窄的一對", first_last: "最外面的一對", strongest: "最強的一對", expected: "最接近預期寬度" } },
      expected_width: { label: "預期寬度" },
      edge_threshold: { label: "邊緣門檻" },
      calipers: { label: "卡尺數" },
      caliper_width: { label: "卡尺寬度" },
      ransac: { label: "RANSAC 去離群" },
      ransac_tol: { label: "RANSAC 容差" },
      smoothing: { label: "剖面平滑" },
    },
    ports: { distance_world: "寬度（物理量）", min_distance_world: "最窄寬度（物理量）", max_distance_world: "最寬寬度（物理量）", angle_world: "角度（世界）", unit: "單位", image: "影像", roi: "區域（動態）", found: "找到", not_found: "沒找到", distance: "寬度", min_distance: "最窄", max_distance: "最寬", angle: "角度", line_a: "邊 A", line_b: "邊 B", center_line: "中線", widths: "各處寬度", found_count: "找到成對的卡尺數" },
  },
  find_lines_multi: {
    label: "找多條線",
    description: "找出區域裡每一條直邊，不只一條：連接器外殼的幾個面、格線、一排腳。先取邊緣點，擬合最強的一條線之後把它的點拿掉，再找下一條，直到沒有值得稱為線的東西為止。",
    params: {
      roi: { label: "區域" },
      max_lines: { label: "最多幾條" },
      edge_threshold: { label: "邊緣門檻", help: "灰階梯度多大才算邊。" },
      min_points: { label: "每條線的點數", help: "點數不到這個數就不算一條線。" },
      tolerance: { label: "擬合容差" },
      min_length: { label: "最短長度" },
      angle_filter: { label: "只要接近這個角度的線" },
      angle_tolerance: { label: "角度容差", help: "0＝不限角度。" },
    },
    ports: { image: "影像", roi: "區域（動態）", found: "找到", not_found: "沒找到", count: "幾條", lines: "線", angles: "角度", first: "第一條", points: "邊緣點" },
  },
  find_circles_matrix: {
    label: "找圓陣列",
    description: "一次找出整排的孔、球或墊：區域依行列切成格子，每格找一個圓。回報每個圓心與半徑、哪幾格是空的，以及格距——球柵陣列、連接器、鑽孔板要的就是這個答案。",
    params: {
      roi: { label: "區域", help: "把整個陣列框起來；會平均切成格子。" },
      rows: { label: "行數" },
      cols: { label: "列數" },
      polarity: { label: "邊緣極性", help: "由格子中心往外掃時的灰階變化。" },
      edge_threshold: { label: "邊緣門檻" },
      min_radius: { label: "最小半徑" },
      max_radius: { label: "最大半徑", help: "0＝到格子的一半。" },
      num_rays: { label: "掃描線數" },
      smoothing: { label: "剖面平滑" },
    },
    ports: { image: "影像", roi: "區域（動態）", found: "全部找到", not_found: "有缺", count: "找到幾個", expected: "預期幾個", missing: "缺的格子", centers: "圓心", radii: "半徑", mean_radius: "平均半徑", pitch_x: "橫向格距", pitch_y: "縱向格距" },
  },
  find_line: {
    label: "找直線",
    description: "在矩形區域內放多條垂直於長邊的卡尺掃描線找邊緣點，再擬合直線（可 RANSAC）。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      roi: {
        label: "區域",
        help: "長邊方向為直線方向，卡尺沿短邊掃描。",
      },
      polarity: {
        label: "邊緣極性",
        help: "沿短邊（由上到下／由左到右）的灰階變化。",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
      },
      num_calipers: {
        label: "卡尺數",
      },
      direction: {
        label: "取哪個邊緣",
        options: {
          first: "第一個",
          last: "最後一個",
          strongest: "最強",
        },
      },
      ransac: {
        label: "RANSAC 剔除離群",
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "進階",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
      gap_tolerant: {
        label: "邊是斷續的",
        help: "虛線或中斷的邊：線的兩端取「真的找到邊」的範圍，而不是區域的兩端。擬合本身本來就會跳過缺口。",
        group: "進階",
      },
    },
    ports: { x1_world: "起點 X（世界）", y1_world: "起點 Y（世界）", x2_world: "終點 X（世界）", y2_world: "終點 Y（世界）", angle_world: "角度（世界）", unit: "單位",
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      angle: "夾角",
      line: "線",
      points: "邊緣點",
      coverage: "覆蓋率",
    },
  },
  fit_arc: {
    label: "圓弧擬合",
    description: "在區域內找邊緣點並以最小平方（可 RANSAC）擬合圓弧：R 角、杯口圓角的半徑與圓心。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      roi: {
        label: "區域",
        help: "圓／環／多邊形：由中心往外徑向掃描；矩形：沿長邊放卡尺。",
      },
      polarity: {
        label: "邊緣極性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
      },
      num_rays: {
        label: "掃描線數",
        help: "圓／環／多邊形為徑向掃描線數，矩形為卡尺數。",
      },
      edge_select: {
        label: "取哪個邊緣",
        options: {
          strongest: "最強",
          first: "第一個",
          last: "最後一個",
        },
      },
      refine: {
        label: "重掃精修",
        help: "擬合後以擬合中心重掃一次：ROI 偏心或多邊形 ROI 時精度明顯較好。",
        group: "進階",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
      ransac: {
        label: "RANSAC 剔除離群",
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "進階",
      },
    },
    ports: { cx_world: "圓心 X（世界）", cy_world: "圓心 Y（世界）", radius_world: "半徑（物理量）", start_angle_world: "起始角度（世界）", end_angle_world: "結束角度（世界）", unit: "單位",
      image: "影像",
      roi: "區域（動態）",
      radius: "半徑",
      cx: "中心 X",
      cy: "中心 Y",
      residual_rms: "殘差 RMS",
      points: "邊緣點",
      start_angle: "起角",
      end_angle: "終角",
      circle: "圓",
    },
  },
  fit_ellipse: {
    label: "橢圓擬合",
    description: "在區域內找邊緣點並以直接最小平方（Direct）擬合橢圓；roundness = 短軸／長軸（1 為正圓），用來量杯口橢圓度。",
    params: {
      roi: {
        label: "區域",
      },
      polarity: {
        label: "邊緣極性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
      },
      num_rays: {
        label: "掃描線數",
        help: "圓／環／多邊形為徑向掃描線數，矩形為卡尺數。",
      },
      edge_select: {
        label: "取哪個邊緣",
        options: {
          strongest: "最強",
          first: "第一個",
          last: "最後一個",
        },
      },
      refine: {
        label: "重掃精修",
        help: "擬合後以擬合中心重掃一次：ROI 偏心或多邊形 ROI 時精度明顯較好。",
        group: "進階",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      cx: "中心 X",
      cy: "中心 Y",
      a: "長半軸",
      b: "短半軸",
      angle: "長軸角度",
      roundness: "圓度 b/a",
      residual_rms: "殘差 RMS",
      points: "邊緣點",
    },
  },
  image_fixture: {
    label: "影像跟隨",
    description: "依定位補正的結果把影像轉回教導時的姿態，後面每一步看到的工件就永遠在同一個地方。要沿用一條在單一樣品上調好的流程，這是最省事的做法：沒有區域需要跟隨，教導好的範本照樣比得到。",
    params: {
      border: { label: "邊緣填色", help: "影像轉過之後角落會空出來，這裡決定填什麼。", options: { black: "黑", white: "白", replicate: "最近的像素" } },
      smooth: { label: "平滑像素", help: "開：內插，看起來對、量起來也準。關：取最近的像素，標記與遮罩不會糊掉。" },
    },
    ports: { image: "影像", transform: "位置修正", dx: "dx", dy: "dy", dtheta: "角度差" },
  },
  fixture_roi: {
    label: "ROI 跟隨",
    description: "把畫好的 ROI 依定位補正的 dx/dy/dθ 移動，輸出動態區域給下游工具的 ROI 輸入埠。",
    params: {
      roi: {
        label: "區域",
      },
    },
    ports: {
      image: "影像",
      transform: "變換",
      region: "區域",
    },
  },
  formula: {
    label: "公式",
    description: "以 a、b、c、d 代表輸入，寫一段算式（例如 abs(a-b)/c*100）。支援 +-*/、比較、and/or、abs/min/max/sqrt/…。",
    params: {
      expression: {
        label: "公式",
        help: "變數 a b c d 對應四個輸入；結果可為數值或布林。",
      },
    },
    ports: {
      value: "值",
      result: "布林",
    },
  },
  points_merge: {
    label: "點集合",
    description: "把幾個步驟找到的點併成一組，一次擬合或一次量測就涵蓋全部：四把卡尺量同一條邊的邊緣點、整排孔的圓心。每個輸入吃一個點或一串點。",
    params: {
      unique: { label: "去掉重複", help: "距離小於 0.1 像素的點算同一個。" },
    },
    ports: { a: "A", b: "B", c: "C", d: "D", image: "影像", points: "點", count: "數量", cx: "中心 X", cy: "中心 Y" },
  },
  geometry: {
    label: "幾何計算",
    description: "算出圖面上標了、影像上卻看不到的幾何：兩線交點、點到線垂距、與某條線平行或垂直的線、兩邊的中線、角平分線、三點定圓、繞一點旋轉。線與點接找線／找圓／卡尺的輸出；線與圓輸出可以直接接給下一步。",
    params: {
      calibration: { label: "標定資產", group: "進階", help: "選填；選了標定就多出 *_world 與 unit 埠，優先使用機構映射。長度使用量測位置的面積等效比例，角度單位為度。" },
      mode: {
        label: "計算",
        options: {
          intersect: "兩線交點",
          point_line: "點到線垂距",
          midpoint: "兩點中點",
          project: "點投影到線",
          line_2pts: "兩點連成的線",
          parallel: "與這條線平行的線",
          perpendicular: "與這條線垂直的線",
          perp_bisector: "兩點的中垂線",
          median: "兩線的中線",
          bisector: "角平分線",
          circle_3pts: "三點定圓",
          rotate: "繞一點旋轉",
          offset: "平移點集或比對結果",
        },
      },
      offset: { label: "偏移", help: "沒接要通過的點時，把線往旁邊平移多少。正值是線方向的右手邊。" },
      angle: { label: "角度", help: "畫面順時針為正，與平台其他角度同向。" },
      offset_x: { label: "偏移 X", help: "未接 offset_x 埠時使用。" },
      offset_y: { label: "偏移 Y", help: "未接 offset_y 埠時使用。" },
      sign: { label: "方向", options: { add: "加回", subtract: "扣除" } },
    },
    ports: { x_world: "X（世界）", y_world: "Y（世界）", distance_world: "距離或半徑（物理量）", angle_world: "角度（世界）", unit: "單位",
      a: "A（線／點）",
      b: "B（線／點）",
      c: "C（點）",
      distance: "距離",
      angle: "角度",
      line: "線",
      circle: "圓",
      points: "點集",
      matches: "比對結果",
      count: "數量",
      offset_x: "偏移 X",
      offset_y: "偏移 Y",
    },
  },
  grayscale: {
    label: "灰階",
    description: "彩色轉灰階；已是灰階則直通。",
    ports: {
      image: "影像",
    },
  },
  sharpness: {
    label: "清晰度",
    description: "評估 ROI 內的對焦與震動模糊程度，可設定上下限並輸出雜訊估計。",
    params: {
      roi: {
        label: "區域",
        help: "留空時使用整張影像。",
      },
      method: {
        label: "方法",
        help: "Laplacian variance 最通用；Gradient energy 適合穩定邊緣；Autocorrelation drop 對隨機雜訊較不敏感。",
        options: {
          laplacian: "Laplacian 變異數",
          gradient: "梯度能量",
          autocorrelation: "自相關落差",
        },
      },
      normalize: {
        label: "依對比正規化",
        help: "開啟後，分數是每像素反應能量除以 ROI 灰階變異數：Laplacian 為 px^-4，gradient 為 px^-2，autocorrelation 為無量綱相關落差。",
      },
      min_score: {
        label: "最低分數",
        help: "0 表示不判下限；分數低於此值走 NG。",
      },
      max_score: {
        label: "最高分數",
        help: "0 表示不判上限；分數高於此值走 NG，可用於攔截雜訊或過度銳化造成的虛高分數。",
      },
      noise_estimate: {
        label: "估計雜訊",
        help: "輸出穩健高頻雜訊水準；低光源會讓雜訊抬高清晰度分數。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      score: "分數",
      noise: "雜訊",
      method: "方法",
      ok: "合格",
      ng: "超出範圍",
    },
  },
  histogram: {
    label: "直方圖",
    description: "區域內 256 階灰階直方圖與峰值。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      normalize: {
        label: "正規化（比例）",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      histogram: "直方圖",
      peak: "峰值灰階",
      peak_count: "峰值數量",
      otsu: "Otsu 門檻",
    },
  },
  hough_circles: {
    label: "Hough 找圓",
    description: "以梯度法在區域內找多個圓。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      min_radius: {
        label: "最小半徑",
      },
      max_radius: {
        label: "最大半徑",
      },
      min_dist: {
        label: "圓心最小間距",
      },
      param1: {
        label: "Canny 高門檻",
        group: "進階",
      },
      param2: {
        label: "累積門檻",
        help: "越小找到越多（含誤判）。",
        group: "進階",
      },
      blur: {
        label: "前置中值濾波核",
        group: "進階",
      },
      max_count: {
        label: "最多輸出",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      circles: "圓",
      count: "數量",
    },
  },
  hough_lines: {
    label: "Hough 找線段",
    description: "Canny 邊緣後以機率 Hough（HoughLinesP）找線段。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      canny_low: {
        label: "Canny 低門檻",
      },
      canny_high: {
        label: "Canny 高門檻",
      },
      threshold: {
        label: "累積門檻",
      },
      min_length: {
        label: "最短線段",
      },
      max_gap: {
        label: "最大斷點間隙",
      },
      max_count: {
        label: "最多輸出",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      lines: "線段",
      count: "數量",
    },
  },
  if_number: {
    label: "數值判斷",
    description: "把輸入數值與門檻比較，走 true / false 分支；下游連到分支把手的節點只在該分支被選中時執行。",
    params: {
      operator: {
        label: "比較",
      },
      threshold: {
        label: "門檻",
      },
      tolerance: {
        label: "容差（= / ≠ 用）",
      },
    },
    ports: {
      value: "值",
      result: "結果",
    },
  },
  fixed_image: {
    label: "固定影像",
    description: "以上傳到此步驟的圖片取代相機：一張，或多張每次執行輪流取用。圖片跟著流程保存，從範本或上傳圖片建立的流程在哪裡都能執行；也用來把參考圖（範本、良品、白參考）透過圖片輸入埠交給需要的工具。",
    params: {
      images: {
        label: "圖片",
        help: "上傳一張或多張圖片；圖片會跟著流程保存。",
      },
      mode: {
        label: "取哪一張",
        options: {
          cycle: "每次執行取下一張（含試執行）",
          fixed: "固定取第 N 張",
        },
      },
      index: {
        label: "序號",
        help: "1 = 第一張。",
      },
      role: {
        label: "角色",
        options: {
          acquire: "待檢影像（API 送圖、批次測試或重跑時以送來的圖取代）",
          reference: "供其他工具使用的參考圖（範本、良品、白參考）：永不取代",
        },
      },
      convert: {
        label: "色彩",
        options: {
          keep: "維持上傳時的樣子",
          gray: "灰階",
          bgr: "彩色（3 通道）",
        },
      },
    },
    ports: {
      image: "影像",
      index: "圖片序號",
      name: "圖片名稱",
      count: "圖片張數",
      width: "寬",
      height: "高",
    },
  },
  image_source: {
    label: "影像來源",
    description: "從設定的影像來源抓一張影像；API 直接送圖時（POST run 附影像）優先使用送來的影像。",
    params: {
      source_id: {
        label: "影像來源",
        help: "留空則只接受 API 送來的影像。",
      },
      mode: {
        label: "取像模式",
        options: {
          auto: "暫存／API 送圖優先，否則從來源庫抓",
          source: "一律從來源抓",
          input: "只用暫存影像（試跑上傳或 API 送圖；沒有就報錯）",
        },
      },
      convert: {
        label: "色彩",
        options: {
          keep: "維持原樣",
          gray: "轉灰階",
          bgr: "轉彩色（BGR）",
        },
      },
      exposure_us: {
        label: "曝光",
        help: "空白或 0 不改相機曝光。",
      },
      gain_db: {
        label: "增益",
        help: "空白或 0 不改相機增益。",
      },
    },
    ports: {
      image: "影像",
      width: "寬",
      height: "高",
      applied: "已套用相機設定",
    },
  },
  in_range: {
    label: "在範圍內",
    description: "數值是否落在 [下限, 上限]；常用於量測值公差判定。",
    params: {
      low: {
        label: "下限",
      },
      high: {
        label: "上限",
      },
    },
    ports: {
      value: "值",
      inside: "在範圍內",
      outside: "超出範圍",
      result: "結果",
    },
  },
  intensity: {
    label: "灰階統計",
    description: "區域內的灰階平均、標準差、最小、最大、中位數。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像；點＝單一像素。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      mean: "平均",
      std: "標準差",
      min: "最小",
      max: "最大",
      median: "中位數",
      pixels: "像素數",
    },
  },
  judge: {
    label: "OK / NG 判定",
    description: "決定整個 run 的判定結果。連到分支把手時，被選中即判定；或用布林輸入決定。",
    params: {
      verdict: {
        label: "判定",
        options: {
          by_input: "依布林輸入（真=OK，假=NG）",
          ok: "固定 OK",
          ng: "固定 NG",
        },
      },
      label: {
        label: "結果標籤",
        help: "寫進 run.outputs.judge_label，方便自動化辨認是哪一條判定。",
      },
    },
    ports: {
      value: "布林",
      verdict: "判定",
    },
  },
  line_profile: {
    label: "線剖面",
    description: "沿著線（或折線）取灰階值，輸出剖面序列與統計；抓斷差、亮暗帶、掃描線缺陷。",
    params: {
      roi: {
        label: "線",
      },
      samples: {
        label: "取樣點數",
        help: "0 = 每像素一點。",
      },
    },
    ports: {
      image: "影像",
      roi: "線（動態）",
      values: "剖面值",
      mean: "平均",
      std: "標準差",
      min: "最小",
      max: "最大",
      length: "長度",
    },
  },
  lut: {
    label: "查表轉換（LUT）",
    description: "灰階轉換與對比增強：線性（亮度／對比）、Gamma、對數、指數、平方、開根號、反相、直方圖等化、CLAHE；查表類彩色逐通道套用。",
    params: {
      mode: {
        label: "轉換",
        options: {
          linear: "線性（亮度／對比）",
          power: "Gamma（次方）",
          log: "對數（暗部展開）",
          exp: "指數（亮部展開）",
          sqrt: "開根號",
          square: "平方",
          invert: "反相",
          equalize: "直方圖等化",
          clahe: "CLAHE（區域對比）",
          normalize_ratio: "百分位拉伸",
          normalize_std: "平均／標準差正規化",
        },
      },
      clip: {
        label: "CLAHE clip",
      },
      tile: {
        label: "CLAHE 格數",
      },
      brightness: {
        label: "亮度",
      },
      contrast: {
        label: "對比",
      },
      gamma: { label: "Gamma" },
      low_percent: { label: "低百分位" },
      high_percent: { label: "高百分位" },
      target_mean: { label: "目標平均" },
      target_std: { label: "目標標準差" },
    },
    ports: {
      image: "影像",
    },
  },
  morphology: {
    label: "形態學",
    description: "侵蝕、膨脹、開、閉、梯度、頂帽、黑帽。",
    params: {
      op: {
        label: "運算",
        options: {
          erode: "侵蝕",
          dilate: "膨脹",
          open: "開運算",
          close: "閉運算",
          gradient: "梯度",
          tophat: "頂帽",
          blackhat: "黑帽",
        },
      },
      shape: {
        label: "核形狀",
        options: {
          rect: "矩形",
          ellipse: "橢圓",
          cross: "十字",
        },
      },
      ksize: {
        label: "核大小",
      },
      iterations: {
        label: "次數",
      },
    },
    ports: {
      image: "影像",
    },
  },
  ocr_read: {
    label: "文字辨識（OCR）",
    description: "從區域讀出印刷文字——日期碼、批號、料號——回傳字串，並附每個字的信心與框。限制字元集（日期碼用數字）能明顯提升準確率。點陣噴印或雷射打標這類通用模型讀不好的字體，在資產頁教字型後在此選用。",
    params: {
      roi: { label: "文字區域", help: "留空則整張影像。單行模式請框一行。" },
      mode: { label: "模式", options: { line: "單行（把區域當一行讀）", detect: "先偵測多行" } },
      model: { label: "模型", help: "留空 = 內建通用模型。選教導字型（.npz）則改走切分＋逐字分類。" },
      charset: { label: "字元集", options: { alnum: "字母與數字", digits: "數字（與 - . / :）", upper: "大寫字母與數字", any: "任何字元", custom: "自訂" } },
      custom_charset: { label: "自訂字元", help: "所有可能出現的字元，例如 0123456789ABCDEF-" },
      polarity: { label: "極性", options: { dark_on_light: "亮底暗字", light_on_dark: "暗底亮字" } },
      min_confidence: { label: "最低信心", help: "有一個字低於此值就視為未讀到。" },
      pattern: { label: "位置樣板", help: "N=數字、A=英文字母、X=任意；其他字元必須完全相同。留空不檢查。" },
      confusables: { label: "易混字替換", help: "一行一條 從:到；只在替換後符合該位置樣板時才套用。" },
      preprocess: { label: "前處理", options: { auto: "自動（對比拉伸與去噪）", none: "無" } },
      segmentation: { label: "切分（教導字型）", options: { projection: "投影（字元間空隙）", components: "連通域", fixed: "固定間距（已知字數）" }, group: "教導字型" },
      char_count: { label: "字數（固定間距）", help: "固定間距切分把墨跡範圍等分成這麼多格。", group: "教導字型" },
    },
    ports: { image: "影像", roi: "文字區域（動態）", found: "找到", not_found: "未找到", text: "文字", corrected: "修正後文字", pattern_ok: "樣板通過", corrections: "修正明細", items: "行", confidence: "信心", count: "行數" },
  },
  ocv_verify: {
    label: "字串驗證（OCV）",
    description: "把讀到的文字與應該是的字串比對：固定字串，或上位機為此批下發的值。? 代表任一字、# 代表任一數字；較長的印字可用包含與正規表示式模式。回報第一個錯的是第幾個字並以紅框標出。",
    params: {
      expected: { label: "預期文字", help: "? = 任一字，# = 任一數字。例：LOT######" },
      expected_source: { label: "預期來源", options: { param: "此參數", input: "預期輸入埠（上位機）" } },
      mode: { label: "模式", options: { exact: "完全相同", contains: "包含", regex: "正規表示式" } },
      min_char_confidence: { label: "最低逐字信心", help: "字對了但信心低於此值也算失敗。需要接上「行」輸入。" },
      ignore_case: { label: "忽略大小寫" },
      strip: { label: "忽略前後空白" },
    },
    ports: { text: "文字", expected: "預期", items: "行（來自文字辨識）", image: "影像（顯示用）", pass: "通過", fail: "失敗", match: "相符", actual: "實際", fail_index: "第一個錯的位置", expected_text: "預期" },
  },
  output: {
    label: "具名輸出",
    description: "把一個值以指定名稱放進 run 的 outputs，供 API / TCP 回傳給自動化系統。",
    params: {
      name: {
        label: "名稱",
      },
      decimals: {
        label: "小數位數",
      },
    },
    ports: {
      value: "值",
    },
  },
  pixel_count: {
    label: "像素數",
    description: "遮罩（或灰階以門檻二值化後）在區域內的前景像素數與比例。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      threshold: {
        label: "門檻",
        help: "大於等於此灰階算前景；輸入已是 0/255 遮罩時維持預設即可。",
      },
      min_count: {
        label: "合格最少像素",
      },
      max_count: {
        label: "合格最多像素",
        help: "0 表示不限。",
      },
    },
    ports: {
      image: "遮罩／影像",
      roi: "區域（動態）",
      ok: "合格",
      ng: "不良",
      count: "像素數",
      ratio: "比例",
      total: "區域像素數",
    },
  },
  polar_restore: {
    label: "極座標還原",
    description: "把在展開圖上找到的點與輪廓換回原圖座標，讓極座標展開後找到的缺陷能標在原圖上。接極座標展開的「對應」輸出；下方的數值與設定只在沒接對應時才用。",
    params: {
      r_outer: {
        label: "外半徑",
        help: "只在沒接對應埠時使用。",
        group: "無對應時",
      },
      angle_step: {
        label: "角度步進",
        group: "無對應時",
        options: {
          auto: "自動（外緣 1 px 弧長）",
          "0.5": "0.5°",
          "1": "1°",
          "2": "2°",
        },
      },
      radial_step: {
        label: "徑向步進",
        group: "無對應時",
      },
      direction: {
        label: "方向",
        group: "無對應時",
        options: {
          ccw: "逆時針",
          cw: "順時針",
        },
      },
      start_angle: {
        label: "起始角",
        group: "無對應時",
      },
    },
    ports: {
      image: "原圖（顯示用）",
      mapping: "對應",
      points: "點（展開圖）",
      contours: "輪廓（展開圖）",
      cx: "中心 X",
      cy: "中心 Y",
      r_inner: "內半徑",
      r_outer: "外半徑",
      count: "數量",
      first_x: "第一個 X",
      first_y: "第一個 Y",
      first_angle: "第一個角度",
      first_radius: "第一個半徑",
    },
  },
  polar_unwrap: {
    label: "極座標展開",
    description: "把圓環攤平成長條圖：寬＝角度、高＝半徑（內圈在上）。螺紋、齒輪齒、軸承滾珠、O-ring 缺口、圓形標籤文字都變成一列直的，一般的二值化、blob、卡尺與找線工具就讀得到。把「對應」輸出接到極座標還原，結果就能畫回原圖。",
    params: {
      roi: {
        label: "圓環",
        help: "要展開的環帶。帶起迄角的圓環只展開該扇形。",
      },
      angle_step: {
        label: "角度步進",
        help: "每一欄幾度。自動＝外緣每欄 1 px，不會欠取樣。",
        options: {
          auto: "自動（外緣 1 px 弧長）",
          "0.5": "0.5°",
          "1": "1°",
          "2": "2°",
        },
      },
      radial_step: {
        label: "徑向步進",
        help: "每一列幾個像素。",
      },
      direction: {
        label: "方向",
        help: "長條圖沿圓環走的方向（以畫面為準）。",
        options: {
          ccw: "逆時針",
          cw: "順時針",
        },
      },
      start_angle: {
        label: "起始角",
        help: "長條圖左緣落在哪個角度（0 = 3 點鐘方向，正值為順時針）。扇形不用此值，從自己的起迄角開始。",
      },
      interpolation: {
        label: "內插",
        group: "進階",
        options: {
          nearest: "最近鄰",
          linear: "線性",
          cubic: "三次",
        },
      },
    },
    ports: {
      image: "影像",
      roi: "圓環（動態）",
      mapping: "對應",
      cx: "中心 X",
      cy: "中心 Y",
      r_inner: "內半徑",
      r_outer: "外半徑",
      step_deg: "每欄角度",
    },
  },
  profile_defect: {
    label: "序列缺陷",
    description: "在一維序列（圓形卡尺的半徑、或線剖面）裡找偏離基線的區段：缺口與凹陷（向內）、毛刺與凸起（向外）。卡尺完全找不到邊的位置也算缺陷——大崩邊會讓邊緣消失。接上邊緣點後，每個缺陷都畫回原圖。",
    params: {
      baseline: { label: "基線", help: "「正常」是什麼：對邊緣點擬合的圓（需要點）、滑動中位數、擬合直線或平均。", options: { fit_circle: "擬合圓（圓形卡尺的半徑）", median: "滑動中位數", fit_line: "擬合直線", mean: "平均" } },
      window: { label: "視窗", help: "滑動中位數的視窗長度（點數）。" },
      threshold: { label: "門檻", help: "算缺陷的偏離量（數值單位，或 σ 倍數）。" },
      threshold_mode: { label: "門檻模式", options: { absolute: "絕對值（數值單位）", sigma: "σ 倍數（穩健離散度）" } },
      min_width: { label: "最小寬度", help: "缺陷至少要連續幾點；擋單點雜訊。" },
      direction: { label: "方向", options: { both: "兩者", inward: "向內（凹陷、缺口、打空）", outward: "向外（毛刺、凸起）" } },
      max_defects: { label: "最多缺陷數", help: "超過此數為 NG；0 = 有缺陷就 NG。" },
      wrap: { label: "循環序列", help: "最後一點接回第一點（整圈）。線剖面請關閉。" },
      missing_as_defect: { label: "打空算缺陷", help: "沒有值的位置（卡尺找不到邊）視為向內缺陷。" },
    },
    ports: { values: "數值", points: "點", image: "影像（顯示用）", ok: "乾淨", defect: "有缺陷", count: "數量", defects: "缺陷", max_deviation: "最大偏離", baseline_values: "基線", deviation: "偏離" },
  },
  python_script: {
    label: "Python 腳本",
    description: "自己寫一段 Python（def run(ctx)）做檢測：讀影像／上游值／現場參數，回傳數值、布林、文字、資料、新影像與標記，並決定通過／不良分支。只有管理員能編輯腳本；受限執行（白名單匯入、逾時中止）。",
    params: {
      code: {
        label: "程式碼",
        help: "定義 def run(ctx)；可用 np、cv2、math 與白名單模組。回傳 dict 或單一值（數值／布林／文字／影像）。",
      },
      p1: {
        label: "現場參數 1",
        help: "腳本以 ctx.params['p1'] 讀取；技術員可在參數卡調整，不必改程式碼。",
        group: "現場參數",
      },
      p2: {
        label: "現場參數 2",
        group: "現場參數",
      },
      p3: {
        label: "現場參數 3",
        group: "現場參數",
      },
      roi: {
        label: "區域",
        help: "腳本以 ctx.roi()／ctx.crop() 取用；留空則整張影像。",
      },
      max_ms: {
        label: "逾時（毫秒）",
        help: "純 Python 迴圈超過此時間即中止（numpy／cv2 呼叫不計）。",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      pass: "合格",
      fail: "不良",
      value: "值",
      result: "布林",
      text: "文字",
      data: "資料",
    },
  },
  read_modbus: {
    label: "讀取 Modbus",
    description: "從通訊連線讀線圈與暫存器的值，供流程判斷或回傳。主站連線（modbus_tcp）是去讀 PLC／設備；從站連線（modbus_server）是讀主站寫進本平台暫存器的值（例如料號、觸發旗標）。",
    params: {
      connection: {
        label: "連線",
        help: "填通訊連線的名稱（設定頁「外部整合 → 連線」建立）。",
      },
      mapping: {
        label: "讀取表",
        help: "陣列，每項 {\"name\": 名稱, \"address\": 位址, \"scale\"?: 倍率, \"offset\"?: 加值}。位址：coil:10 / discrete:3 / holding:100 / holding:100:float32 / input:7；名稱空白時用位址當名稱。",
      },
      publish: {
        label: "同時放進具名輸出",
        help: "開啟後讀到的值會出現在 run 的 outputs（API／TCP 回傳看得到）。",
      },
      on_error: {
        label: "讀取失敗時",
        options: {
          warn: "降級：記警告，run 照常",
          fail: "讓 run 失敗",
        },
      },
      timeout_s: {
        label: "逾時（秒）",
        help: "0 = 用連線設定的逾時。",
        group: "進階",
      },
    },
    ports: {
      values: "值",
      value: "第一個值",
      ok: "成功",
    },
  },
  region_combine: {
    label: "區域組合",
    description: "把好幾個區域組成一個：從量測區挖掉孔位、字樣或反光帶（挖除）、把分開的幾塊合成一塊（聯集）、只留重疊處（交集）。結果接任何工具的區域輸入埠——blob、統計、良品比對等都照組合後的遮罩算。",
    params: {
      base: { label: "基底區域", help: "起始的區域。留空則以第一個接進來的區域為基底。" },
      mode: {
        label: "模式",
        options: { subtract: "挖除（從基底挖掉這些區域）", union: "聯集（把這些區域加進基底）", intersect: "交集（只留重疊處）" },
      },
    },
    ports: { base: "基底區域（動態）", regions: "要組合的區域", image: "影像（顯示用）", region: "區域", count: "組成數" },
  },
  region_from_shape: {
    label: "區域",
    description: "把畫好的形狀變成區域輸出，讓畫布上能有第二、第三個區域——交給區域組合的排除區與加量區域。另外會把形狀的中心、線與圓一起送出去，所以在畫布上畫一條基準線就能量每個孔到它的距離（那條線是圖面給的，影像上找不到）。本身不影響影像。",
    params: {
      roi: { label: "形狀", help: "任何形狀：矩形、旋轉矩形、圓、橢圓、圓環、多邊形。" },
    },
    ports: { image: "影像（顯示用）", region: "區域", point: "中心", line: "線", circle: "圓" },
  },
  resize: {
    label: "比例",
    description: "依比例或指定尺寸縮放；大圖先縮小再處理是最有效的加速。",
    params: {
      scale: {
        label: "比例",
      },
      width: {
        label: "寬（0 = 用比例）",
      },
      height: {
        label: "高（0 = 用比例）",
      },
      interpolation: {
        label: "插值",
        options: {
          area: "區域（縮小）",
          linear: "線性",
          nearest: "最近",
          cubic: "三次",
        },
      },
    },
    ports: {
      image: "影像",
      scale_x: "比例 X",
      scale_y: "比例 Y",
    },
  },
  rotate_flip: {
    label: "旋轉 / 翻轉",
    description: "90 度倍數旋轉、任意角度旋轉、水平／垂直翻轉。",
    params: {
      angle: {
        label: "角度（順時針）",
      },
      flip: {
        label: "翻轉",
        options: {
          none: "不翻",
          h: "水平",
          v: "垂直",
          hv: "水平＋垂直",
        },
      },
      keep_size: {
        label: "維持尺寸",
      },
    },
    ports: {
      image: "影像",
    },
  },
  send_image: {
    label: "傳送影像",
    description: "把這一步的影像經 TCP 傳圖連線（種類 tcp_image）推給上位程式，表頭帶 run id、判定與具名輸出。預設失敗只記警告、不讓 run 失敗。",
    params: {
      connection: { label: "連線", help: "TCP 傳圖連線的名稱（在「外部整合 ▸ TCP」建立；填 id 也可以）。" },
      encoding: { label: "編碼", options: { "": "依連線設定", jpeg: "JPEG", png: "PNG（無損）", raw: "原始像素" } },
      quality: { label: "JPEG 品質", group: "進階" },
      name: { label: "影格名稱", help: "放進表頭的 name；留空用連線名稱。", group: "進階" },
      include_values: { label: "附上判定與輸出", help: "把 judge 與到目前為止的具名輸出放進表頭的 values。", group: "進階" },
      only_ng: { label: "只送 NG" },
      on_error: { label: "傳送失敗時", options: { warn: "降級：記警告、繼續", fail: "讓 run 失敗" } },
      timeout_s: { label: "逾時（秒）", help: "0 用連線自己的逾時。", group: "進階" },
    },
    ports: { image: "影像", sent: "已送出", bytes: "位元組數" },
  },
  set_light: {
    label: "設定光源",
    description: "設定光源控制器某一通道的亮度、開燈或關燈。連線缺失或送出失敗預設降級，流程繼續。",
    params: {
      connection: { label: "連線", help: "在「外部整合 > 設備連線」建立的光源控制器連線名稱。" },
      channel: { label: "通道" },
      value: { label: "亮度", help: "0 到連線設定的 value_max。換料號常要調光，因此列為現場教導參數。" },
      mode: { label: "模式", options: { brightness: "設定亮度", on: "開燈", off: "關燈" } },
      required: { label: "必要", help: "送不出光源命令時讓 run 失敗；預設關閉，通訊問題只降級。" },
      timeout_s: { label: "逾時（秒）", group: "進階" },
    },
    ports: { ok: "成功" },
  },
  io_output: {
    label: "I/O 輸出",
    description: "依目前 OK/NG 判定寫出電平或非阻塞脈衝，可寫 Modbus 位址或光源控制器通道。",
    params: {
      connection: { label: "連線", help: "Modbus 或光源控制器連線名稱；填 id 也可以。" },
      address: { label: "位址", help: "Modbus 用 coil:0 這類 area:offset[:dtype]；光源控制器填通道號。" },
      on_when: { label: "何時輸出", options: { ok: "OK", ng: "NG", always: "總是" } },
      pulse_ms: { label: "脈衝", help: "0 維持電平；大於 0 時由背景計時器復位，不會讓流程執行緒 sleep。" },
      invert: { label: "反相" },
      required: { label: "必要", help: "輸出失敗時讓 run 失敗；預設關閉，通訊問題只降級。" },
      timeout_s: { label: "逾時（秒）", group: "進階" },
    },
    ports: { status: "判定", ok: "成功", active: "輸出電平" },
  },
  camera_io: {
    label: "相機 I/O",
    description: "依目前 OK/NG 判定寫出擷取端相機的輸出線；脈衝由擷取端復位，寬度不受網路延遲影響。",
    params: {
      source: { label: "影像來源" },
      line: { label: "輸出線" },
      on_when: { label: "何時輸出", options: { ok: "OK", ng: "NG", always: "總是" } },
      pulse_ms: { label: "脈衝", help: "0 維持電平；大於 0 時由擷取端背景計時器復位。" },
      invert: { label: "反相" },
      required: { label: "必要", help: "寫入相機輸出失敗時讓 run 失敗；預設關閉，通訊問題只降級。" },
      timeout_s: { label: "逾時（秒）", group: "進階" },
    },
    ports: { status: "判定", ok: "成功", active: "輸出電平" },
  },
  camera_set: {
    label: "相機設定",
    description: "寫入擷取端相機特徵，並可載入或儲存 user set。",
    params: {
      source: { label: "影像來源" },
      values: { label: "參數", help: "一行一個 name=value，例如 exposure_us=5000。" },
      user_set: { label: "User set", options: { none: "不使用", load: "套參數前載入", save: "套參數後儲存" } },
      user_set_name: { label: "User set 名稱" },
      required: { label: "必要", help: "完全連不上相機時讓 run 失敗；預設關閉，通訊問題只降級。" },
      timeout_s: { label: "逾時（秒）", group: "進階" },
    },
    ports: { ok: "成功", applied: "已套用", errors: "錯誤" },
  },
  write_log: {
    label: "寫入紀錄",
    description: "把具名輸出寫成一列 CSV 或一行 TXT，背景寫入 DATA_DIR/file_outputs 下的相對資料夾。",
    params: {
      path: { label: "相對路徑", help: "位於 DATA_DIR/file_outputs 下；絕對路徑與 .. 會被拒絕。" },
      format: { label: "格式", options: { csv: "CSV", txt: "TXT" } },
      fields: { label: "欄位", help: "一行一欄。可填欄位名，或使用 {width:.2f} 這類樣板。" },
      header: { label: "寫入標頭" },
      filename: { label: "檔名", help: "可使用 {station}、{date}、{lot}、{run_id:.8}。" },
      daily_folder: { label: "按日資料夾" },
      rotate_mb: { label: "依大小輪替", group: "輪替" },
      rotate_rows: { label: "依列數輪替", group: "輪替" },
      encoding: { label: "編碼", group: "進階" },
    },
    ports: { a: "a", b: "b", c: "c", d: "d", path: "路徑", queued: "已排入佇列" },
  },
  save_image: {
    label: "存檔",
    description: "把影像存到資料夾（依判定 OK/NG 分子資料夾可選）。檔名含時間戳與 run id。",
    params: {
      folder: {
        label: "資料夾",
        help: "留空則存到 DATA_DIR/saved/<flow_id>。",
      },
      format: {
        label: "格式",
      },
      condition: {
        label: "保存條件",
        options: { all: "全部", ok: "只存 OK", ng: "只存 NG" },
      },
      split_by_judge: {
        label: "依判定分資料夾",
      },
      only_ng: {
        label: "只存 NG",
      },
      prefix: {
        label: "檔名前綴",
      },
      filename: {
        label: "檔名",
        help: "可使用 {station}、{date}、{lot}、{run_id:.8}。",
      },
      daily_folder: {
        label: "按日資料夾",
      },
      jpeg_quality: {
        label: "JPEG 品質",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
      path: "路徑",
    },
  },
  shading_correct: {
    label: "平場校正",
    description: "把打光不均拉平。除以同一組光下拍的均勻白板影像（平場），可先扣暗場；或用大核模糊從影像本身估背景。校正後固定門檻在整個視野都適用，而不是只有中央。",
    params: {
      mode: {
        label: "模式",
        options: { flat_field: "平場（白板參考）", dark_flat: "暗場＋白板參考", estimate: "從影像估背景" },
      },
      flat: { label: "白板參考", help: "工作解析度下拍的均勻白板。上傳成影像資產。" },
      dark: { label: "暗場參考", help: "蓋上鏡頭蓋拍的一張，去掉感測器固定偏移。" },
      blur_sigma: { label: "背景模糊", help: "背景估計的範圍，要比想留下的特徵大。" },
      target_level: { label: "目標亮度", help: "白板映到的灰階（均勻白板校正後就是這個值）；0 = 白板自己的平均。估背景時是輸出的平均亮度；0 = 影像自己的平均。" },
    },
    ports: { image: "影像", mean_before: "校正前平均", mean_after: "校正後平均" },
  },
  align_offset: {
    label: "對位偏移",
    description: "把教導時的位置與現在的位置一比，算出機構要修正多少。定位補正是給區域跟隨用的，這一顆是給機構走的：多了取料點補償，選了手眼標定還會直接給機構座標。",
    params: {
      mode: {
        label: "怎麼比",
        options: {
          point: "一個點加角度",
          rectify: "單點校正",
          point_set: "好幾組對應點",
          grab: "取料點補償",
          line: "線的中點與方向",
        },
      },
      ref_x: { label: "教導 X", help: "教導時工件所在的位置（試執行一次就可以把現在的值填進來）。" },
      ref_y: { label: "教導 Y" },
      ref_angle: { label: "教導角度", help: "角度正值＝畫面順時針。" },
      ref_points: { label: "教導點集", help: "2～8 組 [x, y]，順序要與現在的點集一致。只解旋轉與平移，不含縮放。" },
      grab_x: { label: "教導取料 X", help: "教導時手臂抓在工件的哪一點。工件轉了，這一點會跟著轉。" },
      grab_y: { label: "教導取料 Y" },
      calibration: { label: "手眼標定", help: "選填。選了才會多給機構座標；沒選就只有像素。" },
    },
    ports: {
      image: "影像", matches: "定位結果", a: "目前 X", b: "目前 Y", c: "目前角度",
      points: "目前點集", line: "目前直線",
      dx: "X 偏移", dy: "Y 偏移", dtheta: "角度偏移", transform: "位置修正",
      abs_x: "絕對 X（像素）", abs_y: "絕對 Y（像素）", abs_angle: "絕對角度（影像）",
      world_x: "機構 X", world_y: "機構 Y", world_angle: "機構角度",
      found: "算出來了", not_found: "沒有目前位置",
    },
  },
  map_points: {
    label: "相機映射",
    description: "使用含 mapping 區塊的標定資產，把 A 相機座標換到 B 相機座標；可反向使用。",
    params: {
      calibration: { label: "映射標定", help: "必填；需由標定頁的相機映射模式建立，資產內要有 mapping 區塊。" },
      direction: { label: "方向", options: { forward: "正向", inverse: "反向" } },
    },
    ports: {
      image: "影像",
      points: "點集",
      matches: "定位結果",
      x: "X",
      y: "Y",
      count: "數量",
    },
  },
  shape_align: {
    label: "定位補正",
    description: "比較目前定位結果與教導時的參考位置，算出平移／旋轉量（dx, dy, dθ），供 ROI 跟隨使用。",
    params: {
      ref_x: {
        label: "參考 X",
        help: "教導時最佳匹配的中心 X（前端可一鍵帶入目前值）。",
      },
      ref_y: {
        label: "參考 Y",
      },
      ref_angle: {
        label: "參考角度",
      },
      use_angle: {
        label: "套用旋轉",
        help: "關閉則 dθ 固定為 0，只做平移補正。",
      },
    },
    ports: {
      image: "影像",
      matches: "匹配",
      a: "目前 X",
      b: "目前 Y",
      c: "目前角度",
      transform: "變換",
    },
  },
  shape_match: {
    label: "形狀比對",
    description: "以邊緣的方向而不是灰階值找教導過的形狀，所以光線變了、物件被遮住一部分、背景雜亂或零件轉到任何角度都照樣找得到。在資產頁從一張良品建模；輸出的比對結果接定位補正，用法與範本比對相同。",
    params: {
      model_source: { label: "模型來源", help: "使用已上傳的形狀模型資產，或在記憶體合成內建基準 Mark 模型。", options: { asset: "資產", builtin: "內建 Mark" } },
      model: { label: "形狀範本", help: "用 POST /vision/assets/shape-model 或 manage.py shape_model 從影像資產建立（.npz 檔案資產）。" },
      builtin_shape: { label: "內建圖形", help: "十字、空心方框或實心圓 Mark。", options: { cross: "十字", square_outline: "空心方框", disc: "實心圓" } },
      builtin_size: { label: "Mark 尺寸", help: "外徑或邊長，單位為像素。" },
      builtin_line_width: { label: "線寬", help: "十字與空心方框的筆畫寬度。" },
      roi: { label: "搜尋區域", help: "留空則整張影像。" },
      min_score: { label: "最低分數", help: "1 = 每個模型邊緣都吻合。遮擋會等比例降分：遮住四分之一約 0.75。" },
      max_matches: { label: "最多比對數" },
      angle_start: { label: "起始角" },
      angle_extent: { label: "角度範圍", help: "從起始角起搜尋這麼多度。範圍越窄越快。" },
      scale_min: { label: "最小尺度", group: "尺度" },
      scale_max: { label: "最大尺度", help: "等於最小尺度 = 不搜尺度。", group: "尺度" },
      max_overlap: { label: "最大重疊", help: "兩個結果的外框重疊超過此比例視為同一物件，弱的剔除。", group: "進階" },
      greediness: { label: "積極度", help: "多早放棄沒希望的候選。1 最快但可能漏掉被遮住的件；0 為窮舉。", group: "進階" },
      subpixel: { label: "次像素精修", group: "進階" },
      polarity: { label: "極性", options: { use_polarity: "使用極性（暗底亮件就是暗底亮件）", ignore_polarity: "忽略極性（黑白反轉的件也找）" }, group: "進階" },
      min_contrast: { label: "最小對比", help: "搜尋影像中弱於此值的邊緣不計；0 = 用模型自己的值。", group: "進階" },
    },
    ports: { image: "影像", roi: "搜尋區域（動態）", found: "找到", not_found: "未找到", matches: "比對結果", count: "數量", best_x: "最佳 X", best_y: "最佳 Y", best_angle: "最佳角度", best_scale: "最佳尺度", best_score: "最佳分數" },
  },
  track_objects: {
    label: "目標追蹤",
    description: "在連續執行中用預測位置與最近鄰配對，替匹配框維持穩定 ID。試執行與沙盒只寫變數覆蓋層，不會推進正式追蹤狀態。",
    params: {
      state_name: { label: "狀態變數", help: "保存追蹤狀態的流程變數；多個追蹤器請用不同名稱。" },
      max_distance: { label: "最大距離", help: "偵測中心離預測位置超過此距離時，建立新目標。" },
      max_missing: { label: "最大丟失次數", help: "連續丟失超過此值才淘汰目標。" },
      reset: { label: "重設", help: "本次影格處理前清除已保存的追蹤狀態。" },
      line_mode: { label: "計數線", options: { none: "無", points: "兩點" }, group: "計數" },
      count_line: { label: "線段點", help: "兩點格式：[[x1,y1],[x2,y2]]。由負側跨到正側算 count_in。", group: "計數" },
    },
    ports: {
      matches: "匹配", boxes: "方框", count_line: "計數線", reset: "重設", image: "影像（顯示用）",
      ok: "追蹤中", not_found: "無目標", tracks: "追蹤目標", count: "數量", new_count: "新增數", lost_count: "淘汰數",
      count_in: "進入計數", count_out: "離開計數",
    },
  },
  template_match: {
    label: "範本比對",
    description: "以正規化相關（NCC）在影像或搜尋範圍內找範本；支援旋轉搜尋、金字塔加速與次像素精修。角度以畫面順時針為正（與 ROI／找直線相同）。",
    params: {
      templates: { label: "更多模板", help: "好幾種形狀都算找到：同一個工件的兩種姿態、同一條線上的三種蓋子。每個結果都會說是哪一種。" },
      sort_by: {
        label: "結果排序",
        help: "取放最常用閱讀順序；有無檢測用分數。",
        options: { score: "分數，最高在前", x: "由左到右", y: "由上到下", xy: "閱讀順序（先分列再由左到右）", angle: "角度" },
      },
      scale_x: { label: "橫向縮放", help: "比對前先把模板拉伸，對付成像比教導時大或扁的工件。" },
      scale_y: { label: "縱向縮放" },
      allow_clipped: { label: "允許工件在邊上", help: "把搜尋範圍的邊界往外複製，跨在邊上的工件也找得到。被切掉的工件分數會低，門檻要放寬一點。" },
      timeout_ms: { label: "逾時放棄", help: "時間到就回目前找到最好的，不讓產線等。0＝不限。" },
      template: {
        label: "範本影像",
        help: "上傳的範本影像（灰階比對）。",
      },
      roi: {
        label: "搜尋範圍",
        help: "留空則搜尋整張影像。",
      },
      threshold: {
        label: "分數門檻",
        help: "NCC 分數 0~1，低於此值不算匹配。",
      },
      max_matches: {
        label: "最多匹配數",
      },
      angle_range: {
        label: "旋轉範圍 ±",
        help: "0 表示不做旋轉搜尋。",
        group: "旋轉",
      },
      angle_step: {
        label: "角度步進",
        group: "旋轉",
      },
      pyramid: {
        label: "金字塔加速",
        help: "先在 1/4 縮圖粗找，再在候選附近細找。範本很小時自動關閉。",
        group: "進階",
      },
      subpixel: {
        label: "次像素精修",
        help: "位置以相關圖 3×3 拋物線內插；有旋轉搜尋時再以相鄰角度的分數內插角度（精度優於角度步進）。",
        group: "進階",
      },
    },
    ports: {
      template_image: "範本圖",
      image: "影像",
      roi: "搜尋範圍（動態）",
      found: "找到",
      not_found: "沒找到",
      matches: "匹配",
      count: "數量",
      best_x: "最佳 X",
      best_y: "最佳 Y",
      best_score: "最佳分數",
      best_angle: "最佳角度",
      best_label: "最佳模板",
      counts: "各模板數量",
    },
  },
  text_presence: {
    label: "有無印字",
    description: "區域內筆劃像素比例（自適應二值化後的前景比例）是否達門檻，用來判斷有無印字／標籤。",
    params: {
      roi: {
        label: "區域",
      },
      polarity: {
        label: "字色",
        options: {
          dark: "深色字",
          bright: "淺色字",
        },
      },
      block: {
        label: "自適應區塊（奇數）",
        group: "進階",
      },
      c: {
        label: "自適應常數 C",
        group: "進階",
      },
      min_ratio: {
        label: "最小筆劃比例",
      },
      max_ratio: {
        label: "最大筆劃比例",
        help: "超過視為污損或整片色塊。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      present: "有",
      absent: "無",
      ratio: "筆劃比例",
      is_present: "有印字",
      mask: "筆劃遮罩",
    },
  },
  threshold: {
    label: "門檻",
    description: "固定門檻、Otsu 自動、或自適應（區域）二值化；輸出 0/255 遮罩。",
    params: {
      method: {
        label: "方法",
        options: {
          fixed: "固定門檻",
          otsu: "Otsu 自動",
          triangle: "Triangle 自動",
          adaptive_mean: "自適應（均值）",
          adaptive_gaussian: "自適應（高斯）",
          sauvola: "Sauvola 區域自適應",
          niblack: "Niblack 區域自適應",
          range: "灰階範圍",
        },
      },
      threshold: {
        label: "門檻",
      },
      low: {
        label: "下限",
      },
      high: {
        label: "上限",
      },
      block: {
        label: "區塊大小（奇數）",
      },
      c: {
        label: "常數 C",
      },
      window: { label: "視窗大小（奇數）" },
      k: { label: "k 值" },
      compare: {
        label: "比較方式",
        options: { ge: "像素 >= 門檻", le: "像素 <= 門檻", eq: "像素 == 門檻", ne: "像素 != 門檻" },
      },
      offset: { label: "門檻偏移" },
      roi: { label: "區域" },
      outside_roi: { label: "ROI 外側", options: { black: "塗黑", keep: "保留原灰階" } },
      invert: {
        label: "反相（暗物件為前景）",
      },
    },
    ports: {
      image: "遮罩",
      threshold_used: "實際門檻",
    },
  },
  to_world: {
    label: "真實世界座標",
    description: "把像素位置換成機器實際使用的座標：檯面上的毫米，或機械手要的數字。接入一個位置就讀出 X 與 Y；長度與角度用同一份標定換算。",
    params: {
      mode: { label: "換算方向", help: "to_pixel 將 x/y/points 視為世界或座標系內的座標，輸出 x/y/points_world 為影像像素；長度與角度同方向換算。", options: { to_world: "轉為世界座標", to_pixel: "轉為像素座標" } },
      calibration: { label: "標定資產", group: "進階", help: "選填；未選標定時輸出座標系內的像素值，未接 frame 時保留原座標。" },
      decimals: { label: "小數位數", group: "進階" },
    },
    ports: { frame: "座標系", points: "點", x: "X（像素）", y: "Y（像素）", value: "像素長度", angle: "角度（影像）", points_world: "點（真實世界）", length: "長度", scale: "比例" },
  },
  tolerance_judge: {
    label: "公差判定",
    description: "量測值是否在「標稱 ＋上偏差／＋下偏差」內；判定連同標稱值、上下限、圖面出處一起寫進 run.outputs.tolerances，供 Cpk 與追溯。",
    params: {
      nominal: {
        label: "標稱",
      },
      upper_tol: {
        label: "上偏差",
        help: "帶號；上限 = 標稱 + 上偏差。",
      },
      lower_tol: {
        label: "下偏差",
        help: "帶號（通常為負）；下限 = 標稱 + 下偏差。",
      },
      unit: {
        label: "單位",
      },
      spec_source: {
        label: "圖面出處",
        help: "例如「圖號 A-102 尺寸 ⌀12」。",
      },
      name: {
        label: "尺寸名稱",
        help: "寫進 outputs.tolerances 的 name；留空用節點標籤。",
      },
    },
    ports: {
      value: "量測值",
      pass: "合格",
      fail: "超差",
      verdict: "判定",
      deviation: "偏差（值−標稱）",
      in_spec: "合格",
      nominal: "標稱",
      upper: "上限",
      lower: "下限",
      spec_source: "圖面出處",
    },
  },
  path_extract: {
    label: "路徑提取",
    description: "沿折線或多邊形路徑等距取樣，或在每個取樣點沿法線放卡尺找邊，輸出點集、切線角、偏移與打空索引。",
    params: {
      roi: { label: "路徑", help: "多邊形預設封閉、線段預設開放；上游 points 會優先。" },
      mode: { label: "模式", options: { equal_interval: "等距取樣", edge_search: "找邊" } },
      closed: { label: "封閉路徑", help: "不設定時依路徑型態決定：polygon 封閉，line 與 points 開放。" },
      spacing: { label: "取樣間距", help: "沿路徑每隔幾個像素取一點；點數大於 0 時優先用點數。" },
      count: { label: "取樣點數", help: "大於 0 時覆寫取樣間距。" },
      search: { label: "搜尋半徑", help: "沿法線方向往兩側搜尋的半徑。" },
      caliper_width: { label: "卡尺寬度", help: "沿路徑切線方向平均，用來降噪。" },
      edge_threshold: { label: "邊緣閾值" },
      polarity: { label: "邊緣極性", options: { any: "任意", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      edge_select: { label: "選哪個邊", options: { strongest: "最強", first: "第一個", last: "最後一個" } },
      edge_mode: { label: "找邊模式", options: { single: "單邊", pair: "邊緣對" } },
      pair_polarity: { label: "邊緣對極性", options: { any: "任意", bright: "亮帶", dark: "暗帶" } },
      pair_mode: { label: "選哪一對", options: { first_last: "最外側", widest: "最寬", narrowest: "最窄", strongest: "最強", expected: "最接近預期寬度" } },
      expected_width: { label: "預期寬度" },
      smoothing: { label: "剖面平滑" },
    },
    ports: {
      image: "影像", roi: "路徑（動態）", points: "點集", ok: "成功", not_found: "找不到",
      angles: "切線角", offsets: "偏移", widths: "寬度", missing: "打空索引", count: "數量", length: "路徑長度",
    },
  },
  edge_trend: {
    label: "邊緣趨勢",
    description: "沿一條直線或圓形邊緣放多把卡尺，輸出每把卡尺相對基線的偏移序列、缺失位置與統計。",
    params: {
      roi: { label: "參考", help: "沒有接上游線或圓時使用；上游幾何優先於 ROI。" },
      calipers: { label: "卡尺數" },
      search: { label: "搜尋範圍", help: "每把卡尺沿法線方向搜尋的距離。" },
      caliper_width: { label: "卡尺寬度", help: "沿著邊平均，用來降噪。" },
      edge_threshold: { label: "邊緣門檻" },
      mode: { label: "模式", options: { single: "單一邊緣", pair: "邊緣對" } },
      polarity: { label: "邊緣極性", options: { any: "任一", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      pair_polarity: { label: "邊緣對極性", options: { any: "任一", bright: "亮帶", dark: "暗帶" } },
      baseline: {
        label: "基線",
        help: "offsets 是命中 offset 減去基線，單位 px。",
        options: { fit: "擬合命中邊", median: "滑動中位數", reference: "參考幾何" },
      },
      max_deviation: { label: "最大偏移", help: "最大絕對偏移超過此值時走 NG 分支；0 表示不限制。" },
      window: { label: "中位數視窗" },
      smoothing: { label: "剖面平滑" },
      edge_select: { label: "選哪個邊", options: { strongest: "最強", first: "第一個", last: "最後一個" } },
    },
    ports: {
      image: "影像", roi: "參考（動態）", line: "參考線", circle: "參考圓",
      ok: "趨勢合格", ng: "趨勢超標",
      offsets: "偏移序列", widths: "寬度序列", positions: "位置", points: "邊緣點",
      missing: "打空索引", mean: "平均", std: "標準差", min: "最小", max: "最大", range: "範圍",
    },
  },
  wall_thickness: {
    label: "壁厚",
    description: "沿矩形／線段區域放多條卡尺，每條找「外緣→內緣」成對邊緣，量壁厚（像素）並給最小／最大／平均。",
    params: {
      roi: {
        label: "區域",
        help: "長邊沿著壁的走向；卡尺沿短邊由「外」向「內」掃描（矩形上→下／左→右）。線段 ROI 以線為長邊。",
      },
      polarity: {
        label: "外緣極性",
        help: "沿掃描方向遇到外緣時的灰階變化；內緣自動取相反極性。",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "邊緣門檻",
      },
      num_calipers: {
        label: "卡尺數",
      },
      max_thickness: {
        label: "最大壁厚",
        help: "0 表示不限；配對時內緣距外緣不得超過此值。",
      },
      band: {
        label: "線段掃描寬",
        help: "ROI 為線段時，取線兩側共此寬度做平均。",
        group: "進階",
      },
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      thickness: "壁厚（平均）",
      min: "最小",
      max: "最大",
      mean: "平均",
      std: "標準差",
      count: "有效卡尺數",
      profile: "各卡尺壁厚",
      pairs: "邊緣對",
    },
  },
  stitch_images: {
    label: "影像拼接",
    description: "合成 2 到 4 台相機影像。固定排列且無透視差用硬拼；每張有世界標定，或第 2 到第 4 張有映到第 1 張的相機映射時，用投影拼。",
    params: {
      images: { label: "固定影像", help: "備援來源：沒有接 image_1 到 image_4 時，依清單順序拼接這些固定影像。正式流程建議接 image_1 到 image_4。" },
      mode: { label: "模式", options: { grid: "硬拼", homography: "投影拼" } },
      rows: { label: "列數" },
      cols: { label: "欄數" },
      order: { label: "順序", options: { row_major: "列優先", column_major: "行優先" } },
      trim: { label: "裁掉邊界" },
      overlap_x: { label: "水平重疊", group: "進階" },
      overlap_y: { label: "垂直重疊", group: "進階" },
      blend: { label: "混合", options: { mean: "平均", min: "最小", max: "最大", uncover: "後蓋前" } },
      calibration_1: { label: "標定 1" },
      calibration_2: { label: "標定 2" },
      calibration_3: { label: "標定 3" },
      calibration_4: { label: "標定 4" },
      scale: { label: "平面比例", help: "輸出每像素代表多少世界單位。0 表示使用第一份世界標定比例；相機映射到第 1 張時使用 1 px/px。" },
    },
    ports: {
      image_1: "影像 1",
      image_2: "影像 2",
      image_3: "影像 3",
      image_4: "影像 4",
      image: "影像",
      count: "影像數",
      width: "寬度",
      height: "高度",
      offsets: "硬拼位移",
      origin: "世界原點",
      scale: "比例",
    },
  },
  undistort: {
    label: "鏡頭校正",
    description: "用標定資產把鏡頭彎掉的部分拉直。廣角或近距離時邊角的直線會往外拱；在校正後的影像上量測，數值就不會隨視野位置漂移。",
    params: {
      mode: { label: "??", options: { calibration: "???", manual: "??" } },
      calibration: { label: "標定資產", help: "在標定頁用幾張標定板照片做出來。同一份標定也驅動「真實世界座標」。" },
      alpha: { label: "保留畫面", help: "0 = 裁掉所有黑邊（放大到全部都是有效像素）；1 = 保留整個畫面（角落補黑）；中間值保留該比例。" },
      keep_edges: { label: "保留整個畫面", help: "舊流程用：等於 alpha 1。alpha 大於 0 時忽略。", group: "進階" },
      k1: { label: "K1" },
      k2: { label: "K2" },
      cx: { label: "?? X" },
      cy: { label: "?? Y" },
      scale: { label: "??" },
    },
    ports: { image: "影像", mm_per_pixel: "每像素 mm" },
  },
  warp_perspective: {
    label: "透視校正",
    description: "把畫面上的四邊形區域攤平成矩形：斜拍的板面／標籤校正後再量測。",
    params: {
      roi: {
        label: "來源四邊形",
        help: "畫 4 個點（多於 4 點取前 4 點）。",
      },
      width: {
        label: "輸出寬",
        help: "0 = 依邊長自動。",
      },
      height: {
        label: "輸出高",
      },
    },
    ports: {
      image: "影像",
    },
  },
  write_modbus: {
    label: "寫入 Modbus",
    description: "依對映表把判定、具名輸出或輸入埠的值寫到 Modbus TCP／上位機連線。寫入失敗預設只記警告不讓 run 失敗。",
    params: {
      connection: {
        label: "連線",
        help: "填通訊連線的名稱（設定頁「連線」建立；也可填 id）。",
      },
      mapping: {
        label: "對映表",
        help: "陣列，每項 {\"src\": 來源, \"address\": 位址, \"dtype\"?: bool|int|float, \"scale\"?: 倍率, \"offset\"?: 加值, \"value\"?: 常數}。src：judge（OK→1 / NG→0）、具名輸出名稱、或本節點輸入埠的 v0、v1…。位址：modbus 用 coil:10 / holding:100 / holding:100:float32 / holding:100:int32；tcp_client 用範本欄位名；dio_sim 用通道名。",
      },
      on_error: {
        label: "寫入失敗時",
        options: {
          warn: "降級：記警告，run 照常",
          fail: "讓 run 失敗",
        },
      },
      timeout_s: {
        label: "逾時（秒）",
        help: "0 = 用連線設定的逾時。",
        group: "進階",
      },
    },
    ports: {
      values: "值",
      written: "寫入筆數",
      ok: "成功",
    },
  },
  ai_classify: {
    label: "分類（AI）",
    description: "以分類網路（官方底模或教導頁訓練的模型）判斷區域屬於哪一類；最高分類別分數達門檻（且在合格類別內）走 pass。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_size: {
        label: "底模大小",
        help: "只在沒選模型資產時使用；越大越準但越慢。底模第一次使用時自動下載。",
        options: {
          n: "Nano（最快，預設）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最準，最慢）",
        },
      },
      model_name: {
        label: "模型檔（進階）",
        help: "本機 .pt 路徑，會取代底模；平常留空。",
        group: "進階",
      },
      imgsz: {
        label: "推論尺寸",
        help: "與訓練時一致最準。",
        options: {
          "224": "224（建議）",
        },
      },
      device: {
        label: "裝置",
        group: "進階",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、記憶體更省。",
        group: "進階",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      threshold: {
        label: "分數門檻",
      },
      pass_labels: {
        label: "合格類別",
        help: "逗號分隔；不為空時，最高分類別需在此清單內才 pass。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      pass: "合格",
      fail: "不良",
      label: "類別",
      score: "分數",
      index: "索引",
    },
  },
  ai_detect: {
    label: "物件偵測（AI）",
    description: "以神經網路模型（官方底模或教導頁訓練的 .pt）找物件並回框、類別與分數；GPU 自動使用。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_size: {
        label: "底模大小",
        help: "只在沒選模型資產時使用；越大越準但越慢。底模第一次使用時自動下載。",
        options: {
          n: "Nano（最快，預設）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最準，最慢）",
        },
      },
      model_name: {
        label: "模型檔（進階）",
        help: "本機 .pt 路徑，會取代底模；平常留空。",
        group: "進階",
      },
      imgsz: {
        label: "推論尺寸",
        help: "與訓練時一致最準。",
        options: {
          "640": "640（建議）",
        },
      },
      device: {
        label: "裝置",
        group: "進階",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、記憶體更省。",
        group: "進階",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心門檻",
      },
      iou: {
        label: "NMS IoU",
        group: "進階",
      },
      max_count: {
        label: "最多輸出",
        group: "進階",
      },
      filter_labels: {
        label: "只保留類別",
        help: "逗號分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多數量",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      detections: "偵測結果",
      count: "數量",
      matches: "匹配（含 cx, cy）",
      labels: "類別列表",
    },
  },
  ai_obb: {
    label: "旋轉框（AI）",
    description: "以旋轉框網路找物件並回旋轉矩形（中心、寬高、角度）與四角座標；適合傾斜擺放的工件。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_size: {
        label: "底模大小",
        help: "只在沒選模型資產時使用；越大越準但越慢。底模第一次使用時自動下載。",
        options: {
          n: "Nano（最快，預設）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最準，最慢）",
        },
      },
      model_name: {
        label: "模型檔（進階）",
        help: "本機 .pt 路徑，會取代底模；平常留空。",
        group: "進階",
      },
      imgsz: {
        label: "推論尺寸",
        help: "與訓練時一致最準。",
        options: {
          "640": "640（建議）",
        },
      },
      device: {
        label: "裝置",
        group: "進階",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、記憶體更省。",
        group: "進階",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心門檻",
      },
      iou: {
        label: "NMS IoU",
        group: "進階",
      },
      max_count: {
        label: "最多輸出",
        group: "進階",
      },
      filter_labels: {
        label: "只保留類別",
        help: "逗號分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多數量",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      count: "數量",
      matches: "旋轉框（cx, cy, w, h, angle）",
      contours: "四角輪廓",
      labels: "類別列表",
    },
  },
  ai_pose: {
    label: "姿態關鍵點（AI）",
    description: "以姿態網路找物件並回每個物件的關鍵點座標與信心（COCO 人體 17 點或自訂關鍵點）；可做位置／姿勢檢查。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_size: {
        label: "底模大小",
        help: "只在沒選模型資產時使用；越大越準但越慢。底模第一次使用時自動下載。",
        options: {
          n: "Nano（最快，預設）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最準，最慢）",
        },
      },
      model_name: {
        label: "模型檔（進階）",
        help: "本機 .pt 路徑，會取代底模；平常留空。",
        group: "進階",
      },
      imgsz: {
        label: "推論尺寸",
        help: "與訓練時一致最準。",
        options: {
          "640": "640（建議）",
        },
      },
      device: {
        label: "裝置",
        group: "進階",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、記憶體更省。",
        group: "進階",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心門檻",
      },
      iou: {
        label: "NMS IoU",
        group: "進階",
      },
      max_count: {
        label: "最多輸出",
        group: "進階",
      },
      filter_labels: {
        label: "只保留類別",
        help: "逗號分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多數量",
        help: "0 表示不限。",
        group: "判定",
      },
      kpt_conf: {
        label: "關鍵點信心門檻",
        help: "低於門檻的關鍵點不畫、座標仍輸出（conf 附在每點）。",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      count: "數量",
      matches: "物件框",
      keypoints: "關鍵點",
      labels: "類別列表",
    },
  },
  ai_segment: {
    label: "實例分割（AI）",
    description: "以實例分割網路（官方底模或教導頁訓練的模型）找出每個物件的輪廓、類別與面積；輸出聯合遮罩與輪廓給後續量測。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_size: {
        label: "底模大小",
        help: "只在沒選模型資產時使用；越大越準但越慢。底模第一次使用時自動下載。",
        options: {
          n: "Nano（最快，預設）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最準，最慢）",
        },
      },
      model_name: {
        label: "模型檔（進階）",
        help: "本機 .pt 路徑，會取代底模；平常留空。",
        group: "進階",
      },
      imgsz: {
        label: "推論尺寸",
        help: "與訓練時一致最準。",
        options: {
          "640": "640（建議）",
        },
      },
      device: {
        label: "裝置",
        group: "進階",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、記憶體更省。",
        group: "進階",
      },
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心門檻",
      },
      iou: {
        label: "NMS IoU",
        group: "進階",
      },
      max_count: {
        label: "最多輸出",
        group: "進階",
      },
      filter_labels: {
        label: "只保留類別",
        help: "逗號分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少數量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多數量",
        help: "0 表示不限。",
        group: "判定",
      },
      min_area: {
        label: "最小面積",
        help: "小於此面積的實例略過。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      count: "數量",
      matches: "實例",
      mask: "聯合遮罩",
      contours: "輪廓",
      labels: "類別列表",
    },
  },
}
