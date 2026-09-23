# Deputy Shell Agents MCP

Install the Agents runtime into a dedicated Python 3.10+ virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .\agents
.venv\Scripts\deputy-agents-mcp --check
```

The installed command is independent of the source checkout and current working
directory. Configure the server-owned `DEPUTYAGENTS_*` environment variables
for the Deputy Shell checkout, Docker executable, and runtime/evidence roots.
The default runtime root is a per-user application-state directory outside the
installed package (`%LOCALAPPDATA%\DeputyShellAgentsMCP` on Windows,
`$XDG_STATE_HOME/DeputyShellAgentsMCP` on POSIX, or the platform application
support directory on macOS). `--check` is read-only.
