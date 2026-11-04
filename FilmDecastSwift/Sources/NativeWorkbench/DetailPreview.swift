import AppKit

enum PreviewResolution {
  static func side(displayed: CGSize, crop: CGRect, backingScale: Double, source: CGSize) -> Int {
    guard source.width > 0, source.height > 0 else { return 1500 }
    let needed = max(displayed.width / max(0.0001, crop.width),
                     displayed.height / max(0.0001, crop.height)) * backingScale
    guard needed.isFinite else { return 1500 }
    if needed <= 1500 { return min(1500, Int(max(source.width, source.height))) }
    // Small buckets avoid decoding again for each pixel of a window resize or pinch.
    return min(Int(max(source.width, source.height)), max(1500, Int(ceil(needed / 512)) * 512))
  }

  static func percent(displayed: CGSize, crop: CGRect, backingScale: Double, source: CGSize) -> Int {
    guard source.width > 0 else { return 100 }
    return max(1, Int((displayed.width * backingScale / max(1, source.width * crop.width) * 100).rounded()))
  }
}

extension WorkbenchState {
  var displaySourceSize: CGSize {
    let sideways = Int(params["rotate"].double) % 180 != 0
    return sideways ? CGSize(width: imageSize.height, height: imageSize.width) : imageSize
  }

  func invalidateDetail(resetDemand: Bool = false) {
    detailGeneration += 1
    detailTask?.cancel(); detailTask = nil
    detailImage = nil; detailLoadedSide = 0
    if resetDemand { detailSide = 1500 }
  }

  func requestDetail(side: Int) {
    guard workspace == .develop, side != detailSide else { return }
    detailGeneration += 1
    detailTask?.cancel(); detailTask = nil
    detailSide = side
    if side <= 1500 || side < detailLoadedSide {
      detailImage = nil; detailLoadedSide = 0
    }
    queueDetail()
  }

  func queueDetail() {
    guard ready, workspace == .develop, !busy, !editingBatch, !rendering,
          detailSide > 1500, let path = selected, parameterPath == path else { return }
    if detailImage != nil, detailLoadedSide >= detailSide { return }
    detailTask?.cancel()
    detailGeneration += 1
    let generation = detailGeneration, side = detailSide, p = params, negative = showNegative
    detailTask = Task {
      do {
        try await Task.sleep(for: .milliseconds(350))
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("NegativeMaster-detail", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appendingPathComponent(UUID().uuidString + ".jpg")
        defer { try? FileManager.default.removeItem(at: file) }
        _ = try await detailEngine.call(.object(["action": .string("detail"), "body": .object([
          "path": .string(path), "params": p, "side": .number(Double(side)),
          "negative": .bool(negative), "out": .string(file.path)
        ])]))
        try Task.checkCancellation()
        let decoded = await ImagePipeline.detail(file, size: side)
        guard !Task.isCancelled, generation == detailGeneration,
              selected == path, parameterPath == path, params == p,
              showNegative == negative, workspace == .develop else { return }
        guard let decoded else { throw WorkbenchError(message: "无法读取清晰预览，请重新缩放重试。") }
        detailImage = NSImage(cgImage: decoded, size: .zero)
        detailLoadedSide = side
      } catch {
        if !Task.isCancelled, generation == detailGeneration { failure(error) }
      }
    }
  }
}
