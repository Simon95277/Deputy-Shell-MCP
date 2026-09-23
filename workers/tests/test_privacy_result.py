from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from worker_v1.privacy import PUBLIC_RESULT_SANITIZER_VERSION, child_environment, public_result


class WorkerPrivacyProjectionTests(unittest.TestCase):
    def test_production_status_is_ready_when_legacy_contract_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            missing_contract = Path(temp) / "synthetic-private-runtime" / "WORKER_CONTRACT.md"
            with patch.object(server, "CONTRACT_PATH", missing_contract):
                result = server.deputy_worker_status()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["production"]["status"], "READY")
        self.assertEqual(result["production"]["operation_count"], 22)
        self.assertEqual(result["legacy_smoke"]["status"], "UNAVAILABLE")
        self.assertEqual(result["legacy_smoke"]["reason_code"], "LEGACY_WORKER_CONTRACT_MISSING")
        self.assertNotIn(str(missing_contract.parent), str(result))
        for key in ("generic_shell", "generic_adb", "generic_adb_shell", "arbitrary_process_execution"):
            self.assertFalse(result["production"][key])

    def test_legacy_smoke_tools_still_fail_closed_without_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            missing_contract = Path(temp) / "synthetic-runtime" / "WORKER_CONTRACT.md"
            with patch.object(server, "CONTRACT_PATH", missing_contract), \
                    patch.object(server.subprocess, "run") as run:
                smoke = server.run_worker_smoke_internal()
                exact = server.run_exact_payload_smoke_internal()
        self.assertEqual(smoke["status"], "BLOCKED")
        self.assertEqual(exact["status"], "BLOCKED")
        run.assert_not_called()
        self.assertNotIn(str(missing_contract.parent), str(smoke) + str(exact))

    def test_legacy_status_is_unavailable_when_hermes_is_absent(self):
        with tempfile.TemporaryDirectory() as temp:
            missing_hermes = Path(temp) / "synthetic-private-runtime" / "hermes.exe"
            with patch.object(server, "verify_contract", return_value={"ok": True, "sha256": "0" * 64}), \
                    patch.object(server, "HERMES_EXE", missing_hermes):
                result = server.deputy_worker_status()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["production"]["operation_count"], 22)
        self.assertEqual(result["legacy_smoke"]["status"], "UNAVAILABLE")
        self.assertEqual(result["legacy_smoke"]["reason_code"], "LEGACY_HERMES_UNAVAILABLE")
        self.assertNotIn(str(missing_hermes.parent), str(result))

    def test_legacy_smoke_tools_still_fail_closed_when_hermes_is_absent(self):
        with tempfile.TemporaryDirectory() as temp:
            missing_hermes = Path(temp) / "synthetic-runtime" / "hermes.exe"
            good_contract = {"ok": True, "sha256": "0" * 64}
            with patch.object(server, "verify_contract", return_value=good_contract), \
                    patch.object(server, "HERMES_EXE", missing_hermes), \
                    patch.object(server, "_direct_hermes") as direct:
                smoke = server.run_worker_smoke_internal()
                exact = server.run_exact_payload_smoke_internal()
        self.assertEqual(smoke["status"], "BLOCKED")
        self.assertEqual(smoke["stage"], "hermes_executable")
        self.assertEqual(exact["status"], "BLOCKED")
        self.assertEqual(exact["stage"], "hermes_executable")
        direct.assert_not_called()

    def test_public_projection_omits_host_paths_process_argv_and_environment(self):
        windows_root = "C:" + chr(92) + "Users" + chr(92) + "SyntheticUser"
        posix_root = "/" + "home/" + "synthetic-user"
        posix_temp = "/" + "tmp/" + "runner/log.txt"
        result = public_result({
            "status": "PASS",
            "repo_root": windows_root + chr(92) + "private-repo",
            "android_sdk": windows_root + chr(92) + "Android" + chr(92) + "Sdk",
            "adb_path": "C:\\Android\\platform-tools\\adb.exe",
            "command": [windows_root + chr(92) + "private-repo" + chr(92) + "gradlew.bat"],
            "pid": 1234,
            "environment": {"CLOUD_SECRET": "synthetic-secret"},
            "stdout_log": windows_root + chr(92) + "runtime" + chr(92) + "runs" + chr(92) + "x.log",
            "stdout": "synthetic device output with sensitive content",
            "stderr": "synthetic error output",
            "note": "source at " + posix_root + "/private-repo/file.py and " + posix_temp,
        })
        serialized = str(result)
        for item in ("SyntheticUser", "private-repo", "Android\\Sdk", "adb.exe", "synthetic-secret", "sensitive content", "synthetic error output", "1234", "runner", "log.txt"):
            self.assertNotIn(item, serialized)
        self.assertIn("[HOST_PATH_REDACTED]", serialized)
        self.assertEqual(result["status"], "PASS")

    def test_path_with_spaces_redacts_whole_value_and_common_credentials(self):
        windows_root = "C:" + chr(92) + "Users" + chr(92) + "Synthetic User" + chr(92) + "private repo"
        posix_root = "/home/synthetic user/private repo"
        windows_forward = "D:/Users/Synthetic User/Android SDK"
        token = "sk" + "-proj-" + "A" * 32
        result = public_result({"note": "Windows: " + windows_root + "; POSIX: " + posix_root,
                                "sdk": windows_forward,
                                "detail": "credential=" + token})
        serialized = str(result)
        self.assertEqual(result["note"], "[HOST_PATH_REDACTED]")
        self.assertNotIn("Synthetic User", serialized)
        self.assertNotIn("synthetic user", serialized)
        self.assertNotIn("private repo", serialized)
        self.assertNotIn("Android SDK", serialized)
        self.assertNotIn(token, serialized)
        self.assertEqual(result["detail"], "credential=[REDACTED_CREDENTIAL]")
        self.assertEqual(result["sdk"], "[HOST_PATH_REDACTED]")

    def test_public_projection_keeps_bounded_typed_result_and_caller_serial(self):
        result = public_result({"status": "PASS", "serial": "SERIAL_TEST", "operation": "ADB_QUERY_PACKAGE",
                                "package_present": True, "duration_ms": 2})
        self.assertEqual(result["serial"], "SERIAL_TEST")
        self.assertTrue(result["package_present"])

    def test_public_projection_redacts_credentials_and_raw_exception_text(self):
        fixture = "ghp" + "_" + "S" * 28
        host_path = "C:" + chr(92) + "Users" + chr(92) + "SyntheticUser" + chr(92) + "private-repo"
        result = public_result({"error": "failed at " + host_path + " " + fixture,
                                "reason": "ADB_START_FAILED"})
        self.assertEqual(result["error"], "OPERATION_ERROR")
        self.assertNotIn(fixture, str(result))
        self.assertEqual(result["reason"], "ADB_START_FAILED")

    def test_child_environment_excludes_credentials_git_and_ssh_values(self):
        values = {
            "PATH": "C:\\Windows\\System32", "SystemRoot": "C:\\Windows",
            "AWS_SECRET_ACCESS_KEY": "synthetic-cloud-secret", "GIT_DIR": "C:\\private\\.git",
            "GITHUB_TOKEN": "synthetic-gh-token", "SSH_AUTH_SOCK": "synthetic-socket",
            "DEPUTYWORKERS_RUNTIME_ROOT": "C:\\runtime",
        }
        with patch.dict(os.environ, values, clear=True):
            env = child_environment(include_worker_config=True)
        self.assertEqual(env["PATH"], values["PATH"])
        system_root_key = next(key for key in env if key.upper() == "SYSTEMROOT")
        self.assertEqual(env[system_root_key], values["SystemRoot"])
        self.assertEqual(env["DEPUTYWORKERS_RUNTIME_ROOT"], values["DEPUTYWORKERS_RUNTIME_ROOT"])
        for name in ("AWS_SECRET_ACCESS_KEY", "GIT_DIR", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
            self.assertNotIn(name, env)
        self.assertEqual(PUBLIC_RESULT_SANITIZER_VERSION, "DA-PUBLIC-RESULT-SANITIZER-1")


if __name__ == "__main__":
    unittest.main()
