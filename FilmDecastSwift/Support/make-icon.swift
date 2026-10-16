import AppKit
let folder=URL(fileURLWithPath:CommandLine.arguments[1])
try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
func draw(_ pixels:Int)->Data {
    let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    let ctx=NSGraphicsContext(bitmapImageRep:rep)!
    NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=ctx
    ctx.cgContext.scaleBy(x:Double(pixels)/1024,y:Double(pixels)/1024)
    let tile=NSBezierPath(roundedRect:NSRect(x:56,y:56,width:912,height:912),xRadius:200,yRadius:200)
    NSGradient(starting:NSColor(calibratedWhite:0.21,alpha:1),ending:NSColor(calibratedWhite:0.055,alpha:1))!.draw(in:tile,angle:-90)
    let film=NSBezierPath(roundedRect:NSRect(x:200,y:235,width:624,height:554),xRadius:64,yRadius:64)
    NSGradient(starting:NSColor(calibratedRed:1,green:0.74,blue:0.28,alpha:1),ending:NSColor(calibratedRed:0.94,green:0.39,blue:0.13,alpha:1))!.draw(in:film,angle:-90)
    NSColor(calibratedWhite:0.085,alpha:1).setFill()
    for x in stride(from:248,to:800,by:104){for y in [268,713]{NSBezierPath(roundedRect:NSRect(x:x,y:y,width:55,height:40),xRadius:9,yRadius:9).fill()}}
    NSBezierPath(roundedRect:NSRect(x:249,y:345,width:526,height:335),xRadius:20,yRadius:20).fill()
    let mark=NSBezierPath();mark.move(to:NSPoint(x:305,y:410));mark.line(to:NSPoint(x:447,y:590));mark.line(to:NSPoint(x:553,y:459));mark.line(to:NSPoint(x:623,y:544));mark.line(to:NSPoint(x:723,y:410));mark.close()
    NSColor(calibratedRed:1,green:0.63,blue:0.24,alpha:1).setFill();mark.fill()
    NSBezierPath(ovalIn:NSRect(x:612,y:578,width:42,height:42)).fill()
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using:.png,properties:[:])!
}
for size in [16,32,128,256,512] {
    try draw(size).write(to:folder.appendingPathComponent("icon_\(size)x\(size).png"))
    try draw(size*2).write(to:folder.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
