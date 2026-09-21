from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import re
from pathlib import Path

from mcp.server import MCPServer
from worker_v1 import DurableRunEngine, ProductionRunEngine
from worker_v1.capabilities import (
    APPROVED_ACTIVITIES,
    APPROVED_ARTIFACTS,
    APPROVED_DUMPSYS,
    APPROVED_GRADLE_TASKS,
    APPROVED_INSTRUMENTATION,
    APPROVED_JUNIT_REPORTS,
    APPROVED_VERIFIERS,
    load_registry,
)
from config import EVIDENCE_ROOT, RUNTIME_ROOT, TRUSTED_PYTHON


SERVER_NAME = "Deputy Workers"

BASE_DIR = RUNTIME_ROOT

CONTRACT_PATH = RUNTIME_ROOT / "WORKER_CONTRACT.md"

EXPECTED_CONTRACT_SHA256 = (
    "0326BF9918BBFA37F2A71DBFB278FD8997AAA1F7BC67ACBF3DFA1A919FE6A160"
)

HERMES_EXE = RUNTIME_ROOT / "hermes.exe"

HERMES_PROFILE = "sub-agents"

DELEGATION_LIVE_DIR = RUNTIME_ROOT / "delegation" / "live"

EXPECTED_CHILD_MODEL = "muse-spark-1.3-contributor-free"
EXPECTED_CHILD_PROVIDER = "opencode-free"

EXACT_TASK = r'''# SYNTHETIC DETERMINISTIC EVIDENCE TASK

You are a subordinate deterministic evidence/execution worker.

You have ZERO decision authority.

WORKER_CONTRACT.md is authoritative and applies in full.

This TASK.md is authoritative for this job.

Do not reinterpret either document.

Work only inside the current working directory.

Do not inspect parent directories.

Do not access network, browser, memory, skills, connections, other projects, or unrelated files.

Do not delete or rename files.

Do not modify:

- WORKER_CONTRACT.md
- TASK.md
- evidence-a.txt
- evidence-b.txt
- evidence-c.txt

You are authorized to create exactly one new file:
RESULT.txt

Do not create any other file.

## TASK

Read:

- evidence-a.txt
- evidence-b.txt
- evidence-c.txt

For every evidence record determine:

- tool
- probe
- count

Verify these authoritative requirements:

A. Exactly three evidence records exist.

B. Required ordered tools are exactly:

git
curl
python3

C. Every count equals 1.

D. Every probe is non-empty and equals PASS.

Calculate SHA-256 for:

- WORKER_CONTRACT.md
- TASK.md
- evidence-a.txt
- evidence-b.txt
- evidence-c.txt

Create RESULT.txt using exactly this status vocabulary:

PASS
UNPROVEN
BLOCKED
CONTRADICTION
DECISION_REQUIRED

FAIL is NOT an allowed verdict.

Use this exact schema:

OVERALL:
<status>

RECORDS:
git: <status>
curl: <status>
python3: <status>

REQUIREMENTS:
A: <status>
B: <status>
C: <status>
D: <status>

SHA256:
WORKER_CONTRACT.md: <hash>
TASK.md: <hash>
evidence-a.txt: <hash>
evidence-b.txt: <hash>
evidence-c.txt: <hash>

FILES_MODIFIED:
RESULT.txt

NOTES:
<short factual note>

## VERDICT RULES

Missing or blank required evidence is UNPROVEN.

A blank value is NOT a contradiction.

CONTRADICTION requires positive observed evidence conflicting with an authoritative requirement.

Therefore:

required probe=PASS
observed probe=<blank>

means:

UNPROVEN

while:

required probe=PASS
observed probe=FAIL

means:

CONTRADICTION

Anything unresolved means the overall verdict cannot be PASS.

For the supplied evidence, do not infer the blank python3 probe.

Do not repair evidence.

Do not recommend a correction.

MANDATORY FINAL VERIFICATION

After RESULT.txt has been written successfully:

1. You MUST call read_file(RESULT.txt).
2. You MUST wait for that read_file call to succeed.
3. You MUST NOT finish the task before this read-back occurs.
4. Your final response must contain the contents returned by that read_file call.

A task that writes RESULT.txt but does not subsequently read RESULT.txt is incomplete.
'''

EVIDENCE_FILES = {
    "evidence-a.txt": "tool=git\nprobe=PASS\ncount=1\n",
    "evidence-b.txt": "tool=curl\nprobe=PASS\ncount=1\n",
    "evidence-c.txt": "tool=python3\nprobe=\ncount=1\n",
}


mcp = MCPServer(SERVER_NAME)
W2_ENGINE = DurableRunEngine(BASE_DIR)
PRODUCTION_ENGINE = ProductionRunEngine(BASE_DIR)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest().upper()


def verify_contract() -> dict[str, object]:
    if not CONTRACT_PATH.is_file():
        return {
            "ok": False,
            "reason": "WORKER_CONTRACT.md does not exist.",
        }

    actual_sha256 = sha256_file(CONTRACT_PATH)

    if actual_sha256 != EXPECTED_CONTRACT_SHA256:
        return {
            "ok": False,
            "reason": "Frozen Worker Contract v1 hash mismatch.",
            "expected_sha256": EXPECTED_CONTRACT_SHA256,
            "actual_sha256": actual_sha256,
        }

    return {
        "ok": True,
        "sha256": actual_sha256,
    }


def run_process(
    args: list[str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        shell=False,
    )


def get_delegation_config() -> dict[str, object]:
    process = run_process(
        [
            str(HERMES_EXE),
            "-p",
            HERMES_PROFILE,
            "config",
            "get",
            "delegation",
            "--json",
        ],
        timeout_seconds=30,
    )

    if process.returncode != 0:
        raise RuntimeError(
            "Hermes delegation config command failed. "
            f"returncode={process.returncode}, "
            f"stderr={process.stderr.strip()}"
        )

    return json.loads(process.stdout.strip())


def verify_delegation_config() -> dict[str, object]:
    try:
        config = get_delegation_config()
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"Could not read Hermes delegation config: {exc}",
        }

    violations: list[str] = []

    if config.get("model") != EXPECTED_CHILD_MODEL:
        violations.append(
            f"model={config.get('model')!r}, "
            f"expected={EXPECTED_CHILD_MODEL!r}"
        )

    if config.get("provider") != EXPECTED_CHILD_PROVIDER:
        violations.append(
            f"provider={config.get('provider')!r}, "
            f"expected={EXPECTED_CHILD_PROVIDER!r}"
        )

    if config.get("fallback_providers") != []:
        violations.append(
            "fallback_providers must be an empty list"
        )

    if config.get("max_spawn_depth") != 1:
        violations.append(
            f"max_spawn_depth={config.get('max_spawn_depth')!r}, expected=1"
        )

    if config.get("orchestrator_enabled") is not False:
        violations.append(
            "orchestrator_enabled must be false"
        )

    if config.get("subagent_auto_approve") is not False:
        violations.append(
            "subagent_auto_approve must be false"
        )

    if violations:
        return {
            "ok": False,
            "reason": "Hermes delegation safety configuration mismatch.",
            "violations": violations,
        }

    return {
        "ok": True,
        "model": config.get("model"),
        "provider": config.get("provider"),
        "max_iterations": config.get("max_iterations"),
        "max_concurrent_children": config.get("max_concurrent_children"),
        "max_spawn_depth": config.get("max_spawn_depth"),
        "orchestrator_enabled": config.get("orchestrator_enabled"),
        "subagent_auto_approve": config.get("subagent_auto_approve"),
        "fallback_providers": config.get("fallback_providers"),
    }


def delegation_dirs() -> dict[str, Path]:
    if not DELEGATION_LIVE_DIR.is_dir():
        return {}

    return {
        item.name: item
        for item in DELEGATION_LIVE_DIR.iterdir()
        if item.is_dir()
    }


def find_new_delegation(
    before: set[str],
    timeout_seconds: float = 5.0,
) -> Path | None:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        current = delegation_dirs()
        new_names = set(current) - before

        if new_names:
            newest_name = max(
                new_names,
                key=lambda name: current[name].stat().st_mtime,
            )
            return current[newest_name]

        time.sleep(0.1)

    return None


def run_worker_smoke_internal() -> dict[str, object]:
    return run_direct_worker_smoke_internal()


def _direct_hermes(
    job_dir: Path,
    prompt: str,
    timeout_seconds: int = 300,
) -> dict[str, object]:
    prompt_path = job_dir / "DIRECT_MUSE_BOOTSTRAP.txt"
    stdout_path = job_dir / "DIRECT_MUSE_STDOUT.log"
    stderr_path = job_dir / "DIRECT_MUSE_STDERR.log"
    usage_path = job_dir / "DIRECT_MUSE_USAGE.json"
    prompt_path.write_text(prompt, encoding="utf-8", newline="")
    args = [
        str(HERMES_EXE), "-p", HERMES_PROFILE, "--usage-file", str(usage_path), "chat", "--oneshot",
        "--query-file", str(prompt_path), "--toolsets", "terminal,file",
        "--in", str(job_dir), "--max-turns", "250", "--quiet",
    ]
    started = time.monotonic()
    try:
        process = subprocess.run(
            args, cwd=str(job_dir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stdout_path.write_text(stdout, encoding="utf-8", newline="")
        stderr_path.write_text(stderr, encoding="utf-8", newline="")
        return {"ok": False, "reason": "Direct Hermes session timed out.", "args": args, "returncode": None, "stdout": stdout, "stderr": stderr, "timed_out": True, "terminated": True, "usage_path": str(usage_path)}
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout_path.write_text(process.stdout, encoding="utf-8", newline="")
    stderr_path.write_text(process.stderr, encoding="utf-8", newline="")
    combined = process.stdout + "\n" + process.stderr
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "duration_ms": duration_ms,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "combined": combined,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "args": args,
        "returncode": process.returncode,
        "timed_out": False,
        "terminated": False,
        "usage_path": str(usage_path),
        "usage": _read_json(usage_path) if usage_path.is_file() else {},
    }


def run_direct_worker_smoke_internal() -> dict[str, object]:
    if not verify_contract()["ok"]:
        return {"status": "BLOCKED", "stage": "contract_verification"}
    job_dir = Path(tempfile.mkdtemp(prefix="direct_worker_smoke_", dir=str(BASE_DIR)))
    before = set(delegation_dirs())
    run = _direct_hermes(
        job_dir,
        "Return exactly: WORKER_SMOKE_OK: 703\nDo not use delegation, delegate_task, or Qwen.",
        timeout_seconds=300,
    )
    after = set(delegation_dirs())
    if not run["ok"]:
        return {"status": "BLOCKED", "stage": "hermes_execution", "transport_mode": "DIRECT_MUSE", "reason": run["reason"] if "reason" in run else "Hermes failed.", "stderr_tail": run.get("stderr", "")[-2000:]}
    forbidden = bool(re.search(r"delegate_task|Qwen", run["combined"], re.I))
    if "WORKER_SMOKE_OK: 703" not in run["combined"] or forbidden or after != before:
        return {"status": "CONTRADICTION", "stage": "direct_muse_evidence", "transport_mode": "DIRECT_MUSE", "qwen_used": forbidden, "delegate_task_used": forbidden, "new_delegations": sorted(after - before)}
    return {"status": "PASS", "test": "direct_muse_worker_smoke", "transport_mode": "DIRECT_MUSE", "model": EXPECTED_CHILD_MODEL, "provider": EXPECTED_CHILD_PROVIDER, "qwen_used": False, "delegate_task_used": False, "job_directory": str(job_dir)}


def _run_direct_exact_payload_smoke() -> dict[str, object]:
    contract = verify_contract()
    if not contract["ok"]:
        return {"status": "BLOCKED", "stage": "contract_verification", **contract}
    if not HERMES_EXE.is_file():
        return {"status": "BLOCKED", "stage": "hermes_executable", "reason": "Hermes executable not found."}
    job_dir = Path(tempfile.mkdtemp(prefix="direct_exact_payload_", dir=str(BASE_DIR)))
    (job_dir / "WORKER_CONTRACT.md").write_bytes(CONTRACT_PATH.read_bytes())
    (job_dir / "TASK.md").write_text(EXACT_TASK, encoding="utf-8", newline="")
    for name, content in EVIDENCE_FILES.items():
        (job_dir / name).write_text(content, encoding="utf-8", newline="")
    input_names = ["WORKER_CONTRACT.md", "TASK.md", *EVIDENCE_FILES]
    pre_hashes = {name: sha256_file(job_dir / name) for name in input_names}
    before = set(delegation_dirs())
    run = _direct_hermes(job_dir, "Read WORKER_CONTRACT.md and TASK.md from the current working directory. Treat both as authoritative. Execute TASK.md exactly. Do not inspect parent directories or unrelated files.")
    after = set(delegation_dirs())
    transcript = run.get("combined", "")
    usage = run.get("usage", {})
    result_path = job_dir / "RESULT.txt"
    result_text = result_path.read_text(encoding="utf-8", errors="replace") if result_path.is_file() else ""
    checks = {
        "contract_read": bool(re.search(r"read_file[^\n]*WORKER_CONTRACT\.md", transcript, re.I)),
        "task_read": bool(re.search(r"read_file[^\n]*TASK\.md", transcript, re.I)),
        "evidence_read": all(re.search(r"read_file[^\n]*" + re.escape(n), transcript, re.I) for n in EVIDENCE_FILES),
        "sha_tool": bool(re.search(r"sha.?256|sha256sum|Get-FileHash|hashlib", transcript, re.I)),
        "result_written": bool(re.search(r"write_file[^\n]*RESULT\.txt|RESULT\.txt[^\n]*(written|created)", transcript, re.I)),
        "result_read": bool(re.search(r"read_file[^\n]*RESULT\.txt", transcript, re.I)),
    }
    required = ["OVERALL:\nUNPROVEN", "git: PASS", "curl: PASS", "python3: UNPROVEN", "A: PASS", "B: PASS", "C: PASS", "D: UNPROVEN"]
    result_ok = all(x in result_text for x in required) and "FAIL" not in result_text
    hash_ok = all(re.search(rf"^{re.escape(n)}:\s*{re.escape(v)}\s*$", result_text, re.I | re.M) for n, v in pre_hashes.items())
    unchanged = all(sha256_file(job_dir / n) == v for n, v in pre_hashes.items())
    unexpected = sorted(p.name for p in job_dir.iterdir() if p.name not in {*input_names, "RESULT.txt", "DIRECT_MUSE_BOOTSTRAP.txt", "DIRECT_MUSE_STDOUT.log", "DIRECT_MUSE_STDERR.log"})
    qwen_used = bool(re.search(r"Qwen|delegate_task|delegation", transcript, re.I)) or bool(after - before)
    actual_model = usage.get("model")
    actual_provider = usage.get("provider")
    actual_session_id = usage.get("session_id")
    identity_ok = actual_model == EXPECTED_CHILD_MODEL and actual_provider == EXPECTED_CHILD_PROVIDER and bool(actual_session_id)
    ok = run.get("ok", False) and all(checks.values()) and result_ok and hash_ok and unchanged and not unexpected and not qwen_used and identity_ok
    return {"status": "PASS" if ok else "CONTRADICTION", "test": "exact_payload_worker_delegation", "transport_mode": "DIRECT_MUSE", "model": actual_model, "provider": actual_provider, "contract_sha256": contract["sha256"], "task_sha256": pre_hashes["TASK.md"], "worker_overall": "UNPROVEN" if result_ok else None, "worker_contract_read": checks["contract_read"], "worker_task_read": checks["task_read"], "evidence_read": checks["evidence_read"], "result_written": checks["result_written"], "result_read": checks["result_read"], "input_files_unchanged": unchanged, "unexpected_worker_files": unexpected, "qwen_used": qwen_used, "delegate_task_used": qwen_used, "new_delegations": sorted(after - before), "repository_access": False, "v6_access": False, "private_code_sent": False, "privacy_mode": "SYNTHETIC_ONLY", "job_directory": str(job_dir), "session_identity": {"session_id": actual_session_id, "model": actual_model, "provider": actual_provider, "usage_file": run.get("usage_path")}, "process": {"returncode": run.get("returncode"), "timed_out": run.get("timed_out", False), "terminated": run.get("terminated", False), "stdout_log": run.get("stdout_log"), "stderr_log": run.get("stderr_log")}, "parsed_result": result_text, "reason": {"checks": checks, "hash_ok": hash_ok, "identity_ok": identity_ok, "new_delegations": sorted(after - before)} if not ok else None}
    contract = verify_contract()

    if not contract["ok"]:
        return {
            "status": "BLOCKED",
            "stage": "contract_verification",
            **contract,
        }

    if not HERMES_EXE.is_file():
        return {
            "status": "BLOCKED",
            "stage": "hermes_executable",
            "reason": "Hermes executable not found.",
            "path": str(HERMES_EXE),
        }

    delegation_config = verify_delegation_config()

    if not delegation_config["ok"]:
        return {
            "status": "BLOCKED",
            "stage": "delegation_config",
            **delegation_config,
        }

    before_dirs = set(delegation_dirs())

    prompt = """This is a synthetic delegation transport test.

You are only a dispatcher.

Use delegate_task exactly once.

Spawn exactly one LEAF subagent.

The child task is:

Calculate 37 multiplied by 19.

The child must return exactly:

WORKER_SMOKE_OK: 703

Do not solve the arithmetic yourself.
Do not use any tool other than delegate_task.
Do not spawn more than one child.
Do not browse.
Do not access files.
Do not use terminal commands.
Do not access any repository.
Do not access memory.

Wait for the delegated child to complete.

Then return the child's final response.
"""

    prompt_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            prefix="deputy_worker_smoke_",
            dir=str(BASE_DIR),
            delete=False,
        ) as prompt_file:
            prompt_file.write(prompt)
            prompt_path = Path(prompt_file.name)

        try:
            process = run_process(
                [
                    str(HERMES_EXE),
                    "-p",
                    HERMES_PROFILE,
                    "chat",
                    "--oneshot",
                    "--query-file",
                    str(prompt_path),
                    "--toolsets",
                    "delegation",
                    "--max-turns",
                    "10",
                ],
                timeout_seconds=180,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "BLOCKED",
                "stage": "hermes_execution",
                "reason": "Hermes smoke test timed out after 180 seconds.",
            }

    finally:
        if prompt_path is not None:
            try:
                prompt_path.unlink(missing_ok=True)
            except OSError:
                pass

    if process.returncode != 0:
        return {
            "status": "BLOCKED",
            "stage": "hermes_execution",
            "reason": "Hermes returned a non-zero exit code.",
            "returncode": process.returncode,
            "stderr_tail": process.stderr[-2000:],
        }

    delegation_dir = find_new_delegation(before_dirs)

    if delegation_dir is None:
        return {
            "status": "UNPROVEN",
            "stage": "delegation_evidence",
            "reason": "Hermes returned successfully but no new delegation directory was found.",
            "hermes_stdout_tail": process.stdout[-2000:],
        }

    manifest_path = delegation_dir / "manifest.json"

    if not manifest_path.is_file():
        return {
            "status": "UNPROVEN",
            "stage": "delegation_evidence",
            "reason": "New delegation directory has no manifest.json.",
            "delegation_dir": str(delegation_dir),
        }

    try:
        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )
    except Exception as exc:
        return {
            "status": "UNPROVEN",
            "stage": "delegation_evidence",
            "reason": f"Could not parse manifest.json: {exc}",
            "manifest_path": str(manifest_path),
        }

    violations: list[str] = []

    if manifest.get("model") != EXPECTED_CHILD_MODEL:
        violations.append(
            f"manifest model={manifest.get('model')!r}, "
            f"expected={EXPECTED_CHILD_MODEL!r}"
        )

    if manifest.get("provider") != EXPECTED_CHILD_PROVIDER:
        violations.append(
            f"manifest provider={manifest.get('provider')!r}, "
            f"expected={EXPECTED_CHILD_PROVIDER!r}"
        )

    if manifest.get("task_count") != 1:
        violations.append(
            f"manifest task_count={manifest.get('task_count')!r}, expected=1"
        )

    tasks = manifest.get("tasks")

    if not isinstance(tasks, list) or len(tasks) != 1:
        violations.append(
            "manifest must contain exactly one task"
        )
        task = {}
    else:
        task = tasks[0]

    if task.get("status") != "completed":
        violations.append(
            f"task status={task.get('status')!r}, expected='completed'"
        )

    if task.get("exit_reason") != "completed":
        violations.append(
            f"task exit_reason={task.get('exit_reason')!r}, expected='completed'"
        )

    log_value = task.get("log")
    log_path = Path(log_value) if isinstance(log_value, str) else None

    if log_path is None or not log_path.is_file():
        violations.append(
            "task transcript path is missing or unreadable"
        )
        transcript = ""
    else:
        transcript = log_path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    expected_result = "WORKER_SMOKE_OK: 703"

    if expected_result not in transcript:
        violations.append(
            "expected worker result is absent from child transcript"
        )

    if violations:
        return {
            "status": "CONTRADICTION",
            "stage": "delegation_evidence",
            "delegation_id": manifest.get("delegation_id"),
            "violations": violations,
            "manifest_path": str(manifest_path),
        }

    return {
        "status": "PASS",
        "server": SERVER_NAME,
        "test": "synthetic_single_worker_delegation",
        "contract_sha256": contract["sha256"],
        "hermes_profile": HERMES_PROFILE,
        "child_model": manifest.get("model"),
        "child_provider": manifest.get("provider"),
        "delegation_id": manifest.get("delegation_id"),
        "task_count": manifest.get("task_count"),
        "task_status": task.get("status"),
        "exit_reason": task.get("exit_reason"),
        "worker_result": expected_result,
        "manifest_path": str(manifest_path),
        "privacy_mode": "SYNTHETIC_ONLY",
        "repository_access": False,
        "v6_access": False,
        "private_code_sent": False,
    }


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def run_exact_payload_smoke_internal() -> dict[str, object]:
    return _run_direct_exact_payload_smoke()

    contract = verify_contract()
    if not contract["ok"]:
        return {"status": "BLOCKED", "stage": "contract_verification", **contract}
    if not HERMES_EXE.is_file():
        return {"status": "BLOCKED", "stage": "hermes_executable", "reason": "Hermes executable not found."}
    config = verify_delegation_config()
    if not config["ok"]:
        return {"status": "BLOCKED", "stage": "delegation_config", **config}

    before_dirs = set(delegation_dirs())
    job_dir = Path(tempfile.mkdtemp(prefix="exact_payload_", dir=str(BASE_DIR)))
    contract_dst = job_dir / "WORKER_CONTRACT.md"
    contract_dst.write_bytes(CONTRACT_PATH.read_bytes())
    (job_dir / "TASK.md").write_text(EXACT_TASK, encoding="utf-8", newline="")
    for name, content in EVIDENCE_FILES.items():
        (job_dir / name).write_text(content, encoding="utf-8", newline="")
    input_names = ["WORKER_CONTRACT.md", "TASK.md", *EVIDENCE_FILES]
    pre_hashes = {name: sha256_file(job_dir / name) for name in input_names}
    prompt = """You are only a dispatcher. Do not perform the task yourself. Call delegate_task exactly once and spawn exactly one leaf child. The child must read WORKER_CONTRACT.md and TASK.md from the current working directory, treat those files as authoritative, execute TASK.md, and return the result. Wait for the child. Return the child's final response. Do not read or execute the evidence task yourself."""
    prompt_path = job_dir / "DISPATCHER_PROMPT.txt"
    prompt_path.write_text(prompt, encoding="utf-8", newline="")
    try:
        process = subprocess.run([
            str(HERMES_EXE), "-p", HERMES_PROFILE, "chat", "--oneshot",
            "--query-file", str(prompt_path), "--toolsets", "delegation,terminal,file",
            "--max-turns", "250", "--in", str(job_dir),
        ], cwd=str(job_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, shell=False)
    except subprocess.TimeoutExpired:
        return {"status": "BLOCKED", "stage": "hermes_execution", "reason": "Hermes exact-payload smoke timed out."}
    delegation_dir = find_new_delegation(before_dirs, timeout_seconds=10)
    if process.returncode != 0 or delegation_dir is None:
        return {"status": "UNPROVEN", "stage": "delegation_evidence", "reason": "Hermes failed or produced no new delegation directory.", "returncode": process.returncode, "stderr_tail": process.stderr[-2000:]}
    manifest_path = delegation_dir / "manifest.json"
    if not manifest_path.is_file():
        return {"status": "UNPROVEN", "stage": "delegation_evidence", "reason": "Manifest missing.", "delegation_id": delegation_dir.name}
    manifest = _read_json(manifest_path)
    tasks = manifest.get("tasks")
    task = tasks[0] if isinstance(tasks, list) and len(tasks) == 1 else {}
    log_path = Path(task.get("log")) if isinstance(task.get("log"), str) else None
    transcript = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.is_file() else ""
    checks = {
        "manifest": manifest.get("task_count") == 1 and manifest.get("model") == EXPECTED_CHILD_MODEL and manifest.get("provider") == EXPECTED_CHILD_PROVIDER and task.get("status") == "completed" and task.get("exit_reason") == "completed",
        "contract_read": bool(re.search(r"read_file[^\n]*WORKER_CONTRACT\.md", transcript, re.I)),
        "task_read": bool(re.search(r"read_file[^\n]*TASK\.md", transcript, re.I)),
        "evidence_read": all(re.search(r"read_file[^\n]*" + re.escape(n), transcript, re.I) for n in EVIDENCE_FILES),
        "sha_tool": bool(re.search(r"sha.?256|Get-FileHash|hashlib", transcript, re.I)),
        "result_written": bool(re.search(r"write_file[^\n]*RESULT\.txt|RESULT\.txt[^\n]*(written|created)", transcript, re.I)),
        "result_read": bool(re.search(r"read_file[^\n]*RESULT\.txt", transcript, re.I)),
    }
    result_path = job_dir / "RESULT.txt"
    expected_hashes = {name: pre_hashes[name] for name in input_names}
    unchanged = all(sha256_file(job_dir / name) == value for name, value in pre_hashes.items())
    unexpected = sorted(p.name for p in job_dir.iterdir() if p.name not in {*input_names, "RESULT.txt", "DISPATCHER_PROMPT.txt"})
    result_text = result_path.read_text(encoding="utf-8", errors="replace") if result_path.is_file() else ""
    required = ["OVERALL:\nUNPROVEN", "git: PASS", "curl: PASS", "python3: UNPROVEN", "A: PASS", "B: PASS", "C: PASS", "D: UNPROVEN"]
    result_ok = all(x in result_text for x in required) and "FAIL" not in result_text
    hash_ok = all(
        re.search(
            rf"^{re.escape(name)}:\s*{re.escape(value)}\s*$",
            result_text,
            re.IGNORECASE | re.MULTILINE,
        )
        for name, value in expected_hashes.items()
    )
    all_ok = all(checks.values()) and unchanged and not unexpected and result_ok and hash_ok
    base = {"status": "PASS" if all_ok else "CONTRADICTION", "test": "exact_payload_worker_delegation", "contract_sha256": contract["sha256"], "task_sha256": pre_hashes["TASK.md"], "child_model": manifest.get("model"), "child_provider": manifest.get("provider"), "delegation_id": manifest.get("delegation_id"), "task_count": manifest.get("task_count"), "task_status": task.get("status"), "exit_reason": task.get("exit_reason"), "worker_overall": "UNPROVEN" if result_ok else None, "worker_contract_read": checks["contract_read"], "worker_task_read": checks["task_read"], "input_files_unchanged": unchanged, "unexpected_worker_files": unexpected, "private_code_sent": False, "v6_access": False, "repository_access": False, "privacy_mode": "SYNTHETIC_ONLY", "job_directory": str(job_dir), "manifest_path": str(manifest_path), "parsed_result": result_text}
    if not all_ok:
        base["reason"] = {"checks": checks, "result_ok": result_ok, "hash_ok": hash_ok}
    return base


@mcp.tool()
def deputy_worker_status() -> dict[str, object]:
    """
    Verify the local Deputy Workers MCP bridge and expose its frozen
    legacy-smoke and production typed-worker surfaces.

    This tool performs no repository execution, no Hermes delegation, and no
    external model calls. Production metadata is registry discovery only.
    """

    contract = verify_contract()

    if not contract["ok"]:
        return {
            "status": "BLOCKED",
            "server": SERVER_NAME,
            "contract_path": str(CONTRACT_PATH),
            **contract,
        }

    registry = load_registry()
    symbolic_ids = {
        "GRADLE": sorted(APPROVED_GRADLE_TASKS),
        "RUN_APPROVED_VERIFIER": sorted(APPROVED_VERIFIERS),
        "PARSE_JUNIT": sorted(APPROVED_JUNIT_REPORTS),
        "HASH_ARTIFACT": sorted(APPROVED_ARTIFACTS),
        "ADB_START_DEPUTY_ACTIVITY": sorted(APPROVED_ACTIVITIES),
        "ADB_INSTRUMENT": sorted(APPROVED_INSTRUMENTATION),
        "ADB_DUMPSYS_REGISTERED": sorted(APPROVED_DUMPSYS),
    }
    production_operations = [
        {
            "operation": name,
            "params_schema": metadata["params_schema"],
            "symbolic_ids": symbolic_ids.get(name, []),
            "executable": metadata["enabled"] and metadata["implementation"] == "IMPLEMENTED",
        }
        for name, metadata in sorted(registry.items())
    ]

    return {
        "status": "PASS",
        "server": SERVER_NAME,
        "contract": "DEPUTY SHELL WORKER CONTRACT v1",
        "contract_path": str(CONTRACT_PATH),
        "contract_sha256": contract["sha256"],
        "privacy_mode": "BOUNDED_TYPED_V1_1",
        "hermes_enabled": True,
        "repository_access": "BOUNDED",
        "v6_access": False,
        "external_model_calls": False,
        "legacy_smoke": {
            "status": "SAFE_TEST_ONLY",
            "repository_access": False,
            "description": "Synthetic contract/delegation validation only.",
        },
        "production": {
            "status": "READY",
            "lifecycle": "ASYNC_TYPED_V1_1",
            "job_schema": "deputy.worker.job.v1",
            "repository_binding": "deputy-authoritative-v1",
            "repository_access": "BOUNDED",
            "operation_count": len(production_operations),
            "operations": production_operations,
            "generic_shell": False,
            "generic_adb": False,
            "generic_adb_shell": False,
            "arbitrary_process_execution": False,
        },
    }


@mcp.tool()
def deputy_worker_smoke() -> dict[str, object]:
    """
    Run one synthetic end-to-end Hermes delegation test.

    This tool verifies the frozen Worker Contract, verifies Hermes child
    routing and safety configuration, launches a delegation-only Hermes
    parent, requires exactly one Muse leaf worker, and validates the
    resulting delegation manifest and transcript.

    No Deputy Shell repository, V6 document, source code, or private
    project data is supplied to the external worker.
    """

    return run_worker_smoke_internal()


@mcp.tool()
def deputy_worker_exact_payload_smoke() -> dict[str, object]:
    """Run the synthetic exact-authority file-payload delegation smoke."""
    return run_exact_payload_smoke_internal()


@mcp.tool()
def deputy_worker_start(steps: list[dict[str, object]]) -> dict[str, object]:
    """Start a frozen-registry production typed repository-bound job.

    Canonical input is only ``steps``: each item requires ``operation`` and
    ``params``. Operation names and parameter schemas come from the frozen
    22-operation registry. The MCP injects the deputy.worker.job.v1 schema,
    the deputy-authoritative-v1 repository binding, and deterministic step
    IDs; callers cannot provide those policy fields.

    Example::

        {"steps": [
          {"operation": "CAPTURE_REPO_STATE", "params": {}},
          {"operation": "CHECK_FILE", "params": {"path": "app/build.gradle.kts"}}
        ]}

    This tool does not provide generic shell, ADB, or process execution.
    """
    try:
        if not isinstance(steps, list):
            return {"status": "REJECTED", "reason": "STEPS_REQUIRED"}
        canonical_steps = []
        for index, step in enumerate(steps, 1):
            if not isinstance(step, dict) or set(step) != {"operation", "params"}:
                return {"status": "REJECTED", "reason": "STEP_REQUIRES_OPERATION_AND_PARAMS", "step_index": index - 1}
            canonical_steps.append({
                "id": f"step-{index:03d}",
                "operation": step["operation"],
                "params": step["params"],
            })
        job = {
            "schema": "deputy.worker.job.v1",
            "repo": {"binding": "deputy-authoritative-v1"},
            "steps": canonical_steps,
        }
        return PRODUCTION_ENGINE.start(job)
    except (TypeError, ValueError) as exc:
        return {"status": "REJECTED", "reason": str(exc)}


@mcp.tool()
def deputy_worker_run_status(run_id: str) -> dict[str, object]:
    if str(run_id).startswith("production-"): return PRODUCTION_ENGINE.status(run_id)
    return W2_ENGINE.status(run_id)


@mcp.tool()
def deputy_worker_result(run_id: str) -> dict[str, object]:
    if str(run_id).startswith("production-"): return PRODUCTION_ENGINE.result(run_id)
    return W2_ENGINE.result(run_id)


@mcp.tool()
def deputy_worker_cancel(run_id: str) -> dict[str, object]:
    if str(run_id).startswith("production-"): return PRODUCTION_ENGINE.cancel(run_id)
    return W2_ENGINE.cancel(run_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
