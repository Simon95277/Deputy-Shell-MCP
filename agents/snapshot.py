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


REPO = DEPUTY_SHELL_ROOT
SNAPSHOT_ROOT = CONFIG_SNAPSHOT_ROOT / "DEPUTY_SHELL"
POLICY_VERSION = "DA-FAST-2-positive-allowlist-v1"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILE_COUNT = 5000
MAX_TOTAL_BYTES = 50 * 1024 * 1024
GIT = shutil.which("git")
GIT_COMMAND_TIMEOUT_SECONDS = 3

# Server-owned only. The public MCP deliberately does not expose this mapping.
WORKSPACES = {
    "BRIDGE_LAB": BRIDGE_FIXTURES,
    "DEPUTY_SHELL": REPO,
}
DEPUTY_SHELL_PROVIDER_EXPOSURE = True

ALLOWED_PREFIXES = ("app/src/", "backend/", "tools/")
EXCLUDED_PREFIXES = ("tools/linux-runtime/",)
APPROVED_UNTRACKED = frozenset({
    "app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bContractWideCandidateProbeHarnessTest.kt",
    "app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bPostInstallPreservationTest.kt",
    "app/src/executionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidation.kt",
    "app/src/main/java/com/deputyshell/app/runtime/pack/P3bCanonicalGenerationTreeFingerprintV1.kt",
    "app/src/main/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1.kt",
    "app/src/test/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1Test.kt",
    "app/src/testExecutionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidationTest.kt",
    "tools/android/verify_androidtest_dex_contents.py",
    "tools/android/verify_validation_target_dex_contents.py",
})
ALLOWED_ROOT_FILES = {
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    "gradlew",
    "gradlew.bat",
}
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
    child_env = os.environ.copy() if env is None else dict(env)
    child_env["GIT_OPTIONAL_LOCKS"] = "0"
    child_env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run([GIT, "-C", str(REPO), *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=child_env)


def _git(*args: str, deadline=None, phase_callback=None, trace_path=None, command_label=None, capture_generation="UNSPECIFIED") -> str:
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
        env = os.environ.copy()
        result = _run_git_process(args, deadline=deadline, env=env)
        if result.returncode:
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
    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_UPSTREAM"), trace_path=trace_path, command_label="upstream", capture_generation=capture_generation).strip()
    worktree_changes = _parse_name_status(_git("diff", "--name-status", "--no-renames", "-z", "--", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_WORKTREE_DIFF"), trace_path=trace_path, command_label="worktree_diff", capture_generation=capture_generation))
    index_changes = _parse_name_status(_git("diff", "--cached", "--name-status", "--no-renames", "-z", "--", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_INDEX_DIFF"), trace_path=trace_path, command_label="index_diff", capture_generation=capture_generation))
    untracked = [path for path in _git("ls-files", "--others", "--exclude-standard", "-z", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_UNTRACKED"), trace_path=trace_path, command_label="untracked", capture_generation=capture_generation).split("\0") if path]
    tracked = _git("ls-files", "-z", deadline=deadline, phase_callback=lambda _: phase("SNAPSHOT_GIT_TRACKED_FILES"), trace_path=trace_path, command_label="tracked_files", capture_generation=capture_generation).split("\0")
    return {
        "repo_id": "DEPUTY_SHELL",
        "repo_root_verified": str(REPO).replace("\\", "/"),
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


def _is_sensitive(rel: str) -> bool:
    low = rel.lower().replace("\\", "/")
    name = low.rsplit("/", 1)[-1]
    return (name in {".env", "local.properties", "google-services.json", "signing.properties"}
            or any(part in name for part in SENSITIVE_NAMES)
            or "/.env." in low)


def _allowed(rel: str) -> bool:
    return rel in ALLOWED_ROOT_FILES or (rel.startswith(ALLOWED_PREFIXES) and not rel.startswith(EXCLUDED_PREFIXES))


def _looks_text(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False
    sample = path.read_bytes()[:8192]
    return b"\x00" not in sample


COHERENCE_VERSION = "DA-BYTE-COHERENCE-1"
RUNTIME_CONTRACT_VERSION = "DA-COHERENCE-1"


def _file_record(rel, source, candidate, classification):
    return {"path": rel.replace("\\", "/"), "size": source.stat().st_size,
            "source_before_sha256": _sha256(source),
            "candidate_sha256": _sha256(candidate),
            "source_after_sha256": _sha256(source),
            "sha256": _sha256(candidate), "classification": classification}


def _publish_candidate(candidate: Path):
    backup = SNAPSHOT_ROOT.with_name(SNAPSHOT_ROOT.name + ".backup")
    try:
        if backup.exists():
            shutil.rmtree(backup)
        if SNAPSHOT_ROOT.exists():
            SNAPSHOT_ROOT.replace(backup)
        candidate.replace(SNAPSHOT_ROOT)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        try:
            if SNAPSHOT_ROOT.exists():
                shutil.rmtree(SNAPSHOT_ROOT)
            if backup.exists():
                backup.replace(SNAPSHOT_ROOT)
        except Exception as rollback_error:
            raise RuntimeError(f"SNAPSHOT_PUBLICATION_ROLLBACK_FAILED:{rollback_error}")
        raise


def create_snapshot(deadline=None, phase_callback=None, checkpoint=None) -> dict:
    state_before = capture_repo_state(deadline=deadline, phase_callback=phase_callback, trace_path=checkpoint, capture_generation="BEFORE")
    tracked = set(state_before["tracked"])
    candidates = []
    excluded = {"sensitive": [], "policy": [], "binary": [], "unsafe": []}
    reparses = []
    for rel in sorted(tracked):
        _remaining(deadline)
        source = REPO / rel
        if _is_reparse(source):
            reparses.append(rel)
            excluded["unsafe"].append(rel)
            continue
        if _is_sensitive(rel):
            excluded["sensitive"].append(rel)
            continue
        if not _allowed(rel):
            excluded["policy"].append(rel)
            continue
        if not source.is_file() or not _looks_text(source):
            excluded["binary"].append(rel)
            continue
        size = source.stat().st_size
        if size > MAX_FILE_BYTES:
            raise RuntimeError(f"FILE_SIZE_LIMIT:{rel}:{size}")
        candidates.append((rel, source, size))

    excluded_untracked = []
    potential_untracked = []
    for rel in state_before["untracked"]:
        if _is_sensitive(rel):
            excluded_untracked.append({"path": rel, "classification": "EXCLUDED_SENSITIVE"})
        elif rel in APPROVED_UNTRACKED:
            potential_untracked.append({"path": rel, "classification": "POTENTIAL_SOURCE_REQUIRES_APPROVAL"})
        else:
            excluded_untracked.append({"path": rel, "classification": "EXCLUDED_POLICY"})

    for rel in sorted(APPROVED_UNTRACKED):
        _remaining(deadline)
        source = REPO / rel
        if not source.is_file() or _is_reparse(source) or _is_sensitive(rel) or not _looks_text(source):
            raise RuntimeError(f"APPROVED_UNTRACKED_INVALID:{rel}")
        size = source.stat().st_size
        if size > MAX_FILE_BYTES:
            raise RuntimeError(f"FILE_SIZE_LIMIT:{rel}:{size}")
        candidates.append((rel, source, size))

    total = sum(size for _, _, size in candidates)
    if len(candidates) > MAX_FILE_COUNT or total > MAX_TOTAL_BYTES:
        raise RuntimeError(f"SNAPSHOT_LIMIT:{len(candidates)}:{total}")

    candidate_root = SNAPSHOT_ROOT.with_name(SNAPSHOT_ROOT.name + ".candidate")
    if candidate_root.exists():
        shutil.rmtree(candidate_root)
    candidate_root.mkdir(parents=True)
    files = []
    before_hashes = {}
    before_hash_started = time.monotonic()
    for rel, source, _ in candidates:
        _remaining(deadline)
        before_hashes[rel] = _sha256(source)
    before_hash_ms = int((time.monotonic() - before_hash_started) * 1000)
    copy_started = time.monotonic()
    for rel, source, size in candidates:
        _remaining(deadline)
        target = candidate_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    copy_ms = int((time.monotonic() - copy_started) * 1000)
    candidate_hash_started = time.monotonic()
    candidate_hashes = {rel: _sha256(candidate_root / rel) for rel, _, _ in candidates}
    candidate_hash_ms = int((time.monotonic() - candidate_hash_started) * 1000)

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
    after_hash_started = time.monotonic()
    state_after = capture_repo_state(deadline=deadline, phase_callback=phase_callback, trace_path=checkpoint, capture_generation="AFTER")
    after_hashes = {rel: _sha256(source) for rel, source, _ in candidates}
    after_hash_ms = int((time.monotonic() - after_hash_started) * 1000)
    for rel, source, size in candidates:
        files.append({"path": rel.replace("\\", "/"), "size": size,
                      "source_before_sha256": before_hashes[rel],
                      "candidate_sha256": candidate_hashes[rel],
                      "source_after_sha256": after_hashes[rel],
                      "sha256": candidate_hashes[rel],
                      "classification": "TRACKED_MODIFIED" if rel in state_before["tracked_modified"] else "TRACKED_CLEAN"})
    manifest["files"] = files
    manifest["file_count"] = len(files)
    validation_started = time.monotonic()
    mismatches = [rel for rel in sorted(before_hashes) if not (before_hashes[rel] == candidate_hashes[rel] == after_hashes[rel])]
    comparable = ("branch", "head", "upstream", "worktree_changes", "index_changes", "tracked", "untracked", "dirty")
    repo_validation_ms = int((time.monotonic() - validation_started) * 1000)
    if mismatches or any(state_before[key] != state_after[key] for key in comparable):
        manifest["coherence_status"] = "BLOCKED"
        (candidate_root / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise RuntimeError("SNAPSHOT_SOURCE_CHANGED_DURING_CAPTURE")
    manifest["coherence_status"] = "PASS"
    (candidate_root / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    publication_started = time.monotonic()
    _publish_candidate(candidate_root)
    publication_ms = int((time.monotonic() - publication_started) * 1000)
    _remaining(deadline)
    audit = {"schema": "deputy.recon.snapshot-coherence.v1", "coherence_version": COHERENCE_VERSION, "state_before": state_before, "state_after": state_after, "excluded": excluded, "untracked_classification": excluded_untracked + potential_untracked, "reparse_points": reparses, "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_file_count": MAX_FILE_COUNT, "max_total_bytes": MAX_TOTAL_BYTES}, "provider_exposure": DEPUTY_SHELL_PROVIDER_EXPOSURE, "timings_ms": {"before_hash_ms": before_hash_ms, "copy_ms": copy_ms, "candidate_hash_ms": candidate_hash_ms, "after_hash_ms": after_hash_ms, "repo_validation_ms": repo_validation_ms, "publication_ms": publication_ms, "total_refresh_ms": int((time.monotonic() - before_hash_started) * 1000)}}
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_ROOT / "repo-state-and-audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return {"manifest": manifest, "audit": audit, "snapshot": str(SNAPSHOT_ROOT), "coherence": "PASS", "runtime_contract_version": RUNTIME_CONTRACT_VERSION}


if __name__ == "__main__":
    print(json.dumps(create_snapshot(), indent=2))
