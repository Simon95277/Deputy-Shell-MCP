from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


BRIDGE_ROOT = configured_path("DEPUTYAGENTS_BRIDGE_ROOT", ROOT / "bridge-lab")
BRIDGE_FIXTURES = configured_path("DEPUTYAGENTS_BRIDGE_FIXTURES", BRIDGE_ROOT / "fixtures")
DEPUTY_SHELL_ROOT = configured_path("DEPUTYAGENTS_DEPUTY_SHELL_ROOT", ROOT / "deputy-shell-source")
EVIDENCE_ROOT = configured_path("DEPUTYAGENTS_EVIDENCE_ROOT", ROOT / "evidence")
JOB_STATE_ROOT = configured_path("DEPUTYAGENTS_JOB_STATE_ROOT", EVIDENCE_ROOT / "jobs")
SNAPSHOT_ROOT = configured_path("DEPUTYAGENTS_SNAPSHOT_ROOT", ROOT / "local-snapshots")
DOCKER_EXE = configured_path("DEPUTYAGENTS_DOCKER_EXE", Path("docker"))
