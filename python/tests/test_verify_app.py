import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from verify_app import DEPENDENCIES, MACHO_MAGICS, main, verify_app


class VerifyAppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = self.root / "arm64/RP Steuer App.app"
        self.main_binary = self.app / "Contents/MacOS/RPSteuerApp"
        self.engine = self.app / "Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine"
        self.native(self.main_binary)
        self.native(self.engine)
        self.metadata = {
            "CFBundleIdentifier": "com.relax-pillow.rpsteuerapp",
            "CFBundleDisplayName": "RP Steuer App",
            "CFBundleName": "RP Steuer App",
            "CFBundleExecutable": "RPSteuerApp",
            "CFBundleShortVersionString": "1.1.0",
            "CFBundleVersion": "2",
            "LSMinimumSystemVersion": "14.0",
        }
        self.write_metadata()
        self.arch = "arm64"
        self.architectures = {}
        self.diagnostics = {
            "type": "diagnostics",
            "app": "RP Steuer App",
            "version": "1.1.0",
            "architecture": "arm64",
            "dependencies": dict(DEPENDENCIES),
        }
        mock = patch("verify_app.subprocess.run", side_effect=self.run_command)
        self.run = mock.start()
        self.addCleanup(mock.stop)

    def native(self, path, magic=b"\xcf\xfa\xed\xfe"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(magic + b"synthetic native binary")
        path.chmod(0o755)
        return path

    def write_metadata(self):
        with (self.app / "Contents/Info.plist").open("wb") as stream:
            plistlib.dump(self.metadata, stream)

    def run_command(self, command, **kwargs):
        if command[0] == "/usr/bin/lipo":
            self.assertEqual(command[1], "-archs")
            output = self.architectures.get(command[2], self.arch)
        else:
            self.assertEqual(command, [str(self.engine), "--diagnostics"])
            output = json.dumps(self.diagnostics)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def verify(self, app=None):
        return verify_app(app or self.app, self.arch, "1.1.0", "2")

    def test_valid_both_architectures(self):
        for arch in ("arm64", "x86_64"):
            with self.subTest(arch=arch):
                self.arch = arch
                self.diagnostics["architecture"] = arch
                summary = self.verify()
                self.assertIn(arch, summary)
                self.assertIn("1.1.0 (build 2)", summary)
                self.assertIn("2 Mach-O files", summary)

    def test_all_thin_and_fat_magic_bytes(self):
        for index, magic in enumerate(sorted(MACHO_MAGICS)):
            self.native(self.app / f"Contents/Resources/native-{index}", magic)
        self.assertIn("10 Mach-O files", self.verify())

    def test_universal_binary_contains_requested_architecture(self):
        self.architectures[str(self.main_binary)] = "x86_64 arm64\n"
        self.verify()

    def test_wrong_main_architecture(self):
        self.architectures[str(self.main_binary)] = "x86_64"
        with self.assertRaisesRegex(ValueError, "expected arm64"):
            self.verify()

    def test_mixed_architecture_library_fails(self):
        library = self.native(self.app / "Contents/Resources/numpy/core.so")
        self.architectures[str(library)] = "x86_64"
        with self.assertRaisesRegex(ValueError, "core.so.*expected arm64"):
            self.verify()

    def test_wrong_or_missing_metadata(self):
        for key in tuple(self.metadata):
            original = self.metadata[key]
            for value in ("wrong", None):
                with self.subTest(key=key, value=value):
                    if value is None:
                        del self.metadata[key]
                    else:
                        self.metadata[key] = value
                    self.write_metadata()
                    with self.assertRaisesRegex(ValueError, key):
                        self.verify()
                    self.metadata[key] = original
        self.assertFalse(self.run.called)

    def test_invalid_or_missing_plist(self):
        plist = self.app / "Contents/Info.plist"
        for content in (b"not a plist", b'<?xml version="1.0"?><plist><dict>'):
            with self.subTest(content=content):
                plist.write_bytes(content)
                with self.assertRaisesRegex(ValueError, "Cannot read"):
                    self.verify()
        plist.unlink()
        with self.assertRaisesRegex(ValueError, "Cannot read"):
            self.verify()

    def test_non_dictionary_plist(self):
        with (self.app / "Contents/Info.plist").open("wb") as stream:
            plistlib.dump(["not a dictionary"], stream)
        with self.assertRaisesRegex(ValueError, "dictionary"):
            self.verify()

    def test_missing_executables(self):
        for executable in (self.main_binary, self.engine):
            with self.subTest(path=executable):
                executable.unlink()
                with self.assertRaisesRegex(ValueError, "Missing or non-executable"):
                    self.verify()
                self.native(executable)

    def test_non_executable_binaries(self):
        for executable in (self.main_binary, self.engine):
            with self.subTest(path=executable):
                executable.chmod(0o644)
                with self.assertRaisesRegex(ValueError, "non-executable"):
                    self.verify()
                executable.chmod(0o755)

    def test_main_and_engine_must_be_macho(self):
        for executable in (self.main_binary, self.engine):
            with self.subTest(path=executable):
                executable.write_bytes(b"#!/bin/sh\nexit 0\n")
                with self.assertRaisesRegex(ValueError, "not a Mach-O"):
                    self.verify()
                self.native(executable)

    def test_data_is_not_passed_to_lipo_even_with_native_extension(self):
        data = self.app / "Contents/Resources/not-native.dylib"
        data.write_bytes(b"ordinary data mentioning Mach-O arm64\n")
        (self.app / "Contents/Resources/short-file").write_bytes(b"\xcf\xfa")
        self.verify()
        paths = [call.args[0][-1] for call in self.run.call_args_list if call.args[0][0] == "/usr/bin/lipo"]
        self.assertEqual(set(paths), {str(self.main_binary), str(self.engine)})

    def test_symlinked_app_and_native_file(self):
        alias = self.root / "RP Steuer App.app"
        alias.symlink_to(self.app, target_is_directory=True)
        (self.app / "Contents/Resources/engine-link").symlink_to(self.engine)
        self.assertIn("2 Mach-O files", self.verify(alias))

    def test_symlinked_main_executable(self):
        target = self.main_binary.with_name("native-main")
        self.main_binary.rename(target)
        self.main_binary.symlink_to(target.name)
        self.assertIn("2 Mach-O files", self.verify())

    def test_lipo_failure_is_not_silently_skipped(self):
        self.run.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "malformed Mach-O")
        with self.assertRaisesRegex(ValueError, "malformed Mach-O"):
            self.verify()

    def test_empty_lipo_architectures_fail(self):
        self.architectures[str(self.main_binary)] = ""
        with self.assertRaisesRegex(ValueError, "no architectures"):
            self.verify()

    def test_command_spawn_error_and_timeout(self):
        for error in (OSError("cannot execute"), subprocess.TimeoutExpired("lipo", 60)):
            with self.subTest(error=error):
                self.run.side_effect = error
                with self.assertRaisesRegex(ValueError, "Could not execute"):
                    self.verify()

    def test_engine_failure(self):
        original = self.run_command

        def failed_engine(command, **kwargs):
            if command[0] == "/usr/bin/lipo":
                return original(command, **kwargs)
            return subprocess.CompletedProcess(command, 1, "", "engine failure")

        self.run.side_effect = failed_engine
        with self.assertRaisesRegex(ValueError, "engine failure"):
            self.verify()

    def test_missing_or_wrong_diagnostics_fields(self):
        for key in ("type", "app", "version", "architecture"):
            original = self.diagnostics[key]
            for value in (None, "wrong"):
                with self.subTest(key=key, value=value):
                    if value is None:
                        del self.diagnostics[key]
                    else:
                        self.diagnostics[key] = value
                    with self.assertRaisesRegex(ValueError, f"diagnostics {key}"):
                        self.verify()
                    self.diagnostics[key] = original

    def test_invalid_missing_or_non_object_diagnostics_json(self):
        original = self.run_command
        for output in ("", "not JSON", "[]", "null"):
            with self.subTest(output=output):
                def bad_json(command, **kwargs):
                    if command[0] == "/usr/bin/lipo":
                        return original(command, **kwargs)
                    return subprocess.CompletedProcess(command, 0, output, "")
                self.run.side_effect = bad_json
                with self.assertRaisesRegex(ValueError, "diagnostics"):
                    self.verify()

    def test_dependencies_missing_or_wrong(self):
        for name in DEPENDENCIES:
            original = self.diagnostics["dependencies"][name]
            for value in (None, "0.0.0"):
                with self.subTest(name=name, value=value):
                    if value is None:
                        del self.diagnostics["dependencies"][name]
                    else:
                        self.diagnostics["dependencies"][name] = value
                    with self.assertRaisesRegex(ValueError, f"dependency {name}"):
                        self.verify()
                    self.diagnostics["dependencies"][name] = original
        for value in (None, [], "numpy"):
            self.diagnostics["dependencies"] = value
            with self.assertRaisesRegex(ValueError, "missing dependencies"):
                self.verify()

    def test_engine_environment_is_clean_and_output_captured(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/bad", "PYTHONHOME": "/bad", "DYLD_LIBRARY_PATH": "/bad", "PATH": "/bad"}):
            self.verify()
        engine_call = next(call for call in self.run.call_args_list if call.args[0][0] != "/usr/bin/lipo")
        self.assertEqual(engine_call.kwargs["env"], {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin"})
        self.assertTrue(engine_call.kwargs["capture_output"])
        self.assertTrue(engine_call.kwargs["text"])

    def test_unsupported_architecture(self):
        with self.assertRaisesRegex(ValueError, "Unsupported architecture"):
            verify_app(self.app, "i386", "1.1.0", "2")

    def test_cli_invocation(self):
        with patch("sys.argv", ["verify_app.py", str(self.app), "--arch", "arm64", "--version", "1.1.0", "--build", "2"]), patch("builtins.print") as output:
            self.assertEqual(main(), 0)
        self.assertIn("Verified RP Steuer App", output.call_args.args[0])

    def test_cli_reports_failure(self):
        self.main_binary.unlink()
        with patch("sys.argv", ["verify_app.py", str(self.app), "--arch", "arm64", "--version", "1.1.0", "--build", "2"]), patch("sys.stderr") as stderr:
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        self.assertIn("App verification failed", "".join(call.args[0] for call in stderr.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
