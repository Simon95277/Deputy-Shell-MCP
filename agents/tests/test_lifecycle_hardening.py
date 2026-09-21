import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server
from bridge import executor


class LifecycleHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = server.JOB_STATE_ROOT
        server.JOB_STATE_ROOT = Path(self.tmp.name) / "jobs"
        server._JOBS.clear()

    def tearDown(self):
        server._JOBS.clear()
        server.JOB_STATE_ROOT = self.old_root
        self.tmp.cleanup()

    def job(self, status="RUNNING"):
        return {"job_id": "a" * 32, "workspace_id": "BRIDGE_LAB", "status": status,
                "execution_state": status, "created_at": 1.0, "updated_at": 1.0}

    def test_terminal_job_survives_restart(self):
        job = self.job("PASS"); result = {"status": "PASS", "job_id": job["job_id"]}
        server._persist_job(job, result); server._JOBS.clear(); server._load_durable_jobs()
        self.assertEqual(server._JOBS[job["job_id"]]["result"]["status"], "PASS")

    def test_running_job_becomes_interrupted(self):
        job = self.job(); server._persist_job(job); server._JOBS.clear(); server._load_durable_jobs()
        self.assertEqual(server._JOBS[job["job_id"]]["status"], "INTERRUPTED")
        self.assertEqual(server._public_job_state(server._JOBS[job["job_id"]])["execution_state"], "INTERRUPTED")

    def test_durable_schema_is_explicit(self):
        server._persist_job(self.job())
        data = json.loads(next(server.JOB_STATE_ROOT.glob("*.json")).read_text())
        self.assertEqual(data["schema"], server.DURABLE_SCHEMA)

    def test_atomic_state_has_no_temp_after_write(self):
        server._persist_job(self.job())
        self.assertEqual(list(server.JOB_STATE_ROOT.glob("*.tmp")), [])

    def test_malformed_state_fails_closed(self):
        server.JOB_STATE_ROOT.mkdir(parents=True); (server.JOB_STATE_ROOT / ("b" * 32 + ".json")).write_text("not json")
        self.assertEqual(server._load_durable_jobs(), [])

    def test_invalid_schema_is_ignored(self):
        server.JOB_STATE_ROOT.mkdir(parents=True); (server.JOB_STATE_ROOT / ("c" * 32 + ".json")).write_text(json.dumps({"schema": "other"}))
        self.assertEqual(server._load_durable_jobs(), [])

    def test_repeated_load_is_safe(self):
        server._persist_job(self.job("PASS")); self.assertEqual(len(server._load_durable_jobs()), 1); self.assertEqual(len(server._load_durable_jobs()), 1)

    def test_orphan_resources_are_scoped(self):
        with mock.patch.object(server.executor, "list_resources", return_value={"containers": ["ocb-worker-" + "a" * 20, "unrelated"], "networks": ["ocb-net-" + "a" * 20, "unrelated-net"]}), mock.patch.object(server.executor, "_cleanup") as cleanup:
            server._persist_job(self.job()); out = server.startup_reconcile()
        self.assertNotIn("unrelated", out["owned_resources_seen"])
        self.assertNotIn("unrelated-net", out["owned_resources_seen"])
        cleanup.assert_called_once()

    def test_reconciliation_is_repeatable(self):
        server._persist_job(self.job());
        with mock.patch.object(server.executor, "list_resources", return_value={"containers": [], "networks": []}), mock.patch.object(server.executor, "_cleanup"):
            first = server.startup_reconcile(); second = server.startup_reconcile()
        self.assertEqual(first["status"], "PASS"); self.assertEqual(second["status"], "PASS")

    def test_pending_cancel_is_recorded(self):
        executor.PENDING_CANCELS.clear(); out = executor.cancel("d" * 32)
        self.assertEqual(out["status"], "CANCEL_REQUESTED"); self.assertTrue(out["pending"])
        executor.PENDING_CANCELS.clear()

    def test_pending_cancel_is_consumed_on_registration(self):
        executor.PENDING_CANCELS.add("e" * 32)
        import shutil
        shutil.rmtree(executor.LAB / "evidence" / ("e" * 32), ignore_errors=True)
        with mock.patch.object(executor, "_prepare_snapshot", side_effect=AssertionError("snapshot must not start")), mock.patch.object(executor, "_cleanup"), mock.patch.object(executor, "list_resources", return_value={"containers": [], "networks": []}):
            out = executor.execute("bounded", "BRIDGE_LAB", job_id="e" * 32)
        self.assertEqual(out["status"], "CANCELLED"); self.assertNotIn("e" * 32, executor.PENDING_CANCELS)

    def test_repeated_cancel_is_safe(self):
        executor.PENDING_CANCELS.clear(); first = executor.cancel("f" * 32); second = executor.cancel("f" * 32)
        self.assertEqual(first["status"], "CANCEL_REQUESTED"); self.assertEqual(second["status"], "CANCEL_REQUESTED"); executor.PENDING_CANCELS.clear()

    def test_terminal_result_is_preferred_over_cancel(self):
        job = self.job("PASS"); job["result"] = {"status": "PASS", "job_id": job["job_id"]}
        self.assertEqual(server._public_job_state(job)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
