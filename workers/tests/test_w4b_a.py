from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker_v1 import host_ops, production
from worker_v1.capabilities import validate_job


def job(*steps):
    return {"schema": "deputy.worker.job.v1", "repo": {"binding": "deputy-authoritative-v1"}, "steps": list(steps)}


def step(i, operation="GRADLE", params=None):
    return {"id": i, "operation": operation, "params": params or {}}


class FakeProcess:
    pid = 1234
    returncode = 0

    def communicate(self):
        return "fixture stdout", "fixture stderr"


class W4BATests(unittest.TestCase):
    def valid(self, *steps):
        return validate_job(job(*steps))["valid"]

    def test_ga01_approved_id_resolves(self):
        self.assertEqual(host_ops.APPROVED_GRADLE_TASKS["VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"], "verifyExecutionSubstrateValidationManifestIsolation")

    def test_ga02_unknown_id_rejected(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "UNKNOWN"})))

    def test_ga03_raw_task_rejected(self):
        self.assertFalse(self.valid(step("g", params={"task": "verifyExecutionSubstrateValidationManifestIsolation"})))

    def test_ga04_argv_rejected(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION", "argv": ["x"]})))

    def test_ga05_executable_rejected(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION", "executable": "x"})))

    def test_ga06_cwd_override_rejected(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION", "cwd": "x"})))

    def test_ga07_environment_override_rejected(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION", "environment": {}})))

    def test_ga08_fixed_wrapper_used(self):
        self.assertEqual(host_ops.GRADLE_WRAPPER, host_ops.REPO_ROOT / "gradlew.bat")

    def test_ga09_direct_process_no_shell(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()) as popen, tempfile.TemporaryDirectory() as d:
            host_ops.gradle({"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}, Path(d))
            self.assertFalse(popen.call_args.kwargs["shell"])

    def test_ga10_zero_exit_pass(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(host_ops.gradle({"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}, Path(d))["status"], "PASS")

    def test_ga11_nonzero_exit_fail(self):
        p = FakeProcess(); p.returncode = 7
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=p):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(host_ops.gradle({"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}, Path(d))["status"], "FAIL")

    def test_ga12_wrapper_unavailable_blocked(self):
        with mock.patch.object(host_ops.Path, "is_file", return_value=False):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(host_ops.gradle({"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}, Path(d))["status"], "BLOCKED")

    def test_ga13_logs_persisted_bounded(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()):
            with tempfile.TemporaryDirectory() as d:
                out = host_ops.gradle({"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}, Path(d))
                self.assertTrue(Path(out["stdout_log"]).is_file()); self.assertTrue(Path(out["stderr_log"]).is_file())
                self.assertLessEqual(len(out["stdout"]), host_ops.MAX_GRADLE_OUTPUT)

    def test_ga14_valid_gradle_step_is_composable(self):
        self.assertTrue(self.valid(step("g", params={"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}), step("f", "CHECK_FILE", {"path": "app/build.gradle.kts"})))

    def test_ga15_invalid_gradle_is_rejected_preflight(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "UNKNOWN"}), step("f", "CHECK_FILE", {"path": "app/build.gradle.kts"})))

    def test_ga16_mixed_unimplemented_rejected_preflight(self):
        from worker_v1.production import ProductionRunEngine
        with tempfile.TemporaryDirectory() as d:
            out = ProductionRunEngine(Path(d)).start(job(step("g"), step("v", "RUN_APPROVED_VERIFIER", {"verifier_id": "x"})))
            self.assertEqual(out["status"], "REJECTED")

    def test_ga17_cancellation_api_exists_for_owned_tree(self):
        self.assertTrue(callable(production.ProductionRunEngine.cancel))

    def test_ga18_job_schema_has_no_gradle_command_fields(self):
        self.assertFalse(self.valid(step("g", params={"task_id": "VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION", "command": "x"})))

    def test_ga19_active_ownership_is_engine_managed(self):
        self.assertTrue(hasattr(production.ProductionRunEngine, "_release_active_if_owned"))

    def test_ga20_repo_binding_is_fixed(self):
        self.assertFalse(validate_job({"schema": "deputy.worker.job.v1", "repo": {"binding": "other"}, "steps": [step("g")]})["valid"])


if __name__ == "__main__":
    unittest.main()
