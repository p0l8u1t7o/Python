/**
 * 后端目录的简体中文对照（图像来源种类、连接种类、深度学习训练方式、内置模板）。
 *
 * 后端是英文的唯一事实来源；这里只翻译**显示的文字**，`kind`／`key` 这些**存进数据库的值一律
 * 保持英文原样**。没有对照的项目（插件）就显示后端给的英文，这正是插件作者预期的行为。
 * 由 `lib/catalogueLocale.ts` 叠上去，工具目录则另有 `tools.zh-Hans.ts`。
 */
export default {
  inspectKinds: {
  "measure_diameter": {
    "label": "测量直径",
    "help": "查找圆形边缘，并根据规格检查直径或真圆度。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "check": "直径",
          "roundness": "真圆度"
        }
      },
      "roi": {
        "label": "检测区域",
        "help": "在目标边缘周围绘制圆形或环形搜索区域。"
      },
      "edge": {
        "label": "测量边缘",
        "options": {
          "outer": "外缘",
          "inner": "内缘"
        }
      },
      "polarity": {
        "label": "边缘极性",
        "options": {
          "any": "任意",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "calibration": {
        "label": "标定",
        "help": "可选；留空时使用像素测量。"
      },
      "nominal": {
        "label": "标称值"
      },
      "upper_tol": {
        "label": "上公差"
      },
      "lower_tol": {
        "label": "下公差"
      },
      "unit": {
        "label": "单位",
        "options": {
          "px": "像素",
          "mm": "毫米"
        }
      },
      "result_name": {
        "label": "结果名称",
        "help": "执行结果中使用的名称。"
      },
      "required": {
        "label": "必要任务",
        "help": "必要任务会纳入检测汇总。"
      },
      "locator": {
        "label": "定位任务",
        "help": "可选；用于位置修正的定位任务。"
      },
      "num_rays": {
        "label": "扫描线数"
      },
      "method": {
        "label": "定位方式",
        "options": {
          "template": "模板",
          "shape": "形状模型",
          "register": "注册示例"
        },
        "help": "形状与注册示例定位将在后续版本提供。"
      },
      "template_images": {
        "label": "定位标记",
        "help": "从示教工件裁剪出的固定参考图像。"
      },
      "threshold": {
        "label": "分数阈值"
      },
      "allow_rotation": {
        "label": "允许旋转"
      },
      "angle_range": {
        "label": "旋转范围"
      },
      "ref_x": {
        "label": "参考 X"
      },
      "ref_y": {
        "label": "参考 Y"
      },
      "ref_angle": {
        "label": "参考角度"
      }
    }
  },
  "locate_part": {
    "label": "定位工件",
    "help": "查找示教模板，提供下游任务的位置修正。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "check": "直径",
          "roundness": "真圆度"
        }
      },
      "roi": {
        "label": "检测区域",
        "help": "留空时搜索整张图像。"
      },
      "edge": {
        "label": "测量边缘",
        "options": {
          "outer": "外缘",
          "inner": "内缘"
        }
      },
      "polarity": {
        "label": "边缘极性",
        "options": {
          "any": "任意",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "calibration": {
        "label": "标定",
        "help": "可选；留空时使用像素测量。"
      },
      "nominal": {
        "label": "标称值"
      },
      "upper_tol": {
        "label": "上公差"
      },
      "lower_tol": {
        "label": "下公差"
      },
      "unit": {
        "label": "单位",
        "options": {
          "px": "像素",
          "mm": "毫米"
        }
      },
      "result_name": {
        "label": "结果名称",
        "help": "执行结果中使用的名称。"
      },
      "required": {
        "label": "必要任务",
        "help": "必要任务会纳入检测汇总。"
      },
      "locator": {
        "label": "定位任务",
        "help": "可选；用于位置修正的定位任务。"
      },
      "num_rays": {
        "label": "扫描线数"
      },
      "method": {
        "label": "定位方式",
        "options": {
          "template": "模板",
          "shape": "形状模型",
          "register": "注册示例"
        },
        "help": "选择模板、形状模型或注册图像定位。"
      },
      "template_images": {
        "label": "定位标记",
        "help": "从示教工件裁剪出的固定参考图像。"
      },
      "threshold": {
        "label": "分数阈值"
      },
      "allow_rotation": {
        "label": "允许旋转"
      },
      "angle_range": {
        "label": "旋转范围"
      },
      "ref_x": {
        "label": "参考 X"
      },
      "ref_y": {
        "label": "参考 Y"
      },
      "ref_angle": {
        "label": "参考角度"
      },
      "model": {
        "label": "形状模型"
      }
    }
  },
  "check_presence": {
    "label": "检查有无",
    "help": "使用当前图像设置并执行此检测。",
    "fields": {
      "method": {
        "label": "方式",
        "options": {
          "template": "模板",
          "blob": "对象",
          "print": "印字"
        }
      },
      "roi": {
        "label": "检测区域"
      },
      "expected": {
        "label": "期望内容",
        "options": {
          "present": "应存在",
          "absent": "应不存在"
        }
      },
      "template_images": {
        "label": "参考图像"
      },
      "threshold": {
        "label": "阈值"
      },
      "threshold_method": {
        "label": "阈值方式",
        "options": {
          "otsu": "自动",
          "fixed": "固定",
          "hysteresis": "双阈值",
          "soft": "柔和阈值",
          "none": "不处理"
        }
      },
      "blob_threshold": {
        "label": "亮度阈值"
      },
      "polarity": {
        "label": "目标极性",
        "options": {
          "bright": "亮",
          "dark": "暗"
        }
      },
      "min_area": {
        "label": "最小面积"
      },
      "max_area": {
        "label": "最大面积"
      },
      "print_polarity": {
        "label": "印字极性",
        "options": {
          "dark": "暗",
          "bright": "亮"
        }
      },
      "min_ratio": {
        "label": "笔画比例下限"
      },
      "max_ratio": {
        "label": "笔画比例上限"
      },
      "required": {
        "label": "必要任务"
      },
      "locator": {
        "label": "定位任务"
      }
    }
  },
  "count_objects": {
    "label": "计数",
    "help": "使用当前图像设置并执行此检测。",
    "fields": {
      "roi": {
        "label": "检测区域"
      },
      "threshold_method": {
        "label": "阈值方式",
        "options": {
          "otsu": "自动",
          "fixed": "固定",
          "hysteresis": "双阈值",
          "soft": "柔和阈值",
          "none": "不处理"
        }
      },
      "threshold": {
        "label": "阈值"
      },
      "polarity": {
        "label": "目标极性",
        "options": {
          "bright": "亮",
          "dark": "暗"
        }
      },
      "min_area": {
        "label": "最小面积"
      },
      "max_area": {
        "label": "最大面积"
      },
      "min_circularity": {
        "label": "圆形度下限"
      },
      "min_count": {
        "label": "最少数量"
      },
      "max_count": {
        "label": "最多数量"
      },
      "result_name": {
        "label": "结果名称"
      },
      "required": {
        "label": "必要任务"
      },
      "locator": {
        "label": "定位任务"
      }
    }
  },
  "inspect_circular_surface": {
    "label": "圆周表面检测",
    "help": "使用当前图像设置并执行此检测。",
    "fields": {
      "roi": {
        "label": "检测区域"
      },
      "direction": {
        "label": "方向",
        "options": {
          "ccw": "逆时针",
          "cw": "顺时针"
        }
      },
      "start_angle": {
        "label": "起始角度"
      },
      "polarity": {
        "label": "目标极性",
        "options": {
          "any": "不限",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "threshold": {
        "label": "阈值"
      },
      "min_width": {
        "label": "最小缺陷宽度"
      },
      "max_defects": {
        "label": "允许缺陷数"
      },
      "search": {
        "label": "搜索范围"
      },
      "geometry": {
        "label": "缺陷位置表示",
        "options": {
          "centres": "中心点",
          "boxes": "外框",
          "spans": "起止点"
        }
      },
      "required": {
        "label": "必要任务"
      },
      "locator": {
        "label": "定位任务"
      }
    }
  },
  "inspect_edge_defect": {
    "label": "边缘缺陷检测",
    "help": "使用当前图像设置并执行此检测。",
    "fields": {
      "method": {
        "label": "方式",
        "options": {
          "simple": "直线或圆弧",
          "freeform": "自由轮廓"
        }
      },
      "roi": {
        "label": "检测区域"
      },
      "reference": {
        "label": "参考几何来源",
        "help": "可选上游直线或圆形来源；连线优先于绘制的区域。"
      },
      "mode": {
        "label": "模式",
        "options": {
          "single": "单边",
          "pair": "成对"
        }
      },
      "polarity": {
        "label": "目标极性",
        "options": {
          "any": "不限",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "pair_polarity": {
        "label": "带状区域极性",
        "options": {
          "any": "不限",
          "bright": "亮",
          "dark": "暗"
        }
      },
      "search": {
        "label": "搜索范围"
      },
      "threshold": {
        "label": "阈值"
      },
      "min_width": {
        "label": "最小缺陷宽度"
      },
      "direction": {
        "label": "方向",
        "options": {
          "both": "两侧",
          "inward": "向内",
          "outward": "向外"
        }
      },
      "width_min": {
        "label": "宽度下限"
      },
      "width_max": {
        "label": "宽度上限"
      },
      "max_defects": {
        "label": "允许缺陷数"
      },
      "baseline": {
        "label": "理想边缘",
        "options": {
          "fit": "拟合",
          "median": "中位数",
          "reference": "参考几何"
        }
      },
      "model": {
        "label": "轮廓模型"
      },
      "required": {
        "label": "必要任务"
      },
      "locator": {
        "label": "定位任务"
      }
    }
  },
  "measure_distance": {
    "label": "测量边距",
    "help": "使用当前图像设置并执行此检测。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "edge_pair": "边对",
          "hole_centres": "两孔中心"
        }
      },
      "roi": {
        "label": "检测区域"
      },
      "roi_a": {
        "label": "孔 A 区域"
      },
      "roi_b": {
        "label": "孔 B 区域"
      },
      "polarity": {
        "label": "目标极性",
        "options": {
          "any": "不限",
          "dark_to_light": "暗到亮",
          "light_to_dark": "亮到暗"
        }
      },
      "edge_pair": {
        "label": "边对选择",
        "options": {
          "first_last": "第一条与最后一条",
          "widest": "最宽",
          "narrowest": "最窄",
          "strongest": "最强"
        }
      },
      "pair_polarity": {
        "label": "带状区域极性",
        "options": {
          "any": "不限",
          "bright": "亮",
          "dark": "暗"
        }
      },
      "nominal": {
        "label": "标称值"
      },
      "upper_tol": {
        "label": "上公差"
      },
      "lower_tol": {
        "label": "下公差"
      },
      "unit": {
        "label": "单位",
        "options": {
          "px": "像素",
          "mm": "毫米"
        }
      },
      "result_name": {
        "label": "结果名称"
      },
      "calibration": {
        "label": "标定"
      },
      "required": {
        "label": "必要任务"
      },
      "locator": {
        "label": "定位任务"
      }
    }
  },
  "read_and_verify": {
    "label": "读取与验证",
    "help": "使用当前图像设置并执行此检测。",
    "fields": {
      "mode": {
        "label": "模式",
        "options": {
          "code": "条码",
          "text": "文字"
        }
      },
      "roi": {
        "label": "检测区域"
      },
      "types": {
        "label": "码制",
        "options": {
          "all": "全部",
          "qr": "QR 码",
          "2d": "二维码",
          "1d": "一维码"
        }
      },
      "expected": {
        "label": "期望内容"
      },
      "font_model": {
        "label": "字体模型"
      },
      "charset": {
        "label": "字符集",
        "options": {
          "alnum": "英数字",
          "digits": "数字",
          "upper": "大写字母与数字",
          "any": "不限",
          "custom": "自定义"
        }
      },
      "custom_charset": {
        "label": "自定义字符集"
      },
      "polarity": {
        "label": "目标极性",
        "options": {
          "dark_on_light": "亮底暗字",
          "light_on_dark": "暗底亮字"
        }
      },
      "min_confidence": {
        "label": "最低置信度"
      },
      "pattern": {
        "label": "位置样板"
      },
      "verify_mode": {
        "label": "比对方式",
        "options": {
          "exact": "完全相同",
          "contains": "包含",
          "regex": "正则表达式"
        }
      },
      "result_name": {
        "label": "结果名称"
      },
      "required": {
        "label": "必要任务"
      },
      "locator": {
        "label": "定位任务"
      }
    }
  }
},
  sourceKinds: {
    folder: { label: '文件夹（循环读取图像文件）' },
    file: { label: '单一图像文件' },
    synthetic: { label: '合成测试图像' },
    upload: { label: '推送图像（由 API 上传）' },
    capture: {
      label: '采集端相机',
      description: '相机所在电脑上的采集端程序取像后送到平台；同一台电脑会自动走共享内存。',
    },
    plugin: { label: '插件（自行指定类路径）' },
  },
  connectionKinds: {
    modbus_tcp: {
      label: 'Modbus TCP 主站（连到设备）',
      description: '平台当客户端连到任何 Modbus TCP 设备——控制器、驱动器、I/O 模块、上位程序——读写它的线圈与寄存器；也可以轮询一个地址当触发来源。',
    },
    modbus_server: {
      label: 'Modbus TCP 从站（本机开端口等待连入）',
      description: '平台当服务器开端口，让任何 Modbus TCP 主站来读写我们的寄存器；流程把结果写进去给主站取用。设置触发地址后，主站写入标志就会执行一次流程。服务器启动时会自动开端口。',
    },
    tcp_client: { label: 'TCP 文本或 JSON（上位机）' },
    tcp_image: {
      label: 'TCP 传图（上位机）',
      description: '把流程某一步的图像经一条长连接推给上位程序：13 字节定长前缀、JSON 表头（尺寸、编码、run id、判定与具名输出）、图像 bytes（JPEG／PNG／原始像素）。',
    },
    serial: {
      label: '串口文本设备',
      description: '通过串口收发逐行文本或十六进制字节。',
    },
    udp: {
      label: 'UDP 文本设备',
      description: '把逐行文本或十六进制字节送到 UDP 端点，也可开本机端口接收文本行。',
    },
    tcp_server_text: {
      label: 'TCP 文本设备服务器',
      description: '本机开端口等待设备连进来，收发逐行文本或十六进制字节。',
    },
    light: {
      label: '光源控制器',
      description: '通过串口或 TCP 送出光源控制命令，可设置亮度、开灯与关灯模板。',
    },
    plugin: { label: '插件（自行指定类路径）' },
  },
  /** Advanced／Augment 这些分组名称每个训练方式共用。 */
  paramGroups: {
    Advanced: '进阶',
    Augment: '数据增强',
  },
  /** 四种神经网络训练方式的超参数几乎相同，共用这一份。 */
  sharedParams: {
    model: { label: '底模大小', help: '预训练的起点（第一次使用时下载）；越大越准但训练与执行越慢。透过 API 也接受 .pt 文件路径。', options: { n: 'Nano（最快，默认）', s: 'Small', m: 'Medium', l: 'Large', x: 'Extra large（最准，最慢）' } },
    epochs: { label: '训练轮数' },
    imgsz: { label: '图像尺寸', options: { 224: '224（建议）', 320: '320', 480: '480', 640: '640（建议）', 960: '960' } },
    batch: { label: '批次大小' },
    patience: { label: '早停耐心值' },
    lr0: { label: '初始学习率' },
    val_ratio: { label: '验证集比例' },
    workers: { label: 'DataLoader 线程', help: 'Windows 建议填 0；在后台线程训练时最稳。' },
    suggest_conf: { label: '自动标记的置信度阈值', help: '还没训练前用官方底模提出建议（名称对不上的会挂在第一个类别，您再修正）；训练过后改用 best.pt。' },
    degrees: { label: '旋转角度（±）', help: '随机旋转的最大角度；产线上目标方向固定时建议填 0。' },
    fliplr: { label: '水平翻转概率' },
    mosaic: { label: 'Mosaic 增强', help: '把四张样本拼成一张训练图像；样本少的时候调低。' },
  },
  trainers: {
    mlp_classify: {
      label: '图像分类（MLP）',
      description: '把整张样本图像（或其裁切）分到您定义的类别。轻量全连接网络，CPU 几秒就能训好；产物给「深度学习分类」工具使用。',
      params: {
        input_size: { label: '输入尺寸', options: { 32: '32x32（最快）', 64: '64x64（建议）', 96: '96×96', 128: '128x128（细节较多）' } },
        hidden: { label: '隐藏层宽度' },
        epochs: { label: '训练轮数' },
        learning_rate: { label: '学习率' },
        val_split: { label: '验证集比例', help: '填 0 代表全部拿来训练，适用于样本非常少的时候；手动指定为 val 的样本优先。' },
        augment: { label: '启用数据增强', help: '只在训练集加入水平翻转与亮度抖动的副本；样本少时有助于泛化。' },
        augment_brightness: { label: '亮度抖动' },
      },
    },
    patch_segment: {
      label: '语义分割（轻量）',
      description: '从多边形标记学会逐像素分类（背景加上您的类别）。区块特征加轻量网络，CPU 几秒完成，导出成全卷积 ONNX 给「深度学习语义分割」工具。适合由颜色与纹理界定的区域与缺陷。',
      params: {
        input_size: { label: '工作尺寸', help: '训练用的尺寸，也是建议的推理尺寸。模型是全卷积的，推理时可以用别的尺寸。', options: { 128: '128（最快）', 192: '192（建议）', 256: '256（细节较多）' } },
        kernel: { label: '感受野', options: { 5: '5×5', 7: '7×7', 9: '9×9' } },
        hidden: { label: '隐藏层宽度' },
        epochs: { label: '训练轮数' },
        learning_rate: { label: '学习率' },
        samples_per_image: { label: '每张采样的像素数' },
        augment: { label: '启用数据增强', help: '每张图像另外采样一份水平翻转的版本，标记一并翻转。' },
      },
    },
    anomaly: {
      label: '异常检测（只教良品）',
      description: '只用良品图像学会「正常长什么样」——不需要缺陷样本、不需要标注——没见过的就标成异常。预训练 backbone 把每张图变成区块特征，记忆库留一小部分，运行时每个区块到最近良品区块的距离就是异常分数。训练＝提特征＋建库，CPU 几秒到一分钟。',
      params: {
        backbone: { label: '特征提取器', options: { resnet18: 'ResNet18 layer2+3（ImageNet）' } },
        input_size: { label: '输入尺寸', options: { 224: '224（最快）', 320: '320（建议）', 448: '448（更细的缺陷）' } },
        coreset_ratio: { label: '记忆库比例', help: '贪婪子抽样后保留的良品区块比例。0.1 兼顾准确与运行速度。' },
        threshold_sigma: { label: '阈值 σ 倍数', help: '自动阈值＝良品自身分数的平均 + σ 倍数 × 标准差。' },
        augment: { label: '数据增强（翻转与亮度）', help: '每张良品另加一份翻转与两份亮度偏移的版本进记忆库。' },
        augment_brightness: { label: '亮度扰动' },
        blur_sigma: { label: '分数图平滑' },
        projection_dims: { label: '特征投影', help: '384 维特征的固定随机投影。128 维保留距离排序，运行时间约缩短三倍。', options: { 0: '不投影（384 维，最慢）', 128: '128 维（建议）', 64: '64 维（最快）' } },
      },
    },
    retrieval: {
      label: '影像检索库',
      description: '把已标记影像建立成参考库；日后新增类别只需加入新影像。',
      params: {
        input_size: { label: '输入尺寸', help: '新增参考图时使用的方形尺寸。' },
        topk: { label: '投票数', help: '用几张最接近的参考图决定最终类别。' },
        augment: { label: '保存轻度变化', help: '为每张已标记影像额外保存镜射与小角度参考。' },
        augment_angle: { label: '倾斜角度', help: '保存轻度变化时使用的小角度。' },
        projection_dims: { label: '压缩参考库', options: { 0: '关闭', 64: '小型', 128: '标准' } },
        backbone_path: { label: '参考比对文件', help: '测试用内部文件覆盖。' },
      },
    },
    ai_cls: {
      label: '图像分类（AI）',
      description: '一张一类，从 ImageNet 预训练底模微调 分类网络。比内置 MLP 分类准确，但需要深度学习加购包。产物：训练好的权重给 AI 分类工具、ONNX 给深度学习分类工具。',
    },
    ai_detect: {
      label: '目标检测（AI）',
      description: '从外框标记训练 检测网络（多边形会取外接框），找出每个目标的框与类别。训练最快、标记成本最低。产物：训练好的权重给 AI 目标检测工具、ONNX 给深度学习目标检测工具。',
    },
    ai_obb: {
      label: '旋转框检测（AI）',
      description: '从多边形（取最小面积旋转矩形）或外框训练 旋转框网络，返回每个目标的旋转矩形（中心、尺寸、角度），适合斜摆的零件。产物：训练好的权重给 AI 旋转框工具（ONNX 仅供外部使用）。',
    },
    ai_seg: {
      label: '实例分割（AI）',
      description: '从多边形标记训练 實例分割網路，找出每个目标的轮廓与类别。需要深度学习加购包，建议搭配 NVIDIA GPU。官方底模第一次使用时下载，训练前也能自动标记（底模提出轮廓，挂在第一个类别）。产物：训练好的权重给 AI 实例分割工具、ONNX 给深度学习实例分割工具。',
    },
  },
  templates: {
    character_count: { name: '散乱字符计数', description: '在直线、曲线或散乱排列中检测六个单字符' },
    seal_width: { name: '自由轮廓胶道宽度', description: '测量曲线胶道的两侧，排除缩窄或断裂区段' },
    point_fitting: { name: '由边缘点拟合几何', description: '由测量边界拟合直线、圆与椭圆，要求三项结果完整并计算圆面积' },
    polar_edge_check: { name: '展开并还原圆周缺陷', description: '检查展开后的直边，仅将检出的缺口中心映回原图' },
    absence_check: { name: '禁区异物检查', description: '区域应保持无物体，出现异物即判 NG' },
    list_postprocess: { name: 'Blob 结果排序与挑选', description: '按面积过滤 blob 清单、扫描顺序排序、挑出最大件、分级并合并中心点' },
    boxes_cleanup: { name: '重叠匹配合并与禁区排除', description: 'template_match 的多个结果先合并、按尺寸与分数过滤，再检查是否压到禁区' },
    array_placement: { name: '元件阵列缺位检查', description: '把 blob 中心校正成 3 x 4 阵列，回报缺格位置并判定 OK/NG' },
    label_map_count: { name: '多色分割转计数', description: '红、绿、蓝三段 HSV 范围转成 label map，再由 label-map blob 统计各色数量' },
    color_sample_classify: { name: '固定样本色分类', description: '把 ROI 颜色直方图与红、绿、蓝固定色票比对，相似度不足就判 NG' },
    plate_corners: { name: '矩形板角点与歪斜', description: '直接找矩形四边，也用四条边线重建四角，板宽或歪斜超差就判 NG' },
    parallel_edges: { name: '槽宽与条纹数', description: '成对边缘搜索量槽宽，另一支多线搜索统计参考条纹数' },
    hole_matrix: { name: '孔矩阵完整性', description: '3 x 3 圆矩阵回报每个孔心与缺格索引，缺孔即 NG' },
    edge_trend_peaks: { name: '边缘趋势与剖面峰值', description: '沿教导直边布卡尺找局部凸起，同图剖面搜索确认四个亮峰' },
    outline_defect: { name: '教导轮廓缺陷比对', description: '模板定位补正工件姿态，再用良品轮廓模型检出冲压边缺料' },
    path_edge_search: { name: '沿路径搜索边缘', description: '沿教导路径放卡尺确认亮胶条连续，回报缺边索引' },
    focus_gate: { name: '检查前焦距闸门', description: 'sharpness 分数与噪声估计先挡下模糊图像，再进入后续检查' },
    temporal_frames: { name: '跨帧平均与前帧差异', description: '累积两帧平均，同时读取前一帧做差异检查；第一帧没有缓存会正常 not_found' },
    roi_process_paste: { name: '处理区域后贴回', description: '裁切 ROI 后做 LUT 与滤波，再贴回整张图像并在完整画面上检查' },
    manual_undistort_world: { name: '手动校正与零件坐标', description: '手动镜头修正后找两孔、建立零件坐标，并用示范像素比例标定换算 mm' },
    camera_mapping: { name: '映射到第二相机', description: '在 A 相机找孔心，通过示范仿射标定映射成 B 相机坐标并格式化输出' },
    pick_offset: { name: '教导姿态取料补正', description: '模板比对找到教导姿态，grab 模式补正并输出实际取料坐标' },
    fixture_rerun: { name: '整张回正后重跑量测', description: '定位后把整张图像拉回教导姿态，固定坐标 ROI 可直接重复量测' },
    stitch_two_views: { name: '双视野拼接计数', description: '左视野与右侧固定视野拼成 1 x 2 图像，再跨两相机统计零件' },
    variable_switch: { name: '按变量切换配方', description: '读取配方变量后用 switch 走不同阈值分支，并以 sandbox 覆盖层累计检查数' },
    tile_for_each: { name: '影像切片逐格巡检', description: '将影像切成 2 x 2，for_each 逐格调用子流程，另示范直接 call_flow 接线' },
    script_measure: { name: '自定义 Python 量测', description: 'blob 量测结果交给核准脚本计算长宽比与填满率，再做范围判定' },
    code_message_rules: { name: '解码、拆消息与比对', description: '读取 QR payload，拆出批号与料号，用正则表达式验证批号并格式化回复' },
    io_sequence: { name: '灯源、相机 I/O 与设备信号', description: '相机设置、灯源、站台输出、相机输出与 Modbus 读取在缺连接时都降级为警告' },
    outputs_bundle: { name: '记录、存图、送图与触发', description: '格式化结果、写入 CSV、NG 存图、送出结果影像并异步触发后续流程' },
    register_classes: {"name": "注册多类别计数", "description": "各注册类别恰好三个才合格，无需训练。需要深度学习加购包。"},
    register_segment: {"name": "注册纹理分割", "description": "使用前景与背景样本查找不规则目标纹理。需要深度学习加购包。"},
    register_count: { name: '以注册图计数零件', description: '由一张零件裁切图查找相似目标，恰好三个才合格，无需训练。需要深度学习加购包。' },
    form_tolerance: { name: '真圆度（形位公差）', description: '180 把径向卡尺取边缘点，形位公差以最小区域圆（ISO 1101）评真圆度，两同心圆的环宽在 5 px 内合格——崩边的圆盘不合格' },
    emboss_defect: { name: '刻印字与凹坑（光度立体）', description: '四个裁切把四灯 2×2 拼图拆开，光度立体合成形状强度图，检查区的像素计数找出单张看不见的凹坑' },
    barcode_grade: { name: '条码品质分级（ISO 15415）', description: '像验证器一样替标签上的 Data Matrix 评级——对比、调制、固定图形损伤、轴向与格点不均匀、未用错误更正——C 级以上合格，脏污的符号不合格' },
    hole_count: { name: '孔数计数', description: '灰阶、去噪、二值化、形态学、斑点计数、数值检查、OK/NG——含具名输出与结果图像' },
    exposure: { name: '曝光检查', description: '缩小、Otsu 二值化、范围检查、OK/NG' },
    circle_gauge: { name: '圆测量', description: '找圆、直径、像素换算 mm、公差判定——另含扇形 ROI 圆弧拟合与椭圆真圆度' },
    edge_angle: { name: '边线夹角', description: '两次找直线求夹角公差、交点，以及 45 度倒角测量' },
    golden_compare: { name: '印刷良品比对', description: '与良品模板做差异，抓重印、脏污与缺印；良品图随模板附带（固定图像）' },
    fft_defect: { name: '布面瑕疵', description: '频域低通去掉周期性织纹，剩下的就是刮痕；再用掩膜取出缺陷面积' },
    preprocess_lab: { name: '前处理与测量实验室', description: '位深、查表、滤波、翻转的图像链，再走一遍线剖面、统计、直方图与边缘密度' },
    geometry_count: { name: '圆与直线', description: 'Hough 圆计数、Hough 直线以列表计数，再用两次找圆求中心距' },
    color_presence: { name: '颜色存在', description: '颜色范围掩膜接像素计数，再依阈值判定' },
    color_verify: { name: '颜色验证', description: '区域平均色与目标色的距离比对，色彩统计回报十六进制色码' },
    barcode_read: { name: '条码／QR 读取', description: '读码、检查有没有读到、输出内容' },
    guided_code_read: { name: '定位后读码', description: '先以模板匹配找到码区，让 ROI 跟着移动，裁切放大后再解码；训练的检测模型可经 matches 端口接进同一条接线' },
    label_read: { name: '含透视校正的条码标签', description: '四点透视校正把歪斜的标签拉正再读，另加序号区的文字存在检查' },
    locate_measure: { name: '定位与测量', description: '模板比对、定位补正、ROI 跟随、卡尺宽度、公差判定' },
    cup_measure: { name: '深冲杯件测量', description: '模板比对、定位补正、三个 ROI 跟随、内外圆与壁厚、同心度、三个公差判定、具名输出、OK/NG' },
    ai_count: { name: 'AI 目标计数（官方底模）', description: 'ai_detect 以 COCO 官方底模找停止标志并判定数量。免训练、自动用 GPU（需要深度学习依赖）' },
    ai_area: { name: 'AI 实例分割：标志面积', description: 'ai_segment 的并集掩膜接像素计数与面积阈值，示范分割接测量（需要深度学习依赖）' },
    conveyor_pick: { name: '输送带取料（单相机）', description: '实例分割、边界排除、追踪确认与逐笔文字输出，只在物件第一次确认时送出 x、y、z。' },
    conveyor_pick_bytetrack: { name: '输送带取料（ByteTrack）', description: '分割工具内置 ByteTrack 追踪器给每个物件稳定的追踪 ID，边界排除后以追踪 ID 确认，只在物件第一次确认时送出 x、y、z。' },
    conveyor_pick_stereo: { name: '输送带取料（双视野）', description: '双视野取像、实例分割、边界排除、追踪确认、stereo_depth 量 Z，并送出 x、y、z。' },
    dl_classify_demo: { name: '分类：良品／缺孔（教导模型）', description: '由 seed 训练的内置 MLP 分类器接 dl_classify 判定——示范教导出来的模型怎么进流程' },
    gear_teeth: { name: '圆周齿数（极坐标展开）', description: '极坐标展开把齿圈摊平成长条图，二值化与 blob 数齿，极坐标还原把每颗齿标回原图' },
    contour_defect: { name: '崩边检测（轮廓几何）', description: '轮廓提取、筛出工件本体、轮廓几何数超过 12 px 的凸缺陷、OK/NG，另以 Hu 矩与示例外形比对' },
    date_code: { name: '日期码读取与验证（教导字体）', description: 'seed 教的字体读出日期码（切分＋逐字分类，完全离线），字符串验证比对 8 位数字图样与逐字置信度，被污点盖住的字以红框标出' },
    circular_defect: { name: '圆盘崩边（圆形卡尺）', description: '180 把径向卡尺给每个角度的半径与跳动量；序列缺陷拟合圆后把每处凹陷或打空的卡尺标成崩边，画成圆缘上的红弧' },
    exclusion_zone: { name: '排除区（组合区域）', description: '两个画好的区域由区域组合从板面矩形挖掉，经区域输入端口喂给统计与 blob 步骤，孔内像素完全不算' },
    shading: { name: '平场校正（打光不均）', description: '除以白板参考资产，让同一个固定阈值在角落也找得到暗污点；旁支演示不校正时同一阈值的误判' },
    stat_compare: { name: '统计良品比对', description: '30 张良品建的逐像素平均与变异，偏离 4 个标准差以上就是缺陷，光线与纹理变动不再逼阈值放松' },
    shape_locate: { name: '形状比对定位（任意角度、任意光线）', description: '以边缘方向比对找出旋转、变暗、杂物中的工件，接定位补正与 ROI 跟随，并拒绝不同的零件' },
    anomaly_demo: { name: '异常检测：只教良品（教导模型）', description: 'seed 由 20 张干净铝板建的异常模型把每个区块与良品记忆库比对，没见过的划痕就是异常（需要异常检测 backbone）' },
    dl_segment_demo: { name: '语义分割：刮痕面积（教导模型）', description: '由 seed 训练的 patch_segment 模型接 dl_segment 刮痕面积阈值与 OK/NG' },
    ai_classify_demo: { name: '库存分类器闸门', description: 'ai_classify 先输出库存模型标签，再用 string_match 按标签分流判定；实务可改用教导模型或 pass_labels' },
    ai_obb_demo: { name: '倾斜工件的旋转框', description: 'ai_obb 找旋转外框，list_sort 按角度排序，再由 format_text 组成角度报表' },
    ai_pose_demo: { name: '关键点与几何', description: 'ai_pose 输出姿态与关键点，本示例用人数闸门示范，也可把关键点接到几何量测' },
    dl_detect_instance_demo: { name: '教导式检测与实例模型', description: 'dl_detect 与 dl_instance 并排，模型资产留空，供深度学习教导页训练后选用' },
    dl_retrieval_demo: { name: '免重训扩充的检索库', description: '三类参考图建立检索库，预期标签相符走 OK，低相似度走 not_matched' },
    multi_light_surface: { name: '四向打光融合表面缺陷', description: '每张样本是同一表面四个打光方向的 2×2 拼图：裁四格进 multi_light_fuse（阴影模式）找只在强起伏才出现的划痕；multi_light_grab 演示产线接法' },
  },
}
