import SwiftUI

struct ToneLook: Identifiable {
  let id: String
  let name: String
  let values: [String: Double]
  static let all: [ToneLook] = [
    make("neutral", "自然中性", [0,1,0,0,0,0,0]),
    make("soft", "柔和人像", [-0.08,0.92,-18,12,-6,3,3]),
    make("rich", "浓郁反差", [0.18,1.08,-8,-5,5,-10,12]),
    make("open", "通透宽容", [0.02,1,-30,28,-8,-3,6]),
    make("matte", "柔灰印相", [-0.04,0.88,-12,8,-8,20,-5])
  ]
  private static func make(_ id: String, _ name: String, _ v: [Double]) -> ToneLook {
    ToneLook(id: id, name: name, values: Dictionary(uniqueKeysWithValues: zip(["contrast","saturation","highlights","shadows","whites","blacks","vibrance"],v)))
  }
  func applying(to params: J) -> J {
    var result = params
    for (key,value) in values { result[key] = .number(value) }
    return result
  }
}

enum GammaRecommendation {
  static func canApply(_ report: J) -> Bool {
    guard case .number(let gamma) = report["recommendation"], gamma.isFinite,
      report["confidence"].string != "none" else { return false }
    switch report["parameter_key"].string {
    case "gamma": return (0.6...3).contains(gamma)
    case "nd_gamma": return (1...8).contains(gamma)
    default: return false
    }
  }
}

extension WorkbenchState {
  var workflowSettings: J {
    var result = J.object(["P": params, "curFmt": .string("free"), "orient": .string("land")])
    let crop = params["crop_rect"].array
    if crop.count == 4 { result["cropN"] = .object(Dictionary(uniqueKeysWithValues: zip(["x0","y0","x1","y1"],crop))) }
    return result
  }
  var gammaFresh: Bool {
    analysisPath == selected && analysisParams == params
      && (!analysisIsRoll || analysisPaths == workflowPaths)
  }
  var gammaApplicable: Bool { gammaFresh && GammaRecommendation.canApply(gammaAnalysis["report"]) }
  var canLockRoll: Bool { analysisIsRoll && !analysisPaths.isEmpty && gammaApplicable }
  var workflowPaths: [String] {
    let paths = checked.isEmpty ? filteredPhotos.map(\.path) : visibleCheckedPhotos.map(\.path)
    return paths.isEmpty ? selected.map { [$0] } ?? [] : paths
  }
  func applyLook(_ look: ToneLook) {
    guard selected != nil, !busy else { return }
    remember()
    params = look.applying(to: params)
    queueRender(); persistSoon()
    status = "已应用\(look.name)"
  }
  func analyzeGamma(roll: Bool) {
    guard let path = selected, parameterPath == path, !busy else { return }
    analysisTask?.cancel()
    let p = params, settings = workflowSettings, paths = roll ? workflowPaths : [path]
    analyzing = true
    gammaAnalysis = .null
    analysisTask = Task {
      do {
        let r = try await analysisEngine.api("/api/workflow/analyze", .object([
          "paths": .array(paths.map(J.string)), "current_path": .string(path), "current": settings
        ]))
        guard !Task.isCancelled else { return }
        analysisParams = p; analysisPath = path; analysisPaths = paths; analysisIsRoll = roll; gammaAnalysis = r
        analyzing = false
      } catch {
        if !Task.isCancelled { analyzing = false; failure(error) }
      }
    }
  }
  func applyGamma() {
    guard gammaApplicable else { return }
    let report = gammaAnalysis["report"]
    setParam(report["parameter_key"].string, report["recommendation"])
    analysisParams = params
    status = "已应用 Gamma 建议，可继续手动微调"
  }
  func lockRollGamma() {
    guard canLockRoll, !busy, let path = selected, parameterPath == path else { return }
    let report = gammaAnalysis["report"], p = params, settings = workflowSettings, paths = analysisPaths
    busy = true
    // Drain all older writes on the same serial transport before the gamma-only update.
    saveTask?.cancel()
    Task {
      do {
        _ = try await engine.call(.object(["action": .string("save"), "body": .object(["path": .string(path), "params": p, "sidecar": .bool(true)])]))
        let r = try await engine.api("/api/workflow/roll-gamma", .object([
          "paths": .array(paths.map(J.string)), "parameter_key": report["parameter_key"], "gamma": report["recommendation"],
          "current_path": .string(path), "current": settings
        ]))
        let updated = Set(r["updated"].array.map(\.string))
        if selected == path, updated.contains(path) {
          remember(); params[report["parameter_key"].string] = report["recommendation"]
          analysisParams = params; queueRender()
        }
        for i in photos.indices where updated.contains(photos[i].path) { photos[i].edited = true }
        warnings = r["errors"].array.map { $0["path"].string + "：" + $0["error"].string }
        status = "已统一 \(updated.count) 张的 Gamma；保留每张其他调整"
        busy = false
      } catch { busy = false; failure(error) }
    }
  }
}

struct NativeWorkflowControls: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    Section("影调风格") {
      Menu("应用风格") {
        ForEach(ToneLook.all) { look in Button(look.name) { s.applyLook(look) } }
      }
    }
    Section("Gamma 分析") {
      HStack {
        Button("分析这一张") { s.analyzeGamma(roll: false) }
        Button("分析同卷") { s.analyzeGamma(roll: true) }
      }.disabled(s.analyzing)
      if s.analyzing { ProgressView("正在分析明暗分布…").controlSize(.small) }
      if s.gammaAnalysis != .null {
        let report = s.gammaAnalysis["report"]
        if case .number(let value) = report["recommendation"] {
          LabeledContent(report["parameter_key"].string == "nd_gamma" ? "建议纸张反差" : "建议 Gamma", value: String(format: "%.3f", value))
        } else { Text("当前画面没有可靠的 Gamma 建议") }
        let confidence = ["high":"高", "medium":"中", "low":"低", "none":"不足"][report["confidence"].string] ?? "不足"
        Text("可信度：\(confidence) · 抽样 \(Int(s.gammaAnalysis["sampled"].double)) / \(Int(s.gammaAnalysis["total"].double)) 张").font(.caption).foregroundStyle(.secondary)
        ForEach(Array(report["warnings"].array.enumerated()), id: \.offset) { _, warning in Text(warning.string).font(.caption).foregroundStyle(.secondary) }
        if !s.gammaFresh { Text("当前照片、参数或所选照片已改变，请重新分析。").font(.caption).foregroundStyle(.orange) }
        HStack {
          Button("应用到这张", action: s.applyGamma)
          if s.analysisIsRoll {
            Button("锁定到已分析的 \(s.analysisPaths.count) 张", action: s.lockRollGamma).disabled(!s.canLockRoll)
          }
        }.disabled(!s.gammaApplicable)
        if !s.gammaAnalysis["errors"].array.isEmpty {
          DisclosureGroup("\(s.gammaAnalysis["errors"].array.count) 张未参与分析") {
            ForEach(Array(s.gammaAnalysis["errors"].array.enumerated()), id: \.offset) { _, item in Text(item["path"].string + "：" + item["error"].string).font(.caption) }
          }
        }
      }
    }
  }
}
