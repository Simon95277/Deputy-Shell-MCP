from __future__ import annotations
import sys,time,traceback
from pathlib import Path
from .host_ops import dispatch
from .storage import atomic_json,read_json
from .repo_integrity import capture_snapshot, compare_snapshots

def _integrity_dir(d: Path) -> Path:
    p=d/"integrity"; p.mkdir(parents=True, exist_ok=True); return p

def _write_blocked(d: Path, rid: str, reason: str, execution_verdict=None):
    result={"schema":"deputy.worker-result.v1","run_id":rid,"overall":"BLOCKED","blocked_reason":reason,"steps":[]}
    if execution_verdict is not None: result["execution_verdict"]=execution_verdict
    atomic_json(d/"result.json",result)
    st=read_json(d/"state.json"); st.update(state="BLOCKED",terminal_reason=reason,completed_at=time.time(),updated_at=time.time()); atomic_json(d/"state.json",st)

def main():
    root=Path(sys.argv[1]); rid=sys.argv[2]; d=root/"runs"/rid; job=read_json(d/"job.json"); results=[]; overall="PASS"; integrity=_integrity_dir(d)
    try:
        pre=capture_snapshot(host_root())
        atomic_json(integrity/"pre.json",pre)
    except Exception as exc:
        _write_blocked(d,rid,"REPOSITORY_PRE_SNAPSHOT_UNAVAILABLE")
        return 0
    for i,s in enumerate(job["steps"]):
        st=read_json(d/"state.json"); st.update(current_step_id=s["id"],current_step_index=i,updated_at=time.time()); atomic_json(d/"state.json",st); result={"id":s["id"],"operation":s["operation"],**(dispatch(s["operation"],s["params"]) if s["operation"] not in {"GRADLE","RUN_APPROVED_VERIFIER","ADB_LIST_DEVICES","ADB_WAIT_FOR_DEVICE","ADB_QUERY_PROPERTY","ADB_QUERY_PACKAGE","ADB_INSTALL","ADB_UNINSTALL_DEPUTY","ADB_CLEAR_DEPUTY_DATA","ADB_FORCE_STOP_DEPUTY","ADB_START_DEPUTY_ACTIVITY","ADB_INSTRUMENT","ADB_LOGCAT_CAPTURE","ADB_PUSH_SCOPED","ADB_PULL_SCOPED","ADB_DUMPSYS_REGISTERED"} else dispatch(s["operation"],s["params"] | {"_evidence_dir": str(d/"steps"/s["id"])}))}; results.append(result); sd=d/"steps"/s["id"]; sd.mkdir(parents=True,exist_ok=True); atomic_json(sd/"result.json",result)
        if result.get("status")!="PASS": overall=result.get("status","FAIL"); break
    try:
        post=capture_snapshot(host_root())
        atomic_json(integrity/"post.json",post)
    except Exception:
        result={"schema":"deputy.worker-result.v1","run_id":rid,"overall":"UNPROVEN","unproven_reason":"REPOSITORY_POST_SNAPSHOT_UNAVAILABLE","execution_verdict":overall,"steps":results}
        atomic_json(d/"result.json",result); st=read_json(d/"state.json"); st.update(state="UNPROVEN",completed_at=time.time(),updated_at=time.time()); atomic_json(d/"state.json",st); return 0
    try:
        comparison=compare_snapshots(pre,post)
        atomic_json(integrity/"comparison.json",comparison)
    except Exception:
        result={"schema":"deputy.worker-result.v1","run_id":rid,"overall":"UNPROVEN","unproven_reason":"REPOSITORY_INTEGRITY_COMPARISON_UNAVAILABLE","execution_verdict":overall,"steps":results}
        atomic_json(d/"result.json",result); st=read_json(d/"state.json"); st.update(state="UNPROVEN",completed_at=time.time(),updated_at=time.time()); atomic_json(d/"state.json",st); return 0
    final= "CONTRADICTION" if not comparison.get("same") else overall
    result={"schema":"deputy.worker-result.v1","run_id":rid,"overall":final,"execution_verdict":overall,"steps":results,"integrity":{"pre_path":str(integrity/"pre.json"),"post_path":str(integrity/"post.json"),"comparison_path":str(integrity/"comparison.json"),**comparison}}
    atomic_json(d/"result.json",result); st=read_json(d/"state.json"); st.update(state=final,completed_at=time.time(),updated_at=time.time()); atomic_json(d/"state.json",st); return 0

def host_root():
    from .host_ops import REPO_ROOT
    return REPO_ROOT
if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        root=Path(sys.argv[1]); rid=sys.argv[2]; d=root/"runs"/rid
        d.mkdir(parents=True,exist_ok=True)
        atomic_json(d/"bootstrap-error.json",{"schema":"deputy.worker-bootstrap-error.v1","run_id":rid,"stage":"production_worker_main","exception_type":type(exc).__name__,"message":str(exc)[:1024],"traceback":"".join(traceback.format_exception(type(exc),exc,exc.__traceback__))[-8192:]})
        raise
