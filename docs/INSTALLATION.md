# Install Deputy Shell MCP

This guide installs Workers `1.2.0b1` and the Agents `1.0.0` companion package.
Both are available from the [Focused A4 Beta prerelease](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1).
The six download links below point to that exact immutable release.
These commands do not select a similarly named project from a package index.

The package archives and tagged documentation are frozen snapshots from before
publication. Their embedded READMEs may still say "candidate" or "pending".
Use this current repository guide for download status and installation; those
historical words do not mean the published files are unavailable. Do not replace
release assets to update their embedded wording.

## Prerequisites

- Python **3.10+**, with `venv` and pip. Windows qualification uses CPython
  3.10; Ubuntu/WSL compatibility was checked on CPython 3.12. Not every version
  or platform has been individually qualified.
- Git available to the server, and a local Git repository you control.
- Agents additionally needs Docker running Linux containers, the pinned images
  below and provider connectivity. Host OpenCode is unnecessary.
- Android capabilities need separately configured Android SDK/ADB and an
  authorized target. Repository-only Workers use needs no SDK or device.
- A stdio MCP host; effectful A4 additionally needs the
  [interactive approval behavior](MCP_HOST_SETUP.md).

Use **separate virtual environments** for Agents and Workers. Both distributions
provide top-level `server`, `config` and `preflight` modules and can overwrite
each other if installed together. Avoid system Python installation.

## Check the files

Download these six assets into one directory. Wheels are recommended for
installation; the source archives are alternatives. The checksum commands below
verify all four package files, so keep both archives for that complete check.

| File | Download |
| --- | --- |
| `deputy_workers_mcp-1.2.0b1-py3-none-any.whl` | [Download](https://github.com/Simon95277/Deputy-Shell-MCP/releases/download/workers-v1.2.0b1/deputy_workers_mcp-1.2.0b1-py3-none-any.whl) |
| `deputy_workers_mcp-1.2.0b1.tar.gz` | [Download](https://github.com/Simon95277/Deputy-Shell-MCP/releases/download/workers-v1.2.0b1/deputy_workers_mcp-1.2.0b1.tar.gz) |
| `deputy_shell_agents_mcp-1.0.0-py3-none-any.whl` | [Download](https://github.com/Simon95277/Deputy-Shell-MCP/releases/download/workers-v1.2.0b1/deputy_shell_agents_mcp-1.0.0-py3-none-any.whl) |
| `deputy_shell_agents_mcp-1.0.0.tar.gz` | [Download](https://github.com/Simon95277/Deputy-Shell-MCP/releases/download/workers-v1.2.0b1/deputy_shell_agents_mcp-1.0.0.tar.gz) |
| `SHA256SUMS.txt` | [Download](https://github.com/Simon95277/Deputy-Shell-MCP/releases/download/workers-v1.2.0b1/SHA256SUMS.txt) |
| `release-manifest.json` | [Download](https://github.com/Simon95277/Deputy-Shell-MCP/releases/download/workers-v1.2.0b1/release-manifest.json) |

```text
deputy_workers_mcp-1.2.0b1-py3-none-any.whl
deputy_workers_mcp-1.2.0b1.tar.gz
deputy_shell_agents_mcp-1.0.0-py3-none-any.whl
deputy_shell_agents_mcp-1.0.0.tar.gz
SHA256SUMS.txt
release-manifest.json
```

PowerShell: compare each displayed hash with `SHA256SUMS.txt`:

```powershell
Get-FileHash .\deputy_workers_mcp-1.2.0b1-py3-none-any.whl -Algorithm SHA256
Get-FileHash .\deputy_shell_agents_mcp-1.0.0-py3-none-any.whl -Algorithm SHA256
Get-FileHash .\deputy_workers_mcp-1.2.0b1.tar.gz -Algorithm SHA256
Get-FileHash .\deputy_shell_agents_mcp-1.0.0.tar.gz -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Linux: verify all four package files together:

```bash
sha256sum --check SHA256SUMS.txt
```

Stop on a mismatch. Obtain checksums from the reviewed release, not an untrusted
mirror; a hash alone does not authenticate its publisher.

## Windows wheels

Run from the download directory. These steps use the Python launcher and do
not require activation or a system PATH change:

```powershell
$deputyBase = Join-Path $env:LOCALAPPDATA "DeputyMCP"
New-Item -ItemType Directory -Force $deputyBase | Out-Null
py -3.10 -m venv (Join-Path $deputyBase "workers-venv")
py -3.10 -m venv (Join-Path $deputyBase "agents-venv")
$workersPython = Join-Path $deputyBase "workers-venv\Scripts\python.exe"
$agentsPython = Join-Path $deputyBase "agents-venv\Scripts\python.exe"
& $workersPython -m pip install "mcp==2.2.0" .\deputy_workers_mcp-1.2.0b1-py3-none-any.whl
& $agentsPython -m pip install "mcp==2.2.0" .\deputy_shell_agents_mcp-1.0.0-py3-none-any.whl
& $workersPython -m pip check
& $agentsPython -m pip check
```

Use new environment names if those paths already contain another version.
Install only the component you need. MCP 2.2.0 is the qualification version;
metadata permits `mcp>=2,<3`. For the exact Windows qualification resolution,
add `--constraint constraints/qualification-windows-py310.txt` from a reviewed
checkout to each install command. That file is not a release asset or a Linux lock.

Configure Workers **before** its health check. Replace the example repository
path with an existing Git repository under your control:

```powershell
$sourceRepo = (Resolve-Path "C:\Projects\your-repository").Path
$workersRuntime = Join-Path $deputyBase "workers-state"
New-Item -ItemType Directory -Force $workersRuntime | Out-Null
$env:DEPUTYWORKERS_DEPUTY_SHELL_ROOT = $sourceRepo
$env:DEPUTYWORKERS_RUNTIME_ROOT = $workersRuntime
$env:DEPUTYWORKERS_EVIDENCE_ROOT = Join-Path $workersRuntime "evidence"
$env:DEPUTYWORKERS_PYTHON_EXE = $workersPython
$env:DEPUTYWORKERS_ENABLE_CONTROL_PLANE = "0"
$env:DEPUTYWORKERS_PROTOCOL_MODE = "legacy"
& (Join-Path $deputyBase "workers-venv\Scripts\deputy-workers-mcp.exe") --check
```

For Agents, complete the Docker/source-policy prerequisites below, then:

```powershell
$agentsRuntime = Join-Path $deputyBase "agents-state"
New-Item -ItemType Directory -Force $agentsRuntime | Out-Null
$env:DEPUTYAGENTS_DEPUTY_SHELL_ROOT = $sourceRepo
$env:DEPUTYAGENTS_RUNTIME_ROOT = $agentsRuntime
$env:DEPUTYAGENTS_DOCKER_EXE = (Get-Command docker).Source
$env:DEPUTYAGENTS_ENABLE_DIAGNOSTICS = "0"
$env:DEPUTYAGENTS_ENABLE_CONTROL_PLANE = "0"
& (Join-Path $deputyBase "agents-venv\Scripts\deputy-agents-mcp.exe") --check
```

## Linux wheels

Ensure Python includes `venv` support; some distributions ship it as a separate
OS package. Run from the download directory:

```bash
deputy_base="${XDG_DATA_HOME:-$HOME/.local/share}/deputy-mcp"
mkdir -p "$deputy_base"
python3 -m venv "$deputy_base/workers-venv"
python3 -m venv "$deputy_base/agents-venv"
workers_python="$deputy_base/workers-venv/bin/python"
agents_python="$deputy_base/agents-venv/bin/python"
"$workers_python" -m pip install 'mcp==2.2.0' ./deputy_workers_mcp-1.2.0b1-py3-none-any.whl
"$agents_python" -m pip install 'mcp==2.2.0' ./deputy_shell_agents_mcp-1.0.0-py3-none-any.whl
"$workers_python" -m pip check
"$agents_python" -m pip check
```

Replace the example source path before running:

```bash
source_repo="$(realpath /path/to/your/repository)"
workers_runtime="${XDG_STATE_HOME:-$HOME/.local/state}/DeputyWorkersMCP"
mkdir -p "$workers_runtime"
export DEPUTYWORKERS_DEPUTY_SHELL_ROOT="$source_repo"
export DEPUTYWORKERS_RUNTIME_ROOT="$workers_runtime"
export DEPUTYWORKERS_EVIDENCE_ROOT="$workers_runtime/evidence"
export DEPUTYWORKERS_PYTHON_EXE="$workers_python"
export DEPUTYWORKERS_ENABLE_CONTROL_PLANE=0
export DEPUTYWORKERS_PROTOCOL_MODE=legacy
"$deputy_base/workers-venv/bin/deputy-workers-mcp" --check
```

For Agents, after the prerequisites below:

```bash
agents_runtime="${XDG_STATE_HOME:-$HOME/.local/state}/DeputyShellAgentsMCP"
mkdir -p "$agents_runtime"
export DEPUTYAGENTS_DEPUTY_SHELL_ROOT="$source_repo"
export DEPUTYAGENTS_RUNTIME_ROOT="$agents_runtime"
export DEPUTYAGENTS_DOCKER_EXE="$(command -v docker)"
export DEPUTYAGENTS_ENABLE_DIAGNOSTICS=0
export DEPUTYAGENTS_ENABLE_CONTROL_PLANE=0
"$deputy_base/agents-venv/bin/deputy-agents-mcp" --check
```

In WSL, keep virtual environments on the Linux filesystem if the Windows-mounted
drive cannot create Linux symlinks. Keep runtime data outside installed code.

## Source distribution alternative

In a **new environment**, replace the wheel argument in the corresponding pip
command with `./deputy_workers_mcp-1.2.0b1.tar.gz` or
`./deputy_shell_agents_mcp-1.0.0.tar.gz`; PowerShell also accepts these slashes.
Keep `mcp==2.2.0` in the command. Pip builds a wheel using the declared setuptools
backend, requiring build dependencies or an operator-prepared wheelhouse. Use
the same configuration and health checks afterward. Sdists contain declared
test sources, not a live target repository or SDK.

For development and deterministic build qualification see
[Contributing](../CONTRIBUTING.md) and [CI](CI.md). The Windows checkout helper
`scripts/install.ps1` installs local source; it is not the release-asset installer.

## Agents prerequisites and source selection

Docker must run Linux containers. Check `docker version` and `docker info`
locally. The installed runtime fixes these image references; the Python wheel
does not contain the images:

```text
ghcr.io/anomalyco/opencode@sha256:0d3c9551ea2522fcfd23fbc2e302fc87218d6c198bff277e8ab44d93a3bd6d3d
ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029
```

The operator may pre-pull them using `docker pull <exact-reference>`. First-use
download can need network access and disk space. A Python health check does not
prove image availability, container startup or provider availability. The server
fails closed if the configured provider route cannot run.

The default policy is tailored to Deputy Shell, not every tracked file in every
repository. For another layout, the trusted operator can supply a complete,
bounded policy through `DEPUTYAGENTS_SOURCE_POLICY_JSON`, for example:

```json
{"schema":"deputy.agents.source-policy.v1","policy_id":"EXAMPLE_SOURCE_V1","allowed_prefixes":["src/","docs/"],"allowed_root_files":["README.md"],"excluded_prefixes":[],"approved_untracked":[],"limits":{"max_file_bytes":1048576,"max_file_count":1000,"max_total_bytes":10485760}}
```

Supply this as a **server environment value** in the MCP registration. Review
those paths for provider exposure. Untracked files are denied unless explicitly
approved, and hard secret/sensitive-name/binary/link rules remain in force. No
MCP request or goal may choose a policy path or source root. See
[Agents architecture](../agents/docs/ARCHITECTURE.md).

## Register and opt in

Put the same environment values in the MCP host registration: a GUI host may
not inherit an existing terminal's exports. Register the absolute installed
console path with no authority arguments. See [host setup](MCP_HOST_SETUP.md).

Legacy Workers is default. For A4 set `DEPUTYWORKERS_PROTOCOL_MODE=focused-a4-beta`
and one supported `DEPUTYWORKERS_A4_PROFILE`, then start a fresh server connection.
Do not change profiles underneath live intents. See the [A4 guide](../workers/docs/A4_USER_GUIDE.md).

## Common errors and recovery

| Symptom/code | Check or action |
| --- | --- |
| `DEPUTY_SHELL_ROOT_UNAVAILABLE` | Use an existing directory; repository operations also need a Git repository. |
| `RUNTIME_ROOT_PARENT_UNWRITABLE` | Create a writable runtime directory or parent outside the package before `--check`. |
| `TRUSTED_PYTHON_UNAVAILABLE` | Set Workers' absolute Python executable from its own environment. |
| `DOCKER_EXECUTABLE_UNAVAILABLE` | Set the absolute Docker executable or expose it on the server's PATH. |
| `PROTOCOL_MODE_INVALID` / `A4_PROFILE_INVALID` | Use exact mode/profile spellings and restart the connection. |
| Missing A4 tools or zero tools | Inspect first-connection discovery, stderr and duplicate runtime-root use; see the host guide's Codex limitation. |
| `TARGET_NOT_REGISTERED` | Configure the exact authorized alias locally; never guess another device. |
| `APPROVED_ARTIFACT_UNAVAILABLE` | Check the fixed registered APK path is a regular non-linked file. |
| `CHOICE_PENDING` | Resolve the displayed choice with the operator, wait for expiry or deliberately recover locally; do not substitute a new request. |
| `OUTCOME_UNCERTAIN` / lost action response | Stop and inspect local evidence and target state before authorizing equivalent work. Do not automatically retry. |

`--check` is read-only. It does not install tools, pull images, start a device,
execute a verifier or request inference. Workers reports SDK/ADB availability
but does not qualify Android operations. Keep local evidence out of public reports.

For rollback, stop the server and register the previous verified environment and
configuration. Preserve local receipts and the installed environment for
diagnosis. Restart revokes prepared intents; it does not make an uncertain
operation safe to repeat. Package rollback cannot undo a device action. Do not
overwrite a public package or release to fix it.
