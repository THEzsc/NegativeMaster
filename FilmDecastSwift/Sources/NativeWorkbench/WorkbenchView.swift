import ImageIO
import SwiftUI

struct WorkbenchView: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  @State private var columnVisibility: NavigationSplitViewVisibility = .all
  var body: some View {
    NavigationSplitView(columnVisibility: $columnVisibility) {
      WorkspacePane(state: s, mode: s.workspace, kind: .sidebar)
        .navigationSplitViewColumnWidth(min: 220, ideal: 265, max: 340)
    } detail: {
      VStack(spacing: 0) {
        WorkspacePane(state: s, mode: s.workspace, kind: .canvas)
        if s.workspace == .develop && s.filmstripBottom {
          PhotoBrowser(horizontal: true).frame(height: 150)
        }
        if s.workspace != .archive { WorkbenchStatusBar() }
      }
      .navigationTitle(
        s.workspace == .develop ? (s.currentPhoto?.name ?? "NegativeMaster") : s.workspace.rawValue
      )
      .toolbar { toolbar }
      .inspector(isPresented: Binding(get: { s.inspector && s.workspace != .archive }, set: { if s.workspace != .archive { s.inspector = $0 } })) {
        WorkspacePane(state: s, mode: s.workspace, kind: .inspector)
          .inspectorColumnWidth(min: 310, ideal: 350, max: 420)
      }
    }
    .frame(minWidth: 1000, minHeight: 700)
    .onAppear { columnVisibility = s.filmstripBottom && s.workspace == .develop ? .detailOnly : .all }
    .onChange(of: s.filmstripBottom) { _, bottom in columnVisibility = bottom && s.workspace == .develop ? .detailOnly : .all }
    .onChange(of: s.workspace) { _, mode in columnVisibility = s.filmstripBottom && mode == .develop ? .detailOnly : .all }
    .sheet(isPresented: bindings.showRollAutomation) { RollAutomationSheet().environment(s) }
    .sheet(isPresented: bindings.showTransfer) { RollTransferSheet().environment(s) }
    .onDrop(of: ["public.file-url"], isTargeted: nil) { providers in
      Task {
        var urls: [URL] = []
        for provider in providers {
          let url: URL? = await withCheckedContinuation { continuation in
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
              continuation.resume(returning: url)
            }
          }
          if let url { urls.append(url) }
        }
        s.acceptURLs(urls)
      }
      return !providers.isEmpty
    }
    .alert(
      "操作未完成", isPresented: Binding(get: { s.error != nil }, set: { if !$0 { s.error = nil } })
    ) {
      Button("好", role: .cancel) { s.error = nil }
    } message: {
      Text(s.error ?? "")
    }
    .sheet(isPresented: bindings.showPathSheet) {
      VStack(alignment: .leading, spacing: 20) {
        Text("打开路径").font(.title2.bold())
        Text("输入照片、胶卷文件夹或整卷项目的本地路径。").foregroundStyle(.secondary)
        TextField("/Users/…", text: bindings.pathEntry).textFieldStyle(.roundedBorder).onSubmit {
          s.openEnteredPath()
        }
        HStack {
          Spacer()
          Button("取消") { s.showPathSheet = false }.keyboardShortcut(.cancelAction)
          Button("打开", action: s.openEnteredPath).keyboardShortcut(.defaultAction)
        }
      }.padding(24).frame(width: 500)
    }
    .sheet(isPresented: bindings.showRollExport) { RollExportSheet().environment(s) }
    .sheet(isPresented: bindings.showHelp) {
      VStack(alignment: .leading, spacing: 18) {
        Text("NegativeMaster").font(.largeTitle.bold())
        Text("调片与整卷排版").font(.title3).foregroundStyle(.secondary)
        Label("打开胶卷文件夹，从侧栏选择底片。", systemImage: "folder")
        Label("右侧分组调整影调、色彩、曲线与画幅。", systemImage: "slider.horizontal.3")
        Label("按 ⌘B 比较原片；⌘Z 撤销，⌘E 导出。", systemImage: "keyboard")
        Label("拖动排版照片排序，选择单张后拖动画面调整构图。", systemImage: "rectangle.split.3x3")
        Label("保存整卷项目会包含照片、背景和排版设置。", systemImage: "square.and.arrow.down")
        Text("调片参数会自动保存为 XML。所有图像处理都在本机完成。").font(.callout).foregroundStyle(.secondary)
        HStack {
          Spacer()
          Button("开始使用") { s.showHelp = false }.keyboardShortcut(.defaultAction)
        }
      }.padding(28).frame(width: 490)
    }
    .sheet(isPresented: bindings.showNameSheet) {
      VStack(alignment: .leading, spacing: 20) {
        Text(s.namePurpose == "layout" ? "保存排版样式" : "保存调色预设").font(.title2.bold())
        TextField("名称", text: bindings.nameEntry).textFieldStyle(.roundedBorder).onSubmit {
          s.saveNamed()
        }
        HStack {
          Spacer()
          Button("取消") { s.showNameSheet = false }.keyboardShortcut(.cancelAction)
          Button("保存", action: s.saveNamed).keyboardShortcut(.defaultAction).disabled(
            s.nameEntry.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
      }.padding(24).frame(width: 380)
    }
  }
  @ToolbarContentBuilder private var toolbar: some ToolbarContent {
    ToolbarItem(placement: .principal) {
      Picker("工作区", selection: bindings.workspace) {
        ForEach(WorkbenchState.Workspace.allCases, id: \.self) { Text($0.rawValue).tag($0) }
      }.pickerStyle(.segmented).frame(width: 290)
    }
    ToolbarItemGroup(placement: .primaryAction) {
      Button(action: s.undo) { Label("撤销", systemImage: "arrow.uturn.backward") }.disabled(
        !s.canUndo || s.busy || s.workspace == .archive)
      Button(action: s.redo) { Label("重做", systemImage: "arrow.uturn.forward") }.disabled(
        !s.canRedo || s.busy || s.workspace == .archive)
    }
    ToolbarItemGroup(placement: .primaryAction) {
      if s.workspace != .archive {
        Button {
          if s.workspace == .develop { s.autoCrop() } else { s.frameView = false }
        } label: {
          Label(s.workspace == .develop ? "自动裁剪与校平" : "整卷预览",
                systemImage: s.workspace == .develop ? "crop.rotate" : "rectangle.split.3x3")
        }.disabled(s.workspace == .develop && (s.preview == nil || s.busy))
        if s.workspace == .develop {
          NegativeHoldButton(state: s).frame(width: 34, height: 28)
        } else {
          Button(action: s.saveProject) { Label("保存项目", systemImage: "square.and.arrow.down") }
            .disabled(s.sheetSelection.isEmpty || s.busy)
        }
      }
    }
    ToolbarItem(placement: .primaryAction) {
      if s.workspace == .archive { ArchiveBackupButton(a: s.archive) }
      else if s.workspace == .develop {
        Menu {
          Button("导出当前照片…", action: s.exportCurrent).disabled(s.preview == nil)
          Button("整卷导出…") { s.presentRollExport() }
            .disabled(s.filteredPhotos.isEmpty)
          Button("导出所选照片…", action: s.exportBatch).disabled(s.visibleCheckedPhotos.isEmpty)
          Divider()
          Button("发送到整卷排版…") { s.presentTransfer("sheet") }
          Button("索引到胶卷库…") { s.presentTransfer("archive") }
        } label: { Label("导出", systemImage: "square.and.arrow.up") }
          .accessibilityLabel("导出").help("导出当前照片、整卷或勾选照片")
          .disabled(s.busy || !s.ready || s.photos.isEmpty)
      } else {
        Button(action: s.exportSheet) { Label("导出整卷图片", systemImage: "square.and.arrow.up") }
          .disabled(s.busy || s.sheetImage == nil)
      }
    }
    ToolbarItem(placement: .primaryAction) {
      Button {
        s.inspector.toggle()
      } label: {
        Label("检查器", systemImage: "sidebar.right")
      }.disabled(s.workspace == .archive)
    }
  }
}

private struct WorkbenchStatusBar: View {
  @Environment(WorkbenchState.self) var s
  var body: some View {
    HStack(spacing: 10) {
      if s.rendering || s.busy {
        ProgressView().controlSize(.small).scaleEffect(0.7).frame(width: 14, height: 14)
      }
      Text(s.status).font(.caption).foregroundStyle(.secondary).lineLimit(1)
      Spacer(minLength: 10)
      if !s.warnings.isEmpty {
        Menu {
          ForEach(s.warnings, id: \.self) { Text($0) }
        } label: {
          Label("\(s.warnings.count) 条提示", systemImage: "exclamationmark.triangle")
        }.menuStyle(.borderlessButton).fixedSize()
      }
      if s.batchRunning {
        Button("停止后续导出", action: s.cancelOperation).buttonStyle(.borderless).font(.caption)
      }
      if s.lastExport != nil {
        Button("显示导出文件", action: s.revealExport).buttonStyle(.borderless).font(.caption)
      }
      if s.thumbnailDone < s.thumbnailTotal {
        Text("缩略图 \(s.thumbnailDone) / \(s.thumbnailTotal)").font(.caption2).foregroundStyle(.secondary)
      }
    }.padding(.horizontal, 16).frame(height: 32).background(.bar)
  }
}

struct PhotoSidebar: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  let mode: WorkbenchState.Workspace
  var body: some View {
    VStack(spacing: 0) {
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text(mode == .develop ? "胶卷照片" : "排版照片").font(.headline)
          Text(
            mode == .develop
              ? "\(s.filteredPhotos.count) / \(s.photos.count) 张照片" : "\(s.sheetSelection.count) / \(s.sheetPhotos.count) 张已选"
          ).font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        Menu {
          Button("打开文件夹…", action: s.chooseFolder)
          Button("导入照片…", action: s.chooseFiles)
          Button("打开路径…") {
            s.pathEntry = ""
            s.showPathSheet = true
          }
          if mode == .develop {
            Button("照片栏移到底部") { s.filmstripBottom = true }
            Button("生成缩略图", action: s.generateThumbnails)
          }
          if let folder = s.folder, mode == .develop {
            Button("刷新文件夹") { s.openFolder(folder) }
          }
          if mode == .sheet { Button("打开项目…", action: s.chooseProject) }
        } label: {
          Image(systemName: "plus")
        }.menuStyle(.borderlessButton).fixedSize().disabled(!s.ready || s.busy)
      }.padding(16)
      if mode == .develop {
        TextField("搜索照片", text: bindings.search).textFieldStyle(.roundedBorder).padding(.horizontal, 12)
          .padding(.bottom, 8)
        Toggle("只显示 RAW", isOn: bindings.rawOnly).toggleStyle(.checkbox)
          .padding(.horizontal, 12).padding(.bottom, 8)
        PhotoBrowser()
          .overlay {
            if s.filteredPhotos.isEmpty && !s.photos.isEmpty {
              Text("没有符合筛选条件的照片").font(.callout).foregroundStyle(.secondary).padding(20)
            }
          }
      } else {
        List {
          ForEach(s.sheetPhotos) { p in
            HStack(spacing: 10) {
              Toggle(
                "加入排版",
                isOn: Binding(
                  get: { s.sheetSelection.contains(p.sheetID) },
                  set: { _ in s.toggleFrame(p.sheetID) })
              ).labelsHidden().toggleStyle(.checkbox)
              SheetThumbnail(photo: p, job: s.sheetJob, engine: s.engine).frame(width: 50, height: 44).clipShape(
                RoundedRectangle(cornerRadius: 5))
              VStack(alignment: .leading, spacing: 4) {
                Text(p.name).lineLimit(1).truncationMode(.middle)
                Text(p.source == "saved" ? "已保存的调片" : p.source == "export" ? "已导出成片" : "导入照片").font(
                  .caption2
                ).foregroundStyle(.secondary)
              }
              Spacer(minLength: 0)
            }
            .padding(.vertical, 4).contentShape(Rectangle())
            .listRowBackground(
              s.activeFrame == p.sheetID ? Color.accentColor.opacity(0.14) : Color.clear
            )
            .onTapGesture { s.activateFrame(p.sheetID) }
            .onDrag { NSItemProvider(object: String(p.sheetID) as NSString) }
            .onDrop(of: ["public.text"], isTargeted: nil) { providers in
              guard let provider = providers.first else { return false }
              _ = provider.loadObject(ofClass: String.self) { value, _ in
                if let value, let from = Int(value) {
                  Task { @MainActor in s.reorderFrame(from: from, to: p.sheetID) }
                }
              }
              return true
            }
            .contextMenu {
              Button("前移") {
                s.activeFrame = p.sheetID
                s.moveFrame(-1)
              }
              Button("后移") {
                s.activeFrame = p.sheetID
                s.moveFrame(1)
              }
            }
          }
        }.listStyle(.sidebar)
      }
      HStack {
        Button("全选") {
          if mode == .develop {
            s.checked = Set(s.filteredPhotos.map(\.path))
          } else {
            s.selectAllFrames(true)
          }
        }
        Button("清空") {
          if mode == .develop { s.checked = [] } else { s.selectAllFrames(false) }
        }
        Spacer()
        if mode == .sheet {
          Button {
            s.reverseFrames()
          } label: {
            Image(systemName: "arrow.up.arrow.down")
          }.help("反转照片顺序")
        } else {
          Text("已选 \(s.visibleCheckedPhotos.count)").font(.caption).foregroundStyle(.secondary)
        }
      }.buttonStyle(.borderless).controlSize(.small).padding(12)
    }
  }
}

struct LocalThumbnail: View {
  let path: String
  var body: some View { CachedPhoto(path: path, size: 160) }
}
struct SheetThumbnail: View {
  let photo: Photo
  let job: String
  let engine: EngineBridge
  @State private var image: NSImage?
  var body: some View {
    ZStack {
      Color.secondary.opacity(0.08)
      if let image {
        Image(nsImage: image).resizable().scaledToFit()
      } else {
        Image(systemName: "photo").foregroundStyle(.tertiary)
      }
    }
    .task(id: job + String(photo.sheetID)) {
      do {
        let id = photo.sheetID
        let cg = try await ImagePipeline.shared.image(key: "sheet:\(job):\(id)", size: 160) {
          let r = try await engine.call(.object(["action": .string("thumbnail"), "body": .object(["job": .string(job), "id": .number(Double(id))])]))
          guard let data = Data(base64Encoded: r["bytes"].string) else { throw WorkbenchError(message: "缩略图读取失败") }
          return data
        }
        if !Task.isCancelled, let cg { image = NSImage(cgImage: cg, size: .zero) }
      } catch {}
    }
  }
}
