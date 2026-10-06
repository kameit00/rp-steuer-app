# Changelog — RP Steuer App

Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/). `VERSION` und `BUILD_NUMBER` definieren App-/Engine-Version und Buildnummer. Frühere lokale Prototyp-Versionen werden nicht als veröffentlichte Releases geführt.

## [1.0.0] — 2026-10-06

### Hinzugefügt
- Native macOS-Oberfläche in SwiftUI für PayPal- und sevDesk-CSV-Konvertierung mit Datei-/Ordnerauswahl und Drag-and-drop.
- Eigenständige Python-Engine inklusive Interpreter und Excel-Bibliotheken im App-Bundle; keine zusätzliche Installation beim Anwender erforderlich.
- Unveränderter Snapshot der Python-Produktionskonverter mit Hash-Manifest und originalem Dependency-Lockfile.
- Einstellungen (⌘,) zum Bearbeiten, Validieren und Speichern persönlicher Standardregeln als JSON; Verwerfen und Wiederherstellen der Produktionsregeln.
- Vorrang einer ausgewählten externen `rules.json`; gespeicherte Einstellungen bleiben über App-Neustarts und Updates erhalten.
- Fortschritts-/Protokollanzeige sowie Öffnen und Anzeigen der Ausgabedateien im Finder.
- Regressions- und Integrationstests für Workbook-Inhalte, Formeln, Formatierung, Fehlerfälle, Unicode-Pfade, Einstellungen und paketierte Prozesskommunikation.
- Buildskript mit privater, gesperrter Python-Umgebung, ad-hoc Signierung und vollständigen Tests; optionale Developer-ID-Signierung.
- Projektanleitung und `AGENTS.md` mit verpflichtender Versionserhöhung und Changelog-Pflege für zukünftige Änderungen.

### Vereinheitlicht
- Dauerhafter Name **RP Steuer App**; Ordner/Repository `rp-steuer-app`, Swift-Target `RPSteuerApp`, Python-Engine `rp-steuer-app-engine`.
- Undatierte Bundle-ID `com.relax-pillow.rpsteuerapp`; bestehende persönliche Regeln des lokalen Prototyps werden einmalig ohne Löschen/Überschreiben migriert.
- Gemeinsamer Versionsstart **1.0.0**, Build **1**, mit Metadatenprüfung beim Build.

### Datensicherheit und Kompatibilität
- Originaldateien bleiben unverändert; existierende oder kollidierende Excel-Ausgaben führen zum Abbruch statt zum Überschreiben.
- Verarbeitung auf temporären Kopien; Ergebnisse erst nach erfolgreicher Verarbeitung aller gewählten Eingaben publizieren.
- Beschädigte oder nicht zugängliche gespeicherte Regeln melden einen Fehler, statt unbemerkt andere Kategorien zu verwenden; auch defekte Symlinks werden erkannt.
- In den paketierten Produktionssnapshot gelangen ausschließlich hashgeprüfte Manifestdateien, keine lokal hinzugefügten Buchhaltungsdateien.
- Versteckte Finder-Sidecars werden ausgeschlossen; echte versteckte CSV-Dateien können explizit verarbeitet werden.
- macOS **14+**, architekturspezifische Builds. Aktueller lokaler Build: Apple Silicon (arm64), ad-hoc signiert und nicht notarisiert.
