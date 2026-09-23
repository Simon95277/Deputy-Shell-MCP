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

Hermes is not required; any compatible MCP host that launches the stdio
entrypoint may be used. Agents invokes the server-owned digest-pinned OpenCode
container, so a host OpenCode installation is not required. The supported
deployment is one trusted operator and one server-configured repository, not a
hostile multi-user/tenant service. The owner may supply a bounded
`deputy.agents.source-policy.v1` JSON object through
`DEPUTYAGENTS_SOURCE_POLICY_JSON`; no MCP caller can select a policy or path.
The default policy preserves the qualified Deputy Shell source set. A local
high-confidence content scan blocks selected credential forms before provider
setup; email/path heuristics are warnings, not comprehensive PII detection.
Provider-exposable source is externally exposed by design, and model output
may quote that source.
