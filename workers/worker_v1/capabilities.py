from __future__ import annotations
import json, os, re, sys
from pathlib import Path
from config import DEPUTY_SHELL_ROOT

_SOURCE_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "WORKER_CAPABILITIES.json"
_INSTALLED_REGISTRY_PATH = Path(sys.prefix) / "share" / "deputy-workers-mcp" / "WORKER_CAPABILITIES.json"
REGISTRY_PATH = _SOURCE_REGISTRY_PATH if _SOURCE_REGISTRY_PATH.exists() else _INSTALLED_REGISTRY_PATH
FROZEN = {"CAPTURE_REPO_STATE","GRADLE","RUN_APPROVED_VERIFIER","PARSE_JUNIT","CHECK_FILE","HASH_ARTIFACT","GIT_DIFF_CHECK","CAPTURE_PROCESS_EVIDENCE","ADB_LIST_DEVICES","ADB_WAIT_FOR_DEVICE","ADB_QUERY_PROPERTY","ADB_QUERY_PACKAGE","ADB_INSTALL","ADB_UNINSTALL_DEPUTY","ADB_CLEAR_DEPUTY_DATA","ADB_FORCE_STOP_DEPUTY","ADB_START_DEPUTY_ACTIVITY","ADB_INSTRUMENT","ADB_LOGCAT_CAPTURE","ADB_PUSH_SCOPED","ADB_PULL_SCOPED","ADB_DUMPSYS_REGISTERED"}
REPO_ROOT = DEPUTY_SHELL_ROOT
MAX_STEPS=32; MAX_STRING=256; MAX_SERIAL=128
FORBIDDEN={"command","shell","shell_command","executable","binary","argv","powershell","cmd","script_path","env","environment","api_key","token","password","url","http_method","body","adb_args","package"}
KNOWN_PARAMETER_SCHEMAS={"empty.v1","capture_repo_state.v1","git_diff_check.v1","serial.v1","property.v1","package.v1","serial_limit.v1","file.v1","verifier.v1","gradle.v1","junit.v1","process.v1","artifact_serial.v1","activity.v1","instrument.v1","dumpsys.v1"}
APPROVED_GRADLE_TASKS={"VERIFY_EXECUTION_SUBSTRATE_VALIDATION_MANIFEST_ISOLATION":"verifyExecutionSubstrateValidationManifestIsolation"}
APPROVED_VERIFIERS={"VERIFY_RUNTIME_INTEGRITY_MANIFEST":"tools/android/verify-runtime-integrity-manifest.py"}
APPROVED_JUNIT_REPORTS={"APP_DEBUG_UNIT_TEST":"app/build/test-results/testDebugUnitTest/TEST-*.xml"}
APPROVED_ARTIFACTS={"DEPUTY_DEBUG_APK":"app/build/outputs/apk/debug/app-debug.apk","DEPUTY_RELEASE_APK":"app/build/outputs/apk/release/app-release.apk"}
APPROVED_ACTIVITIES={"DEPUTY_MAIN":"com.deputyshell.app/.MainActivity"}
APPROVED_INSTRUMENTATION={"DEPUTY_SHELL_SMOKE":{"package":"com.deputyshell.app.test","target_package":"com.deputyshell.app","runner":"androidx.test.runner.AndroidJUnitRunner","class":"com.deputyshell.app.DeputyShellInstrumentationTest"}}
APPROVED_DUMPSYS={"DEPUTY_PACKAGE":"package com.deputyshell.app"}

def _err(code,path,reason): return {"code":code,"path":path,"reason":reason}
def load_registry(path=REGISTRY_PATH):
    try: data=json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception: raise ValueError("REGISTRY_INVALID")
    if data.get("schema")!="deputy.worker-capabilities.v1" or data.get("version")!=1: raise ValueError("REGISTRY_UNSUPPORTED_VERSION")
    caps=data.get("capabilities")
    if not isinstance(caps,list) or len(caps)!=len(FROZEN): raise ValueError("REGISTRY_INVALID_CAPABILITIES")
    seen=set()
    for c in caps:
        required={"operation","family","enabled","authorization","implementation","params_schema"}
        if not isinstance(c,dict) or not required.issubset(c) or c.get("operation") in seen or c.get("operation") not in FROZEN: raise ValueError("REGISTRY_DUPLICATE_OR_UNKNOWN_OPERATION")
        seen.add(c["operation"])
        if c.get("family") not in {"HOST","ADB"} or c.get("implementation") not in {"VALIDATION_ONLY", "IMPLEMENTED"} or not isinstance(c.get("enabled"),bool): raise ValueError("REGISTRY_INVALID_METADATA")
        if c.get("params_schema") not in KNOWN_PARAMETER_SCHEMAS: raise ValueError("UNRESOLVED_PARAMETER_SCHEMA")
        if any(k in c for k in FORBIDDEN): raise ValueError("REGISTRY_EXECUTION_FIELD")
    if seen!=FROZEN: raise ValueError("REGISTRY_MISSING_OPERATION")
    return {c["operation"]:c for c in caps}

def _bounded_string(v,path,maxlen=MAX_STRING):
    return isinstance(v,str) and 0<len(v)<=maxlen and not any(ord(x)<32 for x in v)
def _repo_path(v,path):
    if not _bounded_string(v,path,512) or os.path.isabs(v) or re.match(r"^[A-Za-z]:|^\\\\",v): return False
    try:
        candidate=(REPO_ROOT / Path(v.replace('\\','/'))).resolve()
        root=REPO_ROOT.resolve()
        return candidate != root and root in candidate.parents
    except (OSError,RuntimeError,ValueError): return False
def _params(op,p,registry):
    if not isinstance(p,dict): return "PARAMS_TYPE"
    if any(k in FORBIDDEN for k in p): return "FORBIDDEN_PARAMETER"
    schema=registry[op]["params_schema"]
    allowed={"empty.v1":set(),"capture_repo_state.v1":set(),"git_diff_check.v1":set(),"serial.v1":{"serial"},"property.v1":{"serial","property"},"package.v1":{"serial"},"serial_limit.v1":{"serial","limit"},"file.v1":{"path"},"verifier.v1":{"verifier_id"},"gradle.v1":{"task_id"},"junit.v1":{"report_id"},"process.v1":{"pid"},"artifact_serial.v1":{"serial","artifact_id"},"activity.v1":{"serial","activity_id"},"instrument.v1":{"serial","runner_id"},"dumpsys.v1":{"serial","query_id"}}
    if schema not in allowed or set(p)-allowed[schema]: return "UNKNOWN_PARAMETER"
    required={"empty.v1":set(),"capture_repo_state.v1":set(),"git_diff_check.v1":set(),"serial.v1":{"serial"},"property.v1":{"serial","property"},"package.v1":{"serial"},"serial_limit.v1":{"serial","limit"},"file.v1":{"path"},"verifier.v1":{"verifier_id"},"gradle.v1":{"task_id"},"junit.v1":{"report_id"},"process.v1":{"pid"},"artifact_serial.v1":{"serial","artifact_id"},"activity.v1":{"serial","activity_id"},"instrument.v1":{"serial","runner_id"},"dumpsys.v1":{"serial","query_id"}}
    if set(p)!=required.get(schema,set()): return "MISSING_OR_UNKNOWN_PARAMETER"
    if 'serial' in allowed.get(schema,set()) and (not _bounded_string(p.get('serial'),"serial",MAX_SERIAL)): return "INVALID_SERIAL"
    if schema in {"file.v1"} and not _repo_path(p.get('path'),"path"): return "INVALID_REPO_PATH"
    if schema=="property.v1" and p.get('property') not in {"ro.build.version.sdk","ro.product.cpu.abi"}: return "UNAPPROVED_PROPERTY"
    if schema=="package.v1": pass
    if schema=="activity.v1" and p.get("activity_id") not in APPROVED_ACTIVITIES: return "UNAPPROVED_ANDROID_TARGET"
    if schema=="instrument.v1" and p.get("runner_id") not in APPROVED_INSTRUMENTATION: return "UNAPPROVED_ANDROID_TARGET"
    if schema in {"verifier.v1","gradle.v1"} and not _bounded_string(p.get("verifier_id",p.get("task_id")),"id",128): return "INVALID_APPROVED_ID"
    if schema=="junit.v1" and not _bounded_string(p.get("report_id"),"report_id",128): return "INVALID_REPORT_ID"
    if schema=="artifact_serial.v1" and (not _bounded_string(p.get("artifact_id"),"artifact_id",128) or p.get("artifact_id") not in APPROVED_ARTIFACTS): return "UNAPPROVED_ARTIFACT"
    if schema=="dumpsys.v1" and p.get("query_id") not in APPROVED_DUMPSYS: return "UNAPPROVED_DUMPSYS_QUERY"
    if schema=="serial_limit.v1" and (not isinstance(p.get('limit'),int) or not 0<p['limit']<=100000): return "INVALID_LIMIT"
    if schema=="process.v1" and (not isinstance(p.get('pid'),int) or not 0<p['pid']<=2**31-1): return "INVALID_PID"
    for k in set(p)-{"serial","path","property","package_id","limit","pid","verifier_id","task_id","report_id","artifact_id","activity_id","runner_id","query_id"}:
        return "UNKNOWN_PARAMETER"
    if schema=="verifier.v1" and p.get('verifier_id') not in APPROVED_VERIFIERS: return "UNAPPROVED_VERIFIER"
    if schema=="gradle.v1" and p.get('task_id') not in APPROVED_GRADLE_TASKS: return "UNAPPROVED_GRADLE_TASK"
    if schema=="junit.v1" and p.get('report_id') not in APPROVED_JUNIT_REPORTS: return "UNAPPROVED_REPORT"
    return None

def validate_job(job, registry_path=REGISTRY_PATH):
    errors=[]
    try: registry=load_registry(registry_path)
    except ValueError as e: return {"valid":False,"errors":[_err(str(e),"registry","registry failed closed")]}
    if not isinstance(job,dict): return {"valid":False,"errors":[_err("JOB_TYPE","$","job must be object")]}
    if set(job)-{"schema","repo","steps"}: errors.append(_err("UNKNOWN_FIELD","$","unknown top-level field"))
    if job.get('schema')!="deputy.worker.job.v1": errors.append(_err("SCHEMA_VERSION","schema","unsupported schema"))
    if job.get('repo')!={"binding":"deputy-authoritative-v1"}: errors.append(_err("REPO_BINDING","repo","authoritative binding required"))
    steps=job.get('steps');
    if not isinstance(steps,list) or len(steps)>MAX_STEPS: errors.append(_err("STEP_COUNT","steps","invalid or excessive step count")); steps=[]
    seen=set()
    for i,s in enumerate(steps):
        path=f"steps[{i}]"
        if not isinstance(s,dict) or set(s)-{"id","operation","params"}: errors.append(_err("STEP_FIELDS",path,"invalid step fields")); continue
        if not _bounded_string(s.get('id'),path+'.id',64) or s['id'] in seen: errors.append(_err("STEP_ID","%s.id"%path,"missing or duplicate step id"))
        seen.add(s.get('id'))
        op=s.get('operation')
        if op not in registry or not registry[op].get('enabled'): errors.append(_err("UNKNOWN_OPERATION",path+'.operation',"operation is not approved")); continue
        e=_params(op,s.get('params',{}),registry)
        if e: errors.append(_err(e,path+'.params',"parameters rejected"))
    return {"valid":not errors,"schema":"deputy.worker.job.v1","normalized_job":job if not errors else None,"errors":errors[:32]}
