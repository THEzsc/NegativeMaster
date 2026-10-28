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
    showTransfer = false
    if target == "sheet" {
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
    let root = folder ?? FileManager.default.urls(for: .picturesDirectory, in: .userDomainMask)[0]
    let destination = root.appendingPathComponent("胶卷库成片/" + ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-") + "-" + UUID().uuidString.prefix(6))
    let plan = BatchExportPlan(paths: paths, destination: destination,
      settings: BatchExportSettings(format: "jpg", bits: 8, quality: 92, resize: 0),
      currentPath: parameterPath == selected ? selected : nil, currentParams: params)
    batchDestination = destination.path
    batchFinished = false; batchRunning = true; busy = true; cancelBatch = false
    showRollExport = true
    Task {
      await pendingSave?.value
      await performBatchExport(plan) { try await self.engine.call($0) }
      guard batchFinished, !batchCancelled, batchFailures.isEmpty, batchCompleted == paths.count else { return }
      busy = true
      defer { busy = false }
      do {
        await archive.load()
        let id: String
        if archiveID == "new" {
          let created = try await archive.engine.api("/api/archive/rolls", .object([
            "title": .string(title.isEmpty ? "未命名胶卷" : title),
            "format": .string("135"), "status": .string("archived"), "tags": .array([])
          ]))
          id = created["roll"]["id"].string
        } else { id = archiveID }
        let result = try await archive.engine.api("/api/archive/rolls/" + id + "/frames", .object([
          "directory": .string(destination.path), "mode": .string("positive")
        ]))
        archive.detail = result["roll"]; archive.selected = id
        await archive.refresh()
        showRollExport = false; workspace = .archive
        archive.notice = "已加入 \(paths.count) 张成片"
      } catch { batchError = "成片已保存在导出文件夹，加入胶卷库失败：" + error.localizedDescription }
    }
  }
}

struct RollTransferSheet: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  @State private var archiveLoaded = false
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      Text(s.transferDestination == "sheet" ? "发送到整卷排版" : "导出到胶卷库").font(.title2.bold())
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
        Text("JPEG · 原尺寸 · 质量 92").font(.callout).foregroundStyle(.secondary)
      } else {
        Text("优先使用已导出成片，其余读取保存的调整。").font(.callout).foregroundStyle(.secondary)
      }
      HStack {
        Spacer()
        Button("取消") { s.showTransfer = false }.keyboardShortcut(.cancelAction)
        Button(s.transferDestination == "sheet" ? "发送" : "导出并加入", action: s.startTransfer)
          .keyboardShortcut(.defaultAction).disabled(s.transferPhotos.isEmpty || s.busy)
      }
    }.padding(24).frame(width: 460)
      .task { if s.transferDestination == "archive" { await s.archive.load(); archiveLoaded = true } }
  }
}
