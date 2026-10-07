#!/usr/bin/env python3
"""Interactive, local-only setup. Never exports keys or reads Keychain passwords."""
import argparse
import base64
import getpass
import json
from pathlib import Path
import re
import subprocess
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = (
    "DEVELOPER_ID_P12_BASE64", "DEVELOPER_ID_P12_PASSWORD", "SIGNING_IDENTITY",
    "APPLE_TEAM_ID", "APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD",
)


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, cwd=ROOT, **kwargs)


def repository_info(repository):
    result = run(["gh", "repo", "view", repository, "--json", "nameWithOwner,isPrivate"], text=True)
    if result.returncode:
        raise ValueError("GitHub-Repository nicht erreichbar. Bitte gh auth status prüfen.")
    info = json.loads(result.stdout)
    if not info.get("isPrivate"):
        raise ValueError("Diese Einrichtung ist für ein privates Repository vorgesehen.")
    if info.get("nameWithOwner", "").casefold() != repository.casefold():
        raise ValueError("GitHub hat ein unerwartetes Repository zurückgegeben.")
    return info["nameWithOwner"]


def default_identity():
    result = run(["security", "find-identity", "-v", "-p", "codesigning"], text=True)
    matches = re.findall(r'"(Developer ID Application: [^"\n]+)"', result.stdout)
    return matches[0] if result.returncode == 0 and len(matches) == 1 else ""


def validate_identity(identity, team):
    if not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise ValueError("Team-ID muss aus zehn Großbuchstaben/Ziffern bestehen.")
    if not identity.startswith("Developer ID Application: ") or not identity.endswith(f"({team})") or "\n" in identity:
        raise ValueError("Developer-ID-Application-Identität und Team-ID passen nicht zusammen.")


def read_p12(path, root=ROOT):
    path = Path(path).expanduser().resolve()
    if path.is_relative_to(root.resolve()):
        raise ValueError("P12-Datei bitte außerhalb des Projektordners exportieren und aufbewahren.")
    if path.suffix.lower() not in (".p12", ".pfx") or not path.is_file():
        raise ValueError("Bitte eine exportierte .p12/.pfx-Datei auswählen.")
    if not 0 < path.stat().st_size <= 32 * 1024:
        raise ValueError("P12 muss kleiner als 32 KiB sein. Nur die ausgewählte Identität exportieren, nicht den ganzen Schlüsselbund.")
    return path, path.read_bytes()


def validate_p12(path, password):
    if not password or "\n" in password or "\r" in password:
        raise ValueError("Die P12-Datei benötigt ein nicht leeres Export-Passwort.")
    result = run(["openssl", "pkcs12", "-in", str(path), "-noout", "-passin", "stdin"],
                 input=(password + "\n").encode())
    if result.returncode:
        raise ValueError("P12 konnte nicht geöffnet werden. Datei, Export-Passwort und OpenSSL-Kompatibilität prüfen.")


def set_secret(repository, name, value):
    # Pipe the value; do not expose it in argv, shell history, environment or logs.
    if name not in SECRET_NAMES or not value:
        raise ValueError("Ungültiges oder leeres Secret.")
    result = run(["gh", "secret", "set", name, "--repo", repository, "--app", "actions"],
                 input=value.encode("utf-8"))
    if result.returncode:
        raise ValueError(f"Secret {name} konnte nicht gesetzt werden. Bereits gesetzte Secrets bleiben erhalten; Einrichtung erneut ausführen.")
    print(f"Gesetzt: {name}")


def secret_prompt(label):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(label)
        except getpass.GetPassWarning as error:
            raise ValueError("Keine sichere verdeckte Passworteingabe möglich. Bitte ein normales Terminal verwenden.") from error


def set_ci_approval(repository, approved):
    result = run(["gh", "variable", "set", "CI_SECRET_ARGV_APPROVED", "--repo", repository,
                  "--body", "true" if approved else "false"])
    if result.returncode:
        raise ValueError("CI-Freigabevariable konnte nicht gesetzt werden. Keine Signierung in CI freigeben, bevor die Einrichtung vollständig ist.")


def prompt(label, default=""):
    suffix = f" [{default}]" if default else ""
    return input(f"{label}{suffix}: ").strip() or default


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="kameit00/rp-steuer-app")
    args = parser.parse_args(argv)
    # getpass can fall back to echoed stdin. Fail before asking for any secrets.
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        parser.error("Bitte direkt in einem interaktiven Terminal ausführen, nicht über Pipes oder Agenten-Tools.")
    try:
        repository = repository_info(args.repo)
        print(f"Ziel: privates GitHub-Repository {repository}")
        print("Der private Schlüssel wird NICHT automatisch aus dem Schlüsselbund exportiert.")
        print("Benötigt wird eine passwortgeschützte P12-Datei der ausgewählten Developer-ID-Application-Identität.")
        path, data = read_p12(prompt("Pfad zur exportierten P12-Datei (außerhalb des Projekts)"))
        password = secret_prompt("P12-Export-Passwort (verdeckt): ")
        validate_p12(path, password)
        identity = prompt("Developer-ID-Application-Identität", default_identity())
        suffix = re.search(r"\(([A-Z0-9]{10})\)$", identity)
        team = prompt("Apple Team-ID", suffix.group(1) if suffix else "")
        validate_identity(identity, team)
        apple_id = prompt("Apple-ID des Developer-Accounts")
        if not apple_id or "@" not in apple_id:
            raise ValueError("Bitte die E-Mail-Adresse des Developer-Accounts eingeben.")
        print("Anwendungsspezifisches Passwort von account.apple.com verwenden, NICHT das normale Apple-ID-Passwort.")
        apple_password = secret_prompt("Anwendungsspezifisches Apple-Passwort (verdeckt): ")
        if not apple_password:
            raise ValueError("Das anwendungsspezifische Passwort darf nicht leer sein.")
        values = dict(zip(SECRET_NAMES, (base64.b64encode(data).decode("ascii"), password, identity, team, apple_id, apple_password)))
        print("Zu setzende Repository-Secrets: " + ", ".join(SECRET_NAMES))
        print("GitHub CLI verschlüsselt die Werte lokal vor der Übertragung. Vorhandene gleichnamige Secrets werden ersetzt.")
        print("CI-Sicherheitsausnahme: Apples security/notarytool-CLI benötigt Passwörter kurzzeitig in Prozessargumenten.")
        print("Das gilt NUR auf isolierten, temporären GitHub-Runnern mit vertrauenswürdigem Code, nie für die lokale Einrichtung.")
        print("Andere Prozesse desselben Runners könnten diese Argumente theoretisch lesen; Logs/Artefakte enthalten keine Passwörter.")
        if prompt("Für diese eng begrenzte CI-Ausnahme exakt CI-FREIGABE eingeben") != "CI-FREIGABE":
            print("Abgebrochen. Keine Secrets übertragen und keine CI-Freigabe erteilt.")
            return 1
        if prompt(f"Zum Übertragen das Ziel '{repository}' eingeben") != repository:
            print("Abgebrochen. Keine Secrets übertragen.")
            return 1
        # Block CI while rotating secrets; enable only after every upload succeeded.
        set_ci_approval(repository, False)
        for name, value in values.items():
            set_secret(repository, name, value)
        set_ci_approval(repository, True)
        print("Alle sechs Secrets und die ausdrückliche CI-Freigabe gesetzt. Private Dateien nicht committen; P12 sicher aufbewahren oder bewusst entfernen.")
        print("GitHub Actions → Build macOS apps → Run workflow → distribution: developer-id oder notarized.")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Einrichtung fehlgeschlagen: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nAbgebrochen. Eventuell bereits gesetzte Secrets bleiben erhalten.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
