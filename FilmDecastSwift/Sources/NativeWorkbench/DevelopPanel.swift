import SwiftUI

/// Collapsing a panel never changes photo parameters or other panels.
struct DevelopPanel<Content: View>: View {
  @Environment(WorkbenchState.self) private var state
  let title: String
  let id: String
  @ViewBuilder let content: () -> Content

  init(_ title: String, id: String, @ViewBuilder content: @escaping () -> Content) {
    self.title = title
    self.id = id
    self.content = content
  }

  private var expanded: Bool { state.expandedDevelopPanels.contains(id) }

  var body: some View {
    Section {
      if expanded {
        content().disabled(state.selected == nil || state.busy)
      }
    } header: {
      Button {
        NSApp?.keyWindow?.makeFirstResponder(nil)
        state.setDevelopPanel(id, expanded: !expanded)
      } label: {
        HStack(spacing: 8) {
          Image(systemName: expanded ? "chevron.down" : "chevron.right")
            .font(.caption.weight(.semibold)).frame(width: 12)
          Text(title).font(.headline)
          Spacer(minLength: 0)
        }
        .foregroundStyle(.primary)
        .frame(maxWidth: .infinity, minHeight: 32, alignment: .leading)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel(title)
      .accessibilityValue(expanded ? "已展开" : "已收起")
      .accessibilityHint(expanded ? "收起此栏" : "展开此栏")
      .id("develop." + id)
    }
  }
}
