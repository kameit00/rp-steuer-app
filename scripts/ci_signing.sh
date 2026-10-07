#!/bin/bash
# Signing credentials are scoped to a disposable GitHub Actions runner keychain.
set +x
set -euo pipefail
umask 077

fail() {
  printf 'CI signing: %s\n' "$1" >&2
  exit 1
}

[[ "${GITHUB_ACTIONS:-}" == true ]] || fail 'This helper is only for GitHub Actions runners.'

COMMAND="${1:-}"
[[ "$COMMAND" == setup || "$COMMAND" == cleanup ]] || fail 'Usage: ci_signing.sh setup|cleanup --arch arm64|x86_64 [--distribution developer-id|notarized]'
shift
ARCH=''
DISTRIBUTION=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)
      [[ $# -ge 2 ]] || fail 'Missing architecture.'
      ARCH="$2"; shift 2 ;;
    --distribution)
      [[ $# -ge 2 ]] || fail 'Missing distribution.'
      DISTRIBUTION="$2"; shift 2 ;;
    *) fail 'Unknown argument.' ;;
  esac
done
case "$ARCH" in arm64|x86_64) ;; *) fail 'Unsupported architecture.' ;; esac
[[ "${RUNNER_TEMP:-}" == /* && -d "$RUNNER_TEMP" ]] || fail 'RUNNER_TEMP must be an existing absolute directory.'
SIGNING_DIR="$RUNNER_TEMP/rp-steuer-signing-$ARCH"
KEYCHAIN_PATH="$SIGNING_DIR/signing.keychain-db"
P12_PATH="$SIGNING_DIR/developer-id.p12"

cleanup() {
  # Never follow a replacement symlink or touch the runner login keychain.
  [[ ! -L "$SIGNING_DIR" ]] || { printf 'CI signing: Refusing a symlinked signing directory.\n' >&2; return 1; }
  [[ -d "$SIGNING_DIR" ]] || return 0
  local result=0
  if [[ -e "$KEYCHAIN_PATH" ]]; then
    security delete-keychain "$KEYCHAIN_PATH" >/dev/null 2>&1 || result=1
  fi
  rm -rf -- "$SIGNING_DIR" || result=1
  return "$result"
}

if [[ "$COMMAND" == cleanup ]]; then
  cleanup
  exit
fi

# Apple CLI password arguments require explicit repository-owner approval.
# This exception applies only on disposable CI runners; cleanup must not depend on it.
[[ "${CI_SECRET_ARGV_APPROVED:-}" == true ]] || fail 'Set CI_SECRET_ARGV_APPROVED=true only after approving the documented CI-only Apple CLI password-argument exception.'
case "$DISTRIBUTION" in developer-id|notarized) ;; *) fail 'Setup requires developer-id or notarized distribution.' ;; esac
for name in DEVELOPER_ID_P12_BASE64 DEVELOPER_ID_P12_PASSWORD SIGNING_IDENTITY APPLE_TEAM_ID; do
  [[ -n "${!name:-}" ]] || fail "Missing required repository secret: $name."
done
if [[ "$DISTRIBUTION" == notarized ]]; then
  for name in APPLE_ID APPLE_APP_SPECIFIC_PASSWORD; do
    [[ -n "${!name:-}" ]] || fail "Missing required repository secret: $name."
  done
fi
[[ "$APPLE_TEAM_ID" =~ ^[A-Z0-9]{10}$ ]] || fail 'APPLE_TEAM_ID must be a ten-character team identifier.'
[[ "$SIGNING_IDENTITY" == 'Developer ID Application: '*" ($APPLE_TEAM_ID)" ]] || fail 'SIGNING_IDENTITY must be an exact Developer ID Application label for APPLE_TEAM_ID.'
[[ "${GITHUB_ENV:-}" == /* && -f "$GITHUB_ENV" ]] || fail 'Missing GitHub Actions environment file.'

# mkdir deliberately fails for an existing directory: never reuse stale credentials.
mkdir -m 700 "$SIGNING_DIR"
trap 'status=$?; if [[ $status -ne 0 ]]; then cleanup || true; fi; exit "$status"' EXIT
KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
[[ "$KEYCHAIN_PASSWORD" =~ ^[a-f0-9]{64}$ ]] || fail 'Could not generate a keychain password.'
printf '::add-mask::%s\n' "$KEYCHAIN_PASSWORD"

# Read the certificate directly from the environment, never from a shell argument.
python3 - "$P12_PATH" <<'PY'
import base64
import os
import sys

try:
    encoded = ''.join(os.environ['DEVELOPER_ID_P12_BASE64'].split())
    certificate = base64.b64decode(encoded, validate=True)
    if not certificate:
        raise ValueError('empty certificate')
    with open(sys.argv[1], 'xb') as stream:
        stream.write(certificate)
except Exception:
    sys.exit('CI signing: Could not decode the P12 repository secret.')
PY
chmod 600 "$P12_PATH"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" >/dev/null 2>&1 || fail 'Could not create the temporary keychain.'
chmod 600 "$KEYCHAIN_PATH"
security set-keychain-settings -lut 7200 "$KEYCHAIN_PATH" >/dev/null 2>&1 || fail 'Could not configure the temporary keychain.'
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" >/dev/null 2>&1 || fail 'Could not unlock the temporary keychain.'
security import "$P12_PATH" -k "$KEYCHAIN_PATH" -P "$DEVELOPER_ID_P12_PASSWORD" -T /usr/bin/codesign >/dev/null 2>&1 || fail 'Could not import the signing certificate.'
rm -f "$P12_PATH"
unset DEVELOPER_ID_P12_BASE64 DEVELOPER_ID_P12_PASSWORD
# The partition list applies ONLY to this temporary keychain, never login.
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" >/dev/null 2>&1 || fail 'Could not grant codesign access to the temporary keychain.'
security list-keychains -d user -s "$KEYCHAIN_PATH" "$HOME/Library/Keychains/login.keychain-db" >/dev/null 2>&1 || fail 'Could not add the temporary keychain to the search list.'

# Only a valid codesigning identity with the exact requested label is accepted.
security find-identity -v -p codesigning "$KEYCHAIN_PATH" | python3 -c '
import os, re, sys
labels = re.findall(r"^\s*\d+\) [A-Fa-f0-9]{40} \"([^\"]+)\"\s*$", sys.stdin.read(), re.M)
if labels.count(os.environ["SIGNING_IDENTITY"]) != 1:
    sys.exit("CI signing: The temporary keychain must contain exactly one matching valid Developer ID Application identity.")
' || fail 'Signing identity validation failed.'

if [[ "$DISTRIBUTION" == notarized ]]; then
  xcrun notarytool store-credentials rp-steuer-app-ci \
    --apple-id "$APPLE_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --team-id "$APPLE_TEAM_ID" --keychain "$KEYCHAIN_PATH" >/dev/null 2>&1 \
    || fail 'Could not validate and store notarization credentials in the temporary keychain.'
fi
chmod 600 "$KEYCHAIN_PATH"
printf 'NOTARY_KEYCHAIN_PROFILE=rp-steuer-app-ci\nNOTARY_KEYCHAIN_PATH=%s\n' "$KEYCHAIN_PATH" >> "$GITHUB_ENV"
unset KEYCHAIN_PASSWORD APPLE_ID APPLE_APP_SPECIFIC_PASSWORD
printf 'CI signing: Temporary Developer ID keychain ready (%s).\n' "$DISTRIBUTION"
