from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from config import ADB_EXE, ANDROID_SDK_ROOT, DEPUTY_SHELL_ROOT, RUNTIME_ROOT, TRUSTED_PYTHON
from worker_v1.capabilities import load_registry


def check() -> dict[str, object]:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("PYTHON_VERSION_UNSUPPORTED")
    if importlib.util.find_spec("mcp") is None:
        errors.append("MCP_IMPORT_UNAVAILABLE")
    try:
        registry = load_registry()
        capability_count = len(registry)
    except Exception as exc:
        capability_count = 0
        errors.append(f"CAPABILITY_REGISTRY:{exc}")
    if not DEPUTY_SHELL_ROOT.is_absolute() or not DEPUTY_SHELL_ROOT.is_dir():
        errors.append("DEPUTY_SHELL_ROOT_UNAVAILABLE")
    if not TRUSTED_PYTHON.is_absolute() or not TRUSTED_PYTHON.is_file():
        errors.append("TRUSTED_PYTHON_UNAVAILABLE")
    if not RUNTIME_ROOT.is_absolute():
        errors.append("RUNTIME_ROOT_NOT_ABSOLUTE")
    package_root = Path(__file__).resolve().parent
    if package_root in RUNTIME_ROOT.resolve().parents or RUNTIME_ROOT.resolve() == package_root:
        errors.append("RUNTIME_ROOT_INSIDE_PACKAGE")
    if not RUNTIME_ROOT.parent.is_dir() or not os.access(RUNTIME_ROOT.parent, os.W_OK):
        errors.append("RUNTIME_ROOT_PARENT_UNWRITABLE")
    return {
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "mcp_available": importlib.util.find_spec("mcp") is not None,
        "capability_count": capability_count,
        "adb_configured": ADB_EXE.is_absolute() and ADB_EXE.is_file(),
        "android_sdk_configured": ANDROID_SDK_ROOT.is_dir(),
        "runtime_root": str(RUNTIME_ROOT),
        "runtime_root_server_owned": True,
        "mutated_external_state": False,
    }
