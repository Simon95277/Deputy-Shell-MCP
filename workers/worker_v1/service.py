from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model

from . import host_ops
from .capabilities import (
    APPROVED_ACTIVITIES,
    APPROVED_ARTIFACTS,
    APPROVED_DUMPSYS,
    APPROVED_GRADLE_TASKS,
    APPROVED_INSTRUMENTATION,
    APPROVED_JUNIT_REPORTS,
    APPROVED_VERIFIERS,
    load_registry,
    validate_job,
)


OBSERVE_OPERATIONS = (
    "CAPTURE_REPO_STATE", "PARSE_JUNIT", "CHECK_FILE", "HASH_ARTIFACT",
    "GIT_DIFF_CHECK", "CAPTURE_PROCESS_EVIDENCE", "ADB_LIST_DEVICES",
    "ADB_WAIT_FOR_DEVICE", "ADB_QUERY_PROPERTY", "ADB_QUERY_PACKAGE",
    "ADB_LOGCAT_CAPTURE", "ADB_PULL_SCOPED", "ADB_DUMPSYS_REGISTERED",
)
ACT_OPERATIONS = (
    "GRADLE", "RUN_APPROVED_VERIFIER", "ADB_INSTALL", "ADB_UNINSTALL_DEPUTY",
    "ADB_CLEAR_DEPUTY_DATA", "ADB_FORCE_STOP_DEPUTY", "ADB_START_DEPUTY_ACTIVITY",
    "ADB_INSTRUMENT", "ADB_PUSH_SCOPED",
)
PUBLIC_OPERATION_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 0.05

_SERIAL = Annotated[str, StringConstraints(min_length=1, max_length=128)]
_PATH = Annotated[str, StringConstraints(min_length=1, max_length=512)]
_ID = Annotated[str, StringConstraints(min_length=1, max_length=128)]


def _literal(values):
    values = tuple(sorted(values))
    if not values:
        raise ValueError("PUBLIC_OPERATION_ENUM_EMPTY")
    return Literal[values]


def _params_for(schema: str, operation: str) -> dict:
    empty = {}
    file_path = {"path": (_PATH, Field(description="Bounded repository-relative path; absolute and parent paths are rejected."))}
    serial = {"serial": (_SERIAL, Field(description="Android device serial for this fixed operation."))}
    if schema in {"empty.v1", "capture_repo_state.v1", "git_diff_check.v1"}:
        return empty
    if schema == "file.v1":
        return file_path
    if schema == "serial.v1":
        return serial
    if schema == "property.v1":
        return {**serial, "property": (_literal(host_ops.ADB_PROPERTIES), Field(description="Approved Android property identifier."))}
    if schema == "package.v1":
        return serial
    if schema == "serial_limit.v1":
        return {**serial, "limit": (Annotated[int, Field(ge=1, le=2000)], Field(description="Maximum bounded log lines."))}
    if schema == "verifier.v1":
        return {"verifier_id": (_literal(APPROVED_VERIFIERS), Field(description="Server-registered verifier identifier."))}
    if schema == "gradle.v1":
        return {"task_id": (_literal(APPROVED_GRADLE_TASKS), Field(description="Server-registered Gradle task identifier."))}
    if schema == "junit.v1":
        return {"report_id": (_literal(APPROVED_JUNIT_REPORTS), Field(description="Server-registered JUnit report identifier."))}
    if schema == "process.v1":
        return {"pid": (Annotated[int, Field(gt=0)], Field(description="Positive process ID to inspect; no process command line is returned."))}
    if schema == "artifact_serial.v1":
        return {**serial, "artifact_id": (_literal(APPROVED_ARTIFACTS), Field(description="Server-registered artifact identifier."))}
    if schema == "activity.v1":
        return {**serial, "activity_id": (_literal(APPROVED_ACTIVITIES), Field(description="Server-registered activity identifier."))}
    if schema == "instrument.v1":
        return {**serial, "runner_id": (_literal(APPROVED_INSTRUMENTATION), Field(description="Server-registered instrumentation runner identifier."))}
    if schema == "dumpsys.v1":
        return {**serial, "query_id": (_literal(APPROVED_DUMPSYS), Field(description="Server-registered package query identifier."))}
    raise ValueError("PUBLIC_OPERATION_SCHEMA_UNSUPPORTED")


def _request_model(operation: str, parameter_schema: str):
    fields = {
        "operation": (_literal((operation,)), Field(description="Exact registered operation.")),
        **_params_for(parameter_schema, operation),
    }
    return create_model(
        f"{operation.title().replace('_', '')}Request",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _request_union(operations: tuple[str, ...]):
    registry = load_registry()
    if set(registry) != set(OBSERVE_OPERATIONS) | set(ACT_OPERATIONS):
        raise RuntimeError("PUBLIC_OPERATION_REGISTRY_MISMATCH")
    models = tuple(_request_model(name, registry[name]["params_schema"]) for name in operations)
    union = Union[models]
    return Annotated[union, Field(discriminator="operation")]


ObserveRequest = _request_union(OBSERVE_OPERATIONS)
ActRequest = _request_union(ACT_OPERATIONS)


_RESULT_FIELDS = {
    "CAPTURE_REPO_STATE": ("head", "branch", "dirty", "diff_check_pass"),
    "CHECK_FILE": ("path", "size"),
    "HASH_ARTIFACT": ("path", "size", "sha256", "exists"),
    "GIT_DIFF_CHECK": ("exit_code",),
    "GRADLE": ("task_id", "exit_code"),
    "RUN_APPROVED_VERIFIER": ("verifier_id", "exit_code"),
    "PARSE_JUNIT": ("report_status", "tests", "failures", "errors", "skipped", "duration_seconds", "failing_testcases"),
    "CAPTURE_PROCESS_EVIDENCE": ("alive",),
    "ADB_LIST_DEVICES": ("devices",),
    "ADB_WAIT_FOR_DEVICE": ("serial", "state"),
    "ADB_QUERY_PROPERTY": ("serial", "property", "value"),
    "ADB_QUERY_PACKAGE": ("serial", "package_id", "installed", "path_count"),
    "ADB_INSTALL": ("serial", "artifact_id", "exit_code"),
    "ADB_UNINSTALL_DEPUTY": ("serial", "package_id", "present_after", "already_absent"),
    "ADB_CLEAR_DEPUTY_DATA": ("serial", "package_id", "cleared"),
    "ADB_FORCE_STOP_DEPUTY": ("serial", "package_id", "exit_code"),
    "ADB_START_DEPUTY_ACTIVITY": ("serial", "activity_id", "exit_code"),
    "ADB_INSTRUMENT": ("serial", "runner_id", "instrumentation"),
    "ADB_LOGCAT_CAPTURE": ("serial", "line_limit", "line_count"),
    "ADB_PUSH_SCOPED": ("serial", "artifact_id", "source_size", "source_sha256"),
    "ADB_PULL_SCOPED": ("serial", "artifact_id", "size", "sha256"),
    "ADB_DUMPSYS_REGISTERED": ("serial", "query_id"),
}
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_ALLOWED_CODES = {
    "JOB_INVALID", "OPERATION_NOT_IMPLEMENTED", "OPERATION_QUEUE_TIMEOUT",
    "TRUSTED_WORKER_INTERPRETER_UNAVAILABLE", "WORKER_PROCESS_LOST", "REPOSITORY_INTEGRITY_UNAVAILABLE",
    "REPOSITORY_INTEGRITY_COMPARISON_UNAVAILABLE", "WORKER_TERMINATION_UNCONFIRMED",
    "REPOSITORY_PRE_SNAPSHOT_MISSING_AFTER_EXECUTION", "TRUSTED_ADB_UNAVAILABLE",
    "DEVICE_UNAUTHORIZED", "DEVICE_OFFLINE", "TARGET_DEVICE_NOT_FOUND", "ADB_TRANSPORT_FAILED",
    "ADB_START_FAILED", "GRADLE_WRAPPER_UNAVAILABLE", "TRUSTED_ANDROID_SDK_UNAVAILABLE",
    "APPROVED_VERIFIER_UNAVAILABLE", "EXPECTED_REPORT_ABSENT", "PROCESS_NOT_FOUND",
}


def _request_dict(value) -> dict:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("REQUEST_INVALID")


def _code_for(raw: dict) -> str:
    candidates = [raw.get("blocked_reason"), raw.get("unproven_reason"), raw.get("reason")]
    steps = raw.get("steps")
    if isinstance(steps, list):
        candidates.extend(step.get("reason") for step in steps if isinstance(step, dict))
    for candidate in candidates:
        if isinstance(candidate, str) and _REASON.fullmatch(candidate) and candidate in _ALLOWED_CODES:
            return candidate
    return "OPERATION_OUTCOME_UNAVAILABLE"


def project_outcome(operation: str, raw: dict) -> dict:
    status = raw.get("overall")
    if status not in {"PASS", "FAIL", "BLOCKED", "UNPROVEN", "CONTRADICTION", "CANCELLED"}:
        status = "UNPROVEN"
    output = {"status": status, "operation": operation}
    if status not in {"PASS", "FAIL"}:
        output.update({"code": _code_for(raw), "retryable": status in {"BLOCKED", "UNPROVEN"}})
    steps = raw.get("steps")
    step = steps[0] if isinstance(steps, list) and steps and isinstance(steps[0], dict) else {}
    source = step
    if operation == "CAPTURE_REPO_STATE" and not source:
        source = raw
    for key in _RESULT_FIELDS.get(operation, ()):
        if key == "diff_check_pass" and operation == "CAPTURE_REPO_STATE":
            diff_step = steps[1] if isinstance(steps, list) and len(steps) > 1 and isinstance(steps[1], dict) else {}
            output[key] = diff_step.get("status") == "PASS" and diff_step.get("exit_code") == 0
            continue
        if key == "exists" and operation == "HASH_ARTIFACT":
            output[key] = source.get("status") == "PASS"
            continue
        if key == "report_status" and operation == "PARSE_JUNIT":
            output[key] = "FAIL" if source.get("failures", 0) or source.get("errors", 0) else "PASS"
            continue
        if key == "duration_seconds" and operation == "PARSE_JUNIT":
            value = source.get("duration")
            if value is not None:
                output[key] = value
            continue
        if key not in source:
            continue
        value = source[key]
        if key == "failing_testcases" and isinstance(value, list):
            value = [{k: row.get(k) for k in ("suite", "classname", "name", "kind") if k in row}
                     for row in value[:32] if isinstance(row, dict)]
        if key == "devices" and isinstance(value, list):
            value = [{"serial": row.get("serial"), "state": row.get("state")}
                     for row in value[:64] if isinstance(row, dict)]
        if key == "instrumentation" and isinstance(value, dict):
            value = {"verdict": value.get("verdict"), "reason": value.get("reason")}
        output[key] = value
    return output


class WorkerService:
    def __init__(self, engine, timeout_seconds: int = PUBLIC_OPERATION_TIMEOUT_SECONDS):
        self.engine = engine
        self.timeout_seconds = timeout_seconds
        # The production engine owns one global active-run slot. Serialize the
        # synchronous public surface so concurrent callers never see that
        # lifecycle detail as an operation result.
        self._execution_lock = threading.Lock()

    def execute(self, request, permitted: tuple[str, ...]) -> dict:
        try:
            requested_operation = _request_dict(request).get("operation")
        except Exception:
            requested_operation = "UNKNOWN"
        if not self._execution_lock.acquire(timeout=self.timeout_seconds):
            return {"status": "BLOCKED", "operation": requested_operation if requested_operation in _RESULT_FIELDS else "UNKNOWN",
                    "code": "OPERATION_QUEUE_TIMEOUT", "retryable": False}
        try:
            return self._execute_locked(request, permitted)
        finally:
            self._execution_lock.release()

    def _execute_locked(self, request, permitted: tuple[str, ...]) -> dict:
        try:
            value = _request_dict(request)
            operation = value.pop("operation", None)
            if operation not in permitted:
                return {"status": "BLOCKED", "operation": operation if operation in _RESULT_FIELDS else "UNKNOWN",
                        "code": "OPERATION_NOT_PERMITTED", "retryable": False}
            internal_steps = [{"id": "step-001", "operation": operation, "params": value}]
            if operation == "CAPTURE_REPO_STATE":
                internal_steps.append({"id": "step-002", "operation": "GIT_DIFF_CHECK", "params": {}})
            validation = validate_job({
                "schema": "deputy.worker.job.v1",
                "repo": {"binding": "deputy-authoritative-v1"},
                "steps": internal_steps,
            })
            if not validation["valid"]:
                return {"status": "BLOCKED", "operation": operation, "code": "REQUEST_INVALID", "retryable": False}
            start_deadline = time.monotonic() + self.timeout_seconds
            while True:
                started = self.engine.start(validation["normalized_job"])
                if (started.get("status") == "REJECTED"
                        and started.get("reason") in {"ACTIVE_RUN_EXISTS", "ACTIVE_RUN_RACE"}):
                    if time.monotonic() + POLL_INTERVAL_SECONDS >= start_deadline:
                        return {"status": "BLOCKED", "operation": operation,
                                "code": "OPERATION_QUEUE_TIMEOUT", "retryable": False}
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue
                break
            if started.get("status") != "ACCEPTED":
                raw_status = started.get("status")
                code = started.get("reason")
                if code not in _ALLOWED_CODES:
                    code = "OPERATION_NOT_ACCEPTED"
                return {"status": "BLOCKED", "operation": operation, "code": code,
                        "retryable": raw_status == "BLOCKED"}
            run_id = started["run_id"]
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                result = self.engine.result(run_id)
                if result.get("status") == "READY":
                    return project_outcome(operation, result)
                time.sleep(POLL_INTERVAL_SECONDS)
            self.engine.cancel(run_id)
            result = self.engine.result(run_id)
            if result.get("status") == "READY":
                projected = project_outcome(operation, result)
                if projected["status"] in {"CANCELLED", "BLOCKED", "UNPROVEN"}:
                    projected.update({"status": "BLOCKED", "code": "OPERATION_TIMEOUT", "retryable": True})
                return projected
            return {"status": "BLOCKED", "operation": operation, "code": "OPERATION_TIMEOUT", "retryable": True}
        except Exception:
            return {"status": "UNPROVEN", "operation": "UNKNOWN", "code": "OPERATION_OUTCOME_UNAVAILABLE", "retryable": False}


def worker_control_plane_enabled() -> bool:
    return os.environ.get("DEPUTYWORKERS_ENABLE_CONTROL_PLANE") == "1"
