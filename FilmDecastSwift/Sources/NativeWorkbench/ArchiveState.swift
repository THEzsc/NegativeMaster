import AppKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor final class ArchiveState: ObservableObject {
  let engine = EngineBridge()
  @Published var loaded = false
  @Published var loading = false
  @Published var busy = false
  @Published var error: String?
  @Published var notice = ""
  @Published var rolls: [J] = []
  @Published var stocks: [J] = []
  @Published var years: [String] = []
  @Published var stats: J = .null
  @Published var selected: String?
  @Published var detail: J = .null
  @Published var query = "" { didSet { refreshSoon() } }
  @Published var status = "" { didSet { refreshSoon() } }
  @Published var year = "" { didSet { refreshSoon() } }
  @Published var sort = "date" { didSet { refreshSoon() } }
  @Published var editor = false
  @Published var draft: J = .null
  @Published var frameDraft: J = .null
  @Published var showFrameEditor = false
  @Published var showArtwork = false
  @Published var artworks: [J] = []
  @Published var references: [J] = []
  @Published var sources: [J] = []
  @Published var artQuery = ""
  @Published var artBrand = ""
  @Published var artMatched = false
  @Published var artLimit = 24
  var storage = ""
  private var searchTask: Task<Void,Never>?
  private var detailTask: Task<Void,Never>?
  private var listRevision = 0
  static let statuses = [("planned","待拍摄"),("shooting","拍摄中"),("developing","冲洗中"),("scanning","待扫描"),("archived","已归档")]
  static func statusName(_ code: String) -> String { statuses.first { $0.0 == code }?.1 ?? code }
  var assetRoot: String { storage + "/assets/" }
  var artworkRoot: String {
    let bundle = Bundle.main.resourceURL?.appendingPathComponent("Engine")
    if let bundle, FileManager.default.fileExists(atPath: bundle.path + "/static/film_artwork") { return bundle.path + "/static/film_artwork/" }
    return URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().path + "/static/film_artwork/"
  }
  var filteredArt: [J] { artworks.filter { matchesArt($0) } }
  var filteredReferences: [J] { references.filter { matchesArt($0) } }
  static func searchKey(_ text: String) -> String {
    var result = text.lowercased()
    for (from,to) in ["柯达":"kodak","富士":"fujifilm","伊尔福":"ilford","福马":"foma","乐凯":"lucky","凤凰":"phoenix","哈曼":"harman","爱克发":"agfa"] { result = result.replacingOccurrences(of:from,with:to) }
    return String(result.filter { $0.isLetter || $0.isNumber })
  }
  func matchesArt(_ art: J) -> Bool {
    let text = ["name","brand","variant"].map { art[$0].string }.joined(separator: " ")
    let stock = detail["stock_id"].string
    return (artQuery.isEmpty || Self.searchKey(text).contains(Self.searchKey(artQuery))) && (artBrand.isEmpty || art["brand"].string == artBrand) && (!artMatched || (!stock.isEmpty && art["stock_ids"].array.contains(.string(stock)) && (detail["format"].string.isEmpty || art["format"].string == detail["format"].string)))
  }
  func load() async {
    guard !loaded, !loading else { return }
    loading = true; error = nil
    do {
      let r = try await engine.api("/api/archive/catalog", method: "GET")
      stocks = r["stocks"].array; storage = r["storage"].string
      let art = try await engine.api("/api/archive/artwork", method: "GET")
      artworks = art["artworks"].array; references = art["references"].array; sources = art["sources"].array
      loaded = true
      await refresh()
    } catch { self.error = error.localizedDescription }
    loading = false
  }
  func refreshSoon() {
    guard loaded else { return }
    searchTask?.cancel()
    searchTask = Task {
      try? await Task.sleep(for: .milliseconds(200))
      guard !Task.isCancelled else { return }
      await refresh()
    }
  }
  func refresh() async {
    listRevision += 1; let token = listRevision
    var components = URLComponents()
    components.queryItems = ["q":query,"status":status,"year":year,"sort":sort].map { URLQueryItem(name: $0.key, value: $0.value) }
    do {
      let r = try await engine.api("/api/archive/rolls?" + (components.percentEncodedQuery ?? ""), method: "GET")
      guard !Task.isCancelled, token == listRevision else { return }
      rolls = r["rolls"].array; years = r["years"].array.map(\.string); stats = r["stats"]
    } catch { if !(error is CancellationError) { self.error = error.localizedDescription } }
  }
  func select(_ id: String) {
    guard !busy, selected != id || detail == .null else { return }
    detailTask?.cancel(); selected = id; detail = .null; showArtwork = false
    detailTask = Task {
      do {
        let r = try await engine.api("/api/archive/rolls/" + id, method: "GET")
        guard !Task.isCancelled, selected == id else { return }
        detail = r["roll"]
      } catch { if !(error is CancellationError) { self.error = error.localizedDescription } }
    }
  }
  func newRoll() {
    guard !busy else { return }
    draft = .object(["title": .string(""), "format": .string("135"), "status": .string("planned"), "tags": .array([])])
    error = nil; editor = true
  }
  func editRoll() { guard detail != .null, !busy else { return }; draft = detail; error = nil; editor = true }
  func saveRoll() {
    guard !busy else { return }
    let draft = draft, id = draft["id"].string
    mutate("/api/archive/rolls" + (id.isEmpty ? "" : "/" + id), body: draft, method: id.isEmpty ? "POST" : "PUT", success: "胶卷资料已保存") { r in
      self.editor = false; self.selected = r["roll"]["id"].string
    }
  }
  func mutate(_ path: String, body: J = .object([:]), method: String = "POST", files: [String:J] = [:], success: String, completion: @escaping (J)->Void = { _ in }) {
    guard !busy else { return }; busy = true; error = nil; notice = "正在处理…"
    Task {
      do {
        let r = try await engine.api(path, body, method: method, files: files)
        if r["roll"] != .null { detail = r["roll"]; selected = detail["id"].string }
        notice = success
        if !r["warnings"].array.isEmpty { notice += " · " + r["warnings"].array.map(\.string).joined(separator: "；") }
        completion(r)
        await refresh()
      } catch { self.error = error.localizedDescription; notice = "未完成，请重试" }
      busy = false
    }
  }
  func deleteRoll() {
    guard let id = selected, !busy else { return }
    let a = NSAlert(); a.messageText = "删除“\(detail["title"].string)”？"; a.informativeText = "删除档案记录和关联，原始照片会保留。"; a.addButton(withTitle: "删除档案"); a.addButton(withTitle: "取消")
    guard a.runModal() == .alertFirstButtonReturn else { return }
    mutate("/api/archive/rolls/" + id, method: "DELETE", success: "已删除档案") { _ in self.selected = nil; self.detail = .null }
  }
  func importFrames(relink: Bool = false, all: Bool = false) {
    guard selected != nil, !busy else { notice = "先选择一卷胶片，再关联照片"; return }
    let p = NSOpenPanel(); p.canChooseDirectories = true; p.canChooseFiles = false; p.prompt = relink ? "重新关联" : "关联照片"
    if p.runModal() == .OK, let u = p.url { addDirectory(u.path, relink: relink, all: all) }
  }
  func addDirectory(_ path: String, relink: Bool = false, all: Bool = false) {
    guard let id = selected else { return }
    mutate("/api/archive/rolls/\(id)/" + (relink ? "relink" : "frames"), body: .object(["directory": .string(path), "mode": .string(all ? "all" : "positive")]), success: relink ? "照片路径已更新" : "照片关联完成")
  }
  func acceptURLs(_ urls: [URL]) {
    guard let first = urls.first, !busy else { return }
    if first.pathExtension.lowercased() == "zip" { restore(first); return }
    if (try? first.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true { addDirectory(first.path) }
    else { notice = "请拖入照片所在的文件夹，或档案备份 ZIP" }
  }
  func cover(artwork: String? = nil, frame: String? = nil) {
    guard let id = selected else { return }
    var body = J.object([:]); if let artwork { body["artwork_id"] = .string(artwork) }; if let frame { body["frame_id"] = .string(frame) }
    mutate("/api/archive/rolls/\(id)/cover", body: body, success: "封面已更新") { _ in self.showArtwork = false }
  }
  func uploadCover() {
    guard let id = selected, !busy else { return }
    let p = NSOpenPanel(); p.allowedContentTypes = [.image]; p.canChooseDirectories = false
    if p.runModal() == .OK, let url = p.url {
      mutate("/api/archive/rolls/\(id)/cover", files: ["file": .string(url.path)], success: "封面已更新；可在资料中补充来源与署名")
    }
  }
  func saveFrame() {
    guard let id = selected else { return }
    mutate("/api/archive/rolls/\(id)/frames/\(frameDraft["id"].string)", body: .object(["notes": frameDraft["notes"], "rating": frameDraft["rating"]]), method: "PUT", success: "照片备注已保存") { _ in self.showFrameEditor = false }
  }
  func removeFrame(_ frame: J) {
    guard let id = selected else { return }
    let a = NSAlert(); a.messageText = "移除这张照片的档案关联？"; a.informativeText = "原始照片会保留。"; a.addButton(withTitle: "移除关联"); a.addButton(withTitle: "取消")
    if a.runModal() == .alertFirstButtonReturn { mutate("/api/archive/rolls/\(id)/frames/\(frame["id"].string)", method: "DELETE", success: "已移除关联") }
  }
  func backup() {
    guard loaded, !busy else { return }
    let p = NSSavePanel(); p.allowedContentTypes = [.zip]; p.nameFieldStringValue = "NegativeMaster-胶卷档案.zip"
    guard p.runModal() == .OK, let url = p.url else { return }
    busy = true
    Task {
      do { _ = try await engine.api("/api/archive/backup", method: "GET", output: url.path); notice = "备份已保存（资料与预览，不含原始照片）"; NSWorkspace.shared.activateFileViewerSelecting([url]) }
      catch { self.error = error.localizedDescription }
      busy = false
    }
  }
  func chooseRestore() {
    guard !busy else { return }
    let p = NSOpenPanel(); p.allowedContentTypes = [.zip]
    if p.runModal() == .OK, let url = p.url { restore(url) }
  }
  func restore(_ url: URL) {
    guard !busy else { return }
    let a = NSAlert(); a.messageText = "导入档案备份？"; a.informativeText = "以新档案加入，不覆盖现有资料。重复导入会产生重复记录。"; a.addButton(withTitle: "导入备份"); a.addButton(withTitle: "取消")
    if a.runModal() == .alertFirstButtonReturn { mutate("/api/archive/restore", files: ["file": .string(url.path)], success: "备份已导入") { r in self.notice = "已导入 \(Int(r["imported"].double)) 卷档案" } }
  }
}
