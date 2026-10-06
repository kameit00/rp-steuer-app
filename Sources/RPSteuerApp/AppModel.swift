import AppKit
import SwiftUI
import UniformTypeIdentifiers

enum ConversionMode: String, CaseIterable, Identifiable {
    case paypal, sevdesk
    var id: String { rawValue }
    var title: String { self == .paypal ? "PayPal" : "sevDesk" }
}

enum InputFiles {
    /// Only direct child CSV files are included; subfolders are never traversed.
    static func expand(_ urls: [URL]) throws -> [URL] {
        var paths = Set<String>()
        for url in urls {
            let values = try url.resourceValues(forKeys: [.isDirectoryKey, .isRegularFileKey])
            if values.isDirectory == true {
                for child in try FileManager.default.contentsOfDirectory(at: url,
                    includingPropertiesForKeys: [.isRegularFileKey], options: [.skipsHiddenFiles]) {
                    if child.pathExtension.lowercased() == "csv",
                       try child.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
                        paths.insert(child.standardizedFileURL.path)
                    }
                }
            } else if values.isRegularFile == true && url.pathExtension.lowercased() == "csv"
                        && !url.lastPathComponent.hasPrefix("._") {
                paths.insert(url.standardizedFileURL.path)
            } else {
                throw EngineFailure(message: "Bitte nur CSV-Dateien oder Ordner auswählen: \(url.path)")
            }
        }
        return paths.sorted().map { URL(fileURLWithPath: $0) }
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var mode: ConversionMode = .paypal
    @Published private(set) var inputs: [URL] = []
    @Published var outputDirectory: URL?
    @Published var rulesFile: URL?
    @Published private(set) var isProcessing = false
    @Published private(set) var outputs: [URL] = []
    @Published private(set) var logText = ""
    @Published private(set) var status = "Bereit"
    @Published var errorMessage: String?

    let ruleSettings: RuleSettings

    init(ruleSettings: RuleSettings? = nil) {
        self.ruleSettings = ruleSettings ?? RuleSettings()
    }

    var canRun: Bool { !isProcessing && !inputs.isEmpty && outputDirectory != nil }

    func addInputs(_ urls: [URL]) {
        guard !isProcessing else { return }
        do {
            let expanded = try InputFiles.expand(urls)
            inputs = Array(Set(inputs + expanded)).sorted { $0.path < $1.path }
            if expanded.isEmpty { errorMessage = "In der Auswahl wurden keine CSV-Dateien gefunden. Unterordner werden nicht durchsucht." }
        } catch { errorMessage = error.localizedDescription }
    }

    func removeInput(_ url: URL) {
        guard !isProcessing else { return }
        inputs.removeAll { $0 == url }
    }

    func clearInputs() {
        guard !isProcessing else { return }
        inputs.removeAll()
    }

    func chooseInputs() {
        guard !isProcessing else { return }
        let panel = NSOpenPanel()
        panel.title = "CSV-Dateien oder Ordner auswählen"
        panel.prompt = "Hinzufügen"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.commaSeparatedText]
        if panel.runModal() == .OK { addInputs(panel.urls) }
    }

    func chooseOutput() {
        guard !isProcessing else { return }
        let panel = NSOpenPanel()
        panel.title = "Ausgabeordner auswählen"
        panel.prompt = "Auswählen"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        if panel.runModal() == .OK { outputDirectory = panel.url?.standardizedFileURL }
    }

    func chooseRules() {
        guard !isProcessing else { return }
        let panel = NSOpenPanel()
        panel.title = "PayPal-Regeln (rules.json) auswählen"
        panel.allowedContentTypes = [.json]
        panel.canChooseDirectories = false
        if panel.runModal() == .OK { rulesFile = panel.url?.standardizedFileURL }
    }

    func receiveDrop(_ providers: [NSItemProvider]) -> Bool {
        guard !isProcessing else { return false }
        let matching = providers.filter { $0.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) }
        guard !matching.isEmpty else { return false }
        for provider in matching {
            provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { [weak self] data, error in
                Task { @MainActor in
                    guard let self, !self.isProcessing else { return }
                    if let data, let url = URL(dataRepresentation: data, relativeTo: nil), url.isFileURL {
                        self.addInputs([url])
                    } else {
                        self.errorMessage = error?.localizedDescription ?? "Die abgelegte Datei konnte nicht gelesen werden."
                    }
                }
            }
        }
        return true
    }

    func start() {
        guard canRun, let outputDirectory else { return }
        let selectedRules: URL?
        do {
            selectedRules = mode == .paypal ? try (rulesFile ?? ruleSettings.defaultRulesURL()) : nil
        } catch {
            errorMessage = "Standardregeln konnten nicht geladen werden. Bitte in den Einstellungen prüfen.\n\n" + error.localizedDescription
            return
        }
        let request = EngineRequest(mode: mode.rawValue, inputs: inputs.map(\.path),
                                    outputDirectory: outputDirectory.path,
                                    rulesFile: selectedRules?.path)
        isProcessing = true
        outputs = []
        logText = ""
        errorMessage = nil
        status = "Verarbeitung läuft …"
        appendLog("\(mode.title): \(inputs.count) CSV-Datei(en). Eingabedateien werden nicht gelöscht.")
        Task { [self] in
            defer { isProcessing = false }
            do {
                let result = try await EngineRunner.run(request) { [weak self] message in
                    DispatchQueue.main.async { self?.appendLog(message) }
                }
                outputs = result.files.map { URL(fileURLWithPath: $0) }
                if result.success {
                    status = "Fertig – \(outputs.count) Ausgabedatei(en)"
                    appendLog(status)
                } else {
                    status = "Verarbeitung fehlgeschlagen"
                    errorMessage = result.error ?? "Die Engine meldet einen Fehler ohne weitere Beschreibung."
                    appendLog(errorMessage!)
                }
            } catch {
                status = "Verarbeitung fehlgeschlagen"
                errorMessage = error.localizedDescription
                appendLog(error.localizedDescription)
            }
        }
    }

    private func appendLog(_ message: String) {
        // Bounded tail: repeated engine messages must not grow UI memory indefinitely.
        logText = String((logText + message + "\n").suffix(100_000))
    }
}
