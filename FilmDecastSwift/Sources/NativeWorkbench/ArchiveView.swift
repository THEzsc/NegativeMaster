import SwiftUI

struct ArchiveSidebar: View {
  @ObservedObject var a: ArchiveState
  var body: some View {
    VStack(spacing: 12) {
      HStack { Text("胶卷档案").font(.headline); Spacer(); Button(action: a.newRoll) { Label("新建胶卷", systemImage: "plus") }.labelStyle(.iconOnly).disabled(a.busy) }.padding(.top,16)
      TextField("搜索名称、相机、地点、标签", text: $a.query).textFieldStyle(.roundedBorder)
      HStack {
        Picker("状态", selection: $a.status) { Text("全部状态").tag(""); ForEach(ArchiveState.statuses, id: \.0) { Text($0.1).tag($0.0) } }
        Picker("年份", selection: $a.year) { Text("全部年份").tag(""); ForEach(a.years, id: \.self) { Text($0).tag($0) } }
      }.labelsHidden()
      Picker("排序", selection: $a.sort) { Text("拍摄日期").tag("date"); Text("最近更新").tag("updated"); Text("名称").tag("title") }
      List(selection: Binding(get: { a.selected }, set: { if let id = $0 { a.select(id) } })) {
        ForEach(a.rolls) { roll in
          HStack(spacing:10) {
            if !roll["cover"].string.isEmpty { CachedPhoto(path: a.assetRoot + roll["cover"].string, size: 160).frame(width:44,height:50) }
            VStack(alignment: .leading, spacing: 4) {
              Text(roll["title"].string).lineLimit(2)
              Text(roll["stock_name"].string).font(.caption).foregroundStyle(.secondary).lineLimit(1)
              Text("\(ArchiveState.statusName(roll["status"].string)) · \(Int(roll["frame_count"].double)) 张").font(.caption).foregroundStyle(.secondary)
            }
          }.padding(.vertical,4).tag(roll["id"].string)
        }
      }.listStyle(.sidebar).padding(.horizontal,-12).disabled(a.busy)
      if !a.loaded && !a.loading { Button("重试载入") { Task { await a.load() } } }
      if a.loaded && a.rolls.isEmpty { Text(a.query.isEmpty && a.status.isEmpty && a.year.isEmpty ? "还没有胶卷，点 + 建立第一卷档案。" : "没有符合筛选条件的胶卷。 ").font(.callout).foregroundStyle(.secondary) }
      HStack {
        Text("\(Int(a.stats["rolls"].double)) 卷 · \(Int(a.stats["frames"].double)) 张").font(.caption).foregroundStyle(.secondary)
        Spacer()
        Menu {
          Button("刷新档案") { Task { await a.refresh() } }
          Button("导出备份…", action: a.backup)
          Button("导入备份…", action: a.chooseRestore)
          Button("显示档案目录") { NSWorkspace.shared.open(URL(fileURLWithPath: a.storage)) }
        } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).fixedSize().disabled(!a.loaded || a.busy)
      }.padding(.bottom,12)
    }.padding(.horizontal,12).task { await a.load() }
  }
}

struct ArchiveDetail: View {
  @ObservedObject var a: ArchiveState
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var body: some View {
    VStack(spacing:0) {
      if a.showArtwork { ArtworkLibrary(a:a) }
      else if a.detail != .null { rollContent }
      else if a.loading || a.selected != nil { ProgressView("正在读取胶卷档案…").frame(maxWidth:.infinity,maxHeight:.infinity) }
      else {
        ContentUnavailableView {
          Label("每一卷，都有来处", systemImage: "archivebox")
        } description: { Text("记录胶片、相机与冲洗信息，把成片和暗盒封面放在一起。") }
        actions: { Button("新建胶卷", action:a.newRoll).disabled(!a.loaded); Button("暗盒图库") { a.showArtwork = true }.disabled(!a.loaded) }
      }
      Divider()
      HStack {
        if a.busy { ProgressView().controlSize(.small) }
        Text(a.notice.isEmpty ? "本地档案 · 原始照片保持原位" : a.notice).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        Spacer()
      }.padding(12)
    }
    .sheet(isPresented:$a.editor) { ArchiveEditor(a:a) }
    .sheet(isPresented:$a.showFrameEditor) { ArchiveFrameEditor(a:a) }
    .alert("档案操作未完成", isPresented:Binding(get:{a.error != nil && !a.editor && !a.showFrameEditor},set:{if !$0 {a.error = nil}})) { Button("好",role:.cancel) { a.error = nil } } message: { Text(a.error ?? "") }
  }
  private var rollContent: some View {
    ScrollView {
      VStack(alignment:.leading,spacing:24) {
        header
        if !a.detail["notes"].string.isEmpty { Text(a.detail["notes"].string).textSelection(.enabled) }
        HStack {
          Text("照片 · \(a.detail["frames"].array.count)").font(.title3.bold())
          Spacer()
          Menu("关联照片") {
            Button("索引照片文件夹…") { a.importFrames() }
            Button("关联文件夹全部照片…") { a.importFrames(all:true) }
            Button("重新关联缺失路径…") { a.importFrames(relink:true) }
          }.disabled(a.busy)
        }
        if a.detail["frames"].array.isEmpty {
          ContentUnavailableView("关联这卷的照片", systemImage:"photo.on.rectangle", description:Text("选择胶卷文件夹，直接索引成片或生成 RAW 轻量预览。"))
        }
        LazyVGrid(columns:[GridItem(.adaptive(minimum:190),spacing:16)],alignment:.leading,spacing:20) {
          ForEach(a.detail["frames"].array) { frame in ArchiveFrameCard(a:a,frame:frame) }
        }
      }.padding(24).frame(maxWidth:1200,alignment:.leading).frame(maxWidth:.infinity)
    }
  }
  private var header: some View {
    HStack(alignment:.top,spacing:24) {
      VStack(spacing:8) {
        if !a.detail["cover"].string.isEmpty { CachedPhoto(path:a.assetRoot+a.detail["cover"].string).frame(width:156,height:170) }
        else { Image(systemName:"film").font(.system(size:44)).foregroundStyle(.tertiary).frame(width:156,height:130) }
        Menu("更换封面") {
          Button("选择暗盒图案") { a.artMatched = !a.detail["stock_id"].string.isEmpty; a.artLimit = 24; a.showArtwork = true }
          Button("导入图片…", action:a.uploadCover)
          Button("清除封面") { a.cover() }
        }.disabled(a.busy)
        if !a.detail["cover_credit"].string.isEmpty { Text(a.detail["cover_credit"].string).font(.caption).foregroundStyle(.secondary).lineLimit(3) }
        SourceLink(title:a.detail["cover_license"].string, path:a.detail["cover_license_url"].string)
        SourceLink(title:"封面来源",path:a.detail["cover_source"].string)
      }.frame(width:156)
      VStack(alignment:.leading,spacing:12) {
        Text(a.detail["title"].string).font(.title.bold()).textSelection(.enabled)
        Text([a.detail["stock_name"].string,a.detail["format"].string,ArchiveState.statusName(a.detail["status"].string)].filter{!$0.isEmpty}.joined(separator:" · ")).foregroundStyle(.secondary)
        ForEach([("相机","camera"),("镜头","lens"),("地点","place"),("拍摄日期","date_start"),("冲洗","development"),("存放","storage")],id:\.1) { label,key in
          if !a.detail[key].string.isEmpty { LabeledContent(label,value:a.detail[key].string) }
        }
        if !a.detail["tags"].array.isEmpty { Text(a.detail["tags"].array.map(\.string).joined(separator:" · ")).font(.callout).foregroundStyle(.secondary) }
        HStack {
          Button("编辑资料…", action:a.editRoll)
          Menu("更多") {
            Button("暗盒图库") { a.showArtwork = true }
            Button("导出档案备份…", action:a.backup)
            Button("删除这卷档案…", role:.destructive, action:a.deleteRoll)
          }
        }.disabled(a.busy)
      }.frame(maxWidth:.infinity,alignment:.leading)
    }
  }
}

struct ArchiveFrameCard: View {
  @ObservedObject var a: ArchiveState
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  let frame: J
  var body: some View {
    VStack(alignment:.leading,spacing:8) {
      Button { a.frameDraft = frame; a.showFrameEditor = true } label: {
        CachedPhoto(path:a.assetRoot+frame["thumb"].string, size:480).frame(height:150).contentShape(Rectangle())
      }.buttonStyle(.plain).accessibilityLabel("查看 \(frame["name"].string)")
      Text(frame["name"].string).font(.callout).lineLimit(1).truncationMode(.middle)
      if frame["missing"].bool { Label("原文件缺失，可重新关联",systemImage:"exclamationmark.triangle").font(.caption).foregroundStyle(.orange) }
      if frame["rating"].double > 0 { Text(String(repeating:"★",count:min(5,max(0,Int(frame["rating"].double))))).foregroundStyle(.orange) }
      if !frame["notes"].string.isEmpty { Text(frame["notes"].string).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
    }.contextMenu {
      Button("查看与备注") { a.frameDraft = frame; a.showFrameEditor = true }
      Button("设为封面") { a.cover(frame:frame["id"].string) }
      Button("在调片中打开") { s.workspace = .develop; s.acceptURLs([URL(fileURLWithPath:frame["path"].string)]) }.disabled(frame["missing"].bool)
      Button("在 Finder 中显示") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:frame["path"].string)]) }.disabled(frame["missing"].bool)
      Button("移除关联…", role:.destructive) { a.removeFrame(frame) }
    }.disabled(a.busy)
  }
}

struct ArchiveEditor: View {
  @ObservedObject var a: ArchiveState
  @State private var stockQuery = ""
  var body: some View {
    VStack(spacing:0) {
      HStack { Text(a.draft["id"].string.isEmpty ? "新建胶卷" : "编辑胶卷").font(.title2.bold()); Spacer() }.padding(20)
      Form {
        Section("胶卷") {
          field("名称","title"); field("胶卷编号","roll_number")
          TextField("搜索胶片型号",text:$stockQuery)
          Picker("型号",selection:Binding(get:{a.draft["stock_id"].string},set:{id in
            a.draft["stock_id"] = .string(id)
            if let stock = a.stocks.first(where:{$0["id"].string == id}) { a.draft["stock_name"] = stock["name"]; a.draft["iso"] = stock["iso"]; a.draft["process"] = stock["process"] }
          })) {
            Text("自定义").tag("")
            ForEach(a.stocks.filter { stockQuery.isEmpty || $0["id"].string == a.draft["stock_id"].string || ArchiveState.searchKey($0["brand"].string+" "+$0["name"].string).contains(ArchiveState.searchKey(stockQuery)) }) { Text($0["brand"].string+" "+$0["name"].string).tag($0["id"].string) }
          }
          field("胶片名称","stock_name"); field("画幅","format")
          integer("标称 ISO","iso"); integer("实拍 EI","exposure_index")
          Picker("状态",selection:text("status")) { ForEach(ArchiveState.statuses,id:\.0) { Text($0.1).tag($0.0) } }
        }
        Section("拍摄") {
          field("相机","camera"); field("镜头","lens"); field("地点","place")
          field("开始日期 · YYYY-MM-DD","date_start"); field("结束日期 · YYYY-MM-DD","date_end")
        }
        Section("冲洗与存放") {
          field("冲洗店","lab"); field("工艺","process"); field("冲洗日期 · YYYY-MM-DD","developed_on")
          field("冲洗记录","development"); field("底片存放","storage")
        }
        Section("备注") {
          TextField("标签，用逗号分隔",text:Binding(get:{a.draft["tags"].array.map(\.string).joined(separator:", ")},set:{a.draft["tags"] = .array($0.replacingOccurrences(of:"，",with:",").split(separator:",").map{.string($0.trimmingCharacters(in:.whitespaces))})}))
          TextEditor(text:text("notes")).frame(minHeight:80).accessibilityLabel("胶卷备注")
        }
        Section("封面来源") {
          field("来源链接","cover_source"); field("作者署名","cover_credit")
          if !a.draft["cover_artwork"].string.isEmpty { Text("内置图案的许可和署名随封面保存。").font(.caption).foregroundStyle(.secondary) }
        }
      }.formStyle(.grouped)
      if let error = a.error { Text(error).font(.callout).foregroundStyle(.red).padding(.horizontal,20).textSelection(.enabled) }
      HStack { Spacer(); Button("取消") { a.error = nil; a.editor = false }.keyboardShortcut(.cancelAction); Button("保存",action:a.saveRoll).keyboardShortcut(.defaultAction).disabled(a.draft["title"].string.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty) }.padding(20)
    }.frame(width:600,height:700).disabled(a.busy).interactiveDismissDisabled(a.busy)
  }
  func text(_ key:String)->Binding<String> { Binding(get:{a.draft[key].string},set:{a.draft[key] = .string($0)}) }
  func field(_ label:String,_ key:String)->some View { TextField(label,text:text(key)) }
  func integer(_ label:String,_ key:String)->some View {
    TextField(label,text:Binding(get:{if case .number(let v) = a.draft[key] { return String(Int(v)) };return a.draft[key].string},set:{value in a.draft[key] = Int(value).map{.number(Double($0))} ?? (value.isEmpty ? .null : .string(value))}))
  }
}

struct ArchiveFrameEditor: View {
  @ObservedObject var a: ArchiveState
  private var framePreviewPath: String {
    let path = a.frameDraft["path"].string
    let ext = URL(fileURLWithPath: path).pathExtension.lowercased()
    if ["jpg", "jpeg", "png", "tif", "tiff", "webp", "bmp"].contains(ext), FileManager.default.fileExists(atPath: path) { return path }
    return a.assetRoot + a.frameDraft["thumb"].string
  }
  var body: some View {
    VStack(alignment:.leading,spacing:16) {
      Text(a.frameDraft["name"].string).font(.title3.bold())
      CachedPhoto(path: framePreviewPath, size:1200).frame(height:320)
      Picker("评分",selection:Binding(get:{Int(a.frameDraft["rating"].double)},set:{a.frameDraft["rating"] = .number(Double($0))})) { Text("未评分").tag(0); ForEach(1...5,id:\.self) { Text("\($0) 星").tag($0) } }
      TextEditor(text:Binding(get:{a.frameDraft["notes"].string},set:{a.frameDraft["notes"] = .string($0)})).frame(height:90).accessibilityLabel("照片备注")
      if let error = a.error { Text(error).font(.callout).foregroundStyle(.red) }
      HStack { Button("设为封面") { a.cover(frame:a.frameDraft["id"].string) }; Spacer(); Button("取消") { a.error = nil; a.showFrameEditor = false }.keyboardShortcut(.cancelAction); Button("保存",action:a.saveFrame).keyboardShortcut(.defaultAction) }
    }.padding(24).frame(width:620).disabled(a.busy).interactiveDismissDisabled(a.busy)
  }
}

struct ArtworkLibrary: View {
  @ObservedObject var a: ArchiveState
  var body: some View {
    VStack(alignment:.leading,spacing:16) {
      HStack { Button { a.showArtwork = false } label: { Label("返回档案",systemImage:"chevron.left") }; Spacer(); Text("暗盒图库").font(.title2.bold()) }
      HStack {
        TextField("搜索胶片、品牌或版本",text:$a.artQuery).textFieldStyle(.roundedBorder)
        Picker("品牌",selection:$a.artBrand) { Text("全部品牌").tag(""); ForEach(Array(Set((a.artworks+a.references).map{$0["brand"].string})).sorted(),id:\.self) { Text($0).tag($0) } }.frame(maxWidth:170)
      }
      Toggle("仅看这卷型号与画幅",isOn:$a.artMatched).disabled(a.detail["stock_id"].string.isEmpty)
      ScrollView {
        VStack(alignment:.leading,spacing:24) {
          Text("内置图案 · \(a.filteredArt.count)").font(.headline)
          if a.filteredArt.isEmpty { Text("当前筛选没有内置图案，可清除筛选或查看下方外部参考。").foregroundStyle(.secondary) }
          LazyVGrid(columns:[GridItem(.adaptive(minimum:190),spacing:20)],alignment:.leading,spacing:24) {
            ForEach(Array(a.filteredArt.prefix(a.artLimit))) { art in
              ArtworkCard(a:a,art:art)
            }
          }
          if a.filteredArt.count > a.artLimit { Button("显示更多图案") { a.artLimit += 24 } }
          DisclosureGroup("包装扫描参考 · \(a.filteredReferences.count)") {
            LazyVStack(alignment:.leading,spacing:14) {
              Text("外部参考以链接打开；不随应用下载。 ").font(.caption).foregroundStyle(.secondary)
              ForEach(Array(a.filteredReferences.prefix(a.artLimit))) { item in SourceLink(title:item["brand"].string+" "+item["name"].string,path:item["source_url"].string) }
              if a.filteredReferences.count > a.artLimit { Button("显示更多参考") { a.artLimit += 24 } }
            }.padding(.top,12)
          }
          DisclosureGroup("资料来源") {
            ForEach(a.sources) { item in
              VStack(alignment:.leading,spacing:5) { SourceLink(title:item["name"].string,path:item["url"].string); Text(item["note"].string).font(.caption).foregroundStyle(.secondary) }.padding(.vertical,6)
            }
          }
        }.padding(.vertical,8)
      }
    }.padding(24).onChange(of:a.artQuery) { _,_ in a.artLimit = 24 }.onChange(of:a.artBrand) { _,_ in a.artLimit = 24 }
  }
}
struct ArtworkCard: View {
  @ObservedObject var a: ArchiveState
  let art:J
  var body: some View {
    VStack(alignment:.leading,spacing:8) {
      CachedPhoto(path:a.artworkRoot+art["file"].string,size:480).frame(height:180)
      Text(art["brand"].string+" "+art["name"].string).font(.headline).lineLimit(2)
      Text(art["variant"].string).font(.caption).foregroundStyle(.secondary).lineLimit(2)
      Text(art["credit"].string).font(.caption).foregroundStyle(.secondary)
      HStack { SourceLink(title:art["license"].string,path:art["license_url"].string); SourceLink(title:"来源",path:art["source_url"].string) }
      Button("设为这卷封面") { a.cover(artwork:art["id"].string) }.disabled(a.detail == .null || a.busy)
    }
  }
}
struct SourceLink: View {
  let title:String
  let path:String
  var body: some View {
    if let url = URL(string:path), ["https","http"].contains(url.scheme ?? ""), url.host != nil {
      Link(title.isEmpty ? "查看来源" : title,destination:url).font(.caption)
    }
  }
}

struct ArchiveBackupButton: View {
  @ObservedObject var a: ArchiveState
  var body: some View {
    Button(action:a.backup) { Label("备份档案",systemImage:"square.and.arrow.up") }.disabled(!a.loaded || a.busy)
  }
}
