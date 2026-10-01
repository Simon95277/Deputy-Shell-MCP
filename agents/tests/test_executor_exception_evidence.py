from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bridge import executor


class ExecutorExceptionEvidenceTests(unittest.TestCase):
    def test_post_launch_exception_is_local_only_and_cleanup_still_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence_root = Path(temp) / "evidence"
            manifest = {"schema": "deputy.recon.snapshot.v1", "file_count": 1,
                        "total_bytes": 4, "workspace_id": "BRIDGE_LAB"}
            fake_process = SimpleNamespace(returncode=None, poll=lambda: None)
            docker_calls = []

            def run(argv, timeout=20):
                docker_calls.append(list(argv))
                if "inspect" in argv:
                    return SimpleNamespace(returncode=0, stdout='{"Status":"running","Running":true}', stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            def prep_run(argv, deadline, default_timeout=20):
                if "logs" in argv:
                    return SimpleNamespace(returncode=0, stdout="Accepting HTTP Socket connections", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            def fail_collect(*args, **kwargs):
                raise RuntimeError("LOCAL_SENTINEL C:\\synthetic\\private-path")

            with (
                patch.object(executor, "EVIDENCE_ROOT", evidence_root),
                patch.object(executor, "validate_contract"),
                patch.object(executor, "_prepare_snapshot", return_value=(manifest, {"refresh_ms": 0})),
                patch.object(executor, "_prep_run", side_effect=prep_run),
                patch.object(executor, "build_argv", return_value=[
                    "docker", "run", "--network", "REQUIRED_NETWORK", "--mount",
                    "type=bind,source=fixture,target=/workspace,readonly", "-e",
                    "HTTP_PROXY=http://PROXY:3128",
                ]),
                patch.object(executor, "_validate_mount_contract", return_value={"network_policy": "PROVIDER_ONLY"}),
                patch.object(executor.subprocess, "Popen", return_value=fake_process),
                patch.object(executor, "_collect_process", side_effect=fail_collect),
                patch.object(executor, "_capture_worker_state", return_value={"Status": "running", "Running": True}) as capture_state,
                patch.object(executor, "_run", side_effect=run),
                patch.object(executor, "list_resources", return_value={"containers": [], "networks": []}),
            ):
                result = executor.execute("synthetic diagnostic", "BRIDGE_LAB", job_id="a" * 32)

            job_dir = evidence_root / ("a" * 32)
            local_error = json.loads((job_dir / "containment-error.json").read_text(encoding="utf-8"))
            public_result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "CONTAINMENT_ERROR")
            self.assertEqual(local_error["exception_type"], "RuntimeError")
            self.assertIn("LOCAL_SENTINEL", local_error["exception_message"])
            self.assertIn("fail_collect", local_error["traceback"])
            self.assertEqual(local_error["execution_state"], "RUNNING")
            self.assertEqual(local_error["preparation_phase"], "WORKER_LAUNCH")
            self.assertTrue(local_error["child_process_launched"])
            self.assertIsNone(local_error["child_return_code"])
            self.assertIsNone(local_error["session_id"])
            self.assertEqual(local_error["worker_state"]["Status"], "running")
            self.assertNotIn("LOCAL_SENTINEL", json.dumps(public_result))
            self.assertNotIn("synthetic\\private-path", json.dumps(public_result))
            self.assertTrue(capture_state.called)
            self.assertTrue((job_dir / "cleanup.json").exists())
            cleanup = json.loads((job_dir / "cleanup.json").read_text(encoding="utf-8"))
            self.assertEqual(cleanup["remaining"], {"containers": [], "networks": []})
            cleanup_commands = [call for call in docker_calls if "rm" in call or "network" in call]
            self.assertTrue(any(call[:3] == [str(executor.DOCKER), "rm", "-f"] and "worker" in call[-1] for call in cleanup_commands))
            self.assertTrue(any(call[:3] == [str(executor.DOCKER), "rm", "-f"] and "proxy" in call[-1] for call in cleanup_commands))
            self.assertTrue(any("network" in call and "rm" in call for call in cleanup_commands))


if __name__ == "__main__":
    unittest.main()
