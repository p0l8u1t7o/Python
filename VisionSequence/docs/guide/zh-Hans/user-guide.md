# 用户指南

本指南依侧栏由上到下介绍：每个页的位置、页内内容与可执行的操作。每一节都以截图开头，图上的编号标记对应下方编号列表。截图显示英文界面；中文界面版面相同，只是标签已翻译。本指南也是产品内的说明页（侧栏 › 说明），会依界面语言显示，并与工具目录一起提供。

## 1. 浏览界面 {#shell}

<figure class="shot"><img src="/docs/img/shell.jpg" alt="总览上的应用程序外框"><figcaption><b>总览</b>（侧栏 › 总览，路由 <code>/</code>）
<ol class="callouts">
<li data-n="1"><strong>侧栏</strong>依工作内容分组：<strong>检测</strong>（流程、批量测试、AI 助手）、<strong>教导</strong>（站台参数卡、标定、深度学习教导）与 <strong>资源</strong>（图像来源库、资产库），再加上会展开子页的外部集成与管理页。分组可点击开合并记住状态；您的角色无权使用的项目会隐藏，若分组内没有可用页，该分组会消失。底部的「折叠侧栏」会缩成图标；在手机上则变成 ☰ 按钮后方的抽屉。</li>
<li data-n="2"><strong>面包屑</strong>显示当前位置（总览 › 流程 › 流程名称），每一段都是返回链接。</li>
<li data-n="3"><strong>容量</strong>指示器：显示引擎 worker 忙碌数与缓存图像数；点击可查看明细。</li>
<li data-n="4"><strong>用户菜单</strong>：当前登录者、修改密码、退出。绿点代表引擎空闲；集成方锁定引擎时，顶栏下方会出现横幅（见 <a href="#lock">15. 引擎锁定</a>）。</li>
<li data-n="5"><strong>AI 助手</strong>按钮可在每页使用（见 <a href="#assistant">14. 全局助手</a>）。</li>
<li data-n="6"><strong>流程列表</strong>：每条流程一张卡片，显示最后结果与执行次数。选取卡片后，中间显示实时图像，右侧显示判定与输出值。</li>
<li data-n="7">卡片上的<strong>执行一次</strong>会立即执行已保存流程，不需要打开编辑器。</li>
<li data-n="8"><strong>统计</strong>快捷方式会打开该流程的执行历史、良率趋势与图像归档。</li>
</ol></figcaption></figure>

尚无执行时，中间区域会显示「等待下一次检测」；一旦外部触发、连续模式或「执行一次」产生执行，图像、标记与结果会实时显示在该处。

### 1-1. 从另一台 PC 使用站台 {#another-pc}

您的 PC 不需要安装任何项目：在 Chrome、Edge（111 或更新）、Firefox（128+）或 Safari（16.4+）打开站台地址，例如 `https://<station name>/`，或管理员提供的地址。第一次在新 PC 上使用时，浏览器可能提示证书警告：管理员有一个小文件 `root.crt`，导入一次即可（[方式](/docs/deployment.html#https)）。语言与主题会与账号一起保存，因此您从任何 PC 登录都会看到相同外观；共享 PC 上离开时请退出，这会清除该浏览器中的助手对话与命令历史。若画面保持空白并显示浏览器版本通知，代表该 PC 的浏览器需要更新；站台本身正常。

## 2. 登录、角色与权限 {#login}

<figure class="shot"><img src="/docs/img/users.jpg" alt="用户页"><figcaption><b>用户</b>（侧栏 › 用户，仅管理员）
<ol class="callouts">
<li data-n="1"><strong>新增用户</strong>：用户名、显示名称、角色与密码。</li>
<li data-n="2">账号表：变更角色、停用账号、重设密码。</li>
<li data-n="3"><strong>角色权限</strong>：逐项勾选工程师与操作员可使用哪些功能。</li>
</ol></figcaption></figure>

- 尚无用户时，登录页会提供「建立第一个管理员」，并以该账号登录。集成方使用 API 密钥，从不登录。
- 系统有**三种角色**；下表是出厂设置，角色权限卡可调整：

| 角色 | 可执行 | 不可执行 |
|---|---|---|
| 管理员 | 全部功能，包含账号、连接与系统设置 | — |
| 工程师 | 建立与编辑流程、图像来源与资产；深度学习教导、批量测试、Golden Set 回归；变更任何参数 | 账号、主动输出连接、系统设置 |
| 操作员 | 执行检测、启停连续模式、换线（切换绑定配方）、在参数卡调整**现场参数**、查看统计 | 变更流程结构、训练模型、批量测试、编辑来源或连接 |

- **角色权限**：可从工程师移除深度学习教导，将批量测试或操作记录交给操作员，或委派主动输出连接。管理员永远拥有全部功能且无法取消勾选，因此不会把自己锁在外面。服务端会检查每个请求，未勾选的功能即使直接输入网址也无法进入；侧栏与按钮会直接消失。
- **流程属于产线，不属于个人**：每位工程师都能看到并编辑每条流程（Owner 栏只记录建立者），因此工程师离职不会留下无人拥有的流程。
- **现场参数**是工具作者标为教导参数的项目，例如阈值或 blob 的最小面积。操作员在参数卡变更这些值会直接写回流程；变更其他参数或结构会被服务端拒绝。哪些参数属于现场参数，会显示在工具页参数表的「On-site」栏。

## 3. 流程页与模板 {#flows}

<figure class="shot"><img src="/docs/img/flows.jpg" alt="流程页"><figcaption><b>流程</b>（侧栏 › 流程）
<ol class="callouts">
<li data-n="1"><strong>建立检测任务</strong>会建立空流程并打开其检测任务页。</li>
<li data-n="2"><strong>建立进阶流程</strong>会建立空流程并打开画布编辑器。</li>
<li data-n="3"><strong>从模板建立</strong>会打开模板画廊。</li>
<li data-n="4"><strong>导入</strong>会载入导出成 JSON 的流程，可来自另一站或版本控制。</li>
<li data-n="5">每条流程：<strong>检测任务</strong>打开该流程的任务页；点选整行也一样。</li>
<li data-n="6"><strong>更多</strong>：参数卡、Golden Set、统计、导出、复制与删除。铅笔图标打开画布。</li>
<li data-n="7"><strong>配方</strong>：换线用的参数集。</li>
</ol></figcaption></figure>

**模板画廊**有六十多个内置模板，并**依类别分组**：教学、计数、测量、质量、缺陷、识别，接着是您的自定义模板；卡片上方有筛选行。每个内置模板都带有合成样本图：来源保持「模板的样本图」时，采集步骤会成为 **Fixed image** 步骤，每次执行取下一张样本图（多数分组第四张是刻意安排的 NG），因此新流程可立即执行；相机准备好后再选真实来源。您自己的流程也可存为模板供其他人重用。详见[示例模板](samples.md)。

导出与导入使用稳定 JSON 格式，因此流程可放进版本控制并在站台间移动；导入时界面会询问要绑定哪个图像来源。请参考 [Golden Set 与导出](golden.md)。

### 3-1. 检测任务页：不必连线就能建立检测 {#inspect}

**检测任务**页（流程页每一行的按钮，或编辑器工具栏；路径 `/flows/:id/inspect`）用“任务清单”建立检测，而不是一个个步骤与连线。任务清单上方的**新增任务**会打开三步骤的引导：先选任务类型（定位工件、测直径、测距离、边缘缺陷、读码验证……），再在图像上画出区域，最后填写规格（标称值、上下公差、单位、标定）并点**建立任务**；旁边的**移除任务**删除当前选中的任务。页面会替您建好步骤、连线与整体合格判定，全程不需要工具箱，也不需要连线。

- **每个任务就是一个内置工具**：在这里新增的任务（或 AI 助手替您加的任务）会以工具箱“检测任务”分类里对应的内置检测工具（见[复合工具](#composite)）放到画布上，一个任务一个实例，任务清单以工具徽章标示。区域与规格就是这个工具的参数，所以同一个任务也能在工具页调整，高级流程里只看到一个步骤而不是好几个。此次改版之前创建的流程仍保留原本的多步骤任务，两种任务一起列出、用法相同。
- **图像来源**：选择来源、加入固定图像，或**上传临时图像**。没有图像时**试运行**会被拦下并提示原因。
- **读数与状态**：每个任务显示合格、不合格、测不到、定位失败、错误、跳过或尚未运行。必要任务不合格或被跳过，整体就判不合格——被跳过的检查绝不算通过。定位失败时，依赖它的任务会显示定位失败，而不是测到错误的位置。
- **过期**：修改规格之后，上次的读数会标为**过期**，直到您再点一次**试运行**。
- **上次的读数存在服务器**：试运行后页面会把这条流程的读数摘要存到服务器，所以换一台电脑或用全新的浏览器重新打开，也能看到上次的读数；流程之后若有变更，读数会标为过期。图像与示教功能需要重新试运行。
- **毫米**需要标定：表单会要求您先选一份标定，而不是悄悄回报像素值。
- **自定义**：如果在**高级流程**里改动了任务的步骤（加了步骤、换了工具、改了内部连线），该任务会标为**自定义**并列出原因，规格表单随之隐藏；可从原因旁的链接跳到该步骤。移动步骤位置，或修改任务没有管理的参数，任务仍可在此页编辑。
- **保存**会写回流程；若其他人在这段时间已经保存过，会出现保存冲突对话框，让您载入对方的版本、覆盖或取消。**高级流程**随时可打开完整流程图查看与调试。

定位可能旋转的工件：在**定位工件**从当前图像裁出定位标记作为模板，勾选允许旋转并设置角度范围；第一次试运行后，以这次结果示教基准姿态。定位标记请避免每 90° 对称的图形——单纯的十字在角度范围大时会有歧义。

AI 助手也能从对话建出同样的任务清单，请参考[从对话生成检测任务清单](agent.md#tasklist)。

### 3-2. 工程笔记 {#notes}

**工程笔记**（侧栏 › 图像检测 › 工程笔记，路径 `/notes`）把设置背后的理由——决策、经验、打光、标定、限制、公差依据、已知问题——记在它所适用的流程旁边。笔记可关联项目、料号、流程、配方与图像来源，附上佐证图像与运行 ID、适用条件与流程版本范围。检测规格本身永远以流程为准。

- 新笔记一律是**草稿**，只有**确认**后的笔记才会被 AI 助手引用。默认工程师可以确认自己的草稿；站台也可以改成必须由另一位工程师确认（`VISION_ENGINEERING_NOTE_SELF_CONFIRM=0`）。
- 建立替代笔记会写出一份替代旧笔记的新草稿：保存后旧笔记立即不再出现在助手的搜索结果，但历史会保留。撤回笔记不会删除它。
- 编辑器与检测任务页都有“此流程的笔记”链接；助手对话里记下的工程决策，也可以一键存成笔记草稿。

## 4. 流程编辑器 {#editor}

<figure class="shot"><img src="/docs/img/editor.jpg" alt="选取步骤的流程编辑器"><figcaption><b>流程编辑器</b>（流程 › 某条流程，路由 <code>/flows/:id</code>）
<ol class="callouts">
<li data-n="1">顶栏第 1 行：流程名称、<strong>保存</strong>、当前配方，以及连到参数卡的「未教导」徽章。其余都在右侧的流程导航与「更多」菜单。</li>
<li data-n="2">顶栏第 2 行：<strong>试执行</strong>、来源为文件夹或 Fixed image 时的<strong>图像序列试执行</strong>、「用上次图像重跑」、<strong>上传暂存图像</strong>与<strong>连续执行</strong>。批量测试在侧栏「图像检测」群组有自己的页面。</li>
<li data-n="3"><strong>新增工具</strong>会打开工具选择器（下一张图）；「新增注释」会放下一张便利贴。您在选择器收藏的工具会显示在下方，栏位底部的步骤列表可跳到指定步骤。</li>
<li data-n="4"><strong>画布</strong>：步骤与带类型的端口。从输出端口拖到下一步输入端口；只有同色端口能连接。</li>
<li data-n="5"><strong>图像窗口</strong>：选取步骤的前后图像与标记；下方行可切换输入、输出、前后对照，以及「叠加所有步骤标记」。</li>
<li data-n="6">右侧<strong>侧栏</strong>：标题、启用、颜色、「错误时继续」与所选步骤参数；其「结果」分页显示上次试执行。</li>
<li data-n="7"><strong>打开工具页</strong>前往该步骤的专属调整页。</li>
<li data-n="8"><strong>试执行</strong>会用当前画布执行，包含未保存变更。</li>
<li data-n="9">同一条流程四个页面共用的<strong>流程导航</strong>：检测任务、画布、参数卡、统计。</li>
<li data-n="10"><strong>更多</strong>：模板、配方、版本（历史与还原）、自动排版、折叠任务、Golden Set、导出、<strong>清空结果</strong>与<strong>清除执行记录</strong>（对话框会列出影响）。旁边图标是撤销与重做。</li>
</ol></figcaption></figure>

图像窗口工具栏包含**十字线**按钮。打开后会显示一条水平线与一条垂直线，拖拽任一条线即可测量图像位置。窗口会显示交点的图像 X/Y 坐标，并读取该点像素值。鼠标移过图像时也会显示光标信息栏，包含图像坐标与当前灰阶或 RGB 值；缩放与平移不会改变坐标系。

当编辑器同时有选取步骤的输入与输出图像时，主窗口可把第二张图像叠在第一张上。使用图像窗口工具栏中的**叠图透明度**混合前后图像。若两张图像尺寸不同，叠图会依自身尺寸居中，而不是拉伸到主图像大小，且窗口会标示尺寸不符。

使用图像窗口行的 **Grid** 可把编辑器切到格状视图。选择 1、2、4、6 或 9 格，再把每一格绑定到某个步骤与图像输出端口。格状版面与绑定会依流程记在此浏览器中，常用调整视图可重开，不必重新建立。

1. 将判定工具的分支端口接到步骤的 `_flow` 端口，可让该步骤成为条件式；每个步骤也会在 `_image` 端口直通图像，因此只产生数值的工具仍可放在图像链中间。
2. Ctrl+S 会保存。未保存变更会保留为草稿，离开后再回来仍存在；「执行一次」与「连续执行」使用已保存版本，「试执行」使用草稿。
3. 流程从文件夹来源或 Fixed image 步骤采集图像时会出现**图像序列试执行**。它一次试执行一张图像，显示当前图像序号与 OK/NG 计数，且可暂停或停止。它仍只是试执行：不进生产历史或统计。
4. Ctrl+F 打开节点搜索。它会比对步骤 id、标题、工具类型与已填参数值；Enter 跳到下一笔，Esc 关闭。撤销与重做共用同一份编辑历史：Ctrl+Z 撤销，Ctrl+Shift+Z 或 Ctrl+Y 重做。
5. **时间花在哪里？** 试执行后，每个步骤会显示耗时与细条：该次最慢步骤为红色，超过其一半者为橙色。「结果」分页也有**区间耗时**：选来源步骤与目标步骤后，会加总两者之间数据流路径上的所有步骤，分支路径只算一次。右键点击步骤并选 **Run to here**，只执行该步骤与其之前步骤；调整单一步骤时不必等完整流程。
6. **连线上的数值**：试运行后每条连线会显示它传送的值（数字、文字、true/false、列表的项目数）；图像不显示。底部缩放栏的标签按钮可以开关。旁边的自动排列按钮会依数据流从左到右排列，并依每个步骤实际的高度排列行距。
7. **清除结果**只清除当前显示内容：步骤颜色、耗时热度、标记、图像窗口标示与「结果」分页。不会编辑草稿、保存流程或调用服务端；下次试执行或执行会再次填入结果。
8. **未选取任何项目**时，侧栏显示**流程设置**（描述、连续执行间隔、流程超时、并行度、启用与「NG 时停止」），并在**更多设置**下显示三个按钮，各自打开一个对话框：**变量**，也就是此流程在执行间保留的值（计数、前一个零件、设备传来的批号），可在该处读取、变更或清除；**看板设置**，也就是此流程的操作员看板内容（见 [7-1](#board)）；以及**结果回报**，也就是每次执行后由哪个连接接收格式化文字行（见[自动化](/docs/automation.html)）。
9. **尚未选择图像来源？** 编辑器顶端会出现黄色横幅；从横幅下拉菜单挑选来源，或上传暂存图像，即可立刻试执行。选取采集步骤时，侧栏会以含预览缩略图的下拉菜单显示当前来源，并可直接切换来源。
10. **完全没有相机？** 加入 **Fixed image** 步骤（Source 类别）取代图像来源，并上传一张或多张图片到该步骤；它们会随流程保存，导出时一并带走，而且每次执行（包含试执行）会取下一张，因此反复按 Run 可走完整组图像。同一步骤若 role 设为 "reference"，可通过图像输入端口把模板、Golden 样本或白参考交给定位、Golden 比对或平场工具，不需要资产。
11. **想写一小段 Python？** Logic 类别有 "Python script" 工具：在工具页的代码编辑器编写 `def run(ctx)`，可读取 `ctx.image`、`ctx.inputs` 中的上游值、现场参数 `ctx.params['p1'..'p3']` 与 `ctx.roi()` 的区域，并返回数值、布尔、文字、数据、新图像与标记，选择通过或失败分支。输出端口固定为 value、result、text、data、image。脚本在引擎进程中受限制执行，包含允许列表导入、超时与只读输入图像；**只有管理员可编辑并保存它，这也代表批准**。其他人可查看与执行已批准脚本，并在参数卡调整现场参数，不需接触程序代码。

<figure class="shot"><img src="/docs/img/editor-flow-settings.jpg" alt="未选取任何项目时的流程编辑器侧栏"><figcaption><b>流程设置</b>（编辑器 › 点击画布空白处）
<ol class="callouts">
<li data-n="1">未选取任何项目时的<strong>侧栏</strong>：上方是<strong>流程设置</strong>（描述、连续执行间隔、流程超时、并行度、启用、「NG 时停止」），下方是<strong>更多设置</strong>。</li>
<li data-n="2"><strong>变量</strong>会以对话框打开流程变量：读取、变更或清除流程在执行间保留的值。</li>
<li data-n="3"><strong>看板设置</strong>会以对话框打开此流程的操作员看板设置（<a href="#board">7-1</a>）。</li>
<li data-n="4"><strong>结果回报</strong>会以对话框打开逐次执行回报规则，也就是哪个连接取得哪一条格式化文字；每个对话框都有自己的保存按钮。</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/tool-picker.jpg" alt="工具选择器"><figcaption><b>工具选择器</b>（编辑器 › 新增工具）
<ol class="callouts">
<li data-n="1">依名称或 key <strong>搜索</strong>。</li>
<li data-n="2"><strong>类别</strong>：取像、预处理、定位、测量、检测、深度学习、逻辑、输出。</li>
<li data-n="3">该类别的<strong>工具卡</strong>（图标、名称、key）。</li>
<li data-n="4">所选工具的<strong>明细</strong>：描述、输入与输出端口及其类型颜色，以及含默认值、范围与现场标志的参数表。星号代表收藏。</li>
<li data-n="5"><strong>加入画布</strong>，或双击卡片，会把步骤插入画布中央。</li>
</ol></figcaption></figure>

### 4-1. 复合工具 {#composite}

**复合工具**是用其他工具创建的工具：几个步骤接好线，加上一份**对外接口**，声明哪些内部端口是它的输入与输出、哪些内部参数出现在它的参数表。保存后它放在**工具库**（检测资源 › 工具库），并像内置工具一样出现在工具选择器；拖到画布、接线、在工具页调参数。所有使用它的流程都运行同一份实现。

- **封装成工具**（主路径）：在画布上选中步骤，右键选「封装成工具…」（或用多选面板的按钮），取名、给键与分类。选中的步骤换成一个步骤；跨越选择范围的连线变成它的端口，已发布的输出名称搬到新步骤上。
- **编辑工具**：双击复合工具步骤、从它的菜单选「打开工具画布」，或在工具库按「编辑」。工具的画布就是一般的编辑器，右侧多了**对外接口**面板：勾选要对外的内部端口、拖动或用箭头排序、取显示名称，勾选要对外的内部参数并标记操作员可教导的。试执行会把暂存图像送进每一个对外图像输入。
- **版本**：每次保存只要改到工具的步骤或接口就是新的一版（工具库看得到版本号）。放到画布上的步骤会记住放入时的工具版本并一直执行那一版，所以修改工具不会在您不知情时改变产线流程。工具有新版时，步骤上会出现小小的 **v*n*** 徽章，侧栏提供**查看差异**（参数、端口、步骤哪里不同）与**更新到 v*m***；保存工具前仍会先列出使用它的流程与工具。内置检测工具一律执行最新版。仍在使用中的工具不能删除。
- **只有两层**：流程使用工具，工具由内置工具组成。复合工具里不能再放复合工具，所以工具画布上的工具选择器不列复合工具、「封装成工具」也不可用。
- **内置检测工具**：工具选择器的**检测任务**分类里，每一种检测方式各有一个复合工具（量直径或真圆度、以模板／形状模型／注册图定位工件、以边对或孔心量距离、计数、以模板／blob／印刷检查有无、边缘缺陷（直线或自由轮廓）、读码、读文字并核对）。拖到画布、接上图像、画区域、在工具页填规格即可。它们只读；要调整就在工具库**另存副本**。
- **导出与导入**：工具可下载成 `.tool.json`（含嵌套的工具）并在另一站点导入；流程导出时会内嵌它用到的复合工具，流程文件单独就能导入。
- 内置的复合工具只读；在工具库用**另存副本**获得可编辑的版本。

## 5. 工具页与 ROI {#tool}

<figure class="shot"><img src="/docs/img/tool.jpg" alt="工具页"><figcaption><b>工具页</b>（编辑器 › 侧栏 › 打开工具页，路由 <code>/flows/:id/tools/:step</code>）
<ol class="callouts">
<li data-n="1">此步骤的<strong>参数</strong>，依分组排列并含说明文字；区域参数会改画在图像上。</li>
<li data-n="2"><strong>输入图像</strong>，也就是步骤收到的图像，ROI 会画在此处。</li>
<li data-n="3">带有步骤标记的<strong>输出图像</strong>。</li>
<li data-n="4"><strong>参考信息</strong>：直方图、统计与步骤输出值。</li>
<li data-n="5"><strong>执行到此步骤</strong>会试执行流程到此处。</li>
<li data-n="6"><strong>保存</strong>把参数草稿写回流程。</li>
<li data-n="7"><strong>上传暂存图像</strong>提供一张只供试执行使用的图像，不影响来源库。</li>
<li data-n="8"><strong>返回</strong>编辑器，若有未保存参数会先询问是否舍弃。</li>
</ol></figcaption></figure>

- 变更参数**默认不会**执行任何内容；按「执行到此步骤」才会看到结果。打开「自动套用」后，每次变更 500 ms 后试执行，只送出一连串变更中的最后一次。
- 参数变更会暂存在草稿中：「保存」才会写回流程，带着未保存变更离开时会询问是否舍弃。
- ROI：有区域参数的工具，在打开工具页时会立即显示 ROI。在输入图像上绘制矩形、旋转矩形、圆、椭圆、环形（可选扇区）、多边形、折线、线或点。坐标是该步骤输入图像的像素坐标；正角度为画面顺时针。
- 「用上次图像重跑」会固定同一张图像以便调整；定位或 Golden 比对使用的模板可由当前图像上的方框建立，并直接存为资产。
- 有图像列表参数的工具可直接把当前试执行图像的一个裁切加入该列表；按 Add from current image，画出矩形或旋转矩形，再确认。自由形状边缘缺陷工具也可从当前图像教导轮廓模型。
- **端口**（参数下方）：勾选哪些输入与输出端口要画在画布上、拖动行或用箭头调整顺序、替输出取一个发布名称。已接线的端口一律显示（要隐藏请先移除连线）；「按下游位置排序」会把输出排到连线不交叉。把未接线的必填输入隐藏起来不会让问题消失：步骤会挂红色徽章、检查照样不通过。默认规则见[端口](#ports)。

## 6. 参数卡、现场参数与配方 {#teach}

<figure class="shot"><img src="/docs/img/teach.jpg" alt="参数卡页"><figcaption><b>参数卡</b>（流程 › 参数卡图标，或编辑器的「未教导」徽章，路由 <code>/flows/:id/teach</code>）
<ol class="callouts">
<li data-n="1">具有现场参数的<strong>步骤</strong>；选取其中一个。</li>
<li data-n="2">该步骤的<strong>现场参数</strong>：只显示工具作者标为可教导的参数。</li>
<li data-n="3">会随值变更而重新执行的<strong>实时预览</strong>。</li>
<li data-n="4"><strong>配方</strong>行：正在编辑哪一组参数集（graph 本身或具名配方），以及配方管理器。</li>
<li data-n="5"><strong>保存</strong>把值写入 graph 或配方（Ctrl+S）。</li>
<li data-n="6"><strong>标记为已教导</strong>：工程师确认流程已调好；未教导流程仍会执行，只是执行会带警告。</li>
<li data-n="7">当前图像的步骤<strong>输出值</strong>。</li>
</ol></figcaption></figure>

- **配方**是同一流程的具名参数覆盖，例如产品 A、产品 B。「存为配方」会保存当前值；未另外指定时，流程默认配方会套用，外部触发也可指名要用的配方。
- **换线**是在此页或通过 API 切换生效配方；操作员可执行此动作，变更配方内容则需要工程师权限。
- 若角色缺少「现场参数与换线」，操作员会以只读方式看到此页，标头会说明原因。

### 6-1. 站台参数卡与自定义分组 {#station-teach}

Teaching 分组下的**站台参数卡**页，会把每条可见流程的现场参数收在同一份列表。站台有多条流程处理不同相机面或治具时，可使用 Flow、Tool 与 Search 筛选。每行都显示流程、步骤、工具与参数，因此值永远不会脱离它将更新的流程 graph。

保存时使用与单流程参数卡相同的流程更新路径：界面会为每条已变更流程建立一个 graph patch，并分别送出 `PATCH /api/vision/flows/{id}`。若某条流程保存成功、另一条被拒绝，结果面板会逐条列出成功或失败，而不是隐藏部分结果。操作员仍然只能变更标为现场教导参数的项目；变更非 teach 参数会被服务端拒绝。

自定义分组是保存在账号偏好中的个人快捷方式。分组只记录 `flow_id`、`node_id` 与参数 key；当前值永远来自流程 graph。若快捷方式指向已删除的流程、步骤或参数，界面会把它标为无效，并让您移除它，不影响其余内容。每位用户最多可保留 32 个分组。

### 新一批检测工具的位置 {#new-tools}

工具选择器会依类别整理每个工具，因此算法批量新增的工具会出现在符合用途的位置：**预处理** — Polar unwrap 与 Polar restore（环、齿轮、螺纹）、Flat-field correction（不均匀照明）、Lens undistortion、Photometric stereo（四向打光表面形状，用于浮凸与凹刻标记）；**定位** — Shape match（可承受遮挡与照明变化的边缘方向比对）、Region from shape 与 Region combine（排除区）；**测量** — 轮廓链（Contour find、filter、geometry、match）、Circular caliper 与 Profile defects（圆边缺口）、Form and position tolerance（直线度、圆度、平行度等）、Real-world coordinates；**检测** — Statistical template compare、Anomaly detection（只有良品）、OCR read 与 OCV verify、Barcode quality grade。每个工具都有可直接使用的模板，样本图会显示预期用途，[检测能力](vision-capabilities.md)页则列出每项测量内容与精度。

## 7. 试执行、执行、连续与统计 {#run}

| 动作 | 使用版本 | 执行内容 |
|---|---|---|
| 试执行 | 当前画布，包含未保存变更 | 保留所有中间图像；不写入执行历史。 |
| 执行一次 | 已保存版本 | 真正执行，与外部触发相同；写入执行历史与统计。 |
| 连续执行 | 已保存版本 | 依设置间隔反复执行；总览显示实时图像与结果。 |

<figure class="shot"><img src="/docs/img/stats.jpg" alt="统计页"><figcaption><b>统计</b>（总览卡片 › 统计图标，或编辑器顶栏，路由 <code>/flows/:id/stats</code>）
<ol class="callouts">
<li data-n="1"><strong>KPI</strong> 行：执行数、OK、NG、failed、良率与耗时，来源是可跨重启与清理保留的每小时汇总。</li>
<li data-n="2">下方执行历史的<strong>状态筛选</strong>；若图像已归档，点击行可打开该次图像。</li>
</ol></figcaption></figure>

打开归档图像后按**在编辑器重跑此图像**：它会成为编辑器的暂存图像，因此三天前的 NG 可用当前流程再次执行并调整。

**图像归档**：平台**默认不保留执行图像**（内存保留最近几张，重启会清除）。若要在客户反馈时看到相机当时拍到的内容，请在此页打开图像归档（只存 NG，或每次执行都存，OK 执行可抽样）。从那时起，每个 NG 与失败都会把来源与结果图像写到磁盘，点击执行历史行即可查看；旧文件超过保留期间或总大小限制后会自动清除（`VISION_ARCHIVE_DAYS`、`VISION_ARCHIVE_MAX_GB`；若整厂默认打开，使用 `VISION_ARCHIVE_DEFAULT`）。当有 NG 但归档关闭时，界面会提醒您。

### 7-1. 操作员看板 {#board}

<figure class="shot"><img src="/docs/img/board.jpg" alt="全屏操作员看板"><figcaption><b>操作员看板</b>（总览 ›「打开看板」，或编辑器的看板设置，路由 <code>/board/:id</code>）
<ol class="callouts">
<li data-n="1"><strong>看板标题</strong>（未设置时为流程名称）。</li>
<li data-n="2">上一个零件的<strong>判定</strong>，大到可从产线另一侧读取；若流程提供判定标签，也会一并显示。</li>
<li data-n="3">为此流程选择的<strong>数值</strong>，每个都有标签与单位；超出公差时变红。</li>
<li data-n="4"><strong>今日</strong>：总数、OK、NG 与良率，来源与统计页相同，都是每小时汇总。</li>
<li data-n="5">流程<strong>变量</strong>（批号、累计计数）。</li>
<li data-n="6"><strong>返回平台</strong>。看板不需要侧栏；可在产线旁屏幕用浏览器 kiosk 模式打开。</li>
</ol></figcaption></figure>

**选择看板显示内容。** 在流程编辑器中未选取任何项目时，「设置」分页会有**看板**卡：勾选要显示的具名输出，为每个输出指定标签、单位、小数位数与最小／最大值（超出范围会在看板与总览变红），选择要显示哪个步骤的图像（默认最后一张），列出要显示的变量，并切换判定、今日计数与标记是否显示。保存后再打开看板。总览会遵循相同设置，因此实时面板也会用相同数值与颜色。

每个零件检测完成时看板都会更新；计数每十五秒刷新一次。若要自行建立画面，一个请求 `GET /api/vision/flows/{id}/board` 就会返回此页显示的完整内容，包含公差判定（[自动化](/docs/automation.html#board)）。

### 7-2. 运行界面 {#dashboard}

**运行界面**页（`/dashboards`）列出操作员可用 kiosk 模式打开的站台看板。每行显示看板名称、是否为默认、widget 数、最后更新时间与可用动作。操作员可打开看板。工程师可从空白版面、默认版面或内置模板建立看板，将某个看板设为默认、复制、删除，并打开可视化版面设计器。

#### 设计版面 {#dashboard-design}

**看板设计器**（`/dashboards/:id/design`）是工程工作区，可先不编辑 JSON 就变更运行界面。左栏是 widget 目录，中间画布是行与列的网格，右栏显示版面、widget 与高级设置。在画布顶部变更行数与列数，点击单元格选取，拖过相邻单元格合并，使用 Split 将合并格还原为单一格，并把 widget 从目录拖入任一单元格。已在单元格中的 widget 可选取、移到另一格、重新排序、复制或删除。

属性面板会依看板 widget contract 建立可用控件。布尔选项用复选框，数字选项用有界数字字段，选项用选择器，颜色用色板，表格字段、分页、规则与图像墙项目等列表型选项则用精简行编辑器。来源设置让工程师选择 widget 要读流程输出、变量、图像、状态、计数、SPC 序列或设备值。已选流程会在信息已知时控制可用输出、变量与图像 key。

| Widget | 用途 |
|---|---|
| Child dashboard | 嵌入另一个看板，深度一层。该子看板内的嵌套 child dashboard 会在查看器中隐藏，服务端也只收集子看板的直接流程引用。 |

使用**保存**修补看板版面，**预览**会在右侧面板显示缩放后的 kiosk 查看，**模板**会以内置起始版面取代当前版面，**导出 JSON** 或 **导入 JSON** 可在站台间移动版面。高级分页仍包含完整 JSON 编辑器，可做精确变更与排查。带着未保存变更离开设计器时会询问确认。

全屏查看器（`/dashboard/:id`，或默认看板的 `/dashboard`）使用服务端保存的 layout JSON。中央区域是单元格网格。版面启用时，顶栏与底栏会显示标题、时钟与设备状态。查看器会订阅版面引用的每条流程，因此图像、判定与数值会在执行完成时更新；看板数据包每十五秒刷新一次，提供今日计数、站台变量与设备状态。

**编辑 layout JSON。** 打开**编辑版面**，变更 `rows`、`cols`、`cells`、`bars`、`default_flow_id`、`widgets` 与 `theme` 字段后保存。每个 widget 有 `id`、`type`、`cell`、选填 `props` 与选填 `source`。服务端会验证版面，JSON 无效时返回需要调整的确切 widget 与字段。使用**载入默认版面**重置文本框，**导出 JSON** 下载当前版面，**导入 JSON** 粘贴已保存的版面文件。

### 统计页上的测量与精度 {#measurements}

统计页有两种视图。**良率**就是前述 OK/NG 历史。**测量值**是一个具名输出的控制图：选择输出、图表（每次执行一个值时用 I-MR，批量来料时用带 subgroup size 的 X̄-R）与期间（24 h、7 d、30 d）。图表会画出中心线与由数据算出的控制限；若 *Tolerance judge* 步骤绑到同一个值，也会画规格限（USL/LSL，虚线），此绑定同时提供 Cp 与 Cpk。触发 Nelson 规则的点（一点超过 3σ、连续九点在同侧、连续六点上升或下降等）会画成红色，规则列在图下。数值来自测量记录，会独立于执行历史保留一年，因此即使执行明细已清除，仍看得到过去三个月的漂移。

若流程**当前**正在漂移或超出规格（最新点触发规则，或最近三十笔包含超规值），总览会显示测量警示并连到该流程统计。系统没有推送通知；警示显示在画面上。

**精度研究**卡位于良率视图底部，会用验证器方式执行流程：同一张图执行 N 次（重复性），或同一零件采集 N 次（再现性），并报告每个数值输出的 σ 与 range，附可复制报告。多个零件的 Gauge R&R 由命令行执行（`manage.py precision`，见 Performance）。

## 8. 批量测试 {#batch}

<figure class="shot"><img src="/docs/img/batch.jpg" alt="批量测试页"><figcaption><b>批量测试</b>（侧栏 › 批量测试，路由 <code>/batch</code>）
<ol class="callouts">
<li data-n="1"><strong>测试流程</strong>：图像要跑过的流程；任何图像集都可测任何流程。</li>
<li data-n="2"><strong>新建图像集</strong>：上传图像或从图像来源采集 N 张，最多每组 200 张。</li>
<li data-n="3">以测试流程<strong>执行</strong>所选图像集；它在后台执行，有进度条且可中断。</li>
<li data-n="4"><strong>结果</strong>分页：逐张状态、期望标记、命中与输出。</li>
<li data-n="5"><strong>洞察</strong>分页：漏检图像、失败步骤、阈值建议、输出分布与跨执行趋势。</li>
<li data-n="6"><strong>调整</strong>分页：变更现场参数并重新执行，再写回流程、存为配方或送到编辑器；「图像」分页可标记期望，「比较」分页可并排两次执行。</li>
<li data-n="7"><strong>助手</strong>：选取已完成执行后，可依数据咨询或调整。</li>
</ol></figcaption></figure>

1. 选取图像集会填入建立该图像集时的流程；若要比较不同流程，改变下拉菜单后再次执行。编辑器有未保存变更时，可勾选「使用编辑器未保存草稿」。
2. 每次执行的逐张结果都会保留，并可从执行列表回看；若使用不同流程执行，该流程名称会显示在该笔执行上。
3. 在「图像」分页，为每张图像标记期望 OK 或 NG；「结果」分页接着会显示命中率与哪些图像命中，「洞察」可提出阈值建议。「套用并重新执行」会产生新执行。
4. 向助手询问「为什么第 3 张 NG？」或给调参指令；「调整」分页也有「自动调参」。所有操作都会落成新执行，因此不会遗失数据。
5. 勾选图像并「保存到 Golden Set」可建立回归基准。详见[批量测试](batch.md)。

## 9. Golden Set {#golden}

<figure class="shot"><img src="/docs/img/golden.jpg" alt="Golden Set 页"><figcaption><b>Golden Set</b>（流程 › Golden Set 图标，路由 <code>/flows/:id/golden</code>）
<ol class="callouts">
<li data-n="1"><strong>上传图像</strong>为案例，每张都带有期望 OK 或 NG，也可从批量执行送入。</li>
<li data-n="2"><strong>执行回归</strong>：每个案例都会执行，并与期望与基准比对；退步案例排在最前。</li>
<li data-n="3"><strong>自动调参</strong>会搜索现场参数，找出更好的命中率，并让您套用结果。</li>
<li data-n="4"><strong>基准</strong>：把当前结果冻结为下一次回归的参考。</li>
</ol></figcaption></figure>

Golden Set 是调参后的安全网：它会精确告诉您哪些图像在 OK 与 NG 之间翻转。它也可由命令行执行（`manage.py regress`），因此可挡住 CI pipeline。详见 [Golden Set 与导出](golden.md)。

## 10. 图像来源 {#sources}

<figure class="shot"><img src="/docs/img/sources.jpg" alt="图像来源库"><figcaption><b>图像来源库</b>（侧栏 › 图像来源库，路由 <code>/sources</code>）
<ol class="callouts">
<li data-n="1"><strong>新增来源</strong>会打开表单（下一张图）。</li>
<li data-n="2"><strong>下载采集端</strong>：供另一台 PC 上的相机或需要厂商 SDK 的相机使用的桌面程序。</li>
<li data-n="3"><strong>管理分组</strong>：改名或删除列表上方显示为筛选标签的分组。</li>
<li data-n="4">列表有两种形状，可从右上选择：<strong>树状视图（默认）</strong>依来源种类再依分组整理；<strong>卡片</strong>显示每个来源的预览图。两者都提供名称、设置摘要与实时状态（已连接、fps、最后帧）、启用／停用切换，以及预览用眼睛图标。</li>
</ol></figcaption></figure>

示例样本图不再出现在此处：它们会以固定图像随模板移动（见前述 Fixed image 步骤），所以来源库只存您的相机、文件夹与推送来源。

<figure class="shot"><img src="/docs/img/source-form.jpg" alt="新增来源表单"><figcaption><b>新增来源</b>
<ol class="callouts">
<li data-n="1"><strong>种类</strong>：采集端相机、文件夹（循环读取）、单一文件、推送上传、合成生成器或插件种类。</li>
<li data-n="2"><strong>浏览</strong>会打开服务端文件浏览器，供文件夹与文件种类使用。</li>
<li data-n="3"><strong>测试取像</strong>会在保存前用当前设置采集一张图像。</li>
<li data-n="4">结果：尺寸、耗时与缩略图，或失败原因。</li>
</ol></figcaption></figure>

### 相机在另一台 PC，或需要 Basler / IDS SDK 时 {#sources-capture}

您不需要把相机搬到服务器。使用「下载采集端」，在相机所在 PC 解压缩并执行 `VisionSequenceCapture.exe`，于 Connection 填入服务器地址（port 9100）与采集端名称，接着把相机新增为通道、打开并开始取像（可在预览上画 ROI，只传该区域，也可调整并保存相机参数）。回到网页界面后，新增 kind 为「采集端相机」的来源，选取采集端与通道，选「依需求取像」（每次执行取新帧）或「连续流」，并在保存前按测试取像。状态栏会显示采集端是否在线、fps 与最后帧的年龄；外部集成 › 采集端会列出所有已连接采集端，并提供流开关与预览。同一台机器上会自动使用共享内存；跨机器则通过 TCP 无失真传输。列表中的「采集端离线」代表程序尚未连接。详见[采集端](/docs/capture-client.html)。

**采集端相机在执行中超时**：请先在采集端确认通道状态为正在取像且预览仍实时。trigger 模式的相机需要触发信号。曝光较长或跨网络时，请增加来源 timeout 毫秒数。关闭「要求新鲜帧」可让它使用采集端已持有的任何帧。

### 10-2. 标定：毫米、镜头畸变与机械手臂坐标 {#calibration}

<figure class="shot"><img src="/docs/img/calibration.jpg" alt="标定页"><figcaption><b>标定</b>（侧栏 › 标定，路由 <code>/calibration</code>）
<ol class="callouts">
<li data-n="1">三种教导方式与各自提供的结果。<strong>标定板</strong>：几张打印板图像同时提供镜头校正与比例。<strong>机械手臂点位</strong>：在图像上标记位置并输入机械手臂报告的坐标，让位置可直接交给机械手臂。<strong>已知距离</strong>：标记两点、输入真实距离即可。</li>
<li data-n="2">取像用的<strong>图像来源</strong>；也可上传既有照片。</li>
<li data-n="3"><strong>采集</strong>会拍一张图。在标定板模式下，每张图都会立即搜索标定板，并列出找到的点数，因此能立刻知道该角度是否有效。</li>
<li data-n="4"><strong>标定板</strong>：图案，以及以<em>内角点</em>表示的尺寸（10 x 7 格的板是 9 x 6）与相邻两点间距。填错时找不到标定板；界面会明确说明，而不是静默失败。</li>
<li data-n="5">图面与机械手臂使用的<strong>单位</strong>。</li>
<li data-n="6"><strong>计算</strong>会算出结果，但<em>不会</em>保存：您会先看到吻合度。</li>
<li data-n="7"><strong>保存标定</strong>会把它存成资产。之后可在 Lens correction、Real-world coordinates 或 Pixel calibration 步骤中选用。</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/calibration-stereo.jpg" alt="标定 › 立体高度"><figcaption><b>立体高度</b>（左右相机对测量物件高度，用于机械手臂取料）
<ol class="callouts">
<li data-n="1"><strong>立体高度</strong>模式：两台相机从略有差异的位置看同一条皮带；两个视角间差异会给出各物件距离。</li>
<li data-n="2">若相机对已在其他地方完成标定，可<strong>导入 stereo_config.json</strong>；只读取两台相机模型与相对位姿，其余在此重新计算。</li>
<li data-n="3"><strong>采集成对图像</strong>会同时拍两张图，并列出每一对的时间差与拟合误差；至少五对同一块标定板图像后，依序计算与保存。</li>
</ol></figcaption></figure>

**皮带高度参考。** 在图像对列表下方，量一次空皮带并输入该皮带表面对应的机械手臂 Z；之后 Stereo depth 步骤会把每个物件顶面报告为绝对机械手臂 Z，而不只是距相机的距离。没有该参考时，步骤仍会报告距离并让 Z 保持空值。

**选择方式。** 若只需要毫米测量，*已知距离*一分钟即可完成：在已测量物件上标两点并输入距离。若镜头让角落附近直线明显弯曲，或同一零件在视野中央与边缘测量不同，请使用*标定板*：以不同倾角与距离拍三张以上，尽量填满画面。若机械手臂需要前往取件，请用*机械手臂点位*：将机械手臂 jog 到三个以上可见位置，并输入每一点报告的坐标。

**保存前先读误差。** 每种方法都会报告吻合度。标定板标定会显示每张图的重投影误差，因此可删除模糊图像后重算。机械手臂点位会显示*每个*点的误差，最差的一点会在图像上标红，通常代表机械手臂 jog 到错误位置，或坐标输入错误。结果会给出清楚判定：good、fair 或 do it again。

**点位标记容错。** 点击孔、打印点或角落附近，标记会吸附到中心，因此不必精准点到单一像素。若确实要使用点击的位置，可关闭吸附。

**在流程中使用。** 一份已保存标定可供三个步骤共用：*Lens correction* 会拉直图像（放在图像来源后、任何测量前），*Pixel calibration* 的 "from a calibration" 模式会把长度转成毫米，*Real-world coordinates* 会把位置转成机台使用坐标，并同时转换长度与角度。因为它们都读同一资产，重新标定站台会一次更新每条流程，不需要逐步寻找手输数值。

如果相机之后移动、重新对焦或更换，请重新标定。全分辨率建立的标定在流程以半分辨率执行时仍有效：镜头校正会自动缩放，若宽高比不同，步骤会明确说明，而不是悄悄套用错误校正量。

## 11. 资产 {#assets}

<figure class="shot"><img src="/docs/img/assets.jpg" alt="资产库"><figcaption><b>资产库</b>（侧栏 › 资产库，路由 <code>/assets</code>）
<ol class="callouts">
<li data-n="1"><strong>上传资产</strong>：模板图像、模型文件（ONNX 或已训练权重）或数据集归档。</li>
<li data-n="0"><strong>树状或卡片</strong>：右上角的切换。<strong>树状视图是默认</strong>，依种类、分组，再到资产及其大小与日期排列；资产库存放没有缩略图的模型与文件时，此视图最适合。卡片则显示缩略图。您的选择会记在此浏览器。</li>
<li data-n="2"><strong>管理分组</strong>，方式与来源相同。</li>
<li data-n="3">资产卡；工具页也可从当前图像上画的方框建立模板，并直接存到此处。</li>
</ol></figcaption></figure>

模板供定位与 Golden 比对工具使用，模型供深度学习工具使用，数据集归档供教导页使用。参考图也可不通过资产交给工具：把 Fixed image 步骤（role "reference"）连到工具的图像输入端口即可，内置模板就是用这种方式携带 Golden 打印图与定位模板。示例统计模板、形状模型与教导模型都在「Examples」分组。

## 12. 深度学习教导 {#dl}

<figure class="shot"><img src="/docs/img/dl.jpg" alt="DL 教导页"><figcaption><b>DL 教导</b>（侧栏 › DL 教导，路由 <code>/dl</code>）
<ol class="callouts">
<li data-n="1"><strong>新增教导项目</strong>：选择模型种类（分类、语义分割、实例分割、检测、位姿、旋转框）。</li>
<li data-n="2"><strong>自动标记</strong>：让当前模型或智能选取模型提出标记，再由您确认。</li>
<li data-n="3"><strong>训练</strong>：切分 train、val 与 test，冻结数据集版本并在服务端开始训练；完成模型会落到资产库。</li>
<li data-n="4"><strong>从视频建立样本</strong>（打开前为折叠）：选择采集端录下的视频、用来分割的模型、每个追踪物件保留几张图，以及帧间隔；每个保留帧都会成为样本，物件已先画好外框，可直接修正。</li>
</ol></figcaption></figure>

1. 样本：上传图片或 zip、从来源 burst 取像、导入数据集文件夹，或从视频抽取；重复项会自动跳过。点击缩略图即可标记。
2. 标记：分类时，点击缩略图并选择类别；分割与检测时，绘制多边形或方框，也可用「智能选取」点击物件并自动描出外形。
3. 训练后的「用此模型建立流程」会建立 acquire → inference 流程并在编辑器打开。

训练器、GPU 设置与导出格式请见[深度学习教导](dl.md)。

## 13. AI 助手页：从图像产生流程 {#agent}

<figure class="shot"><img src="/docs/img/agent.jpg" alt="AI 助手页"><figcaption><b>AI 助手</b>（侧栏 › AI 助手，路由 <code>/agent</code>）
<ol class="callouts">
<li data-n="1"><strong>上传图像</strong>：一张或多张图像；在其上画出要检测的区域。每个 ROI 都有编号（ROI01、ROI02…），也可带 "good"、"bad" 或 "locator" 等提示。</li>
<li data-n="2"><strong>需求</strong>：一句话，例如 "there should be 5 holes"、"measure the diameter, 17.5 ± 0.4 mm"、"ROI01 is good and ROI02 is bad, find the difference"。</li>
<li data-n="3"><strong>生成</strong>：助手会询问仍缺少的信息，产生流程并在每张图像上执行，为每张缩略图标记 OK 或 NG。</li>
<li data-n="4"><strong>AI 供应商</strong>：离线规则引擎，或 Claude、GPT、Gemini 搭配您自己的密钥（保存在服务端并绑定账号）；保存时会测试连接，「列出模型」显示该密钥可用模型，工作模式可选单次或代理模式。</li>
<li data-n="5"><strong>技能</strong>：助手遵循的内容，并在每个技能下加入您自己的或站台的备注。</li>
</ol></figcaption></figure>

1. 可选择为每张缩略图标记它应得到的判定；ROI 提示为 "good" 或 "bad" 的图像会自动标记。提示为 "locator" 的 ROI 代表固定特征，当零件可能移动时，流程会在前方加入定位补正。
2. 规则引擎会产生多个候选方案，依您的标记挑选最佳者，结果卡也让您切换方案；有两张以上已标记图像时会自动调参。
3. 用文字微调，例如 "too many false rejects"、"expect 4 instead"、"tolerance ±0.2"，然后「存成流程」以在编辑器打开。结果卡上的赞或踩会影响之后是否在类似图像重用这些参数。
4. 历史会显示过去工作阶段，「还原」会带回图像、ROI、需求与标记并重新执行。代理模式下，助手会逐步草拟、尝试、编辑与验证，显示可中断或回复问题的时间轴。

请参考 [AI 助手](agent.md)。

## 14. 全局助手（每页皆可用） {#assistant}

<figure class="shot"><img src="/docs/img/assistant.jpg" alt="在图像来源库打开的助手面板"><figcaption><b>AI 助手面板</b>（每页右下角按钮）
<ol class="callouts">
<li data-n="1"><strong>按钮</strong>会打开与关闭面板；徽章会计算未读提示。</li>
<li data-n="2"><strong>模式</strong>标签：Auto 自行依内容路由；Help、Edit flow、Consult data 与 Tune from data 会强制指定模式。</li>
<li data-n="3"><strong>记忆</strong>：您要求它记住的事实与您评分过的答案。</li>
<li data-n="0"><strong>新对话</strong>（＋）与<strong>过去对话</strong>（时钟，位于旁边）：对话会随账号保留；面板会在您对话时保存当前对话，列表可重开或删除旧对话。每人 50 个对话、每个 60 条消息，保留最新者。</li>
<li data-n="4"><strong>截图</strong>：把此页图片附到下一个问题（需要能读图像的 LLM provider）。</li>
<li data-n="5"><strong>画面文字</strong>：把画面内容文字摘要附到后续问题。</li>
<li data-n="6"><strong>分享</strong>：页内快照与近期操作是否随每个问题送出；关闭时它只知道您位于哪一页。</li>
<li data-n="7">当前页的<strong>快速提示</strong>。</li>
<li data-n="8"><strong>输入框</strong>：问题、指令，或用 "remember: …" 保存事实。</li>
</ol></figcaption></figure>

- 输入问题，例如 "how do I create an image source from a folder?"，它会依平台文档、用界面语言回答，说明所在页、分页与按钮，附上使用章节链接；若答案是位置，会提供「前往」标签。
- 在流程编辑器中输入指令，例如 "set the blob minimum area to 40"、"disable the noise removal"，它会编辑当前画布；「套用到画布」会写回，可再撤销。在批量页选取完成执行后，可询问数据或给出调参指令，结果会成为新执行。
- 它会理解您的情境：所在页、选取项目、最后执行、近期错误、您的角色与引擎锁定。当可识别问题发生时，例如引擎锁定、角色不允许、接收端未监听、步骤缺少来源，会出现提示卡，附一句说明与「询问助手」。
- 有 LLM provider 时，它也可在回答前读取实时状态（流程、来源、连接、执行报告、锁定、插件），且永远受您的权限限制；回复会列出已检查内容。
- **选择硬件**：询问某工作需要哪种相机、镜头或照明（视野、工作距离、最小特征、皮带速度、帧率），它会算出焦距与最接近的现货镜头、特征所需像素、景深、停止运动模糊的曝光、带宽与适用接口，再说明哪种照明能让缺陷可见。
- 用赞或踩评分答案：好的答案会在相似问题中重用。对话与记忆只属于您；另一位用户登录时会看到自己的内容。

## 15. 外部集成 {#integration}

<figure class="shot"><img src="/docs/img/integration-http.jpg" alt="外部集成 › HTTP API"><figcaption><b>外部集成 › HTTP API</b>（侧栏 › 外部集成 › HTTP API，路由 <code>/integration/http</code>）
<ol class="callouts">
<li data-n="1"><strong>子页</strong>：HTTP API、TCP commands、Event monitor、Modbus server、Modbus client、Capture client、Plugins。</li>
<li data-n="2"><strong>信息栏</strong>：HTTP base、TCP port、capture port、是否需要 API key、workers 与 timeout。</li>
<li data-n="3">此页的<strong>分页</strong>：Try it、Response format、Commands and results。</li>
<li data-n="4"><strong>搜索</strong> API。</li>
<li data-n="5"><strong>端点</strong>，重要项目排在前面并带白话描述；打开后可填参数、执行，并复制 curl、Python 或 C# 片段。</li>
</ol></figcaption></figure>

- HTTP：`POST /api/vision/flows/{id}/run`（可选附图像与配方）返回判定、具名输出与 run id。TCP：一行 `RUN <id>`；TCP 页列出每个指令与失败码，并提供可试用的控制台。Events：Event monitor 页会实时显示 SSE 流。
- 每页的 **Commands and results** 分页显示最近几分钟该通道收到与送出的内容，是设备「没有动作」时第一个检查点。

<figure class="shot"><img src="/docs/img/integration-modbus.jpg" alt="外部集成 › Modbus server"><figcaption><b>外部集成 › Modbus server</b>（路由 <code>/integration/modbus-server</code>；Modbus client 与 TCP commands 也用同样方式管理连接）
<ol class="callouts">
<li data-n="1"><strong>连接</strong>：此种类的连接；平台在此监听，任何 Modbus TCP 主站可读结果与写入触发。</li>
<li data-n="2"><strong>地址格式与映射</strong>：寄存器与线圈如何对应到流程输出与触发。</li>
<li data-n="3"><strong>Commands and results</strong>：主站送来的每个请求。</li>
<li data-n="4"><strong>新增连接</strong>（不需选种类；此页会决定）。</li>
<li data-n="5">连接列表含实时状态；图标可测试连接、手动写入值、编辑与删除。</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/integration-capture.jpg" alt="外部集成 › 采集端"><figcaption><b>外部集成 › 采集端</b>
<ol class="callouts">
<li data-n="1"><strong>下载采集端</strong>（版本、大小、SHA-256）与设置步骤，并显示采集端口是否正在监听。</li>
<li data-n="2">每个已连接采集端与通道（尺寸、模式、fps、最后帧、哪个来源使用它），附流与预览控件。</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/integration-plugins.jpg" alt="外部集成 › 插件"><figcaption><b>外部集成 › 插件</b>
<ol class="callouts">
<li data-n="1"><strong>重新扫描</strong>会挂载新放入 <code>plugins/</code> 的文件，并重试失败文件；已载入文件若有变更，需要重新启动。</li>
<li data-n="2">每个插件文件挂载了哪些项目（工具、来源、writer、trainer）、停用项目，以及含 pip 提示的载入错误。</li>
<li data-n="3">kind 来自插件的连接。</li>
</ol></figcaption></figure>

<figure class="shot"><img src="/docs/img/integration-devices.jpg" alt="外部集成 › 设备连接"><figcaption><b>外部集成 › 设备连接</b>
<ol class="callouts">
<li data-n="1"><strong>新增连接</strong>：串口、UDP、本地 TCP 文本服务器或光源控制器；光源控制器预设会填入命令模板，已保存设置仍是正本。</li>
<li data-n="2">每条连接显示种类、设置与实时状态；光源控制器状态会显示每个通道最后亮度与最后送出的命令。</li>
<li data-n="3"><strong>导出</strong>与<strong>导入</strong>可在站台间移动每条连接与规则表，secret 会遮蔽。</li>
</ol></figcaption></figure>

条码读取器、旧主机、光源控制器等以文字行为单位的设备位于此处；每一行收到的文字都会走与 TCP command port 相同的站台规则，流程则以 `set_light`、`io_output` 与 `multi_light_grab` 驱动光源。

请参考[自动化](/docs/automation.html)、[Modbus](/docs/modbus.html)、[采集端](/docs/capture-client.html)与[插件](/docs/plugins.html)。

## 16. 引擎锁定 {#lock}

<figure class="shot"><img src="/docs/img/lock-banner.jpg" alt="总览上的锁定横幅"><figcaption><b>已锁定引擎</b>
<ol class="callouts">
<li data-n="1">顶栏下方的<strong>横幅</strong>：谁持有锁定与原因；管理员或持有者可从此处解除。</li>
<li data-n="2">所有会执行引擎的动作，包括执行一次、试执行、连续执行，在锁定期间都会以错误 423 拒绝；编辑与保存仍可使用。</li>
</ol></figcaption></figure>

集成方或管理员可从外部锁定引擎，也就是 HTTP `POST /api/vision/lock` 或 TCP 指令 `LOCK`，以便在机台循环或维护时段保留硬件；`UNLOCK` 或 `DELETE` 会释放锁定，锁定也可带 time-to-live，避免忘记释放。取得锁定时，每个连续执行都会停止。集成方自己的触发不受影响。

## 17. 操作记录、设置与说明 {#admin}

<figure class="shot"><img src="/docs/img/audit.jpg" alt="操作记录"><figcaption><b>操作记录</b>（侧栏 › 操作记录；管理员，或被授予操作记录功能的角色）
<ol class="callouts">
<li data-n="1">依<strong>动作</strong>筛选（flow.update、recipe.activate、user.create、lock.acquire…）或依操作者筛选。</li>
<li data-n="2"><strong>搜索</strong>摘要与目标名称。</li>
<li data-n="3"><strong>导出 CSV</strong>。</li>
</ol></figcaption></figure>

搜索框旁的 **From** 与 **To** 会限制列表日期范围（包含 To 当天），**Rows per page** 可选 25 到 500 行；API 与 CSV 导出也使用相同的 `since`/`until`/`limit` 参数。

操作记录记录变更，不记录执行：谁在何时、从哪里变更哪条流程、参数、配方、来源、连接、账号或锁定，流程会带参数层级 diff。点选一行可展开：每个变更的字段都列出变更前与变更后的值（流程修改则列出步骤与参数）。执行则位于统计与图像归档。

<figure class="shot"><img src="/docs/img/settings.jpg" alt="设置页"><figcaption><b>设置</b>（侧栏 › 设置）
<ol class="callouts">
<li data-n="1">您自己的<strong>显示名称</strong>（管理员仍在用户页管理用户名、角色与他人密码）。</li>
<li data-n="2"><strong>修改密码</strong>。</li>
<li data-n="3">界面<strong>语言</strong>（English、繁體中文、简体中文）。</li>
<li data-n="4"><strong>主题</strong>（浅色、深色、Cyberpunk 或跟随系统）。语言与主题会保存在账号上，并在不同设备间跟随您。</li>
</ol></figcaption></figure>

设置页按作用范围分成三个标签页：**这台浏览器**（API 密钥、显示）、**我的账号**（语言、主题、显示名称、密码）与**整站**（执行策略、数据保留）。每张卡片都标明变更是立即生效，还是按“保存”后生效。

**数据保留**（仅管理员，在“整站”标签页）：设置执行明细、操作记录、测量与归档图像保留多久，默认一年，零代表永久；也可设置保留多少备份，以及维护时段在哪一小时执行。卡片也显示数据库大小、各数据存储的行数与上次清理时间，并提供「立即清理」按钮。清理只会在引擎空闲时分小批进行，因此永远不会延误检测；每小时汇总（良率曲线）永远不会删除。详见[部署 §9a](/docs/deployment.html#retention)。

**显示**设置保存在每个浏览器。标记显示上限控制图像窗口会从密集结果画出多少标记；当一次执行产生的标记超过上限，窗口只画第一批并显示数量徽章，让浏览器保持流畅。同一卡片可关闭编辑器草稿版本自动保存；打开时，只有草稿 graph 自上次保存后发生变更，编辑器才会每 5 分钟保存一个版本。

<figure class="shot"><img src="/docs/img/help.jpg" alt="说明页"><figcaption><b>说明</b>（侧栏 › 说明）
<ol class="callouts">
<li data-n="1"><strong>快速上手</strong>：浓缩导览。</li>
<li data-n="2"><strong>词汇表</strong>：各页、编辑器区域、核心术语与状态用语。</li>
<li data-n="3"><strong>工具目录</strong>：每个工具及其参数与端口，依界面语言显示；其他分页涵盖端口颜色、快捷键、自动化 API 与账号。</li>
<li data-n="4">所选分页内容。</li>
</ol></figcaption></figure>

## 18. 常见问题 {#faq}

| 情境 | 处理方式 |
|---|---|
| 试执行提示图像已不在缓存中 | 重新上传暂存图像，或执行一次流程取得新图像。 |
| find_circle 或 find_line 报告找不到 | 检查 ROI 是否覆盖边缘（圆用环形 ROI，卡尺 ROI 要跨过两侧边缘）、降低边缘阈值，或变更极性。 |
| 测试 AI provider 失败 | 依显示原因处理：无效密钥、模型已退役（依建议重新命名）、provider 过载（稍后重试或切换模型），或超时（检查网络）。 |
| 执行报告引擎已锁定 | 集成方持有锁定；等待释放，或请管理员从横幅清除（[16](#lock)）。 |
| 连续模式持续报告队列已满 | 增加间隔，或检查流程耗时；性能报告会列出每个工具成本。 |
| 连接测试表示没有程序在监听 | 平台会主动连到主机程序：请先启动接收端，再重新测试。接收端示例位于 [Modbus](/docs/modbus.html)。 |
| 相机在另一台 PC，或需要 Basler / IDS SDK | 使用采集端（[10](#sources-capture)）。 |
| 操作员无法变更参数 | 只有现场参数可由操作员编辑，且角色必须有「现场参数与换线」；管理员可在用户页授权（[2](#login)）。 |
| … 在哪里？ | 询问右下角助手：它会指出所在页与分页，并提供「前往」标签。 |

## 快速参考 {#quick-reference}

### 快速上手 {#quick-start}

1. **建流程** 到「流程」页按「建立检测任务」（任务页）或「建立进阶流程」（画布），或复制示范流程。流程属于产线而不是个人：每位工程师都能看到并修改，「拥有者」栏只记录是谁建立的。
2. **取像** 从工具箱插入「图像来源」步骤，选图像来源库里的文件夹、合成或采集端相机来源；或用顶栏「上传暂存图像」只为试执行放一张图（不进来源库）。相机由相机所在电脑上的采集端程序驱动（图像来源库「下载采集端」）：连到服务端后新增「采集端相机」来源，选采集端与通道即可。
3. **加工具** 把工具箱的工具拖到画布（或点选插到最右边），把上一步的输出端口拉线接到下一步的输入端口；同色的端口才能相接。
4. **ROI** 有「区域」参数的工具：在工具页或侧栏按「在图像上编辑」，直接在图像窗口拖拽画出矩形／圆／多边形等；坐标是该步骤输入图像的像素坐标。
5. **试执行** 顶栏「试执行」用当前画布（未存档）的图执行一次，保留所有中间图像；「用上次图像重跑」可固定同一张图像调参。点选步骤名称旁的图标开「工具页」，改参数会自动重跑到该步骤并显示前／后图像与直方图。
6. **判定** 用「判定」工具给出 OK／NG；用「具名输出」把要返回给自动化系统的值命名。
7. **保存** Ctrl+S 或顶栏「保存」。「执行一次」与「连续执行」用的是已保存的版本。
8. **自动化触发** 外部系统以 HTTP POST /api/vision/flows/{id}/run（可附图像）或 TCP 指令触发；结果经响应或 SSE 取得。细节见「自动化接口」分页。
9. **模板画廊** 「流程」页「从模板建立」或编辑器顶栏「载入模板」：六十多个内置模板涵盖计数、测量、缺陷、颜色、读码与深度学习（官方底模、教导模型）；选对应的「Example: …」图像来源即可直接执行。自己的流程也可「存为模板」。
10. **AI 助手** 「AI 助手」页：上传图像、在图像上圈选检测位置（ROI01、ROI02…可各配提示）、以一句话描述需求；助手先确认信息足够再生成流程并在该图像实跑。为缩略图标记应判的结果，助手会依标记排名候选方案并自动调参；以文字微调后「存成流程」。「历史」可还原过去的工作阶段，「AI 技能」可写自己的要领；工作模式选「代理模式」时助手逐步试执行、修改与验证并显示时间轴。右下角的全局 AI 助手在任何页都可开启：依文档回答问题并附链接、在编辑器修改当前流程、在批量测试页依数据咨询或调整。
11. **批量测试与 Golden Set** 侧栏「批量测试」：选流程、上传或从来源采集图像建立图像集，每次执行都保留逐张结果。为图像标记期望 OK／NG 即可看命中率、洞察与建议阈值；改参数重跑同一图像集并比较，再写回流程或存为配方。也可请 AI 助手依数据咨询或调整。勾选案例可存入 Golden Set 作为回归基准。
12. **深度学习教导** 侧栏「深度学习」：建立教导项目、收集样本（上传或从来源取像）、标记类别或形状（含智能选取）、训练并导出模型到资产库，再于流程中以 DL 工具使用。
13. **来源与资产分组** 图像来源库与资产库皆支持分组：用列表上方的标签筛选，「管理分组」可改名、删除。范例来源与资产都在「Examples」分组。

### 端口类型 {#ports}

| 类型 | 颜色 | 用途 |
|---|---|---|
| `image` | 蓝 `#3b82f6` | 图像 |
| `region` | 紫 `#a855f7` | ROI |
| `number` | 绿 `#22c55e` | 数值 |
| `bool` | 橙 `#f97316` | 布尔 |
| `string` | 黄 `#eab308` | 字符串 |
| `points` | 青 `#06b6d4` | 点集合 |
| `contours` | 靛 `#6366f1` | 轮廓 |
| `matches` | 粉 `#ec4899` | 比对与检测结果 |
| `list` | 蓝绿 `#14b8a6` | 一般列表（含标记） |
| `any` | 灰白 `#cbd5e1` | 任意 |
| `flow` | 灰（菱形） `#94a3b8` | 分支 |

并非每个端口都会画出来。步骤只画已接线的端口、工具的默认端口（第一个图像端口与分支输出）、有发布名称的输出，以及未接线的必填输入；其余收起在卡片上的「+N」徽章后面——点击就展开，只影响这次查看。哪些端口要显示、顺序与发布名称在工具页的「端口」区编辑（侧栏的「编辑端口…」也能到），并随流程一起保存。

### 键盘快捷键 {#shortcuts}

| 按键 | 动作 |
|---|---|
| `Ctrl+S` | 保存流程 |
| `右键点选步骤` | 步骤菜单：打开工具页、复制、停用、删除、复制／粘贴参数 |
| `Ctrl+Z` | 撤销 |
| `Ctrl+C / Ctrl+V` | 复制／粘贴选取的步骤（含内部连线） |
| `Delete / Backspace` | 删除选取的步骤或连线 |
| `Esc` | 取消选取，或结束 ROI 编辑 |
| `左键拖拽（选取模式）` | 框选多个步骤；中键或右键拖拽平移画布 |
| `Shift+拖拽（平移模式）` | 框选 |
| `滚轮` | 缩放图像窗口与画布 |
| `F / 1 / + / −（图像窗口）` | 适合窗口、1:1、放大、缩小 |
| `双击图像` | 适合窗口 |

### 自动化接口 {#automation-entry}

**HTTP 触发**

```
POST /api/vision/flows/{id}/run?wait=1
Headers: X-API-Key: <密钥>（或 Authorization: Bearer <token>）
multipart: image=<文件>   或   JSON: {"context": {...}}
→ 200 RunReport（wait=1）／202 {"queued": true}（wait=0）
```

**试执行（工具页同款）**

```
POST /api/vision/flows/{id}/preview
{"graph": {...}, "reuse_image_ref": "...", "until_node": "blob", "analysis": true}
```

**暂存图像 / 重置**

```
POST /api/vision/flows/{id}/scratch-image（multipart image）→ {ref,width,height,name}
DELETE /api/vision/flows/{id}/recent → 清除内存内的执行记录与统计（SSE 送出 cleared）
```

**事件流（SSE）**

```
GET /api/vision/flows/{id}/stream?since=<seq>
事件：run_started / run_finished（带 run）/ stats / continuous / lock / cleared / ping（15 秒心跳）
```

**采集端（相机在别台电脑）**

```
图像来源库 →「下载采集端」→ 在相机电脑解压执行 VisionSequenceCapture.exe
连接：服务端地址与端口 9100（VISION_CAPTURE_PORT）、采集端名称、密钥（服务端有设 VISION_CAPTURE_AUTH 或 API_KEY 时）
通道：选相机、打开、开始取像；圈 ROI 就只传该区域
网页：新增图像来源 kind=capture {client, channel, mode: on_demand|stream, timeout_ms, fresh, encoding}
无界面：VisionSequenceCapture-console.exe --headless --connect（任务计划或服务包装用）
```

**TCP**

```
一行一个指令（\n 结尾、大小写不拘），一行 JSON 响应：
RUN <flow id 或名称> [key=value ...] → {"ok": true, "status": "ok|ng|failed", "judge": "OK|NG|FAILED|NONE", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}
TRIGGER <flow>   → 只触发不等结果 {"ok": true, "queued": true}
STATUS [flow]    → 统计；不带流程返回容量与引擎锁定
START <flow> / STOP <flow> → 连续模式
LOCK [reason="..." ttl=600] / UNLOCK → 占住硬件：网页只能编辑无法执行
LIST / PING
图像用 POST /api/vision/sources/{id}/push 推进 kind=upload 的图像来源。
```

### 账号与引擎锁定 {#accounts-quick}

- 第一次使用时系统没有任何账号，登录页会直接让您建立第一个管理员。
- 管理员：管理账号、角色权限与系统设置。工程师（默认）：建立与修改流程、来源、资产、深度学习教导、批量测试与 Golden Set。操作员：执行检测、启停连续模式、换线，以及在参数卡页调整现场参数。
- 角色权限：上述分工是出厂设置，不是固定规则。管理员在「用户」页逐项勾选工程师与操作员能用哪些功能——深度学习、批量测试、操作记录、主动输出的连接。管理员永远全开，且服务器每个请求都会检查，所以没勾的功能直接输入网址也无法进入。
- 流程属于产线而不是个人：每位工程师都能看到并修改每一条流程，「拥有者」栏只记录是谁建立的。
- 集成方（自动化系统）以 API 密钥（X-API-Key）调用，永远可以执行流程。
- 引擎锁定：集成方经 HTTP（POST /api/vision/lock）或 TCP（LOCK）取得，所有连续执行停止，其他人只能编辑、无法试执行或执行。画面上方的横幅显示是谁持有与原因；管理员或持有者可从横幅解锁，锁定也可设置到期自动解除。
- 显示名称与密码在「设置」页自行修改；管理员可在「用户」页重设他人密码、改角色、停用账号。
