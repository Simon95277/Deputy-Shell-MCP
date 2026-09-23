from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


SCHEMA = "deputy.agents.source-policy.v1"
POLICY_VERSION = "DA-PRIVACY-1-positive-policy-v1"
POLICY_ENV = "DEPUTYAGENTS_SOURCE_POLICY_JSON"
MAX_POLICY_JSON_BYTES = 64 * 1024
HARD_MAX_FILE_BYTES = 10 * 1024 * 1024
HARD_MAX_FILE_COUNT = 5000
HARD_MAX_TOTAL_BYTES = 50 * 1024 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class SourcePolicy:
    schema: str
    policy_id: str
    allowed_prefixes: tuple[str, ...]
    allowed_root_files: tuple[str, ...]
    excluded_prefixes: tuple[str, ...]
    approved_untracked: tuple[str, ...]
    max_file_bytes: int
    max_file_count: int
    max_total_bytes: int

    def allows(self, relative_path: str) -> bool:
        path = normalize_relative_path(relative_path)
        return (path in self.allowed_root_files or
                (path.startswith(self.allowed_prefixes) and
                 not path.startswith(self.excluded_prefixes)))


def normalize_relative_path(value: object, *, prefix: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("SOURCE_POLICY_INVALID_PATH")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("SOURCE_POLICY_INVALID_PATH")
    if value.startswith("/") or _DRIVE.match(value) or "\x00" in value:
        raise ValueError("SOURCE_POLICY_INVALID_PATH")
    check = value[:-1] if prefix and value.endswith("/") else value
    pieces = check.split("/")
    if any(piece in {"", ".", ".."} for piece in pieces):
        raise ValueError("SOURCE_POLICY_INVALID_PATH")
    if prefix and not value.endswith("/"):
        raise ValueError("SOURCE_POLICY_INVALID_PATH")
    return value


def _path_list(value: object, key: str, *, prefix: bool = False, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > 256:
        raise ValueError("SOURCE_POLICY_INVALID_" + key.upper())
    result = tuple(normalize_relative_path(item, prefix=prefix) for item in value)
    if len(set(result)) != len(result):
        raise ValueError("SOURCE_POLICY_DUPLICATE_PATH")
    return result


def parse_policy(value: object) -> SourcePolicy:
    if not isinstance(value, dict):
        raise ValueError("SOURCE_POLICY_INVALID")
    expected = {"schema", "policy_id", "allowed_prefixes", "allowed_root_files",
                "excluded_prefixes", "approved_untracked", "limits"}
    if set(value) != expected:
        raise ValueError("SOURCE_POLICY_FIELDS_INVALID")
    if value.get("schema") != SCHEMA:
        raise ValueError("SOURCE_POLICY_SCHEMA_INVALID")
    policy_id = value.get("policy_id")
    if not isinstance(policy_id, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,63}", policy_id):
        raise ValueError("SOURCE_POLICY_ID_INVALID")
    allowed_prefixes = _path_list(value.get("allowed_prefixes"), "allowed_prefixes", prefix=True, allow_empty=True)
    roots = _path_list(value.get("allowed_root_files"), "allowed_root_files", allow_empty=True)
    if any("/" in path for path in roots):
        raise ValueError("SOURCE_POLICY_ROOT_FILE_INVALID")
    excluded = value.get("excluded_prefixes")
    approved = value.get("approved_untracked")
    if not isinstance(excluded, list) or len(excluded) > 256:
        raise ValueError("SOURCE_POLICY_INVALID_EXCLUDED_PREFIXES")
    if not isinstance(approved, list) or len(approved) > 256:
        raise ValueError("SOURCE_POLICY_INVALID_APPROVED_UNTRACKED")
    excluded_prefixes = tuple(normalize_relative_path(p, prefix=True) for p in excluded)
    approved_untracked = tuple(normalize_relative_path(p) for p in approved)
    if len(set(excluded_prefixes)) != len(excluded_prefixes) or len(set(approved_untracked)) != len(approved_untracked):
        raise ValueError("SOURCE_POLICY_DUPLICATE_PATH")
    if not allowed_prefixes and not roots:
        raise ValueError("SOURCE_POLICY_EMPTY_OR_BROAD")
    if any(not (path in roots or (path.startswith(allowed_prefixes) and not path.startswith(excluded_prefixes)))
           for path in approved_untracked):
        raise ValueError("SOURCE_POLICY_APPROVED_PATH_OUTSIDE_ALLOWLIST")
    limits = value.get("limits")
    if not isinstance(limits, dict) or set(limits) != {"max_file_bytes", "max_file_count", "max_total_bytes"}:
        raise ValueError("SOURCE_POLICY_LIMITS_INVALID")
    parsed_limits = []
    for key, ceiling in (("max_file_bytes", HARD_MAX_FILE_BYTES), ("max_file_count", HARD_MAX_FILE_COUNT),
                         ("max_total_bytes", HARD_MAX_TOTAL_BYTES)):
        number = limits.get(key)
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= ceiling:
            raise ValueError("SOURCE_POLICY_LIMIT_INVALID")
        parsed_limits.append(number)
    return SourcePolicy(SCHEMA, policy_id, allowed_prefixes, roots, excluded_prefixes,
                        approved_untracked, *parsed_limits)


DEFAULT_DEPUTY_SHELL_POLICY = {
    "schema": SCHEMA,
    "policy_id": "DEPUTY_SHELL_DEFAULT_V1",
    "allowed_prefixes": ["app/src/", "backend/", "tools/"],
    "allowed_root_files": ["build.gradle", "build.gradle.kts", "settings.gradle",
                           "settings.gradle.kts", "gradle.properties", "gradlew", "gradlew.bat"],
    "excluded_prefixes": ["tools/linux-runtime/"],
    "approved_untracked": [
        "app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bContractWideCandidateProbeHarnessTest.kt",
        "app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bPostInstallPreservationTest.kt",
        "app/src/executionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidation.kt",
        "app/src/main/java/com/deputyshell/app/runtime/pack/P3bCanonicalGenerationTreeFingerprintV1.kt",
        "app/src/main/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1.kt",
        "app/src/test/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1Test.kt",
        "app/src/testExecutionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidationTest.kt",
        "tools/android/verify_androidtest_dex_contents.py",
        "tools/android/verify_validation_target_dex_contents.py",
    ],
    "limits": {"max_file_bytes": HARD_MAX_FILE_BYTES, "max_file_count": HARD_MAX_FILE_COUNT,
               "max_total_bytes": HARD_MAX_TOTAL_BYTES},
}


def configured_policy() -> SourcePolicy:
    raw = os.environ.get(POLICY_ENV)
    if not raw:
        return parse_policy(DEFAULT_DEPUTY_SHELL_POLICY)
    if len(raw.encode("utf-8")) > MAX_POLICY_JSON_BYTES:
        raise ValueError("SOURCE_POLICY_JSON_TOO_LARGE")
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("SOURCE_POLICY_JSON_INVALID") from exc
    return parse_policy(decoded)
