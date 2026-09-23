from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def default_runtime_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "DeputyWorkersMCP"


PACKAGE_ROOT = ROOT
RUNTIME_ROOT = _path("DEPUTYWORKERS_RUNTIME_ROOT", default_runtime_root())
DEPUTY_SHELL_ROOT = _path("DEPUTYWORKERS_DEPUTY_SHELL_ROOT", RUNTIME_ROOT / "deputy-shell-source")
if os.name == "nt":
    _default_sdk = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Android" / "Sdk"
else:
    _default_sdk = Path.home() / "Android" / "Sdk"
ANDROID_SDK_ROOT = _path("DEPUTYWORKERS_ANDROID_SDK_ROOT", _default_sdk)
EVIDENCE_ROOT = _path("DEPUTYWORKERS_EVIDENCE_ROOT", RUNTIME_ROOT / "evidence")
TRUSTED_PYTHON = _path("DEPUTYWORKERS_PYTHON_EXE", Path(sys.executable))
ADB_EXE = _path("DEPUTYWORKERS_ADB_EXE", ANDROID_SDK_ROOT / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"))
