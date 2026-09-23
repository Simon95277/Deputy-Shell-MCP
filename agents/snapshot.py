from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from config import DEPUTY_SHELL_ROOT, EVIDENCE_ROOT, SNAPSHOT_ROOT as CONFIG_SNAPSHOT_ROOT, BRIDGE_FIXTURES
from privacy import ContentPolicyBlocked, scan_candidate
from source_policy import POLICY_VERSION, configured_policy


REPO = DEPUTY_SHELL_ROOT
SNAPSHOT_ROOT = CONFIG_SNAPSHOT_ROOT / "DEPUTY_SHELL"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILE_COUNT = 5000
MAX_TOTAL_BYTES = 50 * 1024 * 1024
GIT = shutil.which("git")
GIT_COMMAND_TIMEOUT_SECONDS = 3
_GIT_ENV_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL"}

# Server-owned only. The public MCP deliberately does not expose this mapping.
WORKSPACES = {
    "BRIDGE_LAB": BRIDGE_FIXTURES,
    "DEPUTY_SHELL": REPO,
}
DEPUTY_SHELL_PROVIDER_EXPOSURE = True

_DEFAULT_POLICY = configured_policy()
ALLOWED_PREFIXES = _DEFAULT_POLICY.allowed_prefixes
EXCLUDED_PREFIXES = _DEFAULT_POLICY.excluded_prefixes
APPROVED_UNTRACKED = frozenset(_DEFAULT_POLICY.approved_untracked)
ALLOWED_ROOT_FILES = frozenset(_DEFAULT_POLICY.allowed_root_files)
SENSITIVE_NAMES = (
    ".env", "local.properties", "google-services.json", "signing.properties",
    "credentials", "credential", "token", "password", "secret", "keystore",
    ".jks", ".p12", ".pfx", ".pem", ".key", "auth", "session",
)
BINARY_SUFFIXES = {
    ".apk", ".aab", ".apks", ".so", ".dll", ".exe", ".class", ".dex", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".ndjson", ".bin",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PreparationTimeout(RuntimeError):
    pass


def _remaining(deadline):
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PreparationTimeout("PREPARATION_TIMEOUT")
    return remaining


def _run_git_process(args, deadline=None, env=None):
    if not GIT:
        raise PreparationTimeout("GIT_NOT_RESOLVED")
    remaining = _remaining(deadline)
    timeout = GIT_COMMAND_TIMEOUT_SECONDS if remaining is None else max(0.01, min(GIT_COMMAND_TIMEOUT_SECONDS, remaining))
    child_env = ({key: value for key, value in os.environ.items() if key.upper() in _GIT_ENV_KEYS}
                 if env is None else dict(env))
    # Git control/credential overrides from the MCP host must not redirect
    # snapshot inspection or leak into any later provider-facing path.
    for key in list(child_env):
        if key.upper().startswith("GIT_"):
            child_env.pop(key, None)
    child_env["GIT_OPTIONAL_LOCKS"] = "0"
    child_env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run([GIT, "-C", str(REPO), *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=child_env)


def _git(*args: str, deadline=None, phase_callback=None, trace_path=None, command_label=None, capture_generation="UNSPECIFIED", allow_failure=False) -> str | None:
    if not GIT:
        raise PreparationTimeout("GIT_NOT_RESOLVED")
    if phase_callback:
        phase_callback("SNAPSHOT_GIT_" + {
            "rev-parse": "UPSTREAM" if "--abbrev-ref" in args else "TRACKED",
            "status": "STATUS",
            "diff": "DIFF_DELETED" if "--diff-filter=D" in args else "DIFF_MODIFIED",
            "ls-files": "UNTRACKED" if "--others" in args else "TRACKED",
            "branch": "TRACKED",
        }.get(args[0], "TRACKED"))
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.monotonic()
    _trace_git(trace_path, command_label or args[0], capture_generation, "START", started_at, started)
    try:
        result = _run_git_process(args, deadline=deadline)
        if result.returncode:
            if allow_failure:
                _trace_git(trace_path, command_label or args[0], capture_generation, "PASS", started_at, started)
                return None
            raise RuntimeError(f"GIT_EXIT_{result.returncode}:{result.stderr[-1024:].decode(errors='replace')}")
        _trace_git(trace_path, command_label or args[0], capture_generation, "PASS", started_at, started)
        return result.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        _trace_git(trace_path, command_label or args[0], capture_generation, "TIMEOUT", started_at, started)
        raise PreparationTimeout("PREPARATION_TIMEOUT") from exc
    except Exception:
        _trace_git(trace_path, command_label or args[0], capture_generation, "ERROR", started_at, started)
        raise


def _trace_git(trace_path, command_label, capture_generation, event, started_at, started):
    if not trace_path:
        return
    path = Path(trace_path)
    try:
        events = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        events = []
    events.append({"ordinal": len(events) + 1, "capture_generation": capture_generation, "command_label": command_label, "event": event, "started_at": started_at, "elapsed_ms": int((time.monotonic() - started) * 1000)})
    path.write_text(json.dumps(events[-64:]), encoding="utf-8")


def _parse_name_status(raw: str) -> list[tuple[str, str]]:
    parts = raw.split("\0")
    result = []
    for index in range(0, len(parts) - 1, 2):
        if parts[index]:
            result.append((parts[index], parts[index + 1]))
    return sorted(result, key=lambda item: (item[1], item[0]))


def _canonical_status(worktree_changes: list[tuple[str, str]], index_changes: list[tuple[str, str]], untracked: list[str]) -> str:
    rows = [f"W {status}\t{path}" for status, path in worktree_changes]
    rows += [f"I {status}\t{path}" for status, path in index_changes]
    rows += [f"U ??\t{path}" for path in sorted(untracked)]
    return "\n".join(sorted(rows))


def capture_repo_state(deadline=None, phase_callback=None, trace_path=None, capture_generation="UNSPECIFIED") -> dict:
    def phase(name):
        if phase_callback: phase_callback(name)
    upstream_value = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_UPSTREAM"), trace_path=trace_path, command_label="upstream", capture_generation=capture_generation, allow_failure=True)
    upstream = upstream_value.strip() if upstream_value else None
    worktree_changes = _parse_name_status(_git("diff", "--name-status", "--no-renames", "-z", "--", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_WORKTREE_DIFF"), trace_path=trace_path, command_label="worktree_diff", capture_generation=capture_generation))
    index_changes = _parse_name_status(_git("diff", "--cached", "--name-status", "--no-renames", "-z", "--", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_INDEX_DIFF"), trace_path=trace_path, command_label="index_diff", capture_generation=capture_generation))
    untracked = [path for path in _git("ls-files", "--others", "--exclude-standard", "-z", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_UNTRACKED"), trace_path=trace_path, command_label="untracked", capture_generation=capture_generation).split("\0") if path]
    tracked = _git("ls-files", "-z", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_TRACKED_FILES"), trace_path=trace_path, command_label="tracked_files", capture_generation=capture_generation).split("\0")
    return {
        "repo_id": "DEPUTY_SHELL",
        "branch": _git("branch", "--show-current", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_BRANCH"), trace_path=trace_path, command_label="branch", capture_generation=capture_generation).strip(),
        "head": _git("rev-parse", "HEAD", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_HEAD"), trace_path=trace_path, command_label="head", capture_generation=capture_generation).strip(),
        "upstream": upstream,
        "status_short": _canonical_status(worktree_changes, index_changes, untracked),
        "dirty": bool(worktree_changes or index_changes or untracked),
        "tracked_modified": sorted({path for _, path in worktree_changes + index_changes}),
        "tracked_deleted": sorted({path for status, path in worktree_changes + index_changes if status.startswith("D")}),
        "worktree_changes": worktree_changes,
        "index_changes": index_changes,
        "tracked": sorted(path for path in tracked if path),
        "untracked": untracked,
    }


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    return attrs != 0xFFFFFFFF and bool(attrs & 0x400)


def _has_reparse_component(path: Path, repo_root: Path) -> bool:
    """Reject a reparse point at any component, not only at the leaf file."""
    if _is_reparse(repo_root):
        return True
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return True
    current = repo_root
    for part in relative.parts:
        current = current / part
        if _is_reparse(current):
            return True
    return False


def _is_sensitive(rel: str) -> bool:
    low = rel.lower().replace("\\", "/")
    name = low.rsplit("/", 1)[-1]
    return (name in {".env", "local.properties", "google-services.json", "signing.properties"}
            or any(part in name for part in SENSITIVE_NAMES)
            or "/.env." in low)


def _allowed(rel: str) -> bool:
    # Public call surfaces cannot choose this owner-controlled policy.
    return configured_policy().allows(rel)


def _looks_text(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False
    sample = path.read_bytes()[:8192]
    return b"\x00" not in sample


COHERENCE_VERSION = "DA-BYTE-COHERENCE-1"
RUNTIME_CONTRACT_VERSION = "DA-PRIVACY-1"


def _file_record(rel, source, candidate, classification):
    return {"path": rel.replace("\\", "/"), "size": source.stat().st_size,
            "source_before_sha256": _sha256(source),
            "candidate_sha256": _sha256(candidate),
            "source_after_sha256": _sha256(source),
            "sha256": _sha256(candidate), "classification": classification}


def _publish_candidate(candidate: Path, retain_backup=False):
    backup = SNAPSHOT_ROOT.with_name(SNAPSHOT_ROOT.name + ".backup")
    try:
        if backup.exists():
            shutil.rmtree(backup)
        if SNAPSHOT_ROOT.exists():
            SNAPSHOT_ROOT.replace(backup)
        candidate.replace(SNAPSHOT_ROOT)
        if backup.exists() and not retain_backup:
            shutil.rmtree(backup)
        return backup if retain_backup and backup.exists() else None
    except Exception:
        try:
            if SNAPSHOT_ROOT.exists():
                shutil.rmtree(SNAPSHOT_ROOT)
            if backup.exists():
                backup.replace(SNAPSHOT_ROOT)
        except Exception as rollback_error:
            raise RuntimeError(f"SNAPSHOT_PUBLICATION_ROLLBACK_FAILED:{rollback_error}")
        raise


def create_snapshot(deadline=None, phase_callback=None, checkpoint=None, privacy_audit_path=None, policy=None, job_destination=None, timings_path=None) -> dict:
    candidate_root = SNAPSHOT_ROOT.with_name(SNAPSHOT_ROOT.name + ".candidate")
    job_candidate = Path(job_destination).with_name(Path(job_destination).name + ".candidate") if job_destination else None
    if job_destination and Path(job_destination).exists():
        raise RuntimeError("SNAPSHOT_JOB_DESTINATION_EXISTS")
    started = time.monotonic()
    timings = {}
    current_phase = "SNAPSHOT_GIT_STATE_BEFORE"

    def phase(name):
        nonlocal current_phase
        current_phase = name
        if phase_callback:
            phase_callback(name)

    try:
        phase("SNAPSHOT_RECOVER_LAST_GOOD")
        _restore_last_good_before_deadline(deadline)
        result = _create_snapshot_candidate(
            deadline=deadline, phase=phase, checkpoint=checkpoint,
            privacy_audit_path=privacy_audit_path, policy=policy,
            candidate_root=candidate_root, job_candidate=job_candidate,
            job_destination=Path(job_destination) if job_destination else None,
            timings=timings, started=started,
        )
        if timings_path:
            try:
                _write_bounded_json(timings_path, {
                    "status": "PASS", "phase": "SNAPSHOT_PUBLISHED",
                    "timings_ms": result["audit"]["timings_ms"],
                })
            except OSError:
                pass
        return result
    except Exception as exc:
        shutil.rmtree(candidate_root, ignore_errors=True)
        if job_candidate:
            shutil.rmtree(job_candidate, ignore_errors=True)
        if job_destination:
            shutil.rmtree(job_destination, ignore_errors=True)
        # A timeout must never leave a PASS audit for a generation that was
        # not published. Blocked-secret evidence is intentionally retained.
        if privacy_audit_path and not isinstance(exc, ContentPolicyBlocked):
            try:
                Path(privacy_audit_path).unlink(missing_ok=True)
            except OSError:
                pass
        if timings_path:
            try:
                _write_bounded_json(timings_path, {
                    "status": "TIMEOUT" if isinstance(exc, PreparationTimeout) else "FAILED",
                    "phase": current_phase,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "timings_ms": timings,
                })
            except OSError:
                pass
        raise


def _remove_tree_before_deadline(path: Path, deadline):
    if not path.exists():
        return
    for current, directories, files in os.walk(path, topdown=False):
        for name in files:
            _remaining(deadline)
            (Path(current) / name).unlink()
        for name in directories:
            _remaining(deadline)
            (Path(current) / name).rmdir()
    _remaining(deadline)
    path.rmdir()


def _write_bounded_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def _restore_last_good_before_deadline(deadline):
    """Recover an interrupted two-rename publication before preparing anew."""
    backup = SNAPSHOT_ROOT.with_name(SNAPSHOT_ROOT.name + ".backup")
    if backup.exists() and not SNAPSHOT_ROOT.exists():
        _remaining(deadline)
        backup.replace(SNAPSHOT_ROOT)


def _create_snapshot_candidate(deadline=None, phase=None, checkpoint=None, privacy_audit_path=None,
                              policy=None, candidate_root=None, job_candidate=None,
                              job_destination=None, timings=None, started=None) -> dict:
    policy = policy or configured_policy()
    timings = timings if timings is not None else {}
    started = started or time.monotonic()
    phase = phase or (lambda _name: None)
    phase("SNAPSHOT_GIT_STATE_BEFORE")
    stage_started = time.monotonic()
    state_before = capture_repo_state(deadline=deadline, phase_callback=phase, trace_path=checkpoint, capture_generation="BEFORE")
    timings["git_state_before_ms"] = int((time.monotonic() - stage_started) * 1000)
    tracked = set(state_before["tracked"])
    candidates = []
    excluded = {"sensitive": [], "policy": [], "binary": [], "unsafe": []}
    reparses = []
    phase("SNAPSHOT_SOURCE_SELECTION")
    stage_started = time.monotonic()
    for rel in sorted(tracked):
        _remaining(deadline)
        source = REPO / rel
        if _has_reparse_component(source, REPO):
            reparses.append(rel)
            excluded["unsafe"].append(rel)
            continue
        if _is_sensitive(rel):
            excluded["sensitive"].append(rel)
            continue
        if not policy.allows(rel):
            excluded["policy"].append(rel)
            continue
        if not source.is_file() or not _looks_text(source):
            excluded["binary"].append(rel)
            continue
        size = source.stat().st_size
        if size > min(MAX_FILE_BYTES, policy.max_file_bytes):
            raise RuntimeError(f"FILE_SIZE_LIMIT:{rel}:{size}")
        candidates.append((rel, source, size))

    excluded_untracked = []
    potential_untracked = []
    for rel in state_before["untracked"]:
        if _is_sensitive(rel):
            excluded_untracked.append({"path": rel, "classification": "EXCLUDED_SENSITIVE"})
        elif rel in policy.approved_untracked:
            potential_untracked.append({"path": rel, "classification": "POTENTIAL_SOURCE_REQUIRES_APPROVAL"})
        else:
            excluded_untracked.append({"path": rel, "classification": "EXCLUDED_POLICY"})

    for rel in sorted(policy.approved_untracked):
        _remaining(deadline)
        if rel in tracked:
            # Once an approved path is tracked, the tracked-file pass owns it.
            continue
        source = REPO / rel
        # Approval is an upper bound on eligible untracked paths; absence is
        # ordinary and must not make another repository policy unusable.
        if not source.exists():
            continue
        if not source.is_file() or _has_reparse_component(source, REPO) or _is_sensitive(rel) or not _looks_text(source):
            raise RuntimeError(f"APPROVED_UNTRACKED_INVALID:{rel}")
        size = source.stat().st_size
        if size > min(MAX_FILE_BYTES, policy.max_file_bytes):
            raise RuntimeError(f"FILE_SIZE_LIMIT:{rel}:{size}")
        candidates.append((rel, source, size))

    total = sum(size for _, _, size in candidates)
    if len(candidates) > min(MAX_FILE_COUNT, policy.max_file_count) or total > min(MAX_TOTAL_BYTES, policy.max_total_bytes):
        raise RuntimeError(f"SNAPSHOT_LIMIT:{len(candidates)}:{total}")
    timings["source_selection_ms"] = int((time.monotonic() - stage_started) * 1000)

    phase("SNAPSHOT_SOURCE_BEFORE_HASH")
    stage_started = time.monotonic()
    if candidate_root.exists():
        shutil.rmtree(candidate_root)
    candidate_root.mkdir(parents=True)
    files = []
    before_hashes = {}
    for rel, source, _ in candidates:
        _remaining(deadline)
        before_hashes[rel] = _sha256(source)
    before_hash_ms = int((time.monotonic() - stage_started) * 1000)
    timings["source_before_hash_ms"] = before_hash_ms
    phase("SNAPSHOT_CANDIDATE_COPY")
    copy_started = time.monotonic()
    for rel, source, size in candidates:
        _remaining(deadline)
        target = candidate_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    copy_ms = int((time.monotonic() - copy_started) * 1000)
    timings["candidate_copy_ms"] = copy_ms
    phase("SNAPSHOT_CANDIDATE_HASH")
    candidate_hash_started = time.monotonic()
    candidate_hashes = {}
    for rel, _, _ in candidates:
        _remaining(deadline)
        candidate_hashes[rel] = _sha256(candidate_root / rel)
    candidate_hash_ms = int((time.monotonic() - candidate_hash_started) * 1000)
    timings["candidate_hash_ms"] = candidate_hash_ms

    # Scan the byte-exact candidate generation after its hash and before source
    # post-hashes, coherence approval, publication, Docker, or provider setup.
    scan_records = [{"path": rel.replace("\\", "/")} for rel, _, _ in candidates]
    phase("SNAPSHOT_SECRET_SCAN")
    scan_started = time.monotonic()
    try:
        privacy_audit = scan_candidate(candidate_root, scan_records, checkpoint=lambda: _remaining(deadline))
    except Exception:
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise
    phase("SNAPSHOT_SCANNED_CANDIDATE_HASH")
    scan_integrity_started = time.monotonic()
    scanned_candidate_hashes = {}
    for rel, _, _ in candidates:
        _remaining(deadline)
        scanned_candidate_hashes[rel] = _sha256(candidate_root / rel)
    timings["post_scan_candidate_hash_ms"] = int((time.monotonic() - scan_integrity_started) * 1000)
    if scanned_candidate_hashes != candidate_hashes:
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise RuntimeError("SNAPSHOT_CANDIDATE_CHANGED_DURING_SCAN")
    if privacy_audit["blocking_finding_count"]:
        if privacy_audit_path:
            Path(privacy_audit_path).write_text(json.dumps(privacy_audit, indent=2), encoding="utf-8")
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise ContentPolicyBlocked(ContentPolicyBlocked.code)
    timings["content_secret_scan_ms"] = int((time.monotonic() - scan_started) * 1000)

    manifest = {
        "schema": "deputy.recon.snapshot-coherence.v1",
        "policy_version": POLICY_VERSION,
        "coherence_version": COHERENCE_VERSION,
        "coherence_status": "QUALIFYING",
        "workspace_id": "DEPUTY_SHELL",
        "repo": {"branch": state_before["branch"], "head": state_before["head"], "dirty": state_before["dirty"]},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files, "file_count": len(files), "total_bytes": total,
    }
    phase("SNAPSHOT_GIT_STATE_AFTER")
    after_hash_started = time.monotonic()
    state_after = capture_repo_state(deadline=deadline, phase_callback=phase, trace_path=checkpoint, capture_generation="AFTER")
    timings["git_state_after_ms"] = int((time.monotonic() - after_hash_started) * 1000)
    phase("SNAPSHOT_SOURCE_AFTER_HASH")
    after_hash_started = time.monotonic()
    after_hashes = {}
    for rel, source, _ in candidates:
        _remaining(deadline)
        after_hashes[rel] = _sha256(source)
    after_hash_ms = int((time.monotonic() - after_hash_started) * 1000)
    timings["source_after_hash_ms"] = after_hash_ms
    for rel, source, size in candidates:
        files.append({"path": rel.replace("\\", "/"), "size": size,
                      "source_before_sha256": before_hashes[rel],
                      "candidate_sha256": candidate_hashes[rel],
                      "source_after_sha256": after_hashes[rel],
                      "sha256": candidate_hashes[rel],
                      "classification": "TRACKED_MODIFIED" if rel in state_before["tracked_modified"] else "TRACKED_CLEAN"})
    manifest["files"] = files
    manifest["file_count"] = len(files)
    phase("SNAPSHOT_COHERENCE_VALIDATE")
    validation_started = time.monotonic()
    mismatches = [rel for rel in sorted(before_hashes) if not (before_hashes[rel] == candidate_hashes[rel] == after_hashes[rel])]
    comparable = ("branch", "head", "upstream", "worktree_changes", "index_changes", "tracked", "untracked", "dirty")
    repo_validation_ms = int((time.monotonic() - validation_started) * 1000)
    timings["coherence_validate_ms"] = repo_validation_ms
    if mismatches or any(state_before[key] != state_after[key] for key in comparable):
        manifest["coherence_status"] = "BLOCKED"
        (candidate_root / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise RuntimeError("SNAPSHOT_SOURCE_CHANGED_DURING_CAPTURE")
    manifest["coherence_status"] = "PASS"
    (candidate_root / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    phase("SNAPSHOT_PRIVACY_EVIDENCE")
    evidence_started = time.monotonic()
    audit = {"schema": "deputy.recon.snapshot-coherence.v1", "coherence_version": COHERENCE_VERSION, "state_before": state_before, "state_after": state_after, "excluded": excluded, "untracked_classification": excluded_untracked + potential_untracked, "reparse_points": reparses, "limits": {"max_file_bytes": policy.max_file_bytes, "max_file_count": policy.max_file_count, "max_total_bytes": policy.max_total_bytes}, "source_policy": {"schema": policy.schema, "policy_id": policy.policy_id, "policy_version": POLICY_VERSION}, "privacy_scan": privacy_audit, "provider_exposure": DEPUTY_SHELL_PROVIDER_EXPOSURE, "trust_model": "TRUSTED_SINGLE_OPERATOR_V1", "timings_ms": {**timings, "privacy_evidence_prepare_ms": 0, "publication_ms": None}}
    (candidate_root / "privacy-scan.json").write_text(json.dumps(privacy_audit, indent=2), encoding="utf-8")
    timings["privacy_evidence_prepare_ms"] = int((time.monotonic() - evidence_started) * 1000)
    audit["timings_ms"] = {**timings, "publication_ms": None}
    # The audit is part of the candidate generation, so PASS evidence becomes
    # visible only with the atomic shared-master publication.
    (candidate_root / "repo-state-and-audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    if job_candidate:
        phase("SNAPSHOT_JOB_COPY")
        copy_started = time.monotonic()
        shutil.rmtree(job_candidate, ignore_errors=True)
        job_candidate.parent.mkdir(parents=True, exist_ok=True)
        def bounded_copy(src, dst):
            _remaining(deadline)
            return shutil.copy2(src, dst)
        shutil.copytree(candidate_root, job_candidate, copy_function=bounded_copy)
        timings["job_copy_ms"] = int((time.monotonic() - copy_started) * 1000)

    backup_path = None
    backup = SNAPSHOT_ROOT.with_name(SNAPSHOT_ROOT.name + ".backup")
    phase("SNAPSHOT_STALE_BACKUP_CLEANUP")
    cleanup_started = time.monotonic()
    _remove_tree_before_deadline(backup, deadline)
    timings["stale_backup_cleanup_ms"] = int((time.monotonic() - cleanup_started) * 1000)
    phase("SNAPSHOT_PUBLISH_READY")
    _remaining(deadline)
    publication_started = time.monotonic()
    backup_path = _publish_candidate(candidate_root, retain_backup=True)
    # Job bytes were copied and verified before the final guard. Publish their
    # directory only after the shared qualified generation is committed.
    try:
        if job_candidate:
            job_candidate.replace(job_destination)
    except Exception:
        try:
            shutil.rmtree(SNAPSHOT_ROOT, ignore_errors=True)
            if backup_path and backup_path.exists():
                backup_path.replace(SNAPSHOT_ROOT)
        except Exception as rollback_error:
            raise RuntimeError("SNAPSHOT_JOB_PUBLICATION_ROLLBACK_FAILED") from rollback_error
        raise RuntimeError("SNAPSHOT_JOB_PUBLICATION_FAILED")
    publication_ms = int((time.monotonic() - publication_started) * 1000)
    timings["publication_ms"] = publication_ms
    timings["total_refresh_ms"] = int((time.monotonic() - started) * 1000)
    audit["timings_ms"] = dict(timings)
    if privacy_audit_path:
        try:
            _write_bounded_json(privacy_audit_path, privacy_audit)
        except OSError:
            pass
    try:
        EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        _write_bounded_json(EVIDENCE_ROOT / "repo-state-and-audit.json", audit)
    except OSError:
        pass
    return {"manifest": manifest, "audit": audit, "snapshot": str(SNAPSHOT_ROOT), "coherence": "PASS", "runtime_contract_version": RUNTIME_CONTRACT_VERSION}


if __name__ == "__main__":
    print(json.dumps(create_snapshot(), indent=2))
