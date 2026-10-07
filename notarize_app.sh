#!/bin/bash
# Existing keychain credentials only. Never enable tracing or print credentials.
set +x
set -euo pipefail
cd "$(dirname "$0")"
exec python3 - "$PWD" "$@" <<'PY'
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT = Path(sys.argv[1])
NAME = 'RP Steuer App.app'


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_file(path):
    with path.open('rb') as stream:
        os.fsync(stream.fileno())


def sync_tree(path):
    for child in path.rglob('*'):
        if child.is_file() and not child.is_symlink():
            sync_file(child)
    for child in sorted(path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if child.is_dir() and not child.is_symlink():
            sync_directory(child)
    sync_directory(path)


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(args, check=True):
    # Never echo command lines: keychain locations/profile names can be private.
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if check and result.returncode:
        raise ValueError(f'{args[0]} {args[1]} failed (exit {result.returncode})')
    return result


def response(command, output):
    result = run(command, check=False)
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError()
    except ValueError:
        data = {'error': 'No valid JSON response', 'exit_code': result.returncode}
    atomic_json(output, data)
    return result.returncode, data


def safe_archive(path):
    with zipfile.ZipFile(path) as archive:
        entries = set()
        links = set()
        for entry in archive.infolist():
            name = entry.filename.rstrip('/')
            parts = name.split('/')
            if any(p in ('', '.', '..') for p in parts) or name in entries:
                raise ValueError('Unsafe ZIP path (or duplicate entry)')
            entries.add(name)
            if not (parts[0] == NAME or
                    (parts[0] == '__MACOSX' and (len(parts) == 1 or parts[1] in (NAME, '._' + NAME)))):
                raise ValueError('ZIP must contain exactly ' + NAME)
            if stat.S_ISLNK(entry.external_attr >> 16):
                target = archive.read(entry).decode('utf-8')
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                if target.startswith('/') or not resolved.startswith(NAME + '/') or name == NAME:
                    raise ValueError('Unsafe ZIP symlink')
                links.add(name)
        # ditto must never write through a directory symlink during extraction.
        for name in entries:
            parts = name.split('/')
            if any('/'.join(parts[:i]) in links for i in range(1, len(parts))):
                raise ValueError('ZIP entry traverses a symlink')


def tree_hash(app):
    # Detect changes to the generated app, including signatures and symlinks.
    h = hashlib.sha256()
    for path in sorted(app.rglob('*')):
        mode = path.lstat().st_mode
        record = [str(path.relative_to(app)), stat.S_IMODE(mode)]
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):
                raise ValueError('Bundle symlink escapes app')
            record += ['link', os.readlink(path)]
        elif path.is_file():
            record += ['file', digest(path)]
        elif path.is_dir():
            record += ['dir']
        else:
            raise ValueError('Unsupported bundle file type')
        h.update(json.dumps(record).encode())
    return h.hexdigest()


def verify_signed(app, arch, version, build, expected_team=None):
    if app.is_symlink() or not app.is_dir():
        raise ValueError('Expected a real app directory: ' + str(app))
    tree_hash(app)
    with (app / 'Contents/Info.plist').open('rb') as stream:
        metadata = plistlib.load(stream)
    expected = {
        'CFBundleIdentifier': 'com.relax-pillow.rpsteuerapp',
        'CFBundleExecutable': 'RPSteuerApp',
        'CFBundleName': 'RP Steuer App',
        'CFBundleDisplayName': 'RP Steuer App',
        'CFBundleShortVersionString': version,
        'CFBundleVersion': build,
        'LSMinimumSystemVersion': '14.0',
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError('Bundle metadata mismatch: ' + key)
    run(['codesign', '--verify', '--deep', '--strict', app])
    binaries = []
    magics = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
              b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
    for path in sorted(app.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic in magics:
                if run(['lipo', '-archs', path]).stdout.split() != [arch]:
                    raise ValueError('Wrong or mixed Mach-O architecture: ' + str(path))
                binaries.append(path)
    for relative in ('Contents/MacOS/RPSteuerApp',
                     'Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine'):
        binary = app / relative
        if binary not in binaries or not os.access(binary, os.X_OK):
            raise ValueError('Missing executable Mach-O: ' + relative)
    team = expected_team
    # Deep verification alone permits ad-hoc nested code. Check every Mach-O too.
    for component in [app] + binaries:
        result = run(['codesign', '--display', '--verbose=4', component])
        details = result.stdout + '\n' + result.stderr
        match = re.search(r'^TeamIdentifier=([A-Z0-9]{10})$', details, re.M)
        authority = re.search(r'^Authority=Developer ID Application: .+ \(([A-Z0-9]{10})\)$', details, re.M)
        if not match or not authority or match[1] != authority[1]:
            raise ValueError('Developer ID Application signature/team required')
        if team is None:
            team = match[1]
        if match[1] != team:
            raise ValueError('Inconsistent signing team')
        if not re.search(r'^CodeDirectory .+flags=.*\bruntime\b', details, re.M):
            raise ValueError('Hardened runtime required')
        if not re.search(r'^Timestamp=\S.+$', details, re.M):
            raise ValueError('Secure signing timestamp required')
        if 'Signature=adhoc' in details:
            raise ValueError('Ad-hoc signature cannot be notarized')
    return team


def allowed_hashes(ledger, kind):
    return {ledger.get('original_' + kind + '_sha256'),
            ledger.get('final_' + kind + '_sha256'),
            ledger.get('previous_' + kind + '_sha256')}


def verify_ticket(app, args, version, build, team):
    run(['xcrun', 'stapler', 'validate', app])
    verify_signed(app, args.arch, version, build, team)
    run(['spctl', '--assess', '--type', 'execute', '--verbose=2', app])


def main():
    parser = argparse.ArgumentParser(description='Notarize a signed release ZIP using existing keychain credentials.')
    parser.add_argument('--arch', required=True, choices=('arm64', 'x86_64'))
    parser.add_argument('--resume', action='store_true', help='Require an existing local submission ledger; never submit again.')
    args = parser.parse_args(sys.argv[2:])
    version = (ROOT / 'VERSION').read_text().strip()
    build = (ROOT / 'BUILD_NUMBER').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not re.fullmatch(r'[1-9]\d*', build):
        raise ValueError('Invalid VERSION or BUILD_NUMBER')
    dist = ROOT / 'dist'
    zip_path = dist / f'RP-Steuer-App-{version}-{args.arch}.zip'
    dest_app = dist / args.arch / NAME
    state = dist / 'notarization' / args.arch
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.is_symlink():
        raise ValueError('Notarization state must not be a symlink')
    os.chmod(state, 0o700)
    sync_directory(state.parent)
    sync_directory(dist)
    # macOS has no standard flock executable. Hold an advisory lock in Python.
    lock = (state / '.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('Another notarization process owns this architecture')
    ledger_path = state / 'ledger.json'
    upload = state / 'upload.zip'
    frozen = state / 'input' / NAME
    credentials = ['--keychain-profile', os.environ.get('NOTARY_KEYCHAIN_PROFILE', 'rp-steuer-app')]
    if os.environ.get('NOTARY_KEYCHAIN_PATH'):
        credentials += ['--keychain', os.environ['NOTARY_KEYCHAIN_PATH']]
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        for key, value in {'arch': args.arch, 'version': version, 'build': build}.items():
            if ledger.get(key) != value:
                raise ValueError('Existing ledger mismatch: ' + key)
        if digest(upload) != ledger['original_zip_sha256']:
            raise ValueError('Frozen upload.zip hash differs from ledger')
        current_hash = digest(zip_path)
        if current_hash not in allowed_hashes(ledger, 'zip'):
            raise ValueError('Release ZIP changed since submission; refusing a different rebuild')
        backup = state / 'previous.app'
        # Recover a process interruption between the two directory renames.
        if not dest_app.exists() and backup.is_dir() and ledger.get('final_app_sha256'):
            if tree_hash(backup) not in allowed_hashes(ledger, 'app'):
                raise ValueError('Interrupted publication backup differs from ledger')
            os.replace(backup, dest_app)
            sync_directory(dest_app.parent)
            sync_directory(state)
        if tree_hash(dest_app) not in allowed_hashes(ledger, 'app'):
            raise ValueError('Release app changed since submission; refusing a different rebuild')
        # Recover a response persisted immediately before a crash during ledger update.
        if not ledger.get('id') and (state / 'submit.json').exists():
            ledger['id'] = json.loads((state / 'submit.json').read_text()).get('id')
            atomic_json(ledger_path, ledger)
        if not ledger.get('id'):
            raise ValueError('Submission may have occurred but no ID was recorded. Inspect submit.json / Apple history; do not resubmit.')
    else:
        if args.resume:
            raise ValueError('--resume requires an existing local ledger.json')
        if upload.exists() or (state / 'submit.json').exists():
            raise ValueError('Orphan submission files exist; recover the ledger before proceeding')
        safe_archive(zip_path)
        team = verify_signed(dest_app, args.arch, version, build)
        original_app = tree_hash(dest_app)
        # This immutable copy, not a recreated ZIP, is the exact payload submitted.
        temp_upload = state / '.upload.zip'
        shutil.copyfile(zip_path, temp_upload)
        os.chmod(temp_upload, 0o600)
        sync_file(temp_upload)
        original_hash = digest(temp_upload)
        if digest(zip_path) != original_hash:
            raise ValueError('Release ZIP changed while copying')
        os.replace(temp_upload, upload)
        sync_directory(state)
        ledger = {'schema': 1, 'arch': args.arch, 'version': version, 'build': build,
                  'original_zip_sha256': original_hash, 'original_app_sha256': original_app,
                  'team': team, 'id': None}
        # Persist intent BEFORE the network call; an uncertain submit is never retried.
        atomic_json(ledger_path, ledger)

    # Re-extract on every attempt: stapling is repeatable, and CI only needs upload.zip + JSON.
    safe_archive(upload)
    if frozen.parent.exists():
        shutil.rmtree(frozen.parent)
    frozen.parent.mkdir(mode=0o700)
    run(['ditto', '-x', '-k', upload, frozen.parent])
    verify_signed(frozen, args.arch, version, build, ledger['team'])
    if tree_hash(frozen) != ledger['original_app_sha256']:
        raise ValueError('Input ZIP app differs from generated app')
    if not ledger.get('id'):
        code, submission = response(['xcrun', 'notarytool', 'submit', upload, *credentials,
                                     '--output-format', 'json'], state / 'submit.json')
        request_id = submission.get('id')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-fA-F0-9-]{36}', request_id):
            raise ValueError('No valid submission ID recorded; do not resubmit. Inspect local ledger / Apple history.')
        ledger['id'] = request_id
        atomic_json(ledger_path, ledger)
        print('Submission ID: ' + request_id, flush=True)
    request_id = ledger['id']
    try:
        uuid.UUID(request_id)
    except (ValueError, TypeError):
        raise ValueError('Invalid ledger submission ID')
    print('Waiting for submission ID: ' + request_id, flush=True)
    wait_code, waited = response(['xcrun', 'notarytool', 'wait', request_id, *credentials,
                                 '--timeout', os.environ.get('NOTARY_WAIT_TIMEOUT', '15m'),
                                 '--output-format', 'json'], state / 'wait.json')
    # Query the SAME ID even after a timeout/nonzero exit, retaining the last known status.
    info_code, status = response(['xcrun', 'notarytool', 'info', request_id, *credentials,
                                 '--output-format', 'json'], state / 'status.json')
    accepted = info_code == 0 and status.get('id') == request_id and status.get('status') == 'Accepted'
    if not accepted:
        if status.get('status') == 'Invalid' or waited.get('status') == 'Invalid':
            response(['xcrun', 'notarytool', 'log', request_id, *credentials,
                      '--output-format', 'json'], state / 'log.json')
        raise ValueError(f'Submission {request_id} is not Accepted ({status.get("status", "unknown")}). '
                         f'Resume with ./notarize_app.sh --arch {args.arch} --resume; keep upload.zip and all JSON state.')
    run(['xcrun', 'stapler', 'staple', frozen])
    verify_ticket(frozen, args, version, build, ledger['team'])
    # Stage final artifacts on the same volume. No release output changes until all checks pass.
    with tempfile.TemporaryDirectory(prefix='final-', dir=state) as work:
        work = Path(work)
        final_zip = work / zip_path.name
        run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', frozen, final_zip])
        safe_archive(final_zip)
        unpacked = work / 'unpacked'
        unpacked.mkdir()
        run(['ditto', '-x', '-k', final_zip, unpacked])
        final_app = unpacked / NAME
        verify_ticket(final_app, args, version, build, ledger['team'])
        final_hash = digest(final_zip)
        final_app_hash = tree_hash(final_app)
        checksum = work / (zip_path.name + '.sha256')
        checksum.write_text(final_hash + '  ' + zip_path.name + '\n')
        sync_tree(final_app)
        sync_file(final_zip)
        sync_file(checksum)
        sync_directory(unpacked)
        sync_directory(work)
        sync_directory(state)
        previous_zip_hash = digest(zip_path)
        previous_app_hash = tree_hash(dest_app)
        if previous_zip_hash not in allowed_hashes(ledger, 'zip'):
            raise ValueError('Release ZIP changed during notarization')
        if previous_app_hash not in allowed_hashes(ledger, 'app'):
            raise ValueError('Release app changed during notarization')
        # Retain the outputs actually present, not just the last planned hashes.
        # A retry may start from either side of an interrupted publication.
        ledger.update(previous_zip_sha256=previous_zip_hash, previous_app_sha256=previous_app_hash,
                      final_zip_sha256=final_hash, final_app_sha256=final_app_hash, published=False)
        atomic_json(ledger_path, ledger)
        # Individual renames are atomic; a crash between them is recoverable from this ledger.
        backup = state / 'previous.app'
        if backup.exists():
            shutil.rmtree(backup)
        os.replace(dest_app, backup)
        sync_directory(dest_app.parent)
        sync_directory(state)
        try:
            os.replace(final_app, dest_app)
        except BaseException:
            os.replace(backup, dest_app)
            sync_directory(dest_app.parent)
            sync_directory(state)
            raise
        sync_directory(dest_app.parent)
        sync_directory(unpacked)
        os.replace(final_zip, zip_path)
        sync_directory(dist)
        sync_directory(work)
        os.replace(checksum, Path(str(zip_path) + '.sha256'))
        sync_directory(dist)
        sync_directory(work)
        shutil.rmtree(backup)
        sync_directory(state)
        ledger['published'] = True
        atomic_json(ledger_path, ledger)
    print(f'Notarized and stapled: {zip_path.name} (submission {request_id})')
    # dist/RP Steuer App.app is intentionally untouched: its architecture link stays valid.


try:
    main()
except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
    print('Notarization failed: ' + str(error), file=sys.stderr)
    sys.exit(1)
PY
