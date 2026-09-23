from __future__ import annotations

import re
import os
from typing import Any


PUBLIC_RESULT_SANITIZER_VERSION = "DA-PUBLIC-RESULT-SANITIZER-1"
_CHILD_ENV_KEYS = {
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
    "HOME", "USERPROFILE", "JAVA_HOME", "GRADLE_USER_HOME",
}
_WORKER_CONFIG_KEYS = {
    "DEPUTYWORKERS_RUNTIME_ROOT", "DEPUTYWORKERS_DEPUTY_SHELL_ROOT",
    "DEPUTYWORKERS_ANDROID_SDK_ROOT", "DEPUTYWORKERS_EVIDENCE_ROOT",
    "DEPUTYWORKERS_PYTHON_EXE", "DEPUTYWORKERS_ADB_EXE",
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)\b[A-Z]:[\\/]")
_CREDENTIAL = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|"
    r"\bAKIA[0-9A-Z]{16}\b|(?i:\bBearer\s+[A-Za-z0-9._~+/=-]{24,})|"
    r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b|\bxox[baprs]-[A-Za-z0-9-]{20,}\b|"
    r"\bsk-(?:proj-)?[A-Za-z0-9]{24,}\b|\bsk-ant-api[0-9]{2}-[A-Za-z0-9_-]{24,}\b|"
    r"\bglpat-[A-Za-z0-9_-]{20,}\b|\bAIza[0-9A-Za-z_-]{35}\b"
)
_POSIX_HOST_PATH = re.compile(
    r"(?<![A-Za-z0-9_])/(?:Users|home|tmp|var|opt|root|workspace|private|Applications|Volumes|mnt|usr|etc|android|data|sdcard)/"
)
_OMIT_KEYS = {
    "repo_root", "repo_root_verified", "runtime_root", "evidence_root",
    "contract_path", "job_directory", "manifest_path", "usage_file",
    "adb_path", "android_sdk", "sdk_path", "python_executable",
    "executable", "command", "args", "argv", "environment", "env",
    "pid", "stdout_log", "stderr_log", "stdout_path", "stderr_path",
    "origin", "local_path", "pulled_path", "script", "bootstrap_error_path",
    "stdout", "stderr", "stdout_tail", "stderr_tail", "raw_output", "parsed_result",
    "username", "host_username", "machine_name", "hostname",
}


def _redact_text(value: str) -> str:
    # A path may contain spaces, so partial regex replacement can disclose its
    # suffix. These values are diagnostic prose, not path-bearing API fields;
    # replace the whole string whenever a host path is present.
    if _WINDOWS_ABSOLUTE_PATH.search(value) or _POSIX_HOST_PATH.search(value):
        return "[HOST_PATH_REDACTED]"
    return _CREDENTIAL.sub("[REDACTED_CREDENTIAL]", value)


def public_result(value: Any) -> Any:
    """Remove host execution identity from MCP results; local run evidence stays intact."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _OMIT_KEYS:
                continue
            if normalized == "error":
                # Stable semantic codes are retained; exception text is not.
                if isinstance(item, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", item):
                    cleaned[key] = item
                elif normalized == "error":
                    cleaned["error"] = "OPERATION_ERROR"
                continue
            cleaned[key] = public_result(item)
        return cleaned
    if isinstance(value, list):
        return [public_result(item) for item in value]
    if isinstance(value, tuple):
        return [public_result(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def child_environment(*, include_worker_config: bool = False, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a narrow child env; credentials, Git overrides, and SSH/cloud vars are omitted."""
    allowed = set(_CHILD_ENV_KEYS)
    if include_worker_config:
        allowed.update(_WORKER_CONFIG_KEYS)
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    if extra:
        result.update(extra)
    return result
