//
//  CropOverlayView.swift —— 可拖动的裁切框
//
//  盖在预览图上（尺寸与图完全一致）：
//    - 框外半透明暗化 + 三分构图线 + 四角手柄
//    - 框内拖动 = 移动；四角拖动 = 缩放（可锁定画幅比例）
//    - 拖动过程中只更新本地状态（不触发重渲染），
//      松手才通过 onCommit 写回参数、触发一次渲染
//

import SwiftUI
import FilmDecastCore

struct CropOverlayView: View {
    /// 当前裁切矩形（未拖动时显示；坐标是方向后的 0~1 归一化）
    let rect: CropRectN
    /// 锁定的「归一化坐标宽/高比」（nil = 自由）
    let normalizedAspect: Double?
    /// 方向后的整幅像素尺寸（画尺寸标签用）
    let pixelSize: CGSize
    /// 拖动结束提交新矩形
    let onCommit: (CropRectN) -> Void

    /// 拖动中的临时矩形（nil = 未在拖动）
    @State private var dragRect: CropRectN?
    @State private var startRect: CropRectN?
    @State private var dragMode: DragMode = .idle

    private enum DragMode {
        case idle, move, nw, ne, sw, se
    }

    /// 裁切框最小边长（归一化）
    private let minSide = 0.03
    /// 手柄命中半径（点）
    private let hitRadius: CGFloat = 14

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            let r = dragRect ?? rect
            let vr = viewRect(r, in: size)

            ZStack(alignment: .topLeading) {
                // 框外暗化（奇偶填充挖洞）
                Path { p in
                    p.addRect(CGRect(origin: .zero, size: size))
                    p.addRect(vr)
                }
                .fill(Color.black.opacity(0.45),
                      style: FillStyle(eoFill: true, antialiased: true))

                // 边框 + 三分线
                Path { p in
                    p.addRect(vr)
                    let w3 = vr.width / 3
                    let h3 = vr.height / 3
                    p.move(to: CGPoint(x: vr.minX + w3, y: vr.minY))
                    p.addLine(to: CGPoint(x: vr.minX + w3, y: vr.maxY))
                    p.move(to: CGPoint(x: vr.minX + 2 * w3, y: vr.minY))
                    p.addLine(to: CGPoint(x: vr.minX + 2 * w3, y: vr.maxY))
                    p.move(to: CGPoint(x: vr.minX, y: vr.minY + h3))
                    p.addLine(to: CGPoint(x: vr.maxX, y: vr.minY + h3))
                    p.move(to: CGPoint(x: vr.minX, y: vr.minY + 2 * h3))
                    p.addLine(to: CGPoint(x: vr.maxX, y: vr.minY + 2 * h3))
                }
                .stroke(Color.white.opacity(0.8), lineWidth: 1)

                // 四角手柄
                ForEach(handlePoints(vr), id: \.id) { h in
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.orange)
                        .overlay(RoundedRectangle(cornerRadius: 2)
                            .stroke(Color.black.opacity(0.6), lineWidth: 1))
                        .frame(width: 12, height: 12)
                        .position(h.point)
                }

                // 尺寸标签（对应最终导出的像素数）
                Text(sizeLabel(r))
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(Color.orange)
                    .padding(.horizontal, 4)
                    .padding(.vertical, 1)
                    .background(Color.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 3))
                    .position(x: min(max(vr.minX + 36, 40), size.width - 40),
                              y: max(vr.minY - 12, 10))
                    .allowsHitTesting(false)
            }
            .contentShape(Rectangle())
            .gesture(dragGesture(in: size))
        }
    }

    // ------------------------- 几何换算 ------------------------- //

    private func viewRect(_ r: CropRectN, in size: CGSize) -> CGRect {
        CGRect(x: r.x0 * size.width,
               y: r.y0 * size.height,
               width: (r.x1 - r.x0) * size.width,
               height: (r.y1 - r.y0) * size.height)
    }

    private func sizeLabel(_ r: CropRectN) -> String {
        let w = Int(((r.x1 - r.x0) * Double(pixelSize.width)).rounded())
        let h = Int(((r.y1 - r.y0) * Double(pixelSize.height)).rounded())
        return "\(w)×\(h)"
    }

    private struct HandleSpec: Identifiable {
        let id: String
        let point: CGPoint
    }

    private func handlePoints(_ vr: CGRect) -> [HandleSpec] {
        [
            HandleSpec(id: "nw", point: CGPoint(x: vr.minX, y: vr.minY)),
            HandleSpec(id: "ne", point: CGPoint(x: vr.maxX, y: vr.minY)),
            HandleSpec(id: "sw", point: CGPoint(x: vr.minX, y: vr.maxY)),
            HandleSpec(id: "se", point: CGPoint(x: vr.maxX, y: vr.maxY)),
        ]
    }

    /// 判断按下位置命中了哪个部件
    private func hitMode(at p: CGPoint, vr: CGRect) -> DragMode {
        let corners: [(DragMode, CGPoint)] = [
            (.nw, CGPoint(x: vr.minX, y: vr.minY)),
            (.ne, CGPoint(x: vr.maxX, y: vr.minY)),
            (.sw, CGPoint(x: vr.minX, y: vr.maxY)),
            (.se, CGPoint(x: vr.maxX, y: vr.maxY)),
        ]
        for (m, c) in corners
        where abs(p.x - c.x) <= hitRadius && abs(p.y - c.y) <= hitRadius {
            return m
        }
        return vr.insetBy(dx: -2, dy: -2).contains(p) ? .move : .idle
    }

    // ------------------------- 拖动手势 ------------------------- //

    private func dragGesture(in size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { v in
                if startRect == nil {
                    // 拖动开始：按下位置决定模式
                    startRect = rect
                    dragMode = hitMode(at: v.startLocation, vr: viewRect(rect, in: size))
                }
                guard dragMode != .idle, let s = startRect,
                      size.width > 0, size.height > 0 else { return }
                let dx = Double((v.location.x - v.startLocation.x) / size.width)
                let dy = Double((v.location.y - v.startLocation.y) / size.height)
                dragRect = movedRect(from: s, dx: dx, dy: dy)
            }
            .onEnded { _ in
                if let r = dragRect, dragMode != .idle {
                    onCommit(r)   // 松手才触发一次重渲染
                }
                dragRect = nil
                startRect = nil
                dragMode = .idle
            }
    }

    private func movedRect(from s: CropRectN, dx: Double, dy: Double) -> CropRectN {
        var n = s
        switch dragMode {
        case .move:
            let w = s.x1 - s.x0
            let h = s.y1 - s.y0
            n.x0 = clamp(s.x0 + dx, 0, 1 - w); n.x1 = n.x0 + w
            n.y0 = clamp(s.y0 + dy, 0, 1 - h); n.y1 = n.y0 + h
        case .nw, .ne, .sw, .se:
            let west = (dragMode == .nw || dragMode == .sw)
            let north = (dragMode == .nw || dragMode == .ne)
            if west {
                n.x0 = clamp(s.x0 + dx, 0, s.x1 - minSide)
            } else {
                n.x1 = clamp(s.x1 + dx, s.x0 + minSide, 1)
            }
            if north {
                n.y0 = clamp(s.y0 + dy, 0, s.y1 - minSide)
            } else {
                n.y1 = clamp(s.y1 + dy, s.y0 + minSide, 1)
            }
            if let r = normalizedAspect {
                lockAspect(&n, north: north, west: west, ratio: r)
            }
        case .idle:
            break
        }
        return n
    }

    /// 比例锁定（同 Python 版 lockAspect）：以宽定高，越界时反向收缩
    private func lockAspect(_ n: inout CropRectN,
                            north: Bool, west: Bool, ratio: Double) {
        var w = n.x1 - n.x0
        var h = w / ratio
        if north { n.y0 = n.y1 - h } else { n.y1 = n.y0 + h }
        if n.y0 < -1e-6 || n.y1 > 1 + 1e-6 {
            if north { n.y0 = max(0, n.y0) } else { n.y1 = min(1, n.y1) }
            h = n.y1 - n.y0
            w = h * ratio
            if west { n.x0 = n.x1 - w } else { n.x1 = n.x0 + w }
        }
    }

    private func clamp(_ v: Double, _ lo: Double, _ hi: Double) -> Double {
        min(max(v, lo), hi)
    }
}
