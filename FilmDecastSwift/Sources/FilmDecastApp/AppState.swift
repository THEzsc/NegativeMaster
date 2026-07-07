//
//  AppState.swift —— 应用状态与渲染调度
//
//  职责：
//    - 文件夹扫描 / 文件列表 / 勾选集合（批量导出用）
//    - 载入图像：全分辨率 + 1500px 预览各留一份（只留当前一张，控内存）
//    - 冲洗参数（DevelopParams）随图记忆到 UserDefaults（key = 文件路径）
//    - 防抖渲染：参数变化 150ms 后取消旧任务、后台 develop 预览
//    - 预览合成：整幅（方向后）渲染做背景，裁切框内贴「真裁切」的渲染结果，
//      框内颜色与导出完全一致（对应 Python 版 stats_rect 的所见即所得）
//    - 白点取样 / 参照匹配 / 自动画面探测 / 导出（单张 + 批量）
//

import SwiftUI
import AppKit
import UniformTypeIdentifiers
import FilmDecastCore

// ------------------------------------------------------------------------- //
// 界面用的小枚举
// ------------------------------------------------------------------------- //

/// 裁切画幅（比例锁定；数值为「长边/短边」）
enum CropFormat: String, CaseIterable, Identifiable {
    case free = "自由"
    case f135 = "135"
    case f645 = "645"
    case f66  = "6×6"
    case f67  = "6×7"
    case f69  = "6×9"

    var id: String { rawValue }

    /// 长边/短边 比例（nil = 自由）
    var ratio: Double? {
        switch self {
        case .free: return nil
        case .f135: return 3.0 / 2.0
        case .f645: return 4.0 / 3.0
        case .f66:  return 1.0
        case .f67:  return 5.0 / 4.0
        case .f69:  return 3.0 / 2.0
        }
    }
}

/// 导出格式（界面选择用，导出时转成 ImageExporter 的 ExportFormat）
enum ExportFileFormat: String, CaseIterable, Identifiable {
    case tiff16
    case jpeg

    var id: String { rawValue }
    var label: String { self == .tiff16 ? "TIF 16bit" : "JPG" }
    var ext: String { self == .tiff16 ? "tif" : "jpg" }
}

// ------------------------------------------------------------------------- //
// 应用状态
// ------------------------------------------------------------------------- //

@MainActor
final class AppState: ObservableObject {

    // ------------------------- 文件浏览 ------------------------- //

    /// 支持的文件扩展名（与 Python 版一致）
    nonisolated static let fileExtensions: Set<String> = [
        "arw", "arq", "cr2", "cr3", "nef", "raf", "dng", "rw2",
        "tif", "tiff", "jpg", "jpeg", "png"
    ]

    @Published var folderURL: URL?
    @Published var allFiles: [URL] = []
    @Published var filterText = ""
    @Published private(set) var selectedFile: URL?
    /// 勾选集合（批量导出）
    @Published var checkedFiles: Set<URL> = []

    var filteredFiles: [URL] {
        guard !filterText.isEmpty else { return allFiles }
        return allFiles.filter {
            $0.lastPathComponent.localizedCaseInsensitiveContains(filterText)
        }
    }

    // ------------------------- 图像缓存 ------------------------- //

    /// 全分辨率线性图（只留当前一张，导出用）
    private var fullImage: LinearImage?
    /// 1500px 预览线性图（实时渲染用）
    private var previewImage: LinearImage?
    /// 预览/全图 的边长比例（去噪半径等按此缩放）
    private var previewScale: Double = 1.0
    /// 原图像素尺寸（未做方向调整）
    @Published private(set) var fullPixelSize = CGSize.zero

    // ------------------------- 渲染结果 ------------------------- //

    @Published private(set) var displayCG: CGImage?
    @Published private(set) var negativeCG: CGImage?
    /// 按住「看负片」时为 true
    @Published private(set) var showNegative = false
    /// 直方图（3 通道 x 64 bin，已归一化到 0~1）
    @Published private(set) var histogram: [[Float]] = [[], [], []]
    @Published private(set) var isLoading = false
    @Published private(set) var isRendering = false
    @Published var statusText = "打开文件夹并选择一张底片"

    /// 负片预览缓存标识（文件 + 方向变了要重算）
    private var negativeToken = ""

    // ------------------------- 冲洗参数 ------------------------- //

    @Published var params: DevelopParams = AppState.initialParams() {
        didSet {
            guard !suppressSideEffects else { return }
            persistParams()
            scheduleRender()
        }
    }
    /// 程序内部批量改状态时置 true，避免 didSet 连锁触发
    private var suppressSideEffects = false

    /// 画幅比例锁定
    @Published var cropFormat: CropFormat = .free {
        didSet {
            guard !suppressSideEffects else { return }
            applyCropFormat()
        }
    }
    /// 横幅（false = 竖幅）
    @Published var cropLandscape = true {
        didSet {
            guard !suppressSideEffects else { return }
            applyCropFormat()
        }
    }
    /// 「取白点」模式：开启后点击预览采样
    @Published var wbPicking = false

    // ------------------------- 参照匹配 ------------------------- //

    @Published private(set) var matchRefURL: URL?
    @Published private(set) var matchRefLoaded = false
    private var matchRef: HistogramReference?

    // ------------------------- 导出 ------------------------- //

    @Published var exportFormat: ExportFileFormat = .tiff16
    @Published var jpegQuality: Double = 0.92
    /// 导出长边缩小（0 = 原尺寸）
    @Published var resizeLongEdge: Int = 0
    @Published private(set) var isExporting = false
    /// 批量导出进度（nil = 未在批量导出）
    @Published private(set) var batchProgress: Double?

    /// 长边缩小的可选项
    static let resizeOptions: [Int] = [0, 1600, 2048, 3000, 4096, 6000]

    // ------------------------- 内部任务 ------------------------- //

    private var loadTask: Task<Void, Never>?
    private var renderTask: Task<Void, Never>?

    // --------------------------------------------------------------------- //
    // 默认参数 / 参数记忆
    // --------------------------------------------------------------------- //

    /// 默认参数：引擎默认 + 初始裁切框 6%~94%（同 Python 版）
    nonisolated static func initialParams() -> DevelopParams {
        var p = DevelopParams.defaults
        p.cropRect = CropRectN(x0: 0.06, y0: 0.06, x1: 0.94, y1: 0.94)
        return p
    }

    nonisolated private static func paramsKey(for url: URL) -> String {
        "FilmDecastParams::" + url.path
    }

    /// 读回某个文件保存过的参数（没有则 nil）
    nonisolated static func savedParams(for url: URL) -> DevelopParams? {
        guard let data = UserDefaults.standard.data(forKey: paramsKey(for: url)) else {
            return nil
        }
        return try? JSONDecoder().decode(DevelopParams.self, from: data)
    }

    private func persistParams() {
        guard let url = selectedFile else { return }
        if let data = try? JSONEncoder().encode(params) {
            UserDefaults.standard.set(data, forKey: Self.paramsKey(for: url))
        }
    }

    /// 恢复默认参数（当前图）
    func resetParams() {
        suppressSideEffects = true
        cropFormat = .free
        cropLandscape = true
        wbPicking = false
        suppressSideEffects = false
        params = Self.initialParams()   // didSet -> 持久化 + 渲染
        statusText = "已恢复默认参数"
    }

    // --------------------------------------------------------------------- //
    // 文件夹扫描 / 选择
    // --------------------------------------------------------------------- //

    /// 「打开文件夹」：递归列出支持的底片文件
    func openFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "选择"
        panel.message = "选择包含底片的文件夹（递归扫描）"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        folderURL = url
        scanFolder(url)
    }

    /// 递归收集目录下支持的底片文件（同步函数，供后台任务调用）
    nonisolated private static func collectFiles(in dir: URL) -> [URL] {
        var out: [URL] = []
        let keys: [URLResourceKey] = [.isRegularFileKey]
        if let en = FileManager.default.enumerator(
            at: dir, includingPropertiesForKeys: keys,
            options: [.skipsHiddenFiles, .skipsPackageDescendants]) {
            for case let u as URL in en {
                if fileExtensions.contains(u.pathExtension.lowercased()) {
                    out.append(u)
                    if out.count >= 3000 { break }   // 防止超大目录卡死
                }
            }
        }
        return out.sorted {
            $0.path.localizedStandardCompare($1.path) == .orderedAscending
        }
    }

    private func scanFolder(_ dir: URL) {
        statusText = "扫描文件夹…"
        Task { [weak self] in
            let found = await Task.detached(priority: .userInitiated) {
                AppState.collectFiles(in: dir)
            }.value
            guard let self else { return }
            self.allFiles = found
            self.checkedFiles.removeAll()
            self.statusText = "共 \(found.count) 个文件，点击载入"
        }
    }

    /// 单选载入一张
    func select(_ url: URL) {
        if url == selectedFile && fullImage != nil { return }
        selectedFile = url
        loadFile(url)
    }

    /// 勾选当前过滤结果里的全部文件
    func checkAllFiltered() {
        checkedFiles.formUnion(filteredFiles)
    }

    // --------------------------------------------------------------------- //
    // 载入
    // --------------------------------------------------------------------- //

    private func loadFile(_ url: URL) {
        loadTask?.cancel()
        renderTask?.cancel()
        isLoading = true
        isRendering = false
        statusText = "解码中… \(url.lastPathComponent)"
        // 先释放上一张，控内存
        fullImage = nil
        previewImage = nil
        displayCG = nil
        negativeCG = nil
        negativeToken = ""
        showNegative = false
        wbPicking = false

        loadTask = Task { [weak self] in
            let result = await Task.detached(priority: .userInitiated)
            { () -> Result<(LinearImage, LinearImage), Error> in
                do {
                    let full = try NegativeEngine.load(url: url)
                    let prev = NegativeEngine.downsample(full, maxSide: 1500)
                    return .success((full, prev))
                } catch {
                    return .failure(error)
                }
            }.value
            guard let self, !Task.isCancelled, self.selectedFile == url else { return }
            self.isLoading = false
            switch result {
            case .failure(let err):
                self.statusText = "✗ " + err.localizedDescription
            case .success(let (full, prev)):
                self.fullImage = full
                self.previewImage = prev
                self.previewScale = Double(max(prev.width, prev.height))
                                  / Double(max(full.width, full.height))
                self.fullPixelSize = CGSize(width: full.width, height: full.height)
                // 恢复该图记忆的参数；没有则默认
                self.suppressSideEffects = true
                self.params = Self.savedParams(for: url) ?? Self.initialParams()
                self.cropFormat = .free
                self.suppressSideEffects = false
                self.statusText = "\(url.lastPathComponent) · \(full.width)×\(full.height)"
                self.scheduleRender(debounceNanos: 0)
            }
        }
    }

    // --------------------------------------------------------------------- //
    // 渲染调度（防抖）
    // --------------------------------------------------------------------- //

    /// 参数变化后调用：取消旧渲染，防抖 150ms 再后台 develop 预览
    func scheduleRender(debounceNanos: UInt64 = 150_000_000) {
        renderTask?.cancel()
        guard let prev = previewImage else { return }
        let p = params
        let scale = previewScale
        let ref = (p.useMatch && matchRefLoaded) ? matchRef : nil
        isRendering = true
        renderTask = Task { [weak self] in
            if debounceNanos > 0 {
                try? await Task.sleep(nanoseconds: debounceNanos)
            }
            if Task.isCancelled { return }
            let result = await Task.detached(priority: .userInitiated) {
                PreviewRenderer.renderPreview(prev, params: p, scale: scale, ref: ref)
            }.value
            guard let self, !Task.isCancelled else { return }
            self.displayCG = result.image
            self.histogram = result.histogram
            self.isRendering = false
        }
    }

    // --------------------------------------------------------------------- //
    // 「看负片」：按住显示未反转的负片原图（仅方向 + 2.2 gamma 编码）
    // --------------------------------------------------------------------- //

    func setNegativePressed(_ pressed: Bool) {
        showNegative = pressed
        guard pressed, let prev = previewImage else { return }
        let token = "\(selectedFile?.path ?? "")|\(params.rotate)|\(params.flipH)|\(params.flipV)"
        if token == negativeToken && negativeCG != nil { return }
        let p = params
        Task { [weak self] in
            let cg = await Task.detached(priority: .userInitiated) {
                PreviewRenderer.negativeImage(prev, rotate: p.rotate,
                                              flipH: p.flipH, flipV: p.flipV)
            }.value
            guard let self else { return }
            self.negativeCG = cg
            self.negativeToken = token
        }
    }

    // --------------------------------------------------------------------- //
    // 方向
    // --------------------------------------------------------------------- //

    func rotateLeft() {
        params.rotate = (params.rotate + 270) % 360
        if cropFormat != .free { applyCropFormat() }
    }

    func rotateRight() {
        params.rotate = (params.rotate + 90) % 360
        if cropFormat != .free { applyCropFormat() }
    }

    // --------------------------------------------------------------------- //
    // 裁切
    // --------------------------------------------------------------------- //

    /// 方向调整后的整幅像素尺寸（裁切标注 / 比例换算用）
    var orientedFullSize: CGSize {
        let s = fullPixelSize
        return params.rotate % 180 == 0 ? s : CGSize(width: s.height, height: s.width)
    }

    /// 锁定画幅换算成「归一化坐标里的宽/高比」（nil = 自由）
    var cropAspectNormalized: Double? {
        guard let ratio = cropFormat.ratio else { return nil }
        let aspect = cropLandscape ? ratio : 1.0 / ratio
        let s = orientedFullSize
        guard s.width > 0, s.height > 0 else { return nil }
        return aspect / (Double(s.width) / Double(s.height))
    }

    /// 裁切框拖动结束：写回参数（触发防抖渲染 + 持久化）
    func commitCrop(_ rect: CropRectN) {
        params.cropRect = rect
    }

    /// 把当前裁切框调整到锁定比例（居中收缩/扩展，同 Python 版 applyFormat）
    func applyCropFormat() {
        guard let r = cropAspectNormalized else { return }   // 自由：不动
        var rect = params.cropRect ?? CropRectN(x0: 0, y0: 0, x1: 1, y1: 1)
        let cx = (rect.x0 + rect.x1) / 2
        let cy = (rect.y0 + rect.y1) / 2
        var h = rect.y1 - rect.y0
        var w = h * r
        if w > 1 { w = 1; h = w / r }
        if h > 1 { h = 1; w = h * r }
        let x0 = min(max(cx - w / 2, 0), 1 - w)
        let y0 = min(max(cy - h / 2, 0), 1 - h)
        rect = CropRectN(x0: x0, y0: y0, x1: x0 + w, y1: y0 + h)
        params.cropRect = rect
    }

    /// 裁切框占满整幅
    func cropFull() {
        params.cropRect = CropRectN(x0: 0, y0: 0, x1: 1, y1: 1)
        if cropFormat != .free { applyCropFormat() }
    }

    /// 重置裁切框到 6%~94%
    func cropReset() {
        params.cropRect = CropRectN(x0: 0.06, y0: 0.06, x1: 0.94, y1: 0.94)
        if cropFormat != .free { applyCropFormat() }
    }

    /// 自动探测画面区域（detectFilmRect，输入是方向后的预览）
    func autoDetectCrop() {
        guard let prev = previewImage else { return }
        let p = params
        statusText = "探测画面区域…"
        Task { [weak self] in
            let rect = await Task.detached(priority: .userInitiated) { () -> CropRectN in
                let oriented = PreviewRenderer.orient(prev, rotate: p.rotate,
                                                      flipH: p.flipH, flipV: p.flipV)
                return NegativeEngine.detectFilmRect(oriented)
            }.value
            guard let self else { return }
            self.suppressSideEffects = true
            self.cropFormat = .free
            self.suppressSideEffects = false
            self.params.cropRect = rect
            self.statusText = "已应用自动画面探测"
        }
    }

    // --------------------------------------------------------------------- //
    // 白点取样
    // --------------------------------------------------------------------- //

    /// 点击预览取白点（norm 是方向后、裁切前的 0~1 坐标，正合引擎语义）
    func pickWhitePoint(atNormalized pt: CGPoint) {
        wbPicking = false
        params.wbPoint = pt
        statusText = String(format: "白点取样：(%.3f, %.3f)", pt.x, pt.y)
    }

    func clearWhitePoint() {
        guard params.wbPoint != nil else { return }
        params.wbPoint = nil
        statusText = "已清除白点取样"
    }

    // --------------------------------------------------------------------- //
    // 参照匹配
    // --------------------------------------------------------------------- //

    var matchRefName: String? { matchRefURL?.lastPathComponent }

    /// 选择参照扫描件并建立直方图 CDF
    func chooseMatchReference() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.message = "选择参照扫描件（同一张 / 同卷的成品正片）"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        matchRefURL = url
        matchRefLoaded = false
        statusText = "参照解码中… \(url.lastPathComponent)"
        Task { [weak self] in
            let ref = await Task.detached(priority: .userInitiated)
            { () -> HistogramReference? in
                guard let img = try? NegativeEngine.load(url: url) else { return nil }
                return NegativeEngine.buildHistogramReference(from: img)
            }.value
            guard let self, self.matchRefURL == url else { return }
            if let ref {
                self.matchRef = ref
                self.matchRefLoaded = true
                self.statusText = "✓ 参照已载入：\(url.lastPathComponent)"
                if self.params.useMatch { self.scheduleRender(debounceNanos: 0) }
            } else {
                self.matchRefURL = nil
                self.statusText = "✗ 参照读取失败"
            }
        }
    }

    func clearMatchReference() {
        matchRef = nil
        matchRefURL = nil
        matchRefLoaded = false
        if params.useMatch {
            params.useMatch = false   // didSet -> 重渲染
        }
        statusText = "已清除参照"
    }

    // --------------------------------------------------------------------- //
    // 导出
    // --------------------------------------------------------------------- //

    private var exporterFormat: ExportFormat {
        exportFormat == .tiff16 ? .tiff16 : .jpeg(quality: jpegQuality)
    }

    /// 导出当前图（全分辨率，NSSavePanel 选路径）
    func exportCurrent() {
        guard let full = fullImage, let src = selectedFile else {
            statusText = "先载入图片"
            return
        }
        let panel = NSSavePanel()
        panel.title = "导出当前图像"
        panel.nameFieldStringValue =
            src.deletingPathExtension().lastPathComponent + "_pos." + exportFormat.ext
        panel.allowedContentTypes = [exportFormat == .tiff16 ? UTType.tiff : UTType.jpeg]
        panel.directoryURL = src.deletingLastPathComponent()
        guard panel.runModal() == .OK, let out = panel.url else { return }

        let p = params
        let ref = (p.useMatch && matchRefLoaded) ? matchRef : nil
        let fmt = exporterFormat
        let resize = resizeLongEdge
        isExporting = true
        statusText = "导出中（全分辨率）…"
        Task { [weak self] in
            let errMsg = await Task.detached(priority: .userInitiated) { () -> String? in
                // 导出用原始 denoise / sharpenRadius（预览时才按比例缩小）
                let dev = NegativeEngine.develop(full, params: p, matchRef: ref)
                do {
                    try ImageExporter.save(dev, to: out, format: fmt,
                                           resizeLongEdge: resize)
                    return nil
                } catch {
                    return error.localizedDescription
                }
            }.value
            guard let self else { return }
            self.isExporting = false
            self.statusText = errMsg.map { "✗ " + $0 } ?? "✓ 已导出：\(out.path)"
        }
    }

    /// 批量导出勾选的文件到选定目录。
    /// 每张用其记忆参数（当前打开的这张用当前参数；没记忆的用默认参数）。
    func exportChecked() {
        let files = checkedFiles.sorted {
            $0.path.localizedStandardCompare($1.path) == .orderedAscending
        }
        guard !files.isEmpty else {
            statusText = "请先在左侧勾选要批量导出的文件"
            return
        }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "导出到此"
        panel.message = "选择批量导出的目标文件夹"
        guard panel.runModal() == .OK, let dir = panel.url else { return }

        // 主线程先把每张的参数定下来
        let jobs: [(URL, DevelopParams)] = files.map { url in
            let p: DevelopParams
            if url == selectedFile {
                p = params
            } else {
                p = Self.savedParams(for: url) ?? Self.initialParams()
            }
            return (url, p)
        }
        let ref = matchRefLoaded ? matchRef : nil
        let fmt = exporterFormat
        let ext = exportFormat.ext
        let resize = resizeLongEdge

        isExporting = true
        batchProgress = 0
        statusText = "批量导出 0/\(jobs.count)"
        Task { [weak self] in
            var done = 0
            var failed = 0
            for (url, p) in jobs {
                let out = dir.appendingPathComponent(
                    url.deletingPathExtension().lastPathComponent + "_pos." + ext)
                let ok = await Task.detached(priority: .utility) { () -> Bool in
                    guard let img = try? NegativeEngine.load(url: url) else { return false }
                    let dev = NegativeEngine.develop(img, params: p,
                                                     matchRef: p.useMatch ? ref : nil)
                    return (try? ImageExporter.save(dev, to: out, format: fmt,
                                                    resizeLongEdge: resize)) != nil
                }.value
                done += 1
                if !ok { failed += 1 }
                guard let self else { return }
                self.batchProgress = Double(done) / Double(jobs.count)
                self.statusText = "批量导出 \(done)/\(jobs.count)"
                    + (failed > 0 ? "（失败 \(failed)）" : "")
            }
            guard let self else { return }
            self.batchProgress = nil
            self.isExporting = false
            self.statusText = failed == 0
                ? "✓ 批量导出完成（\(done) 张）→ \(dir.path)"
                : "批量导出结束：成功 \(done - failed)，失败 \(failed)"
        }
    }
}

// ------------------------------------------------------------------------- //
// PreviewRenderer —— 纯计算辅助（不隔离到主线程，供 Task.detached 调用）
// ------------------------------------------------------------------------- //

enum PreviewRenderer {

    /// 预览渲染：
    ///   1. 整幅（方向后、不裁切）develop 一遍做背景；
    ///   2. 裁切框不是满幅时，再按真裁切 develop 一遍，贴回背景对应位置——
    ///      框内像素与最终导出完全一致（等价 Python 版 stats_rect）；
    ///   3. 直方图从框内结果统计。
    /// denoise / sharpenRadius 按 预览/全图 边长比例缩小，效果才有代表性。
    static func renderPreview(_ prev: LinearImage,
                              params: DevelopParams,
                              scale: Double,
                              ref: HistogramReference?)
        -> (image: CGImage?, histogram: [[Float]]) {
        var p = params
        if p.denoise > 0 {
            p.denoise = max(0, (p.denoise * scale).rounded())
        }
        if p.sharpen > 1e-3 {
            p.sharpenRadius = max(1, (p.sharpenRadius * scale).rounded())
        }
        var pFull = p
        pFull.cropRect = nil
        let full = NegativeEngine.develop(prev, params: pFull, matchRef: ref)
        var composite = full
        var histSource = full
        if let rect = p.cropRect, !isFullRect(rect) {
            let cropped = NegativeEngine.develop(prev, params: p, matchRef: ref)
            let (xa, ya, _, _) = rectPixels(rect, width: full.width, height: full.height)
            paste(cropped, into: &composite, x: xa, y: ya)
            histSource = cropped
        }
        return (NegativeEngine.makeCGImage(composite),
                histogramBins(histSource, bins: 64))
    }

    /// 负片原图预览：只做方向调整 + 2.2 gamma 编码（不反转、不去色罩）
    static func negativeImage(_ prev: LinearImage, rotate: Int,
                              flipH: Bool, flipV: Bool) -> CGImage? {
        var img = orient(prev, rotate: rotate, flipH: flipH, flipV: flipV)
        let inv: Float = 1.0 / 2.2
        img.pixels.withUnsafeMutableBufferPointer { buf in
            for i in 0..<buf.count {
                buf[i] = powf(max(buf[i], 0), inv)
            }
        }
        return NegativeEngine.makeCGImage(img)
    }

    /// 是否接近满幅（满幅时预览不必二次渲染）
    static func isFullRect(_ r: CropRectN) -> Bool {
        min(r.x0, r.x1) <= 0.001 && min(r.y0, r.y1) <= 0.001
            && max(r.x0, r.x1) >= 0.999 && max(r.y0, r.y1) >= 0.999
    }

    /// 归一化矩形 -> 像素矩形（与引擎内部同一套公式，保证贴图对位）
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

    /// 把 src 整块贴进 dst 的 (x, y) 位置（越界则跳过，保护性检查）
    static func paste(_ src: LinearImage, into dst: inout LinearImage, x: Int, y: Int) {
        guard x >= 0, y >= 0,
              x + src.width <= dst.width, y + src.height <= dst.height else { return }
        let rowLen = src.width * 3
        for row in 0..<src.height {
            let s = row * rowLen
            let d = ((y + row) * dst.width + x) * 3
            dst.pixels.replaceSubrange(d..<(d + rowLen),
                                       with: src.pixels[s..<(s + rowLen)])
        }
    }

    /// 3 通道直方图（bins 个桶，按三通道共用最大值归一化到 0~1）
    static func histogramBins(_ img: LinearImage, bins: Int) -> [[Float]] {
        let n = img.pixelCount
        guard n > 0, bins > 1 else { return [[], [], []] }
        let step = max(1, n / 250_000)   // 最多采 25 万像素，足够画直方图
        var hist = [[Float]](repeating: [Float](repeating: 0, count: bins), count: 3)
        img.pixels.withUnsafeBufferPointer { buf in
            var i = 0
            while i < n {
                let idx = i * 3
                for c in 0..<3 {
                    let v = min(max(buf[idx + c], 0), 1)
                    var b = Int(v * Float(bins))
                    if b >= bins { b = bins - 1 }
                    hist[c][b] += 1
                }
                i += step
            }
        }
        let m = max(hist[0].max() ?? 1, hist[1].max() ?? 1, hist[2].max() ?? 1, 1)
        for c in 0..<3 {
            for b in 0..<bins { hist[c][b] /= m }
        }
        return hist
    }

    // ------------------------- 方向调整（与引擎语义一致） ------------------------- //

    /// 旋转（顺时针 0/90/180/270）+ 镜像（引擎的 orient 未公开，这里同构实现）
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
}
