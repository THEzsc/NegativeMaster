// swift-tools-version: 5.9
// FilmDecast —— 胶片翻拍去色罩工具（SwiftUI 原生版）
// 包结构：
//   FilmDecastCore  —— 引擎库（模型 / 处理管线 / 导出），纯计算，不依赖 UI
//   FilmDecast      —— SwiftUI 工作台（Sources/NativeWorkbench）
import PackageDescription

let package = Package(
    name: "FilmDecast",
    platforms: [.macOS(.v14)],
    targets: [
        // 引擎库：Models / NegativeEngine / ImageExporter
        .target(
            name: "FilmDecastCore",
            path: "Sources/FilmDecastCore"
        ),
        // 原生工作台入口；通过随应用打包的本地引擎完成图像处理
        .executableTarget(
            name: "FilmDecast",
            dependencies: ["FilmDecastCore"],
            path: "Sources/NativeWorkbench"
        ),
        .testTarget(name: "NativeWorkbenchTests", dependencies: ["FilmDecast"], path: "Tests/NativeWorkbenchTests"),
        // 算法冒烟测试：swift run SmokeTest
        // 用 64x64 合成负片（已知橙色罩 + 灰阶）验证核心反转管线的正确性
        .executableTarget(
            name: "SmokeTest",
            dependencies: ["FilmDecastCore"],
            path: "Sources/SmokeTest"
        ),
    ]
)
