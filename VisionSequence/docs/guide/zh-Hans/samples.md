# 示例模板与合成样本图像

示例模板位于**模板画廊**中，即「流程」页的「从模板建立」与编辑器顶栏的「载入模板」，共有 76 个内置模板，因此不会让流程列表变得杂乱。`manage.py seed_demo` 或 `dev.ps1 -Setup` 会建立与它们搭配的一切：两条示范流程、每个模板各一组合成样本图，这些图会以**固定图像**保存并随模板移动；参考图，也就是定位模板、Golden 打印图与白参考，会以固定图像连接到工具的图像输入端口；统计模板、形状模型与教导模型资产也会一并建立。从模板建立流程后保留来源不变即可，每个模板都以内含自身样本图的 Fixed image 步骤开始，因此可**原样执行**。采集步骤会成为 Fixed image 步骤，逐次循环样本图，第四张通常是刻意安排的 NG。156 个内置工具中有 156 个至少出现在一个模板内，因此打开任一模板即可看到该工具实际如何接线，以及参数在实务中如何设置。

每组有四张图像，教学模板为三张，最后一张刻意设为 NG。来源会循环，因此连续执行或反复点击「执行」会得到 OK → OK → OK → NG。坐标与公差都符合合成图像的标称值，所以开始使用前不需要调参。

## 模板列表 {#list}

| 模板 | 样本图像 | 教导重点 | 主要工具 |
|---|---|---|---|
| 推入并匹配工件 | 四张 333 x 97 图像模拟读数 100、101、99、120 | 推入数值与图像引用，按执行键匹配并合并读数；第四张不合格。进程重新启动即清空，尚无实际现场情境验证 | `queue_push``queue_pop``intensity``formula``in_range` |
| 散乱字符计数 | 六个固定点阵字符，排列为直线、120 度圆弧及散乱分布；第四张只有五个 | 检测旋转字符外框并要求六个字符。分类时选择以首字作为标签的字符样本，使用相同极性，合并间距须小于字符间距。圆弧从最大空白角后顺时针排序；预期文本需启用分类 | `char_detect``in_range` |
| 自由轮廓胶道宽度 | 1001 x 701 图像中的 12 px S 形胶道；第四张缩窄至 6 px 且有断裂 | 模型沿胶道中心线配置，选双边模式与亮暗极性，以宽度中位数及绝对上下限判断。缺陷位置与长度沿轮廓测量；位置修正带动整个模型 | `edge_model_defect` |
| 由边缘点拟合几何 | 1001 x 701 图像中的圆、椭圆与直边；第四张缺少直边 | 拟合测量边界，检查直径、长轴与直线残差并计算圆面积。检测汇总在测量缺席时判 NG，即使其他项目合格亦然 | `contour_find``find_line``fit_circle_points``fit_ellipse_points``fit_line_points``formula``in_range``inspection_summary``tolerance_judge` |
| 展开并还原圆周缺陷 | 1001 x 701 图像中的圆周；第四张在顺时针 40 度有缺口 | 展开圆周并检查直边，仅转换缺陷中心，通过已连接的 mapping 还原坐标。完整边缘点集不作为缺陷位置 | `defects_to_geometry``edge_defect``polar_restore``polar_unwrap` |
| 禁区异物检查 | 四张图像均有框外物体；第四张另有框内异物 | 期望状态设为 absent。检查区域无物体时合格，框内有异物时判 NG | `blob` |
| 注册计数 | 三个重复零件与一张注册参考裁切；第四张数量错误 | 注册一个裁切零件并接受刚好三个匹配，不需要训练 | `judge``register_detect` |
| 注册多类别计数 | 圆形、方形、三角形各三个；第四张缺一个三角形 | 加入类别:图名裁切图，各类须恰好三个 | `register_detect` |
| 注册纹理分割 | 不同背景上三块不规则前景纹理；第四张无目标 | 前景与背景原型产生遮罩和总面积；缩小搜索区域可改善边界精度 | `register_segment` |
| 孔数计数 | 亮色板件有四个角孔与较大的中心孔，并旋转数度；第四张缺少一个角孔 | 最基本的骨架：threshold → blob → count → 依数量分支 | `blob``blur``if_number``morphology``threshold` |
| 曝光检查 | 同一片板件的四种曝光：正常、偏暗、偏亮与过曝；第四张超出范围 | 纯预处理与逻辑的把关流程：缩小加速，并以 Otsu 阈值作为曝光指标 | `grayscale``in_range``resize``threshold` |
| 圆测量 | 亮色板件搭配深色孔洞；第四张超出公差 | 找圆、把像素转成毫米，再依公差判定。也示范**扇形 ROI**，也就是带起讫角的环形 ROI，用于圆弧拟合，以及用椭圆拟合评估真圆度 | `calibration``find_circle``fit_arc``fit_ellipse``judge``tolerance_judge` |
| 边线夹角 | L 形零件；第四张为 84°，右下有 45° 倒角 | 两次找线得到角度与交点；倒角工具测量斜边 | `angle``chamfer_angle``find_line``geometry``in_range``judge` |
| 印刷良品比对 | 一个打印图案；第四张多了一块污点 | 与 Golden 模板做差异比对，可找出事先无法描述的缺陷。模板资产由 seed 建立 | `defect_diff``fixed_image``judge` |
| 统计良品比对 | 打印比对图像，第四张有污点 | seed 会由 30 张抖动的良品打印建立统计模板，亮度 ±8、位移 ±3 px；`defect_stat` 会标出每个像素超过自身正常值 4 个标准差的位置，因此照明与纹理变化不会迫使阈值放宽 | `defect_stat``if_number` |
| 布面瑕疵 | 周期性织纹；第四张有划痕 | 频域低通会抹除规则纹理并留下深色痕迹，也就是缺陷。掩膜会取出缺陷区域 | `apply_mask``blob``fft_filter``if_number``morphology``threshold` |
| 表面划痕（滤波） | 具有方向纹理的拉丝金属表面；第四张有长划痕 | 方向性表面滤波能在不需要周期背景的情况下响应窄长痕迹 | `blob``if_number``surface_filter``threshold` |
| 前处理与测量实验室 | 渐变、灰阶阶梯楔与深色沟槽 | 图像链，包含位深 → gamma → 锐化 → 翻转 → 前后差异；并巡览测量工具：线剖面、区域统计、直方图、边缘密度、暗区比例、裁切与色彩平面 | `arithmetic``color_convert``convert_depth``crop``dark_ratio``edge_density``filter``grayscale``histogram``intensity``judge``line_profile``lut``rotate_flip` |
| Blob 结果排序与挑选 | 六个小圆形零件散布在深色背景上；第四张缺少一个有效零件，且有一个过大的零件 | Blob 结果会按面积过滤、按扫描顺序排序、挑出最大的有效零件、将所有有效零件按尺寸分级，并把左右中心列表合并成一组点集 | `blob``if_number``list_classify``list_filter``list_pick``list_sort``points_merge``threshold` |
| 元件阵列缺位检查 | 干净的 3×4 亮色元件阵列；第四张缺少一个位置 | Blob 检测框送入 Correct array，补齐推断出的网格、报告缺格、计数，并判定阵列是否完整 | `array_correct``blob``count_list``if_number``threshold` |
| 圆与直线 | 五个孔与两条斜线；第四张缺少一个孔 | 示范 Hough 可一次找出多个圆，find-circle 可精准测量单一圆；并计算线段列表数量与两个孔中心距离 | `count_list``distance``find_circle``hough_circles``hough_lines``if_number` |
| 圆周齿数（极坐标展开） | 深色背景上的亮色十二齿齿轮；第四张缺齿 | Polar unwrap 会把齿根与齿尖之间的环带摊平成条带，让每个齿成为亮区块、每个间隙成为暗栏；threshold 与 blob 计算区块，Polar restore 在原图上标示各齿。起始角放在间隙，因此接缝不会切开齿形 | `blob``if_number``polar_restore``polar_unwrap``threshold` |
| 崩边检测（轮廓几何） | 深色背景上的亮色冲压件，含孔与槽；第四张上缘被咬掉一块 | Contour find 追踪外形，filter 只保留最大轮廓，也就是零件；contour geometry 计算深度超过 12 px 的凸性缺陷，即崩边。Contour match 以 Hu moments 与样本外形资产比对轮廓，用于防止零件错误或严重变形 | `contour_filter``contour_find``contour_geometry``contour_match``fixed_image``if_number` |
| 圆盘崩边（边缘缺陷） | 亮色圆片有中心孔；第四张外缘有缺口 | Edge defects 会沿实际轮缘布卡尺，报告每段偏离拟合边的缺陷 | `edge_defect``find_circle``judge` |
| 圆盘崩边（圆形卡尺） | 亮色圆片有中心孔；第四张右下外缘有 24° 崩边 | 180 个径向卡尺每 2° 给出半径与径向跳动；Profile defects 会对边缘点拟合圆，并标记低于该圆 3 px 的每一段，或卡尺完全找不到边缘的位置。崩边会在外缘画成红色弧段 | `circular_caliper``if_number``profile_defect` |
| 真圆度（形位公差） | 崩边圆片组：亮色圆片有中心孔；第四张右下外缘有 7 px 深崩边 | 180 个径向卡尺给出边缘点；Form and position tolerance 拟合最小区域圆（ISO 1101），同心双圆之间的环宽在 5 px 内即通过。明细也报告最小二乘值与两个极值点 | `circular_caliper``gdt_measure``judge` |
| 刻印字与凹坑（光度立体） | 同一片板件在四向打光下的 2×2 图像，光源来自右、下、左、上；板件有斑驳反射率与浮凸字样「VS 42」；第四张在字符上方检查区有凹坑 | 四个 Crop 步骤切出各视角，Photometric stereo 转成形状强度图，斑驳消失后只留下表面形状，再以检查区中的像素计数找出单张图像看不到的凹坑。良品答案是空区，所以用像素计数而非 blob 计数判定 | `crop``judge``photometric_stereo``pixel_count` |
| 条码品质分级（ISO 15415） | 白色标签含 Data Matrix 与料号；四种打印品质为干净、低对比、模糊且有噪声，以及静区有脏污的符号 | Barcode quality grade 像验证器一样测量符号，C 级以上通过；parameters 输出会说明哪一项参数拉低等级，第四张标签会失败 | `barcode_grade``judge` |
| 排除区（组合区域） | 圆测量板件：亮色板件的深色中心孔会改变大小 | 两个 Region 步骤画出孔与标签区，Region combine 从板件矩形中切除它们，并把组合区域经由区域输入提供给统计与 blob 步骤。即使孔变大，板件平均值仍保持稳定，因为孔的像素从未计入 | `blob``in_range``intensity``region_combine``region_from_shape` |
| 平场校正（打光不均） | 亮色板件在强烈暗角下有深色斑点，角落亮度只有 45%；第四张多了一个大标记 | 除以白参考资产可摊平照明，因此固定阈值能找到所有斑点；侧支路用同一阈值跑未校正图像，计数会错。参考图由 seed 写入 | `blob``fixed_image``grayscale``if_number``shading_correct``threshold` |
| 重叠匹配合并与禁区排除 | 三个定位标记位于灰色禁区旁；第四张在禁区内新增一个标记 | 固定标记图送入 Template match，重复检测框会合并，检测框再按尺寸与分数过滤，剩下的标记框会与量到的禁区框比对 | `blob``boxes_filter``boxes_merge``boxes_overlap``fixed_image``judge``template_match` |
| 自定义 Python 量测 | 单一亮色矩形零件；第四张矩形过于细长 | Blob 量测结果送入固定且已核准的 Python 脚本，计算长宽比与填满分数，再由范围检查把自定义值转成 OK/NG | `blob``in_range``python_script``threshold` |
| 颜色存在 | 三个色块；第四张红色偏橙 | HSV 范围掩膜进入像素计数，用于典型存在／缺失判定 | `color_range``if_number``pixel_count` |
| 颜色验证 | 同一组图像 | 以距离比对区域平均色与目标色；色彩统计会输出十六进制色码给主机系统 | `color_check``color_stats``judge` |
| 多色分割转计数 | 一个红点、一个绿点与一个蓝点；第四张缺少蓝点 | 三段 HSV 范围建立整数 label map，接着 Label map blobs 按类别计算连通区域，任何一种颜色缺席就失败 红色标签另转成掩膜以测量像素面积。 | `blob_label``color_segment``judge``label_to_mask``pixel_count` |
| 固定样本色分类 | 色卡上有红色、绿色或蓝色色票；第四张色票不属于固定样本 | 三个固定样本色票随模板附带；Sample colour classify 比对色票 ROI 的直方图，相似度不足时走 NG 分支 | `color_classify``judge` |
| 矩形板角点与歪斜 | 深色背景上的亮色矩形板；第四张板件过宽且歪斜超出公差 | 同一零件用两种方式测量：Find rectangle 直接报告已标定矩形，四次找边则送入 Corners from four edges。宽度公差会拒绝不良板件 | `find_line``find_quadrilateral``find_rectangle``judge``tolerance_judge` |
| 槽宽与条纹数 | 板件有深色槽与五条参考条纹；第四张槽宽过大 | Pair-edge search 在单一步骤测量槽的两侧，多线搜索则计算图像其他位置的参考条纹 | `find_lines_multi``find_parallel_lines``if_number``in_range` |
| 孔矩阵完整性 | 3×3 深色孔阵列；第四张缺少一个孔 | Find circle matrix 将区域分成网格、测量每个孔，并在某个格位无孔时报告缺格索引 | `count_list``find_circles_matrix``judge` |
| 边缘趋势与剖面峰值 | 直板边缘有四个亮色参考标记；第四张边缘有局部凸起 | Edge trend 沿教导边缘排列卡尺，并报告局部凸起造成的缺失样本。Peak search 会从矩形灰阶剖面读出四个参考标记 | `count_list``edge_trend``if_number``judge``peak_search` |
| 教导轮廓缺陷比对 | 自由外形冲压件：正向、平移、往另一侧平移，最后崩边 | 固定定位裁切会教导位姿；Template match 与 Locate offset 修正平移样本，Edge model defects 先由固定参考图教导良品外形，再检查实时边缘 | `edge_model_defect``fixed_image``judge``shape_align``template_match` |
| 沿路径搜索边缘 | 亮色胶条沿着教导路径分布；第四张有断点 | Path extract 沿教导路径放置卡尺，返回找到的边缘点与缺失索引，再由缺失样本数驱动判定 | `count_list``if_number``path_extract` |
| 检查前焦距闸门 | 锐利目标含细线与文字；第四张图像模糊 | Sharpness 在其余检查前先作为闸门，也报告高频噪声估计，避免把噪声误认为对焦 | `judge``sharpness` |
| 跨帧平均与前帧差异 | 四个帧中有两个亮色零件；第四个帧新增一个零件 | Frame accumulate 输出两帧平均，Previous image 将当前帧与上一个缓存平均输出比对。第一个帧无前一张图像，会正确报告 not found 而不是错误 | `arithmetic``blob``frame_accumulate``if_number``previous_image``threshold` |
| 处理区域后贴回 | 板件有三个深色特征；第四张在处理区域内多了一个标记 | ROI 会先裁切、以 look-up table 增强、滤波，再贴回完整图像。完整画面检查接着在同一 ROI 计算深色特征 | `blob``crop``filter``if_number``lut``paste_back``threshold` |
| 手动校正与零件坐标 | 板件有两个基准孔；第四张孔距过大 | Manual lens correction 校正图像，两次找圆定义零件坐标系，seed 建立的 0.05 mm 像素比例标定会把孔距换算成毫米进行公差检查 | `coordinate``distance``find_circle``judge``to_world``tolerance_judge``undistort` |
| 映射到第二相机 | A 相机基准孔位于三个位置；第四张无孔 | 找到的孔中心会通过 seed 建立且名为「Example: camera mapping (A→B)」的仿射相机映射资产，转成 B 相机坐标并格式化 | `find_circle``format_text``judge``map_points` |
| 教导姿态取料补正 | 教导零件先正向，再平移并旋转；第四张无零件 | Template match 找到教导零件，Alignment offset 以 grab 模式将教导取料点旋转和平移到当前图像位姿 | `align_offset``fixed_image``format_text``judge``template_match` |
| 整张回正后重跑量测 | 带标记板件经平移与旋转；第四张有一段带宽超出公差 | 定位标记驱动 Locate offset，Image follow 将整张图像变换回教导位姿，固定坐标卡尺即可每次测量同一条带 | `caliper``fixed_image``image_fixture``judge``shape_align``template_match``tolerance_judge` |
| 双视野拼接计数 | 左视野有两个零件，搭配固定右视野；第四张左视野缺少一个零件 | Image stitching 将实时左视野与固定右视野合成 1×2 格状图像，下游计数即可把两个相机画面视为同一张图像 | `blob``fixed_image``if_number``stitch_images``threshold` |
| 条码／QR 读取 | 倾斜标签含 QR code；第四张无印码 | 最短识别流程：读码、检查是否读到内容、输出内容 | `barcode``if_number` |
| 解码、拆消息与比对 | QR 消息带有批号与料号字段；第四张使用错误批号格式 | 代码 payload 按分隔符拆分，以正则表达式检查批号字段，并格式化简短文本回复给主机系统 | `barcode``format_text``parse_message``string_match` |
| 定位后读码 | 大型杂乱背景中有一个移动的小 QR code；第四张无码 | 示范难读码的接线：template matching 找到码区，ROI follow 将裁切区移到其上，crop 放大后让解码器只读该小区块；教导检测器可通过 matches 端口连接到同一接线 | `barcode``crop``fixed_image``judge``resize``shape_align``template_match` |
| 日期码读取与验证（教导字体） | 白色标签含八位数代码；第四张有一位数被污点遮住 | seed 会由 24 行渲染文字教导数字字体，包含分割与小型分类器，完全离线且不需要 OCR 模型文件；Text read 输出字符串与每字符置信度，Text verify 检查八位数模板与置信度，并在 NG 图像以红框标出被污损的数字 | `judge``ocr_read``ocv_verify` |
| 含透视校正的条码标签 | 同一组图像 | 四点透视校正会先校正倾斜标签再读取，并在序号区做文字存在检查 | `barcode``judge``text_presence``warp_perspective` |
| 形状比对定位（任意角度、任意光线） | 非对称支架：正向、旋转 37° 且变暗、在杂乱中旋转 −120°；第四张为不同零件 | Shape match 会评分边缘方向，因此旋转、变暗与杂乱中的图像都能以高分找到，并提供给 Locate offset 与 ROI follow；不同零件低于分数下限而走 NG 分支。形状模型资产由 seed 从第一张图建立 | `fixture_roi``intensity``judge``shape_align``shape_match` |
| 定位与测量 | 十字标记与亮色带；第四张亮带太宽 | 三段式定位补正：template match → ROI follow → 卡尺宽度。模板资产由 seed 自动裁切 | `caliper``fixed_image``in_range``judge``shape_align``template_match` |
| 深冲杯件测量 | 同心杯缘与壁厚截面；第四张外径超差 | 完整测量流程：定位、三个跟随定位的 ROI、外径与内径找圆、穿过壁面的**线 ROI**量厚度、同心度，以及多个公差合并判定 | `bool_logic``concentricity``find_circle``fixed_image``judge``shape_align``template_match``tolerance_judge``wall_thickness` |
| 输送带取料（单相机） | 六张合成输送带帧；零件沿皮带移动，第一张与最后一张碰到边界 | 单相机取料交握：分割、边缘过滤、平台追踪与确认、格式化 `cls,x,y,z` 文本，以及机械手臂写出 | `ai_segment``edge_filter``format_text``track_objects``write_modbus` |
| 输送带取料（ByteTrack） | 同一组六张输送带帧 | 分割工具使用内置 ByteTrack 追踪器，让每个零件保有一个 tracker ID；`track_objects` 以追踪器参考模式依该 ID 确认，而不是自行比对位置 | `ai_segment``edge_filter``format_text``track_objects``write_modbus` |
| 输送带取料（双视野） | 已知视差的合成输送带零件立体图像对 | 立体取料交握：成对取像、分割、边缘过滤、追踪确认、由 `stereo_depth` 取得物件顶面 Z、格式化 `cls,x,y,z` 文本，以及机械手臂写出 | `ai_segment``edge_filter``format_text``stereo_depth``stereo_grab``track_objects``write_modbus` |
| 按变量切换配方 | 默认配方有三个亮点；第四张对该分支而言太暗 | 读取配方变量，用 switch 分流到亮或暗阈值分支，再保存累计数。Sample mode 使用变量覆盖层，因此不会持久化站台值 | `blob``judge``switch``threshold``variable_get``variable_set` |
| 影像切片逐格巡检 | 2×2 面板图像；第四张某一格有斑点，但 sample mode 只示范子流程接线 | Tile 建立四个区域，For each 会以 sandbox mode 对每格调用 seed 建立的示范流程，直接的 Call flow 节点则示范非循环版本 | `call_flow``for_each``judge``tile` |
| 灯源、相机 I/O 与设备信号 | 三个亮色信号点；第四张缺少一个点 | 流程会套用相机设置、设置环形光源、检查亮点，接着脉冲输出站台与相机输出并读取 Modbus。缺少连接时会降级为警告 | `blob``camera_io``camera_set``if_number``io_output``judge``read_modbus``set_light``threshold` |
| 记录、存图、送图与触发 | 三个方形零件；第四张多了一个零件 | 计数会格式化成文本、写入 CSV 记录、保存 NG 图像、送出结果影像给图像主机，并触发审计流程。Sandbox mode 会报告 Would actions 导出图像包含物体标记，并以具名输出将测量面积取至两位小数。 | `blob``draw_result``format_text``if_number``judge``output``save_image``send_image``threshold``trigger_flow``write_log` |
| AI 目标计数（官方底模） | 停止标志；第四张有一个，第五张有三个 | 无需训练的深度学习：官方底模可直接识别并判定数量。权重会在首次执行时下载，需要深度学习依赖 | `ai_detect``if_number` |
| AI 实例分割：标志面积 | 同一组图像 | 分割的并集掩膜进入像素计数得到总面积，再依阈值判定，是分割接到下游测量的示例 | `ai_segment``judge``pixel_count` |
| 库存分类器闸门 | 四张小型合成产品卡，颜色与形状各不相同 | 库存分类器输出 ImageNet 标签，接着 `string_match` 示范按标签分流。合成产线零件未必会命中允收标签；实务可训练分类器或设置 `pass_labels` | `ai_classify``string_match` |
| 倾斜工件的旋转框 | 四个倾斜矩形零件 | 旋转框官方底模接入后处理链：`ai_obb` 返回旋转框，`list_sort` 按角度排序，`format_text` 建立精简角度报表 | `ai_obb``format_text``judge``list_sort` |
| 关键点与几何 | 四张类似火柴人的样本 | `ai_pose` 返回姿态框与关键点列表。此模板以检测数量作为闸门；在教导关键点项目中，同一输出也可接到几何与距离检查 | `ai_pose``if_number` |
| 分类：良品／缺孔（教导模型） | 深色背景上的亮色圆片；第五与第六张缺少中心孔 | 示范教导模型如何进入流程：seed 以 30 张合成样本与数据增强训练内置 MLP，成为「Example: classifier (good / missing hole)」，再由 `dl_classify` 判定通过或失败。整张缩小图像分类适合整体外观不同的类别 | `dl_classify``judge` |
| 异常检测：只教良品（教导模型） | 分割教导板件，三张干净、两张有划痕 | 安装异常 backbone 时，seed 会以 20 张干净板件建立「Example: anomaly (scratch plate)」；`dl_anomaly` 会把每个 patch 与良品内存库比对，即使训练时未曾看过划痕，划伤板也会成为异常。无 backbone 时模板仍可载入，模型留给您选择 | `dl_anomaly``if_number` |
| 语义分割：划痕面积（教导模型） | 有纹理的面板；第四与第五张有划痕 | seed 以 10 张多边形标记图像训练 patch_segment，成为「Example: segmenter (scratch)」，再由 `dl_segment` 依划痕面积阈值判定 | `dl_segment``judge` |
| 教导式检测与实例模型 | 倾斜零件样本组 | `dl_detect` 与 `dl_instance` 并排放置，模型字段留空。请在深度学习页训练检测或实例分割项目，再于此选择那些 ONNX 模型资产 | `dl_detect``dl_instance``judge` |
| 免重训扩充的检索库 | 三张已知 part_a 查询图与一张无关零件图 | 安装异常 backbone 时，seed 会建立三类、每类两张参考图的检索库。`dl_retrieval` 接受预期标签，并将低相似度图像送到 `not_matched`；日后新增类别只需加入参考图像，不需要重新训练 | `dl_retrieval``if_number``judge` |
| 四向打光融合表面缺陷 | 四张 2x2 拼图，每张都是同一表面在四个打光方向下的图像；第四张在 270 度视角有划痕 | 裁切四个视角，以 shadow mode 的 `multi_light_fuse` 融合，只保留不同方向间会变化的内容，并将划痕检测为强起伏；`multi_light_grab` 连接到样本，用于示范线上采集 | `blob``crop``if_number``multi_light_fuse``multi_light_grab``threshold` |

## 图像与资产位置 {#files}

- 样本图像：`data/samples/<set>/01.png…`，由 `apps/vision/demo_images.py` 产生。若文件夹已有 PNG，会直接重用。要重新产生时，删除该文件夹并再次执行 `manage.py seed_demo`。
- 固定图像：每张样本图与参考图只会保存一次，位置在 `ASSET_DIR/fixed/<sha>.png`，以内容定址，因此重复 seed 不会产生副本，并由模板 graph 参照；`instantiate` 会把 `{SOURCE}` 采集步骤转成持有该组图像的 `fixed_image` 步骤。不再建立文件夹来源或图像资产，旧版 seed 留下的「Example: …」文件夹来源与图片资产在无引用时会移除。
- 资产：由 30 张抖动良品打印建立的统计模板，从第一张形状比对图像建立的支架形状模型，以及教导模型，位于「Examples」分组。两个定位模板、Golden 打印图与冲压件外形会从第一张样本图裁成固定图像，平场模板的白参考也是固定图像。
- `seed_demo` 可安全重复执行：既有来源与资产会重用，流程 graph 会更新到当前版本。

## 尚无模板使用的工具 {#not-included}

无。每个内置工具现在都至少由一个画廊模板代表。`dl_detect` 与 `dl_instance` 等模型特定工具仍需要站台训练的模型资产才能执行，因此其画廊模板是只示范 graph 接线的示例。

## 如何维持正确 {#test}

深度学习模板：`tests/test_demo.py` 会实际执行可快速 seed 的教导模型模板；设置 `VISION_TEST_DL=1` 且官方权重已可用时，也会执行官方模型模板。需要外部训练模型资产的模板，例如 `dl_detect_instance_demo`，会在您选择模型前先检查 graph 层级。

`tests/test_demo.py` 每次测试都会把整组示例 seed 到暂存环境，并以对应样本来源执行每个内置模板，锁住「每个模板都可执行且无任何节点错误」这句话。模板或工具一旦坏掉，测试会立即变红。
