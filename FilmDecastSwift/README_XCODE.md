# NegativeMaster · SwiftUI 工作台

当前构建版本为 **2.1（build 5）**。这是原生 SwiftUI 前端：NavigationSplitView 缩略图侧栏、独立检查器、系统工具栏、菜单、文件面板与浅深色外观。照片和排版位于内容层，操作位于系统导航层；「调片」「整卷排版」「胶卷库」共用原生工作台。

前端不嵌入网页。图像处理复用仓库中已验证的 Python 算法，Swift 与独立本地进程通过 JSON 管道通信，不监听网络端口。打包脚本包含 Python、图像库、胶卷资料、字体与全部渲染资源。

## 使用

双击构建生成的 `NegativeMaster.app`，也可以拖到「应用程序」。构建时按本机处理器架构打包；本轮 Apple Silicon 构建已在 macOS 27.0.1 验证启动。包声明最低 macOS 14，其他系统版本尚未做本轮验收。

- **调片**：打开文件夹或导入照片，左侧选择，右侧切换光线、色彩、曲线、细节、裁剪、导出。
- **整卷排版**：导入成片或打开胶卷文件夹。文件夹优先使用已导出成片，其次读取各照片保存的参数；未调整的 RAW 会提示跳过。
- **胶卷库**：新建胶卷资料，关联照片文件夹，记录评分和备注；可用照片、内置暗盒图案或自选图片作为封面。
- **构图**：选择一张排版照片，拖动画面调整裁切中心，支持独立旋转、缩放、填充、帧号标签和排序。
- **保存**：调片自动保存同目录 XML 和内部 JSON。整卷草稿自动保存，也可保存包含照片和背景的 ZIP 项目，和网页版互通。
- **外观**：在「显示」菜单或设置中选择跟随系统、浅色或深色。
- **快捷键**：⌘O 打开文件夹、⇧⌘O 导入照片、⌘L 输入本地路径、⌘S 保存参数、⇧⌘S 保存整卷项目、⌘E 导出、⌘Z 撤销、⇧⌘Z 重做、⌘B 查看底片、⌘0 适合窗口、⌥⌘I 检查器。

## 胶卷档案

切换到「胶卷库」，在「胶卷档案」侧栏点 **+** 新建胶卷，填写胶卷编号、型号、画幅、标称 ISO、实拍 EI、状态、拍摄日期、相机／镜头、地点、冲洗店／工艺／记录、底片存放、标签和备注。侧栏可按名称、相机、地点与标签搜索，按年份／状态筛选，并按拍摄日期、更新时间或名称排序。编辑表单的错误直接显示在表单内，保留已填内容，修正后可再次保存。

选择胶卷后，用「关联照片」添加已导出成片，或关联文件夹全部照片。档案保存来源路径和托管预览，原照片留在原处。照片卡片可编辑 0–5 星评分与备注、设为封面、在调片中打开或在 Finder 显示；原路径失效后用「重新关联缺失路径」选择新文件夹。删除胶卷档案或移除照片关联会保留原照片，操作前显示确认。

「更换封面」可选择暗盒图库、导入图片或清除封面。图库支持胶片／品牌／版本搜索、品牌筛选及型号与画幅匹配；每项展示署名、许可和来源链接，选为封面后这些信息随档案保存。自选封面可在「编辑资料 → 封面来源」补充来源与署名。程序绘制的文字标签不代表原厂包装；外部包装扫描参考以链接打开，不随应用下载。

用工具栏「备份档案」或侧栏菜单导出 ZIP；侧栏菜单也可导入备份、显示档案目录。档案数据由 SQLite 元数据和托管预览组成，备份包含资料、预览与封面来源，**不包含原始照片**。恢复会作为新档案加入，不覆盖现有资料；重复导入会产生重复记录。搬迁原照片后需重新关联路径。此备份与「整卷项目」不同：整卷项目包含用于排版的照片、背景和设置。

## Gamma、影调与配色

调片检查器中的「Gamma 分析」提供「分析这一张」与「分析同卷」。同卷范围优先使用勾选照片；没有勾选时使用当前搜索筛选结果，最多抽样 12 张。界面显示建议值、可信度、抽样数量和未参与分析的错误。建议只作为起点，仍可手动调整；Negadoctor 的对应建议参数为「纸张反差」。

「应用到这张」只应用建议的 Gamma 参数。「锁定到已分析的 N 张」仅在同卷分析后提供，写入分析时记录的整卷范围；单张分析不能进行整卷锁定。当前照片或调整参数变化后需重新分析；同卷分析还要求勾选范围及影响范围的搜索结果与分析时一致。整卷锁定只更新相应的 `gamma` 或 `nd_gamma`，保留每张的曝光、白平衡、曲线、裁剪及其他调整；不匹配的处理模式不会被强制改写，未更新项目会给出提示。

「应用风格」提供自然中性、柔和人像、浓郁反差、通透宽容和柔灰印相五个快捷方案，只修改对比度、饱和度、高光、阴影、白场、黑场和鲜艳度，保留 Gamma、曝光、白平衡、曲线与裁剪，可撤销后继续微调。

整卷配色优先显示有名称的推荐色卡：片基、边字、横幅、文字与背景各有对应颜色，如胶片黑、琥珀、档案白、墨黑和暖纸。展开「自定义颜色」可用系统颜色选择器或输入 `#` 加六位 HEX 色值。色卡有名称与选中状态，作品颜色独立于工作台的浅深色外观。

## 功能范围

调片：彩负、黑白、正片；RAW 解码选项；去色罩、Negadoctor、曝光、色阶、Gamma、对比度、白平衡框选取样及色温色调、分区取样、四通道 PCHIP 曲线、八色 HSL、鲜艳度、降噪、锐化、晕影、参照匹配、预设增删、裁剪比例、旋转镜像、自动裁剪校平与同卷参考、逐片参数、XML 互通、整卷参数／仅白平衡同步、批量按各自参数导出、TIFF 8/16 位、JPEG、PNG、质量与尺寸控制。

整卷：100 款胶卷资料和来源、边字字体／内容／颜色／大小／字距／光晕、帧号／半格编号／箭头、列数／间距／照片比例、片条透明度、齿孔孔形和孔沿、自动或手动片头、片头形状、六类漏光／曝光效果与强度／柔和度／纹理／延伸照片数、分离投影／衬边、模糊照片／纯色／渐变／透明背景及自定义背景、信息横幅、逐帧构图与拖动排序、选择集、撤销重做、草稿、版式预设、便携项目、PNG/JPEG 高清导出。

旧 SwiftUI 版 UserDefaults 中的调整会在没有 XML/JSON 参数时读取并迁移。原来的 `FilmDecastCore` 与 `SmokeTest` 保留供引擎开发与对照。

## 切换与保存的实现

`WorkbenchState` 使用 Observation 按属性追踪界面依赖。调片与整卷排版的侧栏、检查器和画布保留各自的 `NSHostingView`，固定视口并关闭其固有尺寸协商，切换只改变可见宿主，避免隐藏的 Form／List 参与当前页面尺寸计算。每个画布固定所属工作区，胶卷库的侧栏与内容宿主在首次进入时建立。外观变化仍传入所有宿主，切换前会结束离开面板内的文本编辑。

build 5 将透明棋盘格限制在整卷画布，并把灰格合并为一次路径填充；不透明的调片预览省去棋盘格绘制。作品投影由矩形背板承担，避免对整棵图像与覆盖层计算投影。调片／整卷的两个主要工具栏按钮保持稳定身份，随工作区更新标签和操作。双指缩放从每次手势开始时的当前倍率取基线，结束或取消时清空基线；物理触控板手势尚未实测。

本地引擎通信在串行后台队列执行；预览的 Base64／图像解码和缩略图解码放到后台。共享解码缓存上限为 48 MiB，相同的进行中缩略图请求会合并；底片预览按需获取。整卷草稿保存延迟 600 ms 合并连续编辑，后台编码与写入按顺序完成。正常退出时等待最终草稿和当前照片参数写入，取消的旧任务不会覆盖最后快照。

2026-10-24 在同一台 Apple Silicon Mac、macOS 27.0.1、相同 1440 × 920 点深色窗口、同一组 24 张合成 JPEG 上，使用固定坐标指针点击，在两个已加载工作区之间分别测量 12 次交替切换。build 5 使用最终打包的可执行文件复测：

| 构建 | 切换次数 | `state_to_idle_ms` 中位数 | 最大值 |
| --- | ---: | ---: | ---: |
| 2.1 build 4 | 12 | 76.26 ms | 106.20 ms |
| 2.1 build 5（最终打包可执行文件） | 12 | 40.43 ms | 44.77 ms |

同条件下中位数降低约 **47%**。指标从工作区状态变更计到主运行循环下一次 `beforeWaiting`，覆盖该区间的布局／提交处理，**不是点击到屏幕呈现的延迟**，也不证明大型真实 RAW 胶卷的性能。此前约 61 ms 的测量夹杂辅助功能树查询，查询会干扰主线程工作，与本次指针坐标测量不能直接比较。历史证据保留在[验证记录](../work/native-parity/validation.md)；本轮原始记录为 [build 4](../work/native-parity/switch-build4-pointer.jsonl) 和 [build 5 发布产物](../work/native-parity/switch-build5-shipping-pointer.jsonl)，位于本地忽略目录，以上摘要可独立阅读。

### 可选切换诊断

诊断默认关闭。退出应用后，可在终端启用并重新打开应用：

```bash
defaults write local.NegativeMaster native.profileSwitches -bool true
```

启用后，每个进程在本机临时目录写入 `NegativeMaster-switches-<PID>.jsonl`，仅记录 `pid`、工作区 `mode`、经过时间 `state_to_idle_ms` 和同一区间的主线程 CPU 时间 `main_thread_cpu_to_idle_ms`，不记录照片、路径或编辑内容，也不会上传。两项计时都从工作区状态开始改变到主运行循环下一次 `beforeWaiting`；CPU 时间用于区分主线程实际工作与经过时间，不代表 GPU 工作或屏幕呈现。关闭后重启应用即可停止记录：

```bash
defaults delete local.NegativeMaster native.profileSwitches
```

## 构建

需要 macOS 和 Swift 6.3 工具链（本机 Command Line Tools 可构建）。

```bash
cd FilmDecastSwift
./build-app.sh
open ../NegativeMaster.app
```

首次构建使用项目 `.venv` 的固定依赖，并将其连同 Python 标准库和动态库放入应用。后续构建复用已打包运行时；如果依赖有变，删除生成的应用后重新打包，或更换输出路径：

```bash
./build-app.sh /absolute/path/NegativeMaster.app
```

开发时可以直接 `swift run FilmDecast`，它会使用源项目 `.venv`；打包后的应用使用内置运行时。源目录仍存在时与网页版共享 settings/presets；移动应用到其他机器后，内部配置放在 `~/Library/Application Support/NegativeMaster`。照片旁的 XML 不依赖此目录。

## 验证

以下命令从 `FilmDecastSwift` 目录执行：

```bash
swift test -c release
../.venv/bin/python -m unittest discover -s ../tests -p test_native_bridge.py -v
../.venv/bin/python -m unittest discover -s ../tests -v
swift run -c release SmokeTest
```

2026-10-24 build 5 的 [Release Swift 测试日志](../work/native-parity/swift-tests-build5.log)记录 **9 项通过，0 项失败**，包括通信取消／顺序、缩略图请求合并与暖缓存、Gamma 建议边界、整卷分析范围及单张分析限制、影调参数保留、Observation 更新隔离和草稿最终写入顺序。

`tests/test_native_bridge.py` 覆盖原生传输、完整调色参数、解码选项、预设 CRUD、XML 往返、TIFF/JPEG/PNG 导出、原图保护、整卷预览／导出、单帧构图、带背景项目导入导出、档案增删改与照片关联、封面来源和备份恢复、Gamma 单项写入与模式不匹配时保留参数，以及按需底片和轻量缩略图。

截至 build 4 的 Python／Node 与打包引擎结果继续保留在[验证记录](../work/native-parity/validation.md)：Python 共 150 项，148 项可运行测试已验证通过，2 项平台跳过；其中两项本机 HTTP 启动探针清除代理并设置 loopback `NO_PROXY` 后单独重跑通过。Node 46 项通过，[打包引擎桥接日志](../work/native-parity/bundle-tests.log)记录 13 项通过。本轮改动限于 Swift 界面、诊断与构建版本，未重跑这三组测试。

build 5 的六张场景截图位于 [`.impeccable/review/native-parity`](../.impeccable/review/native-parity/)：`build5-sheet-dark.png`、`build5-develop-dark.png`、`build5-develop-light.png`、`build5-sheet-light.png`、`build5-frame-light.png` 和 `build5-archive-light.png`。最终打包可执行文件另有 `build5-shipping-develop-dark.png` 和 `build5-shipping-sheet-dark.png` 两张复测截图。桌面窗口为 1440 × 920 点，使用 24 张合成 JPEG 与独立测试档案。独立完成评审在本轮性能修正与六个桌面场景范围内给出 **SHIP**，未发现需修正的实质问题；发布产物复测后照片数量与 Gamma 0.85 仍保留。较早截图与档案表单验证继续作为对应历史版本的证据。

本轮已验证切换后 24 张照片数量、曝光 0.25 与 Gamma 0.85 保留，随后将测试曝光恢复为 0；单张构图视图保留，昼夜外观正常传播。build 4 已验证未完成的曝光输入恢复上次有效值并离开焦点，以及档案 ISO 0 的表单内报错、草稿保留和改为 ISO 200 后保存。物理触控板双指缩放、窄桌面窗口、完整 VoiceOver 遍历和大型真实 RAW 胶卷尚未验收；相机 RAW 支持仍取决于 LibRaw 对机型的支持。

## 设计文档边界

本次是现有原生 macOS 工作台的功能与性能扩展，保留以照片为中心的布局、原生侧栏／检查器、标准工具栏和控件。仓库的 [PRODUCT.md](../PRODUCT.md) 仍将平台标为 `web`，[DESIGN.md](../DESIGN.md) 与 `.impeccable/design.json` 描述的是 CSS／HTML 工作台；现有 surface brief 也尚未关联原生源码。这是既有的网页／原生上下文差异，本说明仅记录，不改写设计文件，也不把网页断点与方角样式当作原生验收要求。

Apple 设计依据：

- [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- [Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/liquid-glass)
