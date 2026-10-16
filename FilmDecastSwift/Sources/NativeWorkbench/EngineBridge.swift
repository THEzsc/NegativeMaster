import Foundation

struct WorkbenchError: LocalizedError {
  let message: String
  var errorDescription: String? { message }
}

/// A serial, persistent local worker. Images never leave the machine; no HTTP listener.
actor EngineBridge {
  private var process: Process?
  private var input: FileHandle?
  private var output: FileHandle?
  private var buffer = Data()
  private func start() throws {
    if process?.isRunning == true { return }
    let resources = Bundle.main.resourceURL
    let embedded = resources?.appendingPathComponent("Engine")
    let configuration = resources?.appendingPathComponent("Runtime.json")
    let runtime = configuration.flatMap { try? Data(contentsOf: $0) }.flatMap { try? J(data: $0) }
    let root =
      embedded.flatMap {
        FileManager.default.fileExists(atPath: $0.appendingPathComponent("gui.py").path) ? $0 : nil
      }
      ?? URL(
        fileURLWithPath: runtime?["source"].string
          ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
          .deletingLastPathComponent().deletingLastPathComponent().path)
    let bundledRuntime = resources?.appendingPathComponent("Runtime")
    let bundledPython = bundledRuntime?.appendingPathComponent("bin/python3").path ?? ""
    let python =
      FileManager.default.isExecutableFile(atPath: bundledPython)
      ? bundledPython
      : (runtime?["python"].string ?? root.appendingPathComponent(".venv/bin/python").path)
    let worker = root.appendingPathComponent("FilmDecastSwift/Support/native_worker.py")
    guard FileManager.default.isExecutableFile(atPath: python),
      FileManager.default.fileExists(atPath: worker.path)
    else {
      throw WorkbenchError(message: "找不到本地图像处理环境。请在原项目运行 FilmDecastSwift/build-app.sh 重新打包。")
    }
    let p = Process()
    let to = Pipe()
    let from = Pipe()
    p.executableURL = URL(fileURLWithPath: python)
    p.arguments = ["-u", worker.path, root.path]
    p.currentDirectoryURL = root
    var env = ProcessInfo.processInfo.environment
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.removeValue(forKey: "PYTHONPATH")
    if python == bundledPython { env["PYTHONHOME"] = bundledRuntime?.path }
    // Keep saved adjustments and presets beside the original project across app updates.
    let original = runtime?["source"].string ?? root.path
    if FileManager.default.fileExists(atPath: original + "/presets") {
      env["NM_DATA_ROOT"] = original
    } else {
      let support = FileManager.default.urls(
        for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent(
          "NegativeMaster")
      try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
      let presets = support.appendingPathComponent("presets")
      if !FileManager.default.fileExists(atPath: presets.path) {
        try FileManager.default.copyItem(at: root.appendingPathComponent("presets"), to: presets)
      }
      env["NM_DATA_ROOT"] = support.path
    }
    p.environment = env
    p.standardInput = to
    p.standardOutput = from
    let log = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("NegativeMaster")
    try FileManager.default.createDirectory(at: log, withIntermediateDirectories: true)
    let logFile = log.appendingPathComponent("engine.log")
    if !FileManager.default.fileExists(atPath: logFile.path) {
      FileManager.default.createFile(atPath: logFile.path, contents: nil)
    }
    p.standardError = try FileHandle(forWritingTo: logFile)
    try p.run()
    process = p
    input = to.fileHandleForWriting
    output = from.fileHandleForReading
    buffer = Data()
  }
  func call(_ message: J) throws -> J {
    try Task.checkCancellation()
    try start()
    guard let input, let output else { throw WorkbenchError(message: "图像引擎未启动") }
    var data = message.data
    data.append(10)
    try input.write(contentsOf: data)
    while !buffer.contains(10) {
      let part = output.availableData
      if part.isEmpty {
        process = nil
        throw WorkbenchError(
          message: "图像引擎已退出。请重试；详细原因记录在 ~/Library/Caches/NegativeMaster/engine.log。")
      }
      buffer.append(part)
    }
    let end = buffer.firstIndex(of: 10)!
    let line = buffer[..<end]
    buffer.removeSubrange(...end)
    let reply = try J(data: Data(line))
    guard reply["ok"].bool else { throw WorkbenchError(message: reply["error"].string) }
    return reply["result"]
  }
  func api(
    _ path: String, _ body: J = .object([:]), method: String = "POST", files: [String: J] = [:],
    output: String? = nil
  ) throws -> J {
    var m: [String: J] = [
      "action": .string("api"), "path": .string(path), "body": body, "method": .string(method),
    ]
    if !files.isEmpty { m["files"] = .object(files) }
    if let output { m["output"] = .string(output) }
    return try call(.object(m))
  }
}
