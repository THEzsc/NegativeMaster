import SwiftUI
import AppKit

extension WorkbenchState {
  var transferPhotos: [Photo] { transferScope == "selected" ? visibleCheckedPhotos : filteredPhotos }
  func presentTransfer(_ destination: String) {
    guard !busy, ready else { return }
    NSApp.keyWindow?.makeFirstResponder(nil)
    transferDestination = destination
    transferScope = "all"
    transferTitle = folder?.lastPathComponent ?? "未命名胶卷"
    transferArchiveID = "new"
    showTransfer = true
  }
  func startTransfer() {
    let paths = transferPhotos.map(\.path), target = transferDestination
    guard !paths.isEmpty, !busy else { return }
    NSApp.keyWindow?.makeFirstResponder(nil)
    persistNow(sidecar: true)
    let pendingSave = saveTask
    let currentPath = parameterPath == selected ? selected : nil, currentParams = params
    let title = transferTitle.trimmingCharacters(in: .whitespacesAndNewlines)
    let archiveID = transferArchiveID
    if target == "sheet" {
      showTransfer = false
      busy = true
      Task {
        await pendingSave?.value
        do {
          if let currentPath {
            _ = try await engine.call(.object(["action": .string("save"), "body": .object([
              "path": .string(currentPath), "params": currentParams, "sidecar": .bool(true)
            ])]))
          }
          busy = false
          prepareSheet(paths: paths)
        } catch { busy = false; failure(error) }
      }
      return
    }
    indexingArchive = true; busy = true; stopIndex = false
    indexDone = 0; indexTotal = paths.count; indexName = "准备索引…"
    Task {
      defer { busy = false; indexingArchive = false }
      await pendingSave?.value
      do {
        if let currentPath {
          _ = try await engine.call(.object(["action": .string("save"), "body": .object([
            "path": .string(currentPath), "params": currentParams, "sidecar": .bool(true)
          ])]))
        }
        await archive.load()
        let plan = try await archive.engine.api("/api/archive/index-plan", .object([
          "paths": .array(paths.map(J.string))
        ]))
        let items = plan["items"].array
        indexTotal = items.count
        guard !items.isEmpty else { throw WorkbenchError(message: "没有可索引的照片。") }
        if stopIndex { showTransfer = false; return }
        let id: String
        if archiveID == "new" {
          let created = try await archive.engine.api("/api/archive/rolls", .object([
            "title": .string(title.isEmpty ? "未命名胶卷" : title),
            "format": .string("135"), "status": .string("archived"), "tags": .array([])
          ]))
          id = created["roll"]["id"].string
        } else { id = archiveID }
        transferArchiveID = id
        archive.selected = id
        await archive.refresh()
        var warnings: [String] = []
        for item in items {
          if stopIndex { break }
          indexName = URL(fileURLWithPath: item["path"].string).lastPathComponent
          let result = try await archive.engine.api("/api/archive/rolls/" + id + "/frames", .object([
            "paths": .array([item["source"]]), "mode": .string("index")
          ]))
          archive.detail = result["roll"]
          warnings += result["warnings"].array.map(\.string)
          indexDone += 1
        }
        archive.selected = id
        await archive.refresh()
        showTransfer = false; workspace = .archive
        archive.notice = "已索引 \(indexDone) / \(indexTotal) 张" + (stopIndex ? " · 已停止" : "")
        if !warnings.isEmpty { archive.error = warnings.joined(separator: "\n") }
      } catch { indexName = ""; failure(error) }
    }
  }
}

struct RollTransferSheet: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  @State private var archiveLoaded = false
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      Text(s.transferDestination == "sheet" ? "发送到整卷排版" : "索引到胶卷库").font(.title2.bold())
      if s.indexingArchive {
        ProgressView(value: Double(s.indexDone), total: Double(max(1, s.indexTotal)))
        Text("\(s.indexDone) / \(s.indexTotal) 张 · \(s.indexName)").lineLimit(1).truncationMode(.middle)
        HStack { Spacer(); Button(s.stopIndex ? "正在停止…" : "停止") { s.stopIndex = true }.disabled(s.stopIndex) }
      } else {
      Picker("照片范围", selection: bindings.transferScope) {
        Text("当前列表 · \(s.filteredPhotos.count) 张").tag("all")
        Text("所选照片 · \(s.visibleCheckedPhotos.count) 张").tag("selected")
      }
      if s.transferDestination == "archive" {
        if !archiveLoaded { ProgressView("读取胶卷库…").controlSize(.small) }
        Picker("加入胶卷", selection: bindings.transferArchiveID) {
          Text("新建胶卷").tag("new")
          ForEach(s.archive.rolls.indices, id: \.self) { i in Text(s.archive.rolls[i]["title"].string).tag(s.archive.rolls[i]["id"].string) }
        }
        if s.transferArchiveID == "new" {
          TextField("胶卷名称", text: bindings.transferTitle).textFieldStyle(.roundedBorder)
        }
      }
      HStack {
        Spacer()
        Button("取消") { s.showTransfer = false }.keyboardShortcut(.cancelAction)
        Button(s.transferDestination == "sheet" ? "发送" : "建立索引", action: s.startTransfer)
          .keyboardShortcut(.defaultAction).disabled(s.transferPhotos.isEmpty || s.busy)
      }
      }
    }.interactiveDismissDisabled(s.indexingArchive).padding(24).frame(width: 460)
      .task { if s.transferDestination == "archive" { await s.archive.load(); archiveLoaded = true } }
  }
}
