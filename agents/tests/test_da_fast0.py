import json
import asyncio
import tempfile
import subprocess
import sys
import unittest
import time
import threading
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeputyAgentsContractTests(unittest.TestCase):
    def test_mcp_v2_runtime_and_server_registration(self):
        import importlib.metadata
        from mcp.server import MCPServer
        import server
        self.assertTrue(importlib.metadata.version("mcp").startswith("2."))
        self.assertIsInstance(server.mcp, MCPServer)
        names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(names, {"deputy_recon", "deputy_recon_start", "deputy_recon_status", "deputy_recon_cancel"})

    def test_server_compiles(self):
        subprocess.run([sys.executable, "-m", "py_compile", str(ROOT / "server.py")], check=True)

    def test_mcp_child_ping_returns_pong(self):
        import server
        result = server.deputy_child_ping()
        self.assertEqual(result["runtime_contract_version"], "DA-PACKAGING-1")
        self.assertEqual(result["python_child"]["status"], "PASS")
        self.assertEqual(result["python_child"]["stdout"].strip(), "pong")
        self.assertEqual(result["python_child"]["exit_code"], 0)
        self.assertEqual(result["cmd_child"]["status"], "PASS")
        self.assertEqual(result["cmd_child"]["stdout"].strip(), "pong")
        self.assertEqual(result["cmd_child"]["exit_code"], 0)
        self.assertIn('"-I", "-S", "-u"', (ROOT / "server.py").read_text(encoding="utf-8"))

    def test_mount_attestation_is_job_snapshot_only(self):
        from bridge.executor import _validate_mount_contract
        job = ROOT / "evidence" / "test-job" / "snapshot"
        argv = ["docker", "run", "--mount", f"type=bind,source={job},target=/workspace,readonly"]
        proof = _validate_mount_contract(argv, "DEPUTY_SHELL", job)
        self.assertTrue(proof["workspace_mount_read_only"])
        self.assertFalse(proof["live_repo_mounted"])
        self.assertFalse(proof["shared_master_mounted"])
        self.assertEqual(proof["workspace_mount_source"], "JOB_SANITIZED_SNAPSHOT")

    def test_mount_attestation_rejects_live_and_shared_paths(self):
        from bridge.executor import _validate_mount_contract, REPO, SNAPSHOT_ROOT
        job = ROOT / "evidence" / "test-job" / "snapshot"
        for source in (REPO, SNAPSHOT_ROOT):
            argv = ["docker", "run", "--mount", f"type=bind,source={source},target=/workspace,readonly"]
            with self.assertRaises(RuntimeError):
                _validate_mount_contract(argv, "DEPUTY_SHELL", job)

    def test_result_metadata_uses_manifest_policy_and_hides_host_path(self):
        from bridge.core import result
        manifest = {"schema": "x", "policy_version": "DA-FAST-2-positive-allowlist-v1", "workspace_id": "DEPUTY_SHELL", "created_at": "t", "file_count": 625, "total_bytes": 19507861, "repo": {"branch": "b", "head": "h", "dirty": True}}
        out = result("PASS", "j", "DEPUTY_SHELL", "s", "text", 1, 0, manifest)
        self.assertEqual(out["snapshot"]["policy_version"], "DA-FAST-2-positive-allowlist-v1")
        self.assertEqual(out["snapshot"]["workspace_id"], "DEPUTY_SHELL")
        self.assertNotIn("repo_root_verified", str(out))

    def test_public_schema_source_is_bounded(self):
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('Literal["BRIDGE_LAB", "DEPUTY_SHELL"]', text)
        self.assertIn('worker_profile="RECON"', text)
        for forbidden in ("model:", "provider:", "docker", "container", "path:", "cwd:"):
            self.assertNotIn(forbidden, text.lower())

    def test_bridge_mapping_is_fixed(self):
        text = (ROOT / "bridge" / "core.py").read_text(encoding="utf-8")
        self.assertIn('"BRIDGE_LAB"', text)
        self.assertIn('"DEPUTY_SHELL"', text)
        self.assertIn('"RECON": "plan"', text)

    def test_generated_snapshot_manifest_is_excluded(self):
        text = (ROOT / "bridge" / "core.py").read_text(encoding="utf-8")
        self.assertIn('rel == "snapshot-manifest.json"', text)
        self.assertIn('"local-snapshots/"', text)

    def test_timeout_is_server_owned_and_timed(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        self.assertIn("PREPARATION_BUDGET_MS = 15000", text)
        self.assertNotIn("CHILD_EXECUTION_BUDGET_MS", text)
        self.assertNotIn("child_execution_budget_ms", text)
        self.assertNotIn("timeout_seconds", text[text.index("def execute"):text.index("def execute") + 180])
        self.assertIn("inject_timeout=False", text)
        self.assertIn('"phase_timings_ms"', (ROOT / "bridge" / "core.py").read_text(encoding="utf-8"))
        self.assertIn("EVIDENCE_LIMIT = 8192", text)
        self.assertIn("squid-access.log", text)
        self.assertIn("worker-state.json", text)
        self.assertIn("worker-stdout.txt", text)
        self.assertIn("worker-stderr.txt", text)
        self.assertIn("CHILD_IDLE_TIMEOUT_MS = 180000", text)
        self.assertIn("CHILD_ABSOLUTE_TIMEOUT_MS = 1800000", text)
        self.assertIn("ACTIVE_OPERATION_TIMEOUT_MS = 900000", text)
        self.assertIn("OUTER_WATCHDOG_MS = 1860000", text)

    def test_session_id_is_captured_from_incremental_event(self):
        from bridge.executor import _read_process_stream, _observe_event
        import io
        state, marks, chunks = {}, {}, []
        _read_process_stream(io.StringIO('{"type":"session","sessionID":"ses_test"}\n'), chunks, state, marks, time.monotonic(), True)
        self.assertEqual(state["session_id"], "ses_test")
        self.assertIn("first_session_event_ms", marks)

    def test_meaningful_progress_resets_idle_but_debug_does_not(self):
        from bridge.executor import _observe_event
        state, marks = {"last_progress_monotonic": 1.0}, {}
        _observe_event({"type": "debug", "message": "heartbeat"}, state, marks, 1)
        self.assertEqual(state["last_progress_monotonic"], 1.0)
        _observe_event({"type": "tool_use"}, state, marks, 2)
        self.assertNotEqual(state["last_progress_monotonic"], 1.0)

    def test_outstanding_step_suppresses_idle_for_tool_and_model_waits(self):
        import bridge.executor as executor
        state, marks = {}, {}
        executor._observe_event({"type": "step_start", "id": "step-1"}, state, marks, 0)
        state["active_operation_started_monotonic"] = 0
        state["last_progress_monotonic"] = 0
        self.assertIsNone(executor._watchdog_timeout(state, 200, 0))
        executor._observe_event({"type": "tool_use", "id": "tool-1"}, state, marks, 200000)
        self.assertEqual(state["execution_state"], "ACTIVE_STEP")
        self.assertIsNone(executor._watchdog_timeout(state, 800, 0))

    def test_true_idle_active_operation_and_absolute_timeout(self):
        import bridge.executor as executor
        self.assertEqual(executor._watchdog_timeout({"execution_state": "IDLE", "last_progress_monotonic": 0}, 181, 0), "CHILD_IDLE_TIMEOUT")
        active = {"execution_state": "ACTIVE_STEP", "active_operation_started_monotonic": 0, "last_progress_monotonic": 0}
        self.assertEqual(executor._watchdog_timeout(active, 901, 0), "ACTIVE_OPERATION_TIMEOUT")
        self.assertEqual(executor._watchdog_timeout({"execution_state": "IDLE", "last_progress_monotonic": 0}, 1801, 0), "CHILD_ABSOLUTE_TIMEOUT")

    def test_terminal_state_cannot_timeout(self):
        import bridge.executor as executor
        self.assertIsNone(executor._watchdog_timeout({"execution_state": "TERMINAL", "last_progress_monotonic": 0}, 5000, 0))

    def test_idle_and_absolute_timeout_classification(self):
        import io
        import bridge.executor as executor
        class NeverEnding:
            stdout = io.StringIO("")
            stderr = io.StringIO("")
            def poll(self): return None
        old_idle = executor.CHILD_IDLE_TIMEOUT_MS
        try:
            executor.CHILD_IDLE_TIMEOUT_MS = 0
            state, marks = {}, {}
            _, _, timed, reason = executor._collect_process(NeverEnding(), state, marks, time.monotonic(), 10)
            self.assertTrue(timed); self.assertEqual(reason, "CHILD_IDLE_TIMEOUT")
            executor.CHILD_IDLE_TIMEOUT_MS = 10**9
            state, marks = {}, {}
            _, _, timed, reason = executor._collect_process(NeverEnding(), state, marks, time.monotonic(), 0)
            self.assertTrue(timed); self.assertEqual(reason, "CHILD_ABSOLUTE_TIMEOUT")
        finally:
            executor.CHILD_IDLE_TIMEOUT_MS = old_idle

    def test_cleanup_remains_mandatory(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        self.assertIn("finally:", text)
        self.assertIn("_cleanup(res)", text)

    def test_deputy_snapshot_refresh_is_server_owned_and_locked(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        self.assertIn("SNAPSHOT_LOCK = threading.Lock()", text)
        self.assertIn("create_snapshot()", text)
        self.assertIn("shutil.copytree(SNAPSHOT_ROOT, destination)", text)
        self.assertNotIn("refresh_snapshot", text)
        self.assertNotIn("snapshot_path", (ROOT / "server.py").read_text(encoding="utf-8"))

    def test_deputy_prepare_uses_trusted_snapshot_and_bridge_does_not(self):
        from bridge import executor
        manifest = {"schema": "x", "repo": {"branch": "b", "head": "h", "dirty": False}}
        with patch.object(executor, "create_snapshot", return_value={"manifest": manifest, "audit": {}}) as refresh, \
             patch.object(executor.shutil, "copytree") as copy, \
             patch.object(executor, "build_snapshot", return_value=manifest) as build:
            executor._prepare_snapshot("DEPUTY_SHELL", ROOT / "tmp-job", "a" * 32)
            refresh.assert_called_once(); copy.assert_called_once()
            executor._prepare_snapshot("BRIDGE_LAB", ROOT / "tmp-job-bridge", "b" * 32)
            build.assert_called_once()

    def test_async_start_returns_before_background_completion_and_result_is_retrievable(self):
        import server
        started = threading.Event()
        release = threading.Event()
        original = server.execute
        def fake_execute(**kwargs):
            started.set(); release.wait(2)
            return {"status": "PASS", "job_id": kwargs["job_id"], "workspace_id": kwargs["workspace_id"], "text": "pong"}
        try:
            with patch.object(server, "execute", side_effect=fake_execute):
                t0 = time.monotonic()
                accepted = server.deputy_recon_start("bounded", "BRIDGE_LAB")
                self.assertLess(time.monotonic() - t0, 1)
                self.assertEqual(accepted["status"], "STARTED")
                job_id = accepted["job_id"]
                self.assertTrue(started.wait(1))
                running = server.deputy_recon_status(job_id)
                self.assertEqual(running["status"], "RUNNING")
                release.set()
                for _ in range(20):
                    result = server.deputy_recon_status(job_id)
                    if result["status"] == "PASS": break
                    time.sleep(.01)
                self.assertEqual(result["status"], "PASS")
        finally:
            release.set()
            server._JOBS.pop(locals().get("job_id", ""), None)

    def test_async_unknown_and_terminal_cancel_are_safe(self):
        import server
        self.assertEqual(server.deputy_recon_status("missing")["status"], "NOT_FOUND")
        self.assertEqual(server.deputy_recon_cancel("missing")["status"], "NOT_FOUND")
        job_id = "terminal-test"
        server._JOBS[job_id] = {"job_id": job_id, "workspace_id": "BRIDGE_LAB", "created_at": time.time(), "result": {"status": "PASS", "job_id": job_id}}
        try:
            self.assertEqual(server.deputy_recon_cancel(job_id)["status"], "PASS")
            self.assertEqual(server.deputy_recon_status(job_id)["status"], "PASS")
        finally:
            server._JOBS.pop(job_id, None)

    def test_async_concurrency_is_bounded_and_caller_has_no_execution_controls(self):
        import server
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("MAX_CONCURRENT_RECON = 2", text)
        self.assertNotIn("timeout:", text.lower())
        self.assertNotIn("model:", text.lower())
        self.assertNotIn("provider:", text.lower())
        ids = ["busy-a", "busy-b"]
        for job_id in ids:
            server._JOBS[job_id] = {"job_id": job_id, "workspace_id": "BRIDGE_LAB", "created_at": time.time(), "status": "RUNNING"}
        try:
            self.assertEqual(server.deputy_recon_start("bounded", "BRIDGE_LAB")["status"], "BUSY")
        finally:
            for job_id in ids: server._JOBS.pop(job_id, None)

    def test_async_runtime_and_lifecycle_tools_are_exposed(self):
        import server
        self.assertEqual(server.RUNTIME_CONTRACT_VERSION, "DA-PACKAGING-1")
        for name in ("deputy_recon_start", "deputy_recon_status", "deputy_recon_cancel"):
            self.assertTrue(hasattr(server, name))

    def test_git_probe_is_fixed_read_only_surface(self):
        import server
        import inspect
        self.assertEqual(inspect.signature(server.deputy_git_probe).parameters, {})
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.DEVNULL", text)
        self.assertIn("sanitized_environment", text)
        self.assertNotIn('"GIT_DIR":', text)

    def test_snapshot_reuses_single_pre_capture_and_traces_invocations(self):
        text = (ROOT / "snapshot.py").read_text(encoding="utf-8")
        self.assertEqual(text.count('state_before = capture_repo_state'), 1)
        self.assertIn('tracked = set(state_before["tracked"])', text)
        self.assertIn('"ordinal": len(events) + 1', text)
    def test_preparation_lock_timeout_is_bounded_and_phase_is_durable(self):
        import bridge.executor as executor
        class BusyLock:
            def acquire(self, timeout=None): return False
            def release(self): pass
        with tempfile.TemporaryDirectory() as td, patch.object(executor, "SNAPSHOT_LOCK", BusyLock()):
            evdir = Path(td); state = {"cancel": threading.Event()}
            with self.assertRaises(executor.PreparationTimeout):
                executor._prepare_snapshot("DEPUTY_SHELL", evdir / "snapshot", "lock-test", time.monotonic() + .2, state, evdir, time.monotonic())
            self.assertEqual(json.loads((evdir / "preparation-state.json").read_text())["preparation_phase"], "SNAPSHOT_LOCK_WAIT")

    def test_status_exposes_preparation_phase_without_internal_paths(self):
        import server
        import bridge.executor as executor
        job_id = "phase-test"
        server._JOBS[job_id] = {"job_id": job_id, "workspace_id": "DEPUTY_SHELL", "created_at": time.time(), "status": "STARTED", "execution_state": "PREPARING"}
        with executor.LOCK:
            executor.ACTIVE[job_id] = {"execution_state": "PREPARING", "preparation_phase": "SNAPSHOT_GIT_STATUS", "snapshot_lock_wait_ms": 4}
        try:
            out = server.deputy_recon_status(job_id)
            self.assertEqual(out["preparation_phase"], "SNAPSHOT_GIT_STATUS")
            self.assertEqual(out["snapshot_lock_wait_ms"], 4)
            self.assertNotIn("C:\\", json.dumps(out))
        finally:
            server._JOBS.pop(job_id, None)
            executor.ACTIVE.pop(job_id, None)

    def test_preparation_timeout_is_terminal_without_worker_launch(self):
        import bridge.executor as executor
        with tempfile.TemporaryDirectory() as td, patch.object(executor, "LAB", Path(td)), patch.object(executor, "EVIDENCE_ROOT", Path(td) / "evidence"), patch.object(executor, "_prepare_snapshot", side_effect=executor.PreparationTimeout("PREPARATION_TIMEOUT")), patch.object(executor, "_cleanup"), patch.object(executor, "list_resources", return_value={"containers": [], "networks": []}):
            out = executor.execute("bounded", "DEPUTY_SHELL", job_id="prep-timeout-test")
        self.assertEqual(out["status"], "TIMEOUT")
        self.assertEqual(out["timeout_reason"], "PREPARATION_TIMEOUT")
        self.assertEqual(out["execution_state"], "PREPARING")

    def test_snapshot_uses_plumbing_diffs_and_explicit_untracked_query(self):
        text = (ROOT / "snapshot.py").read_text(encoding="utf-8")
        self.assertNotIn('"status", "--short"', text)
        self.assertIn('"--name-status", "--no-renames"', text)
        self.assertIn('"--cached", "--name-status"', text)
        self.assertIn('"ls-files", "--others", "--exclude-standard"', text)

    def test_canonical_status_preserves_dirty_staged_deleted_and_untracked_states(self):
        from snapshot import _canonical_status
        self.assertTrue(_canonical_status([("M", "tracked.py")], [], []).strip())
        self.assertTrue(_canonical_status([], [("M", "staged.py")], []).strip())
        self.assertTrue(_canonical_status([("D", "deleted.py")], [], []).strip())
        self.assertTrue(_canonical_status([], [("D", "staged-deleted.py")], []).strip())
        self.assertEqual(_canonical_status([], [], ["untracked.py"]), "U ??\tuntracked.py")
        self.assertEqual(_canonical_status([], [], []), "")
        self.assertEqual(_canonical_status([], [], ["b", "a"]), "U ??\ta\nU ??\tb")

    def test_canonical_status_detects_drift_and_unchanged_state(self):
        from snapshot import _canonical_status
        before = _canonical_status([], [("M", "staged.py")], ["u.py"])
        self.assertEqual(before, _canonical_status([], [("M", "staged.py")], ["u.py"]))
        self.assertNotEqual(before, _canonical_status([("M", "staged.py")], [], ["u.py"]))
        self.assertNotEqual(before, _canonical_status([], [("M", "staged.py")], ["v.py"]))

    def test_nul_name_status_handles_spaces_and_git_environment_is_read_only(self):
        import snapshot
        self.assertEqual(snapshot._parse_name_status("M\0folder/has space.txt\0"), [("M", "folder/has space.txt")])
        with patch.object(snapshot.subprocess, "run", return_value=type("P", (), {"stdout": b"", "stderr": b"", "returncode": 0})()) as run:
            snapshot._git("ls-files", deadline=time.monotonic() + 1)
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertLessEqual(run.call_args.kwargs["timeout"], snapshot.GIT_COMMAND_TIMEOUT_SECONDS)

    def test_git_trace_has_start_and_terminal_generation_events(self):
        import snapshot
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "git-trace.json"
            with patch.object(snapshot, "GIT", "git.exe"), patch.object(snapshot, "REPO", ROOT):
                with patch.object(snapshot, "_run_git_process", return_value=type("P", (), {"stdout": b"x", "stderr": b"", "returncode": 0})()):
                    snapshot._git("rev-parse", "HEAD", trace_path=trace, command_label="head", capture_generation="BEFORE")
            events = json.loads(trace.read_text())
            self.assertEqual([e["event"] for e in events], ["START", "PASS"])
            self.assertEqual(events[0]["capture_generation"], "BEFORE")


if __name__ == "__main__":
    unittest.main()
