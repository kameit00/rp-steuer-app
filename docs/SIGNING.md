# Developer-ID-Signierung, GitHub Secrets und Notarisierung

## Status und Voraussetzungen

Signieren, bei Apple einreichen und von Apple akzeptiert werden sind **verschiedene Schritte**. Erst nach `Accepted`, erfolgreichem Stapling und Gatekeeper-Prüfung darf eine ZIP als notarisiert veröffentlicht werden. Ein Timeout bedeutet weder Ablehnung noch Freigabe.

Benötigt werden ein kostenpflichtiges Apple-Developer-Team, eine gültige **Developer ID Application**-Identität mit privatem Schlüssel sowie ein Apple-ID-Notarisierungszugang mit anwendungsspezifischem Passwort. Die Team-ID lässt sich aus `security find-identity -v -p codesigning` für die Developer-ID-Identität ablesen. „Apple Development“ reicht für externe Distribution nicht.

## Einmalig GitHub Secrets einrichten

### 1. Genau die ausgewählte Identität als P12 exportieren

1. **Schlüsselbundverwaltung** öffnen (Spotlight), **Anmeldung → Meine Zertifikate**.
2. **Developer ID Application: …** auswählen. Beim Aufklappen muss ein zugehöriger privater Schlüssel vorhanden sein.
3. Über **Exportieren…** die Identität inklusive privatem Schlüssel als **`.p12`** exportieren. Nicht den ganzen Schlüsselbund exportieren.
4. Beispielsweise `~/Desktop/RP-Steuer-App-Developer-ID.p12` verwenden — **außerhalb des Projektordners**.
5. Ein starkes, nicht leeres Export-Passwort vergeben. Datei und Passwort niemals im Chat oder Repository teilen.

Der Assistent exportiert keine Schlüssel und liest keine gespeicherten Schlüsselbund-Passwörter automatisch aus. Das Exportieren und die Übertragung erfolgen erst durch die explizite Benutzeraktion.

### 2. Anwendungsspezifisches Apple-Passwort

Unter [account.apple.com](https://account.apple.com/) → **Anmeldung und Sicherheit → Anwendungsspezifische Passwörter** ein Passwort mit dem Namen „RP Steuer App GitHub“ erzeugen. Alternativ ein vorhandenes gültiges anwendungsspezifisches Passwort verwenden. **Nicht das normale Apple-ID-Passwort** eingeben.

Das lokale Notary-Schlüsselbundprofil wird nicht zu GitHub kopiert. Die CI legt aus den Secrets einen eigenen temporären Zugang an.

### 3. Einrichtungshilfe im eigenen Terminal starten

```bash
cd /Users/kaimechel/Development/relax-pillow/rp-steuer-app
python3 scripts/setup_github_secrets.py
```

Die Hilfe fragt nach P12-Pfad, verdecktem Export-Passwort, Signieridentität, Team-ID, Apple-ID und verdecktem anwendungsspezifischem Passwort. Bei genau einer lokalen Developer-ID-Application-Identität wird diese vorgeschlagen. Vor der Übertragung werden eine ausdrückliche CI-Sicherheitsfreigabe (**`CI-FREIGABE`**) und der vollständige Repository-Name **`kameit00/rp-steuer-app`** verlangt.

Pfad als normalen Text eingeben, ohne zusätzliche Anführungszeichen oder Shell-Escapes. Die Hilfe verweigert nicht-interaktive Eingaben, Dateien im Projektordner, übergroße P12-Dateien und öffentliche Zielrepositories. Werte werden nicht in Prozessargumenten, Shell-History oder Logausgaben übergeben: `gh secret set` erhält sie über stdin und verschlüsselt sie lokal mit dem Repository-Schlüssel.

Sechs Repository-Secrets für **GitHub Actions**:

| Name | Inhalt |
|---|---|
| `DEVELOPER_ID_P12_BASE64` | Base64 der passwortgeschützten P12-Identität einschließlich privatem Schlüssel |
| `DEVELOPER_ID_P12_PASSWORD` | P12-Export-Passwort |
| `SIGNING_IDENTITY` | Vollständiger Name „Developer ID Application: … (TEAMID)“ |
| `APPLE_TEAM_ID` | Zehnstellige Developer-Team-ID |
| `APPLE_ID` | E-Mail-Adresse des Developer-Accounts |
| `APPLE_APP_SPECIFIC_PASSWORD` | Anwendungsspezifisches Apple-Passwort |

Bereits vorhandene gleichnamige Secrets werden ersetzt. Bei einem Fehler können einzelne Secrets bereits gesetzt sein; Einrichtung erneut ausführen. Abschluss erst melden, wenn **alle sechs** vorhanden sind:

```bash
gh secret list --repo kameit00/rp-steuer-app
```

Zusätzlich setzt die Hilfe die nicht geheime Repository-Variable **`CI_SECRET_ARGV_APPROVED=true`** erst nach vollständiger Secret-Übertragung und expliziter Zustimmung. Während einer Secret-Rotation wird sie auf `false` gesetzt. Ohne diese Freigabe wird kein privater Schlüssel in CI importiert. Prüfen mit `gh variable get CI_SECRET_ARGV_APPROVED --repo kameit00/rp-steuer-app`.

Diese Secret-Liste zeigt **nur Namen und Aktualisierungszeit**, keine Werte. GitHub Secret-Werte lassen sich nachträglich nicht auslesen. Die geschützte P12 danach sicher außerhalb des Projekts aufbewahren oder bewusst entfernen. Bei möglichem Schlüsselverlust/-abfluss Zertifikat widerrufen, neu erzeugen und Secrets ersetzen. Für Secrets sollten nur vertrauenswürdige Repository-Mitwirkende Zugriff auf Workflow-Änderungen erhalten.

## CI-Verarbeitung

**GitHub Actions → Build macOS apps → Run workflow**:

- `architecture`: `both`, `arm64` oder `x86_64`.
- `distribution: adhoc`: Tests/lokale Builds ohne Developer-ID-Secrets, **nicht notarisiert**.
- `distribution: developer-id`: Developer-ID-Signierung und native Regressionstests, **ohne Apple-Einreichung**. Erster empfohlener CI-Test nach Secret-Einrichtung.
- `distribution: notarized`: Signierung, Tests, Apple-Einreichung, Stapling, Gatekeeper-Prüfung, abschließende ZIP/Prüfsumme.

Versionstags `v*` verlangen **notarized**, fehlende Secrets führen zum Fehler — niemals zu einem stillen ad-hoc Fallback. Das Einrichten der Secrets startet selbst keinen Build und keine neue Apple-Einreichung.

**Eng begrenzte, zustimmungspflichtige CI-Ausnahme:** Apples `security`-/`notarytool`-CLI benötigt bei automatisiertem Schlüsselbund-Import teilweise Passwörter als Prozessargumente. Nur auf isolierten, kurzlebigen GitHub-Runnern mit vertrauenswürdigem Code wird das nach der ausdrücklich bestätigten `CI_SECRET_ARGV_APPROVED`-Freigabe erlaubt. Andere Prozesse desselben Runners könnten diese Argumente theoretisch lesen. Tracing ist abgeschaltet, Ausgaben werden unterdrückt/maskiert; Secrets werden nicht in Artefakte geschrieben. Diese Ausnahme gilt **nicht** für die lokale Einrichtungshilfe, deren private Werte weiterhin ausschließlich über stdin übertragen werden. Keine Fremd-PRs mit Signier-Secrets ausführen.

Jeder Architektur-Runner importiert die P12 in einen **eigenen temporären Schlüsselbund** unter `RUNNER_TEMP`. Codesign-Zugriff wird nur für diesen Schlüsselbund erteilt; die P12 wird nach dem Import entfernt. Notary-Zugang liegt ebenfalls nur darin. Cleanup löscht den Schlüsselbund auch nach Build-/Notary-Fehlern. Keine Zertifikate, privaten Schlüssel, Passwörter oder Schlüsselbünde werden als Artefakte hochgeladen.

Das Notarisierungsskript wartet standardmäßig höchstens 15 Minuten. Apple kann länger brauchen. Dann scheitert der Job bewusst; es erscheint **kein vermeintlich notarisierter Download**. Ein gesondertes `pending-notarization-<Version>-<Architektur>`-Artefakt enthält den exakt eingereichten **noch nicht freigegebenen** Upload und JSON-Status/Submission-ID, nicht Zugangsdaten. Die Einreichung kann lokal unter derselben ID fortgesetzt werden, statt mehrfach einzureichen. Artefakte laufen nach sieben Tagen ab. Workflows werden serialisiert, „Re-run failed jobs“ im notarisierten Modus wird vor dem Import verweigert, und ein vorhandenes gleichversioniges Pending-Artefakt blockiert neue notarisierten Aufträge. Vor einem weiteren Versuch unter derselben Version manuell mit Apple-History/Ledger abgleichen; nicht blind neu starten oder Pending-Artefakte löschen, um die Sperre zu umgehen.

## Lokale Signierung und Notarisierung

```bash
SIGNING_IDENTITY="Developer ID Application: Dein Name (TEAMID)" ./build_app.sh --arch arm64

# Interaktive Einrichtung; Passwort ausschließlich verdeckt eingeben
xcrun notarytool store-credentials "rp-steuer-app"

NOTARY_KEYCHAIN_PROFILE=rp-steuer-app ./notarize_app.sh --arch arm64
```

Intel entsprechend auf dem Intel-Runner oder Intel-Mac bauen/testen. `notarize_app.sh` führt keine eingebetteten Programme aus; es prüft statisch Signaturen/Architekturen und Gatekeeper, während native Funktions-/Regressionstests bereits im Build stattfinden.

Das Skript:

1. Prüft Version/Build, Developer-ID-Signaturen, Hardened Runtime, Timestamps und Architektur sämtlicher Mach-O-Dateien.
2. Friert exakt die vorhandene Release-ZIP als `dist/notarization/<Architektur>/upload.zip` ein und speichert vor der Netzwerkanfrage ein Ledger.
3. Erfasst die Submission-ID, wartet und prüft denselben Auftrag erneut. Bei `Invalid` wird Apples Prüfprotokoll gespeichert.
4. Stapelt ausschließlich die eingefrorene App nach bestätigtem `Accepted`, validiert Signatur/Ticket und führt `spctl` aus.
5. Erzeugt ZIP und Prüfsumme aus der gestapelten App neu und prüft auch das erneut entpackte Ergebnis vor dem Austausch der generierten Release-Ausgaben.

Bei einer noch laufenden Einreichung:

```bash
NOTARY_KEYCHAIN_PROFILE=rp-steuer-app ./notarize_app.sh --arch arm64 --resume
```

**Nicht neu signieren/bauen oder Upload/JSON verändern**, solange ein Auftrag wiederaufgenommen werden soll. Das Ledger verweigert eine andere Version, Architektur oder geänderte ZIP/App. Unklare Netzwerkausgänge ohne aufgezeichnete ID müssen über Apple-History geklärt werden; das Skript reicht nicht blind erneut ein.

### Wiederaufnahme eines CI-Artefakts

Das `pending-notarization-<Version>-<Architektur>`-Artefakt herunterladen, auf dem Mac in `dist/notarization/<Architektur>/` ablegen und den exakt gleichen Quellstand mit passender `VERSION`/`BUILD_NUMBER` verwenden. Aus `upload.zip` die ursprüngliche Release-ZIP und App wiederherstellen, **ohne erneut zu signieren**:

```bash
# Beispiel ARM; Versionsnummer durch die tatsächliche Ledger-Version ersetzen
cp dist/notarization/arm64/upload.zip dist/RP-Steuer-App-VERSION-arm64.zip
mkdir -p dist/arm64
ditto -x -k dist/notarization/arm64/upload.zip dist/arm64
NOTARY_KEYCHAIN_PROFILE=rp-steuer-app ./notarize_app.sh --arch arm64 --resume
```

Die alten manuellen 1.1.0-Aufträge bleiben separat unter `.build/notary-prep/`/`.build/notary-submissions.json` erhalten. Sie werden durch Secret-Einrichtung oder einen neuen Build weder erneut eingereicht noch automatisch als freigegeben behandelt.

## Veröffentlichungsregeln

- Ein signierter Build ist nicht automatisch notarisiert.
- Beide nativen Architekturen und endgültige ZIPs prüfen, dann erst GitHub-Release-Assets veröffentlichen.
- Keine Credentials in Logfiles, `.env`, Prozessausgaben, AGENTS/README oder Commits speichern. Die ausdrücklich freigegebene temporäre CI-CLI-Argument-Ausnahme ist kein allgemeiner Freibrief für argv-/Logging-Leaks. Private Dateiformate sind vorsorglich Git-ignored.
- Die Pipeline-Unterstützung kann vor Apples Freigabe committed werden; einen Release als notarisiert erst nach real bestätigtem Erfolg bezeichnen.
