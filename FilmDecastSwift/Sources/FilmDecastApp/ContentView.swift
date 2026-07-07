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
                // 取白点模式：点击采样（坐标 = 方向后、裁切前的归一化坐标）
                .gesture(
                    SpatialTapGesture()
                        .onEnded { v in
                            let pt = CGPoint(x: min(max(v.location.x / fw, 0), 1),
                                             y: min(max(v.location.y / fh, 0), 1))
                            state.pickWhitePoint(atNormalized: pt)
                        },
                    including: state.wbPicking && !state.showNegative ? .all : .none)

            // 白点标记
            if let p = state.params.wbPoint, !state.showNegative {
                Circle()
                    .stroke(Color.yellow, lineWidth: 1.5)
                    .frame(width: 14, height: 14)
                    .position(x: p.x * fw, y: p.y * fh)
                    .allowsHitTesting(false)
            }

            // 裁切框（看负片时隐藏，取白点时不拦截点击）
            if !state.showNegative, let rect = state.params.cropRect {
                CropOverlayView(rect: rect,
                                normalizedAspect: state.cropAspectNormalized,
                                pixelSize: state.orientedFullSize) { newRect in
                    state.commitCrop(newRect)
                }
                .allowsHitTesting(!state.wbPicking)
            }
        }
        .frame(width: fw, height: fh)
        .position(x: avail.width / 2, y: avail.height / 2)
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
            if state.wbPicking {
                Text("点击画面取白点…")
                    .font(.caption)
                    .foregroundStyle(.orange)
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
