import Foundation
import XCTest
@testable import RPSteuerApp

final class SettingsMigrationTests: XCTestCase {
    private let rules = "{\"rules\":[],\"always_show_in_summary\":[\"Übernommen\"]}"

    private func fixture() throws -> (URL, URL, URL) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let legacy = root.appendingPathComponent("legacy/rules.json")
        try FileManager.default.createDirectory(at: legacy.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(rules.utf8).write(to: legacy)
        return (root, legacy, root.appendingPathComponent("new/rules.json"))
    }

    @MainActor
    func testMigrationCopiesExactRulesWithoutDeletingOldFile() throws {
        let (_, legacy, new) = try fixture()
        let original = try Data(contentsOf: legacy)
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: legacy, legacyRulesURL: legacy)
        XCTAssertNil(store.errorMessage)
        XCTAssertEqual(store.draft, rules)
        XCTAssertTrue(store.hasSavedDefaults)
        XCTAssertNotNil(store.notice)
        XCTAssertEqual(try Data(contentsOf: new), original)
        XCTAssertEqual(try Data(contentsOf: legacy), original)
        XCTAssertEqual(try store.defaultRulesURL(), new)
    }

    @MainActor
    func testExistingNewDefaultsWinAndMigrationIsNotRepeated() throws {
        let (_, legacy, new) = try fixture()
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: legacy, legacyRulesURL: legacy)
        let updated = "{\"rules\":[],\"always_show_in_summary\":[\"Neu\"]}"
        store.draft = updated
        store.save()
        try Data("invalid old file".utf8).write(to: legacy)
        let next = RuleSettings(userRulesURL: new, bundledRulesURL: legacy, legacyRulesURL: legacy)
        XCTAssertNil(next.errorMessage)
        XCTAssertEqual(next.draft, updated)
        XCTAssertEqual(try String(contentsOf: new, encoding: .utf8), updated)
        XCTAssertEqual(try String(contentsOf: legacy, encoding: .utf8), "invalid old file")
    }

    @MainActor
    func testInvalidLegacyRulesArePreservedAndReportedNotReplaced() throws {
        let (_, legacy, new) = try fixture()
        try Data("{broken".utf8).write(to: legacy)
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: legacy, legacyRulesURL: legacy)
        XCTAssertEqual(store.draft, "{broken")
        XCTAssertNotNil(store.errorMessage)
        XCTAssertThrowsError(try store.defaultRulesURL())
        XCTAssertEqual(try Data(contentsOf: new), try Data(contentsOf: legacy))
    }

    @MainActor
    func testMissingLegacyFileUsesBundledDefaultsWithoutCreatingUserFile() throws {
        let (root, bundle, new) = try fixture()
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: bundle,
                                 legacyRulesURL: root.appendingPathComponent("missing.json"))
        XCTAssertNil(store.errorMessage)
        XCTAssertEqual(try store.defaultRulesURL(), bundle)
        XCTAssertFalse(FileManager.default.fileExists(atPath: new.path))
    }

    @MainActor
    func testDanglingSavedSettingsSymlinkDoesNotSelectProductionDefaults() throws {
        let (root, bundle, new) = try fixture()
        try FileManager.default.createDirectory(at: new.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: new, withDestinationURL: root.appendingPathComponent("missing.json"))
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: bundle)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertThrowsError(try store.defaultRulesURL())
    }

    @MainActor
    func testInaccessibleSavedSettingsDoNotSelectProductionDefaults() throws {
        let (_, bundle, new) = try fixture()
        let directory = new.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data(rules.utf8).write(to: new)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: directory.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path) }
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: bundle)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertThrowsError(try store.defaultRulesURL())
    }

    @MainActor
    func testInaccessibleLegacySettingsBlockMigrationFallback() throws {
        let (_, legacy, new) = try fixture()
        let directory = legacy.deletingLastPathComponent()
        let bundle = new.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("bundle.json")
        try Data(rules.utf8).write(to: bundle)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: directory.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path) }
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: bundle, legacyRulesURL: legacy)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertThrowsError(try store.defaultRulesURL())
        XCTAssertFalse(FileManager.default.fileExists(atPath: new.path))
    }

    @MainActor
    func testMigrationFailureBlocksSilentFallback() throws {
        let (root, legacy, _) = try fixture()
        let blocker = root.appendingPathComponent("file-not-directory")
        try Data().write(to: blocker)
        let new = blocker.appendingPathComponent("rules.json")
        let store = RuleSettings(userRulesURL: new, bundledRulesURL: legacy, legacyRulesURL: legacy)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertThrowsError(try store.defaultRulesURL())
        XCTAssertFalse(FileManager.default.fileExists(atPath: new.path))
        XCTAssertEqual(try String(contentsOf: legacy, encoding: .utf8), rules)
    }
}
