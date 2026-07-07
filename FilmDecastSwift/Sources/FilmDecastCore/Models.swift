//
//  Models.swift —— 去色罩引擎的数据模型
//
//  与 decast.py 的参数语义保持一致：
//    - LinearImage：线性 RGB 图像（交错存储）
//    - CropRectN：归一化裁切矩形（方向调整后的坐标）
//    - DevelopParams：一次「冲洗」所需的全部参数
//    - HistogramReference：直方图匹配参照（--match）
//

import Foundation
import CoreGraphics

/// 线性 RGB 图像：pixels 按 R,G,B 交错存储，长度 = width * height * 3，
/// 值域约 0~1（线性光，未做 gamma 编码）。
public struct LinearImage {
    public var width: Int
    public var height: Int
    public var pixels: [Float]

    public init(width: Int, height: Int, pixels: [Float]) {
        self.width = width
        self.height = height
        self.pixels = pixels
    }

    /// 像素总数（width * height）
    public var pixelCount: Int { width * height }
}

/// 归一化裁切矩形：x0,y0,x1,y1 均为 0~1 比例，
/// 坐标系是「方向调整（旋转/镜像）之后」的图像，所见即所裁。
public struct CropRectN: Codable, Equatable {
    public var x0: Double
    public var y0: Double
    public var x1: Double
    public var y1: Double

    public init(x0: Double, y0: Double, x1: Double, y1: Double) {
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
    }
}

/// 胶片类型（决定反转方式）
public enum FilmMode: String, Codable, CaseIterable {
    /// 彩色负片：每通道密度空间反转（去色罩 + 反转 + 通道白平衡）
    case colorNegative
    /// 黑白负片：亮度密度单通道反转
    case bwNegative
    /// 正片：不反转，仅按亮度百分位做统一线性拉伸
    case positive
}

/// 反转后的白平衡方式
public enum WBMode: String, Codable, CaseIterable {
    /// 灰世界：只用亮度 0.15~0.9 的中间调像素估计
    case grayWorld
    /// 不做白平衡
    case none
}

/// 冲洗参数（全部可编码，便于 UI 持久化 / 预设）
public struct DevelopParams: Codable, Equatable {
    /// 裁切矩形（nil = 不裁切）
    public var cropRect: CropRectN?
    /// 顺时针旋转角度：0 / 90 / 180 / 270
    public var rotate: Int
    /// 水平镜像（在旋转之后应用）
    public var flipH: Bool
    /// 垂直镜像（在旋转之后应用）
    public var flipV: Bool
    /// 自动黑点百分位（去片基/色罩），默认 0.5
    public var blackPct: Double
    /// 自动白点百分位，默认 99.7
    public var whitePct: Double
    /// 胶片类型
    public var mode: FilmMode
    /// 白平衡方式
    public var wb: WBMode
    /// 白平衡取样点（0~1 归一化，方向调整后、裁切前的坐标；
    /// 非 nil 时取该点 11x11 邻域中值做中性化，优先于 wb 模式）
    public var wbPoint: CGPoint?
    /// 输出 gamma（>1 提亮中间调），默认 1.8
    public var gamma: Double
    /// 对比度 S 曲线强度（-1~1），默认 0.08
    public var contrast: Double
    /// 饱和度（<1 降，>1 增），默认 1.0
    public var saturation: Double
    /// 色温（-100 冷 ~ +100 暖），默认 0
    public var temperature: Double
    /// 色调（-100 偏绿 ~ +100 偏品红），默认 0
    public var tint: Double
    /// 色度降噪半径（像素，0 = 关），去彩色颗粒不掉锐度
    public var denoise: Double
    /// 锐化强度（0~3，0 = 关），亮度 unsharp mask
    public var sharpen: Double
    /// 锐化半径（像素），默认 2
    public var sharpenRadius: Double
    /// 是否启用直方图匹配（需要外部提供 HistogramReference；
    /// 启用后覆盖 gamma / 对比度 / 饱和度 / 色温色调）
    public var useMatch: Bool

    public init(cropRect: CropRectN? = nil,
                rotate: Int = 0,
                flipH: Bool = false,
                flipV: Bool = false,
                blackPct: Double = 0.5,
                whitePct: Double = 99.7,
                mode: FilmMode = .colorNegative,
                wb: WBMode = .grayWorld,
                wbPoint: CGPoint? = nil,
                gamma: Double = 1.8,
                contrast: Double = 0.08,
                saturation: Double = 1.0,
                temperature: Double = 0,
                tint: Double = 0,
                denoise: Double = 0,
                sharpen: Double = 0,
                sharpenRadius: Double = 2,
                useMatch: Bool = false) {
        self.cropRect = cropRect
        self.rotate = rotate
        self.flipH = flipH
        self.flipV = flipV
        self.blackPct = blackPct
        self.whitePct = whitePct
        self.mode = mode
        self.wb = wb
        self.wbPoint = wbPoint
        self.gamma = gamma
        self.contrast = contrast
        self.saturation = saturation
        self.temperature = temperature
        self.tint = tint
        self.denoise = denoise
        self.sharpen = sharpen
        self.sharpenRadius = sharpenRadius
        self.useMatch = useMatch
    }

    /// 默认参数（与 decast.py 命令行默认值一致）
    public static let defaults = DevelopParams()
}

/// 直方图匹配参照：由参照图（成品扫描件）建立的每通道 CDF。
/// 用 NegativeEngine.buildHistogramReference(from:) 构建。
public struct HistogramReference {
    /// 每个直方图 bin 的中心值（0~1，共 nbins 个）
    let centers: [Float]
    /// 三个通道各自的归一化 CDF（与 centers 等长，单调不减）
    let cdfs: [[Float]]

    init(centers: [Float], cdfs: [[Float]]) {
        self.centers = centers
        self.cdfs = cdfs
    }
}

/// 引擎错误（中文描述，直接可显示给用户）
public enum EngineError: LocalizedError {
    case loadFailed(String)
    case exportFailed(String)

    public var errorDescription: String? {
        switch self {
        case .loadFailed(let msg):   return "读取失败：\(msg)"
        case .exportFailed(let msg): return "导出失败：\(msg)"
        }
    }
}
