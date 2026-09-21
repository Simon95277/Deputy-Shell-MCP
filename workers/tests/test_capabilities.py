import json
import hashlib
import os
import socket
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from worker_v1.capabilities import REGISTRY_PATH, load_registry, validate_job

TEST_SERIAL = "DEPUTY_TEST_DEVICE_001"


def job(*steps):
    return {"schema": "deputy.worker.job.v1", "repo": {"binding": "deputy-authoritative-v1"}, "steps": list(steps)}


def step(i, operation, params):
    return {"id": i, "operation": operation, "params": params}


class CapabilityValidationTests(unittest.TestCase):
    def assert_invalid(self, value, code=None, registry_path=REGISTRY_PATH):
        result = validate_job(value, registry_path)
        self.assertFalse(result["valid"], result)
        if code:
            self.assertIn(code, {e["code"] for e in result["errors"]})

    def test_registry_is_frozen_and_self_consistent(self):
        registry = load_registry()
        self.assertEqual(len(registry), 22)
        self.assertEqual(registry["GRADLE"]["implementation"], "IMPLEMENTED")

    def test_positive_validation_cases(self):
        cases = [
            job(step("s1", "CAPTURE_REPO_STATE", {})),
            job(step("s1", "CAPTURE_REPO_STATE", {}), step("s2", "GIT_DIFF_CHECK", {})),
            job(step("s1", "CHECK_FILE", {"path": "app/build.gradle.kts"}), step("s2", "HASH_ARTIFACT", {"path": "app/build.gradle.kts"})),
            job(step("s1", "ADB_QUERY_PROPERTY", {"serial": TEST_SERIAL, "property": "ro.build.version.sdk"})),
            job(step("s1", "ADB_WAIT_FOR_DEVICE", {"serial": TEST_SERIAL})),
        ]
        for value in cases:
            self.assertTrue(validate_job(value)["valid"], value)

    def test_forbidden_and_malformed_jobs_fail_closed(self):
        invalid = [
            job(step("s1", "CAPTURE_REPO_STATE", {"command": "dir"})),
            job(step("s1", "CAPTURE_REPO_STATE", {"argv": ["x"]})),
            job(step("s1", "CHECK_FILE", {"path": "C:\\secret.txt"})),
            job(step("s1", "CHECK_FILE", {"path": "../escape"})),
            job(step("s1", "CHECK_FILE", {"path": "\\\\server\\share"})),
            job(step("s1", "CHECK_FILE", {})),
            job(step("s1", "ADB_QUERY_PROPERTY", {"serial": TEST_SERIAL})),
            job(step("s1", "ADB_QUERY_PROPERTY", {"serial": 3, "property": "ro.build.version.sdk"})),
            job(step("s1", "ADB_QUERY_PACKAGE", {"serial": TEST_SERIAL, "package_id": "com.example"})),
            job(step("s1", "GRADLE", {"task_id": "assembleDebug"})),
            job(step("s1", "RUN_APPROVED_VERIFIER", {"verifier_id": "v1"})),
            job(step("s1", "ADB_START_DEPUTY_ACTIVITY", {"serial": TEST_SERIAL, "activity_id": "x"})),
            job(step("s1", "ADB_INSTRUMENT", {"serial": TEST_SERIAL, "runner_id": "x"})),
            {"schema": "deputy.worker.job.v9", "repo": {"binding": "deputy-authoritative-v1"}, "steps": []},
            job(step("same", "CAPTURE_REPO_STATE", {}), step("same", "GIT_DIFF_CHECK", {})),
            job(step("s1", "DELETE_FILE", {})),
            job(step("s1", "GIT_RESET", {})),
            job(step("s1", "CAPTURE_REPO_STATE", {"env": {"X": "Y"}})),
            job(step("s1", "CAPTURE_REPO_STATE", {"api_key": "secret"})),
            job(step("s1", "CAPTURE_REPO_STATE", {"url": "https://example.invalid"})),
        ]
        for value in invalid:
            self.assert_invalid(value)
        self.assert_invalid(job(*[step(str(i), "CAPTURE_REPO_STATE", {}) for i in range(33)]), "STEP_COUNT")

    def test_registry_fail_closed_without_touching_production(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "registry.json"
            p.write_text("{", encoding="utf-8")
            self.assert_invalid(job(step("s1", "CAPTURE_REPO_STATE", {})), "REGISTRY_INVALID", p)
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            data["version"] = 99
            p.write_text(json.dumps(data), encoding="utf-8")
            self.assert_invalid(job(step("s1", "CAPTURE_REPO_STATE", {})), "REGISTRY_UNSUPPORTED_VERSION", p)

    def test_validation_only_has_no_execution_side_effect(self):
        result = validate_job(job(step("s1", "CAPTURE_REPO_STATE", {})))
        self.assertTrue(result["valid"])
        self.assertIsNone(result.get("execution"))

    def test_p1_single_allowed_operation(self):
        self.assertTrue(validate_job(job(step("p1", "CAPTURE_REPO_STATE", {})))["valid"])

    def test_p2_two_host_operations(self):
        self.assertTrue(validate_job(job(step("p1", "CAPTURE_REPO_STATE", {}), step("p2", "GIT_DIFF_CHECK", {})))["valid"])

    def test_p3_reordered_valid_operations(self):
        self.assertTrue(validate_job(job(step("p1", "GIT_DIFF_CHECK", {}), step("p2", "CAPTURE_REPO_STATE", {})))["valid"])

    def test_p4_valid_repo_relative_path(self):
        self.assertTrue(validate_job(job(step("p4", "CHECK_FILE", {"path": "app/build.gradle.kts"})))["valid"])

    def test_p5_valid_explicit_device_serial(self):
        self.assertTrue(validate_job(job(step("p5", "ADB_QUERY_PROPERTY", {"serial": TEST_SERIAL, "property": "ro.build.version.sdk"})))["valid"])

    def _invalid_step(self, operation, params=None):
        self.assert_invalid(job(step("n", operation, {} if params is None else params)))

    def test_n1_unknown_operation(self): self._invalid_step("UNKNOWN_OPERATION")
    def test_n2_run_shell(self): self._invalid_step("RUN_SHELL")
    def test_n3_caller_controlled_executable(self): self._invalid_step("CAPTURE_REPO_STATE", {"executable": "x"})
    def test_n4_shell_command(self): self._invalid_step("CAPTURE_REPO_STATE", {"shell_command": "x"})
    def test_n5_argv_injection(self): self._invalid_step("CAPTURE_REPO_STATE", {"argv": ["x"]})
    def test_n6_powershell_cmd(self): self._invalid_step("CAPTURE_REPO_STATE", {"powershell": "x"})
    def test_n7_absolute_host_path(self): self._invalid_step("CHECK_FILE", {"path": "C:\\x"})
    def test_n8_parent_escape(self): self._invalid_step("CHECK_FILE", {"path": "../x"})
    def test_n9_unc_path(self): self._invalid_step("CHECK_FILE", {"path": "\\\\server\\share"})
    def test_n10_drive_qualified_path(self): self._invalid_step("CHECK_FILE", {"path": "C:x"})
    def test_n11_unknown_parameter(self): self._invalid_step("CAPTURE_REPO_STATE", {"x": 1})
    def test_n12_missing_required_parameter(self): self._invalid_step("CHECK_FILE", {})
    def test_n13_wrong_parameter_type(self): self._invalid_step("ADB_QUERY_PROPERTY", {"serial": 1, "property": "ro.build.version.sdk"})
    def test_n14_oversized_string(self): self._invalid_step("CHECK_FILE", {"path": "a" * 513})
    def test_n15_excessive_step_count(self): self.assert_invalid(job(*[step(str(i), "CAPTURE_REPO_STATE", {}) for i in range(33)]))
    def test_n16_duplicate_step_id(self): self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {}), step("x", "GIT_DIFF_CHECK", {})))
    def test_n17_unsupported_job_schema(self): self.assert_invalid({"schema": "deputy.worker.job.v99", "repo": {"binding": "deputy-authoritative-v1"}, "steps": []})
    def test_n18_environment_map(self): self._invalid_step("CAPTURE_REPO_STATE", {"environment": {"x": "y"}})
    def test_n19_credentials(self): self._invalid_step("CAPTURE_REPO_STATE", {"token": "x"})
    def test_n20_url_network(self): self._invalid_step("CAPTURE_REPO_STATE", {"endpoint": "https://x"})
    def test_n21_adb_shell_args(self): self._invalid_step("ADB_LIST_DEVICES", {"adb_args": ["shell"]})
    def test_n22_arbitrary_package_target(self): self._invalid_step("ADB_QUERY_PACKAGE", {"serial": TEST_SERIAL, "package_id": "com.example"})
    def test_n23_unapproved_gradle_task(self): self._invalid_step("GRADLE", {"task_id": "assembleDebug"})
    def test_n24_unapproved_verifier(self): self._invalid_step("RUN_APPROVED_VERIFIER", {"verifier_id": "v1"})
    def test_n25_delete_file(self): self._invalid_step("DELETE_FILE")
    def test_n26_git_mutation(self): self._invalid_step("GIT_RESET")

    def _registry_fixture(self, mutate):
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        mutate(data)
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f); f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name

    def test_n27_malformed_registry(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("{"); path=f.name
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {})), "REGISTRY_INVALID", path)

    def test_n28_missing_registry(self):
        with tempfile.TemporaryDirectory() as d:
            self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {})), "REGISTRY_INVALID", Path(d) / "missing.json")

    def test_n29_duplicate_registry_operation(self):
        path=self._registry_fixture(lambda d: d["capabilities"].__setitem__(1, d["capabilities"][0].copy()))
        self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {})), "REGISTRY_DUPLICATE_OR_UNKNOWN_OPERATION", path)

    def test_n30_unsupported_registry_version(self):
        path=self._registry_fixture(lambda d: d.__setitem__("version", 99))
        self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {})), "REGISTRY_UNSUPPORTED_VERSION", path)

    def test_r1_invalid_registry_family(self):
        path=self._registry_fixture(lambda d: d["capabilities"][0].__setitem__("family", "SHELL"))
        self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {})), "REGISTRY_INVALID_METADATA", path)

    def test_r2_unresolved_parameter_schema(self):
        path=self._registry_fixture(lambda d: d["capabilities"][0].__setitem__("params_schema", "missing.v1"))
        self.assert_invalid(job(step("x", "CAPTURE_REPO_STATE", {})), "UNRESOLVED_PARAMETER_SCHEMA", path)

    def test_u1_unknown_top_level_field(self): self.assert_invalid({"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":[],"x":1})
    def test_u2_unknown_step_field(self): self.assert_invalid(job({"id":"x","operation":"CAPTURE_REPO_STATE","params":{},"x":1}))
    def test_u3_unknown_params_field(self): self._invalid_step("CAPTURE_REPO_STATE", {"x": 1})

    def test_path1_relative(self): self.test_p4_valid_repo_relative_path()
    def test_path2_absolute(self): self.test_n7_absolute_host_path()
    def test_path3_drive_qualified(self): self.test_n10_drive_qualified_path()
    def test_path4_unc(self): self.test_n9_unc_path()
    def test_path5_parent_escape(self): self.test_n8_parent_escape()
    def test_path6_normalized_contained(self): self.assertTrue(validate_job(job(step("x", "CHECK_FILE", {"path": "app\\build.gradle.kts"})))["valid"])

    def test_side_effect_guard_for_validation(self):
        def blocked(*args, **kwargs): raise AssertionError("validation attempted execution/network")
        with mock.patch.multiple(subprocess, Popen=blocked, run=blocked, call=blocked, check_call=blocked, check_output=blocked), mock.patch.object(os, "system", blocked), mock.patch.object(socket, "socket", blocked), mock.patch.object(socket, "create_connection", blocked):
            self.assertTrue(validate_job(job(step("x", "CAPTURE_REPO_STATE", {})))["valid"])
            self.assertFalse(validate_job(job(step("x", "ADB_LIST_DEVICES", {"adb_args": []})))["valid"])

    def test_production_job_has_no_execution_barrier(self):
        self.assertTrue(validate_job(job(step("x", "CAPTURE_REPO_STATE", {})))["valid"])


if __name__ == "__main__":
    unittest.main()
