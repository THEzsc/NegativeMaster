import AppKit
import SwiftUI

struct RollSuggestion: Identifiable {
  var id: String { path }
  let path: String
  var name: String { URL(fileURLWithPath: path).lastPathComponent }
  var before: J = .null
  var token: J = .null
  var patch: J = .null
  var report: J = .null
  var included = false
  var note = ""
  var undoID: String?
  var applied = false
  var eligible: Bool { patch != .null }
  var summary: String {
    if patch["crop_rect"] != .null {
      let r = patch["crop_rect"].array.map(\.double)
      return String(format: "画面 %.0f%% × %.0f%% · 校平 %+.2f°", (r[2]-r[0])*100, (r[3]-r[1])*100, patch["level_angle"].double)
    }
    let key = report["parameter_key"].string
    guard patch[key] != .null else { return note }
    return String(format: "%@ %.3f → %.3f", key == "nd_gamma" ? "纸张反差" : "Gamma", before[key].double, patch[key].double)
  }
  static func analyzed(path: String, snapshot: J, result: J, kind: String) -> RollSuggestion {
    var row = RollSuggestion(path: path, before: snapshot["params"], token: snapshot["token"])
    if kind == "crop" {
      let rect = result["rect"].array.map(\.double)
      guard result["status"].string != "uncertain", rect.count == 4,
        rect.allSatisfy({ $0.isFinite && (0...1).contains($0) }), rect[2] > rect[0], rect[3] > rect[1],
        case .number(let angle) = result["angle"], angle.isFinite, (-15...15).contains(angle) else {
        row.note = "未找到可靠片框，保留原裁剪"; return row
      }
      row.patch = .object(["crop_rect": result["rect"], "level_angle": result["angle"], "geometry_source": .string("auto")])
      row.included = true
    } else {
      row.report = result["report"]
      guard GammaRecommendation.canApply(row.report) else {
        row.note = row.report["warnings"].array.last?.string ?? "没有可靠建议"; return row
      }
      row.patch = .object([row.report["parameter_key"].string: row.report["recommendation"]])
      row.included = ["medium", "high"].contains(row.report["confidence"].string)
      row.note = row.included ? "" : "低可信度 · 默认不应用"
    }
    return row
  }
}

extension WorkbenchState {
  var automationPhotos: [Photo] { automationScope == "selected" ? visibleCheckedPhotos : filteredPhotos }
  var automationTitle: String { automationKind == "crop" ? "整卷自动裁剪与校平" : "整卷逐张 Gamma 分析" }
  var automationChosen: Int { automationRows.filter { $0.included && $0.eligible && !$0.applied }.count }
  var automationUndoCount: Int { automationRows.filter { $0.applied && $0.undoID != nil }.count }

  func presentRollAutomation(_ kind: String) {
    guard ready, !busy, !analyzing, workspace == .develop else { return }
    NSApp?.keyWindow?.makeFirstResponder(nil)
    automationKind = kind; automationScope = "visible"; automationPhase = "configure"
    automationRows = []; automationError = nil; automationStopped = false
    showRollAutomation = true
  }
  func startRollAutomation() {
    guard !busy, !automationPhotos.isEmpty else { return }
    NSApp?.keyWindow?.makeFirstResponder(nil)
    let paths = automationPhotos.map(\.path)
    let active = parameterPath == selected ? selected : nil, p = params
    saveTask?.cancel()
    busy = true; automationRunning = true; automationStop = false
    automationPhase = "analyzing"; automationError = nil
    Task {
      do {
        // Same serial transport drains old writes before freezing each frame's parameters.
        if let active {
          _ = try await engine.call(.object(["action": .string("save"), "body": .object([
            "path": .string(active), "params": p, "sidecar": .bool(true)
          ])]))
        }
        await runRollAnalysis(paths: paths) { try await self.analysisEngine.call($0) }
        if automationKind == "crop", !automationStopped, automationChosen > 0 {
          await applyRollAutomation(undo: false) { try await self.engine.call($0) }
        }
      } catch { automationError = error.localizedDescription; automationPhase = "configure" }
      busy = false; automationRunning = false
    }
  }
  func runRollAnalysis(paths: [String], request: (J) async throws -> J) async {
    let kind = automationKind, useReference = useRollReference
    automationRows = []; automationDone = 0; automationTotal = paths.count
    for path in paths {
      if automationStop { break }
      automationName = URL(fileURLWithPath: path).lastPathComponent
      do {
        let snapshot = try await request(.object(["action": .string("batch_snapshot"), "body": .object(["path": .string(path)])]))
        if automationStop { break }
        var body = snapshot["params"]
        let action: String
        if kind == "crop" {
          action = "autocrop"; body["path"] = .string(path)
          body["level"] = .bool(true); body["use_reference"] = .bool(useReference)
        } else {
          action = "analyze_gamma"; body = .object(["path": .string(path), "params": body])
        }
        let result = try await request(.object(["action": .string(action), "body": body]))
        automationRows.append(.analyzed(path: path, snapshot: snapshot, result: result, kind: kind))
      } catch { automationRows.append(RollSuggestion(path: path, note: error.localizedDescription)) }
      automationDone += 1
    }
    automationStopped = automationStop && automationDone < automationTotal
    automationPhase = "review"
  }
  func commitRollAutomation(undo: Bool = false) {
    guard !busy else { return }
    busy = true; automationRunning = true; automationStop = false
    Task {
      await applyRollAutomation(undo: undo) { try await self.engine.call($0) }
      busy = false; automationRunning = false
    }
  }
  func applyRollAutomation(undo: Bool, request: (J) async throws -> J) async {
    automationPhase = undo ? "undoing" : "applying"
    let indices = automationRows.indices.filter { i in
      undo ? (automationRows[i].applied && automationRows[i].undoID != nil) :
        (automationRows[i].included && automationRows[i].eligible && !automationRows[i].applied)
    }
    automationDone = 0; automationTotal = indices.count
    for i in indices {
      if automationStop { break }
      let row = automationRows[i]
      automationName = row.name
      do {
        let body: J = undo ? .object(["undo_id": .string(row.undoID!)]) :
          .object(["path": .string(row.path), "token": row.token, "patch": row.patch])
        let r = try await request(.object(["action": .string(undo ? "batch_restore" : "batch_apply"), "body": body]))
        automationRows[i].applied = !undo
        automationRows[i].included = false
        automationRows[i].undoID = undo ? nil : r["undo_id"].string
        automationRows[i].note = undo ? "已撤销" : "已应用"
        if !r["warnings"].array.isEmpty { automationRows[i].note += " · " + r["warnings"].array.map(\.string).joined(separator: "；") }
        if row.path == selected {
          remember(); params = r["params"]; queueRender()
        }
        if let n = photos.firstIndex(where: { $0.path == row.path }) { photos[n].edited = true }
      } catch { automationRows[i].note = error.localizedDescription; automationRows[i].included = false }
      automationDone += 1
    }
    automationStopped = automationStop && automationDone < automationTotal
    automationPhase = "finished"
    status = "本次批量处理已应用 \(automationUndoCount) 张" + (automationStopped ? " · 已停止" : "")
    gammaAnalysis = .null
  }
}

struct RollAutomationSheet: View {
  @Environment(WorkbenchState.self) private var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text(s.automationTitle).font(.title2.bold())
      if s.automationPhase == "configure" {
        Picker("处理范围", selection: bindings.automationScope) {
          Text("当前列表 · \(s.filteredPhotos.count) 张").tag("visible")
          Text("所选照片 · \(s.visibleCheckedPhotos.count) 张").tag("selected")
        }
        if s.automationKind == "crop" {
          Toggle("参考同卷已调照片", isOn: bindings.useRollReference)
          Text("无法识别片框的照片将跳过").foregroundStyle(.secondary)
        }
      } else {
        if s.automationRunning {
          ProgressView(value: Double(s.automationDone), total: Double(max(1, s.automationTotal)))
          Text("\(s.automationPhase == "analyzing" ? "分析" : s.automationPhase == "undoing" ? "撤销" : "保存") \(s.automationDone) / \(s.automationTotal) · \(s.automationName)")
            .lineLimit(1).truncationMode(.middle)
        } else {
          Text(s.automationPhase == "review" ? "已分析 \(s.automationRows.count) 张 · 可应用 \(s.automationChosen) 张" : "已应用 \(s.automationUndoCount) 张")
            .font(.headline)
          if s.automationStopped { Text("已停止").foregroundStyle(.secondary) }
        }
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 12) {
            ForEach(s.automationRows.indices, id: \.self) { i in
              let row = s.automationRows[i]
              HStack(alignment: .top, spacing: 12) {
                Toggle(isOn: Binding(get: { s.automationRows[i].included }, set: { s.automationRows[i].included = $0 })) {
                  VStack(alignment: .leading, spacing: 4) {
                    Text(row.name).lineLimit(1).truncationMode(.middle)
                    if row.eligible { Text(row.summary).font(.callout).monospacedDigit().foregroundStyle(.secondary) }
                    if !row.note.isEmpty { Text(row.note).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
                  }
                }.toggleStyle(.checkbox).disabled(s.automationRunning || !row.eligible || row.applied || s.automationPhase == "finished")
                Spacer(minLength: 0)
                if row.applied { Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).accessibilityLabel("已应用") }
              }
              Divider()
            }
          }
        }.frame(height: 300)
      }
      if let error = s.automationError { Text(error).foregroundStyle(.red).textSelection(.enabled) }
      HStack {
        if !s.automationRunning, s.automationUndoCount > 0 {
          Button("撤销本次批量处理") { s.commitRollAutomation(undo: true) }
        }
        Spacer()
        if s.automationRunning {
          Button(s.automationStop ? "正在停止…" : "停止") { s.automationStop = true }.disabled(s.automationStop)
        } else {
          Button(s.automationPhase == "configure" ? "取消" : "完成") { s.showRollAutomation = false }.keyboardShortcut(.cancelAction)
          if s.automationPhase == "configure" {
            Button("\(s.automationKind == "crop" ? "裁剪" : "分析") \(s.automationPhotos.count) 张", action: s.startRollAutomation)
              .keyboardShortcut(.defaultAction).disabled(s.automationPhotos.isEmpty)
          } else if s.automationPhase == "review" {
            Button("应用所选 \(s.automationChosen) 张") { s.commitRollAutomation() }
              .keyboardShortcut(.defaultAction).disabled(s.automationChosen == 0)
          }
        }
      }
    }.padding(24).frame(width: 580).interactiveDismissDisabled(s.automationRunning)
  }
}
