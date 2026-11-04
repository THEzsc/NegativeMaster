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
  @MainActor func testArchiveSingleSelectionRangeAndDetailsAreSeparate() {
    let a = ArchiveState()
    let frames: [J] = (1...4).map { .object(["id": .string("frame-\($0)")]) }
    a.detail = .object(["frames": .array(frames)])
    a.selectFrame(frames[0])
    XCTAssertEqual(a.selectedFrames, ["frame-1"])
    XCTAssertFalse(a.showFrameEditor)
    a.selectFrame(frames[2], extending: true)
    XCTAssertEqual(a.selectedFrames, ["frame-1", "frame-2", "frame-3"])
    a.selectFrame(frames[1], toggling: true)
    XCTAssertEqual(a.selectedFrames, ["frame-1", "frame-3"])
    a.openFrame(frames[3])
    XCTAssertTrue(a.showFrameEditor)
    XCTAssertEqual(a.frameDraft, frames[3])
    a.detail = .object(["frames": .array([frames[0]])])
    XCTAssertTrue(a.selectedFrames.isEmpty)
  }
  func testMouseWheelKeepsPreciseAndModifiedScrollingNative() {
    XCTAssertEqual(MouseWheelInput.delta(x: 0, y: -3, precise: false, modifiers: []), -3)
    XCTAssertNil(MouseWheelInput.delta(x: 0, y: 3, precise: true, modifiers: []))
    XCTAssertNil(MouseWheelInput.delta(x: 1, y: 3, precise: false, modifiers: []))
    XCTAssertNil(MouseWheelInput.delta(x: 0, y: 0, precise: false, modifiers: []))
    for modifier: NSEvent.ModifierFlags in [.shift, .command, .control, .option] {
      XCTAssertNil(MouseWheelInput.delta(x: 0, y: 3, precise: false, modifiers: modifier))
    }
    XCTAssertEqual(MouseWheelInput.zoom(1, delta: 1, inverted: false), 1.12, accuracy: 0.0001)
    XCTAssertEqual(MouseWheelInput.zoom(1, delta: -1, inverted: true), 1.12, accuracy: 0.0001)
    XCTAssertEqual(MouseWheelInput.zoom(16, delta: 100, inverted: false), 16)
    XCTAssertEqual(MouseWheelInput.zoom(0.25, delta: -100, inverted: false), 0.25)
  }

  func testEmulsionToggleIsIdempotentAndUsesTheCapturedFilmAxis() {
    let p = J.object(["rotate": .number(90), "flip": .string("none"),
      "level_angle": .number(0.5), "gamma": .number(1.3),
      "crop_rect": .doubles([0.125, 0.25, 0.625, 0.875])])
    let on = DevelopOrientation.applyingEmulsion(true, to: p)
    XCTAssertEqual(on["flip"], .string("v"))
    XCTAssertEqual(on["crop_rect"], .doubles([0.125, 0.125, 0.625, 0.75]))
    XCTAssertEqual(on["level_angle"], .number(-0.5))
    XCTAssertEqual(on["gamma"], p["gamma"])
    XCTAssertEqual(DevelopOrientation.applyingEmulsion(true, to: on), on)
    let off = DevelopOrientation.applyingEmulsion(false, to: on)
    for key in ["rotate", "flip", "crop_rect", "level_angle", "gamma"] { XCTAssertEqual(off[key], p[key]) }
    var old = p; old["flip"] = .string("h")
    let retained = DevelopOrientation.applyingEmulsion(true, to: old)
    XCTAssertEqual(retained["flip"], old["flip"])
    XCTAssertEqual(retained["crop_rect"], old["crop_rect"])
    old["emulsion_mirrored"] = .bool(false)
    XCTAssertFalse(DevelopOrientation.emulsionMirrored(old), "Explicit settings override legacy inference")
  }

  @MainActor func testFilmGammaScopeIncludesHiddenPhotosWithoutCopyingGamma() {
    let s = WorkbenchState(); s.ready = true; s.rawOnly = false
    s.photos = (1...3).map { Photo(path: "/film-\($0).ARW", name: "film-\($0).ARW") }
    s.search = "film-1"; s.checked = [s.photos[0].path]
    s.params = .object(["gamma": .number(1.7)])
    s.filmAppliesToRoll = true
    s.estimateFilmGamma()
    XCTAssertTrue(s.showRollAutomation)
    XCTAssertEqual(s.automationKind, "gamma")
    XCTAssertEqual(s.automationScope, "roll")
    XCTAssertEqual(s.automationPhotos.count, 3)
    XCTAssertEqual(s.params["gamma"], .number(1.7))
    XCTAssertTrue(s.automationRows.isEmpty, "Opening the estimate controls does not write adjustments")
    XCTAssertEqual(WorkbenchState.migratedDevelopPanels(["gamma", "curves"]), ["film", "curves"])
  }

  func testPreviewDemandUsesBackingPixelsAndRetainsFullFrameCropScale() {
    let source = CGSize(width: 8000, height: 6000)
    let full = CGRect(x: 0, y: 0, width: 1, height: 1)
    let half = CGRect(x: 0.25, y: 0.25, width: 0.5, height: 0.5)
    XCTAssertEqual(PreviewResolution.percent(displayed: CGSize(width: 4000, height: 3000),
      crop: full, backingScale: 2, source: source), 100)
    XCTAssertEqual(PreviewResolution.percent(displayed: CGSize(width: 2000, height: 1500),
      crop: full, backingScale: 2, source: source), 50)
    XCTAssertEqual(PreviewResolution.side(displayed: CGSize(width: 2000, height: 1500),
      crop: half, backingScale: 2, source: source), 8000)
    XCTAssertEqual(PreviewResolution.side(displayed: CGSize(width: 8000, height: 6000),
      crop: full, backingScale: 2, source: source), 8000, "Never request invented detail beyond the source")
    XCTAssertEqual(PreviewResolution.side(displayed: CGSize(width: 600, height: 450),
      crop: full, backingScale: 2, source: source), 1500)
  }

  @MainActor func testDetailIsReleasedWhenShrinkingEditingOrChangingPhoto() {
    let s = WorkbenchState()
    func loaded() {
      s.detailSide = 8000; s.detailLoadedSide = 8000
      s.detailImage = NSImage(size: CGSize(width: 8000, height: 6000))
    }
    loaded(); s.requestDetail(side: 1500)
    XCTAssertNil(s.detailImage)
    loaded(); s.queueRender()
    XCTAssertNil(s.detailImage)
    loaded(); s.selected = "/different.ARW"
    XCTAssertNil(s.detailImage); XCTAssertEqual(s.detailSide, 1500)
    loaded(); s.busy = true
    XCTAssertNil(s.detailImage)
    s.busy = false
    loaded(); s.workspace = .sheet
    XCTAssertNil(s.detailImage)
  }

  func testDetailImageIODoesNotApplyThumbnailLimit() async throws {
    let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".jpg")
    defer { try? FileManager.default.removeItem(at: file) }
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 3200, pixelsHigh: 640,
      bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
      colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    try bitmap.representation(using: .jpeg, properties: [:])!.write(to: file)
    let detail = await ImagePipeline.detail(file, size: 3200)
    let half = await ImagePipeline.detail(file, size: 1600)
    XCTAssertEqual(detail?.width, 3200)
    XCTAssertEqual(half?.width, 1600)
  }

  func testTransientBridgeReleasesWorkerStateAndRecoversAfterCancellation() async throws {
    let bridge = EngineBridge(background: true, transient: true)
    let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".jpg")
    defer { try? FileManager.default.removeItem(at: file) }
    try imageData().write(to: file)
    _ = try await bridge.api("/api/load", .object(["path": .string(file.path)]))
    do {
      _ = try await bridge.api("/api/render")
      XCTFail("A transient worker must not retain the preceding image allocation")
    } catch { XCTAssertTrue(error.localizedDescription.contains("先载入图片")) }
    let cancelled = Task { try await bridge.call(.object(["action": .string("bootstrap")])) }
    try await Task.sleep(for: .milliseconds(20)); cancelled.cancel()
    _ = try? await cancelled.value
    let next = try await bridge.call(.object(["action": .string("bootstrap")]))
    XCTAssertFalse(next["defaults"].object.isEmpty)
  }

  func testOrientationKeepsCropAndAllSamplesOnTheSamePixels() {
    let rect = J.doubles([0.125, 0.25, 0.625, 0.75])
    var source = J.object(["rotate": .number(0), "flip": .string("none"),
      "level_angle": .number(0.5), "exposure": .number(0.7),
      "wb_point": .doubles([0.25, 0.125])])
    let keys = ["crop_rect", "wb_rect", "film_base_rect", "shadow_rect", "highlight_rect"]
    for key in keys { source[key] = rect }
    let moved = DevelopOrientation.clockwise.applying(to: source)
    for key in keys { XCTAssertEqual(moved[key], .doubles([0.25, 0.125, 0.75, 0.625])) }
    XCTAssertEqual(moved["wb_point"], .doubles([0.875, 0.25]))
    XCTAssertEqual(moved["level_angle"], source["level_angle"])
    XCTAssertEqual(moved["exposure"], source["exposure"])
    let restored = DevelopOrientation.counterclockwise.applying(to: moved)
    for key in keys { XCTAssertEqual(restored[key], source[key]) }
    XCTAssertEqual(restored["wb_point"], source["wb_point"])
    let object = J.object(["x0": .number(0.125), "y0": .number(0.25),
                          "x1": .number(0.625), "y1": .number(0.75)])
    XCTAssertEqual(DevelopOrientation.horizontal.rectangle(object)["x0"], .number(0.375))
    XCTAssertEqual(DevelopOrientation.horizontal.rectangle(object)["x1"], .number(0.875))
    XCTAssertEqual(DevelopOrientation.clockwise.rectangle(.null), .null)
  }

  func testOrientationCompositionIncludesExistingMirrors() {
    func displayed(_ p: J, x: Double, y: Double) -> (Double, Double) {
      var x = x, y = y
      for _ in 0..<(Int(p["rotate"].double) / 90) { (x, y) = (1-y, x) }
      if p["flip"].string == "h" { x = 1-x }
      if p["flip"].string == "v" { y = 1-y }
      return (x, y)
    }
    for rotation in [0, 90, 180, 270] {
      for flip in ["none", "h", "v"] {
        let source = J.object(["rotate": .number(Double(rotation)), "flip": .string(flip),
                               "level_angle": .number(0.5)])
        let before = displayed(source, x: 0.125, y: 0.75)
        for operation in [DevelopOrientation.clockwise, .counterclockwise, .horizontal, .vertical] {
          let next = operation.applying(to: source)
          let actual = displayed(next, x: 0.125, y: 0.75)
          let expected = operation.point(before.0, before.1)
          XCTAssertEqual(actual.0, expected.0, accuracy: 1e-12)
          XCTAssertEqual(actual.1, expected.1, accuracy: 1e-12)
          XCTAssertEqual(next["level_angle"].double, operation.swapsAxes ? 0.5 : -0.5)
          XCTAssertEqual(next["crop_rect"], .null)
        }
      }
    }
  }

  @MainActor func testRotateAndMirrorAreSingleUndoableCropEdits() {
    let s = WorkbenchState()
    s.params = .object(["rotate": .number(90), "flip": .string("h"),
      "crop_rect": .doubles([0.125, 0.25, 0.625, 0.75]), "level_angle": .number(0.5)])
    s.cropAspect = "3:2"
    let original = s.params
    s.rotate(90)
    XCTAssertEqual(s.params["rotate"], .number(0), "Mirrored photos still rotate clockwise on screen")
    XCTAssertEqual(s.params["crop_rect"], .doubles([0.25, 0.125, 0.75, 0.625]))
    XCTAssertEqual(s.cropAspect, "2:3")
    let rotated = s.params
    s.undo()
    XCTAssertEqual(s.params, original)
    XCTAssertEqual(s.cropAspect, "3:2")
    XCTAssertFalse(s.canUndo)
    s.redo()
    XCTAssertEqual(s.params, rotated)
    XCTAssertEqual(s.cropAspect, "2:3")
    s.mirror("v")
    XCTAssertEqual(s.params["flip"], .string("none"))
    XCTAssertEqual(s.params["rotate"], .number(180))
    XCTAssertEqual(s.params["level_angle"], .number(-0.5))
    XCTAssertEqual(s.params["crop_rect"], .doubles([0.25, 0.375, 0.75, 0.875]))
    s.undo()
    XCTAssertEqual(s.params, rotated)
  }

  @MainActor func testRotationRoundTripAndBatchGuardPreserveCrop() {
    let s = WorkbenchState()
    s.params = .object(["rotate": .number(0), "flip": .string("none"),
      "crop_rect": .doubles([0.125, 0.25, 0.625, 0.75]), "geometry_source": .string("manual")])
    s.cropAspect = "6:7"
    let original = s.params
    s.rotate(-90); s.rotate(90)
    XCTAssertEqual(s.params, original)
    XCTAssertEqual(s.cropAspect, "6:7")
    s.rotate(180)
    XCTAssertEqual(s.params["crop_rect"], .doubles([0.375, 0.25, 0.875, 0.75]))
    XCTAssertEqual(s.cropAspect, "6:7")
    let beforeBatch = s.params
    s.applyingFilm = true
    s.rotate(90); s.mirror("h")
    XCTAssertEqual(s.params, beforeBatch)
  }

  @MainActor func testBasicPanelMigrationPreservesCollapsedState() {
    XCTAssertEqual(WorkbenchState.migratedDevelopPanels(nil), ["histogram", "light"])
    XCTAssertEqual(WorkbenchState.migratedDevelopPanels(["whiteBalance", "color", "curves"]), ["light", "curves"])
    XCTAssertEqual(WorkbenchState.migratedDevelopPanels([]), [])
  }

  func testCropViewportAndSampleCoordinates() {
    let crop = J.doubles([0.2, 0.1, 0.8, 0.9])
    let view = DevelopViewport(crop: crop, editingCrop: false)
    XCTAssertEqual(view.rect.width, 0.6, accuracy: 0.000001)
    let sample = view.fullRect(from: [0.25, 0.25, 0.75, 0.75])
    for (actual, expected) in zip(sample, [0.35, 0.3, 0.65, 0.7]) {
      XCTAssertEqual(actual, expected, accuracy: 0.000001)
    }
    let displayed = view.displayedRect(from: sample)
    XCTAssertEqual(displayed.minX, 0.25, accuracy: 0.000001)
    XCTAssertEqual(displayed.height, 0.5, accuracy: 0.000001)
    XCTAssertEqual(DevelopViewport(crop: crop, editingCrop: true).rect, CGRect(x: 0, y: 0, width: 1, height: 1))
    XCTAssertEqual(DevelopViewport(crop: .doubles([.nan, 0, 1, 1]), editingCrop: false).rect.width, 1)
  }
  @MainActor func testSyncScopeExcludesSourceAndHonoursExplicitRange() {
    let s = WorkbenchState()
    s.photos = (1...4).map { Photo(path: "/tmp/sync-\($0).ARW", name: "sync-\($0).ARW") }
    s.selected = s.photos[0].path; s.rawOnly = false
    s.checked = [s.photos[0].path, s.photos[2].path]
    XCTAssertEqual(s.syncTargets, s.photos.dropFirst().map(\.path))
    s.syncScope = "selected"
    XCTAssertEqual(s.syncTargets, [s.photos[2].path])
    s.search = "sync-1"
    XCTAssertTrue(s.syncTargets.isEmpty)
    s.syncScope = "roll"
    XCTAssertEqual(s.syncTargets.count, 3)
  }
  @MainActor func testFilmScopeDefaultsOffAndIgnoresSearchAndSelection() {
    let s = WorkbenchState()
    s.photos = (1...3).map { Photo(path: "/tmp/film-\($0).ARW", name: "film-\($0).ARW") }
    s.search = "film-1"; s.checked = [s.photos[0].path]
    XCTAssertFalse(s.filmAppliesToRoll)
    let before = s.params
    s.filmAppliesToRoll = true
    XCTAssertEqual(s.params, before)
    XCTAssertEqual(s.filmTargetPaths, s.photos.map(\.path))
    s.applyingFilm = true
    s.selectPhoto(s.photos[1].path)
    XCTAssertNil(s.selected)
  }
  @MainActor func testFilmChangeContinuesAfterFailureAndOnlyUpdatesMatchingPhoto() async {
    let s = WorkbenchState()
    s.photos = ["/a", "/broken", "/b"].map { Photo(path: $0, name: $0) }
    s.selected = "/a"; s.parameterPath = "/a"
    s.params = .object(["gamma": .number(1.8)])
    await s.applyFilmChanges(paths: s.filmTargetPaths, change: .object(["mode": .string("bw")])) { message in
      let path = message["body"]["path"].string
      if path == "/broken" { throw WorkbenchError(message: "unreadable") }
      if message["action"].string == "batch_snapshot" { return .object(["token": .string(path)]) }
      XCTAssertEqual(message["action"].string, "film_apply")
      XCTAssertEqual(message["body"]["token"].string, path)
      XCTAssertEqual(Set(message["body"].object.keys), Set(["mode", "path", "token"]))
      return .object(["params": .object(["mode": .string("bw"), "gamma": .number(path == "/a" ? 1.8 : 1.2)])])
    }
    XCTAssertEqual(s.params["gamma"], .number(1.8))
    XCTAssertEqual(s.params["mode"], .string("bw"))
    XCTAssertEqual(s.photos.map(\.edited), [true, false, true])
    XCTAssertTrue(s.error?.contains("broken") == true)
  }
  @MainActor func testRollAutomationDefaultsToVisibleRollEvenWithOneSelected() {
    let s = WorkbenchState(); s.ready = true; s.rawOnly = false
    s.photos = (1...4).map { Photo(path: "/tmp/roll-\($0).ARW", name: "roll-\($0).ARW") }
    s.checked = [s.photos[0].path]
    s.presentRollAutomation("gamma")
    XCTAssertEqual(s.automationPhotos.count, 4)
    s.automationScope = "selected"
    XCTAssertEqual(s.automationPhotos.count, 1)
  }
  func testRollSuggestionsSkipUncertainCropAndUncheckLowConfidenceGamma() {
    let snap = J.object(["params": .object(["gamma": .number(1.8)]), "token": .string("token")])
    let bad = RollSuggestion.analyzed(path: "/a", snapshot: snap, result: .object(["status": .string("uncertain")]), kind: "crop")
    XCTAssertFalse(bad.eligible); XCTAssertFalse(bad.included)
    let report = J.object(["report": .object(["parameter_key": .string("gamma"), "recommendation": .number(1.2), "confidence": .string("low")])])
    let low = RollSuggestion.analyzed(path: "/b", snapshot: snap, result: report, kind: "gamma")
    XCTAssertTrue(low.eligible); XCTAssertFalse(low.included)
    XCTAssertEqual(low.patch["gamma"], .number(1.2))
  }
  @MainActor func testRollAnalysisContinuesAfterFailureAndKeepsIndividualValues() async {
    let s = WorkbenchState(); s.automationKind = "gamma"
    await s.runRollAnalysis(paths: ["/a", "/broken", "/b"]) { message in
      let path = message["body"]["path"].string
      if path == "/broken" { throw WorkbenchError(message: "bad frame") }
      if message["action"].string == "batch_snapshot" {
        return .object(["params": .object(["exposure": .number(path == "/a" ? 0 : 1)]), "token": .string(path)])
      }
      let ev = message["body"]["params"]["exposure"].double
      return .object(["report": .object(["parameter_key": .string("gamma"), "recommendation": .number(ev == 0 ? 1.8 : 1.1), "confidence": .string("medium")])])
    }
    XCTAssertEqual(s.automationRows.count, 3); XCTAssertEqual(s.automationChosen, 2)
    XCTAssertEqual(s.automationRows[0].patch["gamma"], .number(1.8))
    XCTAssertEqual(s.automationRows[2].patch["gamma"], .number(1.1))
    var applied = 0
    await s.applyRollAutomation(undo: false) { message in
      XCTAssertEqual(message["action"].string, "batch_apply")
      XCTAssertEqual(message["body"]["token"].string, message["body"]["path"].string)
      applied += 1
      if applied == 1 { s.automationStop = true }
      return .object(["undo_id": .string("receipt"), "params": .object([:])])
    }
    XCTAssertEqual(applied, 1); XCTAssertTrue(s.automationStopped); XCTAssertEqual(s.automationUndoCount, 1)
  }
  @MainActor func testLightroomSelectionRangeToggleAndActivePhoto() {
    let s = WorkbenchState()
    s.rawOnly = false
    s.photos = (1...6).map { Photo(path: "/tmp/frame-\($0).ARW", name: "frame-\($0).ARW") }
    s.selectPhoto(s.photos[1].path)
    XCTAssertEqual(s.checked, [s.photos[1].path])
    s.selectPhoto(s.photos[4].path, extending: true)
    XCTAssertEqual(s.checked, Set(s.photos[1...4].map(\.path)))
    XCTAssertEqual(s.selected, s.photos[4].path)
    s.selectPhoto(s.photos[2].path, toggling: true)
    XCTAssertFalse(s.checked.contains(s.photos[2].path))
    XCTAssertEqual(s.selected, s.photos[4].path)
    s.selectPhoto(s.photos[0].path, toggling: true)
    XCTAssertEqual(s.selected, s.photos[0].path)
    s.selectPhoto(s.photos[5].path)
    XCTAssertEqual(s.checked, [s.photos[5].path])
    s.movePhoto(-1, extending: true)
    XCTAssertEqual(s.checked, Set(s.photos[4...5].map(\.path)))
    s.search = "frame-1"
    s.selectPhoto(s.photos[0].path, extending: true)
    XCTAssertEqual(s.checked, [s.photos[0].path], "Hidden photos never enter a shift range")
  }
  func testPersistentThumbnailAndSourceInvalidation() async throws {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: folder) }
    let path = folder.appendingPathComponent("thumb.jpg")
    try imageData().write(to: path)
    let first = try await ImagePipeline().file(path.path, size: 160)
    XCTAssertEqual(first?.width, 160)
    // A new pipeline simulates application restart; the persistent JPEG remains usable.
    let second = try await ImagePipeline().file(path.path, size: 160)
    XCTAssertEqual(second?.width, 160)
    try Data("not an image".utf8).write(to: path)
    do { _ = try await ImagePipeline().file(path.path, size: 160); XCTFail("Must invalidate when the source changes") }
    catch {}
  }
  func testRealRAWThumbnailBenchmarkWhenRequested() async throws {
    guard let path = ProcessInfo.processInfo.environment["NM_BENCH_RAW"] else { return }
    let start = Date()
    let first = try await ImagePipeline().file(path, size: 160)
    let cold = Date().timeIntervalSince(start)
    let warm = Date()
    let second = try await ImagePipeline().file(path, size: 160)
    XCTAssertNotNil(first); XCTAssertNotNil(second)
    print("RAW_THUMBNAIL first_ms=\(cold * 1000) disk_ms=\(Date().timeIntervalSince(warm) * 1000)")
  }
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
  @MainActor func testRawFilterAndBatchScopeNeverIncludeHiddenCheckedJPEGs() {
    let state = WorkbenchState()
    let old = state.rawOnly
    defer { state.rawOnly = old }
    state.rawExtensions = ["arw", "dng"]
    state.photos = [Photo(path: "/roll/01.ARW", name: "01.ARW"), Photo(path: "/roll/01.JPG", name: "01.JPG"), Photo(path: "/roll/02.dNg", name: "02.dNg")]
    state.checked = Set(state.photos.map(\.path))
    state.rawOnly = true
    XCTAssertEqual(state.filteredPhotos.map(\.name), ["01.ARW", "02.dNg"])
    state.batchScope = "selected"
    XCTAssertEqual(state.batchExportPhotos.count, 2)
    state.search = "02"
    XCTAssertEqual(state.batchExportPhotos.map(\.name), ["02.dNg"])
    state.search = "missing"
    XCTAssertTrue(state.batchExportPhotos.isEmpty)
    state.rawOnly = false
    state.search = ""
    XCTAssertEqual(state.batchExportPhotos.count, 3)
  }

  @MainActor func testBatchExportUsesPerPhotoSettingsContinuesFailuresAndPreservesExistingFiles() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let existing = directory.appendingPathComponent("01_pos.jpg")
    try Data("existing".utf8).write(to: existing)
    let state = WorkbenchState()
    let plan = BatchExportPlan(paths: ["/roll/01.ARW", "/roll/02.ARW", "/roll/03.ARW"], destination: directory,
      settings: BatchExportSettings(format: "jpg", bits: 16, quality: 96, resize: 0),
      currentPath: "/roll/01.ARW", currentParams: .object(["gamma": .number(0.85), "rotate": .number(90)]))
    var readPaths: [String] = []
    var exported: [J] = []
    var logged: [J] = []
    await state.performBatchExport(plan) { message in
      let body = message["body"], path = body["path"].string
      if message["action"].string == "export_log" {
        logged = body["items"].array
        return .object(["ok": .bool(true)])
      }
      if message["action"].string == "adjustments" {
        readPaths.append(path)
        return .object(["params": .object(["gamma": .number(path.contains("02") ? 1.4 : 1.9)])])
      }
      exported.append(body)
      if path.contains("02") { throw WorkbenchError(message: "测试损坏照片") }
      try Data("image".utf8).write(to: URL(fileURLWithPath: body["out"].string))
      return .object(["ok": .bool(true)])
    }
    XCTAssertEqual(readPaths, ["/roll/02.ARW", "/roll/03.ARW"])
    XCTAssertEqual(exported.map { $0["params"]["gamma"].double }, [0.85, 1.4, 1.9])
    XCTAssertEqual(exported[0]["params"]["rotate"].double, 90)
    XCTAssertTrue(exported.allSatisfy { $0["quality"].double == 96 && $0["bits"].double == 8 && !$0["overwrite"].bool })
    XCTAssertTrue(exported[0]["out"].string.hasSuffix("01_pos-1.jpg"))
    XCTAssertEqual(try Data(contentsOf: existing), Data("existing".utf8))
    XCTAssertEqual(state.batchCompleted, 2)
    XCTAssertEqual(logged.map { $0["source"].string }, ["/roll/01.ARW", "/roll/03.ARW"])
    XCTAssertEqual(logged.map { $0["path"].string }, state.batchOutputs.map(\.path))
    XCTAssertEqual(state.batchFailures.count, 1)
    XCTAssertEqual(state.batchOutputs.count, 2)
    XCTAssertTrue(state.batchFinished)
    XCTAssertFalse(state.busy)
    XCTAssertFalse(state.batchRunning)
    XCTAssertEqual(state.progress, 1)
  }

  @MainActor func testBatchCancellationKeepsCompletedImageAndStopsNextFrame() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let state = WorkbenchState()
    let plan = BatchExportPlan(paths: ["/roll/01.ARW", "/roll/02.ARW"], destination: directory,
      settings: BatchExportSettings(format: "png", bits: 8, quality: 92, resize: 0),
      currentPath: nil, currentParams: .null)
    var requests = 0
    await state.performBatchExport(plan) { message in
      requests += 1
      if message["action"].string == "adjustments" { return .object(["params": .object([:])]) }
      try Data("completed".utf8).write(to: URL(fileURLWithPath: message["body"]["out"].string))
      state.cancelOperation()
      return .object(["ok": .bool(true)])
    }
    XCTAssertEqual(requests, 2)
    XCTAssertEqual(state.batchCompleted, 1)
    XCTAssertTrue(state.batchCancelled)
    XCTAssertTrue(FileManager.default.fileExists(atPath: directory.appendingPathComponent("01_pos.png").path))
    XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent("02_pos.png").path))
  }

  @MainActor func testInvalidBatchDestinationRemainsRetryableWithoutEngineWork() async throws {
    let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try Data("file".utf8).write(to: file)
    defer { try? FileManager.default.removeItem(at: file) }
    let state = WorkbenchState()
    let plan = BatchExportPlan(paths: ["/roll/01.ARW"], destination: file,
      settings: BatchExportSettings(format: "jpg", bits: 8, quality: 92, resize: 0), currentPath: nil, currentParams: .null)
    await state.performBatchExport(plan) { _ in XCTFail("Invalid destination must fail before engine work"); return .null }
    XCTAssertNotNil(state.batchError)
    XCTAssertFalse(state.batchFinished)
    XCTAssertFalse(state.busy)
    XCTAssertFalse(state.batchRunning)
    XCTAssertEqual(try Data(contentsOf: file), Data("file".utf8))
  }

  @MainActor func testInspectorPanelsExpandIndependentlyAndRevealCropRepeatedly() {
    let key = "native.expandedDevelopPanels"
    let saved = UserDefaults.standard.object(forKey: key)
    defer {
      if let saved { UserDefaults.standard.set(saved, forKey: key) }
      else { UserDefaults.standard.removeObject(forKey: key) }
    }
    let state = WorkbenchState()
    state.expandedDevelopPanels = ["light"]
    state.params = .object(["gamma": .number(1.2), "level_angle": .number(0.3)])
    let before = state.params
    state.inspector = false
    state.revealDevelopPanel("crop")
    XCTAssertTrue(state.inspector)
    XCTAssertEqual(state.expandedDevelopPanels, ["light", "crop"])
    let firstJump = state.developPanelJump
    state.revealDevelopPanel("crop")
    XCTAssertGreaterThan(state.developPanelJump, firstJump)
    XCTAssertEqual(state.requestedDevelopPanel, "crop")
    state.setDevelopPanel("crop", expanded: false)
    XCTAssertEqual(state.expandedDevelopPanels, ["light"])
    XCTAssertEqual(WorkbenchState().expandedDevelopPanels, ["light"])
    state.setDevelopPanel("light", expanded: false)
    XCTAssertTrue(WorkbenchState().expandedDevelopPanels.isEmpty)
    XCTAssertEqual(state.params, before)
  }

}
