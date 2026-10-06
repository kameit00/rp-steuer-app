import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: RuleSettings
    @State private var isDropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("RP Steuer App").font(.largeTitle.bold())
                Spacer()
                SettingsLink { Label("Einstellungen …", systemImage: "gearshape") }
            }
            Text("Dieselbe Produktions-Python-Engine – ohne Änderungen.")
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 12) {
                Picker("Verarbeitung", selection: $model.mode) {
                    ForEach(ConversionMode.allCases) { mode in Text(mode.title).tag(mode) }
                }
                .pickerStyle(.segmented)

                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Eingaben (\(model.inputs.count))").font(.headline)
                            Spacer()
                            Button("CSV-Dateien / Ordner hinzufügen …", action: model.chooseInputs)
                            Button("Leeren", action: model.clearInputs).disabled(model.inputs.isEmpty)
                        }
                        if model.inputs.isEmpty {
                            Text("CSV-Dateien oder Ordner hier ablegen")
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, minHeight: 92)
                        } else {
                            List(model.inputs, id: \.path) { url in
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(url.lastPathComponent)
                                        Text(url.deletingLastPathComponent().path)
                                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                    }
                                    Spacer()
                                    Button { model.removeInput(url) } label: {
                                        Image(systemName: "minus.circle")
                                    }
                                    .buttonStyle(.borderless)
                                    .help("Aus der Liste entfernen (Datei bleibt erhalten)")
                                }
                            }
                            .frame(height: 115)
                        }
                        Text("Nur CSV-Dateien direkt im Ordner, keine Unterordner. Eingabedateien bleiben erhalten.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(4)
                }
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(isDropTargeted && !model.isProcessing ? Color.accentColor : .clear, lineWidth: 2))
                .onDrop(of: [UTType.fileURL.identifier], isTargeted: $isDropTargeted, perform: model.receiveDrop)

                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Ausgabeordner").font(.headline)
                        Text(model.outputDirectory?.path ?? "Bitte einen Ausgabeordner auswählen")
                            .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            .textSelection(.enabled)
                    }
                    Spacer()
                    Button("Auswählen …", action: model.chooseOutput)
                }

                if model.mode == .paypal {
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("PayPal-Regeln").font(.headline)
                            Text(model.rulesFile?.path ?? (settings.hasSavedDefaults ? "Eigene Standardregeln (Einstellungen)" : "Mitgelieferte Produktionsregeln (Standard)"))
                                .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                .textSelection(.enabled)
                        }
                        Spacer()
                        if model.rulesFile != nil {
                            Button("Standard") { model.rulesFile = nil }
                        }
                        Button("rules.json auswählen …", action: model.chooseRules)
                    }
                }
            }
            .disabled(model.isProcessing)

            HStack {
                if model.isProcessing {
                    ProgressView().controlSize(.small)
                }
                Text(model.status).foregroundStyle(.secondary)
                Spacer()
                Button("Verarbeiten", action: model.start)
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.canRun)
                    .keyboardShortcut(.return, modifiers: [.command])
            }

            GroupBox("Protokoll") {
                ScrollView([.vertical, .horizontal]) {
                    Text(model.logText.isEmpty ? "Noch keine Verarbeitung gestartet." : model.logText)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                        .padding(6)
                }
                .frame(minHeight: 95, maxHeight: .infinity)
            }

            if !model.outputs.isEmpty {
                GroupBox("Ausgabedateien") {
                    List(model.outputs, id: \.path) { url in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(url.lastPathComponent)
                                Text(url.path).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                            Spacer()
                            Button("Öffnen") { NSWorkspace.shared.open(url) }
                            Button("Im Finder zeigen") { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                        }
                    }
                    .frame(height: 105)
                }
            }
        }
        .padding(20)
        .frame(minWidth: 760, minHeight: 640)
        .alert("Verarbeitung / Auswahl fehlgeschlagen", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "Unbekannter Fehler")
        }
    }
}
