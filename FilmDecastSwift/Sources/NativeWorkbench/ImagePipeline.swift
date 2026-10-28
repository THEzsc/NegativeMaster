import AppKit
import SwiftUI
import ImageIO
import CryptoKit
import UniformTypeIdentifiers

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
    let fileSize = attributes[.size] as? Int ?? 0
    let identity = "\(path):\(stamp):\(fileSize):\(size):v2"
    return try await image(key: identity, size: size) {
      try await withCheckedThrowingContinuation { continuation in
        Self.fileQueue.async {
          do { continuation.resume(returning: try Self.thumbnailData(path, identity: identity, size: size)) }
          catch { continuation.resume(throwing: error) }
        }
      }
    }
  }
  private nonisolated static let fileQueue = DispatchQueue(label: "NegativeMaster.thumbnails", qos: .utility)
  nonisolated static func trimThumbnails() async {
    await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
      fileQueue.async {
        let fm = FileManager.default
        let folder = fm.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("NegativeMaster/thumbnails-v2")
        let files = (try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey])) ?? []
        let entries = files.filter { $0.pathExtension == "jpg" }.compactMap { url -> (URL, Date, Int)? in
          guard let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey]) else { return nil }
          return (url, values.contentModificationDate ?? .distantPast, values.fileSize ?? 0)
        }.sorted { $0.1 > $1.1 }
        var bytes = 0
        for (url, _, size) in entries {
          bytes += size
          if bytes > 128 * 1024 * 1024 { try? fm.removeItem(at: url) }
        }
        continuation.resume()
      }
    }
  }
  nonisolated static func thumbnailData(_ path: String, identity: String, size: Int) throws -> Data {
    let fm = FileManager.default
    let folder = fm.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("NegativeMaster/thumbnails-v2")
    let hash = SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    let file = folder.appendingPathComponent(hash + ".jpg")
    if let data = try? Data(contentsOf: file), decode(data, size: size) != nil { return data }
    // URL-backed ImageIO can use the RAW's embedded preview without reading the full ARW into Data.
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
      let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
        kCGImageSourceCreateThumbnailFromImageIfAbsent: true,
        kCGImageSourceThumbnailMaxPixelSize: size,
        kCGImageSourceCreateThumbnailWithTransform: true,
        kCGImageSourceShouldCacheImmediately: true
      ] as CFDictionary) else { throw WorkbenchError(message: "无法生成缩略图") }
    let data = NSMutableData()
    guard let target = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else {
      throw WorkbenchError(message: "无法保存缩略图")
    }
    CGImageDestinationAddImage(target, image, [kCGImageDestinationLossyCompressionQuality: 0.85] as CFDictionary)
    guard CGImageDestinationFinalize(target) else { throw WorkbenchError(message: "缩略图编码失败") }
    try? fm.createDirectory(at: folder, withIntermediateDirectories: true)
    try? (data as Data).write(to: file, options: .atomic)
    return data as Data
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
