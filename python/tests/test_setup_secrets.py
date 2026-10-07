import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings

spec = importlib.util.spec_from_file_location("setup_github_secrets", Path(__file__).resolve().parents[2] / "scripts/setup_github_secrets.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SecretSetupTests(unittest.TestCase):
    def test_values_are_piped_not_in_arguments_environment_or_output(self):
        result = subprocess.CompletedProcess([], 0, b"", b"")
        output = io.StringIO()
        with mock.patch.object(setup, "run", return_value=result) as run, contextlib.redirect_stdout(output):
            setup.set_secret("owner/repo", "DEVELOPER_ID_P12_PASSWORD", "private-password")
        args, kwargs = run.call_args
        self.assertNotIn("private-password", " ".join(args[0]))
        self.assertEqual(kwargs["input"], b"private-password")
        self.assertNotIn("env", kwargs)
        self.assertNotIn("private-password", output.getvalue())
        self.assertIn("DEVELOPER_ID_P12_PASSWORD", output.getvalue())

    def test_unknown_empty_and_failed_secrets_do_not_echo_values(self):
        with self.assertRaises(ValueError):
            setup.set_secret("owner/repo", "UNKNOWN", "secret")
        with self.assertRaises(ValueError):
            setup.set_secret("owner/repo", "APPLE_ID", "")
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 1, b"raw-private-content", b"raw-private-content")):
            with self.assertRaises(ValueError) as error:
                setup.set_secret("owner/repo", "APPLE_ID", "private-value")
            self.assertNotIn("private-value", str(error.exception))
            self.assertNotIn("raw-private-content", str(error.exception))

    def test_public_repository_wrong_repository_and_auth_failure_are_rejected(self):
        for result in [subprocess.CompletedProcess([], 0, '{"nameWithOwner":"owner/repo","isPrivate":false}', ""),
                       subprocess.CompletedProcess([], 0, '{"nameWithOwner":"other/repo","isPrivate":true}', ""),
                       subprocess.CompletedProcess([], 1, "", "error")]:
            with self.subTest(result=result), mock.patch.object(setup, "run", return_value=result):
                with self.assertRaises(ValueError):
                    setup.repository_info("owner/repo")
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 0, '{"nameWithOwner":"owner/repo","isPrivate":true}', "")):
            self.assertEqual(setup.repository_info("owner/repo"), "owner/repo")

    def test_only_single_developer_id_identity_is_default(self):
        output = '1) abc "Apple Development: Name"\n2) xyz "Developer ID Application: Name (ABCDEFGHIJ)"\n'
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
            self.assertEqual(setup.default_identity(), "Developer ID Application: Name (ABCDEFGHIJ)")
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 0, output + output, "")):
            self.assertEqual(setup.default_identity(), "")

    def test_team_identity_must_match(self):
        setup.validate_identity("Developer ID Application: Name (ABCDEFGHIJ)", "ABCDEFGHIJ")
        for identity, team in [("Apple Development: Name (ABCDEFGHIJ)", "ABCDEFGHIJ"),
                               ("Developer ID Application: Name (ABCDEFGHIJ)", "KLMNOPQRST"),
                               ("Developer ID Application: Name (ABCDEFGHIJ)", "short")]:
            with self.subTest(identity=identity, team=team), self.assertRaises(ValueError):
                setup.validate_identity(identity, team)

    def test_p12_must_be_small_nonempty_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            valid = root / "export.p12"
            valid.write_bytes(b"encrypted-test")
            path, data = setup.read_p12(valid, root=project)
            self.assertEqual(path, valid.resolve())
            self.assertEqual(data, b"encrypted-test")
            cases = [project / "secret.p12", root / "empty.p12", root / "big.p12", root / "wrong.txt"]
            for path in cases:
                path.write_bytes(b"x" * (32769 if path.name == "big.p12" else 0 if path.name == "empty.p12" else 3))
                with self.subTest(path=path), self.assertRaises(ValueError):
                    setup.read_p12(path, root=project)

    def test_export_password_validation_uses_stdin_and_generic_error(self):
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            setup.validate_p12(Path("/outside/export.p12"), "export-secret")
        self.assertNotIn("export-secret", " ".join(run.call_args.args[0]))
        self.assertEqual(run.call_args.kwargs["input"], b"export-secret\n")
        for password in ["", "bad\npassword", "bad\rpassword"]:
            with self.assertRaises(ValueError):
                setup.validate_p12(Path("/outside/export.p12"), password)
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 1, b"secret-output", b"secret-output")):
            with self.assertRaises(ValueError) as error:
                setup.validate_p12(Path("/outside/export.p12"), "export-secret")
            self.assertNotIn("secret", str(error.exception))

    def test_noninteractive_setup_refuses_before_any_credentials_or_exports(self):
        with mock.patch.object(setup.sys.stdin, "isatty", return_value=False), mock.patch.object(setup, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                setup.main([])
        run.assert_not_called()

    def test_hidden_input_never_falls_back_to_echo(self):
        def warning(_):
            warnings.warn("would echo", setup.getpass.GetPassWarning)
            self.fail("Must not reach echoed input")
        with mock.patch.object(setup.getpass, "getpass", side_effect=warning), self.assertRaises(ValueError):
            setup.secret_prompt("Password: ")

    @contextlib.contextmanager
    def setup_session(self, ci_confirmation, repository_confirmation):
        output = io.StringIO()
        output.isatty = lambda: True
        with mock.patch.object(setup.sys.stdin, "isatty", return_value=True), mock.patch.object(setup.sys.stderr, "isatty", return_value=True), \
             mock.patch.object(setup, "repository_info", return_value="owner/repo"), \
             mock.patch.object(setup, "read_p12", return_value=(Path("/outside/export.p12"), b"bytes")), \
             mock.patch.object(setup, "validate_p12"), mock.patch.object(setup, "default_identity", return_value="Developer ID Application: Name (ABCDEFGHIJ)"), \
             mock.patch.object(setup, "secret_prompt", side_effect=["p12-password", "app-password"]), \
             mock.patch.object(setup, "prompt", side_effect=["/outside/export.p12", "Developer ID Application: Name (ABCDEFGHIJ)", "ABCDEFGHIJ", "name@example.com", ci_confirmation, repository_confirmation]), \
             mock.patch.object(setup, "set_secret") as upload, mock.patch.object(setup, "set_ci_approval") as approval, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            yield upload, approval, output

    def test_ci_and_repository_confirmation_are_required_before_upload(self):
        for ci, repository in [("NO", "owner/repo"), ("CI-FREIGABE", "NO")]:
            with self.subTest(ci=ci, repository=repository), self.setup_session(ci, repository) as (upload, approval, _):
                self.assertEqual(setup.main(["--repo", "owner/repo"]), 1)
                upload.assert_not_called()
                approval.assert_not_called()

    def test_success_uploads_six_secrets_and_enables_ci_only_at_the_end(self):
        with self.setup_session("CI-FREIGABE", "owner/repo") as (upload, approval, output):
            self.assertEqual(setup.main(["--repo", "owner/repo"]), 0)
            self.assertEqual(upload.call_count, 6)
            self.assertEqual([call.args[1] for call in upload.call_args_list], list(setup.SECRET_NAMES))
            self.assertEqual(approval.call_args_list, [mock.call("owner/repo", False), mock.call("owner/repo", True)])
            for value in ["p12-password", "app-password", "Ynl0ZXM="]:
                self.assertNotIn(value, output.getvalue())

    def test_failed_partial_upload_leaves_ci_disabled(self):
        with self.setup_session("CI-FREIGABE", "owner/repo") as (upload, approval, _):
            upload.side_effect = [None, ValueError("Upload failed")]
            self.assertEqual(setup.main(["--repo", "owner/repo"]), 1)
            self.assertEqual(approval.call_args_list, [mock.call("owner/repo", False)])

    def test_ci_approval_is_an_explicit_nonsecret_repository_variable(self):
        with mock.patch.object(setup, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            setup.set_ci_approval("owner/repo", True)
        self.assertEqual(run.call_args.args[0], ["gh", "variable", "set", "CI_SECRET_ARGV_APPROVED", "--repo", "owner/repo", "--body", "true"])
