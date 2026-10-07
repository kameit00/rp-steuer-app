#!/bin/bash
# Native, independently tested macOS builds; no mixed-architecture Python bundles.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
[[ "$(uname -s)" == "Darwin" ]] || { echo "Build on macOS." >&2; exit 1; }
[[ "$(/usr/sbin/sysctl -in sysctl.proc_translated 2>/dev/null || true)" != "1" ]] || {
    echo "Rosetta-translated builds are not native Intel validation. Use a native Mac or GitHub Actions." >&2; exit 1
}
ARCH="$(uname -m)"
if [[ $# -gt 0 ]]; then
    if [[ $# -ne 2 || "$1" != "--arch" ]]; then
        echo "Usage: ./build_app.sh [--arch arm64|x86_64]" >&2; exit 1
    fi
    ARCH="$2"
fi
case "$ARCH" in arm64|x86_64) ;; *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;; esac
[[ "$ARCH" == "$(uname -m)" ]] || {
    echo "Build $ARCH on a matching native Mac or the GitHub Actions build-macos workflow." >&2
    echo "A Swift cross-build alone cannot provide the matching Python runtime." >&2; exit 1
}
command -v swift >/dev/null || { echo "Install Xcode Command Line Tools: xcode-select --install" >&2; exit 1; }
command -v uv >/dev/null || { echo "Install uv before building: https://docs.astral.sh/uv/" >&2; exit 1; }

IDENTITY="${SIGNING_IDENTITY:--}"
APP_NAME="RP Steuer App"
# Keep build environments/caches separate; never mutate the development .venv.
BUILD_ROOT="$ROOT/.build/native/$ARCH"
mkdir -p "$BUILD_ROOT" "$ROOT/dist/$ARCH"
UV_PROJECT_ENVIRONMENT="$BUILD_ROOT/python" uv sync --project python --python 3.13.7 --managed-python --group build --locked
PYTHON="$BUILD_ROOT/python/bin/python"
"$PYTHON" python/check_version.py
IFS= read -r APP_VERSION < VERSION
IFS= read -r APP_BUILD < BUILD_NUMBER
PY_ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
[[ "$ARCH" == "$PY_ARCH" ]] || { echo "Python ($PY_ARCH) must match the build architecture ($ARCH)." >&2; exit 1; }
SWIFT_ARGS=(--scratch-path "$BUILD_ROOT/swift" --arch "$ARCH")

(cd python && "$PYTHON" -m unittest discover -s tests -v)
swift test "${SWIFT_ARGS[@]}"
swift build "${SWIFT_ARGS[@]}" -c release
SWIFT_BIN="$(swift build "${SWIFT_ARGS[@]}" -c release --show-bin-path)/RPSteuerApp"

STAGE="$(mktemp -d "$BUILD_ROOT/app-staging.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
ENGINE_ARGS=(--noconfirm --clean --onedir --name rp-steuer-app-engine
    --target-architecture "$ARCH"
    --distpath "$STAGE/engine" --workpath "$BUILD_ROOT/pyinstaller" --specpath "$STAGE"
    --paths "$ROOT/python/production"
    --add-data "$ROOT/python/production/rules.json:production"
    --add-data "$ROOT/VERSION:."
    --hidden-import pandas.io.excel._xlsxwriter --hidden-import xlsxwriter
    --copy-metadata numpy --copy-metadata pandas --copy-metadata openpyxl --copy-metadata xlsxwriter)
if [[ "$IDENTITY" != "-" ]]; then ENGINE_ARGS+=(--codesign-identity "$IDENTITY"); fi
"$PYTHON" -m PyInstaller "${ENGINE_ARGS[@]}" python/engine.py

APP="$STAGE/$APP_NAME.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/engine"
cp "$SWIFT_BIN" "$APP/Contents/MacOS/RPSteuerApp"
cp -R "$STAGE/engine/rp-steuer-app-engine" "$APP/Contents/Resources/engine/"
cp python/production/rules.json "$APP/Contents/Resources/rules.json"
cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
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
    <key>CFBundleIconFile</key><string>AppIcon.icns</string>
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
"$PYTHON" python/verify_app.py "$APP" --arch "$ARCH" --version "$APP_VERSION" --build "$APP_BUILD"
ENGINE="$APP/Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine"
(cd python && RP_STEUER_APP_TEST_ENGINE="$ENGINE" "$PYTHON" -m unittest discover -s tests -v)
RP_STEUER_APP_TEST_ENGINE="$ENGINE" swift test "${SWIFT_ARGS[@]}"

# Verify relocation AND ZIP extraction, including nested signatures and runtime.
ZIP_NAME="RP-Steuer-App-$APP_VERSION-$ARCH.zip"
ZIP="$STAGE/$ZIP_NAME"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
mkdir "$STAGE/unpacked"
ditto -x -k "$ZIP" "$STAGE/unpacked"
UNPACKED="$STAGE/unpacked/$APP_NAME.app"
codesign --verify --deep --strict "$UNPACKED"
"$PYTHON" python/verify_app.py "$UNPACKED" --arch "$ARCH" --version "$APP_VERSION" --build "$APP_BUILD"

DEST="$ROOT/dist/$ARCH/$APP_NAME.app"
rm -rf "$DEST"
mv "$APP" "$DEST"
mv "$ZIP" "$ROOT/dist/$ZIP_NAME"
(cd "$ROOT/dist" && shasum -a 256 "$ZIP_NAME" > "$ZIP_NAME.sha256")
# Backward-compatible convenience link always points to the latest native build.
rm -rf "$ROOT/dist/$APP_NAME.app"
ln -s "$ARCH/$APP_NAME.app" "$ROOT/dist/$APP_NAME.app"
printf '\nBuilt (%s): %s\nZIP: %s\nOpen: open "%s"\n' "$ARCH" "$DEST" "$ROOT/dist/$ZIP_NAME" "$DEST"
