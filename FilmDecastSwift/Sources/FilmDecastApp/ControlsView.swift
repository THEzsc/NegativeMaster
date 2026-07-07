//
//  ControlsView.swift —— 右侧控制面板
//
//  分组（GroupBox）：胶片类型 / 直方图 / 影调 / 色彩 / 细节 / 高级 /
//  参照匹配 / 裁切 / 方向 / 导出。滑杆直接绑定 AppState.params，
//  参数 didSet 里做防抖渲染与持久化。
//

import SwiftUI
import FilmDecastCore

struct ControlsView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                modeSection
                histogramSection
                toneSection
                colorSection
                detailSection
                advancedSection
                matchSection
                cropSection
                orientationSection
                exportSection
            }
            .padding(10)
        }
    }

    // ------------------------- 胶片类型 ------------------------- //

    private var modeSection: some View {
        GroupBox("胶片类型") {
            Picker("", selection: $state.params.mode) {
                Text("彩色负片").tag(FilmMode.colorNegative)
                Text("黑白负片").tag(FilmMode.bwNegative)
                Text("正片").tag(FilmMode.positive)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
    }

    // ------------------------- 直方图 ------------------------- //

    private var histogramSection: some View {
        GroupBox("直方图（裁切框内）") {
            HistogramView(data: state.histogram)
        }
    }

    // ------------------------- 影调 ------------------------- //

    private var toneSection: some View {
        GroupBox("影调") {
            VStack(spacing: 6) {
                SliderRow(title: "亮度 gamma", value: $state.params.gamma,
                          range: 0.6...3, step: 0.05)
                SliderRow(title: "对比度", value: $state.params.contrast,
                          range: -0.5...0.6, step: 0.02)
                SliderRow(title: "饱和度", value: $state.params.saturation,
                          range: 0...1.6, step: 0.05)
            }
        }
        .disabled(state.params.useMatch && state.matchRefLoaded)
    }

    // ------------------------- 色彩 ------------------------- //

    private var colorSection: some View {
        GroupBox("色彩") {
            VStack(alignment: .leading, spacing: 6) {
                SliderRow(title: "色温（冷 - 暖）", value: $state.params.temperature,
                          range: -100...100, step: 1, format: "%.0f")
                SliderRow(title: "色调（绿 - 品红）", value: $state.params.tint,
                          range: -100...100, step: 1, format: "%.0f")
                    .disabled(state.params.useMatch && state.matchRefLoaded)

                HStack {
                    Text("白平衡").font(.system(size: 12))
                    Picker("", selection: $state.params.wb) {
                        Text("灰世界").tag(WBMode.grayWorld)
                        Text("不做").tag(WBMode.none)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
                .disabled(state.params.wbPoint != nil || state.params.wbRect != nil)

                HStack(spacing: 8) {
                    Toggle("框选白点", isOn: $state.wbPicking)
                        .toggleStyle(.button)
                        .help("开启后在预览画面拖框，把框内平均颜色采样为中性灰")
                    Button("清除白点") { state.clearWhitePoint() }
                        .disabled(state.params.wbPoint == nil && state.params.wbRect == nil)
                    Spacer()
                    if let r = state.params.wbRect {
                        Text(String(format: "%.2f×%.2f", r.x1 - r.x0, r.y1 - r.y0))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(.secondary)
                    } else if let p = state.params.wbPoint {
                        Text(String(format: "(%.2f, %.2f)", p.x, p.y))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
                if state.params.wbPoint != nil || state.params.wbRect != nil {
                    Text("已设白点取样：优先于灰世界白平衡")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    // ------------------------- 细节 ------------------------- //

    private var detailSection: some View {
        GroupBox("细节") {
            VStack(spacing: 6) {
                SliderRow(title: "色度降噪", value: $state.params.denoise,
                          range: 0...12, step: 1, format: "%.0f")
                SliderRow(title: "锐化", value: $state.params.sharpen,
                          range: 0...3, step: 0.05)
            }
        }
    }

    // ------------------------- 高级 ------------------------- //

    private var advancedSection: some View {
        GroupBox("高级") {
            VStack(spacing: 6) {
                SliderRow(title: "黑点 %", value: $state.params.blackPct,
                          range: 0...3, step: 0.1, format: "%.1f")
                SliderRow(title: "白点 %", value: $state.params.whitePct,
                          range: 97...100, step: 0.1, format: "%.1f")
            }
        }
    }

    // ------------------------- 参照匹配 ------------------------- //

    private var matchSection: some View {
        GroupBox("参照匹配（扫描件）") {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Button("选择参照图…") { state.chooseMatchReference() }
                        .help("选同一张 / 同卷的成品正片扫描件，转移其色调与色彩")
                    Button("清除") { state.clearMatchReference() }
                        .disabled(state.matchRefURL == nil)
                }
                if let name = state.matchRefName {
                    Text((state.matchRefLoaded ? "✓ " : "载入中… ") + name)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Toggle("应用直方图匹配", isOn: $state.params.useMatch)
                    .disabled(!state.matchRefLoaded)
                Text("开启后覆盖 gamma / 对比度 / 饱和度 / 色温色调")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // ------------------------- 裁切 ------------------------- //

    private var cropSection: some View {
        GroupBox("裁切画幅（拖动预览里的框定位）") {
            VStack(alignment: .leading, spacing: 6) {
                Picker("", selection: $state.cropFormat) {
                    ForEach(CropFormat.allCases) { f in
                        Text(f.rawValue).tag(f)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()

                HStack(spacing: 8) {
                    Picker("", selection: $state.cropLandscape) {
                        Text("横 ▭").tag(true)
                        Text("竖 ▯").tag(false)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(width: 110)
                    .disabled(state.cropFormat == .free)
                    Spacer()
                }

                HStack(spacing: 8) {
                    Button("自动画面") { state.autoDetectCrop() }
                        .help("自动探测胶片画面区域（区分画面与片基/背景）")
                    Button("占满") { state.cropFull() }
                    Button("重置框") { state.cropReset() }
                }
            }
        }
    }

    // ------------------------- 方向 ------------------------- //

    private var orientationSection: some View {
        GroupBox("方向") {
            HStack(spacing: 8) {
                Button("↶ 左转") { state.rotateLeft() }
                Button("↷ 右转") { state.rotateRight() }
                Toggle("镜像 H", isOn: $state.params.flipH)
                    .toggleStyle(.button)
                Toggle("翻转 V", isOn: $state.params.flipV)
                    .toggleStyle(.button)
            }
        }
    }

    // ------------------------- 导出 ------------------------- //

    private var exportSection: some View {
        GroupBox("导出") {
            VStack(alignment: .leading, spacing: 8) {
                Picker("", selection: $state.exportFormat) {
                    ForEach(ExportFileFormat.allCases) { f in
                        Text(f.label).tag(f)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()

                if state.exportFormat == .jpeg {
                    SliderRow(title: "JPG 质量", value: $state.jpegQuality,
                              range: 0.5...1.0, step: 0.01)
                }

                HStack {
                    Text("长边缩小").font(.system(size: 12))
                    Spacer()
                    Picker("", selection: $state.resizeLongEdge) {
                        ForEach(AppState.resizeOptions, id: \.self) { n in
                            Text(n == 0 ? "原尺寸" : "\(n) px").tag(n)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 110)
                }

                Button {
                    state.exportCurrent()
                } label: {
                    Text("导出当前图…").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(state.displayCG == nil || state.isExporting)

                Button {
                    state.exportChecked()
                } label: {
                    Text("批量导出勾选（\(state.checkedFiles.count)）…")
                        .frame(maxWidth: .infinity)
                }
                .disabled(state.checkedFiles.isEmpty || state.isExporting)
                .help("每张按其记忆的参数导出；没调过的用默认参数")

                Button {
                    state.applyCurrentParamsToRoll()
                } label: {
                    Text("当前参数套整卷").frame(maxWidth: .infinity)
                }
                .disabled(state.selectedFile == nil)
                .help("有勾选则套用到勾选文件；没有勾选则套用到当前过滤列表")

                if let p = state.batchProgress {
                    ProgressView(value: p)
                        .progressViewStyle(.linear)
                } else if state.isExporting {
                    ProgressView()
                        .controlSize(.small)
                }

                Divider()
                Button {
                    state.resetParams()
                } label: {
                    Text("恢复默认参数").frame(maxWidth: .infinity)
                }
                .disabled(state.displayCG == nil)
            }
        }
    }
}

// ------------------------------------------------------------------------- //
// 滑杆行：标题 + 数值 + Slider
// ------------------------------------------------------------------------- //

struct SliderRow: View {
    let title: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var step: Double = 0.01
    var format: String = "%.2f"

    var body: some View {
        VStack(spacing: 2) {
            HStack {
                Text(title).font(.system(size: 12))
                Spacer()
                Text(String(format: format, value))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            Slider(value: $value, in: range, step: step)
                .controlSize(.small)
        }
    }
}
