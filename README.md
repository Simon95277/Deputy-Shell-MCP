# Deputy Shell MCP

Deputy Shell MCP provides two independent MCP runtimes for the Deputy Shell
project at [deputyshell.com](https://deputyshell.com).

> The model chooses intent. The server chooses authority.

## Agents

`agents/` runs independent, untrusted AI reconnaissance against a fresh,
sanitized, read-only snapshot. The live repository is not mounted. Docker
containment, provider-only egress, bounded lifecycle, and mandatory cleanup
protect host authority. Its findings are advisory evidence.

## Workers

`workers/` runs deterministic bounded operations through a fixed capability
registry, including approved Git, Gradle, JUnit, ADB, and verifier operations.
Typed evidence is mechanically checked. Selected operations may mutate device
state, but generic shell, arbitrary processes, arbitrary paths, and caller-
selected executables are not exposed.

The model chooses intent; the server chooses repository binding, executable,
parameters, and authority. Agents and Workers are separate MCP systems.

See `docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, and the subsystem
documentation for implementation details.

## Development

Create separate environments for the two runtimes. Agents declares `mcp>=2,<3`
in `agents/pyproject.toml`; Workers declares the same compatible range and
qualifies against MCP 2.2.0 in `workers/pyproject.toml`.

From `agents/`, install the project dependencies and run
`python -m unittest discover -s tests -q`. From `workers/`, install the
project dependencies, configure the server-owned `DEPUTYWORKERS_*` paths, and
run the same command. Runtime roots, snapshots, logs, and virtual environments
are ignored and must not be committed.
