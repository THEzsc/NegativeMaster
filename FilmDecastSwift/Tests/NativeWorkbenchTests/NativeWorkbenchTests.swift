import XCTest
import AppKit
import Observation
@testable import FilmDecast

actor Loads {
  var count = 0
  func record() { count += 1 }
}
private final class ObservationChanges: @unchecked Sendable {
  private let lock = NSLock()
  private var recorded = 0
  func record() {
    lock.lock(); defer { lock.unlock() }
    recorded += 1
  }
  var count: Int {
    lock.lock(); defer { lock.unlock() }
    return recorded
  }
}
final class NativeWorkbenchTests: XCTestCase {
  func imageData() -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:900,pixelsHigh:600,bitsPerSample:8,samplesPerPixel:3,hasAlpha:false,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    return bitmap.representation(using:.jpeg,properties:[:])!
  }
  func testCacheCoalescesAndSurvivesWorkspaceRemounts() async throws {
    let pipeline = ImagePipeline(), counter = Loads(), data = imageData()
    try await withThrowingTaskGroup(of:Void.self) { group in
      for _ in 0..<12 { group.addTask {
        let image = try await pipeline.image(key:"same",size:160) { await counter.record(); try await Task.sleep(for:.milliseconds(40)); return data }
        XCTAssertEqual(image?.width,160)
      } }
      try await group.waitForAll()
    }
    for _ in 0..<5 { _ = try await pipeline.image(key:"same",size:160) { await counter.record(); return data } }
    let count = await counter.count
    XCTAssertEqual(count,1, "Repeated workspace mounts should reuse decoded images")
  }
  func testThumbnailWarmPathBenchmark() async throws {
    let data = imageData(), pipeline = ImagePipeline(), count = Loads()
    let oldStart = Date()
    for _ in 0..<5 { for _ in 0..<24 { _ = ImagePipeline.decode(data,size:160) } }
    let oldTime = Date().timeIntervalSince(oldStart)
    for i in 0..<24 { _ = try await pipeline.image(key:"frame\(i)",size:160) { await count.record(); return data } }
    let warmStart = Date()
    for _ in 0..<5 { for i in 0..<24 { _ = try await pipeline.image(key:"frame\(i)",size:160) { await count.record(); return data } } }
    let warmTime = Date().timeIntervalSince(warmStart)
    let loads = await count.count
    XCTAssertEqual(loads,24)
    print("THUMBNAIL_BENCH frames=24 cache_passes=5 baseline_decode_ms=\(oldTime*1000) warm_cache_ms=\(warmTime*1000) warm_loads=0")
  }
  func testToneStylesOnlyChangeSevenToneKeys() {
    let original = J.object(["gamma":.number(0.85),"exposure":.number(0.4),"temp":.number(12),"crop_rect":.doubles([0.1,0.2,0.9,0.8]),"rotate":.number(90),"curve":.array([.doubles([0,0]),.doubles([1,0.9])])])
    for look in ToneLook.all {
      let result = look.applying(to:original)
      for (key,value) in original.object { XCTAssertEqual(result[key],value) }
      XCTAssertEqual(look.values.count,7)
    }
    XCTAssertEqual(ToneLook.all.count,5)
  }
  func testGammaRecommendationRejectsWrongEngineAndBounds() {
    XCTAssertTrue(GammaRecommendation.canApply(.object(["parameter_key":.string("gamma"),"recommendation":.number(0.85),"confidence":.string("medium")])))
    for (key,value,confidence) in [("gamma",0.2,"high"),("nd_gamma",9.0,"high"),("other",1.0,"high"),("gamma",1.0,"none")] {
      XCTAssertFalse(GammaRecommendation.canApply(.object(["parameter_key":.string(key),"recommendation":.number(value),"confidence":.string(confidence)])))
    }
    XCTAssertFalse(GammaRecommendation.canApply(.null))
  }
  @MainActor private func gammaAnalysisState(roll: Bool) -> WorkbenchState {
    let state = WorkbenchState()
    state.photos = (1...3).map { Photo(path: "/tmp/native-gamma-frame-\($0).jpg", name: "frame-\($0).jpg") }
    state.selected = state.photos[0].path
    state.parameterPath = state.selected
    state.params = .object(["gamma": .number(1)])
    state.analysisParams = state.params
    state.analysisPath = state.selected
    state.analysisPaths = roll ? state.workflowPaths : [state.photos[0].path]
    state.analysisIsRoll = roll
    state.gammaAnalysis = .object(["report": .object([
      "parameter_key": .string("gamma"), "recommendation": .number(1.2), "confidence": .string("high")
    ])])
    return state
  }
  @MainActor private func assertGammaLockRejectedBeforeWork(_ state: WorkbenchState, file: StaticString = #filePath, line: UInt = #line) {
    let pendingSave = Task<Void, Never> {}
    state.saveTask = pendingSave
    defer { pendingSave.cancel(); state.saveTask = nil }
    let params = state.params, targets = state.analysisPaths, status = state.status
    state.lockRollGamma()
    XCTAssertFalse(state.busy, "Rejected locking must return before scheduling engine work", file: file, line: line)
    XCTAssertFalse(pendingSave.isCancelled, "Rejected locking must not cancel pending parameter saves", file: file, line: line)
    XCTAssertEqual(state.params, params, file: file, line: line)
    XCTAssertEqual(state.analysisPaths, targets, "The captured analysis targets must stay unchanged", file: file, line: line)
    XCTAssertEqual(state.status, status, file: file, line: line)
  }
  @MainActor func testRollGammaRequiresTheAnalyzedSelectionAndSearchScope() {
    let state = gammaAnalysisState(roll: true)
    let captured = state.analysisPaths
    XCTAssertTrue(state.gammaFresh)
    XCTAssertTrue(state.canLockRoll)

    state.checked = [state.photos[0].path, state.photos[1].path]
    XCTAssertFalse(state.gammaFresh)
    XCTAssertFalse(state.gammaApplicable)
    XCTAssertFalse(state.canLockRoll)
    assertGammaLockRejectedBeforeWork(state)

    state.checked = []
    XCTAssertTrue(state.canLockRoll)
    state.search = "frame-1"
    XCTAssertEqual(state.workflowPaths, [state.photos[0].path])
    XCTAssertFalse(state.gammaFresh)
    XCTAssertFalse(state.canLockRoll)
    assertGammaLockRejectedBeforeWork(state)

    state.search = ""
    XCTAssertEqual(state.analysisPaths, captured)
    XCTAssertTrue(state.canLockRoll, "Returning to the analyzed target set restores applicability")
  }
  @MainActor func testSingleFrameGammaAnalysisNeverAllowsRollLocking() {
    let state = gammaAnalysisState(roll: false)
    XCTAssertTrue(state.gammaFresh)
    XCTAssertTrue(state.gammaApplicable)
    XCTAssertFalse(state.canLockRoll)
    assertGammaLockRejectedBeforeWork(state)
    state.checked = [state.photos[1].path]
    state.search = "frame-3"
    XCTAssertTrue(state.gammaApplicable, "Single-frame applicability does not depend on the roll selection")
    XCTAssertFalse(state.canLockRoll)
    assertGammaLockRejectedBeforeWork(state)
  }
  func testBridgeCancellationDoesNotDesynchronizeReplies() async throws {
    let bridge = EngineBridge()
    let first = Task { try await bridge.call(.object(["action":.string("bootstrap")])) }
    try await Task.sleep(for:.milliseconds(30)); first.cancel()
    _ = try? await first.value
    let next = try await bridge.api("/api/sheet/catalog",method:"GET")
    XCTAssertEqual(next["stocks"].array.count,100)
    let last = try await bridge.call(.object(["action":.string("bootstrap")]))
    XCTAssertEqual(last["fields"].array.count,57)
  }
  @MainActor func testDraftDebounceAndQuitFlushKeepLatestSnapshot() async throws {
    let defaults = UserDefaults.standard, key = "native.sheet.draft"
    let original = defaults.object(forKey: key)
    defer {
      if let original { defaults.set(original, forKey: key) }
      else { defaults.removeObject(forKey: key) }
    }
    let sentinel = J.object(["saved": .string("previous session")]).data
    defaults.set(sentinel, forKey: key)
    let state = WorkbenchState()
    state.sheetPhotos = [Photo(path: "/tmp/native-draft-test.jpg", name: "frame.jpg", sheetID: 7, source: "import")]
    state.sheetSelection = [7]
    state.sheetConfig = .object(["header": .object(["title": .string("first edit")])])
    state.saveDraft()
    state.sheetConfig.put("header.title", .string("latest edit"))
    state.saveDraft()
    XCTAssertEqual(defaults.data(forKey: key), sentinel, "Interactive edits should debounce persistence")

    await state.flushBeforeQuit()
    let saved = try XCTUnwrap(defaults.data(forKey: key))
    let draft = try J(data: saved)
    XCTAssertEqual(draft["config"].at("header.title").string, "latest edit")
    XCTAssertEqual(draft["sources"].array.map(\.string), ["/tmp/native-draft-test.jpg"])
    XCTAssertTrue(state.draftAvailable)
    try await Task.sleep(for: .milliseconds(650))
    XCTAssertEqual(defaults.data(forKey: key), saved, "Canceled debounce work must not overwrite the quit snapshot")
  }
  @MainActor func testWorkspaceSwitchesPreserveEditsWithoutInvalidatingUnrelatedReaders() {
    let state = WorkbenchState()
    let photos = [Photo(path: "/tmp/native-observation-negative.jpg", name: "negative.jpg")]
    let params = J.object(["gamma": .number(1.2), "crop_rect": .doubles([0.1, 0.2, 0.9, 0.8])])
    let config = J.object(["width": .number(4800), "header": .object(["title": .string("Saved roll")])])
    let sheetPhotos = [Photo(path: "/tmp/native-observation-positive.jpg", name: "positive.jpg", sheetID: 7, source: "import")]
    let frames = J.object(["7": .object(["rotation": .number(90)])])
    state.photos = photos
    state.params = params
    state.sheetConfig = config
    state.selected = photos[0].path
    state.checked = [photos[0].path]
    state.sheetPhotos = sheetPhotos
    state.sheetSelection = [7]
    state.frames = frames
    state.selectionTool = "crop"
    state.zoom = 2

    let photoChanges = ObservationChanges(), paramChanges = ObservationChanges()
    let configChanges = ObservationChanges(), workspaceChanges = ObservationChanges()
    withObservationTracking { _ = state.photos } onChange: { photoChanges.record() }
    withObservationTracking { _ = state.params } onChange: { paramChanges.record() }
    withObservationTracking { _ = state.sheetConfig } onChange: { configChanges.record() }
    withObservationTracking { _ = state.workspace } onChange: { workspaceChanges.record() }

    for workspace in [WorkbenchState.Workspace.sheet, .develop, .archive, .sheet, .develop] {
      state.workspace = workspace
    }
    XCTAssertEqual(workspaceChanges.count, 1, "The one-shot workspace observer must receive the switch")
    XCTAssertEqual(photoChanges.count, 0, "Sidebar photo readers should not refresh for navigation")
    XCTAssertEqual(paramChanges.count, 0, "Develop controls should not refresh for navigation")
    XCTAssertEqual(configChanges.count, 0, "Sheet controls should not refresh for navigation")
    XCTAssertEqual(state.photos, photos)
    XCTAssertEqual(state.params, params)
    XCTAssertEqual(state.sheetConfig, config)
    XCTAssertEqual(state.selected, photos[0].path)
    XCTAssertEqual(state.checked, [photos[0].path])
    XCTAssertEqual(state.sheetPhotos, sheetPhotos)
    XCTAssertEqual(state.sheetSelection, [7])
    XCTAssertEqual(state.frames, frames)
    XCTAssertEqual(state.selectionTool, "")
    XCTAssertEqual(state.zoom, 1)

    // Positive controls ensure unrelated observers remained registered and nested edits notify.
    state.photos.append(Photo(path: "/tmp/native-observation-next.jpg", name: "next.jpg"))
    XCTAssertEqual(photoChanges.count, 1)
    XCTAssertEqual(paramChanges.count, 0)
    XCTAssertEqual(configChanges.count, 0)
    state.params.put("gamma", .number(1.4))
    XCTAssertEqual(paramChanges.count, 1)
    XCTAssertEqual(configChanges.count, 0)
    state.sheetConfig.put("header.title", .string("Edited roll"))
    XCTAssertEqual(configChanges.count, 1)
  }
}
