from __future__ import annotations

import hashlib
import os
import subprocess
import time
import xml.etree.ElementTree as ET
import glob
import re
from pathlib import Path
from .capabilities import APPROVED_GRADLE_TASKS, APPROVED_VERIFIERS, APPROVED_JUNIT_REPORTS, APPROVED_ARTIFACTS, APPROVED_ACTIVITIES, APPROVED_INSTRUMENTATION, APPROVED_DUMPSYS
from .process import evidence as process_evidence
from config import ADB_EXE, ANDROID_SDK_ROOT, DEPUTY_SHELL_ROOT, TRUSTED_PYTHON

REPO_ROOT = DEPUTY_SHELL_ROOT.resolve()
MAX_OUTPUT = 32768
IMPLEMENTED = {"CAPTURE_REPO_STATE", "CHECK_FILE", "HASH_ARTIFACT", "GIT_DIFF_CHECK", "GRADLE", "RUN_APPROVED_VERIFIER", "PARSE_JUNIT", "CAPTURE_PROCESS_EVIDENCE", "ADB_LIST_DEVICES", "ADB_WAIT_FOR_DEVICE", "ADB_QUERY_PROPERTY", "ADB_QUERY_PACKAGE", "ADB_INSTALL", "ADB_UNINSTALL_DEPUTY", "ADB_CLEAR_DEPUTY_DATA", "ADB_FORCE_STOP_DEPUTY", "ADB_START_DEPUTY_ACTIVITY", "ADB_INSTRUMENT", "ADB_LOGCAT_CAPTURE", "ADB_PUSH_SCOPED", "ADB_PULL_SCOPED", "ADB_DUMPSYS_REGISTERED"}
GRADLE_WRAPPER = REPO_ROOT / "gradlew.bat"
MAX_GRADLE_OUTPUT = 32768
MAX_JUNIT_FILES = 32
MAX_JUNIT_FILE_BYTES = 4 * 1024 * 1024
MAX_JUNIT_TOTAL_BYTES = 16 * 1024 * 1024
MAX_JUNIT_TESTCASES = 100000
MAX_JUNIT_TEXT = 1024
TRUSTED_ANDROID_SDK = ANDROID_SDK_ROOT
TRUSTED_ADB = ADB_EXE
ADB_MAX_OUTPUT = 32768
ADB_PACKAGE = "com.deputyshell.app"
ADB_PROPERTIES = {"ro.build.version.sdk":"ro.build.version.sdk", "ro.product.cpu.abi":"ro.product.cpu.abi"}
ADB_TRANSFER_ROOT = "/data/local/tmp/deputy-workers"
ADB_HOST_EVIDENCE_ROOT = REPO_ROOT / ".deputy-worker-evidence"

def _adb_ready():
    return TRUSTED_ADB if TRUSTED_ADB.is_file() else None

def _adb_run(args, evidence_dir):
    adb=_adb_ready()
    if adb is None: return {"status":"BLOCKED","reason":"TRUSTED_ADB_UNAVAILABLE"}
    started=time.time(); evidence_dir=Path(evidence_dir); evidence_dir.mkdir(parents=True,exist_ok=True)
    try:
        p=subprocess.Popen([str(adb),*args],cwd=str(REPO_ROOT),env=os.environ.copy(),shell=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace")
        stdout,stderr=p.communicate()
    except OSError as exc: return {"status":"BLOCKED","reason":"ADB_START_FAILED","error":str(exc)[:512]}
    ended=time.time(); (evidence_dir/"adb.stdout.log").write_text(stdout,encoding="utf-8"); (evidence_dir/"adb.stderr.log").write_text(stderr,encoding="utf-8")
    return {"adb_path":str(adb),"args":args,"started_at":started,"ended_at":ended,"duration_ms":int((ended-started)*1000),"pid":p.pid,"exit_code":p.returncode,"stdout":stdout[:ADB_MAX_OUTPUT],"stderr":stderr[:ADB_MAX_OUTPUT],"stdout_log":str(evidence_dir/"adb.stdout.log"),"stderr_log":str(evidence_dir/"adb.stderr.log")}

def _device_rows(stdout):
    rows=[]
    for line in stdout.splitlines():
        if not line or line.startswith("List of devices attached") or line.startswith("*"): continue
        fields=line.split();
        if len(fields)<2: continue
        row={"serial":fields[0],"state":fields[1]}
        for f in fields[2:]:
            if ":" in f:
                k,v=f.split(":",1); row[k]=v
        rows.append(row)
    return rows

def adb_list_devices(params, evidence_dir):
    evidence_dir = Path(params.pop("_evidence_dir", evidence_dir))
    raw=_adb_run(["devices","-l"],evidence_dir)
    if raw.get("status")=="BLOCKED": return raw
    rows=_device_rows(raw.get("stdout","")); return {**raw,"status":"PASS" if raw.get("exit_code")==0 else "BLOCKED","devices":rows[:64]}

def adb_wait_for_device(params, evidence_dir):
    evidence_dir = Path(params.pop("_evidence_dir", evidence_dir))
    serial=params["serial"]; raw=_adb_run(["-s",serial,"get-state"],evidence_dir)
    if raw.get("status")=="BLOCKED": return raw
    state=raw.get("stdout","").strip().lower()
    if raw.get("exit_code")==0 and state=="device": return {**raw,"status":"PASS","serial":serial,"state":"device"}
    if "unauthorized" in state or "unauthorized" in raw.get("stderr","").lower(): return {**raw,"status":"BLOCKED","reason":"DEVICE_UNAUTHORIZED","serial":serial,"state":"unauthorized"}
    if "offline" in state or "offline" in raw.get("stderr","").lower(): return {**raw,"status":"BLOCKED","reason":"DEVICE_OFFLINE","serial":serial,"state":"offline"}
    return {**raw,"status":"BLOCKED","reason":"TARGET_DEVICE_NOT_FOUND","serial":serial}

def adb_query_property(params, evidence_dir):
    evidence_dir = Path(params.pop("_evidence_dir", evidence_dir))
    prop=ADB_PROPERTIES.get(params.get("property"));
    if prop is None: return {"status":"BLOCKED","reason":"UNAPPROVED_PROPERTY"}
    raw=_adb_run(["-s",params["serial"],"shell","getprop",prop],evidence_dir)
    if raw.get("status")=="BLOCKED": return raw
    if raw.get("exit_code")!=0: return {**raw,"status":"BLOCKED","reason":"ADB_PROPERTY_QUERY_FAILED","serial":params["serial"],"property":prop}
    return {**raw,"status":"PASS","serial":params["serial"],"property":prop,"value":raw.get("stdout","").strip()[:1024]}

def adb_query_package(params, evidence_dir):
    evidence_dir = Path(params.pop("_evidence_dir", evidence_dir))
    raw=_adb_run(["-s",params["serial"],"shell","pm","path",ADB_PACKAGE],evidence_dir)
    if raw.get("status")=="BLOCKED": return raw
    if raw.get("exit_code")!=0:
        err=raw.get("stderr","").lower(); reason="DEVICE_OFFLINE" if "offline" in err else "DEVICE_UNAUTHORIZED" if "unauthorized" in err else "PACKAGE_QUERY_OUTPUT_UNAVAILABLE"
        return {**raw,"status":"BLOCKED","reason":reason,"serial":params["serial"],"package_id":ADB_PACKAGE}
    paths=[]
    for line in raw.get("stdout","").splitlines():
        if line.startswith("package:"):
            value=line[8:].strip()
            if value and len(value)<=4096 and "\n" not in value: paths.append(value)
    paths=paths[:8]
    return {**raw,"status":"PASS","serial":params["serial"],"package_id":ADB_PACKAGE,"installed":bool(paths),"apk_paths":paths,"path_count":len(paths)}

def _adb_typed(raw, **extra): return {**raw, "status": "PASS" if raw.get("exit_code") == 0 else "BLOCKED", **extra}
def adb_install(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); artifact=params["artifact_id"]; rel=APPROVED_ARTIFACTS.get(artifact); apk=REPO_ROOT/rel if rel else None
    if apk is None or not apk.is_file(): return {"status":"BLOCKED","reason":"APPROVED_ARTIFACT_UNAVAILABLE","artifact_id":artifact}
    digest=hashlib.sha256(apk.read_bytes()).hexdigest(); raw=_adb_run(["-s",params["serial"],"install","-r",str(apk)],evidence_dir)
    return _adb_typed(raw,serial=params["serial"],artifact_id=artifact,artifact_path=str(apk),artifact_size=apk.stat().st_size,artifact_sha256=digest)
def adb_uninstall(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); raw=_adb_run(["-s",params["serial"],"uninstall",ADB_PACKAGE],evidence_dir); text=(raw.get("stdout","")+raw.get("stderr","")).lower()
    if raw.get("exit_code")!=0 and "unknown package" not in text: return {**raw,"status":"BLOCKED","reason":"ADB_UNINSTALL_FAILED"}
    return {**raw,"status":"PASS","serial":params["serial"],"package_id":ADB_PACKAGE,"present_after":False,"already_absent":"unknown package" in text}
def adb_clear_data(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); raw=_adb_run(["-s",params["serial"],"shell","pm","clear",ADB_PACKAGE],evidence_dir); return _adb_typed(raw,serial=params["serial"],package_id=ADB_PACKAGE,cleared=raw.get("exit_code")==0)
def adb_force_stop(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); raw=_adb_run(["-s",params["serial"],"shell","am","force-stop",ADB_PACKAGE],evidence_dir); return _adb_typed(raw,serial=params["serial"],package_id=ADB_PACKAGE)
def adb_start_activity(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); component=APPROVED_ACTIVITIES[params["activity_id"]]; raw=_adb_run(["-s",params["serial"],"shell","am","start","-n",component],evidence_dir); return _adb_typed(raw,serial=params["serial"],activity_id=params["activity_id"],component=component)
def adb_instrument(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); target=APPROVED_INSTRUMENTATION[params["runner_id"]]; component=f"{target['package']}/{target['runner']}"; raw=_adb_run(["-s",params["serial"],"shell","am","instrument","-w","-r","-e","class",target["class"],component],evidence_dir)
    protocol=parse_instrumentation_output(raw.get("stdout",""), raw.get("stderr",""), raw.get("exit_code"))
    status="BLOCKED" if raw.get("status")=="BLOCKED" or protocol["verdict"]=="BLOCKED" else protocol["verdict"]
    return {**raw,"status":status,"serial":params["serial"],"runner_id":params["runner_id"],"component":component,"target":target,"instrumentation":protocol}

def parse_instrumentation_output(stdout, stderr, transport_exit_code):
    text=(stdout or "")+"\n"+(stderr or "")
    markers={"status_lines":[],"status_codes":[],"result_lines":[],"instrumentation_codes":[],"process_crash":False}
    for line in (stdout or "").splitlines():
        if line.startswith("INSTRUMENTATION_STATUS:"): markers["status_lines"].append(line[:2048])
        elif line.startswith("INSTRUMENTATION_STATUS_CODE:"): markers["status_codes"].append(line[:256])
        elif line.startswith("INSTRUMENTATION_RESULT:"): markers["result_lines"].append(line[:2048])
        elif line.startswith("INSTRUMENTATION_CODE:"): markers["instrumentation_codes"].append(line[:256])
    lower=text.lower(); markers["process_crash"] = "process crashed" in lower or "fatal exception" in lower or "abstractmethoderror" in lower
    if transport_exit_code not in (0,): return {"verdict":"BLOCKED","reason":"ADB_TRANSPORT_FAILED","markers":markers}
    if markers["process_crash"]: return {"verdict":"FAIL","reason":"INSTRUMENTATION_PROCESS_CRASH","markers":markers}
    if not markers["instrumentation_codes"] and not markers["status_codes"]: return {"verdict":"BLOCKED","reason":"INSTRUMENTATION_RESULT_UNAVAILABLE","markers":markers}
    if any(("shortMsg=" in x or "Error=" in x or "failure" in x.lower()) for x in markers["result_lines"]): return {"verdict":"FAIL","reason":"INSTRUMENTATION_TEST_FAILURE","markers":markers}
    try: final_code=int(markers["instrumentation_codes"][-1].split(":",1)[1].strip())
    except (IndexError,ValueError): final_code=None
    if final_code == -1: return {"verdict":"PASS","reason":"INSTRUMENTATION_SUCCESS","markers":markers}
    if final_code is not None: return {"verdict":"FAIL","reason":"INSTRUMENTATION_NON_SUCCESS_CODE","markers":markers}
    return {"verdict":"BLOCKED","reason":"INSTRUMENTATION_RESULT_INCOMPLETE","markers":markers}
def adb_logcat(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); limit=min(params["limit"],2000); raw=_adb_run(["-s",params["serial"],"logcat","-b","main","-v","threadtime","-t",str(limit)],evidence_dir); text=raw.get("stdout","")[:ADB_MAX_OUTPUT]; evidence_dir.mkdir(parents=True,exist_ok=True); (evidence_dir/"logcat.txt").write_text(text,encoding="utf-8"); return _adb_typed(raw,serial=params["serial"],line_limit=limit,line_count=len(text.splitlines()),evidence_file=str(evidence_dir/"logcat.txt"))
def _scoped_host_file(artifact):
    if artifact=="W6A_TEST_TEXT":
        p=ADB_HOST_EVIDENCE_ROOT/"w6a-test.txt"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text("Deputy Workers scoped transfer test\n",encoding="utf-8"); return p
    rel=APPROVED_ARTIFACTS.get(artifact); return REPO_ROOT/rel if rel else None
def adb_push(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); source=_scoped_host_file(params["artifact_id"])
    if source is None or not source.is_file(): return {"status":"BLOCKED","reason":"SCOPED_SOURCE_UNAVAILABLE"}
    raw=_adb_run(["-s",params["serial"],"push",str(source),f"{ADB_TRANSFER_ROOT}/{source.name}"],evidence_dir); return _adb_typed(raw,serial=params["serial"],artifact_id=params["artifact_id"],source_size=source.stat().st_size,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),device_path=f"{ADB_TRANSFER_ROOT}/{source.name}")
def adb_pull(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); source=_scoped_host_file(params["artifact_id"])
    if source is None: return {"status":"BLOCKED","reason":"SCOPED_SOURCE_UNAVAILABLE"}
    dest=evidence_dir/"pulled"/source.name; dest.parent.mkdir(parents=True,exist_ok=True); raw=_adb_run(["-s",params["serial"],"pull",f"{ADB_TRANSFER_ROOT}/{source.name}",str(dest)],evidence_dir)
    if raw.get("exit_code")!=0: return {**raw,"status":"BLOCKED","reason":"ADB_PULL_FAILED"}
    return {**raw,"status":"PASS","serial":params["serial"],"artifact_id":params["artifact_id"],"pulled_path":str(dest),"size":dest.stat().st_size,"sha256":hashlib.sha256(dest.read_bytes()).hexdigest()}
def adb_dumpsys(params, evidence_dir):
    evidence_dir=Path(params.pop("_evidence_dir", evidence_dir)); query=APPROVED_DUMPSYS[params["query_id"]]; raw=_adb_run(["-s",params["serial"],"shell","dumpsys","package",ADB_PACKAGE],evidence_dir); text=raw.get("stdout","")[:ADB_MAX_OUTPUT]; evidence_dir.mkdir(parents=True,exist_ok=True); (evidence_dir/"dumpsys.txt").write_text(text,encoding="utf-8"); return _adb_typed(raw,serial=params["serial"],query_id=query,evidence_file=str(evidence_dir/"dumpsys.txt"),output=text)


def _safe_path(value: str) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value or os.path.isabs(value) or value.startswith("\\\\") or (len(value) > 1 and value[1] == ":"):
        return None, "PATH_OUTSIDE_REPOSITORY"
    try:
        candidate = (REPO_ROOT / Path(value.replace("\\", "/"))).resolve()
        if candidate == REPO_ROOT or REPO_ROOT not in candidate.parents:
            return None, "PATH_OUTSIDE_REPOSITORY"
        return candidate, None
    except (OSError, RuntimeError, ValueError):
        return None, "PATH_OUTSIDE_REPOSITORY"


def _git(args: list[str]) -> dict:
    p = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False)
    return {"exit_code": p.returncode, "stdout": p.stdout[:MAX_OUTPUT], "stderr": p.stderr[:MAX_OUTPUT]}


def capture_repo_state() -> dict:
    def one(args):
        return _git(args)["stdout"].strip()
    status = one(["status", "--short"])
    tracked = one(["diff", "--name-only"])
    staged = one(["diff", "--cached", "--name-only"])
    untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    origin = one(["remote", "get-url", "origin"])
    if origin.startswith("https://"):
        origin = origin.split("@")[-1].split("/")[0] if "@" in origin else origin.split("/")[2]
    return {"status": "PASS", "repo_root": str(REPO_ROOT), "head": one(["rev-parse", "HEAD"]), "branch": one(["branch", "--show-current"]), "upstream": one(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]) if _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])["exit_code"] == 0 else None, "origin": origin, "status_short": status[:MAX_OUTPUT], "unstaged_diff_names": tracked.splitlines()[:1024], "staged_diff_names": staged.splitlines()[:1024], "untracked_names": untracked[:1024], "dirty": bool(status)}


def check_file(params: dict) -> dict:
    path, error = _safe_path(params.get("path"))
    if error: return {"status": "BLOCKED", "reason": error}
    if not path.exists() or not path.is_file(): return {"status": "FAIL", "path": params["path"]}
    return {"status": "PASS", "path": params["path"], "size": path.stat().st_size}


def hash_artifact(params: dict) -> dict:
    path, error = _safe_path(params.get("path"))
    if error: return {"status": "BLOCKED", "reason": error}
    if not path.exists() or not path.is_file(): return {"status": "FAIL", "path": params["path"]}
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): digest.update(chunk)
    return {"status": "PASS", "path": params["path"], "size": path.stat().st_size, "sha256": digest.hexdigest()}


def git_diff_check() -> dict:
    result = _git(["diff", "--check"])
    if result["exit_code"] == 0: return {"status": "PASS", **result}
    return {"status": "FAIL", **result}


def resolve_trusted_android_sdk() -> Path | None:
    sdk = TRUSTED_ANDROID_SDK.resolve()
    required = (sdk / "platform-tools" / "adb.exe", sdk / "platforms", sdk / "build-tools", sdk / "cmdline-tools")
    return sdk if sdk.is_dir() and all(p.exists() for p in required) else None


def gradle(params: dict, evidence_dir: Path) -> dict:
    evidence_dir = Path(params.pop("_evidence_dir", evidence_dir))
    task_id = params.get("task_id")
    task = APPROVED_GRADLE_TASKS.get(task_id)
    if task is None:
        return {"status": "BLOCKED", "reason": "UNAPPROVED_GRADLE_TASK"}
    if not GRADLE_WRAPPER.is_file():
        return {"status": "BLOCKED", "reason": "GRADLE_WRAPPER_UNAVAILABLE"}
    sdk = resolve_trusted_android_sdk()
    if sdk is None:
        return {"status": "BLOCKED", "reason": "TRUSTED_ANDROID_SDK_UNAVAILABLE"}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    command = [str(GRADLE_WRAPPER), task]
    try:
        environment = os.environ.copy()
        environment["ANDROID_HOME"] = str(sdk)
        environment["ANDROID_SDK_ROOT"] = str(sdk)
        p = subprocess.Popen(command, cwd=str(REPO_ROOT), env=environment, shell=False,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace")
        stdout, stderr = p.communicate()
    except OSError as exc:
        return {"status": "BLOCKED", "reason": "GRADLE_START_FAILED", "error": str(exc)[:512]}
    ended = time.time()
    (evidence_dir / "gradle.stdout.log").write_text(stdout, encoding="utf-8")
    (evidence_dir / "gradle.stderr.log").write_text(stderr, encoding="utf-8")
    return {"status": "PASS" if p.returncode == 0 else "FAIL", "task_id": task_id,
            "gradle_task": task, "command": command, "started_at": started,
            "ended_at": ended, "duration_ms": int((ended-started)*1000),
            "pid": p.pid, "exit_code": p.returncode,
            "stdout": stdout[:MAX_GRADLE_OUTPUT], "stderr": stderr[:MAX_GRADLE_OUTPUT],
            "android_sdk": str(sdk),
            "stdout_log": str(evidence_dir / "gradle.stdout.log"),
            "stderr_log": str(evidence_dir / "gradle.stderr.log")}


def verifier(params: dict, evidence_dir: Path) -> dict:
    evidence_dir = Path(params.pop("_evidence_dir", evidence_dir))
    verifier_id = params.get("verifier_id")
    relative_script = APPROVED_VERIFIERS.get(verifier_id)
    script = REPO_ROOT / relative_script if relative_script else None
    if script is None:
        return {"status": "BLOCKED", "reason": "UNAPPROVED_VERIFIER"}
    if not TRUSTED_PYTHON.is_file():
        return {"status": "BLOCKED", "reason": "TRUSTED_WORKER_INTERPRETER_UNAVAILABLE"}
    if not script.is_file():
        return {"status": "BLOCKED", "reason": "APPROVED_VERIFIER_UNAVAILABLE"}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    command = [str(TRUSTED_PYTHON), str(script)]
    try:
        p = subprocess.Popen(command, cwd=str(REPO_ROOT), env=os.environ.copy(), shell=False,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace")
        stdout, stderr = p.communicate()
    except OSError as exc:
        return {"status": "BLOCKED", "reason": "VERIFIER_START_FAILED", "error": str(exc)[:512]}
    ended = time.time()
    (evidence_dir / "verifier.stdout.log").write_text(stdout, encoding="utf-8")
    (evidence_dir / "verifier.stderr.log").write_text(stderr, encoding="utf-8")
    return {"status": "PASS" if p.returncode == 0 else "FAIL", "verifier_id": verifier_id,
            "script": str(script), "command": command, "started_at": started,
            "ended_at": ended, "duration_ms": int((ended-started)*1000),
            "pid": p.pid, "exit_code": p.returncode, "stdout": stdout[:MAX_GRADLE_OUTPUT],
            "stderr": stderr[:MAX_GRADLE_OUTPUT], "stdout_log": str(evidence_dir / "verifier.stdout.log"),
            "stderr_log": str(evidence_dir / "verifier.stderr.log")}


def parse_junit(params: dict) -> dict:
    report_id = params.get("report_id")
    pattern = APPROVED_JUNIT_REPORTS.get(report_id)
    if pattern is None:
        return {"status": "BLOCKED", "reason": "UNAPPROVED_REPORT"}
    files = sorted(Path(p) for p in glob.glob(str(REPO_ROOT / pattern)))
    if not files:
        return {"status": "FAIL", "reason": "EXPECTED_REPORT_ABSENT", "report_id": report_id, "files": []}
    if len(files) > MAX_JUNIT_FILES:
        return {"status": "BLOCKED", "reason": "JUNIT_FILE_COUNT_LIMIT"}
    total_bytes = sum(p.stat().st_size for p in files)
    if total_bytes > MAX_JUNIT_TOTAL_BYTES or any(p.stat().st_size > MAX_JUNIT_FILE_BYTES for p in files):
        return {"status": "BLOCKED", "reason": "JUNIT_SIZE_LIMIT"}
    suites=[]; failing=[]; tests=failures=errors=skipped=0; duration=0.0
    try:
        for path in files:
            root=ET.parse(path).getroot()
            nodes=[root] if root.tag == "testsuite" else list(root.findall("testsuite"))
            for suite in nodes:
                name=suite.get("name", "")
                stests=int(suite.get("tests", "0")); sfail=int(suite.get("failures", "0")); serr=int(suite.get("errors", "0")); sskip=int(suite.get("skipped", "0")); sdur=float(suite.get("time", "0") or 0)
                suites.append({"name":name,"tests":stests,"failures":sfail,"errors":serr,"skipped":sskip,"duration":sdur})
                tests += stests; failures += sfail; errors += serr; skipped += sskip; duration += sdur
                for case in suite.findall("testcase"):
                    failure=case.find("failure"); error=case.find("error")
                    if (failure is not None or error is not None) and len(failing) < MAX_JUNIT_TEXT:
                        node=failure if failure is not None else error
                        failing.append({"suite":name,"classname":case.get("classname",""),"name":case.get("name",""),"kind":"failure" if failure is not None else "error","text":(node.text or "")[:MAX_JUNIT_TEXT]})
                if tests > MAX_JUNIT_TESTCASES: return {"status":"BLOCKED","reason":"JUNIT_TESTCASE_LIMIT"}
    except (OSError, ET.ParseError, ValueError):
        return {"status":"BLOCKED","reason":"JUNIT_UNREADABLE_OR_MALFORMED","report_id":report_id}
    return {"status":"PASS" if failures == 0 and errors == 0 else "FAIL", "report_id":report_id, "files":[str(p) for p in files], "suites":suites, "tests":tests, "failures":failures, "errors":errors, "skipped":skipped, "duration":duration, "failing_testcases":failing}


def dispatch(operation: str, params: dict) -> dict:
    if operation == "CAPTURE_REPO_STATE": return capture_repo_state()
    if operation == "CHECK_FILE": return check_file(params)
    if operation == "HASH_ARTIFACT": return hash_artifact(params)
    if operation == "GIT_DIFF_CHECK": return git_diff_check()
    if operation == "GRADLE": return gradle(params, Path.cwd() / "evidence")
    if operation == "RUN_APPROVED_VERIFIER": return verifier(params, Path.cwd() / "evidence")
    if operation == "PARSE_JUNIT": return parse_junit(params)
    if operation == "CAPTURE_PROCESS_EVIDENCE": return process_evidence(params["pid"])
    if operation == "ADB_LIST_DEVICES": return adb_list_devices(params, Path.cwd() / "evidence")
    if operation == "ADB_WAIT_FOR_DEVICE": return adb_wait_for_device(params, Path.cwd() / "evidence")
    if operation == "ADB_QUERY_PROPERTY": return adb_query_property(params, Path.cwd() / "evidence")
    if operation == "ADB_QUERY_PACKAGE": return adb_query_package(params, Path.cwd() / "evidence")
    if operation == "ADB_INSTALL": return adb_install(params, Path.cwd() / "evidence")
    if operation == "ADB_UNINSTALL_DEPUTY": return adb_uninstall(params, Path.cwd() / "evidence")
    if operation == "ADB_CLEAR_DEPUTY_DATA": return adb_clear_data(params, Path.cwd() / "evidence")
    if operation == "ADB_FORCE_STOP_DEPUTY": return adb_force_stop(params, Path.cwd() / "evidence")
    if operation == "ADB_START_DEPUTY_ACTIVITY": return adb_start_activity(params, Path.cwd() / "evidence")
    if operation == "ADB_INSTRUMENT": return adb_instrument(params, Path.cwd() / "evidence")
    if operation == "ADB_LOGCAT_CAPTURE": return adb_logcat(params, Path.cwd() / "evidence")
    if operation == "ADB_PUSH_SCOPED": return adb_push(params, Path.cwd() / "evidence")
    if operation == "ADB_PULL_SCOPED": return adb_pull(params, Path.cwd() / "evidence")
    if operation == "ADB_DUMPSYS_REGISTERED": return adb_dumpsys(params, Path.cwd() / "evidence")
    return {"status": "BLOCKED", "reason": "OPERATION_NOT_IMPLEMENTED"}
