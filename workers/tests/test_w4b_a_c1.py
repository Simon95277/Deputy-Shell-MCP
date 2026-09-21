from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker_v1 import host_ops


class FakeProcess:
    pid = 5678
    returncode = 0

    def communicate(self):
        return "", ""


class SDKBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sdk = Path(self.temp.name) / "Sdk"
        (self.sdk / "platform-tools").mkdir(parents=True)
        (self.sdk / "platform-tools" / "adb.exe").write_bytes(b"")
        for name in ("platforms", "build-tools", "cmdline-tools"):
            (self.sdk / name).mkdir()
        self.patch = mock.patch.object(host_ops, "TRUSTED_ANDROID_SDK", self.sdk)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)

    def run_gradle(self, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()) as popen:
                result = host_ops.gradle({"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}, Path(self.temp.name) / "evidence")
        return result, popen

    def test_sdk01_trusted_root(self):
        self.assertEqual(host_ops.resolve_trusted_android_sdk(), self.sdk.resolve())

    def test_sdk02_caller_cannot_supply_android_home(self):
        result, _ = self.run_gradle({"ANDROID_HOME": "C:\\wrong"})
        self.assertEqual(result["status"], "PASS")

    def test_sdk03_caller_cannot_supply_android_sdk_root(self):
        result, _ = self.run_gradle({"ANDROID_SDK_ROOT": "C:\\wrong"})
        self.assertEqual(result["status"], "PASS")

    def test_sdk04_conflicting_home_does_not_override(self):
        result, popen = self.run_gradle({"ANDROID_HOME": "C:\\wrong"})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(popen.call_args.kwargs["env"]["ANDROID_HOME"], str(self.sdk.resolve()))

    def test_sdk05_conflicting_root_does_not_override(self):
        result, popen = self.run_gradle({"ANDROID_SDK_ROOT": "C:\\wrong"})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(popen.call_args.kwargs["env"]["ANDROID_SDK_ROOT"], str(self.sdk.resolve()))

    def test_sdk06_child_home(self):
        _, popen = self.run_gradle(); self.assertEqual(popen.call_args.kwargs["env"]["ANDROID_HOME"], str(self.sdk.resolve()))

    def test_sdk07_child_root(self):
        _, popen = self.run_gradle(); self.assertEqual(popen.call_args.kwargs["env"]["ANDROID_SDK_ROOT"], str(self.sdk.resolve()))

    def test_sdk08_child_values_match(self):
        _, popen = self.run_gradle(); env = popen.call_args.kwargs["env"]; self.assertEqual(env["ANDROID_HOME"], env["ANDROID_SDK_ROOT"])

    def test_sdk09_missing_fails_closed(self):
        self.sdk.rename(self.sdk.with_name("missing"))
        result, popen = self.run_gradle(); self.assertEqual(result["status"], "BLOCKED"); popen.assert_not_called()

    def test_sdk10_invalid_directory_fails_closed(self):
        for child in self.sdk.iterdir():
            if child.is_dir():
                if child.name == "platform-tools":
                    (child / "adb.exe").unlink()
        result, popen = self.run_gradle(); self.assertEqual(result["status"], "BLOCKED"); popen.assert_not_called()

    def test_sdk11_does_not_create_local_properties(self):
        result, _ = self.run_gradle(); self.assertEqual(result["status"], "PASS"); self.assertFalse((host_ops.REPO_ROOT / "local.properties").exists())

    def test_sdk12_full_environment_is_not_job_configurable(self):
        result, popen = self.run_gradle({"ANDROID_HOME": "C:\\wrong", "ANDROID_SDK_ROOT": "C:\\wrong"})
        self.assertEqual(result["status"], "PASS")
        env = popen.call_args.kwargs["env"]; self.assertEqual(env["ANDROID_HOME"], str(self.sdk.resolve())); self.assertEqual(env["ANDROID_SDK_ROOT"], str(self.sdk.resolve()))


if __name__ == "__main__":
    unittest.main()
