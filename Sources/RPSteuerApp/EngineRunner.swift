import Foundation

struct EngineRequest: Encodable {
    let mode: String
    let inputs: [String]
    let outputDirectory: String
    let rulesFile: String?

    enum CodingKeys: String, CodingKey {
        case mode, inputs
        case outputDirectory = "output_directory"
        case rulesFile = "rules_file"
    }
}

struct EngineResult {
    let success: Bool
    let files: [String]
    let error: String?
}

struct EngineFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// Buffers bytes, not decoded strings: pipe reads may split a UTF-8 character.
struct LineBuffer {
    private var pending = Data()
    private let maximumLineBytes = 1_048_576

    mutating func append(_ data: Data, consume: (Data) -> Void) throws {
        pending.append(data)
        while let newline = pending.firstIndex(of: 10) {
            let line = Data(pending[..<newline])
            guard line.count <= maximumLineBytes else { throw tooLong() }
            consume(line)
            pending.removeSubrange(...newline)
        }
        guard pending.count <= maximumLineBytes else { throw tooLong() }
    }

    mutating func finish(consume: (Data) -> Void) {
        if !pending.isEmpty { consume(pending) }
        pending.removeAll()
    }

    private func tooLong() -> EngineFailure {
        EngineFailure(message: "Eine Ausgabezeile der Engine ist zu groß.")
    }
}

private struct EngineEvent: Decodable {
    let type: String
    let message: String?
    let success: Bool?
    let files: [String]?
    let error: String?
}

/// Each instance is written by exactly one pipe reader, then read after group.wait().
private final class PipeOutput {
    var result: EngineResult?
    var protocolError: String?
    var stderr = ""
}

enum EngineRunner {
    static func executableURL(environment: [String: String] = ProcessInfo.processInfo.environment,
                              resourceURL: URL? = Bundle.main.resourceURL) throws -> URL {
        if let override = environment["RP_STEUER_APP_ENGINE"], !override.isEmpty {
            guard NSString(string: override).isAbsolutePath else {
                throw EngineFailure(message: "RP_STEUER_APP_ENGINE muss ein absoluter Pfad zur ausführbaren Engine sein.")
            }
            return URL(fileURLWithPath: override)
        }
        guard let resourceURL else {
            throw EngineFailure(message: "Die mitgelieferte Engine wurde nicht gefunden.")
        }
        return resourceURL.appendingPathComponent("engine/rp-steuer-app-engine/rp-steuer-app-engine")
    }

    static func run(_ request: EngineRequest,
                    onLog: @escaping @Sendable (String) -> Void) async throws -> EngineResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    continuation.resume(returning: try execute(request, onLog: onLog))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private static func execute(_ request: EngineRequest,
                                onLog: @escaping @Sendable (String) -> Void) throws -> EngineResult {
        let executable = try executableURL()
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw EngineFailure(message: "Engine nicht ausführbar oder nicht gefunden: \(executable.path)")
        }
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent("rp-steuer-app-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: temporary) }
        let requestFile = temporary.appendingPathComponent("request.json")
        try JSONEncoder().encode(request).write(to: requestFile, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: requestFile.path)

        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = executable
        process.arguments = ["--request", requestFile.path]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()

        let group = DispatchGroup()
        let output = PipeOutput()
        let errors = PipeOutput()
        drain(stdout.fileHandleForReading, group: group, state: output) { data in
            guard !data.isEmpty else { return }
            do {
                let event = try JSONDecoder().decode(EngineEvent.self, from: data)
                switch event.type {
                case "log":
                    guard let message = event.message else { throw invalidEvent() }
                    onLog(message)
                case "result":
                    guard let success = event.success, let files = event.files, output.result == nil else {
                        throw invalidEvent()
                    }
                    output.result = EngineResult(success: success, files: files, error: event.error)
                default:
                    throw invalidEvent()
                }
            } catch {
                output.protocolError = "Ungültige JSON-Ausgabe der Engine: \(error.localizedDescription)"
            }
        }
        drain(stderr.fileHandleForReading, group: group, state: errors) { data in
            let message = String(decoding: data, as: UTF8.self)
            if !message.isEmpty {
                onLog("Engine: \(message)")
                // Keep only a bounded tail of human-readable diagnostics.
                errors.stderr = String((errors.stderr + message + "\n").suffix(16_000))
            }
        }
        process.waitUntilExit()
        group.wait()

        if let error = output.protocolError ?? errors.protocolError {
            throw EngineFailure(message: error)
        }
        guard let result = output.result else {
            throw EngineFailure(message: diagnostic("Die Engine wurde ohne Ergebnis beendet (Status \(process.terminationStatus)).", errors.stderr))
        }
        guard process.terminationReason == .exit && process.terminationStatus == 0 else {
            throw EngineFailure(message: diagnostic(result.error ?? "Die Engine wurde mit Fehlerstatus \(process.terminationStatus) beendet.", errors.stderr))
        }
        return result
    }

    private static func drain(_ handle: FileHandle, group: DispatchGroup, state: PipeOutput,
                              consume: @escaping (Data) -> Void) {
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            defer {
                try? handle.close()
                group.leave()
            }
            var buffer = LineBuffer()
            var lineError = false
            do {
                while let data = try handle.read(upToCount: 8192), !data.isEmpty {
                    // Even after a protocol error, drain the pipe to avoid blocking the child.
                    if !lineError {
                        do { try buffer.append(data, consume: consume) }
                        catch {
                            state.protocolError = error.localizedDescription
                            lineError = true
                        }
                    }
                }
                if !lineError { buffer.finish(consume: consume) }
            } catch {
                state.protocolError = "Engine-Ausgabe konnte nicht gelesen werden: \(error.localizedDescription)"
            }
        }
    }

    private static func invalidEvent() -> EngineFailure {
        EngineFailure(message: "Unbekanntes oder unvollständiges Ereignis.")
    }

    private static func diagnostic(_ message: String, _ stderr: String) -> String {
        stderr.isEmpty ? message : message + "\n\n" + stderr
    }
}
