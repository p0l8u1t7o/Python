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
  trigger_flow: {
    label: '触发流程',
    description: '从当前执行中启动另一条流程。异步只排队后继续；同步会在安全容量下等待子流程结果。',
    params: {
      target_flow_id: { label: '目标流程', help: '选择下一条要执行的流程；图中保存的是流程 id。' },
      mode: { label: '模式', options: { async: '异步：排队后继续', sync: '同步：等待结果' } },
      timeout_ms: { label: '同步超时' },
      pass_outputs: { label: '传递具名输出' },
      pass_image: { label: '传递图像' },
    },
    ports: { image: '图像', run_id: '执行 ID', judge: '判定', ok: 'OK', ng: 'NG', failed: '失败' },
  },
  call_flow: {
    label: '调用流程',
    description: '在当前执行中同行程执行另一条流程；不排队、不建立执行记录，也不累计统计。',
    params: {
      target_flow_id: { label: '目标流程', help: '选择要在当前执行内调用的流程；图中保存的是流程 id。' },
      prefix: { label: '输出前缀', help: '子流程具名输出并回当前执行时，加在每个名称前方。' },
      pass_outputs: { label: '传递具名输出' },
      pass_image: { label: '传递图像' },
      timeout_ms: { label: '超时', help: '0 表示使用父流程剩余时间。' },
    },
    ports: { image: '图像', judge: '判定', ok: 'OK', ng: 'NG', failed: '失败', duration_ms: '耗时', outputs: '子流程输出' },
  },
  for_each: {
    label: '逐项执行',
    description: '对每个匹配结果、区域或图像调用同一条子流程，并汇总逐项判定。',
    params: {
      target_flow_id: { label: '目标流程' },
      source: { label: '项目来源', options: { auto: '自动', regions: '区域', matches: '匹配结果', images: '图像' } },
      max_items: { label: '最多项目' },
      on_error: { label: '项目失败时', options: { continue: '继续', stop: '停止' } },
      pass_outputs: { label: '传递具名输出' },
      timeout_ms: { label: '超时', help: '0 表示使用父流程剩余时间。' },
    },
    ports: {
      image: '图像', regions: '区域', matches: '匹配结果', images: '图像',
      count: '数量', ok_count: 'OK 数量', ng_count: 'NG 数量', items: '逐项结果', all_ok: '全部 OK',
      ok: '全部 OK', ng: '有 NG',
    },
  },
  tile: {
    label: '图像切片',
    description: '按行数与列数产生矩形区域，可加重叠；只做几何切片，不处理像素。',
    params: {
      rows: { label: '行数' },
      cols: { label: '列数' },
      overlap: { label: '重叠量', help: '可用基础切片比例或像素量。' },
      overlap_mode: { label: '重叠模式', options: { ratio: '比例', pixels: '像素' } },
      include_remainder: { label: '包含余数' },
      width: { label: '宽度' },
      height: { label: '高度' },
    },
    ports: { image: '图像', regions: '区域', count: '数量' },
  },
  register_detect: {
    label: '注册式检测',
    description: '使用少量目标裁切图查找、计数或检查零件有无，无需训练。加入相似物的排除图可减少误判。',
    params: {
      registrations: { label: '注册图', help: '每张裁切图包含一个目标并保留少许背景，建议少于十张。' },
      negatives: { label: '排除图', help: '选填：不得计入的相似物裁切图。' },
      roi: { label: '搜索区域' },
      mode: { label: '模式', options: { detect: '检测', count: '计数', presence: '有无' } },
      scales: { label: '搜索尺寸', help: '以逗号分隔相对尺寸，例如 0.8,1.0,1.25。' },
      angle_range: { label: '角度范围', help: '从零度向两侧搜索，0 表示不旋转。' },
      angle_step: { label: '角度间距', help: '相邻搜索角度的间距，0 表示不旋转。' },
      min_similarity: { label: '最低相似度' },
      max_count: { label: '最多结果数' },
      nms_overlap: { label: '最大重叠比例' },
      min_size: { label: '最小边长', help: '两边皆须达到此下限，0 表示不限。' },
      max_size: { label: '最大边长', help: '任一边皆不得超过此上限，0 表示不限。' },
      min_count: { label: '合格数量下限' },
      max_count_ok: { label: '合格数量上限' },
      expected: { label: '预期状态', options: { present: '有', absent: '无' } },
      device: { label: '运算设备', options: { auto: '自动', cpu: '处理器', cuda: '图形处理器' } },
      backbone_path: { label: '特征模型文件', help: '内部测试用，留空使用已安装的特征模型。' },
    },
    ports: {
      image: '图像', roi: '搜索区域', found: '已找到', not_found: '未找到', ok: '合格', ng: '不合格',
      matches: '匹配结果', count: '数量', best_score: '最佳相似度', best_x: '最佳 X', best_y: '最佳 Y', present: '存在',
    },
  },
  coordinate: {
    "label": "自订坐标系",
    "description": "由原点与角度、两点或有向直线定义原点及 X 轴；frame 输出可接至真实世界坐标工具。角度正值为画面顺时针。",
    "params": {
      "mode": {
        "label": "定义方式",
        "options": {
          "point_angle": "原点与角度",
          "two_points": "两点",
          "line": "有向直线"
        }
      },
      "origin_x": {
        "label": "原点 X",
        "help": "未连接 point 埠时，与原点 Y 一起使用。"
      },
      "origin_y": {
        "label": "原点 Y"
      },
      "axis_angle": {
        "label": "X 轴角度",
        "help": "画面顺时针为正；未连接 angle 埠时使用。"
      }
    },
    "ports": {
      "point": "原点",
      "angle": "X 轴角度",
      "point2": "X 轴上的另一点",
      "line": "有向直线",
      "frame": "坐标系",
      "origin_x": "原点 X",
      "origin_y": "原点 Y",
      "found": "已建立",
      "not_found": "未找到"
    }
  },
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
  frame_accumulate: {
    label: "????",
    description: "???????????????????????",
    params: {
      mode: { label: "??", options: { mean: "??", max: "??", min: "??" } },
      count: { label: "??" },
      emit: { label: "??", options: { ready: "??????", always: "?????" } },
      reset: { label: "??" },
    },
    ports: { image: "??", reset: "??", frames: "?????", ready: "???", waiting: "???" },
  },
  previous_image: {
    label: "?????",
    description: "???????????????????????",
    params: { node: { label: "?? ID" }, port: { label: "????" }, k: { label: "?????" } },
    ports: { image: "??", found: "??", not_found: "???" },
  },
  apply_mask: {
    label: "套用遮罩",
    description: "只保留遮罩为 255 的像素（其余设为指定灰阶）。",
    params: {
      side: { label: "????", options: { outside: "???", inside: "???" } },
      fill_value: { label: "??" },
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
          min: "???",
          max: "???",
          mean: "??",
          weighted: "??",
          invert: "反相 A",
        },
      },
      weight: { label: "A ??" },
    },
    ports: {
      image: "影像",
    },
  },
  paste_back: {
    label: "????",
    description: "??????????????????????",
    params: {
      x: { label: "X" },
      y: { label: "Y" },
      region: { label: "??" },
      mode: { label: "??", options: { replace: "??", blend: "??", masked: "????" } },
      alpha: { label: "Alpha" },
    },
    ports: { image: "??", patch: "??", region: "??", mask: "??" },
  },
  barcode: {
    label: "條碼 / QR",
    description: "解码 QR code、Data Matrix、Aztec、PDF417 与一维条码（EAN/UPC/Code 128/Code 39 等）。",
    params: {
      roi: {
        label: "区域",
        help: "留空則整張影像。",
      },
      types: {
        label: "类型",
        options: {
          all: "全部码制",
          "2d": "二维码（QR、Data Matrix、Aztec、PDF417）",
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
          hysteresis: "双门槛（高种子＋低成长）",
          soft: "软门槛加权",
          none: "输入已是遮罩（非 0 即前景）",
        },
      },
      threshold: {
        label: "门槛",
      },
      threshold_low: {
        label: "低门槛",
        help: "双门槛会从高门槛种子往相连的低门槛像素成长。",
      },
      soft_width: {
        label: "软门槛宽度",
        help: "门槛附近以 0～1 加权，面积可能是小数。",
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
          xy: "阅读顺序（先行后列）",
          circularity: "圆形度（高→低）",
          perimeter: "周长（大到小）",
          width: "宽度（大到小）",
          height: "高度（大到小）",
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
  blob_label: {
    label: "标签图 Blob",
    description: "对单通道标签图逐类别做 blob 分析，输出每个区块的类别名称、类别编号、面积、中心、外框、周长与最大内接矩形。可接 dl_segment 的 class_map；若接 ai_segment 的 mask，请用 255 当单一类别。",
    params: {
      roi: {
        label: "区域",
        help: "留空代表整张标签图。",
      },
      classes: {
        label: "类别表",
        help: "一行一个「编号:名称」，例如 1:scratch。",
      },
      min_area: {
        label: "最小面积",
      },
      max_area: {
        label: "最大面积",
        help: "0 代表不限制。",
      },
      max_count: {
        label: "最多结果",
      },
      sort_by: {
        label: "排序",
        options: {
          area: "面积（大到小）",
          x: "X（左到右）",
          y: "Y（上到下）",
          xy: "阅读顺序（先行后列）",
          circularity: "圆形度（高到低）",
          perimeter: "周长（大到小）",
          width: "宽度（大到小）",
          height: "高度（大到小）",
        },
      },
      ignore_label: {
        label: "忽略标签",
        help: "通常 0 是背景。",
      },
      min_count: {
        label: "合格最少数量",
        group: "判定",
      },
      max_count_ok: {
        label: "合格最多数量",
        help: "0 代表不限制。",
        group: "判定",
      },
    },
    ports: {
      labels: "标签图",
      roi: "区域（动态）",
      ok: "通过",
      ng: "失败",
      blobs: "Blob 列表",
      counts: "各类数量",
      count: "总数",
      contours: "轮廓",
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
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
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
      max_results: {
        label: "最多结果",
        help: "返回排序后前 N 个边缘对候选；单一宽度与边缘坐标仍取第一笔。",
      },
      sort_by: {
        label: "排序依据",
        help: "分数＝对比加权，扣掉位置误差与宽度误差的加权罚分。",
        options: { score: "分数", position: "位置", contrast: "对比" },
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
      expected_position: {
        label: "期望位置",
        help: "沿扫描方向的期望候选中心（px）；0 表示不使用位置项。",
      },
      position_weight: {
        label: "位置权重",
        help: "每偏离期望位置 1 px 扣多少分。",
      },
      contrast_weight: {
        label: "对比权重",
        help: "每 1 灰阶/px 边缘对比加多少分；所有权重为 0 时分数退回对比。",
      },
      width_weight: {
        label: "宽度权重",
        help: "每偏离期望宽度 1 px 扣多少分。",
      },
      smoothing: {
        label: "剖面平滑",
        group: "进阶",
      },
    },
    ports: { width_world: "宽度（物理量）", edge1_x_world: "边缘 1 X（世界）", edge1_y_world: "边缘 1 Y（世界）", edge2_x_world: "边缘 2 X（世界）", edge2_y_world: "边缘 2 Y（世界）", unit: "单位",
      image: "影像",
      roi: "区域（動态）",
      width: "宽",
      edge1_x: "边缘1 X",
      edge1_y: "边缘1 Y",
      edge2_x: "边缘2 X",
      edge2_y: "边缘2 Y",
      edges: "边缘候选",
      profile: "剖面",
    },
  },
  peak_search: {
    label: "峰值搜索",
    description: "沿矩形区域长边取灰阶剖面，找亮峰、暗峰或两者的中心位置。",
    params: {
      roi: { label: "区域", help: "沿长边方向扫描，短边方向取平均以抗噪。" },
      polarity: { label: "峰值极性", options: { bright: "亮峰", dark: "暗峰", both: "两者" } },
      min_prominence: { label: "最小突出量" },
      min_distance: { label: "最小距离" },
      smoothing: { label: "剖面平滑", group: "高级" },
      max_results: { label: "最多结果" },
      sort_by: { label: "排序依据", options: { position: "位置", prominence: "突出量", value: "灰阶值" } },
    },
    ports: {
      image: "图像", roi: "区域（动态）", found: "找到", not_found: "未找到",
      peaks: "峰值清单", count: "数量", first_x: "第一峰 X", first_y: "第一峰 Y",
      first_position: "第一峰位置", profile: "灰阶剖面",
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
  multi_light_grab: {
    label: "多光源取像",
    description: "按步骤切换光源并连续取像，输出影像序列、前四张影像与光源角度。",
    params: {
      source: { label: "影像来源", help: "capture 来源会要求 fresh frame；非 capture 来源会重复同一张影像并警告。" },
      connection: { label: "光源连接" },
      steps: { label: "打光步骤", help: "每行 channel,brightness[,exposure_us][,azimuth][,elevation]，最多 8 步。" },
      settle_ms: { label: "稳定等待", help: "0 表示使用光源连接的 lead time。" },
      after: { label: "取像后", options: { off: "全部关灯", keep: "保留最后一步", restore: "恢复原亮度" } },
      on_timeout: { label: "超时处理", options: { error: "报错", ng: "标记 NG 并走 timeout 分支" } },
      timeout_ms: { label: "超时" },
      required: { label: "连接必须存在" },
    },
    ports: {
      images: "影像列表",
      image: "影像 1",
      image_1: "影像 2",
      image_2: "影像 3",
      image_3: "影像 4",
      azimuths: "方位角",
      elevations: "仰角",
      count: "张数",
      duration_ms: "耗时",
      timeout: "超时",
    },
  },
  multi_light_fuse: {
    label: "多光源融合",
    description: "把多张不同打光影像按逐像素规则合成，用于去反光、阴影增强、方向增强或平均。",
    params: {
      mode: { label: "模式", options: { reflection: "去反光", shadow: "阴影差", direction: "方向增强", mean: "平均" } },
      azimuths: { label: "方位角", help: "direction 模式每张影像的光源角度。" },
      angle: { label: "强调方向" },
      halo_removal: { label: "去光晕", help: "只作用于去反光模式。" },
      halo_size: { label: "光晕尺寸" },
      normalize: { label: "正规化输出" },
    },
    ports: {
      images: "影像列表",
      image: "影像",
      image_1: "影像 2",
      image_2: "影像 3",
      image_3: "影像 4",
      azimuths: "方位角",
      gradient: "梯度",
    },
  },
  barcode_grade: {
    label: "条码品质分级",
    description: "像验证器一样替二维或一维条码评级：Data Matrix 与 QR 走 ISO/IEC 15415、线性码走 ISO/IEC 15416、金属直接打标走 AIM DPM。每个分项（对比、调制、固定图形损伤、轴向与格点不均匀、未用错误更正、缺陷、可解码度）各自给分，总评 A 到 F，并判定是否达到最低等级。以 8 位灰阶当反射率，数值对得上验证器的量级但不是认证。",
    params: {
      roi: { label: "区域", help: "符号与它的静区；留空则整张图像。" },
      standard: { label: "标准", help: "线性码一律以 15416 分级；DPM 以格对比与格调制取代 15415 的对比与调制。", options: { iso15415: "ISO/IEC 15415（2D：Data Matrix、QR）", iso15416: "ISO/IEC 15416（1D：EAN、UPC、Code 128、Code 39）", aim_dpm: "AIM DPM（ISO/IEC TR 29158，金属直接打标）" } },
      symbology: { label: "码制", options: { auto: "不限", datamatrix: "Data Matrix", qr: "QR Code", ean_upc: "EAN / UPC", code128: "Code 128", code39: "Code 39" } },
      aperture: { label: "孔径", help: "合成孔径直径；0＝模块大小的 80%（DPM 为 50%）。" },
      min_grade: { label: "最低等级", help: "总评要达到此等级或更好才合格。", options: { A: "A（4.0）", B: "B（3.0）", C: "C（2.0）", D: "D（1.0）", F: "F（0.0）" } },
      dpm_filter: { label: "DPM 前置滤波", help: "AIM DPM 允许测量前先做图像处理。", options: { none: "无", median: "中值 3×3" }, group: "高级" },
    },
    ports: { image: "图像", roi: "区域（动态）", pass: "合格", fail: "不合格", grade: "等级", grade_value: "等级分数", params: "分项", text: "内容", symbology: "码制", decoded: "已解码" },
  },
  variable_get: {
    label: "读取变量",
    description: "读出流程或站台变量：料号、计数、上一件的测量值。尚未存储时用默认值。",
    params: {
      name: { label: "变量", help: "英数字与下划线。" },
      scope: { label: "范围", help: "只限这条流程，或整站所有流程共用。", options: { flow: "这条流程", station: "整个站台" } },
      default: { label: "默认值", help: "尚未存储前使用。数字仍是数字；true 与 false 是布尔。" },
    },
    ports: { value: "值", number: "数值", text: "文字", found: "已设定" },
  },
  variable_set: {
    label: "存储变量",
    description: "把值存进流程或站台变量：累计数量、记住最大值、把料号传给下一条流程。试执行只写在覆盖层，不动真正的计数。",
    params: {
      name: { label: "变量" },
      scope: { label: "范围", options: { flow: "这条流程", station: "整个站台" } },
      mode: { label: "方式", options: { set: "存储这个值", add: "加上去（计数、总和）", max: "保留最大", min: "保留最小" } },
    },
    ports: { value: "值", previous: "先前的值" },
  },
  switch: {
    label: "多路分支",
    description: "一个值一条路：一个料号、一个配方码、一个等级各走各的。案例一行一个，这一步就长出对应数量的输出；都不符的走默认分支。",
    params: {
      cases: { label: "案例", help: "一行一个，由上往下比，第一个相符的胜出。比对选数字时，一行可以是单一数值（12）或范围（10-20）。每一行都会多一个输出端口，另外还有默认分支。" },
      match: {
        label: "比对",
        options: {
          exact: "值刚好是这个",
          contains: "值包含这个",
          prefix: "值开头是这个",
          regex: "样式（正则表达式）",
          number: "数字或范围（10-20）",
        },
      },
      case_sensitive: { label: "区分大小写" },
    },
    ports: { value: "值", default: "都不符", index: "第几个案例", matched: "有相符", },
  },
  string_match: {
    label: "文字比对",
    description: "拿一段文字跟清单比对：这个条码是不是我们的、日期码在不在允许清单里、读到的内容有没有包含料号。走相符／不相符分支，并回报是哪一笔。",
    params: {
      list: { label: "允许的值", help: "一行一个。比对选样式时，每一行都是一个正则表达式。" },
      match: {
        label: "比对",
        options: { exact: "文字刚好是这个", contains: "文字包含这个", prefix: "文字开头是这个", regex: "样式（正则表达式）" },
      },
      case_sensitive: { label: "区分大小写" },
      invert: { label: "相符时反而算失败", help: "用在「这些字不准出现」的清单。" },
      on_false: { label: "不成立时", options: { route: "只分流（不判定）", reject: "判 NG（此步骤不合格）" } },
      ng_label: { label: "NG 标签", help: "此步骤判 NG 时写入 run.outputs.judge_label，让自动化系统知道是哪个检查触发。" },
    },
    ports: { text: "文字", found: "相符", not_found: "不相符", index: "第几笔", matched: "相符的那一笔" },
  },
  parse_message: {
    label: "拆解消息",
    description: "把一段文字拆成具名值：条码内容 LOT12345|2026-09-08|A7、文字识别读到的一行，或上位机随触发送来的消息。每个字段都会变成具名输出，后面的步骤可以拿去判断、比对或回送。",
    params: {
      mode: { label: "排列方式", options: { delimiter: "以字符分隔", regex: "以样式（正则表达式）", fixed: "固定字节位置" } },
      separator: { label: "分隔字符", help: "一个或多个字符。制表符请输入 \\t。" },
      pattern: { label: "样式", help: "例如 LOT(?P<lot>\\d+)\\s+(?P<qty>\\d+)。具名分组会填进同名字段，否则依序填。" },
      fields: {
        label: "字段",
        help: "一行一个字段，依序对应。只写名称就取下一段文字；加冒号指定类型（name:int、name:float、name:bool、name:hex）。要跳着取就写位置，从 0 起算（name:int:3）。固定字节位置改写字节范围（name:int:0-1）；设备的字节顺序相反时再加顺序（name:float:2-5:DCBA）。设备送 1234 代表 12.34 就加 *0.01。",
      },
      publish: { label: "并入回复", help: "每个字段也成为具名输出，HTTP 与 TCP 的回复就会带上。" },
      prefix: { label: "名称前缀", help: "加在每个字段名称前面，用来区分两段消息。" },
      on_missing: { label: "字段取不到值时", options: { pass: "留空并继续", fail: "让步骤失败" } },
    },
    ports: { text: "文字", matched: "相符", not_matched: "未相符", fields: "字段", count: "取到几个", first: "第一个字段" },
  },
  format_text: {
    label: "格式化回复",
    description: "用模板组一行纯文本给读不懂 JSON 的设备：{名字} 依序取具名输出、触发参数（lot、sn）、本节点输入 a～d，另有 {run_id} 与 {station}；支持 {width:.2f} 这类格式。设备端用 TCP 的 fmt= 或 HTTP 的 format 取这一行。",
    params: {
      template: { label: "模板", help: "例如 OK;{diameter:.2f};{lot}。\\n 与 \\t 会转成真正的控制字符。" },
      name: { label: "输出名称", help: "回复以此名称带这一行；TCP 指令的 fmt 或 HTTP 的 format 指定它。" },
      ending: { label: "行尾", options: { none: "无", lf: "换行（\\n）", crlf: "回车换行（\\r\\n）", cr: "回车（\\r）" } },
      missing: { label: "名字没有值时", options: { blank: "留空", keep: "保留名字原样", fail: "让步骤失败" } },
      each_template: { label: "每笔模板", help: "接 items 时，每一笔各套一次。可用 {index} 与 {centroid[0]:.2f}。" },
      join: { label: "串接文字", help: "接 items 时用来串接每一行；\\n 会转成真正换行。" },
    },
    ports: { a: "a", b: "b", c: "c", d: "d", items: "逐笔清单", text: "文字", lines: "文字行" },
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
  color_segment: {
    label: "多色分割",
    description: "一次按多个 HSV 或 Lab 色域切成整数标签图，并输出各色面积与类别名称。",
    params: {
      segments: { label: "分割段", help: "一行一段：名称:H下,H上,S下,S上,V下,V上。HSV 的 H 下界大于上界时会跨过 0/180，常用于红色。" },
      space: { label: "色彩空间", options: { hsv: "HSV", lab: "Lab" } },
      min_area: { label: "最小面积" },
      smooth: { label: "平滑" },
      roi: { label: "区域", help: "留空代表整张图像。" },
    },
    ports: {
      image: "图像",
      roi: "区域（动态）",
      labels: "标签图",
      areas: "面积",
      classes: "类别",
    },
  },
  color_classify: {
    label: "样本颜色分类",
    description: "把区域内颜色直方图与固定图像样本比对，返回最接近的样本名称与相似度。",
    params: {
      samples: { label: "样本" },
      space: { label: "色彩空间", options: { hsv: "HSV", lab: "Lab" } },
      bins: { label: "分箱数" },
      metric: { label: "比对方式", options: { histogram_intersection: "直方图交集", earth_mover: "搬移距离" } },
      min_similarity: { label: "最低相似度" },
      roi: { label: "区域", help: "留空代表整张图像。" },
    },
    ports: {
      image: "图像",
      roi: "区域（动态）",
      ok: "通过",
      ng: "低于相似度",
      label: "标签",
      similarity: "相似度",
      ranking: "排名",
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
          merge_rgb: "合成 R/G/B 灰阶",
          yuv_y: "YUV Y 通道",
          yuv_u: "YUV U 通道",
          yuv_v: "YUV V 通道",
          hsi_h: "HSI H 通道",
          hsi_s: "HSI S 通道",
          hsi_i: "HSI I 通道",
          gray_weighted: "加权灰阶",
        },
      },
      weight_r: { label: "R 权重" },
      weight_g: { label: "G 权重" },
      weight_b: { label: "B 权重" },
    },
    ports: {
      image: "影像",
      r: "R 灰阶",
      g: "G 灰阶",
      b: "B 灰阶",
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
      template_image: "模板图",
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
  boxes_merge: {
    label: "合并框",
    description: "依重叠比例或中心距离合并重复的框，可限定同标签才合并。",
    params: {
      mode: { label: "模式", options: { iou: "重叠比例", centre_distance: "中心距离" } },
      threshold: { label: "门槛" },
      same_label_only: { label: "只合并同标签" },
      keep: { label: "保留数据来源", options: { highest_score: "最高分", largest: "最大框", first: "第一个" } },
    },
    ports: { matches: "框清单", values: "值清单", image: "图像（显示用）", count: "数量" },
  },
  boxes_overlap: {
    label: "框重叠",
    description: "比较两组框，返回每个 A 框与 B 框的最大重叠率与对应索引。",
    params: {
      metric: { label: "重叠算法", options: { iou: "交并比", overlap_a: "重叠面积 / A 面积" } },
      min_overlap: { label: "最小重叠率" },
      mode: { label: "OK 条件", options: { any: "有重叠", none: "无重叠" } },
    },
    ports: { matches: "框清单", matches_b: "B 框清单", image: "图像（显示用）", ok: "OK", ng: "NG", count: "数量", pairs: "重叠配对" },
  },
  list_filter: {
    label: "清单筛选",
    description: "依数值、文字或字段条件筛选值清单或框清单。",
    params: {
      field: { label: "字段" },
      op: {
        label: "条件",
        options: { gt: "大于", ge: "大于等于", lt: "小于", le: "小于等于", eq: "等于", ne: "不等于", between: "介于", in: "在清单内", regex: "符合文字规则", nonempty: "非空" },
      },
      value: { label: "值" },
      value2: { label: "第二值" },
    },
    ports: { values: "值清单", matches: "框清单", count: "数量", removed: "移除数", indices: "原始索引" },
  },
  list_classify: {
    label: "清单分类",
    description: "依每行分类范围替值清单或框清单加上类别。",
    params: {
      field: { label: "字段" },
      classes: { label: "分类规则", help: "一行一类：名称:下限,上限；下限包含、上限不包含，空白代表无界。" },
    },
    ports: { values: "值清单", matches: "框清单", labels: "类别清单", counts: "类别数量", dominant: "最多类别" },
  },
  list_pick: {
    label: "清单取值",
    description: "从值清单、框清单或点清单取出第一笔、最后一笔、指定索引或最接近坐标的一笔。",
    params: {
      by: { label: "取法", options: { index: "指定索引", first: "第一笔", last: "最后一笔", min: "最小值", max: "最大值", nearest: "最近坐标" } },
      index: { label: "索引" },
      field: { label: "字段" },
      x: { label: "目标 X" },
      y: { label: "目标 Y" },
    },
    ports: { values: "值清单", matches: "框清单", points: "点清单", image: "图像（显示用）", found: "找到", not_found: "未找到", value: "值", index: "索引" },
  },
  boxes_filter: {
    label: "筛选框",
    description: "依尺寸、面积、长宽比、分数、标签与位置区域留下合格的框。",
    params: {
      min_width: { label: "最小宽度", group: "尺寸" },
      max_width: { label: "最大宽度", group: "尺寸" },
      min_height: { label: "最小高度", group: "尺寸" },
      max_height: { label: "最大高度", group: "尺寸" },
      min_area: { label: "最小面积", group: "尺寸" },
      max_area: { label: "最大面积", group: "尺寸" },
      min_aspect: { label: "最小长宽比", group: "形状" },
      max_aspect: { label: "最大长宽比", group: "形状" },
      min_score: { label: "最低分数" },
      max_score: { label: "最高分数" },
      labels: { label: "标签", help: "逗号分隔或一行一个；留空全部保留。" },
      roi: { label: "位置区域" },
      roi_mode: { label: "区域模式", options: { inside: "区域内", outside: "区域外" } },
    },
    ports: { matches: "框清单", values: "值清单", roi: "位置区域（动态）", image: "图像（显示用）", count: "数量", removed: "移除数" },
  },
  edge_filter: {
    label: "边界排除",
    description: "依上、下、左、右边距排除碰到画面边缘的物件；有多边形时用多边形极值，否则用框。",
    params: {
      margin_top: { label: "上边距", help: "0 表示不检查上边。" },
      margin_bottom: { label: "下边距", help: "0 表示不检查下边。" },
      margin_left: { label: "左边距", help: "0 表示不检查左边。" },
      margin_right: { label: "右边距", help: "0 表示不检查右边。" },
    },
    ports: { matches: "保留物件", removed: "排除物件", count: "保留数", image: "图像（显示用）" },
  },
  array_correct: {
    label: "阵列补齐",
    description: "由已找到的框推回 rows × cols 网格，回报缺格并补上估计框。",
    params: {
      rows: { label: "列数" },
      cols: { label: "栏数" },
      tolerance: { label: "容许距离", help: "小于 1 表示 pitch 比例；大于等于 1 表示像素。" },
    },
    ports: { matches: "框清单", values: "值清单", image: "图像（显示用）", ok: "完整", ng: "缺件", missing: "缺格", count: "数量" },
  },
  list_sort: {
    label: "清单排序",
    description: "排序值清单或框清单，可依坐标阅读顺序、分数或标签排列。",
    params: {
      by: { label: "排序依据", options: { value: "值", x: "X", y: "Y", xy: "阅读顺序", score: "分数", label: "标签" } },
      descending: { label: "递减" },
    },
    ports: { matches: "框清单", values: "值清单", count: "数量", first: "第一笔" },
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
  edge_defect: {
    label: "边缘缺陷",
    description: "整条边一次检查完，不是只量一个地方：沿着边（直的或圆的）布一排卡尺，凡是偏离理想边的那几段都会被指出来，并说明是哪一种不良。缺口与毛刺是「一整段偏进去或偏出来」，崩掉是「这一段根本找不到边」，错位是「相邻两处忽然接不上」；成对模式还会直接检查宽度。每个缺陷都带外框、沿边长度与面积，所以要判最严重的还是判数量都可以。",
    params: {
      roi: { label: "区域", help: "直边画矩形（长边沿着边），圆边画圆或圆环。上游接进来的线或圆优先于这里。" },
      mode: { label: "每把卡尺找什么", options: { single: "一条边", pair: "一对边（肋、沟、缝）" } },
      polarity: { label: "边缘极性", options: { any: "不限", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      pair_polarity: { label: "两边之间", options: { any: "都可以", bright: "比较亮", dark: "比较暗" } },
      calipers: { label: "卡尺数", help: "沿边检查几个地方。越多找得到越小的缺陷，也越慢。" },
      search: { label: "搜索范围", help: "每把卡尺在理想边的两侧各找多远。" },
      caliper_width: { label: "卡尺宽度", help: "沿着边平均，用来降噪。" },
      edge_threshold: { label: "边缘阈值" },
      baseline: {
        label: "理想边是",
        help: "拟合适合会移动的工件；「就是区域本身」适合治具上边必须在固定位置的场合。",
        options: { fit: "由找到的边拟合（直线或圆）", median: "滑动中位数（跟着缓弯走）", reference: "就是区域或接进来的形状" },
      },
      window: { label: "中位数窗口" },
      threshold: { label: "偏离超过", help: "离理想边超过这么多就算缺陷。" },
      min_width: { label: "至少连续几把卡尺", help: "挡掉单把卡尺的噪声。" },
      direction: { label: "哪一侧算", options: { both: "两侧都算", inward: "只算少料", outward: "只算多料" } },
      fracture_run: { label: "连续几把找不到边算断裂", help: "卡尺完全找不到边，通常表示那一段的边不见了。0＝不判断裂。" },
      step_threshold: { label: "相邻两处落差超过", help: "从这一把到下一把忽然跳了：错位或崩角。0＝不判台阶差。" },
      width_min: { label: "宽度不得小于", help: "0＝不检查。" },
      width_max: { label: "宽度不得大于", help: "0＝不检查。" },
      max_defects: { label: "超过几个才算不良", help: "0＝有缺陷就不良。" },
      smoothing: { label: "剖面平滑" },
      edge_select: { label: "选边", options: { strongest: "最强", first: "第一个", last: "最后一个" } },
    },
    ports: {
      image: "图像", roi: "区域（动态）", line: "理想直线", circle: "理想圆",
      ok: "没有缺陷", defect: "有缺陷", count: "几个", defects: "缺陷清单",
      max_deviation: "最大偏离", max_size: "最长的缺陷", total_area: "总面积",
      points: "边缘点", deviation: "偏离序列", widths: "宽度序列",
    },
  },
  edge_model_defect: {
    label: "轮廓模型缺陷",
    description: "把良品外轮廓教成点集模型，每次沿着那条任意轮廓布法向卡尺；向内连续偏移是少料或缺口，向外连续偏移是多料或毛刺，连续找不到边是崩角或断裂。",
    params: {
      roi: { label: "教学区域", help: "只在自动从参考图像教学时使用。留空则用整张参考图像。" },
      model: { label: "轮廓模型", help: "JSON：{version:1, image_size:[宽,高], closed:true, points:[[x,y],...]}。点是教学图像坐标；闭合模型的正偏移代表向外。" },
      reference: { label: "参考图像", help: "选填良品图像。模型为空时，会用第一张参考图像在本次执行自动教学轮廓。" },
      calipers: { label: "卡尺数", help: "沿轮廓检查几个地方。越多找得到越小的缺陷，也越慢。" },
      search: { label: "搜索范围", help: "每把法向卡尺跨过模型轮廓搜索的总距离。" },
      caliper_width: { label: "卡尺宽度", help: "沿轮廓切线方向平均，用来降噪。" },
      edge_threshold: { label: "边缘阈值" },
      polarity: { label: "边缘极性", options: { any: "不限", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      edge_select: { label: "选边", options: { strongest: "最强", first: "第一个", last: "最后一个" } },
      threshold: { label: "偏离超过", help: "离教学轮廓超过这么多就算缺陷。" },
      min_width: { label: "至少连续几把卡尺", help: "挡掉单把卡尺的噪声。" },
      direction: { label: "哪一侧算", options: { both: "两侧都算", inward: "只算少料", outward: "只算多料" } },
      fracture_run: { label: "连续几把找不到边算断裂", help: "卡尺完全找不到边，通常表示那一段的边不见了。0＝不判断裂。" },
      step_threshold: { label: "相邻两处落差超过", help: "从这一把到下一把忽然跳了。0＝不判阶差。" },
      max_defects: { label: "超过几个才算不良", help: "0＝有缺陷就不良。" },
      teach_simplify: { label: "教学简化量", help: "模型为空且用参考图像教学时的多边形近似公差。" },
      smoothing: { label: "剖面平滑" },
    },
    ports: {
      image: "图像", roi: "教学区域（动态）",
      ok: "没有缺陷", defect: "有缺陷", count: "几个", defects: "缺陷列表",
      max_deviation: "最大偏离", points: "边缘点", deviations: "偏离序列", missing: "找不到边的索引",
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
      template_image: "良品图",
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
    label: "距离",
    description: "两个东西之间的距离（像素）。多半是两点，但 A 与 B 也可以是线或圆：孔到边的间隙、两孔之间的净距、凸台到基准线多远。点＝{x,y} 或 [x,y]（也可分别接四个数值），线＝{x1,y1,x2,y2}，圆＝{cx,cy,r}。",
    params: {
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
      mode: {
        label: "测量",
        help: "后三种在 A 或 B 是圆或线时才有差别：图面标的通常是孔的边缘，不是圆心。",
        options: {
          euclid: "直线距离",
          dx: "X 方向距离",
          dy: "Y 方向距离",
          nearest: "最近的两点（边到边）",
          farthest: "最远的两点",
          centers: "中心到中心",
        },
      },
    },
    ports: { distance_world: "距离（物理量）", unit: "单位",
      image: "图像",
      a: "A（点／线／圆）",
      b: "B（点／线／圆）",
      distance: "距离",
    },
  },
  dl_retrieval: {
    label: '参考库比对',
    description: '将影像与已保存的参考库比较，返回最接近的类别。',
    params: {
      model: { label: '参考库', help: '用于比对的已保存参考库。' },
      roi: { label: 'ROI', help: '要比对的区域；留空代表全图。' },
      topk: { label: '投票数', help: '用几张最接近的参考图决定类别。' },
      min_similarity: { label: '最低相似度', help: '低于此值时走 not_matched。' },
      expected: { label: '预期类别', help: '选填；填入后只有相符才是 ok。' },
      device: { label: '执行设备', options: { auto: '自动', cpu: 'CPU', cuda: 'CUDA', directml: 'DirectML' } },
      backbone_path: { label: '参考比对文件', help: '测试用内部文件覆盖。' },
    },
    ports: {
      label: '类别',
      similarity: '相似度',
      confidence: '信心',
      topk: '最接近列表',
      ok: 'OK',
      ng: 'NG',
      not_matched: '未符合',
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
        help: "以 0~1 为单位；检测网络通常填 0。",
        group: "前處理",
      },
      std: {
        help: "检测网络通常填 1。",
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
    description: "以 ONNX 偵测模型（检测网络风格输出）找物件；含 letterbox 前處理与 NMS。",
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
        help: "以 0~1 为单位；检测网络通常填 0。",
        group: "前處理",
      },
      std: {
        help: "检测网络通常填 1。",
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
    description: "以实例分割 ONNX 模型找出每个物件的轮廓与类别（含 letterbox 前處理、NMS 与 mask 合成）。可在平台的深度學習頁教導。",
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
        help: "以 0~1 为单位；检测网络通常填 0。",
        group: "前處理",
      },
      std: {
        help: "检测网络通常填 1。",
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
        help: "以 0~1 为单位；检测网络通常填 0。",
        group: "前處理",
      },
      std: {
        help: "检测网络通常填 1。",
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
  surface_filter: {
    label: "表面缺陷滤波",
    description: "在本身就有纹理的表面上把划伤、发丝与细裂纹挑出来。一般的边缘滤波连纹理一起找；这一个沿着缺陷方向平均、跨着缺陷方向微分，换几个角度取最强的，所以细长的痕迹会浮出来、纹路不会。结果拿去二值化，或直接用最强响应判定。",
    params: {
      polarity: { label: "要找的", options: { dark: "比表面暗（常见的划伤）", bright: "比表面亮", any: "都可以" } },
      width: { label: "缺陷宽度", help: "痕迹大概几个像素宽。太小纹理会穿过来，太大细划伤会被吃掉。" },
      length: { label: "缺陷长度", help: "痕迹延伸多长。越长把表面平均掉越多，但短的痕迹也会跟着不见。" },
      directions: { label: "方向数", help: "在半圈里试几个角度。多了只是慢一点、好一点点；8 个大多够用。" },
      gain: { label: "增益", help: "响应变成图像之前乘上去的倍数。调到划伤看得清楚、表面仍然暗为止。" },
      offset: { label: "偏移", help: "每个像素都加上这个值。" },
      roi: { label: "区域", help: "只滤这一块，其余原样传下去。" },
    },
    ports: { image: "图像", region: "区域（动态）", max_response: "最强响应", mean_response: "平均响应" },
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
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
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
    ports: { cx_world: "圆心 X（世界）", cy_world: "圆心 Y（世界）", r_world: "半径（物理量）", diameter_world: "直径（物理量）", unit: "单位",
      image: "影像",
      roi: "区域（動态）",
      found: "找到",
      not_found: "沒找到",
      cx: "中心 X",
      cy: "中心 Y",
      r: "半径",
      diameter: "直径",
      points: "边缘点",
      score: "分数",
      circle: "圆",
    },
  },
  find_rectangle: {
    label: "找矩形",
    description: "一次找出矩形工件的四条边：卡尺从区域的四边各自往内扫，每条边拟合一条线，四个角就是线的交点。回中心、宽、高与角度，找到的矩形也直接当区域传下去——后面那一步就能在工件落在哪里就量哪里。",
    params: {
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
      roi: { label: "区域", help: "画得比工件大一点；卡尺会从四边往内扫。" },
      polarity: { label: "边缘极性", help: "由外往内扫时的灰阶变化。" },
      edge_threshold: { label: "边缘阈值" },
      calipers: { label: "每边卡尺数" },
      search: { label: "搜索深度", help: "每把卡尺往里面扫多深，以区域的比例计。够碰到边就好，太深会扫到对面那条边。" },
      caliper_width: { label: "卡尺宽度", help: "沿着边平均，用来降噪。" },
      edge_select: { label: "选边", options: { strongest: "最强", first: "第一个（最外）", last: "最后一个（最内）" } },
      ransac: { label: "RANSAC 去离群" },
      ransac_tol: { label: "RANSAC 容差" },
      smoothing: { label: "剖面平滑" },
    },
    ports: { cx_world: "中心 X（世界）", cy_world: "中心 Y（世界）", width_world: "宽度（物理量）", height_world: "高度（物理量）", angle_world: "角度（世界）", unit: "单位", image: "图像", roi: "区域（动态）", found: "找到", not_found: "没找到", cx: "中心 X", cy: "中心 Y", width: "宽", height: "高", angle: "角度", rect: "矩形", corners: "角点", lines: "四条边" },
  },
  find_quadrilateral: {
    label: "四边求角点",
    description: "把四条边变成一个四边形：依序（绕工件一圈）接四个找线的结果，算出四个角、四条边长与两条对角线。工件不是矩形时用它——锥形垫、梯形、斜着看的工件。",
    params: {},
    ports: { image: "图像", a: "边 1", b: "边 2", c: "边 3", d: "边 4", found: "找到", not_found: "没找到", corners: "角点", cx: "中心 X", cy: "中心 Y", sides: "边长", diagonals: "对角线", area: "面积" },
  },
  find_parallel_lines: {
    label: "找一对边",
    description: "一次找出沟、肋或缝的两侧：每把卡尺找的是一对边而不是一条边，两侧各拟合一条线，并回报每把卡尺量到的宽度与整体宽度。中线也一起给——后面要量的通常就是它。",
    params: {
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
      roi: { label: "区域", help: "长边沿着这一对边，卡尺跨着短边扫。" },
      pair_polarity: { label: "两边之间", options: { any: "都可以", bright: "比周围亮", dark: "比周围暗" } },
      pair_mode: { label: "取哪一对", options: { widest: "最宽的一对", narrowest: "最窄的一对", first_last: "最外面的一对", strongest: "最强的一对", expected: "最接近预期宽度" } },
      expected_width: { label: "预期宽度" },
      edge_threshold: { label: "边缘阈值" },
      calipers: { label: "卡尺数" },
      caliper_width: { label: "卡尺宽度" },
      ransac: { label: "RANSAC 去离群" },
      ransac_tol: { label: "RANSAC 容差" },
      smoothing: { label: "剖面平滑" },
    },
    ports: { distance_world: "宽度（物理量）", min_distance_world: "最窄宽度（物理量）", max_distance_world: "最宽宽度（物理量）", angle_world: "角度（世界）", unit: "单位", image: "图像", roi: "区域（动态）", found: "找到", not_found: "没找到", distance: "宽度", min_distance: "最窄", max_distance: "最宽", angle: "角度", line_a: "边 A", line_b: "边 B", center_line: "中线", widths: "各处宽度", found_count: "找到成对的卡尺数" },
  },
  find_lines_multi: {
    label: "找多条线",
    description: "找出区域里每一条直边，不只一条：连接器外壳的几个面、格线、一排脚。先取边缘点，拟合最强的一条线之后把它的点拿掉，再找下一条，直到没有值得称为线的东西为止。",
    params: {
      roi: { label: "区域" },
      max_lines: { label: "最多几条" },
      edge_threshold: { label: "边缘阈值", help: "灰阶梯度多大才算边。" },
      min_points: { label: "每条线的点数", help: "点数不到这个数就不算一条线。" },
      tolerance: { label: "拟合容差" },
      min_length: { label: "最短长度" },
      angle_filter: { label: "只要接近这个角度的线" },
      angle_tolerance: { label: "角度容差", help: "0＝不限角度。" },
    },
    ports: { image: "图像", roi: "区域（动态）", found: "找到", not_found: "没找到", count: "几条", lines: "线", angles: "角度", first: "第一条", points: "边缘点" },
  },
  find_circles_matrix: {
    label: "找圆阵列",
    description: "一次找出整排的孔、球或垫：区域依行列切成格子，每格找一个圆。回报每个圆心与半径、哪几格是空的，以及格距——球栅阵列、连接器、钻孔板要的就是这个答案。",
    params: {
      roi: { label: "区域", help: "把整个阵列框起来；会平均切成格子。" },
      rows: { label: "行数" },
      cols: { label: "列数" },
      polarity: { label: "边缘极性", help: "由格子中心往外扫时的灰阶变化。" },
      edge_threshold: { label: "边缘阈值" },
      min_radius: { label: "最小半径" },
      max_radius: { label: "最大半径", help: "0＝到格子的一半。" },
      num_rays: { label: "扫描线数" },
      smoothing: { label: "剖面平滑" },
    },
    ports: { image: "图像", roi: "区域（动态）", found: "全部找到", not_found: "有缺", count: "找到几个", expected: "预期几个", missing: "缺的格子", centers: "圆心", radii: "半径", mean_radius: "平均半径", pitch_x: "横向格距", pitch_y: "纵向格距" },
  },
  find_line: {
    label: "找直线",
    description: "在矩形区域内放多條垂直于长边的卡尺掃描线找边缘点，再拟合直线（可 RANSAC）。",
    params: {
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
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
      gap_tolerant: {
        label: "边是断续的",
        help: "虚线或中断的边：线的两端取「真的找到边」的范围，而不是区域的两端。拟合本身本来就会跳过缺口。",
        group: "进阶",
      },
    },
    ports: { x1_world: "起点 X（世界）", y1_world: "起点 Y（世界）", x2_world: "终点 X（世界）", y2_world: "终点 Y（世界）", angle_world: "角度（世界）", unit: "单位",
      image: "图像",
      roi: "区域（动态）",
      found: "找到",
      not_found: "没找到",
      angle: "夹角",
      line: "线",
      points: "边缘点",
      coverage: "覆盖率",
    },
  },
  fit_arc: {
    label: "圆弧拟合",
    description: "在区域内找边缘点并以最小平方（可 RANSAC）拟合圆弧：R 角、杯口圆角的半径与圆心。",
    params: {
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
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
    ports: { cx_world: "圆心 X（世界）", cy_world: "圆心 Y（世界）", radius_world: "半径（物理量）", start_angle_world: "起始角度（世界）", end_angle_world: "结束角度（世界）", unit: "单位",
      image: "影像",
      roi: "区域（動态）",
      radius: "半径",
      cx: "中心 X",
      cy: "中心 Y",
      residual_rms: "残差 RMS",
      points: "边缘点",
      start_angle: "起角",
      end_angle: "終角",
      circle: "圆",
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
  image_fixture: {
    label: "图像跟随",
    description: "依定位补正的结果把图像转回示教时的姿态，后面每一步看到的工件就永远在同一个地方。要沿用一条在单一样品上调好的流程，这是最省事的做法：没有区域需要跟随，示教好的模板照样比得到。",
    params: {
      border: { label: "边缘填色", help: "图像转过之后角落会空出来，这里决定填什么。", options: { black: "黑", white: "白", replicate: "最近的像素" } },
      smooth: { label: "平滑像素", help: "开：插值，看起来对、量起来也准。关：取最近的像素，标记与掩膜不会糊掉。" },
    },
    ports: { image: "图像", transform: "位置修正", dx: "dx", dy: "dy", dtheta: "角度差" },
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
  points_merge: {
    label: "点集合",
    description: "把几个步骤找到的点并成一组，一次拟合或一次测量就涵盖全部：四把卡尺量同一条边的边缘点、整排孔的圆心。每个输入吃一个点或一串点。",
    params: {
      unique: { label: "去掉重复", help: "距离小于 0.1 像素的点算同一个。" },
    },
    ports: { a: "A", b: "B", c: "C", d: "D", image: "图像", points: "点", count: "数量", cx: "中心 X", cy: "中心 Y" },
  },
  geometry: {
    label: "几何计算",
    description: "算出图面上标了、图像上却看不到的几何：两线交点、点到线垂距、与某条线平行或垂直的线、两边的中线、角平分线、三点定圆、绕一点旋转。线与点接找线／找圆／卡尺的输出；线与圆输出可以直接接给下一步。",
    params: {
      calibration: { label: "标定资产", group: "高级", help: "选填；选了标定就多出 *_world 与 unit 埠，优先使用机构映射。长度使用量测位置的面积等效比例，角度单位为度。" },
      mode: {
        label: "计算",
        options: {
          intersect: "两线交点",
          point_line: "点到线垂距",
          midpoint: "两点中点",
          project: "点投影到线",
          line_2pts: "两点连成的线",
          parallel: "与这条线平行的线",
          perpendicular: "与这条线垂直的线",
          perp_bisector: "两点的中垂线",
          median: "两线的中线",
          bisector: "角平分线",
          circle_3pts: "三点定圆",
          rotate: "绕一点旋转",
          offset: "平移点集或比对结果",
        },
      },
      offset: { label: "偏移", help: "没接要通过的点时，把线往旁边平移多少。正值是线方向的右手边。" },
      angle: { label: "角度", help: "画面顺时针为正，与平台其他角度同向。" },
      offset_x: { label: "偏移 X", help: "未接 offset_x 埠时使用。" },
      offset_y: { label: "偏移 Y", help: "未接 offset_y 埠时使用。" },
      sign: { label: "方向", options: { add: "加回", subtract: "扣除" } },
    },
    ports: { x_world: "X（世界）", y_world: "Y（世界）", distance_world: "距离或半径（物理量）", angle_world: "角度（世界）", unit: "单位",
      a: "A（线／点）",
      b: "B（线／点）",
      c: "C（点）",
      distance: "距离",
      angle: "角度",
      line: "线",
      circle: "圆",
      points: "点集",
      matches: "比对结果",
      count: "数量",
      offset_x: "偏移 X",
      offset_y: "偏移 Y",
    },
  },
  grayscale: {
    label: "灰阶",
    description: "彩色转灰阶；已是灰阶則直通。",
    ports: {
      image: "影像",
    },
  },
  sharpness: {
    label: "清晰度",
    description: "评估 ROI 内的对焦与震动模糊程度，可设置上下限并输出噪声估计。",
    params: {
      roi: {
        label: "区域",
        help: "留空时使用整张图像。",
      },
      method: {
        label: "方法",
        help: "Laplacian variance 最通用；Gradient energy 适合稳定边缘；Autocorrelation drop 对随机噪声较不敏感。",
        options: {
          laplacian: "Laplacian 方差",
          gradient: "梯度能量",
          autocorrelation: "自相关落差",
        },
      },
      normalize: {
        label: "按对比归一化",
        help: "开启后，分数是每像素响应能量除以 ROI 灰阶方差：Laplacian 为 px^-4，gradient 为 px^-2，autocorrelation 为无量纲相关落差。",
      },
      min_score: {
        label: "最低分数",
        help: "0 表示不判下限；分数低于此值走 NG。",
      },
      max_score: {
        label: "最高分数",
        help: "0 表示不判上限；分数高于此值走 NG，可用于拦截噪声或过度锐化造成的虚高分数。",
      },
      noise_estimate: {
        label: "估计噪声",
        help: "输出稳健高频噪声水平；低光源会让噪声抬高清晰度分数。",
      },
    },
    ports: {
      image: "图像",
      roi: "区域（动态）",
      score: "分数",
      noise: "噪声",
      method: "方法",
      ok: "合格",
      ng: "超出范围",
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
    description: "以梯度法在区域内找多个圆。",
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
      on_false: { label: "不成立时", options: { route: "只分流（不判定）", reject: "判 NG（此步骤不合格）" } },
      ng_label: { label: "NG 标签", help: "此步骤判 NG 时写入 run.outputs.judge_label，让自动化系统知道是哪个检查触发。" },
    },
    ports: {
      value: "值",
      result: "结果",
    },
  },
  fixed_image: {
    label: "固定图像",
    description: "以上传到此步骤的图片取代相机：一张，或多张每次执行轮流取用。图片跟着流程保存，从模板或上传图片建立的流程在哪里都能执行；也用来把参考图（模板、良品、白参考）透过图片输入端口交给需要的工具。",
    params: {
      images: {
        label: "图片",
        help: "上传一张或多张图片；图片会跟着流程保存。",
      },
      mode: {
        label: "取哪一张",
        options: {
          cycle: "每次执行取下一张（含试执行）",
          fixed: "固定取第 N 张",
        },
      },
      index: {
        label: "序号",
        help: "1 = 第一张。",
      },
      role: {
        label: "角色",
        options: {
          acquire: "待检图像（API 送图、批次测试或重跑时以送来的图取代）",
          reference: "供其他工具使用的参考图（模板、良品、白参考）：永不取代",
        },
      },
      convert: {
        label: "色彩",
        options: {
          keep: "维持上传时的样子",
          gray: "灰度",
          bgr: "彩色（3 通道）",
        },
      },
    },
    ports: {
      image: "图像",
      index: "图片序号",
      name: "图片名称",
      count: "图片张数",
      width: "宽",
      height: "高",
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
      exposure_us: {
        label: "曝光",
        help: "空白或 0 不改相机曝光。",
      },
      gain_db: {
        label: "增益",
        help: "空白或 0 不改相机增益。",
      },
    },
    ports: {
      image: "影像",
      width: "宽",
      height: "高",
      applied: "已套用相机设置",
    },
  },
  stereo_grab: {
    label: "立体成对取像",
    description: "从左右两个影像来源取一组立体影像；两者都是同一台采集端的 capture 来源时，会同时送出 GRAB。",
    params: {
      left: { label: "左影像来源" },
      right: { label: "右影像来源" },
      timeout_ms: { label: "超时" },
      max_dt_ms: { label: "最大左右时间差" },
      on_timeout: { label: "超时处理", options: { error: "报错", ng: "标记 NG 并走超时分支" } },
    },
    ports: {
      image: "左影像",
      image_right: "右影像",
      dt_ms: "左右时间差",
      captured_at: "采集时间",
      timeout: "超时",
    },
  },
  stereo_depth: {
    label: "双视野量高度",
    description: "用双相机标定与左右影像量分割物件顶面距离，并依带面基准换算机构 Z。",
    params: {
      calibration: { label: "双视野标定" },
      min_disparity: { label: "最小视差" },
      num_disparities: { label: "视差范围" },
      block_size: { label: "区块大小" },
      scale: { label: "ROI 缩放" },
      use_wls: { label: "WLS 滤波" },
      preprocess: { label: "前处理", options: { none: "无", clahe: "CLAHE", sobel: "Sobel", laplacian: "Laplacian" } },
      stat: { label: "统计", options: { mean: "平均", median: "中位数" } },
      min_valid_ratio: { label: "最小有效比例" },
      motion_compensation: { label: "时间差补偿" },
    },
    ports: {
      image: "左影像",
      image_right: "右影像",
      matches: "物件",
      dt_ms: "左右时间差",
      z: "Z",
      ok: "OK",
      ng: "NG",
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
      on_false: { label: "不成立时", options: { route: "只分流（不判定）", reject: "判 NG（此步骤不合格）" } },
      ng_label: { label: "NG 标签", help: "此步骤判 NG 时写入 run.outputs.judge_label，让自动化系统知道是哪个检查触发。" },
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
          normalize_ratio: "百分位拉伸",
          normalize_std: "平均／标准差归一化",
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
      gamma: { label: "Gamma" },
      low_percent: { label: "低百分位" },
      high_percent: { label: "高百分位" },
      target_mean: { label: "目标平均" },
      target_std: { label: "目标标准差" },
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
      pattern: { label: "位置样板", help: "N=数字、A=英文字母、X=任意；其他字符必须完全相同。留空不检查。" },
      confusables: { label: "易混字替换", help: "一行一条 从:到；只在替换后符合该位置样板时才套用。" },
      preprocess: { label: "预处理", options: { auto: "自动（对比拉伸与去噪）", none: "无" } },
      segmentation: { label: "切分（教导字体）", options: { projection: "投影（字符间空隙）", components: "连通域", fixed: "固定间距（已知字数）" }, group: "教导字体" },
      char_count: { label: "字数（固定间距）", help: "固定间距切分把墨迹范围等分成这么多格。", group: "教导字体" },
    },
    ports: { image: "图像", roi: "文字区域（动态）", found: "找到", not_found: "未找到", text: "文字", corrected: "修正后文字", pattern_ok: "样板通过", corrections: "修正明细", items: "行", confidence: "置信度", count: "行数" },
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
    description: "把画好的形状变成区域输出，让画布上能有第二、第三个区域——交给区域组合的排除区与加量区域。另外会把形状的中心、线与圆一起送出去，所以在画布上画一条基准线就能量每个孔到它的距离（那条线是图面给的，图像上找不到）。本身不影响图像。",
    params: {
      roi: { label: "形状", help: "任何形状：矩形、旋转矩形、圆、椭圆、圆环、多边形。" },
    },
    ports: { image: "图像（显示用）", region: "区域", point: "中心", line: "线", circle: "圆" },
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
  set_light: {
    label: "设置光源",
    description: "设置光源控制器某一通道的亮度、开灯或关灯。连接缺失或送出失败默认降级，流程继续。",
    params: {
      connection: { label: "连接", help: "在「外部集成 > 设备连接」创建的光源控制器连接名称。" },
      channel: { label: "通道" },
      value: { label: "亮度", help: "0 到连接设置的 value_max。换料号常要调光，因此列为现场教学参数。" },
      mode: { label: "模式", options: { brightness: "设置亮度", on: "开灯", off: "关灯" } },
      required: { label: "必要", help: "送不出光源命令时让 run 失败；默认关闭，通讯问题只降级。" },
      timeout_s: { label: "超时（秒）", group: "进阶" },
    },
    ports: { ok: "成功" },
  },
  io_output: {
    label: "I/O 输出",
    description: "依当前 OK/NG 判定写出电平或非阻塞脉冲，可写 Modbus 地址或光源控制器通道。",
    params: {
      connection: { label: "连接", help: "Modbus 或光源控制器连接名称；填 id 也可以。" },
      address: { label: "地址", help: "Modbus 用 coil:0 这类 area:offset[:dtype]；光源控制器填通道号。" },
      on_when: { label: "何时输出", options: { ok: "OK", ng: "NG", always: "总是" } },
      pulse_ms: { label: "脉冲", help: "0 维持电平；大于 0 时由背景计时器复位，不会让流程线程 sleep。" },
      invert: { label: "反相" },
      required: { label: "必要", help: "输出失败时让 run 失败；默认关闭，通讯问题只降级。" },
      timeout_s: { label: "超时（秒）", group: "进阶" },
    },
    ports: { status: "判定", ok: "成功", active: "输出电平" },
  },
  camera_io: {
    label: "相机 I/O",
    description: "依当前 OK/NG 判定写出撷取端相机的输出线；脉冲由撷取端复位，宽度不受网络延迟影响。",
    params: {
      source: { label: "影像来源" },
      line: { label: "输出线" },
      on_when: { label: "何时输出", options: { ok: "OK", ng: "NG", always: "总是" } },
      pulse_ms: { label: "脉冲", help: "0 维持电平；大于 0 时由撷取端背景计时器复位。" },
      invert: { label: "反相" },
      required: { label: "必要", help: "写入相机输出失败时让 run 失败；默认关闭，通讯问题只降级。" },
      timeout_s: { label: "超时（秒）", group: "进阶" },
    },
    ports: { status: "判定", ok: "成功", active: "输出电平" },
  },
  camera_set: {
    label: "相机设置",
    description: "写入撷取端相机特征，并可加载或保存 user set。",
    params: {
      source: { label: "影像来源" },
      values: { label: "参数", help: "一行一个 name=value，例如 exposure_us=5000。" },
      user_set: { label: "User set", options: { none: "不使用", load: "套参数前加载", save: "套参数后保存" } },
      user_set_name: { label: "User set 名称" },
      required: { label: "必要", help: "完全连不上相机时让 run 失败；默认关闭，通讯问题只降级。" },
      timeout_s: { label: "超时（秒）", group: "进阶" },
    },
    ports: { ok: "成功", applied: "已套用", errors: "错误" },
  },
  write_log: {
    label: "写入记录",
    description: "把具名输出写成一列 CSV 或一行 TXT，背景写入 DATA_DIR/file_outputs 下的相对资料夹。",
    params: {
      path: { label: "相对路径", help: "位于 DATA_DIR/file_outputs 下；绝对路径与 .. 会被拒绝。" },
      format: { label: "格式", options: { csv: "CSV", txt: "TXT" } },
      fields: { label: "字段", help: "一行一栏。可填字段名，或使用 {width:.2f} 这类样板。" },
      header: { label: "写入表头" },
      filename: { label: "文件名", help: "可使用 {station}、{date}、{lot}、{run_id:.8}。" },
      daily_folder: { label: "按日资料夹" },
      rotate_mb: { label: "依大小轮替", group: "轮替" },
      rotate_rows: { label: "依行数轮替", group: "轮替" },
      encoding: { label: "编码", group: "进阶" },
    },
    ports: { a: "a", b: "b", c: "c", d: "d", path: "路径", queued: "已排入队列" },
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
      condition: {
        label: "保存条件",
        options: { all: "全部", ok: "只存 OK", ng: "只存 NG" },
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
      filename: {
        label: "文件名",
        help: "可使用 {station}、{date}、{lot}、{run_id:.8}。",
      },
      daily_folder: {
        label: "按日资料夹",
      },
      jpeg_quality: {
        label: "JPEG 质量",
        group: "进阶",
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
  align_offset: {
    label: "对位偏移",
    description: "把示教时的位置与现在的位置一比，算出机构要修正多少。定位补正是给区域跟随用的，这一颗是给机构走的：多了取料点补偿，选了手眼标定还会直接给机构坐标。",
    params: {
      mode: {
        label: "怎么比",
        options: {
          point: "一个点加角度",
          rectify: "单点校正",
          point_set: "好几组对应点",
          grab: "取料点补偿",
          line: "线的中点与方向",
        },
      },
      ref_x: { label: "示教 X", help: "示教时工件所在的位置（试执行一次就可以把现在的值填进来）。" },
      ref_y: { label: "示教 Y" },
      ref_angle: { label: "示教角度", help: "角度正值＝画面顺时针。" },
      ref_points: { label: "示教点集", help: "2～8 组 [x, y]，顺序要与现在的点集一致。只解旋转与平移，不含缩放。" },
      grab_x: { label: "示教取料 X", help: "示教时手臂抓在工件的哪一点。工件转了，这一点会跟着转。" },
      grab_y: { label: "示教取料 Y" },
      calibration: { label: "手眼标定", help: "选填。选了才会多给机构坐标；没选就只有像素。" },
    },
    ports: {
      image: "图像", matches: "定位结果", a: "当前 X", b: "当前 Y", c: "当前角度",
      points: "当前点集", line: "当前直线",
      dx: "X 偏移", dy: "Y 偏移", dtheta: "角度偏移", transform: "位置修正",
      abs_x: "绝对 X（像素）", abs_y: "绝对 Y（像素）", abs_angle: "绝对角度（图像）",
      world_x: "机构 X", world_y: "机构 Y", world_angle: "机构角度",
      found: "算出来了", not_found: "没有当前位置",
    },
  },
  map_points: {
    label: "相机映射",
    description: "使用含 mapping 区块的标定资产，把 A 相机坐标换到 B 相机坐标；可反向使用。",
    params: {
      calibration: { label: "映射标定", help: "必填；需由标定页的相机映射模式创建，资产内要有 mapping 区块。" },
      direction: { label: "方向", options: { forward: "正向", inverse: "反向" } },
    },
    ports: {
      image: "影像",
      points: "点集",
      matches: "定位结果",
      x: "X",
      y: "Y",
      count: "数量",
    },
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
      model_source: { label: "模型来源", help: "使用已上传的形状模型资产，或在内存合成内建基准 Mark 模型。", options: { asset: "资产", builtin: "内建 Mark" } },
      model: { label: "形状模板", help: "用 POST /vision/assets/shape-model 或 manage.py shape_model 从图像资产建立（.npz 文件资产）。" },
      builtin_shape: { label: "内建图形", help: "十字、空心方框或实心圆 Mark。", options: { cross: "十字", square_outline: "空心方框", disc: "实心圆" } },
      builtin_size: { label: "Mark 尺寸", help: "外径或边长，单位为像素。" },
      builtin_line_width: { label: "线宽", help: "十字与空心方框的笔画宽度。" },
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
  track_objects: {
    label: "目标追踪",
    description: "在连续执行中用预测位置与最近邻配对，替匹配框维持稳定 ID。试执行与沙盒只写变量覆盖层，不会推进正式追踪状态。",
    params: {
      state_name: { label: "状态变量", help: "保存追踪状态的流程变量；多个追踪器请用不同名称。" },
      max_distance: { label: "最大距离", help: "检测中心离预测位置超过此距离时，建立新目标。" },
      max_missing: { label: "最大丢失次数", help: "连续丢失超过此值才淘汰目标。" },
      reset: { label: "重设", help: "本次帧处理前清除已保存的追踪状态。" },
      algorithm: { label: "配对方式", options: { platform: "平台配对", bytetrack: "外部追踪辅助" } },
      confirm_frames: { label: "确认影格数", help: "同一物件连续追到几帧后才输出新确认。" },
      motion: { label: "运动模型", options: { free: "自由移动", linear: "线性输送带" } },
      line_mode: { label: "计数线", options: { none: "无", points: "两点" }, group: "计数" },
      count_line: { label: "线段点", help: "两点格式：[[x1,y1],[x2,y2]]。由负侧跨到正侧算 count_in。", group: "计数" },
    },
    ports: {
      matches: "匹配", boxes: "方框", count_line: "计数线", reset: "重设", image: "图像（显示用）",
      ok: "追踪中", not_found: "无目标", tracks: "追踪目标", count: "数量", new_count: "新增数", lost_count: "淘汰数",
      count_in: "进入计数", count_out: "离开计数", new_confirmed: "新确认", confirmed: "已确认",
    },
  },
  template_match: {
    label: "范本比对",
    description: "以正規化相关（NCC）在影像或搜尋范围内找范本；支援旋转搜尋、金字塔加速与次像素精修。角度以画面順时針为正（与 ROI／找直线相同）。",
    params: {
      templates: { label: "更多模板", help: "好几种形状都算找到：同一个工件的两种姿态、同一条线上的三种盖子。每个结果都会说是哪一种。" },
      sort_by: {
        label: "结果排序",
        help: "取放最常用阅读顺序；有无检测用分数。",
        options: { score: "分数，最高在前", x: "由左到右", y: "由上到下", xy: "阅读顺序（先分行再由左到右）", angle: "角度" },
      },
      scale_x: { label: "横向缩放", help: "比对前先把模板拉伸，对付成像比示教时大或扁的工件。" },
      scale_y: { label: "纵向缩放" },
      allow_clipped: { label: "允许工件在边上", help: "把搜索范围的边界往外复制，跨在边上的工件也找得到。被切掉的工件分数会低，阈值要放宽一点。" },
      timeout_ms: { label: "超时放弃", help: "时间到就回目前找到最好的，不让产线等。0＝不限。" },
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
      template_image: "模板图",
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
      best_label: "最佳模板",
      counts: "各模板数量",
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
          sauvola: "Sauvola 区域自适应",
          niblack: "Niblack 区域自适应",
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
      window: { label: "窗口大小（奇数）" },
      k: { label: "k 值" },
      compare: {
        label: "比较方式",
        options: { ge: "像素 >= 门槛", le: "像素 <= 门槛", eq: "像素 == 门槛", ne: "像素 != 门槛" },
      },
      offset: { label: "门槛偏移" },
      roi: { label: "区域" },
      outside_roi: { label: "ROI 外侧", options: { black: "涂黑", keep: "保留原灰阶" } },
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
      mode: { label: "换算方向", help: "to_pixel 将 x/y/points 视为世界或坐标系内的坐标，输出 x/y/points_world 为影像像素；长度与角度同方向换算。", options: { to_world: "转为世界坐标", to_pixel: "转为像素坐标" } },
      calibration: { label: "标定资产", group: "高级", help: "选填；未选标定时输出坐标系内的像素值，未接 frame 时保留原坐标。" },
      decimals: { label: "小数位数", group: "高级" },
    },
    ports: { frame: "坐标系", points: "点", x: "X（像素）", y: "Y（像素）", value: "像素长度", angle: "角度（图像）", points_world: "点（真实世界）", length: "长度", scale: "比例" },
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
  path_extract: {
    label: "路径提取",
    description: "沿折线或多边形路径等距采样，或在每个采样点沿法线放卡尺找边，输出点集、切线角、偏移与打空索引。",
    params: {
      roi: { label: "路径", help: "多边形默认封闭、线段默认开放；上游 points 会优先。" },
      mode: { label: "模式", options: { equal_interval: "等距采样", edge_search: "找边" } },
      closed: { label: "封闭路径", help: "不设置时按路径类型决定：polygon 封闭，line 与 points 开放。" },
      spacing: { label: "采样间距", help: "沿路径每隔几个像素取一点；点数大于 0 时优先用点数。" },
      count: { label: "采样点数", help: "大于 0 时覆盖采样间距。" },
      search: { label: "搜索半径", help: "沿法线方向往两侧搜索的半径。" },
      caliper_width: { label: "卡尺宽度", help: "沿路径切线方向平均，用来降噪。" },
      edge_threshold: { label: "边缘阈值" },
      polarity: { label: "边缘极性", options: { any: "任意", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      edge_select: { label: "选哪个边", options: { strongest: "最强", first: "第一个", last: "最后一个" } },
      edge_mode: { label: "找边模式", options: { single: "单边", pair: "边缘对" } },
      pair_polarity: { label: "边缘对极性", options: { any: "任意", bright: "亮带", dark: "暗带" } },
      pair_mode: { label: "选哪一对", options: { first_last: "最外侧", widest: "最宽", narrowest: "最窄", strongest: "最强", expected: "最接近预期宽度" } },
      expected_width: { label: "预期宽度" },
      smoothing: { label: "剖面平滑" },
    },
    ports: {
      image: "图像", roi: "路径（动态）", points: "点集", ok: "成功", not_found: "找不到",
      angles: "切线角", offsets: "偏移", widths: "宽度", missing: "打空索引", count: "数量", length: "路径长度",
    },
  },
  edge_trend: {
    label: "边缘趋势",
    description: "沿一条直线或圆形边缘放多把卡尺，输出每把卡尺相对基线的偏移序列、缺失位置与统计。",
    params: {
      roi: { label: "参考", help: "没有接上游线或圆时使用；上游几何优先于 ROI。" },
      calipers: { label: "卡尺数" },
      search: { label: "搜索范围", help: "每把卡尺沿法线方向搜索的距离。" },
      caliper_width: { label: "卡尺宽度", help: "沿着边平均，用来降噪。" },
      edge_threshold: { label: "边缘阈值" },
      mode: { label: "模式", options: { single: "单一边缘", pair: "边缘对" } },
      polarity: { label: "边缘极性", options: { any: "任一", dark_to_light: "暗到亮", light_to_dark: "亮到暗" } },
      pair_polarity: { label: "边缘对极性", options: { any: "任一", bright: "亮带", dark: "暗带" } },
      baseline: {
        label: "基线",
        help: "offsets 是命中 offset 减去基线，单位 px。",
        options: { fit: "拟合命中边", median: "滑动中位数", reference: "参考几何" },
      },
      max_deviation: { label: "最大偏移", help: "最大绝对偏移超过此值时走 NG 分支；0 表示不限制。" },
      window: { label: "中位数窗口" },
      smoothing: { label: "剖面平滑" },
      edge_select: { label: "选哪个边", options: { strongest: "最强", first: "第一个", last: "最后一个" } },
    },
    ports: {
      image: "影像", roi: "参考（动态）", line: "参考线", circle: "参考圆",
      ok: "趋势合格", ng: "趋势超标",
      offsets: "偏移序列", widths: "宽度序列", positions: "位置", points: "边缘点",
      missing: "打空索引", mean: "平均", std: "标准差", min: "最小", max: "最大", range: "范围",
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
  stitch_images: {
    label: "影像拼接",
    description: "合成 2 到 4 台相机影像。固定排列且无透视差用硬拼；每张有世界标定，或第 2 到第 4 张有映到第 1 张的相机映射时，用投影拼。",
    params: {
      images: { label: "固定影像", help: "备用来源：没有接 image_1 到 image_4 时，按清单顺序拼接这些固定影像。正式流程建议接 image_1 到 image_4。" },
      mode: { label: "模式", options: { grid: "硬拼", homography: "投影拼" } },
      rows: { label: "行数" },
      cols: { label: "列数" },
      order: { label: "顺序", options: { row_major: "行优先", column_major: "列优先" } },
      trim: { label: "裁掉边界" },
      overlap_x: { label: "水平重叠", group: "高级" },
      overlap_y: { label: "垂直重叠", group: "高级" },
      blend: { label: "混合", options: { mean: "平均", min: "最小", max: "最大", uncover: "后盖前" } },
      calibration_1: { label: "标定 1" },
      calibration_2: { label: "标定 2" },
      calibration_3: { label: "标定 3" },
      calibration_4: { label: "标定 4" },
      scale: { label: "平面比例", help: "输出每像素代表多少世界单位。0 表示使用第一份世界标定比例；相机映射到第 1 张时使用 1 px/px。" },
    },
    ports: {
      image_1: "影像 1",
      image_2: "影像 2",
      image_3: "影像 3",
      image_4: "影像 4",
      image: "影像",
      count: "影像数",
      width: "宽度",
      height: "高度",
      offsets: "硬拼位移",
      origin: "世界原点",
      scale: "比例",
    },
  },
  undistort: {
    label: "镜头校正",
    description: "用标定资产把镜头弯掉的部分拉直。广角或近距离时边角的直线会往外拱；在校正后的图像上测量，数值就不会随视野位置漂移。",
    params: {
      mode: { label: "??", options: { calibration: "????", manual: "??" } },
      calibration: { label: "标定资产", help: "在标定页用几张标定板照片做出来。同一份标定也驱动「真实世界坐标」。" },
      alpha: { label: "保留画面", help: "0 = 裁掉所有黑边（放大到全部都是有效像素）；1 = 保留整个画面（角落补黑）；中间值保留该比例。" },
      keep_edges: { label: "保留整个画面", help: "旧流程用：等于 alpha 1。alpha 大于 0 时忽略。", group: "高级" },
      k1: { label: "K1" },
      k2: { label: "K2" },
      cx: { label: "?? X" },
      cy: { label: "?? Y" },
      scale: { label: "??" },
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
  ai_classify: {
    label: "分类（AI）",
    description: "以分类网络（官方底模或教导页训练的模型）判斷区域屬于哪一类；最高分类别分数達门槛（且在合格类别内）走 pass。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_size: {
        label: "底模大小",
        help: "只在没选模型资产时使用；越大越准但越慢。底模第一次使用时自动下载。",
        options: {
          n: "Nano（最快，默认）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最准，最慢）",
        },
      },
      model_name: {
        label: "模型文件（高级）",
        help: "本机 .pt 路径，会取代底模；平常留空。",
        group: "高级",
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
  ai_detect: {
    label: "对象检测（AI）",
    description: "以神经网络模型（官方底模或教導頁訓練的 .pt）找物件并回框、类别与分数；GPU 自動使用。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_size: {
        label: "底模大小",
        help: "只在没选模型资产时使用；越大越准但越慢。底模第一次使用时自动下载。",
        options: {
          n: "Nano（最快，默认）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最准，最慢）",
        },
      },
      model_name: {
        label: "模型文件（高级）",
        help: "本机 .pt 路径，会取代底模；平常留空。",
        group: "高级",
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
  ai_obb: {
    label: "旋转框（AI）",
    description: "以旋转框网络找物件并回旋转矩形（中心、宽高、角度）与四角座标；适合倾斜摆放的工件。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_size: {
        label: "底模大小",
        help: "只在没选模型资产时使用；越大越准但越慢。底模第一次使用时自动下载。",
        options: {
          n: "Nano（最快，默认）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最准，最慢）",
        },
      },
      model_name: {
        label: "模型文件（高级）",
        help: "本机 .pt 路径，会取代底模；平常留空。",
        group: "高级",
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
  ai_pose: {
    label: "姿态关键点（AI）",
    description: "以姿态网络找物件并回每个物件的关键点座标与信心（COCO 人体 17 点或自訂关键点）；可做位置／姿勢检查。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_size: {
        label: "底模大小",
        help: "只在没选模型资产时使用；越大越准但越慢。底模第一次使用时自动下载。",
        options: {
          n: "Nano（最快，默认）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最准，最慢）",
        },
      },
      model_name: {
        label: "模型文件（高级）",
        help: "本机 .pt 路径，会取代底模；平常留空。",
        group: "高级",
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
  ai_segment: {
    label: "实例分割（AI）",
    description: "以实例分割网络（官方底模或教导页训练的模型）找出每个物件的轮廓、类别与面积；输出聯合遮罩与轮廓給後续量测。",
    params: {
      model: {
        label: "模型资产",
        help: "教導頁訓練出的模型（.pt／.onnx）或自行上传的 .pt；留空則用下方底模名称。",
      },
      model_size: {
        label: "底模大小",
        help: "只在没选模型资产时使用；越大越准但越慢。底模第一次使用时自动下载。",
        options: {
          n: "Nano（最快，默认）",
          s: "Small",
          m: "Medium",
          l: "Large",
          x: "Extra large（最准，最慢）",
        },
      },
      model_name: {
        label: "模型文件（高级）",
        help: "本机 .pt 路径，会取代底模；平常留空。",
        group: "高级",
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
      max_polygon_points: {
        label: "多边形点数上限",
        help: "每个实例轮廓最多保留几个点。",
        group: "进阶",
      },
      precision: {
        label: "精度",
        options: { auto: "自动", half: "半精度", full: "全精度" },
        group: "进阶",
      },
      backend: {
        label: "执行后端",
        options: { eager: "标准", torchscript: "编译" },
        group: "进阶",
      },
      tracker: {
        label: "追踪器",
        options: { none: "无", bytetrack: "追踪器 A", botsort: "追踪器 B" },
        group: "进阶",
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
      centroids: "重心点",
    },
  },
}
