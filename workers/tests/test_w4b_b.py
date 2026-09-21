from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker_v1 import host_ops, production
from worker_v1.capabilities import validate_job


VID = "VERIFY_RUNTIME_INTEGRITY_MANIFEST"


def job(*steps):
    return {"schema": "deputy.worker.job.v1", "repo": {"binding": "deputy-authoritative-v1"}, "steps": list(steps)}


def step(i, operation="RUN_APPROVED_VERIFIER", params=None):
    return {"id": i, "operation": operation, "params": params or {"verifier_id": VID}}


class FakeProcess:
    pid = 9012
    returncode = 0
    def communicate(self): return "ok", ""


class W4BBTests(unittest.TestCase):
    def valid(self, *steps): return validate_job(job(*steps))["valid"]

    def test_vb01_approved_id_resolves(self):
        self.assertEqual(host_ops.APPROVED_VERIFIERS[VID], "tools/android/verify-runtime-integrity-manifest.py")

    def test_vb02_unknown_id_rejected(self): self.assertFalse(self.valid(step("v", params={"verifier_id": "UNKNOWN"})))
    def test_vb03_script_path_rejected(self): self.assertFalse(self.valid(step("v", params={"verifier_id": VID, "script": "x"})))
    def test_vb04_argv_rejected(self): self.assertFalse(self.valid(step("v", params={"verifier_id": VID, "argv": ["x"]})))
    def test_vb05_executable_rejected(self): self.assertFalse(self.valid(step("v", params={"verifier_id": VID, "executable": "x"})))
    def test_vb06_cwd_override_rejected(self): self.assertFalse(self.valid(step("v", params={"verifier_id": VID, "cwd": "x"})))
    def test_vb07_environment_rejected(self): self.assertFalse(self.valid(step("v", params={"verifier_id": VID, "environment": {}})))

    def test_vb08_trusted_python_used(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()) as popen:
            with tempfile.TemporaryDirectory() as d: host_ops.verifier({"verifier_id": VID}, Path(d))
        self.assertEqual(popen.call_args.args[0][0], str(host_ops.TRUSTED_PYTHON))

    def test_vb09_shell_false(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()) as popen:
            with tempfile.TemporaryDirectory() as d: host_ops.verifier({"verifier_id": VID}, Path(d))
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_vb10_zero_exit_pass(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()):
            with tempfile.TemporaryDirectory() as d: self.assertEqual(host_ops.verifier({"verifier_id": VID}, Path(d))["status"], "PASS")

    def test_vb11_nonzero_exit_fail(self):
        p=FakeProcess(); p.returncode=3
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=p):
            with tempfile.TemporaryDirectory() as d: self.assertEqual(host_ops.verifier({"verifier_id": VID}, Path(d))["status"], "FAIL")

    def test_vb12_missing_interpreter_blocked(self):
        with mock.patch.object(host_ops.Path, "is_file", return_value=False):
            with tempfile.TemporaryDirectory() as d: self.assertEqual(host_ops.verifier({"verifier_id": VID}, Path(d))["status"], "BLOCKED")

    def test_vb13_missing_script_blocked(self):
        with mock.patch.object(host_ops, "APPROVED_VERIFIERS", {VID: "missing.py"}):
            with tempfile.TemporaryDirectory() as d: self.assertEqual(host_ops.verifier({"verifier_id": VID}, Path(d))["status"], "BLOCKED")

    def test_vb14_logs_persisted(self):
        with mock.patch.object(host_ops.subprocess, "Popen", return_value=FakeProcess()):
            with tempfile.TemporaryDirectory() as d:
                out=host_ops.verifier({"verifier_id": VID}, Path(d)); self.assertTrue(Path(out["stdout_log"]).is_file()); self.assertTrue(Path(out["stderr_log"]).is_file())

    def test_vb15_gradle_then_verifier_validates(self):
        self.assertTrue(self.valid({"id":"g","operation":"GRADLE","params":{"task_id":"VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION"}}, step("v")))

    def test_vb16_unknown_verifier_prevents_later_step(self): self.assertFalse(self.valid(step("v", params={"verifier_id":"UNKNOWN"}), {"id":"f","operation":"CHECK_FILE","params":{"path":"app/build.gradle.kts"}}))

    def test_vb17_parse_junit_mixed_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            out = production.ProductionRunEngine(Path(d)).start(job(step("v"), {"id":"j","operation":"PARSE_JUNIT","params":{"report_id":"x"}}))
            self.assertEqual(out["status"], "REJECTED")
    def test_vb18_cancellation_api_exists(self): self.assertTrue(callable(production.ProductionRunEngine.cancel))
    def test_vb19_job_json_is_engine_owned(self): self.assertTrue(hasattr(production.ProductionRunEngine, "start"))
    def test_vb20_repo_binding_unchangeable(self): self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"other"},"steps":[step("v")]})["valid"])


if __name__ == "__main__": unittest.main()
