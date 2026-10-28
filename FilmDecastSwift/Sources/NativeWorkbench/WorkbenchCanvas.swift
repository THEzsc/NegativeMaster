import FilmDecastCore
import SwiftUI

struct WorkbenchCanvas: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  let mode: WorkbenchState.Workspace
  @State private var dragStart: CGPoint?
  @State private var dragEnd: CGPoint?
  @State private var magnifyStart: Double?
  @GestureState private var magnifying = false
  @State private var frameStart: CGPoint?
  private var image: NSImage? {
    mode == .develop
      ? (s.showNegative ? (s.negative ?? s.preview) : s.preview) : (s.frameView ? s.sheetFrameImage : s.sheetImage)
  }
  var body: some View {
    GeometryReader { geo in
      ZStack {
        Color(nsColor: .underPageBackgroundColor)
        if let image {
          let size = fitted(image.size, available: geo.size)
          ScrollView([.horizontal, .vertical]) {
            ZStack {
              if mode == .sheet { Checkerboard().frame(width: size.width, height: size.height) }
              Image(nsImage: image).resizable().interpolation(.high).frame(
                width: size.width, height: size.height)
              if mode == .develop && !s.showNegative { developOverlay(size: size) }
              if mode == .sheet && s.frameView {
                if s.frameGrid {
                  ThirdsGrid().stroke(.white.opacity(0.55), lineWidth: 0.75).allowsHitTesting(false)
                }
                Rectangle().fill(.clear).contentShape(Rectangle()).gesture(
                  DragGesture(minimumDistance: 3).onChanged { v in
                    if frameStart == nil {
                      frameStart = CGPoint(
                        x: s.frameValue("crop.x", fallback: .number(0.5)).double,
                        y: s.frameValue("crop.y", fallback: .number(0.5)).double)
                    }
                    guard let start = frameStart else { return }
                    let scale = max(1, s.frameValue("crop.scale", fallback: .number(1)).double)
                    s.setFrame(
                      "crop.x",
                      .number(min(1, max(0, start.x - v.translation.width / size.width / scale))))
                    s.setFrame(
                      "crop.y",
                      .number(min(1, max(0, start.y - v.translation.height / size.height / scale))))
                  }.onEnded { _ in frameStart = nil })
              }
            }
            .frame(width: size.width, height: size.height)
            .background {
              Rectangle().fill(Color(nsColor: .underPageBackgroundColor))
                .shadow(color: .black.opacity(0.16), radius: 12, y: 5)
            }
            .padding(32)
            .frame(minWidth: geo.size.width, minHeight: geo.size.height)
          }
          .simultaneousGesture(
            MagnifyGesture().updating($magnifying) { _, active, _ in active = true }
              .onChanged { v in
                if magnifyStart == nil { magnifyStart = s.zoom }
                s.zoom = min(5, max(0.25, (magnifyStart ?? s.zoom) * v.magnification))
              }.onEnded { _ in magnifyStart = nil }
          )
          .onChange(of: magnifying) { _, active in
            if !active { magnifyStart = nil }
          }
          .overlay(alignment: .bottom) { canvasTools.padding(.bottom, 18) }
          .overlay(alignment: .topLeading) {
            if !s.selectionTool.isEmpty && mode == .develop {
              Label(
                s.selectionTool == "crop" ? "拖动边框调整裁剪" : "在照片上拖出取样区域",
                systemImage: s.selectionTool == "crop" ? "crop" : "eyedropper"
              )
              .font(.callout).padding(10).background(.regularMaterial, in: Capsule()).padding(18)
            }
          }
        } else {
          emptyState
        }
        if s.busy {
          VStack(spacing: 12) {
            ProgressView()
            Text(s.status).font(.callout).lineLimit(2)
            if s.progress > 0 { ProgressView(value: s.progress).frame(width: 180) }
          }
          .padding(24).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18)).frame(
            maxWidth: 340)
        }
      }
    }
  }
  private func fitted(_ size: CGSize, available: CGSize) -> CGSize {
    let scale =
      min(
        max(100, available.width - 64) / max(1, size.width),
        max(100, available.height - (mode == .develop ? 160 : 100)) / max(1, size.height)) * s.zoom
    return CGSize(width: size.width * scale, height: size.height * scale)
  }
  private var emptyState: some View {
    VStack(spacing: 18) {
      Image(systemName: mode == .develop ? "camera.aperture" : "rectangle.split.3x3").font(
        .system(size: 48, weight: .ultraLight)
      ).foregroundStyle(.secondary)
      Text(mode == .develop ? "让底片回到光里" : "把一卷故事放在一起").font(
        .system(size: 25, weight: .semibold))
      Text(
        mode == .develop
          ? "打开胶卷文件夹，或将 RAW、TIFF、JPEG 拖到这里。" : "导入成片，或读取胶卷中已保存的调片参数。\n照片顺序、边字与背景都可以继续编辑。"
      )
      .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center).lineSpacing(5)
      HStack(spacing: 12) {
        Button("打开文件夹…", action: s.chooseFolder).buttonStyle(.borderedProminent)
        Button("导入照片…", action: s.chooseFiles).buttonStyle(.bordered)
      }.controlSize(.large).disabled(!s.ready || s.busy)
      if mode == .sheet {
        HStack {
          Button("打开整卷项目…", action: s.chooseProject)
          if s.draftAvailable { Button("恢复上次草稿", action: s.restoreDraft) }
        }.buttonStyle(.link).disabled(!s.ready || s.busy)
      }
    }.padding(30)
  }
  private var canvasTools: some View {
    HStack(spacing: 12) {
      if mode == .develop {
        Button {
          s.beginCrop()
        } label: {
          Image(systemName: "crop")
        }.help("裁剪")
        Button {
          s.rotate(-90)
        } label: {
          Image(systemName: "rotate.left")
        }.help("向左旋转")
        Button {
          s.rotate(90)
        } label: {
          Image(systemName: "rotate.right")
        }.help("向右旋转")
        Button {
          s.revealDevelopPanel("crop"); s.selectionTool = "crop"
        } label: {
          Label(String(format: "%.2f°", s.params["level_angle"].double), systemImage: "angle")
            .font(.caption.monospacedDigit())
        }.help("微量旋转与校平")
      } else {
        Button {
          s.frameView = false
        } label: {
          Image(systemName: "rectangle.split.3x3")
        }.help("整卷预览")
        if let id = s.activeFrame {
          Button {
            s.activateFrame(id)
          } label: {
            Image(systemName: "photo")
          }.help("单张构图")
        }
      }
      Divider().frame(height: 18)
      Button {
        s.zoom = max(0.25, s.zoom / 1.25)
      } label: {
        Image(systemName: "minus.magnifyingglass")
      }
      Button("\(Int(s.zoom*100))%", action: { s.zoom = 1 }).font(.caption.monospacedDigit()).frame(
        width: 44
      ).help("适合窗口")
      Button {
        s.zoom = min(5, s.zoom * 1.25)
      } label: {
        Image(systemName: "plus.magnifyingglass")
      }
    }.buttonStyle(.borderless).padding(.horizontal, 16).padding(.vertical, 12).modifier(
      WorkbenchGlass()
    ).shadow(color: .black.opacity(0.1), radius: 8, y: 3)
  }
  @ViewBuilder private func developOverlay(size: CGSize) -> some View {
    let cr = s.params["crop_rect"].array.map(\.double)
    if s.selectionTool == "crop" {
      let rect =
        cr.count == 4
        ? CropRectN(x0: cr[0], y0: cr[1], x1: cr[2], y1: cr[3])
        : CropRectN(x0: 0, y0: 0, x1: 1, y1: 1)
      CropOverlayView(rect: rect, normalizedAspect: normalizedAspect(size), pixelSize: orientedSize)
      { r in s.setParam("crop_rect", .doubles([r.x0, r.y0, r.x1, r.y1])) }
    } else if !s.selectionTool.isEmpty {
      Rectangle().fill(.clear).contentShape(Rectangle()).gesture(
        DragGesture(minimumDistance: 0).onChanged { v in
          dragStart = v.startLocation
          dragEnd = v.location
        }.onEnded { v in
          let r = normalized(v.startLocation, v.location, size: size)
          if r[2] - r[0] > 0.002 && r[3] - r[1] > 0.002 { s.commitSample(s.selectionTool, rect: r) }
          dragStart = nil
          dragEnd = nil
          s.selectionTool = ""
        })
    } else if cr.count == 4 {
      Path { p in
        p.addRect(
          CGRect(
            x: cr[0] * size.width, y: cr[1] * size.height, width: (cr[2] - cr[0]) * size.width,
            height: (cr[3] - cr[1]) * size.height))
      }.stroke(.white.opacity(0.7), style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
        .allowsHitTesting(false)
    }
    if let a = dragStart, let b = dragEnd {
      let r = normalized(a, b, size: size)
      Rectangle().fill(.yellow.opacity(0.16)).overlay(Rectangle().stroke(.yellow, lineWidth: 1))
        .frame(width: (r[2] - r[0]) * size.width, height: (r[3] - r[1]) * size.height).position(
          x: (r[0] + r[2]) * size.width / 2, y: (r[1] + r[3]) * size.height / 2
        ).allowsHitTesting(false)
    }
    ForEach(["wb_rect", "film_base_rect", "shadow_rect", "highlight_rect"], id: \.self) { key in
      let r = s.params[key].array.map(\.double)
      if r.count == 4 {
        Rectangle().stroke(key == "wb_rect" ? Color.yellow : Color.cyan, lineWidth: 1).frame(
          width: (r[2] - r[0]) * size.width, height: (r[3] - r[1]) * size.height
        ).position(x: (r[0] + r[2]) * size.width / 2, y: (r[1] + r[3]) * size.height / 2)
          .allowsHitTesting(false)
      }
    }
  }
  private var orientedSize: CGSize {
    Int(s.params["rotate"].double) % 180 == 0
      ? s.imageSize : CGSize(width: s.imageSize.height, height: s.imageSize.width)
  }
  private func normalizedAspect(_ size: CGSize) -> Double? {
    let ratios: [String: Double] = [
      "3:2": 1.5, "2:3": 2 / 3, "4:3": 4 / 3, "3:4": 3 / 4, "1:1": 1, "6:7": 6 / 7, "7:6": 7 / 6,
    ]
    return ratios[s.cropAspect].map { $0 * size.height / size.width }
  }
  private func normalized(_ a: CGPoint, _ b: CGPoint, size: CGSize) -> [Double] {
    [
      max(0, min(1, min(a.x, b.x) / size.width)), max(0, min(1, min(a.y, b.y) / size.height)),
      max(0, min(1, max(a.x, b.x) / size.width)), max(0, min(1, max(a.y, b.y) / size.height)),
    ]
  }
}
struct Checkerboard: View {
  var body: some View {
    Canvas { ctx, size in
      ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white))
      var squares = Path()
      for y in stride(from: 0.0, to: size.height, by: 16) {
        for x in stride(from: 0.0, to: size.width, by: 16) {
          if (Int(x / 16) + Int(y / 16)) % 2 == 0 {
            squares.addRect(CGRect(x: x, y: y, width: 16, height: 16))
          }
        }
      }
      ctx.fill(squares, with: .color(.gray.opacity(0.2)))
    }
  }
}
struct ThirdsGrid: Shape {
  func path(in r: CGRect) -> Path {
    Path { p in
      for i in 1...2 {
        let f = Double(i) / 3
        p.move(to: CGPoint(x: r.width * f, y: 0))
        p.addLine(to: CGPoint(x: r.width * f, y: r.height))
        p.move(to: CGPoint(x: 0, y: r.height * f))
        p.addLine(to: CGPoint(x: r.width, y: r.height * f))
      }
    }
  }
}

private struct WorkbenchGlass: ViewModifier {
  @ViewBuilder func body(content: Content) -> some View {
    if #available(macOS 26.0, *) {
      content.glassEffect(.regular, in: Capsule())
    } else {
      content.background(.regularMaterial, in: Capsule())
    }
  }
}
