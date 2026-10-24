import SwiftUI

/// Each workspace owns a hosting boundary with a fixed viewport. A hidden Form/List
/// must not participate in the visible workspace's intrinsic-size negotiation.
struct WorkspacePane: NSViewRepresentable {
  enum Kind { case sidebar, inspector, canvas }
  let state: WorkbenchState
  let mode: WorkbenchState.Workspace
  let kind: Kind

  func makeNSView(context: Context) -> Container { Container() }
  func updateNSView(_ view: Container, context: Context) {
    view.show(mode, state: state, kind: kind, scheme: context.environment.colorScheme)
  }

  final class Container: NSView {
    private var pages: [WorkbenchState.Workspace: NSHostingView<AnyView>] = [:]
    private var active: WorkbenchState.Workspace?
    private var scheme: ColorScheme?
    override var intrinsicContentSize: NSSize { NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric) }

    func show(_ mode: WorkbenchState.Workspace, state: WorkbenchState, kind: Kind, scheme: ColorScheme) {
      let modes: [WorkbenchState.Workspace] = kind == .inspector ? [.develop, .sheet] : [.develop, .sheet, .archive]
      for page in modes {
        // Archive loading starts on first visit; photo tools are ready before switching.
        guard page != .archive || page == mode || pages[page] != nil else { continue }
        if pages[page] == nil || self.scheme != scheme {
          let content: AnyView
          if kind == .inspector { content = AnyView(WorkbenchInspector(mode: page)) }
          else if kind == .canvas {
            if page == .archive { content = AnyView(ArchiveDetail(a: state.archive)) }
            else { content = AnyView(WorkbenchCanvas(mode: page)) }
          }
          else if page == .archive { content = AnyView(ArchiveSidebar(a: state.archive)) }
          else { content = AnyView(PhotoSidebar(mode: page)) }
          let root = AnyView(content.environment(state).environment(\.colorScheme, scheme).frame(maxWidth: .infinity, maxHeight: .infinity))
          if let host = pages[page] { host.rootView = root }
          else {
            let host = NSHostingView(rootView: root)
            host.sizingOptions = []
            host.frame = bounds
            host.autoresizingMask = [.width, .height]
            host.isHidden = page != mode
            addSubview(host)
            pages[page] = host
          }
        }
      }
      self.scheme = scheme
      if active != mode {
        if let active, let previous = pages[active], let responder = window?.firstResponder as? NSView,
          responder.isDescendant(of: previous) { window?.makeFirstResponder(nil) }
        for (page, host) in pages { host.isHidden = page != mode }
        active = mode
      }
    }
  }
}
