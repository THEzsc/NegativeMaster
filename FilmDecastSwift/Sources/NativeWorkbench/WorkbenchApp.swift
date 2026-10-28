import SwiftUI

@main struct NativeWorkbenchApp: App {
  @NSApplicationDelegateAdaptor(WorkbenchDelegate.self) private var delegate
  @State private var state = WorkbenchState()
  @AppStorage("native.appearance") private var appearance = "system"
  var body: some Scene {
    Window("NegativeMaster", id: "workbench") {
      WorkbenchView().environment(state)
        .preferredColorScheme(appearance == "dark" ? .dark : appearance == "light" ? .light : nil)
        .task {
          delegate.state = state
          await state.bootstrap()
        }
    }
    .defaultSize(width: 1440, height: 920)
    .windowStyle(.automatic)
    .commands {
      CommandGroup(replacing: .newItem) {
        Button("打开路径…") {
          state.pathEntry = ""
          state.showPathSheet = true
        }.keyboardShortcut("l").disabled(!state.ready || state.busy)
        Button("打开胶卷文件夹…", action: state.chooseFolder).keyboardShortcut("o").disabled(
          !state.ready || state.busy)
        Button("导入照片…", action: state.chooseFiles).keyboardShortcut(
          "o", modifiers: [.command, .shift]
        ).disabled(!state.ready || state.busy)
        Button("打开整卷项目…", action: state.chooseProject).disabled(!state.ready || state.busy)
        Divider()
        Button("保存调整参数", action: { state.persistNow(sidecar: true) }).keyboardShortcut("s")
          .disabled(state.selected == nil || state.workspace != .develop)
        Button("保存整卷项目…", action: state.saveProject).keyboardShortcut(
          "s", modifiers: [.command, .shift]
        ).disabled(state.sheetSelection.isEmpty || state.busy)
        Button("导出…", action: state.exportCurrent).keyboardShortcut("e").disabled(
          state.busy
            || (state.workspace == .develop ? state.preview == nil : state.workspace == .sheet ? state.sheetImage == nil : !state.archive.loaded))
      }
      CommandGroup(after: .importExport) {
        Button("整卷导出…") { state.presentRollExport() }
          .keyboardShortcut("e", modifiers: [.command, .shift])
          .disabled(state.workspace != .develop || state.filteredPhotos.isEmpty || state.busy || !state.ready)
      }
      CommandGroup(replacing: .undoRedo) {
        Button("撤销", action: state.undo).keyboardShortcut("z").disabled(
          !state.canUndo || state.busy || state.workspace == .archive)
        Button("重做", action: state.redo).keyboardShortcut("z", modifiers: [.command, .shift])
          .disabled(!state.canRedo || state.busy || state.workspace == .archive)
      }
      CommandGroup(replacing: .help) { Button("NegativeMaster 使用说明") { state.showHelp = true } }
      CommandMenu("照片") {
        Button("顺时针旋转", action: { state.rotate(90) }).keyboardShortcut("r", modifiers: .command)
          .disabled(state.selected == nil || state.workspace != .develop)
        Button("水平镜像", action: { state.mirror("h") }).disabled(state.selected == nil || state.workspace != .develop)
        Button("自动裁剪与校平", action: state.autoCrop).disabled(state.selected == nil || state.busy || state.workspace != .develop)
        Button("整卷自动裁剪…") { state.presentRollAutomation("crop") }.disabled(state.photos.isEmpty || state.busy || state.workspace != .develop)
        Button("整卷逐张 Gamma 分析…") { state.presentRollAutomation("gamma") }.disabled(state.photos.isEmpty || state.busy || state.workspace != .develop)
        Button("裁剪与微量旋转", action: state.beginCrop).keyboardShortcut("c", modifiers: [.command, .option])
          .disabled(state.selected == nil || state.workspace != .develop)
        Button("生成缩略图", action: state.generateThumbnails).disabled(state.photos.isEmpty)
        Button("重置调整", action: state.resetDevelop).disabled(state.selected == nil || state.workspace != .develop)
      }
      CommandGroup(after: .toolbar) {
        Button(state.inspector ? "隐藏检查器" : "显示检查器", action: { state.inspector.toggle() })
          .keyboardShortcut("i", modifiers: [.command, .option])
        Button("适合窗口", action: { state.zoom = 1 }).keyboardShortcut("0")
        Toggle("照片栏放在底部", isOn: $state.filmstripBottom)
        Picker("外观", selection: $appearance) {
          Text("跟随系统").tag("system")
          Text("浅色").tag("light")
          Text("深色").tag("dark")
        }
        Picker("工作区", selection: $state.workspace) {
          ForEach(WorkbenchState.Workspace.allCases, id: \.self) { Text($0.rawValue).tag($0) }
        }
      }
    }
    Settings {
      Form {
        Picker("外观", selection: $appearance) {
          Text("跟随系统").tag("system")
          Text("浅色").tag("light")
          Text("深色").tag("dark")
        }
        LabeledContent("处理方式", value: "本地处理，照片留在这台 Mac")
        Text("调片参数自动保存；按 ⌘S 写入照片旁的 XML。整卷项目包含照片、背景和排版，可在网页版与 Mac 版之间打开。")
          .font(.callout).foregroundStyle(.secondary)
      }.formStyle(.grouped).frame(width: 470, height: 240)
    }
  }
}

@MainActor final class WorkbenchDelegate: NSObject, NSApplicationDelegate {
  weak var state: WorkbenchState?
  func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
    guard let state else { return .terminateNow }
    Task {
      await state.flushBeforeQuit()
      sender.reply(toApplicationShouldTerminate: true)
    }
    return .terminateLater
  }
}
