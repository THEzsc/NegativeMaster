import AppKit
import SwiftUI

struct BatchExportSettings {
  let format: String
  let bits: Int
  let quality: Double
  let resize: Double

  func message(path: String, params: J, output: URL) -> J {
    .object(["action": .string("export"), "body": .object([
      "path": .string(path), "params": params, "out": .string(output.path),
      "bits": .number(format == "tif" ? Double(bits) : 8),
      "quality": .number(quality), "resize": .number(resize), "overwrite": .bool(false),
    ])])
  }
}

struct BatchExportPlan {
  let paths: [String]
  let destination: URL
  let settings: BatchExportSettings
  let currentPath: String?
  let currentParams: J

  static func availableURL(in directory: URL, stem: String, ext: String) -> URL {
    var url = directory.appendingPathComponent(stem).appendingPathExtension(ext)
    var suffix = 1
    while FileManager.default.fileExists(atPath: url.path) {
      url = directory.appendingPathComponent(stem + "-\(suffix)").appendingPathExtension(ext)
      suffix += 1
    }
    return url
  }
}

extension WorkbenchState {
  var visibleCheckedPhotos: [Photo] { filteredPhotos.filter { checked.contains($0.path) } }
  var batchExportPhotos: [Photo] { batchScope == "selected" ? visibleCheckedPhotos : filteredPhotos }

  func presentRollExport(selectedOnly: Bool = false) {
    guard ready, !busy, workspace == .develop else { return }
    NSApp.keyWindow?.makeFirstResponder(nil)
    batchScope = selectedOnly ? "selected" : "visible"
    batchDestination = (folder ?? FileManager.default.urls(for: .picturesDirectory, in: .userDomainMask)[0])
      .appendingPathComponent("导出成片").path
    batchFinished = false
    batchCompleted = 0
    batchTotal = 0
    batchFailures = []
    batchOutputs = []
    batchError = nil
    batchCancelled = false
    showRollExport = true
  }

  func chooseBatchDestination() {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.canCreateDirectories = true
    panel.prompt = "选择导出文件夹"
    panel.directoryURL = URL(fileURLWithPath: batchDestination)
    if panel.runModal() == .OK, let url = panel.url { batchDestination = url.path }
  }

  func startBatchExport() {
    guard !busy, !batchExportPhotos.isEmpty else { return }
    NSApp.keyWindow?.makeFirstResponder(nil)
    let path = batchDestination.trimmingCharacters(in: .whitespacesAndNewlines)
    guard path.hasPrefix("/") else { batchError = "请输入以 / 开头的完整文件夹路径，或点“选择…” 。"; return }
    let plan = BatchExportPlan(
      paths: batchExportPhotos.map(\.path), destination: URL(fileURLWithPath: path),
      settings: BatchExportSettings(format: exportFormat, bits: exportBits, quality: exportQuality, resize: exportResize),
      currentPath: parameterPath == selected ? selected : nil, currentParams: params)
    busy = true
    batchRunning = true
    cancelBatch = false
    Task { await performBatchExport(plan) { try await self.engine.call($0) } }
  }

  /// The queue owns an immutable input/options snapshot. A bad frame does not abort the roll.
  func performBatchExport(_ plan: BatchExportPlan, request: (J) async throws -> J) async {
    busy = true
    batchRunning = true
    batchFinished = false
    batchTotal = plan.paths.count
    batchCompleted = 0
    batchFailures = []
    batchOutputs = []
    batchError = nil
    batchCancelled = false
    progress = 0
    defer { busy = false; batchRunning = false }
    do {
      try FileManager.default.createDirectory(at: plan.destination, withIntermediateDirectories: true)
    } catch {
      batchError = "无法创建导出文件夹：\(error.localizedDescription)"
      return
    }
    var report = ["NegativeMaster 整卷导出", "格式：\(plan.settings.format.uppercased()) · 长边：\(Int(plan.settings.resize))（0 为原尺寸）", ""]
    for (i, path) in plan.paths.enumerated() {
      if cancelBatch { break }
      batchCurrentName = URL(fileURLWithPath: path).lastPathComponent
      status = "导出 \(i + 1) / \(batchTotal) · \(batchCurrentName)"
      do {
        let settings: J
        if path == plan.currentPath { settings = plan.currentParams }
        else {
          settings = try await request(.object(["action": .string("adjustments"), "body": .object(["path": .string(path)])]))["params"]
        }
        // Cancellation can arrive while loading another frame's saved adjustments.
        if cancelBatch { break }
        let stem = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent + "_pos"
        let output = BatchExportPlan.availableURL(in: plan.destination, stem: stem, ext: plan.settings.format)
        _ = try await request(plan.settings.message(path: path, params: settings, output: output))
        batchCompleted += 1
        batchOutputs.append(output)
        report.append("成功：\(batchCurrentName) → \(output.lastPathComponent)")
      } catch {
        let message = "\(batchCurrentName)：\(error.localizedDescription)"
        batchFailures.append(message)
        report.append("失败：" + message)
      }
      progress = Double(i + 1) / Double(max(1, batchTotal))
    }
    batchCancelled = cancelBatch && batchCompleted + batchFailures.count < batchTotal
    batchFinished = true
    let remaining = batchTotal - batchCompleted - batchFailures.count
    status = "已导出 \(batchCompleted) / \(batchTotal) 张"
      + (batchFailures.isEmpty ? "" : "，失败 \(batchFailures.count) 张")
      + (batchCancelled ? "，已停止后续 \(remaining) 张" : "")
    report.append("\n" + status)
    do {
      let url = BatchExportPlan.availableURL(in: plan.destination, stem: "导出记录", ext: "txt")
      try report.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
    } catch { batchError = "照片处理已结束，但导出记录未能保存：\(error.localizedDescription)" }
    lastExport = plan.destination
  }
}

struct RollExportSheet: View {
  @Environment(WorkbenchState.self) private var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text(s.batchFinished ? (s.batchCancelled ? "导出已停止" : "整卷导出结果") : "整卷导出")
        .font(.title2.bold())
      if s.batchRunning || s.batchFinished {
        if s.batchRunning {
          ProgressView(value: s.progress)
          Text(s.status).lineLimit(2)
          Text("停止后将完成当前照片").font(.callout).foregroundStyle(.secondary)
        } else {
          Label("成功 \(s.batchCompleted) / \(s.batchTotal) 张", systemImage: s.batchFailures.isEmpty ? "checkmark.circle" : "exclamationmark.triangle")
            .font(.headline)
          if s.batchCancelled { Text("未处理 \(s.batchTotal - s.batchCompleted - s.batchFailures.count) 张，可重新选择后导出。") }
          if !s.batchFailures.isEmpty {
            Text("以下 \(s.batchFailures.count) 张未导出，其余照片已保留：")
            ScrollView { Text(s.batchFailures.joined(separator: "\n")).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled) }
              .frame(maxHeight: 140)
          }
        }
        Text(s.batchDestination).font(.callout).foregroundStyle(.secondary).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
      } else {
        Form {
          Picker("导出范围", selection: bindings.batchScope) {
            Text("当前列表 · \(s.filteredPhotos.count) 张").tag("visible")
            Text("列表中已勾选 · \(s.visibleCheckedPhotos.count) 张").tag("selected")
          }.help("范围跟随照片列表的筛选；同名 RAW 和 JPEG 分别导出")
          Picker("格式", selection: bindings.exportFormat) {
            Text("TIFF").tag("tif"); Text("JPEG").tag("jpg"); Text("PNG").tag("png")
          }
          if s.exportFormat == "tif" {
            Picker("位深", selection: bindings.exportBits) { Text("16 位").tag(16); Text("8 位").tag(8) }
          }
          if s.exportFormat == "jpg" {
            NumericControl(title: "JPEG 质量", value: bindings.exportQuality, range: 1...100, step: 1)
          }
          NumericControl(title: "长边像素 · 0 为原尺寸", value: bindings.exportResize, range: 0...12000, step: 100)
          LabeledContent("导出到") {
            HStack {
              TextField("完整文件夹路径", text: bindings.batchDestination).textFieldStyle(.roundedBorder)
                .labelsHidden().accessibilityLabel("导出文件夹").help(s.batchDestination)
              Button("选择…", action: s.chooseBatchDestination)
            }
          }
        }.formStyle(.grouped).frame(height: 340)
        Text("同名文件自动编号，不覆盖已有文件。")
          .font(.callout).foregroundStyle(.secondary)
      }
      if let error = s.batchError { Text(error).foregroundStyle(.red).font(.callout).textSelection(.enabled) }
      HStack {
        if s.batchFinished { Button("打开导出文件夹", action: s.revealExport) }
        Spacer()
        if s.batchRunning {
          Button(s.cancelBatch ? "正在停止…" : "停止后续导出", action: s.cancelOperation).disabled(s.cancelBatch)
        } else if s.batchFinished {
          Button("完成") { s.showRollExport = false }.keyboardShortcut(.defaultAction)
        } else {
          Button("取消") { s.showRollExport = false }.keyboardShortcut(.cancelAction)
          Button("开始导出 \(s.batchExportPhotos.count) 张", action: s.startBatchExport)
            .keyboardShortcut(.defaultAction).disabled(s.batchExportPhotos.isEmpty)
        }
      }
    }.padding(24).frame(width: 560)
      .interactiveDismissDisabled(s.batchRunning)
  }
}
