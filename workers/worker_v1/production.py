from __future__ import annotations
import os, subprocess, sys, threading, time, uuid
from pathlib import Path
from .capabilities import validate_job, load_registry
from .host_ops import IMPLEMENTED
from . import host_ops
from .process import identity, terminate_tree
from .storage import atomic_json, read_json
from .repo_integrity import capture_snapshot, compare_snapshots
from config import TRUSTED_PYTHON

TERMINAL={"PASS","FAIL","BLOCKED","CANCELLED"}

def _build_production_worker_command(root: Path, run_id: str) -> list[str]:
    """Trusted private launch seam; callers never supply command material."""
    interpreter = TRUSTED_PYTHON
    if not interpreter.is_file():
        raise RuntimeError("TRUSTED_WORKER_INTERPRETER_UNAVAILABLE")
    return [str(interpreter), "-m", "worker_v1.production_worker", str(root), run_id]

class ProductionRunEngine:
    def __init__(self, root: Path):
        self.root=root; self.runs=root/"runs"; self.active=self.runs/"active.json"; self.runs.mkdir(parents=True,exist_ok=True); self._lock=threading.Lock()
    def _dir(self,rid): return self.runs/rid
    def _state(self,rid): return read_json(self._dir(rid)/"state.json")
    def _write(self,rid,**values):
        p=self._dir(rid)/"state.json"; d=read_json(p) if p.exists() else {}; d.update(values); d["updated_at"]=time.time(); atomic_json(p,d)
    def _release_active_if_owned(self, rid):
        """Idempotently release only this run's ownership, with bounded Win32 retry."""
        for attempt in range(4):
            try:
                if not self.active.exists(): return True
                ref=read_json(self.active)
                if ref.get("run_id") != rid: return False
                self.active.unlink(missing_ok=True); return True
            except PermissionError as exc:
                if getattr(exc, "winerror", None) != 32 or attempt == 3: return False
                time.sleep(0.025 * (attempt + 1))
        return False
    def _finalize_loss(self, rid):
        d=self._dir(rid); result_path=d/"result.json"
        if result_path.exists():
            try:
                existing=read_json(result_path)
                if existing.get("overall") in {"PASS","FAIL","BLOCKED","UNPROVEN","CONTRADICTION","CANCELLED"}:
                    self._release_active_if_owned(rid); return existing
            except Exception: pass
        st=self._state(rid); integrity=d/"integrity"; integrity.mkdir(parents=True,exist_ok=True); pre=integrity/"pre.json"
        loss={"worker_pid":st.get("worker_pid"),"worker_identity":st.get("worker_identity"),"worker_confirmed_lost":True,"observed_at":time.time(),"pre_exists":pre.exists(),"post_exists":False,"comparison_exists":False,"quiescence":"UNKNOWN"}
        steps=[]
        for p in sorted((d/"steps").glob("*/result.json")):
            try: steps.append(read_json(p))
            except Exception: pass
        if not pre.exists():
            status="NOT_ESTABLISHED_BEFORE_EXECUTION" if not steps else "UNPROVEN"; reason=None if not steps else "REPOSITORY_PRE_SNAPSHOT_MISSING_AFTER_EXECUTION"; loss["quiescence"]="NOT_APPLICABLE"
        else:
            job=read_json(d/"job.json"); current=st.get("current_step_index"); uncertain=False
            if isinstance(current,int) and current < len(job.get("steps",[])):
                op=job["steps"][current].get("operation")
                uncertain=op in {"GRADLE","RUN_APPROVED_VERIFIER"} and not any(x.get("id")==job["steps"][current].get("id") for x in steps)
            if uncertain:
                status="UNPROVEN"; reason="WORKER_CHILD_EXECUTION_MAY_CONTINUE"; loss["quiescence"]="UNPROVEN"
            else:
                loss["quiescence"]="PROVEN"
                try:
                    if (integrity/"post.json").exists(): post=read_json(integrity/"post.json")
                    else: post=capture_snapshot(host_ops.REPO_ROOT); atomic_json(integrity/"post.json",post)
                    loss["post_exists"]=True
                    if (integrity/"comparison.json").exists(): comparison=read_json(integrity/"comparison.json")
                    else: comparison=compare_snapshots(read_json(pre),post); atomic_json(integrity/"comparison.json",comparison)
                    loss["comparison_exists"]=True; status="CONTRADICTION" if not comparison.get("same") else "SAME"; reason=None
                except Exception:
                    status="UNPROVEN"; reason="REPOSITORY_INTEGRITY_COMPARISON_UNAVAILABLE" if (integrity/"post.json").exists() else "REPOSITORY_POST_SNAPSHOT_UNAVAILABLE"
        loss["integrity_status"]=status
        if reason: loss["integrity_reason"]=reason
        atomic_json(integrity/"loss.json",loss)
        result={"schema":"deputy.worker-result.v1","run_id":rid,"overall":"BLOCKED","blocked_reason":"WORKER_PROCESS_LOST","steps":steps,"integrity_status":status,"loss_path":str(integrity/"loss.json"),"loss":loss}
        if (integrity/"comparison.json").exists(): result["integrity"]={"pre_path":str(pre),"post_path":str(integrity/"post.json"),"comparison_path":str(integrity/"comparison.json"),**read_json(integrity/"comparison.json")}
        atomic_json(result_path,result); self._write(rid,state="BLOCKED",terminal_reason="WORKER_PROCESS_LOST",completed_at=time.time()); self._release_active_if_owned(rid); return result
    def _reconcile(self):
        if not self.active.exists(): return None
        try: ref=read_json(self.active); st=self._state(ref["run_id"])
        except Exception: return None
        if st.get("state") in TERMINAL: self._release_active_if_owned(ref["run_id"]); return None
        pid=st.get("worker_pid"); live=identity(pid) if pid else None
        if pid and (live is None or live.get("creation_identity") != st.get("worker_identity",{}).get("creation_identity")):
            self._finalize_loss(ref["run_id"]); return None
        return ref
    def start(self,job):
        v=validate_job(job)
        if not v["valid"]: return {"status":"REJECTED","reason":"JOB_INVALID","errors":v["errors"]}
        reg=load_registry()
        if any(s["operation"] not in IMPLEMENTED or reg[s["operation"]].get("implementation")!="IMPLEMENTED" for s in job["steps"]): return {"status":"REJECTED","reason":"OPERATION_NOT_IMPLEMENTED"}
        with self._lock:
            if self._reconcile(): return {"status":"REJECTED","reason":"ACTIVE_RUN_EXISTS"}
            rid="production-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+uuid.uuid4().hex[:12]; d=self._dir(rid); (d/"steps").mkdir(parents=True)
            try: fd=os.open(self.active,os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.close(fd)
            except FileExistsError: return {"status":"REJECTED","reason":"ACTIVE_RUN_RACE"}
            atomic_json(d/"job.json",job); atomic_json(d/"state.json",{"schema":"deputy.worker-state.v1","run_id":rid,"state":"QUEUED","worker_pid":None,"created_at":time.time()}); atomic_json(self.active,{"schema":"deputy.worker-active.v1","run_id":rid,"worker_pid":None})
            try:
                command = _build_production_worker_command(self.root, rid)
                p=subprocess.Popen(command,cwd=str(Path(__file__).resolve().parent.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=False,shell=False)
            except (RuntimeError, OSError):
                self._release_active_if_owned(rid)
                return {"status":"BLOCKED","reason":"TRUSTED_WORKER_INTERPRETER_UNAVAILABLE"}
            ident=identity(p.pid)
            self._write(rid,state="RUNNING",worker_pid=p.pid,worker_identity=ident,started_at=time.time()); atomic_json(self.active,{"schema":"deputy.worker-active.v1","run_id":rid,"worker_pid":p.pid,"worker_identity":ident}); threading.Thread(target=self._watch,args=(rid,p),daemon=True).start(); return {"status":"ACCEPTED","run_id":rid,"state":"RUNNING","worker_pid":p.pid,"worker_identity":ident}
    def _watch(self,rid,p):
        p.wait(); d=self._dir(rid)
        if not (d/"result.json").exists(): self._finalize_loss(rid)
        else: self._release_active_if_owned(rid)
    def status(self,rid):
        self._reconcile(); p=self._dir(rid)/"state.json"; return {"status":"FOUND",**read_json(p)} if p.exists() else {"status":"NOT_FOUND","run_id":rid}
    def result(self,rid):
        p=self._dir(rid)/"result.json"; return {"status":"READY",**read_json(p)} if p.exists() else {"status":"NOT_READY","run_id":rid}
    def cancel(self,rid):
        self._reconcile(); st=self._state(rid)
        if st.get("state") in TERMINAL:
            return {"status":st.get("state"),"run_id":rid,"late":True}
        pid=st.get("worker_pid"); live=identity(pid) if pid else None
        if not pid or not live or live.get("creation_identity")!=st.get("worker_identity",{}).get("creation_identity"): return {"status":"BLOCKED","reason":"WORKER_PROCESS_LOST"}
        d=self._dir(rid); integrity=d/"integrity"; integrity.mkdir(parents=True,exist_ok=True)
        cancellation={"cancellation_accepted":True,"target_pid":pid,"target_creation_identity":live.get("creation_identity"),"termination_requested":True}
        terminate_tree(pid)
        terminated=False
        for _ in range(40):
            current=identity(pid)
            if current is None or current.get("creation_identity")!=live.get("creation_identity"):
                terminated=True; break
            time.sleep(.025)
        cancellation["termination_confirmed"]=terminated
        pre=integrity/"pre.json"
        if not terminated:
            final="UNPROVEN"; reason="WORKER_TERMINATION_UNCONFIRMED"
        elif not pre.exists():
            executed=bool(list((d/"steps").glob("*/result.json")))
            cancellation["pre_exists"]=False; cancellation["post_captured"]=False; cancellation["comparison_available"]=False
            if executed: final="UNPROVEN"; reason="REPOSITORY_PRE_SNAPSHOT_MISSING_AFTER_EXECUTION"
            else: final="CANCELLED"; reason="NOT_ESTABLISHED_BEFORE_EXECUTION"
        else:
            cancellation["pre_exists"]=True
            try:
                post=capture_snapshot(host_ops.REPO_ROOT); atomic_json(integrity/"post.json",post); cancellation["post_captured"]=True
                comparison=compare_snapshots(read_json(pre),post); atomic_json(integrity/"comparison.json",comparison); cancellation["comparison_available"]=True
                final="CONTRADICTION" if not comparison.get("same") else "CANCELLED"; reason=None
            except Exception:
                final="UNPROVEN"; reason="REPOSITORY_INTEGRITY_UNAVAILABLE"; cancellation["post_captured"]=False; cancellation["comparison_available"]=False
        cancellation["integrity_status"]=reason or ("CHANGED" if final=="CONTRADICTION" else "SAME")
        atomic_json(integrity/"cancellation.json",cancellation)
        existing=read_json(d/"result.json") if (d/"result.json").exists() else {"steps":[]}
        steps=existing.get("steps",[])
        if not steps:
            steps=[]
            for step_file in sorted((d/"steps").glob("*/result.json")):
                try: steps.append(read_json(step_file))
                except Exception: pass
        result={"schema":"deputy.worker-result.v1","run_id":rid,"overall":final,"execution_verdict":"CANCELLED","steps":steps,"cancellation":cancellation}
        if reason: result["unproven_reason"]=reason
        if final=="CONTRADICTION" and (integrity/"comparison.json").exists(): result["integrity"]={"pre_path":str(pre),"post_path":str(integrity/"post.json"),"comparison_path":str(integrity/"comparison.json"),**read_json(integrity/"comparison.json")}
        atomic_json(d/"result.json",result); self._write(rid,state=final,terminal_reason="CANCEL_REQUESTED",completed_at=time.time()); self._release_active_if_owned(rid); return {"status":final,"run_id":rid}
