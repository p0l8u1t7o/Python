/**
 * 后端目录的简体中文对照（图像来源种类、连接种类、深度学习训练方式、内置模板）。
 *
 * 后端是英文的唯一事实来源；这里只翻译**显示的文字**，`kind`／`key` 这些**存进数据库的值一律
 * 保持英文原样**。没有对照的项目（插件）就显示后端给的英文，这正是插件作者预期的行为。
 * 由 `lib/catalogueLocale.ts` 叠上去，工具目录则另有 `tools.zh-Hans.ts`。
 */
export default {
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
    plugin: { label: '插件（自行指定类路径）' },
  },
  /** Advanced／Augment 这些分组名称每个训练方式共用。 */
  paramGroups: {
    Advanced: '进阶',
    Augment: '数据增强',
  },
  /** 四种 YOLO 训练方式的超参数几乎相同，共用这一份。 */
  yoloParams: {
    model: { label: '底模', help: 'ultralytics 的模型名称（第一次使用时下载）或 .pt 文件路径；填上一次训练的 best.pt 就会接着它继续训练。' },
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
    yolo_cls: {
      label: '图像分类（YOLO-cls）',
      description: '一张一类，从 ImageNet 预训练底模微调 YOLO 分类模型。比内置 MLP 分类准确，但需要 ultralytics（torch）。产物：best.pt 给 YOLO 分类工具、ONNX 给深度学习分类工具。',
    },
    yolo_detect: {
      label: '目标检测（YOLO）',
      description: '从外框标记训练 YOLO 检测模型（多边形会取外接框），找出每个目标的框与类别。训练最快、标记成本最低。产物：best.pt 给 YOLO 目标检测工具、ONNX 给深度学习目标检测工具。',
    },
    yolo_obb: {
      label: '旋转框检测（YOLO-obb）',
      description: '从多边形（取最小面积旋转矩形）或外框训练 YOLO OBB 模型，返回每个目标的旋转矩形（中心、尺寸、角度），适合斜摆的零件。产物：best.pt 给 YOLO 旋转框工具（ONNX 仅供外部使用）。',
    },
    yolo_seg: {
      label: '实例分割（YOLO-seg）',
      description: '从多边形标记训练 YOLO 分割模型，找出每个目标的轮廓与类别。需要 ultralytics（torch），建议搭配 NVIDIA GPU。官方底模第一次使用时下载，训练前也能自动标记（底模提出轮廓，挂在第一个类别）。产物：best.pt 给 YOLO 实例分割工具、ONNX 给深度学习实例分割工具。',
    },
  },
  templates: {
    hole_count: { name: '孔数计数', description: '灰阶、去噪、二值化、形态学、斑点计数、数值检查、OK/NG——含具名输出与结果图像' },
    exposure: { name: '曝光检查', description: '缩小、Otsu 二值化、范围检查、OK/NG' },
    circle_gauge: { name: '圆测量', description: '找圆、直径、像素换算 mm、公差判定——另含扇形 ROI 圆弧拟合与椭圆真圆度' },
    edge_angle: { name: '边线夹角', description: '两次找直线求夹角公差、交点，以及 45 度倒角测量' },
    golden_compare: { name: '印刷良品比对', description: '与良品模板做差异，抓重印、脏污与缺印；模板资产由范例样本图像建立' },
    fft_defect: { name: '布面瑕疵', description: '频域低通去掉周期性织纹，剩下的就是刮痕；再用掩膜取出缺陷面积' },
    preprocess_lab: { name: '前处理与测量实验室', description: '位深、查表、滤波、翻转的图像链，再走一遍线剖面、统计、直方图与边缘密度' },
    geometry_count: { name: '圆与直线', description: 'Hough 圆计数、Hough 直线以列表计数，再用两次找圆求中心距' },
    color_presence: { name: '颜色存在', description: '颜色范围掩膜接像素计数，再依阈值判定' },
    color_verify: { name: '颜色验证', description: '区域平均色与目标色的距离比对，色彩统计回报十六进制色码' },
    barcode_read: { name: '条码／QR 读取', description: '读码、检查有没有读到、输出内容' },
    label_read: { name: '含透视校正的条码标签', description: '四点透视校正把歪斜的标签拉正再读，另加序号区的文字存在检查' },
    locate_measure: { name: '定位与测量', description: '模板比对、定位补正、ROI 跟随、卡尺宽度、公差判定' },
    cup_measure: { name: '深冲杯件测量', description: '模板比对、定位补正、三个 ROI 跟随、内外圆与壁厚、同心度、三个公差判定、具名输出、OK/NG' },
    yolo_count: { name: 'YOLO 目标计数（官方底模）', description: 'yolo_detect 以 COCO 官方底模找停止标志并判定数量。免训练、自动用 GPU（需要深度学习依赖）' },
    yolo_area: { name: 'YOLO 实例分割：标志面积', description: 'yolo_segment 的并集掩膜接像素计数与面积阈值，示范分割接测量（需要深度学习依赖）' },
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
  },
}
