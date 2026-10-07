"""Mock-only guard tests: no GitHub/Apple calls and no real credentials."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    'ci_notary_guard', Path(__file__).resolve().parents[2] / 'scripts/ci_notary_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class CINotaryGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'VERSION').write_text('1.2.0\n')
        self.env_file = self.root / 'github-env'
        self.env_file.touch()
        self.env = {
            'GITHUB_REPOSITORY': 'owner/rp-steuer-app',
            'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_ENV': str(self.env_file),
            'GH_TOKEN': 'dummy-token-never-print',
        }

    def invoke(self, *, names='', error=None, arch='arm64', **env):
        output = io.StringIO()
        result = subprocess.CompletedProcess([], 0, names, '')
        with mock.patch.object(guard, 'ROOT', self.root), \
             mock.patch.dict(os.environ, {**self.env, **env}, clear=True), \
             mock.patch.object(guard.subprocess, 'run', return_value=result, side_effect=error) as run, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = guard.main(['--arch', arch])
        self.assertNotIn(self.env['GH_TOKEN'], output.getvalue())
        return status, output.getvalue(), run

    def test_new_first_attempt_allowed_and_safe_version_recorded(self):
        status, output, run = self.invoke()
        self.assertEqual(status, 0, output)
        self.assertIn('first attempt allowed', output)
        self.assertEqual(self.env_file.read_text(), 'APP_VERSION=1.2.0\n')
        run.assert_called_once_with(
            ['gh', 'api', 'repos/owner/rp-steuer-app/actions/artifacts', '--paginate',
             '--jq', '.artifacts[].name'],
            capture_output=True, text=True, check=True, timeout=60)
        self.assertNotIn(self.env['GH_TOKEN'], str(run.call_args))

    def test_rerun_denied_before_artifact_api_even_without_pending_artifact(self):
        for attempt in ('2', '3', '10000000000000000000000000000000000000'):
            with self.subTest(attempt=attempt):
                status, output, run = self.invoke(GITHUB_RUN_ATTEMPT=attempt)
                self.assertEqual(status, 1)
                self.assertIn('same submission ID', output)
                self.assertIn('docs/SIGNING.md', output)
                run.assert_not_called()

    def test_pending_same_version_arch_denied_including_expired_entries(self):
        # gh selects only names, never filtering on expired=false. Any returned
        # exact name is a blocker, even if the artifact itself is no longer downloadable.
        for arch in ('arm64', 'x86_64'):
            with self.subTest(arch=arch):
                status, output, run = self.invoke(
                    arch=arch, names=f'other-artifact\npending-notarization-1.2.0-{arch}\n')
                self.assertEqual(status, 1)
                self.assertIn('same submission ID', output)
                self.assertIn('pending artifact exists', output)
                self.assertEqual(self.env_file.read_text().splitlines()[-1], 'APP_VERSION=1.2.0')
                self.assertNotIn('expired', str(run.call_args))

    def test_other_version_or_architecture_allowed(self):
        status, output, _ = self.invoke(names=(
            'pending-notarization-1.1.0-arm64\n'
            'pending-notarization-1.2.0-x86_64\n'
            'pending-notarization-1.2.00-arm64\n'))
        self.assertEqual(status, 0, output)

    def test_api_errors_fail_closed_without_echoing_exception_or_token(self):
        sensitive_output = 'dummy-token-never-print raw response must stay hidden'
        errors = [
            subprocess.CalledProcessError(1, ['gh'], output=sensitive_output, stderr=sensitive_output),
            subprocess.TimeoutExpired(['gh'], 60, output=sensitive_output, stderr=sensitive_output),
            OSError(sensitive_output),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                status, output, run = self.invoke(error=error)
                self.assertEqual(status, 1)
                self.assertIn('Could not check previous pending artifacts', output)
                self.assertNotIn('raw response', output)
                run.assert_called_once()

    def test_missing_token_refuses_before_api(self):
        status, _, run = self.invoke(GH_TOKEN='')
        self.assertEqual(status, 1)
        run.assert_not_called()

    def test_invalid_repository_and_attempt_refuse_before_api(self):
        for name, invalid in (
            ('GITHUB_REPOSITORY', ('', '/repo', 'owner/repo/extra', 'owner/../repo',
                                   'owner/repo\nAPP_VERSION=bad', '--arg/repo')),
            ('GITHUB_RUN_ATTEMPT', ('', '0', '01', '-1', '1\n', 'one')),
        ):
            for value in invalid:
                with self.subTest(name=name, value=value):
                    status, _, run = self.invoke(**{name: value})
                    self.assertEqual(status, 1)
                    run.assert_not_called()
        self.assertEqual(self.env_file.read_text(), '')

    def test_version_requires_stable_semver_and_prevents_env_injection(self):
        for version in ('v1.2.0', '01.2.0', '1.2', '1.2.0-rc.1', '1.2.0+build',
                        '1.2.0\nINJECTED=value', ''):
            with self.subTest(version=version):
                (self.root / 'VERSION').write_text(version)
                status, _, run = self.invoke()
                self.assertEqual(status, 1)
                run.assert_not_called()
        self.assertEqual(self.env_file.read_text(), '')

    def test_missing_version_or_env_file_fail_closed(self):
        (self.root / 'VERSION').unlink()
        status, _, run = self.invoke()
        self.assertEqual(status, 1)
        run.assert_not_called()
        (self.root / 'VERSION').write_text('1.2.0\n')
        for value in ('', 'relative-env', str(self.root / 'nonexistent')):
            with self.subTest(env_file=value):
                status, _, run = self.invoke(GITHUB_ENV=value)
                self.assertEqual(status, 1)
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
