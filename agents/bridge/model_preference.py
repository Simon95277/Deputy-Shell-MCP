from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import MODEL_SELECTION_PATH


SCHEMA = "deputy.agents.model-selection.v1"
_MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_LOCK = threading.RLock()


class ModelPreferenceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def load_model_id() -> str | None:
    """Read the persistent model preference without returning filesystem details."""
    with _LOCK:
        path = Path(MODEL_SELECTION_PATH)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise ModelPreferenceError("MODEL_SELECTION_STATE_INVALID") from None
        if (
            not isinstance(value, dict)
            or value.get("schema") != SCHEMA
            or value.get("provider_id") != "opencode"
            or not isinstance(value.get("model_id"), str)
            or not _MODEL_ID_RE.fullmatch(value["model_id"])
            or not isinstance(value.get("selected_at_utc"), str)
        ):
            raise ModelPreferenceError("MODEL_SELECTION_STATE_INVALID")
        return value["model_id"]


def save_model_id(model_id: str) -> str:
    """Atomically save a validated model ID; no credentials or prompts are stored."""
    if not isinstance(model_id, str) or not _MODEL_ID_RE.fullmatch(model_id):
        raise ModelPreferenceError("MODEL_ID_INVALID")
    path = Path(MODEL_SELECTION_PATH)
    value = {
        "schema": SCHEMA,
        "provider_id": "opencode",
        "model_id": model_id,
        "selected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    temp_path: Path | None = None
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".model-selection-", suffix=".tmp", dir=path.parent)
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except Exception:
            raise ModelPreferenceError("MODEL_SELECTION_SAVE_FAILED") from None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
    return value["selected_at_utc"]
