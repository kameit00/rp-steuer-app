// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RPSteuerApp",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "RPSteuerApp", targets: ["RPSteuerApp"])],
    targets: [
        .executableTarget(name: "RPSteuerApp"),
        .testTarget(name: "RPSteuerAppTests", dependencies: ["RPSteuerApp"])
    ],
    swiftLanguageVersions: [.v5]
)
