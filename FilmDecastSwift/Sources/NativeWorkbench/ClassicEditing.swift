import SwiftUI

extension WorkbenchState {
  func editTitle(_ key: String) -> String {
    let field = key.hasPrefix("p.") ? String(key.dropFirst(2)) : key
    return syncGroups.flatMap { $0["fields"].array }.first { $0["id"].string == field }?["title"].string ?? "调整照片"
  }
  var historyTitles: [String] { let _ = historyRevision; return undoStack.suffix(30).reversed().map { $0["label"].string.isEmpty ? "调整照片" : $0["label"].string } }
  func stageAutoSync(_ key: String) {
    if pendingAutoBefore == nil {
      pendingAutoBefore = params; pendingAutoPath = selected; pendingAutoTargets = syncTargets
      saveTask?.cancel()
    }
    if key == "hsl" {
      pendingAutoFields.formUnion(syncGroups.first { $0["id"].string == "hsl" }?["fields"].array.map { $0["id"].string } ?? [])
    } else { pendingAutoFields.insert(key) }
  }
  func scheduleAutoSync() {
    autoSyncTask?.cancel()
    autoSyncTask = Task {
      try? await Task.sleep(for: .milliseconds(450))
      guard !Task.isCancelled else { return }
      if adjustmentGesture { scheduleAutoSync(); return }
      commitAutoSync()
    }
  }
  func commitAutoSync(completion: (@MainActor () -> Void)? = nil) {
    guard let before = pendingAutoBefore, let path = pendingAutoPath else { completion?(); return }
    autoSyncTask?.cancel(); autoSyncTask = nil
    let source = params, fields = pendingAutoFields.sorted(), targets = [path] + pendingAutoTargets
    pendingAutoBefore = nil; pendingAutoFields = []; pendingAutoPath = nil; pendingAutoTargets = []
    performClassicSync(source: source, fields: fields, targets: targets, baseline: (path,before), title: "自动同步 · \(targets.count) 张", completion: completion)
  }
  func performClassicSync(source: J, fields: [String], targets: [String], baseline: (String,J)? = nil, operation: J = .null, title: String = "同步调整", completion: (@MainActor () -> Void)? = nil) {
    guard !editingBatch, !targets.isEmpty, (!fields.isEmpty || operation != .null) else { completion?(); return }
    saveTask?.cancel(); applyingSync = true; busy = true; syncStop = false
    let activePath = selected, activeParams = params
    syncTask = Task {
      var receipts: [J] = [], issues: [String] = []
      defer { applyingSync = false; busy = false; historyFlags(); completion?() }
      do {
        if let baseline {
          _ = try await engine.call(.object(["action": .string("save"),"body": .object(["path": .string(baseline.0),"params": baseline.1,"sidecar": .bool(true)])]))
        } else if let activePath, parameterPath == activePath {
          _ = try await engine.call(.object(["action": .string("save"),"body": .object(["path": .string(activePath),"params": activeParams,"sidecar": .bool(true)])]))
        }
        for (index,path) in targets.enumerated() {
          if syncStop { break }
          do {
            let snap = try await engine.call(.object(["action": .string("batch_snapshot"),"body": .object(["path": .string(path)])]))
            var body = J.object(["path": .string(path),"token": snap["token"],"source": source,"fields": .array(fields.map(J.string))])
            if operation != .null { body["operation"] = operation }
            let result = try await engine.call(.object(["action": .string("sync_apply"),"body": body]))
            receipts.append(.string(result["undo_id"].string))
            if path == selected { params = result["params"] }
            if let i = photos.firstIndex(where: { $0.path == path }) { photos[i].edited = true }
          } catch { issues.append(URL(fileURLWithPath:path).lastPathComponent + "：" + error.localizedDescription) }
          progress = Double(index + 1) / Double(targets.count)
          status = "\(title) · \(index + 1)/\(targets.count)"
        }
        if !receipts.isEmpty { undoStack.append(.object(["batch": .array(receipts),"label": .string(title)])); redoStack = [] }
        if let activePath, parameterPath == activePath {
          let refreshed = try await engine.call(.object(["action": .string("adjustments"),"body": .object(["path": .string(activePath)])]))
          params = refreshed["params"]
        }
        status = "已完成 \(receipts.count)/\(targets.count) 张"
        if !issues.isEmpty { error = issues.joined(separator:"\n") }
        queueRender()
      } catch { failure(error) }
    }
  }
  func restoreBatchHistory(redo: Bool) {
    guard !editingBatch else { return }
    guard let entry = redo ? redoStack.last : undoStack.last else { return }
    persistNow(); let pendingSave = saveTask
    applyingSync = true; busy = true
    syncTask = Task {
      await pendingSave?.value
      var inverses: [J] = [], remaining: [J] = [], issues: [String] = []
      for receipt in entry["batch"].array.reversed() {
        do {
          let result = try await engine.call(.object(["action": .string("batch_restore"),"body": .object(["undo_id": receipt])]))
          inverses.append(result["undo_id"])
          if result["path"].string == selected { params = result["params"] }
        } catch { remaining.append(receipt); issues.append(error.localizedDescription) }
      }
      if redo { _ = redoStack.popLast() } else { _ = undoStack.popLast() }
      var inverse = entry; inverse["batch"] = .array(inverses)
      if !inverses.isEmpty { if redo { undoStack.append(inverse) } else { redoStack.append(inverse) } }
      if !remaining.isEmpty {
        var failed = entry; failed["batch"] = .array(remaining.reversed())
        if redo { redoStack.append(failed) } else { undoStack.append(failed) }
        error = issues.joined(separator:"\n")
      }
      applyingSync = false; busy = false; historyFlags(); queueRender()
      status = "\(redo ? "已重做" : "已撤销") · \(inverses.count) 张"
    }
  }
  func replaceDevelop(_ next: J, title: String = "调整照片") {
    if (autoSync && !syncTargets.isEmpty) || pendingAutoBefore != nil {
      for (key, value) in next.object where params[key] != value { setParam(key, value) }
    } else { remember(title); params = next; queueRender(); persistSoon() }
  }
  func syncOrientation(_ operation: J) -> Bool {
    guard autoSync && !syncTargets.isEmpty, let path = selected else { return false }
    if pendingAutoBefore != nil { commitAutoSync { _ = self.syncOrientation(operation) }; return true }
    performClassicSync(source: params, fields: [], targets: [path]+syncTargets, operation: operation, title: "同步方向")
    return true
  }
  func pasteClassicAdjustments() {
    guard copiedAdjustments != .null, let path = selected else { return }
    performClassicSync(source: copiedAdjustments, fields: copiedFields, targets: autoSync ? [path]+syncTargets : [path], title: "粘贴调整")
  }
}
