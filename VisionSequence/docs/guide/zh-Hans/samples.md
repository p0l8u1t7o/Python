# 示例模板与合成样本图像

示例模板位于**模板画廊**中，即「流程」页的「从模板建立」与编辑器顶栏的「载入模板」，共有 37 个内置模板，因此不会让流程列表变得杂乱。`manage.py seed_demo` 或 `dev.ps1 -Setup` 会建立与它们搭配的一切：两条示范流程、每个模板各一组合成样本图，这些图会以**固定图像**保存并随模板移动；参考图，也就是定位模板、Golden 打印图与白参考，会以固定图像连接到工具的图像输入端口；统计模板、形状模型与教导模型资产也会一并建立。从模板建立流程后保留来源不变即可，每个模板都以内含自身样本图的 Fixed image 步骤开始，因此可**原样执行**。采集步骤会成为 Fixed image 步骤，逐次循环样本图，第四张通常是刻意安排的 NG。146 个内置工具中有 88 个至少出现在一个模板内，因此打开任一模板即可看到该工具实际如何接线，以及参数在实务中如何设置。

每组有四张图像，教学模板为三张，最后一张刻意设为 NG。来源会循环，因此连续执行或反复按「执行」会得到 OK → OK → OK → NG。坐标与公差都符合合成图像的标称值，所以开始使用前不需要调参。

## 模板列表 {#list}

| 模板 | 样本图像 | 教导重点 | 主要工具 |
|---|---|---|---|
| 孔洞计数 | 亮色板件有四个角孔与较大的中心孔，并旋转数度；第四张缺少一个角孔 | 最基本的骨架：threshold → blob → count → 依数量分支 | `grayscale``blur``threshold``morphology``blob``if_number``judge``output``draw_result` |
| 曝光检查 | 同一片板件的四种曝光：正常、偏暗、偏亮与过曝；第四张超出范围 | 纯预处理与逻辑的把关流程：缩小加速，并以 Otsu 阈值作为曝光指标 | `resize``threshold``in_range` |
| 圆规测量 | 亮色板件搭配深色孔洞；第四张超出公差 | 找圆、把像素转成毫米，再依公差判定。也示范**扇形 ROI**，也就是带起讫角的环形 ROI，用于弧线拟合，以及用椭圆拟合评估圆度 | `find_circle``formula``calibration``tolerance_judge``fit_arc``fit_ellipse` |
| 边角角度 | L 形零件；第四张为 84°，右下有 45° 倒角 | 两次找线得到角度与交点；倒角工具测量斜边 | `find_line``angle``geometry``chamfer_angle``in_range` |
| 打印比对 | 一个打印图案；第四张多了一块污点 | 与 Golden 模板做差异比对，可找出事先无法描述的缺陷。模板资产由 seed 建立 | `defect_diff` |
| 统计打印比对 | 打印比对图像，第四张有污点 | seed 会由 30 张抖动的良品打印建立统计模板，亮度 ±8、位移 ±3 px；`defect_stat` 会标出每个像素超过自身正常值 4 个标准差的位置，因此照明与纹理变化不会迫使阈值放宽 | `defect_stat``if_number` |
| 织物缺陷 | 周期性织纹；第四张有划痕 | 频域低通会抹除规则纹理并留下深色痕迹，也就是缺陷。遮罩会取出缺陷区域 | `fft_filter``threshold``blob``apply_mask` |
| 预处理与测量实验室 | 渐变、灰阶阶梯楔与深色沟槽 | 图像链，包含位深 → gamma → 锐化 → 翻转 → 前后差异；并巡览测量工具：线剖面、区域统计、直方图、边缘密度、暗区比例、裁切与色彩平面 | `convert_depth``lut``filter``rotate_flip``arithmetic``line_profile``intensity``histogram``edge_density``dark_ratio``crop``color_convert` |
| 圆与线 | 五个孔与两条斜线；第四张缺少一个孔 | 示范 Hough 可一次找出多个圆，find-circle 可精准测量单一圆；并计算线段列表数量与两个孔中心距离 | `hough_circles``hough_lines``count_list``find_circle``distance` |
| 齿轮齿数（极坐标展开） | 深色背景上的亮色十二齿齿轮；第四张缺齿 | Polar unwrap 会把齿根与齿尖之间的环带摊平成条带，让每个齿成为亮区块、每个间隙成为暗栏；threshold 与 blob 计算区块，Polar restore 在原图上标示各齿。起始角放在间隙，因此接缝不会切开齿形 | `polar_unwrap``threshold``blob``if_number``polar_restore` |
| 边缘缺口（轮廓几何） | 深色背景上的亮色冲压件，含孔与槽；第四张上缘被咬掉一块 | Contour find 追踪外形，filter 只保留最大轮廓，也就是零件；contour geometry 计算深度超过 12 px 的凸性缺陷，即缺口。Contour match 以 Hu moments 与样本外形资产比对轮廓，用于防止零件错误或严重变形 | `contour_find``contour_filter``contour_geometry``contour_match``if_number` |
| 圆边缺口（圆形卡尺） | 亮色圆片有中心孔；第四张右下外缘有 24° 缺口 | 180 个径向卡尺每 2° 给出半径与径向跳动；Profile defects 会对边缘点拟合圆，并标记低于该圆 3 px 的每一段，或卡尺完全找不到边缘的位置。缺口会在外缘画成红色弧段 | `circular_caliper``profile_defect``if_number` |
| 圆度（形位公差） | 缺口圆片组：亮色圆片有中心孔；第四张右下外缘有 7 px 深缺口 | 180 个径向卡尺给出边缘点；Form and position tolerance 拟合最小区域圆（ISO 1101），同心双圆之间的环宽在 5 px 内即通过。明细也报告最小二乘值与两个极值点 | `circular_caliper``gdt_measure` |
| 浮凸字符与凹痕（光度立体） | 同一片板件在四向打光下的 2×2 图像，光源来自右、下、左、上；板件有斑驳反射率与浮凸字样「VS 42」；第四张在字符上方检查区有凹痕 | 四个 Crop 步骤切出各视角，Photometric stereo 转成形状强度图，斑驳消失后只留下表面形状，再以检查区中的像素计数找出单张图像看不到的凹痕。良品答案是空区，所以用像素计数而非 blob 计数判定 | `crop``photometric_stereo``pixel_count` |
| 条码质量等级（ISO 15415） | 白色标签含 Data Matrix 与料号；四种打印质量为干净、低对比、模糊且有噪声，以及静区有脏污的符号 | Barcode quality grade 像验证器一样测量符号，C 级以上通过；parameters 输出会说明哪一项参数拉低等级，第四张标签会失败 | `barcode_grade` |
| 排除区（组合区域） | 圆规测量板件：亮色板件的深色中心孔会改变大小 | 两个 Region 步骤画出孔与标签区，Region combine 从板件矩形中切除它们，并把组合区域经由区域输入提供给统计与 blob 步骤。即使孔变大，板件平均值仍保持稳定，因为孔的像素从未计入 | `region_from_shape``region_combine``intensity``in_range``blob` |
| 平场校正（不均匀照明） | 亮色板件在强烈暗角下有深色斑点，角落亮度只有 45%；第四张多了一个大标记 | 除以白参考资产可摊平照明，因此固定阈值能找到所有斑点；侧支路用同一阈值跑未校正图像，计数会错。参考图由 seed 写入 | `shading_correct``threshold``blob``if_number` |
| 颜色存在 | 三个色块；第四张红色偏橙 | HSV 范围遮罩进入像素计数，用于典型存在／缺失判定 | `color_range``pixel_count` |
| 颜色验证 | 同一组图像 | 以距离比对区域平均色与目标色；色彩统计会输出十六进制色码给主机系统 | `color_check``color_stats` |
| 条码 / QR 读取 | 倾斜标签含 QR code；第四张没有印码 | 最短识别流程：读码、检查是否读到内容、输出内容 | `barcode``output` |
| 定位后读码 | 大型杂乱背景中有一个移动的小 QR code；第四张无码 | 示范难读码的接线：检测器找出可能的码区，ROI follow 移动裁切区，crop 放大后让解码器只读该小区块。内置检测器尺寸仅用于示范连接；在线上使用前应先为码的位置训练检测器 | `ai_detect``shape_align``fixture_roi``crop``resize``barcode` |
| 日期码读取与验证（教导字型） | 白色标签含八位数代码；第四张有一位数被污点遮住 | seed 会由 24 行渲染文字教导数字字型，包含分割与小型分类器，完全离线且不需要 OCR 模型文件；Text read 输出字符串与每字符置信度，Text verify 检查八位数模板与置信度，并在 NG 图像以红框标出被污损的数字 | `ocr_read``ocv_verify` |
| 透视校正条码标签 | 同一组图像 | 四点透视校正会先拉正倾斜标签再读取，并在序号区做文字存在检查 | `warp_perspective``barcode``text_presence` |
| 形状比对定位（任意角度、任意光线） | 非对称支架：正向、旋转 37° 且变暗、在杂乱中旋转 −120°；第四张为不同零件 | Shape match 会评分边缘方向，因此旋转、变暗与杂乱中的图像都能以高分找到，并提供给 Locate offset 与 ROI follow；不同零件低于分数下限而走 NG 分支。形状模型资产由 seed 从第一张图建立 | `shape_match``shape_align``fixture_roi``intensity` |
| 定位与测量 | 十字标记与亮色带；第四张亮带太宽 | 三段式定位补正：template match → locate correction → ROI follow → 卡尺宽度。模板资产由 seed 自动裁切 | `template_match``shape_align``fixture_roi``caliper` |
| 深拉杯测量 | 同心杯缘与壁厚截面；第四张外径超差 | 完整测量流程：定位、三个跟随定位的 ROI、外径与内径找圆、穿过壁面的**线 ROI**量厚度、同心度，以及多个公差合并判定 | `find_circle``wall_thickness``concentricity``tolerance_judge``bool_logic` |
| 输送带取料（单相机） | 六张合成输送带帧；零件沿皮带移动，第一张与最后一张碰到边界 | 单相机取料交握：分割、边缘过滤、平台追踪与确认、格式化 `cls,x,y,z` 文字，以及机械手臂写出 | `ai_segment``edge_filter``track_objects``format_text``write_modbus` |
| 输送带取料（ByteTrack） | 同一组六张输送带帧 | 分割工具使用内置 ByteTrack 追踪器，让每个零件保有一个 tracker ID；`track_objects` 以追踪器参考模式依该 ID 确认，而不是自行比对位置 | `ai_segment``edge_filter``track_objects``format_text``write_modbus` |
| 输送带取料（立体 Z） | 已知视差的合成输送带零件立体图像对 | 立体取料交握：成对取像、分割、边缘过滤、追踪确认、由 `stereo_depth` 取得物件顶面 Z、格式化 `cls,x,y,z` 文字，以及机械手臂写出 | `stereo_grab``ai_segment``edge_filter``track_objects``stereo_depth``format_text``write_modbus` |
| AI 物件计数（官方底模） | 停止标志；第四张有一个，第五张有三个 | 无需训练的深度学习：官方底模可直接识别并判定数量。权重会在首次执行时下载，需要深度学习依赖 | `ai_detect``if_number` |
| AI 实例分割：标志面积 | 同一组图像 | 分割的并集遮罩进入像素计数得到总面积，再依阈值判定，是分割接到下游测量的示例 | `ai_segment``pixel_count` |
| 分类：良品 / 缺中心孔（教导模型） | 深色背景上的亮色圆片；第五与第六张缺少中心孔 | 示范教导模型如何进入流程：seed 以 30 张合成样本与数据增强训练内置 MLP，成为「Example: classifier (good / missing hole)」，再由 `dl_classify` 判定通过或失败。整张缩小图像分类适合整体外观不同的类别 | `dl_classify` |
| 异常检测：只有良品（教导模型） | 分割教导板件，三张干净、两张有划痕 | 安装异常 backbone 时，seed 会以 20 张干净板件建立「Example: anomaly (scratch plate)」；`dl_anomaly` 会把每个 patch 与良品内存库比对，即使训练时未曾看过划痕，划伤板也会成为异常。没有 backbone 时模板仍可载入，模型留给您选择 | `dl_anomaly``if_number` |
| 语义分割：划痕面积（教导模型） | 有纹理的面板；第四与第五张有划痕 | seed 以 10 张多边形标记图像训练 patch_segment，成为「Example: segmenter (scratch)」，再由 `dl_segment` 依划痕面积阈值判定 | `dl_segment` |

## 图像与资产位置 {#files}

- 样本图像：`data/samples/<set>/01.png…`，由 `apps/vision/demo_images.py` 产生。若文件夹已有 PNG，会直接重用。要重新产生时，删除该文件夹并再次执行 `manage.py seed_demo`。
- 固定图像：每张样本图与参考图只会保存一次，位置在 `ASSET_DIR/fixed/<sha>.png`，以内容定址，因此重复 seed 不会产生副本，并由模板 graph 参照；`instantiate` 会把 `{SOURCE}` 采集步骤转成持有该组图像的 `fixed_image` 步骤。不再建立文件夹来源或图像资产，旧版 seed 留下的「Example: …」文件夹来源与图片资产在无引用时会移除。
- 资产：由 30 张抖动良品打印建立的统计模板，从第一张形状比对图像建立的支架形状模型，以及教导模型，位于「Examples」分组。两个定位模板、Golden 打印图与冲压件外形会从第一张样本图裁成固定图像，平场模板的白参考也是固定图像。
- `seed_demo` 可安全重复执行：既有来源与资产会重用，流程 graph 会更新到当前版本。

## 尚无模板使用的工具 {#not-included}

深度学习：`ai_pose` 需要人物图像，`ai_obb` 需要训练或 DOTA 风格图像，而 `ai_classify`、`dl_instance` 与 `dl_detect` 的接线方式与已涵盖的对应工具相同。`dl_classify`、`dl_detect`、`dl_segment` 与 `dl_instance` 都需要先在深度学习教导页训练模型资产。`write_modbus` 与 `read_modbus` 需要实际的 Modbus 连接，`python_script` 会执行您自行编写的程序代码，而 `save_image` 会在每次执行写出文件，不适合放进循环示例。请参考各工具自身说明，以及[深度学习教导](dl.md)与 [Modbus](/docs/modbus.html)。

## 如何维持正确 {#test}

深度学习模板：`tests/test_demo.py` 会实际执行两个教导模型模板，seed 会在 CPU 上于数秒内完成训练。三个官方模型接线模板需要深度学习依赖，因此该处只检查 graph；真正执行由 `VISION_TEST_DL=1 manage.py test tests.test_dl_live` 负责，五张标志样本会得到 OK、OK、OK、NG、NG。

`tests/test_demo.py` 每次测试都会把整组示例 seed 到暂存环境，并以对应样本来源执行每个内置模板，锁住「每个模板都可执行且没有节点错误」这句话。模板或工具一旦坏掉，测试会立即变红。
