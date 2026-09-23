# Installation and qualification

Agents and Workers are separate Python distributions. They require Python
3.10 or newer and declare `mcp>=2,<3`; this repository qualifies both against
MCP 2.2.0 using the generated Windows CPython 3.10 constraint set.

## Runtime roots

Installed code is read-only with respect to its package directory. Agents
defaults to `%LOCALAPPDATA%\DeputyShellAgentsMCP` on Windows and Workers to
`%LOCALAPPDATA%\DeputyWorkersMCP`. POSIX uses `$XDG_STATE_HOME` or
`~/.local/state`; macOS uses its application-support directory. Evidence,
durable job state, snapshots, generated proxy configuration, and logs belong
under these server-owned roots. Deployment may override the documented
`DEPUTYAGENTS_*` or `DEPUTYWORKERS_*` variables; MCP callers cannot provide
host paths.

## Windows bootstrap

From a source checkout:

```powershell
.\scripts\install.ps1 -Component Agents
.\scripts\install.ps1 -Component Workers
```

The helper uses a user-local venv, installs the selected local distribution,
runs `pip check`, and does not install Docker, Android SDK, arbitrary binaries,
global PATH entries, or Git configuration. It refuses to overwrite an existing
venv unless `-ConfirmReplace` is supplied.

## Preflight and MCP host configuration

After setting server-owned prerequisites, run:

```powershell
deputy-agents-mcp --check
deputy-workers-mcp --check
```

Point the MCP host at the installed console command, not `server.py` and not a
repository-relative working directory. The commands accept no authority
options; `--check` is the only supported option and is read-only.

## Lock refresh

To refresh qualification constraints intentionally, create a clean CPython
environment for each supported OS/Python/architecture combination, install
`mcp==2.2.0` plus the selected build tools, record `pip freeze`, and review
the complete generated file. Do not merge platform-specific resolutions into
a universal lock. For release qualification, pass
`--dependency-constraints-txt constraints/build-tools-windows-py310.txt` to
`python -m build` so the isolated build environment uses the recorded
setuptools/build-tool resolution. Consumer metadata remains the compatibility
range rather than the qualification lock.
