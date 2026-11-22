from __future__ import annotations

import json
import re
from typing import Any


RUNTIME_CONTRACT_VERSION = "DA-PRIVACY-1"
MODEL_SELECTION_CONTRACT_VERSION = "DA-MODEL-CATALOG-1"
PROVIDER_ID = "opencode"
PROVIDER_HOST = "opencode.ai"
SELECTION_SOURCE = "MCP_CALLER_LIVE_ZERO_PRICE_CATALOG"
SELECTION_METHOD = "CATALOG_REVALIDATED_BEFORE_CLI_LAUNCH_AND_INLINE_CONFIG"

_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def model_selector(model_id: str) -> str:
    if not isinstance(model_id, str) or not _MODEL_RE.fullmatch(model_id):
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_INVALID_MODEL")
    return f"{PROVIDER_ID}/{model_id}"


def validate_contract(model_id: str | None = None) -> None:
    """Validate the fixed OpenCode route and, when supplied, a catalog model ID."""
    if not _PROVIDER_RE.fullmatch(PROVIDER_ID) or PROVIDER_ID != "opencode":
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_INVALID_PROVIDER")
    if PROVIDER_HOST != "opencode.ai":
        raise RuntimeError("PROVIDER_MODEL_CONTRACT_INVALID_HOST")
    if model_id is not None:
        model_selector(model_id)


def inline_config_content(model_id: str) -> str:
    """Return deterministic, secret-free config content owned by the server."""
    validate_contract(model_id)
    selector = model_selector(model_id)
    return json.dumps(
        {
            "model": selector,
            "agent": {"plan": {"model": selector}},
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def evidence(
    model_id: str | None = None,
    observed_provider: str | None = None,
    observed_model: str | None = None,
) -> dict[str, Any]:
    validate_contract(model_id)
    observable = bool(observed_provider and observed_model)
    matches = None
    if observable:
        matches = observed_provider == PROVIDER_ID and observed_model == model_id
    return {
        "model_selection_contract_version": MODEL_SELECTION_CONTRACT_VERSION,
        "provider_id": PROVIDER_ID,
        "model_id": model_id,
        "selection_source": SELECTION_SOURCE,
        "selection_method": SELECTION_METHOD,
        "provider_host": PROVIDER_HOST,
        "selection_enforced": model_id is not None,
        "runtime_identity_observable": observable,
        "observed_provider_id": observed_provider,
        "observed_model_id": observed_model,
        "observed_matches_configured": matches,
        "verified": bool(matches is True),
    }
