import Foundation

/// Display-space operations; the renderer applies stored rotation before stored reflection.
enum DevelopOrientation: Equatable {
  case clockwise, counterclockwise, horizontal, vertical

  static func emulsionMirrored(_ params: J) -> Bool {
    if case .bool(let enabled) = params["emulsion_mirrored"] { return enabled }
    return ["h", "v"].contains(params["flip"].string)
  }

  static func applyingEmulsion(_ enabled: Bool, to params: J) -> J {
    var result = params
    if emulsionMirrored(params) != enabled {
      let operation: DevelopOrientation = Int(params["rotate"].double) % 180 == 0 ? .horizontal : .vertical
      result = operation.applying(to: params)
    }
    result["emulsion_mirrored"] = .bool(enabled)
    return result
  }

  var swapsAxes: Bool { self == .clockwise || self == .counterclockwise }

  func point(_ x: Double, _ y: Double) -> (Double, Double) {
    switch self {
    case .clockwise: return (1 - y, x)
    case .counterclockwise: return (y, 1 - x)
    case .horizontal: return (1 - x, y)
    case .vertical: return (x, 1 - y)
    }
  }

  func rectangle(_ value: J) -> J {
    let keys = ["x0", "y0", "x1", "y1"]
    let isObject: Bool
    if case .object = value { isObject = true } else { isObject = false }
    let coordinates = isObject ? keys.map { value[$0] } : value.array
    guard coordinates.count == 4, coordinates.allSatisfy({
      if case .number(let n) = $0 { return n.isFinite && (0...1).contains(n) }
      return false
    }) else { return value }
    let a = point(coordinates[0].double, coordinates[1].double)
    let b = point(coordinates[2].double, coordinates[3].double)
    let result = [min(a.0, b.0), min(a.1, b.1), max(a.0, b.0), max(a.1, b.1)]
    if isObject {
      var object = value
      for (key, number) in zip(keys, result) { object[key] = .number(number) }
      return object
    }
    return .doubles(result)
  }

  func applying(to original: J) -> J {
    var params = original
    let flip = params["flip"].string
    let mirrored = flip == "h" || flip == "v"
    var rotation = Int(params["rotate"].double)
    if swapsAxes {
      let delta = self == .clockwise ? 90 : -90
      rotation += mirrored ? -delta : delta
    } else {
      let axis = self == .horizontal ? "h" : "v"
      if flip == axis { params["flip"] = .string("none") }
      else if !mirrored { params["flip"] = .string(axis) }
      else {
        // Two different reflections compose to a half turn.
        params["flip"] = .string("none")
        rotation += 180
      }
      if case .number(let angle) = params["level_angle"] {
        params["level_angle"] = .number(-angle)
      }
    }
    params["rotate"] = .number(Double((rotation % 360 + 360) % 360))
    for key in ["crop_rect", "wb_rect", "film_base_rect", "shadow_rect", "highlight_rect"] {
      if params[key] != .null { params[key] = rectangle(params[key]) }
    }
    let sample = params["wb_point"].array
    if sample.count == 2, sample.allSatisfy({
      if case .number(let n) = $0 { return n.isFinite && (0...1).contains(n) }
      return false
    }) {
      let moved = point(sample[0].double, sample[1].double)
      params["wb_point"] = .doubles([moved.0, moved.1])
    }
    params["geometry_source"] = .string("manual")
    return params
  }

  func aspect(_ current: String) -> String {
    guard swapsAxes else { return current }
    let sides = current.split(separator: ":")
    return sides.count == 2 ? "\(sides[1]):\(sides[0])" : current
  }
}
