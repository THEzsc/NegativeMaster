# FilmDecast —— 在 Xcode 里调试运行

SwiftUI 原生版胶片去色罩工具。要求 **macOS 14+**、Xcode 15 及以上。

## 包结构

```
FilmDecastSwift/
├── Package.swift
└── Sources/
    ├── FilmDecastCore/     引擎库（纯计算，不依赖 UI）
    │   ├── Models.swift            数据模型（LinearImage / DevelopParams / …）
    │   ├── NegativeEngine.swift    读取 / 反转 / 白平衡 / 匹配 / 探测画面
    │   └── ImageExporter.swift     导出 16bit TIFF / JPEG
    └── FilmDecastApp/      SwiftUI 界面层（executable target「FilmDecast」）
        ├── FilmDecastApp.swift     @main 入口，窗口默认 1280x800
        ├── AppState.swift          应用状态 / 防抖渲染调度 / 导出 / 参数记忆
        ├── ContentView.swift       三栏布局 + 左侧文件列表 + 中间预览
        ├── CropOverlayView.swift   可拖动裁切框（手柄缩放 / 比例锁定）
        ├── ControlsView.swift      右侧控制面板（分组 GroupBox）
        └── HistogramView.swift     RGB 直方图（Canvas）
```

## 方式一：直接打开 Swift 包（推荐）

```bash
cd /Users/apple/Pictures/胶片扫描/去色罩工具/FilmDecastSwift
xed .            # 或者在 Finder 里双击 Package.swift
```

1. Xcode 打开后等待包解析完成（本包无第三方依赖，几秒即可）。
2. 顶部 scheme 选 **FilmDecast**（可执行目标），目的地选 **My Mac**。
3. `Cmd+R` 直接运行调试。断点、Instruments 都可正常使用。

命令行也可以直接跑：

```bash
swift run FilmDecast     # 或 swift build 后运行 .build/debug/FilmDecast
```

## 方式二：新建 macOS App 工程

如果想要正式的 `.app`（图标、签名、发布）：

1. Xcode → File → New → Project → **macOS App**（Interface 选 SwiftUI，
   Language 选 Swift），最低部署版本设为 **macOS 14.0**。
2. 删掉模板自动生成的 `ContentView.swift` 和 `XxxApp.swift`。
3. 把 `Sources/FilmDecastCore` 和 `Sources/FilmDecastApp` 两个文件夹整体
   拖进工程（勾选 "Copy items if needed" 或用引用方式均可）。
   也可以改用 File → Add Package Dependencies → Add Local，把本包作为
   本地包依赖，只拖 `FilmDecastApp` 里的界面文件。
4. **关闭 App Sandbox**：Target → Signing & Capabilities → 删除
   "App Sandbox" 能力；或保留沙盒但勾上
   "User Selected File – Read/Write"（本 App 全部通过 NSOpenPanel /
   NSSavePanel 访问文件，用户选择读写权限即可满足）。
5. 签名用本机的 "Sign to Run Locally" 即可，无需开发者账号。

## 注意事项

- **SPM 可执行目标默认无沙盒、无需 Info.plist、无需签名**，
  文件读写没有限制，方式一开箱即用。
- RAW 解码走系统 `CIRAWFilter`（Sony ARW、ARQ / Canon CR2、CR3 / Nikon NEF /
  Fuji RAF / DNG / Panasonic RW2 等），不依赖 Python 环境。
- 每张图的调整参数自动记到 `UserDefaults`（key = 文件路径），
  下次打开同一文件自动恢复；「恢复默认参数」可清回默认。
- 预览为 1500px 下采样。裁切框内的颜色是按「真裁切」统计渲染的，
  与导出结果一致；框外区域是整幅统计的背景渲染，仅供定位参考。
- 全分辨率图只在内存中保留当前一张；批量导出逐张解码、逐张释放。
