from __future__ import annotations
import json, os, shutil, subprocess, tempfile, threading, time, uuid
from pathlib import Path
from .core import LAB, DOCKER, OPENCODE_IMAGE, SQUID_IMAGE, WORKSPACES, WORKERS, build_snapshot, build_argv, parse_events, result, validate_request
from .provider_contract import MODEL_ID, MODEL_SELECTOR, PROVIDER_HOST, PROVIDER_ID, evidence, inline_config_content, validate_contract
from snapshot import SNAPSHOT_ROOT, REPO, create_snapshot, PreparationTimeout

PREPARATION_BUDGET_MS = 15000
OUTER_WATCHDOG_MS = 1860000
PREPARATION_BUDGET_SECONDS = PREPARATION_BUDGET_MS // 1000
OUTER_WATCHDOG_SECONDS = OUTER_WATCHDOG_MS // 1000
CHILD_IDLE_TIMEOUT_MS = 180000
CHILD_ABSOLUTE_TIMEOUT_MS = 1800000
CHILD_IDLE_TIMEOUT_SECONDS = CHILD_IDLE_TIMEOUT_MS // 1000
CHILD_ABSOLUTE_TIMEOUT_SECONDS = CHILD_ABSOLUTE_TIMEOUT_MS // 1000
ACTIVE_OPERATION_TIMEOUT_MS = 900000
EVIDENCE_LIMIT = 8192
ACTIVE = {}
LOCK = threading.Lock()
PENDING_CANCELS = set()
SNAPSHOT_LOCK = threading.Lock()
class PreparationCancelled(RuntimeError):
    pass

def _run(argv, timeout=20):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)

def _name(prefix, job): return f"ocb-{prefix}-{job[:20]}"

def _docker_resources(job):
    return {"network":_name("net",job),"proxy":_name("proxy",job),"worker":_name("worker",job)}

def _write_squid(path):
    Path(path).write_text("\n".join([
        "http_port 3128", "acl SSL_ports port 443", "acl CONNECT method CONNECT",
        "acl allowed_host dstdomain opencode.ai", "http_access allow CONNECT allowed_host SSL_ports",
        "http_access deny all", "cache deny all", "access_log /var/log/squid/access.log squid",
        "cache_log none", "pid_filename none", "" ]), encoding="ascii")

def _cleanup(resources):
    for kind in ("worker","proxy"):
        _run([str(DOCKER),"rm","-f",resources[kind]],timeout=15)
    _run([str(DOCKER),"network","rm",resources["network"]],timeout=15)

def _bounded_write(path, value):
    data = value if isinstance(value, str) else str(value)
    raw = data.encode("utf-8", errors="replace")
    truncated = len(raw) > EVIDENCE_LIMIT
    Path(path).write_bytes(raw[:EVIDENCE_LIMIT])
    return {"bytes": len(raw), "truncated": truncated}

def _preparation_state(evdir, job_id, workspace_id, state, phase, started, lock_wait_ms=None):
    if state is not None:
        state["preparation_phase"] = phase
    payload = {"job_id": job_id, "workspace_id": workspace_id, "execution_state": "PREPARING", "preparation_phase": phase, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    if lock_wait_ms is not None:
        if state is not None:
            state["snapshot_lock_wait_ms"] = lock_wait_ms
        payload["snapshot_lock_wait_ms"] = lock_wait_ms
    if evdir is None:
        return
    tmp = evdir / "preparation-state.json.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(evdir / "preparation-state.json")

def _remaining_preparation(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PreparationTimeout("PREPARATION_TIMEOUT")
    return remaining

def _prepare_guard(deadline, state):
    _remaining_preparation(deadline)
    if state.get("cancel").is_set():
        raise PreparationCancelled("CANCELLED")

def _prep_run(argv, deadline, default_timeout=20):
    return _run(argv, timeout=max(0.01, min(default_timeout, _remaining_preparation(deadline))))

def _capture_proxy_evidence(proxy, evdir):
    out = _run([str(DOCKER), "cp", f"{proxy}:/var/log/squid/access.log", str(evdir / "squid-access.log")], timeout=10)
    if out.returncode:
        logs = _run([str(DOCKER), "logs", proxy], timeout=10)
        return {"source": "docker-logs", **_bounded_write(evdir / "squid-access.log", logs.stdout + logs.stderr)}
    data = (evdir / "squid-access.log").read_bytes()[:EVIDENCE_LIMIT]
    (evdir / "squid-access.log").write_bytes(data)
    return {"bytes": len(data), "truncated": (evdir / "squid-access.log").stat().st_size >= EVIDENCE_LIMIT}

def _capture_worker_state(worker, evdir):
    p = _run([str(DOCKER), "inspect", "--format", "{{json .State}}", worker], timeout=10)
    if p.returncode:
        state = {"error": p.stderr[-1024:]}
    else:
        try:
            raw = json.loads(p.stdout)
            state = {k: raw.get(k) for k in ("Status", "Running", "ExitCode", "OOMKilled", "Restarting", "StartedAt", "FinishedAt")}
        except Exception as exc:
            state = {"error": f"STATE_PARSE:{exc}"}
    (evdir / "worker-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state

def _capture_process_evidence(stdout, stderr, evdir):
    return {"stdout": _bounded_write(evdir / "worker-stdout.txt", stdout or ""), "stderr": _bounded_write(evdir / "worker-stderr.txt", stderr or "")}

MEANINGFUL_PROGRESS_TYPES = {"session", "step_start", "tool_use", "tool_result", "step_finish", "text", "output", "message", "error"}

def _observe_event(event, state, marks, now):
    event_type = event.get("type")
    session_id = event.get("sessionID")
    if session_id and not state.get("session_id"):
        state["session_id"] = session_id
        marks["time_to_session_ms"] = now
        marks["first_session_event_ms"] = now
    if event_type == "step_start":
        state["execution_state"] = "ACTIVE_STEP"
        state["outstanding_step_id"] = event.get("id") or event.get("stepID")
        state["active_operation_started_monotonic"] = time.monotonic()
        marks["outstanding_step_id"] = state["outstanding_step_id"]
    elif event_type == "step_finish":
        state["execution_state"] = "IDLE"
        state.pop("outstanding_step_id", None)
        state.pop("active_operation_started_monotonic", None)
    elif event_type in {"tool_use", "tool_result"} and state.get("execution_state") == "ACTIVE_STEP":
        state["execution_state"] = "ACTIVE_STEP"
    elif event_type in {"done", "finish", "terminal"}:
        state["execution_state"] = "TERMINAL"
    meaningful = event_type in MEANINGFUL_PROGRESS_TYPES or bool(session_id)
    if meaningful:
        state["last_progress_monotonic"] = time.monotonic()
        state["last_progress_type"] = event_type or "session"
        marks["last_progress_type"] = state["last_progress_type"]
    return meaningful

def _watchdog_timeout(state, now, started):
    if state.get("execution_state") == "TERMINAL":
        return None
    if int((now - started) * 1000) >= CHILD_ABSOLUTE_TIMEOUT_MS:
        return "CHILD_ABSOLUTE_TIMEOUT"
    if state.get("execution_state") == "ACTIVE_STEP":
        active_age = int((now - state.get("active_operation_started_monotonic", started)) * 1000)
        state["active_operation_age_ms"] = active_age
        if active_age >= ACTIVE_OPERATION_TIMEOUT_MS:
            return "ACTIVE_OPERATION_TIMEOUT"
        return None
    idle_age = int((now - state.get("last_progress_monotonic", started)) * 1000)
    state["last_progress_age_ms"] = idle_age
    if idle_age >= CHILD_IDLE_TIMEOUT_MS:
        return "CHILD_IDLE_TIMEOUT"
    return None

def _read_process_stream(stream, chunks, state, marks, child_started, is_stdout):
    for line in iter(stream.readline, ""):
        chunks.append(line)
        now = int((time.monotonic() - child_started) * 1000)
        if is_stdout and marks.get("time_to_first_output_ms") is None:
            marks["time_to_first_output_ms"] = now
        if is_stdout:
            try:
                event = json.loads(line)
            except Exception:
                continue
            _observe_event(event, state, marks, now)

def _collect_process(proc, state, marks, child_started, timeout):
    stdout_chunks, stderr_chunks = [], []
    threads = [
        threading.Thread(target=_read_process_stream, args=(proc.stdout, stdout_chunks, state, marks, child_started, True), daemon=True),
        threading.Thread(target=_read_process_stream, args=(proc.stderr, stderr_chunks, state, marks, child_started, False), daemon=True),
    ]
    for thread in threads: thread.start()
    timed_out, timeout_reason = False, None
    absolute_deadline = time.monotonic() + timeout
    state.setdefault("execution_state", "IDLE")
    state.setdefault("last_progress_monotonic", child_started)
    while proc.poll() is None:
        now = time.monotonic()
        timeout_reason = _watchdog_timeout(state, now, child_started)
        if timeout_reason:
            timed_out = True
            break
        if now >= absolute_deadline:
            timed_out, timeout_reason = True, "CHILD_ABSOLUTE_TIMEOUT"
            break
        time.sleep(0.1)
    for thread in threads: thread.join(timeout=2)
    state["last_progress_age_ms"] = int((time.monotonic() - state["last_progress_monotonic"]) * 1000)
    return "".join(stdout_chunks), "".join(stderr_chunks), timed_out, timeout_reason

def _prepare_snapshot(workspace_id, destination, job_id, deadline=None, state=None, evdir=None, started=None):
    phase = lambda value: _preparation_state(evdir, job_id, workspace_id, state, value, started) if evdir else None
    if workspace_id != "DEPUTY_SHELL":
        if deadline: _prepare_guard(deadline, state)
        return build_snapshot(workspace_id, destination, job_id), {"refresh_ms": 0}
    started = started or time.monotonic()
    phase("SNAPSHOT_LOCK_WAIT")
    lock_started = time.monotonic()
    acquired = SNAPSHOT_LOCK.acquire(timeout=max(0.01, _remaining_preparation(deadline)) if deadline else -1)
    if not acquired:
        raise PreparationTimeout("PREPARATION_TIMEOUT")
    try:
        wait_ms = int((time.monotonic() - lock_started) * 1000)
        phase("SNAPSHOT_REPO_STATE")
        # create_snapshot() is the trusted policy-owned snapshot operation.
        refreshed = create_snapshot(deadline=deadline, phase_callback=phase, checkpoint=evdir / "git-trace.json" if evdir else None)
        _preparation_state(evdir, job_id, workspace_id, state, "SNAPSHOT_PUBLICATION", started, wait_ms)
        shutil.copytree(SNAPSHOT_ROOT, destination)
    finally:
        SNAPSHOT_LOCK.release()
    manifest = refreshed["manifest"]
    return manifest, {"refresh_ms": int((time.monotonic() - started) * 1000), "audit": refreshed["audit"], "timings_ms": refreshed["audit"].get("timings_ms", {})}

def _validate_mount_contract(argv, workspace_id, job_snapshot):
    mounts = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--mount"]
    workspace_mounts = [m for m in mounts if "target=/workspace" in m]
    if len(workspace_mounts) != 1:
        raise RuntimeError("WORKSPACE_MOUNT_CONTRACT_INVALID")
    mount = workspace_mounts[0]
    fields = dict(part.split("=", 1) for part in mount.split(",") if "=" in part)
    if fields.get("source") != str(job_snapshot) or fields.get("target") != "/workspace" or "readonly" not in mount:
        raise RuntimeError("WORKSPACE_MOUNT_CONTRACT_INVALID")
    if workspace_id == "DEPUTY_SHELL" and (str(REPO) in " ".join(argv) or str(SNAPSHOT_ROOT) in " ".join(argv)):
        raise RuntimeError("LIVE_OR_SHARED_SNAPSHOT_MOUNT_FORBIDDEN")
    return {"workspace_mount_source": "JOB_SANITIZED_SNAPSHOT", "workspace_mount_target": "/workspace", "workspace_mount_read_only": True, "live_repo_mounted": False, "shared_master_mounted": False, "network_policy": "PROVIDER_ONLY"}

def list_resources():
    c=_run([str(DOCKER),"ps","-a","--format","{{.Names}}"],timeout=15).stdout.splitlines()
    n=_run([str(DOCKER),"network","ls","--format","{{.Name}}"],timeout=15).stdout.splitlines()
    return {"containers":[x for x in c if x.startswith("ocb-")],"networks":[x for x in n if x.startswith("ocb-")]}

def cancel(job_id):
    with LOCK: item=ACTIVE.get(job_id)
    if not item:
        with LOCK: PENDING_CANCELS.add(job_id)
        return {"status":"CANCEL_REQUESTED","job_id":job_id,"pending":True}
    item["cancel"].set()
    _run([str(DOCKER),"rm","-f",item["resources"]["worker"]],timeout=15)
    return {"status":"CANCEL_REQUESTED","job_id":job_id}

def execute(goal, workspace_id="BRIDGE_LAB", worker_profile="RECON", inject_failure=False, inject_timeout=False, job_id=None):
    validate_request(goal,workspace_id,worker_profile)
    validate_contract()
    job=job_id or uuid.uuid4().hex; res=_docker_resources(job); started=time.monotonic(); preparation_deadline=started + PREPARATION_BUDGET_MS / 1000; cancel_event=threading.Event(); marks={}
    evdir=LAB/"evidence"/job; snap=evdir/"snapshot"; evdir.mkdir(parents=True,exist_ok=False)
    request={"goal":goal,"workspace_id":workspace_id,"worker_profile":worker_profile,"job_id":job}; (evdir/"request.json").write_text(json.dumps(request,indent=2),encoding="utf-8")
    state={"resources":res,"cancel":cancel_event,"execution_state":"PREPARING","created_at":time.time()};
    with LOCK:
        ACTIVE[job]=state
        pending_cancel = job in PENDING_CANCELS
        if pending_cancel:
            PENDING_CANCELS.discard(job)
            cancel_event.set()
    _preparation_state(evdir, job, workspace_id, state, "SNAPSHOT_LOCK_WAIT", started)
    manifest=None; stdout=""; stderr=""; exit_code=None; status="CONTAINMENT_ERROR"; parsed={}
    try:
        _prepare_guard(preparation_deadline, state)
        manifest, snapshot_info = _prepare_snapshot(workspace_id, snap, job, preparation_deadline, state, evdir, started); marks["source_snapshot_refresh_ms"] = snapshot_info.get("refresh_ms", 0); marks["snapshot_ms"]=int((time.monotonic()-started)*1000); marks.update(snapshot_info.get("timings_ms", {})); (evdir/"snapshot-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        _prepare_guard(preparation_deadline, state); _preparation_state(evdir, job, workspace_id, state, "NETWORK_CREATE", started)
        t=time.monotonic(); _prep_run([str(DOCKER),"network","create","--internal",res["network"]],preparation_deadline,15); marks["network_create_ms"]=int((time.monotonic()-t)*1000)
        cfg=evdir/"squid.conf"; _write_squid(cfg)
        proxy_args=[str(DOCKER),"run","-d","--name",res["proxy"],"--network","bridge","--read-only","--security-opt","no-new-privileges","--tmpfs","/var/run/squid:rw,size=8m","--tmpfs","/var/cache/squid:rw,size=64m","--tmpfs","/var/log/squid:rw,uid=13,gid=13,size=16m","-v",f"{cfg}:/etc/squid/squid.conf:ro",SQUID_IMAGE]
        if inject_failure: raise RuntimeError("INJECTED_PARTIAL_START_FAILURE")
        _prepare_guard(preparation_deadline, state); _preparation_state(evdir, job, workspace_id, state, "PROXY_START", started)
        t=time.monotonic(); p=_prep_run(proxy_args,preparation_deadline,20); 
        if p.returncode: raise RuntimeError(p.stderr[-1024:])
        _prepare_guard(preparation_deadline, state); _preparation_state(evdir, job, workspace_id, state, "PROXY_CONNECT", started)
        _prep_run([str(DOCKER),"network","connect",res["network"],res["proxy"]],preparation_deadline,15)
        (evdir/"network-contract.json").write_text(json.dumps({"network":res["network"],"internal":True,"worker_networks":[res["network"]],"proxy_networks":["bridge",res["network"]],"squid_image":SQUID_IMAGE,"provider_host":PROVIDER_HOST,"provider_id":PROVIDER_ID,"model_id":MODEL_ID,"proxy_port":3128,"policy":"PROVIDER_ONLY"},indent=2),encoding="utf-8")
        ready=False
        _prepare_guard(preparation_deadline, state); _preparation_state(evdir, job, workspace_id, state, "PROXY_READY", started)
        for _ in range(20):
            probe=_prep_run([str(DOCKER),"logs",res["proxy"]],preparation_deadline,10)
            logs=probe.stdout+probe.stderr
            if "Accepting HTTP Socket connections" in logs:
                ready=True; break
            _prepare_guard(preparation_deadline, state)
            time.sleep(.25)
        marks["proxy_start_ready_ms"]=int((time.monotonic()-t)*1000)
        if not ready: raise RuntimeError("SQUID_NOT_READY")
        marks["preparation_ms"]=int((time.monotonic()-started)*1000)
        _prepare_guard(preparation_deadline, state)
        _preparation_state(evdir, job, workspace_id, state, "MOUNT_VALIDATE", started)
        argv=build_argv(snap,goal); argv.insert(2,"--name"); argv.insert(3,res["worker"]); argv=[res["worker"] if x=="REQUIRED_NETWORK" else x for x in argv]; argv=[res["network"] if x=="REQUIRED_NETWORK" else x for x in argv]
        argv=[x.replace("http://PROXY:3128",f"http://{res['proxy']}:3128") for x in argv]
        argv[argv.index("--network")+1]=res["network"]
        containment = _validate_mount_contract(argv, workspace_id, snap)
        # Docker image is already in argv; replace the logical proxy host with the job name.
        (evdir/"adapter-contract.json").write_text(json.dumps({"network":res["network"],"proxy":res["proxy"],"worker":res["worker"],"squid_image":SQUID_IMAGE,"opencode_image":OPENCODE_IMAGE,"agent":"plan","provider_id":PROVIDER_ID,"model_id":MODEL_ID,"provider_host":PROVIDER_HOST,"selection_source":"SERVER_OWNED","selection_method":"CLI_MODEL_AND_INLINE_SERVER_CONFIG","inline_config_content":inline_config_content(),"workspace_config_policy":"SERVER_CONFIG_AND_CLI_WIN","worker_argv":argv,"stdin":"DEVNULL","preparation_budget_ms":PREPARATION_BUDGET_MS,"child_idle_timeout_ms":CHILD_IDLE_TIMEOUT_MS,"active_operation_timeout_ms":ACTIVE_OPERATION_TIMEOUT_MS,"child_absolute_timeout_ms":CHILD_ABSOLUTE_TIMEOUT_MS,"outer_watchdog_ms":OUTER_WATCHDOG_MS},indent=2),encoding="utf-8")
        _preparation_state(evdir, job, workspace_id, state, "WORKER_LAUNCH", started)
        _prepare_guard(preparation_deadline, state)
        marks["worker_start_ms"]=int((time.monotonic()-started)*1000); state["execution_state"]="RUNNING"; child_started=time.monotonic(); proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,text=True,encoding="utf-8",errors="replace")
        state["process"]=proc
        child_budget = 1 if inject_timeout else CHILD_ABSOLUTE_TIMEOUT_SECONDS
        stdout, stderr, timed_out, timeout_reason = _collect_process(proc, state, marks, child_started, min(child_budget, max(1, OUTER_WATCHDOG_SECONDS - int(time.monotonic()-started))))
        if timed_out:
            process_evidence = _capture_process_evidence(stdout, stderr, evdir)
            worker_state = _capture_worker_state(res["worker"], evdir)
            proxy_evidence = _capture_proxy_evidence(res["proxy"], evdir)
            _run([str(DOCKER),"rm","-f",res["worker"]],timeout=15); proc.wait(timeout=15); status="TIMEOUT"; marks["timeout_termination_ms"]=int((time.monotonic()-started)*1000); marks["total_ms"]=marks["timeout_termination_ms"]; marks["last_progress_age_ms"]=state.get("last_progress_age_ms"); marks["last_progress_type"]=state.get("last_progress_type"); out=result(status,job,workspace_id,state.get("session_id"),"",marks["total_ms"],None,manifest,stderr,marks,evidence()); out["timeout_reason"]=timeout_reason; out["execution_state"]=state.get("execution_state"); out["outstanding_step_id"]=state.get("outstanding_step_id"); out["active_operation_age_ms"]=state.get("active_operation_age_ms"); out["source_snapshot"]={"workspace_id": manifest.get("workspace_id", workspace_id), "policy_version": manifest.get("policy_version"), "created_at": manifest.get("created_at"), "file_count": manifest.get("file_count"), "total_bytes": manifest.get("total_bytes"), "repo": manifest.get("repo", {}), "refresh_ms": marks.get("source_snapshot_refresh_ms", 0)}; out["containment"]=containment; out["evidence"].update({"process":process_evidence,"worker_state":worker_state,"squid":proxy_evidence}); (evdir/"result.json").write_text(json.dumps(out,indent=2),encoding="utf-8"); return out
        exit_code=proc.returncode; parsed=parse_events(stdout); marks.setdefault("time_to_first_output_ms", None); marks.setdefault("time_to_session_ms", None); marks["child_execution_ms"]=int((time.monotonic()-child_started)*1000); marks["model_execution_ms"]=marks["child_execution_ms"]
        inference = evidence(parsed.get("observed_provider"), parsed.get("observed_model"))
        if inference["observed_matches_configured"] is False: status="IDENTITY_MISMATCH"
        elif cancel_event.is_set(): status="CANCELLED"
        elif parsed["error"]: status="MODEL_ERROR" if "APIError" in json.dumps(parsed["error"]) else "CLIENT_ERROR"
        elif parsed["malformed"] or not parsed["session_id"]: status="OUTPUT_INVALID"
        elif exit_code != 0: status="CLIENT_ERROR"
        else: status="PASS"
        proxy_evidence = _capture_proxy_evidence(res["proxy"], evdir)
        marks["total_ms"]=int((time.monotonic()-started)*1000); out=result(status,job,workspace_id,parsed["session_id"],parsed["text"],marks["total_ms"],exit_code,manifest,stderr,marks,inference); out["source_snapshot"]={"schema": manifest.get("schema"), "workspace_id": manifest.get("workspace_id", workspace_id), "policy_version": manifest.get("policy_version"), "coherence_version": manifest.get("coherence_version"), "coherence_status": manifest.get("coherence_status"), "created_at": manifest.get("created_at"), "file_count": manifest.get("file_count"), "total_bytes": manifest.get("total_bytes"), "repo": manifest.get("repo", {}), "refresh_ms": marks.get("source_snapshot_refresh_ms", 0)}; out["containment"]=containment; out["evidence"]["squid"] = proxy_evidence; (evdir/"result.json").write_text(json.dumps(out,indent=2),encoding="utf-8"); return out
    except PreparationCancelled as e:
        stderr=str(e); marks["total_ms"]=int((time.monotonic()-started)*1000); out=result("CANCELLED",job,workspace_id,None,"",marks["total_ms"],exit_code,manifest or {"schema":"deputy.recon.snapshot.v1","file_count":0,"total_bytes":0},stderr,marks,evidence()); out["execution_state"]="PREPARING"; out["preparation_phase"] = state.get("preparation_phase"); out["preparation_elapsed_ms"] = marks["total_ms"]; (evdir/"result.json").write_text(json.dumps(out,indent=2),encoding="utf-8"); return out
    except PreparationTimeout as e:
        stderr=str(e); marks["total_ms"]=int((time.monotonic()-started)*1000); out=result("TIMEOUT",job,workspace_id,None,"",marks["total_ms"],exit_code,manifest or {"schema":"deputy.recon.snapshot.v1","file_count":0,"total_bytes":0},stderr,marks,evidence()); out["timeout_reason"]="PREPARATION_TIMEOUT"; out["execution_state"]="PREPARING"; out["preparation_phase"] = state.get("preparation_phase"); out["preparation_elapsed_ms"] = marks["total_ms"]; (evdir/"result.json").write_text(json.dumps(out,indent=2),encoding="utf-8"); return out
    except Exception as e:
        stderr=str(e); marks["total_ms"]=int((time.monotonic()-started)*1000); out=result(status,job,workspace_id,None,"",marks["total_ms"],exit_code,manifest or {"schema":"deputy.recon.snapshot.v1","file_count":0,"total_bytes":0},stderr,marks,evidence()); (evdir/"result.json").write_text(json.dumps(out,indent=2),encoding="utf-8"); return out
    finally:
        _cleanup(res)
        (evdir/"cleanup.json").write_text(json.dumps({"resources":res,"remaining":list_resources()},indent=2),encoding="utf-8")
        with LOCK: ACTIVE.pop(job,None)
