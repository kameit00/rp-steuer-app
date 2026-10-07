# Changelog — RP Steuer App

Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/). `VERSION` und `BUILD_NUMBER` definieren App-/Engine-Version und Buildnummer. Frühere lokale Prototyp-Versionen werden nicht als veröffentlichte Releases geführt.

## [1.2.1] — 2026-10-07

### Hinzugefügt
- Eigenes macOS-App-Icon: helles Kissen, Tabellenblatt und goldenes Häkchen auf petrolfarbenem Hintergrund, passend zu relax-pillow und der Buchhaltungsverarbeitung.
- ICNS mit Standard-/Retina-Auflösungen bis 1024 Pixel für Finder, Dock und App-Umschalter; Einbindung in beide Architektur-Builds über `CFBundleIconFile`.
- PNG-Vorschau und reproduzierbare Vektorzeichnung in `scripts/generate_app_icon.swift`, ohne externe Grafiken, Schriften oder zusätzliche Abhängigkeiten.
- Bundle-/ZIP-Prüfung verlangt das Icon und prüft ICNS-Struktur sowie PNG-Auflösungen; Regressionstests für fehlende und beschädigte Icons.

### Status
- Version **1.2.1**, Build **4**. Keine Änderung der Produktionskonverter, Regeln oder Datenverarbeitung. Lokale Standardbuilds bleiben ad-hoc signiert und nicht notarisiert; Release-Downloads werden erst nach erfolgreichen nativen ARM-/Intel-Builds und bestätigter Notarisierung veröffentlicht.

## [1.2.0] — 2026-10-07

### Hinzugefügt
- Interaktive lokale Einrichtung von sechs GitHub-Actions-Secrets: verschlüsselte P12-Identität, Export-Passwort, Signieridentität und Apple-Notarisierungszugang. Verdeckte Passworteingabe und Übertragung ausschließlich über stdin; kein automatischer Schlüssel-/Passwortexport aus dem Schlüsselbund.
- CI-Modi `adhoc`, `developer-id` und `notarized` für beide Architekturen; Versionstags verlangen Notarisierung und fallen bei fehlenden Secrets nicht auf ad-hoc zurück.
- Temporärer CI-Schlüsselbund mit begrenztem Codesign-Zugriff, Credential-Validierung und Cleanup auch bei Fehlern; keine Änderung des lokalen Login-Schlüsselbunds. Eine eng begrenzte Apple-CLI-Argument-Ausnahme in isolierten CI-Runnern erfordert explizite Benutzerbestätigung und `CI_SECRET_ARGV_APPROVED=true`.
- Notarisierungsskript mit dauerhaftem Submission-Ledger, Wiederaufnahme derselben ID, unveränderter Upload-Kopie, Stapling, Gatekeeper-/Signaturprüfung und neuer ZIP-Prüfsumme erst nach `Accepted`.
- Gesonderte versionierte Wiederaufnahme-Artefakte bei noch laufender/fehlgeschlagener Notarisierung; solche ZIPs werden nicht als notarisiert veröffentlicht. Serialisierte Workflows sowie Guards für CI-Reruns und bekannte gleichversionige Pending-Artefakte verhindern blinde erneute Einreichungen.
- Tests für Secret-Übertragung ohne Ausgabe/argv-Leaks, Validierung, sichere Eingabe und Notarisierungs-/Fehler-/Wiederaufnahmelogik.

### Behoben
- P12-Prüfung verwendet auf macOS das kompatible `/usr/bin/openssl` statt Homebrew-OpenSSL 3: ältere macOS-Schlüsselbund-Exporte mit RC2/3DES werden auch bei korrektem Passwort nicht mehr fälschlich abgewiesen. Ohne Apple-Binary wird bei nicht unterstützten Verfahren ein eng begrenzter `-legacy`-Leseversuch verwendet; Passwort-/MAC-Prüfung bleibt aktiv.
- Regressionstests einschließlich einer synthetisch erzeugten RC2/3DES-P12 und Ablehnung falscher Passwörter; keine realen Benutzer-Schlüssel für Tests.

### Sicherheit und Status
- Private Schlüssel, P12-Dateien und Notarisierungsdaten bleiben aus Git ausgeschlossen. Repository-Secrets müssen vom Benutzer im lokalen Terminal vervollständigt werden; der private Schlüssel wird nicht ohne Zustimmung exportiert.
- Version **1.2.0**, Build **3**. Implementierte Notarisierungsunterstützung bedeutet noch keine Apple-Freigabe: bestehende manuelle Einreichungen von **1.1.0** sind separat und dürfen erst nach bestätigter Freigabe als notarisiert bezeichnet werden.

## [1.1.0] — 2026-10-06

### Hinzugefügt
- Zwei unabhängige native Builds: **Apple Silicon (arm64)** und **Intel (x86_64)**, jeweils mit passender Swift-App, Python-Runtime und nativen Bibliotheken.
- GitHub-Actions-Buildmatrix auf nativen ARM- und Intel-macOS-Runnern, ausführbar für beide oder eine einzelne Architektur; Builds bei Versionstags.
- Getrennte Ausgabeordner `dist/arm64/` und `dist/x86_64/` sowie versionierte ZIP-Downloads inklusive SHA-256-Prüfsummen.
- Prüfung aller eingebetteten Mach-O-Dateien, Bundle-Metadaten, Architektur und Bibliotheksversionen; erneute Verifikation nach Entpacken des Download-ZIPs.

### Geändert
- `build_app.sh --arch arm64|x86_64` prüft die native Build-Architektur frühzeitig und verwendet getrennte Python-/Swift-/PyInstaller-Buildumgebungen.
- `dist/RP Steuer App.app` ist ein Komfortlink auf den zuletzt lokal gebauten nativen Build.
- Engine-Diagnose meldet zusätzlich die tatsächlich laufende Architektur.
- Version **1.1.0**, Build **2**. macOS **14+** bleibt erforderlich; ZIPs sind ad-hoc signiert, nicht notarisiert. Es handelt sich um zwei Apps, nicht um ein Universal Binary.

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
