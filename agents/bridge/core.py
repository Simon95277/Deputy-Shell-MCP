from __future__ import annotations

import hashlib, json, os, re, shutil, subprocess, tempfile, time, uuid
from pathlib import Path
from config import BRIDGE_FIXTURES, DEPUTY_SHELL_ROOT, DOCKER_EXE

LAB = BRIDGE_FIXTURES.parent
DOCKER = DOCKER_EXE
OPENCODE_IMAGE = "ghcr.io/anomalyco/opencode@sha256:0d3c9551ea2522fcfd23fbc2e302fc87218d6c198bff277e8ab44d93a3bd6d3d"
SQUID_IMAGE = "ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029"
MAX_GOAL_BYTES = 4096
WORKSPACES = {
    "BRIDGE_LAB": BRIDGE_FIXTURES,
    "DEPUTY_SHELL": DEPUTY_SHELL_ROOT,
}
WORKERS = {"RECON": "plan"}

def validate_request(goal, workspace_id, worker_profile):
    if not isinstance(goal, str) or not goal.strip(): raise ValueError("EMPTY_GOAL")
    if len(goal.encode("utf-8")) > MAX_GOAL_BYTES: raise ValueError("GOAL_TOO_LARGE")
    if workspace_id not in WORKSPACES: raise ValueError("UNKNOWN_WORKSPACE")
    if worker_profile not in WORKERS: raise ValueError("UNKNOWN_WORKER_PROFILE")

def safe_name(prefix, job_id):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id): raise ValueError("INVALID_JOB_ID")
    return f"{prefix}-{job_id[:20]}"

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def build_snapshot(workspace_id, destination, job_id):
    validate_request("snapshot", workspace_id, "RECON")
    src=WORKSPACES[workspace_id]; destination=Path(destination); destination.mkdir(parents=True, exist_ok=False)
    files=[]
    for p in sorted(src.rglob("*")):
        if not p.is_file(): continue
        rel=p.relative_to(src).as_posix()
        if rel.startswith((".git/","work/","build/",".gradle/","evidence/","local-snapshots/")): continue
        if workspace_id == "DEPUTY_SHELL" and rel == "snapshot-manifest.json": continue
        if re.search(r"(^|/)(\.env|local\.properties|google-services\.json)|\.(apk|aab|apks|jks|keystore|pem|key)$", rel, re.I): continue
        out=destination/rel; out.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,out)
        files.append({"path":rel,"size":out.stat().st_size,"sha256":sha256(out)})
    manifest={"schema":"deputy.recon.snapshot.v1","policy_version":"R6-positive-allowlist-v1","source":{"repo_id":"BRIDGE_LAB","branch":None,"head":None,"dirty":None},"created_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"files":files,"file_count":len(files),"total_bytes":sum(x["size"] for x in files)}
    (destination/"snapshot-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest

def parse_events(raw):
    events=[]; malformed=False
    for line in raw.splitlines():
        if not line.strip(): continue
        try: events.append(json.loads(line))
        except json.JSONDecodeError: malformed=True
    sid=next((e.get("sessionID") for e in events if e.get("sessionID")),None)
    texts=[e.get("part",{}).get("text","") for e in events if e.get("type")=="text"]
    err=next((e.get("error",{}) for e in events if e.get("type")=="error"),None)
    return {"events":events,"session_id":sid,"text":"\n".join(x for x in texts if x)[-8192:],"error":err,"malformed":malformed}

def build_argv(job_dir, goal):
    return [str(DOCKER),"run","--rm","--network","REQUIRED_NETWORK","--read-only","--cap-drop=ALL","--security-opt","no-new-privileges","--pids-limit","128","--memory","1g","--cpus","2","--tmpfs","/tmp:rw,nosuid,nodev,size=64m","--tmpfs","/root/.cache:rw,nosuid,nodev,size=128m","--tmpfs","/root/.local/share/opencode:rw,nosuid,nodev,size=128m","--tmpfs","/root/.config/opencode:rw,nosuid,nodev,size=64m","--mount",f"type=bind,source={job_dir},target=/workspace,readonly","-e","HTTP_PROXY=http://PROXY:3128","-e","HTTPS_PROXY=http://PROXY:3128","-e","NO_PROXY=localhost,127.0.0.1,::1",OPENCODE_IMAGE,"run","--format","json","--agent","plan","--dir","/workspace",goal]

def result(status,job_id,workspace,session,text,duration,exit_code,manifest,stderr="",timings=None):
    return {"status":status,"job_id":job_id,"workspace_id":workspace,"worker_profile":"RECON","session_id":session,"text":text[:8192],"duration_ms":duration,"exit_code":exit_code,"snapshot":{"schema":manifest["schema"],"policy_version":manifest.get("policy_version"),"workspace_id":manifest.get("workspace_id", workspace),"file_count":manifest["file_count"],"total_bytes":manifest["total_bytes"]},"evidence":{"stderr_summary":stderr[:2048],"network_policy":"PROVIDER_ONLY","phase_timings_ms":timings or {}}}
