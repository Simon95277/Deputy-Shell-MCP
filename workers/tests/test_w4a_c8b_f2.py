from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker_v1 import production
from worker_v1.production import ProductionRunEngine


class F2InterpreterTests(unittest.TestCase):
    def test_i1_builder_uses_trusted_venv_from_non_venv_process(self):
        command = production._build_production_worker_command(Path(tempfile.mkdtemp()), "internal")
        self.assertEqual(command[0], str(Path(production.__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe"))

    def test_i2_builder_does_not_use_sys_executable(self):
        trusted = str(Path(production.__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe")
        fake_caller = r"C:\caller-runtime\python.exe"
        with mock.patch.object(production.sys, "executable", fake_caller):
            command = production._build_production_worker_command(Path(tempfile.mkdtemp()), "internal")
        self.assertEqual(command[0], trusted)
        self.assertNotEqual(command[0], fake_caller)

    def test_i3_caller_cannot_override_interpreter(self):
        with self.assertRaises(TypeError):
            production._build_production_worker_command(Path(tempfile.mkdtemp()), "internal", "other-python")

    def test_i4_missing_trusted_interpreter_fails_closed(self):
        with mock.patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "TRUSTED_WORKER_INTERPRETER_UNAVAILABLE"):
                production._build_production_worker_command(Path(tempfile.mkdtemp()), "internal")

    def test_i5_test_only_monkeypatch_can_replace_private_builder(self):
        replacement = ["test-python", "-m", "test-worker"]
        with mock.patch.object(production, "_build_production_worker_command", return_value=replacement):
            self.assertEqual(production._build_production_worker_command(Path("."), "internal"), replacement)

    def test_i6_normal_builder_returns_trusted_interpreter_after_patch_scope(self):
        trusted = str(Path(production.__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe")
        with mock.patch.object(production, "_build_production_worker_command", return_value=["test-python"]):
            pass
        self.assertEqual(production._build_production_worker_command(Path(tempfile.mkdtemp()), "internal")[0], trusted)


if __name__ == "__main__":
    unittest.main()
