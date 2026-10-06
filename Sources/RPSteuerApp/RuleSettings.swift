import Foundation
import SwiftUI
import Darwin

/// User-owned defaults live outside the signed bundle and production snapshot.
@MainActor
final class RuleSettings: ObservableObject {
    @Published var draft = ""
    @Published private(set) var savedText = ""
    @Published private(set) var hasSavedDefaults = false
    @Published var errorMessage: String?
    @Published private(set) var notice: String?

    let userRulesURL: URL
    let bundledRulesURL: URL?
    private var migrationError: String?
    var hasUnsavedChanges: Bool { draft != savedText }

    init(userRulesURL: URL? = nil, bundledRulesURL: URL? = nil, legacyRulesURL: URL? = nil) {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        self.userRulesURL = userRulesURL ?? support
            .appendingPathComponent("com.relax-pillow.rpsteuerapp", isDirectory: true)
            .appendingPathComponent("rules.json")
        self.bundledRulesURL = bundledRulesURL ?? Self.findBundledRules()
        // The dated identifier is retained ONLY to migrate local prototype settings.
        // Injected test stores never inspect actual user settings unless requested.
        let legacy = legacyRulesURL ?? (userRulesURL == nil ? support
            .appendingPathComponent("com.relax-pillow.rpsteuer.gui202610", isDirectory: true)
            .appendingPathComponent("rules.json") : nil)
        var migrated = false
        do {
            if let legacy { migrated = try migrateLegacyDefaults(from: legacy) }
        } catch {
            migrationError = "Bisherige Standardregeln konnten nicht übernommen werden: " + error.localizedDescription
        }
        reload()
        if migrated && errorMessage == nil { notice = "Bestehende Standardregeln wurden übernommen. Die bisherige Datei bleibt erhalten." }
    }

    private func migrateLegacyDefaults(from legacy: URL) throws -> Bool {
        let manager = FileManager.default
        guard try !Self.itemExists(userRulesURL), try Self.itemExists(legacy) else { return false }
        try manager.createDirectory(at: userRulesURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                                    attributes: [.posixPermissions: 0o700])
        do {
            // Preserve exact bytes, including damaged drafts so they can be repaired.
            // copyItem is exclusive: another app instance's defaults cannot be overwritten.
            try manager.copyItem(at: legacy, to: userRulesURL)
        } catch {
            if (try? Self.itemExists(userRulesURL)) == true { return false }
            throw error
        }
        return true
    }

    private static func findBundledRules() -> URL? {
        let resource = Bundle.main.resourceURL?.appendingPathComponent("rules.json")
        if let resource, FileManager.default.isReadableFile(atPath: resource.path) { return resource }
        // swift run uses the packaged engine override; its data includes the same snapshot.
        if let engine = ProcessInfo.processInfo.environment["RP_STEUER_APP_ENGINE"],
           NSString(string: engine).isAbsolutePath {
            let resource = URL(fileURLWithPath: engine).deletingLastPathComponent()
                .appendingPathComponent("_internal/production/rules.json")
            if FileManager.default.isReadableFile(atPath: resource.path) { return resource }
        }
        return nil
    }

    /// Mirrors engine.load_rules: preserve order, whitespace in values, and legacy lists.
    static func validate(_ text: String) throws {
        guard let data = text.data(using: .utf8) else { throw failure("Regeln sind kein gültiger UTF-8-Text.") }
        let root = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        let rules: [Any]
        if let list = root as? [Any] {
            rules = list
        } else if let object = root as? [String: Any], let list = object["rules"] as? [Any] {
            rules = list
            if let categories = object["always_show_in_summary"] {
                guard let list = categories as? [Any], list.allSatisfy({ $0 is String }) else {
                    throw failure("always_show_in_summary muss eine Liste von Texten sein.")
                }
            }
        } else {
            throw failure("Erwartet wird ein JSON-Objekt mit 'rules' oder eine Regelliste.")
        }
        for (index, rule) in rules.enumerated() {
            guard let rule = rule as? [String: Any],
                  ["column", "substring", "info_column_value"].allSatisfy({ rule[$0] is String }) else {
                throw failure("Regel \(index + 1): column, substring und info_column_value müssen Texte sein.")
            }
        }
    }

    /// Called at job start, never returns unsaved editor contents. Corrupt saved
    /// defaults fail explicitly instead of silently reverting financial categories.
    func defaultRulesURL() throws -> URL? {
        let exists = try Self.itemExists(userRulesURL)
        if let migrationError, !exists { throw Self.failure(migrationError) }
        let url = exists ? userRulesURL : bundledRulesURL
        if let url { try Self.validate(String(contentsOf: url, encoding: .utf8)) }
        return url
    }

    func reload() {
        notice = nil
        hasSavedDefaults = false
        do {
            hasSavedDefaults = try Self.itemExists(userRulesURL)
            guard let url = hasSavedDefaults ? userRulesURL : bundledRulesURL else {
                throw Self.failure("Produktionsregeln nicht gefunden. Bitte eine gebaute App öffnen oder gültige Regeln einfügen.")
            }
            let text = try String(contentsOf: url, encoding: .utf8)
            draft = text
            savedText = text
            try Self.validate(text)
            if let migrationError, !hasSavedDefaults { throw Self.failure(migrationError) }
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }

    func save() {
        notice = nil
        do {
            try Self.validate(draft)
            let directory = userRulesURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            try Data(draft.utf8).write(to: userRulesURL, options: .atomic)
            savedText = draft
            hasSavedDefaults = true
            migrationError = nil
            errorMessage = nil
            notice = "Gespeichert. Gilt für die nächste PayPal-Verarbeitung mit Standardregeln."
        } catch { errorMessage = error.localizedDescription }
    }

    /// Only updates the draft. Restoring defaults cannot overwrite edits without
    /// confirmation, and persistence still requires an explicit Save.
    func restoreProductionDraft() {
        notice = nil
        do {
            guard let bundledRulesURL else { throw Self.failure("Produktionsregeln nicht gefunden.") }
            let text = try String(contentsOf: bundledRulesURL, encoding: .utf8)
            try Self.validate(text)
            draft = text
            errorMessage = nil
            notice = "Produktionsregeln geladen. Zum Übernehmen bitte speichern."
        } catch { errorMessage = error.localizedDescription }
    }

    private static func itemExists(_ url: URL) throws -> Bool {
        // lstat sees dangling symlinks and differentiates absence from permission
        // errors. Never silently change financial categories on a lookup failure.
        var info = stat()
        if lstat(url.path, &info) == 0 { return true }
        let code = errno
        if code == ENOENT { return false }
        throw failure("Kein Zugriff auf Regeldatei \(url.path): \(String(cString: strerror(code)))")
    }

    private static func failure(_ message: String) -> EngineFailure { EngineFailure(message: message) }
}
