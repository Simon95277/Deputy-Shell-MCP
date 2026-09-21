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


if __name__ == "__main__":
    unittest.main()
