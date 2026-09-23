from __future__ import annotations

import re
import time
from pathlib import Path
from source_policy import POLICY_VERSION


SECRET_DETECTOR_VERSION = "DA-HIGH-CONFIDENCE-SECRETS-1"
PRIVACY_CONTRACT_VERSION = "DA-PRIVACY-1"
TRUST_MODEL = "TRUSTED_SINGLE_OPERATOR_V1"
MAX_SCAN_FILE_BYTES = 10 * 1024 * 1024

# Patterns intentionally target credential-shaped material, not generic words.
_DETECTORS = (
    ("PRIVATE_KEY_PEM", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("BEARER_CREDENTIAL", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}")),
    ("STRIPE_LIVE_KEY", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("OPENAI_API_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{24,}\b")),
    ("ANTHROPIC_API_KEY", re.compile(r"\bsk-ant-api[0-9]{2}-[A-Za-z0-9_-]{24,}\b")),
    ("GITLAB_TOKEN", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WINDOWS_HOME = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\")
_POSIX_HOME = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home)/[^/\s]+/")


class ContentPolicyBlocked(RuntimeError):
    """Safe public classification; never contains matched source content."""
    code = "SNAPSHOT_CONTENT_POLICY_BLOCKED"


def scan_candidate(candidate_root: Path, records: list[dict], checkpoint=None) -> dict:
    findings: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    scanned = 0
    for record in records:
        if checkpoint:
            checkpoint()
        rel = record["path"]
        path = candidate_root / rel
        size = path.stat().st_size
        if size > MAX_SCAN_FILE_BYTES:
            raise ContentPolicyBlocked("SNAPSHOT_CONTENT_POLICY_BLOCKED")
        data = path.read_bytes()
        if checkpoint:
            checkpoint()
        scanned += 1
        text = data.decode("utf-8", errors="replace")
        path_detector = next((detector_id for detector_id, pattern in _DETECTORS if pattern.search(rel)), None)
        for detector_id, pattern in _DETECTORS:
            if pattern.search(text):
                path_safe = rel
                for _, detector in _DETECTORS:
                    path_safe = detector.sub("[REDACTED]", path_safe)
                findings.append({"path": path_safe, "detector_id": path_detector or detector_id})
                break
        else:
            if path_detector:
                path_safe = rel
                for _, detector in _DETECTORS:
                    path_safe = detector.sub("[REDACTED]", path_safe)
                findings.append({"path": path_safe, "detector_id": path_detector})
        if _EMAIL.search(text):
            warnings.append({"path": rel, "warning_id": "EMAIL_ADDRESS_HEURISTIC"})
        if _WINDOWS_HOME.search(text) or _POSIX_HOME.search(text):
            warnings.append({"path": rel, "warning_id": "PERSONAL_ABSOLUTE_PATH_HEURISTIC"})
    return {"privacy_contract_version": PRIVACY_CONTRACT_VERSION,
            "source_policy_version": POLICY_VERSION,
            "secret_detector_version": SECRET_DETECTOR_VERSION,
            "candidate_files_scanned": scanned,
            "blocking_finding_count": len(findings),
            "blocking_findings": findings,
            "pii_warning_count": len(warnings),
            "pii_warnings": warnings,
            "trust_model": TRUST_MODEL,
            "status": "BLOCKED" if findings else "PASS"}


def public_error_code(exc: BaseException) -> str:
    if isinstance(exc, ContentPolicyBlocked):
        return ContentPolicyBlocked.code
    text = str(exc)
    if text == "PREPARATION_TIMEOUT":
        return "PREPARATION_TIMEOUT"
    if text.startswith("SOURCE_POLICY_"):
        return text.split(":", 1)[0][:64]
    return "CONTAINMENT_ERROR"
