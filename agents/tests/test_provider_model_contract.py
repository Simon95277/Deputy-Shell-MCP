from __future__ import annotations

import asyncio
import inspect
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def catalog_model(model_id="big-pickle", model_type="chat", tools=True, input_price=0, output_price=0):
    return {
        "id": model_id,
        "name": model_id.replace("-", " ").title(),
        "owned_by": "opencode",
        "type": model_type,
        "cost": {
            "text": {
                "input": {"price": input_price, "cache": {"read": 0, "write": 0}},
                "output": {"price": output_price},
            }
        },
        "capabilities": {"tools": {"supported": tools}},
    }


class ProviderModelContractTests(unittest.TestCase):
    def test_01_provider_is_server_owned_and_exact(self):
        from bridge.provider_contract import PROVIDER_ID
        self.assertEqual(PROVIDER_ID, "opencode")

    def test_02_selector_uses_fixed_provider_and_selected_model(self):
        from bridge.provider_contract import model_selector
        self.assertEqual(model_selector("big-pickle"), "opencode/big-pickle")

    def test_03_public_recon_has_only_goal_parameter(self):
        import server
        self.assertEqual(list(inspect.signature(server.deputy_recon).parameters), ["goal"])

    def test_04_public_recon_has_no_provider_or_endpoint_parameters(self):
        import server
        self.assertFalse(set(inspect.signature(server.deputy_recon).parameters) & {"provider", "model", "endpoint"})

    def test_05_owner_async_start_has_no_model_selector_parameter(self):
        import server
        self.assertEqual(list(inspect.signature(server.deputy_recon_start).parameters), ["goal", "workspace_id"])

    def test_06_goal_is_not_parsed_as_cli_flags(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "use --model malicious/model --provider malicious", "big-pickle")
        self.assertEqual(argv[-1], "use --model malicious/model --provider malicious")
        self.assertEqual(argv.count("--model"), 1)

    def test_07_goal_cannot_change_selected_model(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "use opencode/other-model", "big-pickle")
        self.assertEqual(argv[argv.index("--model") + 1], "opencode/big-pickle")
        self.assertNotIn("opencode/other-model", argv[:-1])

    def test_08_cli_model_selection_is_present_once(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "goal", "big-pickle")
        self.assertEqual(argv[argv.index("--model") + 1], "opencode/big-pickle")
        self.assertEqual(argv.count("--model"), 1)

    def test_09_fixed_agent_and_workspace_are_present(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "goal", "big-pickle")
        self.assertEqual(argv[argv.index("--agent") + 1], "plan")
        self.assertEqual(argv[argv.index("--dir") + 1], "/workspace")

    def test_10_inline_config_uses_selected_model_and_is_secret_free(self):
        from bridge.provider_contract import inline_config_content
        content = inline_config_content("big-pickle")
        value = json.loads(content)
        self.assertEqual(value["model"], "opencode/big-pickle")
        self.assertEqual(value["agent"]["plan"]["model"], "opencode/big-pickle")
        self.assertNotIn("token", content.lower())
        self.assertNotIn("credential", content.lower())

    def test_11_inline_config_is_injected_server_side(self):
        from bridge.core import build_argv
        from bridge.provider_contract import inline_config_content
        argv = build_argv(Path("job"), "goal", "big-pickle")
        value = next(x for x in argv if x.startswith("OPENCODE_CONFIG_CONTENT="))
        self.assertEqual(value, "OPENCODE_CONFIG_CONTENT=" + inline_config_content("big-pickle"))

    def test_12_no_arbitrary_host_environment_is_forwarded(self):
        from bridge.core import build_argv
        argv = build_argv(Path("job"), "goal", "big-pickle")
        env_values = [argv[i + 1] for i, item in enumerate(argv[:-1]) if item == "-e"]
        self.assertEqual(set(env_values), {
            "HTTP_PROXY=http://PROXY:3128", "HTTPS_PROXY=http://PROXY:3128",
            "NO_PROXY=localhost,127.0.0.1,::1",
            next(x for x in env_values if x.startswith("OPENCODE_CONFIG_CONTENT=")),
        })

    def test_13_provider_host_remains_exact(self):
        from bridge.provider_contract import PROVIDER_HOST
        self.assertEqual(PROVIDER_HOST, "opencode.ai")

    def test_14_workspace_override_fixture_is_actual_filename(self):
        fixture = ROOT / "tests" / "fixtures" / "provider_override" / "opencode.json"
        self.assertTrue(fixture.exists())
        self.assertEqual(fixture.name, "opencode.json")

    def test_15_server_inline_config_wins_over_fixture_contract(self):
        from bridge.provider_contract import inline_config_content
        malicious = json.loads((ROOT / "tests" / "fixtures" / "provider_override" / "opencode.json").read_text())
        enforced = json.loads(inline_config_content("big-pickle"))
        self.assertNotEqual(malicious["model"], enforced["model"])
        self.assertEqual(enforced["model"], "opencode/big-pickle")

    def test_16_unobserved_identity_is_not_claimed_verified(self):
        from bridge.provider_contract import evidence
        out = evidence("big-pickle")
        self.assertTrue(out["selection_enforced"])
        self.assertFalse(out["runtime_identity_observable"])
        self.assertFalse(out["verified"])

    def test_17_observed_matching_identity_is_verified(self):
        from bridge.provider_contract import evidence
        out = evidence("big-pickle", "opencode", "big-pickle")
        self.assertTrue(out["runtime_identity_observable"])
        self.assertTrue(out["observed_matches_configured"])
        self.assertTrue(out["verified"])

    def test_18_observed_mismatch_is_not_verified(self):
        from bridge.provider_contract import evidence
        out = evidence("big-pickle", "other", "other-model")
        self.assertTrue(out["runtime_identity_observable"])
        self.assertFalse(out["observed_matches_configured"])
        self.assertFalse(out["verified"])

    def test_19_event_metadata_is_parsed_when_present(self):
        from bridge.core import parse_events
        out = parse_events('{"type":"step_start","sessionID":"s","providerID":"opencode","modelID":"big-pickle"}\n')
        self.assertEqual(out["observed_provider"], "opencode")
        self.assertEqual(out["observed_model"], "big-pickle")

    def test_20_fixed_provider_contract_passes_without_a_selected_model(self):
        from bridge.provider_contract import validate_contract
        validate_contract()

    def test_21_invalid_provider_fails_closed(self):
        from bridge import provider_contract
        with patch.object(provider_contract, "PROVIDER_ID", "malicious/provider"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_PROVIDER"):
                provider_contract.validate_contract()

    def test_22_invalid_model_id_fails_closed(self):
        from bridge.provider_contract import model_selector
        with self.assertRaisesRegex(RuntimeError, "INVALID_MODEL"):
            model_selector("malicious/model")

    def test_23_invalid_host_fails_closed(self):
        from bridge import provider_contract
        with patch.object(provider_contract, "PROVIDER_HOST", "other.example"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_HOST"):
                provider_contract.validate_contract()

    def test_24_provider_contract_does_not_define_a_fallback(self):
        text = (ROOT / "bridge" / "provider_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("fallback", text.lower())

    def test_25_adapter_evidence_contains_selection_without_credentials(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        for marker in ("provider_id", "model_id", "selection_source", "selection_method", "provider_host"):
            self.assertIn(marker, text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("Bearer", text)

    def test_26_network_contract_keeps_provider_host_fixed(self):
        text = (ROOT / "bridge" / "executor.py").read_text(encoding="utf-8")
        self.assertIn("PROVIDER_HOST", text)
        self.assertIn('"policy":"PROVIDER_ONLY"', text)

    def test_27_runtime_and_snapshot_contract_markers_remain(self):
        import server
        import snapshot
        self.assertEqual(server.RUNTIME_CONTRACT_VERSION, "DA-PRIVACY-1")
        self.assertEqual(snapshot.COHERENCE_VERSION, "DA-BYTE-COHERENCE-1")
        self.assertEqual(snapshot.POLICY_VERSION, "DA-PRIVACY-1-positive-policy-v1")

    def test_28_catalog_includes_only_zero_price_opencode_chat_or_decision_models(self):
        from bridge import model_catalog
        entries = [catalog_model(), catalog_model("paid-model", input_price=0.1),
                   catalog_model("foreign-free") | {"owned_by": "other"},
                   catalog_model("jev-1.13-free", model_type="decision", tools=False)]
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return model_catalog.CATALOG_URL
        class Opener:
            def open(self, request, timeout):
                self.timeout = timeout
                return Response(json.dumps({"data": entries}).encode())
        opener = Opener()
        with patch.object(model_catalog, "build_opener", return_value=opener):
            models = model_catalog._free_agent_models()
        self.assertEqual({item["model_id"] for item in models}, {"big-pickle", "jev-1.13-free"})
        self.assertTrue(next(item for item in models if item["model_id"] == "big-pickle")["recon_compatible"])
        self.assertFalse(next(item for item in models if item["model_id"] == "jev-1.13-free")["recon_compatible"])
        self.assertEqual(opener.timeout, model_catalog.CATALOG_TIMEOUT_SECONDS)

    def test_29_decision_only_model_is_not_recon_compatible(self):
        from bridge import model_catalog
        with patch.object(model_catalog, "_free_agent_models", return_value=[{
            "model_id": "jev-1.13-free", "name": "Jev 1.13 Free", "type": "decision", "recon_compatible": False
        }]):
            with self.assertRaisesRegex(model_catalog.ModelCatalogError, "MODEL_NOT_RECON_COMPATIBLE"):
                model_catalog.require_recon_model("jev-1.13-free")

    def test_30_nonzero_price_model_is_not_selectable(self):
        from bridge import model_catalog
        with patch.object(model_catalog, "_free_agent_models", return_value=[]):
            with self.assertRaisesRegex(model_catalog.ModelCatalogError, "MODEL_NOT_CURRENTLY_FREE"):
                model_catalog.require_recon_model("paid-model")

    def test_31_model_preference_persists_only_model_id(self):
        from bridge import model_preference
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime" / "selection.json"
            with patch.object(model_preference, "MODEL_SELECTION_PATH", path):
                selected_at = model_preference.save_model_id("big-pickle")
                self.assertEqual(model_preference.load_model_id(), "big-pickle")
            value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(value["schema"], model_preference.SCHEMA)
        self.assertEqual(value["provider_id"], "opencode")
        self.assertEqual(value["model_id"], "big-pickle")
        self.assertEqual(value["selected_at_utc"], selected_at)
        self.assertEqual(set(value), {"schema", "provider_id", "model_id", "selected_at_utc"})

    def test_32_invalid_model_preference_fails_closed(self):
        from bridge import model_preference
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "selection.json"
            path.write_text('{"schema":"wrong"}', encoding="utf-8")
            with patch.object(model_preference, "MODEL_SELECTION_PATH", path):
                with self.assertRaisesRegex(model_preference.ModelPreferenceError, "MODEL_SELECTION_STATE_INVALID"):
                    model_preference.load_model_id()

    def test_33_default_mcp_inventory_has_catalog_selector_and_recon(self):
        import server
        names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(names, {"deputy_models", "deputy_select_model", "deputy_recon"})

    def test_34_recon_reuses_saved_choice_without_model_argument(self):
        import server
        with patch.object(server, "load_model_id", return_value="big-pickle"), patch.object(server, "execute", return_value={
            "status": "PASS", "text": "report", "inference_contract": {"model_id": "big-pickle"}
        }) as execute:
            result = server.deputy_recon("inspect source")
        execute.assert_called_once_with(goal="inspect source", workspace_id="DEPUTY_SHELL", worker_profile="RECON", model_id="big-pickle")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["model_id"], "big-pickle")

    def test_35_missing_preference_returns_catalog_without_running_recon(self):
        import server
        with patch.object(server, "load_model_id", return_value=None), patch.object(server, "list_free_models", return_value={"models": [{"model_id": "big-pickle"}]}) as catalog, patch.object(server, "execute") as execute:
            result = server.deputy_recon("inspect source")
        catalog.assert_called_once_with()
        execute.assert_not_called()
        self.assertEqual(result["code"], "MODEL_SELECTION_REQUIRED")
        self.assertEqual(result["models"], [{"model_id": "big-pickle"}])

    def test_36_stale_preference_blocks_and_returns_current_catalog(self):
        from bridge.model_catalog import ModelCatalogError
        import server
        with patch.object(server, "load_model_id", return_value="retired-model"), patch.object(server, "execute", side_effect=ModelCatalogError("MODEL_NOT_CURRENTLY_FREE")), patch.object(server, "list_free_models", return_value={"models": [{"model_id": "big-pickle"}]}):
            result = server.deputy_recon("inspect source")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["code"], "MODEL_SELECTION_REQUIRED")
        self.assertEqual(result["previous_model_id"], "retired-model")
        self.assertEqual(result["models"], [{"model_id": "big-pickle"}])

    def test_37_selector_saves_only_catalog_approved_model(self):
        import server
        selected = {"model_id": "big-pickle", "name": "Big Pickle"}
        with patch.object(server, "require_recon_model", return_value=selected), patch.object(server, "save_model_id", return_value="2026-11-22T00:00:00+00:00") as save:
            result = server.deputy_select_model("big-pickle")
        save.assert_called_once_with("big-pickle")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["model_id"], "big-pickle")


if __name__ == "__main__":
    unittest.main()
