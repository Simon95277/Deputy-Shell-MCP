from __future__ import annotations
import json, os, subprocess, sys, threading, time, uuid
from pathlib import Path
from .models import ACTIVE, TERMINAL, validate_job
from .process import identity, terminate_tree
from .storage import atomic_json, read_json
from .privacy import child_environment

class DurableRunEngine:
    def __init__(self, root: Path):
        self.root = root; self.runs = root / "runs"; self.active = self.runs / "active.json"; self.runs.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _run_dir(self, run_id): return self.runs / run_id
    def _state(self, run_id): return read_json(self._run_dir(run_id) / "state.json")
    def _completion(self, run_id):
        p=self._run_dir(run_id)/"completion.json"
        if not p.exists(): return None
        try:
            value=read_json(p)
            return value if value.get("schema")=="deputy.worker-completion.v1" and value.get("overall") in {"PASS","FAIL"} else None
        except (OSError, ValueError): return None
    def _write_state(self, run_id, state, **extra):
        data = self._state(run_id) if (self._run_dir(run_id)/"state.json").exists() else {}
        data.update(state, **extra); data["updated_at"] = time.time(); atomic_json(self._run_dir(run_id)/"state.json", data)

    def _release_active_if_owned(self, run_id):
        for attempt in range(4):
            try:
                if not self.active.exists(): return True
                if read_json(self.active).get("run_id") != run_id: return False
                self.active.unlink(missing_ok=True); return True
            except PermissionError as exc:
                if getattr(exc, "winerror", None) != 32 or attempt == 3: return False
                time.sleep(0.025 * (attempt + 1))
        return False

    def _reconcile_active(self):
        if not self.active.exists(): return None
        try: ref=read_json(self.active); st=self._state(ref["run_id"])
        except Exception: return None
        if st.get("state") in TERMINAL: self._release_active_if_owned(ref["run_id"]); return None
        completion=self._completion(ref["run_id"])
        if completion and not (self._run_dir(ref["run_id"])/"result.json").exists():
            now=time.time(); self._write_state(ref["run_id"],{"state":completion["overall"]},completed_at=now); self._write_result(ref["run_id"],completion["overall"],exit_code=st.get("exit_code")); self._release_active_if_owned(ref["run_id"]); return None
        current = identity(st["worker_pid"]) if st.get("worker_pid") else None
        if st.get("worker_pid") and (current is None or current.get("creation_identity") != (st.get("worker_identity") or {}).get("creation_identity")):
            self._write_state(ref["run_id"], {"state":"BLOCKED", "terminal_reason":"WORKER_PROCESS_LOST"}, completed_at=time.time())
            self._write_result(ref["run_id"], "BLOCKED", blocked_reason="WORKER_PROCESS_LOST")
            self._release_active_if_owned(ref["run_id"]); return None
        return ref

    def start(self, request: dict) -> dict:
        job=validate_job(request)
        with self._lock:
            if self._reconcile_active(): return {"status":"REJECTED", "reason":"ACTIVE_RUN_EXISTS"}
            run_id="worker-"+time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())+"-"+uuid.uuid4().hex[:12]
            d=self._run_dir(run_id); (d/"logs").mkdir(parents=True)
            try:
                fd=os.open(self.active, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                os.close(fd)
            except FileExistsError:
                if self._reconcile_active(): return {"status":"REJECTED", "reason":"ACTIVE_RUN_EXISTS"}
                return {"status":"REJECTED", "reason":"ACTIVE_RUN_RACE"}
            job={"schema":job["schema"],"run_id":run_id,**{k:job[k] for k in ("duration_seconds","outcome","emit_stderr")}}
            atomic_json(self.active,{"schema":"deputy.worker-active.v1","run_id":run_id,"worker_pid":None})
            atomic_json(d/"job.json", job)
            now=time.time(); atomic_json(d/"state.json", {"schema":"deputy.worker-state.v1","run_id":run_id,"state":"QUEUED","created_at":now,"updated_at":now,"worker_pid":None,"current_step":"SYNTHETIC_WAIT","cancellation_requested":False})
            out=(d/"logs/synthetic.stdout.log").open("wb"); err=(d/"logs/synthetic.stderr.log").open("wb")
            args=[sys.executable, str(Path(__file__).with_name("synthetic.py")), "--duration", str(job["duration_seconds"]), "--outcome", job["outcome"], "--completion-file", str(d/"completion.json")]+(["--stderr"] if job["emit_stderr"] else [])
            # Keep the child independent of the request thread.  On Windows,
            # CREATE_NEW_PROCESS_GROUP combined with the venv interpreter and
            # redirected handles can fail before Python initializes; owned
            # tree cancellation is performed explicitly by terminate_tree().
            p=subprocess.Popen(args,cwd=self.root,env=child_environment(),stdout=out,stderr=err,close_fds=False)
            self._write_state(run_id,{"state":"RUNNING","worker_pid":p.pid,"worker_identity":identity(p.pid)},started_at=now)
            atomic_json(self.active,{"schema":"deputy.worker-active.v1","run_id":run_id,"worker_pid":p.pid,"worker_identity":identity(p.pid)})
            threading.Thread(target=self._watch,args=(run_id,p,out,err),daemon=True).start()
            return {"status":"ACCEPTED","run_id":run_id,"state":"RUNNING"}

    def _watch(self, run_id, p, out, err):
        code=p.wait(); out.close(); err.close(); st=self._state(run_id)
        if st.get("state")=="CANCELLED": return
        completion=self._completion(run_id); overall=completion["overall"] if completion else "BLOCKED"; now=time.time(); self._write_state(run_id,{"state":overall,"exit_code":code,**({} if completion else {"terminal_reason":"WORKER_PROCESS_LOST"})},completed_at=now); self._write_result(run_id,overall,exit_code=code,**({} if completion else {"blocked_reason":"WORKER_PROCESS_LOST"})); self._release_active_if_owned(run_id)

    def _write_result(self, run_id, overall, **extra):
        st=self._state(run_id); started=st.get("started_at",st.get("created_at")); completed=st.get("completed_at",time.time()); d=self._run_dir(run_id)
        atomic_json(d/"result.json", {"schema":"deputy.worker-result.v1","run_id":run_id,"overall":overall,"started_at":started,"completed_at":completed,"duration_ms":int((completed-started)*1000),"stdout_log":str(d/"logs/synthetic.stdout.log"),"stderr_log":str(d/"logs/synthetic.stderr.log"),"contradiction":None,"blocked_reason":extra.get("blocked_reason"),"unproven_reason":None,**extra})

    def status(self, run_id):
        if not (self._run_dir(run_id)/"state.json").exists(): return {"status":"NOT_FOUND","run_id":run_id}
        self._reconcile_active(); return {"status":"FOUND",**self._state(run_id)}
    def result(self, run_id):
        d=self._run_dir(run_id)
        if not (d/"state.json").exists(): return {"status":"NOT_FOUND","run_id":run_id}
        if not (d/"result.json").exists(): return {"status":"NOT_READY",**self._state(run_id)}
        return {"status":"READY",**read_json(d/"result.json")}
    def cancel(self, run_id):
        d=self._run_dir(run_id)
        if not (d/"state.json").exists(): return {"status":"NOT_FOUND","run_id":run_id}
        st=self._state(run_id)
        if st.get("state") in TERMINAL: return {"status":"ALREADY_TERMINAL",**st}
        current = identity(st.get("worker_pid")) if st.get("worker_pid") else None
        if st.get("worker_pid") and (current is None or current.get("creation_identity") != (st.get("worker_identity") or {}).get("creation_identity")):
            return {"status":"BLOCKED","run_id":run_id,"reason":"WORKER_PROCESS_LOST"}
        if st.get("worker_pid"):
            terminate_tree(st["worker_pid"])
            deadline = time.time() + 5
            while time.time() < deadline and identity(st["worker_pid"]):
                time.sleep(0.05)
        now=time.time(); self._write_state(run_id,{"state":"CANCELLED","cancellation_requested":True,"terminal_reason":"CANCEL_REQUESTED"},completed_at=now); self._write_result(run_id,"CANCELLED",exit_code=None); self._release_active_if_owned(run_id); return {"status":"CANCELLED","run_id":run_id}
