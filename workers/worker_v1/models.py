from __future__ import annotations

TERMINAL = {"PASS", "FAIL", "BLOCKED", "UNPROVEN", "CONTRADICTION", "CANCELLED"}
ACTIVE = {"QUEUED", "RUNNING"}

def validate_job(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("job must be an object")
    allowed = {"schema", "duration_seconds", "outcome", "emit_stderr"}
    if set(value) - allowed:
        raise ValueError("W2 synthetic job contains unsupported fields")
    if value.get("schema") != "deputy.worker-w2-synthetic.v1":
        raise ValueError("unsupported W2 synthetic schema")
    duration = value.get("duration_seconds", 0.1)
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 <= duration <= 30:
        raise ValueError("duration_seconds must be between 0 and 30")
    outcome = value.get("outcome", "PASS")
    if outcome not in {"PASS", "FAIL"}:
        raise ValueError("outcome must be PASS or FAIL")
    if not isinstance(value.get("emit_stderr", False), bool):
        raise ValueError("emit_stderr must be boolean")
    return {"schema": value["schema"], "duration_seconds": float(duration), "outcome": outcome, "emit_stderr": value.get("emit_stderr", False)}
