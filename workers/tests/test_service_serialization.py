from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from worker_v1.service import ACT_OPERATIONS, OBSERVE_OPERATIONS, WorkerService


class SingleActiveSlotEngine:
    """Deterministic stand-in for the production engine's one active slot."""

    def __init__(self):
        self.guard = threading.Lock()
        self.active = False
        self.starts = 0
        self.max_active = 0
        self.jobs = {}

    def start(self, job):
        with self.guard:
            self.starts += 1
            if self.active:
                return {"status": "REJECTED", "reason": "ACTIVE_RUN_EXISTS"}
            self.active = True
            self.max_active = max(self.max_active, 1)
            run_id = f"synthetic-{self.starts}"
            self.jobs[run_id] = job
            return {"status": "ACCEPTED", "run_id": run_id}

    def result(self, run_id):
        time.sleep(0.025)
        with self.guard:
            self.active = False
            step = self.jobs[run_id]["steps"][0]
            return {"status": "READY", "overall": "PASS", "steps": [{
                "status": "PASS", "path": step["params"]["path"], "size": len(step["params"]["path"]),
            }]}


class FailingEngine:
    def start(self, job):
        raise OSError("synthetic internal failure")


class WorkerServiceSerializationTests(unittest.TestCase):
    requests = tuple({"operation": "CHECK_FILE", "path": f"src/item-{index}.txt"}
                     for index in range(3))

    def test_three_sequential_observations_each_reach_terminal_result(self):
        engine = SingleActiveSlotEngine()
        service = WorkerService(engine, timeout_seconds=1)
        results = [service.execute(request, OBSERVE_OPERATIONS) for request in self.requests]
        self.assertEqual([value["status"] for value in results], ["PASS"] * 3)
        self.assertEqual([value["path"] for value in results], [request["path"] for request in self.requests])
        self.assertEqual(engine.starts, 3)
        self.assertEqual(engine.max_active, 1)
        self.assertTrue(all(not ({"run_id", "worker_pid", "state", "queue_id"} & value.keys())
                            for value in results))

    def test_three_overlapping_observations_are_serialized_server_side(self):
        engine = SingleActiveSlotEngine()
        service = WorkerService(engine, timeout_seconds=2)
        gate = threading.Barrier(4)

        def invoke(request):
            gate.wait(timeout=1)
            return service.execute(request, OBSERVE_OPERATIONS)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(invoke, request) for request in self.requests]
            gate.wait(timeout=1)
            results = [future.result(timeout=3) for future in futures]

        self.assertEqual([value["status"] for value in results], ["PASS"] * 3)
        self.assertCountEqual([value["path"] for value in results], [request["path"] for request in self.requests])
        self.assertEqual(engine.starts, 3)
        self.assertEqual(engine.max_active, 1)
        self.assertNotIn("ACTIVE_RUN_EXISTS", str(results))
        self.assertTrue(all(not ({"run_id", "worker_pid", "state", "queue_id"} & value.keys())
                            for value in results))

    def test_internal_failure_fails_closed_and_does_not_leak_exception(self):
        service = WorkerService(FailingEngine(), timeout_seconds=1)
        result = service.execute(self.requests[0], OBSERVE_OPERATIONS)
        self.assertEqual(result, {
            "status": "UNPROVEN", "operation": "UNKNOWN",
            "code": "OPERATION_OUTCOME_UNAVAILABLE", "retryable": False,
        })
        self.assertNotIn("synthetic internal failure", str(result))

    def test_observe_act_authority_split_is_unchanged(self):
        engine = SingleActiveSlotEngine()
        service = WorkerService(engine, timeout_seconds=1)
        result = service.execute({"operation": "ADB_CLEAR_DEPUTY_DATA", "serial": "SYNTHETIC"},
                                 OBSERVE_OPERATIONS)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["code"], "OPERATION_NOT_PERMITTED")
        self.assertEqual(engine.starts, 0)
        self.assertIn("ADB_CLEAR_DEPUTY_DATA", ACT_OPERATIONS)


if __name__ == "__main__":
    unittest.main()
