import os
import tempfile
import unittest
from pathlib import Path

import config
import preflight
import server
from bridge import executor


class AgentsPackagingTests(unittest.TestCase):
    def test_runtime_default_is_outside_package(self):
        package = Path(config.__file__).resolve().parent
        self.assertTrue(config.RUNTIME_ROOT.is_absolute())
        self.assertNotIn(package, config.RUNTIME_ROOT.resolve().parents)
        self.assertNotEqual(package, config.RUNTIME_ROOT.resolve())

    def test_all_runtime_roots_are_derived_from_runtime_root(self):
        runtime = config.RUNTIME_ROOT.resolve()
        for root in (config.BRIDGE_ROOT, config.EVIDENCE_ROOT, config.JOB_STATE_ROOT, config.SNAPSHOT_ROOT):
            self.assertTrue(root.is_absolute())
            self.assertIn(runtime, root.resolve().parents)

    def test_evidence_root_is_shared_by_executor_and_server(self):
        self.assertIs(executor.EVIDENCE_ROOT, config.EVIDENCE_ROOT)
        self.assertEqual(server.EVIDENCE_ROOT, config.EVIDENCE_ROOT)

    def test_runtime_root_override_is_server_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(config.configured_path("UNUSED_TEST_ROOT", Path(td)), Path(td))

    def test_entrypoint_rejects_authority_arguments(self):
        self.assertEqual(server.main(["--runtime-root", "C:\\arbitrary"]), 2)

    def test_check_does_not_mutate_external_state(self):
        before = set(Path(tempfile.gettempdir()).iterdir())
        result = preflight.check()
        after = set(Path(tempfile.gettempdir()).iterdir())
        self.assertFalse(result["mutated_external_state"])
        self.assertEqual(before, after)

    def test_provider_marker_is_packaging_generation(self):
        self.assertEqual(server.RUNTIME_CONTRACT_VERSION, "DA-PACKAGING-1")


if __name__ == "__main__":
    unittest.main()
