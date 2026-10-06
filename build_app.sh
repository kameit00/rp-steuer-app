#!/bin/bash
# Build a SwiftUI .app containing a private, frozen Python engine/runtime.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
command -v swift >/dev/null || { echo "Install Xcode Command Line Tools: xcode-select --install" >&2; exit 1; }
command -v uv >/dev/null || { echo "Install uv before building: https://docs.astral.sh/uv/" >&2; exit 1; }
[[ "$(uname -s)" == "Darwin" ]] || { echo "Build on macOS." >&2; exit 1; }

IDENTITY="${SIGNING_IDENTITY:--}"
APP_NAME="RP Steuer App"
uv sync --project python --python 3.13.7 --group build --locked
PYTHON="$ROOT/python/.venv/bin/python"
"$PYTHON" python/check_version.py
IFS= read -r APP_VERSION < VERSION
IFS= read -r APP_BUILD < BUILD_NUMBER
ARCH="$(uname -m)"
PY_ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
[[ "$ARCH" == "$PY_ARCH" ]] || { echo "Python ($PY_ARCH) must match the build architecture ($ARCH)." >&2; exit 1; }

(cd python && "$PYTHON" -m unittest discover -s tests -v)
swift test
swift build -c release
SWIFT_BIN="$(swift build -c release --show-bin-path)/RPSteuerApp"

mkdir -p .build dist
STAGE="$(mktemp -d "$ROOT/.build/app-staging.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
ENGINE_ARGS=(--noconfirm --clean --onedir --name rp-steuer-app-engine
    --distpath "$STAGE/engine" --workpath "$ROOT/.build/pyinstaller" --specpath "$STAGE"
    --paths "$ROOT/python/production"
    --add-data "$ROOT/python/production/rules.json:production"
    --add-data "$ROOT/VERSION:."
    --hidden-import pandas.io.excel._xlsxwriter --hidden-import xlsxwriter
    --copy-metadata numpy --copy-metadata pandas --copy-metadata openpyxl --copy-metadata xlsxwriter)
if [[ "$IDENTITY" != "-" ]]; then
    ENGINE_ARGS+=(--codesign-identity "$IDENTITY")
fi
"$PYTHON" -m PyInstaller "${ENGINE_ARGS[@]}" python/engine.py

APP="$STAGE/$APP_NAME.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/engine"
cp "$SWIFT_BIN" "$APP/Contents/MacOS/RPSteuerApp"
cp -R "$STAGE/engine/rp-steuer-app-engine" "$APP/Contents/Resources/engine/"
cp python/production/rules.json "$APP/Contents/Resources/rules.json"
# Copy only manifest-listed and hash-verified files, never local bookkeeping data.
"$PYTHON" python/copy_snapshot.py python/production "$APP/Contents/Resources/production-snapshot"
cp README.md CHANGELOG.md VERSION BUILD_NUMBER "$APP/Contents/Resources/"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleExecutable</key><string>RPSteuerApp</string>
    <key>CFBundleIdentifier</key><string>com.relax-pillow.rpsteuerapp</string>
    <key>CFBundleName</key><string>RP Steuer App</string>
    <key>CFBundleDisplayName</key><string>RP Steuer App</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$APP_VERSION</string>
    <key>CFBundleVersion</key><string>$APP_BUILD</string>
    <key>CFBundleDevelopmentRegion</key><string>de</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSHumanReadableCopyright</key><string>relax-pillow</string>
</dict></plist>
PLIST

# Sign nested code first, then the bundle. Default is ad-hoc for local use.
while IFS= read -r -d '' component; do
    if file -b "$component" | grep -q 'Mach-O'; then
        if [[ "$IDENTITY" == "-" ]]; then
            codesign --force --sign - "$component"
        else
            codesign --force --options runtime --timestamp --sign "$IDENTITY" "$component"
        fi
    fi
done < <(find "$APP/Contents" -type f -print0)
if [[ "$IDENTITY" == "-" ]]; then
    codesign --force --sign - "$APP"
else
    codesign --force --options runtime --timestamp --sign "$IDENTITY" "$APP"
fi
codesign --verify --deep --strict "$APP"

ENGINE="$APP/Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine"
env -i HOME="$HOME" PATH=/usr/bin:/bin "$ENGINE" --diagnostics
(cd python && RP_STEUER_APP_TEST_ENGINE="$ENGINE" "$PYTHON" -m unittest discover -s tests -v)
RP_STEUER_APP_TEST_ENGINE="$ENGINE" swift test

DEST="$ROOT/dist/$APP_NAME.app"
rm -rf "$DEST"
mv "$APP" "$DEST"
# Check relocation: the frozen runtime must not depend on the staging path.
env -i HOME="$HOME" PATH=/usr/bin:/bin "$DEST/Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine" --diagnostics
printf '\nBuilt (%s): %s\nOpen: open "%s"\n' "$ARCH" "$DEST" "$DEST"
