//
//  FilmDecastApp.swift —— SwiftUI 应用入口
//
//  单窗口应用：左侧文件列表 / 中间预览+裁切框 / 右侧控制面板。
//  引擎全部来自 FilmDecastCore，本目标只做界面与调度。
//

import SwiftUI

/// 应用入口：默认窗口 1280x800
@main
struct FilmDecastApp: App {
    /// 全局应用状态（文件列表 / 当前图像 / 冲洗参数 / 渲染结果）
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup("胶片去色罩") {
            ContentView()
                .environmentObject(state)
                .frame(minWidth: 1000, minHeight: 620)
        }
        .defaultSize(width: 1280, height: 800)
    }
}
