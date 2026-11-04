import Foundation

/// Normalized viewport over the already oriented and levelled preview.
/// Cropping stays in the view: entering/leaving the tool never decodes RAW again.
struct DevelopViewport {
  let rect: CGRect
  init(crop: J, editingCrop: Bool) {
    let values = crop.array.map(\.double)
    if !editingCrop, values.count == 4, values.allSatisfy({ $0.isFinite }),
      values[0] >= 0, values[1] >= 0, values[2] <= 1, values[3] <= 1,
      values[2] > values[0], values[3] > values[1] {
      rect = CGRect(x: values[0], y: values[1], width: values[2]-values[0], height: values[3]-values[1])
    } else { rect = CGRect(x: 0, y: 0, width: 1, height: 1) }
  }
  func fullRect(from displayed: [Double]) -> [Double] {
    [rect.minX + displayed[0]*rect.width, rect.minY + displayed[1]*rect.height,
     rect.minX + displayed[2]*rect.width, rect.minY + displayed[3]*rect.height]
  }
  func displayedRect(from full: [Double]) -> CGRect {
    CGRect(x: (full[0]-rect.minX)/rect.width, y: (full[1]-rect.minY)/rect.height,
           width: (full[2]-full[0])/rect.width, height: (full[3]-full[1])/rect.height)
  }
}
