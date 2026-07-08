//
//  ContentView.swift —— 主界面布局
//
//  三栏：左侧文件列表 / 中间预览（含裁切框与白点取样）/ 右侧控制面板。
//

import SwiftUI
import FilmDecastCore

struct ContentView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        HSplitView {
            SidebarView()
                .frame(minWidth: 210, idealWidth: 250, maxWidth: 340)
            PreviewView()
                .frame(minWidth: 420, maxWidth: .infinity,
                       minHeight: 400, maxHeight: .infinity)
            ControlsView()
                .frame(minWidth: 300, idealWidth: 330, maxWidth: 380)
        }
    }
}

// ------------------------------------------------------------------------- //
// 左侧栏：打开文件夹 / 过滤 / 文件列表（单选载入 + 勾选批量）
// ------------------------------------------------------------------------- //

struct SidebarView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Button("打开文件夹…") { state.openFolder() }
                Spacer()
            }
            if let dir = state.folderURL {
                Text(dir.path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.head)
                    .help(dir.path)
            }
            TextField("过滤文件名…", text: $state.filterText)
                .textFieldStyle(.roundedBorder)

            List {
                ForEach(state.filteredFiles, id: \.self) { url in
                    fileRow(url)
                }
            }
            .listStyle(.inset)

            HStack(spacing: 6) {
                Button("全选") { state.checkAllFiltered() }
                    .controlSize(.small)
                    .help("勾选当前列表中的全部文件（批量导出用）")
                Button("清空勾选") { state.checkedFiles.removeAll() }
                    .controlSize(.small)
                Spacer()
                Text("勾选 \(state.checkedFiles.count)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(8)
    }

    private func fileRow(_ url: URL) -> some View {
        HStack(spacing: 6) {
            Toggle("", isOn: checkedBinding(url))
                .toggleStyle(.checkbox)
                .labelsHidden()
                .help("勾选后可批量导出")
            Text(url.lastPathComponent)
                .font(.system(size: 12))
                .lineLimit(1)
                .truncationMode(.middle)
                .help(url.path)
            Spacer(minLength: 0)
        }
        .contentShape(Rectangle())
        .onTapGesture { state.select(url) }
        .listRowBackground(
            RoundedRectangle(cornerRadius: 4)
                .fill(url == state.selectedFile
                      ? Color.accentColor.opacity(0.22) : Color.clear)
        )
    }

    private func checkedBinding(_ url: URL) -> Binding<Bool> {
        Binding(
            get: { state.checkedFiles.contains(url) },
            set: { on in
                if on { state.checkedFiles.insert(url) }
                else { state.checkedFiles.remove(url) }
            })
    }
}

// ------------------------------------------------------------------------- //
// 中间预览：适合窗口显示 + 裁切框 + 白点取样 + 「按住看负片」
// ------------------------------------------------------------------------- //

struct PreviewView: View {
    @EnvironmentObject var state: AppState
    @State private var wbDragStart: CGPoint?
    @State private var wbDragCurrent: CGPoint?

    /// 当前应显示的图（按住看负片时切到负片原图）
    private var currentImage: CGImage? {
        state.showNegative ? (state.negativeCG ?? state.displayCG) : state.displayCG
    }

    var body: some View {
        VStack(spacing: 0) {
            GeometryReader { geo in
                ZStack {
                    Color(nsColor: .underPageBackgroundColor)
                    if let cg = currentImage {
                        imageArea(cg, in: geo.size)
                    } else {
                        placeholder
                    }
                }
            }
            statusBar
        }
    }

    /// 适合窗口的图像区（含裁切框 / 白点标记 / 取样点击层）
    @ViewBuilder
    private func imageArea(_ cg: CGImage, in avail: CGSize) -> some View {
        let iw = CGFloat(cg.width)
        let ih = CGFloat(cg.height)
        let maxW = max(avail.width - 24, 50)
        let maxH = max(avail.height - 24, 50)
        let s = min(maxW / iw, maxH / ih)
        let fw = iw * s
        let fh = ih * s

        ZStack {
            Image(decorative: cg, scale: 1)
                .resizable()
                .interpolation(.medium)
                .frame(width: fw, height: fh)

            // 取样框（白平衡 / 片基 / 暗部 / 亮部）——已设的框各用一种颜色标注
            if !state.showNegative {
                sampleRectOverlays(fw: fw, fh: fh)
                // 正在拖动中的框：用当前取样模式的颜色实时预览
                if let rect = liveDragRect {
                    sampleRect(rect, color: state.pickMode.overlayColor, fw: fw, fh: fh)
                }
                if let p = state.params.wbPoint,
                   state.params.wbRect == nil, state.pickMode == .none {
                    Circle()
                        .stroke(Color.yellow, lineWidth: 1.5)
                        .frame(width: 14, height: 14)
                        .position(x: p.x * fw, y: p.y * fh)
                        .allowsHitTesting(false)
                }
            }

            // 裁切框（看负片时隐藏，取样时不拦截点击）
            if !state.showNegative, let rect = state.params.cropRect {
                CropOverlayView(rect: rect,
                                normalizedAspect: state.cropAspectNormalized,
                                pixelSize: state.orientedFullSize) { newRect in
                    state.commitCrop(newRect)
                }
                .allowsHitTesting(state.pickMode == .none)
            }

            if state.pickMode != .none && !state.showNegative {
                Rectangle()
                    .fill(Color.clear)
                    .contentShape(Rectangle())
                    .gesture(whiteRectGesture(width: fw, height: fh))
            }
        }
        .frame(width: fw, height: fh)
        .position(x: avail.width / 2, y: avail.height / 2)
    }

    /// 正在拖动中的取样框（未拖动时 nil；已提交的框由 sampleRectOverlays 画）
    private var liveDragRect: CropRectN? {
        if let s = wbDragStart, let c = wbDragCurrent {
            return normalizedRect(from: s, to: c)
        }
        return nil
    }

    /// 已提交的四个取样框（白平衡 / 片基 / 暗部 / 亮部）各画一个彩色矩形
    @ViewBuilder
    private func sampleRectOverlays(fw: CGFloat, fh: CGFloat) -> some View {
        if let r = state.params.wbRect {
            sampleRect(r, color: RectPickMode.whiteBalance.overlayColor, fw: fw, fh: fh)
        }
        if let r = state.params.filmBaseRect {
            sampleRect(r, color: RectPickMode.filmBase.overlayColor, fw: fw, fh: fh)
        }
        if let r = state.params.shadowRect {
            sampleRect(r, color: RectPickMode.shadow.overlayColor, fw: fw, fh: fh)
        }
        if let r = state.params.highlightRect {
            sampleRect(r, color: RectPickMode.highlight.overlayColor, fw: fw, fh: fh)
        }
    }

    private func sampleRect(_ rect: CropRectN, color: Color,
                            fw: CGFloat, fh: CGFloat) -> some View {
        Rectangle()
            .fill(color.opacity(0.14))
            .overlay(Rectangle().stroke(color, lineWidth: 1.5))
            .frame(width: max(1, CGFloat(rect.x1 - rect.x0) * fw),
                   height: max(1, CGFloat(rect.y1 - rect.y0) * fh))
            .position(x: CGFloat(rect.x0 + rect.x1) * fw / 2,
                      y: CGFloat(rect.y0 + rect.y1) * fh / 2)
            .allowsHitTesting(false)
    }

    private func whiteRectGesture(width: CGFloat, height: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { v in
                let p = normalizedPoint(v.location, width: width, height: height)
                if wbDragStart == nil { wbDragStart = p }
                wbDragCurrent = p
            }
            .onEnded { v in
                let end = normalizedPoint(v.location, width: width, height: height)
                let start = wbDragStart ?? end
                let rect = normalizedRect(from: start, to: end)
                wbDragStart = nil
                wbDragCurrent = nil
                state.commitPickRect(rect)
            }
    }

    private func normalizedPoint(_ p: CGPoint, width: CGFloat, height: CGFloat) -> CGPoint {
        CGPoint(x: min(max(p.x / width, 0), 1),
                y: min(max(p.y / height, 0), 1))
    }

    private func normalizedRect(from a: CGPoint, to b: CGPoint) -> CropRectN {
        let minSize = 0.015
        var x0 = min(Double(a.x), Double(b.x))
        var x1 = max(Double(a.x), Double(b.x))
        var y0 = min(Double(a.y), Double(b.y))
        var y1 = max(Double(a.y), Double(b.y))
        if x1 - x0 < minSize {
            let cx = (x0 + x1) / 2
            x0 = min(max(cx - minSize / 2, 0), 1 - minSize)
            x1 = x0 + minSize
        }
        if y1 - y0 < minSize {
            let cy = (y0 + y1) / 2
            y0 = min(max(cy - minSize / 2, 0), 1 - minSize)
            y1 = y0 + minSize
        }
        return CropRectN(x0: x0, y0: y0, x1: x1, y1: y1)
    }

    private var placeholder: some View {
        VStack(spacing: 8) {
            if state.isLoading {
                ProgressView()
                Text("解码中…").foregroundStyle(.secondary)
            } else {
                Text("← 左侧打开文件夹并选择一张底片")
                    .foregroundStyle(.secondary)
                Text("支持 ARW / ARQ / CR2 / CR3 / NEF / RAF / DNG / RW2 / TIF / JPG / PNG")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    /// 底部状态条：状态文本 + 渲染指示 + 「按住看负片」
    private var statusBar: some View {
        HStack(spacing: 10) {
            Text(state.statusText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            if state.pickMode != .none {
                Text("拖框取样：\(state.pickMode.hint)…")
                    .font(.caption)
                    .foregroundStyle(state.pickMode.overlayColor)
            }
            if state.isRendering || state.isLoading {
                ProgressView().controlSize(.small)
            }
            if state.displayCG != nil {
                negativeButton
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.bar)
    }

    /// 按住临时显示未反转的负片原图（松开恢复）
    private var negativeButton: some View {
        Text("按住看负片")
            .font(.caption)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(
                RoundedRectangle(cornerRadius: 5)
                    .fill(state.showNegative
                          ? Color.orange
                          : Color(nsColor: .controlColor)))
            .foregroundStyle(state.showNegative ? Color.black : Color.primary)
            .help("按住临时显示未反转的负片原图（仅方向 + 2.2 gamma 编码）")
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        if !state.showNegative { state.setNegativePressed(true) }
                    }
                    .onEnded { _ in
                        state.setNegativePressed(false)
                    })
    }
}

// ------------------------------------------------------------------------- //
// 取样模式的界面配色 / 提示文案
// ------------------------------------------------------------------------- //

extension RectPickMode {
    /// 取样框在预览里的标注颜色
    var overlayColor: Color {
        switch self {
        case .whiteBalance: return .yellow
        case .filmBase:     return .orange
        case .shadow:       return .cyan
        case .highlight:    return .green
        case .none:         return .yellow
        }
    }

    /// 状态栏提示词
    var hint: String {
        switch self {
        case .whiteBalance: return "白点"
        case .filmBase:     return "片基"
        case .shadow:       return "暗部"
        case .highlight:    return "亮部"
        case .none:         return ""
        }
    }
}
