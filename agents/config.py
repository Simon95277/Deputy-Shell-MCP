from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def default_runtime_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "DeputyShellAgentsMCP"


PACKAGE_ROOT = ROOT
RUNTIME_ROOT = configured_path("DEPUTYAGENTS_RUNTIME_ROOT", default_runtime_root())
BRIDGE_ROOT = configured_path("DEPUTYAGENTS_BRIDGE_ROOT", RUNTIME_ROOT / "bridge")
BRIDGE_FIXTURES = configured_path("DEPUTYAGENTS_BRIDGE_FIXTURES", RUNTIME_ROOT / "bridge-fixtures")
DEPUTY_SHELL_ROOT = configured_path("DEPUTYAGENTS_DEPUTY_SHELL_ROOT", RUNTIME_ROOT / "deputy-shell-source")
EVIDENCE_ROOT = configured_path("DEPUTYAGENTS_EVIDENCE_ROOT", RUNTIME_ROOT / "evidence")
JOB_STATE_ROOT = configured_path("DEPUTYAGENTS_JOB_STATE_ROOT", EVIDENCE_ROOT / "jobs")
SNAPSHOT_ROOT = configured_path("DEPUTYAGENTS_SNAPSHOT_ROOT", RUNTIME_ROOT / "snapshots")
DOCKER_EXE = configured_path("DEPUTYAGENTS_DOCKER_EXE", Path("docker"))
