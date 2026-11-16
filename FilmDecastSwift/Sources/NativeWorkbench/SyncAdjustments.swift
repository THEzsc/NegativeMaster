import SwiftUI

extension WorkbenchState {
  var syncTargets: [String] { visibleCheckedPhotos.map(\.path).filter { $0 != selected } }
  var syncFieldIDs: Set<String> { Set(syncGroups.flatMap { $0["fields"].array.map { $0["id"].string } }) }
  func synchronizeAdjustments(undo: Bool = false) {
    if undo { self.undo(); return }
    guard let path = selected, parameterPath == path else { return }
    performClassicSync(source: params, fields: syncSelected.sorted(), targets: syncTargets, title: "同步调整")
  }
  func openSync(copy: Bool) {
    guard pendingAutoBefore == nil else { commitAutoSync { self.openSync(copy: copy) }; return }
    syncCopyMode = copy; showSyncDialog = true
  }
}

struct ClassicActionBar: View {
  @Environment(WorkbenchState.self) private var s
  var body: some View {
    VStack(spacing: 10) {
      HStack {
        Toggle("自动同步", isOn: Binding(get: { s.autoSync }, set: { enabled in
          if s.pendingAutoBefore != nil { s.commitAutoSync { s.autoSync = enabled } } else { s.autoSync = enabled }
        })).toggleStyle(.checkbox).tint(.orange)
        Spacer()
        Text(s.autoSync ? "影响 \(s.syncTargets.count + (s.selected == nil ? 0 : 1)) 张" : "仅当前照片")
          .font(.caption).foregroundStyle(s.autoSync ? Color.orange : .secondary)
      }
      HStack(spacing: 6) {
        Button("复制…") { s.openSync(copy: true) }
        Button("粘贴", action: s.pasteClassicAdjustments).disabled(s.copiedAdjustments == .null)
        Spacer(minLength: 0)
        Button("同步…") { s.openSync(copy: false) }.disabled(s.syncTargets.isEmpty)
        Button("重置", action: s.resetDevelop)
      }
    }.padding(12).background(.bar)
      .disabled(s.selected == nil || s.parameterPath != s.selected || s.busy)
    if s.applyingSync { Button("停止后续照片") { s.syncStop = true }.padding(.bottom, 8) }
  }
}

struct ClassicSyncSheet: View {
  @Environment(WorkbenchState.self) private var s
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text(s.syncCopyMode ? "复制调整" : "同步调整").font(.title2.bold())
      Text((s.currentPhoto?.name ?? "") + (s.syncCopyMode ? "" : " → \(s.syncTargets.count) 张所选照片"))
        .font(.callout).foregroundStyle(.secondary).lineLimit(1)
      HStack {
        Button("常用") { s.syncSelected = Set(s.syncGroups.filter { $0["selected"].bool }.flatMap { $0["fields"].array.map { $0["id"].string } }) }
        Button("全选") { s.syncSelected = s.syncFieldIDs }
        Button("清空") { s.syncSelected = [] }
        Spacer()
        Text("\(s.syncSelected.count) 项").foregroundStyle(.secondary)
      }
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          ForEach(s.syncGroups) { group in
            let fields = Set(group["fields"].array.map { $0["id"].string })
            DisclosureGroup {
              LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], alignment: .leading, spacing: 10) {
                ForEach(group["fields"].array) { field in
                  Toggle(field["title"].string, isOn: Binding(get: { s.syncSelected.contains(field["id"].string) }, set: { enabled in
                    if enabled { s.syncSelected.insert(field["id"].string) } else { s.syncSelected.remove(field["id"].string) }
                  })).toggleStyle(.checkbox)
                }
              }.padding(.vertical, 8)
            } label: {
              HStack {
                Toggle(group["title"].string, isOn: Binding(get: { fields.isSubset(of: s.syncSelected) }, set: { enabled in
                  if enabled { s.syncSelected.formUnion(fields) } else { s.syncSelected.subtract(fields) }
                })).toggleStyle(.checkbox)
                Spacer()
                Text("\(fields.intersection(s.syncSelected).count)/\(fields.count)").font(.caption).foregroundStyle(.secondary)
              }
            }
          }
        }.padding(4)
      }
      HStack {
        Spacer()
        Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
        Button(s.syncCopyMode ? "复制" : "同步") {
          if s.syncCopyMode { s.copiedAdjustments = s.params; s.copiedFields = s.syncSelected.sorted() }
          else { s.synchronizeAdjustments() }
          dismiss()
        }.keyboardShortcut(.defaultAction).disabled(s.syncSelected.isEmpty || (!s.syncCopyMode && s.syncTargets.isEmpty))
      }
    }.padding(24).frame(width: 520, height: 610)
  }
}

struct ClassicSidebar: View {
  @State private var presetsExpanded = true
  @State private var historyExpanded = true
  @Environment(WorkbenchState.self) private var s
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        DisclosureGroup("预设", isExpanded: $presetsExpanded) {
          VStack(alignment: .leading, spacing: 8) {
            ForEach(s.presetNames, id: \.self) { name in
              Button(name) { s.applyPreset(name) }.buttonStyle(.plain).foregroundStyle(name == s.selectedPreset ? Color.accentColor : .primary)
            }
            Menu("影调风格") { ForEach(ToneLook.all) { look in Button(look.name) { s.applyLook(look) } } }
            Button("存为预设…") { s.askName("preset") }
            Button("删除所选预设", role: .destructive, action: s.deletePreset).disabled(s.selectedPreset.isEmpty)
          }.padding(.top, 8).frame(maxWidth: .infinity, alignment: .leading)
        }
        DisclosureGroup("历史记录", isExpanded: $historyExpanded) {
          VStack(alignment: .leading, spacing: 10) {
            if s.historyTitles.isEmpty { Text("暂无调整").foregroundStyle(.secondary) }
            ForEach(Array(s.historyTitles.enumerated()), id: \.offset) { index, title in
              HStack { Image(systemName: index == 0 ? "circle.fill" : "circle").font(.system(size: 6)); Text(title).lineLimit(1) }
                .foregroundStyle(index == 0 ? .primary : .secondary)
            }
          }.font(.callout).padding(.top, 10).frame(maxWidth: .infinity, alignment: .leading)
        }
      }.padding(16)
    }.disabled(s.busy)
  }
}

struct ClassicExportSheet: View {
  @Environment(WorkbenchState.self) private var s
  @Environment(\.dismiss) private var dismiss
  private var b: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      Text("导出照片").font(.title2.bold())
      Picker("格式", selection: b.exportFormat) { Text("JPEG").tag("jpg"); Text("TIFF").tag("tif"); Text("PNG").tag("png") }
      if s.exportFormat == "tif" { Picker("位深", selection: b.exportBits) { Text("16 位").tag(16); Text("8 位").tag(8) } }
      if s.exportFormat == "jpg" { NumericControl(title: "JPEG 质量", value: b.exportQuality, range: 1...100, step: 1) }
      NumericControl(title: "长边像素 · 0 为原尺寸", value: b.exportResize, range: 0...12000, step: 100)
      HStack { Spacer(); Button("取消") { dismiss() }; Button("导出当前照片…") { dismiss(); s.exportCurrent() }.buttonStyle(.borderedProminent) }
    }.padding(24).frame(width: 440)
  }
}
