//
//  HistogramView.swift —— RGB 直方图（Canvas 绘制）
//
//  输入 3 通道 x 64 bin（AppState 渲染预览时顺带统计，已归一化到 0~1），
//  三通道用 screen 混合叠加，深色背景，风格与老版网页 GUI 接近。
//

import SwiftUI

struct HistogramView: View {
    /// 3 通道 x N bin，值 0~1
    let data: [[Float]]

    var body: some View {
        Canvas { ctx, size in
            // 背景
            let bgRect = CGRect(origin: .zero, size: size)
            ctx.fill(Path(roundedRect: bgRect, cornerRadius: 4),
                     with: .color(Color(white: 0.12)))

            guard data.count == 3,
                  let bins = data.first?.count, bins > 1,
                  data[1].count == bins, data[2].count == bins else {
                return
            }

            let inset: CGFloat = 3
            let plotW = size.width - inset * 2
            let plotH = size.height - inset * 2
            guard plotW > 4, plotH > 4 else { return }

            let colors: [Color] = [
                Color(red: 1.0, green: 0.32, blue: 0.30),
                Color(red: 0.35, green: 0.95, blue: 0.42),
                Color(red: 0.35, green: 0.55, blue: 1.0),
            ]

            ctx.blendMode = .screen
            for c in 0..<3 {
                var path = Path()
                path.move(to: CGPoint(x: inset, y: inset + plotH))
                for b in 0..<bins {
                    let x = inset + plotW * CGFloat(b) / CGFloat(bins - 1)
                    let v = CGFloat(min(max(data[c][b], 0), 1))
                    path.addLine(to: CGPoint(x: x, y: inset + plotH * (1 - v)))
                }
                path.addLine(to: CGPoint(x: inset + plotW, y: inset + plotH))
                path.closeSubpath()
                ctx.fill(path, with: .color(colors[c].opacity(0.45)))
                ctx.stroke(path, with: .color(colors[c].opacity(0.85)), lineWidth: 1)
            }
        }
        .frame(height: 90)
        .frame(maxWidth: .infinity)
    }
}
