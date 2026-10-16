import SwiftUI

struct CurveEditor: View {
  @Binding var value: J
  let channel: String
  @State private var active: Int?
  var points: [[Double]] {
    let p = value.array.map { $0.array.map(\.double) }.filter {
      $0.count == 2 && $0.allSatisfy { $0.isFinite && (0...1).contains($0) }
    }.sorted { $0[0] < $1[0] }
    var unique: [[Double]] = []
    for point in p {
      if let last = unique.last, abs(last[0] - point[0]) < 0.000001 {
        unique[unique.count - 1] = point
      } else {
        unique.append(point)
      }
    }
    return unique.count >= 2 ? unique : [[0, 0], [1, 1]]
  }
  var tint: Color {
    channel == "curve_r"
      ? .red : channel == "curve_g" ? .green : channel == "curve_b" ? .blue : .primary
  }
  var body: some View {
    GeometryReader { g in
      Canvas { ctx, size in
        let rect = CGRect(origin: .zero, size: size)
        ctx.fill(
          Path(roundedRect: rect, cornerRadius: 8),
          with: .color(Color(nsColor: .textBackgroundColor)))
        var grid = Path()
        for i in 1...3 {
          let f = Double(i) / 4
          grid.move(to: CGPoint(x: size.width * f, y: 0))
          grid.addLine(to: CGPoint(x: size.width * f, y: size.height))
          grid.move(to: CGPoint(x: 0, y: size.height * f))
          grid.addLine(to: CGPoint(x: size.width, y: size.height * f))
        }
        ctx.stroke(grid, with: .color(.secondary.opacity(0.18)), lineWidth: 1)
        var diagonal = Path()
        diagonal.move(to: CGPoint(x: 0, y: size.height))
        diagonal.addLine(to: CGPoint(x: size.width, y: 0))
        ctx.stroke(
          diagonal, with: .color(.secondary.opacity(0.3)),
          style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
        var line = Path()
        for (i, p) in interpolated.enumerated() {
          let v = CGPoint(x: p[0] * size.width, y: (1 - p[1]) * size.height)
          if i == 0 { line.move(to: v) } else { line.addLine(to: v) }
        }
        ctx.stroke(line, with: .color(tint), lineWidth: 2)
        for p in points {
          ctx.fill(
            Path(
              ellipseIn: CGRect(
                x: p[0] * size.width - 4, y: (1 - p[1]) * size.height - 4, width: 8, height: 8)),
            with: .color(tint))
        }
      }
      .contentShape(Rectangle())
      .gesture(
        DragGesture(minimumDistance: 0).onChanged { v in
          var ps = points
          let x = min(1, max(0, v.location.x / g.size.width))
          let y = min(1, max(0, 1 - v.location.y / g.size.height))
          if active == nil {
            if let i = ps.indices.min(by: {
              distance(ps[$0], v.startLocation, g.size) < distance(ps[$1], v.startLocation, g.size)
            }), distance(ps[i], v.startLocation, g.size) < 18 {
              active = i
            } else {
              ps.append([x, y])
              ps.sort { $0[0] < $1[0] }
              active = ps.firstIndex(of: [x, y])
            }
          }
          guard let i = active, ps.indices.contains(i) else { return }
          let low = i == 0 ? 0 : ps[i - 1][0] + 0.005
          let high = i == ps.count - 1 ? 1 : ps[i + 1][0] - 0.005
          ps[i] = [i == 0 ? 0 : i == ps.count - 1 ? 1 : min(high, max(low, x)), y]
          value = .array(ps.map { .doubles($0) })
        }.onEnded { _ in active = nil }
      )
      .simultaneousGesture(
        SpatialTapGesture(count: 2).onEnded { v in
          var ps = points
          if let i = ps.indices.min(by: {
            distance(ps[$0], v.location, g.size) < distance(ps[$1], v.location, g.size)
          }), i > 0, i < ps.count - 1, distance(ps[i], v.location, g.size) < 20 {
            ps.remove(at: i)
            value = .array(ps.map { .doubles($0) })
          }
        }
      )
      .accessibilityLabel("\(channel) 色调曲线，拖动控制点调整")
    }.padding(6)
  }
  private var interpolated: [[Double]] {
    let p = points
    let n = p.count
    let h = (0..<n - 1).map { max(0.000001, p[$0 + 1][0] - p[$0][0]) }
    let d = (0..<n - 1).map { (p[$0 + 1][1] - p[$0][1]) / h[$0] }
    var m = [Double](repeating: 0, count: n)
    m[0] = d[0]
    m[n - 1] = d[n - 2]
    if n > 2 {
      for i in 1..<n - 1 where d[i - 1] * d[i] > 0 {
        let a = 2 * h[i] + h[i - 1]
        let b = h[i] + 2 * h[i - 1]
        m[i] = (a + b) / (a / d[i - 1] + b / d[i])
      }
      for i in 0..<n - 1 {
        if abs(d[i]) < 1e-12 {
          m[i] = 0
          m[i + 1] = 0
        } else {
          let a = m[i] / d[i]
          let b = m[i + 1] / d[i]
          let q = a * a + b * b
          if q > 9 {
            let t = 3 / sqrt(q)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]
          }
        }
      }
    }
    return (0...256).map { k in
      let x = Double(k) / 256
      if x <= p[0][0] { return [x, p[0][1]] }
      if x >= p[n - 1][0] { return [x, p[n - 1][1]] }
      let i = max(0, min(n - 2, (p.firstIndex { $0[0] >= x } ?? n - 1) - 1))
      let t = (x - p[i][0]) / h[i]
      let a = 2 * t * t * t - 3 * t * t + 1
      let b = t * t * t - 2 * t * t + t
      let c = -2 * t * t * t + 3 * t * t
      let e = t * t * t - t * t
      let y = p[i][1] * a + m[i] * h[i] * b + p[i + 1][1] * c + m[i + 1] * h[i] * e
      return [x, min(1, max(0, y))]
    }
  }
  private func distance(_ p: [Double], _ q: CGPoint, _ size: CGSize) -> Double {
    hypot(p[0] * size.width - q.x, (1 - p[1]) * size.height - q.y)
  }
}
