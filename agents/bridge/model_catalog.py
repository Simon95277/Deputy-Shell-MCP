from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


CATALOG_URL = "https://opencode.ai/zen/v1/models"
CATALOG_TIMEOUT_SECONDS = 5
MAX_CATALOG_BYTES = 1_000_000
_MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class ModelCatalogError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _zero_price(value: object) -> bool:
    return type(value) in (int, float) and value == 0


def _zero_price_record(value: dict[str, object]) -> bool:
    if not _zero_price(value.get("price")):
        return False
    cache = value.get("cache")
    if cache is None:
        return True
    return isinstance(cache, dict) and all(_zero_price(amount) for amount in cache.values())


def _free_agent_models() -> list[dict[str, object]]:
    request = Request(CATALOG_URL, headers={"Accept": "application/json"}, method="GET")
    opener = build_opener(ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(request, timeout=CATALOG_TIMEOUT_SECONDS) as response:
            if response.geturl() != CATALOG_URL or response.status != 200:
                raise ModelCatalogError("MODEL_CATALOG_UNAVAILABLE")
            raw = response.read(MAX_CATALOG_BYTES + 1)
    except ModelCatalogError:
        raise
    except Exception:
        raise ModelCatalogError("MODEL_CATALOG_UNAVAILABLE") from None

    if len(raw) > MAX_CATALOG_BYTES:
        raise ModelCatalogError("MODEL_CATALOG_INVALID")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelCatalogError("MODEL_CATALOG_INVALID") from None
    entries = document.get("data") if isinstance(document, dict) else None
    if not isinstance(entries, list) or len(entries) > 5000:
        raise ModelCatalogError("MODEL_CATALOG_INVALID")

    models: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("owned_by") != "opencode":
            continue
        if not isinstance(entry.get("type"), str) or entry.get("type") not in {"chat", "decision"}:
            continue
        cost = entry.get("cost")
        text_cost = cost.get("text") if isinstance(cost, dict) else None
        input_cost = text_cost.get("input") if isinstance(text_cost, dict) else None
        output_cost = text_cost.get("output") if isinstance(text_cost, dict) else None
        if not isinstance(input_cost, dict) or not isinstance(output_cost, dict):
            continue
        if not _zero_price_record(input_cost) or not _zero_price_record(output_cost):
            continue

        model_id = entry.get("id")
        name = entry.get("name")
        if not isinstance(model_id, str) or not _MODEL_ID_RE.fullmatch(model_id):
            raise ModelCatalogError("MODEL_CATALOG_INVALID")
        if model_id in seen:
            raise ModelCatalogError("MODEL_CATALOG_INVALID")
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or not name.isprintable():
            raise ModelCatalogError("MODEL_CATALOG_INVALID")
        seen.add(model_id)

        capabilities = entry.get("capabilities")
        tools = capabilities.get("tools") if isinstance(capabilities, dict) else None
        tool_calling = isinstance(tools, dict) and tools.get("supported") is True
        model_type = entry["type"]
        models.append({
            "model_id": model_id,
            "name": name,
            "type": model_type,
            "input_price_per_million_usd": 0,
            "output_price_per_million_usd": 0,
            "recon_compatible": model_type == "chat" and tool_calling,
            "runner_image_compatibility": "NOT_VERIFIED",
        })

    models.sort(key=lambda item: str(item["model_id"]))
    if not models:
        raise ModelCatalogError("MODEL_CATALOG_INVALID")
    return models


def list_free_models() -> dict[str, object]:
    """Return OpenCode-owned chat/decision models with current zero token prices."""
    return {
        "status": "PASS",
        "provider": "opencode",
        "catalog_url": CATALOG_URL,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pricing_check": "text_input_output_and_listed_cache_prices_are_zero",
        "models": _free_agent_models(),
    }


def require_recon_model(model_id: str) -> dict[str, object]:
    if not isinstance(model_id, str) or not _MODEL_ID_RE.fullmatch(model_id):
        raise ModelCatalogError("MODEL_ID_INVALID")
    models = _free_agent_models()
    selected = next((item for item in models if item["model_id"] == model_id), None)
    if selected is None:
        raise ModelCatalogError("MODEL_NOT_CURRENTLY_FREE")
    if selected["recon_compatible"] is not True:
        raise ModelCatalogError("MODEL_NOT_RECON_COMPATIBLE")
    return {
        **selected,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
