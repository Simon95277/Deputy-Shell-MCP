import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "benchmarks" / "efficiency" / "harness" / "phase11_finalize.py"
SPEC = importlib.util.spec_from_file_location("phase11_finalize", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def record(arm, repetition, status, total, input_tokens, output_tokens, cached, mcp_calls=0, payload=0):
    return {
        "case_id": "E6",
        "arm": arm,
        "repetition": repetition,
        "result": {"status": status},
        "supervisor": {
            "total_tokens": total,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached,
        },
        "execution": {"mcp_calls": mcp_calls, "mcp_result_payload_bytes": payload},
    }


class Phase11FinalizeTests(unittest.TestCase):
    def test_valid_pairs_and_status_are_computed_without_self_reference(self):
        rows = []
        for rep in range(1, 6):
            rows.append(record("DIRECT", rep, "PASS" if rep in {1, 5} else "FAIL",
                               100 + rep, 90 + rep, 10, 50))
            rows.append(record("DEPUTY", rep, "PASS" if rep in {1, 5} else "FAIL",
                               110 + rep, 100 + rep, 10, 60, 4, 500))
        summary = MODULE.summarize_e6(rows)
        self.assertEqual(summary["valid_pair_repetitions"], [1, 5])
        self.assertEqual(summary["valid_pair_count"], 2)

        d8 = {"valid_paired_efficiency": {"OVERALL_ELIGIBLE_E1_E5": {
            "direct_total_tokens": 1000,
            "deputy_total_tokens": 900,
        }}}
        final = MODULE.build_final(summary, d8)
        self.assertEqual(final["phase11_disposition"], "DEPUTY_MCP_EFFICIENCY_BENCHMARK_COMPLETE")

    def test_duplicate_slot_is_rejected(self):
        rows = [record("DIRECT", 1, "PASS", 1, 1, 0, 0)] * 10
        with self.assertRaises(ValueError):
            MODULE.summarize_e6(rows)


if __name__ == "__main__":
    unittest.main()
