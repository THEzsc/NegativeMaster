# NegativeMaster · SwiftUI 工作台

这是原生 SwiftUI 前端：NavigationSplitView 缩略图侧栏、独立检查器、系统工具栏、菜单、文件面板、颜色面板与浅深色外观。使用系统提供的外观适配 macOS 27；照片和排版位于内容层，操作位于系统导航层。

前端不嵌入网页。图像处理复用仓库中已验证的 Python 算法，Swift 与独立本地进程通过 JSON 管道通信，不监听网络端口。打包脚本包含 Python、图像库、胶卷资料、字体与全部渲染资源。

## 使用

双击项目根目录的 `NegativeMaster.app`，也可以拖到「应用程序」。构建时按本机处理器架构打包；当前交付包是 Apple Silicon 版，已在 macOS 27.0.1 验证启动。

- **调片**：打开文件夹或导入照片，左侧选择，右侧切换光线、色彩、曲线、细节、裁剪、导出。
- **整卷排版**：导入成片或打开胶卷文件夹。文件夹优先使用已导出成片，其次读取各照片保存的参数；未调整的 RAW 会提示跳过。
- **构图**：选择一张排版照片，拖动画面调整裁切中心，支持独立旋转、缩放、填充、帧号标签和排序。
- **保存**：调片自动保存同目录 XML 和内部 JSON。整卷草稿自动保存，也可保存包含照片和背景的 ZIP 项目，和网页版互通。
- **快捷键**：⌘O 打开文件夹、⇧⌘O 导入照片、⌘L 输入本地路径、⌘S 保存参数、⇧⌘S 保存整卷项目、⌘E 导出、⌘Z 撤销、⇧⌘Z 重做、⌘B 查看底片、⌘0 适合窗口、⌥⌘I 检查器。

## 功能范围

调片：彩负、黑白、正片；RAW 解码选项；去色罩、Negadoctor、曝光、色阶、Gamma、对比度、白平衡框选取样及色温色调、分区取样、四通道 PCHIP 曲线、八色 HSL、鲜艳度、降噪、锐化、晕影、参照匹配、预设增删、裁剪比例、旋转镜像、自动裁剪校平与同卷参考、逐片参数、XML 互通、整卷参数／仅白平衡同步、批量按各自参数导出、TIFF 8/16 位、JPEG、PNG、质量与尺寸控制。

整卷：100 款胶卷资料和来源、边字字体／内容／颜色／大小／字距／光晕、帧号／半格编号／箭头、列数／间距／照片比例、片条透明度、齿孔孔形和孔沿、自动或手动片头、片头形状、六类漏光／曝光效果与强度／柔和度／纹理／延伸照片数、分离投影／衬边、模糊照片／纯色／渐变／透明背景及自定义背景、信息横幅、逐帧构图与拖动排序、选择集、撤销重做、草稿、版式预设、便携项目、PNG/JPEG 高清导出。

旧 SwiftUI 版 UserDefaults 中的调整会在没有 XML/JSON 参数时读取并迁移。原来的 `FilmDecastCore` 与 `SmokeTest` 保留供引擎开发与对照。

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

```bash
../.venv/bin/python -m unittest discover -s ../tests -v
swift run -c release SmokeTest
```

`tests/test_native_bridge.py` 覆盖原生传输、完整调色参数、解码选项、预设 CRUD、XML 往返、TIFF/JPEG/PNG 导出、原图保护、整卷预览／导出、单帧构图以及带背景项目的导入导出。真实相机 RAW 的支持仍取决于 LibRaw 对机型的支持。

Apple 设计依据：
- https://developer.apple.com/design/human-interface-guidelines/toolbars
- https://developer.apple.com/design/human-interface-guidelines/sidebars
- https://developer.apple.com/documentation/technologyoverviews/liquid-glass
