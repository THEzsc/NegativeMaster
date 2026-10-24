import AppKit

/// Opt-in local diagnostic: state change to the end of that UI run-loop turn.
/// This measures layout/commit work, not display scan-out or image rendering.
@MainActor enum SwitchPerformance {
  private static let writer = DispatchQueue(label: "NegativeMaster.switch-metrics", qos: .utility)
  static func begin(_ mode: String) {
    guard UserDefaults.standard.bool(forKey: "native.profileSwitches") else { return }
    let start = ProcessInfo.processInfo.systemUptime
    let pid = ProcessInfo.processInfo.processIdentifier
    let observer = CFRunLoopObserverCreateWithHandler(nil, CFRunLoopActivity.beforeWaiting.rawValue, false, CFIndex.max) { _, _ in
      let ms = (ProcessInfo.processInfo.systemUptime - start) * 1000
      let line = "{\"pid\":\(pid),\"mode\":\"\(mode)\",\"state_to_idle_ms\":\(ms)}\n"
      writer.async {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("NegativeMaster-switches-\(pid).jsonl")
        if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
        guard let h = try? FileHandle(forWritingTo: url) else { return }
        defer { try? h.close() }
        _ = try? h.seekToEnd()
        try? h.write(contentsOf: Data(line.utf8))
      }
    }
    CFRunLoopAddObserver(CFRunLoopGetMain(), observer, .commonModes)
  }
}
