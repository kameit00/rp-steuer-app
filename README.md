# RP Steuer App

Native macOS-App für PayPal- und sevDesk-CSV-Dateien. Die SwiftUI-Oberfläche verwendet die **unveränderten Python-Produktionskonverter**, keine Swift-Neuimplementierung der Excel-Logik.

Version: siehe [`VERSION`](VERSION). Änderungen: [`CHANGELOG.md`](CHANGELOG.md). Projekt-/Agentenregeln: [`AGENTS.md`](AGENTS.md).

## Bauen und öffnen

Voraussetzungen zum Bauen: macOS, Xcode Command Line Tools (`xcode-select --install`) und [uv](https://docs.astral.sh/uv/). Beim ersten Build wird eine Internetverbindung benötigt. Anwender benötigen **weder Python, uv, Homebrew noch Terminal**.

```bash
cd rp-steuer-app
./build_app.sh
open "dist/RP Steuer App.app"
```

Das Buildskript erstellt SwiftUI-Executable und private Python-Engine inklusive Runtime, nativer Bibliotheken und Excel-Abhängigkeiten. Es prüft Versionskonsistenz und CPU-Architektur aller eingebetteten Mach-O-Dateien, signiert die App und führt Regressionstests gegen die paketierte Engine aus. `VERSION` und `BUILD_NUMBER` werden in die Bundle-Metadaten übernommen.

- **macOS 14+**, weil das paketierte NumPy-Wheel Sonoma voraussetzt.
- **Zwei eigenständige Varianten**, kein Universal Binary: **arm64** für Apple Silicon und **x86_64** für Intel. Jede Variante enthält die passende Python-Runtime und native Bibliotheken; Swift- und Python-Architektur werden im Build geprüft.
- Standardmäßig **ad-hoc signiert, nicht notarisiert**. Gatekeeper kann übertragene Builds blockieren.
- Keine App Sandbox; Verarbeitung benötigt Zugriff auf ausgewählte Eingaben und Ausgabeordner.

### Downloads für Apple Silicon und Intel

Für jede Version gibt es zwei ZIPs:

- `RP-Steuer-App-<Version>-arm64.zip` — Apple Silicon (M1, M2, M3 usw.).
- `RP-Steuer-App-<Version>-x86_64.zip` — Intel-Macs.

Beide enthalten `RP Steuer App.app`. Die passende Variante entpacken und nach Programme kopieren. Beide benötigen macOS 14+. Daneben liegt jeweils eine `.zip.sha256`-Datei zur Integritätsprüfung (`shasum -a 256 -c <Datei>.zip.sha256`). Nicht beide Varianten unter gleichem Namen in denselben Programme-Ordner kopieren.

Native Builds:

```bash
./build_app.sh --arch arm64    # auf Apple Silicon
./build_app.sh --arch x86_64   # auf Intel
```

Ergebnisse liegen getrennt in `dist/arm64/RP Steuer App.app` und `dist/x86_64/RP Steuer App.app`; ZIPs/Prüfsummen liegen in `dist/`. Der Komfortlink `dist/RP Steuer App.app` zeigt auf den zuletzt lokal gebauten nativen Build. Ein falsches `--arch` bricht vor der Installation von Abhängigkeiten ab, statt eine gemischte App zu erzeugen. Buildumgebungen und Caches liegen getrennt unter `.build/native/<Architektur>/`; die Entwicklungsumgebung `python/.venv` bleibt unberührt.

**GitHub Actions → Build macOS apps → Run workflow** baut beide oder eine ausgewählte Variante auf passenden nativen macOS-Runnern (`macos-15` für ARM, `macos-15-intel` für Intel). Versionstags `v*` starten automatisch beide Builds. Die Jobs testen die paketierte Engine und Swift-Kommunikation nativ, prüfen alle Mach-O-Dateien und verifizieren die signierte App nach ZIP-Entpacken. ZIP und Prüfsumme werden als getrennte Architektur-Artefakte für 30 Tage bereitgestellt; veröffentlichte Release-Assets bleiben dauerhaft verfügbar. In privaten Repositories verbrauchen die Jobs GitHub-Actions-Kontingent.

Developer-ID-Signierung ist optional:

```bash
SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./build_app.sh
# Danach die App als ZIP mit xcrun notarytool notarieren und die .app stapeln.
```

Developer-ID-Signierung und Notarisierung sind nicht durch den lokalen ad-hoc Build zertifiziert. Vor Rollout die Zielarchitektur und älteste unterstützte macOS-Version prüfen.

## Verwendung

1. **PayPal** oder **sevDesk** auswählen.
2. CSV-Dateien hinzufügen oder Dateien/Ordner per Drag-and-drop ablegen. Ordner liefern nur sichtbare direkte CSV-Dateien, keine Unterordner oder Finder-Sidecars. Echte versteckte CSVs können explizit ausgewählt werden.
3. Einen Ausgabeordner auswählen, möglichst einen leeren Ordner für diesen Lauf.
4. PayPal verwendet zunächst die Produktionsregeln. Eigene Standardregeln können in **Einstellungen…** bearbeitet werden. Eine im Hauptfenster ausgewählte externe `rules.json` hat Vorrang.
5. **Verarbeiten** klicken. Protokoll prüfen und Ergebnisse öffnen oder im Finder anzeigen.

Original-CSVs und externe Regeln werden niemals geändert oder gelöscht. Die Verarbeitung erfolgt lokal, ohne Server oder Netzwerkdienst. Produktions-Debugmeldungen können Buchhaltungsdaten enthalten; das Protokoll ist vertraulich zu behandeln.

## Einstellungen und Standardregeln

**RP Steuer App → Einstellungen / Settings…** (⌘,) oder den Zahnrad-Button verwenden. Im JSON-Editor `rules` und `always_show_in_summary` bearbeiten.

- `column`: CSV-Spalte, z. B. `Beschreibung` oder `Name`.
- `substring`: gesuchter Text. Groß-/Kleinschreibung und Leerzeichen sind relevant; eine leere Zeichenfolge trifft jeden Wert der angegebenen Spalte.
- `info_column_value`: zugewiesene Kategorie.
- Regeln werden in Reihenfolge geprüft; **der erste Treffer gewinnt**.
- `always_show_in_summary`: Kategorien, die auch ohne Buchungen in der Zusammenfassung erscheinen.
- Das frühere Listenformat und leere Regellisten werden ebenfalls unterstützt.

**Speichern** validiert JSON und Schema. Nur gespeicherte Änderungen wirken auf die nächste Verarbeitung. **Änderungen verwerfen** lädt die gespeicherte Version; **Produktionsregeln wiederherstellen…** lädt den Originalsnapshot in den Editor und erfordert anschließend Speichern. Während einer Verarbeitung sind Änderungen gesperrt.

Persönliche Regeln werden außerhalb des signierten App-Bundles gespeichert:

```
~/Library/Application Support/com.relax-pillow.rpsteuerapp/rules.json
```

Sie bleiben über Neustarts und App-Updates erhalten. Die bisherige lokale Prototypdatei wird beim ersten Start einmalig übernommen, falls noch keine neue Regeldatei vorhanden ist. Die alte Datei wird nicht gelöscht; bereits vorhandene neue Regeln werden nicht überschrieben. Eine fehlgeschlagene Migration oder beschädigte Regeln führen zu einer sichtbaren Fehlermeldung, nicht zu einer stillen Änderung der Kategorien.

Eine externe `rules.json` bleibt unverändert und hat Vorrang. **Standard** im Hauptfenster aktiviert wieder die eigenen Standardregeln. Produktionsordner und App-Bundle werden nicht bearbeitet.

## Datensicherheit und bewusste Unterschiede zum CLI

- Verarbeitung auf temporären Kopien. Veröffentlichung erst, wenn alle gewählten Eingaben erfolgreich sind.
- Bereits vorhandene Excel-Dateien werden nicht überschrieben.
- Erzeugen mehrere CSVs denselben Workbook-Namen, scheitert der gesamte Lauf ohne veröffentlichte Ergebnisse. Diese Dateien einzeln in getrennte Ordner verarbeiten. Das alte PayPal-CLI konnte Monatsausgaben ersetzen, das Rechnungstool existierende Dateien überspringen.
- Originaldateien bleiben erhalten, auch Rechnungs-CSVs, die das alte CLI nach der Verarbeitung löschen konnte.
- Gedruckte/verschluckte Produktionsfehler werden als fehlgeschlagener Auftrag gemeldet.
- Bestehende Produktionslogik bleibt ansonsten erhalten: Kategorien, Formeln, Styles, Datumsbehandlung, Blattnamen, Spaltenbreiten und Gruppierung. Insbesondere wird eine sevDesk-CSV mit mehreren Monaten **nicht** aufgeteilt; die Benennung verwendet weiterhin den häufigsten Rechnungsmonat.

Temporäre Verzeichnisse werden nach normalen Erfolgen/Fehlern entfernt. Nach Absturz/erzwungenem Beenden können temporäre Dateien zurückbleiben. Die Veröffentlichung nutzt exklusive Dateierstellung mit Rollback bei normalen Fehlern, ist aber keine dateisystemweite Transaktion bei Stromausfall. Beenden/Fensterschließen wird während der Verarbeitung verhindert; es gibt keinen Abbrechen-Button.

## Excel-Kompatibilität und Abhängigkeiten

`python/production/` enthält bytegenau kopierte Produktionsquellen und Regeln. `SHA256SUMS.json` prüft die Dateien; `production-uv.lock` archiviert den ursprünglichen Dependency-Stand. Namen/Metadaten dieses historischen Snapshots werden bewusst nicht geändert.

Private Runtime: **Python 3.13.7**, **Pandas 2.3.2**, **NumPy 2.3.3**, **OpenPyXL 3.1.5**. Diese Datenbibliotheken entsprechen der Auflösung des Produktions-Lockfiles für Python 3.11+. Transitive Datenabhängigkeiten sind ebenfalls auf den Snapshot festgelegt. **XlsxWriter 3.2.9** ergänzt die in der Produktionskonfiguration fehlende, vom Rechnungskonverter benötigte Bibliothek.

Die tatsächlichen installierten Versionen auf dem Produktions-Mac sind nicht unabhängig geprüft. Vor Produktionswechsel reale CSVs und **tatsächliche Produktions-Excel-Dateien** vergleichen.

Regressionstests vergleichen XLSX-ZIP-Inhalte einschließlich Zellen, Formeln, Formatierung, Blättern, Spalten und Metadaten. Nur ZIP-Container-Metadaten sowie Erzeugungs-/Änderungstimestamps werden ignoriert. Binäridentische Dateien sind daher nicht erforderlich. Excel berechnet die unveränderten Formeln beim Öffnen neu, wie zuvor.

```bash
# Python-Regressionen
(cd python && uv run --locked --group build python -m unittest discover -s tests -v)

# Swift-Tests
swift test

# Tests inklusive paketierter Engine (auch im vollständigen Build)
ENGINE="$PWD/dist/RP Steuer App.app/Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine"
(cd python && RP_STEUER_APP_TEST_ENGINE="$ENGINE" uv run --locked --group build python -m unittest discover -s tests -v)
RP_STEUER_APP_TEST_ENGINE="$ENGINE" swift test

# Reale Workbooks vergleichen
(cd python && uv run --locked python compare_workbooks.py /pfad/produktion.xlsx /pfad/app.xlsx)
```

## Entwicklung und Versionierung

```
rp-steuer-app/
├── VERSION / BUILD_NUMBER       # verbindliche Release-Metadaten
├── CHANGELOG.md / AGENTS.md
├── Package.swift
├── Sources/RPSteuerApp/         # SwiftUI, Einstellungen, Prozesskommunikation
├── Tests/RPSteuerAppTests/
├── python/
│   ├── engine.py                # Transport/Validierung, keine Excel-Neuimplementierung
│   ├── check_version.py
│   ├── production/              # unveränderter Produktionssnapshot
│   ├── pyproject.toml / uv.lock  # private gesperrte Abhängigkeiten
│   ├── compare_workbooks.py
│   └── tests/
├── build_app.sh
├── .github/workflows/build-macos.yml  # native ARM-/Intel-Builds
└── dist/{arm64,x86_64}/RP Steuer App.app  # generiert, nicht in Git
```

Swift startet `engine/rp-steuer-app-engine/rp-steuer-app-engine --request <private JSON-Datei>` ohne Shell. Logs/Ergebnisse werden als NDJSON übertragen; stdout/stderr werden unabhängig außerhalb des UI-Threads gelesen. Es gibt keinen System-Python-Fallback.

Für `swift run` nach einem Build:

```bash
RP_STEUER_APP_ENGINE="$PWD/dist/RP Steuer App.app/Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine" swift run
```

Der Override benötigt einen absoluten Pfad. Die erste dokumentierte Veröffentlichung ist **1.0.0**. Bei weiteren funktionalen Änderungen SemVer und Buildnummer erhöhen, den Changelog pflegen und die Engine-Version in `python/pyproject.toml` synchronisieren:

```bash
uv lock --project python
uv run --project python --locked python python/check_version.py
```

Version, Änderungen, Tests und Changelog gemeinsam committen; Details stehen in `AGENTS.md`. Produktionskonverter nicht für GUI-Funktionen ändern. Generierte Apps, Umgebungen und vertrauliche Daten gehören nicht ins Repository.
