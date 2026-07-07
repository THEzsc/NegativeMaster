//
//  NegativeEngine.swift —— 去色罩 + 反转的核心处理管线
//
//  与 decast.py 的 convert_negative 同构：
//    线性 RGB → 方向（旋转/镜像）→ 裁切 → 按模式反转（密度空间）
//    → 白平衡（取样点 / 灰世界 / 无）→ 色温色调
//    → 直方图匹配 或 (gamma → 对比度 S 曲线 → 饱和度)
//    → 锐化（亮度 unsharp）→ 色度降噪
//
//  数值行为尽量与 Python 版一致：
//    - 百分位用「下采样 + 排序 + 线性插值」（同 numpy percentile 的 linear 法）
//    - 直方图匹配用 512 bin 的逐通道 CDF 映射
//

import Foundation
import CoreGraphics
import CoreImage
import Accelerate
import ImageIO

/// 核心引擎：全部为纯函数（static），不依赖 UI，可在任意线程调用
public final class NegativeEngine {

    private init() {}

    // ------------------------------------------------------------------ //
    // 常量
    // ------------------------------------------------------------------ //

    /// 相机 RAW 扩展名（走 CIRAWFilter，线性、不自动提亮）
    public static let rawExtensions: Set<String> = [
        "arw", "arq", "cr2", "cr3", "nef", "raf", "dng", "rw2",
        "orf", "pef", "srw", "raw", "3fr", "iiq"
    ]

    /// 普通图像扩展名（走 CIImage，自动转到线性工作空间）
    public static let imageExtensions: Set<String> = [
        "tif", "tiff", "png", "jpg", "jpeg", "bmp", "webp", "heic", "heif"
    ]

    /// 密度运算下限（同 decast.py 的 eps）
    private static let eps: Float = 1e-5

    /// 直方图匹配 bin 数（同 decast.py 的 nbins）
    private static let histBins = 512

    /// 统计（百分位/CDF）用的下采样最长边（同 decast.py stats_view）
    private static let statsMaxSide = 1000

    /// 线性 sRGB 色彩空间（渲染 / 统计共用）
    private static let linearColorSpace =
        CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!

    /// 共享 CIContext：工作空间设为线性 sRGB，渲染结果即线性光
    private static let ciContext = CIContext(options: [
        .workingColorSpace: linearColorSpace,
        .cacheIntermediates: false,
    ])

    // ------------------------------------------------------------------ //
    // 读取
    // ------------------------------------------------------------------ //

    /// 读入文件为线性 RGB 图像。
    /// - RAW（.arw/.arq/.cr2/...）：CIRAWFilter，boostAmount=0（线性、不自动提亮）
    /// - 普通图像（tif/jpg/png/heic/...）：CIImage，按 EXIF 方向摆正，
    ///   Core Image 自动把编码值转到线性工作空间
    public static func load(url: URL) throws -> LinearImage {
        let ext = url.pathExtension.lowercased()
        let ciImage: CIImage

        if rawExtensions.contains(ext) {
            guard let filter = CIRAWFilter(imageURL: url) else {
                throw EngineError.loadFailed("无法解析 RAW 文件 \(url.lastPathComponent)")
            }
            filter.boostAmount = 0   // 线性输出，不做自动提亮（同 rawpy no_auto_bright + gamma(1,1)）
            guard let out = filter.outputImage else {
                throw EngineError.loadFailed("RAW 解码失败 \(url.lastPathComponent)")
            }
            ciImage = out
        } else {
            guard let img = CIImage(contentsOf: url,
                                    options: [.applyOrientationProperty: true]) else {
                throw EngineError.loadFailed("无法打开图像 \(url.lastPathComponent)")
            }
            ciImage = img
        }

        let extent = ciImage.extent.integral
        let w = Int(extent.width)
        let h = Int(extent.height)
        guard w > 1, h > 1, w * h <= 400_000_000 else {
            throw EngineError.loadFailed("图像尺寸异常（\(w)x\(h)）")
        }

        // 渲染成 RGBAf（float32）线性缓冲
        var rgba = [Float](repeating: 0, count: w * h * 4)
        rgba.withUnsafeMutableBytes { buf in
            ciContext.render(ciImage,
                             toBitmap: buf.baseAddress!,
                             rowBytes: w * 4 * MemoryLayout<Float>.size,
                             bounds: extent,
                             format: .RGBAf,
                             colorSpace: linearColorSpace)
        }

        // 去掉 alpha，并夹到 [0,1]（extended 空间可能有轻微越界值）
        var pixels = [Float](repeating: 0, count: w * h * 3)
        pixels.withUnsafeMutableBufferPointer { dst in
            rgba.withUnsafeBufferPointer { src in
                for i in 0..<(w * h) {
                    let s = i * 4
                    let d = i * 3
                    dst[d]     = min(max(src[s], 0), 1)
                    dst[d + 1] = min(max(src[s + 1], 0), 1)
                    dst[d + 2] = min(max(src[s + 2], 0), 1)
                }
            }
        }
        return LinearImage(width: w, height: h, pixels: pixels)
    }

    // ------------------------------------------------------------------ //
    // 下采样（跨步取样，用于预览与统计）
    // ------------------------------------------------------------------ //

    /// 跨步下采样：最长边缩到 maxSide 以内（同 decast.py stats_view）
    public static func downsample(_ img: LinearImage, maxSide: Int) -> LinearImage {
        let side = max(img.width, img.height)
        guard maxSide > 0, side > maxSide else { return img }
        let step = Int(ceil(Double(side) / Double(maxSide)))
        let nw = (img.width + step - 1) / step
        let nh = (img.height + step - 1) / step
        var out = [Float](repeating: 0, count: nw * nh * 3)
        img.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                var di = 0
                var y = 0
                while y < img.height {
                    let row = y * img.width
                    var x = 0
                    while x < img.width {
                        let s = (row + x) * 3
                        dst[di] = src[s]
                        dst[di + 1] = src[s + 1]
                        dst[di + 2] = src[s + 2]
                        di += 3
                        x += step
                    }
                    y += step
                }
            }
        }
        return LinearImage(width: nw, height: nh, pixels: out)
    }

    // ------------------------------------------------------------------ //
    // 冲洗管线
    // ------------------------------------------------------------------ //

    /// 完整冲洗：输入线性图像 + 参数（+ 可选直方图匹配参照），
    /// 输出「显示值」图像（0~1，已含 gamma，直接量化显示/导出即可）。
    public static func develop(_ img: LinearImage,
                               params: DevelopParams,
                               matchRef: HistogramReference? = nil) -> LinearImage {
        // 1) 方向：旋转（顺时针）+ 镜像 —— 之后的裁切坐标即最终显示方向
        var work = orient(img, rotate: params.rotate,
                          flipH: params.flipH, flipV: params.flipV)

        // 2) 裁切（归一化矩形，真正裁掉）
        if let rect = params.cropRect {
            work = crop(work, rect: rect)
        }
        let w = work.width
        let h = work.height
        var P = work.pixels

        // 3) 按模式反转 / 拉伸
        switch params.mode {
        case .colorNegative:
            invertColorNegative(&P, width: w, height: h,
                                blackPct: Float(params.blackPct),
                                whitePct: Float(params.whitePct))
        case .bwNegative:
            invertBWNegative(&P, width: w, height: h,
                             blackPct: Float(params.blackPct),
                             whitePct: Float(params.whitePct))
        case .positive:
            stretchPositive(&P, width: w, height: h,
                            blackPct: Float(params.blackPct),
                            whitePct: Float(params.whitePct))
        }

        // 黑白模式没有色彩可调：白平衡 / 色温色调 / 饱和度 / 直方图匹配
        // 全部跳过，只走 gamma + 对比度 + 锐化（同 decast.py 的 bw 分支）
        let isBW = params.mode == .bwNegative
        let matching = params.useMatch && matchRef != nil && !isBW

        // 4) 白平衡（在已反转的正片上做；框选/取样点优先于灰世界；
        //    灰世界在 match 模式下跳过，同 decast.py）
        if !isBW {
            if let rect = params.wbRect {
                applyRectWhiteBalance(&P, width: w, height: h,
                                      rect: rect, cropRect: params.cropRect)
            } else if let point = params.wbPoint {
                applyPointWhiteBalance(&P, width: w, height: h,
                                       point: point, cropRect: params.cropRect)
            } else if params.wb == .grayWorld && !matching {
                applyGrayWorld(&P, width: w, height: h)
            }
        }

        if matching {
            // 5a) 直方图匹配：转移参照扫描件的色调与色彩
            //     （覆盖色温色调 / gamma / 对比度 / 饱和度）
            applyHistogramMatch(&P, width: w, height: h, ref: matchRef!)
        } else {
            // 5b) 手动影调（色温色调 / 饱和度只对彩色有意义）
            if !isBW {
                applyTemperatureTint(&P,
                                     temperature: Float(params.temperature),
                                     tint: Float(params.tint))
            }
            applyGamma(&P, gamma: Float(params.gamma))
            applyContrast(&P, k: Float(params.contrast))
            if !isBW {
                applySaturation(&P, s: Float(params.saturation))
            }
        }

        // 6) 锐化：亮度 unsharp mask（只锐化亮度，不放大彩色噪声）
        if params.sharpen > 1e-3 {
            applySharpen(&P, width: w, height: h,
                         amount: Float(params.sharpen),
                         radius: Int(params.sharpenRadius.rounded()))
        }

        // 7) 色度降噪：去掉反转放大出来的彩色颗粒（尤其蓝通道）；
        //    黑白模式 R==G==B 无色度，跳过（同 decast.py）
        let dr = Int(params.denoise.rounded())
        if dr >= 1 && !isBW {
            applyChromaDenoise(&P, width: w, height: h, radius: dr)
        }

        clip01(&P)
        return LinearImage(width: w, height: h, pixels: P)
    }

    // ------------------------------------------------------------------ //
    // 方向与裁切
    // ------------------------------------------------------------------ //

    /// 旋转（顺时针 0/90/180/270）+ 水平/垂直镜像
    static func orient(_ img: LinearImage, rotate: Int,
                       flipH: Bool, flipV: Bool) -> LinearImage {
        var out = img
        let r = ((rotate % 360) + 360) % 360
        if r == 90 || r == 180 || r == 270 {
            out = rotated(out, degreesCW: r)
        }
        if flipH { out = flippedH(out) }
        if flipV { out = flippedV(out) }
        return out
    }

    private static func rotated(_ img: LinearImage, degreesCW: Int) -> LinearImage {
        let w = img.width, h = img.height
        switch degreesCW {
        case 90:
            // 顺时针 90°：src(r,c) -> dst(c, h-1-r)，新尺寸 h x w
            var out = [Float](repeating: 0, count: img.pixels.count)
            img.pixels.withUnsafeBufferPointer { src in
                out.withUnsafeMutableBufferPointer { dst in
                    for r in 0..<h {
                        let srow = r * w
                        let dcol = h - 1 - r
                        for c in 0..<w {
                            let s = (srow + c) * 3
                            let d = (c * h + dcol) * 3
                            dst[d] = src[s]; dst[d + 1] = src[s + 1]; dst[d + 2] = src[s + 2]
                        }
                    }
                }
            }
            return LinearImage(width: h, height: w, pixels: out)
        case 180:
            var out = [Float](repeating: 0, count: img.pixels.count)
            let n = w * h
            img.pixels.withUnsafeBufferPointer { src in
                out.withUnsafeMutableBufferPointer { dst in
                    for i in 0..<n {
                        let s = i * 3
                        let d = (n - 1 - i) * 3
                        dst[d] = src[s]; dst[d + 1] = src[s + 1]; dst[d + 2] = src[s + 2]
                    }
                }
            }
            return LinearImage(width: w, height: h, pixels: out)
        case 270:
            // 顺时针 270°（= 逆时针 90°）：src(r,c) -> dst(w-1-c, r)，新尺寸 h x w
            var out = [Float](repeating: 0, count: img.pixels.count)
            img.pixels.withUnsafeBufferPointer { src in
                out.withUnsafeMutableBufferPointer { dst in
                    for r in 0..<h {
                        let srow = r * w
                        for c in 0..<w {
                            let s = (srow + c) * 3
                            let d = ((w - 1 - c) * h + r) * 3
                            dst[d] = src[s]; dst[d + 1] = src[s + 1]; dst[d + 2] = src[s + 2]
                        }
                    }
                }
            }
            return LinearImage(width: h, height: w, pixels: out)
        default:
            return img
        }
    }

    private static func flippedH(_ img: LinearImage) -> LinearImage {
        let w = img.width, h = img.height
        var out = [Float](repeating: 0, count: img.pixels.count)
        img.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                for y in 0..<h {
                    let row = y * w
                    for x in 0..<w {
                        let s = (row + x) * 3
                        let d = (row + w - 1 - x) * 3
                        dst[d] = src[s]; dst[d + 1] = src[s + 1]; dst[d + 2] = src[s + 2]
                    }
                }
            }
        }
        return LinearImage(width: w, height: h, pixels: out)
    }

    private static func flippedV(_ img: LinearImage) -> LinearImage {
        let w = img.width, h = img.height
        var out = [Float](repeating: 0, count: img.pixels.count)
        let rowLen = w * 3
        img.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                for y in 0..<h {
                    let s = y * rowLen
                    let d = (h - 1 - y) * rowLen
                    for i in 0..<rowLen { dst[d + i] = src[s + i] }
                }
            }
        }
        return LinearImage(width: w, height: h, pixels: out)
    }

    /// 归一化矩形 -> 像素矩形（带边界与顺序保护，同 decast.py _rect_px）
    static func rectPixels(_ rect: CropRectN, width: Int, height: Int)
        -> (x0: Int, y0: Int, x1: Int, y1: Int) {
        var xa = Int((Double(width) * min(rect.x0, rect.x1)).rounded())
        var xb = Int((Double(width) * max(rect.x0, rect.x1)).rounded())
        var ya = Int((Double(height) * min(rect.y0, rect.y1)).rounded())
        var yb = Int((Double(height) * max(rect.y0, rect.y1)).rounded())
        xa = max(0, min(xa, width - 2));  xb = max(xa + 2, min(xb, width))
        ya = max(0, min(ya, height - 2)); yb = max(ya + 2, min(yb, height))
        return (xa, ya, xb, yb)
    }

    private static func crop(_ img: LinearImage, rect: CropRectN) -> LinearImage {
        let (xa, ya, xb, yb) = rectPixels(rect, width: img.width, height: img.height)
        let nw = xb - xa
        let nh = yb - ya
        if nw == img.width && nh == img.height { return img }
        var out = [Float](repeating: 0, count: nw * nh * 3)
        img.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                for y in 0..<nh {
                    let s = ((ya + y) * img.width + xa) * 3
                    let d = y * nw * 3
                    for i in 0..<(nw * 3) { dst[d + i] = src[s + i] }
                }
            }
        }
        return LinearImage(width: nw, height: nh, pixels: out)
    }

    // ------------------------------------------------------------------ //
    // 反转（密度空间）
    // ------------------------------------------------------------------ //

    /// 彩色负片：D = -log10(clip(lin))，每通道按百分位求黑白点后归一化。
    /// 橙色色罩在密度空间是每通道固定偏移，减黑点即同时完成去色罩+反转。
    private static func invertColorNegative(_ P: inout [Float],
                                            width: Int, height: Int,
                                            blackPct: Float, whitePct: Float) {
        let n = width * height
        // 就地转密度：clip -> log10 -> 取负
        var lo = eps
        var hi: Float = 1.0
        var count = Int32(P.count)
        P.withUnsafeMutableBufferPointer { buf in
            let p = buf.baseAddress!
            vDSP_vclip(p, 1, &lo, &hi, p, 1, vDSP_Length(buf.count))
            vvlog10f(p, p, &count)
            vDSP_vneg(p, 1, p, 1, vDSP_Length(buf.count))
        }

        // 下采样统计：每通道收集密度样本
        let step = statsStep(width: width, height: height)
        var samples = gatherChannelSamples(P, width: width, height: height, step: step)

        // 每通道 (D - bp) / (wp - bp)
        for c in 0..<3 {
            vDSP_vsort(&samples[c], vDSP_Length(samples[c].count), 1)
            let bp = percentileSorted(samples[c], blackPct)
            var wp = percentileSorted(samples[c], whitePct)
            if wp - bp < 1e-6 { wp = bp + 1e-6 }
            var scale = 1.0 / (wp - bp)
            var offset = -bp / (wp - bp)
            P.withUnsafeMutableBufferPointer { buf in
                let p = buf.baseAddress! + c
                vDSP_vsmsa(p, 3, &scale, &offset, p, 3, vDSP_Length(n))
            }
        }
        clip01(&P)
    }

    /// 黑白负片：用亮度密度做单通道反转，三通道写同一结果
    private static func invertBWNegative(_ P: inout [Float],
                                         width: Int, height: Int,
                                         blackPct: Float, whitePct: Float) {
        let n = width * height
        var Y = luminancePlane(P, count: n)
        // 亮度 -> 密度
        var lo = eps
        var hi: Float = 1.0
        var count = Int32(n)
        Y.withUnsafeMutableBufferPointer { buf in
            let p = buf.baseAddress!
            vDSP_vclip(p, 1, &lo, &hi, p, 1, vDSP_Length(n))
            vvlog10f(p, p, &count)
            vDSP_vneg(p, 1, p, 1, vDSP_Length(n))
        }

        var samples = gatherPlaneSamples(Y, width: width, height: height,
                                         step: statsStep(width: width, height: height))
        vDSP_vsort(&samples, vDSP_Length(samples.count), 1)
        let bp = percentileSorted(samples, blackPct)
        var wp = percentileSorted(samples, whitePct)
        if wp - bp < 1e-6 { wp = bp + 1e-6 }
        var scale = 1.0 / (wp - bp)
        var offset = -bp / (wp - bp)
        Y.withUnsafeMutableBufferPointer { buf in
            let p = buf.baseAddress!
            vDSP_vsmsa(p, 1, &scale, &offset, p, 1, vDSP_Length(n))
        }

        P.withUnsafeMutableBufferPointer { dst in
            Y.withUnsafeBufferPointer { src in
                for i in 0..<n {
                    let v = min(max(src[i], 0), 1)
                    let d = i * 3
                    dst[d] = v; dst[d + 1] = v; dst[d + 2] = v
                }
            }
        }
    }

    /// 正片：不反转，按亮度百分位做统一线性拉伸（三通道同一系数，不动色彩）
    private static func stretchPositive(_ P: inout [Float],
                                        width: Int, height: Int,
                                        blackPct: Float, whitePct: Float) {
        let n = width * height
        let Y = luminancePlane(P, count: n)
        var samples = gatherPlaneSamples(Y, width: width, height: height,
                                         step: statsStep(width: width, height: height))
        vDSP_vsort(&samples, vDSP_Length(samples.count), 1)
        let bp = percentileSorted(samples, blackPct)
        var wp = percentileSorted(samples, whitePct)
        if wp - bp < 1e-6 { wp = bp + 1e-6 }
        var scale = 1.0 / (wp - bp)
        var offset = -bp / (wp - bp)
        P.withUnsafeMutableBufferPointer { buf in
            let p = buf.baseAddress!
            vDSP_vsmsa(p, 1, &scale, &offset, p, 1, vDSP_Length(buf.count))
        }
        clip01(&P)
    }

    // ------------------------------------------------------------------ //
    // 白平衡
    // ------------------------------------------------------------------ //

    /// 框选白平衡：取框内每通道平均值，把这一块拉成中性灰。
    /// rect 是「方向后、裁切前」的归一化坐标，这里映射进裁切后的图。
    private static func applyRectWhiteBalance(_ P: inout [Float],
                                              width: Int, height: Int,
                                              rect: CropRectN, cropRect: CropRectN?) {
        var x0 = min(rect.x0, rect.x1)
        var x1 = max(rect.x0, rect.x1)
        var y0 = min(rect.y0, rect.y1)
        var y1 = max(rect.y0, rect.y1)
        if let cropRect {
            let cx0 = min(cropRect.x0, cropRect.x1), cx1 = max(cropRect.x0, cropRect.x1)
            let cy0 = min(cropRect.y0, cropRect.y1), cy1 = max(cropRect.y0, cropRect.y1)
            if cx1 - cx0 > 1e-6 {
                x0 = (x0 - cx0) / (cx1 - cx0)
                x1 = (x1 - cx0) / (cx1 - cx0)
            }
            if cy1 - cy0 > 1e-6 {
                y0 = (y0 - cy0) / (cy1 - cy0)
                y1 = (y1 - cy0) / (cy1 - cy0)
            }
        }
        x0 = min(max(x0, 0), 1); x1 = min(max(x1, 0), 1)
        y0 = min(max(y0, 0), 1); y1 = min(max(y1, 0), 1)
        let xa = min(max(Int(min(x0, x1) * Double(width)), 0), width - 1)
        let xb = min(max(Int(ceil(max(x0, x1) * Double(width))), xa + 1), width)
        let ya = min(max(Int(min(y0, y1) * Double(height)), 0), height - 1)
        let yb = min(max(Int(ceil(max(y0, y1) * Double(height))), ya + 1), height)

        var mean = [Float](repeating: 0, count: 3)
        var count: Float = 0
        for y in ya..<yb {
            let row = y * width
            for x in xa..<xb {
                let i = (row + x) * 3
                mean[0] += P[i]
                mean[1] += P[i + 1]
                mean[2] += P[i + 2]
                count += 1
            }
        }
        guard count > 0 else { return }
        for c in 0..<3 { mean[c] /= count }
        applyWhiteBalanceScales(&P, sampleColor: mean, pixelCount: width * height)
    }

    /// 取样点白平衡：取该点 11x11 邻域每通道中值，把这一点拉成中性灰。
    /// point 是「方向后、裁切前」的归一化坐标，这里映射进裁切后的图。
    private static func applyPointWhiteBalance(_ P: inout [Float],
                                               width: Int, height: Int,
                                               point: CGPoint, cropRect: CropRectN?) {
        var u = Double(point.x)
        var v = Double(point.y)
        if let rect = cropRect {
            let x0 = min(rect.x0, rect.x1), x1 = max(rect.x0, rect.x1)
            let y0 = min(rect.y0, rect.y1), y1 = max(rect.y0, rect.y1)
            if x1 - x0 > 1e-6 { u = (u - x0) / (x1 - x0) }
            if y1 - y0 > 1e-6 { v = (v - y0) / (y1 - y0) }
        }
        u = min(max(u, 0), 1)
        v = min(max(v, 0), 1)
        let cx = min(max(Int(u * Double(width)), 0), width - 1)
        let cy = min(max(Int(v * Double(height)), 0), height - 1)

        // 11x11 邻域（边界处自动收窄），逐通道求中值
        let r = 5
        let xa = max(0, cx - r), xb = min(width - 1, cx + r)
        let ya = max(0, cy - r), yb = min(height - 1, cy + r)
        var med = [Float](repeating: 0, count: 3)
        var win = [Float]()
        win.reserveCapacity((2 * r + 1) * (2 * r + 1))
        for c in 0..<3 {
            win.removeAll(keepingCapacity: true)
            for y in ya...yb {
                let row = y * width
                for x in xa...xb {
                    win.append(P[(row + x) * 3 + c])
                }
            }
            win.sort()
            let m = win.count
            med[c] = m % 2 == 1 ? win[m / 2]
                                : 0.5 * (win[m / 2 - 1] + win[m / 2])
        }

        applyWhiteBalanceScales(&P, sampleColor: med, pixelCount: width * height)
    }

    private static func applyWhiteBalanceScales(_ P: inout [Float],
                                                sampleColor: [Float],
                                                pixelCount: Int) {
        let g = (sampleColor[0] + sampleColor[1] + sampleColor[2]) / 3
        var scales = [Float](repeating: 1, count: 3)
        for c in 0..<3 {
            let s = g / max(sampleColor[c], 1e-4)
            scales[c] = min(max(s, 0.4), 2.5)   // 防止极端取样点造成爆色（同 decast.py）
        }
        multiplyChannels(&P, scales: scales, pixelCount: pixelCount)
        clip01(&P)
    }

    /// 灰世界白平衡：只用亮度 0.15~0.9 的中间调像素估计（同 decast.py）
    private static func applyGrayWorld(_ P: inout [Float], width: Int, height: Int) {
        let n = width * height
        var sumMask: (Float, Float, Float) = (0, 0, 0)
        var cntMask = 0
        var sumAll: (Float, Float, Float) = (0, 0, 0)
        P.withUnsafeBufferPointer { buf in
            for i in 0..<n {
                let idx = i * 3
                let r = buf[idx], g = buf[idx + 1], b = buf[idx + 2]
                let lum = 0.299 * r + 0.587 * g + 0.114 * b
                sumAll.0 += r; sumAll.1 += g; sumAll.2 += b
                if lum > 0.15 && lum < 0.9 {
                    sumMask.0 += r; sumMask.1 += g; sumMask.2 += b
                    cntMask += 1
                }
            }
        }
        var mean: [Float]
        if Float(cntMask) > 0.02 * Float(n) {
            mean = [sumMask.0 / Float(cntMask), sumMask.1 / Float(cntMask),
                    sumMask.2 / Float(cntMask)]
        } else {
            mean = [sumAll.0 / Float(n), sumAll.1 / Float(n), sumAll.2 / Float(n)]
        }
        let g = (mean[0] + mean[1] + mean[2]) / 3
        var scales = [Float](repeating: 1, count: 3)
        for c in 0..<3 {
            scales[c] = min(max(g / max(mean[c], 1e-4), 0.5), 2.0)
        }
        multiplyChannels(&P, scales: scales, pixelCount: n)
        clip01(&P)
    }

    // ------------------------------------------------------------------ //
    // 色温 / 色调
    // ------------------------------------------------------------------ //

    /// 色温色调：通道乘法后均值归一（不改变整体亮度）。
    /// temperature > 0 偏暖（加红减蓝），tint > 0 偏品红（减绿）。
    private static func applyTemperatureTint(_ P: inout [Float],
                                             temperature: Float, tint: Float) {
        if abs(temperature) < 1e-3 && abs(tint) < 1e-3 { return }
        let t = min(max(temperature / 100, -1), 1)
        let ti = min(max(tint / 100, -1), 1)
        // 满档时通道最大偏移 30%（k=0.3，三通道同一系数，同 decast.py）
        var rs = 1 + 0.30 * t
        var gs = 1 - 0.30 * ti
        var bs = 1 - 0.30 * t
        let m = (rs + gs + bs) / 3
        rs /= m; gs /= m; bs /= m
        multiplyChannels(&P, scales: [rs, gs, bs], pixelCount: P.count / 3)
        clip01(&P)
    }

    // ------------------------------------------------------------------ //
    // 影调：gamma / 对比度 / 饱和度
    // ------------------------------------------------------------------ //

    /// gamma：P = P^(1/gamma)（>1 提亮中间调）。
    /// 用 exp((1/g)*ln(P)) 实现以吃到 vForce 加速；P=0 时 ln=-inf、exp=-0 正确。
    private static func applyGamma(_ P: inout [Float], gamma: Float) {
        guard gamma > 0, abs(gamma - 1) > 1e-3 else { return }
        var count = Int32(P.count)
        var k = 1.0 / gamma
        P.withUnsafeMutableBufferPointer { buf in
            let p = buf.baseAddress!
            vvlogf(p, p, &count)
            vDSP_vsmul(p, 1, &k, p, 1, vDSP_Length(buf.count))
            vvexpf(p, p, &count)
        }
    }

    /// 对比度 S 曲线（以 0.5 为中心，同 decast.py）：
    ///   k>0: 0.5 + (P-0.5)*(1+k) - 4k*(P-0.5)^3
    ///   k<=0: 0.5 + (P-0.5)*(1+k)
    private static func applyContrast(_ P: inout [Float], k: Float) {
        guard abs(k) > 1e-3 else { return }
        P.withUnsafeMutableBufferPointer { buf in
            if k > 0 {
                for i in 0..<buf.count {
                    let d = buf[i] - 0.5
                    let v = 0.5 + d * (1 + k) - 4 * k * d * d * d
                    buf[i] = min(max(v, 0), 1)
                }
            } else {
                for i in 0..<buf.count {
                    let v = 0.5 + (buf[i] - 0.5) * (1 + k)
                    buf[i] = min(max(v, 0), 1)
                }
            }
        }
    }

    /// 饱和度：在亮度轴上缩放色度（s<1 降，s>1 增）
    private static func applySaturation(_ P: inout [Float], s: Float) {
        guard abs(s - 1) > 1e-3 else { return }
        let n = P.count / 3
        P.withUnsafeMutableBufferPointer { buf in
            for i in 0..<n {
                let idx = i * 3
                let r = buf[idx], g = buf[idx + 1], b = buf[idx + 2]
                let y = 0.299 * r + 0.587 * g + 0.114 * b
                buf[idx]     = min(max(y + (r - y) * s, 0), 1)
                buf[idx + 1] = min(max(y + (g - y) * s, 0), 1)
                buf[idx + 2] = min(max(y + (b - y) * s, 0), 1)
            }
        }
    }

    // ------------------------------------------------------------------ //
    // 直方图匹配
    // ------------------------------------------------------------------ //

    /// 由参照图（线性）建立每通道 CDF。
    /// 注意：参照的是「显示值」分布，所以先把线性值编码回 sRGB 再统计
    /// （与 Python 版直接用扫描件编码值建 CDF 的行为一致）。
    public static func buildHistogramReference(from img: LinearImage) -> HistogramReference {
        let ds = downsample(img, maxSide: statsMaxSide)
        let nbins = histBins
        var centers = [Float](repeating: 0, count: nbins)
        for i in 0..<nbins {
            centers[i] = (Float(i) + 0.5) / Float(nbins)
        }
        var cdfs: [[Float]] = []
        for c in 0..<3 {
            var hist = [Float](repeating: 0, count: nbins)
            ds.pixels.withUnsafeBufferPointer { buf in
                var i = c
                while i < buf.count {
                    let enc = srgbEncode(min(max(buf[i], 0), 1))
                    var bin = Int(enc * Float(nbins))
                    if bin >= nbins { bin = nbins - 1 }
                    if bin < 0 { bin = 0 }
                    hist[bin] += 1
                    i += 3
                }
            }
            var cdf = [Float](repeating: 0, count: nbins)
            var acc: Float = 0
            for i in 0..<nbins { acc += hist[i]; cdf[i] = acc }
            let total = max(acc, 1)
            for i in 0..<nbins { cdf[i] /= total }
            cdfs.append(cdf)
        }
        return HistogramReference(centers: centers, cdfs: cdfs)
    }

    /// 直方图匹配：把 P 每个通道的分布映射到参照 CDF（逐通道 CDF 映射）。
    /// 用 2048 级 LUT 实现（映射单调，LUT 线性插值与逐像素插值等价）。
    private static func applyHistogramMatch(_ P: inout [Float],
                                            width: Int, height: Int,
                                            ref: HistogramReference) {
        let nbins = histBins
        let step = statsStep(width: width, height: height)
        let samples = gatherChannelSamples(P, width: width, height: height, step: step)

        let lutN = 2048
        for c in 0..<3 {
            // 源 CDF（下采样统计，够用且快）
            var hist = [Float](repeating: 0, count: nbins)
            for v in samples[c] {
                var bin = Int(min(max(v, 0), 1) * Float(nbins))
                if bin >= nbins { bin = nbins - 1 }
                hist[bin] += 1
            }
            var srcCDF = [Float](repeating: 0, count: nbins)
            var acc: Float = 0
            for i in 0..<nbins { acc += hist[i]; srcCDF[i] = acc }
            let total = max(acc, 1)
            for i in 0..<nbins { srcCDF[i] /= total }

            // LUT：v -> 源 CDF 值 s -> 参照 CDF 的反查值
            var lut = [Float](repeating: 0, count: lutN)
            let refCDF = ref.cdfs[c]
            for i in 0..<lutN {
                let v = Float(i) / Float(lutN - 1)
                let s = interpAtCenters(v, values: srcCDF, nbins: nbins)
                lut[i] = inverseInterp(s, xs: refCDF, fs: ref.centers)
            }

            // 应用 LUT（线性插值）
            P.withUnsafeMutableBufferPointer { buf in
                lut.withUnsafeBufferPointer { L in
                    var i = c
                    let scale = Float(lutN - 1)
                    while i < buf.count {
                        let t = min(max(buf[i], 0), 1) * scale
                        let j = min(Int(t), lutN - 2)
                        let f = t - Float(j)
                        buf[i] = L[j] + (L[j + 1] - L[j]) * f
                        i += 3
                    }
                }
            }
        }
        clip01(&P)
    }

    /// 在均匀 bin 中心上做线性插值（等价 np.interp(v, centers, values)）
    private static func interpAtCenters(_ v: Float, values: [Float], nbins: Int) -> Float {
        let t = v * Float(nbins) - 0.5   // 对应 centers 的连续下标
        if t <= 0 { return values[0] }
        if t >= Float(nbins - 1) { return values[nbins - 1] }
        let j = Int(t)
        let f = t - Float(j)
        return values[j] + (values[j + 1] - values[j]) * f
    }

    /// 反查单调不减序列：等价 np.interp(s, xs, fs)（xs 为 CDF）
    private static func inverseInterp(_ s: Float, xs: [Float], fs: [Float]) -> Float {
        if s <= xs[0] { return fs[0] }
        let last = xs.count - 1
        if s >= xs[last] { return fs[last] }
        // 二分找第一个 xs[j] >= s
        var lo = 0, hi = last
        while lo + 1 < hi {
            let mid = (lo + hi) / 2
            if xs[mid] < s { lo = mid } else { hi = mid }
        }
        let dx = xs[hi] - xs[lo]
        if dx <= 1e-12 { return fs[hi] }
        let f = (s - xs[lo]) / dx
        return fs[lo] + (fs[hi] - fs[lo]) * f
    }

    // ------------------------------------------------------------------ //
    // 锐化 / 降噪
    // ------------------------------------------------------------------ //

    /// 亮度 unsharp mask：只增强亮度对比，把差值加回三个通道
    private static func applySharpen(_ P: inout [Float],
                                     width: Int, height: Int,
                                     amount: Float, radius: Int) {
        let r = max(1, radius)
        let n = width * height
        let Y = luminancePlane(P, count: n)
        let Yb = boxBlur(Y, width: width, height: height, radius: r)
        P.withUnsafeMutableBufferPointer { buf in
            Y.withUnsafeBufferPointer { y in
                Yb.withUnsafeBufferPointer { yb in
                    for i in 0..<n {
                        let d = amount * (y[i] - yb[i])
                        let idx = i * 3
                        buf[idx]     = min(max(buf[idx] + d, 0), 1)
                        buf[idx + 1] = min(max(buf[idx + 1] + d, 0), 1)
                        buf[idx + 2] = min(max(buf[idx + 2] + d, 0), 1)
                    }
                }
            }
        }
    }

    /// 色度降噪：亮度/色度分离，只模糊色度（同 decast.py chroma_denoise）
    private static func applyChromaDenoise(_ P: inout [Float],
                                           width: Int, height: Int, radius: Int) {
        let n = width * height
        var Y = [Float](repeating: 0, count: n)
        var Pr = [Float](repeating: 0, count: n)   // R - Y
        var Pb = [Float](repeating: 0, count: n)   // B - Y
        P.withUnsafeBufferPointer { buf in
            for i in 0..<n {
                let idx = i * 3
                let r = buf[idx], g = buf[idx + 1], b = buf[idx + 2]
                let y = 0.299 * r + 0.587 * g + 0.114 * b
                Y[i] = y
                Pr[i] = r - y
                Pb[i] = b - y
            }
        }
        Pr = boxBlur(Pr, width: width, height: height, radius: radius)
        Pb = boxBlur(Pb, width: width, height: height, radius: radius)
        P.withUnsafeMutableBufferPointer { buf in
            for i in 0..<n {
                let y = Y[i]
                let r2 = y + Pr[i]
                let b2 = y + Pb[i]
                let g2 = (y - 0.299 * r2 - 0.114 * b2) / 0.587
                let idx = i * 3
                buf[idx]     = min(max(r2, 0), 1)
                buf[idx + 1] = min(max(g2, 0), 1)
                buf[idx + 2] = min(max(b2, 0), 1)
            }
        }
    }

    /// 可分离 box blur（边缘复制填充，滑动窗口 O(n)）
    static func boxBlur(_ src: [Float], width: Int, height: Int, radius: Int) -> [Float] {
        guard radius >= 1 else { return src }
        let k = Float(2 * radius + 1)
        var tmp = [Float](repeating: 0, count: src.count)
        var out = [Float](repeating: 0, count: src.count)

        // 横向
        src.withUnsafeBufferPointer { s in
            tmp.withUnsafeMutableBufferPointer { t in
                for y in 0..<height {
                    let row = y * width
                    var sum: Float = 0
                    for i in -radius...radius {
                        sum += s[row + min(max(i, 0), width - 1)]
                    }
                    t[row] = sum / k
                    for x in 1..<width {
                        sum += s[row + min(x + radius, width - 1)]
                        sum -= s[row + max(x - 1 - radius, 0)]
                        t[row + x] = sum / k
                    }
                }
            }
        }
        // 纵向
        tmp.withUnsafeBufferPointer { t in
            out.withUnsafeMutableBufferPointer { o in
                for x in 0..<width {
                    var sum: Float = 0
                    for i in -radius...radius {
                        sum += t[min(max(i, 0), height - 1) * width + x]
                    }
                    o[x] = sum / k
                    for y in 1..<height {
                        sum += t[min(y + radius, height - 1) * width + x]
                        sum -= t[max(y - 1 - radius, 0) * width + x]
                        o[y * width + x] = sum / k
                    }
                }
            }
        }
        return out
    }

    // ------------------------------------------------------------------ //
    // 自动探测画面区域
    // ------------------------------------------------------------------ //

    /// 探测胶片画面矩形（自动裁切建议）。
    /// 思路：翻拍件的画面区域与片基/背景亮度差异明显，
    /// 在下采样亮度图上比较「中心基准 vs 边缘基准」，
    /// 从四边向内扫描行/列均值，找到跨过中间阈值且持续若干采样的位置。
    /// 输入应为「方向调整后」的图像，返回归一化矩形；探测不到时返回整幅。
    public static func detectFilmRect(_ oriented: LinearImage) -> CropRectN {
        let full = CropRectN(x0: 0, y0: 0, x1: 1, y1: 1)
        let ds = downsample(oriented, maxSide: 512)
        let w = ds.width, h = ds.height
        guard w >= 16, h >= 16 else { return full }

        // 亮度平面 + 行/列均值
        let n = w * h
        let Y = luminancePlane(ds.pixels, count: n)
        var rowMean = [Float](repeating: 0, count: h)
        var colMean = [Float](repeating: 0, count: w)
        Y.withUnsafeBufferPointer { buf in
            for y in 0..<h {
                var s: Float = 0
                let row = y * w
                for x in 0..<w { s += buf[row + x] }
                rowMean[y] = s / Float(w)
            }
            for x in 0..<w {
                var s: Float = 0
                for y in 0..<h { s += buf[y * w + x] }
                colMean[x] = s / Float(h)
            }
        }

        // 边缘基准：最外圈若干行列；中心基准：中央 1/2 区域
        let bw = max(2, w / 40)
        let bh = max(2, h / 40)
        var border: Float = 0
        var bCnt = 0
        for y in 0..<bh { border += rowMean[y] + rowMean[h - 1 - y]; bCnt += 2 }
        for x in 0..<bw { border += colMean[x] + colMean[w - 1 - x]; bCnt += 2 }
        border /= Float(bCnt)

        var center: Float = 0
        var cCnt = 0
        Y.withUnsafeBufferPointer { buf in
            for y in (h / 4)..<(3 * h / 4) {
                let row = y * w
                for x in (w / 4)..<(3 * w / 4) { center += buf[row + x]; cCnt += 1 }
            }
        }
        center /= Float(max(cCnt, 1))

        // 亮度没有明显分界 -> 认为整幅都是画面
        guard abs(center - border) > 0.02 else { return full }
        let thr = 0.5 * (center + border)
        let insideBrighter = center > border

        // 从某端向内扫描：找到第一个「连续 3 个采样在画面一侧」的位置
        func scan(_ profile: [Float], reversed rev: Bool) -> Int {
            let m = profile.count
            var run = 0
            for i in 0..<m {
                let idx = rev ? m - 1 - i : i
                let inside = insideBrighter ? profile[idx] > thr : profile[idx] < thr
                if inside {
                    run += 1
                    if run >= 3 { return i - 2 }   // 连续段的起点（距边缘的偏移）
                } else {
                    run = 0
                }
            }
            return 0
        }

        let top = scan(rowMean, reversed: false)
        let bottom = scan(rowMean, reversed: true)
        let left = scan(colMean, reversed: false)
        let right = scan(colMean, reversed: true)

        // 再往里收 1.5%，避开画面与片基交界的渐变
        let pad = 0.015
        var x0 = Double(left) / Double(w) + pad
        var x1 = 1 - Double(right) / Double(w) - pad
        var y0 = Double(top) / Double(h) + pad
        var y1 = 1 - Double(bottom) / Double(h) - pad
        x0 = min(max(x0, 0), 1); x1 = min(max(x1, 0), 1)
        y0 = min(max(y0, 0), 1); y1 = min(max(y1, 0), 1)

        // 结果太小说明探测失败，退回整幅
        guard x1 - x0 >= 0.2, y1 - y0 >= 0.2 else { return full }
        return CropRectN(x0: x0, y0: y0, x1: x1, y1: y1)
    }

    // ------------------------------------------------------------------ //
    // 显示
    // ------------------------------------------------------------------ //

    /// 生成 8bit sRGB CGImage 供显示。
    /// 注意：develop 的输出已是「显示值」（含 gamma），这里直接量化，不再编码。
    public static func makeCGImage(_ img: LinearImage) -> CGImage? {
        let w = img.width, h = img.height
        let n = w * h
        guard n > 0, img.pixels.count >= n * 3 else { return nil }
        var bytes = [UInt8](repeating: 0, count: n * 3)
        img.pixels.withUnsafeBufferPointer { src in
            bytes.withUnsafeMutableBufferPointer { dst in
                for i in 0..<(n * 3) {
                    let v = min(max(src[i], 0), 1)
                    dst[i] = UInt8(v * 255 + 0.5)
                }
            }
        }
        guard let provider = CGDataProvider(data: Data(bytes) as CFData) else { return nil }
        return CGImage(width: w,
                       height: h,
                       bitsPerComponent: 8,
                       bitsPerPixel: 24,
                       bytesPerRow: w * 3,
                       space: CGColorSpace(name: CGColorSpace.sRGB)!,
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                       provider: provider,
                       decode: nil,
                       shouldInterpolate: true,
                       intent: .defaultIntent)
    }

    // ------------------------------------------------------------------ //
    // 工具函数
    // ------------------------------------------------------------------ //

    /// 统计采样步长（最长边缩到 statsMaxSide 以内）
    private static func statsStep(width: Int, height: Int) -> Int {
        let side = max(width, height)
        return side <= statsMaxSide ? 1 : Int(ceil(Double(side) / Double(statsMaxSide)))
    }

    /// 从交错像素按步长收集三个通道的样本（用于百分位/CDF 统计）
    private static func gatherChannelSamples(_ P: [Float],
                                             width: Int, height: Int,
                                             step: Int) -> [[Float]] {
        let capacity = ((width + step - 1) / step) * ((height + step - 1) / step)
        var r = [Float](); r.reserveCapacity(capacity)
        var g = [Float](); g.reserveCapacity(capacity)
        var b = [Float](); b.reserveCapacity(capacity)
        P.withUnsafeBufferPointer { buf in
            var y = 0
            while y < height {
                let row = y * width
                var x = 0
                while x < width {
                    let idx = (row + x) * 3
                    r.append(buf[idx])
                    g.append(buf[idx + 1])
                    b.append(buf[idx + 2])
                    x += step
                }
                y += step
            }
        }
        return [r, g, b]
    }

    /// 从单通道平面按步长收集样本
    private static func gatherPlaneSamples(_ plane: [Float],
                                           width: Int, height: Int,
                                           step: Int) -> [Float] {
        if step <= 1 { return plane }
        var out = [Float]()
        out.reserveCapacity(((width + step - 1) / step) * ((height + step - 1) / step))
        plane.withUnsafeBufferPointer { buf in
            var y = 0
            while y < height {
                let row = y * width
                var x = 0
                while x < width {
                    out.append(buf[row + x])
                    x += step
                }
                y += step
            }
        }
        return out
    }

    /// 已排序数组的百分位（numpy 'linear' 法：rank = p/100*(n-1) 后线性插值）
    static func percentileSorted(_ sorted: [Float], _ p: Float) -> Float {
        guard !sorted.isEmpty else { return 0 }
        let n = sorted.count
        if n == 1 { return sorted[0] }
        let rank = min(max(p, 0), 100) / 100 * Float(n - 1)
        let lo = Int(rank)
        let hi = min(lo + 1, n - 1)
        let f = rank - Float(lo)
        return sorted[lo] + (sorted[hi] - sorted[lo]) * f
    }

    /// 交错像素的亮度平面（Rec.601 系数，同 Python 版）
    static func luminancePlane(_ P: [Float], count: Int) -> [Float] {
        var Y = [Float](repeating: 0, count: count)
        P.withUnsafeBufferPointer { buf in
            Y.withUnsafeMutableBufferPointer { y in
                for i in 0..<count {
                    let idx = i * 3
                    y[i] = 0.299 * buf[idx] + 0.587 * buf[idx + 1] + 0.114 * buf[idx + 2]
                }
            }
        }
        return Y
    }

    /// 三个通道分别乘系数（vDSP 跨步）
    private static func multiplyChannels(_ P: inout [Float],
                                         scales: [Float], pixelCount: Int) {
        P.withUnsafeMutableBufferPointer { buf in
            for c in 0..<3 {
                var s = scales[c]
                let p = buf.baseAddress! + c
                vDSP_vsmul(p, 3, &s, p, 3, vDSP_Length(pixelCount))
            }
        }
    }

    /// 整体夹到 [0,1]
    private static func clip01(_ P: inout [Float]) {
        var lo: Float = 0
        var hi: Float = 1
        P.withUnsafeMutableBufferPointer { buf in
            vDSP_vclip(buf.baseAddress!, 1, &lo, &hi,
                       buf.baseAddress!, 1, vDSP_Length(buf.count))
        }
    }

    /// 线性 -> sRGB 编码（单值）
    static func srgbEncode(_ v: Float) -> Float {
        if v <= 0.0031308 { return 12.92 * v }
        return 1.055 * powf(v, 1.0 / 2.4) - 0.055
    }
}
