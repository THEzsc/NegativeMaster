import SwiftUI

struct HSLBandSelector: View {
  @Binding var selection: String
  private let bands: [(id: String, title: String, color: Color)] = [
    ("red", "红", Color(red: 0.85, green: 0.20, blue: 0.22)),
    ("orange", "橙", Color(red: 0.95, green: 0.49, blue: 0.15)),
    ("yellow", "黄", Color(red: 0.94, green: 0.79, blue: 0.20)),
    ("green", "绿", Color(red: 0.29, green: 0.66, blue: 0.31)),
    ("aqua", "青", Color(red: 0.22, green: 0.74, blue: 0.75)),
    ("blue", "蓝", Color(red: 0.24, green: 0.45, blue: 0.91)),
    ("purple", "紫", Color(red: 0.58, green: 0.37, blue: 0.79)),
    ("magenta", "洋红", Color(red: 0.81, green: 0.33, blue: 0.62)),
  ]
  var body: some View {
    HStack(spacing: 0) {
      ForEach(bands, id: \.id) { band in
        Button { selection = band.id } label: {
          Circle().fill(band.color)
            .overlay(Circle().strokeBorder(.black.opacity(0.2), lineWidth: 1))
            .frame(width: 17, height: 17)
            .padding(4)
            .overlay(Circle().strokeBorder(selection == band.id ? Color.primary : .clear, lineWidth: 2))
            .frame(maxWidth: .infinity, minHeight: 32)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).help(band.title)
        .accessibilityLabel(band.title)
        .accessibilityAddTraits(selection == band.id ? .isSelected : [])
      }
    }.accessibilityElement(children: .contain).accessibilityLabel("HSL 颜色")
  }
}
