//
//  ImageExporter.swift —— 导出（16bit TIFF / 8bit JPEG）
//
//  输入是 develop 输出的「显示值」图像（0~1，已含 gamma），
//  这里直接量化写盘，不再做任何色调变换；色彩空间统一标记为 sRGB。
//

import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

/// 导出格式
public enum ExportFormat {
    /// 16bit TIFF（无损，适合后期再调整）
    case tiff16
    /// 8bit JPEG，quality 0~1
    case jpeg(quality: Double)
}

/// 图像导出器
public enum ImageExporter {

    /// 保存图像。
    /// - Parameters:
    ///   - img: develop 输出的显示值图像（0~1）
    ///   - url: 目标路径（扩展名不强制，由 format 决定编码）
    ///   - format: tiff16 或 jpeg
    ///   - resizeLongEdge: >0 时先把最长边缩到该像素（区域平均缩小，0 = 原尺寸）
    public static func save(_ img: LinearImage,
                            to url: URL,
                            format: ExportFormat,
                            resizeLongEdge: Int = 0) throws {
        var image = img
        if resizeLongEdge > 0, max(img.width, img.height) > resizeLongEdge {
            image = resized(img, longEdge: resizeLongEdge)
        }
        switch format {
        case .tiff16:
            try saveTIFF16(image, to: url)
        case .jpeg(let quality):
            try saveJPEG(image, to: url, quality: quality)
        }
    }

    // ------------------------------------------------------------------ //
    // TIFF 16bit
    // ------------------------------------------------------------------ //

    private static func saveTIFF16(_ img: LinearImage, to url: URL) throws {
        let w = img.width, h = img.height
        // 量化到 UInt16 交错 RGB
        var data16 = [UInt16](repeating: 0, count: w * h * 3)
        img.pixels.withUnsafeBufferPointer { src in
            data16.withUnsafeMutableBufferPointer { dst in
                for i in 0..<dst.count {
                    let v = min(max(src[i], 0), 1)
                    dst[i] = UInt16(v * 65535 + 0.5)
                }
            }
        }
        let data = data16.withUnsafeBufferPointer { Data(buffer: $0) }
        guard let provider = CGDataProvider(data: data as CFData) else {
            throw EngineError.exportFailed("无法创建数据缓冲")
        }
        // 16bit 小端（主机序）、无 alpha、48bpp
        let bitmapInfo = CGBitmapInfo(rawValue:
            CGImageAlphaInfo.none.rawValue | CGBitmapInfo.byteOrder16Little.rawValue)
        guard let cg = CGImage(width: w,
                               height: h,
                               bitsPerComponent: 16,
                               bitsPerPixel: 48,
                               bytesPerRow: w * 6,
                               space: CGColorSpace(name: CGColorSpace.sRGB)!,
                               bitmapInfo: bitmapInfo,
                               provider: provider,
                               decode: nil,
                               shouldInterpolate: false,
                               intent: .defaultIntent) else {
            throw EngineError.exportFailed("无法构建 16bit 图像")
        }
        try writeDestination(cg, to: url, type: UTType.tiff, properties: [
            kCGImagePropertyTIFFDictionary: [
                kCGImagePropertyTIFFCompression: 5   // LZW，无损压缩
            ] as CFDictionary
        ] as CFDictionary)
    }

    // ------------------------------------------------------------------ //
    // JPEG 8bit
    // ------------------------------------------------------------------ //

    private static func saveJPEG(_ img: LinearImage, to url: URL,
                                 quality: Double) throws {
        guard let cg = NegativeEngine.makeCGImage(img) else {
            throw EngineError.exportFailed("无法构建 8bit 图像")
        }
        let q = min(max(quality, 0), 1)
        try writeDestination(cg, to: url, type: UTType.jpeg, properties: [
            kCGImageDestinationLossyCompressionQuality: q as CFNumber
        ] as CFDictionary)
    }

    // ------------------------------------------------------------------ //
    // 公共写盘
    // ------------------------------------------------------------------ //

    private static func writeDestination(_ cg: CGImage, to url: URL,
                                         type: UTType,
                                         properties: CFDictionary?) throws {
        guard let dest = CGImageDestinationCreateWithURL(
            url as CFURL, type.identifier as CFString, 1, nil) else {
            throw EngineError.exportFailed("无法创建输出文件 \(url.lastPathComponent)")
        }
        CGImageDestinationAddImage(dest, cg, properties)
        guard CGImageDestinationFinalize(dest) else {
            throw EngineError.exportFailed("写入失败 \(url.lastPathComponent)")
        }
    }

    // ------------------------------------------------------------------ //
    // 缩小（区域平均，导出用）
    // ------------------------------------------------------------------ //

    /// 区域平均缩小：每个目标像素取源图对应整数矩形的均值（仅用于缩小）
    static func resized(_ img: LinearImage, longEdge: Int) -> LinearImage {
        let sw = img.width, sh = img.height
        let side = max(sw, sh)
        guard longEdge > 0, side > longEdge else { return img }
        let ratio = Double(side) / Double(longEdge)
        let dw = max(1, Int((Double(sw) / ratio).rounded()))
        let dh = max(1, Int((Double(sh) / ratio).rounded()))
        var out = [Float](repeating: 0, count: dw * dh * 3)
        img.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                for dy in 0..<dh {
                    let sy0 = min(Int(Double(dy) * Double(sh) / Double(dh)), sh - 1)
                    let sy1 = max(sy0 + 1, min(Int(Double(dy + 1) * Double(sh) / Double(dh)), sh))
                    for dx in 0..<dw {
                        let sx0 = min(Int(Double(dx) * Double(sw) / Double(dw)), sw - 1)
                        let sx1 = max(sx0 + 1, min(Int(Double(dx + 1) * Double(sw) / Double(dw)), sw))
                        var r: Float = 0, g: Float = 0, b: Float = 0
                        for y in sy0..<sy1 {
                            let row = y * sw
                            for x in sx0..<sx1 {
                                let s = (row + x) * 3
                                r += src[s]; g += src[s + 1]; b += src[s + 2]
                            }
                        }
                        let cnt = Float((sy1 - sy0) * (sx1 - sx0))
                        let d = (dy * dw + dx) * 3
                        dst[d] = r / cnt; dst[d + 1] = g / cnt; dst[d + 2] = b / cnt
                    }
                }
            }
        }
        return LinearImage(width: dw, height: dh, pixels: out)
    }
}
