import unittest
from unittest import mock

import server
from worker_v1.capabilities import FROZEN, validate_job


class W8D2Tests(unittest.TestCase):
    def start(self, steps):
        with mock.patch.object(server.PRODUCTION_ENGINE, "start", return_value={"status": "ACCEPTED"}) as start:
            result = server.deputy_worker_start(steps)
            return result, start

    def test_d2_1_canonical_submission(self):
        result, start = self.start([
            {"operation": "CAPTURE_REPO_STATE", "params": {}},
            {"operation": "CHECK_FILE", "params": {"path": "app/build.gradle.kts"}},
        ])
        self.assertEqual(result["status"], "ACCEPTED")
        job = start.call_args.args[0]
        self.assertTrue(validate_job(job)["valid"])

    def test_d2_2_3_injects_schema_and_binding(self):
        _, start = self.start([])
        job = start.call_args.args[0]
        self.assertEqual(job["schema"], "deputy.worker.job.v1")
        self.assertEqual(job["repo"], {"binding": "deputy-authoritative-v1"})

    def test_d2_4_generates_deterministic_unique_ids(self):
        _, start = self.start([
            {"operation": "CAPTURE_REPO_STATE", "params": {}},
            {"operation": "GIT_DIFF_CHECK", "params": {}},
        ])
        self.assertEqual([s["id"] for s in start.call_args.args[0]["steps"]], ["step-001", "step-002"])

    def test_d2_5_6_caller_cannot_override_policy(self):
        result, start = self.start({"schema": "x"})
        self.assertEqual(result["status"], "REJECTED")
        self.assertFalse(start.called)

    def test_d2_7_8_9_validation_remains_engine_owned(self):
        _, start = self.start([{"operation": "NOT_REGISTERED", "params": {}}])
        self.assertFalse(validate_job(start.call_args.args[0])["valid"])

    def test_d2_10_symbolic_ids_remain_registry_validated(self):
        _, start = self.start([{"operation": "GRADLE", "params": {"task_id": "NOT_REGISTERED"}}])
        self.assertFalse(validate_job(start.call_args.args[0])["valid"])

    def test_d2_11_exactly_22_operations(self):
        self.assertEqual(len(FROZEN), 22)

    def test_d2_12_no_generic_execution_fields(self):
        _, start = self.start([{"operation": "CAPTURE_REPO_STATE", "params": {}}])
        job = start.call_args.args[0]
        self.assertNotIn("argv", job)
        self.assertNotIn("command", job)
        self.assertNotIn("executable", job)
        self.assertNotIn("cwd", job)


if __name__ == "__main__":
    unittest.main()
