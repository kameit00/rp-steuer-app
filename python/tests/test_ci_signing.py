"""CI signing fault injection using only synthetic data and PATH-local fakes.

No real security/openssl/xcrun tool, keychain, export, or network is used. The
python3 fake simulates the two small inline scripts without executing them.
"""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/ci_signing.sh'
FAKE_TOOL = r'''#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['FAKE_CALLS'], 'a') as stream:
    stream.write(json.dumps([name] + args) + '\n')

def fail():
    # Sensitive command failures must be redirected, not echoed by the helper.
    print('dummy-export-password raw diagnostic', file=sys.stdout)
    print('dummy-notary-password raw diagnostic', file=sys.stderr)
    sys.exit(1)

if name == 'openssl':
    if args != ['rand', '-hex', '32']:
        fail()
    print('a' * 64)
elif name == 'python3':
    source = sys.stdin.read()
    if args[0] == '-':
        if 'base64.b64decode' not in source:
            fail()
        data = base64.b64decode(os.environ['DEVELOPER_ID_P12_BASE64'], validate=True)
        with open(args[1], 'xb') as stream:
            stream.write(data)
    elif args[0] == '-c':
        if os.environ['SIGNING_IDENTITY'] not in source:
            fail()
    else:
        fail()
elif name == 'security':
    action = args[0]
    if action == 'create-keychain':
        Path(args[-1]).write_bytes(b'synthetic placeholder; NOT a keychain')
    elif action == 'import':
        p12 = Path(args[1])
        if not p12.is_file() or (p12.stat().st_mode & 0o777) != 0o600:
            fail()
        if os.environ.get('FAKE_IMPORT_FAIL'):
            fail()
    elif action == 'find-identity':
        print('  1) ' + 'B' * 40 + ' "' + os.environ['SIGNING_IDENTITY'] + '"')
    elif action == 'delete-keychain':
        Path(args[-1]).unlink(missing_ok=True)
    elif action not in ('set-keychain-settings', 'unlock-keychain',
                         'set-key-partition-list', 'list-keychains'):
        fail()
elif name == 'xcrun':
    if args[:2] != ['notarytool', 'store-credentials']:
        fail()
    if os.environ.get('FAKE_NOTARY_FAIL'):
        fail()
else:
    fail()
'''


class CISigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / 'runner-temp'
        self.runner.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env_file = self.root / 'github-env'
        self.env_file.touch()
        self.calls_file = self.root / 'calls.jsonl'
        tools = self.root / 'bin'
        tools.mkdir()
        fake = tools / 'fake'
        fake.write_text(FAKE_TOOL.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1))
        fake.chmod(0o755)
        for name in ('security', 'openssl', 'python3', 'xcrun'):
            (tools / name).symlink_to('fake')
        # Never inherit real developer credentials, keychain paths or test switches.
        self.env = {
            'PATH': str(tools) + os.pathsep + os.defpath,
            'HOME': str(self.home),
            'GITHUB_ACTIONS': 'true',
            'GITHUB_ENV': str(self.env_file),
            'RUNNER_TEMP': str(self.runner),
            'CI_SECRET_ARGV_APPROVED': 'true',
            'DEVELOPER_ID_P12_BASE64': base64.b64encode(b'dummy encrypted P12; not a certificate').decode(),
            'DEVELOPER_ID_P12_PASSWORD': 'dummy-export-password',
            'SIGNING_IDENTITY': 'Developer ID Application: Synthetic Test (ABCDEFGHIJ)',
            'APPLE_TEAM_ID': 'ABCDEFGHIJ',
            'APPLE_ID': 'dummy@example.invalid',
            'APPLE_APP_SPECIFIC_PASSWORD': 'dummy-notary-password',
            'FAKE_CALLS': str(self.calls_file),
        }
        self.signing_dir = self.runner / 'rp-steuer-signing-arm64'
        self.keychain = self.signing_dir / 'signing.keychain-db'
        self.p12 = self.signing_dir / 'developer-id.p12'

    def invoke(self, command='setup', distribution='notarized', **env):
        args = ['/bin/bash', '-x', str(SCRIPT), command, '--arch', 'arm64']
        if command == 'setup':
            args += ['--distribution', distribution]
        result = subprocess.run(args, env={**self.env, **env}, capture_output=True, text=True, timeout=30)
        # Script must disable inherited xtrace before touching even dummy credentials.
        for secret in ('dummy-export-password', 'dummy-notary-password', 'dummy@example.invalid',
                       self.env['DEVELOPER_ID_P12_BASE64']):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def calls(self, name=None):
        calls = [json.loads(line) for line in self.calls_file.read_text().splitlines()] if self.calls_file.exists() else []
        return [call for call in calls if call[0] == name] if name else calls

    def test_notarized_credentials_are_scoped_only_to_temporary_keychain(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.p12.exists())
        self.assertEqual(stat.S_IMODE(self.signing_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.keychain.stat().st_mode), 0o600)
        self.assertEqual(self.env_file.read_text(),
                         'NOTARY_KEYCHAIN_PROFILE=rp-steuer-app-ci\n'
                         f'NOTARY_KEYCHAIN_PATH={self.keychain}\n')
        security = self.calls('security')
        self.assertEqual([call[1] for call in security], [
            'create-keychain', 'set-keychain-settings', 'unlock-keychain', 'import',
            'set-key-partition-list', 'list-keychains', 'find-identity'])
        for call in security:
            if call[1] == 'import':
                self.assertEqual(call[call.index('-k') + 1], str(self.keychain))
                self.assertEqual(call[2], str(self.p12))
                self.assertEqual(call[call.index('-T') + 1], '/usr/bin/codesign')
            elif call[1] == 'list-keychains':
                # Search-list inclusion is not permission modification of login.
                self.assertEqual(call[2:], ['-d', 'user', '-s', str(self.keychain),
                                           str(self.home / 'Library/Keychains/login.keychain-db')])
            else:
                self.assertEqual(call[-1], str(self.keychain))
            if call[1] != 'list-keychains':
                self.assertNotIn('login.keychain', ' '.join(call))
        notary, = self.calls('xcrun')
        self.assertEqual(notary[1:4], ['notarytool', 'store-credentials', 'rp-steuer-app-ci'])
        self.assertEqual(notary[notary.index('--keychain') + 1], str(self.keychain))
        self.assertEqual(notary[notary.index('--password') + 1], 'dummy-notary-password')
        self.assertEqual(self.calls('openssl'), [['openssl', 'rand', '-hex', '32']])
        self.assertEqual(len(self.calls('python3')), 2)
        self.assertNotIn(self.env['DEVELOPER_ID_P12_BASE64'], str(self.calls()))

    def test_missing_or_nonexact_approval_refuses_before_any_commands(self):
        for value in ('', 'false', 'TRUE', '1', 'true\n'):
            with self.subTest(approval=value):
                result = self.invoke(CI_SECRET_ARGV_APPROVED=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('CI_SECRET_ARGV_APPROVED=true', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.signing_dir.exists())
        self.assertEqual(self.env_file.read_text(), '')

    def test_missing_secrets_refuse_before_any_commands(self):
        for name in ('DEVELOPER_ID_P12_BASE64', 'DEVELOPER_ID_P12_PASSWORD',
                     'SIGNING_IDENTITY', 'APPLE_TEAM_ID', 'APPLE_ID', 'APPLE_APP_SPECIFIC_PASSWORD'):
            with self.subTest(secret=name):
                result = self.invoke(**{name: ''})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Missing required repository secret: ' + name, result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.signing_dir.exists())
        self.assertEqual(self.env_file.read_text(), '')

    def test_import_failure_deletes_temporary_keychain_and_directory(self):
        result = self.invoke(FAKE_IMPORT_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Could not import', result.stderr)
        self.assertFalse(self.signing_dir.exists())
        self.assertEqual(self.calls('security')[-1], ['security', 'delete-keychain', str(self.keychain)])
        self.assertEqual(self.calls('xcrun'), [])
        self.assertEqual(self.env_file.read_text(), '')

    def test_notary_credential_failure_deletes_temporary_keychain_and_directory(self):
        result = self.invoke(FAKE_NOTARY_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Could not validate and store notarization credentials', result.stderr)
        self.assertFalse(self.signing_dir.exists())
        self.assertEqual(self.calls('security')[-1], ['security', 'delete-keychain', str(self.keychain)])
        self.assertEqual(len(self.calls('xcrun')), 1)
        self.assertEqual(self.env_file.read_text(), '')

    def test_cleanup_does_not_require_approval_or_secrets(self):
        self.signing_dir.mkdir()
        self.keychain.write_bytes(b'synthetic keychain placeholder')
        result = self.invoke(command='cleanup', CI_SECRET_ARGV_APPROVED='',
                             DEVELOPER_ID_P12_BASE64='', DEVELOPER_ID_P12_PASSWORD='',
                             SIGNING_IDENTITY='', APPLE_TEAM_ID='', APPLE_ID='',
                             APPLE_APP_SPECIFIC_PASSWORD='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [['security', 'delete-keychain', str(self.keychain)]])
        self.assertFalse(self.signing_dir.exists())
        # Cleanup remains safe and idempotent when setup never ran.
        result = self.invoke(command='cleanup', CI_SECRET_ARGV_APPROVED='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_local_runner_denied_before_calls_for_setup_and_cleanup(self):
        for command in ('setup', 'cleanup'):
            with self.subTest(command=command):
                result = self.invoke(command=command, GITHUB_ACTIONS='false')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('only for GitHub Actions runners', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.signing_dir.exists())

    def test_developer_id_does_not_need_or_store_notary_credentials(self):
        result = self.invoke(distribution='developer-id', APPLE_ID='', APPLE_APP_SPECIFIC_PASSWORD='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('xcrun'), [])
        self.assertFalse(self.p12.exists())
        cleanup = self.invoke(command='cleanup', CI_SECRET_ARGV_APPROVED='')
        self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
        self.assertFalse(self.signing_dir.exists())


if __name__ == '__main__':
    unittest.main()
