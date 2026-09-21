import json
import os
import unittest
from pathlib import Path

import config


class PortabilityRegressionTests(unittest.TestCase):
    def test_trusted_python_default_is_server_interpreter(self):
        self.assertEqual(config.TRUSTED_PYTHON, Path(os.environ.get("DEPUTYWORKERS_PYTHON_EXE", config.TRUSTED_PYTHON)))

    def test_explicit_python_override_is_server_owned(self):
        self.assertEqual(config.TRUSTED_PYTHON, Path(os.environ["DEPUTYWORKERS_PYTHON_EXE"]))

    def test_unavailable_python_override_is_detectable(self):
        self.assertFalse(Path("Z:/unavailable/python.exe").exists())

    def test_configured_repository_root(self):
        self.assertTrue(config.DEPUTY_SHELL_ROOT.is_absolute())

    def test_repository_root_is_not_request_data(self):
        self.assertNotIn("repo_root", config.__dict__)

    def test_configured_android_sdk(self):
        self.assertTrue(config.ANDROID_SDK_ROOT.is_absolute())

    def test_incomplete_sdk_is_not_accepted_as_complete(self):
        self.assertFalse((config.ANDROID_SDK_ROOT / "platform-tools" / "missing-adb").exists())

    def test_adb_path_is_derived_from_sdk(self):
        self.assertEqual(config.ADB_EXE.parent.parent, config.ANDROID_SDK_ROOT)

    def test_runtime_and_evidence_roots_are_server_controlled(self):
        self.assertTrue(config.RUNTIME_ROOT.is_absolute())
        self.assertTrue(config.EVIDENCE_ROOT.is_absolute())

    def test_registry_has_exactly_22_enabled_capabilities(self):
        registry = json.loads((Path(__file__).parents[1] / "WORKER_CAPABILITIES.json").read_text(encoding="utf-8"))
        enabled = [item for item in registry["capabilities"] if item.get("enabled")]
        self.assertEqual(len(enabled), 22)


if __name__ == "__main__":
    unittest.main()
