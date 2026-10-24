import AppKit
import SwiftUI
import ImageIO

/// Decoded images are bounded by memory, shared across workspaces and coalesced in flight.
actor ImagePipeline {
  static let shared = ImagePipeline()
  private var cache: [String: CGImage] = [:]
  private var order: [String] = []
  private var pending: [String: Task<CGImage?, Error>] = [:]
  private var bytes = 0
  private let byteLimit = 48 * 1024 * 1024
  func image(key: String, size: Int, load: @escaping @Sendable () async throws -> Data) async throws -> CGImage? {
    let key = "\(size):\(key)"
    if let image = cache[key] { order.removeAll { $0 == key }; order.append(key); return image }
    if let task = pending[key] { return try await task.value }
    let task = Task.detached(priority: .utility) { Self.decode(try await load(), size: size) }
    pending[key] = task
    do {
      let image = try await task.value
      pending[key] = nil
      if let image {
        cache[key] = image; order.append(key); bytes += image.bytesPerRow * image.height
        while bytes > byteLimit, let old = order.first {
          order.removeFirst()
          if let removed = cache.removeValue(forKey: old) { bytes -= removed.bytesPerRow * removed.height }
        }
      }
      return image
    } catch { pending[key] = nil; throw error }
  }
  func file(_ path: String, size: Int) async throws -> CGImage? {
    let attributes = try FileManager.default.attributesOfItem(atPath: path)
    let stamp = (attributes[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
    return try await image(key: "file:\(path):\(stamp)", size: size) { try Data(contentsOf: URL(fileURLWithPath: path)) }
  }
  nonisolated static func decode(_ data: Data, size: Int) -> CGImage? {
    guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
    return CGImageSourceCreateThumbnailAtIndex(source, 0, [
      kCGImageSourceCreateThumbnailFromImageAlways: true,
      kCGImageSourceThumbnailMaxPixelSize: size,
      kCGImageSourceCreateThumbnailWithTransform: true,
      kCGImageSourceShouldCacheImmediately: true
    ] as CFDictionary)
  }
  nonisolated static func preview(_ value: J) async -> CGImage? {
    await Task.detached(priority: .userInitiated) {
      guard let data = Data(base64Encoded: value.string) else { return nil }
      return decode(data, size: 2000)
    }.value
  }
}

struct CachedPhoto: View {
  let path: String
  var size = 320
  @State private var image: NSImage?
  var body: some View {
    ZStack {
      Color.secondary.opacity(0.06)
      if let image { Image(nsImage: image).resizable().scaledToFit() }
      else { Image(systemName: "photo").foregroundStyle(.tertiary) }
    }.task(id: "\(path):\(size)") {
      image = nil
      if let cg = try? await ImagePipeline.shared.file(path, size: size), !Task.isCancelled {
        image = NSImage(cgImage: cg, size: .zero)
      }
    }
  }
}
