import Foundation
import SwiftUI

enum J: Codable, Equatable, Sendable, Identifiable {
  var id: String {
    object["id"]?.string ?? object["url"]?.string ?? object["value"]?.string ?? string
  }
  case null
  case bool(Bool)
  case number(Double)
  case string(String)
  case array([J])
  case object([String: J])
  init(from decoder: Decoder) throws {
    let c = try decoder.singleValueContainer()
    if c.decodeNil() {
      self = .null
    } else if let v = try? c.decode(Bool.self) {
      self = .bool(v)
    } else if let v = try? c.decode(Double.self) {
      self = .number(v)
    } else if let v = try? c.decode(String.self) {
      self = .string(v)
    } else if let v = try? c.decode([J].self) {
      self = .array(v)
    } else {
      self = .object(try c.decode([String: J].self))
    }
  }
  func encode(to encoder: Encoder) throws {
    var c = encoder.singleValueContainer()
    switch self {
    case .null: try c.encodeNil()
    case .bool(let v): try c.encode(v)
    case .number(let v): try c.encode(v)
    case .string(let v): try c.encode(v)
    case .array(let v): try c.encode(v)
    case .object(let v): try c.encode(v)
    }
  }
  var string: String {
    if case .string(let v) = self { return v }
    return ""
  }
  var double: Double {
    if case .number(let v) = self { return v }
    return 0
  }
  var bool: Bool {
    if case .bool(let v) = self { return v }
    return false
  }
  var array: [J] {
    if case .array(let v) = self { return v }
    return []
  }
  var object: [String: J] {
    if case .object(let v) = self { return v }
    return [:]
  }
  subscript(_ key: String) -> J {
    get { object[key] ?? .null }
    set {
      var o = object
      o[key] = newValue
      self = .object(o)
    }
  }
  func at(_ path: String) -> J { path.split(separator: ".").reduce(self) { $0[String($1)] } }
  mutating func put(_ path: String, _ value: J) {
    var pieces = path.split(separator: ".").map(String.init)
    guard let first = pieces.first else { return }
    pieces.removeFirst()
    if pieces.isEmpty {
      self[first] = value
    } else {
      var child = self[first]
      child.put(pieces.joined(separator: "."), value)
      self[first] = child
    }
  }
  static func doubles(_ values: [Double]) -> J { .array(values.map(J.number)) }
  var data: Data { (try? JSONEncoder().encode(self)) ?? Data() }
  init(data: Data) throws { self = try JSONDecoder().decode(J.self, from: data) }
}

struct ControlField: Identifiable {
  let value: J
  var id: String { value["key"].string }
  var title: String { value["title"].string }
  var kind: String { value["kind"].string }
  var pane: String { value["pane"].string }
}
struct Photo: Identifiable, Equatable {
  var id: String { path }
  let path: String
  let name: String
  var edited = false
  var sheetID = -1
  var width: Double = 0
  var height: Double = 0
  var source = ""
}

extension Color {
  init(hex: String) {
    var s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
    if s.count == 3 { s = s.map { "\($0)\($0)" }.joined() }
    let n = UInt64(s, radix: 16) ?? 0
    self.init(
      .sRGB, red: Double((n >> 16) & 255) / 255, green: Double((n >> 8) & 255) / 255,
      blue: Double(n & 255) / 255, opacity: 1)
  }
  var hex: String {
    let c = NSColor(self).usingColorSpace(.sRGB) ?? .black
    return String(
      format: "#%02x%02x%02x", Int(c.redComponent * 255), Int(c.greenComponent * 255),
      Int(c.blueComponent * 255))
  }
}
