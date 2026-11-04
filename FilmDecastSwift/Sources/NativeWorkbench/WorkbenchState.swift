import AppKit
import Observation
import SwiftUI
import UniformTypeIdentifiers

@MainActor @Observable final class WorkbenchState {
  enum Workspace: String, CaseIterable {
    case develop = "调片"
    case sheet = "整卷排版"
    case archive = "胶卷库"
  }
  let engine = EngineBridge()
  let analysisEngine = EngineBridge(background: true)
  let previewEngine = EngineBridge()
  let detailEngine = EngineBridge(background: true, transient: true)
  let archive = ArchiveState()
  var gammaAnalysis: J = .null
  var analyzing = false
  var analysisParams: J = .null
  var analysisPath: String?
  var analysisPaths: [String] = []
  var analysisIsRoll = false
  @ObservationIgnored var analysisTask: Task<Void, Never>?
  var workspace: Workspace = .develop {
    willSet { if newValue != workspace { SwitchPerformance.begin(newValue.rawValue) } }
    didSet {
      guard workspace != oldValue else { return }
      invalidateDetail(resetDemand: true)
      if !selectionTool.isEmpty { selectionTool = "" }
      if zoom != 1 { zoom = 1 }
    }
  }
  var ready = false
  var showHelp = false
  var showPathSheet = false
  var pathEntry = ""
  var resetOnLoad = false
  var busy = false {
    didSet {
      guard busy != oldValue else { return }
      if busy { invalidateDetail() } else { queueDetail() }
    }
  }
  var batchRunning = false
  var rendering = false
  var progress = 0.0
  var status = "正在准备本地图像引擎…"
  var error: String?
  var warnings: [String] = []
  var photos: [Photo] = []
  var selected: String? {
    didSet { if selected != oldValue { invalidateDetail(resetDemand: true) } }
  }
  var checked: Set<String> = []
  var selectionAnchor: String?
  var filmstripBottom = UserDefaults.standard.bool(forKey: "native.filmstripBottom") {
    didSet { UserDefaults.standard.set(filmstripBottom, forKey: "native.filmstripBottom") }
  }
  var thumbnailDone = 0
  var thumbnailTotal = 0
  @ObservationIgnored var thumbnailTask: Task<Void, Never>?
  var showRollAutomation = false
  var automationKind = "crop"
  var automationScope = "visible"
  var automationPhase = "configure"
  var automationRows: [RollSuggestion] = []
  var automationRunning = false
  var automationStop = false
  var automationStopped = false
  var automationDone = 0
  var automationTotal = 0
  var automationName = ""
  var automationError: String?
  var showTransfer = false
  var transferDestination = "sheet"
  var transferScope = "all"
  var transferArchiveID = "new"
  var transferTitle = ""
  var indexingArchive = false
  var indexDone = 0
  var indexTotal = 0
  var indexName = ""
  var stopIndex = false
  var search = ""
  var rawOnly = UserDefaults.standard.bool(forKey: "native.rawOnly") {
    didSet { UserDefaults.standard.set(rawOnly, forKey: "native.rawOnly") }
  }
  var rawExtensions: Set<String> = []
  var showRollExport = false
  var batchScope = "visible"
  var batchDestination = ""
  var batchFinished = false
  var batchTotal = 0
  var batchCompleted = 0
  var batchFailures: [String] = []
  var batchOutputs: [URL] = []
  var batchCurrentName = ""
  var batchError: String?
  var batchCancelled = false
  var folder: URL?
  var params: J = .object([:])
  var defaults: J = .object([:])
  var preview: NSImage?
  var detailImage: NSImage?
  var detailSide = 1500
  @ObservationIgnored var detailLoadedSide = 0
  @ObservationIgnored var detailGeneration = 0
  @ObservationIgnored var detailTask: Task<Void, Never>?
  var negative: NSImage?
  var histogram: J = .null
  var imageSize = CGSize.zero
  var showNegative = false {
    didSet {
      guard showNegative != oldValue else { return }
      invalidateDetail()
      if showNegative { queueNegative() }
      else { negativeTask?.cancel() }
      queueDetail()
    }
  }
  @ObservationIgnored private var negativeTask: Task<Void, Never>?
  private var negativeParams: J = .null
  private var negativePath = ""
  var zoom = 1.0
  var selectionTool = ""
  var cropAspect = "free"
  var useRollReference = true
  var presetNames: [String] = []
  var selectedPreset = ""
  var filmAppliesToRoll = false
  var applyingFilm = false
  var applyingSync = false
  var editingBatch: Bool { applyingFilm || applyingSync }
  var syncGroups: [J] = []
  var syncSelected: Set<String> = []
  var syncScope = "roll"
  var syncUndo: [String: String] = [:]
  @ObservationIgnored var syncTask: Task<Void, Never>?
  @ObservationIgnored var filmTask: Task<Void, Never>?
  var nameEntry = ""
  var showNameSheet = false
  var namePurpose = "preset"
  var referenceName = ""
  var exportFormat = "tif"
  var exportBits = 16
  var exportQuality = 92.0
  var exportResize = 0.0
  var lastExport: URL?
  var inspector = true
  var expandedDevelopPanels = WorkbenchState.migratedDevelopPanels(UserDefaults.standard.stringArray(forKey: "native.expandedDevelopPanels"))
  var requestedDevelopPanel = "light"
  var developPanelJump = 0

  static func migratedDevelopPanels(_ saved: [String]?) -> Set<String> {
    guard let saved else { return ["histogram", "light"] }
    // Keep the existing light ID for Basic and preserve intentionally collapsed panels.
    return Set(saved.map {
      if $0 == "gamma" { return "film" }
      return ["whiteBalance", "color"].contains($0) ? "light" : $0
    })
  }

  func setDevelopPanel(_ id: String, expanded: Bool) {
    if expanded { expandedDevelopPanels.insert(id) } else { expandedDevelopPanels.remove(id) }
    if id == "crop", !expanded, selectionTool == "crop" { selectionTool = "" }
    UserDefaults.standard.set(expandedDevelopPanels.sorted(), forKey: "native.expandedDevelopPanels")
  }

  func revealDevelopPanel(_ id: String) {
    setDevelopPanel(id, expanded: true)
    requestedDevelopPanel = id
    developPanelJump += 1
    inspector = true
  }
  var sheetPane = "film"
  var sheetConfig: J = .object([:])
  var sheetDefaults: J = .object([:])
  var fields: [ControlField] = []
  var stocks: [J] = []
  var stockID = ""
  var stockSearch = ""
  var sheetPhotos: [Photo] = []
  var sheetSelection: Set<Int> = []
  var activeFrame: Int?
  var frames: J = .object([:])
  var sheetImage: NSImage?
  var sheetFrameImage: NSImage?
  var frameView = false
  var frameGrid = true
  var outputDimensions = ""
  var sheetFormat = "png"
  var layoutNames: [String] = []
  var selectedLayout = ""
  var canUndo = false
  var canRedo = false
  var draftAvailable = false
  var sheetJob = ""
  var backgroundPath: String?
  var sheetDirectory = ""
  @ObservationIgnored private var renderTask: Task<Void, Never>?
  @ObservationIgnored private var sheetTask: Task<Void, Never>?
  @ObservationIgnored private var draftTask: Task<Void, Never>?
  @ObservationIgnored var saveTask: Task<Void, Never>?
  @ObservationIgnored private var undoStack: [J] = []
  @ObservationIgnored private var redoStack: [J] = []
  private var lastEdit = Date.distantPast
  private var editKey = ""
  private var revision = 0
  private var renderEpoch = 0
  private var sheetRevision = 0
  private var selectRevision = 0
  var parameterPath: String?
  @ObservationIgnored private var frameTask: Task<Void, Never>?
  var cancelBatch = false

  var filteredPhotos: [Photo] {
    photos.filter {
      (!rawOnly || rawExtensions.contains(URL(fileURLWithPath: $0.path).pathExtension.lowercased()))
        && (search.isEmpty || $0.name.localizedCaseInsensitiveContains(search))
    }
  }
  var currentPhoto: Photo? { photos.first { $0.path == selected } }
  var activePhoto: Photo? { sheetPhotos.first { $0.sheetID == activeFrame } }
  var currentStock: J { stocks.first { $0["id"].string == stockID } ?? .null }
  var selectedOrder: [Int] { sheetPhotos.map(\.sheetID).filter { sheetSelection.contains($0) } }
  var sheetPayload: J {
    var config = sheetConfig
    config["frameOverrides"] = .array(
      selectedOrder.map { frames[String($0)] == .null ? .object([:]) : frames[String($0)] })
    let source = config.at("background.sourceIndex")
    if source != .string("custom") {
      config.put(
        "background.sourceIndex",
        .number(Double(selectedOrder.firstIndex(of: Int(source.double)) ?? 0)))
    }
    return .object([
      "job": .string(sheetJob), "order": .array(selectedOrder.map { .number(Double($0)) }),
      "config": config, "stockId": .string(stockID),
    ])
  }
  var snapshot: J {
    .object([
      "workspace": .string(workspace.rawValue), "params": params, "config": sheetConfig,
      "cropAspect": .string(cropAspect),
      "stock": .string(stockID), "frames": frames,
      "order": .array(sheetPhotos.map { .number(Double($0.sheetID)) }),
      "selection": .array(sheetSelection.sorted().map { .number(Double($0)) }),
    ])
  }
  func remember(_ key: String = UUID().uuidString) {
    if key != editKey || Date().timeIntervalSince(lastEdit) > 0.6 {
      undoStack.append(snapshot)
      if undoStack.count > 80 { undoStack.removeFirst() }
    }
    lastEdit = Date()
    editKey = key
    redoStack.removeAll()
    historyFlags()
  }
  private func historyFlags() {
    canUndo = !undoStack.isEmpty
    canRedo = !redoStack.isEmpty
  }
  private func restore(_ s: J) {
    workspace = Workspace(rawValue: s["workspace"].string) ?? .develop
    params = s["params"]
    if case .string(let aspect) = s["cropAspect"] { cropAspect = aspect }
    sheetConfig = s["config"]
    stockID = s["stock"].string
    frames = s["frames"]
    let order = s["order"].array.map { Int($0.double) }
    sheetPhotos.sort {
      (order.firstIndex(of: $0.sheetID) ?? 0) < (order.firstIndex(of: $1.sheetID) ?? 0)
    }
    sheetSelection = Set(s["selection"].array.map { Int($0.double) })
    queueRender()
    queueSheet()
    persistSoon()
    historyFlags()
  }
  func undo() {
    guard !editingBatch else { return }
    guard let s = undoStack.popLast() else { return }
    redoStack.append(snapshot)
    restore(s)
  }
  func redo() {
    guard !editingBatch else { return }
    guard let s = redoStack.popLast() else { return }
    undoStack.append(snapshot)
    restore(s)
  }
  func failure(_ e: Error) {
    if e is CancellationError { return }
    error = e.localizedDescription
    status = "操作未完成"
  }
  func bootstrap() async {
    do {
      let r = try await engine.call(.object(["action": .string("bootstrap")]))
      rawExtensions = Set(r["rawExtensions"].array.map(\.string))
      defaults = r["defaults"]
      params = defaults
      sheetDefaults = r["sheetDefaults"]
      sheetConfig = sheetDefaults
      fields = r["fields"].array.map { ControlField(value: $0) }
      stocks = r["stocks"].array
      syncGroups = r["syncGroups"].array
      syncSelected = Set(syncGroups.filter { $0["selected"].bool }.map { $0["id"].string })
      presetNames = r["presets"].array.map(\.string)
      if let first = stocks.first { applyStock(first["id"].string, record: false) }
      layoutNames = layouts.object.keys.sorted()
      draftAvailable = UserDefaults.standard.data(forKey: "native.sheet.draft") != nil
      ready = true
      status = "打开底片开始调片，或导入成片制作整卷排版"
    } catch { failure(error) }
  }
  func setParam(_ key: String, _ value: J) {
    guard !editingBatch else { return }
    remember("p." + key)
    params.put(key, value)
    if ["crop_rect", "level_angle"].contains(key) { params["geometry_source"] = .string("manual") }
    queueRender()
    persistSoon()
  }
  func setConfig(_ key: String, _ value: J) {
    remember("s." + key)
    sheetConfig.put(key, value)
    queueSheet()
  }
  func setFrame(_ key: String, _ value: J) {
    guard let activeFrame else { return }
    remember("frame." + key)
    var f = frames[String(activeFrame)]
    f.put(key, value)
    frames[String(activeFrame)] = f
    queueSheet()
  }
  func frameValue(_ key: String, fallback: J = .null) -> J {
    let v = frames[String(activeFrame ?? -1)].at(key)
    return v == .null ? fallback : v
  }
  func rotateFrame(_ delta: Int) {
    let initial = activePhoto.map { $0.height > $0.width ? 90 : 0 } ?? 0
    let current = Int(frameValue("rotation", fallback: .number(Double(initial))).double)
    setFrame("rotation", .number(Double((current + delta + 360) % 360)))
  }
  func resetFrame() {
    guard let activeFrame else { return }
    remember()
    let label = frameValue("label")
    frames[String(activeFrame)] = .object(["label": label])
    queueSheet()
  }
  func openEnteredPath() {
    let text = pathEntry.trimmingCharacters(in: .whitespacesAndNewlines)
    let path = (text as NSString).expandingTildeInPath
    guard FileManager.default.fileExists(atPath: path) else {
      error = "这个路径不存在，请检查后重试。"
      return
    }
    showPathSheet = false
    acceptURLs([URL(fileURLWithPath: path)])
  }
  func flushBeforeQuit() async {
    await filmTask?.value
    await syncTask?.value
    saveTask?.cancel()
    renderTask?.cancel()
    invalidateDetail(resetDemand: true)
    sheetTask?.cancel()
    frameTask?.cancel()
    thumbnailTask?.cancel()
    saveDraft(immediately: true)
    await draftTask?.value
    guard let selected, parameterPath == selected else { return }
    do {
      _ = try await engine.call(
        .object([
          "action": .string("save"),
          "body": .object(["path": .string(selected), "params": params, "sidecar": .bool(true)]),
        ]))
    } catch { NSLog("NegativeMaster: final save failed: %@", error.localizedDescription) }
  }
  func chooseFolder() {
    if workspace == .archive { archive.importFrames(); return }
    let p = NSOpenPanel()
    p.canChooseDirectories = true
    p.canChooseFiles = false
    p.prompt = "打开胶卷"
    if p.runModal() == .OK, let u = p.url {
      if workspace == .sheet { prepareSheet(directory: u.path) } else { openFolder(u) }
    }
  }
  func chooseFiles() {
    if workspace == .archive { archive.importFrames(); return }
    let p = NSOpenPanel()
    p.canChooseFiles = true
    p.canChooseDirectories = false
    p.allowsMultipleSelection = true
    p.prompt = "导入照片"
    if p.runModal() == .OK { acceptURLs(p.urls) }
  }
  func acceptURLs(_ urls: [URL]) {
    if workspace == .archive { archive.acceptURLs(urls); return }
    guard ready, !busy, let first = urls.first else { return }
    if first.pathExtension.lowercased() == "zip" {
      importProject(first)
      return
    }
    if (try? first.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
      if workspace == .sheet { prepareSheet(directory: first.path) } else { openFolder(first) }
      return
    }
    if workspace == .sheet {
      prepareSheet(paths: urls.map(\.path), positiveOnly: true)
    } else {
      stopThumbnailGeneration()
      photos = urls.map { Photo(path: $0.path, name: $0.lastPathComponent) }
      folder = first.deletingLastPathComponent()
      selectPhoto(first.path)
    }
  }
  func openFolder(_ u: URL) {
    guard !editingBatch else { return }
    invalidateDetail(resetDemand: true)
    stopThumbnailGeneration()
    persistNow()
    selected = nil
    preview = nil
    busy = true
    status = "正在读取胶卷…"
    folder = u
    Task {
      do {
        let q =
          u.path.addingPercentEncoding(
            withAllowedCharacters: .urlQueryAllowed.subtracting(CharacterSet(charactersIn: "&+#?")))
          ?? ""
        let r = try await engine.api("/api/list?dir=" + q, method: "GET")
        let edits = Set(r["edited"].array.map(\.string))
        photos = r["files"].array.map {
          Photo(
            path: $0.string, name: URL(fileURLWithPath: $0.string).lastPathComponent,
            edited: edits.contains($0.string))
        }
        checked.removeAll()
        selectionAnchor = nil
        busy = false
        if let first = filteredPhotos.first {
          selectPhoto(first.path)
        } else {
          selected = nil
          preview = nil
          status = "此文件夹没有支持的照片"
        }
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  func select(_ path: String) {
    guard !editingBatch else { return }
    guard selected != path else { return }
    invalidateDetail(resetDemand: true)
    persistNow()
    selectRevision += 1
    let token = selectRevision
    selected = path
    preview = nil
    negative = nil
    zoom = 1
    selectionTool = ""
    showNegative = false
    undoStack = []
    redoStack = []
    historyFlags()
    renderTask?.cancel()
    renderTask = nil
    renderEpoch += 1
    negativeTask?.cancel()
    revision += 1
    status = "正在载入 \(URL(fileURLWithPath:path).lastPathComponent)…"
    guard ready else { return }
    Task {
      do {
        let r = try await engine.call(
          .object(["action": .string("adjustments"), "body": .object(["path": .string(path)])]))
        guard token == selectRevision else { return }
        params = resetOnLoad ? defaults : r["params"]
        if !resetOnLoad, r["data"].object.isEmpty,
          let data = UserDefaults.standard.data(forKey: "FilmDecastParams::" + path),
          let old = try? J(data: data)
        {
          params = migrateLegacy(old)
        }
        parameterPath = path
        let referencePath = params["reference_path"].string
        referenceName = referencePath.isEmpty ? "" : URL(fileURLWithPath: referencePath).lastPathComponent
        queueRender()
      } catch {
        guard token == selectRevision else { return }
        failure(error)
      }
    }
  }
  func removePhotoFromList(_ path: String) {
    guard !busy, !analyzing, photos.contains(where: { $0.path == path }) else { return }
    let visible = filteredPhotos.map(\.path)
    let index = visible.firstIndex(of: path) ?? 0
    let wasActive = selected == path
    photos.removeAll { $0.path == path }
    checked.remove(path)
    if selectionAnchor == path { selectionAnchor = nil }
    guard wasActive else { return }
    selectedPreset = ""
    let remaining = filteredPhotos.map(\.path)
    if !remaining.isEmpty {
      let next = remaining[min(index, remaining.count - 1)]
      // select saves the outgoing photo's edits before loading its neighbour.
      select(next)
      checked.insert(next)
      selectionAnchor = next
    } else {
      persistNow()
      selectRevision += 1
      renderTask?.cancel(); renderTask = nil; renderEpoch += 1; revision += 1
      negativeTask?.cancel()
      selected = nil; parameterPath = nil
      preview = nil; negative = nil; histogram = .null; imageSize = .zero
      params = defaults; gammaAnalysis = .null
      showNegative = false; selectionTool = ""; rendering = false
      undoStack = []; redoStack = []; historyFlags()
      status = photos.isEmpty ? "打开底片开始调片" : "没有符合筛选条件的照片"
    }
  }
  private func migrateLegacy(_ old: J) -> J {
    var p = defaults
    let mapping = [
      "rotate": "rotate", "blackPct": "black_pct", "whitePct": "white_pct", "gamma": "gamma",
      "contrast": "contrast", "saturation": "saturation", "temperature": "temp", "tint": "tint",
      "denoise": "denoise", "sharpen": "sharpen", "sharpenRadius": "sharpen_radius",
      "exposure": "exposure", "highlights": "highlights", "shadows": "shadows", "whites": "whites",
      "blacks": "blacks", "vignette": "vignette", "wbPoint": "wb_point",
    ]
    for (a, b) in mapping where old[a] != .null { p[b] = old[a] }
    p["mode"] = .string(
      old["mode"].string == "bwNegative"
        ? "bw" : old["mode"].string == "positive" ? "positive" : "color")
    p["wb"] = .string(old["wb"].string == "none" ? "none" : "gray")
    if old["flipH"].bool && old["flipV"].bool {
      p["rotate"] = .number(Double((Int(p["rotate"].double) + 180) % 360))
    } else {
      p["flip"] = .string(old["flipH"].bool ? "h" : old["flipV"].bool ? "v" : "none")
    }
    for (a, b) in [
      "cropRect": "crop_rect", "wbRect": "wb_rect", "filmBaseRect": "film_base_rect",
      "shadowRect": "shadow_rect", "highlightRect": "highlight_rect",
    ] where old[a] != .null { p[b] = .array(["x0", "y0", "x1", "y1"].map { old[a][$0] }) }
    p["emulsion_mirrored"] = .bool(["h", "v"].contains(p["flip"].string))
    return p
  }
  func persistSoon() {
    guard !editingBatch else { return }
    saveTask?.cancel()
    guard let path = selected, parameterPath == path else { return }
    let p = params
    saveTask = Task {
      try? await Task.sleep(for: .milliseconds(600))
      guard !Task.isCancelled else { return }
      do {
        _ = try await engine.call(
          .object([
            "action": .string("save"),
            "body": .object(["path": .string(path), "params": p, "sidecar": .bool(true)]),
          ]))
      } catch { failure(error) }
    }
  }
  func persistNow(sidecar: Bool = true) {
    guard !editingBatch else { return }
    saveTask?.cancel()
    guard let path = selected, parameterPath == path else { return }
    let p = params
    saveTask = Task {
      do {
        _ = try await engine.call(
          .object([
            "action": .string("save"),
            "body": .object(["path": .string(path), "params": p, "sidecar": .bool(sidecar)]),
          ]))
        if sidecar {
          status = "已保存 XML 调整参数"
          if let i = photos.firstIndex(where: { $0.path == path }) { photos[i].edited = true }
        }
      } catch { failure(error) }
    }
  }
  /// One in-flight preview plus the latest parameters; dragging never queues a backlog.
  func queueRender() {
    invalidateDetail()
    revision += 1
    guard selected != nil, parameterPath == selected, ready else { return }
    rendering = true
    guard renderTask == nil else { return }
    renderEpoch += 1
    let epoch = renderEpoch
    renderTask = Task {
      defer {
        if epoch == renderEpoch { renderTask = nil; rendering = false; queueDetail() }
      }
      do {
        while !Task.isCancelled {
          guard let path = selected, parameterPath == path else { return }
          let token = revision, p = params
          try await renderPreview(path, params: p, interactive: true, token: token)
          try Task.checkCancellation()
          if token != revision { continue }
          for _ in 0..<6 {
            try await Task.sleep(for: .milliseconds(20))
            if token != revision { break }
          }
          if token != revision { continue }
          try await renderPreview(path, params: p, interactive: false, token: token)
          if token == revision {
            if showNegative { queueNegative() }
            return
          }
        }
      } catch { if epoch == renderEpoch { failure(error) } }
    }
  }
  private func renderPreview(_ path: String, params p: J, interactive: Bool, token: Int) async throws {
    let r = try await previewEngine.call(.object([
      "action": .string("render"), "body": .object([
        "path": .string(path), "params": p, "interactive": .bool(interactive),
        "include_negative": .bool(false)
      ])
    ]))
    let decoded = await ImagePipeline.preview(r["bytes"])
    guard !Task.isCancelled, selected == path, parameterPath == path else { return }
    // Show intermediate tone feedback during a drag, but never stale geometry.
    guard ["rotate", "flip", "crop_rect", "level_angle"].allSatisfy({ p[$0] == params[$0] }) else { return }
    if !interactive && token != revision { return }
    preview = decoded.map { NSImage(cgImage: $0, size: .zero) }
    histogram = r["histogram"]
    imageSize = CGSize(width: r["fullWidth"].double, height: r["fullHeight"].double)
    status = "\(URL(fileURLWithPath: path).lastPathComponent) · \(Int(imageSize.width)) × \(Int(imageSize.height))"
  }
  func queueNegative() {
    guard let path = selected, parameterPath == path, showNegative else { return }
    let p = params
    guard path != negativePath || p != negativeParams || negative == nil else { return }
    negativeTask?.cancel()
    negative = nil
    negativeTask = Task {
      do {
        let r = try await previewEngine.call(.object(["action": .string("negative"), "body": .object(["path": .string(path), "params": p])]))
        let decoded = await ImagePipeline.preview(r["bytes"])
        guard !Task.isCancelled, selected == path, params == p else { return }
        negative = decoded.map { NSImage(cgImage: $0, size: .zero) }
        negativePath = path; negativeParams = p
      } catch { failure(error) }
    }
  }
  func rotate(_ delta: Int) {
    guard !editingBatch, delta % 90 == 0 else { return }
    let turns = (delta / 90 % 4 + 4) % 4
    guard turns != 0 else { return }
    remember()
    let operation: DevelopOrientation = turns == 3 ? .counterclockwise : .clockwise
    for _ in 0..<(turns == 3 ? 1 : turns) {
      params = operation.applying(to: params)
      cropAspect = operation.aspect(cropAspect)
    }
    queueRender()
    persistSoon()
  }
  func mirror(_ axis: String) {
    guard !editingBatch, axis == "h" || axis == "v" else { return }
    remember()
    params = (axis == "h" ? DevelopOrientation.horizontal : .vertical).applying(to: params)
    queueRender()
    persistSoon()
  }
  func autoCrop() {
    guard let path = selected else { return }
    busy = true
    var b = params
    b["path"] = .string(path)
    b["level"] = .bool(true)
    b["use_reference"] = .bool(useRollReference)
    Task {
      do {
        let r = try await previewEngine.call(.object(["action": .string("autocrop"), "body": b]))
        if selected == path {
          remember()
          if r["status"].string != "uncertain", r["rect"] != .null {
            params["crop_rect"] = r["rect"]
            params["level_angle"] = r["angle"]
            params["geometry_source"] = .string("auto")
            warnings = r["warnings"].array.map(\.string)
            selectionTool = "crop"
            revealDevelopPanel("crop")
            queueRender()
            persistSoon()
          }
          status = r["status"].string == "uncertain" ? "未找到可靠片框，已保留当前裁剪与角度" : "自动裁剪与校平完成"
        }
        busy = false
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  func commitSample(_ key: String, rect: [Double]) {
    guard key == "wb_rect", let path = selected else {
      setParam(key, .doubles(rect))
      return
    }
    let token = revision
    var b = params
    b["path"] = .string(path)
    b["wb_rect"] = .doubles(rect)
    Task {
      do {
        let r = try await engine.call(.object(["action": .string("wbtemp"), "body": b]))
        guard selected == path, revision == token else { return }
        remember()
        params["temp"] = r["temp"]
        params["tint"] = r["tint"]
        params["wb_rect"] = .null
        params["wb_point"] = .null
        queueRender()
        persistSoon()
      } catch { failure(error) }
    }
  }
  func resetDevelop() {
    guard !editingBatch else { return }
    remember()
    params = defaults
    queueRender()
    persistSoon()
  }
  func pickReference() {
    let p = NSOpenPanel()
    p.canChooseFiles = true
    p.canChooseDirectories = false
    p.allowsMultipleSelection = false
    p.allowedContentTypes = [.image]
    guard p.runModal() == .OK, let url = p.url else { return }
    Task {
      do {
        _ = try await engine.api("/api/loadref", .object(["path": .string(url.path)]))
        referenceName = url.lastPathComponent
        setParam("reference_path", .string(url.path))
        setParam("use_match", .bool(true))
      } catch { failure(error) }
    }
  }
  func clearReference() {
    Task {
      do {
        _ = try await engine.api("/api/loadref", .object(["path": .string("")]))
        referenceName = ""
        setParam("reference_path", .null)
        setParam("use_match", .bool(false))
      } catch { failure(error) }
    }
  }
  func applyPreset(_ name: String) {
    guard !name.isEmpty, !busy else { return }
    if filmAppliesToRoll {
      applyFilmToRoll(.object(["preset": .string(name)]))
      return
    }
    let path = selected, selection = selectRevision
    Task {
      do {
        let r = try await engine.api("/api/presets?name=" + escaped(name), method: "GET")
        guard selected == path, selectRevision == selection, !editingBatch else { return }
        remember()
        for (k, v) in r["data"].object { params[k] = v }
        selectedPreset = name
        queueRender()
        persistSoon()
      } catch { failure(error) }
    }
  }
  func setFilmMode(_ mode: String) {
    guard !busy, ["color", "bw", "positive"].contains(mode) else { return }
    if filmAppliesToRoll {
      applyFilmToRoll(.object(["mode": .string(mode)]))
    } else {
      setParam("mode", .string(mode))
      selectedPreset = ""
    }
  }
  var emulsionMirrored: Bool { DevelopOrientation.emulsionMirrored(params) }
  func setEmulsionMirrored(_ enabled: Bool) {
    guard !busy, !editingBatch, selected != nil else { return }
    if filmAppliesToRoll {
      applyFilmToRoll(.object(["emulsion": .bool(enabled)]))
    } else {
      remember()
      params = DevelopOrientation.applyingEmulsion(enabled, to: params)
      gammaAnalysis = .null
      queueRender(); persistSoon()
    }
  }
  var filmTargetPaths: [String] { photos.map(\.path) }
  func applyFilmToRoll(_ change: J) {
    guard !busy, let active = selected, parameterPath == active, !filmTargetPaths.isEmpty else { return }
    let paths = filmTargetPaths, current = params
    saveTask?.cancel()
    busy = true; applyingFilm = true; progress = 0
    status = "正在应用到整卷…"
    filmTask = Task {
      defer { busy = false; applyingFilm = false }
      do {
        // Drain pending writes on the serial transport before reading individual frames.
        _ = try await engine.call(.object(["action": .string("save"), "body": .object([
          "path": .string(active), "params": current, "sidecar": .bool(true)
        ])]))
        await applyFilmChanges(paths: paths, change: change) { try await self.engine.call($0) }
      } catch { failure(error) }
    }
  }
  func applyFilmChanges(paths: [String], change: J, request: (J) async throws -> J) async {
    var completed = 0, issues: [String] = []
    for (i, path) in paths.enumerated() {
      do {
        let snapshot = try await request(.object(["action": .string("batch_snapshot"), "body": .object(["path": .string(path)])]))
        var body = change
        body["path"] = .string(path); body["token"] = snapshot["token"]
        let result = try await request(.object(["action": .string("film_apply"), "body": body]))
        if selected == path, parameterPath == path {
          remember(); params = result["params"]
          selectedPreset = change["preset"].string
          gammaAnalysis = .null; queueRender()
        }
        if let index = photos.firstIndex(where: { $0.path == path }) { photos[index].edited = true }
        completed += 1
        issues += result["warnings"].array.map { URL(fileURLWithPath: path).lastPathComponent + "：" + $0.string }
      } catch { issues.append(URL(fileURLWithPath: path).lastPathComponent + "：" + error.localizedDescription) }
      progress = Double(i + 1) / Double(paths.count)
    }
    status = "已应用到 \(completed) / \(paths.count) 张照片"
    if !issues.isEmpty { error = issues.joined(separator: "\n") }
  }
  func askName(_ purpose: String) {
    namePurpose = purpose
    nameEntry = ""
    showNameSheet = true
  }
  func saveNamed() {
    let name = nameEntry.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !name.isEmpty else { return }
    showNameSheet = false
    if namePurpose == "layout" {
      var l = layouts
      l[name] = .object(["config": sheetConfig, "stockId": .string(stockID)])
      UserDefaults.standard.set(l.data, forKey: "native.layouts")
      layoutNames = l.object.keys.sorted()
      selectedLayout = name
      return
    }
    Task {
      do {
        let r = try await engine.api(
          "/api/presets", .object(["name": .string(name), "data": params]))
        presetNames = r["names"].array.map(\.string)
        selectedPreset = name
      } catch { failure(error) }
    }
  }
  func deletePreset() {
    guard !selectedPreset.isEmpty else { return }
    let n = selectedPreset
    Task {
      do {
        let r = try await engine.api("/api/presets?name=" + escaped(n), method: "DELETE")
        presetNames = r["names"].array.map(\.string)
        selectedPreset = ""
      } catch { failure(error) }
    }
  }
  func escaped(_ value: String) -> String {
    value.addingPercentEncoding(
      withAllowedCharacters: .urlQueryAllowed.subtracting(CharacterSet(charactersIn: "&+#?"))) ?? ""
  }
  func exportCurrent() {
    if workspace == .archive { archive.backup(); return }
    if workspace == .sheet {
      exportSheet()
      return
    }
    guard let path = selected else { return }
    let p = NSSavePanel()
    p.allowedContentTypes = [exportFormat == "jpg" ? .jpeg : exportFormat == "png" ? .png : .tiff]
    p.nameFieldStringValue =
      URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent + "_pos." + exportFormat
    guard p.runModal() == .OK, let u = p.url else { return }
    let settings = params
    busy = true
    status = "正在导出全分辨率照片…"
    Task {
      do {
        _ = try await exportPhoto(path, params: settings, to: u)
        busy = false
        lastExport = u
        status = "已导出 \(u.lastPathComponent)"
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  private func exportPhoto(_ path: String, params: J, to url: URL) async throws -> J {
    try await engine.call(
      .object([
        "action": .string("export"),
        "body": .object([
          "path": .string(path), "params": params, "out": .string(url.path),
          "bits": .number(exportFormat == "tif" ? Double(exportBits) : 8),
          "quality": .number(exportQuality), "resize": .number(exportResize),
        ]),
      ]))
  }
  func exportBatch() { presentRollExport(selectedOnly: true) }
  func cancelOperation() {
    cancelBatch = true
    status = "当前照片处理完成后停止"
  }
  func applyStock(_ id: String, record: Bool = true) {
    guard let s = stocks.first(where: { $0["id"].string == id }) else { return }
    if record { remember() }
    stockID = id
    sheetConfig.put("strip.edgeText", s["edge_text"])
    sheetConfig.put("strip.secondaryText", s["edge_secondary"])
    sheetConfig.put("strip.edgeColor", s["edge_color"])
    sheetConfig.put("strip.fontStyle", .string("auto"))
    sheetConfig.put("header.title", s["name"])
    sheetConfig.put("header.process", s["process"])
    queueSheet()
  }
  func prepareSheet(
    directory: String? = nil, paths: [String] = [], positiveOnly: Bool = false, restoring: J? = nil
  ) {
    guard !busy else { return }
    busy = true
    warnings = []
    status = "正在准备整卷照片…"
    workspace = .sheet
    sheetTask?.cancel()
    var body: J = .object([:])
    if let directory {
      body["directory"] = .string(directory)
    } else {
      body["paths"] = .array(paths.map(J.string))
      body["positiveOnly"] = .bool(positiveOnly)
    }
    Task {
      do {
        let r = try await engine.api("/api/sheet/prepare", body)
        try await finishPrepare(r["job"].string, restoring: restoring)
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  private func finishPrepare(_ id: String, restoring: J? = nil) async throws {
    var result: J = .null
    for _ in 0..<3600 {
      result = try await engine.api("/api/sheet/job/" + id, method: "GET")
      status = result["message"].string
      progress = result["done"].double / max(1, result["total"].double)
      if result["state"].string == "failed" {
        throw WorkbenchError(
          message: status + "\n" + result["warnings"].array.map(\.string).joined(separator: "\n"))
      }
      if result["state"].string == "ready" { break }
      try await Task.sleep(for: .milliseconds(300))
    }
    guard result["state"].string == "ready" else {
      throw WorkbenchError(message: "准备照片超时，请减少一次导入的照片数量后重试。")
    }
    sheetJob = id
    sheetDirectory = result["directory"].string
    sheetPhotos = result["items"].array.map {
      Photo(
        path: $0["path"].string, name: $0["name"].string, sheetID: Int($0["id"].double),
        width: $0["width"].double, height: $0["height"].double, source: $0["source"].string)
    }
    sheetSelection = Set(sheetPhotos.map(\.sheetID))
    frames = .object([:])
    backgroundPath = result["backgroundFile"].string.isEmpty ? nil : result["backgroundFile"].string
    frameView = false
    sheetImage = nil
    sheetFrameImage = nil
    if let r = restoring {
      sheetConfig = r["config"]
      stockID = r["stockId"].string
      let sourcePaths =
        r["allSources"].array.isEmpty
        ? r["sources"].array.map(\.string) : r["allSources"].array.map(\.string)
      sheetPhotos.sort {
        (sourcePaths.firstIndex(of: $0.path) ?? 0) < (sourcePaths.firstIndex(of: $1.path) ?? 0)
      }
      let selectedPaths = Set(r["sources"].array.map(\.string))
      sheetSelection = Set(sheetPhotos.filter { selectedPaths.contains($0.path) }.map(\.sheetID))
      for p in sheetPhotos { frames[String(p.sheetID)] = r["frameOptions"][p.path] }
      if let bg = sheetPhotos.first(where: { $0.path == r["backgroundSourcePath"].string }) {
        sheetConfig.put("background.sourceIndex", .number(Double(bg.sheetID)))
      }
      let custom = r["backgroundFile"].string
      if !custom.isEmpty {
        _ = try await engine.api(
          "/api/sheet/background", .object(["job": .string(id)]), files: ["file": .string(custom)])
        backgroundPath = custom
      }
    }
    warnings = result["warnings"].array.map(\.string)
    busy = false
    activeFrame = sheetPhotos.first?.sheetID
    undoStack = []
    redoStack = []
    historyFlags()
    queueSheet()
  }
  func queueSheet() {
    sheetTask?.cancel()
    sheetRevision += 1
    let token = sheetRevision
    guard ready, !sheetJob.isEmpty else { return }
    saveDraft()
    if frameView { queueFrame() }
    guard !sheetSelection.isEmpty else {
      sheetImage = nil
      outputDimensions = "未选择照片"
      return
    }
    let payload = sheetPayload
    rendering = true
    sheetTask = Task {
      do {
        try await Task.sleep(for: .milliseconds(220))
        try Task.checkCancellation()
        let r = try await engine.api("/api/sheet/preview", payload)
        let decoded = await ImagePipeline.preview(r["bytes"])
        guard !Task.isCancelled, token == sheetRevision else { return }
        sheetImage = decoded.map { NSImage(cgImage: $0, size: .zero) }
        outputDimensions = "\(r["width"].string) × \(r["height"].string) px"
        rendering = false
        if !busy { status = "\(selectedOrder.count) 张照片 · \(outputDimensions)" }
      } catch {
        guard token == sheetRevision else { return }
        rendering = false
        failure(error)
      }
    }
  }
  func activateFrame(_ id: Int) {
    activeFrame = id
    frameView = true
    sheetFrameImage = nil
    queueFrame()
  }
  func queueFrame() {
    frameTask?.cancel()
    guard let id = activeFrame, !sheetJob.isEmpty else { return }
    let job = sheetJob
    let b = J.object([
      "job": .string(job), "id": .number(Double(id)),
      "override": frames[String(id)] == .null ? .object([:]) : frames[String(id)],
      "ratio": sheetConfig["ratio"], "fit": sheetConfig.at("strip.fit"),
    ])
    frameTask = Task {
      do {
        try await Task.sleep(for: .milliseconds(120))
        let r = try await engine.call(.object(["action": .string("frame"), "body": b]))
        let decoded = await ImagePipeline.preview(r["bytes"])
        guard !Task.isCancelled, activeFrame == id, sheetJob == job else { return }
        sheetFrameImage = decoded.map { NSImage(cgImage: $0, size: .zero) }
      } catch { failure(error) }
    }
  }
  func updateCropAspect() {
    selectionTool = "crop"
    let ratios: [String: Double] = [
      "3:2": 1.5, "2:3": 2.0 / 3, "4:3": 4.0 / 3, "3:4": 3.0 / 4, "1:1": 1, "6:7": 6.0 / 7,
      "7:6": 7.0 / 6,
    ]
    guard let ratio = ratios[cropAspect], let image = preview else { return }
    let normalized = ratio * image.size.height / max(1, image.size.width)
    let old = params["crop_rect"].array.map(\.double)
    let centerX = old.count == 4 ? (old[0] + old[2]) / 2 : 0.5
    let centerY = old.count == 4 ? (old[1] + old[3]) / 2 : 0.5
    let width = min(1, normalized)
    let height = width / normalized
    let x = min(max(0, centerX - width / 2), 1 - width)
    let y = min(max(0, centerY - height / 2), 1 - height)
    setParam("crop_rect", .doubles([x, y, x + width, y + height]))
  }

  func moveFrame(_ delta: Int) {
    guard let i = sheetPhotos.firstIndex(where: { $0.sheetID == activeFrame }),
      sheetPhotos.indices.contains(i + delta)
    else { return }
    remember()
    sheetPhotos.swapAt(i, i + delta)
    queueSheet()
  }
  func reorderFrame(from: Int, to: Int) {
    guard from != to, let a = sheetPhotos.firstIndex(where: { $0.sheetID == from }),
      let b = sheetPhotos.firstIndex(where: { $0.sheetID == to })
    else { return }
    remember()
    let p = sheetPhotos.remove(at: a)
    sheetPhotos.insert(p, at: b)
    queueSheet()
  }
  func toggleFrame(_ id: Int) {
    remember()
    if sheetSelection.contains(id) { sheetSelection.remove(id) } else { sheetSelection.insert(id) }
    queueSheet()
  }
  func selectAllFrames(_ all: Bool) {
    remember()
    sheetSelection = all ? Set(sheetPhotos.map(\.sheetID)) : []
    queueSheet()
  }
  func reverseFrames() {
    remember()
    sheetPhotos.reverse()
    queueSheet()
  }
  func importBackground() {
    guard !sheetJob.isEmpty else { return }
    let p = NSOpenPanel()
    p.canChooseFiles = true
    p.canChooseDirectories = false
    p.allowsMultipleSelection = false
    p.allowedContentTypes = [.image]
    guard p.runModal() == .OK, let u = p.url else { return }
    Task {
      do {
        _ = try await engine.api(
          "/api/sheet/background", .object(["job": .string(sheetJob)]),
          files: ["file": .string(u.path)])
        backgroundPath = u.path
        setConfig("background.sourceIndex", .string("custom"))
        setConfig("background.mode", .string("blur"))
      } catch { failure(error) }
    }
  }
  func exportSheet() {
    guard !selectedOrder.isEmpty else { return }
    let panel = NSSavePanel()
    panel.allowedContentTypes = [sheetFormat == "png" ? .png : .jpeg]
    panel.nameFieldStringValue = "整卷展示." + sheetFormat
    guard panel.runModal() == .OK, let u = panel.url else { return }
    var b = sheetPayload
    b["out"] = .string(u.path)
    b["format"] = .string(sheetFormat)
    busy = true
    status = "正在渲染整卷高分辨率图片…"
    Task {
      do {
        let r = try await engine.api("/api/sheet/export", b)
        let id = r["export"].string
        for _ in 0..<3600 {
          let result = try await engine.api("/api/sheet/export/" + id, method: "GET")
          status = result["message"].string
          if result["state"].string == "failed" {
            throw WorkbenchError(message: result["error"].string)
          }
          if result["state"].string == "ready" {
            lastExport = URL(fileURLWithPath: result["out"].string)
            busy = false
            status = "整卷图片已导出"
            return
          }
          try await Task.sleep(for: .milliseconds(400))
        }
        throw WorkbenchError(message: "导出仍在处理，请查看输出文件夹。")
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  func saveProject() {
    guard !selectedOrder.isEmpty else { return }
    let p = NSSavePanel()
    p.allowedContentTypes = [.zip]
    p.nameFieldStringValue = "整卷项目.zip"
    guard p.runModal() == .OK, let u = p.url else { return }
    let b = sheetPayload
    busy = true
    Task {
      do {
        _ = try await engine.api("/api/sheet/project/export", b, output: u.path)
        busy = false
        lastExport = u
        status = "已保存包含照片与布局的项目"
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  func chooseProject() {
    let p = NSOpenPanel()
    p.canChooseFiles = true
    p.canChooseDirectories = false
    p.allowsMultipleSelection = false
    p.allowedContentTypes = [.zip]
    if p.runModal() == .OK, let u = p.url { importProject(u) }
  }
  func importProject(_ u: URL) {
    busy = true
    workspace = .sheet
    Task {
      do {
        let r = try await engine.api("/api/sheet/project/import", files: ["file": .string(u.path)])
        try await finishPrepare(r["job"].string, restoring: r["project"])
      } catch {
        busy = false
        failure(error)
      }
    }
  }
  var layouts: J {
    UserDefaults.standard.data(forKey: "native.layouts").flatMap { try? J(data: $0) }
      ?? .object([:])
  }
  func applyLayout(_ name: String) {
    guard layouts[name] != .null else { return }
    remember()
    sheetConfig = layouts[name]["config"]
    stockID = layouts[name]["stockId"].string
    selectedLayout = name
    queueSheet()
  }
  func deleteLayout() {
    var l = layouts.object
    l.removeValue(forKey: selectedLayout)
    let j = J.object(l)
    UserDefaults.standard.set(j.data, forKey: "native.layouts")
    layoutNames = l.keys.sorted()
    selectedLayout = ""
  }
  func saveDraft(immediately: Bool = false) {
    guard !sheetPhotos.isEmpty else { return }
    let photos = sheetPhotos, config = sheetConfig, options = frames
    let selection = sheetSelection, stock = stockID, background = backgroundPath
    let previous = draftTask
    previous?.cancel()
    draftTask = Task.detached(priority: .utility) { [weak self] in
      if !immediately { try? await Task.sleep(for: .milliseconds(600)) }
      // A canceled intermediate task must still drain its predecessor. Otherwise a newer
      // write could overtake an older write that had already started encoding or saving.
      await previous?.value
      guard !Task.isCancelled else { return }
      var overrides: [String: J] = [:]
      for p in photos { overrides[p.path] = options[String(p.sheetID)] }
      let source = Int(config.at("background.sourceIndex").double)
      let draft = J.object([
        "config": config, "stockId": .string(stock),
        "allSources": .array(photos.map { .string($0.path) }),
        "sources": .array(
          photos.filter { selection.contains($0.sheetID) }.map { .string($0.path) }),
        "frameOptions": .object(overrides), "backgroundFile": .string(background ?? ""),
        "backgroundSourcePath": .string(photos.first { $0.sheetID == source }?.path ?? ""),
        "positiveOnly": .bool(photos.allSatisfy { $0.source == "import" }),
      ])
      let data = draft.data
      guard !Task.isCancelled else { return }
      UserDefaults.standard.set(data, forKey: "native.sheet.draft")
      await MainActor.run { [weak self] in
        if self?.draftAvailable == false { self?.draftAvailable = true }
      }
    }
  }
  func restoreDraft() {
    guard let data = UserDefaults.standard.data(forKey: "native.sheet.draft"),
      let d = try? J(data: data)
    else { return }
    let paths = d["allSources"].array.map(\.string)
    let missing = paths.filter { !FileManager.default.fileExists(atPath: $0) }
    if !missing.isEmpty {
      error = "部分草稿照片已移动，请恢复原文件或打开保存的项目包：\n" + missing.joined(separator: "\n")
      return
    }
    prepareSheet(paths: paths, positiveOnly: d["positiveOnly"].bool, restoring: d)
  }
  func revealExport() {
    if let lastExport { NSWorkspace.shared.activateFileViewerSelecting([lastExport]) }
  }
}
