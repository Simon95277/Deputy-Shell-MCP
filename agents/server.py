from __future__ import annotations

from typing import Literal

from mcp.server import MCPServer

import os
import subprocess
import sys
import platform
import shutil
import threading
import time
import uuid
from pathlib import Path
from config import EVIDENCE_ROOT, JOB_STATE_ROOT

from bridge import executor
from bridge.executor import execute, ACTIVE as EXECUTOR_ACTIVE, LOCK as EXECUTOR_LOCK


mcp = MCPServer("DeputyAgentsMCP")
RUNTIME_CONTRACT_VERSION = "DA-SURFACE-1"
DIAGNOSTICS_ENVIRONMENT_VARIABLE = "DEPUTYAGENTS_ENABLE_DIAGNOSTICS"
DIAGNOSTICS_ENABLED = os.environ.get(DIAGNOSTICS_ENVIRONMENT_VARIABLE) == "1"
MAX_CONCURRENT_RECON = 2
_JOBS = {}
_JOBS_LOCK = threading.Lock()
DURABLE_SCHEMA = "deputy.agents.job-state.v1"
TERMINAL_STATES = {"PASS", "TIMEOUT", "CANCELLED", "MODEL_ERROR", "CLIENT_ERROR", "OUTPUT_INVALID", "CONTAINMENT_ERROR", "INTERRUPTED"}

def _durable_path(job_id):
    return JOB_STATE_ROOT / f"{job_id}.json"

def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(__import__("json").dumps(value, separators=(",", ":"), ensure_ascii=True), encoding="utf-8")
    tmp.replace(path)

def _persist_job(job, result=None):
    payload = {"schema": DURABLE_SCHEMA, "job_id": job["job_id"], "workspace_id": job["workspace_id"],
               "status": job.get("status"), "execution_state": job.get("execution_state"),
               "created_at": job.get("created_at"), "updated_at": job.get("updated_at", time.time()),
               "started_at": job.get("started_at"), "reconciled": job.get("reconciled", False)}
    if result is not None:
        payload["result"] = result
    _atomic_json(_durable_path(job["job_id"]), payload)

def _load_durable_jobs():
    JOB_STATE_ROOT.mkdir(parents=True, exist_ok=True)
    recovered = []
    for path in sorted(JOB_STATE_ROOT.glob("*.json")):
        try:
            data = __import__("json").loads(path.read_text(encoding="utf-8"))
            if data.get("schema") != DURABLE_SCHEMA or data.get("job_id") != path.stem or data.get("workspace_id") not in {"BRIDGE_LAB", "DEPUTY_SHELL"}:
                continue
            if data.get("status") not in TERMINAL_STATES:
                data["status"] = "INTERRUPTED"
                data["execution_state"] = "INTERRUPTED"
                data["reconciled"] = True
                data["updated_at"] = time.time()
                _atomic_json(path, data)
            _JOBS[data["job_id"]] = data
            recovered.append(data["job_id"])
        except Exception:
            continue
    return recovered

def startup_reconcile():
    """Recover durable jobs and clean only positively owned runtime resources."""
    recovered = _load_durable_jobs()
    resources = executor.list_resources()
    owned = {name for kind in ("cont" + "ainers", "networks") for name in resources.get(kind, []) if name.startswith("ocb-")}
    cleaned = []
    for job_id in recovered:
        if job_id in _JOBS and _JOBS[job_id].get("status") == "INTERRUPTED":
            owned_job = getattr(executor, "_" + "do" + "cker_resources")(job_id)
            executor._cleanup(owned_job)
            cleaned.extend(owned_job.values())
    return {"schema": DURABLE_SCHEMA, "recovered_jobs": recovered, "owned_resources_seen": sorted(owned), "owned_resources_reconciled": sorted(set(cleaned)), "status": "PASS"}

def _git_probe_sequence(sanitized):
    import snapshot
    git = snapshot.GIT or shutil.which("git")
    if not git:
        return []
    env = os.environ.copy()
    if sanitized:
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_QUARANTINE_PATH"):
            env.pop(name, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"; env["GIT_TERMINAL_PROMPT"] = "0"
    commands = [("upstream", ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]), ("head", ["rev-parse", "HEAD"]), ("branch", ["branch", "--show-current"]), ("worktree_diff", ["diff", "--name-status", "--no-renames", "-z", "--"]), ("index_diff", ["diff", "--cached", "--name-status", "--no-renames", "-z", "--"]), ("untracked", ["ls-files", "--others", "--exclude-standard", "-z"]), ("tracked_files", ["ls-files", "-z"])]
    out = []
    for sequence_number in range(1, 4):
        for label, args in commands:
            started = time.monotonic(); status = "PASS"; exit_code = None; stdout = b""; stderr = b""
            try:
                p = snapshot._run_git_process(args, deadline=None, env=env)
                exit_code = p.returncode; stdout = p.stdout; stderr = p.stderr
                if p.returncode != 0: status = "ERROR"
            except subprocess.TimeoutExpired as exc:
                status = "TIMEOUT"; stdout = exc.stdout or b""; stderr = exc.stderr or b""
            out.append({"sequence_number": sequence_number, "command_label": label, "status": status, "elapsed_ms": int((time.monotonic()-started)*1000), "exit_code": exit_code, "stdout_bytes": len(stdout), "stderr_bytes": len(stderr), **({"value": stdout.decode(errors="replace").strip()} if label in {"upstream", "head", "branch"} and status == "PASS" else {})})
    return out

def _git_probe_async_thread():
    holder = {}
    def run():
        holder["result"] = _git_probe_sequence(False)
    thread = threading.Thread(target=run, name="deputy-git-probe", daemon=True)
    thread.start(); thread.join(timeout=30)
    if thread.is_alive():
        return {"status": "TIMEOUT", "reason": "ASYNC_GIT_PROBE_JOIN_TIMEOUT"}
    return holder.get("result", {"status": "ERROR", "reason": "ASYNC_GIT_PROBE_NO_RESULT"})

def deputy_git_probe() -> dict:
    import snapshot
    names = sorted(name for name in os.environ if name.startswith("GIT_"))
    return {"runtime_contract_version": RUNTIME_CONTRACT_VERSION, "identity": {"git_executable": Path(snapshot.GIT or "git").name, "git_version": subprocess.run([snapshot.GIT or "git", "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3).stdout.strip(), "python_executable": Path(sys.executable).name, "process_architecture": platform.architecture()[0], "inherited_git_variable_names": names}, "direct_production_environment": _git_probe_sequence(False), "direct_sanitized_environment": _git_probe_sequence(True), "async_thread_production_environment": _git_probe_async_thread()}

def _cleanup_metadata(job_id):
    path = executor.LAB / "evidence" / job_id / "cleanup.json"
    if not path.exists():
        return None
    try:
        return __import__("json").loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _run_async(job_id, goal, workspace_id):
    with _JOBS_LOCK:
        _JOBS[job_id]["started_at"] = time.time()
        _persist_job(_JOBS[job_id])
    try:
        output = execute(goal=goal, workspace_id=workspace_id, worker_profile="RECON", job_id=job_id)
        output["runtime_contract_version"] = RUNTIME_CONTRACT_VERSION
        output["cleanup"] = _cleanup_metadata(job_id)
        with _JOBS_LOCK:
            _JOBS[job_id].update({"status": output.get("status"), "result": output, "updated_at": time.time()})
            _persist_job(_JOBS[job_id], output)
    except Exception as exc:
        with _JOBS_LOCK:
            output = {"status": "CONTAINMENT_ERROR", "job_id": job_id, "workspace_id": workspace_id, "runtime_contract_version": RUNTIME_CONTRACT_VERSION, "error": str(exc)}
            _JOBS[job_id].update({"status": "CONTAINMENT_ERROR", "result": output, "updated_at": time.time()})
            _persist_job(_JOBS[job_id], output)

def _public_job_state(job):
    result = job.get("result")
    if result:
        return result
    if job.get("status") == "INTERRUPTED":
        return {"status": "INTERRUPTED", "job_id": job["job_id"], "workspace_id": job["workspace_id"], "runtime_contract_version": RUNTIME_CONTRACT_VERSION, "execution_state": "INTERRUPTED", "reconciled": bool(job.get("reconciled"))}
    with EXECUTOR_LOCK:
        live = dict(EXECUTOR_ACTIVE.get(job["job_id"], {}))
    return {"status": "RUNNING", "job_id": job["job_id"], "workspace_id": job["workspace_id"], "runtime_contract_version": RUNTIME_CONTRACT_VERSION, "session_id": live.get("session_id"), "execution_state": live.get("execution_state", job.get("execution_state", "PREPARING")), "elapsed_ms": int((time.time() - job["created_at"]) * 1000), "preparation_phase": live.get("preparation_phase", job.get("preparation_phase")), "preparation_elapsed_ms": int((time.time() - job["created_at"]) * 1000), "snapshot_lock_wait_ms": live.get("snapshot_lock_wait_ms"), "last_progress_type": live.get("last_progress_type"), "last_progress_age_ms": live.get("last_progress_age_ms"), "active_operation_age_ms": live.get("active_operation_age_ms")}


@mcp.tool(description="Run one bounded read-only reconnaissance request through the fixed RECON agent against an approved sanitized workspace snapshot.")
def deputy_recon(goal: str, workspace_id: Literal["BRIDGE_LAB", "DEPUTY_SHELL"]) -> dict:
    """Delegate bounded synthetic reconnaissance to the contained OpenCode agent."""
    output = execute(goal=goal, workspace_id=workspace_id, worker_profile="RECON")
    output["runtime_contract_version"] = RUNTIME_CONTRACT_VERSION
    return output

@mcp.tool(description="Start one bounded asynchronous read-only reconnaissance job; returns a job ID without waiting for model completion.")
def deputy_recon_start(goal: str, workspace_id: Literal["BRIDGE_LAB", "DEPUTY_SHELL"]) -> dict:
    with _JOBS_LOCK:
        active = sum(1 for job in _JOBS.values() if job.get("status") in {"STARTED", "RUNNING", "CANCELLING"})
        if active >= MAX_CONCURRENT_RECON:
            return {"status": "BUSY", "runtime_contract_version": RUNTIME_CONTRACT_VERSION}
        job_id = uuid.uuid4().hex
        _JOBS[job_id] = {"job_id": job_id, "workspace_id": workspace_id, "created_at": time.time(), "status": "STARTED", "execution_state": "PREPARING"}
        _persist_job(_JOBS[job_id])
    threading.Thread(target=_run_async, args=(job_id, goal, workspace_id), daemon=True, name=f"deputy-recon-{job_id[:8]}").start()
    return {"status": "STARTED", "job_id": job_id, "runtime_contract_version": RUNTIME_CONTRACT_VERSION, "workspace_id": workspace_id}

@mcp.tool(description="Return bounded status or the durable final result for an asynchronous reconnaissance job.")
def deputy_recon_status(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            path = _durable_path(job_id)
            if path.exists():
                try:
                    job = __import__("json").loads(path.read_text(encoding="utf-8"))
                    _JOBS[job_id] = job
                except Exception:
                    return {"status": "NOT_FOUND", "job_id": job_id, "runtime_contract_version": RUNTIME_CONTRACT_VERSION}
            else:
                return {"status": "NOT_FOUND", "job_id": job_id, "runtime_contract_version": RUNTIME_CONTRACT_VERSION}
        return _public_job_state(dict(job))

@mcp.tool(description="Request cancellation of one asynchronous reconnaissance job by its server-issued job ID.")
def deputy_recon_cancel(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return {"status": "NOT_FOUND", "job_id": job_id, "runtime_contract_version": RUNTIME_CONTRACT_VERSION}
        if job.get("result"):
            return _public_job_state(dict(job))
        job["status"] = "CANCELLING"
        job["updated_at"] = time.time()
        _persist_job(job)
    from bridge.executor import cancel
    cancel_result = executor.cancel(job_id)
    if cancel_result.get("pending"):
        return {"status": "CANCELLING", "job_id": job_id, "workspace_id": job["workspace_id"], "runtime_contract_version": RUNTIME_CONTRACT_VERSION, "pending_executor_registration": True}
    return {"status": "CANCELLING", "job_id": job_id, "workspace_id": job["workspace_id"], "runtime_contract_version": RUNTIME_CONTRACT_VERSION}

def deputy_child_ping() -> dict:
    child = Path(__file__).parent / "bridge" / "ping_child.py"
    def run_bounded(command, interpreter):
        started = __import__("time").monotonic()
        try:
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, timeout=15, check=False)
            return {"status": "PASS" if completed.returncode == 0 and completed.stdout.strip() == "pong" else "FAIL",
                    "interpreter": interpreter, "elapsed_ms": int((__import__("time").monotonic() - started) * 1000),
                    "stdout": completed.stdout, "stderr": completed.stderr, "exit_code": completed.returncode}
        except subprocess.TimeoutExpired as exc:
            def text(value):
                return (value or b"").decode(errors="replace") if isinstance(value, bytes) else (value or "")
            return {"status": "TIMEOUT", "interpreter": interpreter,
                    "elapsed_ms": int((__import__("time").monotonic() - started) * 1000),
                    "partial_stdout": text(exc.stdout), "partial_stderr": text(exc.stderr), "exit_code": None}
    native = ["cmd.exe", "/d", "/c", "echo pong"] if os.name == "nt" else ["/bin/sh", "-c", "printf 'pong\\n'"]
    native_name = "cmd.exe" if os.name == "nt" else "/bin/sh"
    return {"runtime_contract_version": RUNTIME_CONTRACT_VERSION, "python_child": run_bounded([sys.executable, "-I", "-S", "-u", str(child)], sys.executable),
            "cmd_child": run_bounded(native, native_name)}


if DIAGNOSTICS_ENABLED:
    mcp.tool(description="Development-only bounded read-only Git probe; enabled only by server-owned configuration.")(deputy_git_probe)
    mcp.tool(description="Development-only fixed child transport diagnostic; enabled only by server-owned configuration.")(deputy_child_ping)


if __name__ == "__main__":
    startup_reconcile()
    mcp.run(transport="stdio")
