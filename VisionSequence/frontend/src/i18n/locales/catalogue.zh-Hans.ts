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
      label: 'Modbus/TCP 主站（连到 PLC）',
      description: '平台当客户端连到 PLC 或设备，读写它的线圈与寄存器；也可以轮询一个地址当触发来源。',
    },
    modbus_server: {
      label: 'Modbus/TCP 从站（本机开端口等待连入）',
      description: '平台当服务器开端口，让 PLC 或上位机来读写我们的寄存器；流程把结果写进去给主站取用。设置触发地址后，主站写入标志就会执行一次流程。服务器启动时会自动开端口。',
    },
    tcp_client: { label: 'TCP 文本或 JSON（上位机）' },
    dio_sim: { label: '模拟数字 I/O（只记录状态）' },
    plugin: { label: '插件（自行指定类路径）' },
  },
  trainers: {
    mlp_classify: {
      label: '图像分类（MLP）',
      description: '把整张样本图像（或其裁切）分到您定义的类别。轻量全连接网络，CPU 几秒就能训好；产物给「深度学习分类」工具使用。',
    },
    patch_segment: {
      label: '语义分割（轻量）',
      description: '从多边形标记学会逐像素分类（背景加上您的类别）。区块特征加轻量网络，CPU 几秒完成，导出成全卷积 ONNX 给「深度学习语义分割」工具。适合由颜色与纹理界定的区域与缺陷。',
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
    dl_segment_demo: { name: '语义分割：刮痕面积（教导模型）', description: '由 seed 训练的 patch_segment 模型接 dl_segment 刮痕面积阈值与 OK/NG' },
  },
}
