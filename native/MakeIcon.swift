import AppKit

let output = CommandLine.arguments[1]
try FileManager.default.createDirectory(atPath: output, withIntermediateDirectories: true)
for logicalSize in [16, 32, 128, 256, 512] {
  for scale in [1, 2] {
    let size = logicalSize * scale
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()
    let s = CGFloat(size)
    let bounds = NSRect(x: s * 0.07, y: s * 0.07, width: s * 0.86, height: s * 0.86)
    let path = NSBezierPath(roundedRect: bounds, xRadius: s * 0.20, yRadius: s * 0.20)
    NSGradient(starting: NSColor(srgbRed: 0.13, green: 0.26, blue: 0.24, alpha: 1), ending: NSColor(srgbRed: 0.035, green: 0.065, blue: 0.09, alpha: 1))!.draw(in: path, angle: -70)
    NSColor(srgbRed: 0.32, green: 0.55, blue: 0.50, alpha: 1).setStroke(); path.lineWidth = max(1, s * 0.008); path.stroke()
    let text = "f." as NSString
    let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: s * 0.64, weight: .semibold), .foregroundColor: NSColor(srgbRed: 0.57, green: 0.92, blue: 0.85, alpha: 1), .kern: -s * 0.05]
    let textSize = text.size(withAttributes: attrs)
    text.draw(at: NSPoint(x: (s - textSize.width) / 2 - s * 0.012, y: (s - textSize.height) / 2 + s * 0.015), withAttributes: attrs)
    image.unlockFocus()
    let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
    let suffix = scale == 2 ? "@2x" : ""
    try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: output + "/icon_\(logicalSize)x\(logicalSize)\(suffix).png"))
  }
}
