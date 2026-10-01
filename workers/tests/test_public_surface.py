from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from worker_v1.service import ACT_OPERATIONS, OBSERVE_OPERATIONS, project_outcome


class PublicSurfaceTests(unittest.TestCase):
    def test_default_tools_are_exactly_observe_and_act(self):
        names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(names, {"deputy_observe", "deputy_act"})

    def test_owner_control_plane_is_opt_in(self):
        env = os.environ.copy()
        env["DEPUTYWORKERS_ENABLE_CONTROL_PLANE"] = "1"
        code = "import asyncio,json,server; print(json.dumps(sorted(t.name for t in asyncio.run(server.mcp.list_tools()))))"
        proc = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parents[1], env=env,
                              capture_output=True, text=True, check=True)
        names = set(json.loads(proc.stdout))
        self.assertTrue({"deputy_observe", "deputy_act", "deputy_worker_start", "deputy_worker_result",
                         "deputy_worker_run_status", "deputy_worker_cancel", "deputy_worker_status"}.issubset(names))

    def test_observe_and_act_discriminated_schemas_are_finite(self):
        tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
        expected = {"deputy_observe": set(OBSERVE_OPERATIONS), "deputy_act": set(ACT_OPERATIONS)}
        for name, operations in expected.items():
            schema = tools[name].input_schema
            self.assertNotIn("steps", schema.get("properties", {}))
            self.assertNotIn("run_id", json.dumps(schema))
            request = schema["properties"]["request"]
            self.assertIn("oneOf", request)
            defs = schema["$defs"]
            values = {defs[ref["$ref"].split("/")[-1]]["properties"]["operation"].get("const")
                      for ref in request["oneOf"]}
            self.assertEqual(values, operations)
            properties = {key.lower() for definition in schema.get("$defs", {}).values()
                          for key in definition.get("properties", {})}
            properties.update(key.lower() for key in schema.get("properties", {}))
            self.assertFalse(properties & {"executable", "argv", "environment", "shell", "command", "cwd", "steps", "run_id"})
        self.assertEqual(len(set(OBSERVE_OPERATIONS) & set(ACT_OPERATIONS)), 0)
        self.assertEqual(len(OBSERVE_OPERATIONS) + len(ACT_OPERATIONS), 22)

    def test_one_public_call_runs_internal_lifecycle_and_projects_terminal_result(self):
        class FakeEngine:
            starts = 0
            results = 0
            def start(self, job):
                self.starts += 1
                self.asserted_job = job
                return {"status": "ACCEPTED", "run_id": "private-run-id", "worker_pid": 44}
            def result(self, run_id):
                self.results += 1
                self.asserted_run_id = run_id
                return {"status": "READY", "overall": "PASS", "run_id": "private-run-id",
                        "worker_pid": 44, "steps": [{"operation": "CHECK_FILE", "status": "PASS",
                        "path": "app/build.gradle.kts", "size": 48, "stdout": "private"}]}

        engine = FakeEngine()
        with patch.object(server.WORKER_SERVICE, "engine", engine):
            result = asyncio.run(server.mcp.call_tool(
                "deputy_observe", {"request": {"operation": "CHECK_FILE", "path": "app/build.gradle.kts"}}))
        value = result.structured_content
        self.assertEqual(engine.starts, 1)
        self.assertEqual(engine.results, 1)
        self.assertEqual(value, {"status": "PASS", "operation": "CHECK_FILE", "path": "app/build.gradle.kts", "size": 48})
        for forbidden in ("run_id", "worker_pid", "stdout", "argv", "environment", "repo_root"):
            self.assertNotIn(forbidden, json.dumps(value))

    def test_observe_rejects_act_operation_before_engine(self):
        result = project_outcome("ADB_CLEAR_DEPUTY_DATA", {"overall": "PASS", "steps": [{"status": "PASS"}]})
        self.assertEqual(result["status"], "PASS")  # Projection is not the authority boundary.
        class NeverEngine:
            def start(self, job): raise AssertionError("cross-surface operation reached engine")
        with patch.object(server.WORKER_SERVICE, "engine", NeverEngine()):
            result = server.deputy_observe({"operation": "ADB_CLEAR_DEPUTY_DATA", "serial": "SYNTHETIC"})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["code"], "OPERATION_NOT_PERMITTED")

    def test_projector_recursively_excludes_control_plane_and_raw_output(self):
        result = project_outcome("HASH_ARTIFACT", {
            "overall": "PASS", "run_id": "private", "integrity": {"pre_path": "C:\\private"},
            "steps": [{"status": "PASS", "size": 48, "sha256": "a" * 64,
                       "stdout": "private", "command": ["python"], "result_path": "C:\\private"}],
        })
        text = json.dumps(result)
        for forbidden in ("run_id", "pre_path", "stdout", "command", "result_path", "C:\\\\private"):
            self.assertNotIn(forbidden, text)

    def test_benchmark_semantics_are_projected_from_one_public_operation(self):
        hashed = project_outcome("HASH_ARTIFACT", {
            "overall": "PASS", "steps": [{"status": "PASS", "path": "tools/benchmark/payload.txt",
                                             "size": 48, "sha256": "a" * 64}],
        })
        self.assertEqual(hashed["exists"], True)
        self.assertEqual(hashed["size"], 48)
        self.assertEqual(hashed["sha256"], "a" * 64)

        repo = project_outcome("CAPTURE_REPO_STATE", {
            "overall": "PASS", "steps": [
                {"status": "PASS", "head": "a" * 40, "branch": "main", "dirty": False},
                {"status": "PASS", "exit_code": 0},
            ],
        })
        self.assertTrue(repo["diff_check_pass"])

        junit = project_outcome("PARSE_JUNIT", {
            "overall": "FAIL", "steps": [{"status": "FAIL", "tests": 8, "failures": 1,
                                            "errors": 0, "skipped": 0, "duration": 1.25,
                                            "failing_testcases": [{"suite": "s", "classname": "c",
                                                                   "name": "n", "kind": "failure", "text": "omit"}]}],
        })
        self.assertEqual(junit["report_status"], "FAIL")
        self.assertEqual(junit["duration_seconds"], 1.25)
        self.assertEqual(junit["failing_testcases"], [{"suite": "s", "classname": "c", "name": "n", "kind": "failure"}])

    def test_repo_state_intent_composes_diff_check_internally(self):
        class CaptureEngine:
            def start(self, job):
                self.job = job
                return {"status": "ACCEPTED", "run_id": "private"}
            def result(self, run_id):
                return {"status": "READY", "overall": "PASS", "steps": [
                    {"status": "PASS", "head": "b" * 40, "branch": "main", "dirty": True},
                    {"status": "PASS", "exit_code": 0},
                ]}

        engine = CaptureEngine()
        with patch.object(server.WORKER_SERVICE, "engine", engine):
            result = asyncio.run(server.mcp.call_tool(
                "deputy_observe", {"request": {"operation": "CAPTURE_REPO_STATE"}})).structured_content
        self.assertEqual([step["operation"] for step in engine.job["steps"]], ["CAPTURE_REPO_STATE", "GIT_DIFF_CHECK"])
        self.assertEqual(result, {"status": "PASS", "operation": "CAPTURE_REPO_STATE", "head": "b" * 40,
                                  "branch": "main", "dirty": True, "diff_check_pass": True})


if __name__ == "__main__":
    unittest.main()
