from __future__ import annotations

import json
import re
from typing import Any


RUNTIME_CONTRACT_VERSION = "DA-PROVIDER-1"
PROVIDER_ID = "opencode"
MODEL_ID = "muse-spark-1.3-contributor-free"
PROVIDER_HOST = "opencode.ai"
SELECTION_SOURCE = "SERVER_OWNED"
SELECTION_METHOD = "CLI_MODEL_AND_INLINE_SERVER_CONFIG"
MODEL_SELECTOR = f"{PROVIDER_ID}/{MODEL_ID}"

_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def validate_contract() -> None:
    """Reject any incomplete or altered server-owned inference contract."""
    if not _PROVIDER_RE.fullmatch(PROVIDER_ID) or PROVIDER_ID != "opencode":
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_INVALID_PROVIDER")
    if not _MODEL_RE.fullmatch(MODEL_ID) or MODEL_ID != "muse-spark-1.3-contributor-free":
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_INVALID_MODEL")
    if PROVIDER_HOST != "opencode.ai":
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_INVALID_HOST")
    if MODEL_SELECTOR != f"{PROVIDER_ID}/{MODEL_ID}":
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_SELECTOR_MISMATCH")


def inline_config_content() -> str:
    """Return deterministic, secret-free config content owned by the server."""
    validate_contract()
    return json.dumps(
        {
            "model": MODEL_SELECTOR,
            "agent": {"plan": {"model": MODEL_SELECTOR}},
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def evidence(observed_provider: str | None = None, observed_model: str | None = None) -> dict[str, Any]:
    validate_contract()
    observable = bool(observed_provider and observed_model)
    matches = None
    if observable:
        matches = observed_provider == PROVIDER_ID and observed_model == MODEL_ID
    return {
        "provider_id": PROVIDER_ID,
        "model_id": MODEL_ID,
        "selection_source": SELECTION_SOURCE,
        "selection_method": SELECTION_METHOD,
        "provider_host": PROVIDER_HOST,
        "selection_enforced": True,
        "runtime_identity_observable": observable,
        "observed_provider_id": observed_provider,
        "observed_model_id": observed_model,
        "observed_matches_configured": matches,
        "verified": bool(matches is True),
    }
