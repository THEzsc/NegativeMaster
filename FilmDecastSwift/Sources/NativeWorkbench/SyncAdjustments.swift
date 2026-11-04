import SwiftUI

extension WorkbenchState {
  var syncTargets: [String] {
    (syncScope == "selected" ? visibleCheckedPhotos : photos).map(\.path).filter { $0 != selected }
  }

  func synchronizeAdjustments(undo: Bool = false) {
    guard !busy, !analyzing, let sourcePath = selected, parameterPath == sourcePath else { return }
    let targets = undo ? syncUndo.keys.sorted() : syncTargets
    guard !targets.isEmpty, undo || !syncSelected.isEmpty else { return }
    let source = params, groups = syncSelected.sorted(), receipts = syncUndo
    saveTask?.cancel()
    busy = true; applyingSync = true; progress = 0
    status = undo ? "正在撤销同步…" : "正在同步调整…"
    syncTask = Task {
      defer { busy = false; applyingSync = false }
      do {
        _ = try await engine.call(.object(["action": .string("save"), "body": .object([
          "path": .string(sourcePath), "params": source, "sidecar": .bool(true)
        ])]))
        if !undo { syncUndo = [:] }
        var count = 0, issues: [String] = []
        for (index, path) in targets.enumerated() {
          do {
            let result: J
            if undo {
              result = try await engine.call(.object(["action": .string("batch_restore"), "body": .object([
                "undo_id": .string(receipts[path]!)
              ])]))
              syncUndo.removeValue(forKey: path)
            } else {
              let snapshot = try await engine.call(.object(["action": .string("batch_snapshot"), "body": .object(["path": .string(path)])]))
              result = try await engine.call(.object(["action": .string("sync_apply"), "body": .object([
                "path": .string(path), "token": snapshot["token"], "source": source,
                "groups": .array(groups.map(J.string))
              ])]))
              syncUndo[path] = result["undo_id"].string
            }
            if selected == path, parameterPath == path {
              remember(); params = result["params"]; selectedPreset = ""; gammaAnalysis = .null; queueRender()
            }
            if let i = photos.firstIndex(where: { $0.path == path }) { photos[i].edited = true }
            issues += result["warnings"].array.map { URL(fileURLWithPath: path).lastPathComponent + "：" + $0.string }
            count += 1
          } catch { issues.append(URL(fileURLWithPath: path).lastPathComponent + "：" + error.localizedDescription) }
          progress = Double(index + 1) / Double(targets.count)
        }
        status = "\(undo ? "已撤销同步" : "已同步") \(count) / \(targets.count) 张照片"
        if !issues.isEmpty { error = issues.joined(separator: "\n") }
      } catch { failure(error) }
    }
  }
}

struct SyncAdjustmentsControls: View {
  @Environment(WorkbenchState.self) private var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    Picker("同步到", selection: bindings.syncScope) {
      Text("已选照片").tag("selected")
      Text("当前整卷").tag("roll")
    }.pickerStyle(.segmented)
    LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], alignment: .leading, spacing: 10) {
      ForEach(s.syncGroups) { group in
        let id = group["id"].string
        Toggle(group["title"].string, isOn: Binding(
          get: { s.syncSelected.contains(id) },
          set: { if $0 { s.syncSelected.insert(id) } else { s.syncSelected.remove(id) } }
        )).toggleStyle(.checkbox)
      }
    }
    HStack {
      Button("全选") { s.syncSelected = Set(s.syncGroups.map { $0["id"].string }) }
      Button("清空") { s.syncSelected = [] }
      Spacer()
      Button("同步到 \(s.syncTargets.count) 张") { s.synchronizeAdjustments() }
        .buttonStyle(.borderedProminent)
        .disabled(s.syncSelected.isEmpty || s.syncTargets.isEmpty || s.analyzing)
    }
    if !s.syncUndo.isEmpty {
      Button("撤销上次同步") { s.synchronizeAdjustments(undo: true) }.disabled(s.analyzing)
    }
  }
}
