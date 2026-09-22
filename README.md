# Deputy Shell MCP

Deputy Shell MCP provides two independent MCP runtimes for the Deputy Shell
project at [deputyshell.com](https://deputyshell.com).

> The model chooses intent. The server chooses authority.

## Agents

`agents/` runs independent, untrusted AI reconnaissance against a fresh,
sanitized, read-only snapshot. The live repository is not mounted. Docker
containment, provider-only egress, bounded lifecycle, and mandatory cleanup
protect host authority. Its findings are advisory evidence.

Agents uses the server-owned OpenCode contract `opencode` /
`muse-spark-1.3-contributor-free` through the digest-pinned image. The
provider/model selector is not caller-configurable, workspace configuration
cannot replace it, and no provider credential environment is forwarded. When
OpenCode does not emit identity fields, results report that limitation rather
than fabricating runtime verification.

The default Agents MCP surface contains the four reconnaissance lifecycle
tools: `deputy_recon`, `deputy_recon_start`, `deputy_recon_status`, and
`deputy_recon_cancel`. The fixed `deputy_child_ping` and `deputy_git_probe`
diagnostics are development-only and appear only when the server owner sets
`DEPUTYAGENTS_ENABLE_DIAGNOSTICS=1`; callers cannot enable them.

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

Qualification portability uses clean environments and the public dependency
metadata. Both runtimes target the official MCP v2 API and qualify against
MCP 2.2.0. Agents' child ping uses Python everywhere and a fixed native
diagnostic (`cmd.exe` on Windows, a server-owned POSIX equivalent elsewhere);
Workers' subprocess interpreter is server-owned and defaults to the trusted
server interpreter. Windows process-identity guarantees remain physical-host
qualifications and are not fabricated on hosts that cannot provide them.
