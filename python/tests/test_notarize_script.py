"""Fault-injection tests: no Apple authentication/submissions or actual signing."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[2] / 'notarize_app.sh'
NAME = 'RP Steuer App.app'
REQUEST_ID = '01234567-89ab-cdef-0123-456789abcdef'

# Every external Apple command is a PATH-local fake. Python/zipfile implement
# only the fixture's archive transport; this never invokes any system Apple tool.
FAKE_TOOL = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['FAKE_CALLS'], 'a') as stream:
    stream.write(json.dumps([name] + args) + '\n')

def fail():
    sys.exit(1)

if name == 'codesign':
    if '--verify' in args:
        if os.environ.get('FAKE_VERIFY_FAIL'):
            fail()
    else:
        kind = os.environ.get('FAKE_SIGNATURE', 'valid')
        if kind == 'nested-adhoc' and 'MacOS/RPSteuerApp' not in args[-1]:
            kind = 'valid'
        elif kind == 'nested-adhoc':
            kind = 'adhoc'
        team = 'ABCDEFGHIJ' if kind != 'team' else 'ZZZZZZZZZZ'
        print('CodeDirectory v=20500 size=100 flags=0x10000(runtime) hashes=2+7 location=embedded'
              if kind != 'runtime' else 'CodeDirectory v=20500 size=100 flags=0x0(none) hashes=2+7 location=embedded', file=sys.stderr)
        if kind == 'adhoc':
            print('Signature=adhoc\nTeamIdentifier=not set', file=sys.stderr)
        else:
            print('Authority=Developer ID Application: Test Company (ABCDEFGHIJ)', file=sys.stderr)
            print('TeamIdentifier=' + team, file=sys.stderr)
        if kind != 'timestamp':
            print('Timestamp=1 Apr 2026 at 12:34:56', file=sys.stderr)
elif name == 'lipo':
    print(os.environ.get('FAKE_ARCH', 'arm64'))
elif name == 'spctl':
    if os.environ.get('FAKE_SPCTL_FAIL'):
        fail()
    print('accepted', file=sys.stderr)
elif name == 'ditto':
    if '-x' in args:
        archive, dest = Path(args[-2]), Path(args[-1])
        with zipfile.ZipFile(archive) as stream:
            for entry in stream.infolist():
                target = dest / entry.filename
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(stream.read(entry))
                os.chmod(target, (entry.external_attr >> 16) & 0o777)
    else:
        app, archive = Path(args[-2]), Path(args[-1])
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.write(app, app.name + '/')
            for path in sorted(app.rglob('*')):
                stream.write(path, str(path.relative_to(app.parent)))
elif name == 'xcrun':
    if args[0] == 'notarytool':
        action = args[1]
        if action == 'submit':
            data = {'id': '01234567-89ab-cdef-0123-456789abcdef', 'message': 'Successfully uploaded file'}
            if os.environ.get('FAKE_SUBMIT_NO_ID'):
                data = {'message': 'network lost; outcome uncertain'}
            print(json.dumps(data))
        elif action in ('wait', 'info'):
            status = os.environ.get('FAKE_STATUS', 'Accepted')
            if action == 'wait' and os.environ.get('FAKE_WAIT_TIMEOUT'):
                print(json.dumps({'id': args[2], 'status': 'In Progress'}))
                fail()
            print(json.dumps({'id': args[2], 'status': status}))
            if os.environ.get('FAKE_INFO_FAIL') and action == 'info':
                fail()
        elif action == 'log':
            print(json.dumps({'logFormatVersion': 1, 'issues': [{'message': 'synthetic failure'}]}))
        else:
            fail()
    elif args[0] == 'stapler':
        app = Path(args[-1])
        if args[1] == 'staple':
            if os.environ.get('FAKE_STAPLE_FAIL'):
                fail()
            (app / 'Contents/ticket').write_text('Apple synthetic ticket')
        elif args[1] == 'validate':
            if not (app / 'Contents/ticket').exists():
                fail()
            if os.environ.get('FAKE_EXTRACTED_TICKET_FAIL') and 'unpacked' in str(app):
                fail()
        else:
            fail()
    else:
        fail()
else:
    fail()
'''


class NotarizeScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(SCRIPT, self.root / 'notarize_app.sh')
        (self.root / 'VERSION').write_text('1.2.0\n')
        (self.root / 'BUILD_NUMBER').write_text('3\n')
        self.app = self.root / 'dist/arm64' / NAME
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        (self.app / 'Contents/Resources/engine/rp-steuer-app-engine').mkdir(parents=True)
        self.metadata = {
            'CFBundleIdentifier': 'com.relax-pillow.rpsteuerapp',
            'CFBundleExecutable': 'RPSteuerApp',
            'CFBundleName': 'RP Steuer App',
            'CFBundleDisplayName': 'RP Steuer App',
            'CFBundleShortVersionString': '1.2.0',
            'CFBundleVersion': '3',
            'LSMinimumSystemVersion': '14.0',
        }
        self.write_metadata()
        for relative in ('Contents/MacOS/RPSteuerApp',
                         'Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine'):
            path = self.app / relative
            path.write_bytes(b'\xcf\xfa\xed\xfe' + b'synthetic Mach-O; never execute')
            path.chmod(0o755)
        self.archive = self.root / 'dist/RP-Steuer-App-1.2.0-arm64.zip'
        self.pack_input()
        self.original_zip = self.archive.read_bytes()
        self.checksum = Path(str(self.archive) + '.sha256')
        self.checksum.write_text('original-checksum\n')
        self.link = self.root / 'dist' / NAME
        self.link.symlink_to('arm64/' + NAME)
        self.state = self.root / 'dist/notarization/arm64'
        self.calls_file = self.root / 'calls.jsonl'
        tools = self.root / 'bin'
        tools.mkdir()
        executable = tools / 'fake'
        executable.write_text(FAKE_TOOL.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1))
        executable.chmod(0o755)
        for name in ('codesign', 'lipo', 'spctl', 'ditto', 'xcrun'):
            (tools / name).symlink_to('fake')
        self.env = os.environ.copy()
        # Prevent developer/local credentials or fault switches from influencing tests.
        for key in list(self.env):
            if key.startswith(('NOTARY_', 'FAKE_')):
                del self.env[key]
        self.env.update(PATH=str(tools) + os.pathsep + self.env['PATH'], FAKE_CALLS=str(self.calls_file))

    def write_metadata(self):
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps(self.metadata))

    def pack_input(self):
        with zipfile.ZipFile(self.archive, 'w') as stream:
            stream.write(self.app, NAME + '/')
            for path in sorted(self.app.rglob('*')):
                stream.write(path, str(path.relative_to(self.app.parent)))

    def invoke(self, *args, **env):
        return subprocess.run(['bash', str(self.root / 'notarize_app.sh'), '--arch', 'arm64', *args],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=30)

    def calls(self, action=None):
        calls = [json.loads(line) for line in self.calls_file.read_text().splitlines()] if self.calls_file.exists() else []
        return [call for call in calls if len(call) > 2 and call[:3] == ['xcrun', 'notarytool', action]] if action else calls

    def assert_unchanged(self):
        self.assertEqual(self.archive.read_bytes(), self.original_zip)
        self.assertEqual(self.checksum.read_text(), 'original-checksum\n')
        self.assertFalse((self.app / 'Contents/ticket').exists())
        self.assertEqual(os.readlink(self.link), 'arm64/' + NAME)

    def test_accepted_pipeline_uses_exact_upload_and_checks_final_archive(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Notarized and stapled', result.stdout)
        self.assertEqual((self.state / 'upload.zip').read_bytes(), self.original_zip)
        self.assertTrue((self.app / 'Contents/ticket').exists())
        with zipfile.ZipFile(self.archive) as stream:
            self.assertEqual(stream.read(NAME + '/Contents/ticket'), b'Apple synthetic ticket')
        actual_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.assertEqual(self.checksum.read_text(), actual_hash + '  ' + self.archive.name + '\n')
        ledger = json.loads((self.state / 'ledger.json').read_text())
        self.assertEqual(ledger['id'], REQUEST_ID)
        self.assertEqual(ledger['arch'], 'arm64')
        self.assertEqual(ledger['version'], '1.2.0')
        self.assertEqual(ledger['build'], '3')
        self.assertEqual(ledger['original_zip_sha256'], hashlib.sha256(self.original_zip).hexdigest())
        self.assertTrue(ledger['published'])
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state / 'ledger.json').stat().st_mode), 0o600)
        self.assertEqual(len(self.calls('submit')), 1)
        validators = [call for call in self.calls() if call[:3] == ['xcrun', 'stapler', 'validate']]
        self.assertEqual(len(validators), 2)
        self.assertIn('unpacked', validators[-1][-1])
        self.assertEqual(os.readlink(self.link), 'arm64/' + NAME)

    def test_invalid_collects_log_without_publishing(self):
        result = self.invoke(FAKE_STATUS='Invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(REQUEST_ID, result.stderr)
        self.assertIn('--resume', result.stderr)
        self.assertNotIn('Notarized and stapled', result.stdout)
        self.assert_unchanged()
        self.assertTrue((self.state / 'log.json').exists())
        self.assertEqual(self.calls('log')[0][3], REQUEST_ID)

    def test_timeout_retains_id_status_and_does_not_publish(self):
        result = self.invoke(FAKE_WAIT_TIMEOUT='1', FAKE_STATUS='In Progress', NOTARY_WAIT_TIMEOUT='1s')
        self.assertNotEqual(result.returncode, 0)
        self.assert_unchanged()
        self.assertIn(REQUEST_ID, result.stderr)
        self.assertEqual(self.calls('info')[0][3], REQUEST_ID)
        status = json.loads((self.state / 'status.json').read_text())
        self.assertEqual(status['status'], 'In Progress')
        self.assertIn('1s', self.calls('wait')[0])

    def test_existing_ledger_automatically_resumes_without_resubmit(self):
        self.assertNotEqual(self.invoke(FAKE_WAIT_TIMEOUT='1', FAKE_STATUS='In Progress').returncode, 0)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)
        self.assertEqual(len(self.calls('wait')), 2)
        self.assertTrue(all(call[3] == REQUEST_ID for call in self.calls('wait')))
        # Even after publication the exact original payload remains resumable.
        result = self.invoke('--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)

    def test_explicit_resume_requires_ledger(self):
        result = self.invoke('--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('existing local ledger', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assert_unchanged()

    def test_changed_zip_is_rejected_without_resubmitting(self):
        self.invoke(FAKE_STATUS='In Progress')
        self.archive.write_bytes(self.original_zip + b'fresh rebuild')
        result = self.invoke('--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Release ZIP changed', result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)
        self.assertEqual(len(self.calls('wait')), 1)

    def test_changed_app_is_rejected_without_resubmitting(self):
        self.invoke(FAKE_STATUS='In Progress')
        (self.app / 'Contents/new-signature').write_text('freshly signed')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Release app changed', result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)

    def test_frozen_upload_corruption_is_rejected(self):
        self.invoke(FAKE_STATUS='In Progress')
        with (self.state / 'upload.zip').open('ab') as stream:
            stream.write(b'changed')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('upload.zip hash differs', result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)

    def test_rejects_ad_hoc_nested_ad_hoc_missing_runtime_timestamp_team(self):
        for signature in ('adhoc', 'nested-adhoc', 'runtime', 'timestamp', 'team'):
            with self.subTest(signature=signature):
                result = self.invoke(FAKE_SIGNATURE=signature)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls('submit'), [])
                self.assert_unchanged()

    def test_rejects_metadata_signature_and_architecture(self):
        self.metadata['CFBundleVersion'] = '2'
        self.write_metadata()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('metadata mismatch', result.stderr)
        self.assertEqual(self.calls('submit'), [])
        self.metadata['CFBundleVersion'] = '3'
        self.write_metadata()
        for env in ({'FAKE_VERIFY_FAIL': '1'}, {'FAKE_ARCH': 'x86_64'}, {'FAKE_ARCH': 'arm64 x86_64'}):
            with self.subTest(env=env):
                result = self.invoke(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls('submit'), [])
                self.assert_unchanged()

    def test_profile_and_keychain_arguments_without_passwords(self):
        profile = 'CI existing profile with spaces'
        keychain = str(self.root / 'keychain with spaces.keychain-db')
        result = self.invoke(NOTARY_KEYCHAIN_PROFILE=profile, NOTARY_KEYCHAIN_PATH=keychain)
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ('submit', 'wait', 'info'):
            command = self.calls(action)[0]
            self.assertEqual(command[command.index('--keychain-profile') + 1], profile)
            self.assertEqual(command[command.index('--keychain') + 1], keychain)
            self.assertNotIn('--password', command)
            self.assertNotIn('--apple-id', command)
        self.assertNotIn(profile, result.stdout + result.stderr)
        self.assertNotIn(keychain, result.stdout + result.stderr)

    def test_default_profile_without_custom_keychain(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ('submit', 'wait', 'info'):
            command = self.calls(action)[0]
            self.assertEqual(command[command.index('--keychain-profile') + 1], 'rp-steuer-app')
            self.assertNotIn('--keychain', command)

    def test_failed_staple_gatekeeper_or_reextracted_ticket_never_publishes(self):
        # Each failure is safely resumed with the same request ID, not submitted again.
        for env in ({'FAKE_STAPLE_FAIL': '1'}, {'FAKE_SPCTL_FAIL': '1'}, {'FAKE_EXTRACTED_TICKET_FAIL': '1'}):
            with self.subTest(env=env):
                result = self.invoke(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assert_unchanged()
                self.assertEqual(len(self.calls('submit')), 1)
        result = self.invoke('--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)

    def test_info_failure_never_treats_wait_output_as_accepted(self):
        result = self.invoke(FAKE_INFO_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assert_unchanged()
        self.assertIn(REQUEST_ID, result.stderr)

    def test_uncertain_submit_never_resubmits(self):
        result = self.invoke(FAKE_SUBMIT_NO_ID='1')
        self.assertNotEqual(result.returncode, 0)
        self.assert_unchanged()
        result = self.invoke('--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('do not resubmit', result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)

    def test_changed_version_or_build_cannot_reuse_ledger(self):
        self.invoke(FAKE_STATUS='In Progress')
        (self.root / 'BUILD_NUMBER').write_text('4\n')
        result = self.invoke('--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ledger mismatch: build', result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)

    def test_x86_archive_can_be_checked_without_executing_its_binaries(self):
        other_app = self.root / 'dist/x86_64' / NAME
        other_app.parent.mkdir()
        self.app.rename(other_app)
        other_archive = self.root / 'dist/RP-Steuer-App-1.2.0-x86_64.zip'
        self.archive.rename(other_archive)
        result = subprocess.run(['bash', str(self.root / 'notarize_app.sh'), '--arch', 'x86_64'],
                                env={**self.env, 'FAKE_ARCH': 'x86_64'}, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((other_app / 'Contents/ticket').exists())
        self.assertFalse(any('RPSteuerApp' == call[0] or 'rp-steuer-app-engine' == call[0] for call in self.calls()))

    def test_input_archive_must_match_the_generated_app(self):
        # Both objects have good metadata/signatures, but are different builds.
        (self.app / 'Contents/extra').write_text('different build')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Input ZIP app differs', result.stderr)
        self.assertEqual(self.calls('submit'), [])
        self.assertEqual(self.archive.read_bytes(), self.original_zip)

    def test_recovers_response_persisted_before_ledger_id_update(self):
        self.invoke(FAKE_STATUS='In Progress')
        path = self.state / 'ledger.json'
        ledger = json.loads(path.read_text())
        ledger['id'] = None
        path.write_text(json.dumps(ledger))
        result = self.invoke('--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('submit')), 1)
        self.assertEqual(json.loads(path.read_text())['id'], REQUEST_ID)

    def test_recovers_interruption_between_app_directory_renames(self):
        self.assertEqual(self.invoke().returncode, 0)
        self.app.rename(self.state / 'previous.app')
        result = self.invoke('--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.app / 'Contents/ticket').exists())
        self.assertEqual(len(self.calls('submit')), 1)

    def test_rejects_escaping_or_traversed_archive_symlinks(self):
        for target, child in (('../../../../escape', False), ('Contents', True)):
            with self.subTest(target=target):
                self.pack_input()
                with zipfile.ZipFile(self.archive, 'a') as stream:
                    info = zipfile.ZipInfo(NAME + '/link')
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    stream.writestr(info, target)
                    if child:
                        stream.writestr(NAME + '/link/written-through-link', 'unsafe')
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('symlink', result.stderr)
                self.assertEqual(self.calls('submit'), [])

    def test_no_unsafe_zip_extraction(self):
        with zipfile.ZipFile(self.archive, 'a') as stream:
            stream.writestr('../escape', 'unsafe')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe ZIP path', result.stderr)
        self.assertEqual(self.calls('submit'), [])


if __name__ == '__main__':
    unittest.main()
