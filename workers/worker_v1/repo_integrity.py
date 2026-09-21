from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path


def _git(root: Path, *args: str) -> bytes:
    p = subprocess.run(["git", *args], cwd=str(root), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=True, shell=False)
    return p.stdout


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _status(root: Path) -> tuple[list[dict], set[str]]:
    raw = _git(root, "status", "--porcelain=v2", "-z")
    records = []
    untracked = set()
    for item in raw.split(b"\0"):
        if not item:
            continue
        text = item.decode("utf-8", "surrogateescape")
        if text.startswith("? "):
            untracked.add(text[2:])
            continue
        if text.startswith(("1 ", "2 ")):
            fields = text.split(" ")
            path = fields[-1]
            records.append({"path": path, "status": fields[1], "raw": text})
        elif text.startswith("u "):
            fields = text.split(" ")
            records.append({"path": fields[-1], "status": fields[1], "raw": text})
    return records, untracked


def _tracked_identity(root: Path, path: str) -> dict:
    candidate = root / Path(path)
    kind = "file" if candidate.is_file() else "directory" if candidate.is_dir() else "missing"
    return {"path": path, "kind": kind, "sha256": _sha(candidate),
            "mode": oct(candidate.stat().st_mode & 0o777) if candidate.exists() else None}


def capture_snapshot(repo_root: str | Path) -> dict:
    root = Path(repo_root).resolve()
    records, untracked = _status(root)
    dirty = {r["path"]: _tracked_identity(root, r["path"]) for r in records}
    staged_raw = _git(root, "diff", "--cached", "--binary", "--no-ext-diff")
    unstaged_raw = _git(root, "diff", "--binary", "--no-ext-diff")
    index_entries = _git(root, "ls-files", "-s", "-z").decode("utf-8", "surrogateescape")
    return {
        "schema": "deputy.repo-integrity-snapshot.v1",
        "repo_root": str(root),
        "head": _git(root, "rev-parse", "HEAD").decode().strip(),
        "branch": _git(root, "branch", "--show-current").decode().strip(),
        "upstream": _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").decode().strip()
        if subprocess.run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False).returncode == 0 else None,
        "tracked_delta": dirty,
        "staged_paths": sorted({line.rsplit("\t", 1)[-1] for line in staged_raw.decode("utf-8", "surrogateescape").splitlines() if line}),
        "index_sha256": hashlib.sha256(index_entries.encode("utf-8", "surrogateescape")).hexdigest(),
        "staged_diff_sha256": hashlib.sha256(staged_raw).hexdigest(),
        "unstaged_diff_sha256": hashlib.sha256(unstaged_raw).hexdigest(),
        "untracked": sorted(untracked),
        "observed_at": time.time(),
    }


def compare_snapshots(pre: dict, post: dict) -> dict:
    reasons = []
    def changed(a, b, code):
        if a != b: reasons.append(code); return True
        return False
    head = changed(pre.get("head"), post.get("head"), "HEAD_CHANGED")
    branch = changed(pre.get("branch"), post.get("branch"), "BRANCH_CHANGED")
    upstream = changed(pre.get("upstream"), post.get("upstream"), "UPSTREAM_CHANGED")
    staged = any(pre.get(k) != post.get(k) for k in ("staged_paths", "index_sha256", "staged_diff_sha256"))
    if staged: reasons.append("STAGED_STATE_CHANGED")
    unstaged = pre.get("unstaged_diff_sha256") != post.get("unstaged_diff_sha256")
    if unstaged: reasons.append("TRACKED_WORKTREE_STATE_CHANGED")
    paths = set(pre.get("tracked_delta", {})) | set(post.get("tracked_delta", {}))
    content = sorted(p for p in paths if pre.get("tracked_delta", {}).get(p) != post.get("tracked_delta", {}).get(p))
    if content: reasons.append("TRACKED_CONTENT_CHANGED")
    new_untracked = sorted(set(post.get("untracked", [])) - set(pre.get("untracked", [])))
    removed_untracked = sorted(set(pre.get("untracked", [])) - set(post.get("untracked", [])))
    if new_untracked: reasons.append("NEW_UNTRACKED_PATH")
    if removed_untracked: reasons.append("REMOVED_UNTRACKED_PATH")
    return {"same": not reasons, "head_changed": head, "branch_changed": branch,
            "upstream_changed": upstream, "staged_state_changed": staged,
            "unstaged_state_changed": unstaged,
            "tracked_paths_added_to_delta": sorted(set(post.get("tracked_delta", {})) - set(pre.get("tracked_delta", {}))),
            "tracked_paths_removed_from_delta": sorted(set(pre.get("tracked_delta", {})) - set(post.get("tracked_delta", {}))),
            "tracked_paths_content_changed": content, "new_untracked": new_untracked,
            "removed_untracked": removed_untracked, "reasons": reasons}
