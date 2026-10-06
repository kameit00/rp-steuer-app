# RP Steuer App — Projektinformationen und Arbeitsregeln

## Zweck und Architektur

Native macOS-App (SwiftUI) für PayPal- und sevDesk-CSV-Dateien. Excel-Ausgaben werden durch die unveränderten Python-Produktionskonverter erzeugt. Ein mit PyInstaller paketierter Python-Prozess inklusive Runtime und Bibliotheken ist Bestandteil der App; beim Anwender sind weder Python noch uv/Homebrew erforderlich.

- Anzeigename / App-Bundle: **RP Steuer App** / `RP Steuer App.app`
- Ordner und GitHub-Repository: `rp-steuer-app`
- Swift-Package, Target und ausführbare Datei: `RPSteuerApp`
- Bundle-ID: `com.relax-pillow.rpsteuerapp`
- Python-Projekt / Engine: `rp-steuer-app-engine`
- Mindestversion: macOS 14; Builds sind architekturspezifisch (arm64 oder x86_64).

## Versionierung und Changelog (verbindlich)

- Die erste dokumentierte Veröffentlichung ist **1.0.0**. Frühere lokale Prototyp-Versionen sind keine Releases.
- `VERSION` ist die einzige Quelle für die App-/Engine-Version; `BUILD_NUMBER` enthält eine positive ganzzahlige Buildnummer.
- Bei jeder nachfolgenden funktionalen Änderung die Version inkrementieren: PATCH für Fehlerbehebungen, MINOR für abwärtskompatible Funktionen, MAJOR für inkompatible Änderungen (SemVer).
- Bei jeder Veröffentlichung `BUILD_NUMBER` ebenfalls erhöhen. Keine Versionsnummer wiederverwenden.
- Vor dem Commit `CHANGELOG.md` mit Versionsnummer, Datum und nachvollziehbaren Änderungen aktualisieren. Neueste Version zuerst. Mehrere Änderungen eines Releases werden gemeinsam dokumentiert.
- Die Version in `python/pyproject.toml` an `VERSION` angleichen und `uv lock --project python` ausführen. Bundle-Metadaten werden im Buildskript aus `VERSION`/`BUILD_NUMBER` generiert. Das Buildskript prüft Übereinstimmung und Changelog-Eintrag.
- Reine Dokumentationskorrekturen müssen die App-Version nicht ändern, sind aber in einem `[Unreleased]`-Abschnitt zu dokumentieren. Keine separate neue Release-Version allein für einen Zwischenstand innerhalb desselben noch unveröffentlichten Releases erzeugen.
- Versionsänderungen, Changelog und dazugehörige Implementierung/Tests immer zusammen committen.

## Projektstruktur

- `Sources/RPSteuerApp/`: SwiftUI-Oberfläche, Einstellungen, Prozess-/NDJSON-Kommunikation.
- `Tests/RPSteuerAppTests/`: Swift-Tests und optionale Tests gegen die paketierte Engine.
- `python/engine.py`: Validierung, temporäre Kopien, Kollisionsschutz; keine Excel-Neuimplementierung.
- `python/production/`: unveränderter Snapshot der Produktionskonverter, Regeln, originaler Lockfile und SHA-256-Manifest.
- `python/tests/`: Regression, Schema-/Fehler-/Sicherheitsfälle, Workbook-Vergleich.
- `build_app.sh`: Build, Tests, Signierung und paketierte Integrationstests.
- `dist/`: generierte App, nicht in Git.

## Datenintegrität

- Produktionskonverter und Standardregeln in `python/production/` **nicht** für GUI-Funktionen ändern. Bewusste Snapshot-Updates benötigen überprüfte Hashes, Regressionsvergleiche und einen Changelog-Eintrag.
- Reihenfolge/Matching der Regeln sowie Gruppierung, Formeln und Excel-Formatierung erhalten.
- Original-CSVs, externe Regeldateien und bestehende Excel-Ausgaben niemals löschen/überschreiben. Zielkollisionen führen zum Abbruch.
- Standardregeln liegen pro Benutzer unter `~/Library/Application Support/com.relax-pillow.rpsteuerapp/rules.json`. App-Bundle und Produktionssnapshot bleiben schreibgeschützt.
- Änderungen in Einstellungen wirken nur nach validiertem Speichern. Eine externe `rules.json` hat Vorrang. Beschädigte gespeicherte Regeln nicht stillschweigend durch andere Kategorien ersetzen.
- Frühere lokale Einstellungen werden einmalig ohne Überschreiben oder Löschen der alten Datei übernommen. Die alte datierte Bundle-ID darf ausschließlich im dokumentierten Migrationscode/Test bestehen bleiben.
- Keine vertraulichen CSVs, generierten Buchhaltungsdateien, Zugangsdaten oder lokale Benutzereinstellungen committen. Testdaten sind synthetisch; Logs können vertrauliche Daten enthalten.

## Prüfen und Bauen

```bash
swift test
(cd python && uv run --locked --group build python -m unittest discover -s tests -v)
./build_app.sh
open "dist/RP Steuer App.app"
```

Der vollständige Build testet auch die paketierte Python-Engine und die Swift-Prozesskommunikation. Für separate Integrationstests `RP_STEUER_APP_TEST_ENGINE` auf den absoluten Engine-Pfad setzen; `RP_STEUER_APP_ENGINE` ist der Entwickler-Override für `swift run`.

Workbook-Vergleiche prüfen die XLSX-ZIP-Inhalte einschließlich Formeln, Styles und Blattstruktur. Nur Container-Metadaten und Erzeugungs-/Änderungstimestamps werden ignoriert. Vor Produktionsrollout echte Ausgaben unter den tatsächlich installierten Produktionsabhängigkeiten vergleichen.

Standardbuilds sind ad-hoc signiert, nicht notarisiert. Developer-ID-Signierung/Notarisierung und das Zielgerät separat prüfen. Git-Commits enthalten Quellcode, Dokumentation und Lockfiles, aber keine `.build/`, `.venv/` oder `dist/`-Artefakte.
