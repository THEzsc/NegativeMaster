import AppKit
import SwiftUI

/// Preserve mouse-drag panning when scroll indicators are hidden. Crop/sample drags take precedence.
struct CanvasPanSupport: NSViewRepresentable {
  var enabled: Bool

  func makeCoordinator() -> Coordinator { Coordinator() }
  func makeNSView(context: Context) -> Probe {
    let view = Probe()
    view.coordinator = context.coordinator
    context.coordinator.gesture.isEnabled = enabled
    return view
  }
  func updateNSView(_ view: Probe, context: Context) {
    context.coordinator.gesture.isEnabled = enabled
    view.attachWhenReady()
  }
  static func dismantleNSView(_ view: Probe, coordinator: Coordinator) {
    view.coordinator = nil
    coordinator.detach()
  }

  final class Probe: NSView {
    weak var coordinator: Coordinator?
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func viewDidMoveToSuperview() { super.viewDidMoveToSuperview(); attachWhenReady() }
    override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); attachWhenReady() }
    func attachWhenReady() {
      DispatchQueue.main.async { [weak self] in
        guard let self, let scroll = self.enclosingScrollView else { return }
        self.coordinator?.attach(scroll)
      }
    }
  }

  final class Coordinator: NSObject {
    let gesture = NSPanGestureRecognizer()
    weak var scroll: NSScrollView?
    weak var document: NSView?
    private var origin = NSPoint.zero
    override init() {
      super.init()
      gesture.target = self
      gesture.action = #selector(pan(_:))
      gesture.buttonMask = 1
    }
    func attach(_ value: NSScrollView) {
      guard scroll !== value || document !== value.documentView else { return }
      detach()
      scroll = value; document = value.documentView
      document?.addGestureRecognizer(gesture)
    }
    func detach() {
      document?.removeGestureRecognizer(gesture)
      scroll = nil; document = nil
    }
    @objc private func pan(_ sender: NSPanGestureRecognizer) {
      guard let scroll else { return }
      let clip = scroll.contentView
      if sender.state == .began { origin = clip.bounds.origin }
      guard sender.state == .began || sender.state == .changed else { return }
      let translation = sender.translation(in: clip)
      let proposed = NSRect(x: origin.x - translation.x, y: origin.y - translation.y,
                            width: clip.bounds.width, height: clip.bounds.height)
      clip.scroll(to: clip.constrainBoundsRect(proposed).origin)
      scroll.reflectScrolledClipView(clip)
    }
  }
}
