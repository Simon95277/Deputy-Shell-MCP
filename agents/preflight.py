from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

from config import DEPUTY_SHELL_ROOT, DOCKER_EXE, RUNTIME_ROOT
from bridge.provider_contract import MODEL_ID, PROVIDER_ID, validate_contract


def _executable_available(value: Path) -> bool:
    if value.parent != Path("."):
        return value.is_file()
    return shutil.which(str(value)) is not None


def check() -> dict[str, object]:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("PYTHON_VERSION_UNSUPPORTED")
    if importlib.util.find_spec("mcp") is None:
        errors.append("MCP_IMPORT_UNAVAILABLE")
    try:
        validate_contract()
    except Exception as exc:
        errors.append(f"PROVIDER_MODEL_CONTRACT:{exc}")
    if not _executable_available(DOCKER_EXE):
        errors.append("DOCKER_EXECUTABLE_UNAVAILABLE")
    if not _executable_available(Path("git")):
        errors.append("GIT_EXECUTABLE_UNAVAILABLE")
    if not DEPUTY_SHELL_ROOT.is_absolute() or not DEPUTY_SHELL_ROOT.is_dir():
        errors.append("DEPUTY_SHELL_ROOT_UNAVAILABLE")
    package_root = Path(__file__).resolve().parent
    runtime_root = RUNTIME_ROOT.resolve()
    if not RUNTIME_ROOT.is_absolute() or runtime_root == package_root or package_root in runtime_root.parents:
        errors.append("RUNTIME_ROOT_INSIDE_PACKAGE")
    if not RUNTIME_ROOT.parent.is_dir() or not os.access(RUNTIME_ROOT.parent, os.W_OK):
        errors.append("RUNTIME_ROOT_PARENT_UNWRITABLE")
    return {
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "mcp_available": importlib.util.find_spec("mcp") is not None,
        "provider": PROVIDER_ID,
        "model": MODEL_ID,
        "runtime_root": str(RUNTIME_ROOT),
        "runtime_root_server_owned": True,
        "mutated_external_state": False,
    }
