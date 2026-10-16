import ImageIO
import SwiftUI

struct WorkbenchView: View {
  @EnvironmentObject var s: WorkbenchState
  var body: some View {
    NavigationSplitView {
      sidebar.navigationSplitViewColumnWidth(min: 220, ideal: 265, max: 340)
    } detail: {
      VStack(spacing: 0) {
        WorkbenchCanvas()
        statusBar
      }
      .navigationTitle(
        s.workspace == .develop ? (s.currentPhoto?.name ?? "NegativeMaster") : "整卷排版"
      )
      .toolbar { toolbar }
      .inspector(isPresented: $s.inspector) {
        WorkbenchInspector().inspectorColumnWidth(min: 310, ideal: 350, max: 420)
      }
    }
    .frame(minWidth: 1000, minHeight: 700)
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
    .sheet(isPresented: $s.showPathSheet) {
      VStack(alignment: .leading, spacing: 20) {
        Text("打开路径").font(.title2.bold())
        Text("输入照片、胶卷文件夹或整卷项目的本地路径。").foregroundStyle(.secondary)
        TextField("/Users/…", text: $s.pathEntry).textFieldStyle(.roundedBorder).onSubmit {
          s.openEnteredPath()
        }
        HStack {
          Spacer()
          Button("取消") { s.showPathSheet = false }.keyboardShortcut(.cancelAction)
          Button("打开", action: s.openEnteredPath).keyboardShortcut(.defaultAction)
        }
      }.padding(24).frame(width: 500)
    }
    .sheet(isPresented: $s.showHelp) {
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
    .sheet(isPresented: $s.showNameSheet) {
      VStack(alignment: .leading, spacing: 20) {
        Text(s.namePurpose == "layout" ? "保存排版样式" : "保存调色预设").font(.title2.bold())
        TextField("名称", text: $s.nameEntry).textFieldStyle(.roundedBorder).onSubmit {
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
  @ViewBuilder private var sidebar: some View {
    VStack(spacing: 0) {
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text(s.workspace == .develop ? "胶卷照片" : "排版照片").font(.headline)
          Text(
            s.workspace == .develop
              ? "\(s.photos.count) 张照片" : "\(s.sheetSelection.count) / \(s.sheetPhotos.count) 张已选"
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
          if let folder = s.folder, s.workspace == .develop {
            Button("刷新文件夹") { s.openFolder(folder) }
          }
          if s.workspace == .sheet { Button("打开项目…", action: s.chooseProject) }
        } label: {
          Image(systemName: "plus")
        }.menuStyle(.borderlessButton).fixedSize().disabled(!s.ready || s.busy)
      }.padding(16)
      if s.workspace == .develop {
        TextField("搜索照片", text: $s.search).textFieldStyle(.roundedBorder).padding(.horizontal, 12)
          .padding(.bottom, 8)
        List(selection: Binding(get: { s.selected }, set: { if let p = $0 { s.select(p) } })) {
          ForEach(s.filteredPhotos) { p in
            HStack(spacing: 10) {
              Toggle(
                "选择 \(p.name)",
                isOn: Binding(
                  get: { s.checked.contains(p.path) },
                  set: { if $0 { s.checked.insert(p.path) } else { s.checked.remove(p.path) } })
              ).labelsHidden().toggleStyle(.checkbox)
              LocalThumbnail(path: p.path).frame(width: 48, height: 42).clipShape(
                RoundedRectangle(cornerRadius: 5))
              VStack(alignment: .leading, spacing: 4) {
                Text(p.name).lineLimit(1).truncationMode(.middle)
                HStack(spacing: 5) {
                  Text(URL(fileURLWithPath: p.path).pathExtension.uppercased())
                  if p.edited { Image(systemName: "slider.horizontal.3") }
                }.font(.caption2).foregroundStyle(.secondary)
              }
            }.padding(.vertical, 3).tag(p.path)
              .contextMenu {
                Button("在 Finder 中显示") {
                  NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: p.path)])
                }
                Button("加入批量导出") { s.checked.insert(p.path) }
              }
          }
        }.listStyle(.sidebar)
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
              SheetThumbnail(photo: p).frame(width: 50, height: 44).clipShape(
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
          if s.workspace == .develop {
            s.checked = Set(s.filteredPhotos.map(\.path))
          } else {
            s.selectAllFrames(true)
          }
        }
        Button("清空") {
          if s.workspace == .develop { s.checked = [] } else { s.selectAllFrames(false) }
        }
        Spacer()
        if s.workspace == .sheet {
          Button {
            s.reverseFrames()
          } label: {
            Image(systemName: "arrow.up.arrow.down")
          }.help("反转照片顺序")
        } else {
          Text("已选 \(s.checked.count)").font(.caption).foregroundStyle(.secondary)
        }
      }.buttonStyle(.borderless).controlSize(.small).padding(12)
    }
  }
  @ToolbarContentBuilder private var toolbar: some ToolbarContent {
    ToolbarItem(placement: .principal) {
      Picker("工作区", selection: $s.workspace) {
        ForEach(WorkbenchState.Workspace.allCases, id: \.self) { Text($0.rawValue).tag($0) }
      }.pickerStyle(.segmented).frame(width: 200)
    }
    ToolbarItemGroup(placement: .primaryAction) {
      Button(action: s.undo) { Label("撤销", systemImage: "arrow.uturn.backward") }.disabled(
        !s.canUndo || s.busy)
      Button(action: s.redo) { Label("重做", systemImage: "arrow.uturn.forward") }.disabled(
        !s.canRedo || s.busy)
    }
    ToolbarItemGroup(placement: .primaryAction) {
      if s.workspace == .develop {
        Button(action: s.autoCrop) { Label("自动裁剪与校平", systemImage: "crop.rotate") }.disabled(
          s.preview == nil || s.busy)
        Button {
          s.showNegative.toggle()
        } label: {
          Label(
            "查看底片",
            systemImage: s.showNegative ? "circle.lefthalf.filled" : "circle.righthalf.filled")
        }.disabled(s.preview == nil)
      } else {
        Button {
          s.frameView = false
        } label: {
          Label("整卷预览", systemImage: "rectangle.split.3x3")
        }
        Button(action: s.saveProject) { Label("保存项目", systemImage: "square.and.arrow.down") }
          .disabled(s.sheetSelection.isEmpty || s.busy)
      }
    }
    ToolbarItem(placement: .primaryAction) {
      Button(action: s.exportCurrent) { Label("导出", systemImage: "square.and.arrow.up") }.disabled(
        s.busy || (s.workspace == .develop ? s.preview == nil : s.sheetImage == nil))
    }
    ToolbarItem(placement: .primaryAction) {
      Button {
        s.inspector.toggle()
      } label: {
        Label("检查器", systemImage: "sidebar.right")
      }
    }
  }
  private var statusBar: some View {
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
      Text("本地处理").font(.caption2).foregroundStyle(.tertiary)
    }.padding(.horizontal, 16).frame(height: 32).background(.bar)
  }
}

struct LocalThumbnail: View {
  let path: String
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
    .task(id: path) {
      let cg = await Task.detached(priority: .utility) { () -> CGImage? in
        guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil)
        else { return nil }
        return CGImageSourceCreateThumbnailAtIndex(
          source, 0,
          [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: 160,
            kCGImageSourceCreateThumbnailWithTransform: true,
          ] as CFDictionary)
      }.value
      if !Task.isCancelled, let cg { image = NSImage(cgImage: cg, size: .zero) }
    }
  }
}
struct SheetThumbnail: View {
  @EnvironmentObject var s: WorkbenchState
  let photo: Photo
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
    .task(id: s.sheetJob + String(photo.sheetID)) {
      do {
        let r = try await s.engine.api(
          "/api/sheet/thumb/\(s.sheetJob)/\(photo.sheetID)", method: "GET")
        if !Task.isCancelled { image = s.decodeImage(r["bytes"]) }
      } catch {}
    }
  }
}
