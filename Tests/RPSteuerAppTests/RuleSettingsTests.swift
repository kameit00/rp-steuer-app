import Foundation
import XCTest
@testable import RPSteuerApp

final class RuleSettingsTests: XCTestCase {
    private let production = """
    {"rules":[{"column":"Beschreibung","substring":"Gebühren","info_column_value":"Gebühr"}],"always_show_in_summary":["Leer"]}
    """
    private let edited = """
    {"rules":[{"column":"Beschreibung","substring":"Gebühren","info_column_value":"Personalisiert"}],"always_show_in_summary":["Immer zeigen"]}
    """

    private func fixture() throws -> (URL, URL, URL) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let bundle = root.appendingPathComponent("production.json")
        try Data(production.utf8).write(to: bundle)
        return (root, bundle, root.appendingPathComponent("Support/rules.json"))
    }

    @MainActor
    func testProductionDefaultDoesNotWriteUserFileAndDraftDoesNotApply() throws {
        let (_, bundle, user) = try fixture()
        let store = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        XCTAssertEqual(store.draft, production)
        XCTAssertNil(store.errorMessage)
        XCTAssertFalse(store.hasSavedDefaults)
        XCTAssertFalse(store.hasUnsavedChanges)
        XCTAssertEqual(try store.defaultRulesURL(), bundle)
        store.draft = edited
        XCTAssertTrue(store.hasUnsavedChanges)
        XCTAssertEqual(try store.defaultRulesURL(), bundle)
        XCTAssertFalse(FileManager.default.fileExists(atPath: user.path))
    }

    @MainActor
    func testSavePersistsExactlyAndSurvivesRelaunchWithoutEditingProduction() throws {
        let (_, bundle, user) = try fixture()
        let store = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        store.draft = edited
        store.save()
        XCTAssertNil(store.errorMessage)
        XCTAssertTrue(store.hasSavedDefaults)
        XCTAssertFalse(store.hasUnsavedChanges)
        XCTAssertEqual(try String(contentsOf: user, encoding: .utf8), edited)
        XCTAssertEqual(try String(contentsOf: bundle, encoding: .utf8), production)
        let relaunched = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        XCTAssertEqual(relaunched.draft, edited)
        XCTAssertEqual(try relaunched.defaultRulesURL(), user)
    }

    @MainActor
    func testInvalidSaveKeepsLastValidDefaultAndReloadDiscardsDraft() throws {
        let (_, bundle, user) = try fixture()
        let store = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        store.draft = edited
        store.save()
        store.draft = "{broken json"
        store.save()
        XCTAssertNotNil(store.errorMessage)
        XCTAssertTrue(store.hasUnsavedChanges)
        XCTAssertEqual(try String(contentsOf: user, encoding: .utf8), edited)
        XCTAssertEqual(try store.defaultRulesURL(), user)
        store.reload()
        XCTAssertEqual(store.draft, edited)
        XCTAssertNil(store.errorMessage)
    }

    @MainActor
    func testRestoreOnlyChangesDraftUntilSaved() throws {
        let (_, bundle, user) = try fixture()
        let store = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        store.draft = edited
        store.save()
        store.restoreProductionDraft()
        XCTAssertEqual(store.draft, production)
        XCTAssertTrue(store.hasUnsavedChanges)
        XCTAssertEqual(try String(contentsOf: user, encoding: .utf8), edited)
        store.save()
        XCTAssertEqual(try String(contentsOf: user, encoding: .utf8), production)
        XCTAssertEqual(try String(contentsOf: bundle, encoding: .utf8), production)
    }

    @MainActor
    func testCorruptSavedFileIsVisibleAndNeverSilentlyFallsBack() throws {
        let (_, bundle, user) = try fixture()
        try FileManager.default.createDirectory(at: user.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("{invalid".utf8).write(to: user)
        let store = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        XCTAssertEqual(store.draft, "{invalid")
        XCTAssertNotNil(store.errorMessage)
        XCTAssertThrowsError(try store.defaultRulesURL())
        store.restoreProductionDraft()
        store.save()
        XCTAssertNil(store.errorMessage)
        XCTAssertEqual(try store.defaultRulesURL(), user)
    }

    @MainActor
    func testWriteFailureDoesNotMarkDraftAsSaved() throws {
        let (root, bundle, _) = try fixture()
        let blocker = root.appendingPathComponent("not-a-folder")
        try Data().write(to: blocker)
        let store = RuleSettings(userRulesURL: blocker.appendingPathComponent("rules.json"), bundledRulesURL: bundle)
        store.draft = edited
        store.save()
        XCTAssertNotNil(store.errorMessage)
        XCTAssertFalse(store.hasSavedDefaults)
        XCTAssertTrue(store.hasUnsavedChanges)
        XCTAssertEqual(store.savedText, "") // Unreadable defaults never silently load a fallback.
    }

    @MainActor
    func testValidationPreservesLegacyListsEmptyRulesAndMatchingWhitespace() throws {
        for text in [production, edited, "[]", "{\"rules\":[]}",
                     "[{\"column\":\" Name \",\"substring\":\"\",\"info_column_value\":\"\"}]"] {
            XCTAssertNoThrow(try RuleSettings.validate(text))
        }
        for text in ["null", "42", "true", "{}", "{\"rules\":null}", "{\"rules\":{}}",
                     "[{}]", "[1]", "[{\"column\":2,\"substring\":\"x\",\"info_column_value\":\"y\"}]",
                     "{\"rules\":[],\"always_show_in_summary\":[1]}",
                     "{\"rules\":[],\"always_show_in_summary\":null}"] {
            XCTAssertThrowsError(try RuleSettings.validate(text), text)
        }
    }

    @MainActor
    func testSavedDefaultAndExternalOverrideReachPackagedEngine() async throws {
        guard let engine = ProcessInfo.processInfo.environment["RP_STEUER_APP_TEST_ENGINE"] else {
            throw XCTSkip("Set RP_STEUER_APP_TEST_ENGINE for Settings integration")
        }
        let previous = ProcessInfo.processInfo.environment["RP_STEUER_APP_ENGINE"]
        setenv("RP_STEUER_APP_ENGINE", engine, 1)
        defer {
            if let previous { setenv("RP_STEUER_APP_ENGINE", previous, 1) }
            else { unsetenv("RP_STEUER_APP_ENGINE") }
        }
        let (root, bundle, user) = try fixture()
        let store = RuleSettings(userRulesURL: user, bundledRulesURL: bundle)
        store.draft = edited
        store.save()
        let input = root.appendingPathComponent("input.csv")
        try Data("Bezahldatum;Beschreibung;Betrag\n01.10.2026;Gebühren;-1,25\n".utf8).write(to: input)
        let external = root.appendingPathComponent("external.json")
        try Data(edited.replacingOccurrences(of: "Personalisiert", with: "Extern").utf8).write(to: external)
        let model = AppModel(ruleSettings: store)
        model.addInputs([input])
        for (index, custom) in [nil, external].enumerated() {
            let output = root.appendingPathComponent("out-\(index)")
            try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
            model.outputDirectory = output
            model.rulesFile = custom
            // Unsaved changes must never influence a job.
            store.draft = "invalid unsaved edit"
            model.start()
            let deadline = Date().addingTimeInterval(15)
            while model.isProcessing && Date() < deadline {
                try await Task.sleep(nanoseconds: 20_000_000)
            }
            XCTAssertFalse(model.isProcessing)
            XCTAssertNil(model.errorMessage, model.errorMessage ?? "")
            let workbook = try XCTUnwrap(model.outputs.first)
            let unzip = Process()
            let pipe = Pipe()
            unzip.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
            unzip.arguments = ["-p", workbook.path, "xl/worksheets/sheet1.xml"]
            unzip.standardOutput = pipe
            try unzip.run()
            let xml = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            unzip.waitUntilExit()
            XCTAssertEqual(unzip.terminationStatus, 0)
            XCTAssertTrue(xml.contains(custom == nil ? "Personalisiert" : "Extern"))
            if custom != nil { XCTAssertFalse(xml.contains("Personalisiert")) }
        }
        XCTAssertEqual(try String(contentsOf: external, encoding: .utf8), edited.replacingOccurrences(of: "Personalisiert", with: "Extern"))
        XCTAssertEqual(try String(contentsOf: bundle, encoding: .utf8), production)
    }
}
