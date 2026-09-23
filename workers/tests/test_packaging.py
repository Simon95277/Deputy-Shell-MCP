import unittest
from pathlib import Path

import config
import preflight
import server
from worker_v1.capabilities import REGISTRY_PATH, load_registry


class WorkersPackagingTests(unittest.TestCase):
    def test_runtime_default_is_outside_package(self):
        package = Path(config.__file__).resolve().parent
        default = config.default_runtime_root()
        self.assertTrue(default.is_absolute())
        self.assertNotIn(package, default.resolve().parents)
        self.assertNotEqual(package, default.resolve())

    def test_evidence_root_is_under_runtime_root(self):
        self.assertIn(config.RUNTIME_ROOT.resolve(), config.EVIDENCE_ROOT.resolve().parents)

    def test_registry_is_available_and_frozen(self):
        self.assertTrue(REGISTRY_PATH.is_file())
        self.assertEqual(len(load_registry()), 22)

    def test_entrypoint_rejects_authority_arguments(self):
        self.assertEqual(server.main(["--repo-root", "C:\\arbitrary"]), 2)

    def test_preflight_is_read_only(self):
        result = preflight.check()
        self.assertFalse(result["mutated_external_state"])
        self.assertEqual(result["capability_count"], 22)

    def test_packaged_runtime_modules_are_declared(self):
        text = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('py-modules = ["server", "config", "preflight"]', text)
        self.assertIn('deputy-workers-mcp = "server:main"', text)

    def test_default_runtime_is_not_source_runtime(self):
        self.assertNotEqual(config.default_runtime_root(), config.PACKAGE_ROOT / "runtime")


if __name__ == "__main__":
    unittest.main()
