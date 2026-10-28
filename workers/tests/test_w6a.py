import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker_v1 import host_ops
from worker_v1.capabilities import validate_job

TEST_SERIAL = "DEPUTY_TEST_DEVICE_001"


class W6ATests(unittest.TestCase):
    def test_registry_scope_and_package_authority(self):
        self.assertEqual(host_ops.IMPLEMENTED & {"ADB_LIST_DEVICES", "ADB_WAIT_FOR_DEVICE", "ADB_QUERY_PROPERTY", "ADB_QUERY_PACKAGE"}, {"ADB_LIST_DEVICES", "ADB_WAIT_FOR_DEVICE", "ADB_QUERY_PROPERTY", "ADB_QUERY_PACKAGE"})
        self.assertTrue(validate_job({"schema":"deputy.worker.job.v1", "repo":{"binding":"deputy-authoritative-v1"}, "steps":[{"id":"p","operation":"ADB_QUERY_PACKAGE","params":{"serial":TEST_SERIAL}}]})["valid"])
        self.assertFalse(validate_job({"schema":"deputy.worker.job.v1", "repo":{"binding":"deputy-authoritative-v1"}, "steps":[{"id":"p","operation":"ADB_QUERY_PACKAGE","params":{"serial":TEST_SERIAL,"package_id":"x"}}]})["valid"])

    def test_fixed_adb_invocation_and_parser(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(host_ops, "_adb_run", return_value={"exit_code":0,"stdout":"List of devices attached\nS device product:p model:m transport_id:1\n","stderr":""}) as run:
            out = host_ops.adb_list_devices({}, Path(d))
        self.assertEqual(out["devices"][0]["serial"], "S")
        self.assertEqual(run.call_args.args[0], ["devices", "-l"])

    def test_package_empty_is_clean_absence(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(host_ops, "_adb_run", return_value={"exit_code":0,"stdout":"","stderr":""}):
            out = host_ops.adb_query_package({"serial":"S"}, Path(d))
        self.assertEqual(out["status"], "PASS")
        self.assertFalse(out["installed"])

    def test_missing_trusted_adb_blocks(self):
        with mock.patch.object(host_ops, "TRUSTED_ADB", Path("C:/missing/adb.exe")):
            out = host_ops.adb_list_devices({}, Path(tempfile.mkdtemp()))
        self.assertEqual(out["reason"], "TRUSTED_ADB_UNAVAILABLE")

    def test_injection_serial_remains_one_argv_element(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(host_ops, "_adb_run", return_value={"exit_code":0,"stdout":"device\n","stderr":""}) as run:
            out = host_ops.adb_wait_for_device({"serial":"S;reboot"}, Path(d))
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(run.call_args.args[0], ["-s", "S;reboot", "get-state"])

    def test_logcat_caps_physical_lines_in_result_and_local_evidence(self):
        lines = "".join(f"line {index}\n" for index in range(36))
        process = mock.Mock(pid=123, returncode=0)
        process.communicate.return_value = (lines, "")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(host_ops, "_adb_ready", return_value=Path("C:/synthetic/adb.exe")), \
                mock.patch.object(host_ops, "child_environment", return_value={}), \
                mock.patch.object(host_ops.subprocess, "Popen", return_value=process) as popen:
            evidence = Path(d)
            out = host_ops.adb_logcat({"serial": "S", "limit": 20}, evidence)
            expected = [f"line {index}" for index in range(16, 36)]
            self.assertEqual(out["status"], "PASS")
            self.assertEqual(out["line_limit"], 20)
            self.assertEqual(out["line_count"], 20)
            self.assertEqual(out["stdout"].splitlines(), expected)
            self.assertEqual((evidence / "adb.stdout.log").read_text(encoding="utf-8").splitlines(), expected)
            self.assertEqual((evidence / "logcat.txt").read_text(encoding="utf-8").splitlines(), expected)
            self.assertEqual(popen.call_args.args[0][1:], ["-s", "S", "logcat", "-b", "main", "-v", "threadtime", "-t", "20"])

    def test_registered_apk_symlink_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            repo = root / "repo"
            repo.mkdir()
            outside = root / "outside.apk"
            outside.write_bytes(b"synthetic outside bytes")
            apk = repo / "app/build/outputs/apk/debug/app-debug.apk"
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b"synthetic registered bytes")
            with mock.patch.object(host_ops, "REPO_ROOT", repo), \
                    mock.patch.object(host_ops, "_adb_run", return_value={"exit_code": 0, "stdout": "Success", "stderr": ""}) as run:
                accepted = host_ops.adb_install({"serial": TEST_SERIAL, "artifact_id": "DEPUTY_DEBUG_APK"}, root / "evidence")
                self.assertEqual(accepted["status"], "PASS")
                self.assertIn(str(apk), run.call_args.args[0])
                apk.unlink()
                try:
                    os.symlink(outside, apk)
                except OSError:
                    self.skipTest("file symlinks unavailable on this host")
                run.reset_mock()
                blocked_install = host_ops.adb_install({"serial": TEST_SERIAL, "artifact_id": "DEPUTY_DEBUG_APK"}, root / "evidence")
                blocked_push = host_ops.adb_push({"serial": TEST_SERIAL, "artifact_id": "DEPUTY_DEBUG_APK"}, root / "evidence")
                self.assertEqual(blocked_install["reason"], "APPROVED_ARTIFACT_UNAVAILABLE")
                self.assertEqual(blocked_push["reason"], "SCOPED_SOURCE_UNAVAILABLE")
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
