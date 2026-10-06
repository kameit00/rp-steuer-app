import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: RuleSettings
    @State private var confirmRestore = false
    @State private var confirmDiscard = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("PayPal-Standardregeln").font(.title2.bold())
            Text("Diese Regeln gelten, wenn im Hauptfenster keine externe rules.json ausgewählt ist. Änderungen werden erst mit „Speichern“ übernommen.")
                .foregroundStyle(.secondary)
            Text("Regeln werden von oben nach unten geprüft: Der erste Treffer gewinnt. Groß-/Kleinschreibung und Leerzeichen sind relevant. Eine leere substring passt auf jeden Wert der Spalte.")
                .font(.callout)
            Text("column = CSV-Spalte · substring = gesuchter Text · info_column_value = Kategorie\nalways_show_in_summary = Kategorien, die auch ohne Buchungen in der Zusammenfassung stehen")
                .font(.caption).foregroundStyle(.secondary)

            GroupBox("rules.json (JSON)") {
                TextEditor(text: $settings.draft)
                    .font(.system(.body, design: .monospaced))
                    .autocorrectionDisabled()
                    .frame(minHeight: 330)
                    .padding(4)
                    .accessibilityLabel("Standardregeln als JSON bearbeiten")
            }
            .disabled(model.isProcessing)

            if let error = settings.errorMessage {
                Text(error).foregroundStyle(.red).textSelection(.enabled)
            }
            if let notice = settings.notice {
                Text(notice).foregroundStyle(.secondary)
            }
            if model.isProcessing {
                Text("Während der Verarbeitung können die Regeln nicht geändert werden.")
                    .foregroundStyle(.secondary)
            }

            HStack {
                Button("Produktionsregeln wiederherstellen …") { confirmRestore = true }
                Button("Änderungen verwerfen") { confirmDiscard = true }
                    .disabled(!settings.hasUnsavedChanges)
                Spacer()
                Text(settings.hasUnsavedChanges ? "Nicht gespeichert" : "Keine ungespeicherten Änderungen")
                    .font(.caption).foregroundStyle(.secondary)
                Button("Speichern", action: settings.save)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut("s", modifiers: .command)
            }
            .disabled(model.isProcessing)

            Text("Gespeichert pro Benutzer, außerhalb der App. Produktionsdateien bleiben unverändert.")
                .font(.caption).foregroundStyle(.secondary)
            Text(settings.userRulesURL.path)
                .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
        }
        .padding(20)
        .frame(width: 800, height: 700)
        .confirmationDialog("Editor durch die ursprünglichen Produktionsregeln ersetzen?", isPresented: $confirmRestore) {
            Button("Produktionsregeln laden") {
                if !model.isProcessing { settings.restoreProductionDraft() }
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Ungespeicherte Änderungen werden ersetzt. Anschließend zum Übernehmen speichern.")
        }
        .confirmationDialog("Ungespeicherte Änderungen verwerfen?", isPresented: $confirmDiscard) {
            Button("Verwerfen", role: .destructive) {
                if !model.isProcessing { settings.reload() }
            }
            Button("Abbrechen", role: .cancel) {}
        }
    }
}
