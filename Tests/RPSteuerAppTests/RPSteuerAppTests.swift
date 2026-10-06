import Foundation
import XCTest
@testable import RPSteuerApp

final class RPSteuerAppTests: XCTestCase {
    func testCSVExpansionIsNonrecursiveCaseInsensitiveAndSorted() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("nested"), withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        for name in ["z.csv", "A.CSV", ".hidden.CsV", "._z.csv", "ignore.txt", "nested/skip.csv"] {
            try Data().write(to: root.appendingPathComponent(name))
        }
        let files = try InputFiles.expand([root, root.appendingPathComponent("z.csv")])
        XCTAssertEqual(files.map(\.lastPathComponent), ["A.CSV", "z.csv"])
        XCTAssertEqual(try InputFiles.expand([root.appendingPathComponent(".hidden.CsV")]).count, 1)
        XCTAssertThrowsError(try InputFiles.expand([root.appendingPathComponent("._z.csv")]))
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("z.csv").path))
    }

    func testPackagedEngineTransport() async throws {
        guard let executable = ProcessInfo.processInfo.environment["RP_STEUER_APP_TEST_ENGINE"] else {
            throw XCTSkip("Set RP_STEUER_APP_TEST_ENGINE for packaged Process integration")
        }
        let previous = ProcessInfo.processInfo.environment["RP_STEUER_APP_ENGINE"]
        setenv("RP_STEUER_APP_ENGINE", executable, 1)
        defer {
            if let previous { setenv("RP_STEUER_APP_ENGINE", previous, 1) }
            else { unsetenv("RP_STEUER_APP_ENGINE") }
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("transport-ü-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let input = root.appendingPathComponent("Müller.csv")
        try Data("Bezahldatum;Beschreibung;Betrag\n01.10.2026;Gebühren;-1,25\n".utf8).write(to: input)
        let request = EngineRequest(mode: "paypal", inputs: [input.path], outputDirectory: root.path, rulesFile: nil)
        let result = try await EngineRunner.run(request, onLog: { _ in })
        XCTAssertTrue(result.success)
        XCTAssertEqual(result.files.count, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: try XCTUnwrap(result.files.first)))
        XCTAssertTrue(FileManager.default.fileExists(atPath: input.path))
        // Existing outputs must surface as a failed Process result, not success.
        do {
            _ = try await EngineRunner.run(request, onLog: { _ in })
            XCTFail("Expected output collision to fail")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("existiert bereits"))
        }
    }

    func testRequestSchema() throws {
        let request = EngineRequest(mode: "paypal", inputs: ["/input/a.csv"],
                                    outputDirectory: "/output", rulesFile: "/rules.json")
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
        XCTAssertEqual(Set(object.keys), ["mode", "inputs", "output_directory", "rules_file"])
        XCTAssertEqual(object["rules_file"] as? String, "/rules.json")
        let noRules = EngineRequest(mode: "sevdesk", inputs: [], outputDirectory: "/output", rulesFile: nil)
        let noRulesObject = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(noRules)) as? [String: Any])
        XCTAssertNil(noRulesObject["rules_file"])
    }

    func testUTF8AcrossChunksAndFinalLineWithoutNewline() throws {
        let bytes = Data("Grüße\nFertig ✓".utf8)
        var buffer = LineBuffer()
        var lines: [String] = []
        for byte in bytes {
            try buffer.append(Data([byte])) { lines.append(String(decoding: $0, as: UTF8.self)) }
        }
        buffer.finish { lines.append(String(decoding: $0, as: UTF8.self)) }
        XCTAssertEqual(lines, ["Grüße", "Fertig ✓"])
    }

    func testOversizedLineIsRejected() {
        var buffer = LineBuffer()
        XCTAssertThrowsError(try buffer.append(Data(repeating: 65, count: 1_048_577)) { _ in })
    }

    func testEngineLocationAndAbsoluteOverride() throws {
        XCTAssertEqual(try EngineRunner.executableURL(environment: [:], resourceURL: URL(fileURLWithPath: "/App/Contents/Resources")).path,
                       "/App/Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine")
        XCTAssertEqual(try EngineRunner.executableURL(environment: ["RP_STEUER_APP_ENGINE": "/development/engine"]).path, "/development/engine")
        XCTAssertThrowsError(try EngineRunner.executableURL(environment: ["RP_STEUER_APP_ENGINE": "relative/engine"]))
    }
}
