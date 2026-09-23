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

## Clean installation

Python 3.10 or newer is required. Agents and Workers are independent MCP
distributions and can use separate virtual environments. Install from a clean
checkout without changing directory into the runtime at execution time:

```powershell
python -m venv .venv-agents
.venv-agents\Scripts\python -m pip install .\agents
.venv-agents\Scripts\deputy-agents-mcp --check

python -m venv .venv-workers
.venv-workers\Scripts\python -m pip install .\workers
.venv-workers\Scripts\deputy-workers-mcp --check
```

Configure the server-owned environment before starting MCP. Agents requires
Docker, Git, and `DEPUTYAGENTS_DEPUTY_SHELL_ROOT`; Workers requires the
Deputy Shell checkout, trusted Python, and Android SDK/ADB for device-bound
operations. Runtime state is outside the installed package by default:

- Agents: `%LOCALAPPDATA%\DeputyShellAgentsMCP` on Windows;
- Workers: `%LOCALAPPDATA%\DeputyWorkersMCP` on Windows;
- POSIX uses `$XDG_STATE_HOME` or `~/.local/state`, and macOS uses its
  application-support directory.

Deployment-only overrides include `DEPUTYAGENTS_RUNTIME_ROOT`,
`DEPUTYAGENTS_EVIDENCE_ROOT`, `DEPUTYAGENTS_JOB_STATE_ROOT`,
`DEPUTYAGENTS_SNAPSHOT_ROOT`, `DEPUTYAGENTS_DEPUTY_SHELL_ROOT`,
`DEPUTYAGENTS_DOCKER_EXE`, and the corresponding `DEPUTYWORKERS_*` values.
MCP callers cannot set these roots. `--check` validates prerequisites without
installing tools, pulling images, changing PATH, or performing device actions.

Hermes is not required. Any compatible MCP host that can launch the stdio
entrypoints may host these servers. Agents uses the server-owned digest-pinned
OpenCode container; a separate host OpenCode installation is not required.
The source repository and optional `DEPUTYAGENTS_SOURCE_POLICY_JSON` are
server-owner configuration, never MCP parameters. The policy is a bounded
`deputy.agents.source-policy.v1` object; omitted configuration preserves the
qualified Deputy Shell allowlist.

Supported trust model: `TRUSTED_SINGLE_OPERATOR_V1`. The machine owner and
deployment configuration are trusted; MCP callers do not receive host
authority. This product is not a hostile multi-user or multi-tenant service
and does not provide per-user filesystem or credential isolation. Provider-
exposable snapshot source is sent to the configured inference provider as
needed. Secret scanning blocks documented high-confidence credential forms;
it is not comprehensive PII detection. Model output may quote qualified source
content, so bounded output length is not a confidentiality guarantee.

Use `scripts/install.ps1 -Component Agents` or `-Component Workers` for the
bounded Windows bootstrap. It creates a user-local venv, installs only the
selected local distribution, runs `pip check`, and never changes global Git or
PATH configuration.

## Dependency qualification

Both distributions declare the compatibility range `mcp>=2,<3` and qualify
against MCP `2.2.0`. The generated Windows CPython 3.10 qualification set is
in `constraints/qualification-windows-py310.txt`; the deterministic build
tool set is in `constraints/build-tools-windows-py310.txt`. Refresh these
files only from a clean resolver environment, record the Python/OS/architecture
matrix, and review the complete diff before accepting a new lock.
Release builds use `python -m build --dependency-constraints-txt
constraints/build-tools-windows-py310.txt` so isolated setuptools resolution is
bounded by the recorded build-tool set.

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
