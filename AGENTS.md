# Deputy Shell MCP umbrella instructions

This repository contains two authority domains:

- `agents/`: advisory AI reconnaissance over sanitized read-only snapshots;
- `workers/`: deterministic bounded execution with typed mechanical evidence.

Agents findings are advisory and untrusted. Workers results are deterministic
evidence. Callers do not control paths, executables, repositories, networks,
or authority. Missing capabilities fail closed.

Subsystem changes require that subsystem's tests. Cross-subsystem changes
require both suites. Read the relevant `AGENTS.md` and architecture document
before changing behavior.
