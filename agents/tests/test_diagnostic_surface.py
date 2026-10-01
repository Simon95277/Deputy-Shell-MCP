import asyncio
import inspect
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class DiagnosticSurfaceTests(unittest.TestCase):
    def _tool_names(self, value="MISSING", control="MISSING"):
        env = os.environ.copy()
        if value == "MISSING":
            env.pop("DEPUTYAGENTS_ENABLE_DIAGNOSTICS", None)
        else:
            env["DEPUTYAGENTS_ENABLE_DIAGNOSTICS"] = value
        if control == "MISSING":
            env.pop("DEPUTYAGENTS_ENABLE_CONTROL_PLANE", None)
        else:
            env["DEPUTYAGENTS_ENABLE_CONTROL_PLANE"] = control
        code = "import asyncio, json, server; print(json.dumps(sorted(x.name for x in asyncio.run(server.mcp.list_tools()))))"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    @staticmethod
    def _production_names():
        return ["deputy_recon"]

    def test_01_missing_config_disables_diagnostics(self):
        self.assertEqual(self._tool_names(), self._production_names())

    def test_02_empty_config_disables_diagnostics(self):
        self.assertEqual(self._tool_names(""), self._production_names())

    def test_03_unexpected_config_disables_diagnostics(self):
        self.assertEqual(self._tool_names("true"), self._production_names())

    def test_04_exact_one_enables_diagnostics(self):
        self.assertEqual(
            self._tool_names("1"),
            sorted(self._production_names() + ["deputy_child_ping", "deputy_git_probe"]),
        )

    def test_05_production_enumeration_is_exact(self):
        self.assertEqual(self._tool_names(), self._production_names())

    def test_06_production_excludes_git_probe(self):
        self.assertNotIn("deputy_git_probe", self._tool_names())

    def test_07_production_excludes_child_ping(self):
        self.assertNotIn("deputy_child_ping", self._tool_names())

    def test_08_diagnostic_mode_registers_git_probe(self):
        self.assertIn("deputy_git_probe", self._tool_names("1"))

    def test_09_diagnostic_mode_registers_child_ping(self):
        self.assertIn("deputy_child_ping", self._tool_names("1"))

    def test_10_diagnostic_mode_retains_production_tools(self):
        self.assertTrue(set(self._production_names()).issubset(self._tool_names("1")))

    def test_11_start_signature_has_no_diagnostic_switch(self):
        import server
        self.assertNotIn("diagnostic", inspect.signature(server.deputy_recon_start).parameters)

    def test_12_goal_and_workspace_do_not_enable_diagnostics(self):
        import server
        self.assertNotIn("DEPUTYAGENTS_ENABLE_DIAGNOSTICS", inspect.getsource(server.deputy_recon_start))
        with self.assertRaises(TypeError):
            server.deputy_recon_start("goal", "BRIDGE_LAB", enable_diagnostics=True)

    def test_13_server_import_has_no_default_diagnostic_registration(self):
        import server
        self.assertFalse(server.DIAGNOSTICS_ENABLED)
        self.assertNotIn("deputy_git_probe", self._tool_names())

    def test_14_git_probe_accepts_no_caller_arguments(self):
        import server
        self.assertEqual(inspect.signature(server.deputy_git_probe).parameters, {})

    def test_15_git_probe_keeps_fixed_sequence(self):
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        for label in ("upstream", "head", "branch", "worktree_diff", "index_diff", "untracked", "tracked_files"):
            self.assertIn(f'"{label}"', text)

    def test_16_git_probe_has_no_mutating_git_command(self):
        text = (ROOT / "server.py").read_text(encoding="utf-8").lower()
        for command in ("commit", "push", "reset", "checkout", "clean"):
            self.assertNotIn(f'"{command}"', text)

    def test_17_git_probe_does_not_expose_environment_values(self):
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("inherited_git_variable_names", text)
        self.assertNotIn("os.environ[name]", text)

    def test_18_child_ping_accepts_no_caller_command(self):
        import server
        self.assertEqual(inspect.signature(server.deputy_child_ping).parameters, {})

    def test_19_child_ping_uses_fixed_platform_invocations(self):
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('"-I", "-S", "-u"', text)
        self.assertIn('"cmd.exe", "/d", "/c", "echo pong"', text)
        self.assertIn('/bin/sh", "-c", "printf', text)

    def test_20_legacy_sync_recon_remains_registered(self):
        self.assertIn("deputy_recon", self._tool_names())

    def test_21_async_lifecycle_tools_absent_by_default_and_opt_in(self):
        self.assertFalse({"deputy_recon_start", "deputy_recon_status", "deputy_recon_cancel"} & set(self._tool_names()))
        self.assertTrue({"deputy_recon", "deputy_recon_start", "deputy_recon_status", "deputy_recon_cancel"}.issubset(self._tool_names(control="1")))

    def test_22_public_recon_is_goal_only_and_projects_result(self):
        import server
        import inspect
        self.assertEqual(list(inspect.signature(server.deputy_recon).parameters), ["goal"])
        with patch.object(server, "execute", return_value={"status":"PASS", "job_id":"x", "session_id":"secret", "workspace_id":"DEPUTY_SHELL", "text":"Found `app/src/Main.kt`"}) as execute:
            out = server.deputy_recon("find architecture")
        execute.assert_called_once_with(goal="find architecture", workspace_id="DEPUTY_SHELL", worker_profile="RECON")
        self.assertEqual(out, {"status":"PASS", "report":"Found `app/src/Main.kt`"})

    def test_22_runtime_marker_is_surface_one(self):
        import server
        self.assertEqual(server.RUNTIME_CONTRACT_VERSION, "DA-PRIVACY-1")


if __name__ == "__main__":
    unittest.main()
