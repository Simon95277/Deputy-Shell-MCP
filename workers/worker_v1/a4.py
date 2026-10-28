from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import re
import secrets
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

import config
from . import host_ops
from .capabilities import (
    APPROVED_ARTIFACTS,
    APPROVED_VERIFIERS,
    REGISTRY_PATH,
    load_registry,
    validate_job,
)
from .service import ACT_OPERATIONS, OBSERVE_OPERATIONS
from .storage import atomic_json, read_json


A4_PROTOCOL_VERSION = "DA-A4-BETA-2"
MAX_REQUEST_CHARS = 8000
MAX_STAGES = 8
MAX_RECORDS = 2048
PREPARE_TTL_SECONDS = 300
INTENT_TTL_SECONDS = 600
_ID_RE = re.compile(r"^(?:prep|choice|intent)_[A-Za-z0-9_-]{40,64}$")
_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")

_MAPPING = {
    "DEVICE_INVENTORY": {"operation": "ADB_LIST_DEVICES", "profiles": {"android"}, "effect": "OBSERVE_DEVICE"},
    "ANDROID_PROPERTY": {"operation": "ADB_QUERY_PROPERTY", "profiles": {"android"}, "effect": "OBSERVE_DEVICE"},
    "ANDROID_LOG_CAPTURE": {"operation": "ADB_LOGCAT_CAPTURE", "profiles": {"android", "multi_repo"}, "effect": "OBSERVE_DEVICE"},
    "ANDROID_INSTALL": {"operation": "ADB_INSTALL", "profiles": {"android", "multi_repo"}, "effect": "DEVICE_MUTATION_INSTALL"},
    "ANDROID_FORCE_STOP": {"operation": "ADB_FORCE_STOP_DEPUTY", "profiles": {"android"}, "effect": "DEVICE_MUTATION"},
    "ANDROID_CLEAR_DATA": {"operation": "ADB_CLEAR_DEPUTY_DATA", "profiles": {"android"}, "effect": "DEVICE_DESTRUCTIVE"},
    "REGISTERED_VERIFIER": {"operation": "RUN_APPROVED_VERIFIER", "profiles": {"python_docker", "deputy_mcp_package"}, "effect": "LOCAL_EXECUTION"},
    "REPO_STATE": {"operation": "CAPTURE_REPO_STATE", "profiles": {"multi_repo"}, "effect": "OBSERVE"},
    "GIT_DIFF_CHECK": {"operation": "GIT_DIFF_CHECK", "profiles": {"multi_repo"}, "effect": "OBSERVE"},
}

_PATTERNS = {
    "DEVICE_INVENTORY": re.compile(r"\b(?:list|show|enumerate|check|query)\b.{0,60}\b(?:android\s+)?devices?\b|\b(?:android\s+)?device inventory\b", re.I),
    "ANDROID_PROPERTY": re.compile(r"\b(?:android\s+)?(?:device\s+)?property\b|\bro\.[a-z0-9_.]+\b|\b(?:sdk version|cpu abi|android api level)\b", re.I),
    "ANDROID_LOG_CAPTURE": re.compile(r"\b(?:logcat|android logs?|device logs?)\b", re.I),
    "ANDROID_INSTALL": re.compile(
        r"\b(?:install|reinstall)\b(?:(?!\b(?:and|then)\b|[;,\n]).){0,100}"
        r"\b(?:apk|artifact|application|app|build)\b|\b(?:debug|release)\s+apk\b",
        re.I,
    ),
    "ANDROID_FORCE_STOP": re.compile(r"\bforce[ -]stop\b|\bstop\s+(?:the\s+)?(?:deputy|app|application)\b", re.I),
    "ANDROID_CLEAR_DATA": re.compile(r"\bclear\b.{0,40}\b(?:data|storage)\b|\b(?:clear|wipe)\s+(?:the\s+)?(?:deputy|app|application)\s+data\b", re.I),
    "REGISTERED_VERIFIER": re.compile(r"\b(?:VERIFY_RUNTIME_INTEGRITY_MANIFEST|runtime integrity manifest verifier|registered verifier)\b", re.I),
    "REPO_STATE": re.compile(r"\b(?:repository|repo)\s+(?:state|status)\b|\bgit\s+status\b|\bworking tree state\b", re.I),
    "GIT_DIFF_CHECK": re.compile(r"\bgit\s+diff\s+--check\b|\bdiff[ -]check\b|\bwhitespace check\b", re.I),
}

_UNSUPPORTED = re.compile(
    r"\b(?:deploy|deployment|migration|migrate|docker|compose|pytest|gradle|npm|wrangler|"
    r"build\s+(?:a\s+)?(?:wheel|sdist|package|apk)|run\s+(?:the\s+)?tests?|test\s+suite|"
    r"uninstall|arbitrary\s+(?:command|process|path)|shell\s+command|adb\s+shell|"
    r"powershell|cmd\.exe|start\s+(?:the\s+)?(?:app|application|activity)|launch\s+(?:the\s+)?(?:app|application|activity)|"
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"prompt\s+injection|tool\s+output\s+says)\b|\b(?:ADB_[A-Z0-9_]+|CAPTURE_REPO_STATE|RUN_APPROVED_VERIFIER)\b",
    re.I,
)
_NEGATION = re.compile(r"\b(?:do not|don't|dont|never|avoid|not)\b", re.I)
_STAGE_WORD_CONNECTOR = re.compile(r"\b(?:and|or|then)\b", re.I)
_STAGE_PUNCTUATION = re.compile(r"[;,\n]")
_ARTIFACT_MENTION = re.compile(
    r"\b(DEPUTY_DEBUG_APK|DEPUTY_RELEASE_APK|debug\s+apk|release\s+apk)\b", re.I
)


def _artifact_selectors(text: str) -> tuple[set[str], set[str]]:
    """Return positive and negated registered artifact mentions conservatively."""
    positive: set[str] = set()
    negative: set[str] = set()
    for match in _ARTIFACT_MENTION.finditer(text):
        token = match.group(1).upper().replace(" ", "_")
        artifact = token if token.startswith("DEPUTY_") else f"DEPUTY_{token}"
        prefix = text[:match.start()]
        boundary = max(prefix.rfind(mark) for mark in (",", ";", ".", "\n"))
        for conjunction in re.finditer(r"\b(?:and|but|then)\b", prefix, re.I):
            boundary = max(boundary, conjunction.end() - 1)
        clause_prefix = prefix[boundary + 1:]
        # “not only X but also Y” is additive, not a negation. Treat both
        # selectors as positive so the caller must clarify rather than guess.
        negated = bool(_NEGATION.search(clause_prefix)) and not re.search(
            r"\bnot\s+only\b", clause_prefix, re.I
        )
        (negative if negated else positive).add(artifact)
    return positive, negative


def _stage_connector(text: str) -> re.Match[str] | None:
    # Prefer the first explicit connector after an operation. Punctuation
    # after a next-stage target (for example, "then on DEVICE, clear data")
    # is not the boundary between stages.
    words = list(_STAGE_WORD_CONNECTOR.finditer(text))
    if words:
        return words[0]
    punctuation = list(_STAGE_PUNCTUATION.finditer(text))
    return punctuation[0] if punctuation else None


class A4Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: Annotated[str, StringConstraints(min_length=1, max_length=MAX_REQUEST_CHARS)] = Field(
        description="Natural-language request to resolve against the server-owned A4 profile; preparation never executes."
    )


class A4ChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prepare_id: Annotated[str, StringConstraints(min_length=48, max_length=48, pattern=r"^prep_[A-Za-z0-9_-]{43}$")]
    choice_id: Annotated[str, StringConstraints(min_length=50, max_length=50, pattern=r"^choice_[A-Za-z0-9_-]{43}$")]
    choice_review: Annotated[str, StringConstraints(min_length=1, max_length=1800)]


class A4IntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: Annotated[str, StringConstraints(min_length=50, max_length=50, pattern=r"^intent_[A-Za-z0-9_-]{43}$")]


class A4ActRequest(A4IntentRequest):
    approval_review: Annotated[str, StringConstraints(min_length=1, max_length=1800)]


class A4DeviceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_alias: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    state: Annotated[str, StringConstraints(min_length=1, max_length=32)]


class A4IntentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantics: list[Literal[
        "DEVICE_INVENTORY", "ANDROID_PROPERTY", "ANDROID_LOG_CAPTURE", "ANDROID_INSTALL",
        "ANDROID_FORCE_STOP", "ANDROID_CLEAR_DATA", "REGISTERED_VERIFIER", "REPO_STATE", "GIT_DIFF_CHECK",
    ]] = Field(min_length=1, max_length=MAX_STAGES)
    effect: Literal["OBSERVE", "ACT"]
    stage_count: Annotated[int, Field(ge=1, le=MAX_STAGES)]


class A4StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic: Literal[
        "DEVICE_INVENTORY", "ANDROID_PROPERTY", "ANDROID_LOG_CAPTURE", "ANDROID_INSTALL",
        "ANDROID_FORCE_STOP", "ANDROID_CLEAR_DATA", "REGISTERED_VERIFIER", "REPO_STATE", "GIT_DIFF_CHECK",
    ]
    status: Literal["PASS", "FAIL", "BLOCKED", "UNPROVEN", "CONTRADICTION", "CANCELLED"]
    code: Annotated[str, StringConstraints(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")] | None = None
    devices: list[A4DeviceResult] | None = Field(default=None, max_length=64)
    registered_device_count: Annotated[int, Field(ge=0, le=64)] | None = None
    device_alias: Annotated[str, StringConstraints(min_length=1, max_length=32)] | None = None
    property: Literal["ro.product.cpu.abi", "ro.build.version.sdk"] | None = None
    value: Annotated[str, StringConstraints(max_length=1024)] | None = None
    line_count: Annotated[int, Field(ge=0, le=2000)] | None = None
    artifact: Literal["DEPUTY_DEBUG_APK", "DEPUTY_RELEASE_APK"] | None = None
    installed: bool | None = None
    stopped: bool | None = None
    cleared: bool | None = None
    passed: bool | None = None
    exit_code: Annotated[int, Field(ge=-1_000_000, le=1_000_000)] | None = None
    head: Annotated[str, StringConstraints(min_length=40, max_length=64, pattern=r"^[0-9a-fA-F]+$")] | None = None
    branch: Annotated[str, StringConstraints(max_length=256)] | None = None
    dirty: bool | None = None
    diff_check_pass: bool | None = None


class A4ChoiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice_id: Annotated[str, StringConstraints(min_length=50, max_length=50, pattern=r"^choice_[A-Za-z0-9_-]{43}$")]
    label: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    choice_review: Annotated[str, StringConstraints(min_length=1, max_length=1800)]


class A4PrepareResponse(BaseModel):
    """Closed structured response for prepare and choose."""
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["DA-A4-BETA-2"]
    status: Literal[
        "CLEAR", "CHOICE_REQUIRED", "ARGUMENT_REQUIRED", "TARGET_NOT_REGISTERED", "ARGUMENT_INVALID",
        "UNSUPPORTED", "MULTI_STEP_REQUIRED", "BLOCKED",
    ]
    code: Annotated[str, StringConstraints(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")] | None = None
    intent_id: Annotated[str, StringConstraints(min_length=50, max_length=50, pattern=r"^intent_[A-Za-z0-9_-]{43}$")] | None = None
    prepare_id: Annotated[str, StringConstraints(min_length=48, max_length=48, pattern=r"^prep_[A-Za-z0-9_-]{43}$")] | None = None
    choices: list[A4ChoiceResult] | None = Field(default=None, max_length=8)
    intent: A4IntentSummary | None = None
    approval_review: Annotated[str, StringConstraints(min_length=1, max_length=1800)] | None = None
    expires_in_seconds: Annotated[int, Field(ge=0, le=600)] | None = None
    required_arguments: list[Literal["device_alias", "property", "line_limit", "registered_artifact", "verifier_id", "narrower_choice"]] | None = Field(default=None, max_length=8)


class A4DispatchResponse(BaseModel):
    """Closed structured terminal response for observe and act."""
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["DA-A4-BETA-2"]
    status: Literal["PASS", "FAIL", "BLOCKED", "UNPROVEN", "CONTRADICTION", "CANCELLED", "OUTCOME_UNCERTAIN"]
    code: Annotated[str, StringConstraints(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")] | None = None
    stages: list[A4StageResult] | None = Field(default=None, max_length=MAX_STAGES)
    completed_stage_count: Annotated[int, Field(ge=0, le=MAX_STAGES)] | None = None
    partial: bool | None = None


class A4Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _now() -> float:
    return time.time()


def _identifier(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _validate_id(value: object, prefix: str) -> str | None:
    if isinstance(value, str) and _ID_RE.fullmatch(value) and value.startswith(prefix + "_"):
        return value
    return None


def _public(status: str, **values: Any) -> dict[str, Any]:
    from .privacy import public_result
    return public_result({"protocol": A4_PROTOCOL_VERSION, "status": status, **values})


class A4IntentService:
    """Intent-bound adapter over the existing deterministic WorkerService."""

    def __init__(
        self,
        worker_service,
        profile: str,
        *,
        runtime_root: Path | None = None,
        repo_root: Path | None = None,
        registry_path: Path | None = None,
        bindings_path: Path | None = None,
        profile_provider=None,
    ):
        if profile not in {"android", "multi_repo", "python_docker", "deputy_mcp_package"}:
            raise A4Error("A4_PROFILE_INVALID")
        self.worker_service = worker_service
        self.profile = profile
        self.runtime_root = Path(runtime_root or config.RUNTIME_ROOT)
        self.repo_root = Path(repo_root or host_ops.REPO_ROOT).resolve()
        self.registry_path = Path(registry_path or REGISTRY_PATH)
        self.bindings_path = Path(bindings_path or config.A4_DEVICE_BINDINGS_PATH)
        self.profile_provider = profile_provider or config.a4_profile
        self._validate_mapping()
        self.state_root = self.runtime_root / "a4-intents"
        self.records = self.state_root / "records"
        self.claims = self.state_root / "claims"
        self.choice_claims = self.state_root / "choice-claims"
        self.key_path = self.state_root / "integrity.key"
        self.epoch_path = self.state_root / "epoch.json"
        self._lock = threading.RLock()
        self._pending_choice_prepare_id: str | None = None
        self._instance_fd: int | None = None
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.records.mkdir(parents=True, exist_ok=True)
        self.claims.mkdir(parents=True, exist_ok=True)
        self.choice_claims.mkdir(parents=True, exist_ok=True)
        self._acquire_instance_lock()
        try:
            self._key = self._load_or_create_key()
            self._recover_prior_epoch()
            self.epoch = secrets.token_urlsafe(24)
            atomic_json(self.epoch_path, {"epoch": self.epoch, "started_at": _now()})
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        fd, self._instance_fd = self._instance_fd, None
        if fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)

    def _acquire_instance_lock(self) -> None:
        path = self.state_root / "instance.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            os.close(fd)
            raise A4Error("A4_INSTANCE_ALREADY_RUNNING")
        self._instance_fd = fd

    def _load_or_create_key(self) -> bytes:
        if self.key_path.is_symlink():
            raise A4Error("A4_INTEGRITY_KEY_INVALID")
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise A4Error("A4_INTEGRITY_KEY_INVALID")
            return key
        existing = any(self.records.glob("*.json")) or any(self.claims.glob("*.claim"))
        if existing:
            raise A4Error("A4_INTEGRITY_KEY_MISSING")
        key = secrets.token_bytes(32)
        try:
            fd = os.open(self.key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise A4Error("A4_INTEGRITY_KEY_INVALID")
        return key

    def _ensure_capacity(self) -> None:
        with self._lock:
            records = list(self.records.glob("*.json"))
            if len(records) < MAX_RECORDS:
                return

            now = _now()
            reclaimable = []
            for path in records:
                candidate = self._expired_unclaimed_record(path, now)
                if candidate is not None:
                    reclaimable.append((candidate[0], path, candidate[1]))

            remaining = len(records)
            for _, path, kind in sorted(reclaimable, key=lambda row: row[0]):
                try:
                    path.unlink()
                except OSError:
                    continue
                remaining -= 1
                if kind == "prepare":
                    claim = self.choice_claims / f"{path.stem}.claim"
                    try:
                        claim.unlink(missing_ok=True)
                    except OSError:
                        pass
                if remaining < MAX_RECORDS:
                    return

            raise A4Error("A4_STORAGE_LIMIT")

    def _expired_unclaimed_record(self, path: Path, now: float) -> tuple[int | float, str] | None:
        """Identify only authentic expired tickets that have never dispatched."""
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                return None
            envelope = read_json(path)
            if not isinstance(envelope, dict):
                return None
            record = envelope.get("record")
            supplied = envelope.get("mac")
            if not isinstance(record, dict) or not isinstance(supplied, str):
                return None
            digest = record.get("record_digest")
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or path.stem != digest):
                return None
            expected = hmac.new(self._key, _canonical(record), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                return None
            expires_at = record.get("expires_at")
            if (isinstance(expires_at, bool) or not isinstance(expires_at, (int, float))
                    or not expires_at <= now):
                return None

            kind = record.get("kind")
            state = record.get("state")
            if kind == "intent":
                if state not in {"PREPARED", "EXPIRED", "REVOKED"}:
                    return None
                if (self.claims / f"{digest}.claim").exists():
                    return None
            elif kind == "prepare":
                if state not in {"CHOICE_PENDING", "CHOSEN", "EXPIRED", "REVOKED"}:
                    return None
                choice_claim = self.choice_claims / f"{digest}.claim"
                if state == "CHOICE_PENDING" and choice_claim.exists():
                    return None
            else:
                return None
            return expires_at, kind
        except (OSError, ValueError, TypeError, KeyError):
            # Corrupt or concurrently changing evidence is never garbage-collected.
            return None

    def _validate_mapping(self) -> None:
        try:
            registry = load_registry(self.registry_path)
        except Exception:
            raise A4Error("CAPABILITY_REGISTRY_INVALID") from None
        if len(registry) != 22:
            raise A4Error("CAPABILITY_REGISTRY_INVALID")
        observe = set(OBSERVE_OPERATIONS)
        act = set(ACT_OPERATIONS)
        if observe & act:
            raise A4Error("CAPABILITY_REGISTRY_INVALID")
        profiles = {"android", "multi_repo", "python_docker", "deputy_mcp_package"}
        mutating_semantics = {"ANDROID_INSTALL", "ANDROID_FORCE_STOP", "ANDROID_CLEAR_DATA"}
        for semantic, spec in _MAPPING.items():
            operation = spec["operation"]
            if operation not in registry or not registry[operation].get("enabled"):
                raise A4Error("CAPABILITY_REGISTRY_INVALID")
            is_observe = operation in observe
            if (operation not in (observe | act)
                    or is_observe != spec["effect"].startswith("OBSERVE")
                    or not spec["profiles"] or not set(spec["profiles"]) <= profiles
                    or bool(registry[operation].get("device_mutation")) != (semantic in mutating_semantics)):
                raise A4Error("CAPABILITY_REGISTRY_INVALID")

    def _record_path(self, token: str) -> Path:
        return self.records / f"{_digest(token)}.json"

    def _seal(self, record: dict[str, Any]) -> dict[str, Any]:
        mac = hmac.new(self._key, _canonical(record), hashlib.sha256).hexdigest()
        return {"record": record, "mac": mac}

    def _write_record(self, token: str, record: dict[str, Any]) -> None:
        atomic_json(self._record_path(token), self._seal(record))

    def _read_record(self, token: str, expected_kind: str | None = None) -> dict[str, Any]:
        if not _ID_RE.fullmatch(token):
            raise A4Error("TICKET_INVALID")
        path = self._record_path(token)
        if not path.is_file():
            raise A4Error("TICKET_NOT_FOUND")
        try:
            envelope = read_json(path)
            record = envelope["record"]
            supplied = envelope["mac"]
            expected = hmac.new(self._key, _canonical(record), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                raise A4Error("A4_RECORD_TAMPERED")
            if record.get("record_digest") != _digest(token):
                raise A4Error("A4_RECORD_TAMPERED")
            if expected_kind and record.get("kind") != expected_kind:
                raise A4Error("TICKET_TYPE_INVALID")
            return record
        except A4Error:
            raise
        except Exception:
            raise A4Error("A4_RECORD_INVALID") from None

    def _recover_prior_epoch(self) -> None:
        if not self.epoch_path.exists():
            if any(self.records.glob("*.json")):
                raise A4Error("A4_EPOCH_STATE_MISSING")
            return
        try:
            previous = read_json(self.epoch_path).get("epoch")
        except Exception:
            raise A4Error("A4_EPOCH_STATE_INVALID") from None
        if not isinstance(previous, str) or not previous:
            raise A4Error("A4_EPOCH_STATE_INVALID")
        for path in sorted(self.records.glob("*.json")):
            try:
                envelope = read_json(path)
                record = envelope["record"]
                supplied = envelope["mac"]
                expected = hmac.new(self._key, _canonical(record), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(supplied, expected):
                    raise A4Error("A4_RECORD_TAMPERED")
                token_digest = record.get("record_digest")
                if path.stem != token_digest:
                    raise A4Error("A4_RECORD_TAMPERED")
                if record.get("runtime_epoch") != previous:
                    continue
                if record.get("kind") == "intent":
                    claim_exists = (self.claims / f"{token_digest}.claim").exists()
                    state = record.get("state")
                    if state == "DISPATCHING" or (claim_exists and state == "PREPARED"):
                        record["state"] = "OUTCOME_UNCERTAIN"
                        record["receipt"] = {
                            "status": "OUTCOME_UNCERTAIN",
                            "reason": "SERVER_RESTART_DURING_DISPATCH",
                            "completed_stage_count": len(record.get("completed", [])),
                        }
                    elif record.get("state") == "PREPARED":
                        record["state"] = "REVOKED"
                        record["receipt"] = {"status": "REVOKED", "reason": "SERVER_RESTART"}
                elif record.get("kind") == "prepare" and record.get("state") == "CHOICE_PENDING":
                    record["state"] = "REVOKED"
                    record["receipt"] = {"status": "REVOKED", "reason": "SERVER_RESTART"}
                atomic_json(path, self._seal(record))
            except A4Error:
                raise
            except Exception:
                raise A4Error("A4_RECORD_INVALID") from None

    def _device_bindings(self) -> tuple[dict[str, str], str]:
        path = self.bindings_path
        try:
            file_stat = path.lstat()
        except FileNotFoundError:
            return {}, "ABSENT"
        except OSError:
            raise A4Error("DEVICE_BINDINGS_UNAVAILABLE") from None
        is_reparse = bool(getattr(file_stat, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if not path.is_file() or path.is_symlink() or is_reparse:
            raise A4Error("DEVICE_BINDINGS_UNAVAILABLE")
        try:
            raw = path.read_bytes()
            if len(raw) > 16384:
                raise A4Error("DEVICE_BINDINGS_INVALID")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict) or set(value) != {"schema", "devices"}:
                raise A4Error("DEVICE_BINDINGS_INVALID")
            if value.get("schema") != "deputy.workers.a4-device-bindings.v1" or not isinstance(value.get("devices"), list):
                raise A4Error("DEVICE_BINDINGS_INVALID")
            aliases: dict[str, str] = {}
            serials: set[str] = set()
            if len(value["devices"]) > 64:
                raise A4Error("DEVICE_BINDINGS_INVALID")
            for row in value["devices"]:
                if not isinstance(row, dict) or set(row) != {"alias", "serial"}:
                    raise A4Error("DEVICE_BINDINGS_INVALID")
                alias, serial = row["alias"], row["serial"]
                if not isinstance(alias, str) or not _ALIAS_RE.fullmatch(alias):
                    raise A4Error("DEVICE_BINDINGS_INVALID")
                if not isinstance(serial, str) or not 1 <= len(serial) <= 128 or any(ord(ch) < 33 or ord(ch) == 127 for ch in serial):
                    raise A4Error("DEVICE_BINDINGS_INVALID")
                key = alias.casefold()
                if key in aliases or serial in serials:
                    raise A4Error("DEVICE_BINDINGS_INVALID")
                aliases[key] = serial
                serials.add(serial)
            return aliases, _digest(raw)
        except A4Error:
            raise
        except Exception:
            raise A4Error("DEVICE_BINDINGS_INVALID") from None

    def _binding_digests(self, needs_devices: bool) -> dict[str, str]:
        try:
            registry_bytes = self.registry_path.read_bytes()
            registry = load_registry(self.registry_path)
        except Exception:
            raise A4Error("CAPABILITY_REGISTRY_INVALID") from None
        if len(registry) != 22:
            raise A4Error("CAPABILITY_REGISTRY_INVALID")
        values = {
            "registry_sha256": _digest(registry_bytes),
            "repo_binding_sha256": _digest(str(self.repo_root)),
            "mapping_sha256": _digest(_canonical({k: {**v, "profiles": sorted(v["profiles"])} for k, v in _MAPPING.items()})),
            "profile": self.profile,
        }
        if needs_devices:
            _, binding_digest = self._device_bindings()
            values["device_bindings_sha256"] = binding_digest
        return values

    @staticmethod
    def _needs_device_registry(stages: list[dict[str, Any]]) -> bool:
        return any(stage.get("device_alias") or stage.get("semantic") == "DEVICE_INVENTORY" for stage in stages)

    def _current_profile(self) -> str:
        try:
            value = self.profile_provider()
        except Exception:
            return ""
        return value or ""

    def _active_choice_pending(self) -> bool:
        token = self._pending_choice_prepare_id
        if token is None:
            return False
        record = self._read_record(token, "prepare")
        if record.get("state") != "CHOICE_PENDING" or record.get("runtime_epoch") != self.epoch:
            self._pending_choice_prepare_id = None
            return False
        if _now() > record.get("expires_at", 0):
            record["state"] = "EXPIRED"
            self._write_record(token, record)
            self._pending_choice_prepare_id = None
            return False
        return True

    def _check_bindings(self, record: dict[str, Any]) -> None:
        if self._current_profile() != self.profile:
            raise A4Error("INTENT_AUTHORITY_CHANGED")
        if record.get("profile") != self.profile:
            raise A4Error("INTENT_AUTHORITY_CHANGED")
        all_stages = list(record.get("stages", []))
        for choice in record.get("choices", []):
            all_stages.extend(choice.get("stages", []))
        needs_devices = self._needs_device_registry(all_stages)
        if self._binding_digests(needs_devices) != record.get("bindings"):
            raise A4Error("INTENT_AUTHORITY_CHANGED")
        if record.get("runtime_epoch") != self.epoch:
            raise A4Error("TICKET_REVOKED")

    @staticmethod
    def _alias_matches(text: str, aliases: dict[str, str]) -> list[str]:
        found = []
        for key in aliases:
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(key)}(?![A-Za-z0-9_-])", text, re.I):
                found.append(key)
        return found

    def _parse_stage(self, semantic: str, request: str, start: int, end: int, aliases: dict[str, str]) -> tuple[dict[str, Any] | None, str | None, list[str] | dict[str, Any]]:
        spec = _MAPPING[semantic]
        if self.profile not in spec["profiles"]:
            return None, "UNSUPPORTED", []
        local = request[max(0, start):min(len(request), end)]
        lower = local.casefold()
        params: dict[str, Any] = {}
        device_semantics = {"ANDROID_PROPERTY", "ANDROID_LOG_CAPTURE", "ANDROID_INSTALL", "ANDROID_FORCE_STOP", "ANDROID_CLEAR_DATA"}
        missing: list[str] = []
        device_alias = None
        device_alias_candidates: list[str] = []
        property_candidates: list[str] = []
        line_limit_candidates: list[int] = []
        artifact_candidates: list[str] = []
        if semantic in device_semantics:
            matches = self._alias_matches(local, aliases)
            if len(matches) == 1:
                device_alias = matches[0]
            elif len(matches) > 1:
                device_alias_candidates = matches
            else:
                unknown_target = re.search(r"\b(?:device|serial|target)\s*(?:id\s*)?(?:=|:|is\s+)?([A-Za-z0-9][A-Za-z0-9._:-]{2,})", local, re.I)
                unknown = unknown_target.group(1) if unknown_target else None
                if not unknown:
                    on_target = re.search(r"\bon\s+([A-Za-z][A-Za-z0-9_-]{2,})", local, re.I)
                    unknown = on_target.group(1) if on_target else None
                if unknown and unknown.casefold() not in aliases and unknown.casefold() not in {"the", "this", "that", "android", "device", "emulator"}:
                    return None, "TARGET_NOT_REGISTERED", []
                missing.append("device_alias")
        if semantic == "ANDROID_PROPERTY":
            props = []
            if re.search(r"\bro\.product\.cpu\.abi\b|\bcpu\s+abi\b", local, re.I):
                props.append("ro.product.cpu.abi")
            if re.search(r"\bro\.build\.version\.sdk\b|\bsdk\s+version\b|\bandroid\s+api\s+level\b", local, re.I):
                props.append("ro.build.version.sdk")
            explicit = re.findall(r"\bro\.[A-Za-z0-9_.]+\b", local)
            if explicit and any(prop not in {"ro.product.cpu.abi", "ro.build.version.sdk"} for prop in explicit):
                return None, "ARGUMENT_INVALID", []
            props = list(dict.fromkeys(props + [p for p in explicit if p not in props]))
            if len(props) > 1:
                property_candidates = props
            if not props:
                missing.append("property")
            else:
                params["property"] = props[0]
        elif semantic == "ANDROID_LOG_CAPTURE":
            alternatives = re.search(r"\b(\d+(?:\s+or\s+\d+)+)\s+(?:logcat\s+)?lines?\b", local, re.I)
            if alternatives:
                limit_values = re.findall(r"\d+", alternatives.group(1))
            else:
                limit_matches = list(re.finditer(
                    r"\b(?:last|limit(?:\s+of)?|up to|maximum(?: of)?)\s+(\d+)\s+(?:logcat\s+)?lines?\b|\b(\d+)\s+(?:logcat\s+)?lines?\b",
                    local, re.I,
                ))
                limit_values = [next(group for group in match.groups() if group is not None) for match in limit_matches]
            if not limit_values:
                missing.append("line_limit")
            else:
                limits = []
                for digits in limit_values:
                    if len(digits) > 4:
                        return None, "ARGUMENT_INVALID", []
                    limit = int(digits)
                    if not 1 <= limit <= 2000:
                        return None, "ARGUMENT_INVALID", []
                    if limit not in limits:
                        limits.append(limit)
                params["limit"] = limits[0]
                if len(limits) > 1:
                    line_limit_candidates = limits
        elif semantic == "ANDROID_INSTALL":
            positive, negative = _artifact_selectors(local)
            if positive & negative:
                return None, "ARGUMENT_INVALID", []
            if len(positive) > 1:
                if re.search(r"\b(?:or|either)\b", local, re.I):
                    artifact_candidates = sorted(positive)
                else:
                    return None, "ARGUMENT_REQUIRED", ["registered_artifact"]
            artifact = artifact_candidates[0] if artifact_candidates else next(iter(positive), None)
            if artifact is None:
                if re.search(r"\b(?:apk|artifact|build)\b", local, re.I):
                    missing.append("registered_artifact")
                else:
                    return None, "TARGET_NOT_REGISTERED", []
            elif artifact not in APPROVED_ARTIFACTS:
                return None, "TARGET_NOT_REGISTERED", []
            else:
                params["artifact_id"] = artifact
        elif semantic == "REGISTERED_VERIFIER":
            exact = [item for item in APPROVED_VERIFIERS if item.casefold() in local.casefold()]
            if exact:
                verifier = exact[0]
            elif "runtime integrity manifest verifier" in local.casefold() and "VERIFY_RUNTIME_INTEGRITY_MANIFEST" in APPROVED_VERIFIERS:
                verifier = "VERIFY_RUNTIME_INTEGRITY_MANIFEST"
            else:
                return None, "ARGUMENT_REQUIRED", ["verifier_id"]
            if not re.search(r"\b(?:run|execute|perform|check|verify)\b", local, re.I) and not verifier.casefold() in local.casefold():
                return None, "ARGUMENT_REQUIRED", ["verifier_id"]
            params["verifier_id"] = verifier
        if missing:
            return None, "ARGUMENT_REQUIRED", missing
        if device_alias is not None:
            params["_device_alias"] = device_alias.upper() if device_alias.upper() in {k.upper() for k in aliases} else device_alias
        operation = spec["operation"]
        translated = dict(params)
        alias = translated.pop("_device_alias", None)
        validation_alias = alias or (device_alias_candidates[0] if device_alias_candidates else None)
        if validation_alias is not None:
            translated["serial"] = aliases[validation_alias.casefold()]
        validation_params = {k: v for k, v in translated.items()}
        validation = validate_job({
            "schema": "deputy.worker.job.v1",
            "repo": {"binding": "deputy-authoritative-v1"},
            "steps": [{"id": "a4-validate", "operation": operation, "params": validation_params}],
        }, self.registry_path)
        if not validation.get("valid"):
            return None, "ARGUMENT_INVALID", []
        stored_params = dict(params)
        stage = {
            "semantic": semantic,
            "operation": operation,
            "effect": spec["effect"],
            "device_alias": stored_params.pop("_device_alias", None) or (device_alias_candidates[0] if device_alias_candidates else None),
            "params": stored_params,
        }
        choice_options = {"device_aliases": device_alias_candidates, "properties": property_candidates,
                          "artifacts": artifact_candidates}
        if device_alias_candidates or property_candidates or line_limit_candidates or artifact_candidates:
            choice_options["line_limits"] = line_limit_candidates
            return stage, "CHOICE_REQUIRED", choice_options
        return stage, None, []

    def _matches(self, request: str) -> list[tuple[int, int, str]]:
        matches = []
        for semantic, pattern in _PATTERNS.items():
            for match in pattern.finditer(request):
                before = request[max(0, match.start() - 48):match.start()]
                if _NEGATION.search(before):
                    continue
                matches.append((match.start(), match.end(), semantic))
        ordered = sorted(matches, key=lambda row: (row[0], row[1], row[2]))
        merged: list[tuple[int, int, str]] = []
        for start, end, semantic in ordered:
            if merged and merged[-1][2] == semantic:
                prior_start, prior_end, _ = merged[-1]
                between = request[prior_end:start] if start >= prior_end else ""
                if start <= prior_end or (len(between) <= 3 and not re.search(r"\b(?:and|or|then)\b|[;,]", between, re.I)):
                    merged[-1] = (prior_start, max(prior_end, end), semantic)
                    continue
            merged.append((start, end, semantic))
        return merged

    def _resolve(self, request: str, aliases: dict[str, str]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None, list[str] | dict[str, Any]]:
        if not isinstance(request, str) or not 1 <= len(request) <= MAX_REQUEST_CHARS or "\x00" in request:
            return "ARGUMENT_INVALID", [], None, []
        matches = self._matches(request)
        if _UNSUPPORTED.search(request):
            return "UNSUPPORTED", [], None, []
        try:
            operation_names = load_registry(self.registry_path)
        except Exception:
            raise A4Error("CAPABILITY_REGISTRY_INVALID") from None
        if any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", request, re.I)
               for name in operation_names):
            return "UNSUPPORTED", [], None, []
        if not matches:
            return "UNSUPPORTED", [], None, []
        semantics = [row[2] for row in matches]
        if any(self.profile not in _MAPPING[name]["profiles"] for name in semantics):
            return "UNSUPPORTED", [], None, []
        if len(matches) > MAX_STAGES:
            return "MULTI_STEP_REQUIRED", [], None, []
        semantic_or = any(
            re.search(r"\bor\b", request[matches[index][1]:matches[index + 1][0]], re.I)
            for index in range(len(matches) - 1)
            if matches[index][1] <= matches[index + 1][0]
        )
        if semantic_or and len(matches) > 2:
            return "UNSUPPORTED", [], None, []
        if semantic_or and re.search(r"\b(?:and|then)\b", request, re.I):
            return "UNSUPPORTED", [], None, []
        stage_bounds: list[tuple[int, int]] = []
        for index, (start, end, _) in enumerate(matches):
            if index == 0:
                stage_start = 0
            else:
                previous_end = matches[index - 1][1]
                if previous_end > start:
                    return "UNSUPPORTED", [], None, []
                previous_gap = request[previous_end:start]
                previous_connector = _stage_connector(previous_gap)
                if previous_connector is None:
                    return "UNSUPPORTED", [], None, []
                stage_start = previous_end + previous_connector.end()
            if index + 1 == len(matches):
                stage_end = len(request)
            else:
                next_start = matches[index + 1][0]
                if end > next_start:
                    return "UNSUPPORTED", [], None, []
                next_gap = request[end:next_start]
                next_connector = _stage_connector(next_gap)
                if next_connector is None:
                    return "UNSUPPORTED", [], None, []
                stage_end = end + next_connector.start()
            if stage_start > stage_end:
                return "UNSUPPORTED", [], None, []
            stage_bounds.append((stage_start, stage_end))
        stages: list[dict[str, Any] | None] = []
        choice_groups: list[tuple[int, list[dict[str, Any]]]] = []
        for index, (start, end, semantic) in enumerate(matches):
            stage_start, stage_end = stage_bounds[index]
            stage, state, candidates = self._parse_stage(semantic, request, stage_start, stage_end, aliases)
            if state:
                if state == "CHOICE_REQUIRED" and candidates:
                    options = candidates if isinstance(candidates, dict) else {}
                    property_options = options.get("properties", []) or ([stage.get("params", {}).get("property")] if stage and stage.get("params", {}).get("property") else [None])
                    alias_options = options.get("device_aliases", []) or ([stage.get("device_alias")] if stage and stage.get("device_alias") else [None])
                    line_limit_options = options.get("line_limits", []) or ([stage.get("params", {}).get("limit")] if stage and stage.get("params", {}).get("limit") else [None])
                    alternatives = []
                    if stage:
                        artifact_options = options.get("artifacts", []) or [stage.get("params", {}).get("artifact_id")]
                        for artifact, prop, alias, line_limit in itertools.product(artifact_options, property_options, alias_options, line_limit_options):
                            alternative = dict(stage)
                            alternative["params"] = dict(stage.get("params", {}))
                            if artifact:
                                alternative["params"]["artifact_id"] = artifact
                            if prop:
                                alternative["params"]["property"] = prop
                            if alias:
                                alternative["device_alias"] = alias
                            if line_limit:
                                alternative["params"]["limit"] = line_limit
                            selector = ", ".join(value for value in (
                                f"registered artifact {artifact}" if artifact else None,
                                prop, f"registered device {alias}" if alias else None,
                                f"last {line_limit} lines" if line_limit else None,
                            ) if value)
                            alternatives.append({"label": f"{semantic}: {selector}", "stage": alternative})
                    if alternatives:
                        stages.append(None)
                        choice_groups.append((index, alternatives))
                        continue
                if state == "ARGUMENT_REQUIRED":
                    return state, [], None, candidates
                if state == "ARGUMENT_INVALID":
                    return state, [], None, []
                if state == "TARGET_NOT_REGISTERED":
                    return state, [], None, []
                if state == "CHOICE_REQUIRED":
                    return "CHOICE_REQUIRED", [], None, []
                return state, [], None, []
            stages.append(stage)
        if semantic_or and len(matches) > 1:
            if choice_groups:
                return "ARGUMENT_REQUIRED", [], None, ["narrower_choice"]
            choices = [{"label": stage["semantic"], "stages": [stage]} for stage in stages if stage]
            if len(choices) > 1:
                if len(choices) > 8:
                    return "ARGUMENT_REQUIRED", [], None, ["narrower_choice"]
                return "CHOICE_REQUIRED", [], choices, []
        if choice_groups:
            combinations = 1
            for _, alternatives in choice_groups:
                combinations *= len(alternatives)
                if combinations > 8:
                    return "ARGUMENT_REQUIRED", [], None, ["narrower_choice"]
            choices = []
            for selected in itertools.product(*(alternatives for _, alternatives in choice_groups)):
                selected_by_index = {
                    choice_groups[position][0]: option
                    for position, option in enumerate(selected)
                }
                combined_stages = []
                labels = []
                for stage_index, stage_value in enumerate(stages):
                    if stage_index in selected_by_index:
                        option = selected_by_index[stage_index]
                        combined_stages.append(option["stage"])
                        labels.append(option["label"])
                    elif stage_value:
                        combined_stages.append(stage_value)
                choices.append({
                    "label": "; ".join(labels)[:160],
                    "stages": combined_stages,
                })
            return "CHOICE_REQUIRED", [], choices, []
        if not stages:
            return "UNSUPPORTED", [], None, []
        resolved_stages = [stage for stage in stages if stage is not None]
        return "CLEAR", resolved_stages, None, []

    def prepare(self, request: str) -> dict[str, Any]:
        try:
            with self._lock:
                if not isinstance(request, str) or not 1 <= len(request) <= MAX_REQUEST_CHARS or "\x00" in request:
                    return _public("ARGUMENT_INVALID")
                if self._active_choice_pending():
                    return _public("BLOCKED", code="CHOICE_PENDING")
                aliases: dict[str, str] = {}
                needs_devices = any(
                    row[2] in {"DEVICE_INVENTORY", "ANDROID_PROPERTY", "ANDROID_LOG_CAPTURE", "ANDROID_INSTALL", "ANDROID_FORCE_STOP", "ANDROID_CLEAR_DATA"}
                    and self.profile in _MAPPING[row[2]]["profiles"]
                    for row in self._matches(request)
                )
                if needs_devices and self.profile in {"android", "multi_repo"}:
                    aliases, _ = self._device_bindings()
                status, stages, choices, required = self._resolve(request, aliases)
                if status == "CHOICE_REQUIRED" and choices:
                    if len(choices) > 8:
                        return _public("ARGUMENT_REQUIRED", required_arguments=["narrower_choice"])
                    self._ensure_capacity()
                    prepare_id = _identifier("prep")
                    choice_rows = []
                    public_choices = []
                    for candidate in choices:
                        choice_id = _identifier("choice")
                        choice_rows.append({"choice_digest": _digest(choice_id), "label": candidate["label"], "stages": candidate["stages"]})
                        public_choices.append({"choice_id": choice_id, "label": candidate["label"]})
                    record = self._base_record(prepare_id, "prepare", "CHOICE_PENDING", _digest(request))
                    record["choices"] = choice_rows
                    record["bindings"] = self._binding_digests(any(self._needs_device_registry(row["stages"]) for row in choices))
                    self._write_record(prepare_id, record)
                    self._pending_choice_prepare_id = prepare_id
                    for public_choice, stored_choice in zip(public_choices, choice_rows):
                        public_choice["choice_review"] = self._choice_review(
                            prepare_id, public_choice["choice_id"], record, stored_choice,
                        )
                    return _public(status, prepare_id=prepare_id, choices=public_choices)
                if status != "CLEAR":
                    output: dict[str, Any] = {}
                    if required:
                        output["required_arguments"] = required
                    return _public(status, **output)
                intent_id = self._issue_intent(stages, _digest(request))
                return self._clear_response(intent_id, stages)
        except A4Error as exc:
            return _public("BLOCKED", code=exc.code)
        except Exception:
            return _public("BLOCKED", code="A4_PREPARATION_UNAVAILABLE")

    def _base_record(self, token: str, kind: str, state: str, request_digest: str, stages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        needs_devices = self._needs_device_registry(stages or [])
        return {
            "schema": "deputy.workers.a4-record.v1",
            "record_digest": _digest(token),
            "kind": kind,
            "state": state,
            "runtime_epoch": self.epoch,
            "profile": self.profile,
            "created_at": _now(),
            "expires_at": _now() + (PREPARE_TTL_SECONDS if kind == "prepare" else INTENT_TTL_SECONDS),
            "request_sha256": request_digest,
            "bindings": self._binding_digests(needs_devices),
            "stages": stages or [],
        }

    def _issue_intent(self, stages: list[dict[str, Any]], request_digest: str) -> str:
        if not stages or len(stages) > MAX_STAGES:
            raise A4Error("INTENT_NOT_ISSUABLE")
        self._ensure_capacity()
        effect = "OBSERVE" if all(stage["operation"] in OBSERVE_OPERATIONS for stage in stages) else "ACT"
        allowed = set(OBSERVE_OPERATIONS) | set(ACT_OPERATIONS)
        if any(stage["operation"] not in allowed for stage in stages):
            raise A4Error("INTENT_NOT_ISSUABLE")
        token = _identifier("intent")
        record = self._base_record(token, "intent", "PREPARED", request_digest, stages)
        record["effect"] = effect
        record["completed"] = []
        self._write_record(token, record)
        return token

    @staticmethod
    def _expires_utc(record: dict[str, Any]) -> str:
        return datetime.fromtimestamp(record["expires_at"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _stages_review(stages: list[dict[str, Any]]) -> str:
        parts = []
        for index, stage in enumerate(stages, 1):
            semantic = stage["semantic"]
            if semantic not in _MAPPING or stage["effect"] != _MAPPING[semantic]["effect"]:
                raise A4Error("APPROVAL_CONTEXT_INVALID")
            fields = [f"{index}:{semantic}", f"effect={stage['effect']}"]
            alias = stage.get("device_alias")
            if alias:
                if not isinstance(alias, str) or not _ALIAS_RE.fullmatch(alias):
                    raise A4Error("APPROVAL_CONTEXT_INVALID")
                fields.append(f"target={alias}")
            else:
                fields.append("target=CONFIGURED_REPOSITORY" if semantic in {"REGISTERED_VERIFIER", "REPO_STATE", "GIT_DIFF_CHECK"} else "target=REGISTERED_DEVICE_SET")
            params = stage.get("params", {})
            if not isinstance(params, dict) or not set(params).issubset({"artifact_id", "property", "limit", "verifier_id"}):
                raise A4Error("APPROVAL_CONTEXT_INVALID")
            for key, value in sorted(params.items()):
                if not isinstance(value, (str, int)) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(value)):
                    raise A4Error("APPROVAL_CONTEXT_INVALID")
                fields.append(f"{key}={value}")
            parts.append(", ".join(fields))
        return " | ".join(parts)

    @classmethod
    def _choice_review(cls, prepare_id: str, choice_id: str, record: dict[str, Any], selected: dict[str, Any]) -> str:
        effect = "OBSERVE" if all(stage["operation"] in OBSERVE_OPERATIONS for stage in selected["stages"]) else "ACT"
        return (f"A4 CHOICE; effect={effect}; {cls._stages_review(selected['stages'])}; "
                f"prepare={prepare_id}; choice={choice_id}; expires={cls._expires_utc(record)}")

    @classmethod
    def _act_review(cls, intent_id: str, record: dict[str, Any]) -> str:
        return (f"A4 ACT; {cls._stages_review(record['stages'])}; "
                f"ticket={intent_id}; expires={cls._expires_utc(record)}")

    def _clear_response(self, intent_id: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
        record = self._read_record(intent_id, "intent")
        response = _public("CLEAR", intent_id=intent_id, intent={
            "semantics": [stage["semantic"] for stage in stages],
            "effect": "OBSERVE" if all(stage["effect"].startswith("OBSERVE") for stage in stages) else "ACT",
            "stage_count": len(stages),
        }, expires_in_seconds=INTENT_TTL_SECONDS)
        if record["effect"] == "ACT":
            response["approval_review"] = self._act_review(intent_id, record)
        return response

    def choose(self, prepare_id: str, choice_id: str, choice_review: str) -> dict[str, Any]:
        try:
            with self._lock:
                if not _validate_id(prepare_id, "prep") or not _validate_id(choice_id, "choice"):
                    raise A4Error("TICKET_INVALID")
                record = self._read_record(prepare_id, "prepare")
                self._check_bindings(record)
                if (self.choice_claims / f"{_digest(prepare_id)}.claim").exists():
                    raise A4Error("CHOICE_ALREADY_USED")
                if record.get("state") != "CHOICE_PENDING":
                    raise A4Error("CHOICE_NOT_AVAILABLE")
                if _now() > record.get("expires_at", 0):
                    record["state"] = "EXPIRED"
                    self._write_record(prepare_id, record)
                    raise A4Error("CHOICE_EXPIRED")
                digest = _digest(choice_id)
                selected = next((row for row in record.get("choices", []) if hmac.compare_digest(row.get("choice_digest", ""), digest)), None)
                if selected is None:
                    raise A4Error("CHOICE_NOT_REGISTERED")
                if not isinstance(choice_review, str) or not hmac.compare_digest(
                    choice_review, self._choice_review(prepare_id, choice_id, record, selected)
                ):
                    raise A4Error("CHOICE_REVIEW_MISMATCH")
                # Reserve record capacity before consuming the one-shot choice.
                self._ensure_capacity()
                claim = self.choice_claims / f"{_digest(prepare_id)}.claim"
                try:
                    fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(fd)
                except FileExistsError:
                    raise A4Error("CHOICE_ALREADY_USED") from None
                record["state"] = "CHOSEN"
                record["chosen_at"] = _now()
                self._write_record(prepare_id, record)
                intent_id = self._issue_intent(selected["stages"], record["request_sha256"])
                if self._pending_choice_prepare_id == prepare_id:
                    self._pending_choice_prepare_id = None
                return self._clear_response(intent_id, selected["stages"])
        except A4Error as exc:
            return _public("BLOCKED", code=exc.code)
        except Exception:
            return _public("BLOCKED", code="A4_CHOICE_UNAVAILABLE")

    def dispatch(self, intent_id: str, envelope: str, approval_review: str | None = None) -> dict[str, Any]:
        try:
            with self._lock:
                if not _validate_id(intent_id, "intent"):
                    raise A4Error("TICKET_INVALID")
                record = self._read_record(intent_id, "intent")
                if record.get("state") == "OUTCOME_UNCERTAIN":
                    return _public("OUTCOME_UNCERTAIN", completed_stage_count=len(record.get("completed", [])))
                if record.get("state") == "REVOKED":
                    raise A4Error("TICKET_REVOKED")
                self._check_bindings(record)
                if _now() > record.get("expires_at", 0):
                    if record.get("state") == "PREPARED":
                        record["state"] = "EXPIRED"
                        self._write_record(intent_id, record)
                    raise A4Error("INTENT_EXPIRED")
                required_envelope = "observe" if record.get("effect") == "OBSERVE" else "act"
                if required_envelope != envelope:
                    raise A4Error("INTENT_EFFECT_MISMATCH")
                if envelope == "act" and (
                    not isinstance(approval_review, str)
                    or not hmac.compare_digest(approval_review, self._act_review(intent_id, record))
                ):
                    raise A4Error("APPROVAL_REVIEW_MISMATCH")
                if record.get("state") != "PREPARED":
                    raise A4Error("INTENT_ALREADY_DISPATCHED")
                claim = self.claims / f"{_digest(intent_id)}.claim"
                try:
                    fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, "w", encoding="ascii") as stream:
                        stream.write("claimed\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                except FileExistsError:
                    raise A4Error("INTENT_ALREADY_DISPATCHED") from None
                record["state"] = "DISPATCHING"
                record["dispatch_started_at"] = _now()
                record["completed"] = []
                record["local_receipts"] = []
                self._write_record(intent_id, record)
                self._check_bindings(record)
                permitted = tuple(OBSERVE_OPERATIONS) if envelope == "observe" else tuple((*OBSERVE_OPERATIONS, *ACT_OPERATIONS))
                public_stages = []
                for index, stage in enumerate(record["stages"]):
                    self._check_bindings(record)
                    self._check_stage_authority(stage, record)
                    record["active_stage_index"] = index
                    record["active_stage_started_at"] = _now()
                    self._write_record(intent_id, record)
                    params = dict(stage.get("params", {}))
                    alias = stage.get("device_alias")
                    stage_aliases: dict[str, str] = {}
                    if stage["semantic"] == "DEVICE_INVENTORY":
                        stage_aliases, _ = self._device_bindings()
                    if alias:
                        stage_aliases, _ = self._device_bindings()
                        serial = stage_aliases.get(alias.casefold())
                        if serial is None:
                            raise A4Error("INTENT_AUTHORITY_CHANGED")
                        params["serial"] = serial
                    run_holder: dict[str, str] = {}

                    def record_run_started(run_id: str) -> None:
                        run_holder["run_id"] = run_id
                        record["local_receipts"].append({
                            "stage_index": index,
                            "semantic": stage["semantic"],
                            "operation": stage["operation"],
                            "worker_run_id": run_id,
                            "state": "RUNNING",
                        })
                        self._write_record(intent_id, record)

                    result = self.worker_service.execute(
                        {"operation": stage["operation"], **params},
                        permitted,
                        on_run_started=record_run_started,
                    )
                    projected = self._project_stage(stage, result, alias, stage_aliases)
                    public_stages.append(projected)
                    record["completed"].append({"semantic": stage["semantic"], "status": projected["status"], "code": projected.get("code")})
                    if run_holder:
                        for receipt in reversed(record["local_receipts"]):
                            if receipt.get("stage_index") == index and receipt.get("state") == "RUNNING":
                                receipt.update({"state": "TERMINAL", "status": projected["status"], "code": projected.get("code")})
                                break
                    record["active_stage_index"] = None
                    record["receipt"] = {
                        "status": projected["status"],
                        "completed_stage_count": len(record["completed"]),
                        "last_semantic": stage["semantic"],
                    }
                    self._write_record(intent_id, record)
                    if projected["status"] != "PASS":
                        record["state"] = "COMPLETED"
                        record["terminal_at"] = _now()
                        self._write_record(intent_id, record)
                        return _public(projected["status"], stages=public_stages,
                                       completed_stage_count=len(record["completed"]), partial=len(record["completed"]) < len(record["stages"]))
                record["state"] = "COMPLETED"
                record["terminal_at"] = _now()
                record["receipt"] = {"status": "PASS", "completed_stage_count": len(record["completed"])}
                self._write_record(intent_id, record)
                return _public("PASS", stages=public_stages, completed_stage_count=len(public_stages), partial=False)
        except A4Error as exc:
            if "record" in locals() and record.get("state") == "DISPATCHING":
                try:
                    record["state"] = "COMPLETED"
                    record["active_stage_index"] = None
                    record["terminal_at"] = _now()
                    record["receipt"] = {
                        "status": "BLOCKED",
                        "reason": exc.code,
                        "completed_stage_count": len(record.get("completed", [])),
                    }
                    self._write_record(intent_id, record)
                except Exception:
                    return _public("OUTCOME_UNCERTAIN", completed_stage_count=len(record.get("completed", [])))
                completed = len(record.get("completed", []))
                return _public("BLOCKED", code=exc.code, completed_stage_count=completed,
                               partial=completed < len(record.get("stages", [])))
            return _public("BLOCKED", code=exc.code)
        except Exception:
            if "record" not in locals() or record.get("state") != "DISPATCHING":
                return _public("BLOCKED", code="A4_DISPATCH_UNAVAILABLE")
            try:
                if "intent_id" in locals():
                    record["state"] = "OUTCOME_UNCERTAIN"
                    record["receipt"] = {"status": "OUTCOME_UNCERTAIN", "reason": "INTERNAL_DISPATCH_FAILURE",
                                          "completed_stage_count": len(record.get("completed", []))}
                    self._write_record(intent_id, record)
            except Exception:
                pass
            return _public("OUTCOME_UNCERTAIN", completed_stage_count=len(record.get("completed", [])) if "record" in locals() else 0)

    def _check_stage_authority(self, stage: dict[str, Any], record: dict[str, Any]) -> None:
        semantic = stage.get("semantic")
        spec = _MAPPING.get(semantic)
        operation = stage.get("operation")
        if (not spec or spec["operation"] != operation or stage.get("effect") != spec["effect"]
                or self.profile not in spec["profiles"]):
            raise A4Error("INTENT_AUTHORITY_CHANGED")
        registry = load_registry(self.registry_path)
        if operation not in registry or not registry[operation].get("enabled"):
            raise A4Error("INTENT_AUTHORITY_CHANGED")
        if record.get("effect") == "OBSERVE" and operation not in OBSERVE_OPERATIONS:
            raise A4Error("INTENT_EFFECT_MISMATCH")
        if record.get("effect") == "ACT" and operation not in set(OBSERVE_OPERATIONS) | set(ACT_OPERATIONS):
            raise A4Error("INTENT_EFFECT_MISMATCH")

    @staticmethod
    def _project_stage(stage: dict[str, Any], result: dict[str, Any], alias: str | None, aliases: dict[str, str]) -> dict[str, Any]:
        status = result.get("status")
        if status not in {"PASS", "FAIL", "BLOCKED", "UNPROVEN", "CONTRADICTION", "CANCELLED"}:
            status = "UNPROVEN"
        value: dict[str, Any] = {"semantic": stage["semantic"], "status": status}
        if status != "PASS":
            code = result.get("code")
            if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
                value["code"] = code
        operation = stage["operation"]
        def exit_code() -> int | None:
            code = result.get("exit_code")
            return code if type(code) is int and -1_000_000 <= code <= 1_000_000 else None

        if operation == "ADB_LIST_DEVICES":
            reverse = {serial: name.upper() for name, serial in aliases.items()}
            devices = []
            for row in result.get("devices", []) if isinstance(result.get("devices"), list) else []:
                if isinstance(row, dict) and row.get("serial") in reverse:
                    state = row.get("state")
                    if not isinstance(state, str) or not 1 <= len(state) <= 32 or any(ord(ch) < 33 or ord(ch) == 127 for ch in state):
                        state = "UNKNOWN"
                    devices.append({"device_alias": reverse[row["serial"]], "state": state})
            value.update({"devices": devices[:64], "registered_device_count": len(devices)})
        elif operation == "ADB_QUERY_PROPERTY":
            value["device_alias"] = alias.upper() if alias else None
            if isinstance(result.get("property"), str):
                value["property"] = result["property"]
            if isinstance(result.get("value"), str):
                value["value"] = result["value"][:1024]
        elif operation == "ADB_LOGCAT_CAPTURE":
            line_count = result.get("line_count", 0)
            value.update({"device_alias": alias.upper() if alias else None,
                          "line_count": line_count if isinstance(line_count, int) and 0 <= line_count <= 2000 else 0})
        elif operation == "ADB_INSTALL":
            value.update({"device_alias": alias.upper() if alias else None, "artifact": stage.get("params", {}).get("artifact_id"),
                          "installed": status == "PASS", "exit_code": exit_code()})
        elif operation == "ADB_FORCE_STOP_DEPUTY":
            value.update({"device_alias": alias.upper() if alias else None, "stopped": status == "PASS",
                          "exit_code": exit_code()})
        elif operation == "ADB_CLEAR_DEPUTY_DATA":
            value.update({"device_alias": alias.upper() if alias else None, "cleared": result.get("cleared") is True})
        elif operation == "RUN_APPROVED_VERIFIER":
            value.update({"passed": status == "PASS", "exit_code": exit_code()})
        elif operation == "CAPTURE_REPO_STATE":
            head = result.get("head")
            if isinstance(head, str) and re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
                value["head"] = head
            branch = result.get("branch")
            if isinstance(branch, str) and len(branch) <= 256 and not any(ord(ch) < 32 or ord(ch) == 127 for ch in branch):
                value["branch"] = branch
            for key in ("dirty", "diff_check_pass"):
                if type(result.get(key)) is bool:
                    value[key] = result[key]
        elif operation == "GIT_DIFF_CHECK":
            code = exit_code()
            if code is not None:
                value["exit_code"] = code
        from .privacy import public_result
        return public_result(value)


def _tool_code(result: dict[str, Any]) -> dict[str, Any]:
    return result
