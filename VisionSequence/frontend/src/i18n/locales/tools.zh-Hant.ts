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
  apply_mask: {
    label: "套用遮罩",
    description: "只保留遮罩為 255 的像素（其餘設為指定灰階）。",
    params: {
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
          invert: "反相 A",
        },
      },
    },
    ports: {
      image: "影像",
    },
  },
  barcode: {
    label: "條碼 / QR",
    description: "解碼 QR code 與一維條碼（EAN/UPC/Code128 等）。",
    params: {
      roi: {
        label: "區域",
        help: "留空則整張影像。",
      },
      types: {
        label: "類型",
        options: {
          all: "QR + 一維條碼",
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
          none: "輸入已是遮罩（非 0 即前景）",
        },
      },
      threshold: {
        label: "門檻",
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
          circularity: "圓形度（高→低）",
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
      smoothing: {
        label: "剖面平滑",
        group: "進階",
      },
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      width: "寬",
      edge1_x: "邊緣1 X",
      edge1_y: "邊緣1 Y",
      edge2_x: "邊緣2 X",
      edge2_y: "邊緣2 Y",
      edges: "所有邊緣位置",
      profile: "剖面",
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
        },
      },
    },
    ports: {
      image: "影像",
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
  distance: {
    label: "距離",
    description: "兩點距離（像素）。點可為 {x,y} / [x,y]，或分別接 ax, ay, bx, by 四個數值。",
    params: {
      mode: {
        label: "量測",
        options: {
          euclid: "直線距離",
          dx: "X 方向距離",
          dy: "Y 方向距離",
        },
      },
    },
    ports: {
      image: "影像",
      a: "點 A",
      b: "點 B",
      distance: "距離",
    },
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
        help: "以 0~1 為單位；YOLO 通常填 0。",
        group: "前處理",
      },
      std: {
        help: "YOLO 通常填 1。",
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
    description: "以 ONNX 偵測模型（YOLOv5/v8 風格輸出）找物件；含 letterbox 前處理與 NMS。",
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
        help: "以 0~1 為單位；YOLO 通常填 0。",
        group: "前處理",
      },
      std: {
        help: "YOLO 通常填 1。",
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
    description: "以 YOLO-seg 風格的 ONNX 模型找出每個物件的輪廓與類別（含 letterbox 前處理、NMS 與 mask 合成）。可在平台的深度學習頁教導。",
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
        help: "以 0~1 為單位；YOLO 通常填 0。",
        group: "前處理",
      },
      std: {
        help: "YOLO 通常填 1。",
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
        help: "以 0~1 為單位；YOLO 通常填 0。",
        group: "前處理",
      },
      std: {
        help: "YOLO 通常填 1。",
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
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      cx: "中心 X",
      cy: "中心 Y",
      r: "半徑",
      points: "邊緣點",
      score: "分數",
    },
  },
  find_line: {
    label: "找直線",
    description: "在矩形區域內放多條垂直於長邊的卡尺掃描線找邊緣點，再擬合直線（可 RANSAC）。",
    params: {
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
    },
    ports: {
      image: "影像",
      roi: "區域（動態）",
      found: "找到",
      not_found: "沒找到",
      angle: "夾角",
      line: "線",
      points: "邊緣點",
    },
  },
  fit_arc: {
    label: "圓弧擬合",
    description: "在區域內找邊緣點並以最小平方（可 RANSAC）擬合圓弧：R 角、杯口圓角的半徑與圓心。",
    params: {
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
    ports: {
      image: "影像",
      roi: "區域（動態）",
      radius: "半徑",
      cx: "中心 X",
      cy: "中心 Y",
      residual_rms: "殘差 RMS",
      points: "邊緣點",
      start_angle: "起角",
      end_angle: "終角",
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
  geometry: {
    label: "幾何計算",
    description: "解析幾何：兩線交點、點到線垂距、兩點中點、點在線上的投影。線＝{x1,y1,x2,y2}、點＝[x,y] 或 {x,y}（接找線／找圓等工具的輸出）。",
    params: {
      mode: {
        label: "計算",
        options: {
          intersect: "兩線交點",
          point_line: "點到線垂距",
          midpoint: "兩點中點",
          project: "點投影到線",
        },
      },
    },
    ports: {
      a: "A（線／點）",
      b: "B（線／點）",
      distance: "距離",
    },
  },
  grayscale: {
    label: "灰階",
    description: "彩色轉灰階；已是灰階則直通。",
    ports: {
      image: "影像",
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
    description: "cv2.HoughCircles（梯度法）在區域內找多個圓。",
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
    },
    ports: {
      image: "影像",
      width: "寬",
      height: "高",
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
      split_by_judge: {
        label: "依判定分資料夾",
      },
      only_ng: {
        label: "只存 NG",
      },
      prefix: {
        label: "檔名前綴",
      },
    },
    ports: {
      image: "影像",
      path: "路徑",
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
  template_match: {
    label: "範本比對",
    description: "以正規化相關（NCC）在影像或搜尋範圍內找範本；支援旋轉搜尋、金字塔加速與次像素精修。角度以畫面順時針為正（與 ROI／找直線相同）。",
    params: {
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
      invert: {
        label: "反相（暗物件為前景）",
      },
    },
    ports: {
      image: "遮罩",
      threshold_used: "實際門檻",
    },
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
  yolo_classify: {
    label: "YOLO 分類",
    description: "以 ultralytics YOLO-cls 模型判斷區域屬於哪一類；最高分類別分數達門檻（且在合格類別內）走 pass。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_name: {
        label: "底模名稱",
        help: "官方名稱（第一次使用自動下載）或本機 .pt 路徑；只在沒選模型資產時使用。",
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
  yolo_detect: {
    label: "YOLO 物件偵測",
    description: "以 ultralytics YOLO 模型（官方底模或教導頁訓練的 .pt）找物件並回框、類別與分數；GPU 自動使用。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_name: {
        label: "底模名稱",
        help: "官方名稱（第一次使用自動下載）或本機 .pt 路徑；只在沒選模型資產時使用。",
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
  yolo_obb: {
    label: "YOLO 旋轉框（OBB）",
    description: "以 ultralytics YOLO-obb 模型找物件並回旋轉矩形（中心、寬高、角度）與四角座標；適合傾斜擺放的工件。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_name: {
        label: "底模名稱",
        help: "官方名稱（第一次使用自動下載）或本機 .pt 路徑；只在沒選模型資產時使用。",
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
  yolo_pose: {
    label: "YOLO 姿態（關鍵點）",
    description: "以 ultralytics YOLO-pose 模型找物件並回每個物件的關鍵點座標與信心（COCO 人體 17 點或自訂關鍵點）；可做位置／姿勢檢查。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_name: {
        label: "底模名稱",
        help: "官方名稱（第一次使用自動下載）或本機 .pt 路徑；只在沒選模型資產時使用。",
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
  yolo_segment: {
    label: "YOLO 實例分割",
    description: "以 ultralytics YOLO-seg 模型找出每個物件的輪廓、類別與面積；輸出聯合遮罩與輪廓給後續量測。",
    params: {
      model: {
        label: "模型資產",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上傳的 .pt；留空則用下方底模名稱。",
      },
      model_name: {
        label: "底模名稱",
        help: "官方名稱（第一次使用自動下載）或本機 .pt 路徑；只在沒選模型資產時使用。",
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
