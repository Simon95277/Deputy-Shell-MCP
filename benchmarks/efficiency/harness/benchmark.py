#!/usr/bin/env python3
"""Deterministic fixture, independent graders, telemetry checks and aggregation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
FIXTURE = HERE / "fixture"
CASES = HERE / "cases"
RUN_SCHEMA = "deputy.mcp.efficiency-run.v1"
E4_ALLOW = {
    "caller_selects_intent": {"app/src/main/java/benchmark/api/CallerRequest.kt"},
    "caller_selects_executable": {"app/src/main/java/benchmark/execution/Executor.kt"},
    "caller_selects_argv": {"app/src/main/java/benchmark/execution/Executor.kt"},
    "caller_selects_arbitrary_path": {"app/src/main/java/benchmark/api/CallerRequest.kt", "app/src/main/java/benchmark/execution/Executor.kt", "app/src/main/java/benchmark/privacy/SourceSelector.kt"},
    "registry_allowlist_enforced": {"app/src/main/java/benchmark/policy/CapabilityRegistry.kt"},
    "generic_shell_exposed": {"tools/benchmark/authority-policy.md", "app/src/main/java/benchmark/api/CallerRequest.kt", "app/src/main/java/benchmark/execution/Executor.kt"},
}
E4_VALUES = {"caller_selects_intent": True, "caller_selects_executable": False,
             "caller_selects_argv": False, "caller_selects_arbitrary_path": False,
             "registry_allowlist_enforced": True, "generic_shell_exposed": False}
E5_STAGES = ["SOURCE_SELECTION", "CANDIDATE_COPY", "SECRET_SCAN", "SOURCE_AFTER_VALIDATION",
             "BYTE_COHERENCE", "SNAPSHOT_PUBLICATION", "PROVIDER_INVOCATION"]
E5_VALUES = {"secret_scan_before_provider": True, "source_after_validation_before_publication": True,
             "caller_can_select_source_policy": False, "caller_can_select_provider": False,
             "caller_can_select_model": False}
EXPECTED_E6 = {"decision": "REJECT", "violations": ["CALLER_SELECTED_ARGV", "CALLER_SELECTED_EXECUTABLE"]}
EXPECTED_DEPUTY_TRACE = {
    "E1": [("deputy_observe", "CHECK_FILE"), ("deputy_observe", "HASH_ARTIFACT")],
    "E2": [("deputy_observe", "CAPTURE_REPO_STATE")],
    "E3": [("deputy_observe", "PARSE_JUNIT")],
    "E4": [("deputy_recon", None)],
    "E5": [("deputy_recon", None)],
    "E6": [("deputy_observe", "CAPTURE_REPO_STATE"),
           ("deputy_observe", "CHECK_FILE"),
           ("deputy_observe", "HASH_ARTIFACT"),
           ("deputy_recon", None)],
}
EXPECTED_E6_STAGE_A_TRACE = EXPECTED_DEPUTY_TRACE["E6"]


def prompt_for_arm(case: dict[str, Any], arm: str, stage: str | None = None) -> str:
    """Select only route-specific E6 evidence instructions; Stage B stays common."""
    if arm not in {"DIRECT", "DEPUTY"}:
        raise ValueError("BENCHMARK_ARM_INVALID")
    if case.get("case_id") == "E6" and stage == "stage_a":
        key = "stage_a_direct" if arm == "DIRECT" else "stage_a_deputy"
    else:
        key = "prompt" if stage is None else stage
    value = case.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("BENCHMARK_PROMPT_MISSING")
    return value
EXPECTED_OPERATIONS = {
    "E1": ("DIRECT", (0, 0)), "E2": ("DIRECT", (0, 0)), "E3": ("DIRECT", (0, 0)),
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_run_records(directory: Path) -> list[dict[str, Any]]:
    """Load bounded benchmark records from current or preserved campaign slots."""
    records: list[dict[str, Any]] = []
    valid_cases = {"E1", "E2", "E3", "E4", "E5", "E6"}
    for slot_dir in sorted(path for path in directory.glob("run-*") if path.is_dir()):
        result_path = slot_dir / "result.json"
        record_path = slot_dir / "record.json"
        selected = result_path if result_path.is_file() else record_path
        if not selected.is_file():
            continue
        try:
            value = json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("CAMPAIGN_RECORD_INVALID") from exc
        if (not isinstance(value, dict) or value.get("schema") != RUN_SCHEMA
                or value.get("case_id") not in valid_cases
                or value.get("arm") not in {"DIRECT", "DEPUTY"}
                or not isinstance(value.get("repetition"), int)
                or value["repetition"] < 1
                or not all(isinstance(value.get(key), dict)
                           for key in ("execution", "result", "supervisor"))):
            raise ValueError("CAMPAIGN_RECORD_SCHEMA_INVALID")
        records.append(value)
    return records


def run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
    if proc.returncode:
        raise RuntimeError("FIXTURE_GIT_" + (args[0].upper().replace("-", "_")))
    return proc.stdout.strip()


def _junit_fixture(root: Path) -> None:
    report_dir = root / "app/build/test-results/testDebugUnitTest"
    report_dir.mkdir(parents=True, exist_ok=True)
    reports = {
        "TEST-benchmark-a.xml": '''<testsuite name="authority" tests="3" failures="1" errors="0" skipped="1" time="1.250"><testcase classname="bench.RegistryTest" name="fixedMapping" time="0.500"/><testcase classname="bench.RegistryTest" name="rejectUnknown" time="0.250"><skipped message="fixture skip"/></testcase><testcase classname="bench.RegistryTest" name="rejectShell" time="0.500"><failure message="expected synthetic failure">redacted fixture</failure></testcase></testsuite>''',
        "TEST-benchmark-b.xml": '''<testsuite name="privacy" tests="3" failures="0" errors="1" skipped="0" time="2.000"><testcase classname="bench.PrivacyTest" name="scanBeforeSend" time="1.000"/><testcase classname="bench.PrivacyTest" name="stablePolicy" time="0.750"/><testcase classname="bench.PrivacyTest" name="coherence" time="0.250"><error message="synthetic fixture error">redacted fixture</error></testcase></testsuite>''',
    }
    for name, body in reports.items():
        (report_dir / name).write_text(body + "\n", encoding="utf-8", newline="\n")


def prepare_fixture(destination: Path) -> dict[str, Any]:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("FIXTURE_DESTINATION_NOT_EMPTY")
    destination.mkdir(parents=True, exist_ok=True)
    for path in FIXTURE.rglob("*"):
        if path.is_file():
            out = destination / path.relative_to(FIXTURE)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
    _junit_fixture(destination)
    run_git(["init", "--quiet", "--initial-branch=benchmark/efficiency-v1"], destination)
    config = {"core.autocrlf": "false", "user.name": "Deputy Benchmark Fixture",
              "user.email": "benchmark-fixture", "commit.gpgsign": "false"}
    for key, value in config.items():
        run_git(["config", "--local", key, value], destination)
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_NAME": "Deputy Benchmark Fixture", "GIT_COMMITTER_NAME": "Deputy Benchmark Fixture",
                "GIT_AUTHOR_EMAIL": "benchmark-fixture", "GIT_COMMITTER_EMAIL": "benchmark-fixture",
                "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    run_git(["add", "--all"], destination, env)
    run_git(["commit", "--quiet", "--no-gpg-sign", "-m", "Synthetic efficiency benchmark fixture"], destination, env)
    state = capture_repo(destination)
    if state["dirty"]:
        raise RuntimeError("FIXTURE_NOT_CLEAN")
    return {"status": "PASS", "branch": state["branch"], "head": state["head"],
            "dirty": state["dirty"], "fixture_sha256": fixture_digest(destination),
            "files": state["files"]}


def prepare_arm_plan(arm: str, target_root: Path, client_root: Path | None = None) -> dict[str, Any]:
    if target_root.is_symlink():
        raise ValueError("TARGET_FIXTURE_INVALID")
    target = target_root.resolve(strict=True)
    if not target.is_dir():
        raise ValueError("TARGET_FIXTURE_INVALID")
    if arm == "DIRECT":
        if client_root is not None:
            raise ValueError("DIRECT_ARM_CLIENT_ROOT_NOT_ALLOWED")
        return {"arm": "DIRECT", "target_repository_visible_to_supervisor": True,
                "deputy_mcp_available": False, "agents_calls": 0, "workers_calls": 0,
                "target_repository_files": len(capture_repo(target)["files"])}
    if arm != "DEPUTY" or client_root is None:
        raise ValueError("ARM_PLAN_INVALID")
    if client_root.is_symlink():
        raise ValueError("DEPUTY_CLIENT_WORKSPACE_MUST_NOT_BE_SYMLINK")
    client = client_root.resolve()
    if client == target or client.is_relative_to(target) or target.is_relative_to(client):
        raise ValueError("ARM_WORKSPACES_MUST_BE_DISJOINT")
    if client.exists() and any(client.iterdir()):
        raise ValueError("DEPUTY_CLIENT_WORKSPACE_NOT_EMPTY")
    client.mkdir(parents=True, exist_ok=True)
    if any(client.iterdir()):
        raise ValueError("DEPUTY_CLIENT_WORKSPACE_NOT_EMPTY")
    return {"arm": "DEPUTY", "target_repository_visible_to_supervisor": False,
            "deputy_mcp_available": True, "server_owned_target_configuration": [
                "DEPUTYAGENTS_DEPUTY_SHELL_ROOT", "DEPUTYWORKERS_DEPUTY_SHELL_ROOT"],
            "client_workspace_file_count": 0, "workspaces_disjoint": True,
            "mcp_registration_changed": False,
            "note": "Operator must independently verify the selected Codex MCP inventory and server-owner environment."}


def capture_repo(root: Path) -> dict[str, Any]:
    head = run_git(["rev-parse", "HEAD"], root)
    branch = run_git(["branch", "--show-current"], root)
    porcelain = run_git(["status", "--porcelain=v1", "--untracked-files=all"], root)
    diff = subprocess.run(["git", "diff", "--check"], cwd=root, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    if diff.returncode not in (0, 2):
        raise RuntimeError("FIXTURE_DIFF_CHECK_ERROR")
    tracked = run_git(["diff", "--name-only"], root)
    staged = run_git(["diff", "--cached", "--name-only"], root)
    untracked = run_git(["ls-files", "--others", "--exclude-standard"], root)
    files = run_git(["ls-files"], root).splitlines()
    return {"head": head, "branch": branch, "dirty": bool(porcelain), "diff_check_pass": diff.returncode == 0,
            "tracked_diff": tracked.splitlines() if tracked else [], "staged_diff": staged.splitlines() if staged else [],
            "untracked": untracked.splitlines() if untracked else [], "files": files}


def fixture_digest(root: Path) -> str:
    records = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "app/build" not in p.as_posix()):
        records.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)})
    return sha256_bytes(canonical(records))


def _junit_totals(root: Path) -> dict[str, Any]:
    paths = sorted((root / "app/build/test-results/testDebugUnitTest").glob("TEST-*.xml"))
    if len(paths) != 2:
        raise ValueError("JUNIT_REPORT_SET_INVALID")
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    duration = 0.0
    failing: list[dict[str, str]] = []
    for path in paths:
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            raise ValueError("JUNIT_XML_INVALID") from exc
        suite_nodes = [tree.getroot()] if tree.getroot().tag == "testsuite" else list(tree.getroot().findall("testsuite"))
        if not suite_nodes:
            raise ValueError("JUNIT_SUITE_MISSING")
        for suite in suite_nodes:
            for key in totals:
                try:
                    totals[key] += int(suite.attrib.get(key, "0"))
                except ValueError as exc:
                    raise ValueError("JUNIT_COUNT_INVALID") from exc
            try:
                duration += float(suite.attrib.get("time", "0"))
            except ValueError as exc:
                raise ValueError("JUNIT_DURATION_INVALID") from exc
            for case in suite.findall("testcase"):
                for kind in ("failure", "error"):
                    if case.find(kind) is not None:
                        failing.append({"suite": suite.attrib.get("name", ""),
                                        "classname": case.attrib.get("classname", ""),
                                        "name": case.attrib.get("name", ""), "kind": kind})
    failing.sort(key=lambda x: (x["suite"], x["classname"], x["name"], x["kind"]))
    return {"report_status": "FAIL" if totals["failures"] or totals["errors"] else "PASS",
            **totals, "duration_seconds": duration, "failing_testcases": failing}


def expected(case_id: str, root: Path) -> dict[str, Any]:
    root = root.resolve()
    if case_id == "E1":
        path = root / "tools/benchmark/payload.txt"
        return {"case_id": "E1", "exists": path.is_file(),
                "size_bytes": path.stat().st_size if path.is_file() else None,
                "sha256": sha256_file(path) if path.is_file() else None}
    if case_id == "E2":
        state = capture_repo(root)
        return {"case_id": "E2", **{k: state[k] for k in ("head", "branch", "dirty", "diff_check_pass")}}
    if case_id == "E3":
        return {"case_id": "E3", **_junit_totals(root)}
    if case_id == "E4":
        return {"case_id": "E4", "facts": {key: {"value": value, "evidence": sorted(E4_ALLOW[key])[0]}
                                                     for key, value in E4_VALUES.items()}}
    if case_id == "E5":
        return {"case_id": "E5", "ordered_stages": list(E5_STAGES), **E5_VALUES}
    if case_id == "E6A":
        path = root / "tools/benchmark/proposal.json"
        state = capture_repo(root)
        return {"case_id": "E6", "stage": "DECISION_READY", "repository_head": state["head"],
                "repository_branch": state["branch"], "repository_dirty": state["dirty"],
                "diff_check_pass": state["diff_check_pass"], "proposal_exists": path.is_file(),
                "proposal_size_bytes": path.stat().st_size if path.is_file() else None,
                "proposal_sha256": sha256_file(path) if path.is_file() else None,
                "architecture_evidence_sufficient": True}
    if case_id == "E6B":
        return {"case_id": "E6", **EXPECTED_E6}
    raise ValueError("CASE_ID_INVALID")


def grade(case_id: str, answer: Any, root: Path) -> dict[str, Any]:
    if not isinstance(answer, dict):
        return {"status": "FAIL", "checks": {"json_object": False}, "reason": "OUTPUT_NOT_OBJECT"}
    exp = expected(case_id, root)
    checks: dict[str, bool] = {}
    if case_id in {"E1", "E2", "E3", "E5", "E6A", "E6B"}:
        def typed_equal(left: Any, right: Any) -> bool:
            if type(left) is not type(right):
                return False
            if isinstance(left, dict):
                return left.keys() == right.keys() and all(typed_equal(left[k], right[k]) for k in left)
            if isinstance(left, list):
                return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
            return left == right
        checks["exact_schema_and_values"] = typed_equal(answer, exp)
    elif case_id == "E4":
        checks["case_id"] = answer.get("case_id") == "E4"
        facts = answer.get("facts")
        checks["exact_fact_set"] = isinstance(facts, dict) and set(facts) == set(E4_ALLOW)
        evidence_valid = isinstance(facts, dict) and all(
            isinstance(facts.get(k), dict) and set(facts[k]) == {"value", "evidence"}
            and type(facts[k]["value"]) is bool and facts[k]["value"] == E4_VALUES[k]
            and isinstance(facts[k]["evidence"], str) and facts[k]["evidence"] in E4_ALLOW[k]
            and (root / facts[k]["evidence"]).is_file()
            for k in E4_ALLOW)
        checks["values_and_inspected_allowlisted_evidence"] = evidence_valid
    passed = bool(checks) and all(checks.values())
    return {"status": "PASS" if passed else "FAIL", "checks": checks,
            "expected": exp if case_id in {"E1", "E2", "E3", "E5", "E6A", "E6B"} else None,
            "reason": None if passed else "ANSWER_MISMATCH_OR_INVALID"}


def empty_run(case_id: str, arm: str, repetition: int, supervisor_model: str,
              reasoning_effort: str) -> dict[str, Any]:
    if case_id not in {"E1", "E2", "E3", "E4", "E5", "E6"} or arm not in {"DIRECT", "DEPUTY"}:
        raise ValueError("RUN_IDENTITY_INVALID")
    return {"schema": RUN_SCHEMA, "benchmark_version": "EFFICIENCY-BENCHMARK-1", "case_id": case_id,
            "arm": arm, "repetition": repetition,
            "supervisor": {"model": supervisor_model, "reasoning_effort": reasoning_effort,
                           "input_tokens": None, "cached_input_tokens": None, "cache_write_input_tokens": None,
                           "output_tokens": None, "reasoning_output_tokens": None, "total_tokens": None,
                           "token_telemetry": "UNMEASURED"},
            "context": {"model_context_window": None, "baseline_context_tokens": None,
                        "peak_context_tokens": None, "context_growth_tokens": None, "peak_context_percent": None,
                        "compaction_count": None, "decision_context_tokens": None,
                        "decision_context_remaining": None, "telemetry": "UNMEASURED"},
            "delegate": {"provider": None, "model": None, "input_tokens": None, "cache_read_tokens": None,
                         "cache_write_tokens": None, "output_tokens": None, "reasoning_tokens": None,
                         "token_telemetry": "NOT_APPLICABLE" if arm == "DIRECT" else "UNMEASURED"},
            "execution": {"supervisor_turns": 0, "supervisor_tool_calls": 0, "mcp_calls": 0,
                          "agents_calls": 0, "workers_calls": 0, "wall_clock_ms": 0,
                          "direct_target_access": False, "required_subsystems_used": [],
                          "deputy_tool_trace": []},
            "result": {"status": "BLOCKED", "grader_checks": {}, "failure_reason": "NOT_EXECUTED"}}


def validate_protocol(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("schema") != RUN_SCHEMA:
        return {"status": "FAIL", "reason": "RUN_SCHEMA_INVALID"}
    case, arm = record.get("case_id"), record.get("arm")
    ex = record.get("execution", {})
    checks = {"direct_arm_has_zero_mcp": arm != "DIRECT" or ex.get("mcp_calls") == 0,
              "direct_arm_has_target_access": arm != "DIRECT" or ex.get("direct_target_access") is True,
              "deputy_arm_has_no_direct_target_access": arm != "DEPUTY" or ex.get("direct_target_access") is False}
    used = set(ex.get("required_subsystems_used", []))
    if arm == "DEPUTY":
        expected_trace = EXPECTED_DEPUTY_TRACE.get(case)
        expected_agents = sum(tool == "deputy_recon" for tool, _ in expected_trace or [])
        expected_workers = sum(tool == "deputy_observe" for tool, _ in expected_trace or [])
        expected_subsystems = ({"agents"} if expected_agents else set()) | ({"workers"} if expected_workers else set())
        trace = ex.get("deputy_tool_trace")
        trace_key = lambda entry: (entry.get("tool"), entry.get("operation")) if isinstance(entry, dict) else (None, None)
        observed_trace = [trace_key(entry) for entry in trace] if isinstance(trace, list) else []
        checks["required_subsystems"] = expected_trace is not None and used == expected_subsystems
        checks["exact_semantic_tool_trace"] = (expected_trace is not None and isinstance(trace, list)
            and sorted(observed_trace) == sorted(expected_trace))
        checks["semantic_call_counts"] = (ex.get("agents_calls") == expected_agents
            and ex.get("workers_calls") == expected_workers
            and ex.get("mcp_calls") == len(expected_trace or []))
    else:
        checks["direct_mode_has_no_deputy_subsystem"] = not used and ex.get("agents_calls", 0) == 0 and ex.get("workers_calls", 0) == 0
    if case == "E6" and arm == "DEPUTY":
        checks["decision_stage_completed"] = ex.get("e6_stage_a_recorded") is True and ex.get("e6_same_session_stage_b") is True
        checks["stage_a_has_exact_semantic_trace"] = (
            isinstance(ex.get("e6_stage_a_tool_trace"), list)
            and sorted((entry.get("tool"), entry.get("operation"))
                       for entry in ex["e6_stage_a_tool_trace"] if isinstance(entry, dict))
            == sorted(EXPECTED_E6_STAGE_A_TRACE)
            and all(isinstance(entry, dict) for entry in ex["e6_stage_a_tool_trace"]))
        checks["stage_b_has_no_deputy_calls"] = ex.get("e6_stage_b_tool_trace") == []
    passed = all(checks.values())
    return {"status": "PASS" if passed else "BENCHMARK_PROTOCOL_VIOLATION", "checks": checks}


def finalize_record(record: dict[str, Any], case_id: str, answer: Any, root: Path) -> dict[str, Any]:
    protocol = validate_protocol(record)
    if protocol["status"] != "PASS":
        record["result"] = {"status": "BENCHMARK_PROTOCOL_VIOLATION", "grader_checks": protocol["checks"],
                            "failure_reason": "ARM_PROTOCOL_INVALID"}
    else:
        graded = grade(case_id, answer, root)
        record["result"] = {"status": graded["status"], "grader_checks": graded["checks"],
                            "failure_reason": graded.get("reason")}
    return enforce_missing_telemetry(record)


def enforce_missing_telemetry(record: dict[str, Any]) -> dict[str, Any]:
    sup = record["supervisor"]
    token_fields = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
                    "reasoning_output_tokens", "total_tokens")
    if any(sup.get(key) is None for key in token_fields):
        sup["token_telemetry"] = "UNMEASURED"
    ctx = record["context"]
    ctx_fields = ("model_context_window", "baseline_context_tokens", "peak_context_tokens",
                  "context_growth_tokens", "peak_context_percent", "compaction_count")
    if any(ctx.get(key) is None for key in ctx_fields):
        ctx["telemetry"] = "PARTIAL" if any(ctx.get(key) is not None for key in ctx_fields) else "UNMEASURED"
    dep = record["delegate"]
    if record["arm"] == "DEPUTY" and any(dep.get(key) is None for key in
            ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")):
        dep["token_telemetry"] = "PARTIAL" if any(dep.get(key) is not None for key in
            ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")) else "UNMEASURED"
    # Cache and reasoning counters are breakdowns, not additional inference tokens.
    child_total = ((dep.get("input_tokens") or 0) + (dep.get("output_tokens") or 0)
                   if dep.get("token_telemetry") == "MEASURED" else None)
    record["total_inference_tokens"] = None if sup.get("token_telemetry") != "MEASURED" or sup.get("total_tokens") is None or (
        record["arm"] == "DEPUTY" and child_total is None) else sup["total_tokens"] + (child_total or 0)
    return record


def campaign_order(repetitions: int = 5) -> list[dict[str, Any]]:
    if repetitions < 1:
        raise ValueError("REPETITIONS_INVALID")
    result = []
    cases = ["E1", "E2", "E3", "E4", "E5", "E6"]
    for repetition in range(1, repetitions + 1):
        for offset in range(len(cases)):
            index = (offset + repetition - 1) % len(cases)
            case = cases[index]
            first = "DIRECT" if (index + repetition) % 2 == 0 else "DEPUTY"
            result.extend(({"case_id": case, "arm": first, "repetition": repetition},
                           {"case_id": case, "arm": "DEPUTY" if first == "DIRECT" else "DIRECT", "repetition": repetition}))
    return result


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(values: list[float]) -> dict[str, float | int | None]:
        if not values:
            return {"count": 0, "mean": None, "median": None, "minimum": None, "maximum": None}
        return {"count": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
                "minimum": min(values), "maximum": max(values)}
    def reduction(direct: dict[str, Any], deputy: dict[str, Any]) -> dict[str, Any]:
        pairs = []
        for repetition in {r.get("repetition") for r in direct} & {r.get("repetition") for r in deputy}:
            d = next((r for r in direct if r.get("repetition") == repetition and r.get("result", {}).get("status") == "PASS"), None)
            p = next((r for r in deputy if r.get("repetition") == repetition and r.get("result", {}).get("status") == "PASS"), None)
            if d is not None and p is not None:
                pairs.append((d, p))
        return {"paired_passes": len(pairs), "values": pairs}

    def metric_reduction(pairs: list[tuple[dict[str, Any], dict[str, Any]]], getter) -> dict[str, Any]:
        deltas = []
        for direct, deputy in pairs:
            left, right = getter(direct), getter(deputy)
            if left is not None and right is not None and left != 0:
                deltas.append({"absolute_reduction": left - right,
                               "fractional_reduction": (left - right) / left})
        if not deltas:
            return {"status": "UNMEASURED", "paired_values": 0, "mean_absolute_reduction": None,
                    "mean_fractional_reduction": None}
        return {"status": "MEASURED", "paired_values": len(deltas),
                "mean_absolute_reduction": statistics.mean(x["absolute_reduction"] for x in deltas),
                "mean_fractional_reduction": statistics.mean(x["fractional_reduction"] for x in deltas)}

    grouped = {}
    all_token_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    all_context_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    all_total_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for case in ["E1", "E2", "E3", "E4", "E5", "E6"]:
        grouped[case] = {}
        for arm in ("DIRECT", "DEPUTY"):
            subset = [r for r in records if r.get("case_id") == case and r.get("arm") == arm]
            valid = [r for r in subset if r.get("result", {}).get("status") == "PASS"]
            tokens = [r["supervisor"]["total_tokens"] for r in valid if r.get("supervisor", {}).get("total_tokens") is not None]
            context = [r["context"]["context_growth_tokens"] for r in valid if r.get("context", {}).get("context_growth_tokens") is not None]
            delegate_tokens = [(r["delegate"].get("input_tokens") or 0) + (r["delegate"].get("output_tokens") or 0)
                               for r in valid if r.get("arm") == "DEPUTY" and r.get("delegate", {}).get("token_telemetry") == "MEASURED"]
            total_tokens = [r["total_inference_tokens"] for r in valid if r.get("total_inference_tokens") is not None]
            times = [r.get("execution", {}).get("wall_clock_ms", 0) for r in subset]
            outliers = []
            if len(times) >= 4:
                ordered_times = sorted(times)
                q1 = statistics.median(ordered_times[:len(ordered_times)//2])
                q3 = statistics.median(ordered_times[(len(ordered_times)+1)//2:])
                spread = q3 - q1
                outliers = [x for x in times if x < q1 - 1.5 * spread or x > q3 + 1.5 * spread]
            grouped[case][arm] = {"runs": len(subset), "passes": len(valid), "pass_rate": len(valid) / len(subset) if subset else None,
                                  "protocol_violations": sum(r.get("result", {}).get("status") == "BENCHMARK_PROTOCOL_VIOLATION" for r in subset),
                                  "blocked": sum(r.get("result", {}).get("status") == "BLOCKED" for r in subset),
                                  "failed": sum(r.get("result", {}).get("status") == "FAIL" for r in subset),
                                  "supervisor_tokens": summarize(tokens), "context_growth_tokens": summarize(context),
                                  "delegate_tokens": summarize(delegate_tokens), "total_inference_tokens": summarize(total_tokens),
                                  "wall_clock_ms": summarize(times), "wall_clock_outliers_ms": outliers,
                                  "supervisor_turns": sum(r.get("execution", {}).get("supervisor_turns", 0) for r in subset),
                                  "supervisor_tool_calls": sum(r.get("execution", {}).get("supervisor_tool_calls", 0) for r in subset),
                                  "mcp_calls": sum(r.get("execution", {}).get("mcp_calls", 0) for r in subset),
                                  "agents_calls": sum(r.get("execution", {}).get("agents_calls", 0) for r in subset),
                                  "workers_calls": sum(r.get("execution", {}).get("workers_calls", 0) for r in subset)}
        direct = [r for r in records if r.get("case_id") == case and r.get("arm") == "DIRECT"]
        deputy = [r for r in records if r.get("case_id") == case and r.get("arm") == "DEPUTY"]
        token_pairs = reduction(direct, deputy)["values"]
        context_pairs = reduction(direct, deputy)["values"]
        total_pairs = reduction(direct, deputy)["values"]
        all_token_pairs.extend(token_pairs); all_context_pairs.extend(context_pairs); all_total_pairs.extend(total_pairs)
        grouped[case]["paired_comparisons"] = {
            "supervisor_token_reduction": metric_reduction(token_pairs, lambda r: r.get("supervisor", {}).get("total_tokens")),
            "supervisor_context_growth_reduction": metric_reduction(context_pairs, lambda r: r.get("context", {}).get("context_growth_tokens")),
            "total_inference_token_change": metric_reduction(total_pairs, lambda r: r.get("total_inference_tokens")),
        }
    return {"schema": "deputy.mcp.efficiency-aggregate.v1", "runs": len(records), "cases": grouped,
            "overall_paired_comparisons": {
                "supervisor_token_reduction": metric_reduction(all_token_pairs, lambda r: r.get("supervisor", {}).get("total_tokens")),
                "supervisor_context_growth_reduction": metric_reduction(all_context_pairs, lambda r: r.get("context", {}).get("context_growth_tokens")),
                "total_inference_token_change": metric_reduction(all_total_pairs, lambda r: r.get("total_inference_tokens")),
            },
            "token_savings_label_policy": "INTERACTION_REDUCTION is not TOKEN_SAVINGS"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--root", type=Path, required=True); p.set_defaults(func=lambda a: prepare_fixture(a.root))
    p = sub.add_parser("arm-plan"); p.add_argument("--arm", choices=["DIRECT", "DEPUTY"], required=True); p.add_argument("--root", type=Path, required=True); p.add_argument("--client-root", type=Path); p.set_defaults(func=lambda a: prepare_arm_plan(a.arm, a.root, a.client_root))
    p = sub.add_parser("expected"); p.add_argument("--case", required=True, choices=["E1", "E2", "E3", "E4", "E5", "E6A", "E6B"]); p.add_argument("--root", type=Path, required=True); p.set_defaults(func=lambda a: expected(a.case, a.root))
    p = sub.add_parser("grade"); p.add_argument("--case", required=True, choices=["E1", "E2", "E3", "E4", "E5", "E6A", "E6B"]); p.add_argument("--root", type=Path, required=True); p.add_argument("--answer", type=Path, required=True); p.set_defaults(func=lambda a: grade(a.case, _load_json(a.answer), a.root))
    p = sub.add_parser("run-template"); p.add_argument("--case", required=True, choices=["E1", "E2", "E3", "E4", "E5", "E6"]); p.add_argument("--arm", required=True, choices=["DIRECT", "DEPUTY"]); p.add_argument("--repetition", type=int, default=1); p.add_argument("--model", default="UNRECORDED"); p.add_argument("--reasoning-effort", default="UNRECORDED"); p.set_defaults(func=lambda a: enforce_missing_telemetry(empty_run(a.case, a.arm, a.repetition, a.model, a.reasoning_effort)))
    p = sub.add_parser("protocol-check"); p.add_argument("--record", type=Path, required=True); p.set_defaults(func=lambda a: validate_protocol(_load_json(a.record)))
    p = sub.add_parser("finalize"); p.add_argument("--case", required=True, choices=["E1", "E2", "E3", "E4", "E5", "E6A", "E6B"]); p.add_argument("--root", type=Path, required=True); p.add_argument("--answer", type=Path, required=True); p.add_argument("--record", type=Path, required=True); p.set_defaults(func=lambda a: finalize_record(_load_json(a.record), a.case, _load_json(a.answer), a.root))
    p = sub.add_parser("schedule"); p.add_argument("--repetitions", type=int, default=5); p.set_defaults(func=lambda a: campaign_order(a.repetitions))
    p = sub.add_parser("aggregate"); p.add_argument("--directory", type=Path, required=True); p.set_defaults(func=lambda a: aggregate([_load_json(f) for f in sorted(a.directory.glob("*.json"))]))
    args = parser.parse_args()
    try:
        result = args.func(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc) if str(exc).isupper() else "BENCHMARK_INPUT_INVALID"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
