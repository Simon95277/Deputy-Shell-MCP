import json
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ProviderModelContractTests(unittest.TestCase):
    def test_01_provider_is_server_owned_and_exact(self):
        from bridge.provider_contract import PROVIDER_ID
        self.assertEqual(PROVIDER_ID, "opencode")

    def test_02_model_is_server_owned_and_exact(self):
        from bridge.provider_contract import MODEL_ID
        self.assertEqual(MODEL_ID, "muse-spark-1.3-contributor-free")

    def test_03_selector_is_provider_model(self):
        from bridge.provider_contract import MODEL_SELECTOR
        self.assertEqual(MODEL_SELECTOR, "opencode/muse-spark-1.3-contributor-free")

    def test_04_public_recon_has_no_provider_parameter(self):
        import server
        self.assertNotIn("provider", inspect.signature(server.deputy_recon).parameters)

    def test_05_public_recon_has_no_model_parameter(self):
        import server
        self.assertNotIn("model", inspect.signature(server.deputy_recon).parameters)

    def test_06_public_recon_has_no_endpoint_parameter(self):
        import server
        self.assertNotIn("endpoint", inspect.signature(server.deputy_recon).parameters)

    def test_07_start_has_no_provider_model_or_endpoint_parameters(self):
        import server
        names = set(inspect.signature(server.deputy_recon_start).parameters)
        self.assertFalse(names & {"provider", "model", "endpoint", "config_path", "credential"})

    def test_08_goal_is_not_parsed_as_cli_flags(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "use --model malicious/model --provider malicious")
        self.assertEqual(argv[-1], "use --model malicious/model --provider malicious")
        self.assertEqual(argv.count("--model"), 1)

    def test_09_goal_cannot_change_selector(self):
        from bridge.core import build_argv
        from bridge.provider_contract import MODEL_SELECTOR
        argv = build_argv(Path("job"), "use opencode/other-model")
        self.assertIn(MODEL_SELECTOR, argv)
        self.assertNotIn("opencode/other-model", argv[:-1])

    def test_10_cli_model_selection_is_present_once(self):
        from bridge.core import build_argv
        from bridge.provider_contract import MODEL_SELECTOR
        argv = build_argv(Path("job"), "goal")
        self.assertEqual(argv[argv.index("--model") + 1], MODEL_SELECTOR)
        self.assertEqual(argv.count("--model"), 1)

    def test_11_fixed_agent_and_workspace_are_present(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "goal")
        self.assertEqual(argv[argv.index("--agent") + 1], "plan")
        self.assertEqual(argv[argv.index("--dir") + 1], "/workspace")

    def test_12_inline_config_is_secret_free_and_exact(self):
        from bridge.provider_contract import inline_config_content, MODEL_SELECTOR
        value = json.loads(inline_config_content())
        self.assertEqual(value["model"], MODEL_SELECTOR)
        self.assertEqual(value["agent"]["plan"]["model"], MODEL_SELECTOR)
        self.assertNotIn("token", inline_config_content().lower())
        self.assertNotIn("credential", inline_config_content().lower())

    def test_13_inline_config_is_injected_server_side(self):
        from bridge.core import build_argv
        from bridge.provider_contract import inline_config_content
        argv = build_argv(Path("job"), "goal")
        value = argv[argv.index("OPENCODE_CONFIG_CONTENT=") + 1] if "OPENCODE_CONFIG_CONTENT=" in argv else next(x for x in argv if x.startswith("OPENCODE_CONFIG_CONTENT="))
        self.assertEqual(value, "OPENCODE_CONFIG_CONTENT=" + inline_config_content())

    def test_14_no_arbitrary_host_environment_is_forwarded(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "goal")
        env_values = [argv[i + 1] for i, item in enumerate(argv[:-1]) if item == "-e"]
        self.assertEqual(set(env_values), {"HTTP_PROXY=http://PROXY:3128", "HTTPS_PROXY=http://PROXY:3128", "NO_PROXY=localhost,127.0.0.1,::1", next(x for x in env_values if x.startswith("OPENCODE_CONFIG_CONTENT="))})

    def test_15_provider_host_remains_exact(self):
        from bridge.provider_contract import PROVIDER_HOST
        self.assertEqual(PROVIDER_HOST, "opencode.ai")

    def test_16_workspace_override_fixture_is_the_actual_filename(self):
        fixture = ROOT / "tests" / "fixtures" / "provider_override" / "opencode.json"
        self.assertTrue(fixture.exists())
        self.assertEqual(fixture.name, "opencode.json")

    def test_17_server_inline_config_wins_over_fixture_contract(self):
        from bridge.provider_contract import inline_config_content, MODEL_SELECTOR
        malicious = json.loads((ROOT / "tests" / "fixtures" / "provider_override" / "opencode.json").read_text())
        enforced = json.loads(inline_config_content())
        self.assertNotEqual(malicious["model"], MODEL_SELECTOR)
        self.assertEqual(enforced["model"], MODEL_SELECTOR)

    def test_18_unobserved_identity_is_not_claimed_verified(self):
        from bridge.provider_contract import evidence
        out = evidence()
        self.assertTrue(out["selection_enforced"])
        self.assertFalse(out["runtime_identity_observable"])
        self.assertFalse(out["verified"])

    def test_19_observed_matching_identity_is_verified(self):
        from bridge.provider_contract import evidence
        out = evidence("opencode", "muse-spark-1.3-contributor-free")
        self.assertTrue(out["runtime_identity_observable"])
        self.assertTrue(out["observed_matches_configured"])
        self.assertTrue(out["verified"])

    def test_20_observed_mismatch_is_not_verified(self):
        from bridge.provider_contract import evidence
        out = evidence("other", "other-model")
        self.assertTrue(out["runtime_identity_observable"])
        self.assertFalse(out["observed_matches_configured"])
        self.assertFalse(out["verified"])

    def test_21_event_metadata_is_parsed_when_present(self):
        from bridge.core import parse_events
        out = parse_events('{"type":"step_start","sessionID":"s","providerID":"opencode","modelID":"muse-spark-1.3-contributor-free"}\n')
        self.assertEqual(out["observed_provider"], "opencode")
        self.assertEqual(out["observed_model"], "muse-spark-1.3-contributor-free")

    def test_22_missing_contract_fails_closed(self):
        from bridge import provider_contract
        with patch.object(provider_contract, "MODEL_ID", ""):
            with self.assertRaisesRegex(RuntimeError, "INVALID_MODEL"):
                provider_contract.validate_contract()

    def test_23_invalid_provider_fails_closed(self):
        from bridge import provider_contract
        with patch.object(provider_contract, "PROVIDER_ID", "malicious/provider"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_PROVIDER"):
                provider_contract.validate_contract()

    def test_24_invalid_model_fails_closed(self):
        from bridge import provider_contract
        with patch.object(provider_contract, "MODEL_ID", "malicious/model"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_MODEL"):
                provider_contract.validate_contract()

    def test_25_invalid_host_fails_closed(self):
        from bridge import provider_contract
        with patch.object(provider_contract, "PROVIDER_HOST", "other.example"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_HOST"):
                provider_contract.validate_contract()

    def test_26_provider_contract_does_not_define_fallback(self):
        text = (ROOT / "bridge" / "provider_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("fallback", text.lower())

    def test_27_adapter_evidence_contains_contract_without_credentials(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        for marker in ("provider_id", "model_id", "selection_source", "selection_method", "provider_host"):
            self.assertIn(marker, text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("Bearer", text)

    def test_28_network_contract_does_not_widen_host(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        self.assertIn('PROVIDER_HOST', text)
        self.assertIn('"policy":"PROVIDER_ONLY"', text)

    def test_29_runtime_marker_is_provider_contract(self):
        import server
        self.assertEqual(server.RUNTIME_CONTRACT_VERSION, "DA-PACKAGING-1")

    def test_30_coherence_and_snapshot_policy_markers_unchanged(self):
        import snapshot
        self.assertEqual(snapshot.COHERENCE_VERSION, "DA-BYTE-COHERENCE-1")
        self.assertEqual(snapshot.POLICY_VERSION, "DA-FAST-2-positive-allowlist-v1")


if __name__ == "__main__":
    unittest.main()
