from __future__ import annotations
import os, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

from worker_v1 import DurableRunEngine, ProductionRunEngine
from worker_v1.capabilities import validate_job
from worker_v1 import production

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "w4a_hold_worker.py"

def job(*steps):
    return {"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":list(steps)}

def step(i, op="CHECK_FILE", path="app/build.gradle.kts"):
    return {"id":i,"operation":op,"params":({"path":path} if op in {"CHECK_FILE","HASH_ARTIFACT"} else {})}

class C5ATests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="w4a-c5a-")); self.ready=self.temp/"ready"; self.release=self.temp/"release"; self.engine=ProductionRunEngine(self.temp)
        self.patch=mock.patch.object(production, "_build_production_worker_command", lambda root, rid: [sys.executable, str(FIXTURE), str(self.ready), str(self.release)])
        self.patch.start(); self.addCleanup(self.patch.stop)
    def hold_job(self): return job(step("s1"))
    def wait_running(self, run):
        for _ in range(60):
            st=self.engine.status(run["run_id"])
            if st.get("state")=="RUNNING": return st
            time.sleep(.02)
        self.fail("worker did not become RUNNING")
    def release_worker(self): self.release.write_text("RELEASE", encoding="utf-8")
    def test_t1_fixture_not_job_selectable(self): self.assertFalse(validate_job(job({"id":"x","operation":"CHECK_FILE","params":{"path":"app/build.gradle.kts"},"worker":"fixture"}))["valid"])
    def test_t2_fixture_not_mcp_argument(self): self.assertNotIn("fixture", production._build_production_worker_command(self.temp,"rid"))
    def test_t3_registry_has_no_fixture_operation(self): self.assertNotIn("W4A_HOLD", Path(ROOT/"WORKER_CAPABILITIES.json").read_text(encoding="utf-8"))
    def test_t4_normal_builder_targets_production_worker(self):
        self.patch.stop(); self.addCleanup(self.patch.start); self.assertIn("worker_v1.production_worker", production._build_production_worker_command(self.temp,"rid"))
    def test_t5_override_is_scoped(self):
        self.patch.stop(); self.assertIn("worker_v1.production_worker", production._build_production_worker_command(self.temp,"rid")); self.patch.start()
    def test_t6_forbidden_lifecycle_fields_rejected(self):
        for field in ("command","executable","argv","module","script_path","worker","worker_kind","test_mode","delay","duration"):
            self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":[],field:"x"})["valid"], field)
    def test_c2_1_separate_process(self):
        r=self.engine.start(self.hold_job()); self.assertNotEqual(r["worker_pid"],os.getpid()); self.release_worker()
    def test_c2_2_creation_identity_persisted(self):
        r=self.engine.start(self.hold_job())
        if os.name == "nt":
            self.assertTrue(r["worker_identity"]["creation_identity"])
        else:
            # POSIX liveness evidence intentionally has no Windows creation token.
            self.assertEqual(r["worker_identity"], {"pid": r["worker_pid"]})
        self.release_worker()
    def test_c2_3_async_start_running(self):
        r=self.engine.start(self.hold_job()); self.assertEqual(self.wait_running(r)["state"],"RUNNING"); self.release_worker()
    def test_c2_4_fresh_engine_recognizes_worker(self):
        r=self.engine.start(self.hold_job()); st=self.wait_running(r); fresh=ProductionRunEngine(self.temp); self.assertEqual(fresh.status(r["run_id"])["state"],"RUNNING"); self.release_worker()
    def test_c2_5_cancellation(self):
        r=self.engine.start(self.hold_job()); self.wait_running(r); self.assertEqual(self.engine.cancel(r["run_id"])["status"],"CANCELLED")
    def test_c2_6_worker_loss(self):
        import subprocess

        launched = []
        real_popen = subprocess.Popen

        def launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            launched.append(child)
            return child

        # Retain the actual Popen object, not a reopened/reusable PID. Windows
        # Popen.wait uses its original process handle's exit signal; POSIX uses
        # its synchronized child wait. No creation-identity disappearance test.
        with mock.patch.object(production.subprocess, "Popen", side_effect=launch):
            r = self.engine.start(self.hold_job())
        self.assertEqual(len(launched), 1)
        child = launched[0]
        self.addCleanup(child.wait, timeout=5)
        self.addCleanup(self.release_worker)
        st = self.wait_running(r)
        self.assertEqual(child.pid, st["worker_pid"])
        self.assertEqual(st["worker_identity"], r["worker_identity"])
        if os.name == "nt":
            self.assertEqual(production.identity(child.pid), st["worker_identity"])

        last_status, last_result = st, {}

        def diagnostics():
            return repr({
                "pid": child.pid, "exit_code": child.returncode,
                "expected_identity": st["worker_identity"],
                "status": {k: last_status.get(k) for k in
                           ("status", "state", "terminal_reason")},
                "result": {k: last_result.get(k) for k in
                           ("status", "overall", "blocked_reason")},
                "active_exists": self.engine.active.exists(),
            })[:1500]

        production.terminate_tree(child.pid)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.fail("worker exit deadline expired: " + diagnostics())
        self.assertIsNotNone(child.returncode, diagnostics())

        # Exit and durable finalization are separate conditions. A process may
        # be gone while the watcher still flushes its terminal result/state.
        deadline = time.monotonic() + 5
        while True:
            fresh = ProductionRunEngine(self.temp)
            last_status = fresh.status(r["run_id"])
            last_result = fresh.result(r["run_id"])
            if (last_status.get("state") == "BLOCKED"
                    and last_status.get("terminal_reason") == "WORKER_PROCESS_LOST"
                    and last_result.get("status") == "READY"
                    and last_result.get("overall") == "BLOCKED"
                    and last_result.get("blocked_reason") == "WORKER_PROCESS_LOST"
                    and not fresh.active.exists()):
                break
            if time.monotonic() >= deadline:
                self.fail("worker-loss finalization deadline expired: " + diagnostics())
            time.sleep(.01)
        self.assertEqual(last_status["state"], "BLOCKED", diagnostics())
        self.assertEqual(last_result["overall"], "BLOCKED", diagnostics())
        self.assertFalse(self.engine.active.exists(), diagnostics())
    def test_c2_7_production_blocks_synthetic(self):
        r=self.engine.start(self.hold_job()); self.wait_running(r); s=DurableRunEngine(self.temp).start({"schema":"deputy.worker-w2-synthetic.v1","duration_seconds":1,"outcome":"PASS","emit_stderr":False}); self.assertEqual(s["status"],"REJECTED"); self.release_worker()
    def test_c2_8_synthetic_blocks_production(self):
        s=DurableRunEngine(self.temp).start({"schema":"deputy.worker-w2-synthetic.v1","duration_seconds":1,"outcome":"PASS","emit_stderr":False}); self.assertEqual(self.engine.start(job(step("x")))["status"],"REJECTED"); DurableRunEngine(self.temp).cancel(s["run_id"])
    def test_c2_9_concurrent_production_starts(self):
        results=[]; barrier=threading.Barrier(2)
        def go(): barrier.wait(); results.append(self.engine.start(self.hold_job()))
        a=threading.Thread(target=go); b=threading.Thread(target=go); a.start(); b.start(); a.join(); b.join(); self.assertEqual(sum(x["status"]=="ACCEPTED" for x in results),1); self.release_worker()

if __name__=="__main__": unittest.main()
