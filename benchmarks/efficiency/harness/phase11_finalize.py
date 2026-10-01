from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_records(runs_dir: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(runs_dir.glob("run-*/result.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _sum(records: list[dict[str, Any]], field: str) -> int:
    values = [record["supervisor"][field] for record in records]
    if not all(isinstance(value, int) for value in values):
        raise ValueError(f"unmeasured supervisor field: {field}")
    return sum(values)


def summarize_e6(records: list[dict[str, Any]]) -> dict[str, Any]:
    if len(records) != 10:
        raise ValueError(f"expected 10 E6 records, found {len(records)}")
    keys = {(r["case_id"], r["arm"], r["repetition"]) for r in records}
    if len(keys) != len(records) or any(r["case_id"] != "E6" for r in records):
        raise ValueError("invalid or duplicate E6 records")
    direct = {
        r["repetition"]: r for r in records
        if r["arm"] == "DIRECT" and r["result"]["status"] == "PASS"
    }
    deputy = {
        r["repetition"]: r for r in records
        if r["arm"] == "DEPUTY" and r["result"]["status"] == "PASS"
    }
    reps = sorted(direct.keys() & deputy.keys())
    drows = [direct[rep] for rep in reps]
    prows = [deputy[rep] for rep in reps]
    dt = _sum(drows, "total_tokens") if drows else 0
    pt = _sum(prows, "total_tokens") if prows else 0

    statuses = ("PASS", "FAIL", "BLOCKED", "BENCHMARK_PROTOCOL_VIOLATION")
    reliability = {
        arm: {
            status: sum(r["arm"] == arm and r["result"]["status"] == status for r in records)
            for status in statuses
        }
        for arm in ("DIRECT", "DEPUTY")
    }
    return {
        "accounted_slots": len(records),
        "reliability": reliability,
        "valid_pair_repetitions": reps,
        "valid_pair_count": len(reps),
        "direct_total_tokens": dt,
        "deputy_total_tokens": pt,
        "deputy_percent_delta": ((pt - dt) / dt * 100) if dt else None,
        "direct_input_tokens": _sum(drows, "input_tokens") if drows else 0,
        "deputy_input_tokens": _sum(prows, "input_tokens") if prows else 0,
        "direct_output_tokens": _sum(drows, "output_tokens") if drows else 0,
        "deputy_output_tokens": _sum(prows, "output_tokens") if prows else 0,
        "direct_cached_input_tokens": _sum(drows, "cached_input_tokens") if drows else 0,
        "deputy_cached_input_tokens": _sum(prows, "cached_input_tokens") if prows else 0,
        "direct_mcp_calls": sum(r["execution"]["mcp_calls"] for r in drows),
        "deputy_mcp_calls": sum(r["execution"]["mcp_calls"] for r in prows),
        "direct_payload_bytes": sum(r["execution"]["mcp_result_payload_bytes"] for r in drows),
        "deputy_payload_bytes": sum(r["execution"]["mcp_result_payload_bytes"] for r in prows),
    }


def build_final(e6: dict[str, Any], d8: dict[str, Any]) -> dict[str, Any]:
    e1e5 = d8["valid_paired_efficiency"]["OVERALL_ELIGIBLE_E1_E5"]
    combined_direct = e1e5["direct_total_tokens"] + e6["direct_total_tokens"]
    combined_deputy = e1e5["deputy_total_tokens"] + e6["deputy_total_tokens"]
    status = "COMPLETE" if e6["valid_pair_count"] > 0 else "BLOCKED"
    return {
        "schema": "deputy.efficiency.phase11-postprocess.v1",
        "phase11_disposition": f"DEPUTY_MCP_EFFICIENCY_BENCHMARK_{status}",
        "e6": e6,
        "d8_e1_e5": e1e5,
        "combined_valid_pairs": {
            "direct_total_tokens": combined_direct,
            "deputy_total_tokens": combined_deputy,
            "deputy_percent_delta": (combined_deputy - combined_direct) / combined_direct * 100,
        },
        "context_telemetry": "UNMEASURED",
        "delegate_token_telemetry": "UNMEASURED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase11f", type=Path, required=True)
    parser.add_argument("--d8-final", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = _load_records(args.phase11f / "runs")
    d8 = json.loads(args.d8_final.read_text(encoding="utf-8"))
    result = build_final(summarize_e6(records), d8)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
