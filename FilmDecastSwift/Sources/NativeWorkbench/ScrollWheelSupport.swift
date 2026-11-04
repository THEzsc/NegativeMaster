import AppKit
import SwiftUI

enum MouseWheelInput {
  static func delta(x: CGFloat, y: CGFloat, precise: Bool,
                    modifiers: NSEvent.ModifierFlags) -> Double? {
    guard !precise, x == 0, y.isFinite, y != 0,
      modifiers.intersection([.command, .control, .option, .shift]).isEmpty else { return nil }
    return Double(y)
  }

  static func zoom(_ current: Double, delta: Double, inverted: Bool) -> Double {
    let physicalDelta = inverted ? -delta : delta
    return min(16, max(0.25, current * pow(1.12, min(4, max(-4, physicalDelta)))))
  }
}

/// Handle conventional mouse wheels only within the hovered scroll view.
/// Precise trackpad scrolling, momentum and modified gestures keep their native behavior.
struct ScrollWheelSupport: NSViewRepresentable {
  var enabled = true
  var onZoom: ((Double, Bool) -> Void)? = nil

  func makeCoordinator() -> Coordinator { Coordinator() }
  func makeNSView(context: Context) -> Probe {
    let view = Probe()
    view.coordinator = context.coordinator
    return view
  }
  func updateNSView(_ view: Probe, context: Context) {
    context.coordinator.enabled = enabled
    context.coordinator.onZoom = onZoom
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

  final class Coordinator {
    var enabled = true
    var onZoom: ((Double, Bool) -> Void)?
    weak var scroll: NSScrollView?
    private var monitor: Any?

    func attach(_ scroll: NSScrollView) {
      self.scroll = scroll
      guard monitor == nil else { return }
      monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] event in
        guard let self, self.handle(event) else { return event }
        return nil
      }
    }
    func detach() {
      if let monitor { NSEvent.removeMonitor(monitor) }
      monitor = nil; scroll = nil
    }
    deinit { if let monitor { NSEvent.removeMonitor(monitor) } }

    private func handle(_ event: NSEvent) -> Bool {
      guard enabled, let scroll, !scroll.isHiddenOrHasHiddenAncestor,
        let window = scroll.window, event.window === window,
        let root = window.contentView,
        let hit = root.hitTest(root.convert(event.locationInWindow, from: nil)),
        hit === scroll || hit.isDescendant(of: scroll),
        let delta = MouseWheelInput.delta(x: event.scrollingDeltaX, y: event.scrollingDeltaY,
          precise: event.hasPreciseScrollingDeltas, modifiers: event.modifierFlags)
      else { return false }

      if let onZoom {
        onZoom(delta, event.isDirectionInvertedFromDevice)
      } else {
        let clip = scroll.contentView
        var bounds = clip.bounds
        bounds.origin.x -= CGFloat(delta) * max(32, scroll.horizontalLineScroll)
        clip.scroll(to: clip.constrainBoundsRect(bounds).origin)
        scroll.reflectScrolledClipView(clip)
      }
      return true
    }
  }
}
