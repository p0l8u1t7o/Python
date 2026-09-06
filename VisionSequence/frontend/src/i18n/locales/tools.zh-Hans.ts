/**
 * Tool catalogue in Simplified Chinese.
 *
 * The backend catalogue is English — that is the source of truth (`apps/vision/tools/`). This file
 * translates it for the Chinese interface: `lib/toolLocale.ts` overlays it, and a tool with no entry
 * (a folder plugin, say) keeps whatever wording the backend sent.
 *
 * Generated from the catalogue; keep it in step when tool wording changes.
 */
export default {
  angle: {
    label: "夹角",
    description: "兩條直线的夹角（度）。直线可为 {x1,y1,x2,y2} 或分别接八个数值。",
    params: {
      range: {
        label: "角度范围",
        options: {
          "0_90": "0 ~ 90（不分方向）",
          signed: "-180 ~ 180（帶号）",
        },
      },
    },
    ports: {
      image: "影像",
      a: "直线 A",
      b: "直线 B",
      angle_deg: "夹角",
      angle_a: "A 角度",
      angle_b: "B 角度",
    },
  },
  apply_mask: {
    label: "套用遮罩",
    description: "只保留遮罩为 255 的像素（其余设为指定灰阶）。",
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
    description: "兩張影像相加／相減／差異／AND／OR，或单張的反相、亮度对比调整。",
    params: {
      op: {
        label: "運算",
        options: {
          absdiff: "絕对差 |A-B|",
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
    description: "解碼 QR code 与一維條碼（EAN/UPC/Code128 等）。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      types: {
        label: "类型",
        options: {
          all: "QR + 一維條碼",
          qr: "只 QR",
          "1d": "只一維條碼",
        },
      },
      expected: {
        label: "期望内容",
        help: "不为空时，内容需完全相同才走「符合」分支。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到／符合",
      not_found: "沒找到／不符",
      texts: "内容列表",
      count: "数量",
      first: "第一个内容",
      codes: "详细",
    },
  },
  blob: {
    label: "Blob 分析",
    description: "连通区域／轮廓分析：面积、中心、外接矩形、圆形度；可依面积与圆形度篩选并排序。灰阶输入會自動二值化。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      threshold_method: {
        label: "门槛",
        options: {
          otsu: "Otsu 自動",
          fixed: "固定门槛",
          none: "输入已是遮罩（非 0 即前景）",
        },
      },
      threshold: {
        label: "门槛",
      },
      polarity: {
        label: "前景",
        options: {
          bright: "亮物件",
          dark: "暗物件",
        },
      },
      min_area: {
        label: "最小面积",
      },
      max_area: {
        label: "最大面积",
        help: "0 表示不限。",
      },
      min_circularity: {
        label: "最小圆形度",
        help: "4πA/P²，正圆为 1。",
      },
      max_count: {
        label: "最多输出",
      },
      sort_by: {
        label: "排序",
        options: {
          area: "面积（大→小）",
          x: "X（左→右）",
          y: "Y（上→下）",
          circularity: "圆形度（高→低）",
        },
      },
      separate: {
        label: "分離黏连粒子",
        help: "距離转换＋分水嶺把黏在一起的粒子切开再量测；種子視窗依「最小面积」推算的粒子半径。",
        group: "进阶",
      },
      fill_holes: {
        label: "填滿孔洞",
        group: "进阶",
      },
      external_only: {
        label: "只取最外层轮廓",
        help: "关闭时面积會扣掉孔洞。",
        group: "进阶",
      },
      min_count: {
        label: "合格最少数量",
        help: "找到的 blob 少于此值判 NG。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      blobs: "Blob 列表",
      count: "数量",
      largest_area: "最大面积",
      total_area: "总面积",
      contours: "轮廓",
      centers: "中心点",
      mask: "遮罩",
      first_cx: "第一个中心 X",
      first_cy: "第一个中心 Y",
    },
  },
  blur: {
    label: "平滑 / 去雜訊",
    description: "高斯、中值、双边或均值滤波。",
    params: {
      method: {
        label: "方法",
        options: {
          gaussian: "高斯",
          median: "中值",
          bilateral: "双边（保边）",
          box: "均值",
        },
      },
      ksize: {
        label: "核大小（奇数）",
      },
      sigma: {
        label: "Sigma（高斯／双边）",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
    },
  },
  bool_logic: {
    label: "布林组合",
    description: "把多个布林输入以 AND / OR / NOT 组合，走 true / false 分支。",
    params: {
      mode: {
        label: "運算",
        options: {
          and: "AND（全部为真）",
          or: "OR（任一为真）",
        },
      },
    },
    ports: {
      values: "布林",
      result: "结果",
    },
  },
  calibration: {
    label: "像素校正",
    description: "把像素量测值换算成毫米：直接給每像素 mm，或用「已知距離」（像素数 ↔ 实际 mm）算比例。也可缩放点列表。",
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
        label: "实际距離",
      },
      power: {
        label: "次方",
        help: "面积量测請选 k²。",
        options: {
          "1": "长度（×k）",
          "2": "面积（×k²）",
        },
      },
    },
    ports: {
      value: "像素值",
      points: "点列表",
      mm: "毫米",
      scale: "比例",
      points_mm: "点列表（mm）",
    },
  },
  caliper: {
    label: "卡尺",
    description: "在矩形区域内沿长边投影灰阶剖面，找一对边缘并量测宽度（像素）。",
    params: {
      roi: {
        label: "区域",
        help: "沿长边方向掃描，短边方向取平均以抗雜訊。",
      },
      polarity: {
        label: "边缘极性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
      },
      edge_pair: {
        label: "取边缘对",
        options: {
          first_last: "第一个与最後一个",
          widest: "最宽的一对",
          narrowest: "最窄的一对（相鄰）",
          strongest: "最强的兩个",
        },
      },
      pair_polarity: {
        label: "边缘对极性",
        help: "限制成对边缘的极性順序：量亮條／暗條的宽度时不會配到旁边的雜訊边缘。",
        options: {
          any: "不限",
          bright: "亮條（暗→亮、亮→暗）",
          dark: "暗條（亮→暗、暗→亮）",
        },
      },
      expected_width: {
        label: "期望宽度",
        help: "大于 0 时改挑「宽度最接近此值」的边缘对（優先于取边缘对模式）。",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      width: "宽",
      edge1_x: "边缘1 X",
      edge1_y: "边缘1 Y",
      edge2_x: "边缘2 X",
      edge2_y: "边缘2 Y",
      edges: "所有边缘位置",
      profile: "剖面",
    },
  },
  chamfer_angle: {
    label: "倒角",
    description: "在旋转矩形区域内以卡尺找轮廓边缘点，RANSAC 拟合第一條直线後排除其内点再拟合第二條；输出兩线夹角与倒角段长度。",
    params: {
      roi: {
        label: "区域",
        help: "长边沿著轮廓走向、要同时包住主边与倒角段；卡尺沿短边掃描。",
      },
      polarity: {
        label: "边缘极性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
      },
      num_calipers: {
        label: "卡尺数",
      },
      direction: {
        label: "取哪个边缘",
        options: {
          first: "第一个",
          last: "最後一个",
          strongest: "最强",
        },
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "进阶",
      },
      min_points: {
        label: "第二段最少点数",
        group: "进阶",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      angle_deg: "夹角",
      length: "倒角长度",
      line1: "主边",
      line2: "倒角边",
      ix: "交点 X",
      iy: "交点 Y",
      points: "边缘点",
    },
  },
  gdt_measure: {
    label: "形位公差",
    description: "照图面语言测几何公差（ISO 1101）：直线度与平面度是包住所有点的最窄平行带，真圆度是两个同心圆之间最窄的环，平行度、垂直度与倾斜度是特征相对基准的偏差带。报告偏差、是否在公差内，以及背后的方法与极值点。",
    params: {
      mode: { label: "公差项目", options: { straightness: "直线度（点集）", flatness: "平面度（点集，2D 投影）", roundness: "真圆度（点集）", parallelism: "平行度（a 对基准 b）", perpendicularity: "垂直度（a 对基准 b）", angularity: "倾斜度（a 对基准 b 成参考角）" } },
      tolerance: { label: "公差带", help: "偏差必须落在的带宽（像素；有比例时为毫米）。" },
      unit: { label: "单位", options: { px: "像素", mm: "毫米（比例来自标定工具）" } },
      mm_per_px: { label: "每像素 mm", help: "留 0 并接入标定工具的比例输入。" },
      reference_angle: { label: "参考角", help: "特征 a 应与基准 b 成的角度（正值＝画面顺时针）。" },
    },
    ports: { points: "点", a: "特征 a", b: "基准 b", scale: "比例（每像素 mm）", image: "图像（显示用）", pass: "合格", fail: "不合格", deviation: "偏差", in_spec: "在公差内", unit: "单位", tolerance: "公差" },
  },
  photometric_stereo: {
    label: "光度立体",
    description: "把同一件在三或四个方向打光各拍的一张合成表面形状：浮凸与刻印字、凹坑、凸点与抛光面划痕在曲率图上一目了然，即使任何单张都看不出来。反射率输出是去掉打光后的材质。",
    params: {
      light_azimuth: { label: "光源方位角", help: "每盏灯一个角度（度），绕画面一圈（0＝自右、90＝自下，顺时针）。四灯各隔 90° 是常见灯架。" },
      light_elevation: { label: "光源仰角", help: "灯离表面的仰角；所有灯相同。" },
      output: { label: "图像输出", options: { curvature: "曲率（有号形状图：凸亮凹暗）", curvature_abs: "形状强度（无号曲率，供二值化）", normal_x: "法向 X（左右斜度）", normal_y: "法向 Y（上下斜度）", albedo: "反射率（去掉打光）", all: "全部（图像＝曲率）" } },
      normalize: { label: "归一化为 8 位", help: "关闭时保留 float32 图（曲率与法向带正负号）。" },
      drop_darkest: { label: "每像素丢掉最暗的灯", help: "四灯时每个像素用较亮的三张求解，深槽里的阴影不会把法向拉歪。", group: "高级" },
    },
    ports: { image: "光 1", image_1: "光 2", image_2: "光 3", image_3: "光 4", curvature: "曲率", curvature_abs: "形状强度", albedo: "反射率", normal_x: "法向 X", normal_y: "法向 Y", lights: "使用的灯数" },
  },
  circular_caliper: {
    label: "圆形卡尺",
    description: "沿圆形边缘放一圈径向卡尺，量出每个角度的半径。半径序列一眼看出崩边、缺口、毛刺与不圆；跳动量（最大减最小）就是径向偏差。把数值接进序列缺陷就能数出缺陷。",
    params: {
      roi: { label: "搜索环", help: "环要盖住边缘；带起止角时只量该扇形。" },
      caliper_count: { label: "卡尺数" },
      caliper_width: { label: "卡尺宽度", help: "每把卡尺切向平均的宽度，用来降噪。" },
      edge_threshold: { label: "边缘阈值" },
      polarity: { label: "极性", help: "由内往外的灰度变化。", options: { any: "不限", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      edge_select: { label: "选边", options: { first: "第一个（最内）", last: "最后一个（最外）", strongest: "最强" } },
      outlier_sigma: { label: "离群 σ", help: "与中位数差超过几倍稳健 σ 的半径不进统计（仍保留在序列里）。0 = 全部采计。" },
      smoothing: { label: "剖面平滑", group: "高级" },
    },
    ports: { image: "图像", roi: "搜索环（动态）", found: "找到", not_found: "未找到", radii: "半径列表", angles: "角度列表", points: "边缘点", all_points: "每把卡尺的点", mean_r: "平均半径", min_r: "最小半径", max_r: "最大半径", runout: "跳动量", missing_count: "未找到数", outlier_count: "离群数", cx: "中心 X", cy: "中心 Y" },
  },
  color_check: {
    label: "颜色检查",
    description: "区域内平均颜色与目标色的距離（RGB 或 HSV 空间）是否在容差内。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      color: {
        label: "目标色",
      },
      space: {
        label: "比較空间",
        options: {
          rgb: "RGB 歐氏距離（0~441）",
          hsv: "HSV（色相为主）",
        },
      },
      tolerance: {
        label: "容差",
        help: "RGB：歐氏距離；HSV：色相差（0~180，依饱和度加权）＋饱和度／明度差÷4 的距離。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
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
    label: "色彩空间 / 通道",
    description: "转 HSV/Lab 或抽出单一通道，作为色彩检测的前處理。",
    params: {
      mode: {
        label: "输出",
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
    label: "色彩范围遮罩",
    description: "HSV 范围内的像素为 255（支援 H 跨 0 的紅色）。",
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
      ratio: "覆盖比例",
    },
  },
  color_stats: {
    label: "色彩統计",
    description: "区域内 RGB 与 HSV 的平均／标準差、主色相与平均色；供颜色验证与上下游邏輯判斷。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      mean_r: "R 平均",
      mean_g: "G 平均",
      mean_b: "B 平均",
      mean_h: "色相平均",
      mean_s: "饱和度平均",
      mean_v: "明度平均",
      std_v: "明度标準差",
      hex: "平均色",
    },
  },
  concentricity: {
    label: "同心度",
    description: "兩个圆（例如外径与内径）圆心的偏移量；GD&T 同心度 = 2×偏移。接 find_circle 的 cx/cy/r 或 {cx,cy,r}。",
    params: {
      max_deviation: {
        label: "最大偏移",
        help: "圆心距離超过此值走 ng 分支。",
      },
    },
    ports: {
      image: "影像",
      a: "圆 A",
      b: "圆 B",
      ax: "A 圆心 X",
      ay: "A 圆心 Y",
      ar: "A 半径",
      bx: "B 圆心 X",
      by: "B 圆心 Y",
      br: "B 半径",
      ok: "合格",
      ng: "超差",
      deviation: "偏移量",
      concentricity: "同心度（2×偏移）",
      verdict: "判定",
      in_spec: "合格",
    },
  },
  contour_filter: {
    label: "轮廓筛选",
    description: "依面积、周长、凸度、长宽比与位置留下合格的轮廓并排序。放在轮廓提取与几何／比对工具之间，先去掉噪声、孔洞与不测的部位。",
    params: {
      min_area: { label: "最小面积" },
      max_area: { label: "最大面积", help: "0 = 不限。" },
      min_perimeter: { label: "最小周长", group: "更多限制" },
      max_perimeter: { label: "最大周长", help: "0 = 不限。", group: "更多限制" },
      min_convexity: { label: "最小凸度", help: "面积除以凸包面积；凸形为 1。", group: "更多限制" },
      max_convexity: { label: "最大凸度", group: "更多限制" },
      min_aspect: { label: "最小长宽比", help: "最小外接矩形的长边除以短边。", group: "更多限制" },
      max_aspect: { label: "最大长宽比", help: "0 = 不限。", group: "更多限制" },
      roi: { label: "只留区域内", help: "只留下重心落在此区域内的轮廓。", group: "更多限制" },
      sort_by: {
        label: "排序",
        options: { area: "面积（大到小）", perimeter: "周长（长到短）", x: "X（左到右）", y: "Y（上到下）", none: "保持输入顺序" },
      },
      max_count: { label: "最多输出", help: "排序后最多留这么多条。" },
      min_count: { label: "最少通过数", help: "少于此数视为 NG。", group: "判定" },
    },
    ports: {
      contours: "轮廓", roi: "只留区域内（动态）", found: "找到", not_found: "未找到", count: "数量", rejected: "剔除数",
      areas: "面积列表", first_area: "第一条面积", centers: "重心", first_cx: "第一条重心 X", first_cy: "第一条重心 Y",
    },
  },
  contour_find: {
    label: "轮廓提取",
    description: "从二值图像描出外形（灰度输入先二值化）：只取外轮廓，或连孔洞一起。轮廓接轮廓筛选、轮廓几何、轮廓比对与公差工具；坐标是输入图像的坐标。",
    params: {
      roi: { label: "区域", help: "留空则整张图像。" },
      threshold_method: {
        label: "二值化",
        options: { otsu: "Otsu（自动）", fixed: "固定", none: "输入已是掩码（非零即前景）" },
      },
      threshold: { label: "阈值" },
      polarity: { label: "前景", options: { bright: "亮物体", dark: "暗物体" } },
      mode: {
        label: "提取方式",
        options: { external: "只取外轮廓", list: "全部轮廓（含孔洞，不分层）", ccomp: "外轮廓与其孔洞", tree: "完整层级" },
      },
      approx: { label: "简化", help: "开：直线段只留端点。关：每个边界像素都留。" },
      min_points: { label: "最少点数", help: "点数少于此值的轮廓丢弃。" },
      min_area: { label: "最小面积", help: "0 = 全部保留。" },
      max_count: { label: "最多输出" },
    },
    ports: {
      image: "图像", roi: "区域（动态）", found: "找到", not_found: "未找到", contours: "轮廓", count: "数量",
      areas: "面积列表", first_area: "第一条面积", centers: "重心", first_cx: "第一条重心 X", first_cy: "第一条重心 Y", mask: "掩码",
    },
  },
  contour_geometry: {
    label: "轮廓几何",
    description: "测每一条轮廓：面积、周长、重心、最小外接矩形（含角度）、最小外接圆、凸包面积与凸度、凸缺陷（缺角、边缘被咬掉一块、异物咬入外形——计数并回报最深的一个）、圆形度与 Hu 矩。列表每条一项；first_ 端口是第一条。",
    params: {
      defect_depth: { label: "缺陷深度", help: "外形相对凸包凹陷超过此深度就算一个凸缺陷。" },
      max_contours: { label: "最多轮廓数", help: "只测前 N 条。" },
    },
    ports: {
      contours: "轮廓", image: "图像（显示用）", geometry: "几何", count: "数量", areas: "面积列表", perimeters: "周长列表", centers: "重心",
      rects: "最小外接矩形", circles: "外接圆", convexities: "凸度列表", defect_counts: "缺陷数列表", defect_points: "缺陷点",
      first_area: "第一条面积", first_perimeter: "第一条周长", first_cx: "第一条重心 X", first_cy: "第一条重心 Y",
      first_w: "第一条长", first_h: "第一条宽", first_angle: "第一条角度", first_r: "第一条外接圆半径", first_convexity: "第一条凸度",
      first_circularity: "第一条圆形度", first_defects: "第一条缺陷数", first_max_defect_depth: "第一条最深缺陷",
      total_defects: "缺陷总数", max_defect_depth: "最深缺陷",
    },
  },
  contour_match: {
    label: "轮廓比对",
    description: "以 Hu 矩距离把每条轮廓与参考外形比对，不受位置、缩放与旋转影响。参考来自另一个轮廓提取（参考端口）或模板图像中最大的形状。距离低于上限即为相符——用来依外形分料，或抓错料与变形件。",
    params: {
      template: { label: "模板图像", help: "参考端口没接时使用；二值化后最大的亮形状就是参考。" },
      template_threshold: {
        label: "模板二值化",
        options: { otsu: "Otsu（自动）", fixed: "固定", none: "模板已是掩码" },
        group: "模板",
      },
      threshold: { label: "阈值", group: "模板" },
      polarity: { label: "模板前景", options: { bright: "亮形状", dark: "暗形状" }, group: "模板" },
      method: {
        label: "方法",
        options: { i1: "I1（|1/mA − 1/mB| 总和）", i2: "I2（|mA − mB| 总和）", i3: "I3（最大相对差）" },
      },
      max_distance: { label: "最大距离", help: "距离不超过此值即相符。相同形状接近 0；可试 0.05～0.3。" },
      min_matches: { label: "最少相符数", help: "相符的轮廓少于此数视为 NG。", group: "判定" },
    },
    ports: {
      contours: "轮廓", reference: "参考轮廓", image: "图像（显示用）", match: "相符", no_match: "不符",
      distances: "距离列表", distance: "最佳距离", best_index: "最佳索引", match_flag: "相符", match_count: "相符数",
      matched: "相符的轮廓", best: "最佳轮廓", first_distance: "第一条距离",
    },
  },
  convert_depth: {
    label: "位深转换",
    description: "8 位元／16 位元／浮点影像互转。转 8 位元可选右移（线性、可預期）或 min-max 拉伸（吃滿動态范围）。",
    params: {
      to: {
        label: "目标位深",
        options: {
          u8: "8 位元（U8）",
          u16: "16 位元（U16）",
          f32: "浮点（SGL）",
        },
      },
      scale: {
        label: "转 8 位元方式",
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
    label: "数量",
    description: "输出 list／points／matches 的元素数量。",
    ports: {
      items: "清单",
      count: "数量",
    },
  },
  crop: {
    label: "裁切 ROI",
    description: "裁出区域成为新影像（旋转矩形會摆正）。下游工具在小图上跑會快很多。",
    params: {
      roi: {
        label: "区域",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      offset_x: "偏移 X",
      offset_y: "偏移 Y",
    },
  },
  dark_ratio: {
    label: "暗区比例（范例外掛）",
    description: "ROI 内灰阶低于门槛的像素比例，超过允许比例走「不良」分支。",
    params: {
      roi: {
        label: "区域",
      },
      threshold: {
        label: "门槛",
      },
      max_ratio: {
        label: "允许比例",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      ratio: "比例",
      pass: "合格",
      fail: "不良",
    },
  },
  defect_diff: {
    label: "差異缺陷",
    description: "与良品范本对齊後做灰阶差異（absdiff → 门槛 → 形态學），差異区域即缺陷。",
    params: {
      template: {
        label: "良品范本",
      },
      roi: {
        label: "区域",
        help: "留空則整張影像。范本需与影像同尺寸（或會被缩放到相同尺寸）。",
      },
      align: {
        label: "对齊",
        options: {
          none: "不对齊",
          phase: "相位相关（平移）",
          ecc: "ECC（平移＋旋转）",
        },
      },
      blur: {
        label: "前置高斯核",
        group: "进阶",
      },
      threshold: {
        label: "差異门槛",
      },
      morph: {
        label: "形态學开運算核",
        group: "进阶",
      },
      min_area: {
        label: "最小缺陷面积",
      },
      max_count: {
        label: "最多输出",
      },
      border: {
        label: "忽略边界",
        help: "对齊後边界會有假差異，忽略此宽度。",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      ok: "無缺陷",
      defect: "有缺陷",
      defects: "缺陷列表",
      count: "数量",
      total_area: "总面积",
      defect_mask: "缺陷遮罩",
      diff: "差異影像",
    },
  },
  defect_stat: {
    label: "统计良品比对",
    description: "与多张良品建的统计模板比对：每个像素有自己的平均与变异范围，纹理区允许波动、平坦区抓得紧。偏离正常几倍标准差以上就是缺陷。打光变动与材质纹理下比单张良品稳得多。",
    params: {
      model: { label: "统计模板", help: "用 POST /vision/assets/stat-template 或 manage.py stat_template 由良品图像建立（.npz 文件资产）。" },
      roi: { label: "区域", help: "尺寸必须与建立模板时的区域相同；留空则整张图像。" },
      align: { label: "对齐", options: { none: "不对齐", phase: "相位相关（平移）" } },
      sigma: { label: "σ 阈值", help: "偏离正常几倍标准差算缺陷。先用 3；良品被误判就调高。" },
      min_sigma_floor: { label: "最小变异", help: "标准差不会低于此值，均匀区才不会把单阶噪声当缺陷。" },
      min_area: { label: "最小缺陷面积" },
      direction: { label: "方向", options: { both: "变暗或变亮", darker: "只看变暗", brighter: "只看变亮" } },
      border: { label: "忽略边界", help: "对齐后边界会有假差异，忽略这些像素。" },
      morph: { label: "开运算核", group: "高级" },
      max_count: { label: "最多输出", group: "高级" },
    },
    ports: { image: "图像", roi: "区域（动态）", ok: "干净", defect: "有缺陷", count: "数量", total_area: "总面积", max_sigma: "最大偏离", defect_mask: "缺陷掩码", deviation: "偏离图像", regions: "缺陷" },
  },
  distance: {
    label: "距離",
    description: "兩点距離（像素）。点可为 {x,y} / [x,y]，或分别接 ax, ay, bx, by 四个数值。",
    params: {
      mode: {
        label: "量测",
        options: {
          euclid: "直线距離",
          dx: "X 方向距離",
          dy: "Y 方向距離",
        },
      },
    },
    ports: {
      image: "影像",
      a: "点 A",
      b: "点 B",
      distance: "距離",
    },
  },
  dl_anomaly: {
    label: "深度学习异常检测",
    description: "用只以良品训练的模型，为画面每个区域打「与教导良品差多少」的分数。超过阈值的就是异常——划痕、凹陷、缺料、异物——完全不必给它看过缺陷。调阈值时看分数图。",
    params: {
      model: { label: "异常模型", help: "在教导页以「异常检测（只教良品）」训练。" },
      roi: { label: "区域", help: "留空则整张图像；区域会缩放到模型的输入尺寸。" },
      threshold: { label: "阈值", help: "异常分数高于此值的像素视为缺陷。0 = 使用模型内置的自动阈值。" },
      min_area: { label: "最小缺陷面积" },
      device: { label: "设备", options: { auto: "自动（有 GPU 就用）", cpu: "CPU", cuda: "CUDA" } },
      max_count: { label: "最多输出", group: "高级" },
    },
    ports: { image: "图像", roi: "区域（动态）", ok: "干净", defect: "有缺陷", score: "最大分数", count: "数量", total_area: "总面积", score_map: "分数图", mask: "掩码", regions: "区域", threshold_used: "使用的阈值" },
  },
  dl_classify: {
    label: "DL 分类",
    description: "以 ONNX 分类模型判斷区域屬于哪一类；最高分类别分数達门槛走 pass。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "类别名称",
        help: "每行一个类别，順序与模型输出一致；留空則用索引。",
      },
      input_size: {
        label: "输入尺寸",
        help: "模型输入为固定尺寸时以模型为準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 为单位；YOLO 通常填 0。",
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
        label: "区域",
        help: "留空則整張影像。",
      },
      threshold: {
        label: "分数门槛",
      },
      pass_labels: {
        label: "合格类别",
        help: "逗号分隔；不为空时，最高分类别需在此清单内才 pass。",
      },
      apply_softmax: {
        label: "输出套用 softmax",
        help: "模型已输出機率时可关闭。",
        group: "前處理",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      pass: "合格",
      fail: "不良",
      label: "类别",
      score: "分数",
      index: "索引",
    },
  },
  dl_detect: {
    label: "DL 物件偵测",
    description: "以 ONNX 偵测模型（YOLOv5/v8 風格输出）找物件；含 letterbox 前處理与 NMS。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "类别名称",
        help: "每行一个类别，順序与模型输出一致；留空則用索引。",
      },
      input_size: {
        label: "输入尺寸",
        help: "模型输入为固定尺寸时以模型为準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 为单位；YOLO 通常填 0。",
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
        label: "区域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心门槛",
      },
      iou: {
        label: "NMS IoU",
      },
      max_count: {
        label: "最多输出",
      },
      filter_labels: {
        label: "只保留类别",
        help: "逗号分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      normalized: {
        label: "输出座标为 0~1",
        help: "模型输出框为正規化座标时开啟。",
        group: "前處理",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      detections: "偵测结果",
      count: "数量",
      matches: "匹配（含 cx, cy）",
      labels: "类别列表",
    },
  },
  dl_instance: {
    label: "DL 实例分割",
    description: "以 YOLO-seg 風格的 ONNX 模型找出每个物件的轮廓与类别（含 letterbox 前處理、NMS 与 mask 合成）。可在平台的深度學習頁教導。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "类别名称",
        help: "每行一个类别，順序与模型输出一致；留空則用索引。",
      },
      input_size: {
        label: "输入尺寸",
        help: "模型输入为固定尺寸时以模型为準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 为单位；YOLO 通常填 0。",
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
        label: "区域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心门槛",
      },
      iou: {
        label: "NMS IoU",
      },
      max_count: {
        label: "最多输出",
      },
      filter_labels: {
        label: "只保留类别",
        help: "逗号分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多数量",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      count: "数量",
      matches: "实例",
      mask: "聯合遮罩",
      contours: "轮廓",
    },
  },
  dl_segment: {
    label: "DL 语意分割",
    description: "以 ONNX 分割模型输出每像素类别（argmax），回传类别遮罩与各类面积。",
    params: {
      model: {
        label: "ONNX 模型",
      },
      labels: {
        label: "类别名称",
        help: "每行一个类别，順序与模型输出一致；留空則用索引。",
      },
      input_size: {
        label: "输入尺寸",
        help: "模型输入为固定尺寸时以模型为準。",
      },
      mean: {
        label: "平均",
        help: "以 0~1 为单位；YOLO 通常填 0。",
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
        label: "区域",
        help: "留空則整張影像。",
      },
      target_class: {
        label: "目标类别索引",
        help: "mask 输出为此类别的 0/255 遮罩；class_map 为全部类别索引。",
      },
      min_area: {
        label: "合格最小面积",
        group: "判定",
      },
      max_area: {
        label: "合格最大面积",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      ok: "合格",
      ng: "不良",
      mask: "目标遮罩",
      class_map: "类别图",
      area: "目标面积",
      classes: "各类面积",
    },
  },
  draw_result: {
    label: "结果影像",
    description: "把上游工具的标记画进影像，产生可存档／可显示的结果图（OK 綠、NG 紅）。",
    params: {
      thickness: {
        label: "线宽",
      },
      banner: {
        label: "显示判定横幅",
      },
    },
    ports: {
      image: "影像",
      overlays: "标记",
    },
  },
  edge_density: {
    label: "边缘密度",
    description: "区域内 Canny 边缘像素比例；平滑表面出現刮痕、脏污时比例會升高。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      canny_low: {
        label: "Canny 低门槛",
      },
      canny_high: {
        label: "Canny 高门槛",
      },
      blur: {
        label: "前置高斯核",
        group: "进阶",
      },
      max_ratio: {
        label: "合格最大比例",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      ok: "合格",
      ng: "超标",
      ratio: "边缘比例",
      edge_pixels: "边缘像素数",
      edges: "边缘影像",
    },
  },
  fft_filter: {
    label: "频域滤波（FFT）",
    description: "频域滤波：低通去周期性纹理／雜訊、高通留边缘，截斷（truncate）或高斯衰減（attenuate）。另输出频谱图供检視。",
    params: {
      mode: {
        label: "滤波",
        options: {
          lowpass: "低通（保留大结构）",
          highpass: "高通（保留边缘／细纹，以中灰 128 为零点）",
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
        label: "截止（半径比例）",
      },
    },
    ports: {
      image: "影像",
      spectrum: "频谱",
    },
  },
  filter: {
    label: "卷积滤波",
    description: "卷积与边缘滤波：锐利化、Canny 边缘、Laplacian、Sobel／Prewitt 梯度、高通、浮雕，或自訂 3×3 kernel（JSON）。平滑用「模糊」工具。",
    params: {
      method: {
        label: "方法",
        options: {
          sharpen: "锐利化",
          canny: "Canny 边缘（二值）",
          gradient: "梯度强度（Sobel）",
          prewitt: "Prewitt 梯度",
          highpass: "高通",
          emboss: "浮雕",
          custom: "自訂 3×3",
        },
      },
      strength: {
        label: "强度",
      },
      low: {
        label: "Canny 低门槛",
      },
      high: {
        label: "Canny 高门槛",
      },
      ksize: {
        label: "核大小",
      },
      kernel: {
        label: "自訂 kernel",
        help: "3×3 数字阵列。",
      },
    },
    ports: {
      image: "影像",
    },
  },
  find_circle: {
    label: "找圆",
    description: "从 ROI 中心向外发射径向掃描线找边缘点，再以最小平方或 RANSAC 拟合圆。",
    params: {
      roi: {
        label: "区域",
        help: "圆／圆環：由中心往外掃到外半径（圆環可设扇形起迄角，只掃該扇形）；矩形：掃到内切半径。",
      },
      polarity: {
        label: "边缘极性",
        help: "沿掃描线由内往外的灰阶变化方向。",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
        help: "灰阶梯度低于此值不算边缘。",
      },
      num_rays: {
        label: "掃描线数",
      },
      edge_select: {
        label: "取哪个边缘",
        options: {
          strongest: "最强",
          first: "第一个（最靠内）",
          last: "最後一个（最靠外）",
        },
      },
      ransac: {
        label: "RANSAC 剔除離群",
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "进阶",
      },
      refine: {
        label: "重掃精修",
        help: "ROI 中心偏離圆心时，以拟合圆心重掃一次讓掃描线与边缘垂直。",
        group: "进阶",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      cx: "中心 X",
      cy: "中心 Y",
      r: "半径",
      points: "边缘点",
      score: "分数",
    },
  },
  find_line: {
    label: "找直线",
    description: "在矩形区域内放多條垂直于长边的卡尺掃描线找边缘点，再拟合直线（可 RANSAC）。",
    params: {
      roi: {
        label: "区域",
        help: "长边方向为直线方向，卡尺沿短边掃描。",
      },
      polarity: {
        label: "边缘极性",
        help: "沿短边（由上到下／由左到右）的灰阶变化。",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
      },
      num_calipers: {
        label: "卡尺数",
      },
      direction: {
        label: "取哪个边缘",
        options: {
          first: "第一个",
          last: "最後一个",
          strongest: "最强",
        },
      },
      ransac: {
        label: "RANSAC 剔除離群",
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "进阶",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      angle: "夹角",
      line: "线",
      points: "边缘点",
    },
  },
  fit_arc: {
    label: "圆弧拟合",
    description: "在区域内找边缘点并以最小平方（可 RANSAC）拟合圆弧：R 角、杯口圆角的半径与圆心。",
    params: {
      roi: {
        label: "区域",
        help: "圆／環／多边形：由中心往外径向掃描；矩形：沿长边放卡尺。",
      },
      polarity: {
        label: "边缘极性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
      },
      num_rays: {
        label: "掃描线数",
        help: "圆／環／多边形为径向掃描线数，矩形为卡尺数。",
      },
      edge_select: {
        label: "取哪个边缘",
        options: {
          strongest: "最强",
          first: "第一个",
          last: "最後一个",
        },
      },
      refine: {
        label: "重掃精修",
        help: "拟合後以拟合中心重掃一次：ROI 偏心或多边形 ROI 时精度明显較好。",
        group: "进阶",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
      ransac: {
        label: "RANSAC 剔除離群",
      },
      ransac_tol: {
        label: "RANSAC 容差",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      radius: "半径",
      cx: "中心 X",
      cy: "中心 Y",
      residual_rms: "残差 RMS",
      points: "边缘点",
      start_angle: "起角",
      end_angle: "終角",
    },
  },
  fit_ellipse: {
    label: "橢圆拟合",
    description: "在区域内找边缘点并以直接最小平方（Direct）拟合橢圆；roundness = 短軸／长軸（1 为正圆），用来量杯口橢圆度。",
    params: {
      roi: {
        label: "区域",
      },
      polarity: {
        label: "边缘极性",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
      },
      num_rays: {
        label: "掃描线数",
        help: "圆／環／多边形为径向掃描线数，矩形为卡尺数。",
      },
      edge_select: {
        label: "取哪个边缘",
        options: {
          strongest: "最强",
          first: "第一个",
          last: "最後一个",
        },
      },
      refine: {
        label: "重掃精修",
        help: "拟合後以拟合中心重掃一次：ROI 偏心或多边形 ROI 时精度明显較好。",
        group: "进阶",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      cx: "中心 X",
      cy: "中心 Y",
      a: "长半軸",
      b: "短半軸",
      angle: "长軸角度",
      roundness: "圆度 b/a",
      residual_rms: "残差 RMS",
      points: "边缘点",
    },
  },
  fixture_roi: {
    label: "ROI 跟随",
    description: "把画好的 ROI 依定位补正的 dx/dy/dθ 移動，输出動态区域給下游工具的 ROI 输入埠。",
    params: {
      roi: {
        label: "区域",
      },
    },
    ports: {
      image: "影像",
      transform: "变换",
      region: "区域",
    },
  },
  formula: {
    label: "公式",
    description: "以 a、b、c、d 代表输入，寫一段算式（例如 abs(a-b)/c*100）。支援 +-*/、比較、and/or、abs/min/max/sqrt/…。",
    params: {
      expression: {
        label: "公式",
        help: "变数 a b c d 对应四个输入；结果可为数值或布林。",
      },
    },
    ports: {
      value: "值",
      result: "布林",
    },
  },
  geometry: {
    label: "幾何计算",
    description: "解析幾何：兩线交点、点到线垂距、兩点中点、点在线上的投影。线＝{x1,y1,x2,y2}、点＝[x,y] 或 {x,y}（接找线／找圆等工具的输出）。",
    params: {
      mode: {
        label: "计算",
        options: {
          intersect: "兩线交点",
          point_line: "点到线垂距",
          midpoint: "兩点中点",
          project: "点投影到线",
        },
      },
    },
    ports: {
      a: "A（线／点）",
      b: "B（线／点）",
      distance: "距離",
    },
  },
  grayscale: {
    label: "灰阶",
    description: "彩色转灰阶；已是灰阶則直通。",
    ports: {
      image: "影像",
    },
  },
  histogram: {
    label: "直方图",
    description: "区域内 256 阶灰阶直方图与峰值。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      normalize: {
        label: "正規化（比例）",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      histogram: "直方图",
      peak: "峰值灰阶",
      peak_count: "峰值数量",
      otsu: "Otsu 门槛",
    },
  },
  hough_circles: {
    label: "Hough 找圆",
    description: "cv2.HoughCircles（梯度法）在区域内找多个圆。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      min_radius: {
        label: "最小半径",
      },
      max_radius: {
        label: "最大半径",
      },
      min_dist: {
        label: "圆心最小间距",
      },
      param1: {
        label: "Canny 高门槛",
        group: "进阶",
      },
      param2: {
        label: "累积门槛",
        help: "越小找到越多（含误判）。",
        group: "进阶",
      },
      blur: {
        label: "前置中值滤波核",
        group: "进阶",
      },
      max_count: {
        label: "最多输出",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      circles: "圆",
      count: "数量",
    },
  },
  hough_lines: {
    label: "Hough 找线段",
    description: "Canny 边缘後以機率 Hough（HoughLinesP）找线段。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      canny_low: {
        label: "Canny 低门槛",
      },
      canny_high: {
        label: "Canny 高门槛",
      },
      threshold: {
        label: "累积门槛",
      },
      min_length: {
        label: "最短线段",
      },
      max_gap: {
        label: "最大斷点间隙",
      },
      max_count: {
        label: "最多输出",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      lines: "线段",
      count: "数量",
    },
  },
  if_number: {
    label: "数值判斷",
    description: "把输入数值与门槛比較，走 true / false 分支；下游连到分支把手的節点只在該分支被选中时执行。",
    params: {
      operator: {
        label: "比較",
      },
      threshold: {
        label: "门槛",
      },
      tolerance: {
        label: "容差（= / ≠ 用）",
      },
    },
    ports: {
      value: "值",
      result: "结果",
    },
  },
  image_source: {
    label: "影像来源",
    description: "从设定的影像来源抓一張影像；API 直接送图时（POST run 附影像）優先使用送来的影像。",
    params: {
      source_id: {
        label: "影像来源",
        help: "留空則只接受 API 送来的影像。",
      },
      mode: {
        label: "取像模式",
        options: {
          auto: "暫存／API 送图優先，否則从来源庫抓",
          source: "一律从来源抓",
          input: "只用暫存影像（试跑上传或 API 送图；沒有就報錯）",
        },
      },
      convert: {
        label: "色彩",
        options: {
          keep: "維持原样",
          gray: "转灰阶",
          bgr: "转彩色（BGR）",
        },
      },
    },
    ports: {
      image: "影像",
      width: "宽",
      height: "高",
    },
  },
  in_range: {
    label: "在范围内",
    description: "数值是否落在 [下限, 上限]；常用于量测值公差判定。",
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
      inside: "在范围内",
      outside: "超出范围",
      result: "结果",
    },
  },
  intensity: {
    label: "灰阶統计",
    description: "区域内的灰阶平均、标準差、最小、最大、中位数。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像；点＝单一像素。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      mean: "平均",
      std: "标準差",
      min: "最小",
      max: "最大",
      median: "中位数",
      pixels: "像素数",
    },
  },
  judge: {
    label: "OK / NG 判定",
    description: "決定整个 run 的判定结果。连到分支把手时，被选中即判定；或用布林输入決定。",
    params: {
      verdict: {
        label: "判定",
        options: {
          by_input: "依布林输入（真=OK，假=NG）",
          ok: "固定 OK",
          ng: "固定 NG",
        },
      },
      label: {
        label: "结果标籤",
        help: "寫进 run.outputs.judge_label，方便自動化辨认是哪一條判定。",
      },
    },
    ports: {
      value: "布林",
      verdict: "判定",
    },
  },
  line_profile: {
    label: "线剖面",
    description: "沿著线（或折线）取灰阶值，输出剖面序列与統计；抓斷差、亮暗帶、掃描线缺陷。",
    params: {
      roi: {
        label: "线",
      },
      samples: {
        label: "取样点数",
        help: "0 = 每像素一点。",
      },
    },
    ports: {
      image: "影像",
      roi: "线（動态）",
      values: "剖面值",
      mean: "平均",
      std: "标準差",
      min: "最小",
      max: "最大",
      length: "长度",
    },
  },
  lut: {
    label: "查表转换（LUT）",
    description: "灰阶转换与对比增强：线性（亮度／对比）、Gamma、对数、指数、平方、开根号、反相、直方图等化、CLAHE；查表类彩色逐通道套用。",
    params: {
      mode: {
        label: "转换",
        options: {
          linear: "线性（亮度／对比）",
          power: "Gamma（次方）",
          log: "对数（暗部展开）",
          exp: "指数（亮部展开）",
          sqrt: "开根号",
          square: "平方",
          invert: "反相",
          equalize: "直方图等化",
          clahe: "CLAHE（区域对比）",
        },
      },
      clip: {
        label: "CLAHE clip",
      },
      tile: {
        label: "CLAHE 格数",
      },
      brightness: {
        label: "亮度",
      },
      contrast: {
        label: "对比",
      },
    },
    ports: {
      image: "影像",
    },
  },
  morphology: {
    label: "形态學",
    description: "侵蝕、膨脹、开、闭、梯度、頂帽、黑帽。",
    params: {
      op: {
        label: "運算",
        options: {
          erode: "侵蝕",
          dilate: "膨脹",
          open: "开運算",
          close: "闭運算",
          gradient: "梯度",
          tophat: "頂帽",
          blackhat: "黑帽",
        },
      },
      shape: {
        label: "核形状",
        options: {
          rect: "矩形",
          ellipse: "橢圆",
          cross: "十字",
        },
      },
      ksize: {
        label: "核大小",
      },
      iterations: {
        label: "次数",
      },
    },
    ports: {
      image: "影像",
    },
  },
  ocr_read: {
    label: "文字识别（OCR）",
    description: "从区域读出印刷文字——日期码、批号、料号——返回字符串，并附每个字的置信度与框。限制字符集（日期码用数字）能明显提升准确率。点阵喷印或激光打标这类通用模型读不好的字体，在资产页教字体后在此选用。",
    params: {
      roi: { label: "文字区域", help: "留空则整张图像。单行模式请框一行。" },
      mode: { label: "模式", options: { line: "单行（把区域当一行读）", detect: "先检测多行" } },
      model: { label: "模型", help: "留空 = 内置通用模型。选教导字体（.npz）则改走切分＋逐字分类。" },
      charset: { label: "字符集", options: { alnum: "字母与数字", digits: "数字（与 - . / :）", upper: "大写字母与数字", any: "任何字符", custom: "自定义" } },
      custom_charset: { label: "自定义字符", help: "所有可能出现的字符，例如 0123456789ABCDEF-" },
      polarity: { label: "极性", options: { dark_on_light: "亮底暗字", light_on_dark: "暗底亮字" } },
      min_confidence: { label: "最低置信度", help: "有一个字低于此值就视为未读到。" },
      preprocess: { label: "预处理", options: { auto: "自动（对比拉伸与去噪）", none: "无" } },
      segmentation: { label: "切分（教导字体）", options: { projection: "投影（字符间空隙）", components: "连通域", fixed: "固定间距（已知字数）" }, group: "教导字体" },
      char_count: { label: "字数（固定间距）", help: "固定间距切分把墨迹范围等分成这么多格。", group: "教导字体" },
    },
    ports: { image: "图像", roi: "文字区域（动态）", found: "找到", not_found: "未找到", text: "文字", items: "行", confidence: "置信度", count: "行数" },
  },
  ocv_verify: {
    label: "字符串验证（OCV）",
    description: "把读到的文字与应该是的字符串比对：固定字符串，或上位机为此批下发的值。? 代表任一字、# 代表任一数字；较长的印字可用包含与正则表达式模式。报告第一个错的是第几个字并以红框标出。",
    params: {
      expected: { label: "预期文字", help: "? = 任一字，# = 任一数字。例：LOT######" },
      expected_source: { label: "预期来源", options: { param: "此参数", input: "预期输入端口（上位机）" } },
      mode: { label: "模式", options: { exact: "完全相同", contains: "包含", regex: "正则表达式" } },
      min_char_confidence: { label: "最低逐字置信度", help: "字对了但置信度低于此值也算失败。需要接上「行」输入。" },
      ignore_case: { label: "忽略大小写" },
      strip: { label: "忽略前后空白" },
    },
    ports: { text: "文字", expected: "预期", items: "行（来自文字识别）", image: "图像（显示用）", pass: "通过", fail: "失败", match: "相符", actual: "实际", fail_index: "第一个错的位置", expected_text: "预期" },
  },
  output: {
    label: "具名输出",
    description: "把一个值以指定名称放进 run 的 outputs，供 API / TCP 回传給自動化系統。",
    params: {
      name: {
        label: "名称",
      },
      decimals: {
        label: "小数位数",
      },
    },
    ports: {
      value: "值",
    },
  },
  pixel_count: {
    label: "像素数",
    description: "遮罩（或灰阶以门槛二值化後）在区域内的前景像素数与比例。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      threshold: {
        label: "门槛",
        help: "大于等于此灰阶算前景；输入已是 0/255 遮罩时維持預设即可。",
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
      roi: "区域（動态）",
      ok: "合格",
      ng: "不良",
      count: "像素数",
      ratio: "比例",
      total: "区域像素数",
    },
  },
  polar_restore: {
    label: "极坐标还原",
    description: "把在展开图上找到的点与轮廓换回原图坐标，让极坐标展开后找到的缺陷能标在原图上。接极坐标展开的「对应」输出；下方的数值与设置只在没接对应时才用。",
    params: {
      r_outer: {
        label: "外半径",
        help: "只在没接对应端口时使用。",
        group: "无对应时",
      },
      angle_step: {
        label: "角度步进",
        group: "无对应时",
        options: {
          auto: "自动（外缘 1 px 弧长）",
          "0.5": "0.5°",
          "1": "1°",
          "2": "2°",
        },
      },
      radial_step: {
        label: "径向步进",
        group: "无对应时",
      },
      direction: {
        label: "方向",
        group: "无对应时",
        options: {
          ccw: "逆时针",
          cw: "顺时针",
        },
      },
      start_angle: {
        label: "起始角",
        group: "无对应时",
      },
    },
    ports: {
      image: "原图（显示用）",
      mapping: "对应",
      points: "点（展开图）",
      contours: "轮廓（展开图）",
      cx: "中心 X",
      cy: "中心 Y",
      r_inner: "内半径",
      r_outer: "外半径",
      count: "数量",
      first_x: "第一个 X",
      first_y: "第一个 Y",
      first_angle: "第一个角度",
      first_radius: "第一个半径",
    },
  },
  polar_unwrap: {
    label: "极坐标展开",
    description: "把圆环摊平成长条图：宽＝角度、高＝半径（内圈在上）。螺纹、齿轮齿、轴承滚珠、O-ring 缺口、圆形标签文字都变成一列直的，一般的二值化、blob、卡尺与找线工具就读得到。把「对应」输出接到极坐标还原，结果就能画回原图。",
    params: {
      roi: {
        label: "圆环",
        help: "要展开的环带。带起止角的圆环只展开该扇形。",
      },
      angle_step: {
        label: "角度步进",
        help: "每一列几度。自动＝外缘每列 1 px，不会欠采样。",
        options: {
          auto: "自动（外缘 1 px 弧长）",
          "0.5": "0.5°",
          "1": "1°",
          "2": "2°",
        },
      },
      radial_step: {
        label: "径向步进",
        help: "每一行几个像素。",
      },
      direction: {
        label: "方向",
        help: "长条图沿圆环走的方向（以画面为准）。",
        options: {
          ccw: "逆时针",
          cw: "顺时针",
        },
      },
      start_angle: {
        label: "起始角",
        help: "长条图左缘落在哪个角度（0 = 3 点钟方向，正值为顺时针）。扇形不用此值，从自己的起止角开始。",
      },
      interpolation: {
        label: "插值",
        group: "高级",
        options: {
          nearest: "最近邻",
          linear: "线性",
          cubic: "三次",
        },
      },
    },
    ports: {
      image: "图像",
      roi: "圆环（动态）",
      mapping: "对应",
      cx: "中心 X",
      cy: "中心 Y",
      r_inner: "内半径",
      r_outer: "外半径",
      step_deg: "每列角度",
    },
  },
  profile_defect: {
    label: "序列缺陷",
    description: "在一维序列（圆形卡尺的半径、或线剖面）里找偏离基线的区段：缺口与凹陷（向内）、毛刺与凸起（向外）。卡尺完全找不到边的位置也算缺陷——大崩边会让边缘消失。接上边缘点后，每个缺陷都画回原图。",
    params: {
      baseline: { label: "基线", help: "「正常」是什么：对边缘点拟合的圆（需要点）、滑动中位数、拟合直线或平均。", options: { fit_circle: "拟合圆（圆形卡尺的半径）", median: "滑动中位数", fit_line: "拟合直线", mean: "平均" } },
      window: { label: "窗口", help: "滑动中位数的窗口长度（点数）。" },
      threshold: { label: "阈值", help: "算缺陷的偏离量（数值单位，或 σ 倍数）。" },
      threshold_mode: { label: "阈值模式", options: { absolute: "绝对值（数值单位）", sigma: "σ 倍数（稳健离散度）" } },
      min_width: { label: "最小宽度", help: "缺陷至少要连续几点；挡单点噪声。" },
      direction: { label: "方向", options: { both: "两者", inward: "向内（凹陷、缺口、打空）", outward: "向外（毛刺、凸起）" } },
      max_defects: { label: "最多缺陷数", help: "超过此数为 NG；0 = 有缺陷就 NG。" },
      wrap: { label: "循环序列", help: "最后一点接回第一点（整圈）。线剖面请关闭。" },
      missing_as_defect: { label: "打空算缺陷", help: "没有值的位置（卡尺找不到边）视为向内缺陷。" },
    },
    ports: { values: "数值", points: "点", image: "图像（显示用）", ok: "干净", defect: "有缺陷", count: "数量", defects: "缺陷", max_deviation: "最大偏离", baseline_values: "基线", deviation: "偏离" },
  },
  python_script: {
    label: "Python 脚本",
    description: "自己寫一段 Python（def run(ctx)）做检测：讀影像／上游值／現場参数，回传数值、布林、文字、资料、新影像与标记，并決定通过／不良分支。只有管理員能編輯脚本；受限执行（白名单匯入、逾时中止）。",
    params: {
      code: {
        label: "程式碼",
        help: "定义 def run(ctx)；可用 np、cv2、math 与白名单模组。回传 dict 或单一值（数值／布林／文字／影像）。",
      },
      p1: {
        label: "現場参数 1",
        help: "脚本以 ctx.params['p1'] 讀取；技术員可在参数卡调整，不必改程式碼。",
        group: "現場参数",
      },
      p2: {
        label: "現場参数 2",
        group: "現場参数",
      },
      p3: {
        label: "現場参数 3",
        group: "現場参数",
      },
      roi: {
        label: "区域",
        help: "脚本以 ctx.roi()／ctx.crop() 取用；留空則整張影像。",
      },
      max_ms: {
        label: "逾时（毫秒）",
        help: "純 Python 迴圈超过此时间即中止（numpy／cv2 呼叫不计）。",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      pass: "合格",
      fail: "不良",
      value: "值",
      result: "布林",
      text: "文字",
      data: "资料",
    },
  },
  read_modbus: {
    label: "讀取 Modbus",
    description: "从通訊连线讀线圈与暫存器的值，供流程判斷或回传。主站连线（modbus_tcp）是去讀 PLC／设备；从站连线（modbus_server）是讀主站寫进本平台暫存器的值（例如料号、触发旗标）。",
    params: {
      connection: {
        label: "连线",
        help: "填通訊连线的名称（设定頁「外部整合 → 连线」建立）。",
      },
      mapping: {
        label: "讀取表",
        help: "阵列，每项 {\"name\": 名称, \"address\": 位址, \"scale\"?: 倍率, \"offset\"?: 加值}。位址：coil:10 / discrete:3 / holding:100 / holding:100:float32 / input:7；名称空白时用位址當名称。",
      },
      publish: {
        label: "同时放进具名输出",
        help: "开啟後讀到的值會出現在 run 的 outputs（API／TCP 回传看得到）。",
      },
      on_error: {
        label: "讀取失敗时",
        options: {
          warn: "降级：记警告，run 照常",
          fail: "讓 run 失敗",
        },
      },
      timeout_s: {
        label: "逾时（秒）",
        help: "0 = 用连线设定的逾时。",
        group: "进阶",
      },
    },
    ports: {
      values: "值",
      value: "第一个值",
      ok: "成功",
    },
  },
  region_combine: {
    label: "区域组合",
    description: "把好几个区域组成一个：从测量区挖掉孔位、字样或反光带（挖除）、把分开的几块合成一块（并集）、只留重叠处（交集）。结果接任何工具的区域输入端口——blob、统计、良品比对等都按组合后的掩码算。",
    params: {
      base: { label: "基底区域", help: "起始的区域。留空则以第一个接进来的区域为基底。" },
      mode: {
        label: "模式",
        options: { subtract: "挖除（从基底挖掉这些区域）", union: "并集（把这些区域加进基底）", intersect: "交集（只留重叠处）" },
      },
    },
    ports: { base: "基底区域（动态）", regions: "要组合的区域", image: "图像（显示用）", region: "区域", count: "组成数" },
  },
  region_from_shape: {
    label: "区域",
    description: "把画好的形状变成区域输出，让画布上能有第二、第三个区域——交给区域组合的排除区与加量区域。本身不影响图像。",
    params: {
      roi: { label: "形状", help: "任何形状：矩形、旋转矩形、圆、椭圆、圆环、多边形。" },
    },
    ports: { image: "图像（显示用）", region: "区域" },
  },
  resize: {
    label: "比例",
    description: "依比例或指定尺寸缩放；大图先缩小再處理是最有效的加速。",
    params: {
      scale: {
        label: "比例",
      },
      width: {
        label: "宽（0 = 用比例）",
      },
      height: {
        label: "高（0 = 用比例）",
      },
      interpolation: {
        label: "插值",
        options: {
          area: "区域（缩小）",
          linear: "线性",
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
    label: "旋转 / 翻转",
    description: "90 度倍数旋转、任意角度旋转、水平／垂直翻转。",
    params: {
      angle: {
        label: "角度（順时針）",
      },
      flip: {
        label: "翻转",
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
    label: "传送图像",
    description: "把这一步的图像经 TCP 传图连接（种类 tcp_image）推给上位程序，表头带 run id、判定与具名输出。默认失败只记警告、不让 run 失败。",
    params: {
      connection: { label: "连接", help: "TCP 传图连接的名称（在「外部集成 ▸ TCP」创建；填 id 也可以）。" },
      encoding: { label: "编码", options: { "": "依连接设置", jpeg: "JPEG", png: "PNG（无损）", raw: "原始像素" } },
      quality: { label: "JPEG 质量", group: "进阶" },
      name: { label: "帧名称", help: "放进表头的 name；留空用连接名称。", group: "进阶" },
      include_values: { label: "附上判定与输出", help: "把 judge 与到目前为止的具名输出放进表头的 values。", group: "进阶" },
      only_ng: { label: "只送 NG" },
      on_error: { label: "传送失败时", options: { warn: "降级：记警告、继续", fail: "让 run 失败" } },
      timeout_s: { label: "超时（秒）", help: "0 用连接自己的超时。", group: "进阶" },
    },
    ports: { image: "图像", sent: "已送出", bytes: "字节数" },
  },
  save_image: {
    label: "存档",
    description: "把影像存到资料夹（依判定 OK/NG 分子资料夹可选）。档名含时间戳与 run id。",
    params: {
      folder: {
        label: "资料夹",
        help: "留空則存到 DATA_DIR/saved/<flow_id>。",
      },
      format: {
        label: "格式",
      },
      split_by_judge: {
        label: "依判定分资料夹",
      },
      only_ng: {
        label: "只存 NG",
      },
      prefix: {
        label: "档名前綴",
      },
    },
    ports: {
      image: "影像",
      path: "路径",
    },
  },
  shading_correct: {
    label: "平场校正",
    description: "把打光不均拉平。除以同一组光下拍的均匀白板图像（平场），可先扣暗场；或用大核模糊从图像本身估背景。校正后固定阈值在整个视野都适用，而不是只有中央。",
    params: {
      mode: {
        label: "模式",
        options: { flat_field: "平场（白板参考）", dark_flat: "暗场＋白板参考", estimate: "从图像估背景" },
      },
      flat: { label: "白板参考", help: "工作分辨率下拍的均匀白板。上传成图像资产。" },
      dark: { label: "暗场参考", help: "盖上镜头盖拍的一张，去掉传感器固定偏移。" },
      blur_sigma: { label: "背景模糊", help: "背景估计的范围，要比想留下的特征大。" },
      target_level: { label: "目标亮度", help: "白板映到的灰度（均匀白板校正后就是这个值）；0 = 白板自己的平均。估背景时是输出的平均亮度；0 = 图像自己的平均。" },
    },
    ports: { image: "图像", mean_before: "校正前平均", mean_after: "校正后平均" },
  },
  shape_align: {
    label: "定位补正",
    description: "比較目前定位结果与教導时的参考位置，算出平移／旋转量（dx, dy, dθ），供 ROI 跟随使用。",
    params: {
      ref_x: {
        label: "参考 X",
        help: "教導时最佳匹配的中心 X（前端可一键帶入目前值）。",
      },
      ref_y: {
        label: "参考 Y",
      },
      ref_angle: {
        label: "参考角度",
      },
      use_angle: {
        label: "套用旋转",
        help: "关闭則 dθ 固定为 0，只做平移补正。",
      },
    },
    ports: {
      image: "影像",
      matches: "匹配",
      a: "目前 X",
      b: "目前 Y",
      c: "目前角度",
      transform: "变换",
    },
  },
  shape_match: {
    label: "形状比对",
    description: "以边缘的方向而不是灰度值找教导过的形状，所以光线变了、物体被遮住一部分、背景杂乱或零件转到任何角度都照样找得到。在资产页从一张良品建模；输出的比对结果接定位补正，用法与模板比对相同。",
    params: {
      model: { label: "形状模板", help: "用 POST /vision/assets/shape-model 或 manage.py shape_model 从图像资产建立（.npz 文件资产）。" },
      roi: { label: "搜索区域", help: "留空则整张图像。" },
      min_score: { label: "最低分数", help: "1 = 每个模型边缘都吻合。遮挡会等比例降分：遮住四分之一约 0.75。" },
      max_matches: { label: "最多比对数" },
      angle_start: { label: "起始角" },
      angle_extent: { label: "角度范围", help: "从起始角起搜索这么多度。范围越窄越快。" },
      scale_min: { label: "最小尺度", group: "尺度" },
      scale_max: { label: "最大尺度", help: "等于最小尺度 = 不搜尺度。", group: "尺度" },
      max_overlap: { label: "最大重叠", help: "两个结果的外框重叠超过此比例视为同一物体，弱的剔除。", group: "高级" },
      greediness: { label: "积极度", help: "多早放弃没希望的候选。1 最快但可能漏掉被遮住的件；0 为穷举。", group: "高级" },
      subpixel: { label: "亚像素精修", group: "高级" },
      polarity: { label: "极性", options: { use_polarity: "使用极性（暗底亮件就是暗底亮件）", ignore_polarity: "忽略极性（黑白反转的件也找）" }, group: "高级" },
      min_contrast: { label: "最小对比", help: "搜索图像中弱于此值的边缘不计；0 = 用模型自己的值。", group: "高级" },
    },
    ports: { image: "图像", roi: "搜索区域（动态）", found: "找到", not_found: "未找到", matches: "比对结果", count: "数量", best_x: "最佳 X", best_y: "最佳 Y", best_angle: "最佳角度", best_scale: "最佳尺度", best_score: "最佳分数" },
  },
  template_match: {
    label: "范本比对",
    description: "以正規化相关（NCC）在影像或搜尋范围内找范本；支援旋转搜尋、金字塔加速与次像素精修。角度以画面順时針为正（与 ROI／找直线相同）。",
    params: {
      template: {
        label: "范本影像",
        help: "上传的范本影像（灰阶比对）。",
      },
      roi: {
        label: "搜尋范围",
        help: "留空則搜尋整張影像。",
      },
      threshold: {
        label: "分数门槛",
        help: "NCC 分数 0~1，低于此值不算匹配。",
      },
      max_matches: {
        label: "最多匹配数",
      },
      angle_range: {
        label: "旋转范围 ±",
        help: "0 表示不做旋转搜尋。",
        group: "旋转",
      },
      angle_step: {
        label: "角度步进",
        group: "旋转",
      },
      pyramid: {
        label: "金字塔加速",
        help: "先在 1/4 缩图粗找，再在候选附近细找。范本很小时自動关闭。",
        group: "进阶",
      },
      subpixel: {
        label: "次像素精修",
        help: "位置以相关图 3×3 抛物线内插；有旋转搜尋时再以相鄰角度的分数内插角度（精度優于角度步进）。",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "搜尋范围（動态）",
      found: "找到",
      not_found: "沒找到",
      matches: "匹配",
      count: "数量",
      best_x: "最佳 X",
      best_y: "最佳 Y",
      best_score: "最佳分数",
      best_angle: "最佳角度",
    },
  },
  text_presence: {
    label: "有無印字",
    description: "区域内筆劃像素比例（自适应二值化後的前景比例）是否達门槛，用来判斷有無印字／标籤。",
    params: {
      roi: {
        label: "区域",
      },
      polarity: {
        label: "字色",
        options: {
          dark: "深色字",
          bright: "淺色字",
        },
      },
      block: {
        label: "自适应区块（奇数）",
        group: "进阶",
      },
      c: {
        label: "自适应常数 C",
        group: "进阶",
      },
      min_ratio: {
        label: "最小筆劃比例",
      },
      max_ratio: {
        label: "最大筆劃比例",
        help: "超过視为污損或整片色块。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      present: "有",
      absent: "無",
      ratio: "筆劃比例",
      is_present: "有印字",
      mask: "筆劃遮罩",
    },
  },
  threshold: {
    label: "门槛",
    description: "固定门槛、Otsu 自動、或自适应（区域）二值化；输出 0/255 遮罩。",
    params: {
      method: {
        label: "方法",
        options: {
          fixed: "固定门槛",
          otsu: "Otsu 自動",
          triangle: "Triangle 自動",
          adaptive_mean: "自适应（均值）",
          adaptive_gaussian: "自适应（高斯）",
          range: "灰阶范围",
        },
      },
      threshold: {
        label: "门槛",
      },
      low: {
        label: "下限",
      },
      high: {
        label: "上限",
      },
      block: {
        label: "区块大小（奇数）",
      },
      c: {
        label: "常数 C",
      },
      invert: {
        label: "反相（暗物件为前景）",
      },
    },
    ports: {
      image: "遮罩",
      threshold_used: "实际门槛",
    },
  },
  to_world: {
    label: "真实世界坐标",
    description: "把像素位置换成机器实际使用的坐标：台面上的毫米，或机械手要的数字。接入一个位置就读出 X 与 Y；长度与角度用同一份标定换算。",
    params: {
      calibration: { label: "标定资产", help: "在标定页做出来。一站教一次，所有流程跟着用。" },
      decimals: { label: "小数位数", group: "高级" },
    },
    ports: { points: "点", x: "X（像素）", y: "Y（像素）", value: "像素长度", angle: "角度（图像）", points_world: "点（真实世界）", length: "长度", scale: "比例" },
  },
  tolerance_judge: {
    label: "公差判定",
    description: "量测值是否在「标称 ＋上偏差／＋下偏差」内；判定连同标称值、上下限、图面出處一起寫进 run.outputs.tolerances，供 Cpk 与追溯。",
    params: {
      nominal: {
        label: "标称",
      },
      upper_tol: {
        label: "上偏差",
        help: "帶号；上限 = 标称 + 上偏差。",
      },
      lower_tol: {
        label: "下偏差",
        help: "帶号（通常为負）；下限 = 标称 + 下偏差。",
      },
      unit: {
        label: "单位",
      },
      spec_source: {
        label: "图面出處",
        help: "例如「图号 A-102 尺寸 ⌀12」。",
      },
      name: {
        label: "尺寸名称",
        help: "寫进 outputs.tolerances 的 name；留空用節点标籤。",
      },
    },
    ports: {
      value: "量测值",
      pass: "合格",
      fail: "超差",
      verdict: "判定",
      deviation: "偏差（值−标称）",
      in_spec: "合格",
      nominal: "标称",
      upper: "上限",
      lower: "下限",
      spec_source: "图面出處",
    },
  },
  wall_thickness: {
    label: "壁厚",
    description: "沿矩形／线段区域放多條卡尺，每條找「外缘→内缘」成对边缘，量壁厚（像素）并給最小／最大／平均。",
    params: {
      roi: {
        label: "区域",
        help: "长边沿著壁的走向；卡尺沿短边由「外」向「内」掃描（矩形上→下／左→右）。线段 ROI 以线为长边。",
      },
      polarity: {
        label: "外缘极性",
        help: "沿掃描方向遇到外缘时的灰阶变化；内缘自動取相反极性。",
        options: {
          any: "不限",
          dark_to_light: "暗 → 亮",
          light_to_dark: "亮 → 暗",
        },
      },
      edge_threshold: {
        label: "边缘门槛",
      },
      num_calipers: {
        label: "卡尺数",
      },
      max_thickness: {
        label: "最大壁厚",
        help: "0 表示不限；配对时内缘距外缘不得超过此值。",
      },
      band: {
        label: "线段掃描宽",
        help: "ROI 为线段时，取线兩侧共此宽度做平均。",
        group: "进阶",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      thickness: "壁厚（平均）",
      min: "最小",
      max: "最大",
      mean: "平均",
      std: "标準差",
      count: "有效卡尺数",
      profile: "各卡尺壁厚",
      pairs: "边缘对",
    },
  },
  undistort: {
    label: "镜头校正",
    description: "用标定资产把镜头弯掉的部分拉直。广角或近距离时边角的直线会往外拱；在校正后的图像上测量，数值就不会随视野位置漂移。",
    params: {
      calibration: { label: "标定资产", help: "在标定页用几张标定板照片做出来。同一份标定也驱动「真实世界坐标」。" },
      alpha: { label: "保留画面", help: "0 = 裁掉所有黑边（放大到全部都是有效像素）；1 = 保留整个画面（角落补黑）；中间值保留该比例。" },
      keep_edges: { label: "保留整个画面", help: "旧流程用：等于 alpha 1。alpha 大于 0 时忽略。", group: "高级" },
    },
    ports: { image: "图像", mm_per_pixel: "每像素 mm" },
  },
  warp_perspective: {
    label: "透視校正",
    description: "把画面上的四边形区域攤平成矩形：斜拍的板面／标籤校正後再量测。",
    params: {
      roi: {
        label: "来源四边形",
        help: "画 4 个点（多于 4 点取前 4 点）。",
      },
      width: {
        label: "输出宽",
        help: "0 = 依边长自動。",
      },
      height: {
        label: "输出高",
      },
    },
    ports: {
      image: "影像",
    },
  },
  write_modbus: {
    label: "寫入 Modbus",
    description: "依对映表把判定、具名输出或输入埠的值寫到 Modbus TCP／上位機连线。寫入失敗預设只记警告不讓 run 失敗。",
    params: {
      connection: {
        label: "连线",
        help: "填通訊连线的名称（设定頁「连线」建立；也可填 id）。",
      },
      mapping: {
        label: "对映表",
        help: "阵列，每项 {\"src\": 来源, \"address\": 位址, \"dtype\"?: bool|int|float, \"scale\"?: 倍率, \"offset\"?: 加值, \"value\"?: 常数}。src：judge（OK→1 / NG→0）、具名输出名称、或本節点输入埠的 v0、v1…。位址：modbus 用 coil:10 / holding:100 / holding:100:float32 / holding:100:int32；tcp_client 用范本欄位名；dio_sim 用通道名。",
      },
      on_error: {
        label: "寫入失敗时",
        options: {
          warn: "降级：记警告，run 照常",
          fail: "讓 run 失敗",
        },
      },
      timeout_s: {
        label: "逾时（秒）",
        help: "0 = 用连线设定的逾时。",
        group: "进阶",
      },
    },
    ports: {
      values: "值",
      written: "寫入筆数",
      ok: "成功",
    },
  },
  yolo_classify: {
    label: "YOLO 分类",
    description: "以 ultralytics YOLO-cls 模型判斷区域屬于哪一类；最高分类别分数達门槛（且在合格类别内）走 pass。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_name: {
        label: "底模名称",
        help: "官方名称（第一次使用自動下载）或本機 .pt 路径；只在沒选模型资产时使用。",
      },
      imgsz: {
        label: "推論尺寸",
        help: "与訓練时一致最準。",
        options: {
          "224": "224（建议）",
        },
      },
      device: {
        label: "装置",
        group: "进阶",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、记憶体更省。",
        group: "进阶",
      },
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      threshold: {
        label: "分数门槛",
      },
      pass_labels: {
        label: "合格类别",
        help: "逗号分隔；不为空时，最高分类别需在此清单内才 pass。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      pass: "合格",
      fail: "不良",
      label: "类别",
      score: "分数",
      index: "索引",
    },
  },
  yolo_detect: {
    label: "YOLO 物件偵测",
    description: "以 ultralytics YOLO 模型（官方底模或教導頁訓練的 .pt）找物件并回框、类别与分数；GPU 自動使用。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_name: {
        label: "底模名称",
        help: "官方名称（第一次使用自動下载）或本機 .pt 路径；只在沒选模型资产时使用。",
      },
      imgsz: {
        label: "推論尺寸",
        help: "与訓練时一致最準。",
        options: {
          "640": "640（建议）",
        },
      },
      device: {
        label: "装置",
        group: "进阶",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、记憶体更省。",
        group: "进阶",
      },
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心门槛",
      },
      iou: {
        label: "NMS IoU",
        group: "进阶",
      },
      max_count: {
        label: "最多输出",
        group: "进阶",
      },
      filter_labels: {
        label: "只保留类别",
        help: "逗号分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多数量",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      detections: "偵测结果",
      count: "数量",
      matches: "匹配（含 cx, cy）",
      labels: "类别列表",
    },
  },
  yolo_obb: {
    label: "YOLO 旋转框（OBB）",
    description: "以 ultralytics YOLO-obb 模型找物件并回旋转矩形（中心、宽高、角度）与四角座标；适合倾斜摆放的工件。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_name: {
        label: "底模名称",
        help: "官方名称（第一次使用自動下载）或本機 .pt 路径；只在沒选模型资产时使用。",
      },
      imgsz: {
        label: "推論尺寸",
        help: "与訓練时一致最準。",
        options: {
          "640": "640（建议）",
        },
      },
      device: {
        label: "装置",
        group: "进阶",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、记憶体更省。",
        group: "进阶",
      },
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心门槛",
      },
      iou: {
        label: "NMS IoU",
        group: "进阶",
      },
      max_count: {
        label: "最多输出",
        group: "进阶",
      },
      filter_labels: {
        label: "只保留类别",
        help: "逗号分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多数量",
        help: "0 表示不限。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      count: "数量",
      matches: "旋转框（cx, cy, w, h, angle）",
      contours: "四角轮廓",
      labels: "类别列表",
    },
  },
  yolo_pose: {
    label: "YOLO 姿态（关键点）",
    description: "以 ultralytics YOLO-pose 模型找物件并回每个物件的关键点座标与信心（COCO 人体 17 点或自訂关键点）；可做位置／姿勢检查。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_name: {
        label: "底模名称",
        help: "官方名称（第一次使用自動下载）或本機 .pt 路径；只在沒选模型资产时使用。",
      },
      imgsz: {
        label: "推論尺寸",
        help: "与訓練时一致最準。",
        options: {
          "640": "640（建议）",
        },
      },
      device: {
        label: "装置",
        group: "进阶",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、记憶体更省。",
        group: "进阶",
      },
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心门槛",
      },
      iou: {
        label: "NMS IoU",
        group: "进阶",
      },
      max_count: {
        label: "最多输出",
        group: "进阶",
      },
      filter_labels: {
        label: "只保留类别",
        help: "逗号分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多数量",
        help: "0 表示不限。",
        group: "判定",
      },
      kpt_conf: {
        label: "关键点信心门槛",
        help: "低于门槛的关键点不画、座标仍输出（conf 附在每点）。",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      count: "数量",
      matches: "物件框",
      keypoints: "关键点",
      labels: "类别列表",
    },
  },
  yolo_segment: {
    label: "YOLO 实例分割",
    description: "以 ultralytics YOLO-seg 模型找出每个物件的轮廓、类别与面积；输出聯合遮罩与轮廓給後续量测。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_name: {
        label: "底模名称",
        help: "官方名称（第一次使用自動下载）或本機 .pt 路径；只在沒选模型资产时使用。",
      },
      imgsz: {
        label: "推論尺寸",
        help: "与訓練时一致最準。",
        options: {
          "640": "640（建议）",
        },
      },
      device: {
        label: "装置",
        group: "进阶",
        options: {
          auto: "自動（有 GPU 就用）",
        },
      },
      half: {
        label: "半精度（FP16）",
        help: "只在 GPU 生效，更快、记憶体更省。",
        group: "进阶",
      },
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      conf: {
        label: "信心门槛",
      },
      iou: {
        label: "NMS IoU",
        group: "进阶",
      },
      max_count: {
        label: "最多输出",
        group: "进阶",
      },
      filter_labels: {
        label: "只保留类别",
        help: "逗号分隔；留空全部保留。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多数量",
        help: "0 表示不限。",
        group: "判定",
      },
      min_area: {
        label: "最小面积",
        help: "小于此面积的实例略过。",
        group: "判定",
      },
    },
    ports: {
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      count: "数量",
      matches: "实例",
      mask: "聯合遮罩",
      contours: "轮廓",
      labels: "类别列表",
    },
  },
}
