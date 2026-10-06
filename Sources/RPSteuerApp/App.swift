import AppKit
import SwiftUI

@MainActor
final class ApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard model?.isProcessing == true else { return .terminateNow }
        showProcessingAlert()
        return .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { sender.windows.first { $0.title == "RP Steuer App" }?.makeKeyAndOrderFront(nil) }
        return true
    }

    static func processingAlert() {
        let alert = NSAlert()
        alert.messageText = "Verarbeitung läuft"
        alert.informativeText = "Bitte warten Sie, bis die Verarbeitung beendet ist. Die Anwendung kann währenddessen nicht geschlossen werden."
        alert.addButton(withTitle: "Weiter warten")
        alert.runModal()
    }

    private func showProcessingAlert() { Self.processingAlert() }
}

/// Preserve SwiftUI's window delegate while vetoing close during processing.
@MainActor
private final class CloseGuardDelegate: NSObject, NSWindowDelegate {
    weak var original: NSWindowDelegate?
    weak var model: AppModel?

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if model?.isProcessing == true {
            ApplicationDelegate.processingAlert()
            return false
        }
        return original?.windowShouldClose?(sender) ?? true
    }

    override func responds(to selector: Selector!) -> Bool {
        super.responds(to: selector) || (original?.responds(to: selector) ?? false)
    }

    override func forwardingTarget(for selector: Selector!) -> Any? {
        original?.responds(to: selector) == true ? original : super.forwardingTarget(for: selector)
    }
}

@MainActor
struct WindowCloseGuard: NSViewRepresentable {
    let model: AppModel

    @MainActor
    final class Coordinator {
        fileprivate let delegate = CloseGuardDelegate()
        // Retain the original delegate for the lifetime of this window.
        fileprivate var original: NSWindowDelegate?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> NSView { NSView() }
    func updateNSView(_ nsView: NSView, context: Context) {
        let coordinator = context.coordinator
        DispatchQueue.main.async {
            guard let window = nsView.window else { return }
            coordinator.delegate.model = model
            if window.delegate !== coordinator.delegate {
                coordinator.original = window.delegate
                coordinator.delegate.original = window.delegate
                window.delegate = coordinator.delegate
            }
        }
    }
}

@main
@MainActor
struct RPSteuerApp: App {
    @NSApplicationDelegateAdaptor(ApplicationDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        Window("RP Steuer App", id: "main") {
            ContentView(model: model, settings: model.ruleSettings)
                .background(WindowCloseGuard(model: model))
                .onAppear { appDelegate.model = model }
        }
        .defaultSize(width: 940, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
        Settings {
            SettingsView(model: model, settings: model.ruleSettings)
        }
    }
}
