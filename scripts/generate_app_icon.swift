#!/usr/bin/env swift
// Original vector artwork for RP Steuer App. No fonts, external assets or dependencies.
// Regenerate on macOS: swift scripts/generate_app_icon.swift
import AppKit

func color(_ hex: UInt32, alpha: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: alpha)
}

func rounded(_ rect: CGRect, radius: CGFloat) -> CGPath {
    CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius, transform: nil)
}

func pillow(inset: CGFloat = 0) -> CGPath {
    let path = CGMutablePath()
    path.move(to: CGPoint(x: 194 + inset, y: 296 + inset))
    path.addCurve(to: CGPoint(x: 754 - inset, y: 296 + inset),
                  control1: CGPoint(x: 367, y: 337 + inset), control2: CGPoint(x: 589, y: 321 + inset))
    path.addCurve(to: CGPoint(x: 760 - inset, y: 750 - inset),
                  control1: CGPoint(x: 728 - inset, y: 446), control2: CGPoint(x: 728 - inset, y: 608))
    path.addCurve(to: CGPoint(x: 188 + inset, y: 750 - inset),
                  control1: CGPoint(x: 568, y: 711 - inset), control2: CGPoint(x: 371, y: 713 - inset))
    path.addCurve(to: CGPoint(x: 194 + inset, y: 296 + inset),
                  control1: CGPoint(x: 231 + inset, y: 606), control2: CGPoint(x: 229 + inset, y: 447))
    path.closeSubpath()
    return path
}

func artwork(_ ctx: CGContext, scale: CGFloat) {
    // Top-left coordinates, matching the 1024 px design canvas.
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: 0, y: 1024)
    ctx.scaleBy(x: 1, y: -1)
    let tile = rounded(CGRect(x: 100, y: 100, width: 824, height: 824), radius: 184)
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -12 * scale), blur: 22 * scale,
                  color: color(0x092E36, alpha: 0.25))
    ctx.setFillColor(color(0x12646C))
    ctx.addPath(tile)
    ctx.fillPath()
    ctx.restoreGState()
    ctx.saveGState()
    ctx.addPath(tile)
    ctx.clip()
    let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                              colors: [color(0x248B8A), color(0x104B5B)] as CFArray,
                              locations: [0, 1])!
    ctx.drawLinearGradient(gradient, start: CGPoint(x: 180, y: 100),
                           end: CGPoint(x: 820, y: 924), options: [])
    ctx.restoreGState()

    // Soft cushion: concave edges and an inset stitched seam.
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -18 * scale), blur: 26 * scale,
                  color: color(0x062B38, alpha: 0.30))
    ctx.setFillColor(color(0xF7F0E2))
    ctx.addPath(pillow())
    ctx.fillPath()
    ctx.restoreGState()
    ctx.setStrokeColor(color(0xD9CDB8))
    ctx.setLineWidth(4)
    ctx.setLineDash(phase: 0, lengths: [7, 9])
    ctx.addPath(pillow(inset: 27))
    ctx.strokePath()
    ctx.setLineDash(phase: 0, lengths: [])

    // A small, calm fold on the left makes the cushion legible without lettering.
    let fold = CGMutablePath()
    fold.move(to: CGPoint(x: 263, y: 440))
    fold.addCurve(to: CGPoint(x: 267, y: 609),
                  control1: CGPoint(x: 279, y: 493), control2: CGPoint(x: 279, y: 555))
    ctx.setStrokeColor(color(0xE1D6C4))
    ctx.setLineWidth(8)
    ctx.setLineCap(.round)
    ctx.addPath(fold)
    ctx.strokePath()

    // Ledger / spreadsheet, overlapping the pillow on the right.
    let ledger = rounded(CGRect(x: 410, y: 263, width: 354, height: 454), radius: 38)
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -12 * scale), blur: 20 * scale,
                  color: color(0x203A40, alpha: 0.24))
    ctx.setFillColor(color(0xFFFFFF))
    ctx.addPath(ledger)
    ctx.fillPath()
    ctx.restoreGState()
    ctx.saveGState()
    ctx.addPath(ledger)
    ctx.clip()
    ctx.setFillColor(color(0x163E50))
    ctx.fill(CGRect(x: 410, y: 263, width: 354, height: 102))
    ctx.restoreGState()
    ctx.setFillColor(color(0x88D9CC))
    ctx.addPath(rounded(CGRect(x: 450, y: 305, width: 138, height: 17), radius: 8))
    ctx.fillPath()
    ctx.setFillColor(color(0x467986))
    ctx.addPath(rounded(CGRect(x: 661, y: 300, width: 60, height: 27), radius: 8))
    ctx.fillPath()
    ctx.setFillColor(color(0xEDF4F3))
    ctx.addPath(rounded(CGRect(x: 452, y: 405, width: 270, height: 223), radius: 12))
    ctx.fillPath()
    ctx.setStrokeColor(color(0xC2D8D6))
    ctx.setLineWidth(6)
    ctx.setLineCap(.butt)
    for y in [461, 517, 573] {
        ctx.move(to: CGPoint(x: 452, y: y))
        ctx.addLine(to: CGPoint(x: 722, y: y))
    }
    ctx.move(to: CGPoint(x: 618, y: 405))
    ctx.addLine(to: CGPoint(x: 618, y: 628))
    ctx.strokePath()
    ctx.setFillColor(color(0x73B6AE))
    ctx.addPath(rounded(CGRect(x: 477, y: 427, width: 93, height: 12), radius: 6))
    ctx.fillPath()

    // Confirmation badge: a warm accent that stays readable at Dock sizes.
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -10 * scale), blur: 16 * scale,
                  color: color(0x173C46, alpha: 0.25))
    ctx.setFillColor(color(0xEFB85B))
    ctx.fillEllipse(in: CGRect(x: 621, y: 604, width: 192, height: 192))
    ctx.restoreGState()
    ctx.setStrokeColor(color(0x183F4A))
    ctx.setLineWidth(21)
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)
    ctx.move(to: CGPoint(x: 675, y: 700))
    ctx.addLine(to: CGPoint(x: 705, y: 730))
    ctx.addLine(to: CGPoint(x: 761, y: 673))
    ctx.strokePath()
}

func png(size: Int) throws -> Data {
    let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                            bytesPerRow: size * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    artwork(context, scale: CGFloat(size) / 1024)
    let representation = NSBitmapImageRep(cgImage: context.makeImage()!)
    return representation.representation(using: .png, properties: [:])!
}

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let resources = root.appendingPathComponent("Resources", isDirectory: true)
let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
let iconset = temporary.appendingPathComponent("AppIcon.iconset", isDirectory: true)
try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: temporary) }
for size in [16, 32, 128, 256, 512] {
    for density in [1, 2] {
        let suffix = density == 2 ? "@2x" : ""
        let data = try png(size: size * density)
        try data.write(to: iconset.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
        if size == 512 && density == 2 {
            try data.write(to: resources.appendingPathComponent("AppIcon.png"))
        }
    }
}
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", iconset.path, "-o", resources.appendingPathComponent("AppIcon.icns").path]
try process.run()
process.waitUntilExit()
guard process.terminationStatus == 0 else { fatalError("iconutil failed") }
print("Generated Resources/AppIcon.png and Resources/AppIcon.icns")
