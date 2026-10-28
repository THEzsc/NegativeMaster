import SwiftUI
import AppKit

extension WorkbenchState {
  func selectPhoto(_ path: String, extending: Bool = false, toggling: Bool = false) {
    let paths = filteredPhotos.map(\.path)
    guard let index = paths.firstIndex(of: path) else { return }
    if extending, let anchor = selectionAnchor, let start = paths.firstIndex(of: anchor) {
      let range = Set(paths[min(start, index)...max(start, index)])
      checked = toggling ? checked.union(range) : range
    } else if toggling {
      if checked.contains(path) {
        checked.remove(path)
        if selected == path {
          if let next = paths.first(where: { checked.contains($0) }) { select(next) }
          else { persistNow(); selected = nil; preview = nil; negative = nil }
        }
        selectionAnchor = path
        return
      }
      checked.insert(path)
      selectionAnchor = path
    } else {
      checked = [path]
      selectionAnchor = path
    }
    select(path)
  }
  func movePhoto(_ delta: Int, extending: Bool = false) {
    let paths = filteredPhotos.map(\.path)
    guard !paths.isEmpty else { return }
    let index = paths.firstIndex(of: selected ?? "") ?? (delta > 0 ? -1 : paths.count)
    selectPhoto(paths[min(paths.count - 1, max(0, index + delta))], extending: extending)
  }
  func generateThumbnails() {
    thumbnailTask?.cancel()
    let paths = filteredPhotos.map(\.path)
    thumbnailDone = 0; thumbnailTotal = paths.count
    thumbnailTask = Task {
      for path in paths {
        guard !Task.isCancelled else { return }
        _ = try? await ImagePipeline.shared.file(path, size: 160)
        guard !Task.isCancelled else { return }
        thumbnailDone += 1
        await Task.yield()
      }
      await ImagePipeline.trimThumbnails()
    }
  }
  func beginCrop() {
    revealDevelopPanel("crop")
    selectionTool = selectionTool == "crop" ? "" : "crop"
  }
}

struct PhotoBrowser: View {
  @Environment(WorkbenchState.self) var s
  var horizontal = false
  @FocusState private var browserFocused: Bool
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    VStack(spacing: 0) {
      if horizontal {
        HStack(spacing: 16) {
          Text("\(s.filteredPhotos.count) 张 · 已选 \(s.visibleCheckedPhotos.count)").font(.caption).monospacedDigit()
          TextField("搜索照片", text: bindings.search).textFieldStyle(.roundedBorder).frame(width: 180)
          Toggle("只显示 RAW", isOn: bindings.rawOnly).toggleStyle(.checkbox)
          Spacer()
          Button("生成缩略图", action: s.generateThumbnails).disabled(s.thumbnailDone < s.thumbnailTotal)
          Button { s.filmstripBottom = false } label: { Image(systemName: "sidebar.left") }.help("照片栏移到左侧")
        }.padding(.horizontal, 16).padding(.top, 10)
      }
      ScrollViewReader { proxy in
        ScrollView(horizontal ? .horizontal : .vertical) {
          if horizontal {
            LazyHStack(spacing: 6) { ForEach(s.filteredPhotos) { photo in tile(photo).id(photo.path) } }.padding(10)
          } else {
            LazyVStack(spacing: 3) { ForEach(s.filteredPhotos) { photo in tile(photo).id(photo.path) } }.padding(.horizontal, 8).padding(.vertical, 4)
          }
        }
        .focusable().focused($browserFocused).focusEffectDisabled()
        .onKeyPress(.rightArrow, phases: [.down, .repeat]) { press in s.movePhoto(1, extending: press.modifiers.contains(.shift)); return .handled }
        .onKeyPress(.downArrow, phases: [.down, .repeat]) { press in s.movePhoto(1, extending: press.modifiers.contains(.shift)); return .handled }
        .onKeyPress(.leftArrow, phases: [.down, .repeat]) { press in s.movePhoto(-1, extending: press.modifiers.contains(.shift)); return .handled }
        .onKeyPress(.upArrow, phases: [.down, .repeat]) { press in s.movePhoto(-1, extending: press.modifiers.contains(.shift)); return .handled }
        .onKeyPress(characters: CharacterSet(charactersIn: "aA"), phases: .down) { press in
          guard press.modifiers.contains(.command) else { return .ignored }
          s.checked = Set(s.filteredPhotos.map(\.path)); return .handled
        }
        .onChange(of: s.selected) { _, path in if let path { proxy.scrollTo(path) } }
      }
    }.background(.bar)
  }
  private func tile(_ photo: Photo) -> some View {
    let active = s.selected == photo.path, selected = s.checked.contains(photo.path)
    return Button {
      browserFocused = true
      let flags = (NSApp.currentEvent?.modifierFlags ?? []).union(NSEvent.modifierFlags)
      s.selectPhoto(photo.path, extending: flags.contains(.shift), toggling: flags.contains(.command))
    } label: {
      Group {
        if horizontal {
          VStack(spacing: 5) {
            LocalThumbnail(path: photo.path).frame(width: 108, height: 72)
            Text(photo.name).font(.caption2).lineLimit(1).truncationMode(.middle).frame(width: 108)
          }.padding(6)
        } else {
          HStack(spacing: 10) {
            LocalThumbnail(path: photo.path).frame(width: 54, height: 46)
            VStack(alignment: .leading, spacing: 4) {
              Text(photo.name).lineLimit(1).truncationMode(.middle)
              HStack(spacing: 5) {
                Text(URL(fileURLWithPath: photo.path).pathExtension.uppercased())
                if photo.edited { Image(systemName: "slider.horizontal.3") }
              }.font(.caption2).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
          }.padding(6)
        }
      }
      .background(active ? Color.accentColor.opacity(0.22) : selected ? Color.primary.opacity(0.09) : Color.clear)
      .overlay(Rectangle().stroke(active ? Color.accentColor : Color.clear, lineWidth: 2))
      .contentShape(Rectangle())
    }.buttonStyle(.plain)
      .help("单击选择 · ⌘ 点击增减 · Shift 点击连选")
      .accessibilityLabel(photo.name)
      .accessibilityValue(active ? "当前照片，已选择" : selected ? "已选择" : "未选择")
      .contextMenu {
        Button("在 Finder 中显示") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: photo.path)]) }
        Button("只选择这张") { s.selectPhoto(photo.path) }
      }
  }
}

/// Momentary comparison: mouse/Space down shows the negative, release restores it.
struct NegativeHoldButton: NSViewRepresentable {
  let state: WorkbenchState
  func makeNSView(context: Context) -> HoldButton {
    let button = HoldButton()
    button.image = NSImage(systemSymbolName: "circle.lefthalf.filled", accessibilityDescription: "按住查看底片")
    button.bezelStyle = .texturedRounded
    button.setAccessibilityLabel("按住查看底片")
    button.toolTip = "按住查看底片，松开返回调片"
    return button
  }
  func updateNSView(_ button: HoldButton, context: Context) {
    button.onHold = { state.showNegative = $0 }
    button.isEnabled = state.preview != nil && state.workspace == .develop
  }
  final class HoldButton: NSButton {
    var onHold: ((Bool) -> Void)?
    override func mouseDown(with event: NSEvent) {
      guard isEnabled else { return }
      onHold?(true)
      defer { onHold?(false) }
      super.mouseDown(with: event)
    }
    override func keyDown(with event: NSEvent) {
      if event.keyCode == 49, isEnabled { onHold?(true) } else { super.keyDown(with: event) }
    }
    override func keyUp(with event: NSEvent) {
      if event.keyCode == 49 { onHold?(false) } else { super.keyUp(with: event) }
    }
    override func resignFirstResponder() -> Bool { onHold?(false); return super.resignFirstResponder() }
  }
}
