//
//  main.swift —— 核心算法冒烟测试（swift run SmokeTest）
//
//  用 64x64 的合成负片验证 NegativeEngine.develop 的关键性质：
//    1. 彩色负片：已知橙色罩 + 灰阶场景 → 反转后中间调三通道差 < 0.05
//       （每通道密度归一化应同时完成去色罩与通道白平衡）
//    2. 输出亮度沿场景灰阶单调不减（反转 + gamma + S 曲线都不破坏单调性）
//    3. gamma 更大 → 中间调更亮（gamma 方向正确）
//    4. 黑白负片模式：输出严格 R==G==B（即使给了色温/色调/饱和度参数也要跳过）
//
//  任一断言失败即打印 FAIL 并以非零码退出；全部通过打印 PASS。
//

import Foundation
import FilmDecastCore

// ------------------------------------------------------------------------- //
// 断言工具：失败立即退出
// ------------------------------------------------------------------------- //

var checkCount = 0

func check(_ cond: Bool, _ msg: String) {
    checkCount += 1
    if cond {
        print("  ✓ \(msg)")
    } else {
        print("  ✗ 断言失败：\(msg)")
        print("FAIL")
        exit(1)
    }
}

// ------------------------------------------------------------------------- //
// 合成负片：橙色罩 + 灰阶
// ------------------------------------------------------------------------- //

let side = 64
let n = side * side

/// 橙色片基的透过率（R 透得最多、B 最少 —— 典型彩色负片色罩）
let base: [Float] = [0.55, 0.35, 0.18]
/// 场景亮度 -> 负片密度的斜率（模拟胶片 gamma）
let slope: Float = 1.5

/// 场景灰阶：像素 i 的场景亮度 s = i/(n-1)，从 0 到 1 的斜坡
/// 负片透过率 N_c = base_c * 10^(-slope * s)：
/// 场景越亮 → 负片越密 → 透过率越低；色罩即密度空间的每通道固定偏移
func makeNegative() -> LinearImage {
    var pixels = [Float](repeating: 0, count: n * 3)
    for i in 0..<n {
        let s = Float(i) / Float(n - 1)
        let att = powf(10, -slope * s)
        pixels[i * 3]     = base[0] * att
        pixels[i * 3 + 1] = base[1] * att
        pixels[i * 3 + 2] = base[2] * att
    }
    return LinearImage(width: side, height: side, pixels: pixels)
}

/// 像素亮度（Rec.601，与引擎一致）
func luma(_ img: LinearImage, _ i: Int) -> Float {
    let r = img.pixels[i * 3], g = img.pixels[i * 3 + 1], b = img.pixels[i * 3 + 2]
    return 0.299 * r + 0.587 * g + 0.114 * b
}

let negative = makeNegative()

// ------------------------------------------------------------------------- //
// 1) 彩色负片：中间调三通道差 < 0.05（去色罩 + 通道白平衡）
// ------------------------------------------------------------------------- //

print("[1] 彩色负片反转：去色罩后中间调应接近中性")
var pColor = DevelopParams()
pColor.mode = .colorNegative
pColor.wb = .none          // 关掉灰世界，验证纯密度归一化本身就能去色罩
let outColor = NegativeEngine.develop(negative, params: pColor)

check(outColor.width == side && outColor.height == side, "输出尺寸 64x64")

// 取场景亮度 0.3~0.7 的中间调像素，检查三通道最大差
var maxMidDiff: Float = 0
for i in 0..<n {
    let s = Float(i) / Float(n - 1)
    guard s > 0.3 && s < 0.7 else { continue }
    let r = outColor.pixels[i * 3]
    let g = outColor.pixels[i * 3 + 1]
    let b = outColor.pixels[i * 3 + 2]
    maxMidDiff = max(maxMidDiff, max(r, g, b) - min(r, g, b))
}
check(maxMidDiff < 0.05,
      String(format: "中间调三通道最大差 %.5f < 0.05", maxMidDiff))

// ------------------------------------------------------------------------- //
// 2) 输出亮度沿场景灰阶单调不减（反转方向正确 + 影调曲线不破坏单调）
// ------------------------------------------------------------------------- //

print("[2] 单调性：场景越亮 → 正片越亮")
var monotonic = true
var prevY = luma(outColor, 0)
for i in 1..<n {
    let y = luma(outColor, i)
    if y < prevY - 1e-4 { monotonic = false; break }
    prevY = y
}
check(monotonic, "输出亮度沿灰阶单调不减")
check(luma(outColor, 0) < 0.02,
      String(format: "最暗端接近黑（%.4f）", luma(outColor, 0)))
check(luma(outColor, n - 1) > 0.9,
      String(format: "最亮端接近白（%.4f）", luma(outColor, n - 1)))

// ------------------------------------------------------------------------- //
// 3) gamma 方向：gamma 更大 → 中间调更亮
// ------------------------------------------------------------------------- //

print("[3] gamma 方向：gamma 越大中间调越亮")
var pG1 = pColor; pG1.gamma = 1.0; pG1.contrast = 0
var pG2 = pColor; pG2.gamma = 2.2; pG2.contrast = 0
let outG1 = NegativeEngine.develop(negative, params: pG1)
let outG2 = NegativeEngine.develop(negative, params: pG2)
let mid = n / 2
let y1 = luma(outG1, mid)
let y2 = luma(outG2, mid)
check(y2 > y1 + 0.05,
      String(format: "中间调亮度 gamma2.2=%.4f > gamma1.0=%.4f", y2, y1))

// ------------------------------------------------------------------------- //
// 4) 黑白负片模式：输出严格 R==G==B（色温/色调/饱和度都必须被跳过）
// ------------------------------------------------------------------------- //

print("[4] 黑白模式：输出必须严格 R==G==B")
var pBW = DevelopParams()
pBW.mode = .bwNegative
pBW.temperature = 50       // 故意给非零色温/色调/饱和度/降噪，验证 bw 模式跳过它们
pBW.tint = -30
pBW.saturation = 1.5
pBW.denoise = 2
let outBW = NegativeEngine.develop(negative, params: pBW)
var maxBWDiff: Float = 0
for i in 0..<n {
    let r = outBW.pixels[i * 3]
    let g = outBW.pixels[i * 3 + 1]
    let b = outBW.pixels[i * 3 + 2]
    maxBWDiff = max(maxBWDiff, max(r, g, b) - min(r, g, b))
}
check(maxBWDiff < 1e-6,
      String(format: "黑白输出三通道最大差 %.2e（应为 0）", maxBWDiff))

// ------------------------------------------------------------------------- //
// 5) 精调：曝光提亮 / 晕影压暗亮角 / 黑白仍严格 R==G==B
// ------------------------------------------------------------------------- //

func meanLuma(_ img: LinearImage) -> Float {
    var s: Float = 0
    for i in 0..<(img.width * img.height) { s += luma(img, i) }
    return s / Float(img.width * img.height)
}

print("[5] 精调：曝光 / 晕影 / 白黑场")

var pExp = pColor; pExp.exposure = 1.0
let outExp = NegativeEngine.develop(negative, params: pExp)
let midE0 = luma(outColor, n / 2)
let midE1 = luma(outExp, n / 2)
check(midE1 > midE0 + 0.05,
      String(format: "曝光 +1EV 提亮中间调（%.4f > %.4f）", midE1, midE0))

var pVig = pColor; pVig.vignette = -100
let outVig = NegativeEngine.develop(negative, params: pVig)
let cornerBase = luma(outColor, n - 1)   // 右下角亮点
let cornerVig = luma(outVig, n - 1)
check(cornerVig < cornerBase - 0.3,
      String(format: "晕影 -100 明显压暗亮角（%.4f < %.4f）", cornerVig, cornerBase))

var pBWFine = DevelopParams()
pBWFine.mode = .bwNegative
pBWFine.exposure = 0.8; pBWFine.highlights = 40; pBWFine.shadows = -20
pBWFine.whites = 15; pBWFine.blacks = 10; pBWFine.vignette = -50
let outBWFine = NegativeEngine.develop(negative, params: pBWFine)
var maxBWFineDiff: Float = 0
for i in 0..<n {
    let r = outBWFine.pixels[i * 3], g = outBWFine.pixels[i * 3 + 1], b = outBWFine.pixels[i * 3 + 2]
    maxBWFineDiff = max(maxBWFineDiff, max(r, g, b) - min(r, g, b))
}
check(maxBWFineDiff < 1e-5,
      String(format: "黑白 + 精调后仍严格 R==G==B（%.2e）", maxBWFineDiff))

// ------------------------------------------------------------------------- //
// 6) 引导取样：暗部框取「亮场」→ 黑点抬高 → 整体压暗
// ------------------------------------------------------------------------- //

print("[6] 引导取样：shadowRect 覆盖各通道黑点")
var pGuide = pColor
pGuide.shadowRect = CropRectN(x0: 0.9, y0: 0.9, x1: 1.0, y1: 1.0)  // 右下=最亮场（高密度）
let outGuide = NegativeEngine.develop(negative, params: pGuide)
let mBase = meanLuma(outColor)
let mGuide = meanLuma(outGuide)
check(mGuide < mBase - 0.1,
      String(format: "shadowRect 取亮场把黑点抬高，整体明显压暗（%.4f < %.4f）", mGuide, mBase))

// ------------------------------------------------------------------------- //

print("共 \(checkCount) 项断言全部通过")
print("PASS")
